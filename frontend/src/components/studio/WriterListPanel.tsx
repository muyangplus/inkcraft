import React, { useEffect, useRef, useState } from 'react';
import { AlertCircle, Check, Eye, Plus, Trash2, Upload } from 'lucide-react';
import type { GlyphVariantsResponse, HwFontMeta } from '../../api/types';
import { useDocumentLayoutStore } from '../../stores/useDocumentLayoutStore';
import { useMachineStore } from '../../stores/useMachineStore';
import { useViewportStore } from '../../stores/useViewportStore';
import { useWriterStore } from '../../stores/useWriterStore';

const WriterThumbCanvas: React.FC<{
  writer: HwFontMeta;
  glyphData?: GlyphVariantsResponse;
}> = ({ writer, glyphData }) => {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const size = 44;
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    ctx.fillStyle = '#FAF7F0';
    ctx.fillRect(0, 0, size, size);

    // Subtle baseline & center cross
    ctx.strokeStyle = 'rgba(148, 163, 184, 0.25)';
    ctx.lineWidth = 0.7;
    ctx.beginPath();
    ctx.moveTo(0, size * 0.8);
    ctx.lineTo(size, size * 0.8);
    ctx.moveTo(size * 0.5, 0);
    ctx.lineTo(size * 0.5, size);
    ctx.stroke();

    const variant = glyphData?.variants?.[0];
    if (variant && variant.strokes.length > 0) {
      const pad = 4;
      const scale = (size - pad * 2) / (writer.units_per_em || 1000);
      ctx.strokeStyle = '#1B365D';
      ctx.lineWidth = 1.45;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.beginPath();
      for (const stroke of variant.strokes) {
        if (stroke.length < 4) continue;
        ctx.moveTo(pad + stroke[0] * scale, pad + stroke[1] * scale);
        for (let i = 2; i < stroke.length; i += 2) {
          ctx.lineTo(pad + stroke[i] * scale, pad + stroke[i + 1] * scale);
        }
      }
      ctx.stroke();
    } else {
      ctx.fillStyle = '#1B365D';
      ctx.font = '600 22px "Noto Sans SC", serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(writer.preview_char || '永', size / 2, size / 2 + 1);
    }
  }, [writer, glyphData]);

  return <canvas ref={ref} className="writer-thumb" />;
};

