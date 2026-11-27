import React, { useState } from 'react';
import { Layers, Plus, Sparkles } from 'lucide-react';
import {
  createDefaultPageRuleOverride,
  type BackgroundTemplate,
  type HwFontMeta,
  type PageRuleOverride,
  type PageRuleStrategy,
} from '../../../api/types';
import { useDocumentLayoutStore } from '../../../stores/useDocumentLayoutStore';
import { useViewportStore } from '../../../stores/useViewportStore';
import { PageRuleEditorCard } from './PageRuleEditorCard';

const STRATEGIES: Array<{ id: PageRuleStrategy; title: string; sub: string }> = [
  { id: 'uniform', title: '全部统一', sub: '所有页同底稿' },
  { id: 'first_and_rest', title: '首页 A / 续页 B', sub: '第1页A，后续页B' },
  { id: 'odd_even', title: '奇偶页交替', sub: '奇数页A / 偶数页B' },
  { id: 'custom', title: '自由逐页指定', sub: '1 / 2-4 / 3+ / 默认' },
];

const QUICK_CUSTOM_SELECTORS = [
  { selector: '1', label: '第 1 页 · 封面/首页 A' },
  { selector: '2', label: '第 2 页 · 方案 B' },
  { selector: '2-4', label: '第 2–4 页 · 中间段' },
  { selector: '3+', label: '第 3 页起 · 续页' },
  { selector: 'default', label: '其余默认页' },
];

export interface PageStrategySectionProps {
  visibleBackgrounds: BackgroundTemplate[];
  visibleWriters: HwFontMeta[];
}

