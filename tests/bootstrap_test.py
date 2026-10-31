"""The no-snapshot bootstrap writes the `_main` shim of `kodc.kod` and
`tools/kod.kod` with `kod _emit-runtime-main` (kod/bootstrap.py), before any
`sh_kodc` exists. It must write what `sh_kodc _emit-runtime-main` writes, byte
for byte, so the bootstrap's `runtime_main.s` equals the snapshot build's."""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from kod.bootstrap import module_prefix

ROOT = Path(__file__).resolve().parent.parent

# The two compiler entries, and one entry per shape of `main`: no argv, a
# `T or Error` result, argv, argv with a result alias.
ENTRIES = [
    "kodc.kod",
    "tools/kod.kod",
    "tests/hello.kod",
    "tests/error_main.kod",
    "tests/match_int.kod",
    "tests/result_alias_main_ok.kod",
]


def python_shim(entry: str, out: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "kod", "_emit-runtime-main", entry, str(out)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize("entry", ENTRIES)
def test_python_shim_matches_sh_kodc(entry: str, sh_kodc, tmp_path):
    ours = tmp_path / "python.s"
    theirs = tmp_path / "sh_kodc.s"
    result = python_shim(entry, ours)
    assert result.returncode == 0, result.stderr
    native = subprocess.run(
        [str(sh_kodc), "_emit-runtime-main", entry, str(theirs)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert native.returncode == 0, native.stderr
    # Guard against comparing two empty files.
    assert ".globl _main" in ours.read_text()
    assert ours.read_text() == theirs.read_text()


def test_the_compiler_entries_have_no_stdlib_twin():
    """`kod/bootstrap.py` can't write the namespace marker a project module
    gets when a stdlib module has its path; these two entries must not have
    one."""
    assert not (ROOT / "stdlib" / "kodc.kod").exists()
    assert not (ROOT / "stdlib" / "tools" / "kod.kod").exists()


@pytest.mark.parametrize(
    "source,prefix",
    [
        ("kodc.kod", "kodc"),
        ("tools/kod.kod", "tools$kod"),
        ("tests/hello.kod", "tests$hello"),
        ("stdlib/io.kod", "io"),
        ("stdlib/kod/ast.kod", "kod$ast"),
        ("a/b_2.kod", "a$b_2"),
    ],
)
def test_module_prefix_of_a_plain_path(source: str, prefix: str):
    assert module_prefix(Path(source)) == prefix


@pytest.mark.parametrize(
    "source",
    ["my-app.kod", "tests/with space.kod", "a/p$q.kod", ".hidden.kod", "01_hello.kod"]
    + ["café.kod", "a/.b.kod"],
)
def test_module_prefix_refuses_a_path_it_cannot_escape(source: str):
    with pytest.raises(ValueError):
        module_prefix(Path(source))


def test_emit_runtime_main_refuses_such_a_path_with_a_message():
    # The interpreter reads only files inside the project, so the scratch
    # entry lives under build/, which a fresh checkout doesn't have yet.
    (ROOT / "build").mkdir(exist_ok=True)
    scratch = Path(tempfile.mkdtemp(dir=ROOT / "build", prefix="bootstrap_"))
    try:
        entry = scratch / "my-app.kod"
        entry.write_text("func main() -> int64 {\n    return 0\n}\n")
        out = scratch / "main.s"
        result = python_shim(str(entry.relative_to(ROOT)), out)
        assert result.returncode == 1
        assert "Traceback" not in result.stderr
        assert "can't write the symbol prefix" in result.stderr
        assert not out.exists()
    finally:
        shutil.rmtree(scratch)
