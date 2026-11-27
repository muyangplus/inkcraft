import React, { useEffect, useState } from 'react';
import { ChevronDown, ChevronUp, Trash2, Wand2 } from 'lucide-react';
import { restClient } from '../../../api/restClient';
import type {
  BackgroundTemplate,
  HwFontMeta,
  MarginsMM,
  PageRuleOverride,
  RuledConfig,
} from '../../../api/types';
import { useViewportStore } from '../../../stores/useViewportStore';
import { NumericInput } from '../layout/NumericInput';

export interface RuleEditorCardProps {
  badge: string;
  tone: 'a' | 'b' | 'neutral';
  rule: PageRuleOverride;
  globalMargins: MarginsMM;
  globalFontSize: number;
  globalLineSpacing: number;
  globalLineSpacingMm?: number | null;
  globalParagraphSpacingMm?: number;
  globalRuled: RuledConfig;
  backgrounds: BackgroundTemplate[];
  writers: HwFontMeta[];
  selectorKey?: string;
  isUniform?: boolean;
  onChangeSelector?: (nextKey: string) => void;
  onDelete?: () => void;
  onChange: (next: PageRuleOverride, immediate?: boolean) => void;
}

export const PageRuleEditorCard: React.FC<RuleEditorCardProps> = ({
  badge,
  tone,
  rule,
  globalMargins,
  globalFontSize,
  globalLineSpacing,
  globalLineSpacingMm = null,
  globalParagraphSpacingMm = 3.0,
  globalRuled,
  backgrounds,
  writers,
  selectorKey,
  isUniform = false,
  onChangeSelector,
  onDelete,
  onChange,
}) => {
  const [expanded, setExpanded] = useState(false);
  const [draftSelector, setDraftSelector] = useState(selectorKey ?? '');

  useEffect(() => {
    setDraftSelector(selectorKey ?? '');
  }, [selectorKey]);

  const selectedBg = backgrounds.find((b) => b.background_id === rule.background_id) ?? null;

  const applyRecommendedMargins = () => {
    if (!selectedBg) return;
    const nextRuled: RuledConfig | null = selectedBg.recommended_ruled_pitch_mm
      ? {
          style: selectedBg.background_id.includes('grid') ? 'grid' : 'lines',
          pitch_mm: selectedBg.recommended_ruled_pitch_mm,
          draw: false,
        }
      : rule.ruled;
    onChange(
      {
        ...rule,
        margins_mm: { ...selectedBg.recommended_margins_mm },
        ruled: nextRuled,
      },
      true,
    );
    setExpanded(true);
  };

  return (
    <div className={`rule-card ${tone === 'a' ? 'tone-a' : tone === 'b' ? 'tone-b' : ''}`}>
      <div className="row-between">
        <span className={`rule-badge ${tone === 'a' ? 'tone-a' : tone === 'b' ? 'tone-b' : 'tone-neutral'}`}>
          {badge}
        </span>

        <div className="row-gap" style={{ gap: 5 }}>
          {selectorKey !== undefined && onChangeSelector && (
            <input
              type="text"
              className="mono"
              value={draftSelector}
              onChange={(e) => setDraftSelector(e.target.value)}
              onBlur={() => {
                const trimmed = draftSelector.trim();
                if (trimmed && trimmed !== selectorKey) {
                  onChangeSelector(trimmed);
                } else {
                  setDraftSelector(selectorKey);
                }
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  (e.target as HTMLInputElement).blur();
                }
              }}
              placeholder="如 1 / 2-4 / 3+"
              title="1-based 页码选择器：支持单页(1)、区间(2-4)、起始(3+) 或 default"
              style={{ width: 76, padding: '2px 6px', fontSize: 11, fontWeight: 700 }}
            />
          )}
          {onDelete && (
            <button className="nudge-btn" title="删除该页规则" onClick={onDelete}>
              <Trash2 size={11} />
            </button>
          )}
        </div>
      </div>

      <div style={{ display: 'flex', gap: 9, alignItems: 'center' }}>
        <div className="rule-bg-preview" title={selectedBg ? selectedBg.name : '纯白无底稿'}>
          {selectedBg ? (
            <img src={restClient.getBackgroundImageUrl(selectedBg.background_id)} alt={selectedBg.name} />
          ) : (
            <span>无</span>
          )}
        </div>

        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
          <input
            type="text"
            value={rule.label}
            onChange={(e) => onChange({ ...rule, label: e.target.value }, false)}
            placeholder="方案名称（如：首页方案 A）"
            style={{ padding: '4px 8px', fontSize: 11.5, fontWeight: 600 }}
          />
          <select
            value={rule.background_id ?? ''}
            onChange={(e) => {
              const bgId = e.target.value || null;
              useViewportStore.getState().setShowUnderlay(true);
              onChange({ ...rule, background_id: bgId }, true);
            }}
            style={{ padding: '4px 8px', fontSize: 11.5 }}
          >
            <option value="">空白标准纸张（无背景底稿）</option>
            {backgrounds.map((b) => (
              <option key={b.background_id} value={b.background_id}>
                {b.kind === 'uploaded' ? '[自传] ' : '[内置] '}
                {b.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {rule.background_id && (
        <div className="ctrl-row">
          <div className="ctrl-label">
            <span>底稿显示浓度</span>
            <div className="row-gap" style={{ gap: 6 }}>
              <span className="ctrl-val mono">{Math.round(rule.background_opacity * 100)}%</span>
              {selectedBg && !isUniform && (
                <button
                  type="button"
                  className="btn btn-xs btn-soft"
                  onClick={applyRecommendedMargins}
                  title={`自动填入推荐边距 (上${selectedBg.recommended_margins_mm.top} 左${selectedBg.recommended_margins_mm.left}mm)`}
                >
                  <Wand2 size={10} /> 套用底稿推荐边距
                </button>
              )}
            </div>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            step={2}
            value={Math.round(rule.background_opacity * 100)}
            onChange={(e) =>
              onChange({ ...rule, background_opacity: Number(e.target.value) / 100 }, false)
            }
          />
        </div>
      )}

      <div className="mini-field">
        <span>本规则专属笔迹 (.hwfont)</span>
        <select
          value={rule.writer_id ?? ''}
          onChange={(e) => onChange({ ...rule, writer_id: e.target.value || null }, true)}
          style={{ padding: '4px 8px', fontSize: 11.5 }}
        >
          <option value="">跟随全局当前笔迹</option>
          {writers.map((w) => (
            <option key={w.writer_id} value={w.writer_id}>
              {w.writer_name}
              {w.writer_alias ? ` · ${w.writer_alias}` : ''}
            </option>
          ))}
        </select>
      </div>

      {isUniform ? (
        <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.4 }}>
          统一模式下所有页沿用上方全局纸张尺寸与行段距设置；点选下方底稿会自动同步尺寸与边距。
        </div>
      ) : (
        <button
          type="button"
          className="collapsible-toggle"
          onClick={() => setExpanded((v) => !v)}
        >
          <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            边距 / 字号 / 行段距 / 格线覆写
            {(rule.margins_mm ||
              rule.font_size_mm ||
              rule.line_spacing ||
              rule.line_spacing_mm ||
              rule.paragraph_spacing_mm !== null ||
              rule.ruled) && (
              <strong style={{ color: 'var(--accent-primary)', marginLeft: 5 }}>
                · {rule.margins_mm ? `上${rule.margins_mm.top}mm` : '已覆写'}
                {rule.line_spacing_mm ? ` / 行${rule.line_spacing_mm}mm` : ''}
                {rule.ruled && rule.ruled.style !== 'none' ? ` / 格${rule.ruled.pitch_mm}mm` : ''}
              </strong>
            )}
          </span>
          {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        </button>
      )}

      {!isUniform && expanded && (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
            paddingTop: 4,
            borderTop: '1px solid var(--border-subtle)',
          }}
        >
          <div className="row-between">
            <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)' }}>
              独立四向边距 (mm)
            </span>
            <label className="row-gap" style={{ fontSize: 11, cursor: 'pointer', color: 'var(--text-muted)' }}>
              <input
                type="checkbox"
                checked={rule.margins_mm !== null}
                onChange={(e) =>
                  onChange(
                    {
                      ...rule,
                      margins_mm: e.target.checked ? { ...globalMargins } : null,
                    },
                    true,
                  )
                }
              />
              启用独立边距
            </label>
          </div>

          {rule.margins_mm && (
            <div className="grid-4">
              {(['top', 'bottom', 'left', 'right'] as const).map((side) => {
                const labels = { top: '上', bottom: '下', left: '左', right: '右' };
                return (
                  <div key={side} className="mini-field">
                    <span>{labels[side]}</span>
                    <NumericInput
                      className="mono"
                      min={0}
                      max={150}
                      decimals={1}
                      value={rule.margins_mm![side]}
                      onCommit={(val) => {
                        if (val === null) return;
                        onChange(
                          {
                            ...rule,
                            margins_mm: { ...rule.margins_mm!, [side]: val },
                          },
                          true,
                        );
                      }}
                    />
                  </div>
                );
              })}
            </div>
          )}

          <div className="grid-2">
            <div className="mini-field">
              <span>字号覆写 (默认 {globalFontSize.toFixed(1)})</span>
              <NumericInput
                className="mono"
                allowEmpty
                min={1.5}
                max={40}
                decimals={1}
                placeholder="跟随全局"
                value={rule.font_size_mm}
                onCommit={(val) =>
                  onChange({ ...rule, font_size_mm: val }, true)
                }
              />
            </div>
            <div className="mini-field">
              <span>行距倍率覆写 ({globalLineSpacing.toFixed(2)})</span>
              <NumericInput
                className="mono"
                allowEmpty
                min={-2.0}
                max={8.0}
                decimals={2}
                placeholder="跟随全局"
                value={rule.line_spacing}
                onCommit={(val) =>
                  onChange({ ...rule, line_spacing: val }, true)
                }
              />
            </div>
          </div>

          <div className="grid-2">
            <div className="mini-field">
              <span>
                自由行间距 mm ({globalLineSpacingMm !== null ? globalLineSpacingMm.toFixed(2) : '自动'})
              </span>
              <NumericInput
                className="mono"
                allowEmpty
                min={-20}
                max={80}
                decimals={2}
                placeholder="跟随全局"
                value={rule.line_spacing_mm}
                onCommit={(val) =>
                  onChange({ ...rule, line_spacing_mm: val }, true)
                }
              />
            </div>
            <div className="mini-field">
              <span>段间距覆写 mm (默认 {globalParagraphSpacingMm.toFixed(2)})</span>
              <NumericInput
                className="mono"
                allowEmpty
                min={-20}
                max={80}
                decimals={2}
                placeholder="跟随全局"
                value={rule.paragraph_spacing_mm}
                onCommit={(val) =>
                  onChange({ ...rule, paragraph_spacing_mm: val }, true)
                }
              />
            </div>
          </div>

          <div className="row-between">
            <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)' }}>
              独立贴线格距
            </span>
            <label className="row-gap" style={{ fontSize: 11, cursor: 'pointer', color: 'var(--text-muted)' }}>
              <input
                type="checkbox"
                checked={rule.ruled !== null}
                onChange={(e) =>
                  onChange(
                    {
                      ...rule,
                      ruled: e.target.checked ? { ...globalRuled } : null,
                    },
                    true,
                  )
                }
              />
              启用独立格线
            </label>
          </div>

          {rule.ruled && (
            <div className="grid-2">
              <div className="mini-field">
                <span>格线模式</span>
                <select
                  value={rule.ruled.style}
                  onChange={(e) =>
                    onChange(
                      {
                        ...rule,
                        ruled: {
                          ...rule.ruled!,
                          style: e.target.value as 'none' | 'lines' | 'grid',
                        },
                      },
                      true,
                    )
                  }
                >
                  <option value="none">无格线</option>
                  <option value="lines">横线贴线</option>
                  <option value="grid">方格对齐</option>
                </select>
              </div>
              <div className="mini-field">
                <span>间距 (mm)</span>
                <NumericInput
                  className="mono"
                  min={5}
                  max={25}
                  decimals={1}
                  value={rule.ruled.pitch_mm}
                  onCommit={(val) => {
                    if (val === null) return;
                    onChange(
                      {
                        ...rule,
                        ruled: { ...rule.ruled!, pitch_mm: val },
                      },
                      true,
                    );
                  }}
                />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
