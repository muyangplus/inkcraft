"""Builder-side single-file .hwfont v1 SQLite writer with validation & VACUUM."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Sequence

import numpy as np

from hwfont_sdk.codec import encode_strokes
from hwfont_sdk.schema import (
    CoverageSummary,
    DDL_V1,
    HwFontMeta,
    VariantSource,
    classify_char,
)
from hwfont_sdk.verify import compute_content_sha256


class HwFontWriter:
    """Create, populate, verify, and finalize a single-file .hwfont database."""

    def __init__(self, path: str | Path, meta: HwFontMeta, *, overwrite: bool = True) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if overwrite and self.path.exists():
            self.path.unlink()
        self.meta = meta.model_copy(deep=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.executescript(DDL_V1)
        self._glyph_ids: dict[int, int] = {}
        self._variant_counts: dict[int, int] = {}
        self._finalized = False

    def _ensure_glyph(self, ch: str, advance: int) -> int:
        cp = ord(ch[0])
        if cp in self._glyph_ids:
            return self._glyph_ids[cp]
        category = classify_char(ch)
        cur = self._conn.execute(
            "INSERT INTO glyphs (codepoint, char, category, advance) VALUES (?, ?, ?, ?)",
            (cp, ch[0], category, int(advance)),
        )
        gid = int(cur.lastrowid)
        self._glyph_ids[cp] = gid
        self._variant_counts[cp] = 0
        return gid

    def add_variant(
        self,
        ch: str,
        strokes: Sequence[np.ndarray | Sequence[tuple[int, int]]],
        *,
        source: VariantSource = "generated",
        quality: float = 1.0,
        weight: float = 1.0,
        advance: int | None = None,
        scan_png: bytes | None = None,
        thumb_png: bytes | None = None,
    ) -> int:
        """Add one stroke-sequence variant for a character in 0..1000 coordinates."""
        if not ch:
            raise ValueError("Character must be non-empty")
        ch = ch[0]
        cp = ord(ch)

        norm_strokes: list[np.ndarray] = []
        min_x, min_y, max_x, max_y = 1000, 1000, 0, 0
        total_pts = 0
        for raw in strokes:
            raw_arr = np.asarray(raw, dtype=np.float64)
            if raw_arr.ndim != 2 or raw_arr.shape[1] != 2 or raw_arr.shape[0] < 2:
                raise ValueError("Each stroke must have shape (N>=2, 2)")
            if not np.all(np.isfinite(raw_arr)):
                raise ValueError("Stroke contains non-finite (NaN/inf) coordinates")
            arr = np.rint(raw_arr).astype(np.int32)
            arr = np.clip(arr, 0, 1000)
            min_x = min(min_x, int(arr[:, 0].min()))
            min_y = min(min_y, int(arr[:, 1].min()))
            max_x = max(max_x, int(arr[:, 0].max()))
            max_y = max(max_y, int(arr[:, 1].max()))
            total_pts += int(arr.shape[0])
            norm_strokes.append(arr)

        if advance is None:
            cat = classify_char(ch)
            if cat == "cjk":
                calc_adv = self.meta.default_advance
            else:
                calc_adv = max(280, min(1000, max_x + 120))
        else:
            calc_adv = int(advance)

        # Encode and validate before mutating SQLite rows
        blob = encode_strokes(norm_strokes)

        gid = self._ensure_glyph(ch, calc_adv)
        v_no = self._variant_counts[cp]
        self._variant_counts[cp] = v_no + 1
        cur = self._conn.execute(
            """
            INSERT INTO variants (
                glyph_id, variant_no, source, quality, weight,
                stroke_count, point_count,
                bbox_x0, bbox_y0, bbox_x1, bbox_y1,
                advance, strokes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                gid,
                v_no,
                source,
                float(quality),
                float(weight),
                len(norm_strokes),
                total_pts,
                min_x,
                min_y,
                max_x,
                max_y,
                calc_adv,
                blob,
            ),
        )
        vid = int(cur.lastrowid)

        if v_no == 0:
            self._conn.execute(
                "UPDATE glyphs SET default_variant = ? WHERE glyph_id = ?",
                (vid, gid),
            )
        if scan_png is not None:
            self._conn.execute(
                "INSERT INTO variant_assets (variant_id, kind, data) VALUES (?, 'scan_png', ?)",
                (vid, scan_png),
            )
        if thumb_png is not None:
            self._conn.execute(
                "INSERT INTO variant_assets (variant_id, kind, data) VALUES (?, 'thumb_png', ?)",
                (vid, thumb_png),
            )
        return vid

    def set_kerning(self, left: str, right: str, adjust: int) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO kerning (left_cp, right_cp, adjust) VALUES (?, ?, ?)",
            (ord(left[0]), ord(right[0]), int(adjust)),
        )

    def finalize(self) -> Path:
        """Compute coverage statistics, content_sha256, VACUUM, and close cleanly."""
        if self._finalized:
            return self.path

        glyph_count = int(self._conn.execute("SELECT COUNT(*) FROM glyphs").fetchone()[0])
        variant_count = int(self._conn.execute("SELECT COUNT(*) FROM variants").fetchone()[0])

        cov = {"cjk": 0, "latin": 0, "digit": 0, "punct": 0, "symbol": 0}
        for cat, cnt in self._conn.execute("SELECT category, COUNT(*) FROM glyphs GROUP BY category"):
            if cat in cov:
                cov[cat] += int(cnt)
            elif cat == "greek":
                cov["symbol"] += int(cnt)

        self.meta.glyph_count = glyph_count
        self.meta.variant_count = variant_count
        self.meta.coverage = CoverageSummary(**cov)
        self.meta.content_sha256 = compute_content_sha256(self._conn)

        meta_dict = self.meta.model_dump()
        for key, value in meta_dict.items():
            self._conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (key, json.dumps(value, ensure_ascii=False)),
            )

        self._conn.commit()
        self._conn.execute("PRAGMA journal_mode = DELETE")
        self._conn.execute("VACUUM")
        self._conn.close()
        self._finalized = True
        return self.path
