import React, { useState } from 'react';
import {
  FileCheck2,
  Pause,
  PenLine,
  Play,
  RotateCcw,
  Scan,
  XCircle,
} from 'lucide-react';
import { useDocumentLayoutStore } from '../../stores/useDocumentLayoutStore';
import { useMachineStore } from '../../stores/useMachineStore';
import { useViewportStore } from '../../stores/useViewportStore';

export const JobActionPanel: React.FC = () => {
  const layout = useDocumentLayoutStore((s) => s.layout);
  const currentPageIndex = useDocumentLayoutStore((s) => s.currentPageIndex);
  const activePagePaths = useDocumentLayoutStore((s) => s.activePagePaths);

  const machineState = useMachineStore((s) => s.machineState);
  const activeJobId = useMachineStore((s) => s.activeJobId);
  const busyAction = useMachineStore((s) => s.busyAction);
  const profiles = useMachineStore((s) => s.profiles);
  const activeProfileId = useMachineStore((s) => s.activeProfileId);

  const frameCheck = useMachineStore((s) => s.frameCheck);
  const startJob = useMachineStore((s) => s.startJob);
  const pauseJob = useMachineStore((s) => s.pauseJob);
  const resumeJob = useMachineStore((s) => s.resumeJob);
  const enterPenChange = useMachineStore((s) => s.enterPenChange);
  const abortJob = useMachineStore((s) => s.abortJob);

  const pushToast = useViewportStore((s) => s.pushToast);
  const openPaperChangeModal = useViewportStore((s) => s.openPaperChangeModal);

  const [writeScope, setWriteScope] = useState<'page' | 'all'>('all');

  const profile =
    profiles.find((p) => p.profile_id === activeProfileId) ??
    useMachineStore.getState().getActiveProfile();

  const pageCount = layout?.page_count ?? 0;
  const currentPageSummary = layout?.pages[currentPageIndex];
  const strokeCount = activePagePaths?.strokeCount ?? currentPageSummary?.stats.stroke_count ?? 0;
  const bbox = activePagePaths?.bbox ?? currentPageSummary?.bbox ?? [0, 0, 0, 0];

  const isOutOfBounds =
    bbox[2] > bbox[0] &&
    (bbox[0] < 0 ||
      bbox[1] < 0 ||
      bbox[2] > profile.workspace_mm.x ||
      bbox[3] > profile.workspace_mm.y);

  const canFrame =
    (machineState === 'IDLE' || machineState === 'PAPER_CHANGE') &&
    Boolean(layout) &&
    strokeCount > 0 &&
    !isOutOfBounds;

  const canStart =
    machineState === 'IDLE' && Boolean(layout) && pageCount > 0 && strokeCount > 0 && !isOutOfBounds;

  const canPause = machineState === 'RUNNING' && Boolean(activeJobId);
  const canResume =
    (machineState === 'PAUSED' || machineState === 'PEN_CHANGE') && Boolean(activeJobId);
  const canPenChange = machineState === 'PAUSED' && Boolean(activeJobId);
  const canAbort =
    (machineState === 'RUNNING' ||
      machineState === 'HOLDING' ||
      machineState === 'PAUSED' ||
      machineState === 'PEN_CHANGE' ||
      machineState === 'PAPER_CHANGE') &&
    Boolean(activeJobId);

  const handleFrame = () => {
    if (!layout) return;
    if (strokeCount === 0) {
      pushToast('当前页无有效书写笔画，已拦截试跑', 'warn');
      return;
    }
    if (isOutOfBounds) {
      pushToast('当前页外框超出机械臂物理工作区，请缩小纸张或调整偏移', 'error');
      return;
    }
    void frameCheck(layout.layout_id, currentPageIndex);
  };

  const handleStart = () => {
    if (!layout) return;
    if (strokeCount === 0) {
      pushToast('当前页无有效书写笔画（可能套打块已全部禁用）', 'warn');
      return;
    }
    if (writeScope === 'page' || layout.page_count <= 1) {
      void startJob(layout.layout_id, [currentPageIndex], currentPageIndex);
    } else {
      const indices = Array.from(
        { length: Math.max(1, layout.page_count - currentPageIndex) },
        (_, i) => currentPageIndex + i,
      );
      void startJob(layout.layout_id, indices, currentPageIndex);
    }
  };

  return (
    <div className="section-card">
      <div className="section-head">
        <span>外框与书写作业</span>
        {isOutOfBounds && (
          <span style={{ color: 'var(--state-danger)', fontSize: 10.5 }}>超出物理幅面!</span>
        )}
      </div>

      {pageCount > 1 && (
        <div className="seg-group" style={{ width: '100%' }}>
          <button
            type="button"
            style={{ flex: 1, justifyContent: 'center', fontSize: 11, padding: '4px 6px' }}
            className={`seg-btn ${writeScope === 'page' ? 'active' : ''}`}
            onClick={() => setWriteScope('page')}
            title={`仅书写当前选中的第 ${currentPageIndex + 1} 页`}
          >
            仅本页 (P{currentPageIndex + 1})
          </button>
          <button
            type="button"
            style={{ flex: 1, justifyContent: 'center', fontSize: 11, padding: '4px 6px' }}
            className={`seg-btn ${writeScope === 'all' ? 'active' : ''}`}
            onClick={() => setWriteScope('all')}
            title={`从 P${currentPageIndex + 1} 连写至 P${pageCount}（每页自动停靠换纸）`}
          >
            连写 (P{currentPageIndex + 1}–P{pageCount})
          </button>
        </div>
      )}

      <button
        type="button"
        className={`btn ${isOutOfBounds ? 'btn-danger-outline' : 'btn-cyan'}`}
        style={{ width: '100%', height: 34 }}
        disabled={!canFrame || busyAction === 'frame'}
        title={
          isOutOfBounds
            ? '外框超出机械臂物理工作区，已拦截'
            : machineState === 'IDLE' || machineState === 'PAPER_CHANGE'
              ? '强制抬笔沿当前页边界外框试跑一圈'
              : `当前状态 (${machineState}) 禁止试跑外框`
        }
        onClick={handleFrame}
      >
        <Scan size={13} />
        {isOutOfBounds
          ? '外框越界 — 已拦截'
          : `外框试跑 (P${currentPageIndex + 1})`}
      </button>

      <button
        type="button"
        className="btn btn-primary"
        style={{ width: '100%', height: 36, fontSize: 12.5 }}
        disabled={!canStart || busyAction === 'startJob'}
        title={
          machineState !== 'IDLE'
            ? `请先确保机台已连接并处于 IDLE 就绪态 (当前: ${machineState})`
            : isOutOfBounds
              ? '路径超出工作区'
              : '开始流式书写'
        }
        onClick={handleStart}
      >
        <Play size={13} />
        {pageCount > 1 && writeScope === 'all'
          ? `开始书写 (P${currentPageIndex + 1}–P${pageCount})`
          : pageCount > 1
            ? `开始书写本页 (P${currentPageIndex + 1})`
            : '开始书写当前页'}
      </button>

      <div className="grid-2">
        {machineState === 'PAUSED' || machineState === 'PEN_CHANGE' ? (
          <button
            type="button"
            className="btn btn-success"
            disabled={!canResume}
            title="发送 ~ 恢复流式书写 (Shift+Space)"
            onClick={() => void resumeJob()}
          >
            <RotateCcw size={12} /> 续写 (~)
          </button>
        ) : (
          <button
            type="button"
            className="btn btn-warn"
            disabled={!canPause}
            title="发送 ! 平滑减速暂停并抬笔 (Shift+Space)"
            onClick={() => void pauseJob()}
          >
            <Pause size={12} /> {machineState === 'HOLDING' ? '减速中…' : '暂停 (!)'}
          </button>
        )}

        <button
          type="button"
          className="btn"
          disabled={!canPenChange}
          title={
            canPenChange
              ? '记录断点并抬笔移至前端换笔安全泊位'
              : '请先点击“暂停”进入 PAUSED 态后再换笔'
          }
          onClick={() => void enterPenChange()}
        >
          <PenLine size={12} /> 换笔泊位
        </button>
      </div>

      <div className="grid-2">
        <button
          type="button"
          className="btn btn-danger-outline"
          disabled={!canAbort}
          title="中止当前作业并抬笔归位"
          onClick={() => void abortJob()}
        >
          <XCircle size={12} /> 中止作业
        </button>

        {machineState === 'PAPER_CHANGE' ? (
          <button
            type="button"
            className="btn btn-warn"
            onClick={() =>
              openPaperChangeModal(useMachineStore.getState().activeJobPageIndex)
            }
          >
            <FileCheck2 size={12} /> 换纸确认
          </button>
        ) : (
          <button
            type="button"
            className="btn btn-sm"
            disabled
            style={{ fontSize: 11 }}
            title="多页任务单页完成后自动弹出换纸确认窗"
          >
            <FileCheck2 size={12} /> 待换纸
          </button>
        )}
      </div>
    </div>
  );
};
