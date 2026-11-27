"""Native 奎享-style GRBL control scheme: coordinates, pen modes, timing, streaming, firmware."""

from __future__ import annotations

import json
from pathlib import Path
import time

import numpy as np
import pytest

from inkcraft.api.schemas import (
    ComposedPage,
    MachineMacro,
    MachineProfile,
    MachineState,
    PenConfig,
    StrokeItem,
    Vec2,
)
from inkcraft.core.db import Database
from inkcraft.core.events import EventBus
from inkcraft.docparse.service import decode_text_bytes
from inkcraft.gcode.compiler import compile_page_gcode, pen_down_commands, pen_up_commands, split_custom_gcode
from inkcraft.grbl.controller import MachineController
from inkcraft.grbl.parser import parse_status_line
from inkcraft.grbl.streamer import CharacterCountingStreamer
from inkcraft.machine.geometry import (
    machine_bounds,
    machine_to_page,
    page_delta_to_machine,
    page_to_machine,
)
from inkcraft.machine.grbl_settings import check_settings, parse_settings, report_scale
from inkcraft.machine.ports import pick_serial_port

ROOT = Path(__file__).resolve().parents[2]


def _builtin(profile_id: str) -> MachineProfile:
    raw = json.loads((ROOT / "config" / "default_profiles.json").read_text(encoding="utf-8"))
    return MachineProfile(**next(p for p in raw if p["profile_id"] == profile_id))


def _page(*pts: float, w: float = 200.0, h: float = 280.0) -> ComposedPage:
    return ComposedPage(page_index=0, width_mm=w, height_mm=h, strokes=[StrokeItem(id=0, pts=list(pts))])


# ---------------------------------------------------------------------------
# Coordinate model
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("origin", ["top_left", "top_right", "bottom_left", "bottom_right"])
@pytest.mark.parametrize("x_axis", ["auto", "right", "left"])
@pytest.mark.parametrize("y_axis", ["auto", "down", "up"])
@pytest.mark.parametrize("swap", [False, True])
@pytest.mark.parametrize("rot", [0.0, 3.5])
def test_page_machine_roundtrip(origin: str, x_axis: str, y_axis: str, swap: bool, rot: float) -> None:
    prof = MachineProfile(
        origin=origin, x_axis=x_axis, y_axis=y_axis, swap_xy=swap, rotation_deg=rot,
        invert_x=True, offset_mm=Vec2(x=1.5, y=-2.0),
    )
    for x, y in ((0.0, 0.0), (12.3, 45.6), (175.0, 226.0)):
        mx, my = page_to_machine(x, y, 175.0, 226.0, prof)
        assert machine_to_page(mx, my, 175.0, 226.0, prof) == pytest.approx((x, y), abs=1e-9)


def test_legacy_profiles_unchanged() -> None:
    assert page_to_machine(10, 20, 210, 297, MachineProfile(origin="top_left")) == (10, 20)
    assert page_to_machine(10, 20, 210, 297, MachineProfile(origin="bottom_left")) == (10, 277)
    assert page_to_machine(10, 20, 210, 297, MachineProfile(origin="bottom_left", invert_y=True)) == (10, 20)
    assert page_to_machine(10, 20, 210, 297, MachineProfile(invert_x=True)) == (200, 20)


def test_rotation_about_page_centre() -> None:
    prof = MachineProfile(rotation_deg=90.0)
    cx, cy = page_to_machine(100.0, 140.0, 200.0, 280.0, prof)
    assert (cx, cy) == pytest.approx((100.0, 140.0))  # centre is fixed
    x, y = page_to_machine(110.0, 140.0, 200.0, 280.0, prof)
    assert (x, y) == pytest.approx((100.0, 150.0))  # clockwise on paper (y down)


def test_kx_left_up_frame() -> None:
    prof = _builtin("kx_grbl_stepper_z")
    # origin top-left, standard GRBL axes: writing down the page runs in -Y
    assert page_to_machine(30.0, 50.0, 175.0, 226.0, prof) == (30.0, -50.0)
    assert page_delta_to_machine(0.0, 1.0, prof) == (0.0, -1.0)  # jog ↓
    assert page_delta_to_machine(1.0, 0.0, prof) == (1.0, 0.0)  # jog →
    x0, y0, x1, y1 = machine_bounds(prof)
    assert (x0, x1) == (0.0, prof.workspace_mm.x)
    assert (y0, y1) == (-prof.workspace_mm.y, 0.0)


# ---------------------------------------------------------------------------
# Pen modes, timing and G-code
# ---------------------------------------------------------------------------


def test_kx_builtin_profile_uses_factory_defaults() -> None:
    prof = _builtin("kx_grbl_stepper_z")
    assert prof.port == "auto"
    assert (prof.pen.mode, prof.pen.z_up_mm, prof.pen.z_down_mm, prof.pen.z_feed) == ("z", 0.0, 2.0, 3000.0)
    assert (prof.pen.down_delay_ms, prof.pen.up_delay_ms) == (200, 200)
    assert (prof.feed_draw, prof.jog_feed) == (1500.0, 2500.0)
    assert prof.auto_zero_on_start and not prof.sleep_after_job
    assert prof.grbl_expected == {}


