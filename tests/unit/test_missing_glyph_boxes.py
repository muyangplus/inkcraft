"""Unit tests for spatial MissingGlyphBox tracking across all fallback policies & schema validation."""

from __future__ import annotations

from pathlib import Path
import pytest

from inkcraft.api.schemas import FallbackConfig, LayoutConfig, MachineProfile, PageConfig
from inkcraft.docparse.docir import DocBlock, DocIR, DocPageInfo, DocSource, TextInline
from inkcraft.gcode.compiler import compile_page_gcode
from inkcraft.layout.composer import compose_document
from inkcraft.writers.registry import WriterRegistry

ROOT = Path(__file__).resolve().parents[2]


def _get_reader():
    reg = WriterRegistry(ROOT / "fonts")
    reg.rescan()
    wid = "lin_kaishu" if reg.get("lin_kaishu") else reg.active_writer_id
    if not wid:
        pytest.skip("No writer font available for missing-glyph test")
    return reg.get(wid)


def test_page_config_underlay_fit_schema() -> None:
    cfg = PageConfig()
    assert cfg.underlay_fit == "fill"
    cfg_contain = PageConfig(underlay_fit="contain")
    assert cfg_contain.underlay_fit == "contain"
    cfg_custom = PageConfig(underlay_fit="custom", underlay_width_mm=180.0, underlay_height_mm=260.0)
    assert cfg_custom.underlay_width_mm == 180.0


@pytest.mark.parametrize("policy", ["blank", "skip", "builtin_single_line", "box"])
def test_missing_glyph_boxes_recorded_across_all_policies(policy: str) -> None:
    reader = _get_reader()
    doc = DocIR(
        doc_id="doc_mg_test",
        source=DocSource(type="text", filename="mg.txt", sha256="x", parser="test"),
        pages=[DocPageInfo(page_index=0, width_mm=210, height_mm=297)],
        blocks=[
            DocBlock(
                block_id="blk_para",
                page_index=0,
                type="paragraph",
                reading_order=0,
                bbox_mm=[20, 22, 190, 40],
                inlines=[TextInline(text="测试缺失字龘和靐结束。")],
            )
        ],
    )
    cfg = LayoutConfig(fallback=FallbackConfig(policy=policy))
    pages = compose_document(doc, reader, cfg)
    assert len(pages) == 1
    page = pages[0]
    mgs = page.missing_glyphs
    chars = [m.char for m in mgs]
    assert "龘" in chars
    assert "靐" in chars

    ids = [m.id for m in mgs]
    assert len(ids) == len(set(ids))
    assert ids[0].startswith("mg_p0_")

    for mg in mgs:
        assert mg.page_index == 0
        assert mg.block_id == "blk_para"
        assert mg.policy == policy
        assert len(mg.bbox_mm) == 4
        assert mg.bbox_mm[2] > mg.bbox_mm[0]
        assert mg.bbox_mm[3] > mg.bbox_mm[1]
        assert mg.unicode_hex.startswith("U+")
        assert len(mg.context) > 1


def test_blank_and_skip_emit_no_gcode_strokes_for_missing_glyphs() -> None:
    reader = _get_reader()
    doc = DocIR(
        doc_id="doc_mg_only",
        source=DocSource(type="text", filename="mg_only.txt", sha256="x", parser="test"),
        pages=[DocPageInfo(page_index=0, width_mm=210, height_mm=297)],
        blocks=[
            DocBlock(
                block_id="blk_only_mg",
                page_index=0,
                type="paragraph",
                reading_order=0,
                bbox_mm=[20, 22, 190, 40],
                inlines=[TextInline(text="龘靐")],
            )
        ],
    )
    # Blank policy keeps bounding boxes visible in UI while writing zero strokes to G-code
    pages_blank = compose_document(doc, reader, LayoutConfig(fallback=FallbackConfig(policy="blank")))
    assert len(pages_blank[0].missing_glyphs) == 2
    assert len(pages_blank[0].strokes) == 0
    compiled = compile_page_gcode(pages_blank[0], MachineProfile())
    assert compiled.draw_mm == 0.0

    # Skip policy advances zero width for skipped glyphs (second glyph sits near first glyph's x0)
    pages_skip = compose_document(doc, reader, LayoutConfig(fallback=FallbackConfig(policy="skip")))
    assert len(pages_skip[0].missing_glyphs) == 2
    assert len(pages_skip[0].strokes) == 0
    assert abs(pages_skip[0].missing_glyphs[1].bbox_mm[0] - pages_skip[0].missing_glyphs[0].bbox_mm[0]) < 1.0


def test_missing_glyphs_cross_page_indices() -> None:
    reader = _get_reader()
    filler = "实验测试文字换行填充内容。" * 25
    doc = DocIR(
        doc_id="doc_mg_multipage",
        source=DocSource(type="text", filename="mg_multi.txt", sha256="x", parser="test"),
        pages=[DocPageInfo(page_index=0, width_mm=148, height_mm=210)],
        blocks=[
            DocBlock(
                block_id="blk_1",
                page_index=0,
                type="paragraph",
                reading_order=0,
                bbox_mm=[15, 20, 130, 60],
                inlines=[TextInline(text="首段缺字龘。") ],
            ),
            DocBlock(
                block_id="blk_2",
                page_index=0,
                type="paragraph",
                reading_order=1,
                bbox_mm=[15, 70, 130, 190],
                inlines=[TextInline(text=filler + "尾段缺字靐。")],
            ),
        ],
    )
    cfg = LayoutConfig(
        page=PageConfig(size="A5", width_mm=148, height_mm=210),
        fallback=FallbackConfig(policy="blank"),
    )
    pages = compose_document(doc, reader, cfg)
    assert len(pages) >= 2
    p0_chars = [m.char for m in pages[0].missing_glyphs]
    later_chars = [m.char for p in pages[1:] for m in p.missing_glyphs]
    assert "龘" in p0_chars
    assert "靐" in later_chars
