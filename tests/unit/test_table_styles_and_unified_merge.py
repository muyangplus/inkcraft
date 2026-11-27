"""Unit & API tests for multi-style tables, cohesive (1)(2)(3) list merging, and Markdown roundtrip."""

from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient

from inkcraft.api.app import create_app
from inkcraft.api.schemas import LayoutConfig, TableBorderStyle, TableConfig
from inkcraft.config import Settings
from inkcraft.docparse.docir import (
    BreakInline,
    DocBlock,
    DocIR,
    DocPageInfo,
    DocSource,
    TableCell,
    TableData,
    TextInline,
)
from inkcraft.docparse.markdown_codec import docir_to_markdown, markdown_to_docir
from inkcraft.docparse.pdf_paragraph import (
    PageTypographyProfile,
    RawPdfLine,
    reconstruct_page_paragraphs,
)
from inkcraft.layout.composer import compose_document
from inkcraft.layout.table_renderer import render_table
from inkcraft.writers.registry import WriterRegistry

ROOT = Path(__file__).resolve().parents[2]
DEMO_FONT = ROOT / "fonts" / "lin_kaishu.hwfont"


def _make_sample_table(rows: int = 3, cols: int = 3) -> TableData:
    cells: list[TableCell] = []
    for r in range(rows):
        for c in range(cols):
            val = f"H{c+1}" if r == 0 else f"{r*10 + c}"
            cells.append(TableCell(r=r, c=c, rs=1, cs=1, inlines=[TextInline(text=val)]))
    return TableData(rows=rows, cols=cols, col_widths_mm=[50.0] * cols, cells=cells)


def _get_reader():
    reg = WriterRegistry(ROOT / "fonts")
    reg.rescan()
    return reg.get("lin_kaishu") or (reg.get(reg.active_writer_id) if reg.active_writer_id else None)


def test_table_renderer_all_seven_border_styles_and_compact_dimensions() -> None:
    from inkcraft.writers.selector import VariantSelector

    reader = _get_reader()
    assert reader is not None
    table = _make_sample_table(rows=4, cols=4)

    border_counts: dict[str, int] = {}
    heights: dict[str, float] = {}
    styles: list[TableBorderStyle] = [
        "grid",
        "compact",
        "three_line",
        "horizontal",
        "dashed",
        "minimal",
        "none",
    ]
    for st in styles:
        cfg = LayoutConfig(
            table=TableConfig(
                draw_borders=(st != "none"),
                border_style=st,
                hand_jitter_mm=0.15,
            )
        )
        sel = VariantSelector(reader, fallback_policy="blank")
        strokes, th = render_table(
            table,
            x0_mm=20.0,
            y0_mm=30.0,
            width_mm=160.0,
            max_height_mm=None,
            selector=sel,
            config=cfg,
            block_id=f"tbl-{st}",
            page_index=0,
        )
        borders = [s for s in strokes if s.kind == "table" and s.reversible]
        border_counts[st] = len(borders)
        heights[st] = th

    assert border_counts["none"] == 0
    assert border_counts["three_line"] == 5  # top double (2) + header (1) + bottom double (2)
    assert border_counts["minimal"] == 5     # outer 4 edges + header separator
    assert border_counts["horizontal"] == 5  # rows + 1 horizontal lines, 0 vertical
    assert border_counts["grid"] == 10       # 5 horizontal + 5 vertical
    assert border_counts["dashed"] > border_counts["grid"] * 2
    assert heights["compact"] < heights["grid"] * 0.85

    # Verify compose_reflow narrows table width when style="compact"
    doc_compact = DocIR(
        doc_id="d_tbl",
        source=DocSource(type="text", filename="t.txt", sha256="x", parser="test"),
        pages=[DocPageInfo(page_index=0, width_mm=210, height_mm=297)],
        blocks=[
            DocBlock(
                block_id="t1",
                page_index=0,
                type="table",
                reading_order=0,
                table=_make_sample_table(rows=3, cols=3),
            )
        ],
    )
    pages_grid = compose_document(doc_compact, reader, LayoutConfig(table=TableConfig(border_style="grid")))
    pages_compact = compose_document(doc_compact, reader, LayoutConfig(table=TableConfig(border_style="compact")))
    box_grid = pages_grid[0].placed_blocks[0].bbox_mm
    box_compact = pages_compact[0].placed_blocks[0].bbox_mm
    w_grid = box_grid[2] - box_grid[0]
    w_compact = box_compact[2] - box_compact[0]
    assert w_compact < w_grid * 0.85


