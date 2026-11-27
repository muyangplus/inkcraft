"""Background task status lookup endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from handwrite.api.state import ApiError, AppContext

router = APIRouter()


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    task = ctx.tasks.get_task(task_id)
    if task is None:
        raise ApiError(404, "TASK_NOT_FOUND", f"任务不存在: {task_id}")
    return task
