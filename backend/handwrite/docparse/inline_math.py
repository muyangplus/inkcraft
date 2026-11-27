"""Inline `$...$` LaTeX math splitter, PDF/DOCX subscript-to-LaTeX reconstructor, and helpers."""

from __future__ import annotations

import re

from handwrite.docparse.docir import BreakInline, DocInline, MathInline, TextInline

_INLINE_MATH_RE = re.compile(r"\$\$(.+?)\$\$|\$([^$\n]+?)\$", re.DOTALL)

# Trailing base token before a subscript/superscript span (units like kg/m, Greek+letter like △t, identifiers like FeCl/Al/A1, numbers, closing delim)
_BASE_PEEL_RE = re.compile(
    r"(?:([△Δα-ωΑ-Ωρσθλμ])\s*)?((?:[A-Za-z]{1,6}(?:/[A-Za-z]{1,6})+)|[A-Za-z][A-Za-z0-9]{0,7}|(?<![A-Za-z0-9.])\d+(?:\.\d+)?|[)\]])$"
)
# Trailing base + single space (e.g. `C ` before small-font `卡` in `C 卡`)
_BASE_SPACE_PEEL_RE = re.compile(r"(?:([△Δα-ωΑ-Ωρσθλμ])\s*)?([A-Za-z]{1,4})\s+$")

# Chemical/formula bridge allowed to stay inside one contiguous inline formula (e.g. `(SO` or `)` inside `Al2(SO4)3`)
_FORMULA_BRIDGE_RE = re.compile(
    r"^[A-Za-z0-9()\[\]{}·.,+\-*/=]+$"
)

# Plain-text unambiguous physical unit powers (applied only OUTSIDE existing `$...$`)
_UNIT_POWER_SLASH_RE = re.compile(
    r"(?<![A-Za-z0-9\\$/])(kg|g|mg|μg|t)/\s*(cm|mm|dm|m)([23])(?![0-9A-Za-z])"
)
_UNIT_POWER_ACCEL_RE = re.compile(
    r"(?<![A-Za-z0-9\\$/])(m|cm)/s([23])(?![0-9A-Za-z])"
)

_SYM_MAP_TEX = {
    "△": r"\Delta ",
    "Δ": r"\Delta ",
    "α": r"\alpha ",
    "β": r"\beta ",
    "γ": r"\gamma ",
    "δ": r"\delta ",
    "ε": r"\varepsilon ",
    "θ": r"\theta ",
    "λ": r"\lambda ",
    "μ": r"\mu ",
    "π": r"\pi ",
    "ρ": r"\rho ",
    "σ": r"\sigma ",
    "φ": r"\varphi ",
    "ω": r"\omega ",
    "Α": "A",
    "Ω": r"\Omega ",
    "Σ": r"\Sigma ",
    "Π": r"\Pi ",
}


def split_inline_math(text: str) -> list[DocInline]:
    """Split text containing `$...$` inline LaTeX spans into `[TextInline | MathInline, ...]`."""
    if "$" not in text:
        return [TextInline(text=text)] if text else []

    inlines: list[DocInline] = []
    pos = 0
    for m in _INLINE_MATH_RE.finditer(text):
        if m.start() > pos:
            chunk = text[pos : m.start()]
            if chunk:
                inlines.append(TextInline(text=chunk))
        tex = (m.group(1) or m.group(2) or "").strip()
        if tex:
            inlines.append(MathInline(latex=tex))
        pos = m.end()
    if pos < len(text):
        tail = text[pos:]
        if tail:
            inlines.append(TextInline(text=tail))
    return inlines


def inlines_to_inline_math_str(inlines: list[DocInline]) -> str:
    """Serialize `DocInline` stream preserving `$...$` around `MathInline` and `\\n` for breaks."""
    parts: list[str] = []
    for inl in inlines:
        if isinstance(inl, TextInline):
            parts.append(inl.text or "")
        elif isinstance(inl, MathInline):
            parts.append(f"${inl.latex}$")
        elif isinstance(inl, BreakInline):
            parts.append("\n")
    return "".join(parts)


def strip_inline_math_markup(text: str) -> str:
    """Strip inline `$...$` and basic TeX wrappers for plain structural role detection."""
    if "$" not in text and "\\" not in text:
        return text
    s = text.replace("$", "")
    s = re.sub(r"\\(?:text|mathrm|mathbf|mathit|operatorname)\{([^}]*)\}", r"\1", s)
    s = s.replace(r"\Delta ", "Δ").replace(r"\Delta", "Δ")
    s = s.replace(r"\rho ", "ρ").replace(r"\rho", "ρ")
    s = s.replace(r"\%", "%")
    s = re.sub(r"[_^{}]", "", s)
    return s


