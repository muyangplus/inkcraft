import React, { useEffect, useRef, useState } from 'react';
import { Eye, Search, X } from 'lucide-react';
import type { GlyphVariantInfo, GlyphVariantsResponse, HwFontMeta } from '../../api/types';
import { useViewportStore } from '../../stores/useViewportStore';
import { useWriterStore } from '../../stores/useWriterStore';

const QUICK_CHARS = ['永', '和', '单', '线', '手', '写', '力', '学', 'A', 'g', '8', 'α', '∑'];

const GlyphVariantCanvas: React.FC<{
  variant: GlyphVariantInfo;
  meta: HwFontMeta;
  showOrder: boolean;
}> = ({ variant, meta, showOrder }) => {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const size = 164;
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const upm = meta.units_per_em || 1000;
    const pad = 12;
    const drawSize = size - pad * 2;
    const s = drawSize / upm;

    // Archival paper background
    ctx.fillStyle = '#FAF7F0';
    ctx.fillRect(0, 0, size, size);

    // 0..1000 coordinate grid (200 unit step)
    ctx.strokeStyle = 'rgba(148, 163, 184, 0.28)';
    ctx.lineWidth = 0.7;
    ctx.beginPath();
    for (let u = 0; u <= upm; u += 200) {
      const p = pad + u * s;
      ctx.moveTo(p, pad);
      ctx.lineTo(p, pad + drawSize);
      ctx.moveTo(pad, p);
      ctx.lineTo(pad + drawSize, p);
    }
    ctx.stroke();

    // x_height & cap_height guides
    const capY = pad + (meta.baseline_y - (meta.cap_height || 680)) * s;
    const xY = pad + (meta.baseline_y - (meta.x_height || 440)) * s;
    ctx.save();
    ctx.strokeStyle = 'rgba(59, 130, 246, 0.3)';
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(pad, capY);
    ctx.lineTo(pad + drawSize, capY);
    ctx.moveTo(pad, xY);
    ctx.lineTo(pad + drawSize, xY);
    ctx.stroke();

    // baseline_y = 800 amber line
    const baseY = pad + (meta.baseline_y || 800) * s;
    ctx.strokeStyle = 'rgba(245, 158, 11, 0.85)';
    ctx.setLineDash([]);
    ctx.lineWidth = 1.1;
    ctx.beginPath();
    ctx.moveTo(pad, baseY);
    ctx.lineTo(pad + drawSize, baseY);
    ctx.stroke();

    // Advance width guide
    const advX = pad + Math.min(upm, variant.advance || meta.default_advance || 1000) * s;
    ctx.strokeStyle = 'rgba(14, 165, 233, 0.45)';
    ctx.setLineDash([2, 2]);
    ctx.beginPath();
    ctx.moveTo(advX, pad);
    ctx.lineTo(advX, pad + drawSize);
    ctx.stroke();

    // BBox guide
    if (variant.bbox && variant.bbox.length === 4) {
      const [bx0, by0, bx1, by1] = variant.bbox;
      ctx.strokeStyle = 'rgba(34, 197, 94, 0.45)';
      ctx.setLineDash([2, 2]);
      ctx.strokeRect(pad + bx0 * s, pad + by0 * s, (bx1 - bx0) * s, (by1 - by0) * s);
    }
    ctx.restore();

    // Single-line strokes with optional start-point numbers & direction arrows
    variant.strokes.forEach((stroke, idx) => {
      if (stroke.length < 4) return;
      const sx = pad + stroke[0] * s;
      const sy = pad + stroke[1] * s;
      const ex = pad + stroke[stroke.length - 2] * s;
      const ey = pad + stroke[stroke.length - 1] * s;

      const grad = ctx.createLinearGradient(sx, sy, ex, ey);
      grad.addColorStop(0, '#1B365D');
      grad.addColorStop(1, '#3B82F6');

      ctx.strokeStyle = showOrder ? grad : '#1B365D';
      ctx.lineWidth = 2.0;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      for (let i = 2; i < stroke.length; i += 2) {
        ctx.lineTo(pad + stroke[i] * s, pad + stroke[i + 1] * s);
      }
      ctx.stroke();

      if (showOrder) {
        // Start point green badge + stroke index
        ctx.fillStyle = '#16A34A';
        ctx.beginPath();
        ctx.arc(sx, sy, 5.2, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = '#FFFFFF';
        ctx.font = '700 7.5px "JetBrains Mono", monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(String(idx + 1), sx, sy + 0.4);

        // Direction arrowhead at stroke end
        const px = pad + stroke[stroke.length - 4] * s;
        const py = pad + stroke[stroke.length - 3] * s;
        const ang = Math.atan2(ey - py, ex - px);
        ctx.fillStyle = '#2563EB';
        ctx.beginPath();
        ctx.moveTo(ex, ey);
        ctx.lineTo(ex - 5 * Math.cos(ang - 0.5), ey - 5 * Math.sin(ang - 0.5));
        ctx.lineTo(ex - 5 * Math.cos(ang + 0.5), ey - 5 * Math.sin(ang + 0.5));
        ctx.closePath();
        ctx.fill();
      }
    });
  }, [variant, meta, showOrder]);

  return <canvas ref={ref} className="glyph-canvas" />;
};