def test_pen_delays_order() -> None:
    prof = MachineProfile(pen=PenConfig(mode="z", z_up_mm=0, z_down_mm=2, z_feed=3000, dwell_ms=50,
                                        down_delay_ms=200, up_delay_ms=300))
    assert pen_down_commands(prof) == ["G1 Z2 F3000", "G4 P0.25"]  # settle + after-touch pause
    assert pen_up_commands(prof) == ["G4 P0.3", "G0 Z0", "G4 P0.05"]  # pause before lift
    assert pen_up_commands(prof, include_dwell=False) == ["G0 Z0"]  # safety lifts never wait


def test_laser_mode_and_custom_gcode() -> None:
    prof = _builtin("kx_grbl_laser").model_copy(update={"start_gcode": "M8;g4 p0.1", "end_gcode": "M9"})
    g = compile_page_gcode(_page(10.0, 10.0, 20.0, 30.0), prof)
    assert "M3 S1000" in g.lines and g.lines.count("M5") >= 2
    assert "G0 X10 Y-10 F3000" in g.lines and "G1 X20 Y-30 F1500" in g.lines
    assert "M8" in g.lines and "G4 P0.1" in g.lines and "M9" in g.lines
    assert split_custom_gcode("M3 S0 (comment);\n\nG4 P1") == ["M3 S0", "G4 P1"]
    codes = [w["code"] for w in check_settings(prof, {32: 0.0})]
    assert "GRBL_LASER_MODE_OFF" in codes


def test_stepper_where_plus_z_lowers_the_pen() -> None:
    prof = _builtin("kx_grbl_stepper_z")
    g = compile_page_gcode(_page(5.0, 5.0, 6.0, 6.0), prof)
    assert g.lines.index("G1 Z2 F3000") > g.lines.index("G0 X5 Y-5 F3000")
    assert "G0 Z0" in g.lines


# ---------------------------------------------------------------------------
# Streaming, legacy GRBL, firmware settings, ports, text encoding
# ---------------------------------------------------------------------------


def test_line_by_line_streaming() -> None:
    s = CharacterCountingStreamer(rx_buffer=128, max_lines=1)
    assert s.can_send("G1 X1")
    s.on_sent(0, "G1 X1")
    assert not s.can_send("G1 X2")  # 单步: wait for ok
    s.on_ok()
    assert s.can_send("G1 X2")
    fast = CharacterCountingStreamer(rx_buffer=128)
    fast.on_sent(0, "G1 X1")
    assert fast.can_send("G1 X2")


def test_legacy_grbl09_status() -> None:
    st = parse_status_line("<Idle,MPos:1.000,-2.500,0.000,WPos:0.500,-2.500,0.000,Buf:0,RX:0>")
    assert st is not None and st.state == "Idle"
    assert st.mpos == (1.0, -2.5, 0.0) and st.wpos == (0.5, -2.5, 0.0)
    st11 = parse_status_line("<Run|MPos:1.000,2.000,3.000|FS:500,0>")
    assert st11 is not None and st11.mpos == (1.0, 2.0, 3.0) and st11.feed == 500.0


def test_grbl_settings_checks() -> None:
    s = parse_settings(["$13=1", "$32=1", "$100=80.000", "junk", "$101=150"])
    assert report_scale(s) == 25.4
    prof = MachineProfile(pen=PenConfig(mode="z"), grbl_expected={"$101": 160})
    codes = [w["code"] for w in check_settings(prof, s)]
    assert "GRBL_SETTING_MISMATCH" in codes
    assert "GRBL_LASER_MODE" not in codes  # harmless for a Z-stepper pen
    servo = MachineProfile(pen=PenConfig(mode="servo"))
    assert "GRBL_LASER_MODE" in [w["code"] for w in check_settings(servo, s)]


def test_pick_serial_port_prefers_ch340() -> None:
    ports = [
        {"device": "COM1", "description": "通信端口", "vid": None},
        {"device": "COM7", "description": "Bluetooth 链接上的标准串行", "vid": None},
        {"device": "COM12", "description": "USB-SERIAL CH340 (COM12)", "vid": 0x1A86, "pid": 0x7523},
        {"device": "COM3", "description": "Silicon Labs CP210x", "vid": 0x10C4},
    ]
    assert pick_serial_port(ports) == "COM12"
    assert pick_serial_port([{"device": "COM1", "description": "通信端口", "vid": None}]) is None


def test_decode_gbk_text() -> None:
    assert decode_text_bytes("书写测试\n".encode("gbk")) == "书写测试\n"
    assert decode_text_bytes("﻿书写".encode("utf-8")) == "书写"


# ---------------------------------------------------------------------------
# Controller against MockGrbl
# ---------------------------------------------------------------------------


def _wait_idle(ctrl: MachineController, timeout: float = 4.0) -> None:
    deadline = time.monotonic() + timeout
    while ctrl.machine_state != MachineState.IDLE and time.monotonic() < deadline:
        time.sleep(0.02)
    time.sleep(0.15)