# Shared structural symbol-definition patterns (reused across PDF parser, DOCX parser, and Reflow composer)
SYMBOL_DEF_PREFIX_RE = re.compile(
    r"^(?:式中|其中)(?:[：:\s]|(?=[A-Za-zα-ωΑ-ΩΔρ△σθλπ]))"
)
SYMBOL_DEF_DASH_RE = re.compile(
    r"^(?:[A-Za-zα-ωΑ-ΩΔρ△σθλπ][A-Za-z0-9_]*(?:\s*[（(][^）)]{1,6}[）)])?(?:\s*[\u4e00-\u9fff]{1,2})?|\d{2,5})"
    r"\s*(?:--|——|—|–|-\s|[：:])"
)
SYMBOL_DEF_COMMA_RE = re.compile(
    r"^[A-Za-zα-ωΑ-ΩΔρ△σθλπ][A-Za-z0-9()（）_]{0,5}\s*[,，]\s*[\u4e00-\u9fff]"
)

# Leading 2-char variable+subscript on a symbol-def line outside `$...$` (e.g. `Wi，...`, `Vi，...`, `Ci，...`, `Vs，...`, `V0--...`)
_LEADING_SYM_SUB_RE = re.compile(
    r"^((?:(?:式中|其中)\s*[：:]?\s*)?)"
    r"(?:"
    r"([A-Z])([a-z0-9])"
    r"|([a-z])([0-9])"
    r"|([α-ωΑ-Ωρσθλμ])([a-z0-9])"
    r")"
    r"(?=\s*(?:[,，]|--|——|—|–|-\s|[：:]))"
)


def is_symbol_def_line(text: str) -> bool:
    """Return True if a single line looks like a formula symbol definition (`式中...` or `Wi，...` or `A--...`)."""
    txt = strip_inline_math_markup(text).strip()
    if not txt:
        return False
    return bool(
        SYMBOL_DEF_PREFIX_RE.match(txt)
        or SYMBOL_DEF_DASH_RE.match(txt)
        or SYMBOL_DEF_COMMA_RE.match(txt)
    )


def is_symbol_def_block(blk: object) -> bool:
    """Return True if a `DocBlock(type='paragraph')` represents a symbol-definition block."""
    if getattr(blk, "type", None) != "paragraph":
        return False
    inlines = getattr(blk, "inlines", None) or []
    raw = inlines_to_inline_math_str(list(inlines))
    rows = [ln.strip() for ln in raw.split("\n") if ln.strip()]
    if not rows:
        return False
    if is_symbol_def_line(rows[0]):
        return True
    if len(rows) >= 2:
        sym_hits = sum(1 for r in rows if is_symbol_def_line(r))
        return sym_hits * 2 >= len(rows)
    return False


def normalize_symbol_def_leading_subscript(text: str) -> str:
    """Convert plain leading 2-char symbol variables (`Wi，`, `Vi，`, `Ci，`, `Vs，`, `V0--`) into `$W_i$` etc."""
    if not text:
        return text
    stripped_l = text.lstrip()
    lead_ws = text[: len(text) - len(stripped_l)]
    # Tidy stray spaces between an already-wrapped leading `$...$` and Chinese comma/colon (e.g. `$\rho_s$ ，` -> `$\rho_s$，`)
    m_existing = re.match(r"^((?:(?:式中|其中)\s*[：:]?\s*)?\$[^$\n]+\$)\s+([，：])", stripped_l)
    if m_existing:
        return lead_ws + m_existing.group(1) + m_existing.group(2) + stripped_l[m_existing.end() :]
    if "$" in stripped_l[:6]:
        return text

    m = _LEADING_SYM_SUB_RE.match(stripped_l)
    if not m:
        return text
    prefix = m.group(1) or ""
    base = m.group(2) or m.group(4) or m.group(6) or ""
    sub = m.group(3) or m.group(5) or m.group(7) or ""
    if not base or not sub:
        return text
    base_tex = _SYM_MAP_TEX.get(base, base).rstrip()
    tex = f"{base_tex}_{sub}"
    rest = stripped_l[m.end() :]
    # Trim accidental single space before Chinese comma/colon if present
    rest = re.sub(r"^\s+([，：])", r"\1", rest)
    return f"{lead_ws}{prefix}${tex}${rest}"


