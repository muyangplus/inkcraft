import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Code2,
  Download,
  FileText,
  ImagePlus,
  Save,
  Sigma,
  Sparkles,
  Table2,
  X,
} from 'lucide-react';
import { restClient } from '../../api/restClient';
import {
  applyTableStylePreset,
  TABLE_STYLE_OPTIONS,
  type DocBlock,
  type TableBorderStyle,
} from '../../api/types';
import { useDocumentLayoutStore } from '../../stores/useDocumentLayoutStore';
import { useViewportStore } from '../../stores/useViewportStore';
import { InlineFigureBlock } from './InlineFigureBlock';
import { InlineFormulaBlock } from './InlineFormulaBlock';
import { InlineTableBlock } from './InlineTableBlock';
import { buildDocumentSegments } from './unifiedDocUtils';
import { UnifiedTextSegment } from './UnifiedTextSegment';

function createStarterTableBlock(readingOrder: number): DocBlock {
  const headers = ['项目', '实测值', '单位'];
  const cells = [];
  for (let r = 0; r < 3; r++) {
    for (let c = 0; c < 3; c++) {
      cells.push({
        r,
        c,
        rs: 1,
        cs: 1,
        inlines: [{ t: 'text' as const, text: r === 0 ? headers[c] : '' }],
      });
    }
  }
  return {
    block_id: `tbl-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 5)}`,
    page_index: 0,
    type: 'table',
    reading_order: readingOrder,
    level: 1,
    bbox_mm: [20, 40, 185, 85],
    table: {
      rows: 3,
      cols: 3,
      col_widths_mm: [55, 55, 55],
      cells,
    },
  };
}

