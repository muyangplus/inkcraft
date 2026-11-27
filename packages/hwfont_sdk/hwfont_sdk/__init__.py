"""Shared .hwfont v1 SQLite single-line handwriting font SDK."""

from hwfont_sdk.codec import (
    HWS1_MAGIC,
    FLAG_HAS_PRESSURE,
    FLAG_HAS_TIME,
    DecodedStrokes,
    decode_strokes,
    decode_strokes_full,
    encode_strokes,
)
from hwfont_sdk.reader import GlyphVariant, HwFontReader, Stroke
from hwfont_sdk.schema import (
    APPLICATION_ID,
    DDL_V1,
    FORMAT_VERSION,
    USER_VERSION,
    CoverageSummary,
    HwFontMeta,
    classify_char,
)
from hwfont_sdk.verify import VerifyReport, compute_content_sha256, verify_database
from hwfont_sdk.writer import HwFontWriter

__all__ = [
    "APPLICATION_ID",
    "USER_VERSION",
    "FORMAT_VERSION",
    "DDL_V1",
    "HWS1_MAGIC",
    "FLAG_HAS_PRESSURE",
    "FLAG_HAS_TIME",
    "DecodedStrokes",
    "CoverageSummary",
    "HwFontMeta",
    "Stroke",
    "GlyphVariant",
    "HwFontReader",
    "HwFontWriter",
    "VerifyReport",
    "encode_strokes",
    "decode_strokes",
    "decode_strokes_full",
    "classify_char",
    "compute_content_sha256",
    "verify_database",
]