def normalize_symbol_def_inlines(inlines: list[DocInline]) -> list[DocInline]:
    """Normalize plain leading variable+subscript tokens on symbol-def rows within an inline stream."""
    if not inlines:
        return inlines
    rows: list[list[DocInline]] = [[]]
    for inl in inlines:
        if isinstance(inl, BreakInline):
            rows.append([])
        else:
            rows[-1].append(inl)

    changed = False
    out_rows: list[list[DocInline]] = []
    for row in rows:
        row_str = inlines_to_inline_math_str(row)
        if row and isinstance(row[0], TextInline) and is_symbol_def_line(row_str):
            head_txt = row[0].text or ""
            norm_head = normalize_symbol_def_leading_subscript(head_txt)
            if norm_head != head_txt:
                head_bold = row[0].bold
                head_italic = row[0].italic
                head_parts = [
                    TextInline(text=p.text, bold=head_bold, italic=head_italic)
                    if isinstance(p, TextInline)
                    else p
                    for p in split_inline_math(norm_head)
                ]
                out_rows.append([*head_parts, *row[1:]])
                changed = True
                continue
        out_rows.append(row)

    if not changed:
        return inlines
    merged: list[DocInline] = []
    for idx, row in enumerate(out_rows):
        if idx > 0:
            merged.append(BreakInline())
        merged.extend(row)
    return merged


def _format_base_token(sym: str | None, base: str) -> str:
    """Format a peeled base token in TeX: single Latin var stays italic, multi-letter uses \\mathrm{...}."""
    pre = _SYM_MAP_TEX.get(sym, f"{sym} ") if sym else ""
    if base in {")", "]"} or base[0].isdigit():
        return f"{pre}{base}".strip()
    if len(base) == 1 and base.isalpha():
        return f"{pre}{base}".strip()
    return f"{pre}\\mathrm{{{base}}}".strip()


def _format_script_payload(raw_txt: str) -> str:
    """Format subscript/superscript text payload cleanly for LaTeX (`0`, `\\text{卡}`, `j(\\text{湿})`)."""
    s = raw_txt.strip()
    if not s:
        return ""
    s = s.replace("（", "(").replace("）", ")").replace("，", ",")
    s = re.sub(r"(?<!\\)%", r"\\%", s)
    s = re.sub(r"[\u4e00-\u9fff]+", lambda m: f"\\text{{{m.group(0)}}}", s)
    for ch, cmd in _SYM_MAP_TEX.items():
        if ch in s:
            s = s.replace(ch, cmd)
    return s.strip()


def _wrap_script_arg(payload: str) -> str:
    if len(payload) == 1 and payload.isalnum():
        return payload
    return f"{{{payload}}}"


def _append_script_to_tex(tex: str, role: str, payload: str) -> str:
    """Attach a subscript/superscript to `tex`, merging consecutive same-kind scripts cleanly."""
    op = "^" if role == "sup" else "_"
    # Detect if `tex` ALREADY ends with `_arg` or `^arg` of the SAME script kind (e.g. `M_j` + `(\text{湿})`)
    same_braced = re.search(rf"\{op}\{{([^{{}}]*)\}}$", tex)
    if same_braced:
        inner = same_braced.group(1)
        merged = f"{inner}{payload}"
        return tex[: same_braced.start()] + f"{op}{{{merged}}}"
    same_single = re.search(rf"\{op}([A-Za-z0-9])$", tex)
    if same_single:
        inner = same_single.group(1)
        merged = f"{inner}{payload}"
        return tex[: same_single.start()] + f"{op}{{{merged}}}"
    return f"{tex}{op}{_wrap_script_arg(payload)}"


def _is_bridge_piece(
    pieces: list[tuple[str, str]],
    idx: int,
) -> bool:
    """Return True if `pieces[idx]` is a short non-space chemical/math bridge followed by a script piece."""
    txt, role = pieces[idx]
    if role != "normal":
        return False
    stripped = txt.strip()
    if not stripped or len(stripped) > 14:
        return False
    if txt != txt.lstrip():
        return False
    if re.search(r"\s", stripped):
        return False
    if not _FORMULA_BRIDGE_RE.match(stripped):
        return False
    # Look ahead for next non-whitespace piece
    j = idx + 1
    while j < len(pieces) and not pieces[j][0].strip():
        j += 1
    if j >= len(pieces):
        return False
    return pieces[j][1] in {"sub", "sup", "math"}


