"""Unit tests for keep-caption-with-table and keep-caption-with-figure reflow pagination toggles."""

from __future__ import annotations

from pathlib import Path
from PIL import Image

from handwrite.api.schemas import LayoutConfig
from handwrite.docparse.docir import (
    ChartData,
    DocBlock,
    DocIR,
    DocPageInfo,
    DocSource,
    TableCell,
    TableData,
    TextInline,
)
from handwrite.layout.composer import compose_document
from handwrite.writers.registry import WriterRegistry

ROOT = Path(__file__).resolve().parents[2]


def _load_reader():
    reg = WriterRegistry(ROOT / "fonts")
    reg.rescan()
    reader = reg.get("personal") or reg.get("lin_kaishu") or reg.get(reg.active_writer_id or "")
    assert reader is not None
    return reader


def _make_filler_blocks(count: int, text: str) -> list[DocBlock]:
    return [
        DocBlock(
            block_id=f"fill-{i}",
            page_index=0,
            type="paragraph",
            reading_order=i,
            bbox_mm=[20.0, 22.0 + i * 18.0, 185.0, 36.0 + i * 18.0],
            inlines=[TextInline(text=text)],
        )
        for i in range(count)
    ]


def _make_sample_table(block_id: str, ro: int, rows: int = 5, cols: int = 4) -> DocBlock:
    cells = [
        TableCell(
            r=r,
            c=c,
            rs=1,
            cs=1,
            inlines=[TextInline(text=f"C{r}-{c}" if r > 0 else f"列{c+1}")],
        )
        for r in range(rows)
        for c in range(cols)
    ]
    return DocBlock(
        block_id=block_id,
        page_index=0,
        type="table",
        reading_order=ro,
        bbox_mm=[20.0, 100.0, 185.0, 160.0],
        table=TableData(rows=rows, cols=cols, col_widths_mm=[40.0] * cols, cells=cells),
    )


def _find_placed(pages, block_id: str) -> int:
    for pg in pages:
        for box in pg.placed_blocks:
            if box.block_id == block_id:
                return pg.page_index
    raise AssertionError(f"Block {block_id!r} not found in composed pages")


def test_default_keep_caption_switches_are_enabled() -> None:
    cfg = LayoutConfig()
    assert cfg.table.keep_caption_with_table is True
    assert cfg.chart.keep_caption_with_figure is True


def test_table_caption_moves_to_next_page_with_table_when_enabled() -> None:
    reader = _load_reader()
    filler_txt = "本实验通过烘干与灼烧测量生活垃圾的含水率及可燃物比例，请严格控制箱内温度。" * 2
    # Tune filler count until caption alone fits on Page 0 while table (5 rows) does not
    cap_id = "cap-tbl"
    tbl_id = "tbl-main"

    matched_blocks: list[DocBlock] | None = None
    for n_fill in range(4, 14):
        blocks = _make_filler_blocks(n_fill, filler_txt)
        blocks.append(
            DocBlock(
                block_id=cap_id,
                page_index=0,
                type="caption",
                reading_order=n_fill,
                bbox_mm=[20.0, 220.0, 120.0, 226.0],
                inlines=[TextInline(text="表1 污泥调理数据记录")],
            )
        )
        blocks.append(_make_sample_table(tbl_id, n_fill + 1, rows=5, cols=4))
        doc = DocIR(
            doc_id="doc_tbl_keep",
            source=DocSource(type="docx", filename="tbl.docx", sha256="tbl", parser="docx"),
            pages=[DocPageInfo(page_index=0, width_mm=210.0, height_mm=297.0)],
            blocks=blocks,
        )
        cfg_off = LayoutConfig(mode="reflow")
        cfg_off.table.keep_caption_with_table = False
        pages_off = compose_document(doc, reader, cfg_off)
        if _find_placed(pages_off, cap_id) == 0 and _find_placed(pages_off, tbl_id) == 1:
            matched_blocks = blocks
            break

    assert matched_blocks is not None, "Could not construct boundary where caption fits P0 and table wraps P1"
    doc = DocIR(
        doc_id="doc_tbl_keep",
        source=DocSource(type="docx", filename="tbl.docx", sha256="tbl", parser="docx"),
        pages=[DocPageInfo(page_index=0, width_mm=210.0, height_mm=297.0)],
        blocks=matched_blocks,
    )

    cfg_on = LayoutConfig(mode="reflow")
    pages_on = compose_document(doc, reader, cfg_on)
    assert _find_placed(pages_on, cap_id) == 1
    assert _find_placed(pages_on, tbl_id) == 1

    # Also verify a plain paragraph styled as table title (`表1 ...`) follows the same toggle
    para_blocks = [b.model_copy(deep=True) for b in matched_blocks]
    para_blocks[-2].type = "paragraph"
    doc_para = doc.model_copy(deep=True, update={"blocks": para_blocks})
    pages_para_on = compose_document(doc_para, reader, cfg_on)
    assert _find_placed(pages_para_on, cap_id) == 1
    assert _find_placed(pages_para_on, tbl_id) == 1


