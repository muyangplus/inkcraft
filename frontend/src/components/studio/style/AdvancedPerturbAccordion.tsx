import React, { useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, Sliders } from 'lucide-react';
import { DEFAULT_LAYOUT_CONFIG } from '../../../api/types';
import { useDocumentLayoutStore } from '../../../stores/useDocumentLayoutStore';

export const AdvancedPerturbAccordion: React.FC = () => {
  const [open, setOpen] = useState(false);
  const config = useDocumentLayoutStore((s) => s.config);
  const updateConfig = useDocumentLayoutStore((s) => s.updateConfig);

  const modifiedCount = useMemo(() => {
    const p = config.perturb;
    const d = DEFAULT_LAYOUT_CONFIG.perturb;
    let count = 0;
    if (Math.abs(p.scale_jitter - d.scale_jitter) > 1e-4) count += 1;
    if (Math.abs(p.slant_deg - d.slant_deg) > 1e-4) count += 1;
    if (Math.abs(p.baseline_wave_amp_mm - d.baseline_wave_amp_mm) > 1e-4) count += 1;
    if (Math.abs(p.baseline_wave_period_mm - d.baseline_wave_period_mm) > 1e-4) count += 1;
    if (Math.abs(p.spacing_jitter - d.spacing_jitter) > 1e-4) count += 1;
    if (Math.abs(p.rotation_jitter_deg - d.rotation_jitter_deg) > 1e-4) count += 1;
    if (p.variant_strategy !== d.variant_strategy) count += 1;
    if (p.variant_no_repeat_window !== d.variant_no_repeat_window) count += 1;
    return count;
  }, [config.perturb]);

  return (
    <div className="section-card">
      <button
        type="button"
        className="accordion-header"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="section-head-title">
          <Sliders size={13} style={{ color: 'var(--accent-primary)' }} />
          手写微扰细节（倾斜 / 抖动 / 异形）
          {modifiedCount > 0 && <span className="accordion-count-badge">{modifiedCount} 项调整</span>}
        </span>
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </button>

      {open && (
        <div className="accordion-body">
          <div className="ctrl-row">
            <div className="ctrl-label">
              <span>字号大小抖动 (scale_jitter)</span>
              <span className="ctrl-val mono">{config.perturb.scale_jitter.toFixed(2)}</span>
            </div>
            <input
              type="range"
              min={0}
              max={0.3}
              step={0.01}
              value={config.perturb.scale_jitter}
              onChange={(e) =>
                updateConfig((p) => ({
                  ...p,
                  preset_id: null,
                  perturb: { ...p.perturb, scale_jitter: Number(e.target.value) },
                }))
              }
            />
          </div>

          <div className="ctrl-row">
            <div className="ctrl-label">
              <span>手写倾角 (slant_deg)</span>
              <span className="ctrl-val mono">{config.perturb.slant_deg.toFixed(1)}°</span>
            </div>
            <input
              type="range"
              min={0}
              max={8}
              step={0.2}
              value={config.perturb.slant_deg}
              onChange={(e) =>
                updateConfig((p) => ({
                  ...p,
                  preset_id: null,
                  perturb: { ...p.perturb, slant_deg: Number(e.target.value) },
                }))
              }
            />
          </div>

          <div className="ctrl-row">
            <div className="ctrl-label">
              <span>基线波浪振幅 (baseline_wave)</span>
              <span className="ctrl-val mono">{config.perturb.baseline_wave_amp_mm.toFixed(2)} mm</span>
            </div>
            <input
              type="range"
              min={0}
              max={1.5}
              step={0.05}
              value={config.perturb.baseline_wave_amp_mm}
              onChange={(e) =>
                updateConfig((p) => ({
                  ...p,
                  preset_id: null,
                  perturb: { ...p.perturb, baseline_wave_amp_mm: Number(e.target.value) },
                }))
              }
            />
          </div>

          <div className="ctrl-row">
            <div className="ctrl-label">
              <span>基线波浪周期 (period_mm)</span>
              <span className="ctrl-val mono">{config.perturb.baseline_wave_period_mm.toFixed(0)} mm</span>
            </div>
            <input
              type="range"
              min={20}
              max={200}
              step={5}
              value={config.perturb.baseline_wave_period_mm}
              onChange={(e) =>
                updateConfig((p) => ({
                  ...p,
                  preset_id: null,
                  perturb: { ...p.perturb, baseline_wave_period_mm: Number(e.target.value) },
                }))
              }
            />
          </div>

          <div className="ctrl-row">
            <div className="ctrl-label">
              <span>字距呼吸抖动 (spacing_jitter)</span>
              <span className="ctrl-val mono">{config.perturb.spacing_jitter.toFixed(2)}</span>
            </div>
            <input
              type="range"
              min={0}
              max={0.3}
              step={0.01}
              value={config.perturb.spacing_jitter}
              onChange={(e) =>
                updateConfig((p) => ({
                  ...p,
                  preset_id: null,
                  perturb: { ...p.perturb, spacing_jitter: Number(e.target.value) },
                }))
              }
            />
          </div>

          <div className="ctrl-row">
            <div className="ctrl-label">
              <span>单字微旋转 (rotation_jitter)</span>
              <span className="ctrl-val mono">{config.perturb.rotation_jitter_deg.toFixed(1)}°</span>
            </div>
            <input
              type="range"
              min={0}
              max={5}
              step={0.2}
              value={config.perturb.rotation_jitter_deg}
              onChange={(e) =>
                updateConfig((p) => ({
                  ...p,
                  preset_id: null,
                  perturb: { ...p.perturb, rotation_jitter_deg: Number(e.target.value) },
                }))
              }
            />
          </div>

          <div className="grid-2">
            <div className="mini-field">
              <span>同字异形策略</span>
              <select
                value={config.perturb.variant_strategy}
                onChange={(e) =>
                  updateConfig(
                    (p) => ({
                      ...p,
                      preset_id: null,
                      perturb: {
                        ...p.perturb,
                        variant_strategy: e.target.value as 'random_no_repeat' | 'round_robin' | 'lru',
                      },
                    }),
                    true,
                  )
                }
              >
                <option value="random_no_repeat">随机防连重</option>
                <option value="round_robin">轮询交替</option>
                <option value="lru">最近最少使用</option>
              </select>
            </div>
            <div className="mini-field">
              <span>防重窗口 ({config.perturb.variant_no_repeat_window} 字)</span>
              <div style={{ paddingTop: 6 }}>
                <input
                  type="range"
                  min={1}
                  max={16}
                  step={1}
                  value={config.perturb.variant_no_repeat_window}
                  onChange={(e) =>
                    updateConfig((p) => ({
                      ...p,
                      preset_id: null,
                      perturb: { ...p.perturb, variant_no_repeat_window: Number(e.target.value) },
                    }))
                  }
                />
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
