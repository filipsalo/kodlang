#!/usr/bin/env python
"""I am the Kod language.

User-facing commands:
    kod build <file>     compile to an executable
    kod run <file>       build, then execute
    kod check <file>     compile through codegen; report errors but emit no
                         artifacts (exits non-zero if anything failed)
    kod test [path]      run the test framework (not yet implemented)
    kod fmt <file>       format source (not yet implemented)

Internal/debug commands (subject to change):
    kod _interpret <file>          run via the Python interpreter
    kod _emit-asm <file>           print the assembly for the entry module
    kod _dump-ast <file>           pretty-print the parsed AST
    kod _emit-runtime-main <file> <out.s>
    kod _build-stage0
"""

import argparse
import subprocess
import sys
from pathlib import Path

import kod.ast as ast
from kod.builder import Builder
from kod.exceptions import KodError
from kod.filesys import FileSystem
from kod.interpreter import Interpreter
from kod.paths import find_stdlib_path


def _make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kod")
    # Accepted-but-ignored: the standalone typechecker was retired once the
    # self-hosted codegen began reporting the same errors with spans, so the
    # flag exists only to keep existing build scripts working.
    parser.add_argument("--no-type-check", dest="type_check", action="store_false")

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    subparsers.required = True

    # Public commands.
    p = subparsers.add_parser("build", help="compile to an executable")
    p.add_argument("file", type=str)

    p = subparsers.add_parser("run", help="build, then execute")
    p.add_argument("file", type=str)
    p.add_argument("args", nargs="*")

    p = subparsers.add_parser(
        "check", help="parse + codegen; report errors but emit nothing"
    )
    p.add_argument("file", type=str)

    p = subparsers.add_parser("test", help="run the test framework (TODO)")
    p.add_argument("path", nargs="?", default=".")

    p = subparsers.add_parser("fmt", help="format source (TODO)")
    p.add_argument("file", type=str)

    # Internal/debug commands. Underscore prefix signals "not part of the
    # public surface; shape and existence may change."
    p = subparsers.add_parser("_interpret")
    p.add_argument("file", type=str)
    p.add_argument("args", nargs="*")

    p = subparsers.add_parser("_emit-asm")
    p.add_argument("file", type=str)

    p = subparsers.add_parser("_dump-ast")
    p.add_argument("file", type=str)

    p = subparsers.add_parser("_emit-runtime-main")
    p.add_argument("file", type=str)
    p.add_argument("out", type=str)

    p = subparsers.add_parser("_emit-test-runtime-main")
    p.add_argument("file", type=str)
    p.add_argument("out", type=str)

    subparsers.add_parser("_build-stage0")

    return parser


_DIR_TEST_RUNNER = ".kod_test_runner.kod"


def _run_dir_tests(directory: Path) -> int:
    """Walk `directory` for `*_test.kod`, build them all into a single
    executable via a temporary aggregator file at the project root,
    run it, return the exit code. Cleans up the aggregator on the way
    out (even if compilation fails)."""
    test_files = sorted(directory.rglob("*_test.kod"))
    if not test_files:
        print(f"kod test: no `*_test.kod` files under {directory}", file=sys.stderr)
        return 1

    cwd = Path.cwd()
    aggregator_path = cwd / _DIR_TEST_RUNNER
    # Each test file gets imported via a path relative to the project root
    # (`./stdlib/map_test`). The aggregator has no test blocks of its own;
    # the runtime_main walks the program for every module that does.
    imports = []
    for test_file in test_files:
        rel = test_file.resolve().relative_to(cwd).with_suffix("")
        imports.append(f'import "./{rel}"')
    aggregator_path.write_text("\n".join(imports) + "\n")
    try:
        bob, _, entry_module = _open_program(str(aggregator_path))
        executable = bob.build_test_executable(entry_module)
        result = subprocess.run([executable], check=False)
        return result.returncode
    finally:
        if aggregator_path.exists():
            aggregator_path.unlink()


def _open_program(file: str):
    """Resolve stdlib + project FS, parse program from `file`, return
    (builder, program, entry_module). Exits non-zero on parse errors."""
    stdlib_fs = FileSystem(find_stdlib_path())
    project_fs = FileSystem(Path.cwd())
    entry_module = project_fs.open(Path(file).absolute())
    bob = Builder(project_fs=project_fs, stdlib_fs=stdlib_fs)
    try:
        program = bob.parse_program(entry_module)
    except KodError as err:
        print(err, file=sys.stderr)
        sys.exit(1)
    return bob, program, entry_module


_NATIVE_DELEGATED = {"build", "run", "test", "check"}


