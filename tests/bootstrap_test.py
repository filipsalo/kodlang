"""The snapshot is the only way to build the compiler: `make` says how to get
one back when it is gone, and refreshing one can't lose the old one."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def make(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["make", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_without_a_snapshot_make_says_how_to_restore_it(tmp_path):
    missing = tmp_path / "sh_kodc"
    result = make(
        "-s",
        "stage1",
        f"BOOTSTRAP_SH_KODC={missing}",
        f"KODC={missing}",
        f"STAGE0={tmp_path / 'stage0'}",
        f"STAGE1={tmp_path / 'stage1'}",
    )
    assert result.returncode != 0
    assert f"{missing} not found; restore it with: git checkout" in result.stderr


def test_a_refresh_replaces_the_snapshot_only_after_the_checks():
    recipe = make("-n", "bootstrap-snapshot")
    assert recipe.returncode == 0, recipe.stderr
    out = recipe.stdout
    assert "rm -f bootstrap/sh_kodc" not in out
    assert "cp build/selfhost/stage2/stage1/sh_kodc bootstrap/sh_kodc.new" in out
    replace = out.index("mv bootstrap/sh_kodc.new bootstrap/sh_kodc")
    assert out.index("cmp build/selfhost/stage2/stage1/sh_kodc") < replace
    assert out.index("tools/asm_diff.py --compilers") < replace
