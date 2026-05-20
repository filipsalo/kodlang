"""Building/compiling stuff"""

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

    def __init__(
        self,
        *,
        project_fs: FileSystem,
        stdlib_fs: FileSystem,
        build_root: Path | None = None,
    ):
        self.program = Program(project_fs, stdlib_fs)
        # Where outputs go. Layout:
        #   {build_root}/stage0/  shared stdlib objects (arena, runtime, builtins,
        #                         primitives) — produced once, reused by stage1
        #                         and every app build
        #   {build_root}/stage1/  the self-hosted compiler (sh_kodc) + its parts
        #   {build_root}/apps/<stem>/  per-app outputs
        self.build_root = build_root or (project_fs.root_path / "build")
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
        # Eagerly-loaded stdlib modules (their .o becomes part of stage0
        # so sh_kodc links them, even though user code still needs an
        # explicit `import "io"` / `import "process"` to use them).
        for name in ("io", "process"):
            module = self.parse_module(self.program.resolve_import(name))
            self.program.add_module(module)

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
        pre-built native binary at build/stage1/sh_kodc (fast); falls back to running
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

        sh_kodc = self.build_root / "stage1" / "sh_kodc"
        if sh_kodc.exists() and not self._sh_kodc_stale(sh_kodc):
            cmd = [str(sh_kodc), str(rel_path)]
        else:
            cmd = [
                sys.executable,
                "-m",
                "kod",
                "--no-type-check",
                "_interpret",
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

    def _build_c(self, c_path: Path, out_dir: Path) -> Path:
        """Compile a C source file to an object file."""
        root_path = self.program.root_fs.root_path
        out_dir.mkdir(parents=True, exist_ok=True)
        obj_path = (out_dir / c_path.stem).with_suffix(".o")
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

    def _build(self, module_name: str, asm: str, out_dir: Path) -> Path:
        """Build an object file."""
        root_path = self.program.root_fs.root_path
        out_dir.mkdir(parents=True, exist_ok=True)
        asm_path = (out_dir / module_name).with_suffix(".s")
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

    def build_module(self, module: ast.Module, out_dir: Path) -> Path:
        """Build a module to a .o file. When sh_kodc is available, lets it
        drive both codegen and `as` in one subprocess (`_compile`).
        Falls back to the two-step Python-orchestrated path during
        bootstrap or when sh_kodc is stale."""
        print(
            f"\033[2mBuilding module \033[22;1;36m{module.source_file.path}\033[0m",
            file=sys.stderr,
        )
        root_path = self.program.root_fs.root_path
        out_dir.mkdir(parents=True, exist_ok=True)
        obj_path = (out_dir / module.mangled_name).with_suffix(".o")
        sh_kodc = self.build_root / "stage1" / "sh_kodc"
        if sh_kodc.exists() and not self._sh_kodc_stale(sh_kodc):
            try:
                rel_src = module.source_file.path.relative_to(root_path)
            except ValueError:
                rel_src = module.source_file.path
            cmd = [
                str(sh_kodc),
                "_compile",
                str(rel_src),
                str(obj_path.relative_to(root_path)),
            ]
            print(f"=> \033[2m{' '.join(cmd)}\033[0m", file=sys.stderr)
            result = subprocess.run(cmd, check=False, cwd=root_path)
            if result.returncode == 0:
                return obj_path
        # Fallback: Python interpreter drives kodc.kod → captured .s → `as`.
        asm = self.compile_module(module)
        return self._build(module.mangled_name, asm, out_dir=out_dir)

    def _mangled_module_prefix(self, file: FileWrapper) -> str:
        """Mirror of kodc.kod:path_to_prefix — turn a canonical path into
        the symbol prefix codegen uses. Strips leading `stdlib/` so
        modules under stdlib match `import "kod/foo"` style resolution."""
        parts = file.canonical_path.with_suffix("").parts
        if parts and parts[0] == "stdlib":
            parts = parts[1:]
        return "$".join(parts)

    def _modules_with_tests(self) -> list[ast.Module]:
        """Modules in the program (entry + transitive imports) that
        declare at least one `test "..." { ... }` block."""
        result = []
        for module in self.program:
            if any(isinstance(d, ast.TestDeclaration) for d in module.body):
                result.append(module)
        return result

    def compose_runtime_main_asm(self, file: FileWrapper) -> str:
        """Compose the runtime _main shim for the given entry file. The
        shape depends on whether main takes argv and whether it returns
        `T or Error`."""
        module = self.program.get_module(file.canonical_path.with_suffix(""))
        main_decl = next(
            s
            for s in module.body
            if isinstance(s, ast.FunctionDeclaration) and s.name == "main"
        )
        mangled = self._mangled_module_prefix(file)
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
                return f"""
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
            return f"""
                .text
                .globl _main
                _main:
                    b ${mangled}$main
            """
        # Param-form (main accepts argv).
        return f"""
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

    def build_runtime_main(self, file: FileWrapper, out_dir: Path) -> Path:
        """Build the runtime _main object file into `out_dir`. Delegates to
        sh_kodc when available; falls back to the Python composer during
        bootstrap (when sh_kodc doesn't yet exist or is stale)."""
        return self._build_runtime_main(
            file,
            out_dir,
            "_emit-runtime-main",
            self.compose_runtime_main_asm,
        )

    def compose_test_runtime_main_asm(self, file: FileWrapper) -> str:
        """Compose a runtime _main that calls every test-bearing module's
        `__run_tests` dispatcher (entry file + transitive imports), then
        prints the aggregate summary and exits with the failure count
        (capped at 1). Each per-module dispatcher just runs its own
        tests; the summary is hoisted here so the totals roll up."""
        test_modules = self._modules_with_tests()
        calls = "\n                ".join(
            f"bl ${self._mangled_module_prefix(m.source_file)}$__run_tests"
            for m in test_modules
        )
        return f"""
            .text
            .globl _main
            _main:
                stp x29, x30, [sp, #-16]!
                mov x29, sp
                {calls}
                bl _kod_test_summary
                ldp x29, x30, [sp], #16
                ret
        """

    def build_test_runtime_main(self, file: FileWrapper, out_dir: Path) -> Path:
        return self._build_runtime_main(
            file,
            out_dir,
            "_emit-test-runtime-main",
            self.compose_test_runtime_main_asm,
        )

    def _build_runtime_main(
        self,
        file: FileWrapper,
        out_dir: Path,
        subcommand: str,
        python_compose,
    ) -> Path:
        """Write a runtime_main.s via sh_kodc when fresh, else via the
        Python composer (bootstrap fallback). Assemble and return the
        resulting .o path."""
        root_path = self.program.root_fs.root_path
        out_dir.mkdir(parents=True, exist_ok=True)
        asm_path = (out_dir / "runtime_main").with_suffix(".s")
        sh_kodc = self.build_root / "stage1" / "sh_kodc"
        used_sh_kodc = False
        if sh_kodc.exists() and not self._sh_kodc_stale(sh_kodc):
            try:
                rel_file = file.path.relative_to(root_path)
            except ValueError:
                rel_file = file.path
            result = subprocess.run(
                [str(sh_kodc), subcommand, str(rel_file), str(asm_path)],
                check=False,
                cwd=root_path,
            )
            used_sh_kodc = result.returncode == 0
        if not used_sh_kodc:
            asm_path.write_text(python_compose(file))
        return self._assemble(asm_path)

    def _assemble(self, asm_path: Path) -> Path:
        """Run `as` on a .s file and return the sibling .o path."""
        root_path = self.program.root_fs.root_path
        obj_path = asm_path.with_suffix(".o")
        cmd = [
            "as",
            "-target",
            "arm64-apple-darwin",
            "-o",
            obj_path.relative_to(root_path),
            asm_path.relative_to(root_path),
        ]
        print(f"=> \033[2m{' '.join(map(str, cmd))}\033[0m", file=sys.stderr)
        subprocess.run(cmd, check=True, cwd=root_path)
        return obj_path

    def _is_stdlib_module(self, module: ast.Module) -> bool:
        stdlib_path = self.program.stdlib_fs.root_path
        try:
            module.source_file.path.resolve().relative_to(stdlib_path.resolve())
            return True
        except ValueError:
            return False

    def build_stage0(self) -> list[Path]:
        """Build the shared stage0 objects: arena.o, runtime.o, plus every
        stdlib module currently loaded into the program (builtins +
        primitives). Returns the list of object file paths."""
        stage0_dir = self.build_root / "stage0"
        stdlib_root = self.program.stdlib_fs.root_path
        outputs = []
        for module in self.program:
            if self._is_stdlib_module(module):
                outputs.append(self.build_module(module, out_dir=stage0_dir))
        outputs.append(self._build_c(stdlib_root / "arena.c", out_dir=stage0_dir))
        outputs.append(self._build_c(stdlib_root / "runtime.c", out_dir=stage0_dir))
        return outputs

    def _build_executable_with_runtime_main(
        self,
        file: FileWrapper,
        executable_name: str,
        build_runtime_main,
    ) -> Path:
        """Compile every module to .o, build the runtime_main shim (via the
        caller's builder fn), drive the linker. Used by both `kod build` and
        `kod test` — they differ only in which shim builder runs."""
        root_path = self.program.root_fs.root_path
        app_dir = self.build_root / "apps" / file.path.stem
        stage0_dir = self.build_root / "stage0"
        app_dir.mkdir(parents=True, exist_ok=True)
        stage0_dir.mkdir(parents=True, exist_ok=True)
        executable = app_dir / executable_name
        print(
            f"\033[2mBuilding executable \033[22;1;36m{executable}\033[0m",
            file=sys.stderr,
        )
        object_files = []
        for module in self.program:
            out_dir = stage0_dir if self._is_stdlib_module(module) else app_dir
            object_files.append(
                self.build_module(module, out_dir=out_dir).relative_to(root_path)
            )
        object_files.append(build_runtime_main(file, app_dir).relative_to(root_path))
        stdlib_root = self.program.stdlib_fs.root_path
        object_files.append(
            self._build_c(stdlib_root / "arena.c", out_dir=stage0_dir).relative_to(
                root_path
            )
        )
        object_files.append(
            self._build_c(stdlib_root / "runtime.c", out_dir=stage0_dir).relative_to(
                root_path
            )
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

    def build_executable(self, file: FileWrapper) -> Path:
        """Build a normal executable. Stdlib modules + arena/runtime land
        in build/stage0/ (shared across all apps); project modules and the
        runtime_main shim land in build/apps/<stem>/; the final executable
        is build/apps/<stem>/<stem>."""
        return self._build_executable_with_runtime_main(
            file,
            executable_name=file.path.stem,
            build_runtime_main=self.build_runtime_main,
        )

    def build_test_executable(self, file: FileWrapper) -> Path:
        """Build a test runner: same as build_executable but the
        runtime_main shim calls the codegen-emitted `__run_tests`
        dispatcher instead of the user's `main`. The executable is named
        `<stem>_test` to coexist with a regular `build` of the same file."""
        return self._build_executable_with_runtime_main(
            file,
            executable_name=f"{file.path.stem}_test",
            build_runtime_main=self.build_test_runtime_main,
        )
