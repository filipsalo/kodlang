"""Abstract syntax tree."""

import dataclasses

from kod.span import Span
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


@dataclasses.dataclass
class ASTNode:
    """An AST node."""

@dataclasses.dataclass
class StringLiteral(ASTNode):
    """A string literal."""
    value: str
    type: Type
    span: Span


@dataclasses.dataclass
class Variable(ASTNode):
    """A name."""
    id: str
    type: Type
    span: Span


@dataclasses.dataclass
class FunctionParam(ASTNode):
    """A function parameter."""
    variable: Variable
    anonymous: bool
    span: Span


@dataclasses.dataclass
class FunctionParamList(ASTNode):
    """A function parameter list."""
    params: list[FunctionParam]
    span: Span

    def __iter__(self):
        return iter(self.params)

    def __len__(self):
        return len(self.params)

@dataclasses.dataclass
class FunctionCallParam(ASTNode):
    """A function parameter."""
    label: Variable
    expression: ASTNode
    span: Span


@dataclasses.dataclass
class FunctionCallParamList(ASTNode):
    """A function parameter list."""
    params: list[FunctionCallParam]
    span: Span

    def __iter__(self):
        return iter(self.params)

    def __len__(self):
        return len(self.params)

@dataclasses.dataclass
class FunctionCall(ASTNode):
    """A function call."""
    callee: ASTNode
    args: list[ASTNode]
    span: Span


@dataclasses.dataclass
class FunctionDeclaration(ASTNode):
    """A function declaration."""
    name: str
    params: FunctionParamList
    body: list[ASTNode]
    return_type: str
    variables: list[Variable]
    span: Span


@dataclasses.dataclass
class ExternalFunctionDeclaration(ASTNode):
    """An external function declaration."""
    name: str
    params: FunctionParamList
    body: list[ASTNode]
    return_type: str
    span: Span


@dataclasses.dataclass
class Module(ASTNode):
    """A module."""
    body: list[ExternalFunctionDeclaration | FunctionDeclaration]
    span: Span


@dataclasses.dataclass
class VariableDeclaration(ASTNode):
    """An assignment."""
    variable: Variable
    value: ASTNode
    span: Span


@dataclasses.dataclass
class Assignment(ASTNode):
    """An assignment."""
    variable: Variable
    value: ASTNode
    span: Span
