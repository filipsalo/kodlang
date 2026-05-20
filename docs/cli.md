---
icon: lucide/terminal
---

# CLI reference

The CLI is `kod` (installed as a [project script](install.md)). Run via `uv run kod ...` from the project, or install globally with `uv tool install .`.

## Public commands

### `kod build <file>`

Compile a Kod source file to a native ARM64 binary.

```shell
uv run kod build hello.kod
./build/apps/hello/hello
```

Build pipeline:

1. Parse all transitively-imported modules.
2. Emit ARM64 assembly for each module (via `sh_kodc` when available, Python interpreter as fallback during bootstrap).
3. Assemble each `.s` with `as`.
4. Compile `stdlib/{arena,runtime}.c` with `clang`.
5. Generate the `_main` runtime shim that calls the user's `main`.
6. Link everything with `ld`.

### `kod run <file>`

`kod build` + execute. Arguments after the file are passed to the program.

```shell
uv run kod run hello.kod
```

### `kod test <path>`

Run `test "..." { ... }` blocks. Path can be a file or a directory.

- File: builds the file + all transitively-imported modules that contain tests, runs everything in one binary, prints a rolled-up summary.
- Directory: walks for `*_test.kod` and runs them all together via a temporary aggregator.

```shell
uv run kod test stdlib/map_test.kod
uv run kod test stdlib            # everything under stdlib/
uv run kod test .                 # everything in the project
```

See [Testing](testing.md) for the syntax.

### `kod check <file>`

Run the full compile pipeline through codegen, report errors, but write no artifacts and skip the link step. Exits non-zero on any error.

```shell
uv run kod check src/foo.kod
```

### `kod fmt <file>`

Not yet implemented.

## Build outputs

| Path | Description |
|------|-------------|
| `build/stage0/` | Shared stdlib objects: `arena.o`, `runtime.o`, `_builtins.o`, `_int64.o`, `_str.o`, `_bool.o`. Reused by `sh_kodc` and every app. |
| `build/stage1/` | The self-hosted compiler `sh_kodc` and its parts (`lexing.{s,o}`, `parsing.{s,o}`, `codegen.{s,o}`, `kodc.{s,o}`, `runtime_main.{s,o}`). |
| `build/apps/<stem>/` | Per-app artifacts: each module's `.s` and `.o`, the runtime_main shim, and the final executable (or `<stem>_test` for `kod test`). |

`make clean-apps`, `make clean-stage1`, `make clean` give scoped cleanup.

## Internal / debug commands

These exist to support the bootstrap and for debugging. Their shape may change.

| Command | Purpose |
|---------|---------|
| `kod _interpret <file>` | Run via the Python interpreter (slow; used by sh_kodc's bootstrap). |
| `kod _emit-asm <file>` | Print the assembly for the entry module to stdout. |
| `kod _dump-ast <file>` | Pretty-print the parsed AST. |
| `kod _emit-runtime-main <entry.kod> <out.s>` | Write the `_main` shim for the given entry. Delegates to sh_kodc when available. |
| `kod _build-stage0` | Build the shared stage0 objects without producing an executable. |
