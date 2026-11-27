import React from 'react';
import { Plug, RefreshCw, Settings, Unplug } from 'lucide-react';
import { useMachineStore } from '../../stores/useMachineStore';
import { useViewportStore } from '../../stores/useViewportStore';

export const ConnectionCard: React.FC = () => {
  const machineState = useMachineStore((s) => s.machineState);
  const ports = useMachineStore((s) => s.ports);
  const selectedPort = useMachineStore((s) => s.selectedPort);
  const baud = useMachineStore((s) => s.baud);
  const profiles = useMachineStore((s) => s.profiles);
  const activeProfileId = useMachineStore((s) => s.activeProfileId);
  const mock = useMachineStore((s) => s.mock);
  const busyAction = useMachineStore((s) => s.busyAction);

  const fetchPorts = useMachineStore((s) => s.fetchPorts);
  const setSelectedPort = useMachineStore((s) => s.setSelectedPort);
  const setBaud = useMachineStore((s) => s.setBaud);
  const setActiveProfileId = useMachineStore((s) => s.setActiveProfileId);
  const connect = useMachineStore((s) => s.connect);
  const disconnect = useMachineStore((s) => s.disconnect);

  const openModal = useViewportStore((s) => s.openModal);

  const isConnected = machineState !== 'DISCONNECTED' && machineState !== 'ERROR';
  const canDisconnect =
    isConnected &&
    machineState !== 'RUNNING' &&
    machineState !== 'JOGGING' &&
    machineState !== 'FRAMING';

  const activeProfile =
    profiles.find((p) => p.profile_id === activeProfileId) ??
    useMachineStore.getState().getActiveProfile();

  return (
    <div className="section-card">
      <div className="section-head">
        <span>GRBL 连接与档案</span>
        <div className="row-gap" style={{ gap: 5 }}>
          <button
            className="btn btn-xs"
            disabled={isConnected}
            onClick={() => void fetchPorts()}
            title="刷新可用 USB 串口列表"
          >
            <RefreshCw size={11} />
          </button>
          <button
            className="btn btn-xs"
            onClick={() => openModal('machine-profile')}
            title="配置舵机/步进Z轴抬笔、行程与速度"
          >
            <Settings size={11} /> 配置
          </button>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 76px', gap: 6 }}>
        <select
          disabled={isConnected || mock}
          value={mock ? 'MOCK' : selectedPort}
          onChange={(e) => setSelectedPort(e.target.value)}
        >
          {mock && <option value="MOCK">MOCK-GRBL-1.1 (内置仿真)</option>}
          {ports.map((p) => (
            <option key={p.device} value={p.device}>
              {p.device} {p.description ? `(${p.description})` : ''}
            </option>
          ))}
        </select>

        <select
          className="mono"
          disabled={isConnected}
          value={baud}
          onChange={(e) => setBaud(Number(e.target.value))}
        >
          <option value={115200}>115200</option>
          <option value={250000}>250000</option>
          <option value={57600}>57600</option>
        </select>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto', gap: 6 }}>
        <select
          disabled={isConnected}
          value={activeProfileId}
          onChange={(e) => setActiveProfileId(e.target.value)}
        >
          {profiles.map((p) => (
            <option key={p.profile_id} value={p.profile_id}>
              {p.name}
            </option>
          ))}
        </select>

        {!isConnected ? (
          <button
            className="btn btn-primary"
            disabled={busyAction === 'connect'}
            onClick={() => void connect()}
          >
            <Plug size={12} /> {busyAction === 'connect' ? '连接中…' : '连接'}
          </button>
        ) : (
          <button
            className="btn btn-success"
            disabled={!canDisconnect || busyAction === 'disconnect'}
            title={!canDisconnect ? '运动进行中，请先停止再断开连接' : '断开串口连接'}
            onClick={() => void disconnect()}
          >
            <Unplug size={12} /> 断开
          </button>
        )}
      </div>

      <div className="mono" style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>
        {activeProfile.pen.mode === 'servo'
          ? `舵机 ${activeProfile.pen.servo_up}/${activeProfile.pen.servo_down} · 延时 ${activeProfile.pen.dwell_ms}ms`
          : `步进 Z ${activeProfile.pen.z_up_mm}/${activeProfile.pen.z_down_mm}mm`}{' '}
        · 幅面 {activeProfile.workspace_mm.x}×{activeProfile.workspace_mm.y}mm
      </div>
    </div>
  );
};
