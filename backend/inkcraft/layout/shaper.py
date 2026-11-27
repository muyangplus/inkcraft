"""CJK kinsoku line-breaking shaper, inline-math integration, text label emitter, and ruled grid."""

from __future__ import annotations

from dataclasses import dataclass, field
import unicodedata

import numpy as np

from inkcraft.api.schemas import (
    LayoutConfig,
    MarginsMM,
    MissingGlyphBox,
    PerturbConfig,
    RuledConfig,
    StrokeKind,
)
from inkcraft.docparse.docir import BreakInline, DocInline, MathInline, TextInline
from inkcraft.layout.math_typesetter import (
    MathLayout,
    translate_math_missing,
    translate_math_strokes,
    typeset_math,
)
from inkcraft.layout.perturb import (
    LineWaveState,
    connect_inter_glyph_strokes,
    hand_draw_polyline,
    sample_spacing_factor,
    scope_rng,
    transform_glyph_strokes,
)
from inkcraft.writers.selector import ResolvedGlyph, VariantSelector

# CJK Kinsoku Shori (避头尾禁则)
NO_LINE_START = frozenset("，。、；：？！）》」』】〉…—·%‰℃,.;:?!)]}’”")
NO_LINE_END = frozenset("（《「『【〈“‘([{")


@dataclass(slots=True)
class EmittedStroke:
    """Internal stroke emitted before final page indexing and statistics."""

    pts: np.ndarray  # shape=(N, 2), float64, page mm
    kind: StrokeKind
    block_id: str
    reversible: bool = False


def is_cjk_char(ch: str) -> bool:
    if not ch:
        return False
    cp = ord(ch[0])
    return (
        0x4E00 <= cp <= 0x9FFF
        or 0x3400 <= cp <= 0x4DBF
        or 0x3000 <= cp <= 0x303F
        or 0xFF00 <= cp <= 0xFFEF
        or 0x2000 <= cp <= 0x206F
    )


def _is_latin_word_char(ch: str) -> bool:
    if not ch:
        return False
    cp = ord(ch[0])
    return (cp < 128 and (ch.isalnum() or ch in {"_", "-", ".", "'"}))


@dataclass(slots=True)
class ShapedAtom:
    kind: str  # "glyph", "word", "space", "math", "break"
    text: str = ""
    glyphs: list[ResolvedGlyph] = field(default_factory=list)
    math: MathLayout | None = None
    math_scale: float = 1.0
    width_mm: float = 0.0
    ascent_mm: float = 0.0
    descent_mm: float = 0.0
    is_cjk: bool = False
    bold: bool = False
    italic: bool = False
    inline_index: int | None = None


@dataclass(slots=True)
class ShapedLine:
    atoms: list[ShapedAtom]
    natural_width_mm: float
    ascent_mm: float
    descent_mm: float
    indent_mm: float = 0.0
    is_last_line: bool = False


def _measure_glyph_advance_mm(
    glyph: ResolvedGlyph,
    *,
    font_size_mm: float,
    char_spacing: float,
    units_per_em: float,
    grid_pitch_mm: float | None = None,
    char_scale_x: float = 1.0,
) -> float:
    if glyph.advance_u <= 0:
        return 0.0
    if grid_pitch_mm is not None and is_cjk_char(glyph.char):
        return grid_pitch_mm
    base_mm = (glyph.advance_u / max(1.0, units_per_em)) * font_size_mm * float(char_scale_x)
    if glyph.char in {" ", "\u3000"}:
        return base_mm
    return max(0.2 * font_size_mm, base_mm * (1.0 + char_spacing))


