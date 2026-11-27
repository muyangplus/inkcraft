"""XML namespaces and pure-Python OMML (`m:oMath`) -> LaTeX converter."""

from __future__ import annotations

import re

from lxml import etree

TWIP_TO_MM = 25.4 / 1440.0

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
}

W_NS = f"{{{NS['w']}}}"
M_NS = f"{{{NS['m']}}}"
R_NS = f"{{{NS['r']}}}"
A_NS = f"{{{NS['a']}}}"
C_NS = f"{{{NS['c']}}}"

_OMML_SYMBOL_MAP: dict[str, str] = {
    "±": r"\pm ",
    "∓": r"\mp ",
    "×": r"\times ",
    "÷": r"\div ",
    "·": r"\cdot ",
    "≤": r"\leq ",
    "≥": r"\geq ",
    "≠": r"\neq ",
    "≈": r"\approx ",
    "≡": r"\equiv ",
    "∞": r"\infty ",
    "∂": r"\partial ",
    "∇": r"\nabla ",
    "∈": r"\in ",
    "∉": r"\notin ",
    "⊂": r"\subset ",
    "⊆": r"\subseteq ",
    "∪": r"\cup ",
    "∩": r"\cap ",
    "→": r"\to ",
    "⇒": r"\Rightarrow ",
    "⇔": r"\Leftrightarrow ",
    "−": "-",
    "–": "-",
    "α": r"\alpha ",
    "β": r"\beta ",
    "γ": r"\gamma ",
    "δ": r"\delta ",
    "ε": r"\varepsilon ",
    "ϵ": r"\epsilon ",
    "ζ": r"\zeta ",
    "η": r"\eta ",
    "θ": r"\theta ",
    "ι": r"\iota ",
    "κ": r"\kappa ",
    "λ": r"\lambda ",
    "μ": r"\mu ",
    "ν": r"\nu ",
    "ξ": r"\xi ",
    "π": r"\pi ",
    "ρ": r"\rho ",
    "σ": r"\sigma ",
    "τ": r"\tau ",
    "υ": r"\upsilon ",
    "φ": r"\phi ",
    "ϕ": r"\varphi ",
    "χ": r"\chi ",
    "ψ": r"\psi ",
    "ω": r"\omega ",
    "Γ": r"\Gamma ",
    "Δ": r"\Delta ",
    "Θ": r"\Theta ",
    "Λ": r"\Lambda ",
    "Ξ": r"\Xi ",
    "Π": r"\Pi ",
    "Σ": r"\Sigma ",
    "Φ": r"\Phi ",
    "Ψ": r"\Psi ",
    "Ω": r"\Omega ",
    "∑": r"\sum",
    "∏": r"\prod",
    "∫": r"\int",
    "∬": r"\iint",
    "∮": r"\oint",
}

_NARY_MAP: dict[str, str] = {
    "∑": r"\sum",
    "∏": r"\prod",
    "∫": r"\int",
    "∬": r"\iint",
    "∮": r"\oint",
    "⋃": r"\bigcup",
    "⋂": r"\bigcap",
}

_ACCENT_MAP: dict[str, str] = {
    "^": r"\hat",
    "̂": r"\hat",
    "~": r"\tilde",
    "̃": r"\tilde",
    "¯": r"\bar",
    "̄": r"\bar",
    "→": r"\vec",
    "⃗": r"\vec",
    "˙": r"\dot",
    "̇": r"\dot",
    "¨": r"\ddot",
    "̈": r"\ddot",
}

_DELIM_ESCAPE: dict[str, str] = {
    "{": r"\{",
    "}": r"\}",
    "[": "[",
    "]": "]",
    "(": "(",
    ")": ")",
    "|": "|",
    "‖": r"\|",
    "⟨": r"\langle",
    "⟩": r"\rangle",
    "": ".",
}

