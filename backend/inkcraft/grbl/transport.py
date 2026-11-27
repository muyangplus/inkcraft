"""SerialTransport abstract interface and PySerialTransport with priority realtime byte queue."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
import logging
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

LineCallback = Callable[[str], None]
LogCallback = Callable[[str, str], None]
DisconnectCallback = Callable[[str], None]


def list_serial_ports() -> list[dict[str, Any]]:
    """Enumerate available USB/serial ports on the host machine."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []

    ports: list[dict[str, Any]] = []
    try:
        for p in list_ports.comports():
            ports.append(
                {
                    "device": p.device,
                    "description": p.description or "",
                    "hwid": p.hwid or "",
                    "vid": p.vid,
                    "pid": p.pid,
                }
            )
    except Exception as exc:
        logger.warning("Failed to list serial ports: %s", exc)
    return ports


class SerialTransport(ABC):
    """Abstract GRBL serial transport implemented by PySerialTransport and MockGrblTransport."""

    def __init__(self) -> None:
        self._on_line: LineCallback | None = None
        self._on_log: LogCallback | None = None
        self._on_disconnect: DisconnectCallback | None = None

    def set_callbacks(
        self,
        *,
        on_line: LineCallback | None = None,
        on_log: LogCallback | None = None,
        on_disconnect: DisconnectCallback | None = None,
    ) -> None:
        self._on_line = on_line
        self._on_log = on_log
        self._on_disconnect = on_disconnect

    @abstractmethod
    def open(self) -> None:
        ...

    @abstractmethod
    def close(self) -> None:
        ...

    @abstractmethod
    def is_open(self) -> bool:
        ...

    @abstractmethod
    def send_line(self, line: str) -> None:
        ...

    @abstractmethod
    def send_realtime(self, cmd: bytes) -> None:
        ...

    @abstractmethod
    def clear_tx_queue(self) -> None:
        ...


class PySerialTransport(SerialTransport):
    """Real USB virtual serial transport running a dedicated SerialIOThread."""

    def __init__(self, port: str, baud: int = 115200) -> None:
        super().__init__()
        self.port = port
        self.baud = int(baud)
        self._ser: Any = None
        self._lock = threading.Lock()
        self._rt_queue: deque[bytes] = deque()
        self._tx_queue: deque[str] = deque()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def open(self) -> None:
        import serial

        self._stop.clear()
        self._ser = serial.Serial(
            port=self.port,
            baudrate=self.baud,
            timeout=0.015,
            write_timeout=0.5,
        )
        # Wake up GRBL (Arduino/CH340 DTR reset settles briefly)
        time.sleep(0.15)
        try:
            self._ser.reset_input_buffer()
        except Exception:
            pass
        self._thread = threading.Thread(
            target=self._io_loop, name=f"grbl-io-{self.port}", daemon=True
        )
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    def is_open(self) -> bool:
        return bool(self._ser is not None and getattr(self._ser, "is_open", False) and not self._stop.is_set())

    def send_line(self, line: str) -> None:
        cleaned = line.strip()
        if not cleaned:
            return
        with self._lock:
            self._tx_queue.append(cleaned)
        self._wake.set()

    def send_realtime(self, cmd: bytes) -> None:
        if not cmd:
            return
        with self._lock:
            if cmd == b"\x18":
                # Highest priority: preempt all pending lines and realtime bytes
                self._tx_queue.clear()
                self._rt_queue.appendleft(cmd)
            else:
                self._rt_queue.append(cmd)
        self._wake.set()

    def clear_tx_queue(self) -> None:
        with self._lock:
            self._tx_queue.clear()

    def _io_loop(self) -> None:
        rx_buf = bytearray()
        while not self._stop.is_set():
            ser = self._ser
            if ser is None or not ser.is_open:
                break
            try:
                # 1. Drain priority realtime bytes first
                while True:
                    with self._lock:
                        rt = self._rt_queue.popleft() if self._rt_queue else None
                    if rt is None:
                        break
                    ser.write(rt)
                    ser.flush()
                    if self._on_log is not None and rt != b"?":
                        label = f"0x{rt[0]:02x}" if rt[0] < 32 or rt[0] >= 127 else rt.decode("ascii", "ignore")
                        self._on_log("tx", label)

                # 2. Drain normal G-code lines
                while True:
                    with self._lock:
                        if self._rt_queue:
                            break
                        line = self._tx_queue.popleft() if self._tx_queue else None
                    if line is None:
                        break
                    ser.write((line + "\n").encode("ascii", errors="ignore"))
                    ser.flush()
                    if self._on_log is not None:
                        self._on_log("tx", line)

                # 3. Read incoming bytes
                waiting = getattr(ser, "in_waiting", 0)
                chunk = ser.read(waiting if waiting > 0 else 1)
                if chunk:
                    rx_buf.extend(chunk)
                    while b"\n" in rx_buf:
                        idx = rx_buf.index(b"\n")
                        raw_bytes = bytes(rx_buf[:idx])
                        del rx_buf[: idx + 1]
                        text = raw_bytes.decode("ascii", errors="replace").strip()
                        if text:
                            if self._on_log is not None and not text.startswith("<"):
                                self._on_log("rx", text)
                            if self._on_line is not None:
                                self._on_line(text)
            except Exception as exc:
                if not self._stop.is_set():
                    logger.error("Serial IO error on %s: %s", self.port, exc)
                    self._stop.set()
                    if self._on_disconnect is not None:
                        self._on_disconnect(str(exc))
                break
