import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  CheckSquare,
  Crop,
  FileText,
  Merge,
  Plus,
  RotateCcw,
  Scissors,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';
import { restClient } from '../../api/restClient';
import { useDocumentLayoutStore } from '../../stores/useDocumentLayoutStore';
import { useViewportStore } from '../../stores/useViewportStore';

type CropHandle = 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w';

interface DraftProject {
  id: string;
  title: string;
  pageIndices: number[];
}

interface CropDragState {
  mode: 'draw' | 'move' | 'resize';
  handle?: CropHandle;
  pageIndex: number;
  startXmm: number;
  startYmm: number;
  origRect: [number, number, number, number];
}

const HANDLES: Array<{ key: CropHandle; left: string; top: string; cursor: string }> = [
  { key: 'nw', left: '0%', top: '0%', cursor: 'nwse-resize' },
  { key: 'n', left: '50%', top: '0%', cursor: 'ns-resize' },
  { key: 'ne', left: '100%', top: '0%', cursor: 'nesw-resize' },
  { key: 'e', left: '100%', top: '50%', cursor: 'ew-resize' },
  { key: 'se', left: '100%', top: '100%', cursor: 'nwse-resize' },
  { key: 's', left: '50%', top: '100%', cursor: 'ns-resize' },
  { key: 'sw', left: '0%', top: '100%', cursor: 'nesw-resize' },
  { key: 'w', left: '0%', top: '50%', cursor: 'ew-resize' },
];

