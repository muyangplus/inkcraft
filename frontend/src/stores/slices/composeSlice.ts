import { restClient } from '../../api/restClient';
import type { PlacedBlockBox } from '../../api/types';
import { decodeF32Paths, type DecodedPagePaths } from '../../canvas/f32PathDecoder';
import { useViewportStore } from '../useViewportStore';
import { useWriterStore } from '../useWriterStore';
import {
  currentComposeSeq,
  nextComposeSeq,
  type ComposeSlice,
  type DocLayoutSliceCreator,
} from './storeTypes';

const MAX_PAGE_CACHE_ENTRIES = 24;

export const createComposeSlice: DocLayoutSliceCreator<ComposeSlice> = (set, get) => ({
  layout: null,
  currentPageIndex: 0,
  pagePathsCache: {},
  activePagePaths: null,
  composing: false,

  composeNow: async (overrideWriterId) => {
    const doc = get().currentDoc;
    const cfg = get().config;
    const hasActiveFields = cfg.regions.some(
      (r) => r.enabled && r.role === 'field' && r.text.trim().length > 0,
    );
    if (!doc && !hasActiveFields) {
      set({ layout: null, activePagePaths: null, pagePathsCache: {}, composing: false });
      return;
    }
    const writerId =
      overrideWriterId !== undefined
        ? overrideWriterId
        : useWriterStore.getState().activeWriterId;

    const mySeq = nextComposeSeq();
    set({ composing: true });

    try {
      const created = await restClient.createLayout(doc ? doc.doc_id : null, writerId, cfg);
      if (created.task_id) {
        let composeDone = false;
        for (let i = 0; i < 500; i++) {
          if (mySeq !== currentComposeSeq()) return;
          const t = await restClient.getTask(created.task_id);
          if (mySeq !== currentComposeSeq()) return;
          if (t.state === 'done') {
            composeDone = true;
            break;
          }
          if (t.state === 'failed') {
            throw new Error(t.error || t.message || '排版失败');
          }
          await new Promise((r) => setTimeout(r, 120));
        }
        if (!composeDone) {
          throw new Error('排版计算超时，请稍后重试');
        }
      }
      if (mySeq !== currentComposeSeq()) return;

      const detail = await restClient.getLayout(created.layout_id);
      if (mySeq !== currentComposeSeq()) return;

      const nextPageIdx = Math.min(get().currentPageIndex, Math.max(0, detail.page_count - 1));
      set({ layout: detail, currentPageIndex: nextPageIdx });
      await get().ensurePagePaths(detail.layout_id, nextPageIdx);
    } catch (err) {
      if (mySeq === currentComposeSeq()) {
        useViewportStore
          .getState()
          .pushToast(`排版计算失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
      }
    } finally {
      if (mySeq === currentComposeSeq()) {
        set({ composing: false });
      }
    }
  },

  setCurrentPageIndex: async (pageIndex) => {
    const layout = get().layout;
    if (!layout) return;
    const clamped = Math.max(0, Math.min(layout.page_count - 1, pageIndex));
    set({ currentPageIndex: clamped });
    // Keep selectedObjectId intact so cross-page Editor <-> Canvas jump keeps block highlighted
    useViewportStore.getState().setSelectedBlockId(null);
    await get().ensurePagePaths(layout.layout_id, clamped);
  },

  ensurePagePaths: async (layoutId, pageIndex) => {
    const key = `${layoutId}:${pageIndex}`;
    const cache = get().pagePathsCache;
    const cached = cache[key];
    if (cached) {
      const cur = get();
      const keys = Object.keys(cache);
      const isMostRecent = keys[keys.length - 1] === key;
      if (!isMostRecent) {
        const refreshed = { ...cache };
        delete refreshed[key];
        refreshed[key] = cached;
        set({
          pagePathsCache: refreshed,
          activePagePaths:
            cur.layout?.layout_id === layoutId && cur.currentPageIndex === pageIndex
              ? cached
              : cur.activePagePaths,
        });
      } else if (cur.layout?.layout_id === layoutId && cur.currentPageIndex === pageIndex) {
        set({ activePagePaths: cached });
      }
      return cached;
    }

    try {
      const res = await restClient.getPagePathsF32(layoutId, pageIndex);
      const decoded = decodeF32Paths(res.buffer, {
        widthMm: res.widthMm,
        heightMm: res.heightMm,
        bbox: res.bbox,
      });
      set((s) => {
        const nextCache: Record<string, DecodedPagePaths> = { ...s.pagePathsCache };
        delete nextCache[key];
        nextCache[key] = decoded;
        const keys = Object.keys(nextCache);
        while (keys.length > MAX_PAGE_CACHE_ENTRIES) {
          const oldest = keys.shift();
          if (oldest) delete nextCache[oldest];
        }
        return {
          pagePathsCache: nextCache,
          activePagePaths:
            s.layout?.layout_id === layoutId && s.currentPageIndex === pageIndex
              ? decoded
              : s.activePagePaths,
        };
      });
      return decoded;
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`拉取路径数据失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
      return null;
    }
  },

  focusBlockOnCanvas: async (blockId) => {
    const { layout, blocks, setCurrentPageIndex } = get();
    const vp = useViewportStore.getState();
    if (vp.workspaceView === 'editor') {
      vp.setWorkspaceView('split');
    }
    vp.setSelectedObjectId(blockId);

    const pages = layout?.pages ?? [];
    let placed: PlacedBlockBox | undefined;
    let targetPage = -1;
    for (const p of pages) {
      const hit = p.placed_blocks?.find((pb) => pb.block_id === blockId);
      if (hit) {
        placed = hit;
        targetPage = p.page_index;
        break;
      }
    }

    const rawBlk = blocks.find((b) => b.block_id === blockId);
    if (!placed && rawBlk) {
      const snippet = (
        rawBlk.latex ||
        (rawBlk.inlines ?? [])
          .map((i) => (i.t === 'text' ? i.text : i.t === 'math' ? i.latex : ' '))
          .join('')
      )
        .replace(/\s+/g, '')
        .slice(0, 12);
      if (snippet.length >= 2) {
        for (const p of pages) {
          const hit = p.placed_blocks?.find((pb) =>
            pb.label.replace(/\s+/g, '').includes(snippet),
          );
          if (hit) {
            placed = hit;
            targetPage = p.page_index;
            break;
          }
        }
      }
    }

    if (placed && targetPage >= 0) {
      if (get().currentPageIndex !== targetPage) {
        await setCurrentPageIndex(targetPage);
      } else {
        await get().ensurePagePaths(layout!.layout_id, targetPage);
      }
      useViewportStore.getState().requestCameraFocus({
        pageIndex: targetPage,
        bboxMm: placed.bbox_mm,
        blockId,
        color: '#4F46E5',
        maxZoom: 2.2,
      });
      return;
    }

    if (rawBlk && typeof rawBlk.page_index === 'number') {
      const pIdx = Math.max(0, Math.min((layout?.page_count ?? 1) - 1, rawBlk.page_index));
      if (get().currentPageIndex !== pIdx) {
        await setCurrentPageIndex(pIdx);
      }
      useViewportStore.getState().requestCameraFocus({
        pageIndex: pIdx,
        bboxMm: rawBlk.bbox_mm ?? [20, 40, 180, 60],
        blockId,
        color: '#4F46E5',
        maxZoom: 2.0,
      });
      return;
    }

    vp.pushToast('该内容块尚未在当前排版页生成定位框', 'info');
  },

  focusMissingGlyph: async (mg) => {
    const vp = useViewportStore.getState();
    vp.setShowMissingGlyphs(true);
    vp.setActiveMissingGlyphId(mg.id);
    if (mg.block_id) {
      vp.setSelectedObjectId(mg.block_id);
    }
    if (vp.workspaceView === 'editor') {
      vp.setWorkspaceView('split');
    }
    if (get().currentPageIndex !== mg.page_index) {
      await get().setCurrentPageIndex(mg.page_index);
    }
    useViewportStore.getState().requestCameraFocus({
      pageIndex: mg.page_index,
      bboxMm: mg.bbox_mm,
      missingId: mg.id,
      blockId: mg.block_id || undefined,
      color: '#DC2626',
      maxZoom: 2.8,
    });
  },
});
