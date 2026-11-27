import type { JobProgressData, MachineStatusData, SerialLogData } from '../api/types';

export interface SerialLogEntry {
  id: number;
  ts: number;
  dir: 'tx' | 'rx' | 'sys';
  line: string;
}

type StatusListener = (status: MachineStatusData) => void;
type ProgressListener = (progress: JobProgressData | null) => void;
type SerialListener = (entry: SerialLogEntry) => void;

const SERIAL_RING_CAPACITY = 500;

/**
 * Transient pub-sub channel that bypasses React rendering for 10Hz machine status,
 * 5Hz job progress, and high-frequency GRBL serial logs.
 */
class TelemetryBus {
  private statusListeners = new Set<StatusListener>();
  private progressListeners = new Set<ProgressListener>();
  private serialListeners = new Set<SerialListener>();

  private serialRing: SerialLogEntry[] = [];
  private nextLogId = 1;

  public latestStatus: MachineStatusData = {
    machine_state: 'DISCONNECTED',
    job_state: null,
    grbl_state: 'Idle',
    mpos: { x: 0, y: 0, z: 0 },
    wpos: { x: 0, y: 0, z: 0 },
    feed: 0,
    pen: 'up',
    buf: { planner: 15, rx: 128 },
    alarm_code: null,
    mock: true,
  };

  public latestProgress: JobProgressData | null = null;

  publishStatus(status: MachineStatusData): void {
    this.latestStatus = status;
    for (const fn of this.statusListeners) {
      fn(status);
    }
  }

  publishProgress(progress: JobProgressData | null): void {
    this.latestProgress = progress;
    for (const fn of this.progressListeners) {
      fn(progress);
    }
  }

  publishSerial(data: SerialLogData | { dir: 'sys'; line: string }, ts = Date.now()): void {
    const entry: SerialLogEntry = {
      id: this.nextLogId++,
      ts,
      dir: data.dir,
      line: data.line,
    };
    this.serialRing.push(entry);
    if (this.serialRing.length > SERIAL_RING_CAPACITY) {
      this.serialRing.shift();
    }
    for (const fn of this.serialListeners) {
      fn(entry);
    }
  }

  getSerialLogs(): readonly SerialLogEntry[] {
    return this.serialRing;
  }

  clearSerialLogs(): void {
    this.serialRing = [];
  }

  subscribeStatus(listener: StatusListener): () => void {
    this.statusListeners.add(listener);
    listener(this.latestStatus);
    return () => {
      this.statusListeners.delete(listener);
    };
  }

  subscribeProgress(listener: ProgressListener): () => void {
    this.progressListeners.add(listener);
    listener(this.latestProgress);
    return () => {
      this.progressListeners.delete(listener);
    };
  }

  subscribeSerial(listener: SerialListener): () => void {
    this.serialListeners.add(listener);
    return () => {
      this.serialListeners.delete(listener);
    };
  }
}

export const telemetryBus = new TelemetryBus();
