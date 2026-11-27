"""Single-line hand-drawn chart renderer with shapely polygon hatching and writer-font labels."""

from __future__ import annotations

import math

import numpy as np
from shapely import affinity
from shapely.geometry import LineString, MultiLineString, Polygon

from inkcraft.api.schemas import ChartConfig, LayoutConfig, MissingGlyphBox
from inkcraft.docparse.chart_extract import prune_major_outer_strokes, vectorize_raster_image
from inkcraft.docparse.docir import ChartData
from inkcraft.layout.perturb import hand_draw_polyline, scope_rng
from inkcraft.layout.shaper import EmittedStroke, emit_text_label
from inkcraft.writers.selector import VariantSelector


# ---------------------------------------------------------------------------
# Shapely Single-Line Polygon Hatching (§10.3)
# ---------------------------------------------------------------------------

def _extract_segments_from_geom(geom) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    segs: list[tuple[tuple[float, float], tuple[float, float]]] = []
    if geom is None or geom.is_empty:
        return segs
    if isinstance(geom, LineString):
        coords = list(geom.coords)
        if len(coords) >= 2:
            segs.append(((float(coords[0][0]), float(coords[0][1])), (float(coords[-1][0]), float(coords[-1][1]))))
    elif isinstance(geom, MultiLineString):
        for ls in geom.geoms:
            segs.extend(_extract_segments_from_geom(ls))
    elif hasattr(geom, "geoms"):
        for sub in geom.geoms:
            segs.extend(_extract_segments_from_geom(sub))
    return segs


def _hatch_single_pass(
    poly: Polygon,
    *,
    spacing_mm: float,
    angle_deg: float,
    zigzag: bool,
    jitter_mm: float,
    rng: np.random.Generator,
) -> list[np.ndarray]:
    if poly.is_empty or poly.area < 0.2:
        return []

    inset = poly.buffer(-0.22)
    work_poly = inset if (not inset.is_empty and inset.area > 0.08) else poly
    origin = work_poly.centroid
    rot_poly = affinity.rotate(work_poly, -angle_deg, origin=origin)
    minx, miny, maxx, maxy = rot_poly.bounds
    if (maxy - miny) < 0.2 or (maxx - minx) < 0.2:
        return []

    s = max(0.8, float(spacing_mm))
    raw_lines_rot: list[np.ndarray] = []
    rot_poly_buf = rot_poly.buffer(0.15)

    y = miny + 0.5 * s
    row_idx = 0
    prev_end: np.ndarray | None = None

    while y < maxy:
        scan = LineString([(minx - 2.0, y), (maxx + 2.0, y)])
        inter = rot_poly.intersection(scan)
        segs = _extract_segments_from_geom(inter)
        segs.sort(key=lambda pair: min(pair[0][0], pair[1][0]))

        row_segs: list[np.ndarray] = []
        for p0, p1 in segs:
            a = np.array(p0, dtype=np.float64)
            b = np.array(p1, dtype=np.float64)
            length = float(np.linalg.norm(b - a))
            if length < 0.35:
                continue
            # Slight hand-drawn endpoint pullback (0..0.22 * s)
            if length > 1.2:
                d = (b - a) / length
                a = a + d * float(rng.uniform(0.0, min(0.22 * s, 0.2 * length)))
                b = b - d * float(rng.uniform(0.0, min(0.22 * s, 0.2 * length)))
            row_segs.append(np.vstack([a, b]))

        # Boustrophedon alternating sweep direction
        if row_idx % 2 == 1:
            row_segs = [seg[::-1] for seg in reversed(row_segs)]

        for seg in row_segs:
            connected = False
            if prev_end is not None:
                dist = float(np.linalg.norm(prev_end - seg[0]))
                threshold = s * 2.4 if zigzag else s * 1.45
                if dist <= threshold:
                    conn = LineString([tuple(prev_end), tuple(seg[0])])
                    if rot_poly_buf.contains(conn):
                        raw_lines_rot[-1] = np.vstack([raw_lines_rot[-1], seg])
                        connected = True
            if not connected:
                raw_lines_rot.append(seg)
            prev_end = raw_lines_rot[-1][-1]

        if not row_segs:
            prev_end = None
        y += s
        row_idx += 1

    # Rotate back by +angle_deg around origin and hand-draw lightly
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    ox, oy = float(origin.x), float(origin.y)

    out: list[np.ndarray] = []
    for arr in raw_lines_rot:
        dx = arr[:, 0] - ox
        dy = arr[:, 1] - oy
        rx = ox + dx * cos_a - dy * sin_a
        ry = oy + dx * sin_a + dy * cos_a
        world = np.column_stack((rx, ry))
        if jitter_mm > 1e-6:
            world = hand_draw_polyline(
                world,
                jitter_mm * 0.45,
                rng,
                overshoot_mm=0.0,
                resample_step_mm=2.2,
                simplify_tol_mm=0.06,
            )
        out.append(world)
    return out


