"""General geometric PDF line extraction & intra-page / cross-page paragraph reconstruction."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import statistics
from typing import Literal

import pymupdf as fitz

from inkcraft.docparse.chart_extract import PT_TO_MM
from inkcraft.docparse.docir import BlockType, BreakInline, DocBlock, DocInline, DocLine, MathInline, TextInline
from inkcraft.docparse.formula_ocr import has_math_alnum_chars, normalize_math_unicode, normalize_text_math_alnum
from inkcraft.docparse.inline_math import (
    SYMBOL_DEF_COMMA_RE,
    SYMBOL_DEF_DASH_RE,
    SYMBOL_DEF_PREFIX_RE,
    build_text_with_scripts,
    inlines_to_inline_math_str,
    is_symbol_def_block,
    normalize_symbol_def_leading_subscript,
    normalize_unambiguous_unit_powers,
    split_inline_math,
    strip_inline_math_markup,
)

LineRole = Literal[
    "header",
    "footer",
    "page_number",
    "heading",
    "list_item",
    "symbol_def",
    "caption",
    "formula_block",
    "eq_tag",
    "body",
]

_MATH_HINT_CHARS = set("∫∑∏√±×÷≤≥≠≈∞∂∇αβγδεθλμπρστφωΔΣΠΩ")
_LATEX_CMD_RE = re.compile(r"\\(?:frac|sqrt|sum|int|prod|lim|alpha|beta|gamma|pi|theta|Delta|Sigma)")

_HEADING_CN_RE = re.compile(
    r"^(?:"
    r"实验[一二三四五六七八九十百\d]+[：:、\s]"
    r"|第[一二三四五六七八九十百\d]+[章节篇讲部]"
    r"|[一二三四五六七八九十]+、\s*\S"
    r")"
)
_LIST_ITEM_RE = re.compile(
    r"^(?:"
    r"[（(]\s*\d{1,3}\s*[)）]"
    r"|\d{1,3}\s*[、)）]\s*(?!\d)"
    r"|\d{1,3}[.．]\s*(?!\s*\d)"
    r"|[-•·*●▪]\s+\S"
    r"|[a-zA-Z][)）]\s+\S"
    r")"
)
_CAPTION_RE = re.compile(r"^(?:图|表|Table|Fig\.?)\s*\d+", re.IGNORECASE)
_EQ_TAG_RE = re.compile(r"^[（(]\s*(?:式\s*\d+|\d+(?:\.\d+)?)\s*[)）]$")
_TERMINAL_PUNCT = frozenset("。！？：；:;.!?")


def looks_like_formula_line(text: str) -> bool:
    s = text.strip()
    if not s or len(s) > 160:
        return False
    if s.startswith("$$") and s.endswith("$$") and s.count("$$") == 2:
        return True
    if s.startswith("$") and s.endswith("$") and s.count("$") == 2:
        inner = s[1:-1].strip()
        if any(ch in inner for ch in ("=", "<", ">", "≤", "≥", "≠")) or _LATEX_CMD_RE.search(inner):
            return True
        if any(ch in inner for ch in _MATH_HINT_CHARS):
            return True
        return False
    stripped_cjk = re.sub(r"\$[^$]+\$", "", s)
    if re.search(r"[\u4e00-\u9fff]{2,}", stripped_cjk):
        return False
    if _LATEX_CMD_RE.search(stripped_cjk):
        return True
    math_hits = sum(1 for ch in stripped_cjk if ch in _MATH_HINT_CHARS)
    if math_hits >= 2 and len(s) <= 80:
        return True
    if "=" in stripped_cjk and math_hits >= 1 and len(s) <= 60:
        return True
    return False


def _bbox_overlaps(a: list[float], b: list[float], tol: float = 1.5) -> bool:
    return not (
        a[2] < b[0] + tol
        or a[0] > b[2] - tol
        or a[3] < b[1] + tol
        or a[1] > b[3] - tol
    )


@dataclass
class RawPdfLine:
    page_index: int
    bbox_mm: list[float]  # [visual_x0, y0, visual_x1, y1]
    raw_bbox_mm: list[float]
    text: str
    dom_font_pt: float
    max_font_pt: float
    is_bold: bool
    role: LineRole = "body"
    heading_level: int = 1


@dataclass
class PageTypographyProfile:
    page_index: int
    page_w_mm: float
    page_h_mm: float
    body_pt: float
    body_font_mm: float
    body_left_x0: float
    body_right_x1: float
    median_gap_mm: float


def _percentile(values: list[float], pct: float, default: float) -> float:
    if not values:
        return default
    s = sorted(values)
    idx = (len(s) - 1) * max(0.0, min(1.0, pct))
    lo = int(idx)
    hi = min(len(s) - 1, lo + 1)
    frac = idx - lo
    return s[lo] * (1.0 - frac) + s[hi] * frac


def extract_raw_pdf_lines(
    page: fitz.Page,
    page_index: int,
    *,
    exclude_bboxes_mm: list[list[float]] | None = None,
    native_math_bboxes_mm: list[list[float]] | None = None,
    crop_rect_mm: list[float] | None = None,
) -> list[RawPdfLine]:
    """Extract visually aligned, trimmed text lines with real non-whitespace left/right x-edges."""
    excl = list(exclude_bboxes_mm or [])
    math_excl = list(native_math_bboxes_mm or [])

    clip_rect: fitz.Rect | None = None
    if crop_rect_mm and len(crop_rect_mm) == 4:
        clip_rect = fitz.Rect(
            float(crop_rect_mm[0]) / PT_TO_MM,
            float(crop_rect_mm[1]) / PT_TO_MM,
            float(crop_rect_mm[2]) / PT_TO_MM,
            float(crop_rect_mm[3]) / PT_TO_MM,
        )

    raw_dict = page.get_text("rawdict", clip=clip_rect, flags=fitz.TEXT_PRESERVE_WHITESPACE)
    lines_out: list[RawPdfLine] = []

    for blk in raw_dict.get("blocks", []):
        if blk.get("type") != 0:
            continue
        for ln in blk.get("lines", []):
            raw_lb = [round(float(v) * PT_TO_MM, 2) for v in ln["bbox"]]
            if any(_bbox_overlaps(raw_lb, tb, tol=1.0) for tb in excl):
                continue
            if any(_bbox_overlaps(raw_lb, mb, tol=0.6) for mb in math_excl):
                continue

            # Collect char stream and span metadata from spans; fall back gracefully if chars list is absent
            char_entries: list[tuple[str, float, float, float, float, float, bool]] = []
            raw_spans: list[tuple[str, float, int, str, float, float, float]] = []
            for sp in ln.get("spans", []):
                sz = float(sp.get("size", 11.0))
                flags = int(sp.get("flags", 0))
                font_name = str(sp.get("font", "")).lower()
                sp_bold = bool(flags & 16) or ("bold" in font_name)
                sb = sp.get("bbox") or ln["bbox"]
                origin = sp.get("origin") or (sb[0], sb[3])
                sp_oy = float(origin[1]) * PT_TO_MM
                sp_y0 = float(sb[1]) * PT_TO_MM
                sp_y1 = float(sb[3]) * PT_TO_MM

                chars = sp.get("chars")
                if chars:
                    sp_txt = "".join(str(ch_info.get("c", "")) for ch_info in chars)
                    for ch_info in chars:
                        c = str(ch_info.get("c", ""))
                        if not c:
                            continue
                        cb = ch_info.get("bbox") or sp.get("bbox") or ln["bbox"]
                        char_entries.append(
                            (
                                c,
                                float(cb[0]) * PT_TO_MM,
                                float(cb[1]) * PT_TO_MM,
                                float(cb[2]) * PT_TO_MM,
                                float(cb[3]) * PT_TO_MM,
                                sz,
                                sp_bold,
                            )
                        )
                else:
                    sp_txt = str(sp.get("text", ""))
                    if not sp_txt:
                        continue
                    sx0, sy0, sx1, sy1 = [float(v) * PT_TO_MM for v in sb]
                    n_c = max(1, len(sp_txt))
                    cw = (sx1 - sx0) / n_c
                    for ci, ch in enumerate(sp_txt):
                        char_entries.append(
                            (ch, sx0 + ci * cw, sy0, sx0 + (ci + 1) * cw, sy1, sz, sp_bold)
                        )
                if sp_txt:
                    raw_spans.append((sp_txt, sz, flags, font_name, sp_oy, sp_y0, sp_y1))

            # Trim leading/trailing whitespace so visual left edge reflects real ink
            start = 0
            while start < len(char_entries) and char_entries[start][0].isspace():
                start += 1
            end = len(char_entries)
            while end > start and char_entries[end - 1][0].isspace():
                end -= 1
            kept = char_entries[start:end]
            if not kept:
                continue

            # Detect subscript / superscript / CambriaMath inline formulas from PDF spans
            non_ws_sizes = [sp[1] for sp in raw_spans if sp[0].strip()]
            line_max_pt = max(non_ws_sizes) if non_ws_sizes else 11.0
            normal_anchors = [sp for sp in raw_spans if sp[0].strip() and sp[1] >= line_max_pt * 0.85]
            default_anchor = normal_anchors[0] if normal_anchors else (raw_spans[0] if raw_spans else None)
            anchor_sz = default_anchor[1] if default_anchor else line_max_pt
            anchor_oy = default_anchor[4] if default_anchor else 0.0
            anchor_y0 = default_anchor[5] if default_anchor else 0.0
            anchor_y1 = default_anchor[6] if default_anchor else 1.0
            anchor_cy = 0.5 * (anchor_y0 + anchor_y1)
            anchor_h = max(1.0, anchor_y1 - anchor_y0)

            pieces: list[tuple[str, str]] = []
            for sp_txt, sz, flags, _, sp_oy, sp_y0, sp_y1 in raw_spans:
                if has_math_alnum_chars(sp_txt):
                    norm_m = normalize_math_unicode(sp_txt, escape_percent=True)
                    norm_m = re.sub(
                        r"(\\(?:rho|alpha|beta|gamma|sigma|theta|Delta|pi|varphi)|[A-Za-z])\s*([ijkmnws0-9])\b",
                        lambda m: f"{m.group(1)}_{m.group(2)}" if len(m.group(2)) == 1 else m.group(0),
                        norm_m,
                    )
                    lead = sp_txt[: len(sp_txt) - len(sp_txt.lstrip())]
                    trail = sp_txt[len(sp_txt.rstrip()) :]
                    if lead:
                        pieces.append((lead, "normal"))
                    if norm_m:
                        pieces.append((norm_m, "math"))
                    if trail:
                        pieces.append((trail, "normal"))
                    continue

                cleaned_txt = normalize_text_math_alnum(sp_txt)
                stripped_sp = cleaned_txt.strip()
                sp_cy = 0.5 * (sp_y0 + sp_y1)
                if (
                    stripped_sp
                    and len(stripped_sp) <= 12
                    and sz <= anchor_sz * 0.82
                    and anchor_sz >= 8.0
                ):
                    is_sup = (sp_cy < anchor_cy - 0.10 * anchor_h) or (
                        bool(flags & 1) and sp_cy < anchor_cy
                    )
                    is_sub = (sp_cy > anchor_cy + 0.06 * anchor_h) or (
                        sp_oy > anchor_oy + 0.20 and sp_cy >= anchor_cy
                    )
                    if is_sup and not is_sub:
                        pieces.append((cleaned_txt, "sup"))
                        continue
                    if is_sub or (sz <= anchor_sz * 0.72 and sp_y1 >= anchor_y1 - 0.3):
                        pieces.append((cleaned_txt, "sub"))
                        continue

                pieces.append((cleaned_txt, "normal"))
                if stripped_sp and sz >= line_max_pt * 0.85:
                    anchor_sz = sz
                    anchor_oy = sp_oy
                    anchor_y0 = sp_y0
                    anchor_y1 = sp_y1
                    anchor_cy = sp_cy
                    anchor_h = max(1.0, sp_y1 - sp_y0)

            text = normalize_unambiguous_unit_powers(build_text_with_scripts(pieces)).strip()
            if not text:
                continue

            vis_x0 = round(min(item[1] for item in kept), 2)
            vis_y0 = round(min(item[2] for item in kept), 2)
            vis_x1 = round(max(item[3] for item in kept), 2)
            vis_y1 = round(max(item[4] for item in kept), 2)

            if crop_rect_mm and len(crop_rect_mm) == 4:
                cx = 0.5 * (vis_x0 + vis_x1)
                cy = 0.5 * (vis_y0 + vis_y1)
                if not (
                    crop_rect_mm[0] - 1.0 <= cx <= crop_rect_mm[2] + 1.0
                    and crop_rect_mm[1] - 1.0 <= cy <= crop_rect_mm[3] + 1.0
                ):
                    continue

            sizes: list[float] = []
            bold_cnt = 0
            non_ws_cnt = 0
            for ch, _, _, _, _, sz, is_b in kept:
                if ch.isspace():
                    continue
                non_ws_cnt += 1
                sizes.append(sz)
                if is_b:
                    bold_cnt += 1

            dom_pt = statistics.median(sizes) if sizes else 11.0
            max_pt = max(sizes) if sizes else dom_pt
            is_bold = (bold_cnt / max(1, non_ws_cnt)) >= 0.5

            lines_out.append(
                RawPdfLine(
                    page_index=page_index,
                    bbox_mm=[vis_x0, vis_y0, vis_x1, vis_y1],
                    raw_bbox_mm=raw_lb,
                    text=text,
                    dom_font_pt=float(dom_pt),
                    max_font_pt=float(max_pt),
                    is_bold=is_bold,
                )
            )

    lines_out.sort(key=lambda ln: (round(ln.bbox_mm[1] / 2.2), ln.bbox_mm[0]))
    return lines_out


def compute_page_profile(
    lines: list[RawPdfLine],
    page_index: int,
    page_w_mm: float,
    page_h_mm: float,
    fallback_profile: PageTypographyProfile | None = None,
) -> PageTypographyProfile:
    """Compute dominant body typography & margin geometry for one PDF page."""
    core_lines = [
        ln
        for ln in lines
        if ln.bbox_mm[1] >= page_h_mm * 0.065
        and ln.bbox_mm[3] <= page_h_mm * 0.925
        and len(ln.text) >= 4
    ]
    weighted_pts: list[float] = []
    for ln in core_lines:
        rep = max(1, min(12, len(ln.text) // 4))
        weighted_pts.extend([ln.dom_font_pt] * rep)

    body_pt = (
        float(statistics.median(weighted_pts))
        if weighted_pts
        else (fallback_profile.body_pt if fallback_profile else 12.0)
    )
    body_font_mm = max(2.2, body_pt * PT_TO_MM)

    body_lines = [
        ln
        for ln in core_lines
        if abs(ln.dom_font_pt - body_pt) <= 1.2 and len(ln.text) >= 6
    ]
    left_candidates = [ln.bbox_mm[0] for ln in body_lines if ln.bbox_mm[0] < page_w_mm * 0.45]
    right_candidates = [ln.bbox_mm[2] for ln in body_lines if ln.bbox_mm[2] > page_w_mm * 0.45]

    if len(left_candidates) >= 3:
        body_left = _percentile(left_candidates, 0.12, 25.0)
    elif fallback_profile is not None:
        body_left = fallback_profile.body_left_x0
    else:
        body_left = min(left_candidates) if left_candidates else 25.0

    if len(right_candidates) >= 3:
        body_right = _percentile(right_candidates, 0.88, page_w_mm - 25.0)
    elif fallback_profile is not None:
        body_right = fallback_profile.body_right_x1
    else:
        body_right = max(right_candidates) if right_candidates else (page_w_mm - 25.0)

    if body_right - body_left < 60.0:
        if fallback_profile is not None:
            body_left = fallback_profile.body_left_x0
            body_right = fallback_profile.body_right_x1
        else:
            body_right = max(body_left + 80.0, page_w_mm - 25.0)

    gaps: list[float] = []
    ordered_body = sorted(body_lines, key=lambda ln: (ln.bbox_mm[1], ln.bbox_mm[0]))
    for i in range(1, len(ordered_body)):
        dy = ordered_body[i].bbox_mm[1] - ordered_body[i - 1].bbox_mm[3]
        if 0.0 <= dy <= max(12.0, body_font_mm * 2.8):
            gaps.append(dy)
    median_gap = (
        float(statistics.median(gaps))
        if gaps
        else (fallback_profile.median_gap_mm if fallback_profile else body_font_mm * 0.85)
    )

    return PageTypographyProfile(
        page_index=page_index,
        page_w_mm=page_w_mm,
        page_h_mm=page_h_mm,
        body_pt=round(body_pt, 2),
        body_font_mm=round(body_font_mm, 2),
        body_left_x0=round(body_left, 2),
        body_right_x1=round(body_right, 2),
        median_gap_mm=round(median_gap, 2),
    )


def _join_line_texts(prev_text: str, curr_text: str) -> str:
    """Join wrapped line fragments cleanly without inserting spurious spaces inside CJK words."""
    a = prev_text.rstrip()
    b = curr_text.lstrip()
    if not a:
        return b
    if not b:
        return a
    # De-hyphenate ASCII word wrap (`-\nword`)
    if len(a) >= 2 and a.endswith("-") and a[-2].isascii() and a[-2].isalpha() and b[0].isascii() and b[0].islower():
        return a[:-1] + b
    last_a = a[-1]
    first_b = b[0]
    if last_a.isascii() and last_a.isalnum() and first_b.isascii() and first_b.isalnum():
        return f"{a} {b}"
    return f"{a}{b}"


def _has_obstacle_between(
    prev_bbox: list[float],
    curr_bbox: list[float],
    obstacle_bboxes_mm: list[list[float]],
) -> bool:
    """Return True if an image, formula, or table lies vertically between `prev_bbox` and `curr_bbox`."""
    y_lo = min(prev_bbox[3], curr_bbox[1])
    y_hi = max(prev_bbox[3], curr_bbox[1])
    for ob in obstacle_bboxes_mm:
        if ob[1] <= y_hi + 1.0 and ob[3] >= y_lo - 1.0:
            return True
    return False


def _append_continuation_to_inlines(
    inlines: list[DocInline],
    cont_text: str,
) -> list[DocInline]:
    """Join `cont_text` onto the tail segment after the last `BreakInline`, preserving earlier breaks."""
    last_brk = -1
    for idx, inl in enumerate(inlines):
        if isinstance(inl, BreakInline):
            last_brk = idx
    prefix = list(inlines[: last_brk + 1]) if last_brk >= 0 else []
    tail = inlines[last_brk + 1 :] if last_brk >= 0 else inlines
    tail_parts: list[str] = []
    for inl in tail:
        if isinstance(inl, TextInline):
            tail_parts.append(inl.text)
        elif isinstance(inl, MathInline):
            tail_parts.append(f"${inl.latex}$")
    merged_tail = _join_line_texts("".join(tail_parts), cont_text)
    return prefix + split_inline_math(merged_tail)


def _is_wrapped_continuation(
    prev_line: RawPdfLine,
    curr_line: RawPdfLine,
    profile: PageTypographyProfile,
    obstacle_bboxes_mm: list[list[float]],
) -> bool:
    """Return True if `curr_line` geometrically continues `prev_line`'s paragraph."""
    # Check if an image, formula, or table intervenes vertically between the two lines
    if _has_obstacle_between(prev_line.bbox_mm, curr_line.bbox_mm, obstacle_bboxes_mm):
        return False

    if abs(curr_line.dom_font_pt - prev_line.dom_font_pt) > 1.25:
        return False

    dy = curr_line.bbox_mm[1] - prev_line.bbox_mm[3]
    max_gap = max(profile.median_gap_mm * 1.8, profile.body_font_mm * 1.55)
    if dy < -1.0 or dy > max_gap:
        return False

    # Indented line starts a new paragraph (flush-left continuation stays near body_left_x0)
    indent_tol = max(2.6, profile.body_font_mm * 0.6)
    if curr_line.bbox_mm[0] > profile.body_left_x0 + indent_tol:
        return False

    ptxt = prev_line.text.rstrip()
    if not ptxt or ptxt[-1] in {":", "："}:
        return False

    wrap_margin = profile.body_right_x1 - max(18.0, profile.body_font_mm * 3.5)
    if prev_line.bbox_mm[2] >= wrap_margin:
        return True
    if ptxt[-1] not in _TERMINAL_PUNCT and prev_line.bbox_mm[2] >= profile.body_right_x1 - 36.0:
        return True
    return False


