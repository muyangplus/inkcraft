import React, { useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, Shapes } from 'lucide-react';
import {
  applyTableStylePreset,
  DEFAULT_LAYOUT_CONFIG,
  TABLE_STYLE_OPTIONS,
  type ImageRenderMode,
  type TableBorderStyle,
} from '../../../api/types';
import { useDocumentLayoutStore } from '../../../stores/useDocumentLayoutStore';

export const MediaStyleAccordion: React.FC = () => {
  const [open, setOpen] = useState(false);
  const config = useDocumentLayoutStore((s) => s.config);
  const currentDoc = useDocumentLayoutStore((s) => s.currentDoc);
  const updateConfig = useDocumentLayoutStore((s) => s.updateConfig);
  const applyGlobalImageStyle = useDocumentLayoutStore((s) => s.applyGlobalImageStyle);

  const modifiedCount = useMemo(() => {
    let count = 0;
    const df = DEFAULT_LAYOUT_CONFIG.formula;
    const dc = DEFAULT_LAYOUT_CONFIG.chart;
    const dt = DEFAULT_LAYOUT_CONFIG.table;
    if (Math.abs(config.formula.scale - df.scale) > 1e-4) count += 1;
    if (Math.abs(config.formula.line_spacing_mm - df.line_spacing_mm) > 1e-4) count += 1;
    if (Math.abs(config.formula.inner_row_spacing - df.inner_row_spacing) > 1e-4) count += 1;
    if (config.formula.stroke_style !== df.stroke_style) count += 1;
    if (config.chart.image_render_mode !== dc.image_render_mode) count += 1;
    if (config.chart.contour_threshold !== dc.contour_threshold) count += 1;
    if (config.chart.hatch_style !== dc.hatch_style) count += 1;
    if (Math.abs(config.chart.hatch_spacing_mm - dc.hatch_spacing_mm) > 1e-4) count += 1;
    if (Math.abs(config.chart.hatch_angle_deg - dc.hatch_angle_deg) > 1e-4) count += 1;
    if (Math.abs(config.chart.hand_jitter_mm - dc.hand_jitter_mm) > 1e-4) count += 1;
    if (config.table.draw_borders !== dt.draw_borders) count += 1;
    if (config.table.border_style !== dt.border_style) count += 1;
    if (Math.abs(config.table.width_ratio - dt.width_ratio) > 1e-4) count += 1;
    if (Math.abs(config.table.cell_padding_mm - dt.cell_padding_mm) > 1e-4) count += 1;
    if (Math.abs(config.table.row_height_scale - dt.row_height_scale) > 1e-4) count += 1;
    if (Math.abs(config.table.font_scale - dt.font_scale) > 1e-4) count += 1;
    if (config.table.align !== dt.align) count += 1;
    if (Math.abs(config.table.hand_jitter_mm - dt.hand_jitter_mm) > 1e-4) count += 1;
    return count;
  }, [config.formula, config.chart, config.table]);

  return (
    <div className="section-card">
      <button
        type="button"
        className="accordion-header"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="section-head-title">
          <Shapes size={13} style={{ color: 'var(--accent-primary)' }} />
          公式 / 插图 / 表格绘制样式
          {modifiedCount > 0 && <span className="accordion-count-badge">{modifiedCount} 项调整</span>}
        </span>
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </button>

      {open && (
        <div className="accordion-body">
          <div className="ctrl-row">
            <div className="ctrl-label">
              <span>数学公式缩放</span>
              <span className="ctrl-val mono">{config.formula.scale.toFixed(2)} ×</span>
            </div>
            <input
              type="range"
              min={0.6}
              max={1.2}
              step={0.05}
              value={config.formula.scale}
              onChange={(e) =>
                updateConfig((p) => ({
                  ...p,
                  preset_id: null,
                  formula: { ...p.formula, scale: Number(e.target.value) },
                }))
              }
            />
          </div>

          <div className="ctrl-row">
            <div className="ctrl-label">
              <span>公式上下行间距（支持负值紧缩）</span>
              <span className="ctrl-val mono">
                {config.formula.line_spacing_mm >= 0 ? '+' : ''}
                {config.formula.line_spacing_mm.toFixed(1)} mm
              </span>
            </div>
            <input
              type="range"
              min={-6.0}
              max={6.0}
              step={0.2}
              value={config.formula.line_spacing_mm}
              onChange={(e) =>
                updateConfig((p) => ({
                  ...p,
                  preset_id: null,
                  formula: { ...p.formula, line_spacing_mm: Number(e.target.value) },
                }))
              }
            />
          </div>

          <div className="ctrl-row">
            <div className="ctrl-label">
              <span>公式内行距（分式 / 上下限 / 矩阵）</span>
              <span className="ctrl-val mono">
                {config.formula.inner_row_spacing >= 0 ? '+' : ''}
                {config.formula.inner_row_spacing.toFixed(2)} em
              </span>
            </div>
            <input
              type="range"
              min={-0.24}
              max={0.4}
              step={0.02}
              value={config.formula.inner_row_spacing}
              onChange={(e) =>
                updateConfig((p) => ({
                  ...p,
                  preset_id: null,
                  formula: { ...p.formula, inner_row_spacing: Number(e.target.value) },
                }))
              }
            />
          </div>

          <div className="grid-2">
            <div className="mini-field">
              <span>插图默认绘制策略</span>
              <select
                value={config.chart.image_render_mode}
                onChange={(e) =>
                  updateConfig(
                    (p) => ({
                      ...p,
                      preset_id: null,
                      chart: {
                        ...p.chart,
                        image_render_mode: e.target.value as ImageRenderMode,
                      },
                    }),
                    true,
                  )
                }
              >
                <option value="outline">仅画轮廓 (推荐默认)</option>
                <option value="major_outline">仅主要外轮廓 (禁密集线)</option>
                <option value="hatch">轮廓 + 单向阴影</option>
                <option value="crosshatch">轮廓 + 交叉阴影</option>
                <option value="sketch">轮廓 + 素描排线</option>
                <option value="skip">跳过插图不绘制</option>
              </select>
            </div>
            <div className="mini-field">
              <span>轮廓阈值 ({config.chart.contour_threshold})</span>
              <input
                type="range"
                min={60}
                max={240}
                step={5}
                value={config.chart.contour_threshold}
                onChange={(e) =>
                  updateConfig((p) => ({
                    ...p,
                    preset_id: null,
                    chart: { ...p.chart, contour_threshold: Number(e.target.value) },
                  }))
                }
              />
            </div>
          </div>

          {currentDoc && (
            <button
              type="button"
              className="btn btn-xs"
              style={{ alignSelf: 'flex-start' }}
              onClick={() => void applyGlobalImageStyle(config.chart.image_render_mode)}
            >
              将当前插图策略应用到本文全部图片
            </button>
          )}

          <div className="grid-2">
            <div className="mini-field">
              <span>阴影排线纹理</span>
              <select
                value={config.chart.hatch_style}
                onChange={(e) =>
                  updateConfig(
                    (p) => ({
                      ...p,
                      preset_id: null,
                      chart: {
                        ...p.chart,
                        hatch_style: e.target.value as 'parallel' | 'cross' | 'zigzag',
                      },
                    }),
                    true,
                  )
                }
              >
                <option value="parallel">平行斜线</option>
                <option value="cross">交叉网纹</option>
                <option value="zigzag">往复折线</option>
              </select>
            </div>
            <div className="mini-field">
              <span>排线间距 (mm)</span>
              <input
                type="number"
                className="mono"
                min={0.8}
                max={5.0}
                step={0.1}
                value={config.chart.hatch_spacing_mm}
                onChange={(e) =>
                  updateConfig((p) => ({
                    ...p,
                    preset_id: null,
                    chart: {
                      ...p.chart,
                      hatch_spacing_mm: Math.max(0.8, Number(e.target.value) || 1.8),
                    },
                  }))
                }
              />
            </div>
          </div>

          <div className="ctrl-row">
            <div className="ctrl-label">
              <span>图表阴影倾角</span>
              <span className="ctrl-val mono">{config.chart.hatch_angle_deg.toFixed(0)}°</span>
            </div>
            <input
              type="range"
              min={-90}
              max={90}
              step={5}
              value={config.chart.hatch_angle_deg}
              onChange={(e) =>
                updateConfig((p) => ({
                  ...p,
                  preset_id: null,
                  chart: { ...p.chart, hatch_angle_deg: Number(e.target.value) },
                }))
              }
            />
          </div>

          <div className="ctrl-row">
            <div className="ctrl-label">
              <span>图表手绘抖动</span>
              <span className="ctrl-val mono">{config.chart.hand_jitter_mm.toFixed(2)} mm</span>
            </div>
            <input
              type="range"
              min={0}
              max={1.0}
              step={0.05}
              value={config.chart.hand_jitter_mm}
              onChange={(e) =>
                updateConfig((p) => ({
                  ...p,
                  preset_id: null,
                  chart: { ...p.chart, hand_jitter_mm: Number(e.target.value) },
                }))
              }
            />
          </div>

          <div className="mini-field">
            <span>表格线条风格与紧凑度</span>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginTop: 4 }}>
              {TABLE_STYLE_OPTIONS.map((opt) => {
                const effStyle: TableBorderStyle = config.table.draw_borders
                  ? config.table.border_style
                  : 'none';
                const active = effStyle === opt.value;
                return (
                  <button
                    key={opt.value}
                    type="button"
                    className={`btn btn-xs ${active ? 'btn-primary' : ''}`}
                    title={opt.desc}
                    onClick={() =>
                      updateConfig(
                        (p) => ({
                          ...p,
                          preset_id: null,
                          table: applyTableStylePreset(p.table, opt.value),
                        }),
                        true,
                      )
                    }
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="ctrl-row">
            <div className="ctrl-label">
              <span>表格宽比例 (窄小 ↔ 满栏)</span>
              <span className="ctrl-val mono">{Math.round(config.table.width_ratio * 100)}%</span>
            </div>
            <input
              type="range"
              min={0.45}
              max={1.0}
              step={0.05}
              value={config.table.width_ratio}
              onChange={(e) =>
                updateConfig((p) => ({
                  ...p,
                  preset_id: null,
                  table: { ...p.table, width_ratio: Number(e.target.value) },
                }))
              }
            />
          </div>

          <div className="grid-2">
            <div className="ctrl-row">
              <div className="ctrl-label">
                <span>单元格内边距</span>
                <span className="ctrl-val mono">{config.table.cell_padding_mm.toFixed(2)} mm</span>
              </div>
              <input
                type="range"
                min={0.35}
                max={3.5}
                step={0.1}
                value={config.table.cell_padding_mm}
                onChange={(e) =>
                  updateConfig((p) => ({
                    ...p,
                    preset_id: null,
                    table: { ...p.table, cell_padding_mm: Number(e.target.value) },
                  }))
                }
              />
            </div>

            <div className="ctrl-row">
              <div className="ctrl-label">
                <span>行高紧凑度</span>
                <span className="ctrl-val mono">{config.table.row_height_scale.toFixed(2)} ×</span>
              </div>
              <input
                type="range"
                min={0.55}
                max={1.45}
                step={0.05}
                value={config.table.row_height_scale}
                onChange={(e) =>
                  updateConfig((p) => ({
                    ...p,
                    preset_id: null,
                    table: { ...p.table, row_height_scale: Number(e.target.value) },
                  }))
                }
              />
            </div>
          </div>

          <div className="grid-2">
            <div className="ctrl-row">
              <div className="ctrl-label">
                <span>表内字号比</span>
                <span className="ctrl-val mono">{config.table.font_scale.toFixed(2)} ×</span>
              </div>
              <input
                type="range"
                min={0.55}
                max={1.1}
                step={0.04}
                value={config.table.font_scale}
                onChange={(e) =>
                  updateConfig((p) => ({
                    ...p,
                    preset_id: null,
                    table: { ...p.table, font_scale: Number(e.target.value) },
                  }))
                }
              />
            </div>

            <div className="mini-field">
              <span>表格水平对齐</span>
              <select
                value={config.table.align}
                onChange={(e) =>
                  updateConfig(
                    (p) => ({
                      ...p,
                      preset_id: null,
                      table: { ...p.table, align: e.target.value as 'left' | 'center' | 'right' },
                    }),
                    true,
                  )
                }
              >
                <option value="left">居左对齐</option>
                <option value="center">居中对齐</option>
                <option value="right">居右对齐</option>
              </select>
            </div>
          </div>

          {config.table.border_style !== 'none' && config.table.draw_borders && (
            <div className="ctrl-row">
              <div className="ctrl-label">
                <span>表格边框手绘抖动</span>
                <span className="ctrl-val mono">{config.table.hand_jitter_mm.toFixed(2)} mm</span>
              </div>
              <input
                type="range"
                min={0}
                max={1.0}
                step={0.05}
                value={config.table.hand_jitter_mm}
                onChange={(e) =>
                  updateConfig((p) => ({
                    ...p,
                    preset_id: null,
                    table: { ...p.table, hand_jitter_mm: Number(e.target.value) },
                  }))
                }
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
};
