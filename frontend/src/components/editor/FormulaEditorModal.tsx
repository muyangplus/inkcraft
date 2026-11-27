import React, { useEffect, useState } from 'react';
import { RefreshCw, Sigma, Sparkles, X } from 'lucide-react';
import { restClient } from '../../api/restClient';
import type { MathPreviewResponse } from '../../api/types';
import { useDocumentLayoutStore } from '../../stores/useDocumentLayoutStore';
import { useViewportStore } from '../../stores/useViewportStore';
import { useWriterStore } from '../../stores/useWriterStore';

const FORMULA_SNIPPETS: Array<{ label: string; tex: string }> = [
  { label: '分式 a/b', tex: '\\frac{a}{b}' },
  { label: '求和 Σ', tex: '\\sum_{i=1}^{n}' },
  { label: '积分 ∫', tex: '\\int_{a}^{b}' },
  { label: '根号 √', tex: '\\sqrt{x}' },
  { label: '乘号 ×', tex: '\\times' },
  { label: 'Delta Δ', tex: '\\Delta' },
  { label: 'rho ρ', tex: '\\rho' },
  { label: '下标 _{i}', tex: '_{i}' },
  { label: '百分号 \\%', tex: '\\%' },
  { label: '中文 \\text{}', tex: '\\text{中文}' },
];

