import React, { useState } from 'react';
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  ChevronRight,
  Crosshair,
  Home,
  Keyboard,
  LocateFixed,
  Navigation,
  Send,
  Square,
  Target,
  Unlock,
} from 'lucide-react';
import { useDocumentLayoutStore } from '../../stores/useDocumentLayoutStore';
import { useMachineStore } from '../../stores/useMachineStore';
import { useViewportStore } from '../../stores/useViewportStore';

const STEPS: Array<0.1 | 1 | 10 | 50> = [0.1, 1, 10, 50];

const DIRS = [
  { label: '↖', dx: -1, dy: -1 },
  { label: '↑', dx: 0, dy: -1 },
  { label: '↗', dx: 1, dy: -1 },
  { label: '←', dx: -1, dy: 0 },
  { label: '设0', dx: 0, dy: 0 },
  { label: '→', dx: 1, dy: 0 },
  { label: '↙', dx: -1, dy: 1 },
  { label: '↓', dx: 0, dy: 1 },
  { label: '↘', dx: 1, dy: 1 },
];

export const JogControlPad: React.FC = () => {
  const layout = useDocumentLayoutStore((s) => s.layout);
  const currentPageIndex = useDocumentLayoutStore((s) => s.currentPageIndex);
  const activePagePaths = useDocumentLayoutStore((s) => s.activePagePaths);

  const machineState = useMachineStore((s) => s.machineState);
  const jogStepMm = useMachineStore((s) => s.jogStepMm);
  const busyAction = useMachineStore((s) => s.busyAction);
  const setJogStepMm = useMachineStore((s) => s.setJogStepMm);
  const jog = useMachineStore((s) => s.jog);
  const cancelJog = useMachineStore((s) => s.cancelJog);
  const zeroXY = useMachineStore((s) => s.zeroXY);
  const gotoZero = useMachineStore((s) => s.gotoZero);
  const moveTo = useMachineStore((s) => s.moveTo);
  const moveToStart = useMachineStore((s) => s.moveToStart);
  const home = useMachineStore((s) => s.home);
  const sendRawCommand = useMachineStore((s) => s.sendRawCommand);
  const setPen = useMachineStore((s) => s.setPen);
  const unlock = useMachineStore((s) => s.unlock);
  const profiles = useMachineStore((s) => s.profiles);
  const activeProfileId = useMachineStore((s) => s.activeProfileId);

  const jogKeyboardActive = useViewportStore((s) => s.jogKeyboardActive);
  const setJogKeyboardActive = useViewportStore((s) => s.setJogKeyboardActive);

  const [advOpen, setAdvOpen] = useState(false);
  const [targetX, setTargetX] = useState('0');
  const [targetY, setTargetY] = useState('0');
  const [rawCmd, setRawCmd] = useState('');
  const [cmdOutput, setCmdOutput] = useState<string[]>([]);

  const profile =
    profiles.find((p) => p.profile_id === activeProfileId) ??
    useMachineStore.getState().getActiveProfile();

  const canJog = machineState === 'IDLE';
  const canZero = machineState === 'IDLE' || machineState === 'PEN_CHANGE';
  const canMove =
    machineState === 'IDLE' ||
    machineState === 'PEN_CHANGE' ||
    machineState === 'PAPER_CHANGE';
  const canMoveStart =
    (machineState === 'IDLE' ||
      machineState === 'PAUSED' ||
      machineState === 'PEN_CHANGE' ||
      machineState === 'PAPER_CHANGE') &&
    Boolean(layout) &&
    ((activePagePaths?.strokeCount ?? layout?.pages[currentPageIndex]?.stats.stroke_count ?? 0) > 0 ||
      machineState === 'PAUSED' ||
      machineState === 'PEN_CHANGE');
  const canPenTest =
    machineState === 'IDLE' ||
    machineState === 'PAUSED' ||
    machineState === 'PEN_CHANGE' ||
    machineState === 'PAPER_CHANGE';
  const canUnlock = machineState === 'ALARM' || machineState === 'ESTOPPED';
  const canHome =
    machineState === 'IDLE' || machineState === 'ALARM' || machineState === 'ESTOPPED';
  const canRaw =
    machineState === 'IDLE' ||
    machineState === 'PAUSED' ||
    machineState === 'PEN_CHANGE' ||
    machineState === 'PAPER_CHANGE' ||
    machineState === 'ALARM' ||
    machineState === 'ESTOPPED';
  const isJogging = machineState === 'JOGGING';
  const isResumeStart = machineState === 'PAUSED' || machineState === 'PEN_CHANGE';

  const handleExecRaw = async (cmdText?: string) => {
    const toRun = (cmdText ?? rawCmd).trim();
    if (!toRun) return;
    const lines = await sendRawCommand(toRun);
    setCmdOutput(lines);
    if (!cmdText) setRawCmd('');
  };

  return (
    <div className="section-card">
      <div className="section-head">
        <span>对零与调试 (Jog / G92)</span>
        <button
          type="button"
          className={`btn btn-xs ${jogKeyboardActive ? 'btn-primary' : ''}`}
          onClick={() => setJogKeyboardActive(!jogKeyboardActive)}
          title="开启/关闭键盘方向键与 WASD 直接点动控制"
        >
          <Keyboard size={11} /> {jogKeyboardActive ? '键盘开' : '键盘'}
        </button>
      </div>

      {/* D-pad + 2x2 Step Selector */}
      <div className="jog-layout">
        <div className="jog-grid">
          {DIRS.map((d) =>
            d.label === '设0' ? (
              <button
                key="zero"
                type="button"
                className="jog-btn center mono"
                disabled={!canZero}
                title={canZero ? '将当前位置设为工作原点 G92 X0 Y0' : '仅 IDLE 态允许设为 0 点'}
                onClick={() => void zeroXY()}
              >
                设0
              </button>
            ) : (
              <button
                key={d.label}
                type="button"
                className="jog-btn"
                disabled={!canJog}
                title={
                  canJog
                    ? `点动 ΔX=${d.dx * jogStepMm}mm ΔY=${d.dy * jogStepMm}mm`
                    : `当前状态 (${machineState}) 禁止点动`
                }
                onClick={() => void jog(d.dx * jogStepMm, d.dy * jogStepMm)}
              >
                {d.label}
              </button>
            ),
          )}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
          <div style={{ fontSize: 10.5, color: 'var(--text-secondary)', fontWeight: 600 }}>
            步进距离 (mm)
          </div>
          <div className="step-chips">
            {STEPS.map((st) => (
              <button
                key={st}
                type="button"
                className={`step-chip mono ${jogStepMm === st ? 'active' : ''}`}
                onClick={() => setJogStepMm(st)}
              >
                {st}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* 4 Primary Streamlined Calibration Buttons */}
      <div className="grid-2">
        <button
          type="button"
          className="btn btn-sm"
          disabled={!canZero || busyAction !== null}
          title="执行 G92 X0 Y0 将当前位置设为工作 0 点"
          onClick={() => void zeroXY()}
        >
          <Target size={12} /> 设为 0 点
        </button>
        <button
          type="button"
          className="btn btn-sm"
          disabled={!canMove || busyAction === 'gotoZero'}
          title="强制抬笔并快速回到当前工作原点 (X0, Y0)"
          onClick={() => void gotoZero()}
        >
          <LocateFixed size={12} /> 回到 0 点
        </button>
        <button
          type="button"
          className="btn btn-sm"
          disabled={!canPenTest}
          title="执行抬笔测试"
          onClick={() => void setPen('up')}
        >
          <ArrowUp size={12} /> 抬笔
        </button>
        <button
          type="button"
          className="btn btn-sm"
          disabled={!canPenTest}
          title="执行落笔触纸测试"
          onClick={() => void setPen('down')}
        >
          <ArrowDown size={12} /> 落笔
        </button>
      </div>

      {/* Dedicated Action: Move to Next Writing Start Point */}
      <button
        type="button"
        className="btn btn-cyan btn-sm"
        style={{ width: '100%' }}
        disabled={!canMoveStart || busyAction === 'moveToStart'}
        title={
          isResumeStart
            ? '抬笔并移动至暂停断点坐标，方便预览校准下一次续写位置'
            : `抬笔并移动至 P${currentPageIndex + 1} 首笔落笔起点，预览确认纸张对位`
        }
        onClick={() => {
          if (layout) void moveToStart(layout.layout_id, currentPageIndex);
        }}
      >
        <Navigation size={12} />
        {isResumeStart ? '移至续写断点' : `移至书写起点 (P${currentPageIndex + 1})`}
      </button>

      {(isJogging || canUnlock) && (
        <div className="grid-2">
          {isJogging && (
            <button type="button" className="btn btn-sm btn-warn" onClick={() => void cancelJog()}>
              <Square size={11} /> 取消点动
            </button>
          )}
          {canUnlock && (
            <button type="button" className="btn btn-sm btn-warn" onClick={() => void unlock()}>
              <Unlock size={12} /> $X 解锁
            </button>
          )}
        </div>
      )}

      {/* Collapsible Advanced GRBL Tuning & Raw Command Drawer */}
      <button
        type="button"
        className="collapsible-toggle"
        onClick={() => setAdvOpen((v) => !v)}
      >
        <span>高级调试 (坐标 / $H / 指令)</span>
        {advOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
      </button>

      {advOpen && (
        <div className="grbl-advanced-box">
          <div style={{ fontSize: 10.5, color: 'var(--text-muted)', fontWeight: 600 }}>
            定距抬笔定位移动 (WPos mm)
          </div>
          <div className="grbl-coord-row">
            <input
              type="number"
              className="mono"
              placeholder="X"
              aria-label="目标 X 坐标"
              value={targetX}
              onChange={(e) => setTargetX(e.target.value)}
              style={{ padding: '4px 6px', fontSize: 11 }}
            />
            <input
              type="number"
              className="mono"
              placeholder="Y"
              aria-label="目标 Y 坐标"
              value={targetY}
              onChange={(e) => setTargetY(e.target.value)}
              style={{ padding: '4px 6px', fontSize: 11 }}
            />
            <button
              type="button"
              className="btn btn-xs btn-primary"
              disabled={!canMove || busyAction === 'moveTo'}
              onClick={() => void moveTo(Number(targetX) || 0, Number(targetY) || 0)}
            >
              移动
            </button>
          </div>

          <div className="grid-2">
            <button
              type="button"
              className="btn btn-xs"
              disabled={!canHome || busyAction === 'home'}
              title="执行硬件回零循环 $H"
              onClick={() => void home()}
            >
              <Home size={11} /> $H 回零
            </button>
            <button
              type="button"
              className="btn btn-xs"
              disabled={!canUnlock || busyAction === 'unlock'}
              title="发送 $X 解除报警锁"
              onClick={() => void unlock()}
            >
              <Unlock size={11} /> $X 解锁
            </button>
            <button
              type="button"
              className="btn btn-xs"
              disabled={!canMove || busyAction === 'moveTo'}
              title={`抬笔移至档案换笔泊位 (${profile.pen_change_pos_mm.x}, ${profile.pen_change_pos_mm.y})`}
              onClick={() =>
                void moveTo(profile.pen_change_pos_mm.x, profile.pen_change_pos_mm.y)
              }
            >
              <Crosshair size={11} /> 换笔泊位
            </button>
            <button
              type="button"
              className="btn btn-xs"
              disabled={!canRaw || busyAction === 'rawCmd'}
              title="查询当前固件 GRBL $$ 参数"
              onClick={() => void handleExecRaw('$$')}
            >
              $$ 参数
            </button>
          </div>

          <div className="grbl-cmd-row">
            <input
              type="text"
              className="mono"
              placeholder="GRBL 指令 (如 $32=0 / G0 X10 Y10)"
              value={rawCmd}
              disabled={!canRaw}
              onChange={(e) => setRawCmd(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  void handleExecRaw();
                }
              }}
              style={{ padding: '4px 6px', fontSize: 11 }}
            />
            <button
              type="button"
              className="btn btn-xs btn-primary"
              disabled={!canRaw || !rawCmd.trim() || busyAction === 'rawCmd'}
              onClick={() => void handleExecRaw()}
            >
              <Send size={10} /> 发送
            </button>
          </div>

          {cmdOutput.length > 0 && (
            <div className="grbl-resp-box mono">{cmdOutput.join('\n')}</div>
          )}
        </div>
      )}
    </div>
  );
};
