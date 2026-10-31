---
icon: lucide/cpu
---

# Self-hosting

The primary goal of Kod is self-hosting — a compiler written in Kod that compiles itself. The Python side is frozen: it is the interpreter and the bootstrap, and gets no new build logic.

## Status

The self-hosted compiler `sh_kodc` exists and is the production path. `make stage1` builds it, and every `kod build` / `kod run` / `kod test` invocation uses it for codegen when available.

**Sources in Kod:**

| File | Role |
|------|------|
| `stdlib/kod/lexing.kod` | Tokenizer |
| `stdlib/kod/parsing.kod` | Parser (AST built into a pool of `int64` ids) |
| `stdlib/kod/ast.kod` | AST node types |
| `stdlib/kod/regalloc.kod` | Register allocation over the emitted instructions |
| `stdlib/kod/codegen.kod` | ARM64 assembly emitter |
| `stdlib/kod/build.kod` | Import resolution and whole-program registration |
| `kodc.kod` | `sh_kodc` entry point: compile a module, emit the `_main` shim |
| `tools/kod.kod` | The native `kod` driver: build / run / test / check |

`sh_kodc` reads a `.kod` file and emits ARM64 assembly to stdout, plus a few internal subcommands (`_compile`, `_emit-runtime-main`, `_emit-test-runtime-main`).

## Build chain

```
bootstrap/sh_kodc   checked-in sh_kodc snapshot
build/stage0/       C runtime objects, the always-linked stdlib modules, and the
                    compiler library shared by sh_kodc and the kod driver
build/stage1/       sh_kodc + its .s/.o, plus runtime_main.{s,o}
build/apps/kod/     the native kod driver
build/apps/<stem>/  the final executable; its objects are in <stem>.obj/, a tree that
                    mirrors the source tree (see Modules, "Symbol and object names")
link.cfg            how everything is linked, read by the Makefile and by kod
```

Driven by the `Makefile`:

1. **stage0**: the checked-in snapshot `bootstrap/sh_kodc` compiles the always-linked stdlib modules and the compiler library to assembly; `as` assembles them and `clang` builds `arena.c` / `runtime.c`.
2. **stage1**: the snapshot compiles `kodc.kod` and writes the `_main` shim; `clang` links everything into `build/stage1/sh_kodc`. So `sh_kodc` is the *current* compiler sources, compiled by the *snapshot*.
3. **apps**: `kod build foo.kod` compiles each of the program's modules with `build/stage1/sh_kodc` to `build/apps/foo/foo.obj/<path>.o` and links them against `build/stage0/`.

Two consequences: a codegen change reaches user programs right away, but the stage0 stdlib modules keep the snapshot's codegen until `make bootstrap-snapshot` refreshes it. And the compiler sources themselves may only use features the snapshot can compile.

If the snapshot is missing, the Makefile falls back to running `kodc.kod` under the Python interpreter (`make bootstrap-snapshot` forces this path; it takes minutes).

### The link configuration

`link.cfg` at the repository root describes the link once. The Makefile `include`s it and `tools/kod.kod` reads it, so both link the same way. One `NAME := word word ...` per line, and nothing else:

