#!/usr/bin/env python
"""A lexer for the kod language."""

from kod.exceptions import KodSyntaxError
from kod.tokens import (  # pylint: disable=no-name-in-module
    EOF,
    EOL,
    Identifier,
    OpenParen,
    CloseParen,
    OpenCurly,
    CloseCurly,
    Dot,
    Colon,
    Comma,
    QuotedString,
    LiteralNumber,
    Comment,
    Arrow,
    Extern,
    Func,
)

KEYWORDS = ["func", "extern"]


class Lexer:
    """A lexer for the kod language."""
    def __init__(self, source):
        self.source = source
        self.pos = 0

    def peek(self):
        """Return the next character in the source, or None if at EOF."""
        if self.pos < len(self.source):
            return self.source[self.pos]
        return None

    def skip_whitespace(self):
        """Skip whitespace and tabs."""
        while self.peek() in (" ", "\t"):
            self.pos += 1

    def eof(self):
        """Return True if at EOF."""
        return self.pos == len(self.source)

    def consume(self, char):
        """Consume the next character, or raise ValueError if it doesn't match."""
        if self.peek() != char:
            raise ValueError(f"Expected {char}, got {self.peek()!r}")
        self.pos += 1

    def lex_string(self):
        """Lex a quoted string."""
        self.consume('"')
        start = self.pos
        while self.peek() != '"':
            self.pos += 1
        self.consume('"')
        return QuotedString(self.source[start: self.pos - 1])

    def lex_number(self):
        """Lex a number."""
        start = self.pos
        while self.peek() in "0123456789":
            self.pos += 1
        return LiteralNumber(int(self.source[start: self.pos]))

    def lex_single_char(self, token_type):
        """Lex a single character token."""
        char = self.peek()
        self.consume(char)
        return token_type(char)

    def lex_identifier(self):
        """Lex an identifier."""
        if not (self.peek().isalpha() or self.peek() == "_"):
            raise KodSyntaxError(f"Lexer expected identifier, got {self.peek()!r}")
        assert self.peek().isalpha() or self.peek() == "_"
        start = self.pos
        while self.peek().isalnum() or self.peek() == "_":
            self.pos += 1
        match value := self.source[start: self.pos]:
            case "extern":
                return Extern(value)
            case "func":
                return Func(value)
            case _:
                return Identifier(value)

    def lex_comment(self):
        """Lex a comment."""
        self.consume("/")
        self.consume("/")
        self.skip_whitespace()
        start = self.pos
        while self.peek() != "\n":
            self.pos += 1
        return Comment(self.source[start: self.pos])

    def lex_arrow(self):
        """Lex an arrow (->)."""
        self.consume("-")
        self.consume(">")
        return Arrow("->")

    def lex(self):
        """Lex the source code into tokens."""
        return list(self)

    def __iter__(self):
        try:
            while True:
                self.skip_whitespace()
                # print(repr(self.peek()))
                match self.peek():
                    case None:
                        yield EOF()
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
                    case ".":
                        yield self.lex_single_char(Dot)
                    case ":":
                        yield self.lex_single_char(Colon)
                    case ",":
                        yield self.lex_single_char(Comma)
                    case "-":
                        yield self.lex_arrow()
                    case '"':
                        yield self.lex_string()
                    case '0' | '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9':
                        yield self.lex_number()
                    case "/":
                        yield self.lex_comment()
                    case _:
                        yield self.lex_identifier()
        except KodSyntaxError as e:
            line_number = self.source.count("\n", 0, self.pos) + 1
            line_start = self.source.rfind("\n", 0, self.pos) + 1
            column_number = self.pos - line_start + 1
            e.line = line_number
            e.col = column_number
            lines = self.source.split("\n")
            for n, line in enumerate(lines[max(0, line_number - 3): line_number + 3], max(0, line_number - 2)):
                e.excerpt += f"{n:3d}: {line}\n"
                if n == line_number:
                    e.excerpt += f"     {' ' * (column_number - 1)}^\n"

            raise
