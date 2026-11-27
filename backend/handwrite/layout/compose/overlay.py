"""Exact Overlay composition mode respecting original page boxes and block overrides."""

from __future__ import annotations

import numpy as np

from handwrite.api.schemas import ComposedPage, LayoutConfig, MissingGlyphBox, PlacedBlockBox
from handwrite.docparse.docir import ChartData, DocBlock, DocIR
from handwrite.layout.chart_renderer import render_chart
from handwrite.layout.compose.finalize import (
    apply_global_overlay_transform,
    finalize_page,
    transform_missing_boxes,
    transform_placed_boxes,
)
from handwrite.layout.compose.regions import compose_field_region
from handwrite.layout.compose.rules import (
    SKIP_IN_REFLOW,
    ComposeProgressCB,
    SelectorGetter,
    append_math_missing_boxes,
    build_block_box_label,
    count_missing_chars,
    diff_counts,
    matches_page_scope,
    merge_counts,
    resolve_page_rule,
    resolve_page_size,
)
from handwrite.layout.math_typesetter import translate_math_strokes, typeset_math
from handwrite.layout.perturb import scope_rng
from handwrite.layout.shaper import (
    EmittedStroke,
    break_atoms_into_lines,
    emit_shaped_line,
    shape_inlines,
)
from handwrite.layout.table_renderer import render_table