export const DocumentImportModal: React.FC = () => {
  const activeModal = useViewportStore((s) => s.activeModal);
  const importPreview = useDocumentLayoutStore((s) => s.importPreview);
  const importPreviewCommitting = useDocumentLayoutStore((s) => s.importPreviewCommitting);
  const defaultMode = useDocumentLayoutStore((s) => s.config.mode);
  const commitImportPreview = useDocumentLayoutStore((s) => s.commitImportPreview);
  const cancelImportPreview = useDocumentLayoutStore((s) => s.cancelImportPreview);

  const [modeHint, setModeHint] = useState<'reflow' | 'overlay'>(defaultMode);
  const [projects, setProjects] = useState<DraftProject[]>([]);
  const [activeProjId, setActiveProjId] = useState<string>('');
  const [activePageIndex, setActivePageIndex] = useState<number>(0);
  const [cropRectsMm, setCropRectsMm] = useState<Record<string, [number, number, number, number]>>({});
  const [excludeHeaderFooter, setExcludeHeaderFooter] = useState<boolean>(false);
  const [lastShiftAnchor, setLastShiftAnchor] = useState<number | null>(null);

  const paperRef = useRef<HTMLDivElement>(null);
  const cropDragRef = useRef<CropDragState | null>(null);

  useEffect(() => {
    if (activeModal !== 'document-import' || !importPreview) return;
    setModeHint(defaultMode);
    setCropRectsMm({});
    setExcludeHeaderFooter(false);
    setLastShiftAnchor(null);

    const sections = importPreview.detected_sections ?? [];
    const stem = importPreview.filename.replace(/\.[^.]+$/, '') || '文稿';
    const initial: DraftProject[] =
      sections.length > 1
        ? sections.map((sec, idx) => ({
            id: `proj_${idx}_${Date.now().toString(36)}`,
            title: sec.title || `${stem} (${idx + 1})`,
            pageIndices: Array.from(
              { length: Math.max(0, sec.end_page - sec.start_page + 1) },
              (_, k) => sec.start_page + k,
            ),
          }))
        : [
            {
              id: `proj_0_${Date.now().toString(36)}`,
              title: sections[0]?.title || stem,
              pageIndices: Array.from({ length: importPreview.page_count }, (_, i) => i),
            },
          ];

    setProjects(initial);
    setActiveProjId(initial[0]?.id ?? '');
    setActivePageIndex(initial[0]?.pageIndices[0] ?? 0);
  }, [activeModal, importPreview, defaultMode]);

  const activeProject = useMemo(
    () => projects.find((p) => p.id === activeProjId) ?? projects[0] ?? null,
    [projects, activeProjId],
  );

  if (activeModal !== 'document-import' || !importPreview) return null;

  const pages = importPreview.pages;
  const pageMeta = pages[activePageIndex] ?? pages[0];
  const pageW = pageMeta?.width_mm || 210;
  const pageH = pageMeta?.height_mm || 297;
  const activeCrop = cropRectsMm[String(activePageIndex)] ?? null;
  const isPdf = importPreview.file_type === 'pdf';

  const toPageMm = (clientX: number, clientY: number): { x: number; y: number } => {
    const el = paperRef.current;
    if (!el) return { x: 0, y: 0 };
    const rect = el.getBoundingClientRect();
    const nx = Math.max(0, Math.min(1, (clientX - rect.left) / Math.max(1, rect.width)));
    const ny = Math.max(0, Math.min(1, (clientY - rect.top) / Math.max(1, rect.height)));
    return {
      x: Number((nx * pageW).toFixed(1)),
      y: Number((ny * pageH).toFixed(1)),
    };
  };

  const handlePaperPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!isPdf || e.button !== 0) return;
    const pt = toPageMm(e.clientX, e.clientY);
    cropDragRef.current = {
      mode: 'draw',
      pageIndex: activePageIndex,
      startXmm: pt.x,
      startYmm: pt.y,
      origRect: [pt.x, pt.y, pt.x, pt.y],
    };
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const startBoxDrag = (
    e: React.PointerEvent,
    mode: 'move' | 'resize',
    handle?: CropHandle,
  ) => {
    if (!activeCrop) return;
    e.stopPropagation();
    const pt = toPageMm(e.clientX, e.clientY);
    cropDragRef.current = {
      mode,
      handle,
      pageIndex: activePageIndex,
      startXmm: pt.x,
      startYmm: pt.y,
      origRect: [...activeCrop] as [number, number, number, number],
    };
    paperRef.current?.setPointerCapture(e.pointerId);
  };

  const handlePaperPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const drag = cropDragRef.current;
    if (!drag) return;
    const pt = toPageMm(e.clientX, e.clientY);
    const dx = pt.x - drag.startXmm;
    const dy = pt.y - drag.startYmm;
    const [ox0, oy0, ox1, oy1] = drag.origRect;

    let nextRect: [number, number, number, number] = [ox0, oy0, ox1, oy1];
    if (drag.mode === 'draw') {
      nextRect = [
        Math.min(drag.startXmm, pt.x),
        Math.min(drag.startYmm, pt.y),
        Math.max(drag.startXmm, pt.x),
        Math.max(drag.startYmm, pt.y),
      ];
    } else if (drag.mode === 'move') {
      const bw = ox1 - ox0;
      const bh = oy1 - oy0;
      const x0 = Math.max(0, Math.min(pageW - bw, ox0 + dx));
      const y0 = Math.max(0, Math.min(pageH - bh, oy0 + dy));
      nextRect = [Number(x0.toFixed(1)), Number(y0.toFixed(1)), Number((x0 + bw).toFixed(1)), Number((y0 + bh).toFixed(1))];
    } else if (drag.mode === 'resize' && drag.handle) {
      let x0 = ox0;
      let y0 = oy0;
      let x1 = ox1;
      let y1 = oy1;
      const minSize = 15;
      if (drag.handle.includes('w')) x0 = Math.max(0, Math.min(x1 - minSize, ox0 + dx));
      if (drag.handle.includes('e')) x1 = Math.min(pageW, Math.max(x0 + minSize, ox1 + dx));
      if (drag.handle.includes('n')) y0 = Math.max(0, Math.min(y1 - minSize, oy0 + dy));
      if (drag.handle.includes('s')) y1 = Math.min(pageH, Math.max(y0 + minSize, oy1 + dy));
      nextRect = [Number(x0.toFixed(1)), Number(y0.toFixed(1)), Number(x1.toFixed(1)), Number(y1.toFixed(1))];
    }

    setCropRectsMm((prev) => ({ ...prev, [String(drag.pageIndex)]: nextRect }));
  };

  const handlePaperPointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    const drag = cropDragRef.current;
    if (!drag) return;
    cropDragRef.current = null;
    if (paperRef.current?.hasPointerCapture?.(e.pointerId)) {
      paperRef.current.releasePointerCapture(e.pointerId);
    }
    const r = cropRectsMm[String(drag.pageIndex)];
    if (drag.mode === 'draw' && r && (r[2] - r[0] < 12 || r[3] - r[1] < 12)) {
      setCropRectsMm((prev) => {
        const copy = { ...prev };
        delete copy[String(drag.pageIndex)];
        return copy;
      });
    }
  };

  const applyCropToPages = (targetPages: number[]) => {
    if (!activeCrop) return;
    setCropRectsMm((prev) => {
      const next = { ...prev };
      for (const pIdx of targetPages) {
        next[String(pIdx)] = [...activeCrop] as [number, number, number, number];
      }
      return next;
    });
  };

  const handleToggleSingleMode = () => {
    const stem = importPreview.filename.replace(/\.[^.]+$/, '') || '文稿';
    const allPages = Array.from({ length: importPreview.page_count }, (_, i) => i);
    const single: DraftProject = {
      id: `proj_all_${Date.now().toString(36)}`,
      title: stem,
      pageIndices: allPages,
    };
    setProjects([single]);
    setActiveProjId(single.id);
  };

  const handleApplyAutoSections = () => {
    const sections = importPreview.detected_sections ?? [];
    const stem = importPreview.filename.replace(/\.[^.]+$/, '') || '文稿';
    const splitList: DraftProject[] =
      sections.length > 0
        ? sections.map((sec, idx) => ({
            id: `proj_${idx}_${Date.now().toString(36)}`,
            title: sec.title || `${stem} (${idx + 1})`,
            pageIndices: Array.from(
              { length: Math.max(0, sec.end_page - sec.start_page + 1) },
              (_, k) => sec.start_page + k,
            ),
          }))
        : [
            {
              id: `proj_0_${Date.now().toString(36)}`,
              title: stem,
              pageIndices: Array.from({ length: importPreview.page_count }, (_, i) => i),
            },
          ];
    setProjects(splitList);
    setActiveProjId(splitList[0].id);
    setActivePageIndex(splitList[0].pageIndices[0] ?? 0);
  };

  const handleSplitAtActivePage = () => {
    if (!activeProject) return;
    const before = activeProject.pageIndices.filter((p) => p < activePageIndex);
    const after = activeProject.pageIndices.filter((p) => p >= activePageIndex);
    if (before.length === 0 || after.length === 0) return;

    const splitHeading = pages[activePageIndex]?.heading || `分段 P${activePageIndex + 1}`;
    const newProj: DraftProject = {
      id: `proj_${Date.now().toString(36)}`,
      title: splitHeading,
      pageIndices: after,
    };
    setProjects((prev) => {
      const out: DraftProject[] = [];
      for (const p of prev) {
        if (p.id === activeProject.id) {
          out.push({ ...p, pageIndices: before }, newProj);
        } else {
          out.push(p);
        }
      }
      return out;
    });
    setActiveProjId(newProj.id);
  };

  const handleTogglePageInActiveProject = (pageIdx: number, shiftKey: boolean) => {
    if (!activeProject) return;
    setProjects((prev) =>
      prev.map((proj) => {
        if (proj.id !== activeProject.id) return proj;
        const nextSet = new Set(proj.pageIndices);
        if (shiftKey && lastShiftAnchor !== null) {
          const lo = Math.min(lastShiftAnchor, pageIdx);
          const hi = Math.max(lastShiftAnchor, pageIdx);
          const shouldAdd = !nextSet.has(pageIdx);
          for (let i = lo; i <= hi; i++) {
            if (shouldAdd) nextSet.add(i);
            else nextSet.delete(i);
          }
        } else {
          if (nextSet.has(pageIdx)) {
            if (nextSet.size > 1) nextSet.delete(pageIdx);
          } else {
            nextSet.add(pageIdx);
          }
        }
        return { ...proj, pageIndices: Array.from(nextSet).sort((a, b) => a - b) };
      }),
    );
    setLastShiftAnchor(pageIdx);
  };

  const handleCommit = async () => {
    const valid = projects.filter((p) => p.pageIndices.length > 0);
    if (valid.length === 0) return;
    await commitImportPreview({
      mode_hint: modeHint,
      projects: valid.map((p) => {
        const subCrop: Record<string, [number, number, number, number]> = {};
        for (const pi of p.pageIndices) {
          const r = cropRectsMm[String(pi)];
          if (r) subCrop[String(pi)] = r;
        }
        return {
          title: p.title.trim() || importPreview.filename,
          page_indices: p.pageIndices,
          crop_rects_mm: subCrop,
          exclude_header_footer: excludeHeaderFooter,
        };
      }),
    });
  };

  const handleQuickImportFull = async () => {
    const stem = importPreview.filename.replace(/\.[^.]+$/, '') || '文稿';
    await commitImportPreview({
      mode_hint: modeHint,
      projects: [
        {
          title: stem,
          page_indices: Array.from({ length: importPreview.page_count }, (_, i) => i),
          crop_rects_mm: {},
          exclude_header_footer: excludeHeaderFooter,
        },
      ],
    });
  };

  const pageOwnerMap = new Map<number, number>();
  projects.forEach((p, idx) => {
    p.pageIndices.forEach((pi) => {
      if (!pageOwnerMap.has(pi)) pageOwnerMap.set(pi, idx);
    });
  });

  const validProjects = projects.filter((p) => p.pageIndices.length > 0);
  const totalSelectedPages = validProjects.reduce((acc, p) => acc + p.pageIndices.length, 0);

  return (
    <div
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="文档预解析与区域/项目切分"
      onClick={() => {
        if (!importPreviewCommitting) void cancelImportPreview();
      }}
    >
      <div className="import-modal-box" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div className="modal-title">
            <FileText size={16} style={{ color: 'var(--accent-primary)' }} />
            <span>文档预解析 · 选区与多项目拆分</span>
            <span className="tag-chip mono" style={{ margin: 0 }}>
              {importPreview.filename} · {importPreview.page_count} 页 · {importPreview.file_type.toUpperCase()}
            </span>
          </div>

          <div className="row-gap" style={{ gap: 8 }}>
            <div className="seg-group" style={{ padding: 2 }}>
              <button
                type="button"
                className={`seg-btn ${modeHint === 'reflow' ? 'active' : ''}`}
                style={{ padding: '3px 9px', fontSize: 11 }}
                onClick={() => setModeHint('reflow')}
              >
                智能重排
              </button>
              <button
                type="button"
                className={`seg-btn ${modeHint === 'overlay' ? 'active' : ''}`}
                style={{ padding: '3px 9px', fontSize: 11 }}
                onClick={() => setModeHint('overlay')}
              >
                原稿套打
              </button>
            </div>
            <button
              type="button"
              className="btn btn-xs btn-soft"
              disabled={importPreviewCommitting}
              onClick={() => void handleQuickImportFull()}
              title="跳过拆分与裁切，立即导入整份文档"
            >
              <Sparkles size={11} /> 直接导入全文
            </button>
            <button
              type="button"
              className="nudge-btn"
              disabled={importPreviewCommitting}
              onClick={() => void cancelImportPreview()}
              aria-label="关闭导入预览"
            >
              <X size={14} />
            </button>
          </div>
        </div>

        <div className="import-modal-grid">
          {/* Left Panel: Detected Sections & Multi-Project Split Plan */}
          <div className="import-split-col">
            <div className="row-between">
              <span style={{ fontSize: 12, fontWeight: 700 }}>切分项目列表 ({projects.length})</span>
              <div className="row-gap" style={{ gap: 4 }}>
                <button
                  type="button"
                  className="btn btn-xs"
                  onClick={handleApplyAutoSections}
                  title="恢复按检测到的实验/章节自动拆分（每份实验报告独立成一个文档）"
                >
                  按实验拆分
                </button>
                <button
                  type="button"
                  className="btn btn-xs"
                  onClick={handleToggleSingleMode}
                  title="合并为 1 份完整一体文档项目"
                >
                  合并整篇 (1份报告)
                </button>
              </div>
            </div>

            {importPreview.detected_sections.length > 1 && (
              <div style={{ fontSize: 11, color: 'var(--accent-primary)', lineHeight: 1.4 }}>
                已自动识别到 {importPreview.detected_sections.length} 个独立章节/实验，可直接分别解析为多个独立文稿项目：
              </div>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
              {projects.map((proj, idx) => {
                const isActive = proj.id === activeProject?.id;
                const minP = Math.min(...proj.pageIndices);
                const maxP = Math.max(...proj.pageIndices);
                return (
                  <div
                    key={proj.id}
                    className={`import-proj-card ${isActive ? 'active' : ''}`}
                    onClick={() => {
                      setActiveProjId(proj.id);
                      if (proj.pageIndices.length > 0 && !proj.pageIndices.includes(activePageIndex)) {
                        setActivePageIndex(proj.pageIndices[0]);
                      }
                    }}
                  >
                    <div className="row-between" style={{ gap: 5 }}>
                      <span className="mono" style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--accent-primary)' }}>
                        #{idx + 1} · {proj.pageIndices.length} 页 ({minP === maxP ? `P${minP + 1}` : `P${minP + 1}-P${maxP + 1}`})
                      </span>
                      <div className="row-gap" style={{ gap: 3 }} onClick={(e) => e.stopPropagation()}>
                        {idx > 0 && (
                          <button
                            type="button"
                            className="nudge-btn"
                            title="合并到上一个项目"
                            onClick={() => {
                              setProjects((prev) => {
                                const merged = Array.from(
                                  new Set([...prev[idx - 1].pageIndices, ...proj.pageIndices]),
                                ).sort((a, b) => a - b);
                                return prev
                                  .map((item, k) => (k === idx - 1 ? { ...item, pageIndices: merged } : item))
                                  .filter((_, k) => k !== idx);
                              });
                              setActiveProjId(projects[idx - 1].id);
                            }}
                          >
                            <Merge size={11} />
                          </button>
                        )}
                        {projects.length > 1 && (
                          <button
                            type="button"
                            className="nudge-btn"
                            title="删除此拆分项目"
                            onClick={() => {
                              const next = projects.filter((item) => item.id !== proj.id);
                              setProjects(next);
                              if (isActive && next[0]) setActiveProjId(next[0].id);
                            }}
                          >
                            <Trash2 size={11} />
                          </button>
                        )}
                      </div>
                    </div>

                    <input
                      type="text"
                      value={proj.title}
                      onClick={(e) => e.stopPropagation()}
                      onChange={(e) => {
                        const val = e.target.value;
                        setProjects((prev) =>
                          prev.map((item) => (item.id === proj.id ? { ...item, title: val } : item)),
                        );
                      }}
                      placeholder="输入独立项目名称"
                      style={{ fontSize: 11.5, padding: '4px 7px', fontWeight: 600 }}
                    />
                  </div>
                );
              })}
            </div>

            <div className="grid-2" style={{ marginTop: 2 }}>
              <button
                type="button"
                className="btn btn-xs btn-soft"
                onClick={() => {
                  const newP: DraftProject = {
                    id: `proj_${Date.now().toString(36)}`,
                    title: `自定义项目 #${projects.length + 1}`,
                    pageIndices: [activePageIndex],
                  };
                  setProjects((prev) => [...prev, newP]);
                  setActiveProjId(newP.id);
                }}
              >
                <Plus size={11} /> 新增项目
              </button>
              <button
                type="button"
                className="btn btn-xs"
                disabled={
                  !activeProject ||
                  !activeProject.pageIndices.includes(activePageIndex) ||
                  activeProject.pageIndices.filter((p) => p < activePageIndex).length === 0
                }
                onClick={handleSplitAtActivePage}
                title="从当前预览页把当前项目一分为二"
              >
                <Scissors size={11} /> 从当前页拆分
              </button>
            </div>
          </div>

          {/* Center Panel: Interactive Crop & Preview */}
          <div className="import-crop-col">
            <div className="import-crop-toolbar">
              <div className="row-gap" style={{ gap: 6 }}>
                <span className="mono" style={{ fontSize: 11.5, fontWeight: 700 }}>
                  P{activePageIndex + 1} / {importPreview.page_count}
                </span>
                <span className="mono" style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  {activeCrop
                    ? `解析选区: X ${activeCrop[0]}~${activeCrop[2]} · Y ${activeCrop[1]}~${activeCrop[3]} mm`
                    : isPdf
                      ? `全页解析 (${Math.round(pageW)}×${Math.round(pageH)} mm，在图中拖框可裁切解析区域)`
                      : 'Word/Markdown 文本节预览'}
                </span>
              </div>

              <div className="row-gap" style={{ gap: 6 }}>
                {isPdf && activeCrop && activeProject && (
                  <>
                    <button
                      type="button"
                      className="btn btn-xs btn-soft"
                      onClick={() => applyCropToPages(activeProject.pageIndices)}
                    >
                      <Crop size={11} /> 应用到本项目页
                    </button>
                    <button
                      type="button"
                      className="btn btn-xs"
                      onClick={() =>
                        applyCropToPages(Array.from({ length: importPreview.page_count }, (_, i) => i))
                      }
                    >
                      应用选区到全部页
                    </button>
                    <button
                      type="button"
                      className="btn btn-xs"
                      onClick={() =>
                        setCropRectsMm((prev) => {
                          const next = { ...prev };
                          delete next[String(activePageIndex)];
                          return next;
                        })
                      }
                    >
                      <RotateCcw size={11} /> 重置本页
                    </button>
                  </>
                )}

                <label className="row-gap" style={{ fontSize: 11, cursor: 'pointer', color: 'var(--text-secondary)' }}>
                  <input
                    type="checkbox"
                    checked={excludeHeaderFooter}
                    onChange={(e) => setExcludeHeaderFooter(e.target.checked)}
                  />
                  自动排除页眉页脚 (上8%/下8%)
                </label>
              </div>
            </div>

            <div className="import-crop-stage">
              <div
                ref={paperRef}
                className="import-crop-paper"
                onPointerDown={handlePaperPointerDown}
                onPointerMove={handlePaperPointerMove}
                onPointerUp={handlePaperPointerUp}
                onPointerCancel={handlePaperPointerUp}
              >
                <img
                  src={restClient.getPreviewThumbUrl(importPreview.preview_id, activePageIndex, 150)}
                  alt={`第 ${activePageIndex + 1} 页预览`}
                />

                {excludeHeaderFooter && (
                  <>
                    <div className="import-hf-line" style={{ top: '8%' }} />
                    <div className="import-hf-line" style={{ top: '92%' }} />
                  </>
                )}

                {isPdf && activeCrop && (
                  <div
                    className="import-crop-box"
                    style={{
                      left: `${(activeCrop[0] / pageW) * 100}%`,
                      top: `${(activeCrop[1] / pageH) * 100}%`,
                      width: `${((activeCrop[2] - activeCrop[0]) / pageW) * 100}%`,
                      height: `${((activeCrop[3] - activeCrop[1]) / pageH) * 100}%`,
                    }}
                    onPointerDown={(e) => startBoxDrag(e, 'move')}
                  >
                    {HANDLES.map((h) => (
                      <div
                        key={h.key}
                        className="import-crop-handle"
                        style={{ left: h.left, top: h.top, cursor: h.cursor }}
                        onPointerDown={(e) => startBoxDrag(e, 'resize', h.key)}
                      />
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Bottom Page Thumbnails + Checkboxes */}
        <div className="import-thumb-strip" aria-label="页面缩略图选择条">
          {pages.map((p) => {
            const isViewing = p.page_index === activePageIndex;
            const inActiveProj = Boolean(activeProject?.pageIndices.includes(p.page_index));
            const hasCrop = Boolean(cropRectsMm[String(p.page_index)]);
            const ownerIdx = pageOwnerMap.get(p.page_index);
            return (
              <div
                key={p.page_index}
                className={`import-thumb-item ${isViewing ? 'active' : ''} ${inActiveProj ? 'in-proj' : ''}`}
                onClick={() => setActivePageIndex(p.page_index)}
                title={`${p.heading || `第 ${p.page_index + 1} 页`}${p.snippet ? `\n${p.snippet}` : ''}\n提示：勾选可将此页加入当前选中项目（按住 Shift 连续多选）`}
              >
                <img
                  src={restClient.getPreviewThumbUrl(importPreview.preview_id, p.page_index, 96)}
                  alt={`P${p.page_index + 1}`}
                  loading="lazy"
                />
                {hasCrop && <span className="import-thumb-badge">裁</span>}
                <div className="row-between" style={{ width: '100%', padding: '0 2px' }}>
                  <label
                    className="row-gap"
                    style={{ gap: 3, cursor: 'pointer', fontSize: 10.5 }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <input
                      type="checkbox"
                      checked={inActiveProj}
                      onChange={() => undefined}
                      onClick={(e) => handleTogglePageInActiveProject(p.page_index, e.shiftKey)}
                    />
                    <span className="mono" style={{ fontWeight: 700 }}>
                      P{p.page_index + 1}
                    </span>
                  </label>
                  {ownerIdx !== undefined && projects.length > 1 && (
                    <span className="mono" style={{ fontSize: 9.5, color: 'var(--accent-primary)' }}>
                      #{ownerIdx + 1}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        <div className="modal-foot" style={{ justifyContent: 'space-between' }}>
          <span style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}>
            将导入 <strong>{validProjects.length}</strong> 个独立项目，共{' '}
            <strong className="mono">{totalSelectedPages}</strong> 页 · 支持按 Shift 批量勾选页面
          </span>
          <div className="row-gap" style={{ gap: 8 }}>
            <button
              type="button"
              className="btn btn-sm"
              disabled={importPreviewCommitting}
              onClick={() => void cancelImportPreview()}
            >
              取消
            </button>
            <button
              type="button"
              className="btn btn-sm btn-primary"
              disabled={importPreviewCommitting || validProjects.length === 0}
              onClick={() => void handleCommit()}
            >
              <CheckSquare size={13} />
              <span>
                {importPreviewCommitting
                  ? '正在提交解析…'
                  : `开始解析导入 (${validProjects.length} 个项目)`}
              </span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
