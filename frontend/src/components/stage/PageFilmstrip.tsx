import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useDocumentLayoutStore } from '../../stores/useDocumentLayoutStore';
import { useViewportStore } from '../../stores/useViewportStore';

function shortRuleTag(label: string | undefined, pageIndex: number, strategy: string): string {
  if (label) {
    if (label.includes('A') && !label.includes('B')) return 'A';
    if (label.includes('B') && !label.includes('A')) return 'B';
    return label.length > 6 ? label.slice(0, 6) : label;
  }
  if (strategy === 'first_and_rest') return pageIndex === 0 ? 'A' : 'B';
  if (strategy === 'odd_even') return (pageIndex + 1) % 2 === 1 ? '奇' : '偶';
  return '';
}

export const PageFilmstrip: React.FC = () => {
  const railRef = useRef<HTMLDivElement>(null);
  const pillRefs = useRef<Record<number, HTMLButtonElement | null>>({});
  const dragRef = useRef<{ active: boolean; startX: number; scrollLeft: number; moved: boolean }>({
    active: false,
    startX: 0,
    scrollLeft: 0,
    moved: false,
  });

  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);
  const [jumpInput, setJumpInput] = useState('1');

  const layout = useDocumentLayoutStore((s) => s.layout);
  const config = useDocumentLayoutStore((s) => s.config);
  const currentPageIndex = useDocumentLayoutStore((s) => s.currentPageIndex);
  const setCurrentPageIndex = useDocumentLayoutStore((s) => s.setCurrentPageIndex);
  const workspaceView = useViewportStore((s) => s.workspaceView);

  const pages = layout?.pages ?? [];

  const updateScrollEdges = useCallback(() => {
    const el = railRef.current;
    if (!el) return;
    setCanScrollLeft(el.scrollLeft > 4);
    setCanScrollRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 4);
  }, []);

  useEffect(() => {
    setJumpInput(String(currentPageIndex + 1));
    const pill = pillRefs.current[currentPageIndex];
    if (pill && typeof pill.scrollIntoView === 'function') {
      pill.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
    }
    const id = window.setTimeout(updateScrollEdges, 180);
    return () => window.clearTimeout(id);
  }, [currentPageIndex, pages.length, updateScrollEdges]);

  useEffect(() => {
    updateScrollEdges();
    window.addEventListener('resize', updateScrollEdges);
    return () => window.removeEventListener('resize', updateScrollEdges);
  }, [pages.length, workspaceView, updateScrollEdges]);

  if (pages.length === 0) return null;

  const scrollRailBy = (delta: number) => {
    const el = railRef.current;
    if (!el) return;
    el.scrollBy({ left: delta, behavior: 'smooth' });
    window.setTimeout(updateScrollEdges, 220);
  };

  const commitJumpPage = () => {
    const num = parseInt(jumpInput, 10);
    if (!Number.isFinite(num)) {
      setJumpInput(String(currentPageIndex + 1));
      return;
    }
    const target = Math.max(0, Math.min(pages.length - 1, num - 1));
    setJumpInput(String(target + 1));
    if (target !== currentPageIndex) {
      void setCurrentPageIndex(target);
    }
  };

  return (
    <div
      className={`page-filmstrip ${workspaceView === 'split' ? 'is-split' : ''}`}
      role="navigation"
      aria-label="页面快速切换"
    >
      <button
        type="button"
        className="filmstrip-nav-btn"
        disabled={!canScrollLeft}
        onClick={() => scrollRailBy(-200)}
        title="向左滚动页签"
      >
        <ChevronLeft size={13} />
      </button>

      <div className={`filmstrip-rail-wrap ${canScrollLeft ? 'fade-l' : ''} ${canScrollRight ? 'fade-r' : ''}`}>
        <div
          ref={railRef}
          className="filmstrip-rail"
          onScroll={updateScrollEdges}
          onWheel={(e) => {
            const el = railRef.current;
            if (!el) return;
            const delta = Math.abs(e.deltaY) >= Math.abs(e.deltaX) ? e.deltaY : e.deltaX;
            if (delta !== 0) {
              el.scrollLeft += delta;
              updateScrollEdges();
            }
          }}
          onPointerDown={(e) => {
            const el = railRef.current;
            if (!el || e.button !== 0) return;
            dragRef.current = {
              active: true,
              startX: e.clientX,
              scrollLeft: el.scrollLeft,
              moved: false,
            };
          }}
          onPointerMove={(e) => {
            const el = railRef.current;
            if (!el || !dragRef.current.active) return;
            const dx = e.clientX - dragRef.current.startX;
            if (Math.abs(dx) > 4) dragRef.current.moved = true;
            if (dragRef.current.moved) {
              el.scrollLeft = dragRef.current.scrollLeft - dx;
              updateScrollEdges();
            }
          }}
          onPointerUp={() => {
            dragRef.current.active = false;
          }}
          onPointerCancel={() => {
            dragRef.current.active = false;
          }}
        >
          {pages.map((p) => {
            const isActive = p.page_index === currentPageIndex;
            const tag = shortRuleTag(p.applied_rule_label, p.page_index, config.page_rules.strategy);
            const missingCount = p.missing_glyphs?.length ?? 0;
            return (
              <button
                key={p.page_index}
                ref={(el) => {
                  pillRefs.current[p.page_index] = el;
                }}
                type="button"
                className={`filmstrip-pill mono ${isActive ? 'active' : ''}`}
                onClick={() => {
                  if (dragRef.current.moved) {
                    dragRef.current.moved = false;
                    return;
                  }
                  void setCurrentPageIndex(p.page_index);
                }}
                title={`第 ${p.page_index + 1} 页${p.applied_rule_label ? ` · ${p.applied_rule_label}` : ''}${
                  missingCount > 0 ? ` · 含 ${missingCount} 处缺字` : ''
                }`}
              >
                <span>P{p.page_index + 1}</span>
                {tag && (
                  <>
                    <span className="filmstrip-rule-dot" />
                    <span style={{ fontFamily: 'var(--font-sans)' }}>{tag}</span>
                  </>
                )}
                {missingCount > 0 && <span className="filmstrip-missing-dot" />}
              </button>
            );
          })}
        </div>
      </div>

      <button
        type="button"
        className="filmstrip-nav-btn"
        disabled={!canScrollRight}
        onClick={() => scrollRailBy(200)}
        title="向右滚动页签"
      >
        <ChevronRight size={13} />
      </button>

      <div className="filmstrip-jump mono" title="输入页码后按回车快速跳转">
        <input
          type="text"
          inputMode="numeric"
          value={jumpInput}
          onChange={(e) => setJumpInput(e.target.value.replace(/[^0-9]/g, ''))}
          onBlur={commitJumpPage}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              commitJumpPage();
              (e.target as HTMLInputElement).blur();
            }
          }}
          aria-label="页码快速跳转"
        />
        <span>/ {pages.length}</span>
      </div>
    </div>
  );
};