def shape_inlines(
    inlines: list[DocInline],
    selector: VariantSelector,
    *,
    font_size_mm: float,
    char_spacing: float,
    formula_scale: float,
    max_width_mm: float,
    perturb_cfg: PerturbConfig,
    rng: np.random.Generator,
    units_per_em: float = 1000.0,
    baseline_u: float = 800.0,
    grid_pitch_mm: float | None = None,
    inner_row_spacing: float = -0.04,
    char_scale_x: float = 1.0,
) -> list[ShapedAtom]:
    """Convert `DocInline` stream into atomic `ShapedAtom`s (single CJK glyphs, Latin words, MathBoxes)."""
    atoms: list[ShapedAtom] = []
    ascent_default = font_size_mm * (baseline_u / max(1.0, units_per_em))
    descent_default = font_size_mm * (1.0 - baseline_u / max(1.0, units_per_em))

    for inl_idx, inl in enumerate(inlines):
        if isinstance(inl, BreakInline):
            atoms.append(ShapedAtom(kind="break"))
            continue

        if isinstance(inl, MathInline):
            ml = typeset_math(
                inl.latex,
                selector,
                font_size_mm=font_size_mm,
                formula_scale=formula_scale,
                inner_row_spacing=inner_row_spacing,
                display=False,
                perturb_cfg=perturb_cfg,
                rng=rng,
                units_per_em=units_per_em,
                baseline_u=baseline_u,
            )
            m_scale = 1.0
            if ml.width_mm > max_width_mm * 0.96 and ml.width_mm > 1e-3:
                m_scale = max(0.65, (max_width_mm * 0.96) / ml.width_mm)
            atoms.append(
                ShapedAtom(
                    kind="math",
                    text=inl.latex,
                    math=ml,
                    math_scale=m_scale,
                    width_mm=ml.width_mm * m_scale,
                    ascent_mm=max(ascent_default, ml.height_mm * m_scale),
                    descent_mm=max(descent_default, ml.depth_mm * m_scale),
                    inline_index=inl_idx,
                )
            )
            continue

        if isinstance(inl, TextInline):
            txt = inl.text or ""
            i = 0
            n = len(txt)
            while i < n:
                ch = txt[i]
                if ch == "\n":
                    atoms.append(ShapedAtom(kind="break"))
                    i += 1
                    continue
                if ch == "\r":
                    i += 1
                    continue
                if ch in {" ", "\t"}:
                    g = selector.select(" ", rng)
                    w = (g.advance_u / units_per_em) * font_size_mm if g else 0.35 * font_size_mm
                    atoms.append(
                        ShapedAtom(
                            kind="space",
                            text=" ",
                            width_mm=w,
                            ascent_mm=ascent_default,
                            descent_mm=descent_default,
                        )
                    )
                    i += 1
                    continue

                # Keep contiguous Latin/numeric tokens together unless longer than line width
                if _is_latin_word_char(ch):
                    j = i + 1
                    while j < n and _is_latin_word_char(txt[j]):
                        j += 1
                    word = txt[i:j]
                    word_glyphs: list[ResolvedGlyph] = []
                    word_w = 0.0
                    prev_ch = ""
                    for wch in word:
                        g = selector.select(wch, rng)
                        if g is None:
                            continue
                        kern_mm = (
                            (selector.kerning(prev_ch, wch) / units_per_em) * font_size_mm
                            if prev_ch
                            else 0.0
                        )
                        word_glyphs.append(g)
                        word_w += _measure_glyph_advance_mm(
                            g,
                            font_size_mm=font_size_mm,
                            char_spacing=char_spacing,
                            units_per_em=units_per_em,
                            grid_pitch_mm=None,
                            char_scale_x=char_scale_x,
                        ) + kern_mm
                        prev_ch = wch

                    # If single token exceeds line width, split into individual glyphs
                    if word_w > max_width_mm * 0.92 and len(word_glyphs) > 1:
                        for g in word_glyphs:
                            gw = _measure_glyph_advance_mm(
                                g,
                                font_size_mm=font_size_mm,
                                char_spacing=char_spacing,
                                units_per_em=units_per_em,
                                char_scale_x=char_scale_x,
                            )
                            atoms.append(
                                ShapedAtom(
                                    kind="glyph",
                                    text=g.char,
                                    glyphs=[g],
                                    width_mm=gw,
                                    ascent_mm=ascent_default,
                                    descent_mm=descent_default,
                                    is_cjk=False,
                                    bold=inl.bold,
                                    italic=inl.italic,
                                )
                            )
                    elif word_glyphs:
                        atoms.append(
                            ShapedAtom(
                                kind="word",
                                text=word,
                                glyphs=word_glyphs,
                                width_mm=word_w,
                                ascent_mm=ascent_default,
                                descent_mm=descent_default,
                                is_cjk=False,
                                bold=inl.bold,
                                italic=inl.italic,
                            )
                        )
                    i = j
                    continue

                # Single CJK or punctuation glyph
                g = selector.select(ch, rng)
                if g is not None:
                    gw = _measure_glyph_advance_mm(
                        g,
                        font_size_mm=font_size_mm,
                        char_spacing=char_spacing,
                        units_per_em=units_per_em,
                        grid_pitch_mm=grid_pitch_mm,
                        char_scale_x=char_scale_x,
                    )
                    atoms.append(
                        ShapedAtom(
                            kind="glyph",
                            text=ch,
                            glyphs=[g],
                            width_mm=gw,
                            ascent_mm=ascent_default,
                            descent_mm=descent_default,
                            is_cjk=is_cjk_char(ch),
                            bold=inl.bold,
                            italic=inl.italic,
                        )
                    )
                i += 1

    return atoms


