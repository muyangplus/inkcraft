import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Check, Crosshair, ImagePlus, Pencil, Sigma, Table2 } from 'lucide-react';
import type { DocBlock, DocInline } from '../../api/types';
import { useDocumentLayoutStore } from '../../stores/useDocumentLayoutStore';
import { useViewportStore } from '../../stores/useViewportStore';
import { StandardLatexMath } from './latexMathRenderer';
import {
  parseTextRunToBlocks,
  serializeTextRun,
} from './unifiedDocUtils';

export interface UnifiedTextSegmentProps {
  docId: string;
  blocks: DocBlock[];
  startVisIdx: number;
  endVisIdx: number;
  selectedObjectId: string | null;
  flashLocateId: string | null;
  onCommitTextRun: (startVisIdx: number, endVisIdx: number, nextBlocks: DocBlock[]) => Promise<void>;
  onInsertObjectAtEnd: (afterVisIdx: number, kind: 'formula_block' | 'table' | 'figure') => void;
}

function splitInlinesByBreak(inlines: DocInline[]): DocInline[][] {
  const rows: DocInline[][] = [[]];
  for (const inl of inlines) {
    if (inl.t === 'break') {
      rows.push([]);
    } else {
      rows[rows.length - 1].push(inl);
    }
  }
  return rows;
}

const SYMBOL_DEF_PREFIX_RE = /^(?:式中|其中)(?:[：:\s]|[A-Za-zα-ωΑ-ΩΔρ△σθλπ])/;
const SYMBOL_DEF_DASH_RE =
  /^(?:[A-Za-zα-ωΑ-ΩΔρ△σθλπ][A-Za-z0-9_]*(?:\s*[（(][^）)]{1,6}[）)])?(?:\s*[\u4e00-\u9fff]{1,2})?|\d{2,5})\s*(?:--|——|—|–|-\s|[：:])/;
const SYMBOL_DEF_COMMA_RE =
  /^[A-Za-zα-ωΑ-ΩΔρ△σθλπ][A-Za-z0-9()（）_]{0,5}\s*[,，]\s*[\u4e00-\u9fff]/;

function stripInlineMathRowText(inls: DocInline[]): string {
  const raw = inls
    .map((inl) => {
      if (inl.t === 'text') return inl.text || '';
      if (inl.t === 'math') return inl.latex || '';
      return '';
    })
    .join('');
  return raw
    .replace(/\$/g, '')
    .replace(/\\(?:text|mathrm|mathbf|mathit|operatorname)\{([^}]*)\}/g, '$1')
    .replace(/\\Delta\s*/g, 'Δ')
    .replace(/\\rho\s*/g, 'ρ')
    .replace(/\\%/g, '%')
    .replace(/[_^{}]/g, '')
    .trim();
}

function isSymbolDefLine(txt: string): boolean {
  if (!txt) return false;
  return (
    SYMBOL_DEF_PREFIX_RE.test(txt) ||
    SYMBOL_DEF_DASH_RE.test(txt) ||
    SYMBOL_DEF_COMMA_RE.test(txt)
  );
}

function isSymbolDefBlock(blk: DocBlock): boolean {
  if (blk.type !== 'paragraph') return false;
  const rows = splitInlinesByBreak(blk.inlines ?? [])
    .map((r) => stripInlineMathRowText(r))
    .filter(Boolean);
  if (rows.length === 0) return false;
  if (isSymbolDefLine(rows[0])) return true;
  if (rows.length >= 2) {
    const hits = rows.filter((r) => isSymbolDefLine(r)).length;
    return hits * 2 >= rows.length;
  }
  return false;
}

