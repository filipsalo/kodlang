#!/usr/bin/env python
"""A parser for the Kod lanuage"""

from contextlib import contextmanager
from kod import ast, types
from kod.exceptions import KodSyntaxError
from kod.span import Span
from kod.tokens import (
    BooleanLiteral,
    CloseBracket,
    CloseCurly,
    Comma,
    Comment,
    EOF,
    EOL,
    Extern,
    For,
    Func,
    Identifier,
    If,
    Import,
    Let,
    OpenBracket,
    OpenCurly,
    Return,
    Struct,
    Type,
)


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

    def parse_type(self, name=None):
        """Parse a type."""
        if self.peek(Struct):
            self.consume(Struct)
            self.consume(OpenCurly)
            fields = []
            while not self.peek(CloseCurly):
                if self.peek(EOL):
                    self.consume(EOL)
                    continue
                fields.append(ast.ParsedVariable.parse(self))
            if self.peek(EOL):
                self.consume(EOL)
            self.consume(CloseCurly)
            return types.StructType.make(name, fields)
        elif self.peek(OpenBracket):
            self.consume(OpenBracket)
            item_type = self.parse_type()
            self.consume(CloseBracket)
            return types.ArrayType.make(item_type)
        param_type = ast.ParsedName.parse(self)
        return types.Type.from_name(param_type.id)

    def parse_statement(self):
        """Parse a statement."""
        stmt = None
        match self.peek():
            case BooleanLiteral():
                stmt = ast.ParsedBooleanLiteral.parse(self)
            case Import():
                stmt = ast.ParsedImport.parse(self)
            case Return():
                stmt = ast.ParsedReturn.parse(self)
            case If():
                stmt = ast.ParsedIfStatement.parse(self)
            case For():
                stmt = ast.ParsedForStatement.parse(self)
            case Let():
                stmt = ast.ParsedVariableDeclaration.parse(self)
            case Type():
                stmt = ast.ParsedTypeDeclaration.parse(self)
            case Extern():
                stmt = ast.ParsedExternalFunctionDeclaration.parse(self)
            case Func():
                stmt = ast.ParsedFunctionDeclaration.parse(self)
            case Identifier():
                stmt = ast.ParsedExpression.parse(self)
            case Comment():
                self.consume(Comment)
            case EOL():
                self.consume(EOL)
            case _:
                raise self.error(f"Unexpected token {self.peek()}")
        return stmt

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
        return ast.ParsedModule(self.path, self.module_name, statements, {}, span)

    def __iter__(self):
        while True:
            if self.eof():
                return
            if statement := self.parse_statement():
                yield statement