def test_reconstruct_merges_consecutive_lists_and_symbol_defs_and_roundtrips_md() -> None:
    profile = PageTypographyProfile(
        page_index=0,
        page_w_mm=210.0,
        page_h_mm=297.0,
        body_pt=10.5,
        body_font_mm=3.7,
        body_left_x0=25.0,
        body_right_x1=185.0,
        median_gap_mm=2.4,
    )
    lines = [
        RawPdfLine(0, [25.0, 22.0, 100.0, 28.0], [25.0, 22.0, 100.0, 28.0], "二、实验步骤", 14.0, 14.0, True),
        RawPdfLine(0, [32.0, 32.0, 165.0, 36.0], [32.0, 32.0, 165.0, 36.0], "(1) 取试样 50 g 放入烘干皿中。", 10.5, 10.5, False),
        RawPdfLine(0, [32.0, 39.0, 183.5, 43.0], [32.0, 39.0, 183.5, 43.0], "(2) 在 105 度条件下恒温烘烤直至前后两次", 10.5, 10.5, False),
        RawPdfLine(0, [25.0, 45.2, 115.0, 49.2], [25.0, 45.2, 115.0, 49.2], "称量差值小于 0.1 克为止。", 10.5, 10.5, False),
        RawPdfLine(0, [32.0, 52.0, 150.0, 56.0], [32.0, 52.0, 150.0, 56.0], "(3) 放入干燥器冷却后读取质量。", 10.5, 10.5, False),
        RawPdfLine(0, [32.0, 62.0, 155.0, 66.0], [32.0, 62.0, 155.0, 66.0], "式中：C1——湿基水分含量；", 10.5, 10.5, False),
        RawPdfLine(0, [32.0, 68.5, 150.0, 72.5], [32.0, 68.5, 150.0, 72.5], "C2——干基残渣比例。", 10.5, 10.5, False),
    ]

    blocks = reconstruct_page_paragraphs(lines, [], page_index=0, profile=profile)
    assert [b.type for b in blocks] == ["heading", "list_item", "paragraph"]

    list_blk = blocks[1]
    assert len(list_blk.lines) == 4  # Keeps all 4 PDF visual lines intact for Overlay!
    assert sum(1 for inl in list_blk.inlines if isinstance(inl, BreakInline)) == 2
    plain = list_blk.plain_text()
    assert "(1) 取试样" in plain
    assert "(2) 在 105 度条件下恒温烘烤直至前后两次称量差值小于 0.1 克为止。" in plain
    assert "(3) 放入干燥器冷却后读取质量。" in plain

    sym_blk = blocks[2]
    assert sum(1 for inl in sym_blk.inlines if isinstance(inl, BreakInline)) == 1
    assert "式中：C_1——湿基水分含量；" in sym_blk.plain_text()
    assert "C_2——干基残渣比例。" in sym_blk.plain_text()

    # Lossless Markdown roundtrip preserves single merged list_item without bogus "- " prefix
    doc = DocIR(
        doc_id="doc_list_rt",
        source=DocSource(type="pdf", filename="rt.pdf", sha256="x", parser="pymupdf"),
        pages=[DocPageInfo(page_index=0, width_mm=210, height_mm=297)],
        blocks=blocks,
    )
    md = docir_to_markdown(doc)
    assert "\n- (1)" not in md
    assert "(1) 取试样 50 g 放入烘干皿中。\n(2)" in md

    rt = markdown_to_docir(md, doc)
    rt_lists = [b for b in rt.blocks if b.type == "list_item"]
    assert len(rt_lists) == 1
    assert sum(1 for inl in rt_lists[0].inlines if isinstance(inl, BreakInline)) == 2


def test_per_table_style_patch_markdown_and_compose_override(tmp_path: Path) -> None:
    fonts_dir = tmp_path / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    if DEMO_FONT.is_file():
        (fonts_dir / DEMO_FONT.name).write_bytes(DEMO_FONT.read_bytes())
    data_dir = tmp_path / "data"
    settings = Settings(
        root_dir=ROOT,
        fonts_dir=fonts_dir,
        data_dir=data_dir,
        db_path=data_dir / "app.db",
        profiles_path=ROOT / "config" / "default_profiles.json",
        frontend_dist_dir=ROOT / "frontend" / "dist",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        md_src = "| 列A | 列B | 列C |\n| --- | --- | --- |\n| 1 | 2 | 3 |\n| 4 | 5 | 6 |"
        r = client.post("/api/v1/documents/text", json={"title": "表格测试", "text": md_src})
        assert r.status_code == 201
        doc_id = r.json()["doc_id"]

        r_blks = client.get(f"/api/v1/documents/{doc_id}/blocks")
        assert r_blks.status_code == 200
        tbl_blk = next(b for b in r_blks.json()["blocks"] if b["type"] == "table")

        r_patch = client.patch(
            f"/api/v1/documents/{doc_id}/blocks/{tbl_blk['block_id']}",
            json={"table_border_style": "three_line", "table_width_ratio": 0.72, "table_align": "left"},
        )
        assert r_patch.status_code == 200
        patched = r_patch.json()["block"]
        assert patched["table"]["border_style"] == "three_line"
        assert patched["table"]["width_ratio"] == 0.72
        assert "<!-- hw:table" in r_patch.json()["markdown"]
        assert "style=three_line" in r_patch.json()["markdown"]

        r_put_md = client.put(
            f"/api/v1/documents/{doc_id}/markdown",
            json={"markdown": r_patch.json()["markdown"]},
        )
        assert r_put_md.status_code == 200
        rt_tbl = next(b for b in r_put_md.json()["blocks"] if b["type"] == "table")
        assert rt_tbl["table"]["border_style"] == "three_line"
        assert rt_tbl["table"]["width_ratio"] == 0.72
