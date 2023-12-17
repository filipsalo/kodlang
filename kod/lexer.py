#!/usr/bin/env python
"""A lexer for the kod language."""

from kod.exceptions import KodSyntaxError
from kod.tokens import (
    Anon,
    Arrow,
    CloseCurly,
    CloseParen,
    Colon,
    Comma,
    Comment,
    Dot,
    EOF,
    EOL,
    Equals,
    Extern,
    Func,
    Identifier,
    Let,
    LiteralNumber,
    OpenCurly,
    OpenParen,
    Position,
    QuotedString,
)


class Lexer:
    """A lexer for the kod language."""

    def __init__(self, source, filename="<unknown>"):
        self.source = source
        self.filename = filename
        self.pos = 0
        self.start = 0

    def peek(self):
        """Return the next character in the source, or None if at EOF."""
        if self.pos < len(self.source):
            return self.source[self.pos]
        return None

    def error(self, msg):
        """Raise a syntax error."""
        err = KodSyntaxError(msg)
        line_number = self.source.count("\n", 0, self.pos) + 1
        line_start = self.source.rfind("\n", 0, self.pos) + 1
        column_number = self.pos - line_start + 1
        err.line = line_number
        err.col = column_number
        lines = self.source.split("\n")
        for n, line in enumerate(
            lines[max(0, line_number - 3) : line_number + 3],
            max(0, line_number - 2),
        ):
            err.excerpt += f"{n:3d}: {line}\n"
            if n == line_number:
                err.excerpt += f"     {' ' * (column_number - 1)}^\n"
        return err

    def skip_whitespace(self):
        """Skip whitespace and tabs."""
        while self.peek() in (" ", "\t"):
            self.pos += 1
        self.start = self.pos

    def eof(self):
        """Return True if at EOF."""
        return self.pos == len(self.source)

    def consume(self, char):
        """Consume the next character, or raise ValueError if it doesn't match"""
        if self.peek() != char:
            raise self.error(f"Expected {char}, got {self.peek()!r}")
        self.pos += 1

    def buffered(self):
        """Return the buffered text."""
        return self.source[self.start : self.pos]

    def build(self, token_type):
        """Build a token."""
        value = self.source[self.start : self.pos]
        position = Position(
            self.filename,
            self.start,
            self.pos,
        )
        self.start = self.pos
        return token_type(value, position)

    def lex_string(self):
        """Lex a quoted string."""
        self.consume('"')
        while self.peek() != '"':
            self.pos += 1
        self.consume('"')
        return self.build(QuotedString)

    def lex_number(self):
        """Lex a number."""
        while self.peek() in "0123456789":
            self.pos += 1
        return self.build(LiteralNumber)

    def lex_single_char(self, token_type):
        """Lex a single character token."""
        char = self.peek()
        self.consume(char)
        return self.build(token_type)

    def lex_identifier(self):
        """Lex an identifier."""
        if not (self.peek().isalpha() or self.peek() == "_"):
            raise self.error(f"Lexer expected identifier, got {self.peek()!r}")
        while self.peek().isalnum() or self.peek() == "_":
            self.pos += 1
        match self.buffered():
            case "let":
                return self.build(Let)
            case "extern":
                return self.build(Extern)
            case "func":
                return self.build(Func)
            case "anon":
                return self.build(Anon)
            case _:
                return self.build(Identifier)

    def lex_comment(self):
        """Lex a comment."""
        self.consume("/")
        self.consume("/")
        while self.peek() in (" ", "\t"):
            self.pos += 1
        while self.peek() != "\n":
            self.pos += 1
        return self.build(Comment)

    def lex_arrow(self):
        """Lex an arrow (->)."""
        self.consume("-")
        self.consume(">")
        return self.build(Arrow)

    def lex(self):
        """Lex the source code into tokens."""
        return list(self)

    def __iter__(self):
        while True:
            self.skip_whitespace()
            match self.peek():
                case None:
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
                case ".":
                    yield self.lex_single_char(Dot)
                case ":":
                    yield self.lex_single_char(Colon)
                case ",":
                    yield self.lex_single_char(Comma)
                case "=":
                    yield self.lex_single_char(Equals)
                case "-":
                    yield self.lex_arrow()
                case '"':
                    yield self.lex_string()
                case ("0" | "1" | "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9"):
                    yield self.lex_number()
                case "/":
                    yield self.lex_comment()
                case _:
                    yield self.lex_identifier()
