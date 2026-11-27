"""GRBL 1.1 G-code compiler supporting servo (M3/M5) and stepper Z-axis pen lifters."""

from __future__ import annotations

from dataclasses import dataclass, field
import math

from handwrite.api.schemas import ComposedPage, MachineProfile
from handwrite.gcode.optimizer import WorkspaceBoundsError, check_bounds


@dataclass
class CompiledGcode:
    """Compiled G-code program with bidirectional line <-> stroke mapping."""

    lines: list[str]
    line_to_stroke: list[int]
    stroke_to_line: dict[int, int]
    est_s: float
    draw_mm: float
    travel_mm: float
    stroke_start_xy: dict[int, tuple[float, float]] = field(default_factory=dict)

    def to_text(self) -> str:
        return "\n".join(self.lines) + ("\n" if self.lines else "")


def _fmt_dwell(dwell_ms: int) -> str | None:
    if dwell_ms <= 0:
        return None
    sec = dwell_ms / 1000.0
    return f"G4 P{sec:.3f}".rstrip("0").rstrip(".")


def _fmt_coord(val: float) -> str:
    text = f"{val:.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def pen_up_commands(profile: MachineProfile, *, include_dwell: bool = True) -> list[str]:
    cmds: list[str] = []
    if profile.pen.mode == "z":
        cmds.append(f"G0 Z{_fmt_coord(profile.pen.z_up_mm)}")
    else:
        cmds.append(profile.pen.servo_up.strip() or "M5")
    if include_dwell:
        dwell = _fmt_dwell(profile.pen.dwell_ms)
        if dwell:
            cmds.append(dwell)
    return cmds


def pen_down_commands(profile: MachineProfile, *, include_dwell: bool = True) -> list[str]:
    cmds: list[str] = []
    if profile.pen.mode == "z":
        cmds.append(
            f"G1 Z{_fmt_coord(profile.pen.z_down_mm)} F{int(round(profile.pen.z_feed))}"
        )
    else:
        cmds.append(profile.pen.servo_down.strip() or "M3 S90")
    if include_dwell:
        dwell = _fmt_dwell(profile.pen.dwell_ms)
        if dwell:
            cmds.append(dwell)
    return cmds


def map_page_to_machine(
    x_mm: float,
    y_mm: float,
    page_width_mm: float,
    page_height_mm: float,
    profile: MachineProfile,
) -> tuple[float, float]:
    """Map page-space coordinates (mm, top-left origin) to machine work coordinates."""
    mx = (page_width_mm - x_mm) if profile.invert_x else x_mm
    my = (page_height_mm - y_mm) if profile.origin == "bottom_left" else y_mm
    if profile.invert_y:
        my = page_height_mm - my
    return mx, my


def _segment_time_s(dist_mm: float, feed_mm_min: float, accel_mm_s2: float = 500.0) -> float:
    """Trapezoidal velocity profile duration estimate for a linear segment."""
    if dist_mm <= 0.0:
        return 0.0
    v_max = max(1.0, feed_mm_min / 60.0)
    d_accel = (v_max * v_max) / accel_mm_s2
    if dist_mm >= d_accel:
        return (dist_mm / v_max) + (v_max / accel_mm_s2)
    return 2.0 * math.sqrt(dist_mm / accel_mm_s2)