export const UnifiedTextSegment: React.FC<UnifiedTextSegmentProps> = ({
  docId,
  blocks,
  startVisIdx,
  endVisIdx,
  selectedObjectId,
  flashLocateId,
  onCommitTextRun,
  onInsertObjectAtEnd,
}) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const focusBlockOnCanvas = useDocumentLayoutStore((s) => s.focusBlockOnCanvas);
  const openFormulaEditor = useViewportStore((s) => s.openFormulaEditor);
  const setSelectedObjectId = useViewportStore((s) => s.setSelectedObjectId);

  const serialized = useMemo(() => serializeTextRun(blocks), [blocks]);
  const [draft, setDraft] = useState(serialized);
  const [editing, setEditing] = useState(blocks.length === 0);

  useEffect(() => {
    setDraft(serialized);
    if (blocks.length === 0) setEditing(true);
  }, [serialized, docId, blocks.length]);

  useLayoutEffect(() => {
    const el = textareaRef.current;
    if (!el || !editing) return;
    el.style.height = '0px';
    el.style.height = `${Math.max(40, el.scrollHeight + 2)}px`;
  }, [draft, editing]);

  const enterEditMode = () => {
    setEditing(true);
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
    });
  };

  const commitIfDirtyAndExit = () => {
    setEditing(false);
    if (draft === serialized) return;
    const nextBlocks = parseTextRunToBlocks(draft, blocks);
    void onCommitTextRun(startVisIdx, endVisIdx, nextBlocks);
  };

  const renderInlineSlice = (block: DocBlock, inls: DocInline[], baseOffset: number) =>
    inls.map((inl, k) => {
      if (inl.t === 'break') return <br key={`br-${baseOffset + k}`} />;
      if (inl.t === 'math') {
        const inlineIdx = (block.inlines ?? []).indexOf(inl);
        return (
          <span
            key={`m-${baseOffset + k}`}
            className="rendered-inline-math"
            title="点击编辑此行内公式 · 双击定位对应页"
            onClick={(e) => {
              e.stopPropagation();
              setSelectedObjectId(block.block_id);
              openFormulaEditor({
                docId,
                blockId: block.block_id,
                inlineIndex: inlineIdx >= 0 ? inlineIdx : null,
                initialLatex: inl.latex,
              });
            }}
            onDoubleClick={(e) => {
              e.stopPropagation();
              void focusBlockOnCanvas(block.block_id);
            }}
          >
            <StandardLatexMath latex={inl.latex} display={false} />
          </span>
        );
      }
      const txt = inl.text || '';
      if (inl.bold) return <strong key={`b-${baseOffset + k}`}>{txt}</strong>;
      if (inl.italic) return <em key={`i-${baseOffset + k}`}>{txt}</em>;
      return <React.Fragment key={`t-${baseOffset + k}`}>{txt}</React.Fragment>;
    });

  const targetActiveBlockId =
    blocks.find((b) => b.block_id === selectedObjectId)?.block_id ?? blocks[0]?.block_id ?? '';

  return (
    <div className={`unified-text-segment ${editing ? 'is-editing' : ''}`}>
      <div className="unified-text-hover-bar">
        {editing ? (
          <button
            type="button"
            className="btn btn-xs btn-primary"
            onClick={(e) => {
              e.stopPropagation();
              commitIfDirtyAndExit();
            }}
          >
            <Check size={10} /> 完成渲染
          </button>
        ) : (
          <button
            type="button"
            className="btn btn-xs"
            title="切换为文本编辑框进行文字微调"
            onClick={(e) => {
              e.stopPropagation();
              enterEditMode();
            }}
          >
            <Pencil size={10} /> 编辑文字
          </button>
        )}
        {targetActiveBlockId && (
          <button
            type="button"
            className="btn btn-xs"
            title="在画布区定位高亮此段手写排版（也可直接双击段落）"
            onClick={(e) => {
              e.stopPropagation();
              void focusBlockOnCanvas(targetActiveBlockId);
            }}
          >
            <Crosshair size={10} /> 画布定位
          </button>
        )}
        <button
          type="button"
          className="nudge-btn"
          title="在此段后插入公式"
          onClick={(e) => {
            e.stopPropagation();
            onInsertObjectAtEnd(endVisIdx, 'formula_block');
          }}
        >
          <Sigma size={11} />
        </button>
        <button
          type="button"
          className="nudge-btn"
          title="在此段后插入表格"
          onClick={(e) => {
            e.stopPropagation();
            onInsertObjectAtEnd(endVisIdx, 'table');
          }}
        >
          <Table2 size={11} />
        </button>
        <button
          type="button"
          className="nudge-btn"
          title="在此段后插入插图"
          onClick={(e) => {
            e.stopPropagation();
            onInsertObjectAtEnd(endVisIdx, 'figure');
          }}
        >
          <ImagePlus size={11} />
        </button>
      </div>

      {editing ? (
        <textarea
          ref={textareaRef}
          className="unified-textarea"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commitIfDirtyAndExit}
          onKeyDown={(e) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
              e.preventDefault();
              commitIfDirtyAndExit();
            } else if (e.key === 'Escape') {
              e.preventDefault();
              setDraft(serialized);
              setEditing(false);
            }
          }}
          placeholder="支持 # 标题、(1)(2)(3) 列表与 $x^2$ 行内公式（失焦自动回到标准渲染视图）…"
          spellCheck={false}
        />
      ) : (
        <div className="rendered-text-flow">
          {blocks.map((blk) => {
            const isSel = selectedObjectId === blk.block_id;
            const isFlash = flashLocateId === blk.block_id;
            const cls = `rendered-block ${isSel ? 'selected' : ''} ${isFlash ? 'flash-locate' : ''}`;
            const commonProps = {
              'data-block-id': blk.block_id,
              title: '双击立即切换到右侧对应渲染页面',
              onClick: (e: React.MouseEvent) => {
                e.stopPropagation();
                setSelectedObjectId(blk.block_id);
              },
              onDoubleClick: (e: React.MouseEvent) => {
                e.stopPropagation();
                void focusBlockOnCanvas(blk.block_id);
              },
            };

            if (blk.type === 'heading') {
              const lvl = Math.max(1, Math.min(3, blk.level || 1));
              const content = renderInlineSlice(blk, blk.inlines ?? [], 0);
              if (lvl === 1) {
                return (
                  <h1 key={blk.block_id} className={`${cls} rendered-heading lvl-1`} {...commonProps}>
                    {content}
                  </h1>
                );
              }
              if (lvl === 2) {
                return (
                  <h2 key={blk.block_id} className={`${cls} rendered-heading lvl-2`} {...commonProps}>
                    {content}
                  </h2>
                );
              }
              return (
                <h3 key={blk.block_id} className={`${cls} rendered-heading lvl-3`} {...commonProps}>
                  {content}
                </h3>
              );
            }

            if (blk.type === 'caption') {
              return (
                <div key={blk.block_id} className={`${cls} rendered-caption`} {...commonProps}>
                  {renderInlineSlice(blk, blk.inlines ?? [], 0)}
                </div>
              );
            }

            if (blk.type === 'list_item') {
              const rows = splitInlinesByBreak(blk.inlines ?? []);
              return (
                <div key={blk.block_id} className={`${cls} rendered-list`} {...commonProps}>
                  {rows.map((rowInls, rIdx) => (
                    <div key={rIdx} className="rendered-list-line">
                      {renderInlineSlice(blk, rowInls, rIdx * 100)}
                    </div>
                  ))}
                </div>
              );
            }

            if (isSymbolDefBlock(blk)) {
              const rows = splitInlinesByBreak(blk.inlines ?? []);
              return (
                <div key={blk.block_id} className={`${cls} rendered-symbol-def`} {...commonProps}>
                  {rows.map((rowInls, rIdx) => (
                    <div key={rIdx} className="rendered-symbol-line">
                      {renderInlineSlice(blk, rowInls, rIdx * 100)}
                    </div>
                  ))}
                </div>
              );
            }

            return (
              <p key={blk.block_id} className={`${cls} rendered-para`} {...commonProps}>
                {renderInlineSlice(blk, blk.inlines ?? [], 0)}
              </p>
            );
          })}
        </div>
      )}
    </div>
  );
};