def _classify_line_role(
    ln: RawPdfLine,
    prev_line: RawPdfLine | None,
    profile: PageTypographyProfile,
    obstacle_bboxes_mm: list[list[float]],
) -> tuple[LineRole, int]:
    """Classify a line's structural role and heading level."""
    raw_txt = ln.text.strip()
    txt = strip_inline_math_markup(raw_txt).strip()
    x0, y0, x1, y1 = ln.bbox_mm
    body_w = max(40.0, profile.body_right_x1 - profile.body_left_x0)
    line_w = max(0.0, x1 - x0)

    if y1 < profile.page_h_mm * 0.068 and len(txt) < 40 and ln.max_font_pt < profile.body_pt * 1.35:
        return "header", 1
    if y0 > profile.page_h_mm * 0.92 and len(txt) < 24:
        if re.fullmatch(r"[-–—第页共/\s]*\d+[-–—页\s]*", txt):
            return "page_number", 1
        return "footer", 1
    if _EQ_TAG_RE.match(txt) and x0 > profile.body_left_x0 + 30.0:
        return "eq_tag", 1
    if looks_like_formula_line(raw_txt):
        return "formula_block", 1

    # Check symbol definition lines BEFORE centered heading heuristic so centered/indented `Wi，调理剂...` stays paragraph
    wrapped_from_prev = (
        prev_line is not None
        and _is_wrapped_continuation(prev_line, ln, profile, obstacle_bboxes_mm)
    )
    if SYMBOL_DEF_PREFIX_RE.match(txt):
        return "symbol_def", 1
    near_symbol_or_formula = (
        prev_line is not None
        and (
            prev_line.role in {"symbol_def", "eq_tag", "formula_block"}
            or any(
                ob[3] <= y0 + 2.0 and (y0 - ob[3]) <= 24.0
                for ob in obstacle_bboxes_mm
            )
        )
    )
    near_page_top = y0 <= profile.page_h_mm * 0.18
    indented_line = x0 >= profile.body_left_x0 + 4.0
    if (
        SYMBOL_DEF_DASH_RE.match(txt)
        or (
            SYMBOL_DEF_COMMA_RE.match(txt)
            and (near_symbol_or_formula or near_page_top or indented_line)
        )
    ) and (line_w <= body_w * 0.90 or near_symbol_or_formula or indented_line):
        return "symbol_def", 1

    # Heading checks before list_item so `五、思考题` / 16pt headings win
    is_big = ln.max_font_pt >= profile.body_pt * 1.20
    is_subhead_bold = ln.is_bold and ln.max_font_pt >= profile.body_pt * 1.08 and len(txt) <= 55
    is_centered = (
        abs(0.5 * (x0 + x1) - 0.5 * profile.page_w_mm) <= profile.page_w_mm * 0.10
        and line_w <= body_w * 0.72
        and len(txt) <= 40
        and not txt.endswith(("。", "；", ";", "，", ","))
        and not _CAPTION_RE.match(txt)
    )
    if (is_big or is_subhead_bold) and len(txt) <= 65:
        lvl = 1 if ln.max_font_pt >= profile.body_pt * 1.45 else 2
        return "heading", lvl
    if _HEADING_CN_RE.match(txt) and len(txt) <= 45 and line_w <= body_w * 0.85:
        lvl = 1 if txt.startswith("实验") or txt.startswith("第") else 2
        return "heading", lvl
    if is_centered:
        return "heading", 2

    if _LIST_ITEM_RE.match(txt):
        return "list_item", 1

    if _CAPTION_RE.match(txt) and len(txt) <= 60 and not wrapped_from_prev:
        if not (txt.endswith("。") and x0 <= profile.body_left_x0 + 3.0):
            return "caption", 1

    return "body", 1


