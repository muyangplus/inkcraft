"""Contract v1 Pydantic schemas shared across REST API, WebSocket, Layout, and GRBL modules."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from hwfont_sdk.schema import HwFontMeta


# ---------------------------------------------------------------------------
# State Enums (§12.1)
# ---------------------------------------------------------------------------

class MachineState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    IDLE = "IDLE"
    JOGGING = "JOGGING"
    FRAMING = "FRAMING"
    RUNNING = "RUNNING"
    HOLDING = "HOLDING"
    PAUSED = "PAUSED"
    PEN_CHANGE = "PEN_CHANGE"
    PAPER_CHANGE = "PAPER_CHANGE"
    ALARM = "ALARM"
    ESTOPPED = "ESTOPPED"
    ERROR = "ERROR"


GrblState = Literal[
    "Idle", "Run", "Hold:0", "Hold:1", "Jog", "Alarm", "Door", "Check", "Home", "Sleep"
]


class JobState(StrEnum):
    QUEUED = "QUEUED"
    PREPARING = "PREPARING"
    STREAMING = "STREAMING"
    PAUSED = "PAUSED"
    PEN_CHANGE = "PEN_CHANGE"
    WAIT_PAPER = "WAIT_PAPER"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    FAILED = "FAILED"


TaskKind = Literal["parse", "compose", "font_import"]
TaskState = Literal["pending", "running", "done", "failed"]
StrokeKind = Literal["text", "formula", "table", "chart", "rule", "frame"]
ImageRenderMode = Literal["major_outline", "outline", "hatch", "crosshatch", "sketch", "skip"]
TableBorderStyle = Literal["grid", "compact", "three_line", "horizontal", "dashed", "minimal", "none"]


# ---------------------------------------------------------------------------
# Basic Geometry Helpers
# ---------------------------------------------------------------------------

class Vec2(BaseModel):
    x: float = 0.0
    y: float = 0.0


class Vec3(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


# ---------------------------------------------------------------------------
# LayoutConfig (§12.5)
# ---------------------------------------------------------------------------

class MarginsMM(BaseModel):
    top: float = Field(default=22.0, ge=0.0)
    right: float = Field(default=20.0, ge=0.0)
    bottom: float = Field(default=22.0, ge=0.0)
    left: float = Field(default=20.0, ge=0.0)


class PageConfig(BaseModel):
    size: Literal["A4", "A5", "B5", "Letter", "custom"] = "A4"
    width_mm: float = Field(default=210.0, ge=20.0, le=1000.0)
    height_mm: float = Field(default=297.0, ge=20.0, le=1000.0)
    orientation: Literal["portrait", "landscape"] = "portrait"
    margins_mm: MarginsMM = Field(default_factory=MarginsMM)
    underlay_fit: Literal["fill", "contain", "custom"] = "fill"
    underlay_width_mm: float | None = Field(default=None, ge=20.0, le=1000.0)
    underlay_height_mm: float | None = Field(default=None, ge=20.0, le=1000.0)
    underlay_offset_x_mm: float = Field(default=0.0, ge=-500.0, le=500.0)
    underlay_offset_y_mm: float = Field(default=0.0, ge=-500.0, le=500.0)


class RuledConfig(BaseModel):
    style: Literal["none", "lines", "grid"] = "none"
    pitch_mm: float = Field(default=9.0, ge=5.0, le=25.0)
    draw: bool = False


class TextConfig(BaseModel):
    font_size_mm: float = Field(default=6.0, ge=1.5, le=40.0)
    char_scale_x: float = Field(default=1.0, ge=0.5, le=2.0)
    char_scale_y: float = Field(default=1.0, ge=0.5, le=2.0)
    line_spacing: float = Field(default=1.5, ge=-2.0, le=8.0)
    line_spacing_mm: float | None = Field(default=None, ge=-20.0, le=80.0)
    char_spacing: float = Field(default=0.05, ge=-0.3, le=1.5)
    paragraph_spacing_mm: float = Field(default=3.0, ge=-20.0, le=80.0)
    first_line_indent_chars: float = Field(default=2.0, ge=0.0, le=8.0)
    align: Literal["left", "justify", "center", "right"] = "justify"
    ruled: RuledConfig = Field(default_factory=RuledConfig)


class PerturbConfig(BaseModel):
    seed: int = Field(default=42, ge=0, le=4294967295)
    neatness: float = Field(default=0.72, ge=0.0, le=1.0)
    scale_jitter: float = Field(default=0.08, ge=0.0, le=0.3)
    slant_deg: float = Field(default=2.5, ge=0.0, le=8.0)
    baseline_wave_amp_mm: float = Field(default=0.45, ge=0.0, le=1.5)
    baseline_wave_period_mm: float = Field(default=75.0, ge=20.0, le=200.0)
    spacing_jitter: float = Field(default=0.08, ge=0.0, le=0.3)
    rotation_jitter_deg: float = Field(default=1.2, ge=0.0, le=5.0)
    variant_strategy: Literal["random_no_repeat", "round_robin", "lru"] = "random_no_repeat"
    variant_no_repeat_window: int = Field(default=3, ge=1, le=16)


class FormulaConfig(BaseModel):
    scale: float = Field(default=0.95, ge=0.6, le=1.2)
    line_spacing_mm: float = Field(default=-0.8, ge=-8.0, le=8.0)
    inner_row_spacing: float = Field(default=-0.04, ge=-0.35, le=0.50)
    stroke_style: Literal["handwrite"] = "handwrite"


class ChartConfig(BaseModel):
    image_render_mode: ImageRenderMode = "outline"
    contour_threshold: int = Field(default=185, ge=60, le=240)
    hatch_spacing_mm: float = Field(default=1.8, ge=0.8, le=5.0)
    hatch_angle_deg: float = Field(default=45.0, ge=-90.0, le=90.0)
    hatch_style: Literal["parallel", "cross", "zigzag"] = "parallel"
    hand_jitter_mm: float = Field(default=0.25, ge=0.0, le=1.0)
    keep_caption_with_figure: bool = True


class TableConfig(BaseModel):
    draw_borders: bool = True
    border_style: TableBorderStyle = "grid"
    width_ratio: float = Field(default=1.0, ge=0.4, le=1.0)
    cell_padding_mm: float = Field(default=1.4, ge=0.3, le=5.0)
    row_height_scale: float = Field(default=1.0, ge=0.55, le=1.6)
    font_scale: float = Field(default=0.86, ge=0.55, le=1.15)
    align: Literal["left", "center", "right"] = "center"
    hand_jitter_mm: float = Field(default=0.20, ge=0.0, le=1.0)
    keep_caption_with_table: bool = True


class OverlayBlockOverride(BaseModel):
    enabled: bool = True
    nudge_mm: Vec2 = Field(default_factory=Vec2)


class OverlayConfig(BaseModel):
    offset_mm: Vec2 = Field(default_factory=Vec2)
    scale: float = Field(default=1.0, ge=0.5, le=1.5)
    rotation_deg: float = Field(default=0.0, ge=-10.0, le=10.0)
    underlay_opacity: float = Field(default=0.35, ge=0.0, le=1.0)
    blocks: dict[str, OverlayBlockOverride] = Field(default_factory=dict)


class OptimizeConfig(BaseModel):
    travel: Literal["greedy_2opt", "none"] = "greedy_2opt"
    simplify_tol_mm: float = Field(default=0.08, ge=0.02, le=0.5)
    join_tol_mm: float = Field(default=0.15, ge=0.0, le=1.0)


class FallbackConfig(BaseModel):
    policy: Literal["blank", "builtin_single_line", "skip", "box"] = "blank"


class WritingRegion(BaseModel):
    region_id: str
    name: str = "书写区域"
    role: Literal["field", "body"] = "field"
    field_key: str = ""
    text: str = ""
    page_scope: str = "1"  # "1", "2+", "all", "odd", "even", "2-4", "1,3"
    order: int = 0
    x_mm: float = Field(default=20.0, ge=0.0, le=1000.0)
    y_mm: float = Field(default=20.0, ge=0.0, le=1000.0)
    width_mm: float = Field(default=80.0, ge=4.0, le=1000.0)
    height_mm: float = Field(default=12.0, ge=3.0, le=1000.0)
    font_size_mm: float | None = Field(default=None, ge=1.5, le=40.0)
    line_spacing: float | None = Field(default=None, ge=-2.0, le=8.0)
    line_spacing_mm: float | None = Field(default=None, ge=-20.0, le=80.0)
    paragraph_spacing_mm: float | None = Field(default=None, ge=-20.0, le=80.0)
    char_spacing: float | None = Field(default=None, ge=-0.3, le=1.5)
    align: Literal["left", "center", "right", "justify"] = "left"
    valign: Literal["top", "middle", "bottom"] = "middle"
    single_line: bool = True
    auto_fit: bool = True
    writer_id: str | None = None
    neatness: float | None = Field(default=None, ge=0.0, le=1.0)
    enabled: bool = True


class PageRuleOverride(BaseModel):
    label: str = ""
    background_id: str | None = None
    background_opacity: float = Field(default=0.72, ge=0.0, le=1.0)
    writer_id: str | None = None
    margins_mm: MarginsMM | None = None
    font_size_mm: float | None = Field(default=None, ge=1.5, le=40.0)
    line_spacing: float | None = Field(default=None, ge=-2.0, le=8.0)
    line_spacing_mm: float | None = Field(default=None, ge=-20.0, le=80.0)
    paragraph_spacing_mm: float | None = Field(default=None, ge=-20.0, le=80.0)
    ruled: RuledConfig | None = None


class PageRulesConfig(BaseModel):
    strategy: Literal["uniform", "first_and_rest", "odd_even", "custom"] = "uniform"
    uniform: PageRuleOverride = Field(default_factory=lambda: PageRuleOverride(label="统一底稿"))
    first_page: PageRuleOverride = Field(default_factory=lambda: PageRuleOverride(label="首页方案 A"))
    rest_pages: PageRuleOverride = Field(default_factory=lambda: PageRuleOverride(label="后续页方案 B"))
    odd_pages: PageRuleOverride = Field(default_factory=lambda: PageRuleOverride(label="奇数页方案 A"))
    even_pages: PageRuleOverride = Field(default_factory=lambda: PageRuleOverride(label="偶数页方案 B"))
    # 1-based page selectors: "1", "2-4", "2+", "default"
    custom_pages: dict[str, PageRuleOverride] = Field(default_factory=dict)


class BackgroundTemplate(BaseModel):
    background_id: str
    name: str
    kind: Literal["builtin", "uploaded"] = "uploaded"
    description: str = ""
    width_mm: float = 210.0
    height_mm: float = 297.0
    image_url: str
    recommended_margins_mm: MarginsMM = Field(default_factory=MarginsMM)
    recommended_ruled_pitch_mm: float | None = None
    created_at: str = ""


class LayoutConfig(BaseModel):
    preset_id: str | None = None
    mode: Literal["reflow", "overlay"] = "reflow"
    page: PageConfig = Field(default_factory=PageConfig)
    text: TextConfig = Field(default_factory=TextConfig)
    perturb: PerturbConfig = Field(default_factory=PerturbConfig)
    formula: FormulaConfig = Field(default_factory=FormulaConfig)
    chart: ChartConfig = Field(default_factory=ChartConfig)
    table: TableConfig = Field(default_factory=TableConfig)
    overlay: OverlayConfig = Field(default_factory=OverlayConfig)
    optimize: OptimizeConfig = Field(default_factory=OptimizeConfig)
    fallback: FallbackConfig = Field(default_factory=FallbackConfig)
    page_rules: PageRulesConfig = Field(default_factory=PageRulesConfig)
    regions: list[WritingRegion] = Field(default_factory=list)


class LayoutPreset(BaseModel):
    preset_id: str
    name: str
    category: Literal["homework", "notes", "letter", "overlay", "draft"] = "homework"
    description: str
    tags: list[str] = Field(default_factory=list)
    config: LayoutConfig


# ---------------------------------------------------------------------------
# MachineProfile (§12.6)
# ---------------------------------------------------------------------------

class PenConfig(BaseModel):
    mode: Literal["servo", "z"] = "servo"
    servo_up: str = "M5"
    servo_down: str = "M3 S90"
    dwell_ms: int = Field(default=120, ge=0, le=2000)
    z_up_mm: float = 4.0
    z_down_mm: float = 0.0
    z_feed: float = 1200.0


class MachineProfile(BaseModel):
    profile_id: str = "corexy_servo_a4"
    name: str = "CoreXY A4 舵机写字机 (GRBL 1.1)"
    baud: int = 115200
    pen: PenConfig = Field(default_factory=PenConfig)
    workspace_mm: Vec2 = Field(default_factory=lambda: Vec2(x=220.0, y=310.0))
    pen_change_pos_mm: Vec2 = Field(default_factory=lambda: Vec2(x=10.0, y=10.0))
    paper_change_pos_mm: Vec2 = Field(default_factory=lambda: Vec2(x=0.0, y=0.0))
    origin: Literal["top_left", "bottom_left"] = "top_left"
    invert_x: bool = False
    invert_y: bool = False
    feed_draw: float = 2400.0
    feed_travel: float = 5000.0
    jog_feed: float = 3000.0
    status_hz: float = 10.0
    rx_buffer: int = 128


# ---------------------------------------------------------------------------
# Paths / Layout Output (§12.3)
# ---------------------------------------------------------------------------

class StrokeItem(BaseModel):
    id: int
    block_id: str = ""
    kind: StrokeKind = "text"
    reversible: bool = False
    pts: list[float]  # flat [x0, y0, x1, y1, ...] in mm


class PageStats(BaseModel):
    draw_mm: float = 0.0
    travel_mm: float = 0.0
    stroke_count: int = 0
    est_s: float = 0.0


class FallbackGlyphInfo(BaseModel):
    char: str
    count: int


class MissingGlyphBox(BaseModel):
    id: str = ""
    char: str
    unicode_hex: str = ""
    page_index: int = 0
    block_id: str = ""
    bbox_mm: list[float]  # [x0, y0, x1, y1] in page mm
    context: str = ""
    source: Literal["text", "formula", "table", "region", "chart"] = "text"
    policy: Literal["blank", "builtin_single_line", "skip", "box"] = "blank"


class PlacedBlockBox(BaseModel):
    block_id: str
    block_type: str
    page_index: int
    bbox_mm: list[float]  # [x0, y0, x1, y1]
    label: str = ""
    latex: str | None = None
    inline_index: int | None = None
    placement: Literal["inline", "float"] | None = None
    render_mode: str | None = None


class ComposedPage(BaseModel):
    page_index: int
    width_mm: float
    height_mm: float
    bbox: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    strokes: list[StrokeItem] = Field(default_factory=list)
    stats: PageStats = Field(default_factory=PageStats)
    fallback_glyphs: list[FallbackGlyphInfo] = Field(default_factory=list)
    missing_glyphs: list[MissingGlyphBox] = Field(default_factory=list)
    applied_rule_label: str = ""
    background_id: str | None = None
    background_opacity: float = 0.72
    writer_id: str | None = None
    placed_blocks: list[PlacedBlockBox] = Field(default_factory=list)


class LayoutPageSummary(BaseModel):
    page_index: int
    width_mm: float
    height_mm: float
    bbox: list[float]
    stats: PageStats
    fallback_glyphs: list[FallbackGlyphInfo] = Field(default_factory=list)
    missing_glyphs: list[MissingGlyphBox] = Field(default_factory=list)
    applied_rule_label: str = ""
    background_id: str | None = None
    background_opacity: float = 0.72
    writer_id: str | None = None
    placed_blocks: list[PlacedBlockBox] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# REST Request / Response Payloads (§12.2)
# ---------------------------------------------------------------------------

class ActiveWriterRequest(BaseModel):
    writer_id: str


class CreateTextDocumentRequest(BaseModel):
    title: str = "手写文稿"
    text: str


class RenameDocumentRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=200)


class CommitImportProjectSpec(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    page_indices: list[int] = Field(min_length=1)
    crop_rects_mm: dict[str, list[float]] = Field(default_factory=dict)
    exclude_header_footer: bool = False


class CommitImportRequest(BaseModel):
    mode_hint: Literal["reflow", "overlay"] = "reflow"
    projects: list[CommitImportProjectSpec] = Field(min_length=1, max_length=24)


class UpdateDocumentMarkdownRequest(BaseModel):
    markdown: str


class UpdateDocumentBlocksRequest(BaseModel):
    blocks: list[dict[str, Any]]


class PatchDocumentBlockRequest(BaseModel):
    type: str | None = None
    level: int | None = Field(default=None, ge=1, le=6)
    page_index: int | None = Field(default=None, ge=0)
    inlines: list[dict[str, Any]] | None = None
    latex: str | None = None
    table: dict[str, Any] | None = None
    table_border_style: Literal["inherit", "grid", "compact", "three_line", "horizontal", "dashed", "minimal", "none"] | None = None
    table_width_ratio: float | None = Field(default=None, ge=0.4, le=1.0)
    table_align: Literal["left", "center", "right"] | None = None
    alt_text: str | None = None
    image_render_mode: Literal["inherit", "major_outline", "outline", "hatch", "crosshatch", "sketch", "skip"] | None = None
    placement: Literal["inline", "float"] | None = None
    image_align: Literal["left", "center", "right"] | None = None
    image_width_mm: float | None = Field(default=None, ge=5.0, le=500.0)
    image_height_mm: float | None = Field(default=None, ge=5.0, le=500.0)
    float_box_mm: list[float] | None = None


class ApplyImageStyleRequest(BaseModel):
    image_render_mode: Literal["inherit", "major_outline", "outline", "hatch", "crosshatch", "sketch", "skip"]


class MathPreviewRequest(BaseModel):
    latex: str
    writer_id: str | None = None
    font_size_mm: float = Field(default=7.5, ge=2.0, le=30.0)
    formula_scale: float = Field(default=0.95, ge=0.6, le=1.4)
    inner_row_spacing: float = Field(default=-0.04, ge=-0.35, le=0.5)
    display: bool = True


class CreateLayoutRequest(BaseModel):
    doc_id: str | None = None
    writer_id: str | None = None
    config: LayoutConfig = Field(default_factory=LayoutConfig)


class MachineConnectRequest(BaseModel):
    port: str = "MOCK"
    baud: int = 115200
    profile_id: str = "corexy_servo_a4"
    mock: bool = True


class JogRequest(BaseModel):
    dx: float = 0.0
    dy: float = 0.0
    feed: float = 3000.0


class ZeroRequest(BaseModel):
    axes: list[Literal["X", "Y", "Z"]] = Field(default_factory=lambda: ["X", "Y"])


class PenRequest(BaseModel):
    state: Literal["up", "down"]
    override_cmd: str | None = Field(default=None, max_length=64)
    override_z_mm: float | None = Field(default=None, ge=-30.0, le=50.0)
    override_z_feed: float | None = Field(default=None, ge=60.0, le=10000.0)


class MoveToRequest(BaseModel):
    x: float = 0.0
    y: float = 0.0
    feed: float | None = Field(default=None, ge=60.0, le=20000.0)
    pen_up: bool = True


class MoveToStartRequest(BaseModel):
    layout_id: str
    page_index: int = Field(default=0, ge=0)


class RawCommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=120)


class FrameCheckRequest(BaseModel):
    layout_id: str
    page_index: int = 0


class CreateJobRequest(BaseModel):
    layout_id: str
    page_indices: list[int] | None = None
    start_page_index: int = 0


class PaperReadyRequest(BaseModel):
    page_index: int


class WritersListResponse(BaseModel):
    active_writer_id: str | None
    writers: list[HwFontMeta]


class WsEnvelope(BaseModel):
    v: int = 1
    type: str
    seq: int
    ts: int
    data: dict[str, Any]
