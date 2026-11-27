"""Bidirectional DocIR <-> Markdown codec supporting editable documents, math, tables, and images."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import uuid

from PIL import Image

from handwrite.docparse.docir import (
    BreakInline,
    ChartData,
    DocBlock,
    DocInline,
    DocIR,
    DocLine,
    DocPageInfo,
    MathInline,
    TableCell,
    TableData,
    TextInline,
)
from handwrite.docparse.inline_math import split_inline_math

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST_RE = re.compile(
    r"^(?:[-*•+·]\s+|[（(]\s*\d{1,3}\s*[)）]\s*|\d{1,3}[.、)）．]\s*|[a-zA-Z][)）]\s+)(.*)$"
)
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)+\|?\s*$")
_QUOTE_RE = re.compile(r"^>\s*(.*)$")
_FORMULA_META_RE = re.compile(r"^<!--\s*hw:formula\b([^>]*)-->$")
_TABLE_META_RE = re.compile(r"^<!--\s*hw:table\b([^>]*)-->$")
_IMAGE_LINE_RE = re.compile(
    r"^!\[([^\]]*)\]\(([^)]+)\)(?:\{([^}]*)\})?\s*$"
)
_KV_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)=([^\s}]+)")

_VALID_RENDER_MODES = frozenset({"inherit", "major_outline", "outline", "hatch", "crosshatch", "sketch", "skip"})
_VALID_PLACEMENTS = frozenset({"inline", "float"})
_VALID_ALIGNS = frozenset({"left", "center", "right"})
_VALID_TABLE_STYLES = frozenset({"grid", "compact", "three_line", "horizontal", "dashed", "minimal", "none"})


def sanitize_asset_name(raw_name: str | None) -> str | None:
    """Validate and return a single-segment safe filename inside a document's assets directory."""
    if not raw_name:
        return None
    cleaned = str(raw_name).strip()
    if not cleaned or cleaned.startswith("http"):
        return None
    if cleaned.startswith("asset://"):
        cleaned = cleaned[len("asset://") :]
    cleaned = Path(cleaned).name
    if not cleaned or cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,160}", cleaned):
        return None
    return cleaned


def resolve_safe_asset_path(
    asset_name: str | None,
    assets_dir: Path | None,
    fallback_path: str | None = None,
) -> Path | None:
    """Resolve an asset path strictly confined within `assets_dir` (or verify `fallback_path`)."""
    safe_name = sanitize_asset_name(asset_name)
    if safe_name and assets_dir is not None:
        base = assets_dir.resolve()
        cand = (base / safe_name).resolve()
        if cand.is_relative_to(base) and cand.is_file():
            return cand
    if fallback_path:
        cand = Path(fallback_path).resolve()
        if assets_dir is not None:
            base = assets_dir.resolve()
            if cand.is_relative_to(base) and cand.is_file():
                return cand
        elif cand.is_file():
            return cand
    return None


def _inlines_to_markdown(inlines: list[DocInline]) -> str:
    parts: list[str] = []
    for inl in inlines:
        if isinstance(inl, TextInline):
            t = inl.text or ""
            if inl.bold and t.strip():
                t = f"**{t}**"
            elif inl.italic and t.strip():
                t = f"*{t}*"
            parts.append(t)
        elif isinstance(inl, MathInline):
            parts.append(f"${inl.latex}$")
        elif isinstance(inl, BreakInline):
            parts.append("  \n")
    return "".join(parts).strip()


def _parse_inline_formatting(text: str) -> list[DocInline]:
    """Split inline math and basic `**bold**` / `*italic*` markers into `DocInline` items."""
    out: list[DocInline] = []
    for token in split_inline_math(text):
        if isinstance(token, MathInline) or isinstance(token, BreakInline):
            out.append(token)
            continue
        raw = token.text
        pos = 0
        for m in re.finditer(r"\*\*(.+?)\*\*|\*(.+?)\*", raw):
            if m.start() > pos:
                chunk = raw[pos : m.start()]
                if chunk:
                    out.append(TextInline(text=chunk))
            if m.group(1) is not None:
                out.append(TextInline(text=m.group(1), bold=True))
            elif m.group(2) is not None:
                out.append(TextInline(text=m.group(2), italic=True))
            pos = m.end()
        if pos < len(raw):
            tail = raw[pos:]
            if tail:
                out.append(TextInline(text=tail))
    return out


