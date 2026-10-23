"""Shared pytest fixtures."""

import fcntl
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def sh_kodc():
    """Build (or refresh) sh_kodc and the native `kod` driver once per
    session, so every `kod build/run/test` the tests spawn goes through the
    same, current driver on a fresh clone and locally. Returns the path to
    sh_kodc.
    """
    root = Path(__file__).parent.parent
    # Same lock as kod/__main__.py's toolchain refresh.
    (root / "build").mkdir(exist_ok=True)
    with open(root / "build" / ".toolchain.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result = subprocess.run(
            ["make", "stage1", "kod"], cwd=root, capture_output=True, text=True
        )
    if result.returncode != 0:
        pytest.fail(f"failed to build sh_kodc:\n{result.stdout}\n{result.stderr}")
    return root / "build" / "stage1" / "sh_kodc"
