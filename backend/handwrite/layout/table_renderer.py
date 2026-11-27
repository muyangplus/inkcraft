"""Single-line hand-drawn table renderer supporting merged spans (rs/cs) and inline math cells."""

from __future__ import annotations

import math
import numpy as np

from handwrite.api.schemas import LayoutConfig, MissingGlyphBox, TableBorderStyle
from handwrite.docparse.docir import TableCell, TableData
from handwrite.layout.perturb import hand_draw_polyline, scope_rng
from handwrite.layout.shaper import (
    EmittedStroke,
    ShapedLine,
    break_atoms_into_lines,
    emit_shaped_line,
    shape_inlines,
)
from handwrite.writers.selector import VariantSelector


def _compute_column_widths(table: TableData, total_width_mm: float) -> list[float]:
    ncols = max(1, table.cols)
    if table.col_widths_mm and len(table.col_widths_mm) >= ncols:
        raw = [max(4.0, float(w)) for w in table.col_widths_mm[:ncols]]
        s = sum(raw)
        if s > 1e-3:
            scale = total_width_mm / s
            return [w * scale for w in raw]
    return [total_width_mm / ncols] * ncols


def resolve_effective_table_style(table: TableData, config: LayoutConfig) -> TableBorderStyle:
    """Resolve effective border style from per-table override or global TableConfig."""
    if table.border_style is not None:
        return table.border_style
    if not config.table.draw_borders:
        return "none"
    return config.table.border_style


def _emit_rule_strokes(
    p0: tuple[float, float],
    p1: tuple[float, float],
    *,
    style: TableBorderStyle,
    jitter: float,
    overshoot: float,
    rng,
    block_id: str,
    double: bool = False,
) -> list[EmittedStroke]:
    """Emit hand-drawn border strokes between `(p0, p1)` matching `style`."""
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    length = math.hypot(dx, dy)
    if length < 0.4:
        return []

    out: list[EmittedStroke] = []
    if style == "dashed":
        ux, uy = dx / length, dy / length
        dash_len = 2.4
        gap_len = 1.5
        s = 0.0
        while s < length - 0.35:
            e = min(length, s + dash_len)
            seg = np.array(
                [[p0[0] + ux * s, p0[1] + uy * s], [p0[0] + ux * e, p0[1] + uy * e]],
                dtype=np.float64,
            )
            pts = hand_draw_polyline(seg, min(jitter, 0.14), rng, overshoot_mm=0.0, resample_step_mm=1.2)
            out.append(EmittedStroke(pts=pts, kind="table", block_id=block_id, reversible=True))
            s += dash_len + gap_len
        return out

    if double:
        nx, ny = -dy / length, dx / length
        for sign in (-0.19, 0.19):
            raw = np.array(
                [[p0[0] + nx * sign, p0[1] + ny * sign], [p1[0] + nx * sign, p1[1] + ny * sign]],
                dtype=np.float64,
            )
            pts = hand_draw_polyline(raw, min(jitter, 0.14), rng, overshoot_mm=overshoot * 0.6, resample_step_mm=2.0)
            out.append(EmittedStroke(pts=pts, kind="table", block_id=block_id, reversible=True))
        return out

    raw = np.array([[p0[0], p0[1]], [p1[0], p1[1]]], dtype=np.float64)
    pts = hand_draw_polyline(raw, jitter, rng, overshoot_mm=overshoot, resample_step_mm=2.0)
    out.append(EmittedStroke(pts=pts, kind="table", block_id=block_id, reversible=True))
    return out


