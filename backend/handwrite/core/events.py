"""Thread-safe async EventBus bridging background GRBL/task threads to WebSocket clients."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import threading
import time
from typing import Any, Callable

from handwrite.api.schemas import WsEnvelope

HIGH_FREQ_EVENTS = frozenset({"machine.status", "job.progress", "serial.log"})


@dataclass(eq=False)
class EventSubscriber:
    """Subscription handle owned by a WebSocket connection."""

    queue: asyncio.Queue[dict[str, Any]]
    loop: asyncio.AbstractEventLoop
    include_serial_log: bool = False


class EventBus:
    """Monotonically sequenced pub-sub bus safe for cross-thread publishing."""

    def __init__(self, *, max_queue_size: int = 256) -> None:
        self._lock = threading.RLock()
        self._seq: int = 0
        self._max_queue_size = max_queue_size
        self._subscribers: set[EventSubscriber] = set()
        self._sync_listeners: list[Callable[[dict[str, Any]], None]] = []

    @property
    def seq(self) -> int:
        with self._lock:
            return self._seq

    def subscribe(
        self,
        loop: asyncio.AbstractEventLoop | None = None,
        *,
        include_serial_log: bool = False,
    ) -> EventSubscriber:
        target_loop = loop or asyncio.get_running_loop()
        sub = EventSubscriber(
            queue=asyncio.Queue(maxsize=self._max_queue_size),
            loop=target_loop,
            include_serial_log=include_serial_log,
        )
        with self._lock:
            self._subscribers.add(sub)
        return sub

    def unsubscribe(self, sub: EventSubscriber) -> None:
        with self._lock:
            self._subscribers.discard(sub)

    def set_serial_log(self, sub: EventSubscriber, enabled: bool) -> None:
        with self._lock:
            sub.include_serial_log = bool(enabled)

    def add_sync_listener(self, cb: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            self._sync_listeners.append(cb)

    def remove_sync_listener(self, cb: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            if cb in self._sync_listeners:
                self._sync_listeners.remove(cb)

    def publish(self, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """Publish an event from any thread; returns the serialized WsEnvelope dict."""
        ts_ms = int(time.time() * 1000)
        with self._lock:
            self._seq += 1
            envelope = WsEnvelope(
                v=1,
                type=event_type,
                seq=self._seq,
                ts=ts_ms,
                data=data,
            ).model_dump()
            subs = list(self._subscribers)
            sync_cbs = list(self._sync_listeners)

        is_serial = event_type == "serial.log"
        is_high_freq = event_type in HIGH_FREQ_EVENTS

        for sub in subs:
            if is_serial and not sub.include_serial_log:
                continue
            if sub.loop.is_closed():
                continue
            try:
                sub.loop.call_soon_threadsafe(
                    self._enqueue_on_loop, sub.queue, envelope, is_high_freq
                )
            except RuntimeError:
                # Loop closed between check and call_soon_threadsafe
                continue

        for cb in sync_cbs:
            try:
                cb(envelope)
            except Exception:
                pass

        return envelope

    @staticmethod
    def _enqueue_on_loop(
        queue: asyncio.Queue[dict[str, Any]],
        envelope: dict[str, Any],
        is_high_freq: bool,
    ) -> None:
        if queue.full():
            if is_high_freq:
                # Drop oldest entry to keep telemetry fresh without stalling producers
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            else:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
        try:
            queue.put_nowait(envelope)
        except asyncio.QueueFull:
            pass
