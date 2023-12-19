#!/usr/bin/env python
"""A parser for the Kod lanuage"""

from contextlib import contextmanager
from kod.ast import (
    ParsedAssignment,
    ParsedExternalFunctionDeclaration,
    ParsedFunctionCall,
    ParsedFunctionCallParam,
    ParsedFunctionCallParamList,
    ParsedFunctionDeclaration,
    ParsedFunctionParam,
    ParsedFunctionParamList,
    ParsedImport,
    ParsedModule,
    ParsedStringLiteral,
    ParsedVariable,
    ParsedVariableDeclaration,
)
from kod.exceptions import KodSyntaxError
from kod.span import Span
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
    Import,
    Let,
    LiteralNumber,
    OpenCurly,
    OpenParen,
    QuotedString,
)
from kod.types import BUILTIN_TYPES


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

    def parse_token(self, token_type):
        """Parse the next token, or raise ValueError if it doesn't match."""
        token = self.consume(token_type)
        match token:
            case Identifier():
                return ParsedVariable(token.value, None, span=token.span)
        raise self.error(f"Unexpected token {token_type}", token.span)

    def parse_quoted_string(self):
        """Parse a quoted string."""
        token = self.consume(QuotedString)
        return ParsedStringLiteral(
            token.value.strip("\"").encode('utf8'),
            BUILTIN_TYPES["str"],
            span=token.span
        )

    def parse_type(self):
        """Parse a type."""
        param_type = self.parse_token(Identifier)
        if param_type.id not in BUILTIN_TYPES:
            raise self.error(f"Unexpected type {param_type.id}", param_type.span)
        return BUILTIN_TYPES[param_type.id]

    def parse_param(self):
        """Parse a function parameter."""
        with self.span() as span:
            anonymous = False
            if self.peek(Anon):
                anonymous = True
                self.consume(Anon)
            variable = self.parse_token(Identifier)
            self.consume(Colon)
            variable.type = self.parse_type()
        return ParsedFunctionParam(variable, anonymous, span)

    def parse_param_list(self):
        """Parse a list of function parameters."""
        with self.span() as span:
            params = [self.parse_param()]
            while self.peek(Comma):
                self.consume(Comma)
                params.append(self.parse_param())
        return ParsedFunctionParamList(params, span)

    def parse_func(self):
        """Parse a function declaration."""
        with self.span() as span:
            body = []
            params = []
            self.consume(Func)
            name = self.consume(Identifier).value
            self.consume(OpenParen)
            if not self.peek(CloseParen):
                params = self.parse_param_list()
            self.consume(CloseParen)
            self.consume(Arrow)
            return_type = self.parse_type()
            self.consume(OpenCurly)
            self.stack.append({param.variable.id: param.variable for param in params})
            while not self.peek(CloseCurly):
                if statement := self.parse_statement():
                    body.append(statement)
            self.consume(CloseCurly)
            variables = self.stack.pop().values()
        return ParsedFunctionDeclaration(name, params, body, return_type, variables, span)

    def parse_call_param(self):
        """Parse a function call parameter."""
        label = None
        with self.span() as span:
            if self.peek(Identifier):
                expr = self.parse_token(Identifier)
                if self.peek(Colon):
                    label = expr
                    self.consume(Colon)
                    expr = self.parse_expression()
            else:
                expr = self.parse_expression()
        return ParsedFunctionCallParam(label, expr, span)

    def parse_call_param_list(self):
        """Parse a list of function parameters."""
        with self.span() as span:
            params = [self.parse_call_param()]
            while self.peek(Comma):
                self.consume(Comma)
                params.append(self.parse_call_param())
        return ParsedFunctionCallParamList(params, span)

    def parse_call(self, callee):
        """Parse a function call."""
        with self.span() as span:
            self.consume(OpenParen)
            if not self.peek(CloseParen):
                args = self.parse_call_param_list()
            else:
                args = []
            self.consume(CloseParen)
        return ParsedFunctionCall(callee, args, span)

    def parse_expression(self):
        """Parse an expression."""
        if self.peek(QuotedString):
            return self.parse_quoted_string()
        if self.peek(LiteralNumber):
            return self.parse_token(LiteralNumber)
        with self.span() as expr_span:
            name = self.parse_token(Identifier)
            if self.peek(OpenParen):
                return self.parse_call(name)
            elif self.peek(Equals):
                # fixme: this is a statement, not an expression
                self.consume(Equals)
                value = self.parse_expression()
                return ParsedAssignment(name, value, expr_span)
        return name

    def parse_external(self):
        """Parse an external function declaration."""
        with self.span() as span:
            self.consume(Extern)
            self.consume(Func)
            name = self.consume(Identifier).value
            self.consume(OpenParen)
            params = self.parse_param_list()
            self.consume(CloseParen)
            self.consume(Arrow)
            return_type = self.parse_type()
        return ParsedExternalFunctionDeclaration(name, params, [], return_type, span)

    def parse_variable_declaration(self):
        """Parse a variable declaration."""
        with self.span() as span:
            self.consume(Let)
            variable = self.parse_token(Identifier)
            self.stack[-1][variable.id] = variable
            self.consume(Equals)
            value = self.parse_expression()
            variable.type = value.type
        return ParsedVariableDeclaration(variable, value, span)

    def parse_import(self):
        """Parse an import statement."""
        with self.span() as span:
            self.consume(Import)
            module_name = self.parse_quoted_string()
        return ParsedImport(module_name, span)

    def parse_statement(self):
        """Parse a statement."""
        match self.peek():
            case Import():
                return self.parse_import()
            case Let():
                return self.parse_variable_declaration()
            case Extern():
                return self.parse_external()
            case Func():
                return self.parse_func()
            case Identifier():
                return self.parse_expression()
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
        return ParsedModule(self.path, self.module_name, statements, span)

    def __iter__(self):
        while True:
            if self.eof():
                return
            if statement := self.parse_statement():
                yield statement
