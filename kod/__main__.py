#!/usr/bin/env python
"""I am the Kod language."""

import argparse
import io
from pathlib import Path
import subprocess
import sys

from kod.compiler import Compiler
from kod.interpreter import Interpreter
from kod.lexer import Lexer
from kod.parser import Parser
from kod.typechecker import TypeChecker
from kod.exceptions import KodSyntaxError
import kod.ast as ast


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    run_parser = subparsers.add_parser("interpret")
    run_parser.add_argument("file", type=argparse.FileType("r"))

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("file", type=argparse.FileType("r"))

    parse_parser = subparsers.add_parser("parse")
    parse_parser.add_argument("file", type=argparse.FileType("r"))

    build_parser = subparsers.add_parser("compile")
    build_parser.add_argument("file", type=argparse.FileType("r"))

    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("file", type=argparse.FileType("r"))

    args = parser.parse_args()

    src = args.file.read()
    try:
        tokens = Lexer(src).lex()
    except KodSyntaxError as e:
        print(e)
        return 1
    prog = Parser(tokens).parse()
    TypeChecker().check_module(prog)

    match args.command:
        case "interpret":
            Interpreter(prog).run()
        case "compile":
            asm = io.StringIO()
            Compiler(prog, asm).compile()
            if args.output_assembly:
                print(asm.getvalue())
                return 0
        case "build" | "run":
            asm = io.StringIO()
            Compiler(prog, asm).compile()
            object_file = (Path("build") / Path(args.file.name).stem).with_suffix(".o")
            executable = object_file.with_suffix("")
            subprocess.run([
                "as",
                "-o", object_file,
                "-"
            ], input=asm.getvalue().encode("ascii"), check=True)
            subprocess.run([
                "ld",
                "-macosx_version_min", "13.1",
                "-lc",
                "-L", "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib",
                "-o", executable,
                object_file
            ], check=True)
            if args.command == "run":
                result = subprocess.run(executable, check=False)
                return result.returncode
        case "parse":
            ast.dump(prog)


sys.exit(main())
