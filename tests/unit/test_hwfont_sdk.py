"""Unit tests for hwfont_sdk: HWS1 binary codec, SQLite .hwfont reader/writer, and verification."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import numpy as np
import pytest

from hwfont_sdk import (
    APPLICATION_ID,
    HwFontMeta,
    HwFontReader,
    HwFontWriter,
    USER_VERSION,
    decode_strokes,
    decode_strokes_full,
    encode_strokes,
)


def test_hws1_roundtrip_and_channels() -> None:
    s1 = np.array([[100, 200], [500, 210], [880, 195]], dtype=np.int16)
    s2 = np.array([[495, 120], [500, 500], [490, 860]], dtype=np.int16)
    p1 = [120, 200, 140]
    p2 = [100, 255, 80]
    dt1 = [0, 18, 22]
    dt2 = [0, 25, 31]

    blob = encode_strokes([s1, s2], pressure=[p1, p2], dt=[dt1, dt2])
    decoded = decode_strokes_full(blob)
    assert len(decoded.strokes) == 2
    assert np.array_equal(decoded.strokes[0], s1)
    assert np.array_equal(decoded.strokes[1], s2)
    assert decoded.pressure is not None
    assert list(decoded.pressure[0]) == p1
    assert list(decoded.pressure[1]) == p2
    assert decoded.dt_ms is not None
    assert list(decoded.dt_ms[0]) == dt1
    assert list(decoded.dt_ms[1]) == dt2

    plain = decode_strokes(encode_strokes([s1]))
    assert len(plain) == 1 and np.array_equal(plain[0], s1)


def test_hwfont_writer_reader_and_tamper_detection(tmp_path: Path) -> None:
    out = tmp_path / "sample.hwfont"
    meta = HwFontMeta(writer_name="测试书写者", writer_alias="行楷", style_tags=["测试"])
    writer = HwFontWriter(out, meta)
    writer.add_variant("永", [np.array([[200, 200], [800, 200]]), np.array([[500, 150], [500, 850]])], source="scan")
    writer.add_variant("永", [np.array([[210, 210], [790, 195]]), np.array([[505, 160], [495, 840]])], source="generated")
    writer.add_variant("A", [np.array([[100, 800], [320, 130], [540, 800]])], source="scan", advance=620)
    writer.set_kerning("A", "V", -45)
    final_path = writer.finalize()

    with HwFontReader(final_path) as reader:
        report = reader.verify()
        assert report.ok, report.errors
        assert report.glyph_count == 2
        assert report.variant_count == 3
        assert reader.meta.units_per_em == 1000
        assert reader.meta.baseline_y == 800
        assert reader.has("永")
        assert len(reader.variants("永")) == 2
        assert reader.kerning("A", "V") == -45

    # Verify SQLite header pragmas
    conn = sqlite3.connect(str(final_path))
    assert conn.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
    assert conn.execute("PRAGMA user_version").fetchone()[0] == USER_VERSION
    # Tamper with variant stroke advance to confirm content_sha256 catches corruption
    conn.execute("UPDATE variants SET advance = 999 WHERE variant_no = 0")
    conn.commit()
    conn.close()

    with HwFontReader(final_path) as reader:
        tampered = reader.verify()
        assert not tampered.ok
        assert any("content_sha256" in err for err in tampered.errors)
