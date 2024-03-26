#!/usr/bin/env python
"""A parser for the Kod lanuage"""

from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from kod import ast, types
from kod.exceptions import KodSyntaxError
from kod.span import Span
from kod.tokens import (
    EOF,
    EOL,
    BooleanLiteral,
    CloseBracket,
    CloseCurly,
    Comment,
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
    Token,
    Type,
)


class Parser:
    """A parser for the kod language."""

    def __init__(self, tokens: list[Token], path: Path, module_name: str):
        self.tokens = tokens
        self.path = path
        self.module_name = module_name
        self.pos = 0
        self.stack = [{}]
        self.spans = []

    def eof(self) -> bool:
        """Return True if at EOF."""
        return self.peeking_at(EOF)

    @contextmanager
    def span(self) -> Generator[Span, None, None]:
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

    def try_consume(self, token_type):
        """Consume the next token if it matches, otherwise return None."""
        if not self.peeking_at(token_type):
            return None
        return self.consume(token_type)

    def consume(self, token_type) -> Token:
        """Consume the next token, or raise ValueError if it doesn't match."""
        token = self.peek()
        if not isinstance(token, token_type):
            raise self.error(f"Expected {token_type}, got {token}", span=token.span)
        self.pos += 1
        if self.spans:
            self.spans[-1] |= token.span
        return token

    def parse_type(self, name=None) -> type[types.Type]:
        """Parse a type."""
        if self.try_consume(Struct):
            self.consume(OpenCurly)
            fields = []
            while not self.try_consume(CloseCurly):
                if self.try_consume(EOL):
                    continue
                fields.append(ast.ParsedVariable.parse(self))
            self.try_consume(EOL)
            return types.StructType.make(name, fields)
        elif self.try_consume(OpenBracket):
            item_type = self.parse_type()
            self.consume(CloseBracket)
            return types.ArrayType.make(item_type)
        param_type = ast.ParsedName.parse(self)
        return types.Type.from_name(param_type.id)

    def parse_statement(self) -> "Optional[ast.Statement]":
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

    def peek(self) -> Token:
        """Return the next token"""
        token = self.tokens[self.pos]
        return token

    def peeking_at(self, token_type: type[Token]) -> bool:
        """Return True if the next token is of the given type."""
        token = self.peek()
        return isinstance(token, token_type)

    def parse(self) -> "ast.ParsedModule":
        """Parse the program."""
        with self.span() as span:
            statements = list(self)
        return ast.ParsedModule(self.path, self.module_name, statements, {}, span)

    def __iter__(self) -> Generator["ast.Statement", None, None]:
        while True:
            if self.eof():
                return
            if statement := self.parse_statement():
                yield statement
