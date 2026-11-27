"""Dual-mode single-line document composer facade: Smart Reflow and Exact Overlay."""

from __future__ import annotations

from handwrite.api.schemas import ComposedPage, LayoutConfig
from handwrite.docparse.docir import DocIR
from handwrite.layout.compose.finalize import (
    apply_global_overlay_transform as _apply_global_overlay_transform,
    finalize_page as _finalize_page,
)
from handwrite.layout.compose.overlay import compose_overlay as _compose_overlay
from handwrite.layout.compose.reflow import compose_reflow as _compose_reflow
from handwrite.layout.compose.regions import compose_field_region as _compose_field_region
from handwrite.layout.compose.rules import (
    ComposeProgressCB,
    WriterResolver,
    diff_counts as _diff_counts,
    make_selector_pool as _make_selector_pool,
    matches_page_scope,
    max_explicit_region_page as _max_explicit_region_page,
    resolve_page_rule,
    resolve_page_size as _resolve_page_size,
)
from hwfont_sdk.reader import HwFontReader


def compose_document(
    doc: DocIR,
    reader: HwFontReader | None,
    config: LayoutConfig,
    progress_cb: ComposeProgressCB | None = None,
    writer_resolver: WriterResolver | None = None,
) -> list[ComposedPage]:
    """Deterministic pure-function composition pipeline: `DocIR + HwFontReader + LayoutConfig -> pages`."""
    if progress_cb is not None:
        progress_cb("compose", 0.02, f"开始排版 ({config.mode} 模式)")

    get_selector = _make_selector_pool(reader, config, writer_resolver)

    if config.mode == "overlay":
        pages = _compose_overlay(doc, get_selector, config, progress_cb)
    else:
        pages = _compose_reflow(doc, get_selector, config, progress_cb)

    if progress_cb is not None:
        progress_cb("done", 1.0, f"排版完成，共 {len(pages)} 页")

    return pages


__all__ = [
    "ComposeProgressCB",
    "WriterResolver",
    "compose_document",
    "matches_page_scope",
    "resolve_page_rule",
    "_apply_global_overlay_transform",
    "_compose_field_region",
    "_compose_overlay",
    "_compose_reflow",
    "_diff_counts",
    "_finalize_page",
    "_make_selector_pool",
    "_max_explicit_region_page",
    "_resolve_page_size",
]
