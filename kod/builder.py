"""Building/compiling stuff"""

import os
import subprocess
import sys
from pathlib import Path

from kod import ast
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

        def resolve_import(module_name):
            import_file = self.program.resolve_import(
                module_name, relative_to=file.path
            )
            key = import_file.canonical_path.with_suffix("")
            if key not in self.program.modules:
                dep = self.parse_module(import_file)
                self.program.add_module(dep)

        module = Parser(
            tokens, file, program=self.program, resolve_import=resolve_import
        ).parse()
        return module

    def compile_module(self, module: ast.Module) -> str:
        """Compile a module by running the self-hosted compiler (kodc.kod)
        inside the Python interpreter. Returns the emitted assembly."""
        root_path = self.program.root_fs.root_path
        kodc_path = root_path / "kodc.kod"
        if not kodc_path.exists():
            raise RuntimeError(
                f"kodc.kod not found at {kodc_path}; cannot self-host compile."
            )
        module_path = module.source_file.path
        try:
            rel_path = module_path.relative_to(root_path)
        except ValueError:
            rel_path = module_path
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "kod",
                "--no-type-check",
                "interpret",
                str(kodc_path),
                str(rel_path),
            ],
            capture_output=True,
            text=True,
            cwd=root_path,
            check=False,
        )
        if result.returncode != 0:
            sys.stderr.write(result.stderr)
            raise RuntimeError(
                f"kodc.kod failed for {rel_path} (exit {result.returncode})"
            )
        return result.stdout

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
        module = self.program.get_module(file.canonical_path.with_suffix(""))
        main_decl = next(
            s
            for s in module.body
            if isinstance(s, ast.FunctionDeclaration) and s.name == "main"
        )
        mangled = "$".join(file.canonical_path.with_suffix("").parts)
        if len(main_decl.params) == 0:
            asm = f"""
                .text
                .globl _main
                _main:
                    b ${mangled}$main
            """
        else:
            asm = f"""
                .text
                .globl _main
                _main:
                    stp x29, x30, [sp, #-64]!
                    mov x29, sp
                    stp x19, x20, [sp, #16]
                    stp x21, x22, [sp, #32]
                    str x23, [sp, #48]

                    mov x19, x0
                    mov x20, x1

                    lsl x0, x19, #3
                    bl _arena_alloc
                    mov x21, x0

                    mov x22, #0
                Lloop:
                    cmp x22, x19
                    b.ge Ldone
                    ldr x23, [x20, x22, lsl #3]
                    str x23, [x21, x22, lsl #3]
                    add x22, x22, #1
                    b Lloop
                Ldone:

                    mov x0, #24
                    bl _arena_alloc
                    str x21, [x0]
                    str x19, [x0, #8]
                    str x19, [x0, #16]

                    bl ${mangled}$main

                    ldr x23, [sp, #48]
                    ldp x21, x22, [sp, #32]
                    ldp x19, x20, [sp, #16]
                    ldp x29, x30, [sp], #64
                    ret
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
        macos_version = subprocess.check_output(
            ["sw_vers", "-productVersion"], text=True
        ).strip()
        cmd = [
            "ld",
            "-macos_version_min",
            macos_version,
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
