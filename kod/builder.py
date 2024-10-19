"""Building/compiling stuff"""

import io
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from kod import ast
from kod.compiler import Compiler
from kod.filesys import FileSystem, FileWrapper
from kod.lexer import Lexer
from kod.parser import Parser
from kod.program import Program


class Builder:
    """Build the project."""

    def __init__(self, *, project_fs: FileSystem, stdlib_fs: FileSystem):
        self.project_fs = project_fs
        self.stdlib_fs = stdlib_fs
        self.program = Program(self.parse_builtins())

    def parse_builtins(self) -> ast.Module:
        """Parse the builtins module."""
        return self.parse_module(self.resolve_import("builtins"))

    def resolve_import(
        self, module_name: str, relative_to: Optional[Path] = None
    ) -> FileWrapper:
        """Resolve a name to a Path"""
        path = Path(module_name).with_suffix(".kod")
        if module_name.startswith("./"):
            fs = self.project_fs
            if relative_to:
                path = relative_to.parent / path
        else:
            fs = self.stdlib_fs
        return fs.open(path)

    def parse_program(self, file: FileWrapper) -> Program:
        """Parse the program starting at `file`."""
        # print("in parse_program", entry_module_name)
        # file = self.resolve_import(entry_module_name)
        main = self.parse_module(file)
        self.program.add_module(main)
        return self.program

    def parse_module(self, file: FileWrapper) -> ast.Module:
        """Parse a module."""
        source = file.read()
        tokens = Lexer(source, Path(file.name)).lex()
        module = Parser(tokens, file).parse()
        for import_ in self.get_imports(module):
            name = import_.module_name
            import_file = self.resolve_import(name, relative_to=module.source_file.path)
            if import_file not in self.program.modules:
                import_module = self.parse_module(import_file)
                self.program.add_module(import_module)
        return module

    def get_imports(self, module) -> list[ast.Import]:
        """Get the imports of a module."""
        imports = []
        for statement in module.body:
            if isinstance(statement, ast.Import):
                imports.append(statement)
        return imports

    def compile_module(self, module: ast.Module) -> str:
        """Compile a module."""
        output = io.StringIO()
        Compiler(module, self.program, output).compile()
        return output.getvalue()

    def _build(self, module_name: str, asm: str) -> Path:
        """Build an object file."""
        asm_path = (self.project_fs.root_path / "build" / module_name).with_suffix(".s")
        obj_path = asm_path.with_suffix(".o")
        print(
            f"\033[2mWriting assembly to \033[22;1;36m{asm_path}\033[0m",
            file=sys.stderr,
        )
        asm_path.write_text(asm)
        cmd = [
            "as",
            "-target",
            "arm64-apple-darwin",
            "-o",
            obj_path.relative_to(self.project_fs.root_path),
            asm_path.relative_to(self.project_fs.root_path),
        ]
        print(f"=> \033[2m{" ".join(map(str, cmd))}\033[0m", file=sys.stderr)
        subprocess.run(
            cmd,
            check=True,
            cwd=self.project_fs.root_path,
        )
        return obj_path

    def build_module(self, module: ast.Module) -> Path:
        """Build a module."""
        print(
            f"\033[2mBuilding module \033[22;1;36m{module.source_file.path}\033[0m",
            file=sys.stderr,
        )
        asm = self.compile_module(module)
        return self._build(module.mangled_name, asm)

    def build_runtime_main(self, file: FileWrapper) -> Path:
        """Build the runtime main function."""
        asm = f"""
            .text
            .globl _main
            _main:
                b ${"$".join(file.canonical_path.parts)}$main
        """
        return self._build("runtime_main", asm)

    def build_executable(self, file: FileWrapper) -> Path:
        """Build an executable."""
        os.makedirs(self.project_fs.root_path / "build", exist_ok=True)
        executable = self.project_fs.root_path / "build" / file.path.stem
        print(
            f"\033[2mBuilding executable \033[22;1;36m{executable}\033[0m",
            file=sys.stderr,
        )
        object_files = []
        for module in self.program:
            object_files.append(
                self.build_module(module).relative_to(self.project_fs.root_path)
            )
        object_files.append(
            self.build_runtime_main(file).relative_to(self.project_fs.root_path)
        )
        cmd = [
            "ld",
            "-macos_version_min",
            "15.0",
            "-lc",
            "-L",
            "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib",
            "-o",
            executable.relative_to(self.project_fs.root_path),
            *object_files,
        ]
        print(f"=> \033[2m{" ".join(map(str, cmd))}\033[0m", file=sys.stderr)
        subprocess.run(
            cmd,
            check=True,
            cwd=self.project_fs.root_path,
        )
        return executable
