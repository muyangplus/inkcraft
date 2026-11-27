"""Pure-Python python-docx + lxml parser with OMML->LaTeX, merged tables, charts, and images."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
import re
from typing import Callable

from docx import Document
from lxml import etree

from inkcraft.docparse.docir import (
    BreakInline,
    ChartData,
    DocBlock,
    DocIR,
    DocPageInfo,
    DocSource,
    MathInline,
    TextInline,
)
from inkcraft.docparse.docx_chart import parse_drawingml_chart_xml
from inkcraft.docparse.docx_omml import (
    A_NS,
    C_NS,
    M_NS,
    NS,
    R_NS,
    TWIP_TO_MM,
    W_NS,
    omml_to_latex,
    xml_local_tag,
)
from inkcraft.docparse.inline_math import normalize_symbol_def_inlines
from inkcraft.docparse.docx_table import (
    detect_heading_level,
    extract_inlines_from_p,
    is_list_paragraph,
    parse_table_elem,
)
from inkcraft.docparse.formula_ocr import (
    classify_raster_image,
    recognize_formula_image,
    recognize_text_caption_image,
)

logger = logging.getLogger(__name__)

ProgressHook = Callable[[str, float, int, int, str], None]


def _extract_page_dimensions(doc: Document) -> tuple[float, float]:
    width_mm, height_mm = 210.0, 297.0
    try:
        if doc.sections:
            sec = doc.sections[0]
            if sec.page_width is not None:
                width_mm = round(sec.page_width.mm, 2)
            if sec.page_height is not None:
                height_mm = round(sec.page_height.mm, 2)
    except Exception:
        pass
    return width_mm, height_mm


def _sanitize_image_ext(partname: str) -> str:
    raw_ext = Path(str(partname)).suffix.lower()
    cleaned = re.sub(r"[^.a-zA-Z0-9]", "", raw_ext)[:10]
    if cleaned and cleaned.startswith(".") and len(cleaned) > 1:
        return cleaned
    return ".png"


def parse_docx(
    file_path: Path,
    *,
    doc_id: str,
    out_dir: Path | None = None,
    progress_cb: ProgressHook | None = None,
) -> DocIR:
    """Parse a `.docx` file into a structured `DocIR`."""
    file_path = Path(file_path).resolve()
    sha256 = hashlib.sha256(file_path.read_bytes()).hexdigest()

    if progress_cb is not None:
        progress_cb("convert", 0.1, 0, 1, f"正在解析 DOCX: {file_path.name}")

    doc = Document(str(file_path))
    width_mm, height_mm = _extract_page_dimensions(doc)
    part = doc.part
    rels = part.rels

    assets_dir: Path | None = None
    if out_dir is not None:
        assets_dir = Path(out_dir) / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

    blocks: list[DocBlock] = []
    block_idx = 0
    cursor_y = 22.0
    content_w = max(80.0, width_mm - 40.0)
    margin_x = 20.0

    def _next_block_id() -> str:
        nonlocal block_idx
        bid = f"p0-b{block_idx}"
        block_idx += 1
        return bid

    def _alloc_bbox(est_h: float) -> list[float]:
        nonlocal cursor_y
        y0 = cursor_y
        y1 = min(height_mm - 15.0, y0 + est_h)
        cursor_y = y1 + 3.0
        return [round(margin_x, 2), round(y0, 2), round(margin_x + content_w, 2), round(y1, 2)]

    body = doc.element.body
    children = list(body)
    total_children = max(1, len(children))

    def _handle_element(elem: etree._Element) -> None:
        nonlocal block_idx
        if elem.tag == f"{W_NS}p":
            for chart_ref in elem.findall(f".//{C_NS}chart"):
                rid = chart_ref.get(f"{R_NS}id")
                if rid and rid in rels:
                    try:
                        chart_part = rels[rid].target_part
                        chart_data = parse_drawingml_chart_xml(chart_part.blob)
                        if chart_data is not None:
                            blocks.append(
                                DocBlock(
                                    block_id=_next_block_id(),
                                    page_index=0,
                                    type="chart",
                                    reading_order=len(blocks),
                                    bbox_mm=_alloc_bbox(62.0),
                                    chart=chart_data,
                                )
                            )
                    except Exception as exc:
                        logger.warning("Failed to parse DOCX chart rel %s: %s", rid, exc)

            for blip in elem.findall(f".//{A_NS}blip"):
                # Skip mc:Fallback raster duplicates when Word provides mc:Choice OMML/Drawing
                in_fallback = False
                anc = blip.getparent()
                while anc is not None and anc is not elem:
                    if xml_local_tag(anc.tag) == "Fallback":
                        in_fallback = True
                        break
                    anc = anc.getparent()
                if in_fallback:
                    continue

                rid = blip.get(f"{R_NS}embed")
                if rid and rid in rels and assets_dir is not None:
                    try:
                        img_part = rels[rid].target_part
                        ext = _sanitize_image_ext(str(img_part.partname))
                        img_file = assets_dir / f"docx_img_{block_idx}{ext}"
                        img_file.write_bytes(img_part.blob)
                        asset_name = img_file.name

                        # Extract physical extent in mm from wp:extent if present
                        w_mm: float = 55.0
                        h_mm: float | None = None
                        anc2 = blip.getparent()
                        while anc2 is not None and anc2 is not elem:
                            if xml_local_tag(anc2.tag) in {"inline", "anchor"}:
                                for sub in anc2:
                                    if xml_local_tag(sub.tag) == "extent":
                                        cx = sub.get("cx")
                                        cy = sub.get("cy")
                                        if cx and cx.isdigit():
                                            w_mm = round(max(8.0, int(cx) / 36000.0), 2)
                                        if cy and cy.isdigit():
                                            h_mm = round(max(4.0, int(cy) / 36000.0), 2)
                                        break
                                break
                            anc2 = anc2.getparent()

                        bbox_mm = _alloc_bbox(h_mm or 45.0)
                        if w_mm < bbox_mm[2] - bbox_mm[0]:
                            bbox_mm[2] = round(bbox_mm[0] + w_mm, 2)
                        prev_ctx = ""
                        for prev_b in reversed(blocks[-2:]):
                            if prev_b.inlines:
                                prev_ctx = " ".join(
                                    inl.text for inl in prev_b.inlines if isinstance(inl, TextInline)
                                ).strip()
                                if prev_ctx:
                                    break

                        kind = classify_raster_image(img_file, bbox_mm, prev_text=prev_ctx)
                        if kind == "formula":
                            latex, ocr_src = recognize_formula_image(img_file, prev_text=prev_ctx)
                            blocks.append(
                                DocBlock(
                                    block_id=_next_block_id(),
                                    page_index=0,
                                    type="formula_block",
                                    reading_order=len(blocks),
                                    bbox_mm=bbox_mm,
                                    latex=latex,
                                    image_path=str(img_file),
                                    asset_name=asset_name,
                                    ocr_source=ocr_src,
                                )
                            )
                        elif kind == "text_caption":
                            cap = recognize_text_caption_image(img_file)
                            blocks.append(
                                DocBlock(
                                    block_id=_next_block_id(),
                                    page_index=0,
                                    type="caption",
                                    reading_order=len(blocks),
                                    bbox_mm=bbox_mm,
                                    inlines=[TextInline(text=cap)] if cap else [],
                                    image_path=str(img_file),
                                    asset_name=asset_name,
                                    ocr_source="rapidocr_caption",
                                )
                            )
                        else:
                            blocks.append(
                                DocBlock(
                                    block_id=_next_block_id(),
                                    page_index=0,
                                    type="figure",
                                    reading_order=len(blocks),
                                    bbox_mm=bbox_mm,
                                    image_path=str(img_file),
                                    asset_name=asset_name,
                                    image_render_mode="outline",
                                    placement="inline",
                                    image_align="center",
                                    image_width_mm=w_mm,
                                    image_height_mm=h_mm,
                                    chart=ChartData(
                                        chart_type="raster",
                                        image_path=str(img_file),
                                        extra={"origin": "docx_image"},
                                    ),
                                )
                            )
                    except Exception as exc:
                        logger.warning("Failed to extract DOCX image rel %s: %s", rid, exc)

            omath_paras = elem.findall(f"{M_NS}oMathPara")
            inlines = extract_inlines_from_p(elem)
            if omath_paras and all(
                isinstance(inl, MathInline)
                or (isinstance(inl, TextInline) and not inl.text.strip())
                for inl in inlines
            ):
                latex_parts = [inl.latex for inl in inlines if isinstance(inl, MathInline)]
                if latex_parts:
                    blocks.append(
                        DocBlock(
                            block_id=_next_block_id(),
                            page_index=0,
                            type="formula_block",
                            reading_order=len(blocks),
                            bbox_mm=_alloc_bbox(16.0),
                            latex=" ".join(latex_parts),
                        )
                    )
                return

            non_ws = [
                inl
                for inl in inlines
                if not (isinstance(inl, TextInline) and not inl.text.strip())
                and not isinstance(inl, BreakInline)
            ]
            if len(non_ws) == 1 and isinstance(non_ws[0], MathInline):
                blocks.append(
                    DocBlock(
                        block_id=_next_block_id(),
                        page_index=0,
                        type="formula_block",
                        reading_order=len(blocks),
                        bbox_mm=_alloc_bbox(16.0),
                        latex=non_ws[0].latex,
                    )
                )
                return

            if not non_ws:
                return

            heading_level = detect_heading_level(elem)
            if heading_level is not None:
                blocks.append(
                    DocBlock(
                        block_id=_next_block_id(),
                        page_index=0,
                        type="heading",
                        reading_order=len(blocks),
                        level=heading_level,
                        bbox_mm=_alloc_bbox(11.0),
                        inlines=inlines,
                    )
                )
            elif is_list_paragraph(elem):
                blocks.append(
                    DocBlock(
                        block_id=_next_block_id(),
                        page_index=0,
                        type="list_item",
                        reading_order=len(blocks),
                        bbox_mm=_alloc_bbox(9.0),
                        inlines=inlines,
                    )
                )
            else:
                norm_inlines = normalize_symbol_def_inlines(inlines)
                text_len = sum(len(i.text) for i in norm_inlines if isinstance(i, TextInline))
                est_lines = max(1, (text_len // 26) + 1)
                blocks.append(
                    DocBlock(
                        block_id=_next_block_id(),
                        page_index=0,
                        type="paragraph",
                        reading_order=len(blocks),
                        bbox_mm=_alloc_bbox(est_lines * 9.0),
                        inlines=norm_inlines,
                    )
                )

        elif elem.tag == f"{W_NS}tbl":
            table_data = parse_table_elem(elem)
            if table_data is not None:
                est_h = max(18.0, table_data.rows * 10.0)
                blocks.append(
                    DocBlock(
                        block_id=_next_block_id(),
                        page_index=0,
                        type="table",
                        reading_order=len(blocks),
                        bbox_mm=_alloc_bbox(est_h),
                        table=table_data,
                    )
                )

        elif elem.tag == f"{W_NS}sdt":
            sdt_content = elem.find(f"{W_NS}sdtContent")
            if sdt_content is not None:
                for sub in sdt_content:
                    _handle_element(sub)

    for idx, child in enumerate(children):
        _handle_element(child)
        if progress_cb is not None and (idx % 20 == 0 or idx == total_children - 1):
            pct = 0.2 + 0.7 * ((idx + 1) / total_children)
            progress_cb("assemble", pct, 0, 1, f"正在解析 DOCX 结构 ({idx + 1}/{total_children})")

    if progress_cb is not None:
        progress_cb("done", 1.0, 1, 1, f"DOCX 解析完成，共 {len(blocks)} 个内容块")

    return DocIR(
        doc_id=doc_id,
        source=DocSource(
            type="docx",
            filename=file_path.name,
            sha256=sha256,
            parser="python-docx+lxml",
        ),
        pages=[DocPageInfo(page_index=0, width_mm=width_mm, height_mm=height_mm, image=None)],
        blocks=blocks,
    )


__all__ = [
    "NS",
    "ProgressHook",
    "TWIP_TO_MM",
    "omml_to_latex",
    "parse_docx",
    "parse_drawingml_chart_xml",
]
