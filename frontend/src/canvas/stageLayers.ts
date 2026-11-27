import type {
  JobProgressData,
  MachineState,
  MachineStatusData,
  MissingGlyphBox,
  PlacedBlockBox,
  WritingRegion,
} from '../api/types';
import type { DecodedPagePaths } from './f32PathDecoder';
import { overlayLocalToWorld, type OverlayBlockBox } from './overlayHitTest';
import { getRegionHandles } from './regionGeometry';
import type {
  DragBlockState,
  DrawDraftState,
  PlacedImageDragState,
  PulseHighlightState,
  RegionDragState,
  StageSceneSnapshot,
} from './stageTypes';

export function renderMatBackgroundLayer(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  panX: number,
  panY: number,
  s: number,
  theme: 'dark' | 'light',
): void {
  ctx.fillStyle = theme === 'dark' ? '#0B0E14' : '#E8ECF2';
  ctx.fillRect(0, 0, w, h);

  const grid10 = 10 * s;
  if (grid10 < 6) return;

  const startX = Math.floor(-panX / (10 * s)) * 10;
  const endX = Math.ceil((w - panX) / (10 * s)) * 10;
  const startY = Math.floor(-panY / (10 * s)) * 10;
  const endY = Math.ceil((h - panY) / (10 * s)) * 10;

  ctx.strokeStyle = theme === 'dark' ? '#131823' : '#DCE2EC';
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let mm = startX; mm <= endX; mm += 10) {
    const x = Math.round(mm * s + panX) + 0.5;
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
  }
  for (let mm = startY; mm <= endY; mm += 10) {
    const y = Math.round(mm * s + panY) + 0.5;
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
  }
  ctx.stroke();

  ctx.strokeStyle = theme === 'dark' ? '#1B2230' : '#CFD7E4';
  ctx.beginPath();
  for (let mm = Math.floor(startX / 50) * 50; mm <= endX; mm += 50) {
    const x = Math.round(mm * s + panX) + 0.5;
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
  }
  for (let mm = Math.floor(startY / 50) * 50; mm <= endY; mm += 50) {
    const y = Math.round(mm * s + panY) + 0.5;
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
  }
  ctx.stroke();
}

export function renderPaperSheetAndGuidesLayer(
  ctx: CanvasRenderingContext2D,
  scene: StageSceneSnapshot,
  pw: number,
  ph: number,
  s: number,
  underlayImg: HTMLImageElement | null,
): void {
  // Archival paper sheet with elevation shadow
  ctx.save();
  ctx.shadowColor = scene.theme === 'dark' ? 'rgba(0, 0, 0, 0.56)' : 'rgba(15, 23, 42, 0.14)';
  ctx.shadowBlur = 32;
  ctx.shadowOffsetY = 10;
  ctx.fillStyle = scene.theme === 'dark' ? '#FAF8F2' : '#FFFEFA';
  ctx.fillRect(0, 0, pw, ph);
  ctx.restore();

  // Layer 1: Background or PDF underlay
  if (scene.showUnderlay && underlayImg) {
    const ur = scene.underlayRectMm;
    ctx.save();
    ctx.globalAlpha = Math.max(0, Math.min(1, scene.underlayOpacity));
    ctx.drawImage(underlayImg, ur.x, ur.y, ur.w, ur.h);
    ctx.restore();
  }

  // Crisp paper edge
  ctx.strokeStyle = scene.theme === 'dark' ? 'rgba(148, 163, 184, 0.25)' : 'rgba(148, 163, 184, 0.48)';
  ctx.lineWidth = 1 / s;
  ctx.strokeRect(0, 0, pw, ph);

  // Reflow margins guide
  const margins = scene.activeMargins;
  if (scene.config.mode === 'reflow') {
    ctx.save();
    ctx.strokeStyle = 'rgba(79, 70, 229, 0.22)';
    ctx.lineWidth = 1 / s;
    ctx.setLineDash([4 / s, 4 / s]);
    ctx.strokeRect(
      margins.left,
      margins.top,
      Math.max(0, pw - margins.left - margins.right),
      Math.max(0, ph - margins.top - margins.bottom),
    );
    ctx.restore();
  }

  // Software ruled guides when no visual page background covers them
  const drawingBgUnderlay = Boolean(scene.hasPageBackground && scene.showUnderlay && underlayImg);
  if (!drawingBgUnderlay && scene.showRuled && scene.activeRuled.style !== 'none') {
    const pitch = Math.max(4, scene.activeRuled.pitch_mm || 9);
    ctx.save();
    ctx.strokeStyle = 'rgba(148, 163, 184, 0.32)';
    ctx.lineWidth = 0.75 / s;
    ctx.beginPath();
    const x0 = margins.left;
    const x1 = pw - margins.right;
    const y0 = margins.top;
    const y1 = ph - margins.bottom;
    for (let y = y0 + pitch; y <= y1 + 0.01; y += pitch) {
      ctx.moveTo(x0, y);
      ctx.lineTo(x1, y);
    }
    if (scene.activeRuled.style === 'grid') {
      for (let x = x0; x <= x1 + 0.01; x += pitch) {
        ctx.moveTo(x, y0);
        ctx.lineTo(x, y1);
      }
    }
    ctx.stroke();
    ctx.restore();
  }

  // Machine physical workspace bounds
  const wsX = scene.profile.workspace_mm.x;
  const wsY = scene.profile.workspace_mm.y;
  ctx.save();
  ctx.strokeStyle = 'rgba(16, 185, 129, 0.36)';
  ctx.lineWidth = 1.2 / s;
  ctx.setLineDash([6 / s, 4 / s]);
  ctx.strokeRect(0, 0, wsX, wsY);
  ctx.restore();
}

