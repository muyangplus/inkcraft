import React, { useMemo } from 'react';

function escHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const GREEK_MAP: Record<string, string> = {
  alpha: 'α', beta: 'β', gamma: 'γ', delta: 'δ', epsilon: 'ϵ', varepsilon: 'ε',
  zeta: 'ζ', eta: 'η', theta: 'θ', vartheta: 'ϑ', iota: 'ι', kappa: 'κ',
  lambda: 'λ', mu: 'μ', nu: 'ν', xi: 'ξ', pi: 'π', varpi: 'ϖ',
  rho: 'ρ', varrho: 'ϱ', sigma: 'σ', varsigma: 'ς', tau: 'τ', upsilon: 'υ',
  phi: 'ϕ', varphi: 'φ', chi: 'χ', psi: 'ψ', omega: 'ω',
  Gamma: 'Γ', Delta: 'Δ', Theta: 'Θ', Lambda: 'Λ', Xi: 'Ξ', Pi: 'Π',
  Sigma: 'Σ', Upsilon: 'Υ', Phi: 'Φ', Psi: 'Ψ', Omega: 'Ω',
  infty: '∞', partial: '∂', nabla: '∇',
};

const OPERATOR_MAP: Record<string, string> = {
  times: '×', cdot: '·', div: '÷', pm: '±', mp: '∓', ast: '∗', star: '⋆',
  le: '≤', leq: '≤', ge: '≥', geq: '≥', ne: '≠', neq: '≠',
  approx: '≈', equiv: '≡', sim: '∼', simeq: '≃', cong: '≅', propto: '∝',
  lt: '<', gt: '>', ll: '≪', gg: '≫',
  to: '→', rightarrow: '→', leftarrow: '←', leftrightarrow: '↔',
  Rightarrow: '⇒', Leftarrow: '⇐', Leftrightarrow: '⇔', mapsto: '↦',
  in: '∈', notin: '∉', subset: '⊂', subseteq: '⊆', supset: '⊃', cup: '∪', cap: '∩',
  forall: '∀', exists: '∃', neg: '¬', land: '∧', lor: '∨',
  cdots: '⋯', ldots: '…', vdots: '⋮', ddots: '⋱', prime: '′',
  '%': '%', '&': '&', $: '$', '#': '#', _: '_', '{': '{', '}': '}',
  '|': '∥', ' ': ' ', ',': '\u2009', ';': '\u2005', ':': '\u2005', quad: '\u2001', qquad: '\u2001\u2001',
};

const BIG_OPS: Record<string, string> = {
  sum: '∑', prod: '∏', coprod: '∐',
  int: '∫', iint: '∬', iiint: '∭', oint: '∮',
  bigcup: '⋃', bigcap: '⋂', bigoplus: '⨁', bigotimes: '⨂',
};

const NAMED_FUNCS = new Set([
  'sin', 'cos', 'tan', 'cot', 'sec', 'csc',
  'arcsin', 'arccos', 'arctan', 'sinh', 'cosh', 'tanh',
  'log', 'ln', 'lg', 'exp', 'lim', 'limsup', 'liminf',
  'max', 'min', 'sup', 'inf', 'arg', 'det', 'dim', 'gcd', 'ker', 'deg',
]);

const UNDER_OVER_FUNCS = new Set(['lim', 'limsup', 'liminf', 'max', 'min', 'sup', 'inf']);

const ACCENTS: Record<string, string> = {
  bar: '¯', overline: '¯', hat: '^', widehat: '^',
  tilde: '~', widetilde: '~', vec: '→', dot: '˙', ddot: '¨', underline: '_',
};

type Tok =
  | { kind: 'cmd'; name: string }
  | { kind: 'sym'; ch: string }
  | { kind: 'num'; val: string }
  | { kind: 'ident'; val: string }
  | { kind: 'textch'; val: string };

