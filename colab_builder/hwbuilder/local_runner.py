"""Unified Local (GPU/CPU) & Cloud (Google Colab) Font Builder Runner.

Provides:
  - `probe_capabilities()`: Inspects local CUDA/PyTorch/OpenCV/GPU VRAM (`nvidia-smi`)
  - `preset_charset(preset, custom_chars)`: Quick / Standard / Custom collection charsets
  - `build_synthetic_scans(manifest, ...)`: Renders realistic synthetic filled scans for demo/testing
  - `run_local_font_build(...)`: End-to-end local pipeline (`segment` -> `skeleton_align` ->
    `SDTTrainer` (GPU) or `LocalStyleTransferAugmentor` (CPU) -> `qc_export`) with stage callbacks
  - `package_colab_bundle(...)`: Creates a self-contained `handwrite_colab_bundle.zip` ready to
    upload to Google Drive / Colab with all 3 notebooks, `hwbuilder` + `hwfont_sdk`, config,
    manifest, and scan images.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Callable, Literal, Sequence
import zipfile

import numpy as np
from PIL import Image, ImageDraw

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    fitz = None  # type: ignore[assignment]

from hwbuilder.model_sdt import (
    LocalStyleTransferAugmentor,
    SDTConfig,
    SDTTrainer,
    is_torch_available,
)
from hwbuilder.qc_export import (
    QCConfig,
    VariantCandidate,
    export_hwfont_detailed,
)
from hwbuilder.segment import (
    CroppedGlyph,
    SegmentConfig,
    export_review_html,
    segment_scan,
)
from hwbuilder.sheet_gen import (
    DEFAULT_CORE_CHARSET,
    GridColor,
    SheetConfig,
    SheetManifest,
    generate_collection_sheets,
)
from hwbuilder.skeleton_align import (
    VectorizeConfig,
    load_builtin_priors,
    load_makemeahanzi_priors,
    vectorize_glyph,
)
from hwfont_sdk import HwFontMeta, VerifyReport


BuildEngine = Literal["auto", "local_gpu", "local_cpu"]
ResolvedEngine = Literal["local_gpu", "local_cpu"]
BuilderModeId = Literal["local_gpu", "local_cpu", "colab_cloud"]
SheetPreset = Literal["quick", "standard", "custom"]
TargetPreset = Literal["quick", "standard", "scanned_only"]
StageProgressCB = Callable[[str, float, str], None]

# Fast 1-page collection preset covering digits, sample Latin, punctuation/math & key CJK chars
QUICK_CHARSET: str = (
    "0123456789"
    "ABCDEFGHMNOPRSTWXYZ"
    "abcdefghmnoprstwxyz"
    "，。、；：？！（）+-=×÷"
    "永和九年岁在癸丑中国学习工程实验数学模型时间速度质量"
)


def preset_charset(preset: SheetPreset = "standard", custom_chars: str | None = None) -> str:
    """Resolve character list for `quick`, `standard`, or `custom` presets."""
    if preset == "custom":
        cleaned = "".join(ch for ch in (custom_chars or "") if not ch.isspace())
        cleaned = "".join(dict.fromkeys(cleaned))
        if not cleaned:
            raise ValueError("custom_chars 不能为空（已过滤空白字符）")
        return cleaned
    if preset == "quick":
        return "".join(dict.fromkeys(QUICK_CHARSET))
    return DEFAULT_CORE_CHARSET


def _probe_nvidia_smi() -> tuple[str | None, int | None]:
    if shutil.which("nvidia-smi") is None:
        return None, None
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=True,
        )
        lines = [ln.strip() for ln in proc.stdout.strip().splitlines() if ln.strip()]
        if not lines:
            return None, None
        parts = [p.strip() for p in lines[0].split(",")]
        gpu_name = parts[0] if parts else None
        vram_mb = int(float(parts[1])) if len(parts) > 1 else None
        return gpu_name, vram_mb
    except Exception:
        return None, None


def probe_capabilities() -> dict[str, Any]:
    """Detect local GPU/CUDA, PyTorch, and OpenCV availability for the font builder UI & CLI."""
    torch_available = is_torch_available()
    cv2_available = importlib.util.find_spec("cv2") is not None

    cuda_available = False
    gpu_name: str | None = None
    vram_mb: int | None = None

    if torch_available:
        try:
            import torch  # type: ignore[import-not-found]

            cuda_available = bool(torch.cuda.is_available())
            if cuda_available:
                gpu_name = str(torch.cuda.get_device_name(0))
                props = torch.cuda.get_device_properties(0)
                vram_mb = int(round(props.total_memory / (1024 * 1024)))
        except Exception:
            cuda_available = False

    if gpu_name is None or vram_mb is None:
        smi_name, smi_vram = _probe_nvidia_smi()
        gpu_name = gpu_name or smi_name
        vram_mb = vram_mb or smi_vram

    local_gpu_ready = bool(cuda_available and torch_available)
    if local_gpu_ready:
        recommended_mode: BuilderModeId = "local_gpu"
    else:
        recommended_mode = "local_cpu"

    if local_gpu_ready:
        gpu_desc = f"检测到 {gpu_name or 'CUDA GPU'} ({vram_mb or 0} MB)，支持本机离线 SDT-LoRA 微调与高速生成。"
    elif gpu_name:
        gpu_desc = (
            f"检测到硬件 GPU ({gpu_name}, {vram_mb or 0} MB)，但当前 Python 环境未安装 PyTorch CUDA；"
            "安装 torch 后即可启用本机 GPU 微调，当前可先使用本机 CPU 或 Colab 云端。"
        )
    else:
        gpu_desc = "未检测到可用的 CUDA GPU 与 PyTorch 环境，请使用本机 CPU 快速构建或 Colab 云端 GPU。"

    return {
        "cuda_available": cuda_available,
        "gpu_name": gpu_name,
        "vram_mb": vram_mb,
        "torch_available": torch_available,
        "cv2_available": cv2_available,
        "recommended_mode": recommended_mode,
        "modes": [
            {
                "id": "local_gpu",
                "available": local_gpu_ready,
                "label": "本机 GPU 离线微调 (SDT + LoRA)",
                "description": gpu_desc,
            },
            {
                "id": "local_cpu",
                "available": True,
                "label": "本机 CPU 离线快速构建",
                "description": "纯离线运行（NumPy + Pillow），支持真实扫描切片、TPS 笔顺恢复与参数化风格多异形合成，无需 GPU。",
            },
            {
                "id": "colab_cloud",
                "available": True,
                "label": "Google Colab 云端 GPU 构建",
                "description": "打包采集表、扫描件与 3 份 Notebook 为 .zip，上传 Google Colab 免费 T4/L4 GPU 完成全字库微调后导回 .hwfont。",
            },
        ],
    }


def resolve_engine(engine: BuildEngine = "auto") -> ResolvedEngine:
    """Resolve requested engine (`auto`/`local_gpu`/`local_cpu`) against local capabilities."""
    caps = probe_capabilities()
    gpu_ready = bool(caps["cuda_available"] and caps["torch_available"])
    if engine == "local_gpu":
        return "local_gpu" if gpu_ready else "local_cpu"
    if engine == "local_cpu":
        return "local_cpu"
    return "local_gpu" if gpu_ready else "local_cpu"


def build_synthetic_scans(
    manifest: SheetManifest,
    pdf_path: Path,
    out_dir: Path,
    *,
    dpi: int = 180,
    seed: int = 2026,
    max_pages: int = 2,
) -> list[Path]:
    """Render synthetic filled scan PNGs from a sheet PDF for zero-hardware quick testing."""
    if fitz is None:
        raise RuntimeError("PyMuPDF (`pymupdf`) is required to synthesize demo scans.")
    out_dir.mkdir(parents=True, exist_ok=True)
    priors = load_builtin_priors()
    rng = np.random.default_rng(seed)

    # Randomize a writer-specific slant & aspect per synthetic run so generated fonts look distinct
    slant = float(rng.uniform(-0.10, 0.14))
    doc = fitz.open(str(pdf_path))
    px_per_mm = dpi / 25.4
    scan_paths: list[Path] = []

    try:
        n_pages = min(len(doc), len(manifest.pages), max_pages)
        for p_idx in range(n_pages):
            pix = doc[p_idx].get_pixmap(dpi=dpi)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            draw = ImageDraw.Draw(img)

            for cell in manifest.pages[p_idx].cells:
                bx0, by0, bx1, by1 = cell.write_box_mm
                x0 = bx0 * px_per_mm
                y0 = by0 * px_per_mm
                x1 = bx1 * px_per_mm
                y1 = by1 * px_per_mm
                pad = max(4.0, (x1 - x0) * 0.12)
                w_box = max(6.0, (x1 - x0) - 2.0 * pad)
                h_box = max(6.0, (y1 - y0) - 2.0 * pad)

                if cell.char in priors:
                    strokes = priors[cell.char]
                else:
                    # Deterministic compact CJK-like multi-stroke shape
                    d = hashlib.sha256(cell.char.encode("utf-8")).digest()
                    y_top = 210 + (d[0] % 60)
                    y_mid = 480 + (d[1] % 60)
                    strokes = [
                        np.array([[200, y_top], [800, y_top - 15]], dtype=np.float64),
                        np.array([[500, 140], [500, 860]], dtype=np.float64),
                        np.array([[220, y_mid], [780, y_mid - 10]], dtype=np.float64),
                        np.array([[480, y_mid], [210, 830]], dtype=np.float64),
                        np.array([[520, y_mid], [800, 830]], dtype=np.float64),
                    ]

                for st in strokes:
                    arr = np.asarray(st, dtype=np.float64)
                    pts: list[tuple[float, float]] = []
                    for px_u, py_u in arr:
                        ux = px_u - slant * (py_u - 500.0) + float(rng.normal(0.0, 6.0))
                        uy = py_u + float(rng.normal(0.0, 6.0))
                        ux = max(40.0, min(960.0, ux))
                        uy = max(40.0, min(960.0, uy))
                        pts.append((x0 + pad + ux / 1000.0 * w_box, y0 + pad + uy / 1000.0 * h_box))
                    if len(pts) >= 2:
                        draw.line(pts, fill=(20, 20, 24), width=max(2, int(round(dpi / 55.0))))

            # Mild scanner rotation to exercise fiducial perspective alignment
            angle = float(rng.uniform(-1.2, 1.2))
            img = img.rotate(angle, resample=Image.Resampling.BILINEAR, fillcolor=(248, 248, 246))
            out_png = out_dir / f"demo_scan_p{p_idx:03d}.png"
            img.save(out_png)
            scan_paths.append(out_png)
    finally:
        doc.close()

    return scan_paths


@dataclass
class LocalBuildConfig:
    """Configuration for a complete local offline `.hwfont` build job."""

    writer_name: str
    writer_alias: str = ""
    author: str = "Handwrite Local Builder"
    version: str = "1.0.0"
    style_tags: list[str] = field(default_factory=list)
    engine: BuildEngine = "auto"
    variants_per_char: int = 3
    target_preset: TargetPreset = "standard"
    grid_color: GridColor = "cyan"
    target_dpi: int = 220
    makemeahanzi_path: Path | None = None
    seed: int = 2026
    sdt_epochs: int = 25


@dataclass
class LocalBuildResult:
    """Outputs and verification summary of a local `.hwfont` build run."""

    out_hwfont: Path
    verify_report: VerifyReport
    engine_used: ResolvedEngine
    glyph_count: int
    variant_count: int
    scanned_glyphs_count: int
    accepted_variants: int
    rejected_variants: int
    review_html_path: Path | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


def run_local_font_build(
    *,
    out_hwfont: str | Path,
    config: LocalBuildConfig,
    scan_paths: Sequence[str | Path] = (),
    manifest: SheetManifest | None = None,
    manifest_path: str | Path | None = None,
    demo_synthetic: bool = False,
    work_dir: str | Path | None = None,
    progress: StageProgressCB | None = None,
) -> LocalBuildResult:
    """Execute end-to-end local font building (`segment -> align -> synthesize -> qc -> export`)."""
    def _emit(stage: str, pct: float, msg: str) -> None:
        if progress is not None:
            progress(stage, pct, msg)

    out_path = Path(out_hwfont).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    auto_tmp = work_dir is None
    wdir = Path(tempfile.mkdtemp(prefix="hwbuild_")) if auto_tmp else Path(work_dir).resolve()
    wdir.mkdir(parents=True, exist_ok=True)

    try:
        return _run_local_font_build_inner(
            out_path=out_path,
            wdir=wdir,
            auto_tmp=auto_tmp,
            config=config,
            scan_paths=scan_paths,
            manifest=manifest,
            manifest_path=manifest_path,
            demo_synthetic=demo_synthetic,
            emit=_emit,
        )
    finally:
        if auto_tmp and wdir.exists():
            shutil.rmtree(wdir, ignore_errors=True)


def _run_local_font_build_inner(
    *,
    out_path: Path,
    wdir: Path,
    auto_tmp: bool,
    config: LocalBuildConfig,
    scan_paths: Sequence[str | Path],
    manifest: SheetManifest | None,
    manifest_path: str | Path | None,
    demo_synthetic: bool,
    emit: StageProgressCB,
) -> LocalBuildResult:
    _emit = emit

    resolved_engine = resolve_engine(config.engine)
    _emit("segment", 5.0, f"初始化本机构建引擎：{resolved_engine}")

    # Load or synthesize manifest & scans
    active_manifest = manifest
    if active_manifest is None and manifest_path is not None and Path(manifest_path).is_file():
        active_manifest = SheetManifest.load(manifest_path)

    active_scans = [Path(p) for p in scan_paths if Path(p).is_file()]

    if active_manifest is None:
        # Generate a matching default sheet manifest if user passed demo_synthetic or raw scans
        sheet_preset: SheetPreset = "quick" if config.target_preset == "quick" else "standard"
        s_cfg = SheetConfig(
            writer_name=config.writer_name,
            rows=8 if sheet_preset == "quick" else 12,
            cols=8 if sheet_preset == "quick" else 10,
            grid_color=config.grid_color,
            preview_dpi=120,
        )
        sheets_dir = wdir / "auto_sheets"
        active_manifest = generate_collection_sheets(
            preset_charset(sheet_preset),
            out_dir=sheets_dir,
            config=s_cfg,
            render_previews=False,
        )
        if demo_synthetic and not active_scans:
            active_scans = build_synthetic_scans(
                active_manifest,
                sheets_dir / active_manifest.pdf_path,
                wdir / "demo_scans",
                dpi=180,
                seed=config.seed,
                max_pages=2,
            )
    elif demo_synthetic and not active_scans:
        # Render synthetic scans for the provided manifest
        pdf_cand = Path(manifest_path).parent / active_manifest.pdf_path if manifest_path else None
        if pdf_cand is None or not pdf_cand.is_file():
            # Regenerate PDF from manifest characters so synthetic scan matches exact layout
            chars = "".join(c.char for p in active_manifest.pages for c in p.cells)
            sheets_dir = wdir / "regen_sheets"
            active_manifest = generate_collection_sheets(
                chars,
                out_dir=sheets_dir,
                config=SheetConfig(
                    writer_name=active_manifest.writer_name or config.writer_name,
                    rows=active_manifest.rows,
                    cols=active_manifest.cols,
                    grid_color=active_manifest.grid_color,
                    preview_dpi=120,
                ),
                render_previews=False,
            )
            pdf_cand = sheets_dir / active_manifest.pdf_path
        active_scans = build_synthetic_scans(
            active_manifest,
            pdf_cand,
            wdir / "demo_scans",
            dpi=180,
            seed=config.seed,
            max_pages=min(2, len(active_manifest.pages)),
        )

    if not active_scans:
        raise ValueError("未提供扫描图片，且未启用 demo_synthetic 合成样例模式。")

    # 1. Segment scans -> CroppedGlyph list + review.html
    seg_cfg = SegmentConfig(
        target_dpi=config.target_dpi,
        grid_color=active_manifest.grid_color,
        binarize_method="hybrid",
    )
    all_crops: list[CroppedGlyph] = []
    seg_diags: list[dict[str, Any]] = []
    total_pages = min(len(active_scans), len(active_manifest.pages))
    for p_idx in range(total_pages):
        _emit(
            "segment",
            10.0 + 18.0 * (p_idx / max(1, total_pages)),
            f"正在透视对齐并切片第 {p_idx + 1}/{total_pages} 页扫描件…",
        )
        crops, diag = segment_scan(
            active_scans[p_idx],
            active_manifest,
            page_index=p_idx,
            config=seg_cfg,
            save_crops_dir=wdir / "crops",
        )
        all_crops.extend(crops)
        seg_diags.append(diag)

    review_html_path = export_review_html(all_crops, wdir / "review.html")
    kept_crops = [c for c in all_crops if c.kept]

    # 2. Skeletonize & align with template priors
    _emit("align", 32.0, f"正在恢复 {len(kept_crops)} 个字形的有向单线笔顺轨迹…")
    priors = load_builtin_priors()
    if config.makemeahanzi_path is not None and Path(config.makemeahanzi_path).is_file():
        priors.update(load_makemeahanzi_priors(config.makemeahanzi_path))

    vec_cfg = VectorizeConfig()
    scanned_by_char: dict[str, list[tuple[list[np.ndarray], float]]] = defaultdict(list)
    method_counts: dict[str, int] = defaultdict(int)
    for idx, crop in enumerate(kept_crops):
        if idx % 20 == 0:
            _emit(
                "align",
                32.0 + 22.0 * (idx / max(1, len(kept_crops))),
                f"骨架细化与笔顺配准 ({idx + 1}/{len(kept_crops)})…",
            )
        res = vectorize_glyph(crop.binary, char=crop.char, priors=priors, config=vec_cfg)
        method_counts[res.method] += 1
        if res.strokes:
            scanned_by_char[crop.char].append((res.strokes, res.quality))

    # 3. Learn writer style & synthesize multi-variant trajectories
    _emit("synthesize", 58.0, f"使用 {resolved_engine} 引擎学习笔迹风格并合成多异形…")
    augmentor = LocalStyleTransferAugmentor()
    style_profile = augmentor.fit(
        {ch: [v[0] for v in vs] for ch, vs in scanned_by_char.items()},
        writer_name=config.writer_name,
    )
    style_profile.save(wdir / "writer_style_profile.json")

    sdt_trainer: SDTTrainer | None = None
    actual_engine_used: ResolvedEngine = "local_cpu"
    if resolved_engine == "local_gpu" and is_torch_available():
        pairs = [
            (priors[ch], vs[0][0])
            for ch, vs in scanned_by_char.items()
            if ch in priors and vs
        ]
        if len(pairs) >= 8:
            try:
                _emit("synthesize", 62.0, f"本机 GPU 启动 SDT-LoRA 少样本微调 ({len(pairs)} 配对字形)…")
                sdt_cfg = SDTConfig(epochs=config.sdt_epochs, batch_size=min(16, len(pairs)))
                sdt_trainer = SDTTrainer(sdt_cfg)
                sdt_trainer.fit(pairs, lora_only=True)
                actual_engine_used = "local_gpu"
            except Exception:
                sdt_trainer = None
                actual_engine_used = "local_cpu"

    # Determine target characters to populate in the final .hwfont
    if config.target_preset == "scanned_only":
        target_chars = list(scanned_by_char.keys())
    elif config.target_preset == "quick":
        target_chars = list(dict.fromkeys(list(scanned_by_char.keys()) + list(preset_charset("quick"))))
    else:
        target_chars = list(
            dict.fromkeys(list(scanned_by_char.keys()) + list(priors.keys()))
        )

    char_variants: dict[str, list[VariantCandidate]] = {}
    style_ref_strokes = (
        next(iter(scanned_by_char.values()))[0][0]
        if scanned_by_char
        else next(iter(priors.values()))
    )

    for idx, ch in enumerate(target_chars):
        if idx % 30 == 0:
            _emit(
                "synthesize",
                64.0 + 18.0 * (idx / max(1, len(target_chars))),
                f"合成同字异形 ({idx + 1}/{len(target_chars)})…",
            )
        cands: list[VariantCandidate] = []
        for strokes, q in scanned_by_char.get(ch, []):
            cands.append(VariantCandidate(strokes=strokes, source="scan", quality=q, weight=1.5))

        need = max(0, config.variants_per_char - len(cands))
        base = cands[0].strokes if cands else priors.get(ch)
        if need > 0 and base:
            if sdt_trainer is not None and ch in priors:
                gen_sdt = sdt_trainer.generate_variants(
                    priors[ch],
                    style_ref_strokes,
                    n_variants=max(1, need // 2),
                    seed=config.seed + ord(ch),
                )
                for g in gen_sdt:
                    cands.append(VariantCandidate(strokes=g, source="generated", quality=0.90, weight=1.0))
            rem = max(0, config.variants_per_char - len(cands))
            if rem > 0:
                synths = augmentor.synthesize_variants(
                    ch,
                    base,
                    n_variants=rem + 2,
                    seed=config.seed,
                    diversity_boost=1.25,
                )
                for syn in synths:
                    cands.append(VariantCandidate(strokes=syn, source="generated", quality=0.92, weight=1.0))

        if cands:
            char_variants[ch] = cands

    # 4. QC gate + verified .hwfont export
    _emit("qc", 85.0, "正在执行自动化质检门禁（点密度、外接框与异形多样性）…")
    tags = [t.strip() for t in config.style_tags if t.strip()]
    if not tags:
        tags = ["本机构建", "GPU-SDT" if actual_engine_used == "local_gpu" else "CPU风格迁移"]

    meta = HwFontMeta(
        writer_name=config.writer_name,
        writer_alias=config.writer_alias or f"{config.writer_name}·自建笔迹",
        author=config.author,
        version=config.version,
        style_tags=tags,
        builder=f"hwbuilder 1.0.0 ({actual_engine_used})",
        model="sdt-lora-r8" if actual_engine_used == "local_gpu" else "local-style-transfer-v1",
        license=f"Authorized personal handwriting font of {config.writer_name}",
    )

    _emit("export", 93.0, "正在写入单文件 .hwfont 并校验 content_sha256…")
    qc_cfg = QCConfig(min_chamfer_diversity_u=14.0, embed_thumbnails=False)
    exp = export_hwfont_detailed(
        meta,
        char_variants,
        out_path,
        qc_config=qc_cfg,
        priors=priors,
    )
    if not exp.verify_report.ok:
        raise RuntimeError(f".hwfont 校验失败: {exp.verify_report.errors}")

    _emit("done", 100.0, f"完成！已生成 {exp.verify_report.glyph_count} 字 / {exp.verify_report.variant_count} 异形")
    return LocalBuildResult(
        out_hwfont=exp.out_path,
        verify_report=exp.verify_report,
        engine_used=actual_engine_used,
        glyph_count=exp.verify_report.glyph_count,
        variant_count=exp.verify_report.variant_count,
        scanned_glyphs_count=len(scanned_by_char),
        accepted_variants=exp.accepted_variants,
        rejected_variants=exp.rejected_variants,
        review_html_path=None if auto_tmp else review_html_path,
        diagnostics={
            "segmentation": seg_diags,
            "vectorize_methods": dict(method_counts),
            "style_profile": style_profile.to_dict(),
        },
    )


def package_colab_bundle(
    *,
    repo_root: str | Path,
    writer_name: str = "my_writer",
    writer_alias: str = "",
    style_tags: Sequence[str] = (),
    variants_per_char: int = 4,
    manifest_bytes: bytes | None = None,
    sheet_pdf_bytes: bytes | None = None,
    scan_files: Sequence[tuple[str, bytes]] = (),
) -> bytes:
    """Package a self-contained Google Colab `.zip` bundle with notebooks, SDK, config & scans."""
    root = Path(repo_root).resolve()
    buf = io.BytesIO()

    config_payload = {
        "writer_name": writer_name,
        "writer_alias": writer_alias or f"{writer_name}·Colab云端笔迹",
        "style_tags": [t.strip() for t in style_tags if t.strip()],
        "variants_per_char": int(variants_per_char),
        "scans_included": [name for name, _ in scan_files],
        "has_manifest": manifest_bytes is not None,
    }

    readme_colab = f"""# Handwrite Google Colab 云端字体构建包（{writer_name}）

