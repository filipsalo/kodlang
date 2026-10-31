"""Load a program for the interpreter: parse a module and the modules it
imports, plus the builtins and the primitive-type modules."""

import os
from pathlib import Path

from kod import ast
from kod import values as types
from kod.filesys import FileSystem, FileWrapper
from kod.lexer import Lexer
from kod.parser import Parser
from kod.program import Program


class LoadError(Exception):
    """A program that can't be loaded, for a reason with no source position."""


class Loader:
    """Parses programs. Holds the `Program` the parsed modules go into."""

    def __init__(self, *, project_fs: FileSystem, stdlib_fs: FileSystem):
        self.program = Program(project_fs, stdlib_fs)
        # The files being parsed, innermost last. A module joins the program
        # only once parsed, so an import cycle would never end.
        self._parsing: list[Path] = []
        self.program.builtins = self.parse_module(
            self.program.resolve_import("builtins")
        )
        # Primitive-type modules live in stdlib/primitives/. The functions are
        # attached as `methods` on the corresponding Python wrapper type so
        # the interpreter's `x.method()` dispatch path finds them in
        # `getattr(type(lhs), "methods", {})`.
        primitive_modules = (
            ("primitives/int64", types.Int64),
            ("primitives/str", types.String),
            ("primitives/bool", types.Bool),
        )
        for name, type_cls in primitive_modules:
            module = self.parse_module(self.program.resolve_import(name))
            self.program.add_module(module)
            if not hasattr(type_cls, "methods") or type_cls.methods is None:
                type_cls.methods = {}
            for decl in module.body:
                if isinstance(decl, ast.FunctionDeclaration):
                    decl.module = module
                    type_cls.methods[decl.name] = decl

    def parse_program(self, file: FileWrapper) -> Program:
        """Parse the program starting at `file`."""
        main = self.parse_module(file)
        self.program.add_module(main)
        return self.program

    def parse_module(self, file: FileWrapper) -> ast.Module:
        """Parse a module, and the modules it imports that aren't loaded yet."""
        location = Path(os.path.normpath(file.path))
        if location in self._parsing:
            raise LoadError(
                f"{file.canonical_path}: error: import cycle "
                "(the Python loader can't load one)"
            )
        source = file.read()
        tokens = Lexer(source, Path(file.name)).lex()

        def resolve_import(module_name):
            import_file = self.program.resolve_import(
                module_name, relative_to=file.path
            )
            key = import_file.canonical_path.with_suffix("")
            if key not in self.program.modules:
                dep = self.parse_module(import_file)
                self.program.add_module(dep)

        self._parsing.append(location)
        try:
            return Parser(
                tokens, file, program=self.program, resolve_import=resolve_import
            ).parse()
        finally:
            self._parsing.pop()
