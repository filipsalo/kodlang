"""Abstract syntax tree."""

import dataclasses
from pathlib import Path
from kod import tokens, types

from kod.parser import Parser
from kod.span import Span


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
class Literal:
    """A literal."""

    value: any
    span: Span


@dataclasses.dataclass
class ParsedStringLiteral(ASTNode, Literal):
    """A string literal."""

    value: types.String
    span: Span

    @classmethod
    def parse(cls, parser):
        """Parse a string literal."""
        token = parser.consume(tokens.StringLiteral)
        bytes_ = token.value.strip('"').encode("utf8")
        value = types.String(bytes_)
        return cls(value, span=token.span)


@dataclasses.dataclass
class ParsedIntegerLiteral(ASTNode, Literal):
    """An integerliteral."""

    value: types.Int64
    span: Span

    @classmethod
    def parse(cls, parser):
        """Parse an integer literal."""
        token = parser.consume(tokens.IntegerLiteral)
        value = types.Int64(int(token.value))
        return cls(value, span=token.span)


@dataclasses.dataclass
class ParsedBooleanLiteral(ASTNode, Literal):
    """An integerliteral."""

    value: types.Bool
    span: Span

    @classmethod
    def parse(cls, parser):
        """Parse an integer literal."""
        token = parser.consume(tokens.BooleanLiteral)
        value = types.Bool(token.value == "true")
        return cls(value, span=token.span)


@dataclasses.dataclass
class ParsedVariable(ASTNode):
    """A name."""

    id: str
    type: types.Type
    span: Span

    @classmethod
    def parse(cls, parser):
        """Parse a variable."""
        type_ = None
        token = parser.consume(tokens.Identifier)
        if parser.try_consume(tokens.Colon):
            type_ = parser.parse_type()
        return cls(token.value, type_, span=token.span)


@dataclasses.dataclass
class ParsedName(ASTNode):
    """A name."""

    id: str
    span: Span

    @classmethod
    def parse(cls, parser):
        """Parse a variable."""
        token = parser.consume(tokens.Identifier)
        return cls(token.value, span=token.span)


@dataclasses.dataclass
class ParsedFunctionParam(ASTNode):
    """A function parameter."""

    variable: ParsedVariable
    anonymous: bool
    span: Span

    @classmethod
    def parse(cls, parser):
        """Parse a function parameter."""
        with parser.span() as span:
            anonymous = False
            if parser.try_consume(tokens.Anon):
                anonymous = True
            variable = ParsedVariable.parse(parser)
        return cls(variable, anonymous, span)


@dataclasses.dataclass
class ParsedFunctionParamList(ASTNode):
    """A function parameter list."""

    params: list[ParsedFunctionParam]
    span: Span

    def __iter__(self):
        return iter(self.params)

    def __len__(self):
        return len(self.params)

    @classmethod
    def parse(cls, parser):
        """Parse a function parameter list."""
        with parser.span() as span:
            parser.consume(tokens.OpenParen)
            params = []
            while not parser.try_consume(tokens.CloseParen):
                params.append(ParsedFunctionParam.parse(parser))
                if not parser.try_consume(tokens.Comma):
                    parser.consume(tokens.CloseParen)
                    break
        return cls(params, span)


@dataclasses.dataclass
class ParsedFunctionCallParam(ASTNode):
    """A function parameter."""

    label: ParsedName
    expression: ASTNode
    span: Span

    @classmethod
    def parse(cls, parser):
        """Parse a function call parameter."""
        with parser.span() as span:
            label = None
            expr = ParsedExpression.parse(parser)
            if parser.try_consume(tokens.Colon):
                label = ParsedName(expr, expr.span)
                expr = ParsedExpression.parse(parser)
        return cls(label, expr, span)