function tokenizeLatex(src: string, textChunks: string[]): Tok[] {
  const toks: Tok[] = [];
  let i = 0;
  const n = src.length;
  while (i < n) {
    const ch = src[i];
    if (ch === ' ' || ch === '\t' || ch === '\r' || ch === '\n') {
      i += 1;
      continue;
    }
    if (src.startsWith('\\__TEXTCHUNK', i)) {
      const endPos = src.indexOf('__', i + 12);
      if (endPos > i) {
        const idxNum = Number(src.slice(i + 12, endPos));
        toks.push({ kind: 'textch', val: textChunks[idxNum] ?? '' });
        i = endPos + 2;
        continue;
      }
    }
    if (ch === '\\') {
      if (i + 1 < n && src[i + 1] === '\\') {
        toks.push({ kind: 'cmd', name: '\\\\' });
        i += 2;
        continue;
      }
      if (i + 1 < n && !/[a-zA-Z]/.test(src[i + 1])) {
        toks.push({ kind: 'cmd', name: src[i + 1] });
        i += 2;
        continue;
      }
      let j = i + 1;
      while (j < n && /[a-zA-Z]/.test(src[j])) j += 1;
      toks.push({ kind: 'cmd', name: src.slice(i + 1, j) });
      i = j;
      continue;
    }
    if (ch === '{' || ch === '}' || ch === '[' || ch === ']' || ch === '_' || ch === '^' || ch === '&') {
      toks.push({ kind: 'sym', ch });
      i += 1;
      continue;
    }
    if (/[0-9]/.test(ch)) {
      let j = i;
      while (j < n && /[0-9.]/.test(src[j])) j += 1;
      toks.push({ kind: 'num', val: src.slice(i, j) });
      i = j;
      continue;
    }
    if (/[a-zA-Z]/.test(ch)) {
      toks.push({ kind: 'ident', val: ch });
      i += 1;
      continue;
    }
    if (/[\u4e00-\u9fff]/.test(ch)) {
      let j = i;
      while (j < n && /[\u4e00-\u9fff]/.test(src[j])) j += 1;
      toks.push({ kind: 'textch', val: src.slice(i, j) });
      i = j;
      continue;
    }
    toks.push({ kind: 'sym', ch });
    i += 1;
  }
  return toks;
}

function readBracedRaw(src: string, startIdx: number): { content: string; nextIdx: number } {
  let i = startIdx;
  while (i < src.length && /\s/.test(src[i])) i += 1;
  if (i >= src.length || src[i] !== '{') {
    return { content: src[i] ?? '', nextIdx: Math.min(src.length, i + 1) };
  }
  let depth = 1;
  let j = i + 1;
  while (j < src.length && depth > 0) {
    if (src[j] === '\\' && j + 1 < src.length) {
      j += 2;
      continue;
    }
    if (src[j] === '{') depth += 1;
    else if (src[j] === '}') depth -= 1;
    j += 1;
  }
  return { content: src.slice(i + 1, Math.max(i + 1, j - 1)), nextIdx: j };
}

function preprocessRawTextArgs(raw: string): string {
  // Preserve spaces cleanly inside `\text{...}`, `\mathrm{...}`, etc. by collapsing to tokens
  return raw.trim();
}

function extractTextMacroContent(src: string, cmdNames: Set<string>): { cleaned: string; textChunks: string[] } {
  const chunks: string[] = [];
  let out = '';
  let i = 0;
  while (i < src.length) {
    if (src[i] === '\\') {
      let j = i + 1;
      while (j < src.length && /[a-zA-Z]/.test(src[j])) j += 1;
      const name = src.slice(i + 1, j);
      if (cmdNames.has(name)) {
        const { content, nextIdx } = readBracedRaw(src, j);
        const idx = chunks.length;
        chunks.push(preprocessRawTextArgs(content));
        out += `\\__TEXTCHUNK${idx}__`;
        i = nextIdx;
        continue;
      }
    }
    out += src[i];
    i += 1;
  }
  return { cleaned: out, textChunks: chunks };
}