def _compute_table_metrics(
    table: TableData,
    *,
    width_mm: float,
    max_height_mm: float | None,
    selector: VariantSelector,
    config: LayoutConfig,
    block_id: str,
    units_per_em: float = 1000.0,
    baseline_u: float = 800.0,
    font_size_mm: float | None = None,
    char_scale_x: float | None = None,
    char_scale_y: float | None = None,
) -> tuple[
    TableBorderStyle,
    float,
    float,
    float,
    float,
    float,
    float,
    list[float],
    list[float],
    list[list[int]],
    list[tuple[TableCell, list[ShapedLine], float]],
    float,
]:
    """Compute column widths, row heights, shaped cells, and total table height."""
    rows = max(1, table.rows)
    cols = max(1, table.cols)
    eff_style = resolve_effective_table_style(table, config)
    col_ws = _compute_column_widths(table, width_mm)

    if eff_style == "compact":
        pad_x = min(float(config.table.cell_padding_mm), 0.65)
        pad_y = min(float(config.table.cell_padding_mm) * 0.78, 0.55)
        row_scale = min(float(config.table.row_height_scale), 0.76)
        eff_font_scale = min(float(config.table.font_scale), 0.76)
        eff_jitter = min(float(config.table.hand_jitter_mm), 0.12)
    else:
        pad_x = float(config.table.cell_padding_mm)
        pad_y = max(0.3, float(config.table.cell_padding_mm) * 0.85)
        row_scale = float(config.table.row_height_scale)
        eff_font_scale = float(config.table.font_scale)
        eff_jitter = float(config.table.hand_jitter_mm)

    eff_char_sx = float(char_scale_x if char_scale_x is not None else config.text.char_scale_x)
    eff_char_sy = float(char_scale_y if char_scale_y is not None else config.text.char_scale_y)
    eff_font = float(font_size_mm if font_size_mm is not None else config.text.font_size_mm)
    base_font = max(2.6, eff_font * eff_font_scale)
    line_pitch = base_font * max(1.18, config.text.line_spacing * 0.82) * eff_char_sy * row_scale
    min_row_h = max(4.6, base_font * 1.38 * row_scale)

    shaped_cells: list[tuple[TableCell, list[ShapedLine], float]] = []
    row_heights = [
        float(table.row_heights_mm[r]) * row_scale
        if r < len(table.row_heights_mm)
        else max(line_pitch + 2.0 * pad_y, min_row_h)
        for r in range(rows)
    ]

    owner_grid: list[list[int]] = [[-1 for _ in range(cols)] for _ in range(rows)]

    for cell_idx, cell in enumerate(table.cells):
        r0 = max(0, min(rows - 1, cell.r))
        c0 = max(0, min(cols - 1, cell.c))
        rs = max(1, min(rows - r0, cell.rs))
        cs = max(1, min(cols - c0, cell.cs))
        for rr in range(r0, r0 + rs):
            for cc in range(c0, c0 + cs):
                owner_grid[rr][cc] = cell_idx

        cell_w = sum(col_ws[c0 : c0 + cs])
        inner_w = max(4.0, cell_w - 2.0 * pad_x)

        cell_rng = scope_rng(config.perturb.seed, "table_cell_shape", block_id, r0, c0)
        cell_font = base_font
        atoms = shape_inlines(
            cell.inlines,
            selector,
            font_size_mm=cell_font,
            char_spacing=config.text.char_spacing,
            formula_scale=config.formula.scale,
            max_width_mm=inner_w,
            perturb_cfg=config.perturb,
            rng=cell_rng,
            units_per_em=units_per_em,
            baseline_u=baseline_u,
            char_scale_x=eff_char_sx,
        )
        lines = break_atoms_into_lines(atoms, line_width_mm=inner_w, font_size_mm=cell_font)
        if len(lines) > 2 and cell_font > base_font * 0.72:
            cell_font = max(2.4, base_font * 0.75)
            cell_rng = scope_rng(config.perturb.seed, "table_cell_shape", block_id, r0, c0)
            atoms = shape_inlines(
                cell.inlines,
                selector,
                font_size_mm=cell_font,
                char_spacing=config.text.char_spacing,
                formula_scale=config.formula.scale,
                max_width_mm=inner_w,
                perturb_cfg=config.perturb,
                rng=cell_rng,
                units_per_em=units_per_em,
                baseline_u=baseline_u,
                char_scale_x=eff_char_sx,
            )
            lines = break_atoms_into_lines(atoms, line_width_mm=inner_w, font_size_mm=cell_font)

        shaped_cells.append((cell, lines, cell_font))

        if lines:
            req_h = (
                sum(max(cell_font * 1.15 * row_scale, ln.ascent_mm + ln.descent_mm + 0.65 * row_scale) for ln in lines)
                + 2.0 * pad_y
            )
            cur_span_h = sum(row_heights[r0 : r0 + rs])
            if req_h > cur_span_h:
                extra = (req_h - cur_span_h) / rs
                for rr in range(r0, r0 + rs):
                    row_heights[rr] += extra

    total_h = sum(row_heights)
    if max_height_mm is not None and total_h > max_height_mm and total_h > 1e-3:
        h_scale = max(0.65, max_height_mm / total_h)
        row_heights = [h * h_scale for h in row_heights]
        total_h = sum(row_heights)

    return (
        eff_style,
        pad_x,
        pad_y,
        row_scale,
        eff_jitter,
        eff_char_sx,
        eff_char_sy,
        col_ws,
        row_heights,
        owner_grid,
        shaped_cells,
        total_h,
    )


