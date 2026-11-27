"""HWS1 compact binary stroke codec (u16le anchor + zigzag-varint deltas)."""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Sequence

import numpy as np

HWS1_MAGIC = b"HWS1"
FLAG_HAS_PRESSURE = 0x01
FLAG_HAS_TIME = 0x02
MAX_STROKES = 64


@dataclass(frozen=True, slots=True)
class DecodedStrokes:
    strokes: list[np.ndarray]
    pressure: list[np.ndarray] | None = None
    dt_ms: list[np.ndarray] | None = None


def _encode_uvarint(buf: bytearray, value: int) -> None:
    if value < 0:
        raise ValueError(f"uvarint requires non-negative value, got {value}")
    while value >= 0x80:
        buf.append((value & 0x7F) | 0x80)
        value >>= 7
    buf.append(value)


def _decode_uvarint(data: memoryview, offset: int) -> tuple[int, int]:
    result = 0
    shift = 0
    length = len(data)
    while offset < length:
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result, offset
        shift += 7
        if shift > 35:
            raise ValueError("HWS1 varint overflow")
    raise ValueError("Truncated HWS1 varint")


def _zigzag_encode(n: int) -> int:
    return (n << 1) ^ (n >> 31) if n >= 0 else ((-n << 1) - 1)


def _zigzag_decode(z: int) -> int:
    return (z >> 1) ^ -(z & 1)


def encode_strokes(
    strokes: Sequence[np.ndarray | Sequence[tuple[int, int]]],
    *,
    pressure: Sequence[Sequence[int]] | None = None,
    dt: Sequence[Sequence[int]] | None = None,
) -> bytes:
    """Encode strokes in 0..1000 integer glyph coordinates to HWS1 BLOB."""
    if not strokes:
        raise ValueError("At least one stroke is required")
    if len(strokes) > MAX_STROKES:
        raise ValueError(f"Stroke count {len(strokes)} exceeds max {MAX_STROKES}")

    flags = 0
    if pressure is not None:
        if len(pressure) != len(strokes):
            raise ValueError("pressure list length must match strokes")
        flags |= FLAG_HAS_PRESSURE
    if dt is not None:
        if len(dt) != len(strokes):
            raise ValueError("dt list length must match strokes")
        flags |= FLAG_HAS_TIME

    out = bytearray()
    out.extend(HWS1_MAGIC)
    out.append(flags)
    out.append(len(strokes))

    for i, raw in enumerate(strokes):
        raw_arr = np.asarray(raw, dtype=np.float64)
        if not np.all(np.isfinite(raw_arr)):
            raise ValueError(f"Stroke {i} contains non-finite coordinates")
        arr = np.rint(raw_arr).astype(np.int32)
        if arr.ndim != 2 or arr.shape[1] != 2:
            raise ValueError(f"Stroke {i} must have shape (N, 2), got {arr.shape}")
        n_pts = int(arr.shape[0])
        if n_pts < 2:
            raise ValueError(f"Stroke {i} must have >= 2 points, got {n_pts}")
        if int(arr.min()) < 0 or int(arr.max()) > 1000:
            raise ValueError(f"Stroke {i} coordinates out of 0..1000 range")

        _encode_uvarint(out, n_pts)
        x0, y0 = int(arr[0, 0]), int(arr[0, 1])
        out.extend(struct.pack("<HH", x0, y0))

        prev_x, prev_y = x0, y0
        for idx in range(1, n_pts):
            x, y = int(arr[idx, 0]), int(arr[idx, 1])
            _encode_uvarint(out, _zigzag_encode(x - prev_x))
            _encode_uvarint(out, _zigzag_encode(y - prev_y))
            prev_x, prev_y = x, y

        if pressure is not None:
            p_seq = pressure[i]
            if len(p_seq) != n_pts:
                raise ValueError(f"Stroke {i} pressure length mismatch")
            for p in p_seq:
                out.append(max(0, min(255, int(p))))

        if dt is not None:
            t_seq = dt[i]
            if len(t_seq) != n_pts:
                raise ValueError(f"Stroke {i} dt length mismatch")
            for t in t_seq:
                _encode_uvarint(out, max(0, int(t)))

    return bytes(out)


