"""Deterministic multi-variant glyph selector with no-repeat window & fallback chain."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Literal

import numpy as np

from inkcraft.writers.fallback.hershey import get_fallback_glyph, make_missing_box_glyph
from hwfont_sdk.reader import GlyphVariant, HwFontReader


@dataclass(frozen=True, slots=True)
class ResolvedGlyph:
    char: str
    advance_u: int
    strokes: list[np.ndarray]  # list of (N, 2) float64 arrays in 0..1000 coords
    variant_id: int | None
    is_fallback: bool


class VariantSelector:
    """Selects glyph variants according to PerturbConfig strategy & fallback policy."""

    def __init__(
        self,
        reader: HwFontReader | None,
        *,
        strategy: Literal["random_no_repeat", "round_robin", "lru"] = "random_no_repeat",
        no_repeat_window: int = 3,
        fallback_policy: Literal["blank", "builtin_single_line", "skip", "box"] = "blank",
    ) -> None:
        self.reader = reader
        self.strategy = strategy
        self.no_repeat_window = max(1, int(no_repeat_window))
        self.fallback_policy = fallback_policy
        self._recent: dict[str, deque[int]] = {}
        self._rr_counter: dict[str, int] = {}
        self.fallback_counts: dict[str, int] = {}

    def select(self, ch: str, rng: np.random.Generator) -> ResolvedGlyph | None:
        """Resolve a character into single-line strokes in 0..1000 space."""
        if not ch:
            return None
        c = ch[0]
        if c == " ":
            return ResolvedGlyph(char=c, advance_u=360, strokes=[], variant_id=None, is_fallback=False)
        if c == "\u3000":
            return ResolvedGlyph(char=c, advance_u=1000, strokes=[], variant_id=None, is_fallback=False)

        variants: list[GlyphVariant] = self.reader.variants(c) if self.reader is not None else []
        if variants:
            chosen = self._pick_variant(c, variants, rng)
            return ResolvedGlyph(
                char=c,
                advance_u=chosen.advance,
                strokes=[s.pts.astype(np.float64) for s in chosen.strokes],
                variant_id=chosen.variant_id,
                is_fallback=False,
            )

        # Fallback chain
        self.fallback_counts[c] = self.fallback_counts.get(c, 0) + 1
        if self.fallback_policy == "blank":
            cp = ord(c)
            is_wide = (
                0x2E80 <= cp <= 0x9FFF
                or 0x3000 <= cp <= 0x303F
                or 0xF900 <= cp <= 0xFAFF
                or 0xFE30 <= cp <= 0xFE6F
                or 0xFF00 <= cp <= 0xFF60
            )
            default_adv = (
                int(self.reader.meta.default_advance)
                if (self.reader is not None and getattr(self.reader.meta, "default_advance", 0) > 0)
                else 1000
            )
            adv = default_adv if is_wide else 520
            return ResolvedGlyph(char=c, advance_u=adv, strokes=[], variant_id=None, is_fallback=True)
        if self.fallback_policy == "skip":
            return ResolvedGlyph(char=c, advance_u=0, strokes=[], variant_id=None, is_fallback=True)
        if self.fallback_policy == "box":
            adv, strokes = make_missing_box_glyph(c)
            return ResolvedGlyph(
                char=c,
                advance_u=adv,
                strokes=[s.astype(np.float64) for s in strokes],
                variant_id=None,
                is_fallback=True,
            )
        adv, strokes, _ = get_fallback_glyph(c)
        return ResolvedGlyph(
            char=c,
            advance_u=adv,
            strokes=[s.astype(np.float64) for s in strokes],
            variant_id=None,
            is_fallback=True,
        )

    def clone(self) -> "VariantSelector":
        """Fresh selector with identical settings (used for dry-run measuring)."""
        return VariantSelector(
            self.reader,
            strategy=self.strategy,
            no_repeat_window=self.no_repeat_window,
            fallback_policy=self.fallback_policy,
        )

    def kerning(self, left: str, right: str) -> int:
        if self.reader is None:
            return 0
        return self.reader.kerning(left, right)

    def _pick_variant(
        self, ch: str, variants: list[GlyphVariant], rng: np.random.Generator
    ) -> GlyphVariant:
        if len(variants) == 1:
            return variants[0]

        if self.strategy == "round_robin":
            idx = self._rr_counter.get(ch, 0) % len(variants)
            self._rr_counter[ch] = idx + 1
            return variants[idx]

        hist = self._recent.setdefault(ch, deque(maxlen=self.no_repeat_window))
        if self.strategy == "lru":
            # Prefer least recently used variant
            for v in variants:
                if v.variant_id not in hist:
                    hist.append(v.variant_id)
                    return v
            # All variants in history; pick the oldest one
            oldest_vid = hist[0]
            for v in variants:
                if v.variant_id == oldest_vid:
                    hist.append(v.variant_id)
                    return v
            chosen = variants[0]
            hist.append(chosen.variant_id)
            return chosen

        # Default: random_no_repeat with weighted sampling
        candidates = [v for v in variants if v.variant_id not in hist]
        if not candidates:
            # Exclude only the immediately previous variant if possible
            last_vid = hist[-1] if hist else -1
            candidates = [v for v in variants if v.variant_id != last_vid] or variants
        weights = np.array([max(1e-3, v.weight * v.quality) for v in candidates], dtype=np.float64)
        weights /= weights.sum()
        idx = int(rng.choice(len(candidates), p=weights))
        chosen = candidates[idx]
        hist.append(chosen.variant_id)
        return chosen


class MixedVariantSelector:
    """Picks a writer per character by weight (奎享雕刻 "多字体按概率混写").

    Exposes the same surface as :class:`VariantSelector`.  Glyphs from secondary
    writers are re-normalised into the primary writer's units-per-em/baseline so
    that the mixed line keeps a common baseline.  When the drawn writer lacks a
    glyph the remaining writers are tried (heaviest first) before the fallback
    policy of the primary selector applies.
    """

    def __init__(
        self,
        members: list[tuple[VariantSelector, float, float, float]],
    ) -> None:
        # members: (selector, weight, units_per_em, baseline_u); first = primary
        if not members:
            raise ValueError("MixedVariantSelector needs at least one writer")
        self.members = members
        primary = members[0][0]
        self.reader = primary.reader
        self.strategy = primary.strategy
        self.no_repeat_window = primary.no_repeat_window
        self.fallback_policy = primary.fallback_policy
        self._upm = members[0][2]
        self._base = members[0][3]
        w = np.array([max(0.0, m[1]) for m in members], dtype=np.float64)
        self._weights = w / w.sum() if w.sum() > 0 else np.full(len(members), 1.0 / len(members))

    @property
    def fallback_counts(self) -> dict[str, int]:
        return self.members[0][0].fallback_counts

    def clone(self) -> "MixedVariantSelector":
        return MixedVariantSelector(
            [
                (
                    VariantSelector(
                        sel.reader,
                        strategy=sel.strategy,
                        no_repeat_window=sel.no_repeat_window,
                        fallback_policy=sel.fallback_policy,
                    ),
                    wt,
                    upm,
                    base,
                )
                for sel, wt, upm, base in self.members
            ]
        )

    def _normalise(self, g: ResolvedGlyph, upm: float, base: float) -> ResolvedGlyph:
        if abs(upm - self._upm) < 1e-6 and abs(base - self._base) < 1e-6:
            return g
        k = self._upm / upm if upm > 0 else 1.0
        dy = self._base - base * k
        strokes = [np.column_stack((s[:, 0] * k, s[:, 1] * k + dy)) for s in g.strokes]
        return ResolvedGlyph(
            char=g.char,
            advance_u=int(round(g.advance_u * k)),
            strokes=strokes,
            variant_id=g.variant_id,
            is_fallback=g.is_fallback,
        )

    def select(self, ch: str, rng: np.random.Generator) -> ResolvedGlyph | None:
        if not ch:
            return None
        if ch[0] in (" ", "　"):
            return self.members[0][0].select(ch, rng)
        first = int(rng.choice(len(self.members), p=self._weights))
        order = [first] + sorted(
            (i for i in range(len(self.members)) if i != first),
            key=lambda i: -self._weights[i],
        )
        for i in order:
            sel, _, upm, base = self.members[i]
            if sel.reader is not None and sel.reader.variants(ch[0]):
                g = sel.select(ch, rng)
                return None if g is None else self._normalise(g, upm, base)
        return self.members[0][0].select(ch, rng)

    def kerning(self, left: str, right: str) -> int:
        return self.members[0][0].kerning(left, right)
