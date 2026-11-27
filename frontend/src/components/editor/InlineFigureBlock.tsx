import React, { useEffect, useRef, useState } from 'react';
import {
  AlignCenter,
  AlignLeft,
  AlignRight,
  Crosshair,
  Image as ImageIcon,
  Move,
  Sparkles,
  Trash2,
} from 'lucide-react';
import { restClient } from '../../api/restClient';
import type { DocBlock, ImageRenderMode } from '../../api/types';
import { useDocumentLayoutStore } from '../../stores/useDocumentLayoutStore';
import { useViewportStore } from '../../stores/useViewportStore';
import { NumericInput } from '../studio/layout/NumericInput';

const MODE_LABELS: Array<{ value: ImageRenderMode; label: string }> = [
  { value: 'major_outline', label: '仅主外轮廓' },
  { value: 'outline', label: '仅轮廓' },
  { value: 'hatch', label: '单向阴影' },
  { value: 'crosshatch', label: '交叉阴影' },
  { value: 'sketch', label: '素描排线' },
  { value: 'skip', label: '跳过' },
];

export interface InlineFigureBlockProps {
  docId: string;
  block: DocBlock;
  selected: boolean;
  flashLocated: boolean;
  defaultImageMode: ImageRenderMode;
  onPatch: (blockId: string, patch: Record<string, unknown>) => Promise<boolean>;
  onDelete: () => void;
}