export const FormulaEditorModal: React.FC = () => {
  const target = useViewportStore((s) => s.formulaEditorTarget);
  const closeFormulaEditor = useViewportStore((s) => s.closeFormulaEditor);
  const inkColor = useViewportStore((s) => s.inkColor);
  const pushToast = useViewportStore((s) => s.pushToast);

  const blocks = useDocumentLayoutStore((s) => s.blocks);
  const patchDocumentBlock = useDocumentLayoutStore((s) => s.patchDocumentBlock);
  const reRecognizeFormulaBlock = useDocumentLayoutStore((s) => s.reRecognizeFormulaBlock);
  const activeWriterId = useWriterStore((s) => s.activeWriterId);

  const [latex, setLatex] = useState('');
  const [preview, setPreview] = useState<MathPreviewResponse | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [recognizing, setRecognizing] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (target) {
      setLatex(target.initialLatex || '');
    }
  }, [target]);

  useEffect(() => {
    if (!target) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setLoadingPreview(true);
      void restClient
        .previewMath({
          latex: latex || '\\text{ }',
          writer_id: activeWriterId,
          font_size_mm: 7.5,
          formula_scale: 0.95,
          display: target.inlineIndex === null,
        })
        .then((res) => {
          if (!cancelled) setPreview(res);
        })
        .catch(() => {
          if (!cancelled) setPreview(null);
        })
        .finally(() => {
          if (!cancelled) setLoadingPreview(false);
        });
    }, 160);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [target, latex, activeWriterId]);

  if (!target) return null;

  const blk = blocks.find((b) => b.block_id === target.blockId) ?? null;
  const assetName = target.assetName ?? blk?.asset_name ?? null;

  const insertSnippet = (snippet: string) => {
    setLatex((cur) => (cur ? `${cur} ${snippet}` : snippet));
  };

  const handleReRecognize = async () => {
    if (!target) return;
    setRecognizing(true);
    try {
      const updated = await reRecognizeFormulaBlock(target.blockId);
      if (updated?.latex) {
        setLatex(updated.latex);
        pushToast('已重新识别公式 LaTeX', 'success');
      }
    } finally {
      setRecognizing(false);
    }
  };

  const handleSave = async () => {
    const trimmed = latex.trim();
    if (!trimmed) {
      pushToast('公式 LaTeX 不能为空', 'warn');
      return;
    }
    setSaving(true);
    try {
      if (target.inlineIndex !== null && blk?.inlines) {
        const nextInlines = blk.inlines.map((inl, idx) =>
          idx === target.inlineIndex ? { t: 'math' as const, latex: trimmed } : inl,
        );
        const ok = await patchDocumentBlock(target.blockId, { inlines: nextInlines });
        if (ok) {
          pushToast('已保存行内公式并更新手写排版', 'success');
          closeFormulaEditor();
        }
      } else {
        const ok = await patchDocumentBlock(target.blockId, {
          type: 'formula_block',
          latex: trimmed,
        });
        if (ok) {
          pushToast('已保存公式并重排手写预览', 'success');
          closeFormulaEditor();
        }
      }
    } finally {
      setSaving(false);
    }
  };

  const svgW = Math.max(20, preview?.width_mm ?? 60);
  const svgH = Math.max(12, preview?.height_mm ?? 20);

  return (
    <div
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="手写公式 LaTeX 编辑器"
      onClick={(e) => {
        if (e.target === e.currentTarget) closeFormulaEditor();
      }}
    >
      <div className="modal-box formula-modal-card">
        <div className="modal-head">
          <div className="row-gap" style={{ gap: 7 }}>
            <Sigma size={16} style={{ color: '#7C3AED' }} />
            <span className="modal-title">
              公式双击精修 · {target.inlineIndex !== null ? '行内公式' : '独立公式块'}
            </span>
          </div>
          <button type="button" className="nudge-btn" onClick={closeFormulaEditor} title="关闭">
            <X size={14} />
          </button>
        </div>

        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div className="formula-compare-grid">
            {assetName && (
              <div className="formula-pane">
                <div className="row-between">
                  <span className="formula-pane-label">原文档公式裁剪图</span>
                  <button
                    type="button"
                    className="btn btn-xs"
                    disabled={recognizing}
                    onClick={() => void handleReRecognize()}
                  >
                    <RefreshCw size={11} className={recognizing ? 'spin' : ''} />
                    {recognizing ? '识别中…' : '重新 OCR 识别'}
                  </button>
                </div>
                <div className="formula-img-box">
                  <img
                    src={restClient.getDocumentAssetUrl(target.docId, assetName)}
                    alt="原文档公式"
                  />
                </div>
              </div>
            )}

            <div className="formula-pane" style={!assetName ? { gridColumn: '1 / -1' } : undefined}>
              <div className="row-between">
                <span className="formula-pane-label">实时手写笔迹预览</span>
                <span className="mono" style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>
                  {loadingPreview
                    ? '计算中…'
                    : preview?.ok
                      ? `${preview.strokes.length} 笔 · ${svgW.toFixed(1)}×${svgH.toFixed(1)} mm`
                      : '待检查语法'}
                </span>
              </div>
              <div className="formula-svg-box">
                <svg
                  viewBox={`0 0 ${svgW} ${svgH}`}
                  preserveAspectRatio="xMidYMid meet"
                  style={{ width: '100%', height: '100%', maxHeight: 112 }}
                >
                  {(preview?.strokes ?? []).map((pts, idx) => {
                    const polyPts: string[] = [];
                    for (let i = 0; i + 1 < pts.length; i += 2) {
                      polyPts.push(`${pts[i]},${pts[i + 1]}`);
                    }
                    return (
                      <polyline
                        key={idx}
                        fill="none"
                        stroke={inkColor}
                        strokeWidth={0.42}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        points={polyPts.join(' ')}
                      />
                    );
                  })}
                </svg>
              </div>
              {preview?.error && (
                <div style={{ fontSize: 11, color: 'var(--state-danger)' }}>
                  解析提示：{preview.error}
                </div>
              )}
            </div>
          </div>

          <div className="mini-field">
            <div className="row-between">
              <span>LaTeX 公式代码（支持中文 `\text{'{...}'}` 与 `\begin{'{aligned}'}`）</span>
              <span className="mono" style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>
                {target.blockId}
              </span>
            </div>
            <textarea
              rows={3}
              className="mono"
              value={latex}
              onChange={(e) => setLatex(e.target.value)}
              placeholder="输入或修正 LaTeX 公式，如：\frac{V_i C_i}{V_s \rho_s} \times 100\%"
              style={{ width: '100%', fontSize: 12.5, padding: '8px 10px', lineHeight: 1.5 }}
            />
          </div>

          <div className="formula-snippets">
            {FORMULA_SNIPPETS.map((s) => (
              <button
                key={s.label}
                type="button"
                className="btn btn-xs"
                onClick={() => insertSnippet(s.tex)}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>

        <div className="modal-foot">
          <button type="button" className="btn" onClick={closeFormulaEditor}>
            取消
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={saving}
            onClick={() => void handleSave()}
          >
            <Sparkles size={13} />
            {saving ? '保存并重排中…' : '保存公式并刷新画布'}
          </button>
        </div>
      </div>
    </div>
  );
};