def build_text_with_scripts(pieces: list[tuple[str, str]]) -> str:
    """Combine `(text, role)` runs (`normal|sub|sup|math`) into text with cohesive `$...$` math."""
    if not pieces:
        return ""

    # 1. Coalesce adjacent identical non-bridge raw/normal pieces and turn whitespace-only script pieces into normal
    normalized: list[tuple[str, str]] = []
    for raw_t, role in pieces:
        if not raw_t:
            continue
        if role in {"sub", "sup"} and not raw_t.strip():
            eff_role = "normal"
        else:
            eff_role = role
        if eff_role == "normal" and normalized and normalized[-1][1] == "normal":
            normalized[-1] = (normalized[-1][0] + raw_t, "normal")
        else:
            normalized.append((raw_t, eff_role))

    # Output tokens: ("raw", str) or ("math", tex_str)
    tokens: list[tuple[str, str]] = []
    i = 0
    n = len(normalized)
    while i < n:
        raw_t, role = normalized[i]

        if role == "math":
            tex_m = raw_t.strip().strip("$").strip()
            lead = raw_t[: len(raw_t) - len(raw_t.lstrip())]
            trail = raw_t[len(raw_t.rstrip()) :]
            if lead:
                tokens.append(("raw", lead))
            if tex_m:
                if tokens and tokens[-1][0] == "math" and not lead:
                    tokens[-1] = ("math", f"{tokens[-1][1]} {tex_m}")
                else:
                    tokens.append(("math", tex_m))
            if trail:
                tokens.append(("raw", trail))
            i += 1
            continue

        if role == "normal":
            # Check if this normal piece acts as a bridge continuing an immediately preceding math chunk
            if tokens and tokens[-1][0] == "math" and _is_bridge_piece(normalized, i):
                # Format bridge inside the active math chunk: peel optional base at end if next is sub/sup
                j = i + 1
                next_role = normalized[j][1] if j < n else "normal"
                if next_role in {"sub", "sup"}:
                    m = _BASE_PEEL_RE.search(raw_t)
                    if m:
                        prefix = raw_t[: m.start()]
                        base_tex = _format_base_token(m.group(1), m.group(2))
                        tokens[-1] = ("math", f"{tokens[-1][1]}{prefix}{base_tex}")
                        i += 1
                        continue
                tokens[-1] = ("math", f"{tokens[-1][1]}{raw_t}")
                i += 1
                continue

            if tokens and tokens[-1][0] == "raw":
                tokens[-1] = ("raw", tokens[-1][1] + raw_t)
            else:
                tokens.append(("raw", raw_t))
            i += 1
            continue

        # role in {"sub", "sup"}
        lead_ws = raw_t[: len(raw_t) - len(raw_t.lstrip())]
        trail_ws = raw_t[len(raw_t.rstrip()) :]
        payload = _format_script_payload(raw_t)
        if not payload:
            tokens.append(("raw", raw_t))
            i += 1
            continue

        attached = False
        if tokens and tokens[-1][0] == "math" and not lead_ws:
            tokens[-1] = ("math", _append_script_to_tex(tokens[-1][1], role, payload))
            attached = True
        elif tokens and tokens[-1][0] == "raw":
            prev_raw = tokens[-1][1]
            # Special case: `10-` followed by sup `3` -> `$10^{-3}$`
            neg_pow_m = re.search(r"(\d+)-$", prev_raw) if role == "sup" else None
            if neg_pow_m:
                tokens[-1] = ("raw", prev_raw[: neg_pow_m.start()])
                if not tokens[-1][1]:
                    tokens.pop()
                tokens.append(("math", _append_script_to_tex(neg_pow_m.group(1), "sup", f"-{payload}")))
                attached = True
            else:
                base_m = _BASE_PEEL_RE.search(prev_raw)
                if not base_m and not lead_ws:
                    base_m = _BASE_SPACE_PEEL_RE.search(prev_raw)
                if base_m:
                    rest = prev_raw[: base_m.start()]
                    tokens[-1] = ("raw", rest)
                    if not rest:
                        tokens.pop()
                    base_tex = _format_base_token(base_m.group(1), base_m.group(2))
                    new_tex = _append_script_to_tex(base_tex, role, payload)
                    if tokens and tokens[-1][0] == "math" and rest == "":
                        tokens[-1] = ("math", f"{tokens[-1][1]}{new_tex}")
                    else:
                        tokens.append(("math", new_tex))
                    attached = True

        if not attached:
            tokens.append(("raw", raw_t))
        elif trail_ws:
            tokens.append(("raw", trail_ws))
        i += 1

    out_parts: list[str] = []
    for kind, val in tokens:
        if kind == "math":
            if val:
                out_parts.append(f"${val}$")
        else:
            out_parts.append(val)
    return "".join(out_parts)


def normalize_unambiguous_unit_powers(text: str) -> str:
    """Convert unambiguous physical unit strings like `g/cm3` and `kg/m3` outside `$...$` into `$...$` math."""
    if not text or not any(d in text for d in ("2", "3")):
        return text

    def _conv_plain(seg: str) -> str:
        seg = _UNIT_POWER_SLASH_RE.sub(
            lambda m: f"$\\mathrm{{{m.group(1)}/{m.group(2)}}}^{m.group(3)}$",
            seg,
        )
        seg = _UNIT_POWER_ACCEL_RE.sub(
            lambda m: f"$\\mathrm{{{m.group(1)}/s}}^{m.group(2)}$",
            seg,
        )
        return seg

    out: list[str] = []
    pos = 0
    for m in _INLINE_MATH_RE.finditer(text):
        if m.start() > pos:
            out.append(_conv_plain(text[pos : m.start()]))
        out.append(m.group(0))
        pos = m.end()
    if pos < len(text):
        out.append(_conv_plain(text[pos:]))
    return "".join(out)
