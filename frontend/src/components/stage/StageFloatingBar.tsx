import React from 'react';
import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Download,
  Hand,
  Image as ImageIcon,
  Layers,
  Maximize2,
  Minus,
  Plus,
  Route,
  Scan,
  SquareDashed,
} from 'lucide-react';
import { restClient } from '../../api/restClient';
import { resolvePageRuleForIndex } from '../../api/types';
import { useDocumentLayoutStore } from '../../stores/useDocumentLayoutStore';
import { useViewportStore } from '../../stores/useViewportStore';

const INK_SWATCHES = [
  { color: '#1B365D', label: '蓝黑钢笔' },
  { color: '#181B20', label: '碳素黑' },
  { color: '#1D4ED8', label: '纯蓝圆珠笔' },
  { color: '#B91C1C', label: '朱红批注' },
];

export const StageFloatingBar: React.FC = () => {
  const zoom = useViewportStore((s) => s.zoom);
  const zoomBy = useViewportStore((s) => s.zoomBy);
  const requestFit = useViewportStore((s) => s.requestFit);
  const setZoom100 = useViewportStore((s) => s.setZoom100);
  const showTravel = useViewportStore((s) => s.showTravel);
  const showBbox = useViewportStore((s) => s.showBbox);
  const showUnderlay = useViewportStore((s) => s.showUnderlay);
  const showRegions = useViewportStore((s) => s.showRegions);
  const showMissingGlyphs = useViewportStore((s) => s.showMissingGlyphs);
  const stageTool = useViewportStore((s) => s.stageTool);
  const inkColor = useViewportStore((s) => s.inkColor);
  const toggleTravel = useViewportStore((s) => s.toggleTravel);
  const toggleBbox = useViewportStore((s) => s.toggleBbox);
  const toggleUnderlay = useViewportStore((s) => s.toggleUnderlay);
  const toggleRegions = useViewportStore((s) => s.toggleRegions);
  const toggleMissingGlyphs = useViewportStore((s) => s.toggleMissingGlyphs);
  const setStageTool = useViewportStore((s) => s.setStageTool);
  const setShowRegions = useViewportStore((s) => s.setShowRegions);
  const setInkColor = useViewportStore((s) => s.setInkColor);
  const setLeftTab = useViewportStore((s) => s.setLeftTab);
  const pushToast = useViewportStore((s) => s.pushToast);

  const layout = useDocumentLayoutStore((s) => s.layout);
  const config = useDocumentLayoutStore((s) => s.config);
  const currentPageIndex = useDocumentLayoutStore((s) => s.currentPageIndex);
  const setCurrentPageIndex = useDocumentLayoutStore((s) => s.setCurrentPageIndex);

  const pageCount = layout?.page_count ?? 1;
  const currentPageSummary = layout?.pages[currentPageIndex];
  const resolvedRule = resolvePageRuleForIndex(config.page_rules, currentPageIndex);
  const activeRuleLabel = currentPageSummary?.applied_rule_label || resolvedRule?.label || '';

  const handleDownloadGcode = async () => {
    if (!layout) return;
    try {
      const gcode = await restClient.getPageGcode(layout.layout_id, currentPageIndex);
      const blob = new Blob([gcode], { type: 'text/plain;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${layout.layout_id}_page_${currentPageIndex + 1}.gcode`;
      a.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
      pushToast(`已导出第 ${currentPageIndex + 1} 页 G-code`, 'success');
    } catch (err) {
      pushToast(`导出 G-code 失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    }
  };

  return (
    <div className="stage-toolbar">
      <button className="btn btn-xs" style={{ borderRadius: 999 }} onClick={() => zoomBy(0.85)} title="缩小 (-)">
        <Minus size={12} />
      </button>
      <button
        className="btn btn-xs mono"
        style={{ minWidth: 46, borderRadius: 999 }}
        onClick={setZoom100}
        title="重置 100% 物理比例 (1)"
      >
        {Math.round(zoom * 100)}%
      </button>
      <button className="btn btn-xs" style={{ borderRadius: 999 }} onClick={() => zoomBy(1.18)} title="放大 (+)">
        <Plus size={12} />
      </button>
      <button className="btn btn-xs" style={{ borderRadius: 999 }} onClick={requestFit} title="适应窗口 (0)">
        <Maximize2 size={11} /> 适应
      </button>

      <div className="divider-v" style={{ height: 16 }} />

      <button
        className={`tool-toggle ${stageTool === 'pan' ? 'on' : ''}`}
        onClick={() => setStageTool('pan')}
        title="工作区左键拖拽平移 & 区域选中微调 (V)"
      >
        <Hand size={12} /> 拖拽
      </button>
      <button
        className={`tool-toggle ${stageTool === 'draw_region' ? 'on' : ''}`}
        onClick={() => {
          setShowRegions(true);
          setStageTool(stageTool === 'draw_region' ? 'pan' : 'draw_region');
        }}
        title="在画布左键拖框创建书写区域 / 自定义字段 (R)"
      >
        <Scan size={12} /> 拉图区域
      </button>
      <button
        className={`tool-toggle ${showRegions ? 'on' : ''}`}
        onClick={toggleRegions}
        title="显隐书写区域框"
      >
        <SquareDashed size={12} /> 区域框
      </button>
      <button
        className={`tool-toggle ${showMissingGlyphs ? 'on-danger' : ''}`}
        onClick={toggleMissingGlyphs}
        title="显隐缺字红色虚线框标注"
      >
        <AlertTriangle size={12} /> 缺字框
      </button>

      <div className="divider-v" style={{ height: 16 }} />

      <button
        className={`tool-toggle ${showTravel ? 'on-amber' : ''}`}
        onClick={toggleTravel}
        title="显隐 G0 抬笔空移轨迹 (T)"
      >
        <Route size={12} /> 空移
      </button>
      <button
        className={`tool-toggle ${showBbox ? 'on-cyan' : ''}`}
        onClick={toggleBbox}
        title="显隐 Frame Check 外框边界 (B)"
      >
        <SquareDashed size={12} /> 外框
      </button>
      <button
        className={`tool-toggle ${showUnderlay ? 'on' : ''}`}
        onClick={toggleUnderlay}
        title="显隐背景底稿 / PDF 套打底图 (U)"
      >
        <ImageIcon size={12} /> 底稿
      </button>

      <div className="divider-v" style={{ height: 16 }} />

      <div className="row-gap" style={{ gap: 5 }} title="预览墨水颜色">
        {INK_SWATCHES.map((sw) => (
          <span
            key={sw.color}
            className={`ink-dot ${inkColor === sw.color ? 'active' : ''}`}
            style={{ background: sw.color }}
            title={sw.label}
            onClick={() => setInkColor(sw.color)}
          />
        ))}
      </div>

      <div className="divider-v" style={{ height: 16 }} />

      <button
        className="btn btn-xs"
        style={{ borderRadius: 999 }}
        disabled={currentPageIndex <= 0}
        onClick={() => void setCurrentPageIndex(currentPageIndex - 1)}
        title="上一页 ([)"
      >
        <ChevronLeft size={12} />
      </button>
      <span className="mono" style={{ fontSize: 11.5, fontWeight: 700, whiteSpace: 'nowrap', padding: '0 2px' }}>
        {currentPageIndex + 1} / {Math.max(1, pageCount)}
      </span>
      <button
        className="btn btn-xs"
        style={{ borderRadius: 999 }}
        disabled={currentPageIndex >= pageCount - 1}
        onClick={() => void setCurrentPageIndex(currentPageIndex + 1)}
        title="下一页 (])"
      >
        <ChevronRight size={12} />
      </button>

      {activeRuleLabel && (
        <button
          className={`rule-badge ${currentPageIndex === 0 && config.page_rules.strategy === 'first_and_rest' ? 'tone-a' : config.page_rules.strategy === 'first_and_rest' ? 'tone-b' : 'tone-a'}`}
          style={{ cursor: 'pointer', maxWidth: 148, overflow: 'hidden', textOverflow: 'ellipsis' }}
          onClick={() => setLeftTab('paper')}
          title={`当前页生效分页规则：${activeRuleLabel}（点击进入 ② 纸张与排版）`}
        >
          <Layers size={10} />
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{activeRuleLabel}</span>
        </button>
      )}

      <div className="divider-v" style={{ height: 16 }} />

      <button
        className="btn btn-xs"
        style={{ borderRadius: 999 }}
        disabled={!layout}
        onClick={() => void handleDownloadGcode()}
        title="下载当前页标准 GRBL G-code"
      >
        <Download size={12} /> G-code
      </button>
    </div>
  );
};
