import type { DocBlock, LayoutConfig } from '../api/types';

export interface OverlayTransformSpec {
  cx: number;
  cy: number;
  scale: number;
  cosR: number;
  sinR: number;
  offsetX: number;
  offsetY: number;
}

export interface OverlayBlockBox {
  block: DocBlock;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  localX0: number;
  localY0: number;
  localX1: number;
  localY1: number;
  corners: [number, number][];
  transform: OverlayTransformSpec;
  enabled: boolean;
  nudgeX: number;
  nudgeY: number;
  area: number;
}

/** Build the exact forward/inverse overlay transform matching backend `finalize.py`. */
export function makeOverlayTransformSpec(
  overlayCfg: LayoutConfig['overlay'],
  pageWidthMm: number,
  pageHeightMm: number,
): OverlayTransformSpec {
  const scale = overlayCfg.scale && overlayCfg.scale > 1e-4 ? overlayCfg.scale : 1;
  const rad = ((overlayCfg.rotation_deg ?? 0) * Math.PI) / 180;
  return {
    cx: pageWidthMm * 0.5,
    cy: pageHeightMm * 0.5,
    scale,
    cosR: Math.cos(rad),
    sinR: Math.sin(rad),
    offsetX: overlayCfg.offset_mm?.x ?? 0,
    offsetY: overlayCfg.offset_mm?.y ?? 0,
  };
}

/** Apply `T = Translate(offset) * Rotate(rot, center) * Scale(scale, center)` to local coords. */
export function overlayLocalToWorld(
  spec: OverlayTransformSpec,
  lx: number,
  ly: number,
): [number, number] {
  const dx = lx - spec.cx;
  const dy = ly - spec.cy;
  const wx = spec.cx + spec.offsetX + spec.scale * (dx * spec.cosR - dy * spec.sinR);
  const wy = spec.cy + spec.offsetY + spec.scale * (dx * spec.sinR + dy * spec.cosR);
  return [wx, wy];
}

/** Inverse-transform world mm coords back into pre-global-transform page coords. */
export function worldToOverlayLocal(
  spec: OverlayTransformSpec,
  wx: number,
  wy: number,
): [number, number] {
  const ux = (wx - (spec.cx + spec.offsetX)) / spec.scale;
  const uy = (wy - (spec.cy + spec.offsetY)) / spec.scale;
  const lx = spec.cx + (ux * spec.cosR + uy * spec.sinR);
  const ly = spec.cy + (-ux * spec.sinR + uy * spec.cosR);
  return [lx, ly];
}

/** Convert a world-space drag delta into pre-transform `nudge_mm` delta. */
export function worldDeltaToOverlayNudge(
  overlayCfg: LayoutConfig['overlay'],
  dxWorld: number,
  dyWorld: number,
): [number, number] {
  const scale = overlayCfg.scale && overlayCfg.scale > 1e-4 ? overlayCfg.scale : 1;
  const rad = ((overlayCfg.rotation_deg ?? 0) * Math.PI) / 180;
  const cosR = Math.cos(rad);
  const sinR = Math.sin(rad);
  return [
    (dxWorld * cosR + dyWorld * sinR) / scale,
    (-dxWorld * sinR + dyWorld * cosR) / scale,
  ];
}

/**
 * Compute page-space overlay boxes for blocks: per-block `nudge_mm` is applied first in local
 * coordinates, followed by global `scale`, `rotation_deg`, and `offset_mm` around page center.
 */
export function computeOverlayBoxes(
  blocks: DocBlock[],
  pageIndex: number,
  overlayCfg: LayoutConfig['overlay'],
  pageWidthMm: number,
  pageHeightMm: number,
): OverlayBlockBox[] {
  const spec = makeOverlayTransformSpec(overlayCfg, pageWidthMm, pageHeightMm);
  const boxes: OverlayBlockBox[] = [];

  for (const b of blocks) {
    if ((b.page_index ?? 0) !== pageIndex) continue;
    if (!b.bbox_mm || b.bbox_mm.length !== 4) continue;
    if (b.type === 'discarded') continue;

    const override = overlayCfg.blocks[b.block_id];
    const enabled = override ? override.enabled : true;
    const nx = override?.nudge_mm?.x ?? 0;
    const ny = override?.nudge_mm?.y ?? 0;

    const localX0 = b.bbox_mm[0] + nx;
    const localY0 = b.bbox_mm[1] + ny;
    const localX1 = b.bbox_mm[2] + nx;
    const localY1 = b.bbox_mm[3] + ny;

    const c00 = overlayLocalToWorld(spec, localX0, localY0);
    const c10 = overlayLocalToWorld(spec, localX1, localY0);
    const c11 = overlayLocalToWorld(spec, localX1, localY1);
    const c01 = overlayLocalToWorld(spec, localX0, localY1);
    const corners = [c00, c10, c11, c01];

    const x0 = Math.min(c00[0], c10[0], c11[0], c01[0]);
    const y0 = Math.min(c00[1], c10[1], c11[1], c01[1]);
    const x1 = Math.max(c00[0], c10[0], c11[0], c01[0]);
    const y1 = Math.max(c00[1], c10[1], c11[1], c01[1]);
    const area = Math.max(0.01, (localX1 - localX0) * (localY1 - localY0) * spec.scale * spec.scale);

    boxes.push({
      block: b,
      x0,
      y0,
      x1,
      y1,
      localX0,
      localY0,
      localX1,
      localY1,
      corners,
      transform: spec,
      enabled,
      nudgeX: nx,
      nudgeY: ny,
      area,
    });
  }
  return boxes;
}

/**
 * Hit-test world coordinate (mm) against overlay blocks using the inverse overlay transform,
 * prioritizing smaller boxes on overlap.
 */
export function hitTestOverlayBlocks(
  boxes: OverlayBlockBox[],
  xMm: number,
  yMm: number,
  padMm = 1.5,
): OverlayBlockBox | null {
  let best: OverlayBlockBox | null = null;
  for (let i = boxes.length - 1; i >= 0; i--) {
    const b = boxes[i];
    const [lx, ly] = worldToOverlayLocal(b.transform, xMm, yMm);
    const localPad = padMm / Math.max(0.1, b.transform.scale);
    if (
      lx >= b.localX0 - localPad &&
      lx <= b.localX1 + localPad &&
      ly >= b.localY0 - localPad &&
      ly <= b.localY1 + localPad
    ) {
      if (!best || b.area < best.area) {
        best = b;
      }
    }
  }
  return best;
}
