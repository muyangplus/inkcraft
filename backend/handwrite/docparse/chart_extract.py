"""Vector chart extraction from PyMuPDF drawings and single-line raster chart vectorization."""

from __future__ import annotations

from collections import OrderedDict
import math
from pathlib import Path
import threading
from typing import Iterable

import pymupdf as fitz
import numpy as np
from PIL import Image, ImageFilter
from shapely.geometry import LineString, Polygon

from handwrite.api.schemas import ChartConfig
from handwrite.docparse.docir import ChartData

PT_TO_MM = 25.4 / 72.0

_RASTER_VEC_LOCK = threading.Lock()
_RASTER_VEC_CACHE: OrderedDict[tuple[object, ...], list[np.ndarray]] = OrderedDict()
_MAX_RASTER_CACHE = 64


def _sample_cubic_bezier(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    steps: int = 8,
) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for i in range(steps + 1):
        t = i / steps
        mt = 1.0 - t
        x = (
            mt**3 * p0[0]
            + 3.0 * mt**2 * t * p1[0]
            + 3.0 * mt * t**2 * p2[0]
            + t**3 * p3[0]
        )
        y = (
            mt**3 * p0[1]
            + 3.0 * mt**2 * t * p1[1]
            + 3.0 * mt * t**2 * p2[1]
            + t**3 * p3[1]
        )
        pts.append((x, y))
    return pts


def _pt_in_bbox(x: float, y: float, bbox: list[float], pad: float = 0.5) -> bool:
    return (bbox[0] - pad) <= x <= (bbox[2] + pad) and (bbox[1] - pad) <= y <= (bbox[3] + pad)


def _polyline_intersects_bbox(pts: list[tuple[float, float]], bbox: list[float]) -> bool:
    if not pts:
        return False
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return not (max(xs) < bbox[0] or min(xs) > bbox[2] or max(ys) < bbox[1] or min(ys) > bbox[3])


def _normalize_points(
    pts: list[tuple[float, float]], bbox_mm: list[float]
) -> list[tuple[float, float]]:
    x0, y0, x1, y1 = bbox_mm
    w = max(1e-3, x1 - x0)
    h = max(1e-3, y1 - y0)
    return [(round((x - x0) / w, 4), round((y - y0) / h, 4)) for x, y in pts]


