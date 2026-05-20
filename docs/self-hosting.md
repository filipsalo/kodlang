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
| `stdlib/kod/codegen.kod` | ARM64 assembly emitter |
| `kodc.kod` | Driver: parses entry + imports, registers types, runs codegen |
| `stdlib/process.kod`, `stdlib/io.kod`, `stdlib/testing.kod` | Stdlib |

`sh_kodc` reads a `.kod` file and emits ARM64 assembly to stdout, plus a few internal subcommands (`_emit-runtime-main`) that grow over time as build steps move out of Python.

## Build chain

```
build/stage0/   shared stdlib objects (arena.o, runtime.o, _builtins.o,
                _int64.o, _str.o, _bool.o)
build/stage1/   sh_kodc + its .s/.o, plus runtime_main.{s,o}
build/apps/<stem>/  per-app outputs + the final executable
```

Bootstrap, driven by the `Makefile`:

1. **stage0** — the Python interpreter compiles every stdlib module under `stdlib/` to assembly, then assembles them. Slow but only happens once per source change.
2. **stage1** — for each of `lexing`, `parsing`, `codegen`, `kodc`, the Python interpreter drives `kodc.kod` to emit `.s`, which `as` assembles. `_emit-runtime-main` writes the `_main` shim. `ld` links it all into `build/stage1/sh_kodc`.
3. After bootstrap, `kod build foo.kod` uses `sh_kodc` to compile each module; the Python interpreter is only used as a fallback if `sh_kodc` is missing or stale.

## What's still Python

- The build orchestrator (`kod/builder.py`) drives `as` / `ld` / `clang` and walks the module graph. Subprocess support in Kod (`process.run` in `stdlib/process.kod`) is the foundation for moving this in; the first step landed (`_emit-runtime-main` is Kod-native).
- The Python lexer/parser still exists, used by `kod _interpret` and as the entry point that walks imports. `kod build` parses with Python then hands each module to `sh_kodc`; the parse happens twice in practice.

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
$ make bootstrap
$ build/stage1/sh_kodc tests/map.kod > /tmp/sh.s
$ uv run kod _interpret kodc.kod tests/map.kod > /tmp/py.s
$ diff /tmp/sh.s /tmp/py.s
```

`sh_kodc` and the interpreter-driven `kodc.kod` produce identical assembly. `tests/examples_test.py::test_selfhost_matches_interpreter` runs this check in CI.
