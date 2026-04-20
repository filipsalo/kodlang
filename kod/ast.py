"""Abstract syntax tree."""

import dataclasses
from pathlib import Path
from typing import Any, Optional, Self, Union

from kod import tokens
from kod import values as types
from kod.filesys import FileWrapper
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


Statement = Union[
    "Import",
    "ExternalFunctionDeclaration",
    "FunctionDeclaration",
    "VariableDeclaration",
    "Assignment",
]


@dataclasses.dataclass
class ASTNode:
    """An AST node."""

    def __repr__(self):
        return f"ast.{super().__repr__()}"


@dataclasses.dataclass
class Literal:
    """A literal."""

    value: Any
    span: Span


@dataclasses.dataclass
class StringLiteral(ASTNode, Literal):
    """A string literal."""

    value: types.String
    span: Span

    @classmethod
    def parse(cls, parser: Parser) -> Self:
        """Parse a string literal."""
        token = parser.consume(tokens.StringLiteral)
        bytes_ = token.value.strip('"').encode("utf8")
        value = types.String(bytes_)
        return cls(value, span=token.span)


@dataclasses.dataclass
class IntegerLiteral(ASTNode, Literal):
    """An integerliteral."""

    value: types.Int64
    span: Span

    @classmethod
    def parse(cls, parser: Parser) -> Self:
        """Parse an integer literal."""
        token = parser.consume(tokens.IntegerLiteral)
        value = types.Int64(int(token.value))
        return cls(value, span=token.span)


@dataclasses.dataclass
class BooleanLiteral(ASTNode, Literal):
    """An integerliteral."""

    value: types.Bool
    span: Span

    @classmethod
    def parse(cls, parser: Parser) -> Self:
        """Parse an integer literal."""
        token = parser.consume(tokens.BooleanLiteral)
        value = types.Bool(token.value == "true")
        return cls(value, span=token.span)


@dataclasses.dataclass
class NoneLiteral(ASTNode, Literal):
    """A none literal."""

    value: types.NoneType
    span: Span

    @classmethod
    def parse(cls, parser: Parser) -> Self:
        """Parse a none literal."""
        token = parser.consume(tokens.NoneLiteral)
        return cls(types.none_value, span=token.span)


@dataclasses.dataclass
class Variable(ASTNode):
    """A name."""

    id: str
    type: Optional[type[types.Type]]
    span: Span

    @classmethod
    def parse(cls, parser: Parser) -> Self:
        """Parse a variable."""
        type_ = None
        token = parser.consume(tokens.Identifier)
        if parser.try_consume(tokens.Colon):
            type_ = parser.parse_type()
        return cls(token.value, type_, span=token.span)


@dataclasses.dataclass
class Name(ASTNode):
    """A name."""

    id: str
    span: Span

    @classmethod
    def parse(cls, parser: Parser) -> Self:
        """Parse a variable."""
        token = parser.consume(tokens.Identifier)
        return cls(token.value, span=token.span)


@dataclasses.dataclass
class FunctionParam(ASTNode):
    """A function parameter."""

    variable: Variable
    anonymous: bool
    span: Span

    @classmethod
    def parse(cls, parser: Parser) -> Self:
        """Parse a function parameter."""
        with parser.span() as span:
            anonymous = False
            if parser.try_consume(tokens.Anon):
                anonymous = True
            variable = Variable.parse(parser)
        return cls(variable, anonymous, span)


@dataclasses.dataclass
class FunctionParamList(ASTNode):
    """A function parameter list."""

    params: list[FunctionParam]
    span: Span

    def __iter__(self):
        return iter(self.params)

    def __len__(self):
        return len(self.params)

    @classmethod
    def parse(cls, parser: Parser) -> Self:
        """Parse a function parameter list."""
        with parser.span() as span:
            parser.consume(tokens.OpenParen)
            params = []
            while not parser.try_consume(tokens.CloseParen):
                params.append(FunctionParam.parse(parser))
                if not parser.try_consume(tokens.Comma):
                    parser.consume(tokens.CloseParen)
                    break
        return cls(params, span)


@dataclasses.dataclass
class FunctionCallParam(ASTNode):
    """A function parameter."""

    label: Optional[Name]
    expression: ASTNode
    span: Span

    @classmethod
    def parse(cls, parser: Parser) -> Self:
        """Parse a function call parameter."""
        with parser.span() as span:
            label: Optional[Name] = None
            expr = Expression.parse(parser)
            if parser.try_consume(tokens.Colon):
                assert isinstance(expr, Name)
                label = expr
                expr = Expression.parse(parser)
        return cls(label, expr, span)


