"""Page-space <-> machine work-coordinate transforms.

Page space: millimetres, origin at the paper's top-left corner, +x to the right,
+y towards the bottom of the paper.  Every layout/stroke in InkCraft lives here.

Machine space: GRBL work coordinates (WPos) after ``G92 X0 Y0`` was set with the
pen on ``MachineProfile.origin``.  The mapping is

    1. legacy mirrors (``invert_x`` / ``invert_y``) and ``offset_mm`` in page space
    2. rotation by ``rotation_deg`` about the page centre (clockwise on paper)
    3. translate so the origin corner becomes (0, 0)
    4. scale by the axis signs (``x_axis`` / ``y_axis``)
    5. optionally swap X and Y (``swap_xy``)

Steps 1–2 move the *drawing*; jog arrows (``page_delta_to_machine``) and the
reachable envelope (``machine_bounds``) only use steps 3–5.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid import cycle: api -> gcode -> machine -> api
    from inkcraft.api.schemas import MachineProfile


@dataclass(frozen=True, slots=True)
class AxisFrame:
    page_w: float
    page_h: float
    origin_x: float  # page-space x of work zero
    origin_y: float  # page-space y of work zero
    sx: float  # +1: machine +X points to page right
    sy: float  # +1: machine +Y points to page bottom
    mirror_x: bool
    mirror_y: bool
    off_x: float
    off_y: float
    swap: bool
    cos_r: float = 1.0
    sin_r: float = 0.0


def axis_signs(profile: MachineProfile) -> tuple[float, float]:
    origin = profile.origin
    if profile.x_axis == "auto":
        sx = -1.0 if origin.endswith("_right") else 1.0
    else:
        sx = 1.0 if profile.x_axis == "right" else -1.0
    if profile.y_axis == "auto":
        sy = -1.0 if origin.startswith("bottom") else 1.0
    else:
        sy = 1.0 if profile.y_axis == "down" else -1.0
    return sx, sy


def make_frame(profile: MachineProfile, page_w: float, page_h: float) -> AxisFrame:
    sx, sy = axis_signs(profile)
    return AxisFrame(
        page_w=float(page_w),
        page_h=float(page_h),
        origin_x=float(page_w) if profile.origin.endswith("_right") else 0.0,
        origin_y=float(page_h) if profile.origin.startswith("bottom") else 0.0,
        sx=sx,
        sy=sy,
        mirror_x=bool(profile.invert_x),
        mirror_y=bool(profile.invert_y),
        off_x=float(profile.offset_mm.x),
        off_y=float(profile.offset_mm.y),
        swap=bool(profile.swap_xy),
        cos_r=math.cos(math.radians(float(profile.rotation_deg))),
        sin_r=math.sin(math.radians(float(profile.rotation_deg))),
    )


def _rotate(f: AxisFrame, x: float, y: float, sign: float) -> tuple[float, float]:
    if f.sin_r == 0.0 and f.cos_r == 1.0:
        return x, y
    cx, cy = f.page_w / 2.0, f.page_h / 2.0
    dx, dy = x - cx, y - cy
    s = f.sin_r * sign
    return (cx + dx * f.cos_r - dy * s, cy + dx * s + dy * f.cos_r)


def frame_page_to_machine(f: AxisFrame, x: float, y: float) -> tuple[float, float]:
    px = (f.page_w - x) if f.mirror_x else x
    py = (f.page_h - y) if f.mirror_y else y
    px += f.off_x
    py += f.off_y
    px, py = _rotate(f, px, py, 1.0)
    mx = (px - f.origin_x) * f.sx
    my = (py - f.origin_y) * f.sy
    if f.swap:
        mx, my = my, mx
    return (mx + 0.0, my + 0.0)  # normalise -0.0


def frame_machine_to_page(f: AxisFrame, mx: float, my: float) -> tuple[float, float]:
    if f.swap:
        mx, my = my, mx
    px = mx / f.sx + f.origin_x
    py = my / f.sy + f.origin_y
    px, py = _rotate(f, px, py, -1.0)
    px -= f.off_x
    py -= f.off_y
    x = (f.page_w - px) if f.mirror_x else px
    y = (f.page_h - py) if f.mirror_y else py
    return (x + 0.0, y + 0.0)


def page_to_machine(
    x: float, y: float, page_w: float, page_h: float, profile: MachineProfile
) -> tuple[float, float]:
    return frame_page_to_machine(make_frame(profile, page_w, page_h), x, y)


def machine_to_page(
    mx: float, my: float, page_w: float, page_h: float, profile: MachineProfile
) -> tuple[float, float]:
    return frame_machine_to_page(make_frame(profile, page_w, page_h), mx, my)


def page_delta_to_machine(dx: float, dy: float, profile: MachineProfile) -> tuple[float, float]:
    """Convert a page-space displacement (e.g. jog arrow) into a machine displacement."""
    sx, sy = axis_signs(profile)
    if profile.invert_x:
        dx = -dx
    if profile.invert_y:
        dy = -dy
    mx, my = dx * sx, dy * sy
    if profile.swap_xy:
        mx, my = my, mx
    return (mx + 0.0, my + 0.0)


def workspace_page_size(profile: MachineProfile) -> tuple[float, float]:
    return float(profile.workspace_mm.x), float(profile.workspace_mm.y)


def machine_bounds(profile: MachineProfile) -> tuple[float, float, float, float]:
    """Machine-space rectangle ``(min_x, min_y, max_x, max_y)`` reachable by the pen.

    The workspace is described in page terms (``workspace_mm``) relative to the
    origin corner, so the page frame used here is the workspace itself.
    """
    w, h = workspace_page_size(profile)
    f = make_frame(profile, w, h)
    # Mirrors/offsets describe where the *drawing* lands, not the machine envelope.
    f = AxisFrame(w, h, f.origin_x, f.origin_y, f.sx, f.sy, False, False, 0.0, 0.0, f.swap)
    pts = [frame_page_to_machine(f, x, y) for x, y in ((0.0, 0.0), (w, 0.0), (0.0, h), (w, h))]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def check_machine_target(
    profile: MachineProfile, mx: float, my: float, *, tol_mm: float = 10.0
) -> str | None:
    """Return a human-readable error if ``(mx, my)`` lies outside the workspace."""
    x0, y0, x1, y1 = machine_bounds(profile)
    if mx < x0 - tol_mm or mx > x1 + tol_mm or my < y0 - tol_mm or my > y1 + tol_mm:
        return (
            f"目标坐标 ({mx:.1f}, {my:.1f}) 超出工作区 "
            f"X[{x0:.0f}, {x1:.0f}] Y[{y0:.0f}, {y1:.0f}] mm"
        )
    return None
