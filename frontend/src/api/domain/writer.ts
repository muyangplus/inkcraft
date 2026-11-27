// Writer / .hwfont metadata and glyph coverage types.

export interface CoverageSummary {
  cjk: number;
  latin: number;
  digit: number;
  punct: number;
  symbol: number;
}

export interface HwFontMeta {
  format_version: string;
  writer_id: string;
  writer_name: string;
  writer_alias: string;
  author: string;
  version: string;
  style_tags: string[];
  units_per_em: number;
  baseline_y: number;
  x_height: number;
  cap_height: number;
  default_advance: number;
  glyph_count: number;
  variant_count: number;
  coverage: CoverageSummary;
  builder: string;
  model: string;
  created_at: string;
  license: string;
  preview_text: string;
  preview_char: string;
  content_sha256: string;
}

export interface WritersListResponse {
  active_writer_id: string | null;
  writers: HwFontMeta[];
}

export interface GlyphVariantInfo {
  variant_id: number;
  variant_no: number;
  source: 'scan' | 'generated' | 'augmented' | 'manual' | 'builtin';
  quality: number;
  weight: number;
  advance: number;
  bbox: [number, number, number, number];
  strokes: number[][]; // each stroke is flat [x0, y0, x1, y1, ...] in 0..1000
}

export interface GlyphVariantsResponse {
  char: string;
  codepoint: number;
  variants: GlyphVariantInfo[];
}

export interface MissingCharInfo {
  char: string;
  count: number;
  fallback_available: boolean;
}

export interface WriterCoverageResponse {
  total_chars: number;
  unique_chars: number;
  covered: number;
  missing: MissingCharInfo[];
}
