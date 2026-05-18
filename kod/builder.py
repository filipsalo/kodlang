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
        # Primitive-type modules live in stdlib/primitives/. They're parsed
        # and added to the program so the build pipeline produces a .o for
        # each (linker resolves the $primitives$<kind>$<method> labels that
        # the codegen emits for primitive method calls). The functions are
        # also attached as `methods` on the corresponding Python wrapper
        # type so the interpreter's `x.method()` dispatch path finds them
        # in `getattr(type(lhs), "methods", {})`.
        from kod import values as types

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
        """Compile a module with the self-hosted compiler. Prefers the
        pre-built native binary at build/sh_kodc (fast); falls back to running
        kodc.kod through the Python interpreter (slow, used to bootstrap)."""
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

        sh_kodc = root_path / "build" / "sh_kodc"
        if sh_kodc.exists() and not self._sh_kodc_stale(sh_kodc):
            cmd = [str(sh_kodc), str(rel_path)]
        else:
            cmd = [
                sys.executable,
                "-m",
                "kod",
                "--no-type-check",
                "interpret",
                str(kodc_path),
                str(rel_path),
            ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=root_path, check=False
        )
        if result.returncode != 0:
            sys.stderr.write(result.stderr)
            raise RuntimeError(
                f"compile_module failed for {rel_path} (exit {result.returncode})"
            )
        return result.stdout

    def _sh_kodc_stale(self, sh_kodc: Path) -> bool:
        """True if sh_kodc is older than any compiler source it was built from."""
        try:
            sh_mtime = sh_kodc.stat().st_mtime
        except OSError:
            return True
        root_path = self.program.root_fs.root_path
        stdlib_path = self.program.stdlib_fs.root_path
        sources = [
            root_path / "kodc.kod",
            stdlib_path / "kod" / "codegen.kod",
            stdlib_path / "kod" / "parsing.kod",
            stdlib_path / "kod" / "lexing.kod",
            stdlib_path / "kod" / "ast.kod",
            stdlib_path / "builtins.kod",
        ]
        for src in sources:
            try:
                if src.stat().st_mtime > sh_mtime:
                    return True
            except OSError:
                continue
        return False

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
        # If main returns `T or Error`, the call result is a Result cell ptr:
        # {discriminant, payload}. On Ok, we unwrap the payload as the exit
        # code; on Err, we call _kod_panic (prints the message and exits 1).
        from kod import values as types

        returns_result = isinstance(main_decl.return_type, type) and issubclass(
            main_decl.return_type, types.ResultType
        )
        if returns_result:
            unwrap = """
                    ldr x9, [x0, #0]
                    cbz x9, Lmain_ok
                    ldr x0, [x0, #8]
                    ldr x1, [x0, #8]
                    ldr x9, [x1, #0]
                    ldr x0, [x0, #0]
                    blr x9
                    bl _kod_panic
                Lmain_ok:
                    ldr x0, [x0, #8]
            """
        else:
            unwrap = ""
        if len(main_decl.params) == 0:
            if returns_result:
                asm = f"""
                    .text
                    .globl _main
                    _main:
                        stp x29, x30, [sp, #-16]!
                        mov x29, sp
                        bl ${mangled}$main
                        {unwrap}
                        ldp x29, x30, [sp], #16
                        ret
                """
            else:
                asm = f"""
                    .text
                    .globl _main
                    _main:
                        b ${mangled}$main
                """
            return self._build("runtime_main", asm)
        # Param-form (main accepts argv).
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
                {unwrap}

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
