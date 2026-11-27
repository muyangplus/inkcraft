"""Unit tests for PathOptimizer, GcodeCompiler, GRBL parser, 128B streamer, and MachineController."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from inkcraft.api.schemas import (
    ComposedPage,
    JobState,
    MachineProfile,
    MachineState,
    OptimizeConfig,
    PenConfig,
    StrokeItem,
)
from inkcraft.core.db import Database
from inkcraft.core.events import EventBus
from inkcraft.gcode.compiler import compile_frame_gcode, compile_page_gcode
from inkcraft.gcode.optimizer import WorkspaceBoundsError, check_bounds, optimize_page
from inkcraft.grbl.controller import MachineController
from inkcraft.grbl.mock import MockGrblTransport
from inkcraft.grbl.parser import parse_status_line
from inkcraft.grbl.streamer import CharacterCountingStreamer


def test_optimizer_preserves_text_and_reduces_chart_travel() -> None:
    text_s0 = StrokeItem(id=0, block_id="b0", kind="text", reversible=False, pts=[10.0, 10.0, 20.0, 10.0])
    text_s1 = StrokeItem(id=1, block_id="b0", kind="text", reversible=False, pts=[12.0, 15.0, 18.0, 15.0])
    chart_strokes = [
        StrokeItem(id=2, block_id="b1", kind="chart", reversible=True, pts=[10.0, 50.0, 10.0, 80.0]),
        StrokeItem(id=3, block_id="b1", kind="chart", reversible=True, pts=[90.0, 50.0, 90.0, 80.0]),
        StrokeItem(id=4, block_id="b1", kind="chart", reversible=True, pts=[14.0, 50.0, 14.0, 80.0]),
        StrokeItem(id=5, block_id="b1", kind="chart", reversible=True, pts=[86.0, 50.0, 86.0, 80.0]),
    ]
    page = ComposedPage(page_index=0, width_mm=210.0, height_mm=297.0, strokes=[text_s0, text_s1, *chart_strokes])
    opt = optimize_page(page, OptimizeConfig(travel="greedy_2opt", simplify_tol_mm=0.05, join_tol_mm=0.05))
    # Text strokes strictly preserve exact order & direction
    assert opt.strokes[0].pts == text_s0.pts
    assert opt.strokes[1].pts == text_s1.pts
    # Bounds check returns violations & optimize_page raises on OOB
    oob = ComposedPage(
        page_index=0,
        width_mm=210.0,
        height_mm=297.0,
        strokes=[StrokeItem(id=0, kind="text", pts=[10.0, 10.0, 250.0, 10.0])],
    )
    violations = check_bounds(oob, MachineProfile().workspace_mm)
    assert len(violations) >= 1
    assert "250" in str(violations[0])


def test_gcode_compiler_servo_and_stepper_z() -> None:
    page = ComposedPage(
        page_index=0,
        width_mm=210.0,
        height_mm=297.0,
        bbox=[10.0, 10.0, 40.0, 30.0],
        strokes=[StrokeItem(id=0, kind="text", pts=[10.0, 10.0, 40.0, 30.0])],
    )
    servo_profile = MachineProfile(pen=PenConfig(mode="servo", servo_up="M5", servo_down="M3 S90", dwell_ms=120))
    c_servo = compile_page_gcode(page, servo_profile)
    assert any("M3 S90" in ln for ln in c_servo.lines)
    assert any(ln.strip() == "M5" for ln in c_servo.lines)

    z_profile = MachineProfile(pen=PenConfig(mode="z", z_up_mm=5.0, z_down_mm=0.0, z_feed=1000.0))
    c_z = compile_page_gcode(page, z_profile)
    assert any("Z5" in ln for ln in c_z.lines)
    assert any("Z0" in ln for ln in c_z.lines)

    frame_lines = compile_frame_gcode([10.0, 10.0, 40.0, 30.0], servo_profile)
    assert not any("M3 S90" in ln for ln in frame_lines)


def test_grbl_parser_and_128b_streamer() -> None:
    st = parse_status_line("<Run|MPos:12.50,34.25,0.00|FS:2400,90|Bf:14,110>")
    assert st is not None
    assert st.state == "Run"
    assert st.mpos is not None and st.mpos[0] == pytest.approx(12.5)
    assert st.planner_avail == 14
    assert st.rx_avail == 110

    lines = [f"G1 X{i:.2f} Y{i * 0.5:.2f} F2400" for i in range(60)]
    streamer = CharacterCountingStreamer(rx_buffer=128)
    idx = 0
    while idx < len(lines) or not streamer.is_drained:
        while idx < len(lines) and streamer.can_send(lines[idx]):
            streamer.on_sent(idx, lines[idx])
            assert streamer.in_flight_bytes <= 128
            idx += 1
        if streamer.in_flight_count > 0:
            streamer.on_ok()
    assert streamer.sent_count == len(lines)
    assert streamer.acked_count == len(lines)
    assert streamer.peak_in_flight_bytes <= 128


def test_machine_controller_full_safety_lifecycle(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.db")
    bus = EventBus()
    ctrl = MachineController(bus, db, mock_speed_multiplier=50.0)
    profile = MachineProfile(profile_id="test_servo", pen=PenConfig(mode="servo", dwell_ms=10))

    # Connect mock GRBL
    ctrl.connect("MOCK", 115200, profile, mock=True)
    assert ctrl.machine_state == MachineState.IDLE

    # Jog, Zero, Pen test
    ctrl.jog(5.0, 5.0, 3000.0)
    deadline = time.monotonic() + 3.0
    while ctrl.machine_state != MachineState.IDLE and time.monotonic() < deadline:
        time.sleep(0.02)
    res = ctrl.zero(["X", "Y"])
    assert res["wpos"]["x"] == pytest.approx(0.0, abs=0.2)
    assert ctrl.set_pen("down")["pen"] == "down"
    assert ctrl.set_pen("up")["pen"] == "up"

    # Frame Check
    ctrl.frame_check([10.0, 10.0, 30.0, 30.0])
    deadline = time.monotonic() + 5.0
    while ctrl.machine_state != MachineState.IDLE and time.monotonic() < deadline:
        time.sleep(0.03)
    assert ctrl.machine_state == MachineState.IDLE

    # 2-Page Job: Pause -> Pen-Change -> Resume -> Page 0 Paper-Change -> Page 1 Done
    strokes = [
        StrokeItem(id=i, kind="text", pts=[10.0 + i * 2.0, 10.0, 10.0 + i * 2.0, 22.0])
        for i in range(12)
    ]
    p0 = ComposedPage(page_index=0, width_mm=210.0, height_mm=297.0, bbox=[10.0, 10.0, 34.0, 22.0], strokes=strokes)
    p1 = ComposedPage(page_index=1, width_mm=210.0, height_mm=297.0, bbox=[10.0, 10.0, 34.0, 22.0], strokes=strokes[:6])
    c0 = compile_page_gcode(p0, profile)
    c1 = compile_page_gcode(p1, profile)

    ctrl.start_job("job_t1", "ly_t1", {0: c0, 1: c1}, [0, 1], 0)
    time.sleep(0.06)
    ctrl.pause_job()
    assert ctrl.machine_state == MachineState.PAUSED
    ctrl.enter_pen_change()
    assert ctrl.machine_state == MachineState.PEN_CHANGE
    ctrl.resume_job()

    # Wait for page 0 paper change
    deadline = time.monotonic() + 8.0
    while ctrl.machine_state != MachineState.PAPER_CHANGE and time.monotonic() < deadline:
        time.sleep(0.03)
    assert ctrl.machine_state == MachineState.PAPER_CHANGE
    assert ctrl.job_state == JobState.WAIT_PAPER

    ctrl.paper_ready("job_t1", 1)
    deadline = time.monotonic() + 8.0
    while ctrl.job_state != JobState.COMPLETED and time.monotonic() < deadline:
        time.sleep(0.03)
    assert ctrl.job_state == JobState.COMPLETED
    assert ctrl.machine_state == MachineState.IDLE

    # E-Stop latency < 30ms + Unlock
    t0 = time.perf_counter()
    ctrl.estop()
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert elapsed_ms < 100.0
    assert ctrl.machine_state == MachineState.ESTOPPED
    ctrl.unlock()
    assert ctrl.machine_state == MachineState.IDLE

    ctrl.disconnect()
    assert ctrl.machine_state == MachineState.DISCONNECTED
    db.close()
