import React, { useState } from 'react';
import { FilePlus2, X } from 'lucide-react';
import { useDocumentLayoutStore } from '../../stores/useDocumentLayoutStore';
import { useViewportStore } from '../../stores/useViewportStore';

const SAMPLE_TEXT = `# 实验记录：单线手写与微扰分析

本系统直接调用活动书写人的单线笔迹进行流式排版，支持行内公式 $E = mc^2$ 与居中公式：

$$F(x) = \\int_{0}^{L} \\frac{\\alpha x^2 + \\beta}{\\sqrt{1 + k^2}} dx$$

| 编号 | 角度 θ | 实测力 F(N) | 误差 |
| --- | --- | --- | --- |
| 01 | 15° | 2.48 | 0.6% |
| 02 | 30° | 4.91 | 0.4% |
| 03 | 45° | 6.95 | 0.5% |

通过字号抖动、基线正弦起伏与同字异形防连重，消除机械重复感。`;

export const QuickTextModal: React.FC = () => {
  const activeModal = useViewportStore((s) => s.activeModal);
  const openModal = useViewportStore((s) => s.openModal);
  const createTextDocument = useDocumentLayoutStore((s) => s.createTextDocument);

  const [title, setTitle] = useState('手写实验笔记');
  const [text, setText] = useState(SAMPLE_TEXT);
  const [submitting, setSubmitting] = useState(false);

  if (activeModal !== 'quick-text') return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    setSubmitting(true);
    try {
      await createTextDocument(title.trim() || '手写文稿', text);
      openModal(null);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={() => openModal(null)}>
      <div className="modal-box" style={{ width: 580 }} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div className="modal-title">
            <FilePlus2 size={15} /> 快速输入手写文稿 (支持 Markdown 标题 / $LaTeX$ 公式 / 表格)
          </div>
          <button className="btn btn-sm" onClick={() => openModal(null)}>
            <X size={13} /> 关闭
          </button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            <div>
              <div className="ctrl-label" style={{ marginBottom: 4 }}>
                <span>文稿标题</span>
              </div>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="输入文档名称"
              />
            </div>
            <div>
              <div className="ctrl-label" style={{ marginBottom: 4 }}>
                <span>正文内容（支持 # 标题、$行内公式$、$$块级公式$$、| 表格 |）</span>
              </div>
              <textarea
                rows={12}
                className="mono"
                value={text}
                onChange={(e) => setText(e.target.value)}
                style={{ fontSize: 12, lineHeight: 1.5 }}
              />
            </div>
          </div>
          <div className="modal-foot">
            <button type="button" className="btn" onClick={() => openModal(null)}>
              取消
            </button>
            <button type="submit" className="btn btn-primary" disabled={submitting || !text.trim()}>
              {submitting ? '正在生成排版…' : '生成手写路径'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