export const PageStrategySection: React.FC<PageStrategySectionProps> = ({
  visibleBackgrounds,
  visibleWriters,
}) => {
  const [addingCustom, setAddingCustom] = useState(false);
  const [customSelInput, setCustomSelInput] = useState('3+');

  const config = useDocumentLayoutStore((s) => s.config);
  const updatePageRules = useDocumentLayoutStore((s) => s.updatePageRules);
  const appMode = useViewportStore((s) => s.appMode);
  const pushToast = useViewportStore((s) => s.pushToast);

  const pageRules = config.page_rules;
  const strategy = pageRules.strategy;

  const applyClassicAB = () => {
    useViewportStore.getState().setShowUnderlay(true);
    updatePageRules(
      (prev) => ({
        ...prev,
        strategy: 'first_and_rest',
        first_page: {
          ...prev.first_page,
          label: '首页方案 A · 抬头',
          background_id: 'bg_letterhead_a',
          background_opacity: 0.82,
          margins_mm: { top: 56, right: 20, bottom: 22, left: 20 },
          ruled: { style: 'lines', pitch_mm: 9.0, draw: false },
        },
        rest_pages: {
          ...prev.rest_pages,
          label: '续页方案 B · 横格',
          background_id: 'bg_lined_9mm_b',
          background_opacity: 0.78,
          margins_mm: { top: 22, right: 20, bottom: 22, left: 20 },
          ruled: { style: 'lines', pitch_mm: 9.0, draw: false },
        },
      }),
      true,
    );
    pushToast('已启用经典「首页抬头 A + 续页横格 B」组合', 'success');
  };

  const addCustomRule = (selector: string, label?: string) => {
    const key = selector.trim();
    if (!key) return;
    updatePageRules((prev) => {
      if (prev.custom_pages[key]) return prev;
      return {
        ...prev,
        strategy: 'custom',
        custom_pages: {
          ...prev.custom_pages,
          [key]: createDefaultPageRuleOverride(label || `页面 ${key}`),
        },
      };
    }, true);
    setAddingCustom(false);
  };

  const renameCustomRuleKey = (oldKey: string, newKey: string) => {
    updatePageRules((prev) => {
      if (!prev.custom_pages[oldKey] || prev.custom_pages[newKey]) return prev;
      const nextMap: Record<string, PageRuleOverride> = {};
      for (const [k, v] of Object.entries(prev.custom_pages)) {
        nextMap[k === oldKey ? newKey : k] = v;
      }
      return { ...prev, custom_pages: nextMap };
    }, true);
  };

  const removeCustomRule = (key: string) => {
    updatePageRules((prev) => {
      const nextMap = { ...prev.custom_pages };
      delete nextMap[key];
      return { ...prev, custom_pages: nextMap };
    }, true);
  };

  const customEntries = Object.entries(pageRules.custom_pages || {});

  return (
    <div className="section-card">
      <div className="section-head">
        <span className="section-head-title" style={{ whiteSpace: 'nowrap' }}>
          <Layers size={13} style={{ color: 'var(--accent-primary)' }} />
          分页组合规则
        </span>
        {appMode === 'demo' && (
          <button
            type="button"
            className="btn btn-xs btn-soft"
            onClick={applyClassicAB}
            title="一键配置：第 1 页使用抬头底稿 A，第 2 页起自动切换横格底稿 B"
          >
            <Sparkles size={10} /> 一键 A+B
          </button>
        )}
      </div>

      <div className="strategy-grid">
        {STRATEGIES.map((st) => (
          <button
            key={st.id}
            type="button"
            className={`strategy-btn ${strategy === st.id ? 'active' : ''}`}
            onClick={() => {
              updatePageRules((prev) => {
                const next = { ...prev, strategy: st.id };
                if (st.id === 'custom' && Object.keys(prev.custom_pages).length === 0) {
                  next.custom_pages = {
                    '1': { ...prev.first_page, label: prev.first_page.label || '第 1 页方案 A' },
                    '2+': { ...prev.rest_pages, label: prev.rest_pages.label || '第 2 页起方案 B' },
                  };
                }
                return next;
              }, true);
            }}
          >
            <span className="strategy-btn-title">{st.title}</span>
            <span className="strategy-btn-sub">{st.sub}</span>
          </button>
        ))}
      </div>

      {strategy === 'uniform' && (
        <PageRuleEditorCard
          badge="全局统一底稿与笔迹"
          tone="a"
          isUniform
          rule={pageRules.uniform}
          globalMargins={config.page.margins_mm}
          globalFontSize={config.text.font_size_mm}
          globalLineSpacing={config.text.line_spacing}
          globalLineSpacingMm={config.text.line_spacing_mm}
          globalParagraphSpacingMm={config.text.paragraph_spacing_mm}
          globalRuled={config.text.ruled}
          backgrounds={visibleBackgrounds}
          writers={visibleWriters}
          onChange={(next, imm) => updatePageRules((p) => ({ ...p, uniform: next }), imm)}
        />
      )}

      {strategy === 'first_and_rest' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
          <PageRuleEditorCard
            badge="方案 A · 第 1 页"
            tone="a"
            rule={pageRules.first_page}
            globalMargins={config.page.margins_mm}
            globalFontSize={config.text.font_size_mm}
            globalLineSpacing={config.text.line_spacing}
            globalLineSpacingMm={config.text.line_spacing_mm}
            globalParagraphSpacingMm={config.text.paragraph_spacing_mm}
            globalRuled={config.text.ruled}
            backgrounds={visibleBackgrounds}
            writers={visibleWriters}
            onChange={(next, imm) => updatePageRules((p) => ({ ...p, first_page: next }), imm)}
          />
          <PageRuleEditorCard
            badge="方案 B · 第 2 页及以后"
            tone="b"
            rule={pageRules.rest_pages}
            globalMargins={config.page.margins_mm}
            globalFontSize={config.text.font_size_mm}
            globalLineSpacing={config.text.line_spacing}
            globalLineSpacingMm={config.text.line_spacing_mm}
            globalParagraphSpacingMm={config.text.paragraph_spacing_mm}
            globalRuled={config.text.ruled}
            backgrounds={visibleBackgrounds}
            writers={visibleWriters}
            onChange={(next, imm) => updatePageRules((p) => ({ ...p, rest_pages: next }), imm)}
          />
        </div>
      )}

      {strategy === 'odd_even' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
          <PageRuleEditorCard
            badge="奇数页 · 方案 A (1, 3, 5…)"
            tone="a"
            rule={pageRules.odd_pages}
            globalMargins={config.page.margins_mm}
            globalFontSize={config.text.font_size_mm}
            globalLineSpacing={config.text.line_spacing}
            globalLineSpacingMm={config.text.line_spacing_mm}
            globalParagraphSpacingMm={config.text.paragraph_spacing_mm}
            globalRuled={config.text.ruled}
            backgrounds={visibleBackgrounds}
            writers={visibleWriters}
            onChange={(next, imm) => updatePageRules((p) => ({ ...p, odd_pages: next }), imm)}
          />
          <PageRuleEditorCard
            badge="偶数页 · 方案 B (2, 4, 6…)"
            tone="b"
            rule={pageRules.even_pages}
            globalMargins={config.page.margins_mm}
            globalFontSize={config.text.font_size_mm}
            globalLineSpacing={config.text.line_spacing}
            globalLineSpacingMm={config.text.line_spacing_mm}
            globalParagraphSpacingMm={config.text.paragraph_spacing_mm}
            globalRuled={config.text.ruled}
            backgrounds={visibleBackgrounds}
            writers={visibleWriters}
            onChange={(next, imm) => updatePageRules((p) => ({ ...p, even_pages: next }), imm)}
          />
        </div>
      )}

      {strategy === 'custom' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
          {customEntries.map(([sel, rule], idx) => (
            <PageRuleEditorCard
              key={sel}
              badge={`页码规则 #${idx + 1}`}
              tone={idx % 2 === 0 ? 'a' : 'b'}
              selectorKey={sel}
              rule={rule}
              globalMargins={config.page.margins_mm}
              globalFontSize={config.text.font_size_mm}
              globalLineSpacing={config.text.line_spacing}
              globalLineSpacingMm={config.text.line_spacing_mm}
              globalParagraphSpacingMm={config.text.paragraph_spacing_mm}
              globalRuled={config.text.ruled}
              backgrounds={visibleBackgrounds}
              writers={visibleWriters}
              onChangeSelector={(nextKey) => renameCustomRuleKey(sel, nextKey)}
              onDelete={() => removeCustomRule(sel)}
              onChange={(next, imm) =>
                updatePageRules(
                  (p) => ({
                    ...p,
                    custom_pages: { ...p.custom_pages, [sel]: next },
                  }),
                  imm,
                )
              }
            />
          ))}

          {addingCustom ? (
            <div
              style={{
                padding: 9,
                borderRadius: 10,
                background: 'var(--bg-input)',
                border: '1px solid var(--border-default)',
                display: 'flex',
                flexDirection: 'column',
                gap: 7,
              }}
            >
              <div className="row-gap">
                <input
                  type="text"
                  className="mono"
                  value={customSelInput}
                  onChange={(e) => setCustomSelInput(e.target.value)}
                  placeholder="页码如 1 / 2 / 2-4 / 3+ / default"
                  style={{ flex: 1 }}
                />
                <button
                  type="button"
                  className="btn btn-xs btn-primary"
                  onClick={() => addCustomRule(customSelInput)}
                >
                  添加
                </button>
                <button
                  type="button"
                  className="btn btn-xs"
                  onClick={() => setAddingCustom(false)}
                >
                  取消
                </button>
              </div>
              <div className="filter-pills">
                {QUICK_CUSTOM_SELECTORS.map((q) => (
                  <button
                    key={q.selector}
                    type="button"
                    className="filter-pill mono"
                    onClick={() => addCustomRule(q.selector, q.label)}
                  >
                    + {q.selector}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <button
              type="button"
              className="btn btn-sm btn-soft"
              style={{ width: '100%' }}
              onClick={() => setAddingCustom(true)}
            >
              <Plus size={12} /> 添加逐页规则 (1 / 2-4 / 3+ / default)
            </button>
          )}
        </div>
      )}
    </div>
  );
};
