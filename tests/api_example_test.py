"""Run examples/github_repo.kod against tests/support/http_fixture.py, a local
stand-in for the GitHub API, and check what it prints and returns."""

import os
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
KOD = ROOT / "build" / "apps" / "kod" / "kod"
EXAMPLE = ROOT / "examples" / "github_repo.kod"
BINARY = ROOT / "build" / "apps" / "github_repo" / "github_repo"
FIXTURE = ROOT / "tests" / "support" / "http_fixture.py"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def example(sh_kodc) -> Path:
    built = subprocess.run(
        [str(KOD), "build", str(EXAMPLE)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    return BINARY


@pytest.fixture(scope="module")
def api() -> Iterator[str]:
    port = free_port()
    server = subprocess.Popen(
        [sys.executable, str(FIXTURE), str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.05)
        else:
            pytest.fail("the fixture server did not start")
        yield f"http://127.0.0.1:{port}"
    finally:
        server.terminate()
        server.wait(timeout=10)


def run(example: Path, args: list[str], api_url: str, token: str | None = None):
    env = {
        k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "GITHUB_API")
    }
    env["GITHUB_API"] = api_url
    if token is not None:
        env["GITHUB_TOKEN"] = token
    return subprocess.run(
        [str(example), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_a_repository_and_its_open_issues(example, api):
    r = run(example, ["octo/hello"], api)
    assert r.returncode == 0, r.stderr
    assert r.stdout == (
        "octo/hello\n"
        "  Café ☕ tools\n"
        "  language: Kod\n"
        "  stars: 1234, forks: 56\n"
        "  license: MIT\n"
        "open issues:\n"
        "  #7 It crashes\n"
        '  #3 Add "docs"\n'
    )
    assert r.stderr == ""


def test_missing_fields_fall_back(example, api):
    r = run(example, ["octo/secret"], api, token="s3cret")
    assert r.returncode == 0, r.stderr
    assert r.stdout == (
        "octo/secret\n"
        "  (no description)\n"
        "  language: unknown\n"
        "  stars: 0, forks: 0\n"
        "  license: none\n"
        "open issues:\n"
        "  none\n"
    )


def test_a_repository_with_no_issues(example, api):
    r = run(example, ["octo/quiet"], api)
    assert r.returncode == 0, r.stderr
    assert r.stdout.endswith("open issues:\n  none\n")


def test_the_token_is_sent_only_when_set(example, api):
    r = run(example, ["octo/secret"], api)
    assert r.returncode == 1
    assert r.stdout == ""
    assert r.stderr == "error: 404 Not Found: Not Found\n"


def test_an_error_body_that_is_not_json(example, api):
    r = run(example, ["octo/html"], api)
    assert r.returncode == 1
    assert r.stderr == "error: 502 Bad Gateway\n"


def test_an_unknown_repository(example, api):
    r = run(example, ["octo/none"], api)
    assert r.returncode == 1
    assert r.stderr == "error: 404 Not Found: Not Found\n"


@pytest.mark.parametrize("args", [[], ["name"], ["a/b", "extra"]])
def test_bad_usage(example, api, args):
    r = run(example, args, api)
    assert r.returncode == 2
    assert r.stdout == ""
    assert r.stderr == "usage: github_repo OWNER/REPO\n"


def test_an_unreachable_api(example):
    r = run(example, ["octo/hello"], f"http://127.0.0.1:{free_port()}")
    assert r.returncode == 1
    assert r.stdout == ""
    assert r.stderr.startswith("error: ")
    assert "connect" in r.stderr


def connections_so_far(api_url: str) -> int:
    """How many connections the fixture has served, counting this request's."""
    with urllib.request.urlopen(f"{api_url}/stats", timeout=10) as response:
        return int(response.read())


def test_both_requests_share_one_connection(example, api):
    before = connections_so_far(api)
    r = run(example, ["octo/hello"], api)
    assert r.returncode == 0, r.stderr
    after = connections_so_far(api)
    # `before` and `after` each count the connection that asked for them.
    assert after - before - 1 == 1
