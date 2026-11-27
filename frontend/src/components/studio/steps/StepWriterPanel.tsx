import React from 'react';
import { ArrowRight } from 'lucide-react';
import { useViewportStore } from '../../../stores/useViewportStore';
import { NeatnessMasterCard } from '../style/NeatnessMasterCard';
import { WriterListPanel } from '../WriterListPanel';

export const StepWriterPanel: React.FC = () => {
  const setLeftTab = useViewportStore((s) => s.setLeftTab);

  return (
    <div className="panel-scroll">
      <WriterListPanel embedded />
      <NeatnessMasterCard />

      <div className="step-next-bar">
        <button
          type="button"
          className="btn btn-sm btn-primary"
          onClick={() => setLeftTab('refine')}
        >
          <span>下一步：精调与区域</span>
          <ArrowRight size={13} />
        </button>
      </div>
    </div>
  );
};