def measure_table_height(
    table: TableData,
    *,
    width_mm: float,
    max_height_mm: float | None,
    selector: VariantSelector,
    config: LayoutConfig,
    block_id: str,
    units_per_em: float = 1000.0,
    baseline_u: float = 800.0,
    font_size_mm: float | None = None,
    char_scale_x: float | None = None,
    char_scale_y: float | None = None,
) -> float:
    """Measure exact rendered height of a table without mutating `selector` state."""
    dry_selector = VariantSelector(
        selector.reader,
        strategy=selector.strategy,
        no_repeat_window=selector.no_repeat_window,
        fallback_policy=selector.fallback_policy,
    )
    _, _, _, _, _, _, _, _, _, _, _, total_h = _compute_table_metrics(
        table,
        width_mm=width_mm,
        max_height_mm=max_height_mm,
        selector=dry_selector,
        config=config,
        block_id=block_id,
        units_per_em=units_per_em,
        baseline_u=baseline_u,
        font_size_mm=font_size_mm,
        char_scale_x=char_scale_x,
        char_scale_y=char_scale_y,
    )
    return total_h


def render_table(
    table: TableData,
    *,
    x0_mm: float,
    y0_mm: float,
    width_mm: float,
    max_height_mm: float | None,
    selector: VariantSelector,
    config: LayoutConfig,
    block_id: str,
    page_index: int,
    units_per_em: float = 1000.0,
    baseline_u: float = 800.0,
    font_size_mm: float | None = None,
    char_scale_x: float | None = None,
    char_scale_y: float | None = None,
    missing_out: list[MissingGlyphBox] | None = None,
) -> tuple[list[EmittedStroke], float]:
    """Render a `TableData` block with multi-style hand-drawn borders and wrapped cell contents.

    Returns `(strokes, rendered_height_mm)`.
    """
    rows = max(1, table.rows)
    cols = max(1, table.cols)
    (
        eff_style,
        pad_x,
        pad_y,
        row_scale,
        eff_jitter,
        eff_char_sx,
        eff_char_sy,
        col_ws,
        row_heights,
        owner_grid,
        shaped_cells,
        total_h,
    ) = _compute_table_metrics(
        table,
        width_mm=width_mm,
        max_height_mm=max_height_mm,
        selector=selector,
        config=config,
        block_id=block_id,
        units_per_em=units_per_em,
        baseline_u=baseline_u,
        font_size_mm=font_size_mm,
        char_scale_x=char_scale_x,
        char_scale_y=char_scale_y,
    )
    col_xs = [x0_mm]
    for w in col_ws:
        col_xs.append(col_xs[-1] + w)

    row_ys = [y0_mm]
    for h in row_heights:
        row_ys.append(row_ys[-1] + h)

    strokes: list[EmittedStroke] = []

    # 1. Hand-drawn table borders respecting eff_style & rs/cs merged spans
    if eff_style != "none":
        border_rng = scope_rng(config.perturb.seed, "table_borders", block_id, page_index)
        overshoot = 0.24 if (eff_jitter > 0.0 and eff_style in {"grid", "compact", "minimal"}) else 0.0

        def _emit_h_boundaries(r: int, *, double: bool = False, span_aware: bool = True) -> None:
            y = row_ys[r]
            if not span_aware or r == 0 or r == rows:
                strokes.extend(
                    _emit_rule_strokes(
                        (col_xs[0], y),
                        (col_xs[cols], y),
                        style=eff_style,
                        jitter=eff_jitter,
                        overshoot=overshoot,
                        rng=border_rng,
                        block_id=block_id,
                        double=double,
                    )
                )
                return
            seg_start: int | None = None
            for c in range(cols + 1):
                need_edge = False
                if c < cols:
                    above = owner_grid[r - 1][c]
                    below = owner_grid[r][c]
                    need_edge = (above != below) or (above == -1)
                if need_edge and seg_start is None:
                    seg_start = c
                elif not need_edge and seg_start is not None:
                    strokes.extend(
                        _emit_rule_strokes(
                            (col_xs[seg_start], y),
                            (col_xs[c], y),
                            style=eff_style,
                            jitter=eff_jitter,
                            overshoot=overshoot,
                            rng=border_rng,
                            block_id=block_id,
                            double=double,
                        )
                    )
                    seg_start = None

        def _emit_v_boundaries(c: int, *, outer_only: bool = False) -> None:
            x = col_xs[c]
            if outer_only or c == 0 or c == cols:
                strokes.extend(
                    _emit_rule_strokes(
                        (x, row_ys[0]),
                        (x, row_ys[rows]),
                        style=eff_style,
                        jitter=eff_jitter,
                        overshoot=overshoot,
                        rng=border_rng,
                        block_id=block_id,
                    )
                )
                return
            seg_start: int | None = None
            for r in range(rows + 1):
                need_edge = False
                if r < rows:
                    left = owner_grid[r][c - 1]
                    right = owner_grid[r][c]
                    need_edge = (left != right) or (left == -1)
                if need_edge and seg_start is None:
                    seg_start = r
                elif not need_edge and seg_start is not None:
                    strokes.extend(
                        _emit_rule_strokes(
                            (x, row_ys[seg_start]),
                            (x, row_ys[r]),
                            style=eff_style,
                            jitter=eff_jitter,
                            overshoot=overshoot,
                            rng=border_rng,
                            block_id=block_id,
                        )
                    )
                    seg_start = None

        if eff_style == "three_line":
            _emit_h_boundaries(0, double=True, span_aware=False)
            if rows > 1:
                _emit_h_boundaries(1, double=False, span_aware=True)
            _emit_h_boundaries(rows, double=True, span_aware=False)
        elif eff_style == "horizontal":
            for r in range(rows + 1):
                _emit_h_boundaries(r)
        elif eff_style == "minimal":
            _emit_h_boundaries(0, span_aware=False)
            if rows > 1:
                _emit_h_boundaries(1, span_aware=True)
            _emit_h_boundaries(rows, span_aware=False)
            _emit_v_boundaries(0, outer_only=True)
            _emit_v_boundaries(cols, outer_only=True)
        else:
            # "grid", "compact", "dashed"
            for r in range(rows + 1):
                _emit_h_boundaries(r)
            for c in range(cols + 1):
                _emit_v_boundaries(c)

    # 2. Emit cell contents strictly row-by-row, left-to-right (r asc, c asc)
    shaped_cells.sort(key=lambda item: (item[0].r, item[0].c))
    for cell, lines, cell_font in shaped_cells:
        if not lines:
            continue
        r0 = max(0, min(rows - 1, cell.r))
        c0 = max(0, min(cols - 1, cell.c))
        rs = max(1, min(rows - r0, cell.rs))
        cs = max(1, min(cols - c0, cell.cs))

        cx0 = col_xs[c0] + pad_x
        cell_w = sum(col_ws[c0 : c0 + cs]) - 2.0 * pad_x
        cy0 = row_ys[r0]
        cell_h = sum(row_heights[r0 : r0 + rs])

        # Vertically center lines inside the cell
        line_hs = [max(cell_font * 1.15 * row_scale, ln.ascent_mm + ln.descent_mm + 0.5 * row_scale) for ln in lines]
        block_h = sum(line_hs)
        cur_y = cy0 + max(pad_y, 0.5 * (cell_h - block_h))

        # Center header row or short numeric cells; left-align longer cells
        cell_align = "center" if (r0 == 0 or (len(lines) == 1 and lines[0].natural_width_mm < cell_w * 0.6)) else "left"

        for li, (ln, lh) in enumerate(zip(lines, line_hs)):
            baseline_y = cur_y + ln.ascent_mm
            emitted = emit_shaped_line(
                ln,
                x0_mm=cx0,
                baseline_y_mm=baseline_y,
                line_width_mm=max(4.0, cell_w),
                font_size_mm=cell_font,
                char_spacing=config.text.char_spacing,
                align=cell_align,
                perturb_cfg=config.perturb,
                seed=config.perturb.seed,
                scope_key=("table_cell", page_index, block_id, r0, c0, li),
                block_id=block_id,
                kind="table",
                units_per_em=units_per_em,
                baseline_u=baseline_u,
                selector=selector,
                wave_mult=0.5,
                char_scale_x=eff_char_sx,
                char_scale_y=eff_char_sy,
                missing_out=missing_out,
                page_index=page_index,
                source_kind="table",
            )
            strokes.extend(emitted)
            cur_y += lh

    return strokes, total_h
