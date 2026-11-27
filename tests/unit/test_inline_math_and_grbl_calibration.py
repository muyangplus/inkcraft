"""Unit & integration tests for PDF/DOCX inline math subscripts, compact chemical layout, and GRBL calibration."""

from __future__ import annotations

from pathlib import Path
import time

from fastapi.testclient import TestClient
import pymupdf as fitz
import pytest

from handwrite.api.app import create_app
from handwrite.config import Settings
from handwrite.api.schemas import LayoutConfig
from handwrite.docparse.docir import BreakInline, DocBlock, DocIR, DocPageInfo, DocSource, MathInline, TextInline
from handwrite.docparse.formula_ocr import (
    _OcrBox,
    _extract_symbol_table,
    _repair_latex_subscripts_with_context,
)
from handwrite.docparse.inline_math import (
    build_text_with_scripts,
    is_symbol_def_block,
    normalize_symbol_def_leading_subscript,
    normalize_unambiguous_unit_powers,
)
from handwrite.docparse.pdf_parser import _extract_page_structure_pymupdf, parse_pdf
from handwrite.layout.composer import compose_document
from handwrite.layout.math_typesetter import typeset_math
from handwrite.writers.registry import WriterRegistry
from handwrite.writers.selector import VariantSelector

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_PDF = ROOT / "source" / "4-实验教学指导书.pdf"


def _make_test_settings(tmp_path: Path) -> Settings:
    fonts_dir = tmp_path / "fonts"
    fonts_dir.mkdir()
    for f in (ROOT / "fonts").glob("*.hwfont"):
        (fonts_dir / f.name).write_bytes(f.read_bytes())
    data_dir = tmp_path / "data"
    return Settings(
        root_dir=ROOT,
        fonts_dir=fonts_dir,
        data_dir=data_dir,
        db_path=data_dir / "app.db",
        profiles_path=ROOT / "config" / "default_profiles.json",
        frontend_dist_dir=ROOT / "frontend" / "dist",
    )


