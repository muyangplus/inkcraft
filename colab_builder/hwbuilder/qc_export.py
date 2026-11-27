"""Automated quality control gate and verified `.hwfont` export via `hwfont_sdk`.

Implements the §16.5 quality-control gates:
  - Coordinate & bounding-box sanity (`0..1000`, non-degenerate geometry)
  - Point density & arm-friendliness (RDP simplification, `<= 120` pts/stroke, `<= 450` total pts)
  - Stroke-count sanity against optional prior (`[-35%, +20%]`)
  - Inter-variant Chamfer diversity check (`>= 18u` by default) to prevent duplicate "fake variants"
  - Optional OCR round-trip readability hook on rendered 128x128 single-line bitmaps
  - Export via `hwfont_sdk.HwFontWriter` + full verification via `hwfont_sdk.HwFontReader.verify()`
"""

from __future__ import annotations

from dataclasses import dataclass, field
import io
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np
from PIL import Image, ImageDraw

from hwbuilder.skeleton_align import rdp_simplify, resample_stroke
from hwfont_sdk import HwFontMeta, HwFontReader, HwFontWriter, VerifyReport, classify_char
from hwfont_sdk.schema import VariantSource


OcrHook = Callable[[Image.Image], Sequence[tuple[str, float]] | Sequence[str]]


@dataclass
class QCConfig:
    """Quality-control thresholds aligned with architecture blueprint §16.5."""

    min_bbox_span_u: int = 20
    punct_min_bbox_span_u: int = 5
    max_strokes: int = 64
    max_points_per_stroke: int = 120
    max_total_points: int = 450
    rdp_epsilon_u: float = 2.6
    min_point_dist_u: float = 3.0
    max_point_dist_u: float = 38.0
    min_chamfer_diversity_u: float = 18.0
    stroke_count_min_ratio: float = 0.65
    stroke_count_max_ratio: float = 1.20
    ocr_top_k: int = 3
    ocr_reject_on_miss: bool = False
    embed_thumbnails: bool = False


@dataclass
class VariantCandidate:
    """Candidate glyph variant awaiting QC and `.hwfont` export."""

    strokes: list[np.ndarray]
    source: VariantSource = "generated"
    quality: float = 1.0
    weight: float = 1.0
    advance: int | None = None
    scan_png: bytes | None = None


@dataclass
class GlyphQCResult:
    """Per-variant quality control verdict and diagnostics."""

    char: str
    passed: bool
    quality: float
    cleaned_strokes: list[np.ndarray]
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
    stroke_count: int = 0
    point_count: int = 0
    ocr_hit: bool | None = None
    reasons: list[str] = field(default_factory=list)


@dataclass
class ExportResult:
    """Detailed summary returned by `export_hwfont_detailed`."""

    out_path: Path
    verify_report: VerifyReport
    total_chars: int
    accepted_variants: int
    rejected_variants: int
    qc_results: list[GlyphQCResult] = field(default_factory=list)


def _sample_strokes_cloud(strokes: Sequence[np.ndarray], total_samples: int = 72) -> np.ndarray:
    """Sample a fixed-size 2D point cloud evenly by arc length across all strokes."""
    valid = [np.asarray(s, dtype=np.float64) for s in strokes if len(s) >= 2]
    if not valid:
        return np.zeros((1, 2), dtype=np.float64)

    lengths: list[float] = []
    for s in valid:
        d = np.diff(s, axis=0)
        lengths.append(max(1e-3, float(np.hypot(d[:, 0], d[:, 1]).sum())))
    sum_len = sum(lengths)

    pts_list: list[np.ndarray] = []
    for s, sl in zip(valid, lengths):
        k = max(2, int(round(total_samples * (sl / sum_len))))
        d = np.diff(s, axis=0)
        cum = np.concatenate([[0.0], np.cumsum(np.hypot(d[:, 0], d[:, 1]))])
        tot = float(cum[-1])
        if tot < 1e-6:
            pts_list.append(np.repeat(s[:1], k, axis=0))
        else:
            ts = np.linspace(0.0, tot, k)
            pts_list.append(np.column_stack([np.interp(ts, cum, s[:, 0]), np.interp(ts, cum, s[:, 1])]))
    return np.vstack(pts_list)


def chamfer_distance(
    strokes_a: Sequence[np.ndarray],
    strokes_b: Sequence[np.ndarray],
    samples: int = 72,
) -> float:
    """Symmetric mean nearest-neighbor Chamfer distance in `0..1000` glyph units."""
    pa = _sample_strokes_cloud(strokes_a, total_samples=samples)
    pb = _sample_strokes_cloud(strokes_b, total_samples=samples)
    d2 = np.sum((pa[:, None, :] - pb[None, :, :]) ** 2, axis=-1)
    d_ab = float(np.sqrt(np.min(d2, axis=1)).mean())
    d_ba = float(np.sqrt(np.min(d2, axis=0)).mean())
    return 0.5 * (d_ab + d_ba)