@dataclasses.dataclass
class FunctionCallParamList(ASTNode):
    """A function parameter list."""

    params: list[FunctionCallParam]
    span: Span

    def __iter__(self):
        return iter(self.params)

    def __len__(self):
        return len(self.params)

    @classmethod
    def parse(cls, parser: Parser) -> Self:
        """Parse a function call parameter list."""
        with parser.span() as span:
            parser.consume(tokens.OpenParen)
            params = []
            while not parser.try_consume(tokens.CloseParen):
                params.append(FunctionCallParam.parse(parser))
                if not parser.try_consume(tokens.Comma):
                    parser.consume(tokens.CloseParen)
                    break
        return cls(params, span)


@dataclasses.dataclass
class FunctionCall(ASTNode):
    """A function call."""

    callee: ASTNode
    args: FunctionCallParamList
    span: Span


@dataclasses.dataclass
class FunctionDeclaration(ASTNode):
    """A function declaration."""

    name: str
    label_name: str
    params: FunctionParamList
    body: list[Statement]
    return_type: type[types.Type]
    variables: dict[str, Variable]
    span: Span
    struct_name: Optional[str] = None

    @classmethod
    def parse(cls, parser: Parser) -> Self:
        """Parse a function declaration."""
        with parser.span() as span:
            parser.consume(tokens.Func)
            name = parser.consume(tokens.Identifier).value
            params = FunctionParamList.parse(parser)
            parser.consume(tokens.Arrow)
            return_type = parser.parse_type()
            parser.consume(tokens.OpenCurly)
            body = []
            variables = {param.variable.id: param.variable for param in params}
            while not parser.try_consume(tokens.CloseCurly):
                if statement := parser.parse_statement():
                    body.append(statement)
                if isinstance(statement, VariableDeclaration):
                    variables[statement.variable.id] = statement.variable
                if isinstance(statement, ForEachStatement):
                    idx_name = f"__foreach_idx_{statement.binding}"
                    variables[statement.binding] = Variable(
                        statement.binding, None, statement.span
                    )
                    variables[idx_name] = Variable(idx_name, None, statement.span)
                if isinstance(statement, MatchStatement):
                    for arm in statement.arms:
                        if isinstance(arm.pattern, EnumVariantPattern):
                            enum_type = parser.type_registry.get(arm.pattern.enum_name)
                            if enum_type is not None and hasattr(enum_type, "variants"):
                                variant_info = enum_type.variants.get(
                                    arm.pattern.variant_name
                                )
                                if variant_info is not None:
                                    for binding_name, field in zip(
                                        arm.pattern.bindings, variant_info.fields
                                    ):
                                        variables[binding_name] = Variable(
                                            binding_name, field.type, arm.pattern.span
                                        )
                        elif (
                            isinstance(arm.pattern, OptionalSomePattern)
                            and arm.pattern.binding
                        ):
                            if isinstance(statement.expression, Name):
                                var = variables.get(statement.expression.id)
                                if (
                                    var is not None
                                    and var.type is not None
                                    and hasattr(var.type, "inner_type")
                                ):
                                    variables[arm.pattern.binding] = Variable(
                                        arm.pattern.binding,
                                        var.type.inner_type,
                                        arm.pattern.span,
                                    )
        label_parts = ["", *parser.file.canonical_path.with_suffix("").parts, name]
        label_name = "$".join(label_parts)
        node = cls(name, label_name, params, body, return_type, variables, span)
        return node

    @classmethod
    def parse_method(cls, parser: Parser, struct_name: str) -> "FunctionDeclaration":
        """Parse a method declaration inside a struct block."""
        with parser.span() as span:
            parser.consume(tokens.Func)
            name = parser.consume(tokens.Identifier).value
            params = FunctionParamList.parse(parser)
            parser.consume(tokens.Arrow)
            return_type = parser.parse_type()
            parser.consume(tokens.OpenCurly)
            body = []
            variables = {param.variable.id: param.variable for param in params}
            while not parser.try_consume(tokens.CloseCurly):
                if statement := parser.parse_statement():
                    body.append(statement)
                if isinstance(statement, VariableDeclaration):
                    variables[statement.variable.id] = statement.variable
                if isinstance(statement, ForEachStatement):
                    idx_name = f"__foreach_idx_{statement.binding}"
                    variables[statement.binding] = Variable(
                        statement.binding, None, statement.span
                    )
                    variables[idx_name] = Variable(idx_name, None, statement.span)
        label_parts = [
            "",
            *parser.file.canonical_path.with_suffix("").parts,
            struct_name,
            name,
        ]
        label_name = "$".join(label_parts)
        return cls(
            name, label_name, params, body, return_type, variables, span, struct_name
        )


