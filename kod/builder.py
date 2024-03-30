"""Building/compiling stuff"""

import io
import subprocess
import sys
from pathlib import Path
from typing import Optional

from kod import ast
from kod.compiler import Compiler
from kod.filesys import FileSystem, FileWrapper
from kod.lexer import Lexer
from kod.parser import Parser
from kod.program import BuildModule, Program
from kod.typechecker import TypeChecker


class Builder:
    """Build the project."""

    def __init__(self, *, project_fs: FileSystem, stdlib_fs: FileSystem):
        self.project_fs = project_fs
        self.stdlib_fs = stdlib_fs
        self.program = Program(self.parse_builtins())

    def parse_builtins(self) -> BuildModule:
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
        type_checker = TypeChecker(self.program)
        if not type_checker.check():
            for error in type_checker.errors:
                print(error, file=sys.stderr)
            sys.exit(1)

        return self.program

    def parse_module(self, file: FileWrapper) -> BuildModule:
        """Parse a module."""
        source = file.read()
        tokens = Lexer(source, Path(file.name)).lex()
        module = Parser(tokens, file).parse()
        for import_ in self.get_imports(module):
            name = import_.module_name
            import_file = self.resolve_import(name, relative_to=module.file.path)
            if import_file not in self.program.modules:
                import_module = self.parse_module(import_file)
                self.program.add_module(import_module)
        return BuildModule(module)

    def get_imports(self, module) -> list[ast.ParsedImport]:
        """Get the imports of a module."""
        imports = []
        for statement in module.body:
            if isinstance(statement, ast.ParsedImport):
                imports.append(statement)
        return imports

    def compile_module(self, module: BuildModule) -> str:
        """Compile a module."""
        output = io.StringIO()
        Compiler(module.module, self.program.builtins.module, output).compile()
        return output.getvalue()

    def build_module(self, module: BuildModule) -> None:
        """Build a module."""
        print(
            f"\033[1;30mBuilding module \033[1;36m{module.source_path}\033[0m",
            file=sys.stderr,
        )
        asm = self.compile_module(module)
        (Path("build") / module.asm_path).write_text(asm)
        object_file = Path("build") / module.object_path
        subprocess.run(
            ["as", "-target", "arm64-apple-darwin", "-o", object_file, "-"],
            input=asm.encode("ascii"),
            check=True,
        )

    def build_runtime_main(self, file: FileWrapper):
        """Build the runtime main function."""
        runtime_main_path = Path("build") / "runtime_main.o"
        asm = f"""
            .text
            .globl _main
            _main:
                b ${"$".join(file.canonical_module_path.parts)}$main
        """
        (Path("build") / "runtime_main.s").write_text(asm)
        subprocess.run(
            ["as", "-target", "arm64-apple-darwin", "-o", runtime_main_path, "-"],
            input=asm.encode("ascii"),
            check=True,
        )

    def build_executable(self, file: FileWrapper) -> Path:
        """Build an executable."""
        executable = Path("build") / file.path.stem
        print(
            f"\033[1;30mBuilding executable \033[1;36m{executable}\033[0m",
            file=sys.stderr,
        )
        for module in self.program:
            self.build_module(module)
        self.build_runtime_main(file)
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
