"""Types are worked out once: with KOD_SHADOW_TYPES set, sh_kodc reports an
expression whose inferred type changes within a function, and a store into a
binding that has no type yet (docs/self-hosting.md). For a file that compiles,
only a change while compiling (`EE`, which narrowing makes) is allowed."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SH_KODC = ROOT / "build" / "stage1" / "sh_kodc"


def corpus() -> list[str]:
    files: list[Path] = []
    for top in ["tests", "stdlib", "tools", "examples"]:
        files += (ROOT / top).rglob("*.kod")
    return sorted(str(f.relative_to(ROOT)) for f in files)


@pytest.mark.parametrize("path", corpus())
def test_types_are_worked_out_once(path: str, sh_kodc):
    result = subprocess.run(
        [str(SH_KODC), path],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        env={**os.environ, "KOD_SHADOW_TYPES": "1"},
    )
    if result.returncode != 0:
        return
    bad = [
        line
        for line in result.stderr.splitlines()
        if line.startswith("UNTYPED-STORE")
        or (line.startswith("SHADOW") and not line.startswith("SHADOW EE"))
    ]
    assert bad == []
