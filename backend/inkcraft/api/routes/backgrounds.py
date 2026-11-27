"""Custom & built-in background paper underlay template management API."""

from __future__ import annotations

from datetime import datetime, timezone
import io
import json
from pathlib import Path
import re
import threading
from typing import Any
import uuid

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image, ImageDraw

from inkcraft.api.schemas import BackgroundTemplate, MarginsMM
from inkcraft.api.state import ApiError, AppContext

router = APIRouter()

_BG_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_BG_INDEX_LOCK = threading.Lock()
MAX_UPLOAD_BYTES = 100 * 1024 * 1024

_BUILTIN_TEMPLATES: list[BackgroundTemplate] = [
    BackgroundTemplate(
        background_id="bg_letterhead_a",
        name="方案 A · 报告/信纸抬头首页",
        kind="builtin",
        description="顶部预留 54mm 抬头与信息栏，适配首页（A）与续页（B）组合排版",
        width_mm=210.0,
        height_mm=297.0,
        image_url="/api/v1/backgrounds/bg_letterhead_a/image",
        recommended_margins_mm=MarginsMM(top=56.0, right=20.0, bottom=22.0, left=20.0),
        recommended_ruled_pitch_mm=9.0,
        created_at="builtin",
    ),
    BackgroundTemplate(
        background_id="bg_lined_9mm_b",
        name="方案 B · 9mm 标准横格续页",
        kind="builtin",
        description="标准 9mm 淡青色横格纸，常规 22mm 顶边距，适合作为第 2 页起的续页底稿",
        width_mm=210.0,
        height_mm=297.0,
        image_url="/api/v1/backgrounds/bg_lined_9mm_b/image",
        recommended_margins_mm=MarginsMM(top=22.0, right=20.0, bottom=22.0, left=20.0),
        recommended_ruled_pitch_mm=9.0,
        created_at="builtin",
    ),
    BackgroundTemplate(
        background_id="bg_lined_8mm",
        name="8mm 细密横格笔记纸",
        kind="builtin",
        description="经典 8mm 间距横格 + 左侧红色装订基线，适配日常笔记与作业本",
        width_mm=210.0,
        height_mm=297.0,
        image_url="/api/v1/backgrounds/bg_lined_8mm/image",
        recommended_margins_mm=MarginsMM(top=24.0, right=18.0, bottom=20.0, left=24.0),
        recommended_ruled_pitch_mm=8.0,
        created_at="builtin",
    ),
    BackgroundTemplate(
        background_id="bg_composition_grid",
        name="传统 9mm 作文方格稿纸",
        kind="builtin",
        description="绿色双栏边框 + 9mm 正方格，经典手写稿纸风格",
        width_mm=210.0,
        height_mm=297.0,
        image_url="/api/v1/backgrounds/bg_composition_grid/image",
        recommended_margins_mm=MarginsMM(top=24.0, right=18.0, bottom=22.0, left=18.0),
        recommended_ruled_pitch_mm=9.0,
        created_at="builtin",
    ),
    BackgroundTemplate(
        background_id="bg_grid_5mm",
        name="5mm 工程坐标方格纸",
        kind="builtin",
        description="精密 5mm 淡灰方格（每 25mm 加粗），适合数学推导与图表手绘",
        width_mm=210.0,
        height_mm=297.0,
        image_url="/api/v1/backgrounds/bg_grid_5mm/image",
        recommended_margins_mm=MarginsMM(top=20.0, right=18.0, bottom=20.0, left=18.0),
        recommended_ruled_pitch_mm=10.0,
        created_at="builtin",
    ),
    BackgroundTemplate(
        background_id="bg_cornell",
        name="康奈尔笔记底稿",
        kind="builtin",
        description="顶部标题区 + 左侧 52mm 线索栏 + 右侧 9mm 横格笔记区 + 底部总结栏",
        width_mm=210.0,
        height_mm=297.0,
        image_url="/api/v1/backgrounds/bg_cornell/image",
        recommended_margins_mm=MarginsMM(top=32.0, right=16.0, bottom=42.0, left=58.0),
        recommended_ruled_pitch_mm=9.0,
        created_at="builtin",
    ),
]

