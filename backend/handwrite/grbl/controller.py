"""MachineController: full 13-state MachineState & 9-state JobState GRBL orchestrator."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Literal

from handwrite.api.schemas import ComposedPage
from handwrite.core.db import Database
from handwrite.core.events import EventBus
from handwrite.gcode.compiler import (
    compile_frame_gcode,
    map_page_to_machine,
    pen_down_commands,
    pen_up_commands,
)
from handwrite.grbl.controller_io import _ControllerIOMixin
from handwrite.grbl.controller_jobs import _ControllerJobsMixin
from handwrite.grbl.controller_types import (
    ActiveJobContext,
    JobState,
    MachineProfile,
    MachineState,
    MachineStateError,
    Vec3,
    _ActiveJob,
)
from handwrite.grbl.mock import MockGrblTransport
from handwrite.grbl.streamer import CharacterCountingStreamer
from handwrite.grbl.transport import PySerialTransport, SerialTransport, list_serial_ports

logger = logging.getLogger(__name__)


class MachineController(_ControllerJobsMixin, _ControllerIOMixin):
    """Thread-safe real-time GRBL controller managing connection, jogging, framing, jobs, and E-Stop."""

    def __init__(
        self,
        event_bus: EventBus,
        db: Database | None = None,
        *,
        mock_speed_multiplier: float = 10.0,
    ) -> None:
        self._bus = event_bus
        self._db = db
        self._mock_speed_multiplier = mock_speed_multiplier

        self._state_lock = threading.RLock()
        self._op_lock = threading.Lock()

        self._machine_state: MachineState = MachineState.DISCONNECTED
        self._framing_return_state: MachineState = MachineState.IDLE
        self._job_state: JobState | None = None
        self._grbl_state: str = "Idle"
        self._profile: MachineProfile = MachineProfile()
        self._mock: bool = False
        self._port: str = ""
        self._baud: int = 115200

        self._mpos = Vec3()
        self._wpos = Vec3()
        self._wco = Vec3()
        self._feed: float = 0.0
        self._spindle: float = 0.0
        self._pen_state: Literal["up", "down"] = "up"
        self._buf_planner: int = 15
        self._buf_rx: int = 128
        self._alarm_code: int | None = None

        self._transport: SerialTransport | None = None
        self._streamer = CharacterCountingStreamer(rx_buffer=128)
        self._streaming_active = False

        self._rx_cond = threading.Condition(self._state_lock)
        self._welcome_count: int = 0
        self._status_count: int = 0
        self._sync_ok_count: int = 0
        self._sync_error: tuple[int, str] | None = None
        self._sync_capture_active: bool = False
        self._sync_captured_lines: list[str] = []

        self._stop_poll = threading.Event()
        self._poll_wake = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._worker_thread: threading.Thread | None = None

        self._estop_event = threading.Event()
        self._pause_event = threading.Event()
        self._abort_event = threading.Event()

        self._job: ActiveJobContext | None = None

    @property
    def machine_state(self) -> MachineState:
        with self._state_lock:
            return self._machine_state

    @property
    def job_state(self) -> JobState | None:
        with self._state_lock:
            return self._job_state

    @property
    def profile(self) -> MachineProfile:
        with self._state_lock:
            return self._profile

    @property
    def transport(self) -> SerialTransport | None:
        return self._transport

    @property
    def streamer(self) -> CharacterCountingStreamer:
        return self._streamer

    def is_busy_with_job(self) -> bool:
        with self._state_lock:
            return self._job is not None and self._job_state in (
                JobState.QUEUED,
                JobState.PREPARING,
                JobState.STREAMING,
                JobState.PAUSED,
                JobState.PEN_CHANGE,
                JobState.WAIT_PAPER,
            )

    def get_status_snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "machine_state": self._machine_state.value,
                "job_state": self._job_state.value if self._job_state else None,
                "grbl_state": self._grbl_state,
                "mpos": {
                    "x": round(self._mpos.x, 3),
                    "y": round(self._mpos.y, 3),
                    "z": round(self._mpos.z, 3),
                },
                "wpos": {
                    "x": round(self._wpos.x, 3),
                    "y": round(self._wpos.y, 3),
                    "z": round(self._wpos.z, 3),
                },
                "feed": round(self._feed, 1),
                "pen": self._pen_state,
                "buf": {
                    "planner": self._buf_planner,
                    "rx": self._buf_rx,
                },
                "alarm_code": self._alarm_code,
                "mock": self._mock,
            }

    def get_active_job_snapshot(self, job_id: str | None = None) -> dict[str, Any] | None:
        with self._state_lock:
            job = self._job
            if job is None:
                return None
            if job_id is not None and job.job_id != job_id:
                return None
            return {
                "job_id": job.job_id,
                "layout_id": job.layout_id,
                "job_state": self._job_state.value if self._job_state else JobState.QUEUED.value,
                "page_indices": list(job.page_indices),
                "current_page_index": job.current_page_index,
                "progress": dict(job.last_progress) if job.last_progress else None,
            }

    @staticmethod
    def list_ports() -> list[dict[str, Any]]:
        return list_serial_ports()

    def connect(
        self,
        port: str,
        baud: int,
        profile: MachineProfile,
        mock: bool = True,
    ) -> dict[str, Any]:
        with self._op_lock:
            self._shutdown_transport()

            with self._state_lock:
                self._profile = profile
                self._port = port
                self._baud = int(baud)
                self._mock = bool(mock or port.upper() == "MOCK")
                self._machine_state = MachineState.CONNECTING
                self._framing_return_state = MachineState.IDLE
                self._job_state = None
                self._job = None
                self._alarm_code = None
                self._streamer = CharacterCountingStreamer(rx_buffer=profile.rx_buffer)
                self._buf_rx = profile.rx_buffer
                self._estop_event.clear()
                self._pause_event.clear()
                self._abort_event.clear()
                welcome_before = self._welcome_count
                status_before = self._status_count

            self._publish_status()

            transport: SerialTransport
            if self._mock:
                transport = MockGrblTransport(
                    profile=profile,
                    speed_multiplier=self._mock_speed_multiplier,
                )
            else:
                transport = PySerialTransport(port=port, baud=baud)

            transport.set_callbacks(
                on_line=self._handle_rx_line,
                on_log=self._handle_serial_log,
                on_disconnect=self._handle_disconnect,
            )

            try:
                transport.open()
            except Exception as exc:
                with self._state_lock:
                    self._machine_state = MachineState.ERROR
                    self._transport = None
                self._publish_status()
                self._bus.publish(
                    "alarm",
                    {
                        "code": "SERIAL_OPEN_FAILED",
                        "message": f"串口打开失败 ({port}): {exc}",
                        "severity": "critical",
                    },
                )
                raise RuntimeError(f"Failed to open serial port {port}: {exc}") from exc

            self._transport = transport

            deadline = time.monotonic() + 2.0
            probed = False
            with self._rx_cond:
                while (
                    self._welcome_count == welcome_before
                    and self._status_count == status_before
                    and time.monotonic() < deadline
                ):
                    if not probed:
                        transport.send_realtime(b"?")
                        probed = True
                    self._rx_cond.wait(timeout=0.1)

            if self._welcome_count == welcome_before and self._status_count == status_before:
                self._shutdown_transport()
                with self._state_lock:
                    self._machine_state = MachineState.ERROR
                self._publish_status()
                raise TimeoutError(f"GRBL handshake timeout on {port}")

            self._query_status_sync(timeout=0.5)
            with self._state_lock:
                self._machine_state = (
                    MachineState.ALARM if self._grbl_state == "Alarm" else MachineState.IDLE
                )

            if self.machine_state == MachineState.IDLE:
                try:
                    self._send_sync_lines(pen_up_commands(profile), timeout=2.0)
                    with self._state_lock:
                        self._pen_state = "up"
                except Exception as exc:
                    logger.warning("Initial pen-up command on connect failed: %s", exc)

            self._stop_poll.clear()
            self._poll_thread = threading.Thread(
                target=self._poll_loop, name="grbl-status-poll", daemon=True
            )
            self._poll_thread.start()
            self._publish_status()

            return {
                "machine_state": self.machine_state.value,
                "profile_id": profile.profile_id,
                "mock": self._mock,
            }

    def disconnect(self) -> dict[str, Any]:
        with self._op_lock:
            self._abort_event.set()
            self._shutdown_transport()
            with self._state_lock:
                self._machine_state = MachineState.DISCONNECTED
                if self._job is not None and self._job_state not in (
                    JobState.COMPLETED,
                    JobState.ABORTED,
                    JobState.FAILED,
                ):
                    self._job_state = JobState.ABORTED
                    if self._db is not None:
                        self._db.update_job(
                            self._job.job_id,
                            state=JobState.ABORTED.value,
                            error_message="Disconnected",
                        )
                self._job = None
                self._job_state = None
                self._alarm_code = None
            self._publish_status()
            return {"machine_state": MachineState.DISCONNECTED.value}

    def _shutdown_transport(self) -> None:
        self._stop_poll.set()
        self._poll_wake.set()
        if self._worker_thread is not None and self._worker_thread.is_alive():
            self._abort_event.set()
            with self._rx_cond:
                self._rx_cond.notify_all()
            self._worker_thread.join(timeout=1.5)
        self._worker_thread = None

        if self._poll_thread is not None and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=1.0)
        self._poll_thread = None

        if self._transport is not None:
            try:
                self._transport.close()
            except Exception as exc:
                logger.debug("Transport close error ignored during shutdown: %s", exc)
            self._transport = None

    def jog(self, dx: float, dy: float, feed: float | None = None) -> dict[str, Any]:
        with self._state_lock:
            if self._machine_state not in (
                MachineState.IDLE,
                MachineState.JOGGING,
                MachineState.PEN_CHANGE,
            ):
                raise MachineStateError(f"Cannot jog in state {self._machine_state.value}")
            if self._transport is None or not self._transport.is_open():
                raise MachineStateError("Machine is not connected")
            prof = self._profile
            target_x = self._wpos.x + float(dx)
            target_y = self._wpos.y + float(dy)
            if (
                target_x < -10.0
                or target_y < -10.0
                or target_x > prof.workspace_mm.x + 10.0
                or target_y > prof.workspace_mm.y + 10.0
            ):
                msg = (
                    f"点动目标 ({target_x:.1f}, {target_y:.1f}) 超出工作区 "
                    f"({prof.workspace_mm.x}x{prof.workspace_mm.y} mm)"
                )
                self._bus.publish(
                    "alarm", {"code": "SOFT_LIMIT", "message": msg, "severity": "warn"}
                )
                raise ValueError(msg)

            jog_feed = float(feed or prof.jog_feed)
            cmd = f"$J=G91 G21 X{dx:.3f} Y{dy:.3f} F{int(round(max(60.0, jog_feed)))}"
            if self._machine_state == MachineState.IDLE:
                self._machine_state = MachineState.JOGGING
            transport = self._transport

        transport.send_line(cmd)
        self._publish_status()
        return {"accepted": True}

    def jog_cancel(self) -> dict[str, Any]:
        transport = self._transport
        if transport is not None and transport.is_open():
            transport.send_realtime(b"\x85")
        return {"accepted": True}

    def zero(self, axes: list[str] | None = None) -> dict[str, Any]:
        axes = axes or ["X", "Y"]
        with self._op_lock:
            with self._state_lock:
                if self._machine_state not in (MachineState.IDLE, MachineState.PEN_CHANGE):
                    raise MachineStateError(
                        f"Cannot zero axes in state {self._machine_state.value}"
                    )
                prof = self._profile

            self._send_sync_lines(pen_up_commands(prof, include_dwell=False), timeout=2.0)
            parts = [f"{a.upper()}0" for a in axes if a.upper() in ("X", "Y", "Z")]
            if not parts:
                parts = ["X0", "Y0"]
            self._send_sync_lines([f"G92 {' '.join(parts)}"], timeout=2.0)
            self._wait_grbl_idle(timeout=1.5)
            self._query_status_sync(timeout=0.5)
            with self._state_lock:
                self._pen_state = "up"
                wpos = {
                    "x": round(self._wpos.x, 3),
                    "y": round(self._wpos.y, 3),
                    "z": round(self._wpos.z, 3),
                }
            self._publish_status()
            return {"wpos": wpos}

    def update_active_profile(self, profile: MachineProfile) -> bool:
        """Apply updated `MachineProfile` parameters immediately when idle/paused on the same profile."""
        with self._state_lock:
            if (
                self._machine_state == MachineState.DISCONNECTED
                or self.is_busy_with_job()
                or self._profile.profile_id != profile.profile_id
            ):
                return False
            self._profile = profile
            if isinstance(self._transport, MockGrblTransport):
                self._transport.profile = profile
        self._publish_status()
        return True

    def set_pen(
        self,
        state: Literal["up", "down"],
        *,
        override_cmd: str | None = None,
        override_z_mm: float | None = None,
        override_z_feed: float | None = None,
    ) -> dict[str, Any]:
        with self._op_lock:
            with self._state_lock:
                if self._machine_state not in (
                    MachineState.IDLE,
                    MachineState.PAUSED,
                    MachineState.PEN_CHANGE,
                    MachineState.PAPER_CHANGE,
                ):
                    raise MachineStateError(
                        f"Cannot toggle pen in state {self._machine_state.value}"
                    )
                prof = self._profile

            if override_z_mm is not None:
                z_val = float(override_z_mm)
                if state == "up":
                    cmds = [f"G0 Z{z_val:.3f}".rstrip("0").rstrip(".")]
                else:
                    zf = int(round(max(60.0, float(override_z_feed or prof.pen.z_feed))))
                    cmds = [f"G1 Z{z_val:.3f} F{zf}"]
                if prof.pen.dwell_ms > 0:
                    cmds.append(f"G4 P{prof.pen.dwell_ms / 1000.0:.3f}".rstrip("0").rstrip("."))
            elif override_cmd and override_cmd.strip():
                clean_cmd = CharacterCountingStreamer.clean_line(override_cmd.strip())
                if not clean_cmd:
                    raise ValueError("Invalid pen calibration command")
                cmds = [clean_cmd]
                if prof.pen.dwell_ms > 0:
                    cmds.append(f"G4 P{prof.pen.dwell_ms / 1000.0:.3f}".rstrip("0").rstrip("."))
            else:
                cmds = pen_up_commands(prof) if state == "up" else pen_down_commands(prof)

            self._send_sync_lines(cmds, timeout=2.0)
            self._wait_grbl_idle(timeout=2.0)
            with self._state_lock:
                self._pen_state = state
            self._publish_status()
            return {"pen": state}

    def goto_zero(self, feed: float | None = None) -> dict[str, Any]:
        """Lift pen safely and rapid-return to current work origin (WPos X0 Y0)."""
        return self.move_to(0.0, 0.0, feed=feed, pen_up=True)

    def move_to(
        self,
        x: float,
        y: float,
        *,
        feed: float | None = None,
        pen_up: bool = True,
    ) -> dict[str, Any]:
        """Safely lift pen (default) and move to absolute work coordinate `(x, y)` in mm."""
        tx, ty = float(x), float(y)
        with self._op_lock:
            with self._state_lock:
                if self._machine_state not in (
                    MachineState.IDLE,
                    MachineState.PEN_CHANGE,
                    MachineState.PAPER_CHANGE,
                ):
                    raise MachineStateError(
                        f"Cannot move to coordinate in state {self._machine_state.value}"
                    )
                if self._transport is None or not self._transport.is_open():
                    raise MachineStateError("Machine is not connected")
                prof = self._profile
                if (
                    tx < -10.0
                    or ty < -10.0
                    or tx > prof.workspace_mm.x + 10.0
                    or ty > prof.workspace_mm.y + 10.0
                ):
                    msg = (
                        f"目标坐标 ({tx:.1f}, {ty:.1f}) 超出工作区 "
                        f"({prof.workspace_mm.x}x{prof.workspace_mm.y} mm)"
                    )
                    self._bus.publish(
                        "alarm", {"code": "SOFT_LIMIT", "message": msg, "severity": "warn"}
                    )
                    raise ValueError(msg)

            cmds: list[str] = []
            if pen_up:
                cmds.extend(pen_up_commands(prof))
            move_feed = int(round(max(60.0, float(feed or prof.feed_travel))))
            cmds.extend(["G21", "G90", f"G0 X{tx:.3f} Y{ty:.3f} F{move_feed}"])
            self._send_sync_lines(cmds, timeout=6.0)
            self._wait_grbl_idle(timeout=12.0)
            self._query_status_sync(timeout=0.5)
            with self._state_lock:
                if pen_up:
                    self._pen_state = "up"
                wpos = {
                    "x": round(self._wpos.x, 3),
                    "y": round(self._wpos.y, 3),
                    "z": round(self._wpos.z, 3),
                }
            self._publish_status()
            return {"wpos": wpos, "target": {"x": round(tx, 3), "y": round(ty, 3)}}

    def move_to_start(self, page: ComposedPage) -> dict[str, Any]:
        """Lift pen and move to next writing start point (paused breakpoint or page first stroke)."""
        with self._op_lock:
            with self._state_lock:
                if self._machine_state not in (
                    MachineState.IDLE,
                    MachineState.PAUSED,
                    MachineState.PEN_CHANGE,
                    MachineState.PAPER_CHANGE,
                ):
                    raise MachineStateError(
                        f"Cannot move to writing start in state {self._machine_state.value}"
                    )
                if self._transport is None or not self._transport.is_open():
                    raise MachineStateError("Machine is not connected")
                prof = self._profile

                if self._machine_state in (MachineState.PAUSED, MachineState.PEN_CHANGE) and self._job is not None:
                    s_idx = self._job.resume_stroke_idx
                    tx, ty = self._job.current_compiled.stroke_start_xy.get(
                        s_idx,
                        (self._job.saved_wpos["x"], self._job.saved_wpos["y"]),
                    )
                    source = "resume_breakpoint"
                else:
                    first_stroke = next(
                        ((idx, st) for idx, st in enumerate(page.strokes) if len(st.pts) >= 4),
                        None,
                    )
                    if first_stroke is None:
                        raise ValueError("当前页无有效书写笔画，无法移动至书写起点")
                    s_idx, st = first_stroke
                    tx, ty = map_page_to_machine(
                        float(st.pts[0]),
                        float(st.pts[1]),
                        page.width_mm,
                        page.height_mm,
                        prof,
                    )
                    source = "page_first_stroke"

                if (
                    tx < -10.0
                    or ty < -10.0
                    or tx > prof.workspace_mm.x + 10.0
                    or ty > prof.workspace_mm.y + 10.0
                ):
                    msg = (
                        f"书写起点 ({tx:.1f}, {ty:.1f}) 超出工作区 "
                        f"({prof.workspace_mm.x}x{prof.workspace_mm.y} mm)"
                    )
                    self._bus.publish(
                        "alarm", {"code": "SOFT_LIMIT", "message": msg, "severity": "warn"}
                    )
                    raise ValueError(msg)

            move_feed = int(round(max(60.0, float(prof.feed_travel))))
            cmds = list(pen_up_commands(prof))
            cmds.extend(["G21", "G90", f"G0 X{tx:.3f} Y{ty:.3f} F{move_feed}"])
            self._send_sync_lines(cmds, timeout=6.0)
            self._wait_grbl_idle(timeout=12.0)
            self._query_status_sync(timeout=0.5)
            with self._state_lock:
                self._pen_state = "up"
                wpos = {
                    "x": round(self._wpos.x, 3),
                    "y": round(self._wpos.y, 3),
                    "z": round(self._wpos.z, 3),
                }
            self._publish_status()
            return {
                "wpos": wpos,
                "target": {"x": round(tx, 3), "y": round(ty, 3)},
                "source": source,
                "stroke_index": s_idx,
            }

    def home(self) -> dict[str, Any]:
        """Run GRBL `$H` hardware homing cycle and ensure pen is lifted cleanly."""
        with self._op_lock:
            with self._state_lock:
                if self._machine_state not in (
                    MachineState.IDLE,
                    MachineState.ALARM,
                    MachineState.ESTOPPED,
                ):
                    raise MachineStateError(f"Cannot home in state {self._machine_state.value}")
                if self._transport is None or not self._transport.is_open():
                    raise MachineStateError("Machine is not connected")
                prof = self._profile
                was_idle = self._machine_state == MachineState.IDLE
                self._estop_event.clear()
                self._abort_event.clear()

            if self._worker_thread is not None and self._worker_thread.is_alive():
                self._worker_thread.join(timeout=1.5)

            if was_idle:
                self._send_sync_lines(pen_up_commands(prof), timeout=2.0)
            self._send_sync_lines(["$H"], timeout=20.0)
            self._wait_grbl_idle(timeout=20.0)
            self._send_sync_lines(pen_up_commands(prof), timeout=2.0)
            self._query_status_sync(timeout=0.5)
            with self._state_lock:
                self._alarm_code = None
                self._pen_state = "up"
                self._machine_state = MachineState.IDLE
                wpos = {
                    "x": round(self._wpos.x, 3),
                    "y": round(self._wpos.y, 3),
                    "z": round(self._wpos.z, 3),
                }
                mpos = {
                    "x": round(self._mpos.x, 3),
                    "y": round(self._mpos.y, 3),
                    "z": round(self._mpos.z, 3),
                }
            self._publish_status()
            return {"machine_state": MachineState.IDLE.value, "wpos": wpos, "mpos": mpos}

    def send_raw_command(self, command: str) -> dict[str, Any]:
        """Execute a single interactive GRBL/G-code tuning command safely and return captured lines."""
        raw = str(command or "").strip()
        if not raw or "\n" in raw or "\r" in raw:
            raise ValueError("仅支持单行 GRBL 指令")
        cmd = CharacterCountingStreamer.clean_line(raw)
        if not cmd:
            raise ValueError("指令为空或非法")

        with self._op_lock:
            with self._state_lock:
                if self._machine_state not in (
                    MachineState.IDLE,
                    MachineState.PAUSED,
                    MachineState.PEN_CHANGE,
                    MachineState.PAPER_CHANGE,
                    MachineState.ALARM,
                    MachineState.ESTOPPED,
                ):
                    raise MachineStateError(
                        f"Cannot send raw command in state {self._machine_state.value}"
                    )
                if self._transport is None or not self._transport.is_open():
                    raise MachineStateError("Machine is not connected")

            captured = self._send_sync_lines([cmd], timeout=5.0, capture=True)
            if self.machine_state not in (MachineState.ALARM, MachineState.ESTOPPED):
                self._wait_grbl_idle(timeout=6.0)
            self._query_status_sync(timeout=0.5)
            with self._state_lock:
                if cmd.upper() == "$X" and self._grbl_state == "Idle":
                    self._alarm_code = None
                    self._machine_state = MachineState.IDLE
                wpos = {
                    "x": round(self._wpos.x, 3),
                    "y": round(self._wpos.y, 3),
                    "z": round(self._wpos.z, 3),
                }
            self._publish_status()
            return {"command": cmd, "ok": True, "responses": captured, "wpos": wpos}

    def frame_check(
        self,
        bbox: list[float],
        *,
        page_width_mm: float = 210.0,
        page_height_mm: float = 297.0,
    ) -> dict[str, Any]:
        with self._op_lock:
            with self._state_lock:
                if self._machine_state not in (MachineState.IDLE, MachineState.PAPER_CHANGE):
                    raise MachineStateError(
                        f"Frame check requires IDLE or PAPER_CHANGE state (current: {self._machine_state.value})"
                    )
                if self._worker_thread is not None and self._worker_thread.is_alive():
                    raise MachineStateError("Previous motion worker is still active")
                prof = self._profile
                return_state = self._machine_state

            lines = compile_frame_gcode(
                bbox,
                prof,
                page_width_mm=page_width_mm,
                page_height_mm=page_height_mm,
            )

            with self._state_lock:
                self._framing_return_state = return_state
                self._machine_state = MachineState.FRAMING
                self._pen_state = "up"
                self._estop_event.clear()
                self._abort_event.clear()
            self._publish_status()

            if self._worker_thread is not None:
                self._worker_thread.join(timeout=0.1)
            self._worker_thread = threading.Thread(
                target=self._run_frame_worker,
                args=(lines,),
                name="grbl-frame-worker",
                daemon=True,
            )
            self._worker_thread.start()
            return {"machine_state": MachineState.FRAMING.value, "bbox": list(bbox)}

    def _run_frame_worker(self, lines: list[str]) -> None:
        try:
            self._stream_lines(lines, is_job=False)
            if not self._estop_event.is_set() and not self._abort_event.is_set():
                self._wait_grbl_idle(timeout=15.0)
                with self._state_lock:
                    if (
                        self._machine_state == MachineState.FRAMING
                        and not self._estop_event.is_set()
                        and not self._abort_event.is_set()
                    ):
                        self._machine_state = self._framing_return_state
                self._publish_status()
        except Exception as exc:
            logger.exception("Frame check worker failed: %s", exc)
            with self._state_lock:
                if self._machine_state == MachineState.FRAMING and not self._estop_event.is_set():
                    self._machine_state = MachineState.ALARM
            self._publish_status()

    def estop(self) -> dict[str, Any]:
        """Highest-priority idempotent E-Stop: bypasses _op_lock, sends 0x18 + safe pen lift."""
        self._estop_event.set()
        self._abort_event.set()

        with self._state_lock:
            transport = self._transport
            prof = self._profile
            welcome_before = self._welcome_count
            job = self._job
            if self._machine_state == MachineState.DISCONNECTED or transport is None:
                return {"machine_state": self._machine_state.value}

        transport.clear_tx_queue()
        transport.send_realtime(b"\x18")

        with self._rx_cond:
            self._streamer.reset()
            self._streaming_active = False
            self._rx_cond.notify_all()

        deadline = time.monotonic() + 0.8
        with self._rx_cond:
            while self._welcome_count == welcome_before and time.monotonic() < deadline:
                self._rx_cond.wait(timeout=0.05)
            got_welcome = self._welcome_count > welcome_before

        if got_welcome and prof.pen.mode == "z":
            try:
                safe_lift = abs(float(prof.pen.z_up_mm - prof.pen.z_down_mm)) or 4.0
                transport.send_line("$X")
                transport.send_line("G91")
                transport.send_line(f"G0 Z{safe_lift:.3f}")
                transport.send_line("G90")
            except Exception as exc:
                logger.warning("Z failsafe lift on E-Stop raised: %s", exc)

        with self._state_lock:
            self._machine_state = MachineState.ESTOPPED if got_welcome else MachineState.ERROR
            self._pen_state = "up"
            self._alarm_code = 3
            if job is not None and self._job_state not in (
                JobState.COMPLETED,
                JobState.ABORTED,
                JobState.FAILED,
            ):
                self._job_state = JobState.ABORTED
                if self._db is not None:
                    self._db.update_job(
                        job.job_id,
                        state=JobState.ABORTED.value,
                        error_message="Emergency stop triggered",
                    )

        if job is not None:
            self._bus.publish(
                "job.event",
                {
                    "job_id": job.job_id,
                    "event": "estop",
                    "page_index": job.current_page_index,
                    "message": "已触发急停（0x18 软复位 + 安全抬笔），请检查笔尖后手动解锁",
                },
            )
        self._bus.publish(
            "alarm",
            {
                "code": "ESTOP",
                "message": "急停已触发：已发送 0x18 软复位并确保抬笔，请检查机械臂与纸面后点击解锁",
                "severity": "critical",
            },
        )
        self._publish_status()
        return {"machine_state": self.machine_state.value}

    def unlock(self) -> dict[str, Any]:
        with self._op_lock:
            with self._state_lock:
                if self._machine_state not in (
                    MachineState.ALARM,
                    MachineState.ESTOPPED,
                    MachineState.IDLE,
                ):
                    raise MachineStateError(
                        f"Cannot unlock in state {self._machine_state.value}"
                    )
                if self._transport is None or not self._transport.is_open():
                    raise MachineStateError("Machine is not connected")
                prof = self._profile
                self._estop_event.clear()
                self._abort_event.clear()

            if self._worker_thread is not None and self._worker_thread.is_alive():
                self._worker_thread.join(timeout=1.5)

            self._send_sync_lines(["$X"], timeout=2.0)
            self._send_sync_lines(pen_up_commands(prof), timeout=2.0)
            self._query_status_sync(timeout=0.5)

            with self._state_lock:
                self._alarm_code = None
                self._pen_state = "up"
                self._machine_state = MachineState.IDLE
            self._publish_status()
            return {"machine_state": MachineState.IDLE.value}


__all__ = [
    "ActiveJobContext",
    "JobState",
    "MachineController",
    "MachineProfile",
    "MachineState",
    "MachineStateError",
    "Vec3",
    "_ActiveJob",
]
