#!/usr/bin/env python
"""A lexer for the kod language."""

from pathlib import Path
from typing import Iterator, TypeVar

from kod.exceptions import KodError
from kod.span import Span
from kod.tokens import (
    EOF,
    EOL,
    And,
    Anon,
    Arrow,
    Assert,
    BooleanLiteral,
    Break,
    CloseBracket,
    CloseCurly,
    CloseParen,
    Colon,
    Comma,
    Comment,
    Continue,
    Dot,
    Else,
    Enum,
    Equal,
    EqualEqual,
    Extern,
    For,
    FStringLiteral,
    Func,
    GreaterEqual,
    GreaterThan,
    Identifier,
    If,
    Import,
    In,
    IntegerLiteral,
    Interface,
    Is,
    LessEqual,
    LessThan,
    Let,
    Match,
    Minus,
    MinusEqual,
    Must,
    Mut,
    NoneLiteral,
    NotEqual,
    OpenBracket,
    OpenCurly,
    OpenParen,
    Or,
    Percent,
    Plus,
    PlusEqual,
    Question,
    Return,
    Slash,
    Star,
    StringLiteral,
    Struct,
    Test,
    Throw,
    Token,
    Try,
    Type,
)

KEYWORDS = {
    "import": Import,
    "let": Let,
    "mut": Mut,
    "extern": Extern,
    "func": Func,
    "anon": Anon,
    "return": Return,
    "if": If,
    "else": Else,
    "true": BooleanLiteral,
    "false": BooleanLiteral,
    "for": For,
    "in": In,
    "break": Break,
    "continue": Continue,
    "struct": Struct,
    "type": Type,
    "enum": Enum,
    "interface": Interface,
    "throw": Throw,
    "try": Try,
    "must": Must,
    "test": Test,
    "assert": Assert,
    "match": Match,
    "is": Is,
    "and": And,
    "or": Or,
    "none": NoneLiteral,
}

_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "\\": "\\",
    "'": "'",
    "0": "\0",
    '"': '"',
}


def process_escapes(s: str) -> str:
    """Process backslash escapes in a string body, mirroring the self-hosted
    parsing.kod `unescape_str`. Unlike `s.encode().decode("unicode-escape")`
    (the old approach), this leaves non-ASCII UTF-8 intact instead of
    re-decoding each byte as latin-1. Unknown escapes drop both characters
    and a trailing lone backslash is kept literally — matching unescape_str."""
    out = []
    i, n = 0, len(s)
    while i < n:
        if s[i] == "\\" and i + 1 < n:
            i += 1
            repl = _ESCAPES.get(s[i])
            if repl is not None:
                out.append(repl)
        else:
            out.append(s[i])
        i += 1
    return "".join(out)


