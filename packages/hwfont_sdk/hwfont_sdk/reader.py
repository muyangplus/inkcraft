"""Read-only, immutable, LRU-cached .hwfont v1 reader."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import sqlite3
import threading

import numpy as np

from hwfont_sdk.codec import decode_strokes
from hwfont_sdk.schema import APPLICATION_ID, USER_VERSION, CoverageSummary, HwFontMeta
from hwfont_sdk.verify import VerifyReport, verify_database


@dataclass(frozen=True, slots=True)
class Stroke:
    pts: np.ndarray  # shape=(N, 2), dtype=int16, range 0..1000


@dataclass(frozen=True, slots=True)
class GlyphVariant:
    variant_id: int
    char: str
    variant_no: int
    source: str
    quality: float
    weight: float
    advance: int
    bbox: tuple[int, int, int, int]
    strokes: tuple[Stroke, ...]


class HwFontReader:
    """High-performance read-only reader for single-file .hwfont SQLite databases."""

    def __init__(self, path: str | Path, *, cache_size: int = 4096) -> None:
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise FileNotFoundError(f".hwfont file not found: {self.path}")

        uri = f"{self.path.as_uri()}?mode=ro&immutable=1"
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(uri, uri=True, check_same_thread=False)

        try:
            app_id = self._conn.execute("PRAGMA application_id").fetchone()[0]
            if app_id != APPLICATION_ID:
                raise ValueError(
                    f"{self.path.name}: invalid .hwfont application_id ({app_id:#x} != {APPLICATION_ID:#x})"
                )

            user_ver = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if user_ver > USER_VERSION:
                raise ValueError(
                    f"{self.path.name}: .hwfont format v{user_ver} is newer than supported v{USER_VERSION}"
                )

            self.meta: HwFontMeta = self._load_meta()
            self._charset: frozenset[str] = self._load_charset()
            self._kerning: dict[tuple[int, int], int] = self._load_kerning()
        except Exception:
            self._conn.close()
            raise
        self._variants_cached = lru_cache(maxsize=cache_size)(self._query_variants)

    def _load_meta(self) -> HwFontMeta:
        raw: dict[str, object] = {}
        for k, v in self._conn.execute("SELECT key, value FROM meta"):
            raw[k] = json.loads(v)
        if "coverage" in raw and isinstance(raw["coverage"], dict):
            raw["coverage"] = CoverageSummary(**raw["coverage"])
        return HwFontMeta(**raw)

    def _load_charset(self) -> frozenset[str]:
        rows = self._conn.execute("SELECT char FROM glyphs").fetchall()
        return frozenset(r[0] for r in rows)

    def _load_kerning(self) -> dict[tuple[int, int], int]:
        rows = self._conn.execute("SELECT left_cp, right_cp, adjust FROM kerning").fetchall()
        return {(int(l), int(r)): int(adj) for l, r, adj in rows}

    def has(self, ch: str) -> bool:
        return ch in self._charset

    def charset(self) -> frozenset[str]:
        return self._charset

    def kerning(self, left: str, right: str) -> int:
        if not left or not right:
            return 0
        return self._kerning.get((ord(left[0]), ord(right[0])), 0)

    def _query_variants(self, ch: str) -> tuple[GlyphVariant, ...]:
        if not ch:
            return ()
        cp = ord(ch[0])
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT v.variant_id, g.char, v.variant_no, v.source,
                       v.quality, v.weight, COALESCE(v.advance, g.advance),
                       v.bbox_x0, v.bbox_y0, v.bbox_x1, v.bbox_y1, v.strokes
                FROM glyphs g
                JOIN variants v ON v.glyph_id = g.glyph_id
                WHERE g.codepoint = ?
                ORDER BY v.variant_no ASC
                """,
                (cp,),
            ).fetchall()
        result: list[GlyphVariant] = []
        for vid, c, vno, src, qual, weight, adv, x0, y0, x1, y1, blob in rows:
            decoded = decode_strokes(blob)
            result.append(
                GlyphVariant(
                    variant_id=int(vid),
                    char=str(c),
                    variant_no=int(vno),
                    source=str(src),
                    quality=float(qual),
                    weight=float(weight),
                    advance=int(adv),
                    bbox=(int(x0), int(y0), int(x1), int(y1)),
                    strokes=tuple(Stroke(pts=s) for s in decoded),
                )
            )
        return tuple(result)

    def variants(self, ch: str) -> list[GlyphVariant]:
        return list(self._variants_cached(ch))

    def verify(self) -> VerifyReport:
        with self._lock:
            return verify_database(self._conn)

    def close(self) -> None:
        with self._lock:
            self._variants_cached.cache_clear()
            self._conn.close()

    def __enter__(self) -> HwFontReader:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