def _split_md_table_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [cell.strip() for cell in s.split("|")]


def _format_image_attr(block: DocBlock) -> str:
    attrs: list[str] = [f"id={block.block_id}"]
    if block.image_render_mode and block.image_render_mode != "inherit":
        attrs.append(f"mode={block.image_render_mode}")
    if block.placement and block.placement != "inline":
        attrs.append(f"placement={block.placement}")
    if block.image_align and block.image_align != "center":
        attrs.append(f"align={block.image_align}")
    if block.image_width_mm is not None:
        attrs.append(f"w={block.image_width_mm:.1f}")
    if block.image_height_mm is not None:
        attrs.append(f"h={block.image_height_mm:.1f}")
    if block.placement == "float" and block.float_box_mm and len(block.float_box_mm) == 4:
        pno = (block.page_index or 0) + 1
        attrs.append(f"page={pno}")
        attrs.append(f"x={block.float_box_mm[0]:.1f}")
        attrs.append(f"y={block.float_box_mm[1]:.1f}")
        if block.image_width_mm is None:
            attrs.append(f"w={max(6.0, block.float_box_mm[2] - block.float_box_mm[0]):.1f}")
        if block.image_height_mm is None:
            attrs.append(f"h={max(6.0, block.float_box_mm[3] - block.float_box_mm[1]):.1f}")
    return " ".join(attrs)


def docir_to_markdown(doc: DocIR, *, include_headers_footers: bool = False) -> str:
    """Serialize a `DocIR` into editable Markdown preserving formulas, tables, and image metadata."""
    lines_out: list[str] = []
    ordered = sorted(doc.blocks, key=lambda b: b.reading_order)

    for blk in ordered:
        if blk.type == "discarded":
            continue
        if not include_headers_footers and blk.type in {"header", "footer", "page_number"}:
            continue

        if blk.type == "heading":
            lvl = max(1, min(6, int(blk.level or 1)))
            txt = _inlines_to_markdown(blk.inlines)
            if txt:
                lines_out.append(f"{'#' * lvl} {txt}")
                lines_out.append("")
            continue

        if blk.type == "paragraph":
            txt = _inlines_to_markdown(blk.inlines)
            if txt:
                lines_out.append(txt)
                lines_out.append("")
            continue

        if blk.type == "list_item":
            chunks: list[list[DocInline]] = [[]]
            for inl in blk.inlines:
                if isinstance(inl, BreakInline):
                    if chunks[-1]:
                        chunks.append([])
                else:
                    chunks[-1].append(inl)
            emitted_any = False
            for ch in chunks:
                txt = _inlines_to_markdown(ch)
                if not txt:
                    continue
                if _LIST_RE.match(txt):
                    lines_out.append(txt)
                else:
                    lines_out.append(f"- {txt}")
                emitted_any = True
            if emitted_any:
                lines_out.append("")
            continue

        if blk.type == "caption":
            txt = _inlines_to_markdown(blk.inlines)
            if txt:
                lines_out.append(f"> {txt}")
                lines_out.append("")
            continue

        if blk.type == "formula_block":
            tex = (blk.latex or "").strip()
            if tex:
                asset = blk.asset_name or (Path(blk.image_path).name if blk.image_path else None)
                if asset:
                    lines_out.append(f"<!-- hw:formula id={blk.block_id} asset={asset} -->")
                lines_out.append("$$")
                lines_out.append(tex)
                lines_out.append("$$")
                lines_out.append("")
            continue

        if blk.type == "table" and blk.table is not None:
            t_attrs: list[str] = []
            if blk.table.border_style:
                t_attrs.append(f"style={blk.table.border_style}")
            if blk.table.width_ratio is not None:
                t_attrs.append(f"width={blk.table.width_ratio:.2f}")
            if blk.table.align:
                t_attrs.append(f"align={blk.table.align}")
            if t_attrs:
                lines_out.append(f"<!-- hw:table {' '.join(t_attrs)} -->")
            rows_cnt = max(1, blk.table.rows)
            cols_cnt = max(1, blk.table.cols)
            grid = [["" for _ in range(cols_cnt)] for _ in range(rows_cnt)]
            for cell in blk.table.cells:
                if 0 <= cell.r < rows_cnt and 0 <= cell.c < cols_cnt:
                    txt = _inlines_to_markdown(cell.inlines).replace("\n", "<br>").replace("|", "\\|")
                    grid[cell.r][cell.c] = txt
            lines_out.append("| " + " | ".join(grid[0]) + " |")
            lines_out.append("| " + " | ".join(["---"] * cols_cnt) + " |")
            for r_idx in range(1, rows_cnt):
                lines_out.append("| " + " | ".join(grid[r_idx]) + " |")
            lines_out.append("")
            continue

        if blk.type in {"figure", "chart"}:
            asset = blk.asset_name or (Path(blk.image_path).name if blk.image_path else None)
            if not asset and blk.chart and blk.chart.image_path:
                asset = Path(blk.chart.image_path).name
            target = f"asset://{asset}" if asset else f"chart://{blk.block_id}"
            alt = blk.alt_text or (blk.chart.title if blk.chart else "") or ("配图" if blk.type == "figure" else "图表")
            attr_str = _format_image_attr(blk)
            lines_out.append(f"![{alt}]({target}){{{attr_str}}}")
            lines_out.append("")
            continue

    while lines_out and lines_out[-1] == "":
        lines_out.pop()
    return "\n".join(lines_out)


