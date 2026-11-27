import { restClient } from '../../api/restClient';
import type {
  DocBlock,
  DocInline,
  MathPreviewResponse,
} from '../../api/types';

export type UnifiedSegment =
  | {
      kind: 'text_run';
      key: string;
      blocks: DocBlock[];
      startVisIdx: number;
      endVisIdx: number;
    }
  | { kind: 'formula'; key: string; block: DocBlock; visIdx: number }
  | { kind: 'figure'; key: string; block: DocBlock; visIdx: number }
  | { kind: 'table'; key: string; block: DocBlock; visIdx: number };

const TEXTUAL_TYPES = new Set(['heading', 'paragraph', 'list_item', 'caption']);
const LIST_START_RE = /^(?:[（(]\s*\d{1,3}\s*[)）]|\d{1,3}[.、)）．]\s*|[-*•+·]\s+|[a-zA-Z][)）]\s+)/;
const HEADING_LINE_RE = /^(#{1,3})\s+(.+)$/;
const QUOTE_LINE_RE = /^>\s*(.+)$/;
const CAPTION_START_RE = /^(?:图|表|Table|Fig\.?)\s*\d+/i;

export function inlinesToEditableText(inlines?: DocInline[]): string {
  if (!inlines || inlines.length === 0) return '';
  return inlines
    .map((inl) => {
      if (inl.t === 'text') return inl.text || '';
      if (inl.t === 'math') return `$${inl.latex}$`;
      return '\n';
    })
    .join('');
}

function parseSingleLineInlines(line: string): DocInline[] {
  const res: DocInline[] = [];
  const re = /\$\$([\s\S]+?)\$\$|\$([^$\n]+?)\$/g;
  let pos = 0;
  let match: RegExpExecArray | null;
  while ((match = re.exec(line)) !== null) {
    if (match.index > pos) {
      const chunk = line.slice(pos, match.index);
      if (chunk) res.push({ t: 'text', text: chunk });
    }
    const tex = (match[1] ?? match[2] ?? '').trim();
    if (tex) res.push({ t: 'math', latex: tex });
    pos = match.index + match[0].length;
  }
  if (pos < line.length) {
    const tail = line.slice(pos);
    if (tail) res.push({ t: 'text', text: tail });
  }
  return res;
}

export function editableTextToInlines(text: string): DocInline[] {
  const parts = text.replace(/\r\n/g, '\n').split('\n');
  const out: DocInline[] = [];
  for (let i = 0; i < parts.length; i++) {
    if (i > 0) out.push({ t: 'break' });
    out.push(...parseSingleLineInlines(parts[i]));
  }
  return out;
}

export function buildDocumentSegments(visibleBlocks: DocBlock[]): UnifiedSegment[] {
  const segments: UnifiedSegment[] = [];
  let textBuf: DocBlock[] = [];
  let runStart = 0;

  const flushText = (endIdx: number) => {
    if (textBuf.length === 0) return;
    segments.push({
      kind: 'text_run',
      key: `tr-${textBuf[0].block_id}`,
      blocks: textBuf,
      startVisIdx: runStart,
      endVisIdx: endIdx,
    });
    textBuf = [];
  };

  for (let i = 0; i < visibleBlocks.length; i++) {
    const blk = visibleBlocks[i];
    if (TEXTUAL_TYPES.has(blk.type)) {
      if (textBuf.length === 0) runStart = i;
      textBuf.push(blk);
      continue;
    }
    flushText(i - 1);
    if (blk.type === 'formula_block') {
      segments.push({ kind: 'formula', key: blk.block_id, block: blk, visIdx: i });
    } else if (blk.type === 'table') {
      segments.push({ kind: 'table', key: blk.block_id, block: blk, visIdx: i });
    } else {
      segments.push({ kind: 'figure', key: blk.block_id, block: blk, visIdx: i });
    }
  }
  flushText(visibleBlocks.length - 1);
  return segments;
}

export function serializeTextRun(blocks: DocBlock[]): string {
  return blocks
    .map((b) => {
      const txt = inlinesToEditableText(b.inlines);
      if (b.type === 'heading') {
        const lvl = Math.max(1, Math.min(3, b.level || 1));
        return `${'#'.repeat(lvl)} ${txt}`;
      }
      if (b.type === 'caption') {
        return txt.startsWith('>') ? txt : `> ${txt}`;
      }
      return txt;
    })
    .filter((s) => s.length > 0)
    .join('\n\n');
}

export function parseTextRunToBlocks(
  text: string,
  prevBlocks: DocBlock[],
): DocBlock[] {
  const normalized = text.replace(/\r\n/g, '\n').trim();
  if (!normalized) return [];
  const rawChunks = normalized.split(/\n[ \t]*\n+/).map((c) => c.trim()).filter(Boolean);
  const fallbackPage = prevBlocks[0]?.page_index ?? 0;

  const unusedPrev = new Set(prevBlocks.map((_, i) => i));
  const pickPrev = (chunkIdx: number, cleanChunk: string): DocBlock | undefined => {
    const exactBody = cleanChunk.replace(/^#{1,3}\s+/, '').replace(/^>\s*/, '').trim();
    for (const i of unusedPrev) {
      const pTxt = inlinesToEditableText(prevBlocks[i].inlines).trim();
      if (pTxt && pTxt === exactBody) {
        unusedPrev.delete(i);
        return prevBlocks[i];
      }
    }
    if (unusedPrev.has(chunkIdx)) {
      unusedPrev.delete(chunkIdx);
      return prevBlocks[chunkIdx];
    }
    return undefined;
  };

  return rawChunks.map((chunk, idx) => {
    const prev = pickPrev(idx, chunk);
    const baseId =
      prev?.block_id ??
      `ed-${Date.now().toString(36)}-${idx}-${Math.random().toString(36).slice(2, 5)}`;
    const pageIndex = prev?.page_index ?? fallbackPage;
    const bbox = prev?.bbox_mm ?? [20, 30, 185, 45];

    const hMatch = !chunk.includes('\n') ? HEADING_LINE_RE.exec(chunk) : null;
    if (hMatch) {
      return {
        block_id: baseId,
        page_index: pageIndex,
        type: 'heading',
        reading_order: 0,
        level: hMatch[1].length,
        bbox_mm: bbox,
        inlines: editableTextToInlines(hMatch[2].trim()),
      };
    }

    const qMatch = QUOTE_LINE_RE.exec(chunk);
    if (qMatch && !chunk.includes('\n')) {
      return {
        block_id: baseId,
        page_index: pageIndex,
        type: 'caption',
        reading_order: 0,
        level: 1,
        bbox_mm: bbox,
        inlines: editableTextToInlines(qMatch[1].trim()),
      };
    }

    const firstLine = chunk.split('\n')[0].trim();
    if (LIST_START_RE.test(firstLine)) {
      return {
        block_id: baseId,
        page_index: pageIndex,
        type: 'list_item',
        reading_order: 0,
        level: 1,
        bbox_mm: bbox,
        inlines: editableTextToInlines(chunk),
      };
    }

    if (
      prev?.type === 'caption' &&
      CAPTION_START_RE.test(firstLine) &&
      chunk.length <= 80 &&
      !chunk.includes('\n')
    ) {
      return {
        block_id: baseId,
        page_index: pageIndex,
        type: 'caption',
        reading_order: 0,
        level: 1,
        bbox_mm: bbox,
        inlines: editableTextToInlines(chunk),
      };
    }

    return {
      block_id: baseId,
      page_index: pageIndex,
      type: 'paragraph',
      reading_order: 0,
      level: 1,
      bbox_mm: bbox,
      inlines: editableTextToInlines(chunk),
    };
  });
}

const MATH_CACHE = new Map<string, MathPreviewResponse>();
const MATH_INFLIGHT = new Map<string, Promise<MathPreviewResponse>>();

export function getCachedMathPreview(
  latex: string,
  writerId: string | null | undefined,
): Promise<MathPreviewResponse> {
  const key = `${writerId || 'default'}::${latex}`;
  const hit = MATH_CACHE.get(key);
  if (hit) return Promise.resolve(hit);
  const inflight = MATH_INFLIGHT.get(key);
  if (inflight) return inflight;

  const p = restClient
    .previewMath({
      latex: latex || '\\text{ }',
      writer_id: writerId ?? null,
      font_size_mm: 7.0,
      formula_scale: 0.95,
      display: true,
    })
    .then((res) => {
      if (MATH_CACHE.size >= 240) {
        const oldest = MATH_CACHE.keys().next().value;
        if (oldest !== undefined) MATH_CACHE.delete(oldest);
      }
      MATH_CACHE.set(key, res);
      return res;
    })
    .finally(() => {
      MATH_INFLIGHT.delete(key);
    });
  MATH_INFLIGHT.set(key, p);
  return p;
}
