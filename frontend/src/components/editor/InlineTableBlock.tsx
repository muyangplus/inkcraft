import React, { useEffect, useRef, useState } from 'react';
import { Columns, Crosshair, Rows, Table2, Trash2 } from 'lucide-react';
import {
  TABLE_STYLE_OPTIONS,
  type DocBlock,
  type TableBorderStyle,
} from '../../api/types';
import { useDocumentLayoutStore } from '../../stores/useDocumentLayoutStore';
import { useViewportStore } from '../../stores/useViewportStore';
import {
  editableTextToInlines,
  inlinesToEditableText,
} from './unifiedDocUtils';

export interface InlineTableBlockProps {
  block: DocBlock;
  selected: boolean;
  flashLocated: boolean;
  globalTableStyle: TableBorderStyle;
  globalTableWidthRatio: number;
  globalTableAlign: 'left' | 'center' | 'right';
  onPatch: (blockId: string, patch: Record<string, unknown>) => Promise<boolean>;
  onDelete: () => void;
}

export const InlineTableBlock: React.FC<InlineTableBlockProps> = ({
  block,
  selected,
  flashLocated,
  globalTableStyle,
  globalTableWidthRatio,
  globalTableAlign,
  onPatch,
  onDelete,
}) => {
  const closeTimerRef = useRef<number | null>(null);
  const setSelectedObjectId = useViewportStore((s) => s.setSelectedObjectId);
  const focusBlockOnCanvas = useDocumentLayoutStore((s) => s.focusBlockOnCanvas);

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

  if (!block.table) return null;
  const table = block.table;

  const effStyle: TableBorderStyle = table.border_style ?? globalTableStyle;
  const effRatio =
    table.width_ratio ??
    (effStyle === 'compact' && Math.abs(globalTableWidthRatio - 1.0) < 1e-4
      ? 0.80
      : globalTableWidthRatio);
  const effAlign = table.align ?? globalTableAlign;

  const handleMouseEnter = () => {
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    setHovered(true);
  };

  const handleMouseLeave = () => {
    if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current);
    closeTimerRef.current = window.setTimeout(() => setHovered(false), 160);
  };

  const handleAddRow = () => {
    const nextCells = [...table.cells];
    for (let c = 0; c < table.cols; c++) {
      nextCells.push({ r: table.rows, c, rs: 1, cs: 1, inlines: [] });
    }
    void onPatch(block.block_id, {
      table: { ...table, rows: table.rows + 1, cells: nextCells },
    });
  };

  const handleAddCol = () => {
    const nextCells = [...table.cells];
    for (let r = 0; r < table.rows; r++) {
      nextCells.push({ r, c: table.cols, rs: 1, cs: 1, inlines: [] });
    }
    void onPatch(block.block_id, {
      table: { ...table, cols: table.cols + 1, cells: nextCells },
    });
  };

  const showPopover = hovered || pinned;

  return (
    <div
      data-block-id={block.block_id}
      className={`unified-inline-table align-${effAlign} ${selected ? 'selected' : ''} ${flashLocated ? 'flash-locate' : ''}`}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onClick={(e) => {
        e.stopPropagation();
        setSelectedObjectId(block.block_id);
        setPinned(true);
      }}
      onDoubleClick={(e) => {
        e.stopPropagation();
        void focusBlockOnCanvas(block.block_id);
      }}
    >
      <div
        className="unified-table-inner"
        style={{ width: `${Math.round(Math.max(45, Math.min(100, effRatio * 100)))}%` }}
      >
        <table className={`doc-edit-table tbl-style-${effStyle}`}>
          <tbody>
            {Array.from({ length: table.rows }, (_, rIdx) => (
              <tr key={rIdx}>
                {Array.from({ length: table.cols }, (_, cIdx) => {
                  const cell = table.cells.find((c) => c.r === rIdx && c.c === cIdx);
                  const cellTxt = inlinesToEditableText(cell?.inlines);
                  return (
                    <td key={cIdx}>
                      <input
                        key={`${rIdx}-${cIdx}-${cellTxt}`}
                        type="text"
                        defaultValue={cellTxt}
                        onBlur={(e) => {
                          const nextVal = e.target.value;
                          if (nextVal === cellTxt) return;
                          const nextCells = [...table.cells];
                          const existingIdx = nextCells.findIndex(
                            (c) => c.r === rIdx && c.c === cIdx,
                          );
                          const nextInlines = editableTextToInlines(nextVal);
                          if (existingIdx >= 0) {
                            nextCells[existingIdx] = {
                              ...nextCells[existingIdx],
                              inlines: nextInlines,
                            };
                          } else {
                            nextCells.push({
                              r: rIdx,
                              c: cIdx,
                              rs: 1,
                              cs: 1,
                              inlines: nextInlines,
                            });
                          }
                          void onPatch(block.block_id, {
                            table: { ...table, cells: nextCells },
                          });
                        }}
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showPopover && (
        <div
          className="unified-hover-popover table-popover"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="popover-head">
            <span className="row-gap" style={{ gap: 5, fontSize: 11, fontWeight: 700 }}>
              <Table2 size={12} style={{ color: 'var(--accent-primary)' }} />
              表格线条与宽窄 ({table.rows}×{table.cols})
            </span>
            <button
              type="button"
              className="btn btn-xs"
              style={{ fontSize: 10 }}
              onClick={() => void onPatch(block.block_id, { table_border_style: 'inherit' })}
            >
              跟随全局
            </button>
          </div>

          <div className="popover-chip-row">
            {TABLE_STYLE_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                className={`btn btn-xs ${effStyle === opt.value ? 'btn-primary' : ''}`}
                title={opt.desc}
                onClick={() => {
                  const patch: Record<string, unknown> = { table_border_style: opt.value };
                  if (opt.value === 'compact' && table.width_ratio == null) {
                    patch.table_width_ratio = 0.78;
                  }
                  void onPatch(block.block_id, patch);
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>

          <div className="popover-actions">
            <div className="seg-group">
              {[0.6, 0.75, 0.88, 1.0].map((r) => (
                <button
                  key={r}
                  type="button"
                  className={`seg-btn ${Math.abs(effRatio - r) < 0.06 ? 'active' : ''}`}
                  onClick={() => void onPatch(block.block_id, { table_width_ratio: r })}
                >
                  {Math.round(r * 100)}%
                </button>
              ))}
            </div>
            <button type="button" className="btn btn-xs" onClick={handleAddRow}>
              <Rows size={10} /> +行
            </button>
            <button type="button" className="btn btn-xs" onClick={handleAddCol}>
              <Columns size={10} /> +列
            </button>
            <button
              type="button"
              className="btn btn-xs"
              onClick={() => void focusBlockOnCanvas(block.block_id)}
            >
              <Crosshair size={10} /> 定位
            </button>
            <button type="button" className="nudge-btn" title="删除表格" onClick={onDelete}>
              <Trash2 size={11} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
