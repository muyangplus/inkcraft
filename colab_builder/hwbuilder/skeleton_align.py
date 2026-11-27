"""Offline static glyph bitmap -> ordered single-line strokes in 0..1000 coordinates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

from hwbuilder.priors import load_builtin_priors, load_makemeahanzi_priors
from hwbuilder.skel_graph import (
    _chain_endpoints_meta,
    _join_pair,
    extract_contracted_skeleton_chains,
    merge_chains_continuous,
    order_and_orient_heuristic as _order_and_orient_heuristic,
    polyline_length as _polyline_length,
    smooth_preserve_corners,
)
from hwbuilder.skel_morph import (
    chamfer_distance_transform,
    morph_close_3x3,
    pixel_neighbors as _pixel_neighbors,
    prune_skeleton_spurs,
    zhang_suen_thin,
)
from hwbuilder.skel_resample import normalize_strokes_to_1000, rdp_simplify, resample_stroke
from hwbuilder.skel_tps import (
    _normalize_point_set,
    _tps_kernel,
    align_template_tps,
    apply_tps,
    fit_tps,
    sample_polyline_fixed as _sample_polyline_fixed,
)


@dataclass
class VectorizeConfig:
    """Configuration for offline bitmap-to-stroke vectorization."""

    spur_length_factor: float = 1.2
    min_stroke_length_px: float = 4.0
    max_junction_turn_deg: float = 55.0
    tps_iterations: int = 3
    tps_reg: float = 0.08
    tps_snap_blend: float = 0.55
    tps_snap_radius_norm: float = 0.14
    tps_max_residual: float = 0.16
    rdp_epsilon_u: float = 2.6
    min_point_dist_u: float = 4.0
    max_point_dist_u: float = 38.0
    max_points_per_stroke: int = 110
    max_total_points: int = 440
    target_box: tuple[int, int, int, int] = (60, 60, 940, 940)


@dataclass
class VectorizeResult:
    """Result of vectorizing a single static glyph bitmap."""

    char: str
    strokes: list[np.ndarray]
    method: str  # "tps_template" | "heuristic_trace" | "empty"
    quality: float
    estimated_stroke_width_px: float
    residual_error: float = 0.0
    warnings: list[str] = field(default_factory=list)


def vectorize_glyph(
    bitmap: np.ndarray,
    char: str = "?",
    *,
    template_strokes: Sequence[np.ndarray] | None = None,
    priors: Mapping[str, Sequence[np.ndarray]] | None = None,
    config: VectorizeConfig | None = None,
) -> VectorizeResult:
    """Convert an offline binary or grayscale glyph bitmap into clean `0..1000` single-line strokes."""
    cfg = config or VectorizeConfig()
    arr = np.asarray(bitmap)
    if arr.ndim == 3:
        arr = arr.mean(axis=2)
    mask = arr.astype(bool) if arr.dtype == bool else (arr < 128)

    if int(mask.sum()) < 4:
        return VectorizeResult(
            char=char,
            strokes=[],
            method="empty",
            quality=0.0,
            estimated_stroke_width_px=0.0,
            warnings=["empty_bitmap"],
        )

    if int(mask.sum()) >= 12:
        mask = morph_close_3x3(mask)

    dt = chamfer_distance_transform(mask)
    skel = zhang_suen_thin(mask)
    if not skel.any():
        skel = mask.copy()

    skel_dt = dt[skel]
    w_stroke = float(max(1.5, 2.0 * np.median(skel_dt))) if skel_dt.size > 0 else 2.0

    pruned = prune_skeleton_spurs(skel, max_spur_len_px=cfg.spur_length_factor * w_stroke)
    if pruned.any():
        skel = pruned

    tpl = template_strokes
    if tpl is None and priors is not None and char in priors:
        tpl = priors[char]
    if tpl is None:
        builtin = load_builtin_priors()
        if char in builtin:
            tpl = builtin[char]

    ys, xs = np.nonzero(skel)
    skel_xy = np.column_stack([xs, ys]).astype(np.float64)
    warnings: list[str] = []

    if tpl is not None and len(tpl) > 0 and len(skel_xy) >= 6:
        aligned_img, residual = align_template_tps(skel_xy, tpl, cfg)
        if aligned_img and residual <= cfg.tps_max_residual:
            norm_strokes = normalize_strokes_to_1000(aligned_img, cfg)
            if norm_strokes:
                quality = float(max(0.35, min(1.0, 1.0 - residual * 2.5)))
                return VectorizeResult(
                    char=char,
                    strokes=norm_strokes,
                    method="tps_template",
                    quality=round(quality, 4),
                    estimated_stroke_width_px=round(w_stroke, 2),
                    residual_error=round(residual, 4),
                    warnings=warnings,
                )
        warnings.append(f"tps_residual_high:{residual:.3f}")

    chains = extract_contracted_skeleton_chains(skel)
    if not chains:
        if len(skel_xy) >= 2:
            chains = [np.vstack([skel_xy[0], skel_xy[-1]])]
        else:
            p = skel_xy[0]
            chains = [np.vstack([p, p + np.array([1.0, 1.0])])]

    merged = merge_chains_continuous(chains, scale_up=1)
    ordered = _order_and_orient_heuristic(merged)
    smoothed = [smooth_preserve_corners(st, corner_deg=55.0, iterations=2) for st in ordered]
    norm_strokes = normalize_strokes_to_1000(smoothed, cfg)
    quality = 0.78 if not warnings else 0.62

    return VectorizeResult(
        char=char,
        strokes=norm_strokes,
        method="heuristic_trace",
        quality=round(quality, 4),
        estimated_stroke_width_px=round(w_stroke, 2),
        residual_error=0.0,
        warnings=warnings,
    )


__all__ = [
    "VectorizeConfig",
    "VectorizeResult",
    "_chain_endpoints_meta",
    "_join_pair",
    "_normalize_point_set",
    "_order_and_orient_heuristic",
    "_pixel_neighbors",
    "_polyline_length",
    "_sample_polyline_fixed",
    "_tps_kernel",
    "align_template_tps",
    "apply_tps",
    "chamfer_distance_transform",
    "extract_contracted_skeleton_chains",
    "fit_tps",
    "load_builtin_priors",
    "load_makemeahanzi_priors",
    "merge_chains_continuous",
    "morph_close_3x3",
    "normalize_strokes_to_1000",
    "prune_skeleton_spurs",
    "rdp_simplify",
    "resample_stroke",
    "smooth_preserve_corners",
    "vectorize_glyph",
    "zhang_suen_thin",
]
