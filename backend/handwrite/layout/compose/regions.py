"""Independent positioned WritingRegion composition (`role=='field'`)."""

from __future__ import annotations

import math

from handwrite.api.schemas import LayoutConfig, MissingGlyphBox, PageRuleOverride, WritingRegion
from handwrite.docparse.docir import BreakInline, DocInline
from handwrite.docparse.pdf_parser import split_inline_math
from handwrite.layout.compose.rules import (
    SelectorGetter,
    compute_effective_line_pitch_mm,
    diff_counts,
)
from handwrite.layout.perturb import scope_rng
from handwrite.layout.shaper import (
    EmittedStroke,
    break_atoms_into_lines,
    emit_shaped_line,
    shape_inlines,
)


def compose_field_region(
    region: WritingRegion,
    page_index: int,
    page_rule: PageRuleOverride,
    get_selector: SelectorGetter,
    config: LayoutConfig,
    *,
    missing_out: list[MissingGlyphBox] | None = None,
) -> tuple[list[EmittedStroke], dict[str, int]]:
    """Compose an independent positioned `WritingRegion` (`role=='field'`)."""
    txt = region.text or ""
    if not region.enabled or not txt.strip():
        return [], {}

    selector, units_per_em, baseline_u, _ = get_selector(region.writer_id or page_rule.writer_id)
    fb_before = dict(selector.fallback_counts)

    perturb_cfg = (
        config.perturb.model_copy(update={"neatness": region.neatness})
        if region.neatness is not None
        else config.perturb
    )
    base_font = float(
        region.font_size_mm
        or page_rule.font_size_mm
        or config.text.font_size_mm
    )
    lspace = float(
        region.line_spacing
        if region.line_spacing is not None
        else (page_rule.line_spacing if page_rule.line_spacing is not None else config.text.line_spacing)
    )
    lspace_mm = (
        region.line_spacing_mm
        if region.line_spacing_mm is not None
        else (
            page_rule.line_spacing_mm
            if page_rule.line_spacing_mm is not None
            else config.text.line_spacing_mm
        )
    )
    cspace = float(
        region.char_spacing
        if region.char_spacing is not None
        else config.text.char_spacing
    )
    para_mm = float(
        region.paragraph_spacing_mm
        if region.paragraph_spacing_mm is not None
        else (
            page_rule.paragraph_spacing_mm
            if page_rule.paragraph_spacing_mm is not None
            else config.text.paragraph_spacing_mm
        )
    )
    char_sx = float(config.text.char_scale_x)
    char_sy = float(config.text.char_scale_y)

    rx = float(region.x_mm)
    ry = float(region.y_mm)
    rw = max(4.0, float(region.width_mm))
    rh = max(3.0, float(region.height_mm))

    lines_raw = txt.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    inlines: list[DocInline] = []
    if region.single_line:
        joined = " ".join(s.strip() for s in lines_raw if s.strip())
        inlines = split_inline_math(joined)
    else:
        for idx, sub_ln in enumerate(lines_raw):
            if idx > 0:
                inlines.append(BreakInline())
            if sub_ln:
                inlines.extend(split_inline_math(sub_ln))

    if not inlines:
        return [], {}

    block_id = f"region:{region.region_id}"

    use_font = base_font
    if region.single_line:
        rng0 = scope_rng(perturb_cfg.seed, "region_shape", page_index, region.region_id)
        atoms = shape_inlines(
            inlines,
            selector,
            font_size_mm=use_font,
            char_spacing=cspace,
            formula_scale=config.formula.scale,
            max_width_mm=1e6,
            perturb_cfg=perturb_cfg,
            rng=rng0,
            units_per_em=units_per_em,
            baseline_u=baseline_u,
            inner_row_spacing=config.formula.inner_row_spacing,
            char_scale_x=char_sx,
        )
        nat_w = sum(a.width_mm for a in atoms)
        if region.auto_fit:
            scale_w = (rw * 0.98) / nat_w if (nat_w > rw * 0.98 and nat_w > 1e-3) else 1.0
            eff_h_char = use_font * char_sy
            scale_h = (rh * 0.90) / eff_h_char if eff_h_char > rh * 0.90 else 1.0
            shrink = min(1.0, scale_w, scale_h)
            if shrink < 0.995:
                use_font = max(1.5, use_font * shrink)
                rng0 = scope_rng(perturb_cfg.seed, "region_shape", page_index, region.region_id)
                atoms = shape_inlines(
                    inlines,
                    selector,
                    font_size_mm=use_font,
                    char_spacing=cspace,
                    formula_scale=config.formula.scale,
                    max_width_mm=1e6,
                    perturb_cfg=perturb_cfg,
                    rng=rng0,
                    units_per_em=units_per_em,
                    baseline_u=baseline_u,
                    inner_row_spacing=config.formula.inner_row_spacing,
                    char_scale_x=char_sx,
                )
        lines = break_atoms_into_lines(atoms, line_width_mm=1e6, font_size_mm=use_font)
    else:
        lines = []
        for attempt in range(4):
            rng0 = scope_rng(perturb_cfg.seed, "region_shape", page_index, region.region_id)
            atoms = shape_inlines(
                inlines,
                selector,
                font_size_mm=use_font,
                char_spacing=cspace,
                formula_scale=config.formula.scale,
                max_width_mm=rw,
                perturb_cfg=perturb_cfg,
                rng=rng0,
                units_per_em=units_per_em,
                baseline_u=baseline_u,
                inner_row_spacing=config.formula.inner_row_spacing,
                char_scale_x=char_sx,
            )
            lines = break_atoms_into_lines(atoms, line_width_mm=rw, font_size_mm=use_font)
            line_pitch = compute_effective_line_pitch_mm(use_font, lspace, lspace_mm, char_sy)
            est_h = len(lines) * line_pitch
            if not region.auto_fit or est_h <= rh * 1.02 or attempt == 3:
                break
            ratio = max(0.52, math.sqrt((rh * 0.98) / max(1e-3, est_h)))
            next_font = max(1.5, use_font * ratio)
            if abs(next_font - use_font) < 0.05:
                break
            use_font = next_font

    if not lines:
        return [], diff_counts(fb_before, selector.fallback_counts)

    line_pitch = compute_effective_line_pitch_mm(use_font, lspace, lspace_mm, char_sy)
    line_hs: list[float] = []
    for li_idx, ln in enumerate(lines):
        if len(lines) == 1:
            line_hs.append(max(use_font * char_sy * 0.72, (ln.ascent_mm + ln.descent_mm) * char_sy))
        else:
            gap_extra = para_mm if (ln.is_last_line and li_idx < len(lines) - 1) else 0.0
            line_hs.append(max(0.8, line_pitch + gap_extra))
    total_h = sum(line_hs)

    if region.valign == "middle":
        start_y = ry + max(0.0, 0.5 * (rh - total_h))
    elif region.valign == "bottom":
        start_y = ry + max(0.0, rh - total_h)
    else:
        start_y = ry

    strokes: list[EmittedStroke] = []
    cur_y = start_y
    for li, (ln, lh) in enumerate(zip(lines, line_hs)):
        if li > 0 and cur_y + lh * 0.6 > ry + rh + 0.5:
            break
        asc = max(ln.ascent_mm, use_font * (baseline_u / max(1.0, units_per_em))) * char_sy
        baseline_y = cur_y + asc
        emitted = emit_shaped_line(
            ln,
            x0_mm=rx,
            baseline_y_mm=baseline_y,
            line_width_mm=rw,
            font_size_mm=use_font,
            char_spacing=cspace,
            align=region.align,
            perturb_cfg=perturb_cfg,
            seed=perturb_cfg.seed,
            scope_key=("region", page_index, region.region_id, li),
            block_id=block_id,
            kind="text",
            units_per_em=units_per_em,
            baseline_u=baseline_u,
            selector=selector,
            wave_mult=0.45 if region.single_line else 0.75,
            char_scale_x=char_sx,
            char_scale_y=char_sy,
            missing_out=missing_out,
            page_index=page_index,
            source_kind="region",
        )
        strokes.extend(emitted)
        cur_y += lh

    if missing_out is not None:
        reg_counts: dict[str, int] = {}
        for m in missing_out:
            if m.block_id == block_id:
                reg_counts[m.char] = reg_counts.get(m.char, 0) + 1
        return strokes, reg_counts
    return strokes, diff_counts(fb_before, selector.fallback_counts)
