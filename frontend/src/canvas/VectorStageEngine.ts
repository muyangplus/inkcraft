import {
  matchesPageScope,
  type MissingGlyphBox,
  type PlacedBlockBox,
  type WritingRegion,
} from '../api/types';
import { telemetryBus } from '../stores/telemetryBus';
import {
  computeOverlayBoxes,
  hitTestOverlayBlocks,
  worldDeltaToOverlayNudge,
  type OverlayBlockBox,
} from './overlayHitTest';
import { hitTestRegionBody, hitTestRegionHandle } from './regionGeometry';
import { renderRulers } from './rulerRenderer';
import {
  renderDrawDraftLayer,
  renderMatBackgroundLayer,
  renderMissingGlyphsLayer,
  renderOverlayBoxesLayer,
  renderPaperSheetAndGuidesLayer,
  renderPenCrosshairLayer,
  renderPlacedObjectsLayer,
  renderProgressStrokesLayer,
  renderPulseHighlightLayer,
  renderTravelAndBboxLayer,
  renderWritingRegionsLayer,
} from './stageLayers';
import {
  BASE_PX_PER_MM,
  HANDLE_CURSORS,
  type DragBlockState,
  type DrawDraftState,
  type PlacedImageDragState,
  type PulseHighlightState,
  type RegionDragState,
  type ResizeHandle,
  type StageEngineOptions,
  type StageSceneSnapshot,
} from './stageTypes';
import { StrokeLayerCache } from './strokeCache';
import { UnderlayImageCache } from './underlayCache';

export type { StageEngineOptions, StageSceneSnapshot } from './stageTypes';

/**
 * Pure TypeScript 6-Layer Canvas 2D Vector Stage Engine with demand-driven RAF scheduling.
 */
export class VectorStageEngine {
  private mainCanvas: HTMLCanvasElement;
  private topRuler: HTMLCanvasElement;
  private leftRuler: HTMLCanvasElement;
  private opts: StageEngineOptions;

  private strokeCache = new StrokeLayerCache();
  private underlayCache = new UnderlayImageCache();

  // Camera state
  private zoom = 1;
  private panX = 40;
  private panY = 24;

  // Scene state pushed from React
  private scene: StageSceneSnapshot | null = null;
  private overlayBoxes: OverlayBlockBox[] = [];
  private hoveredBlockId: string | null = null;
  private cursorMm: { x: number; y: number } | null = null;

  // Interaction state
  private dragBlock: DragBlockState | null = null;
  private activeRegions: WritingRegion[] = [];
  private hoveredRegionId: string | null = null;
  private hoveredHandle: ResizeHandle | null = null;
  private drawDraft: DrawDraftState | null = null;
  private regionDrag: RegionDragState | null = null;
  private hoveredObjectId: string | null = null;
  private imageDrag: PlacedImageDragState | null = null;
  private pulseHighlight: PulseHighlightState | null = null;
  private cameraTweenRaf: number | null = null;
  private lastCursorStyle = '';

  // Frame trail history for FRAMING animation
  private penTrail: Array<{ x: number; y: number }> = [];

  // Demand-driven RAF handle
  private rafId: number | null = null;
  private destroyed = false;
  private unsubStatus: (() => void) | null = null;
  private unsubProgress: (() => void) | null = null;
  private resizeObserver: ResizeObserver | null = null;

  constructor(opts: StageEngineOptions) {
    this.opts = opts;
    this.mainCanvas = opts.mainCanvas;
    this.topRuler = opts.topRuler;
    this.leftRuler = opts.leftRuler;

    this.unsubStatus = telemetryBus.subscribeStatus((st) => {
      if (st.machine_state === 'FRAMING') {
        this.penTrail.push({ x: st.wpos.x, y: st.wpos.y });
        if (this.penTrail.length > 80) this.penTrail.shift();
      } else if (this.penTrail.length > 0) {
        this.penTrail = [];
      }
      this.scheduleRender();
    });

    this.unsubProgress = telemetryBus.subscribeProgress(() => {
      this.scheduleRender();
    });

    this.resizeObserver = new ResizeObserver(() => {
      this.scheduleRender();
    });
    this.resizeObserver.observe(this.mainCanvas);
  }

  destroy(): void {
    this.destroyed = true;
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
    if (this.cameraTweenRaf !== null) {
      cancelAnimationFrame(this.cameraTweenRaf);
      this.cameraTweenRaf = null;
    }
    this.unsubStatus?.();
    this.unsubProgress?.();
    this.resizeObserver?.disconnect();
    this.strokeCache.destroy();
    this.underlayCache.destroy();
  }

