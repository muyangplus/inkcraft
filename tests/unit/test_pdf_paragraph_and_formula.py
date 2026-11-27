"""Unit tests for PDF paragraph reconstruction, cross-page merging, and formula/caption OCR fixes."""

from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw
import pytest

from handwrite.api.schemas import LayoutConfig
from handwrite.docparse.docir import DocBlock, DocIR, DocLine, DocPageInfo, DocSource, TextInline
from handwrite.docparse.formula_ocr import (
    _OcrBox,
    _PdfSpan,
    _align_cjk_phrase_with_lexicon,
    _extract_symbol_table,
    _format_pdf_span_group,
    _repair_latex_subscripts_with_context,
    _split_stacked_rows,
    build_cjk_lexicon,
)
from handwrite.docparse.pdf_paragraph import (
    PageTypographyProfile,
    RawPdfLine,
    _join_line_texts,
    merge_cross_page_paragraphs,
    reconstruct_page_paragraphs,
)
from handwrite.docparse.pdf_parser import parse_pdf
from handwrite.layout.composer import compose_document
from handwrite.writers.registry import WriterRegistry

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_PDF = ROOT / "source" / "4-实验教学指导书.pdf"


def test_join_line_texts_cjk_and_ascii_hyphen() -> None:
    assert _join_line_texts("城市生活垃圾含水率", "测定实验步骤") == "城市生活垃圾含水率测定实验步骤"
    assert _join_line_texts("volatile solid", "content") == "volatile solid content"
    assert _join_line_texts("calori-", "meter") == "calorimeter"


def test_reconstruct_page_paragraphs_merges_soft_wraps_and_preserves_breaks() -> None:
    profile = PageTypographyProfile(
        page_index=0,
        page_w_mm=210.0,
        page_h_mm=297.0,
        body_pt=10.5,
        body_font_mm=3.7,
        body_left_x0=25.0,
        body_right_x1=185.0,
        median_gap_mm=2.5,
    )
    lines = [
        RawPdfLine(0, [25.0, 22.0, 120.0, 28.0], [25.0, 22.0, 120.0, 28.0], "一、实验目的与原理", 14.0, 14.0, True),
        # First paragraph: indented first line + flush-left wrapped continuation + final short line
        RawPdfLine(0, [32.4, 34.0, 184.0, 38.0], [32.4, 34.0, 184.0, 38.0], "将城市生活垃圾试样放在烘箱内保持恒温烘", 10.5, 10.5, False),
        RawPdfLine(0, [25.0, 40.5, 183.5, 44.5], [25.0, 40.5, 183.5, 44.5], "干至恒重，随后置于干燥器内冷却并记录试样", 10.5, 10.5, False),
        RawPdfLine(0, [25.0, 47.0, 75.0, 51.0], [25.0, 47.0, 75.0, 51.0], "的前后质量变化。", 10.5, 10.5, False),
        # Second paragraph: indented start -> MUST remain a distinct paragraph block
        RawPdfLine(0, [32.4, 53.5, 145.0, 57.5], [32.4, 53.5, 145.0, 57.5], "（1）实验开始前检查天平零点校准。", 10.5, 10.5, False),
        # Symbol definition line -> must stay distinct
        RawPdfLine(0, [32.0, 60.0, 140.0, 64.0], [32.0, 60.0, 140.0, 64.0], "式中：Ci（湿）——湿地垃圾中湿基含量；", 10.5, 10.5, False),
    ]

    blocks = reconstruct_page_paragraphs(lines, [], page_index=0, profile=profile)
    assert [b.type for b in blocks] == ["heading", "paragraph", "list_item", "paragraph"]
    assert blocks[1].plain_text() == "将城市生活垃圾试样放在烘箱内保持恒温烘干至恒重，随后置于干燥器内冷却并记录试样的前后质量变化。"
    assert len(blocks[1].lines) == 3
    assert all(ln.page_index == 0 for ln in blocks[1].lines)


