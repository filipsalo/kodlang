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
    Assert,
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
    Equal,
    Extern,
    For,
    Func,
    Identifier,
    If,
    Import,
    Interface,
    Let,
    Match,
    Mut,
    NoneLiteral,
    OpenBracket,
    OpenCurly,
    OpenParen,
    Question,
    Return,
    Struct,
    Test,
    Throw,
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
        """Parse a type and resolve it to a concrete values.Type. Shim over
        parse_type_expr + resolve_type_expr, kept so the many callers that
        want a resolved type (struct layout, params, etc.) are unchanged."""
        return self.resolve_type_expr(self.parse_type_expr(name))

    def parse_type_expr(self, name=None) -> ast.TypeExpr:
        """Parse a type into its data-only ast.TypeExpr form, including the
        optional `T?` suffix and trailing `or Error` for fallible results.
        No name resolution happens here beyond what's needed to decide
        token consumption (generic templates require `[...]`)."""
        base = self._parse_base_type_expr(name)
        if self.try_consume(Question):
            base = ast.OptionalTypeExpr(base)
        # `T or Error` — fallible result. Only the umbrella Error is allowed;
        # idempotent under repetition.
        from kod.tokens import Or as OrTok

        while self.peeking_at(OrTok):
            self.consume(OrTok)
            err_name = self.consume(Identifier).value
            if err_name != "Error":
                raise self.error(
                    f"unsupported `or` clause in type: only `or Error` is allowed, got `or {err_name}`",
                    self.peek().span,
                )
            base = ast.ResultTypeExpr(base)
        return base

    def _parse_base_type_expr(self, name=None) -> ast.TypeExpr:
        """Parse a base type (no `?` / `or Error` suffix) into a TypeExpr.
        Struct / enum literals and bare `none` are resolved eagerly here
        (struct layout needs field widths) and wrapped in a
        ResolvedTypeExpr; everything else stays purely syntactic."""
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
                    field = ast.Variable.parse(self)
                    # `field: Type = expr` — optional default value.
                    if self.try_consume(Equal):
                        field.default = ast.Expression.parse(self)
                    fields.append(field)
            self.try_consume(EOL)
            return ast.ResolvedTypeExpr(types.StructType.make(name, fields, methods))
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
            return ast.ResolvedTypeExpr(types.EnumType.make(name, variants))
        elif self.try_consume(OpenBracket):
            element = self.parse_type_expr()
            self.consume(CloseBracket)
            return ast.ArrayTypeExpr(element)
        if self.try_consume(NoneLiteral):
            return ast.ResolvedTypeExpr(types.NoneType)
        param_type = ast.Name.parse(self)
        result = self.lookup_type(param_type.id)
        if result is not None:
            if isinstance(result, types.GenericTemplate):
                return ast.GenericTypeExpr(
                    ast.NamedTypeExpr(param_type.id), self._parse_type_args()
                )
            return ast.NamedTypeExpr(param_type.id)
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
            qualified = ast.QualifiedTypeExpr(param_type.id, type_name)
            if isinstance(result, types.GenericTemplate):
                return ast.GenericTypeExpr(qualified, self._parse_type_args())
            return qualified
        return ast.NamedTypeExpr(param_type.id)

    def _parse_type_args(self) -> tuple:
        """Consume `[arg, arg, ...]` and return the args as a tuple of
        TypeExprs. Caller has already established the base is a generic
        template (so the bracket is required)."""
        self.consume(OpenBracket)
        type_args = []
        while True:
            type_args.append(self.parse_type_expr())
            if self.try_consume(CloseBracket):
                break
            self.consume(Comma)
        return tuple(type_args)

    def resolve_type_expr(self, expr: ast.TypeExpr) -> type[types.Type]:
        """Resolve a data-only TypeExpr into a concrete values.Type, using
        the parser's current scope (local type registry, builtins, import
        aliases). Mirrors the resolution the old parse_type did inline."""
        if isinstance(expr, ast.ResolvedTypeExpr):
            return expr.resolved
        if isinstance(expr, ast.ArrayTypeExpr):
            return types.ArrayType.make(self.resolve_type_expr(expr.element))
        if isinstance(expr, ast.OptionalTypeExpr):
            return types.OptionalType.make(self.resolve_type_expr(expr.inner))
        if isinstance(expr, ast.ResultTypeExpr):
            return types.ResultType.make(self.resolve_type_expr(expr.inner))
        if isinstance(expr, ast.NamedTypeExpr):
            result = self.lookup_type(expr.name)
            if result is not None:
                return result
            return types.Type.from_name(expr.name)
        if isinstance(expr, ast.QualifiedTypeExpr):
            module_name = self.import_aliases[expr.module]
            import_file = self.program.resolve_import(
                module_name, relative_to=self.file.path
            )
            mod = self.program.get_module(import_file.canonical_path.with_suffix(""))
            return mod.names.get(expr.name)
        if isinstance(expr, ast.GenericTypeExpr):
            template = self.resolve_type_expr(expr.base)
            return template.instantiate(
                tuple(self.resolve_type_expr(a) for a in expr.args)
            )
        raise self.error(f"cannot resolve type expression {expr!r}", self.peek().span)

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
            case Throw():
                stmt = ast.ThrowStatement.parse(self)
            case Assert():
                stmt = ast.AssertStatement.parse(self)
            case If():
                stmt = ast.IfStatement.parse(self)
            case For():
                stmt = ast.ForStatement.parse(self)
            case Let() | Mut():
                stmt = ast.VariableDeclaration.parse(self)
            case Type():
                stmt = ast.TypeDeclaration.parse(self)
            case Interface():
                stmt = ast.InterfaceDeclaration.parse(self)
            case Extern():
                stmt = ast.ExternalFunctionDeclaration.parse(self)
            case Func():
                stmt = ast.FunctionDeclaration.parse(self)
            case Test():
                stmt = ast.TestDeclaration.parse(self)
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
