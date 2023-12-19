"""Abstract syntax tree."""

import dataclasses
from pathlib import Path

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
class ParsedStringLiteral(ASTNode):
    """A string literal."""
    value: str
    type: Type
    span: Span


@dataclasses.dataclass
class ParsedVariable(ASTNode):
    """A name."""
    id: str
    type: Type
    span: Span


@dataclasses.dataclass
class ParsedFunctionParam(ASTNode):
    """A function parameter."""
    variable: ParsedVariable
    anonymous: bool
    span: Span


@dataclasses.dataclass
class ParsedFunctionParamList(ASTNode):
    """A function parameter list."""
    params: list[ParsedFunctionParam]
    span: Span

    def __iter__(self):
        return iter(self.params)

    def __len__(self):
        return len(self.params)


@dataclasses.dataclass
class ParsedFunctionCallParam(ASTNode):
    """A function parameter."""
    label: ParsedVariable
    expression: ASTNode
    span: Span


@dataclasses.dataclass
class ParsedFunctionCallParamList(ASTNode):
    """A function parameter list."""
    params: list[ParsedFunctionCallParam]
    span: Span

    def __iter__(self):
        return iter(self.params)

    def __len__(self):
        return len(self.params)


@dataclasses.dataclass
class ParsedFunctionCall(ASTNode):
    """A function call."""
    callee: ASTNode
    args: list[ASTNode]
    span: Span


@dataclasses.dataclass
class ParsedFunctionDeclaration(ASTNode):
    """A function declaration."""
    name: str
    params: ParsedFunctionParamList
    body: list[ASTNode]
    return_type: str
    variables: list[ParsedVariable]
    span: Span


@dataclasses.dataclass
class ParsedImport(ASTNode):
    """An import statement."""
    module_name: str
    span: Span


@dataclasses.dataclass
class ParsedExternalFunctionDeclaration(ASTNode):
    """An external function declaration."""
    name: str
    params: ParsedFunctionParamList
    body: list[ASTNode]
    return_type: str
    span: Span


@dataclasses.dataclass
class ParsedVariableDeclaration(ASTNode):
    """An assignment."""
    variable: ParsedVariable
    value: ASTNode
    span: Span


@dataclasses.dataclass
class ParsedAssignment(ASTNode):
    """An assignment."""
    variable: ParsedVariable
    value: ASTNode
    span: Span


@dataclasses.dataclass
class ParsedModule(ASTNode):
    """A module."""
    path : Path
    name: str
    body: list[ParsedImport | ParsedExternalFunctionDeclaration | ParsedFunctionDeclaration | ParsedVariableDeclaration | ParsedAssignment]
    span: Span
