"""Writer font registry (hot-swap) and variant selector with fallback chain."""

from handwrite.writers.registry import WriterRegistry
from handwrite.writers.selector import ResolvedGlyph, VariantSelector

__all__ = ["WriterRegistry", "VariantSelector", "ResolvedGlyph"]