def compile_page_gcode(
    page: ComposedPage,
    profile: MachineProfile,
    *,
    validate_bounds: bool = True,
) -> CompiledGcode:
    """Compile an optimized ComposedPage into compact GRBL 1.1 G-code."""
    if validate_bounds:
        violations = check_bounds(page, profile.workspace_mm)
        if violations:
            raise WorkspaceBoundsError(
                f"Page {page.page_index} exceeds workspace ({profile.workspace_mm.x}x{profile.workspace_mm.y} mm)",
                violations,
            )

    lines: list[str] = []
    line_to_stroke: list[int] = []
    stroke_to_line: dict[int, int] = {}
    stroke_start_xy: dict[int, tuple[float, float]] = {}

    def emit(cmd: str, stroke_idx: int) -> None:
        lines.append(cmd)
        line_to_stroke.append(stroke_idx)

    # Preamble
    for cmd in ("G21", "G90", "G17", "G94"):
        emit(cmd, -1)
    for cmd in pen_up_commands(profile):
        emit(cmd, -1)

    draw_mm = 0.0
    travel_mm = 0.0
    est_s = profile.pen.dwell_ms / 1000.0
    cur_x, cur_y = 0.0, 0.0

    feed_travel_int = int(round(max(100.0, profile.feed_travel)))
    feed_draw_int = int(round(max(100.0, profile.feed_draw)))
    dwell_s = profile.pen.dwell_ms / 1000.0

    for idx, stroke in enumerate(page.strokes):
        pts = stroke.pts
        if len(pts) < 4:
            continue

        x0, y0 = map_page_to_machine(
            pts[0], pts[1], page.width_mm, page.height_mm, profile
        )
        stroke_to_line[idx] = len(lines)
        stroke_start_xy[idx] = (round(x0, 3), round(y0, 3))

        # Rapid travel to stroke start (always explicit X/Y/F for clean checkpoint resume)
        emit(f"G0 X{_fmt_coord(x0)} Y{_fmt_coord(y0)} F{feed_travel_int}", idx)
        td = math.hypot(x0 - cur_x, y0 - cur_y)
        travel_mm += td
        est_s += _segment_time_s(td, profile.feed_travel)
        cur_x, cur_y = x0, y0

        # Pen down
        for cmd in pen_down_commands(profile):
            emit(cmd, idx)
        est_s += dwell_s
        if profile.pen.mode == "z":
            z_dist = abs(profile.pen.z_up_mm - profile.pen.z_down_mm)
            est_s += _segment_time_s(z_dist, profile.pen.z_feed)

        # Draw segments with modal omission
        first_seg = True
        for p in range(2, len(pts), 2):
            nx, ny = map_page_to_machine(
                pts[p], pts[p + 1], page.width_mm, page.height_mm, profile
            )
            seg_d = math.hypot(nx - cur_x, ny - cur_y)
            if seg_d < 1e-5:
                continue
            draw_mm += seg_d
            est_s += _segment_time_s(seg_d, profile.feed_draw)

            sx = _fmt_coord(nx)
            sy = _fmt_coord(ny)
            if first_seg:
                emit(f"G1 X{sx} Y{sy} F{feed_draw_int}", idx)
                first_seg = False
            else:
                parts: list[str] = []
                if abs(nx - cur_x) >= 1e-4:
                    parts.append(f"X{sx}")
                if abs(ny - cur_y) >= 1e-4:
                    parts.append(f"Y{sy}")
                if parts:
                    emit(" ".join(parts), idx)
            cur_x, cur_y = nx, ny

        # Pen up
        for cmd in pen_up_commands(profile):
            emit(cmd, idx)
        est_s += dwell_s
        if profile.pen.mode == "z":
            z_dist = abs(profile.pen.z_up_mm - profile.pen.z_down_mm)
            est_s += _segment_time_s(z_dist, profile.pen.z_feed)

    # Epilogue: ensure pen up & park at paper_change_pos_mm
    for cmd in pen_up_commands(profile):
        emit(cmd, -1)
    park_x = profile.paper_change_pos_mm.x
    park_y = profile.paper_change_pos_mm.y
    emit(f"G0 X{_fmt_coord(park_x)} Y{_fmt_coord(park_y)} F{feed_travel_int}", -1)
    emit("G4 P0.1", -1)
    td = math.hypot(park_x - cur_x, park_y - cur_y)
    travel_mm += td
    est_s += _segment_time_s(td, profile.feed_travel) + 0.1

    return CompiledGcode(
        lines=lines,
        line_to_stroke=line_to_stroke,
        stroke_to_line=stroke_to_line,
        est_s=round(est_s, 2),
        draw_mm=round(draw_mm, 2),
        travel_mm=round(travel_mm, 2),
        stroke_start_xy=stroke_start_xy,
    )


def compile_frame_gcode(
    bbox: list[float] | tuple[float, float, float, float],
    profile: MachineProfile,
    *,
    page_width_mm: float = 210.0,
    page_height_mm: float = 297.0,
) -> list[str]:
    """Compile pen-up Frame Check G-code tracing the page bounding box rectangle."""
    if len(bbox) != 4:
        raise ValueError("bbox must have 4 elements: [x0, y0, x1, y1]")
    x0, y0, x1, y1 = [float(v) for v in bbox]
    ws_x = float(profile.workspace_mm.x)
    ws_y = float(profile.workspace_mm.y)
    tol = 0.05
    if x0 < -tol or y0 < -tol or x1 > ws_x + tol or y1 > ws_y + tol:
        raise WorkspaceBoundsError(
            f"Frame bbox {[x0, y0, x1, y1]} exceeds workspace ({ws_x}x{ws_y} mm)",
            [
                {
                    "block_id": "frame",
                    "min_x": round(x0, 2),
                    "max_x": round(x1, 2),
                    "min_y": round(y0, 2),
                    "max_y": round(y1, 2),
                    "workspace_mm": {"x": ws_x, "y": ws_y},
                }
            ],
        )

    corners = [
        map_page_to_machine(x0, y0, page_width_mm, page_height_mm, profile),
        map_page_to_machine(x1, y0, page_width_mm, page_height_mm, profile),
        map_page_to_machine(x1, y1, page_width_mm, page_height_mm, profile),
        map_page_to_machine(x0, y1, page_width_mm, page_height_mm, profile),
        map_page_to_machine(x0, y0, page_width_mm, page_height_mm, profile),
    ]
    frame_feed = int(round(max(300.0, profile.feed_travel * 0.7)))

    lines: list[str] = ["G21", "G90", "G17", "G94"]
    lines.extend(pen_up_commands(profile))
    cx0, cy0 = corners[0]
    lines.append(f"G0 X{_fmt_coord(cx0)} Y{_fmt_coord(cy0)} F{frame_feed}")
    for cx, cy in corners[1:]:
        lines.append(f"G1 X{_fmt_coord(cx)} Y{_fmt_coord(cy)} F{frame_feed}")
    lines.append(f"G0 X0 Y0 F{frame_feed}")
    lines.append("G4 P0.1")
    return lines