export function renderTravelAndBboxLayer(
  ctx: CanvasRenderingContext2D,
  scene: StageSceneSnapshot,
  paths: DecodedPagePaths,
  wsX: number,
  wsY: number,
  s: number,
): void {
  if (paths.vertexCount > 0 && scene.showTravel) {
    ctx.save();
    ctx.strokeStyle = 'rgba(217, 119, 6, 0.56)';
    ctx.lineWidth = Math.max(0.22, 0.85 / s);
    ctx.setLineDash([2.2, 2.2]);
    ctx.beginPath();
    const { data, vertexCount } = paths;
    let prevX = 0;
    let prevY = 0;
    for (let i = 0; i < vertexCount; i++) {
      const b = i * 3;
      const x = data[b];
      const y = data[b + 1];
      const flag = data[b + 2];
      if (flag === 0 && i > 0) {
        ctx.moveTo(prevX, prevY);
        ctx.lineTo(x, y);
      }
      prevX = x;
      prevY = y;
    }
    ctx.stroke();
    ctx.restore();
  }

  if (scene.showBbox) {
    const [bx0, by0, bx1, by1] = paths.bbox;
    if (bx1 > bx0 && by1 > by0) {
      const oob = bx0 < 0 || by0 < 0 || bx1 > wsX || by1 > wsY;
      ctx.save();
      ctx.strokeStyle = oob ? '#E11D48' : '#0891B2';
      ctx.lineWidth = (scene.machineState === 'FRAMING' ? 2.2 : 1.25) / s;
      ctx.setLineDash([5 / s, 3 / s]);
      ctx.strokeRect(bx0, by0, bx1 - bx0, by1 - by0);

      if (oob) {
        ctx.fillStyle = 'rgba(225, 29, 72, 0.08)';
        ctx.fillRect(bx0, by0, bx1 - bx0, by1 - by0);
      }

      ctx.setLineDash([]);
      ctx.font = `600 ${10 / s}px "JetBrains Mono", monospace`;
      ctx.fillStyle = oob ? '#E11D48' : '#0891B2';
      const label = `${(bx1 - bx0).toFixed(1)} × ${(by1 - by0).toFixed(1)} mm${oob ? ' [超出行程!]' : ''}`;
      ctx.fillText(label, bx0, Math.max(4, by0 - 2.2));
      ctx.restore();
    }
  }
}

