#!/usr/bin/env python
"""Exceptions for the Kod language."""


class KodSyntaxError(Exception):
    """A syntax error in the Kod language."""
    def __init__(self, msg):
        self.msg = msg
        self.filename = "<input>"
        self.line = 0
        self.col = 0
        self.excerpt = ""

    def __str__(self):
        return (
            f"{self.excerpt}\n"
            f"Syntax error in {self.filename}, "
            f"line {self.line}, col {self.col}:\n"
            f"{self.msg}\n"
        )
