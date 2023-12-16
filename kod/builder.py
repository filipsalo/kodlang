"""Building/compiling stuff"""

import io
import subprocess
import sys

from pathlib import Path

from kod.compiler import Compiler
from kod.lexer import Lexer
from kod.parser import Parser
from kod.program import Module, Program


class FileWrapper:
    """A wrapper for a file."""
    def __init__(self, path, file=None):
        self.path = Path(path)
        self.file = file

    def open(self, *args, **kwargs):
        """Open the file."""
        if self.file:
            return self.file
        elif self.path == Path("-"):
            return sys.stdin
        return self.path.open(*args, **kwargs)


class Builder:
    """Build the project."""
    def __init__(self, *, root_path: Path, stdlib_path: Path):
        self.root_path = root_path
        self.stdlib_path = stdlib_path
        self.program = Program()

    def resolve_name(self, name) -> Path:
        """Resolve a name to a Path"""
        root = self.root_path if name.startswith("./") else self.stdlib_path
        path = (root / name).with_suffix(".kod")
        return FileWrapper(path)

    def parse_program(self, file_wrapper: FileWrapper):
        """Parse the program starting at `main_path`."""
        builtins = self.parse_module("builtins", self.resolve_name("builtins"))
        main = self.parse_module("__main", file_wrapper)
        self.program.add_module(builtins)
        self.program.add_module(main)
        return self.program

    def parse_module(self, name, file_wrapper: FileWrapper):
        """Parse a module."""
        with file_wrapper.open(encoding="utf8") as f:
            source = f.read()
        tokens = Lexer(source).lex()
        ast = Parser(tokens).parse()
        return Module(name, file_wrapper.path, ast)

    def compile_module(self, name):
        """Compile a module."""
        module = self.program.modules[name]
        builtins = self.program.modules["builtins"]
        output = io.StringIO()
        Compiler(module, builtins, output).compile()
        return output.getvalue()

    def build_module(self, name):
        """Build a module."""
        module = self.program.get_module(name)
        asm = self.compile_module(name)
        (Path("build") / module.asm_path).write_text(asm)
        object_file = Path("build") / module.object_path
        subprocess.run([
            "as",
            "-o", object_file,
            "-"
        ], input=asm.encode("ascii"), check=True)

    def build_executable(self, path):
        """Build an executable."""
        for module in self.program:
            self.build_module(module.name)
        executable = Path("build") / path
        subprocess.run([
            "ld",
            "-macosx_version_min", "13.1",
            "-lc",
            "-L", "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib",
            "-o", executable,
        ] + [Path("build") / module.object_path for module in self.program], check=True)
        return executable