def compose_overlay(
    doc: DocIR,
    get_selector: SelectorGetter,
    config: LayoutConfig,
    progress_cb: ComposeProgressCB | None,
) -> list[ComposedPage]:
    """Compose a document in Exact Overlay coordinate-registration mode."""
    default_w, default_h = resolve_page_size(config)
    page_dims: dict[int, tuple[float, float]] = {
        p.page_index: (float(p.width_mm), float(p.height_mm)) for p in doc.pages
    }
    if not page_dims:
        page_dims[0] = (default_w, default_h)

    by_page: dict[int, list[DocBlock]] = {pidx: [] for pidx in page_dims}
    for blk in sorted(doc.blocks, key=lambda b: b.reading_order):
        line_pages = {
            ln.page_index
            for ln in blk.lines
            if ln.page_index is not None and ln.inlines
        }
        if len(line_pages) > 1:
            grouped: dict[int, list] = {}
            default_pi = blk.page_index if blk.page_index is not None else 0
            for ln in blk.lines:
                lp = ln.page_index if ln.page_index is not None else default_pi
                grouped.setdefault(lp, []).append(ln)
            for lp, lns in sorted(grouped.items()):
                if lp not in page_dims:
                    page_dims[lp] = (default_w, default_h)
                    by_page[lp] = []
                lboxes = [ln.bbox_mm for ln in lns if ln.bbox_mm and len(ln.bbox_mm) == 4]
                sub_bbox = (
                    [
                        round(min(b[0] for b in lboxes), 2),
                        round(min(b[1] for b in lboxes), 2),
                        round(max(b[2] for b in lboxes), 2),
                        round(max(b[3] for b in lboxes), 2),
                    ]
                    if lboxes
                    else blk.bbox_mm
                )
                by_page[lp].append(
                    blk.model_copy(
                        update={"page_index": lp, "lines": lns, "bbox_mm": sub_bbox}
                    )
                )
            continue

        pidx = blk.page_index if blk.page_index is not None else 0
        if pidx not in page_dims:
            page_dims[pidx] = (default_w, default_h)
            by_page[pidx] = []
        by_page[pidx].append(blk)

    ov = config.overlay
    char_sx = float(config.text.char_scale_x)
    char_sy = float(config.text.char_scale_y)
    inner_row_spacing = float(config.formula.inner_row_spacing)
    page_indices = sorted(page_dims.keys())
    total_pages = max(1, len(page_indices))
    composed: list[ComposedPage] = []

    for pi_pos, pidx in enumerate(page_indices):
        if progress_cb is not None:
            progress_cb(
                "compose",
                0.08 + 0.82 * ((pi_pos + 1) / total_pages),
                f"正在套打第 {pidx + 1}/{total_pages} 页",
            )

        pw, ph = page_dims[pidx]
        rule = resolve_page_rule(pidx, config)
        selector, units_per_em, baseline_u, active_wid = get_selector(rule.writer_id)
        page_strokes: list[EmittedStroke] = []
        placed_boxes: list[PlacedBlockBox] = []
        page_missing: list[MissingGlyphBox] = []
        fb_before_page = dict(selector.fallback_counts)

        row_band_mm = max(3.5, float(config.text.font_size_mm) * 0.75)

        def _overlay_sort_key(b: DocBlock) -> tuple[int, float, int]:
            bb = b.bbox_mm
            if not bb or len(bb) < 4:
                return (10**6, 0.0, b.reading_order)
            ov_b = ov.blocks.get(b.block_id)
            nx = float(ov_b.nudge_mm.x) if ov_b else 0.0
            ny = float(ov_b.nudge_mm.y) if ov_b else 0.0
            return (int(round((float(bb[1]) + ny) / row_band_mm)), float(bb[0]) + nx, b.reading_order)

        ordered_page_blocks = sorted(by_page.get(pidx, []), key=_overlay_sort_key)

        for blk_idx, blk in enumerate(ordered_page_blocks):
            override = ov.blocks.get(blk.block_id)
            if override is not None:
                if not override.enabled:
                    continue
                nudge_x = float(override.nudge_mm.x)
                nudge_y = float(override.nudge_mm.y)
            else:
                if blk.type in SKIP_IN_REFLOW:
                    continue
                nudge_x, nudge_y = 0.0, 0.0

            if (
                blk.type in {"chart", "figure"}
                and getattr(blk, "placement", "inline") == "float"
                and getattr(blk, "float_box_mm", None)
                and len(blk.float_box_mm) == 4
            ):
                bbox = blk.float_box_mm
            else:
                bbox = blk.bbox_mm or [20.0, 22.0 + blk_idx * 18.0, pw - 20.0, 36.0 + blk_idx * 18.0]
            bx0 = float(bbox[0]) + nudge_x
            by0 = float(bbox[1]) + nudge_y
            bx1 = float(bbox[2]) + nudge_x
            by1 = float(bbox[3]) + nudge_y
            bw = max(8.0, bx1 - bx0)
            bh = max(4.0, by1 - by0)

            if blk.type == "formula_block" and blk.latex:
                f_rng = scope_rng(config.perturb.seed, "ov_formula", pidx, blk.block_id)
                base_f = min(config.text.font_size_mm * 1.05, max(4.0, bh * 0.42))
                ml = typeset_math(
                    blk.latex,
                    selector,
                    font_size_mm=base_f,
                    formula_scale=config.formula.scale,
                    inner_row_spacing=inner_row_spacing,
                    display=True,
                    perturb_cfg=config.perturb,
                    rng=f_rng,
                    units_per_em=units_per_em,
                    baseline_u=baseline_u,
                )
                sx = (bw * 0.96) / ml.width_mm if ml.width_mm > 1e-3 else 1.0
                sy = (bh * 0.92) / ml.total_height_mm if ml.total_height_mm > 1e-3 else 1.0
                fit_scale = min(1.0, sx, sy)
                fx = bx0 + 0.5 * (bw - ml.width_mm * fit_scale)
                fy_top = by0 + 0.5 * (bh - ml.total_height_mm * fit_scale)
                f_base_y = fy_top + ml.height_mm * fit_scale
                for st in translate_math_strokes(ml, fx, f_base_y, scale=fit_scale):
                    page_strokes.append(
                        EmittedStroke(pts=st, kind="formula", block_id=blk.block_id, reversible=False)
                    )
                append_math_missing_boxes(
                    page_missing,
                    ml,
                    x_mm=fx,
                    baseline_y_mm=f_base_y,
                    scale=fit_scale,
                    page_index=pidx,
                    block_id=blk.block_id,
                    latex=blk.latex,
                    policy=selector.fallback_policy,
                )
                placed_boxes.append(
                    PlacedBlockBox(
                        block_id=blk.block_id,
                        block_type="formula_block",
                        page_index=pidx,
                        bbox_mm=[
                            round(fx, 2),
                            round(fy_top, 2),
                            round(fx + ml.width_mm * fit_scale, 2),
                            round(fy_top + ml.total_height_mm * fit_scale, 2),
                        ],
                        label=build_block_box_label(blk),
                        latex=blk.latex,
                    )
                )
                continue

            if blk.type == "table" and blk.table is not None:
                t_strokes, t_h = render_table(
                    blk.table,
                    x0_mm=bx0,
                    y0_mm=by0,
                    width_mm=bw,
                    max_height_mm=bh,
                    selector=selector,
                    config=config,
                    block_id=blk.block_id,
                    page_index=pidx,
                    units_per_em=units_per_em,
                    baseline_u=baseline_u,
                    font_size_mm=rule.font_size_mm or config.text.font_size_mm,
                    char_scale_x=char_sx,
                    char_scale_y=char_sy,
                    missing_out=page_missing,
                )
                page_strokes.extend(t_strokes)
                placed_boxes.append(
                    PlacedBlockBox(
                        block_id=blk.block_id,
                        block_type="table",
                        page_index=pidx,
                        bbox_mm=[round(bx0, 2), round(by0, 2), round(bx1, 2), round(max(by1, by0 + t_h), 2)],
                        label=f"表格 · {blk.table.rows}×{blk.table.cols}",
                    )
                )
                continue

            if blk.type in {"chart", "figure"} and (blk.chart is not None or blk.image_path):
                chart_obj = blk.chart
                if chart_obj is None and blk.image_path:
                    chart_obj = ChartData(chart_type="raster", image_path=blk.image_path)
                eff_mode = getattr(blk, "image_render_mode", None) or config.chart.image_render_mode
                eff_placement = getattr(blk, "placement", None) or "inline"
                if chart_obj is not None:
                    c_strokes = render_chart(
                        chart_obj,
                        bbox_mm=[bx0, by0, bx1, by1],
                        selector=selector,
                        config=config,
                        block_id=blk.block_id,
                        page_index=pidx,
                        units_per_em=units_per_em,
                        baseline_u=baseline_u,
                        render_mode=eff_mode,
                        missing_out=page_missing,
                    )
                    page_strokes.extend(c_strokes)
                placed_boxes.append(
                    PlacedBlockBox(
                        block_id=blk.block_id,
                        block_type=blk.type,
                        page_index=pidx,
                        bbox_mm=[round(bx0, 2), round(by0, 2), round(bx1, 2), round(by1, 2)],
                        label=f"{'图表' if blk.type == 'chart' else '插图'} · {getattr(blk, 'asset_name', None) or blk.block_id}",
                        placement=eff_placement,
                        render_mode=eff_mode,
                    )
                )
                continue

            if blk.lines:
                line_hs = [
                    max(3.5, (ln.bbox_mm[3] - ln.bbox_mm[1]))
                    for ln in blk.lines
                    if ln.bbox_mm and len(ln.bbox_mm) == 4
                ]
                med_h = float(np.median(line_hs)) if line_hs else config.text.font_size_mm * 1.15 * char_sy
                est_font = max(3.2, min(config.text.font_size_mm * 1.35, med_h * 0.82))

                ordered_lines = sorted(
                    blk.lines,
                    key=lambda ln: (
                        int(round(float(ln.bbox_mm[1]) / max(2.5, med_h * 0.55)))
                        if ln.bbox_mm and len(ln.bbox_mm) == 4
                        else 10**6,
                        float(ln.bbox_mm[0]) if ln.bbox_mm and len(ln.bbox_mm) == 4 else 0.0,
                    ),
                )

                for li, doc_ln in enumerate(ordered_lines):
                    if not doc_ln.inlines:
                        continue
                    if doc_ln.bbox_mm and len(doc_ln.bbox_mm) == 4:
                        lx0 = float(doc_ln.bbox_mm[0]) + nudge_x
                        ly0 = float(doc_ln.bbox_mm[1]) + nudge_y
                        lx1 = float(doc_ln.bbox_mm[2]) + nudge_x
                        ly1 = float(doc_ln.bbox_mm[3]) + nudge_y
                    else:
                        lx0 = bx0
                        lx1 = bx1
                        ly0 = by0 + li * med_h
                        ly1 = ly0 + med_h
                    lw = max(8.0, lx1 - lx0)
                    lh = max(3.5, ly1 - ly0)

                    ln_rng = scope_rng(config.perturb.seed, "ov_line", pidx, blk.block_id, li)
                    atoms = shape_inlines(
                        doc_ln.inlines,
                        selector,
                        font_size_mm=est_font,
                        char_spacing=config.text.char_spacing,
                        formula_scale=config.formula.scale,
                        max_width_mm=lw * 1.4,
                        perturb_cfg=config.perturb,
                        rng=ln_rng,
                        units_per_em=units_per_em,
                        baseline_u=baseline_u,
                        inner_row_spacing=inner_row_spacing,
                        char_scale_x=char_sx,
                    )
                    nat_w = sum(a.width_mm for a in atoms)
                    use_font = est_font
                    if nat_w > lw * 1.02 and nat_w > 1e-3:
                        shrink = max(0.65, lw / nat_w)
                        use_font = max(2.8, est_font * shrink)
                        ln_rng = scope_rng(config.perturb.seed, "ov_line", pidx, blk.block_id, li)
                        atoms = shape_inlines(
                            doc_ln.inlines,
                            selector,
                            font_size_mm=use_font,
                            char_spacing=config.text.char_spacing,
                            formula_scale=config.formula.scale,
                            max_width_mm=lw * 1.2,
                            perturb_cfg=config.perturb,
                            rng=ln_rng,
                            units_per_em=units_per_em,
                            baseline_u=baseline_u,
                            inner_row_spacing=inner_row_spacing,
                            char_scale_x=char_sx,
                        )
                    shaped_lines = break_atoms_into_lines(atoms, line_width_mm=lw * 1.05, font_size_mm=use_font)
                    baseline_y = ly0 + lh * 0.82
                    for sl_i, sl in enumerate(shaped_lines):
                        inline_math_boxes: list[tuple[int | None, str, list[float]]] = []
                        page_strokes.extend(
                            emit_shaped_line(
                                sl,
                                x0_mm=lx0,
                                baseline_y_mm=baseline_y + sl_i * (use_font * 1.2 * char_sy),
                                line_width_mm=lw,
                                font_size_mm=use_font,
                                char_spacing=config.text.char_spacing,
                                align="left",
                                perturb_cfg=config.perturb,
                                seed=config.perturb.seed,
                                scope_key=("ov", pidx, blk.block_id, li, sl_i),
                                block_id=blk.block_id,
                                kind="text",
                                units_per_em=units_per_em,
                                baseline_u=baseline_u,
                                selector=selector,
                                wave_mult=0.7,
                                char_scale_x=char_sx,
                                char_scale_y=char_sy,
                                math_boxes_out=inline_math_boxes,
                                missing_out=page_missing,
                                page_index=pidx,
                                source_kind="text",
                            )
                        )
                        for m_idx, m_tex, m_box in inline_math_boxes:
                            placed_boxes.append(
                                PlacedBlockBox(
                                    block_id=blk.block_id,
                                    block_type="formula_inline",
                                    page_index=pidx,
                                    bbox_mm=m_box,
                                    label="行内公式",
                                    latex=m_tex,
                                    inline_index=m_idx,
                                )
                            )
                placed_boxes.append(
                    PlacedBlockBox(
                        block_id=blk.block_id,
                        block_type=blk.type,
                        page_index=pidx,
                        bbox_mm=[round(bx0, 2), round(by0, 2), round(bx1, 2), round(by1, 2)],
                        label=build_block_box_label(blk),
                    )
                )
                continue

            if blk.inlines:
                use_font = config.text.font_size_mm * (1.2 if blk.type == "heading" else 0.95)
                for attempt in range(3):
                    b_rng = scope_rng(config.perturb.seed, "ov_blk", pidx, blk.block_id)
                    atoms = shape_inlines(
                        blk.inlines,
                        selector,
                        font_size_mm=use_font,
                        char_spacing=config.text.char_spacing,
                        formula_scale=config.formula.scale,
                        max_width_mm=bw,
                        perturb_cfg=config.perturb,
                        rng=b_rng,
                        units_per_em=units_per_em,
                        baseline_u=baseline_u,
                        inner_row_spacing=inner_row_spacing,
                        char_scale_x=char_sx,
                    )
                    slines = break_atoms_into_lines(atoms, line_width_mm=bw, font_size_mm=use_font)
                    est_h = len(slines) * use_font * 1.32 * char_sy
                    if est_h <= bh * 1.05 or attempt == 2:
                        cy = by0
                        for sl_i, sl in enumerate(slines):
                            baseline_y = cy + max(sl.ascent_mm, use_font * 0.82) * char_sy
                            inline_math_boxes: list[tuple[int | None, str, list[float]]] = []
                            page_strokes.extend(
                                emit_shaped_line(
                                    sl,
                                    x0_mm=bx0,
                                    baseline_y_mm=baseline_y,
                                    line_width_mm=bw,
                                    font_size_mm=use_font,
                                    char_spacing=config.text.char_spacing,
                                    align="left",
                                    perturb_cfg=config.perturb,
                                    seed=config.perturb.seed,
                                    scope_key=("ov_blk", pidx, blk.block_id, sl_i),
                                    block_id=blk.block_id,
                                    kind="text",
                                    units_per_em=units_per_em,
                                    baseline_u=baseline_u,
                                    selector=selector,
                                    wave_mult=0.7,
                                    char_scale_x=char_sx,
                                    char_scale_y=char_sy,
                                    math_boxes_out=inline_math_boxes,
                                    missing_out=page_missing,
                                    page_index=pidx,
                                    source_kind="text",
                                )
                            )
                            for m_idx, m_tex, m_box in inline_math_boxes:
                                placed_boxes.append(
                                    PlacedBlockBox(
                                        block_id=blk.block_id,
                                        block_type="formula_inline",
                                        page_index=pidx,
                                        bbox_mm=m_box,
                                        label="行内公式",
                                        latex=m_tex,
                                        inline_index=m_idx,
                                    )
                                )
                            cy += max(use_font * 1.32 * char_sy, (sl.ascent_mm + sl.descent_mm) * char_sy + 0.8)
                        placed_boxes.append(
                            PlacedBlockBox(
                                block_id=blk.block_id,
                                block_type=blk.type,
                                page_index=pidx,
                                bbox_mm=[round(bx0, 2), round(by0, 2), round(bx1, 2), round(max(by1, cy), 2)],
                                label=build_block_box_label(blk),
                            )
                        )
                        break
                    use_font = max(3.0, use_font * 0.82)

        page_strokes = apply_global_overlay_transform(
            page_strokes,
            page_w=pw,
            page_h=ph,
            offset_x=float(ov.offset_mm.x),
            offset_y=float(ov.offset_mm.y),
            scale=float(ov.scale),
            rotation_deg=float(ov.rotation_deg),
        )
        placed_boxes = transform_placed_boxes(
            placed_boxes,
            page_w=pw,
            page_h=ph,
            offset_x=float(ov.offset_mm.x),
            offset_y=float(ov.offset_mm.y),
            scale=float(ov.scale),
            rotation_deg=float(ov.rotation_deg),
        )
        page_missing = transform_missing_boxes(
            page_missing,
            page_w=pw,
            page_h=ph,
            offset_x=float(ov.offset_mm.x),
            offset_y=float(ov.offset_mm.y),
            scale=float(ov.scale),
            rotation_deg=float(ov.rotation_deg),
        )

        field_regions = sorted(
            [
                r
                for r in config.regions
                if r.enabled and r.role == "field" and r.text.strip() and matches_page_scope(r.page_scope, pidx)
            ],
            key=lambda r: (r.order, r.y_mm, r.x_mm),
        )
        field_strokes: list[EmittedStroke] = []
        field_missing: list[MissingGlyphBox] = []
        for fr in field_regions:
            fs, _ = compose_field_region(
                fr, pidx, rule, get_selector, config, missing_out=field_missing
            )
            field_strokes.extend(fs)

        combined_missing = field_missing + page_missing
        fb_delta = count_missing_chars(combined_missing)

        composed.append(
            finalize_page(
                pidx,
                pw,
                ph,
                field_strokes + page_strokes,
                fb_delta,
                applied_rule_label=rule.label,
                background_id=rule.background_id,
                background_opacity=float(rule.background_opacity),
                writer_id=active_wid,
                placed_blocks=placed_boxes,
                missing_glyphs=combined_missing,
            )
        )

    return composed
