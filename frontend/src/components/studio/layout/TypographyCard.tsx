import React, { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { resolvePageRuleForIndex } from '../../../api/types';
import { useDocumentLayoutStore } from '../../../stores/useDocumentLayoutStore';
import { NumericInput } from './NumericInput';

export const TypographyCard: React.FC = () => {
  const [stretchOpen, setStretchOpen] = useState(false);

  const config = useDocumentLayoutStore((s) => s.config);
  const currentPageIndex = useDocumentLayoutStore((s) => s.currentPageIndex);
  const updateConfig = useDocumentLayoutStore((s) => s.updateConfig);
  const clearPageRuleOverrides = useDocumentLayoutStore((s) => s.clearPageRuleOverrides);

  const activeRule = resolvePageRuleForIndex(config.page_rules, currentPageIndex);
  const isCustomStrategy = config.page_rules.strategy !== 'uniform';
  const effRuled =
    isCustomStrategy && activeRule?.ruled ? activeRule.ruled : config.text.ruled;
  const rawPitch =
    config.text.line_spacing_mm !== null
      ? config.text.line_spacing_mm > 0
        ? config.text.line_spacing_mm
        : config.text.font_size_mm * config.text.char_scale_y + config.text.line_spacing_mm
      : config.text.line_spacing > 0
        ? config.text.font_size_mm * config.text.line_spacing * config.text.char_scale_y
        : config.text.font_size_mm * (1 + config.text.line_spacing) * config.text.char_scale_y;
  const effPitch = Math.max(0.8, rawPitch);
  const hasStretch =
    Math.abs(config.text.char_scale_x - 1) > 1e-3 ||
    Math.abs(config.text.char_scale_y - 1) > 1e-3;

  return (
    <div className="section-card">
      <div className="section-head">
        <span>书写字号与行段距排版</span>
      </div>

      <div className="ctrl-row">
        <div className="ctrl-label">
          <span>基础字号 (mm)</span>
          <NumericInput
            className="mono"
            min={1.5}
            max={40}
            decimals={1}
            value={config.text.font_size_mm}
            style={{ width: 64, padding: '2px 6px', fontSize: 11 }}
            onCommit={(val) => {
              if (val === null) return;
              updateConfig((p) => ({
                ...p,
                preset_id: null,
                text: { ...p.text, font_size_mm: val },
              }));
            }}
          />
        </div>
        <input
          type="range"
          min={2.0}
          max={20.0}
          step={0.2}
          value={Math.min(20, Math.max(2, config.text.font_size_mm))}
          onChange={(e) =>
            updateConfig((p) => ({
              ...p,
              preset_id: null,
              text: { ...p.text, font_size_mm: Number(e.target.value) },
            }))
          }
        />
      </div>

      <div className="ctrl-row">
        <div className="ctrl-label">
          <span>行距倍率 (实际行高 {effPitch.toFixed(2)} mm · 含小数/负紧缩)</span>
          <NumericInput
            className="mono"
            min={-2.0}
            max={8.0}
            decimals={2}
            disabled={config.text.line_spacing_mm !== null}
            value={config.text.line_spacing}
            style={{ width: 68, padding: '2px 6px', fontSize: 11 }}
            onCommit={(val) => {
              if (val === null) return;
              updateConfig((p) => ({
                ...p,
                preset_id: null,
                text: { ...p.text, line_spacing: val },
              }));
            }}
          />
        </div>
        <input
          type="range"
          min={-0.5}
          max={4.0}
          step={0.05}
          disabled={config.text.line_spacing_mm !== null}
          value={Math.min(4.0, Math.max(-0.5, config.text.line_spacing))}
          onChange={(e) =>
            updateConfig((p) => ({
              ...p,
              preset_id: null,
              text: { ...p.text, line_spacing: Number(e.target.value) },
            }))
          }
        />
      </div>

      {/* Free Fixed/Offset Line Spacing (supports arbitrary decimals & negatives) */}
      <div className="ctrl-row">
        <div className="ctrl-label">
          <span>自由行间距 (mm · 正值定高/负值紧缩)</span>
          <div className="row-gap" style={{ gap: 4 }}>
            <NumericInput
              className="mono"
              allowEmpty
              min={-20}
              max={80}
              decimals={2}
              placeholder="按倍率"
              value={config.text.line_spacing_mm}
              style={{ width: 68, padding: '2px 6px', fontSize: 11 }}
              onCommit={(val) =>
                updateConfig(
                  (p) => ({
                    ...p,
                    preset_id: null,
                    text: { ...p.text, line_spacing_mm: val },
                  }),
                  true,
                )
              }
            />
            {config.text.line_spacing_mm !== null && (
              <button
                type="button"
                className="btn btn-xs"
                onClick={() =>
                  updateConfig(
                    (p) => ({
                      ...p,
                      preset_id: null,
                      text: { ...p.text, line_spacing_mm: null },
                    }),
                    true,
                  )
                }
                title="恢复使用行距倍率"
              >
                ×
              </button>
            )}
          </div>
        </div>
        <input
          type="range"
          min={-8.0}
          max={28.0}
          step={0.25}
          value={Math.min(28.0, Math.max(-8.0, config.text.line_spacing_mm ?? effPitch))}
          onChange={(e) =>
            updateConfig((p) => ({
              ...p,
              preset_id: null,
              text: { ...p.text, line_spacing_mm: Number(e.target.value) },
            }))
          }
        />
      </div>

      {/* Unified Single Paragraph Spacing Control (NumericInput + Slider supporting negatives & decimals) */}
      <div className="ctrl-row">
        <div className="ctrl-label">
          <span>段落间距 (mm · 含小数/负值紧缩)</span>
          <NumericInput
            className="mono"
            min={-20}
            max={80}
            decimals={2}
            value={config.text.paragraph_spacing_mm}
            style={{ width: 68, padding: '2px 6px', fontSize: 11 }}
            onCommit={(val) => {
              if (val === null) return;
              updateConfig(
                (p) => ({
                  ...p,
                  preset_id: null,
                  text: { ...p.text, paragraph_spacing_mm: val },
                }),
                true,
              );
            }}
          />
        </div>
        <input
          type="range"
          min={-8}
          max={30}
          step={0.25}
          value={Math.min(30, Math.max(-8, config.text.paragraph_spacing_mm))}
          onChange={(e) =>
            updateConfig((p) => ({
              ...p,
              preset_id: null,
              text: { ...p.text, paragraph_spacing_mm: Number(e.target.value) },
            }))
          }
        />
      </div>

      <div className="ctrl-row">
        <div className="ctrl-label">
          <span>字距微调 ({config.text.char_spacing.toFixed(2)})</span>
          <span className="ctrl-val mono">{config.text.char_spacing.toFixed(2)}</span>
        </div>
        <input
          type="range"
          min={-0.15}
          max={0.5}
          step={0.02}
          value={config.text.char_spacing}
          onChange={(e) =>
            updateConfig((p) => ({
              ...p,
              preset_id: null,
              text: { ...p.text, char_spacing: Number(e.target.value) },
            }))
          }
        />
      </div>

      {effRuled.style !== 'none' && (
        <div className="sync-hint-banner">
          <span>
            当前处于{effRuled.style === 'grid' ? '方格' : '横线'}贴线 ({effRuled.pitch_mm} mm)：行距低于{' '}
            {effRuled.pitch_mm} mm 会自动吸线。
          </span>
          <button
            type="button"
            className="btn btn-xs"
            onClick={() => {
              updateConfig(
                (p) => ({
                  ...p,
                  preset_id: null,
                  text: { ...p.text, ruled: { ...p.text.ruled, style: 'none' } },
                }),
                true,
              );
              if (isCustomStrategy) clearPageRuleOverrides(currentPageIndex);
            }}
          >
            切为自由行距
          </button>
        </div>
      )}

      <div className="grid-2">
        <div className="mini-field">
          <span>段落对齐</span>
          <select
            value={config.text.align}
            onChange={(e) =>
              updateConfig(
                (p) => ({
                  ...p,
                  preset_id: null,
                  text: {
                    ...p.text,
                    align: e.target.value as 'left' | 'justify' | 'center' | 'right',
                  },
                }),
                true,
              )
            }
          >
            <option value="justify">两端对齐</option>
            <option value="left">左对齐</option>
            <option value="center">居中对齐</option>
            <option value="right">右对齐</option>
          </select>
        </div>
        <div className="mini-field">
          <span>首行缩进 (字)</span>
          <NumericInput
            className="mono"
            min={0}
            max={8}
            decimals={1}
            value={config.text.first_line_indent_chars}
            onCommit={(val) => {
              if (val === null) return;
              updateConfig((p) => ({
                ...p,
                preset_id: null,
                text: { ...p.text, first_line_indent_chars: val },
              }));
            }}
          />
        </div>
      </div>

      <div className="row-between" style={{ fontSize: 11.5, color: 'var(--text-secondary)', padding: '2px 0' }}>
        <span
          style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
          title="开启后，若表头（表名）后面的表格在当前页放不下需要换页，则自动将表头一并放到下一页"
        >
          表名与表格同页
        </span>
        <label className="switch" title="默认开启：表头后紧跟表格且跨页时，自动把表头一并换到下一页">
          <input
            type="checkbox"
            checked={config.table.keep_caption_with_table}
            onChange={(e) =>
              updateConfig(
                (p) => ({
                  ...p,
                  preset_id: null,
                  table: { ...p.table, keep_caption_with_table: e.target.checked },
                }),
                true,
              )
            }
          />
          <span className="switch-slider" />
        </label>
      </div>

      <div className="row-between" style={{ fontSize: 11.5, color: 'var(--text-secondary)', padding: '2px 0' }}>
        <span
          style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
          title="开启后，插图/图表与其图名（无论图名在上方还是下方）自动保持在同一页"
        >
          图名与插图同页
        </span>
        <label className="switch" title="默认开启：图名与插图跨页时，自动换页使图与图名位于同一页">
          <input
            type="checkbox"
            checked={config.chart.keep_caption_with_figure}
            onChange={(e) =>
              updateConfig(
                (p) => ({
                  ...p,
                  preset_id: null,
                  chart: { ...p.chart, keep_caption_with_figure: e.target.checked },
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
        onClick={() => setStretchOpen((v) => !v)}
      >
        <span className="row-gap" style={{ gap: 5 }}>
          <span>高级字形宽高拉伸</span>
          {hasStretch && (
            <strong style={{ color: 'var(--accent-primary)' }}>
              · {Math.round(config.text.char_scale_x * 100)}% × {Math.round(config.text.char_scale_y * 100)}%
            </strong>
          )}
        </span>
        {stretchOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </button>

      {stretchOpen && (
        <div className="grid-2">
          <div className="mini-field">
            <span>单字宽度 ({Math.round(config.text.char_scale_x * 100)}%)</span>
            <input
              type="range"
              min={0.5}
              max={2.0}
              step={0.05}
              value={config.text.char_scale_x}
              onChange={(e) =>
                updateConfig((p) => ({
                  ...p,
                  preset_id: null,
                  text: { ...p.text, char_scale_x: Number(e.target.value) },
                }))
              }
            />
          </div>
          <div className="mini-field">
            <span>单字高度 ({Math.round(config.text.char_scale_y * 100)}%)</span>
            <input
              type="range"
              min={0.5}
              max={2.0}
              step={0.05}
              value={config.text.char_scale_y}
              onChange={(e) =>
                updateConfig((p) => ({
                  ...p,
                  preset_id: null,
                  text: { ...p.text, char_scale_y: Number(e.target.value) },
                }))
              }
            />
          </div>
        </div>
      )}
    </div>
  );
};
