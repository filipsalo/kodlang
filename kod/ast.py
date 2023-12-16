"""Abstract syntax tree."""

import dataclasses

from kod.types import Type


def dump(node, indent=""):
    """Dump the AST node."""

    print(f"{indent}{node.__class__.__name__}(")
    for field in dataclasses.fields(node):
        value = getattr(node, field.name)
        if isinstance(value, list) and len(value) > 0:
            newindent = indent + "    "
            print(f"{newindent}{field.name}=[")
            for item in value:
                dump(item, newindent + "    ")
            print(f"{newindent}],")
        else:
            print(f"{indent + '    '}{field.name}={value!r},")
    print(f"{indent}),")


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
    variable: Variable
    anonymous: bool


@dataclasses.dataclass
class FunctionCallParam(ASTNode):
    """A function parameter."""
    label: Variable
    expression: ASTNode


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
    variables: list[Variable]


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


@dataclasses.dataclass
class VariableDeclaration(ASTNode):
    """An assignment."""
    variable: Variable
    value: ASTNode


@dataclasses.dataclass
class Assignment(ASTNode):
    """An assignment."""
    variable: Variable
    value: ASTNode