- A name is capital letters, digits and `_`, starting with a letter, and is set once per file.
- Words are separated by one space. A word is letters, digits and the characters `_ . / , = + @ -`; there is no quoting, no `$(...)`, no continuation line, no tab, no trailing space.
- A line that starts with `#` is a comment, and an empty line is skipped. A `#` anywhere else in a line is an error, and so is a comment that ends in `\`.

`kod` rejects a line that does not fit, naming the file and line; for a line that fits, Make and `kod` read the same words. `link.local.cfg` (untracked) is read after `link.cfg` and overrides single names on one machine; a new `git worktree` needs its own copy. It overrides and does not add: a name there that `link.cfg` does not set (a typo, or a name of Make's own such as `STAGE0` or `SHELL`) is an error in both. Neither accepts a `LINK`, `RUNTIME_C` or `STAGE0_KOD` that ends up empty.

| Name | Meaning |
|---|---|
| `LINK` | command that links an executable: `clang -target arm64-apple-darwin -Wl,-dead_strip`. `clang` finds the SDK and the macOS version. |
| `CC`, `CFLAGS` | compile a C file: `clang`, `-target arm64-apple-darwin -I stdlib`. The target is pinned as in `LINK` (and `as`), so a `clang` that follows the architecture of the shell it runs in (one under Rosetta) does not produce x86_64 objects that the arm64 link rejects. |
| `RUNTIME_C` | C files linked into every program; built to `build/stage0/<name>.o` |
| `STAGE0_KOD` | Kod modules linked into every program, in link order; prebuilt by the snapshot compiler to `build/stage0/_<basename>.o`, so their basenames must be unique |

A program links, in order: `LINK`, `-o <exe>`, the `RUNTIME_C` objects, the `STAGE0_KOD` objects, the program's module objects, the objects of the C files its modules name, its `_main` shim, and last the arguments its modules give with `kod:link` (see [Modules](modules.md#link-inputs)). A module that declares such lines cannot be in `STAGE0_KOD`, nor be one of the compiler's own modules: the Makefile does not read them. `kod` says so for `STAGE0_KOD`, and a test checks the others. Adding an always-linked module is one more word in `STAGE0_KOD`; the Makefile derives its rule. `make` rebuilds the C runtime objects and relinks `sh_kodc` and `kod` when `link.cfg` or `link.local.cfg` changes (the objects also when a header in `stdlib/` does, such as `kod_rt.h`), and also when the configuration in force is not the one they were built with (it keeps that in `build/.link-config`), so removing `link.local.cfg`, or a name from it, rebuilds too. A program gets the deployment target of the machine that builds it, as `clang` chooses it (`MACOSX_DEPLOYMENT_TARGET` in the environment overrides that).

Requirements: `clang` and `as` (Xcode Command Line Tools). `kod` is run from the repository root; from another directory `uv run kod` says that `build/apps/kod/kod` is not found, and that tool, called by its path, says `link.cfg not found`. Calling `build/apps/kod/kod` directly does not rebuild `build/stage0/`, so after a change to `runtime.c` or `link.cfg` run `make kod` (or `uv run kod`, which does); when the configuration names an always-linked object that is not there yet, `kod` says `build/stage0/_name.o not found; run make`.

## What's still Python

- `kod/interpreter.py`, the Python lexer, parser and `kod/loader.py`: the independent second implementation of the language (the `both`-mode fixtures and the parity tests) and the bootstrap when `bootstrap/sh_kodc` is missing (`kod _interpret kodc.kod ...`).
- `kod/bootstrap.py`: the one piece of build logic left, `kod _emit-runtime-main`, which the Makefile uses to write the `_main` shim of `kodc.kod` and `tools/kod.kod` when there is no snapshot. `tests/bootstrap_test.py` keeps it identical to `sh_kodc _emit-runtime-main`.
- `kod/__main__.py`: `uv run kod build|run|test|check`, run from the repository root, refreshes the toolchain with `make` and hands off to `build/apps/kod/kod`. If `make` fails, it prints make's errors and `kod: failed to rebuild the toolchain` and stops with make's status; from any other directory, or when `make` is not installed and the tool is not built, it says that the tool is missing. Plus `_interpret`.

Rules: language features and build logic are added in Kod only. The interpreter is not extended for them: their fixtures say `// expected mode:` `run`. An `extern func` the interpreter does not mirror is compiled-only. It mirrors twelve: `read_file`, `kod_is_file`, `kod_panic`, `kod_puts`, `kod_bytes_from_array`, `kod_str_to_bytes`, `kod_bytes_to_str`, `kod_eprint`, `read_stdin_line`, `read_stdin_exact`, `write_stdout` and `putchar` (the builtin; it shares libc's stdout buffer with `kod_puts`). The compiler sources and the stage0 stdlib stay within what the snapshot and the Python parser accept (types declared before use). Tests call `build/apps/kod/kod` and `build/stage1/sh_kodc` directly. `uv tool install .` is not supported: the wheel contains no stdlib.

See `TODO.md` for the running list of Python-deletion work.

## Codegen design

`codegen.kod` is a single-pass emitter built around a few key data structures:

- **Expression / statement / type-expr pools** on the parser: AST nodes are stored in flat arrays and referenced by `int64` ids.
- **Struct / enum / interface tables** on the codegen: registration happens before compilation; field/method lookups index these tables. Each module also keeps a table of the type names it declares, so a type name resolves in the module that wrote it: through that module's own table, the tables of the modules its import lists name, then the builtins', and `m.T` through the table of the module imported as `m`.
- **Register pool**: `x8`–`x15` used as expression temporaries; saved/restored across calls via stack spills as needed.
- **Generic monomorphisation**: each unique `Map[str, int64]` instantiation gets its own struct entry; methods compile once per instantiation.
- **Interface dispatch**: `{data_ptr, vtable_ptr}` cells in the arena, one vtable per (struct, interface) pair; primitives box implicitly.

## Verifying self-hosting

```shell
make selfhost-check
```

Fixed-point check. `build/stage1/sh_kodc` compiles the compiler into `build/selfhost/stage2/`, that compiler compiles it again into `build/selfhost/stage3/`, and the two sets of assembly must be byte-identical. A miscompile in the compiler that changes its own behavior shows up as a difference. Takes a few seconds; pytest runs it.

It then compiles every `.kod` file in the repo (the `make asm-diff` corpus) with both `build/stage1/sh_kodc` and the stage2 compiler, and fails if any file's assembly, diagnostics or exit status differ, writing both outputs under `build/selfhost/corpus-diff/`. Stage1 is the current sources compiled by the snapshot and stage2 the same sources compiled by themselves, so a difference means the snapshot miscompiles some of the new compiler code, typically a construct it handles differently than the current compiler does. Compiler sources must then avoid that construct until the snapshot is refreshed.

`tests/examples_test.py::test_selfhost_matches_interpreter` additionally checks that `sh_kodc` and `kodc.kod` running under the Python interpreter produce identical assembly for a small program, so the bootstrap path stays usable.

### Checking that a compiler refactor changes nothing

```shell
make asm-diff            # compare against HEAD
make asm-diff BASE=main  # or any other revision
```

Builds `sh_kodc` at `BASE` (cached under `build/asm-diff/`), compiles every `.kod` file in the repo with both that compiler and the working tree's, and reports each file whose assembly, diagnostics or exit status differ. A pure refactor should report no differences. Both compilers read the working tree's `stdlib/`, so the comparison isolates changes to the compiler itself.
