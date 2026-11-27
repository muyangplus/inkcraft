"""Document upload, quick plain-text creation, listing, block inspection, and page image routes."""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
from typing import Any
import uuid

from fastapi import APIRouter, File, Form, Path as PathParam, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from handwrite.api.schemas import (
    ApplyImageStyleRequest,
    CommitImportRequest,
    CreateTextDocumentRequest,
    PatchDocumentBlockRequest,
    RenameDocumentRequest,
    UpdateDocumentBlocksRequest,
    UpdateDocumentMarkdownRequest,
)
from handwrite.api.state import ApiError, AppContext
from handwrite.docparse.docir import DocBlock, DocLine, DocPageInfo, DocIR, TableData

router = APIRouter()

ALLOWED_EXTENSIONS = {".docx", ".pdf", ".txt", ".md"}
MAX_UPLOAD_BYTES = 100 * 1024 * 1024


@router.get("/documents")
async def list_documents(request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    rows = ctx.db.list_documents()
    items = []
    for row in rows:
        meta = row.get("meta") or {}
        items.append(
            {
                "doc_id": row["doc_id"],
                "filename": row["filename"],
                "file_type": row["file_type"],
                "page_count": row["page_count"],
                "status": row["status"],
                "is_builtin": row["doc_id"] == "doc_demo",
                "source": meta.get(
                    "source",
                    {
                        "type": row["file_type"],
                        "filename": row["filename"],
                        "sha256": row["sha256"],
                        "parser": "builtin",
                    },
                ),
                "pages": meta.get("pages", []),
                "created_at": row["created_at"],
            }
        )
    return {"documents": items}


@router.post("/documents", status_code=202)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    mode_hint: str | None = Form(default=None),
) -> JSONResponse:
    ctx: AppContext = request.app.state.ctx
    orig_name = Path(file.filename or "document.docx").name
    ext = Path(orig_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ApiError(
            400,
            "UNSUPPORTED_FORMAT",
            f"不支持的文档格式 '{ext}'，仅支持 .docx / .pdf / .txt / .md",
        )

    data = await file.read()
    if not data:
        raise ApiError(400, "EMPTY_FILE", "上传的文档内容为空")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ApiError(413, "FILE_TOO_LARGE", "上传的文档超过 100MB 限制")

    sha256 = hashlib.sha256(data).hexdigest()
    doc_id = f"doc_{uuid.uuid4().hex[:10]}"
    out_dir = ctx.doc_dir(doc_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    src_path = out_dir / f"source{ext}"
    src_path.write_bytes(data)

    file_type = "text" if ext in (".txt", ".md") else ext.lstrip(".")
    ctx.db.upsert_document(
        doc_id=doc_id,
        filename=orig_name,
        file_type=file_type,
        sha256=sha256,
        page_count=0,
        status="parsing",
        meta={
            "source": {
                "type": file_type,
                "filename": orig_name,
                "sha256": sha256,
                "parser": "pending",
            },
            "pages": [],
        },
    )

    def _run_parse(_task_id: str, report) -> dict[str, Any]:
        from handwrite.docparse.service import parse_document

        def _cb(stage: str, pct: float, page: int, page_count: int, msg: str) -> None:
            norm_pct = pct * 100.0 if 0.0 <= pct <= 1.0 else pct
            report(stage, norm_pct, msg, page, page_count)

        try:
            doc = parse_document(
                src_path,
                doc_id=doc_id,
                out_dir=out_dir,
                mode_hint=mode_hint,
                progress_cb=_cb,
            )
            # Preserve user-facing original filename in DocSource
            doc.source.filename = orig_name
            ctx.save_docir(doc, status="ready")
            return {
                "doc_id": doc.doc_id,
                "page_count": len(doc.pages),
                "status": "ready",
            }
        except Exception:
            ctx.db.upsert_document(
                doc_id=doc_id,
                filename=orig_name,
                file_type=file_type,
                sha256=sha256,
                page_count=0,
                status="failed",
            )
            raise

    task_id = ctx.tasks.submit(
        "parse",
        _run_parse,
        initial_stage="queued",
        initial_message=f"正在解析文档 {orig_name}",
    )
    return JSONResponse(status_code=202, content={"doc_id": doc_id, "task_id": task_id})


@router.post("/documents/text", status_code=201)
async def create_text_document(
    body: CreateTextDocumentRequest,
    request: Request,
) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    if not body.text.strip():
        raise ApiError(400, "EMPTY_TEXT", "文本内容不能为空")

    from handwrite.docparse.service import parse_plain_text

    doc_id = f"doc_{uuid.uuid4().hex[:10]}"
    doc = parse_plain_text(body.title or "手写文稿", body.text, doc_id)
    ctx.save_docir(doc, status="ready")
    return {
        "doc_id": doc.doc_id,
        "source": doc.source.model_dump(),
        "page_count": len(doc.pages),
        "pages": [
            {
                "page_index": p.page_index,
                "width_mm": p.width_mm,
                "height_mm": p.height_mm,
            }
            for p in doc.pages
        ],
        "status": "ready",
    }


@router.post("/documents/preview")
async def preview_document(
    request: Request,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Quick pre-parse scan returning page thumbnails & auto-detected split sections."""
    from handwrite.docparse.preview import create_import_preview

    ctx: AppContext = request.app.state.ctx
    orig_name = Path(file.filename or "document.pdf").name
    ext = Path(orig_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ApiError(
            400,
            "UNSUPPORTED_FORMAT",
            f"不支持的文档格式 '{ext}'，仅支持 .docx / .pdf / .txt / .md",
        )
    data = await file.read()
    if not data:
        raise ApiError(400, "EMPTY_FILE", "上传的文档内容为空")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ApiError(413, "FILE_TOO_LARGE", "上传的文档超过 100MB 限制")

    previews_root = ctx.settings.cache_dir / "previews"
    try:
        return create_import_preview(data, orig_name, previews_root)
    except Exception as exc:
        raise ApiError(400, "PREVIEW_FAILED", f"预解析预览失败: {exc}") from exc


@router.get("/documents/preview/{preview_id}/pages/{page_index}/thumb")
async def get_preview_thumb(
    preview_id: str,
    request: Request,
    page_index: int = PathParam(..., ge=0),
    dpi: int = Query(default=96, ge=72, le=200),
) -> FileResponse:
    from handwrite.docparse.preview import ensure_preview_thumb

    ctx: AppContext = request.app.state.ctx
    previews_root = ctx.settings.cache_dir / "previews"
    try:
        thumb_path = ensure_preview_thumb(previews_root, preview_id, page_index, dpi=dpi)
    except FileNotFoundError as exc:
        raise ApiError(404, "PREVIEW_NOT_FOUND", str(exc)) from exc
    except IndexError as exc:
        raise ApiError(400, "INVALID_PAGE_INDEX", str(exc)) from exc
    except ValueError as exc:
        raise ApiError(400, "INVALID_PREVIEW", str(exc)) from exc
    return FileResponse(thumb_path, media_type="image/jpeg")


@router.post("/documents/preview/{preview_id}/commit", status_code=202)
async def commit_preview(
    preview_id: str,
    body: CommitImportRequest,
    request: Request,
) -> JSONResponse:
    from handwrite.docparse.preview import commit_preview_projects, load_preview_manifest

    ctx: AppContext = request.app.state.ctx
    previews_root = ctx.settings.cache_dir / "previews"
    try:
        pdir, manifest = load_preview_manifest(previews_root, preview_id)
        created_docs, runner = commit_preview_projects(
            pdir=pdir,
            manifest=manifest,
            projects=body.projects,
            mode_hint=body.mode_hint,
            ctx=ctx,
        )
    except FileNotFoundError as exc:
        raise ApiError(404, "PREVIEW_NOT_FOUND", str(exc)) from exc
    except ValueError as exc:
        raise ApiError(400, "INVALID_COMMIT_SPEC", str(exc)) from exc

    task_id = ctx.tasks.submit(
        "parse",
        runner,
        initial_stage="queued",
        initial_message=f"正在导入 {len(created_docs)} 个项目...",
    )
    return JSONResponse(status_code=202, content={"task_id": task_id, "documents": created_docs})


@router.delete("/documents/preview/{preview_id}")
async def cancel_preview(preview_id: str, request: Request) -> dict[str, Any]:
    from handwrite.docparse.preview import _resolve_preview_dir

    ctx: AppContext = request.app.state.ctx
    previews_root = ctx.settings.cache_dir / "previews"
    try:
        pdir = _resolve_preview_dir(previews_root, preview_id)
    except ValueError as exc:
        raise ApiError(400, "INVALID_PREVIEW", str(exc)) from exc
    if pdir.is_dir():
        shutil.rmtree(pdir, ignore_errors=True)
    return {"deleted": True, "preview_id": preview_id}


@router.patch("/documents/{doc_id}")
async def rename_document(
    doc_id: str,
    body: RenameDocumentRequest,
    request: Request,
) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    new_name = body.filename.strip()
    if not new_name:
        raise ApiError(400, "EMPTY_NAME", "文档名称不能为空")
    ok = ctx.db.rename_document(doc_id, new_name)
    if not ok:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", f"文档不存在: {doc_id}")
    doc = ctx.load_docir(doc_id)
    if doc is not None:
        doc.source.filename = new_name
        ctx.save_docir(doc, status="ready")
    return {"doc_id": doc_id, "filename": new_name}


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, request: Request) -> dict[str, Any]:
    if doc_id == "doc_demo":
        raise ApiError(400, "BUILTIN_PROTECTED", "内置示例文稿不可删除")
    ctx: AppContext = request.app.state.ctx
    deleted = ctx.db.delete_document(doc_id)
    ddir = ctx.doc_dir(doc_id)
    if ddir.is_dir():
        shutil.rmtree(ddir, ignore_errors=True)
    if not deleted and not ddir.exists():
        raise ApiError(404, "DOCUMENT_NOT_FOUND", f"文档不存在: {doc_id}")
    return {"deleted": True, "doc_id": doc_id}


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str, request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    row = ctx.db.get_document(doc_id)
    doc = ctx.load_docir(doc_id)
    if row is None and doc is None:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", f"文档不存在: {doc_id}")

    if doc is not None:
        pages_out = []
        for p in doc.pages:
            entry: dict[str, Any] = {
                "page_index": p.page_index,
                "width_mm": p.width_mm,
                "height_mm": p.height_mm,
            }
            if p.image is not None:
                entry["image"] = p.image
            pages_out.append(entry)
        return {
            "doc_id": doc.doc_id,
            "is_builtin": doc.doc_id == "doc_demo",
            "source": doc.source.model_dump(),
            "page_count": len(doc.pages),
            "pages": pages_out,
            "status": row["status"] if row else "ready",
        }

    assert row is not None
    meta = row.get("meta") or {}
    return {
        "doc_id": row["doc_id"],
        "is_builtin": row["doc_id"] == "doc_demo",
        "source": meta.get(
            "source",
            {
                "type": row["file_type"],
                "filename": row["filename"],
                "sha256": row["sha256"],
                "parser": "pending",
            },
        ),
        "page_count": row["page_count"],
        "pages": meta.get("pages", []),
        "status": row["status"],
    }


@router.get("/documents/{doc_id}/blocks")
async def get_document_blocks(
    doc_id: str,
    request: Request,
    page_index: int | None = Query(default=None, ge=0),
) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    doc = ctx.load_docir(doc_id)
    if doc is None:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", f"文档不存在或尚未解析完成: {doc_id}")

    blocks = doc.blocks
    if page_index is not None:
        blocks = [b for b in blocks if b.page_index == page_index]

    return {
        "doc_id": doc.doc_id,
        "blocks": [b.model_dump() for b in blocks],
    }


@router.get("/documents/{doc_id}/pages/{page_index}/image")
async def get_document_page_image(
    doc_id: str,
    request: Request,
    page_index: int = PathParam(..., ge=0),
) -> FileResponse:
    ctx: AppContext = request.app.state.ctx
    pages_dir = (ctx.doc_dir(doc_id) / "pages").resolve()
    img_path = (pages_dir / f"{page_index}.png").resolve()
    if not img_path.is_relative_to(pages_dir):
        raise ApiError(400, "INVALID_PAGE_INDEX", f"非法页码: {page_index}")
    if not img_path.is_file():
        raise ApiError(
            404,
            "PAGE_IMAGE_NOT_FOUND",
            f"文档 '{doc_id}' 第 {page_index + 1} 页无套打底图",
        )
    return FileResponse(img_path, media_type="image/png")


@router.get("/documents/{doc_id}/assets/{asset_name}")
async def get_document_asset(
    doc_id: str,
    asset_name: str,
    request: Request,
) -> FileResponse:
    from handwrite.docparse.markdown_codec import resolve_safe_asset_path

    ctx: AppContext = request.app.state.ctx
    assets_dir = ctx.doc_dir(doc_id) / "assets"
    safe_path = resolve_safe_asset_path(asset_name, assets_dir)
    if safe_path is None:
        raise ApiError(404, "ASSET_NOT_FOUND", f"未找到文档资源: {asset_name}")
    ext = safe_path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }.get(ext, "application/octet-stream")
    return FileResponse(safe_path, media_type=mime)


@router.post("/documents/{doc_id}/assets")
async def upload_document_asset(
    doc_id: str,
    request: Request,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    doc = ctx.load_docir(doc_id)
    if doc is None:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", f"文档不存在或尚未解析完成: {doc_id}")

    orig = Path(file.filename or "image.png").name
    ext = Path(orig).suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
        raise ApiError(400, "UNSUPPORTED_IMAGE", f"不支持的图片格式 '{ext}'")
    data = await file.read()
    if not data:
        raise ApiError(400, "EMPTY_FILE", "图片内容为空")
    if len(data) > 20 * 1024 * 1024:
        raise ApiError(413, "FILE_TOO_LARGE", "图片超过 20MB 限制")

    assets_dir = ctx.doc_dir(doc_id) / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    asset_name = f"user_{uuid.uuid4().hex[:8]}{ext}"
    out_path = (assets_dir / asset_name).resolve()
    out_path.write_bytes(data)

    w_mm: float = 65.0
    h_mm: float = 45.0
    try:
        from PIL import Image

        with Image.open(out_path) as im:
            px_w, px_h = im.size
            if px_w > 0 and px_h > 0:
                w_mm = round(min(150.0, max(25.0, px_w * 25.4 / 150.0)), 1)
                h_mm = round(max(12.0, w_mm * (px_h / px_w)), 1)
    except Exception:
        pass

    return {
        "doc_id": doc_id,
        "asset_name": asset_name,
        "url": f"/api/v1/documents/{doc_id}/assets/{asset_name}",
        "width_mm": w_mm,
        "height_mm": h_mm,
    }


@router.get("/documents/{doc_id}/markdown")
async def get_document_markdown(
    doc_id: str,
    request: Request,
    download: bool = Query(default=False),
) -> Any:
    from handwrite.docparse.markdown_codec import docir_to_markdown

    ctx: AppContext = request.app.state.ctx
    doc = ctx.load_docir(doc_id)
    if doc is None:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", f"文档不存在或尚未解析完成: {doc_id}")
    md = docir_to_markdown(doc)
    if download:
        stem = Path(doc.source.filename or doc_id).stem or doc_id
        return PlainTextResponse(
            content=md,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{stem}.md"'},
        )
    return {
        "doc_id": doc.doc_id,
        "sha256": doc.source.sha256,
        "markdown": md,
    }


@router.put("/documents/{doc_id}/markdown")
async def update_document_markdown(
    doc_id: str,
    body: UpdateDocumentMarkdownRequest,
    request: Request,
) -> dict[str, Any]:
    from handwrite.docparse.markdown_codec import docir_to_markdown, markdown_to_docir

    ctx: AppContext = request.app.state.ctx
    doc = ctx.load_docir(doc_id)
    if doc is None:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", f"文档不存在或尚未解析完成: {doc_id}")

    assets_dir = ctx.doc_dir(doc_id) / "assets"
    updated = markdown_to_docir(body.markdown, doc, assets_dir=assets_dir)
    ctx.save_docir(updated, status="ready")
    return {
        "doc_id": updated.doc_id,
        "sha256": updated.source.sha256,
        "markdown": docir_to_markdown(updated),
        "blocks": [b.model_dump() for b in updated.blocks],
    }


@router.put("/documents/{doc_id}/blocks")
async def replace_document_blocks(
    doc_id: str,
    body: UpdateDocumentBlocksRequest,
    request: Request,
) -> dict[str, Any]:
    from handwrite.docparse.markdown_codec import (
        compute_docir_sha256,
        docir_to_markdown,
        resolve_safe_asset_path,
    )

    ctx: AppContext = request.app.state.ctx
    base = ctx.load_docir(doc_id)
    if base is None:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", f"文档不存在或尚未解析完成: {doc_id}")

    assets_dir = ctx.doc_dir(doc_id) / "assets"
    prev_by_id = {b.block_id: b for b in base.blocks}
    new_blocks: list[DocBlock] = []

    for idx, raw_item in enumerate(body.blocks):
        try:
            blk = DocBlock.model_validate(raw_item)
        except Exception as exc:
            raise ApiError(400, "INVALID_BLOCK", f"第 {idx + 1} 个块格式无效: {exc}") from exc

        blk.reading_order = idx
        prev = prev_by_id.get(blk.block_id)

        # Constrain image/chart asset paths strictly inside this document's assets directory
        cand_name = blk.asset_name or (Path(blk.image_path).name if blk.image_path else None)
        safe_path = resolve_safe_asset_path(cand_name, assets_dir)
        if safe_path is None and prev is not None:
            safe_path = resolve_safe_asset_path(prev.asset_name, assets_dir, prev.image_path)
        if safe_path is not None:
            blk.image_path = str(safe_path)
            blk.asset_name = safe_path.name
            if blk.chart is not None and blk.chart.chart_type == "raster":
                blk.chart.image_path = str(safe_path)
        else:
            blk.image_path = None
            blk.asset_name = None
            if blk.chart is not None and blk.chart.image_path:
                blk.chart.image_path = None

        if blk.inlines and not blk.lines:
            blk.lines = [DocLine(bbox_mm=blk.bbox_mm, inlines=blk.inlines)]

        new_blocks.append(blk)

    updated = DocIR(
        doc_id=base.doc_id,
        source=base.source.model_copy(deep=True),
        pages=[p.model_copy(deep=True) for p in base.pages] or [DocPageInfo(page_index=0)],
        blocks=new_blocks,
    )
    updated.source.sha256 = compute_docir_sha256(updated)
    ctx.save_docir(updated, status="ready")
    return {
        "doc_id": updated.doc_id,
        "sha256": updated.source.sha256,
        "markdown": docir_to_markdown(updated),
        "blocks": [b.model_dump() for b in updated.blocks],
    }


@router.patch("/documents/{doc_id}/blocks/{block_id}")
async def patch_document_block(
    doc_id: str,
    block_id: str,
    body: PatchDocumentBlockRequest,
    request: Request,
) -> dict[str, Any]:
    from handwrite.docparse.markdown_codec import compute_docir_sha256, docir_to_markdown

    ctx: AppContext = request.app.state.ctx
    doc = ctx.load_docir(doc_id)
    if doc is None:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", f"文档不存在或尚未解析完成: {doc_id}")

    target: DocBlock | None = None
    for b in doc.blocks:
        if b.block_id == block_id:
            target = b
            break
    if target is None:
        raise ApiError(404, "BLOCK_NOT_FOUND", f"未找到文档块: {block_id}")

    if body.type is not None:
        allowed_types = {
            "heading", "paragraph", "list_item", "formula_block",
            "table", "figure", "chart", "caption", "header", "footer", "page_number", "discarded",
        }
        if body.type not in allowed_types:
            raise ApiError(400, "INVALID_BLOCK_TYPE", f"不支持的块类型: {body.type}")
        target.type = body.type  # type: ignore[assignment]
    if body.level is not None:
        target.level = body.level
    if body.page_index is not None:
        target.page_index = body.page_index
    if body.inlines is not None:
        validated = DocBlock.model_validate({"block_id": target.block_id, "type": target.type, "inlines": body.inlines})
        target.inlines = validated.inlines
        target.lines = [DocLine(bbox_mm=target.bbox_mm, inlines=validated.inlines)]
    if body.latex is not None:
        target.latex = body.latex
    if body.table is not None:
        target.table = TableData.model_validate(body.table)
    if target.table is not None:
        if body.table_border_style is not None:
            target.table.border_style = (
                None if body.table_border_style == "inherit" else body.table_border_style
            )
        if body.table_width_ratio is not None:
            target.table.width_ratio = round(float(body.table_width_ratio), 3)
        if body.table_align is not None:
            target.table.align = body.table_align
    if body.alt_text is not None:
        target.alt_text = body.alt_text
    if body.image_render_mode is not None:
        target.image_render_mode = body.image_render_mode
    if body.placement is not None:
        target.placement = body.placement
        if body.placement == "float" and target.float_box_mm is None and body.float_box_mm is None:
            w = float(target.image_width_mm or 70.0)
            h = float(target.image_height_mm or 48.0)
            target.float_box_mm = [30.0, 40.0, round(30.0 + w, 2), round(40.0 + h, 2)]
    if body.image_align is not None:
        target.image_align = body.image_align
    if body.image_width_mm is not None:
        target.image_width_mm = round(float(body.image_width_mm), 2)
    if body.image_height_mm is not None:
        target.image_height_mm = round(float(body.image_height_mm), 2)
    if body.float_box_mm is not None:
        if len(body.float_box_mm) != 4:
            raise ApiError(400, "INVALID_BBOX", "float_box_mm 必须包含 4 个坐标值")
        fx0, fy0, fx1, fy1 = [round(float(v), 2) for v in body.float_box_mm]
        if fx1 < fx0 + 6.0 or fy1 < fy0 + 6.0:
            raise ApiError(400, "INVALID_BBOX", "浮动边框尺寸至少为 6×6 mm")
        target.float_box_mm = [fx0, fy0, fx1, fy1]
        target.image_width_mm = round(fx1 - fx0, 2)
        target.image_height_mm = round(fy1 - fy0, 2)

    doc.source.sha256 = compute_docir_sha256(doc)
    ctx.save_docir(doc, status="ready")
    return {
        "doc_id": doc.doc_id,
        "sha256": doc.source.sha256,
        "block": target.model_dump(),
        "markdown": docir_to_markdown(doc),
    }


@router.post("/documents/{doc_id}/blocks/apply-image-style")
async def apply_global_image_style(
    doc_id: str,
    body: ApplyImageStyleRequest,
    request: Request,
) -> dict[str, Any]:
    from handwrite.docparse.markdown_codec import compute_docir_sha256, docir_to_markdown

    ctx: AppContext = request.app.state.ctx
    doc = ctx.load_docir(doc_id)
    if doc is None:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", f"文档不存在或尚未解析完成: {doc_id}")

    count = 0
    for blk in doc.blocks:
        if blk.type in {"figure", "chart"}:
            blk.image_render_mode = body.image_render_mode
            count += 1

    doc.source.sha256 = compute_docir_sha256(doc)
    ctx.save_docir(doc, status="ready")
    return {
        "doc_id": doc.doc_id,
        "sha256": doc.source.sha256,
        "updated_count": count,
        "image_render_mode": body.image_render_mode,
        "blocks": [b.model_dump() for b in doc.blocks],
        "markdown": docir_to_markdown(doc),
    }


@router.post("/documents/{doc_id}/blocks/{block_id}/recognize-formula")
async def re_recognize_formula_block(
    doc_id: str,
    block_id: str,
    request: Request,
) -> dict[str, Any]:
    from handwrite.docparse.markdown_codec import (
        compute_docir_sha256,
        docir_to_markdown,
        resolve_safe_asset_path,
    )

    ctx: AppContext = request.app.state.ctx
    doc = ctx.load_docir(doc_id)
    if doc is None:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", f"文档不存在或尚未解析完成: {doc_id}")

    assets_dir = ctx.doc_dir(doc_id) / "assets"
    target = next((b for b in doc.blocks if b.block_id == block_id), None)
    if target is None:
        raise ApiError(404, "BLOCK_NOT_FOUND", f"未找到文档块: {block_id}")

    img_path = resolve_safe_asset_path(target.asset_name, assets_dir, target.image_path)
    if img_path is None:
        raise ApiError(400, "NO_FORMULA_IMAGE", "该公式块没有关联的原始裁剪图像可供重新识别")

    from handwrite.docparse.formula_ocr import recognize_formula_image

    latex, src = recognize_formula_image(img_path)
    target.type = "formula_block"
    target.latex = latex
    target.ocr_source = src
    doc.source.sha256 = compute_docir_sha256(doc)
    ctx.save_docir(doc, status="ready")
    return {
        "doc_id": doc.doc_id,
        "sha256": doc.source.sha256,
        "block": target.model_dump(),
        "markdown": docir_to_markdown(doc),
    }