@dataclasses.dataclass
class ParsedFunctionCallParamList(ASTNode):
    """A function parameter list."""

    params: list[ParsedFunctionCallParam]
    span: Span

    def __iter__(self):
        return iter(self.params)

    def __len__(self):
        return len(self.params)

    @classmethod
    def parse(cls, parser):
        """Parse a function call parameter list."""
        with parser.span() as span:
            parser.consume(tokens.OpenParen)
            params = []
            while not parser.try_consume(tokens.CloseParen):
                params.append(ParsedFunctionCallParam.parse(parser))
                if not parser.try_consume(tokens.Comma):
                    parser.consume(tokens.CloseParen)
                    break
        return cls(params, span)


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
    label_name: str
    params: ParsedFunctionParamList
    body: list[ASTNode]
    return_type: str
    variables: list[ParsedVariable]
    span: Span

    @classmethod
    def parse(cls, parser):
        """Parse a function declaration."""
        with parser.span() as span:
            parser.consume(tokens.Func)
            name = parser.consume(tokens.Identifier).value
            params = ParsedFunctionParamList.parse(parser)
            parser.consume(tokens.Arrow)
            return_type = parser.parse_type()
            parser.consume(tokens.OpenCurly)
            body = []
            variables = {param.variable.id: param.variable for param in params}
            while not parser.try_consume(tokens.CloseCurly):
                if statement := parser.parse_statement():
                    body.append(statement)
                if isinstance(statement, ParsedVariableDeclaration):
                    variables[statement.variable.id] = statement.variable
        label_parts = ["", *parser.path.parent.parts, parser.module_name, name]
        label_name = "$".join(label_parts)
        node = cls(name, label_name, params, body, return_type, variables, span)
        # parser.stack[-1][name] = node
        return node


@dataclasses.dataclass
class ParsedImport(ASTNode):
    """An import statement."""

    module_name: str
    span: Span

    @classmethod
    def parse(cls, parser):
        """Parse an import statement."""
        with parser.span() as span:
            parser.consume(tokens.Import)
            module_name = ParsedStringLiteral.parse(parser)
        return cls(module_name, span)


@dataclasses.dataclass
class ParsedExternalFunctionDeclaration(ASTNode):
    """An external function declaration."""

    name: str
    label_name: str
    params: ParsedFunctionParamList
    body: list[ASTNode]
    return_type: str
    span: Span

    @classmethod
    def parse(cls, parser):
        """Parse an external function declaration."""
        with parser.span() as span:
            parser.consume(tokens.Extern)
            parser.consume(tokens.Func)
            name = parser.consume(tokens.Identifier).value
            params = ParsedFunctionParamList.parse(parser)
            parser.consume(tokens.Arrow)
            return_type = parser.parse_type()
        label_name = f"_{name}"
        return cls(name, label_name, params, [], return_type, span)


@dataclasses.dataclass
class ParsedVariableDeclaration(ASTNode):
    """An assignment."""

    variable: ParsedVariable
    value: ASTNode
    span: Span

    @classmethod
    def parse(cls, parser):
        """Parse a variable declaration."""
        with parser.span() as span:
            parser.consume(tokens.Let)
            variable = ParsedVariable.parse(parser)
            parser.stack[-1][variable.id] = variable
            parser.consume(tokens.Equal)
            value = ParsedExpression.parse(parser)
            # variable.type = value.type
        return cls(variable, value, span)


@dataclasses.dataclass
class BinaryOperator(ASTNode):
    """A binary operator."""

    lhs: ASTNode
    op: tokens.Token
    rhs: ASTNode
    span: Span


@dataclasses.dataclass
class ParsedExpression(ASTNode):
    """An expression."""

    value: ASTNode
    span: Span

    @classmethod
    def parse_lhs(cls, parser):
        """Parse the left hand side of an expression."""
        match parser.peek():
            case tokens.OpenParen():
                parser.consume(tokens.OpenParen)
                value = ParsedExpression.parse(parser, 1)
                parser.consume(tokens.CloseParen)
            case tokens.StringLiteral():
                value = ParsedStringLiteral.parse(parser)
            case tokens.IntegerLiteral():
                value = ParsedIntegerLiteral.parse(parser)
            case tokens.BooleanLiteral():
                value = ParsedBooleanLiteral.parse(parser)
            case tokens.Identifier():
                value = ParsedName.parse(parser)
            case _:
                raise parser.error(f"Expected an expression: {parser.peek()}")
        return value

    @classmethod
    def parse(cls, parser, precedence=0):
        """Parse an expression."""
        op = rhs = None
        with parser.span() as span:
            lhs = cls.parse_lhs(parser)
            while True:
                op = parser.peek()
                if (
                    not isinstance(op, tokens.BinaryOperator)
                    or op.precedence < precedence
                ):
                    break
                if isinstance(op, tokens.OpenParen):
                    rhs = ParsedFunctionCallParamList.parse(parser)
                    lhs = ParsedFunctionCall(lhs, rhs, span)
                elif isinstance(op, tokens.OpenBracket):
                    parser.consume(tokens.OpenBracket)
                    rhs = ParsedExpression.parse(parser)
                    parser.consume(tokens.CloseBracket)
                    lhs = BinaryOperator(lhs, op, rhs, span)
                else:
                    parser.consume(type(op))
                    rhs = cls.parse(parser, op.precedence + op.left_associative)
                    if isinstance(op, tokens.Equal):
                        lhs = ParsedAssignment(lhs, rhs, span)
                    else:
                        lhs = BinaryOperator(lhs, op, rhs, span)
        return lhs


