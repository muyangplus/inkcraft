"""Procedural single-line vector geometry for mathematical structures (in em coordinates, y-down).

Coordinate convention:
- Horizontal x increases to the right; x = 0 is the left edge of the structure.
- Vertical y increases downward; y = 0 is the math baseline, negative y is above baseline,
  positive y is below baseline.
"""

from __future__ import annotations

import math
import numpy as np


def make_fraction_bar(
    width_em: float,
    axis_y_em: float,
    rng: np.random.Generator,
) -> list[np.ndarray]:
    """Single-line hand-drawn horizontal fraction bar centered at `y = -axis_y_em`."""
    w = max(0.25, float(width_em))
    n = 8
    xs = np.linspace(0.0, w, n)
    phase = float(rng.uniform(0.0, 2.0 * math.pi))
    amp = 0.008
    ys = np.full(n, -float(axis_y_em), dtype=np.float64) + amp * np.sin(
        np.linspace(0.0, math.pi, n) + phase
    ) * np.sin(np.linspace(0.0, math.pi, n))
    return [np.column_stack((xs, ys))]


def make_radical(
    body_w_em: float,
    body_h_em: float,
    body_d_em: float,
    gap_em: float = 0.12,
) -> tuple[list[np.ndarray], float, float]:
    """Single-line continuous radical/sqrt polyline.

    Returns `(strokes_em, left_advance_em, top_y_em)` where `top_y_em < 0` is the y coordinate
    of the vinculum (top bar). The radicand starts at `x = left_advance_em`.
    """
    hook_w = 0.52
    top_y = -(max(0.72, body_h_em) + gap_em)
    bot_y = max(0.14, body_d_em + 0.06)
    mid_y = top_y + 0.58 * (bot_y - top_y)
    right_x = hook_w + max(0.3, body_w_em) + 0.08

    pts = np.array(
        [
            [0.02, mid_y + 0.06],
            [0.14, mid_y - 0.05],
            [0.27, bot_y],
            [hook_w, top_y],
            [right_x, top_y],
        ],
        dtype=np.float64,
    )
    return [pts], hook_w, top_y


def _cubic(p0: np.ndarray, p1: np.ndarray, p2: np.ndarray, p3: np.ndarray, steps: int = 10) -> np.ndarray:
    t = np.linspace(0.0, 1.0, steps + 1)[:, None]
    mt = 1.0 - t
    return (mt**3) * p0 + 3.0 * (mt**2) * t * p1 + 3.0 * mt * (t**2) * p2 + (t**3) * p3