def render_strokes_bitmap(
    strokes: Sequence[np.ndarray],
    size: int = 128,
    stroke_width: int = 3,
    margin: int = 6,
) -> Image.Image:
    """Render `0..1000` single-line strokes onto a `size x size` white grayscale bitmap."""
    img = Image.new("L", (size, size), color=255)
    draw = ImageDraw.Draw(img)
    scale = (size - 2 * margin) / 1000.0
    for s in strokes:
        arr = np.asarray(s, dtype=np.float64)
        if arr.ndim != 2 or arr.shape[1] != 2 or len(arr) < 2:
            continue
        pts = [(margin + float(x) * scale, margin + float(y) * scale) for x, y in arr]
        draw.line(pts, fill=0, width=max(1, stroke_width), joint="curve")
    return img


def _clean_strokes(strokes: Sequence[np.ndarray], cfg: QCConfig) -> list[np.ndarray]:
    """Clamp to `0..1000`, run RDP simplification, and resample for arm-friendly point density."""
    cleaned: list[np.ndarray] = []
    for raw in strokes:
        arr = np.asarray(raw, dtype=np.float64)
        if arr.ndim != 2 or arr.shape[1] != 2 or len(arr) < 2:
            continue
        arr = np.clip(arr, 0.0, 1000.0)
        simp = rdp_simplify(arr, cfg.rdp_epsilon_u)
        res = resample_stroke(
            simp,
            min_dist=cfg.min_point_dist_u,
            max_dist=cfg.max_point_dist_u,
            max_points=cfg.max_points_per_stroke,
        )
        rounded = np.clip(np.rint(res), 0, 1000).astype(np.int16)
        if len(rounded) >= 2:
            cleaned.append(rounded)
    return cleaned


def qc_variant(
    char: str,
    candidate: VariantCandidate | Sequence[np.ndarray],
    *,
    reference_stroke_count: int | None = None,
    ocr_fn: OcrHook | None = None,
    config: QCConfig | None = None,
) -> GlyphQCResult:
    """Validate and clean a single candidate glyph variant."""
    cfg = config or QCConfig()
    cand = (
        candidate
        if isinstance(candidate, VariantCandidate)
        else VariantCandidate(strokes=[np.asarray(s) for s in candidate])
    )
    reasons: list[str] = []
    quality = float(np.clip(cand.quality, 0.0, 1.0))

    cleaned = _clean_strokes(cand.strokes, cfg)
    if not cleaned:
        return GlyphQCResult(
            char=char,
            passed=False,
            quality=0.0,
            cleaned_strokes=[],
            reasons=["no_valid_strokes"],
        )

    sc = len(cleaned)
    pc = sum(len(s) for s in cleaned)
    if sc > cfg.max_strokes:
        reasons.append(f"too_many_strokes:{sc}>{cfg.max_strokes}")
    if pc > cfg.max_total_points:
        reasons.append(f"too_many_points:{pc}>{cfg.max_total_points}")

    all_pts = np.vstack(cleaned)
    x0, y0 = int(all_pts[:, 0].min()), int(all_pts[:, 1].min())
    x1, y1 = int(all_pts[:, 0].max()), int(all_pts[:, 1].max())
    span = max(x1 - x0, y1 - y0)

    cat = classify_char(char)
    min_span = cfg.punct_min_bbox_span_u if cat in ("punct", "other") else cfg.min_bbox_span_u
    if span < min_span:
        reasons.append(f"degenerate_bbox_span:{span}<{min_span}")

    # Stroke-count sanity check against template prior (if provided and >= 3 strokes)
    if reference_stroke_count is not None and reference_stroke_count >= 3:
        lo = max(1, int(np.floor(reference_stroke_count * cfg.stroke_count_min_ratio)))
        hi = int(np.ceil(reference_stroke_count * cfg.stroke_count_max_ratio)) + 1
        if sc < lo or sc > hi:
            reasons.append(f"stroke_count_out_of_range:{sc}_vs_ref_{reference_stroke_count}")

    # Optional OCR readability round-trip check
    ocr_hit: bool | None = None
    if ocr_fn is not None and not reasons:
        bmp = render_strokes_bitmap(cleaned, size=128, stroke_width=3)
        preds = ocr_fn(bmp)
        top_chars = [
            (p[0] if isinstance(p, tuple) else str(p))
            for p in list(preds)[: cfg.ocr_top_k]
        ]
        ocr_hit = char in top_chars
        if not ocr_hit:
            quality = round(quality * 0.65, 4)
            if cfg.ocr_reject_on_miss:
                reasons.append("ocr_top_k_miss")

    passed = len(reasons) == 0
    return GlyphQCResult(
        char=char,
        passed=passed,
        quality=round(quality, 4),
        cleaned_strokes=cleaned,
        bbox=(x0, y0, x1, y1),
        stroke_count=sc,
        point_count=pc,
        ocr_hit=ocr_hit,
        reasons=reasons,
    )


