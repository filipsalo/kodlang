#!/usr/bin/env python
"""A parser for the Kod lanuage"""

from kod.ast import (
    ExternalFunctionDeclaration,
    FunctionDeclaration,
    FunctionCall,
    Module,
    Variable,
    StringLiteral,
    VariableDeclaration,
    Assignment,
)
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
    Let,
    Equals,
)
from kod.types import BUILTIN_TYPES


class Parser:
    """A parser for the kod language."""

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0
        self.stack = []

    def eof(self):
        """Return True if at EOF."""
        return self.peek(EOF)

    def consume(self, token_type):
        """Consume the next token, or raise ValueError if it doesn't match."""
        token = self.peek()
        if not isinstance(token, token_type):
            raise ValueError(f"Expected {token_type}, got {token}")
        self.pos += 1
        return token

    def parse_token(self, token_type):
        """Parse the next token, or raise ValueError if it doesn't match."""
        token = self.consume(token_type)
        match token:
            case Identifier():
                return Variable(token.value, None)
            case QuotedString():
                return StringLiteral(token.value.strip("\"").encode('utf8'), BUILTIN_TYPES["str"])
        raise ValueError(f"Unexpected token {token_type}")

    def parse_type(self):
        """Parse a type."""
        param_type = self.parse_token(Identifier)
        if param_type.id not in BUILTIN_TYPES:
            raise ValueError(f"Unexpected type {param_type.id}")
        return BUILTIN_TYPES[param_type.id]

    def parse_param(self):
        """Parse a function parameter."""
        variable = self.parse_token(Identifier)
        self.consume(Colon)
        variable.type = self.parse_type()
        return variable

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
        return_type = self.parse_type()
        self.consume(OpenCurly)
        self.stack.append({param.id: param for param in params})
        while not self.peek(CloseCurly):
            if statement := self.parse_statement():
                body.append(statement)
        self.consume(CloseCurly)
        variables = self.stack.pop().values()
        return FunctionDeclaration(name, params, body, return_type, variables)

    def parse_expression(self):
        """Parse an expression."""
        if self.peek(QuotedString):
            return self.parse_token(QuotedString)
        if self.peek(LiteralNumber):
            return self.parse_token(LiteralNumber)
        name = self.parse_token(Identifier)
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
        elif self.peek(Equals):
            self.consume(Equals)
            value = self.parse_expression()
            assert name.id in self.stack[-1], f"Undeclared variable {name.id}"
            return Assignment(name, value)
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
        return_type = self.parse_type()
        return ExternalFunctionDeclaration(name, params, [], return_type)

    def parse_variable_declaration(self):
        """Parse a variable declaration."""
        self.consume(Let)
        variable = self.parse_token(Identifier)
        self.stack[-1][variable.id] = variable
        self.consume(Equals)
        value = self.parse_expression()
        variable.type = value.type
        return VariableDeclaration(variable, value)

    def parse_statement(self):
        """Parse a statement."""
        match self.peek():
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
                raise ValueError(f"Unexpected token {self.peek()}")

    def peek(self, token_type=None):
        """Return the next token, or raise ValueError if it doesn't match."""
        token = self.tokens[self.pos]
        if token_type is not None:
            return isinstance(token, token_type)
        return token

    def parse(self):
        """Parse the program."""
        return Module(list(self))

    def __iter__(self):
        while True:
            if self.eof():
                return
            if statement := self.parse_statement():
                yield statement
