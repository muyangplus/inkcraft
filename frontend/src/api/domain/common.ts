// Shared transport, status, geometry, and envelope types.

export type MachineState =
  | 'DISCONNECTED'
  | 'CONNECTING'
  | 'IDLE'
  | 'JOGGING'
  | 'FRAMING'
  | 'RUNNING'
  | 'HOLDING'
  | 'PAUSED'
  | 'PEN_CHANGE'
  | 'PAPER_CHANGE'
  | 'ALARM'
  | 'ESTOPPED'
  | 'ERROR';

export type GrblState =
  | 'Idle'
  | 'Run'
  | 'Hold:0'
  | 'Hold:1'
  | 'Jog'
  | 'Alarm'
  | 'Door'
  | 'Check'
  | 'Home'
  | 'Sleep';

export type JobState =
  | 'QUEUED'
  | 'PREPARING'
  | 'STREAMING'
  | 'PAUSED'
  | 'PEN_CHANGE'
  | 'WAIT_PAPER'
  | 'COMPLETED'
  | 'ABORTED'
  | 'FAILED';

export type TaskKind = 'parse' | 'compose' | 'font_import';
export type TaskState = 'pending' | 'running' | 'done' | 'failed';
export type StrokeKind = 'text' | 'formula' | 'table' | 'chart' | 'rule' | 'frame';

export interface Vec2 {
  x: number;
  y: number;
}

export interface Vec3 {
  x: number;
  y: number;
  z: number;
}

export interface HealthResponse {
  status: string;
  version: string;
  contract_version: number;
  gpu?: {
    available: boolean;
    name?: string | null;
    vram_free_mb?: number | null;
  };
}

export interface TaskStatus {
  task_id: string;
  kind: TaskKind;
  state: TaskState;
  stage: string;
  pct: number;
  page?: number | null;
  page_count?: number | null;
  message: string;
  result?: Record<string, unknown> | null;
  error?: string | null;
}

export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown> | null;
  };
}
