// Document IR contract types.

export interface DocSource {
  type: 'docx' | 'pdf' | 'text';
  filename: string;
  sha256: string;
  parser: string;
}

export interface DocPageInfo {
  page_index: number;
  width_mm: number;
  height_mm: number;
  image?: string | null;
}

export type BlockType =
  | 'heading'
  | 'paragraph'
  | 'list_item'
  | 'formula_block'
  | 'table'
  | 'figure'
  | 'chart'
  | 'caption'
  | 'header'
  | 'footer'
  | 'page_number'
  | 'discarded';

export type DocInline =
  | { t: 'text'; text: string; bold?: boolean; italic?: boolean }
  | { t: 'math'; latex: string }
  | { t: 'break' };

import type { ImageRenderMode, TableBorderStyle } from './layout';

export interface DocBlock {
  block_id: string;
  page_index: number | null;
  type: BlockType;
  reading_order: number;
  level: number;
  bbox_mm: [number, number, number, number] | null;
  inlines?: DocInline[];
  latex?: string | null;
  image_path?: string | null;
  asset_name?: string | null;
  image_render_mode?: ImageRenderMode | null;
  placement?: 'inline' | 'float';
  image_align?: 'left' | 'center' | 'right';
  image_width_mm?: number | null;
  image_height_mm?: number | null;
  float_box_mm?: [number, number, number, number] | null;
  alt_text?: string;
  ocr_source?: string | null;
  table?: {
    rows: number;
    cols: number;
    col_widths_mm?: number[];
    row_heights_mm?: number[];
    cells: Array<{ r: number; c: number; rs: number; cs: number; inlines: DocInline[] }>;
    border_style?: TableBorderStyle | null;
    width_ratio?: number | null;
    align?: 'left' | 'center' | 'right' | null;
  } | null;
  chart?: {
    chart_type: string;
    title?: string;
    image_path?: string | null;
  } | null;
}

export interface DocumentEditPayload {
  doc_id: string;
  sha256: string;
  markdown: string;
  blocks?: DocBlock[];
  block?: DocBlock;
}

export interface MathPreviewResponse {
  ok: boolean;
  latex: string;
  width_mm: number;
  height_mm: number;
  strokes: number[][];
  error: string | null;
}

export interface DocumentDetail {
  doc_id: string;
  is_builtin?: boolean;
  source: DocSource;
  page_count: number;
  pages: DocPageInfo[];
  status: string;
}

export interface ImportPreviewPage {
  page_index: number;
  width_mm: number;
  height_mm: number;
  heading: string;
  snippet: string;
  block_start?: number;
  block_end?: number;
  thumb_url: string;
}

export interface ImportDetectedSection {
  id: string;
  title: string;
  start_page: number;
  end_page: number;
  level: number;
  confidence: number;
}

export interface ImportPreviewManifest {
  preview_id: string;
  filename: string;
  file_type: 'pdf' | 'docx' | 'text';
  page_count: number;
  pages: ImportPreviewPage[];
  detected_sections: ImportDetectedSection[];
}

export interface CommitImportProjectSpec {
  title: string;
  page_indices: number[];
  crop_rects_mm: Record<string, [number, number, number, number]>;
  exclude_header_footer: boolean;
}

export interface CommitImportRequest {
  mode_hint: 'reflow' | 'overlay';
  projects: CommitImportProjectSpec[];
}

export interface CommitImportResponse {
  task_id: string;
  documents: Array<{
    doc_id: string;
    title: string;
    page_count: number;
  }>;
}
