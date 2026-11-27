"""WebSocket /ws/telemetry endpoint implementing Contract v1 S->C & C->S protocol."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from handwrite.api.schemas import WsEnvelope
from handwrite.api.state import AppContext

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/telemetry")
async def ws_telemetry(websocket: WebSocket) -> None:
    await websocket.accept()
    ctx: AppContext = websocket.app.state.ctx
    loop = asyncio.get_running_loop()
    sub = ctx.event_bus.subscribe(loop=loop, include_serial_log=False)

    # Send immediate snapshot on connect so UI syncs without waiting for next poll
    try:
        init_env = WsEnvelope(
            v=1,
            type="machine.status",
            seq=ctx.event_bus.seq,
            ts=int(time.time() * 1000),
            data=ctx.machine.get_status_snapshot(),
        ).model_dump()
        await websocket.send_json(init_env)
    except Exception:
        ctx.event_bus.unsubscribe(sub)
        return

    async def _sender() -> None:
        while True:
            msg = await sub.queue.get()
            await websocket.send_json(msg)

    async def _receiver() -> None:
        while True:
            payload = await websocket.receive_json()
            if not isinstance(payload, dict):
                continue
            msg_type = str(payload.get("type", ""))
            data: dict[str, Any] = (
                payload.get("data") if isinstance(payload.get("data"), dict) else {}
            )

            if msg_type == "ping":
                now_ms = int(time.time() * 1000)
                pong = WsEnvelope(
                    v=1,
                    type="pong",
                    seq=ctx.event_bus.seq,
                    ts=now_ms,
                    data={"ts": now_ms},
                ).model_dump()
                await websocket.send_json(pong)

            elif msg_type == "subscribe":
                serial_log = bool(data.get("serial_log", False))
                ctx.event_bus.set_serial_log(sub, serial_log)

            elif msg_type == "jog":
                try:
                    dx = float(data.get("dx", 0.0))
                    dy = float(data.get("dy", 0.0))
                    feed = float(data["feed"]) if "feed" in data and data["feed"] is not None else None
                    await asyncio.to_thread(ctx.machine.jog, dx, dy, feed)
                except Exception as exc:
                    ctx.event_bus.publish(
                        "alarm",
                        {"code": "JOG_REJECTED", "message": str(exc), "severity": "warn"},
                    )

            elif msg_type == "jog.cancel":
                await asyncio.to_thread(ctx.machine.jog_cancel)

            elif msg_type == "estop":
                # Execute immediately off the event loop so 0x18 fires with minimal latency
                await asyncio.to_thread(ctx.machine.estop)

    sender_task = asyncio.create_task(_sender())
    receiver_task = asyncio.create_task(_receiver())

    try:
        done, pending = await asyncio.wait(
            {sender_task, receiver_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc is not None and not isinstance(exc, (WebSocketDisconnect, asyncio.CancelledError)):
                logger.debug("WS telemetry task ended with: %s", exc)
    except WebSocketDisconnect:
        pass
    finally:
        sender_task.cancel()
        receiver_task.cancel()
        ctx.event_bus.unsubscribe(sub)
