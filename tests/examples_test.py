"""Example-based tests for the compiler."""

import io
import subprocess
import sys
from pathlib import Path

import pytest

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


def generate_tests():
    """Generate tests from example files."""
    test_dir = Path(__file__).parent.relative_to(Path.cwd())
    for path in test_dir.glob("*.kod"):
        src, expects = parse_example(path)
        if not expects:
            yield pytest.param(
                compile_to_assembly, src, expects, id=f"{path.stem}_compile"
            )
        else:
            yield pytest.param(run_compiled, src, expects, id=f"{path.stem}_run")
            yield pytest.param(
                run_interpreted, src, expects, id=f"{path.stem}_interpret"
            )


@pytest.mark.parametrize("func,src,expects", generate_tests())
def test_example(func, src: str, expects: dict[str, str]):
    """Run example-based tests."""
    result = func(src)
    assert result
    if not expects:
        return
    if "output" in expects:
        assert result.stdout == expects["output"]
    assert result.returncode == int(expects.get("status", 0))