def extract_pdf_vector_drawings(
    page: fitz.Page,
    clip_mm: list[float] | None = None,
    *,
    normalize: bool = True,
) -> tuple[list[list[tuple[float, float]]], list[list[tuple[float, float]]]]:
    """Extract stroked polylines and filled polygons from a PyMuPDF page inside `clip_mm`.

    When `normalize=True` and `clip_mm` is provided, coordinates are normalized to `0..1`
    relative to `clip_mm` so charts scale seamlessly in both Reflow and Overlay modes.
    """
    polylines: list[list[tuple[float, float]]] = []
    polygons: list[list[tuple[float, float]]] = []

    try:
        drawings = page.get_drawings()
    except Exception:
        return polylines, polygons

    page_bbox = [
        0.0,
        0.0,
        float(page.rect.width) * PT_TO_MM,
        float(page.rect.height) * PT_TO_MM,
    ]
    ref_bbox = clip_mm if clip_mm is not None else page_bbox

    for d in drawings:
        is_fill = d.get("fill") is not None
        is_stroke = d.get("color") is not None
        items = d.get("items") or []
        if not items:
            continue

        current_path: list[tuple[float, float]] = []

        def _flush(closed: bool = False) -> None:
            nonlocal current_path
            if len(current_path) < 2:
                current_path = []
                return
            if clip_mm is not None and not _polyline_intersects_bbox(current_path, clip_mm):
                current_path = []
                return
            out_pts = (
                _normalize_points(current_path, ref_bbox)
                if (normalize and clip_mm is not None)
                else [(round(p[0], 3), round(p[1], 3)) for p in current_path]
            )
            if is_fill and (closed or len(out_pts) >= 3):
                if out_pts[0] != out_pts[-1]:
                    out_pts.append(out_pts[0])
                polygons.append(out_pts)
            if is_stroke or not is_fill:
                polylines.append(out_pts)
            current_path = []

        for item in items:
            op = item[0]
            if op == "l":
                p1 = (float(item[1].x) * PT_TO_MM, float(item[1].y) * PT_TO_MM)
                p2 = (float(item[2].x) * PT_TO_MM, float(item[2].y) * PT_TO_MM)
                if current_path and math.hypot(current_path[-1][0] - p1[0], current_path[-1][1] - p1[1]) < 0.05:
                    current_path.append(p2)
                else:
                    _flush(False)
                    current_path = [p1, p2]
            elif op == "c":
                p0 = (float(item[1].x) * PT_TO_MM, float(item[1].y) * PT_TO_MM)
                p1 = (float(item[2].x) * PT_TO_MM, float(item[2].y) * PT_TO_MM)
                p2 = (float(item[3].x) * PT_TO_MM, float(item[3].y) * PT_TO_MM)
                p3 = (float(item[4].x) * PT_TO_MM, float(item[4].y) * PT_TO_MM)
                seg = _sample_cubic_bezier(p0, p1, p2, p3, steps=8)
                if current_path and math.hypot(current_path[-1][0] - seg[0][0], current_path[-1][1] - seg[0][1]) < 0.05:
                    current_path.extend(seg[1:])
                else:
                    _flush(False)
                    current_path = seg
            elif op == "re":
                _flush(False)
                r = item[1]
                x0, y0 = float(r.x0) * PT_TO_MM, float(r.y0) * PT_TO_MM
                x1, y1 = float(r.x1) * PT_TO_MM, float(r.y1) * PT_TO_MM
                # Skip full-page background rectangles
                if abs(x1 - x0) > page_bbox[2] * 0.92 and abs(y1 - y0) > page_bbox[3] * 0.92:
                    continue
                rect_pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
                current_path = rect_pts
                _flush(True)
            elif op == "qu":
                _flush(False)
                q = item[1]
                quad_pts = [
                    (float(q.ul.x) * PT_TO_MM, float(q.ul.y) * PT_TO_MM),
                    (float(q.ur.x) * PT_TO_MM, float(q.ur.y) * PT_TO_MM),
                    (float(q.lr.x) * PT_TO_MM, float(q.lr.y) * PT_TO_MM),
                    (float(q.ll.x) * PT_TO_MM, float(q.ll.y) * PT_TO_MM),
                    (float(q.ul.x) * PT_TO_MM, float(q.ul.y) * PT_TO_MM),
                ]
                current_path = quad_pts
                _flush(True)

        _flush(bool(d.get("closePath", False)))

    return polylines, polygons


