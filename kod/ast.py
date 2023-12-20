"""Abstract syntax tree."""

import dataclasses
from pathlib import Path
from kod import tokens

from kod.span import Span
from kod.types import Type, BUILTIN_TYPES


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

    @classmethod
    def parse(cls, parser):
        """Parse a string literal."""
        token = parser.consume(tokens.QuotedString)
        return cls(
            token.value.strip("\"").encode('utf8'),
            BUILTIN_TYPES["str"],
            span=token.span
        )


@dataclasses.dataclass
class ParsedVariable(ASTNode):
    """A name."""
    id: str
    type: Type
    span: Span

    @classmethod
    def parse(cls, parser):
        """Parse a variable."""
        token = parser.consume(tokens.Identifier)
        return cls(token.value, None, span=token.span)


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
            if parser.peek(tokens.Anon):
                parser.consume(tokens.Anon)
                anonymous = True
            variable = ParsedVariable.parse(parser)
            parser.consume(tokens.Colon)
            variable.type = parser.parse_type()
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
            while not parser.peek(tokens.CloseParen):
                params.append(ParsedFunctionParam.parse(parser))
                if not parser.peek(tokens.Comma):
                    break
                parser.consume(tokens.Comma)
            parser.consume(tokens.CloseParen)
        return cls(params, span)


@dataclasses.dataclass
class ParsedFunctionCallParam(ASTNode):
    """A function parameter."""
    label: ParsedVariable
    expression: ASTNode
    span: Span

    @classmethod
    def parse(cls, parser):
        """Parse a function call parameter."""
        with parser.span() as span:
            label = None
            if parser.peek(tokens.Identifier):
                expr = ParsedVariable.parse(parser)
                if parser.peek(tokens.Colon):
                    label = expr
                    parser.consume(tokens.Colon)
                    expr = ParsedExpression.parse(parser)
            else:
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
            while not parser.peek(tokens.CloseParen):
                params.append(ParsedFunctionCallParam.parse(parser))
                if not parser.peek(tokens.Comma):
                    break
                parser.consume(tokens.Comma)
            parser.consume(tokens.CloseParen)
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
            while not parser.peek(tokens.CloseCurly):
                if statement := parser.parse_statement():
                    body.append(statement)
                if isinstance(statement, ParsedVariableDeclaration):
                    variables[statement.variable.id] = statement.variable
            parser.consume(tokens.CloseCurly)
        node = cls(name, params, body, return_type, variables, span)
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
        return cls(name, params, [], return_type, span)


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
            parser.consume(tokens.Equals)
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
        # print(parser.peek())
        with parser.span() as span:
            match parser.peek():
                case tokens.OpenParen():
                    parser.consume(tokens.OpenParen)
                    value = ParsedExpression.parse(parser, 1)
                    parser.consume(tokens.CloseParen)
                case tokens.QuotedString():
                    value = ParsedStringLiteral.parse(parser)
                case tokens.Identifier():
                    value = ParsedName.parse(parser)
                case _:
                    raise parser.error(f"Expected an expression: {parser.peek()}")
        return cls(value, span)

    @classmethod
    def parse(cls, parser, precedence=0):
        """Parse an expression."""
        op = rhs = None
        with parser.span() as span:
            lhs = cls.parse_lhs(parser)
            while True:
                op = parser.peek()
                if not isinstance(op, tokens.BinaryOperator) or op.precedence < precedence:
                    break
                if isinstance(op, tokens.OpenParen):
                    rhs = ParsedFunctionCallParamList.parse(parser)
                    lhs = ParsedFunctionCall(lhs, rhs, span)
                else:
                    parser.consume(type(op))
                    rhs = cls.parse(parser, op.precedence + op.left_associative)
                    if isinstance(op, tokens.Equals):
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


@dataclasses.dataclass
class ParsedModule(ASTNode):
    """A module."""
    path : Path
    name: str
    body: list[ParsedImport | ParsedExternalFunctionDeclaration | ParsedFunctionDeclaration | ParsedVariableDeclaration | ParsedAssignment]
    names: dict
    span: Span