def break_atoms_into_lines(
    atoms: list[ShapedAtom],
    *,
    line_width_mm: float,
    first_line_indent_mm: float = 0.0,
    font_size_mm: float = 6.0,
) -> list[ShapedLine]:
    """Greedy + CJK kinsoku (避头尾禁则) line breaker."""
    if not atoms:
        return []

    lines: list[ShapedLine] = []
    cur: list[ShapedAtom] = []
    cur_w = 0.0
    is_first = True

    def _avail() -> float:
        return max(font_size_mm * 2.0, line_width_mm - (first_line_indent_mm if is_first else 0.0))

    def _flush(*, is_hard_end: bool = False) -> None:
        nonlocal cur, cur_w, is_first
        # Strip trailing spaces
        while cur and cur[-1].kind == "space":
            popped = cur.pop()
            cur_w -= popped.width_mm
        if cur:
            asc = max(a.ascent_mm for a in cur)
            desc = max(a.descent_mm for a in cur)
            lines.append(
                ShapedLine(
                    atoms=cur,
                    natural_width_mm=max(0.0, cur_w),
                    ascent_mm=asc,
                    descent_mm=desc,
                    indent_mm=first_line_indent_mm if is_first else 0.0,
                    is_last_line=is_hard_end,
                )
            )
            is_first = False
        cur = []
        cur_w = 0.0

    i = 0
    n = len(atoms)
    while i < n:
        atom = atoms[i]
        if atom.kind == "break":
            _flush(is_hard_end=True)
            i += 1
            continue

        if not cur and atom.kind == "space":
            i += 1
            continue

        avail = _avail()
        if not cur or (cur_w + atom.width_mm) <= avail:
            cur.append(atom)
            cur_w += atom.width_mm
            i += 1
            continue

        # Overflow: apply CJK kinsoku rules
        # Case 1: Incoming atom cannot start a line (NO_LINE_START, e.g. ，。！？)
        if atom.kind == "glyph" and atom.text in NO_LINE_START:
            # Try squeezing into current line if overflow <= 15% of line width
            if (cur_w + atom.width_mm) <= avail * 1.15:
                cur.append(atom)
                cur_w += atom.width_mm
                _flush(is_hard_end=False)
                i += 1
                continue
            # Otherwise push previous breakable atom onto next line with it
            if len(cur) > 1:
                carried = cur.pop()
                cur_w -= carried.width_mm
                _flush(is_hard_end=False)
                cur = [carried, atom]
                cur_w = carried.width_mm + atom.width_mm
                i += 1
                continue

        # Case 2: Last atom on current line cannot end a line (NO_LINE_END, e.g. （《“)
        carried_open: ShapedAtom | None = None
        if len(cur) > 1 and cur[-1].kind == "glyph" and cur[-1].text in NO_LINE_END:
            carried_open = cur.pop()
            cur_w -= carried_open.width_mm

        _flush(is_hard_end=False)
        if carried_open is not None:
            cur.append(carried_open)
            cur_w += carried_open.width_mm
        if atom.kind != "space":
            cur.append(atom)
            cur_w += atom.width_mm
        i += 1

    _flush(is_hard_end=True)
    if lines:
        lines[-1].is_last_line = True
    return lines


