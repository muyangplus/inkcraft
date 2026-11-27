"""Recursive-descent LaTeX subset parser."""

from __future__ import annotations

from inkcraft.layout.math_ast import (
    AccentNode,
    BigOpNode,
    CharNode,
    DelimitedNode,
    FracNode,
    MathNode,
    MatrixNode,
    RowNode,
    ScriptNode,
    SpaceNode,
    SqrtNode,
    TextNode,
    Token,
    lex_latex,
)
from inkcraft.layout.math_symbols import (
    ACCENT_COMMANDS,
    BIG_OP_COMMANDS,
    FUNC_COMMANDS,
    GREEK_AND_SYMBOLS,
    IGNORED_SIZING_CMDS,
    SPACE_COMMANDS,
)


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0
        self.n = len(tokens)

    def peek(self) -> Token | None:
        return self.tokens[self.pos] if self.pos < self.n else None

    def consume(self) -> Token | None:
        if self.pos >= self.n:
            return None
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def parse_row(self, stop_kinds: set[str] | None = None, stop_cmds: set[str] | None = None) -> RowNode:
        items: list[MathNode] = []
        while self.pos < self.n:
            tok = self.peek()
            if tok is None:
                break
            if stop_kinds and tok.kind in stop_kinds:
                break
            if stop_cmds and tok.kind == "CMD" and tok.value in stop_cmds:
                break
            node = self.parse_scripted()
            if node is not None:
                items.append(node)
        return RowNode(items=items)

    def parse_arg(self) -> MathNode:
        tok = self.peek()
        if tok is None:
            return RowNode()
        if tok.kind == "LBRACE":
            self.consume()
            row = self.parse_row(stop_kinds={"RBRACE"})
            nxt = self.peek()
            if nxt is not None and nxt.kind == "RBRACE":
                self.consume()
            return row
        atom = self.parse_atom()
        return atom if atom is not None else RowNode()

    def parse_raw_group_text(self) -> str:
        """Read `{...}` as literal text for `\\text{...}`, `\\mathrm{...}`, `\\begin{...}`."""
        tok = self.peek()
        if tok is None:
            return ""
        if tok.kind != "LBRACE":
            self.consume()
            return tok.value
        self.consume()
        depth = 1
        parts: list[str] = []
        while self.pos < self.n and depth > 0:
            t = self.consume()
            if t is None:
                break
            if t.kind == "LBRACE":
                depth += 1
                parts.append("{")
            elif t.kind == "RBRACE":
                depth -= 1
                if depth > 0:
                    parts.append("}")
            elif t.kind == "CMD" and t.value in GREEK_AND_SYMBOLS:
                parts.append(GREEK_AND_SYMBOLS[t.value][0])
            else:
                parts.append(t.value)
        return "".join(parts)

    def parse_scripted(self) -> MathNode | None:
        base = self.parse_atom()
        if base is None:
            return None

        sub: MathNode | None = None
        sup: MathNode | None = None
        primes = 0

        while self.pos < self.n:
            tok = self.peek()
            if tok is None:
                break
            if tok.kind == "PRIME":
                self.consume()
                primes += 1
            elif tok.kind == "SUB":
                self.consume()
                sub = self.parse_arg()
            elif tok.kind == "SUP":
                self.consume()
                sup = self.parse_arg()
            elif tok.kind == "CMD" and tok.value in {r"\limits", r"\nolimits"}:
                self.consume()
            else:
                break

        if primes > 0:
            prime_nodes: list[MathNode] = [CharNode("'", "ord", False) for _ in range(primes)]
            sup = RowNode(items=prime_nodes) if sup is None else RowNode(items=prime_nodes + [sup])

        if isinstance(base, BigOpNode):
            base.sub = sub if sub is not None else base.sub
            base.sup = sup if sup is not None else base.sup
            return base

        if sub is not None or sup is not None:
            return ScriptNode(base=base, sub=sub, sup=sup)
        return base

    def _parse_delim_token(self) -> str:
        tok = self.consume()
        return "." if tok is None else tok.value

    def parse_atom(self) -> MathNode | None:
        tok = self.consume()
        if tok is None:
            return None

        if tok.kind == "LBRACE":
            row = self.parse_row(stop_kinds={"RBRACE"})
            nxt = self.peek()
            if nxt is not None and nxt.kind == "RBRACE":
                self.consume()
            return row

        if tok.kind == "RBRACE":
            return None

        if tok.kind in {"LBRACK", "RBRACK"}:
            return CharNode(tok.value, "open" if tok.kind == "LBRACK" else "close", False)

        if tok.kind == "CHAR":
            ch = tok.value
            if ch in "+-":
                return CharNode(ch, "bin", False)
            if ch in "=<>":
                return CharNode(ch, "rel", False)
            if ch in "([":
                return CharNode(ch, "open", False)
            if ch in ")]":
                return CharNode(ch, "close", False)
            if ch in ",;":
                return CharNode(ch, "punct", False)
            is_italic = ch.isalpha() and ord(ch) < 128
            return CharNode(ch, "ord", is_italic)

        if tok.kind == "CMD":
            cmd = tok.value
            if cmd in IGNORED_SIZING_CMDS:
                return None
            if cmd in SPACE_COMMANDS:
                return SpaceNode(SPACE_COMMANDS[cmd])
            if cmd in {r"\frac", r"\dfrac", r"\tfrac"}:
                num = self.parse_arg()
                den = self.parse_arg()
                return FracNode(num=num, den=den)
            if cmd == r"\sqrt":
                deg: MathNode | None = None
                nxt = self.peek()
                if nxt is not None and nxt.kind == "LBRACK":
                    self.consume()
                    deg = self.parse_row(stop_kinds={"RBRACK"})
                    end_b = self.peek()
                    if end_b is not None and end_b.kind == "RBRACK":
                        self.consume()
                body = self.parse_arg()
                return SqrtNode(body=body, degree=deg)
            if cmd in BIG_OP_COMMANDS:
                return BigOpNode(cmd=cmd)
            if cmd == r"\left":
                ldelim = self._parse_delim_token()
                body = self.parse_row(stop_cmds={r"\right"})
                rdelim = "."
                nxt = self.peek()
                if nxt is not None and nxt.kind == "CMD" and nxt.value == r"\right":
                    self.consume()
                    rdelim = self._parse_delim_token()
                return DelimitedNode(left=ldelim, right=rdelim, body=body)
            if cmd == r"\right":
                return None
            if cmd == r"\begin":
                env = self.parse_raw_group_text().strip()
                nxt_brace = self.peek()
                if env == "array" and nxt_brace is not None and nxt_brace.kind == "LBRACE":
                    self.parse_raw_group_text()
                rows: list[list[MathNode]] = []
                cur_row: list[MathNode] = []
                while self.pos < self.n:
                    cell = self.parse_row(stop_kinds={"AMP", "NEWLINE"}, stop_cmds={r"\end"})
                    cur_row.append(cell)
                    nxt = self.peek()
                    if nxt is None:
                        break
                    if nxt.kind == "AMP":
                        self.consume()
                    elif nxt.kind == "NEWLINE":
                        self.consume()
                        rows.append(cur_row)
                        cur_row = []
                    elif nxt.kind == "CMD" and nxt.value == r"\end":
                        self.consume()
                        self.parse_raw_group_text()
                        break
                    else:
                        break
                if cur_row and not (
                    len(cur_row) == 1 and isinstance(cur_row[0], RowNode) and not cur_row[0].items
                ):
                    rows.append(cur_row)
                return MatrixNode(env=env, rows=rows)
            if cmd in ACCENT_COMMANDS:
                body = self.parse_arg()
                return AccentNode(cmd=cmd, body=body)
            if cmd in {r"\mathcal", r"\mathbb", r"\mathit", r"\boldsymbol"}:
                return self.parse_arg()
            if cmd in {r"\text", r"\textbf", r"\textit", r"\mathrm", r"\mathbf", r"\operatorname", r"\mbox"}:
                txt = self.parse_raw_group_text()
                return TextNode(text=txt, kind="ord")
            if cmd in FUNC_COMMANDS:
                return TextNode(text=cmd[1:], kind="op")
            if cmd in GREEK_AND_SYMBOLS:
                ch, kind, italic = GREEK_AND_SYMBOLS[cmd]
                return CharNode(ch, kind, italic)
            return TextNode(text=cmd.lstrip("\\"), kind="ord")

        return None


def parse_latex(latex: str) -> RowNode:
    tokens = lex_latex(latex or "")
    return _Parser(tokens).parse_row()
