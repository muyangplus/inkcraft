"""Scan preprocessing, fiducial perspective alignment, grid drop-out, glyph cropping & QA review HTML.

Works cleanly on local CPU with NumPy + Pillow, while automatically leveraging OpenCV (`cv2`)
when installed (e.g. inside Google Colab).
"""

from __future__ import annotations

import base64
from collections import deque
from dataclasses import dataclass, field
import html
import io
import json
from pathlib import Path
from typing import Literal, Sequence

import numpy as np
from PIL import Image, ImageFilter

from hwbuilder.sheet_gen import GridColor, SheetCellSpec, SheetManifest

try:  # Optional OpenCV acceleration in Google Colab
    import cv2  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]


@dataclass
class SegmentConfig:
    """Parameters for scan alignment, drop-out filtering, binarization, and cell cropping."""

    target_dpi: int = 300
    grid_color: GridColor = "cyan"
    binarize_method: Literal["otsu", "sauvola", "hybrid"] = "hybrid"
    sauvola_window: int = 25
    sauvola_k: float = 0.22
    cell_inner_margin_mm: float = 0.8
    min_component_area_px: int = 8
    min_ink_pixels: int = 25
    max_ink_ratio: float = 0.65
    output_size_px: int = 128
    pad_px: int = 10
    use_cv2_if_available: bool = True


@dataclass
class CroppedGlyph:
    """Single cropped glyph sample extracted from a scanned collection sheet."""

    cell_id: str
    char: str
    codepoint: int
    page: int
    row: int
    col: int
    repeat_index: int
    gray: np.ndarray          # uint8 (H, W), 0=black ink, 255=white paper
    binary: np.ndarray        # bool (H, W), True=foreground ink
    ink_ratio: float
    ink_pixels: int
    flags: list[str] = field(default_factory=list)
    image_path: str = ""
    kept: bool = True

    def to_metadata_dict(self) -> dict:
        return {
            "cell_id": self.cell_id,
            "char": self.char,
            "codepoint": self.codepoint,
            "page": self.page,
            "row": self.row,
            "col": self.col,
            "repeat_index": self.repeat_index,
            "ink_ratio": round(self.ink_ratio, 5),
            "ink_pixels": self.ink_pixels,
            "flags": list(self.flags),
            "image_path": self.image_path,
            "kept": self.kept,
        }


