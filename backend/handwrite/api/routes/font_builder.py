"""Local (GPU/CPU) and Google Colab Cloud .hwfont builder API routes.

Endpoints (mounted under `/api/v1`):
  - `GET  /font-builder/capabilities`
  - `POST /font-builder/sheets`
  - `GET  /font-builder/sheets/{sheet_id}/pdf`
  - `GET  /font-builder/sheets/{sheet_id}/manifest`
  - `POST /font-builder/build` (202 Accepted background `font_import` task)
  - `POST /font-builder/colab-bundle` (`application/zip`)
"""

from __future__ import annotations

from pathlib import Path
import re
import sys
from typing import Any, Literal
import uuid

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from handwrite.api.state import ApiError

router = APIRouter()


def _ensure_hwbuilder_importable(root_dir: Path) -> None:
    """Ensure `colab_builder` is on `sys.path` even if not editable-installed."""
    cb_dir = str((root_dir / "colab_builder").resolve())
    if cb_dir not in sys.path and Path(cb_dir).is_dir():
        sys.path.insert(0, cb_dir)


def _get_services(request: Request) -> tuple[Any, Any, Any]:
    """Return `(writers, tasks, settings)` from `app.state.ctx` or direct attributes."""
    state = request.app.state
    ctx = getattr(state, "ctx", None)
    if ctx is not None:
        return ctx.writers, ctx.tasks, ctx.settings
    return state.writers, state.tasks, state.settings


def _sheets_root(settings: Any) -> Path:
    d = Path(settings.DATA_DIR) / "font_builder" / "sheets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _builds_root(settings: Any) -> Path:
    d = Path(settings.DATA_DIR) / "font_builder" / "builds"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sanitize_id(raw: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", raw):
        raise ApiError(400, "INVALID_SHEET_ID", f"非法 sheet_id: {raw}")
    return raw


def _slugify_filename(writer_name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff_-]+", "_", writer_name.strip()).strip("_")
    return cleaned[:40] or f"writer_{uuid.uuid4().hex[:6]}"


def _parse_style_tags(raw: str) -> list[str]:
    if not raw:
        return []
    return [t.strip() for t in raw.replace("，", ",").split(",") if t.strip()]


class GenerateSheetsRequest(BaseModel):
    preset: Literal["quick", "standard", "custom"] = "standard"
    custom_chars: str | None = Field(default=None)
    grid_color: Literal["cyan", "red"] = "cyan"
    writer_name: str = Field(default="my_writer")


@router.get("/font-builder/capabilities")
async def get_font_builder_capabilities(request: Request) -> dict[str, Any]:
    _writers, _tasks, settings = _get_services(request)
    _ensure_hwbuilder_importable(Path(settings.ROOT_DIR))
    from hwbuilder.local_runner import probe_capabilities

    return probe_capabilities()


@router.post("/font-builder/sheets")
async def create_collection_sheets(
    body: GenerateSheetsRequest,
    request: Request,
) -> dict[str, Any]:
    _writers, _tasks, settings = _get_services(request)
    _ensure_hwbuilder_importable(Path(settings.ROOT_DIR))
    from hwbuilder.local_runner import preset_charset
    from hwbuilder.sheet_gen import SheetConfig, generate_collection_sheets

    try:
        chars = preset_charset(body.preset, body.custom_chars)
    except ValueError as exc:
        raise ApiError(422, "INVALID_CHARSET", str(exc)) from exc

    sheet_id = f"sht_{uuid.uuid4().hex[:10]}"
    out_dir = _sheets_root(settings) / sheet_id
    cfg = SheetConfig(
        writer_name=body.writer_name.strip() or "my_writer",
        rows=8 if body.preset == "quick" else 12,
        cols=8 if body.preset == "quick" else 10,
        grid_color=body.grid_color,
        preview_dpi=150,
    )
    manifest = generate_collection_sheets(
        chars=chars,
        out_dir=out_dir,
        config=cfg,
        render_previews=True,
    )
    char_count = sum(len(p.cells) for p in manifest.pages)
    return {
        "sheet_id": sheet_id,
        "page_count": len(manifest.pages),
        "char_count": char_count,
        "pdf_url": f"/api/v1/font-builder/sheets/{sheet_id}/pdf",
        "manifest_url": f"/api/v1/font-builder/sheets/{sheet_id}/manifest",
    }


@router.get("/font-builder/sheets/{sheet_id}/pdf")
async def download_sheet_pdf(sheet_id: str, request: Request) -> FileResponse:
    _writers, _tasks, settings = _get_services(request)
    sid = _sanitize_id(sheet_id)
    pdf_path = _sheets_root(settings) / sid / "collection_sheets.pdf"
    if not pdf_path.is_file():
        raise ApiError(404, "SHEET_NOT_FOUND", f"未找到采集表 PDF: {sid}")
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=f"handwrite_sheet_{sid}.pdf",
    )