@dataclass
class _ReconstructedItem:
    block: DocBlock
    last_line: RawPdfLine
    is_symbol_def: bool = False


def reconstruct_page_paragraphs(
    raw_lines: list[RawPdfLine],
    obstacle_bboxes_mm: list[list[float]],
    *,
    page_index: int,
    profile: PageTypographyProfile,
) -> list[DocBlock]:
    """Reconstruct coherent paragraphs, lists, headings & symbol defs from single PDF lines."""
    if not raw_lines:
        return []

    prev_line: RawPdfLine | None = None
    for ln in raw_lines:
        role, lvl = _classify_line_role(ln, prev_line, profile, obstacle_bboxes_mm)
        ln.role = role
        ln.heading_level = lvl
        if role == "symbol_def":
            ln.text = normalize_symbol_def_leading_subscript(ln.text)
        prev_line = ln

    items: list[_ReconstructedItem] = []

    def _new_block(ln: RawPdfLine) -> _ReconstructedItem:
        btype: BlockType = "paragraph"
        is_sym = False
        if ln.role in {"header", "footer", "page_number", "heading", "list_item", "caption", "formula_block"}:
            btype = ln.role  # type: ignore[assignment]
        elif ln.role == "symbol_def":
            btype = "paragraph"
            is_sym = True
        doc_line = DocLine(page_index=page_index, bbox_mm=list(ln.bbox_mm), inlines=split_inline_math(ln.text))
        blk = DocBlock(
            block_id="",
            page_index=page_index,
            type=btype,
            level=ln.heading_level if btype == "heading" else 1,
            bbox_mm=list(ln.bbox_mm),
            lines=[doc_line],
            inlines=[] if btype == "formula_block" else list(doc_line.inlines),
            latex=ln.text.strip("$ ") if btype == "formula_block" else None,
        )
        return _ReconstructedItem(block=blk, last_line=ln, is_symbol_def=is_sym)

    for ln in raw_lines:
        if ln.role in {"header", "footer", "page_number", "heading", "formula_block", "caption", "eq_tag"}:
            items.append(_new_block(ln))
            continue

        if items:
            cur = items[-1]
            # Merge body continuation line into preceding paragraph or list_item (never into heading/caption/eq_tag)
            can_target = cur.block.type in {"paragraph", "list_item"}
            if (
                can_target
                and ln.role == "body"
                and _is_wrapped_continuation(cur.last_line, ln, profile, obstacle_bboxes_mm)
            ):
                cur.block.lines.append(
                    DocLine(
                        page_index=page_index,
                        bbox_mm=list(ln.bbox_mm),
                        inlines=split_inline_math(ln.text),
                    )
                )
                cur.block.inlines = _append_continuation_to_inlines(cur.block.inlines, ln.text)
                if cur.block.bbox_mm and len(cur.block.bbox_mm) == 4:
                    cur.block.bbox_mm = [
                        round(min(cur.block.bbox_mm[0], ln.bbox_mm[0]), 2),
                        round(min(cur.block.bbox_mm[1], ln.bbox_mm[1]), 2),
                        round(max(cur.block.bbox_mm[2], ln.bbox_mm[2]), 2),
                        round(max(cur.block.bbox_mm[3], ln.bbox_mm[3]), 2),
                    ]
                cur.last_line = ln
                continue

            # Merge consecutive list items ((1), (2), (3)...) and consecutive symbol definitions
            # into ONE cohesive block separated by BreakInline, while retaining individual DocLines.
            can_merge_list = cur.block.type == "list_item" and ln.role == "list_item"
            can_merge_sym = cur.is_symbol_def and ln.role == "symbol_def"
            if can_merge_list or can_merge_sym:
                dy = ln.bbox_mm[1] - cur.last_line.bbox_mm[3]
                max_group_gap = max(profile.median_gap_mm * 3.0, profile.body_font_mm * 2.8)
                if -profile.body_font_mm * 0.4 <= dy <= max_group_gap and not _has_obstacle_between(
                    cur.last_line.bbox_mm, ln.bbox_mm, obstacle_bboxes_mm
                ):
                    new_inlines = split_inline_math(ln.text)
                    cur.block.lines.append(
                        DocLine(
                            page_index=page_index,
                            bbox_mm=list(ln.bbox_mm),
                            inlines=new_inlines,
                        )
                    )
                    if cur.block.inlines:
                        cur.block.inlines = list(cur.block.inlines) + [BreakInline(), *new_inlines]
                    else:
                        cur.block.inlines = list(new_inlines)
                    if cur.block.bbox_mm and len(cur.block.bbox_mm) == 4:
                        cur.block.bbox_mm = [
                            round(min(cur.block.bbox_mm[0], ln.bbox_mm[0]), 2),
                            round(min(cur.block.bbox_mm[1], ln.bbox_mm[1]), 2),
                            round(max(cur.block.bbox_mm[2], ln.bbox_mm[2]), 2),
                            round(max(cur.block.bbox_mm[3], ln.bbox_mm[3]), 2),
                        ]
                    cur.last_line = ln
                    continue

            # Also merge multi-line headings when they have the exact same big font size and small vertical gap
            if (
                cur.block.type == "heading"
                and ln.role == "heading"
                and abs(cur.last_line.dom_font_pt - ln.dom_font_pt) <= 0.5
                and cur.block.level == ln.heading_level
                and 0.0 <= (ln.bbox_mm[1] - cur.last_line.bbox_mm[3]) <= profile.body_font_mm * 1.4
                and cur.last_line.bbox_mm[2] >= profile.body_right_x1 - 24.0
            ):
                cur.block.lines.append(
                    DocLine(
                        page_index=page_index,
                        bbox_mm=list(ln.bbox_mm),
                        inlines=split_inline_math(ln.text),
                    )
                )
                merged_text = _join_line_texts(cur.block.plain_text(), ln.text)
                cur.block.inlines = split_inline_math(merged_text)
                if cur.block.bbox_mm and len(cur.block.bbox_mm) == 4:
                    cur.block.bbox_mm = [
                        round(min(cur.block.bbox_mm[0], ln.bbox_mm[0]), 2),
                        round(min(cur.block.bbox_mm[1], ln.bbox_mm[1]), 2),
                        round(max(cur.block.bbox_mm[2], ln.bbox_mm[2]), 2),
                        round(max(cur.block.bbox_mm[3], ln.bbox_mm[3]), 2),
                    ]
                cur.last_line = ln
                continue

        items.append(_new_block(ln))

    return [it.block for it in items]


