import React from 'react';
import { ChevronDown, ChevronUp, Copy, Trash2 } from 'lucide-react';
import { matchesPageScope, type HwFontMeta, type WritingRegion } from '../../../api/types';
import { RegionStyleFields } from './RegionStyleFields';

export interface RegionItemCardProps {
  region: WritingRegion;
  currentPageIndex: number;
  selected: boolean;
  expanded: boolean;
  visibleWriters: HwFontMeta[];
  onSelect: (regionId: string) => void;
  onToggleExpand: () => void;
  onUpdate: (regionId: string, patch: Partial<WritingRegion>, immediate?: boolean) => void;
  onDuplicate: (regionId: string) => void;
  onRemove: (regionId: string) => void;
}

export const RegionItemCard: React.FC<RegionItemCardProps> = ({
  region: r,
  currentPageIndex,
  selected,
  expanded,
  visibleWriters,
  onSelect,
  onToggleExpand,
  onUpdate,
  onDuplicate,
  onRemove,
}) => {
  const isOnCurrentPage = matchesPageScope(r.page_scope, currentPageIndex);

  return (
    <div
      className={`region-card ${selected ? 'selected' : ''} ${!r.enabled ? 'disabled' : ''}`}
      onClick={() => onSelect(r.region_id)}
    >
      <div className="row-between" style={{ gap: 6 }}>
        <div className="row-gap" style={{ gap: 6, flex: 1, minWidth: 0 }}>
          <input
            type="checkbox"
            checked={r.enabled}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => onUpdate(r.region_id, { enabled: e.target.checked }, true)}
            title="启用或停用该区域"
          />
          <span className={`region-role-badge ${r.role === 'body' ? 'body' : 'field'}`}>
            {r.role === 'body' ? '正文' : '字段'}
          </span>
          <input
            type="text"
            value={r.name}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => onUpdate(r.region_id, { name: e.target.value }, false)}
            placeholder="区域名称"
            style={{
              flex: 1,
              minWidth: 0,
              padding: '3px 7px',
              fontSize: 12,
              fontWeight: 700,
            }}
          />
        </div>

        <div
          className="row-gap"
          style={{ gap: 3, flexShrink: 0 }}
          onClick={(e) => e.stopPropagation()}
        >
          <span
            className="mono"
            style={{
              fontSize: 10,
              color: isOnCurrentPage ? 'var(--accent-primary)' : 'var(--text-muted)',
              fontWeight: 600,
            }}
            title="生效页范围"
          >
            P:{r.page_scope || 'all'}
          </span>
          <button
            type="button"
            className="nudge-btn"
            title="复制该区域"
            onClick={() => onDuplicate(r.region_id)}
          >
            <Copy size={10} />
          </button>
          <button
            type="button"
            className="nudge-btn"
            title="删除该区域"
            onClick={() => onRemove(r.region_id)}
          >
            <Trash2 size={10} />
          </button>
          <button
            type="button"
            className="nudge-btn"
            title={expanded ? '收起详情' : '展开详情'}
            onClick={onToggleExpand}
          >
            {expanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
          </button>
        </div>
      </div>

      {r.role === 'field' ? (
        <div onClick={(e) => e.stopPropagation()}>
          {r.single_line ? (
            <input
              type="text"
              value={r.text}
              onChange={(e) => onUpdate(r.region_id, { text: e.target.value }, false)}
              placeholder={`输入「${r.name}」书写内容（支持 $公式$）`}
              style={{ padding: '5px 8px', fontSize: 12 }}
            />
          ) : (
            <textarea
              rows={2}
              value={r.text}
              onChange={(e) => onUpdate(r.region_id, { text: e.target.value }, false)}
              placeholder={`输入「${r.name}」多行内容（支持换行与 $公式$）`}
              style={{ padding: '5px 8px', fontSize: 12 }}
            />
          )}
        </div>
      ) : (
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          文档正文将按顺序自动排入该框（第 {r.order + 1} 顺位，{Math.round(r.width_mm)}×
          {Math.round(r.height_mm)} mm）
        </div>
      )}

      {expanded && (
        <RegionStyleFields region={r} visibleWriters={visibleWriters} onUpdate={onUpdate} />
      )}
    </div>
  );
};
