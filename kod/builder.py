"""Building/compiling stuff"""

import io
import os
import subprocess
import sys
from pathlib import Path

from kod import ast
from kod.compiler import Compiler
from kod.filesys import FileSystem, FileWrapper
from kod.lexer import Lexer
from kod.parser import Parser
from kod.program import Program


class Builder:
    """Build the project."""

    def __init__(self, *, project_fs: FileSystem, stdlib_fs: FileSystem):
        self.program = Program(project_fs, stdlib_fs)
        self.program.builtins = self.parse_builtins()

    def parse_builtins(self) -> ast.Module:
        """Parse the builtins module."""
        return self.parse_module(self.program.resolve_import("builtins"))

    def parse_program(self, file: FileWrapper) -> Program:
        """Parse the program starting at `file`."""
        main = self.parse_module(file)
        self.program.add_module(main)
        return self.program

    def parse_module(self, file: FileWrapper) -> ast.Module:
        """Parse a module."""
        source = file.read()
        tokens = Lexer(source, Path(file.name)).lex()
        module = Parser(tokens, file).parse()
        for import_ in module.get_imports():
            name = import_.module_name
            import_file = self.program.resolve_import(
                name, relative_to=module.source_file.path
            )
            if import_file not in self.program.modules:
                import_module = self.parse_module(import_file)
                self.program.add_module(import_module)
        return module

    def compile_module(self, module: ast.Module) -> str:
        """Compile a module."""
        output = io.StringIO()
        Compiler(module, self.program, output).compile()
        return output.getvalue()

    def _build_c(self, c_path: Path) -> Path:
        """Compile a C source file to an object file."""
        root_path = self.program.root_fs.root_path
        obj_path = (root_path / "build" / c_path.stem).with_suffix(".o")
        cmd = [
            "clang",
            "-c",
            "-o",
            str(obj_path.relative_to(root_path)),
            str(c_path),
        ]
        print(f"=> \033[2m{' '.join(map(str, cmd))}\033[0m", file=sys.stderr)
        subprocess.run(cmd, check=True, cwd=root_path)
        return obj_path

    def _build(self, module_name: str, asm: str) -> Path:
        """Build an object file."""
        root_path = self.program.root_fs.root_path
        asm_path = (root_path / "build" / module_name).with_suffix(".s")
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
            obj_path.relative_to(root_path),
            asm_path.relative_to(root_path),
        ]
        print(f"=> \033[2m{" ".join(map(str, cmd))}\033[0m", file=sys.stderr)
        subprocess.run(cmd, check=True, cwd=root_path)
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
                b ${"$".join(file.canonical_path.with_suffix("").parts)}$main
        """
        return self._build("runtime_main", asm)

    def build_executable(self, file: FileWrapper) -> Path:
        """Build an executable."""
        root_path = self.program.root_fs.root_path
        build_dir = root_path / "build"
        os.makedirs(build_dir, exist_ok=True)
        executable = build_dir / file.path.stem
        print(
            f"\033[2mBuilding executable \033[22;1;36m{executable}\033[0m",
            file=sys.stderr,
        )
        object_files = []
        for module in self.program:
            object_files.append(self.build_module(module).relative_to(root_path))
        object_files.append(self.build_runtime_main(file).relative_to(root_path))
        stdlib_root = self.program.stdlib_fs.root_path
        object_files.append(
            self._build_c(stdlib_root / "arena.c").relative_to(root_path)
        )
        object_files.append(
            self._build_c(stdlib_root / "runtime.c").relative_to(root_path)
        )
        cmd = [
            "ld",
            "-macos_version_min",
            "15.0",
            "-lc",
            "-L",
            "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib",
            "-o",
            executable.relative_to(root_path),
            *object_files,
        ]
        print(f"=> \033[2m{" ".join(map(str, cmd))}\033[0m", file=sys.stderr)
        subprocess.run(cmd, check=True, cwd=root_path)
        return executable
