#!/usr/bin/env python
"""A parser for the Kod lanuage"""

from contextlib import contextmanager
from typing import Generator, Optional

from kod import ast
from kod import values as types
from kod.exceptions import KodError, get_source
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


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance, as codegen's str.distance computes it."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        cur = [i + 1]
        for j, cb in enumerate(b):
            cur.append(min(prev[j + 1] + 1, cur[j] + 1, prev[j] + (ca != cb)))
        prev = cur
    return prev[-1]


def with_suggestion(msg: str, typo: str, candidates) -> str:
    """`msg; did you mean `X`?` for the first closest candidate within 2 edits."""
    best, best_dist = "", 3
    for candidate in candidates:
        d = edit_distance(typo, candidate)
        if d < best_dist:
            best, best_dist = candidate, d
    return f"{msg}; did you mean `{best}`?" if best else msg


def qualified_type_error(alias: str, name: str, mod, call: bool = False) -> str:
    """Why `alias.name` names no type of `mod`, the module imported as `alias`."""
    candidates = [
        n for n, v in mod.names.items() if isinstance(v, (type, types.GenericTemplate))
    ]
    what = "type"
    if call:
        what = "function or type"
        funcs = (ast.FunctionDeclaration, ast.ExternalFunctionDeclaration)
        candidates += [n for n, v in mod.names.items() if isinstance(v, funcs)]
    return with_suggestion(f"module `{alias}` has no {what} `{name}`", name, candidates)


def _declares_type(module, name: str) -> bool:
    return isinstance(module.names.get(name), (type, types.GenericTemplate))


def shown_path(program, module) -> str:
    """`module`'s file as the compiler prints it: relative to the project root."""
    path = module.source_file.path
    if path.is_relative_to(program.root_fs.root_path):
        return str(path.relative_to(program.root_fs.root_path))
    return str(module.source_file.canonical_path)


def type_hint(program, path, aliases: dict, name: str) -> str:
    """Where a type `name` that the module at `path` doesn't see is declared, or ""."""
    if program is None:
        return ""
    for alias, module_name in aliases.items():
        target = program.resolve_import(module_name, relative_to=path)
        module = program.modules.get(target.canonical_path.with_suffix(""))
        if module is not None and _declares_type(module, name):
            where = shown_path(program, module)
            return (
                f"{where} declares `{name}`: write `{alias}.{name}` or list it in"
                f" the import (`{{ {name} }}`)"
            )
    for module in program.modules.values():
        # The module itself isn't one to import: its later types are just not read yet.
        if module.source_file.path != path and _declares_type(module, name):
            where = shown_path(program, module)
            return f"{where} declares `{name}`: import it to use it here"
    return ""


