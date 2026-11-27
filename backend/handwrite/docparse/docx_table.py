"""DOCX paragraph inline, heading, list, and table extraction helpers."""

from __future__ import annotations

import re

from lxml import etree

from handwrite.docparse.docir import (
    BreakInline,
    DocInline,
    MathInline,
    TableCell,
    TableData,
    TextInline,
)
from handwrite.docparse.docx_omml import (
    M_NS,
    TWIP_TO_MM,
    W_NS,
    clean_latex,
    omml_to_latex,
    xml_local_tag,
)
from handwrite.docparse.inline_math import (
    build_text_with_scripts,
    normalize_unambiguous_unit_powers,
    split_inline_math,
)


def _is_run_flag(rpr: etree._Element | None, tag_name: str) -> bool:
    if rpr is None:
        return False
    el = rpr.find(f"{W_NS}{tag_name}")
    if el is None:
        return False
    val = el.get(f"{W_NS}val")
    return val not in {"0", "false", "off"}


def _run_vert_align(rpr: etree._Element | None) -> str:
    if rpr is None:
        return "normal"
    el = rpr.find(f"{W_NS}vertAlign")
    if el is None:
        return "normal"
    val = (el.get(f"{W_NS}val") or "").lower()
    if val == "subscript":
        return "sub"
    if val == "superscript":
        return "sup"
    return "normal"


def extract_inlines_from_p(p_elem: etree._Element) -> list[DocInline]:
    """Extract mixed TextInline, MathInline (including sub/superscript runs), and BreakInline from `w:p`."""
    inlines: list[DocInline] = []
    pending_text_runs: list[tuple[str, str, bool, bool]] = []  # (text, script_role, bold, italic)

    def _append_text_direct(txt: str, bold: bool, italic: bool) -> None:
        if not txt:
            return
        if (
            inlines
            and isinstance(inlines[-1], TextInline)
            and inlines[-1].bold == bold
            and inlines[-1].italic == italic
        ):
            inlines[-1] = TextInline(
                text=inlines[-1].text + txt, bold=bold, italic=italic
            )
        else:
            inlines.append(TextInline(text=txt, bold=bold, italic=italic))

    def _flush_pending_text_runs() -> None:
        nonlocal pending_text_runs
        if not pending_text_runs:
            return
        has_script = any(role != "normal" for _, role, _, _ in pending_text_runs)
        if not has_script:
            for txt, _, bold, italic in pending_text_runs:
                norm_txt = normalize_unambiguous_unit_powers(txt)
                if "$" in norm_txt:
                    inlines.extend(split_inline_math(norm_txt))
                else:
                    _append_text_direct(norm_txt, bold, italic)
        else:
            combined = normalize_unambiguous_unit_powers(
                build_text_with_scripts([(txt, role) for txt, role, _, _ in pending_text_runs])
            )
            any_bold = all(b for txt, _, b, _ in pending_text_runs if txt.strip())
            for tok in split_inline_math(combined):
                if isinstance(tok, TextInline) and any_bold:
                    _append_text_direct(tok.text, True, False)
                else:
                    inlines.append(tok)
        pending_text_runs = []

    def _queue_text(txt: str, role: str, bold: bool, italic: bool) -> None:
        if not txt:
            return
        if (
            pending_text_runs
            and pending_text_runs[-1][1] == role
            and pending_text_runs[-1][2] == bold
            and pending_text_runs[-1][3] == italic
        ):
            prev_t, _, _, _ = pending_text_runs[-1]
            pending_text_runs[-1] = (prev_t + txt, role, bold, italic)
        else:
            pending_text_runs.append((txt, role, bold, italic))

    def _pick_alternate_branch(ac_node: etree._Element) -> etree._Element | None:
        choice = None
        fallback = None
        for ch in ac_node:
            t = xml_local_tag(ch.tag)
            if t == "Choice" and choice is None:
                choice = ch
            elif t == "Fallback" and fallback is None:
                fallback = ch
        return choice if choice is not None else fallback

    def _walk(node: etree._Element) -> None:
        for child in node:
            lt = xml_local_tag(child.tag)
            if lt == "AlternateContent":
                branch = _pick_alternate_branch(child)
                if branch is not None:
                    _walk(branch)
            elif child.tag == f"{W_NS}r":
                rpr = child.find(f"{W_NS}rPr")
                bold = _is_run_flag(rpr, "b")
                italic = _is_run_flag(rpr, "i")
                script_role = _run_vert_align(rpr)
                def _walk_run_children(parent_el: etree._Element) -> None:
                    for rc in parent_el:
                        rlt = xml_local_tag(rc.tag)
                        if rlt == "AlternateContent":
                            br = _pick_alternate_branch(rc)
                            if br is not None:
                                _walk_run_children(br)
                        elif rlt == "t" and rc.text:
                            _queue_text(rc.text, script_role, bold, italic)
                        elif rlt == "tab":
                            _queue_text("  ", "normal", bold, italic)
                        elif rlt in {"br", "cr"}:
                            _flush_pending_text_runs()
                            inlines.append(BreakInline())
                _walk_run_children(child)
            elif child.tag == f"{M_NS}oMath":
                _flush_pending_text_runs()
                tex = clean_latex(omml_to_latex(child))
                if tex:
                    inlines.append(MathInline(latex=tex))
            elif child.tag == f"{M_NS}oMathPara":
                _flush_pending_text_runs()
                for om in child.findall(f"{M_NS}oMath"):
                    tex = clean_latex(omml_to_latex(om))
                    if tex:
                        inlines.append(MathInline(latex=tex))
            elif lt in {"hyperlink", "smartTag", "sdt", "sdtContent", "ins", "Choice", "Fallback"}:
                _walk(child)

    _walk(p_elem)
    _flush_pending_text_runs()
    return inlines