def _maybe_delegate_to_native() -> int | None:
    """If `build/apps/kod/kod` exists and the user is invoking one of
    the subcommands the native binary implements, exec it directly with
    the same argv. The native path is ~5× faster on cold builds — most
    of the Python `kod` startup is import+import-cache overhead the
    native binary doesn't pay. The Python path stays valid as the
    fallback when the native binary is missing (fresh clone before
    `make kod`) or when the user has explicitly asked for a Python-only
    subcommand (anything not in `_NATIVE_DELEGATED`)."""
    if len(sys.argv) < 2 or sys.argv[1] not in _NATIVE_DELEGATED:
        return None
    native = Path.cwd() / "build" / "apps" / "kod" / "kod"
    if not native.exists():
        return None
    import os

    os.execv(str(native), [str(native), *sys.argv[1:]])


def main():
    """Main entry point."""
    rc = _maybe_delegate_to_native()
    if rc is not None:
        return rc

    args = _make_parser().parse_args()

    # Commands that bypass the usual parse-program flow.
    if args.command == "_build-stage0":
        stdlib_fs = FileSystem(find_stdlib_path())
        project_fs = FileSystem(Path.cwd())
        Builder(project_fs=project_fs, stdlib_fs=stdlib_fs).build_stage0()
        return 0

    if args.command == "test":
        # `kod test <file>` builds the file with a runtime_main that
        # calls every test-bearing module's __run_tests dispatcher
        # (entry file + transitive imports), then runs the resulting
        # binary and propagates its exit code.
        # `kod test <dir>` walks <dir> for `*_test.kod` files and runs
        # all of them in one binary via a temporary aggregator module.
        path = Path(args.path)
        if path.is_dir():
            return _run_dir_tests(path)
        bob, _, entry_module = _open_program(args.path)
        executable = bob.build_test_executable(entry_module)
        result = subprocess.run([executable], check=False)
        return result.returncode

    if args.command == "fmt":
        print("kod fmt: not yet implemented", file=sys.stderr)
        return 1

    if args.command == "_emit-runtime-main":
        # Delegate to sh_kodc when it's available and fresh — that's the
        # Kod-native composer. Fall back to the Python composer during
        # bootstrap (sh_kodc doesn't exist yet) or when the binary is
        # stale relative to its sources.
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        stdlib_fs = FileSystem(find_stdlib_path())
        project_fs = FileSystem(Path.cwd())
        bob = Builder(project_fs=project_fs, stdlib_fs=stdlib_fs)
        sh_kodc = bob.build_root / "stage1" / "sh_kodc"
        if sh_kodc.exists() and not bob._sh_kodc_stale(sh_kodc):
            result = subprocess.run(
                [str(sh_kodc), "_emit-runtime-main", args.file, str(out)],
                check=False,
            )
            return result.returncode
        # Python fallback.
        entry_module = project_fs.open(Path(args.file).absolute())
        try:
            bob.parse_program(entry_module)
        except KodError as err:
            print(err, file=sys.stderr)
            return 1
        out.write_text(bob.compose_runtime_main_asm(entry_module))
        return 0

    if args.command == "_emit-test-runtime-main":
        # Mirrors _emit-runtime-main: prefers sh_kodc when fresh,
        # falls back to the Python composer during bootstrap.
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        stdlib_fs = FileSystem(find_stdlib_path())
        project_fs = FileSystem(Path.cwd())
        bob = Builder(project_fs=project_fs, stdlib_fs=stdlib_fs)
        sh_kodc = bob.build_root / "stage1" / "sh_kodc"
        if sh_kodc.exists() and not bob._sh_kodc_stale(sh_kodc):
            result = subprocess.run(
                [str(sh_kodc), "_emit-test-runtime-main", args.file, str(out)],
                check=False,
            )
            return result.returncode
        entry_module = project_fs.open(Path(args.file).absolute())
        try:
            bob.parse_program(entry_module)
        except KodError as err:
            print(err, file=sys.stderr)
            return 1
        out.write_text(bob.compose_test_runtime_main_asm(entry_module))
        return 0

    bob, program, entry_module = _open_program(args.file)
    entry_key = entry_module.canonical_path.with_suffix("")

    match args.command:
        case "build":
            bob.build_executable(entry_module)
            return 0
        case "run":
            executable = bob.build_executable(entry_module)
            result = subprocess.run([executable, *args.args], check=False)
            return result.returncode
        case "check":
            # Run every module through codegen so the same error checks fire
            # as in `build`, but don't write artifacts or link. compile_module
            # already streams the underlying error to stderr; we just count.
            errors = 0
            for module in program:
                try:
                    bob.compile_module(module)
                except (KodError, RuntimeError):
                    errors += 1
            return 1 if errors else 0
        case "_interpret":
            argv = [str(entry_module), *args.args]
            Interpreter(program).run(entry_module, argv)
            return 0
        case "_emit-asm":
            module = program.get_module(entry_key)
            print(bob.compile_module(module))
            return 0
        case "_dump-ast":
            module = program.get_module(entry_module.path)
            ast.dump(module)
            return 0

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
