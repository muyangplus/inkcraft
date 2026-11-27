"""TeX box-and-glue layout and stroke emission for parsed math ASTs."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from handwrite.api.schemas import PerturbConfig
from handwrite.layout.math_ast import (
    AccentNode,
    BigOpNode,
    CharNode,
    DelimitedNode,
    FracNode,
    MathNode,
    MatrixNode,
    RowNode,
    ScriptNode,
    SpaceNode,
    SqrtNode,
    TextNode,
)
from handwrite.layout.math_geom import (
    make_accent,
    make_big_operator,
    make_delimiter,
    make_fraction_bar,
    make_radical,
)
from handwrite.layout.math_symbols import STYLE_SCALE, AtomKind, MathStyle
from handwrite.layout.perturb import transform_glyph_strokes
from handwrite.writers.selector import VariantSelector


@dataclass(slots=True)
class MathBox:
    width: float
    height: float
    depth: float
    strokes: list[np.ndarray]
    kind: AtomKind = "ord"
    missing: list[tuple[str, float, float, float, float]] = field(default_factory=list)


@dataclass(slots=True)
class MathLayout:
    width_mm: float
    height_mm: float
    depth_mm: float
    strokes: list[np.ndarray]
    missing: list[tuple[str, float, float, float, float]] = field(default_factory=list)

    @property
    def total_height_mm(self) -> float:
        return self.height_mm + self.depth_mm


def _script_style(style: MathStyle) -> MathStyle:
    return "S" if style in {"D", "T"} else "SS"


def _frac_style(style: MathStyle) -> MathStyle:
    if style == "D":
        return "T"
    if style == "T":
        return "S"
    return "SS"


def _atom_space_em(prev_kind: AtomKind | None, next_kind: AtomKind, style: MathStyle) -> float:
    if prev_kind is None:
        return 0.0
    thin = 3.0 / 18.0
    med = 4.0 / 18.0
    thick = 5.0 / 18.0
    in_script = style in {"S", "SS"}
    if prev_kind == "rel" or next_kind == "rel":
        return 0.0 if in_script else thick
    if prev_kind == "bin" or next_kind == "bin":
        return 0.0 if in_script else med
    if prev_kind == "op" and next_kind in {"ord", "op", "inner"}:
        return thin
    if prev_kind == "punct":
        return 0.0 if in_script else thin
    if prev_kind == "close" and next_kind == "op":
        return thin
    return 0.0


def _shift_strokes(strokes: list[np.ndarray], dx: float, dy: float) -> list[np.ndarray]:
    if not strokes:
        return []
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return [s.copy() for s in strokes]
    offset = np.array([dx, dy], dtype=np.float64)
    return [s + offset for s in strokes]


def _scale_strokes(strokes: list[np.ndarray], s: float) -> list[np.ndarray]:
    if not strokes or abs(s - 1.0) < 1e-9:
        return [st.copy() for st in strokes]
    return [st * s for st in strokes]


def _shift_missing(
    items: list[tuple[str, float, float, float, float]], dx: float, dy: float
) -> list[tuple[str, float, float, float, float]]:
    if not items:
        return []
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return list(items)
    return [(ch, x0 + dx, y0 + dy, x1 + dx, y1 + dy) for (ch, x0, y0, x1, y1) in items]


def _scale_missing(
    items: list[tuple[str, float, float, float, float]], s: float
) -> list[tuple[str, float, float, float, float]]:
    if not items or abs(s - 1.0) < 1e-9:
        return list(items)
    return [(ch, x0 * s, y0 * s, x1 * s, y1 * s) for (ch, x0, y0, x1, y1) in items]


def _is_cjk_char_math(ch: str) -> bool:
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


class MathBoxTypesetter:
    AXIS_HEIGHT = 0.25
    NUM_GAP = 0.06
    DEN_GAP = 0.06
    FRAC_EXT = 0.08
    LIMITS_GAP = 0.05
    MATRIX_COL_GAP = 0.68
    MATRIX_ROW_GAP = 0.14

    def __init__(
        self,
        selector: VariantSelector,
        perturb_cfg: PerturbConfig,
        rng: np.random.Generator,
        units_per_em: float = 1000.0,
        baseline_u: float = 800.0,
        inner_row_spacing: float = -0.04,
    ) -> None:
        self.selector = selector
        self.perturb_cfg = perturb_cfg
        self.rng = rng
        self.units_per_em = units_per_em
        self.baseline_u = baseline_u
        self.inner_row_spacing = float(inner_row_spacing)
        self.num_gap = max(-0.08, self.NUM_GAP + self.inner_row_spacing * 0.45)
        self.den_gap = max(-0.08, self.DEN_GAP + self.inner_row_spacing * 0.45)
        self.limits_gap = max(-0.08, self.LIMITS_GAP + self.inner_row_spacing * 0.40)
        self.matrix_row_gap = max(-0.22, self.MATRIX_ROW_GAP + self.inner_row_spacing)

    def _emit_char_box(
        self,
        ch: str,
        style: MathStyle,
        kind: AtomKind,
        italic: bool,
        *,
        compact_ascii: bool = False,
    ) -> MathBox:
        scale = STYLE_SCALE[style]
        glyph = self.selector.select(ch, self.rng)
        if glyph is None:
            return MathBox(width=0.35 * scale, height=0.68 * scale, depth=0.0, strokes=[], kind=kind)

        adv_em = (glyph.advance_u / self.units_per_em) * scale
        em_strokes = transform_glyph_strokes(
            glyph.strokes,
            origin_x_mm=0.0,
            baseline_y_mm=0.0,
            font_size_mm=scale,
            units_per_em=self.units_per_em,
            baseline_u=self.baseline_u,
            advance_u=float(glyph.advance_u),
            cfg=self.perturb_cfg,
            rng=self.rng,
            line_state=None,
            scale_mult=0.5,
            wave_mult=0.0,
            slant_mult=0.4,
            rot_mult=0.5,
            extra_italic_deg=7.5 if italic else 0.0,
            allow_cursive=False,
        )

        height = 0.68 * scale
        depth = 0.05 * scale
        if em_strokes:
            all_y = np.concatenate([s[:, 1] for s in em_strokes])
            height = max(height * 0.55, float(-np.min(all_y)))
            depth = max(0.0, float(np.max(all_y)))

        w = max(0.18 * scale, adv_em)
        # Optical horizontal ink-tightening for Latin/digits/parens so formulas do not inherit oversized CJK bearings
        if em_strokes and ch and not ch.isspace() and not _is_cjk_char_math(ch):
            ink_min_x = min(float(np.min(s[:, 0])) for s in em_strokes)
            ink_max_x = max(float(np.max(s[:, 0])) for s in em_strokes)
            ink_w = max(0.0, ink_max_x - ink_min_x)
            if ch in "()[]":
                lsb, rsb, min_w = 0.032 * scale, 0.032 * scale, 0.14 * scale
            elif kind in {"bin", "rel"}:
                lsb, rsb, min_w = 0.045 * scale, 0.045 * scale, 0.22 * scale
            elif ord(ch[0]) < 128 and ch.isalnum():
                if style in {"S", "SS"} or compact_ascii:
                    lsb, rsb, min_w = 0.022 * scale, 0.028 * scale, 0.11 * scale
                else:
                    lsb, rsb, min_w = 0.032 * scale, 0.040 * scale, 0.13 * scale
            else:
                lsb, rsb, min_w = 0.035 * scale, 0.040 * scale, 0.16 * scale
            dx = lsb - ink_min_x
            if abs(dx) > 1e-6:
                em_strokes = _shift_strokes(em_strokes, dx, 0.0)
            w = max(min_w, ink_w + lsb + rsb)

        missing = (
            [(ch, 0.0, -height, max(w, 0.28 * scale), max(0.02 * scale, depth))]
            if glyph.is_fallback
            else []
        )
        return MathBox(width=w, height=height, depth=depth, strokes=em_strokes, kind=kind, missing=missing)

    def _emit_text_box(self, text: str, style: MathStyle, kind: AtomKind) -> MathBox:
        x = 0.0
        scale = STYLE_SCALE[style]
        is_pure_ascii = bool(text) and all(ord(c) < 128 for c in text)
        max_h = 0.68 * scale
        max_d = 0.0
        strokes: list[np.ndarray] = []
        missing: list[tuple[str, float, float, float, float]] = []
        prev_non_ws = False
        for ch in text:
            if prev_non_ws and is_pure_ascii and not ch.isspace():
                x = max(0.0, x - 0.015 * scale)
            cb = self._emit_char_box(
                ch, style, "ord", italic=False, compact_ascii=is_pure_ascii
            )
            strokes.extend(_shift_strokes(cb.strokes, x, 0.0))
            missing.extend(_shift_missing(cb.missing, x, 0.0))
            x += cb.width
            max_h = max(max_h, cb.height)
            max_d = max(max_d, cb.depth)
            prev_non_ws = not ch.isspace()
        return MathBox(width=x, height=max_h, depth=max_d, strokes=strokes, kind=kind, missing=missing)

    def layout(self, node: MathNode, style: MathStyle) -> MathBox:
        scale = STYLE_SCALE[style]

        if isinstance(node, CharNode):
            return self._emit_char_box(node.char, style, node.kind, node.italic)

        if isinstance(node, TextNode):
            return self._emit_text_box(node.text, style, node.kind)

        if isinstance(node, SpaceNode):
            return MathBox(width=node.width_em * scale, height=0.0, depth=0.0, strokes=[], kind="ord")

        if isinstance(node, RowNode):
            if not node.items:
                return MathBox(width=0.0, height=0.0, depth=0.0, strokes=[], kind="ord")
            x = 0.0
            max_h = 0.0
            max_d = 0.0
            strokes: list[np.ndarray] = []
            missing: list[tuple[str, float, float, float, float]] = []
            prev_kind: AtomKind | None = None
            last_kind: AtomKind = "ord"
            for child in node.items:
                cb = self.layout(child, style)
                eff_kind = cb.kind
                if eff_kind == "bin" and prev_kind in {None, "bin", "rel", "open", "punct", "op"}:
                    eff_kind = "ord"
                sp = _atom_space_em(prev_kind, eff_kind, style)
                x = max(0.0, x + sp)
                strokes.extend(_shift_strokes(cb.strokes, x, 0.0))
                missing.extend(_shift_missing(cb.missing, x, 0.0))
                x = max(0.0, x + cb.width)
                max_h = max(max_h, cb.height)
                max_d = max(max_d, cb.depth)
                prev_kind = eff_kind
                last_kind = eff_kind
            return MathBox(width=max(0.0, x), height=max_h, depth=max_d, strokes=strokes, kind=last_kind, missing=missing)

        if isinstance(node, FracNode):
            sub_style = _frac_style(style)
            num_box = self.layout(node.num, sub_style)
            den_box = self.layout(node.den, sub_style)
            axis_y = self.AXIS_HEIGHT * scale
            ext = self.FRAC_EXT * scale
            bar_w = max(num_box.width, den_box.width) + 2.0 * ext

            num_dx = 0.5 * (bar_w - num_box.width)
            den_dx = 0.5 * (bar_w - den_box.width)
            num_base_y = -(axis_y + self.num_gap * scale + num_box.depth)
            den_base_y = -(axis_y - self.den_gap * scale - den_box.height)

            bar_strokes = make_fraction_bar(bar_w, axis_y, self.rng)
            strokes = (
                _shift_strokes(num_box.strokes, num_dx, num_base_y)
                + bar_strokes
                + _shift_strokes(den_box.strokes, den_dx, den_base_y)
            )
            missing = (
                _shift_missing(num_box.missing, num_dx, num_base_y)
                + _shift_missing(den_box.missing, den_dx, den_base_y)
            )
            height = max(0.0, -(num_base_y - num_box.height))
            depth = max(0.0, den_base_y + den_box.depth)
            return MathBox(width=bar_w + 0.08 * scale, height=height, depth=depth, strokes=strokes, kind="inner", missing=missing)

        if isinstance(node, SqrtNode):
            body = self.layout(node.body, style)
            rad_strokes_u, left_w_u, top_y_u = make_radical(
                body.width / scale,
                body.height / scale,
                body.depth / scale,
                gap_em=0.11,
            )
            rad_strokes = _scale_strokes(rad_strokes_u, scale)
            left_w = left_w_u * scale
            top_y = top_y_u * scale
            strokes = rad_strokes + _shift_strokes(body.strokes, left_w, 0.0)
            missing = _shift_missing(body.missing, left_w, 0.0)
            extra_left = 0.0
            total_h = max(body.height, -top_y)
            if node.degree is not None:
                deg_box = self.layout(node.degree, "SS")
                deg_x = max(0.0, left_w * 0.45 - deg_box.width)
                deg_y = top_y + 0.35 * (total_h + body.depth) - deg_box.depth
                if deg_box.width > left_w * 0.45:
                    extra_left = deg_box.width - left_w * 0.45
                    strokes = _shift_strokes(strokes, extra_left, 0.0)
                    missing = _shift_missing(missing, extra_left, 0.0)
                    deg_x = 0.0
                strokes.extend(_shift_strokes(deg_box.strokes, deg_x, deg_y))
                missing.extend(_shift_missing(deg_box.missing, deg_x, deg_y))
                total_h = max(total_h, -(deg_y - deg_box.height))
            total_w = extra_left + left_w + body.width + 0.12 * scale
            total_d = max(body.depth + 0.06 * scale, 0.14 * scale)
            return MathBox(width=total_w, height=total_h, depth=total_d, strokes=strokes, kind="ord", missing=missing)

        if isinstance(node, ScriptNode):
            base = self.layout(node.base, style)
            s_style = _script_style(style)
            sup_box = self.layout(node.sup, s_style) if node.sup is not None else None
            sub_box = self.layout(node.sub, s_style) if node.sub is not None else None

            strokes = list(base.strokes)
            missing = list(base.missing)
            gap_before = 0.014 if sup_box is not None else 0.004
            script_x = base.width + gap_before * scale
            extra_w = 0.0
            height = base.height
            depth = base.depth

            if sup_box is not None:
                sup_shift = max((0.46 if style == "D" else 0.40) * scale, base.height - 0.25 * scale)
                sup_y = -(sup_shift + sup_box.depth * 0.5)
                strokes.extend(_shift_strokes(sup_box.strokes, script_x, sup_y))
                missing.extend(_shift_missing(sup_box.missing, script_x, sup_y))
                extra_w = max(extra_w, sup_box.width)
                height = max(height, -(sup_y - sup_box.height))

            if sub_box is not None:
                sub_shift = 0.28 if sup_box is not None else 0.25
                sub_y = max(sub_shift * scale, base.depth + 0.08 * scale)
                strokes.extend(_shift_strokes(sub_box.strokes, script_x, sub_y))
                missing.extend(_shift_missing(sub_box.missing, script_x, sub_y))
                extra_w = max(extra_w, sub_box.width)
                depth = max(depth, sub_y + sub_box.depth)

            return MathBox(
                width=script_x + extra_w + 0.014 * scale,
                height=height,
                depth=depth,
                strokes=strokes,
                kind=base.kind,
                missing=missing,
            )

        if isinstance(node, BigOpNode):
            is_display = style == "D"
            if node.cmd == r"\lim":
                op_box = self._emit_text_box("lim", style, "op")
            else:
                op_strokes, op_w, op_h, op_d = make_big_operator(
                    node.cmd, is_display, self.AXIS_HEIGHT * scale
                )
                op_box = MathBox(width=op_w, height=op_h, depth=op_d, strokes=op_strokes, kind="op")

            s_style = _script_style(style)
            sub_box = self.layout(node.sub, s_style) if node.sub is not None else None
            sup_box = self.layout(node.sup, s_style) if node.sup is not None else None

            stack_limits = is_display and node.cmd in {r"\sum", r"\prod", r"\lim"}
            if stack_limits:
                total_w = max(
                    op_box.width,
                    sub_box.width if sub_box else 0.0,
                    sup_box.width if sup_box else 0.0,
                )
                strokes = _shift_strokes(op_box.strokes, 0.5 * (total_w - op_box.width), 0.0)
                missing = _shift_missing(op_box.missing, 0.5 * (total_w - op_box.width), 0.0)
                height = op_box.height
                depth = op_box.depth
                gap = self.limits_gap * scale
                if sup_box is not None:
                    sup_y = -(op_box.height + gap + sup_box.depth)
                    dx_sup = 0.5 * (total_w - sup_box.width)
                    strokes.extend(_shift_strokes(sup_box.strokes, dx_sup, sup_y))
                    missing.extend(_shift_missing(sup_box.missing, dx_sup, sup_y))
                    height = max(height, -(sup_y - sup_box.height))
                if sub_box is not None:
                    sub_y = op_box.depth + gap + sub_box.height
                    dx_sub = 0.5 * (total_w - sub_box.width)
                    strokes.extend(_shift_strokes(sub_box.strokes, dx_sub, sub_y))
                    missing.extend(_shift_missing(sub_box.missing, dx_sub, sub_y))
                    depth = max(depth, sub_y + sub_box.depth)
                return MathBox(width=total_w + 0.12 * scale, height=height, depth=depth, strokes=strokes, kind="op", missing=missing)

            strokes = list(op_box.strokes)
            missing = list(op_box.missing)
            sx = op_box.width + 0.06 * scale
            extra_w = 0.0
            height = op_box.height
            depth = op_box.depth
            if sup_box is not None:
                sup_y = -(op_box.height * 0.72)
                strokes.extend(_shift_strokes(sup_box.strokes, sx + 0.06 * scale, sup_y))
                missing.extend(_shift_missing(sup_box.missing, sx + 0.06 * scale, sup_y))
                extra_w = max(extra_w, sup_box.width + 0.06 * scale)
                height = max(height, -(sup_y - sup_box.height))
            if sub_box is not None:
                sub_y = op_box.depth * 0.78 + sub_box.height * 0.35
                strokes.extend(_shift_strokes(sub_box.strokes, sx, sub_y))
                missing.extend(_shift_missing(sub_box.missing, sx, sub_y))
                extra_w = max(extra_w, sub_box.width)
                depth = max(depth, sub_y + sub_box.depth)
            return MathBox(width=sx + extra_w + 0.10 * scale, height=height, depth=depth, strokes=strokes, kind="op", missing=missing)

        if isinstance(node, DelimitedNode):
            body = self.layout(node.body, style)
            h = max(0.75 * scale, body.height + 0.08 * scale)
            d = max(0.22 * scale, body.depth + 0.08 * scale)
            l_strokes_u, l_w_u = make_delimiter(node.left, h / scale, d / scale, self.AXIS_HEIGHT)
            r_strokes_u, r_w_u = make_delimiter(node.right, h / scale, d / scale, self.AXIS_HEIGHT)
            l_strokes = _scale_strokes(l_strokes_u, scale)
            r_strokes = _scale_strokes(r_strokes_u, scale)
            l_w = l_w_u * scale
            r_w = r_w_u * scale
            pad = 0.06 * scale
            strokes = (
                l_strokes
                + _shift_strokes(body.strokes, l_w + pad, 0.0)
                + _shift_strokes(r_strokes, l_w + pad + body.width + pad, 0.0)
            )
            missing = _shift_missing(body.missing, l_w + pad, 0.0)
            return MathBox(
                width=l_w + body.width + r_w + 2.0 * pad,
                height=h,
                depth=d,
                strokes=strokes,
                kind="inner",
                missing=missing,
            )

        if isinstance(node, MatrixNode):
            cell_style: MathStyle = "T" if style == "D" else style
            cell_boxes: list[list[MathBox]] = [
                [self.layout(cell, cell_style) for cell in row] for row in node.rows
            ]
            if not cell_boxes:
                return MathBox(width=0.0, height=0.0, depth=0.0, strokes=[], kind="inner")
            ncols = max(len(r) for r in cell_boxes)
            col_ws = [0.0] * ncols
            row_hs: list[float] = []
            row_ds: list[float] = []
            for row in cell_boxes:
                rh, rd = 0.65 * scale, 0.20 * scale
                for c_idx, cb in enumerate(row):
                    col_ws[c_idx] = max(col_ws[c_idx], cb.width)
                    rh = max(rh, cb.height)
                    rd = max(rd, cb.depth)
                row_hs.append(rh)
                row_ds.append(rd)

            col_gap = self.MATRIX_COL_GAP * scale
            row_gap = self.matrix_row_gap * scale
            total_h = sum(row_hs) + sum(row_ds) + row_gap * max(0, len(cell_boxes) - 1)
            total_w = sum(col_ws) + col_gap * max(0, ncols - 1)

            axis_y = -self.AXIS_HEIGHT * scale
            cur_y = axis_y - 0.5 * total_h
            strokes = []
            missing = []
            for r_idx, row in enumerate(cell_boxes):
                baseline_y = cur_y + row_hs[r_idx]
                cur_x = 0.0
                for c_idx, cb in enumerate(row):
                    if node.env in {"cases", "aligned"}:
                        dx = cur_x
                    else:
                        dx = cur_x + 0.5 * (col_ws[c_idx] - cb.width)
                    strokes.extend(_shift_strokes(cb.strokes, dx, baseline_y))
                    missing.extend(_shift_missing(cb.missing, dx, baseline_y))
                    cur_x += col_ws[c_idx] + col_gap
                cur_y += row_hs[r_idx] + row_ds[r_idx] + row_gap

            m_height = max(0.0, -(axis_y - 0.5 * total_h))
            m_depth = max(0.0, axis_y + 0.5 * total_h)

            env_delims: dict[str, tuple[str, str]] = {
                "pmatrix": ("(", ")"),
                "bmatrix": ("[", "]"),
                "Bmatrix": ("{", "}"),
                "vmatrix": ("|", "|"),
                "Vmatrix": (r"\|", r"\|"),
                "cases": ("{", "."),
            }
            if node.env in env_delims:
                ld, rd = env_delims[node.env]
                l_su, l_wu = make_delimiter(
                    ld, (m_height + 0.06 * scale) / scale, (m_depth + 0.06 * scale) / scale, self.AXIS_HEIGHT
                )
                r_su, r_wu = make_delimiter(
                    rd, (m_height + 0.06 * scale) / scale, (m_depth + 0.06 * scale) / scale, self.AXIS_HEIGHT
                )
                l_s = _scale_strokes(l_su, scale)
                r_s = _scale_strokes(r_su, scale)
                l_w = l_wu * scale
                r_w = r_wu * scale
                pad = 0.08 * scale
                strokes = (
                    l_s
                    + _shift_strokes(strokes, l_w + pad, 0.0)
                    + _shift_strokes(r_s, l_w + pad + total_w + pad, 0.0)
                )
                missing = _shift_missing(missing, l_w + pad, 0.0)
                total_w = l_w + total_w + r_w + 2.0 * pad

            return MathBox(width=total_w, height=m_height, depth=m_depth, strokes=strokes, kind="inner", missing=missing)

        if isinstance(node, AccentNode):
            body = self.layout(node.body, style)
            acc_strokes = _scale_strokes(
                make_accent(node.cmd, body.width / scale, -body.height / scale, body.depth / scale),
                scale,
            )
            extra_h = 0.16 * scale if node.cmd != r"\underline" else 0.0
            extra_d = 0.14 * scale if node.cmd == r"\underline" else 0.0
            return MathBox(
                width=body.width,
                height=body.height + extra_h,
                depth=body.depth + extra_d,
                strokes=body.strokes + acc_strokes,
                kind=body.kind,
                missing=list(body.missing),
            )

        return MathBox(width=0.0, height=0.0, depth=0.0, strokes=[], kind="ord")