@pytest.fixture()
def kx_ctrl(tmp_path: Path):
    ctrl = MachineController(EventBus(), Database(tmp_path / "a.db"), mock_speed_multiplier=50.0)
    prof = _builtin("kx_grbl_stepper_z").model_copy(
        update={
            "grbl_expected": {"$13": 1},  # mock firmware reports in inches
            "macros": [MachineMacro(name="回原点", gcode="G0 X0 Y0")],
        }
    )
    ctrl.connect("MOCK", 115200, prof, mock=True)
    yield ctrl
    ctrl.disconnect()


def test_controller_inch_reports_page_jog_and_z_pen(kx_ctrl: MachineController) -> None:
    ctrl = kx_ctrl
    assert ctrl.get_status_snapshot()["report_inches"] is True
    assert ctrl.get_status_snapshot()["pen"] == "up"

    ctrl.jog(10.0, 20.0)  # page: right 10, down 20
    _wait_idle(ctrl)
    ctrl._query_status_sync(timeout=0.5)
    snap = ctrl.get_status_snapshot()
    assert snap["wpos"]["x"] == pytest.approx(10.0, abs=0.05)
    assert snap["wpos"]["y"] == pytest.approx(-20.0, abs=0.05)
    assert snap["page_pos"]["y"] == pytest.approx(20.0, abs=0.05)

    assert ctrl.set_pen("down")["pen"] == "down"
    ctrl._query_status_sync(timeout=0.5)
    assert ctrl.get_status_snapshot()["pen"] == "down"
    assert ctrl.set_pen("up")["pen"] == "up"

    with pytest.raises(ValueError):
        ctrl.jog(0.0, -50.0)  # above the paper top: outside the workspace


def test_controller_z_jog_macro_and_firmware_write(kx_ctrl: MachineController) -> None:
    ctrl = kx_ctrl
    ctrl.jog(0.0, 0.0, dz=1.5)
    _wait_idle(ctrl)
    ctrl._query_status_sync(timeout=0.5)
    assert ctrl.get_status_snapshot()["wpos"]["z"] == pytest.approx(1.5, abs=0.05)

    ctrl.jog(5.0, 5.0)
    _wait_idle(ctrl)
    res = ctrl.run_macro(0)
    assert res["lines"] == ["G0 X0 Y0"]
    ctrl._query_status_sync(timeout=0.5)
    assert ctrl.get_status_snapshot()["wpos"]["x"] == pytest.approx(0.0, abs=0.05)
    with pytest.raises(ValueError):
        ctrl.run_macro(3)

    out = ctrl.write_grbl_settings({"$13": 0, "110": 4000})
    assert out["written"] == ["$13=0", "$110=4000"]
    assert ctrl.grbl_settings[13] == 0.0 and ctrl.grbl_settings[110] == 4000.0
    assert ctrl.get_status_snapshot()["report_inches"] is False
    with pytest.raises(ValueError):
        ctrl.write_grbl_settings({"$x": 1})


def test_controller_legacy_jog_and_line_mode(tmp_path: Path) -> None:
    ctrl = MachineController(EventBus(), Database(tmp_path / "b.db"), mock_speed_multiplier=50.0)
    prof = _builtin("kx_grbl_stepper_z").model_copy(update={"legacy_grbl": True, "stream_mode": "line"})
    ctrl.connect("MOCK", 115200, prof, mock=True)
    try:
        assert ctrl.jog(3.0, 4.0)["legacy"] is True  # G91 G1 … / G90 instead of $J=
        _wait_idle(ctrl)
        ctrl._query_status_sync(timeout=0.5)
        assert ctrl.get_status_snapshot()["wpos"]["y"] == pytest.approx(-4.0, abs=0.05)
        assert ctrl.streamer.max_lines == 1
    finally:
        ctrl.disconnect()


# ---------------------------------------------------------------------------
# Writer mix (多字体按概率混写)
# ---------------------------------------------------------------------------


def test_mixed_selector_uses_all_writers() -> None:
    from hwfont_sdk.reader import HwFontReader

    from inkcraft.writers.selector import MixedVariantSelector, VariantSelector

    fonts = [f for f in sorted((ROOT / "fonts").glob("*.hwfont")) if not f.name.startswith("personal")][:2]
    readers = [HwFontReader(f) for f in fonts]
    sample = next(
        ch for ch in "的一是不了人我在有他这中大来上国个到说们为子和你地出道也时年得就那要下以生会自着去之过家学对可"
        if all(r.variants(ch) for r in readers)
    )
    members = [(VariantSelector(r), 50.0, float(r.meta.units_per_em), float(r.meta.baseline_y)) for r in readers]
    mixed = MixedVariantSelector(members)
    rng = np.random.default_rng(7)
    seen = set()
    for _ in range(60):
        g = mixed.select(sample, rng)
        assert g is not None and g.strokes
        seen.add(tuple(np.round(g.strokes[0][0], 3)))
    assert len(seen) >= 2
    assert isinstance(mixed.clone(), MixedVariantSelector)
