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

    subparsers.add_parser("_build-stage0")

    return parser


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


def main():
    """Main entry point."""
    args = _make_parser().parse_args()

    # Commands that bypass the usual parse-program flow.
    if args.command == "_build-stage0":
        stdlib_fs = FileSystem(find_stdlib_path())
        project_fs = FileSystem(Path.cwd())
        Builder(project_fs=project_fs, stdlib_fs=stdlib_fs).build_stage0()
        return 0

    if args.command == "test":
        print("kod test: not yet implemented", file=sys.stderr)
        return 1

    if args.command == "fmt":
        print("kod fmt: not yet implemented", file=sys.stderr)
        return 1

    if args.command == "_emit-runtime-main":
        bob, _, entry_module = _open_program(args.file)
        asm = bob.compose_runtime_main_asm(entry_module)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(asm)
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
