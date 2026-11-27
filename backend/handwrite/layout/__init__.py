"""Single-line handwriting layout, LaTeX math, table, chart, perturbation, and export engine."""

from handwrite.layout.chart_renderer import hatch_polygon, render_chart
from handwrite.layout.composer import compose_document
from handwrite.layout.export import export_page_f32, export_page_json
from handwrite.layout.math_typesetter import MathLayout, parse_latex, translate_math_strokes, typeset_math
from handwrite.layout.perturb import (
    LineWaveState,
    hand_draw_polyline,
    rdp_simplify,
    scope_rng,
    transform_glyph_strokes,
)
from handwrite.layout.shaper import (
    EmittedStroke,
    break_atoms_into_lines,
    emit_shaped_line,
    emit_text_label,
    generate_ruled_strokes,
    shape_inlines,
)
from handwrite.layout.table_renderer import render_table

__all__ = [
    "EmittedStroke",
    "LineWaveState",
    "MathLayout",
    "break_atoms_into_lines",
    "compose_document",
    "emit_shaped_line",
    "emit_text_label",
    "export_page_f32",
    "export_page_json",
    "generate_ruled_strokes",
    "hand_draw_polyline",
    "hatch_polygon",
    "parse_latex",
    "rdp_simplify",
    "render_chart",
    "render_table",
    "scope_rng",
    "shape_inlines",
    "transform_glyph_strokes",
    "translate_math_strokes",
    "typeset_math",
]
