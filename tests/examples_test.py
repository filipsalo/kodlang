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


def run_selfhosted(path: str) -> subprocess.CompletedProcess:
    """Compile with kodc.kod (self-hosted compiler) and run the result."""
    path = Path(path)
    stem = path.stem
    build_dir = Path("build")
    build_dir.mkdir(exist_ok=True)

    # Python build to get all object files (builtins, runtime_main, arena, runtime).
    py_build = subprocess.run(
        [sys.executable, "-m", "kod", "build", str(path)],
        capture_output=True,
        text=True,
    )
    if py_build.returncode != 0:
        return py_build

    # Extract the ld command from builder stderr so we know the exact object file list.
    ld_cmd = None
    for line in py_build.stderr.splitlines():
        clean = re.sub(r"\x1b\[[^m]*m", "", line).strip()
        if clean.startswith("=> ld "):
            ld_cmd = clean[3:].split()

    if ld_cmd is None:
        return subprocess.CompletedProcess(
            [], 1, stdout="", stderr="no ld command in build output"
        )

    # Self-hosted compilation: kodc.kod → assembly on stdout.
    sh_asm = subprocess.run(
        [sys.executable, "-m", "kod", "interpret", "kodc.kod", str(path)],
        capture_output=True,
        text=True,
    )
    if sh_asm.returncode != 0:
        return sh_asm

    sh_s = build_dir / f"sh_{stem}.s"
    sh_o = build_dir / f"sh_{stem}.o"
    sh_s.write_text(sh_asm.stdout)

    # Assemble.
    as_result = subprocess.run(
        ["as", "-target", "arm64-apple-darwin", "-o", str(sh_o), str(sh_s)],
        capture_output=True,
        text=True,
    )
    if as_result.returncode != 0:
        return as_result

    # Re-link: replace _{stem}.o with the self-hosted sh_{stem}.o.
    py_o = f"_{stem}.o"
    ld_cmd = [
        str(sh_o) if (arg.endswith(f"/{py_o}") or arg == f"build/{py_o}") else arg
        for arg in ld_cmd
    ]
    out_idx = ld_cmd.index("-o") + 1
    ld_cmd[out_idx] = str(build_dir / f"sh_{stem}")

    ld_result = subprocess.run(ld_cmd, capture_output=True, text=True)
    if ld_result.returncode != 0:
        return ld_result

    return subprocess.run(
        [str(build_dir / f"sh_{stem}")],
        capture_output=True,
        text=True,
        timeout=5,
    )


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
    for path in sorted(test_dir.glob("**/*.kod")):
        _, expects = parse_example(path)
        mode = expects.get("mode", "both").strip()
        if mode == "skip":
            continue
        if "errors" in expects:
            yield pytest.param(compile_to_assembly, path, expects, id=f"{path} compile")
        else:
            if mode != "interpret":
                yield pytest.param(run_compiled, path, expects, id=f"{path} run")
            yield pytest.param(run_interpreted, path, expects, id=f"{path} interpret")

            sh_marker = expects.get("selfhosted", "").strip()
            marks = (
                [pytest.mark.skip(reason="not yet supported in self-hosted mode")]
                if sh_marker == "skip"
                else []
            )
            yield pytest.param(
                run_selfhosted, path, expects, id=f"{path} selfhosted", marks=marks
            )


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
