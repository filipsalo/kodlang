#!/usr/bin/env python
"""I am the Kod language."""

import argparse
from pathlib import Path
import subprocess
import sys

from kod.builder import Builder, FileWrapper
from kod.interpreter import Interpreter
from kod.typechecker import TypeChecker
from kod.exceptions import KodSyntaxError
import kod.ast as ast


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    interpret_parser = subparsers.add_parser("interpret")
    interpret_parser.add_argument("file", type=FileWrapper)
    interpret_parser.add_argument('args', nargs='*')

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("file", type=FileWrapper)

    parse_parser = subparsers.add_parser("parse")
    parse_parser.add_argument("file", type=FileWrapper)

    compile_parser = subparsers.add_parser("compile")
    compile_parser.add_argument("file", type=FileWrapper)

    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("file", type=FileWrapper)

    args = parser.parse_args()

    try:
        bob = Builder(root_path=Path.cwd(), stdlib_path=Path("stdlib"))
        program = bob.parse_program(args.file)
    except KodSyntaxError as err:
        print(err, file=sys.stderr)
        return 1

    entry_module = args.file.path.stem

    match args.command:
        case "interpret":
            argv = [str(args.file.path)] + args.args
            Interpreter(program).run(entry_module, argv)
        case "compile":
            print(bob.compile_module(entry_module))
            return 0
        case "build" | "run":
            executable = bob.build_executable(Path("./main"))
            if args.command == "run":
                result = subprocess.run(executable, check=False)
                return result.returncode
        case "parse":
            ast.dump(program.get_module(entry_module).module)


sys.exit(main())
