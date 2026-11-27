"""Unit and API tests for decimal/negative custom line spacing and major_outline image vectorization."""

from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient

from inkcraft.api.app import create_app
from inkcraft.api.schemas import ChartConfig, LayoutConfig, PageRuleOverride, TextConfig, WritingRegion
from inkcraft.config import Settings
from inkcraft.docparse.chart_extract import vectorize_raster_image
from inkcraft.docparse.docir import DocBlock, DocIR, DocPageInfo, DocSource, TextInline
from inkcraft.docparse.markdown_codec import docir_to_markdown, markdown_to_docir
from inkcraft.layout.composer import compose_document
from inkcraft.writers.registry import WriterRegistry

ROOT = Path(__file__).resolve().parents[2]
DEMO_FONT = ROOT / "fonts" / "lin_kaishu.hwfont"


def _get_reader():
    reg = WriterRegistry(ROOT / "fonts")
    reg.rescan()
    return reg.get("lin_kaishu") or (reg.get(reg.active_writer_id) if reg.active_writer_id else None)


def test_decimal_and_negative_line_and_paragraph_spacing() -> None:
    reader = _get_reader()
    assert reader is not None

    # Schema accepts arbitrary decimals & negatives across global, page_rule, and region
    region = WritingRegion(
        region_id="r1",
        line_spacing=-0.25,
        line_spacing_mm=-1.85,
        paragraph_spacing_mm=-2.4,
    )
    assert region.line_spacing == -0.25
    rule = PageRuleOverride(line_spacing=0.45, line_spacing_mm=3.75, paragraph_spacing_mm=-1.5)
    assert rule.line_spacing_mm == 3.75

    doc = DocIR(
        doc_id="doc_spacing",
        source=DocSource(type="text", filename="sp.txt", sha256="x", parser="test"),
        pages=[DocPageInfo(page_index=0, width_mm=210, height_mm=297)],
        blocks=[
            DocBlock(
                block_id="p0",
                page_index=0,
                type="paragraph",
                reading_order=0,
                inlines=[TextInline(text="第一段文字用于测试自由行间距与紧缩小数和负数排版效果。" * 4)],
            ),
            DocBlock(
                block_id="p1",
                page_index=0,
                type="paragraph",
                reading_order=1,
                inlines=[TextInline(text="第二段文字接续测试负段间距不会超出纸张上边界。" * 3)],
            ),
        ],
    )

    def _y_span(cfg: LayoutConfig) -> tuple[float, float]:
        pages = compose_document(doc, reader, cfg)
        assert len(pages) == 1
        ys = [s.pts[i] for s in pages[0].strokes for i in range(1, len(s.pts), 2)]
        assert ys
        return min(ys), max(ys)

    _, max_default = _y_span(LayoutConfig(text=TextConfig(font_size_mm=6.0, line_spacing=1.5)))
    min_dec, max_dec = _y_span(
        LayoutConfig(text=TextConfig(font_size_mm=6.0, line_spacing_mm=4.25, paragraph_spacing_mm=0.5))
    )
    min_neg, max_neg = _y_span(
        LayoutConfig(text=TextConfig(font_size_mm=6.0, line_spacing_mm=-2.65, paragraph_spacing_mm=-1.5))
    )
    _, max_neg_ratio = _y_span(
        LayoutConfig(text=TextConfig(font_size_mm=6.0, line_spacing=-0.45, paragraph_spacing_mm=-1.2))
    )

    assert min_dec >= 18.0
    assert min_neg >= 18.0
    assert max_dec < max_default - 8.0
    # -2.65 mm on 6mm font -> 3.35mm pitch < 4.25mm fixed decimal pitch < 4.32mm old 0.72 floor!
    assert max_neg < max_dec
    assert max_neg_ratio < max_dec


def test_major_outline_strips_dense_lines_and_api_roundtrips(tmp_path: Path) -> None:
    img_path = tmp_path / "dense_fig.png"
    im = Image.new("L", (240, 180), 255)
    draw = ImageDraw.Draw(im)
    # Outer housing boundary
    draw.rectangle((20, 20, 220, 160), outline=0, width=4)
    # Major interior chamber
    draw.ellipse((80, 50, 160, 130), outline=0, width=3)
    # Dense hatch/grid lines inside + micro specks (must be aggressively suppressed!)
    for gx in range(28, 76, 4):
        draw.line((gx, 28, gx, 152), fill=30, width=1)
    for gy in range(28, 152, 4):
        draw.line((165, gy, 212, gy), fill=30, width=1)
    im.save(img_path)

    bbox = [20.0, 20.0, 110.0, 88.0]
    outline_strokes = vectorize_raster_image(img_path, bbox, ChartConfig(), render_mode="outline")
    major_strokes = vectorize_raster_image(img_path, bbox, ChartConfig(), render_mode="major_outline")
    hatch_strokes = vectorize_raster_image(img_path, bbox, ChartConfig(), render_mode="hatch")

    assert len(major_strokes) > 0
    assert len(major_strokes) < len(outline_strokes)
    assert len(major_strokes) * 2 < len(hatch_strokes)

    # REST API + Markdown roundtrip supports major_outline
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
        r = client.post("/api/v1/documents/text", json={"title": "主轮廓图测试", "text": "正文测试"})
        assert r.status_code == 201
        doc_id = r.json()["doc_id"]

        r_up = client.post(
            f"/api/v1/documents/{doc_id}/assets",
            files={"file": ("dense.png", img_path.read_bytes(), "image/png")},
        )
        assert r_up.status_code == 200
        asset_name = r_up.json()["asset_name"]

        blocks = client.get(f"/api/v1/documents/{doc_id}/blocks").json()["blocks"]
        blocks.append(
            {
                "block_id": "fig-major",
                "page_index": 0,
                "type": "figure",
                "reading_order": len(blocks),
                "level": 1,
                "asset_name": asset_name,
                "image_render_mode": "outline",
                "placement": "inline",
            }
        )
        client.put(f"/api/v1/documents/{doc_id}/blocks", json={"blocks": blocks})

        r_style = client.post(
            f"/api/v1/documents/{doc_id}/blocks/apply-image-style",
            json={"image_render_mode": "major_outline"},
        )
        assert r_style.status_code == 200
        assert "mode=major_outline" in r_style.json()["markdown"]
        fig = next(b for b in r_style.json()["blocks"] if b["block_id"] == "fig-major")
        assert fig["image_render_mode"] == "major_outline"

        md = r_style.json()["markdown"]
        r_rt = client.put(f"/api/v1/documents/{doc_id}/markdown", json={"markdown": md})
        assert r_rt.status_code == 200
        rt_fig = next(b for b in r_rt.json()["blocks"] if b["block_id"] == "fig-major")
        assert rt_fig["image_render_mode"] == "major_outline"
