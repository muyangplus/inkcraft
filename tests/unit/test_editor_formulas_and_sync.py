"""Unit and API tests for PDF formula extraction, Markdown editing, outline/shading images, and spacing sync."""

from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw
import pytest
from fastapi.testclient import TestClient

from inkcraft.api.app import create_app
from inkcraft.api.schemas import ChartConfig, LayoutConfig, TextConfig
from inkcraft.config import Settings
from inkcraft.docparse.chart_extract import vectorize_raster_image
from inkcraft.docparse.docir import ChartData, DocBlock, DocIR, DocPageInfo, DocSource, MathInline, TextInline
from inkcraft.docparse.markdown_codec import docir_to_markdown, markdown_to_docir
from inkcraft.docparse.pdf_parser import parse_pdf
from inkcraft.gcode.optimizer import optimize_page
from inkcraft.layout.chart_renderer import render_chart
from inkcraft.layout.composer import compose_document
from inkcraft.writers.registry import WriterRegistry

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_PDF = ROOT / "source" / "4-实验教学指导书.pdf"
DEMO_FONT = ROOT / "fonts" / "lin_kaishu.hwfont"


def _make_settings(tmp_path: Path) -> Settings:
    fonts_dir = tmp_path / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    if DEMO_FONT.is_file():
        (fonts_dir / DEMO_FONT.name).write_bytes(DEMO_FONT.read_bytes())
    data_dir = tmp_path / "data"
    return Settings(
        root_dir=ROOT,
        fonts_dir=fonts_dir,
        data_dir=data_dir,
        db_path=data_dir / "app.db",
        profiles_path=ROOT / "config" / "default_profiles.json",
        frontend_dist_dir=ROOT / "frontend" / "dist",
    )


def _sample_diagram(path: Path) -> None:
    im = Image.new("RGB", (180, 120), (255, 255, 255))
    draw = ImageDraw.Draw(im)
    draw.rectangle((30, 20, 150, 100), fill=(40, 40, 40), outline=(0, 0, 0))
    draw.ellipse((70, 40, 110, 80), fill=(255, 255, 255), outline=(0, 0, 0))
    im.save(path)


def test_parse_sample_pdf_formulas_captions_and_outline_figures(tmp_path: Path) -> None:
    if not SAMPLE_PDF.is_file():
        pytest.skip("Sample PDF not present in workspace")
    out_dir = tmp_path / "pdf_out"
    doc = parse_pdf(SAMPLE_PDF, doc_id="doc_sample", out_dir=out_dir, use_mineru=False)

    formulas = [b for b in doc.blocks if b.type == "formula_block"]
    figures = [b for b in doc.blocks if b.type == "figure"]
    captions = [b for b in doc.blocks if b.type == "caption"]

    assert len(formulas) >= 5
    native_p9 = [b for b in formulas if b.ocr_source == "pdf_native_math"]
    assert len(native_p9) == 1
    assert "W_i" in (native_p9[0].latex or "")
    assert r"\frac" in (native_p9[0].latex or "")

    assert len(captions) >= 1
    ocr_caps = [b for b in captions if b.ocr_source == "rapidocr_caption"]
    assert len(ocr_caps) >= 1
    cap_txt = "".join(inl.text for inl in ocr_caps[0].inlines if isinstance(inl, TextInline))
    assert "筒" in cap_txt and "盖" in cap_txt and "燃烧皿" in cap_txt

    assert len(figures) >= 4
    assert all(fig.image_render_mode == "outline" for fig in figures)

    md = docir_to_markdown(doc)
    assert "$$" in md
    assert "![diagram]" in md or "![" in md

    roundtrip = markdown_to_docir(md, doc, assets_dir=out_dir / "assets")
    assert len([b for b in roundtrip.blocks if b.type == "formula_block"]) == len(formulas)
    assert len([b for b in roundtrip.blocks if b.type == "figure"]) == len(figures)