  private scheduleRender(): void {
    if (this.destroyed || this.rafId !== null) return;
    this.rafId = requestAnimationFrame(() => {
      this.rafId = null;
      if (!this.destroyed) {
        this.render();
      }
    });
  }

  updateScene(snapshot: StageSceneSnapshot): void {
    this.scene = snapshot;
    const pw = this.getPageWidthMm();
    const ph = this.getPageHeightMm();
    this.overlayBoxes = computeOverlayBoxes(
      snapshot.blocks,
      snapshot.pageIndex,
      snapshot.config.overlay,
      pw,
      ph,
    );
    this.activeRegions = (snapshot.config.regions || []).filter((r) =>
      matchesPageScope(r.page_scope, snapshot.pageIndex),
    );

    if (snapshot.underlayUrl) {
      this.underlayCache.ensureLoaded(snapshot.underlayUrl, () => {
        this.scheduleRender();
      });
    }

    this.scheduleRender();
  }

  private setCursorStyle(style: string): void {
    if (style !== this.lastCursorStyle) {
      this.lastCursorStyle = style;
      this.opts.onCursorStyleChange?.(style);
    }
  }

  setCamera(zoom: number, panX: number, panY: number): void {
    if (this.cameraTweenRaf !== null) {
      cancelAnimationFrame(this.cameraTweenRaf);
      this.cameraTweenRaf = null;
    }
    this.zoom = Math.max(0.25, Math.min(5, zoom));
    this.panX = panX;
    this.panY = panY;
    this.scheduleRender();
  }

  getCamera(): { zoom: number; panX: number; panY: number } {
    return { zoom: this.zoom, panX: this.panX, panY: this.panY };
  }

  focusWorldBox(
    bboxMm: [number, number, number, number],
    opts?: { color?: string; maxZoom?: number; durationMs?: number },
  ): void {
    const w = this.mainCanvas.clientWidth;
    const h = this.mainCanvas.clientHeight;
    if (w <= 0 || h <= 0) return;

    if (this.cameraTweenRaf !== null) {
      cancelAnimationFrame(this.cameraTweenRaf);
      this.cameraTweenRaf = null;
    }

    const [x0, y0, x1, y1] = bboxMm;
    const bw = Math.max(4, x1 - x0);
    const bh = Math.max(4, y1 - y0);
    const cx = (x0 + x1) * 0.5;
    const cy = (y0 + y1) * 0.5;

    const maxAllowedZoom = opts?.maxZoom ?? 2.4;
    const fitScaleX = (w * 0.52) / bw;
    const fitScaleY = (h * 0.42) / bh;
    const fitZoom = Math.min(fitScaleX, fitScaleY) / BASE_PX_PER_MM;
    const targetZoom = Math.max(0.55, Math.min(maxAllowedZoom, fitZoom));
    const targetScale = targetZoom * BASE_PX_PER_MM;
    const targetPanX = w * 0.5 - cx * targetScale;
    const targetPanY = h * 0.5 - cy * targetScale;

    this.pulseHighlight = {
      bboxMm,
      color: opts?.color ?? '#4F46E5',
      untilMs: performance.now() + 1250,
    };

    const startZoom = this.zoom;
    const startPanX = this.panX;
    const startPanY = this.panY;
    const duration = opts?.durationMs ?? 260;
    const t0 = performance.now();

    const step = (now: number) => {
      if (this.destroyed) return;
      const elapsed = now - t0;
      const rawT = Math.min(1, elapsed / Math.max(1, duration));
      const ease = 1 - Math.pow(1 - rawT, 3);
      this.zoom = startZoom + (targetZoom - startZoom) * ease;
      this.panX = startPanX + (targetPanX - startPanX) * ease;
      this.panY = startPanY + (targetPanY - startPanY) * ease;
      this.scheduleRender();

      if (rawT < 1) {
        this.cameraTweenRaf = requestAnimationFrame(step);
      } else {
        this.cameraTweenRaf = null;
        this.opts.onCameraChange?.(this.zoom, this.panX, this.panY);
      }
    };
    this.cameraTweenRaf = requestAnimationFrame(step);
  }

