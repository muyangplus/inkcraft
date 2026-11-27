#!/usr/bin/env python3
"""RTX 4070 Super (12GB) VRAM peak monitor & MinerU `pipeline` chunked benchmark script.

Splits a target PDF into fixed-size page chunks (default 10 pages/chunk via PyMuPDF),
invokes `mineru -b pipeline` (explicitly enforcing pipeline mode and `MINERU_VIRTUAL_VRAM_SIZE=8`),
polls `nvidia-smi` every 200ms in a background thread, and validates that peak VRAM stays
within the 8.5 GB safety budget (`>= 3.5 GB` headroom on a 12 GB RTX 4070 Super).

Usage:
    python scripts/bench_mineru_vram.py --pdf sample_50p.pdf
    python scripts/bench_mineru_vram.py --pdf sample_50p.pdf --chunk-pages 10 --max-vram-gb 8.5
    python scripts/bench_mineru_vram.py --monitor-only --duration 5
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    fitz = None  # type: ignore[assignment]


@dataclass
class VramSample:
    timestamp_s: float
    used_mb: float
    total_mb: float
    gpu_util_pct: float


@dataclass
class ChunkBenchResult:
    chunk_index: int
    start_page: int
    end_page: int
    elapsed_s: float
    peak_vram_mb: float
    exit_code: int
    command: list[str] = field(default_factory=list)


class NvidiaSmiMonitor:
    """Background 200ms `nvidia-smi` VRAM sampler."""

    def __init__(self, interval_ms: int = 200, gpu_index: int = 0) -> None:
        self.interval_s = max(0.05, interval_ms / 1000.0)
        self.gpu_index = gpu_index
        self.samples: list[VramSample] = []
        self.available: bool = shutil.which("nvidia-smi") is not None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._t0 = 0.0

    def _query_once(self) -> VramSample | None:
        if not self.available:
            return None
        try:
            proc = subprocess.run(
                [
                    "nvidia-smi",
                    f"--id={self.gpu_index}",
                    "--query-gpu=memory.used,memory.total,utilization.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=1.5,
                check=True,
            )
            line = proc.stdout.strip().splitlines()[0]
            parts = [p.strip() for p in line.split(",")]
            return VramSample(
                timestamp_s=round(time.monotonic() - self._t0, 3),
                used_mb=float(parts[0]),
                total_mb=float(parts[1]),
                gpu_util_pct=float(parts[2]),
            )
        except Exception:
            return None

    def _loop(self) -> None:
        while not self._stop.is_set():
            sample = self._query_once()
            if sample is not None:
                with self._lock:
                    self.samples.append(sample)
            self._stop.wait(self.interval_s)

    def start(self) -> None:
        self._t0 = time.monotonic()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="nvidia-smi-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> list[VramSample]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        with self._lock:
            return list(self.samples)

    def peak_mb_since(self, since_idx: int) -> float:
        with self._lock:
            sub = self.samples[since_idx:]
        return max((s.used_mb for s in sub), default=0.0)

    def sample_count(self) -> int:
        with self._lock:
            return len(self.samples)


def split_pdf_chunks(pdf_path: Path, out_dir: Path, chunk_pages: int) -> list[tuple[int, int, Path]]:
    """Split `pdf_path` into `chunk_pages`-page PDF files using PyMuPDF."""
    if fitz is None:
        raise RuntimeError("PyMuPDF (`pymupdf`) is required to split PDF chunks.")
    doc = fitz.open(str(pdf_path))
    total = len(doc)
    chunks: list[tuple[int, int, Path]] = []
    for start in range(0, total, chunk_pages):
        end = min(total, start + chunk_pages)
        sub = fitz.open()
        sub.insert_pdf(doc, from_page=start, to_page=end - 1)
        chunk_file = out_dir / f"chunk_{start:04d}_{end - 1:04d}.pdf"
        sub.save(str(chunk_file))
        sub.close()
        chunks.append((start, end - 1, chunk_file))
    doc.close()
    return chunks


def run_benchmark(args: argparse.Namespace) -> int:
    monitor = NvidiaSmiMonitor(interval_ms=args.interval_ms, gpu_index=args.gpu_index)
    if not monitor.available:
        print("[WARN] `nvidia-smi` not found in PATH; VRAM readings will be reported as 0.0 MB.")

    chunk_results: list[ChunkBenchResult] = []
    t_start = time.monotonic()
    monitor.start()

    try:
        if args.monitor_only:
            time.sleep(max(0.5, float(args.duration)))
        else:
            if args.pdf is None or not args.pdf.exists():
                print(f"[ERROR] PDF file not found: {args.pdf}", file=sys.stderr)
                return 1

            mineru_bin = args.mineru_bin or shutil.which("mineru")
            if not mineru_bin and not args.dry_run:
                print(
                    "[ERROR] `mineru` CLI not found in PATH. Install MinerU in its isolated venv "
                    "or pass `--mineru-bin /path/to/mineru` (or `--dry-run`).",
                    file=sys.stderr,
                )
                return 1

            env = os.environ.copy()
            env.update(
                {
                    "MINERU_DEVICE_MODE": args.device,
                    "MINERU_VIRTUAL_VRAM_SIZE": str(args.virtual_vram_gb),
                    "MINERU_MODEL_SOURCE": args.model_source,
                    "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
                    "CUDA_VISIBLE_DEVICES": str(args.gpu_index),
                }
            )

            with tempfile.TemporaryDirectory(prefix="mineru_vram_bench_") as tmp_str:
                tmp_dir = Path(tmp_str)
                chunks_dir = tmp_dir / "chunks"
                out_dir = tmp_dir / "out"
                chunks_dir.mkdir(parents=True, exist_ok=True)
                out_dir.mkdir(parents=True, exist_ok=True)

                chunks = split_pdf_chunks(args.pdf, chunks_dir, args.chunk_pages)
                print(
                    f"[INFO] Benchmarking {args.pdf.name}: {len(chunks)} chunks "
                    f"(<= {args.chunk_pages} pages/chunk, backend=pipeline, "
                    f"MINERU_VIRTUAL_VRAM_SIZE={args.virtual_vram_gb}GB)"
                )

                for idx, (p0, p1, chunk_pdf) in enumerate(chunks):
                    chunk_out = out_dir / f"chunk_{idx:03d}"
                    chunk_out.mkdir(parents=True, exist_ok=True)
                    cmd = [
                        str(mineru_bin or "mineru"),
                        "-p",
                        str(chunk_pdf),
                        "-o",
                        str(chunk_out),
                        "-b",
                        "pipeline",
                        "-m",
                        args.method,
                        "-l",
                        args.lang,
                        "--formula",
                        "true",
                        "--table",
                        "true",
                    ]
                    s0 = monitor.sample_count()
                    c_t0 = time.monotonic()
                    if args.dry_run:
                        time.sleep(0.25)
                        rc = 0
                    else:
                        proc = subprocess.run(cmd, env=env, check=False)
                        rc = int(proc.returncode)
                    elapsed = round(time.monotonic() - c_t0, 2)
                    peak_mb = round(monitor.peak_mb_since(s0), 1)
                    chunk_results.append(
                        ChunkBenchResult(
                            chunk_index=idx,
                            start_page=p0,
                            end_page=p1,
                            elapsed_s=elapsed,
                            peak_vram_mb=peak_mb,
                            exit_code=rc,
                            command=cmd,
                        )
                    )
                    print(
                        f"  chunk {idx:02d} [pages {p0 + 1}..{p1 + 1}]: "
                        f"{elapsed:6.2f}s | peak VRAM = {peak_mb / 1024.0:.2f} GB | rc={rc}"
                    )
                    if rc != 0:
                        print(f"[WARN] Chunk {idx} exited with code {rc}; stopping benchmark.")
                        break
    finally:
        samples = monitor.stop()

    total_elapsed = round(time.monotonic() - t_start, 2)
    peak_vram_mb = max((s.used_mb for s in samples), default=0.0)
    peak_vram_gb = peak_vram_mb / 1024.0
    total_vram_mb = max((s.total_mb for s in samples), default=12288.0)
    headroom_gb = (total_vram_mb - peak_vram_mb) / 1024.0
    vram_ok = peak_vram_gb <= args.max_vram_gb
    chunks_ok = all(c.exit_code == 0 for c in chunk_results)
    passed = vram_ok and chunks_ok

    summary: dict[str, Any] = {
        "backend": "pipeline",
        "nvidia_smi_available": monitor.available,
        "interval_ms": args.interval_ms,
        "samples_collected": len(samples),
        "total_elapsed_s": total_elapsed,
        "peak_vram_mb": round(peak_vram_mb, 1),
        "peak_vram_gb": round(peak_vram_gb, 3),
        "budget_max_vram_gb": args.max_vram_gb,
        "gpu_total_vram_gb": round(total_vram_mb / 1024.0, 2),
        "headroom_gb": round(headroom_gb, 2),
        "vram_budget_ok": vram_ok,
        "chunks": [asdict(c) for c in chunk_results],
        "passed": passed,
    }

    print("\n================ MinerU Pipeline VRAM Benchmark Summary ================")
    print(f"Samples Collected : {len(samples)} (@ {args.interval_ms} ms)")
    print(f"Total Elapsed     : {total_elapsed:.2f} s")
    print(f"Peak VRAM Used    : {peak_vram_gb:.2f} GB ({peak_vram_mb:.0f} MB)")
    print(f"VRAM Safety Limit : <= {args.max_vram_gb:.2f} GB (headroom {headroom_gb:.2f} GB)")
    print(f"Verdict           : {'PASS' if passed else 'FAIL'}")
    print("========================================================================")

    if args.json_report is not None:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[INFO] Saved JSON report -> {args.json_report}")

    return 0 if passed else 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description="RTX 4070 Super 12GB VRAM monitor & MinerU pipeline chunked benchmark."
    )
    parser.add_argument("--pdf", type=Path, default=None, help="Input PDF to benchmark.")
    parser.add_argument("--chunk-pages", type=int, default=10, help="Pages per MinerU chunk (default: 10).")
    parser.add_argument("--interval-ms", type=int, default=200, help="nvidia-smi sampling interval in ms.")
    parser.add_argument("--max-vram-gb", type=float, default=8.5, help="Peak VRAM budget threshold in GB.")
    parser.add_argument("--virtual-vram-gb", type=int, default=8, help="MINERU_VIRTUAL_VRAM_SIZE value.")
    parser.add_argument("--gpu-index", type=int, default=0, help="GPU index for CUDA & nvidia-smi.")
    parser.add_argument("--device", type=str, default="cuda", choices=("cuda", "cpu"))
    parser.add_argument("--method", type=str, default="auto", choices=("auto", "txt", "ocr"))
    parser.add_argument("--lang", type=str, default="ch", help="OCR language passed to MinerU.")
    parser.add_argument("--model-source", type=str, default="local", help="MINERU_MODEL_SOURCE value.")
    parser.add_argument("--mineru-bin", type=str, default="", help="Explicit path to mineru executable.")
    parser.add_argument("--monitor-only", action="store_true", help="Sample nvidia-smi without running MinerU.")
    parser.add_argument("--duration", type=float, default=3.0, help="Duration (s) for --monitor-only.")
    parser.add_argument("--dry-run", action="store_true", help="Chunk PDF and sample VRAM without calling mineru.")
    parser.add_argument("--json-report", type=Path, default=None, help="Optional output path for JSON summary.")
    args = parser.parse_args()
    return run_benchmark(args)


if __name__ == "__main__":
    raise SystemExit(main())