class UnknownTypeError(KodError):
    """A bare type name that names nothing here, worded by `word` once every
    module of the program is loaded, so the hint can name any of them."""

    def __init__(self, parser, name: str, span: Span):
        super().__init__(f"unknown type `{name}`", span)
        self.parser = parser
        self.name = name

    def word(self) -> "UnknownTypeError":
        self.msg = self.parser.unknown_type_error(self.name)
        return self


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
        # Each name an import lists (`import "./pa" { Pt }`) -> its module_name.
        self.import_items: dict[str, str] = {}
        # (declaration, target) of aliases whose target is declared later.
        self.pending_aliases: list = []
        self.pending_alias_names: set[str] = set()
        # Type names that name nothing, raised when the program runs: compiling
        # still parses here first, and the compiler reports every such error.
        self.type_errors: list[KodError] = []
        # Return types, checked once the module is parsed so a type declared
        # later resolves: each with its first and last token and the type
        # parameters in scope there.
        self.return_types: list = []

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
        """Look up a type by name in the local registry, the import lists, then builtins."""
        if name in self.type_registry:
            return self.type_registry[name]
        if name in self.import_items:
            item = self._item_type(name)
            if item is not None:
                return item
        if self.program is not None and hasattr(self.program, "builtins"):
            return self.program.builtins.names.get(name)
        return None

    def qualified_type(self, alias: str, name: str, span: Span):
        """The type `alias.name`: one the module imported as `alias` declares."""
        import_file = self.program.resolve_import(
            self.import_aliases[alias], relative_to=self.file.path
        )
        mod = self.program.get_module(import_file.canonical_path.with_suffix(""))
        result = mod.names.get(name)
        if not isinstance(result, (type, types.GenericTemplate)):
            self.type_errors.append(
                KodError(qualified_type_error(alias, name, mod), span)
            )
            return types.InterfaceType
        return result

    def check_enum_qualifier(self, alias: str, name: str, span: Span) -> None:
        """A three-part pattern's `alias.Enum` names a type of the module `alias`."""
        if self.program is None:
            return
        if alias in self.import_aliases:
            self.qualified_type(alias, name, span)
        else:
            self.type_errors.append(KodError(f"unknown type `{alias}.{name}`", span))

    def _item_type(self, name: str):
        """The type `name` names in the module whose import lists it, or None."""
        if self.program is None:
            return None
        import_file = self.program.resolve_import(
            self.import_items[name], relative_to=self.file.path
        )
        mod = self.program.modules.get(import_file.canonical_path.with_suffix(""))
        value = mod.names.get(name) if mod is not None else None
        if isinstance(value, (type, types.GenericTemplate)):
            return value
        return None

    def parse_type(self, name=None) -> type[types.Type]:
        """Parse a type and resolve it to a concrete values.Type. Shim over
        parse_type_expr + resolve_type_expr, kept so the many callers that
        want a resolved type (struct layout, params, etc.) are unchanged."""
        start = self.pos
        expr = self.parse_type_expr(name)
        try:
            return self.resolve_type_expr(expr)
        except types.UnknownTypeName as err:
            span = self._name_token_span(err.name, start, self.pos)
            self.type_errors.append(UnknownTypeError(self, err.name, span))
            return types.InterfaceType

    def parse_return_type(self) -> ast.TypeExpr:
        """A function's return type, whose names check_return_types resolves."""
        start = self.pos
        expr = self.parse_type_expr()
        params = frozenset(
            name
            for name, t in self.type_registry.items()
            if isinstance(t, type) and issubclass(t, types.TypeParam)
        )
        self.return_types.append((expr, start, self.pos, params))
        return expr

    def check_return_types(self) -> None:
        """Note each bare name in a return type that names no type of the module."""
        for expr, start, end, params in self.return_types:
            for name in self.unknown_type_names(expr, params):
                span = self._name_token_span(name, start, end)
                self.type_errors.append(UnknownTypeError(self, name, span))

    def unknown_type_names(self, expr: ast.TypeExpr, params: frozenset) -> list:
        """The bare names in `expr` that name no type here, in order."""
        if isinstance(expr, ast.NamedTypeExpr):
            if expr.name in params or self.lookup_type(expr.name) is not None:
                return []
            try:
                types.Type.from_name(expr.name)
            except types.UnknownTypeName:
                return [expr.name]
            return []
        if isinstance(expr, ast.ArrayTypeExpr):
            return self.unknown_type_names(expr.element, params)
        if isinstance(expr, ast.OptionalTypeExpr):
            return self.unknown_type_names(expr.inner, params)
        if isinstance(expr, ast.GenericTypeExpr):
            names = self.unknown_type_names(expr.base, params)
            for arg in expr.args:
                names += self.unknown_type_names(arg, params)
            return names
        if isinstance(expr, ast.FuncTypeExpr):
            names = []
            for param in expr.params:
                names += self.unknown_type_names(param, params)
            return names + self.unknown_type_names(expr.return_typ, params)
        return []

    def _name_token_span(self, name: str, start: int, end: int) -> Span:
        """The span of the identifier `name` among the tokens from `start` to `end`."""
        for token in self.tokens[start:end]:
            if isinstance(token, Identifier) and token.value == name:
                return token.span
        return self.tokens[start].span

    def _name_span_in(self, name: str, within: Span) -> Span:
        """The span of the last identifier `name` inside `within`."""
        found = within
        for token in self.tokens:
            span = token.span
            if within.start <= span.start and span.end <= within.end:
                if isinstance(token, Identifier) and token.value == name:
                    found = span
        return found

    def unknown_type_error(self, name: str) -> str:
        """Why the bare type name `name` names nothing here, as the compiler says it."""
        hint = type_hint(self.program, self.file.path, self.import_aliases, name)
        if hint:
            return f"unknown type `{name}`; {hint}"
        candidates = ["int64", "bool", "str", "bytes", "none", *self.type_registry]
        candidates += [n for n in self.import_items if self.lookup_type(n) is not None]
        if self.program is not None and hasattr(self.program, "builtins"):
            builtins = self.program.builtins
            candidates += [n for n in builtins.names if _declares_type(builtins, n)]
        # A type declared further down this file is registered by now, but not yet read.
        candidates = [n for n in candidates if n != name]
        return with_suggestion(f"unknown type `{name}`", name, candidates)

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
            # `T or Error` desugars to Result[T, Error] — the unified
            # tagged-sum representation. Idempotent under repetition:
            # `(T or Error) or Error` collapses back to the same shape.
            if ast.is_result_type_expr(base):
                continue
            base = ast.GenericTypeExpr(
                ast.NamedTypeExpr("Result"),
                (base, ast.NamedTypeExpr("Error")),
            )
        return base

    def _check_first(self, seen: dict[str, int], shown: str, span: Span) -> None:
        if shown in seen:
            line = get_source(span.filename).count("\n", 0, seen[shown]) + 1
            raise KodError(f"`{shown}` is already declared on line {line}", span)
        seen[shown] = span.start

    def _parse_base_type_expr(self, name=None) -> ast.TypeExpr:
        """Parse a base type (no `?` / `or Error` suffix) into a TypeExpr.
        Struct / enum literals and bare `none` are resolved eagerly here
        (struct layout needs field widths) and wrapped in a
        ResolvedTypeExpr; everything else stays purely syntactic."""
        if self.try_consume(Struct):
            self.consume(OpenCurly)
            fields = []
            methods = {}
            seen: dict[str, int] = {}
            method_spans = []
            while not self.try_consume(CloseCurly):
                if self.try_consume(EOL) or self.try_consume(Comment):
                    continue
                if self.peeking_at(Func):
                    name_span = self.tokens[self.pos + 1].span
                    method = ast.FunctionDeclaration.parse_method(self, name)
                    methods[method.name] = method
                    method_spans.append((f"{name}.{method.name}", name_span))
                else:
                    field = ast.Variable.parse(self)
                    self._check_first(seen, f"{name}.{field.id}", field.span)
                    # `field: Type = expr` — optional default value.
                    if self.try_consume(Equal):
                        field.default = ast.Expression.parse(self)
                    fields.append(field)
            for shown, name_span in method_spans:
                if shown in seen:
                    self._check_first(seen, shown, name_span)
            self.try_consume(EOL)
            return ast.ResolvedTypeExpr(types.StructType.make(name, fields, methods))
        elif self.try_consume(Enum):
            self.consume(OpenCurly)
            variants = []
            seen = {}
            while not self.try_consume(CloseCurly):
                if self.try_consume(EOL) or self.try_consume(Comment):
                    continue
                variant_tok = self.consume(Identifier)
                variant_name = variant_tok.value
                self._check_first(seen, f"{name}.{variant_name}", variant_tok.span)
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
        elif self.try_consume(Func):
            # `func(T1, T2, ...) -> R` — function-pointer type. The
            # `(` immediately after `func` disambiguates from a
            # declaration site (which never appears in type position).
            self.consume(OpenParen)
            params: list = []
            while not self.try_consume(CloseParen):
                params.append(self.parse_type_expr())
                if not self.try_consume(Comma):
                    self.consume(CloseParen)
                    break
            from kod.tokens import Arrow

            self.consume(Arrow)
            return_typ = self.parse_type_expr()
            return ast.FuncTypeExpr(tuple(params), return_typ)
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
            name_tok = self.consume(Identifier)
            type_name = name_tok.value
            result = self.qualified_type(param_type.id, type_name, name_tok.span)
            qualified = ast.QualifiedTypeExpr(param_type.id, type_name)
            if isinstance(result, types.GenericTemplate):
                return ast.GenericTypeExpr(qualified, self._parse_type_args())
            return qualified
        if self.peeking_at(Dot) and isinstance(self.tokens[self.pos + 1], Identifier):
            self.consume(Dot)
            name_tok = self.consume(Identifier)
            shown = f"{param_type.id}.{name_tok.value}"
            self.type_errors.append(KodError(f"unknown type `{shown}`", name_tok.span))
            return ast.ResolvedTypeExpr(types.InterfaceType)
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
        if isinstance(expr, ast.NamedTypeExpr):
            result = self.lookup_type(expr.name)
            if result is not None:
                return result
            return types.Type.from_name(expr.name)
        if isinstance(expr, ast.QualifiedTypeExpr):
            return self.qualified_type(expr.module, expr.name, self.peek().span)
        if isinstance(expr, ast.GenericTypeExpr):
            template = self.resolve_type_expr(expr.base)
            return template.instantiate(
                tuple(self.resolve_type_expr(a) for a in expr.args)
            )
        if isinstance(expr, ast.FuncTypeExpr):
            params = tuple(self.resolve_type_expr(p) for p in expr.params)
            ret = self.resolve_type_expr(expr.return_typ)
            return types.FunctionType.make(params, ret)
        raise self.error(f"cannot resolve type expression {expr!r}", self.peek().span)

    def parse_statement(self, check_end: bool = True) -> "Optional[ast.Statement]":
        """Parse a statement."""
        stmt = None
        match self.peek():
            case BooleanLiteral():
                stmt = ast.BooleanLiteral.parse(self)
            case Import():
                stmt = ast.Import.parse(self)
                self.import_aliases[stmt.local_name] = stmt.module_name
                for item in stmt.items:
                    self.import_items.setdefault(item, stmt.module_name)
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
        if stmt is not None and check_end:
            self.expect_statement_end(stmt)
        return stmt

    def expect_statement_end(self, stmt: "ast.Statement") -> None:
        prev = self.tokens[self.pos - 1]
        if isinstance(prev, (EOL, CloseCurly)):
            return
        if isinstance(self.peek(), (EOL, Comment, CloseCurly, EOF)):
            return
        what = f"`{stmt.id}`" if isinstance(stmt, ast.Name) else "this statement"
        raise self.error(
            f"expected the end of the line after {what}, got {self.peek()}"
        )

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
        for decl, type_expr in self.pending_aliases:
            # Still unresolved: report the unknown target when the program runs.
            try:
                self.resolve_type_expr(type_expr)
            except types.UnknownTypeName as err:
                span = self._name_span_in(err.name, decl.span)
                self.type_errors.append(UnknownTypeError(self, err.name, span))
        self.check_return_types()
        self.type_errors.sort(key=lambda err: err.span.start)
        module = ast.Module(self.file, statements, span)
        module.__dict__["_kod_type_errors"] = self.type_errors
        return module

    def resolve_pending_aliases(self) -> None:
        """Resolve pending aliases whose targets are now declared."""
        progress = True
        while progress:
            progress = False
            still_pending = []
            for decl, type_expr in self.pending_aliases:
                if self.names_pending_alias(type_expr):
                    still_pending.append((decl, type_expr))
                    continue
                try:
                    resolved = self.resolve_type_expr(type_expr)
                except ValueError:
                    still_pending.append((decl, type_expr))
                    continue
                decl.type = resolved
                self.type_registry[decl.name.id] = resolved
                self.pending_alias_names.discard(decl.name.id)
                progress = True
            self.pending_aliases = still_pending

    def names_pending_alias(self, expr: ast.TypeExpr) -> bool:
        """True when `expr` names an alias whose target isn't declared yet."""
        if isinstance(expr, ast.NamedTypeExpr):
            return expr.name in self.pending_alias_names
        if isinstance(expr, ast.ArrayTypeExpr):
            return self.names_pending_alias(expr.element)
        if isinstance(expr, ast.OptionalTypeExpr):
            return self.names_pending_alias(expr.inner)
        if isinstance(expr, ast.GenericTypeExpr):
            return self.names_pending_alias(expr.base) or any(
                self.names_pending_alias(arg) for arg in expr.args
            )
        if isinstance(expr, ast.FuncTypeExpr):
            return any(
                self.names_pending_alias(param) for param in expr.params
            ) or self.names_pending_alias(expr.return_typ)
        return False

    def __iter__(self) -> Generator["ast.Statement", None, None]:
        while True:
            if self.eof():
                return
            self.expect_declaration()
            if statement := self.parse_statement():
                yield statement

    def expect_declaration(self) -> None:
        token = self.peek()
        if isinstance(token, (Let, Mut)):
            raise self.error(
                f"a top-level `{token.value}` isn't supported; for a module-wide"
                " constant, use a function with no arguments"
            )
        if not isinstance(
            token, (Import, Type, Interface, Extern, Func, Test, Comment, EOL)
        ):
            raise self.error(
                "expected a declaration (`func`, `type`, `interface`, `import`,"
                f" `extern` or `test`), got {token}"
            )
