import React, { useMemo, useState } from 'react';
import { BookmarkPlus, Check, Sparkles, Trash2 } from 'lucide-react';
import type { PresetCategory } from '../../../api/types';
import { useDocumentLayoutStore } from '../../../stores/useDocumentLayoutStore';
import { useViewportStore } from '../../../stores/useViewportStore';

type FilterKey = 'all' | PresetCategory | 'custom';

const FILTER_TABS: Array<{ key: FilterKey; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'letter', label: '首页A+续页B' },
  { key: 'homework', label: '作业/稿纸' },
  { key: 'notes', label: '笔记' },
  { key: 'overlay', label: '套打' },
  { key: 'draft', label: '快写' },
  { key: 'custom', label: '我的' },
];

export const PresetGalleryCard: React.FC = () => {
  const [filterCat, setFilterCat] = useState<FilterKey>('all');
  const [savingPreset, setSavingPreset] = useState(false);
  const [newPresetName, setNewPresetName] = useState('');

  const config = useDocumentLayoutStore((s) => s.config);
  const presets = useDocumentLayoutStore((s) => s.presets);
  const customPresets = useDocumentLayoutStore((s) => s.customPresets);
  const applyPreset = useDocumentLayoutStore((s) => s.applyPreset);
  const saveCustomPreset = useDocumentLayoutStore((s) => s.saveCustomPreset);
  const deleteCustomPreset = useDocumentLayoutStore((s) => s.deleteCustomPreset);

  const appMode = useViewportStore((s) => s.appMode);

  const visibleBuiltinPresets = useMemo(() => {
    if (appMode !== 'demo') return [];
    if (filterCat === 'custom') return [];
    if (filterCat === 'all') return presets;
    return presets.filter((p) => p.category === filterCat);
  }, [presets, filterCat, appMode]);

  const visibleCustomPresets = useMemo(() => {
    if (appMode !== 'demo' || filterCat === 'all' || filterCat === 'custom') return customPresets;
    return [];
  }, [customPresets, filterCat, appMode]);

  const handleSavePresetSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newPresetName.trim()) return;
    saveCustomPreset(newPresetName.trim());
    setNewPresetName('');
    setSavingPreset(false);
  };

  return (
    <div className="section-card">
      <div className="section-head">
        <span className="section-head-title">
          <Sparkles size={13} style={{ color: 'var(--accent-primary)' }} />
          {appMode === 'demo' ? '内置与自定义参数预设' : `我的配置模板 (${customPresets.length})`}
        </span>
        <button
          className="btn btn-xs btn-soft"
          onClick={() => setSavingPreset((v) => !v)}
          title="将当前底稿尺寸、区域字段与书写参数保存为个人模板"
        >
          <BookmarkPlus size={11} /> 保存当前
        </button>
      </div>

      {savingPreset && (
        <form
          onSubmit={handleSavePresetSubmit}
          style={{
            display: 'flex',
            gap: 6,
            padding: 8,
            borderRadius: 9,
            background: 'var(--accent-soft)',
            border: '1px solid var(--rule-a-border)',
          }}
        >
          <input
            type="text"
            autoFocus
            value={newPresetName}
            onChange={(e) => setNewPresetName(e.target.value)}
            placeholder="输入模板名称（如：课程实验报告）"
            style={{ flex: 1, padding: '5px 8px' }}
          />
          <button type="submit" className="btn btn-xs btn-primary" disabled={!newPresetName.trim()}>
            保存
          </button>
        </form>
      )}

      {appMode === 'demo' && (
        <div className="filter-pills">
          {FILTER_TABS.map((t) => (
            <button
              key={t.key}
              className={`filter-pill ${filterCat === t.key ? 'active' : ''}`}
              onClick={() => setFilterCat(t.key)}
            >
              {t.label}
              {t.key === 'custom' && customPresets.length > 0 ? ` (${customPresets.length})` : ''}
            </button>
          ))}
        </div>
      )}

      {visibleCustomPresets.length > 0 || visibleBuiltinPresets.length > 0 || appMode === 'demo' ? (
        <div className="preset-list">
          {visibleCustomPresets.map((cp) => {
            const isActive = config.preset_id === cp.preset_id;
            return (
              <div
                key={cp.preset_id}
                className={`preset-card ${isActive ? 'active' : ''}`}
                role="button"
                tabIndex={0}
                onClick={() => applyPreset(cp.config, cp.name)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') applyPreset(cp.config, cp.name);
                }}
              >
                <div className="preset-card-title">
                  <span>★ {cp.name}</span>
                  <div className="row-gap" style={{ gap: 4 }}>
                    {isActive && <Check size={13} style={{ color: 'var(--accent-primary)' }} />}
                    <button
                      className="nudge-btn"
                      title="删除该模板"
                      onClick={(e) => {
                        e.stopPropagation();
                        deleteCustomPreset(cp.preset_id);
                      }}
                    >
                      <Trash2 size={11} />
                    </button>
                  </div>
                </div>
                <div className="preset-card-desc">{cp.description}</div>
              </div>
            );
          })}

          {visibleBuiltinPresets.map((p) => {
            const isActive = config.preset_id === p.preset_id;
            return (
              <button
                key={p.preset_id}
                type="button"
                className={`preset-card ${isActive ? 'active' : ''}`}
                onClick={() => applyPreset(p.config, p.name)}
              >
                <div className="preset-card-title">
                  <span>{p.name}</span>
                  {isActive && <Check size={13} style={{ color: 'var(--accent-primary)', flexShrink: 0 }} />}
                </div>
                <div className="preset-card-desc">{p.description}</div>
                <div className="preset-tags">
                  {p.tags.map((tag) => (
                    <span key={tag} className="preset-tag">
                      {tag}
                    </span>
                  ))}
                </div>
              </button>
            );
          })}

          {visibleBuiltinPresets.length === 0 && visibleCustomPresets.length === 0 && appMode === 'demo' && (
            <div style={{ fontSize: 11.5, color: 'var(--text-muted)', padding: '10px 4px', textAlign: 'center' }}>
              {filterCat === 'custom'
                ? '暂无自定义模板，点击右上角「保存当前」即可保存。'
                : '正在加载内置演示预设…'}
            </div>
          )}
        </div>
      ) : (
        <div style={{ fontSize: 11.5, color: 'var(--text-muted)', lineHeight: 1.45 }}>
          当前默认为空白标准 A4，无内置预设约束。配置好自定义区域或参数后，可点击「保存当前」沉淀个人模板。
        </div>
      )}

    </div>
  );
};