@dataclasses.dataclass
class ParsedAssignment(ASTNode):
    """An assignment."""

    lhs: ParsedExpression
    rhs: ParsedExpression
    span: Span


Statement = (
    ParsedImport
    | ParsedExternalFunctionDeclaration
    | ParsedFunctionDeclaration
    | ParsedVariableDeclaration
    | ParsedAssignment
)


@dataclasses.dataclass
class ParsedModule(ASTNode):
    """A module."""

    path: Path
    name: str
    body: list[Statement]
    names: dict
    span: Span


@dataclasses.dataclass
class ParsedReturn(ASTNode):
    """A return statement."""

    expression: ParsedExpression
    span: Span

    @classmethod
    def parse(cls, parser):
        """Parse an import statement."""
        with parser.span() as span:
            parser.consume(tokens.Return)
            expression = ParsedExpression.parse(parser)
        return cls(expression, span)


@dataclasses.dataclass
class ParsedIfStatement(ASTNode):
    """An if statement."""

    condition: ParsedExpression
    true_branch: list[Statement]
    false_branch: list[Statement]
    span: Span

    @classmethod
    def parse(cls, parser):
        """Parse an if statement."""
        true_branch = []
        false_branch = []
        with parser.span() as span:
            parser.consume(tokens.If)
            condition = ParsedExpression.parse(parser)
            parser.consume(tokens.OpenCurly)
            while not parser.try_consume(tokens.CloseCurly):
                if statement := parser.parse_statement():
                    true_branch.append(statement)
            if parser.try_consume(tokens.Else):
                parser.consume(tokens.OpenCurly)
                while not parser.try_consume(tokens.CloseCurly):
                    if statement := parser.parse_statement():
                        false_branch.append(statement)
        return cls(condition, true_branch, false_branch, span)


@dataclasses.dataclass
class ParsedForStatement(ASTNode):
    """An if statement."""

    condition: ParsedExpression
    body: list[Statement]
    span: Span

    @classmethod
    def parse(cls, parser):
        """Parse an if statement."""
        body = []
        with parser.span() as span:
            parser.consume(tokens.For)
            condition = ParsedExpression.parse(parser)
            parser.consume(tokens.OpenCurly)
            while not parser.try_consume(tokens.CloseCurly):
                if statement := parser.parse_statement():
                    body.append(statement)
        return cls(condition, body, span)


@dataclasses.dataclass
class ParsedTypeDeclaration(ASTNode):
    """A type declaration."""

    name: ParsedName
    type: types.Type
    span: Span

    @classmethod
    def parse(cls, parser: Parser):
        """Parse a type declaration."""
        with parser.span() as span:
            parser.consume(tokens.Type)
            name = ParsedName.parse(parser)
            parser.consume(tokens.Equal)
            type_ = parser.parse_type(name.id)
        return cls(name, type_, span)


@dataclasses.dataclass
class ParsedStruct(ASTNode):
    """A struct."""

    name: str
    fields: list[ParsedVariable]
    span: Span

    @classmethod
    def parse(cls, parser):
        """Parse a struct."""
        with parser.span() as span:
            parser.consume(tokens.Struct)
            name = parser.consume(tokens.Identifier).value
            parser.consume(tokens.OpenCurly)
            fields = []
            while not parser.try_consume(tokens.CloseCurly):
                fields.append(ParsedVariable.parse(parser))
        return cls(name, fields, span)