def _line_flat_chars(line: ShapedLine) -> list[tuple[int, int, str]]:
    """Build flat `(atom_idx, glyph_idx, char)` index list for ±4 context snippets."""
    out: list[tuple[int, int, str]] = []
    for ai, atom in enumerate(line.atoms):
        if atom.kind == "space":
            out.append((ai, 0, " "))
        elif atom.kind == "math":
            out.append((ai, 0, atom.text or "$公式$"))
        else:
            for gi, g in enumerate(atom.glyphs):
                out.append((ai, gi, g.char))
    return out


def _build_missing_context(
    flat: list[tuple[int, int, str]],
    target_atom_idx: int,
    target_glyph_idx: int,
    target_ch: str,
) -> str:
    pos = -1
    for idx, (ai, gi, _) in enumerate(flat):
        if ai == target_atom_idx and gi == target_glyph_idx:
            pos = idx
            break
    if pos < 0:
        return f"【{target_ch}】"
    lo = max(0, pos - 4)
    hi = min(len(flat), pos + 5)
    left = "".join(item[2] for item in flat[lo:pos])
    right = "".join(item[2] for item in flat[pos + 1 : hi])
    return f"{left}【{target_ch}】{right}"


def emit_shaped_line(
    line: ShapedLine,
    *,
    x0_mm: float,
    baseline_y_mm: float,
    line_width_mm: float,
    font_size_mm: float,
    char_spacing: float,
    align: str,
    perturb_cfg: PerturbConfig,
    seed: int,
    scope_key: tuple[object, ...],
    block_id: str,
    kind: StrokeKind = "text",
    units_per_em: float = 1000.0,
    baseline_u: float = 800.0,
    selector: VariantSelector | None = None,
    wave_mult: float = 1.0,
    grid_pitch_mm: float | None = None,
    char_scale_x: float = 1.0,
    char_scale_y: float = 1.0,
    math_boxes_out: list[tuple[int | None, str, list[float]]] | None = None,
    missing_out: list[MissingGlyphBox] | None = None,
    page_index: int = 0,
    source_kind: str | None = None,
) -> list[EmittedStroke]:
    """Emit all strokes for a `ShapedLine` with alignment, perturbation, and spacing-jitter recovery."""
    if not line.atoms:
        return []

    line_rng = scope_rng(seed, "line", *scope_key)
    line_state = LineWaveState.create(perturb_cfg, line_rng)

    avail_w = max(1.0, line_width_mm - line.indent_mm)
    # Squeeze factor if line slightly overflowed (e.g. kinsoku squeeze or tight overlay)
    squeeze = 1.0
    if line.natural_width_mm > avail_w and line.natural_width_mm > 1e-3:
        squeeze = max(0.75, avail_w / line.natural_width_mm)

    eff_w = line.natural_width_mm * squeeze
    start_x = x0_mm + line.indent_mm
    extra_gap = 0.0

    if align == "center":
        start_x = x0_mm + max(0.0, 0.5 * (line_width_mm - eff_w))
    elif align == "right":
        start_x = x0_mm + max(0.0, line_width_mm - eff_w)
    elif align == "justify" and not line.is_last_line and len(line.atoms) > 1 and grid_pitch_mm is None:
        slack = avail_w - eff_w
        if 0.0 < slack < avail_w * 0.35:
            extra_gap = slack / (len(line.atoms) - 1)

    strokes: list[EmittedStroke] = []
    pending_text_groups: list[list[np.ndarray]] = []
    cursor_x = start_x
    glyph_seq = 0
    drift_mm = 0.0
    flat_ctx = _line_flat_chars(line) if missing_out is not None else []
    eff_policy = (
        selector.fallback_policy if selector is not None else "blank"
    )
    eff_source = source_kind or (kind if kind in {"text", "formula", "table", "chart"} else "text")

    def _flush_text_groups() -> None:
        if not pending_text_groups:
            return
        join_rng = scope_rng(seed, "inter_glyph", *scope_key, glyph_seq)
        merged = connect_inter_glyph_strokes(
            pending_text_groups,
            font_size_mm=font_size_mm * squeeze,
            neatness=perturb_cfg.neatness,
            rng=join_rng,
        )
        for st in merged:
            strokes.append(EmittedStroke(pts=st, kind=kind, block_id=block_id, reversible=False))
        pending_text_groups.clear()

    for atom_idx, atom in enumerate(line.atoms):
        if atom.kind == "space":
            _flush_text_groups()
            cursor_x += atom.width_mm * squeeze + extra_gap
            continue

        if atom.kind == "math" and atom.math is not None:
            _flush_text_groups()
            eff_scale = atom.math_scale * squeeze
            m_strokes = translate_math_strokes(
                atom.math,
                cursor_x,
                baseline_y_mm,
                scale=eff_scale,
            )
            for st in m_strokes:
                strokes.append(EmittedStroke(pts=st, kind="formula", block_id=block_id, reversible=False))
            if missing_out is not None:
                for m_ch, m_bb in translate_math_missing(
                    atom.math, cursor_x, baseline_y_mm, scale=eff_scale
                ):
                    missing_out.append(
                        MissingGlyphBox(
                            id="",
                            char=m_ch,
                            unicode_hex=f"U+{ord(m_ch[0]):04X}",
                            page_index=page_index,
                            block_id=block_id,
                            bbox_mm=m_bb,
                            context=f"${atom.text or m_ch}$",
                            source="formula",
                            policy=eff_policy,  # type: ignore[arg-type]
                        )
                    )
            if math_boxes_out is not None:
                mw = atom.math.width_mm * eff_scale
                my0 = baseline_y_mm - atom.math.height_mm * eff_scale
                my1 = baseline_y_mm + atom.math.depth_mm * eff_scale
                math_boxes_out.append(
                    (
                        atom.inline_index,
                        atom.text,
                        [round(cursor_x, 2), round(my0, 2), round(cursor_x + mw, 2), round(my1, 2)],
                    )
                )
            cursor_x += atom.width_mm * squeeze + extra_gap
            continue

        # Emit glyphs for "glyph" or "word"
        prev_ch = ""
        for g_idx, g in enumerate(atom.glyphs):
            g_rng = scope_rng(seed, "glyph", *scope_key, glyph_seq)
            glyph_seq += 1

            kern_mm = (
                (selector.kerning(prev_ch, g.char) / units_per_em) * font_size_mm * squeeze
                if (selector is not None and prev_ch)
                else 0.0
            )
            cursor_x += kern_mm

            nom_adv = _measure_glyph_advance_mm(
                g,
                font_size_mm=font_size_mm,
                char_spacing=char_spacing,
                units_per_em=units_per_em,
                grid_pitch_mm=grid_pitch_mm,
                char_scale_x=char_scale_x,
            ) * squeeze

            # Apply spacing jitter with gentle drift recovery so line ends stay aligned
            jitter_factor = sample_spacing_factor(
                perturb_cfg, g_rng, mult=0.35 if grid_pitch_mm is not None else 1.0
            )
            jitter_delta = nom_adv * (jitter_factor - 1.0) - 0.25 * drift_mm
            drift_mm += jitter_delta
            if g.advance_u <= 0:
                actual_adv = 0.0
            else:
                actual_adv = max(0.2 * font_size_mm, nom_adv + jitter_delta)

            # Center CJK glyph inside square grid cell if grid ruled mode is active
            draw_x = cursor_x
            if grid_pitch_mm is not None and is_cjk_char(g.char):
                glyph_w_mm = (g.advance_u / units_per_em) * font_size_mm * char_scale_x
                draw_x = cursor_x + max(0.0, 0.5 * (grid_pitch_mm - glyph_w_mm))

            # Record exact physical bounding box for every missing/fallback glyph across all fallback policies
            if missing_out is not None and g.is_fallback and g.char and not g.char.isspace():
                box_w = (
                    max(2.2, (g.advance_u / max(1.0, units_per_em)) * font_size_mm * squeeze * char_scale_x)
                    if g.advance_u > 0
                    else max(2.0, font_size_mm * 0.45)
                )
                asc_ratio = float(baseline_u) / max(1.0, float(units_per_em))
                desc_ratio = max(0.16, 1.0 - asc_ratio)
                eff_h = font_size_mm * squeeze * char_scale_y
                my0 = baseline_y_mm - eff_h * asc_ratio
                my1 = baseline_y_mm + eff_h * desc_ratio
                missing_out.append(
                    MissingGlyphBox(
                        id="",
                        char=g.char[0],
                        unicode_hex=f"U+{ord(g.char[0]):04X}",
                        page_index=page_index,
                        block_id=block_id,
                        bbox_mm=[
                            round(draw_x, 2),
                            round(my0, 2),
                            round(draw_x + box_w, 2),
                            round(my1, 2),
                        ],
                        context=_build_missing_context(flat_ctx, atom_idx, g_idx, g.char[0]),
                        source=eff_source,  # type: ignore[arg-type]
                        policy=eff_policy,  # type: ignore[arg-type]
                    )
                )

            # Blank-space missing glyph, skipped missing glyph, or whitespace glyph: leave gap without ligature bridge
            if not g.strokes:
                _flush_text_groups()
                cursor_x += actual_adv
                prev_ch = ""
                continue

            placed = transform_glyph_strokes(
                g.strokes,
                origin_x_mm=draw_x,
                baseline_y_mm=baseline_y_mm,
                font_size_mm=font_size_mm * squeeze,
                units_per_em=units_per_em,
                baseline_u=baseline_u,
                advance_u=float(g.advance_u),
                cfg=perturb_cfg,
                rng=g_rng,
                line_state=line_state,
                wave_mult=wave_mult,
                extra_italic_deg=6.0 if atom.italic else 0.0,
                char_scale_x=char_scale_x,
                char_scale_y=char_scale_y,
            )
            if placed:
                pending_text_groups.append(placed)

            cursor_x += actual_adv
            prev_ch = g.char

        if atom_idx < len(line.atoms) - 1:
            cursor_x += extra_gap

    _flush_text_groups()
    return strokes


