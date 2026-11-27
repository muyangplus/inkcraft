"""Integrity verification and content_sha256 computation for .hwfont files."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import sqlite3
import struct

from hwfont_sdk.codec import decode_strokes
from hwfont_sdk.schema import APPLICATION_ID, USER_VERSION


@dataclass
class VerifyReport:
    ok: bool
    glyph_count: int = 0
    variant_count: int = 0
    expected_sha256: str = ""
    actual_sha256: str = ""
    errors: list[str] = field(default_factory=list)


def compute_content_sha256(conn: sqlite3.Connection) -> str:
    """Compute canonical SHA-256 across all glyphs & variants ordered by (codepoint, variant_no)."""
    hasher = hashlib.sha256()
    cur = conn.execute(
        """
        SELECT g.codepoint, g.char, g.advance, v.variant_no, v.source,
               v.advance, v.strokes
        FROM glyphs g
        JOIN variants v ON v.glyph_id = g.glyph_id
        ORDER BY g.codepoint ASC, v.variant_no ASC
        """
    )
    for codepoint, ch, g_adv, v_no, source, v_adv, blob in cur:
        adv = v_adv if v_adv is not None else g_adv
        hasher.update(struct.pack("<III", int(codepoint), int(v_no), int(adv)))
        hasher.update(ch.encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(source.encode("ascii"))
        hasher.update(struct.pack("<I", len(blob)))
        hasher.update(blob)
    return hasher.hexdigest()


def verify_database(conn: sqlite3.Connection) -> VerifyReport:
    """Verify SQLite header pragmas, HWS1 blobs, bounding boxes, and content_sha256."""
    errors: list[str] = []

    app_id = conn.execute("PRAGMA application_id").fetchone()[0]
    if app_id != APPLICATION_ID:
        errors.append(f"Invalid application_id: expected {APPLICATION_ID:#x}, got {app_id:#x}")

    user_ver = conn.execute("PRAGMA user_version").fetchone()[0]
    if user_ver != USER_VERSION:
        errors.append(f"Unsupported user_version: expected {USER_VERSION}, got {user_ver}")

    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        errors.append(f"SQLite integrity_check failed: {integrity}")

    glyph_count = conn.execute("SELECT COUNT(*) FROM glyphs").fetchone()[0]
    variant_count = conn.execute("SELECT COUNT(*) FROM variants").fetchone()[0]

    # Validate each variant blob & bbox consistency
    cur = conn.execute(
        """
        SELECT variant_id, stroke_count, point_count,
               bbox_x0, bbox_y0, bbox_x1, bbox_y1, strokes
        FROM variants
        """
    )
    for vid, sc, pc, x0, y0, x1, y1, blob in cur:
        try:
            strokes = decode_strokes(blob)
        except Exception as exc:
            errors.append(f"variant_id={vid}: HWS1 decode error: {exc}")
            continue
        if len(strokes) != sc:
            errors.append(f"variant_id={vid}: stroke_count mismatch ({len(strokes)} != {sc})")
        total_pts = sum(int(s.shape[0]) for s in strokes)
        if total_pts != pc:
            errors.append(f"variant_id={vid}: point_count mismatch ({total_pts} != {pc})")
        if not strokes:
            errors.append(f"variant_id={vid}: empty strokes")
            continue
        all_x = [int(s[:, 0].min()) for s in strokes]
        all_y = [int(s[:, 1].min()) for s in strokes]
        max_x = [int(s[:, 0].max()) for s in strokes]
        max_y = [int(s[:, 1].max()) for s in strokes]
        if (min(all_x), min(all_y), max(max_x), max(max_y)) != (x0, y0, x1, y1):
            errors.append(f"variant_id={vid}: bbox mismatch")

    row = conn.execute("SELECT value FROM meta WHERE key = 'content_sha256'").fetchone()
    expected_sha = str(json.loads(row[0])) if row and row[0] else ""
    actual_sha = compute_content_sha256(conn)
    if not expected_sha:
        errors.append("missing content_sha256 in metadata")
    elif expected_sha != actual_sha:
        errors.append(f"content_sha256 mismatch: expected {expected_sha}, got {actual_sha}")

    return VerifyReport(
        ok=len(errors) == 0,
        glyph_count=glyph_count,
        variant_count=variant_count,
        expected_sha256=expected_sha,
        actual_sha256=actual_sha,
        errors=errors,
    )
