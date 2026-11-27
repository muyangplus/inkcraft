"""Page rules, paper geometry, page scopes, and writer selector pooling."""

from __future__ import annotations

from typing import Callable

from inkcraft.api.schemas import LayoutConfig, MissingGlyphBox, PageRuleOverride, WritingRegion
from inkcraft.layout.math_box import MathLayout
from inkcraft.layout.math_typesetter import translate_math_missing
from inkcraft.writers.selector import MixedVariantSelector, VariantSelector
from hwfont_sdk.reader import HwFontReader

ComposeProgressCB = Callable[[str, float, str], None]
WriterResolver = Callable[[str | None], HwFontReader | None]
SelectorEntry = tuple[VariantSelector, float, float, str | None]
SelectorGetter = Callable[[str | None], SelectorEntry]

SKIP_IN_REFLOW = frozenset({"header", "footer", "page_number", "discarded"})

_PAGE_SIZES_MM: dict[str, tuple[float, float]] = {
    "A4": (210.0, 297.0),
    "A5": (148.0, 210.0),
    "B5": (176.0, 250.0),
    "Letter": (215.9, 279.4),
}


def resolve_page_size(config: LayoutConfig) -> tuple[float, float]:
    if config.page.size == "custom":
        w, h = float(config.page.width_mm), float(config.page.height_mm)
    elif config.page.size in _PAGE_SIZES_MM:
        pw, ph = _PAGE_SIZES_MM[config.page.size]
        if abs(config.page.width_mm - pw) > 0.5 or abs(config.page.height_mm - ph) > 0.5:
            w, h = float(config.page.width_mm), float(config.page.height_mm)
        else:
            w, h = pw, ph
    else:
        w, h = float(config.page.width_mm), float(config.page.height_mm)
    if config.page.orientation == "landscape" and w < h:
        w, h = h, w
    elif config.page.orientation == "portrait" and w > h:
        w, h = h, w
    return float(w), float(h)


def matches_page_scope(scope: str, page_index: int) -> bool:
    """Return True if 0-based `page_index` matches a WritingRegion `page_scope`."""
    raw = (scope or "all").strip().lower()
    if not raw or raw in {"all", "*", "every"}:
        return True
    p1 = page_index + 1
    for tok in raw.split(","):
        t = tok.strip()
        if not t:
            continue
        if t == "first":
            if p1 == 1:
                return True
        elif t == "rest":
            if p1 >= 2:
                return True
        elif t == "odd":
            if p1 % 2 == 1:
                return True
        elif t == "even":
            if p1 % 2 == 0:
                return True
        elif t.endswith("+") and t[:-1].isdigit():
            if p1 >= int(t[:-1]):
                return True
        elif "-" in t:
            a, b = t.split("-", 1)
            if a.strip().isdigit() and b.strip().isdigit():
                if int(a.strip()) <= p1 <= int(b.strip()):
                    return True
        elif t.isdigit() and p1 == int(t):
            return True
    return False


def max_explicit_region_page(regions: list[WritingRegion]) -> int:
    """Highest explicit 0-based page index referenced by enabled non-empty field regions."""
    max_p0 = 0
    for r in regions:
        if not r.enabled or r.role != "field" or not r.text.strip():
            continue
        for tok in (r.page_scope or "1").lower().split(","):
            t = tok.strip()
            if t.isdigit():
                max_p0 = max(max_p0, int(t) - 1)
            elif t.endswith("+") and t[:-1].isdigit():
                max_p0 = max(max_p0, int(t[:-1]) - 1)
            elif "-" in t:
                a, b = t.split("-", 1)
                if a.strip().isdigit() and b.strip().isdigit():
                    max_p0 = max(max_p0, int(b.strip()) - 1)
    return max(0, max_p0)


def resolve_page_rule(page_index: int, config: LayoutConfig) -> PageRuleOverride:
    """Resolve effective per-page rule override for 0-based `page_index`."""
    pr = config.page_rules
    if pr.strategy == "first_and_rest":
        rule = pr.first_page if page_index == 0 else pr.rest_pages
        if not rule.label:
            return rule.model_copy(update={"label": "首页方案 A" if page_index == 0 else "后续页方案 B"})
        return rule
    if pr.strategy == "odd_even":
        rule = pr.odd_pages if (page_index % 2 == 0) else pr.even_pages
        if not rule.label:
            return rule.model_copy(update={"label": "奇数页方案 A" if page_index % 2 == 0 else "偶数页方案 B"})
        return rule
    if pr.strategy == "custom":
        p1 = page_index + 1
        if str(p1) in pr.custom_pages:
            r = pr.custom_pages[str(p1)]
            return r if r.label else r.model_copy(update={"label": f"第 {p1} 页自定义"})
        for key, r in pr.custom_pages.items():
            k = key.strip()
            if k.endswith("+") and k[:-1].isdigit():
                if p1 >= int(k[:-1]):
                    return r if r.label else r.model_copy(update={"label": f"第 {k} 页方案"})
            elif "-" in k:
                parts = k.split("-", 1)
                if parts[0].strip().isdigit() and parts[1].strip().isdigit():
                    lo, hi = int(parts[0].strip()), int(parts[1].strip())
                    if lo <= p1 <= hi:
                        return r if r.label else r.model_copy(update={"label": f"第 {lo}-{hi} 页方案"})
        if "default" in pr.custom_pages:
            r = pr.custom_pages["default"]
            return r if r.label else r.model_copy(update={"label": "默认方案"})
        return pr.rest_pages
    return pr.uniform