def emit_text_label(
    text: str,
    selector: VariantSelector,
    *,
    x_mm: float,
    baseline_y_mm: float,
    font_size_mm: float,
    align: str = "left",
    max_width_mm: float | None = None,
    perturb_cfg: PerturbConfig | None = None,
    rng: np.random.Generator | None = None,
    block_id: str = "",
    kind: StrokeKind = "chart",
    units_per_em: float = 1000.0,
    baseline_u: float = 800.0,
    missing_out: list[MissingGlyphBox] | None = None,
    page_index: int = 0,
) -> list[EmittedStroke]:
    """Render a compact single-line label (chart title, ticks, legend) in the active writer's `.hwfont`."""
    if not text:
        return []
    cfg = perturb_cfg or PerturbConfig()
    gen = rng if rng is not None else np.random.default_rng(cfg.seed)

    glyphs: list[ResolvedGlyph] = []
    widths: list[float] = []
    for ch in text:
        g = selector.select(ch, gen)
        if g is None:
            continue
        w = (g.advance_u / units_per_em) * font_size_mm * 1.04 if g.advance_u > 0 else 0.0
        glyphs.append(g)
        widths.append(w)

    if not glyphs:
        return []

    total_w = sum(widths)
    scale = 1.0
    if max_width_mm is not None and total_w > max_width_mm and total_w > 1e-3:
        scale = max(0.55, max_width_mm / total_w)
        total_w *= scale

    if align == "center":
        cx = x_mm - 0.5 * total_w
    elif align == "right":
        cx = x_mm - total_w
    else:
        cx = x_mm

    out: list[EmittedStroke] = []
    asc_ratio = float(baseline_u) / max(1.0, float(units_per_em))
    desc_ratio = max(0.16, 1.0 - asc_ratio)
    eff_policy = selector.fallback_policy
    for gi, (g, w) in enumerate(zip(glyphs, widths)):
        if missing_out is not None and g.is_fallback and g.char and not g.char.isspace():
            box_w = max(2.0, w * scale) if w > 0 else max(1.8, font_size_mm * scale * 0.45)
            my0 = baseline_y_mm - font_size_mm * scale * asc_ratio
            my1 = baseline_y_mm + font_size_mm * scale * desc_ratio
            lo = max(0, gi - 4)
            hi = min(len(text), gi + 5)
            ctx_snip = f"{text[lo:gi]}【{g.char[0]}】{text[gi + 1 : hi]}"
            missing_out.append(
                MissingGlyphBox(
                    id="",
                    char=g.char[0],
                    unicode_hex=f"U+{ord(g.char[0]):04X}",
                    page_index=page_index,
                    block_id=block_id,
                    bbox_mm=[round(cx, 2), round(my0, 2), round(cx + box_w, 2), round(my1, 2)],
                    context=ctx_snip,
                    source="chart",
                    policy=eff_policy,  # type: ignore[arg-type]
                )
            )
        if not g.strokes:
            cx += w * scale
            continue
        placed = transform_glyph_strokes(
            g.strokes,
            origin_x_mm=cx,
            baseline_y_mm=baseline_y_mm,
            font_size_mm=font_size_mm * scale,
            units_per_em=units_per_em,
            baseline_u=baseline_u,
            advance_u=float(g.advance_u),
            cfg=cfg,
            rng=gen,
            line_state=None,
            scale_mult=0.4,
            wave_mult=0.0,
            slant_mult=0.5,
            rot_mult=0.5,
        )
        for st in placed:
            out.append(EmittedStroke(pts=st, kind=kind, block_id=block_id, reversible=False))
        cx += w * scale
    return out