def merge_cross_page_paragraphs(
    all_blocks: list[DocBlock],
    profiles_by_page: dict[int, PageTypographyProfile],
) -> list[DocBlock]:
    """Merge paragraphs split across consecutive PDF page breaks while keeping DocLine.page_index intact."""
    if not all_blocks or not profiles_by_page:
        return all_blocks

    # Group flow-order indices by page_index
    skip_types = {"header", "footer", "page_number", "discarded"}
    drop_indices: set[int] = set()

    # Work sequentially over blocks in page order
    page_indices = sorted(profiles_by_page.keys())
    for p_pos in range(len(page_indices) - 1):
        p_curr = page_indices[p_pos]
        p_next = page_indices[p_pos + 1]
        if p_next != p_curr + 1:
            continue

        curr_candidates = [
            i
            for i, b in enumerate(all_blocks)
            if i not in drop_indices and b.page_index == p_curr and b.type not in skip_types
        ]
        next_candidates = [
            i
            for i, b in enumerate(all_blocks)
            if i not in drop_indices and b.page_index == p_next and b.type not in skip_types
        ]
        if not curr_candidates or not next_candidates:
            continue

        last_idx = curr_candidates[-1]
        first_idx = next_candidates[0]
        last_blk = all_blocks[last_idx]
        first_blk = all_blocks[first_idx]

        if last_blk.type == "list_item" and first_blk.type == "list_item":
            first_line = first_blk.lines[0] if first_blk.lines else None
            first_box = (first_line.bbox_mm if first_line and first_line.bbox_mm else first_blk.bbox_mm) or []
            prof_next = profiles_by_page[p_next]
            if len(first_box) == 4 and first_box[1] <= prof_next.page_h_mm * 0.25:
                for ln in first_blk.lines:
                    if ln.page_index is None:
                        ln.page_index = p_next
                    last_blk.lines.append(ln)
                last_blk.inlines = list(last_blk.inlines) + [BreakInline(), *first_blk.inlines]
                drop_indices.add(first_idx)
            continue

        if (
            last_blk.type == "paragraph"
            and first_blk.type == "paragraph"
            and is_symbol_def_block(last_blk)
            and is_symbol_def_block(first_blk)
        ):
            first_line = first_blk.lines[0] if first_blk.lines else None
            first_box = (first_line.bbox_mm if first_line and first_line.bbox_mm else first_blk.bbox_mm) or []
            prof_next = profiles_by_page[p_next]
            if len(first_box) == 4 and first_box[1] <= prof_next.page_h_mm * 0.25:
                for ln in first_blk.lines:
                    if ln.page_index is None:
                        ln.page_index = p_next
                    last_blk.lines.append(ln)
                last_blk.inlines = list(last_blk.inlines) + [BreakInline(), *first_blk.inlines]
                drop_indices.add(first_idx)
            continue

        if last_blk.type not in {"paragraph", "list_item"}:
            continue
        if first_blk.type != "paragraph":
            continue
        if is_symbol_def_block(first_blk) or is_symbol_def_block(last_blk):
            continue

        prof_curr = profiles_by_page[p_curr]
        prof_next = profiles_by_page[p_next]

        last_line = last_blk.lines[-1] if last_blk.lines else None
        first_line = first_blk.lines[0] if first_blk.lines else None
        last_box = (last_line.bbox_mm if last_line and last_line.bbox_mm else last_blk.bbox_mm) or []
        first_box = (first_line.bbox_mm if first_line and first_line.bbox_mm else first_blk.bbox_mm) or []
        if len(last_box) != 4 or len(first_box) != 4:
            continue

        # Must sit near bottom of p_curr (or be last content) and near top of p_next, flush-left
        if first_box[1] > prof_next.page_h_mm * 0.25:
            continue
        if first_box[0] > prof_next.body_left_x0 + max(2.6, prof_next.body_font_mm * 0.6):
            continue

        prev_plain = last_blk.plain_text().rstrip()
        if not prev_plain or prev_plain[-1] in _TERMINAL_PUNCT:
            continue
        if last_box[2] < prof_curr.body_right_x1 - 24.0:
            continue

        # Merge first_blk into last_blk cleanly, preserving per-line page_index!
        for ln in first_blk.lines:
            if ln.page_index is None:
                ln.page_index = p_next
            last_blk.lines.append(ln)
        last_blk.inlines = _append_continuation_to_inlines(
            last_blk.inlines, inlines_to_inline_math_str(first_blk.inlines).lstrip()
        )
        drop_indices.add(first_idx)

    if not drop_indices:
        return all_blocks
    return [b for i, b in enumerate(all_blocks) if i not in drop_indices]
