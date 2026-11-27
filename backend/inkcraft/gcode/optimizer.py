"""Single-line path optimizer: RDP simplification, bounds check, reversible greedy + 2-opt, micro-join."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from inkcraft.api.schemas import (
    ComposedPage,
    OptimizeConfig,
    PageStats,
    StrokeItem,
    Vec2,
)


class WorkspaceBoundsError(ValueError):
    """Raised when strokes or framing bbox exceed MachineProfile.workspace_mm."""

    def __init__(self, message: str, violations: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.violations = violations


def _dedup_points(pts: np.ndarray, eps: float = 1e-5) -> np.ndarray:
    if len(pts) <= 1:
        return pts
    diffs = np.diff(pts, axis=0)
    dists = np.hypot(diffs[:, 0], diffs[:, 1])
    keep = np.empty(len(pts), dtype=bool)
    keep[0] = True
    keep[1:] = dists > eps
    out = pts[keep]
    if len(out) == 1 and len(pts) >= 2:
        # Preserve tiny non-zero segment if endpoints differ
        if np.hypot(*(pts[-1] - pts[0])) > 0.0:
            return np.vstack([pts[0], pts[-1]])
    return out


def rdp_simplify(pts: np.ndarray, tol: float) -> np.ndarray:
    """Iterative Ramer-Douglas-Peucker polyline simplification."""
    pts = _dedup_points(np.asarray(pts, dtype=np.float64))
    n = len(pts)
    if n <= 2 or tol <= 0.0:
        return pts

    tol_sq = tol * tol
    keep = np.zeros(n, dtype=bool)
    keep[0] = True
    keep[n - 1] = True

    stack: list[tuple[int, int]] = [(0, n - 1)]
    while stack:
        start, end = stack.pop()
        if end - start <= 1:
            continue
        p0 = pts[start]
        p1 = pts[end]
        seg = p1 - p0
        seg_len_sq = float(seg[0] * seg[0] + seg[1] * seg[1])

        sub = pts[start + 1 : end]
        if seg_len_sq < 1e-12:
            d = sub - p0
            dist_sq = d[:, 0] * d[:, 0] + d[:, 1] * d[:, 1]
        else:
            # Perpendicular distance squared to segment [p0, p1]
            v = sub - p0
            t = np.clip((v[:, 0] * seg[0] + v[:, 1] * seg[1]) / seg_len_sq, 0.0, 1.0)
            proj_x = p0[0] + t * seg[0]
            proj_y = p0[1] + t * seg[1]
            dx = sub[:, 0] - proj_x
            dy = sub[:, 1] - proj_y
            dist_sq = dx * dx + dy * dy

        rel_idx = int(np.argmax(dist_sq))
        if float(dist_sq[rel_idx]) > tol_sq:
            split = start + 1 + rel_idx
            keep[split] = True
            stack.append((start, split))
            stack.append((split, end))

    return pts[keep]


def check_bounds(
    page: ComposedPage,
    workspace_mm: Vec2,
    *,
    tol_mm: float = 0.05,
) -> list[dict[str, Any]]:
    """Return a list of workspace bound violations (empty if all points are in bounds)."""
    violations: list[dict[str, Any]] = []
    max_x = float(workspace_mm.x) + tol_mm
    max_y = float(workspace_mm.y) + tol_mm
    min_x = -tol_mm
    min_y = -tol_mm

    per_block: dict[str, dict[str, Any]] = {}
    for stroke in page.strokes:
        pts = stroke.pts
        if len(pts) < 2:
            continue
        xs = pts[0::2]
        ys = pts[1::2]
        s_min_x, s_max_x = min(xs), max(xs)
        s_min_y, s_max_y = min(ys), max(ys)
        if s_min_x < min_x or s_max_x > max_x or s_min_y < min_y or s_max_y > max_y:
            bid = stroke.block_id or f"stroke_{stroke.id}"
            entry = per_block.get(bid)
            if entry is None:
                per_block[bid] = {
                    "block_id": stroke.block_id,
                    "stroke_id": stroke.id,
                    "min_x": round(s_min_x, 2),
                    "max_x": round(s_max_x, 2),
                    "min_y": round(s_min_y, 2),
                    "max_y": round(s_max_y, 2),
                    "workspace_mm": {"x": workspace_mm.x, "y": workspace_mm.y},
                }
            else:
                entry["min_x"] = round(min(entry["min_x"], s_min_x), 2)
                entry["max_x"] = round(max(entry["max_x"], s_max_x), 2)
                entry["min_y"] = round(min(entry["min_y"], s_min_y), 2)
                entry["max_y"] = round(max(entry["max_y"], s_max_y), 2)

    violations.extend(per_block.values())
    return violations


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _optimize_reversible_group(
    items: list[tuple[StrokeItem, np.ndarray]],
    start_xy: tuple[float, float],
    *,
    do_2opt: bool = True,
) -> list[tuple[StrokeItem, np.ndarray]]:
    """Greedy nearest-neighbor + 2-opt travel minimization for reversible strokes."""
    n = len(items)
    if n <= 1:
        if n == 1:
            item, arr = items[0]
            d_fwd = _dist(start_xy, (float(arr[0, 0]), float(arr[0, 1])))
            d_rev = _dist(start_xy, (float(arr[-1, 0]), float(arr[-1, 1])))
            if d_rev + 1e-6 < d_fwd:
                return [(item, arr[::-1].copy())]
        return items

    # 1. Greedy nearest neighbor with orientation choice
    remaining = list(range(n))
    starts = [(float(arr[0, 0]), float(arr[0, 1])) for _, arr in items]
    ends = [(float(arr[-1, 0]), float(arr[-1, 1])) for _, arr in items]

    # Ordered tour as list of (orig_idx, reversed_flag)
    tour: list[tuple[int, bool]] = []
    cur = start_xy
    while remaining:
        best_pos = 0
        best_idx = remaining[0]
        best_rev = False
        best_d = float("inf")
        cx, cy = cur
        for pos, idx in enumerate(remaining):
            sx, sy = starts[idx]
            d_fwd = (sx - cx) * (sx - cx) + (sy - cy) * (sy - cy)
            if d_fwd < best_d:
                best_d = d_fwd
                best_pos = pos
                best_idx = idx
                best_rev = False
            ex, ey = ends[idx]
            d_rev = (ex - cx) * (ex - cx) + (ey - cy) * (ey - cy)
            if d_rev < best_d:
                best_d = d_rev
                best_pos = pos
                best_idx = idx
                best_rev = True
        remaining.pop(best_pos)
        tour.append((best_idx, best_rev))
        cur = starts[best_idx] if best_rev else ends[best_idx]

    # 2. 2-opt local refinement (bounded for interactive latency)
    if do_2opt and 3 <= n <= 1200:
        def entry_pt(step: tuple[int, bool]) -> tuple[float, float]:
            idx, rev = step
            return ends[idx] if rev else starts[idx]

        def exit_pt(step: tuple[int, bool]) -> tuple[float, float]:
            idx, rev = step
            return starts[idx] if rev else ends[idx]

        max_passes = 8 if n <= 400 else 3
        for _ in range(max_passes):
            improved = False
            # Also try single-stroke flip if it shortens adjacent travels
            for i in range(n):
                prev_pt = start_xy if i == 0 else exit_pt(tour[i - 1])
                idx, rev = tour[i]
                cur_cost = _dist(prev_pt, entry_pt((idx, rev)))
                alt_cost = _dist(prev_pt, entry_pt((idx, not rev)))
                if i + 1 < n:
                    nxt_pt = entry_pt(tour[i + 1])
                    cur_cost += _dist(exit_pt((idx, rev)), nxt_pt)
                    alt_cost += _dist(exit_pt((idx, not rev)), nxt_pt)
                if alt_cost + 1e-4 < cur_cost:
                    tour[i] = (idx, not rev)
                    improved = True

            # Standard 2-opt subsequence reversal (reversing order AND flipping each stroke in slice)
            for i in range(n - 1):
                prev_pt = start_xy if i == 0 else exit_pt(tour[i - 1])
                a_entry = entry_pt(tour[i])
                d_before_i = _dist(prev_pt, a_entry)
                for j in range(i + 1, n):
                    # If we reverse tour[i..j] and flip each stroke's direction:
                    # new first element is flipped tour[j], whose entry is old exit_pt(tour[j])
                    # new last element is flipped tour[i], whose exit is old entry_pt(tour[i])
                    old_cost = d_before_i
                    new_cost = _dist(prev_pt, exit_pt(tour[j]))
                    if j + 1 < n:
                        nxt_pt = entry_pt(tour[j + 1])
                        old_cost += _dist(exit_pt(tour[j]), nxt_pt)
                        new_cost += _dist(a_entry, nxt_pt)
                    if new_cost + 1e-4 < old_cost:
                        tour[i : j + 1] = [(idx, not rev) for idx, rev in reversed(tour[i : j + 1])]
                        improved = True
                        a_entry = entry_pt(tour[i])
                        d_before_i = _dist(prev_pt, a_entry)
            if not improved:
                break

    result: list[tuple[StrokeItem, np.ndarray]] = []
    for idx, rev in tour:
        item, arr = items[idx]
        result.append((item, arr[::-1].copy() if rev else arr))
    return result


def _join_reversible_group(
    items: list[tuple[StrokeItem, np.ndarray]],
    join_tol_mm: float,
) -> list[tuple[StrokeItem, np.ndarray]]:
    """Merge consecutive strokes in a reversible group whose end->start gap <= join_tol_mm."""
    if not items or join_tol_mm <= 0.0:
        return items
    merged: list[tuple[StrokeItem, np.ndarray]] = [items[0]]
    for item, arr in items[1:]:
        prev_item, prev_arr = merged[-1]
        gap = _dist(
            (float(prev_arr[-1, 0]), float(prev_arr[-1, 1])),
            (float(arr[0, 0]), float(arr[0, 1])),
        )
        if gap <= join_tol_mm and prev_item.kind == item.kind and prev_item.block_id == item.block_id:
            if gap < 1e-4:
                combined = np.vstack([prev_arr, arr[1:]])
            else:
                combined = np.vstack([prev_arr, arr])
            merged[-1] = (prev_item, combined)
        else:
            merged.append((item, arr))
    return merged


def _compute_stats_and_bbox(
    strokes: list[StrokeItem],
    *,
    feed_draw: float = 2400.0,
    feed_travel: float = 5000.0,
    dwell_s: float = 0.12,
) -> tuple[list[float], PageStats]:
    if not strokes:
        return [0.0, 0.0, 0.0, 0.0], PageStats()

    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")
    draw_mm = 0.0
    travel_mm = 0.0
    prev_end: tuple[float, float] = (0.0, 0.0)

    for s in strokes:
        pts = s.pts
        if len(pts) < 4:
            continue
        x0, y0 = pts[0], pts[1]
        travel_mm += math.hypot(x0 - prev_end[0], y0 - prev_end[1])
        if x0 < min_x:
            min_x = x0
        if x0 > max_x:
            max_x = x0
        if y0 < min_y:
            min_y = y0
        if y0 > max_y:
            max_y = y0
        px, py = x0, y0
        for i in range(2, len(pts), 2):
            nx, ny = pts[i], pts[i + 1]
            draw_mm += math.hypot(nx - px, ny - py)
            if nx < min_x:
                min_x = nx
            if nx > max_x:
                max_x = nx
            if ny < min_y:
                min_y = ny
            if ny > max_y:
                max_y = ny
            px, py = nx, ny
        prev_end = (px, py)

    if min_x == float("inf"):
        return [0.0, 0.0, 0.0, 0.0], PageStats()

    v_draw = max(1.0, feed_draw / 60.0)
    v_travel = max(1.0, feed_travel / 60.0)
    est_s = (draw_mm / v_draw) + (travel_mm / v_travel) + len(strokes) * (2.0 * dwell_s)

    bbox = [round(min_x, 2), round(min_y, 2), round(max_x, 2), round(max_y, 2)]
    stats = PageStats(
        draw_mm=round(draw_mm, 2),
        travel_mm=round(travel_mm, 2),
        stroke_count=len(strokes),
        est_s=round(est_s, 2),
    )
    return bbox, stats


def optimize_page(page: ComposedPage, cfg: OptimizeConfig | None = None) -> ComposedPage:
    """Simplify polylines, optimize travel ONLY on reversible=True runs, and join micro-gaps.

    Strictly preserves stroke order and direction for all reversible=False strokes
    (text, formula, etc.).
    """
    cfg = cfg or OptimizeConfig()

    # Step 1: Simplify strokes into numpy arrays
    simplified: list[tuple[StrokeItem, np.ndarray]] = []
    for s in page.strokes:
        if len(s.pts) < 4:
            continue
        raw = np.asarray(s.pts, dtype=np.float64).reshape(-1, 2)
        arr = rdp_simplify(raw, cfg.simplify_tol_mm)
        if len(arr) < 2:
            continue
        simplified.append((s, arr))

    # Step 2: Process contiguous runs; only optimize reversible=True runs
    output_pairs: list[tuple[StrokeItem, np.ndarray]] = []
    cur_xy: tuple[float, float] = (0.0, 0.0)

    i = 0
    total = len(simplified)
    while i < total:
        s_item, arr = simplified[i]
        if not s_item.reversible:
            # Strict order and direction preservation
            output_pairs.append((s_item, arr))
            cur_xy = (float(arr[-1, 0]), float(arr[-1, 1]))
            i += 1
            continue

        # Collect contiguous reversible run with same (block_id, kind)
        group: list[tuple[StrokeItem, np.ndarray]] = [(s_item, arr)]
        j = i + 1
        while j < total:
            nxt_item, nxt_arr = simplified[j]
            if (
                nxt_item.reversible
                and nxt_item.block_id == s_item.block_id
                and nxt_item.kind == s_item.kind
            ):
                group.append((nxt_item, nxt_arr))
                j += 1
            else:
                break

        if cfg.travel == "greedy_2opt":
            group = _optimize_reversible_group(group, cur_xy, do_2opt=True)
        if cfg.join_tol_mm > 0.0:
            group = _join_reversible_group(group, cfg.join_tol_mm)

        output_pairs.extend(group)
        if group:
            last_arr = group[-1][1]
            cur_xy = (float(last_arr[-1, 0]), float(last_arr[-1, 1]))
        i = j

    # Step 3: Rebuild StrokeItems with sequential IDs and clean rounding
    final_strokes: list[StrokeItem] = []
    for new_id, (orig, arr) in enumerate(output_pairs):
        flat_pts = [round(float(v), 3) for v in arr.reshape(-1)]
        final_strokes.append(
            StrokeItem(
                id=new_id,
                block_id=orig.block_id,
                kind=orig.kind,
                reversible=orig.reversible,
                pts=flat_pts,
            )
        )

    bbox, stats = _compute_stats_and_bbox(final_strokes)
    return ComposedPage(
        page_index=page.page_index,
        width_mm=page.width_mm,
        height_mm=page.height_mm,
        bbox=bbox,
        strokes=final_strokes,
        stats=stats,
        fallback_glyphs=list(page.fallback_glyphs),
        missing_glyphs=list(page.missing_glyphs),
        applied_rule_label=page.applied_rule_label,
        background_id=page.background_id,
        background_opacity=page.background_opacity,
        writer_id=page.writer_id,
        placed_blocks=list(page.placed_blocks),
    )
