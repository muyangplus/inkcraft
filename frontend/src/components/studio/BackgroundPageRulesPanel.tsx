import React from 'react';
import { useDocumentLayoutStore } from '../../stores/useDocumentLayoutStore';
import { useViewportStore } from '../../stores/useViewportStore';
import { useWriterStore } from '../../stores/useWriterStore';
import { BackgroundLibraryCard } from './pages/BackgroundLibraryCard';
import { PageStrategySection } from './pages/PageStrategySection';

export const BackgroundPageRulesPanel: React.FC = () => {
  const backgrounds = useDocumentLayoutStore((s) => s.backgrounds);
  const writers = useWriterStore((s) => s.writers);
  const appMode = useViewportStore((s) => s.appMode);

  const visibleBackgrounds =
    appMode === 'demo' ? backgrounds : backgrounds.filter((b) => b.kind === 'uploaded');
  const visibleWriters =
    appMode === 'demo'
      ? writers
      : writers.filter((w) => !(w.builder || '').includes('generate_demo_writers'));

  return (
    <div className="panel-scroll">
      <PageStrategySection
        visibleBackgrounds={visibleBackgrounds}
        visibleWriters={visibleWriters}
      />
      <BackgroundLibraryCard visibleBackgrounds={visibleBackgrounds} />
    </div>
  );
};
