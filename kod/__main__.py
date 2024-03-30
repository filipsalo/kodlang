#!/usr/bin/env python
"""I am the Kod language."""

import argparse
import subprocess
import sys
from pathlib import Path

import kod.ast as ast
from kod.builder import Builder
from kod.exceptions import KodSyntaxError
from kod.filesys import FileSystem
from kod.interpreter import Interpreter


def find_stdlib_path() -> Path:
    """Find the path to the standard library."""
    stdlib_path = Path(sys.executable)
    while not (stdlib_path / "stdlib").is_dir():
        stdlib_path = stdlib_path.parent
    stdlib_path = stdlib_path / "stdlib"
    return stdlib_path


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser()
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

    args = parser.parse_args()

    stdlib_path = find_stdlib_path()
    stdlib_fs = FileSystem(stdlib_path)
    project_fs = FileSystem(Path.cwd())
    entry_path = Path(args.file).absolute()
    entry_module = project_fs.open(entry_path)

    try:
        bob = Builder(project_fs=project_fs, stdlib_fs=stdlib_fs)
        program = bob.parse_program(entry_module)
    except KodSyntaxError as err:
        print(err, file=sys.stderr)
        return 1

    match args.command:
        case "interpret":
            argv = [str(entry_module), *args.args]
            Interpreter(program).run(entry_module, argv)
        case "compile":
            module = program.get_module(entry_module.path)
            print(bob.compile_module(module))
            return 0
        case "build" | "run":
            executable = bob.build_executable(entry_module)
            if args.command == "run":
                result = subprocess.run([executable, *args.args], check=False)
                return result.returncode
        case "parse":
            module = program.get_module(entry_module.path).module
            ast.dump(module)


sys.exit(main())
