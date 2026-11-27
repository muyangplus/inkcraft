"""GRBL machine connection, profiles, jogging, zeroing, pen test, framing, unlock, and E-Stop routes."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request

from handwrite.api.schemas import (
    FrameCheckRequest,
    JogRequest,
    MachineConnectRequest,
    MachineProfile,
    MoveToRequest,
    MoveToStartRequest,
    PenRequest,
    RawCommandRequest,
    ZeroRequest,
)
from handwrite.api.state import ApiError, AppContext

router = APIRouter()


@router.get("/machine/ports")
async def list_machine_ports(request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    return {"ports": ctx.machine.list_ports()}


@router.get("/machine/profiles")
async def list_machine_profiles(request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    active_id, profiles = ctx.db.list_profiles()
    return {
        "active_profile_id": active_id,
        "profiles": [p.model_dump() for p in profiles],
    }


@router.put("/machine/profiles/{profile_id}")
async def save_machine_profile(
    profile_id: str,
    body: MachineProfile,
    request: Request,
) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    profile = body.model_copy(update={"profile_id": profile_id})
    saved = ctx.db.upsert_profile(profile)
    ctx.machine.update_active_profile(saved)

    if saved.pen.mode == "servo" and saved.pen.servo_up.strip().upper() != "M5":
        ctx.event_bus.publish(
            "alarm",
            {
                "code": "SERVO_FAILSAFE_WARN",
                "message": (
                    f"舵机抬笔指令当前为 '{saved.pen.servo_up}' 而非 M5："
                    "建议将硬件接线配置为 M5=抬笔 以保证急停/复位自动抬笔安全"
                ),
                "severity": "warn",
            },
        )
    return {"profile": saved.model_dump()}


@router.post("/machine/connect")
async def connect_machine(
    body: MachineConnectRequest,
    request: Request,
) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    profile = ctx.db.get_profile(body.profile_id)
    if profile is None:
        profile = ctx.get_active_profile()
    else:
        ctx.db.set_active_profile(profile.profile_id)

    try:
        return await asyncio.to_thread(
            ctx.machine.connect,
            body.port,
            body.baud,
            profile,
            body.mock,
        )
    except Exception as exc:
        raise ApiError(502, "CONNECT_FAILED", str(exc)) from exc


@router.post("/machine/disconnect")
async def disconnect_machine(request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    return await asyncio.to_thread(ctx.machine.disconnect)


@router.post("/machine/jog")
async def jog_machine(body: JogRequest, request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    try:
        return await asyncio.to_thread(ctx.machine.jog, body.dx, body.dy, body.feed)
    except ValueError as exc:
        raise ApiError(422, "SOFT_LIMIT", str(exc)) from exc


@router.post("/machine/jog/cancel")
async def jog_cancel_machine(request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    return await asyncio.to_thread(ctx.machine.jog_cancel)


@router.post("/machine/zero")
async def zero_machine(body: ZeroRequest, request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    return await asyncio.to_thread(ctx.machine.zero, body.axes)


@router.post("/machine/pen")
async def set_machine_pen(body: PenRequest, request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    try:
        return await asyncio.to_thread(
            ctx.machine.set_pen,
            body.state,
            override_cmd=body.override_cmd,
            override_z_mm=body.override_z_mm,
            override_z_feed=body.override_z_feed,
        )
    except ValueError as exc:
        raise ApiError(422, "INVALID_PEN_CMD", str(exc)) from exc


@router.post("/machine/goto-zero")
async def goto_zero_machine(request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    return await asyncio.to_thread(ctx.machine.goto_zero)


@router.post("/machine/move-to")
async def move_to_machine(body: MoveToRequest, request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    try:
        return await asyncio.to_thread(
            ctx.machine.move_to,
            body.x,
            body.y,
            feed=body.feed,
            pen_up=body.pen_up,
        )
    except ValueError as exc:
        raise ApiError(422, "SOFT_LIMIT", str(exc)) from exc


@router.post("/machine/move-to-start")
async def move_to_start_machine(
    body: MoveToStartRequest,
    request: Request,
) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    page = ctx.load_composed_page(body.layout_id, body.page_index)
    if page is None:
        raise ApiError(
            404,
            "PAGE_NOT_FOUND",
            f"排版 '{body.layout_id}' 第 {body.page_index + 1} 页不存在",
        )
    try:
        return await asyncio.to_thread(ctx.machine.move_to_start, page)
    except ValueError as exc:
        raise ApiError(422, "INVALID_TARGET", str(exc)) from exc


@router.post("/machine/home")
async def home_machine(request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    return await asyncio.to_thread(ctx.machine.home)


@router.post("/machine/raw")
async def raw_command_machine(body: RawCommandRequest, request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    try:
        return await asyncio.to_thread(ctx.machine.send_raw_command, body.command)
    except ValueError as exc:
        raise ApiError(422, "INVALID_COMMAND", str(exc)) from exc


@router.post("/machine/frame")
async def frame_check_machine(
    body: FrameCheckRequest,
    request: Request,
) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    page = ctx.load_composed_page(body.layout_id, body.page_index)
    if page is None:
        raise ApiError(
            404,
            "PAGE_NOT_FOUND",
            f"排版 '{body.layout_id}' 第 {body.page_index + 1} 页不存在",
        )
    return await asyncio.to_thread(
        ctx.machine.frame_check,
        page.bbox,
        page_width_mm=page.width_mm,
        page_height_mm=page.height_mm,
    )


@router.post("/machine/unlock")
async def unlock_machine(request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    return await asyncio.to_thread(ctx.machine.unlock)


@router.post("/machine/estop")
async def estop_machine(request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    return await asyncio.to_thread(ctx.machine.estop)