def test_figure_and_caption_stay_together_for_top_and_bottom_captions(tmp_path: Path) -> None:
    reader = _load_reader()
    img_path = tmp_path / "sample_fig.png"
    Image.new("L", (160, 100), 255).save(img_path)

    filler_txt = "测试填充行用于精确定位图名分页窗口。"

    # 1. Bottom caption (`figure -> caption`): figure fits on P0 alone, caption wraps to P1 when switch OFF
    bottom_blocks: list[DocBlock] | None = None
    for n_fill in range(8, 22):
        blocks = _make_filler_blocks(n_fill, filler_txt)
        blocks.append(
            DocBlock(
                block_id="fig-bot",
                page_index=0,
                type="figure",
                reading_order=n_fill,
                bbox_mm=[30.0, 140.0, 150.0, 200.0],
                image_path=str(img_path),
                image_width_mm=100.0,
                image_height_mm=58.0,
                chart=ChartData(chart_type="raster", image_path=str(img_path)),
            )
        )
        blocks.append(
            DocBlock(
                block_id="cap-bot",
                page_index=0,
                type="caption",
                reading_order=n_fill + 1,
                bbox_mm=[40.0, 205.0, 140.0, 212.0],
                inlines=[TextInline(text="图1 氧弹外形图")],
            )
        )
        doc = DocIR(
            doc_id="doc_fig_bot",
            source=DocSource(type="docx", filename="fig_bot.docx", sha256="fb", parser="docx"),
            pages=[DocPageInfo(page_index=0, width_mm=210.0, height_mm=297.0)],
            blocks=blocks,
        )
        cfg_off = LayoutConfig(mode="reflow")
        cfg_off.chart.keep_caption_with_figure = False
        pages_off = compose_document(doc, reader, cfg_off)
        if _find_placed(pages_off, "fig-bot") == 0 and _find_placed(pages_off, "cap-bot") == 1:
            bottom_blocks = blocks
            break

    assert bottom_blocks is not None, "Could not construct bottom-caption figure split boundary"
    doc_bot = DocIR(
        doc_id="doc_fig_bot",
        source=DocSource(type="docx", filename="fig_bot.docx", sha256="fb", parser="docx"),
        pages=[DocPageInfo(page_index=0, width_mm=210.0, height_mm=297.0)],
        blocks=bottom_blocks,
    )
    pages_bot_on = compose_document(doc_bot, reader, LayoutConfig(mode="reflow"))
    assert _find_placed(pages_bot_on, "fig-bot") == 1
    assert _find_placed(pages_bot_on, "cap-bot") == 1

    # 2. Top caption (`caption -> figure`): caption fits on P0 alone, figure wraps to P1 when switch OFF
    top_blocks: list[DocBlock] | None = None
    for n_fill in range(8, 22):
        blocks = _make_filler_blocks(n_fill, filler_txt)
        blocks.append(
            DocBlock(
                block_id="cap-top",
                page_index=0,
                type="caption",
                reading_order=n_fill,
                bbox_mm=[40.0, 220.0, 140.0, 226.0],
                inlines=[TextInline(text="图2 装置连接示意图")],
            )
        )
        blocks.append(
            DocBlock(
                block_id="fig-top",
                page_index=0,
                type="figure",
                reading_order=n_fill + 1,
                bbox_mm=[30.0, 230.0, 150.0, 285.0],
                image_path=str(img_path),
                image_width_mm=100.0,
                image_height_mm=58.0,
                chart=ChartData(chart_type="raster", image_path=str(img_path)),
            )
        )
        doc = DocIR(
            doc_id="doc_fig_top",
            source=DocSource(type="docx", filename="fig_top.docx", sha256="ft", parser="docx"),
            pages=[DocPageInfo(page_index=0, width_mm=210.0, height_mm=297.0)],
            blocks=blocks,
        )
        cfg_off = LayoutConfig(mode="reflow")
        cfg_off.chart.keep_caption_with_figure = False
        pages_off = compose_document(doc, reader, cfg_off)
        if _find_placed(pages_off, "cap-top") == 0 and _find_placed(pages_off, "fig-top") == 1:
            top_blocks = blocks
            break

    assert top_blocks is not None, "Could not construct top-caption figure split boundary"
    doc_top = DocIR(
        doc_id="doc_fig_top",
        source=DocSource(type="docx", filename="fig_top.docx", sha256="ft", parser="docx"),
        pages=[DocPageInfo(page_index=0, width_mm=210.0, height_mm=297.0)],
        blocks=top_blocks,
    )
    pages_top_on = compose_document(doc_top, reader, LayoutConfig(mode="reflow"))
    assert _find_placed(pages_top_on, "cap-top") == 1
    assert _find_placed(pages_top_on, "fig-top") == 1

    # 3. Consecutive `[fig1, cap1, fig2, cap2]` must NOT drag `cap1` onto `fig2`'s page
    pair_blocks = [
        DocBlock(
            block_id="fig-1",
            page_index=0,
            type="figure",
            reading_order=0,
            bbox_mm=[30.0, 22.0, 150.0, 140.0],
            image_path=str(img_path),
            image_width_mm=120.0,
            image_height_mm=115.0,
            chart=ChartData(chart_type="raster", image_path=str(img_path)),
        ),
        DocBlock(
            block_id="cap-1",
            page_index=0,
            type="caption",
            reading_order=1,
            bbox_mm=[40.0, 144.0, 140.0, 150.0],
            inlines=[TextInline(text="图1 仪器外形图")],
        ),
        DocBlock(
            block_id="fig-2",
            page_index=0,
            type="figure",
            reading_order=2,
            bbox_mm=[30.0, 160.0, 150.0, 280.0],
            image_path=str(img_path),
            image_width_mm=120.0,
            image_height_mm=115.0,
            chart=ChartData(chart_type="raster", image_path=str(img_path)),
        ),
        DocBlock(
            block_id="cap-2",
            page_index=0,
            type="caption",
            reading_order=3,
            bbox_mm=[40.0, 282.0, 140.0, 288.0],
            inlines=[TextInline(text="图2 仪器剖面图")],
        ),
    ]
    doc_pair = DocIR(
        doc_id="doc_fig_pair",
        source=DocSource(type="docx", filename="pair.docx", sha256="pr", parser="docx"),
        pages=[DocPageInfo(page_index=0, width_mm=210.0, height_mm=297.0)],
        blocks=pair_blocks,
    )
    pages_pair = compose_document(doc_pair, reader, LayoutConfig(mode="reflow"))
    assert _find_placed(pages_pair, "fig-1") == 0
    assert _find_placed(pages_pair, "cap-1") == 0
    assert _find_placed(pages_pair, "fig-2") == 1
    assert _find_placed(pages_pair, "cap-2") == 1
