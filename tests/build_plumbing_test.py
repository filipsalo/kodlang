"""Names and objects (docs/modules.md, "Symbol and object names"): a path of
any shape builds, modules with the same name link, and each object is named
after its source path. Everything goes through the native `kod` tool."""

import contextlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parent.parent
KOD = ROOT / "build" / "apps" / "kod" / "kod"

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
