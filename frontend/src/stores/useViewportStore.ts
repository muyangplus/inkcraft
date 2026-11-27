import { create } from 'zustand';

export type LeftStudioTab = 'document' | 'paper' | 'writer' | 'refine';
export type ThemeMode = 'dark' | 'light';
export type AppMode = 'production' | 'demo';
export type StageTool = 'pan' | 'draw_region';
export type WorkspaceView = 'canvas' | 'split' | 'editor';
export type EditorSubMode = 'visual' | 'markdown';

export interface CameraFocusRequest {
  nonce: number;
  pageIndex: number;
  bboxMm: [number, number, number, number];
  blockId?: string;
  missingId?: string;
  color?: string;
  maxZoom?: number;
}

export interface EditorScrollTarget {
  nonce: number;
  blockId: string;
}

export interface FormulaEditorTarget {
  docId: string;
  blockId: string;
  inlineIndex: number | null;
  initialLatex: string;
  assetName?: string | null;
}
export type ActiveModal =
  | null
  | 'about'
  | 'glyph-inspector'
  | 'machine-profile'
  | 'paper-change'
  | 'quick-text'
  | 'font-builder'
  | 'document-import';

export interface ToastItem {
  id: number;
  message: string;
  tone: 'info' | 'success' | 'warn' | 'error';
}

const THEME_STORAGE_KEY = 'handwrite_theme_v2';

function loadInitialTheme(): ThemeMode {
  try {
    const saved = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (saved === 'dark' || saved === 'light') return saved;
  } catch {
    // ignore storage errors
  }
  return 'light';
}

export interface ViewportState {
  theme: ThemeMode;
  appMode: AppMode;
  leftTab: LeftStudioTab;

  // Canvas view transform
  zoom: number;
  panX: number;
  panY: number;
  fitNonce: number;

  // Layer visibility toggles
  showTravel: boolean;
  showBbox: boolean;
  showUnderlay: boolean;
  showRuled: boolean;
  showRegions: boolean;
  showMissingGlyphs: boolean;
  inkColor: string;

  // Workspace view & Document/Object Editor state
  workspaceView: WorkspaceView;
  editorSubMode: EditorSubMode;
  selectedObjectId: string | null;
  formulaEditorTarget: FormulaEditorTarget | null;

  // Stage interaction tool & selections
  stageTool: StageTool;
  newRegionRole: 'field' | 'body';
  selectedRegionId: string | null;
  selectedBlockId: string | null;

  // Fallback & Missing Glyph highlight focus + cross-pane jump signals
  highlightFallbackChar: string | null;
  activeMissingGlyphId: string | null;
  cameraFocusRequest: CameraFocusRequest | null;
  editorScrollTarget: EditorScrollTarget | null;

  // Preview playback scrubber (0..1)
  playbackProgress: number;
  isPlayingPreview: boolean;
  playbackSpeed: 1 | 4 | 16;

  // Drawers & Modals
  serialDrawerOpen: boolean;
  activeModal: ActiveModal;
  glyphInspectorChar: string;
  penChangeOpen: boolean;

  // Paper change modal context
  paperChangeNextPage: number;
  paperChangeCompletedPage: number;

  // Jog keyboard focus
  jogKeyboardActive: boolean;

  // Toasts
  toasts: ToastItem[];

  setTheme: (theme: ThemeMode) => void;
  toggleTheme: () => void;
  setAppMode: (mode: AppMode) => void;
  setLeftTab: (tab: LeftStudioTab) => void;
  setCamera: (zoom: number, panX: number, panY: number) => void;
  requestFit: () => void;
  setZoom100: () => void;
  zoomBy: (factor: number) => void;

  toggleTravel: () => void;
  toggleBbox: () => void;
  toggleUnderlay: () => void;
  setShowUnderlay: (v: boolean) => void;
  toggleRuled: () => void;
  toggleRegions: () => void;
  setShowRegions: (v: boolean) => void;
  toggleMissingGlyphs: () => void;
  setShowMissingGlyphs: (v: boolean) => void;
  setInkColor: (color: string) => void;

  setWorkspaceView: (view: WorkspaceView) => void;
  setEditorSubMode: (mode: EditorSubMode) => void;
  setSelectedObjectId: (id: string | null) => void;
  openFormulaEditor: (target: FormulaEditorTarget) => void;
  closeFormulaEditor: () => void;

  setStageTool: (tool: StageTool) => void;
  setNewRegionRole: (role: 'field' | 'body') => void;
  setSelectedRegionId: (id: string | null) => void;
  setSelectedBlockId: (id: string | null) => void;
  setHighlightFallbackChar: (ch: string | null) => void;
  setActiveMissingGlyphId: (id: string | null) => void;
  requestCameraFocus: (req: Omit<CameraFocusRequest, 'nonce'>) => void;
  clearCameraFocus: () => void;
  requestEditorScroll: (blockId: string) => void;
  clearEditorScrollTarget: () => void;

  setPlaybackProgress: (p: number) => void;
  setIsPlayingPreview: (playing: boolean) => void;
  setPlaybackSpeed: (speed: 1 | 4 | 16) => void;

  setSerialDrawerOpen: (open: boolean) => void;
  openModal: (modal: ActiveModal) => void;
  openGlyphInspector: (char?: string) => void;
  setGlyphInspectorChar: (char: string) => void;
  setPenChangeOpen: (open: boolean) => void;
  openPaperChangeModal: (nextPageIndex: number) => void;
  setJogKeyboardActive: (active: boolean) => void;

  pushToast: (message: string, tone?: ToastItem['tone']) => void;
}

let nextToastId = 1;
let nextFocusNonce = 1;
let nextEditorScrollNonce = 1;