@dataclasses.dataclass
class Import(ASTNode):
    """An import statement."""

    module_name: str
    local_name: str
    span: Span

    @classmethod
    def parse(cls, parser: Parser) -> Self:
        """Parse an import statement."""
        with parser.span() as span:
            parser.consume(tokens.Import)
            module_name = StringLiteral.parse(parser).value.to_py_str()
            local_name = module_name.split("/")[-1]
        return cls(module_name, local_name, span)


@dataclasses.dataclass
class ExternalFunctionDeclaration(ASTNode):
    """An external function declaration."""

    name: str
    label_name: str
    params: FunctionParamList
    body: list[ASTNode]
    return_type: type[types.Type]
    span: Span

    @classmethod
    def parse(cls, parser: Parser) -> Self:
        """Parse an external function declaration."""
        with parser.span() as span:
            parser.consume(tokens.Extern)
            parser.consume(tokens.Func)
            name = parser.consume(tokens.Identifier).value
            params = FunctionParamList.parse(parser)
            parser.consume(tokens.Arrow)
            return_type = parser.parse_type()
        label_name = f"_{name}"
        return cls(name, label_name, params, [], return_type, span)


@dataclasses.dataclass
class VariableDeclaration(ASTNode):
    """An assignment."""

    variable: Variable
    value: ASTNode
    span: Span

    @classmethod
    def parse(cls, parser: Parser) -> Self:
        """Parse a variable declaration."""
        with parser.span() as span:
            parser.consume(tokens.Let)
            variable = Variable.parse(parser)
            parser.stack[-1][variable.id] = variable
            parser.consume(tokens.Equal)
            value = Expression.parse(parser)
        return cls(variable, value, span)


@dataclasses.dataclass
class BinaryOperator(ASTNode):
    """A binary operator."""

    lhs: ASTNode
    op: tokens.Token
    rhs: ASTNode
    span: Span


@dataclasses.dataclass
class ArrayLiteral(ASTNode):
    """An array literal like [1, 2, 3]."""

    elements: list
    span: Span


@dataclasses.dataclass
class StringSlice(ASTNode):
    """A string slice expression: s[i:j]."""

    string: ASTNode
    start: ASTNode
    end: ASTNode
    span: Span


@dataclasses.dataclass
class Expression(ASTNode):
    """An expression."""

    value: ASTNode
    span: Span

    @classmethod
    def parse_lhs(cls, parser):
        """Parse the left hand side of an expression."""
        match parser.peek():
            case tokens.OpenParen():
                parser.consume(tokens.OpenParen)
                value = Expression.parse(parser, 1)
                parser.consume(tokens.CloseParen)
            case tokens.StringLiteral():
                value = StringLiteral.parse(parser)
            case tokens.IntegerLiteral():
                value = IntegerLiteral.parse(parser)
            case tokens.BooleanLiteral():
                value = BooleanLiteral.parse(parser)
            case tokens.NoneLiteral():
                value = NoneLiteral.parse(parser)
            case tokens.Minus():
                op_token = parser.consume(tokens.Minus)
                operand = Expression.parse(parser, 17)
                zero = IntegerLiteral(types.Int64(0), span=op_token.span)
                value = BinaryOperator(zero, op_token, operand, op_token.span)
            case tokens.OpenBracket():
                span = parser.peek().span
                parser.consume(tokens.OpenBracket)
                elements = []
                while not parser.try_consume(tokens.CloseBracket):
                    elements.append(Expression.parse(parser))
                    if not parser.try_consume(tokens.Comma):
                        parser.consume(tokens.CloseBracket)
                        break
                value = ArrayLiteral(elements, span)
            case tokens.Identifier():
                value = Name.parse(parser)
            case _:
                raise parser.error(f"Expected an expression: {parser.peek()}")
        return value

    @classmethod
    def parse(cls, parser, precedence=0) -> ASTNode:
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
                    rhs = FunctionCallParamList.parse(parser)
                    lhs = FunctionCall(lhs, rhs, span)
                elif isinstance(op, tokens.OpenBracket):
                    parser.consume(tokens.OpenBracket)
                    start = Expression.parse(parser)
                    if parser.try_consume(tokens.Colon):
                        end = Expression.parse(parser)
                        parser.consume(tokens.CloseBracket)
                        lhs = StringSlice(lhs, start, end, span)
                    else:
                        parser.consume(tokens.CloseBracket)
                        lhs = BinaryOperator(lhs, op, start, span)
                else:
                    parser.consume(type(op))
                    rhs = cls.parse(parser, op.precedence + op.left_associative)
                    if isinstance(op, tokens.Equal):
                        lhs = Assignment(lhs, rhs, span)
                    elif isinstance(op, tokens.PlusEqual):
                        plus = tokens.Plus(value="+", span=op.span)
                        lhs = Assignment(
                            lhs, BinaryOperator(lhs, plus, rhs, span), span
                        )
                    else:
                        lhs = BinaryOperator(lhs, op, rhs, span)
        return lhs


