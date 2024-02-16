#!/usr/bin/env python
"""A lexer for the kod language."""

from kod.exceptions import KodSyntaxError
from kod.span import Span
from kod.tokens import (
    EOF,
    EOL,
    Anon,
    Arrow,
    BooleanLiteral,
    CloseBracket,
    CloseCurly,
    CloseParen,
    Colon,
    Comma,
    Comment,
    Dot,
    Else,
    Equal,
    EqualEqual,
    Extern,
    For,
    Func,
    GreaterThan,
    Identifier,
    If,
    Import,
    IntegerLiteral,
    LessThan,
    Let,
    Minus,
    OpenBracket,
    OpenCurly,
    OpenParen,
    Percent,
    Plus,
    Return,
    Slash,
    Star,
    StringLiteral,
    Struct,
    Type,
)

KEYWORDS = {
    "import": Import,
    "let": Let,
    "extern": Extern,
    "func": Func,
    "anon": Anon,
    "return": Return,
    "if": If,
    "else": Else,
    "true": BooleanLiteral,
    "false": BooleanLiteral,
    "for": For,
    "struct": Struct,
    "type": Type,
}


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
        err = KodSyntaxError(msg, Span(self.filename, self.pos, self.pos + 1))
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
        position = Span(self.filename, self.start, self.pos)
        self.start = self.pos
        return token_type(value, position)

    def lex_string(self):
        """Lex a quoted string."""
        self.consume('"')
        while self.peek() != '"':
            self.pos += 1
        self.consume('"')
        string = self.build(StringLiteral)
        string.value = string.value.encode().decode("unicode-escape")
        return string

    def lex_number(self):
        """Lex a number."""
        while self.peek() in "0123456789":
            self.pos += 1
        return self.build(IntegerLiteral)

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
        if keyword_token_type := KEYWORDS.get(self.buffered()):
            return self.build(keyword_token_type)
        return self.build(Identifier)

    def lex_slash_or_comment(self):
        """Lex a comment."""
        self.consume("/")
        if self.peek() == "/":
            self.consume("/")
            while self.peek() in (" ", "\t"):
                self.pos += 1
            while self.peek() != "\n":
                self.pos += 1
            return self.build(Comment)
        return self.build(Slash)

    def lex_arrow_or_minus(self):
        """Lex an arrow (->) or a lone minus (-)."""
        self.consume("-")
        if self.peek() == ">":
            self.consume(">")
            return self.build(Arrow)
        return self.build(Minus)

    def lex_equals(self):
        """Lex an equals sign or two."""
        self.consume("=")
        if self.peek() == "=":
            self.consume("=")
            return self.build(EqualEqual)
        return self.build(Equal)

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
                    yield self.lex_single_char(Plus)
                case "%":
                    yield self.lex_single_char(Percent)
                case "*":
                    yield self.lex_single_char(Star)
                case "<":
                    yield self.lex_single_char(LessThan)
                case ">":
                    yield self.lex_single_char(GreaterThan)
                case "-":
                    yield self.lex_arrow_or_minus()
                case '"':
                    yield self.lex_string()
                case "0" | "1" | "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9":
                    yield self.lex_number()
                case "/":
                    yield self.lex_slash_or_comment()
                case _:
                    yield self.lex_identifier()