_KNOWN_FUNCS = frozenset(
    {
        "sin",
        "cos",
        "tan",
        "cot",
        "sec",
        "csc",
        "arcsin",
        "arccos",
        "arctan",
        "sinh",
        "cosh",
        "tanh",
        "log",
        "ln",
        "exp",
        "lim",
        "max",
        "min",
        "sup",
        "inf",
        "det",
        "gcd",
    }
)


def xml_local_tag(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _m_val(parent: etree._Element | None, child_local: str, default: str = "") -> str:
    if parent is None:
        return default
    el = parent.find(f"{M_NS}{child_local}")
    if el is None:
        return default
    val = el.get(f"{M_NS}val")
    return default if val is None else val


def _omml_text(text: str) -> str:
    return "".join(_OMML_SYMBOL_MAP.get(ch, ch) for ch in text)


def _omml_children(elem: etree._Element | None) -> str:
    if elem is None:
        return ""
    return "".join(omml_to_latex(child) for child in elem)


def omml_to_latex(elem: etree._Element) -> str:
    """Recursively convert an Office Math ML (`m:oMath`, `m:oMathPara`, etc.) element to LaTeX."""
    tag = xml_local_tag(elem.tag)

    if tag in {"oMathPara", "oMath", "e", "num", "den", "sup", "sub", "deg", "lim", "fName"}:
        return _omml_children(elem)

    if tag == "r":
        rpr = elem.find(f"{M_NS}rPr")
        is_normal = rpr is not None and rpr.find(f"{M_NS}nor") is not None
        raw = "".join(t.text or "" for t in elem.findall(f"{M_NS}t"))
        if not raw:
            return ""
        if is_normal:
            stripped = raw.strip()
            if stripped in _KNOWN_FUNCS:
                return f"\\{stripped} "
            return f"\\text{{{raw}}}"
        return _omml_text(raw)

    if tag == "t":
        return _omml_text(elem.text or "")

    if tag == "f":
        num = _omml_children(elem.find(f"{M_NS}num")).strip()
        den = _omml_children(elem.find(f"{M_NS}den")).strip()
        fpr = elem.find(f"{M_NS}fPr")
        ftype = _m_val(fpr, "type", "bar")
        if ftype == "lin":
            return f"({num})/({den})"
        return f"\\frac{{{num}}}{{{den}}}"

    if tag == "sSup":
        base = _omml_children(elem.find(f"{M_NS}e")).strip()
        sup = _omml_children(elem.find(f"{M_NS}sup")).strip()
        if len(base) > 1 and not (base.startswith("{") and base.endswith("}")):
            base = f"{{{base}}}"
        return f"{base}^{{{sup}}}"

    if tag == "sSub":
        base = _omml_children(elem.find(f"{M_NS}e")).strip()
        sub = _omml_children(elem.find(f"{M_NS}sub")).strip()
        if len(base) > 1 and not (base.startswith("{") and base.endswith("}")):
            base = f"{{{base}}}"
        return f"{base}_{{{sub}}}"

    if tag == "sSubSup":
        base = _omml_children(elem.find(f"{M_NS}e")).strip()
        sub = _omml_children(elem.find(f"{M_NS}sub")).strip()
        sup = _omml_children(elem.find(f"{M_NS}sup")).strip()
        if len(base) > 1 and not (base.startswith("{") and base.endswith("}")):
            base = f"{{{base}}}"
        return f"{base}_{{{sub}}}^{{{sup}}}"

    if tag == "sPre":
        base = _omml_children(elem.find(f"{M_NS}e")).strip()
        sub = _omml_children(elem.find(f"{M_NS}sub")).strip()
        sup = _omml_children(elem.find(f"{M_NS}sup")).strip()
        return f"{{}}_{{{sub}}}^{{{sup}}}{base}"

    if tag == "rad":
        rad_pr = elem.find(f"{M_NS}radPr")
        deg_hide = _m_val(rad_pr, "degHide", "0") in {"1", "on", "true"}
        deg = "" if deg_hide else _omml_children(elem.find(f"{M_NS}deg")).strip()
        body = _omml_children(elem.find(f"{M_NS}e")).strip()
        if deg:
            return f"\\sqrt[{deg}]{{{body}}}"
        return f"\\sqrt{{{body}}}"

    if tag == "nary":
        nary_pr = elem.find(f"{M_NS}naryPr")
        chr_val = _m_val(nary_pr, "chr", "∫")
        op = _NARY_MAP.get(chr_val, r"\int")
        sub = _omml_children(elem.find(f"{M_NS}sub")).strip()
        sup = _omml_children(elem.find(f"{M_NS}sup")).strip()
        body = _omml_children(elem.find(f"{M_NS}e")).strip()
        parts = [op]
        if sub:
            parts.append(f"_{{{sub}}}")
        if sup:
            parts.append(f"^{{{sup}}}")
        if body:
            parts.append(f" {body}")
        return "".join(parts)

    if tag == "d":
        dpr = elem.find(f"{M_NS}dPr")
        beg = _m_val(dpr, "begChr", "(")
        end = _m_val(dpr, "endChr", ")")
        sep = _m_val(dpr, "sepChr", ",")
        beg_tex = _DELIM_ESCAPE.get(beg, beg)
        end_tex = _DELIM_ESCAPE.get(end, end)
        items = [_omml_children(e).strip() for e in elem.findall(f"{M_NS}e")]
        inner = f" {sep} ".join(items)
        return f"\\left{beg_tex} {inner} \\right{end_tex}"

    if tag == "m":
        rows: list[str] = []
        for mr in elem.findall(f"{M_NS}mr"):
            cells = [_omml_children(e).strip() for e in mr.findall(f"{M_NS}e")]
            rows.append(" & ".join(cells))
        body = r" \\ ".join(rows)
        return f"\\begin{{matrix}} {body} \\end{{matrix}}"

    if tag == "eqArr":
        lines = [_omml_children(e).strip() for e in elem.findall(f"{M_NS}e")]
        return f"\\begin{{aligned}} {' \\\\ '.join(lines)} \\end{{aligned}}"

    if tag == "func":
        fname = _omml_children(elem.find(f"{M_NS}fName")).strip()
        body = _omml_children(elem.find(f"{M_NS}e")).strip()
        clean_fn = re.sub(r"^\\text\{(.+)\}$", r"\1", fname).strip()
        if clean_fn in _KNOWN_FUNCS:
            return f"\\{clean_fn} {body}"
        return f"{fname} {body}"

    if tag == "limLow":
        base = _omml_children(elem.find(f"{M_NS}e")).strip()
        lim = _omml_children(elem.find(f"{M_NS}lim")).strip()
        if base in _KNOWN_FUNCS:
            base = f"\\{base}"
        return f"{base}_{{{lim}}}"

    if tag == "limUpp":
        base = _omml_children(elem.find(f"{M_NS}e")).strip()
        lim = _omml_children(elem.find(f"{M_NS}lim")).strip()
        return f"{base}^{{{lim}}}"

    if tag == "acc":
        apr = elem.find(f"{M_NS}accPr")
        acc_chr = _m_val(apr, "chr", "^")
        cmd = _ACCENT_MAP.get(acc_chr, r"\hat")
        body = _omml_children(elem.find(f"{M_NS}e")).strip()
        return f"{cmd}{{{body}}}"

    if tag == "bar":
        bpr = elem.find(f"{M_NS}barPr")
        pos = _m_val(bpr, "pos", "top")
        body = _omml_children(elem.find(f"{M_NS}e")).strip()
        cmd = r"\underline" if pos == "bot" else r"\overline"
        return f"{cmd}{{{body}}}"

    if tag in {"box", "borderBox", "groupChr", "phant"}:
        return _omml_children(elem.find(f"{M_NS}e"))

    if tag.endswith("Pr"):
        return ""

    return _omml_children(elem)


def clean_latex(tex: str) -> str:
    return re.sub(r"\s+", " ", tex).strip()