class LatexMathParser {
  private pos = 0;
  constructor(
    private readonly toks: Tok[],
    private readonly display: boolean,
  ) {}

  private peek(): Tok | undefined {
    return this.toks[this.pos];
  }

  private peekIsSym(ch: string): boolean {
    const p = this.toks[this.pos];
    return p?.kind === 'sym' && p.ch === ch;
  }

  private peekIsCmd(name: string): boolean {
    const p = this.toks[this.pos];
    return p?.kind === 'cmd' && p.name === name;
  }

  private consume(): Tok | undefined {
    return this.toks[this.pos++];
  }

  parseSequence(stopKinds?: Set<string>, stopCmds?: Set<string>): string {
    const out: string[] = [];
    while (this.pos < this.toks.length) {
      const t = this.peek()!;
      if (t.kind === 'sym' && stopKinds?.has(t.ch)) break;
      if (t.kind === 'cmd' && stopCmds?.has(t.name)) break;
      out.push(this.parseWithScripts());
    }
    if (out.length === 0) return '<mrow></mrow>';
    if (out.length === 1) return out[0];
    return `<mrow>${out.join('')}</mrow>`;
  }

  private parseWithScripts(): string {
    const atom = this.parseAtom();
    let sub: string | null = null;
    let sup: string | null = null;

    while (this.pos < this.toks.length) {
      const t = this.peek()!;
      if (t.kind === 'sym' && t.ch === '_' && sub === null) {
        this.consume();
        sub = this.parseScriptArg();
      } else if (t.kind === 'sym' && t.ch === '^' && sup === null) {
        this.consume();
        sup = this.parseScriptArg();
      } else {
        break;
      }
    }

    if (sub === null && sup === null) return atom.ml;

    const useLimits = this.display && atom.preferLimits;
    if (sub !== null && sup !== null) {
      const tag = useLimits ? 'munderover' : 'msubsup';
      return `<${tag}>${atom.ml}${sub}${sup}</${tag}>`;
    }
    if (sub !== null) {
      const tag = useLimits ? 'munder' : 'msub';
      return `<${tag}>${atom.ml}${sub}</${tag}>`;
    }
    const tag = useLimits ? 'mover' : 'msup';
    return `<${tag}>${atom.ml}${sup}</${tag}>`;
  }

  private parseScriptArg(): string {
    const t = this.peek();
    if (!t) return '<mrow></mrow>';
    if (t.kind === 'sym' && t.ch === '{') {
      return this.parseBracedGroup();
    }
    return this.parseAtom().ml;
  }

  private parseBracedGroup(): string {
    if (this.peekIsSym('{')) {
      this.consume();
      const inner = this.parseSequence(new Set(['}']));
      if (this.peekIsSym('}')) {
        this.consume();
      }
      return inner;
    }
    return this.parseAtom().ml;
  }

  private parseOptionalBracket(): string | null {
    if (this.peekIsSym('[')) {
      this.consume();
      const inner = this.parseSequence(new Set([']']));
      if (this.peekIsSym(']')) {
        this.consume();
      }
      return inner;
    }
    return null;
  }

  private readRawNameGroup(): string {
    if (this.peekIsSym('{')) {
      this.consume();
      const parts: string[] = [];
      while (this.pos < this.toks.length) {
        const cur = this.consume()!;
        if (cur.kind === 'sym' && cur.ch === '}') break;
        if (cur.kind === 'ident' || cur.kind === 'num') parts.push(cur.val);
        else if (cur.kind === 'sym') parts.push(cur.ch);
      }
      return parts.join('').trim();
    }
    return '';
  }

