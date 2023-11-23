#!/usr/bin/env python

import dataclasses


@dataclasses.dataclass
class Position:
    """A position in a source file."""
    filename: str
    line: int
    column: int


@dataclasses.dataclass
class Token:
    """A token in the Kod language."""
    value: str
    position: Position

    def __str__(self) -> str:
        return f"{self.__class__.__name__}({self.value!r})"


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
class OpenParen(Token):
    """An open parenthesis."""


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
class Dot(Token):
    """A dot."""


@dataclasses.dataclass
class Colon(Token):
    """A colon."""


@dataclasses.dataclass
class Comma(Token):
    """A comma."""


@dataclasses.dataclass
class QuotedString(Token):
    """A quoted string."""


@dataclasses.dataclass
class LiteralNumber(Token):
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
class Equals(Token):
    """An equals sign."""
