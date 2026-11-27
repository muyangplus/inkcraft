"""Contract v1 path exporters: JSON and zero-copy little-endian Float32 binary format."""

from __future__ import annotations

import numpy as np

from handwrite.api.schemas import ComposedPage


def export_page_json(layout_id: str, page: ComposedPage) -> dict:
    """Serialize a `ComposedPage` to Contract v1 §12.3 `format=json` dictionary."""
    return {
        "layout_id": layout_id,
        "page_index": page.page_index,
        "width_mm": round(float(page.width_mm), 2),
        "height_mm": round(float(page.height_mm), 2),
        "bbox": [round(float(v), 2) for v in page.bbox],
        "strokes": [
            {
                "id": st.id,
                "block_id": st.block_id,
                "kind": st.kind,
                "reversible": st.reversible,
                "pts": st.pts,
            }
            for st in page.strokes
        ],
        "stats": page.stats.model_dump(),
    }


def export_page_f32(page: ComposedPage) -> tuple[bytes, dict[str, str]]:
    """Serialize a `ComposedPage` to little-endian IEEE-754 Float32 triples `(x, y, flag)`.

    Flag encoding (§12.3):
    - `0.0`: travel-to (pen up, start of stroke)
    - `1.0`: draw-to (pen down, intermediate stroke vertex)
    - `2.0`: draw-to & stroke boundary (pen down, final vertex of stroke)

    Returns `(payload_bytes, http_headers)`.
    """
    valid_blocks: list[np.ndarray] = []
    stroke_count = 0
    seg_count = 0

    for st in page.strokes:
        n_floats = len(st.pts)
        n_pts = n_floats // 2
        if n_pts < 2:
            continue
        coords = np.asarray(st.pts[: n_pts * 2], dtype="<f4").reshape(n_pts, 2)
        block = np.empty((n_pts, 3), dtype="<f4")
        block[:, 0:2] = coords
        block[0, 2] = 0.0
        if n_pts > 2:
            block[1:-1, 2] = 1.0
        block[-1, 2] = 2.0
        valid_blocks.append(block)
        stroke_count += 1
        seg_count += n_pts - 1

    if valid_blocks:
        merged = np.vstack(valid_blocks)
        payload = np.ascontiguousarray(merged, dtype="<f4").tobytes()
    else:
        payload = b""

    bbox = page.bbox if len(page.bbox) == 4 else [0.0, 0.0, 0.0, 0.0]
    headers = {
        "X-Page-Width-Mm": f"{float(page.width_mm):.2f}",
        "X-Page-Height-Mm": f"{float(page.height_mm):.2f}",
        "X-Bbox": ",".join(f"{float(v):.2f}" for v in bbox),
        "X-Stroke-Count": str(stroke_count),
        "X-Seg-Count": str(seg_count),
    }
    return payload, headers