def _wait_task(client: TestClient, task_id: str, timeout_s: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = client.get(f"/api/v1/tasks/{task_id}")
        assert r.status_code == 200
        body = r.json()
        if body["state"] in ("done", "failed"):
            return body
        time.sleep(0.05)
    raise TimeoutError(f"Task {task_id} did not finish")


def test_inline_math_script_builder_and_symbol_repair() -> None:
    assert build_text_with_scripts([("FeCl", "normal"), ("3 ", "sub")]) == r"$\mathrm{FeCl}_3$ "
    assert (
        build_text_with_scripts(
            [
                ("Al", "normal"),
                ("2", "sub"),
                ("(SO", "normal"),
                ("4", "sub"),
                (")", "normal"),
                ("3", "sub"),
            ]
        )
        == r"$\mathrm{Al}_2(\mathrm{SO}_4)_3$"
    )
    assert (
        build_text_with_scripts([("记录量筒内滤液体积V", "normal"), ("0", "sub"), ("。", "normal")])
        == r"记录量筒内滤液体积$V_0$。"
    )
    assert (
        build_text_with_scripts(
            [("式中", "normal"), ("M", "normal"), ("j", "sub"), ("（湿）", "sub"), ("--", "normal")]
        )
        == r"式中$M_{j(\text{湿})}$--"
    )
    assert build_text_with_scripts([("10-", "normal"), ("3", "sup")]) == r"$10^{-3}$"

    units = normalize_unambiguous_unit_powers("水的密度g/cm3，容重kg/ m3，标准GB/T 12496.10-1999。")
    assert r"$\mathrm{g/cm}^3$" in units
    assert r"$\mathrm{kg/m}^3$" in units
    assert "GB/T 12496.10-1999" in units

    ctx = "式中$M_{j(\\text{湿})}$--每次湿重；$M_{j(\\text{干})}$--每次干重；$C_{\\text{卡}}$--热容。"
    sym_table = _extract_symbol_table(ctx)
    assert "M" in sym_table and len(sym_table["M"]) >= 2
    repaired = _repair_latex_subscripts_with_context(
        r"M_{j\star} - M_{j\mp}",
        [_OcrBox(0, 0, 20, 15, "Mj(湿)"), _OcrBox(30, 0, 50, 15, "Mj(干)")],
        sym_table,
    )
    assert r"M_{j(\text{湿})}" in repaired
    assert r"M_{j(\text{干})}" in repaired
    # Even if first repair emitted duplicate wet-wet subtraction, counterpart resolver separates them
    repaired_dup = _repair_latex_subscripts_with_context(
        r"M_{j\star} - M_{j\star}",
        [_OcrBox(0, 0, 20, 15, "Mj(湿)")],
        sym_table,
    )
    assert r"M_{j(\text{湿})} - M_{j(\text{干})}" in repaired_dup


def test_sample_pdf_subscript_and_chemical_extraction() -> None:
    if not SAMPLE_PDF.is_file():
        pytest.skip("Sample PDF not present in workspace")
    doc = fitz.open(str(SAMPLE_PDF))
    collected: list[str] = []
    try:
        for pi in (1, 4, 8, 9, 10):
            blks, _, _ = _extract_page_structure_pymupdf(doc[pi], pi)
            for b in blks:
                for inl in b.inlines:
                    if inl.t == "math":
                        collected.append(inl.latex)
                if b.table:
                    for c in b.table.cells:
                        for inl in c.inlines:
                            if inl.t == "math":
                                collected.append(inl.latex)
    finally:
        doc.close()

    joined = "\n".join(collected)
    for expected in (
        r"V_0",
        r"\mathrm{FeCl}_3",
        r"\mathrm{Al}_2(\mathrm{SO}_4)_3",
        r"P_w",
        r"\rho_s",
        r"W_0",
        r"W_1",
        r"C_{\text{卡}}",
        r"\Delta t_1",
        r"\mathrm{kg/m}^3",
        r"\mathrm{g/cm}^3",
        r"M_{j(\text{湿})}",
        r"M_{j(\text{干})}",
    ):
        assert expected in joined, f"Missing expected inline math {expected!r} in PDF extraction"


def test_compact_chemical_handwriting_metrics() -> None:
    hw_path = ROOT / "fonts" / "personal.hwfont"
    if not hw_path.is_file():
        pytest.skip("personal.hwfont not present")
    reg = WriterRegistry(ROOT / "fonts")
    reader = reg.get("personal")
    assert reader is not None
    sel = VariantSelector(reader, fallback_policy="blank")

    ml_al = typeset_math(r"\mathrm{Al}_2(\mathrm{SO}_4)_3", sel, font_size_mm=6.0, display=False)
    ml_fe = typeset_math(r"\mathrm{FeCl}_3", sel, font_size_mm=6.0, display=False)
    ml_v0 = typeset_math(r"V_0", sel, font_size_mm=6.0, display=False)

    assert len(ml_al.strokes) >= 8
    assert ml_al.width_mm < 20.5  # Compact chemical width (< 3.42 em, far tighter than raw CJK advance)
    assert ml_al.depth_mm >= 0.8   # Subscripts visibly lowered beneath baseline
    assert ml_fe.width_mm < 13.0
    assert ml_v0.width_mm < 8.5


def test_grbl_calibration_endpoints_and_safety(tmp_path: Path) -> None:
    app = create_app(_make_test_settings(tmp_path))
    with TestClient(app) as client:
        conn = client.post(
            "/api/v1/machine/connect",
            json={"port": "MOCK", "baud": 115200, "profile_id": "corexy_servo_a4", "mock": True},
        )
        assert conn.status_code == 200

        # Prepare composed demo layout
        ly_resp = client.post("/api/v1/layouts", json={"doc_id": "doc_demo"})
        assert ly_resp.status_code == 202
        ly_id = ly_resp.json()["layout_id"]
        t = _wait_task(client, ly_resp.json()["task_id"])
        assert t["state"] == "done"

        # 1. Jog -> Zero -> Jog -> Goto-Zero returns cleanly to WPos (0, 0)
        assert client.post("/api/v1/machine/jog", json={"dx": 12.0, "dy": 18.0, "feed": 3000}).status_code == 200
        time.sleep(0.12)
        z = client.post("/api/v1/machine/zero", json={"axes": ["X", "Y"]})
        assert z.status_code == 200
        assert z.json()["wpos"]["x"] == pytest.approx(0.0, abs=0.25)

        assert client.post("/api/v1/machine/jog", json={"dx": 15.0, "dy": 20.0, "feed": 3000}).status_code == 200
        time.sleep(0.15)
        gz = client.post("/api/v1/machine/goto-zero")
        assert gz.status_code == 200
        assert gz.json()["wpos"]["x"] == pytest.approx(0.0, abs=0.25)
        assert gz.json()["wpos"]["y"] == pytest.approx(0.0, abs=0.25)

        # 2. Move-to valid vs soft-limit rejection
        mt = client.post("/api/v1/machine/move-to", json={"x": 25.0, "y": 35.0, "pen_up": True})
        assert mt.status_code == 200
        assert mt.json()["wpos"]["x"] == pytest.approx(25.0, abs=0.25)
        oob = client.post("/api/v1/machine/move-to", json={"x": 999.0, "y": 10.0, "pen_up": True})
        assert oob.status_code == 422

        # 3. Move-to-start goes to first stroke of P0
        ms = client.post("/api/v1/machine/move-to-start", json={"layout_id": ly_id, "page_index": 0})
        assert ms.status_code == 200
        ms_body = ms.json()
        assert ms_body["source"] == "page_first_stroke"
        assert ms_body["wpos"]["x"] == pytest.approx(ms_body["target"]["x"], abs=0.35)
        assert ms_body["wpos"]["y"] == pytest.approx(ms_body["target"]["y"], abs=0.35)

        # 4. Raw command $$ query and Home $H
        raw = client.post("/api/v1/machine/raw", json={"command": "$$"})
        assert raw.status_code == 200
        assert any(ln.startswith("$130=") for ln in raw.json()["responses"])

        hm = client.post("/api/v1/machine/home")
        assert hm.status_code == 200
        assert hm.json()["mpos"]["x"] == pytest.approx(0.0, abs=0.1)
        assert hm.json()["wpos"]["x"] == pytest.approx(0.0, abs=0.1)

        # 5. Live pen calibration override
        pd = client.post("/api/v1/machine/pen", json={"state": "down", "override_cmd": "M3 S75"})
        assert pd.status_code == 200 and pd.json()["pen"] == "down"
        pu = client.post("/api/v1/machine/pen", json={"state": "up", "override_cmd": "M5"})
        assert pu.status_code == 200 and pu.json()["pen"] == "up"

        # 6. Move-to-start while PAUSED targets exact resume_breakpoint
        jb = client.post("/api/v1/jobs", json={"layout_id": ly_id, "page_indices": [0], "start_page_index": 0})
        assert jb.status_code == 201
        job_id = jb.json()["job_id"]
        time.sleep(0.06)
        assert client.post(f"/api/v1/jobs/{job_id}/pause").status_code == 200
        bp = client.post("/api/v1/machine/move-to-start", json={"layout_id": ly_id, "page_index": 0})
        assert bp.status_code == 200
        assert bp.json()["source"] == "resume_breakpoint"
        assert client.post(f"/api/v1/jobs/{job_id}/abort").status_code == 200


def test_symbol_def_leading_subscripts_merge_and_uniform_indent(tmp_path: Path) -> None:
    # 1. Leading variable+subscript normalization helper
    assert normalize_symbol_def_leading_subscript("Wi，调理剂添加量，%") == "$W_i$，调理剂添加量，%"
    assert normalize_symbol_def_leading_subscript("Vi，调理剂溶液添加体积，mL") == "$V_i$，调理剂溶液添加体积，mL"
    assert normalize_symbol_def_leading_subscript("Ci，调理剂溶液浓度，g/L") == "$C_i$，调理剂溶液浓度，g/L"
    assert normalize_symbol_def_leading_subscript("Vs，污泥体积，mL") == "$V_s$，污泥体积，mL"
    assert normalize_symbol_def_leading_subscript("Pw，污泥含水率") == "$P_w$，污泥含水率"
    assert normalize_symbol_def_leading_subscript("式中Wi，添加量") == "式中$W_i$，添加量"
    assert normalize_symbol_def_leading_subscript(r"$\rho_s$ ，污泥密度") == r"$\rho_s$，污泥密度"
    # Negatives (acronyms, single vars, mixed-case pH) remain untouched
    assert normalize_symbol_def_leading_subscript("CST，毛细吸水时间，s") == "CST，毛细吸水时间，s"
    assert normalize_symbol_def_leading_subscript("pH，酸碱度") == "pH，酸碱度"
    assert normalize_symbol_def_leading_subscript("A--垃圾灰分含量") == "A--垃圾灰分含量"

    if not SAMPLE_PDF.is_file():
        pytest.skip("Sample PDF not present in workspace")

    doc = parse_pdf(SAMPLE_PDF, doc_id="doc_sym", out_dir=tmp_path / "sym_out", use_mineru=False)
    sym_blocks = [b for b in doc.blocks if is_symbol_def_block(b)]
    target_sym = next((b for b in sym_blocks if "调理剂添加量" in b.plain_text()), None)
    assert target_sym is not None, "Expected P10/P11 conditioning-agent symbol-def block"

    tex_items = [inl.latex for inl in target_sym.inlines if isinstance(inl, MathInline)]
    for expected_tex in ("W_i", "V_i", "C_i", "V_s", r"\rho_s", "P_w"):
        assert expected_tex in tex_items, f"Missing {expected_tex!r} in {tex_items!r}"
    assert "污泥含水率" in target_sym.plain_text()
    assert {ln.page_index for ln in target_sym.lines if ln.page_index is not None} == {9, 10}

    # Earlier formula symbol blocks (P2 `式中Mj(湿)`, P3 `式中A`, P5 `式中Q`) should also merge cleanly
    assert any("M_{j(" in "".join(inl.latex for inl in b.inlines if isinstance(inl, MathInline)) for b in sym_blocks)
    assert any("灰分含量" in b.plain_text() and "灼烧" in b.plain_text() for b in sym_blocks)
    assert any("热值" in b.plain_text() and "铁丝的长度" in b.plain_text() for b in sym_blocks)

    # 2. Verify EVERY physical row of `target_sym` is indented in Reflow composition (not flush-left)
    hw_path = ROOT / "fonts" / "personal.hwfont"
    if not hw_path.is_file():
        pytest.skip("personal.hwfont not present")
    reg = WriterRegistry(ROOT / "fonts")
    reader = reg.get("personal")
    assert reader is not None
    mini_doc = DocIR(
        doc_id="doc_sym_mini",
        source=DocSource(type="pdf", filename="sym.pdf", sha256="sym", parser="pymupdf"),
        pages=[DocPageInfo(page_index=0, width_mm=210.0, height_mm=297.0)],
        blocks=[target_sym.model_copy(deep=True, update={"page_index": 0, "reading_order": 0})],
    )
    cfg = LayoutConfig(mode="reflow")
    composed = compose_document(mini_doc, reader, cfg)
    assert len(composed) == 1
    blk_strokes = [st for st in composed[0].strokes if st.block_id == target_sym.block_id]
    assert blk_strokes
    # Group strokes into 6 physical rows (y buckets spaced by ~line pitch; pts is flat [x0, y0, ...])
    row_buckets: list[list[float]] = []
    for st in sorted(blk_strokes, key=lambda s: min(s.pts[1::2])):
        xs = st.pts[0::2]
        ys = st.pts[1::2]
        if not xs or not ys:
            continue
        min_x = min(xs)
        min_y = min(ys)
        if not row_buckets or abs(min_y - row_buckets[-1][0]) > cfg.text.font_size_mm * 0.9:
            row_buckets.append([min_y, min_x])
        else:
            row_buckets[-1].append(min_x)

    assert len(row_buckets) >= 6
    indent_floor = cfg.page.margins_mm.left + cfg.text.font_size_mm * 1.5
    for idx, bucket in enumerate(row_buckets):
        row_min_x = min(bucket[1:])
        assert row_min_x >= indent_floor, (
            f"Row {idx} of symbol-def block was not indented: row_min_x={row_min_x:.2f} < {indent_floor:.2f}"
        )