export const WriterListPanel: React.FC<{ embedded?: boolean }> = ({ embedded = false }) => {
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const writers = useWriterStore((s) => s.writers);
  const activeWriterId = useWriterStore((s) => s.activeWriterId);
  const uploading = useWriterStore((s) => s.uploading);
  const glyphCache = useWriterStore((s) => s.glyphCache);
  const coverage = useWriterStore((s) => s.coverage);
  const selectWriter = useWriterStore((s) => s.selectWriter);
  const uploadWriterFile = useWriterStore((s) => s.uploadWriterFile);
  const deleteWriter = useWriterStore((s) => s.deleteWriter);
  const fetchCoverage = useWriterStore((s) => s.fetchCoverage);

  const currentDoc = useDocumentLayoutStore((s) => s.currentDoc);
  const layout = useDocumentLayoutStore((s) => s.layout);
  const currentPageIndex = useDocumentLayoutStore((s) => s.currentPageIndex);
  const fallbackPolicy = useDocumentLayoutStore((s) => s.config.fallback.policy);
  const updateConfig = useDocumentLayoutStore((s) => s.updateConfig);
  const composeNow = useDocumentLayoutStore((s) => s.composeNow);

  const machineState = useMachineStore((s) => s.machineState);
  const appMode = useViewportStore((s) => s.appMode);
  const openGlyphInspector = useViewportStore((s) => s.openGlyphInspector);
  const openModal = useViewportStore((s) => s.openModal);

  const isJobLocked =
    machineState === 'RUNNING' ||
    machineState === 'HOLDING' ||
    machineState === 'PAUSED' ||
    machineState === 'PEN_CHANGE' ||
    machineState === 'PAPER_CHANGE';

  const activeWriter = writers.find((w) => w.writer_id === activeWriterId) ?? writers[0];
  const pageFallbacks = layout?.pages[currentPageIndex]?.fallback_glyphs ?? [];

  const handleSelect = async (writerId: string) => {
    if (isJobLocked) return;
    await selectWriter(writerId);
    void composeNow(writerId);
    if (currentDoc) {
      void fetchCoverage(writerId, currentDoc.doc_id);
    }
  };

  const handleFiles = async (files: FileList | null) => {
    const file = files?.[0];
    if (!file) return;
    await uploadWriterFile(file);
  };

  const covItems = activeWriter
    ? [
        { label: '汉字', val: activeWriter.coverage?.cjk ?? 0, max: Math.max(100, activeWriter.coverage?.cjk ?? 0, 500) },
        { label: '英文', val: activeWriter.coverage?.latin ?? 0, max: 52 },
        { label: '数字', val: activeWriter.coverage?.digit ?? 0, max: 10 },
        { label: '标点', val: activeWriter.coverage?.punct ?? 0, max: 40 },
        { label: '符号', val: activeWriter.coverage?.symbol ?? 0, max: 50 },
      ]
    : [];

  const docCovPct =
    coverage && coverage.unique_chars > 0
      ? Math.round((coverage.covered / coverage.unique_chars) * 1000) / 10
      : 100;

  const content = (
    <>
      <div className="section-card">
        <div className="section-head">
          <span>书写人 .hwfont 热切换</span>
          <div className="row-gap" style={{ gap: 4 }}>
            <button
              className="btn btn-xs btn-primary"
              onClick={() => openModal('font-builder')}
              title="本机 GPU/CPU 离线构建或 Google Colab 云端构建新笔迹"
            >
              <Plus size={11} /> 构建新笔迹
            </button>
            <button
              className="btn btn-xs"
              disabled={!activeWriterId}
              onClick={() => openGlyphInspector(activeWriter?.preview_char || '永')}
            >
              <Eye size={11} /> 字形
            </button>
          </div>
        </div>

        {(() => {
          const isBuiltinWriter = (w: HwFontMeta) =>
            (w.builder || '').includes('generate_demo_writers');
          const userWriters = writers.filter((w) => !isBuiltinWriter(w));
          const builtinWriters = writers.filter((w) => isBuiltinWriter(w));

          const renderWriterCard = (w: HwFontMeta, isBuiltin: boolean) => {
            const isActive = w.writer_id === activeWriterId;
            const cacheKey = `${w.writer_id}:${w.preview_char || '永'}`;
            return (
              <div
                key={w.writer_id}
                className={`writer-card ${isActive ? 'active' : ''}`}
                style={isJobLocked && !isActive ? { opacity: 0.6, cursor: 'not-allowed' } : undefined}
                onClick={() => void handleSelect(w.writer_id)}
                title={isJobLocked ? '书写作业进行中，禁止切换书写人' : `切换到 ${w.writer_name}`}
              >
                <WriterThumbCanvas writer={w} glyphData={glyphCache[cacheKey]} />
                <div style={{ minWidth: 0 }}>
                  <div className="writer-name">
                    <span
                      style={{
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {w.writer_name}
                      {w.writer_alias ? (
                        <span style={{ color: 'var(--text-muted)', fontWeight: 400, marginLeft: 4 }}>
                          · {w.writer_alias}
                        </span>
                      ) : null}
                    </span>
                    <span className="row-gap" style={{ gap: 3 }}>
                      {isBuiltin && (
                        <span className="tag-chip" style={{ margin: 0, fontSize: 9.5 }}>
                          内置演示
                        </span>
                      )}
                      {isActive && <Check size={13} style={{ color: 'var(--accent-primary)' }} />}
                      {!isActive && !isJobLocked && (
                        <button
                          className="nudge-btn"
                          title="删除该笔迹文件"
                          onClick={(e) => {
                            e.stopPropagation();
                            if (window.confirm(`确认删除笔迹文件「${w.writer_name}」吗？`)) {
                              void deleteWriter(w.writer_id);
                            }
                          }}
                        >
                          <Trash2 size={10} />
                        </button>
                      )}
                    </span>
                  </div>
                  <div className="writer-meta mono">
                    {w.glyph_count.toLocaleString()} 字 · {w.variant_count.toLocaleString()} 变体
                  </div>
                  <div>
                    {(w.style_tags || []).slice(0, 3).map((tag) => (
                      <span key={tag} className="tag-chip">
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            );
          };

          if (writers.length === 0) {
            return (
              <div style={{ color: 'var(--text-muted)', fontSize: 11.5, padding: '8px 2px' }}>
                未检测到 `.hwfont` 笔迹文件，请在下方拖入导入或点击「构建新笔迹」。
              </div>
            );
          }

          return (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <div style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.03em' }}>
                  我的实际笔迹 ({userWriters.length})
                </div>
                {userWriters.length === 0 ? (
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: '6px 8px', background: 'var(--bg-subtle)', borderRadius: 8 }}>
                    尚未导入个人笔迹，可拖入 `.hwfont` 或点击上方「构建新笔迹」本地/云端生成。
                  </div>
                ) : (
                  userWriters.map((w) => renderWriterCard(w, false))
                )}
              </div>

              {appMode === 'demo' && builtinWriters.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.03em' }}>
                    内置演示笔迹 ({builtinWriters.length})
                  </div>
                  {builtinWriters.map((w) => renderWriterCard(w, true))}
                </div>
              )}
            </div>
          );
        })()}

        <div
          className={`dropzone ${dragOver ? 'dragover' : ''}`}
          onClick={() => fileRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            void handleFiles(e.dataTransfer.files);
          }}
        >
          <Upload size={14} />
          <span>{uploading ? '正在校验并导入 .hwfont…' : '拖入或点击导入 .hwfont 笔迹文件'}</span>
          <input
            ref={fileRef}
            type="file"
            accept=".hwfont"
            style={{ display: 'none' }}
            onChange={(e) => {
              void handleFiles(e.target.files);
              e.target.value = '';
            }}
          />
        </div>
      </div>

      {activeWriter && (
        <div className="section-card">
          <div className="section-head">
            <span>字库覆盖率 (Contract Meta)</span>
            <span className="mono" style={{ color: 'var(--text-primary)' }}>
              {docCovPct.toFixed(1)}%
            </span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            {covItems.map((it) => {
              const pct = Math.min(100, Math.round((it.val / Math.max(1, it.max)) * 100));
              return (
                <div key={it.label} className="cov-bar-row mono">
                  <span>{it.label}</span>
                  <div className="bar-track">
                    <div className="bar-fill" style={{ width: `${pct}%` }} />
                  </div>
                  <span style={{ textAlign: 'right' }}>{it.val}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="fallback-box">
        <div className="row-between">
          <span className="row-gap" style={{ fontWeight: 700, color: 'var(--fallback-text)', fontSize: 11.5 }}>
            <AlertCircle size={13} />
            缺字回退 ({pageFallbacks.length})
          </span>
          <select
            style={{ width: 132, padding: '2px 5px', fontSize: 11 }}
            value={fallbackPolicy}
            onChange={(e) =>
              updateConfig(
                (prev) => ({
                  ...prev,
                  fallback: {
                    policy: e.target.value as 'blank' | 'builtin_single_line' | 'skip' | 'box',
                  },
                }),
                true,
              )
            }
          >
            <option value="blank">留空格（默认，不写）</option>
            <option value="skip">跳过不占位</option>
            <option value="builtin_single_line">内置单线回退</option>
            <option value="box">空框占位</option>
          </select>
        </div>

        {pageFallbacks.length === 0 ? (
          <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
            当前页所有字符均已命中书写人字库，无缺字告警。
          </div>
        ) : (
          <>
            <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
              {fallbackPolicy === 'blank'
                ? '以下字库未收录字符将自动留空（仅前进字宽不落笔），点击可查看详情：'
                : '点击缺字胶囊在字形检测器中查看回退详情：'}
            </div>
            <div className="fallback-chips">
              {pageFallbacks.slice(0, 16).map((fg) => (
                <button
                  key={fg.char}
                  className="fallback-chip"
                  onClick={() => openGlyphInspector(fg.char)}
                >
                  <span>{fg.char}</span>
                  <span className="mono" style={{ opacity: 0.85 }}>
                    ×{fg.count}
                  </span>
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </>
  );

  return embedded ? content : <div className="panel-scroll">{content}</div>;
};
