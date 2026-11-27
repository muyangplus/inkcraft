"""Writing job creation, inspection, pause, pen-change, resume, paper-ready, and abort routes."""

from __future__ import annotations

import asyncio
from typing import Any
import uuid

from fastapi import APIRouter, Request

from handwrite.api.schemas import CreateJobRequest, PaperReadyRequest
from handwrite.api.state import ApiError, AppContext

router = APIRouter()


@router.post("/jobs", status_code=201)
async def create_job(
    body: CreateJobRequest,
    request: Request,
) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    layout = ctx.db.get_layout(body.layout_id)
    if layout is None:
        raise ApiError(404, "LAYOUT_NOT_FOUND", f"排版结果不存在: {body.layout_id}")

    page_count = int(layout["page_count"])
    if page_count <= 0:
        raise ApiError(422, "EMPTY_LAYOUT", "排版结果为空，无可书写页面")

    page_indices = (
        list(body.page_indices)
        if body.page_indices is not None and len(body.page_indices) > 0
        else list(range(page_count))
    )
    for idx in page_indices:
        if idx < 0 or idx >= page_count:
            raise ApiError(
                422,
                "INVALID_PAGE_INDEX",
                f"页码 {idx} 超出范围 [0, {page_count - 1}]",
            )

    profile = ctx.machine.profile or ctx.get_active_profile()

    # Compile and strictly validate workspace bounds for every requested page before sending to hardware
    compiled_pages = {}
    for p_idx in page_indices:
        compiled_pages[p_idx] = await asyncio.to_thread(
            ctx.compile_layout_page,
            body.layout_id,
            p_idx,
            profile,
            validate_bounds=True,
        )

    job_id = f"job_{uuid.uuid4().hex[:10]}"
    return await asyncio.to_thread(
        ctx.machine.start_job,
        job_id,
        body.layout_id,
        compiled_pages,
        page_indices,
        body.start_page_index,
    )


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    live = ctx.machine.get_active_job_snapshot(job_id)
    if live is not None:
        return live
    row = ctx.db.get_job(job_id)
    if row is None:
        raise ApiError(404, "JOB_NOT_FOUND", f"书写任务不存在: {job_id}")
    return {
        "job_id": row["job_id"],
        "layout_id": row["layout_id"],
        "job_state": row["job_state"],
        "page_indices": row["page_indices"],
        "current_page_index": row["current_page_index"],
        "progress": row["progress"],
    }


@router.post("/jobs/{job_id}/pause")
async def pause_job(job_id: str, request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    try:
        return await asyncio.to_thread(ctx.machine.pause_job, job_id)
    except KeyError as exc:
        raise ApiError(404, "JOB_NOT_FOUND", str(exc)) from exc


@router.post("/jobs/{job_id}/resume")
async def resume_job(job_id: str, request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    try:
        return await asyncio.to_thread(ctx.machine.resume_job, job_id)
    except KeyError as exc:
        raise ApiError(404, "JOB_NOT_FOUND", str(exc)) from exc


@router.post("/jobs/{job_id}/pen-change")
async def pen_change_job(job_id: str, request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    try:
        return await asyncio.to_thread(ctx.machine.enter_pen_change, job_id)
    except KeyError as exc:
        raise ApiError(404, "JOB_NOT_FOUND", str(exc)) from exc


@router.post("/jobs/{job_id}/paper-ready")
async def paper_ready_job(
    job_id: str,
    body: PaperReadyRequest,
    request: Request,
) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    try:
        return await asyncio.to_thread(ctx.machine.paper_ready, job_id, body.page_index)
    except KeyError as exc:
        raise ApiError(404, "JOB_NOT_FOUND", str(exc)) from exc
    except ValueError as exc:
        raise ApiError(422, "INVALID_PAGE_INDEX", str(exc)) from exc


@router.post("/jobs/{job_id}/abort")
async def abort_job(job_id: str, request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    try:
        return await asyncio.to_thread(ctx.machine.abort_job, job_id)
    except KeyError as exc:
        raise ApiError(404, "JOB_NOT_FOUND", str(exc)) from exc
