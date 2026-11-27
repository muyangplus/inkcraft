import { create } from 'zustand';
import { restClient } from '../api/restClient';
import { telemetrySocket } from '../api/telemetrySocket';
import type {
  AlarmEventData,
  GrblState,
  JobEventData,
  JobState,
  MachineProfile,
  MachineState,
  MachineStatusData,
  SerialPortInfo,
} from '../api/types';
import { telemetryBus } from './telemetryBus';
import { useViewportStore } from './useViewportStore';

const FALLBACK_PROFILE: MachineProfile = {
  profile_id: 'corexy_servo_a4',
  name: 'CoreXY A4 舵机写字机 (GRBL 1.1)',
  port: 'auto',
  baud: 115200,
  pen: {
    mode: 'servo',
    servo_up: 'M5',
    servo_down: 'M3 S90',
    dwell_ms: 120,
    z_up_mm: 4.0,
    z_down_mm: 0.0,
    z_feed: 1200,
    down_delay_ms: 0,
    up_delay_ms: 0,
    laser_power: 1000,
  },
  workspace_mm: { x: 220, y: 310 },
  pen_change_pos_mm: { x: 10, y: 10 },
  paper_change_pos_mm: { x: 0, y: 0 },
  origin: 'top_left',
  x_axis: 'auto',
  y_axis: 'auto',
  swap_xy: false,
  invert_x: false,
  invert_y: false,
  offset_mm: { x: 0, y: 0 },
  feed_draw: 2400,
  feed_travel: 5000,
  jog_feed: 3000,
  status_hz: 10,
  rx_buffer: 128,
  rotation_deg: 0,
  z_jog_step_mm: 1,
  stream_mode: 'char_count',
  auto_zero_on_start: false,
  sleep_after_job: false,
  legacy_grbl: false,
  start_gcode: '',
  end_gcode: '',
  macros: [],
  grbl_expected: {},
};

/** Fill fields that older backends / stored profiles may lack. */
export function normalizeMachineProfile(p: Partial<MachineProfile>): MachineProfile {
  return {
    ...FALLBACK_PROFILE,
    ...p,
    pen: { ...FALLBACK_PROFILE.pen, ...p.pen },
    offset_mm: { ...FALLBACK_PROFILE.offset_mm, ...p.offset_mm },
    grbl_expected: { ...(p.grbl_expected ?? {}) },
    macros: [...(p.macros ?? [])],
  } as MachineProfile;
}

/** COM numbers change between USB sockets, so "auto" is the default port. */
export const AUTO_PORT = 'auto';

export interface MachineStoreState {
  // WebSocket link state
  wsConnected: boolean;
  wsReconnectAttempt: number;

  // Low-frequency discrete machine & job states
  machineState: MachineState;
  jobState: JobState | null;
  grblState: GrblState;
  pen: 'up' | 'down';
  mock: boolean;
  alarmCode: string | number | null;
  lastAlarmMessage: string | null;

  // Active job metadata
  activeJobId: string | null;
  activeJobPageIndex: number;
  activeJobPageCount: number;

  // Connection form
  ports: SerialPortInfo[];
  selectedPort: string;
  baud: number;
  profiles: MachineProfile[];
  activeProfileId: string;
  jogStepMm: 0.1 | 1 | 10 | 50;
  busyAction: string | null;

  // Actions
  setWsConnection: (connected: boolean, attempt: number) => void;
  applyDiscreteStatus: (status: MachineStatusData) => void;
  handleJobEvent: (event: JobEventData) => void;
  handleAlarm: (alarm: AlarmEventData) => void;
  setActiveJobPage: (jobId: string, pageIndex: number, pageCount: number, jobState: JobState) => void;

  fetchPorts: () => Promise<void>;
  fetchProfiles: () => Promise<void>;
  saveProfile: (profile: MachineProfile) => Promise<void>;
  jogZ: (dz: number) => Promise<void>;
  runMacro: (index: number) => Promise<void>;

  setSelectedPort: (port: string) => void;
  setBaud: (baud: number) => void;
  setActiveProfileId: (profileId: string) => void;
  setMock: (mock: boolean) => void;
  setJogStepMm: (step: 0.1 | 1 | 10 | 50) => void;

