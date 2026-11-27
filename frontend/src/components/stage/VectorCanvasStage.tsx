import React, { useEffect, useRef, useState } from 'react';
import { restClient } from '../../api/restClient';
import { resolvePageRuleForIndex } from '../../api/types';
import { VectorStageEngine } from '../../canvas/VectorStageEngine';
import { useDocumentLayoutStore } from '../../stores/useDocumentLayoutStore';
import { useMachineStore } from '../../stores/useMachineStore';
import { useViewportStore } from '../../stores/useViewportStore';
import { CanvasImageToolbar } from './CanvasImageToolbar';
import { MissingGlyphNavigator } from './MissingGlyphNavigator';
import { PageFilmstrip } from './PageFilmstrip';
import { StageFloatingBar } from './StageFloatingBar';

const PARSE_STAGES = [
  'upload',
  'convert',
  'mineru_layout',
  'mineru_ocr',
  'mineru_formula',
  'mineru_table',
  'assemble',
];

export const VectorCanvasStage: React.FC = () => {
  const mainCanvasRef = useRef<HTMLCanvasElement>(null);
  const topRulerRef = useRef<HTMLCanvasElement>(null);
  const leftRulerRef = useRef<HTMLCanvasElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const cursorHudRef = useRef<HTMLSpanElement>(null);
  const engineRef = useRef<VectorStageEngine | null>(null);
  const panStartRef = useRef<{ x: number; y: number } | null>(null);
  const clickCandidateRef = useRef<{ x: number; y: number; sx: number; sy: number } | null>(null);

  const [spacePressed, setSpacePressed] = useState(false);
  const [isPanning, setIsPanning] = useState(false);
  const [hoverCursor, setHoverCursor] = useState<string>('grab');

  const theme = useViewportStore((s) => s.theme);
  const zoom = useViewportStore((s) => s.zoom);
  const lastSyncedZoomRef = useRef<number>(zoom);
  const fitNonce = useViewportStore((s) => s.fitNonce);
  const showTravel = useViewportStore((s) => s.showTravel);
  const showBbox = useViewportStore((s) => s.showBbox);
  const showUnderlay = useViewportStore((s) => s.showUnderlay);
  const showRuled = useViewportStore((s) => s.showRuled);
  const showRegions = useViewportStore((s) => s.showRegions);
  const showMissingGlyphs = useViewportStore((s) => s.showMissingGlyphs);
  const inkColor = useViewportStore((s) => s.inkColor);
  const stageTool = useViewportStore((s) => s.stageTool);
  const workspaceView = useViewportStore((s) => s.workspaceView);
  const selectedRegionId = useViewportStore((s) => s.selectedRegionId);
  const selectedBlockId = useViewportStore((s) => s.selectedBlockId);
  const selectedObjectId = useViewportStore((s) => s.selectedObjectId);
  const activeMissingGlyphId = useViewportStore((s) => s.activeMissingGlyphId);
  const cameraFocusRequest = useViewportStore((s) => s.cameraFocusRequest);
  const clearCameraFocus = useViewportStore((s) => s.clearCameraFocus);
  const playbackProgress = useViewportStore((s) => s.playbackProgress);

  const currentDoc = useDocumentLayoutStore((s) => s.currentDoc);
  const blocks = useDocumentLayoutStore((s) => s.blocks);
  const config = useDocumentLayoutStore((s) => s.config);
  const backgrounds = useDocumentLayoutStore((s) => s.backgrounds);
  const layout = useDocumentLayoutStore((s) => s.layout);
  const currentPageIndex = useDocumentLayoutStore((s) => s.currentPageIndex);
  const activePagePaths = useDocumentLayoutStore((s) => s.activePagePaths);
  const parseTask = useDocumentLayoutStore((s) => s.parseTask);
  const setOverlayBlockNudge = useDocumentLayoutStore((s) => s.setOverlayBlockNudge);
  const addRegion = useDocumentLayoutStore((s) => s.addRegion);
  const updateRegion = useDocumentLayoutStore((s) => s.updateRegion);

  const machineState = useMachineStore((s) => s.machineState);
  const profiles = useMachineStore((s) => s.profiles);
  const activeProfileId = useMachineStore((s) => s.activeProfileId);
  const profile =
    profiles.find((p) => p.profile_id === activeProfileId) ??
    useMachineStore.getState().getActiveProfile();

  // Mount VectorStageEngine once
  useEffect(() => {
    if (!mainCanvasRef.current || !topRulerRef.current || !leftRulerRef.current) return;
    const engine = new VectorStageEngine({
      mainCanvas: mainCanvasRef.current,
      topRuler: topRulerRef.current,
      leftRuler: leftRulerRef.current,
      onCameraChange: (z, px, py) => {
        lastSyncedZoomRef.current = z;
        useViewportStore.getState().setCamera(z, px, py);
      },
      onCursorMove: (mm) => {
        if (cursorHudRef.current) {
          cursorHudRef.current.textContent = mm
            ? `X ${mm.x.toFixed(1)} · Y ${mm.y.toFixed(1)} mm`
            : 'X --.- · Y --.- mm';
        }
      },
      onSelectBlock: (blockId) => {
        useViewportStore.getState().setSelectedBlockId(blockId);
      },
      onBlockDragEnd: (blockId, nx, ny) => {
        useDocumentLayoutStore.getState().setOverlayBlockNudge(blockId, nx, ny);
      },
      onSelectRegion: (regionId) => {
        useViewportStore.getState().setSelectedRegionId(regionId);
      },
      onCreateRegion: (rect) => {
        const vp = useViewportStore.getState();
        const docState = useDocumentLayoutStore.getState();
        const role = vp.newRegionRole;
        const countSame = docState.config.regions.filter((r) => r.role === role).length + 1;
        const created = docState.addRegion({
          name: role === 'body' ? `正文区域 #${countSame}` : `字段 #${countSame}`,
          role,
          field_key: role === 'field' ? `field_${countSame}` : '',
          text: '',
          page_scope: String(docState.currentPageIndex + 1),
          x_mm: rect.x_mm,
          y_mm: rect.y_mm,
          width_mm: rect.width_mm,
          height_mm: rect.height_mm,
          single_line: role === 'field',
          valign: role === 'field' ? 'middle' : 'top',
        });
        vp.setStageTool('pan');
        vp.setLeftTab('refine');
        vp.pushToast(`已划定「${created.name}」(${rect.width_mm}×${rect.height_mm} mm)`, 'success');
      },
      onUpdateRegionRect: (regionId, rect) => {
        useDocumentLayoutStore.getState().updateRegion(regionId, rect, true);
      },
      onSelectObject: (blockId) => {
        useViewportStore.getState().setSelectedObjectId(blockId);
      },
      onLocateBlockInEditor: (blockId) => {
        const vp = useViewportStore.getState();
        if (vp.workspaceView === 'canvas') {
          vp.setWorkspaceView('split');
        }
        vp.requestEditorScroll(blockId);
      },
      onSelectMissingGlyph: (mg) => {
        void useDocumentLayoutStore.getState().focusMissingGlyph(mg);
      },
      onDoubleClickFormula: (box) => {
        const docState = useDocumentLayoutStore.getState();
        const docId = docState.currentDoc?.doc_id;
        if (!docId) return;
        const blk = docState.blocks.find((b) => b.block_id === box.block_id);
        let initLatex = box.latex ?? blk?.latex ?? '';
        if (box.inline_index !== null && box.inline_index !== undefined && blk?.inlines) {
          const inl = blk.inlines[box.inline_index];
          if (inl && inl.t === 'math') initLatex = inl.latex;
        }
        useViewportStore.getState().openFormulaEditor({
          docId,
          blockId: box.block_id,
          inlineIndex: box.inline_index ?? null,
          initialLatex: initLatex,
          assetName: blk?.asset_name ?? null,
        });
      },
      onUpdatePlacedImageBox: (blockId, pageIdx, bboxMm) => {
        void useDocumentLayoutStore.getState().patchDocumentBlock(blockId, {
          placement: 'float',
          page_index: pageIdx,
          float_box_mm: bboxMm,
        });
      },
      onCursorStyleChange: (c) => {
        setHoverCursor(c);
      },
    });
    engineRef.current = engine;
    const fitRaf = requestAnimationFrame(() => {
      if (!useViewportStore.getState().cameraFocusRequest) {
        engine.fitToViewport();
      }
    });
    return () => {
      cancelAnimationFrame(fitRaf);
      engine.destroy();
      engineRef.current = null;
    };
  }, [addRegion, updateRegion]);

  // Push scene snapshots to engine (resolving per-page background_id & underlay physical rect!)
  useEffect(() => {
    const engine = engineRef.current;
    if (!engine) return;

    const pageSummary = layout?.pages[currentPageIndex];
    const resolvedRule = resolvePageRuleForIndex(config.page_rules, currentPageIndex);
    const effectiveBgId = pageSummary?.background_id ?? resolvedRule?.background_id ?? null;
    const effectiveBgOpacity =
      typeof pageSummary?.background_opacity === 'number'
        ? pageSummary.background_opacity
        : resolvedRule?.background_opacity ?? 0.72;

    const pageInfo = currentDoc?.pages?.[currentPageIndex];
    const hasPdfImage = Boolean(currentDoc && (pageInfo?.image || currentDoc.source.type === 'pdf'));
    const pdfUnderlayUrl =
      config.mode === 'overlay' && hasPdfImage && currentDoc
        ? restClient.getPageImageUrl(currentDoc.doc_id, currentPageIndex)
        : null;

    const underlayUrl =
      config.mode === 'overlay' && pdfUnderlayUrl
        ? pdfUnderlayUrl
        : effectiveBgId
          ? restClient.getBackgroundImageUrl(effectiveBgId)
          : null;

    const underlayOpacity =
      config.mode === 'overlay' && pdfUnderlayUrl
        ? config.overlay.underlay_opacity
        : effectiveBgOpacity;

    const hasPageBackground = Boolean(
      effectiveBgId && !(config.mode === 'overlay' && pdfUnderlayUrl),
    );

    const activeMargins = resolvedRule?.margins_mm ?? config.page.margins_mm;
    const activeRuled = resolvedRule?.ruled ?? config.text.ruled;
    const pageW = activePagePaths?.widthMm || config.page.width_mm || 210;
    const pageH = activePagePaths?.heightMm || config.page.height_mm || 297;
    const ox = config.page.underlay_offset_x_mm || 0;
    const oy = config.page.underlay_offset_y_mm || 0;

    let underlayRectMm = { x: ox, y: oy, w: pageW, h: pageH };
    if (config.mode === 'overlay' && pdfUnderlayUrl) {
      underlayRectMm = { x: 0, y: 0, w: pageW, h: pageH };
    } else if (config.page.underlay_fit === 'custom') {
      underlayRectMm = {
        x: ox,
        y: oy,
        w: config.page.underlay_width_mm ?? pageW,
        h: config.page.underlay_height_mm ?? pageH,
      };
    } else if (config.page.underlay_fit === 'contain' && effectiveBgId) {
      const bg = backgrounds.find((b) => b.background_id === effectiveBgId);
      if (bg && bg.width_mm > 0 && bg.height_mm > 0) {
        const s = Math.min(pageW / bg.width_mm, pageH / bg.height_mm);
        const rw = bg.width_mm * s;
        const rh = bg.height_mm * s;
        underlayRectMm = {
          x: (pageW - rw) * 0.5 + ox,
          y: (pageH - rh) * 0.5 + oy,
          w: rw,
          h: rh,
        };
      }
    }

    engine.updateScene({
      theme,
      paths: activePagePaths,
      config,
      profile,
      blocks,
      placedBlocks: pageSummary?.placed_blocks ?? [],
      missingGlyphs: pageSummary?.missing_glyphs ?? [],
      pageIndex: currentPageIndex,
      underlayUrl,
      underlayOpacity,
      underlayRectMm,
      hasPageBackground,
      activeMargins,
      activeRuled,
      showTravel,
      showBbox,
      showUnderlay,
      showRuled,
      showRegions,
      showMissingGlyphs,
      inkColor,
      stageTool,
      selectedRegionId,
      selectedBlockId,
      selectedObjectId,
      activeMissingGlyphId,
      playbackProgress,
      machineState,
    });
  }, [
    theme,
    activePagePaths,
    config,
    backgrounds,
    layout,
    profile,
    blocks,
    currentDoc,
    currentPageIndex,
    showTravel,
    showBbox,
    showUnderlay,
    showRuled,
    showRegions,
    showMissingGlyphs,
    inkColor,
    stageTool,
    selectedRegionId,
    selectedBlockId,
    selectedObjectId,
    activeMissingGlyphId,
    playbackProgress,
    machineState,
  ]);

  // Fit-to-viewport requests
  useEffect(() => {
    engineRef.current?.fitToViewport();
  }, [fitNonce, config.page.width_mm, config.page.height_mm]);

  // Focus world box tween on Editor <-> Canvas or Missing Glyph jump (waits until new page paths are loaded)
  useEffect(() => {
    if (!cameraFocusRequest) return;
    if (cameraFocusRequest.pageIndex !== currentPageIndex) return;
    if (!activePagePaths || !engineRef.current) return;
    const req = cameraFocusRequest;
    const raf = requestAnimationFrame(() => {
      engineRef.current?.focusWorldBox(req.bboxMm, {
        color: req.color,
        maxZoom: req.maxZoom,
      });
      clearCameraFocus();
    });
    return () => cancelAnimationFrame(raf);
  }, [cameraFocusRequest, currentPageIndex, activePagePaths, clearCameraFocus]);

  // Sync toolbar zoom button clicks into engine camera (guarded against tween fight)
  useEffect(() => {
    if (Math.abs(zoom - lastSyncedZoomRef.current) < 1e-4) return;
    const engine = engineRef.current;
    if (!engine) return;
    const cam = engine.getCamera();
    if (Math.abs(cam.zoom - zoom) > 0.005) {
      const canvas = mainCanvasRef.current;
      if (canvas) {
        lastSyncedZoomRef.current = zoom;
        engine.zoomAtScreenPoint(zoom / cam.zoom, canvas.clientWidth * 0.5, canvas.clientHeight * 0.5);
      }
    } else {
      lastSyncedZoomRef.current = zoom;
    }
  }, [zoom]);

  // Global keyboard shortcuts (including Esc = E-STOP, Space = pan, arrows = nudge/jog)
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const inInput =
        target?.tagName === 'INPUT' ||
        target?.tagName === 'TEXTAREA' ||
        target?.tagName === 'SELECT' ||
        target?.isContentEditable;

      const ms = useMachineStore.getState().machineState;
      const isMoving =
        ms === 'RUNNING' || ms === 'FRAMING' || ms === 'JOGGING' || ms === 'HOLDING';

      if (e.key === 'Escape') {
        if (isMoving) {
          e.preventDefault();
          void useMachineStore.getState().estop();
          return;
        }
        const vp = useViewportStore.getState();
        if (
          vp.activeModal &&
          vp.activeModal !== 'paper-change' &&
          vp.activeModal !== 'font-builder'
        ) {
          vp.openModal(null);
        } else if (!vp.activeModal) {
          if (vp.stageTool === 'draw_region') {
            vp.setStageTool('pan');
          } else if (vp.selectedRegionId) {
            vp.setSelectedRegionId(null);
          } else if (vp.selectedBlockId) {
            vp.setSelectedBlockId(null);
          }
        }
        return;
      }

      if (inInput) return;
      if (useViewportStore.getState().activeModal) return;

      if (e.altKey && (e.key === '[' || e.key === ']')) {
        e.preventDefault();
        const docStore = useDocumentLayoutStore.getState();
        const vp = useViewportStore.getState();
        const allMg = (docStore.layout?.pages ?? []).flatMap((p) => p.missing_glyphs ?? []);
        if (allMg.length > 0) {
          const curIdx = allMg.findIndex((m) => m.id === vp.activeMissingGlyphId);
          const base =
            curIdx >= 0
              ? curIdx
              : Math.max(0, allMg.findIndex((m) => m.page_index >= docStore.currentPageIndex));
          const next = (base + (e.key === '[' ? -1 : 1) + allMg.length) % allMg.length;
          void docStore.focusMissingGlyph(allMg[next]);
        }
        return;
      }

      if (e.ctrlKey || e.metaKey || e.altKey) return;

      if (e.code === 'Space') {
        if (e.shiftKey) {
          e.preventDefault();
          const m = useMachineStore.getState();
          if (m.machineState === 'RUNNING') void m.pauseJob();
          else if (m.machineState === 'PAUSED') void m.resumeJob();
          return;
        }
        e.preventDefault();
        setSpacePressed(true);
        return;
      }

      const vp = useViewportStore.getState();
      const docStore = useDocumentLayoutStore.getState();

      if (e.key === '0') {
        vp.requestFit();
      } else if (e.key === '1') {
        vp.setZoom100();
      } else if (e.key === '=' || e.key === '+') {
        vp.zoomBy(1.15);
      } else if (e.key === '-') {
        vp.zoomBy(0.87);
      } else if (e.key === 'r' || e.key === 'R') {
        if (vp.stageTool === 'draw_region') {
          vp.setStageTool('pan');
        } else {
          vp.setShowRegions(true);
          vp.setStageTool('draw_region');
        }
      } else if (e.key === 'v' || e.key === 'V') {
        vp.setStageTool('pan');
      } else if ((e.key === 'Delete' || e.key === 'Backspace') && vp.selectedRegionId) {
        e.preventDefault();
        docStore.removeRegion(vp.selectedRegionId);
      } else if (e.key === 't' || e.key === 'T') {
        vp.toggleTravel();
      } else if (e.key === 'b' || e.key === 'B') {
        vp.toggleBbox();
      } else if (e.key === 'u' || e.key === 'U') {
        vp.toggleUnderlay();
      } else if (e.key === 'k' || e.key === 'K') {
        vp.setIsPlayingPreview(!vp.isPlayingPreview);
      } else if (e.key === '[') {
        void docStore.setCurrentPageIndex(docStore.currentPageIndex - 1);
      } else if (e.key === ']') {
        void docStore.setCurrentPageIndex(docStore.currentPageIndex + 1);
      } else if (
        vp.selectedBlockId &&
        docStore.config.mode === 'overlay' &&
        ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)
      ) {
        e.preventDefault();
        const step = e.shiftKey ? 2.0 : 0.5;
        const dx = e.key === 'ArrowLeft' ? -step : e.key === 'ArrowRight' ? step : 0;
        const dy = e.key === 'ArrowUp' ? -step : e.key === 'ArrowDown' ? step : 0;
        docStore.nudgeOverlayBlock(vp.selectedBlockId, dx, dy);
      } else if (
        vp.jogKeyboardActive &&
        ms === 'IDLE' &&
        ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'w', 'a', 's', 'd', 'W', 'A', 'S', 'D', 'p', 'P'].includes(e.key)
      ) {
        e.preventDefault();
        const m = useMachineStore.getState();
        if (e.key === 'p' || e.key === 'P') {
          void m.setPen(m.pen === 'up' ? 'down' : 'up');
          return;
        }
        const st = m.jogStepMm;
        const dx =
          e.key === 'ArrowLeft' || e.key === 'a' || e.key === 'A'
            ? -st
            : e.key === 'ArrowRight' || e.key === 'd' || e.key === 'D'
              ? st
              : 0;
        const dy =
          e.key === 'ArrowUp' || e.key === 'w' || e.key === 'W'
            ? -st
            : e.key === 'ArrowDown' || e.key === 's' || e.key === 'S'
              ? st
              : 0;
        if (dx !== 0 || dy !== 0) {
          void m.jog(dx, dy);
        }
      }
    };

    const onKeyUp = (e: KeyboardEvent) => {
      if (e.code === 'Space') {
        setSpacePressed(false);
        setIsPanning(false);
        panStartRef.current = null;
      }
    };

    const onBlur = () => {
      setSpacePressed(false);
      setIsPanning(false);
      panStartRef.current = null;
      engineRef.current?.handlePointerUp();
    };

    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    window.addEventListener('blur', onBlur);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
      window.removeEventListener('blur', onBlur);
    };
  }, [setOverlayBlockNudge]);

  // Attach native non-passive wheel listener so e.preventDefault() reliably prevents page scroll
  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const onNativeWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = mainCanvasRef.current?.getBoundingClientRect();
      if (!rect || !engineRef.current) return;
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const factor = e.deltaY < 0 ? 1.12 : 0.89;
      engineRef.current.zoomAtScreenPoint(factor, sx, sy);
    };
    el.addEventListener('wheel', onNativeWheel, { passive: false });
    return () => {
      el.removeEventListener('wheel', onNativeWheel);
    };
  }, []);

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.target !== mainCanvasRef.current) return;
    const rect = mainCanvasRef.current?.getBoundingClientRect();
    if (!rect || !engineRef.current) return;
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;

    if (spacePressed || e.button === 1) {
      e.preventDefault();
      setIsPanning(true);
      panStartRef.current = { x: e.clientX, y: e.clientY };
      e.currentTarget.setPointerCapture(e.pointerId);
      return;
    }

    if (e.button === 0) {
      const hit = engineRef.current.handlePointerDown(sx, sy);
      if (hit === 'region' || hit === 'block' || hit === 'object') {
        clickCandidateRef.current = null;
        e.currentTarget.setPointerCapture(e.pointerId);
      } else if (stageTool === 'pan') {
        clickCandidateRef.current = { x: e.clientX, y: e.clientY, sx, sy };
        setIsPanning(true);
        panStartRef.current = { x: e.clientX, y: e.clientY };
        e.currentTarget.setPointerCapture(e.pointerId);
      }
    }
  };

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (isPanning && panStartRef.current && engineRef.current) {
      const dx = e.clientX - panStartRef.current.x;
      const dy = e.clientY - panStartRef.current.y;
      panStartRef.current = { x: e.clientX, y: e.clientY };
      engineRef.current.panBy(dx, dy);
      return;
    }
    const rect = mainCanvasRef.current?.getBoundingClientRect();
    if (!rect || !engineRef.current) return;
    engineRef.current.handlePointerMove(e.clientX - rect.left, e.clientY - rect.top);
  };

  const handlePointerUp = (e?: React.PointerEvent<HTMLDivElement>) => {
    if (e && e.currentTarget.hasPointerCapture?.(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
    if (isPanning) {
      setIsPanning(false);
      panStartRef.current = null;
      const cand = clickCandidateRef.current;
      clickCandidateRef.current = null;
      if (e && cand && Math.hypot(e.clientX - cand.x, e.clientY - cand.y) <= 5) {
        engineRef.current?.handleCanvasClick(cand.sx, cand.sy);
      }
    }
    engineRef.current?.handlePointerUp();
  };

  const activeStageIndex = parseTask
    ? Math.max(0, PARSE_STAGES.indexOf(parseTask.stage))
    : -1;

  const appMode = useViewportStore((s) => s.appMode);
  const pageSummary = layout?.pages[currentPageIndex];

  return (
    <main className="stage-wrap">
      <div className="ruler-corner mono">mm</div>
      <canvas ref={topRulerRef} className="ruler-top" />
      <canvas ref={leftRulerRef} className="ruler-left" />

      <div
        ref={viewportRef}
        className={`canvas-viewport ${
          isPanning
            ? 'panning'
            : spacePressed
              ? 'space-ready'
              : stageTool === 'draw_region'
                ? 'draw-region'
                : ''
        }`}
        style={{
          cursor: isPanning
            ? 'grabbing'
            : spacePressed
              ? 'grab'
              : stageTool === 'draw_region'
                ? 'crosshair'
                : hoverCursor || 'grab',
        }}
        onPointerDown={handlePointerDown}
        onDoubleClick={(e) => {
          const rect = mainCanvasRef.current?.getBoundingClientRect();
          if (!rect || !engineRef.current) return;
          engineRef.current.handleDoubleClick(e.clientX - rect.left, e.clientY - rect.top);
        }}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        onPointerLeave={() => {
          handlePointerUp();
          engineRef.current?.handlePointerLeave();
        }}
      >
        <canvas ref={mainCanvasRef} className="stage-canvas" />

        <CanvasImageToolbar />
        <div className="stage-top-stack">
          <StageFloatingBar />
          <MissingGlyphNavigator />
        </div>

        {parseTask && (
          <div className="parse-toast">
            <div className="row-between">
              <span style={{ fontWeight: 700, fontSize: 12.5 }}>
                MinerU Pipeline 文档解析中 ({parseTask.stage})
              </span>
              <span className="mono" style={{ color: 'var(--accent-primary)', fontWeight: 700 }}>
                {Math.round(parseTask.pct)}%
              </span>
            </div>
            <div className="stage-steps">
              {PARSE_STAGES.map((st, idx) => (
                <div
                  key={st}
                  className={`stage-step ${
                    idx < activeStageIndex ? 'done' : idx === activeStageIndex ? 'active' : ''
                  }`}
                  title={st}
                />
              ))}
            </div>
            <div className="row-between" style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}>
              <span>{parseTask.message || '正在处理页面…'}</span>
              {parseTask.page_count ? (
                <span className="mono">
                  {(parseTask.page ?? 0) + 1}/{parseTask.page_count} 页
                </span>
              ) : null}
            </div>
          </div>
        )}

        {!activePagePaths && !parseTask && (
          <div
            style={{
              position: 'absolute',
              bottom: 52,
              left: '50%',
              transform: 'translateX(-50%)',
              background: 'var(--float-bg)',
              backdropFilter: 'blur(12px)',
              border: '1px solid var(--float-border)',
              borderRadius: 12,
              padding: '8px 14px',
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              boxShadow: 'var(--shadow-md)',
              zIndex: 12,
              fontSize: 12,
              color: 'var(--text-secondary)',
              whiteSpace: 'nowrap',
            }}
          >
            {appMode === 'demo' ? (
              <span>演示模式 · 空白画布（已关闭自动预填，可按需选取样例或直接输入测试）</span>
            ) : (
              <>
                <span>空白工作台 · 可上传底稿/文稿、输入文本或拉图配置字段区域</span>
                <button
                  type="button"
                  className="btn btn-xs btn-soft"
                  onClick={() => {
                    useViewportStore.getState().setShowRegions(true);
                    useViewportStore.getState().setStageTool('draw_region');
                    useViewportStore.getState().setLeftTab('refine');
                  }}
                >
                  拉图划区
                </button>
                <button
                  type="button"
                  className="btn btn-xs btn-primary"
                  onClick={() => useViewportStore.getState().openModal('quick-text')}
                >
                  新建文本
                </button>
              </>
            )}
          </div>
        )}

        <PageFilmstrip />

        <div className={`stage-hud-bottom mono ${workspaceView === 'split' ? 'is-split' : ''}`}>
          <span ref={cursorHudRef}>X 0.0 · Y 0.0 mm</span>
          <span style={{ fontFamily: 'var(--font-sans)', opacity: 0.85 }}>
            {stageTool === 'draw_region'
              ? '左键在纸面拖拽拉出区域 · Esc 退出拉图'
              : config.mode === 'overlay'
                ? '左键拖拽工作区或区块 · R 拉图区域 · 滚轮缩放'
                : '左键拖拽工作区 · R 拉图区域 · 滚轮缩放 · Esc 急停'}
          </span>
        </div>
      </div>
    </main>
  );
};
