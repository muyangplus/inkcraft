import React, { useRef } from 'react';
import {
  FileText,
  Info,
  Moon,
  OctagonAlert,
  PenTool,
  Sun,
  Upload,
} from 'lucide-react';
import type { MachineState } from '../../api/types';
import { useDocumentLayoutStore } from '../../stores/useDocumentLayoutStore';
import { useMachineStore } from '../../stores/useMachineStore';
import { useViewportStore } from '../../stores/useViewportStore';

const STATE_LABEL: Record<MachineState, string> = {
  DISCONNECTED: '未连接',
  CONNECTING: '握手中',
  IDLE: '就绪',
  JOGGING: '点动',
  FRAMING: '试框',
  RUNNING: '书写中',
  HOLDING: '减速',
  PAUSED: '已暂停',
  PEN_CHANGE: '换笔',
  PAPER_CHANGE: '待换纸',
  ALARM: '告警',
  ESTOPPED: '已急停',
  ERROR: '错误',
};

function ledClass(state: MachineState): string {
  switch (state) {
    case 'IDLE':
      return 'led';
    case 'RUNNING':
    case 'CONNECTING':
    case 'JOGGING':
      return 'led running';
    case 'FRAMING':
      return 'led framing';
    case 'HOLDING':
    case 'PAUSED':
    case 'PEN_CHANGE':
    case 'PAPER_CHANGE':
      return 'led warn';
    case 'ALARM':
    case 'ESTOPPED':
    case 'ERROR':
      return 'led danger';
    default:
      return 'led off';
  }
}

