"""Job lifecycle state machine, checkpointing, and progress streaming for MachineController."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from inkcraft.gcode.compiler import CompiledGcode, pen_up_commands
from inkcraft.grbl.controller_types import (
    ActiveJobContext,
    JobState,
    MachineState,
    MachineStateError,
)

logger = logging.getLogger(__name__)


class _ControllerJobsMixin:
    """Writing job start/pause/pen-change/resume/paper-ready/abort and progress tracking."""

    def start_job(
        self,
        job_id: str,
        layout_id: str,
        compiled_pages: dict[int, CompiledGcode],
        page_indices: list[int],
        start_page_index: int = 0,
    ) -> dict[str, Any]:
        with self._op_lock:
            with self._state_lock:
                if self._machine_state != MachineState.IDLE:
                    raise MachineStateError(
                        f"Cannot start job in state {self._machine_state.value}"
                    )
                if not page_indices:
                    raise ValueError("page_indices cannot be empty")
                for p in page_indices:
                    if p not in compiled_pages:
                        raise ValueError(f"Compiled G-code missing for page {p}")
                start_pos = (
                    page_indices.index(start_page_index)
                    if start_page_index in page_indices
                    else 0
                )
                prof = self._profile

                job = ActiveJobContext(
                    job_id=job_id,
                    layout_id=layout_id,
                    profile_id=prof.profile_id,
                    compiled_pages=compiled_pages,
                    page_indices=list(page_indices),
                    current_pos_in_list=start_pos,
                    resume_line_idx=0,
                    resume_stroke_idx=0,
                )
                self._job = job
                self._job_state = JobState.PREPARING
                self._machine_state = MachineState.RUNNING
                self._estop_event.clear()
                self._pause_event.clear()
                self._abort_event.clear()

            if self._db is not None:
                self._db.create_job(
                    job_id=job_id,
                    layout_id=layout_id,
                    profile_id=prof.profile_id,
                    state=JobState.STREAMING.value,
                    page_indices=job.page_indices,
                    current_page_index=job.current_page_index,
                )

            with self._state_lock:
                self._job_state = JobState.STREAMING

            self._bus.publish(
                "job.event",
                {
                    "job_id": job_id,
                    "event": "started",
                    "page_index": job.current_page_index,
                    "message": f"开始书写第 {job.current_page_index + 1} 页",
                },
            )
            if prof.auto_zero_on_start:
                # 自动设置原点: the pen's current position becomes the work origin.
                self._send_sync_lines(["G92 X0 Y0"], timeout=2.0)
            self._publish_status()
            self._launch_job_stream_thread(start_line=0)
            return {"job_id": job_id, "job_state": JobState.STREAMING.value}

    def _enter_sleep(self) -> None:
        """文件完成后自动休眠: `$SLP` de-energises steppers (soft-reset to wake)."""
        try:
            self._send_sync_lines(["$SLP"], timeout=3.0)
            self._bus.publish(
                "alarm",
                {"code": "SLEEP", "message": "书写完成，机器已进入休眠（断开重连即可唤醒）", "severity": "info"},
            )
        except Exception as exc:
            logger.warning("$SLP after job failed: %s", exc)

    def pause_job(self, job_id: str | None = None) -> dict[str, Any]:
        with self._op_lock:
            with self._state_lock:
                job = self._require_job(job_id)
                if self._machine_state == MachineState.PAUSED:
                    return {
                        "job_state": JobState.PAUSED.value,
                        "machine_state": MachineState.PAUSED.value,
                    }
                if self._machine_state != MachineState.RUNNING:
                    raise MachineStateError(
                        f"Cannot pause job in state {self._machine_state.value}"
                    )
                self._machine_state = MachineState.HOLDING
                self._pause_event.set()
                transport = self._transport
                prof = self._profile

            with self._rx_cond:
                self._rx_cond.notify_all()
            self._publish_status()

            if transport is not None:
                transport.send_realtime(b"!")

            if self._worker_thread is not None and self._worker_thread.is_alive():
                self._worker_thread.join(timeout=2.0)

            self._wait_grbl_states(("Hold:0", "Idle"), timeout=2.5)
            self._query_status_sync(timeout=0.5)

            with self._state_lock:
                saved_wpos = {
                    "x": round(self._wpos.x, 3),
                    "y": round(self._wpos.y, 3),
                    "z": round(self._wpos.z, 3),
                }
                compiled = job.current_compiled
                acked = max(0, self._streamer.last_acked_line)
                if 0 <= acked < len(compiled.line_to_stroke):
                    s_idx = compiled.line_to_stroke[acked]
                else:
                    s_idx = job.resume_stroke_idx
                if s_idx < 0:
                    s_idx = job.resume_stroke_idx
                resume_line = compiled.stroke_to_line.get(
                    s_idx, min(acked + 1, len(compiled.lines))
                )
                job.saved_wpos = saved_wpos
                job.resume_stroke_idx = max(0, s_idx)
                job.resume_line_idx = resume_line

            self._deterministic_standstill_lift(saved_wpos, prof)

            with self._state_lock:
                if self._estop_event.is_set():
                    return {
                        "job_state": self._job_state.value if self._job_state else JobState.ABORTED.value,
                        "machine_state": self._machine_state.value,
                    }
                self._machine_state = MachineState.PAUSED
                self._job_state = JobState.PAUSED
                self._pen_state = "up"

            if self._db is not None:
                self._db.update_job(
                    job.job_id,
                    state=JobState.PAUSED.value,
                    last_stroke_index=job.resume_stroke_idx,
                    last_line_acked=job.resume_line_idx,
                    saved_wpos=saved_wpos,
                )
                self._db.save_checkpoint(
                    job_id=job.job_id,
                    page_index=job.current_page_index,
                    stroke_index=job.resume_stroke_idx,
                    line_acked=job.resume_line_idx,
                    wpos=saved_wpos,
                )

            self._bus.publish(
                "job.event",
                {
                    "job_id": job.job_id,
                    "event": "paused",
                    "page_index": job.current_page_index,
                    "message": f"已安全暂停并抬笔（断点：第 {job.resume_stroke_idx} 笔）",
                },
            )
            self._publish_status()
            return {
                "job_state": JobState.PAUSED.value,
                "machine_state": MachineState.PAUSED.value,
            }

    def enter_pen_change(self, job_id: str | None = None) -> dict[str, Any]:
        if self.machine_state == MachineState.RUNNING:
            self.pause_job(job_id)

        with self._op_lock:
            with self._state_lock:
                job = self._require_job(job_id)
                if self._machine_state == MachineState.PEN_CHANGE:
                    return {
                        "job_state": JobState.PEN_CHANGE.value,
                        "machine_state": MachineState.PEN_CHANGE.value,
                    }
                if self._machine_state != MachineState.PAUSED:
                    raise MachineStateError(
                        f"Pen change requires PAUSED state (current: {self._machine_state.value})"
                    )
                prof = self._profile

            pcx, pcy = self._page_to_machine(prof.pen_change_pos_mm.x, prof.pen_change_pos_mm.y)
            cmds = list(pen_up_commands(prof))
            cmds.append(f"G0 X{pcx:.3f} Y{pcy:.3f} F{int(round(prof.feed_travel))}")
            self._send_sync_lines(cmds, timeout=5.0)
            self._wait_grbl_idle(timeout=8.0)
            self._query_status_sync(timeout=0.5)

            with self._state_lock:
                if self._estop_event.is_set():
                    return {
                        "job_state": self._job_state.value if self._job_state else JobState.ABORTED.value,
                        "machine_state": self._machine_state.value,
                    }
                self._machine_state = MachineState.PEN_CHANGE
                self._job_state = JobState.PEN_CHANGE
                self._pen_state = "up"

            if self._db is not None:
                self._db.update_job(job.job_id, state=JobState.PEN_CHANGE.value)

            self._bus.publish(
                "job.event",
                {
                    "job_id": job.job_id,
                    "event": "pen_change_ready",
                    "page_index": job.current_page_index,
                    "message": (
                        f"已移至换笔位 ({prof.pen_change_pos_mm.x:.1f}, {prof.pen_change_pos_mm.y:.1f})，"
                        "请更换笔芯后点击继续"
                    ),
                },
            )
            self._publish_status()
            return {
                "job_state": JobState.PEN_CHANGE.value,
                "machine_state": MachineState.PEN_CHANGE.value,
            }

    def resume_job(self, job_id: str | None = None) -> dict[str, Any]:
        with self._op_lock:
            with self._state_lock:
                job = self._require_job(job_id)
                if self._machine_state not in (MachineState.PAUSED, MachineState.PEN_CHANGE):
                    raise MachineStateError(
                        f"Cannot resume job in state {self._machine_state.value}"
                    )
                prof = self._profile
                resume_line = job.resume_line_idx
                compiled = job.current_compiled
                bp_xy = compiled.stroke_start_xy.get(
                    job.resume_stroke_idx,
                    (job.saved_wpos["x"], job.saved_wpos["y"]),
                )

            prep_cmds = ["G21", "G90", "G17", "G94"]
            prep_cmds.extend(pen_up_commands(prof))
            prep_cmds.append(
                f"G0 X{bp_xy[0]:.3f} Y{bp_xy[1]:.3f} F{int(round(prof.feed_travel))}"
            )
            self._send_sync_lines(prep_cmds, timeout=5.0)
            self._wait_grbl_idle(timeout=8.0)

            with self._state_lock:
                if self._estop_event.is_set():
                    return {
                        "job_state": self._job_state.value if self._job_state else JobState.ABORTED.value,
                        "machine_state": self._machine_state.value,
                    }
                self._pause_event.clear()
                self._abort_event.clear()
                self._machine_state = MachineState.RUNNING
                self._job_state = JobState.STREAMING

            if self._db is not None:
                self._db.update_job(job.job_id, state=JobState.STREAMING.value)

            self._bus.publish(
                "job.event",
                {
                    "job_id": job.job_id,
                    "event": "resumed",
                    "page_index": job.current_page_index,
                    "message": f"从第 {job.resume_stroke_idx} 笔断点继续书写",
                },
            )
            self._publish_status()
            self._launch_job_stream_thread(start_line=resume_line)
            return {
                "job_state": JobState.STREAMING.value,
                "machine_state": MachineState.RUNNING.value,
            }

    def paper_ready(self, job_id: str | None, page_index: int) -> dict[str, Any]:
        with self._op_lock:
            with self._state_lock:
                job = self._require_job(job_id)
                if self._machine_state != MachineState.PAPER_CHANGE or self._job_state != JobState.WAIT_PAPER:
                    raise MachineStateError(
                        f"Machine is not waiting for paper change (state={self._machine_state.value})"
                    )
                if page_index in job.page_indices:
                    job.current_pos_in_list = job.page_indices.index(page_index)
                elif job.current_pos_in_list + 1 < len(job.page_indices):
                    job.current_pos_in_list += 1
                    page_index = job.current_page_index
                else:
                    raise ValueError(f"Invalid page_index {page_index} for job {job.job_id}")

                job.resume_line_idx = 0
                job.resume_stroke_idx = 0
                self._pause_event.clear()
                self._abort_event.clear()
                self._machine_state = MachineState.RUNNING
                self._job_state = JobState.STREAMING

            if self._db is not None:
                self._db.update_job(
                    job.job_id,
                    state=JobState.STREAMING.value,
                    current_page_index=page_index,
                    last_stroke_index=0,
                    last_line_acked=0,
                )

            self._bus.publish(
                "job.event",
                {
                    "job_id": job.job_id,
                    "event": "started",
                    "page_index": page_index,
                    "message": f"换纸确认完成，开始书写第 {page_index + 1} 页",
                },
            )
            self._publish_status()
            self._launch_job_stream_thread(start_line=0)
            return {"job_state": JobState.STREAMING.value, "page_index": page_index}

    def abort_job(self, job_id: str | None = None) -> dict[str, Any]:
        with self._op_lock:
            with self._state_lock:
                job = self._require_job(job_id)
                was_running = self._machine_state in (MachineState.RUNNING, MachineState.HOLDING)
                self._abort_event.set()
                transport = self._transport
                prof = self._profile

            with self._rx_cond:
                self._rx_cond.notify_all()

            if was_running and transport is not None:
                transport.send_realtime(b"!")

            if self._worker_thread is not None and self._worker_thread.is_alive():
                self._worker_thread.join(timeout=2.0)

            if was_running:
                self._wait_grbl_states(("Hold:0", "Idle"), timeout=2.0)
                self._query_status_sync(timeout=0.4)
                with self._state_lock:
                    wpos = {"x": self._wpos.x, "y": self._wpos.y, "z": self._wpos.z}
                self._deterministic_standstill_lift(wpos, prof)

            if self._transport is not None and self._transport.is_open() and not self._estop_event.is_set():
                try:
                    ppx, ppy = self._page_to_machine(
                        prof.paper_change_pos_mm.x, prof.paper_change_pos_mm.y
                    )
                    cmds = list(pen_up_commands(prof))
                    cmds.append(f"G0 X{ppx:.3f} Y{ppy:.3f} F{int(round(prof.feed_travel))}")
                    self._send_sync_lines(cmds, timeout=4.0)
                    self._wait_grbl_idle(timeout=6.0)
                except Exception as exc:
                    logger.warning("Abort park move warning: %s", exc)

            with self._state_lock:
                self._job_state = JobState.ABORTED
                if (
                    not self._estop_event.is_set()
                    and self._machine_state
                    not in (
                        MachineState.DISCONNECTED,
                        MachineState.ESTOPPED,
                        MachineState.ERROR,
                    )
                ):
                    self._machine_state = MachineState.IDLE
                self._pen_state = "up"
                page_idx = job.current_page_index

            if self._db is not None:
                self._db.update_job(job.job_id, state=JobState.ABORTED.value)

            self._bus.publish(
                "job.event",
                {
                    "job_id": job.job_id,
                    "event": "aborted",
                    "page_index": page_idx,
                    "message": "任务已中止，笔尖已抬起并退回原位",
                },
            )
            self._publish_status()
            return {"job_state": JobState.ABORTED.value}

    def _require_job(self, job_id: str | None) -> ActiveJobContext:
        if self._job is None:
            raise MachineStateError("No active job")
        if job_id is not None and self._job.job_id != job_id:
            raise KeyError(f"Job {job_id} is not the active job ({self._job.job_id})")
        return self._job

    def _launch_job_stream_thread(self, *, start_line: int) -> None:
        if self._worker_thread is not None and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=0.5)
        self._worker_thread = threading.Thread(
            target=self._run_job_page_worker,
            args=(start_line,),
            name="grbl-job-streamer",
            daemon=True,
        )
        self._worker_thread.start()

    def _run_job_page_worker(self, start_line: int) -> None:
        with self._state_lock:
            job = self._job
            if job is None:
                return
            compiled = job.current_compiled
            page_index = job.current_page_index

        try:
            finished = self._stream_lines(
                compiled.lines,
                is_job=True,
                start_line=start_line,
                compiled=compiled,
                job=job,
            )
            if not finished:
                return

            if not self._wait_grbl_idle(timeout=30.0):
                if self._pause_event.is_set() or self._abort_event.is_set() or self._estop_event.is_set():
                    return

            if self._pause_event.is_set() or self._abort_event.is_set() or self._estop_event.is_set():
                return

            self._publish_job_progress(job, compiled, len(compiled.lines) - 1, force=True)
            with self._state_lock:
                wpos_snap = {
                    "x": round(self._wpos.x, 3),
                    "y": round(self._wpos.y, 3),
                    "z": round(self._wpos.z, 3),
                }
            if self._db is not None:
                self._db.save_checkpoint(
                    job_id=job.job_id,
                    page_index=page_index,
                    stroke_index=len(compiled.stroke_to_line),
                    line_acked=len(compiled.lines),
                    wpos=wpos_snap,
                )

            self._bus.publish(
                "job.event",
                {
                    "job_id": job.job_id,
                    "event": "page_done",
                    "page_index": page_index,
                    "message": f"第 {page_index + 1} 页书写完成",
                },
            )

            with self._state_lock:
                if self._estop_event.is_set() or self._abort_event.is_set():
                    return
                has_next = (job.current_pos_in_list + 1) < len(job.page_indices)
                next_page = job.page_indices[job.current_pos_in_list + 1] if has_next else None
                if has_next and next_page is not None:
                    self._machine_state = MachineState.PAPER_CHANGE
                    self._job_state = JobState.WAIT_PAPER
                    self._pen_state = "up"
                else:
                    self._machine_state = MachineState.IDLE
                    self._job_state = JobState.COMPLETED
                    self._pen_state = "up"

            if has_next and next_page is not None:
                if self._db is not None:
                    self._db.update_job(
                        job.job_id,
                        state=JobState.WAIT_PAPER.value,
                        current_page_index=next_page,
                    )
                self._bus.publish(
                    "job.event",
                    {
                        "job_id": job.job_id,
                        "event": "paper_change_required",
                        "page_index": next_page,
                        "message": f"第 {page_index + 1} 页已完成，请更换新纸后确认继续第 {next_page + 1} 页",
                    },
                )
            else:
                if self._db is not None:
                    self._db.update_job(job.job_id, state=JobState.COMPLETED.value)
                self._bus.publish(
                    "job.event",
                    {
                        "job_id": job.job_id,
                        "event": "job_done",
                        "page_index": page_index,
                        "message": "全部页面书写完成",
                    },
                )
                if self._profile.sleep_after_job:
                    self._enter_sleep()
            self._publish_status()

        except Exception as exc:
            logger.exception("Job streaming worker failed: %s", exc)
            with self._state_lock:
                self._job_state = JobState.FAILED
                if self._machine_state == MachineState.RUNNING and not self._estop_event.is_set():
                    self._machine_state = MachineState.ALARM
            if self._db is not None:
                self._db.update_job(
                    job.job_id, state=JobState.FAILED.value, error_message=str(exc)
                )
            self._bus.publish(
                "job.event",
                {
                    "job_id": job.job_id,
                    "event": "failed",
                    "page_index": page_index,
                    "message": f"任务执行异常: {exc}",
                },
            )
            self._publish_status()

    def _publish_job_progress(
        self,
        job: ActiveJobContext,
        compiled: CompiledGcode,
        acked_line: int,
        *,
        force: bool = False,
    ) -> None:
        line_total = max(1, len(compiled.lines))
        clamped_line = max(0, min(acked_line, line_total - 1))
        stroke_total = max(1, len(compiled.stroke_to_line))
        s_idx = (
            compiled.line_to_stroke[clamped_line]
            if clamped_line < len(compiled.line_to_stroke)
            else -1
        )
        if s_idx < 0:
            s_idx = stroke_total if force else job.resume_stroke_idx
        else:
            job.resume_stroke_idx = s_idx

        pct = 100.0 if force else round(min(99.9, (clamped_line + 1) / line_total * 100.0), 2)
        elapsed_s = round(time.monotonic() - job.started_at, 2)
        eta_s = round(max(0.0, compiled.est_s * (1.0 - pct / 100.0)), 2)

        with self._state_lock:
            pgx, pgy = self._machine_to_page(self._wpos.x, self._wpos.y)
            pen_xy = {"x": round(pgx, 2), "y": round(pgy, 2)}
            wpos_snap = {
                "x": round(self._wpos.x, 3),
                "y": round(self._wpos.y, 3),
                "z": round(self._wpos.z, 3),
            }
            jstate = self._job_state.value if self._job_state else JobState.STREAMING.value

        payload = {
            "job_id": job.job_id,
            "job_state": jstate,
            "page_index": job.current_page_index,
            "page_count": len(job.page_indices),
            "stroke_index": s_idx,
            "stroke_total": stroke_total,
            "seg_index": clamped_line + 1,
            "seg_total": line_total,
            "line_acked": clamped_line + 1,
            "line_total": line_total,
            "pct": pct,
            "pen_xy": pen_xy,
            "elapsed_s": elapsed_s,
            "eta_s": eta_s,
            "draw_mm": compiled.draw_mm,
            "travel_mm": compiled.travel_mm,
        }
        job.last_progress = payload
        self._bus.publish("job.progress", payload)

        if self._db is not None and (
            force or (s_idx >= 0 and s_idx - job.last_checkpoint_stroke >= 20)
        ):
            job.last_checkpoint_stroke = s_idx
            self._db.save_checkpoint(
                job_id=job.job_id,
                page_index=job.current_page_index,
                stroke_index=s_idx,
                line_acked=clamped_line + 1,
                wpos=wpos_snap,
            )
            self._db.update_job(job.job_id, progress=payload)
