"""On a terminal, `kod` colours errors and the test report; on a pipe, or with
NO_COLOR or TERM=dumb, it doesn't. The terminal is a pseudo-terminal."""

import os
import pty
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
KOD = ROOT / "build" / "apps" / "kod" / "kod"
ESC = "\033["

pytestmark = pytest.mark.usefixtures("sh_kodc")


def on_terminal(argv: list[str], **env: str) -> str:
    """What `argv` writes to a terminal, stdout and stderr together."""
    full = {k: v for k, v in os.environ.items() if k != "NO_COLOR"}
    full["TERM"] = "xterm"
    full.update(env)
    master, slave = pty.openpty()
    p = subprocess.Popen(
        argv, cwd=ROOT, env=full, stdin=slave, stdout=slave, stderr=slave
    )
    os.close(slave)
    out = b""
    while True:
        try:
            chunk = os.read(master, 65536)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
    p.wait(timeout=60)
    os.close(master)
    return out.decode()


@pytest.fixture
def bad(tmp_path: Path) -> Path:
    path = tmp_path / "bad.kod"
    path.write_text('func main() { let x: int64 = "a" }\n')
    return path


@pytest.fixture
def mixed(tmp_path: Path) -> Path:
    path = tmp_path / "mixed_test.kod"
    path.write_text(
        'test "good" {\n    assert 1 == 1\n}\n\ntest "bad" {\n    assert 1 == 2\n}\n'
    )
    return path


def test_errors_are_coloured_on_a_terminal(bad: Path) -> None:
    out = on_terminal([str(KOD), "check", str(bad)])
    bold, red, reset = f"{ESC}1m", f"{ESC}31m", f"{ESC}0m"
    assert (
        f"{bold}{bad}:1:30:{reset} {bold}{red}error:{reset} {bold}expected `int64`, got `str`{reset}"
        in out
    )
    assert f"{bold}{red}{' ' * 29}^{reset}" in out
    # The source line is left as it is.
    assert '\r\nfunc main() { let x: int64 = "a" }\r\n' in out


@pytest.mark.parametrize("env", [{"NO_COLOR": "1"}, {"TERM": "dumb"}])
def test_errors_are_plain_when_colour_is_off(bad: Path, env: dict[str, str]) -> None:
    out = on_terminal([str(KOD), "check", str(bad)], **env)
    assert f"{bad}:1:30: error: expected `int64`, got `str`" in out
    assert ESC not in out


def test_an_empty_no_color_leaves_colour_on(bad: Path) -> None:
    assert ESC in on_terminal([str(KOD), "check", str(bad)], NO_COLOR="")


def test_the_test_report_is_coloured_on_a_terminal(mixed: Path) -> None:
    out = on_terminal([str(KOD), "test", str(mixed)])
    assert f"  {ESC}32mok  {ESC}0m good {ESC}2m(" in out
    assert f"  {ESC}31m{ESC}1mFAIL{ESC}0m{ESC}0m bad {ESC}2m(" in out
    assert f"{ESC}31m{ESC}1m1/2 passed in " in out


def test_the_test_report_is_plain_with_no_color(mixed: Path) -> None:
    out = on_terminal([str(KOD), "test", str(mixed)], NO_COLOR="1")
    assert "  ok   good (" in out
    assert ESC not in out
