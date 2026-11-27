import React, { useEffect, useRef } from 'react';
import { telemetryBus } from '../../stores/telemetryBus';
import { useMachineStore } from '../../stores/useMachineStore';

function padCoord(val: number): string {
  const sign = val < 0 ? '-' : '';
  return sign + Math.abs(val).toFixed(2).padStart(6, '0');
}

/**
 * Digital Readout (DRO) Telemetry Card.
 * Subscribes directly to `telemetryBus` and updates DOM refs at 10Hz with ZERO React re-renders.
 */
export const DroTelemetryCard: React.FC = () => {
  const pen = useMachineStore((s) => s.pen);

  const wxRef = useRef<HTMLSpanElement>(null);
  const wyRef = useRef<HTMLSpanElement>(null);
  const mxRef = useRef<HTMLSpanElement>(null);
  const myRef = useRef<HTMLSpanElement>(null);
  const feedRef = useRef<HTMLSpanElement>(null);
  const plannerBarRef = useRef<HTMLDivElement>(null);
  const plannerTxtRef = useRef<HTMLSpanElement>(null);
  const rxBarRef = useRef<HTMLDivElement>(null);
  const rxTxtRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const unsub = telemetryBus.subscribeStatus((st) => {
      if (wxRef.current) wxRef.current.textContent = padCoord(st.wpos.x);
      if (wyRef.current) wyRef.current.textContent = padCoord(st.wpos.y);
      if (mxRef.current) mxRef.current.textContent = `MPos ${padCoord(st.mpos.x)}`;
      if (myRef.current) myRef.current.textContent = `MPos ${padCoord(st.mpos.y)}`;
      if (feedRef.current) feedRef.current.textContent = `${Math.round(st.feed)} mm/min`;

      const plannerPct = Math.max(0, Math.min(100, (st.buf.planner / 15) * 100));
      if (plannerBarRef.current) {
        plannerBarRef.current.style.width = `${plannerPct}%`;
        plannerBarRef.current.style.background =
          plannerPct < 25 ? 'var(--state-warn)' : 'var(--state-ready)';
      }
      if (plannerTxtRef.current) plannerTxtRef.current.textContent = `${st.buf.planner}/15`;

      const rxPct = Math.max(0, Math.min(100, (st.buf.rx / 128) * 100));
      if (rxBarRef.current) {
        rxBarRef.current.style.width = `${rxPct}%`;
        rxBarRef.current.style.background =
          rxPct < 25 ? 'var(--state-warn)' : 'var(--accent-primary)';
      }
      if (rxTxtRef.current) rxTxtRef.current.textContent = `${st.buf.rx}B`;
    });
    return unsub;
  }, []);

  return (
    <div className="section-card">
      <div className="section-head">
        <span>实时位置 (DRO)</span>
        <span
          className="mono"
          style={{
            color: pen === 'down' ? 'var(--accent-primary)' : 'var(--state-ready)',
            fontWeight: 700,
            fontSize: 11,
          }}
        >
          {pen === 'down' ? '↓ 落笔' : '↑ 抬笔'}
        </span>
      </div>

      <div className="dro-grid mono">
        <div className="dro-axis">
          <span className="dro-lbl">WPos X (mm)</span>
          <span className="dro-num" ref={wxRef}>
            000.00
          </span>
          <span className="dro-sub" ref={mxRef}>
            MPos 000.00
          </span>
        </div>
        <div className="dro-axis">
          <span className="dro-lbl">WPos Y (mm)</span>
          <span className="dro-num" ref={wyRef}>
            000.00
          </span>
          <span className="dro-sub" ref={myRef}>
            MPos 000.00
          </span>
        </div>
      </div>

      <div className="row-between mono" style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
        <span>当前进给 Feed</span>
        <span ref={feedRef} style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
          0 mm/min
        </span>
      </div>

      <div className="buf-row mono">
        <span>Planner</span>
        <div className="bar-track">
          <div
            ref={plannerBarRef}
            className="bar-fill"
            style={{ width: '100%', background: 'var(--state-ready)' }}
          />
        </div>
        <span ref={plannerTxtRef} style={{ textAlign: 'right' }}>
          15/15
        </span>
      </div>

      <div className="buf-row mono">
        <span>RX Buf</span>
        <div className="bar-track">
          <div
            ref={rxBarRef}
            className="bar-fill"
            style={{ width: '100%', background: 'var(--accent-primary)' }}
          />
        </div>
        <span ref={rxTxtRef} style={{ textAlign: 'right' }}>
          128B
        </span>
      </div>
    </div>
  );
};