def test_cross_page_merge_preserves_page_indices_in_overlay() -> None:
    prof0 = PageTypographyProfile(0, 210.0, 297.0, 10.5, 3.7, 25.0, 185.0, 2.5)
    prof1 = PageTypographyProfile(1, 210.0, 297.0, 10.5, 3.7, 25.0, 185.0, 2.5)

    b0 = DocBlock(
        block_id="p0-b0",
        page_index=0,
        type="paragraph",
        reading_order=0,
        bbox_mm=[25.0, 260.0, 184.0, 270.0],
        lines=[DocLine(page_index=0, bbox_mm=[32.0, 260.0, 184.0, 270.0], inlines=[TextInline(text="本段前半部分跨过页尾并没有终止符号，继续向")])],
        inlines=[TextInline(text="本段前半部分跨过页尾并没有终止符号，继续向")],
    )
    b1 = DocBlock(
        block_id="p1-b0",
        page_index=1,
        type="paragraph",
        reading_order=1,
        bbox_mm=[25.0, 26.0, 120.0, 32.0],
        lines=[DocLine(page_index=1, bbox_mm=[25.0, 26.0, 120.0, 32.0], inlines=[TextInline(text="下一页开头延续完成整段叙述。")])],
        inlines=[TextInline(text="下一页开头延续完成整段叙述。")],
    )

    merged = merge_cross_page_paragraphs([b0, b1], {0: prof0, 1: prof1})
    assert len(merged) == 1
    assert merged[0].plain_text() == "本段前半部分跨过页尾并没有终止符号，继续向下一页开头延续完成整段叙述。"
    assert [ln.page_index for ln in merged[0].lines] == [0, 1]

    doc = DocIR(
        doc_id="doc_cross",
        source=DocSource(type="pdf", filename="cross.pdf", sha256="x", parser="pymupdf"),
        pages=[DocPageInfo(page_index=0, width_mm=210, height_mm=297), DocPageInfo(page_index=1, width_mm=210, height_mm=297)],
        blocks=merged,
    )
    reg = WriterRegistry(ROOT / "fonts")
    reg.rescan()
    reader = reg.get("lin_kaishu") or (reg.get(reg.active_writer_id) if reg.active_writer_id else None)
    cfg = LayoutConfig(mode="overlay")
    pages = compose_document(doc, reader, cfg)
    assert len(pages) == 2
    assert pages[0].stats.stroke_count > 0
    assert pages[1].stats.stroke_count > 0


def test_formula_ocr_stacked_rows_symbol_table_and_lexicon() -> None:
    # 1. Thin 3px superscript band above major row must survive _split_stacked_rows (e.g. `n` over `\sum`)
    im = Image.new("L", (140, 86), 255)
    draw = ImageDraw.Draw(im)
    draw.rectangle((10, 12, 18, 15), fill=0)   # 4px superscript band above first equation body
    draw.rectangle((5, 22, 120, 38), fill=0)   # first equation row (17px tall >= major_thresh=12)
    draw.rectangle((35, 58, 95, 74), fill=0)   # second equation row (17px tall, distinct vertical band)
    rows = _split_stacked_rows(im)
    assert len(rows) == 2
    assert rows[0].height >= 20  # retained superscript band at y=12..15 alongside y=22..38!

    # 2. General SymbolTable repair works for both `C_{i(\text{湿})}`, `C_{(\text{水})}`, and `C_{\text{卡}}`
    ctx = "式中：Ci（湿）——垃圾组分湿基含量；C(水)——水样比热容；C卡——量热计热容。"
    sym_table = _extract_symbol_table(ctx)
    assert "C" in sym_table
    repaired = _repair_latex_subscripts_with_context(
        r"C_{i\star} + C_{\infty} + C_{\mathbb{R}}",
        [_OcrBox(0, 0, 40, 20, "Ci(湿)"), _OcrBox(50, 0, 90, 20, "C(水)"), _OcrBox(100, 0, 140, 20, "C卡")],
        sym_table,
    )
    assert r"C_{i(\text{湿})}" in repaired
    assert r"C_{(\text{水})}" in repaired
    assert r"C_{\text{卡}}" in repaired

    # 3. Confusable-guarded lexicon alignment fixes OCR homoglyphs using real nearby terms
    lexicon = build_cjk_lexicon("测定生活垃圾容重与燃烧皿热值参数。")
    aligned, changed = _align_cjk_phrase_with_lexicon("垃圾客重", 0.72, lexicon, set())
    assert changed is True
    assert aligned == "垃圾容重"

    # 4. Native PDF span y-offset superscript formatting (`kg/m^3`)
    spans = [
        _PdfSpan("kg/m", [10.0, 20.0, 30.0, 30.0], 10.0, "TimesNewRoman"),
        _PdfSpan("3", [30.2, 18.0, 34.0, 25.0], 6.5, "TimesNewRoman"),
    ]
    assert _format_pdf_span_group(spans) == "kg/m^{3}"


def test_sample_pdf_paragraphs_and_key_formulas(tmp_path: Path) -> None:
    if not SAMPLE_PDF.is_file():
        pytest.skip("Sample PDF not present in workspace")
    doc = parse_pdf(SAMPLE_PDF, doc_id="doc_sample_p1", out_dir=tmp_path / "out", use_mineru=False)
    paras = [b for b in doc.blocks if b.type == "paragraph"]
    # Previously >200 fragments; reconstructed paragraphs should be well below 85
    assert len(paras) < 85
    # Page 0 -> Page 1 cross-page merge should exist
    assert any(
        b.lines and len({ln.page_index for ln in b.lines if ln.page_index is not None}) >= 2
        for b in paras
    )

    formulas = [b for b in doc.blocks if b.type == "formula_block" and b.latex]
    all_latex = "\n".join(b.latex or "" for b in formulas)
    assert r"\sum" in all_latex
    assert "湿" in all_latex

    captions = [b for b in doc.blocks if b.type == "caption"]
    assert any("燃烧皿" in c.plain_text() for c in captions)
