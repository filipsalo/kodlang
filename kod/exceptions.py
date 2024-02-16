#!/usr/bin/env python
"""Exceptions for the Kod language."""


from functools import cache


@cache
def get_source(filename):
    """Return the source code for a given filename."""
    with open(filename) as file:
        return file.read()


class KodSyntaxError(Exception):
    """A syntax error in the Kod language."""

    def __init__(self, msg, span):
        self.msg = msg
        self.span = span

    @property
    def source(self):
        """Return the source code for the error."""
        return get_source(self.span.filename)

    def excerpt(self):
        """Return an excerpt of the source code around the error."""
        excerpt = ""
        lines = self.source.split("\n")
        first = max(0, self.line - 3)
        last = self.line + 2

        for n, line in list(enumerate(lines, 1))[first : last + 1]:
            excerpt += f"{n:3d}: {line}\n"
            if n == self.line:
                excerpt += f"     {' ' * (self.col - 1)}^\n"
        return excerpt

    @property
    def line(self):
        """Return the line number of the error."""
        return self.source.count("\n", 0, self.span.start) + 1

    @property
    def col(self):
        """Return the column number of the error."""
        line_start = self.source.rfind("\n", 0, self.span.start + 1)
        return self.span.start - line_start + 1

    def __str__(self):
        return (
            f"{self.excerpt()}\n"
            f"Syntax error in {self.span.filename}, "
            f"line {self.line}, col {self.col}:\n"
            f"{self.msg}\n"
        )