  fitToViewport(): void {
    const w = this.mainCanvas.clientWidth;
    const h = this.mainCanvas.clientHeight;
    if (w <= 0 || h <= 0) return;
    const pw = this.getPageWidthMm();
    const ph = this.getPageHeightMm();

    const padX = 56;
    const padTop = 68;
    const padBottom = 56;
    const availW = Math.max(120, w - padX * 2);
    const availH = Math.max(120, h - padTop - padBottom);

    const scale = Math.min(availW / pw, availH / ph);
    const nextZoom = Math.max(0.25, Math.min(4.5, scale / BASE_PX_PER_MM));
    const s = nextZoom * BASE_PX_PER_MM;

    this.zoom = nextZoom;
    this.panX = (w - pw * s) * 0.5;
    this.panY = padTop + (availH - ph * s) * 0.5;
    this.scheduleRender();
    this.opts.onCameraChange?.(this.zoom, this.panX, this.panY);
  }

  zoomAtScreenPoint(factor: number, sx: number, sy: number): void {
    const oldScale = this.zoom * BASE_PX_PER_MM;
    const worldX = (sx - this.panX) / oldScale;
    const worldY = (sy - this.panY) / oldScale;

    const nextZoom = Math.max(0.25, Math.min(5, this.zoom * factor));
    const newScale = nextZoom * BASE_PX_PER_MM;
    this.zoom = nextZoom;
    this.panX = sx - worldX * newScale;
    this.panY = sy - worldY * newScale;
    this.scheduleRender();
    this.opts.onCameraChange?.(this.zoom, this.panX, this.panY);
  }

  panBy(dx: number, dy: number): void {
    this.panX += dx;
    this.panY += dy;
    this.scheduleRender();
    this.opts.onCameraChange?.(this.zoom, this.panX, this.panY);
  }

  screenToWorld(sx: number, sy: number): { x: number; y: number } {
    const s = this.zoom * BASE_PX_PER_MM;
    return {
      x: (sx - this.panX) / s,
      y: (sy - this.panY) / s,
    };
  }

