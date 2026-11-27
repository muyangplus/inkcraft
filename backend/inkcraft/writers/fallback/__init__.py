"""Built-in single-line fallback vector font (ASCII, Greek, Math, Punctuation, CJK)."""

from inkcraft.writers.fallback.hershey import (
    BUILTIN_GLYPHS,
    get_fallback_glyph,
    make_missing_box_glyph,
)

__all__ = ["BUILTIN_GLYPHS", "get_fallback_glyph", "make_missing_box_glyph"]
