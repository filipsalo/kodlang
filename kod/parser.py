#!/usr/bin/env python
"""A parser for the Kod lanuage"""

from contextlib import contextmanager
from typing import Generator, Optional

from kod import ast
from kod import values as types
from kod.exceptions import KodError
from kod.filesys import FileWrapper
from kod.span import Span
from kod.tokens import (
    EOF,
    EOL,
    BooleanLiteral,
    Break,
    CloseBracket,
    CloseCurly,
    CloseParen,
    Comma,
    Comment,
    Continue,
    Dot,
    Enum,
    Extern,
    For,
    Func,
    Identifier,
    If,
    Import,
    Interface,
    Let,
    Match,
    NoneLiteral,
    OpenBracket,
    OpenCurly,
    OpenParen,
    Question,
    Return,
    Struct,
    Token,
    Type,
)


class Parser:
    """A parser for the kod language."""

    def __init__(
        self, tokens: list[Token], file: FileWrapper, program=None, resolve_import=None
    ):
        self.tokens = tokens
        self.file = file
        self.pos = 0
        self.stack = [{}]
        self.spans = []
        self.type_registry: dict[str, type] = {}
        self.program = program
        self.resolve_import = resolve_import  # Callable[[str] -> ast.Module] | None
        self.import_aliases: dict[str, str] = {}  # local_name -> module_name

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
        err = KodError(msg, span or self.peek().span)
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

    def lookup_type(self, name: str):
        """Look up a type by name in the local registry, then builtins."""
        if name in self.type_registry:
            return self.type_registry[name]
        if self.program is not None and hasattr(self.program, "builtins"):
            return self.program.builtins.names.get(name)
        return None

    def parse_type(self, name=None) -> type[types.Type]:
        """Parse a type, including optional T? suffix."""
        base = self._parse_base_type(name)
        if self.try_consume(Question):
            return types.OptionalType.make(base)
        return base

    def _parse_base_type(self, name=None) -> type[types.Type]:
        """Parse a base type without optional suffix."""
        if self.try_consume(Struct):
            self.consume(OpenCurly)
            fields = []
            methods = {}
            while not self.try_consume(CloseCurly):
                if self.try_consume(EOL) or self.try_consume(Comment):
                    continue
                if self.peeking_at(Func):
                    method = ast.FunctionDeclaration.parse_method(self, name)
                    methods[method.name] = method
                else:
                    fields.append(ast.Variable.parse(self))
            self.try_consume(EOL)
            return types.StructType.make(name, fields, methods)
        elif self.try_consume(Enum):
            self.consume(OpenCurly)
            variants = []
            while not self.try_consume(CloseCurly):
                if self.try_consume(EOL) or self.try_consume(Comment):
                    continue
                variant_name = self.consume(Identifier).value
                fields = []
                if self.try_consume(OpenParen):
                    while not self.try_consume(CloseParen):
                        fields.append(ast.Variable.parse(self))
                        if not self.try_consume(Comma):
                            self.consume(CloseParen)
                            break
                variants.append((variant_name, fields))
            return types.EnumType.make(name, variants)
        elif self.try_consume(OpenBracket):
            item_type = self.parse_type()
            self.consume(CloseBracket)
            return types.ArrayType.make(item_type)
        if self.try_consume(NoneLiteral):
            return types.NoneType
        param_type = ast.Name.parse(self)
        result = self.lookup_type(param_type.id)
        if result is not None:
            if isinstance(result, types.GenericTemplate):
                self.consume(OpenBracket)
                type_args = []
                while True:
                    type_args.append(self.parse_type())
                    if self.try_consume(CloseBracket):
                        break
                    self.consume(Comma)
                return result.instantiate(tuple(type_args))
            return result
        if (
            self.program is not None
            and param_type.id in self.import_aliases
            and self.try_consume(Dot)
        ):
            type_name = self.consume(Identifier).value
            module_name = self.import_aliases[param_type.id]
            import_file = self.program.resolve_import(
                module_name, relative_to=self.file.path
            )
            mod = self.program.get_module(import_file.canonical_path.with_suffix(""))
            result = mod.names.get(type_name)
            if isinstance(result, types.GenericTemplate):
                self.consume(OpenBracket)
                type_args = []
                while True:
                    type_args.append(self.parse_type())
                    if self.try_consume(CloseBracket):
                        break
                    self.consume(Comma)
                return result.instantiate(tuple(type_args))
            return result
        return types.Type.from_name(param_type.id)

    def parse_statement(self) -> "Optional[ast.Statement]":
        """Parse a statement."""
        stmt = None
        match self.peek():
            case BooleanLiteral():
                stmt = ast.BooleanLiteral.parse(self)
            case Import():
                stmt = ast.Import.parse(self)
                self.import_aliases[stmt.local_name] = stmt.module_name
                if self.resolve_import:
                    self.resolve_import(stmt.module_name)
            case Return():
                stmt = ast.Return.parse(self)
            case If():
                stmt = ast.IfStatement.parse(self)
            case For():
                stmt = ast.ForStatement.parse(self)
            case Let():
                stmt = ast.VariableDeclaration.parse(self)
            case Type():
                stmt = ast.TypeDeclaration.parse(self)
            case Interface():
                stmt = ast.InterfaceDeclaration.parse(self)
            case Extern():
                stmt = ast.ExternalFunctionDeclaration.parse(self)
            case Func():
                stmt = ast.FunctionDeclaration.parse(self)
            case Break():
                stmt = ast.BreakStatement.parse(self)
            case Continue():
                stmt = ast.ContinueStatement.parse(self)
            case Match():
                stmt = ast.MatchStatement.parse(self)
            case Identifier():
                stmt = ast.Expression.parse(self)
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

    def parse(self) -> "ast.Module":
        """Parse the program."""
        with self.span() as span:
            statements = list(self)
        return ast.Module(self.file, statements, span)

    def __iter__(self) -> Generator["ast.Statement", None, None]:
        while True:
            if self.eof():
                return
            if statement := self.parse_statement():
                yield statement