  connect: () => Promise<void>;
  disconnect: () => Promise<void>;
  jog: (dx: number, dy: number) => Promise<void>;
  cancelJog: () => Promise<void>;
  zeroXY: () => Promise<void>;
  gotoZero: () => Promise<void>;
  moveTo: (x: number, y: number, feed?: number) => Promise<void>;
  moveToStart: (layoutId: string, pageIndex: number) => Promise<void>;
  home: () => Promise<void>;
  sendRawCommand: (command: string) => Promise<string[]>;
  setPen: (state: 'up' | 'down') => Promise<void>;
  testPenOverride: (
    state: 'up' | 'down',
    overrides?: { overrideCmd?: string; overrideZMm?: number; overrideZFeed?: number },
  ) => Promise<void>;
  frameCheck: (layoutId: string, pageIndex: number) => Promise<void>;
  unlock: () => Promise<void>;
  estop: () => Promise<void>;

  startJob: (layoutId: string, pageIndices: number[], startPageIndex?: number) => Promise<void>;
  pauseJob: () => Promise<void>;
  resumeJob: () => Promise<void>;
  enterPenChange: () => Promise<void>;
  confirmPaperReady: (pageIndex: number) => Promise<void>;
  abortJob: () => Promise<void>;

  getActiveProfile: () => MachineProfile;
}

