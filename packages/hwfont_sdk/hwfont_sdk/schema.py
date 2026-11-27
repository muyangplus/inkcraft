"""SQLite DDL and Pydantic metadata schemas for .hwfont v1."""

from __future__ import annotations

import unicodedata
from datetime import datetime, timezone
from typing import Literal
import uuid

from pydantic import BaseModel, Field

APPLICATION_ID: int = 0x48574654  # ASCII 'HWFT' == 1213679188
USER_VERSION: int = 1
FORMAT_VERSION: str = "1.0"

GlyphCategory = Literal["cjk", "latin", "digit", "punct", "symbol", "greek", "other"]
VariantSource = Literal["scan", "generated", "augmented", "manual", "builtin"]

DDL_V1: str = f"""
PRAGMA application_id = {APPLICATION_ID};
PRAGMA user_version   = {USER_VERSION};
PRAGMA journal_mode   = DELETE;
PRAGMA foreign_keys   = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL CHECK (json_valid(value))
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS glyphs (
    glyph_id        INTEGER PRIMARY KEY,
    codepoint       INTEGER NOT NULL UNIQUE CHECK (codepoint BETWEEN 0 AND 1114111),
    char            TEXT    NOT NULL,
    category        TEXT    NOT NULL CHECK (category IN
                        ('cjk','latin','digit','punct','symbol','greek','other')),
    advance         INTEGER NOT NULL DEFAULT 1000 CHECK (advance BETWEEN 0 AND 2000),
    default_variant INTEGER,
    note            TEXT
);

CREATE TABLE IF NOT EXISTS variants (
    variant_id   INTEGER PRIMARY KEY,
    glyph_id     INTEGER NOT NULL REFERENCES glyphs(glyph_id) ON DELETE CASCADE,
    variant_no   INTEGER NOT NULL CHECK (variant_no >= 0),
    source       TEXT    NOT NULL CHECK (source IN
                     ('scan','generated','augmented','manual','builtin')),
    quality      REAL    NOT NULL DEFAULT 1.0 CHECK (quality BETWEEN 0 AND 1),
    weight       REAL    NOT NULL DEFAULT 1.0 CHECK (weight > 0),
    stroke_count INTEGER NOT NULL CHECK (stroke_count BETWEEN 1 AND 64),
    point_count  INTEGER NOT NULL CHECK (point_count >= 2),
    bbox_x0      INTEGER NOT NULL CHECK (bbox_x0 BETWEEN 0 AND 1000),
    bbox_y0      INTEGER NOT NULL CHECK (bbox_y0 BETWEEN 0 AND 1000),
    bbox_x1      INTEGER NOT NULL CHECK (bbox_x1 BETWEEN bbox_x0 AND 1000),
    bbox_y1      INTEGER NOT NULL CHECK (bbox_y1 BETWEEN bbox_y0 AND 1000),
    advance      INTEGER CHECK (advance BETWEEN 0 AND 2000),
    strokes      BLOB    NOT NULL,
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (glyph_id, variant_no)
);

CREATE INDEX IF NOT EXISTS idx_variants_glyph ON variants(glyph_id);

CREATE TABLE IF NOT EXISTS kerning (
    left_cp  INTEGER NOT NULL,
    right_cp INTEGER NOT NULL,
    adjust   INTEGER NOT NULL CHECK (adjust BETWEEN -500 AND 500),
    PRIMARY KEY (left_cp, right_cp)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS variant_assets (
    variant_id INTEGER NOT NULL REFERENCES variants(variant_id) ON DELETE CASCADE,
    kind       TEXT    NOT NULL CHECK (kind IN ('scan_png','thumb_png')),
    data       BLOB    NOT NULL,
    PRIMARY KEY (variant_id, kind)
) WITHOUT ROWID;

CREATE VIEW IF NOT EXISTS v_coverage AS
SELECT category,
       COUNT(*) AS glyph_count,
       SUM((SELECT COUNT(*) FROM variants v WHERE v.glyph_id = g.glyph_id)) AS variant_count
FROM glyphs g
GROUP BY category;
"""


class CoverageSummary(BaseModel):
    cjk: int = 0
    latin: int = 0
    digit: int = 0
    punct: int = 0
    symbol: int = 0


class HwFontMeta(BaseModel):
    format_version: str = FORMAT_VERSION
    writer_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    writer_name: str
    writer_alias: str = ""
    author: str = ""
    version: str = "1.0.0"
    style_tags: list[str] = Field(default_factory=list)
    units_per_em: int = 1000
    baseline_y: int = 800
    x_height: int = 440
    cap_height: int = 680
    default_advance: int = 1000
    glyph_count: int = 0
    variant_count: int = 0
    coverage: CoverageSummary = Field(default_factory=CoverageSummary)
    builder: str = "hwfont_sdk 1.0.0"
    model: str = ""
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    license: str = "Personal / Authorized Handwriting License"
    preview_text: str = "永和九年，岁在癸丑 E=mc²"
    preview_char: str = "永"
    content_sha256: str = ""


def classify_char(ch: str) -> GlyphCategory:
    """Classify a single Unicode character into .hwfont glyph categories."""
    if not ch:
        return "other"
    cp = ord(ch[0])
    if (
        0x4E00 <= cp <= 0x9FFF
        or 0x3400 <= cp <= 0x4DBF
        or 0x20000 <= cp <= 0x2A6DF
        or 0xF900 <= cp <= 0xFAFF
    ):
        return "cjk"
    if 0x0030 <= cp <= 0x0039:
        return "digit"
    if (0x0041 <= cp <= 0x005A) or (0x0061 <= cp <= 0x007A):
        return "latin"
    if 0x0370 <= cp <= 0x03FF:
        return "greek"
    cat = unicodedata.category(ch[0])
    if cat.startswith("P") or (0x3000 <= cp <= 0x303F) or (0xFF01 <= cp <= 0xFF0F):
        return "punct"
    if cat.startswith("S"):
        return "symbol"
    return "other"