@dataclasses.dataclass
class Assignment(ASTNode):
    """An assignment."""

    lhs: ASTNode
    rhs: ASTNode
    span: Span


@dataclasses.dataclass
class Module(ASTNode):
    """A module."""

    source_file: FileWrapper
    body: list[Statement]
    span: Span

    @property
    def names(self):
        names = {}
        for statement in self.body:
            match statement:
                case FunctionDeclaration(name):
                    names[name] = statement
                case ExternalFunctionDeclaration(name):
                    names[name] = statement
                case VariableDeclaration(variable):
                    names[variable.id] = statement
                case Import(_, local_name):
                    names[local_name] = statement
                case TypeDeclaration(name, type_):
                    names[name.id] = type_
        return names

    def get_imports(self) -> list[Import]:
        """Get the imports of a module."""
        imports = []
        for statement in self.body:
            if isinstance(statement, Import):
                imports.append(statement)
        return imports

    @property
    def canonical_name(self):
        """Return the canonical module name."""
        return self.source_file.canonical_path.with_suffix("")

    @property
    def mangled_name(self):
        return f"_{self.canonical_name.name.replace('/', '$')}"

    @property
    def asm_path(self):
        return Path(self.mangled_name).with_suffix(".s")

    @property
    def obj_path(self):
        return Path(self.mangled_name).with_suffix(".o")

    def resolve_import(self, module_name) -> Path:
        """Resolve an import. Relative (./foo) imports are resolved against
        the importing module; stdlib imports are just the bare path."""
        if module_name.startswith("./"):
            return self.canonical_name.parent / module_name
        return Path(module_name)


@dataclasses.dataclass
class Return(ASTNode):
    """A return statement."""

    expression: ASTNode
    span: Span

    @classmethod
    def parse(cls, parser: Parser) -> Self:
        """Parse an import statement."""
        with parser.span() as span:
            parser.consume(tokens.Return)
            expression = Expression.parse(parser)
        return cls(expression, span)


@dataclasses.dataclass
class IfStatement(ASTNode):
    """An if statement."""

    condition: ASTNode
    true_branch: list[Statement]
    false_branch: list[Statement]
    span: Span

    @classmethod
    def parse(cls, parser: Parser) -> Self:
        """Parse an if statement."""
        true_branch = []
        false_branch = []
        with parser.span() as span:
            parser.consume(tokens.If)
            condition = Expression.parse(parser)
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
class ForStatement(ASTNode):
    """A while-style for loop."""

    condition: ASTNode
    body: list[Statement]
    span: Span

    @classmethod
    def parse(cls, parser: Parser) -> "ForStatement | ForEachStatement":
        """Parse a for statement (while-style or foreach)."""
        body = []
        with parser.span() as span:
            parser.consume(tokens.For)
            if parser.peeking_at(tokens.Identifier):
                saved_pos = parser.pos
                binding = parser.consume(tokens.Identifier).value
                if parser.try_consume(tokens.In):
                    iterable = Expression.parse(parser)
                    parser.consume(tokens.OpenCurly)
                    while not parser.try_consume(tokens.CloseCurly):
                        if statement := parser.parse_statement():
                            body.append(statement)
                    return ForEachStatement(binding, iterable, body, span)
                parser.pos = saved_pos
            condition = Expression.parse(parser)
            parser.consume(tokens.OpenCurly)
            while not parser.try_consume(tokens.CloseCurly):
                if statement := parser.parse_statement():
                    body.append(statement)
        return cls(condition, body, span)


@dataclasses.dataclass
class ForEachStatement(ASTNode):
    """A for-each loop over an array."""

    binding: str
    iterable: ASTNode
    body: list[Statement]
    span: Span


@dataclasses.dataclass
class BreakStatement(ASTNode):
    """A break statement."""

    span: Span

    @classmethod
    def parse(cls, parser: Parser) -> "BreakStatement":
        with parser.span() as span:
            parser.consume(tokens.Break)
        return cls(span)


