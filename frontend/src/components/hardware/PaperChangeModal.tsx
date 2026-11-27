import React, { useEffect, useRef } from 'react';
import { ArrowUp, CheckCircle2, FileText, Scan, XCircle } from 'lucide-react';
import { useDocumentLayoutStore } from '../../stores/useDocumentLayoutStore';
import { useMachineStore } from '../../stores/useMachineStore';
import { useViewportStore } from '../../stores/useViewportStore';

/**
 * Multi-page Paper Change Safety Modal.
 * Intentionally CANNOT be dismissed by clicking the backdrop or pressing Esc —
 * requires explicit operator confirmation after physically replacing the sheet.
 */
export const PaperChangeModal: React.FC = () => {
  const activeModal = useViewportStore((s) => s.activeModal);
  const nextPage = useViewportStore((s) => s.paperChangeNextPage);
  const completedPage = useViewportStore((s) => s.paperChangeCompletedPage);

  const layout = useDocumentLayoutStore((s) => s.layout);
  const ensurePagePaths = useDocumentLayoutStore((s) => s.ensurePagePaths);

  const machineState = useMachineStore((s) => s.machineState);
  const confirmPaperReady = useMachineStore((s) => s.confirmPaperReady);
  const frameCheck = useMachineStore((s) => s.frameCheck);
  const setPen = useMachineStore((s) => s.setPen);
  const abortJob = useMachineStore((s) => s.abortJob);

  const thumbRef = useRef<HTMLCanvasElement>(null);
  const isOpen = activeModal === 'paper-change';

  useEffect(() => {
    if (!isOpen || !layout) return;
    let cancelled = false;

    void ensurePagePaths(layout.layout_id, nextPage).then((paths) => {
      if (cancelled || !paths || !thumbRef.current) return;
      const canvas = thumbRef.current;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const cw = 152;
      const ch = Math.round((cw * paths.heightMm) / Math.max(1, paths.widthMm));
      canvas.width = cw * dpr;
      canvas.height = ch * dpr;
      canvas.style.width = `${cw}px`;
      canvas.style.height = `${ch}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      ctx.fillStyle = '#FAF7F0';
      ctx.fillRect(0, 0, cw, ch);

      const scale = cw / Math.max(1, paths.widthMm);
      ctx.save();
      ctx.scale(scale, scale);
      ctx.strokeStyle = '#1B365D';
      ctx.lineWidth = Math.max(0.45, 0.8 / scale);
      ctx.lineCap = 'round';
      ctx.beginPath();
      const { data, vertexCount } = paths;
      for (let i = 0; i < vertexCount; i++) {
        const b = i * 3;
        if (data[b + 2] === 0) ctx.moveTo(data[b], data[b + 1]);
        else ctx.lineTo(data[b], data[b + 1]);
      }
      ctx.stroke();
      ctx.restore();
    });

    return () => {
      cancelled = true;
    };
  }, [isOpen, layout, nextPage, ensurePagePaths]);

  if (!isOpen) return null;

  const pageCount = layout?.page_count ?? nextPage + 1;
  const doneStats = layout?.pages[completedPage]?.stats;
  const nextStats = layout?.pages[nextPage]?.stats;

  return (
    <div className="modal-backdrop">
      <div className="modal-box" style={{ width: 590 }}>
        <div className="modal-head">
          <div className="modal-title" style={{ color: 'var(--state-warn)' }}>
            <FileText size={16} /> 第 {completedPage + 1} 页已书写完成 — 请更换空白新纸
          </div>
          <span className="mono" style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            PAPER_CHANGE · WAIT_PAPER
          </span>
        </div>

        <div className="modal-body">
          <div style={{ display: 'grid', gridTemplateColumns: '162px 1fr', gap: 16, alignItems: 'center' }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
              <canvas
                ref={thumbRef}
                width={152}
                height={214}
                style={{
                  background: '#FAF7F0',
                  borderRadius: 4,
                  border: '1px solid var(--border-strong)',
                }}
              />
              <span className="mono" style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                下一页：第 {nextPage + 1} / {pageCount} 页
              </span>
              {nextStats && (
                <span className="mono" style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>
                  {nextStats.stroke_count} 笔 · 预计 {Math.round(nextStats.est_s)}s
                </span>
              )}
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div
                style={{
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 7,
                  padding: 11,
                  fontSize: 12,
                  lineHeight: 1.6,
                }}
              >
                <div>
                  写字机已自动<strong>抬笔并回停靠位</strong>。
                  {doneStats && (
                    <span className="mono" style={{ color: 'var(--text-muted)', marginLeft: 6 }}>
                      (本页实绘 {(doneStats.draw_mm / 1000).toFixed(2)}m)
                    </span>
                  )}
                </div>
                <div style={{ color: 'var(--text-secondary)', marginTop: 6 }}>
                  1. 取出已书写完成的第 {completedPage + 1} 页纸张；
                  <br />
                  2. 放好第 {nextPage + 1} 页空白新纸并对齐压紧边角；
                  <br />
                  3. 可先点击下方“试跑外框”确认新纸未放歪，再继续书写。
                </div>
              </div>

              <div className="row-gap">
                <button
                  className="btn btn-cyan btn-sm"
                  disabled={!layout || machineState === 'FRAMING'}
                  onClick={() => {
                    if (layout) void frameCheck(layout.layout_id, nextPage);
                  }}
                >
                  <Scan size={12} /> 试跑第 {nextPage + 1} 页外框
                </button>
                <button className="btn btn-sm" onClick={() => void setPen('up')}>
                  <ArrowUp size={12} /> 确认抬笔避让
                </button>
              </div>
            </div>
          </div>
        </div>

        <div className="modal-foot" style={{ justifyContent: 'space-between' }}>
          <button
            className="btn btn-danger-outline"
            onClick={() => {
              if (window.confirm('确认中止剩余页面的书写任务吗？')) {
                void abortJob();
              }
            }}
          >
            <XCircle size={13} /> 中止剩余页面
          </button>
          <button
            className="btn btn-primary"
            disabled={machineState === 'FRAMING'}
            onClick={() => void confirmPaperReady(nextPage)}
          >
            <CheckCircle2 size={14} /> 我已换好新纸，开始第 {nextPage + 1} 页
          </button>
        </div>
      </div>
    </div>
  );
};