def compute_docir_sha256(doc: DocIR) -> str:
    """Compute a deterministic hash covering current blocks so layout cache invalidates on edits."""
    payload = doc.model_dump_json(include={"pages", "blocks"})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def markdown_to_docir(
    markdown: str,
    base_doc: DocIR,
    *,
    assets_dir: Path | None = None,
) -> DocIR:
    """Parse edited Markdown back into `DocIR`, preserving trusted assets and chart structures."""
    by_id: dict[str, DocBlock] = {b.block_id: b for b in base_doc.blocks}
    by_asset: dict[str, DocBlock] = {}
    for b in base_doc.blocks:
        aname = b.asset_name or (Path(b.image_path).name if b.image_path else None)
        if aname:
            by_asset.setdefault(aname, b)

    raw_lines = (markdown or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[DocBlock] = []
    cursor_y = 22.0
    used_ids: set[str] = set()

    def _next_id(preferred: str | None = None) -> str:
        if preferred and re.fullmatch(r"[A-Za-z0-9_.\-:]{1,64}", preferred) and preferred not in used_ids:
            used_ids.add(preferred)
            return preferred
        candidate = f"ed-{len(blocks)}-{uuid.uuid4().hex[:4]}"
        while candidate in used_ids:
            candidate = f"ed-{len(blocks)}-{uuid.uuid4().hex[:6]}"
        used_ids.add(candidate)
        return candidate

    def _alloc_bbox(est_h: float, prev: DocBlock | None = None) -> list[float]:
        nonlocal cursor_y
        if prev and prev.bbox_mm and len(prev.bbox_mm) == 4:
            return list(prev.bbox_mm)
        y0 = round(cursor_y, 2)
        y1 = round(min(282.0, y0 + est_h), 2)
        cursor_y = min(275.0, y1 + 3.0)
        return [20.0, y0, 190.0, y1]

    para_buf: list[str] = []
    pending_formula_meta: dict[str, str] = {}
    pending_table_meta: dict[str, str] = {}
    prev_was_list = False

    def _flush_para() -> None:
        nonlocal para_buf
        if not para_buf:
            return
        segments: list[str] = [""]
        for raw_ln in para_buf:
            has_hard_break = raw_ln.endswith("  ")
            clean = raw_ln.strip()
            if not clean:
                continue
            if not segments[-1]:
                segments[-1] = clean
            else:
                a = segments[-1]
                if a[-1].isascii() and a[-1].isalnum() and clean[0].isascii() and clean[0].isalnum():
                    segments[-1] = f"{a} {clean}"
                else:
                    segments[-1] = f"{a}{clean}"
            if has_hard_break:
                segments.append("")
        para_buf = []
        segments = [s for s in segments if s]
        if not segments:
            return
        inlines: list[DocInline] = []
        doc_lines: list[DocLine] = []
        for s_idx, seg in enumerate(segments):
            seg_inlines = _parse_inline_formatting(seg)
            if s_idx > 0:
                inlines.append(BreakInline())
            inlines.extend(seg_inlines)
            doc_lines.append(DocLine(bbox_mm=None, inlines=seg_inlines))
        est_lines = max(len(segments), (sum(len(s) for s in segments) // 26) + 1)
        bid = _next_id()
        bbox = _alloc_bbox(est_lines * 8.5)
        for dl in doc_lines:
            dl.bbox_mm = list(bbox)
        blocks.append(
            DocBlock(
                block_id=bid,
                page_index=0,
                type="paragraph",
                reading_order=len(blocks),
                bbox_mm=bbox,
                lines=doc_lines,
                inlines=inlines,
            )
        )

    i = 0
    n = len(raw_lines)
    while i < n:
        line = raw_lines[i]
        stripped = line.strip()

        if not stripped:
            _flush_para()
            prev_was_list = False
            i += 1
            continue

        # Formula metadata HTML comment preceding `$$`
        fm = _FORMULA_META_RE.match(stripped)
        if fm:
            _flush_para()
            prev_was_list = False
            pending_formula_meta = {m.group(1): m.group(2) for m in _KV_RE.finditer(fm.group(1))}
            i += 1
            continue

        # Table metadata HTML comment preceding `| ... |`
        tm = _TABLE_META_RE.match(stripped)
        if tm:
            _flush_para()
            prev_was_list = False
            pending_table_meta = {m.group(1): m.group(2) for m in _KV_RE.finditer(tm.group(1))}
            i += 1
            continue

        # 1. Display math block `$$ ... $$`
        if stripped.startswith("$$"):
            _flush_para()
            if stripped.endswith("$$") and len(stripped) >= 4:
                tex = stripped[2:-2].strip()
                i += 1
            else:
                math_parts = [stripped[2:]] if len(stripped) > 2 else []
                i += 1
                while i < n:
                    cur = raw_lines[i].strip()
                    if cur.endswith("$$"):
                        if len(cur) > 2:
                            math_parts.append(cur[:-2])
                        i += 1
                        break
                    math_parts.append(cur)
                    i += 1
                tex = " ".join(p.strip() for p in math_parts if p.strip()).strip()

            pref_id = pending_formula_meta.get("id")
            pref_asset = sanitize_asset_name(pending_formula_meta.get("asset"))
            pending_formula_meta = {}
            orig = (by_id.get(pref_id) if pref_id else None) or (by_asset.get(pref_asset) if pref_asset else None)
            if tex:
                img_p = resolve_safe_asset_path(
                    pref_asset or (orig.asset_name if orig else None),
                    assets_dir,
                    orig.image_path if orig else None,
                )
                blocks.append(
                    DocBlock(
                        block_id=_next_id(pref_id),
                        page_index=orig.page_index if orig else 0,
                        type="formula_block",
                        reading_order=len(blocks),
                        bbox_mm=_alloc_bbox(16.0, orig),
                        latex=tex,
                        image_path=str(img_p) if img_p else None,
                        asset_name=pref_asset or (img_p.name if img_p else None),
                        ocr_source="manual" if orig and orig.latex != tex else (orig.ocr_source if orig else "manual"),
                    )
                )
            prev_was_list = False
            pending_table_meta = {}
            continue

        pending_formula_meta = {}

        # 2. Markdown image / chart `![alt](target){id=... mode=...}`
        im = _IMAGE_LINE_RE.match(stripped)
        if im:
            _flush_para()
            alt = im.group(1).strip()
            target = im.group(2).strip()
            attr_str = im.group(3) or ""
            kvs = {m.group(1): m.group(2) for m in _KV_RE.finditer(attr_str)}

            pref_id = kvs.get("id")
            orig = by_id.get(pref_id) if pref_id else None
            safe_asset = sanitize_asset_name(target)
            if orig is None and safe_asset:
                orig = by_asset.get(safe_asset)

            resolved_img = resolve_safe_asset_path(
                safe_asset or (orig.asset_name if orig else None),
                assets_dir,
                orig.image_path if orig else None,
            )
            btype = orig.type if orig and orig.type in {"figure", "chart"} else "figure"
            render_mode = kvs.get("mode", orig.image_render_mode if orig else "inherit")
            if render_mode not in _VALID_RENDER_MODES:
                render_mode = "inherit"
            placement = kvs.get("placement", orig.placement if orig else "inline")
            if placement not in _VALID_PLACEMENTS:
                placement = "inline"
            align = kvs.get("align", orig.image_align if orig else "center")
            if align not in _VALID_ALIGNS:
                align = "center"

            def _opt_float(key: str, fallback: float | None, lo: float, hi: float) -> float | None:
                if key in kvs:
                    try:
                        return max(lo, min(hi, float(kvs[key])))
                    except ValueError:
                        return fallback
                return fallback

            img_w = _opt_float("w", orig.image_width_mm if orig else None, 6.0, 400.0)
            img_h = _opt_float("h", orig.image_height_mm if orig else None, 6.0, 400.0)
            pidx = orig.page_index if orig and orig.page_index is not None else 0
            if "page" in kvs:
                try:
                    pidx = max(0, int(kvs["page"]) - 1)
                except ValueError:
                    pass

            float_box = list(orig.float_box_mm) if orig and orig.float_box_mm else None
            if placement == "float" and ("x" in kvs or "y" in kvs or float_box is None):
                fx = _opt_float("x", float_box[0] if float_box else 35.0, 0.0, 500.0) or 35.0
                fy = _opt_float("y", float_box[1] if float_box else 50.0, 0.0, 500.0) or 50.0
                fw = img_w or (float_box[2] - float_box[0] if float_box else 85.0)
                fh = img_h or (float_box[3] - float_box[1] if float_box else 55.0)
                float_box = [round(fx, 2), round(fy, 2), round(fx + fw, 2), round(fy + fh, 2)]

            chart_obj = orig.chart.model_copy(deep=True) if orig and orig.chart else None
            if resolved_img is not None:
                if chart_obj is None:
                    chart_obj = ChartData(chart_type="raster", image_path=str(resolved_img))
                else:
                    chart_obj.image_path = str(resolved_img)

            # Infer physical dimensions if missing from disk image
            if img_w is None and orig and orig.bbox_mm and len(orig.bbox_mm) == 4:
                img_w = round(max(10.0, orig.bbox_mm[2] - orig.bbox_mm[0]), 1)
                img_h = img_h or round(max(10.0, orig.bbox_mm[3] - orig.bbox_mm[1]), 1)
            elif img_w is None and resolved_img is not None:
                try:
                    with Image.open(resolved_img) as pil_im:
                        iw, ih = pil_im.size
                        img_w = round(min(135.0, max(24.0, iw * 0.17)), 1)
                        img_h = round(img_w * (ih / max(1, iw)), 1)
                except Exception:
                    pass

            blocks.append(
                DocBlock(
                    block_id=_next_id(pref_id),
                    page_index=pidx,
                    type=btype,  # type: ignore[arg-type]
                    reading_order=len(blocks),
                    bbox_mm=float_box or _alloc_bbox(img_h or 55.0, orig),
                    chart=chart_obj,
                    image_path=str(resolved_img) if resolved_img else (orig.image_path if orig else None),
                    asset_name=resolved_img.name if resolved_img else safe_asset,
                    image_render_mode=render_mode,  # type: ignore[arg-type]
                    placement=placement,  # type: ignore[arg-type]
                    image_align=align,  # type: ignore[arg-type]
                    image_width_mm=img_w,
                    image_height_mm=img_h,
                    float_box_mm=float_box,
                    alt_text=alt,
                )
            )
            i += 1
            continue

        # 3. Heading `# ...`
        hm = _HEADING_RE.match(stripped)
        if hm:
            _flush_para()
            lvl = max(1, min(6, len(hm.group(1))))
            htext = hm.group(2).strip()
            if htext:
                inlines = _parse_inline_formatting(htext)
                bbox = _alloc_bbox(10.5)
                blocks.append(
                    DocBlock(
                        block_id=_next_id(),
                        page_index=0,
                        type="heading",
                        reading_order=len(blocks),
                        level=lvl,
                        bbox_mm=bbox,
                        lines=[DocLine(bbox_mm=bbox, inlines=inlines)],
                        inlines=inlines,
                    )
                )
            i += 1
            continue

        # 4. Pipe Table
        if "|" in stripped and (i + 1) < n and _TABLE_SEP_RE.match(raw_lines[i + 1]):
            _flush_para()
            prev_was_list = False
            t_meta = pending_table_meta
            pending_table_meta = {}
            header_cells = _split_md_table_row(stripped)
            table_rows: list[list[str]] = [header_cells]
            i += 2
            while i < n and "|" in raw_lines[i].strip() and raw_lines[i].strip():
                table_rows.append(_split_md_table_row(raw_lines[i]))
                i += 1
            ncols = max(len(r) for r in table_rows)
            if ncols > 0:
                cells: list[TableCell] = []
                for r_i, row in enumerate(table_rows):
                    for c_i in range(ncols):
                        val = row[c_i] if c_i < len(row) else ""
                        val = val.replace("<br>", "\n").replace("\\|", "|")
                        cells.append(
                            TableCell(
                                r=r_i,
                                c=c_i,
                                rs=1,
                                cs=1,
                                inlines=_parse_inline_formatting(val) if val else [],
                            )
                        )
                col_w = round(170.0 / ncols, 2)
                t_style = t_meta.get("style")
                t_style_val = t_style if t_style in _VALID_TABLE_STYLES else None
                t_width_val: float | None = None
                if "width" in t_meta:
                    try:
                        t_width_val = max(0.4, min(1.0, float(t_meta["width"])))
                    except ValueError:
                        pass
                t_align = t_meta.get("align")
                t_align_val = t_align if t_align in _VALID_ALIGNS else None
                tdata = TableData(
                    rows=len(table_rows),
                    cols=ncols,
                    col_widths_mm=[col_w] * ncols,
                    cells=cells,
                    border_style=t_style_val,  # type: ignore[arg-type]
                    width_ratio=t_width_val,
                    align=t_align_val,  # type: ignore[arg-type]
                )
                blocks.append(
                    DocBlock(
                        block_id=_next_id(),
                        page_index=0,
                        type="table",
                        reading_order=len(blocks),
                        bbox_mm=_alloc_bbox(max(18.0, len(table_rows) * 10.0)),
                        table=tdata,
                    )
                )
            continue

        pending_table_meta = {}

        # 5. Blockquote -> caption
        qm = _QUOTE_RE.match(stripped)
        if qm:
            _flush_para()
            prev_was_list = False
            qtxt = qm.group(1).strip()
            if qtxt:
                inlines = _parse_inline_formatting(qtxt)
                bbox = _alloc_bbox(8.0)
                blocks.append(
                    DocBlock(
                        block_id=_next_id(),
                        page_index=0,
                        type="caption",
                        reading_order=len(blocks),
                        bbox_mm=bbox,
                        lines=[DocLine(bbox_mm=bbox, inlines=inlines)],
                        inlines=inlines,
                    )
                )
            i += 1
            continue

        # 6. List item (merge consecutive lines without intervening blank line into one list block)
        lm = _LIST_RE.match(stripped)
        if lm:
            _flush_para()
            inlines = _parse_inline_formatting(stripped)
            bbox = _alloc_bbox(9.0)
            if prev_was_list and blocks and blocks[-1].type == "list_item":
                blocks[-1].inlines.append(BreakInline())
                blocks[-1].inlines.extend(inlines)
                blocks[-1].lines.append(DocLine(bbox_mm=bbox, inlines=inlines))
            else:
                blocks.append(
                    DocBlock(
                        block_id=_next_id(),
                        page_index=0,
                        type="list_item",
                        reading_order=len(blocks),
                        bbox_mm=bbox,
                        lines=[DocLine(bbox_mm=bbox, inlines=inlines)],
                        inlines=inlines,
                    )
                )
            prev_was_list = True
            i += 1
            continue

        # 7. Normal paragraph line (preserve trailing two-space hard line break)
        prev_was_list = False
        raw_para_line = line.rstrip("\r\n")
        if raw_para_line.endswith("  "):
            para_buf.append(stripped + "  ")
        else:
            para_buf.append(stripped)
        i += 1

    _flush_para()

    preserved_hidden = [
        b.model_copy(deep=True)
        for b in base_doc.blocks
        if b.type in {"header", "footer", "page_number"}
    ]
    all_blocks = blocks + preserved_hidden
    for idx, blk in enumerate(all_blocks):
        blk.reading_order = idx

    next_doc = DocIR(
        doc_id=base_doc.doc_id,
        source=base_doc.source.model_copy(deep=True),
        pages=[p.model_copy(deep=True) for p in base_doc.pages] or [DocPageInfo(page_index=0)],
        blocks=all_blocks,
    )
    next_doc.source.sha256 = compute_docir_sha256(next_doc)
    return next_doc