  private readDelimiter(): string {
    const t = this.consume();
    if (!t) return '';
    if (t.kind === 'sym') return t.ch === '.' ? '' : t.ch;
    if (t.kind === 'cmd') {
      if (t.name === '{' || t.name === '}' || t.name === '|') {
        return OPERATOR_MAP[t.name] ?? t.name;
      }
      if (t.name === 'langle') return '⟨';
      if (t.name === 'rangle') return '⟩';
      if (t.name === 'lfloor') return '⌊';
      if (t.name === 'rfloor') return '⌋';
      if (t.name === 'lceil') return '⌈';
      if (t.name === 'rceil') return '⌉';
    }
    return '';
  }

  private parseEnvironment(envName: string): string {
    const rows: string[][] = [[]];
    while (this.pos < this.toks.length) {
      const t = this.peek()!;
      if (t.kind === 'cmd' && t.name === 'end') {
        this.consume();
        this.readRawNameGroup();
        break;
      }
      if (t.kind === 'cmd' && t.name === '\\\\') {
        this.consume();
        rows.push([]);
        continue;
      }
      if (t.kind === 'sym' && t.ch === '&') {
        this.consume();
        if (this.peekIsSym('&')) {
          rows[rows.length - 1].push('');
        }
        continue;
      }
      const cell = this.parseSequence(new Set(['&']), new Set(['\\\\', 'end']));
      rows[rows.length - 1].push(cell);
    }

    const rowXml = rows
      .filter((r) => r.length > 0)
      .map(
        (r) =>
          `<mtr>${r.map((c) => `<mtd>${c || '<mrow></mrow>'}</mtd>`).join('')}</mtr>`,
      )
      .join('');
    const table = `<mtable>${rowXml}</mtable>`;
    if (envName === 'pmatrix') return `<mrow><mo>(</mo>${table}<mo>)</mo></mrow>`;
    if (envName === 'bmatrix') return `<mrow><mo>[</mo>${table}<mo>]</mo></mrow>`;
    if (envName === 'Bmatrix') return `<mrow><mo>{</mo>${table}<mo>}</mo></mrow>`;
    if (envName === 'vmatrix') return `<mrow><mo>|</mo>${table}<mo>|</mo></mrow>`;
    if (envName === 'cases') return `<mrow><mo stretchy="true">{</mo>${table}</mrow>`;
    return table;
  }

