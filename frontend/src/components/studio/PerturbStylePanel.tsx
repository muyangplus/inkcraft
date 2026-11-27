import React from 'react';
import { AdvancedPerturbAccordion } from './style/AdvancedPerturbAccordion';
import { MediaStyleAccordion } from './style/MediaStyleAccordion';
import { NeatnessMasterCard } from './style/NeatnessMasterCard';
import { PathOptimizeAccordion } from './style/PathOptimizeAccordion';

export const PerturbStylePanel: React.FC = () => (
  <div className="panel-scroll">
    <NeatnessMasterCard />
    <AdvancedPerturbAccordion />
    <MediaStyleAccordion />
    <PathOptimizeAccordion />
  </div>
);
