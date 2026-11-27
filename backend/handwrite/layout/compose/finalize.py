"""Page finalization, bbox/statistics calculation, and global overlay transforms."""

from __future__ import annotations

import math

import numpy as np

from handwrite.api.schemas import (
    ComposedPage,
    FallbackGlyphInfo,
    MissingGlyphBox,
    PageStats,
    PlacedBlockBox,
    StrokeItem,
)
from handwrite.layout.shaper import EmittedStroke


def transform_placed_boxes(
    boxes: list[PlacedBlockBox],
    *,
    page_w: float,
    page_h: float,
    offset_x: float,
    offset_y: float,
    scale: float,
    rotation_deg: float,
) -> list[PlacedBlockBox]:
    """Apply the global overlay affine transform to bounding boxes so canvas hit-testing matches strokes."""
    if (
        not boxes
        or (
            abs(offset_x) < 1e-6
            and abs(offset_y) < 1e-6
            and abs(scale - 1.0) < 1e-6
            and abs(rotation_deg) < 1e-6
        )
    ):
        return boxes

    cx, cy = 0.5 * page_w, 0.5 * page_h
    rad = math.radians(rotation_deg)
    cos_r = math.cos(rad)
    sin_r = math.sin(rad)
    rot_scale = np.array(
        [[cos_r * scale, sin_r * scale], [-sin_r * scale, cos_r * scale]], dtype=np.float64
    )
    center = np.array([cx, cy], dtype=np.float64)
    shift = np.array([cx + offset_x, cy + offset_y], dtype=np.float64)

    out: list[PlacedBlockBox] = []
    for box in boxes:
        if len(box.bbox_mm) != 4:
            out.append(box)
            continue
        x0, y0, x1, y1 = box.bbox_mm
        corners = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float64)
        tc = (corners - center) @ rot_scale + shift
        new_bb = [
            round(float(np.min(tc[:, 0])), 2),
            round(float(np.min(tc[:, 1])), 2),
            round(float(np.max(tc[:, 0])), 2),
            round(float(np.max(tc[:, 1])), 2),
        ]
        out.append(box.model_copy(update={"bbox_mm": new_bb}))
    return out


def transform_missing_boxes(
    boxes: list[MissingGlyphBox],
    *,
    page_w: float,
    page_h: float,
    offset_x: float,
    offset_y: float,
    scale: float,
    rotation_deg: float,
) -> list[MissingGlyphBox]:
    """Apply the global overlay affine transform to missing-glyph bboxes identically to strokes."""
    if (
        not boxes
        or (
            abs(offset_x) < 1e-6
            and abs(offset_y) < 1e-6
            and abs(scale - 1.0) < 1e-6
            and abs(rotation_deg) < 1e-6
        )
    ):
        return boxes

    cx, cy = 0.5 * page_w, 0.5 * page_h
    rad = math.radians(rotation_deg)
    cos_r = math.cos(rad)
    sin_r = math.sin(rad)
    rot_scale = np.array(
        [[cos_r * scale, sin_r * scale], [-sin_r * scale, cos_r * scale]], dtype=np.float64
    )
    center = np.array([cx, cy], dtype=np.float64)
    shift = np.array([cx + offset_x, cy + offset_y], dtype=np.float64)

    out: list[MissingGlyphBox] = []
    for box in boxes:
        if len(box.bbox_mm) != 4:
            out.append(box)
            continue
        x0, y0, x1, y1 = box.bbox_mm
        corners = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float64)
        tc = (corners - center) @ rot_scale + shift
        new_bb = [
            round(float(np.min(tc[:, 0])), 2),
            round(float(np.min(tc[:, 1])), 2),
            round(float(np.max(tc[:, 0])), 2),
            round(float(np.max(tc[:, 1])), 2),
        ]
        out.append(box.model_copy(update={"bbox_mm": new_bb}))
    return out


def apply_global_overlay_transform(
    strokes: list[EmittedStroke],
    *,
    page_w: float,
    page_h: float,
    offset_x: float,
    offset_y: float,
    scale: float,
    rotation_deg: float,
) -> list[EmittedStroke]:
    """Apply T = Translate(offset) * Rotate(rot, center) * Scale(scale, center) to all strokes."""
    if (
        abs(offset_x) < 1e-6
        and abs(offset_y) < 1e-6
        and abs(scale - 1.0) < 1e-6
        and abs(rotation_deg) < 1e-6
    ):
        return strokes

    cx, cy = 0.5 * page_w, 0.5 * page_h
    rad = math.radians(rotation_deg)
    cos_r = math.cos(rad)
    sin_r = math.sin(rad)
    rot_scale = np.array(
        [[cos_r * scale, sin_r * scale], [-sin_r * scale, cos_r * scale]], dtype=np.float64
    )
    center = np.array([cx, cy], dtype=np.float64)
    shift = np.array([cx + offset_x, cy + offset_y], dtype=np.float64)

    transformed: list[EmittedStroke] = []
    for st in strokes:
        pts = (st.pts - center) @ rot_scale + shift
        transformed.append(
            EmittedStroke(
                pts=pts,
                kind=st.kind,
                block_id=st.block_id,
                reversible=st.reversible,
            )
        )
    return transformed