export function renderProgressStrokesLayer(
  ctx: CanvasRenderingContext2D,
  scene: StageSceneSnapshot,
  paths: DecodedPagePaths | null,
  s: number,
  liveProgress: JobProgressData | null,
  isLiveRunning: boolean,
  isPartialMode: boolean,
  penTrail: Array<{ x: number; y: number }>,
): { x: number; y: number; down: boolean } | null {
  let simPenXY: { x: number; y: number; down: boolean } | null = null;

  if (paths && paths.strokeCount > 0 && isPartialMode) {
    const targetStroke = isLiveRunning
      ? Math.min(paths.strokeCount, liveProgress!.stroke_index + 1)
      : Math.round(scene.playbackProgress * paths.strokeCount);

    if (targetStroke > 0) {
      const { data, strokeOffsets, strokeEnds } = paths;
      const completedCount = Math.max(0, targetStroke - 1);

      if (completedCount > 0) {
        ctx.save();
        ctx.strokeStyle = scene.inkColor;
        ctx.lineWidth = Math.max(0.4, 0.85 / s);
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        ctx.beginPath();
        for (let si = 0; si < completedCount; si++) {
          const start = strokeOffsets[si];
          const end = strokeEnds[si];
          ctx.moveTo(data[start * 3], data[start * 3 + 1]);
          for (let vi = start + 1; vi <= end; vi++) {
            ctx.lineTo(data[vi * 3], data[vi * 3 + 1]);
          }
        }
        ctx.stroke();
        ctx.restore();
      }

      const activeIdx = Math.min(paths.strokeCount - 1, targetStroke - 1);
      const aStart = strokeOffsets[activeIdx];
      const aEnd = strokeEnds[activeIdx];
      ctx.save();
      ctx.strokeStyle = '#4F46E5';
      ctx.lineWidth = Math.max(0.55, 1.35 / s);
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.beginPath();
      ctx.moveTo(data[aStart * 3], data[aStart * 3 + 1]);
      for (let vi = aStart + 1; vi <= aEnd; vi++) {
        ctx.lineTo(data[vi * 3], data[vi * 3 + 1]);
      }
      ctx.stroke();
      ctx.restore();

      simPenXY = {
        x: data[aEnd * 3],
        y: data[aEnd * 3 + 1],
        down: true,
      };
    }
  }

  if (penTrail.length > 1) {
    ctx.save();
    ctx.strokeStyle = 'rgba(8, 145, 178, 0.78)';
    ctx.lineWidth = 2.2 / s;
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(penTrail[0].x, penTrail[0].y);
    for (let i = 1; i < penTrail.length; i++) {
      ctx.lineTo(penTrail[i].x, penTrail[i].y);
    }
    ctx.stroke();
    ctx.restore();
  }

  return simPenXY;
}

export function renderOverlayBoxesLayer(
  ctx: CanvasRenderingContext2D,
  overlayBoxes: OverlayBlockBox[],
  selectedBlockId: string | null,
  hoveredBlockId: string | null,
  dragBlock: DragBlockState | null,
  s: number,
): void {
  for (const box of overlayBoxes) {
    const isSelected = box.block.block_id === selectedBlockId;
    const isHovered = box.block.block_id === hoveredBlockId;
    const isDragging = dragBlock?.blockId === box.block.block_id;

    let corners = box.corners;
    if (isDragging && dragBlock) {
      const dnx = dragBlock.curNudgeX - dragBlock.origNudgeX;
      const dny = dragBlock.curNudgeY - dragBlock.origNudgeY;
      const lx0 = box.localX0 + dnx;
      const ly0 = box.localY0 + dny;
      const lx1 = box.localX1 + dnx;
      const ly1 = box.localY1 + dny;
      corners = [
        overlayLocalToWorld(box.transform, lx0, ly0),
        overlayLocalToWorld(box.transform, lx1, ly0),
        overlayLocalToWorld(box.transform, lx1, ly1),
        overlayLocalToWorld(box.transform, lx0, ly1),
      ];
    }

    ctx.save();
    if (isSelected) {
      ctx.strokeStyle = '#0284C7';
      ctx.fillStyle = 'rgba(2, 132, 199, 0.10)';
      ctx.lineWidth = 1.6 / s;
      ctx.beginPath();
      ctx.moveTo(corners[0][0], corners[0][1]);
      for (let i = 1; i < corners.length; i++) {
        ctx.lineTo(corners[i][0], corners[i][1]);
      }
      ctx.closePath();
      ctx.fill();
      ctx.stroke();

      const hs = 4.5 / s;
      ctx.fillStyle = '#0284C7';
      for (const [cx, cy] of corners) {
        ctx.fillRect(cx - hs * 0.5, cy - hs * 0.5, hs, hs);
      }

      const nx = isDragging && dragBlock ? dragBlock.curNudgeX : box.nudgeX;
      const ny = isDragging && dragBlock ? dragBlock.curNudgeY : box.nudgeY;
      ctx.font = `600 ${10 / s}px "JetBrains Mono", monospace`;
      ctx.fillStyle = '#0284C7';
      const minX = Math.min(...corners.map((c) => c[0]));
      const minY = Math.min(...corners.map((c) => c[1]));
      ctx.fillText(
        `${box.block.block_id} (${nx >= 0 ? '+' : ''}${nx.toFixed(1)}, ${ny >= 0 ? '+' : ''}${ny.toFixed(1)})`,
        minX,
        Math.max(4, minY - 1.5),
      );
    } else if (isHovered || !box.enabled) {
      ctx.strokeStyle = !box.enabled
        ? 'rgba(148, 163, 184, 0.5)'
        : 'rgba(2, 132, 199, 0.65)';
      ctx.lineWidth = 1 / s;
      ctx.setLineDash([3 / s, 3 / s]);
      ctx.beginPath();
      ctx.moveTo(corners[0][0], corners[0][1]);
      for (let i = 1; i < corners.length; i++) {
        ctx.lineTo(corners[i][0], corners[i][1]);
      }
      ctx.closePath();
      ctx.stroke();
    }
    ctx.restore();
  }
}

