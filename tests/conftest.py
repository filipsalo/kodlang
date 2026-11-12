"""Shared pytest fixtures."""

import fcntl
import subprocess
from pathlib import Path

import pytest

# Tests that change what every other test uses: they rebuild or replace the
# `kod` driver, write into the project root, or run `make` on the real tree.
# `make test` runs them one at a time, after the rest has run in parallel.
SERIAL_MODULES = {"build_plumbing_test.py", "bootstrap_test.py", "launcher_test.py"}

# Kod test files whose tests build through stdlib/kod/test_support.kod, which
# writes to fixed scratch paths (`.kod_test_build_dir`, `build/apps/main`, ...).
TEST_SUPPORT_USERS = {
    "stdlib/build_test.kod",
    "stdlib/import_test.kod",
    "stdlib/panic_test.kod",
    "stdlib/kod/compiler_errors_test.kod",
    "stdlib/kod/match_exhaustiveness_test.kod",
}

# Modules whose tests all build the same program.
SHARED_PROGRAM = {
    "lsp_test.py": "lsp",
    "api_example_test.py": "api_example",
    "colour_test.py": "colour",
}


def build_group(item: pytest.Item) -> str | None:
    """Tests that build into the same `build/apps/<name>` share a group, which
    `pytest -n` with `--dist loadgroup` keeps on one worker."""
    module = item.path.name
    if module in SHARED_PROGRAM:
        return SHARED_PROGRAM[module]
    callspec = getattr(item, "callspec", None)
    path = callspec.params.get("path") if callspec else None
    if path is None:
        return None
    if str(path) in TEST_SUPPORT_USERS:
        return "test_support"
    return Path(path).stem


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "serial: changes what other tests use; not run in parallel"
    )


# First, so that xdist's own hook sees the groups.
@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if item.path.name in SERIAL_MODULES:
            item.add_marker(pytest.mark.serial)
        group = build_group(item)
        if group is not None:
            item.add_marker(pytest.mark.xdist_group(group))


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
