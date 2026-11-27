"""GRBL 1.1 character-counting streaming buffer (strict in_flight_bytes <= rx_buffer)."""

from __future__ import annotations

from collections import deque
import re
import threading

_PAREN_COMMENT_RE = re.compile(r"\([^)]*\)")


class CharacterCountingStreamer:
    """Tracks in-flight G-code line byte lengths for GRBL's 128-byte RX buffer.

    Guarantees `in_flight_bytes <= effective_budget <= rx_buffer` at all times.
    """

    def __init__(
        self,
        rx_buffer: int = 128,
        *,
        safety_margin: int = 8,
        max_lines: int | None = None,
    ) -> None:
        """``max_lines=1`` gives send-response (单步) streaming: wait for each ``ok``."""
        if rx_buffer < 16:
            raise ValueError("rx_buffer must be >= 16 bytes")
        if max_lines is not None and max_lines < 1:
            raise ValueError("max_lines must be >= 1")
        self.max_lines = max_lines
        self.rx_buffer = int(rx_buffer)
        self.safety_margin = max(0, min(int(safety_margin), self.rx_buffer - 16))
        self.effective_budget = self.rx_buffer - self.safety_margin

        self._lock = threading.RLock()
        self._in_flight: deque[tuple[int, int]] = deque()
        self._in_flight_bytes: int = 0
        self._peak_in_flight_bytes: int = 0
        self._last_acked_line: int = -1
        self._sent_count: int = 0
        self._acked_count: int = 0

    @staticmethod
    def clean_line(raw: str) -> str:
        """Strip G-code comments and surrounding whitespace."""
        line = _PAREN_COMMENT_RE.sub("", raw)
        if ";" in line:
            line = line.split(";", 1)[0]
        return line.strip()

    @classmethod
    def line_byte_len(cls, raw: str) -> int:
        """Return exact byte length transmitted to GRBL including trailing LF."""
        cleaned = cls.clean_line(raw)
        if not cleaned:
            return 0
        return len(cleaned.encode("ascii", errors="ignore")) + 1

    @property
    def in_flight_bytes(self) -> int:
        with self._lock:
            return self._in_flight_bytes

    @property
    def peak_in_flight_bytes(self) -> int:
        with self._lock:
            return self._peak_in_flight_bytes

    @property
    def in_flight_count(self) -> int:
        with self._lock:
            return len(self._in_flight)

    @property
    def last_acked_line(self) -> int:
        with self._lock:
            return self._last_acked_line

    @property
    def acked_count(self) -> int:
        with self._lock:
            return self._acked_count

    @property
    def sent_count(self) -> int:
        with self._lock:
            return self._sent_count

    @property
    def is_drained(self) -> bool:
        with self._lock:
            return len(self._in_flight) == 0

    @property
    def rx_available(self) -> int:
        with self._lock:
            return max(0, self.rx_buffer - self._in_flight_bytes)

    def can_send(self, raw_line: str) -> bool:
        nbytes = self.line_byte_len(raw_line)
        if nbytes == 0:
            return True
        with self._lock:
            if self.max_lines is not None and len(self._in_flight) >= self.max_lines:
                return False
            # Allow a single line up to rx_buffer if buffer is currently empty
            if not self._in_flight and nbytes <= self.rx_buffer:
                return True
            return (self._in_flight_bytes + nbytes) <= self.effective_budget

    def on_sent(self, line_no: int, raw_line: str) -> int:
        """Record a sent line. Raises BufferError if it would exceed rx_buffer."""
        nbytes = self.line_byte_len(raw_line)
        if nbytes == 0:
            return 0
        with self._lock:
            if self._in_flight_bytes + nbytes > self.rx_buffer:
                raise BufferError(
                    f"RX buffer overflow prevented: {self._in_flight_bytes} + {nbytes} > {self.rx_buffer}"
                )
            self._in_flight.append((line_no, nbytes))
            self._in_flight_bytes += nbytes
            self._sent_count += 1
            if self._in_flight_bytes > self._peak_in_flight_bytes:
                self._peak_in_flight_bytes = self._in_flight_bytes
            return nbytes

    def on_ok(self) -> int | None:
        """Acknowledge oldest in-flight line and release its RX bytes."""
        with self._lock:
            if not self._in_flight:
                return None
            line_no, nbytes = self._in_flight.popleft()
            self._in_flight_bytes = max(0, self._in_flight_bytes - nbytes)
            self._last_acked_line = line_no
            self._acked_count += 1
            return line_no

    def on_error(self) -> int | None:
        """Pop oldest in-flight line on GRBL `error:N` and return its line index."""
        with self._lock:
            if not self._in_flight:
                return None
            line_no, nbytes = self._in_flight.popleft()
            self._in_flight_bytes = max(0, self._in_flight_bytes - nbytes)
            return line_no

    def reset(self) -> None:
        """Clear all in-flight state (e.g. after 0x18 soft reset or new page)."""
        with self._lock:
            self._in_flight.clear()
            self._in_flight_bytes = 0
            self._sent_count = 0
            self._acked_count = 0
            self._last_acked_line = -1
