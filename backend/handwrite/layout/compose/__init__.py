"""Single-line dual-mode document composer subpackage."""

from handwrite.layout.compose.finalize import apply_global_overlay_transform, finalize_page
from handwrite.layout.compose.overlay import compose_overlay
from handwrite.layout.compose.reflow import compose_reflow
from handwrite.layout.compose.regions import compose_field_region
from handwrite.layout.compose.rules import (
    ComposeProgressCB,
    WriterResolver,
    diff_counts,
    make_selector_pool,
    matches_page_scope,
    max_explicit_region_page,
    resolve_page_rule,
    resolve_page_size,
)

__all__ = [
    "ComposeProgressCB",
    "WriterResolver",
    "apply_global_overlay_transform",
    "compose_field_region",
    "compose_overlay",
    "compose_reflow",
    "diff_counts",
    "finalize_page",
    "make_selector_pool",
    "matches_page_scope",
    "max_explicit_region_page",
    "resolve_page_rule",
    "resolve_page_size",
]
