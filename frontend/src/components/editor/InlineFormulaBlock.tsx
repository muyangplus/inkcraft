import React, { useEffect, useRef, useState } from 'react';
import { Crosshair, RefreshCw, Sigma, Trash2 } from 'lucide-react';
import { restClient } from '../../api/restClient';
import type { DocBlock } from '../../api/types';
import { useDocumentLayoutStore } from '../../stores/useDocumentLayoutStore';
import { useViewportStore } from '../../stores/useViewportStore';
import { StandardLatexMath } from './latexMathRenderer';

export interface InlineFormulaBlockProps {
  docId: string;
  block: DocBlock;
  selected: boolean;
  flashLocated: boolean;
  onDelete: () => void;
}

export const InlineFormulaBlock: React.FC<InlineFormulaBlockProps> = ({
  docId,
  block,
  selected,
  flashLocated,
  onDelete,
}) => {
  const closeTimerRef = useRef<number | null>(null);

  const openFormulaEditor = useViewportStore((s) => s.openFormulaEditor);
  const setSelectedObjectId = useViewportStore((s) => s.setSelectedObjectId);
  const focusBlockOnCanvas = useDocumentLayoutStore((s) => s.focusBlockOnCanvas);
  const reRecognizeFormulaBlock = useDocumentLayoutStore((s) => s.reRecognizeFormulaBlock);
  const pushToast = useViewportStore((s) => s.pushToast);

  const [hovered, setHovered] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [recognizing, setRecognizing] = useState(false);

  const latex = (block.latex || '').trim();

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

  const showPopover = hovered || pinned || recognizing;

  const openModal = () =>
    openFormulaEditor({
      docId,
      blockId: block.block_id,
      inlineIndex: null,
      initialLatex: latex,
      assetName: block.asset_name ?? null,
    });

  return (
    <div
      data-block-id={block.block_id}
      className={`unified-inline-formula ${selected ? 'selected' : ''} ${flashLocated ? 'flash-locate' : ''}`}
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
        openModal();
      }}
      title="悬浮查看原图识别预览与重试识别 · 双击切换画布页并精修公式"
    >
      {/* Standard LaTeX MathML display rendering */}
      <div className="unified-formula-scroll">
        <StandardLatexMath latex={latex} display={true} />
      </div>

      {/* Floating Hover Popover: OCR Crop Preview + Source + Retry Recognition + Edit */}
      {showPopover && (
        <div
          className="unified-hover-popover formula-popover"
          role="dialog"
          aria-label="公式识别预览与操作"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="popover-head">
            <span className="row-gap" style={{ gap: 5, fontSize: 11, fontWeight: 700 }}>
              <Sigma size={12} style={{ color: '#7C3AED' }} />
              识别预览
            </span>
            <span className="popover-source-badge mono">
              {block.ocr_source || '手工/原生'}
            </span>
          </div>

          {block.asset_name && (
            <div className="popover-crop-wrap">
              <img
                src={restClient.getDocumentAssetUrl(docId, block.asset_name)}
                alt="原公式识别切片"
              />
            </div>
          )}

          <div className="popover-latex-line mono" title={latex}>
            $$ {latex || '...'} $$
          </div>

          <div className="popover-actions">
            {block.asset_name && (
              <button
                type="button"
                className="btn btn-xs"
                disabled={recognizing}
                onClick={(e) => {
                  e.stopPropagation();
                  setRecognizing(true);
                  void reRecognizeFormulaBlock(block.block_id)
                    .then((updated) => {
                      if (updated?.latex) pushToast('已完成公式重新识别', 'success');
                    })
                    .finally(() => setRecognizing(false));
                }}
              >
                <RefreshCw size={10} className={recognizing ? 'spin' : ''} />
                {recognizing ? '识别中…' : '重试识别'}
              </button>
            )}
            <button
              type="button"
              className="btn btn-xs btn-primary"
              onClick={(e) => {
                e.stopPropagation();
                openModal();
              }}
            >
              <Sigma size={10} /> 精修公式
            </button>
            <button
              type="button"
              className="btn btn-xs"
              title="在画布定位此公式"
              onClick={(e) => {
                e.stopPropagation();
                void focusBlockOnCanvas(block.block_id);
              }}
            >
              <Crosshair size={10} /> 定位
            </button>
            <button
              type="button"
              className="nudge-btn"
              title="删除此公式"
              onClick={(e) => {
                e.stopPropagation();
                onDelete();
              }}
            >
              <Trash2 size={11} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
