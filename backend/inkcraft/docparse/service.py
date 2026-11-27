"""Public facade for document parsing: DOCX, PDF, plain text/Markdown, and rich demo DocIR."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Callable

from inkcraft.docparse.docir import (
    ChartData,
    ChartSeries,
    DocBlock,
    DocInline,
    DocIR,
    DocLine,
    DocPageInfo,
    DocSource,
    MathInline,
    TableCell,
    TableData,
    TextInline,
)
from inkcraft.docparse.docx_parser import parse_docx
from inkcraft.docparse.pdf_parser import parse_pdf, split_inline_math

ProgressHook = Callable[[str, float, int, int, str], None]

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST_RE = re.compile(r"^(?:[-*•]|\d+[.)、])\s+(.*)$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)+\|?\s*$")


def _split_md_table_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [cell.strip() for cell in s.split("|")]


def decode_text_bytes(raw: bytes) -> str:
    """Decode user text files: UTF-8 (with/without BOM), UTF-16 BOM, else GB18030.

    奎享雕刻 and most Windows Chinese editors save ``.txt`` as GBK, which would
    otherwise be garbled by a UTF-8 decode.
    """
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_plain_text(title: str, text: str, doc_id: str) -> DocIR:
    """Parse plain text / Markdown with `#` headings, `$$...$$`, `$...$`, and pipe tables into DocIR."""
    raw = text or ""
    sha256 = hashlib.sha256(f"{title}\n{raw}".encode("utf-8")).hexdigest()
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    blocks: list[DocBlock] = []
    cursor_y = 22.0

    def _add_block(
        btype: str,
        *,
        inlines: list[DocInline] | None = None,
        latex: str | None = None,
        table: TableData | None = None,
        level: int = 1,
        est_h: float = 10.0,
    ) -> None:
        nonlocal cursor_y
        bidx = len(blocks)
        y0 = round(cursor_y, 2)
        y1 = round(min(280.0, y0 + est_h), 2)
        cursor_y = min(275.0, y1 + 3.0)
        doc_lines: list[DocLine] = []
        if inlines:
            doc_lines = [DocLine(bbox_mm=[20.0, y0, 190.0, y1], inlines=inlines)]
        blocks.append(
            DocBlock(
                block_id=f"p0-b{bidx}",
                page_index=0,
                type=btype,  # type: ignore[arg-type]
                reading_order=bidx,
                level=level,
                bbox_mm=[20.0, y0, 190.0, y1],
                lines=doc_lines,
                inlines=inlines or [],
                latex=latex,
                table=table,
            )
        )

    # Check if the first non-empty line is already a heading; if not and title is given, emit title
    first_non_empty = next((ln.strip() for ln in lines if ln.strip()), "")
    if title.strip() and not _HEADING_RE.match(first_non_empty):
        _add_block("heading", inlines=split_inline_math(title.strip()), level=1, est_h=11.0)

    i = 0
    n = len(lines)
    para_buf: list[str] = []

    def _flush_para() -> None:
        nonlocal para_buf
        if not para_buf:
            return
        joined = " ".join(part.strip() for part in para_buf if part.strip()).strip()
        para_buf = []
        if not joined:
            return
        inlines = split_inline_math(joined)
        est_lines = max(1, (len(joined) // 26) + 1)
        _add_block("paragraph", inlines=inlines, est_h=est_lines * 8.5)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            _flush_para()
            i += 1
            continue

        # 1. Display math block `$$ ... $$`
        if stripped.startswith("$$"):
            _flush_para()
            if stripped.endswith("$$") and len(stripped) >= 4:
                tex = stripped[2:-2].strip()
                if tex:
                    _add_block("formula_block", latex=tex, est_h=16.0)
                i += 1
                continue
            math_lines = [stripped[2:]]
            i += 1
            while i < n:
                cur = lines[i].strip()
                if cur.endswith("$$"):
                    math_lines.append(cur[:-2])
                    i += 1
                    break
                math_lines.append(cur)
                i += 1
            tex = " ".join(m.strip() for m in math_lines if m.strip()).strip()
            if tex:
                _add_block("formula_block", latex=tex, est_h=16.0)
            continue

        # 2. Markdown heading `# ...`
        hm = _HEADING_RE.match(stripped)
        if hm:
            _flush_para()
            lvl = len(hm.group(1))
            htext = hm.group(2).strip()
            if htext:
                _add_block("heading", inlines=split_inline_math(htext), level=lvl, est_h=10.5)
            i += 1
            continue

        # 3. Markdown pipe table
        if "|" in stripped and (i + 1) < n and _TABLE_SEP_RE.match(lines[i + 1]):
            _flush_para()
            header_cells = _split_md_table_row(stripped)
            table_rows: list[list[str]] = [header_cells]
            i += 2  # skip separator row
            while i < n and "|" in lines[i].strip() and lines[i].strip():
                table_rows.append(_split_md_table_row(lines[i]))
                i += 1
            ncols = max(len(r) for r in table_rows)
            if ncols > 0:
                cells: list[TableCell] = []
                for r_i, row in enumerate(table_rows):
                    for c_i in range(ncols):
                        val = row[c_i] if c_i < len(row) else ""
                        cells.append(
                            TableCell(
                                r=r_i,
                                c=c_i,
                                rs=1,
                                cs=1,
                                inlines=split_inline_math(val) if val else [],
                            )
                        )
                col_w = round(170.0 / ncols, 2)
                tdata = TableData(
                    rows=len(table_rows),
                    cols=ncols,
                    col_widths_mm=[col_w] * ncols,
                    cells=cells,
                )
                _add_block("table", table=tdata, est_h=max(18.0, len(table_rows) * 10.0))
            continue

        # 4. List item
        lm = _LIST_RE.match(stripped)
        if lm:
            _flush_para()
            _add_block("list_item", inlines=split_inline_math(stripped), est_h=9.0)
            i += 1
            continue

        # 5. Normal paragraph line
        para_buf.append(stripped)
        i += 1

    _flush_para()

    return DocIR(
        doc_id=doc_id,
        source=DocSource(
            type="text",
            filename=f"{title or 'note'}.txt",
            sha256=sha256,
            parser="plain-text-markdown",
        ),
        pages=[DocPageInfo(page_index=0, width_mm=210.0, height_mm=297.0, image=None)],
        blocks=blocks,
    )


def parse_document(
    file_path: Path,
    doc_id: str,
    out_dir: Path,
    mode_hint: str | None = None,
    progress_cb: ProgressHook | None = None,
) -> DocIR:
    """Route an uploaded `.docx`, `.pdf`, or `.txt`/`.md` file to the appropriate parser."""
    path = Path(file_path).resolve()
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()

    if suffix == ".docx":
        doc_ir = parse_docx(path, doc_id=doc_id, out_dir=out_path, progress_cb=progress_cb)
    elif suffix == ".pdf":
        doc_ir = parse_pdf(path, doc_id=doc_id, out_dir=out_path, progress_cb=progress_cb)
    elif suffix in {".txt", ".md"}:
        if progress_cb is not None:
            progress_cb("convert", 0.3, 0, 1, f"正在解析文本: {path.name}")
        content = decode_text_bytes(path.read_bytes())
        doc_ir = parse_plain_text(path.stem, content, doc_id=doc_id)
        if progress_cb is not None:
            progress_cb("done", 1.0, 1, 1, "文本解析完成")
    else:
        raise ValueError(f"Unsupported document format: '{suffix}' (expected .docx, .pdf, .txt, .md)")

    # Persist DocIR artifact for inspection / caching
    (out_path / "docir.json").write_text(doc_ir.model_dump_json(indent=2), encoding="utf-8")
    return doc_ir


def build_demo_docir(doc_id: str = "doc_demo") -> DocIR:
    """Build a rich 2-page Chinese + LaTeX math + table + bar/line chart demo DocIR.

    Includes exact `bbox_mm` and `lines[].bbox_mm` coordinates on both A4 pages so both
    Smart Reflow and Exact Overlay modes render cleanly right out of the box.
    """
    p0_blocks: list[DocBlock] = [
        DocBlock(
            block_id="p0-b0",
            page_index=0,
            type="heading",
            reading_order=0,
            level=1,
            bbox_mm=[20.0, 22.0, 190.0, 34.0],
            lines=[
                DocLine(
                    bbox_mm=[20.0, 22.0, 190.0, 34.0],
                    inlines=[TextInline(text="手写字机系统实验与数学公式分析报告", bold=True)],
                )
            ],
            inlines=[TextInline(text="手写字机系统实验与数学公式分析报告", bold=True)],
        ),
        DocBlock(
            block_id="p0-b1",
            page_index=0,
            type="paragraph",
            reading_order=1,
            bbox_mm=[20.0, 39.0, 190.0, 67.0],
            lines=[
                DocLine(
                    bbox_mm=[20.0, 39.0, 190.0, 48.0],
                    inlines=[
                        TextInline(text="永和九年，本文测试多笔迹单线书写系统。正文与行内公式 "),
                        MathInline(latex="E = mc^2"),
                        TextInline(text=" 统一调用"),
                    ],
                ),
                DocLine(
                    bbox_mm=[20.0, 49.0, 190.0, 58.0],
                    inlines=[
                        TextInline(text="当前书写者字形，并满足角度关系 "),
                        MathInline(latex=r"\alpha + \beta = \pi"),
                        TextInline(text=" 与可控随机扰动。"),
                    ],
                ),
            ],
            inlines=[
                TextInline(text="永和九年，本文测试多笔迹单线书写系统。正文与行内公式 "),
                MathInline(latex="E = mc^2"),
                TextInline(text=" 统一调用当前书写者字形，并满足角度关系 "),
                MathInline(latex=r"\alpha + \beta = \pi"),
                TextInline(text=" 与可控随机扰动，确保自然手写笔顺。"),
            ],
        ),
        DocBlock(
            block_id="p0-b2",
            page_index=0,
            type="formula_block",
            reading_order=2,
            bbox_mm=[28.0, 72.0, 182.0, 96.0],
            latex=r"y = \int_{0}^{\pi} \frac{\sin(x) + \alpha}{x^2 + 1} dx",
        ),
        DocBlock(
            block_id="p0-b3",
            page_index=0,
            type="formula_block",
            reading_order=3,
            bbox_mm=[28.0, 102.0, 182.0, 126.0],
            latex=r"S_n = \sum_{k=1}^{n} \sqrt{k^2 + \Delta x} \pm \varepsilon",
        ),
        DocBlock(
            block_id="p0-b4",
            page_index=0,
            type="heading",
            reading_order=4,
            level=2,
            bbox_mm=[20.0, 134.0, 190.0, 144.0],
            lines=[
                DocLine(
                    bbox_mm=[20.0, 134.0, 190.0, 144.0],
                    inlines=[TextInline(text="一、实验数据与控制结果表", bold=True)],
                )
            ],
            inlines=[TextInline(text="一、实验数据与控制结果表", bold=True)],
        ),
        DocBlock(
            block_id="p0-b5",
            page_index=0,
            type="table",
            reading_order=5,
            bbox_mm=[20.0, 148.0, 190.0, 198.0],
            table=TableData(
                rows=4,
                cols=4,
                col_widths_mm=[42.0, 42.0, 44.0, 42.0],
                row_heights_mm=[12.0, 12.0, 12.0, 12.0],
                cells=[
                    TableCell(r=0, c=0, inlines=[TextInline(text="测试组", bold=True)]),
                    TableCell(r=0, c=1, inlines=[TextInline(text="字号(mm)", bold=True)]),
                    TableCell(r=0, c=2, inlines=[TextInline(text="公式误差", bold=True)]),
                    TableCell(r=0, c=3, inlines=[TextInline(text="结论", bold=True)]),
                    TableCell(r=1, c=0, inlines=[TextInline(text="A1 行楷")]),
                    TableCell(r=1, c=1, inlines=[TextInline(text="6.0")]),
                    TableCell(r=1, c=2, inlines=[MathInline(latex=r"\pm 0.05")]),
                    TableCell(r=1, c=3, inlines=[TextInline(text="正常")]),
                    TableCell(r=2, c=0, inlines=[TextInline(text="A2 行书")]),
                    TableCell(r=2, c=1, inlines=[TextInline(text="6.5")]),
                    TableCell(r=2, c=2, inlines=[MathInline(latex=r"\pm 0.08")]),
                    TableCell(r=2, c=3, inlines=[TextInline(text="正常")]),
                    TableCell(r=3, c=0, inlines=[TextInline(text="A3 工程")]),
                    TableCell(r=3, c=1, inlines=[TextInline(text="5.5")]),
                    TableCell(r=3, c=2, inlines=[MathInline(latex=r"\pm 0.03")]),
                    TableCell(r=3, c=3, inlines=[TextInline(text="稳定")]),
                ],
            ),
        ),
        DocBlock(
            block_id="p0-b6",
            page_index=0,
            type="paragraph",
            reading_order=6,
            bbox_mm=[20.0, 206.0, 190.0, 232.0],
            lines=[
                DocLine(
                    bbox_mm=[20.0, 206.0, 190.0, 215.0],
                    inlines=[TextInline(text="上表统计了三组手写字形在 A4 纸面上的实测结果，所有笔画均保持")],
                ),
                DocLine(
                    bbox_mm=[20.0, 216.0, 190.0, 225.0],
                    inlines=[TextInline(text="自然书写顺序，并通过同字异形与基线波动消除重复机械感。")],
                ),
            ],
            inlines=[
                TextInline(
                    text="上表统计了三组手写字形在 A4 纸面上的实测结果，所有笔画均保持自然书写顺序，并通过同字异形与基线波动消除重复机械感。"
                )
            ],
        ),
    ]

    p1_blocks: list[DocBlock] = [
        DocBlock(
            block_id="p1-b0",
            page_index=1,
            type="heading",
            reading_order=7,
            level=2,
            bbox_mm=[20.0, 22.0, 190.0, 33.0],
            lines=[
                DocLine(
                    bbox_mm=[20.0, 22.0, 190.0, 33.0],
                    inlines=[TextInline(text="二、图表分析与单线剖面填充测试", bold=True)],
                )
            ],
            inlines=[TextInline(text="二、图表分析与单线剖面填充测试", bold=True)],
        ),
        DocBlock(
            block_id="p1-b1",
            page_index=1,
            type="paragraph",
            reading_order=8,
            bbox_mm=[20.0, 38.0, 190.0, 56.0],
            lines=[
                DocLine(
                    bbox_mm=[20.0, 38.0, 190.0, 47.0],
                    inlines=[TextInline(text="下图展示两组实验柱状图与折线图，柱体内部采用手绘剖面线填充。")],
                ),
            ],
            inlines=[TextInline(text="下图展示两组实验柱状图与折线图，柱体内部采用手绘剖面线填充，标签与刻度均使用当前书写者单线笔迹。")],
        ),
        DocBlock(
            block_id="p1-b2",
            page_index=1,
            type="chart",
            reading_order=9,
            bbox_mm=[22.0, 62.0, 188.0, 134.0],
            chart=ChartData(
                chart_type="bar",
                title="实验效率对比 (Bar)",
                x_label="Test",
                y_label="Score",
                categories=["T1", "T2", "T3", "T4"],
                series=[
                    ChartSeries(name="S1", values=[62.0, 78.0, 85.0, 94.0]),
                    ChartSeries(name="S2", values=[48.0, 65.0, 74.0, 88.0]),
                ],
                extra={"origin": "demo"},
            ),
        ),
        DocBlock(
            block_id="p1-b3",
            page_index=1,
            type="chart",
            reading_order=10,
            bbox_mm=[22.0, 144.0, 188.0, 212.0],
            chart=ChartData(
                chart_type="line",
                title="路径收敛曲线 (Line)",
                x_label="Step",
                y_label="mm",
                categories=["1", "2", "3", "4", "5"],
                series=[
                    ChartSeries(name="Base", values=[95.0, 72.0, 58.0, 46.0, 39.0]),
                    ChartSeries(name="2-Opt", values=[80.0, 54.0, 41.0, 32.0, 27.0]),
                ],
                extra={"origin": "demo"},
            ),
        ),
        DocBlock(
            block_id="p1-b4",
            page_index=1,
            type="formula_block",
            reading_order=11,
            bbox_mm=[30.0, 222.0, 180.0, 250.0],
            latex=r"\begin{pmatrix} x' \\ y' \end{pmatrix} = \begin{pmatrix} 1 & \theta \\ 0 & 1 \end{pmatrix} \begin{pmatrix} x \\ y \end{pmatrix}",
        ),
    ]

    all_blocks = p0_blocks + p1_blocks
    sha = hashlib.sha256(f"demo-v1:{doc_id}:{len(all_blocks)}".encode("utf-8")).hexdigest()
    return DocIR(
        doc_id=doc_id,
        source=DocSource(
            type="text",
            filename="demo_handwrite_report.docx",
            sha256=sha,
            parser="builtin-demo",
        ),
        pages=[
            DocPageInfo(page_index=0, width_mm=210.0, height_mm=297.0, image=None),
            DocPageInfo(page_index=1, width_mm=210.0, height_mm=297.0, image=None),
        ],
        blocks=all_blocks,
    )