## 快速步骤
1. 解压本压缩包，将整个文件夹上传至 Google Drive：`MyDrive/handwrite_builder/{writer_name}/`
2. 在 Google Colab 中依次打开 `notebooks/` 下的 Notebook（建议运行时选择 **T4 / L4 GPU**）：
   - `01_generate_sheets.ipynb`：若尚未打印采集表，可重新生成 A4 PDF 与 `manifest.json`；
   - `02_scan_to_trajectories.ipynb`：对 `02_scans/` 下的扫描件执行 ArUco 透视校正、去网格切片、导出 `review.html` 复核并执行 TPS 笔顺恢复；
   - `03_train_and_export.ipynb`：在 Colab GPU 上执行 SDT-LoRA 少样本微调，通过质检门禁后导出 `{writer_name}_v1.0.hwfont`。
3. 下载导出的 `.hwfont` 文件，回到本地 Handwrite 工作台拖入「书写者管理」或直接导入即可热插拔写字。
"""

    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README_COLAB.md", readme_colab)
        zf.writestr(
            "builder_config.json",
            json.dumps(config_payload, ensure_ascii=False, indent=2),
        )

        # Include all 3 Colab notebooks
        nb_dir = root / "colab_builder" / "notebooks"
        if nb_dir.is_dir():
            for nb_file in sorted(nb_dir.glob("*.ipynb")):
                zf.write(nb_file, arcname=f"notebooks/{nb_file.name}")

        # Include self-contained hwbuilder + hwfont_sdk Python packages recursively
        hb_dir = root / "colab_builder" / "hwbuilder"
        wrote_hershey = False
        if hb_dir.is_dir():
            for py_file in sorted(hb_dir.rglob("*.py")):
                if "__pycache__" in py_file.parts:
                    continue
                rel_py = py_file.relative_to(hb_dir).as_posix()
                if rel_py == "hershey_fallback.py":
                    wrote_hershey = True
                zf.write(py_file, arcname=f"hwbuilder/{rel_py}")
        if not wrote_hershey:
            hershey_src = root / "backend" / "handwrite" / "writers" / "fallback" / "hershey.py"
            if hershey_src.is_file():
                zf.write(hershey_src, arcname="hwbuilder/hershey_fallback.py")

        sdk_dir = root / "packages" / "hwfont_sdk" / "hwfont_sdk"
        if sdk_dir.is_dir():
            for py_file in sorted(sdk_dir.rglob("*.py")):
                if "__pycache__" in py_file.parts:
                    continue
                rel_py = py_file.relative_to(sdk_dir).as_posix()
                zf.write(py_file, arcname=f"hwfont_sdk/{rel_py}")

        if manifest_bytes is not None:
            zf.writestr("01_sheets/manifest.json", manifest_bytes)
        if sheet_pdf_bytes is not None:
            zf.writestr("01_sheets/collection_sheets.pdf", sheet_pdf_bytes)

        for idx, (fname, data) in enumerate(scan_files):
            safe_name = Path(fname).name or f"scan_{idx:03d}.png"
            zf.writestr(f"02_scans/{safe_name}", data)

    return buf.getvalue()
