"""Unit tests for docparse (DOCX/PDF/MinerU guard) and layout (Math/Chart/Perturb/Reflow/Overlay)."""

from __future__ import annotations

from pathlib import Path
import struct

import docx
from docx.oxml import parse_xml
import fitz
import numpy as np
import pytest

from handwrite.api.schemas import LayoutConfig, OverlayBlockOverride, Vec2, WritingRegion
from handwrite.docparse.docir import ChartData, ChartSeries, DocBlock, DocIR, DocPageInfo, DocSource
from handwrite.docparse.mineru_worker import MinerUUnavailableError, run_mineru_pipeline
from handwrite.docparse.service import build_demo_docir, parse_document, parse_plain_text
from handwrite.layout.chart_renderer import render_chart
from handwrite.layout.composer import compose_document
from handwrite.layout.export import export_page_f32, export_page_json
from handwrite.layout.math_typesetter import typeset_math
from handwrite.writers.selector import VariantSelector
from hwfont_sdk import HwFontReader

ROOT = Path(__file__).resolve().parents[2]
DEMO_FONT = ROOT / "fonts" / "lin_kaishu.hwfont"

import sys
if str(ROOT / "colab_builder") not in sys.path:
    sys.path.insert(0, str(ROOT / "colab_builder"))
from hwbuilder.model_sdt import LocalStyleTransferAugmentor
from hwbuilder.qc_export import chamfer_distance


def test_mineru_vllm_strictly_rejected(tmp_path: Path) -> None:
    dummy_pdf = tmp_path / "a.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    with pytest.raises(ValueError):
        run_mineru_pipeline(dummy_pdf, tmp_path / "out", backend="vlm-vllm-engine")


def test_docx_omml_and_table_parsing(tmp_path: Path) -> None:
    d = docx.Document()
    d.add_heading("实验报告测试", level=1)
    p = d.add_paragraph("正文与行内公式：")
    omml_xml = (
        '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
        '<m:f><m:num><m:r><m:t>a+b</m:t></m:r></m:num>'
        '<m:den><m:r><m:t>2</m:t></m:r></m:den></m:f>'
        "</m:oMath>"
    )
    p._p.append(parse_xml(omml_xml))
    tbl = d.add_table(rows=2, cols=2)
    tbl.cell(0, 0).text = "参数"
    tbl.cell(0, 1).text = "数值"
    tbl.cell(1, 0).text = "误差"
    tbl.cell(1, 1).text = "0.12"
    path = tmp_path / "sample.docx"
    d.save(str(path))

    ir = parse_document(path, "doc_docx", tmp_path / "out")
    assert ir.source.type == "docx"
    assert any(b.type == "heading" for b in ir.blocks)
    assert any(b.type == "table" and b.table and b.table.rows == 2 for b in ir.blocks)
    all_text = " ".join(b.plain_text() for b in ir.blocks)
    assert "\\frac" in all_text


