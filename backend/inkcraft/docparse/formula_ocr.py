"""Formula recognition (PDF native fraction math + RapidLaTeXOCR / RapidOCR hybrid) & image classifier."""

from __future__ import annotations

from dataclasses import dataclass, field
import io
import logging
from pathlib import Path
import re
import threading
from typing import Any, Literal

import numpy as np
from PIL import Image, ImageFilter, ImageOps
import pymupdf as fitz

from inkcraft.docparse.docir import DocBlock

logger = logging.getLogger(__name__)

PT_TO_MM = 25.4 / 72.0

_OCR_LOCK = threading.Lock()
_LATEX_OCR_ENGINE: Any = None
_LATEX_OCR_TRIED = False
_RAPID_OCR_ENGINE: Any = None
_RAPID_OCR_TRIED = False

# Single mathematical symbols mapped explicitly outside contiguous ASCII blocks
_SPECIAL_MATH_MAP: dict[int, str] = {
    0x210E: "h",       # Planck constant
    0x2113: "l",
    0x211D: "R",
    0x2115: "N",
    0x2124: "Z",
    0x211A: "Q",
    0x2102: "C",
    0x2212: "-",       # MINUS SIGN
    0x00D7: r"\times ",
    0x00F7: r"\div ",
    0x00B1: r"\pm ",
    0x2264: r"\leq ",
    0x2265: r"\geq ",
    0x2260: r"\neq ",
    0x2248: r"\approx ",
    0x2211: r"\sum ",
    0x220F: r"\prod ",
    0x222B: r"\int ",
    0x221A: r"\sqrt ",
    0x221E: r"\infty ",
    0x2202: r"\partial ",
    0x2207: r"\nabla ",
    0x25B3: r"\Delta ",  # white up-pointing triangle used as Delta in Chinese PDFs
    0x0394: r"\Delta ",
    0x03A3: r"\Sigma ",
    0x03A9: r"\Omega ",
    0x03A0: r"\Pi ",
    0x03B1: r"\alpha ",
    0x03B2: r"\beta ",
    0x03B3: r"\gamma ",
    0x03B4: r"\delta ",
    0x03B5: r"\varepsilon ",
    0x03B8: r"\theta ",
    0x03BB: r"\lambda ",
    0x03BC: r"\mu ",
    0x03C0: r"\pi ",
    0x03C1: r"\rho ",
    0x03C3: r"\sigma ",
    0x03C4: r"\tau ",
    0x03C6: r"\varphi ",
    0x03C9: r"\omega ",
    0xFF05: "%",
    0xFF08: "(",
    0xFF09: ")",
    0xFF1D: "=",
    0xFF0B: "+",
    0xFF0D: "-",
}

_GREEK_LOWER_TEX = [
    r"\alpha ", r"\beta ", r"\gamma ", r"\delta ", r"\varepsilon ",
    r"\zeta ", r"\eta ", r"\theta ", r"\iota ", r"\kappa ", r"\lambda ",
    r"\mu ", r"\nu ", r"\xi ", "o", r"\pi ", r"\rho ", r"\varsigma ",
    r"\sigma ", r"\tau ", r"\upsilon ", r"\varphi ", r"\chi ", r"\psi ", r"\omega ",
]
_GREEK_UPPER_TEX = [
    "A", "B", r"\Gamma ", r"\Delta ", "E", "Z", "H", r"\Theta ",
    "I", "K", r"\Lambda ", "M", "N", r"\Xi ", "O", r"\Pi ", "P", r"\Theta ",
    r"\Sigma ", "T", r"\Upsilon ", r"\Phi ", "X", r"\Psi ", r"\Omega ",
]


