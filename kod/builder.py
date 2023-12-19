"""Building/compiling stuff"""

import io
import subprocess
import sys

from pathlib import Path
from kod.ast import ParsedImport

from kod.compiler import Compiler
from kod.lexer import Lexer
from kod.parser import Parser
from kod.program import BuildModule, Program


class FileWrapper:
    """A wrapper for a file."""
    def __init__(self, path, file=None):
        if path == "-":
            file = sys.stdin
            path = "main.kod"
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
        self.parse_builtins()

    def parse_builtins(self):
        """Parse the builtins module."""
        builtins = self.parse_module("builtins", self.resolve_name("builtins", self.root_path))
        self.program.add_module(builtins)

    def resolve_name(self, module_name, root_path) -> Path:
        """Resolve a name to a Path"""
        if not module_name.startswith("./"):
            root_path = self.stdlib_path
        path = (root_path / module_name).with_suffix(".kod")
        return FileWrapper(path)

    def parse_program(self, file_wrapper: FileWrapper):
        """Parse the program starting at `main_path`."""
        main = self.parse_module(file_wrapper.path.stem, file_wrapper)
        self.program.add_module(main)
        return self.program

    def parse_module(self, name, file_wrapper: FileWrapper):
        """Parse a module."""
        with file_wrapper.open(encoding="utf8") as f:
            source = f.read()
        tokens = Lexer(source, file_wrapper.path).lex()
        module = Parser(tokens, file_wrapper.path, name).parse()
        for import_ in self.get_imports(module):
            name = import_.module_name.value.decode("ascii")
            if name not in self.program.modules:
                import_path = self.resolve_name(name, file_wrapper.path.parent)
                import_module = self.parse_module(name, import_path)
                self.program.add_module(import_module)
        return BuildModule(module)

    def get_imports(self, module):
        """Get the imports of a module."""
        imports = []
        for statement in module.body:
            if isinstance(statement, ParsedImport):
                imports.append(statement)
        return imports

    def compile_module(self, name):
        """Compile a module."""
        build_module = self.program.modules[name]
        builtins = self.program.modules["builtins"]
        output = io.StringIO()
        Compiler(build_module.module, builtins.module, output).compile()
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
