"""Shared pytest fixtures."""

import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def sh_kodc():
    """Build (or refresh) the native self-hosted compiler once per session.

    The Builder used by `kod build` / `kod run` automatically picks up the
    binary at build/sh_kodc when it exists and is up to date with the
    compiler sources, falling back to the slow interpreter path otherwise.
    Returns the path to the binary.
    """
    root = Path(__file__).parent.parent
    script = root / "scripts" / "build_sh_kodc.sh"
    result = subprocess.run([str(script)], cwd=root, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.fail(f"failed to build sh_kodc:\n{result.stdout}\n{result.stderr}")
    return root / "build" / "sh_kodc"
