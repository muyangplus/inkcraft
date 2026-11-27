import { restClient } from '../../api/restClient';
import {
  normalizeLayoutConfig,
  type DocBlock,
  type DocumentDetail,
  type ImageRenderMode,
} from '../../api/types';
import { useViewportStore } from '../useViewportStore';
import { useWriterStore } from '../useWriterStore';
import {
  cancelPendingCompose,
  enforceUniformSSOT,
  type DocLayoutSliceCreator,
  type DocumentSlice,
} from './storeTypes';

async function pollDocumentParseTask(
  taskId: string,
  set: Parameters<DocLayoutSliceCreator<DocumentSlice>>[0],
): Promise<void> {
  set((s) => ({
    parseTask: s.parseTask ? { ...s.parseTask, task_id: taskId } : null,
  }));
  for (let i = 0; i < 360; i++) {
    const task = await restClient.getTask(taskId);
    set({
      parseTask: {
        task_id: task.task_id,
        kind: task.kind,
        state: task.state,
        stage: task.stage,
        pct: task.pct,
        page: task.page,
        page_count: task.page_count,
        message: task.message,
      },
    });
    if (task.state === 'done') {
      return;
    }
    if (task.state === 'failed') {
      throw new Error(task.error || task.message || '文档解析失败');
    }
    await new Promise((r) => setTimeout(r, 350));
  }
  throw new Error('文档解析超时，请稍后重试');
}

