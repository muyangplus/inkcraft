import React, { useEffect, useRef, useState } from 'react';
import { ChevronDown, Copy, Pause, Play, Send, Terminal, Trash2 } from 'lucide-react';
import { telemetrySocket } from '../../api/telemetrySocket';
import type { JobProgressData } from '../../api/types';
import { telemetryBus, type SerialLogEntry } from '../../stores/telemetryBus';
import { useDocumentLayoutStore } from '../../stores/useDocumentLayoutStore';
import { useMachineStore } from '../../stores/useMachineStore';
import { useViewportStore } from '../../stores/useViewportStore';

function formatDuration(sec: number): string {
  const s = Math.max(0, Math.round(sec));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`;
}

function formatTime(ts: number): string {
  const d = new Date(ts);
  return d.toTimeString().slice(0, 8);
}

export const BottomTransportBar: React.FC = () => {
  const layout = useDocumentLayoutStore((s) => s.layout);
  const currentPageIndex = useDocumentLayoutStore((s) => s.currentPageIndex);
  const activePaths = useDocumentLayoutStore((s) => s.activePagePaths);

  const machineState = useMachineStore((s) => s.machineState);
  const jobState = useMachineStore((s) => s.jobState);
  const sendRawCommand = useMachineStore((s) => s.sendRawCommand);
  const busyAction = useMachineStore((s) => s.busyAction);

  const playbackProgress = useViewportStore((s) => s.playbackProgress);
  const isPlayingPreview = useViewportStore((s) => s.isPlayingPreview);
  const playbackSpeed = useViewportStore((s) => s.playbackSpeed);
  const serialDrawerOpen = useViewportStore((s) => s.serialDrawerOpen);
  const setPlaybackProgress = useViewportStore((s) => s.setPlaybackProgress);
  const setIsPlayingPreview = useViewportStore((s) => s.setIsPlayingPreview);
  const setPlaybackSpeed = useViewportStore((s) => s.setPlaybackSpeed);
  const setSerialDrawerOpen = useViewportStore((s) => s.setSerialDrawerOpen);
  const pushToast = useViewportStore((s) => s.pushToast);

  const [filterPolling, setFilterPolling] = useState(true);
  const [logs, setLogs] = useState<SerialLogEntry[]>([]);
  const [serialCmd, setSerialCmd] = useState('');
  const logBodyRef = useRef<HTMLDivElement>(null);

  const canSendRaw =
    machineState === 'IDLE' ||
    machineState === 'PAUSED' ||
    machineState === 'PEN_CHANGE' ||
    machineState === 'PAPER_CHANGE' ||
    machineState === 'ALARM' ||
    machineState === 'ESTOPPED';

  const isLiveJob =
    machineState === 'RUNNING' ||
    machineState === 'HOLDING' ||
    machineState === 'PAUSED' ||
    machineState === 'PEN_CHANGE' ||
    machineState === 'PAPER_CHANGE';

  const [liveProgress, setLiveProgress] = useState<JobProgressData | null>(() =>
    telemetryBus.latestProgress,
  );

  const pageSummary = layout?.pages[currentPageIndex];
  const totalStrokes = activePaths?.strokeCount ?? pageSummary?.stats.stroke_count ?? 0;

  // Subscribe to serial logs only when drawer is open (100ms throttled refresh)
  useEffect(() => {
    telemetrySocket.setSerialLogSubscription(serialDrawerOpen);
    if (!serialDrawerOpen) return;

    setLogs([...telemetryBus.getSerialLogs()]);
    let dirty = false;
    const unsub = telemetryBus.subscribeSerial(() => {
      dirty = true;
    });
    const timer = window.setInterval(() => {
      if (dirty) {
        dirty = false;
        setLogs([...telemetryBus.getSerialLogs()]);
      }
    }, 100);
    return () => {
      unsub();
      window.clearInterval(timer);
    };
  }, [serialDrawerOpen]);

  useEffect(() => {
    if (serialDrawerOpen && logBodyRef.current) {
      logBodyRef.current.scrollTop = logBodyRef.current.scrollHeight;
    }
  }, [logs, serialDrawerOpen]);

  // React state sync for 5Hz live job progress (prevents React re-renders wiping values)
  useEffect(() => {
    if (!isLiveJob) {
      setLiveProgress(null);
      return;
    }
    setLiveProgress(telemetryBus.latestProgress);
    return telemetryBus.subscribeProgress((prog) => {
      setLiveProgress(prog);
    });
  }, [isLiveJob]);

  // Idle playback scrubber animation
  useEffect(() => {
    if (!isPlayingPreview || isLiveJob) return;
    let lastTs = performance.now();
    let rafId = 0;

    const step = (now: number) => {
      const dt = Math.min(0.1, (now - lastTs) / 1000);
      lastTs = now;
      const cur = useViewportStore.getState().playbackProgress;
      const speed = useViewportStore.getState().playbackSpeed;
      const durationSec = Math.max(4, (pageSummary?.stats.est_s || 24) / speed);
      const next = cur >= 1 ? 0 : cur + dt / durationSec;
      if (next >= 1) {
        setPlaybackProgress(1);
        setIsPlayingPreview(false);
        return;
      }
      setPlaybackProgress(next);
      rafId = requestAnimationFrame(step);
    };

    if (useViewportStore.getState().playbackProgress >= 0.999) {
      setPlaybackProgress(0);
    }
    rafId = requestAnimationFrame(step);
    return () => cancelAnimationFrame(rafId);
  }, [isPlayingPreview, isLiveJob, pageSummary?.stats.est_s, setPlaybackProgress, setIsPlayingPreview]);

  const filteredLogs = filterPolling
    ? logs.filter((l) => l.line.trim() !== '?' && !l.line.startsWith('<'))
    : logs;

  const shownStrokes = Math.round(playbackProgress * totalStrokes);
  const drawM = ((pageSummary?.stats.draw_mm ?? 0) / 1000).toFixed(2);
  const travelM = ((pageSummary?.stats.travel_mm ?? 0) / 1000).toFixed(2);
  const estStr = formatDuration(pageSummary?.stats.est_s ?? 0);

  return (
    <div className="bottom-area">
      {serialDrawerOpen && (
        <div className="serial-drawer">
          <div className="serial-head">
            <div className="row-gap">
              <Terminal size={12} />
              <span className="mono">GRBL 串口实时日志 (/ws/telemetry · serial.log · 环形缓存 500 条)</span>
            </div>
            <div className="row-gap">
              <label className="row-gap" style={{ cursor: 'pointer', fontSize: 11 }}>
                <input
                  type="checkbox"
                  checked={filterPolling}
                  onChange={(e) => setFilterPolling(e.target.checked)}
                />
                过滤 `?` 状态心跳
              </label>
              <button
                className="btn btn-xs"
                onClick={() => {
                  const text = filteredLogs
                    .map((l) => `[${formatTime(l.ts)}] ${l.dir.toUpperCase()} ${l.line}`)
                    .join('\n');
                  void navigator.clipboard?.writeText(text);
                  pushToast('已复制串口日志到剪贴板', 'info');
                }}
              >
                <Copy size={11} /> 复制
              </button>
              <button
                className="btn btn-xs"
                onClick={() => {
                  telemetryBus.clearSerialLogs();
                  setLogs([]);
                }}
              >
                <Trash2 size={11} /> 清空
              </button>
              <button className="btn btn-xs" onClick={() => setSerialDrawerOpen(false)}>
                <ChevronDown size={12} /> 收起
              </button>
            </div>
          </div>
          <div className="serial-body mono" ref={logBodyRef}>
            {filteredLogs.length === 0 ? (
              <div style={{ color: '#64748B' }}>暂无串口通信日志。连接机台或执行点动/书写后将实时流式输出…</div>
            ) : (
              filteredLogs.map((l) => {
                const cls =
                  l.line.includes('ALARM') || l.line.includes('error') || l.line.includes('estop')
                    ? 'log-err'
                    : l.dir === 'tx'
                      ? 'log-tx'
                      : l.dir === 'rx'
                        ? 'log-rx'
                        : 'log-warn';
                return (
                  <div key={l.id} className={cls}>
                    <span style={{ color: '#475569', marginRight: 8 }}>{formatTime(l.ts)}</span>
                    <span style={{ opacity: 0.75, marginRight: 6 }}>{l.dir.toUpperCase()}</span>
                    <span>{l.line}</span>
                  </div>
                );
              })
            )}
          </div>
          <div className="serial-cmd-bar">
            <input
              type="text"
              className="mono"
              placeholder={
                canSendRaw
                  ? '输入 GRBL / G-code 指令回车发送，如 $$、$H、G92 X0 Y0、G0 X0 Y0'
                  : '请先连接 GRBL 机台后发送指令'
              }
              disabled={!canSendRaw}
              value={serialCmd}
              onChange={(e) => setSerialCmd(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && serialCmd.trim() && canSendRaw) {
                  e.preventDefault();
                  const cmd = serialCmd.trim();
                  setSerialCmd('');
                  void sendRawCommand(cmd);
                }
              }}
            />
            <button
              type="button"
              className="btn btn-xs btn-primary"
              disabled={!canSendRaw || !serialCmd.trim() || busyAction === 'rawCmd'}
              onClick={() => {
                const cmd = serialCmd.trim();
                if (!cmd) return;
                setSerialCmd('');
                void sendRawCommand(cmd);
              }}
            >
              <Send size={11} /> 发送
            </button>
          </div>
        </div>
      )}

      <footer className="transport-bar">
        {!isLiveJob ? (
          <>
            <button
              className="btn btn-sm"
              style={{ minWidth: 88 }}
              disabled={totalStrokes === 0}
              onClick={() => setIsPlayingPreview(!isPlayingPreview)}
              title="播放 / 暂停单线落笔顺序预演 (K)"
            >
              {isPlayingPreview ? <Pause size={12} /> : <Play size={12} />}
              {isPlayingPreview ? '暂停预演' : '轨迹预演'}
            </button>

            <select
              className="mono"
              style={{ width: 62, padding: '3px 5px', fontSize: 11.5 }}
              value={playbackSpeed}
              onChange={(e) => setPlaybackSpeed(Number(e.target.value) as 1 | 4 | 16)}
            >
              <option value={1}>1×</option>
              <option value={4}>4×</option>
              <option value={16}>16×</option>
            </select>

            <div className="scrubber-wrap">
              <input
                type="range"
                min={0}
                max={1000}
                value={Math.round(playbackProgress * 1000)}
                onChange={(e) => {
                  setIsPlayingPreview(false);
                  setPlaybackProgress(Number(e.target.value) / 1000);
                }}
              />
            </div>
          </>
        ) : (
          <div className="scrubber-wrap">
            <span
              className="mono"
              style={{
                fontSize: 11,
                fontWeight: 700,
                color: 'var(--accent-primary)',
                whiteSpace: 'nowrap',
              }}
            >
              {jobState ?? 'STREAMING'}
            </span>
            <div className="bar-track" style={{ flex: 1, height: 7 }}>
              <div
                className="bar-fill"
                style={{
                  width: `${Math.max(0, Math.min(100, liveProgress?.pct ?? 0))}%`,
                  background: 'var(--accent-primary)',
                }}
              />
            </div>
          </div>
        )}

        <div className="stats-group mono">
          <span>
            笔画{' '}
            <strong>
              {isLiveJob && liveProgress
                ? `${liveProgress.stroke_index}/${liveProgress.stroke_total}`
                : `${shownStrokes}/${totalStrokes}`}
            </strong>
          </span>
          <span>
            实绘{' '}
            <strong>
              {isLiveJob && liveProgress ? (liveProgress.draw_mm / 1000).toFixed(2) : drawM}m
            </strong>
          </span>
          <span>
            空移{' '}
            <strong>
              {isLiveJob && liveProgress ? (liveProgress.travel_mm / 1000).toFixed(2) : travelM}m
            </strong>
          </span>
          <span>
            {isLiveJob ? '剩余 ' : '预计 '}
            <strong>
              {isLiveJob && liveProgress ? formatDuration(liveProgress.eta_s) : estStr}
            </strong>
          </span>
        </div>

        <button
          className={`btn btn-sm mono ${serialDrawerOpen ? 'btn-primary' : ''}`}
          onClick={() => setSerialDrawerOpen(!serialDrawerOpen)}
        >
          <Terminal size={12} /> 串口日志
        </button>
      </footer>
    </div>
  );
};
