import React, { useRef, useState } from 'react';
import { ImagePlus, Trash2 } from 'lucide-react';
import { restClient } from '../../../api/restClient';
import type { BackgroundTemplate, PageRuleOverride } from '../../../api/types';
import { useDocumentLayoutStore } from '../../../stores/useDocumentLayoutStore';
import { useViewportStore } from '../../../stores/useViewportStore';
import { NumericInput } from '../layout/NumericInput';

export interface BackgroundLibraryCardProps {
  visibleBackgrounds: BackgroundTemplate[];
}

export const BackgroundLibraryCard: React.FC<BackgroundLibraryCardProps> = ({
  visibleBackgrounds,
}) => {
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [bgName, setBgName] = useState('');
  const [customDimsOpen, setCustomDimsOpen] = useState(false);
  const [bgWidthNum, setBgWidthNum] = useState<number | null>(null);
  const [bgHeightNum, setBgHeightNum] = useState<number | null>(null);

  const config = useDocumentLayoutStore((s) => s.config);
  const uploadingBackground = useDocumentLayoutStore((s) => s.uploadingBackground);
  const uploadBackground = useDocumentLayoutStore((s) => s.uploadBackground);
  const deleteBackground = useDocumentLayoutStore((s) => s.deleteBackground);
  const assignBackgroundToSlot = useDocumentLayoutStore((s) => s.assignBackgroundToSlot);
  const pushToast = useViewportStore((s) => s.pushToast);

  const pageRules = config.page_rules;
  const strategy = pageRules.strategy;

  const handleUploadFile = async (file: File | undefined) => {
    if (!file) return;
    const uploaded = await uploadBackground(file, {
      name: bgName.trim() || undefined,
      width_mm: bgWidthNum !== null && bgWidthNum >= 20 ? bgWidthNum : config.page.width_mm,
      height_mm: bgHeightNum !== null && bgHeightNum >= 20 ? bgHeightNum : config.page.height_mm,
      margins: config.page.margins_mm,
    });
    if (uploaded) {
      setBgName('');
    }
  };

  const quickAssignBackground = (bg: BackgroundTemplate, slot: 'uniform' | 'a' | 'b') => {
    assignBackgroundToSlot(bg, slot);

    const slotLabel =
      slot === 'uniform'
        ? '全局统一底稿（已同步尺寸与边距）'
        : strategy === 'odd_even'
          ? slot === 'a'
            ? '奇数页 A'
            : '偶数页 B'
          : slot === 'a'
            ? '第 1 页方案 A'
            : '第 2 页起方案 B';
    pushToast(`已将「${bg.name}」设为 ${slotLabel}`, 'success');
  };

  return (
    <div className="section-card">
      <div className="section-head">
        <span className="section-head-title">
          <ImagePlus size={13} style={{ color: 'var(--accent-primary)' }} />
          背景底稿库 ({visibleBackgrounds.length})
        </span>
        <span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>PNG / JPG / PDF</span>
      </div>

      <input
        type="text"
        value={bgName}
        onChange={(e) => setBgName(e.target.value)}
        placeholder="可选：为即将上传的底稿命名（如：学院实验报告首页）"
        style={{ fontSize: 11.5 }}
      />

      <button
        type="button"
        className="collapsible-toggle"
        onClick={() => setCustomDimsOpen((v) => !v)}
      >
        <span>手动指定上传物理尺寸（默认按图片比例适配纸张）</span>
        <span>{customDimsOpen ? '收起' : '展开'}</span>
      </button>

      {customDimsOpen && (
        <div className="grid-2">
          <div className="mini-field">
            <span>底稿宽 (mm)</span>
            <NumericInput
              className="mono"
              allowEmpty
              min={20}
              max={1000}
              decimals={1}
              placeholder={`${Math.round(config.page.width_mm)}`}
              value={bgWidthNum}
              onCommit={setBgWidthNum}
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
              value={bgHeightNum}
              onCommit={setBgHeightNum}
            />
          </div>
        </div>
      )}

      <div
        className={`dropzone ${dragOver ? 'dragover' : ''}`}
        onClick={() => fileRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          void handleUploadFile(e.dataTransfer.files?.[0]);
        }}
      >
        <ImagePlus size={15} />
        <span>
          {uploadingBackground
            ? '正在处理并上传背景底稿…'
            : '拖入或点击上传自定义纸张底稿（PNG / JPG / WEBP / PDF）'}
        </span>
        <input
          ref={fileRef}
          type="file"
          accept=".png,.jpg,.jpeg,.webp,.bmp,.pdf"
          style={{ display: 'none' }}
          onChange={(e) => {
            void handleUploadFile(e.target.files?.[0]);
            e.target.value = '';
          }}
        />
      </div>

      {visibleBackgrounds.length === 0 ? (
        <div
          style={{
            fontSize: 11.5,
            color: 'var(--text-muted)',
            padding: '10px 8px',
            background: 'var(--bg-subtle)',
            borderRadius: 9,
            textAlign: 'center',
          }}
        >
          当前暂无上传背景底稿，默认使用空白标准 A4 纸张；拖入图片或 PDF 即可设为首页 A / 续页 B。
        </div>
      ) : (
        <div className="bg-grid">
          {visibleBackgrounds.map((bg) => {
            const isAssignedA =
              (strategy === 'uniform' && pageRules.uniform.background_id === bg.background_id) ||
              (strategy === 'first_and_rest' && pageRules.first_page.background_id === bg.background_id) ||
              (strategy === 'odd_even' && pageRules.odd_pages.background_id === bg.background_id);
            const isAssignedB =
              (strategy === 'first_and_rest' && pageRules.rest_pages.background_id === bg.background_id) ||
              (strategy === 'odd_even' && pageRules.even_pages.background_id === bg.background_id);

            return (
              <div
                key={bg.background_id}
                className={`bg-card ${isAssignedA ? 'assigned-a' : isAssignedB ? 'assigned-b' : ''}`}
              >
                <div className="bg-thumb-wrap">
                  <img
                    className="bg-thumb-img"
                    src={restClient.getBackgroundImageUrl(bg.background_id)}
                    alt={bg.name}
                    loading="lazy"
                  />
                  <span className={`bg-kind-badge ${bg.kind === 'uploaded' ? 'uploaded' : ''}`}>
                    {bg.kind === 'uploaded' ? '自传' : '内置'}
                  </span>
                  {bg.kind === 'uploaded' && (
                    <button
                      type="button"
                      className="bg-delete-btn"
                      title="删除自定义背景底稿"
                      onClick={() => {
                        if (window.confirm(`确认删除自定义底稿「${bg.name}」吗？`)) {
                          void deleteBackground(bg.background_id);
                        }
                      }}
                    >
                      <Trash2 size={11} />
                    </button>
                  )}
                </div>

                <div className="bg-card-body">
                  <div className="bg-card-name" title={bg.name}>
                    {bg.name}
                  </div>
                  <div className="bg-card-dims mono">
                    {Math.round(bg.width_mm)}×{Math.round(bg.height_mm)} mm
                  </div>
                  <div className="bg-assign-row">
                    {strategy === 'uniform' ? (
                      <button
                        type="button"
                        className={`bg-assign-btn ${isAssignedA ? 'active-a' : ''}`}
                        onClick={() => quickAssignBackground(bg, 'uniform')}
                      >
                        {isAssignedA ? '✓ 当前底稿' : '设为底稿'}
                      </button>
                    ) : (
                      <>
                        <button
                          type="button"
                          className={`bg-assign-btn ${isAssignedA ? 'active-a' : ''}`}
                          onClick={() => quickAssignBackground(bg, 'a')}
                          title={strategy === 'odd_even' ? '设为奇数页底稿' : '设为第 1 页方案 A'}
                        >
                          {strategy === 'odd_even' ? '设奇 A' : '首页 A'}
                        </button>
                        <button
                          type="button"
                          className={`bg-assign-btn ${isAssignedB ? 'active-b' : ''}`}
                          onClick={() => quickAssignBackground(bg, 'b')}
                          title={strategy === 'odd_even' ? '设为偶数页底稿' : '设为第 2 页起方案 B'}
                        >
                          {strategy === 'odd_even' ? '设偶 B' : '续页 B'}
                        </button>
                      </>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
