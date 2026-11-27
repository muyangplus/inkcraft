"""REST flow for the native machine control scheme (MockGrbl)."""

from __future__ import annotations

from pathlib import Path
import time

from fastapi.testclient import TestClient

from inkcraft.api.app import create_app
from inkcraft.config import Settings

ROOT = Path(__file__).resolve().parents[2]


def _settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    return Settings(
        root_dir=ROOT,
        fonts_dir=ROOT / "fonts",
        data_dir=data_dir,
        db_path=data_dir / "app.db",
        profiles_path=ROOT / "config" / "default_profiles.json",
        frontend_dist_dir=ROOT / "frontend" / "dist",
    )


def test_machine_control_scheme_api(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        listing = client.get("/api/v1/machine/profiles").json()
        ids = [p["profile_id"] for p in listing["profiles"]]
        assert {"kx_grbl_stepper_z", "kx_grbl_laser"} <= set(ids)

        prof = next(p for p in listing["profiles"] if p["profile_id"] == "kx_grbl_stepper_z")
        prof["macros"] = [{"name": "回原点", "gcode": "G0 X0 Y0"}]
        saved = client.put("/api/v1/machine/profiles/kx_grbl_stepper_z", json=prof)
        assert saved.status_code == 200 and saved.json()["profile"]["macros"][0]["name"] == "回原点"

        r = client.post(
            "/api/v1/machine/connect",
            json={"port": "auto", "baud": 115200, "profile_id": "kx_grbl_stepper_z", "mock": True},
        )
        assert r.status_code == 200, r.text

        gs = client.get("/api/v1/machine/grbl-settings").json()
        assert any(s["key"] == "$100" for s in gs["settings"])

        w = client.put("/api/v1/machine/grbl-settings", json={"settings": {"$110": 4200}})
        assert w.status_code == 200, w.text
        assert w.json()["settings"]["$110"] == 4200
        bad = client.put("/api/v1/machine/grbl-settings", json={"settings": {"$abc": 1}})
        assert bad.status_code == 422

        assert client.post("/api/v1/machine/jog", json={"dx": 0, "dy": 0, "dz": 1.0}).status_code == 200
        busy = client.post("/api/v1/machine/macros/0/run")
        assert busy.status_code in (200, 409)  # 409 while the jog is still moving
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and app.state.ctx.machine.machine_state.value != "IDLE":
            time.sleep(0.05)
        m = client.post("/api/v1/machine/macros/0/run")
        assert m.status_code == 200, m.text
        assert client.post("/api/v1/machine/macros/5/run").status_code == 422

        assert client.post("/api/v1/machine/import/kvenjoy").status_code in (404, 405)
        client.post("/api/v1/machine/disconnect")