def test_outline_default_vs_hatch_stroke_counts_and_float_wrap(tmp_path: Path) -> None:
    img_path = tmp_path / "diag.png"
    _sample_diagram(img_path)

    reg = WriterRegistry(ROOT / "fonts")
    reg.rescan()
    reader = reg.get(reg.active_writer_id or "lin_kaishu")

    out_strokes = vectorize_raster_image(img_path, [0, 0, 60, 40], render_mode="outline")
    assert len(out_strokes) > 0

    hatch_strokes = vectorize_raster_image(img_path, [0, 0, 60, 40], render_mode="hatch")
    assert len(hatch_strokes) > len(out_strokes)

    chart_obj = ChartData(chart_type="raster", image_path=str(img_path))
    cfg = LayoutConfig()
    assert cfg.chart.image_render_mode == "outline"

    s_outline = render_chart(
        chart_obj,
        bbox_mm=[20, 30, 90, 75],
        selector=None,
        config=cfg,
        block_id="b_fig",
        page_index=0,
    )
    s_hatch = render_chart(
        chart_obj,
        bbox_mm=[20, 30, 90, 75],
        selector=None,
        config=cfg,
        block_id="b_fig",
        page_index=0,
        render_mode="hatch",
    )
    assert len(s_hatch) > len(s_outline)

    # Floating image at [105, 22, 180, 65] forces reflow text onto left side without overlapping image box
    doc = DocIR(
        doc_id="doc_float",
        source=DocSource(type="text", filename="float.txt", sha256="x", parser="test"),
        pages=[DocPageInfo(page_index=0, width_mm=210, height_mm=297)],
        blocks=[
            DocBlock(
                block_id="p0-img",
                page_index=0,
                type="figure",
                reading_order=0,
                image_path=str(img_path),
                asset_name="diag.png",
                image_render_mode="outline",
                placement="float",
                float_box_mm=[105.0, 22.0, 180.0, 65.0],
                chart=chart_obj,
            ),
            DocBlock(
                block_id="p0-txt",
                page_index=0,
                type="paragraph",
                reading_order=1,
                inlines=[TextInline(text="这是一段用来测试自由浮动插图文字环绕与精确行距控制的实验说明文字。" * 6)],
            ),
        ],
    )
    pages_tight = compose_document(doc, reader, LayoutConfig(text=TextConfig(line_spacing_mm=5.0, paragraph_spacing_mm=1.0)))
    pages_loose = compose_document(doc, reader, LayoutConfig(text=TextConfig(line_spacing_mm=14.0, paragraph_spacing_mm=8.0)))
    assert len(pages_tight) >= 1
    assert any(pb.block_id == "p0-img" and pb.placement == "float" for pb in pages_tight[0].placed_blocks)
    opt_page = optimize_page(pages_tight[0], cfg.optimize)
    assert any(pb.block_id == "p0-img" and pb.placement == "float" for pb in opt_page.placed_blocks)

    txt_strokes_tight = [s for s in pages_tight[0].strokes if s.block_id == "p0-txt"]
    txt_strokes_loose = [s for s in pages_loose[0].strokes if s.block_id == "p0-txt"]
    assert txt_strokes_tight and txt_strokes_loose
    max_y_tight = max(s.pts[i] for s in txt_strokes_tight for i in range(1, len(s.pts), 2))
    max_y_loose = max(s.pts[i] for s in txt_strokes_loose for i in range(1, len(s.pts), 2))
    assert max_y_loose > max_y_tight + 5.0


