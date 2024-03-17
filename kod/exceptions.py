#!/usr/bin/env python
"""Exceptions for the Kod language."""

import itertools
from functools import cache

RESET = "\033[0m"
DIM = "\033[1;30m"
ERR = "\033[1;31m"
HL = "\033[1;36m"


@cache
def get_source(filename):
    """Return the source code for a given filename."""
    with open(filename) as file:
        return file.read()


class ExcerptString:
    """A string that is part of an excerpt."""

    def __init__(self, s, highlight=False):
        self.str = s
        self.highlight = highlight


class ExcerptLine:
    """A line in an excerpt."""

    def __init__(self, line_no, parts=None):
        self.line_no = line_no
        self.parts = parts or []

    @property
    def has_highlight(self):
        """Return True if the line has a highlight."""
        return any(part.highlight for part in self.parts)


class Excerpt:
    """An excerpt of a source file."""

    def __init__(self, filename):
        self.filename = filename
        self.lines = []

    def append(self, line):
        """Append a line to the excerpt."""
        self.lines.append(line)


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
        excerpt = Excerpt(self.span.filename)
        lines = self.source.split("\n")
        first = max(0, self.line - 1)
        last = min(len(lines) - 1, self.line + 1)

        line_numbers = range(first, last + 1)
        lines = lines[first : last + 1]
        for n, line in zip(line_numbers, lines):
            if n == self.line:
                start = self.col
                end = start + self.span.length
                before = ExcerptString(line[:start])
                highlight = ExcerptString(line[start:end], highlight=True)
                after = ExcerptString(line[end:])
                excerpt_line = ExcerptLine(n + 1, [before, highlight, after])
                excerpt.append(excerpt_line)
            else:
                excerpt_line = ExcerptLine(n + 1, [ExcerptString(line)])
                excerpt.append(excerpt_line)
        return excerpt

    @property
    def line(self):
        """Return the line number of the error."""
        return self.source.count("\n", 0, self.span.start)

    @property
    def col(self):
        """Return the column number of the error."""
        line_start = self.source.rfind("\n", 0, self.span.start) + 1
        col = self.span.start - line_start
        return col

    def __str__(self):
        excerpt = self.excerpt()
        s = f"\033[1;37m{self.span.filename}:{self.line+1}:{self.col+1}{RESET}: "
        s += f"{ERR}error: \033[1;37m{self.msg}{RESET}\n"
        line_no_width = 5  # max(len(str(line.line_no)) for line in excerpt.lines)
        for line in excerpt.lines:
            s += f"{DIM}{line.line_no:{line_no_width}} |{RESET} "
            for part in line.parts:
                if part.highlight:
                    s += f"{HL}{part.str}{RESET}"
                elif line.has_highlight:
                    s += f"\033[0;39m{part.str}{RESET}"
                else:
                    s += f"{DIM}{part.str}{RESET}"
            s += "\n"
            if line.has_highlight:
                s += f"{DIM}" + " " * (line_no_width) + f" |{RESET} "
                for part in line.parts:
                    if part.highlight:
                        s += f"{ERR}{'^' * len(part.str)}{RESET}"
                    else:
                        indent = "".join(itertools.takewhile(str.isspace, part.str))
                        s += DIM
                        s += indent
                        s += " " * (len(part.str) - len(indent))
                        s += RESET
                s += "\n"

        return s.replace("\t", "    ")