  handlePointerMove(sx: number, sy: number): void {
    const w = this.screenToWorld(sx, sy);
    this.cursorMm = w;
    this.opts.onCursorMove?.(w);

    const pw = this.getPageWidthMm();
    const ph = this.getPageHeightMm();

    if (this.drawDraft) {
      this.drawDraft.curX = Math.max(0, Math.min(pw, w.x));
      this.drawDraft.curY = Math.max(0, Math.min(ph, w.y));
      this.setCursorStyle('crosshair');
      this.scheduleRender();
      return;
    }

    if (this.imageDrag) {
      const dx = w.x - this.imageDrag.startX;
      const dy = w.y - this.imageDrag.startY;
      const [ox0, oy0, ox1, oy1] = this.imageDrag.origBox;
      const ow = Math.max(10, ox1 - ox0);
      const oh = Math.max(10, oy1 - oy0);
      const snap = (v: number) => Math.round(v * 2) / 2;

      if (this.imageDrag.mode === 'move') {
        const nx = Math.max(0, Math.min(pw - ow, snap(ox0 + dx)));
        const ny = Math.max(0, Math.min(ph - oh, snap(oy0 + dy)));
        this.imageDrag.curBox = [
          nx,
          ny,
          Number((nx + ow).toFixed(2)),
          Number((ny + oh).toFixed(2)),
        ];
        this.setCursorStyle('move');
      } else {
        const h = this.imageDrag.handle!;
        let x0 = ox0;
        let y0 = oy0;
        let x1 = ox1;
        let y1 = oy1;
        const minSize = 10;
        if (h.includes('w')) x0 = Math.max(0, Math.min(x1 - minSize, snap(ox0 + dx)));
        if (h.includes('e')) x1 = Math.min(pw, Math.max(x0 + minSize, snap(ox1 + dx)));
        if (h.includes('n')) y0 = Math.max(0, Math.min(y1 - minSize, snap(oy0 + dy)));
        if (h.includes('s')) y1 = Math.min(ph, Math.max(y0 + minSize, snap(oy1 + dy)));
        this.imageDrag.curBox = [
          Number(x0.toFixed(2)),
          Number(y0.toFixed(2)),
          Number(x1.toFixed(2)),
          Number(y1.toFixed(2)),
        ];
        this.setCursorStyle(HANDLE_CURSORS[h]);
      }
      this.scheduleRender();
      return;
    }

    if (this.regionDrag) {
      const dx = w.x - this.regionDrag.startX;
      const dy = w.y - this.regionDrag.startY;
      const orig = this.regionDrag.origRect;
      const snap = (v: number) => Math.round(v * 2) / 2;

      if (this.regionDrag.mode === 'move') {
        const nx = Math.max(0, Math.min(pw - orig.width_mm, snap(orig.x_mm + dx)));
        const ny = Math.max(0, Math.min(ph - orig.height_mm, snap(orig.y_mm + dy)));
        this.regionDrag.curRect = {
          x_mm: nx,
          y_mm: ny,
          width_mm: orig.width_mm,
          height_mm: orig.height_mm,
        };
        this.setCursorStyle('move');
      } else {
        const h = this.regionDrag.handle!;
        let x0 = orig.x_mm;
        let y0 = orig.y_mm;
        let x1 = orig.x_mm + orig.width_mm;
        let y1 = orig.y_mm + orig.height_mm;
        const minW = 5;
        const minH = 4;
        if (h.includes('w')) x0 = Math.max(0, Math.min(x1 - minW, snap(orig.x_mm + dx)));
        if (h.includes('e')) x1 = Math.min(pw, Math.max(x0 + minW, snap(orig.x_mm + orig.width_mm + dx)));
        if (h.includes('n')) y0 = Math.max(0, Math.min(y1 - minH, snap(orig.y_mm + dy)));
        if (h.includes('s')) y1 = Math.min(ph, Math.max(y0 + minH, snap(orig.y_mm + orig.height_mm + dy)));
        this.regionDrag.curRect = {
          x_mm: x0,
          y_mm: y0,
          width_mm: Number((x1 - x0).toFixed(2)),
          height_mm: Number((y1 - y0).toFixed(2)),
        };
        this.setCursorStyle(HANDLE_CURSORS[h]);
      }
      this.scheduleRender();
      return;
    }

    if (this.dragBlock && this.scene) {
      const dxWorld = w.x - this.dragBlock.startWorldX;
      const dyWorld = w.y - this.dragBlock.startWorldY;
      const [dnx, dny] = worldDeltaToOverlayNudge(this.scene.config.overlay, dxWorld, dyWorld);
      this.dragBlock.curNudgeX = Math.round((this.dragBlock.origNudgeX + dnx) * 2) / 2;
      this.dragBlock.curNudgeY = Math.round((this.dragBlock.origNudgeY + dny) * 2) / 2;
      this.setCursorStyle('move');
      this.scheduleRender();
      return;
    }

    if (this.scene?.stageTool === 'draw_region') {
      this.hoveredRegionId = null;
      this.hoveredHandle = null;
      this.setCursorStyle('crosshair');
      this.scheduleRender();
      return;
    }

    if (this.scene?.showRegions && this.activeRegions.length > 0) {
      const s = this.zoom * BASE_PX_PER_MM;
      if (this.scene.selectedRegionId) {
        const selReg = this.activeRegions.find((r) => r.region_id === this.scene!.selectedRegionId);
        if (selReg) {
          const handle = hitTestRegionHandle(w.x, w.y, selReg, s);
          if (handle) {
            this.hoveredHandle = handle;
            this.hoveredRegionId = selReg.region_id;
            this.setCursorStyle(HANDLE_CURSORS[handle]);
            this.scheduleRender();
            return;
          }
        }
      }
      const hitReg = hitTestRegionBody(this.activeRegions, w.x, w.y);
      if (hitReg) {
        this.hoveredRegionId = hitReg.region_id;
        this.hoveredHandle = null;
        this.setCursorStyle('move');
        this.scheduleRender();
        return;
      }
    }
    this.hoveredRegionId = null;
    this.hoveredHandle = null;

    // Hit-test placed images (resize handles then body) & formulas for interactive affordances
    const s = this.zoom * BASE_PX_PER_MM;
    const placed = this.scene?.placedBlocks || [];
    const mediaBoxes = placed.filter((b) => b.block_type === 'figure' || b.block_type === 'chart');
    if (this.scene?.selectedObjectId) {
      const selMedia = mediaBoxes.find((b) => b.block_id === this.scene!.selectedObjectId);
      if (selMedia) {
        const [bx0, by0, bx1, by1] = selMedia.bbox_mm;
        const h = hitTestRegionHandle(
          w.x,
          w.y,
          { x_mm: bx0, y_mm: by0, width_mm: Math.max(4, bx1 - bx0), height_mm: Math.max(4, by1 - by0) },
          s,
        );
        if (h) {
          this.hoveredObjectId = selMedia.block_id;
          this.setCursorStyle(HANDLE_CURSORS[h]);
          this.scheduleRender();
          return;
        }
      }
    }
    const hitMedia = this.findHitBox(mediaBoxes, w.x, w.y, 1.5);
    if (hitMedia) {
      this.hoveredObjectId = hitMedia.block_id;
      this.hoveredBlockId = null;
      this.setCursorStyle('move');
      this.scheduleRender();
      return;
    }
    const formulaBoxes = this.orderedFormulaBoxes(placed);
    const hitFormula = this.findHitBox(formulaBoxes, w.x, w.y, 2.0);
    if (hitFormula) {
      this.hoveredObjectId = hitFormula.block_id;
      this.hoveredBlockId = null;
      this.setCursorStyle('pointer');
      this.scheduleRender();
      return;
    }

    if (this.scene?.showMissingGlyphs && this.scene.missingGlyphs.length > 0) {
      const hitMg = this.findHitMissingGlyph(this.scene.missingGlyphs, w.x, w.y, 1.4);
      if (hitMg) {
        this.hoveredObjectId = hitMg.block_id || null;
        this.hoveredBlockId = null;
        this.setCursorStyle('pointer');
        this.scheduleRender();
        return;
      }
    }

    const otherBoxes = placed.filter(
      (b) =>
        b.block_type !== 'figure' &&
        b.block_type !== 'chart' &&
        b.block_type !== 'formula_block' &&
        b.block_type !== 'formula_inline',
    );
    const hitOther = this.findHitBox(otherBoxes, w.x, w.y, 1.0);
    if (hitOther) {
      this.hoveredObjectId = hitOther.block_id;
      this.hoveredBlockId = null;
      this.setCursorStyle('pointer');
      this.scheduleRender();
      return;
    }
    this.hoveredObjectId = null;

    if (this.scene?.config.mode === 'overlay') {
      const hit = hitTestOverlayBlocks(this.overlayBoxes, w.x, w.y);
      const nextHover = hit ? hit.block.block_id : null;
      if (nextHover !== this.hoveredBlockId) {
        this.hoveredBlockId = nextHover;
      }
      this.setCursorStyle(hit ? 'move' : 'grab');
    } else {
      if (this.hoveredBlockId !== null) {
        this.hoveredBlockId = null;
      }
      this.setCursorStyle('grab');
    }

    this.scheduleRender();
  }