def hatch_polygon(
    poly: Polygon,
    *,
    spacing_mm: float,
    angle_deg: float,
    style: str,
    jitter_mm: float,
    rng: np.random.Generator,
) -> list[np.ndarray]:
    """Generate single-line hatch strokes inside a `shapely.Polygon`."""
    zigzag = style == "zigzag"
    strokes = _hatch_single_pass(
        poly,
        spacing_mm=spacing_mm,
        angle_deg=angle_deg,
        zigzag=zigzag,
        jitter_mm=jitter_mm,
        rng=rng,
    )
    if style == "cross":
        strokes.extend(
            _hatch_single_pass(
                poly,
                spacing_mm=spacing_mm * 1.1,
                angle_deg=angle_deg + 90.0,
                zigzag=False,
                jitter_mm=jitter_mm,
                rng=rng,
            )
        )
    return strokes


# ---------------------------------------------------------------------------
# Markers & Formatting Helpers
# ---------------------------------------------------------------------------

def _make_marker_strokes(cx: float, cy: float, radius: float, series_idx: int) -> list[np.ndarray]:
    kind = series_idx % 4
    if kind == 0:  # circle ○
        th = np.linspace(0.0, 2.0 * math.pi, 13)
        return [np.column_stack((cx + radius * np.cos(th), cy + radius * np.sin(th)))]
    if kind == 1:  # triangle △
        pts = np.array(
            [
                [cx, cy - radius * 1.15],
                [cx + radius, cy + radius * 0.85],
                [cx - radius, cy + radius * 0.85],
                [cx, cy - radius * 1.15],
            ],
            dtype=np.float64,
        )
        return [pts]
    if kind == 2:  # square □
        r = radius * 0.88
        pts = np.array(
            [[cx - r, cy - r], [cx + r, cy - r], [cx + r, cy + r], [cx - r, cy + r], [cx - r, cy - r]],
            dtype=np.float64,
        )
        return [pts]
    # cross ×
    r = radius * 0.9
    return [
        np.array([[cx - r, cy - r], [cx + r, cy + r]], dtype=np.float64),
        np.array([[cx + r, cy - r], [cx - r, cy + r]], dtype=np.float64),
    ]


def _fmt_tick(v: float) -> str:
    if abs(v - round(v)) < 1e-3:
        return str(int(round(v)))
    return f"{v:.1f}"


def _nice_range(vals: list[float], include_zero: bool = True) -> tuple[float, float]:
    if not vals:
        return 0.0, 100.0
    vmin = min(vals)
    vmax = max(vals)
    if include_zero:
        vmin = min(0.0, vmin)
        vmax = max(0.0, vmax)
    if abs(vmax - vmin) < 1e-6:
        vmax = vmin + 1.0
    span = vmax - vmin
    exp = math.floor(math.log10(span))
    step = 10.0**exp
    if span / step < 2.0:
        step *= 0.25
    elif span / step < 5.0:
        step *= 0.5
    lo = math.floor(vmin / step) * step
    hi = math.ceil(vmax / step) * step
    return lo, hi


# ---------------------------------------------------------------------------
# Chart Type Renderers
# ---------------------------------------------------------------------------

