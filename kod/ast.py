"""Abstract syntax tree."""

import dataclasses

from kod.types import Type


class ASTNode:
    """An AST node."""


@dataclasses.dataclass
class StringLiteral(ASTNode):
    """A string literal."""
    value: str
    type: Type


@dataclasses.dataclass
class Variable(ASTNode):
    """A name."""
    id: str
    type: Type


@dataclasses.dataclass
class FunctionParam(ASTNode):
    """A function parameter."""
    name: str
    type: str


@dataclasses.dataclass
class FunctionCall(ASTNode):
    """A function call."""
    callee: ASTNode
    args: list[ASTNode]


@dataclasses.dataclass
class FunctionDeclaration(ASTNode):
    """A function declaration."""
    name: str
    params: list[FunctionParam]
    body: list[ASTNode]
    return_type: str


@dataclasses.dataclass
class ExternalFunctionDeclaration(ASTNode):
    """An external function declaration."""
    name: str
    params: list[FunctionParam]
    body: list[ASTNode]
    return_type: str


@dataclasses.dataclass
class Module(ASTNode):
    """A module."""
    body: list[ExternalFunctionDeclaration | FunctionDeclaration]
