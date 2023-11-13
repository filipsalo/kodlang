#!/usr/bin/env python
"""A parser for the Kod lanuage"""

from kod.tokens import (  # pylint: disable=no-name-in-module
    EOF,
    EOL,
    Identifier,
    OpenParen,
    CloseParen,
    OpenCurly,
    CloseCurly,
    Colon,
    Comma,
    QuotedString,
    LiteralNumber,
    Comment,
    Arrow,
    Extern,
    Func,
)


class FunctionDeclaration:
    """A function declaration."""

    external = False

    def __init__(self, name, params, body, return_type):
        self.name = name
        self.params = params
        self.body = body
        self.return_type = return_type


class ExternalFunctionDeclaration(FunctionDeclaration):
    """An external function declaration."""

    external = True


class FunctionCall:
    """A function call."""

    def __init__(self, callee, args):
        self.callee = callee
        self.args = args


class FunctionParam:
    """A function parameter."""

    def __init__(self, name, type_):
        self.name = name
        self.type = type_


class VariableExpr:
    """A variable expression."""

    def __init__(self, name):
        self.name = name


class Parser:
    """A parser for the kod language."""

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def eof(self):
        """Return True if at EOF."""
        return self.peek(EOF)

    def consume(self, token_type):
        """Consume the next token, or raise ValueError if it doesn't match."""
        token = self.peek()
        if not isinstance(token, token_type.value):
            raise ValueError(f"Expected {token_type}, got {token}")
        self.pos += 1
        return token

    def parse_token(self, token_type):
        """Parse the next token, or raise ValueError if it doesn't match."""
        token = self.consume(token_type)
        return token.value

    def parse_param(self):
        """Parse a function parameter."""
        name = self.parse_token(Identifier)
        self.consume(Colon)
        param_type = self.parse_token(Identifier)
        return FunctionParam(name, param_type)

    def parse_param_list(self):
        """Parse a list of function parameters."""
        params = [self.parse_param()]
        while self.peek(Comma):
            self.consume(Comma)
            params.append(self.parse_param())
        return params

    def parse_func(self):
        """Parse a function declaration."""
        body = []
        params = []
        self.consume(Func)
        name = self.consume(Identifier).value
        self.consume(OpenParen)
        if not self.peek(CloseParen):
            params = self.parse_param_list()
        self.consume(CloseParen)
        self.consume(Arrow)
        return_type = self.consume(Identifier).value
        self.consume(OpenCurly)
        while not self.peek(CloseCurly):
            if statement := self.parse_statement():
                body.append(statement)
        self.consume(CloseCurly)
        return FunctionDeclaration(name, params, body, return_type)

    def parse_expression(self):
        """Parse an expression."""
        if self.peek(QuotedString):
            return self.parse_token(QuotedString)
        if self.peek(LiteralNumber):
            return self.parse_token(LiteralNumber)
        name_lookup = self.parse_token(Identifier)
        name = VariableExpr(name_lookup)
        if self.peek(OpenParen):
            self.consume(OpenParen)
            args = []
            while not self.peek(CloseParen):
                args.append(self.parse_expression())
                while self.peek(Comma):
                    self.consume(Comma)
                    args.append(self.parse_expression())
            self.consume(CloseParen)
            return FunctionCall(name, args)
        return name

    def parse_external(self):
        """Parse an external function declaration."""
        self.consume(Extern)
        self.consume(Func)
        name = self.consume(Identifier).value
        self.consume(OpenParen)
        params = self.parse_param_list()
        self.consume(CloseParen)
        self.consume(Arrow)
        return_type = self.consume(Identifier).value
        return ExternalFunctionDeclaration(name, params, [], return_type)

    def parse_statement(self):
        """Parse a statement."""
        match type(self.peek()):
            case Extern.value:
                return self.parse_external()
            case Func.value:
                return self.parse_func()
            case Identifier.value:
                return self.parse_expression()
            case Comment.value:
                self.consume(Comment)
            case EOL.value:
                self.consume(EOL)
                return
            case _:
                raise ValueError(f"Unexpected token {self.peek()}")

    def peek(self, token_type=None):
        """Return the next token, or raise ValueError if it doesn't match."""
        token = self.tokens[self.pos]
        if token_type is not None:
            return isinstance(token, token_type.value)
        return token

    def parse(self):
        """Parse the program."""
        return list(self)

    def __iter__(self):
        while True:
            if self.eof():
                return
            if statement := self.parse_statement():
                yield statement
