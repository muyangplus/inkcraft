"""Writer font registry (hot-swap) and variant selector with fallback chain."""

from inkcraft.writers.registry import WriterRegistry
from inkcraft.writers.selector import ResolvedGlyph, VariantSelector

__all__ = ["WriterRegistry", "VariantSelector", "ResolvedGlyph"]