def render_chart(
    chart: ChartData,
    *,
    bbox_mm: list[float],
    selector: VariantSelector,
    config: LayoutConfig,
    block_id: str,
    page_index: int = 0,
    units_per_em: float = 1000.0,
    baseline_u: float = 800.0,
    render_mode: str | None = None,
    missing_out: list[MissingGlyphBox] | None = None,
) -> list[EmittedStroke]:
    """Render a `ChartData` block inside `bbox_mm = [x0, y0, x1, y1]` into single-line strokes."""
    x0, y0, x1, y1 = [float(v) for v in bbox_mm]
    w = max(8.0, x1 - x0)
    h = max(6.0, y1 - y0)
    ccfg: ChartConfig = config.chart
    eff_mode = (
        render_mode
        if (render_mode and render_mode != "inherit")
        else getattr(ccfg, "image_render_mode", "outline")
    )
    if eff_mode == "skip":
        return []

    should_hatch = eff_mode in {"hatch", "crosshatch", "sketch"}
    hatch_style_override = "cross" if eff_mode == "crosshatch" else ccfg.hatch_style
    hatch_spacing_eff = (
        max(0.8, ccfg.hatch_spacing_mm * 0.78) if eff_mode == "sketch" else ccfg.hatch_spacing_mm
    )

    rng = scope_rng(config.perturb.seed, "chart", block_id, page_index)
    jitter = float(ccfg.hand_jitter_mm)

    strokes: list[EmittedStroke] = []

    def _add_rev(raw_pts: np.ndarray, *, closed: bool = False, overshoot: float = 0.22) -> None:
        pts = hand_draw_polyline(
            raw_pts,
            jitter,
            rng,
            overshoot_mm=0.0 if closed else overshoot,
            resample_step_mm=1.8,
            simplify_tol_mm=0.06,
            closed=closed,
        )
        strokes.append(EmittedStroke(pts=pts, kind="chart", block_id=block_id, reversible=True))

    def _add_label(
        txt: str,
        lx: float,
        ly: float,
        fsize: float,
        align: str = "center",
        max_w: float | None = None,
    ) -> None:
        if not txt:
            return
        strokes.extend(
            emit_text_label(
                txt,
                selector,
                x_mm=lx,
                baseline_y_mm=ly,
                font_size_mm=fsize,
                align=align,
                max_width_mm=max_w,
                perturb_cfg=config.perturb,
                rng=rng,
                block_id=block_id,
                kind="chart",
                units_per_em=units_per_em,
                baseline_u=baseline_u,
                missing_out=missing_out,
                page_index=page_index,
            )
        )

    # 1. Raster fallback vectorization
    if chart.chart_type == "raster" and chart.image_path:
        vec_strokes = vectorize_raster_image(
            chart.image_path,
            [x0, y0, x1, y1],
            ccfg,
            rng,
            render_mode=eff_mode,
        )
        for st in vec_strokes:
            strokes.append(EmittedStroke(pts=st, kind="chart", block_id=block_id, reversible=True))
        if chart.title:
            _add_label(chart.title, 0.5 * (x0 + x1), y0 + 4.5, max(3.5, config.text.font_size_mm * 0.75))
        return strokes

    # 2. Vector drawing primitives (from PDF get_drawings)
    if chart.chart_type == "vector" and (chart.vector_polylines or chart.vector_polygons):
        is_norm = chart.extra.get("coord_space") == "normalized"

        def _map_pts(pts_list: list[tuple[float, float]]) -> np.ndarray:
            arr = np.asarray(pts_list, dtype=np.float64)
            if is_norm:
                arr = np.column_stack((x0 + arr[:, 0] * w, y0 + arr[:, 1] * h))
            return arr

        if eff_mode == "major_outline":
            min_vec_len = max(3.5, min(w, h) * 0.055)
            vec_cands: list[np.ndarray] = []
            for poly_pts in chart.vector_polygons:
                if len(poly_pts) < 3:
                    continue
                arr = _map_pts(poly_pts)
                if float(np.linalg.norm(arr[0] - arr[-1])) > 1e-6:
                    arr = np.vstack([arr, arr[0:1]])
                vec_cands.append(arr)
            for line_pts in chart.vector_polylines:
                if len(line_pts) >= 2:
                    vec_cands.append(_map_pts(line_pts))
            for arr in prune_major_outer_strokes(vec_cands, w, h, min_len_mm=min_vec_len, max_strokes=45):
                is_cl = len(arr) >= 4 and float(np.linalg.norm(arr[0] - arr[-1])) < 1e-6
                _add_rev(arr, closed=is_cl, overshoot=0.0 if is_cl else 0.12)
        else:
            for p_idx, poly_pts in enumerate(chart.vector_polygons):
                if len(poly_pts) < 3:
                    continue
                arr = _map_pts(poly_pts)
                if float(np.linalg.norm(arr[0] - arr[-1])) > 1e-6:
                    arr = np.vstack([arr, arr[0:1]])
                _add_rev(arr, closed=True)
                if should_hatch:
                    try:
                        poly = Polygon(arr)
                        if not poly.is_valid:
                            poly = poly.buffer(0)
                        if isinstance(poly, Polygon) and poly.area >= 4.0:
                            hatches = hatch_polygon(
                                poly,
                                spacing_mm=hatch_spacing_eff,
                                angle_deg=ccfg.hatch_angle_deg + (p_idx % 4) * 45.0,
                                style=hatch_style_override,
                                jitter_mm=jitter,
                                rng=rng,
                            )
                            for hst in hatches:
                                strokes.append(EmittedStroke(pts=hst, kind="chart", block_id=block_id, reversible=True))
                    except Exception:
                        pass

            for line_pts in chart.vector_polylines:
                if len(line_pts) < 2:
                    continue
                _add_rev(_map_pts(line_pts), closed=False, overshoot=0.12)

        if chart.title:
            _add_label(chart.title, 0.5 * (x0 + x1), y0 + 4.5, max(3.5, config.text.font_size_mm * 0.75))
        return strokes

    # Common layout margins for semantic charts (bar / line / pie / scatter)
    label_font = max(3.0, min(4.8, config.text.font_size_mm * 0.65))
    title_font = max(3.6, min(5.8, config.text.font_size_mm * 0.82))
    top_pad = (title_font + 4.0) if chart.title else 4.0
    if chart.title:
        _add_label(chart.title, 0.5 * (x0 + x1), y0 + title_font + 0.8, title_font, align="center", max_w=w * 0.92)

    # 3. Pie chart
    if chart.chart_type == "pie":
        vals = chart.series[0].values if chart.series else []
        positive = [max(0.0, float(v)) for v in vals]
        total = sum(positive)
        if total <= 1e-6:
            return strokes

        cx = x0 + 0.48 * w
        cy = y0 + top_pad + 0.5 * (h - top_pad - 4.0)
        radius = max(8.0, min(w * 0.34, (h - top_pad - 8.0) * 0.46))

        angle = -math.pi * 0.5
        for idx, val in enumerate(positive):
            frac = val / total
            sweep = frac * 2.0 * math.pi
            a0, a1 = angle, angle + sweep
            steps = max(8, int(math.ceil(sweep / 0.18)))
            arc_th = np.linspace(a0, a1, steps + 1)
            arc_pts = np.column_stack((cx + radius * np.cos(arc_th), cy + radius * np.sin(arc_th)))
            wedge_pts = np.vstack([np.array([[cx, cy]]), arc_pts, np.array([[cx, cy]])])
            _add_rev(wedge_pts, closed=True)

            poly = Polygon(wedge_pts)
            if should_hatch:
                style_i = "cross" if (idx >= 4 or hatch_style_override == "cross") else hatch_style_override
                hatches = hatch_polygon(
                    poly,
                    spacing_mm=hatch_spacing_eff,
                    angle_deg=ccfg.hatch_angle_deg + (idx % 4) * 45.0,
                    style=style_i,
                    jitter_mm=jitter,
                    rng=rng,
                )
                for hst in hatches:
                    strokes.append(EmittedStroke(pts=hst, kind="chart", block_id=block_id, reversible=True))

            # Radial leader + label
            mid_a = 0.5 * (a0 + a1)
            p_in = np.array([cx + radius * 1.03 * math.cos(mid_a), cy + radius * 1.03 * math.sin(mid_a)])
            p_out = np.array([cx + (radius + 4.5) * math.cos(mid_a), cy + (radius + 4.5) * math.sin(mid_a)])
            _add_rev(np.vstack([p_in, p_out]), overshoot=0.05)
            cat_txt = chart.categories[idx] if idx < len(chart.categories) else f"P{idx + 1}"
            lbl = f"{cat_txt} {int(round(frac * 100))}%"
            l_align = "left" if math.cos(mid_a) >= 0 else "right"
            _add_label(lbl, p_out[0] + (1.2 if l_align == "left" else -1.2), p_out[1] + label_font * 0.3, label_font, align=l_align)
            angle = a1
        return strokes

    # 4. Cartesian charts: bar / line / scatter
    left_pad = min(15.0, w * 0.28)
    right_pad = min(8.0, w * 0.14)
    bot_pad = min(12.0 if not chart.x_label else 16.0, h * 0.30)
    legend_h = 6.5 if len(chart.series) > 1 and h > 36.0 else 0.0

    px0 = x0 + left_pad
    px1 = max(px0 + 12.0, x1 - right_pad)
    py0 = y0 + top_pad + legend_h
    py1 = max(py0 + 10.0, y1 - bot_pad)
    pw = px1 - px0
    ph = py1 - py0

    all_y = [float(v) for s in chart.series for v in s.values]
    y_min, y_max = _nice_range(all_y, include_zero=(chart.chart_type == "bar"))
    y_span = max(1e-6, y_max - y_min)

    def _map_y(v: float) -> float:
        return py1 - ((v - y_min) / y_span) * ph

    # Axes with hand-drawn overshoot and small arrowheads
    _add_rev(np.array([[px0, py1], [px0, py0 - 2.0]], dtype=np.float64), overshoot=0.25)
    _add_rev(np.array([[px0, py1], [px1 + 2.0, py1]], dtype=np.float64), overshoot=0.25)
    # Arrow tips
    _add_rev(np.array([[px0 - 1.1, py0 + 0.2], [px0, py0 - 2.2], [px0 + 1.1, py0 + 0.2]], dtype=np.float64), overshoot=0.0)
    _add_rev(np.array([[px1 - 0.2, py1 - 1.1], [px1 + 2.2, py1], [px1 - 0.2, py1 + 1.1]], dtype=np.float64), overshoot=0.0)

    # Y-axis ticks & numeric labels (4 intervals)
    n_ticks = 4
    for ti in range(n_ticks + 1):
        val = y_min + (y_span * ti / n_ticks)
        ty = _map_y(val)
        _add_rev(np.array([[px0 - 1.4, ty], [px0, ty]], dtype=np.float64), overshoot=0.05)
        _add_label(_fmt_tick(val), px0 - 2.2, ty + label_font * 0.32, label_font, align="right", max_w=left_pad - 3.0)

    # Axis title labels
    if chart.y_label:
        _add_label(chart.y_label, px0, py0 - 3.5, label_font * 0.92, align="center", max_w=24.0)
    if chart.x_label:
        _add_label(chart.x_label, 0.5 * (px0 + px1), y1 - 1.2, label_font * 0.92, align="center", max_w=pw * 0.6)

    # Legend for multi-series charts
    if len(chart.series) > 1:
        leg_y = y0 + top_pad + 2.8
        leg_step = min(34.0, pw / max(1, len(chart.series)))
        leg_x = px0 + 4.0
        for si, ser in enumerate(chart.series):
            if chart.chart_type == "bar":
                sw = Polygon([(leg_x, leg_y - 3.0), (leg_x + 4.8, leg_y - 3.0), (leg_x + 4.8, leg_y + 0.8), (leg_x, leg_y + 0.8)])
                _add_rev(np.asarray(sw.exterior.coords, dtype=np.float64), closed=True)
                if should_hatch:
                    s_style = "cross" if (si >= 4 or hatch_style_override == "cross") else hatch_style_override
                    for hst in hatch_polygon(
                        sw,
                        spacing_mm=max(1.1, hatch_spacing_eff * 0.8),
                        angle_deg=ccfg.hatch_angle_deg + (si % 4) * 45.0,
                        style=s_style,
                        jitter_mm=jitter * 0.5,
                        rng=rng,
                    ):
                        strokes.append(EmittedStroke(pts=hst, kind="chart", block_id=block_id, reversible=True))
            else:
                _add_rev(np.array([[leg_x, leg_y - 1.0], [leg_x + 5.0, leg_y - 1.0]], dtype=np.float64), overshoot=0.05)
                for mst in _make_marker_strokes(leg_x + 2.5, leg_y - 1.0, 1.2, si):
                    strokes.append(EmittedStroke(pts=mst, kind="chart", block_id=block_id, reversible=True))
            _add_label(ser.name or f"S{si + 1}", leg_x + 6.2, leg_y + 0.4, label_font * 0.92, align="left", max_w=leg_step - 7.5)
            leg_x += leg_step

    if chart.chart_type == "bar":
        n_cats = max(len(chart.categories), max((len(s.values) for s in chart.series), default=0))
        if n_cats == 0:
            return strokes
        n_ser = max(1, len(chart.series))
        group_w = pw / n_cats
        usable_w = group_w * 0.72
        bar_w = usable_w / n_ser
        zero_y = _map_y(max(y_min, 0.0))

        for ci in range(n_cats):
            gx0 = px0 + ci * group_w + (group_w - usable_w) * 0.5
            cat_lbl = chart.categories[ci] if ci < len(chart.categories) else str(ci + 1)
            _add_label(cat_lbl, px0 + (ci + 0.5) * group_w, py1 + label_font + 1.8, label_font, align="center", max_w=group_w * 0.92)

            for si, ser in enumerate(chart.series):
                if ci >= len(ser.values):
                    continue
                val = float(ser.values[ci])
                bx0 = gx0 + si * bar_w + 0.4
                bx1 = gx0 + (si + 1) * bar_w - 0.4
                by_top = _map_y(val)
                y_lo, y_hi = min(by_top, zero_y), max(by_top, zero_y)
                if (bx1 - bx0) < 0.8 or (y_hi - y_lo) < 0.4:
                    continue

                rect_pts = np.array(
                    [[bx0, y_hi], [bx0, y_lo], [bx1, y_lo], [bx1, y_hi], [bx0, y_hi]],
                    dtype=np.float64,
                )
                _add_rev(rect_pts, closed=True)

                if should_hatch:
                    poly = Polygon(rect_pts)
                    s_style = "cross" if (si >= 4 or hatch_style_override == "cross") else hatch_style_override
                    s_angle = ccfg.hatch_angle_deg + (si % 4) * 45.0
                    hatches = hatch_polygon(
                        poly,
                        spacing_mm=hatch_spacing_eff,
                        angle_deg=s_angle,
                        style=s_style,
                        jitter_mm=jitter,
                        rng=rng,
                    )
                    for hst in hatches:
                        strokes.append(EmittedStroke(pts=hst, kind="chart", block_id=block_id, reversible=True))

    elif chart.chart_type == "line":
        n_cats = max(len(chart.categories), max((len(s.values) for s in chart.series), default=0))
        if n_cats == 0:
            return strokes
        for ci in range(n_cats):
            tx = px0 + (pw * ci / max(1, n_cats - 1)) if n_cats > 1 else (px0 + 0.5 * pw)
            _add_rev(np.array([[tx, py1], [tx, py1 + 1.3]], dtype=np.float64), overshoot=0.04)
            cat_lbl = chart.categories[ci] if ci < len(chart.categories) else str(ci + 1)
            _add_label(cat_lbl, tx, py1 + label_font + 2.0, label_font, align="center", max_w=pw / max(1, n_cats))

        for si, ser in enumerate(chart.series):
            if not ser.values:
                continue
            pts_list: list[tuple[float, float]] = []
            for ci, val in enumerate(ser.values):
                tx = px0 + (pw * ci / max(1, n_cats - 1)) if n_cats > 1 else (px0 + 0.5 * pw)
                ty = _map_y(float(val))
                pts_list.append((tx, ty))
            arr = np.asarray(pts_list, dtype=np.float64)
            if len(arr) >= 2:
                _add_rev(arr, closed=False, overshoot=0.10)
            for tx, ty in pts_list:
                for mst in _make_marker_strokes(tx, ty, 1.35, si):
                    strokes.append(EmittedStroke(pts=mst, kind="chart", block_id=block_id, reversible=True))

    elif chart.chart_type == "scatter":
        all_x: list[float] = []
        for ser in chart.series:
            xs = ser.x_values if (ser.x_values and len(ser.x_values) == len(ser.values)) else list(range(len(ser.values)))
            all_x.extend(float(v) for v in xs)
        x_min, x_max = _nice_range(all_x, include_zero=False)
        x_span = max(1e-6, x_max - x_min)

        for ti in range(5):
            xv = x_min + x_span * ti / 4.0
            tx = px0 + ((xv - x_min) / x_span) * pw
            _add_rev(np.array([[tx, py1], [tx, py1 + 1.3]], dtype=np.float64), overshoot=0.04)
            _add_label(_fmt_tick(xv), tx, py1 + label_font + 2.0, label_font, align="center")

        for si, ser in enumerate(chart.series):
            xs = ser.x_values if (ser.x_values and len(ser.x_values) == len(ser.values)) else list(range(len(ser.values)))
            for xv, yv in zip(xs, ser.values):
                tx = px0 + ((float(xv) - x_min) / x_span) * pw
                ty = _map_y(float(yv))
                for mst in _make_marker_strokes(tx, ty, 1.45, si):
                    strokes.append(EmittedStroke(pts=mst, kind="chart", block_id=block_id, reversible=True))

    return strokes
