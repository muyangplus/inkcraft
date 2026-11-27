"""Regression tests covering blind-review P0/P1 fixes across SDK, API, GRBL, layout, and kits."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3
import sys
import time

from fastapi.testclient import TestClient
import fitz
import numpy as np
import pytest

from inkcraft.api.app import create_app
from inkcraft.api.schemas import (
    ComposedPage,
    MachineProfile,
    MachineState,
    PenConfig,
    StrokeItem,
)
from inkcraft.api.state import ApiError, AppContext
from inkcraft.config import Settings
from inkcraft.core.db import Database
from inkcraft.core.events import EventBus
from inkcraft.gcode.compiler import compile_page_gcode
from inkcraft.grbl.controller import MachineController
from inkcraft.layout.math_typesetter import typeset_math
from inkcraft.writers.selector import VariantSelector
from hwfont_sdk import HwFontMeta, HwFontReader, HwFontWriter, decode_strokes_full

ROOT = Path(__file__).resolve().parents[2]
DEMO_FONT = ROOT / "fonts" / "lin_kaishu.hwfont"

if str(ROOT / "colab_builder") not in sys.path:
    sys.path.insert(0, str(ROOT / "colab_builder"))
from hwbuilder.segment import CroppedGlyph, export_review_html


def _make_settings(tmp_path: Path) -> Settings:
    fonts_dir = tmp_path / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
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


def _encode_uvarint(n: int) -> bytes:
    buf = bytearray()
    while n >= 0x80:
        buf.append((n & 0x7F) | 0x80)
        n >>= 7
    buf.append(n)
    return bytes(buf)


def test_hwfont_sdk_oom_bounds_greek_symbol_and_missing_sha(tmp_path: Path) -> None:
    # 1. Oversized stroke point_count must fail fast before np.empty OOM
    malformed = b"HWS1\x00\x01" + _encode_uvarint(50_000_000) + b"\x00\x00\x00\x00"
    with pytest.raises(ValueError, match="Truncated HWS1"):
        decode_strokes_full(malformed)

    # Oversized stroke_count header check
    too_many_strokes = b"HWS1\x00\x41" + b"\x02\x00\x00\x00\x00"
    with pytest.raises(ValueError, match="Invalid HWS1 stroke_count"):
        decode_strokes_full(too_many_strokes)

    # 2. Greek + symbol counts both accumulate into coverage.symbol
    out = tmp_path / "greek_symbol.hwfont"
    writer = HwFontWriter(out, HwFontMeta(writer_name="GreekSymbolTest"))
    writer.add_variant("α", [np.array([[200, 300], [500, 700]])], source="scan")
    writer.add_variant("∑", [np.array([[200, 200], [700, 800]])], source="scan")
    writer.finalize()

    with HwFontReader(out) as reader:
        ok_rep = reader.verify()
        assert ok_rep.ok, ok_rep.errors
        assert reader.meta.coverage.symbol == 2

    # 3. Clearing or deleting content_sha256 fails verify()
    conn = sqlite3.connect(str(out))
    conn.execute("UPDATE meta SET value = '\"\"' WHERE key = 'content_sha256'")
    conn.commit()
    conn.close()

    with HwFontReader(out) as reader:
        bad_rep = reader.verify()
        assert not bad_rep.ok
        assert any("content_sha256" in err for err in bad_rep.errors)


def test_machine_controller_paper_change_allows_pen_and_frame_check(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.db")
    bus = EventBus()
    ctrl = MachineController(bus, db, mock_speed_multiplier=50.0)
    profile = MachineProfile(
        profile_id="test_paper_change",
        pen=PenConfig(mode="servo", dwell_ms=10),
    )
    ctrl.connect("MOCK", 115200, profile, mock=True)
    try:
        strokes = [
            StrokeItem(id=i, kind="text", pts=[10.0 + i * 2.0, 10.0, 10.0 + i * 2.0, 20.0])
            for i in range(4)
        ]
        p0 = ComposedPage(page_index=0, width_mm=210.0, height_mm=297.0, bbox=[10.0, 10.0, 20.0, 20.0], strokes=strokes)
        p1 = ComposedPage(page_index=1, width_mm=210.0, height_mm=297.0, bbox=[10.0, 10.0, 20.0, 20.0], strokes=strokes)
        ctrl.start_job(
            "job_pc",
            "ly_pc",
            {0: compile_page_gcode(p0, profile), 1: compile_page_gcode(p1, profile)},
            [0, 1],
            0,
        )

        deadline = time.monotonic() + 8.0
        while ctrl.machine_state != MachineState.PAPER_CHANGE and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ctrl.machine_state == MachineState.PAPER_CHANGE

        assert ctrl.set_pen("down")["pen"] == "down"
        assert ctrl.set_pen("up")["pen"] == "up"
        assert ctrl.machine_state == MachineState.PAPER_CHANGE

        ctrl.frame_check([10.0, 10.0, 30.0, 30.0])
        deadline = time.monotonic() + 5.0
        while ctrl.machine_state == MachineState.FRAMING and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ctrl.machine_state == MachineState.PAPER_CHANGE
    finally:
        ctrl.abort_job()
        ctrl.disconnect()
        db.close()


def test_path_traversal_rejections_and_background_routes(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    ctx = AppContext(settings)
    try:
        with pytest.raises((ApiError, ValueError)):
            ctx.doc_dir("../etc")
        with pytest.raises((ApiError, ValueError)):
            ctx.layout_dir("../etc")
    finally:
        ctx.shutdown()

    app = create_app(settings)
    with TestClient(app) as client:
        r_img = client.get("/api/v1/backgrounds/bad..id/image")
        assert r_img.status_code == 400
        r_del = client.delete("/api/v1/backgrounds/bad..id")
        assert r_del.status_code == 400


def test_document_detail_includes_is_builtin_and_page_image(tmp_path: Path) -> None:
    app = create_app(_make_settings(tmp_path))
    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Document Metadata Test", fontsize=14)
    doc.save(str(pdf_path))
    doc.close()

    with TestClient(app) as client:
        r_demo = client.get("/api/v1/documents/doc_demo")
        assert r_demo.status_code == 200
        assert r_demo.json()["is_builtin"] is True

        up = client.post(
            "/api/v1/documents",
            files={"file": ("sample.pdf", pdf_path.read_bytes(), "application/pdf")},
            data={"mode_hint": "overlay"},
        )
        assert up.status_code == 202
        up_body = up.json()
        doc_id = up_body["doc_id"]

        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            t = client.get(f"/api/v1/tasks/{up_body['task_id']}").json()
            if t["state"] == "done":
                break
            assert t["state"] != "failed", t
            time.sleep(0.05)

        det = client.get(f"/api/v1/documents/{doc_id}")
        assert det.status_code == 200
        body = det.json()
        assert body["is_builtin"] is False
        assert len(body["pages"]) >= 1
        assert body["pages"][0].get("image")


def test_math_typesetter_text_spaces_and_leading_neg_kern() -> None:
    with HwFontReader(DEMO_FONT) as reader:
        sel = VariantSelector(reader)
        spaced = typeset_math(
            r"\text{hello world}",
            sel,
            font_size_mm=6.0,
            rng=np.random.default_rng(1),
        )
        compact = typeset_math(
            r"\text{helloworld}",
            sel,
            font_size_mm=6.0,
            rng=np.random.default_rng(1),
        )
        assert spaced.width_mm > compact.width_mm

        neg = typeset_math(
            r"\!x",
            sel,
            font_size_mm=6.0,
            rng=np.random.default_rng(1),
        )
        assert neg.width_mm >= 0.0


def test_export_review_html_escapes_script_and_html_tags(tmp_path: Path) -> None:
    gray = np.full((16, 16), 240, dtype=np.uint8)
    binary = np.zeros((16, 16), dtype=bool)
    crop = CroppedGlyph(
        cell_id='c1"</script><img src=x onerror=alert(1)>',
        char="<",
        codepoint=ord("<"),
        page=1,
        row=0,
        col=0,
        repeat_index=0,
        gray=gray,
        binary=binary,
        ink_ratio=0.1,
        ink_pixels=25,
        flags=['<b>XSS</b></script>'],
        kept=True,
    )
    out_html = tmp_path / "review.html"
    export_review_html([crop], out_html, title='<script>bad</script>')
    content = out_html.read_text(encoding="utf-8")
    assert 'c1"</script><img' not in content
    assert "\\u003c/script\\u003e" in content
    assert "<script>bad</script>" not in content
    assert ".textContent =" in content


def test_package_windows_bundle_should_include_rules() -> None:
    spec = importlib.util.spec_from_file_location(
        "package_windows_bundle",
        ROOT / "scripts" / "package_windows_bundle.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.should_include(ROOT / "frontend" / "dist" / "index.html") is True
    assert mod.should_include(ROOT / "dist" / "inkcraft-windows-portable.zip") is False
    assert mod.should_include(ROOT / "source" / "scans" / "raw.jpg") is False
    assert mod.should_include(ROOT / "cuda_font_kit" / "train_font_cuda.py") is False
    assert mod.should_include(ROOT / "data" / "app.db") is False
