"""The `kod` launcher (kod/__main__.py): the public commands go to the native
tool, and when there is none it says so instead of building something else."""

import os
import shutil
import signal
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


def test_a_program_run_through_the_launcher_dies_of_a_closed_pipe():
    # Python ignores SIGPIPE, and exec keeps an ignored signal ignored, so
    # unless the launcher resets it `uv run kod run prog | head` is a program
    # that writes to a pipe nobody reads and carries on.
    stem = f"huge_launcher_{os.getpid()}"
    source = ROOT / "build" / f"{stem}.kod"
    source.write_bytes((ROOT / "tests" / "stdio" / "huge.kod").read_bytes())
    proc = subprocess.Popen(
        [sys.executable, "-m", "kod", "run", str(source.relative_to(ROOT))],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        assert proc.stdout is not None
        assert proc.stdout.read(1) == b"0"
        proc.stdout.close()
        assert proc.wait(timeout=120) == -signal.SIGPIPE
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        source.unlink(missing_ok=True)
        shutil.rmtree(ROOT / "build" / "apps" / stem, ignore_errors=True)
