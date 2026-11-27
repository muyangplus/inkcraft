import type {
  AlarmEventData,
  JobEventData,
  JobProgressData,
  MachineStatusData,
  SerialLogData,
  TaskProgressData,
  WsEnvelope,
} from './types';
import { telemetryBus } from '../stores/telemetryBus';

export interface TelemetryHandlers {
  onConnectionChange?: (connected: boolean, attempt: number) => void;
  onMachineDiscreteChange?: (status: MachineStatusData) => void;
  onJobEvent?: (event: JobEventData) => void;
  onJobProgressDiscrete?: (progress: JobProgressData) => void;
  onTaskProgress?: (task: TaskProgressData) => void;
  onWriterChanged?: (writerId: string) => void;
  onAlarm?: (alarm: AlarmEventData) => void;
}

const BACKOFF_MS = [500, 1000, 2000, 5000];

class TelemetrySocket {
  private ws: WebSocket | null = null;
  private handlers: TelemetryHandlers = {};
  private reconnectTimer: number | null = null;
  private pingTimer: number | null = null;
  private attempt = 0;
  private intentionallyClosed = false;
  private serialSubscribed = false;
  private seq = 1;

  // Track last discrete state so React Zustand store is ONLY updated on discrete transitions
  private lastDiscreteKey = '';
  private lastJobPageKey = '';

  configure(handlers: TelemetryHandlers): void {
    this.handlers = handlers;
  }

  connect(): void {
    this.intentionallyClosed = false;
    this.clearTimers();
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${window.location.host}/ws/telemetry`;

    try {
      const ws = new WebSocket(url);
      this.ws = ws;

      ws.onopen = () => {
        if (this.ws !== ws) return;
        this.attempt = 0;
        this.handlers.onConnectionChange?.(true, 0);
        telemetryBus.publishSerial({ dir: 'sys', line: `[WS] 已连接 ${url}` });
        if (this.serialSubscribed) {
          this.send('subscribe', { serial_log: true });
        }
        this.startPing();
      };

      ws.onmessage = (evt) => {
        if (this.ws !== ws) return;
        if (typeof evt.data !== 'string') return;
        let env: WsEnvelope;
        try {
          env = JSON.parse(evt.data) as WsEnvelope;
        } catch {
          return;
        }
        this.dispatch(env);
      };

      ws.onerror = () => {
        if (this.ws !== ws) return;
        // onclose will handle reconnect
      };

      ws.onclose = () => {
        if (this.ws !== ws) return;
        this.clearPing();
        this.ws = null;
        if (this.intentionallyClosed) {
          this.handlers.onConnectionChange?.(false, 0);
          return;
        }
        this.attempt += 1;
        this.handlers.onConnectionChange?.(false, this.attempt);
        const delay = BACKOFF_MS[Math.min(this.attempt - 1, BACKOFF_MS.length - 1)];
        this.reconnectTimer = window.setTimeout(() => this.connect(), delay);
      };
    } catch {
      this.attempt += 1;
      this.handlers.onConnectionChange?.(false, this.attempt);
      const delay = BACKOFF_MS[Math.min(this.attempt - 1, BACKOFF_MS.length - 1)];
      this.reconnectTimer = window.setTimeout(() => this.connect(), delay);
    }
  }

  disconnect(): void {
    this.intentionallyClosed = true;
    this.clearTimers();
    const old = this.ws;
    this.ws = null;
    if (old) {
      old.onopen = null;
      old.onmessage = null;
      old.onerror = null;
      old.onclose = null;
      old.close();
    }
  }

  send(type: string, data: Record<string, unknown> = {}): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return false;
    }
    const payload = {
      v: 1,
      type,
      seq: this.seq++,
      ts: Date.now(),
      data,
    };
    try {
      this.ws.send(JSON.stringify(payload));
      return true;
    } catch {
      return false;
    }
  }

  setSerialLogSubscription(enabled: boolean): void {
    this.serialSubscribed = enabled;
    this.send('subscribe', { serial_log: enabled });
  }

  sendJog(dx: number, dy: number, feed: number): boolean {
    return this.send('jog', { dx, dy, feed });
  }

  sendJogCancel(): boolean {
    return this.send('jog.cancel', {});
  }

  sendEstop(): boolean {
    return this.send('estop', {});
  }

  private dispatch(env: WsEnvelope): void {
    switch (env.type) {
      case 'machine.status': {
        const status = env.data as MachineStatusData;
        // 1. Always push to zero-rerender transient bus (10Hz)
        telemetryBus.publishStatus(status);
        // 2. Only notify React Zustand store when low-frequency discrete state changes
        const key = `${status.machine_state}|${status.job_state ?? ''}|${status.grbl_state}|${status.pen}|${status.mock}|${status.alarm_code ?? ''}`;
        if (key !== this.lastDiscreteKey) {
          this.lastDiscreteKey = key;
          this.handlers.onMachineDiscreteChange?.(status);
        }
        break;
      }
      case 'job.progress': {
        const progress = env.data as JobProgressData;
        telemetryBus.publishProgress(progress);
        const key = `${progress.job_id}|${progress.job_state}|${progress.page_index}|${progress.page_count}`;
        if (key !== this.lastJobPageKey) {
          this.lastJobPageKey = key;
          this.handlers.onJobProgressDiscrete?.(progress);
        }
        break;
      }
      case 'job.event': {
        const ev = env.data as JobEventData;
        telemetryBus.publishSerial({
          dir: 'sys',
          line: `[JOB ${ev.job_id}] ${ev.event} (P${ev.page_index + 1}): ${ev.message}`,
        });
        this.handlers.onJobEvent?.(ev);
        break;
      }
      case 'task.progress': {
        this.handlers.onTaskProgress?.(env.data as TaskProgressData);
        break;
      }
      case 'writer.changed': {
        const d = env.data as { writer_id?: string };
        if (d.writer_id) {
          this.handlers.onWriterChanged?.(d.writer_id);
        }
        break;
      }
      case 'alarm': {
        const alarm = env.data as AlarmEventData;
        telemetryBus.publishSerial({
          dir: 'sys',
          line: `[ALARM ${alarm.code}] ${alarm.message}`,
        });
        this.handlers.onAlarm?.(alarm);
        break;
      }
      case 'serial.log': {
        telemetryBus.publishSerial(env.data as SerialLogData, env.ts || Date.now());
        break;
      }
      case 'pong':
      default:
        break;
    }
  }

  private startPing(): void {
    this.clearPing();
    this.pingTimer = window.setInterval(() => {
      this.send('ping', {});
    }, 15000);
  }

  private clearPing(): void {
    if (this.pingTimer !== null) {
      window.clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  private clearTimers(): void {
    this.clearPing();
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }
}

export const telemetrySocket = new TelemetrySocket();
