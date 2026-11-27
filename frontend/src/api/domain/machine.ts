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
  mode: 'servo' | 'z';
  servo_up: string;
  servo_down: string;
  dwell_ms: number;
  z_up_mm: number;
  z_down_mm: number;
  z_feed: number;
}

export interface MachineProfile {
  profile_id: string;
  name: string;
  baud: number;
  pen: PenConfig;
  workspace_mm: Vec2;
  pen_change_pos_mm: Vec2;
  paper_change_pos_mm: Vec2;
  origin: 'top_left' | 'bottom_left';
  invert_x: boolean;
  invert_y: boolean;
  feed_draw: number;
  feed_travel: number;
  jog_feed: number;
  status_hz: number;
  rx_buffer: number;
}

export interface SerialPortInfo {
  device: string;
  description: string;
  hwid?: string;
  vid?: number | null;
  pid?: number | null;
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
