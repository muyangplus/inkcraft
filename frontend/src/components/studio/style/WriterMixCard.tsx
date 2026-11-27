import React from 'react';
import { Shuffle } from 'lucide-react';
import { useDocumentLayoutStore } from '../../../stores/useDocumentLayoutStore';
import { useWriterStore } from '../../../stores/useWriterStore';

/**
 * 多字体按概率混写（对应奎享雕刻稿纸设置里的「字体 + 概率」）。
 * 勾选两位及以上书写者后，正文每个字按权重随机选用其中一位的笔迹。
 */
export const WriterMixCard: React.FC = () => {
  const writers = useWriterStore((s) => s.writers);
  const config = useDocumentLayoutStore((s) => s.config);
  const updateConfig = useDocumentLayoutStore((s) => s.updateConfig);
  const mix = config.writer_mix ?? [];

  const weightOf = (id: string) => mix.find((m) => m.writer_id === id)?.weight;

  const setWeight = (id: string, weight: number | null) => {
    updateConfig((p) => {
      const rest = (p.writer_mix ?? []).filter((m) => m.writer_id !== id);
      const next = weight === null ? rest : [...rest, { writer_id: id, weight }];
      return { ...p, preset_id: null, writer_mix: next };
    }, true);
  };

  const total = mix.reduce((acc, m) => acc + m.weight, 0);
  const active = mix.filter((m) => m.weight > 0).length;

  return (
    <div className="section-card">
      <div className="section-head">
        <span className="section-head-title">
          <Shuffle size={13} style={{ color: 'var(--accent-primary)' }} />
          多字体混写
        </span>
        {mix.length > 0 && (
          <button
            type="button"
            className="btn btn-xs"
            onClick={() => updateConfig((p) => ({ ...p, preset_id: null, writer_mix: [] }), true)}
          >
            清空
          </button>
        )}
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
        勾选 2 位以上书写者后，每个字按比例随机选用其中一位的笔迹（类似奎享「字体概率」）。
        {active === 1 && ' 当前仅 1 位，混写未生效。'}
      </div>
      {writers.map((w) => {
        const wt = weightOf(w.writer_id);
        const on = wt !== undefined;
        return (
          <div
            key={w.writer_id}
            style={{ display: 'grid', gridTemplateColumns: 'auto minmax(0,1fr) 64px 40px', gap: 6, alignItems: 'center' }}
          >
            <input
              type="checkbox"
              checked={on}
              onChange={(e) => setWeight(w.writer_id, e.target.checked ? 50 : null)}
            />
            <span style={{ fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {w.writer_name}
              {w.writer_alias ? ` · ${w.writer_alias}` : ''}
            </span>
            <input
              type="number"
              className="mono"
              min={0}
              max={1000}
              disabled={!on}
              value={on ? wt : ''}
              onChange={(e) => setWeight(w.writer_id, Math.max(0, Number(e.target.value) || 0))}
            />
            <span className="mono" style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>
              {on && total > 0 ? `${Math.round(((wt ?? 0) / total) * 100)}%` : ''}
            </span>
          </div>
        );
      })}
    </div>
  );
};