def make_delimiter(
    delim: str,
    height_em: float,
    depth_em: float,
    axis_height_em: float = 0.25,
) -> tuple[list[np.ndarray], float]:
    """Generate stretchy single-line delimiter covering `[-height_em, +depth_em]`.

    Returns `(strokes_em, width_em)`.
    """
    if delim in {"", "."}:
        return [], 0.08

    # Symmetrize slightly around math axis (-axis_height_em)
    center_y = -axis_height_em
    half_h = max(0.55, height_em - axis_height_em, depth_em + axis_height_em)
    y_top = center_y - half_h
    y_bot = center_y + half_h
    total_h = y_bot - y_top
    w = 0.22 + 0.07 * math.log2(max(1.0, total_h))

    if delim in {"(", ")"}:
        steps = 16
        t = np.linspace(0.0, 1.0, steps + 1)
        # Elliptical arc bulging outward
        ys = y_top + t * total_h
        bulge = np.sin(math.pi * t)
        if delim == "(":
            xs = (w * 0.85) - (w * 0.65) * bulge
        else:
            xs = (w * 0.15) + (w * 0.65) * bulge
        return [np.column_stack((xs, ys))], w

    if delim in {"[", "]"}:
        r = 0.025
        if delim == "[":
            pts = np.array(
                [
                    [w * 0.88, y_top],
                    [w * 0.22 + r, y_top],
                    [w * 0.22, y_top + r],
                    [w * 0.22, y_bot - r],
                    [w * 0.22 + r, y_bot],
                    [w * 0.88, y_bot],
                ],
                dtype=np.float64,
            )
        else:
            pts = np.array(
                [
                    [w * 0.12, y_top],
                    [w * 0.78 - r, y_top],
                    [w * 0.78, y_top + r],
                    [w * 0.78, y_bot - r],
                    [w * 0.78 - r, y_bot],
                    [w * 0.12, y_bot],
                ],
                dtype=np.float64,
            )
        return [pts], w

    if delim in {"{", r"\{", "}", r"\}"}:
        bw = w * 1.25
        if delim in {"{", r"\{"}:
            top_curve = _cubic(
                np.array([bw * 0.88, y_top]),
                np.array([bw * 0.42, y_top]),
                np.array([bw * 0.52, center_y - 0.08]),
                np.array([bw * 0.12, center_y]),
                steps=9,
            )
            bot_curve = _cubic(
                np.array([bw * 0.12, center_y]),
                np.array([bw * 0.52, center_y + 0.08]),
                np.array([bw * 0.42, y_bot]),
                np.array([bw * 0.88, y_bot]),
                steps=9,
            )
        else:
            top_curve = _cubic(
                np.array([bw * 0.12, y_top]),
                np.array([bw * 0.58, y_top]),
                np.array([bw * 0.48, center_y - 0.08]),
                np.array([bw * 0.88, center_y]),
                steps=9,
            )
            bot_curve = _cubic(
                np.array([bw * 0.88, center_y]),
                np.array([bw * 0.48, center_y + 0.08]),
                np.array([bw * 0.58, y_bot]),
                np.array([bw * 0.12, y_bot]),
                steps=9,
            )
        pts = np.vstack([top_curve, bot_curve[1:]])
        return [pts], bw

    if delim in {"|", r"\vert"}:
        vw = 0.22
        pts = np.array([[vw * 0.5, y_top], [vw * 0.5, y_bot]], dtype=np.float64)
        return [pts], vw

    if delim in {r"\|", r"\Vert", "‖"}:
        vw = 0.34
        s1 = np.array([[vw * 0.30, y_top], [vw * 0.30, y_bot]], dtype=np.float64)
        s2 = np.array([[vw * 0.70, y_top], [vw * 0.70, y_bot]], dtype=np.float64)
        return [s1, s2], vw

    if delim in {r"\langle", "⟨"}:
        pts = np.array([[w * 0.88, y_top], [w * 0.15, center_y], [w * 0.88, y_bot]], dtype=np.float64)
        return [pts], w

    if delim in {r"\rangle", "⟩"}:
        pts = np.array([[w * 0.12, y_top], [w * 0.85, center_y], [w * 0.12, y_bot]], dtype=np.float64)
        return [pts], w

    # Default fallback: vertical bar
    return [np.array([[w * 0.5, y_top], [w * 0.5, y_bot]], dtype=np.float64)], w


def _single_integral_stroke(x_offset: float, total_h: float, center_y: float) -> np.ndarray:
    """Smooth parametric S-curve integral sign centered vertically at `center_y`."""
    half_h = 0.5 * total_h
    w = 0.48 if total_h > 1.7 else 0.36
    # Top hook -> slanted stem -> bottom hook
    p0 = np.array([x_offset + w * 0.96, center_y - half_h * 0.82])
    p1 = np.array([x_offset + w * 0.84, center_y - half_h * 1.06])
    p2 = np.array([x_offset + w * 0.58, center_y - half_h * 0.96])
    p3 = np.array([x_offset + w * 0.54, center_y - half_h * 0.42])

    p4 = np.array([x_offset + w * 0.46, center_y + half_h * 0.42])
    p5 = np.array([x_offset + w * 0.42, center_y + half_h * 0.96])
    p6 = np.array([x_offset + w * 0.16, center_y + half_h * 1.06])
    p7 = np.array([x_offset + w * 0.04, center_y + half_h * 0.82])

    top = _cubic(p0, p1, p2, p3, steps=8)
    mid = np.linspace(p3, p4, 6)
    bot = _cubic(p4, p5, p6, p7, steps=8)
    return np.vstack([top, mid[1:], bot[1:]])


