import React, { useMemo, useState } from 'react';
import { ArrowRight, ChevronDown, ChevronRight, Sparkles } from 'lucide-react';
import { useDocumentLayoutStore } from '../../../stores/useDocumentLayoutStore';
import { useViewportStore } from '../../../stores/useViewportStore';
import { useWriterStore } from '../../../stores/useWriterStore';
import { PaperGeometryCard } from '../layout/PaperGeometryCard';
import { PresetGalleryCard } from '../layout/PresetGalleryCard';
import { TypographyCard } from '../layout/TypographyCard';
import { BackgroundLibraryCard } from '../pages/BackgroundLibraryCard';
import { PageStrategySection } from '../pages/PageStrategySection';

export const StepPaperPanel: React.FC = () => {
  const [presetsOpen, setPresetsOpen] = useState(false);

  const backgrounds = useDocumentLayoutStore((s) => s.backgrounds);
  const writers = useWriterStore((s) => s.writers);
  const appMode = useViewportStore((s) => s.appMode);
  const setLeftTab = useViewportStore((s) => s.setLeftTab);

  const visibleBackgrounds = useMemo(
    () => (appMode === 'demo' ? backgrounds : backgrounds.filter((b) => b.kind === 'uploaded')),
    [backgrounds, appMode],
  );
  const visibleWriters = useMemo(
    () =>
      appMode === 'demo'
        ? writers
        : writers.filter((w) => !(w.builder || '').includes('generate_demo_writers')),
    [writers, appMode],
  );

  return (
    <div className="panel-scroll">
      <PaperGeometryCard />
      <TypographyCard />
      <PageStrategySection visibleBackgrounds={visibleBackgrounds} visibleWriters={visibleWriters} />
      <BackgroundLibraryCard visibleBackgrounds={visibleBackgrounds} />

      <div className="section-card">
        <button
          type="button"
          className="accordion-header"
          onClick={() => setPresetsOpen((v) => !v)}
          aria-expanded={presetsOpen}
        >
          <span className="section-head-title">
            <Sparkles size={13} style={{ color: 'var(--accent-primary)' }} />
            预设与个人模板（可选）
          </span>
          {presetsOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>
        {presetsOpen && (
          <div className="accordion-body">
            <PresetGalleryCard />
          </div>
        )}
      </div>

      <div className="step-next-bar">
        <button
          type="button"
          className="btn btn-sm btn-primary"
          onClick={() => setLeftTab('writer')}
        >
          <span>下一步：选择笔迹</span>
          <ArrowRight size={13} />
        </button>
      </div>
    </div>
  );
};
