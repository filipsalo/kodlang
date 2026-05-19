#!/usr/bin/env python
"""I am the Kod language."""

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


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser()
    # Accepted-but-ignored: the standalone typechecker was retired once the
    # self-hosted codegen began reporting the same errors with spans, so the
    # flag exists only to keep existing build scripts working.
    parser.add_argument("--no-type-check", dest="type_check", action="store_false")

    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    interpret_parser = subparsers.add_parser("interpret")
    interpret_parser.add_argument("file", type=str)
    interpret_parser.add_argument("args", nargs="*")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("file", type=str)
    run_parser.add_argument("args", nargs="*")

    parse_parser = subparsers.add_parser("parse")
    parse_parser.add_argument("file", type=str)

    compile_parser = subparsers.add_parser("compile")
    compile_parser.add_argument("file", type=str)

    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("file", type=str)

    # Internal: emit the runtime _main shim for an entry file. Used by the
    # Makefile to wire up stage1 (sh_kodc) without duplicating the shim asm.
    emit_rm_parser = subparsers.add_parser("_emit-runtime-main")
    emit_rm_parser.add_argument("file", type=str)
    emit_rm_parser.add_argument("out", type=str)

    # Internal: build the shared stage0 objects (arena, runtime, builtins,
    # primitives) into build/stage0/. Used by the Makefile to seed the
    # link step that produces sh_kodc.
    subparsers.add_parser("_build-stage0")

    args = parser.parse_args()

    if args.command == "_build-stage0":
        stdlib_path = find_stdlib_path()
        stdlib_fs = FileSystem(stdlib_path)
        project_fs = FileSystem(Path.cwd())
        bob = Builder(project_fs=project_fs, stdlib_fs=stdlib_fs)
        bob.build_stage0()
        return 0

    if args.command == "_emit-runtime-main":
        stdlib_path = find_stdlib_path()
        stdlib_fs = FileSystem(stdlib_path)
        project_fs = FileSystem(Path.cwd())
        entry_path = Path(args.file).absolute()
        entry_module = project_fs.open(entry_path)
        bob = Builder(project_fs=project_fs, stdlib_fs=stdlib_fs)
        try:
            bob.parse_program(entry_module)
        except KodError as err:
            print(err, file=sys.stderr)
            return 1
        asm = bob.compose_runtime_main_asm(entry_module)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(asm)
        return 0

    stdlib_path = find_stdlib_path()
    stdlib_fs = FileSystem(stdlib_path)
    project_fs = FileSystem(Path.cwd())
    entry_path = Path(args.file).absolute()
    entry_module = project_fs.open(entry_path)

    bob = Builder(project_fs=project_fs, stdlib_fs=stdlib_fs)
    try:
        program = bob.parse_program(entry_module)
    except KodError as err:
        print(err, file=sys.stderr)
        return 1

    entry_key = entry_module.canonical_path.with_suffix("")
    match args.command:
        case "interpret":
            argv = [str(entry_module), *args.args]
            Interpreter(program).run(entry_module, argv)
        case "compile":
            module = program.get_module(entry_key)
            print(bob.compile_module(module))
            return 0
        case "build" | "run":
            executable = bob.build_executable(entry_module)
            if args.command == "run":
                result = subprocess.run([executable, *args.args], check=False)
                return result.returncode
        case "parse":
            module = program.get_module(entry_module.path)
            ast.dump(module)


sys.exit(main())
