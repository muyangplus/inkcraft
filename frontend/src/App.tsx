import React, { useEffect } from 'react';
import { Feather, FileText, Layers, SlidersHorizontal } from 'lucide-react';
import { telemetrySocket } from './api/telemetrySocket';
import { ConnectionCard } from './components/hardware/ConnectionCard';
import { DroTelemetryCard } from './components/hardware/DroTelemetryCard';
import { JobActionPanel } from './components/hardware/JobActionPanel';
import { JogControlPad } from './components/hardware/JogControlPad';
import { MachineProfileModal } from './components/hardware/MachineProfileModal';
import { PaperChangeModal } from './components/hardware/PaperChangeModal';
import { PenChangePopover } from './components/hardware/PenChangePopover';
import { AboutSettingsModal } from './components/layout/AboutSettingsModal';
import { BottomTransportBar } from './components/layout/BottomTransportBar';
import { EstopRecoveryBanner } from './components/layout/EstopRecoveryBanner';
import { TopCommandBar } from './components/layout/TopCommandBar';
import { DocumentEditorPane } from './components/editor/DocumentEditorPane';
import { FormulaEditorModal } from './components/editor/FormulaEditorModal';
import { VectorCanvasStage } from './components/stage/VectorCanvasStage';
import { DocumentImportModal } from './components/studio/DocumentImportModal';
import { FontBuilderModal } from './components/studio/FontBuilderModal';
import { GlyphInspectorModal } from './components/studio/GlyphInspectorModal';
import { QuickTextModal } from './components/studio/QuickTextModal';
import { StepDocumentPanel } from './components/studio/steps/StepDocumentPanel';
import { StepPaperPanel } from './components/studio/steps/StepPaperPanel';
import { StepRefinePanel } from './components/studio/steps/StepRefinePanel';
import { StepWriterPanel } from './components/studio/steps/StepWriterPanel';
import { useDocumentLayoutStore } from './stores/useDocumentLayoutStore';
import { useMachineStore } from './stores/useMachineStore';
import { useViewportStore } from './stores/useViewportStore';
import { useWriterStore } from './stores/useWriterStore';