def test_pdf_parsing_and_underlay_png(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Handwrite PDF Test E=mc^2", fontsize=14)
    page.draw_rect(fitz.Rect(72, 150, 220, 250), color=(0, 0, 0), width=1)
    doc.save(str(pdf_path))
    doc.close()

    out_dir = tmp_path / "pdf_out"
    ir = parse_document(pdf_path, "doc_pdf", out_dir)
    assert ir.source.type == "pdf"
    assert len(ir.pages) == 1
    assert (out_dir / "pages" / "0.png").is_file()
    assert len(ir.blocks) >= 1


def test_math_typesetter_15_expressions() -> None:
    formulas = [
        r"E = mc^2",
        r"\frac{a+b}{c-d}",
        r"\sqrt{x^2 + y^2}",
        r"\sqrt[3]{1 + \frac{x}{2}}",
        r"\int_{0}^{\infty} e^{-x^2} dx = \frac{\sqrt{\pi}}{2}",
        r"\sum_{i=1}^{n} i^2 = \frac{n(n+1)(2n+1)}{6}",
        r"\prod_{k=1}^{m} (1 + x_k)",
        r"\lim_{x \to 0} \frac{\sin x}{x} = 1",
        r"\alpha + \beta \leq \gamma \neq \delta \approx \omega",
        r"\left(\frac{x+1}{x-1}\right)^2",
        r"\begin{matrix} 1 & 2 \\ 3 & 4 \end{matrix}",
        r"\begin{cases} x^2 & x \geq 0 \\ -x & x < 0 \end{cases}",
        r"\partial f / \partial x + \Delta y = 0",
        r"a_{i,j}^{(k)} \pm \sigma",
        r"\text{速度} = \frac{s}{t}",
    ]
    with HwFontReader(DEMO_FONT) as reader:
        sel = VariantSelector(reader)
        rng = np.random.default_rng(42)
        for expr in formulas:
            layout = typeset_math(expr, sel, font_size_mm=6.5, display=True, rng=rng)
            assert layout.width_mm > 0.0, f"Empty width for {expr}"
            assert len(layout.strokes) >= 2, f"Too few strokes for {expr}"


def test_chart_renderer_all_hatch_styles() -> None:
    chart = ChartData(
        chart_type="bar",
        title="性能对比",
        categories=["A", "B", "C"],
        series=[ChartSeries(name="实测", values=[12.0, 28.0, 19.5])],
    )
    cfg = LayoutConfig()
    with HwFontReader(DEMO_FONT) as reader:
        sel = VariantSelector(reader)
        for style in ("parallel", "cross", "zigzag"):
            cfg.chart.hatch_style = style
            strokes = render_chart(
                chart,
                bbox_mm=[20.0, 40.0, 160.0, 120.0],
                selector=sel,
                config=cfg,
                block_id="p0-b1",
            )
            assert len(strokes) > 15
            assert any(s.reversible for s in strokes)


def test_compose_determinism_reflow_overlay_and_f32() -> None:
    doc = build_demo_docir("doc_det")
    cfg = LayoutConfig()
    cfg.perturb.seed = 2026

    with HwFontReader(DEMO_FONT) as reader:
        pages_a = compose_document(doc, reader, cfg)
        pages_b = compose_document(doc, reader, cfg)

    assert len(pages_a) >= 2
    f32_a, hdr_a = export_page_f32(pages_a[0])
    f32_b, _ = export_page_f32(pages_b[0])
    assert f32_a == f32_b  # 100% byte-identical determinism!
    assert len(f32_a) % 12 == 0
    assert int(hdr_a["X-Stroke-Count"]) == len(pages_a[0].strokes)

    # Verify flag semantics in f32 buffer
    triples = [struct.unpack_from("<fff", f32_a, i) for i in range(0, len(f32_a), 12)]
    flags = {t[2] for t in triples}
    assert flags.issubset({0.0, 1.0, 2.0})
    assert 0.0 in flags and 2.0 in flags

    # Verify JSON export matches Contract v1
    js = export_page_json("ly_test", pages_a[0])
    assert js["layout_id"] == "ly_test"
    assert js["stats"]["stroke_count"] == len(js["strokes"])

    # Verify Overlay mode with block override
    cfg_ov = LayoutConfig(mode="overlay")
    cfg_ov.overlay.offset_mm = Vec2(x=2.0, y=1.5)
    first_bid = doc.blocks[0].block_id
    cfg_ov.overlay.blocks[first_bid] = OverlayBlockOverride(enabled=False, nudge_mm=Vec2(x=0, y=0))
    with HwFontReader(DEMO_FONT) as reader:
        ov_pages = compose_document(doc, reader, cfg_ov)
    assert len(ov_pages) >= 1
    assert all(s.block_id != first_bid for s in ov_pages[0].strokes)


def test_text_row_left_to_right_and_negative_formula_spacing() -> None:
    doc = parse_plain_text(
        "排序与公式行距测试",
        "第一行文字严格从左到右依次书写。\n\n$$y = \\frac{a+b}{c+d}$$\n\n$$z = \\sum_{i=1}^{n} x_i$$\n\n最后一行正文紧跟公式下方。",
        "doc_order_formula",
    )

    cfg_loose = LayoutConfig()
    cfg_loose.formula.line_spacing_mm = 3.0
    cfg_loose.formula.inner_row_spacing = 0.25

    cfg_tight = LayoutConfig()
    cfg_tight.formula.line_spacing_mm = -3.0
    cfg_tight.formula.inner_row_spacing = -0.12

    with HwFontReader(DEMO_FONT) as reader:
        pages_loose = compose_document(doc, reader, cfg_loose)
        pages_tight = compose_document(doc, reader, cfg_tight)

    # Tight / negative formula spacing packs vertically much tighter than positive spacing
    h_loose = pages_loose[0].bbox[3] - pages_loose[0].bbox[1]
    h_tight = pages_tight[0].bbox[3] - pages_tight[0].bbox[1]
    assert h_tight < h_loose - 6.0

    # Verify text strokes proceed row-by-row top-to-bottom, and left-to-right within each row
    text_strokes = [s for s in pages_tight[0].strokes if s.kind == "text" and s.block_id == "p0-b1"]
    assert len(text_strokes) > 10
    xs = [float(np.mean(s.pts[0::2])) for s in text_strokes]
    ys = [float(np.mean(s.pts[1::2])) for s in text_strokes]
    # Check strokes on the first visual line are monotonically left-to-right (allowing intra-glyph stroke width <= 7mm)
    y_first = ys[0]
    first_line_xs = [x for x, y in zip(xs, ys) if abs(y - y_first) < 4.0]
    assert len(first_line_xs) >= 10
    assert first_line_xs[-1] > first_line_xs[0] + 40.0
    for a, b in zip(first_line_xs, first_line_xs[1:]):
        assert b >= a - 7.5  # never jumps backwards across characters on a line


def test_neatness_transitions_neat_to_cursive() -> None:
    doc = parse_plain_text(
        "工整度测试",
        "永和九年实验系统测试报告与数学分析结果对比。",
        "doc_neatness",
    )
    cfg_neat = LayoutConfig()
    cfg_neat.perturb.neatness = 0.96
    cfg_cursive = LayoutConfig()
    cfg_cursive.perturb.neatness = 0.08

    with HwFontReader(DEMO_FONT) as reader:
        pages_neat = compose_document(doc, reader, cfg_neat)
        pages_cursive_a = compose_document(doc, reader, cfg_cursive)
        pages_cursive_b = compose_document(doc, reader, cfg_cursive)

    # Cursive mode links sequential strokes via ligatures -> markedly fewer pen lifts than neat mode
    neat_strokes = len(pages_neat[0].strokes)
    cursive_strokes = len(pages_cursive_a[0].strokes)
    assert cursive_strokes < neat_strokes * 0.75
    # Still 100% deterministic for the same seed
    assert export_page_f32(pages_cursive_a[0])[0] == export_page_f32(pages_cursive_b[0])[0]


def test_missing_glyph_defaults_to_blank_space() -> None:
    cfg = LayoutConfig()
    assert cfg.fallback.policy == "blank"

    # Compare "永和" vs "永龘和": missing '龘' adds advance spacing without emitting strokes
    doc_ref = parse_plain_text("", "永和", "doc_ref_gap")
    doc_miss = parse_plain_text("", "永龘和", "doc_miss_gap")

    with HwFontReader(DEMO_FONT) as reader:
        assert not reader.has("龘")
        cfg_neat = LayoutConfig()
        cfg_neat.perturb.neatness = 0.90
        cfg_neat.text.first_line_indent_chars = 0.0
        pages_ref = compose_document(doc_ref, reader, cfg_neat)
        pages_miss = compose_document(doc_miss, reader, cfg_neat)

        assert len(pages_miss[0].strokes) == len(pages_ref[0].strokes)
        assert pages_miss[0].bbox[2] > pages_ref[0].bbox[2] + 3.0
        assert any(fg.char == "龘" and fg.count == 1 for fg in pages_miss[0].fallback_glyphs)

        # In cursive mode, ligatures must NOT bridge across the missing blank space
        cfg_cursive = LayoutConfig()
        cfg_cursive.perturb.neatness = 0.10
        cfg_cursive.text.first_line_indent_chars = 0.0
        pages_cur = compose_document(doc_miss, reader, cfg_cursive)
        assert any(fg.char == "龘" for fg in pages_cur[0].fallback_glyphs)
        # Every stroke X segment stops cleanly before/after the blank gap without jumping across '和' and '永'
        assert len(pages_cur[0].strokes) >= 2


def test_writing_regions_multi_field_and_body_flow() -> None:
    # 1. Pure multi-field composition with empty DocIR
    empty_doc = DocIR(
        doc_id="__regions_only__",
        source=DocSource(type="text", filename="fields", sha256="fields", parser="regions-only"),
        pages=[DocPageInfo(page_index=0, width_mm=210.0, height_mm=297.0)],
        blocks=[],
    )
    cfg = LayoutConfig()
    cfg.regions = [
        WritingRegion(
            region_id="r_course",
            name="课程名称",
            role="field",
            field_key="course_name",
            text="物理实验",
            page_scope="1",
            x_mm=30.0,
            y_mm=24.0,
            width_mm=80.0,
            height_mm=12.0,
        ),
        WritingRegion(
            region_id="r_name",
            name="姓名",
            role="field",
            field_key="student_name",
            text="永和",
            page_scope="1",
            x_mm=130.0,
            y_mm=24.0,
            width_mm=45.0,
            height_mm=12.0,
        ),
        WritingRegion(
            region_id="r_id",
            name="学号",
            role="field",
            field_key="student_id",
            text="01234567890",
            page_scope="1",
            x_mm=30.0,
            y_mm=44.0,
            width_mm=70.0,
            height_mm=12.0,
        ),
    ]
    with HwFontReader(DEMO_FONT) as reader:
        pages = compose_document(empty_doc, reader, cfg)

    assert len(pages) == 1
    by_reg: dict[str, list] = {}
    for st in pages[0].strokes:
        by_reg.setdefault(st.block_id, []).append(st)
    assert {"region:r_course", "region:r_name", "region:r_id"}.issubset(by_reg.keys())

    # Check coordinates stay inside each region bbox (plus small stroke jitter tolerance)
    for reg in cfg.regions:
        pts = np.concatenate([np.asarray(s.pts, dtype=np.float64).reshape(-1, 2) for s in by_reg[f"region:{reg.region_id}"]])
        assert pts[:, 0].min() >= reg.x_mm - 2.0
        assert pts[:, 0].max() <= reg.x_mm + reg.width_mm + 2.0
        assert pts[:, 1].min() >= reg.y_mm - 2.0
        assert pts[:, 1].max() <= reg.y_mm + reg.height_mm + 2.0

    # 2. Multi-body frame flow on the same page
    doc_long = parse_plain_text("", "永和九年，实验报告正文测试。" * 6, "doc_two_frames")
    cfg_body = LayoutConfig()
    cfg_body.text.first_line_indent_chars = 0.0
    cfg_body.regions = [
        WritingRegion(
            region_id="body_left",
            name="左栏",
            role="body",
            order=0,
            page_scope="1",
            x_mm=20.0,
            y_mm=30.0,
            width_mm=70.0,
            height_mm=32.0,
        ),
        WritingRegion(
            region_id="body_right",
            name="右栏",
            role="body",
            order=1,
            page_scope="1",
            x_mm=115.0,
            y_mm=30.0,
            width_mm=75.0,
            height_mm=65.0,
        ),
    ]
    with HwFontReader(DEMO_FONT) as reader:
        framed = compose_document(doc_long, reader, cfg_body)
    assert len(framed) >= 1
    all_xs = [float(np.mean(s.pts[0::2])) for s in framed[0].strokes]
    assert any(x < 95.0 for x in all_xs)
    assert any(x > 112.0 for x in all_xs)


def test_custom_paper_and_char_scale() -> None:
    doc = parse_plain_text("", "2026实验", "doc_custom_sz")
    cfg = LayoutConfig()
    cfg.page.size = "custom"
    cfg.page.width_mm = 150.0
    cfg.page.height_mm = 200.0
    cfg.text.first_line_indent_chars = 0.0
    cfg.text.char_scale_x = 1.0
    cfg.text.char_scale_y = 1.0

    cfg_wide = cfg.model_copy(deep=True)
    cfg_wide.text.char_scale_x = 1.45
    cfg_wide.text.char_scale_y = 0.80

    with HwFontReader(DEMO_FONT) as reader:
        p_norm = compose_document(doc, reader, cfg)[0]
        p_wide = compose_document(doc, reader, cfg_wide)[0]

    assert p_wide.width_mm == 150.0
    assert p_wide.height_mm == 200.0
    assert (p_wide.bbox[2] - p_wide.bbox[0]) > (p_norm.bbox[2] - p_norm.bbox[0]) * 1.25


def test_personal_reference_font_valid() -> None:
    personal_path = ROOT / "fonts" / "personal.hwfont"
    if not personal_path.is_file():
        pytest.skip("personal reference font is local-only (not in the repository)")

    with HwFontReader(personal_path) as reader:
        rep = reader.verify()
        assert rep.ok, f"personal.hwfont verification errors: {rep.errors}"
        assert reader.meta.writer_id == "personal"
        assert "generate_demo_writers" not in reader.meta.builder
        assert reader.meta.glyph_count >= 500
        assert reader.meta.variant_count >= 1200

        for ch in "0123456789实验声波":
            assert reader.has(ch), f"Missing scanned glyph '{ch}' in personal.hwfont"
            vars_list = reader.variants(ch)
            assert any(v.source == "scan" for v in vars_list), f"Glyph '{ch}' lacks scan provenance"

        # Continuous vectorization guard: rank-0 digits should be single/continuous strokes (median <= 2.5)
        digit_strokes = [len(reader.variants(d)[0].strokes) for d in "0123456789"]
        assert float(np.median(digit_strokes)) <= 2.5, f"Fragmented digit strokes: {digit_strokes}"

        doc = parse_plain_text("", "物理性污染控制工程实验2413龘", "doc_personal_test")
        cfg = LayoutConfig()
        assert cfg.fallback.policy == "blank"
        pages = compose_document(doc, reader, cfg)
        assert len(pages) == 1
        assert len(pages[0].strokes) > 30
        assert any(fg.char == "龘" and fg.count == 1 for fg in pages[0].fallback_glyphs)


def test_local_style_augmentor_preserves_junctions() -> None:
    aug = LocalStyleTransferAugmentor()
    s1 = np.array([[200, 200], [200, 800]], dtype=np.float64)
    s2 = np.array([[200, 200], [800, 200], [800, 800]], dtype=np.float64)
    s3 = np.array([[200, 800], [800, 800]], dtype=np.float64)
    variants = aug.synthesize_variants("口", [s1, s2, s3], n_variants=4, seed=42)
    assert len(variants) == 4

    for v in variants:
        assert len(v) == 3
        g1 = float(np.hypot(*(v[0][0] - v[1][0])))
        g2 = float(np.hypot(*(v[0][-1] - v[2][0])))
        g3 = float(np.hypot(*(v[1][-1] - v[2][-1])))
        assert max(g1, g2, g3) <= 4.0, f"Junction split detected: {(g1, g2, g3)}"

    for i in range(len(variants)):
        for j in range(i + 1, len(variants)):
            assert chamfer_distance(variants[i], variants[j]) >= 18.0
