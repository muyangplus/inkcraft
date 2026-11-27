import type { DecodedPagePaths } from './f32PathDecoder';

const MAX_CANVAS_DIM = 4096;

/**
 * Offscreen raster cache for Layer 2 single-line ink strokes.
 * Keys by unique path object identity + DPR + zoom bucket + ink state, and caps dimensions at 4096px.
 */
export class StrokeLayerCache {
  private canvas: HTMLCanvasElement;
  private cacheKey = '';
  private pathIds = new WeakMap<DecodedPagePaths, number>();
  private nextPathId = 1;

  constructor() {
    this.canvas = document.createElement('canvas');
  }

  private getPathId(paths: DecodedPagePaths): number {
    let id = this.pathIds.get(paths);
    if (id === undefined) {
      id = this.nextPathId++;
      this.pathIds.set(paths, id);
    }
    return id;
  }

  ensure(
    paths: DecodedPagePaths,
    scalePxPerMm: number,
    inkColor: string,
    dimmed: boolean,
  ): HTMLCanvasElement {
    const bucket = scalePxPerMm < 2.2 ? 2.2 : scalePxPerMm < 4.5 ? 4.5 : 8.0;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    let cacheScale = bucket * dpr;

    const rawW = Math.max(1, Math.ceil(paths.widthMm * cacheScale));
    const rawH = Math.max(1, Math.ceil(paths.heightMm * cacheScale));
    if (Math.max(rawW, rawH) > MAX_CANVAS_DIM) {
      cacheScale *= MAX_CANVAS_DIM / Math.max(rawW, rawH);
    }

    const cw = Math.max(1, Math.min(MAX_CANVAS_DIM, Math.ceil(paths.widthMm * cacheScale)));
    const ch = Math.max(1, Math.min(MAX_CANVAS_DIM, Math.ceil(paths.heightMm * cacheScale)));
    const key = `${this.getPathId(paths)}|${dpr}|${bucket}|${cw}x${ch}|${inkColor}|${dimmed ? 'dim' : 'full'}`;

    if (this.cacheKey === key) return this.canvas;
    this.cacheKey = key;

    this.canvas.width = cw;
    this.canvas.height = ch;

    const ctx = this.canvas.getContext('2d');
    if (!ctx) return this.canvas;

    ctx.clearRect(0, 0, cw, ch);
    ctx.save();
    ctx.scale(cacheScale, cacheScale);
    ctx.strokeStyle = dimmed ? 'rgba(71, 85, 105, 0.25)' : inkColor;
    ctx.lineWidth = Math.max(0.36, 0.9 / bucket);
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    const { data, vertexCount } = paths;
    ctx.beginPath();
    let hasOpen = false;
    for (let i = 0; i < vertexCount; i++) {
      const b = i * 3;
      const x = data[b];
      const y = data[b + 1];
      const flag = data[b + 2];
      if (flag === 0) {
        ctx.moveTo(x, y);
        hasOpen = true;
      } else if (!hasOpen) {
        ctx.moveTo(x, y);
        hasOpen = true;
      } else {
        ctx.lineTo(x, y);
      }
    }
    ctx.stroke();
    ctx.restore();
    return this.canvas;
  }

  destroy(): void {
    this.cacheKey = '';
    this.canvas.width = 0;
    this.canvas.height = 0;
  }
}
