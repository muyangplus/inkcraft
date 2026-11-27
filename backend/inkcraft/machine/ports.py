"""Serial port auto-detection for USB-serial GRBL boards.

COM port numbers change whenever the board is plugged into another USB socket,
so profiles default to ``port="auto"`` and the controller picks the most likely
GRBL adapter at connect time.
"""

from __future__ import annotations

from typing import Any

# (vid, label, score) — higher score wins.  CH340 ships with 奎享雕刻's driver.
_KNOWN_ADAPTERS: dict[int, tuple[str, int]] = {
    0x1A86: ("WCH CH340/CH341", 100),
    0x10C4: ("SiLabs CP210x", 90),
    0x0403: ("FTDI", 90),
    0x2341: ("Arduino", 80),
    0x2A03: ("Arduino", 80),
    0x1EAF: ("STM32 Maple", 60),
    0x0483: ("STM32 VCP", 60),
}

_DESC_HINTS = ("ch340", "ch341", "usb-serial", "usb serial", "cp210", "ftdi", "arduino", "grbl")
_IGNORE_HINTS = ("bluetooth", "蓝牙", "ttys", "modem")


def is_auto_port(port: str | None) -> bool:
    return (port or "").strip().lower() in ("", "auto", "自动")


def score_port(info: dict[str, Any]) -> int:
    vid = info.get("vid")
    desc = f"{info.get('description', '')} {info.get('hwid', '')} {info.get('device', '')}".lower()
    if any(h in desc for h in _IGNORE_HINTS) and vid is None:
        return -1
    score = 0
    if isinstance(vid, int) and vid in _KNOWN_ADAPTERS:
        score += _KNOWN_ADAPTERS[vid][1]
    if any(h in desc for h in _DESC_HINTS):
        score += 20
    if vid is not None:
        score += 5  # any USB device beats legacy on-board UARTs
    return score


def pick_serial_port(ports: list[dict[str, Any]]) -> str | None:
    """Return the device name of the best GRBL candidate, or ``None``."""
    ranked = sorted(
        ((score_port(p), str(p.get("device", ""))) for p in ports if p.get("device")),
        key=lambda t: (-t[0], t[1]),
    )
    ranked = [r for r in ranked if r[0] > 0]
    return ranked[0][1] if ranked else None


def annotate_ports(ports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best = pick_serial_port(ports)
    out = []
    for p in ports:
        q = dict(p)
        vid = p.get("vid")
        q["adapter"] = _KNOWN_ADAPTERS.get(vid, ("", 0))[0] if isinstance(vid, int) else ""
        q["recommended"] = p.get("device") == best
        out.append(q)
    return out
