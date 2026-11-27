import type { WritingRegion } from '../api/types';
import type { RegionRect, ResizeHandle } from './stageTypes';

export function getRegionHandles(r: RegionRect): Array<{
  id: ResizeHandle;
  x: number;
  y: number;
}> {
  const x0 = r.x_mm;
  const y0 = r.y_mm;
  const x1 = r.x_mm + r.width_mm;
  const y1 = r.y_mm + r.height_mm;
  const xm = (x0 + x1) * 0.5;
  const ym = (y0 + y1) * 0.5;
  return [
    { id: 'nw', x: x0, y: y0 },
    { id: 'n', x: xm, y: y0 },
    { id: 'ne', x: x1, y: y0 },
    { id: 'e', x: x1, y: ym },
    { id: 'se', x: x1, y: y1 },
    { id: 's', x: xm, y: y1 },
    { id: 'sw', x: x0, y: y1 },
    { id: 'w', x: x0, y: ym },
  ];
}

export function hitTestRegionHandle(
  wx: number,
  wy: number,
  region: RegionRect,
  scalePxPerMm: number,
): ResizeHandle | null {
  const tol = Math.max(2.0, 7.0 / Math.max(0.5, scalePxPerMm));
  for (const h of getRegionHandles(region)) {
    if (Math.abs(wx - h.x) <= tol && Math.abs(wy - h.y) <= tol) {
      return h.id;
    }
  }
  return null;
}

export function hitTestRegionBody(
  regions: WritingRegion[],
  wx: number,
  wy: number,
): WritingRegion | null {
  // Prefer smallest area region when nested/overlapping
  const hits = regions.filter(
    (r) => wx >= r.x_mm && wx <= r.x_mm + r.width_mm && wy >= r.y_mm && wy <= r.y_mm + r.height_mm,
  );
  if (hits.length === 0) return null;
  hits.sort((a, b) => a.width_mm * a.height_mm - b.width_mm * b.height_mm);
  return hits[0];
}
