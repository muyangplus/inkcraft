"""Iterative segment-projected RDP simplification, resampling, and 0..1000 normalization."""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from hwbuilder.skel_tps import sample_polyline_fixed


def rdp_simplify(pts: np.ndarray, epsilon: float) -> np.ndarray:
    """Iterative Ramer-Douglas-Peucker simplification using clamped segment distances."""
    arr = np.asarray(pts, dtype=np.float64)
    n = len(arr)
    if n <= 2 or epsilon <= 0.0:
        return arr

    keep = np.zeros(n, dtype=bool)
    keep[0] = True
    keep[-1] = True
    stack = [(0, n - 1)]
    eps_sq = float(epsilon) * float(epsilon)

    while stack:
        i0, i1 = stack.pop()
        if i1 <= i0 + 1:
            continue
        p0 = arr[i0]
        p1 = arr[i1]
        seg = p1 - p0
        seg_len_sq = float(seg[0] * seg[0] + seg[1] * seg[1])
        sub = arr[i0 + 1 : i1] - p0
        if seg_len_sq <= 1e-12:
            dist_sq = sub[:, 0] ** 2 + sub[:, 1] ** 2
        else:
            t = np.clip((sub[:, 0] * seg[0] + sub[:, 1] * seg[1]) / seg_len_sq, 0.0, 1.0)
            proj_x = t * seg[0]
            proj_y = t * seg[1]
            dist_sq = (sub[:, 0] - proj_x) ** 2 + (sub[:, 1] - proj_y) ** 2
        rel_max = int(np.argmax(dist_sq))
        if float(dist_sq[rel_max]) > eps_sq:
            idx = i0 + 1 + rel_max
            keep[idx] = True
            stack.append((i0, idx))
            stack.append((idx, i1))

    return arr[keep]


def resample_stroke(
    pts: np.ndarray,
    min_dist: float = 4.0,
    max_dist: float = 55.0,
    max_points: int = 110,
) -> np.ndarray:
    """Ensure every segment satisfies `min_dist <= d <= max_dist` and point count <= `max_points`."""
    arr = np.asarray(pts, dtype=np.float64)
    if len(arr) < 2:
        return arr

    sub: list[np.ndarray] = [arr[0]]
    for i in range(1, len(arr)):
        p0, p1 = sub[-1], arr[i]
        d = float(np.linalg.norm(p1 - p0))
        if d > max_dist:
            steps = int(math.ceil(d / max_dist))
            for k in range(1, steps + 1):
                t = k / float(steps)
                sub.append(p0 * (1.0 - t) + p1 * t)
        elif d >= min_dist or i == len(arr) - 1:
            sub.append(p1)
    res = np.asarray(sub, dtype=np.float64)
    if len(res) < 2:
        res = np.vstack([arr[0], arr[-1]])

    if len(res) > max_points:
        res = sample_polyline_fixed(res, max_points)
    return res


def normalize_strokes_to_1000(
    strokes: Sequence[np.ndarray],
    cfg,
) -> list[np.ndarray]:
    """Normalize strokes preserving aspect ratio into `cfg.target_box` within `0..1000` int16."""
    valid = [np.asarray(s, dtype=np.float64) for s in strokes if len(s) >= 2]
    if not valid:
        return []

    all_pts = np.vstack(valid)
    min_xy = all_pts.min(axis=0)
    max_xy = all_pts.max(axis=0)
    span = np.maximum(max_xy - min_xy, 1e-6)

    bx0, by0, bx1, by1 = cfg.target_box
    box_w = float(bx1 - bx0)
    box_h = float(by1 - by0)
    scale = min(box_w / float(span[0]), box_h / float(span[1]))

    scaled_w = float(span[0]) * scale
    scaled_h = float(span[1]) * scale
    ox = bx0 + 0.5 * (box_w - scaled_w)
    oy = by0 + 0.5 * (box_h - scaled_h)

    out: list[np.ndarray] = []
    for s in valid[:64]:
        mapped = np.empty_like(s)
        mapped[:, 0] = (s[:, 0] - min_xy[0]) * scale + ox
        mapped[:, 1] = (s[:, 1] - min_xy[1]) * scale + oy
        simp = rdp_simplify(mapped, cfg.rdp_epsilon_u)
        resamp = resample_stroke(
            simp,
            min_dist=cfg.min_point_dist_u,
            max_dist=cfg.max_point_dist_u,
            max_points=cfg.max_points_per_stroke,
        )
        rounded = np.clip(np.rint(resamp), 0, 1000).astype(np.int16)
        if len(rounded) >= 2:
            out.append(rounded)

    total_pts = sum(len(s) for s in out)
    if total_pts > cfg.max_total_points and out:
        ratio = cfg.max_total_points / float(total_pts)
        capped: list[np.ndarray] = []
        for s in out:
            n_keep = max(2, int(len(s) * ratio))
            if len(s) > n_keep:
                s = np.clip(
                    np.rint(sample_polyline_fixed(s.astype(np.float64), n_keep)), 0, 1000
                ).astype(np.int16)
            capped.append(s)
        # Strictly trim any remaining overshoot due to min-2 floors or rounding
        cur_total = sum(len(s) for s in capped)
        while cur_total > cfg.max_total_points:
            longest_idx = max(range(len(capped)), key=lambda idx: len(capped[idx]))
            cur_len = len(capped[longest_idx])
            if cur_len <= 2:
                break
            reduce_by = min(cur_len - 2, cur_total - cfg.max_total_points)
            target_len = cur_len - reduce_by
            capped[longest_idx] = np.clip(
                np.rint(sample_polyline_fixed(capped[longest_idx].astype(np.float64), target_len)),
                0,
                1000,
            ).astype(np.int16)
            cur_total -= reduce_by
        out = capped

    return out
