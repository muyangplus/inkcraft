"""LaTeX AST node dataclasses and space-preserving lexer."""

from __future__ import annotations

from dataclasses import dataclass, field

from inkcraft.layout.math_symbols import RAW_TEXT_COMMANDS, AtomKind


@dataclass(frozen=True, slots=True)
class Token:
    kind: str  # CMD, LBRACE, RBRACE, LBRACK, RBRACK, SUP, SUB, AMP, NEWLINE, PRIME, CHAR
    value: str


def lex_latex(src: str) -> list[Token]:
    """Tokenize a LaTeX math string, preserving whitespace inside `\\text{...}` and similar groups."""
    tokens: list[Token] = []
    i = 0
    n = len(src)
    expect_raw_group = False
    raw_group_depth = 0

    while i < n:
        ch = src[i]
        if ch.isspace():
            if raw_group_depth > 0:
                tokens.append(Token("CHAR", " "))
            i += 1
            continue

        if ch == "\\":
            if i + 1 >= n:
                expect_raw_group = False
                i += 1
                continue
            nxt = src[i + 1]
            if nxt == "\\":
                tokens.append(Token("NEWLINE", r"\\"))
                expect_raw_group = False
                i += 2
            elif nxt.isalpha():
                j = i + 2
                while j < n and src[j].isalpha():
                    j += 1
                cmd = src[i:j]
                tokens.append(Token("CMD", cmd))
                expect_raw_group = cmd in RAW_TEXT_COMMANDS
                i = j
            else:
                tokens.append(Token("CMD", "\\" + nxt))
                expect_raw_group = False
                i += 2
            continue

        if ch == "{":
            if raw_group_depth > 0:
                raw_group_depth += 1
            elif expect_raw_group:
                raw_group_depth = 1
                expect_raw_group = False
            tokens.append(Token("LBRACE", "{"))
        elif ch == "}":
            if raw_group_depth > 0:
                raw_group_depth -= 1
            expect_raw_group = False
            tokens.append(Token("RBRACE", "}"))
        elif ch == "[":
            expect_raw_group = False
            tokens.append(Token("LBRACK", "["))
        elif ch == "]":
            expect_raw_group = False
            tokens.append(Token("RBRACK", "]"))
        elif ch == "^":
            expect_raw_group = False
            tokens.append(Token("SUP", "^"))
        elif ch == "_":
            expect_raw_group = False
            tokens.append(Token("SUB", "_"))
        elif ch == "&":
            expect_raw_group = False
            tokens.append(Token("AMP", "&"))
        elif ch == "'":
            expect_raw_group = False
            tokens.append(Token("PRIME", "'"))
        else:
            expect_raw_group = False
            tokens.append(Token("CHAR", ch))
        i += 1
    return tokens


class MathNode:
    pass


@dataclass(slots=True)
class RowNode(MathNode):
    items: list[MathNode] = field(default_factory=list)


@dataclass(slots=True)
class CharNode(MathNode):
    char: str
    kind: AtomKind = "ord"
    italic: bool = False


@dataclass(slots=True)
class TextNode(MathNode):
    text: str
    kind: AtomKind = "ord"


@dataclass(slots=True)
class SpaceNode(MathNode):
    width_em: float


@dataclass(slots=True)
class FracNode(MathNode):
    num: MathNode
    den: MathNode


@dataclass(slots=True)
class SqrtNode(MathNode):
    body: MathNode
    degree: MathNode | None = None


@dataclass(slots=True)
class ScriptNode(MathNode):
    base: MathNode
    sub: MathNode | None = None
    sup: MathNode | None = None


@dataclass(slots=True)
class BigOpNode(MathNode):
    cmd: str
    sub: MathNode | None = None
    sup: MathNode | None = None


@dataclass(slots=True)
class DelimitedNode(MathNode):
    left: str
    right: str
    body: MathNode


@dataclass(slots=True)
class MatrixNode(MathNode):
    env: str
    rows: list[list[MathNode]]


@dataclass(slots=True)
class AccentNode(MathNode):
    cmd: str
    body: MathNode
