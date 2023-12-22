#!/usr/bin/env python
"""A parser for the Kod lanuage"""

from contextlib import contextmanager
from kod.ast import (
    ParsedExpression,
    ParsedExternalFunctionDeclaration,
    ParsedFunctionDeclaration,
    ParsedImport,
    ParsedModule,
    ParsedReturn,
    ParsedVariable,
    ParsedVariableDeclaration,
)
from kod.exceptions import KodSyntaxError
from kod.span import Span
from kod.tokens import (
    CloseBracket,
    Comment,
    EOF,
    EOL,
    Extern,
    Func,
    Identifier,
    Import,
    Let,
    OpenBracket,
    Return,
)
from kod.types import BUILTIN_TYPES, ArrayType


class Parser:
    """A parser for the kod language."""

    def __init__(self, tokens, path, module_name):
        self.tokens = tokens
        self.path = path
        self.module_name = module_name
        self.pos = 0
        self.stack = [{}]
        self.spans = []

    def eof(self):
        """Return True if at EOF."""
        return self.peek(EOF)

    @contextmanager
    def span(self):
        """Return a span for the next token."""
        span = self.peek().span
        span = Span(span.filename, span.start, span.end)
        self.spans.append(span)
        yield span
        self.spans.pop()
        if self.spans:
            self.spans[-1] |= span

    def error(self, msg, span=None):
        """Return a syntax error."""
        err = KodSyntaxError(msg, span or self.peek().span)
        return err

    def consume(self, token_type):
        """Consume the next token, or raise ValueError if it doesn't match."""
        token = self.peek()
        if not isinstance(token, token_type):
            raise self.error(f"Expected {token_type}, got {token}", span=token.span)
        self.pos += 1
        if self.spans:
            self.spans[-1] |= token.span
        return token

    def parse_type(self):
        """Parse a type."""
        if self.peek(OpenBracket):
            self.consume(OpenBracket)
            item_type = self.parse_type()
            self.consume(CloseBracket)
            return ArrayType(item_type)
        param_type = ParsedVariable.parse(self)
        if param_type.id not in BUILTIN_TYPES:
            raise self.error(f"Unexpected type {param_type.id}", param_type.span)
        return BUILTIN_TYPES[param_type.id]

    def parse_statement(self):
        """Parse a statement."""
        match self.peek():
            case Import():
                return ParsedImport.parse(self)
            case Return():
                return ParsedReturn.parse(self)
            case Let():
                return ParsedVariableDeclaration.parse(self)
            case Extern():
                return ParsedExternalFunctionDeclaration.parse(self)
            case Func():
                return ParsedFunctionDeclaration.parse(self)
            case Identifier():
                return ParsedExpression.parse(self)
            case Comment():
                self.consume(Comment)
            case EOL():
                self.consume(EOL)
                return
            case _:
                raise self.error(f"Unexpected token {self.peek()}")

    def peek(self, token_type=None):
        """Return the next token, or raise ValueError if it doesn't match."""
        token = self.tokens[self.pos]
        if token_type is not None:
            return isinstance(token, token_type)
        return token

    def parse(self):
        """Parse the program."""
        with self.span() as span:
            statements = list(self)
        return ParsedModule(self.path, self.module_name, statements, {}, span)

    def __iter__(self):
        while True:
            if self.eof():
                return
            if statement := self.parse_statement():
                yield statement