def test_editor_endpoints_markdown_blocks_image_style_and_math_preview(tmp_path: Path) -> None:
    app = create_app(_make_settings(tmp_path))
    with TestClient(app) as client:
        r = client.post(
            "/api/v1/documents/text",
            json={"title": "编辑测试", "text": "# 标题一\n\n测试正文行距与公式 $x^2+y^2$。\n\n$$\nA = \\frac{R-C}{S-C}\n$$"},
        )
        assert r.status_code == 201
        doc_id = r.json()["doc_id"]

        # 1. Fetch Markdown and verify formula preserved
        r_md = client.get(f"/api/v1/documents/{doc_id}/markdown")
        assert r_md.status_code == 200
        md_text = r_md.json()["markdown"]
        assert "标题一" in md_text and "$$" in md_text

        # 2. Update Markdown and verify new block created + persisted
        r_put_md = client.put(
            f"/api/v1/documents/{doc_id}/markdown",
            json={"markdown": md_text + "\n新增结尾段落。\n"},
        )
        assert r_put_md.status_code == 200
        assert any(
            "新增结尾段落" in "".join((i.get("text") or "") for i in (b.get("inlines") or []))
            for b in r_put_md.json()["blocks"]
        )

        # 3. Upload inline asset & insert figure block via replaceDocumentBlocks, also testing path traversal rejection
        img_file = tmp_path / "inline.png"
        _sample_diagram(img_file)
        r_up = client.post(
            f"/api/v1/documents/{doc_id}/assets",
            files={"file": ("inline.png", img_file.read_bytes(), "image/png")},
        )
        assert r_up.status_code == 200
        asset_name = r_up.json()["asset_name"]

        blocks = r_put_md.json()["blocks"]
        blocks.append(
            {
                "block_id": "fig-1",
                "page_index": 0,
                "type": "figure",
                "reading_order": len(blocks),
                "level": 1,
                "asset_name": asset_name,
                "image_path": "/etc/passwd",  # Must be sanitized/rejected by backend!
                "image_render_mode": "outline",
                "placement": "inline",
            }
        )
        r_put_blk = client.put(f"/api/v1/documents/{doc_id}/blocks", json={"blocks": blocks})
        assert r_put_blk.status_code == 200
        fig_blk = next(b for b in r_put_blk.json()["blocks"] if b["block_id"] == "fig-1")
        assert "/etc/passwd" not in (fig_blk.get("image_path") or "")
        assert fig_blk["asset_name"] == asset_name

        # 4. Patch block float placement & apply global shading style
        r_patch = client.patch(
            f"/api/v1/documents/{doc_id}/blocks/fig-1",
            json={"placement": "float", "float_box_mm": [30, 40, 100, 90]},
        )
        assert r_patch.status_code == 200
        assert r_patch.json()["block"]["placement"] == "float"

        r_style = client.post(
            f"/api/v1/documents/{doc_id}/blocks/apply-image-style",
            json={"image_render_mode": "crosshatch"},
        )
        assert r_style.status_code == 200
        assert r_style.json()["updated_count"] == 1
        assert next(b for b in r_style.json()["blocks"] if b["block_id"] == "fig-1")["image_render_mode"] == "crosshatch"

        # 5. Live math preview endpoint
        r_math = client.post("/api/v1/math/preview", json={"latex": r"W_i(\%) = \frac{V_i C_i}{V_s \rho_s}"})
        assert r_math.status_code == 200
        assert r_math.json()["ok"] is True
        assert len(r_math.json()["strokes"]) > 0

        # 6. Create & read layout and confirm placed_blocks survive optimize_page in LayoutPageSummary
        r_ly = client.post("/api/v1/layouts", json={"doc_id": doc_id, "config": LayoutConfig().model_dump()})
        assert r_ly.status_code == 202
        ly_id = r_ly.json()["layout_id"]
        tid = r_ly.json()["task_id"]
        for _ in range(100):
            rt = client.get(f"/api/v1/tasks/{tid}")
            if rt.json()["state"] in ("done", "failed"):
                assert rt.json()["state"] == "done"
                break
        r_get_ly = client.get(f"/api/v1/layouts/{ly_id}")
        assert r_get_ly.status_code == 200
        all_placed = [pb for p in r_get_ly.json()["pages"] for pb in p.get("placed_blocks", [])]
        assert any(pb["block_type"] == "figure" and pb["block_id"] == "fig-1" for pb in all_placed)
        assert any(pb["block_type"] == "formula_block" for pb in all_placed)
