import React, { useEffect, useState } from 'react';
import { ArrowDown, ArrowUp, Plus, Settings, Trash2, X } from 'lucide-react';
import type { MachineOrigin, MachineProfile } from '../../api/types';
import { useMachineStore } from '../../stores/useMachineStore';
import { useViewportStore } from '../../stores/useViewportStore';
import { GrblFirmwarePanel } from './GrblFirmwarePanel';

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

  const applyTemplate = (kind: 'corexy_servo' | 'stepper_z' | 'fast_check' | 'kx_compatible') => {
    if (kind === 'kx_compatible') {
      setDraft((d) => ({
        ...d,
        pen: {
          ...d.pen,
          mode: 'z',
          z_up_mm: 0,
          z_down_mm: 2,
          z_feed: 3000,
          dwell_ms: 0,
          down_delay_ms: 200,
          up_delay_ms: 200,
        },
        origin: 'top_left',
        x_axis: 'right',
        y_axis: 'up',
        swap_xy: false,
        feed_draw: 1500,
        feed_travel: 3000,
        jog_feed: 2500,
        auto_zero_on_start: true,
      }));
    } else if (kind === 'corexy_servo') {
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
    } else if (draft.pen.mode === 'laser') {
      void testPenOverride(state, {
        overrideCmd: state === 'up' ? 'M5' : `M3 S${draft.pen.laser_power}`,
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
              <button
                type="button"
                className="btn btn-xs btn-primary"
                title="奎享式控制方案出厂值：步进Z 落笔Z2/抬笔Z0、落笔后与抬笔前各停 0.2s、左上原点向下为 -Y、开始时自动置零"
                onClick={() => applyTemplate('kx_compatible')}
              >
                奎享兼容方案
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
              <button
                type="button"
                className={`seg-btn ${draft.pen.mode === 'laser' ? 'active' : ''}`}
                onClick={() => setDraft({ ...draft, pen: { ...draft.pen, mode: 'laser' } })}
              >
                激光 / PWM
              </button>
            </div>
          </div>

          {draft.pen.mode === 'laser' ? (
            <div className="grid-3">
              <div>
                <div className="ctrl-label" style={{ marginBottom: 3 }} title="落笔 = M3 S功率，抬笔 = M5">
                  激光功率 S
                </div>
                <input
                  type="number"
                  className="mono"
                  min={0}
                  value={draft.pen.laser_power}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      pen: { ...draft.pen, laser_power: Math.max(0, Number(e.target.value) || 0) },
                    })
                  }
                />
              </div>
              <div className="mono" style={{ gridColumn: 'span 2', fontSize: 10.5, color: 'var(--text-muted)', alignSelf: 'end' }}>
                落笔 M3 S{draft.pen.laser_power} · 抬笔 M5 · 建议固件 $32=1（空移自动熄灭）
              </div>
            </div>
          ) : draft.pen.mode === 'servo' ? (
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

          <div className="grid-3">
            {(
              [
                ['dwell_ms', '机构稳定 (ms)', '每次抬/落笔后等待执行机构到位'],
                ['down_delay_ms', '落笔后暂停 (ms)', '落笔后、开始书写前停顿，便于出墨'],
                ['up_delay_ms', '抬笔前暂停 (ms)', '一笔写完、抬笔之前停顿'],
              ] as const
            ).map(([key, label, tip]) => (
              <div key={key}>
                <div className="ctrl-label" style={{ marginBottom: 3 }} title={tip}>
                  {label}
                </div>
                <input
                  type="number"
                  className="mono"
                  min={0}
                  max={5000}
                  step={10}
                  value={draft.pen[key]}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      pen: { ...draft.pen, [key]: Math.max(0, Number(e.target.value) || 0) },
                    })
                  }
                />
              </div>
            ))}
          </div>

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
                坐标原点（纸面角）
              </div>
              <select
                value={draft.origin}
                onChange={(e) => setDraft({ ...draft, origin: e.target.value as MachineOrigin })}
              >
                <option value="top_left">左上角</option>
                <option value="top_right">右上角</option>
                <option value="bottom_left">左下角</option>
                <option value="bottom_right">右下角</option>
              </select>
            </div>
            <div>
              <div className="ctrl-label" style={{ marginBottom: 3 }} title="机器 +X 指向纸面哪一侧">
                机器 +X 方向
              </div>
              <select
                value={draft.x_axis}
                onChange={(e) =>
                  setDraft({ ...draft, x_axis: e.target.value as MachineProfile['x_axis'] })
                }
              >
                <option value="auto">自动（坐标恒为正）</option>
                <option value="right">指向纸面右侧</option>
                <option value="left">指向纸面左侧</option>
              </select>
            </div>
            <div>
              <div className="ctrl-label" style={{ marginBottom: 3 }} title="奎享「左上」原点机器为「指向纸面上方」：向下书写 Y 为负">
                机器 +Y 方向
              </div>
              <select
                value={draft.y_axis}
                onChange={(e) =>
                  setDraft({ ...draft, y_axis: e.target.value as MachineProfile['y_axis'] })
                }
              >
                <option value="auto">自动（坐标恒为正）</option>
                <option value="down">指向纸面下方</option>
                <option value="up">指向纸面上方（奎享）</option>
              </select>
            </div>
          </div>

          <div className="grid-3">
            <label className="row-gap" style={{ cursor: 'pointer', fontSize: 12 }}>
              <input
                type="checkbox"
                checked={draft.swap_xy}
                onChange={(e) => setDraft({ ...draft, swap_xy: e.target.checked })}
              />
              对调 XY 轴
            </label>
            <label className="row-gap" style={{ cursor: 'pointer', fontSize: 12 }}>
              <input
                type="checkbox"
                checked={draft.invert_x}
                onChange={(e) => setDraft({ ...draft, invert_x: e.target.checked })}
              />
              左右镜像
            </label>
            <label className="row-gap" style={{ cursor: 'pointer', fontSize: 12 }}>
              <input
                type="checkbox"
                checked={draft.invert_y}
                onChange={(e) => setDraft({ ...draft, invert_y: e.target.checked })}
              />
              上下镜像
            </label>
          </div>

          <div className="grid-3">
            <div>
              <div className="ctrl-label" style={{ marginBottom: 3 }}>
                整体偏移 X (mm)
              </div>
              <input
                type="number"
                className="mono"
                step={0.1}
                value={draft.offset_mm.x}
                onChange={(e) =>
                  setDraft({ ...draft, offset_mm: { ...draft.offset_mm, x: Number(e.target.value) || 0 } })
                }
              />
            </div>
            <div>
              <div className="ctrl-label" style={{ marginBottom: 3 }}>
                整体偏移 Y (mm)
              </div>
              <input
                type="number"
                className="mono"
                step={0.1}
                value={draft.offset_mm.y}
                onChange={(e) =>
                  setDraft({ ...draft, offset_mm: { ...draft.offset_mm, y: Number(e.target.value) || 0 } })
                }
              />
            </div>
            <div>
              <div className="ctrl-label" style={{ marginBottom: 3 }}>
                串口
              </div>
              <input
                className="mono"
                value={draft.port}
                placeholder="auto"
                title="填 auto 时每次连接自动识别（推荐，COM 号会随 USB 口变化）"
                onChange={(e) => setDraft({ ...draft, port: e.target.value.trim() || 'auto' })}
              />
            </div>
          </div>

          <div className="grid-3">
            <div>
              <div className="ctrl-label" style={{ marginBottom: 3 }} title="绕纸面中心旋转整幅内容，用于纠正纸张放歪">
                整体旋转 (°)
              </div>
              <input
                type="number"
                className="mono"
                step={0.1}
                min={-180}
                max={180}
                value={draft.rotation_deg}
                onChange={(e) => setDraft({ ...draft, rotation_deg: Number(e.target.value) || 0 })}
              />
            </div>
            <div>
              <div className="ctrl-label" style={{ marginBottom: 3 }} title="点动面板 Z+/Z- 每次移动的距离">
                Z 点动步长 (mm)
              </div>
              <input
                type="number"
                className="mono"
                step={0.1}
                min={0.1}
                value={draft.z_jog_step_mm}
                onChange={(e) =>
                  setDraft({ ...draft, z_jog_step_mm: Math.max(0.1, Number(e.target.value) || 1) })
                }
              />
            </div>
            <div>
              <div className="ctrl-label" style={{ marginBottom: 3 }} title="单步：每发一行等待 ok，兼容性最好但较慢">
                发送方式
              </div>
              <select
                value={draft.stream_mode}
                onChange={(e) =>
                  setDraft({ ...draft, stream_mode: e.target.value as MachineProfile['stream_mode'] })
                }
              >
                <option value="char_count">流式（字符计数）</option>
                <option value="line">单步（逐行等待 ok）</option>
              </select>
            </div>
          </div>

          <div className="grid-3">
            <label className="row-gap" style={{ cursor: 'pointer', fontSize: 12 }} title="开始书写时以笔尖当前位置为原点 (G92 X0 Y0)">
              <input
                type="checkbox"
                checked={draft.auto_zero_on_start}
                onChange={(e) => setDraft({ ...draft, auto_zero_on_start: e.target.checked })}
              />
              开始时自动置零
            </label>
            <label className="row-gap" style={{ cursor: 'pointer', fontSize: 12 }} title="全部书写完成后发送 $SLP 让电机休眠">
              <input
                type="checkbox"
                checked={draft.sleep_after_job}
                onChange={(e) => setDraft({ ...draft, sleep_after_job: e.target.checked })}
              />
              完成后自动休眠
            </label>
            <label className="row-gap" style={{ cursor: 'pointer', fontSize: 12 }} title="GRBL 0.9 等旧固件：不使用 $J= 点动（连接时也会按欢迎语自动识别）">
              <input
                type="checkbox"
                checked={draft.legacy_grbl}
                onChange={(e) => setDraft({ ...draft, legacy_grbl: e.target.checked })}
              />
              兼容旧版 GRBL 0.9
            </label>
          </div>

          <div>
            <div className="row-between" style={{ marginBottom: 4 }}>
              <span className="ctrl-label">自定义宏（点动面板一键执行）</span>
              <button
                type="button"
                className="btn btn-xs"
                disabled={draft.macros.length >= 8}
                onClick={() =>
                  setDraft({
                    ...draft,
                    macros: [...draft.macros, { name: `宏${draft.macros.length + 1}`, gcode: '' }],
                  })
                }
              >
                <Plus size={11} /> 添加
              </button>
            </div>
            {draft.macros.map((m, i) => (
              <div
                key={i}
                style={{ display: 'grid', gridTemplateColumns: '90px minmax(0,1fr) auto', gap: 6, marginBottom: 4 }}
              >
                <input
                  value={m.name}
                  maxLength={24}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      macros: draft.macros.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)),
                    })
                  }
                />
                <input
                  className="mono"
                  value={m.gcode}
                  placeholder="例如 G0 X0 Y0; M5"
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      macros: draft.macros.map((x, j) => (j === i ? { ...x, gcode: e.target.value } : x)),
                    })
                  }
                />
                <button
                  type="button"
                  className="btn btn-xs"
                  title="删除"
                  onClick={() => setDraft({ ...draft, macros: draft.macros.filter((_, j) => j !== i) })}
                >
                  <Trash2 size={11} />
                </button>
              </div>
            ))}
          </div>

          <div className="grid-2" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <div>
              <div className="ctrl-label" style={{ marginBottom: 3 }}>
                开始前自定义 G-code（换行或 ; 分隔）
              </div>
              <textarea
                className="mono"
                rows={2}
                value={draft.start_gcode}
                onChange={(e) => setDraft({ ...draft, start_gcode: e.target.value })}
              />
            </div>
            <div>
              <div className="ctrl-label" style={{ marginBottom: 3 }}>
                结束后自定义 G-code
              </div>
              <textarea
                className="mono"
                rows={2}
                value={draft.end_gcode}
                onChange={(e) => setDraft({ ...draft, end_gcode: e.target.value })}
              />
            </div>
          </div>

          {Object.keys(draft.grbl_expected).length > 0 && (
            <div className="mono" style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>
              连接时校验固件参数：
              {Object.entries(draft.grbl_expected)
                .map(([k, v]) => `${k}=${v}`)
                .join('  ')}
            </div>
          )}

          <GrblFirmwarePanel />
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
