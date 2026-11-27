import type { StateCreator } from 'zustand';
import type {
  BackgroundTemplate,
  CommitImportRequest,
  CustomUserPreset,
  DocBlock,
  DocumentDetail,
  ImageRenderMode,
  ImportPreviewManifest,
  LayoutConfig,
  LayoutDetail,
  LayoutPreset,
  MarginsMM,
  MissingGlyphBox,
  PageRulesConfig,
  TaskProgressData,
  WritingRegion,
} from '../../api/types';
import type { DecodedPagePaths } from '../../canvas/f32PathDecoder';

export interface DocumentSlice {
  documents: DocumentDetail[];
  currentDoc: DocumentDetail | null;
  blocks: DocBlock[];
  markdown: string;
  savingDoc: boolean;
  parseTask: TaskProgressData | null;
  importPreview: ImportPreviewManifest | null;
  importPreviewLoading: boolean;
  importPreviewCommitting: boolean;

  bootstrap: () => Promise<void>;
  selectDocument: (docId: string) => Promise<void>;
  clearDocument: () => void;
  uploadDocument: (file: File) => Promise<void>;
  openImportPreview: (file: File) => Promise<void>;
  commitImportPreview: (payload: CommitImportRequest) => Promise<boolean>;
  cancelImportPreview: () => Promise<void>;
  renameDocument: (docId: string, filename: string) => Promise<boolean>;
  deleteDocument: (docId: string) => Promise<boolean>;
  createTextDocument: (title: string, text: string) => Promise<void>;
  handleTaskProgress: (task: TaskProgressData) => void;

  saveDocumentMarkdown: (markdown: string) => Promise<boolean>;
  saveDocumentBlocks: (blocks: DocBlock[]) => Promise<boolean>;
  patchDocumentBlock: (blockId: string, patch: Record<string, unknown>) => Promise<boolean>;
  applyGlobalImageStyle: (mode: ImageRenderMode) => Promise<void>;
  reRecognizeFormulaBlock: (blockId: string) => Promise<DocBlock | null>;
  uploadDocumentAsset: (file: File) => Promise<{
    asset_name: string;
    url: string;
    width_mm: number;
    height_mm: number;
  } | null>;
}

export interface LayoutConfigSlice {
  config: LayoutConfig;
  presets: LayoutPreset[];
  customPresets: CustomUserPreset[];
  backgrounds: BackgroundTemplate[];
  uploadingBackground: boolean;

  fetchPresets: () => Promise<void>;
  fetchBackgrounds: () => Promise<void>;
  uploadBackground: (
    file: File,
    opts?: {
      name?: string;
      width_mm?: number;
      height_mm?: number;
      margins?: MarginsMM;
    },
  ) => Promise<BackgroundTemplate | null>;
  deleteBackground: (backgroundId: string) => Promise<void>;

  applyPreset: (presetConfig: LayoutConfig, presetLabel?: string) => void;
  saveCustomPreset: (name: string, description?: string) => void;
  deleteCustomPreset: (presetId: string) => void;

  updateConfig: (updater: (prev: LayoutConfig) => LayoutConfig, immediate?: boolean) => void;
  updatePageRules: (updater: (prev: PageRulesConfig) => PageRulesConfig, immediate?: boolean) => void;
  assignBackgroundToSlot: (bg: BackgroundTemplate, slot: 'uniform' | 'a' | 'b') => void;
  clearPageRuleOverrides: (pageIndex: number) => void;

  addRegion: (partial?: Partial<WritingRegion>) => WritingRegion;
  updateRegion: (regionId: string, patch: Partial<WritingRegion>, immediate?: boolean) => void;
  removeRegion: (regionId: string) => void;
  duplicateRegion: (regionId: string) => void;
  clearRegions: () => void;
  resetToBlankA4: () => void;
  setMode: (mode: 'reflow' | 'overlay') => void;
  toggleOverlayBlock: (blockId: string, enabled: boolean) => void;
  nudgeOverlayBlock: (blockId: string, dx: number, dy: number) => void;
  setOverlayBlockNudge: (blockId: string, x: number, y: number) => void;
  resetOverlayTransform: () => void;
}

export interface ComposeSlice {
  layout: LayoutDetail | null;
  currentPageIndex: number;
  /** Decoded Float32Array page path LRU cache (max 24 pages) keyed by `${layout_id}:${page_index}` */
  pagePathsCache: Record<string, DecodedPagePaths>;
  activePagePaths: DecodedPagePaths | null;
  composing: boolean;

  composeNow: (overrideWriterId?: string | null) => Promise<void>;
  setCurrentPageIndex: (pageIndex: number) => Promise<void>;
  ensurePagePaths: (layoutId: string, pageIndex: number) => Promise<DecodedPagePaths | null>;
  focusBlockOnCanvas: (blockId: string) => Promise<void>;
  focusMissingGlyph: (mg: MissingGlyphBox) => Promise<void>;
}

export type DocumentLayoutStoreState = DocumentSlice & LayoutConfigSlice & ComposeSlice;

export type DocLayoutSliceCreator<T> = StateCreator<DocumentLayoutStoreState, [], [], T>;

let composeDebounceTimer: number | null = null;
let composeSeq = 0;

export function nextComposeSeq(): number {
  composeSeq += 1;
  return composeSeq;
}

export function currentComposeSeq(): number {
  return composeSeq;
}

export function cancelPendingCompose(): void {
  composeSeq += 1;
  if (composeDebounceTimer !== null) {
    window.clearTimeout(composeDebounceTimer);
    composeDebounceTimer = null;
  }
}

export function scheduleCompose(runCompose: () => Promise<void>, immediate = false): void {
  if (composeDebounceTimer !== null) {
    window.clearTimeout(composeDebounceTimer);
    composeDebounceTimer = null;
  }
  if (immediate) {
    void runCompose();
    return;
  }
  composeDebounceTimer = window.setTimeout(() => {
    composeDebounceTimer = null;
    void runCompose();
  }, 150);
}

/**
 * SSOT invariant: under `uniform` page strategy, `page_rules.uniform` never stores
 * duplicate typography or margin overrides; global `config.page` & `config.text` remain authoritative.
 */
export function enforceUniformSSOT(cfg: LayoutConfig): LayoutConfig {
  if (cfg.page_rules.strategy !== 'uniform') return cfg;
  const u = cfg.page_rules.uniform;
  if (
    u.margins_mm === null &&
    u.font_size_mm === null &&
    u.line_spacing === null &&
    u.line_spacing_mm === null &&
    u.paragraph_spacing_mm === null &&
    u.ruled === null
  ) {
    return cfg;
  }
  return {
    ...cfg,
    page_rules: {
      ...cfg.page_rules,
      uniform: {
        ...u,
        margins_mm: null,
        font_size_mm: null,
        line_spacing: null,
        line_spacing_mm: null,
        paragraph_spacing_mm: null,
        ruled: null,
      },
    },
  };
}
