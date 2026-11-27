import React, { useState } from 'react';
import { ChevronDown, ChevronRight, SlidersHorizontal } from 'lucide-react';
import { resolvePageRuleForIndex } from '../../../api/types';
import { useDocumentLayoutStore } from '../../../stores/useDocumentLayoutStore';
import { useViewportStore } from '../../../stores/useViewportStore';
import { NumericInput } from './NumericInput';

const PAPER_SIZES: Record<'A4' | 'B5' | 'A5' | 'Letter', { w: number; h: number }> = {
  A4: { w: 210, h: 297 },
  B5: { w: 176, h: 250 },
  A5: { w: 148, h: 210 },
  Letter: { w: 215.9, h: 279.4 },
};

export const PaperGeometryCard: React.FC = () => {
  const [underlayAdvOpen, setUnderlayAdvOpen] = useState(false);

  const config = useDocumentLayoutStore((s) => s.config);
  const currentPageIndex = useDocumentLayoutStore((s) => s.currentPageIndex);
  const updateConfig = useDocumentLayoutStore((s) => s.updateConfig);
  const clearPageRuleOverrides = useDocumentLayoutStore((s) => s.clearPageRuleOverrides);
  const appMode = useViewportStore((s) => s.appMode);
  const setLeftTab = useViewportStore((s) => s.setLeftTab);

  const activeRule = resolvePageRuleForIndex(config.page_rules, currentPageIndex);
  const isCustomStrategy = config.page_rules.strategy !== 'uniform';
  const hasMarginsOverride = Boolean(isCustomStrategy && activeRule?.margins_mm);

  const hasUnderlayAdjust =
    config.page.underlay_fit !== 'fill' ||
    config.page.underlay_width_mm !== null ||
    config.page.underlay_height_mm !== null ||
    config.page.underlay_offset_x_mm !== 0 ||
    config.page.underlay_offset_y_mm !== 0;

  const handlePaperSize = (size: 'A4' | 'B5' | 'A5' | 'Letter' | 'custom') => {
    updateConfig((prev) => {
      if (size === 'custom') {
        return { ...prev, preset_id: null, page: { ...prev.page, size } };
      }
      const dims = PAPER_SIZES[size];
      const landscape = prev.page.orientation === 'landscape';
      return {
        ...prev,
        preset_id: null,
        page: {
          ...prev.page,
          size,
          width_mm: landscape ? dims.h : dims.w,
          height_mm: landscape ? dims.w : dims.h,
          underlay_width_mm: prev.page.underlay_fit === 'custom' ? prev.page.underlay_width_mm : null,
          underlay_height_mm: prev.page.underlay_fit === 'custom' ? prev.page.underlay_height_mm : null,
        },
      };
    }, true);
  };

  const handleOrientation = (orientation: 'portrait' | 'landscape') => {
    updateConfig((prev) => {
      if (prev.page.orientation === orientation) return prev;
      return {
        ...prev,
        preset_id: null,
        page: {
          ...prev.page,
          orientation,
          width_mm: prev.page.height_mm,
          height_mm: prev.page.width_mm,
        },
      };
    }, true);
  };

  const writableW = Math.max(
    10,
    Number((config.page.width_mm - config.page.margins_mm.left - config.page.margins_mm.right).toFixed(1)),
  );
  const writableH = Math.max(
    10,
    Number((config.page.height_mm - config.page.margins_mm.top - config.page.margins_mm.bottom).toFixed(1)),
  );

  return (
    <div className="section-card">
      <div className="section-head">
        <span className="section-head-title">
          <SlidersHorizontal size={13} style={{ color: 'var(--accent-primary)' }} />
          纸张规格与书写边距 (mm)
        </span>
        {(config.page.size !== 'A4' ||
          Math.abs(config.page.width_mm - 210) > 0.2 ||
          Math.abs(config.page.height_mm - 297) > 0.2) && (
          <button
            type="button"
            className="btn btn-xs"
            onClick={() =>
              updateConfig(
                (p) => ({
                  ...p,
                  preset_id: null,
                  page: {
                    ...p.page,
                    size: 'A4',
                    width_mm: 210,
                    height_mm: 297,
                    orientation: 'portrait',
                    underlay_fit: 'fill',
                    underlay_width_mm: null,
                    underlay_height_mm: null,
                    underlay_offset_x_mm: 0,
                    underlay_offset_y_mm: 0,
                  },
                }),
                true,
              )
            }
            title="恢复空白标准 A4 (210×297 mm)"
          >
            恢复 A4
          </button>
        )}
      </div>

      <div className="grid-2">
        <div className="mini-field">
          <span>纸张规格（同步画布与底稿）</span>
          <select
            value={config.page.size}
            onChange={(e) =>
              handlePaperSize(e.target.value as 'A4' | 'B5' | 'A5' | 'Letter' | 'custom')
            }
          >
            <option value="A4">空白标准 A4 (210×297)</option>
            {appMode === 'demo' && (
              <>
                <option value="B5">B5 (176×250)</option>
                <option value="A5">A5 (148×210)</option>
                <option value="Letter">Letter (216×279)</option>
              </>
            )}
            <option value="custom">自定义纸张尺寸</option>
          </select>
        </div>
        <div className="mini-field">
          <span>纸张方向</span>
          <select
            value={config.page.orientation}
            onChange={(e) => handleOrientation(e.target.value as 'portrait' | 'landscape')}
          >
            <option value="portrait">纵向 Portrait</option>
            <option value="landscape">横向 Landscape</option>
          </select>
        </div>
      </div>

      <div className="grid-2">
        <div className="mini-field">
          <span>纸张宽 (mm)</span>
          <NumericInput
            className="mono"
            min={20}
            max={1000}
            decimals={1}
            value={config.page.width_mm}
            onCommit={(val) => {
              if (val === null) return;
              updateConfig((p) => ({
                ...p,
                preset_id: null,
                page: { ...p.page, size: 'custom', width_mm: val },
              }));
            }}
          />
        </div>
        <div className="mini-field">
          <span>纸张高 (mm)</span>
          <NumericInput
            className="mono"
            min={20}
            max={1000}
            decimals={1}
            value={config.page.height_mm}
            onCommit={(val) => {
              if (val === null) return;
              updateConfig((p) => ({
                ...p,
                preset_id: null,
                page: { ...p.page, size: 'custom', height_mm: val },
              }));
            }}
          />
        </div>
      </div>

      <div className="grid-4">
        {(['top', 'bottom', 'left', 'right'] as const).map((side) => {
          const labels = { top: '上边距', bottom: '下边距', left: '左边距', right: '右边距' };
          return (
            <div key={side} className="mini-field">
              <span>{labels[side]}</span>
              <NumericInput
                className="mono"
                min={0}
                max={300}
                decimals={1}
                value={config.page.margins_mm[side]}
                onCommit={(val) => {
                  if (val === null) return;
                  updateConfig((p) => ({
                    ...p,
                    preset_id: null,
                    page: {
                      ...p.page,
                      margins_mm: { ...p.page.margins_mm, [side]: val },
                    },
                  }));
                }}
              />
            </div>
          );
        })}
      </div>

      <div className="grid-2">
        <div className="mini-field">
          <span>书写区宽 (mm)</span>
          <NumericInput
            className="mono"
            min={10}
            max={config.page.width_mm}
            decimals={1}
            value={writableW}
            onCommit={(val) => {
              if (val === null) return;
              updateConfig((p) => ({
                ...p,
                preset_id: null,
                page: {
                  ...p.page,
                  margins_mm: {
                    ...p.page.margins_mm,
                    right: Math.max(0, Number((p.page.width_mm - p.page.margins_mm.left - val).toFixed(1))),
                  },
                },
              }));
            }}
          />
        </div>
        <div className="mini-field">
          <span>书写区高 (mm)</span>
          <NumericInput
            className="mono"
            min={10}
            max={config.page.height_mm}
            decimals={1}
            value={writableH}
            onCommit={(val) => {
              if (val === null) return;
              updateConfig((p) => ({
                ...p,
                preset_id: null,
                page: {
                  ...p.page,
                  margins_mm: {
                    ...p.page.margins_mm,
                    bottom: Math.max(0, Number((p.page.height_mm - p.page.margins_mm.top - val).toFixed(1))),
                  },
                },
              }));
            }}
          />
        </div>
      </div>

      {hasMarginsOverride && (
        <div className="sync-hint-banner">
          <span>第 {currentPageIndex + 1} 页应用了分规则独立边距。</span>
          <button
            type="button"
            className="btn btn-xs"
            onClick={() => clearPageRuleOverrides(currentPageIndex)}
          >
            恢复全局边距
          </button>
        </div>
      )}

      <div className="grid-2">
        <div className="mini-field">
          <span>信纸基线吸附</span>
          <select
            value={config.text.ruled.style}
            onChange={(e) =>
              updateConfig(
                (p) => ({
                  ...p,
                  preset_id: null,
                  text: {
                    ...p.text,
                    ruled: {
                      ...p.text.ruled,
                      style: e.target.value as 'none' | 'lines' | 'grid',
                    },
                  },
                }),
                true,
              )
            }
          >
            <option value="none">纯白自由行距</option>
            <option value="lines">横线贴线对齐</option>
            <option value="grid">方格逐字对齐</option>
          </select>
        </div>
        <div className="mini-field">
          <span>格线间距 (mm)</span>
          <NumericInput
            className="mono"
            min={5}
            max={25}
            decimals={1}
            value={config.text.ruled.pitch_mm}
            onCommit={(val) => {
              if (val === null) return;
              updateConfig((p) => ({
                ...p,
                preset_id: null,
                text: {
                  ...p.text,
                  ruled: { ...p.text.ruled, pitch_mm: val },
                },
              }));
            }}
          />
        </div>
      </div>

      <div className="row-between" style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}>
        <span>写字机同步绘制格线 (ruled.draw)</span>
        <label className="switch">
          <input
            type="checkbox"
            checked={config.text.ruled.draw}
            onChange={(e) =>
              updateConfig(
                (p) => ({
                  ...p,
                  preset_id: null,
                  text: { ...p.text, ruled: { ...p.text.ruled, draw: e.target.checked } },
                }),
                true,
              )
            }
          />
          <span className="switch-slider" />
        </label>
      </div>

      <button
        type="button"
        className="collapsible-toggle"
        onClick={() => setUnderlayAdvOpen((v) => !v)}
      >
        <span className="row-gap" style={{ gap: 5 }}>
          <span>底稿物理偏移校准（高级）</span>
          {hasUnderlayAdjust && (
            <strong style={{ color: 'var(--accent-primary)' }}>· 已调整</strong>
          )}
        </span>
        {underlayAdvOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </button>

      {underlayAdvOpen && (
        <div
          style={{
            padding: '8px',
            borderRadius: 8,
            background: 'var(--bg-subtle)',
            border: '1px solid var(--border-subtle)',
            display: 'flex',
            flexDirection: 'column',
            gap: 7,
          }}
        >
          <div className="row-between" style={{ gap: 6 }}>
            <div className="mini-field" style={{ flex: 1 }}>
              <span>底稿适应纸面方式</span>
              <select
                value={config.page.underlay_fit}
                onChange={(e) => {
                  const fit = e.target.value as 'fill' | 'contain' | 'custom';
                  updateConfig((p) => ({
                    ...p,
                    page: {
                      ...p.page,
                      underlay_fit: fit,
                      underlay_width_mm: fit === 'custom' ? p.page.underlay_width_mm ?? p.page.width_mm : null,
                      underlay_height_mm: fit === 'custom' ? p.page.underlay_height_mm ?? p.page.height_mm : null,
                    },
                  }));
                }}
              >
                <option value="fill">铺满纸面（默认，严格同步）</option>
                <option value="contain">等比居中适应</option>
                <option value="custom">自定义物理宽高</option>
              </select>
            </div>
            {hasUnderlayAdjust && (
              <button
                type="button"
                className="btn btn-xs"
                style={{ alignSelf: 'flex-end' }}
                onClick={() =>
                  updateConfig((p) => ({
                    ...p,
                    page: {
                      ...p.page,
                      underlay_fit: 'fill',
                      underlay_width_mm: null,
                      underlay_height_mm: null,
                      underlay_offset_x_mm: 0,
                      underlay_offset_y_mm: 0,
                    },
                  }))
                }
              >
                恢复铺满
              </button>
            )}
          </div>

          <div className={config.page.underlay_fit === 'custom' ? 'grid-4' : 'grid-2'}>
            {config.page.underlay_fit === 'custom' && (
              <>
                <div className="mini-field">
                  <span>底稿宽 (mm)</span>
                  <NumericInput
                    className="mono"
                    allowEmpty
                    min={20}
                    max={1000}
                    decimals={1}
                    placeholder={`${Math.round(config.page.width_mm)}`}
                    value={config.page.underlay_width_mm}
                    onCommit={(val) =>
                      updateConfig((p) => ({
                        ...p,
                        page: { ...p.page, underlay_width_mm: val },
                      }))
                    }
                  />
                </div>
                <div className="mini-field">
                  <span>底稿高 (mm)</span>
                  <NumericInput
                    className="mono"
                    allowEmpty
                    min={20}
                    max={1000}
                    decimals={1}
                    placeholder={`${Math.round(config.page.height_mm)}`}
                    value={config.page.underlay_height_mm}
                    onCommit={(val) =>
                      updateConfig((p) => ({
                        ...p,
                        page: { ...p.page, underlay_height_mm: val },
                      }))
                    }
                  />
                </div>
              </>
            )}
            <div className="mini-field">
              <span>底稿 X 偏移 (mm)</span>
              <NumericInput
                className="mono"
                min={-200}
                max={200}
                decimals={1}
                value={config.page.underlay_offset_x_mm}
                onCommit={(val) =>
                  updateConfig((p) => ({
                    ...p,
                    page: { ...p.page, underlay_offset_x_mm: val ?? 0 },
                  }))
                }
              />
            </div>
            <div className="mini-field">
              <span>底稿 Y 偏移 (mm)</span>
              <NumericInput
                className="mono"
                min={-200}
                max={200}
                decimals={1}
                value={config.page.underlay_offset_y_mm}
                onCommit={(val) =>
                  updateConfig((p) => ({
                    ...p,
                    page: { ...p.page, underlay_offset_y_mm: val ?? 0 },
                  }))
                }
              />
            </div>
          </div>
        </div>
      )}

      <button
        type="button"
        className="collapsible-toggle"
        onClick={() => setLeftTab('refine')}
      >
        <span>需要多个独立区域或拉图填表字段？</span>
        <span>去「④ 精调」拉图框选 →</span>
      </button>
    </div>
  );
};