export const App: React.FC = () => {
  const leftTab = useViewportStore((s) => s.leftTab);
  const setLeftTab = useViewportStore((s) => s.setLeftTab);
  const workspaceView = useViewportStore((s) => s.workspaceView);
  const toasts = useViewportStore((s) => s.toasts);
  const pageStrategy = useDocumentLayoutStore((s) => s.config.page_rules.strategy);
  const regionCount = useDocumentLayoutStore((s) => s.config.regions.length);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', useViewportStore.getState().theme);

    let wasConnectedOnce = false;

    telemetrySocket.configure({
      onConnectionChange: (connected, attempt) => {
        useMachineStore.getState().setWsConnection(connected, attempt);
        if (connected && wasConnectedOnce) {
          void useWriterStore.getState().fetchWriters();
          void useMachineStore.getState().fetchProfiles();
        }
        if (connected) {
          wasConnectedOnce = true;
        }
      },
      onMachineDiscreteChange: (status) => {
        useMachineStore.getState().applyDiscreteStatus(status);
      },
      onJobEvent: (ev) => {
        useMachineStore.getState().handleJobEvent(ev);
      },
      onJobProgressDiscrete: (prog) => {
        useMachineStore
          .getState()
          .setActiveJobPage(prog.job_id, prog.page_index, prog.page_count, prog.job_state);
        const docStore = useDocumentLayoutStore.getState();
        if (docStore.layout && docStore.currentPageIndex !== prog.page_index) {
          void docStore.setCurrentPageIndex(prog.page_index);
        }
      },
      onTaskProgress: (task) => {
        if (task.kind === 'font_import') {
          useWriterStore.getState().setFontBuildTask(task);
        } else {
          useDocumentLayoutStore.getState().handleTaskProgress(task);
        }
      },
      onWriterChanged: (writerId) => {
        const ws = useWriterStore.getState();
        if (ws.activeWriterId !== writerId) {
          ws.setActiveWriterLocal(writerId);
          void useDocumentLayoutStore.getState().composeNow(writerId);
        }
      },
      onAlarm: (alarm) => {
        useMachineStore.getState().handleAlarm(alarm);
      },
    });

    telemetrySocket.connect();

    // Boot initial data (writers, presets, backgrounds, demo doc, ports/profiles)
    void (async () => {
      await Promise.all([
        useWriterStore.getState().fetchWriters(),
        useMachineStore.getState().fetchPorts(),
        useMachineStore.getState().fetchProfiles(),
      ]);
      await useDocumentLayoutStore.getState().bootstrap();
    })();

    return () => {
      telemetrySocket.disconnect();
    };
  }, []);

  return (
    <div className="app-shell">
      <TopCommandBar />
      <EstopRecoveryBanner />

      <div className={workspaceView === 'split' ? 'workspace view-split' : 'workspace'}>
        {/* Left Studio Panel — Guided 4-Step Workflow */}
        <aside className="side-panel left-panel">
          <div className="panel-tabs" role="tablist" aria-label="4步手写工作流向导">
            <button
              role="tab"
              aria-selected={leftTab === 'document'}
              className={`panel-tab ${leftTab === 'document' ? 'active' : ''}`}
              onClick={() => setLeftTab('document')}
            >
              <FileText size={14} />
              <span>① 文稿</span>
            </button>
            <button
              role="tab"
              aria-selected={leftTab === 'paper'}
              className={`panel-tab ${leftTab === 'paper' ? 'active' : ''}`}
              onClick={() => setLeftTab('paper')}
            >
              <Layers size={14} />
              <span>② 纸张</span>
              {pageStrategy !== 'uniform' && <span className="tab-badge" />}
            </button>
            <button
              role="tab"
              aria-selected={leftTab === 'writer'}
              className={`panel-tab ${leftTab === 'writer' ? 'active' : ''}`}
              onClick={() => setLeftTab('writer')}
            >
              <Feather size={14} />
              <span>③ 笔迹</span>
            </button>
            <button
              role="tab"
              aria-selected={leftTab === 'refine'}
              className={`panel-tab ${leftTab === 'refine' ? 'active' : ''}`}
              onClick={() => setLeftTab('refine')}
            >
              <SlidersHorizontal size={14} />
              <span>④ 精调</span>
              {regionCount > 0 && <span className="tab-badge" />}
            </button>
          </div>

          {leftTab === 'document' && <StepDocumentPanel />}
          {leftTab === 'paper' && <StepPaperPanel />}
          {leftTab === 'writer' && <StepWriterPanel />}
          {leftTab === 'refine' && <StepRefinePanel />}
        </aside>

        {/* Optional Word / Markdown Document Editor */}
        {(workspaceView === 'split' || workspaceView === 'editor') && <DocumentEditorPane />}

        {/* Center Multi-Layer Vector Stage */}
        {workspaceView !== 'editor' && <VectorCanvasStage />}

        {/* Right Hardware & Safety Console */}
        <aside className="side-panel right-panel">
          <div className="panel-scroll">
            <ConnectionCard />
            <DroTelemetryCard />
            <JogControlPad />
            <JobActionPanel />
          </div>
        </aside>
      </div>

      <BottomTransportBar />

      {/* Modals & Safety Overlays */}
      <AboutSettingsModal />
      <DocumentImportModal />
      <GlyphInspectorModal />
      <FontBuilderModal />
      <FormulaEditorModal />
      <QuickTextModal />
      <MachineProfileModal />
      <PaperChangeModal />
      <PenChangePopover />

      {/* Toast Stack */}
      {toasts.length > 0 && (
        <div className="toast-stack" role="status" aria-live="polite">
          {toasts.map((t) => (
            <div key={t.id} className={`toast-item ${t.tone}`}>
              {t.message}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default App;
