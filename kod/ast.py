"""Abstract syntax tree."""

import dataclasses


class ASTNode:
    """An AST node."""


@dataclasses.dataclass
class StringLiteral(ASTNode):
    """A string literal."""
    value: str


@dataclasses.dataclass
class Name(ASTNode):
    """A name."""
    id: str


@dataclasses.dataclass
class VariableExpr(ASTNode):
    """A variable expression."""
    name: str


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
