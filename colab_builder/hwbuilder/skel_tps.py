"""Thin-Plate Spline (TPS) non-rigid alignment for template-guided stroke ordering."""

from __future__ import annotations

from typing import Sequence

import numpy as np

from hwbuilder.skel_graph import polyline_length


def _tps_kernel(r2: np.ndarray) -> np.ndarray:
    """Thin-plate spline radial basis function U(r) = r^2 * log(r^2)."""
    out = np.zeros_like(r2, dtype=np.float64)
    nz = r2 > 1e-12
    out[nz] = r2[nz] * np.log(r2[nz])
    return out


def fit_tps(
    src_ctrl: np.ndarray,
    dst_ctrl: np.ndarray,
    reg: float = 0.08,
) -> tuple[np.ndarray, np.ndarray]:
    """Fit regularized 2D Thin-Plate Spline mapping `src_ctrl (M,2) -> dst_ctrl (M,2)`."""
    src = np.asarray(src_ctrl, dtype=np.float64)
    dst = np.asarray(dst_ctrl, dtype=np.float64)
    m = len(src)
    if m < 3:
        return src, np.zeros((m + 3, 2), dtype=np.float64)

    diff = src[:, None, :] - src[None, :, :]
    r2 = np.sum(diff * diff, axis=-1)
    K = _tps_kernel(r2) + reg * np.eye(m, dtype=np.float64)
    P = np.hstack([np.ones((m, 1), dtype=np.float64), src])

    L = np.zeros((m + 3, m + 3), dtype=np.float64)
    L[:m, :m] = K
    L[:m, m:] = P
    L[m:, :m] = P.T

    Y = np.zeros((m + 3, 2), dtype=np.float64)
    Y[:m] = dst

    try:
        weights = np.linalg.solve(L, Y)
    except np.linalg.LinAlgError:
        weights, *_ = np.linalg.lstsq(L, Y, rcond=None)
    return src, weights


def apply_tps(pts: np.ndarray, ctrl: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Evaluate fitted 2D TPS at query points `pts (N, 2)`."""
    p = np.asarray(pts, dtype=np.float64)
    m = len(ctrl)
    if m < 3 or np.allclose(weights, 0.0):
        return p.copy()
    diff = p[:, None, :] - ctrl[None, :, :]
    r2 = np.sum(diff * diff, axis=-1)
    U = _tps_kernel(r2)
    P = np.hstack([np.ones((len(p), 1), dtype=np.float64), p])
    return U @ weights[:m] + P @ weights[m:]


def _normalize_point_set(pts: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Normalize point set into `[0, 1]` preserving aspect ratio. Returns `(norm, min_xy, scale)`."""
    min_xy = pts.min(axis=0)
    span = pts.max(axis=0) - min_xy
    scale = max(float(span.max()), 1e-6)
    offset = 0.5 * (scale - span)
    norm = (pts - min_xy + offset) / scale
    return norm, min_xy - offset, scale


def sample_polyline_fixed(pts: np.ndarray, n_samples: int) -> np.ndarray:
    if len(pts) < 2 or n_samples <= 2:
        if len(pts) >= 2 and n_samples == 2:
            return np.vstack([pts[0].astype(np.float64), pts[-1].astype(np.float64)])
        return pts.astype(np.float64)
    diffs = np.diff(pts.astype(np.float64), axis=0)
    seg_lens = np.hypot(diffs[:, 0], diffs[:, 1])
    cum = np.concatenate([[0.0], np.cumsum(seg_lens)])
    total = float(cum[-1])
    if total < 1e-6:
        return np.repeat(pts[:1].astype(np.float64), n_samples, axis=0)
    ts = np.linspace(0.0, total, n_samples)
    xs = np.interp(ts, cum, pts[:, 0])
    ys = np.interp(ts, cum, pts[:, 1])
    return np.column_stack([xs, ys])


def align_template_tps(
    skel_points_xy: np.ndarray,
    template_strokes: Sequence[np.ndarray],
    cfg,
) -> tuple[list[np.ndarray], float]:
    """Non-rigidly align ordered template strokes onto scanned skeleton points via iterative TPS."""
    if len(skel_points_xy) < 4 or not template_strokes:
        return [], 1.0

    skel_norm, skel_origin, skel_scale = _normalize_point_set(skel_points_xy.astype(np.float64))

    tpl_arrays = [np.asarray(s, dtype=np.float64) for s in template_strokes if len(s) >= 2]
    if not tpl_arrays:
        return [], 1.0
    tpl_all = np.vstack(tpl_arrays)
    _, tpl_origin, tpl_scale = _normalize_point_set(tpl_all)

    norm_tpl = [(s - tpl_origin) / tpl_scale for s in tpl_arrays]
    per_stroke = max(3, min(8, 48 // max(1, len(norm_tpl))))
    ctrl_src = np.vstack([sample_polyline_fixed(s, per_stroke) for s in norm_tpl])
    if len(ctrl_src) > 64:
        idx = np.linspace(0, len(ctrl_src) - 1, 64).round().astype(int)
        ctrl_src = ctrl_src[idx]

    if len(skel_norm) > 400:
        s_idx = np.linspace(0, len(skel_norm) - 1, 400).round().astype(int)
        skel_sub = skel_norm[s_idx]
    else:
        skel_sub = skel_norm

    warped_ctrl = ctrl_src.copy()
    ctrl_basis = ctrl_src
    weights = np.zeros((len(ctrl_src) + 3, 2), dtype=np.float64)

    for it in range(max(1, cfg.tps_iterations)):
        d2 = np.sum((warped_ctrl[:, None, :] - skel_sub[None, :, :]) ** 2, axis=-1)
        nn_idx = np.argmin(d2, axis=1)
        targets = skel_sub[nn_idx]
        reg = cfg.tps_reg * (1.8 if it == 0 else 1.0)
        ctrl_basis, weights = fit_tps(ctrl_src, targets, reg=reg)
        warped_ctrl = apply_tps(ctrl_src, ctrl_basis, weights)

    aligned_norm: list[np.ndarray] = []
    residuals: list[float] = []
    for s in norm_tpl:
        dense = sample_polyline_fixed(s, max(6, min(28, int(round(polyline_length(s) * 28)) + 4)))
        warped = apply_tps(dense, ctrl_basis, weights)
        d2 = np.sum((warped[:, None, :] - skel_sub[None, :, :]) ** 2, axis=-1)
        nn_idx = np.argmin(d2, axis=1)
        nn_dist = np.sqrt(d2[np.arange(len(warped)), nn_idx])
        residuals.extend(nn_dist.tolist())

        snapped = warped.copy()
        close = nn_dist <= cfg.tps_snap_radius_norm
        if np.any(close):
            snapped[close] = (
                (1.0 - cfg.tps_snap_blend) * warped[close]
                + cfg.tps_snap_blend * skel_sub[nn_idx[close]]
            )
        if len(snapped) >= 4:
            smoothed = snapped.copy()
            smoothed[1:-1] = 0.25 * snapped[:-2] + 0.5 * snapped[1:-1] + 0.25 * snapped[2:]
            snapped = smoothed
        aligned_norm.append(snapped)

    aligned_all = np.vstack(aligned_norm)
    d2_rev = np.sum((skel_sub[:, None, :] - aligned_all[None, :, :]) ** 2, axis=-1)
    rev_dist = np.sqrt(np.min(d2_rev, axis=1))
    mean_res = 0.5 * (float(np.mean(residuals)) + float(np.mean(rev_dist)))

    aligned_img = [s * skel_scale + skel_origin for s in aligned_norm]
    return aligned_img, mean_res
