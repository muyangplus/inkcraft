"""LaTeX subset lexer, recursive-descent parser, and TeX box-and-glue single-line typesetter."""

from __future__ import annotations

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
    Token,
    lex_latex,
)
from handwrite.layout.math_box import (
    MathBox,
    MathBoxTypesetter,
    MathLayout,
)
from handwrite.layout.math_parser import _Parser, parse_latex
from handwrite.layout.math_symbols import (
    ACCENT_COMMANDS,
    BIG_OP_COMMANDS,
    FUNC_COMMANDS,
    GREEK_AND_SYMBOLS,
    IGNORED_SIZING_CMDS,
    SPACE_COMMANDS,
    STYLE_SCALE,
    AtomKind,
    MathStyle,
)
from handwrite.layout.perturb import hand_draw_polyline
from handwrite.writers.selector import VariantSelector

_STYLE_SCALE = STYLE_SCALE
_Typesetter = MathBoxTypesetter
parse_latex_to_ast = parse_latex


def _is_compact_inline_chemical_or_script(node: MathNode) -> bool:
    """Return True for compact inline scripted notations (e.g. `Al2(SO4)3`, `FeCl3`, `V0`)."""
    has_script = False

    def _walk(cur: MathNode) -> bool:
        nonlocal has_script
        if isinstance(cur, (FracNode, BigOpNode, MatrixNode, SqrtNode)):
            return False
        if isinstance(cur, CharNode):
            if cur.kind in {"rel", "bin"} or cur.char in "=+-<>≤≥≠≈×÷":
                return False
            return True
        if isinstance(cur, ScriptNode):
            has_script = True
            return (
                _walk(cur.base)
                and (cur.sub is None or _walk(cur.sub))
                and (cur.sup is None or _walk(cur.sup))
            )
        if isinstance(cur, RowNode):
            return all(_walk(item) for item in cur.items)
        if isinstance(cur, DelimitedNode):
            return _walk(cur.body)
        if isinstance(cur, AccentNode):
            return _walk(cur.body)
        return True

    return _walk(node) and has_script


def typeset_math(
    latex: str,
    selector: VariantSelector,
    *,
    font_size_mm: float,
    formula_scale: float = 0.95,
    inner_row_spacing: float = -0.04,
    display: bool = False,
    perturb_cfg: PerturbConfig | None = None,
    rng: np.random.Generator | None = None,
    units_per_em: float = 1000.0,
    baseline_u: float = 800.0,
) -> MathLayout:
    """Parse and typeset a LaTeX expression into single-line strokes in mm (baseline at y=0)."""
    cfg = perturb_cfg or PerturbConfig()
    gen = rng if rng is not None else np.random.default_rng(cfg.seed)
    em_mm = max(2.0, float(font_size_mm) * float(formula_scale))

    ast = parse_latex(latex)
    ts = MathBoxTypesetter(
        selector=selector,
        perturb_cfg=cfg,
        rng=gen,
        units_per_em=units_per_em,
        baseline_u=baseline_u,
        inner_row_spacing=inner_row_spacing,
    )
    box = ts.layout(ast, "D" if display else "T")
    x_comp = 0.90 if (not display and _is_compact_inline_chemical_or_script(ast)) else 1.0

    mm_strokes: list[np.ndarray] = []
    for st in box.strokes:
        pts = st * em_mm
        if abs(x_comp - 1.0) > 1e-6 and len(pts) > 0:
            pts[:, 0] *= x_comp
        if len(pts) >= 2:
            seg_len = float(np.sum(np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))))
            if len(pts) <= 6 and seg_len > em_mm * 1.4:
                pts = hand_draw_polyline(
                    pts,
                    jitter_mm=min(0.12, em_mm * 0.018),
                    rng=gen,
                    overshoot_mm=0.08,
                    resample_step_mm=1.8,
                    simplify_tol_mm=0.05,
                )
            mm_strokes.append(pts)

    return MathLayout(
        width_mm=box.width * em_mm * x_comp,
        height_mm=box.height * em_mm,
        depth_mm=box.depth * em_mm,
        strokes=mm_strokes,
        missing=[
            (ch, x0 * em_mm * x_comp, y0 * em_mm, x1 * em_mm * x_comp, y1 * em_mm)
            for (ch, x0, y0, x1, y1) in box.missing
        ],
    )


def translate_math_strokes(
    layout: MathLayout,
    x_mm: float,
    baseline_y_mm: float,
    *,
    scale: float = 1.0,
) -> list[np.ndarray]:
    """Place a typeset `MathLayout` at `(x_mm, baseline_y_mm)` with optional uniform scaling."""
    offset = np.array([x_mm, baseline_y_mm], dtype=np.float64)
    if abs(scale - 1.0) < 1e-6:
        return [st + offset for st in layout.strokes]
    return [st * scale + offset for st in layout.strokes]


def translate_math_missing(
    layout: MathLayout,
    x_mm: float,
    baseline_y_mm: float,
    *,
    scale: float = 1.0,
) -> list[tuple[str, list[float]]]:
    """Translate relative math missing-glyph boxes into absolute page-mm coordinates."""
    if not layout.missing:
        return []
    out: list[tuple[str, list[float]]] = []
    for ch, mx0, my0, mx1, my1 in layout.missing:
        out.append(
            (
                ch,
                [
                    round(x_mm + mx0 * scale, 2),
                    round(baseline_y_mm + my0 * scale, 2),
                    round(x_mm + mx1 * scale, 2),
                    round(baseline_y_mm + my1 * scale, 2),
                ],
            )
        )
    return out


__all__ = [
    "ACCENT_COMMANDS",
    "AtomKind",
    "BIG_OP_COMMANDS",
    "AccentNode",
    "BigOpNode",
    "CharNode",
    "DelimitedNode",
    "FUNC_COMMANDS",
    "FracNode",
    "GREEK_AND_SYMBOLS",
    "IGNORED_SIZING_CMDS",
    "MathBox",
    "MathBoxTypesetter",
    "MathLayout",
    "MathNode",
    "MathStyle",
    "MatrixNode",
    "RowNode",
    "SPACE_COMMANDS",
    "STYLE_SCALE",
    "ScriptNode",
    "SpaceNode",
    "SqrtNode",
    "TextNode",
    "Token",
    "_Parser",
    "_STYLE_SCALE",
    "_Typesetter",
    "lex_latex",
    "parse_latex",
    "parse_latex_to_ast",
    "translate_math_missing",
    "translate_math_strokes",
    "typeset_math",
]