export function renderWritingRegionsLayer(
  ctx: CanvasRenderingContext2D,
  activeRegions: WritingRegion[],
  selectedRegionId: string | null,
  hoveredRegionId: string | null,
  regionDrag: RegionDragState | null,
  s: number,
): void {
  for (const reg of activeRegions) {
    const isSel = reg.region_id === selectedRegionId;
    const isHov = reg.region_id === hoveredRegionId;
    const rect =
      regionDrag && regionDrag.regionId === reg.region_id
        ? regionDrag.curRect
        : {
            x_mm: reg.x_mm,
            y_mm: reg.y_mm,
            width_mm: reg.width_mm,
            height_mm: reg.height_mm,
          };

    const strokeCol = !reg.enabled
      ? 'rgba(148, 163, 184, 0.72)'
      : reg.role === 'body'
        ? '#0D9488'
        : '#4F46E5';
    const fillCol = !reg.enabled
      ? 'rgba(148, 163, 184, 0.04)'
      : reg.role === 'body'
        ? isSel
          ? 'rgba(13, 148, 136, 0.11)'
          : 'rgba(13, 148, 136, 0.05)'
        : isSel
          ? 'rgba(79, 70, 229, 0.12)'
          : 'rgba(79, 70, 229, 0.05)';

    ctx.save();
    ctx.fillStyle = fillCol;
    ctx.fillRect(rect.x_mm, rect.y_mm, rect.width_mm, rect.height_mm);
    ctx.strokeStyle = strokeCol;
    ctx.lineWidth = (isSel ? 1.85 : isHov ? 1.45 : 1.05) / s;
    if (!isSel) {
      ctx.setLineDash([4 / s, 3 / s]);
    }
    ctx.strokeRect(rect.x_mm, rect.y_mm, rect.width_mm, rect.height_mm);
    ctx.setLineDash([]);

    const label = reg.role === 'body' ? `正文#${reg.order + 1} · ${reg.name}` : reg.name;
    ctx.font = `700 ${10 / s}px "Plus Jakarta Sans", "Noto Sans SC", sans-serif`;
    const textW = ctx.measureText(label).width;
    const tagH = 14 / s;
    const tagY = rect.y_mm >= tagH + 2 / s ? rect.y_mm - tagH - 1 / s : rect.y_mm + 1 / s;
    ctx.fillStyle = strokeCol;
    ctx.fillRect(rect.x_mm, tagY, textW + 8 / s, tagH);
    ctx.fillStyle = '#FFFFFF';
    ctx.textBaseline = 'middle';
    ctx.fillText(label, rect.x_mm + 4 / s, tagY + tagH * 0.5);

    if (isSel) {
      const hs = 6 / s;
      for (const h of getRegionHandles(rect)) {
        ctx.fillStyle = '#FFFFFF';
        ctx.fillRect(h.x - hs * 0.5, h.y - hs * 0.5, hs, hs);
        ctx.strokeStyle = strokeCol;
        ctx.lineWidth = 1.4 / s;
        ctx.strokeRect(h.x - hs * 0.5, h.y - hs * 0.5, hs, hs);
      }

      const dimsLabel = `${rect.x_mm.toFixed(1)}, ${rect.y_mm.toFixed(1)} · ${rect.width_mm.toFixed(1)}×${rect.height_mm.toFixed(1)} mm`;
      ctx.font = `600 ${9.5 / s}px "JetBrains Mono", monospace`;
      ctx.fillStyle = strokeCol;
      ctx.textBaseline = 'top';
      ctx.fillText(dimsLabel, rect.x_mm, rect.y_mm + rect.height_mm + 2.5 / s);
    }
    ctx.restore();
  }
}

