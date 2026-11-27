import React from 'react';
import { WritingRegionsPanel } from '../WritingRegionsPanel';
import { AdvancedPerturbAccordion } from '../style/AdvancedPerturbAccordion';
import { MediaStyleAccordion } from '../style/MediaStyleAccordion';
import { PathOptimizeAccordion } from '../style/PathOptimizeAccordion';

export const StepRefinePanel: React.FC = () => {
  return (
    <div className="panel-scroll">
      <WritingRegionsPanel embedded />
      <AdvancedPerturbAccordion />
      <MediaStyleAccordion />
      <PathOptimizeAccordion />
    </div>
  );
};
