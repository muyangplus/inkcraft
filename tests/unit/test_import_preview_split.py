"""API and service tests for pre-parse document preview, crop rects, multi-project split, rename & delete."""

from __future__ import annotations

import time
from pathlib import Path
import fitz
import pytest
from fastapi.testclient import TestClient

from inkcraft.api.app import create_app
from inkcraft.config import Settings

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


def _build_two_chapter_pdf(path: Path) -> bytes:
    doc = fitz.open()
    for title, body in [
        ("实验一 样品水分测定", "第一页正文：将样品放入烘箱恒重测定。"),
        ("实验一 数据记录", "第二页正文：计算含水率。"),
        ("实验二 灰分测定", "第三页正文：马弗炉灼烧测量残渣。"),
    ]:
        page = doc.new_page(width=595.28, height=841.89)
        page.insert_text((72, 42), "页眉：实验教学内部讲义", fontsize=9)
        page.insert_text((72, 95), title, fontsize=16)
        page.insert_text((72, 145), body, fontsize=11)
        page.insert_text((290, 815), "- 1 -", fontsize=9)
    raw = doc.tobytes()
    doc.close()
    path.write_bytes(raw)
    return raw


def _poll_task(client: TestClient, task_id: str) -> dict:
    for _ in range(120):
        r = client.get(f"/api/v1/tasks/{task_id}")
        assert r.status_code == 200
        data = r.json()
        if data["state"] == "done":
            return data
        if data["state"] == "failed":
            raise AssertionError(f"Task failed: {data}")
        time.sleep(0.1)
    raise AssertionError("Task polling timed out")


def test_preview_split_crop_rename_and_delete(tmp_path: Path) -> None:
    app = create_app(_make_settings(tmp_path))
    with TestClient(app) as client:
        pdf_bytes = _build_two_chapter_pdf(tmp_path / "chapters.pdf")

        # 1. Preview upload
        res = client.post(
            "/api/v1/documents/preview",
            files={"file": ("实验指导.pdf", pdf_bytes, "application/pdf")},
        )
        assert res.status_code == 200
        pv = res.json()
        preview_id = pv["preview_id"]
        assert pv["page_count"] == 3
        assert len(pv["pages"]) == 3
        assert pv["file_type"] == "pdf"

        # 2. Thumbnails (96 DPI & 150 DPI)
        t96 = client.get(f"/api/v1/documents/preview/{preview_id}/pages/0/thumb?dpi=96")
        assert t96.status_code == 200
        assert t96.headers["content-type"].startswith("image/jpeg")
        t150 = client.get(f"/api/v1/documents/preview/{preview_id}/pages/2/thumb?dpi=150")
        assert t150.status_code == 200
        assert len(t150.content) > 500

        # 3. Commit split into 2 projects + crop box + header/footer exclusion
        commit_res = client.post(
            f"/api/v1/documents/preview/{preview_id}/commit",
            json={
                "mode_hint": "reflow",
                "projects": [
                    {
                        "title": "项目A_实验一",
                        "page_indices": [0, 1],
                        "crop_rects_mm": {"0": [15.0, 28.0, 195.0, 260.0]},
                        "exclude_header_footer": True,
                    },
                    {
                        "title": "项目B_实验二",
                        "page_indices": [2],
                        "crop_rects_mm": {"2": [15.0, 28.0, 195.0, 260.0]},
                        "exclude_header_footer": True,
                    },
                ],
            },
        )
        assert commit_res.status_code == 202
        cdata = commit_res.json()
        assert len(cdata["documents"]) == 2
        doc_a_id = cdata["documents"][0]["doc_id"]
        doc_b_id = cdata["documents"][1]["doc_id"]
        assert doc_a_id != doc_b_id

        _poll_task(client, cdata["task_id"])

        doc_a = client.get(f"/api/v1/documents/{doc_a_id}").json()
        doc_b = client.get(f"/api/v1/documents/{doc_b_id}").json()
        assert doc_a["page_count"] == 2
        assert doc_b["page_count"] == 1

        # Header text inserted at y=42pt (~14.8mm) should be filtered out by exclude_header_footer / crop
        blocks_a = client.get(f"/api/v1/documents/{doc_a_id}/blocks").json()["blocks"]
        assert blocks_a

        # 4. Rename & Delete + builtin protection
        ren = client.patch(f"/api/v1/documents/{doc_a_id}", json={"filename": "重命名实验一.pdf"})
        assert ren.status_code == 200
        assert client.get(f"/api/v1/documents/{doc_a_id}").json()["source"]["filename"] == "重命名实验一.pdf"

        dele = client.delete(f"/api/v1/documents/{doc_a_id}")
        assert dele.status_code == 200
        assert client.get(f"/api/v1/documents/{doc_a_id}").status_code == 404

        demo_del = client.delete("/api/v1/documents/doc_demo")
        assert demo_del.status_code == 400


def test_sample_pdf_preview_detects_experiment_sections(tmp_path: Path) -> None:
    if not SAMPLE_PDF.is_file():
        pytest.skip("Sample PDF not present in workspace")
    app = create_app(_make_settings(tmp_path))
    with TestClient(app) as client:
        res = client.post(
            "/api/v1/documents/preview",
            files={"file": (SAMPLE_PDF.name, SAMPLE_PDF.read_bytes(), "application/pdf")},
        )
        assert res.status_code == 200
        pv = res.json()
        assert pv["page_count"] >= 8
        titles = [s["title"] for s in pv["detected_sections"]]
        assert len(titles) >= 2
        assert any("实验" in t for t in titles)

        cancel_res = client.delete(f"/api/v1/documents/preview/{pv['preview_id']}")
        assert cancel_res.status_code == 200