def detect_chart_regions_on_page(
    page: fitz.Page,
    exclude_bboxes_mm: Iterable[list[float]] = (),
) -> list[tuple[list[float], ChartData]]:
    """Cluster non-table vector drawings on a PDF page into chart regions."""
    try:
        drawings = page.get_drawings()
    except Exception:
        return []

    page_w = float(page.rect.width) * PT_TO_MM
    page_h = float(page.rect.height) * PT_TO_MM
    excl = list(exclude_bboxes_mm)

    boxes: list[tuple[list[float], int]] = []
    for d in drawings:
        rect = d.get("rect")
        if rect is None:
            continue
        x0, y0 = float(rect.x0) * PT_TO_MM, float(rect.y0) * PT_TO_MM
        x1, y1 = float(rect.x1) * PT_TO_MM, float(rect.y1) * PT_TO_MM
        w, h = x1 - x0, y1 - y0
        if w > page_w * 0.92 and h > page_h * 0.92:
            continue
        if w < 0.3 and h < 0.3:
            continue
        # Skip drawings inside excluded regions (e.g. detected tables)
        cx, cy = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
        if any(_pt_in_bbox(cx, cy, eb, pad=1.0) for eb in excl):
            continue
        item_weight = max(1, len(d.get("items") or []))
        boxes.append(([x0, y0, x1, y1], item_weight))

    if sum(wt for _, wt in boxes) < 4:
        return []

    # Merge overlapping/nearby drawing boxes within 8 mm margin
    clusters: list[tuple[list[float], int]] = []
    margin = 8.0
    for b, wt in boxes:
        merged_idx = -1
        for i, (cb, cnt) in enumerate(clusters):
            if not (
                b[2] + margin < cb[0]
                or b[0] - margin > cb[2]
                or b[3] + margin < cb[1]
                or b[1] - margin > cb[3]
            ):
                cb[0] = min(cb[0], b[0])
                cb[1] = min(cb[1], b[1])
                cb[2] = max(cb[2], b[2])
                cb[3] = max(cb[3], b[3])
                clusters[i] = (cb, cnt + wt)
                merged_idx = i
                break
        if merged_idx < 0:
            clusters.append((list(b), wt))

    # Second pass merge for clusters that became adjacent
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(clusters):
            j = i + 1
            while j < len(clusters):
                a, ca = clusters[i]
                b, cb = clusters[j]
                if not (
                    b[2] + margin < a[0]
                    or b[0] - margin > a[2]
                    or b[3] + margin < a[1]
                    or b[1] - margin > a[3]
                ):
                    a[0] = min(a[0], b[0])
                    a[1] = min(a[1], b[1])
                    a[2] = max(a[2], b[2])
                    a[3] = max(a[3], b[3])
                    clusters[i] = (a, ca + cb)
                    clusters.pop(j)
                    changed = True
                else:
                    j += 1
            i += 1

    results: list[tuple[list[float], ChartData]] = []
    for bbox, count in clusters:
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        if count >= 4 and w >= 25.0 and h >= 18.0:
            polylines, polygons = extract_pdf_vector_drawings(page, clip_mm=bbox, normalize=True)
            if polylines or polygons:
                chart = ChartData(
                    chart_type="vector",
                    vector_polylines=polylines,
                    vector_polygons=polygons,
                    extra={"origin": "pdf_vector", "coord_space": "normalized"},
                )
                results.append(([round(v, 2) for v in bbox], chart))
    return results


def _marching_squares_contours(mask: np.ndarray, threshold: float = 0.5) -> list[list[tuple[float, float]]]:
    """Extract simple closed/open contour polylines from a 2D scalar array using marching squares."""
    h, w = mask.shape
    if h < 2 or w < 2:
        return []

    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    # Lookup edge pairs per 4-bit marching squares cell (TL=8, TR=4, BR=2, BL=1)
    # Edges: 0=top, 1=right, 2=bottom, 3=left
    table: dict[int, list[tuple[int, int]]] = {
        1: [(3, 2)],
        2: [(2, 1)],
        3: [(3, 1)],
        4: [(0, 1)],
        5: [(3, 0), (2, 1)],
        6: [(0, 2)],
        7: [(3, 0)],
        8: [(0, 3)],
        9: [(0, 2)],
        10: [(0, 1), (3, 2)],
        11: [(0, 1)],
        12: [(1, 3)],
        13: [(1, 2)],
        14: [(2, 3)],
    }

    b = (mask >= threshold).astype(np.uint8)
    codes = (b[:-1, :-1] << 3) | (b[:-1, 1:] << 2) | (b[1:, 1:] << 1) | b[1:, :-1]
    ys, xs = np.nonzero((codes > 0) & (codes < 15))

    for y_i, x_i in zip(ys.tolist(), xs.tolist()):
        code = int(codes[y_i, x_i])
        edge_pts = (
            (x_i + 0.5, float(y_i)),
            (float(x_i + 1), y_i + 0.5),
            (x_i + 0.5, float(y_i + 1)),
            (float(x_i), y_i + 0.5),
        )
        for e0, e1 in table[code]:
            segments.append((edge_pts[e0], edge_pts[e1]))

    if not segments:
        return []

    # Chain segments sharing exact half-grid endpoints
    adj: dict[tuple[float, float], list[int]] = {}
    for idx, (p0, p1) in enumerate(segments):
        adj.setdefault(p0, []).append(idx)
        adj.setdefault(p1, []).append(idx)

    used = [False] * len(segments)
    polylines: list[list[tuple[float, float]]] = []

    for idx in range(len(segments)):
        if used[idx]:
            continue
        used[idx] = True
        p0, p1 = segments[idx]
        chain = [p0, p1]

        # Extend forward
        while True:
            cur = chain[-1]
            nxt_idx = -1
            for cand in adj.get(cur, ()):
                if not used[cand]:
                    nxt_idx = cand
                    break
            if nxt_idx < 0:
                break
            used[nxt_idx] = True
            a, b_pt = segments[nxt_idx]
            chain.append(b_pt if a == cur else a)

        # Extend backward
        while True:
            cur = chain[0]
            nxt_idx = -1
            for cand in adj.get(cur, ()):
                if not used[cand]:
                    nxt_idx = cand
                    break
            if nxt_idx < 0:
                break
            used[nxt_idx] = True
            a, b_pt = segments[nxt_idx]
            chain.insert(0, b_pt if a == cur else a)

        if len(chain) >= 3:
            polylines.append(chain)

    return polylines


