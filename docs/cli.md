---
icon: lucide/terminal
---

# CLI reference

The CLI is `kod` (installed as a [project script](install.md)). Run it as `uv run kod ...` from the repository root: it refreshes the toolchain with `make` and hands off to the native tool `build/apps/kod/kod`. From any other directory it prints one line saying where to run it from and exits 1.

## Public commands

### `kod build <file>`

Compile a Kod source file to a native ARM64 binary.

```shell
uv run kod build hello.kod
./build/apps/hello/hello
```

Build pipeline:

1. Refresh the toolchain with `make stage1 kod` (a no-op unless the compiler, the C runtime, or an always-linked stdlib module changed). This only happens when `kod` runs from the repo root; invoking `build/apps/kod/kod` directly skips it. If the rebuild fails, `kod` reports it and stops.
2. Parse the entry and walk its transitive imports. A missing entry file (`path:1:1: error: no such file`) or a missing import (`importer:line:col: error: no such module ...`) is an error.
3. Compile each module that isn't prebuilt in `build/stage0/` to a `.o` with `sh_kodc _compile`, the entry first, stopping at the first that fails. A failing module's errors follow those in the declarations of the modules it loads, such as an import that names no file, an unknown return type, a field declared twice or a parse error, since its own may be only their cascades.
4. Generate and assemble the `_main` runtime shim that calls the user's `main`.
5. Link everything with `ld` against the prebuilt `build/stage0/` objects.

The native driver (`build/apps/kod/kod`, built from `tools/kod.kod`) runs steps 2–5.

### `kod run <file>`

`kod build` + execute. Arguments after the file are passed to the program.

```shell
uv run kod run hello.kod
```

### `kod test <path>`

Run `test "..." { ... }` blocks. Path can be a file or a directory.

- File: builds the file + all transitively-imported modules that contain tests, runs everything in one binary, prints a rolled-up summary.
- Directory: walks for `*_test.kod` and builds them all into one program, with no temporary module, so two test files may share a file name. A file with a path component below the directory that starts with `.` (worktrees under `.claude/`, editor files) and a `build` directory directly below it are skipped; a `*_test.kod` that cannot be read (a link to nothing) stops the run. `kod test <file>` takes the file named, whatever its path.

```shell
uv run kod test stdlib/map_test.kod
uv run kod test stdlib            # everything under stdlib/
uv run kod test .                 # everything in the project
```

See [Testing](testing.md) for the syntax.

### `kod check <file>`

Run the full compile pipeline through codegen, report errors, but write no artifacts and skip the link step. Exits non-zero on any error. An error already shown for one module isn't shown again for another.

```shell
uv run kod check src/foo.kod
```

## Build outputs

| Path | Description |
|------|-------------|
| `build/stage0/` | Shared stdlib objects: `arena.o`, `runtime.o`, `_builtins.o`, `_int64.o`, `_str.o`, `_bool.o`. Reused by `sh_kodc` and every app. |
| `build/stage1/` | The self-hosted compiler `sh_kodc` and its parts (`lexing.{s,o}`, `parsing.{s,o}`, `codegen.{s,o}`, `kodc.{s,o}`, `runtime_main.{s,o}`). |
| `build/apps/<stem>/` | The final executable, `<stem>` (or `<stem>_test` for `kod test`). `<stem>` is the entry's file name without `.kod`; for `kod test <dir>` it is the directory with every byte outside letters, digits, `_` and `-` replaced by `_` (its last 200 bytes, when it is longer), then `_tests`. A file whose name without `.kod` is empty, `.` or `..` has no program name and is refused. An entry named `kod` or `lsp` (other than `tools/kod.kod` and `tools/lsp.kod`, however they are spelled) is refused, because its executable would replace the tool. So is one whose directory the volume takes for the tool's, such as `KOD` on a case-insensitive volume. |
| `build/apps/<stem>/<stem>.obj/` | The program's objects, in a tree that mirrors the source tree: each module's `.s` and `.o` (`lib/json.kod` is `<stem>.obj/lib/json.kod.o`) and the `_main` shim (`<entry>.main.{s,o}`, or `<first entry>.testmain.{s,o}` for tests). So `json` and `./json`, or `a/util` and `b/util`, are different objects. |

`make clean-apps`, `make clean-stage1`, `make clean` give scoped cleanup.

## Internal / debug commands

These exist to support the bootstrap and for debugging. Their shape may change. `sh_kodc` has its own internal subcommands (`_compile`, `_emit-runtime-main`, `_emit-test-runtime-main`).

| Command | Purpose |
|---------|---------|
| `kod _interpret <file>` | Run via the Python interpreter (slow; used by sh_kodc's bootstrap). |
| `kod _emit-runtime-main <entry.kod> <out.s>` | Write the `_main` shim for the given entry: the bootstrap's version, which the Makefile uses when there is no snapshot. `build/stage1/sh_kodc _emit-runtime-main` writes the same shim. Run from the repository root. |