  handlePointerLeave(): void {
    this.cursorMm = null;
    this.hoveredBlockId = null;
    this.hoveredRegionId = null;
    this.hoveredHandle = null;
    this.hoveredObjectId = null;
    this.opts.onCursorMove?.(null);
    this.scheduleRender();
  }

  private orderedFormulaBoxes(placed: PlacedBlockBox[]): PlacedBlockBox[] {
    const inline = placed.filter((b) => b.block_type === 'formula_inline');
    const display = placed.filter((b) => b.block_type === 'formula_block');
    return [...display, ...inline];
  }

  private findHitBox(
    boxes: PlacedBlockBox[],
    wx: number,
    wy: number,
    tolMm: number,
  ): PlacedBlockBox | null {
    for (let i = boxes.length - 1; i >= 0; i--) {
      const b = boxes[i];
      const [x0, y0, x1, y1] = b.bbox_mm;
      if (wx >= x0 - tolMm && wx <= x1 + tolMm && wy >= y0 - tolMm && wy <= y1 + tolMm) {
        return b;
      }
    }
    return null;
  }

  private findHitMissingGlyph(
    boxes: MissingGlyphBox[],
    wx: number,
    wy: number,
    tolMm: number,
  ): MissingGlyphBox | null {
    for (let i = boxes.length - 1; i >= 0; i--) {
      const b = boxes[i];
      const [x0, y0, x1, y1] = b.bbox_mm;
      if (wx >= x0 - tolMm && wx <= x1 + tolMm && wy >= y0 - tolMm && wy <= y1 + tolMm) {
        return b;
      }
    }
    return null;
  }