def _scanline_hatch_mask(
    mask: np.ndarray,
    bbox_mm: list[float],
    spacing_mm: float,
    angle_deg: float,
    zigzag: bool,
    rng: np.random.Generator,
) -> list[np.ndarray]:
    """Generate single-line hatch strokes across True pixels of a boolean mask inside bbox_mm."""
    h, w = mask.shape
    x0, y0, x1, y1 = bbox_mm
    bw = max(1e-3, x1 - x0)
    bh = max(1e-3, y1 - y0)
    cx, cy = 0.5 * (x0 + x1), 0.5 * (y0 + y1)

    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    diag = math.hypot(bw, bh)
    half_d = 0.5 * diag
    step_u = max(0.35, min(bw / max(w, 1), bh / max(h, 1)))
    spacing = max(0.8, float(spacing_mm))

    strokes: list[np.ndarray] = []
    v_vals = np.arange(-half_d + spacing * 0.5, half_d, spacing)
    u_vals = np.arange(-half_d, half_d, step_u)

    prev_end: np.ndarray | None = None
    for row_idx, v in enumerate(v_vals):
        # Sample points along rotated line (u, v) -> page (x, y)
        xs = cx + u_vals * cos_a - v * sin_a
        ys = cy + u_vals * sin_a + v * cos_a

        in_box = (xs >= x0) & (xs <= x1) & (ys >= y0) & (ys <= y1)
        if not np.any(in_box):
            prev_end = None
            continue

        ix = np.clip(((xs - x0) / bw * (w - 1)).astype(np.int32), 0, w - 1)
        iy = np.clip(((ys - y0) / bh * (h - 1)).astype(np.int32), 0, h - 1)
        hits = in_box & mask[iy, ix]

        # Extract contiguous runs
        padded = np.concatenate(([False], hits, [False]))
        diffs = np.diff(padded.astype(np.int8))
        starts = np.nonzero(diffs == 1)[0]
        ends = np.nonzero(diffs == -1)[0] - 1

        row_segs: list[np.ndarray] = []
        for s_idx, e_idx in zip(starts.tolist(), ends.tolist()):
            if e_idx - s_idx < 1:
                continue
            p_start = np.array([xs[s_idx], ys[s_idx]], dtype=np.float64)
            p_end = np.array([xs[e_idx], ys[e_idx]], dtype=np.float64)
            if float(np.linalg.norm(p_end - p_start)) < 0.6:
                continue
            row_segs.append(np.vstack([p_start, p_end]))

        if row_idx % 2 == 1:
            row_segs = [seg[::-1] for seg in reversed(row_segs)]

        for seg in row_segs:
            # Slight hand-drawn endpoint variance
            if rng is not None and float(np.linalg.norm(seg[-1] - seg[0])) > 1.5:
                dvec = seg[-1] - seg[0]
                dvec = dvec / (np.linalg.norm(dvec) + 1e-9)
                seg = seg.copy()
                seg[0] += dvec * float(rng.uniform(0.0, 0.15 * spacing))
                seg[-1] -= dvec * float(rng.uniform(0.0, 0.15 * spacing))

            if zigzag and prev_end is not None and float(np.linalg.norm(prev_end - seg[0])) <= spacing * 2.2:
                strokes[-1] = np.vstack([strokes[-1], seg])
            else:
                strokes.append(seg)
            prev_end = strokes[-1][-1]

        if not row_segs:
            prev_end = None

    return strokes


