"""Isolated subprocess adapter for MinerU 2.x `pipeline` backend (strictly no vLLM/sglang)."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from typing import Callable

import pymupdf as fitz

logger = logging.getLogger(__name__)

# Global GPU concurrency guard: strictly 1 MinerU subprocess at a time on RTX 4070 Super (12GB)
_GPU_SEMAPHORE = threading.Semaphore(1)

FORBIDDEN_BACKENDS = frozenset(
    {
        "vlm",
        "vlm-vllm-engine",
        "vlm-sglang-engine",
        "vlm-sglang-client",
        "vlm-transformers",
        "vlm-http-client",
    }
)


class MinerUUnavailableError(RuntimeError):
    """Raised when the local MinerU CLI executable is not installed or accessible."""


class MinerUExecutionError(RuntimeError):
    """Raised when MinerU pipeline execution fails after all retry/fallback tiers."""


@dataclass
class MinerUResult:
    """Merged MinerU output across all 10-page chunks."""

    pdf_info: list[dict] = field(default_factory=list)
    content_list: list[dict] = field(default_factory=list)
    images_dir: Path | None = None
    parser_name: str = "mineru-2.x/pipeline"
    used_cpu_fallback: bool = False


ProgressHook = Callable[[str, float, int, int, str], None]


def find_mineru_executable(explicit_bin: str | Path | None = None) -> Path | None:
    """Locate the local `mineru` CLI binary (Linux & Windows) without importing torch."""
    candidates: list[Path] = []
    if explicit_bin:
        candidates.append(Path(explicit_bin))
    env_bin = os.environ.get("MINERU_BIN")
    if env_bin:
        candidates.append(Path(env_bin))
    env_py = os.environ.get("INKCRAFT_MINERU_PYTHON")
    if env_py:
        py_dir = Path(env_py).expanduser().resolve().parent
        candidates.extend([py_dir / "mineru.exe", py_dir / "mineru", py_dir / "magic-pdf.exe", py_dir / "magic-pdf"])
    # Optional isolated runtime venv inside project root (Linux bin/ & Windows Scripts/)
    repo_root = Path(__file__).resolve().parents[3]
    for base in (repo_root / "runtime" / "mineru-venv", repo_root / ".venv-mineru", repo_root / ".venv"):
        candidates.extend([
            base / "Scripts" / "mineru.exe",
            base / "Scripts" / "magic-pdf.exe",
            base / "bin" / "mineru",
            base / "bin" / "magic-pdf",
        ])

    for cand in candidates:
        if cand.is_file() and (os.name == "nt" or os.access(cand, os.X_OK)):
            return cand

    for cmd in ("mineru", "magic-pdf"):
        which = shutil.which(cmd)
        if which:
            return Path(which)
    return None


def is_mineru_available(explicit_bin: str | Path | None = None) -> bool:
    """Return True if a local MinerU CLI binary is present."""
    return find_mineru_executable(explicit_bin) is not None


def _build_mineru_env(*, device_mode: str = "cuda", virtual_vram_gb: int = 8) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("MINERU_MODEL_SOURCE", "local")
    env["MINERU_DEVICE_MODE"] = device_mode
    env["MINERU_VIRTUAL_VRAM_SIZE"] = str(max(2, int(virtual_vram_gb)))
    env.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    env.setdefault("OMP_NUM_THREADS", "8")
    return env


def _split_pdf_chunk(src_doc: fitz.Document, start_page: int, end_page: int, dst_path: Path) -> None:
    chunk_doc = fitz.open()
    try:
        chunk_doc.insert_pdf(src_doc, from_page=start_page, to_page=end_page - 1)
        chunk_doc.save(str(dst_path))
    finally:
        chunk_doc.close()


def _invoke_mineru_chunk(
    mineru_bin: Path,
    chunk_pdf: Path,
    chunk_out_dir: Path,
    *,
    method: str,
    lang: str,
    device_mode: str,
    virtual_vram_gb: int,
    timeout_s: int,
) -> tuple[list[dict], list[dict]]:
    chunk_out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(mineru_bin),
        "-p",
        str(chunk_pdf),
        "-o",
        str(chunk_out_dir),
        "-b",
        "pipeline",  # Strictly locked to pipeline backend; vLLM/sglang forbidden
        "-m",
        method,
        "-l",
        lang,
        "--formula",
        "true",
        "--table",
        "true",
    ]
    env = _build_mineru_env(device_mode=device_mode, virtual_vram_gb=virtual_vram_gb)
    logger.info(
        "Running MinerU pipeline chunk=%s device=%s vram=%sGB",
        chunk_pdf.name,
        device_mode,
        virtual_vram_gb,
    )
    proc = subprocess.run(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    if proc.returncode != 0:
        err_tail = (proc.stderr or proc.stdout or "")[-800:]
        raise MinerUExecutionError(
            f"MinerU pipeline failed (rc={proc.returncode}, device={device_mode}, vram={virtual_vram_gb}GB): {err_tail}"
        )

    pdf_info: list[dict] = []
    content_list: list[dict] = []

    middle_files = sorted(chunk_out_dir.rglob("*_middle.json")) + sorted(
        chunk_out_dir.rglob("middle.json")
    )
    if middle_files:
        data = json.loads(middle_files[0].read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("pdf_info"), list):
            pdf_info = data["pdf_info"]
        elif isinstance(data, list):
            pdf_info = data

    cl_files = sorted(chunk_out_dir.rglob("*_content_list.json")) + sorted(
        chunk_out_dir.rglob("content_list.json")
    )
    if cl_files:
        cl_data = json.loads(cl_files[0].read_text(encoding="utf-8"))
        if isinstance(cl_data, list):
            content_list = cl_data

    return pdf_info, content_list


def _run_range_with_fallback(
    mineru_bin: Path,
    src_doc: fitz.Document,
    start_page: int,
    end_page: int,
    work_dir: Path,
    *,
    method: str,
    lang: str,
    virtual_vram_gb: int,
    timeout_s: int,
) -> tuple[list[dict], list[dict], bool]:
    """Run MinerU on [start_page, end_page) with automatic half-chunk -> CPU fallback."""
    page_span = end_page - start_page
    tag = f"p{start_page:04d}_{end_page - 1:04d}"
    chunk_pdf = work_dir / f"chunk_{tag}.pdf"
    chunk_out = work_dir / f"out_{tag}"
    _split_pdf_chunk(src_doc, start_page, end_page, chunk_pdf)

    # Tier 1: GPU with configured virtual VRAM budget (default 8 GB)
    try:
        pdf_info, cl = _invoke_mineru_chunk(
            mineru_bin,
            chunk_pdf,
            chunk_out,
            method=method,
            lang=lang,
            device_mode="cuda",
            virtual_vram_gb=virtual_vram_gb,
            timeout_s=timeout_s,
        )
        return pdf_info, cl, False
    except (MinerUExecutionError, subprocess.TimeoutExpired) as exc:
        logger.warning("MinerU tier-1 failed for %s: %s", tag, exc)

    # Tier 2: Half-chunk split + halved virtual VRAM on GPU
    half_vram = max(4, virtual_vram_gb // 2)
    if page_span > 1:
        mid = start_page + page_span // 2
        try:
            pi1, cl1, cpu1 = _run_range_with_fallback(
                mineru_bin,
                src_doc,
                start_page,
                mid,
                work_dir,
                method=method,
                lang=lang,
                virtual_vram_gb=half_vram,
                timeout_s=timeout_s,
            )
            pi2, cl2, cpu2 = _run_range_with_fallback(
                mineru_bin,
                src_doc,
                mid,
                end_page,
                work_dir,
                method=method,
                lang=lang,
                virtual_vram_gb=half_vram,
                timeout_s=timeout_s,
            )
            return pi1 + pi2, cl1 + cl2, (cpu1 or cpu2)
        except MinerUExecutionError as exc:
            logger.warning("MinerU tier-2 half-chunk GPU retry failed for %s: %s", tag, exc)

    # Tier 3: CPU fallback
    cpu_out = work_dir / f"out_{tag}_cpu"
    pdf_info, cl = _invoke_mineru_chunk(
        mineru_bin,
        chunk_pdf,
        cpu_out,
        method=method,
        lang=lang,
        device_mode="cpu",
        virtual_vram_gb=4,
        timeout_s=timeout_s * 2,
    )
    return pdf_info, cl, True


def run_mineru_pipeline(
    pdf_path: Path,
    work_dir: Path | None = None,
    *,
    backend: str = "pipeline",
    method: str = "auto",
    lang: str = "ch",
    chunk_size: int = 10,
    virtual_vram_gb: int = 8,
    timeout_s: int = 300,
    mineru_bin: str | Path | None = None,
    progress_cb: ProgressHook | None = None,
) -> MinerUResult:
    """Execute MinerU strictly in `pipeline` mode over 10-page chunks with VRAM safety."""
    if backend != "pipeline" or backend in FORBIDDEN_BACKENDS:
        raise ValueError(
            f"Unsupported MinerU backend '{backend}'. Only 'pipeline' is allowed "
            "(vLLM / sglang / VLM backends are strictly forbidden on 12GB VRAM hosts)."
        )
    if method not in {"auto", "txt", "ocr"}:
        raise ValueError(f"Unsupported MinerU method: {method}")

    exe = find_mineru_executable(mineru_bin)
    if exe is None:
        raise MinerUUnavailableError(
            "MinerU CLI ('mineru') is not installed locally; falling back to PyMuPDF parser."
        )

    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    temp_ctx = None
    if work_dir is None:
        temp_ctx = tempfile.TemporaryDirectory(prefix="inkcraft_mineru_")
        resolved_work = Path(temp_ctx.name)
    else:
        resolved_work = Path(work_dir)
        resolved_work.mkdir(parents=True, exist_ok=True)

    result = MinerUResult(images_dir=resolved_work)
    try:
        with _GPU_SEMAPHORE:
            src_doc = fitz.open(str(pdf_path))
            try:
                total_pages = len(src_doc)
                if total_pages == 0:
                    return result

                step = max(1, int(chunk_size))
                for start in range(0, total_pages, step):
                    end = min(total_pages, start + step)
                    if progress_cb is not None:
                        pct = 0.15 + 0.65 * (start / max(1, total_pages))
                        progress_cb(
                            "mineru_layout",
                            pct,
                            start,
                            total_pages,
                            f"MinerU pipeline 解析第 {start + 1}-{end}/{total_pages} 页",
                        )

                    pi_chunk, cl_chunk, used_cpu = _run_range_with_fallback(
                        exe,
                        src_doc,
                        start,
                        end,
                        resolved_work,
                        method=method,
                        lang=lang,
                        virtual_vram_gb=virtual_vram_gb,
                        timeout_s=timeout_s,
                    )
                    if used_cpu:
                        result.used_cpu_fallback = True

                    for idx, pinfo in enumerate(pi_chunk):
                        entry = dict(pinfo)
                        entry["page_idx"] = start + int(entry.get("page_idx", idx))
                        result.pdf_info.append(entry)

                    for item in cl_chunk:
                        entry = dict(item)
                        if "page_idx" in entry:
                            entry["page_idx"] = start + int(entry["page_idx"])
                        result.content_list.append(entry)
            finally:
                src_doc.close()
    finally:
        if temp_ctx is not None:
            temp_ctx.cleanup()

    return result
