"""Serial RX/TX streaming, synchronous command helpers, and status polling for MachineController."""

from __future__ import annotations

import logging
import time

from handwrite.gcode.compiler import CompiledGcode, pen_up_commands
from handwrite.grbl.controller_types import (
    ActiveJobContext,
    JobState,
    MachineProfile,
    MachineState,
    MachineStateError,
    Vec3,
)
from handwrite.grbl.parser import GrblStatus, parse_grbl_line
from handwrite.grbl.streamer import CharacterCountingStreamer

logger = logging.getLogger(__name__)


class _ControllerIOMixin:
    """Low-level GRBL serial RX/TX streaming, status parsing, and polling mixin."""

    def _deterministic_standstill_lift(
        self, saved_wpos: dict[str, float], prof: MachineProfile
    ) -> None:
        transport = self._transport
        if transport is None or not transport.is_open():
            return
        with self._state_lock:
            welcome_before = self._welcome_count

        transport.clear_tx_queue()
        transport.send_realtime(b"\x18")
        with self._rx_cond:
            self._streamer.reset()
            self._streaming_active = False

        deadline = time.monotonic() + 1.0
        with self._rx_cond:
            while self._welcome_count == welcome_before and time.monotonic() < deadline:
                self._rx_cond.wait(timeout=0.05)

        if self._estop_event.is_set():
            return

        cmds = [
            "$X",
            "G21",
            "G90",
            f"G92 X{saved_wpos['x']:.3f} Y{saved_wpos['y']:.3f}",
        ]
        cmds.extend(pen_up_commands(prof))
        self._send_sync_lines(cmds, timeout=3.0)
        self._wait_grbl_idle(timeout=2.0)

    def _stream_lines(
        self,
        lines: list[str],
        *,
        is_job: bool,
        start_line: int = 0,
        compiled: CompiledGcode | None = None,
        job: ActiveJobContext | None = None,
    ) -> bool:
        """Stream G-code lines using strict 128B CharacterCountingStreamer."""
        transport = self._transport
        if transport is None or not transport.is_open():
            return False

        with self._rx_cond:
            self._streamer.reset()
            self._streaming_active = True
            self._sync_error = None

        total = len(lines)
        idx = max(0, start_line)
        last_progress_ts = 0.0

        try:
            while idx < total:
                if self._estop_event.is_set() or self._abort_event.is_set():
                    return False
                if is_job and self._pause_event.is_set():
                    return False
                with self._state_lock:
                    if self._sync_error is not None:
                        code, msg = self._sync_error
                        raise RuntimeError(f"GRBL error:{code} ({msg})")
                    if self._machine_state in (
                        MachineState.ALARM,
                        MachineState.ESTOPPED,
                        MachineState.ERROR,
                        MachineState.DISCONNECTED,
                    ):
                        return False

                cleaned = CharacterCountingStreamer.clean_line(lines[idx])
                if not cleaned:
                    idx += 1
                    continue

                sent = False
                with self._rx_cond:
                    if self._streamer.can_send(cleaned):
                        self._streamer.on_sent(idx, cleaned)
                        sent = True
                    else:
                        self._rx_cond.wait(timeout=0.02)

                if sent:
                    self._update_pen_state_from_cmd(cleaned)
                    transport.send_line(cleaned)
                    idx += 1

                if is_job and job is not None and compiled is not None:
                    now = time.monotonic()
                    if now - last_progress_ts >= 0.2:
                        acked = max(0, self._streamer.last_acked_line)
                        self._publish_job_progress(job, compiled, acked)
                        last_progress_ts = now

            while True:
                if self._estop_event.is_set() or self._abort_event.is_set():
                    return False
                if is_job and self._pause_event.is_set():
                    return False
                with self._rx_cond:
                    if self._sync_error is not None:
                        code, msg = self._sync_error
                        raise RuntimeError(f"GRBL error:{code} ({msg})")
                    if self._streamer.is_drained:
                        break
                    self._rx_cond.wait(timeout=0.02)

                if is_job and job is not None and compiled is not None:
                    now = time.monotonic()
                    if now - last_progress_ts >= 0.2:
                        acked = max(0, self._streamer.last_acked_line)
                        self._publish_job_progress(job, compiled, acked)
                        last_progress_ts = now

            return True
        finally:
            with self._rx_cond:
                self._streaming_active = False

    def _update_pen_state_from_cmd(self, cmd: str) -> None:
        upper = cmd.upper()
        with self._state_lock:
            prof = self._profile
            if prof.pen.mode == "servo":
                if upper.startswith("M5"):
                    self._pen_state = "up"
                elif upper.startswith("M3") or upper.startswith("M4"):
                    self._pen_state = "down"
            else:
                if "Z" in upper:
                    mid = (prof.pen.z_up_mm + prof.pen.z_down_mm) / 2.0
                    try:
                        z_part = upper.split("Z", 1)[1].split()[0]
                        self._pen_state = "up" if float(z_part) >= mid else "down"
                    except Exception:
                        pass

    def _send_sync_lines(
        self, lines: list[str], timeout: float = 3.0, *, capture: bool = False
    ) -> list[str]:
        transport = self._transport
        if transport is None or not transport.is_open():
            raise MachineStateError("Machine is not connected")
        with self._rx_cond:
            if capture:
                self._sync_captured_lines = []
                self._sync_capture_active = True
        try:
            for raw in lines:
                cmd = CharacterCountingStreamer.clean_line(raw)
                if not cmd:
                    continue
                with self._rx_cond:
                    before = self._sync_ok_count
                    self._sync_error = None
                self._update_pen_state_from_cmd(cmd)
                transport.send_line(cmd)
                deadline = time.monotonic() + timeout
                with self._rx_cond:
                    while (
                        self._sync_ok_count == before
                        and self._sync_error is None
                        and not self._estop_event.is_set()
                        and time.monotonic() < deadline
                    ):
                        self._rx_cond.wait(timeout=0.05)
                    if self._estop_event.is_set():
                        return []
                    if self._sync_error is not None:
                        code, msg = self._sync_error
                        self._sync_error = None
                        raise RuntimeError(f"GRBL rejected '{cmd}': error:{code} ({msg})")
                    if self._sync_ok_count == before:
                        raise TimeoutError(f"Timed out waiting for 'ok' after '{cmd}'")
            with self._rx_cond:
                return list(self._sync_captured_lines) if capture else []
        finally:
            if capture:
                with self._rx_cond:
                    self._sync_capture_active = False

    def _query_status_sync(self, timeout: float = 0.5) -> None:
        transport = self._transport
        if transport is None or not transport.is_open():
            return
        with self._rx_cond:
            before = self._status_count
        transport.send_realtime(b"?")
        deadline = time.monotonic() + timeout
        with self._rx_cond:
            while self._status_count == before and time.monotonic() < deadline:
                self._rx_cond.wait(timeout=0.02)

    def _wait_grbl_states(self, target_states: tuple[str, ...], timeout: float = 3.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._estop_event.is_set():
                return False
            self._query_status_sync(timeout=0.15)
            with self._state_lock:
                if self._grbl_state in target_states:
                    return True
            time.sleep(0.02)
        return False

    def _wait_grbl_idle(self, timeout: float = 10.0) -> bool:
        return self._wait_grbl_states(("Idle",), timeout=timeout)

    def _handle_serial_log(self, direction: str, line: str) -> None:
        self._bus.publish("serial.log", {"dir": direction, "line": line})

    def _handle_disconnect(self, reason: str) -> None:
        with self._state_lock:
            self._machine_state = MachineState.ERROR
            if self._job is not None and self._job_state not in (
                JobState.COMPLETED,
                JobState.ABORTED,
                JobState.FAILED,
            ):
                self._job_state = JobState.FAILED
                if self._db is not None:
                    self._db.update_job(
                        self._job.job_id,
                        state=JobState.FAILED.value,
                        error_message=f"Serial disconnected: {reason}",
                    )
        with self._rx_cond:
            self._rx_cond.notify_all()
        self._bus.publish(
            "alarm",
            {
                "code": "SERIAL_DISCONNECT",
                "message": f"串口连接异常断开: {reason}",
                "severity": "critical",
            },
        )
        self._publish_status()

    def _handle_rx_line(self, line: str) -> None:
        parsed = parse_grbl_line(line)

        if parsed.kind == "status" and parsed.status is not None:
            self._apply_status(parsed.status)
            return

        if parsed.kind == "ok":
            with self._rx_cond:
                if self._streaming_active:
                    self._streamer.on_ok()
                else:
                    self._sync_ok_count += 1
                self._rx_cond.notify_all()
            return

        if parsed.kind == "welcome":
            with self._rx_cond:
                self._welcome_count += 1
                self._rx_cond.notify_all()
            return

        if parsed.kind == "error":
            code = parsed.code or 0
            msg = parsed.message
            with self._rx_cond:
                if self._streaming_active:
                    bad_line = self._streamer.on_error()
                    self._sync_error = (code, f"line {bad_line}: {msg}")
                else:
                    self._sync_error = (code, msg)
                self._rx_cond.notify_all()
            self._bus.publish(
                "alarm",
                {"code": code, "message": f"GRBL 错误 error:{code} — {msg}", "severity": "warn"},
            )
            return

        if parsed.kind == "alarm":
            code = parsed.code or 0
            msg = parsed.message
            with self._rx_cond:
                self._alarm_code = code
                self._grbl_state = "Alarm"
                if self._machine_state != MachineState.ESTOPPED:
                    self._machine_state = MachineState.ALARM
                job = self._job
                self._rx_cond.notify_all()
            self._bus.publish(
                "alarm",
                {"code": code, "message": f"GRBL 报警 ALARM:{code} — {msg}", "severity": "critical"},
            )
            if job is not None:
                self._bus.publish(
                    "job.event",
                    {
                        "job_id": job.job_id,
                        "event": "alarm",
                        "page_index": job.current_page_index,
                        "code": code,
                        "message": f"GRBL ALARM:{code} — {msg}",
                    },
                )
            self._publish_status()
            return

        if parsed.kind in {"setting", "message", "other"} and parsed.raw:
            with self._rx_cond:
                if self._sync_capture_active and len(self._sync_captured_lines) < 256:
                    self._sync_captured_lines.append(parsed.raw)

    def _apply_status(self, st: GrblStatus) -> None:
        state_changed = False
        with self._rx_cond:
            self._grbl_state = st.state
            self._feed = st.feed
            self._spindle = st.spindle
            if st.wco is not None:
                self._wco = Vec3(x=st.wco[0], y=st.wco[1], z=st.wco[2])
            if st.mpos is not None:
                self._mpos = Vec3(x=st.mpos[0], y=st.mpos[1], z=st.mpos[2])
                if st.wpos is None:
                    self._wpos = Vec3(
                        x=st.mpos[0] - self._wco.x,
                        y=st.mpos[1] - self._wco.y,
                        z=st.mpos[2] - self._wco.z,
                    )
            if st.wpos is not None:
                self._wpos = Vec3(x=st.wpos[0], y=st.wpos[1], z=st.wpos[2])
                if st.mpos is None:
                    self._mpos = Vec3(
                        x=st.wpos[0] + self._wco.x,
                        y=st.wpos[1] + self._wco.y,
                        z=st.wpos[2] + self._wco.z,
                    )
            if st.planner_avail is not None:
                self._buf_planner = st.planner_avail
            if st.rx_avail is not None:
                self._buf_rx = st.rx_avail

            if self._profile.pen.mode == "servo":
                self._pen_state = "down" if st.spindle > 0.5 else "up"
            else:
                mid = (self._profile.pen.z_up_mm + self._profile.pen.z_down_mm) / 2.0
                self._pen_state = "up" if self._mpos.z >= mid else "down"

            if self._machine_state == MachineState.JOGGING and st.state == "Idle":
                self._machine_state = MachineState.IDLE
                state_changed = True
            elif (
                st.state == "Alarm"
                and not self._abort_event.is_set()
                and not self._pause_event.is_set()
                and self._machine_state
                not in (
                    MachineState.ALARM,
                    MachineState.ESTOPPED,
                    MachineState.DISCONNECTED,
                    MachineState.HOLDING,
                )
            ):
                self._machine_state = MachineState.ALARM
                state_changed = True

            self._status_count += 1
            self._rx_cond.notify_all()

        if state_changed:
            self._publish_status()

    def _publish_status(self) -> None:
        self._poll_wake.set()
        self._bus.publish("machine.status", self.get_status_snapshot())

    def _poll_loop(self) -> None:
        while not self._stop_poll.is_set():
            transport = self._transport
            if transport is None or not transport.is_open():
                break
            with self._state_lock:
                st = self._machine_state
                active_hz = max(2.0, min(20.0, float(self._profile.status_hz)))

            is_active = st in (
                MachineState.RUNNING,
                MachineState.JOGGING,
                MachineState.FRAMING,
                MachineState.HOLDING,
                MachineState.CONNECTING,
            )
            interval = (1.0 / active_hz) if is_active else 0.5
            try:
                transport.send_realtime(b"?")
            except Exception as exc:
                logger.debug("Status poll probe skipped: %s", exc)
            self._bus.publish("machine.status", self.get_status_snapshot())
            self._poll_wake.clear()
            self._poll_wake.wait(timeout=interval)
