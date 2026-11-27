import React, { useEffect, useState } from 'react';
import { ArrowDown, ArrowUp, Settings, X } from 'lucide-react';
import type { MachineProfile } from '../../api/types';
import { useMachineStore } from '../../stores/useMachineStore';
import { useViewportStore } from '../../stores/useViewportStore';

export const MachineProfileModal: React.FC = () => {
  const activeModal = useViewportStore((s) => s.activeModal);
  const openModal = useViewportStore((s) => s.openModal);

  const profiles = useMachineStore((s) => s.profiles);
  const activeProfileId = useMachineStore((s) => s.activeProfileId);
  const machineState = useMachineStore((s) => s.machineState);
  const saveProfile = useMachineStore((s) => s.saveProfile);
  const testPenOverride = useMachineStore((s) => s.testPenOverride);

  const isOpen = activeModal === 'machine-profile';
  const activeProfile =
    profiles.find((p) => p.profile_id === activeProfileId) ??
    useMachineStore.getState().getActiveProfile();

  const [draft, setDraft] = useState<MachineProfile>(() => structuredClone(activeProfile));
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setDraft(structuredClone(activeProfile));
    }
  }, [isOpen, activeProfile]);

  if (!isOpen) return null;

  const canLivePenTest =
    machineState === 'IDLE' ||
    machineState === 'PEN_CHANGE' ||
    machineState === 'PAPER_CHANGE' ||
    machineState === 'PAUSED';

  const handleSave = async () => {
    setSaving(true);
    try {
      await saveProfile(draft);
      openModal(null);
    } finally {
      setSaving(false);
    }
  };

  const applyTemplate = (kind: 'corexy_servo' | 'stepper_z' | 'fast_check') => {
    if (kind === 'corexy_servo') {
      setDraft((d) => ({
        ...d,
        pen: { ...d.pen, mode: 'servo', servo_up: 'M5', servo_down: 'M3 S90', dwell_ms: 120 },
        feed_draw: 2400,
        feed_travel: 5000,
        jog_feed: 3000,
      }));
    } else if (kind === 'stepper_z') {
      setDraft((d) => ({
        ...d,
        pen: { ...d.pen, mode: 'z', z_up_mm: 4.0, z_down_mm: 0.0, z_feed: 1200, dwell_ms: 40 },
        feed_draw: 2200,
        feed_travel: 4500,
        jog_feed: 2800,
      }));
    } else {
      setDraft((d) => ({
        ...d,
        pen: { ...d.pen, dwell_ms: 70 },
        feed_draw: 3600,
        feed_travel: 6500,
        jog_feed: 3600,
      }));
    }
  };

  const handleLivePenTest = (state: 'up' | 'down') => {
    if (draft.pen.mode === 'z') {
      void testPenOverride(state, {
        overrideZMm: state === 'up' ? draft.pen.z_up_mm : draft.pen.z_down_mm,
        overrideZFeed: draft.pen.z_feed,
      });
    } else {
      void testPenOverride(state, {
        overrideCmd: state === 'up' ? draft.pen.servo_up : draft.pen.servo_down,
      });
    }
  };

  return (
    <div className="modal-backdrop" onClick={() => openModal(null)}>
      <div className="modal-box" style={{ width: 570 }} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div className="modal-title">
            <Settings size={15} /> GRBL 机台档案与调试配置 (MachineProfile)
          </div>
          <button type="button" className="btn btn-sm" onClick={() => openModal(null)}>
            <X size={13} /> 取消
          </button>
        </div>

        <div className="modal-body">
          {/* Quick Hardware Presets */}
          <div className="row-between" style={{ gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 11.5, color: 'var(--text-secondary)', fontWeight: 600 }}>
              快捷硬件模板:
            </span>
            <div className="row-gap" style={{ gap: 5, flexWrap: 'wrap' }}>
              <button
                type="button"
                className="btn btn-xs"
                onClick={() => applyTemplate('corexy_servo')}
              >
                CoreXY 舵机 A4
              </button>
              <button
                type="button"
                className="btn btn-xs"
                onClick={() => applyTemplate('stepper_z')}
              >
                步进 Z 轴写字机
              </button>
              <button
                type="button"
                className="btn btn-xs"
                onClick={() => applyTemplate('fast_check')}
              >
                高速流畅书写
              </button>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 120px', gap: 10 }}>
            <div>
              <div className="ctrl-label" style={{ marginBottom: 4 }}>
                <span>档案名称</span>
                <span className="mono" style={{ fontSize: 10.5 }}>
                  {draft.profile_id}
                </span>
              </div>
              <input
                type="text"
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              />
            </div>

            <div>
              <div className="ctrl-label" style={{ marginBottom: 4 }}>
                默认波特率
              </div>
              <select
                className="mono"
                value={draft.baud}
                onChange={(e) => setDraft({ ...draft, baud: Number(e.target.value) })}
              >
                <option value={115200}>115200</option>
                <option value={250000}>250000</option>
                <option value={57600}>57600</option>
              </select>
            </div>
          </div>

          <div className="row-between">
            <span style={{ fontWeight: 600 }}>抬落笔执行机构 (pen.mode)</span>
            <div className="seg-group">
              <button
                type="button"
                className={`seg-btn ${draft.pen.mode === 'servo' ? 'active' : ''}`}
                onClick={() => setDraft({ ...draft, pen: { ...draft.pen, mode: 'servo' } })}
              >
                舵机 M3 / M5
              </button>
              <button
                type="button"
                className={`seg-btn ${draft.pen.mode === 'z' ? 'active' : ''}`}
                onClick={() => setDraft({ ...draft, pen: { ...draft.pen, mode: 'z' } })}
              >
                步进 Z 轴
              </button>
            </div>
          </div>

          {draft.pen.mode === 'servo' ? (
            <div className="grid-3">
              <div>
                <div className="ctrl-label" style={{ marginBottom: 3 }}>
                  抬笔指令
                </div>
                <input
                  type="text"
                  className="mono"
                  value={draft.pen.servo_up}
                  onChange={(e) =>
                    setDraft({ ...draft, pen: { ...draft.pen, servo_up: e.target.value } })
                  }
                />
              </div>
              <div>
                <div className="ctrl-label" style={{ marginBottom: 3 }}>
                  落笔指令
                </div>
                <input
                  type="text"
                  className="mono"
                  value={draft.pen.servo_down}
                  onChange={(e) =>
                    setDraft({ ...draft, pen: { ...draft.pen, servo_down: e.target.value } })
                  }
                />
              </div>
              <div>
                <div className="ctrl-label" style={{ marginBottom: 3 }}>
                  落笔延时 (ms)
                </div>
                <input
                  type="number"
                  className="mono"
                  min={0}
                  max={2000}
                  value={draft.pen.dwell_ms}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      pen: { ...draft.pen, dwell_ms: Number(e.target.value) || 0 },
                    })
                  }
                />
              </div>
            </div>
          ) : (
            <div className="grid-3">
              <div>
                <div className="ctrl-label" style={{ marginBottom: 3 }}>
                  抬笔 Z (mm)
                </div>
                <input
                  type="number"
                  className="mono"
                  step={0.5}
                  value={draft.pen.z_up_mm}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      pen: { ...draft.pen, z_up_mm: Number(e.target.value) },
                    })
                  }
                />
              </div>
              <div>
                <div className="ctrl-label" style={{ marginBottom: 3 }}>
                  落笔 Z (mm)
                </div>
                <input
                  type="number"
                  className="mono"
                  step={0.5}
                  value={draft.pen.z_down_mm}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      pen: { ...draft.pen, z_down_mm: Number(e.target.value) },
                    })
                  }
                />
              </div>
              <div>
                <div className="ctrl-label" style={{ marginBottom: 3 }}>
                  Z 进给 (mm/min)
                </div>
                <input
                  type="number"
                  className="mono"
                  value={draft.pen.z_feed}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      pen: { ...draft.pen, z_feed: Number(e.target.value) || 600 },
                    })
                  }
                />
              </div>
            </div>
          )}

          {/* Live Pen Calibration Bar */}
          <div className="row-between" style={{ gap: 8 }}>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              {canLivePenTest
                ? '使用当前草稿值立即实机测试舵机角度 / Z轴高度：'
                : '连接 GRBL 并处于 IDLE 态时可直接在此实测抬落笔'}
            </span>
            <div className="row-gap" style={{ gap: 6, flexShrink: 0 }}>
              <button
                type="button"
                className="btn btn-xs"
                disabled={!canLivePenTest}
                onClick={() => handleLivePenTest('up')}
              >
                <ArrowUp size={11} /> 实时测试抬笔
              </button>
              <button
                type="button"
                className="btn btn-xs btn-soft"
                disabled={!canLivePenTest}
                onClick={() => handleLivePenTest('down')}
              >
                <ArrowDown size={11} /> 实时测试落笔
              </button>
            </div>
          </div>

          <div className="grid-2">
            <div>
              <div className="ctrl-label" style={{ marginBottom: 3 }}>
                物理工作区 X 行程 (mm)
              </div>
              <input
                type="number"
                className="mono"
                value={draft.workspace_mm.x}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    workspace_mm: { ...draft.workspace_mm, x: Number(e.target.value) || 220 },
                  })
                }
              />
            </div>
            <div>
              <div className="ctrl-label" style={{ marginBottom: 3 }}>
                物理工作区 Y 行程 (mm)
              </div>
              <input
                type="number"
                className="mono"
                value={draft.workspace_mm.y}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    workspace_mm: { ...draft.workspace_mm, y: Number(e.target.value) || 310 },
                  })
                }
              />
            </div>
          </div>

          <div className="grid-2">
            <div>
              <div className="ctrl-label" style={{ marginBottom: 3 }}>
                换笔安全泊位 X / Y (mm)
              </div>
              <div className="grid-2" style={{ gap: 6 }}>
                <input
                  type="number"
                  className="mono"
                  step={1}
                  value={draft.pen_change_pos_mm.x}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      pen_change_pos_mm: {
                        ...draft.pen_change_pos_mm,
                        x: Number(e.target.value) || 0,
                      },
                    })
                  }
                />
                <input
                  type="number"
                  className="mono"
                  step={1}
                  value={draft.pen_change_pos_mm.y}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      pen_change_pos_mm: {
                        ...draft.pen_change_pos_mm,
                        y: Number(e.target.value) || 0,
                      },
                    })
                  }
                />
              </div>
            </div>
            <div>
              <div className="ctrl-label" style={{ marginBottom: 3 }}>
                换纸 / 完工停靠位 X / Y (mm)
              </div>
              <div className="grid-2" style={{ gap: 6 }}>
                <input
                  type="number"
                  className="mono"
                  step={1}
                  value={draft.paper_change_pos_mm.x}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      paper_change_pos_mm: {
                        ...draft.paper_change_pos_mm,
                        x: Number(e.target.value) || 0,
                      },
                    })
                  }
                />
                <input
                  type="number"
                  className="mono"
                  step={1}
                  value={draft.paper_change_pos_mm.y}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      paper_change_pos_mm: {
                        ...draft.paper_change_pos_mm,
                        y: Number(e.target.value) || 0,
                      },
                    })
                  }
                />
              </div>
            </div>
          </div>

          <div className="grid-3">
            <div>
              <div className="ctrl-label" style={{ marginBottom: 3 }}>
                书写速度 (mm/min)
              </div>
              <input
                type="number"
                className="mono"
                value={draft.feed_draw}
                onChange={(e) =>
                  setDraft({ ...draft, feed_draw: Number(e.target.value) || 2400 })
                }
              />
            </div>
            <div>
              <div className="ctrl-label" style={{ marginBottom: 3 }}>
                空移速度 (mm/min)
              </div>
              <input
                type="number"
                className="mono"
                value={draft.feed_travel}
                onChange={(e) =>
                  setDraft({ ...draft, feed_travel: Number(e.target.value) || 5000 })
                }
              />
            </div>
            <div>
              <div className="ctrl-label" style={{ marginBottom: 3 }}>
                点动速度 (mm/min)
              </div>
              <input
                type="number"
                className="mono"
                value={draft.jog_feed}
                onChange={(e) =>
                  setDraft({ ...draft, jog_feed: Number(e.target.value) || 3000 })
                }
              />
            </div>
          </div>

          <div className="grid-3">
            <div>
              <div className="ctrl-label" style={{ marginBottom: 3 }}>
                坐标系原点
              </div>
              <select
                value={draft.origin}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    origin: e.target.value as 'top_left' | 'bottom_left',
                  })
                }
              >
                <option value="top_left">左上角 (top_left)</option>
                <option value="bottom_left">左下角 (bottom_left)</option>
              </select>
            </div>
            <label className="row-gap" style={{ marginTop: 18, cursor: 'pointer', fontSize: 12 }}>
              <input
                type="checkbox"
                checked={draft.invert_x}
                onChange={(e) => setDraft({ ...draft, invert_x: e.target.checked })}
              />
              反转 X 轴
            </label>
            <label className="row-gap" style={{ marginTop: 18, cursor: 'pointer', fontSize: 12 }}>
              <input
                type="checkbox"
                checked={draft.invert_y}
                onChange={(e) => setDraft({ ...draft, invert_y: e.target.checked })}
              />
              反转 Y 轴
            </label>
          </div>
        </div>

        <div className="modal-foot">
          <button type="button" className="btn" onClick={() => openModal(null)}>
            取消
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={saving}
            onClick={() => void handleSave()}
          >
            {saving ? '保存中…' : '保存机台档案'}
          </button>
        </div>
      </div>
    </div>
  );
};
