"""Background TaskManager for parse, compose, and font_import tasks."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import logging
import threading
from typing import Any, Callable
import uuid

from handwrite.api.schemas import TaskKind, TaskState
from handwrite.core.db import Database
from handwrite.core.events import EventBus

logger = logging.getLogger(__name__)

ProgressReporter = Callable[[str, float, str, int | None, int | None], None]


class TaskManager:
    """Runs background tasks in a worker pool and streams task.progress events."""

    def __init__(
        self,
        db: Database,
        event_bus: EventBus,
        *,
        max_workers: int = 4,
    ) -> None:
        self._db = db
        self._bus = event_bus
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="hw-task")
        self._lock = threading.RLock()
        self._tasks: dict[str, dict[str, Any]] = {}

    def create_task(
        self,
        kind: TaskKind,
        *,
        stage: str = "queued",
        message: str = "",
        task_id: str | None = None,
    ) -> str:
        tid = task_id or f"tsk_{uuid.uuid4().hex[:10]}"
        record: dict[str, Any] = {
            "task_id": tid,
            "kind": kind,
            "state": "pending",
            "stage": stage,
            "pct": 0.0,
            "page": None,
            "page_count": None,
            "message": message,
            "result": None,
            "error": None,
        }
        with self._lock:
            self._tasks[tid] = record
        self._db.upsert_task(record)
        self._publish(record)
        return tid

    def update_task(
        self,
        task_id: str,
        *,
        state: TaskState | None = None,
        stage: str | None = None,
        pct: float | None = None,
        page: int | None = None,
        page_count: int | None = None,
        message: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                loaded = self._db.get_task(task_id)
                if loaded is None:
                    raise KeyError(f"Task not found: {task_id}")
                record = loaded
                self._tasks[task_id] = record
            if state is not None:
                record["state"] = state
            if stage is not None:
                record["stage"] = stage
            if pct is not None:
                record["pct"] = round(max(0.0, min(100.0, float(pct))), 2)
            if page is not None:
                record["page"] = int(page)
            if page_count is not None:
                record["page_count"] = int(page_count)
            if message is not None:
                record["message"] = message
            if result is not None:
                record["result"] = result
            if error is not None:
                record["error"] = error
            snapshot = dict(record)

        self._db.upsert_task(snapshot)
        self._publish(snapshot)
        return snapshot

    def submit(
        self,
        kind: TaskKind,
        fn: Callable[[str, ProgressReporter], dict[str, Any] | None],
        *,
        initial_stage: str = "queued",
        initial_message: str = "",
        task_id: str | None = None,
    ) -> str:
        tid = self.create_task(
            kind, stage=initial_stage, message=initial_message, task_id=task_id
        )

        def _report(
            stage: str,
            pct: float,
            message: str = "",
            page: int | None = None,
            page_count: int | None = None,
        ) -> None:
            self.update_task(
                tid,
                state="running",
                stage=stage,
                pct=pct,
                page=page,
                page_count=page_count,
                message=message,
            )

        def _runner() -> None:
            try:
                self.update_task(tid, state="running", stage="starting", pct=1.0)
                result = fn(tid, _report)
                self.update_task(
                    tid,
                    state="done",
                    stage="done",
                    pct=100.0,
                    message="完成",
                    result=result if isinstance(result, dict) else None,
                )
            except Exception as exc:
                logger.exception("Background task %s (%s) failed: %s", tid, kind, exc)
                self.update_task(
                    tid,
                    state="failed",
                    stage="failed",
                    message=str(exc),
                    error=str(exc),
                )

        self._pool.submit(_runner)
        return tid

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            rec = self._tasks.get(task_id)
            if rec is not None:
                return self._format_task(rec)
        return self._db.get_task(task_id)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=False)

    @staticmethod
    def _format_task(rec: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {
            "task_id": rec["task_id"],
            "kind": rec["kind"],
            "state": rec["state"],
            "stage": rec["stage"],
            "pct": rec["pct"],
            "message": rec.get("message", ""),
        }
        if rec.get("page") is not None:
            out["page"] = rec["page"]
        if rec.get("page_count") is not None:
            out["page_count"] = rec["page_count"]
        if rec.get("result") is not None:
            out["result"] = rec["result"]
        if rec.get("error") is not None:
            out["error"] = rec["error"]
        return out

    def _publish(self, rec: dict[str, Any]) -> None:
        payload: dict[str, Any] = {
            "task_id": rec["task_id"],
            "kind": rec["kind"],
            "state": rec["state"],
            "stage": rec["stage"],
            "pct": rec["pct"],
            "message": rec.get("message", ""),
        }
        if rec.get("page") is not None:
            payload["page"] = rec["page"]
        if rec.get("page_count") is not None:
            payload["page_count"] = rec["page_count"]
        if rec.get("result") is not None:
            payload["result"] = rec["result"]
        if rec.get("error") is not None:
            payload["error"] = rec["error"]
        self._bus.publish("task.progress", payload)
