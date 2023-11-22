#!/usr/bin/env python

import dataclasses
from enum import Enum, global_enum, auto
from typing import Optional


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


@global_enum
class TokenType(Enum):
    """An enumeration of token types."""

    @staticmethod
    def _generate_next_value_(name, start, count, last_values):
        return type(name, (Token,), {})

    def __call__(self, *args, **kwargs):
        return self.value(*args, **kwargs)

    EOF = auto()
    EOL = auto()
    Identifier = auto()
    OpenParen = auto()
    CloseParen = auto()
    OpenCurly = auto()
    CloseCurly = auto()
    Dot = auto()
    Colon = auto()
    Comma = auto()
    QuotedString = auto()
    LiteralNumber = auto()
    Comment = auto()
    Arrow = auto()
    Variable = auto()

    # Keywords
    Extern = auto()
    Func = auto()
