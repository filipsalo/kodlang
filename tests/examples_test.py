"""Example-based tests for the compiler."""

import os
import re
import subprocess
import sys
import types
from pathlib import Path
from typing import Generator

import _pytest
import pytest

ROOT = Path(__file__).resolve().parent.parent


def run_interpreted(path: str) -> subprocess.CompletedProcess:
    """Run a program in the interpreter."""
    result = subprocess.run(
        [sys.executable, "-m", "kod", "_interpret", path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return result


def run_compiled(path: str) -> subprocess.CompletedProcess:
    """Run a program compiled to an executable. The Builder picks the native
    self-hosted compiler at build/stage1/sh_kodc automatically when it exists."""
    result = subprocess.run(
        [sys.executable, "-m", "kod", "run", path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return result


def compile_to_assembly(path: str) -> subprocess.CompletedProcess:
    """Compile a program to assembly."""
    result = subprocess.run(
        [sys.executable, "-m", "kod", "_emit-asm", path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return result


def parse_example(path: Path) -> tuple[str, dict[str, str]]:
    """Parse an example file into source and expected results."""
    with path.open() as f:
        src, *expect_blocks = f.read().split("// expected ")
    expects = {}
    for expect_block in expect_blocks:
        expected, block = expect_block.split(":\n", 1)
        block = "".join(
            line.removeprefix("// ")
            for line in block.splitlines(keepends=True)
            if line.strip()
        )
        expects[expected] = block
    return src, expects


def generate_tests() -> Generator[_pytest.mark.structures.ParameterSet, None, None]:
    """Generate tests from example files."""
    test_dir = Path(__file__).parent.relative_to(Path.cwd())
    for path in sorted(test_dir.glob("**/*.kod")):
        _, expects = parse_example(path)
        mode = expects.get("mode", "both").strip()
        if mode == "skip":
            continue
        if "errors" in expects:
            yield pytest.param(compile_to_assembly, path, expects, id=f"{path} compile")
        else:
            if mode != "interpret":
                yield pytest.param(run_compiled, path, expects, id=f"{path} run")
            if mode != "run":
                yield pytest.param(
                    run_interpreted, path, expects, id=f"{path} interpret"
                )


@pytest.mark.parametrize("func,path,expects", generate_tests())
def test_example(func: types.FunctionType, path: str, expects: dict[str, str], sh_kodc):
    """Run example-based tests. The sh_kodc fixture ensures the native
    self-hosted compiler is built once before any `run` test executes."""
    result = func(path)
    assert result
    if not expects:
        return
    if "output" in expects:
        assert result.stdout == expects["output"]
    if "stderr" in expects:
        # The Kod CLI prints its own build-progress chatter to stderr,
        # so we accept any stderr that *contains* the expected substring
        # (with terminal color escapes stripped) rather than requiring
        # byte-for-byte equality.
        stderr = re.sub("\033[^m]+?m", "", result.stderr)
        assert expects["stderr"] in stderr
    if "errors" in expects:
        expects["status"] = "1"
        for error in expects["errors"].splitlines():
            error = f"{path}:{error}"
            stderr = result.stderr
            # TODO: Don't emit colors at all when output is not a tty
            stderr = re.sub("\033[^m]+?m", "", stderr)

            assert error in stderr
    assert result.returncode == int(expects.get("status", 0))


TEST_BLOCK = re.compile(r"^[ \t]*test\b", re.MULTILINE)
TEST_SUMMARY = re.compile(r"^(\d+)/(\d+) passed", re.MULTILINE)


def run_kod_test(path: Path | str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "kod", "test", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def find_test_block_files() -> Generator[Path, None, None]:
    """Every `*_test.kod` in the repo that contains `test` blocks, relative
    to the repo root. Skips build output and dot-directories (worktrees)."""
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel_dir = Path(dirpath).relative_to(ROOT)
        dirnames[:] = sorted(
            d
            for d in dirnames
            if not d.startswith(".") and not (rel_dir == Path(".") and d == "build")
        )
        for name in sorted(filenames):
            if not name.endswith("_test.kod"):
                continue
            path = Path(dirpath) / name
            if TEST_BLOCK.search(path.read_text()):
                yield path.relative_to(ROOT)


@pytest.mark.parametrize("path", find_test_block_files(), ids=str)
def test_kod_test_blocks(path: Path, sh_kodc):
    """Run a file's `test` blocks (and those of the modules it imports), and
    check that at least the file's own blocks actually ran."""
    result = run_kod_test(path)
    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 0, output
    summary = TEST_SUMMARY.search(result.stdout)
    assert summary, output
    passed, total = int(summary[1]), int(summary[2])
    assert passed == total, output
    assert total >= len(TEST_BLOCK.findall((ROOT / path).read_text())), output


def test_kod_test_reports_failures(sh_kodc):
    """A failing `test` block fails the run (guards against the runner
    silently passing everything)."""
    result = run_kod_test("tests/test_block_canary.kod")
    assert result.returncode == 1, f"{result.stdout}\n{result.stderr}"
    assert "1/2 passed" in result.stdout
    assert "FAIL canary: this test fails" in result.stdout


def test_read_file_pipe(sh_kodc):
    """io.read_file on a pipe must read to EOF; ftell can't size it."""
    path = "tests/read_file_stdin.kod"
    data = b"".join(b"line %06d of piped input\n" % i for i in range(12000))
    build = subprocess.run(
        [sys.executable, "-m", "kod", "build", path],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    assert build.returncode == 0, build.stderr.decode()
    for cmd in (
        [str(ROOT / "build/apps/read_file_stdin/read_file_stdin")],
        [sys.executable, "-m", "kod", "_interpret", path],
    ):
        result = subprocess.run(
            cmd, cwd=ROOT, input=data, capture_output=True, timeout=30, check=False
        )
        assert result.returncode == 0, result.stderr.decode()
        assert result.stdout == b"%d\n" % len(data) + data + b"\n"


@pytest.mark.parametrize(
    "target",
    [
        "tests/xmod_return_kind.kod",
        "tests/interface_dispatch.kod",
        "tests/selfhost_parity.kod",
    ],
)
def test_selfhost_matches_interpreter(target: str, sh_kodc):
    """Byte-identity check between the native sh_kodc binary and kodc.kod
    driven through the Python interpreter. Keeps the bootstrap path (which
    runs the compiler under the interpreter) honest. The targets cover
    imports, structs, enums, interfaces, match, methods, and (via
    selfhost_parity.kod) the statement lowering the compiler sources use."""
    sh_out = subprocess.run(
        [str(sh_kodc), target],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    py_out = subprocess.run(
        [sys.executable, "-m", "kod", "_interpret", "kodc.kod", target],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert sh_out.returncode == 0, f"sh_kodc failed: {sh_out.stderr}"
    assert py_out.returncode == 0, f"interpreter failed: {py_out.stderr}"
    # Guard against comparing two empty modules.
    assert ".globl" in sh_out.stdout, f"sh_kodc emitted no symbols for {target}"
    assert (
        sh_out.stdout == py_out.stdout
    ), f"sh_kodc and interpreter diverge on {target}"


def test_selfhost_fixed_point(sh_kodc):
    """The current compiler, compiled by itself twice, emits identical
    assembly both times (see `make selfhost-check`)."""
    result = subprocess.run(
        ["make", "-s", "selfhost-check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


@pytest.mark.parametrize("via", ["sh_kodc", "kod build"])
def test_missing_entry_file_is_an_error(via: str, sh_kodc):
    missing = "tests/does_not_exist.kod"
    if via == "sh_kodc":
        cmd = [str(sh_kodc), missing]
    else:
        cmd = [sys.executable, "-m", "kod", "build", missing]
    result = subprocess.run(
        cmd, cwd=ROOT, capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 1
    assert f"{missing}:1:1: error: no such file" in result.stderr


def test_let_else_checks_keep_memory_linear(sh_kodc, tmp_path):
    """Deciding whether each let-else's `else` block can finish doesn't copy
    every local of the function, so 2000 of them stay within a few times
    the memory of compiling one."""
    lines = ["func g(anon k: int64) -> int64? {", "    return k", "}"]
    lines.append("func f(anon k: int64) -> int64 {")
    for i in range(2000):
        lines += [
            f"    let .Some(v{i}) = g(k + {i}) else {{",
            f"        return {i}",
            "    }",
        ]
    lines += ["    return v0", "}", "func main() -> int64 {", "    return f(1)", "}"]
    src = tmp_path / "let_else_many.kod"
    src.write_text("\n".join(lines) + "\n")
    probe = (
        "import resource, subprocess, sys\n"
        "r = subprocess.run(sys.argv[1:], capture_output=True)\n"
        "print(r.returncode, resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe, str(sh_kodc), str(src)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    rc, maxrss = result.stdout.split()
    assert rc == "0", result.stderr
    # ru_maxrss is in bytes on macOS and in kilobytes elsewhere.
    rss = int(maxrss) if sys.platform == "darwin" else int(maxrss) * 1024
    assert rss < 300 * 2**20, f"{rss // 2**20} MB"


def test_scope_hints_keep_memory_linear(sh_kodc, tmp_path):
    """Each function is decided once for the hints of 1000 errors along a chain."""
    lines = ["type Hard = struct {", "    tag: str"]
    lines += ["    func fail(self, anon msg: str) -> none {", "        kod_panic(msg)"]
    lines += ["    }", "}"]
    n = 1000
    for i in range(n):
        lines += [f"func d{i}(anon msg: str) -> none {{", f"    d{i + 1}(msg)", "}"]
    lines += [f"func d{n}(anon msg: str) -> none {{", '    let h = Hard(tag: "x")']
    lines += ["    h.fail(msg)", "}"]
    for i in range(n):
        lines += [f"func f{i}(anon k: int64) -> int64 {{", f'    return d{i}("x")', "}"]
    lines += ["func main() -> int64 {", "    return 0", "}"]
    src = tmp_path / "hint_chain.kod"
    src.write_text("\n".join(lines) + "\n")
    probe = (
        "import resource, subprocess, sys\n"
        "r = subprocess.run(sys.argv[1:], capture_output=True, text=True)\n"
        "print(r.stderr.count('ends in `h.fail(msg)`'),"
        " resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe, str(sh_kodc), str(src)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    hints, maxrss = result.stdout.split()
    assert hints == str(n), result.stderr
    rss = int(maxrss) if sys.platform == "darwin" else int(maxrss) * 1024
    assert rss < 300 * 2**20, f"{rss // 2**20} MB"


def test_interpreter_reads_a_plus_chain_once(monkeypatch):
    """Whether an operand of `+` takes its enum from a slot is worked out
    once per operand, so a long chain is evaluated in linear time."""
    from kod import __main__ as cli
    from kod import interpreter

    calls = 0
    slot_target = interpreter._slot_target

    def counting(expr):
        nonlocal calls
        calls += 1
        return slot_target(expr)

    monkeypatch.setattr(interpreter, "_slot_target", counting)
    terms = " + ".join(["i"] * 100)
    src = ROOT / "build" / f"plus_chain_{os.getpid()}.kod"
    src.parent.mkdir(exist_ok=True)
    src.write_text(
        "func main() -> int64 {\n    mut t = 0\n    mut i = 0\n"
        f"    for i < 20 {{\n        t = t + {terms}\n        i += 1\n    }}\n"
        "    return t\n}\n"
    )
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(sys, "argv", ["kod", "_interpret", str(src.relative_to(ROOT))])
    try:
        with pytest.raises(SystemExit) as exited:
            cli.main()
    finally:
        src.unlink()
    assert exited.value.code == 19000
    assert calls < 20 * 100