class Lexer:
    """A lexer for the kod language."""

    def __init__(self, source: str, filename: Path = Path("<unknown>")):
        self.source = source
        self.filename = filename
        self.pos = 0
        self.start = 0

    def peek(self) -> str:
        """Return the next character in the source, or None if at EOF."""
        if self.pos < len(self.source):
            return self.source[self.pos]
        return ""

    def error(self, msg: str) -> KodError:
        """Raise a syntax error."""
        err = KodError(msg, Span(self.filename, self.pos, self.pos + 1))
        return err

    def skip_whitespace(self) -> None:
        """Skip whitespace and tabs."""
        while self.peek() in (" ", "\t"):
            self.pos += 1
        self.start = self.pos

    def eof(self) -> bool:
        """Return True if at EOF."""
        return self.pos == len(self.source)

    def consume(self, char) -> None:
        """Consume the next character, or raise ValueError if it doesn't match"""
        if self.peek() != char:
            raise self.error(f"Expected {char}, got {self.peek()!r}")
        self.pos += 1

    def buffered(self) -> str:
        """Return the buffered text."""
        return self.source[self.start : self.pos]

    T = TypeVar("T", bound=Token)

    def build(self, token_type: type[T]) -> T:
        """Build a token."""
        value = self.source[self.start : self.pos]
        position = Span(self.filename, self.start, self.pos)
        self.start = self.pos
        token = token_type(value, position)
        return token

    def lex_char_literal(self) -> IntegerLiteral:
        """Lex a single-quoted character literal, producing its ASCII value."""
        self.consume("'")
        char = self.peek()
        if char == "\\":
            self.pos += 1
            escape = self.peek()
            self.pos += 1
            char = _ESCAPES.get(escape, escape)
        else:
            self.pos += 1
        self.consume("'")
        token = self.build(IntegerLiteral)
        token.value = str(ord(char))
        return token

    def _peek_at(self, offset: int) -> str:
        i = self.pos + offset
        if i < len(self.source):
            return self.source[i]
        return ""

    def lex_string(self) -> StringLiteral:
        # Lex a quoted string. Both single and triple-quoted forms.
        self.consume('"')
        # Triple-quoted? Dedent + escape processing happen in the parser.
        if self.peek() == '"' and self._peek_at(1) == '"':
            self.consume('"')
            self.consume('"')
            while True:
                if self.peek() == "":
                    raise self.error("Unterminated triple-quoted string")
                if (
                    self.peek() == '"'
                    and self._peek_at(1) == '"'
                    and self._peek_at(2) == '"'
                ):
                    self.consume('"')
                    self.consume('"')
                    self.consume('"')
                    break
                self.pos += 1
            return self.build(StringLiteral)
        while self.peek() != '"':
            if self.peek() == "\\":
                self.pos += 1
                if self.peek() != "":
                    self.pos += 1
            else:
                self.pos += 1
        self.consume('"')
        string: StringLiteral = self.build(StringLiteral)
        string.value = process_escapes(string.value)
        return string

    def lex_fstring(self) -> FStringLiteral:
        # Lex an f-string literal — both single-line and triple-quoted forms.
        self.consume('"')
        if self.peek() == '"' and self._peek_at(1) == '"':
            self.consume('"')
            self.consume('"')
            depth = 0
            while True:
                ch = self.peek()
                if ch == "":
                    raise self.error("Unterminated triple-quoted f-string")
                if (
                    ch == '"'
                    and depth == 0
                    and self._peek_at(1) == '"'
                    and self._peek_at(2) == '"'
                ):
                    self.consume('"')
                    self.consume('"')
                    self.consume('"')
                    break
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                self.pos += 1
            return self.build(FStringLiteral)
        depth = 0
        while True:
            ch = self.peek()
            if ch == "":
                raise self.error("Unterminated f-string")
            if ch == '"' and depth == 0:
                self.pos += 1
                break
            if ch == "\\":
                self.pos += 1
                if self.peek() != "":
                    self.pos += 1
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            self.pos += 1
        return self.build(FStringLiteral)

    def lex_number(self) -> IntegerLiteral:
        """Lex a number, with optional thousands grouping (`1 000 000`).
        The grouped form is a 1-3 digit head followed by zero or more
        `<space><exactly-3-digits>` groups; the lexer eats the spaces
        as part of the token. Bare digit runs of any length stay valid
        (`1234567`)."""
        head_start = self.pos
        while (c := self.peek()) and c.isdigit():
            self.pos += 1
        head_len = self.pos - head_start
        if 1 <= head_len <= 3:
            # Try to consume `<space><3 digits>` groups. Strict on the
            # group size — 2 or 4 digits after the space stops the loop
            # so a typo like `1 2345` doesn't get glued into one number.
            while (
                self.peek() == " "
                and (d1 := self._peek_at(1))
                and d1.isdigit()
                and (d2 := self._peek_at(2))
                and d2.isdigit()
                and (d3 := self._peek_at(3))
                and d3.isdigit()
                and not ((d4 := self._peek_at(4)) and d4.isdigit())
            ):
                self.pos += 4
        return self.build(IntegerLiteral)

    def lex_single_char(self, token_type) -> Token:
        """Lex a single character token."""
        char = self.peek()
        self.consume(char)
        return self.build(token_type)

    def lex_identifier(self) -> Token:
        """Lex an identifier."""
        char = self.peek()
        assert char is not None
        if not (char.isalpha() or char == "_"):
            raise self.error(f"Lexer expected identifier, got {char!r}")
        while char.isalnum() or char == "_":
            self.pos += 1
            char = self.peek()
        if self.buffered() == "f" and self.peek() == '"':
            return self.lex_fstring()
        if keyword_token_type := KEYWORDS.get(self.buffered()):
            return self.build(keyword_token_type)
        return self.build(Identifier)

    def lex_not_equal(self) -> Token:
        """Lex a != operator."""
        self.consume("!")
        self.consume("=")
        return self.build(NotEqual)

    def lex_less_than_or_equal(self) -> Token:
        """Lex < or <=."""
        self.consume("<")
        if self.peek() == "=":
            self.consume("=")
            return self.build(LessEqual)
        return self.build(LessThan)

    def lex_greater_than_or_equal(self) -> Token:
        """Lex > or >=."""
        self.consume(">")
        if self.peek() == "=":
            self.consume("=")
            return self.build(GreaterEqual)
        return self.build(GreaterThan)

    def lex_slash_or_comment(self) -> Token:
        """Lex a comment."""
        self.consume("/")
        if self.peek() == "/":
            self.consume("/")
            while self.peek() in (" ", "\t"):
                self.pos += 1
            while self.peek() not in ("\n", ""):
                self.pos += 1
            return self.build(Comment)
        return self.build(Slash)

    def lex_arrow_or_minus(self) -> Token:
        """Lex an arrow (->), a minus-equal (-=), or a lone minus (-)."""
        self.consume("-")
        if self.peek() == ">":
            self.consume(">")
            return self.build(Arrow)
        if self.peek() == "=":
            self.consume("=")
            return self.build(MinusEqual)
        return self.build(Minus)

    def lex_plus_or_plus_equal(self) -> Token:
        """Lex + or +=."""
        self.consume("+")
        if self.peek() == "=":
            self.consume("=")
            return self.build(PlusEqual)
        return self.build(Plus)

    def lex_equals(self) -> Token:
        """Lex an equals sign or two."""
        self.consume("=")
        if self.peek() == "=":
            self.consume("=")
            return self.build(EqualEqual)
        return self.build(Equal)

    def lex(self) -> list[Token]:
        """Lex the source code into tokens."""
        return list(self)

    def __iter__(self) -> Iterator[Token]:
        while True:
            self.skip_whitespace()
            match self.peek():
                case "":
                    yield self.build(EOF)
                    return
                case "\n":
                    yield self.lex_single_char(EOL)
                case "(":
                    yield self.lex_single_char(OpenParen)
                case ")":
                    yield self.lex_single_char(CloseParen)
                case "{":
                    yield self.lex_single_char(OpenCurly)
                case "}":
                    yield self.lex_single_char(CloseCurly)
                case "[":
                    yield self.lex_single_char(OpenBracket)
                case "]":
                    yield self.lex_single_char(CloseBracket)
                case ".":
                    yield self.lex_single_char(Dot)
                case ":":
                    yield self.lex_single_char(Colon)
                case ",":
                    yield self.lex_single_char(Comma)
                case "=":
                    yield self.lex_equals()
                case "+":
                    yield self.lex_plus_or_plus_equal()
                case "%":
                    yield self.lex_single_char(Percent)
                case "*":
                    yield self.lex_single_char(Star)
                case "!":
                    yield self.lex_not_equal()
                case "<":
                    yield self.lex_less_than_or_equal()
                case ">":
                    yield self.lex_greater_than_or_equal()
                case "-":
                    yield self.lex_arrow_or_minus()
                case "'":
                    yield self.lex_char_literal()
                case '"':
                    yield self.lex_string()
                case "0" | "1" | "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9":
                    yield self.lex_number()
                case "/":
                    yield self.lex_slash_or_comment()
                case "?":
                    yield self.lex_single_char(Question)
                case _:
                    yield self.lex_identifier()
