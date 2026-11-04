"""The `kod` launcher (kod/__main__.py): the public commands go to the native
tool, and when there is none it says so instead of building something else."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from kod import __main__ as launcher

ROOT = Path(__file__).resolve().parent.parent
MISSING = (
    "kod: build/apps/kod/kod not found; "
    "run kod from the repository root after `make kod`\n"
)


def launch(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    """Run the launcher in `cwd` (which may be outside the repository)."""
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    return subprocess.run(
        [sys.executable, "-m", "kod", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize("command", ["build", "run", "check", "test"])
def test_outside_a_checkout_it_says_what_is_missing(command, tmp_path):
    (tmp_path / "hello.kod").write_text("func main() -> int64 {\n    return 0\n}\n")
    result = launch(command, "hello.kod", cwd=tmp_path)
    assert result.returncode == 1
    assert result.stderr == MISSING
    assert result.stdout == ""
    assert list(tmp_path.iterdir()) == [tmp_path / "hello.kod"]


def test_inside_a_checkout_it_hands_off_to_the_native_tool(sh_kodc):
    result = launch("run", "tests/hello.kod", cwd=ROOT)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "Hello, world!\n"
    result = launch("check", "tests/does_not_exist.kod", cwd=ROOT)
    assert result.returncode == 1
    assert "tests/does_not_exist.kod:1:1: error: no such file" in result.stderr


@pytest.mark.parametrize(
    "command",
    ["_emit-asm", "_dump-ast", "_emit-test-runtime-main"]
    + ["_interpret", "_emit-runtime-main"],
)
def test_the_debug_commands_that_built_things_are_gone(command):
    result = launch(command, "tests/hello.kod", cwd=ROOT)
    assert result.returncode == 2
    assert "invalid choice" in result.stderr
    assert result.stdout == ""


def test_the_test_command_it_lists_takes_a_path_as_the_native_tool_does(sh_kodc):
    # `kod test` alone is the native tool's usage, not a run of `.`.
    result = launch("test", cwd=ROOT)
    assert result.returncode == 1
    assert "kod test <file-or-dir>" in result.stderr
    assert "kod test <path>" in launcher.__doc__
    with pytest.raises(SystemExit):
        launcher._make_parser().parse_args(["test"])