def diff_counts(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    out: dict[str, int] = {}
    for k, v in after.items():
        delta = v - before.get(k, 0)
        if delta > 0:
            out[k] = delta
    return out


def merge_counts(dst: dict[str, int], delta: dict[str, int]) -> None:
    for ch, cnt in delta.items():
        dst[ch] = dst.get(ch, 0) + cnt


def make_selector_pool(
    default_reader: HwFontReader | None,
    config: LayoutConfig,
    writer_resolver: WriterResolver | None,
) -> SelectorGetter:
    default_wid = default_reader.meta.writer_id if default_reader is not None else None
    cache: dict[str | None, SelectorEntry] = {}

    def _make(r: HwFontReader | None) -> VariantSelector:
        return VariantSelector(
            r,
            strategy=config.perturb.variant_strategy,
            no_repeat_window=config.perturb.variant_no_repeat_window,
            fallback_policy=config.fallback.policy,
        )

    def _metrics(r: HwFontReader | None) -> tuple[float, float]:
        upm = float(r.meta.units_per_em) if r is not None else 1000.0
        bl = float(r.meta.baseline_y) if r is not None else 800.0
        return upm, bl

    def _mixed() -> SelectorEntry | None:
        members = []
        for entry in config.writer_mix:
            if entry.weight <= 0:
                continue
            r = default_reader if entry.writer_id == default_wid else (
                writer_resolver(entry.writer_id) if writer_resolver is not None else None
            )
            if r is None:
                continue
            upm, bl = _metrics(r)
            members.append((_make(r), float(entry.weight), upm, bl))
        if len(members) < 2:
            return None
        mixed = MixedVariantSelector(members)
        upm, bl = members[0][2], members[0][3]
        return (mixed, upm, bl, members[0][0].reader.meta.writer_id)  # type: ignore[return-value]

    def _get(override_wid: str | None) -> SelectorEntry:
        if override_wid is None and config.writer_mix:
            if "__mix__" not in cache:
                mixed = _mixed()
                if mixed is not None:
                    cache["__mix__"] = mixed
            if "__mix__" in cache:
                return cache["__mix__"]
        target_wid = override_wid or default_wid
        if target_wid in cache:
            return cache[target_wid]
        r = default_reader
        if override_wid and override_wid != default_wid and writer_resolver is not None:
            resolved = writer_resolver(override_wid)
            if resolved is not None:
                r = resolved
        sel = _make(r)
        upm, bl = _metrics(r)
        actual_wid = r.meta.writer_id if r is not None else target_wid
        entry = (sel, upm, bl, actual_wid)
        cache[target_wid] = entry
        return entry

    return _get


_TYPE_LABELS_ZH: dict[str, str] = {
    "heading": "标题",
    "paragraph": "段落",
    "list_item": "列表",
    "caption": "图注",
    "table": "表格",
    "formula_block": "公式",
    "figure": "插图",
    "chart": "图表",
}


def build_block_box_label(blk) -> str:
    """Return a concise human-readable label (`类型 · 内容摘要`) for canvas PlacedBlockBox overlays."""
    prefix = _TYPE_LABELS_ZH.get(getattr(blk, "type", ""), str(getattr(blk, "type", "区块")))
    txt = ""
    if hasattr(blk, "plain_text"):
        txt = " ".join(str(blk.plain_text() or "").split())
    if not txt:
        txt = str(getattr(blk, "asset_name", None) or getattr(blk, "block_id", "") or "")
    snippet = txt[:18] + ("…" if len(txt) > 18 else "") if txt else str(getattr(blk, "block_id", ""))
    return f"{prefix} · {snippet}"


def append_math_missing_boxes(
    missing_out: list[MissingGlyphBox],
    ml: MathLayout,
    *,
    x_mm: float,
    baseline_y_mm: float,
    scale: float,
    page_index: int,
    block_id: str,
    latex: str,
    policy: str,
) -> None:
    """Record exact physical MissingGlyphBox coordinates for a placed MathLayout."""
    for ch, bb in translate_math_missing(ml, x_mm, baseline_y_mm, scale=scale):
        if not ch or ch.isspace():
            continue
        missing_out.append(
            MissingGlyphBox(
                id="",
                char=ch[0],
                unicode_hex=f"U+{ord(ch[0]):04X}",
                page_index=page_index,
                block_id=block_id,
                bbox_mm=bb,
                context=f"${latex[:36]}$",
                source="formula",
                policy=policy,  # type: ignore[arg-type]
            )
        )


def count_missing_chars(items: list[MissingGlyphBox]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for mg in items:
        counts[mg.char] = counts.get(mg.char, 0) + 1
    return counts


def compute_effective_line_pitch_mm(
    font_mm: float,
    line_spacing: float,
    line_spacing_mm: float | None,
    char_sy: float,
    ruled_pitch_mm: float = 0.0,
) -> float:
    """Compute effective line-to-line vertical pitch supporting arbitrary decimals and negatives.

    Positive values act directly as multiplier (`>0`) or fixed mm (`>0`).
    Non-positive values act as tightening offsets (`font*char_sy + offset_mm` or `font*(1+ratio)*char_sy`).
    Clamped at `0.8 mm` to prevent backwards motion or infinite page-break loops.
    """
    eff_sy = max(0.3, float(char_sy))
    if line_spacing_mm is not None:
        val = float(line_spacing_mm)
        raw = val if val > 0.0 else (float(font_mm) * eff_sy + val)
    else:
        ratio = float(line_spacing)
        raw = (float(font_mm) * ratio * eff_sy) if ratio > 0.0 else (float(font_mm) * (1.0 + ratio) * eff_sy)
    eff = max(0.8, raw)
    if ruled_pitch_mm > 0.0:
        eff = max(eff, float(ruled_pitch_mm))
    return eff