export const GlyphInspectorModal: React.FC = () => {
  const activeModal = useViewportStore((s) => s.activeModal);
  const glyphChar = useViewportStore((s) => s.glyphInspectorChar);
  const openModal = useViewportStore((s) => s.openModal);
  const setGlyphInspectorChar = useViewportStore((s) => s.setGlyphInspectorChar);

  const writers = useWriterStore((s) => s.writers);
  const activeWriterId = useWriterStore((s) => s.activeWriterId);
  const fetchGlyph = useWriterStore((s) => s.fetchGlyph);

  const [inputChar, setInputChar] = useState(glyphChar);
  const [showOrder, setShowOrder] = useState(true);
  const [glyphResp, setGlyphResp] = useState<GlyphVariantsResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const isOpen = activeModal === 'glyph-inspector';
  const activeWriter = writers.find((w) => w.writer_id === activeWriterId) ?? writers[0];

  useEffect(() => {
    setInputChar(glyphChar);
  }, [glyphChar]);

  useEffect(() => {
    if (!isOpen || !activeWriterId || !glyphChar) return;
    let cancelled = false;
    setLoading(true);
    void fetchGlyph(activeWriterId, glyphChar).then((res) => {
      if (!cancelled) {
        setGlyphResp(res);
        setLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [isOpen, activeWriterId, glyphChar, fetchGlyph]);

  if (!isOpen || !activeWriter) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const ch = Array.from(inputChar.trim())[0];
    if (ch) setGlyphInspectorChar(ch);
  };

  return (
    <div className="modal-backdrop" onClick={() => openModal(null)}>
      <div className="modal-box" style={{ width: 680 }} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div className="modal-title">
            <Eye size={15} />
            字形检测器 · 同字异形与单线笔顺 (0..1000 坐标系)
          </div>
          <button className="btn btn-sm" onClick={() => openModal(null)}>
            <X size={13} /> 关闭
          </button>
        </div>

        <div className="modal-body">
          <div className="row-between" style={{ flexWrap: 'wrap', gap: 10 }}>
            <form className="row-gap" onSubmit={handleSubmit}>
              <input
                type="text"
                maxLength={2}
                value={inputChar}
                onChange={(e) => setInputChar(e.target.value)}
                style={{ width: 64, textAlign: 'center', fontSize: 15, fontWeight: 700 }}
                placeholder="字"
              />
              <button type="submit" className="btn btn-sm btn-primary">
                <Search size={12} /> 查询
              </button>
            </form>

            <label className="row-gap" style={{ fontSize: 12, color: 'var(--text-secondary)', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={showOrder}
                onChange={(e) => setShowOrder(e.target.checked)}
              />
              显示笔顺编号与方向箭头
            </label>
          </div>

          <div className="char-pills">
            {QUICK_CHARS.map((ch) => (
              <button
                key={ch}
                className={`char-pill ${glyphChar === ch ? 'active' : ''}`}
                onClick={() => setGlyphInspectorChar(ch)}
              >
                {ch}
              </button>
            ))}
          </div>

          {loading ? (
            <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)' }}>
              正在从 .hwfont 加载字符「{glyphChar}」变体轨迹…
            </div>
          ) : !glyphResp || glyphResp.variants.length === 0 ? (
            <div style={{ padding: 24, textAlign: 'center', color: 'var(--fallback-text)' }}>
              当前书写人字库中未收录字符「{glyphChar}」（将按回退策略使用内置单线矢量或占位）。
            </div>
          ) : (
            <div className="glyph-variants">
              {glyphResp.variants.map((v) => (
                <div key={v.variant_id} className="glyph-card">
                  <GlyphVariantCanvas variant={v} meta={activeWriter} showOrder={showOrder} />
                  <div className="row-between mono" style={{ width: '100%', fontSize: 11, color: 'var(--text-secondary)' }}>
                    <span>变体 #{v.variant_no + 1}</span>
                    <span>{v.strokes.length} 笔</span>
                  </div>
                  <div className="row-between mono" style={{ width: '100%', fontSize: 10.5, color: 'var(--text-muted)' }}>
                    <span>{v.source}</span>
                    <span>adv {v.advance} · q {v.quality.toFixed(2)}</span>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div
            className="row-between mono"
            style={{
              fontSize: 11,
              color: 'var(--text-muted)',
              background: 'var(--bg-input)',
              padding: '7px 10px',
              borderRadius: 6,
            }}
          >
            <span>
              units_per_em: {activeWriter.units_per_em} · baseline_y: {activeWriter.baseline_y} · y-down
            </span>
            <span>
              书写人: {activeWriter.writer_name} (U+
              {glyphChar ? glyphChar.codePointAt(0)?.toString(16).toUpperCase().padStart(4, '0') : '0000'})
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
