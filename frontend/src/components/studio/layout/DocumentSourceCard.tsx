import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Check, Download, Edit2, Edit3, FilePlus2, FileText, Trash2, Upload, X } from 'lucide-react';
import { restClient } from '../../../api/restClient';
import { useDocumentLayoutStore } from '../../../stores/useDocumentLayoutStore';
import { useViewportStore } from '../../../stores/useViewportStore';

export const DocumentSourceCard: React.FC = () => {
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [renameText, setRenameText] = useState('');

  const documents = useDocumentLayoutStore((s) => s.documents);
  const currentDoc = useDocumentLayoutStore((s) => s.currentDoc);
  const selectDocument = useDocumentLayoutStore((s) => s.selectDocument);
  const openImportPreview = useDocumentLayoutStore((s) => s.openImportPreview);
  const importPreviewLoading = useDocumentLayoutStore((s) => s.importPreviewLoading);
  const renameDocument = useDocumentLayoutStore((s) => s.renameDocument);
  const deleteDocument = useDocumentLayoutStore((s) => s.deleteDocument);

  const appMode = useViewportStore((s) => s.appMode);
  const openModal = useViewportStore((s) => s.openModal);
  const setWorkspaceView = useViewportStore((s) => s.setWorkspaceView);

  useEffect(() => {
    setRenaming(false);
    setRenameText(currentDoc?.source.filename ?? '');
  }, [currentDoc?.doc_id, currentDoc?.source.filename]);

  const userDocs = useMemo(
    () => documents.filter((d) => !d.is_builtin && d.doc_id !== 'doc_demo'),
    [documents],
  );
  const demoDocs = useMemo(
    () => (appMode === 'demo' ? documents.filter((d) => d.is_builtin || d.doc_id === 'doc_demo') : []),
    [documents, appMode],
  );

  const canModifyDoc = Boolean(currentDoc && !currentDoc.is_builtin && currentDoc.doc_id !== 'doc_demo');

  const handleConfirmRename = async () => {
    if (!currentDoc) return;
    const trimmed = renameText.trim();
    if (!trimmed) return;
    const ok = await renameDocument(currentDoc.doc_id, trimmed);
    if (ok) setRenaming(false);
  };

  return (
    <div className="section-card">
      <div className="section-head">
        <span className="section-head-title">
          <FileText size={13} style={{ color: 'var(--accent-primary)' }} />
          文稿项目与来源
        </span>
        <button className="btn btn-xs btn-primary" onClick={() => openModal('quick-text')}>
          <FilePlus2 size={11} /> 速写文本
        </button>
      </div>

      <div className="row-gap" style={{ gap: 5 }}>
        <select
          style={{ flex: 1, minWidth: 0 }}
          value={currentDoc?.doc_id ?? ''}
          onChange={(e) => {
            const v = e.target.value;
            if (!v) {
              useDocumentLayoutStore.getState().clearDocument();
            } else {
              void selectDocument(v);
            }
          }}
        >
          <option value="">空白画布（仅用自定义区域或未选文稿）</option>
          {userDocs.length > 0 && (
            <optgroup label="我的实际文稿">
              {userDocs.map((d) => (
                <option key={d.doc_id} value={d.doc_id}>
                  {d.source.filename} ({d.page_count}页 · {d.source.type.toUpperCase()})
                </option>
              ))}
            </optgroup>
          )}
          {demoDocs.length > 0 && (
            <optgroup label="演示样例（已在关于页开启演示模式）">
              {demoDocs.map((d) => (
                <option key={d.doc_id} value={d.doc_id}>
                  [演示样例] {d.source.filename} ({d.page_count}页)
                </option>
              ))}
            </optgroup>
          )}
        </select>

        {canModifyDoc && (
          <button
            type="button"
            className="btn btn-xs"
            onClick={() => {
              setRenameText(currentDoc?.source.filename ?? '');
              setRenaming((v) => !v);
            }}
            title="重命名当前项目"
          >
            <Edit2 size={11} />
          </button>
        )}

        {canModifyDoc && currentDoc && (
          <button
            type="button"
            className="btn btn-xs btn-danger-outline"
            onClick={() => {
              if (window.confirm(`确认删除文稿项目「${currentDoc.source.filename}」吗？`)) {
                void deleteDocument(currentDoc.doc_id);
              }
            }}
            title="删除当前文稿项目"
          >
            <Trash2 size={11} />
          </button>
        )}
      </div>

      {renaming && currentDoc && (
        <div className="row-gap" style={{ gap: 5 }}>
          <input
            type="text"
            value={renameText}
            onChange={(e) => setRenameText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void handleConfirmRename();
              if (e.key === 'Escape') setRenaming(false);
            }}
            placeholder="输入新的项目名称"
            style={{ flex: 1, fontSize: 11.5, padding: '4px 7px' }}
          />
          <button
            type="button"
            className="btn btn-xs btn-primary"
            onClick={() => void handleConfirmRename()}
          >
            <Check size={11} />
          </button>
          <button type="button" className="btn btn-xs" onClick={() => setRenaming(false)}>
            <X size={11} />
          </button>
        </div>
      )}

      {currentDoc && (
        <div className="row-between" style={{ gap: 6 }}>
          <div className="row-gap" style={{ gap: 5 }}>
            <button
              type="button"
              className="btn btn-xs btn-soft"
              onClick={() => setWorkspaceView('split')}
              title="打开自由编辑 / Markdown 分屏编辑器"
            >
              <Edit3 size={11} /> 分屏编辑
            </button>
            <a
              className="btn btn-xs"
              href={restClient.getDocumentMarkdownDownloadUrl(currentDoc.doc_id)}
              download={`${currentDoc.source.filename}.md`}
              title="导出文档为 Markdown (.md)"
            >
              <Download size={11} /> 导出 .md
            </a>
          </div>
          <button
            type="button"
            className="btn btn-xs"
            onClick={() => useDocumentLayoutStore.getState().clearDocument()}
            title="关闭当前文稿预览"
          >
            关闭文稿
          </button>
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
          const f = e.dataTransfer.files?.[0];
          if (f) void openImportPreview(f);
        }}
      >
        <Upload size={14} />
        <span>
          {importPreviewLoading
            ? '正在生成预解析预览…'
            : '拖入或点击上传 .docx / .pdf / .md / .txt（支持区域裁切与多项目拆分）'}
        </span>
        <input
          ref={fileRef}
          type="file"
          accept=".docx,.pdf,.txt,.md"
          style={{ display: 'none' }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void openImportPreview(f);
            e.target.value = '';
          }}
        />
      </div>
    </div>
  );
};
