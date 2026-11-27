"""GRBL ``$$`` settings parsing and profile compatibility checks."""

from __future__ import annotations

import re
from typing import Any

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid import cycle: api -> gcode -> machine -> api
    from inkcraft.api.schemas import MachineProfile

_SETTING_RE = re.compile(r"^\$(\d+)\s*=\s*(-?[0-9.]+)")

GRBL_SETTING_NAMES: dict[int, str] = {
    0: "步进脉冲时间 (µs)", 1: "步进空闲延时 (ms)", 2: "步进端口反相", 3: "方向端口反相",
    4: "使能反相", 5: "限位反相", 6: "探针反相", 10: "状态报告掩码", 11: "转角偏差",
    12: "圆弧精度", 13: "以英寸报告", 20: "软限位", 21: "硬限位", 22: "回零使能",
    23: "回零方向反相", 24: "回零定位速度", 25: "回零搜索速度", 26: "回零去抖", 27: "回零退离",
    30: "主轴最大转速", 31: "主轴最小转速", 32: "激光模式",
    100: "X 步/mm", 101: "Y 步/mm", 102: "Z 步/mm", 110: "X 最大速率", 111: "Y 最大速率",
    112: "Z 最大速率", 120: "X 加速度", 121: "Y 加速度", 122: "Z 加速度",
    130: "X 最大行程", 131: "Y 最大行程", 132: "Z 最大行程",
}

# Settings whose drift means "this is not the machine the profile was made for".
CRITICAL_KEYS = (3, 13, 100, 101, 102)


def parse_setting_line(line: str) -> tuple[int, float] | None:
    m = _SETTING_RE.match(line.strip())
    if not m:
        return None
    try:
        return int(m.group(1)), float(m.group(2))
    except ValueError:
        return None


def parse_settings(lines: list[str]) -> dict[int, float]:
    out: dict[int, float] = {}
    for ln in lines:
        kv = parse_setting_line(ln)
        if kv is not None:
            out[kv[0]] = kv[1]
    return out


def report_scale(settings: dict[int, float]) -> float:
    """Factor turning reported positions into mm (``$13=1`` reports inches)."""
    return 25.4 if int(settings.get(13, 0)) == 1 else 1.0


def expected_settings(profile: MachineProfile) -> dict[int, float]:
    out: dict[int, float] = {}
    for k, v in profile.grbl_expected.items():
        key = str(k).lstrip("$")
        if key.isdigit():
            out[int(key)] = float(v)
    return out


def check_settings(profile: MachineProfile, settings: dict[int, float]) -> list[dict[str, Any]]:
    """Return warnings ``{code, message, severity}`` for the connected firmware."""
    warns: list[dict[str, Any]] = []
    if not settings:
        return warns
    if profile.pen.mode == "servo" and int(settings.get(32, 0)) == 1:
        warns.append({
            "code": "GRBL_LASER_MODE",
            "message": "舵机抬笔模式下检测到 $32=1（激光模式），G0 空移时 PWM 会被关闭导致落笔异常，建议设置 $32=0",
            "severity": "warn",
        })
    if profile.pen.mode == "laser" and int(settings.get(32, 0)) == 0:
        warns.append({
            "code": "GRBL_LASER_MODE_OFF",
            "message": "激光笔控建议开启 $32=1：空移 (G0) 时自动关闭激光，避免拖出连线",
            "severity": "warn",
        })
    if 10 in settings and (int(settings[10]) & 2) == 0:
        warns.append({
            "code": "GRBL_NO_BUFFER_REPORT",
            "message": "$10 未开启缓冲区状态 (Bf)，流控仍可用但 UI 缓冲显示不可用",
            "severity": "info",
        })
    for key, want in sorted(expected_settings(profile).items()):
        if key not in CRITICAL_KEYS or key not in settings:
            continue
        have = settings[key]
        if abs(have - want) > max(1e-6, abs(want) * 1e-3):
            name = GRBL_SETTING_NAMES.get(key, "")
            warns.append({
                "code": "GRBL_SETTING_MISMATCH",
                "message": f"${key}（{name}）固件值 {have:g} 与配置期望 {want:g} 不一致，请确认连接的是否为该机器",
                "severity": "warn",
            })
    return warns
