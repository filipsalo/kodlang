"""Example-based tests for the compiler."""

import io
import subprocess
import sys
import unittest

from functools import partial
from pathlib import Path

from kod.builder import Builder, FileWrapper


def run_interpreted(source):
    """Run a program in the interpreter."""
    result = subprocess.run(
        [sys.executable, "-m", "kod", "interpret", "-"],
        input=source,
        stdout=subprocess.PIPE,
        text=True,
        check=True,
    )
    return result.stdout


def compile_to_assembly(source):
    """Compile a program to assembly."""
    bob = Builder(root_path=Path.cwd(), stdlib_path=Path("stdlib"))
    file_wrapper = FileWrapper("main.kod", io.StringIO(source))
    bob.parse_program(file_wrapper)
    return bob.compile_module("main")


def make_tests(path):
    """Make a test function for a given test file."""
    with path.open() as f:
        src, *expect_blocks = f.read().split("// expected ")
    expects = {}
    for expect_block in expect_blocks:
        expected, block = expect_block.split(":\n", 1)
        block = "".join(
            line.removeprefix("// ")
            for line in block.splitlines(keepends=True)
            if line.strip()
        )
        expects[expected] = block
    if not expects:
        raise ValueError(f"Invalid test file: {path}")

    description = src.splitlines()[0].strip("/ ")
    for expect, expected in expects.items():
        name = f"test_{path}_{expect}"
        doc = f"{description} ({path}) [{expect}]"
        match expect:
            case "output":
                func = run_interpreted
            case "assembly":
                func = compile_to_assembly
            case _:
                raise ValueError(f"Invalid expectation '{expect}' in {path}")
        yield make_testfunc(name, doc, partial(func, src), expected)


# pylint: disable=missing-function-docstring
def make_testfunc(name, doc, func, expected):
    def testfunc(self):
        actual = func()
        self.assertEqual(actual, expected)
    testfunc.__name__ = name
    testfunc.__doc__ = doc
    return testfunc


class ExamplesTestCase(unittest.TestCase):
    """Test that the examples in the tests directory run without error."""
    maxDiff = 2048


test_dir = Path(__file__).parent.relative_to(Path.cwd())
for example in test_dir.glob("*.kod"):
    for test in make_tests(example):
        setattr(ExamplesTestCase, test.__name__, test)
