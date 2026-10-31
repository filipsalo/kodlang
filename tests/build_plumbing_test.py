"""Names and objects (docs/modules.md, "Symbol and object names"): a path of
any shape builds, modules with the same name link, and each object is named
after its source path. And the link configuration (docs/self-hosting.md, "The
link configuration"): `link.cfg` is read by Make and by the driver, and
programs are linked the way it says. Everything goes through the native `kod`
tool."""

import contextlib
import importlib.util
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Iterator

import pytest
from stdio_test import removed_if_signalled, running, stderr_text

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
def cleaned(path: Path) -> Iterator[Path]:
    """`path`, a file or a directory, removed afterwards unless it was there
    before."""
    existed = path.exists()
    try:
        yield path
    finally:
        if not existed:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)


def app_dir(stem: str) -> contextlib.AbstractContextManager[Path]:
    """`build/apps/<stem>`, removed afterwards unless it was there before."""
    return cleaned(ROOT / "build" / "apps" / stem)


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


@contextlib.contextmanager
def preserved(path: Path) -> Iterator[None]:
    """Put the file `path` back as it was (or remove it, if it was not there)
    when the body changes it."""
    before = path.read_bytes() if path.exists() else None
    try:
        yield
    finally:
        if before is None:
            path.unlink(missing_ok=True)
        elif not path.exists() or path.read_bytes() != before:
            # A new file, not a rewrite: macOS kills an executable that was
            # changed in place after it ran.
            fresh = path.with_name(path.name + ".restore")
            fresh.write_bytes(before)
            fresh.chmod(0o755)
            os.replace(fresh, path)


def tool_is_up_to_date() -> bool:
    made = subprocess.run(["make", "-s", "-q", "kod"], cwd=ROOT, check=False)
    return made.returncode == 0


@pytest.mark.parametrize(
    "spelling,name,what",
    [
        ("kod", "kod", "the build tool"),
        ("lsp", "lsp", "the language server"),
        # What a case-insensitive volume takes for the tool's directory
        # (U+212A, the Kelvin sign, is a k to it).
        ("KOD", "kod", "the build tool"),
        ("Kod", "kod", "the build tool"),
        ("\u212aod", "kod", "the build tool"),
        ("Lsp", "lsp", "the language server"),
    ],
)
def test_an_entry_that_would_replace_a_tool_is_refused(
    scratch: Path, spelling: str, name: str, what: str
):
    entry = scratch / f"{spelling}.kod"
    entry.write_text(program("not the tool"))
    tool = ROOT / "build" / "apps" / name / name
    existed = tool.exists()
    before = tool.read_bytes() if existed else b""
    # Without the guard the build replaces the tool, so put it back.
    with (
        cleaned(tool.parent),
        cleaned(tool.parent / f"{spelling}.obj"),
        preserved(tool),
    ):
        tool.parent.mkdir(parents=True, exist_ok=True)
        if not (tool.parent.parent / spelling).exists():
            pytest.skip("this volume tells that name from the tool's")
        assert tool_is_up_to_date()
        result = kod_build(entry.relative_to(ROOT))
        assert result.returncode == 1
        assert result.stderr == f"kod: an entry named {spelling} would replace {what}\n"
        assert result.stdout == ""
        assert tool.exists() == existed
        assert not existed or tool.read_bytes() == before
        assert tool_is_up_to_date()