def _map_math_alpha_cp(cp: int) -> str | None:
    # Latin Mathematical Alphanumeric styles in SMP (U+1D400..U+1D6A3)
    if 0x1D400 <= cp <= 0x1D6A3:
        offset = (cp - 0x1D400) % 52
        return chr(ord("A") + offset) if offset < 26 else chr(ord("a") + (offset - 26))
    # Mathematical Digits (U+1D7CE..U+1D7FF)
    if 0x1D7CE <= cp <= 0x1D7FF:
        return chr(ord("0") + ((cp - 0x1D7CE) % 10))
    # Greek Mathematical Alphanumeric blocks (5 families of 58 chars starting at 0x1D6A8)
    if 0x1D6A8 <= cp <= 0x1D7CB:
        style_start = 0x1D6A8 + ((cp - 0x1D6A8) // 58) * 58
        idx = cp - style_start
        if 0 <= idx < 25:
            return _GREEK_UPPER_TEX[idx]
        if 26 <= idx < 51:
            return _GREEK_LOWER_TEX[idx - 26]
        if idx == 52:
            return r"\partial "
        if idx == 53:
            return r"\varepsilon "
        if idx == 54:
            return r"\vartheta "
        if idx == 56:
            return r"\varphi "
        if idx == 57:
            return r"\rho "
    return None


def normalize_math_unicode(text: str, *, escape_percent: bool = True) -> str:
    """Normalize SMP Mathematical Alphanumeric symbols & common Unicode operators to ASCII/LaTeX."""
    out: list[str] = []
    for ch in text or "":
        cp = ord(ch)
        mapped = _SPECIAL_MATH_MAP.get(cp) or _map_math_alpha_cp(cp)
        if mapped is not None:
            out.append(mapped)
        elif ch == "%" and escape_percent:
            out.append(r"\%")
        else:
            out.append(ch)
    res = "".join(out)
    res = re.sub(r"\\(alpha|beta|gamma|delta|rho|sigma|pi|theta|Delta|times|div|pm)\s+([A-Za-z0-9])", r"\\\1 \2", res)
    res = re.sub(r"\s+", " ", res).strip()
    return res


def has_math_alnum_chars(text: str) -> bool:
    return any(0x1D400 <= ord(ch) <= 0x1D7FF for ch in (text or ""))


_GREEK_LOWER_UNI = "αβγδεζηθικλμνξoπρςστυφχψω"
_GREEK_UPPER_UNI = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΘΣΤΥΦΧΨΩ"


def normalize_text_math_alnum(text: str) -> str:
    """Convert SMP Mathematical Alphanumeric symbols (`𝑊𝑖`, `𝜌`) to plain Unicode for PDF prose."""
    if not text:
        return ""
    out: list[str] = []
    for ch in text:
        cp = ord(ch)
        if cp in (0x2061, 0x2062, 0x2063, 0x2064):
            continue
        if 0x1D400 <= cp <= 0x1D6A3:
            offset = (cp - 0x1D400) % 52
            out.append(chr(ord("A") + offset) if offset < 26 else chr(ord("a") + (offset - 26)))
        elif 0x1D7CE <= cp <= 0x1D7FF:
            out.append(chr(ord("0") + ((cp - 0x1D7CE) % 10)))
        elif 0x1D6A8 <= cp <= 0x1D7CB:
            idx = cp - (0x1D6A8 + ((cp - 0x1D6A8) // 58) * 58)
            if 0 <= idx < len(_GREEK_UPPER_UNI):
                out.append(_GREEK_UPPER_UNI[idx])
            elif 26 <= idx < 26 + len(_GREEK_LOWER_UNI):
                out.append(_GREEK_LOWER_UNI[idx - 26])
            elif idx == 52:
                out.append("∂")
            elif idx == 57:
                out.append("ρ")
            else:
                out.append(ch)
        else:
            out.append(ch)
    return "".join(out)


def _get_latex_ocr() -> Any | None:
    global _LATEX_OCR_ENGINE, _LATEX_OCR_TRIED
    with _OCR_LOCK:
        if _LATEX_OCR_TRIED:
            return _LATEX_OCR_ENGINE
        _LATEX_OCR_TRIED = True
        try:
            from rapid_latex_ocr import LaTeXOCR  # type: ignore[import-not-found]

            _LATEX_OCR_ENGINE = LaTeXOCR()
        except Exception as exc:
            logger.info("RapidLaTeXOCR unavailable (falling back cleanly): %s", exc)
            _LATEX_OCR_ENGINE = None
        return _LATEX_OCR_ENGINE


def _get_rapid_ocr() -> Any | None:
    global _RAPID_OCR_ENGINE, _RAPID_OCR_TRIED
    with _OCR_LOCK:
        if _RAPID_OCR_TRIED:
            return _RAPID_OCR_ENGINE
        _RAPID_OCR_TRIED = True
        try:
            from rapidocr_onnxruntime import RapidOCR  # type: ignore[import-not-found]

            _RAPID_OCR_ENGINE = RapidOCR()
        except Exception as exc:
            logger.info("RapidOCR unavailable (falling back cleanly): %s", exc)
            _RAPID_OCR_ENGINE = None
        return _RAPID_OCR_ENGINE


# ---------------------------------------------------------------------------
# 1. PDF Native Vector Fraction / Equation Extraction
# ---------------------------------------------------------------------------

@dataclass
class _PdfSpan:
    text: str
    bbox: list[float]  # mm [x0, y0, x1, y1]
    size: float
    font: str


def _boxes_overlap(a: list[float], b: list[float], tol: float = 1.0) -> bool:
    return not (a[2] < b[0] + tol or a[0] > b[2] - tol or a[3] < b[1] + tol or a[1] > b[3] - tol)


def _format_pdf_span_group(spans: list[_PdfSpan]) -> str:
    """Order PDF spans left-to-right and format smaller-font trailing spans as subscripts/superscripts."""
    if not spans:
        return ""
    ordered = sorted(spans, key=lambda s: (s.bbox[0], s.bbox[1]))
    dom_size = max(s.size for s in ordered)
    parts: list[str] = []
    prev_cy: float | None = None
    prev_h: float = 0.0
    for sp in ordered:
        raw = sp.text.strip()
        if not raw:
            continue
        is_cjk = any("\u4e00" <= c <= "\u9fff" for c in raw)
        is_math_font = any(k in sp.font.lower() for k in ("math", "symbol", "cambria")) or has_math_alnum_chars(raw)

        # Handle two-char variable + subscript token like `𝑊𝑖(%) =` or `𝜌𝑠` or `𝑉𝑖 𝐶𝑖`
        sub_rendered = _format_token_with_inline_subs(raw, is_math_font=is_math_font)
        # Escape bare `%` so LaTeX parser never treats trailing tokens as comments
        sub_rendered = re.sub(r"(?<!\\)%", r"\\%", sub_rendered)
        sp_cy = 0.5 * (sp.bbox[1] + sp.bbox[3])
        sp_h = max(1.0, sp.bbox[3] - sp.bbox[1])

        if is_cjk and not parts and not is_math_font:
            parts.append(f"\\text{{{raw}}}")
            prev_cy, prev_h = sp_cy, sp_h
        elif sp.size <= dom_size * 0.78 and parts and len(raw) <= 6 and not raw.startswith("("):
            safe_sub = re.sub(r"(?<!\\)%", r"\\%", normalize_math_unicode(raw))
            if prev_cy is not None and sp_cy < prev_cy - max(0.45, 0.15 * prev_h):
                parts[-1] = f"{parts[-1]}^{{{safe_sub}}}"
            else:
                parts[-1] = f"{parts[-1]}_{{{safe_sub}}}"
        else:
            parts.append(sub_rendered)
            prev_cy, prev_h = sp_cy, sp_h
    return " ".join(parts).strip()


def _format_token_with_inline_subs(raw: str, *, is_math_font: bool) -> str:
    """Convert native math runs like `𝑉𝑖 𝐶𝑖` or `𝜌𝑠` into subscripted TeX `V_i C_i`, `\\rho_s`."""
    if not is_math_font and not has_math_alnum_chars(raw):
        return normalize_math_unicode(raw)

    norm = normalize_math_unicode(raw)
    # Match single base letter/command followed by single subscript letter (`Wi`, `Vi`, `Ci`, `Vs`, `Pw`, `\rho s`)
    out = re.sub(
        r"(\\(?:rho|alpha|beta|gamma|sigma|theta|Delta|pi|varphi)|[A-Za-z])\s*([ijkmnws0-9])\b",
        lambda m: f"{m.group(1)}_{m.group(2)}" if len(m.group(2)) == 1 else m.group(0),
        norm,
    )
    return out


def extract_pdf_native_math_blocks(
    page: fitz.Page,
    exclude_bboxes_mm: list[list[float]] | None = None,
) -> tuple[list[DocBlock], list[list[float]]]:
    """Detect native PDF equations built with drawn horizontal fraction bars + CambriaMath/text spans."""
    excl = list(exclude_bboxes_mm or [])
    page_w = float(page.rect.width) * PT_TO_MM

    try:
        drawings = page.get_drawings()
    except Exception:
        return [], []

    # Collect horizontal candidate bars (w >= 4mm, h <= 1.2mm) outside tables
    bars: list[list[float]] = []
    for d in drawings:
        rect = d.get("rect")
        if rect is None:
            continue
        bx0 = float(rect.x0) * PT_TO_MM
        by0 = float(rect.y0) * PT_TO_MM
        bx1 = float(rect.x1) * PT_TO_MM
        by1 = float(rect.y1) * PT_TO_MM
        bw = bx1 - bx0
        bh = max(0.05, by1 - by0)
        if bw < 4.0 or bw > page_w * 0.65 or bh > 1.2 or (bw / bh) < 4.5:
            continue
        bb = [bx0, by0, bx1, by1]
        if any(_boxes_overlap(bb, eb, tol=1.5) for eb in excl):
            continue
        bars.append(bb)

    if not bars:
        return [], []

    # Collect text spans from page
    spans: list[_PdfSpan] = []
    td = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    for b in td.get("blocks", []):
        if b.get("type") != 0:
            continue
        for ln in b.get("lines", []):
            for sp in ln.get("spans", []):
                txt = str(sp.get("text", "")).strip()
                if not txt:
                    continue
                sbox = [float(v) * PT_TO_MM for v in sp["bbox"]]
                if any(_boxes_overlap(sbox, eb, tol=1.0) for eb in excl):
                    continue
                spans.append(
                    _PdfSpan(
                        text=txt,
                        bbox=sbox,
                        size=float(sp.get("size", 11.0)),
                        font=str(sp.get("font", "")),
                    )
                )

    if not spans:
        return [], []

    formula_blocks: list[DocBlock] = []
    consumed_bboxes: list[list[float]] = []

    for bar in sorted(bars, key=lambda b: (b[1], b[0])):
        bx0, by0, bx1, by1 = bar
        ymid = 0.5 * (by0 + by1)

        num_spans: list[_PdfSpan] = []
        den_spans: list[_PdfSpan] = []
        for sp in spans:
            cx = 0.5 * (sp.bbox[0] + sp.bbox[2])
            cy = 0.5 * (sp.bbox[1] + sp.bbox[3])
            # Strictly inside fraction bar X extent; vertically centered operators & trailing RHS stay outside
            if not (bx0 - 0.8 <= cx <= bx1 + 0.6 and sp.bbox[0] <= bx1 + 0.8 and sp.bbox[2] >= bx0 - 0.8):
                continue
            if abs(cy - ymid) <= 1.2:
                continue
            if sp.bbox[3] <= ymid + 0.6 and (ymid - sp.bbox[3]) <= 5.5 and sp.bbox[1] >= ymid - 14.0:
                num_spans.append(sp)
            elif sp.bbox[1] >= ymid - 0.6 and (sp.bbox[1] - ymid) <= 5.5 and sp.bbox[3] <= ymid + 14.0:
                den_spans.append(sp)

        if not num_spans or not den_spans:
            continue

        num_txt = _format_pdf_span_group(num_spans)
        den_txt = _format_pdf_span_group(den_spans)
        if not num_txt or not den_txt or len(num_txt) > 55 or len(den_txt) > 55:
            continue

        frac_y0 = min(s.bbox[1] for s in num_spans + den_spans)
        frac_y1 = max(s.bbox[3] for s in num_spans + den_spans)
        row_h = max(6.0, frac_y1 - frac_y0)

        # Look for LHS and RHS inline spans aligned vertically with the fraction bar
        left_spans: list[_PdfSpan] = []
        right_spans: list[_PdfSpan] = []
        frac_span_ids = {id(s) for s in num_spans + den_spans}
        for sp in spans:
            if id(sp) in frac_span_ids:
                continue
            sp_ymid = 0.5 * (sp.bbox[1] + sp.bbox[3])
            if abs(sp_ymid - ymid) > max(4.5, row_h * 0.65):
                continue
            if sp.bbox[2] <= bx0 + 1.5 and (bx0 - sp.bbox[0]) <= 65.0 and len(sp.text) <= 28:
                left_spans.append(sp)
            elif sp.bbox[0] >= bx1 - 1.5 and (sp.bbox[2] - bx1) <= 55.0 and len(sp.text) <= 24:
                right_spans.append(sp)

        lhs = _format_pdf_span_group(left_spans)
        rhs = _format_pdf_span_group(right_spans)

        # Reject false positives that don't look like formulas
        has_math_signal = (
            "=" in lhs
            or "=" in rhs
            or any("math" in s.font.lower() or has_math_alnum_chars(s.text) for s in (num_spans + den_spans + left_spans))
        )
        if not has_math_signal:
            continue

        latex_parts = [p for p in (lhs, f"\\frac{{{num_txt}}}{{{den_txt}}}", rhs) if p]
        latex = " ".join(latex_parts).strip()

        used_spans = num_spans + den_spans + left_spans + right_spans
        eq_box = [
            round(min([bx0] + [s.bbox[0] for s in used_spans]), 2),
            round(min([by0] + [s.bbox[1] for s in used_spans]), 2),
            round(max([bx1] + [s.bbox[2] for s in used_spans]), 2),
            round(max([by1] + [s.bbox[3] for s in used_spans]), 2),
        ]
        consumed_bboxes.append([eq_box[0] - 0.5, eq_box[1] - 0.5, eq_box[2] + 0.5, eq_box[3] + 0.5])
        formula_blocks.append(
            DocBlock(
                block_id="",
                page_index=0,
                type="formula_block",
                bbox_mm=eq_box,
                latex=latex,
                ocr_source="pdf_native_math",
            )
        )

    return formula_blocks, consumed_bboxes


# ---------------------------------------------------------------------------
# 2. Raster Image Classification & Formula / Caption Recognition
# ---------------------------------------------------------------------------

def _detect_fraction_bars_in_image(fg_bool: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Detect horizontal fraction bars `(y0, y1, x0, x1)` with ink both above and below."""
    h, w = fg_bool.shape
    if h < 14 or w < 20:
        return []

    bars: list[tuple[int, int, int, int]] = []
    min_run = max(18, int(w * 0.055))

    y = 4
    while y < h - 4:
        row = fg_bool[y]
        padded = np.concatenate(([False], row, [False]))
        diffs = np.diff(padded.astype(np.int8))
        starts = np.nonzero(diffs == 1)[0]
        ends = np.nonzero(diffs == -1)[0] - 1
        max_y_end = y
        row_matched = False
        for sx, ex in zip(starts.tolist(), ends.tolist()):
            run_w = ex - sx + 1
            if run_w < min_run:
                continue
            # Check vertical thickness around (y, sx..ex) <= 5px and slender aspect >= 6
            y_end = y
            while y_end + 1 < h and float(np.mean(fg_bool[y_end + 1, sx : ex + 1])) > 0.65:
                y_end += 1
            thick = y_end - y + 1
            if thick > 5 or (run_w / max(1, thick)) < 6.0:
                continue
            # Require genuine ink both directly above AND directly below (within 2..9px)
            above = fg_bool[max(0, y - 9) : max(0, y - 1), sx : ex + 1]
            below = fg_bool[min(h, y_end + 2) : min(h, y_end + 10), sx : ex + 1]
            if int(np.count_nonzero(above)) >= 3 and int(np.count_nonzero(below)) >= 3:
                cand = (y, y_end + 1, int(sx), int(ex + 1))
                # Deduplicate overlapping bars already recorded on adjacent rows
                dup = any(
                    abs(b[0] - cand[0]) <= 4 and min(b[3], cand[3]) - max(b[2], cand[2]) > 8
                    for b in bars
                )
                if not dup:
                    bars.append(cand)
                row_matched = True
                if y_end > max_y_end:
                    max_y_end = y_end
        y = (max_y_end + 2) if row_matched else (y + 1)
    return bars


@dataclass
class _OcrBox:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    score: float = 1.0


_CJK_VISUAL_CONFUSABLES: list[frozenset[str]] = [
    frozenset({"皿", "血", "Ⅲ", "III"}),
    frozenset({"重", "量"}),
    frozenset({"干", "千", "于"}),
    frozenset({"湿", "温"}),
    frozenset({"筒", "简"}),
    frozenset({"未", "末"}),
    frozenset({"己", "已", "巳"}),
    frozenset({"日", "曰"}),
    frozenset({"土", "士"}),
    frozenset({"水", "永"}),
    frozenset({"烧", "绕", "浇"}),
    frozenset({"灰", "炭"}),
]


def _are_visually_confusable(ch_a: str, ch_b: str) -> bool:
    if ch_a == ch_b:
        return True
    if not ("\u4e00" <= ch_a <= "\u9fff"):
        return True  # stray Roman numeral / symbol inside CJK run (e.g. `Ⅲ`)
    for grp in _CJK_VISUAL_CONFUSABLES:
        if ch_a in grp and ch_b in grp:
            return True
    return False


def build_cjk_lexicon(text: str) -> set[str]:
    """Collect 2..8 char CJK terms & n-grams from surrounding prose / document text."""
    lex: set[str] = set()
    if not text:
        return lex
    for m in re.finditer(r"[\u4e00-\u9fff]{2,24}", text):
        run = m.group(0)
        n = len(run)
        if n <= 8:
            lex.add(run)
        for length in range(2, min(9, n + 1)):
            for i in range(0, n - length + 1):
                lex.add(run[i : i + length])
    return lex


def _align_cjk_phrase_with_lexicon(
    phrase: str,
    score: float,
    local_lexicon: set[str],
    doc_lexicon: set[str],
) -> tuple[str, bool]:
    """Snap a single OCR CJK/confusable phrase to a unique distance-1 term in context."""
    # Expand Roman-numeral `Ⅲ`/`II`/`Ⅰ` embedded in CJK runs via `?` wildcard match first
    clean = phrase.strip()
    if len(clean) < 3:
        return clean, False
    if clean in local_lexicon or (len(clean) >= 3 and clean in doc_lexicon):
        return clean, False

    def _find_unique(lex: set[str], *, require_confusable: bool) -> str | None:
        matches: list[str] = []
        n = len(clean)
        for cand in lex:
            if len(cand) != n:
                continue
            diffs = [(ca, cb) for ca, cb in zip(clean, cand) if ca != cb]
            if len(diffs) != 1:
                continue
            ca, cb = diffs[0]
            if require_confusable and not _are_visually_confusable(ca, cb):
                continue
            matches.append(cand)
            if len(matches) > 1:
                return None
        return matches[0] if len(matches) == 1 else None

    # 1. Local immediate context: confusable OR low score
    hit = _find_unique(local_lexicon, require_confusable=(score >= 0.88))
    if hit:
        return hit, True

    # 2. Document-wide lexicon: strict confusable OR low score guard prevents false edits like 出气道->出气口
    if doc_lexicon:
        hit = _find_unique(doc_lexicon, require_confusable=(score >= 0.85))
        if hit:
            return hit, True

    return clean, False


def _align_text_runs_with_lexicon(
    text: str,
    score: float,
    *,
    local_lexicon: set[str],
    doc_lexicon: set[str],
) -> tuple[str, bool]:
    """Align embedded CJK (+ occasional Roman-numeral noise) phrases inside OCR text lines."""
    if not text or (not local_lexicon and not doc_lexicon):
        return text, False
    changed = False

    def _repl(m: re.Match[str]) -> str:
        nonlocal changed
        raw_seg = m.group(0)
        # Try normalized Roman numeral -> candidate wildcard check or direct alignment
        norm_seg = raw_seg.replace("III", "Ⅲ")
        aligned, did = _align_cjk_phrase_with_lexicon(norm_seg, score, local_lexicon, doc_lexicon)
        if did:
            changed = True
            return aligned
        return raw_seg

    out = re.sub(r"[\u4e00-\u9fffⅠⅡⅢⅣⅤ]+", _repl, text)
    return out, changed


def _preprocess_for_rapid_ocr(img: Image.Image) -> tuple[Image.Image, float]:
    """Upscale low-res formula/caption crops for sharper CJK RapidOCR detection."""
    rgb = img.convert("RGB")
    w, h = rgb.size
    scale = 1.0
    if h < 96:
        target_h = min(180, max(110, int(round(h * 2.5))))
        scale = target_h / max(1, h)
        target_w = max(8, int(round(w * scale)))
        rgb = rgb.resize((target_w, target_h), Image.Resampling.LANCZOS)
        rgb = ImageOps.autocontrast(rgb, cutoff=1)
        rgb = rgb.filter(ImageFilter.UnsharpMask(radius=1.0, percent=120, threshold=3))
    pad = 24
    padded = ImageOps.expand(rgb, border=pad, fill=(255, 255, 255))
    return padded, scale


def _preprocess_for_latex_ocr(row_img: Image.Image) -> Image.Image:
    """Keep RapidLaTeXOCR in its calibrated glyph height sweet-spot (no blind upscaling)."""
    rgb = row_img.convert("RGB")
    w, h = rgb.size
    if h < 34:
        sc = 44.0 / max(1, h)
        rgb = rgb.resize((max(8, int(round(w * sc))), 44), Image.Resampling.LANCZOS)
    elif h > 115:
        sc = 84.0 / max(1, h)
        rgb = rgb.resize((max(8, int(round(w * sc))), 84), Image.Resampling.LANCZOS)
    return ImageOps.expand(rgb, border=(16, 12), fill=(255, 255, 255))


def _run_rapid_ocr_boxes(img: Image.Image, *, preprocess: bool = False) -> list[_OcrBox]:
    engine = _get_rapid_ocr()
    if engine is None:
        return []
    work_img = img
    scale = 1.0
    pad = 0
    if preprocess:
        work_img, scale = _preprocess_for_rapid_ocr(img)
        pad = 24
    try:
        arr = np.asarray(work_img.convert("RGB"))
        res, _ = engine(arr)
    except Exception:
        return []
    out: list[_OcrBox] = []
    for item in res or []:
        if not item or len(item) < 2:
            continue
        quad, txt = item[0], str(item[1]).strip()
        if not txt:
            continue
        score = float(item[2]) if len(item) >= 3 and item[2] is not None else 1.0
        xs = [(float(p[0]) - pad) / scale for p in quad]
        ys = [(float(p[1]) - pad) / scale for p in quad]
        out.append(_OcrBox(x0=min(xs), y0=min(ys), x1=max(xs), y1=max(ys), text=txt, score=score))
    return out


def _split_stacked_rows(gray: Image.Image) -> list[Image.Image]:
    """Split stacked multi-line equation images while preserving small superscript/limit bands."""
    arr = np.asarray(gray)
    h, w = arr.shape
    if h < 48:
        return [gray]

    ink_mask = arr < 200
    row_ink = ink_mask.sum(axis=1)

    # 1. Retain ALL vertical ink bands >= 2px tall with >= 4 ink pixels (never drop small `^n` limits!)
    raw_bands: list[tuple[int, int, int, int]] = []  # (y0, y1, x0, x1)
    in_band = False
    start = 0
    for y in range(h):
        if row_ink[y] >= 2 and not in_band:
            in_band = True
            start = y
        elif row_ink[y] <= 1 and in_band:
            in_band = False
            if y - start >= 2:
                sub = ink_mask[start:y]
                if int(sub.sum()) >= 4:
                    xs = np.nonzero(sub.any(axis=0))[0]
                    raw_bands.append((start, y, int(xs[0]), int(xs[-1]) + 1))
    if in_band and h - start >= 2:
        sub = ink_mask[start:h]
        if int(sub.sum()) >= 4:
            xs = np.nonzero(sub.any(axis=0))[0]
            raw_bands.append((start, h, int(xs[0]), int(xs[-1]) + 1))

    if len(raw_bands) <= 1:
        return [gray]

    max_bh = max(b[1] - b[0] for b in raw_bands)
    major_thresh = max(12, int(round(max_bh * 0.40)))
    majors = [b for b in raw_bands if (b[1] - b[0]) >= major_thresh]
    if len(majors) <= 1:
        # Attach everything into one coherent row
        return [gray]

    # 2. First merge major bands separated only by small intra-equation gaps (numerator/bar/denominator)
    minor_gap = max(6, int(h * 0.045))
    major_groups: list[list[int]] = []
    for y0, y1, x0, x1 in majors:
        if major_groups and (y0 - major_groups[-1][1]) < minor_gap:
            g = major_groups[-1]
            g[1] = max(g[1], y1)
            g[2] = min(g[2], x0)
            g[3] = max(g[3], x1)
        else:
            major_groups.append([y0, y1, x0, x1])

    # 3. Attach small satellite bands (e.g. superscript `^n`, subscript `i=1`, accents) to nearest overlapping major group
    satellites = [b for b in raw_bands if (b[1] - b[0]) < major_thresh]
    max_sat_gap = max(14, int(h * 0.16))
    for sy0, sy1, sx0, sx1 in satellites:
        sat_w = max(1, sx1 - sx0)
        best_idx = -1
        best_dist = 10**9
        for gi, (gy0, gy1, gx0, gx1) in enumerate(major_groups):
            if sy1 <= gy0:
                dist = gy0 - sy1
            elif sy0 >= gy1:
                dist = sy0 - gy1
            else:
                dist = 0
            if dist > max_sat_gap:
                continue
            x_ov = max(0, min(sx1, gx1) - max(sx0, gx0))
            if (x_ov / sat_w) >= 0.40 or (sx0 >= gx0 - 12 and sx1 <= gx1 + 12):
                if dist < best_dist:
                    best_dist = dist
                    best_idx = gi
        if best_idx >= 0:
            g = major_groups[best_idx]
            g[0] = min(g[0], sy0)
            g[1] = max(g[1], sy1)
            g[2] = min(g[2], sx0)
            g[3] = max(g[3], sx1)

    major_groups.sort(key=lambda g: g[0])
    merged_groups: list[list[int]] = []
    for g in major_groups:
        if merged_groups and g[0] <= merged_groups[-1][1] + 4:
            prev = merged_groups[-1]
            prev[1] = max(prev[1], g[1])
            prev[2] = min(prev[2], g[2])
            prev[3] = max(prev[3], g[3])
        else:
            merged_groups.append(g)

    if len(merged_groups) <= 1:
        return [gray]

    rows: list[Image.Image] = []
    for y0, y1, _, _ in merged_groups:
        pad = 4
        rows.append(gray.crop((0, max(0, y0 - pad), w, min(h, y1 + pad))))
    return rows


def classify_raster_image(
    image_path: str | Path,
    bbox_mm: list[float] | None = None,
    *,
    prev_text: str = "",
    next_text: str = "",
) -> Literal["formula", "text_caption", "figure"]:
    """Distinguish equation crops and scanned text captions from true engineering figures/charts."""
    path = Path(image_path)
    if not path.is_file():
        return "figure"

    try:
        with Image.open(path) as im:
            rgb = im.convert("RGB")
            w_px, h_px = rgb.size
            rgb_arr = np.asarray(rgb, dtype=np.float32)
            gray_arr = np.asarray(rgb.convert("L"), dtype=np.float32)
    except Exception:
        return "figure"

    if bbox_mm and len(bbox_mm) == 4:
        w_mm = max(1.0, float(bbox_mm[2]) - float(bbox_mm[0]))
        h_mm = max(1.0, float(bbox_mm[3]) - float(bbox_mm[1]))
    else:
        w_mm = w_px * 25.4 / 150.0
        h_mm = h_px * 25.4 / 150.0

    aspect = w_mm / max(0.5, h_mm)
    # 1. Strong physical geometry & figure-caption guards -> always figure
    if h_mm > 34.0 or w_mm < 6.0 or h_mm < 3.5 or aspect < 1.25:
        return "figure"
    nxt_clean = (next_text or "").strip()
    if re.match(r"^图\s*\d", nxt_clean):
        return "figure"

    # 2. Color & ink density check: real equations are crisp black-on-white
    chan_spread = np.max(rgb_arr, axis=2) - np.min(rgb_arr, axis=2)
    color_sat_ratio = float(np.mean(chan_spread > 32.0))
    white_ratio = float(np.mean(gray_arr > 230.0))
    ink_ratio = float(np.mean(gray_arr < 185.0))
    if color_sat_ratio > 0.12 or white_ratio < 0.55 or ink_ratio > 0.35:
        return "figure"

    has_math_ctx = bool(
        re.search(r"(?:公式|下式|关系式|计算(?:如下|公式)?|按下式)", prev_text or "")
        or re.match(r"^(?:式中|其中|[（(]式\s*\d)", nxt_clean)
    )

    ocr_boxes = _run_rapid_ocr_boxes(Image.fromarray(gray_arr.astype(np.uint8)), preprocess=True)
    ocr_joined = " ".join(b.text for b in ocr_boxes)
    has_math_tokens = bool(re.search(r"[=∑∫∏√±×÷≤≥≠≈%]", ocr_joined))

    # Check numbered diagram legend (e.g. `1—筒；2—盖；...`) BEFORE fraction-bar heuristics
    if (
        not has_math_tokens
        and not has_math_ctx
        and ocr_boxes
        and (re.search(r"[；;].*[；;]", ocr_joined) or len(re.findall(r"\d\s*[—\-一]", ocr_joined)) >= 2)
    ):
        return "text_caption"

    fg_bool = gray_arr < 180.0
    frac_bars = _detect_fraction_bars_in_image(fg_bool)

    if frac_bars or has_math_tokens:
        return "formula"

    if has_math_ctx:
        return "formula"

    return "figure"


def recognize_text_caption_image(
    image_path: str | Path,
    *,
    section_text: str = "",
    doc_lexicon: set[str] | None = None,
) -> str:
    """Extract clean readable text lines from a raster legend/caption image."""
    path = Path(image_path)
    if not path.is_file():
        return ""
    try:
        with Image.open(path) as im:
            boxes = _run_rapid_ocr_boxes(im.convert("RGB"), preprocess=True)
    except Exception:
        return ""
    if not boxes:
        return ""
    boxes.sort(key=lambda b: (round(b.y0 / 12.0), b.x0))
    # Drop narrow duplicate/split single-digit boxes that overlap the start of a longer box on the same line
    dedup: list[_OcrBox] = []
    for b in boxes:
        if len(b.text) <= 2 and b.text.rstrip("-—一").isdigit():
            overlapped = any(
                other is not b
                and len(other.text) > len(b.text)
                and abs(other.y0 - b.y0) < 10.0
                and b.x0 >= other.x0 - 12.0
                and b.x1 <= other.x1 + 12.0
                for other in boxes
            )
            if overlapped:
                continue
        dedup.append(b)

    local_lex = build_cjk_lexicon(section_text)
    full_doc_lex = doc_lexicon or set()
    aligned_parts: list[str] = []
    for b in dedup:
        txt = b.text
        if local_lex or full_doc_lex:
            txt, _ = _align_text_runs_with_lexicon(
                txt, b.score, local_lexicon=local_lex, doc_lexicon=full_doc_lex
            )
        aligned_parts.append(txt)

    joined = " ".join(aligned_parts)
    # Collapse stuttered digits and standardize `1—部件` legend separators
    joined = re.sub(r"\b(\d)(?:\s+\1)+\s*([—\-一])", r"\1—", joined)
    joined = re.sub(r"(\d)\s*[—\-一]+\s*([\u4e00-\u9fff])", r"\1—\2", joined)
    joined = re.sub(r"\s*([；;，,])\s*", r"\1 ", joined)
    return re.sub(r"\s+", " ", joined).strip()


@dataclass(frozen=True)
class _SymbolDef:
    base: str
    index_char: str
    cjk_sub: str
    is_paren: bool


def _extract_symbol_table(ctx_text: str) -> dict[str, list[_SymbolDef]]:
    """Parse variable subscript definitions from surrounding text for ANY variable letter."""
    table: dict[str, list[_SymbolDef]] = {}
    if not ctx_text:
        return table

    # Normalize inline LaTeX wrappers (`M_{j(\text{湿})}` -> `Mj(湿)`, `C_{\text{卡}}` -> `C卡`)
    norm_ctx = ctx_text.replace("$", "")
    norm_ctx = re.sub(r"\\(?:text|mathrm|mathbf|mathit)\{([^}]*)\}", r"\1", norm_ctx)
    norm_ctx = re.sub(r"_\s*\{([^{}]*)\}", r"\1", norm_ctx)
    norm_ctx = re.sub(r"_\s*([A-Za-z0-9])", r"\1", norm_ctx)
    norm_ctx = re.sub(r"[{}]", "", norm_ctx)

    def _add(entry: _SymbolDef) -> None:
        lst = table.setdefault(entry.base, [])
        if entry not in lst:
            lst.append(entry)

    for src in (ctx_text, norm_ctx):
        # Pattern 1: Mj（湿）, Ci(水), C(水)
        for m in re.finditer(r"([A-Za-z])([A-Za-z0-9]?)\s*[（(]\s*([\u4e00-\u9fff]{1,3})\s*[）)]", src):
            _add(_SymbolDef(base=m.group(1), index_char=m.group(2), cjk_sub=m.group(3), is_paren=True))

        # Pattern 2: `C 卡--`, `C卡——`, `Q总：`
        for m in re.finditer(r"([A-Za-z])\s*([\u4e00-\u9fff]{1,2})\s*(?:-+|—+|–+|[：:=])", src):
            _add(_SymbolDef(base=m.group(1), index_char="", cjk_sub=m.group(2), is_paren=False))

    return table


def _extract_context_subscript_defs(prev_text: str, next_text: str) -> dict[str, list[str]]:
    """Backward-compatible wrapper returning ordered CJK subscript labels per base letter."""
    tbl = _extract_symbol_table(f"{prev_text}\n{next_text}")
    return {
        k: list(dict.fromkeys(d.cjk_sub for d in defs))
        for k, defs in tbl.items()
    }


def _extract_row_ocr_subscripts(ocr_boxes: list[_OcrBox], sym_table: dict[str, list[_SymbolDef]]) -> list[_SymbolDef]:
    """Extract ordered subscript sightings directly from RapidOCR boxes on the formula row."""
    found: list[_SymbolDef] = []
    ordered = sorted(ocr_boxes, key=lambda b: b.x0)
    known_by_base = {base: {d.cjk_sub for d in defs} for base, defs in sym_table.items()}
    for box in ordered:
        txt = box.text
        # Match `Ci(水)`, `Ci湿)`, `C(水)`, `Mj（湿）`, `C卡` left-to-right within the box
        for m in re.finditer(
            r"([A-Za-z])([ijkmnws0-9]?)\s*([（(]?)\s*([\u4e00-\u9fff]{1,2})\s*([）)]?)",
            txt,
        ):
            base, idx_ch, lp, sub, rp = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
            has_paren = bool(lp or rp)
            if not has_paren and sub not in known_by_base.get(base, set()):
                continue
            found.append(_SymbolDef(base=base, index_char=idx_ch, cjk_sub=sub, is_paren=has_paren))
    return found


_GARBLED_SUB_SIGNAL_RE = re.compile(
    r"\\star|\\mp|\\tiny|\\infty|\\mathbb|\\mathcal|\\Re|\\mathrm\{\(|\\left\(|(?<!\w)[A-Za-z]{2,}(?!\w)"
)
_PHANTOM_SUP_RE = re.compile(r"(?:\(z\)|\\mathrm\{\(|\\mathbb|\\mathcal|\\tiny)")


def _repair_latex_subscripts_with_context(
    tex: str,
    ocr_boxes: list[_OcrBox],
    sym_table: dict[str, list[_SymbolDef]],
) -> str:
    """Repair OCR-garbled CJK subscripts/phantom superscripts generally using SymbolTable + RapidOCR row hits."""
    if not tex or not sym_table:
        return tex

    row_hits = _extract_row_ocr_subscripts(ocr_boxes, sym_table)
    row_consumed = [False] * len(row_hits)
    sym_cursors: dict[str, int] = {}

    pattern = re.compile(
        r"([A-Za-z])\s*_\s*\{((?:[^{}]|\{[^{}]*\})*)\}(\s*\^\s*\{((?:[^{}]|\{[^{}]*\})*)\})?"
    )

    def _pick_def(base: str, idx_char: str, has_paren_or_sym: bool) -> _SymbolDef | None:
        # 1. Prefer unmatched RapidOCR sighting on THIS exact row matching `(base, idx_char)`
        for hi, hit in enumerate(row_hits):
            if row_consumed[hi]:
                continue
            if hit.base == base and (not idx_char or hit.index_char == idx_char or not hit.index_char):
                row_consumed[hi] = True
                return hit

        # 2. Fallback to contextual SymbolTable definitions (cycling cleanly via cursor)
        defs = sym_table.get(base, [])
        if not defs:
            return None
        filtered = [d for d in defs if not idx_char or d.index_char == idx_char] or defs
        cur = sym_cursors.get(f"{base}:{idx_char}", 0)
        sym_cursors[f"{base}:{idx_char}"] = cur + 1
        chosen = filtered[cur % len(filtered)]
        if has_paren_or_sym and not chosen.is_paren:
            return chosen
        return chosen

    def _repl(m: re.Match[str]) -> str:
        base = m.group(1)
        sub_body = m.group(2)
        sup_full = m.group(3) or ""
        sup_body = m.group(4) or ""
        if base not in sym_table:
            return m.group(0)

        # Preserve clean single-letter/numeric non-paren subscripts (like `Q_{\mathrm{v}}`) unless `C_{\star}`
        has_garble = bool(_GARBLED_SUB_SIGNAL_RE.search(sub_body)) or (
            "(" in sub_body and not re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9()\\text{}]+", sub_body)
        ) or ("(" in sub_body and "\\text" not in sub_body)
        if not has_garble:
            return m.group(0)

        idx_match = re.match(r"^\s*([ijkmnws])\b", sub_body)
        idx_char = idx_match.group(1) if idx_match else ""
        has_paren = "(" in sub_body or r"\left(" in sub_body

        chosen = _pick_def(base, idx_char, has_paren)
        if chosen is None:
            return m.group(0)

        eff_idx = idx_char or chosen.index_char
        if chosen.is_paren:
            new_sub = f"{eff_idx}(\\text{{{chosen.cjk_sub}}})"
        else:
            new_sub = f"{eff_idx}\\text{{{chosen.cjk_sub}}}" if eff_idx else f"\\text{{{chosen.cjk_sub}}}"

        # Keep legitimate powers (`^2`, `^n`), strip phantom CJK-split superscripts like `^{\mathrm{(z)}}`
        keep_sup = sup_full if (sup_body and not _PHANTOM_SUP_RE.search(sup_body)) else ""
        return f"{base}_{{{new_sub}}}{keep_sup}"

    out = pattern.sub(_repl, tex)

    # Post-pass: resolve identical subtraction `M_{j(\text{湿})} - M_{j(\text{湿})}` -> second becomes distinct counterpart (`干`)
    dup_sub_re = re.compile(
        r"([A-Za-z])_\{([ijkmnws]?)\(\\text\{([\u4e00-\u9fff]{1,3})\}\)\}\s*-\s*\1_\{\2\(\\text\{\3\}\)\}"
    )

    def _fix_dup_sub(dm: re.Match[str]) -> str:
        base, idx_ch, cjk = dm.group(1), dm.group(2), dm.group(3)
        defs = sym_table.get(base, [])
        alt = next(
            (d for d in defs if d.cjk_sub != cjk and (not idx_ch or not d.index_char or d.index_char == idx_ch)),
            None,
        )
        if alt is None:
            return dm.group(0)
        eff_idx = idx_ch or alt.index_char
        right = (
            f"{base}_{{{eff_idx}(\\text{{{alt.cjk_sub}}})}}"
            if alt.is_paren
            else f"{base}_{{{eff_idx}\\text{{{alt.cjk_sub}}}}}"
        )
        return f"{base}_{{{idx_ch}(\\text{{{cjk}}})}} - {right}"

    return dup_sub_re.sub(_fix_dup_sub, out)


def _clean_latex_ocr_output(raw: str) -> str:
    tex = raw.strip()
    # Clean spurious spacing / macro artifacts from LaTeXOCR
    tex = tex.replace(r"\;", " ").replace(r"\,", " ")
    tex = re.sub(r"\\operatorname\*?\s*\{([^}]*)\}", lambda m: f"\\text{{{m.group(1)}}}", tex)
    # Fix `\times100 9_{0}` / `\times100 I_{0}` / `\times100 \bar{\nu}_{0}` -> `\times 100\%`
    tex = re.sub(
        r"(?<!\d)(100\s*)(?:9_\{?0\}?|I_\{?0\}?|l_\{?0\}?|g_\{?0\}?|\\mathcal\{I\}_\{?0\}?|\\bar\{\\nu\}_\{?0\}?|\\nu_\{?0\}?)",
        lambda m: f"{m.group(1)}\\%",
        tex,
    )
    if "=" in tex or r"\frac" in tex:
        tex = re.sub(
            r"([A-Za-z0-9}\)])\s*\\longrightarrow\s*([A-Za-z0-9{\(\\-])",
            lambda m: f"{m.group(1)} - {m.group(2)}",
            tex,
        )
    tex = re.sub(r"\{\\cal\s+([A-Za-z])\}", lambda m: m.group(1), tex)
    tex = re.sub(r"\\mathcal\{([A-Za-z])\}", lambda m: m.group(1), tex)
    tex = re.sub(r"(\d)\.\s+(\d)", lambda m: f"{m.group(1)}.{m.group(2)}", tex)
    tex = re.sub(r"\s+", " ", tex).strip()
    return tex


def _geom_reconstruct_hybrid_row(
    row_img: Image.Image,
    ocr_boxes: list[_OcrBox],
    frac_bars: list[tuple[int, int, int, int]],
    ctx_text: str,
    *,
    doc_lexicon: set[str] | None = None,
) -> tuple[str | None, bool]:
    """Reconstruct Chinese+math horizontal fraction formulas geometrically from RapidOCR boxes & bars."""
    if not frac_bars or not ocr_boxes:
        return None, False

    local_lex = build_cjk_lexicon(ctx_text)
    full_doc_lex = doc_lexicon or set()
    used: set[int] = set()
    pieces: list[tuple[float, str]] = []
    ctx_aligned = False

    def _fmt_seg(txt: str, score: float) -> str:
        nonlocal ctx_aligned
        t = txt.strip()
        if local_lex or full_doc_lex:
            t, did = _align_text_runs_with_lexicon(
                t, score, local_lexicon=local_lex, doc_lexicon=full_doc_lex
            )
            if did:
                ctx_aligned = True
        combined_ctx = (ctx_text + " " + " ".join(b.text for b in ocr_boxes)).replace(" ", "")
        if any(k in combined_ctx for k in ("m³", "kg/m3", "m3", "容重", "容量")):
            t = re.sub(r"kg/m[²2\?]", "kg/m^3", t)
        t = t.replace("（", "(").replace("）", ")").replace("X", r"\times").replace("×", r"\times")
        t = re.sub(r"[\u4e00-\u9fff]+", lambda m: f"\\text{{{m.group(0)}}}", t)
        return t

    h = row_img.height
    for (by0, by1, bx0, bx1) in sorted(frac_bars, key=lambda b: b[2]):
        ymid = 0.5 * (by0 + by1)
        nums: list[_OcrBox] = []
        dens: list[_OcrBox] = []
        for idx, b in enumerate(ocr_boxes):
            if idx in used:
                continue
            cx = 0.5 * (b.x0 + b.x1)
            cy = 0.5 * (b.y0 + b.y1)
            if not (bx0 - 14 <= cx <= bx1 + 14):
                continue
            if cy < ymid and (by0 - b.y1) < h * 0.45:
                nums.append(b)
                used.add(idx)
            elif cy >= ymid and (b.y0 - by1) < h * 0.45:
                dens.append(b)
                used.add(idx)
        num_str = " ".join(_fmt_seg(n.text, n.score) for n in sorted(nums, key=lambda z: z.x0))
        den_str = " ".join(_fmt_seg(d.text, d.score) for d in sorted(dens, key=lambda z: z.x0))
        if num_str and den_str:
            pieces.append((bx0, f"\\frac{{{num_str}}}{{{den_str}}}"))

    for idx, b in enumerate(ocr_boxes):
        if idx not in used:
            pieces.append((b.x0, _fmt_seg(b.text, b.score)))

    if not pieces:
        return None, False
    pieces.sort(key=lambda p: p[0])

    # Insert `\sum` before large gaps between two adjacent fractions if RapidOCR missed Sigma
    out_strs: list[str] = []
    for k, (px, s) in enumerate(pieces):
        if k > 0 and pieces[k - 1][1].startswith(r"\frac") and s.startswith(r"\frac"):
            if px - pieces[k - 1][0] > row_img.width * 0.14:
                out_strs.append(r"\sum")
        out_strs.append(s)

    return re.sub(r"\s+", " ", " ".join(out_strs)).strip(), ctx_aligned


def _recognize_single_row(
    row_img: Image.Image,
    *,
    ctx_text: str,
    sym_table: dict[str, list[_SymbolDef]],
    doc_lexicon: set[str] | None = None,
) -> tuple[str, str]:
    """Recognize one horizontal formula row via RapidOCR + RapidLaTeXOCR."""
    gray = row_img.convert("L")
    fg_bool = np.asarray(gray, dtype=np.float32) < 180.0
    frac_bars = _detect_fraction_bars_in_image(fg_bool)
    ocr_boxes = _run_rapid_ocr_boxes(row_img.convert("RGB"), preprocess=True)

    cjk_phrases = [
        b.text for b in ocr_boxes if len(re.findall(r"[\u4e00-\u9fff]", b.text)) >= 2
    ]
    total_cjk_chars = sum(len(re.findall(r"[\u4e00-\u9fff]", b.text)) for b in ocr_boxes)

    # Case A: Heavy Chinese labels inside equation -> geometric RapidOCR + fraction reconstruction
    if total_cjk_chars >= 5 and cjk_phrases and frac_bars:
        hybrid, ctx_aligned = _geom_reconstruct_hybrid_row(
            row_img, ocr_boxes, frac_bars, ctx_text, doc_lexicon=doc_lexicon
        )
        if hybrid:
            return hybrid, ("formula_ocr_hybrid+ctx" if ctx_aligned else "formula_ocr_hybrid")

    # Case B: Run LaTeXOCR at its optimal natural scale (no blind upscaling!)
    latex_engine = _get_latex_ocr()
    if latex_engine is not None:
        try:
            pad_im = _preprocess_for_latex_ocr(row_img)
            buf = io.BytesIO()
            pad_im.save(buf, format="PNG")
            raw_tex, _ = latex_engine(buf.getvalue())
            tex = _clean_latex_ocr_output(str(raw_tex or ""))

            # Merge any extra subscript definitions spotted by RapidOCR inside this row
            merged_tbl: dict[str, list[_SymbolDef]] = {k: list(v) for k, v in sym_table.items()}
            row_tbl = _extract_symbol_table(" ".join(b.text for b in ocr_boxes))
            for k, defs in row_tbl.items():
                dst = merged_tbl.setdefault(k, [])
                for d in defs:
                    if d not in dst:
                        dst.append(d)

            tex = _repair_latex_subscripts_with_context(tex, ocr_boxes, merged_tbl)
            if tex:
                return tex, "rapid_latex_ocr"
        except Exception as exc:
            logger.debug("LaTeXOCR row recognition failed: %s", exc)

    # Case C: Geometric / RapidOCR fallback
    if ocr_boxes:
        ordered = sorted(ocr_boxes, key=lambda b: b.x0)
        return normalize_math_unicode(" ".join(b.text for b in ordered)), "rapidocr_fallback"
    return r"\text{公式待校对}", "formula_pending"


def recognize_formula_image(
    image_path: str | Path,
    *,
    prev_text: str = "",
    next_text: str = "",
    section_text: str = "",
    doc_lexicon: set[str] | None = None,
) -> tuple[str, str]:
    """Recognize a mathematical formula image into editable LaTeX `(latex, ocr_source)`."""
    path = Path(image_path)
    if not path.is_file():
        return r"\text{公式待校对}", "formula_pending"

    try:
        with Image.open(path) as im:
            gray = im.convert("L")
    except Exception:
        return r"\text{公式待校对}", "formula_pending"

    ctx_text = f"{prev_text}\n{next_text}\n{section_text}".strip()
    sym_table = _extract_symbol_table(f"{prev_text}\n{next_text}")
    rows = _split_stacked_rows(gray)

    row_results: list[tuple[str, str]] = []
    for row_img in rows:
        tex, src = _recognize_single_row(
            row_img,
            ctx_text=ctx_text,
            sym_table=sym_table,
            doc_lexicon=doc_lexicon,
        )
        if tex:
            row_results.append((tex, src))

    if not row_results:
        return r"\text{公式待校对}", "formula_pending"
    if len(row_results) == 1:
        return row_results[0]

    body = r" \\ ".join(tex for tex, _ in row_results)
    sources = "+".join(dict.fromkeys(src for _, src in row_results))
    return f"\\begin{{aligned}} {body} \\end{{aligned}}", sources