def detect_heading_level(p_elem: etree._Element) -> int | None:
    ppr = p_elem.find(f"{W_NS}pPr")
    if ppr is None:
        return None

    pstyle = ppr.find(f"{W_NS}pStyle")
    if pstyle is not None:
        val = (pstyle.get(f"{W_NS}val") or "").strip()
        low = val.lower()
        if low in {"title", "标题"}:
            return 1
        m = re.match(r"^(?:heading|标题|h)\s*([1-6])$", low)
        if m:
            return int(m.group(1))
        if low.startswith("heading") and low[7:].isdigit():
            return max(1, min(6, int(low[7:])))

    outline = ppr.find(f"{W_NS}outlineLvl")
    if outline is not None:
        val = outline.get(f"{W_NS}val")
        if val is not None and val.isdigit():
            lvl = int(val) + 1
            if 1 <= lvl <= 6:
                return lvl
    return None


def is_list_paragraph(p_elem: etree._Element) -> bool:
    ppr = p_elem.find(f"{W_NS}pPr")
    if ppr is None:
        return False
    if ppr.find(f"{W_NS}numPr") is not None:
        return True
    pstyle = ppr.find(f"{W_NS}pStyle")
    if pstyle is not None:
        val = (pstyle.get(f"{W_NS}val") or "").lower()
        if "list" in val or "bullet" in val:
            return True
    return False


def parse_table_elem(tbl_elem: etree._Element) -> TableData | None:
    """Parse a `w:tbl` element resolving `w:gridSpan` (colspan) and `w:vMerge` (rowspan)."""
    grid_cols = tbl_elem.findall(f"{W_NS}tblGrid/{W_NS}gridCol")
    col_widths_mm: list[float] = []
    for gc in grid_cols:
        w_attr = gc.get(f"{W_NS}w")
        if w_attr and w_attr.isdigit():
            col_widths_mm.append(round(int(w_attr) * TWIP_TO_MM, 2))

    tr_elems = tbl_elem.findall(f"{W_NS}tr")
    if not tr_elems:
        return None

    cells: list[TableCell] = []
    active_vmerge: dict[int, TableCell] = {}
    max_cols = len(col_widths_mm)

    for r_idx, tr in enumerate(tr_elems):
        c_idx = 0
        seen_cols_in_row: set[int] = set()
        for tc in tr.findall(f"{W_NS}tc"):
            tc_pr = tc.find(f"{W_NS}tcPr")
            cs = 1
            if tc_pr is not None:
                gs = tc_pr.find(f"{W_NS}gridSpan")
                if gs is not None:
                    gs_val = gs.get(f"{W_NS}val")
                    if gs_val and gs_val.isdigit():
                        cs = max(1, int(gs_val))

            vmerge_el = tc_pr.find(f"{W_NS}vMerge") if tc_pr is not None else None
            vmerge_state: str | None = None
            if vmerge_el is not None:
                vmerge_state = vmerge_el.get(f"{W_NS}val", "continue")

            cell_inlines: list[DocInline] = []
            ps = tc.findall(f"{W_NS}p")
            for pi, p in enumerate(ps):
                p_inlines = extract_inlines_from_p(p)
                if pi > 0 and cell_inlines and p_inlines:
                    cell_inlines.append(BreakInline())
                cell_inlines.extend(p_inlines)

            if vmerge_state == "continue" and c_idx in active_vmerge:
                origin_cell = active_vmerge[c_idx]
                origin_cell.rs += 1
                if cell_inlines:
                    if origin_cell.inlines:
                        origin_cell.inlines.append(BreakInline())
                    origin_cell.inlines.extend(cell_inlines)
            else:
                cell = TableCell(r=r_idx, c=c_idx, rs=1, cs=cs, inlines=cell_inlines)
                cells.append(cell)
                if vmerge_state == "restart":
                    for k in range(c_idx, c_idx + cs):
                        active_vmerge[k] = cell
                else:
                    for k in range(c_idx, c_idx + cs):
                        active_vmerge.pop(k, None)

            for k in range(c_idx, c_idx + cs):
                seen_cols_in_row.add(k)
            c_idx += cs

        max_cols = max(max_cols, c_idx)
        for k in list(active_vmerge.keys()):
            if k not in seen_cols_in_row:
                active_vmerge.pop(k, None)

    if max_cols == 0:
        return None

    if len(col_widths_mm) < max_cols:
        default_w = round(170.0 / max_cols, 2)
        col_widths_mm.extend([default_w] * (max_cols - len(col_widths_mm)))

    return TableData(
        rows=len(tr_elems),
        cols=max_cols,
        col_widths_mm=col_widths_mm[:max_cols],
        cells=cells,
    )