def prune_major_outer_strokes(
    candidate_lines: list[np.ndarray],
    w_mm: float,
    h_mm: float,
    *,
    min_len_mm: float,
    max_strokes: int = 45,
    filter_inner_holes: bool = True,
) -> list[np.ndarray]:
    """Filter candidate strokes down to outer/major structural contours, suppressing dense lines."""
    if not candidate_lines:
        return []

    poly_candidates: list[tuple[Polygon, np.ndarray, float, float]] = []
    open_candidates: list[tuple[np.ndarray, float]] = []

    for coords in candidate_lines:
        if len(coords) < 2:
            continue
        ls = LineString(coords)
        arc = float(ls.length)
        if arc < min_len_mm:
            continue
        is_closed = len(coords) >= 4 and float(np.linalg.norm(coords[0] - coords[-1])) <= max(1.6, min_len_mm * 0.4)
        if filter_inner_holes and is_closed:
            try:
                ring = coords if float(np.linalg.norm(coords[0] - coords[-1])) < 1e-6 else np.vstack([coords, coords[0:1]])
                poly = Polygon(ring)
                if not poly.is_valid:
                    poly = poly.buffer(0)
                if isinstance(poly, Polygon) and poly.area > 0.5:
                    poly_candidates.append((poly, coords, arc, float(poly.area)))
                    continue
            except Exception:
                pass
        open_candidates.append((coords, arc))

    # Retain outer contours and only major interior structural cavities
    poly_candidates.sort(key=lambda item: item[3], reverse=True)
    kept_polys: list[tuple[Polygon, np.ndarray, float, float]] = []
    for poly, coords, arc, area in poly_candidates:
        rp = poly.representative_point()
        skip_inner = False
        for parent, _, _, p_area in kept_polys:
            if p_area > area * 1.15 and parent.contains(rp):
                if area < max(14.0, p_area * 0.08):
                    skip_inner = True
                break
        if not skip_inner:
            kept_polys.append((poly, coords, arc, area))

    all_ranked: list[tuple[np.ndarray, float]] = [(c, arc) for _, c, arc, _ in kept_polys] + open_candidates
    all_ranked.sort(key=lambda item: item[1], reverse=True)

    # Spatial occupancy deduplication: suppress dense parallel / crowded interior strokes
    cell = max(1.8, min(w_mm, h_mm) * 0.025)
    occupied: set[tuple[int, int]] = set()
    kept: list[np.ndarray] = []

    for coords, arc in all_ranked:
        if len(kept) >= max_strokes:
            break
        ls = LineString(coords)
        n_samp = max(3, min(80, int(arc / 1.0) + 1))
        pts = [ls.interpolate(i / max(1, n_samp - 1), normalized=True) for i in range(n_samp)]
        cells = [(int(math.floor(pt.x / cell)), int(math.floor(pt.y / cell))) for pt in pts]
        hits = sum(1 for c_key in cells if c_key in occupied)
        if hits >= int(math.ceil(0.72 * len(cells))):
            continue
        occupied.update(cells)
        kept.append(coords)

    return kept