def decode_strokes_full(blob: bytes) -> DecodedStrokes:
    """Decode HWS1 BLOB into list of int16 (N,2) arrays plus optional channels."""
    view = memoryview(blob)
    if len(view) < 6:
        raise ValueError("HWS1 blob too short")
    if bytes(view[0:4]) != HWS1_MAGIC:
        raise ValueError(f"Invalid HWS1 magic: {bytes(view[0:4])!r}")

    flags = view[4]
    stroke_count = view[5]
    if stroke_count < 1 or stroke_count > MAX_STROKES:
        raise ValueError(f"Invalid HWS1 stroke_count: {stroke_count}")

    has_pressure = bool(flags & FLAG_HAS_PRESSURE)
    has_time = bool(flags & FLAG_HAS_TIME)
    offset = 6
    if stroke_count * 7 > len(view) - offset:
        raise ValueError("Truncated HWS1 payload header")

    strokes: list[np.ndarray] = []
    pressures: list[np.ndarray] | None = [] if has_pressure else None
    dts: list[np.ndarray] | None = [] if has_time else None

    for _ in range(stroke_count):
        n_pts, offset = _decode_uvarint(view, offset)
        if n_pts < 2:
            raise ValueError(f"Invalid stroke point_count: {n_pts}")
        rem = len(view) - offset
        min_bytes = 4 + 2 * (n_pts - 1) + (n_pts if has_pressure else 0) + (n_pts if has_time else 0)
        if min_bytes > rem:
            raise ValueError(
                f"Truncated HWS1 stroke payload: need >= {min_bytes} bytes, got {rem}"
            )
        x0, y0 = struct.unpack_from("<HH", view, offset)
        offset += 4
        if not (0 <= x0 <= 1000 and 0 <= y0 <= 1000):
            raise ValueError(f"Decoded anchor coordinate out of bounds: ({x0}, {y0})")

        pts = np.empty((n_pts, 2), dtype=np.int16)
        pts[0, 0] = x0
        pts[0, 1] = y0
        cx, cy = int(x0), int(y0)
        for idx in range(1, n_pts):
            zx, offset = _decode_uvarint(view, offset)
            zy, offset = _decode_uvarint(view, offset)
            cx += _zigzag_decode(zx)
            cy += _zigzag_decode(zy)
            if not (0 <= cx <= 1000 and 0 <= cy <= 1000):
                raise ValueError(f"Decoded coordinate out of bounds: ({cx}, {cy})")
            pts[idx, 0] = cx
            pts[idx, 1] = cy
        strokes.append(pts)

        if has_pressure and pressures is not None:
            if offset + n_pts > len(view):
                raise ValueError("Truncated HWS1 pressure channel")
            pressures.append(np.frombuffer(view[offset : offset + n_pts], dtype=np.uint8).copy())
            offset += n_pts

        if has_time and dts is not None:
            t_arr = np.empty(n_pts, dtype=np.uint32)
            for idx in range(n_pts):
                val, offset = _decode_uvarint(view, offset)
                if val > 0xFFFFFFFF:
                    raise ValueError(f"HWS1 time value overflows uint32: {val}")
                t_arr[idx] = val
            dts.append(t_arr)

    if offset != len(view):
        raise ValueError(f"Trailing bytes in HWS1 blob: {len(view) - offset}")

    return DecodedStrokes(strokes=strokes, pressure=pressures, dt_ms=dts)


def decode_strokes(blob: bytes) -> list[np.ndarray]:
    """Decode HWS1 BLOB into a list of int16 numpy arrays of shape (N, 2)."""
    return decode_strokes_full(blob).strokes
