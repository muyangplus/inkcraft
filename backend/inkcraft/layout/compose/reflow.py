"""Smart Reflow composition mode with adaptive multi-frame/page breaking."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re

from inkcraft.api.schemas import (
    ComposedPage,
    LayoutConfig,
    MarginsMM,
    MissingGlyphBox,
    PageRuleOverride,
    PlacedBlockBox,
    RuledConfig,
    TableConfig,
    WritingRegion,
)
from inkcraft.docparse.docir import ChartData, DocIR, TableData
from inkcraft.docparse.inline_math import is_symbol_def_block
from inkcraft.layout.chart_renderer import render_chart
from inkcraft.layout.compose.finalize import finalize_page
from inkcraft.layout.compose.regions import compose_field_region
from inkcraft.layout.compose.rules import (
    SKIP_IN_REFLOW,
    ComposeProgressCB,
    SelectorGetter,
    append_math_missing_boxes,
    build_block_box_label,
    compute_effective_line_pitch_mm,
    count_missing_chars,
    diff_counts,
    matches_page_scope,
    max_explicit_region_page,
    merge_counts,
    resolve_page_rule,
    resolve_page_size,
)
from inkcraft.layout.math_typesetter import translate_math_strokes, typeset_math
from inkcraft.layout.perturb import scope_rng
from inkcraft.layout.shaper import (
    EmittedStroke,
    ShapedAtom,
    ShapedLine,
    break_atoms_into_lines,
    emit_shaped_line,
    generate_ruled_strokes,
    shape_inlines,
)
from inkcraft.layout.table_renderer import measure_table_height, render_table


_TABLE_CAPTION_TEXT_RE = re.compile(
    r"^(?:附?表\s*\d+|表\s*[一二三四五六七八九十\d]|Table\s*\d+)",
    re.IGNORECASE,
)
_FIGURE_CAPTION_TEXT_RE = re.compile(
    r"^(?:附?图\s*\d+|图\s*[一二三四五六七八九十\d]|Fig(?:ure)?\.?\s*\d+)",
    re.IGNORECASE,
)


def _is_table_caption_for_next(blk, next_blk) -> bool:
    """Return True when `blk` is a table title/caption directly preceding a table block."""
    if blk is None or next_blk is None or next_blk.type != "table" or next_blk.table is None:
        return False
    if blk.type not in {"caption", "paragraph", "heading"} or not getattr(blk, "inlines", None):
        return False
    txt = blk.plain_text().strip()
    if not txt or len(txt) > 85:
        return False
    if blk.type == "caption" and not _FIGURE_CAPTION_TEXT_RE.match(txt):
        return True
    if _TABLE_CAPTION_TEXT_RE.match(txt):
        return True
    return (
        "\n" not in txt
        and len(txt) <= 36
        and not any(p in txt for p in "。！？；")
        and (txt.endswith("表") or txt.endswith(("表：", "表:")))
    )


def _is_figure_caption_for_neighbor(blk, neighbor_blk) -> bool:
    """Return True when `blk` is a figure/chart caption directly adjacent to a figure/chart block."""
    if blk is None or neighbor_blk is None or neighbor_blk.type not in {"chart", "figure"}:
        return False
    if not (neighbor_blk.chart is not None or neighbor_blk.image_path):
        return False
    if blk.type not in {"caption", "paragraph", "heading"} or not getattr(blk, "inlines", None):
        return False
    txt = blk.plain_text().strip()
    if not txt or len(txt) > 85:
        return False
    if blk.type == "caption" and not _TABLE_CAPTION_TEXT_RE.match(txt):
        return True
    if _FIGURE_CAPTION_TEXT_RE.match(txt):
        return True
    return (
        "\n" not in txt
        and len(txt) <= 36
        and not any(p in txt for p in "。！？；")
        and (txt.endswith("图") or txt.endswith(("图：", "图:")))
    )


def _compute_inline_figure_size(blk, content_w: float, body_h: float) -> tuple[float, float]:
    """Return `(draw_w, draw_h)` in mm for an inline chart/figure block."""
    src_aspect = 0.65
    if getattr(blk, "image_width_mm", None) and getattr(blk, "image_height_mm", None):
        src_aspect = max(0.15, float(blk.image_height_mm) / max(1.0, float(blk.image_width_mm)))
    elif blk.bbox_mm and (blk.bbox_mm[2] - blk.bbox_mm[0]) > 5.0:
        src_aspect = max(0.15, (blk.bbox_mm[3] - blk.bbox_mm[1]) / (blk.bbox_mm[2] - blk.bbox_mm[0]))

    if getattr(blk, "image_width_mm", None):
        draw_w = max(18.0, min(content_w, float(blk.image_width_mm)))
    else:
        draw_w = min(content_w, content_w * 0.88)
    if getattr(blk, "image_height_mm", None):
        draw_h = max(14.0, min(max(20.0, body_h), float(blk.image_height_mm)))
    else:
        draw_h = max(36.0, min(92.0, draw_w * src_aspect))
    return draw_w, draw_h


@dataclass
class _ReflowPageBuf:
    page_index: int
    strokes: list[EmittedStroke] = field(default_factory=list)
    placed_blocks: list[PlacedBlockBox] = field(default_factory=list)
    fallback_counts: dict[str, int] = field(default_factory=dict)
    missing_glyphs: list[MissingGlyphBox] = field(default_factory=list)
    applied_rule_label: str = ""
    background_id: str | None = None
    background_opacity: float = 0.72
    writer_id: str | None = None


def _collect_remaining_atoms(remaining_lines: list[ShapedLine]) -> list[ShapedAtom]:
    """Flatten remaining lines back into atoms, preserving line breaks for mid-block reflow."""
    atoms: list[ShapedAtom] = []
    for idx, ln in enumerate(remaining_lines):
        if idx > 0 and atoms:
            if remaining_lines[idx - 1].is_last_line:
                atoms.append(ShapedAtom(kind="break"))
            elif not (atoms[-1].is_cjk and ln.atoms and ln.atoms[0].is_cjk):
                atoms.append(ShapedAtom(kind="space", text=" "))
        atoms.extend(ln.atoms)
    return atoms


def _resolve_table_geometry(
    table: TableData,
    tcfg: TableConfig,
    x0: float,
    content_w: float,
) -> tuple[float, float]:
    """Compute horizontal offset `tx0` and effective width `eff_w` honoring per-table or global style."""
    eff_style = table.border_style if table.border_style is not None else tcfg.border_style
    ratio = table.width_ratio if table.width_ratio is not None else tcfg.width_ratio
    if eff_style == "compact" and table.width_ratio is None and abs(float(tcfg.width_ratio) - 1.0) < 1e-4:
        ratio = 0.80
    eff_w = max(36.0, min(content_w, content_w * max(0.4, min(1.0, float(ratio)))))
    align = table.align or tcfg.align or "center"
    if align == "left":
        tx0 = x0
    elif align == "right":
        tx0 = x0 + max(0.0, content_w - eff_w)
    else:
        tx0 = x0 + max(0.0, 0.5 * (content_w - eff_w))
    return tx0, eff_w


def compose_reflow(
    doc: DocIR,
    get_selector: SelectorGetter,
    config: LayoutConfig,
    progress_cb: ComposeProgressCB | None,
) -> list[ComposedPage]:
    """Compose a document in adaptive Smart Reflow mode across frames and pages."""
    page_w, page_h = resolve_page_size(config)
    para_gap = float(config.text.paragraph_spacing_mm)

    pages: list[_ReflowPageBuf] = [_ReflowPageBuf(page_index=0)]
    cur_page = pages[0]

    margins: MarginsMM = config.page.margins_mm
    active_rule: PageRuleOverride = resolve_page_rule(0, config)
    body_frames: list[WritingRegion | None] = [None]
    frame_idx: int = 0
    x0: float = margins.left
    content_w: float = max(25.0, page_w - margins.left - margins.right)
    y_top: float = margins.top
    y_bottom: float = max(y_top + 25.0, page_h - margins.bottom)
    base_font: float = float(config.text.font_size_mm)
    line_spacing: float = float(config.text.line_spacing)
    line_spacing_mm: float | None = (
        float(config.text.line_spacing_mm) if config.text.line_spacing_mm is not None else None
    )
    char_spacing: float = float(config.text.char_spacing)
    char_sx: float = float(config.text.char_scale_x)
    char_sy: float = float(config.text.char_scale_y)
    ruled: RuledConfig = config.text.ruled
    ruled_active: bool = ruled.style in {"lines", "grid"}
    grid_pitch: float | None = float(ruled.pitch_mm) if ruled.style == "grid" else None
    ruled_p = float(ruled.pitch_mm) if ruled_active else 0.0
    base_pitch: float = compute_effective_line_pitch_mm(
        base_font, line_spacing, line_spacing_mm, char_sy, ruled_pitch_mm=ruled_p
    )
    selector, units_per_em, baseline_u, active_wid = get_selector(None)
    cursor_y = y_top
    line_counter = 0

    def _compute_pitch(font_mm: float) -> float:
        rp = float(ruled.pitch_mm) if ruled_active else 0.0
        return compute_effective_line_pitch_mm(
            font_mm, line_spacing, line_spacing_mm, char_sy, ruled_pitch_mm=rp
        )

    def _record_fb(before_snap: dict[str, int], target_sel=None, target_page: _ReflowPageBuf | None = None) -> None:
        sel = target_sel if target_sel is not None else selector
        p = target_page if target_page is not None else cur_page
        merge_counts(p.fallback_counts, diff_counts(before_snap, sel.fallback_counts))

    def _apply_frame(pbuf: _ReflowPageBuf, idx: int) -> None:
        nonlocal frame_idx, x0, content_w, y_top, y_bottom, para_gap
        nonlocal base_font, line_spacing, line_spacing_mm, char_spacing, ruled, ruled_active, grid_pitch, base_pitch
        nonlocal selector, units_per_em, baseline_u, active_wid, cursor_y

        frame_idx = idx
        fr = body_frames[idx] if idx < len(body_frames) else None
        if fr is None:
            x0 = float(margins.left)
            content_w = max(25.0, page_w - float(margins.left) - float(margins.right))
            y_top = float(margins.top)
            y_bottom = max(y_top + 25.0, page_h - float(margins.bottom))
            base_font = (
                float(active_rule.font_size_mm)
                if active_rule.font_size_mm is not None
                else float(config.text.font_size_mm)
            )
            line_spacing = (
                float(active_rule.line_spacing)
                if active_rule.line_spacing is not None
                else float(config.text.line_spacing)
            )
            line_spacing_mm = (
                float(active_rule.line_spacing_mm)
                if active_rule.line_spacing_mm is not None
                else (float(config.text.line_spacing_mm) if config.text.line_spacing_mm is not None else None)
            )
            para_gap = (
                float(active_rule.paragraph_spacing_mm)
                if active_rule.paragraph_spacing_mm is not None
                else float(config.text.paragraph_spacing_mm)
            )
            char_spacing = float(config.text.char_spacing)
            selector, units_per_em, baseline_u, active_wid = get_selector(active_rule.writer_id)
        else:
            x0 = float(fr.x_mm)
            content_w = max(12.0, float(fr.width_mm))
            y_top = float(fr.y_mm)
            y_bottom = max(y_top + 8.0, float(fr.y_mm) + float(fr.height_mm))
            base_font = float(
                fr.font_size_mm
                or active_rule.font_size_mm
                or config.text.font_size_mm
            )
            line_spacing = float(
                fr.line_spacing
                if fr.line_spacing is not None
                else (active_rule.line_spacing if active_rule.line_spacing is not None else config.text.line_spacing)
            )
            if fr.line_spacing_mm is not None:
                line_spacing_mm = float(fr.line_spacing_mm)
            elif active_rule.line_spacing_mm is not None:
                line_spacing_mm = float(active_rule.line_spacing_mm)
            elif config.text.line_spacing_mm is not None:
                line_spacing_mm = float(config.text.line_spacing_mm)
            else:
                line_spacing_mm = None
            para_gap = float(
                fr.paragraph_spacing_mm
                if fr.paragraph_spacing_mm is not None
                else (
                    active_rule.paragraph_spacing_mm
                    if active_rule.paragraph_spacing_mm is not None
                    else config.text.paragraph_spacing_mm
                )
            )
            char_spacing = float(
                fr.char_spacing
                if fr.char_spacing is not None
                else config.text.char_spacing
            )
            selector, units_per_em, baseline_u, active_wid = get_selector(
                fr.writer_id or active_rule.writer_id
            )

        base_pitch = _compute_pitch(base_font)
        pbuf.writer_id = active_wid
        cursor_y = y_top

    def _activate_page_rule(pbuf: _ReflowPageBuf) -> None:
        nonlocal margins, active_rule, body_frames, ruled, ruled_active, grid_pitch

        rule = resolve_page_rule(pbuf.page_index, config)
        active_rule = rule
        margins = rule.margins_mm if rule.margins_mm is not None else config.page.margins_mm
        ruled = rule.ruled if rule.ruled is not None else config.text.ruled
        ruled_active = ruled.style in {"lines", "grid"}
        grid_pitch = float(ruled.pitch_mm) if ruled.style == "grid" else None

        matching_body = sorted(
            [
                r
                for r in config.regions
                if r.enabled and r.role == "body" and matches_page_scope(r.page_scope, pbuf.page_index)
            ],
            key=lambda r: (r.order, r.y_mm, r.x_mm),
        )
        body_frames = list(matching_body) if matching_body else [None]

        pbuf.applied_rule_label = rule.label
        pbuf.background_id = rule.background_id
        pbuf.background_opacity = float(rule.background_opacity)

        if ruled.draw and ruled.style != "none":
            r_rng = scope_rng(config.perturb.seed, "ruled", pbuf.page_index)
            pbuf.strokes.extend(generate_ruled_strokes(page_w, page_h, margins, ruled, rng=r_rng))

        _apply_frame(pbuf, 0)

    _activate_page_rule(cur_page)

    def _new_page() -> None:
        nonlocal cur_page
        if frame_idx + 1 < len(body_frames):
            _apply_frame(cur_page, frame_idx + 1)
            return
        cur_page = _ReflowPageBuf(page_index=len(pages))
        pages.append(cur_page)
        _activate_page_rule(cur_page)

    def _block_font_and_layout(blk) -> tuple[float, str, float, float, float, float]:
        blk_font = base_font
        blk_align = config.text.align
        indent_mm = 0.0
        left_offset = 0.0
        before_gap = 0.0
        after_gap = para_gap

        if blk.type == "heading":
            scale_map = {1: 1.32, 2: 1.16, 3: 1.08}
            blk_font = min(24.0, base_font * scale_map.get(blk.level, 1.04))
            blk_align = "center" if blk.level == 1 else "left"
            before_gap = para_gap * 0.8 if cursor_y > y_top + 1.0 else 0.0
            after_gap = para_gap * 0.9
        elif blk.type == "paragraph":
            pitch = grid_pitch if grid_pitch is not None else base_font
            if is_symbol_def_block(blk):
                indent_chars = max(2.0, float(config.text.first_line_indent_chars))
                left_offset = min(indent_chars * pitch, max(0.0, content_w - 20.0))
                indent_mm = 0.0
                blk_align = "left"
                after_gap = para_gap * 0.65
            else:
                indent_mm = float(config.text.first_line_indent_chars) * pitch
        elif blk.type == "list_item":
            left_offset = base_font * 1.1
            blk_align = "left"
            after_gap = para_gap * 0.5
        elif blk.type == "caption":
            blk_font = max(3.5, base_font * 0.85)
            blk_align = "center"
            after_gap = para_gap * 0.7

        return blk_font, blk_align, indent_mm, left_offset, before_gap, after_gap

    ordered_blocks = sorted(doc.blocks, key=lambda b: b.reading_order)
    active_blocks = [b for b in ordered_blocks if b.type not in SKIP_IN_REFLOW]

    float_images_by_page: dict[int, list] = {}
    flow_blocks = []
    for blk in active_blocks:
        if (
            blk.type in {"chart", "figure"}
            and getattr(blk, "placement", "inline") == "float"
            and getattr(blk, "float_box_mm", None)
            and len(blk.float_box_mm) == 4
            and (blk.chart is not None or blk.image_path)
        ):
            pidx = max(0, int(blk.page_index or 0))
            float_images_by_page.setdefault(pidx, []).append(blk)
        else:
            flow_blocks.append(blk)

    def _resolve_wrap_band(pidx: int, line_x0: float, band_w: float, y0: float, y1: float) -> tuple[float, float, float | None]:
        """Return `(eff_x0, eff_w, blocked_jump_y)` after checking floating image obstacles on `pidx`."""
        obs_list = float_images_by_page.get(pidx, [])
        if not obs_list:
            return line_x0, band_w, None
        x_end = line_x0 + band_w
        eff_x0 = line_x0
        eff_x1 = x_end
        max_jump_y: float | None = None
        for ob in obs_list:
            fx0, fy0, fx1, fy1 = [float(v) for v in ob.float_box_mm]
            if y1 <= fy0 - 1.2 or y0 >= fy1 + 1.2:
                continue
            pad_x0 = max(line_x0, fx0 - 2.5)
            pad_x1 = min(x_end, fx1 + 2.5)
            if pad_x1 <= pad_x0:
                continue
            left_span = pad_x0 - eff_x0
            right_span = eff_x1 - pad_x1
            if left_span >= right_span and left_span >= 18.0:
                eff_x1 = pad_x0
            elif right_span > left_span and right_span >= 18.0:
                eff_x0 = pad_x1
            else:
                max_jump_y = max(max_jump_y or 0.0, fy1 + 1.5)
        if max_jump_y is not None:
            return line_x0, band_w, max_jump_y
        return eff_x0, max(16.0, eff_x1 - eff_x0), None

    def _skip_float_vertical(pidx: int, y0: float, req_h: float) -> float:
        """Advance block top `y0` past any floating image overlapping `[y0, y0 + req_h]`."""
        obs_list = float_images_by_page.get(pidx, [])
        if not obs_list:
            return y0
        cur_y = y0
        for _ in range(len(obs_list) + 1):
            bumped = False
            for ob in obs_list:
                _, fy0, _, fy1 = [float(v) for v in ob.float_box_mm]
                if not (cur_y + req_h <= fy0 - 1.5 or cur_y >= fy1 + 1.5):
                    if fy1 + 2.0 > cur_y:
                        cur_y = fy1 + 2.0
                        bumped = True
            if not bumped:
                break
        return cur_y

    def _estimate_text_lines_end_y(
        lines_list: list[ShapedLine],
        blk_font: float,
        blk_pitch: float,
        start_y: float,
        after_gap: float,
        *,
        include_after_gap: bool,
    ) -> float:
        """Simulate Y progression across shaped text lines without mutating page state."""
        sim_y = start_y
        f_gap = float(config.formula.line_spacing_mm)
        for ln in lines_list:
            has_inline_math = any(a.kind == "math" for a in ln.atoms)
            if has_inline_math:
                math_h = max(blk_font * 0.80, ln.ascent_mm + ln.descent_mm + f_gap)
                need_h = (
                    max(blk_pitch + min(0.0, f_gap * 0.5), math_h)
                    if f_gap < 0
                    else max(blk_pitch, math_h)
                )
            else:
                need_h = blk_pitch
            if ruled_active and ruled.pitch_mm > 0:
                eff_need = (
                    need_h
                    if not (has_inline_math and f_gap <= 0)
                    else min(need_h, float(ruled.pitch_mm) * 1.0)
                )
                slots = max(1, int(math.ceil(eff_need / float(ruled.pitch_mm))))
                step_h = slots * float(ruled.pitch_mm)
                rel = sim_y - y_top
                slot_idx = int(math.ceil((rel - 0.1) / float(ruled.pitch_mm)))
                slot_top = y_top + slot_idx * float(ruled.pitch_mm)
                sim_y = slot_top + step_h
            else:
                sim_y = sim_y + need_h
        if include_after_gap:
            if ruled_active and ruled.pitch_mm > 0:
                slots_gap = max(0, round(after_gap / float(ruled.pitch_mm)))
                sim_y += slots_gap * float(ruled.pitch_mm)
            else:
                sim_y = max(y_top, sim_y + after_gap)
        return sim_y

    def _estimate_next_text_block_end_y(
        target_blk,
        start_y: float,
        *,
        include_after_gap: bool,
    ) -> float:
        """Measure end Y of an upcoming text block using a dry-run selector."""
        t_font, _, t_indent, t_left_off, t_before_gap, t_after_gap = _block_font_and_layout(target_blk)
        t_avail_w = max(20.0, content_w - t_left_off)
        dry_sel = selector.clone()
        t_rng = scope_rng(config.perturb.seed, "shape", target_blk.block_id)
        t_atoms = shape_inlines(
            target_blk.inlines,
            dry_sel,
            font_size_mm=t_font,
            char_spacing=char_spacing,
            formula_scale=config.formula.scale,
            max_width_mm=t_avail_w,
            perturb_cfg=config.perturb,
            rng=t_rng,
            units_per_em=units_per_em,
            baseline_u=baseline_u,
            grid_pitch_mm=grid_pitch if target_blk.type == "paragraph" else None,
            inner_row_spacing=config.formula.inner_row_spacing,
            char_scale_x=char_sx,
        )
        t_lines = break_atoms_into_lines(
            t_atoms,
            line_width_mm=t_avail_w,
            first_line_indent_mm=t_indent,
            font_size_mm=t_font,
        )
        if not t_lines:
            return start_y
        return _estimate_text_lines_end_y(
            t_lines,
            t_font,
            _compute_pitch(t_font),
            max(y_top, start_y + t_before_gap),
            t_after_gap,
            include_after_gap=include_after_gap,
        )

    total_blocks = max(1, len(flow_blocks))

    for b_idx, blk in enumerate(flow_blocks):
        if progress_cb is not None and (b_idx % 4 == 0 or b_idx == total_blocks - 1):
            progress_cb(
                "compose",
                0.05 + 0.85 * ((b_idx + 1) / total_blocks),
                f"正在重排块 {b_idx + 1}/{total_blocks} ({blk.type})",
            )

        # 1. Display Formula Block
        if blk.type == "formula_block" and blk.latex:
            sel_before = selector
            fb_before = dict(sel_before.fallback_counts)
            f_rng = scope_rng(config.perturb.seed, "formula_block", blk.block_id)
            ml = typeset_math(
                blk.latex,
                selector,
                font_size_mm=base_font * 1.05,
                formula_scale=config.formula.scale,
                inner_row_spacing=config.formula.inner_row_spacing,
                display=True,
                perturb_cfg=config.perturb,
                rng=f_rng,
                units_per_em=units_per_em,
                baseline_u=baseline_u,
            )
            f_scale = 1.0
            if ml.width_mm > content_w * 0.96 and ml.width_mm > 1e-3:
                f_scale = max(0.55, (content_w * 0.96) / ml.width_mm)

            f_gap = float(config.formula.line_spacing_mm)
            pad_top = f_gap * 0.5
            pad_bot = f_gap * 0.5
            req_h = max(base_font * 0.72, ml.total_height_mm * f_scale + pad_top + pad_bot)
            cursor_y = _skip_float_vertical(cur_page.page_index, cursor_y, req_h)
            if cursor_y + req_h > y_bottom and cursor_y > y_top + 1.0:
                _record_fb(fb_before, sel_before, cur_page)
                _new_page()
                # Re-typeset on new page in case writer/font/width changed
                sel_before = selector
                fb_before = dict(sel_before.fallback_counts)
                f_rng = scope_rng(config.perturb.seed, "formula_block", blk.block_id)
                ml = typeset_math(
                    blk.latex,
                    selector,
                    font_size_mm=base_font * 1.05,
                    formula_scale=config.formula.scale,
                    inner_row_spacing=config.formula.inner_row_spacing,
                    display=True,
                    perturb_cfg=config.perturb,
                    rng=f_rng,
                    units_per_em=units_per_em,
                    baseline_u=baseline_u,
                )
                f_scale = 1.0
                if ml.width_mm > content_w * 0.96 and ml.width_mm > 1e-3:
                    f_scale = max(0.55, (content_w * 0.96) / ml.width_mm)
                req_h = max(base_font * 0.72, ml.total_height_mm * f_scale + pad_top + pad_bot)
                cursor_y = _skip_float_vertical(cur_page.page_index, cursor_y, req_h)

            fx = x0 + max(0.0, 0.5 * (content_w - ml.width_mm * f_scale))
            f_base_y = cursor_y + pad_top + ml.height_mm * f_scale
            for st in translate_math_strokes(ml, fx, f_base_y, scale=f_scale):
                cur_page.strokes.append(
                    EmittedStroke(pts=st, kind="formula", block_id=blk.block_id, reversible=False)
                )
            append_math_missing_boxes(
                cur_page.missing_glyphs,
                ml,
                x_mm=fx,
                baseline_y_mm=f_base_y,
                scale=f_scale,
                page_index=cur_page.page_index,
                block_id=blk.block_id,
                latex=blk.latex,
                policy=selector.fallback_policy,
            )
            f_box_y0 = cursor_y + max(0.0, pad_top)
            cur_page.placed_blocks.append(
                PlacedBlockBox(
                    block_id=blk.block_id,
                    block_type="formula_block",
                    page_index=cur_page.page_index,
                    bbox_mm=[
                        round(fx, 2),
                        round(f_box_y0, 2),
                        round(fx + ml.width_mm * f_scale, 2),
                        round(f_box_y0 + ml.total_height_mm * f_scale, 2),
                    ],
                    label=build_block_box_label(blk),
                    latex=blk.latex,
                )
            )
            cursor_y = max(y_top, cursor_y + req_h)
            _record_fb(fb_before, sel_before, cur_page)
            continue

        # 2. Table Block
        if blk.type == "table" and blk.table is not None:
            sel_before = selector
            fb_before = dict(sel_before.fallback_counts)
            t_y0 = _skip_float_vertical(cur_page.page_index, cursor_y, 24.0)
            tx0, t_eff_w = _resolve_table_geometry(blk.table, config.table, x0, content_w)
            t_missing: list[MissingGlyphBox] = []
            t_strokes, t_h = render_table(
                blk.table,
                x0_mm=tx0,
                y0_mm=t_y0,
                width_mm=t_eff_w,
                max_height_mm=None,
                selector=selector,
                config=config,
                block_id=blk.block_id,
                page_index=cur_page.page_index,
                units_per_em=units_per_em,
                baseline_u=baseline_u,
                font_size_mm=base_font,
                char_scale_x=char_sx,
                char_scale_y=char_sy,
                missing_out=t_missing,
            )
            shifted_y0 = _skip_float_vertical(cur_page.page_index, t_y0, t_h)
            if shifted_y0 > t_y0 + 0.5:
                t_y0 = shifted_y0
                fb_re = dict(selector.fallback_counts)
                t_missing = []
                t_strokes, t_h = render_table(
                    blk.table,
                    x0_mm=tx0,
                    y0_mm=t_y0,
                    width_mm=t_eff_w,
                    max_height_mm=None,
                    selector=selector,
                    config=config,
                    block_id=blk.block_id,
                    page_index=cur_page.page_index,
                    units_per_em=units_per_em,
                    baseline_u=baseline_u,
                    font_size_mm=base_font,
                    char_scale_x=char_sx,
                    char_scale_y=char_sy,
                    missing_out=t_missing,
                )
                fb_before = fb_re
            cursor_y = t_y0
            if cursor_y + t_h > y_bottom and cursor_y > y_top + 1.0:
                old_page = cur_page
                _new_page()
                tx0, t_eff_w = _resolve_table_geometry(blk.table, config.table, x0, content_w)
                cursor_y = _skip_float_vertical(cur_page.page_index, cursor_y, t_h)
                fb_new_before = dict(selector.fallback_counts)
                t_missing = []
                t_strokes, t_h = render_table(
                    blk.table,
                    x0_mm=tx0,
                    y0_mm=cursor_y,
                    width_mm=t_eff_w,
                    max_height_mm=None,
                    selector=selector,
                    config=config,
                    block_id=blk.block_id,
                    page_index=cur_page.page_index,
                    units_per_em=units_per_em,
                    baseline_u=baseline_u,
                    font_size_mm=base_font,
                    char_scale_x=char_sx,
                    char_scale_y=char_sy,
                    missing_out=t_missing,
                )
                if selector is sel_before:
                    merge_counts(cur_page.fallback_counts, diff_counts(fb_new_before, selector.fallback_counts))
                else:
                    _record_fb(fb_before, sel_before, old_page)
                    _record_fb(fb_new_before, selector, cur_page)
            else:
                _record_fb(fb_before, sel_before, cur_page)

            cur_page.missing_glyphs.extend(t_missing)
            cur_page.strokes.extend(t_strokes)
            cur_page.placed_blocks.append(
                PlacedBlockBox(
                    block_id=blk.block_id,
                    block_type="table",
                    page_index=cur_page.page_index,
                    bbox_mm=[round(tx0, 2), round(cursor_y, 2), round(tx0 + t_eff_w, 2), round(cursor_y + t_h, 2)],
                    label=f"表格 · {blk.table.rows}×{blk.table.cols}",
                )
            )
            cursor_y += t_h + para_gap + 2.0
            continue

        # 3. Inline Chart / Figure Block
        if blk.type in {"chart", "figure"} and (blk.chart is not None or blk.image_path):
            chart_obj = blk.chart
            if chart_obj is None and blk.image_path:
                chart_obj = ChartData(chart_type="raster", image_path=blk.image_path)
            if chart_obj is not None:
                eff_mode = getattr(blk, "image_render_mode", None) or config.chart.image_render_mode
                draw_w, draw_h = _compute_inline_figure_size(blk, content_w, max(20.0, y_bottom - y_top))

                need_page_break = cursor_y + draw_h > y_bottom
                if not need_page_break and config.chart.keep_caption_with_figure and cursor_y > y_top + 1.0:
                    next_blk = flow_blocks[b_idx + 1] if b_idx + 1 < len(flow_blocks) else None
                    if _is_figure_caption_for_neighbor(next_blk, blk):
                        cap_start_y = cursor_y + draw_h + para_gap + 2.0
                        cap_end_y = _estimate_next_text_block_end_y(
                            next_blk, cap_start_y, include_after_gap=False
                        )
                        fresh_end_y = _estimate_next_text_block_end_y(
                            next_blk, y_top + draw_h + para_gap + 2.0, include_after_gap=False
                        )
                        if cap_end_y > y_bottom and fresh_end_y <= y_bottom:
                            need_page_break = True

                if need_page_break and cursor_y > y_top + 1.0:
                    _new_page()
                    draw_w, draw_h = _compute_inline_figure_size(blk, content_w, max(20.0, y_bottom - y_top))

                align_mode = getattr(blk, "image_align", "center")
                if align_mode == "left":
                    ix0 = x0
                elif align_mode == "right":
                    ix0 = x0 + max(0.0, content_w - draw_w)
                else:
                    ix0 = x0 + max(0.0, 0.5 * (content_w - draw_w))

                sel_before = selector
                fb_before = dict(sel_before.fallback_counts)
                cbbox = [round(ix0, 2), round(cursor_y, 2), round(ix0 + draw_w, 2), round(min(y_bottom, cursor_y + draw_h), 2)]
                c_strokes = render_chart(
                    chart_obj,
                    bbox_mm=cbbox,
                    selector=selector,
                    config=config,
                    block_id=blk.block_id,
                    page_index=cur_page.page_index,
                    units_per_em=units_per_em,
                    baseline_u=baseline_u,
                    render_mode=eff_mode,
                    missing_out=cur_page.missing_glyphs,
                )
                cur_page.strokes.extend(c_strokes)
                cur_page.placed_blocks.append(
                    PlacedBlockBox(
                        block_id=blk.block_id,
                        block_type=blk.type,
                        page_index=cur_page.page_index,
                        bbox_mm=cbbox,
                        label=f"{'图表' if blk.type == 'chart' else '插图'} · {getattr(blk, 'asset_name', None) or blk.block_id}",
                        placement="inline",
                        render_mode=eff_mode,
                    )
                )
                cursor_y = cbbox[3] + para_gap + 2.0
                _record_fb(fb_before, sel_before, cur_page)
            continue

        # 4. Textual blocks (heading, paragraph, list_item, caption)
        if not blk.inlines:
            continue

        blk_font, blk_align, indent_mm, left_offset, before_gap, after_gap = _block_font_and_layout(blk)
        avail_w = max(20.0, content_w - left_offset)
        sel_shape = selector
        fb_shape_before = dict(sel_shape.fallback_counts)
        shape_rng = scope_rng(config.perturb.seed, "shape", blk.block_id)
        atoms = shape_inlines(
            blk.inlines,
            selector,
            font_size_mm=blk_font,
            char_spacing=char_spacing,
            formula_scale=config.formula.scale,
            max_width_mm=avail_w,
            perturb_cfg=config.perturb,
            rng=shape_rng,
            units_per_em=units_per_em,
            baseline_u=baseline_u,
            grid_pitch_mm=grid_pitch if blk.type == "paragraph" else None,
            inner_row_spacing=config.formula.inner_row_spacing,
            char_scale_x=char_sx,
        )
        _record_fb(fb_shape_before, sel_shape, cur_page)
        lines = break_atoms_into_lines(
            atoms,
            line_width_mm=avail_w,
            first_line_indent_mm=indent_mm,
            font_size_mm=blk_font,
        )
        if not lines:
            continue

        need_pre_break = False
        if blk.type == "heading" and (cursor_y + before_gap + base_pitch * 2.2) > y_bottom and cursor_y > y_top + 1.0:
            need_pre_break = True
        elif cursor_y > y_top + 1.0:
            next_blk = flow_blocks[b_idx + 1] if b_idx + 1 < len(flow_blocks) else None
            prev_blk = flow_blocks[b_idx - 1] if b_idx > 0 else None
            blk_pitch_est = _compute_pitch(blk_font)
            cap_end_y = _estimate_text_lines_end_y(
                lines,
                blk_font,
                blk_pitch_est,
                max(y_top, cursor_y + before_gap),
                after_gap,
                include_after_gap=True,
            )
            cap_end_from_top = _estimate_text_lines_end_y(
                lines,
                blk_font,
                blk_pitch_est,
                y_top,
                after_gap,
                include_after_gap=True,
            )
            if config.table.keep_caption_with_table and _is_table_caption_for_next(blk, next_blk):
                _, t_eff_w = _resolve_table_geometry(next_blk.table, config.table, x0, content_w)
                t_h = measure_table_height(
                    next_blk.table,
                    width_mm=t_eff_w,
                    max_height_mm=None,
                    selector=selector,
                    config=config,
                    block_id=next_blk.block_id,
                    units_per_em=units_per_em,
                    baseline_u=baseline_u,
                    font_size_mm=base_font,
                    char_scale_x=char_sx,
                    char_scale_y=char_sy,
                )
                t_y0 = _skip_float_vertical(cur_page.page_index, cap_end_y, 24.0)
                shifted_t_y0 = _skip_float_vertical(cur_page.page_index, t_y0, t_h)
                if shifted_t_y0 > t_y0 + 0.5:
                    t_y0 = shifted_t_y0
                if t_y0 + t_h > y_bottom and cap_end_from_top + t_h <= y_bottom:
                    need_pre_break = True
            elif (
                config.chart.keep_caption_with_figure
                and (prev_blk is None or prev_blk.type not in {"chart", "figure"})
                and _is_figure_caption_for_neighbor(blk, next_blk)
            ):
                _, fig_h = _compute_inline_figure_size(next_blk, content_w, max(20.0, y_bottom - y_top))
                if cap_end_y + fig_h > y_bottom and cap_end_from_top + fig_h <= y_bottom:
                    need_pre_break = True

        if need_pre_break:
            prev_shape_w = avail_w
            prev_blk_font = blk_font
            _new_page()
            before_gap = 0.0
            blk_font, blk_align, indent_mm, left_offset, _, after_gap = _block_font_and_layout(blk)
            avail_w = max(20.0, content_w - left_offset)
            if abs(avail_w - prev_shape_w) > 1.0 or abs(blk_font - prev_blk_font) > 0.05:
                sel_reshape = selector
                fb_reshape_before = dict(sel_reshape.fallback_counts)
                reshape_rng = scope_rng(config.perturb.seed, "shape", blk.block_id, cur_page.page_index)
                atoms = shape_inlines(
                    blk.inlines,
                    selector,
                    font_size_mm=blk_font,
                    char_spacing=char_spacing,
                    formula_scale=config.formula.scale,
                    max_width_mm=avail_w,
                    perturb_cfg=config.perturb,
                    rng=reshape_rng,
                    units_per_em=units_per_em,
                    baseline_u=baseline_u,
                    grid_pitch_mm=grid_pitch if blk.type == "paragraph" else None,
                    inner_row_spacing=config.formula.inner_row_spacing,
                    char_scale_x=char_sx,
                )
                _record_fb(fb_reshape_before, sel_reshape, cur_page)
                lines = break_atoms_into_lines(
                    atoms,
                    line_width_mm=avail_w,
                    first_line_indent_mm=indent_mm,
                    font_size_mm=blk_font,
                )
                if not lines:
                    continue

        cursor_y = max(y_top, cursor_y + before_gap)
        blk_pitch = _compute_pitch(blk_font)

        f_gap = float(config.formula.line_spacing_mm)
        l_idx = 0
        current_break_w = avail_w
        blk_span_y0: float | None = None
        blk_span_y1: float | None = None
        blk_span_x0: float = x0 + left_offset
        blk_span_x1: float = x0 + left_offset + avail_w
        obstacle_skips = 0

        def _flush_text_box() -> None:
            nonlocal blk_span_y0, blk_span_y1
            if blk_span_y0 is not None and blk_span_y1 is not None:
                cur_page.placed_blocks.append(
                    PlacedBlockBox(
                        block_id=blk.block_id,
                        block_type=blk.type,
                        page_index=cur_page.page_index,
                        bbox_mm=[round(blk_span_x0, 2), round(blk_span_y0, 2), round(blk_span_x1, 2), round(blk_span_y1, 2)],
                        label=build_block_box_label(blk),
                    )
                )
            blk_span_y0 = None
            blk_span_y1 = None

        while l_idx < len(lines):
            ln = lines[l_idx]
            has_inline_math = any(a.kind == "math" for a in ln.atoms)
            if has_inline_math:
                math_h = max(blk_font * 0.80, ln.ascent_mm + ln.descent_mm + f_gap)
                need_h = max(blk_pitch + min(0.0, f_gap * 0.5), math_h) if f_gap < 0 else max(blk_pitch, math_h)
            else:
                need_h = blk_pitch

            eff_x0, wrap_w, jump_y = _resolve_wrap_band(
                cur_page.page_index,
                x0 + left_offset,
                avail_w,
                cursor_y,
                cursor_y + need_h,
            )
            if jump_y is not None and jump_y > cursor_y and obstacle_skips < 12:
                obstacle_skips += 1
                cursor_y = jump_y
                if cursor_y + need_h <= y_bottom or cursor_y <= y_top + 1.0:
                    continue

            broke_to_new_page = False
            if ruled_active and ruled.pitch_mm > 0:
                eff_need = need_h if not (has_inline_math and f_gap <= 0) else min(need_h, float(ruled.pitch_mm) * 1.0)
                slots = max(1, int(math.ceil(eff_need / float(ruled.pitch_mm))))
                step_h = slots * float(ruled.pitch_mm)
                rel = cursor_y - y_top
                slot_idx = int(math.ceil((rel - 0.1) / float(ruled.pitch_mm)))
                slot_top = y_top + slot_idx * float(ruled.pitch_mm)
                if slot_top + step_h > y_bottom and cursor_y > y_top + 1.0:
                    broke_to_new_page = True
            else:
                if cursor_y + need_h > y_bottom and cursor_y > y_top + 1.0:
                    broke_to_new_page = True

            if broke_to_new_page:
                _flush_text_box()
                prev_avail_w = current_break_w
                prev_font = blk_font
                _new_page()
                blk_font, blk_align, _, left_offset, _, after_gap = _block_font_and_layout(blk)
                avail_w = max(20.0, content_w - left_offset)
                blk_pitch = _compute_pitch(blk_font)
                blk_span_x0 = x0 + left_offset
                blk_span_x1 = x0 + left_offset + avail_w
                eff_x0, wrap_w, _ = _resolve_wrap_band(
                    cur_page.page_index,
                    x0 + left_offset,
                    avail_w,
                    cursor_y,
                    cursor_y + blk_pitch,
                )
                if abs(wrap_w - prev_avail_w) > 1.0 or abs(blk_font - prev_font) > 0.05:
                    rem_atoms = _collect_remaining_atoms(lines[l_idx:])
                    lines = break_atoms_into_lines(
                        rem_atoms,
                        line_width_mm=wrap_w,
                        first_line_indent_mm=0.0,
                        font_size_mm=blk_font,
                    )
                    current_break_w = wrap_w
                    l_idx = 0
                    if not lines:
                        break
                    ln = lines[0]
                    has_inline_math = any(a.kind == "math" for a in ln.atoms)
                    if has_inline_math:
                        math_h = max(blk_font * 0.80, ln.ascent_mm + ln.descent_mm + f_gap)
                        need_h = max(blk_pitch + min(0.0, f_gap * 0.5), math_h) if f_gap < 0 else max(blk_pitch, math_h)
                    else:
                        need_h = blk_pitch
            elif abs(wrap_w - current_break_w) > 1.5:
                rem_atoms = _collect_remaining_atoms(lines[l_idx:])
                lines = break_atoms_into_lines(
                    rem_atoms,
                    line_width_mm=wrap_w,
                    first_line_indent_mm=indent_mm if (l_idx == 0 and blk_span_y0 is None) else 0.0,
                    font_size_mm=blk_font,
                )
                current_break_w = wrap_w
                l_idx = 0
                if not lines:
                    break
                ln = lines[0]
                has_inline_math = any(a.kind == "math" for a in ln.atoms)
                if has_inline_math:
                    math_h = max(blk_font * 0.80, ln.ascent_mm + ln.descent_mm + f_gap)
                    need_h = max(blk_pitch + min(0.0, f_gap * 0.5), math_h) if f_gap < 0 else max(blk_pitch, math_h)
                else:
                    need_h = blk_pitch

            if ruled_active and ruled.pitch_mm > 0:
                eff_need = need_h if not (has_inline_math and f_gap <= 0) else min(need_h, float(ruled.pitch_mm) * 1.0)
                slots = max(1, int(math.ceil(eff_need / float(ruled.pitch_mm))))
                step_h = slots * float(ruled.pitch_mm)
                rel = cursor_y - y_top
                slot_idx = int(math.ceil((rel - 0.1) / float(ruled.pitch_mm)))
                slot_top = y_top + slot_idx * float(ruled.pitch_mm)
                baseline_y = slot_top + step_h - 0.15 * float(ruled.pitch_mm)
                line_top_y = slot_top
                next_y = slot_top + step_h
            else:
                if has_inline_math and f_gap < 0:
                    baseline_y = cursor_y + max(blk_font * 0.78, ln.ascent_mm + f_gap * 0.35)
                else:
                    baseline_y = cursor_y + max(ln.ascent_mm, blk_font * 0.82) * char_sy
                line_top_y = cursor_y
                next_y = cursor_y + need_h

            sel_line = selector
            fb_line_before = dict(sel_line.fallback_counts)
            inline_math_boxes: list[tuple[int | None, str, list[float]]] = []
            emitted = emit_shaped_line(
                ln,
                x0_mm=eff_x0,
                baseline_y_mm=baseline_y,
                line_width_mm=wrap_w,
                font_size_mm=blk_font,
                char_spacing=char_spacing,
                align=blk_align,
                perturb_cfg=config.perturb,
                seed=config.perturb.seed,
                scope_key=(cur_page.page_index, line_counter, blk.block_id, l_idx),
                block_id=blk.block_id,
                kind="text",
                units_per_em=units_per_em,
                baseline_u=baseline_u,
                selector=selector,
                grid_pitch_mm=grid_pitch if blk.type == "paragraph" else None,
                char_scale_x=char_sx,
                char_scale_y=char_sy,
                math_boxes_out=inline_math_boxes,
                missing_out=cur_page.missing_glyphs,
                page_index=cur_page.page_index,
                source_kind="text",
            )
            cur_page.strokes.extend(emitted)
            for m_idx, m_tex, m_box in inline_math_boxes:
                cur_page.placed_blocks.append(
                    PlacedBlockBox(
                        block_id=blk.block_id,
                        block_type="formula_inline",
                        page_index=cur_page.page_index,
                        bbox_mm=m_box,
                        label="行内公式",
                        latex=m_tex,
                        inline_index=m_idx,
                    )
                )
            if blk_span_y0 is None:
                blk_span_y0 = line_top_y
            blk_span_y1 = next_y
            _record_fb(fb_line_before, sel_line, cur_page)
            cursor_y = next_y
            line_counter += 1
            l_idx += 1

        _flush_text_box()
        if ruled_active and ruled.pitch_mm > 0:
            slots_gap = max(0, round(after_gap / float(ruled.pitch_mm)))
            cursor_y += slots_gap * float(ruled.pitch_mm)
        else:
            cursor_y = max(y_top, cursor_y + after_gap)

    max_field_page = max_explicit_region_page(config.regions)
    max_float_page = max(float_images_by_page.keys(), default=0)
    target_last_page = max(max_field_page, max_float_page)
    while len(pages) <= target_last_page:
        cur_page = _ReflowPageBuf(page_index=len(pages))
        pages.append(cur_page)
        _activate_page_rule(cur_page)

    composed: list[ComposedPage] = []
    for pbuf in pages:
        p_rule = resolve_page_rule(pbuf.page_index, config)

        # Render floating images placed onto this page
        for fl_blk in float_images_by_page.get(pbuf.page_index, []):
            fl_box = [round(float(v), 2) for v in fl_blk.float_box_mm]
            eff_mode = getattr(fl_blk, "image_render_mode", None) or config.chart.image_render_mode
            chart_obj = fl_blk.chart
            if chart_obj is None and fl_blk.image_path:
                chart_obj = ChartData(chart_type="raster", image_path=fl_blk.image_path)
            if chart_obj is not None:
                fl_sel, fl_upm, fl_base_u, _ = get_selector(p_rule.writer_id)
                fb_fl_before = dict(fl_sel.fallback_counts)
                c_strokes = render_chart(
                    chart_obj,
                    bbox_mm=fl_box,
                    selector=fl_sel,
                    config=config,
                    block_id=fl_blk.block_id,
                    page_index=pbuf.page_index,
                    units_per_em=fl_upm,
                    baseline_u=fl_base_u,
                    render_mode=eff_mode,
                    missing_out=pbuf.missing_glyphs,
                )
                pbuf.strokes.extend(c_strokes)
                merge_counts(pbuf.fallback_counts, diff_counts(fb_fl_before, fl_sel.fallback_counts))
            pbuf.placed_blocks.append(
                PlacedBlockBox(
                    block_id=fl_blk.block_id,
                    block_type=fl_blk.type,
                    page_index=pbuf.page_index,
                    bbox_mm=fl_box,
                    label=f"{'图表' if fl_blk.type == 'chart' else '插图'} · {getattr(fl_blk, 'asset_name', None) or fl_blk.block_id}",
                    placement="float",
                    render_mode=eff_mode,
                )
            )

        field_regions = sorted(
            [
                r
                for r in config.regions
                if r.enabled and r.role == "field" and r.text.strip() and matches_page_scope(r.page_scope, pbuf.page_index)
            ],
            key=lambda r: (r.order, r.y_mm, r.x_mm),
        )
        field_strokes: list[EmittedStroke] = []
        for fr in field_regions:
            fs, f_fb = compose_field_region(
                fr,
                pbuf.page_index,
                p_rule,
                get_selector,
                config,
                missing_out=pbuf.missing_glyphs,
            )
            field_strokes.extend(fs)
            merge_counts(pbuf.fallback_counts, f_fb)

        page_fb_counts = count_missing_chars(pbuf.missing_glyphs)
        composed.append(
            finalize_page(
                pbuf.page_index,
                page_w,
                page_h,
                field_strokes + pbuf.strokes,
                page_fb_counts,
                applied_rule_label=pbuf.applied_rule_label,
                background_id=pbuf.background_id,
                background_opacity=pbuf.background_opacity,
                writer_id=pbuf.writer_id,
                placed_blocks=pbuf.placed_blocks,
                missing_glyphs=pbuf.missing_glyphs,
            )
        )
    return composed