export const TopCommandBar: React.FC = () => {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const currentDoc = useDocumentLayoutStore((s) => s.currentDoc);
  const layout = useDocumentLayoutStore((s) => s.layout);
  const mode = useDocumentLayoutStore((s) => s.config.mode);
  const setMode = useDocumentLayoutStore((s) => s.setMode);
  const openImportPreview = useDocumentLayoutStore((s) => s.openImportPreview);
  const importPreviewLoading = useDocumentLayoutStore((s) => s.importPreviewLoading);
  const composing = useDocumentLayoutStore((s) => s.composing);

  const machineState = useMachineStore((s) => s.machineState);
  const grblState = useMachineStore((s) => s.grblState);
  const mock = useMachineStore((s) => s.mock);
  const wsConnected = useMachineStore((s) => s.wsConnected);
  const wsReconnectAttempt = useMachineStore((s) => s.wsReconnectAttempt);
  const estop = useMachineStore((s) => s.estop);

  const theme = useViewportStore((s) => s.theme);
  const toggleTheme = useViewportStore((s) => s.toggleTheme);
  const appMode = useViewportStore((s) => s.appMode);
  const setLeftTab = useViewportStore((s) => s.setLeftTab);
  const openModal = useViewportStore((s) => s.openModal);
  const workspaceView = useViewportStore((s) => s.workspaceView);
  const setWorkspaceView = useViewportStore((s) => s.setWorkspaceView);

  const isJobLocked =
    machineState === 'RUNNING' ||
    machineState === 'HOLDING' ||
    machineState === 'PAUSED' ||
    machineState === 'PEN_CHANGE' ||
    machineState === 'PAPER_CHANGE';

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      void openImportPreview(file);
      e.target.value = '';
    }
  };

  const docTitle = currentDoc?.source.filename || '上传文稿 (.docx / .pdf)';
  const pageCount = layout?.page_count ?? currentDoc?.page_count ?? 0;

  return (
    <header className="top-bar">
      <div className="top-left">
        <div className="brand">
          <div className="brand-mark">
            <PenTool size={15} strokeWidth={2.3} />
          </div>
          <span>墨迹工坊</span>
          <span className="brand-sub">Studio Workbench</span>
        </div>

        <div className="divider-v" />

        <button
          className="doc-pill"
          onClick={() => fileInputRef.current?.click()}
          title="点击上传 .docx 或 .pdf 文稿"
        >
          <FileText size={13} style={{ color: 'var(--accent-primary)', flexShrink: 0 }} />
          <span className="doc-pill-name">{docTitle}</span>
          <span className="doc-pill-sub mono">
            {importPreviewLoading
              ? '预览中…'
              : composing
                ? '排版中…'
                : pageCount > 0
                  ? `${pageCount} 页`
                  : '上传'}
          </span>
          <Upload size={11} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
        </button>

        <input
          ref={fileInputRef}
          type="file"
          accept=".docx,.pdf,.txt,.md"
          style={{ display: 'none' }}
          onChange={handleFileChange}
        />
      </div>

      <div className="top-center" style={{ gap: 8 }}>
        <div className="seg-group" role="tablist" aria-label="排版模式切换">
          <button
            className={`seg-btn ${mode === 'reflow' ? 'active' : ''}`}
            disabled={isJobLocked}
            title={isJobLocked ? '书写作业进行中，请先停止后再切换排版模式' : '智能手写重排模式'}
            onClick={() => {
              setMode('reflow');
              setLeftTab('document');
            }}
          >
            智能手写重排
          </button>
          <button
            className={`seg-btn ${mode === 'overlay' ? 'active' : ''}`}
            disabled={isJobLocked}
            title={isJobLocked ? '书写作业进行中，请先停止后再切换排版模式' : '原版坐标套打模式'}
            onClick={() => {
              setMode('overlay');
              setLeftTab('document');
            }}
          >
            原版坐标套打
          </button>
        </div>

        <div className="seg-group" role="tablist" aria-label="视图布局切换">
          <button
            className={`seg-btn ${workspaceView === 'canvas' ? 'active' : ''}`}
            onClick={() => setWorkspaceView('canvas')}
            title="全屏手写画布视图"
          >
            画布预览
          </button>
          <button
            className={`seg-btn ${workspaceView === 'split' ? 'active' : ''}`}
            onClick={() => setWorkspaceView('split')}
            title="左侧可自由编辑 Word/Markdown · 右侧实时手写画布"
          >
            分屏编辑
          </button>
          <button
            className={`seg-btn ${workspaceView === 'editor' ? 'active' : ''}`}
            onClick={() => setWorkspaceView('editor')}
            title="全屏 Word / Markdown 文档编辑器"
          >
            文档编辑
          </button>
        </div>
      </div>

      <div className="top-right">
        {!wsConnected && (
          <span className="ws-tag mono" title="后端 WebSocket 遥测断线重连中">
            WS 重连#{wsReconnectAttempt || 1}
          </span>
        )}

        <div className="status-pill" title={`机台状态: ${machineState} / GRBL: ${grblState}`}>
          <span className={ledClass(machineState)} />
          <span>{STATE_LABEL[machineState]}</span>
          <span className="mono" style={{ color: 'var(--text-muted)', fontWeight: 500, fontSize: 11 }}>
            {grblState}
          </span>
        </div>

        {mock && (
          <button
            type="button"
            className="mock-tag"
            style={{ cursor: 'pointer' }}
            onClick={() => openModal('about')}
            title="当前处于 GRBL 仿真模式，不会驱动真实硬件；点击进入「关于与系统设置」关闭"
          >
            MOCK
          </button>
        )}

        {appMode === 'demo' && (
          <button
            type="button"
            className="mock-tag"
            style={{ cursor: 'pointer', border: '1px solid var(--accent-primary)', background: 'var(--accent-soft)', color: 'var(--accent-primary)' }}
            onClick={() => openModal('about')}
            title="演示模式已开启，点击进入「关于与系统设置」关闭"
          >
            演示模式
          </button>
        )}

        <button
          className="btn btn-sm"
          onClick={() => openModal('about')}
          title="关于本软件与高级设置（含演示模式与 GRBL 仿真开关）"
        >
          <Info size={13} />
          <span>关于</span>
        </button>

        <button
          className="btn btn-icon"
          onClick={toggleTheme}
          title={theme === 'dark' ? '切换为明亮日间画室 (Light)' : '切换为曜石深色模式 (Dark)'}
        >
          {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
        </button>

        <button
          className="btn-estop"
          onClick={() => void estop()}
          title="紧急停止并强制抬笔 (0x18 + 抬笔 · 全局快捷键 Esc)"
        >
          <OctagonAlert size={14} />
          <span>E-STOP</span>
        </button>
      </div>
    </header>
  );
};