export const useViewportStore = create<ViewportState>((set, get) => ({
  theme: loadInitialTheme(),
  appMode: 'production',
  leftTab: 'document',

  zoom: 1,
  panX: 0,
  panY: 0,
  fitNonce: 1,

  showTravel: false,
  showBbox: true,
  showUnderlay: true,
  showRuled: true,
  showRegions: true,
  showMissingGlyphs: true,
  inkColor: '#1B365D',

  workspaceView: 'canvas',
  editorSubMode: 'visual',
  selectedObjectId: null,
  formulaEditorTarget: null,

  stageTool: 'pan',
  newRegionRole: 'field',
  selectedRegionId: null,
  selectedBlockId: null,
  highlightFallbackChar: null,
  activeMissingGlyphId: null,
  cameraFocusRequest: null,
  editorScrollTarget: null,

  playbackProgress: 1,
  isPlayingPreview: false,
  playbackSpeed: 4,

  serialDrawerOpen: false,
  activeModal: null,
  glyphInspectorChar: '永',
  penChangeOpen: false,

  paperChangeNextPage: 1,
  paperChangeCompletedPage: 0,

  jogKeyboardActive: false,
  toasts: [],

  setTheme: (theme) => {
    document.documentElement.setAttribute('data-theme', theme);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      // ignore
    }
    set({ theme });
  },

  toggleTheme: () => {
    const next: ThemeMode = get().theme === 'dark' ? 'light' : 'dark';
    get().setTheme(next);
  },

  setAppMode: (appMode) => set({ appMode }),

  setLeftTab: (leftTab) => set({ leftTab }),

  setCamera: (zoom, panX, panY) =>
    set({
      zoom: Math.max(0.25, Math.min(5, zoom)),
      panX,
      panY,
    }),

  requestFit: () => set((s) => ({ fitNonce: s.fitNonce + 1 })),

  setZoom100: () => set({ zoom: 1 }),

  zoomBy: (factor) =>
    set((s) => ({
      zoom: Math.max(0.25, Math.min(5, s.zoom * factor)),
    })),

  toggleTravel: () => set((s) => ({ showTravel: !s.showTravel })),
  toggleBbox: () => set((s) => ({ showBbox: !s.showBbox })),
  toggleUnderlay: () => set((s) => ({ showUnderlay: !s.showUnderlay })),
  setShowUnderlay: (showUnderlay) => set({ showUnderlay }),
  toggleRuled: () => set((s) => ({ showRuled: !s.showRuled })),
  toggleRegions: () => set((s) => ({ showRegions: !s.showRegions })),
  setShowRegions: (showRegions) => set({ showRegions }),
  toggleMissingGlyphs: () => set((s) => ({ showMissingGlyphs: !s.showMissingGlyphs })),
  setShowMissingGlyphs: (showMissingGlyphs) => set({ showMissingGlyphs }),
  setInkColor: (inkColor) => set({ inkColor }),

  setWorkspaceView: (workspaceView) => set({ workspaceView }),
  setEditorSubMode: (editorSubMode) => set({ editorSubMode }),
  setSelectedObjectId: (selectedObjectId) => set({ selectedObjectId }),
  openFormulaEditor: (formulaEditorTarget) => set({ formulaEditorTarget }),
  closeFormulaEditor: () => set({ formulaEditorTarget: null }),

  setStageTool: (stageTool) => set({ stageTool }),
  setNewRegionRole: (newRegionRole) => set({ newRegionRole }),
  setSelectedRegionId: (selectedRegionId) => set({ selectedRegionId }),
  setSelectedBlockId: (selectedBlockId) => set({ selectedBlockId }),
  setHighlightFallbackChar: (highlightFallbackChar) => set({ highlightFallbackChar }),
  setActiveMissingGlyphId: (activeMissingGlyphId) => set({ activeMissingGlyphId }),
  requestCameraFocus: (req) =>
    set({
      cameraFocusRequest: {
        ...req,
        nonce: nextFocusNonce++,
      },
    }),
  clearCameraFocus: () => set({ cameraFocusRequest: null }),
  requestEditorScroll: (blockId) =>
    set({
      selectedObjectId: blockId,
      editorScrollTarget: {
        nonce: nextEditorScrollNonce++,
        blockId,
      },
    }),
  clearEditorScrollTarget: () => set({ editorScrollTarget: null }),

  setPlaybackProgress: (playbackProgress) =>
    set({ playbackProgress: Math.max(0, Math.min(1, playbackProgress)) }),
  setIsPlayingPreview: (isPlayingPreview) => set({ isPlayingPreview }),
  setPlaybackSpeed: (playbackSpeed) => set({ playbackSpeed }),

  setSerialDrawerOpen: (serialDrawerOpen) => set({ serialDrawerOpen }),
  openModal: (activeModal) => set({ activeModal }),
  openGlyphInspector: (char) =>
    set((s) => ({
      activeModal: 'glyph-inspector',
      glyphInspectorChar: char || s.glyphInspectorChar || '永',
    })),
  setGlyphInspectorChar: (glyphInspectorChar) => set({ glyphInspectorChar }),
  setPenChangeOpen: (penChangeOpen) => set({ penChangeOpen }),
  openPaperChangeModal: (nextPageIndex) =>
    set({
      activeModal: 'paper-change',
      paperChangeNextPage: nextPageIndex,
      paperChangeCompletedPage: Math.max(0, nextPageIndex - 1),
    }),
  setJogKeyboardActive: (jogKeyboardActive) => set({ jogKeyboardActive }),

  pushToast: (message, tone = 'info') => {
    const id = nextToastId++;
    set((s) => ({ toasts: [...s.toasts.slice(-3), { id, message, tone }] }));
    window.setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
    }, 3400);
  },
}));
