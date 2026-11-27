import type {
  DocBlock,
  LayoutConfig,
  MachineProfile,
  MachineState,
  MarginsMM,
  MissingGlyphBox,
  PlacedBlockBox,
  RuledConfig,
  WritingRegion,
} from '../api/types';
import type { DecodedPagePaths } from './f32PathDecoder';

export interface StageEngineOptions {
  mainCanvas: HTMLCanvasElement;
  topRuler: HTMLCanvasElement;
  leftRuler: HTMLCanvasElement;
  onCameraChange?: (zoom: number, panX: number, panY: number) => void;
  onCursorMove?: (mm: { x: number; y: number } | null) => void;
  onSelectBlock?: (blockId: string | null) => void;
  onBlockDragEnd?: (blockId: string, nudgeX: number, nudgeY: number) => void;
  onSelectRegion?: (regionId: string | null) => void;
  onCreateRegion?: (rect: { x_mm: number; y_mm: number; width_mm: number; height_mm: number }) => void;
  onUpdateRegionRect?: (
    regionId: string,
    rect: { x_mm: number; y_mm: number; width_mm: number; height_mm: number },
  ) => void;
  onSelectObject?: (blockId: string | null) => void;
  onLocateBlockInEditor?: (blockId: string) => void;
  onSelectMissingGlyph?: (mg: MissingGlyphBox) => void;
  onDoubleClickFormula?: (box: PlacedBlockBox) => void;
  onUpdatePlacedImageBox?: (
    blockId: string,
    pageIndex: number,
    bboxMm: [number, number, number, number],
  ) => void;
  onCursorStyleChange?: (cursor: string) => void;
}

export interface StageSceneSnapshot {
  theme: 'dark' | 'light';
  paths: DecodedPagePaths | null;
  config: LayoutConfig;
  profile: MachineProfile;
  blocks: DocBlock[];
  placedBlocks: PlacedBlockBox[];
  missingGlyphs: MissingGlyphBox[];
  pageIndex: number;
  underlayUrl: string | null;
  underlayOpacity: number;
  underlayRectMm: { x: number; y: number; w: number; h: number };
  hasPageBackground: boolean;
  activeMargins: MarginsMM;
  activeRuled: RuledConfig;
  showTravel: boolean;
  showBbox: boolean;
  showUnderlay: boolean;
  showRuled: boolean;
  showRegions: boolean;
  showMissingGlyphs: boolean;
  inkColor: string;
  stageTool: 'pan' | 'draw_region';
  selectedRegionId: string | null;
  selectedBlockId: string | null;
  selectedObjectId: string | null;
  activeMissingGlyphId: string | null;
  playbackProgress: number;
  machineState: MachineState;
}

export type ResizeHandle = 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w';

export const HANDLE_CURSORS: Record<ResizeHandle, string> = {
  nw: 'nwse-resize',
  se: 'nwse-resize',
  ne: 'nesw-resize',
  sw: 'nesw-resize',
  n: 'ns-resize',
  s: 'ns-resize',
  e: 'ew-resize',
  w: 'ew-resize',
};

export const BASE_PX_PER_MM = 2.85;

export interface RegionRect {
  x_mm: number;
  y_mm: number;
  width_mm: number;
  height_mm: number;
}

export interface DrawDraftState {
  startX: number;
  startY: number;
  curX: number;
  curY: number;
}

export interface RegionDragState {
  regionId: string;
  mode: 'move' | 'resize';
  handle?: ResizeHandle;
  startX: number;
  startY: number;
  origRect: RegionRect;
  curRect: RegionRect;
}

export interface DragBlockState {
  blockId: string;
  startWorldX: number;
  startWorldY: number;
  origNudgeX: number;
  origNudgeY: number;
  curNudgeX: number;
  curNudgeY: number;
}

export interface PlacedImageDragState {
  blockId: string;
  pageIndex: number;
  mode: 'move' | 'resize';
  handle?: ResizeHandle;
  startX: number;
  startY: number;
  origBox: [number, number, number, number];
  curBox: [number, number, number, number];
}

export interface PulseHighlightState {
  bboxMm: [number, number, number, number];
  color: string;
  untilMs: number;
}
