"""Unified Document Intermediate Representation (DocIR v1)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DocSource(BaseModel):
    type: Literal["docx", "pdf", "text"]
    filename: str
    sha256: str
    parser: str = "builtin"


class DocPageInfo(BaseModel):
    page_index: int = Field(ge=0)
    width_mm: float = 210.0
    height_mm: float = 297.0
    image: str | None = None


class TextInline(BaseModel):
    t: Literal["text"] = "text"
    text: str
    bold: bool = False
    italic: bool = False


class MathInline(BaseModel):
    t: Literal["math"] = "math"
    latex: str


class BreakInline(BaseModel):
    t: Literal["break"] = "break"


DocInline = TextInline | MathInline | BreakInline


class DocLine(BaseModel):
    page_index: int | None = None
    bbox_mm: list[float] | None = None  # [x0, y0, x1, y1]
    inlines: list[DocInline] = Field(default_factory=list)


class TableCell(BaseModel):
    r: int
    c: int
    rs: int = 1
    cs: int = 1
    bbox_mm: list[float] | None = None
    inlines: list[DocInline] = Field(default_factory=list)


class TableData(BaseModel):
    rows: int
    cols: int
    col_widths_mm: list[float] = Field(default_factory=list)
    row_heights_mm: list[float] = Field(default_factory=list)
    cells: list[TableCell] = Field(default_factory=list)
    border_style: Literal["grid", "compact", "three_line", "horizontal", "dashed", "minimal", "none"] | None = None
    width_ratio: float | None = None
    align: Literal["left", "center", "right"] | None = None


class ChartSeries(BaseModel):
    name: str = ""
    values: list[float] = Field(default_factory=list)
    x_values: list[float] | None = None


class ChartData(BaseModel):
    chart_type: Literal["bar", "line", "pie", "scatter", "vector", "raster"] = "bar"
    title: str = ""
    x_label: str = ""
    y_label: str = ""
    categories: list[str] = Field(default_factory=list)
    series: list[ChartSeries] = Field(default_factory=list)
    # Optional extracted vector polylines (page-local or 0..1 normalized coords)
    vector_polylines: list[list[tuple[float, float]]] = Field(default_factory=list)
    vector_polygons: list[list[tuple[float, float]]] = Field(default_factory=list)
    # Optional path to raster image for fallback vectorization
    image_path: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


BlockType = Literal[
    "heading",
    "paragraph",
    "list_item",
    "formula_block",
    "table",
    "figure",
    "chart",
    "caption",
    "header",
    "footer",
    "page_number",
    "discarded",
]


class DocBlock(BaseModel):
    block_id: str
    page_index: int | None = 0
    type: BlockType = "paragraph"
    reading_order: int = 0
    level: int = 1  # heading level 1..6 or list nesting
    bbox_mm: list[float] | None = None  # [x0, y0, x1, y1]
    lines: list[DocLine] = Field(default_factory=list)
    inlines: list[DocInline] = Field(default_factory=list)
    latex: str | None = None
    table: TableData | None = None
    chart: ChartData | None = None
    image_path: str | None = None
    asset_name: str | None = None
    image_render_mode: Literal["inherit", "major_outline", "outline", "hatch", "crosshatch", "sketch", "skip"] = "inherit"
    placement: Literal["inline", "float"] = "inline"
    image_align: Literal["left", "center", "right"] = "center"
    image_width_mm: float | None = None
    image_height_mm: float | None = None
    float_box_mm: list[float] | None = None
    alt_text: str = ""
    ocr_source: str | None = None

    def plain_text(self) -> str:
        if self.latex:
            return self.latex
        parts: list[str] = []
        for inl in self.inlines:
            if isinstance(inl, TextInline):
                parts.append(inl.text)
            elif isinstance(inl, MathInline):
                parts.append(inl.latex)
            else:
                parts.append("\n")
        if self.table:
            for cell in self.table.cells:
                for inl in cell.inlines:
                    if isinstance(inl, TextInline):
                        parts.append(inl.text)
                    elif isinstance(inl, MathInline):
                        parts.append(inl.latex)
        return "".join(parts)


class DocIR(BaseModel):
    doc_id: str
    source: DocSource
    pages: list[DocPageInfo] = Field(default_factory=list)
    blocks: list[DocBlock] = Field(default_factory=list)