def qc_char_variants(
    char: str,
    candidates: Sequence[VariantCandidate | Sequence[np.ndarray]],
    *,
    reference_stroke_count: int | None = None,
    ocr_fn: OcrHook | None = None,
    config: QCConfig | None = None,
) -> tuple[list[VariantCandidate], list[GlyphQCResult]]:
    """Run per-variant QC plus pairwise Chamfer diversity filtering for one character."""
    cfg = config or QCConfig()
    norm_cands = [
        c if isinstance(c, VariantCandidate) else VariantCandidate(strokes=[np.asarray(s) for s in c])
        for c in candidates
    ]

    # Prioritize genuine scanned variants first, then higher quality
    indexed = sorted(
        enumerate(norm_cands),
        key=lambda item: (0 if item[1].source == "scan" else 1, -item[1].quality, item[0]),
    )

    accepted: list[VariantCandidate] = []
    reports: list[GlyphQCResult] = []

    for _orig_idx, cand in indexed:
        res = qc_variant(
            char,
            cand,
            reference_stroke_count=reference_stroke_count,
            ocr_fn=ocr_fn,
            config=cfg,
        )
        if not res.passed:
            reports.append(res)
            continue

        # Check Chamfer diversity against already-accepted variants
        too_similar = False
        if accepted and cfg.min_chamfer_diversity_u > 0.0:
            for prev in accepted:
                cd = chamfer_distance(res.cleaned_strokes, prev.strokes)
                if cd < cfg.min_chamfer_diversity_u:
                    res.passed = False
                    res.reasons.append(f"low_diversity_chamfer:{cd:.1f}<{cfg.min_chamfer_diversity_u:.1f}")
                    too_similar = True
                    break

        reports.append(res)
        if not too_similar:
            accepted.append(
                VariantCandidate(
                    strokes=res.cleaned_strokes,
                    source=cand.source,
                    quality=res.quality,
                    weight=cand.weight,
                    advance=cand.advance,
                    scan_png=cand.scan_png,
                )
            )

    return accepted, reports


def _thumb_png_bytes(strokes: Sequence[np.ndarray]) -> bytes:
    buf = io.BytesIO()
    render_strokes_bitmap(strokes, size=96, stroke_width=2).save(buf, format="PNG")
    return buf.getvalue()


def export_hwfont_detailed(
    meta: HwFontMeta,
    char_variants: Mapping[str, Sequence[VariantCandidate | Sequence[np.ndarray]]],
    out_path: str | Path,
    *,
    qc_config: QCConfig | None = None,
    priors: Mapping[str, Sequence[np.ndarray]] | None = None,
    ocr_fn: OcrHook | None = None,
) -> ExportResult:
    """Run QC on all characters, write a `.hwfont` file via `HwFontWriter`, and verify it."""
    cfg = qc_config or QCConfig()
    out_file = Path(out_path)
    writer = HwFontWriter(out_file, meta, overwrite=True)

    all_qc: list[GlyphQCResult] = []
    accepted_total = 0
    rejected_total = 0
    written_chars = 0

    for ch, raw_variants in char_variants.items():
        if not ch:
            continue
        ref_sc = len(priors[ch]) if (priors is not None and ch in priors) else None
        accepted, reports = qc_char_variants(
            ch,
            raw_variants,
            reference_stroke_count=ref_sc,
            ocr_fn=ocr_fn,
            config=cfg,
        )
        all_qc.extend(reports)
        rejected_total += sum(1 for r in reports if not r.passed)

        if not accepted:
            continue
        written_chars += 1
        for cand in accepted:
            thumb = _thumb_png_bytes(cand.strokes) if cfg.embed_thumbnails else None
            writer.add_variant(
                ch,
                cand.strokes,
                source=cand.source,
                quality=cand.quality,
                weight=cand.weight,
                advance=cand.advance,
                scan_png=cand.scan_png,
                thumb_png=thumb,
            )
            accepted_total += 1

    final_path = writer.finalize()
    reader = HwFontReader(final_path)
    try:
        verify_report = reader.verify()
    finally:
        reader.close()

    return ExportResult(
        out_path=final_path,
        verify_report=verify_report,
        total_chars=written_chars,
        accepted_variants=accepted_total,
        rejected_variants=rejected_total,
        qc_results=all_qc,
    )


def export_hwfont(
    meta: HwFontMeta,
    char_variants: Mapping[str, Sequence[VariantCandidate | Sequence[np.ndarray]]],
    out_path: str | Path,
    *,
    qc_config: QCConfig | None = None,
    priors: Mapping[str, Sequence[np.ndarray]] | None = None,
    ocr_fn: OcrHook | None = None,
) -> VerifyReport:
    """Export QC-filtered variants into a `.hwfont` database and return `HwFontReader.verify()`."""
    res = export_hwfont_detailed(
        meta,
        char_variants,
        out_path,
        qc_config=qc_config,
        priors=priors,
        ocr_fn=ocr_fn,
    )
    return res.verify_report