def vectorize_raster_image(
    image_path: str | Path,
    bbox_mm: list[float],
    hatch_cfg: ChartConfig | None = None,
    rng: np.random.Generator | None = None,
    *,
    render_mode: str | None = None,
) -> list[np.ndarray]:
    """Convert a raster chart/figure PNG/JPEG into crisp hand-drawn single-line strokes in mm.

    Supports render modes:
    - `major_outline`: major/outer structural contours only, strictly banning dense interior lines
    - `outline` (default): crisp outer/inner contour extraction (zero fill hatching)
    - `hatch`: contours + single-pass primary angle shading
    - `crosshatch`: contours + dual-pass orthogonal crosshatch shading
    - `sketch`: contours + multi-tonal progressive sketch shading
    - `skip`: emit no strokes
    """
    cfg = hatch_cfg or ChartConfig()
    mode = (
        render_mode
        if (render_mode and render_mode != "inherit")
        else getattr(cfg, "image_render_mode", "outline")
    )
    if mode == "skip":
        return []

    gen = rng if rng is not None else np.random.default_rng(42)

    path = Path(image_path)
    if not path.is_file():
        return []

    x0, y0, x1, y1 = [float(v) for v in bbox_mm]
    bw = max(1.0, x1 - x0)
    bh = max(1.0, y1 - y0)

    try:
        st_stat = path.stat()
        mtime_ns = st_stat.st_mtime_ns
        file_size = st_stat.st_size
    except OSError:
        mtime_ns = 0
        file_size = 0

    thresh = float(getattr(cfg, "contour_threshold", 185))
    jitter = float(cfg.hand_jitter_mm)
    cache_key = (
        str(path.resolve()),
        mtime_ns,
        file_size,
        round(x0, 2),
        round(y0, 2),
        round(bw, 2),
        round(bh, 2),
        mode,
        round(thresh, 1),
        round(float(cfg.hatch_spacing_mm), 2),
        round(float(cfg.hatch_angle_deg), 1),
        cfg.hatch_style,
        round(jitter, 3),
    )
    with _RASTER_VEC_LOCK:
        cached = _RASTER_VEC_CACHE.get(cache_key)
        if cached is not None:
            _RASTER_VEC_CACHE.move_to_end(cache_key)
            return [a.copy() for a in cached]

    with Image.open(path) as im:
        gray = im.convert("L")
        max_dim = 150 if mode == "major_outline" else (240 if mode == "outline" else 170)
        scale = min(1.0, max_dim / max(1, max(gray.size)))
        new_w = max(16, int(round(gray.width * scale)))
        new_h = max(16, int(round(gray.height * scale)))
        if (new_w, new_h) != gray.size:
            gray = gray.resize((new_w, new_h), Image.Resampling.BILINEAR)
        if mode == "major_outline":
            gray = gray.filter(ImageFilter.MedianFilter(size=3))
        arr = np.asarray(gray, dtype=np.float32)

    h, w = arr.shape
    strokes: list[np.ndarray] = []

    # 1. Edge / contour extraction on foreground ink mask
    thresh = float(getattr(cfg, "contour_threshold", 185))
    fg_mask = (arr < thresh).astype(np.float32)
    if mode == "major_outline":
        # Morphological closing + opening fuses outer silhouettes & dissolves dense thin lines
        mask_im = Image.fromarray((fg_mask * 255).astype(np.uint8))
        closed = mask_im.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
        opened = closed.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
        fg_mask = (np.asarray(opened, dtype=np.float32) > 127.0).astype(np.float32)

    raw_contours = _marching_squares_contours(fg_mask, threshold=0.5)
    if mode == "major_outline":
        simp_tol = max(0.42, min(bw, bh) * 0.008)
        candidates: list[np.ndarray] = []
        for contour in raw_contours:
            pts_mm = [
                (x0 + (px / max(1, w - 1)) * bw, y0 + (py / max(1, h - 1)) * bh)
                for px, py in contour
            ]
            ls = LineString(pts_mm).simplify(simp_tol, preserve_topology=False)
            coords = np.asarray(ls.coords, dtype=np.float64)
            if len(coords) >= 2:
                candidates.append(coords)
        min_major = max(4.2, min(bw, bh) * 0.075)
        strokes = prune_major_outer_strokes(
            candidates,
            bw,
            bh,
            min_len_mm=min_major,
            max_strokes=45,
            filter_inner_holes=True,
        )
        if not strokes and raw_contours:
            fallback_cands: list[np.ndarray] = []
            for contour in raw_contours:
                pts_mm = [
                    (x0 + (px / max(1, w - 1)) * bw, y0 + (py / max(1, h - 1)) * bh)
                    for px, py in contour
                ]
                ls = LineString(pts_mm).simplify(0.25, preserve_topology=False)
                coords = np.asarray(ls.coords, dtype=np.float64)
                if len(coords) >= 2:
                    fallback_cands.append(coords)
            strokes = prune_major_outer_strokes(
                fallback_cands,
                bw,
                bh,
                min_len_mm=2.0,
                max_strokes=25,
                filter_inner_holes=False,
            )
    else:
        min_len = 0.8 if mode == "outline" else 1.1
        simp_tol = 0.18 if mode == "outline" else 0.24
        for contour in raw_contours:
            pts_mm = [
                (x0 + (px / max(1, w - 1)) * bw, y0 + (py / max(1, h - 1)) * bh)
                for px, py in contour
            ]
            ls = LineString(pts_mm).simplify(simp_tol, preserve_topology=False)
            if ls.length < min_len:
                continue
            coords = np.asarray(ls.coords, dtype=np.float64)
            if len(coords) >= 2:
                strokes.append(coords)

    # 2. Optional grayscale-level single-line hatching when shading mode is enabled
    zigzag = cfg.hatch_style == "zigzag"
    if mode == "hatch":
        mid_mask = arr < min(thresh - 10.0, 165.0)
        if np.any(mid_mask):
            strokes.extend(
                _scanline_hatch_mask(
                    mid_mask,
                    bbox_mm,
                    spacing_mm=cfg.hatch_spacing_mm,
                    angle_deg=cfg.hatch_angle_deg,
                    zigzag=zigzag,
                    rng=gen,
                )
            )
    elif mode == "crosshatch":
        mid_mask = arr < min(thresh - 10.0, 165.0)
        if np.any(mid_mask):
            strokes.extend(
                _scanline_hatch_mask(
                    mid_mask,
                    bbox_mm,
                    spacing_mm=cfg.hatch_spacing_mm,
                    angle_deg=cfg.hatch_angle_deg,
                    zigzag=zigzag,
                    rng=gen,
                )
            )
        dark_mask = arr < 105.0
        if np.any(dark_mask):
            strokes.extend(
                _scanline_hatch_mask(
                    dark_mask,
                    bbox_mm,
                    spacing_mm=max(cfg.hatch_spacing_mm * 1.1, 1.1),
                    angle_deg=cfg.hatch_angle_deg + 90.0,
                    zigzag=False,
                    rng=gen,
                )
            )
    elif mode == "sketch":
        light_mask = arr < 195.0
        mid_mask = arr < 140.0
        dark_mask = arr < 85.0
        if np.any(light_mask):
            strokes.extend(
                _scanline_hatch_mask(
                    light_mask,
                    bbox_mm,
                    spacing_mm=cfg.hatch_spacing_mm * 1.35,
                    angle_deg=cfg.hatch_angle_deg,
                    zigzag=zigzag,
                    rng=gen,
                )
            )
        if np.any(mid_mask):
            strokes.extend(
                _scanline_hatch_mask(
                    mid_mask,
                    bbox_mm,
                    spacing_mm=cfg.hatch_spacing_mm,
                    angle_deg=cfg.hatch_angle_deg + 90.0,
                    zigzag=False,
                    rng=gen,
                )
            )
        if np.any(dark_mask):
            strokes.extend(
                _scanline_hatch_mask(
                    dark_mask,
                    bbox_mm,
                    spacing_mm=max(0.8, cfg.hatch_spacing_mm * 0.72),
                    angle_deg=cfg.hatch_angle_deg + 45.0,
                    zigzag=False,
                    rng=gen,
                )
            )

    # Subtle smooth hand-drawn perturbation on vectorized strokes
    final_strokes = strokes
    if jitter > 0.0 and strokes:
        jittered: list[np.ndarray] = []
        for st in strokes:
            if len(st) < 2:
                continue
            noise = gen.normal(0.0, jitter * 0.25, size=st.shape)
            # Keep endpoints near original anchor
            noise[0] *= 0.35
            noise[-1] *= 0.35
            pts = st + noise
            pts[:, 0] = np.clip(pts[:, 0], x0, x1)
            pts[:, 1] = np.clip(pts[:, 1], y0, y1)
            jittered.append(pts)
        final_strokes = jittered

    with _RASTER_VEC_LOCK:
        _RASTER_VEC_CACHE[cache_key] = [a.copy() for a in final_strokes]
        _RASTER_VEC_CACHE.move_to_end(cache_key)
        while len(_RASTER_VEC_CACHE) > _MAX_RASTER_CACHE:
            _RASTER_VEC_CACHE.popitem(last=False)

    return final_strokes