@router.get("/font-builder/sheets/{sheet_id}/manifest")
async def download_sheet_manifest(sheet_id: str, request: Request) -> FileResponse:
    _writers, _tasks, settings = _get_services(request)
    sid = _sanitize_id(sheet_id)
    manifest_path = _sheets_root(settings) / sid / "manifest.json"
    if not manifest_path.is_file():
        raise ApiError(404, "SHEET_NOT_FOUND", f"未找到采集表 manifest: {sid}")
    return FileResponse(
        path=str(manifest_path),
        media_type="application/json",
        filename=f"manifest_{sid}.json",
    )


@router.post("/font-builder/build", status_code=202)
async def start_local_font_build(
    request: Request,
    files: list[UploadFile] | None = File(default=None),
    manifest: UploadFile | None = File(default=None),
    sheet_id: str | None = Form(default=None),
    writer_name: str = Form(...),
    writer_alias: str = Form(default=""),
    style_tags: str = Form(default=""),
    engine: Literal["auto", "local_gpu", "local_cpu"] = Form(default="auto"),
    variants_per_char: int = Form(default=3, ge=1, le=8),
    target_preset: Literal["quick", "standard", "scanned_only"] = Form(default="standard"),
    demo_synthetic: bool = Form(default=False),
) -> dict[str, Any]:
    writers, tasks, settings = _get_services(request)
    _ensure_hwbuilder_importable(Path(settings.ROOT_DIR))
    from hwbuilder.local_runner import LocalBuildConfig, resolve_engine, run_local_font_build

    name_clean = writer_name.strip()
    if not name_clean:
        raise ApiError(422, "INVALID_WRITER_NAME", "writer_name 不能为空")

    # Persist all uploaded files synchronously before returning 202
    build_id = f"bld_{uuid.uuid4().hex[:10]}"
    build_dir = _builds_root(settings) / build_id
    scans_dir = build_dir / "scans"
    scans_dir.mkdir(parents=True, exist_ok=True)

    saved_scans: list[Path] = []
    max_scan_bytes = 100 * 1024 * 1024
    if files:
        for idx, up in enumerate(files):
            raw = await up.read()
            if not raw:
                continue
            if len(raw) > max_scan_bytes:
                raise ApiError(413, "FILE_TOO_LARGE", "上传扫描图片超过 100MB 限制")
            raw_suffix = Path(up.filename or f"scan_{idx}.png").suffix.lower()
            suffix = re.sub(r"[^.a-zA-Z0-9]", "", raw_suffix)[:10] or ".png"
            dst = scans_dir / f"scan_{idx:03d}{suffix}"
            dst.write_bytes(raw)
            saved_scans.append(dst)

    if not saved_scans and not demo_synthetic:
        raise ApiError(
            422,
            "NO_SCAN_FILES",
            "请上传至少一张扫描图片，或勾选 demo_synthetic=true 使用合成样例体验本机构建。",
        )

    manifest_path: Path | None = None
    if manifest is not None:
        m_bytes = await manifest.read()
        if m_bytes:
            manifest_path = build_dir / "manifest.json"
            manifest_path.write_bytes(m_bytes)
    elif sheet_id:
        sid = _sanitize_id(sheet_id)
        cand = _sheets_root(settings) / sid / "manifest.json"
        if not cand.is_file():
            raise ApiError(404, "SHEET_NOT_FOUND", f"未找到采集表 manifest: {sid}")
        manifest_path = cand

    engine_selected = resolve_engine(engine)
    tags = _parse_style_tags(style_tags)

    build_cfg = LocalBuildConfig(
        writer_name=name_clean,
        writer_alias=writer_alias.strip(),
        style_tags=tags,
        engine=engine_selected,
        variants_per_char=variants_per_char,
        target_preset=target_preset,
    )

    def _run_task(_tid: str, report: Any) -> dict[str, Any]:
        out_hwfont = build_dir / f"{_slugify_filename(name_clean)}.hwfont"

        def _stage_cb(stage: str, pct: float, msg: str) -> None:
            report(stage, pct, msg, None, None)

        res = run_local_font_build(
            out_hwfont=out_hwfont,
            config=build_cfg,
            scan_paths=saved_scans,
            manifest_path=manifest_path,
            demo_synthetic=demo_synthetic,
            work_dir=build_dir / "work",
            progress=_stage_cb,
        )
        # Import into WriterRegistry and set as active writer (broadcasts writer.changed)
        meta = writers.import_file(res.out_hwfont, res.out_hwfont.name)
        writers.set_active(meta.writer_id)
        return {
            "writer_id": meta.writer_id,
            "writer": meta.model_dump(),
            "glyph_count": meta.glyph_count,
            "variant_count": meta.variant_count,
            "engine_used": res.engine_used,
        }

    task_id = tasks.submit(
        "font_import",
        _run_task,
        initial_stage="segment",
        initial_message=f"正在本机（{engine_selected}）构建笔迹：{name_clean}",
    )
    return {
        "task_id": task_id,
        "engine_selected": engine_selected,
    }


