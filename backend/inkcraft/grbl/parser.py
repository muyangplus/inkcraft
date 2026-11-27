"""GRBL 1.1 status line parser and human-readable error/alarm decoders."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

GRBL_ERROR_CODES: dict[int, str] = {
    1: "G-code 命令字母缺失 (Expected command letter)",
    2: "数值格式错误 (Bad number format)",
    3: "不支持的 $ 系统指令 (Invalid statement)",
    4: "参数不能为负值 (Value < 0)",
    5: "未启用归零循环 (Setting disabled)",
    6: "步进脉冲时间过短 (Value < 3 usec)",
    7: "EEPROM 读取失败 (EEPROM read fail)",
    8: "仅在 Idle 空闲态可执行该指令 (Not idle)",
    9: "报警或点动锁定状态下禁止 G-code (G-code lock)",
    10: "软限位需先启用归零 (Homing not enabled)",
    11: "单行字符超过 80 字节上限 (Max characters per line exceeded)",
    12: "步进频率超过固件上限 (Max step rate exceeded)",
    13: "安全门已打开 (Check door)",
    14: "行长度或 RX 缓冲区溢出 (Line length exceeded / RX overflow)",
    15: "点动目标超出行程软限位 (Jog target exceeds machine travel)",
    16: "无效的点动指令 (Invalid jog command)",
    17: "激光模式需要 PWM 输出 (Laser mode requires PWM)",
    20: "不支持的 G-code 指令 (Unsupported command)",
    21: "同一模态组指令冲突 (Modal group violation)",
    22: "未定义进给速率 F (Undefined feed rate)",
    23: "指令要求整数值 (Invalid G-code ID:23)",
    24: "轴字冲突 (Axis command conflict)",
    25: "重复的 G-code 字 (Word repeated)",
    26: "缺少轴坐标字 (No axis words)",
    27: "行号无效 (Invalid line number)",
    28: "缺少必须的参数字 (Value word missing)",
    29: "不支持的坐标系 (G59.x WCS not supported)",
    30: "G53 仅支持 G0/G1 (G53 only allowed with G0 and G1)",
    31: "存在未使用的轴字 (Axis words exist)",
    32: "圆弧缺少轴字 (No axis words in plane)",
    33: "无效运动目标 (Invalid motion target)",
    34: "圆弧半径计算错误 (Arc radius error)",
    35: "圆弧缺少偏移量 (No offsets in plane)",
    36: "存在未使用的字 (Unused words)",
    37: "G43.1 动态刀长偏移轴无效 (G43.1 axis error)",
    38: "刀具号超出最大值 (Max tool number exceeded)",
}

GRBL_ALARM_CODES: dict[int, str] = {
    1: "触发硬限位开关 (Hard limit triggered)",
    2: "运动目标超出软件工作区限位 (G-code motion target exceeds machine travel)",
    3: "运动中发生软复位，位置可能丢失 (Reset while in motion)",
    4: "探针初始状态异常 (Probe fail: initial state)",
    5: "探针未在行程内触发 (Probe fail: did not contact)",
    6: "归零循环被复位中断 (Homing fail: reset during active homing)",
    7: "归零循环因安全门打开中断 (Homing fail: safety door opened)",
    8: "归零拉离限位失败 (Homing fail: pull off failed)",
    9: "归零未找到限位开关 (Homing fail: could not find limit switch)",
}


def decode_error(code: int) -> str:
    return GRBL_ERROR_CODES.get(code, f"未知 GRBL 错误 (error:{code})")


def decode_alarm(code: int) -> str:
    return GRBL_ALARM_CODES.get(code, f"未知 GRBL 报警 (ALARM:{code})")


@dataclass(frozen=True, slots=True)
class GrblStatus:
    state: str
    mpos: tuple[float, float, float] | None = None
    wpos: tuple[float, float, float] | None = None
    wco: tuple[float, float, float] | None = None
    feed: float = 0.0
    spindle: float = 0.0
    planner_avail: int | None = None
    rx_avail: int | None = None


ResponseKind = Literal[
    "ok", "error", "alarm", "status", "welcome", "message", "setting", "other"
]


@dataclass(frozen=True, slots=True)
class ParsedResponse:
    kind: ResponseKind
    raw: str
    code: int | None = None
    message: str = ""
    status: GrblStatus | None = None


_ERROR_RE = re.compile(r"^error:(\d+)$", re.IGNORECASE)
_ALARM_RE = re.compile(r"^ALARM:(\d+)$", re.IGNORECASE)
_WELCOME_RE = re.compile(r"^Grbl\s+([0-9]+\.[0-9]+[a-z]?)", re.IGNORECASE)
_MSG_RE = re.compile(r"^\[MSG:(.*)\]$")
_SETTING_RE = re.compile(r"^\$(\d+)=(.+)$")
_LEGACY_SPLIT_RE = re.compile(r",(?=[A-Za-z]+:)")


def _legacy_fields(body: str) -> list[str]:
    """Split a GRBL 0.9 comma-separated report into 1.1-style ``key:value`` fields."""
    return [f.strip() for f in _LEGACY_SPLIT_RE.split(body)]


def _parse_vec3(raw: str) -> tuple[float, float, float] | None:
    parts = raw.split(",")
    if len(parts) < 2:
        return None
    try:
        x = float(parts[0])
        y = float(parts[1])
        z = float(parts[2]) if len(parts) >= 3 else 0.0
        return (x, y, z)
    except ValueError:
        return None


def parse_status_line(line: str) -> GrblStatus | None:
    """Parse a GRBL status report.

    GRBL 1.1: ``<Idle|MPos:0.000,0.000,4.000|Bf:15,128|FS:0,0>``
    GRBL 0.9: ``<Idle,MPos:0.000,0.000,0.000,WPos:0.000,0.000,0.000,Buf:0,RX:0>``
    """
    s = line.strip()
    if not (s.startswith("<") and s.endswith(">")):
        return None
    body = s[1:-1]
    if "|" not in body and "," in body:
        fields = _legacy_fields(body)
    else:
        fields = body.split("|")
    if not fields:
        return None

    state = fields[0].strip()
    mpos: tuple[float, float, float] | None = None
    wpos: tuple[float, float, float] | None = None
    wco: tuple[float, float, float] | None = None
    feed = 0.0
    spindle = 0.0
    planner_avail: int | None = None
    rx_avail: int | None = None

    for fld in fields[1:]:
        if ":" not in fld:
            continue
        key, val = fld.split(":", 1)
        if key == "MPos":
            mpos = _parse_vec3(val)
        elif key == "WPos":
            wpos = _parse_vec3(val)
        elif key == "WCO":
            wco = _parse_vec3(val)
        elif key == "FS":
            parts = val.split(",")
            try:
                feed = float(parts[0])
                if len(parts) >= 2:
                    spindle = float(parts[1])
            except ValueError:
                pass
        elif key == "F":
            try:
                feed = float(val)
            except ValueError:
                pass
        elif key == "Bf":
            parts = val.split(",")
            try:
                planner_avail = int(parts[0])
                if len(parts) >= 2:
                    rx_avail = int(parts[1])
            except ValueError:
                pass

    return GrblStatus(
        state=state,
        mpos=mpos,
        wpos=wpos,
        wco=wco,
        feed=feed,
        spindle=spindle,
        planner_avail=planner_avail,
        rx_avail=rx_avail,
    )


def parse_grbl_line(line: str) -> ParsedResponse:
    """Classify and decode any single line received from GRBL 1.1."""
    raw = line.strip()
    if not raw:
        return ParsedResponse(kind="other", raw=raw)

    if raw == "ok":
        return ParsedResponse(kind="ok", raw=raw)

    if raw.startswith("<") and raw.endswith(">"):
        st = parse_status_line(raw)
        if st is not None:
            return ParsedResponse(kind="status", raw=raw, status=st)

    m = _ERROR_RE.match(raw)
    if m:
        code = int(m.group(1))
        return ParsedResponse(
            kind="error", raw=raw, code=code, message=decode_error(code)
        )

    m = _ALARM_RE.match(raw)
    if m:
        code = int(m.group(1))
        return ParsedResponse(
            kind="alarm", raw=raw, code=code, message=decode_alarm(code)
        )

    if _WELCOME_RE.match(raw):
        return ParsedResponse(kind="welcome", raw=raw, message=raw)

    m = _MSG_RE.match(raw)
    if m:
        return ParsedResponse(kind="message", raw=raw, message=m.group(1).strip())

    m = _SETTING_RE.match(raw)
    if m:
        return ParsedResponse(
            kind="setting", raw=raw, code=int(m.group(1)), message=m.group(2).strip()
        )

    return ParsedResponse(kind="other", raw=raw, message=raw)
