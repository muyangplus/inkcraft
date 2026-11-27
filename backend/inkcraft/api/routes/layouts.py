"""Layout composition, default config, JSON/Float32 path streaming, and G-code download routes."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal
import uuid

from fastapi import APIRouter, Path as PathParam, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from inkcraft.api.schemas import (
    ChartConfig,
    CreateLayoutRequest,
    FormulaConfig,
    LayoutConfig,
    LayoutPreset,
    MarginsMM,
    MathPreviewRequest,
    OverlayConfig,
    PageConfig,
    PageRuleOverride,
    PageRulesConfig,
    PerturbConfig,
    RuledConfig,
    TextConfig,
)
from inkcraft.api.state import ApiError, AppContext

router = APIRouter()


def _builtin_presets() -> list[LayoutPreset]:
    return [
        LayoutPreset(
            preset_id="standard_a4",
            name="标准 A4 作业 / 报告",
            category="homework",
            description="均衡自然的 A4 竖版手写参数，适合日常作业、实验报告与课程论文",
            tags=["A4", "6.0mm", "自然微扰"],
            config=LayoutConfig(preset_id="standard_a4"),
        ),
        LayoutPreset(
            preset_id="first_a_rest_b",
            name="首页抬头 A + 续页横格 B",
            category="letter",
            description="第一页自动应用抬头底稿 A（顶距 56mm 避让表头），第 2 页起自动切换标准 9mm 横格底稿 B",
            tags=["首页 A", "续页 B", "9mm 贴线"],
            config=LayoutConfig(
                preset_id="first_a_rest_b",
                text=TextConfig(
                    font_size_mm=5.8,
                    line_spacing=1.55,
                    ruled=RuledConfig(style="lines", pitch_mm=9.0, draw=False),
                ),
                page_rules=PageRulesConfig(
                    strategy="first_and_rest",
                    first_page=PageRuleOverride(
                        label="首页方案 A · 抬头",
                        background_id="bg_letterhead_a",
                        background_opacity=0.82,
                        margins_mm=MarginsMM(top=56.0, right=20.0, bottom=22.0, left=20.0),
                        ruled=RuledConfig(style="lines", pitch_mm=9.0, draw=False),
                    ),
                    rest_pages=PageRuleOverride(
                        label="续页方案 B · 横格",
                        background_id="bg_lined_9mm_b",
                        background_opacity=0.78,
                        margins_mm=MarginsMM(top=22.0, right=20.0, bottom=22.0, left=20.0),
                        ruled=RuledConfig(style="lines", pitch_mm=9.0, draw=False),
                    ),
                ),
            ),
        ),
        LayoutPreset(
            preset_id="lined_8mm",
            name="8mm 横格本精准贴线",
            category="notes",
            description="基线自动吸附 8mm 横格，适配常规横格笔记本与信纸底稿",
            tags=["8mm 横格", "贴线对齐", "笔记"],
            config=LayoutConfig(
                preset_id="lined_8mm",
                page=PageConfig(
                    size="A4",
                    width_mm=210.0,
                    height_mm=297.0,
                    margins_mm=MarginsMM(top=24.0, right=18.0, bottom=20.0, left=24.0),
                ),
                text=TextConfig(
                    font_size_mm=5.4,
                    line_spacing=1.48,
                    ruled=RuledConfig(style="lines", pitch_mm=8.0, draw=False),
                ),
                page_rules=PageRulesConfig(
                    strategy="uniform",
                    uniform=PageRuleOverride(
                        label="8mm 横格底稿",
                        background_id="bg_lined_8mm",
                        background_opacity=0.80,
                    ),
                ),
            ),
        ),
        LayoutPreset(
            preset_id="composition_grid",
            name="传统 9mm 作文方格纸",
            category="homework",
            description="逐字网格对齐，较低倾角与缩放抖动，再现工整方格稿纸观感",
            tags=["方格稿纸", "9mm 网格", "工整"],
            config=LayoutConfig(
                preset_id="composition_grid",
                page=PageConfig(
                    size="A4",
                    width_mm=210.0,
                    height_mm=297.0,
                    margins_mm=MarginsMM(top=24.0, right=18.0, bottom=22.0, left=18.0),
                ),
                text=TextConfig(
                    font_size_mm=5.8,
                    line_spacing=1.55,
                    ruled=RuledConfig(style="grid", pitch_mm=9.0, draw=False),
                ),
                perturb=PerturbConfig(
                    seed=42,
                    neatness=0.92,
                    scale_jitter=0.05,
                    slant_deg=1.5,
                    baseline_wave_amp_mm=0.22,
                    rotation_jitter_deg=0.8,
                ),
                page_rules=PageRulesConfig(
                    strategy="uniform",
                    uniform=PageRuleOverride(
                        label="9mm 作文稿纸",
                        background_id="bg_composition_grid",
                        background_opacity=0.82,
                    ),
                ),
            ),
        ),
        LayoutPreset(
            preset_id="b5_notes",
            name="B5 课堂手写笔记",
            category="notes",
            description="B5 便携开本、紧凑 5.2mm 字号与丰富的同字异形自然笔迹微扰",
            tags=["B5", "紧凑 5.2mm", "高拟真"],
            config=LayoutConfig(
                preset_id="b5_notes",
                page=PageConfig(
                    size="B5",
                    width_mm=176.0,
                    height_mm=250.0,
                    margins_mm=MarginsMM(top=18.0, right=15.0, bottom=18.0, left=15.0),
                ),
                text=TextConfig(font_size_mm=5.2, line_spacing=1.42, paragraph_spacing_mm=2.2),
                perturb=PerturbConfig(
                    seed=108,
                    neatness=0.48,
                    scale_jitter=0.10,
                    slant_deg=3.2,
                    baseline_wave_amp_mm=0.55,
                    spacing_jitter=0.10,
                    rotation_jitter_deg=1.6,
                    variant_no_repeat_window=4,
                ),
            ),
        ),
        LayoutPreset(
            preset_id="cornell_study",
            name="康奈尔笔记双栏排版",
            category="notes",
            description="左侧自动留白 58mm 线索区，右侧主体按 9mm 横格排版",
            tags=["康奈尔", "左留白", "学习笔记"],
            config=LayoutConfig(
                preset_id="cornell_study",
                page=PageConfig(
                    size="A4",
                    width_mm=210.0,
                    height_mm=297.0,
                    margins_mm=MarginsMM(top=32.0, right=16.0, bottom=42.0, left=58.0),
                ),
                text=TextConfig(
                    font_size_mm=5.5,
                    line_spacing=1.55,
                    first_line_indent_chars=0.0,
                    ruled=RuledConfig(style="lines", pitch_mm=9.0, draw=False),
                ),
                page_rules=PageRulesConfig(
                    strategy="uniform",
                    uniform=PageRuleOverride(
                        label="康奈尔底稿",
                        background_id="bg_cornell",
                        background_opacity=0.85,
                    ),
                ),
            ),
        ),
        LayoutPreset(
            preset_id="overlay_exam",
            name="试卷 / 表格原版套打",
            category="overlay",
            description="严格按原文档坐标套写，自动开启半透明原页底图便于块级微调对位",
            tags=["原版套打", "底图对位", "防越界"],
            config=LayoutConfig(
                preset_id="overlay_exam",
                mode="overlay",
                text=TextConfig(font_size_mm=5.4, line_spacing=1.35),
                formula=FormulaConfig(scale=0.90),
                overlay=OverlayConfig(underlay_opacity=0.45),
            ),
        ),
        LayoutPreset(
            preset_id="fast_draft",
            name="极速草稿 / 机械臂试写",
            category="draft",
            description="稀疏图表排线与更大字号，缩短笔尖落笔与空移时间，适合快速打样校准",
            tags=["快速打样", "大字号", "稀疏排线"],
            config=LayoutConfig(
                preset_id="fast_draft",
                text=TextConfig(font_size_mm=7.2, line_spacing=1.6),
                chart=ChartConfig(hatch_spacing_mm=3.2, hatch_style="parallel", hand_jitter_mm=0.15),
                perturb=PerturbConfig(seed=7, scale_jitter=0.04, slant_deg=1.5, baseline_wave_amp_mm=0.2),
            ),
        ),
    ]


@router.get("/layout/presets")
async def get_layout_presets(
    request: Request,
    include_builtin: bool = Query(default=True),
) -> dict[str, Any]:
    items = [p.model_dump() for p in _builtin_presets()] if include_builtin else []
    ctx: AppContext = request.app.state.ctx
    items.extend(p.model_dump() for p in ctx.presets.list())
    return {"presets": items}


@router.put("/layout/presets/{preset_id}")
async def save_layout_preset(preset_id: str, body: LayoutPreset, request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    preset = body.model_copy(update={"preset_id": preset_id})
    try:
        saved = ctx.presets.save(preset)
    except ValueError as exc:
        raise ApiError(422, "INVALID_PRESET", str(exc)) from exc
    return {"preset": saved.model_dump()}


@router.delete("/layout/presets/{preset_id}")
async def delete_layout_preset(preset_id: str, request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    return {"deleted": ctx.presets.delete(preset_id)}


@router.get("/layout/defaults")
async def get_layout_defaults(
    request: Request,
    doc_id: str | None = Query(default=None),
) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    cfg = LayoutConfig()
    if doc_id:
        doc = ctx.load_docir(doc_id)
        if doc is not None and doc.pages:
            p0 = doc.pages[0]
            if 20.0 <= p0.width_mm <= 1000.0 and 20.0 <= p0.height_mm <= 1000.0:
                cfg.page.width_mm = p0.width_mm
                cfg.page.height_mm = p0.height_mm
                if abs(p0.width_mm - 210.0) < 1.0 and abs(p0.height_mm - 297.0) < 1.0:
                    cfg.page.size = "A4"
                elif abs(p0.width_mm - 148.0) < 1.0 and abs(p0.height_mm - 210.0) < 1.0:
                    cfg.page.size = "A5"
                elif abs(p0.width_mm - 176.0) < 1.0 and abs(p0.height_mm - 250.0) < 1.0:
                    cfg.page.size = "B5"
                elif abs(p0.width_mm - 215.9) < 1.5 and abs(p0.height_mm - 279.4) < 1.5:
                    cfg.page.size = "Letter"
                else:
                    cfg.page.size = "custom"
    return {"config": cfg.model_dump()}


@router.post("/layouts", status_code=202)
async def create_layout(
    body: CreateLayoutRequest,
    request: Request,
) -> JSONResponse:
    ctx: AppContext = request.app.state.ctx
    if not body.doc_id or body.doc_id == "__regions_only__":
        from inkcraft.docparse.docir import DocIR, DocPageInfo, DocSource

        doc = DocIR(
            doc_id="__regions_only__",
            source=DocSource(
                type="text",
                filename="自定义区域与字段",
                sha256="regions_only_v1",
                parser="regions-only",
            ),
            pages=[
                DocPageInfo(
                    page_index=0,
                    width_mm=body.config.page.width_mm,
                    height_mm=body.config.page.height_mm,
                    image=None,
                )
            ],
            blocks=[],
        )
    else:
        doc = ctx.load_docir(body.doc_id)
        if doc is None:
            raise ApiError(404, "DOCUMENT_NOT_FOUND", f"文档不存在或尚未解析完成: {body.doc_id}")

    writer_id = body.writer_id or ctx.writers.active_writer_id
    reader = ctx.writers.get(writer_id) if writer_id else None
    if body.writer_id and reader is None:
        raise ApiError(404, "WRITER_NOT_FOUND", f"未找到书写者: {body.writer_id}")

    resolved_writer_id = reader.meta.writer_id if reader is not None else "builtin"
    writer_sha = reader.meta.content_sha256 if reader is not None else "builtin"

    extra_writer_ids: set[str] = set()
    rules = body.config.page_rules
    for ov in (rules.uniform, rules.first_page, rules.rest_pages, rules.odd_pages, rules.even_pages):
        if ov.writer_id:
            extra_writer_ids.add(ov.writer_id)
    for ov in rules.custom_pages.values():
        if ov.writer_id:
            extra_writer_ids.add(ov.writer_id)
    for reg in body.config.regions:
        if reg.enabled and reg.writer_id:
            extra_writer_ids.add(reg.writer_id)

    extra_writer_shas: dict[str, str] = {}
    for wid in sorted(extra_writer_ids):
        extra_reader = ctx.writers.get(wid)
        if extra_reader is not None:
            extra_writer_shas[wid] = extra_reader.meta.content_sha256

    cache_key = ctx.compute_layout_cache_key(
        doc.doc_id,
        doc.source.sha256,
        resolved_writer_id,
        writer_sha,
        body.config,
        extra_writer_shas=extra_writer_shas or None,
    )

    cached = ctx.db.find_layout_by_cache_key(cache_key)
    if cached is not None:
        cached_id = cached["layout_id"]
        if (ctx.layout_dir(cached_id) / "meta.json").is_file():
            def _cached_hit(_task_id: str, report) -> dict[str, Any]:
                report("cache_hit", 95.0, "命中排版缓存", None, None)
                return {
                    "layout_id": cached_id,
                    "doc_id": doc.doc_id,
                    "writer_id": resolved_writer_id,
                    "page_count": cached["page_count"],
                    "cached": True,
                }

            task_id = ctx.tasks.submit(
                "compose",
                _cached_hit,
                initial_stage="cache_hit",
                initial_message="命中排版缓存",
            )
            return JSONResponse(
                status_code=202,
                content={"layout_id": cached_id, "task_id": task_id},
            )

    layout_id = f"ly_{uuid.uuid4().hex[:10]}"

    def _run_compose(_task_id: str, report) -> dict[str, Any]:
        from inkcraft.layout.composer import compose_document

        def _cb(stage: str, pct: float, msg: str) -> None:
            norm_pct = pct * 100.0 if 0.0 <= pct <= 1.0 else pct
            report(stage, min(88.0, norm_pct), msg, None, None)

        pages = compose_document(
            doc,
            reader,
            body.config,
            progress_cb=_cb,
            writer_resolver=ctx.writers.get,
        )
        report("optimize", 92.0, "正在执行路径优化与矢量打包", None, None)
        meta = ctx.save_layout_pages(
            layout_id=layout_id,
            doc_id=doc.doc_id,
            writer_id=resolved_writer_id,
            cache_key=cache_key,
            config=body.config,
            pages=pages,
        )
        return {
            "layout_id": layout_id,
            "doc_id": doc.doc_id,
            "writer_id": resolved_writer_id,
            "page_count": meta["page_count"],
            "cached": False,
        }

    task_id = ctx.tasks.submit(
        "compose",
        _run_compose,
        initial_stage="queued",
        initial_message="正在生成单线手写排版路径",
    )
    return JSONResponse(
        status_code=202,
        content={"layout_id": layout_id, "task_id": task_id},
    )


@router.get("/layouts/{layout_id}")
async def get_layout(layout_id: str, request: Request) -> dict[str, Any]:
    ctx: AppContext = request.app.state.ctx
    row = ctx.db.get_layout(layout_id)
    if row is None:
        raise ApiError(404, "LAYOUT_NOT_FOUND", f"排版结果不存在或仍在生成中: {layout_id}")
    return {
        "layout_id": row["layout_id"],
        "writer_id": row["writer_id"],
        "doc_id": row["doc_id"],
        "page_count": row["page_count"],
        "config": row["config"],
        "pages": row["pages"],
    }


@router.get("/layouts/{layout_id}/pages/{page_index}/paths")
async def get_layout_page_paths(
    layout_id: str,
    request: Request,
    page_index: int = PathParam(..., ge=0),
    format: Literal["json", "f32"] = Query(default="json"),
) -> Response:
    ctx: AppContext = request.app.state.ctx
    pdir = ctx.layout_dir(layout_id) / "pages"

    if format == "f32":
        f32_path = pdir / f"{page_index}.f32"
        hdr_path = pdir / f"{page_index}.f32.headers.json"
        if f32_path.is_file() and hdr_path.is_file():
            data = f32_path.read_bytes()
            headers = json.loads(hdr_path.read_text(encoding="utf-8"))
            return Response(
                content=data,
                media_type="application/octet-stream",
                headers={str(k): str(v) for k, v in headers.items()},
            )

        page = ctx.load_composed_page(layout_id, page_index)
        if page is None:
            raise ApiError(
                404,
                "PAGE_NOT_FOUND",
                f"排版 '{layout_id}' 第 {page_index + 1} 页不存在",
            )
        from inkcraft.layout.export import export_page_f32

        data, headers = export_page_f32(page)
        return Response(
            content=data,
            media_type="application/octet-stream",
            headers={str(k): str(v) for k, v in headers.items()},
        )

    json_path = pdir / f"{page_index}.json"
    if json_path.is_file():
        return JSONResponse(content=json.loads(json_path.read_text(encoding="utf-8")))

    page = ctx.load_composed_page(layout_id, page_index)
    if page is None:
        raise ApiError(
            404,
            "PAGE_NOT_FOUND",
            f"排版 '{layout_id}' 第 {page_index + 1} 页不存在",
        )
    from inkcraft.layout.export import export_page_json

    return JSONResponse(content=export_page_json(layout_id, page))


@router.get("/layouts/{layout_id}/pages/{page_index}/gcode")
async def get_layout_page_gcode(
    layout_id: str,
    request: Request,
    page_index: int = PathParam(..., ge=0),
    profile_id: str | None = Query(default=None),
) -> PlainTextResponse:
    ctx: AppContext = request.app.state.ctx
    profile = ctx.db.get_profile(profile_id) if profile_id else ctx.get_active_profile()
    if profile is None:
        raise ApiError(404, "PROFILE_NOT_FOUND", f"未找到机器配置: {profile_id}")

    compiled = await asyncio.to_thread(
        ctx.compile_layout_page,
        layout_id,
        page_index,
        profile,
        validate_bounds=False,
    )
    return PlainTextResponse(
        content=compiled.to_text(),
        headers={
            "Content-Disposition": f'attachment; filename="{layout_id}_p{page_index}.gcode"'
        },
    )


@router.post("/math/preview")
async def preview_math_latex(
    body: MathPreviewRequest,
    request: Request,
) -> dict[str, Any]:
    """Render live handwritten stroke preview for any LaTeX formula string."""
    ctx: AppContext = request.app.state.ctx
    from inkcraft.layout.math_typesetter import translate_math_strokes, typeset_math
    from inkcraft.layout.perturb import scope_rng
    from inkcraft.writers.selector import VariantSelector

    font_pkg = None
    wid = body.writer_id or ctx.writers.active_writer_id
    if wid:
        try:
            font_pkg = ctx.writers.get(wid)
        except Exception:
            font_pkg = None
    if font_pkg is None:
        font_pkg = ctx.writers.get()

    try:
        selector = VariantSelector(font_pkg, fallback_policy="builtin_single_line")
        upm = float(font_pkg.meta.units_per_em) if font_pkg is not None else 1000.0
        base_u = float(font_pkg.meta.baseline_y) if font_pkg is not None else 800.0
        cfg = PerturbConfig(neatness=0.92, spacing_jitter=0.02, baseline_wave_amp_mm=0.05)
        ml = typeset_math(
            body.latex,
            selector,
            font_size_mm=float(body.font_size_mm),
            formula_scale=float(body.formula_scale),
            inner_row_spacing=float(body.inner_row_spacing),
            display=bool(body.display),
            perturb_cfg=cfg,
            rng=scope_rng(42, "math_preview"),
            units_per_em=upm,
            baseline_u=base_u,
        )
        pad = 2.0
        pts_list = translate_math_strokes(ml, pad, pad + ml.height_mm, scale=1.0)
        return {
            "ok": True,
            "latex": body.latex,
            "width_mm": round(max(12.0, ml.width_mm + pad * 2.0), 2),
            "height_mm": round(max(8.0, ml.total_height_mm + pad * 2.0), 2),
            "strokes": [[round(float(v), 2) for v in st.reshape(-1)] for st in pts_list if len(st) >= 2],
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "latex": body.latex,
            "width_mm": 60.0,
            "height_mm": 18.0,
            "strokes": [],
            "error": str(exc),
        }
