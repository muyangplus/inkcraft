import React from 'react';
import { Eye, EyeOff, Plus, Scan } from 'lucide-react';
import { useViewportStore } from '../../../stores/useViewportStore';

export const QUICK_FIELD_CHIPS: Array<{ name: string; field_key: string; w: number; h: number }> = [
  { name: '课程名称', field_key: 'course_name', w: 90, h: 10 },
  { name: '实验名称', field_key: 'experiment_name', w: 105, h: 10 },
  { name: '姓名', field_key: 'student_name', w: 42, h: 10 },
  { name: '班级', field_key: 'class_name', w: 45, h: 10 },
  { name: '学号', field_key: 'student_id', w: 55, h: 10 },
  { name: '日期', field_key: 'date', w: 48, h: 10 },
  { name: '指导老师', field_key: 'instructor', w: 45, h: 10 },
];

export interface RegionToolbarCardProps {
  onQuickAddField: (chip: { name: string; field_key: string; w: number; h: number }) => void;
  onAddCustomField: () => void;
  onAddBodyRegion: () => void;
}

export const RegionToolbarCard: React.FC<RegionToolbarCardProps> = ({
  onQuickAddField,
  onAddCustomField,
  onAddBodyRegion,
}) => {
  const stageTool = useViewportStore((s) => s.stageTool);
  const setStageTool = useViewportStore((s) => s.setStageTool);
  const newRegionRole = useViewportStore((s) => s.newRegionRole);
  const setNewRegionRole = useViewportStore((s) => s.setNewRegionRole);
  const showRegions = useViewportStore((s) => s.showRegions);
  const toggleRegions = useViewportStore((s) => s.toggleRegions);

  return (
    <>
      <div className="section-card">
        <div className="section-head">
          <span className="section-head-title">
            <Scan size={13} style={{ color: 'var(--accent-primary)' }} />
            画布拉图与自定义区域
          </span>
          <button
            type="button"
            className="btn btn-xs"
            onClick={toggleRegions}
            title={showRegions ? '在画布隐藏区域框（仍正常排版输出）' : '在画布显示区域框'}
          >
            {showRegions ? <Eye size={11} /> : <EyeOff size={11} />}
            <span>{showRegions ? '显框' : '隐框'}</span>
          </button>
        </div>

        <button
          type="button"
          className={`btn btn-sm ${stageTool === 'draw_region' ? 'btn-primary' : 'btn-soft'}`}
          style={{ width: '100%', padding: '8px 10px' }}
          onClick={() => {
            if (stageTool === 'draw_region') {
              setStageTool('pan');
            } else {
              useViewportStore.getState().setShowRegions(true);
              setStageTool('draw_region');
            }
          }}
        >
          <Scan size={14} />
          <span>
            {stageTool === 'draw_region'
              ? '拉图框选已激活 · 请在画布拖拽划区 (Esc 退出)'
              : '在画布拉图框选新书写区域 (快捷键 R)'}
          </span>
        </button>

        <div className="row-between" style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}>
          <span>拉图新建区域类型：</span>
          <div className="seg-group" style={{ padding: 2 }}>
            <button
              type="button"
              className={`seg-btn ${newRegionRole === 'field' ? 'active' : ''}`}
              style={{ padding: '3px 9px', fontSize: 11 }}
              onClick={() => setNewRegionRole('field')}
            >
              自定义字段
            </button>
            <button
              type="button"
              className={`seg-btn ${newRegionRole === 'body' ? 'active' : ''}`}
              style={{ padding: '3px 9px', fontSize: 11 }}
              onClick={() => setNewRegionRole('body')}
            >
              正文流区域
            </button>
          </div>
        </div>
      </div>

      <div className="section-card">
        <div className="section-head">
          <span>快捷添加表头字段 / 区域</span>
        </div>

        <div className="filter-pills">
          {QUICK_FIELD_CHIPS.map((chip) => (
            <button
              key={chip.field_key}
              type="button"
              className="filter-pill"
              onClick={() => onQuickAddField(chip)}
              title={`添加可自由定位与编辑的「${chip.name}」字段`}
            >
              + {chip.name}
            </button>
          ))}
        </div>

        <div className="grid-2">
          <button type="button" className="btn btn-xs btn-soft" onClick={onAddCustomField}>
            <Plus size={11} /> 添加自定义字段
          </button>
          <button type="button" className="btn btn-xs" onClick={onAddBodyRegion}>
            <Plus size={11} /> 添加正文流区域
          </button>
        </div>
      </div>
    </>
  );
};