def normalize_illumination(rgb_or_gray: np.ndarray, blur_radius: int = 35) -> np.ndarray:
    """Remove uneven paper lighting / scanner shadows via large-scale background division."""
    arr = np.asarray(rgb_or_gray, dtype=np.float32)
    if arr.ndim == 2:
        h, w = arr.shape
        ds_w = max(8, w // 4)
        ds_h = max(8, h // 4)
        pil_small = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode="L").resize(
            (ds_w, ds_h), Image.Resampling.BILINEAR
        )
        bg_small = pil_small.filter(ImageFilter.GaussianBlur(radius=max(2, blur_radius // 4)))
        bg = np.asarray(bg_small.resize((w, h), Image.Resampling.BILINEAR), dtype=np.float32)
        norm = (arr / np.maximum(bg, 16.0)) * 255.0
        return np.clip(norm, 0, 255).astype(np.uint8)

    # RGB image: normalize each channel against its own smooth paper illumination field
    out = np.empty_like(arr)
    h, w, _ = arr.shape
    ds_w = max(8, w // 4)
    ds_h = max(8, h // 4)
    pil_small = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode="RGB").resize(
        (ds_w, ds_h), Image.Resampling.BILINEAR
    )
    bg_small = pil_small.filter(ImageFilter.GaussianBlur(radius=max(2, blur_radius // 4)))
    bg = np.asarray(bg_small.resize((w, h), Image.Resampling.BILINEAR), dtype=np.float32)
    out = (arr / np.maximum(bg, 16.0)) * 255.0
    return np.clip(out, 0, 255).astype(np.uint8)


def drop_out_grid_color(
    rgb: np.ndarray,
    grid_color: GridColor = "cyan",
    chroma_thresh: float = 22.0,
) -> np.ndarray:
    """Convert color scan to grayscale while dropping out cyan or red guide grid lines.

    Black/dark-neutral pen ink has R ≈ G ≈ B (low chromaticity), while cyan guides have
    high (G, B) vs R and red guides have high R vs (G, B).
    """
    arr = np.asarray(rgb, dtype=np.float32)
    if arr.ndim == 2:
        return np.clip(arr, 0, 255).astype(np.uint8)

    r = arr[:, :, 0]
    g = arr[:, :, 1]
    b = arr[:, :, 2]

    if grid_color == "red":
        # Red guide lines have high R and lower G/B; Green/Blue channels see red as dark,
        # whereas Red channel sees red as bright white!
        base = r.copy()
        chroma = r - 0.5 * (g + b)
        is_grid = (chroma > chroma_thresh) & (r > 110.0)
        # Keep neutral dark ink crisp by combining luminance where chroma is low
        neutral_luma = 0.299 * r + 0.587 * g + 0.114 * b
        gray = np.where(is_grid, 255.0, np.maximum(base, neutral_luma))
    else:
        # Cyan guide lines have high G & B, lower R; pushing high-(G,B)-minus-R pixels to white
        # and taking max(G, B) suppresses cyan completely while keeping black ink dark.
        chroma = 0.5 * (g + b) - r
        is_grid = (chroma > chroma_thresh) & (np.maximum(g, b) > 110.0)
        cyan_blind = np.maximum(g, b)
        neutral_luma = 0.299 * r + 0.587 * g + 0.114 * b
        gray = np.where(is_grid, 255.0, np.where(chroma > chroma_thresh * 0.5, cyan_blind, neutral_luma))

    return np.clip(gray, 0, 255).astype(np.uint8)


def otsu_threshold(gray: np.ndarray) -> int:
    """Pure-NumPy Otsu global threshold (returns threshold t where ink is `gray < t`)."""
    hist, _ = np.histogram(gray.ravel(), bins=256, range=(0, 256))
    total = int(gray.size)
    if total == 0:
        return 128
    prob = hist.astype(np.float64) / total
    bins = np.arange(256, dtype=np.float64)
    w0 = np.cumsum(prob)
    w1 = 1.0 - w0
    mu0 = np.cumsum(prob * bins)
    mu_total = mu0[-1]
    valid = (w0 > 1e-9) & (w1 > 1e-9)
    sigma_b = np.zeros(256, dtype=np.float64)
    sigma_b[valid] = ((mu_total * w0[valid] - mu0[valid]) ** 2) / (w0[valid] * w1[valid])
    return int(np.argmax(sigma_b))


def sauvola_binarize(
    gray: np.ndarray,
    window: int = 25,
    k: float = 0.22,
    r: float = 128.0,
) -> np.ndarray:
    """Pure-NumPy integral-image Sauvola local adaptive binarization (True = dark ink)."""
    img = gray.astype(np.float64)
    h, w = img.shape
    win = max(3, int(window) | 1)
    pad = win // 2

    padded = np.pad(img, pad, mode="reflect")
    padded_sq = padded * padded

    def _box_sum(a: np.ndarray) -> np.ndarray:
        integ = np.pad(a, ((1, 0), (1, 0)), mode="constant").cumsum(axis=0).cumsum(axis=1)
        return (
            integ[win : win + h, win : win + w]
            - integ[:h, win : win + w]
            - integ[win : win + h, :w]
            + integ[:h, :w]
        )

    area = float(win * win)
    mean = _box_sum(padded) / area
    mean_sq = _box_sum(padded_sq) / area
    std = np.sqrt(np.maximum(0.0, mean_sq - mean * mean))
    thresh = mean * (1.0 + k * (std / r - 1.0))
    return img < thresh


def binarize_glyph(gray: np.ndarray, cfg: SegmentConfig) -> np.ndarray:
    """Binarize a grayscale glyph patch into boolean ink mask (`True` = foreground)."""
    if gray.size == 0:
        return np.zeros_like(gray, dtype=bool)
    # Guard against blank white patches (all pixels near 255)
    if float(gray.max()) - float(gray.min()) < 20.0:
        return np.zeros_like(gray, dtype=bool)

    t_otsu = min(220, max(40, otsu_threshold(gray)))
    mask_otsu = gray < t_otsu
    if cfg.binarize_method == "otsu":
        return mask_otsu
    mask_sauvola = sauvola_binarize(gray, window=cfg.sauvola_window, k=cfg.sauvola_k)
    if cfg.binarize_method == "sauvola":
        return mask_sauvola
    # Hybrid: combine local Sauvola sensitivity with global Otsu ceiling to avoid white-paper noise
    return mask_sauvola & (gray < min(235, t_otsu + 25))


def _label_components_numpy(mask: np.ndarray) -> tuple[np.ndarray, list[tuple[int, int, int, int, int]]]:
    """Pure-NumPy 8-connected component labeling returning `(labels, stats)`.

    Each stats entry is `(area, x0, y0, x1, y1)` for label `idx + 1`.
    """
    h, w = mask.shape
    labels = np.zeros((h, w), dtype=np.int32)
    stats: list[tuple[int, int, int, int, int]] = []
    cur_label = 0
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return labels, stats

    neighbors = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))
    for sy, sx in zip(ys.tolist(), xs.tolist()):
        if labels[sy, sx] != 0:
            continue
        cur_label += 1
        q: deque[tuple[int, int]] = deque([(sy, sx)])
        labels[sy, sx] = cur_label
        area = 0
        min_x = max_x = sx
        min_y = max_y = sy
        while q:
            cy, cx = q.popleft()
            area += 1
            if cx < min_x:
                min_x = cx
            if cx > max_x:
                max_x = cx
            if cy < min_y:
                min_y = cy
            if cy > max_y:
                max_y = cy
            for dy, dx in neighbors:
                ny, nx = cy + dy, cx + dx
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and labels[ny, nx] == 0:
                    labels[ny, nx] = cur_label
                    q.append((ny, nx))
        stats.append((area, min_x, min_y, max_x, max_y))
    return labels, stats


def remove_small_components(mask: np.ndarray, min_area: int = 8) -> np.ndarray:
    """Filter out isolated dust/noise connected components smaller than `min_area` pixels."""
    if min_area <= 1 or not mask.any():
        return mask
    if cv2 is not None:
        num, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
        keep = np.zeros(num, dtype=bool)
        for lbl in range(1, num):
            if int(stats[lbl, cv2.CC_STAT_AREA]) >= min_area:
                keep[lbl] = True
        return keep[labels]

    labels, stats = _label_components_numpy(mask)
    out = np.zeros_like(mask, dtype=bool)
    for idx, (area, *_bbox) in enumerate(stats, start=1):
        if area >= min_area:
            out |= labels == idx
    return out


def _solve_perspective_coeffs(
    dst_pts: np.ndarray,
    src_pts: np.ndarray,
) -> tuple[float, float, float, float, float, float, float, float]:
    """Solve 8 perspective transform coefficients mapping dst (x, y) -> src (X, Y) for PIL."""
    matrix = []
    rhs = []
    for (x, y), (X, Y) in zip(dst_pts, src_pts):
        matrix.append([x, y, 1.0, 0.0, 0.0, 0.0, -X * x, -X * y])
        rhs.append(X)
        matrix.append([0.0, 0.0, 0.0, x, y, 1.0, -Y * x, -Y * y])
        rhs.append(Y)
    A = np.asarray(matrix, dtype=np.float64)
    b = np.asarray(rhs, dtype=np.float64)
    try:
        coeffs = np.linalg.solve(A, b)
    except np.linalg.LinAlgError as exc:
        raise ValueError("Perspective fiducial points are degenerate or collinear") from exc
    return tuple(float(c) for c in coeffs)  # type: ignore[return-value]


def _detect_fiducials_cv2(gray: np.ndarray) -> dict[str, tuple[float, float]] | None:
    """Detect ArUco DICT_4X4_50 markers 0..3 using OpenCV when available."""
    if cv2 is None or not hasattr(cv2, "aruco"):
        return None
    try:
        aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        if hasattr(cv2.aruco, "ArucoDetector"):
            detector = cv2.aruco.ArucoDetector(aruco_dict)
            corners, ids, _ = detector.detectMarkers(gray)
        else:
            corners, ids, _ = cv2.aruco.detectMarkers(gray, aruco_dict)
        if ids is None:
            return None
        id_map = {0: "tl", 1: "tr", 2: "br", 3: "bl"}
        found: dict[str, tuple[float, float]] = {}
        for corner, mid in zip(corners, ids.flatten().tolist()):
            if mid in id_map:
                pts = corner.reshape(-1, 2)
                found[id_map[mid]] = (float(pts[:, 0].mean()), float(pts[:, 1].mean()))
        return found if len(found) == 4 else None
    except Exception:
        return None


def _detect_fiducials_numpy(gray: np.ndarray) -> dict[str, tuple[float, float]] | None:
    """Pure-NumPy corner fiducial detector searching the 4 outer corner ROIs."""
    h, w = gray.shape
    roi_h = max(32, int(h * 0.22))
    roi_w = max(32, int(w * 0.22))

    corners_roi = {
        "tl": (0, 0, roi_w, roi_h),
        "tr": (w - roi_w, 0, w, roi_h),
        "br": (w - roi_w, h - roi_h, w, h),
        "bl": (0, h - roi_h, roi_w, h),
    }

    found: dict[str, tuple[float, float]] = {}
    for key, (x0, y0, x1, y1) in corners_roi.items():
        patch = gray[y0:y1, x0:x1]
        if float(patch.max()) - float(patch.min()) < 30.0:
            return None
        t = min(150, otsu_threshold(patch))
        dark = patch < t
        # Downsample slightly for fast CC detection on high-DPI scans
        scale = max(1, min(patch.shape) // 160)
        if scale > 1:
            dark_s = dark[::scale, ::scale]
        else:
            dark_s = dark
        labels, stats = _label_components_numpy(dark_s)
        best_score = -1.0
        best_center: tuple[float, float] | None = None
        min_side = max(4, int(min(dark_s.shape) * 0.08))
        max_side = int(min(dark_s.shape) * 0.65)
        for area, bx0, by0, bx1, by1 in stats:
            bw = bx1 - bx0 + 1
            bh = by1 - by0 + 1
            if bw < min_side or bh < min_side or bw > max_side or bh > max_side:
                continue
            aspect = bw / float(bh)
            if not (0.70 <= aspect <= 1.42):
                continue
            fill = area / float(bw * bh)
            if not (0.28 <= fill <= 0.96):
                continue
            # Prefer square, compact markers with substantial area
            score = area * (1.0 - abs(1.0 - aspect))
            if score > best_score:
                best_score = score
                cx = x0 + (bx0 + bx1) * 0.5 * scale
                cy = y0 + (by0 + by1) * 0.5 * scale
                best_center = (cx, cy)
        if best_center is None:
            return None
        found[key] = best_center

    return found if len(found) == 4 else None


def align_scan_to_manifest(
    image: Image.Image,
    manifest: SheetManifest,
    cfg: SegmentConfig,
) -> tuple[Image.Image, str]:
    """Warp scanned sheet image into canonical manifest pixel dimensions at `cfg.target_dpi`."""
    px_per_mm = cfg.target_dpi / 25.4
    out_w = int(round(manifest.page_width_mm * px_per_mm))
    out_h = int(round(manifest.page_height_mm * px_per_mm))

    rgb = image.convert("RGB")
    gray_raw = np.asarray(rgb.convert("L"), dtype=np.uint8)

    detected: dict[str, tuple[float, float]] | None = None
    method = "fallback_resize"
    if cfg.use_cv2_if_available and cv2 is not None:
        detected = _detect_fiducials_cv2(gray_raw)
        if detected is not None:
            method = "cv2_aruco"
    if detected is None:
        detected = _detect_fiducials_numpy(gray_raw)
        if detected is not None:
            method = "numpy_fiducial"

    if detected is None or not all(k in manifest.fiducials_mm for k in ("tl", "tr", "br", "bl")):
        return rgb.resize((out_w, out_h), Image.Resampling.BILINEAR), "fallback_resize"

    order = ("tl", "tr", "br", "bl")
    src_pts = np.array([detected[k] for k in order], dtype=np.float64)
    dst_pts = np.array(
        [
            [manifest.fiducials_mm[k][0] * px_per_mm, manifest.fiducials_mm[k][1] * px_per_mm]
            for k in order
        ],
        dtype=np.float64,
    )

    if cfg.use_cv2_if_available and cv2 is not None:
        H, _ = cv2.findHomography(src_pts.astype(np.float32), dst_pts.astype(np.float32))
        if H is not None:
            warped = cv2.warpPerspective(
                np.asarray(rgb, dtype=np.uint8),
                H,
                (out_w, out_h),
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=(255, 255, 255),
            )
            return Image.fromarray(warped, mode="RGB"), method

    try:
        coeffs = _solve_perspective_coeffs(dst_pts, src_pts)
    except (ValueError, np.linalg.LinAlgError):
        return rgb.resize((out_w, out_h), Image.Resampling.BILINEAR), "fallback_resize"
    warped_pil = rgb.transform(
        (out_w, out_h),
        Image.Transform.PERSPECTIVE,
        coeffs,
        resample=Image.Resampling.BILINEAR,
        fillcolor=(255, 255, 255),
    )
    return warped_pil, method


def _normalize_crop_patch(
    gray_patch: np.ndarray,
    mask_patch: np.ndarray,
    output_size: int,
    pad: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Center tight ink bounding box inside a square `(output_size, output_size)` canvas."""
    ys, xs = np.nonzero(mask_patch)
    if len(ys) == 0:
        g_out = np.full((output_size, output_size), 255, dtype=np.uint8)
        b_out = np.zeros((output_size, output_size), dtype=bool)
        return g_out, b_out

    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    sub_g = gray_patch[y0:y1, x0:x1]
    sub_b = mask_patch[y0:y1, x0:x1]

    sh, sw = sub_g.shape
    inner = max(8, output_size - 2 * pad)
    scale = min(inner / float(sw), inner / float(sh))
    nw = max(1, int(round(sw * scale)))
    nh = max(1, int(round(sh * scale)))

    g_resized = np.asarray(
        Image.fromarray(sub_g, mode="L").resize((nw, nh), Image.Resampling.BILINEAR),
        dtype=np.uint8,
    )
    b_resized = (
        np.asarray(
            Image.fromarray((sub_b.astype(np.uint8) * 255), mode="L").resize(
                (nw, nh), Image.Resampling.NEAREST
            ),
            dtype=np.uint8,
        )
        > 127
    )

    g_canvas = np.full((output_size, output_size), 255, dtype=np.uint8)
    b_canvas = np.zeros((output_size, output_size), dtype=bool)
    oy = (output_size - nh) // 2
    ox = (output_size - nw) // 2
    g_canvas[oy : oy + nh, ox : ox + nw] = g_resized
    b_canvas[oy : oy + nh, ox : ox + nw] = b_resized
    return g_canvas, b_canvas


def segment_scan(
    scan_image: str | Path | Image.Image | np.ndarray,
    manifest: SheetManifest,
    page_index: int = 0,
    config: SegmentConfig | None = None,
    *,
    save_crops_dir: str | Path | None = None,
) -> tuple[list[CroppedGlyph], dict[str, object]]:
    """Preprocess, align, drop-out filter, binarize, and crop every glyph cell on one sheet page.

    Returns `(crops, diagnostics)`.
    """
    cfg = config or SegmentConfig(grid_color=manifest.grid_color)
    if page_index < 0 or page_index >= len(manifest.pages):
        raise IndexError(f"page_index={page_index} out of range for manifest ({len(manifest.pages)} pages)")

    if isinstance(scan_image, (str, Path)):
        pil_img = Image.open(scan_image).convert("RGB")
    elif isinstance(scan_image, np.ndarray):
        pil_img = Image.fromarray(scan_image).convert("RGB")
    else:
        pil_img = scan_image.convert("RGB")

    # 1. Perspective alignment using 4 corner fiducials
    aligned_pil, align_method = align_scan_to_manifest(pil_img, manifest, cfg)
    aligned_rgb = np.asarray(aligned_pil, dtype=np.uint8)

    # 2. Illumination normalization + drop-out grid filtering
    norm_rgb = normalize_illumination(aligned_rgb)
    ink_gray = drop_out_grid_color(norm_rgb, grid_color=cfg.grid_color)

    px_per_mm = cfg.target_dpi / 25.4
    margin_px = int(round(cfg.cell_inner_margin_mm * px_per_mm))
    page_spec = manifest.pages[page_index]

    crops_out_dir = Path(save_crops_dir) if save_crops_dir is not None else None
    if crops_out_dir is not None:
        crops_out_dir.mkdir(parents=True, exist_ok=True)

    crops: list[CroppedGlyph] = []
    h_img, w_img = ink_gray.shape

    for cell in page_spec.cells:
        bx0, by0, bx1, by1 = cell.write_box_mm
        x0 = max(0, int(round(bx0 * px_per_mm)) + margin_px)
        y0 = max(0, int(round(by0 * px_per_mm)) + margin_px)
        x1 = min(w_img, int(round(bx1 * px_per_mm)) - margin_px)
        y1 = min(h_img, int(round(by1 * px_per_mm)) - margin_px)
        if x1 <= x0 + 4 or y1 <= y0 + 4:
            x0 = max(0, int(round(bx0 * px_per_mm)))
            y0 = max(0, int(round(by0 * px_per_mm)))
            x1 = min(w_img, int(round(bx1 * px_per_mm)))
            y1 = min(h_img, int(round(by1 * px_per_mm)))

        raw_gray = ink_gray[y0:y1, x0:x1]
        raw_mask = binarize_glyph(raw_gray, cfg)
        clean_mask = remove_small_components(raw_mask, min_area=cfg.min_component_area_px)

        ink_pixels = int(clean_mask.sum())
        cell_area = max(1, clean_mask.size)
        ink_ratio = ink_pixels / float(cell_area)

        flags: list[str] = []
        if ink_pixels < cfg.min_ink_pixels:
            flags.append("empty")
        if ink_ratio > cfg.max_ink_ratio:
            flags.append("too_dense")
        if ink_pixels >= cfg.min_ink_pixels and (
            clean_mask[0, :].any()
            or clean_mask[-1, :].any()
            or clean_mask[:, 0].any()
            or clean_mask[:, -1].any()
        ):
            flags.append("touching_border")

        norm_g, norm_b = _normalize_crop_patch(
            raw_gray, clean_mask, output_size=cfg.output_size_px, pad=cfg.pad_px
        )

        img_path_str = ""
        if crops_out_dir is not None:
            fname = f"{cell.cell_id}_U{cell.codepoint:04X}.png"
            out_file = crops_out_dir / fname
            Image.fromarray(norm_g, mode="L").save(out_file)
            img_path_str = str(out_file)

        crops.append(
            CroppedGlyph(
                cell_id=cell.cell_id,
                char=cell.char,
                codepoint=cell.codepoint,
                page=cell.page,
                row=cell.row,
                col=cell.col,
                repeat_index=cell.repeat_index,
                gray=norm_g,
                binary=norm_b,
                ink_ratio=ink_ratio,
                ink_pixels=ink_pixels,
                flags=flags,
                image_path=img_path_str,
                kept="empty" not in flags,
            )
        )

    diagnostics = {
        "page_index": page_index,
        "align_method": align_method,
        "aligned_size": [aligned_rgb.shape[1], aligned_rgb.shape[0]],
        "total_cells": len(crops),
        "kept_initial": sum(1 for c in crops if c.kept),
        "flagged_cells": sum(1 for c in crops if c.flags),
    }
    return crops, diagnostics


def _png_data_uri(gray: np.ndarray) -> str:
    buf = io.BytesIO()
    Image.fromarray(gray, mode="L").save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def export_review_html(
    crops: Sequence[CroppedGlyph],
    out_html: str | Path,
    *,
    title: str = "HWBuilder 扫描切片人工复核面板",
) -> Path:
    """Export a standalone interactive HTML page for clicking to reject/keep glyph crops.

    Users can inspect each glyph crop, toggle kept/rejected status by clicking cards, filter
    flagged crops, and download `kept_ids.json` directly from the browser.
    """
    out_path = Path(out_html)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    records = []
    for crop in crops:
        bin_img = np.where(crop.binary, 15, 250).astype(np.uint8)
        records.append(
            {
                "cell_id": crop.cell_id,
                "char": crop.char,
                "codepoint": f"U+{crop.codepoint:04X}",
                "page": crop.page,
                "row": crop.row,
                "col": crop.col,
                "ink_ratio": round(crop.ink_ratio, 4),
                "ink_pixels": crop.ink_pixels,
                "flags": crop.flags,
                "kept": bool(crop.kept),
                "gray_uri": _png_data_uri(crop.gray),
                "bin_uri": _png_data_uri(bin_img),
            }
        )

    data_json = (
        json.dumps(records, ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    safe_title = html.escape(title)

    page_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{safe_title}</title>
<style>
  :root {{
    --bg: #f6f4ef; --card: #ffffff; --ink: #1e2329; --muted: #6c737f;
    --accent: #2563eb; --ok: #15803d; --warn: #d97706; --bad: #dc2626; --border: #e2dfd7;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: system-ui, -apple-system, "PingFang SC", sans-serif; background: var(--bg); color: var(--ink); }}
  header {{
    position: sticky; top: 0; z-index: 10; background: #fff; border-bottom: 1px solid var(--border);
    padding: 12px 20px; display: flex; flex-wrap: wrap; gap: 10px; align-items: center; justify-content: space-between;
  }}
  h1 {{ font-size: 16px; margin: 0; }}
  .controls {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
  button, select, input {{
    font-size: 13px; padding: 6px 10px; border-radius: 6px; border: 1px solid var(--border); background: #fff; cursor: pointer;
  }}
  button.primary {{ background: var(--accent); color: #fff; border-color: var(--accent); font-weight: 600; }}
  button.active {{ background: #eff6ff; border-color: var(--accent); color: var(--accent); }}
  .stats {{ font-size: 13px; color: var(--muted); }}
  .grid {{
    display: grid; grid-template-columns: repeat(auto-fill, minmax(136px, 1fr));
    gap: 10px; padding: 16px 20px;
  }}
  .card {{
    background: var(--card); border: 2px solid var(--border); border-radius: 8px; padding: 8px;
    cursor: pointer; transition: transform 0.08s ease, border-color 0.12s ease; user-select: none;
  }}
  .card:hover {{ transform: translateY(-1px); border-color: var(--accent); }}
  .card.rejected {{ border-color: var(--bad); background: #fef2f2; opacity: 0.62; }}
  .card.flagged:not(.rejected) {{ border-color: var(--warn); }}
  .card-head {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px; }}
  .char {{ font-size: 20px; font-weight: 700; line-height: 1; }}
  .cid {{ font-size: 10px; color: var(--muted); font-family: monospace; }}
  .thumb-wrap {{
    width: 100%; aspect-ratio: 1; background: #fafafa; border: 1px solid #eee; border-radius: 4px;
    display: flex; align-items: center; justify-content: center; overflow: hidden;
  }}
  .thumb-wrap img {{ width: 100%; height: 100%; object-fit: contain; image-rendering: pixelated; }}
  .meta {{ margin-top: 6px; display: flex; justify-content: space-between; align-items: center; font-size: 11px; color: var(--muted); }}
  .badge {{ padding: 1px 5px; border-radius: 4px; font-size: 10px; font-weight: 600; }}
  .badge.ok {{ background: #dcfce7; color: var(--ok); }}
  .badge.bad {{ background: #fee2e2; color: var(--bad); }}
  .badge.warn {{ background: #fef3c7; color: var(--warn); }}
</style>
</head>
<body>
<header>
  <div>
    <h1>{safe_title}</h1>
    <div class="stats" id="stats"></div>
  </div>
  <div class="controls">
    <input id="search" type="text" placeholder="搜索字符或 cell_id..." />
    <button data-filter="all" class="active">全部</button>
    <button data-filter="kept">仅保留</button>
    <button data-filter="rejected">仅剔除</button>
    <button data-filter="flagged">异常警告</button>
    <button id="toggleMode">切换二值图</button>
    <button id="keepAll">全部保留</button>
    <button id="rejectFlagged">剔除空/异常</button>
    <button id="exportBtn" class="primary">导出 kept_ids.json</button>
  </div>
</header>
<main class="grid" id="grid"></main>
<script>
const ITEMS = {data_json};
let filterMode = "all";
let showBinary = false;
let searchText = "";

function render() {{
  const grid = document.getElementById("grid");
  grid.innerHTML = "";
  let keptCount = 0, flagCount = 0;
  for (const it of ITEMS) {{
    if (it.kept) keptCount++;
    if (it.flags.length > 0) flagCount++;
  }}
  document.getElementById("stats").textContent =
    `总切片: ${{ITEMS.length}} · 保留: ${{keptCount}} · 剔除: ${{ITEMS.length - keptCount}} · 标记异常: ${{flagCount}}（点击卡片切换保留/剔除）`;

  const q = searchText.trim().toLowerCase();
  for (const it of ITEMS) {{
    if (filterMode === "kept" && !it.kept) continue;
    if (filterMode === "rejected" && it.kept) continue;
    if (filterMode === "flagged" && it.flags.length === 0) continue;
    if (q && !it.char.toLowerCase().includes(q) && !it.cell_id.toLowerCase().includes(q)) continue;

    const card = document.createElement("div");
    card.className = "card" + (it.kept ? "" : " rejected") + (it.flags.length ? " flagged" : "");
    card.onclick = () => {{ it.kept = !it.kept; render(); }};

    const head = document.createElement("div");
    head.className = "card-head";
    const charEl = document.createElement("span");
    charEl.className = "char";
    charEl.textContent = String(it.char ?? "");
    const cidEl = document.createElement("span");
    cidEl.className = "cid";
    cidEl.textContent = String(it.cell_id ?? "");
    head.appendChild(charEl);
    head.appendChild(cidEl);

    const thumbWrap = document.createElement("div");
    thumbWrap.className = "thumb-wrap";
    const imgEl = document.createElement("img");
    imgEl.src = showBinary ? it.bin_uri : it.gray_uri;
    imgEl.alt = String(it.char ?? "");
    thumbWrap.appendChild(imgEl);

    const meta = document.createElement("div");
    meta.className = "meta";
    const flagSpan = document.createElement("span");
    if (it.flags.length) {{
      flagSpan.className = "badge warn";
      flagSpan.textContent = it.flags.join(",");
    }} else {{
      flagSpan.textContent = `${{(it.ink_ratio * 100).toFixed(1)}}%`;
    }}
    const statusSpan = document.createElement("span");
    statusSpan.className = it.kept ? "badge ok" : "badge bad";
    statusSpan.textContent = it.kept ? "保留" : "剔除";
    meta.appendChild(flagSpan);
    meta.appendChild(statusSpan);

    card.appendChild(head);
    card.appendChild(thumbWrap);
    card.appendChild(meta);
    grid.appendChild(card);
  }}
}}

document.querySelectorAll("button[data-filter]").forEach(btn => {{
  btn.onclick = () => {{
    filterMode = btn.dataset.filter;
    document.querySelectorAll("button[data-filter]").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    render();
  }};
}});
document.getElementById("search").oninput = e => {{ searchText = e.target.value; render(); }};
document.getElementById("toggleMode").onclick = e => {{
  showBinary = !showBinary;
  e.target.textContent = showBinary ? "切换灰度图" : "切换二值图";
  render();
}};
document.getElementById("keepAll").onclick = () => {{ ITEMS.forEach(i => i.kept = true); render(); }};
document.getElementById("rejectFlagged").onclick = () => {{
  ITEMS.forEach(i => {{ if (i.flags.length > 0) i.kept = false; }});
  render();
}};
document.getElementById("exportBtn").onclick = () => {{
  const payload = {{
    total: ITEMS.length,
    kept_ids: ITEMS.filter(i => i.kept).map(i => i.cell_id),
    rejected_ids: ITEMS.filter(i => !i.kept).map(i => i.cell_id),
  }};
  const blob = new Blob([JSON.stringify(payload, null, 2)], {{ type: "application/json" }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "kept_ids.json";
  a.click();
  URL.revokeObjectURL(url);
}};
render();
</script>
</body>
</html>
"""
    out_path.write_text(page_html, encoding="utf-8")
    return out_path
