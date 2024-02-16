"""Example-based tests for the compiler."""

import io
import subprocess
import sys
import unittest
from pathlib import Path

from kod.builder import Builder, FileWrapper


def run_interpreted(source):
    """Run a program in the interpreter."""
    result = subprocess.run(
        [sys.executable, "-m", "kod", "interpret", "-"],
        input=source,
        stdout=subprocess.PIPE,
        text=True,
        check=False,
    )
    return result


def run_compiled(source):
    """Run a program compiled to an executable."""
    result = subprocess.run(
        [sys.executable, "-m", "kod", "run", "-"],
        input=source,
        stdout=subprocess.PIPE,
        text=True,
        check=False,
    )
    return result


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
        # print(repr(expect_block))
        expected, block = expect_block.split(":\n", 1)
        block = "".join(
            line.removeprefix("// ")
            for line in block.splitlines(keepends=True)
            if line.strip()
        )
        expects[expected] = block

    description = src.splitlines()[0].strip("/ ")
    name = f"test_{path}"
    doc = f"{description} ({path})"
    yield make_testfunc(name, doc, src, expects)


# pylint: disable=missing-function-docstring
def make_testfunc(name, doc, src, expected):
    def testfunc(self):
        if not expected:
            asm = compile_to_assembly(src)
            self.assertTrue(asm)
            return
        compiled = run_compiled(src)
        if "status" not in expected:
            expected["status"] = "0"
        interpreted = run_interpreted(src)
        if "output" in expected:
            self.assertEqual(compiled.stdout, expected["output"])
            self.assertEqual(interpreted.stdout, expected["output"])
        if "status" in expected:
            self.assertEqual(compiled.returncode, int(expected["status"]))
            self.assertEqual(interpreted.returncode, int(expected["status"]))

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
