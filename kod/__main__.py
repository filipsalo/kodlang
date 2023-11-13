#!/usr/bin/env python
"""I am the Kod language."""

import sys
import argparse

from kod.interpreter import Interpreter
from kod.lexer import Lexer
from kod.parser import Parser
from kod.exceptions import KodSyntaxError


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("-r", "--run", action="store_true")
    parser.add_argument("file", type=argparse.FileType("r"))
    args = parser.parse_args()

    src = args.file.read()
    try:
        tokens = Lexer(src).lex()
    except KodSyntaxError as e:
        print(e)
        return 1
    prog = Parser(tokens).parse()

    if args.run:
        Interpreter(prog).run()
        return 0

    print("usage: kod --run FILE")
    return 1


sys.exit(main())
