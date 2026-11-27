import React, { useMemo } from 'react';
import { AlertTriangle, ArrowRight } from 'lucide-react';
import type { MissingGlyphBox } from '../../../api/types';
import { useDocumentLayoutStore } from '../../../stores/useDocumentLayoutStore';
import { useViewportStore } from '../../../stores/useViewportStore';
import { DocumentSourceCard } from '../layout/DocumentSourceCard';
import { OverlayRegistrationSection } from '../layout/OverlayRegistrationSection';

export const StepDocumentPanel: React.FC = () => {
  const mode = useDocumentLayoutStore((s) => s.config.mode);
  const layout = useDocumentLayoutStore((s) => s.layout);
  const focusMissingGlyph = useDocumentLayoutStore((s) => s.focusMissingGlyph);
  const setLeftTab = useViewportStore((s) => s.setLeftTab);

  const missingSummary = useMemo(() => {
    const all: MissingGlyphBox[] = [];
    for (const p of layout?.pages ?? []) {
      if (p.missing_glyphs?.length) {
        all.push(...p.missing_glyphs);
      }
    }
    const pages = new Set(all.map((m) => m.page_index));
    return { all, count: all.length, pageCount: pages.size };
  }, [layout]);

  return (
    <div className="panel-scroll">
      <DocumentSourceCard />

      {mode === 'overlay' && <OverlayRegistrationSection />}

      {missingSummary.count > 0 && (
        <div className="section-card" style={{ borderColor: 'rgba(220, 38, 38, 0.35)', background: 'rgba(220, 38, 38, 0.04)' }}>
          <div className="section-head">
            <span className="section-head-title" style={{ color: '#DC2626' }}>
              <AlertTriangle size={13} />
              检测到 {missingSummary.count} 处缺字（跨 {missingSummary.pageCount} 页）
            </span>
            <button
              type="button"
              className="btn btn-xs"
              style={{ borderColor: 'rgba(220, 38, 38, 0.45)', color: '#DC2626' }}
              onClick={() => void focusMissingGlyph(missingSummary.all[0])}
            >
              跳转首个缺字
            </button>
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-secondary)', lineHeight: 1.45 }}>
            画布已自动用红色虚线框标出当前字库未收录的字符（导出 G-code 时不会误落笔）。可使用画布左上角导航条快速逐个检查或更换字库。
          </div>
        </div>
      )}

      <div className="step-next-bar">
        <button
          type="button"
          className="btn btn-sm btn-primary"
          onClick={() => setLeftTab('paper')}
        >
          <span>下一步：纸张与排版</span>
          <ArrowRight size={13} />
        </button>
      </div>
    </div>
  );
};