  handleCanvasClick(sx: number, sy: number): boolean {
    const scene = this.scene;
    if (!scene) return false;
    const w = this.screenToWorld(sx, sy);

    if (scene.showMissingGlyphs && scene.missingGlyphs.length > 0) {
      const hitMg = this.findHitMissingGlyph(scene.missingGlyphs, w.x, w.y, 1.4);
      if (hitMg) {
        this.pulseHighlight = {
          bboxMm: hitMg.bbox_mm,
          color: '#DC2626',
          untilMs: performance.now() + 1250,
        };
        this.opts.onSelectMissingGlyph?.(hitMg);
        this.scheduleRender();
        return true;
      }
    }

    const placed = scene.placedBlocks || [];
    const formulaBoxes = this.orderedFormulaBoxes(placed);
    const hitF = this.findHitBox(formulaBoxes, w.x, w.y, 2.0);
    if (hitF) {
      this.opts.onSelectObject?.(hitF.block_id);
      this.opts.onLocateBlockInEditor?.(hitF.block_id);
      this.scheduleRender();
      return true;
    }

    const otherBoxes = placed.filter(
      (b) =>
        b.block_type !== 'figure' &&
        b.block_type !== 'chart' &&
        b.block_type !== 'formula_block' &&
        b.block_type !== 'formula_inline',
    );
    const hitOther = this.findHitBox(otherBoxes, w.x, w.y, 1.0);
    if (hitOther) {
      this.opts.onSelectObject?.(hitOther.block_id);
      this.opts.onLocateBlockInEditor?.(hitOther.block_id);
      this.scheduleRender();
      return true;
    }
    return false;
  }

  handleDoubleClick(sx: number, sy: number): boolean {
    const scene = this.scene;
    if (!scene) return false;
    const w = this.screenToWorld(sx, sy);
    const formulaBoxes = this.orderedFormulaBoxes(scene.placedBlocks || []);
    const hitF = this.findHitBox(formulaBoxes, w.x, w.y, 2.2);
    if (hitF) {
      this.opts.onSelectObject?.(hitF.block_id);
      this.opts.onDoubleClickFormula?.(hitF);
      this.scheduleRender();
      return true;
    }
    return false;
  }

  handlePointerDown(sx: number, sy: number): 'region' | 'object' | 'block' | 'none' {
    const scene = this.scene;
    if (!scene) return 'none';
    const w = this.screenToWorld(sx, sy);
    const pw = this.getPageWidthMm();
    const ph = this.getPageHeightMm();

    if (scene.stageTool === 'draw_region') {
      const cx = Math.max(0, Math.min(pw, w.x));
      const cy = Math.max(0, Math.min(ph, w.y));
      this.drawDraft = { startX: cx, startY: cy, curX: cx, curY: cy };
      this.scheduleRender();
      return 'region';
    }

    if (scene.showRegions && scene.selectedRegionId) {
      const selReg = this.activeRegions.find((r) => r.region_id === scene.selectedRegionId);
      if (selReg) {
        const handle = hitTestRegionHandle(w.x, w.y, selReg, this.zoom * BASE_PX_PER_MM);
        if (handle) {
          const origRect = {
            x_mm: selReg.x_mm,
            y_mm: selReg.y_mm,
            width_mm: selReg.width_mm,
            height_mm: selReg.height_mm,
          };
          this.regionDrag = {
            regionId: selReg.region_id,
            mode: 'resize',
            handle,
            startX: w.x,
            startY: w.y,
            origRect,
            curRect: { ...origRect },
          };
          this.scheduleRender();
          return 'region';
        }
      }
    }

    if (scene.showRegions && this.activeRegions.length > 0) {
      const hitReg = hitTestRegionBody(this.activeRegions, w.x, w.y);
      if (hitReg) {
        this.opts.onSelectRegion?.(hitReg.region_id);
        this.opts.onSelectBlock?.(null);
        const origRect = {
          x_mm: hitReg.x_mm,
          y_mm: hitReg.y_mm,
          width_mm: hitReg.width_mm,
          height_mm: hitReg.height_mm,
        };
        this.regionDrag = {
          regionId: hitReg.region_id,
          mode: 'move',
          startX: w.x,
          startY: w.y,
          origRect,
          curRect: { ...origRect },
        };
        this.scheduleRender();
        return 'region';
      }
    }

    // Interactive figure/chart objects (handles first, then body move)
    const mediaBoxes = (scene.placedBlocks || []).filter(
      (b) => b.block_type === 'figure' || b.block_type === 'chart',
    );
    if (scene.selectedObjectId) {
      const selMedia = mediaBoxes.find((b) => b.block_id === scene.selectedObjectId);
      if (selMedia) {
        const [bx0, by0, bx1, by1] = selMedia.bbox_mm;
        const h = hitTestRegionHandle(
          w.x,
          w.y,
          { x_mm: bx0, y_mm: by0, width_mm: Math.max(4, bx1 - bx0), height_mm: Math.max(4, by1 - by0) },
          this.zoom * BASE_PX_PER_MM,
        );
        if (h) {
          this.imageDrag = {
            blockId: selMedia.block_id,
            pageIndex: selMedia.page_index,
            mode: 'resize',
            handle: h,
            startX: w.x,
            startY: w.y,
            origBox: [bx0, by0, bx1, by1],
            curBox: [bx0, by0, bx1, by1],
          };
          this.scheduleRender();
          return 'object';
        }
      }
    }
    const hitMedia = this.findHitBox(mediaBoxes, w.x, w.y, 1.5);
    if (hitMedia) {
      this.opts.onSelectRegion?.(null);
      this.opts.onSelectBlock?.(null);
      this.opts.onSelectObject?.(hitMedia.block_id);
      const [bx0, by0, bx1, by1] = hitMedia.bbox_mm;
      this.imageDrag = {
        blockId: hitMedia.block_id,
        pageIndex: hitMedia.page_index,
        mode: 'move',
        startX: w.x,
        startY: w.y,
        origBox: [bx0, by0, bx1, by1],
        curBox: [bx0, by0, bx1, by1],
      };
      this.scheduleRender();
      return 'object';
    }

    if (scene.config.mode === 'overlay') {
      const hit = hitTestOverlayBlocks(this.overlayBoxes, w.x, w.y);
      if (hit) {
        this.opts.onSelectRegion?.(null);
        this.opts.onSelectObject?.(null);
        this.opts.onSelectBlock?.(hit.block.block_id);
        this.dragBlock = {
          blockId: hit.block.block_id,
          startWorldX: w.x,
          startWorldY: w.y,
          origNudgeX: hit.nudgeX,
          origNudgeY: hit.nudgeY,
          curNudgeX: hit.nudgeX,
          curNudgeY: hit.nudgeY,
        };
        this.scheduleRender();
        return 'block';
      }
    }

    this.opts.onSelectRegion?.(null);
    this.opts.onSelectBlock?.(null);
    this.opts.onSelectObject?.(null);
    this.scheduleRender();
    return 'none';
  }

