"""Names and objects (docs/modules.md, "Symbol and object names"): a path of
any shape builds, modules with the same name link, and each object is named
after its source path. Everything goes through the native `kod` tool."""

import contextlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parent.parent
KOD = ROOT / "build" / "apps" / "kod" / "kod"
SH_KODC = ROOT / "build" / "stage1" / "sh_kodc"

# The `sh_kodc` fixture builds the tools these tests call.
pytestmark = pytest.mark.usefixtures("sh_kodc")


def program(output: str) -> str:
    return f'func main() -> int64 {{\n    print("{output}")\n    return 0\n}}\n'


def kod_build(entry: Path | str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(KOD), "build", str(entry)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def build_and_run(entry: Path | str, stem: str) -> str:
    """Build `entry` with the native tool, run `build/apps/<stem>/<stem>` and
    return what it printed."""
    built = kod_build(entry)
    assert built.returncode == 0, built.stderr
    exe = ROOT / "build" / "apps" / stem / stem
    ran = subprocess.run(
        [str(exe)], capture_output=True, text=True, timeout=5, check=False
    )
    assert ran.returncode == 0, ran.stderr
    return ran.stdout


@contextlib.contextmanager
def app_dir(stem: str) -> Iterator[Path]:
    """`build/apps/<stem>`, removed afterwards unless it was there before."""
    path = ROOT / "build" / "apps" / stem
    existed = path.exists()
    try:
        yield path
    finally:
        if not existed:
            shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def scratch() -> Iterator[Path]:
    """A fresh directory below build/, so that the entries in it are inside
    the project, as the interpreter requires."""
    (ROOT / "build").mkdir(exist_ok=True)
    path = Path(tempfile.mkdtemp(dir=ROOT / "build", prefix="names_"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.mark.parametrize("stem", ["gzip", "sort"])
def test_a_bench_program_named_like_a_stdlib_module_builds(stem: str):
    with app_dir(stem):
        built = kod_build(f"bench/{stem}.kod")
        assert built.returncode == 0, built.stderr


def test_dollar_and_slash_in_a_path_are_different_modules(scratch: Path):
    (scratch / "p").mkdir()
    (scratch / "p$q.kod").write_text("func f() -> int64 {\n    return 1\n}\n")
    (scratch / "p" / "q.kod").write_text("func f() -> int64 {\n    return 2\n}\n")
    entry = scratch / "dollar_probe.kod"
    entry.write_text(
        'import "./p$q"\nimport "./p/q"\n\n'
        'func main() -> int64 {\n    print(f"{q.f()}")\n    return 0\n}\n'
    )
    with app_dir("dollar_probe"):
        assert build_and_run(entry.relative_to(ROOT), "dollar_probe") == "2\n"


def test_an_entry_in_a_directory_with_a_very_long_name_builds(scratch: Path):
    deep = scratch / ("-" * 230)
    deep.mkdir()
    entry = deep / "far_away.kod"
    entry.write_text(program("far away"))
    assert len(str(entry)) > 240
    with app_dir("far_away"):
        assert build_and_run(entry, "far_away") == "far away\n"


def test_an_entry_named_obj_has_its_executable_and_objects_apart(scratch: Path):
    entry = scratch / "obj.kod"
    entry.write_text(program("obj"))
    with app_dir("obj") as app:
        assert build_and_run(entry.relative_to(ROOT), "obj") == "obj\n"
        assert (app / "obj").is_file()
        assert (app / "obj.obj").is_dir()


def test_objects_are_named_after_their_source_in_a_tree(scratch: Path):
    (scratch / "lib").mkdir()
    (scratch / "lib" / "helper.kod").write_text(
        'func name() -> str {\n    return "helper"\n}\n'
    )
    entry = scratch / "layout_probe.kod"
    entry.write_text(
        'import "json"\nimport "./lib/helper"\n\n'
        "func main() -> int64 {\n"
        '    let rendered: str = json.emit(json.parse("[]"))\n'
        '    print(f"{helper.name()} {rendered}")\n'
        "    return 0\n}\n"
    )
    source = entry.relative_to(ROOT)
    with app_dir("layout_probe") as app:
        assert build_and_run(source, "layout_probe") == "helper []\n"
        assert sorted(p.name for p in app.iterdir()) == [
            "layout_probe",
            "layout_probe.obj",
        ]
        objects = app / "layout_probe.obj"
        found = sorted(
            str(p.relative_to(objects)) for p in objects.rglob("*") if p.is_file()
        )
        wanted = []
        for module in [
            "stdlib/json",
            str(source.with_suffix("")),
            str(scratch.relative_to(ROOT) / "lib" / "helper"),
        ]:
            wanted += [f"{module}.kod.o", f"{module}.kod.s"]
        wanted += [f"{source}.main.o", f"{source}.main.s"]
        assert found == sorted(wanted)


# Shapes that only occur at the repository root: a module named like a
# stdlib module, and a path that starts with a digit. The files are written
# there for the length of one test.
ROOT_PROBES = {
    "io.kod": (
        'import "io"\n\n'
        "func is_file(anon path: str) -> bool {\n    return false\n}\n\n"
        "func main() -> int64 {\n"
        '    let ours: bool = is_file("kodc.kod")\n'
        '    let theirs: bool = io.is_file("kodc.kod")\n'
        '    print(f"{ours} {theirs}")\n'
        "    return 0\n}\n"
    ),
    "00_probe.kod": program("probe"),
    "00e_probe.kod": program("probe e"),
    "00_probe_dir/report.kod": program("report"),
}


@pytest.fixture
def root_probes() -> Iterator[None]:
    paths = [ROOT / name for name in ROOT_PROBES]
    directory = ROOT / "00_probe_dir"
    already = [str(p) for p in [*paths, directory] if p.exists()]
    if already:
        # Not ours to delete; a killed run may have left them.
        verb = "exists" if len(already) == 1 else "exist"
        pytest.fail(f"{', '.join(already)} {verb} already; delete them and run again")
    try:
        directory.mkdir()
        for name, source in ROOT_PROBES.items():
            (ROOT / name).write_text(source)
        yield
    finally:
        for path in paths:
            path.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            directory.rmdir()


@pytest.mark.parametrize(
    "entry,stem,output",
    [
        ("io.kod", "io", "false true\n"),
        ("00_probe.kod", "00_probe", "probe\n"),
        ("00e_probe.kod", "00e_probe", "probe e\n"),
        ("00_probe_dir/report.kod", "report", "report\n"),
    ],
)
def test_a_root_module_with_a_stdlib_twin_or_a_digit_builds(
    root_probes: None, entry: str, stem: str, output: str
):
    with app_dir(stem):
        assert build_and_run(entry, stem) == output


FAILING = 'test "must not run" {\n    fail("this test is not part of the run")\n}\n'
PASSING = 'test "runs" {\n    assert 1 + 1 == 2\n}\n'


def kod_test(target: Path | str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(KOD), "test", str(target)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_kod_test_of_a_directory_skips_dot_paths_and_a_build_directory(scratch: Path):
    (scratch / ".wt").mkdir()
    (scratch / "build").mkdir()
    (scratch / "ok_test.kod").write_text(PASSING)
    (scratch / ".wt" / "b_test.kod").write_text(FAILING)
    (scratch / ".stray_test.kod").write_text(FAILING)
    (scratch / "build" / "c_test.kod").write_text(FAILING)
    # What is left out is not looked at, a link to nothing included.
    (scratch / ".wt" / "dangling_test.kod").symlink_to("nowhere.kod")
    directory = scratch.relative_to(ROOT)
    stem = re.sub(r"[^A-Za-z0-9_-]", "_", str(directory)) + "_tests"
    with app_dir(stem) as app:
        result = kod_test(directory)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "1/1 passed" in result.stdout
        # One program for the directory, named after it.
        assert (app / f"{stem}_test").is_file()
        assert list((app / f"{stem}.obj").rglob("*.testmain.o"))
    # A file is taken whatever its path.
    with app_dir("b_test"):
        named = kod_test(directory / ".wt" / "b_test.kod")
        assert named.returncode == 1
        assert "0/1 passed" in named.stdout


def test_kod_test_of_a_directory_takes_two_test_files_of_one_name(scratch: Path):
    for name, answer in [("x", 1), ("y", 2)]:
        (scratch / name).mkdir()
        (scratch / name / "helper.kod").write_text(
            f"func answer() -> int64 {{\n    return {answer}\n}}\n"
        )
        (scratch / name / "dup_test.kod").write_text(
            f'import "./helper"\n\ntest "{name} answers" {{\n'
            f"    assert helper.answer() == {answer}\n}}\n"
        )
    directory = scratch.relative_to(ROOT)
    stem = re.sub(r"[^A-Za-z0-9_-]", "_", str(directory)) + "_tests"
    scratch_modules = sorted(p.name for p in ROOT.glob(".kod_test_runner*"))
    with app_dir(stem):
        result = kod_test(directory)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "2/2 passed" in result.stdout
    # No temporary module is left (or was made) at the project root.
    assert sorted(p.name for p in ROOT.glob(".kod_test_runner*")) == scratch_modules


def program_for_tests(directory: Path | str) -> str:
    """The program name `kod test <directory>` gives: the directory as it is
    spelled, without what a file name should not hold (its last 200 bytes
    at most), and `_tests`."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(directory))[-200:] + "_tests"


def test_kod_test_of_a_directory_does_not_run_a_directory_named_like_a_test_file(
    scratch: Path,
):
    (scratch / "dirnamed_test.kod").mkdir()
    (scratch / "dirnamed_test.kod" / "inner_test.kod").write_text(PASSING)
    (scratch / "real").mkdir()
    (scratch / "real" / "r_test.kod").write_text(PASSING)
    directory = scratch.relative_to(ROOT)
    with app_dir(program_for_tests(directory)):
        result = kod_test(directory)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "2/2 passed" in result.stdout


@pytest.mark.parametrize(
    "name", ["a\nb_test.kod", "\nb_test.kod", "a\nb/c_test.kod", "a\n/\nc_test.kod"]
)
def test_kod_test_of_a_directory_runs_a_test_file_with_a_newline_in_its_path(
    scratch: Path, name: str
):
    (scratch / "ok_test.kod").write_text(PASSING)
    (scratch / name).parent.mkdir(exist_ok=True)
    (scratch / name).write_text(FAILING)
    directory = scratch.relative_to(ROOT)
    with app_dir(program_for_tests(directory)):
        result = kod_test(directory)
        # `find` ends a name at a NUL byte; a newline is part of it.
        assert result.returncode == 1, result.stdout + result.stderr
        assert "1/2 passed" in result.stdout


def test_kod_test_of_a_directory_stops_at_a_test_file_it_cannot_read(scratch: Path):
    (scratch / "ok_test.kod").write_text(PASSING)
    (scratch / "dangling_test.kod").symlink_to("nowhere.kod")
    directory = scratch.relative_to(ROOT)
    with app_dir(program_for_tests(directory)):
        result = kod_test(directory)
        assert result.returncode == 1, result.stdout
        assert result.stderr == f"kod test: cannot read {directory}/dangling_test.kod\n"
        assert result.stdout == ""


@contextlib.contextmanager
def dash_directory(name: str) -> Iterator[Path]:
    """A directory at the project root whose name starts with `-`, removed
    afterwards, also when pytest is stopped by SIGTERM or SIGHUP."""
    path = ROOT / name
    if path.exists():
        # Not ours to delete; a killed run may have left it.
        pytest.fail(f"{path} exists already; delete it and run again")
    path.mkdir()

    def remove() -> None:
        shutil.rmtree(path, ignore_errors=True)

    with removed_if_signalled(remove):
        try:
            yield path
        finally:
            remove()


@pytest.fixture
def dash_dir() -> Iterator[Path]:
    with dash_directory("-dash_probe") as path:
        yield path


def test_a_signal_removes_the_directory_whose_name_starts_with_a_dash():
    code = (
        "import os, signal, sys, time\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from build_plumbing_test import dash_directory\n"
        "with dash_directory('-dash_signal_probe') as path:\n"
        "    (path / 'ok_test.kod').write_text('x')\n"
        "    print(path, flush=True)\n"
        "    os.kill(os.getpid(), signal.SIGTERM)\n"
        "    time.sleep(30)\n"
    )
    ran = subprocess.run(
        [sys.executable, "-c", code, str(ROOT / "tests")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    left = Path(ran.stdout.strip())
    try:
        assert ran.returncode == -signal.SIGTERM, ran.stderr
        assert left.name == "-dash_signal_probe"
        assert not left.exists()
    finally:
        shutil.rmtree(left, ignore_errors=True)


def test_kod_test_takes_a_directory_whose_name_starts_with_a_dash(dash_dir: Path):
    (dash_dir / "ok_test.kod").write_text(PASSING)
    with app_dir(program_for_tests(dash_dir.name)):
        result = kod_test(dash_dir.name)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "1/1 passed" in result.stdout


def test_kod_test_of_a_directory_with_a_very_long_absolute_name(scratch: Path):
    deep = scratch / ("d" * 120) / ("e" * 120)
    deep.mkdir(parents=True)
    (deep / "ok_test.kod").write_text(PASSING)
    assert len(str(deep)) > 300
    with app_dir(program_for_tests(deep)):
        result = kod_test(deep)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "1/1 passed" in result.stdout


@pytest.mark.parametrize("name", [".kod", "..kod", "...kod"])
def test_a_file_that_leaves_no_name_for_a_program_is_refused(scratch: Path, name: str):
    entry = scratch / name
    entry.write_text(PASSING + program("nameless"))
    source = entry.relative_to(ROOT)
    wanted = f"kod: cannot name a program after {source}; rename the file\n"
    built = kod_build(source)
    assert built.returncode == 1
    assert built.stderr == wanted
    tested = kod_test(source)
    assert tested.returncode == 1
    assert tested.stderr == wanted


def test_the_test_shim_calls_a_module_once_however_often_it_is_named(scratch: Path):
    for name in ["a_test.kod", "b_test.kod"]:
        (scratch / name).write_text(PASSING)
    a = scratch.relative_to(ROOT) / "a_test.kod"
    b = scratch.relative_to(ROOT) / "b_test.kod"
    shim = scratch / "shim.s"
    made = subprocess.run(
        [str(SH_KODC), "_emit-test-runtime-main", str(a), str(shim)]
        + [str(a), f"./{a}", str(b), str(a)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert made.returncode == 0, made.stderr
    calls = re.findall(r"bl \$(\S+)\$__run_tests", shim.read_text())
    assert calls == [
        str(a.with_suffix("")).replace("/", "$"),
        str(b.with_suffix("")).replace("/", "$"),
    ]


def test_a_tool_that_cannot_be_started_is_named(scratch: Path):
    entry = scratch / "no_path.kod"
    entry.write_text(program("never built"))
    with app_dir("no_path"):
        result = subprocess.run(
            [str(KOD), "build", str(entry.relative_to(ROOT))],
            cwd=ROOT,
            env={**os.environ, "PATH": ""},
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    assert result.returncode == 1
    assert (
        result.stderr
        == "kod: mkdir could not be run (not found, killed, or its argument list too long)\n"
    )
