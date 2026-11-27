import React from 'react';
import type { HwFontMeta, WritingRegion } from '../../../api/types';
import { NumericInput } from '../layout/NumericInput';

export const PAGE_SCOPE_PRESETS = [
  { value: '1', label: '仅第 1 页 (1)' },
  { value: '2+', label: '第 2 页起 (2+)' },
  { value: 'all', label: '全部页 (all)' },
  { value: 'odd', label: '奇数页 (odd)' },
  { value: 'even', label: '偶数页 (even)' },
];

export interface RegionStyleFieldsProps {
  region: WritingRegion;
  visibleWriters: HwFontMeta[];
  onUpdate: (regionId: string, patch: Partial<WritingRegion>, immediate?: boolean) => void;
}

export const RegionStyleFields: React.FC<RegionStyleFieldsProps> = ({
  region: r,
  visibleWriters,
  onUpdate,
}) => {
  const isKnownScopePreset = PAGE_SCOPE_PRESETS.some((p) => p.value === r.page_scope);

  return (
    <div
      onClick={(e) => e.stopPropagation()}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 7,
        paddingTop: 6,
        borderTop: '1px solid var(--border-subtle)',
      }}
    >
      <div className="grid-2">
        <div className="mini-field">
          <span>区域类型</span>
          <select
            value={r.role}
            onChange={(e) => {
              const role = e.target.value as 'field' | 'body';
              onUpdate(
                r.region_id,
                {
                  role,
                  single_line: role === 'field',
                  valign: role === 'field' ? 'middle' : 'top',
                },
                true,
              );
            }}
          >
            <option value="field">自定义字段 (Field)</option>
            <option value="body">正文流区域 (Body Frame)</option>
          </select>
        </div>
        <div className="mini-field">
          <span>{r.role === 'field' ? '字段 Key' : '排版顺位 Order'}</span>
          {r.role === 'field' ? (
            <input
              type="text"
              className="mono"
              value={r.field_key}
              onChange={(e) => onUpdate(r.region_id, { field_key: e.target.value }, false)}
              placeholder="如 course_name"
            />
          ) : (
            <NumericInput
              className="mono"
              min={0}
              decimals={0}
              value={r.order}
              onCommit={(val) => {
                if (val === null) return;
                onUpdate(r.region_id, { order: val }, true);
              }}
            />
          )}
        </div>
      </div>

      <div className="grid-2">
        <div className="mini-field">
          <span>生效页规则</span>
          <select
            value={isKnownScopePreset ? r.page_scope : '__custom__'}
            onChange={(e) => {
              if (e.target.value !== '__custom__') {
                onUpdate(r.region_id, { page_scope: e.target.value }, true);
              }
            }}
          >
            {PAGE_SCOPE_PRESETS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
            {!isKnownScopePreset && <option value="__custom__">自定义 ({r.page_scope})</option>}
          </select>
        </div>
        <div className="mini-field">
          <span>页码表达式 (如 1, 2+, 1-3)</span>
          <input
            type="text"
            className="mono"
            value={r.page_scope}
            onChange={(e) => onUpdate(r.region_id, { page_scope: e.target.value }, false)}
            onBlur={() => onUpdate(r.region_id, {}, true)}
          />
        </div>
      </div>

      <div className="grid-4">
        <div className="mini-field">
          <span>X (mm)</span>
          <NumericInput
            className="mono"
            min={0}
            max={1000}
            decimals={1}
            value={r.x_mm}
            onCommit={(val) => val !== null && onUpdate(r.region_id, { x_mm: val }, true)}
          />
        </div>
        <div className="mini-field">
          <span>Y (mm)</span>
          <NumericInput
            className="mono"
            min={0}
            max={1000}
            decimals={1}
            value={r.y_mm}
            onCommit={(val) => val !== null && onUpdate(r.region_id, { y_mm: val }, true)}
          />
        </div>
        <div className="mini-field">
          <span>宽 W</span>
          <NumericInput
            className="mono"
            min={4}
            max={1000}
            decimals={1}
            value={r.width_mm}
            onCommit={(val) => val !== null && onUpdate(r.region_id, { width_mm: val }, true)}
          />
        </div>
        <div className="mini-field">
          <span>高 H</span>
          <NumericInput
            className="mono"
            min={3}
            max={1000}
            decimals={1}
            value={r.height_mm}
            onCommit={(val) => val !== null && onUpdate(r.region_id, { height_mm: val }, true)}
          />
        </div>
      </div>

      <div className="grid-3" style={{ gridTemplateColumns: '1fr 1fr 1fr', display: 'grid', gap: 6 }}>
        <div className="mini-field">
          <span>独立字号(mm)</span>
          <NumericInput
            className="mono"
            allowEmpty
            min={1.5}
            max={40}
            decimals={1}
            placeholder="全局"
            value={r.font_size_mm}
            onCommit={(val) => onUpdate(r.region_id, { font_size_mm: val }, true)}
          />
        </div>
        <div className="mini-field">
          <span>水平对齐</span>
          <select
            value={r.align}
            onChange={(e) =>
              onUpdate(r.region_id, { align: e.target.value as WritingRegion['align'] }, true)
            }
          >
            <option value="left">左对齐</option>
            <option value="center">居中</option>
            <option value="right">右对齐</option>
            <option value="justify">两端</option>
          </select>
        </div>
        <div className="mini-field">
          <span>垂直对齐</span>
          <select
            value={r.valign}
            onChange={(e) =>
              onUpdate(r.region_id, { valign: e.target.value as WritingRegion['valign'] }, true)
            }
          >
            <option value="top">靠上</option>
            <option value="middle">居中</option>
            <option value="bottom">靠下</option>
          </select>
        </div>
      </div>

      <div className="grid-2" style={{ marginTop: 6 }}>
        <div className="mini-field">
          <span>自由行距 (mm，支持小数/负数)</span>
          <NumericInput
            className="mono"
            allowEmpty
            min={-20}
            max={80}
            decimals={2}
            placeholder="自动"
            value={r.line_spacing_mm}
            onCommit={(val) => onUpdate(r.region_id, { line_spacing_mm: val }, true)}
          />
        </div>
        <div className="mini-field">
          <span>区域段距 (mm，支持小数/负数)</span>
          <NumericInput
            className="mono"
            allowEmpty
            min={-20}
            max={80}
            decimals={2}
            placeholder="跟随全局"
            value={r.paragraph_spacing_mm}
            onCommit={(val) => onUpdate(r.region_id, { paragraph_spacing_mm: val }, true)}
          />
        </div>
      </div>

      {r.role === 'field' && (
        <div className="row-between" style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
          <label className="row-gap" style={{ cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={r.single_line}
              onChange={(e) => onUpdate(r.region_id, { single_line: e.target.checked }, true)}
            />
            单行填格
          </label>
          <label className="row-gap" style={{ cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={r.auto_fit}
              onChange={(e) => onUpdate(r.region_id, { auto_fit: e.target.checked }, true)}
            />
            自动缩字防越界
          </label>
        </div>
      )}

      <div className="grid-2">
        <div className="mini-field">
          <span>区域专属笔迹</span>
          <select
            value={r.writer_id ?? ''}
            onChange={(e) =>
              onUpdate(r.region_id, { writer_id: e.target.value || null }, true)
            }
          >
            <option value="">跟随全局 / 分页笔迹</option>
            {visibleWriters.map((w) => (
              <option key={w.writer_id} value={w.writer_id}>
                {w.writer_name}
              </option>
            ))}
          </select>
        </div>
        <div className="mini-field">
          <span>独立工整度 (0..1)</span>
          <NumericInput
            className="mono"
            allowEmpty
            min={0}
            max={1}
            decimals={2}
            placeholder="跟随全局"
            value={r.neatness}
            onCommit={(val) => onUpdate(r.region_id, { neatness: val }, true)}
          />
        </div>
      </div>
    </div>
  );
};
