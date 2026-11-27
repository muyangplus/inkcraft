import React from 'react';
import { Dices, RotateCcw, Sparkles } from 'lucide-react';
import { DEFAULT_LAYOUT_CONFIG } from '../../../api/types';
import { useDocumentLayoutStore } from '../../../stores/useDocumentLayoutStore';

function neatnessDescriptor(n: number): { label: string; color: string } {
  if (n >= 0.85) return { label: '一笔一画 · 工整规范', color: 'var(--accent-primary)' };
  if (n >= 0.65) return { label: '自然清晰 · 常规手写', color: 'var(--state-ready)' };
  if (n >= 0.4) return { label: '流畅行楷 · 轻度连笔', color: '#0284C7' };
  if (n >= 0.2) return { label: '飘逸行书 · 牵丝连笔', color: 'var(--state-warn)' };
  return { label: '速记潦草 · 放逸连写', color: 'var(--state-danger)' };
}

const NEATNESS_CHIPS = [
  { label: '工整', value: 0.95 },
  { label: '自然', value: 0.72 },
  { label: '行书', value: 0.4 },
  { label: '潦草', value: 0.12 },
];

export const NeatnessMasterCard: React.FC = () => {
  const config = useDocumentLayoutStore((s) => s.config);
  const updateConfig = useDocumentLayoutStore((s) => s.updateConfig);
  const neatness = typeof config.perturb.neatness === 'number' ? config.perturb.neatness : 0.72;
  const neatInfo = neatnessDescriptor(neatness);

  const rollSeed = () => {
    const next = Math.floor(Math.random() * 99999) + 1;
    updateConfig((p) => ({ ...p, preset_id: null, perturb: { ...p.perturb, seed: next } }), true);
  };

  const resetPerturb = () => {
    updateConfig(
      (p) => ({
        ...p,
        preset_id: null,
        perturb: { ...DEFAULT_LAYOUT_CONFIG.perturb },
      }),
      true,
    );
  };

  return (
    <div className="section-card">
      <div className="section-head">
        <span className="section-head-title">
          <Sparkles size={13} style={{ color: 'var(--accent-primary)' }} />
          手写工整度与随机种子
        </span>
        <div className="row-gap" style={{ gap: 5 }}>
          <input
            type="number"
            className="mono"
            style={{ width: 64, padding: '3px 6px', fontSize: 11 }}
            min={0}
            max={4294967295}
            value={config.perturb.seed}
            onChange={(e) =>
              updateConfig((p) => ({
                ...p,
                preset_id: null,
                perturb: { ...p.perturb, seed: Math.max(0, Number(e.target.value) || 0) },
              }))
            }
            title="确定性随机种子 (PCG64)"
          />
          <button type="button" className="btn btn-xs" onClick={rollSeed} title="随机生成新种子">
            <Dices size={12} />
          </button>
          <button type="button" className="btn btn-xs" onClick={resetPerturb} title="恢复默认微扰参数">
            <RotateCcw size={11} />
          </button>
        </div>
      </div>

      <div
        style={{
          background: 'var(--bg-subtle)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 10,
          padding: '10px 10px 9px',
          display: 'flex',
          flexDirection: 'column',
          gap: 7,
        }}
      >
        <div className="row-between">
          <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)' }}>
            书写工整度
          </span>
          <span className="mono" style={{ fontSize: 11.5, fontWeight: 700, color: neatInfo.color }}>
            {Math.round(neatness * 100)}% · {neatInfo.label}
          </span>
        </div>
        <input
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={neatness}
          onChange={(e) =>
            updateConfig((p) => ({
              ...p,
              preset_id: null,
              perturb: { ...p.perturb, neatness: Number(e.target.value) },
            }))
          }
        />
        <div className="row-between" style={{ gap: 5 }}>
          {NEATNESS_CHIPS.map((c) => (
            <button
              key={c.label}
              type="button"
              className={`btn btn-xs ${Math.abs(neatness - c.value) < 0.06 ? 'btn-primary' : ''}`}
              style={{ flex: 1, justifyContent: 'center' }}
              onClick={() =>
                updateConfig(
                  (p) => ({
                    ...p,
                    preset_id: null,
                    perturb: { ...p.perturb, neatness: c.value },
                  }),
                  true,
                )
              }
            >
              {c.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};
