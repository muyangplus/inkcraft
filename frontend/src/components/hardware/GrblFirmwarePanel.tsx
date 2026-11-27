import React, { useState } from 'react';
import { Cpu, RefreshCw, Save } from 'lucide-react';
import { restClient } from '../../api/restClient';
import type { GrblSettingsResponse } from '../../api/types';
import { useMachineStore } from '../../stores/useMachineStore';
import { useViewportStore } from '../../stores/useViewportStore';

/**
 * GRBL 固件参数（$$）读取与写入。写入的值保存在控制板 EEPROM 中，对所有上位机软件生效。
 */
export const GrblFirmwarePanel: React.FC = () => {
  const machineState = useMachineStore((s) => s.machineState);
  const pushToast = useViewportStore((s) => s.pushToast);
  const [data, setData] = useState<GrblSettingsResponse | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const connected = machineState === 'IDLE' || machineState === 'ALARM';

  const load = async () => {
    setBusy(true);
    try {
      setData(await restClient.getGrblSettings());
      setEdits({});
    } catch (err) {
      pushToast(`读取固件参数失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    } finally {
      setBusy(false);
    }
  };

  const changed = Object.entries(edits).filter(([key, text]) => {
    const orig = data?.settings.find((s) => s.key === key)?.value;
    return text.trim() !== '' && Number.isFinite(Number(text)) && Number(text) !== orig;
  });

  const save = async () => {
    if (!changed.length) return;
    if (!window.confirm(`确认写入 ${changed.length} 项固件参数到控制板？\n${changed.map(([k, v]) => `${k}=${v}`).join('\n')}`)) {
      return;
    }
    setBusy(true);
    try {
      const res = await restClient.writeGrblSettings(
        Object.fromEntries(changed.map(([k, v]) => [k, Number(v)])),
      );
      pushToast(`已写入：${res.written.join(' ')}`, 'success');
      await load();
    } catch (err) {
      pushToast(`写入固件参数失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div className="row-between" style={{ marginBottom: 4 }}>
        <span className="ctrl-label">
          <Cpu size={11} /> GRBL 固件参数 ($$)
          {data?.grbl_version ? ` · Grbl ${data.grbl_version}` : ''}
          {data?.report_inches ? ' · 以英寸上报（已自动换算）' : ''}
        </span>
        <div className="row-gap" style={{ gap: 5 }}>
          <button type="button" className="btn btn-xs" disabled={!connected || busy} onClick={() => void load()}>
            <RefreshCw size={11} /> 读取
          </button>
          <button
            type="button"
            className="btn btn-xs btn-primary"
            disabled={!connected || busy || changed.length === 0}
            onClick={() => void save()}
          >
            <Save size={11} /> 写入{changed.length ? ` (${changed.length})` : ''}
          </button>
        </div>
      </div>
      {!connected && !data && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>连接写字机并处于空闲状态后可读取 / 修改固件参数。</div>
      )}
      {data?.warnings.map((w) => (
        <div key={w.code + w.message} style={{ fontSize: 11, color: 'var(--state-warn)' }}>
          ⚠ {w.message}
        </div>
      ))}
      {data && (
        <div style={{ maxHeight: 180, overflowY: 'auto', display: 'grid', gridTemplateColumns: '52px minmax(0,1fr) 86px', gap: '3px 6px', fontSize: 11.5 }}>
          {data.settings.map((s) => (
            <React.Fragment key={s.key}>
              <span className="mono">{s.key}</span>
              <span style={{ color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {s.name}
              </span>
              <input
                className="mono"
                style={{ padding: '1px 4px' }}
                value={edits[s.key] ?? String(s.value)}
                onChange={(e) => setEdits({ ...edits, [s.key]: e.target.value })}
              />
            </React.Fragment>
          ))}
        </div>
      )}
    </div>
  );
};
