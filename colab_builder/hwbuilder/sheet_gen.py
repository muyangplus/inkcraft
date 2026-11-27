"""Printable A4 handwriting collection sheet generator (PDF + PNG preview + JSON manifest).

Generates A4 sheets with:
  - 4 corner ArUco-compatible (DICT_4X4_50 IDs 0..3) fiducial markers for exact scan alignment
  - Faint drop-out cyan or red writing grid cells (Tian/Mi guide lines) removable by color filtering
  - Per-cell character prompt header & page identification strip
  - Deterministic JSON manifest mapping `(page, row, col) -> char` and exact `write_box_mm`
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Literal, Sequence

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    try:
        import fitz  # type: ignore[no-redef]
    except ImportError:
        fitz = None  # type: ignore[assignment]


MM_TO_PT: float = 72.0 / 25.4
A4_WIDTH_MM: float = 210.0
A4_HEIGHT_MM: float = 297.0

# Exact OpenCV ArUco DICT_4X4_50 4x4 interior bit patterns for marker IDs 0, 1, 2, 3
# (1 = white interior cell, 0 = black interior cell; surrounded by 1-cell black border)
ARUCO_4X4_PATTERNS: dict[int, tuple[tuple[int, int, int, int], ...]] = {
    0: (
        (1, 0, 1, 1),
        (0, 1, 0, 1),
        (0, 0, 1, 1),
        (0, 0, 1, 0),
    ),
    1: (
        (0, 0, 0, 0),
        (1, 1, 1, 1),
        (1, 0, 0, 1),
        (1, 0, 1, 0),
    ),
    2: (
        (0, 0, 1, 1),
        (0, 0, 1, 1),
        (0, 0, 1, 0),
        (1, 1, 0, 1),
    ),
    3: (
        (1, 0, 0, 1),
        (1, 0, 0, 1),
        (0, 1, 0, 0),
        (0, 1, 1, 0),
    ),
}

# Representative core collection set: digits + Latin + common punctuation/math + ~240 high-frequency
# Chinese characters covering primary GB2312 radicals & stroke combinations.
DEFAULT_DIGITS_LATIN: str = (
    "0123456789"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
)

DEFAULT_PUNCT_SYMBOLS: str = (
    "，。、；：？！（）《》“”‘’—…·"
    ",.;:?!()[]{}+-*/=<>^_%~|@#"
    "±×÷≤≥≠≈∞∑∫√παβγθλμσΔΩ"
)

DEFAULT_CJK_RADICAL_SAMPLE: str = (
    "永和九年岁在癸丑暮春之初会于会稽山阴之兰亭修禊事也"
    "群贤毕至少长咸集此地有崇山峻岭茂林修竹又有清流激湍"
    "映带左右引以为流觞曲水列坐其次虽无丝竹管弦之盛一觞"
    "一咏亦足以畅叙幽情是日也天朗气清惠风和畅仰观宇宙之"
    "大俯察品类之盛所以游目骋怀足以极视听之娱信可乐也"
    "人大小中上下左右天地日月水火木金土石山川风雨云电光"
    "学习工作研究实验数据分析算法模型系统工程机械控制自动"
    "证明求解函数方程矩阵向量概率统计物理化学材料力学光学"
    "中国北京上海深圳科技大学图书馆报告论文摘要结论参考文献"
    "一二三四五六七八九十百千万亿零两第页行段图表公式题目"
    "我的你他她它们这那什么为什么怎么如何可以应该必须能够"
    "时间空间速度位置温度压力电流电压频率精度误差质量效率"
)

DEFAULT_CORE_CHARSET: str = "".join(
    dict.fromkeys(DEFAULT_DIGITS_LATIN + DEFAULT_PUNCT_SYMBOLS + DEFAULT_CJK_RADICAL_SAMPLE)
)

GridColor = Literal["cyan", "red"]


@dataclass
class SheetConfig:
    """Layout parameters for printable A4 handwriting collection sheets."""

    writer_name: str = "unnamed_writer"
    page_width_mm: float = A4_WIDTH_MM
    page_height_mm: float = A4_HEIGHT_MM
    rows: int = 12
    cols: int = 10
    margin_x_mm: float = 16.0
    margin_top_mm: float = 28.0
    margin_bottom_mm: float = 20.0
    cell_gap_x_mm: float = 2.0
    cell_gap_y_mm: float = 2.5
    prompt_h_mm: float = 4.2
    fiducial_size_mm: float = 10.0
    fiducial_inset_mm: float = 7.0
    grid_color: GridColor = "cyan"
    guide_style: Literal["cross", "mi", "none"] = "cross"
    preview_dpi: int = 150
    repeat_ascii: int = 1
    repeat_cjk: int = 1


@dataclass
class SheetCellSpec:
    """Deterministic metadata for a single grid cell on a collection sheet."""

    cell_id: str
    page: int
    row: int
    col: int
    char: str
    codepoint: int
    repeat_index: int
    write_box_mm: list[float]  # [x0, y0, x1, y1] writing area only (excludes prompt strip)
    full_box_mm: list[float]   # [x0, y0, x1, y1] full cell including prompt strip


@dataclass
class SheetPageSpec:
    """Metadata for a single generated page."""

    page_index: int
    preview_png: str
    cells: list[SheetCellSpec] = field(default_factory=list)


@dataclass
class SheetManifest:
    """Full manifest saved to `manifest.json` for deterministic scan alignment."""

    schema_version: str = "1.0"
    writer_name: str = "unnamed_writer"
    page_width_mm: float = A4_WIDTH_MM
    page_height_mm: float = A4_HEIGHT_MM
    grid_color: GridColor = "cyan"
    rows: int = 12
    cols: int = 10
    fiducials_mm: dict[str, list[float]] = field(default_factory=dict)
    pdf_path: str = ""
    pages: list[SheetPageSpec] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: str | Path) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return out

    @classmethod
    def load(cls, path: str | Path) -> SheetManifest:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        pages = [
            SheetPageSpec(
                page_index=int(p["page_index"]),
                preview_png=str(p.get("preview_png", "")),
                cells=[SheetCellSpec(**c) for c in p.get("cells", [])],
            )
            for p in raw.get("pages", [])
        ]
        return cls(
            schema_version=str(raw.get("schema_version", "1.0")),
            writer_name=str(raw.get("writer_name", "")),
            page_width_mm=float(raw["page_width_mm"]),
            page_height_mm=float(raw["page_height_mm"]),
            grid_color=raw.get("grid_color", "cyan"),
            rows=int(raw["rows"]),
            cols=int(raw["cols"]),
            fiducials_mm=dict(raw["fiducials_mm"]),
            pdf_path=str(raw.get("pdf_path", "")),
            pages=pages,
        )


def _grid_rgb(color: GridColor) -> tuple[float, float, float]:
    """Drop-out friendly RGB colors (0..1) easily separable from black/dark ink."""
    if color == "red":
        return (0.95, 0.45, 0.45)
    return (0.35, 0.80, 0.94)


def _guide_rgb(color: GridColor) -> tuple[float, float, float]:
    if color == "red":
        return (0.98, 0.72, 0.72)
    return (0.68, 0.91, 0.98)


def _draw_aruco_marker(
    page: fitz.Page,
    cx_mm: float,
    cy_mm: float,
    size_mm: float,
    marker_id: int,
) -> None:
    """Draw a 6x6 (1-cell black border + 4x4 ArUco data) marker centered at `(cx_mm, cy_mm)`."""
    pattern = ARUCO_4X4_PATTERNS[marker_id % 4]
    x0 = (cx_mm - size_mm / 2.0) * MM_TO_PT
    y0 = (cy_mm - size_mm / 2.0) * MM_TO_PT
    size_pt = size_mm * MM_TO_PT
    cell_pt = size_pt / 6.0

    # Outer black square
    page.draw_rect(
        fitz.Rect(x0, y0, x0 + size_pt, y0 + size_pt),
        color=None,
        fill=(0.0, 0.0, 0.0),
    )

    # Interior 4x4 white cells
    for r in range(4):
        for c in range(4):
            if pattern[r][c] == 1:
                rx0 = x0 + (c + 1) * cell_pt
                ry0 = y0 + (r + 1) * cell_pt
                page.draw_rect(
                    fitz.Rect(rx0, ry0, rx0 + cell_pt, ry0 + cell_pt),
                    color=None,
                    fill=(1.0, 1.0, 1.0),
                )


def _draw_page_id_bars(
    page: fitz.Page,
    page_index: int,
    width_mm: float,
    top_mm: float,
) -> None:
    """Draw an 8-bit binary page ID strip at top-center for visual/automated page identification."""
    bits = [(page_index >> (7 - i)) & 1 for i in range(8)]
    bar_w = 2.6 * MM_TO_PT
    bar_h = 3.2 * MM_TO_PT
    gap = 1.0 * MM_TO_PT
    total_w = 8 * bar_w + 7 * gap
    start_x = (width_mm * MM_TO_PT - total_w) / 2.0
    y0 = top_mm * MM_TO_PT

    for idx, bit in enumerate(bits):
        x0 = start_x + idx * (bar_w + gap)
        rect = fitz.Rect(x0, y0, x0 + bar_w, y0 + bar_h)
        if bit:
            page.draw_rect(rect, color=(0.0, 0.0, 0.0), fill=(0.0, 0.0, 0.0), width=0.5)
        else:
            page.draw_rect(rect, color=(0.0, 0.0, 0.0), fill=(1.0, 1.0, 1.0), width=0.5)


def _insert_prompt_text(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    fontsize: float,
    color: tuple[float, float, float],
) -> None:
    """Render prompt character inside `rect`, using CJK font when needed and safe fallback."""
    is_ascii = all(ord(ch) < 128 for ch in text)
    fontname = "helv" if is_ascii else "china-s"
    try:
        rc = page.insert_textbox(
            rect,
            text,
            fontsize=fontsize,
            fontname=fontname,
            color=color,
            align=fitz.TEXT_ALIGN_CENTER,
        )
        if rc < 0:
            page.insert_text(
                fitz.Point(rect.x0 + rect.width * 0.3, rect.y1 - 1.5),
                text,
                fontsize=max(6.0, fontsize * 0.8),
                fontname=fontname,
                color=color,
            )
    except Exception:
        # Fallback to unicode codepoint label if CJK built-in font is unavailable
        fallback = text if is_ascii else f"U+{ord(text[0]):04X}"
        page.insert_textbox(
            rect,
            fallback,
            fontsize=max(5.5, fontsize * 0.65),
            fontname="helv",
            color=color,
            align=fitz.TEXT_ALIGN_CENTER,
        )


def _expand_char_list(chars: Sequence[str] | str, cfg: SheetConfig) -> list[tuple[str, int]]:
    """Expand character sequence into `(char, repeat_index)` entries."""
    items: list[tuple[str, int]] = []
    seen_counts: dict[str, int] = {}
    for ch in chars:
        if not ch or ch.isspace():
            continue
        c = ch[0]
        reps = cfg.repeat_ascii if ord(c) < 128 else cfg.repeat_cjk
        for _ in range(max(1, reps)):
            rep_idx = seen_counts.get(c, 0)
            seen_counts[c] = rep_idx + 1
            items.append((c, rep_idx))
    return items


def compute_fiducials_mm(cfg: SheetConfig) -> dict[str, list[float]]:
    """Compute exact `(cx_mm, cy_mm, size_mm)` for the 4 corner fiducial markers."""
    s = cfg.fiducial_size_mm
    half = s / 2.0
    inset = cfg.fiducial_inset_mm
    return {
        "tl": [round(inset + half, 3), round(inset + half, 3), round(s, 3)],
        "tr": [round(cfg.page_width_mm - inset - half, 3), round(inset + half, 3), round(s, 3)],
        "br": [
            round(cfg.page_width_mm - inset - half, 3),
            round(cfg.page_height_mm - inset - half, 3),
            round(s, 3),
        ],
        "bl": [round(inset + half, 3), round(cfg.page_height_mm - inset - half, 3), round(s, 3)],
    }


def generate_collection_sheets(
    chars: Sequence[str] | str = DEFAULT_CORE_CHARSET,
    out_dir: str | Path = "sheets_out",
    config: SheetConfig | None = None,
    *,
    render_previews: bool = True,
) -> SheetManifest:
    """Generate printable A4 collection sheet PDF, PNG previews, and JSON manifest.

    Returns the populated `SheetManifest` (also saved to `<out_dir>/manifest.json`).
    """
    if fitz is None:
        raise RuntimeError("PyMuPDF (`pymupdf`) is required to generate A4 PDF collection sheets.")
    cfg = config or SheetConfig()
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    preview_dir = out_path / "previews"
    if render_previews:
        preview_dir.mkdir(parents=True, exist_ok=True)

    expanded = _expand_char_list(chars, cfg)
    if not expanded:
        raise ValueError("Character list is empty after filtering whitespace.")

    cells_per_page = cfg.rows * cfg.cols
    num_pages = (len(expanded) + cells_per_page - 1) // cells_per_page

    avail_w = cfg.page_width_mm - 2.0 * cfg.margin_x_mm - (cfg.cols - 1) * cfg.cell_gap_x_mm
    avail_h = (
        cfg.page_height_mm
        - cfg.margin_top_mm
        - cfg.margin_bottom_mm
        - (cfg.rows - 1) * cfg.cell_gap_y_mm
    )
    cell_w = avail_w / cfg.cols
    cell_h = avail_h / cfg.rows
    write_h = cell_h - cfg.prompt_h_mm
    if cell_w <= 4.0 or write_h <= 4.0:
        raise ValueError(
            f"Grid too dense for page size: cell_w={cell_w:.2f}mm, write_h={write_h:.2f}mm"
        )

    fiducials = compute_fiducials_mm(cfg)
    border_col = _grid_rgb(cfg.grid_color)
    guide_col = _guide_rgb(cfg.grid_color)

    doc = fitz.open()
    page_specs: list[SheetPageSpec] = []

    for page_idx in range(num_pages):
        page = doc.new_page(
            width=cfg.page_width_mm * MM_TO_PT,
            height=cfg.page_height_mm * MM_TO_PT,
        )

        # 1. Draw 4 corner ArUco-compatible fiducials (IDs 0=TL, 1=TR, 2=BR, 3=BL)
        for marker_id, key in enumerate(("tl", "tr", "br", "bl")):
            cx, cy, sz = fiducials[key]
            _draw_aruco_marker(page, cx, cy, sz, marker_id)

        # 2. Header title & binary page ID bar
        header_rect = fitz.Rect(
            (cfg.fiducial_inset_mm + cfg.fiducial_size_mm + 4.0) * MM_TO_PT,
            8.0 * MM_TO_PT,
            (cfg.page_width_mm - cfg.fiducial_inset_mm - cfg.fiducial_size_mm - 4.0) * MM_TO_PT,
            16.5 * MM_TO_PT,
        )
        header_text = (
            f"HWFont Collection Sheet  |  Writer: {cfg.writer_name}  |  "
            f"Page {page_idx + 1}/{num_pages}  |  Drop-out: {cfg.grid_color.upper()}"
        )
        page.insert_textbox(
            header_rect,
            header_text,
            fontsize=8.5,
            fontname="helv",
            color=border_col,
            align=fitz.TEXT_ALIGN_CENTER,
        )
        _draw_page_id_bars(page, page_idx, cfg.page_width_mm, top_mm=17.5)

        # 3. Draw writing grid cells & prompt chars
        cell_specs: list[SheetCellSpec] = []
        start_i = page_idx * cells_per_page
        end_i = min(len(expanded), start_i + cells_per_page)

        for local_idx in range(end_i - start_i):
            ch, rep_idx = expanded[start_i + local_idx]
            r = local_idx // cfg.cols
            c = local_idx % cfg.cols

            x0_mm = cfg.margin_x_mm + c * (cell_w + cfg.cell_gap_x_mm)
            y0_mm = cfg.margin_top_mm + r * (cell_h + cfg.cell_gap_y_mm)
            x1_mm = x0_mm + cell_w
            y1_mm = y0_mm + cell_h
            wy0_mm = y0_mm + cfg.prompt_h_mm

            full_rect = fitz.Rect(
                x0_mm * MM_TO_PT, y0_mm * MM_TO_PT, x1_mm * MM_TO_PT, y1_mm * MM_TO_PT
            )
            prompt_rect = fitz.Rect(
                x0_mm * MM_TO_PT, y0_mm * MM_TO_PT, x1_mm * MM_TO_PT, wy0_mm * MM_TO_PT
            )
            write_rect = fitz.Rect(
                x0_mm * MM_TO_PT, wy0_mm * MM_TO_PT, x1_mm * MM_TO_PT, y1_mm * MM_TO_PT
            )

            # Prompt band background tint + border
            page.draw_rect(prompt_rect, color=border_col, fill=None, width=0.45)
            page.draw_rect(write_rect, color=border_col, fill=None, width=0.6)

            # Inner cross / Mi guide lines (drop-out color, dashed)
            if cfg.guide_style in ("cross", "mi"):
                mx = (write_rect.x0 + write_rect.x1) / 2.0
                my = (write_rect.y0 + write_rect.y1) / 2.0
                page.draw_line(
                    fitz.Point(mx, write_rect.y0),
                    fitz.Point(mx, write_rect.y1),
                    color=guide_col,
                    width=0.35,
                    dashes="[2 2] 0",
                )
                page.draw_line(
                    fitz.Point(write_rect.x0, my),
                    fitz.Point(write_rect.x1, my),
                    color=guide_col,
                    width=0.35,
                    dashes="[2 2] 0",
                )
            if cfg.guide_style == "mi":
                page.draw_line(
                    fitz.Point(write_rect.x0, write_rect.y0),
                    fitz.Point(write_rect.x1, write_rect.y1),
                    color=guide_col,
                    width=0.3,
                    dashes="[2 3] 0",
                )
                page.draw_line(
                    fitz.Point(write_rect.x1, write_rect.y0),
                    fitz.Point(write_rect.x0, write_rect.y1),
                    color=guide_col,
                    width=0.3,
                    dashes="[2 3] 0",
                )

            # Character prompt label (in drop-out color so scanning filter ignores it)
            prompt_font_pt = max(6.5, min(9.5, cfg.prompt_h_mm * MM_TO_PT * 0.72))
            _insert_prompt_text(page, prompt_rect, ch, prompt_font_pt, border_col)

            cell_id = f"p{page_idx:03d}_r{r:02d}_c{c:02d}"
            cell_specs.append(
                SheetCellSpec(
                    cell_id=cell_id,
                    page=page_idx,
                    row=r,
                    col=c,
                    char=ch,
                    codepoint=ord(ch),
                    repeat_index=rep_idx,
                    write_box_mm=[
                        round(x0_mm, 3),
                        round(wy0_mm, 3),
                        round(x1_mm, 3),
                        round(y1_mm, 3),
                    ],
                    full_box_mm=[
                        round(x0_mm, 3),
                        round(y0_mm, 3),
                        round(x1_mm, 3),
                        round(y1_mm, 3),
                    ],
                )
            )

        # Footer note
        footer_rect = fitz.Rect(
            (cfg.fiducial_inset_mm + cfg.fiducial_size_mm + 4.0) * MM_TO_PT,
            (cfg.page_height_mm - 13.5) * MM_TO_PT,
            (cfg.page_width_mm - cfg.fiducial_inset_mm - cfg.fiducial_size_mm - 4.0) * MM_TO_PT,
            (cfg.page_height_mm - 7.0) * MM_TO_PT,
        )
        page.insert_textbox(
            footer_rect,
            "Write naturally inside each box with a black 0.5mm-0.7mm pen. Scan in color at 300-600 DPI.",
            fontsize=7.2,
            fontname="helv",
            color=border_col,
            align=fitz.TEXT_ALIGN_CENTER,
        )

        preview_rel = ""
        if render_previews:
            pix = page.get_pixmap(dpi=cfg.preview_dpi)
            png_path = preview_dir / f"page_{page_idx:03d}.png"
            pix.save(str(png_path))
            preview_rel = str(png_path.relative_to(out_path))

        page_specs.append(
            SheetPageSpec(
                page_index=page_idx,
                preview_png=preview_rel,
                cells=cell_specs,
            )
        )

    pdf_path = out_path / "collection_sheets.pdf"
    doc.save(str(pdf_path))
    doc.close()

    manifest = SheetManifest(
        schema_version="1.0",
        writer_name=cfg.writer_name,
        page_width_mm=cfg.page_width_mm,
        page_height_mm=cfg.page_height_mm,
        grid_color=cfg.grid_color,
        rows=cfg.rows,
        cols=cfg.cols,
        fiducials_mm=fiducials,
        pdf_path=str(pdf_path.name),
        pages=page_specs,
    )
    manifest.save(out_path / "manifest.json")
    return manifest
