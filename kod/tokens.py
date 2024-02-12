#!/usr/bin/env python

import dataclasses

from kod.span import Span


@dataclasses.dataclass
class Token:
    """A token in the Kod language."""
    value: str
    span: Span

    def __str__(self) -> str:
        return f"{self.__class__.__name__}({self.value!r})"


class BinaryOperator(Token):
    """A binary operator."""
    precedence: int = 1
    left_associative: bool = True


@dataclasses.dataclass
class OpenBracket(BinaryOperator):
    """An open bracket."""
    precedence = 20


@dataclasses.dataclass
class OpenParen(BinaryOperator):
    """An open parenthesis."""
    precedence = 20


@dataclasses.dataclass
class Dot(BinaryOperator):
    """A dot."""
    precedence = 20


@dataclasses.dataclass
class Percent(BinaryOperator):
    """A percent sign."""
    precedence = 16


@dataclasses.dataclass
class Slash(BinaryOperator):
    """A slash."""
    precedence = 16


@dataclasses.dataclass
class Star(BinaryOperator):
    """A star."""
    precedence = 16


@dataclasses.dataclass
class Plus(BinaryOperator):
    """A plus sign."""
    precedence = 15


@dataclasses.dataclass
class Minus(BinaryOperator):
    """A minus sign."""
    precedence = 15


@dataclasses.dataclass
class Equal(BinaryOperator):
    """An equals sign."""
    precedence = 10


@dataclasses.dataclass
class EqualEqual(BinaryOperator):
    """Two equals signs."""
    precedence = 12


@dataclasses.dataclass
class LessThan(BinaryOperator):
    """An equals sign."""
    precedence = 12


@dataclasses.dataclass
class GreaterThan(BinaryOperator):
    """An equals sign."""
    precedence = 12


@dataclasses.dataclass
class EOF(Token):
    """The end of the file."""


@dataclasses.dataclass
class EOL(Token):
    """A newline."""


@dataclasses.dataclass
class Identifier(Token):
    """An identifier."""


@dataclasses.dataclass
class CloseParen(Token):
    """A close parenthesis."""


@dataclasses.dataclass
class OpenCurly(Token):
    """An open curly brace."""


@dataclasses.dataclass
class CloseCurly(Token):
    """A close curly brace."""


@dataclasses.dataclass
class CloseBracket(Token):
    """A close backet."""


@dataclasses.dataclass
class Colon(Token):
    """A colon."""


@dataclasses.dataclass
class Comma(Token):
    """A comma."""


@dataclasses.dataclass
class StringLiteral(Token):
    """A quoted string."""


@dataclasses.dataclass
class IntegerLiteral(Token):
    """A literal number."""


@dataclasses.dataclass
class Comment(Token):
    """A comment."""


@dataclasses.dataclass
class Arrow(Token):
    """An arrow."""


@dataclasses.dataclass
class Variable(Token):
    """A variable."""


@dataclasses.dataclass
class Extern(Token):
    """An extern function declaration."""


@dataclasses.dataclass
class Func(Token):
    """A function declaration."""


@dataclasses.dataclass
class Let(Token):
    """A let statement."""


@dataclasses.dataclass
class Anon(Token):
    """An anon specifier."""


@dataclasses.dataclass
class Import(Token):
    """An import token"""


@dataclasses.dataclass
class Return(Token):
    """A return token"""


@dataclasses.dataclass
class If(Token):
    """An if token"""


@dataclasses.dataclass
class Else(Token):
    """An else token"""


@dataclasses.dataclass
class For(Token):
    """A for token"""


@dataclasses.dataclass
class BooleanLiteral(Token):
    """A true/false token"""


@dataclasses.dataclass
class Type(Token):
    """A type token"""


@dataclasses.dataclass
class Struct(Token):
    """A struct token"""