def generate_ruled_strokes(
    page_w: float,
    page_h: float,
    margins: MarginsMM,
    ruled: RuledConfig,
    *,
    rng: np.random.Generator,
    hand_jitter_mm: float = 0.14,
) -> list[EmittedStroke]:
    """Generate optional hand-drawn ruled horizontal lines or square writing grid."""
    if not ruled.draw or ruled.style == "none":
        return []

    x0 = margins.left
    x1 = page_w - margins.right
    y0 = margins.top
    y1 = page_h - margins.bottom
    pitch = max(5.0, float(ruled.pitch_mm))

    strokes: list[EmittedStroke] = []
    y = y0 + pitch
    while y <= y1 + 1e-3:
        raw = np.array([[x0, y], [x1, y]], dtype=np.float64)
        pts = hand_draw_polyline(raw, hand_jitter_mm, rng, overshoot_mm=0.2, resample_step_mm=2.5)
        strokes.append(EmittedStroke(pts=pts, kind="rule", block_id="page-rule", reversible=True))
        y += pitch

    if ruled.style == "grid":
        # Top border line for grid
        top_raw = np.array([[x0, y0], [x1, y0]], dtype=np.float64)
        strokes.append(
            EmittedStroke(
                pts=hand_draw_polyline(top_raw, hand_jitter_mm, rng, overshoot_mm=0.2, resample_step_mm=2.5),
                kind="rule",
                block_id="page-rule",
                reversible=True,
            )
        )
        bottom_y = y - pitch
        if bottom_y > y0:
            x = x0
            while x <= x1 + 1e-3:
                raw = np.array([[x, y0], [x, bottom_y]], dtype=np.float64)
                pts = hand_draw_polyline(raw, hand_jitter_mm, rng, overshoot_mm=0.2, resample_step_mm=2.5)
                strokes.append(EmittedStroke(pts=pts, kind="rule", block_id="page-rule", reversible=True))
                x += pitch

    return strokes
