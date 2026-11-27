import React, { useEffect, useState } from 'react';
import { Cpu, FlaskConical, Info, Keyboard, PenTool, Radio, X } from 'lucide-react';
import { restClient } from '../../api/restClient';
import type { HealthResponse } from '../../api/types';
import { useDocumentLayoutStore } from '../../stores/useDocumentLayoutStore';
import { useMachineStore } from '../../stores/useMachineStore';
import { useViewportStore } from '../../stores/useViewportStore';
import { useWriterStore } from '../../stores/useWriterStore';

export const AboutSettingsModal: React.FC = () => {
  const activeModal = useViewportStore((s) => s.activeModal);
  const openModal = useViewportStore((s) => s.openModal);
  const appMode = useViewportStore((s) => s.appMode);
  const setAppMode = useViewportStore((s) => s.setAppMode);
  const pushToast = useViewportStore((s) => s.pushToast);

  const currentDoc = useDocumentLayoutStore((s) => s.currentDoc);
  const clearDocument = useDocumentLayoutStore((s) => s.clearDocument);
  const resetToBlankA4 = useDocumentLayoutStore((s) => s.resetToBlankA4);

  const writers = useWriterStore((s) => s.writers);
  const activeWriterId = useWriterStore((s) => s.activeWriterId);
  const selectWriter = useWriterStore((s) => s.selectWriter);

  const machineState = useMachineStore((s) => s.machineState);
  const mock = useMachineStore((s) => s.mock);
  const setMock = useMachineStore((s) => s.setMock);

  const [health, setHealth] = useState<HealthResponse | null>(null);

  const isOpen = activeModal === 'about';
  const isConnected = machineState !== 'DISCONNECTED' && machineState !== 'ERROR';
  const isJobLocked =
    machineState === 'RUNNING' ||
    machineState === 'HOLDING' ||
    machineState === 'PAUSED' ||
    machineState === 'PEN_CHANGE' ||
    machineState === 'PAPER_CHANGE';

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    void restClient
      .health()
      .then((res) => {
        if (!cancelled) setHealth(res);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [isOpen]);

  if (!isOpen) return null;

  const handleToggleDemo = (enabled: boolean) => {
    if (isJobLocked) {
      pushToast('书写任务进行中，请先暂停或停止后再切换模式', 'warn');
      return;
    }

    if (enabled) {
      setAppMode('demo');
      clearDocument();
      if (machineState === 'DISCONNECTED') {
        setMock(true);
      }
      pushToast('已开启演示模式（空白画布 · 内置示例与 Mock 仿真已在工作区解锁）', 'info');
    } else {
      setAppMode('production');
      if (currentDoc?.is_builtin || currentDoc?.doc_id === 'doc_demo') {
        clearDocument();
      }
      resetToBlankA4();
      if (machineState === 'DISCONNECTED') {
        setMock(false);
      }
      const userWriters = writers.filter((w) => !(w.builder || '').includes('generate_demo_writers'));
      const curWriter = writers.find((w) => w.writer_id === activeWriterId);
      if (
        curWriter &&
        (curWriter.builder || '').includes('generate_demo_writers') &&
        userWriters.length > 0
      ) {
        void selectWriter(userWriters[0].writer_id);
      }
      pushToast('已退出演示模式，恢复纯净标准 A4 实际工作台', 'success');
    }
  };

  const handleToggleMock = (enabled: boolean) => {
    if (isConnected) {
      pushToast('请先在右侧硬件栏断开当前 GRBL 连接后再切换仿真模式', 'warn');
      return;
    }
    setMock(enabled);
    if (enabled) {
      pushToast('已开启 GRBL 仿真模式（免硬件调试），可在右侧硬件栏直接连接内置仿真器', 'info');
    } else {
      pushToast('已关闭 GRBL 仿真模式，切换为真实 USB 串口连接', 'success');
    }
  };

  return (
    <div className="modal-backdrop" onClick={() => openModal(null)}>
      <div className="modal-box" style={{ width: 560 }} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div className="modal-title">
            <Info size={15} />
            关于 · 墨迹工坊与高级开关
          </div>
          <button className="btn btn-sm" onClick={() => openModal(null)}>
            <X size={13} /> 关闭
          </button>
        </div>

        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* Brand Summary */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: 14,
              borderRadius: 12,
              background: 'var(--bg-subtle)',
              border: '1px solid var(--border-default)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div className="brand-mark" style={{ width: 38, height: 38, borderRadius: 11 }}>
                <PenTool size={18} strokeWidth={2.2} />
              </div>
              <div>
                <div style={{ fontSize: 14.5, fontWeight: 700, color: 'var(--text-primary)' }}>
                  墨迹工坊 · InkCraft
                </div>
                <div style={{ fontSize: 11.5, color: 'var(--text-secondary)', marginTop: 2 }}>
                  多书写者笔迹排版与 GRBL 写字机上位机
                </div>
              </div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div className="mono" style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--accent-primary)' }}>
                v{health?.version ?? '1.0.0'}
              </div>
              <div className="mono" style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>
                Contract v{health?.contract_version ?? 1}
              </div>
            </div>
          </div>

          {/* Hardware / GPU Capabilities */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '9px 12px',
              borderRadius: 10,
              background: 'var(--bg-input)',
              border: '1px solid var(--border-subtle)',
              fontSize: 12,
              color: 'var(--text-secondary)',
            }}
          >
            <Cpu size={14} style={{ color: 'var(--accent-primary)', flexShrink: 0 }} />
            <span>
              本地推理算力：
              <strong style={{ color: 'var(--text-primary)' }}>
                {health?.gpu?.available
                  ? `${health.gpu.name || 'CUDA GPU'} (${health.gpu.vram_free_mb ?? '?'} MB 可用显存)`
                  : 'CPU 离线解析与单线合成模式'}
              </strong>
            </span>
          </div>

          {/* Demo Mode Secondary Switch */}
          <div className={`about-switch-card ${appMode === 'demo' ? 'active' : ''}`}>
            <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', flex: 1 }}>
              <FlaskConical
                size={16}
                style={{
                  color: appMode === 'demo' ? 'var(--accent-primary)' : 'var(--text-muted)',
                  marginTop: 2,
                  flexShrink: 0,
                }}
              />
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>
                  演示模式（Demo Mode）
                </div>
                <div style={{ fontSize: 11.5, color: 'var(--text-secondary)', marginTop: 3, lineHeight: 1.5 }}>
                  默认关闭以保持纯净工作台（仅标准空白 A4 与个人笔迹/底稿）。开启后画布仍保持空白，但在左侧面板按需解锁内置演示纸张、参数预设、样例文档与 Mock 仿真机台。
                </div>
              </div>
            </div>
            <label className="switch" title={isJobLocked ? '任务执行中禁止切换' : '开启或关闭演示模式'}>
              <input
                type="checkbox"
                checked={appMode === 'demo'}
                disabled={isJobLocked}
                onChange={(e) => handleToggleDemo(e.target.checked)}
              />
              <span className="switch-slider" />
            </label>
          </div>

          {/* GRBL Mock Simulation Switch */}
          <div className={`about-switch-card ${mock ? 'active' : ''}`}>
            <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', flex: 1 }}>
              <Radio
                size={16}
                style={{
                  color: mock ? 'var(--state-warn)' : 'var(--text-muted)',
                  marginTop: 2,
                  flexShrink: 0,
                }}
              />
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>
                  GRBL 仿真模式（Mock GRBL）
                </div>
                <div style={{ fontSize: 11.5, color: 'var(--text-secondary)', marginTop: 3, lineHeight: 1.5 }}>
                  免硬件仿真调试开关：开启后无需连接真实写字机串口，使用内置 GRBL 1.1 运动学仿真器测试点动、对零、外框巡边与书写流程。
                  {isConnected ? '（当前已连接机台，断开后可切换）' : ''}
                </div>
              </div>
            </div>
            <label
              className="switch"
              title={isConnected ? '请先断开当前 GRBL 连接后再切换' : '开启或关闭 GRBL 免硬件仿真模式'}
            >
              <input
                type="checkbox"
                checked={mock}
                disabled={isConnected}
                onChange={(e) => handleToggleMock(e.target.checked)}
              />
              <span className="switch-slider amber" />
            </label>
          </div>

          {/* Keyboard Shortcuts Reference */}
          <div
            style={{
              borderRadius: 10,
              border: '1px solid var(--border-subtle)',
              padding: '10px 12px',
              background: 'var(--bg-input)',
            }}
          >
            <div
              className="row-gap"
              style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 8 }}
            >
              <Keyboard size={13} style={{ color: 'var(--accent-primary)' }} />
              工作台快捷操作
            </div>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: '6px 14px',
                fontSize: 11.5,
                color: 'var(--text-secondary)',
              }}
            >
              <div>
                <span className="mono" style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
                  左键拖拽 / 滚轮
                </span>
                ：移动工作区 / 缩放
              </div>
              <div>
                <span className="mono" style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
                  R / V
                </span>
                ：切换「画布拉图框选 / 拖拽」
              </div>
              <div>
                <span className="mono" style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
                  0 / 1
                </span>
                ：适应窗口 / 100% 物理比例
              </div>
              <div>
                <span className="mono" style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
                  Del / Backspace
                </span>
                ：删除当前选中区域
              </div>
              <div>
                <span className="mono" style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
                  T / B / U
                </span>
                ：空移 / 外框 / 底稿开关
              </div>
              <div>
                <span className="mono" style={{ color: 'var(--state-danger)', fontWeight: 600 }}>
                  Esc
                </span>
                ：运行中急停 / 取消当前工具
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