  handlePointerUp(): void {
    if (this.imageDrag) {
      const { blockId, pageIndex, origBox, curBox } = this.imageDrag;
      this.imageDrag = null;
      const moved =
        Math.abs(curBox[0] - origBox[0]) > 0.6 ||
        Math.abs(curBox[1] - origBox[1]) > 0.6 ||
        Math.abs(curBox[2] - origBox[2]) > 0.6 ||
        Math.abs(curBox[3] - origBox[3]) > 0.6;
      if (moved) {
        this.opts.onUpdatePlacedImageBox?.(blockId, pageIndex, curBox);
      }
      this.scheduleRender();
      return;
    }

    if (this.drawDraft) {
      const { startX, startY, curX, curY } = this.drawDraft;
      this.drawDraft = null;
      const snap = (v: number) => Math.round(v * 2) / 2;
      const x0 = snap(Math.min(startX, curX));
      const y0 = snap(Math.min(startY, curY));
      const x1 = snap(Math.max(startX, curX));
      const y1 = snap(Math.max(startY, curY));
      const w = Number((x1 - x0).toFixed(1));
      const h = Number((y1 - y0).toFixed(1));
      if (w >= 4.0 && h >= 3.0) {
        this.opts.onCreateRegion?.({ x_mm: x0, y_mm: y0, width_mm: w, height_mm: h });
      }
      this.scheduleRender();
      return;
    }

    if (this.regionDrag) {
      const { regionId, origRect, curRect } = this.regionDrag;
      this.regionDrag = null;
      if (
        Math.abs(curRect.x_mm - origRect.x_mm) > 0.05 ||
        Math.abs(curRect.y_mm - origRect.y_mm) > 0.05 ||
        Math.abs(curRect.width_mm - origRect.width_mm) > 0.05 ||
        Math.abs(curRect.height_mm - origRect.height_mm) > 0.05
      ) {
        this.opts.onUpdateRegionRect?.(regionId, curRect);
      }
      this.scheduleRender();
      return;
    }

    if (this.dragBlock) {
      const { blockId, origNudgeX, origNudgeY, curNudgeX, curNudgeY } = this.dragBlock;
      this.dragBlock = null;
      if (Math.abs(curNudgeX - origNudgeX) > 0.05 || Math.abs(curNudgeY - origNudgeY) > 0.05) {
        this.opts.onBlockDragEnd?.(blockId, curNudgeX, curNudgeY);
      }
      this.scheduleRender();
    }
  }

