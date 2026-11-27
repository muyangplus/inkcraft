"""PDF parser: PyMuPDF 150-DPI underlay rendering + MinerU pipeline adapter + structured fallback."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
import re
import statistics
from typing import Callable

import pymupdf as fitz
from lxml import html as lxml_html

from inkcraft.docparse.chart_extract import (
    PT_TO_MM,
    detect_chart_regions_on_page,
    extract_pdf_vector_drawings,
)
from inkcraft.docparse.docir import (
    BlockType,
    ChartData,
    DocBlock,
    DocInline,
    DocIR,
    DocLine,
    DocPageInfo,
    DocSource,
    MathInline,
    TableCell,
    TableData,
    TextInline,
)
from inkcraft.docparse.inline_math import (
    _INLINE_MATH_RE,  # noqa: F401
    normalize_unambiguous_unit_powers,
    split_inline_math,
    strip_inline_math_markup,
)
from inkcraft.docparse.formula_ocr import (
    build_cjk_lexicon,
    classify_raster_image,
    extract_pdf_native_math_blocks,
    normalize_text_math_alnum,
    recognize_formula_image,
    recognize_text_caption_image,
)
from inkcraft.docparse.pdf_paragraph import (
    PageTypographyProfile,
    compute_page_profile,
    extract_raw_pdf_lines,
    looks_like_formula_line,
    merge_cross_page_paragraphs,
    reconstruct_page_paragraphs,
)
from inkcraft.docparse.mineru_worker import (
    MinerUExecutionError,
    MinerUResult,
    MinerUUnavailableError,
    run_mineru_pipeline,
)

logger = logging.getLogger(__name__)

ProgressHook = Callable[[str, float, int, int, str], None]

_MATH_HINT_CHARS = set("∫∑∏√±×÷≤≥≠≈∞∂∇αβγδεθλμπρστφωΔΣΠΩ")
_LATEX_CMD_RE = re.compile(r"\\(?:frac|sqrt|sum|int|prod|lim|alpha|beta|gamma|pi|theta|Delta|Sigma)")


def _parse_html_table(table_html: str) -> TableData | None:
    """Parse MinerU HTML `<table>` string into `TableData` with rowspan/colspan resolution."""
    if not table_html or "<table" not in table_html.lower():
        return None
    try:
        doc = lxml_html.fromstring(table_html)
    except Exception:
        return None

    rows_el = doc.xpath(".//tr")
    if not rows_el:
        return None

    occupied: set[tuple[int, int]] = set()
    cells: list[TableCell] = []
    max_cols = 0

    for r_idx, tr in enumerate(rows_el):
        c_idx = 0
        for td in tr.xpath("./th|./td"):
            while (r_idx, c_idx) in occupied:
                c_idx += 1
            try:
                rs = max(1, int(td.get("rowspan", "1")))
            except ValueError:
                rs = 1
            try:
                cs = max(1, int(td.get("colspan", "1")))
            except ValueError:
                cs = 1

            raw_text = " ".join("".join(td.itertext()).split())
            inlines = split_inline_math(raw_text) if raw_text else []
            cells.append(TableCell(r=r_idx, c=c_idx, rs=rs, cs=cs, inlines=inlines))

            for dr in range(rs):
                for dc in range(cs):
                    occupied.add((r_idx + dr, c_idx + dc))
            c_idx += cs
            max_cols = max(max_cols, c_idx)

    if max_cols == 0:
        return None
    return TableData(rows=len(rows_el), cols=max_cols, cells=cells)


def _adapt_mineru_result(
    mineru_res: MinerUResult,
    pdf_doc: fitz.Document,
    pages_info: list[DocPageInfo],
) -> list[DocBlock]:
    """Convert MinerU `middle.json` / `content_list.json` into `DocBlock`s with mm coordinates."""
    blocks: list[DocBlock] = []
    per_page_counter: dict[int, int] = {}

    def _bid(pidx: int) -> str:
        n = per_page_counter.get(pidx, 0)
        per_page_counter[pidx] = n + 1
        return f"p{pidx}-b{n}"

    # Prefer `pdf_info` (middle.json) since it has exact per-line bboxes
    if mineru_res.pdf_info:
        for page_entry in mineru_res.pdf_info:
            pidx = int(page_entry.get("page_idx", 0))
            if pidx < 0 or pidx >= len(pdf_doc):
                continue
            fitz_page = pdf_doc[pidx]
            page_size = page_entry.get("page_size")
            if isinstance(page_size, list) and len(page_size) == 2 and page_size[0] > 0 and page_size[1] > 0:
                sx = pages_info[pidx].width_mm / float(page_size[0])
                sy = pages_info[pidx].height_mm / float(page_size[1])
            else:
                sx = PT_TO_MM
                sy = PT_TO_MM

            def _to_mm(box: list[float] | None) -> list[float] | None:
                if not box or len(box) != 4:
                    return None
                return [
                    round(float(box[0]) * sx, 2),
                    round(float(box[1]) * sy, 2),
                    round(float(box[2]) * sx, 2),
                    round(float(box[3]) * sy, 2),
                ]

            raw_blocks = page_entry.get("para_blocks") or page_entry.get("preproc_blocks") or []
            for rb in raw_blocks:
                btype_raw = str(rb.get("type", "text")).lower()
                bbox_mm = _to_mm(rb.get("bbox"))

                if btype_raw == "interline_equation":
                    tex_parts: list[str] = []
                    for line in rb.get("lines", []):
                        for span in line.get("spans", []):
                            content = str(span.get("content", "")).strip()
                            if content:
                                tex_parts.append(content)
                    tex = " ".join(tex_parts).strip("$ ")
                    if tex:
                        blocks.append(
                            DocBlock(
                                block_id=_bid(pidx),
                                page_index=pidx,
                                type="formula_block",
                                reading_order=len(blocks),
                                bbox_mm=bbox_mm,
                                latex=tex,
                            )
                        )
                    continue

                if btype_raw == "table":
                    html_str = ""
                    for sub in rb.get("blocks", []):
                        for line in sub.get("lines", []):
                            for span in line.get("spans", []):
                                if span.get("html"):
                                    html_str = str(span["html"])
                    tdata = _parse_html_table(html_str)
                    if tdata is not None:
                        blocks.append(
                            DocBlock(
                                block_id=_bid(pidx),
                                page_index=pidx,
                                type="table",
                                reading_order=len(blocks),
                                bbox_mm=bbox_mm,
                                table=tdata,
                            )
                        )
                    continue

                if btype_raw in {"image", "figure"}:
                    img_path: str | None = None
                    for sub in rb.get("blocks", []):
                        for line in sub.get("lines", []):
                            for span in line.get("spans", []):
                                if span.get("image_path") and mineru_res.images_dir:
                                    cand = mineru_res.images_dir / str(span["image_path"])
                                    if cand.is_file():
                                        img_path = str(cand)
                    polylines, polygons = (
                        extract_pdf_vector_drawings(fitz_page, clip_mm=bbox_mm, normalize=True)
                        if bbox_mm
                        else ([], [])
                    )
                    if polylines or polygons:
                        chart = ChartData(
                            chart_type="vector",
                            vector_polylines=polylines,
                            vector_polygons=polygons,
                            image_path=img_path,
                            extra={"origin": "pdf_vector", "coord_space": "normalized"},
                        )
                        blocks.append(
                            DocBlock(
                                block_id=_bid(pidx),
                                page_index=pidx,
                                type="chart",
                                reading_order=len(blocks),
                                bbox_mm=bbox_mm,
                                chart=chart,
                                image_path=img_path,
                                asset_name=Path(img_path).name if img_path else None,
                                image_render_mode="outline",
                            )
                        )
                    elif img_path:
                        kind = classify_raster_image(img_path, bbox_mm)
                        asset_name = Path(img_path).name
                        if kind == "formula":
                            latex, ocr_src = recognize_formula_image(img_path)
                            blocks.append(
                                DocBlock(
                                    block_id=_bid(pidx),
                                    page_index=pidx,
                                    type="formula_block",
                                    reading_order=len(blocks),
                                    bbox_mm=bbox_mm,
                                    latex=latex,
                                    image_path=img_path,
                                    asset_name=asset_name,
                                    ocr_source=ocr_src,
                                )
                            )
                        elif kind == "text_caption":
                            cap = recognize_text_caption_image(img_path)
                            blocks.append(
                                DocBlock(
                                    block_id=_bid(pidx),
                                    page_index=pidx,
                                    type="caption",
                                    reading_order=len(blocks),
                                    bbox_mm=bbox_mm,
                                    inlines=[TextInline(text=cap)] if cap else [],
                                    image_path=img_path,
                                    asset_name=asset_name,
                                    ocr_source="rapidocr_caption",
                                )
                            )
                        else:
                            w_mm = round(bbox_mm[2] - bbox_mm[0], 2) if bbox_mm else None
                            h_mm = round(bbox_mm[3] - bbox_mm[1], 2) if bbox_mm else None
                            blocks.append(
                                DocBlock(
                                    block_id=_bid(pidx),
                                    page_index=pidx,
                                    type="figure",
                                    reading_order=len(blocks),
                                    bbox_mm=bbox_mm,
                                    image_path=img_path,
                                    asset_name=asset_name,
                                    image_render_mode="outline",
                                    placement="inline",
                                    image_align="center",
                                    image_width_mm=w_mm,
                                    image_height_mm=h_mm,
                                    chart=ChartData(chart_type="raster", image_path=img_path),
                                )
                            )
                    continue

                # Text / title / list blocks
                doc_lines: list[DocLine] = []
                all_inlines: list[DocInline] = []
                for line in rb.get("lines", []):
                    line_inlines: list[DocInline] = []
                    for span in line.get("spans", []):
                        stype = str(span.get("type", "text")).lower()
                        content = str(span.get("content", ""))
                        if not content:
                            continue
                        if stype == "inline_equation":
                            line_inlines.append(MathInline(latex=content.strip("$ ")))
                        else:
                            line_inlines.extend(split_inline_math(content))
                    if line_inlines:
                        doc_lines.append(
                            DocLine(bbox_mm=_to_mm(line.get("bbox")), inlines=line_inlines)
                        )
                        all_inlines.extend(line_inlines)

                if not all_inlines:
                    continue

                mapped_type: BlockType = "paragraph"
                if btype_raw == "title":
                    mapped_type = "heading"
                elif btype_raw == "list":
                    mapped_type = "list_item"
                elif btype_raw in {"header", "footer", "page_number", "discarded"}:
                    mapped_type = btype_raw  # type: ignore[assignment]

                blocks.append(
                    DocBlock(
                        block_id=_bid(pidx),
                        page_index=pidx,
                        type=mapped_type,
                        reading_order=len(blocks),
                        bbox_mm=bbox_mm,
                        lines=doc_lines,
                        inlines=all_inlines,
                    )
                )
        return blocks

    # Fallback: adapt `content_list.json` if `middle.json` wasn't emitted
    for item in mineru_res.content_list:
        pidx = int(item.get("page_idx", 0))
        itype = str(item.get("type", "text")).lower()
        if itype == "equation":
            tex = str(item.get("text", "")).strip("$ ")
            if tex:
                blocks.append(
                    DocBlock(
                        block_id=_bid(pidx),
                        page_index=pidx,
                        type="formula_block",
                        reading_order=len(blocks),
                        latex=tex,
                    )
                )
        elif itype == "table":
            tdata = _parse_html_table(str(item.get("table_body", "")))
            if tdata is not None:
                blocks.append(
                    DocBlock(
                        block_id=_bid(pidx),
                        page_index=pidx,
                        type="table",
                        reading_order=len(blocks),
                        table=tdata,
                    )
                )
        elif itype == "text":
            txt = str(item.get("text", "")).strip()
            if txt:
                lvl = item.get("text_level")
                blocks.append(
                    DocBlock(
                        block_id=_bid(pidx),
                        page_index=pidx,
                        type="heading" if lvl else "paragraph",
                        level=int(lvl) if isinstance(lvl, int) and 1 <= lvl <= 6 else 1,
                        reading_order=len(blocks),
                        inlines=split_inline_math(txt),
                    )
                )
    return blocks


def _looks_like_formula(text: str) -> bool:
    s = text.strip()
    if not s or len(s) > 160:
        return False
    if (s.startswith("$$") and s.endswith("$$")) or (s.startswith("$") and s.endswith("$") and s.count("$") == 2):
        return True
    if _LATEX_CMD_RE.search(s):
        return True
    math_hits = sum(1 for ch in s if ch in _MATH_HINT_CHARS)
    if math_hits >= 2 and len(s) <= 80:
        return True
    if "=" in s and math_hits >= 1 and len(s) <= 60:
        return True
    return False


def _bbox_overlaps(a: list[float], b: list[float], tol: float = 1.5) -> bool:
    return not (a[2] < b[0] + tol or a[0] > b[2] - tol or a[3] < b[1] + tol or a[1] > b[3] - tol)


def _resolve_crop_rect(crop_rects_mm: dict[str, list[float]] | None, page_index: int) -> list[float] | None:
    if not crop_rects_mm:
        return None
    rect = crop_rects_mm.get(str(page_index)) or crop_rects_mm.get("default")
    if not rect or len(rect) != 4:
        return None
    x0, y0, x1, y1 = [float(v) for v in rect]
    if x1 <= x0 + 2.0 or y1 <= y0 + 2.0:
        return None
    return [x0, y0, x1, y1]


def _bbox_center_in_crop(bbox_mm: list[float] | None, crop_mm: list[float] | None, tol: float = 1.0) -> bool:
    if not crop_mm or not bbox_mm or len(bbox_mm) != 4:
        return True
    cx = 0.5 * (float(bbox_mm[0]) + float(bbox_mm[2]))
    cy = 0.5 * (float(bbox_mm[1]) + float(bbox_mm[3]))
    return (
        crop_mm[0] - tol <= cx <= crop_mm[2] + tol
        and crop_mm[1] - tol <= cy <= crop_mm[3] + tol
    )


def _block_plain(blk: DocBlock) -> str:
    if blk.latex:
        return blk.latex
    return blk.plain_text().strip()


def _extract_formula_context(
    sorted_blocks: list[DocBlock],
    ibbox: list[float],
    *,
    page_h_mm: float,
    prev_page_tail_text: str = "",
    next_page_head_text: str = "",
) -> tuple[str, str, str]:
    """Gather generous semantic context above, below (contiguous `式中...` up to 15 blocks), and section text."""
    above: list[DocBlock] = []
    below: list[DocBlock] = []
    section_parts: list[str] = []

    for blk in sorted_blocks:
        txt = _block_plain(blk)
        if not txt:
            continue
        if blk.type in {"paragraph", "heading", "list_item", "caption"}:
            section_parts.append(txt)
        if not blk.bbox_mm or len(blk.bbox_mm) != 4:
            continue
        if blk.bbox_mm[3] <= ibbox[1] + 4.0:
            above.append(blk)
        elif blk.bbox_mm[1] >= ibbox[3] - 4.0:
            below.append(blk)

    # Take up to 6 blocks immediately above, stopping at the nearest preceding heading
    above_texts: list[str] = []
    for blk in reversed(above):
        txt = _block_plain(blk)
        above_texts.append(txt)
        if blk.type == "heading" or len(above_texts) >= 6:
            break
    above_texts.reverse()

    # Take up to 15 blocks below through contiguous equation tag / `式中...` symbol definitions
    below_texts: list[str] = []
    seen_sym_block = False
    for idx, blk in enumerate(below):
        txt = _block_plain(blk)
        plain_role = strip_inline_math_markup(txt)
        if blk.type == "heading" and idx > 0:
            break
        below_texts.append(txt)
        is_sym_or_tag = bool(
            re.match(r"^(?:式中|其中|[（(]式\s*\d)", plain_role)
            or re.match(r"^[A-Za-zα-ωΑ-ΩΔρ△][^，。]{0,12}(?:--|——|—|–|[,，])", plain_role)
        )
        if is_sym_or_tag:
            seen_sym_block = True
        elif seen_sym_block and len(below_texts) >= 6:
            break
        elif not seen_sym_block and len(below_texts) >= 5:
            break
        if len(below_texts) >= 15:
            break

    if (not below_texts or ibbox[3] >= page_h_mm * 0.72) and next_page_head_text:
        below_texts.append(next_page_head_text)

    prev_ctx = " ".join(above_texts) if above_texts else prev_page_tail_text
    next_ctx = " ".join(below_texts)
    section_text = "\n".join(p for p in [prev_page_tail_text, *section_parts, next_page_head_text] if p)
    return prev_ctx, next_ctx, section_text


def _extract_page_structure_pymupdf(
    page: fitz.Page,
    page_index: int,
    *,
    fallback_profile: PageTypographyProfile | None = None,
    crop_rect_mm: list[float] | None = None,
    exclude_header_footer: bool = False,
) -> tuple[list[DocBlock], list[list[float]], PageTypographyProfile]:
    """Extract tables, native math, vector charts, and geometrically reconstructed paragraphs for one page."""
    page_w = float(page.rect.width) * PT_TO_MM
    page_h = float(page.rect.height) * PT_TO_MM

    blocks: list[DocBlock] = []
    table_bboxes: list[list[float]] = []
    chart_bboxes: list[list[float]] = []

    clip_rect: fitz.Rect | None = None
    if crop_rect_mm and len(crop_rect_mm) == 4:
        clip_rect = fitz.Rect(
            float(crop_rect_mm[0]) / PT_TO_MM,
            float(crop_rect_mm[1]) / PT_TO_MM,
            float(crop_rect_mm[2]) / PT_TO_MM,
            float(crop_rect_mm[3]) / PT_TO_MM,
        )

    # 1. Detect tables via PyMuPDF find_tables (clipped when crop selected)
    try:
        tf = page.find_tables(clip=clip_rect) if clip_rect is not None else page.find_tables()
        for tab in tf.tables:
            raw_rows = tab.extract()
            if not raw_rows or len(raw_rows) < 2:
                continue
            ncols = max(len(r) for r in raw_rows)
            if ncols < 2:
                continue
            tb = [round(float(v) * PT_TO_MM, 2) for v in tab.bbox]
            if not _bbox_center_in_crop(tb, crop_rect_mm):
                continue
            cells: list[TableCell] = []
            for r_i, row in enumerate(raw_rows):
                for c_i, cell_val in enumerate(row):
                    txt = normalize_unambiguous_unit_powers(" ".join(str(cell_val or "").split()))
                    cells.append(
                        TableCell(
                            r=r_i,
                            c=c_i,
                            rs=1,
                            cs=1,
                            inlines=split_inline_math(txt) if txt else [],
                        )
                    )
            col_w = round((tb[2] - tb[0]) / max(1, ncols), 2)
            table_bboxes.append(tb)
            blocks.append(
                DocBlock(
                    block_id="",
                    page_index=page_index,
                    type="table",
                    bbox_mm=tb,
                    table=TableData(
                        rows=len(raw_rows),
                        cols=ncols,
                        col_widths_mm=[col_w] * ncols,
                        cells=cells,
                    ),
                )
            )
    except Exception as exc:
        logger.debug("PyMuPDF find_tables skipped on page %d: %s", page_index, exc)

    # 1.5 Detect native PDF fraction equations (CambriaMath/math spans + drawn fraction bar)
    native_math_blocks, native_math_bboxes = extract_pdf_native_math_blocks(
        page, exclude_bboxes_mm=table_bboxes
    )
    filtered_native_bboxes: list[list[float]] = []
    for mb in native_math_blocks:
        if not _bbox_center_in_crop(mb.bbox_mm, crop_rect_mm):
            continue
        mb.page_index = page_index
        blocks.append(mb)
        if mb.bbox_mm:
            filtered_native_bboxes.append(mb.bbox_mm)

    # 2. Detect vector chart regions outside tables and native math fraction bars
    for cbbox, chart_data in detect_chart_regions_on_page(
        page, exclude_bboxes_mm=table_bboxes + native_math_bboxes
    ):
        if not _bbox_center_in_crop(cbbox, crop_rect_mm):
            continue
        chart_bboxes.append(cbbox)
        blocks.append(
            DocBlock(
                block_id="",
                page_index=page_index,
                type="chart",
                bbox_mm=cbbox,
                chart=chart_data,
            )
        )

    # 3. Extract raw visual lines & geometrically reconstruct coherent paragraphs
    raw_lines = extract_raw_pdf_lines(
        page,
        page_index,
        exclude_bboxes_mm=table_bboxes,
        native_math_bboxes_mm=native_math_bboxes,
        crop_rect_mm=crop_rect_mm,
    )
    profile = compute_page_profile(
        raw_lines, page_index, page_w, page_h, fallback_profile=fallback_profile
    )

    # Non-text blocks serve as vertical merge obstacles while preserving order
    text_obstacles: list[list[float]] = list(table_bboxes) + list(chart_bboxes) + list(filtered_native_bboxes)
    for img_info in page.get_images(full=True):
        xref = img_info[0]
        try:
            for r in page.get_image_rects(xref):
                ib = [
                    round(float(r.x0) * PT_TO_MM, 2),
                    round(float(r.y0) * PT_TO_MM, 2),
                    round(float(r.x1) * PT_TO_MM, 2),
                    round(float(r.y1) * PT_TO_MM, 2),
                ]
                if ib[2] - ib[0] >= 6.0 and ib[3] - ib[1] >= 3.5:
                    text_obstacles.append(ib)
        except Exception:
            pass

    para_blocks = reconstruct_page_paragraphs(
        raw_lines,
        text_obstacles,
        page_index=page_index,
        profile=profile,
    )
    if exclude_header_footer:
        para_blocks = [
            b for b in para_blocks if b.type not in {"header", "footer", "page_number", "discarded"}
        ]
    blocks.extend(para_blocks)
    return blocks, chart_bboxes, profile


def _extract_page_images_pymupdf(
    page: fitz.Page,
    page_index: int,
    assets_dir: Path | None,
    *,
    existing_blocks: list[DocBlock],
    chart_bboxes: list[list[float]],
    prev_page_tail_text: str = "",
    next_page_head_text: str = "",
    doc_lexicon: set[str] | None = None,
    crop_rect_mm: list[float] | None = None,
) -> list[DocBlock]:
    """Extract and classify embedded raster images on a page using rich text & document lexicon context."""
    if assets_dir is None:
        return []

    page_h = float(page.rect.height) * PT_TO_MM
    sorted_ctx_blocks = sorted(
        existing_blocks,
        key=lambda blk: (
            blk.bbox_mm[1] if blk.bbox_mm else 0.0,
            blk.bbox_mm[0] if blk.bbox_mm else 0.0,
        ),
    )

    img_blocks: list[DocBlock] = []
    for img_idx, img_info in enumerate(page.get_images(full=True)):
        xref = img_info[0]
        try:
            rects = page.get_image_rects(xref)
            if not rects:
                continue
            r = rects[0]
            ibbox = [
                round(float(r.x0) * PT_TO_MM, 2),
                round(float(r.y0) * PT_TO_MM, 2),
                round(float(r.x1) * PT_TO_MM, 2),
                round(float(r.y1) * PT_TO_MM, 2),
            ]
            w_mm = round(ibbox[2] - ibbox[0], 2)
            h_mm = round(ibbox[3] - ibbox[1], 2)
            if w_mm < 6.0 or h_mm < 3.5:
                continue
            if not _bbox_center_in_crop(ibbox, crop_rect_mm):
                continue
            if any(_bbox_overlaps(ibbox, cb) for cb in chart_bboxes):
                continue

            base_img = page.parent.extract_image(xref)
            ext = base_img.get("ext", "png")
            img_path = assets_dir / f"pdf_p{page_index}_img{img_idx}.{ext}"
            img_path.write_bytes(base_img["image"])
            asset_name = img_path.name

            prev_ctx, next_ctx, section_text = _extract_formula_context(
                sorted_ctx_blocks,
                ibbox,
                page_h_mm=page_h,
                prev_page_tail_text=prev_page_tail_text,
                next_page_head_text=next_page_head_text,
            )

            kind = classify_raster_image(
                img_path, ibbox, prev_text=prev_ctx, next_text=next_ctx
            )
            if kind == "formula":
                latex, ocr_src = recognize_formula_image(
                    img_path,
                    prev_text=prev_ctx,
                    next_text=next_ctx,
                    section_text=section_text,
                    doc_lexicon=doc_lexicon,
                )
                img_blocks.append(
                    DocBlock(
                        block_id="",
                        page_index=page_index,
                        type="formula_block",
                        bbox_mm=ibbox,
                        latex=latex,
                        image_path=str(img_path),
                        asset_name=asset_name,
                        ocr_source=ocr_src,
                    )
                )
            elif kind == "text_caption":
                cap_text = recognize_text_caption_image(
                    img_path, section_text=section_text, doc_lexicon=doc_lexicon
                )
                img_blocks.append(
                    DocBlock(
                        block_id="",
                        page_index=page_index,
                        type="caption",
                        bbox_mm=ibbox,
                        inlines=[TextInline(text=cap_text)] if cap_text else [],
                        image_path=str(img_path),
                        asset_name=asset_name,
                        ocr_source="rapidocr_caption",
                    )
                )
            else:
                img_blocks.append(
                    DocBlock(
                        block_id="",
                        page_index=page_index,
                        type="figure",
                        bbox_mm=ibbox,
                        image_path=str(img_path),
                        asset_name=asset_name,
                        image_render_mode="outline",
                        placement="inline",
                        image_align="center",
                        image_width_mm=w_mm,
                        image_height_mm=h_mm,
                        chart=ChartData(
                            chart_type="raster",
                            image_path=str(img_path),
                            extra={"origin": "pdf_raster"},
                        ),
                    )
                )
        except Exception as exc:
            logger.debug("Skipping PDF image xref=%s: %s", xref, exc)
    return img_blocks


def _sort_and_assign_page_block_ids(blocks: list[DocBlock]) -> None:
    """Sort blocks in reading order within each page and assign clean `p{page}-b{idx}` IDs."""
    blocks.sort(
        key=lambda blk: (
            blk.page_index if blk.page_index is not None else 0,
            round((blk.bbox_mm[1] if blk.bbox_mm else 0.0) / 4.0),
            blk.bbox_mm[0] if blk.bbox_mm else 0.0,
        )
    )
    counters: dict[int, int] = {}
    for blk in blocks:
        p = blk.page_index if blk.page_index is not None else 0
        idx = counters.get(p, 0)
        counters[p] = idx + 1
        blk.block_id = f"p{p}-b{idx}"


def _extract_page_fallback_pymupdf(
    page: fitz.Page,
    page_index: int,
    assets_dir: Path | None,
    *,
    prev_page_tail_text: str = "",
) -> list[DocBlock]:
    """Structured PyMuPDF fallback extraction for a single page (with paragraph reconstruction)."""
    blocks, chart_bboxes, _ = _extract_page_structure_pymupdf(page, page_index)
    doc_lex = build_cjk_lexicon(
        " ".join([prev_page_tail_text] + [_block_plain(b) for b in blocks if _block_plain(b)])
    )
    img_blocks = _extract_page_images_pymupdf(
        page,
        page_index,
        assets_dir,
        existing_blocks=blocks,
        chart_bboxes=chart_bboxes,
        prev_page_tail_text=prev_page_tail_text,
        doc_lexicon=doc_lex,
    )
    blocks.extend(img_blocks)
    _sort_and_assign_page_block_ids(blocks)
    return blocks


def parse_pdf(
    file_path: Path,
    *,
    doc_id: str,
    out_dir: Path | None = None,
    use_mineru: bool = True,
    progress_cb: ProgressHook | None = None,
    crop_rects_mm: dict[str, list[float]] | None = None,
    exclude_header_footer: bool = False,
) -> DocIR:
    """Parse a PDF using PyMuPDF 150-DPI rendering + MinerU pipeline (with graceful fallback)."""
    file_path = Path(file_path).resolve()
    sha256 = hashlib.sha256(file_path.read_bytes()).hexdigest()

    pages_dir: Path | None = None
    assets_dir: Path | None = None
    mineru_dir: Path | None = None
    if out_dir is not None:
        out_path = Path(out_dir)
        pages_dir = out_path / "pages"
        assets_dir = out_path / "assets"
        mineru_dir = out_path / "mineru"
        pages_dir.mkdir(parents=True, exist_ok=True)
        assets_dir.mkdir(parents=True, exist_ok=True)

    pdf_doc = fitz.open(str(file_path))
    pages_info: list[DocPageInfo] = []
    all_blocks: list[DocBlock] = []
    parser_name = "pymupdf-structured"

    try:
        page_count = len(pdf_doc)
        total_chars = 0

        # Step 1: Render 150 DPI page underlays & collect page dimensions
        zoom = 150.0 / 72.0
        mat = fitz.Matrix(zoom, zoom)
        for pidx in range(page_count):
            page = pdf_doc[pidx]
            w_mm = round(float(page.rect.width) * PT_TO_MM, 2)
            h_mm = round(float(page.rect.height) * PT_TO_MM, 2)
            img_rel: str | None = None
            if pages_dir is not None:
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img_file = pages_dir / f"{pidx}.png"
                pix.save(str(img_file))
                img_rel = f"pages/{pidx}.png"
            pages_info.append(
                DocPageInfo(page_index=pidx, width_mm=w_mm, height_mm=h_mm, image=img_rel)
            )
            total_chars += len(page.get_text("text").strip())
            if progress_cb is not None:
                pct = 0.05 + 0.15 * ((pidx + 1) / max(1, page_count))
                progress_cb(
                    "convert",
                    pct,
                    pidx + 1,
                    page_count,
                    f"已渲染底图 {pidx + 1}/{page_count} 页 (150 DPI)",
                )

        # Step 2: Attempt MinerU `pipeline` backend when installed (unless per-page crop filtering overrides heavily)
        mineru_ok = False
        if use_mineru and page_count > 0:
            method = "txt" if (total_chars / max(1, page_count)) >= 25 else "ocr"
            try:
                mineru_res = run_mineru_pipeline(
                    file_path,
                    work_dir=mineru_dir,
                    backend="pipeline",
                    method=method,
                    progress_cb=progress_cb,
                )
                adapted = _adapt_mineru_result(mineru_res, pdf_doc, pages_info)
                if adapted:
                    if crop_rects_mm:
                        adapted = [
                            b
                            for b in adapted
                            if _bbox_center_in_crop(
                                b.bbox_mm,
                                _resolve_crop_rect(crop_rects_mm, b.page_index if b.page_index is not None else 0),
                            )
                        ]
                    if exclude_header_footer:
                        adapted = [
                            b
                            for b in adapted
                            if b.type not in {"header", "footer", "page_number", "discarded"}
                        ]
                    all_blocks = adapted
                    parser_name = (
                        "mineru-2.x/pipeline-cpu"
                        if mineru_res.used_cpu_fallback
                        else mineru_res.parser_name
                    )
                    mineru_ok = True
            except MinerUUnavailableError as exc:
                logger.info("%s", exc)
            except MinerUExecutionError as exc:
                logger.warning("MinerU pipeline execution failed; using PyMuPDF fallback: %s", exc)

        # Step 3: Two-pass PyMuPDF structured fallback (paragraphs + document lexicon first, then formula/caption OCR)
        if not mineru_ok:
            per_page_struct: list[tuple[list[DocBlock], list[list[float]], PageTypographyProfile]] = []
            prev_prof: PageTypographyProfile | None = None
            for pidx in range(page_count):
                if progress_cb is not None:
                    pct = 0.22 + 0.30 * ((pidx + 1) / max(1, page_count))
                    progress_cb(
                        "assemble",
                        pct,
                        pidx + 1,
                        page_count,
                        f"正在重建第 {pidx + 1}/{page_count} 页段落结构",
                    )
                crop_mm = _resolve_crop_rect(crop_rects_mm, pidx)
                p_blocks, chart_bbs, prof = _extract_page_structure_pymupdf(
                    pdf_doc[pidx],
                    pidx,
                    fallback_profile=prev_prof,
                    crop_rect_mm=crop_mm,
                    exclude_header_footer=exclude_header_footer,
                )
                prev_prof = prof
                per_page_struct.append((p_blocks, chart_bbs, prof))

            # Build document-wide CJK lexicon across all extracted text blocks for robust caption/formula verification
            doc_prose = "\n".join(
                _block_plain(blk)
                for p_blks, _, _ in per_page_struct
                for blk in p_blks
                if blk.type in {"paragraph", "heading", "list_item", "caption", "table"} and _block_plain(blk)
            )
            doc_lexicon = build_cjk_lexicon(doc_prose)

            # Pass B: Classify & OCR embedded raster formulas / captions with full local + doc lexicon context
            page_text_summaries: list[list[str]] = []
            for p_blks, _, _ in per_page_struct:
                t_list = [
                    _block_plain(b)
                    for b in p_blks
                    if b.type in {"paragraph", "heading", "list_item"} and _block_plain(b)
                ]
                page_text_summaries.append(t_list)

            for pidx in range(page_count):
                if progress_cb is not None:
                    pct = 0.52 + 0.38 * ((pidx + 1) / max(1, page_count))
                    progress_cb(
                        "assemble",
                        pct,
                        pidx + 1,
                        page_count,
                        f"正在识别第 {pidx + 1}/{page_count} 页公式与图表",
                    )
                p_blocks, chart_bbs, _ = per_page_struct[pidx]
                prev_tail = " ".join(page_text_summaries[pidx - 1][-3:]) if pidx > 0 and page_text_summaries[pidx - 1] else ""
                next_head = " ".join(page_text_summaries[pidx + 1][:6]) if (pidx + 1) < page_count and page_text_summaries[pidx + 1] else ""
                crop_mm = _resolve_crop_rect(crop_rects_mm, pidx)
                img_blocks = _extract_page_images_pymupdf(
                    pdf_doc[pidx],
                    pidx,
                    assets_dir,
                    existing_blocks=p_blocks,
                    chart_bboxes=chart_bbs,
                    prev_page_tail_text=prev_tail,
                    next_page_head_text=next_head,
                    doc_lexicon=doc_lexicon,
                    crop_rect_mm=crop_mm,
                )
                p_blocks.extend(img_blocks)
                p_blocks.sort(
                    key=lambda blk: (
                        round((blk.bbox_mm[1] if blk.bbox_mm else 0.0) / 4.0),
                        blk.bbox_mm[0] if blk.bbox_mm else 0.0,
                    )
                )
                all_blocks.extend(p_blocks)

            profiles_map = {pidx: per_page_struct[pidx][2] for pidx in range(page_count)}
            all_blocks = merge_cross_page_paragraphs(all_blocks, profiles_map)
            _sort_and_assign_page_block_ids(all_blocks)

        for order, blk in enumerate(all_blocks):
            blk.reading_order = order

        if progress_cb is not None:
            progress_cb("done", 1.0, page_count, page_count, f"PDF 解析完成 ({parser_name})")
    finally:
        pdf_doc.close()

    return DocIR(
        doc_id=doc_id,
        source=DocSource(
            type="pdf",
            filename=file_path.name,
            sha256=sha256,
            parser=parser_name,
        ),
        pages=pages_info,
        blocks=all_blocks,
    )
