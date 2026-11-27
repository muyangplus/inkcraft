import React from 'react';
import { AlignCenter, AlignLeft, AlignRight, Layers, Move, Sparkles, X } from 'lucide-react';
import type { ImageRenderMode } from '../../api/types';
import { useDocumentLayoutStore } from '../../stores/useDocumentLayoutStore';
import { useViewportStore } from '../../stores/useViewportStore';
import { NumericInput } from '../studio/layout/NumericInput';

const STYLE_OPTIONS: Array<{ value: ImageRenderMode; label: string }> = [
  { value: 'major_outline', label: '仅主外轮廓' },
  { value: 'outline', label: '仅轮廓' },
  { value: 'hatch', label: '单向阴影' },
  { value: 'crosshatch', label: '交叉阴影' },
  { value: 'sketch', label: '素描排线' },
  { value: 'skip', label: '跳过不画' },
];

export const CanvasImageToolbar: React.FC = () => {
  const selectedObjectId = useViewportStore((s) => s.selectedObjectId);
  const setSelectedObjectId = useViewportStore((s) => s.setSelectedObjectId);

  const blocks = useDocumentLayoutStore((s) => s.blocks);
  const layout = useDocumentLayoutStore((s) => s.layout);
  const currentPageIndex = useDocumentLayoutStore((s) => s.currentPageIndex);
  const config = useDocumentLayoutStore((s) => s.config);
  const patchDocumentBlock = useDocumentLayoutStore((s) => s.patchDocumentBlock);
  const applyGlobalImageStyle = useDocumentLayoutStore((s) => s.applyGlobalImageStyle);

  if (!selectedObjectId) return null;
  const blk = blocks.find((b) => b.block_id === selectedObjectId);
  if (!blk || (blk.type !== 'figure' && blk.type !== 'chart')) return null;

  const placed = layout?.pages?.[currentPageIndex]?.placed_blocks?.find(
    (pb) => pb.block_id === blk.block_id,
  );
  const box = blk.placement === 'float' && blk.float_box_mm ? blk.float_box_mm : placed?.bbox_mm;
  const curW = blk.image_width_mm ?? (box ? Number((box[2] - box[0]).toFixed(1)) : 80);
  const curH = blk.image_height_mm ?? (box ? Number((box[3] - box[1]).toFixed(1)) : 52);
  const effMode: ImageRenderMode = blk.image_render_mode || config.chart.image_render_mode;
  const placement = blk.placement ?? 'inline';
  const align = blk.image_align ?? 'center';

  const applyScaleMm = (nextW: number, nextH: number) => {
    const patch: Record<string, unknown> = {
      image_width_mm: nextW,
      image_height_mm: nextH,
    };
    if (placement === 'float' && box) {
      patch.float_box_mm = [
        box[0],
        box[1],
        Number((box[0] + nextW).toFixed(2)),
        Number((box[1] + nextH).toFixed(2)),
      ];
    }
    void patchDocumentBlock(blk.block_id, patch);
  };

  return (
    <div className="canvas-image-toolbar" role="region" aria-label="选中插图工具栏">
      <div className="row-between" style={{ gap: 8 }}>
        <span className="cit-title">
          <Layers size={13} style={{ color: '#0284C7' }} />
          插图对象 · {blk.asset_name || blk.block_id}
        </span>
        <div className="row-gap" style={{ gap: 4 }}>
          <button
            type="button"
            className="btn btn-xs"
            onClick={() => void applyGlobalImageStyle(effMode)}
            title="将此绘制策略批量应用到文档中的全部图片"
          >
            <Sparkles size={11} /> 全部图片用此风格
          </button>
          <button
            type="button"
            className="nudge-btn"
            title="取消选中"
            onClick={() => setSelectedObjectId(null)}
          >
            <X size={12} />
          </button>
        </div>
      </div>

      <div className="cit-row">
        <span className="cit-label">绘制策略</span>
        <div className="seg-group">
          {STYLE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              className={`seg-btn ${effMode === opt.value ? 'active' : ''}`}
              style={{ padding: '2px 7px', fontSize: 11 }}
              onClick={() =>
                void patchDocumentBlock(blk.block_id, { image_render_mode: opt.value })
              }
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      <div className="cit-row">
        <span className="cit-label">排版嵌入</span>
        <div className="seg-group">
          <button
            type="button"
            className={`seg-btn ${placement === 'inline' ? 'active' : ''}`}
            style={{ padding: '2px 8px', fontSize: 11 }}
            onClick={() =>
              void patchDocumentBlock(blk.block_id, { placement: 'inline' })
            }
          >
            嵌入行间
          </button>
          <button
            type="button"
            className={`seg-btn ${placement === 'float' ? 'active' : ''}`}
            style={{ padding: '2px 8px', fontSize: 11 }}
            onClick={() => {
              const fb =
                blk.float_box_mm ??
                box ?? [30, 40, Number((30 + curW).toFixed(1)), Number((40 + curH).toFixed(1))];
              void patchDocumentBlock(blk.block_id, {
                placement: 'float',
                page_index: currentPageIndex,
                float_box_mm: fb,
              });
            }}
          >
            <Move size={10} /> 自由浮动 (文字环绕)
          </button>
        </div>

        {placement === 'inline' && (
          <div className="seg-group" style={{ marginLeft: 4 }}>
            <button
              type="button"
              className={`seg-btn ${align === 'left' ? 'active' : ''}`}
              title="左对齐"
              onClick={() => void patchDocumentBlock(blk.block_id, { image_align: 'left' })}
            >
              <AlignLeft size={12} />
            </button>
            <button
              type="button"
              className={`seg-btn ${align === 'center' ? 'active' : ''}`}
              title="居中"
              onClick={() => void patchDocumentBlock(blk.block_id, { image_align: 'center' })}
            >
              <AlignCenter size={12} />
            </button>
            <button
              type="button"
              className={`seg-btn ${align === 'right' ? 'active' : ''}`}
              title="右对齐"
              onClick={() => void patchDocumentBlock(blk.block_id, { image_align: 'right' })}
            >
              <AlignRight size={12} />
            </button>
          </div>
        )}

        <div className="row-gap" style={{ gap: 4, marginLeft: 'auto' }}>
          <span className="cit-label">尺寸 mm</span>
          <NumericInput
            className="mono"
            min={12}
            max={280}
            decimals={1}
            value={curW}
            style={{ width: 52, padding: '2px 4px', fontSize: 11 }}
            onCommit={(val) => {
              if (val === null) return;
              applyScaleMm(val, curH);
            }}
          />
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>×</span>
          <NumericInput
            className="mono"
            min={10}
            max={350}
            decimals={1}
            value={curH}
            style={{ width: 52, padding: '2px 4px', fontSize: 11 }}
            onCommit={(val) => {
              if (val === null) return;
              applyScaleMm(curW, val);
            }}
          />
        </div>
      </div>
    </div>
  );
};
