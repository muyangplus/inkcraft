"""End-to-end integration tests for FastAPI REST, WebSocket, Dual Font Builder, and SPA serving."""

from __future__ import annotations

import io
from pathlib import Path
import time
import zipfile

from fastapi.testclient import TestClient

from inkcraft.api.app import create_app
from inkcraft.config import Settings

ROOT = Path(__file__).resolve().parents[2]


def _make_test_settings(tmp_path: Path) -> Settings:
    fonts_dir = tmp_path / "fonts"
    fonts_dir.mkdir()
    for f in (ROOT / "fonts").glob("*.hwfont"):
        (fonts_dir / f.name).write_bytes(f.read_bytes())
    data_dir = tmp_path / "data"
    return Settings(
        root_dir=ROOT,
        fonts_dir=fonts_dir,
        data_dir=data_dir,
        db_path=data_dir / "app.db",
        profiles_path=ROOT / "config" / "default_profiles.json",
        frontend_dist_dir=ROOT / "frontend" / "dist",
    )


def _wait_task(client: TestClient, task_id: str, timeout_s: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = client.get(f"/api/v1/tasks/{task_id}")
        assert r.status_code == 200
        body = r.json()
        if body["state"] in ("done", "failed"):
            return body
        time.sleep(0.05)
    raise TimeoutError(f"Task {task_id} did not finish")


def test_full_end_to_end_workbench_and_dual_font_builder(tmp_path: Path) -> None:
    app = create_app(_make_test_settings(tmp_path))
    with TestClient(app) as client:
        # 1. Health + Built Frontend SPA served at /
        h = client.get("/api/v1/health")
        assert h.status_code == 200
        assert h.json()["contract_version"] == 1

        spa = client.get("/")
        assert spa.status_code == 200
        assert "<div id=\"root\">" in spa.text

        # 2. Multi-writer hot-swap + glyph inspector
        wr = client.get("/api/v1/writers").json()
        initial_writers = len(wr["writers"])
        assert initial_writers >= 3
        second_id = wr["writers"][1]["writer_id"]
        act = client.post("/api/v1/writers/active", json={"writer_id": second_id})
        assert act.status_code == 200
        assert act.json()["active_writer_id"] == second_id

        glyph = client.get(f"/api/v1/writers/{second_id}/glyphs/永?all_variants=1")
        assert glyph.status_code == 200
        assert len(glyph.json()["variants"]) >= 3

        # 3. Demo document + Compose Reflow + Float32 paths + G-code
        docs = client.get("/api/v1/documents").json()
        assert any(d["doc_id"] == "doc_demo" for d in docs["documents"])

        ly_resp = client.post(
            "/api/v1/layouts",
            json={"doc_id": "doc_demo", "writer_id": second_id},
        )
        assert ly_resp.status_code == 202
        ly_id = ly_resp.json()["layout_id"]
        t = _wait_task(client, ly_resp.json()["task_id"])
        assert t["state"] == "done"

        ly = client.get(f"/api/v1/layouts/{ly_id}").json()
        assert ly["page_count"] >= 2

        f32 = client.get(f"/api/v1/layouts/{ly_id}/pages/0/paths?format=f32")
        assert f32.status_code == 200
        assert len(f32.content) > 1000
        assert int(f32.headers["X-Stroke-Count"]) > 100

        gc = client.get(f"/api/v1/layouts/{ly_id}/pages/0/gcode")
        assert gc.status_code == 200
        assert "G1 " in gc.text

        # 4. Dual Font Builder: Capabilities + Sheets + Local Build + Cloud Colab Bundle
        caps = client.get("/api/v1/font-builder/capabilities")
        assert caps.status_code == 200
        cap_json = caps.json()
        mode_ids = {m["id"] for m in cap_json["modes"]}
        assert {"local_gpu", "local_cpu", "colab_cloud"}.issubset(mode_ids)

        sheet = client.post("/api/v1/font-builder/sheets", json={"preset": "quick", "grid_color": "cyan"})
        assert sheet.status_code == 200
        sheet_id = sheet.json()["sheet_id"]
        assert client.get(sheet.json()["pdf_url"]).headers["content-type"].startswith("application/pdf")

        build = client.post(
            "/api/v1/font-builder/build",
            data={
                "writer_name": "集成测试书写者",
                "writer_alias": "本机离线体",
                "engine": "local_cpu",
                "variants_per_char": "2",
                "target_preset": "quick",
                "demo_synthetic": "true",
                "sheet_id": sheet_id,
            },
        )
        assert build.status_code == 202
        bt = _wait_task(client, build.json()["task_id"], timeout_s=30.0)
        assert bt["state"] == "done", bt
        # Newly built writer is hot-loaded into registry
        wr_after = client.get("/api/v1/writers").json()
        assert len(wr_after["writers"]) == initial_writers + 1

        bundle = client.post(
            "/api/v1/font-builder/colab-bundle",
            data={"writer_name": "云端书写者", "sheet_id": sheet_id},
        )
        assert bundle.status_code == 200
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as zf:
            names = zf.namelist()
            assert any("02_scan_to_trajectories.ipynb" in n for n in names)
            assert any("03_train_and_export.ipynb" in n for n in names)

        # 5. Mock GRBL connect + WebSocket telemetry + Frame Check + E-Stop
        conn = client.post(
            "/api/v1/machine/connect",
            json={"port": "MOCK", "baud": 115200, "profile_id": "corexy_servo_a4", "mock": True},
        )
        assert conn.status_code == 200
        assert conn.json()["machine_state"] == "IDLE"

        with client.websocket_connect("/ws/telemetry") as ws:
            ws.send_json({"type": "ping", "data": {}})
            got_pong = False
            for _ in range(10):
                msg = ws.receive_json()
                if msg["type"] == "pong":
                    got_pong = True
                    break
            assert got_pong

            ws.send_json({"type": "estop", "data": {}})
            time.sleep(0.08)

        unlock = client.post("/api/v1/machine/unlock")
        assert unlock.status_code == 200
        assert unlock.json()["machine_state"] == "IDLE"
        client.post("/api/v1/machine/disconnect")


def test_backgrounds_presets_and_first_a_rest_b_rules(tmp_path: Path) -> None:
    from PIL import Image

    app = create_app(_make_test_settings(tmp_path))
    with TestClient(app) as client:
        # 1. Built-in backgrounds & custom upload
        bgs = client.get("/api/v1/backgrounds").json()["backgrounds"]
        bg_ids = {b["background_id"] for b in bgs}
        assert {"bg_letterhead_a", "bg_lined_9mm_b", "bg_lined_8mm", "bg_composition_grid"}.issubset(bg_ids)
        assert client.get("/api/v1/backgrounds/bg_letterhead_a/image").headers["content-type"] == "image/png"

        buf = io.BytesIO()
        Image.new("RGB", (400, 560), (250, 248, 240)).save(buf, format="PNG")
        up = client.post(
            "/api/v1/backgrounds",
            files={"file": ("my_cover_a.png", buf.getvalue(), "image/png")},
            data={"name": "我的自定义首页 A", "margin_top": "58"},
        )
        assert up.status_code == 201
        custom_bg_id = up.json()["background"]["background_id"]
        assert client.get(f"/api/v1/backgrounds/{custom_bg_id}/image").status_code == 200

        # 2. Built-in presets
        presets = client.get("/api/v1/layout/presets").json()["presets"]
        assert len(presets) >= 7
        preset_ab = next(p for p in presets if p["preset_id"] == "first_a_rest_b")

        # 3. Compose with Page 1 = Custom Background A (top=58mm, Writer 0) & Page 2+ = Background B (top=22mm, Writer 1)
        writers = client.get("/api/v1/writers").json()["writers"]
        cfg = preset_ab["config"]
        cfg["page_rules"]["first_page"]["background_id"] = custom_bg_id
        cfg["page_rules"]["first_page"]["margins_mm"]["top"] = 58.0
        cfg["page_rules"]["first_page"]["writer_id"] = writers[0]["writer_id"]
        cfg["page_rules"]["rest_pages"]["background_id"] = "bg_lined_9mm_b"
        cfg["page_rules"]["rest_pages"]["margins_mm"]["top"] = 22.0
        cfg["page_rules"]["rest_pages"]["writer_id"] = writers[1]["writer_id"]

        ly_resp = client.post("/api/v1/layouts", json={"doc_id": "doc_demo", "config": cfg})
        assert ly_resp.status_code == 202
        t = _wait_task(client, ly_resp.json()["task_id"])
        assert t["state"] == "done"

        ly = client.get(f"/api/v1/layouts/{ly_resp.json()['layout_id']}").json()
        assert ly["page_count"] >= 2
        p0, p1 = ly["pages"][0], ly["pages"][1]
        assert p0["background_id"] == custom_bg_id
        assert p0["writer_id"] == writers[0]["writer_id"]
        assert p0["bbox"][1] >= 54.0  # Page 1 text starts below 58mm letterhead!
        assert p1["background_id"] == "bg_lined_9mm_b"
        assert p1["writer_id"] == writers[1]["writer_id"]
        assert p1["bbox"][1] < 45.0   # Page 2 starts near 22mm top margin!

        # 4. Delete uploaded background
        dl = client.delete(f"/api/v1/backgrounds/{custom_bg_id}")
        assert dl.status_code == 200
        assert dl.json()["deleted"] is True