  private parseAtom(): { ml: string; preferLimits: boolean } {
    const t = this.consume();
    if (!t) return { ml: '<mrow></mrow>', preferLimits: false };

    if (t.kind === 'num') {
      return { ml: `<mn>${escHtml(t.val)}</mn>`, preferLimits: false };
    }
    if (t.kind === 'ident') {
      return { ml: `<mi>${escHtml(t.val)}</mi>`, preferLimits: false };
    }
    if (t.kind === 'textch') {
      return { ml: `<mtext>${escHtml(t.val)}</mtext>`, preferLimits: false };
    }
    if (t.kind === 'sym') {
      if (t.ch === '{') {
        const inner = this.parseSequence(new Set(['}']));
        if (this.peekIsSym('}')) this.consume();
        return { ml: inner, preferLimits: false };
      }
      return { ml: `<mo>${escHtml(t.ch)}</mo>`, preferLimits: false };
    }

    // Command tokens
    const cmd = t.name;

    if (cmd === 'frac' || cmd === 'dfrac' || cmd === 'tfrac' || cmd === 'cfrac') {
      const num = this.parseBracedGroup();
      const den = this.parseBracedGroup();
      return { ml: `<mfrac>${num}${den}</mfrac>`, preferLimits: false };
    }

    if (cmd === 'sqrt') {
      const nRoot = this.parseOptionalBracket();
      const body = this.parseBracedGroup();
      if (nRoot) {
        return { ml: `<mroot>${body}${nRoot}</mroot>`, preferLimits: false };
      }
      return { ml: `<msqrt>${body}</msqrt>`, preferLimits: false };
    }

    if (cmd === 'left') {
      const lDelim = this.readDelimiter();
      const inner = this.parseSequence(undefined, new Set(['right']));
      let rDelim = '';
      if (this.peekIsCmd('right')) {
        this.consume();
        rDelim = this.readDelimiter();
      }
      const lTag = lDelim ? `<mo stretchy="true">${escHtml(lDelim)}</mo>` : '';
      const rTag = rDelim ? `<mo stretchy="true">${escHtml(rDelim)}</mo>` : '';
      return { ml: `<mrow>${lTag}${inner}${rTag}</mrow>`, preferLimits: false };
    }

    if (cmd === 'begin') {
      const envName = this.readRawNameGroup();
      return { ml: this.parseEnvironment(envName), preferLimits: false };
    }

    if (cmd === 'limits') {
      return this.parseAtom();
    }

    if (cmd in ACCENTS) {
      const base = this.parseBracedGroup();
      const sym = ACCENTS[cmd];
      const tag = cmd === 'underline' ? 'munder' : 'mover';
      return {
        ml: `<${tag} accent="true">${base}<mo>${escHtml(sym)}</mo></${tag}>`,
        preferLimits: false,
      };
    }

    if (cmd in BIG_OPS) {
      return { ml: `<mo largeop="true">${escHtml(BIG_OPS[cmd])}</mo>`, preferLimits: cmd !== 'int' && cmd !== 'iint' && cmd !== 'iiint' && cmd !== 'oint' };
    }

    if (NAMED_FUNCS.has(cmd)) {
      return { ml: `<mi mathvariant="normal">${escHtml(cmd)}</mi>`, preferLimits: UNDER_OVER_FUNCS.has(cmd) };
    }

    if (cmd in GREEK_MAP) {
      return { ml: `<mi mathvariant="normal">${escHtml(GREEK_MAP[cmd])}</mi>`, preferLimits: false };
    }

    if (cmd in OPERATOR_MAP) {
      return { ml: `<mo>${escHtml(OPERATOR_MAP[cmd])}</mo>`, preferLimits: false };
    }

    if (cmd === 'stackrel') {
      const top = this.parseBracedGroup();
      const bot = this.parseBracedGroup();
      return { ml: `<mover>${bot}${top}</mover>`, preferLimits: false };
    }

    return { ml: `<mi>${escHtml(cmd)}</mi>`, preferLimits: false };
  }
}

export function renderLatexToMathML(latex: string, display = false): string {
  let clean = (latex || '').trim();
  if (clean.startsWith('$$') && clean.endsWith('$$') && clean.length >= 4) {
    clean = clean.slice(2, -2).trim();
  } else if (clean.startsWith('$') && clean.endsWith('$') && clean.length >= 2) {
    clean = clean.slice(1, -1).trim();
  }
  if (!clean) return '';

  try {
    // Normalize `\_` or `\text{...}` cleanly before tokenizing
    const textCmds = new Set(['text', 'mbox', 'mathrm', 'mathbf', 'boldsymbol', 'operatorname', 'textrm']);
    const { cleaned, textChunks } = extractTextMacroContent(clean, textCmds);
    const toks = tokenizeLatex(cleaned, textChunks);
    const parser = new LatexMathParser(toks, display);
    const body = parser.parseSequence();
    return `<math xmlns="http://www.w3.org/1998/Math/MathML" display="${display ? 'block' : 'inline'}">${body}</math>`;
  } catch {
    return '';
  }
}

export interface StandardLatexMathProps {
  latex: string;
  display?: boolean;
  className?: string;
}

export const StandardLatexMath: React.FC<StandardLatexMathProps> = ({
  latex,
  display = false,
  className = '',
}) => {
  const mathml = useMemo(() => renderLatexToMathML(latex, display), [latex, display]);
  if (!mathml) {
    return (
      <span className={`std-math-fallback mono ${className}`}>
        {latex || '（空公式）'}
      </span>
    );
  }
  return (
    <span
      className={`${display ? 'std-math-block' : 'std-math-inline'} ${className}`}
      dangerouslySetInnerHTML={{ __html: mathml }}
    />
  );
};
