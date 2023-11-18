"""Example-based tests for the compiler."""

import io
import unittest

from pathlib import Path

from kod.compiler import Compiler
from kod.lexer import Lexer
from kod.parser import Parser


def make_test(path):
    """Make a test function for a given test file."""
    with path.open() as f:
        kod, asm = f.read().split("// generated assembly\n")
    asm = "".join(
        line.removeprefix("// ")
        for line in asm.splitlines(keepends=True)
    )

    doc = kod.splitlines()[0].strip("/ ")

    def testfunc(self):
        tokens = Lexer(kod).lex()
        program = Parser(tokens).parse()
        output = io.StringIO()
        Compiler(program, output).compile()
        self.assertEqual(output.getvalue(), asm)

    testfunc.__name__ = f"test_{path.stem}"
    testfunc.__doc__ = doc
    return testfunc


class ExamplesTestCase(unittest.TestCase):
    """Test that the examples in the tests directory run without error."""
    maxDiff = 2048


test_dir = Path(__file__).parent.relative_to(Path.cwd())
for example in test_dir.glob("*.kod"):
    test = make_test(example)
    setattr(ExamplesTestCase, test.__name__, test)