export const createDocumentSlice: DocLayoutSliceCreator<DocumentSlice> = (set, get) => ({
  documents: [],
  currentDoc: null,
  blocks: [],
  markdown: '',
  savingDoc: false,
  parseTask: null,
  importPreview: null,
  importPreviewLoading: false,
  importPreviewCommitting: false,

  bootstrap: async () => {
    try {
      await Promise.all([
        get().fetchPresets(),
        get().fetchBackgrounds(),
        restClient
          .getLayoutDefaults()
          .then((def) => {
            if (def.config) {
              set({ config: enforceUniformSSOT(normalizeLayoutConfig(def.config)) });
            }
          })
          .catch(() => undefined),
      ]);

      let docs: DocumentDetail[] = [];
      try {
        docs = await restClient.listDocuments();
      } catch {
        // ignore offline list error
      }
      set({ documents: docs });
      const userDocs = docs.filter((d) => !d.is_builtin && d.doc_id !== 'doc_demo');
      if (userDocs.length > 0 && useViewportStore.getState().appMode === 'production') {
        await get().selectDocument(userDocs[0].doc_id);
      }
    } catch {
      // ignore boot errors
    }
  },

  clearDocument: () => {
    cancelPendingCompose();
    const vp = useViewportStore.getState();
    vp.setSelectedBlockId(null);
    vp.setSelectedObjectId(null);
    vp.setActiveMissingGlyphId(null);
    set({
      currentDoc: null,
      blocks: [],
      markdown: '',
      layout: null,
      pagePathsCache: {},
      activePagePaths: null,
      currentPageIndex: 0,
      composing: false,
    });
  },

  selectDocument: async (docId) => {
    try {
      const [doc, blocksRes, mdRes] = await Promise.all([
        restClient.getDocument(docId),
        restClient.getDocumentBlocks(docId).catch(() => ({ doc_id: docId, blocks: [] as DocBlock[] })),
        restClient
          .getDocumentMarkdown(docId)
          .catch(() => ({ doc_id: docId, sha256: '', markdown: '' })),
      ]);
      set((s) => ({
        currentDoc: doc,
        blocks: blocksRes.blocks ?? [],
        markdown: mdRes.markdown ?? '',
        currentPageIndex: 0,
        config: {
          ...s.config,
          overlay: {
            ...s.config.overlay,
            blocks: {},
          },
        },
      }));
      const vp = useViewportStore.getState();
      vp.setSelectedBlockId(null);
      vp.setSelectedObjectId(null);
      vp.setActiveMissingGlyphId(null);
      await get().composeNow();
      void useWriterStore.getState().fetchCoverage(undefined, docId);
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`加载文档失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    }
  },

  uploadDocument: async (file) => {
    const modeHint = get().config.mode;
    const isPdf = file.name.toLowerCase().endsWith('.pdf');
    set({
      parseTask: {
        task_id: 'uploading',
        kind: 'parse',
        state: 'running',
        stage: 'upload',
        pct: 5,
        page: 0,
        page_count: 1,
        message: `正在上传 ${file.name}...`,
      },
    });
    try {
      const res = await restClient.uploadDocument(file, modeHint);
      if (res.task_id) {
        await pollDocumentParseTask(res.task_id, set);
      }
      const docs = await restClient.listDocuments().catch(() => get().documents);
      set({ documents: docs, parseTask: null });
      if (isPdf && get().config.mode === 'overlay') {
        useViewportStore.getState().setShowUnderlay(true);
      }
      await get().selectDocument(res.doc_id);
      useViewportStore.getState().pushToast(`文档已解析就绪：${file.name}`, 'success');
    } catch (err) {
      set({ parseTask: null });
      useViewportStore
        .getState()
        .pushToast(`上传解析失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    }
  },

  openImportPreview: async (file) => {
    set({ importPreviewLoading: true });
    try {
      const manifest = await restClient.previewDocument(file);
      set({ importPreview: manifest, importPreviewLoading: false });
      useViewportStore.getState().openModal('document-import');
    } catch (err) {
      set({ importPreviewLoading: false });
      useViewportStore
        .getState()
        .pushToast(`预解析预览失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    }
  },

  commitImportPreview: async (payload) => {
    const preview = get().importPreview;
    if (!preview) return false;
    set({
      importPreviewCommitting: true,
      parseTask: {
        task_id: 'committing',
        kind: 'parse',
        state: 'running',
        stage: 'split',
        pct: 8,
        page: 0,
        page_count: payload.projects.length,
        message: `正在准备切分并解析 ${payload.projects.length} 个项目...`,
      },
    });
    try {
      const res = await restClient.commitDocumentPreview(preview.preview_id, payload);
      useViewportStore.getState().openModal(null);
      set({ importPreview: null, importPreviewCommitting: false });
      if (res.task_id) {
        await pollDocumentParseTask(res.task_id, set);
      }
      const docs = await restClient.listDocuments().catch(() => get().documents);
      set({ documents: docs, parseTask: null });
      if (payload.mode_hint === 'overlay' || preview.file_type === 'pdf') {
        if (get().config.mode === 'overlay') {
          useViewportStore.getState().setShowUnderlay(true);
        }
      }
      const first = res.documents?.[0];
      if (first?.doc_id) {
        await get().selectDocument(first.doc_id);
      }
      useViewportStore
        .getState()
        .pushToast(
          res.documents.length > 1
            ? `已切分导入 ${res.documents.length} 个独立项目（当前打开：${first?.title ?? ''}）`
            : `文档已导入就绪：${first?.title ?? preview.filename}`,
          'success',
        );
      return true;
    } catch (err) {
      set({ importPreviewCommitting: false, parseTask: null });
      useViewportStore
        .getState()
        .pushToast(`导入解析失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
      return false;
    }
  },

  cancelImportPreview: async () => {
    const preview = get().importPreview;
    set({ importPreview: null, importPreviewCommitting: false });
    const vp = useViewportStore.getState();
    if (vp.activeModal === 'document-import') {
      vp.openModal(null);
    }
    if (preview) {
      await restClient.cancelDocumentPreview(preview.preview_id).catch(() => undefined);
    }
  },

  renameDocument: async (docId, filename) => {
    const trimmed = filename.trim();
    if (!trimmed) return false;
    try {
      const res = await restClient.renameDocument(docId, trimmed);
      set((s) => ({
        documents: s.documents.map((d) =>
          d.doc_id === docId ? { ...d, source: { ...d.source, filename: res.filename } } : d,
        ),
        currentDoc:
          s.currentDoc?.doc_id === docId
            ? { ...s.currentDoc, source: { ...s.currentDoc.source, filename: res.filename } }
            : s.currentDoc,
      }));
      useViewportStore.getState().pushToast(`已重命名为「${res.filename}」`, 'success');
      return true;
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`重命名失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
      return false;
    }
  },

  deleteDocument: async (docId) => {
    try {
      await restClient.deleteDocument(docId);
      const remaining = get().documents.filter((d) => d.doc_id !== docId);
      const wasActive = get().currentDoc?.doc_id === docId;
      set({ documents: remaining });
      if (wasActive) {
        const nextUserDoc = remaining.find((d) => !d.is_builtin && d.doc_id !== 'doc_demo');
        if (nextUserDoc) {
          await get().selectDocument(nextUserDoc.doc_id);
        } else {
          get().clearDocument();
        }
      }
      useViewportStore.getState().pushToast('已删除文稿项目', 'info');
      return true;
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`删除文稿失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
      return false;
    }
  },

  createTextDocument: async (title, text) => {
    try {
      const doc = await restClient.createTextDocument(title, text);
      const docs = await restClient.listDocuments().catch(() => [doc, ...get().documents]);
      set({ documents: docs });
      await get().selectDocument(doc.doc_id);
      useViewportStore.getState().pushToast(`已生成手写文稿：${title}`, 'success');
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`创建文本失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    }
  },

  handleTaskProgress: (task) => {
    if (task.kind === 'parse') {
      if (task.state === 'done' || task.state === 'failed') {
        window.setTimeout(() => {
          set((s) => (s.parseTask?.task_id === task.task_id ? { parseTask: null } : s));
        }, 700);
      }
      set({ parseTask: task });
    }
  },

  saveDocumentMarkdown: async (markdown) => {
    const doc = get().currentDoc;
    if (!doc) return false;
    set({ savingDoc: true });
    try {
      const res = await restClient.updateDocumentMarkdown(doc.doc_id, markdown);
      set((s) => ({
        blocks: res.blocks ?? s.blocks,
        markdown: res.markdown ?? markdown,
        currentDoc: s.currentDoc
          ? { ...s.currentDoc, source: { ...s.currentDoc.source, sha256: res.sha256 } }
          : null,
        pagePathsCache: {},
      }));
      await get().composeNow();
      return true;
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`保存 Markdown 失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
      return false;
    } finally {
      set({ savingDoc: false });
    }
  },

  saveDocumentBlocks: async (blocks) => {
    const doc = get().currentDoc;
    if (!doc) return false;
    set({ savingDoc: true });
    try {
      const res = await restClient.replaceDocumentBlocks(doc.doc_id, blocks);
      set((s) => ({
        blocks: res.blocks ?? blocks,
        markdown: res.markdown ?? s.markdown,
        currentDoc: s.currentDoc
          ? { ...s.currentDoc, source: { ...s.currentDoc.source, sha256: res.sha256 } }
          : null,
        pagePathsCache: {},
      }));
      await get().composeNow();
      return true;
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`保存文档结构失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
      return false;
    } finally {
      set({ savingDoc: false });
    }
  },

  patchDocumentBlock: async (blockId, patch) => {
    const doc = get().currentDoc;
    if (!doc) return false;
    set({ savingDoc: true });
    try {
      const res = await restClient.patchDocumentBlock(doc.doc_id, blockId, patch);
      set((s) => ({
        blocks: res.block
          ? s.blocks.map((b) => (b.block_id === blockId ? res.block! : b))
          : s.blocks,
        markdown: res.markdown ?? s.markdown,
        currentDoc: s.currentDoc
          ? { ...s.currentDoc, source: { ...s.currentDoc.source, sha256: res.sha256 } }
          : null,
        pagePathsCache: {},
      }));
      await get().composeNow();
      return true;
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`更新对象失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
      return false;
    } finally {
      set({ savingDoc: false });
    }
  },

  applyGlobalImageStyle: async (mode) => {
    set((s) => ({
      config: {
        ...s.config,
        chart: { ...s.config.chart, image_render_mode: mode },
      },
      pagePathsCache: {},
    }));
    const doc = get().currentDoc;
    if (doc) {
      try {
        const res = await restClient.applyGlobalImageStyle(doc.doc_id, mode);
        set((s) => ({
          blocks: res.blocks ?? s.blocks,
          markdown: res.markdown ?? s.markdown,
          currentDoc: s.currentDoc
            ? { ...s.currentDoc, source: { ...s.currentDoc.source, sha256: res.sha256 } }
            : null,
        }));
      } catch (err) {
        useViewportStore
          .getState()
          .pushToast(`应用图片风格失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
      }
    }
    await get().composeNow();
    const labelMap: Record<ImageRenderMode, string> = {
      inherit: '跟随全局',
      major_outline: '仅主要外轮廓',
      outline: '仅画轮廓',
      hatch: '单向阴影',
      crosshatch: '交叉阴影',
      sketch: '素描排线',
      skip: '跳过不画',
    };
    useViewportStore.getState().pushToast(`已将全部插图风格设为「${labelMap[mode]}」`, 'success');
  },

  reRecognizeFormulaBlock: async (blockId) => {
    const doc = get().currentDoc;
    if (!doc) return null;
    try {
      const res = await restClient.recognizeFormulaBlock(doc.doc_id, blockId);
      set((s) => ({
        blocks: res.block
          ? s.blocks.map((b) => (b.block_id === blockId ? res.block! : b))
          : s.blocks,
        markdown: res.markdown ?? s.markdown,
        currentDoc: s.currentDoc
          ? { ...s.currentDoc, source: { ...s.currentDoc.source, sha256: res.sha256 } }
          : null,
        pagePathsCache: {},
      }));
      await get().composeNow();
      return res.block ?? null;
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`公式识别失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
      return null;
    }
  },

  uploadDocumentAsset: async (file) => {
    const doc = get().currentDoc;
    if (!doc) return null;
    try {
      return await restClient.uploadDocumentAsset(doc.doc_id, file);
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`上传插图失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
      return null;
    }
  },
});
