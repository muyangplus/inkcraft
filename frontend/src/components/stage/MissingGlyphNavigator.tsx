import React, { useMemo, useState } from 'react';
import { AlertTriangle, ArrowDown, ArrowUp, ChevronDown, Eye, FileSearch } from 'lucide-react';
import type { MissingGlyphBox } from '../../api/types';
import { useDocumentLayoutStore } from '../../stores/useDocumentLayoutStore';
import { useViewportStore } from '../../stores/useViewportStore';

export const MissingGlyphNavigator: React.FC = () => {
  const [listOpen, setListOpen] = useState(false);

  const layout = useDocumentLayoutStore((s) => s.layout);
  const currentPageIndex = useDocumentLayoutStore((s) => s.currentPageIndex);
  const focusMissingGlyph = useDocumentLayoutStore((s) => s.focusMissingGlyph);

  const activeMissingGlyphId = useViewportStore((s) => s.activeMissingGlyphId);
  const setShowMissingGlyphs = useViewportStore((s) => s.setShowMissingGlyphs);
  const requestEditorScroll = useViewportStore((s) => s.requestEditorScroll);
  const setWorkspaceView = useViewportStore((s) => s.setWorkspaceView);
  const workspaceView = useViewportStore((s) => s.workspaceView);
  const openGlyphInspector = useViewportStore((s) => s.openGlyphInspector);

  const allMissing = useMemo<MissingGlyphBox[]>(() => {
    const out: MissingGlyphBox[] = [];
    for (const p of layout?.pages ?? []) {
      if (p.missing_glyphs?.length) {
        out.push(...p.missing_glyphs);
      }
    }
    return out;
  }, [layout]);

  if (allMissing.length === 0) return null;

  let activeIdx = allMissing.findIndex((m) => m.id === activeMissingGlyphId);
  if (activeIdx < 0) {
    activeIdx = Math.max(
      0,
      allMissing.findIndex((m) => m.page_index === currentPageIndex),
    );
  }
  const currentMg = allMissing[activeIdx] ?? allMissing[0];

  const stepGlyph = (delta: -1 | 1) => {
    if (allMissing.length === 0) return;
    const baseIdx =
      allMissing.findIndex((m) => m.id === activeMissingGlyphId) >= 0
        ? allMissing.findIndex((m) => m.id === activeMissingGlyphId)
        : Math.max(0, allMissing.findIndex((m) => m.page_index >= currentPageIndex));
    const nextIdx = (baseIdx + delta + allMissing.length) % allMissing.length;
    setShowMissingGlyphs(true);
    void focusMissingGlyph(allMissing[nextIdx]);
  };

  return (
    <div className="missing-glyph-nav" aria-label="缺字回退快速定位">
      <button
        type="button"
        className="mgn-summary-btn"
        onClick={() => setListOpen((v) => !v)}
        title="展开全部缺字位置列表"
      >
        <AlertTriangle size={12} />
        <span className="mono">
          缺字 {activeIdx + 1}/{allMissing.length} · 「{currentMg.char}」 P{currentMg.page_index + 1}
        </span>
        <ChevronDown size={11} />
      </button>

      <button
        type="button"
        className="mgn-icon-btn"
        onClick={() => stepGlyph(-1)}
        title="上一个缺字 (Alt+[)"
      >
        <ArrowUp size={12} />
      </button>
      <button
        type="button"
        className="mgn-icon-btn"
        onClick={() => stepGlyph(1)}
        title="下一个缺字 (Alt+])"
      >
        <ArrowDown size={12} />
      </button>

      {currentMg.block_id && (
        <button
          type="button"
          className="mgn-action-btn"
          onClick={() => {
            if (workspaceView === 'canvas') setWorkspaceView('split');
            requestEditorScroll(currentMg.block_id);
          }}
          title="在文稿编辑器中定位到该缺字所属段落"
        >
          <FileSearch size={11} /> 文稿
        </button>
      )}

      <button
        type="button"
        className="mgn-action-btn"
        onClick={() => openGlyphInspector(currentMg.char)}
        title={`在字形检测器中查看「${currentMg.char}」`}
      >
        <Eye size={11} /> 字形
      </button>

      {listOpen && (
        <div className="mgn-popover">
          <div className="mgn-popover-head">
            <span>全文档缺字清单 ({allMissing.length} 处)</span>
            <button type="button" className="btn btn-xs" onClick={() => setListOpen(false)}>
              关闭
            </button>
          </div>
          <div className="mgn-popover-list">
            {allMissing.slice(0, 120).map((mg, i) => (
              <button
                key={mg.id || `${mg.page_index}-${i}`}
                type="button"
                className={`mgn-popover-item ${mg.id === currentMg.id ? 'active' : ''}`}
                onClick={() => {
                  setListOpen(false);
                  void focusMissingGlyph(mg);
                }}
              >
                <span className="mgn-char">{mg.char}</span>
                <span className="mono mgn-page">P{mg.page_index + 1}</span>
                <span className="mgn-ctx">{mg.context || mg.source}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
