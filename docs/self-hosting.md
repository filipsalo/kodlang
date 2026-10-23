---
icon: lucide/cpu
---

# Self-hosting

The primary goal of Kod is self-hosting — a compiler written in Kod that compiles itself. The Python frontend exists to bootstrap that, and is shrinking as more orchestration moves into Kod.

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
build/apps/<stem>/  per-app outputs + the final executable
```

Driven by the `Makefile`:

1. **stage0**: the checked-in snapshot `bootstrap/sh_kodc` compiles the always-linked stdlib modules and the compiler library to assembly; `as` assembles them and `clang` builds `arena.c` / `runtime.c`.
2. **stage1**: the snapshot compiles `kodc.kod` and writes the `_main` shim; `ld` links everything into `build/stage1/sh_kodc`. So `sh_kodc` is the *current* compiler sources, compiled by the *snapshot*.
3. **apps**: `kod build foo.kod` compiles each of the program's modules with `build/stage1/sh_kodc` and links them against `build/stage0/`.

Two consequences: a codegen change reaches user programs right away, but the stage0 stdlib modules keep the snapshot's codegen until `make bootstrap-snapshot` refreshes it. And the compiler sources themselves may only use features the snapshot can compile.

If the snapshot is missing, the Makefile falls back to running `kodc.kod` under the Python interpreter (`make bootstrap-snapshot` forces this path; it takes minutes).

## What's still Python

- `kod/interpreter.py` and the Python lexer/parser: the bootstrap path (`kod _interpret kodc.kod ...`) for when the snapshot can't be used.
- `kod/builder.py`: the older build orchestrator. From the repo root, `uv run kod build/run/test/check` no longer reach it; the internal subcommands (`_interpret`, `_emit-asm`, `_dump-ast`) still use it to load programs.
- `kod/__main__.py`: the `uv run kod` entry point. For `build` / `run` / `test` / `check` it refreshes the toolchain with `make` and hands off to `build/apps/kod/kod`.

See `TODO.md` for the running list of Python-deletion work.

## Codegen design

`codegen.kod` is a single-pass emitter built around a few key data structures:

- **Expression / statement / type-expr pools** on the parser: AST nodes are stored in flat arrays and referenced by `int64` ids.
- **Struct / enum / interface tables** on the codegen: registration happens before compilation; field/method lookups index these tables.
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
