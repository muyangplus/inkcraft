import React from 'react';
import { useDocumentLayoutStore } from '../../stores/useDocumentLayoutStore';
import { DocumentSourceCard } from './layout/DocumentSourceCard';
import { OverlayRegistrationSection } from './layout/OverlayRegistrationSection';
import { PaperGeometryCard } from './layout/PaperGeometryCard';
import { PresetGalleryCard } from './layout/PresetGalleryCard';
import { TypographyCard } from './layout/TypographyCard';

export const PresetsAndLayoutPanel: React.FC = () => {
  const mode = useDocumentLayoutStore((s) => s.config.mode);

  return (
    <div className="panel-scroll">
      <PresetGalleryCard />
      <DocumentSourceCard />
      {mode === 'reflow' ? (
        <>
          <PaperGeometryCard />
          <TypographyCard />
        </>
      ) : (
        <OverlayRegistrationSection />
      )}
    </div>
  );
};
