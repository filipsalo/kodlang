"""`kod test` runs each test in a process of its own (docs/testing.md)."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KOD = ROOT / "build" / "apps" / "kod" / "kod"


def test_a_panic_or_a_crash_fails_only_its_test(sh_kodc):
    r = subprocess.run(
        [str(KOD), "test", "tests/support/crashing_tests.kod"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert r.returncode == 1, r.stdout + r.stderr
    results = [
        line.split()[:2] for line in r.stdout.splitlines() if line.startswith("  ")
    ]
    assert results == [
        ["FAIL", "fails"],
        ["FAIL", "panics"],
        ["FAIL", "crashes"],
        ["ok", "runs"],
    ], r.stdout
    assert "1/4 passed" in r.stdout
    assert "assertion failed: 1 == 2" in r.stderr
    assert "panic: index 5 out of bounds" in r.stderr
    assert '#0  test "panics"' in r.stderr
    assert "killed by SIGSEGV" in r.stderr
