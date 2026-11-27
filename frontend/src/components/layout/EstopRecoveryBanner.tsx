import React from 'react';
import { AlertTriangle, RotateCcw, ShieldAlert, Unlock } from 'lucide-react';
import { useMachineStore } from '../../stores/useMachineStore';

export const EstopRecoveryBanner: React.FC = () => {
  const machineState = useMachineStore((s) => s.machineState);
  const alarmCode = useMachineStore((s) => s.alarmCode);
  const lastAlarmMessage = useMachineStore((s) => s.lastAlarmMessage);
  const unlock = useMachineStore((s) => s.unlock);
  const zeroXY = useMachineStore((s) => s.zeroXY);
  const busyAction = useMachineStore((s) => s.busyAction);

  if (machineState === 'ESTOPPED') {
    return (
      <div className="alert-banner" role="alert">
        <div className="row-gap">
          <ShieldAlert size={15} />
          <span>
            <strong>已触发紧急停止（0x18 软复位 + 强制抬笔）</strong> — 步进位置可能已丢失，禁止直接续写。
            请清理笔头与纸张障碍后执行 <code className="mono">$X</code> 解锁并重新归零。
          </span>
        </div>
        <div className="row-gap">
          <button
            className="btn btn-sm btn-warn"
            disabled={busyAction === 'unlock'}
            onClick={() => void unlock()}
          >
            <Unlock size={12} /> $X 解除锁定
          </button>
          <button
            className="btn btn-sm"
            disabled={busyAction === 'unlock'}
            onClick={async () => {
              await unlock();
              await zeroXY();
            }}
          >
            <RotateCcw size={12} /> 解锁并设当前点为原点
          </button>
        </div>
      </div>
    );
  }

  if (machineState === 'ALARM' || machineState === 'ERROR') {
    return (
      <div className="alert-banner" role="alert">
        <div className="row-gap">
          <AlertTriangle size={15} />
          <span>
            <strong>
              {machineState === 'ALARM'
                ? `GRBL 机台告警 (${alarmCode ?? 'ALARM'})`
                : '串口通信错误'}
            </strong>
            {lastAlarmMessage ? ` — ${lastAlarmMessage}` : ' — 请检查限位开关或串口连接状态。'}
          </span>
        </div>
        {machineState === 'ALARM' && (
          <button
            className="btn btn-sm btn-warn"
            disabled={busyAction === 'unlock'}
            onClick={() => void unlock()}
          >
            <Unlock size={12} /> $X 解除告警
          </button>
        )}
      </div>
    );
  }

  return null;
};
