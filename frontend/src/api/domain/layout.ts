// Backgrounds, per-page rules, layout configuration, writing regions, and composed path types.

import type { StrokeKind, Vec2 } from './common';

export interface MarginsMM {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

export interface RuledConfig {
  style: 'none' | 'lines' | 'grid';
  pitch_mm: number;
  draw: boolean;
}

export type ImageRenderMode =
  | 'inherit'
  | 'major_outline'
  | 'outline'
  | 'hatch'
  | 'crosshatch'
  | 'sketch'
  | 'skip';

export type TableBorderStyle =
  | 'grid'
  | 'compact'
  | 'three_line'
  | 'horizontal'
  | 'dashed'
  | 'minimal'
  | 'none';

export interface PlacedBlockBox {
  block_id: string;
  block_type: string;
  page_index: number;
  bbox_mm: [number, number, number, number];
  label: string;
  latex?: string | null;
  inline_index?: number | null;
  placement?: 'inline' | 'float' | null;
  render_mode?: string | null;
}

export interface PageRuleOverride {
  label: string;
  background_id: string | null;
  background_opacity: number;
  writer_id: string | null;
  margins_mm: MarginsMM | null;
  font_size_mm: number | null;
  line_spacing: number | null;
  line_spacing_mm: number | null;
  paragraph_spacing_mm: number | null;
  ruled: RuledConfig | null;
}

export type PageRuleStrategy = 'uniform' | 'first_and_rest' | 'odd_even' | 'custom';

export interface PageRulesConfig {
  strategy: PageRuleStrategy;
  uniform: PageRuleOverride;
  first_page: PageRuleOverride;
  rest_pages: PageRuleOverride;
  odd_pages: PageRuleOverride;
  even_pages: PageRuleOverride;
  /** 1-based page selectors: "1", "2", "2-4", "3+", "default" */
  custom_pages: Record<string, PageRuleOverride>;
}

export interface BackgroundTemplate {
  background_id: string;
  name: string;
  kind: 'builtin' | 'uploaded';
  description: string;
  width_mm: number;
  height_mm: number;
  image_url: string;
  recommended_margins_mm: MarginsMM;
  recommended_ruled_pitch_mm: number | null;
  created_at: string;
}

export type PresetCategory = 'homework' | 'notes' | 'letter' | 'overlay' | 'draft';

export interface LayoutPreset {
  preset_id: string;
  name: string;
  category: PresetCategory;
  description: string;
  tags: string[];
  config: LayoutConfig;
}

export interface CustomUserPreset {
  preset_id: string;
  name: string;
  description: string;
  created_at: string;
  config: LayoutConfig;
}

export interface OverlayBlockOverride {
  enabled: boolean;
  nudge_mm: Vec2;
}

export interface LayoutConfig {
  preset_id?: string | null;
  mode: 'reflow' | 'overlay';
  page: {
    size: 'A4' | 'A5' | 'B5' | 'Letter' | 'custom';
    width_mm: number;
    height_mm: number;
    orientation: 'portrait' | 'landscape';
    margins_mm: MarginsMM;
    underlay_fit: 'fill' | 'contain' | 'custom';
    underlay_width_mm: number | null;
    underlay_height_mm: number | null;
    underlay_offset_x_mm: number;
    underlay_offset_y_mm: number;
  };
  text: {
    font_size_mm: number;
    char_scale_x: number;
    char_scale_y: number;
    line_spacing: number;
    line_spacing_mm: number | null;
    char_spacing: number;
    paragraph_spacing_mm: number;
    first_line_indent_chars: number;
    align: 'left' | 'justify' | 'center' | 'right';
    ruled: RuledConfig;
  };
  perturb: {
    seed: number;
    neatness: number;
    scale_jitter: number;
    slant_deg: number;
    baseline_wave_amp_mm: number;
    baseline_wave_period_mm: number;
    spacing_jitter: number;
    rotation_jitter_deg: number;
    variant_strategy: 'random_no_repeat' | 'round_robin' | 'lru';
    variant_no_repeat_window: number;
  };
  formula: {
    scale: number;
    line_spacing_mm: number;
    inner_row_spacing: number;
    stroke_style: 'handwrite';
  };
  chart: {
    image_render_mode: ImageRenderMode;
    contour_threshold: number;
    hatch_spacing_mm: number;
    hatch_angle_deg: number;
    hatch_style: 'parallel' | 'cross' | 'zigzag';
    hand_jitter_mm: number;
    keep_caption_with_figure: boolean;
  };
  table: {
    draw_borders: boolean;
    border_style: TableBorderStyle;
    width_ratio: number;
    cell_padding_mm: number;
    row_height_scale: number;
    font_scale: number;
    align: 'left' | 'center' | 'right';
    hand_jitter_mm: number;
    keep_caption_with_table: boolean;
  };
  overlay: {
    offset_mm: Vec2;
    scale: number;
    rotation_deg: number;
    underlay_opacity: number;
    blocks: Record<string, OverlayBlockOverride>;
  };
  optimize: {
    travel: 'greedy_2opt' | 'none';
    simplify_tol_mm: number;
    join_tol_mm: number;
  };
  fallback: {
    policy: 'blank' | 'builtin_single_line' | 'skip' | 'box';
  };
  page_rules: PageRulesConfig;
  regions: WritingRegion[];
  /** 多字体按概率混写：每个字按权重随机选择书写者（奎享「字体混合」）。 */
  writer_mix: Array<{ writer_id: string; weight: number }>;
}

export interface WritingRegion {
  region_id: string;
  name: string;
  role: 'field' | 'body';
  field_key: string;
  text: string;
  page_scope: string; // "1", "2+", "all", "odd", "even", "2-4", "1,3"
  order: number;
  x_mm: number;
  y_mm: number;
  width_mm: number;
  height_mm: number;
  font_size_mm: number | null;
  line_spacing: number | null;
  line_spacing_mm: number | null;
  paragraph_spacing_mm: number | null;
  char_spacing: number | null;
  align: 'left' | 'center' | 'right' | 'justify';
  valign: 'top' | 'middle' | 'bottom';
  single_line: boolean;
  auto_fit: boolean;
  writer_id: string | null;
  neatness: number | null;
  enabled: boolean;
}

export interface PageStats {
  draw_mm: number;
  travel_mm: number;
  stroke_count: number;
  est_s: number;
}

export interface FallbackGlyphInfo {
  char: string;
  count: number;
}

export interface MissingGlyphBox {
  id: string;
  char: string;
  unicode_hex: string;
  page_index: number;
  block_id: string;
  bbox_mm: [number, number, number, number];
  context: string;
  source: 'text' | 'formula' | 'table' | 'region' | 'chart';
  policy: 'blank' | 'builtin_single_line' | 'skip' | 'box';
}

export interface LayoutPageSummary {
  page_index: number;
  width_mm: number;
  height_mm: number;
  bbox: [number, number, number, number];
  stats: PageStats;
  fallback_glyphs: FallbackGlyphInfo[];
  missing_glyphs?: MissingGlyphBox[];
  applied_rule_label?: string;
  background_id?: string | null;
  background_opacity?: number;
  writer_id?: string | null;
  placed_blocks?: PlacedBlockBox[];
}

export interface LayoutDetail {
  layout_id: string;
  writer_id: string;
  doc_id: string;
  page_count: number;
  config: LayoutConfig;
  pages: LayoutPageSummary[];
}

export interface StrokeItem {
  id: number;
  block_id: string;
  kind: StrokeKind;
  reversible?: boolean;
  pts: number[];
}

export interface PagePathsJson {
  layout_id: string;
  page_index: number;
  width_mm: number;
  height_mm: number;
  bbox: [number, number, number, number];
  strokes: StrokeItem[];
  stats: PageStats;
}
