export interface DecodedPagePaths {
  /** Raw interleaved [x0, y0, flag0, x1, y1, flag1, ...] */
  data: Float32Array;
  /** Number of vertices (data.length / 3) */
  vertexCount: number;
  /** Number of draw segments (vertices with flag === 1 or 2) */
  segCount: number;
  /** Number of pen-down strokes */
  strokeCount: number;
  /** Starting vertex index in `data` (multiply by 3 for float index) for each stroke */
  strokeOffsets: Uint32Array;
  /** Ending vertex index (inclusive) for each stroke */
  strokeEnds: Uint32Array;
  /** Page dimensions in mm */
  widthMm: number;
  heightMm: number;
  /** Bounding box [x0, y0, x1, y1] in mm */
  bbox: [number, number, number, number];
}

/**
 * Zero-copy Float32Array binary path decoder for Contract v1 `format=f32`.
 * Flags:
 *   0 = travel-to (pen up moveTo, starts a new stroke)
 *   1 = draw-to (pen down lineTo)
 *   2 = draw-to & stroke boundary (end of stroke)
 */
export function decodeF32Paths(
  buffer: ArrayBuffer,
  meta?: {
    widthMm?: number;
    heightMm?: number;
    bbox?: [number, number, number, number];
  },
): DecodedPagePaths {
  const usableBytes = buffer.byteLength - (buffer.byteLength % 12);
  const data = new Float32Array(buffer, 0, usableBytes / 4);
  const vertexCount = Math.floor(data.length / 3);

  const offsetsList: number[] = [];
  const endsList: number[] = [];

  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  let segCount = 0;
  let inStroke = false;
  let currentStart = 0;

  for (let i = 0; i < vertexCount; i++) {
    const base = i * 3;
    const x = data[base];
    const y = data[base + 1];
    const flag = data[base + 2];

    if (flag === 0) {
      if (inStroke) {
        offsetsList.push(currentStart);
        endsList.push(i - 1);
      }
      currentStart = i;
      inStroke = true;
    } else {
      if (!inStroke) {
        currentStart = Math.max(0, i - 1);
        inStroke = true;
      }
      segCount += 1;
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;

      // Also include the stroke start vertex in bbox
      if (i > 0 && data[(i - 1) * 3 + 2] === 0) {
        const px = data[(i - 1) * 3];
        const py = data[(i - 1) * 3 + 1];
        if (px < minX) minX = px;
        if (py < minY) minY = py;
        if (px > maxX) maxX = px;
        if (py > maxY) maxY = py;
      }

      if (flag >= 2) {
        offsetsList.push(currentStart);
        endsList.push(i);
        inStroke = false;
      }
    }
  }

  if (inStroke && vertexCount > currentStart + 1) {
    offsetsList.push(currentStart);
    endsList.push(vertexCount - 1);
  }

  const hasHeaderBbox =
    meta?.bbox &&
    (meta.bbox[2] > meta.bbox[0] || meta.bbox[3] > meta.bbox[1]);

  const bbox: [number, number, number, number] = hasHeaderBbox
    ? meta!.bbox!
    : Number.isFinite(minX)
      ? [minX, minY, maxX, maxY]
      : [0, 0, 0, 0];

  return {
    data,
    vertexCount,
    segCount,
    strokeCount: offsetsList.length,
    strokeOffsets: Uint32Array.from(offsetsList),
    strokeEnds: Uint32Array.from(endsList),
    widthMm: meta?.widthMm ?? 210,
    heightMm: meta?.heightMm ?? 297,
    bbox,
  };
}
