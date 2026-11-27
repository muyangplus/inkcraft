// Machine profile, serial hardware, job details, and WebSocket telemetry payloads.

import type {
  GrblState,
  JobState,
  MachineState,
  TaskKind,
  TaskState,
  Vec2,
  Vec3,
} from './common';

export interface PenConfig {
  /** servo: 自定义 M 指令；z: 步进 Z 轴；laser: M3 S功率 / M5 */
  mode: 'servo' | 'z' | 'laser';
  servo_up: string;
  servo_down: string;
  /** 抬/落笔后的机构稳定时间 */
  dwell_ms: number;
  /** 落笔后暂停（出墨） */
  down_delay_ms: number;
  /** 抬笔前暂停 */
  up_delay_ms: number;
  z_up_mm: number;
  z_down_mm: number;
  z_feed: number;
  laser_power: number;
}

export type MachineOrigin = 'top_left' | 'top_right' | 'bottom_left' | 'bottom_right';

export interface MachineProfile {
  profile_id: string;
  name: string;
  /** 'auto' = detect the USB-serial adapter at connect time (COM numbers change). */
  port: string;
  baud: number;
  pen: PenConfig;
  workspace_mm: Vec2;
  pen_change_pos_mm: Vec2;
  paper_change_pos_mm: Vec2;
  origin: MachineOrigin;
  /** Paper direction of machine +X / +Y; 'auto' keeps all coordinates positive. */
  x_axis: 'auto' | 'right' | 'left';
  y_axis: 'auto' | 'down' | 'up';
  swap_xy: boolean;
  invert_x: boolean;
  invert_y: boolean;
  offset_mm: Vec2;
  feed_draw: number;
  feed_travel: number;
  jog_feed: number;
  status_hz: number;
  rx_buffer: number;
  rotation_deg: number;
  z_jog_step_mm: number;
  /** 'char_count' = GRBL character-counting streaming; 'line' = 单步（逐行等 ok）. */
  stream_mode: 'char_count' | 'line';
  auto_zero_on_start: boolean;
  sleep_after_job: boolean;
  legacy_grbl: boolean;
  start_gcode: string;
  end_gcode: string;
  macros: MachineMacro[];
  grbl_expected: Record<string, number>;
}

export interface MachineMacro {
  name: string;
  gcode: string;
}

export interface GrblSettingsResponse {
  settings: Array<{ key: string; value: number; name: string }>;
  report_inches: boolean;
  grbl_version: string;
  warnings: Array<{ code: string; message: string; severity: string }>;
}

export interface SerialPortInfo {
  device: string;
  description: string;
  hwid?: string;
  vid?: number | null;
  pid?: number | null;
  adapter?: string;
  recommended?: boolean;
}

export interface JobDetail {
  job_id: string;
  layout_id: string;
  job_state: JobState;
  page_indices: number[];
  current_page_index: number;
  progress?: JobProgressData | null;
}

export interface WsEnvelope<T extends string = string, D = unknown> {
  v: 1;
  type: T;
  seq: number;
  ts: number;
  data: D;
}

export interface MachineStatusData {
  machine_state: MachineState;
  job_state: JobState | null;
  grbl_state: GrblState;
  mpos: Vec3;
  wpos: Vec3;
  feed: number;
  pen: 'up' | 'down';
  buf: { planner: number; rx: number };
  alarm_code: string | number | null;
  mock: boolean;
  port?: string;
  /** Pen position in page coordinates (mm, top-left origin). */
  page_pos?: Vec2;
  report_inches?: boolean;
}

export interface JobProgressData {
  job_id: string;
  job_state: JobState;
  page_index: number;
  page_count: number;
  stroke_index: number;
  stroke_total: number;
  seg_index: number;
  seg_total: number;
  line_acked: number;
  line_total: number;
  pct: number;
  pen_xy: Vec2;
  elapsed_s: number;
  eta_s: number;
  draw_mm: number;
  travel_mm: number;
}

export interface JobEventData {
  job_id: string;
  event:
    | 'started'
    | 'paused'
    | 'pen_change_ready'
    | 'resumed'
    | 'page_done'
    | 'paper_change_required'
    | 'job_done'
    | 'aborted'
    | 'failed'
    | 'alarm'
    | 'estop';
  page_index: number;
  code?: number | string | null;
  message: string;
}

export interface TaskProgressData {
  task_id: string;
  kind: TaskKind;
  state: TaskState;
  stage: string;
  pct: number;
  page?: number | null;
  page_count?: number | null;
  message: string;
}

export interface AlarmEventData {
  code: string | number;
  message: string;
  severity: 'info' | 'warn' | 'critical';
}

export interface SerialLogData {
  dir: 'tx' | 'rx';
  line: string;
}
