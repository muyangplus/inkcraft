import React from 'react';
import { ArrowDown, ArrowUp, PenLine, RotateCcw, XCircle } from 'lucide-react';
import { useMachineStore } from '../../stores/useMachineStore';
import { useViewportStore } from '../../stores/useViewportStore';

export const PenChangePopover: React.FC = () => {
  const penChangeOpen = useViewportStore((s) => s.penChangeOpen);
  const machineState = useMachineStore((s) => s.machineState);
  const pen = useMachineStore((s) => s.pen);
  const setPen = useMachineStore((s) => s.setPen);
  const resumeJob = useMachineStore((s) => s.resumeJob);
  const abortJob = useMachineStore((s) => s.abortJob);

  if (!penChangeOpen && machineState !== 'PEN_CHANGE') return null;

  return (
    <div className="pen-popover" role="dialog" aria-label="换笔安全泊位">
      <div className="modal-head" style={{ padding: '10px 13px' }}>
        <div className="modal-title" style={{ color: 'var(--state-warn)', fontSize: 13 }}>
          <PenLine size={14} /> 换笔安全泊位 (PEN_CHANGE)
        </div>
        <span className="mono" style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>
          {pen === 'down' ? '↓ 落笔' : '↑ 抬笔'}
        </span>
      </div>

      <div className="modal-body" style={{ padding: '12px 13px', gap: 10 }}>
        <div style={{ fontSize: 12, lineHeight: 1.55, color: 'var(--text-secondary)' }}>
          写字机已记录精确断点坐标并抬笔移至换笔安全泊位。请更换新笔芯，可使用下方按钮微触验证笔尖贴纸高度：
        </div>
        <div className="grid-2">
          <button className="btn btn-sm" onClick={() => void setPen('up')}>
            <ArrowUp size={12} /> 抬笔测试
          </button>
          <button className="btn btn-sm" onClick={() => void setPen('down')}>
            <ArrowDown size={12} /> 落笔微触测试
          </button>
        </div>
      </div>

      <div className="modal-foot" style={{ padding: '9px 13px', justifyContent: 'space-between' }}>
        <button className="btn btn-xs btn-danger-outline" onClick={() => void abortJob()}>
          <XCircle size={12} /> 中止
        </button>
        <button className="btn btn-sm btn-primary" onClick={() => void resumeJob()}>
          <RotateCcw size={12} /> 换笔完成，回位续写 (~)
        </button>
      </div>
    </div>
  );
};
