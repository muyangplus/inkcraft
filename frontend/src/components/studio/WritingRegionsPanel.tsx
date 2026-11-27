import React, { useMemo, useState } from 'react';
import { matchesPageScope, type WritingRegion } from '../../api/types';
import { useDocumentLayoutStore } from '../../stores/useDocumentLayoutStore';
import { useViewportStore } from '../../stores/useViewportStore';
import { useWriterStore } from '../../stores/useWriterStore';
import { RegionItemCard } from './regions/RegionItemCard';
import { RegionToolbarCard } from './regions/RegionToolbarCard';

export interface WritingRegionsPanelProps {
  embedded?: boolean;
}

export const WritingRegionsPanel: React.FC<WritingRegionsPanelProps> = ({ embedded = false }) => {
  const [expandedMap, setExpandedMap] = useState<Record<string, boolean>>({});

  const config = useDocumentLayoutStore((s) => s.config);
  const currentPageIndex = useDocumentLayoutStore((s) => s.currentPageIndex);
  const addRegion = useDocumentLayoutStore((s) => s.addRegion);
  const updateRegion = useDocumentLayoutStore((s) => s.updateRegion);
  const removeRegion = useDocumentLayoutStore((s) => s.removeRegion);
  const duplicateRegion = useDocumentLayoutStore((s) => s.duplicateRegion);
  const clearRegions = useDocumentLayoutStore((s) => s.clearRegions);

  const appMode = useViewportStore((s) => s.appMode);
  const selectedRegionId = useViewportStore((s) => s.selectedRegionId);
  const setSelectedRegionId = useViewportStore((s) => s.setSelectedRegionId);

  const writers = useWriterStore((s) => s.writers);
  const visibleWriters = useMemo(
    () =>
      appMode === 'demo'
        ? writers
        : writers.filter((w) => !(w.builder || '').includes('generate_demo_writers')),
    [writers, appMode],
  );

  const regions = config.regions || [];
  const activeOnPageCount = regions.filter((r) => matchesPageScope(r.page_scope, currentPageIndex)).length;

  const findNextSlotY = (defaultH: number): number => {
    const pageRegs = regions.filter((r) => matchesPageScope(r.page_scope, currentPageIndex));
    if (pageRegs.length === 0) return Math.min(config.page.height_mm - defaultH - 8, 22);
    const maxBottom = Math.max(...pageRegs.map((r) => r.y_mm + r.height_mm));
    const candidate = maxBottom + 4;
    if (candidate + defaultH <= config.page.height_mm - 8) return Number(candidate.toFixed(1));
    return Math.min(config.page.height_mm - defaultH - 8, 20 + (pageRegs.length % 8) * 14);
  };

  const handleQuickAddField = (chip: { name: string; field_key: string; w: number; h: number }) => {
    const pw = config.page.width_mm;
    const r = addRegion({
      name: chip.name,
      role: 'field',
      field_key: chip.field_key,
      text: '',
      page_scope: String(currentPageIndex + 1),
      x_mm: Math.max(8, Math.min(pw - chip.w - 8, config.page.margins_mm.left)),
      y_mm: findNextSlotY(chip.h),
      width_mm: Math.min(chip.w, pw - 16),
      height_mm: chip.h,
      single_line: true,
      auto_fit: true,
    });
    setExpandedMap((m) => ({ ...m, [r.region_id]: true }));
  };

  const handleAddCustomField = () => {
    const n = regions.filter((r) => r.role === 'field').length + 1;
    const w = Math.min(95, Math.max(25, config.page.width_mm - 40));
    const h = 11;
    const r = addRegion({
      name: `自定义字段 ${n}`,
      role: 'field',
      field_key: `field_${n}`,
      text: '',
      page_scope: String(currentPageIndex + 1),
      x_mm: config.page.margins_mm.left,
      y_mm: findNextSlotY(h),
      width_mm: w,
      height_mm: h,
      single_line: true,
      auto_fit: true,
    });
    setExpandedMap((m) => ({ ...m, [r.region_id]: true }));
  };

  const handleAddBodyRegion = () => {
    const n = regions.filter((r) => r.role === 'body').length + 1;
    const margins = config.page.margins_mm;
    const w = Math.max(30, config.page.width_mm - margins.left - margins.right);
    const y = findNextSlotY(60);
    const h = Math.max(35, Math.min(140, config.page.height_mm - margins.bottom - y));
    const r = addRegion({
      name: `正文流区域 #${n}`,
      role: 'body',
      field_key: '',
      text: '',
      page_scope: String(currentPageIndex + 1),
      x_mm: margins.left,
      y_mm: y,
      width_mm: w,
      height_mm: h,
      single_line: false,
      auto_fit: false,
      valign: 'top',
    });
    setExpandedMap((m) => ({ ...m, [r.region_id]: true }));
  };

  const body = (
    <>
      <RegionToolbarCard
        onQuickAddField={handleQuickAddField}
        onAddCustomField={handleAddCustomField}
        onAddBodyRegion={handleAddBodyRegion}
      />

      <div className="section-card">
        <div className="section-head">
          <span>
            已配置区域 ({regions.length} · 当前第 {currentPageIndex + 1} 页生效 {activeOnPageCount})
          </span>
          {regions.length > 0 && (
            <button
              type="button"
              className="btn btn-xs btn-danger-outline"
              onClick={() => {
                if (window.confirm('确认清空全部自定义区域与字段吗？')) {
                  clearRegions();
                }
              }}
            >
              清空
            </button>
          )}
        </div>

        {regions.length === 0 ? (
          <div
            style={{
              fontSize: 11.5,
              color: 'var(--text-muted)',
              padding: '10px 8px',
              background: 'var(--bg-subtle)',
              borderRadius: 9,
              textAlign: 'center',
              lineHeight: 1.5,
            }}
          >
            尚未创建自定义区域。可在画布拉图框选或点击上方快捷字段添加表头栏目。
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {regions.map((r: WritingRegion) => {
              const isSelected = selectedRegionId === r.region_id;
              const isExpanded = expandedMap[r.region_id] ?? isSelected;
              return (
                <RegionItemCard
                  key={r.region_id}
                  region={r}
                  currentPageIndex={currentPageIndex}
                  selected={isSelected}
                  expanded={isExpanded}
                  visibleWriters={visibleWriters}
                  onSelect={setSelectedRegionId}
                  onToggleExpand={() =>
                    setExpandedMap((m) => ({ ...m, [r.region_id]: !isExpanded }))
                  }
                  onUpdate={updateRegion}
                  onDuplicate={duplicateRegion}
                  onRemove={removeRegion}
                />
              );
            })}
          </div>
        )}
      </div>
    </>
  );

  return embedded ? <>{body}</> : <div className="panel-scroll">{body}</div>;
};
