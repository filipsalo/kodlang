"""Example-based tests for the compiler."""

import re
import subprocess
import sys
import types
from pathlib import Path
from typing import Generator

import _pytest
import pytest


def run_interpreted(path: str) -> subprocess.CompletedProcess:
    """Run a program in the interpreter."""
    result = subprocess.run(
        [sys.executable, "-m", "kod", "interpret", path],
        stdout=subprocess.PIPE,
        text=True,
        check=False,
    )
    return result


def run_compiled(path: str) -> subprocess.CompletedProcess:
    """Run a program compiled to an executable."""
    result = subprocess.run(
        [sys.executable, "-m", "kod", "run", path],
        stdout=subprocess.PIPE,
        text=True,
        check=False,
    )
    return result


def compile_to_assembly(path: str) -> subprocess.CompletedProcess:
    """Compile a program to assembly."""
    result = subprocess.run(
        [sys.executable, "-m", "kod", "compile", path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return result


def parse_example(path: Path) -> tuple[str, dict[str, str]]:
    """Parse an example file into source and expected results."""
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
    return src, expects


def generate_tests() -> Generator[_pytest.mark.structures.ParameterSet, None, None]:
    """Generate tests from example files."""
    test_dir = Path(__file__).parent.relative_to(Path.cwd())
    for path in test_dir.glob("**/*.kod"):
        _, expects = parse_example(path)
        if "errors" in expects:
            yield pytest.param(compile_to_assembly, path, expects, id=f"{path} compile")
        else:
            yield pytest.param(run_compiled, path, expects, id=f"{path} run")
            yield pytest.param(run_interpreted, path, expects, id=f"{path} interpret")


@pytest.mark.parametrize("func,path,expects", generate_tests())
def test_example(func: types.FunctionType, path: str, expects: dict[str, str]):
    """Run example-based tests."""
    result = func(path)
    assert result
    if not expects:
        return
    if "output" in expects:
        assert result.stdout == expects["output"]
    if "stderr" in expects:
        assert result.stderr == expects["stderr"]
    if "errors" in expects:
        expects["status"] = "1"
        for error in expects["errors"].splitlines():
            error = f"{path}:{error}"
            stderr = result.stderr
            # TODO: Don't emit colors at all when output is not a tty
            stderr = re.sub("\033[^m]+?m", "", stderr)

            assert error in stderr
    assert result.returncode == int(expects.get("status", 0))
