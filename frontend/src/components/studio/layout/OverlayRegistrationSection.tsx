import React from 'react';
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, RotateCcw } from 'lucide-react';
import type { DocBlock } from '../../../api/types';
import { useDocumentLayoutStore } from '../../../stores/useDocumentLayoutStore';
import { useViewportStore } from '../../../stores/useViewportStore';

function summarizeBlock(block: DocBlock): string {
  if (block.latex) return `公式: ${block.latex.slice(0, 24)}`;
  if (block.chart) return `图表: ${block.chart.title || block.chart.chart_type}`;
  if (block.table) return `表格 (${block.table.rows}×${block.table.cols})`;
  const text = (block.inlines ?? [])
    .map((i) => (i.t === 'text' ? i.text : i.t === 'math' ? `$${i.latex}$` : ' '))
    .join('')
    .trim();
  return text ? text.slice(0, 22) : `${block.type} (${block.block_id})`;
}

export const OverlayRegistrationSection: React.FC = () => {
  const blocks = useDocumentLayoutStore((s) => s.blocks);
  const config = useDocumentLayoutStore((s) => s.config);
  const currentPageIndex = useDocumentLayoutStore((s) => s.currentPageIndex);
  const updateConfig = useDocumentLayoutStore((s) => s.updateConfig);
  const toggleOverlayBlock = useDocumentLayoutStore((s) => s.toggleOverlayBlock);
  const nudgeOverlayBlock = useDocumentLayoutStore((s) => s.nudgeOverlayBlock);
  const resetOverlayTransform = useDocumentLayoutStore((s) => s.resetOverlayTransform);

  const selectedBlockId = useViewportStore((s) => s.selectedBlockId);
  const setSelectedBlockId = useViewportStore((s) => s.setSelectedBlockId);

  const pageBlocks = blocks.filter(
    (b) => (b.page_index ?? 0) === currentPageIndex && b.type !== 'discarded',
  );

  return (
    <>
      <div className="section-card">
        <div className="section-head">
          <span>原版 PDF 套打全局配准</span>
          <button className="btn btn-xs" onClick={resetOverlayTransform}>
            <RotateCcw size={10} /> 重置
          </button>
        </div>

        <div className="ctrl-row">
          <div className="ctrl-label">
            <span>PDF 底图透明度</span>
            <span className="ctrl-val mono">
              {Math.round(config.overlay.underlay_opacity * 100)}%
            </span>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            step={2}
            value={Math.round(config.overlay.underlay_opacity * 100)}
            onChange={(e) =>
              updateConfig((p) => ({
                ...p,
                overlay: { ...p.overlay, underlay_opacity: Number(e.target.value) / 100 },
              }))
            }
          />
        </div>

        <div className="ctrl-row">
          <div className="ctrl-label">
            <span>全局 X 偏置</span>
            <span className="ctrl-val mono">{config.overlay.offset_mm.x.toFixed(1)} mm</span>
          </div>
          <input
            type="range"
            min={-15}
            max={15}
            step={0.2}
            value={config.overlay.offset_mm.x}
            onChange={(e) =>
              updateConfig((p) => ({
                ...p,
                overlay: {
                  ...p.overlay,
                  offset_mm: { ...p.overlay.offset_mm, x: Number(e.target.value) },
                },
              }))
            }
          />
        </div>

        <div className="ctrl-row">
          <div className="ctrl-label">
            <span>全局 Y 偏置</span>
            <span className="ctrl-val mono">{config.overlay.offset_mm.y.toFixed(1)} mm</span>
          </div>
          <input
            type="range"
            min={-15}
            max={15}
            step={0.2}
            value={config.overlay.offset_mm.y}
            onChange={(e) =>
              updateConfig((p) => ({
                ...p,
                overlay: {
                  ...p.overlay,
                  offset_mm: { ...p.overlay.offset_mm, y: Number(e.target.value) },
                },
              }))
            }
          />
        </div>

        <div className="ctrl-row">
          <div className="ctrl-label">
            <span>全局缩放</span>
            <span className="ctrl-val mono">{config.overlay.scale.toFixed(3)} ×</span>
          </div>
          <input
            type="range"
            min={0.85}
            max={1.15}
            step={0.005}
            value={config.overlay.scale}
            onChange={(e) =>
              updateConfig((p) => ({
                ...p,
                overlay: { ...p.overlay, scale: Number(e.target.value) },
              }))
            }
          />
        </div>

        <div className="ctrl-row">
          <div className="ctrl-label">
            <span>纸张微旋补偿</span>
            <span className="ctrl-val mono">{config.overlay.rotation_deg.toFixed(1)}°</span>
          </div>
          <input
            type="range"
            min={-3}
            max={3}
            step={0.1}
            value={config.overlay.rotation_deg}
            onChange={(e) =>
              updateConfig((p) => ({
                ...p,
                overlay: { ...p.overlay, rotation_deg: Number(e.target.value) },
              }))
            }
          />
        </div>
      </div>

      <div className="section-card">
        <div className="section-head">
          <span>本页套打区块 ({pageBlocks.length})</span>
          <span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>画布可点选拖拽</span>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          {pageBlocks.length === 0 ? (
            <div style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>当前页暂无可微调区块。</div>
          ) : (
            pageBlocks.map((b) => {
              const ov = config.overlay.blocks[b.block_id] ?? {
                enabled: true,
                nudge_mm: { x: 0, y: 0 },
              };
              const isSel = selectedBlockId === b.block_id;
              return (
                <div
                  key={b.block_id}
                  className={`block-item ${isSel ? 'selected' : ''} ${!ov.enabled ? 'disabled' : ''}`}
                  onClick={() => setSelectedBlockId(b.block_id)}
                >
                  <input
                    type="checkbox"
                    checked={ov.enabled}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => toggleOverlayBlock(b.block_id, e.target.checked)}
                  />
                  <span className="block-label" title={b.block_id}>
                    {summarizeBlock(b)}
                  </span>
                  <div className="nudge-btns" onClick={(e) => e.stopPropagation()}>
                    <button
                      className="nudge-btn"
                      title="左移 0.5mm"
                      onClick={() => nudgeOverlayBlock(b.block_id, -0.5, 0)}
                    >
                      <ArrowLeft size={10} />
                    </button>
                    <button
                      className="nudge-btn"
                      title="右移 0.5mm"
                      onClick={() => nudgeOverlayBlock(b.block_id, 0.5, 0)}
                    >
                      <ArrowRight size={10} />
                    </button>
                    <button
                      className="nudge-btn"
                      title="上移 0.5mm"
                      onClick={() => nudgeOverlayBlock(b.block_id, 0, -0.5)}
                    >
                      <ArrowUp size={10} />
                    </button>
                    <button
                      className="nudge-btn"
                      title="下移 0.5mm"
                      onClick={() => nudgeOverlayBlock(b.block_id, 0, 0.5)}
                    >
                      <ArrowDown size={10} />
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </>
  );
};
