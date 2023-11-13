#!/usr/bin/env python

from enum import Enum, global_enum, auto


class Token:
    """A token in the Kod language."""

    def __init__(self, value=None):
        self.value = value

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