export function renderDrawDraftLayer(
  ctx: CanvasRenderingContext2D,
  drawDraft: DrawDraftState,
  s: number,
): void {
  const x0 = Math.min(drawDraft.startX, drawDraft.curX);
  const y0 = Math.min(drawDraft.startY, drawDraft.curY);
  const dw = Math.abs(drawDraft.curX - drawDraft.startX);
  const dh = Math.abs(drawDraft.curY - drawDraft.startY);
  ctx.save();
  ctx.fillStyle = 'rgba(79, 70, 229, 0.14)';
  ctx.fillRect(x0, y0, dw, dh);
  ctx.strokeStyle = '#4F46E5';
  ctx.lineWidth = 1.8 / s;
  ctx.setLineDash([5 / s, 3 / s]);
  ctx.strokeRect(x0, y0, dw, dh);
  ctx.setLineDash([]);
  ctx.font = `700 ${10.5 / s}px "JetBrains Mono", monospace`;
  ctx.fillStyle = '#4F46E5';
  ctx.fillText(`${dw.toFixed(1)} × ${dh.toFixed(1)} mm`, x0, Math.max(4, y0 - 4 / s));
  ctx.restore();
}

export function renderPenCrosshairLayer(
  ctx: CanvasRenderingContext2D,
  machineState: MachineState,
  status: MachineStatusData,
  simPenXY: { x: number; y: number; down: boolean } | null,
  s: number,
): void {
  const penPos =
    machineState !== 'DISCONNECTED'
      ? {
          // page_pos is machine WPos mapped back to paper coordinates (handles
          // negative-Y / right-origin machines such as 奎享 "左上" setups).
          x: status.page_pos?.x ?? status.wpos.x,
          y: status.page_pos?.y ?? status.wpos.y,
          down: status.pen === 'down',
        }
      : simPenXY;
  if (!penPos) return;

  const r = 7 / s;
  ctx.save();
  const color =
    machineState === 'FRAMING'
      ? '#0891B2'
      : machineState === 'ESTOPPED' || machineState === 'ALARM'
        ? '#E11D48'
        : penPos.down
          ? '#4F46E5'
          : '#10B981';

  ctx.strokeStyle = color;
  ctx.lineWidth = 1.4 / s;
  ctx.beginPath();
  ctx.moveTo(penPos.x - r * 1.6, penPos.y);
  ctx.lineTo(penPos.x + r * 1.6, penPos.y);
  ctx.moveTo(penPos.x, penPos.y - r * 1.6);
  ctx.lineTo(penPos.x, penPos.y + r * 1.6);
  ctx.stroke();

  ctx.beginPath();
  ctx.arc(penPos.x, penPos.y, r, 0, Math.PI * 2);
  ctx.fillStyle = penPos.down ? 'rgba(79, 70, 229, 0.22)' : 'rgba(16, 185, 129, 0.14)';
  ctx.fill();
  ctx.stroke();

  ctx.beginPath();
  ctx.arc(penPos.x, penPos.y, 2.2 / s, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();
  ctx.restore();
}

export function renderPlacedObjectsLayer(
  ctx: CanvasRenderingContext2D,
  placedBlocks: PlacedBlockBox[],
  selectedObjectId: string | null,
  hoveredObjectId: string | null,
  imageDrag: PlacedImageDragState | null,
  s: number,
): void {
  if (!placedBlocks.length) return;

  for (const box of placedBlocks) {
    const isMedia = box.block_type === 'figure' || box.block_type === 'chart';
    const isFormula = box.block_type === 'formula_block' || box.block_type === 'formula_inline';
    const isSelected = box.block_id === selectedObjectId;
    const isHover = box.block_id === hoveredObjectId;

    if (!isMedia && !isFormula) {
      if (!isSelected && !isHover) continue;
      const [x0, y0, x1, y1] = box.bbox_mm;
      const bw = Math.max(4, x1 - x0);
      const bh = Math.max(3, y1 - y0);
      ctx.save();
      ctx.fillStyle = isSelected ? 'rgba(79, 70, 229, 0.08)' : 'rgba(79, 70, 229, 0.035)';
      ctx.strokeStyle = isSelected ? '#4F46E5' : 'rgba(79, 70, 229, 0.55)';
      ctx.lineWidth = (isSelected ? 1.65 : 1.0) / s;
      ctx.setLineDash(isSelected ? [] : [4 / s, 2.8 / s]);
      ctx.fillRect(x0 - 1.2, y0 - 1, bw + 2.4, bh + 2);
      ctx.strokeRect(x0 - 1.2, y0 - 1, bw + 2.4, bh + 2);
      ctx.setLineDash([]);
      if (isSelected) {
        const tag = box.label || box.block_type;
        ctx.font = `700 ${9.5 / s}px sans-serif`;
        ctx.fillStyle = '#4F46E5';
        ctx.textBaseline = 'bottom';
        ctx.fillText(tag.slice(0, 24), x0, Math.max(4, y0 - 2.2 / s));
      }
      ctx.restore();
      continue;
    }

    if (!isSelected && !isHover && !(isMedia && box.render_mode === 'skip')) continue;

    const activeBbox =
      imageDrag && imageDrag.blockId === box.block_id ? imageDrag.curBox : box.bbox_mm;
    const [x0, y0, x1, y1] = activeBbox;
    const bw = Math.max(4, x1 - x0);
    const bh = Math.max(3, y1 - y0);

    ctx.save();
    if (isFormula) {
      ctx.fillStyle = 'rgba(124, 58, 237, 0.08)';
      ctx.strokeStyle = 'rgba(124, 58, 237, 0.85)';
      ctx.lineWidth = 1.3 / s;
      ctx.setLineDash([4 / s, 2.5 / s]);
      ctx.fillRect(x0 - 1, y0 - 1, bw + 2, bh + 2);
      ctx.strokeRect(x0 - 1, y0 - 1, bw + 2, bh + 2);
      ctx.setLineDash([]);
      if (isHover) {
        ctx.font = `600 ${9.5 / s}px sans-serif`;
        ctx.fillStyle = '#7C3AED';
        ctx.textBaseline = 'bottom';
        ctx.fillText('公式 · 双击编辑', x0, Math.max(4, y0 - 2.5 / s));
      }
      ctx.restore();
      continue;
    }

    // Figure / Chart object (selection frame + 8 Word-like resize handles)
    const accent = box.placement === 'float' ? '#0284C7' : '#0EA5E9';
    ctx.fillStyle = isSelected ? 'rgba(2, 132, 199, 0.06)' : 'rgba(14, 165, 233, 0.04)';
    ctx.fillRect(x0, y0, bw, bh);

    ctx.strokeStyle = accent;
    ctx.lineWidth = (isSelected ? 1.7 : 1.1) / s;
    ctx.setLineDash(isSelected ? [] : [4 / s, 3 / s]);
    ctx.strokeRect(x0, y0, bw, bh);
    ctx.setLineDash([]);

    if (box.render_mode === 'skip' && !isSelected) {
      ctx.font = `600 ${9 / s}px sans-serif`;
      ctx.fillStyle = '#64748B';
      ctx.textBaseline = 'middle';
      ctx.fillText('已跳过插图 (点击恢复)', x0 + 3, y0 + bh * 0.5);
    }

    if (isSelected) {
      const handles = getRegionHandles({ x_mm: x0, y_mm: y0, width_mm: bw, height_mm: bh });
      const hs = 6.5 / s;
      for (const h of handles) {
        ctx.fillStyle = '#FFFFFF';
        ctx.fillRect(h.x - hs * 0.5, h.y - hs * 0.5, hs, hs);
        ctx.strokeStyle = accent;
        ctx.lineWidth = 1.4 / s;
        ctx.strokeRect(h.x - hs * 0.5, h.y - hs * 0.5, hs, hs);
      }
      const modeTag = box.placement === 'float' ? '浮动环绕' : '嵌入式';
      const label = `${modeTag} · ${bw.toFixed(1)}×${bh.toFixed(1)} mm`;
      ctx.font = `600 ${9.5 / s}px "JetBrains Mono", sans-serif`;
      ctx.fillStyle = accent;
      ctx.textBaseline = 'top';
      ctx.fillText(label, x0, y1 + 2.5 / s);
    }
    ctx.restore();
  }
}

export function renderMissingGlyphsLayer(
  ctx: CanvasRenderingContext2D,
  missingGlyphs: MissingGlyphBox[],
  activeMissingGlyphId: string | null,
  s: number,
): void {
  if (!missingGlyphs.length) return;

  for (const mg of missingGlyphs) {
    const [x0, y0, x1, y1] = mg.bbox_mm;
    const bw = Math.max(2.4, x1 - x0);
    const bh = Math.max(2.4, y1 - y0);
    const isActive = mg.id === activeMissingGlyphId;

    ctx.save();
    if (isActive) {
      ctx.strokeStyle = 'rgba(220, 38, 38, 0.25)';
      ctx.lineWidth = 4.2 / s;
      ctx.strokeRect(x0 - 0.8, y0 - 0.8, bw + 1.6, bh + 1.6);
    }

    ctx.fillStyle = isActive ? 'rgba(220, 38, 38, 0.16)' : 'rgba(220, 38, 38, 0.075)';
    ctx.fillRect(x0, y0, bw, bh);

    ctx.strokeStyle = isActive ? '#B91C1C' : '#DC2626';
    ctx.lineWidth = (isActive ? 1.8 : 1.15) / s;
    ctx.setLineDash([3.2 / s, 2.0 / s]);
    ctx.strokeRect(x0, y0, bw, bh);
    ctx.setLineDash([]);

    // Subtle non-plotted reference glyph inside dashed frame so missing char is recognizable
    if (mg.char) {
      const refSize = Math.max(1.8, Math.min(bw, bh) * 0.68);
      ctx.font = `500 ${refSize}px "Noto Sans SC", "Microsoft YaHei", sans-serif`;
      ctx.fillStyle = isActive ? 'rgba(185, 28, 28, 0.72)' : 'rgba(220, 38, 38, 0.45)';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(mg.char, x0 + bw * 0.5, y0 + bh * 0.52);
    }

    if (isActive) {
      const tag = `缺字「${mg.char}」`;
      ctx.font = `700 ${9.5 / s}px sans-serif`;
      const tw = ctx.measureText(tag).width + 6 / s;
      const th = 13 / s;
      const ty = Math.max(2, y0 - th - 2 / s);
      ctx.fillStyle = '#DC2626';
      ctx.fillRect(x0, ty, tw, th);
      ctx.fillStyle = '#FFFFFF';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.fillText(tag, x0 + 3 / s, ty + th * 0.52);
    }
    ctx.restore();
  }
}

export function renderPulseHighlightLayer(
  ctx: CanvasRenderingContext2D,
  pulse: PulseHighlightState | null,
  s: number,
): boolean {
  if (!pulse) return false;
  const rem = pulse.untilMs - performance.now();
  if (rem <= 0) return false;
  const t = Math.max(0, Math.min(1, rem / 1250));
  const [x0, y0, x1, y1] = pulse.bboxMm;
  const pad = 1.2 + (1 - t) * 2.2;

  ctx.save();
  ctx.globalAlpha = 0.8 * t;
  ctx.strokeStyle = pulse.color;
  ctx.lineWidth = (2.4 + t * 1.2) / s;
  ctx.strokeRect(
    x0 - pad,
    y0 - pad,
    Math.max(4, x1 - x0) + pad * 2,
    Math.max(3, y1 - y0) + pad * 2,
  );
  ctx.restore();
  return true;
}
