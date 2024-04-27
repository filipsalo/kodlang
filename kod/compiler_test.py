import subprocess
import textwrap
from pathlib import Path

from kod.builder import Builder
from kod.filesys import FakeFileSystem, FileSystem
from kod.paths import find_stdlib_path


def compile_src(src: str):
    """Compile a module."""
    dedent_src = textwrap.dedent(src)
    project_fs = FakeFileSystem({"main.kod": dedent_src})
    builder = Builder(
        project_fs=project_fs,
        stdlib_fs=FileSystem(find_stdlib_path()),
    )
    entry_file = project_fs.open(Path("main.kod"))
    builder.parse_program(entry_file)
    executable = builder.build_executable(entry_file)
    result = subprocess.run(executable, stdout=subprocess.PIPE, check=True)
    return result.stdout.decode()


def test_variable_declarations():
    src = """\
        func main() -> int64 {
            let x: int64 = 5
            print_int(x)
            return 0
        }
    """
    expected = "5\n"
    assert compile_src(src) == expected