@pytest.mark.parametrize(
    "tool,spelling",
    [
        ("kod", "tools/kod.kod"),
        ("kod", str(ROOT / "tools" / "kod.kod")),
        ("kod", "./tools/../tools/kod.kod"),
        ("lsp", str(ROOT / "tools" / "lsp.kod")),
    ],
)
def test_the_source_of_a_tool_is_not_refused_however_it_is_spelled(
    scratch: Path, tool: str, spelling: str
):
    # The build replaces the tool, so run a copy of it.
    copy = scratch / "kod_copy"
    shutil.copy2(KOD, copy)
    exe = ROOT / "build" / "apps" / tool / tool
    with cleaned(exe.parent), cleaned(exe.parent / f"{tool}.obj"), preserved(exe):
        result = subprocess.run(
            [str(copy), "build", spelling],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert result.returncode == 0, result.stderr


# --- The link configuration ------------------------------------------------

LINK_CFG = ROOT / "link.cfg"
LOCAL_CFG = ROOT / "link.local.cfg"

# The grammar of a line of link.cfg: empty, a comment, or `NAME := words`.
# Make and the driver read a line of this shape the same way; anything else
# is a line one of them would read differently.
CFG_NAME = r"[A-Z][A-Z0-9_]*"
CFG_WORD = r"[A-Za-z0-9_./,=+@-]+"
CFG_COMMENT = r"#(?:[^\t\r]*[^\t\r\\])?"
CFG_LINE = re.compile(rf"(?:{CFG_COMMENT}|{CFG_NAME} :=(?: {CFG_WORD})*)?")


def cfg_values(*files: Path) -> dict[str, list[str]]:
    """The names the files set and their words; a later file overrides an
    earlier one, as for Make and the driver."""
    values: dict[str, list[str]] = {}
    for path in files:
        if path.exists():
            for line in path.read_text().split("\n"):
                if line and not line.startswith("#"):
                    name, _, rest = line.partition(" :=")
                    values[name] = rest.split()
    return values


def make_in(root: Path, *args: str) -> subprocess.CompletedProcess:
    """Run `make <args>` in `root`."""
    return subprocess.run(
        ["make", *args],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def make_recipes(*args: str, root: Path = ROOT) -> list[str]:
    """The recipe lines `make -n -B <args>` prints, a continued line as one."""
    made = make_in(root, "-n", "-B", *args)
    assert made.returncode == 0, made.stderr
    assert "No rule to make target" not in made.stderr
    return made.stdout.replace("\\\n", " ").split("\n")


def make_variables(path: Path) -> dict[str, str]:
    """What Make reads from the makefile `path`: its variables and their
    values, from Make's database."""
    made = subprocess.run(
        ["make", "-pq", "-f", path.name],
        cwd=path.parent,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    variables = {}
    previous = ""
    for line in made.stdout.split("\n"):
        if previous.startswith("# makefile (from ") and path.name in previous:
            name, _, value = line.partition(" := ")
            if name != "MAKEFILE_LIST":  # Make's own, listed there too
                variables[name] = value
        previous = line
    return variables


def test_no_file_but_the_docs_names_the_linker_flags_and_sdk_it_used_to():
    # In pieces, so that this file does not hold them.
    needles = ["Command" + "LineTools", "macos_" + "version", "sw_" + "vers"]
    found = subprocess.run(
        ["git", "grep", "-n", "-i", "-I", *[f"-e{n}" for n in needles]]
        + ["--", ".", ":!docs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert found.returncode == 1, found.stdout


def test_link_cfg_is_tracked_and_link_local_cfg_is_not():
    listed = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "link.cfg"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert listed.returncode == 0, listed.stderr
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "link.local.cfg"], cwd=ROOT, check=False
    )
    assert ignored.returncode == 0


def test_link_cfg_obeys_the_restricted_grammar():
    text = LINK_CFG.read_text()
    assert text.endswith("\n")
    names = []
    for number, line in enumerate(text.split("\n")[:-1], 1):
        assert CFG_LINE.fullmatch(line), f"link.cfg:{number}: {line!r}"
        if line and not line.startswith("#"):
            names.append(line.split(" ")[0])
    assert len(names) == len(set(names)), "a name is set twice"
    assert {"LINK", "CC", "CFLAGS", "RUNTIME_C", "STAGE0_KOD"} <= set(names)


@pytest.mark.parametrize(
    "line",
    [
        " ",  # an empty line is empty
        "  # indented comment",
        "# comment ending in a backslash \\",
        "# a\tb",
        "# crlf\r",
        "link := a",  # a name is capitals, digits and _
        "1X := a",
        "_X := a",
        "X-Y := a",
        "X",  # := follows the name after one space
        "X = a",
        "X: a",
        "X:= a",
        "X  := a",
        "X ?= a",
        "X += a",
        "X ::= a",
        "X :=a",  # a space follows :=
        "X := a ",  # one space between words, none at the end
        "X := a  b",
        "X := ",
        "X :=  a",
        "\tX := a",
        "X :=\ta",
        "X := a\r",
        "X := a # trailing comment",
        "X := a#b",
        "X := $(CC)",
        "X := ${CC}",
        "X := a\\",
        'X := "a"',
        "X := 'a'",
        "X := `a`",
        "X := a;b",
        "X := a b|c",
        "X := a>b",
        "X := ~/a",
        "X := *.c",
        "X := %.c",
        "X := a:b",
        "X := caf\u00e9",
    ],
)
def test_the_grammar_of_link_cfg_leaves_out_what_make_would_read_differently(
    line: str,
):
    assert CFG_LINE.fullmatch(line) is None


def test_make_reads_every_line_the_grammar_accepts_as_its_words(elsewhere: Path):
    lines = [
        "# a comment: := $(shell false) \\ anything",
        "",
        "LINK := clang -target arm64-apple-darwin -Wl,-dead_strip",
        "EMPTY :=",
        "FLAGS := -DKOD=1 -std=c11 +x a=b -,- @ = - . / ,",
        "PATHS := /opt/homebrew/opt/openssl@3/lib ../a_b-c.d libc++.a",
        "N2_X := 1",
    ]
    assert all(CFG_LINE.fullmatch(line) for line in lines)
    cfg = elsewhere / "words.cfg"
    cfg.write_text("\n".join(lines) + "\n")
    want = {
        line.partition(" :=")[0]: line.partition(" :=")[2].removeprefix(" ")
        for line in lines
        if line and not line.startswith("#")
    }
    assert make_variables(cfg) == want


def test_make_keeps_what_the_grammar_leaves_out(elsewhere: Path):
    # Why the grammar is as strict as it is: Make keeps a trailing space, the
    # space before a #, and a doubled space, and it joins a line that ends in a
    # backslash with the next one.
    cfg = elsewhere / "loose.cfg"
    cfg.write_text("A := a b \nB := a # note\nC := a  b\nD := d \\\nE := e\n")
    assert make_variables(cfg) == {
        "A": "a b ",
        "B": "a ",
        "C": "a  b",
        "D": "d E := e",
    }


def test_the_lists_of_link_cfg_are_what_the_link_lines_name():
    config = cfg_values(LINK_CFG, LOCAL_CFG)
    objects = [f"build/stage0/{Path(c).stem}.o" for c in config["RUNTIME_C"]] + [
        f"build/stage0/_{Path(m).stem}.o" for m in config["STAGE0_KOD"]
    ]
    for target, exe in [
        ("stage1", "build/stage1/sh_kodc"),
        ("kod", "build/apps/kod/kod"),
    ]:
        links = [
            line.split() for line in make_recipes(target) if f" -o {exe} " in line + " "
        ]
        assert len(links) == 1, target
        words = links[0]
        at = words.index("-o")
        assert words[:at] == config["LINK"]
        assert words[at + 1] == exe
        assert words[at + 2 : at + 2 + len(objects)] == objects


def test_the_always_linked_objects_have_names_of_their_own():
    config = cfg_values(LINK_CFG, LOCAL_CFG)
    made = subprocess.run(
        ["make", "-pq", "stage0"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    compiler = next(
        line.partition(" := ")[2]
        for line in made.stdout.split("\n")
        if line.startswith("COMPILER_KOD := ")
    ).split()
    stage0 = [Path(m).stem for m in config["STAGE0_KOD"]]
    runtime = [Path(c).stem for c in config["RUNTIME_C"]]
    others = [Path(m).stem for m in compiler]
    assert len(set(stage0)) == len(stage0)
    assert len(set(runtime)) == len(runtime)
    # build/stage0/_<name>.o and <name>.o
    assert not set(stage0) & set(others)
    assert not {f"_{s}" for s in stage0} & set(runtime)


def test_make_stage0_has_a_rule_for_everything_link_cfg_lists():
    recipes = make_recipes("stage0")
    config = cfg_values(LINK_CFG, LOCAL_CFG)
    for module in config["STAGE0_KOD"]:
        assert any(f" {module} >" in line for line in recipes), module
    for source in config["RUNTIME_C"]:
        assert any(line.endswith(f" {source}") for line in recipes), source


def adjacent(words: list[str], *want: str) -> bool:
    return any(words[i : i + len(want)] == list(want) for i in range(len(words)))


def test_link_cfg_pins_the_target_and_the_flags_the_links_rely_on():
    own = cfg_values(LINK_CFG)
    assert own["LINK"][0] == "clang"
    # The target of the link is that of the objects and of `as`; dead code and
    # the functions only it calls are left out of an executable.
    assert adjacent(own["LINK"], "-target", "arm64-apple-darwin")
    assert "-Wl,-dead_strip" in own["LINK"]
    assert adjacent(own["CFLAGS"], "-target", "arm64-apple-darwin")
    # Where a companion C file finds the runtime header.
    assert adjacent(own["CFLAGS"], "-I", "stdlib")


def test_the_c_runtime_is_compiled_with_cc_and_cflags_of_link_cfg():
    config = cfg_values(LINK_CFG, LOCAL_CFG)
    cflags = " ".join(config["CFLAGS"])
    assert "-target arm64-apple-darwin" in " ".join(cfg_values(LINK_CFG)["CFLAGS"])
    recipes = make_recipes("stage0")
    for source in config["RUNTIME_C"]:
        want = (
            f"{' '.join(config['CC'])} {cflags} -c -o "
            f"build/stage0/{Path(source).stem}.o {source}"
        )
        assert want in recipes


@pytest.mark.parametrize("target", ["stage0", "stage1", "kod"])
def test_a_change_of_link_cfg_rebuilds_what_it_configures(target: str):
    # `-W` pretends the file changed, so no file's time is touched.
    def out_of_date(*args: str) -> int:
        return subprocess.run(
            ["make", "-q", *args, target], cwd=ROOT, check=False
        ).returncode

    assert out_of_date() == 0
    assert out_of_date("-W", "link.cfg") == 1


def test_a_change_of_link_cfg_rebuilds_the_c_objects_and_the_links_not_the_modules():
    # `-n -W` lists what would run if the file changed, and runs nothing.
    made = subprocess.run(
        ["make", "-n", "-W", "link.cfg", "stage1", "kod"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert made.returncode == 0, made.stderr
    lines = made.stdout.replace("\\\n", " ").split("\n")
    for source in cfg_values(LINK_CFG, LOCAL_CFG)["RUNTIME_C"]:
        assert any(
            f"-c -o build/stage0/{Path(source).stem}.o {source}" in line
            for line in lines
        )
    assert any(" -o build/stage1/sh_kodc " in line for line in lines)
    assert any(" -o build/apps/kod/kod " in line for line in lines)
    # A Kod module is not compiled again.
    assert not any(" > build/" in line for line in lines)


@pytest.mark.parametrize("target", ["stage0", "stage1", "kod"])
def test_a_change_of_a_header_rebuilds_what_includes_it(target: str):
    # runtime.c includes stdlib/kod_rt.h, and Make is told only of the .c file
    # (there are no dependency files), so a header is a prerequisite of its own.
    # `-W` pretends the file changed, so no file's time is touched.
    def out_of_date(*args: str) -> int:
        return subprocess.run(
            ["make", "-q", *args, target], cwd=ROOT, check=False
        ).returncode

    assert (ROOT / "stdlib" / "kod_rt.h").is_file()
    assert out_of_date() == 0
    assert out_of_date("-W", "stdlib/kod_rt.h") == 1


def test_a_change_of_a_header_rebuilds_the_c_objects_not_the_modules():
    made = subprocess.run(
        ["make", "-n", "-W", "stdlib/kod_rt.h", "stage1", "kod"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert made.returncode == 0, made.stderr
    lines = made.stdout.replace("\\\n", " ").split("\n")
    for source in cfg_values(LINK_CFG, LOCAL_CFG)["RUNTIME_C"]:
        assert any(
            f"-c -o build/stage0/{Path(source).stem}.o {source}" in line
            for line in lines
        )
    # The Kod modules are not compiled again.
    assert not any(" > build/" in line for line in lines)


def c_object(source: str, *flags: str) -> subprocess.CompletedProcess:
    """Compile the C source text with `CC` and `CFLAGS` of link.cfg, to a
    temporary object."""
    config = cfg_values(LINK_CFG, LOCAL_CFG)
    with temp_dir("kod_c_") as path:
        (path / "probe.c").write_text(source)
        return subprocess.run(
            [
                *config["CC"],
                *config["CFLAGS"],
                *flags,
                "-c",
                "-o",
                str(path / "probe.o"),
                str(path / "probe.c"),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )


def test_the_runtime_header_has_the_layout_the_generated_code_uses():
    # A str is {buf, len}, an array {ptr, len, cap}, each field 8 bytes.
    compiled = c_object(
        '#include "kod_rt.h"\n#include <stddef.h>\n'
        '_Static_assert(sizeof(KodStr) == 16, "KodStr");\n'
        '_Static_assert(offsetof(KodStr, buf) == 0, "buf");\n'
        '_Static_assert(offsetof(KodStr, len) == 8, "len");\n'
        '_Static_assert(sizeof(KodArray) == 24, "KodArray");\n'
        '_Static_assert(offsetof(KodArray, ptr) == 0, "ptr");\n'
        '_Static_assert(offsetof(KodArray, len) == 8, "array len");\n'
        '_Static_assert(offsetof(KodArray, cap) == 16, "cap");\n',
        "-Wall",
        "-Werror",
    )
    assert compiled.returncode == 0, compiled.stderr


def test_the_runtime_header_stands_alone_and_unused_helpers_cost_nothing():
    # Included first and twice, with every warning an unused static inline
    # function could draw, and used the way a companion would.
    compiled = c_object(
        '#include "kod_rt.h"\n#include "kod_rt.h"\n'
        "KodStr *kod_probe(KodArray *a, const char *p) {\n"
        "    if (a->len < 0) kod_panic(kod_str_new(0));\n"
        "    return kod_str_from_bytes(p, 3);\n"
        "}\n",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-Wunused-function",
    )
    assert compiled.returncode == 0, compiled.stderr


def test_runtime_o_exports_what_it_did_and_nothing_from_the_header():
    # The header's helpers are `static inline`, so they are no symbols.
    defined = subprocess.run(
        ["nm", "-g", "--defined-only", str(ROOT / "build" / "stage0" / "runtime.o")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert defined.returncode == 0, defined.stderr
    names = {line.split()[-1] for line in defined.stdout.splitlines() if line.strip()}
    for exported in [
        "_kod_panic",
        "_kod_str_from_cstr",
        "_kod_str_concat",
        "_read_file",
    ]:
        assert exported in names
    for local in ["_kod_str_new", "_kod_str_from_bytes", "_kod_str_alloc"]:
        assert local not in names


def run_bounded(argv: list, cwd: Path, **kwargs) -> tuple[int, str, str]:
    """Run `argv` in `cwd` as `running` does, so that a signal to pytest stops
    it before the directory it runs in is removed; its status, stdout and
    stderr."""
    with running(argv, cwd=cwd, **kwargs) as proc:
        assert proc.stdout is not None
        out = proc.stdout.read().decode(errors="replace")
        proc.wait()
        return proc.returncode, out, stderr_text(proc)


def run_driver(argv: list, cwd: Path, **kwargs) -> tuple[int, str, str]:
    """Run the driver in `cwd`; its status, stdout and stderr."""
    return run_bounded([KOD, *argv], cwd, **kwargs)


@contextlib.contextmanager
def temp_dir(prefix: str) -> Iterator[Path]:
    """A directory outside the project, removed afterwards, also when pytest
    is stopped by SIGTERM or SIGHUP."""
    path = Path(tempfile.mkdtemp(prefix=prefix)).resolve()

    def remove() -> None:
        shutil.rmtree(path, ignore_errors=True)

    with removed_if_signalled(remove):
        try:
            yield path
        finally:
            remove()


def test_a_signal_removes_what_every_enclosing_block_made_and_stops_the_programs():
    # A program started in the blocks is stopped before the directories go.
    code = (
        "import os, signal, sys, time\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from build_plumbing_test import running, temp_dir\n"
        "with temp_dir('kod_nest_outer_') as outer:\n"
        "    with temp_dir('kod_nest_inner_') as inner:\n"
        "        with running(['sleep', '60'], cwd=inner) as proc:\n"
        "            print(outer, inner, proc.pid, flush=True)\n"
        "            os.kill(os.getpid(), signal.SIGTERM)\n"
        "            time.sleep(30)\n"
    )
    ran = subprocess.run(
        [sys.executable, "-c", code, str(ROOT / "tests")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    outer, inner, pid = ran.stdout.split()
    try:
        assert ran.returncode == -signal.SIGTERM, ran.stderr
        assert not Path(outer).exists()
        assert not Path(inner).exists()
        for _ in range(100):  # the program is gone once init has reaped it
            try:
                os.kill(int(pid), 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            pytest.fail("the program is still running")
    finally:
        for left in (outer, inner):
            shutil.rmtree(left, ignore_errors=True)
        with contextlib.suppress(ProcessLookupError):
            os.kill(int(pid), signal.SIGKILL)


@pytest.fixture
def elsewhere() -> Iterator[Path]:
    """An empty directory: not a repository root."""
    with temp_dir("kod_elsewhere_") as path:
        yield path


@pytest.fixture
def driver_root() -> Iterator[Path]:
    """A directory the driver takes for the repository root: a copy of
    link.cfg, the built stage0 and stage1 and the stdlib by link, and a
    build/apps of its own, so that what it builds stays out of the real tree.
    A test adds a link.local.cfg to change the link."""
    if not re.fullmatch(r"[A-Za-z0-9_./,=+@-]+", tempfile.gettempdir()):
        pytest.skip("the temporary directory is not a path a link.cfg can name")
    with temp_dir("kod_root_") as path:
        (path / "build" / "apps").mkdir(parents=True)
        for built in ["stage0", "stage1"]:
            (path / "build" / built).symlink_to(ROOT / "build" / built)
        (path / "stdlib").symlink_to(ROOT / "stdlib")
        shutil.copyfile(LINK_CFG, path / "link.cfg")
        (path / "hello.kod").write_text(program("linked"))
        yield path


MISSING_ROOT = "kod: link.cfg not found; run kod from the repository root\n"


@pytest.mark.parametrize("command", ["build", "run", "test", "check"])
def test_the_driver_outside_the_repository_root_says_where_to_run_it(
    elsewhere: Path, command: str
):
    (elsewhere / "x.kod").write_text(program("x") + PASSING)
    status, out, err = run_driver([command, "x.kod"], cwd=elsewhere)
    assert (status, out, err) == (1, "", MISSING_ROOT)
    assert sorted(p.name for p in elsewhere.iterdir()) == ["x.kod"]


def test_the_driver_without_a_compiler_says_to_run_make(elsewhere: Path):
    shutil.copyfile(LINK_CFG, elsewhere / "link.cfg")
    (elsewhere / "x.kod").write_text(program("x"))
    status, out, err = run_driver(["build", "x.kod"], cwd=elsewhere)
    assert (status, out, err) == (
        1,
        "",
        "kod: build/stage1/sh_kodc not found; run make\n",
    )


def test_the_driver_without_a_command_prints_its_usage_wherever_it_is(elsewhere: Path):
    status, out, err = run_driver([], cwd=elsewhere)
    assert status == 1 and out == ""
    assert err.startswith("usage: kod build <file>\n")


def linked_with(root: Path, local: str) -> list[str]:
    """Build hello.kod in `root` with `local` as its link.local.cfg and a
    linker that records its arguments and then links; those arguments."""
    link = cfg_values(root / "link.cfg")["LINK"]
    recorder = root / "linkshim"
    recorder.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$@" > "$KOD_LINK_LOG"\nexec "$KOD_REAL_LINKER" "$@"\n'
    )
    recorder.chmod(0o755)
    (root / "link.local.cfg").write_text(local.replace("RECORDER", str(recorder)))
    log = root / "link.args"
    env = {**os.environ, "KOD_LINK_LOG": str(log), "KOD_REAL_LINKER": link[0]}
    status, _, err = run_driver(["build", "hello.kod"], cwd=root, env=env)
    assert status == 0, err
    assert err == ""
    return log.read_text().split("\n")[:-1]


def test_the_driver_links_as_link_cfg_says(driver_root: Path):
    config = cfg_values(driver_root / "link.cfg")
    flags = " ".join(config["LINK"][1:])
    argv = linked_with(driver_root, f"LINK := RECORDER {flags}\n")
    objects = [f"build/stage0/{Path(c).stem}.o" for c in config["RUNTIME_C"]] + [
        f"build/stage0/_{Path(m).stem}.o" for m in config["STAGE0_KOD"]
    ]
    assert argv == [
        *config["LINK"][1:],
        "-o",
        "build/apps/hello/hello",
        *objects,
        "build/apps/hello/hello.obj/hello.kod.o",
        "build/apps/hello/hello.obj/hello.kod.main.o",
    ]
    status, out, _ = run_bounded(
        [driver_root / "build/apps/hello/hello"], cwd=driver_root
    )
    assert (status, out) == (0, "linked\n")


def test_the_driver_links_the_always_linked_modules_in_the_order_link_cfg_gives(
    driver_root: Path,
):
    config = cfg_values(driver_root / "link.cfg")
    flags = " ".join(config["LINK"][1:])
    reversed_kod = " ".join(reversed(config["STAGE0_KOD"]))
    argv = linked_with(
        driver_root, f"LINK := RECORDER {flags}\nSTAGE0_KOD := {reversed_kod}\n"
    )
    objects = [f"build/stage0/{Path(c).stem}.o" for c in config["RUNTIME_C"]] + [
        f"build/stage0/_{Path(m).stem}.o" for m in reversed(config["STAGE0_KOD"])
    ]
    at = argv.index("-o")
    assert argv[at + 2 : at + 2 + len(objects)] == objects
    status, out, _ = run_bounded(
        [driver_root / "build/apps/hello/hello"], cwd=driver_root
    )
    assert (status, out) == (0, "linked\n")


def test_the_linker_is_the_one_link_cfg_names_and_link_local_cfg_overrides_it(
    driver_root: Path,
):
    (driver_root / "link.local.cfg").write_text("LINK := /no/such/linker -v\n")
    status, out, err = run_driver(["build", "hello.kod"], cwd=driver_root)
    assert status == 1
    assert out == ""
    assert err == (
        "kod: /no/such/linker could not be run "
        "(not found, killed, or its argument list too long)\n"
    )


@pytest.mark.parametrize(
    "local,wanted",
    [
        ("LINK = clang\n", "link.local.cfg:1:5: error: "),
        ("# machine\n\nCC := clang \n", "link.local.cfg:3:"),
        ("LINK := a\nLINK := b\n", "link.local.cfg:2:1: error: LINK is set twice"),
        ("CFLAG := -DX\n", "link.local.cfg:1:1: error: CFLAG is not set in link.cfg"),
        (
            "# machine\n\nSTAGE0 := build/s0\n",
            "link.local.cfg:3:1: error: STAGE0 is not set in link.cfg",
        ),
        ("LINK :=\n", "kod: link.cfg and link.local.cfg set no LINK\n"),
        ("STAGE0_KOD :=\n", "kod: link.cfg and link.local.cfg set no STAGE0_KOD\n"),
        ("RUNTIME_C :=\n", "kod: link.cfg and link.local.cfg set no RUNTIME_C\n"),
    ],
)
def test_the_driver_stops_at_a_link_configuration_it_cannot_read(
    driver_root: Path, local: str, wanted: str
):
    (driver_root / "link.local.cfg").write_text(local)
    status, out, err = run_driver(["build", "hello.kod"], cwd=driver_root)
    assert status == 1
    assert out == ""
    assert err.startswith(wanted), err
    # Nothing is compiled first.
    assert list((driver_root / "build" / "apps").iterdir()) == []


def test_the_driver_stops_at_a_link_cfg_that_is_empty_or_cannot_be_read(
    driver_root: Path,
):
    (driver_root / "link.cfg").write_text("")
    status, out, err = run_driver(["build", "hello.kod"], cwd=driver_root)
    assert (status, out, err) == (1, "", "kod: link.cfg is empty or cannot be read\n")


def test_the_driver_asks_for_make_when_an_always_linked_object_is_not_built(
    driver_root: Path,
):
    # A module added to STAGE0_KOD, before `make` has built its object.
    modules = [
        *cfg_values(driver_root / "link.cfg")["STAGE0_KOD"],
        "stdlib/zzprobe.kod",
    ]
    (driver_root / "link.local.cfg").write_text(f"STAGE0_KOD := {' '.join(modules)}\n")
    for command in ["build", "run", "test"]:
        status, out, err = run_driver([command, "hello.kod"], cwd=driver_root)
        assert (status, out, err) == (
            1,
            "",
            "kod: build/stage0/_zzprobe.o not found; run make\n",
        ), command
    assert list((driver_root / "build" / "apps").iterdir()) == []
    # `check` links nothing.
    assert run_driver(["check", "hello.kod"], cwd=driver_root) == (0, "", "")


def test_the_driver_stops_at_a_malformed_link_cfg_for_check_too(driver_root: Path):
    (driver_root / "link.cfg").write_text("LINK clang\n")
    status, out, err = run_driver(["check", "hello.kod"], cwd=driver_root)
    assert status == 1
    assert err.startswith("link.cfg:1:5: error: ")


def test_a_program_linked_by_clang_is_a_signed_arm64_executable(driver_root: Path):
    status, _, err = run_driver(["build", "hello.kod"], cwd=driver_root)
    assert status == 0, err
    exe = driver_root / "build" / "apps" / "hello" / "hello"
    verified = subprocess.run(
        ["codesign", "--verify", "--strict", str(exe)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr
    archs = subprocess.run(
        ["lipo", "-archs", str(exe)], capture_output=True, text=True, check=False
    )
    assert archs.stdout.split() == ["arm64"]
    # It starts from another directory with the bare environment of a script.
    with temp_dir("kod_cwd_") as elsewhere:
        status, out, _ = run_bounded(
            [exe], cwd=elsewhere, env={"PATH": "/usr/bin:/bin"}
        )
    assert (status, out) == (0, "linked\n")
    # And it does not ask for more of macOS than this one has.
    header = subprocess.run(
        ["otool", "-l", str(exe)], capture_output=True, text=True, check=False
    ).stdout
    minos = re.search(r"LC_BUILD_VERSION.*?minos (\S+)", header, re.S)
    assert minos, header
    here = platform.mac_ver()[0]
    if here and "MACOSX_DEPLOYMENT_TARGET" not in os.environ:

        def numbers(version: str) -> tuple[int, ...]:
            return tuple(int(part) for part in version.split("."))

        assert numbers(minos.group(1)) <= numbers(here)


def load_asm_diff():
    spec = importlib.util.spec_from_file_location(
        "asm_diff", ROOT / "tools" / "asm_diff.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_asm_diff_gives_the_base_copy_the_link_local_cfg_it_has(
    elsewhere: Path, capsys, monkeypatch
):
    asm_diff = load_asm_diff()
    root = elsewhere / "checkout"
    copy = elsewhere / "base"
    root.mkdir()
    copy.mkdir()
    monkeypatch.setattr(asm_diff, "ROOT", root)
    # None here: nothing is copied and nothing said.
    asm_diff.copy_link_local_cfg(copy)
    assert list(copy.iterdir()) == []
    assert capsys.readouterr().err == ""
    (root / "link.local.cfg").write_text("LINK := /usr/bin/clang\n")
    asm_diff.copy_link_local_cfg(copy)
    assert (copy / "link.local.cfg").read_text() == "LINK := /usr/bin/clang\n"
    assert "link.local.cfg" in capsys.readouterr().err


# --- Make and the link configuration -----------------------------------------

# Older than anything built.
LONG_AGO = 946684800


@pytest.fixture
def make_root() -> Iterator[Path]:
    """A directory Make takes for the repository: the Makefile, link.cfg, the
    sources and what is built, all by link, and a `build/` of its own, so that
    a link.local.cfg and the record of the configuration (build/.link-config)
    stay out of the real tree. Only `make -n`, `make -q` and the recipe that
    writes the record are run in it."""
    with temp_dir("kod_make_") as path:
        for name in [
            "Makefile",
            "link.cfg",
            "stdlib",
            "kodc.kod",
            "tools",
            "bootstrap",
        ]:
            (path / name).symlink_to(ROOT / name)
        (path / "build" / "apps").mkdir(parents=True)
        for built in ["stage0", "stage1"]:
            (path / "build" / built).symlink_to(ROOT / "build" / built)
        (path / "build" / "apps" / "kod").symlink_to(ROOT / "build" / "apps" / "kod")
        yield path


def written_long_ago(path: Path, text: str) -> None:
    """Write `path` and give it a time older than anything built, as a file
    restored from a backup has, so that only its content can tell."""
    path.write_text(text)
    os.utime(path, (LONG_AGO, LONG_AGO))


def record_link_config(root: Path) -> None:
    """Have Make record the configuration in force in `root`, as a build does,
    dated so that it is not newer than what was built."""
    made = make_in(root, "-s", "build/.link-config")
    assert made.returncode == 0, made.stderr
    os.utime(root / "build" / ".link-config", (LONG_AGO, LONG_AGO))


def test_make_takes_the_names_link_local_cfg_overrides(make_root: Path):
    (make_root / "link.local.cfg").write_text(
        "# this machine\n"
        "LINK := clang -target arm64-apple-darwin -Wl,-probe\n"
        "CFLAGS := -target arm64-apple-darwin -I stdlib -DPROBE=1\n"
    )
    recipes = make_recipes("stage1", "kod", root=make_root)
    for source in cfg_values(LINK_CFG)["RUNTIME_C"]:
        want = (
            "clang -target arm64-apple-darwin -I stdlib -DPROBE=1 -c -o "
            f"build/stage0/{Path(source).stem}.o {source}"
        )
        assert want in recipes
    for exe in ["build/stage1/sh_kodc", "build/apps/kod/kod"]:
        links = [line for line in recipes if f" -o {exe} " in line + " "]
        assert len(links) == 1, exe
        assert links[0].startswith("clang -target arm64-apple-darwin -Wl,-probe -o ")


@pytest.mark.parametrize(
    "local,wanted",
    [
        ("CFLAG := -DX\n", "link.local.cfg sets CFLAG, which link.cfg does not set"),
        ("# machine\nSTAGE0 := build/s0\n", "link.local.cfg sets STAGE0, which"),
        ("  SHELL := /bin/false\n", "link.local.cfg sets SHELL, which"),
        ("MAKEFLAGS := k\n", "link.local.cfg sets MAKEFLAGS, which"),
        ("CC := clang\nLNK:=clang\n", "link.local.cfg sets LNK, which"),
        ("LINK :=\n", "link.cfg and link.local.cfg set no LINK"),
        ("RUNTIME_C :=\n", "link.cfg and link.local.cfg set no RUNTIME_C"),
        ("STAGE0_KOD :=\n", "link.cfg and link.local.cfg set no STAGE0_KOD"),
        (
            "RUNTIME_C := stdlib/arena.c stdlib/notes.txt\n",
            "RUNTIME_C must name only .c files",
        ),
        (
            "STAGE0_KOD := stdlib/io.kod stdlib/io.c\n",
            "STAGE0_KOD must name only .kod files",
        ),
    ],
)
def test_make_stops_at_a_link_local_cfg_it_cannot_use(
    make_root: Path, local: str, wanted: str
):
    (make_root / "link.local.cfg").write_text(local)
    made = make_in(make_root, "-n", "stage0")
    assert made.returncode != 0
    assert wanted in made.stderr, made.stderr
    assert made.stdout == ""


@pytest.mark.parametrize("target", ["stage0", "stage1", "kod"])
def test_make_rebuilds_when_link_local_cfg_comes_or_goes(make_root: Path, target: str):
    # Nothing below is newer than what was built, but the first time: only the
    # record of the configuration can tell that the configuration changed.
    record_link_config(make_root)
    assert make_in(make_root, "-q", target).returncode == 0
    local = make_root / "link.local.cfg"
    written_long_ago(
        local, "CFLAGS := -target arm64-apple-darwin -I stdlib -DPROBE=1\n"
    )
    assert make_in(make_root, "-q", target).returncode == 1
    record_link_config(make_root)
    assert make_in(make_root, "-q", target).returncode == 0
    # The file as it was, but newer than what was built.
    os.utime(local)
    assert make_in(make_root, "-q", target).returncode == 1
    os.utime(local, (LONG_AGO, LONG_AGO))
    assert make_in(make_root, "-q", target).returncode == 0
    # Gone: what was built with it is not what the configuration says now.
    local.unlink()
    assert make_in(make_root, "-q", target).returncode == 1
    record_link_config(make_root)
    assert make_in(make_root, "-q", target).returncode == 0


@pytest.mark.parametrize("target", ["stage0", "stage1", "kod"])
def test_make_rebuilds_when_link_local_cfg_loses_a_name(make_root: Path, target: str):
    local = make_root / "link.local.cfg"
    both = (
        "CFLAGS := -target arm64-apple-darwin -I stdlib -DPROBE=1\n"
        "LINK := clang -target arm64-apple-darwin -Wl,-dead_strip -Wl,-probe\n"
    )
    written_long_ago(local, both)
    record_link_config(make_root)
    assert make_in(make_root, "-q", target).returncode == 0
    for kept in [both.split("\n")[0] + "\n", "# nothing now\n"]:
        written_long_ago(local, kept)
        assert make_in(make_root, "-q", target).returncode == 1, kept
        record_link_config(make_root)
        assert make_in(make_root, "-q", target).returncode == 0
