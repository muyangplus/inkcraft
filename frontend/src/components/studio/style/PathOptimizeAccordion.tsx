import React, { useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, Gauge } from 'lucide-react';
import { DEFAULT_LAYOUT_CONFIG } from '../../../api/types';
import { useDocumentLayoutStore } from '../../../stores/useDocumentLayoutStore';

export const PathOptimizeAccordion: React.FC = () => {
  const [open, setOpen] = useState(false);
  const config = useDocumentLayoutStore((s) => s.config);
  const updateConfig = useDocumentLayoutStore((s) => s.updateConfig);

  const modifiedCount = useMemo(() => {
    const o = config.optimize;
    const d = DEFAULT_LAYOUT_CONFIG.optimize;
    let count = 0;
    if (o.travel !== d.travel) count += 1;
    if (Math.abs(o.simplify_tol_mm - d.simplify_tol_mm) > 1e-4) count += 1;
    if (Math.abs(o.join_tol_mm - d.join_tol_mm) > 1e-4) count += 1;
    return count;
  }, [config.optimize]);

  return (
    <div className="section-card">
      <button
        type="button"
        className="accordion-header"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="section-head-title">
          <Gauge size={13} style={{ color: 'var(--accent-primary)' }} />
          路径优化与机械臂提速
          {modifiedCount > 0 && <span className="accordion-count-badge">{modifiedCount} 项调整</span>}
        </span>
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </button>

      {open && (
        <div className="accordion-body">
          <div className="mini-field">
            <span>抬笔空移优化算法</span>
            <select
              value={config.optimize.travel}
              onChange={(e) =>
                updateConfig(
                  (p) => ({
                    ...p,
                    optimize: {
                      ...p.optimize,
                      travel: e.target.value as 'greedy_2opt' | 'none',
                    },
                  }),
                  true,
                )
              }
            >
              <option value="greedy_2opt">Greedy + 2-Opt 减空移（推荐）</option>
              <option value="none">关闭空移重排（按书写顺序）</option>
            </select>
          </div>

          <div className="grid-2">
            <div className="mini-field">
              <span>路径抽稀容差 (mm)</span>
              <input
                type="number"
                className="mono"
                min={0.02}
                max={0.5}
                step={0.02}
                value={config.optimize.simplify_tol_mm}
                onChange={(e) =>
                  updateConfig((p) => ({
                    ...p,
                    optimize: {
                      ...p.optimize,
                      simplify_tol_mm: Math.max(0.02, Math.min(0.5, Number(e.target.value) || 0.08)),
                    },
                  }))
                }
              />
            </div>
            <div className="mini-field">
              <span>近邻连笔容差 (mm)</span>
              <input
                type="number"
                className="mono"
                min={0}
                max={1.0}
                step={0.05}
                value={config.optimize.join_tol_mm}
                onChange={(e) =>
                  updateConfig((p) => ({
                    ...p,
                    optimize: {
                      ...p.optimize,
                      join_tol_mm: Math.max(0, Math.min(1.0, Number(e.target.value) || 0.15)),
                    },
                  }))
                }
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