  private getPageWidthMm(): number {
    if (!this.scene) return 210;
    return this.scene.paths?.widthMm || this.scene.config.page.width_mm || 210;
  }

  private getPageHeightMm(): number {
    if (!this.scene) return 297;
    return this.scene.paths?.heightMm || this.scene.config.page.height_mm || 297;
  }

  private render(): void {
    const scene = this.scene;
    if (!scene) return;

    const w = this.mainCanvas.clientWidth;
    const h = this.mainCanvas.clientHeight;
    if (w <= 0 || h <= 0) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (
      this.mainCanvas.width !== Math.round(w * dpr) ||
      this.mainCanvas.height !== Math.round(h * dpr)
    ) {
      this.mainCanvas.width = Math.round(w * dpr);
      this.mainCanvas.height = Math.round(h * dpr);
    }

    const ctx = this.mainCanvas.getContext('2d');
    if (!ctx) return;

    const s = this.zoom * BASE_PX_PER_MM;
    const pw = this.getPageWidthMm();
    const ph = this.getPageHeightMm();

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    renderMatBackgroundLayer(ctx, w, h, this.panX, this.panY, s, scene.theme);

    ctx.save();
    ctx.translate(this.panX, this.panY);
    ctx.scale(s, s);

    const underlayImg = this.underlayCache.get(scene.underlayUrl);
    renderPaperSheetAndGuidesLayer(ctx, scene, pw, ph, s, underlayImg);

    const paths = scene.paths;
    const liveProgress = telemetryBus.latestProgress;
    const isLiveRunning =
      (scene.machineState === 'RUNNING' ||
        scene.machineState === 'HOLDING' ||
        scene.machineState === 'PAUSED' ||
        scene.machineState === 'PEN_CHANGE') &&
      liveProgress !== null &&
      liveProgress.page_index === scene.pageIndex;
    const isPartialMode = isLiveRunning || scene.playbackProgress < 0.999;

    if (paths && paths.vertexCount > 0) {
      const strokeCanvas = this.strokeCache.ensure(paths, s, scene.inkColor, isPartialMode);
      ctx.drawImage(strokeCanvas, 0, 0, pw, ph);
      renderTravelAndBboxLayer(
        ctx,
        scene,
        paths,
        scene.profile.workspace_mm.x,
        scene.profile.workspace_mm.y,
        s,
      );
    }

    const simPenXY = renderProgressStrokesLayer(
      ctx,
      scene,
      paths,
      s,
      liveProgress,
      isLiveRunning,
      isPartialMode,
      this.penTrail,
    );

    if (scene.placedBlocks.length > 0) {
      renderPlacedObjectsLayer(
        ctx,
        scene.placedBlocks,
        scene.selectedObjectId,
        this.hoveredObjectId,
        this.imageDrag,
        s,
      );
    }

    if (scene.showMissingGlyphs && scene.missingGlyphs.length > 0) {
      renderMissingGlyphsLayer(ctx, scene.missingGlyphs, scene.activeMissingGlyphId, s);
    }

    if (this.pulseHighlight) {
      const keepAnim = renderPulseHighlightLayer(ctx, this.pulseHighlight, s);
      if (keepAnim) {
        this.scheduleRender();
      } else {
        this.pulseHighlight = null;
      }
    }

    if (scene.config.mode === 'overlay' && this.overlayBoxes.length > 0) {
      renderOverlayBoxesLayer(
        ctx,
        this.overlayBoxes,
        scene.selectedBlockId,
        this.hoveredBlockId,
        this.dragBlock,
        s,
      );
    }

    if (scene.showRegions && this.activeRegions.length > 0) {
      renderWritingRegionsLayer(
        ctx,
        this.activeRegions,
        scene.selectedRegionId,
        this.hoveredRegionId,
        this.regionDrag,
        s,
      );
    }

    if (this.drawDraft) {
      renderDrawDraftLayer(ctx, this.drawDraft, s);
    }

    renderPenCrosshairLayer(ctx, scene.machineState, telemetryBus.latestStatus, simPenXY, s);

    ctx.restore();

    renderRulers({
      topCanvas: this.topRuler,
      leftCanvas: this.leftRuler,
      scalePxPerMm: s,
      offsetX: this.panX,
      offsetY: this.panY,
      cursorMm: this.cursorMm,
      theme: scene.theme,
    });
  }
}
