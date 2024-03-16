"""Building/compiling stuff"""

import io
import subprocess
import sys
from pathlib import Path
from typing import TextIO

from kod import ast
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

    def open(self, *args, **kwargs) -> TextIO:
        """Open the file."""
        if self.file:
            return self.file
        elif self.path == Path("-"):
            return sys.stdin
        encoding = kwargs.pop("encoding", "utf8")
        return self.path.open(*args, encoding=encoding, **kwargs)


class Builder:
    """Build the project."""

    def __init__(self, *, root_path: Path, stdlib_path: Path):
        self.root_path = root_path
        self.stdlib_path = stdlib_path
        self.program = Program()
        self.parse_builtins()

    def parse_builtins(self) -> None:
        """Parse the builtins module."""
        builtins = self.parse_module(
            "builtins", self.resolve_name("builtins", self.root_path)
        )
        self.program.add_module(builtins)

    def resolve_name(self, module_name, root_path) -> FileWrapper:
        """Resolve a name to a Path"""
        if not module_name.startswith("./"):
            root_path = self.stdlib_path
        path = (root_path / module_name).with_suffix(".kod")
        return FileWrapper(path)

    def parse_program(self, file_wrapper: str) -> Program:
        """Parse the program starting at `main_path`."""
        main = self.parse_module(file_wrapper.path.stem, file_wrapper)
        self.program.add_module(main)
        return self.program

    def parse_module(self, name: str, file_wrapper: FileWrapper) -> BuildModule:
        """Parse a module."""
        with file_wrapper.open(encoding="utf8") as f:
            source = f.read()
        tokens = Lexer(source, file_wrapper.path).lex()
        module = Parser(tokens, file_wrapper.path, name).parse()
        for import_ in self.get_imports(module):
            name = import_.module_name
            if name not in self.program.modules:
                import_path = self.resolve_name(name, file_wrapper.path.parent)
                import_module = self.parse_module(name, import_path)
                self.program.add_module(import_module)
        return BuildModule(module)

    def get_imports(self, module) -> list[ast.ParsedImport]:
        """Get the imports of a module."""
        imports = []
        for statement in module.body:
            if isinstance(statement, ast.ParsedImport):
                imports.append(statement)
        return imports

    def compile_module(self, name: str) -> str:
        """Compile a module."""
        build_module = self.program.modules[name]
        builtins = self.program.modules["builtins"]
        output = io.StringIO()
        Compiler(build_module.module, builtins.module, output).compile()
        return output.getvalue()

    def build_module(self, name: str) -> None:
        """Build a module."""
        print(f"\033[1;30mBuilding module \033[1;36m{name}\033[0m", file=sys.stderr)
        module = self.program.get_module(name)
        asm = self.compile_module(name)
        (Path("build") / module.asm_path).write_text(asm)
        object_file = Path("build") / module.object_path
        subprocess.run(
            ["as", "-target", "arm64-apple-darwin", "-o", object_file, "-"],
            input=asm.encode("ascii"),
            check=True,
        )

    def build_runtime_main(self, main_module):
        """Build the runtime main function."""
        runtime_main_path = Path("build") / "runtime_main.o"
        asm = f"""
            .text
            .globl _main
            _main:
                b ${str(main_module).replace("/", "$")}$main
        """
        (Path("build") / "runtime_main.s").write_text(asm)
        subprocess.run(
            ["as", "-target", "arm64-apple-darwin", "-o", runtime_main_path, "-"],
            input=asm.encode("ascii"),
            check=True,
        )

    def build_executable(self, path: Path) -> Path:
        """Build an executable."""
        print(f"\033[1;30mBuilding executable \033[1;36m{path}\033[0m", file=sys.stderr)
        for module in self.program:
            self.build_module(module.name)
        self.build_runtime_main(path)
        executable = Path("build") / path.stem
        runtime_main_path = Path("build") / "runtime_main.o"
        cmd = (
            [
                "ld",
                "-macos_version_min",
                "14",
                "-lc",
                "-L",
                "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib",
                "-o",
                str(executable),
            ]
            + [str(Path("build") / module.object_path) for module in self.program]
            + [str(runtime_main_path)]
        )
        print(f"\033[1;30mRunning\033[0m {" ".join(cmd)}", file=sys.stderr)
        subprocess.run(
            cmd,
            check=True,
        )
        return executable
