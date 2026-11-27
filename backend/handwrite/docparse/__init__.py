"""Document parsing layer (DOCX, PDF, Plain Text -> DocIR v1)."""

from handwrite.docparse.chart_extract import (
    detect_chart_regions_on_page,
    extract_pdf_vector_drawings,
    vectorize_raster_image,
)
from handwrite.docparse.docir import (
    BlockType,
    BreakInline,
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
from handwrite.docparse.docx_parser import omml_to_latex, parse_docx, parse_drawingml_chart_xml
from handwrite.docparse.mineru_worker import (
    MinerUExecutionError,
    MinerUResult,
    MinerUUnavailableError,
    is_mineru_available,
    run_mineru_pipeline,
)
from handwrite.docparse.pdf_parser import parse_pdf, split_inline_math
from handwrite.docparse.service import build_demo_docir, parse_document, parse_plain_text

__all__ = [
    "BlockType",
    "BreakInline",
    "ChartData",
    "ChartSeries",
    "DocBlock",
    "DocIR",
    "DocInline",
    "DocLine",
    "DocPageInfo",
    "DocSource",
    "MathInline",
    "MinerUExecutionError",
    "MinerUResult",
    "MinerUUnavailableError",
    "TableCell",
    "TableData",
    "TextInline",
    "build_demo_docir",
    "detect_chart_regions_on_page",
    "extract_pdf_vector_drawings",
    "is_mineru_available",
    "omml_to_latex",
    "parse_document",
    "parse_docx",
    "parse_drawingml_chart_xml",
    "parse_pdf",
    "parse_plain_text",
    "run_mineru_pipeline",
    "split_inline_math",
    "vectorize_raster_image",
]