def finalize_page(
    page_index: int,
    width_mm: float,
    height_mm: float,
    raw_strokes: list[EmittedStroke],
    fallback_delta: dict[str, int],
    *,
    applied_rule_label: str = "",
    background_id: str | None = None,
    background_opacity: float = 0.72,
    writer_id: str | None = None,
    placed_blocks: list[PlacedBlockBox] | None = None,
    missing_glyphs: list[MissingGlyphBox] | None = None,
) -> ComposedPage:
    """Convert internal `EmittedStroke`s into a Contract v1 `ComposedPage` with bbox & stats."""
    items: list[StrokeItem] = []
    min_x = math.inf
    min_y = math.inf
    max_x = -math.inf
    max_y = -math.inf

    draw_mm = 0.0
    travel_mm = 0.0
    last_pt: tuple[float, float] = (0.0, 0.0)

    for st in raw_strokes:
        arr = np.asarray(st.pts, dtype=np.float64)
        if arr.ndim != 2 or len(arr) < 2:
            continue
        if not np.all(np.isfinite(arr)):
            continue

        x_lo = float(np.min(arr[:, 0]))
        y_lo = float(np.min(arr[:, 1]))
        x_hi = float(np.max(arr[:, 0]))
        y_hi = float(np.max(arr[:, 1]))
        min_x = min(min_x, x_lo)
        min_y = min(min_y, y_lo)
        max_x = max(max_x, x_hi)
        max_y = max(max_y, y_hi)

        sx, sy = float(arr[0, 0]), float(arr[0, 1])
        travel_mm += math.hypot(sx - last_pt[0], sy - last_pt[1])

        diffs = np.diff(arr, axis=0)
        seg_lens = np.hypot(diffs[:, 0], diffs[:, 1])
        draw_mm += float(np.sum(seg_lens))
        last_pt = (float(arr[-1, 0]), float(arr[-1, 1]))

        flat_pts = [round(float(v), 2) for v in arr.reshape(-1)]
        items.append(
            StrokeItem(
                id=len(items),
                block_id=st.block_id,
                kind=st.kind,
                reversible=st.reversible,
                pts=flat_pts,
            )
        )

    bbox = (
        [round(min_x, 2), round(min_y, 2), round(max_x, 2), round(max_y, 2)]
        if items
        else [0.0, 0.0, 0.0, 0.0]
    )

    est_s = (draw_mm / 40.0) + (travel_mm / 83.3333) + (len(items) * 0.24)
    stats = PageStats(
        draw_mm=round(draw_mm, 2),
        travel_mm=round(travel_mm, 2),
        stroke_count=len(items),
        est_s=round(est_s, 2),
    )

    assigned_missing: list[MissingGlyphBox] = []
    if missing_glyphs:
        for i, mg in enumerate(missing_glyphs):
            assigned_missing.append(
                mg.model_copy(
                    update={
                        "id": mg.id or f"mg_p{page_index}_{i}",
                        "page_index": page_index,
                    }
                )
            )
        counts_from_boxes: dict[str, int] = {}
        for mg in assigned_missing:
            counts_from_boxes[mg.char] = counts_from_boxes.get(mg.char, 0) + 1
        eff_delta = counts_from_boxes
    elif missing_glyphs is not None:
        # Caller explicitly tracked missing boxes and recorded zero missing glyphs on this page
        eff_delta = {}
    else:
        eff_delta = fallback_delta

    fb_list = [
        FallbackGlyphInfo(char=ch, count=cnt)
        for ch, cnt in sorted(eff_delta.items(), key=lambda kv: (-kv[1], kv[0]))
        if cnt > 0
    ]

    return ComposedPage(
        page_index=page_index,
        width_mm=round(width_mm, 2),
        height_mm=round(height_mm, 2),
        bbox=bbox,
        strokes=items,
        stats=stats,
        fallback_glyphs=fb_list,
        missing_glyphs=assigned_missing,
        applied_rule_label=applied_rule_label,
        background_id=background_id,
        background_opacity=background_opacity,
        writer_id=writer_id,
        placed_blocks=list(placed_blocks or []),
    )