_BUILTIN_MAP: dict[str, BackgroundTemplate] = {t.background_id: t for t in _BUILTIN_TEMPLATES}


def _bg_dir(ctx: AppContext) -> Path:
    d = ctx.settings.DATA_DIR / "backgrounds"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path(ctx: AppContext) -> Path:
    return _bg_dir(ctx) / "index.json"


def _load_uploaded(ctx: AppContext) -> list[BackgroundTemplate]:
    idx = _index_path(ctx)
    if not idx.is_file():
        return []
    try:
        raw = json.loads(idx.read_text(encoding="utf-8"))
        return [BackgroundTemplate(**item) for item in raw]
    except Exception:
        return []


def _save_uploaded(ctx: AppContext, items: list[BackgroundTemplate]) -> None:
    idx = _index_path(ctx)
    tmp = idx.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps([i.model_dump() for i in items], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(idx)


def _validate_bg_id(background_id: str) -> str:
    if not _BG_ID_RE.fullmatch(background_id):
        raise ApiError(400, "INVALID_BACKGROUND_ID", f"非法的背景模板 ID: {background_id}")
    return background_id


def _render_builtin_png(bg_id: str) -> bytes:
    """Render a crisp 150-DPI A4 paper background PNG using Pillow."""
    dpi_scale = 150.0 / 25.4  # px per mm
    w_mm, h_mm = 210.0, 297.0
    w_px = int(round(w_mm * dpi_scale))
    h_px = int(round(h_mm * dpi_scale))
    mm = lambda v: int(round(v * dpi_scale))

    img = Image.new("RGB", (w_px, h_px), (252, 250, 245))
    draw = ImageDraw.Draw(img)

    if bg_id == "bg_letterhead_a":
        # Decorative letterhead header block (0..50mm)
        draw.rectangle([mm(18), mm(14), mm(192), mm(46)], outline=(148, 176, 206), width=3)
        draw.line([mm(18), mm(31), mm(192), mm(31)], fill=(190, 208, 228), width=2)
        draw.line([mm(18), mm(49), mm(192), mm(49)], fill=(59, 114, 175), width=4)
        # Subtle metadata underline placeholders inside header
        for x0, x1 in [(26, 72), (82, 128), (138, 184)]:
            draw.line([mm(x0), mm(41), mm(x1), mm(41)], fill=(176, 194, 214), width=2)
        # Body ruled lines from 56mm to 275mm at 9mm pitch
        y = 56.0 + 9.0
        while y <= 275.0:
            draw.line([mm(18), mm(y), mm(192), mm(y)], fill=(208, 224, 238), width=2)
            y += 9.0
        draw.line([mm(18), mm(282), mm(192), mm(282)], fill=(210, 218, 228), width=2)

    elif bg_id == "bg_lined_9mm_b":
        # Top & bottom subtle frame lines + continuous 9mm ruled lines
        draw.line([mm(18), mm(18), mm(192), mm(18)], fill=(140, 178, 212), width=3)
        y = 22.0 + 9.0
        while y <= 275.0:
            draw.line([mm(18), mm(y), mm(192), mm(y)], fill=(208, 224, 238), width=2)
            y += 9.0
        draw.line([mm(18), mm(282), mm(192), mm(282)], fill=(210, 218, 228), width=2)

    elif bg_id == "bg_lined_8mm":
        # Left red margin line + 8mm horizontal rules
        draw.line([mm(22), mm(0), mm(22), mm(h_mm)], fill=(235, 168, 168), width=2)
        draw.line([mm(0), mm(21), mm(w_mm), mm(21)], fill=(180, 206, 232), width=3)
        y = 24.0 + 8.0
        while y <= 278.0:
            draw.line([mm(0), mm(y), mm(w_mm), mm(y)], fill=(214, 228, 240), width=2)
            y += 8.0

    elif bg_id == "bg_composition_grid":
        # Classic green Chinese composition paper
        frame_c = (118, 176, 134)
        grid_c = (178, 216, 188)
        draw.rectangle([mm(16), mm(20), mm(194), mm(276)], outline=frame_c, width=3)
        draw.rectangle([mm(18), mm(22), mm(192), mm(274)], outline=frame_c, width=2)
        pitch = 9.0
        row_gap = 2.5
        y = 24.0
        while y + pitch <= 272.0:
            draw.rectangle([mm(18), mm(y), mm(192), mm(y + pitch)], outline=grid_c, width=2)
            x = 18.0 + pitch
            while x < 191.0:
                draw.line([mm(x), mm(y), mm(x), mm(y + pitch)], fill=grid_c, width=1)
                x += pitch
            y += pitch + row_gap

    elif bg_id == "bg_grid_5mm":
        # 5mm engineering graph grid
        for step_mm in range(10, 205, 5):
            major = (step_mm - 10) % 25 == 0
            c = (196, 208, 220) if major else (228, 234, 240)
            draw.line([mm(step_mm), mm(12), mm(step_mm), mm(285)], fill=c, width=2 if major else 1)
        for step_mm in range(12, 288, 5):
            major = (step_mm - 12) % 25 == 0
            c = (196, 208, 220) if major else (228, 234, 240)
            draw.line([mm(10), mm(step_mm), mm(200), mm(step_mm)], fill=c, width=2 if major else 1)

    elif bg_id == "bg_cornell":
        # Cornell note layout
        line_c = (156, 178, 204)
        rule_c = (218, 228, 238)
        draw.line([mm(12), mm(28), mm(198), mm(28)], fill=line_c, width=3)
        draw.line([mm(54), mm(28), mm(54), mm(256)], fill=line_c, width=3)
        draw.line([mm(12), mm(256), mm(198), mm(256)], fill=line_c, width=3)
        y = 32.0 + 9.0
        while y < 254.0:
            draw.line([mm(56), mm(y), mm(196), mm(y)], fill=rule_c, width=2)
            y += 9.0

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


@router.get("/backgrounds")
async def list_backgrounds(
    request: Request,
    include_builtin: bool = Query(default=True),
) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    with _BG_INDEX_LOCK:
        uploaded = _load_uploaded(ctx)
    all_items = [*uploaded, *_BUILTIN_TEMPLATES] if include_builtin else uploaded
    return {
        "backgrounds": [b.model_dump() for b in all_items],
    }


@router.post("/backgrounds", status_code=201)
async def upload_background(
    request: Request,
    file: UploadFile = File(...),
    name: str = Form(default=""),
    width_mm: float = Form(default=210.0),
    height_mm: float = Form(default=297.0),
    margin_top: float = Form(default=22.0),
    margin_right: float = Form(default=20.0),
    margin_bottom: float = Form(default=22.0),
    margin_left: float = Form(default=20.0),
) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    raw = await file.read()
    if not raw:
        raise ApiError(400, "EMPTY_FILE", "上传的背景底稿文件为空")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ApiError(413, "FILE_TOO_LARGE", "上传的背景底稿文件超过 100MB 限制")

    orig_name = Path(file.filename or "background.png").name
    ext = Path(orig_name).suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".pdf"}:
        raise ApiError(400, "UNSUPPORTED_FORMAT", "背景底稿仅支持 PNG / JPG / WEBP / PDF 格式")

    bg_id = f"bg_u_{uuid.uuid4().hex[:10]}"
    out_png = _bg_dir(ctx) / f"{bg_id}.png"

    eff_w = float(width_mm)
    eff_h = float(height_mm)

    if ext == ".pdf":
        try:
            import fitz

            pdf = fitz.open(stream=raw, filetype="pdf")
            if len(pdf) == 0:
                raise ValueError("PDF 页面为空")
            p0 = pdf[0]
            eff_w = round(float(p0.rect.width) * 25.4 / 72.0, 2)
            eff_h = round(float(p0.rect.height) * 25.4 / 72.0, 2)
            pix = p0.get_pixmap(dpi=150)
            pix.save(str(out_png))
            pdf.close()
        except Exception as exc:
            raise ApiError(400, "PDF_RENDER_FAILED", f"PDF 背景底稿解析失败: {exc}") from exc
    else:
        try:
            im = Image.open(io.BytesIO(raw)).convert("RGB")
            w_px, h_px = im.size
            # Preserve exact raster aspect ratio automatically when user kept default 210x297 dimensions
            if (
                abs(eff_w - 210.0) < 0.5
                and abs(eff_h - 297.0) < 0.5
                and w_px > 0
                and h_px > 0
            ):
                ratio = float(w_px) / float(h_px)
                if w_px > h_px:
                    # Landscape raster -> fit long edge to 297mm (snap clean A4 if within 3%)
                    eff_w = 297.0
                    eff_h = 210.0 if abs(ratio - (297.0 / 210.0)) < 0.04 else round(max(40.0, 297.0 / ratio), 1)
                else:
                    eff_h = 297.0
                    eff_w = 210.0 if abs(ratio - (210.0 / 297.0)) < 0.04 else round(max(40.0, 297.0 * ratio), 1)
            # Clamp huge scans to max 2600px longest side for crisp 60fps Canvas texture upload
            max_side = max(im.size)
            if max_side > 2600:
                ratio = 2600.0 / max_side
                im = im.resize((int(im.width * ratio), int(im.height * ratio)), Image.Resampling.LANCZOS)
            im.save(out_png, format="PNG", optimize=True)
        except Exception as exc:
            raise ApiError(400, "IMAGE_DECODE_FAILED", f"背景底稿图片解码失败: {exc}") from exc

    display_name = name.strip() or Path(orig_name).stem
    tpl = BackgroundTemplate(
        background_id=bg_id,
        name=display_name,
        kind="uploaded",
        description=f"自定义底稿 ({orig_name}, {eff_w:.0f}×{eff_h:.0f} mm)",
        width_mm=max(20.0, min(1000.0, eff_w)),
        height_mm=max(20.0, min(1000.0, eff_h)),
        image_url=f"/api/v1/backgrounds/{bg_id}/image",
        recommended_margins_mm=MarginsMM(
            top=max(0.0, margin_top),
            right=max(0.0, margin_right),
            bottom=max(0.0, margin_bottom),
            left=max(0.0, margin_left),
        ),
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    with _BG_INDEX_LOCK:
        items = _load_uploaded(ctx)
        items.insert(0, tpl)
        _save_uploaded(ctx, items)
    return {"background": tpl.model_dump()}


@router.get("/backgrounds/{background_id}/image")
async def get_background_image(background_id: str, request: Request) -> Response:
    ctx: AppContext = request.app.state.ctx
    bg_id = _validate_bg_id(background_id)
    if bg_id in _BUILTIN_MAP:
        cache_dir = _bg_dir(ctx) / "builtin_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached_png = cache_dir / f"{bg_id}.png"
        if not cached_png.is_file():
            cached_png.write_bytes(_render_builtin_png(bg_id))
        return FileResponse(cached_png, media_type="image/png")

    bg_root = _bg_dir(ctx).resolve()
    img_path = (bg_root / f"{bg_id}.png").resolve()
    if not img_path.is_relative_to(bg_root):
        raise ApiError(400, "INVALID_BACKGROUND_ID", f"非法的背景模板路径: {background_id}")
    if not img_path.is_file():
        raise ApiError(404, "BACKGROUND_NOT_FOUND", f"未找到背景底稿: {bg_id}")
    return FileResponse(img_path, media_type="image/png")


@router.delete("/backgrounds/{background_id}")
async def delete_background(background_id: str, request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    bg_id = _validate_bg_id(background_id)
    if bg_id in _BUILTIN_MAP:
        raise ApiError(400, "BUILTIN_PROTECTED", "内置底稿模板不可删除")
    with _BG_INDEX_LOCK:
        items = _load_uploaded(ctx)
        kept = [i for i in items if i.background_id != bg_id]
        if len(kept) == len(items):
            raise ApiError(404, "BACKGROUND_NOT_FOUND", f"未找到背景底稿: {bg_id}")
        _save_uploaded(ctx, kept)
    bg_root = _bg_dir(ctx).resolve()
    img_path = (bg_root / f"{bg_id}.png").resolve()
    if img_path.is_relative_to(bg_root) and img_path.is_file():
        img_path.unlink()
    return {"deleted": True, "background_id": bg_id}
