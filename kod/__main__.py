#!/usr/bin/env python
"""I am the Kod language."""

import argparse
import pprint
import sys

from kod.compiler import Compiler
from kod.interpreter import Interpreter
from kod.lexer import Lexer
from kod.parser import Parser
from kod.exceptions import KodSyntaxError


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("file", type=argparse.FileType("r"))

    parse_parser = subparsers.add_parser("parse")
    parse_parser.add_argument("file", type=argparse.FileType("r"))

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

    match args.command:
        case "run":
            Interpreter(prog).run()
        case "build":
            Compiler(prog).compile()
        case "parse":
            pprint.pprint(prog)


sys.exit(main())
