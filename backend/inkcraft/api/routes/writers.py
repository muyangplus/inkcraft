"""Multi-writer .hwfont hot-swap, glyph inspection, coverage, import, and deletion routes."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import tempfile
from typing import Any

from fastapi import APIRouter, File, Query, Request, UploadFile

from inkcraft.api.schemas import ActiveWriterRequest
from inkcraft.api.state import ApiError, AppContext
from inkcraft.writers.fallback.hershey import BUILTIN_GLYPHS

router = APIRouter()


@router.get("/writers")
async def list_writers(request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    writers = ctx.writers.list_writers()
    return {
        "active_writer_id": ctx.writers.active_writer_id,
        "writers": [w.model_dump() for w in writers],
    }


@router.post("/writers")
async def upload_writer(
    request: Request,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    filename = file.filename or "uploaded.hwfont"
    if not filename.lower().endswith(".hwfont"):
        raise ApiError(400, "INVALID_FILE_TYPE", "仅支持上传 .hwfont 笔迹字体文件")

    content = await file.read()
    if not content:
        raise ApiError(400, "EMPTY_FILE", "上传的 .hwfont 文件为空")

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".hwfont", delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        meta = ctx.writers.import_file(tmp_path, filename)
    except ValueError as exc:
        raise ApiError(422, "INVALID_HWFONT", str(exc)) from exc
    except Exception as exc:
        raise ApiError(422, "INVALID_HWFONT", f"笔迹字体校验失败: {exc}") from exc
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass

    return {"writer": meta.model_dump()}


@router.get("/writers/active")
async def get_active_writer(request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    reader = ctx.writers.get()
    return {"writer": reader.meta.model_dump() if reader is not None else None}


@router.post("/writers/active")
async def set_active_writer(
    body: ActiveWriterRequest,
    request: Request,
) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    try:
        meta = ctx.writers.set_active(body.writer_id)
    except KeyError as exc:
        raise ApiError(404, "WRITER_NOT_FOUND", f"未找到书写者: {body.writer_id}") from exc
    return {"active_writer_id": meta.writer_id}


@router.get("/writers/{writer_id}/glyphs/{char}")
async def get_writer_glyph(
    writer_id: str,
    char: str,
    request: Request,
    all_variants: int = Query(default=1, ge=0, le=1),
) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    reader = ctx.writers.get(writer_id)
    if reader is None:
        raise ApiError(404, "WRITER_NOT_FOUND", f"未找到书写者: {writer_id}")
    if not char:
        raise ApiError(400, "INVALID_CHAR", "字符参数不能为空")

    ch = char[0]
    variants = reader.variants(ch)
    if not all_variants and variants:
        variants = variants[:1]

    serialized = []
    for v in variants:
        strokes_flat = [
            [int(val) for val in s.pts.reshape(-1).tolist()]
            for s in v.strokes
        ]
        serialized.append(
            {
                "variant_id": v.variant_id,
                "variant_no": v.variant_no,
                "source": v.source,
                "quality": v.quality,
                "weight": v.weight,
                "advance": v.advance,
                "bbox": list(v.bbox),
                "strokes": strokes_flat,
            }
        )

    return {
        "char": ch,
        "codepoint": ord(ch),
        "variants": serialized,
    }


@router.get("/writers/{writer_id}/coverage")
async def get_writer_coverage(
    writer_id: str,
    request: Request,
    doc_id: str | None = Query(default=None),
) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    reader = ctx.writers.get(writer_id)
    if reader is None:
        raise ApiError(404, "WRITER_NOT_FOUND", f"未找到书写者: {writer_id}")

    counts: Counter[str] = Counter()
    if doc_id:
        doc = ctx.load_docir(doc_id)
        if doc is None:
            raise ApiError(404, "DOCUMENT_NOT_FOUND", f"文档不存在: {doc_id}")
        for blk in doc.blocks:
            if blk.type == "discarded":
                continue
            for ch in blk.plain_text():
                if ch.isspace():
                    continue
                counts[ch] += 1
    else:
        for ch in reader.meta.preview_text:
            if not ch.isspace():
                counts[ch] += 1

    total_chars = sum(counts.values())
    unique_chars = len(counts)
    covered = 0
    missing: list[dict[str, Any]] = []

    for ch, cnt in counts.most_common():
        if reader.has(ch):
            covered += 1
        else:
            missing.append(
                {
                    "char": ch,
                    "count": cnt,
                    "fallback_available": ch in BUILTIN_GLYPHS,
                }
            )

    return {
        "total_chars": total_chars,
        "unique_chars": unique_chars,
        "covered": covered,
        "missing": missing,
    }


@router.delete("/writers/{writer_id}")
async def delete_writer(writer_id: str, request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    protected: set[str] = set()
    if ctx.machine.is_busy_with_job():
        active_job = ctx.machine.get_active_job_snapshot()
        if active_job:
            layout = ctx.db.get_layout(active_job["layout_id"])
            if layout and layout.get("writer_id"):
                protected.add(layout["writer_id"])

    try:
        ctx.writers.delete(writer_id, protected_ids=protected)
    except KeyError as exc:
        raise ApiError(404, "WRITER_NOT_FOUND", f"未找到书写者: {writer_id}") from exc
    except PermissionError as exc:
        raise ApiError(409, "WRITER_IN_USE", "当前活动或正在执行任务的书写者无法删除") from exc

    return {"deleted": True}