export const InlineFigureBlock: React.FC<InlineFigureBlockProps> = ({
  docId,
  block,
  selected,
  flashLocated,
  defaultImageMode,
  onPatch,
  onDelete,
}) => {
  const closeTimerRef = useRef<number | null>(null);
  const setSelectedObjectId = useViewportStore((s) => s.setSelectedObjectId);
  const focusBlockOnCanvas = useDocumentLayoutStore((s) => s.focusBlockOnCanvas);
  const applyGlobalImageStyle = useDocumentLayoutStore((s) => s.applyGlobalImageStyle);

  const [hovered, setHovered] = useState(false);
  const [pinned, setPinned] = useState(false);

  useEffect(() => {
    if (!selected) setPinned(false);
  }, [selected]);

  useEffect(() => {
    return () => {
      if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current);
    };
  }, []);

  const handleMouseEnter = () => {
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    setHovered(true);
  };

  const handleMouseLeave = () => {
    if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current);
    closeTimerRef.current = window.setTimeout(() => setHovered(false), 140);
  };

  const effMode: ImageRenderMode =
    !block.image_render_mode || block.image_render_mode === 'inherit'
      ? defaultImageMode
      : block.image_render_mode;
  const placement = block.placement ?? 'inline';
  const align = block.image_align ?? 'center';
  const boxW =
    block.image_width_mm ??
    (block.bbox_mm ? Number((block.bbox_mm[2] - block.bbox_mm[0]).toFixed(1)) : 80);
  const boxH =
    block.image_height_mm ??
    (block.bbox_mm ? Number((block.bbox_mm[3] - block.bbox_mm[1]).toFixed(1)) : 52);

  const showPopover = hovered || pinned;

  return (
    <div
      data-block-id={block.block_id}
      className={`unified-inline-figure align-${align} ${selected ? 'selected' : ''} ${flashLocated ? 'flash-locate' : ''}`}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onClick={(e) => {
        e.stopPropagation();
        setSelectedObjectId(block.block_id);
        setPinned((v) => !v);
      }}
      onDoubleClick={(e) => {
        e.stopPropagation();
        void focusBlockOnCanvas(block.block_id);
      }}
    >
      <div className="unified-figure-frame">
        {block.asset_name ? (
          <img
            src={restClient.getDocumentAssetUrl(docId, block.asset_name)}
            alt={block.alt_text || block.asset_name}
            style={{
              width: `${Math.max(90, Math.min(420, boxW * 2.8))}px`,
              opacity: effMode === 'skip' ? 0.35 : 1,
            }}
          />
        ) : (
          <div className="unified-figure-vector-box">
            <ImageIcon size={20} style={{ opacity: 0.6 }} />
            <span>{block.alt_text || block.chart?.title || '矢量插图'}</span>
          </div>
        )}
        {(placement === 'float' || effMode === 'skip') && (
          <span className="unified-figure-badge mono">
            {effMode === 'skip' ? '已跳过' : '浮动环绕'}
          </span>
        )}
      </div>

      {showPopover && (
        <div
          className="unified-hover-popover figure-popover"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="popover-head">
            <span className="row-gap" style={{ gap: 5, fontSize: 11, fontWeight: 700 }}>
              <ImageIcon size={12} style={{ color: '#0284C7' }} />
              插图设置 · {block.asset_name || '矢量图'}
            </span>
            <span className="mono" style={{ fontSize: 10, color: 'var(--text-muted)' }}>
              {boxW}×{boxH}mm
            </span>
          </div>

          <div className="popover-chip-row">
            {MODE_LABELS.map((m) => (
              <button
                key={m.value}
                type="button"
                className={`btn btn-xs ${effMode === m.value ? 'btn-primary' : ''}`}
                onClick={() =>
                  void onPatch(block.block_id, { image_render_mode: m.value })
                }
              >
                {m.label}
              </button>
            ))}
            <button
              type="button"
              className="btn btn-xs"
              title="将当前图片绘制模式应用到全部图片"
              onClick={() => void applyGlobalImageStyle(effMode)}
            >
              <Sparkles size={10} /> 全部应用
            </button>
          </div>

          <div className="popover-actions">
            <button
              type="button"
              className="btn btn-xs"
              onClick={() => {
                const nextMode = placement === 'inline' ? 'float' : 'inline';
                const patch: Record<string, unknown> = { placement: nextMode };
                if (nextMode === 'float' && !block.float_box_mm) {
                  patch.float_box_mm = [
                    30,
                    40,
                    Number((30 + boxW).toFixed(1)),
                    Number((40 + boxH).toFixed(1)),
                  ];
                }
                void onPatch(block.block_id, patch);
              }}
            >
              <Move size={10} />
              {placement === 'float' ? '切为嵌入' : '切为浮动'}
            </button>

            {placement === 'inline' && (
              <div className="seg-group">
                <button
                  type="button"
                  className={`seg-btn ${align === 'left' ? 'active' : ''}`}
                  onClick={() => void onPatch(block.block_id, { image_align: 'left' })}
                >
                  <AlignLeft size={10} />
                </button>
                <button
                  type="button"
                  className={`seg-btn ${align === 'center' ? 'active' : ''}`}
                  onClick={() => void onPatch(block.block_id, { image_align: 'center' })}
                >
                  <AlignCenter size={10} />
                </button>
                <button
                  type="button"
                  className={`seg-btn ${align === 'right' ? 'active' : ''}`}
                  onClick={() => void onPatch(block.block_id, { image_align: 'right' })}
                >
                  <AlignRight size={10} />
                </button>
              </div>
            )}

            <div className="row-gap" style={{ gap: 3 }}>
              <NumericInput
                className="mono"
                min={12}
                max={280}
                decimals={1}
                value={boxW}
                style={{ width: 42, padding: '2px 4px', fontSize: 10 }}
                onCommit={(val) => {
                  if (val !== null) void onPatch(block.block_id, { image_width_mm: val });
                }}
              />
              <span style={{ fontSize: 10 }}>×</span>
              <NumericInput
                className="mono"
                min={10}
                max={350}
                decimals={1}
                value={boxH}
                style={{ width: 42, padding: '2px 4px', fontSize: 10 }}
                onCommit={(val) => {
                  if (val !== null) void onPatch(block.block_id, { image_height_mm: val });
                }}
              />
            </div>

            <button
              type="button"
              className="btn btn-xs"
              onClick={() => void focusBlockOnCanvas(block.block_id)}
            >
              <Crosshair size={10} /> 定位
            </button>
            <button
              type="button"
              className="nudge-btn"
              title="删除此图"
              onClick={onDelete}
            >
              <Trash2 size={11} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
