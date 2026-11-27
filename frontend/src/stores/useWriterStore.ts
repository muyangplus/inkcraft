import { create } from 'zustand';
import { restClient } from '../api/restClient';
import type {
  GlyphVariantsResponse,
  HwFontMeta,
  TaskProgressData,
  WriterCoverageResponse,
} from '../api/types';
import { useViewportStore } from './useViewportStore';

export interface WriterStoreState {
  writers: HwFontMeta[];
  activeWriterId: string | null;
  loading: boolean;
  uploading: boolean;
  coverage: WriterCoverageResponse | null;
  /** Cache key: `${writerId}:${char}` */
  glyphCache: Record<string, GlyphVariantsResponse>;
  /** Live progress for font_import / local font builder background task */
  fontBuildTask: TaskProgressData | null;

  fetchWriters: () => Promise<void>;
  selectWriter: (writerId: string) => Promise<void>;
  setActiveWriterLocal: (writerId: string) => void;
  setFontBuildTask: (task: TaskProgressData | null) => void;
  uploadWriterFile: (file: File) => Promise<HwFontMeta | null>;
  deleteWriter: (writerId: string) => Promise<void>;
  fetchCoverage: (writerId?: string, docId?: string) => Promise<void>;
  fetchGlyph: (writerId: string, char: string) => Promise<GlyphVariantsResponse | null>;
}

export const useWriterStore = create<WriterStoreState>((set, get) => ({
  writers: [],
  activeWriterId: null,
  loading: false,
  uploading: false,
  coverage: null,
  glyphCache: {},
  fontBuildTask: null,

  fetchWriters: async () => {
    set({ loading: true });
    try {
      const res = await restClient.listWriters();
      const userWriters = res.writers.filter(
        (w) => !(w.builder || '').includes('generate_demo_writers'),
      );
      const isActiveDemo = Boolean(
        res.active_writer_id &&
          res.writers.find(
            (w) =>
              w.writer_id === res.active_writer_id &&
              (w.builder || '').includes('generate_demo_writers'),
          ),
      );
      let activeId = res.active_writer_id ?? res.writers[0]?.writer_id ?? null;
      if (
        useViewportStore.getState().appMode !== 'demo' &&
        userWriters.length > 0 &&
        (!activeId || isActiveDemo)
      ) {
        activeId = userWriters[0].writer_id;
        void restClient.setActiveWriter(activeId).catch(() => undefined);
      }
      set({ writers: res.writers, activeWriterId: activeId });
      // Preload preview glyphs for writer cards
      for (const w of res.writers) {
        const ch = w.preview_char || '永';
        void get().fetchGlyph(w.writer_id, ch);
      }
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`加载书写人列表失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    } finally {
      set({ loading: false });
    }
  },

  selectWriter: async (writerId) => {
    if (get().activeWriterId === writerId) return;
    try {
      const res = await restClient.setActiveWriter(writerId);
      set({ activeWriterId: res.active_writer_id });
      const w = get().writers.find((x) => x.writer_id === res.active_writer_id);
      if (w) {
        useViewportStore.getState().pushToast(`已热切换书写人：${w.writer_name}`, 'info');
      }
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`切换书写人失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    }
  },

  setActiveWriterLocal: (writerId) => set({ activeWriterId: writerId }),

  setFontBuildTask: (fontBuildTask) => set({ fontBuildTask }),

  uploadWriterFile: async (file) => {
    set({ uploading: true });
    try {
      const res = await restClient.uploadWriter(file);
      if (res.writer) {
        await get().fetchWriters();
        useViewportStore.getState().pushToast(`已导入笔迹字体：${res.writer.writer_name}`, 'success');
        return res.writer;
      }
      if (res.task_id) {
        // Poll task until completion
        for (let i = 0; i < 60; i++) {
          const t = await restClient.getTask(res.task_id);
          if (t.state === 'done') {
            await get().fetchWriters();
            useViewportStore.getState().pushToast('笔迹字体导入校验完成', 'success');
            return null;
          }
          if (t.state === 'failed') {
            throw new Error(t.error || t.message || '导入失败');
          }
          await new Promise((r) => setTimeout(r, 400));
        }
      }
      return null;
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`导入 .hwfont 失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
      return null;
    } finally {
      set({ uploading: false });
    }
  },

  deleteWriter: async (writerId) => {
    try {
      await restClient.deleteWriter(writerId);
      await get().fetchWriters();
      useViewportStore.getState().pushToast('已移除笔迹文件', 'info');
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`删除失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    }
  },

  fetchCoverage: async (writerId, docId) => {
    const id = writerId ?? get().activeWriterId;
    if (!id) return;
    try {
      const cov = await restClient.getWriterCoverage(id, docId);
      set({ coverage: cov });
    } catch {
      // ignore if doc not ready
    }
  },

  fetchGlyph: async (writerId, char) => {
    if (!writerId || !char) return null;
    const key = `${writerId}:${char}`;
    const existing = get().glyphCache[key];
    if (existing) return existing;
    try {
      const data = await restClient.getWriterGlyph(writerId, char, true);
      set((s) => ({ glyphCache: { ...s.glyphCache, [key]: data } }));
      return data;
    } catch {
      return null;
    }
  },
}));
