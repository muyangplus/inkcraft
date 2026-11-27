"""Pre-parse upload preview, thumbnail rendering, chapter/experiment split detection & project commit."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import re
import shutil
import statistics
import time
from typing import Any
import uuid

from PIL import Image, ImageDraw
import pymupdf as fitz

from inkcraft.api.schemas import CommitImportProjectSpec
from inkcraft.docparse.chart_extract import PT_TO_MM
from inkcraft.docparse.docir import DocBlock, DocIR, DocPageInfo, DocSource
from inkcraft.docparse.markdown_codec import compute_docir_sha256

logger = logging.getLogger(__name__)

_MAJOR_CHAPTER_RE = re.compile(
    r"^(?:"
    r"实验[一二三四五六七八九十百\d]+(?:[：:、\s]|$)"
    r"|第[一二三四五六七八九十百\d]+[章节篇讲课]"
    r"|(?:Chapter|Experiment|Lab|Unit)\s+\d+"
    r")",
    re.IGNORECASE,
)


def prune_expired_previews(previews_root: Path, *, max_age_sec: int = 7200) -> None:
    """Remove staged preview directories older than `max_age_sec`."""
    if not previews_root.exists():
        return
    cutoff = time.time() - max_age_sec
    for entry in previews_root.iterdir():
        if not entry.is_dir():
            continue
        try:
            if entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
        except Exception:
            pass


def _resolve_preview_dir(previews_root: Path, preview_id: str) -> Path:
    safe_id = str(preview_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", safe_id):
        raise ValueError(f"非法的 preview_id: {preview_id}")
    root = previews_root.resolve()
    target = (root / safe_id).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"非法预览目录路径: {preview_id}")
    return target


def _estimate_pdf_body_pt(pdf_doc: fitz.Document) -> float:
    sizes: list[float] = []
    for pidx in range(min(len(pdf_doc), 8)):
        page = pdf_doc[pidx]
        td = page.get_text("dict")
        for b in td.get("blocks", []):
            if b.get("type") != 0:
                continue
            for ln in b.get("lines", []):
                for sp in ln.get("spans", []):
                    t = str(sp.get("text", "")).strip()
                    if len(t) >= 4:
                        sizes.append(float(sp.get("size", 12.0)))
    return float(statistics.median(sizes)) if sizes else 12.0


def _scan_pdf_page_heading(page: fitz.Page, body_pt: float) -> tuple[str | None, float, int, str]:
    """Return `(major_heading, confidence, level, top_snippet)` for a PDF page in <3ms."""
    page_h = max(100.0, float(page.rect.height))
    td = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    lines: list[tuple[float, float, str]] = []  # (y0, max_pt, text)

    for b in td.get("blocks", []):
        if b.get("type") != 0:
            continue
        for ln in b.get("lines", []):
            pts: list[float] = []
            parts: list[str] = []
            for sp in ln.get("spans", []):
                txt = str(sp.get("text", ""))
                if txt.strip():
                    pts.append(float(sp.get("size", body_pt)))
                parts.append(txt)
            line_text = "".join(parts).strip()
            if not line_text:
                continue
            y0 = float(ln["bbox"][1])
            if y0 < page_h * 0.05 or y0 > page_h * 0.93:
                continue
            lines.append((y0, max(pts) if pts else body_pt, line_text))

    lines.sort(key=lambda item: item[0])
    snippet = " ".join(t for _, _, t in lines[:3])[:140]

    for y0, sz, txt in lines[:8]:
        if _MAJOR_CHAPTER_RE.match(txt) and len(txt) <= 55:
            conf = 0.98 if sz >= body_pt * 1.2 else 0.90
            return txt, conf, 1, snippet
    for y0, sz, txt in lines[:5]:
        if y0 <= page_h * 0.30 and sz >= body_pt * 1.52 and 2 <= len(txt) <= 45:
            return txt, 0.85, 1, snippet

    # Sub-heading for snippet display if no major boundary exists
    for y0, sz, txt in lines[:4]:
        if sz >= body_pt * 1.22 and len(txt) <= 45:
            return None, 0.0, 2, f"{txt} — {snippet}"[:140]
    return None, 0.0, 2, snippet


def _render_text_card_thumb(
    out_path: Path,
    *,
    page_index: int,
    title: str,
    snippet: str,
    dpi: int,
) -> None:
    scale = 1.5 if dpi >= 140 else 1.0
    w, h = int(260 * scale), int(368 * scale)
    im = Image.new("RGB", (w, h), (255, 254, 250))
    draw = ImageDraw.Draw(im)
    draw.rectangle([1, 1, w - 2, h - 2], outline=(218, 224, 232), width=2)
    margin = int(20 * scale)
    draw.rectangle([margin, margin, w - margin, margin + int(28 * scale)], fill=(238, 242, 255))
    header_txt = f"P{page_index + 1} · {title[:22]}"
    draw.text((margin + 8, margin + 8), header_txt, fill=(67, 56, 202))
    # Draw clean mock body preview lines summarizing snippet characters
    y = margin + int(46 * scale)
    preview_lines = [snippet[i : i + 26] for i in range(0, min(len(snippet), 240), 26)]
    for ln in preview_lines:
        draw.text((margin, y), ln, fill=(51, 65, 85))
        y += int(18 * scale)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(str(out_path), format="JPEG", quality=82)


def _detect_sections_from_boundaries(
    boundaries: list[tuple[int, str, float, int]],
    page_count: int,
    fallback_title: str,
) -> list[dict[str, Any]]:
    if page_count <= 0:
        return []
    if not boundaries:
        return [
            {
                "id": "sec_0",
                "title": fallback_title,
                "start_page": 0,
                "end_page": page_count - 1,
                "level": 1,
                "confidence": 1.0,
            }
        ]

    sections: list[dict[str, Any]] = []
    # If content precedes the first boundary (e.g., cover/preface), include it as section 0
    if boundaries[0][0] > 0:
        sections.append(
            {
                "id": "sec_pre",
                "title": f"{fallback_title} (前置页)",
                "start_page": 0,
                "end_page": boundaries[0][0] - 1,
                "level": 1,
                "confidence": 0.75,
            }
        )

    for idx, (start_p, title, conf, lvl) in enumerate(boundaries):
        end_p = (boundaries[idx + 1][0] - 1) if (idx + 1) < len(boundaries) else (page_count - 1)
        if end_p < start_p:
            continue
        sections.append(
            {
                "id": f"sec_{idx}",
                "title": title,
                "start_page": start_p,
                "end_page": end_p,
                "level": lvl,
                "confidence": round(conf, 2),
            }
        )
    return sections


def create_import_preview(
    file_bytes: bytes,
    filename: str,
    previews_root: Path,
) -> dict[str, Any]:
    """Stage uploaded document and produce lightweight page thumbnails + chapter split suggestions."""
    previews_root.mkdir(parents=True, exist_ok=True)
    prune_expired_previews(previews_root)

    ext = Path(filename).suffix.lower()
    preview_id = f"pv_{uuid.uuid4().hex[:12]}"
    pdir = _resolve_preview_dir(previews_root, preview_id)
    thumbs_dir = pdir / "thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    src_path = pdir / f"source{ext}"
    src_path.write_bytes(file_bytes)
    stem_title = Path(filename).stem or "未命名文稿"

    pages_meta: list[dict[str, Any]] = []
    boundaries: list[tuple[int, str, float, int]] = []

    if ext == ".pdf":
        pdf_doc = fitz.open(str(src_path))
        try:
            page_count = len(pdf_doc)
            body_pt = _estimate_pdf_body_pt(pdf_doc)
            eager_limit = page_count if page_count <= 30 else 12
            zoom = 96.0 / 72.0
            mat = fitz.Matrix(zoom, zoom)

            for pidx in range(page_count):
                page = pdf_doc[pidx]
                w_mm = round(float(page.rect.width) * PT_TO_MM, 2)
                h_mm = round(float(page.rect.height) * PT_TO_MM, 2)
                heading, conf, lvl, snippet = _scan_pdf_page_heading(page, body_pt)
                if heading:
                    boundaries.append((pidx, heading, conf, lvl))

                if pidx < eager_limit:
                    pix = page.get_pixmap(matrix=mat, alpha=False)
                    pix.save(str(thumbs_dir / f"p{pidx}_96.jpg"))

                pages_meta.append(
                    {
                        "page_index": pidx,
                        "width_mm": w_mm,
                        "height_mm": h_mm,
                        "heading": heading or "",
                        "snippet": snippet,
                        "thumb_url": f"/api/v1/documents/preview/{preview_id}/pages/{pidx}/thumb?dpi=96",
                    }
                )
        finally:
            pdf_doc.close()

        detected_sections = _detect_sections_from_boundaries(boundaries, len(pages_meta), stem_title)
        manifest = {
            "preview_id": preview_id,
            "filename": filename,
            "file_type": "pdf",
            "page_count": len(pages_meta),
            "pages": pages_meta,
            "detected_sections": detected_sections,
        }
    else:
        from inkcraft.docparse.service import parse_document

        parsed_dir = pdir / "parsed"
        full_doc = parse_document(src_path, doc_id=f"pvdoc_{preview_id}", out_dir=parsed_dir)
        blocks = full_doc.blocks

        # Group non-empty blocks by top-level chapters/headings (or chunk by ~16 blocks)
        groups: list[tuple[str, int, int]] = []  # (title, start_idx, end_idx)
        cur_start = 0
        cur_title = stem_title
        for bi, blk in enumerate(blocks):
            txt = blk.plain_text().strip()
            is_split_heading = (
                blk.type == "heading"
                and bool(_MAJOR_CHAPTER_RE.match(txt))
                and bi > cur_start
            )
            if is_split_heading:
                groups.append((cur_title, cur_start, bi))
                cur_title = txt or f"章节 {len(groups) + 1}"
                cur_start = bi
        if cur_start < len(blocks) or not groups:
            groups.append((cur_title, cur_start, len(blocks)))

        for gi, (g_title, b_start, b_end) in enumerate(groups):
            slice_texts = [
                blocks[k].plain_text().strip()
                for k in range(b_start, min(b_end, b_start + 8))
                if blocks[k].plain_text().strip()
            ]
            snippet = " ".join(slice_texts)[:160]
            _render_text_card_thumb(
                thumbs_dir / f"p{gi}_96.jpg",
                page_index=gi,
                title=g_title,
                snippet=snippet,
                dpi=96,
            )
            pages_meta.append(
                {
                    "page_index": gi,
                    "width_mm": 210.0,
                    "height_mm": 297.0,
                    "heading": g_title,
                    "snippet": snippet,
                    "block_start": b_start,
                    "block_end": b_end,
                    "thumb_url": f"/api/v1/documents/preview/{preview_id}/pages/{gi}/thumb?dpi=96",
                }
            )
            boundaries.append((gi, g_title, 0.92, 1))

        detected_sections = _detect_sections_from_boundaries(boundaries, len(pages_meta), stem_title)
        manifest = {
            "preview_id": preview_id,
            "filename": filename,
            "file_type": "docx" if ext == ".docx" else "text",
            "page_count": len(pages_meta),
            "pages": pages_meta,
            "detected_sections": detected_sections,
        }

    (pdir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def load_preview_manifest(previews_root: Path, preview_id: str) -> tuple[Path, dict[str, Any]]:
    pdir = _resolve_preview_dir(previews_root, preview_id)
    mfile = pdir / "manifest.json"
    if not mfile.is_file():
        raise FileNotFoundError(f"预览会话不存在或已过期: {preview_id}")
    return pdir, json.loads(mfile.read_text(encoding="utf-8"))


def ensure_preview_thumb(
    previews_root: Path,
    preview_id: str,
    page_index: int,
    *,
    dpi: int = 96,
) -> Path:
    pdir, manifest = load_preview_manifest(previews_root, preview_id)
    eff_dpi = 150 if dpi >= 125 else 96
    page_count = int(manifest.get("page_count", 0))
    if page_index < 0 or page_index >= page_count:
        raise IndexError(f"页码超出范围: {page_index}")

    thumbs_dir = (pdir / "thumbs").resolve()
    thumb_path = (thumbs_dir / f"p{page_index}_{eff_dpi}.jpg").resolve()
    if not thumb_path.is_relative_to(thumbs_dir):
        raise ValueError("非法缩略图路径")
    if thumb_path.is_file():
        return thumb_path

    if manifest.get("file_type") == "pdf":
        src_pdf = pdir / "source.pdf"
        if not src_pdf.is_file():
            raise FileNotFoundError("源 PDF 文件已不存在")
        pdf_doc = fitz.open(str(src_pdf))
        try:
            page = pdf_doc[page_index]
            zoom = float(eff_dpi) / 72.0
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            pix.save(str(thumb_path))
        finally:
            pdf_doc.close()
    else:
        page_meta = manifest["pages"][page_index]
        _render_text_card_thumb(
            thumb_path,
            page_index=page_index,
            title=str(page_meta.get("heading") or f"段落节 {page_index + 1}"),
            snippet=str(page_meta.get("snippet") or ""),
            dpi=eff_dpi,
        )
    return thumb_path


def _clean_crop_map(
    crop_rects_mm: dict[str, list[float]],
    selected_pages: list[int],
) -> dict[str, list[float]]:
    """Remap original page crop boxes cleanly to 0..k-1 slice indices."""
    out: dict[str, list[float]] = {}
    if "default" in crop_rects_mm and len(crop_rects_mm["default"]) == 4:
        out["default"] = [float(v) for v in crop_rects_mm["default"]]
    for new_idx, orig_idx in enumerate(selected_pages):
        raw = crop_rects_mm.get(str(orig_idx))
        if raw and len(raw) == 4:
            out[str(new_idx)] = [float(v) for v in raw]
    return out


def commit_preview_projects(
    *,
    pdir: Path,
    manifest: dict[str, Any],
    projects: list[CommitImportProjectSpec],
    mode_hint: str,
    ctx: Any,
) -> tuple[list[dict[str, Any]], Any]:
    """Allocate project document records and return a background task callable to slice & parse them."""
    page_count = int(manifest.get("page_count", 0))
    orig_filename = str(manifest.get("filename", "document"))
    file_type = str(manifest.get("file_type", "pdf"))

    created_specs: list[dict[str, Any]] = []
    for proj in projects:
        clean_pages = sorted({int(p) for p in proj.page_indices if 0 <= int(p) < page_count})
        if not clean_pages:
            raise ValueError(f"项目「{proj.title}」未包含有效页码")
        doc_id = f"doc_{uuid.uuid4().hex[:10]}"
        title_clean = proj.title.strip() or f"{Path(orig_filename).stem} ({len(created_specs) + 1})"
        ext = Path(orig_filename).suffix.lower() or (".pdf" if file_type == "pdf" else ".docx")
        display_name = title_clean if title_clean.lower().endswith(ext) else f"{title_clean}{ext}"

        out_dir = ctx.doc_dir(doc_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        sha_seed = hashlib.sha256(f"{manifest['preview_id']}:{doc_id}:{clean_pages}".encode()).hexdigest()

        ctx.db.upsert_document(
            doc_id=doc_id,
            filename=display_name,
            file_type=file_type,
            sha256=sha_seed,
            page_count=len(clean_pages),
            status="parsing",
            meta={
                "source": {
                    "type": file_type,
                    "filename": display_name,
                    "sha256": sha_seed,
                    "parser": "pending",
                },
                "pages": [],
            },
        )
        created_specs.append(
            {
                "doc_id": doc_id,
                "title": title_clean,
                "filename": display_name,
                "page_indices": clean_pages,
                "crop_rects_mm": dict(proj.crop_rects_mm),
                "exclude_header_footer": bool(proj.exclude_header_footer),
                "out_dir": str(out_dir),
            }
        )

    def _run_commit(_task_id: str, report) -> dict[str, Any]:
        total_proj = max(1, len(created_specs))
        results: list[dict[str, Any]] = []
        try:
            if file_type == "pdf":
                from inkcraft.docparse.pdf_parser import parse_pdf

                src_pdf = pdir / "source.pdf"
                src_doc = fitz.open(str(src_pdf))
                try:
                    for pi, spec in enumerate(created_specs):
                        out_dir = Path(spec["out_dir"])
                        sub_pdf_path = out_dir / "source.pdf"
                        sub_pdf = fitz.open()
                        try:
                            for orig_p in spec["page_indices"]:
                                sub_pdf.insert_pdf(src_doc, from_page=orig_p, to_page=orig_p)
                            sub_pdf.save(str(sub_pdf_path))
                        finally:
                            sub_pdf.close()

                        remapped_crops = _clean_crop_map(
                            spec["crop_rects_mm"], spec["page_indices"]
                        )

                        def _sub_cb(stage: str, pct: float, page: int, pc: int, msg: str, _pi=pi) -> None:
                            overall = ((_pi + max(0.0, min(1.0, pct))) / total_proj) * 100.0
                            report(stage, overall, f"[{_pi + 1}/{total_proj}] {msg}", page, pc)

                        doc_ir = parse_pdf(
                            sub_pdf_path,
                            doc_id=spec["doc_id"],
                            out_dir=out_dir,
                            use_mineru=(mode_hint != "pymupdf_only"),
                            progress_cb=_sub_cb,
                            crop_rects_mm=remapped_crops or None,
                            exclude_header_footer=spec["exclude_header_footer"],
                        )
                        doc_ir.source.filename = spec["filename"]
                        ctx.save_docir(doc_ir, status="ready")
                        results.append(
                            {
                                "doc_id": doc_ir.doc_id,
                                "filename": spec["filename"],
                                "page_count": len(doc_ir.pages),
                                "status": "ready",
                            }
                        )
                finally:
                    src_doc.close()
            else:
                parsed_dir = pdir / "parsed"
                full_doc_json = parsed_dir / "docir.json"
                full_doc = DocIR.model_validate_json(full_doc_json.read_text(encoding="utf-8"))
                src_assets = parsed_dir / "assets"
                pages_lookup = {int(m["page_index"]): m for m in manifest["pages"]}

                for pi, spec in enumerate(created_specs):
                    report(
                        "assemble",
                        ((pi + 0.5) / total_proj) * 100.0,
                        f"正在拆分导出项目 {pi + 1}/{total_proj}: {spec['filename']}",
                        pi + 1,
                        total_proj,
                    )
                    out_dir = Path(spec["out_dir"])
                    dst_assets = out_dir / "assets"
                    dst_assets.mkdir(parents=True, exist_ok=True)
                    sub_blocks: list[DocBlock] = []
                    for sec_idx in spec["page_indices"]:
                        pm = pages_lookup.get(sec_idx)
                        if not pm:
                            continue
                        b_start = int(pm.get("block_start", 0))
                        b_end = int(pm.get("block_end", 0))
                        for b in full_doc.blocks[b_start:b_end]:
                            if spec["exclude_header_footer"] and b.type in {
                                "header",
                                "footer",
                                "page_number",
                                "discarded",
                            }:
                                continue
                            cloned = b.model_copy(deep=True)
                            cloned.block_id = f"b{len(sub_blocks)}"
                            cloned.reading_order = len(sub_blocks)
                            cloned.page_index = 0
                            if cloned.asset_name and (src_assets / cloned.asset_name).is_file():
                                dst_file = dst_assets / cloned.asset_name
                                shutil.copy2(src_assets / cloned.asset_name, dst_file)
                                cloned.image_path = str(dst_file)
                            sub_blocks.append(cloned)

                    sub_doc = DocIR(
                        doc_id=spec["doc_id"],
                        source=DocSource(
                            type=full_doc.source.type,
                            filename=spec["filename"],
                            sha256="pending",
                            parser=f"{full_doc.source.parser}:split",
                        ),
                        pages=[DocPageInfo(page_index=0, width_mm=210.0, height_mm=297.0, image=None)],
                        blocks=sub_blocks,
                    )
                    sub_doc.source.sha256 = compute_docir_sha256(sub_doc)
                    ctx.save_docir(sub_doc, status="ready")
                    results.append(
                        {
                            "doc_id": sub_doc.doc_id,
                            "filename": spec["filename"],
                            "page_count": len(sub_doc.pages),
                            "status": "ready",
                        }
                    )
                report("done", 100.0, f"已完成 {total_proj} 个项目导入", total_proj, total_proj)

            return {
                "doc_id": results[0]["doc_id"] if results else None,
                "documents": results,
                "status": "ready",
            }
        except Exception:
            for spec in created_specs:
                if not any(r["doc_id"] == spec["doc_id"] for r in results):
                    ctx.db.upsert_document(
                        doc_id=spec["doc_id"],
                        filename=spec["filename"],
                        file_type=file_type,
                        sha256="failed",
                        page_count=0,
                        status="failed",
                    )
            raise
        finally:
            shutil.rmtree(pdir, ignore_errors=True)

    return [
        {"doc_id": s["doc_id"], "title": s["filename"], "page_count": len(s["page_indices"])}
        for s in created_specs
    ], _run_commit
