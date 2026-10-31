"""The `kod` launcher (kod/__main__.py): the public commands go to the native
tool, and when there is none it says so instead of building something else."""

import os
import re
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
    "command", ["_emit-asm", "_dump-ast", "_emit-test-runtime-main"]
)
def test_the_debug_commands_that_built_things_are_gone(command):
    result = launch(command, "tests/hello.kod", cwd=ROOT)
    assert result.returncode == 2
    assert "invalid choice" in result.stderr
    assert result.stdout == ""


def test_interpret_prints_a_runtime_error_without_a_traceback():
    result = launch("_interpret", "tests/block_local_fn_gone_interpreted.kod", cwd=ROOT)
    assert result.returncode == 1
    stderr = re.sub("\033[^m]+?m", "", result.stderr)
    assert "9:15: error: `f` is declared in a block that has ended" in stderr
    assert "Traceback" not in stderr


@pytest.mark.parametrize(
    "entry,message",
    [
        ("stdlib/io.kod", "_emit-runtime-main: no `main` function in stdlib/io.kod"),
        ("nonexistent.kod", "nonexistent.kod:1:1: error: no such file"),
        (
            "tests/dep_signature_error.kod",
            "tests/no_such_dep_module.kod:1:1: error: no such file",
        ),
        ("tests/cyclic_import_enum.kod", "error: import cycle"),
    ],
)
def test_emit_runtime_main_says_what_is_wrong_without_a_traceback(
    entry, message, tmp_path
):
    out = tmp_path / "main.s"
    result = launch("_emit-runtime-main", entry, str(out), cwd=ROOT)
    assert result.returncode == 1
    assert message in result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout == ""
    assert not out.exists()


@pytest.mark.parametrize(
    "entry,message",
    [
        ("nonexistent.kod", "nonexistent.kod:1:1: error: no such file"),
        ("tests/cyclic_import_struct.kod", "error: import cycle"),
    ],
)
def test_interpret_says_what_is_wrong_without_a_traceback(entry, message):
    result = launch("_interpret", entry, cwd=ROOT)
    assert result.returncode == 1
    assert message in result.stderr
    assert "Traceback" not in result.stderr


def test_the_test_command_it_lists_takes_a_path_as_the_native_tool_does(sh_kodc):
    # `kod test` alone is the native tool's usage, not a run of `.`.
    result = launch("test", cwd=ROOT)
    assert result.returncode == 1
    assert "kod test <file-or-dir>" in result.stderr
    assert "kod test <path>" in launcher.__doc__
    with pytest.raises(SystemExit):
        launcher._make_parser().parse_args(["test"])