export const DocumentEditorPane: React.FC = () => {
  const imgInputRef = useRef<HTMLInputElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const pendingImgAfterRef = useRef<number | null>(null);
  const lastHandledScrollNonceRef = useRef<number>(0);

  const currentDoc = useDocumentLayoutStore((s) => s.currentDoc);
  const blocks = useDocumentLayoutStore((s) => s.blocks);
  const markdown = useDocumentLayoutStore((s) => s.markdown);
  const savingDoc = useDocumentLayoutStore((s) => s.savingDoc);
  const config = useDocumentLayoutStore((s) => s.config);
  const updateConfig = useDocumentLayoutStore((s) => s.updateConfig);
  const saveDocumentMarkdown = useDocumentLayoutStore((s) => s.saveDocumentMarkdown);
  const saveDocumentBlocks = useDocumentLayoutStore((s) => s.saveDocumentBlocks);
  const patchDocumentBlock = useDocumentLayoutStore((s) => s.patchDocumentBlock);
  const applyGlobalImageStyle = useDocumentLayoutStore((s) => s.applyGlobalImageStyle);
  const uploadDocumentAsset = useDocumentLayoutStore((s) => s.uploadDocumentAsset);

  const editorSubMode = useViewportStore((s) => s.editorSubMode);
  const setEditorSubMode = useViewportStore((s) => s.setEditorSubMode);
  const setWorkspaceView = useViewportStore((s) => s.setWorkspaceView);
  const selectedObjectId = useViewportStore((s) => s.selectedObjectId);
  const setSelectedObjectId = useViewportStore((s) => s.setSelectedObjectId);
  const editorScrollTarget = useViewportStore((s) => s.editorScrollTarget);
  const clearEditorScrollTarget = useViewportStore((s) => s.clearEditorScrollTarget);
  const pushToast = useViewportStore((s) => s.pushToast);

  const [mdDraft, setMdDraft] = useState(markdown);
  const [showHiddenMeta, setShowHiddenMeta] = useState(false);
  const [flashLocateId, setFlashLocateId] = useState<string | null>(null);

  useEffect(() => {
    setMdDraft(markdown);
  }, [markdown, currentDoc?.doc_id]);

  useEffect(() => {
    if (!editorScrollTarget || editorScrollTarget.nonce === lastHandledScrollNonceRef.current) {
      return;
    }
    if (editorSubMode !== 'visual') {
      setEditorSubMode('visual');
      return;
    }
    lastHandledScrollNonceRef.current = editorScrollTarget.nonce;
    const targetBlockId = editorScrollTarget.blockId;
    clearEditorScrollTarget();

    const raf = requestAnimationFrame(() => {
      const container = scrollContainerRef.current;
      if (!container) return;
      const targets = Array.from(container.querySelectorAll<HTMLElement>('[data-block-id]'));
      const found = targets.find((el) => el.dataset.blockId === targetBlockId);
      if (found) {
        const scrollEl = found.classList.contains('rendered-block')
          ? found
          : (found.closest('.unified-text-segment') ?? found);
        scrollEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        setFlashLocateId(targetBlockId);
      }
    });
    const timer = window.setTimeout(() => {
      setFlashLocateId((cur) => (cur === targetBlockId ? null : cur));
    }, 1300);
    return () => {
      cancelAnimationFrame(raf);
      window.clearTimeout(timer);
    };
  }, [editorScrollTarget, editorSubMode, setEditorSubMode, clearEditorScrollTarget]);

  const visibleBlocks = useMemo(
    () =>
      blocks.filter(
        (b) =>
          showHiddenMeta ||
          (b.type !== 'header' &&
            b.type !== 'footer' &&
            b.type !== 'page_number' &&
            b.type !== 'discarded'),
      ),
    [blocks, showHiddenMeta],
  );
  const hiddenBlocks = useMemo(
    () =>
      blocks.filter(
        (b) =>
          b.type === 'header' ||
          b.type === 'footer' ||
          b.type === 'page_number' ||
          b.type === 'discarded',
      ),
    [blocks],
  );

  const segments = useMemo(() => buildDocumentSegments(visibleBlocks), [visibleBlocks]);

  const docStats = useMemo(() => {
    let formulaCnt = 0;
    let figCnt = 0;
    let tblCnt = 0;
    for (const b of visibleBlocks) {
      if (b.type === 'formula_block') formulaCnt += 1;
      else if (b.type === 'figure' || b.type === 'chart') figCnt += 1;
      else if (b.type === 'table') tblCnt += 1;
    }
    return { formulaCnt, figCnt, tblCnt };
  }, [visibleBlocks]);

  if (!currentDoc) {
    return (
      <section className="editor-pane empty">
        <div className="editor-empty-box">
          <FileText size={28} style={{ color: 'var(--accent-primary)', opacity: 0.7 }} />
          <div style={{ fontWeight: 700, fontSize: 13.5 }}>尚未打开文稿</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            请先上传 `.docx / .pdf / .md / .txt`，或使用「速写文本」创建一体化手写报告。
          </div>
          <button type="button" className="btn btn-sm" onClick={() => setWorkspaceView('canvas')}>
            返回画布预览
          </button>
        </div>
      </section>
    );
  }

  const commitVisualBlocks = async (nextVisible: DocBlock[]) => {
    const combined = [...nextVisible, ...(showHiddenMeta ? [] : hiddenBlocks)].map((b, idx) => ({
      ...b,
      reading_order: idx,
    }));
    await saveDocumentBlocks(combined);
  };

  const handleCommitTextRun = async (
    startVisIdx: number,
    endVisIdx: number,
    nextBlocks: DocBlock[],
  ) => {
    const nextVisible = [
      ...visibleBlocks.slice(0, startVisIdx),
      ...nextBlocks,
      ...visibleBlocks.slice(endVisIdx + 1),
    ];
    await commitVisualBlocks(nextVisible);
  };

  const handleDeleteBlock = (visIdx: number) => {
    const copy = visibleBlocks.filter((_, i) => i !== visIdx);
    void commitVisualBlocks(copy);
  };

  const handleInsertObject = (
    afterVisIdx: number,
    kind: 'formula_block' | 'table' | 'figure',
  ) => {
    if (kind === 'figure') {
      pendingImgAfterRef.current = afterVisIdx;
      imgInputRef.current?.click();
      return;
    }
    const copy = [...visibleBlocks];
    const insertIdx = afterVisIdx >= 0 ? Math.min(copy.length, afterVisIdx + 1) : copy.length;
    const newBlk: DocBlock =
      kind === 'table'
        ? createStarterTableBlock(insertIdx)
        : {
            block_id: `eq-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 5)}`,
            page_index: 0,
            type: 'formula_block',
            reading_order: insertIdx,
            level: 1,
            bbox_mm: [20, 40, 180, 56],
            latex: '\\frac{a}{b}',
          };
    copy.splice(insertIdx, 0, newBlk);
    void commitVisualBlocks(copy);
  };

  const handleUploadInlineImage = async (file: File | undefined) => {
    if (!file) return;
    const afterIdx = pendingImgAfterRef.current;
    pendingImgAfterRef.current = null;
    const uploaded = await uploadDocumentAsset(file);
    if (!uploaded) return;
    const insertIdx =
      afterIdx !== null && afterIdx >= 0
        ? Math.min(visibleBlocks.length, afterIdx + 1)
        : visibleBlocks.length;
    const newImgBlock: DocBlock = {
      block_id: `img-${Date.now().toString(36)}`,
      page_index: 0,
      type: 'figure',
      reading_order: insertIdx,
      level: 1,
      bbox_mm: [25, 40, 25 + uploaded.width_mm, 40 + uploaded.height_mm],
      asset_name: uploaded.asset_name,
      image_render_mode: 'outline',
      placement: 'inline',
      image_align: 'center',
      image_width_mm: uploaded.width_mm,
      image_height_mm: uploaded.height_mm,
      chart: { chart_type: 'raster' },
    };
    const copy = [...visibleBlocks];
    copy.splice(insertIdx, 0, newImgBlock);
    await commitVisualBlocks(copy);
    pushToast(`已插入插图 ${uploaded.asset_name}（默认仅画轮廓）`, 'success');
  };

  const handleSaveMarkdown = async () => {
    const ok = await saveDocumentMarkdown(mdDraft);
    if (ok) {
      pushToast('Markdown 修改已同步并重新排版', 'success');
    }
  };

  const effGlobalTableStyle: TableBorderStyle = config.table.draw_borders
    ? config.table.border_style
    : 'none';

  return (
    <section className="editor-pane" aria-label="Word 一体化文档编辑器">
      <div className="editor-topbar">
        <div className="row-gap" style={{ gap: 8, minWidth: 0, flexWrap: 'wrap', flex: '1 1 200px' }}>
          <div className="seg-group" role="tablist">
            <button
              type="button"
              className={`seg-btn ${editorSubMode === 'visual' ? 'active' : ''}`}
              onClick={() => setEditorSubMode('visual')}
            >
              <FileText size={12} /> 渲染模式
            </button>
            <button
              type="button"
              className={`seg-btn ${editorSubMode === 'markdown' ? 'active' : ''}`}
              onClick={() => {
                clearEditorScrollTarget();
                setEditorSubMode('markdown');
              }}
            >
              <Code2 size={12} /> Markdown 模式
            </button>
          </div>
          <span
            className="mono editor-doc-stats"
            style={{ fontSize: 10.5, color: 'var(--text-muted)' }}
            title={`整篇报告 · ${docStats.formulaCnt} 公式 · ${docStats.figCnt} 插图 · ${docStats.tblCnt} 表格 · ${savingDoc ? '保存中…' : '已同步'}`}
          >
            {docStats.formulaCnt}公式 · {docStats.figCnt}图 · {docStats.tblCnt}表 ·{' '}
            {savingDoc ? '保存中…' : '已同步'}
          </span>
        </div>

        <div className="row-gap" style={{ gap: 5 }}>
          <a
            className="btn btn-xs"
            href={restClient.getDocumentMarkdownDownloadUrl(currentDoc.doc_id)}
            download={`${currentDoc.source.filename}.md`}
          >
            <Download size={11} /> 导出 .md
          </a>
          <button
            type="button"
            className="nudge-btn"
            title="收起编辑器"
            onClick={() => setWorkspaceView('canvas')}
          >
            <X size={13} />
          </button>
        </div>
      </div>

      <div className="editor-subbar">
        {editorSubMode === 'visual' ? (
          <>
            <button
              type="button"
              className="btn btn-xs"
              onClick={() => handleInsertObject(visibleBlocks.length - 1, 'formula_block')}
            >
              <Sigma size={11} /> + 公式
            </button>
            <button
              type="button"
              className="btn btn-xs"
              onClick={() => handleInsertObject(visibleBlocks.length - 1, 'figure')}
            >
              <ImagePlus size={11} /> + 插图
            </button>
            <button
              type="button"
              className="btn btn-xs"
              onClick={() => handleInsertObject(visibleBlocks.length - 1, 'table')}
            >
              <Table2 size={11} /> + 表格
            </button>
            <input
              ref={imgInputRef}
              type="file"
              accept="image/*"
              style={{ display: 'none' }}
              onChange={(e) => {
                void handleUploadInlineImage(e.target.files?.[0]);
                e.target.value = '';
              }}
            />
            <span className="editor-divider" />
            <button
              type="button"
              className="btn btn-xs"
              onClick={() => void applyGlobalImageStyle('major_outline')}
              title="全部图片设为仅主外轮廓（严格禁止内部密集划线）"
            >
              仅主外轮廓
            </button>
            <button
              type="button"
              className="btn btn-xs"
              onClick={() => void applyGlobalImageStyle('outline')}
              title="全部图片设为仅画轮廓"
            >
              图片轮廓
            </button>
            <button
              type="button"
              className="btn btn-xs"
              onClick={() => void applyGlobalImageStyle('hatch')}
              title="全部图片设为单向阴影"
            >
              <Sparkles size={11} /> 图片阴影
            </button>
            <label className="row-gap" style={{ gap: 4, fontSize: 10.5, color: 'var(--text-secondary)' }}>
              <span>表格风格:</span>
              <select
                className="doc-block-type-sel"
                value={effGlobalTableStyle}
                onChange={(e) => {
                  const st = e.target.value as TableBorderStyle;
                  updateConfig(
                    (p) => ({
                      ...p,
                      preset_id: null,
                      table: applyTableStylePreset(p.table, st),
                    }),
                    true,
                  );
                }}
              >
                {TABLE_STYLE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </label>
            {hiddenBlocks.length > 0 && (
              <label
                className="row-gap"
                style={{ fontSize: 10.5, color: 'var(--text-muted)', marginLeft: 'auto', cursor: 'pointer' }}
              >
                <input
                  type="checkbox"
                  checked={showHiddenMeta}
                  onChange={(e) => setShowHiddenMeta(e.target.checked)}
                />
                页眉/页脚({hiddenBlocks.length})
              </label>
            )}
          </>
        ) : (
          <>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              支持 `# 标题`、`(1)(2)(3)` 合并列表、`$$公式$$`、`![图](asset){'{mode=outline}'}`、`&lt;!-- hw:table style=compact --&gt;`
            </span>
            <button
              type="button"
              className="btn btn-xs btn-primary"
              style={{ marginLeft: 'auto' }}
              disabled={savingDoc}
              onClick={() => void handleSaveMarkdown()}
            >
              <Save size={11} /> 应用 Markdown 并刷新画布
            </button>
          </>
        )}
      </div>

      {editorSubMode === 'visual' ? (
        <div
          ref={scrollContainerRef}
          className="editor-scroll"
          onClick={() => setSelectedObjectId(null)}
        >
          <div className="unified-doc-sheet">
            {segments.length === 0 ? (
              <UnifiedTextSegment
                docId={currentDoc.doc_id}
                blocks={[]}
                startVisIdx={0}
                endVisIdx={-1}
                selectedObjectId={selectedObjectId}
                flashLocateId={flashLocateId}
                onCommitTextRun={handleCommitTextRun}
                onInsertObjectAtEnd={handleInsertObject}
              />
            ) : (
              segments.map((seg) => {
                if (seg.kind === 'text_run') {
                  return (
                    <UnifiedTextSegment
                      key={seg.key}
                      docId={currentDoc.doc_id}
                      blocks={seg.blocks}
                      startVisIdx={seg.startVisIdx}
                      endVisIdx={seg.endVisIdx}
                      selectedObjectId={selectedObjectId}
                      flashLocateId={flashLocateId}
                      onCommitTextRun={handleCommitTextRun}
                      onInsertObjectAtEnd={handleInsertObject}
                    />
                  );
                }
                if (seg.kind === 'formula') {
                  return (
                    <InlineFormulaBlock
                      key={seg.key}
                      docId={currentDoc.doc_id}
                      block={seg.block}
                      selected={selectedObjectId === seg.block.block_id}
                      flashLocated={flashLocateId === seg.block.block_id}
                      onDelete={() => handleDeleteBlock(seg.visIdx)}
                    />
                  );
                }
                if (seg.kind === 'figure') {
                  return (
                    <InlineFigureBlock
                      key={seg.key}
                      docId={currentDoc.doc_id}
                      block={seg.block}
                      selected={selectedObjectId === seg.block.block_id}
                      flashLocated={flashLocateId === seg.block.block_id}
                      defaultImageMode={config.chart.image_render_mode}
                      onPatch={patchDocumentBlock}
                      onDelete={() => handleDeleteBlock(seg.visIdx)}
                    />
                  );
                }
                return (
                  <InlineTableBlock
                    key={seg.key}
                    block={seg.block}
                    selected={selectedObjectId === seg.block.block_id}
                    flashLocated={flashLocateId === seg.block.block_id}
                    globalTableStyle={effGlobalTableStyle}
                    globalTableWidthRatio={config.table.width_ratio}
                    globalTableAlign={config.table.align}
                    onPatch={patchDocumentBlock}
                    onDelete={() => handleDeleteBlock(seg.visIdx)}
                  />
                );
              })
            )}
          </div>
        </div>
      ) : (
        <div className="editor-md-wrap">
          <textarea
            className="editor-md-textarea mono"
            value={mdDraft}
            onChange={(e) => setMdDraft(e.target.value)}
            onKeyDown={(e) => {
              if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
                e.preventDefault();
                void handleSaveMarkdown();
              }
            }}
            spellCheck={false}
          />
        </div>
      )}
    </section>
  );
};