@dataclasses.dataclass
class ContinueStatement(ASTNode):
    """A continue statement."""

    span: Span

    @classmethod
    def parse(cls, parser: Parser) -> "ContinueStatement":
        with parser.span() as span:
            parser.consume(tokens.Continue)
        return cls(span)


@dataclasses.dataclass
class TypeDeclaration(ASTNode):
    """A type declaration."""

    name: Name
    type: type[types.Type]
    span: Span

    @classmethod
    def parse(cls, parser: Parser) -> Self:
        """Parse a type declaration."""
        with parser.span() as span:
            parser.consume(tokens.Type)
            name = Name.parse(parser)
            parser.consume(tokens.Equal)
            type_ = parser.parse_type(name.id)
        parser.type_registry[name.id] = type_
        return cls(name, type_, span)


@dataclasses.dataclass
class Struct(ASTNode):
    """A struct."""

    name: str
    fields: list[Variable]
    span: Span

    @classmethod
    def parse(cls, parser: Parser) -> Self:
        """Parse a struct."""
        with parser.span() as span:
            parser.consume(tokens.Struct)
            name = parser.consume(tokens.Identifier).value
            parser.consume(tokens.OpenCurly)
            fields = []
            while not parser.try_consume(tokens.CloseCurly):
                fields.append(Variable.parse(parser))
        return cls(name, fields, span)


@dataclasses.dataclass
class WildcardPattern:
    span: Span


@dataclasses.dataclass
class EnumVariantPattern:
    enum_name: str
    variant_name: str
    bindings: list  # list of str (binding names)
    span: Span


@dataclasses.dataclass
class OptionalSomePattern:
    binding: str  # empty string if no binding
    span: Span


@dataclasses.dataclass
class OptionalNonePattern:
    span: Span


@dataclasses.dataclass
class MatchArm:
    pattern: Any  # WildcardPattern | EnumVariantPattern
    body: list  # list of Statement
    span: Span

    @classmethod
    def parse(cls, parser: "Parser") -> "MatchArm":
        with parser.span() as span:
            # Parse pattern
            if parser.peeking_at(tokens.Identifier) and parser.peek().value == "_":
                parser.consume(tokens.Identifier)
                pattern = WildcardPattern(span)
            elif parser.peeking_at(tokens.NoneLiteral):
                parser.consume(tokens.NoneLiteral)
                pattern = OptionalNonePattern(span)
            elif parser.peeking_at(tokens.Identifier) and parser.peek().value == "Some":
                parser.consume(tokens.Identifier)
                binding = ""
                if parser.try_consume(tokens.OpenParen):
                    binding = parser.consume(tokens.Identifier).value
                    parser.consume(tokens.CloseParen)
                pattern = OptionalSomePattern(binding, span)
            else:
                enum_name = parser.consume(tokens.Identifier).value
                parser.consume(tokens.Dot)
                variant_name = parser.consume(tokens.Identifier).value
                bindings = []
                if parser.try_consume(tokens.OpenParen):
                    while not parser.try_consume(tokens.CloseParen):
                        bindings.append(parser.consume(tokens.Identifier).value)
                        if not parser.try_consume(tokens.Comma):
                            parser.consume(tokens.CloseParen)
                            break
                pattern = EnumVariantPattern(enum_name, variant_name, bindings, span)
            # Parse ->
            parser.consume(tokens.Arrow)
            # Parse body: block or single statement
            if parser.peeking_at(tokens.OpenCurly):
                parser.consume(tokens.OpenCurly)
                body = []
                while not parser.try_consume(tokens.CloseCurly):
                    if parser.try_consume(tokens.EOL):
                        continue
                    if stmt := parser.parse_statement():
                        body.append(stmt)
            else:
                body = []
                if stmt := parser.parse_statement():
                    body.append(stmt)
        return cls(pattern, body, span)


@dataclasses.dataclass
class MatchStatement(ASTNode):
    expression: ASTNode
    arms: list  # list of MatchArm
    span: Span

    @classmethod
    def parse(cls, parser: "Parser") -> "MatchStatement":
        with parser.span() as span:
            parser.consume(tokens.Match)
            expression = Expression.parse(parser)
            parser.try_consume(tokens.EOL)
            parser.consume(tokens.OpenCurly)
            arms = []
            while not parser.try_consume(tokens.CloseCurly):
                if parser.try_consume(tokens.EOL):
                    continue
                arms.append(MatchArm.parse(parser))
        return cls(expression, arms, span)