def make_big_operator(
    op_cmd: str,
    display: bool,
    axis_height_em: float = 0.25,
) -> tuple[list[np.ndarray], float, float, float]:
    """Generate procedural single-line large operators (`\\sum`, `\\prod`, `\\int`, `\\iint`, `\\oint`).

    Returns `(strokes_em, width_em, height_em, depth_em)`.
    """
    center_y = -axis_height_em

    if op_cmd in {r"\int", r"\iint", r"\oint"}:
        total_h = 2.10 if display else 1.38
        half_h = 0.5 * total_h
        w_one = 0.52 if display else 0.40
        if op_cmd == r"\int":
            strokes = [_single_integral_stroke(0.0, total_h, center_y)]
            width = w_one
        elif op_cmd == r"\iint":
            gap = 0.28 if display else 0.22
            strokes = [
                _single_integral_stroke(0.0, total_h, center_y),
                _single_integral_stroke(gap, total_h, center_y),
            ]
            width = w_one + gap
        else:  # \oint
            s_int = _single_integral_stroke(0.0, total_h, center_y)
            th = np.linspace(0.0, 2.0 * math.pi, 18)
            rx = w_one * 0.42
            ry = total_h * 0.14
            loop = np.column_stack((w_one * 0.50 + rx * np.cos(th), center_y + ry * np.sin(th)))
            strokes = [s_int, loop]
            width = w_one
        height = max(0.0, -(center_y - half_h))
        depth = max(0.0, center_y + half_h)
        return strokes, width, height, depth

    if op_cmd == r"\sum":
        scale = 1.48 if display else 1.05
        half_h = 0.52 * scale
        w = 0.72 * scale
        y_top = center_y - half_h
        y_bot = center_y + half_h
        pts = np.array(
            [
                [w * 0.94, y_top + 0.12 * scale],
                [w * 0.90, y_top],
                [w * 0.06, y_top],
                [w * 0.50, center_y],
                [w * 0.06, y_bot],
                [w * 0.92, y_bot],
                [w * 0.96, y_bot - 0.12 * scale],
            ],
            dtype=np.float64,
        )
        return [pts], w, max(0.0, -y_top), max(0.0, y_bot)

    if op_cmd == r"\prod":
        scale = 1.45 if display else 1.05
        half_h = 0.50 * scale
        w = 0.76 * scale
        y_top = center_y - half_h
        y_bot = center_y + half_h
        top_bar = np.array([[w * 0.05, y_top], [w * 0.95, y_top]], dtype=np.float64)
        left_leg = np.array([[w * 0.24, y_top], [w * 0.24, y_bot]], dtype=np.float64)
        right_leg = np.array([[w * 0.76, y_top], [w * 0.76, y_bot]], dtype=np.float64)
        return [top_bar, left_leg, right_leg], w, max(0.0, -y_top), max(0.0, y_bot)

    # Fallback
    return [], 0.5, 0.7, 0.2


def make_accent(cmd: str, width_em: float, top_y_em: float, bot_y_em: float) -> list[np.ndarray]:
    """Generate single-line accents (`\\overline`, `\\underline`, `\\hat`, `\\bar`, `\\vec`, `\\tilde`, `\\dot`, `\\ddot`)."""
    w = max(0.28, width_em)
    cx = 0.5 * w
    y = top_y_em - 0.10

    if cmd == r"\overline":
        return [np.array([[0.0, y], [w, y]], dtype=np.float64)]
    if cmd == r"\underline":
        uy = bot_y_em + 0.10
        return [np.array([[0.0, uy], [w, uy]], dtype=np.float64)]
    if cmd == r"\bar":
        hw = min(w * 0.45, 0.26)
        return [np.array([[cx - hw, y], [cx + hw, y]], dtype=np.float64)]
    if cmd == r"\hat":
        hw = min(w * 0.42, 0.24)
        return [np.array([[cx - hw, y + 0.04], [cx, y - 0.12], [cx + hw, y + 0.04]], dtype=np.float64)]
    if cmd == r"\tilde":
        xs = np.linspace(cx - min(w * 0.45, 0.28), cx + min(w * 0.45, 0.28), 9)
        ys = y - 0.06 * np.sin(np.linspace(0.0, 2.0 * math.pi, 9))
        return [np.column_stack((xs, ys))]
    if cmd == r"\vec":
        x0 = max(0.0, cx - max(w * 0.45, 0.22))
        x1 = min(w + 0.08, cx + max(w * 0.45, 0.22))
        shaft = np.array([[x0, y - 0.03], [x1, y - 0.03]], dtype=np.float64)
        head = np.array([[x1 - 0.12, y - 0.11], [x1, y - 0.03], [x1 - 0.12, y + 0.05]], dtype=np.float64)
        return [shaft, head]
    if cmd == r"\dot":
        return [np.array([[cx - 0.02, y - 0.03], [cx + 0.02, y - 0.03]], dtype=np.float64)]
    if cmd == r"\ddot":
        return [
            np.array([[cx - 0.10, y - 0.03], [cx - 0.06, y - 0.03]], dtype=np.float64),
            np.array([[cx + 0.06, y - 0.03], [cx + 0.10, y - 0.03]], dtype=np.float64),
        ]
    return []
