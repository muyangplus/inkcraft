export interface RulerRenderParams {
  topCanvas: HTMLCanvasElement;
  leftCanvas: HTMLCanvasElement;
  scalePxPerMm: number;
  offsetX: number;
  offsetY: number;
  cursorMm: { x: number; y: number } | null;
  theme: 'dark' | 'light';
}

function chooseTickStep(scalePxPerMm: number): { major: number; minor: number } {
  const targetPx = 64;
  const rawMm = targetPx / Math.max(scalePxPerMm, 0.05);
  const candidates = [5, 10, 20, 25, 50, 100];
  let major = 100;
  for (const c of candidates) {
    if (c >= rawMm) {
      major = c;
      break;
    }
  }
  const minor = major >= 50 ? 10 : major >= 20 ? 5 : major >= 10 ? 2 : 1;
  return { major, minor };
}

export function renderRulers(params: RulerRenderParams): void {
  const { topCanvas, leftCanvas, scalePxPerMm, offsetX, offsetY, cursorMm, theme } = params;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const bg = theme === 'dark' ? '#111520' : '#F1F5F9';
  const tickColor = theme === 'dark' ? '#334155' : '#CBD5E1';
  const textColor = theme === 'dark' ? '#64748B' : '#64748B';
  const cursorColor = theme === 'dark' ? '#6366F1' : '#4F46E5';

  const { major, minor } = chooseTickStep(scalePxPerMm);

  // Top Ruler (X axis in mm)
  {
    const w = topCanvas.clientWidth;
    const h = topCanvas.clientHeight;
    if (w > 0 && h > 0) {
      if (topCanvas.width !== Math.round(w * dpr) || topCanvas.height !== Math.round(h * dpr)) {
        topCanvas.width = Math.round(w * dpr);
        topCanvas.height = Math.round(h * dpr);
      }
      const ctx = topCanvas.getContext('2d');
      if (ctx) {
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.fillStyle = bg;
        ctx.fillRect(0, 0, w, h);

        const startMm = Math.floor(-offsetX / scalePxPerMm / minor) * minor;
        const endMm = Math.ceil((w - offsetX) / scalePxPerMm / minor) * minor;

        ctx.strokeStyle = tickColor;
        ctx.fillStyle = textColor;
        ctx.font = '10px "JetBrains Mono", Menlo, monospace';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'top';
        ctx.lineWidth = 1;

        ctx.beginPath();
        for (let mm = startMm; mm <= endMm; mm += minor) {
          const x = Math.round(mm * scalePxPerMm + offsetX) + 0.5;
          if (x < 0 || x > w) continue;
          const isMajor = mm % major === 0;
          const tickH = isMajor ? 10 : 5;
          ctx.moveTo(x, h);
          ctx.lineTo(x, h - tickH);
          if (isMajor) {
            ctx.fillText(String(mm), x + 3, 2);
          }
        }
        ctx.stroke();

        if (cursorMm) {
          const cx = cursorMm.x * scalePxPerMm + offsetX;
          if (cx >= 0 && cx <= w) {
            ctx.strokeStyle = cursorColor;
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.moveTo(cx, 0);
            ctx.lineTo(cx, h);
            ctx.stroke();
          }
        }
      }
    }
  }

  // Left Ruler (Y axis in mm)
  {
    const w = leftCanvas.clientWidth;
    const h = leftCanvas.clientHeight;
    if (w > 0 && h > 0) {
      if (leftCanvas.width !== Math.round(w * dpr) || leftCanvas.height !== Math.round(h * dpr)) {
        leftCanvas.width = Math.round(w * dpr);
        leftCanvas.height = Math.round(h * dpr);
      }
      const ctx = leftCanvas.getContext('2d');
      if (ctx) {
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.fillStyle = bg;
        ctx.fillRect(0, 0, w, h);

        const startMm = Math.floor(-offsetY / scalePxPerMm / minor) * minor;
        const endMm = Math.ceil((h - offsetY) / scalePxPerMm / minor) * minor;

        ctx.strokeStyle = tickColor;
        ctx.fillStyle = textColor;
        ctx.font = '10px "JetBrains Mono", Menlo, monospace';
        ctx.lineWidth = 1;

        ctx.beginPath();
        for (let mm = startMm; mm <= endMm; mm += minor) {
          const y = Math.round(mm * scalePxPerMm + offsetY) + 0.5;
          if (y < 0 || y > h) continue;
          const isMajor = mm % major === 0;
          const tickW = isMajor ? 10 : 5;
          ctx.moveTo(w, y);
          ctx.lineTo(w - tickW, y);
        }
        ctx.stroke();

        for (let mm = startMm; mm <= endMm; mm += major) {
          const y = mm * scalePxPerMm + offsetY;
          if (y < -12 || y > h + 12) continue;
          ctx.save();
          ctx.translate(10, y + 3);
          ctx.rotate(-Math.PI / 2);
          ctx.textAlign = 'right';
          ctx.textBaseline = 'middle';
          ctx.fillText(String(mm), 0, 0);
          ctx.restore();
        }

        if (cursorMm) {
          const cy = cursorMm.y * scalePxPerMm + offsetY;
          if (cy >= 0 && cy <= h) {
            ctx.strokeStyle = cursorColor;
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.moveTo(0, cy);
            ctx.lineTo(w, cy);
            ctx.stroke();
          }
        }
      }
    }
  }
}