@router.post("/font-builder/colab-bundle")
async def export_colab_bundle(
    request: Request,
    files: list[UploadFile] | None = File(default=None),
    manifest: UploadFile | None = File(default=None),
    sheet_id: str | None = Form(default=None),
    writer_name: str = Form(default="my_writer"),
    writer_alias: str = Form(default=""),
    style_tags: str = Form(default=""),
    variants_per_char: int = Form(default=4, ge=1, le=8),
) -> Response:
    _writers, _tasks, settings = _get_services(request)
    root_dir = Path(settings.ROOT_DIR)
    _ensure_hwbuilder_importable(root_dir)
    from hwbuilder.local_runner import package_colab_bundle

    manifest_bytes: bytes | None = None
    sheet_pdf_bytes: bytes | None = None

    if manifest is not None:
        raw_m = await manifest.read()
        if raw_m:
            manifest_bytes = raw_m
    elif sheet_id:
        sid = _sanitize_id(sheet_id)
        sdir = _sheets_root(settings) / sid
        m_file = sdir / "manifest.json"
        if m_file.is_file():
            manifest_bytes = m_file.read_bytes()
        pdf_file = sdir / "collection_sheets.pdf"
        if pdf_file.is_file():
            sheet_pdf_bytes = pdf_file.read_bytes()

    scan_files: list[tuple[str, bytes]] = []
    if files:
        for idx, up in enumerate(files):
            raw = await up.read()
            if raw:
                scan_files.append((up.filename or f"scan_{idx:03d}.png", raw))

    zip_bytes = package_colab_bundle(
        repo_root=root_dir,
        writer_name=writer_name.strip() or "my_writer",
        writer_alias=writer_alias.strip(),
        style_tags=_parse_style_tags(style_tags),
        variants_per_char=variants_per_char,
        manifest_bytes=manifest_bytes,
        sheet_pdf_bytes=sheet_pdf_bytes,
        scan_files=scan_files,
    )
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="handwrite_colab_bundle.zip"',
        },
    )