export const useMachineStore = create<MachineStoreState>((set, get) => ({
  wsConnected: false,
  wsReconnectAttempt: 0,

  machineState: 'DISCONNECTED',
  jobState: null,
  grblState: 'Idle',
  pen: 'up',
  mock: false,
  alarmCode: null,
  lastAlarmMessage: null,

  activeJobId: null,
  activeJobPageIndex: 0,
  activeJobPageCount: 1,

  ports: [{ device: 'MOCK', description: 'Mock GRBL 1.1 仿真串口' }],
  selectedPort: AUTO_PORT,
  baud: 115200,
  profiles: [FALLBACK_PROFILE],
  activeProfileId: FALLBACK_PROFILE.profile_id,
  jogStepMm: 10,
  busyAction: null,

  setWsConnection: (wsConnected, wsReconnectAttempt) =>
    set({ wsConnected, wsReconnectAttempt }),

  applyDiscreteStatus: (status) => {
    set((s) => ({
      machineState: status.machine_state,
      jobState: status.job_state,
      grblState: status.grbl_state,
      pen: status.pen,
      mock: status.mock,
      alarmCode: status.alarm_code,
      lastAlarmMessage:
        status.machine_state === 'IDLE' ? null : s.lastAlarmMessage,
    }));
    const vp = useViewportStore.getState();
    if (status.machine_state === 'PEN_CHANGE') {
      vp.setPenChangeOpen(true);
    } else if (vp.penChangeOpen) {
      vp.setPenChangeOpen(false);
    }
  },

  handleJobEvent: (ev) => {
    const vp = useViewportStore.getState();
    switch (ev.event) {
      case 'started':
        set({ activeJobId: ev.job_id, jobState: 'STREAMING', activeJobPageIndex: ev.page_index });
        vp.pushToast(`开始书写作业 (第 ${ev.page_index + 1} 页)`, 'info');
        break;
      case 'paused':
        set({ jobState: 'PAUSED' });
        vp.pushToast('作业已平滑暂停并抬笔', 'warn');
        break;
      case 'pen_change_ready':
        set({ jobState: 'PEN_CHANGE', machineState: 'PEN_CHANGE' });
        vp.setPenChangeOpen(true);
        vp.pushToast('写字机已到达换笔安全泊位', 'warn');
        break;
      case 'resumed':
        set({ jobState: 'STREAMING' });
        vp.setPenChangeOpen(false);
        vp.pushToast('已回位落笔，继续书写', 'success');
        break;
      case 'page_done':
        vp.pushToast(`第 ${ev.page_index + 1} 页书写完成`, 'success');
        break;
      case 'paper_change_required':
        set({
          activeJobId: ev.job_id,
          jobState: 'WAIT_PAPER',
          machineState: 'PAPER_CHANGE',
          activeJobPageIndex: ev.page_index,
        });
        vp.openPaperChangeModal(ev.page_index);
        break;
      case 'job_done':
        set({ jobState: 'COMPLETED', activeJobId: null });
        telemetryBus.publishProgress(null);
        vp.setPenChangeOpen(false);
        if (vp.activeModal === 'paper-change') vp.openModal(null);
        vp.pushToast('全部页面书写完成！笔头已安全归位', 'success');
        break;
      case 'aborted':
        set({ jobState: 'ABORTED', activeJobId: null });
        telemetryBus.publishProgress(null);
        vp.setPenChangeOpen(false);
        if (vp.activeModal === 'paper-change') vp.openModal(null);
        vp.pushToast('作业已中止并抬笔归位', 'warn');
        break;
      case 'failed':
        set({ jobState: 'FAILED', activeJobId: null });
        telemetryBus.publishProgress(null);
        vp.pushToast(`作业异常终止: ${ev.message}`, 'error');
        break;
      case 'estop':
        set({ machineState: 'ESTOPPED', jobState: 'ABORTED', lastAlarmMessage: ev.message });
        vp.setPenChangeOpen(false);
        if (vp.activeModal === 'paper-change') vp.openModal(null);
        vp.pushToast('已触发紧急停止 (0x18 + 抬笔)', 'error');
        break;
      case 'alarm':
        set({ machineState: 'ALARM', alarmCode: ev.code ?? 'ALARM', lastAlarmMessage: ev.message });
        vp.pushToast(`机台告警: ${ev.message}`, 'error');
        break;
      default:
        break;
    }
  },

  handleAlarm: (alarm) => {
    set({
      alarmCode: alarm.code,
      lastAlarmMessage: alarm.message,
    });
    const tone = alarm.severity === 'critical' ? 'error' : alarm.severity === 'warn' ? 'warn' : 'info';
    useViewportStore.getState().pushToast(`[${alarm.code}] ${alarm.message}`, tone);
  },

  setActiveJobPage: (activeJobId, activeJobPageIndex, activeJobPageCount, jobState) =>
    set({ activeJobId, activeJobPageIndex, activeJobPageCount, jobState }),

  fetchPorts: async () => {
    try {
      const res = await restClient.listPorts();
      const ports = res.ports.length
        ? res.ports
        : [{ device: 'MOCK', description: 'Mock GRBL 1.1 仿真串口' }];
      set((s) => ({
        ports,
        selectedPort:
          s.selectedPort === AUTO_PORT ||
          s.selectedPort === 'MOCK' ||
          ports.some((p) => p.device === s.selectedPort)
            ? s.selectedPort
            : AUTO_PORT,
      }));
    } catch {
      // keep existing fallback
    }
  },

  fetchProfiles: async () => {
    try {
      const res = await restClient.listProfiles();
      if (res.profiles.length > 0) {
        res.profiles = res.profiles.map(normalizeMachineProfile);
        const activeId = res.active_profile_id || res.profiles[0].profile_id;
        const active = res.profiles.find((p) => p.profile_id === activeId) ?? res.profiles[0];
        set({
          profiles: res.profiles,
          activeProfileId: active.profile_id,
          baud: active.baud || 115200,
        });
      }
    } catch {
      // keep fallback profile
    }
  },

  saveProfile: async (profile) => {
    try {
      const res = await restClient.updateProfile(profile.profile_id, profile);
      const saved = normalizeMachineProfile(res.profile);
      set((s) => ({
        profiles: s.profiles.some((p) => p.profile_id === saved.profile_id)
          ? s.profiles.map((p) => (p.profile_id === saved.profile_id ? saved : p))
          : [...s.profiles, saved],
        activeProfileId: saved.profile_id,
        baud: saved.baud,
      }));
      useViewportStore.getState().pushToast('机台档案已保存', 'success');
    } catch (err) {
      useViewportStore.getState().pushToast(
        `保存机台档案失败: ${err instanceof Error ? err.message : String(err)}`,
        'error',
      );
      throw err;
    }
  },

  jogZ: async (dz) => {
    const profile = get().getActiveProfile();
    try {
      await restClient.jogMachine(0, 0, profile.pen.z_feed || 1200, dz);
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`Z 点动失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    }
  },

  runMacro: async (index) => {
    set({ busyAction: `macro-${index}` });
    try {
      const res = await restClient.runMachineMacro(index);
      useViewportStore.getState().pushToast(`已执行宏「${res.macro}」(${res.lines.length} 行)`, 'success');
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`执行宏失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    } finally {
      set({ busyAction: null });
    }
  },

  setSelectedPort: (selectedPort) => set({ selectedPort }),
  setBaud: (baud) => set({ baud }),
  setActiveProfileId: (activeProfileId) => {
    const profile = get().profiles.find((p) => p.profile_id === activeProfileId);
    set({ activeProfileId, baud: profile?.baud ?? get().baud });
  },
  setMock: (mock) =>
    set((s) => ({
      mock,
      selectedPort: mock ? 'MOCK' : s.selectedPort === 'MOCK' ? AUTO_PORT : s.selectedPort,
    })),
  setJogStepMm: (jogStepMm) => set({ jogStepMm }),

  connect: async () => {
    const { selectedPort, baud, activeProfileId, mock } = get();
    set({ busyAction: 'connect', machineState: 'CONNECTING' });
    try {
      const res = await restClient.connectMachine({
        port: mock ? 'MOCK' : selectedPort,
        baud,
        profile_id: activeProfileId,
        mock,
      });
      set({
        machineState: res.machine_state,
        activeProfileId: res.profile_id,
        mock: res.mock,
        alarmCode: null,
        lastAlarmMessage: null,
      });
      useViewportStore
        .getState()
        .pushToast(
          res.mock ? '已连接 Mock GRBL 仿真机台' : `已连接串口 ${res.port ?? selectedPort}`,
          'success',
        );
    } catch (err) {
      set({ machineState: 'ERROR' });
      useViewportStore
        .getState()
        .pushToast(`连接失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    } finally {
      set({ busyAction: null });
    }
  },

  disconnect: async () => {
    set({ busyAction: 'disconnect' });
    try {
      await restClient.disconnectMachine();
      set({ machineState: 'DISCONNECTED', jobState: null, activeJobId: null });
      telemetryBus.publishProgress(null);
      useViewportStore.getState().pushToast('已断开 GRBL 连接', 'info');
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`断开失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    } finally {
      set({ busyAction: null });
    }
  },

  jog: async (dx, dy) => {
    const profile = get().getActiveProfile();
    const feed = profile.jog_feed || 3000;
    // Prefer low-latency WebSocket channel; fall back to REST if WS closed
    if (!telemetrySocket.sendJog(dx, dy, feed)) {
      try {
        await restClient.jogMachine(dx, dy, feed);
      } catch (err) {
        useViewportStore
          .getState()
          .pushToast(`点动失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
      }
    }
  },

  cancelJog: async () => {
    telemetrySocket.sendJogCancel();
    try {
      await restClient.cancelJog();
    } catch {
      // ignore
    }
  },

  zeroXY: async () => {
    try {
      await restClient.zeroMachine(['X', 'Y']);
      useViewportStore.getState().pushToast('已设当前点为工作原点 (G92 X0 Y0)', 'success');
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`归零失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    }
  },

  gotoZero: async () => {
    set({ busyAction: 'gotoZero' });
    try {
      await restClient.gotoZeroMachine();
      set({ pen: 'up' });
      useViewportStore.getState().pushToast('已抬笔并回到工作原点 (X0, Y0)', 'success');
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`回原点失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    } finally {
      set({ busyAction: null });
    }
  },

  moveTo: async (x, y, feed) => {
    set({ busyAction: 'moveTo' });
    try {
      const res = await restClient.moveToMachine(x, y, feed, true);
      set({ pen: 'up' });
      useViewportStore
        .getState()
        .pushToast(`已抬笔移至 (${res.target.x}, ${res.target.y}) mm`, 'success');
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`定位移动失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    } finally {
      set({ busyAction: null });
    }
  },

  moveToStart: async (layoutId, pageIndex) => {
    set({ busyAction: 'moveToStart' });
    try {
      const res = await restClient.moveToStartMachine(layoutId, pageIndex);
      set({ pen: 'up' });
      const label =
        res.source === 'resume_breakpoint'
          ? `已抬笔移至续写断点 #${res.stroke_index + 1}`
          : `已抬笔移至 P${pageIndex + 1} 书写起点`;
      useViewportStore
        .getState()
        .pushToast(`${label} (${res.target.x}, ${res.target.y})`, 'success');
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`移动至书写起点失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    } finally {
      set({ busyAction: null });
    }
  },

  home: async () => {
    set({ busyAction: 'home' });
    try {
      const res = await restClient.homeMachine();
      set({
        machineState: res.machine_state,
        pen: 'up',
        alarmCode: null,
        lastAlarmMessage: null,
      });
      useViewportStore.getState().pushToast('已完成机械回零 ($H) 并抬笔', 'success');
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`机械回零失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    } finally {
      set({ busyAction: null });
    }
  },

  sendRawCommand: async (command) => {
    const cleaned = command.trim();
    if (!cleaned) return [];
    set({ busyAction: 'rawCmd' });
    try {
      const res = await restClient.sendRawCommand(cleaned);
      return res.responses.length > 0 ? res.responses : ['ok'];
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      useViewportStore.getState().pushToast(`指令执行失败: ${msg}`, 'error');
      return [`ERR: ${msg}`];
    } finally {
      set({ busyAction: null });
    }
  },

  setPen: async (state) => {
    try {
      const res = await restClient.setPen(state);
      set({ pen: res.pen });
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`抬落笔控制失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    }
  },

  testPenOverride: async (state, overrides) => {
    try {
      const res = await restClient.setPen(state, overrides);
      set({ pen: res.pen });
      useViewportStore
        .getState()
        .pushToast(state === 'up' ? '已实时测试抬笔位置' : '已实时测试落笔触纸高度', 'info');
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`实时测试失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    }
  },

  frameCheck: async (layoutId, pageIndex) => {
    set({ busyAction: 'frame' });
    try {
      const res = await restClient.frameCheck(layoutId, pageIndex);
      set({ machineState: res.machine_state });
      useViewportStore.getState().pushToast(`正在试跑第 ${pageIndex + 1} 页外框边界 (强制抬笔)`, 'info');
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`外框试跑被拦截: ${err instanceof Error ? err.message : String(err)}`, 'error');
    } finally {
      set({ busyAction: null });
    }
  },

  unlock: async () => {
    set({ busyAction: 'unlock' });
    try {
      const res = await restClient.unlockMachine();
      set({ machineState: res.machine_state, alarmCode: null, lastAlarmMessage: null });
      useViewportStore.getState().pushToast('已执行 $X 解锁并确保抬笔', 'success');
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`解锁失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    } finally {
      set({ busyAction: null });
    }
  },

  estop: async () => {
    // Dual-channel immediate E-STOP: WS lowest latency + REST guaranteed fallback
    telemetrySocket.sendEstop();
    set({ machineState: 'ESTOPPED' });
    try {
      await restClient.estopMachine();
    } catch {
      // WS channel already triggered
    }
  },

  startJob: async (layoutId, pageIndices, startPageIndex = 0) => {
    set({ busyAction: 'startJob' });
    try {
      const res = await restClient.createJob({
        layout_id: layoutId,
        page_indices: pageIndices,
        start_page_index: startPageIndex,
      });
      set({
        activeJobId: res.job_id,
        jobState: res.job_state,
        activeJobPageIndex: pageIndices.includes(startPageIndex)
          ? startPageIndex
          : (pageIndices[0] ?? 0),
        activeJobPageCount: pageIndices.length,
      });
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`启动书写失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    } finally {
      set({ busyAction: null });
    }
  },

  pauseJob: async () => {
    const jobId = get().activeJobId;
    if (!jobId) return;
    try {
      const res = await restClient.pauseJob(jobId);
      set({ jobState: res.job_state, machineState: res.machine_state });
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`暂停失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    }
  },

  resumeJob: async () => {
    const jobId = get().activeJobId;
    if (!jobId) return;
    try {
      const res = await restClient.resumeJob(jobId);
      set({ jobState: res.job_state, machineState: res.machine_state });
      useViewportStore.getState().setPenChangeOpen(false);
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`续写失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    }
  },

  enterPenChange: async () => {
    const jobId = get().activeJobId;
    if (!jobId) return;
    try {
      const res = await restClient.penChangeJob(jobId);
      set({ jobState: res.job_state, machineState: res.machine_state });
      useViewportStore.getState().setPenChangeOpen(true);
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`进入换笔模式失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    }
  },

  confirmPaperReady: async (pageIndex) => {
    const jobId = get().activeJobId;
    if (!jobId) return;
    try {
      const res = await restClient.paperReadyJob(jobId, pageIndex);
      set({ jobState: res.job_state, activeJobPageIndex: res.page_index });
      useViewportStore.getState().openModal(null);
      useViewportStore.getState().pushToast(`已确认换纸，开始书写第 ${pageIndex + 1} 页`, 'success');
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`确认换纸失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    }
  },

  abortJob: async () => {
    const jobId = get().activeJobId;
    if (!jobId) return;
    try {
      await restClient.abortJob(jobId);
      set({ jobState: 'ABORTED', activeJobId: null });
      telemetryBus.publishProgress(null);
      const vp = useViewportStore.getState();
      vp.setPenChangeOpen(false);
      if (vp.activeModal === 'paper-change') vp.openModal(null);
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`中止作业失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    }
  },

  getActiveProfile: () => {
    const { profiles, activeProfileId } = get();
    return profiles.find((p) => p.profile_id === activeProfileId) ?? profiles[0] ?? FALLBACK_PROFILE;
  },
}));
