---
icon: lucide/download
---

# Install

## Requirements

- macOS on Apple Silicon (AArch64)
- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (recommended)
- Xcode Command Line Tools (`xcode-select --install`) — provides `as` and `clang`, which compiles the C runtime and links every program

## From source

```shell
git clone https://codeberg.org/filipsalo/kod
cd kod
uv sync
```

## Building the self-hosted compiler

The Makefile bootstraps everything from scratch:

```shell
make bootstrap   # clean rebuild of stage0 + stage1 (sh_kodc)
make stage1      # incremental rebuild
make test        # rebuild, then run the full test suite
```

`uv run kod build|run|test|check` runs `make stage1 kod` first when invoked from the repo root, so edits to the compiler, the C runtime, or the always-linked stdlib modules are picked up automatically.

## Running

`kod` is installed as a `uv run` script:

```shell
uv run kod build hello.kod   # compile to a native binary
uv run kod run hello.kod     # build + execute
uv run kod test hello.kod    # run any `test "..." {}` blocks
uv run kod check hello.kod   # parse + codegen; report errors but emit nothing
```

Run `kod` from the repository root. A global `uv tool install .` is not supported: the package carries no stdlib.

## Linking

`link.cfg` at the repository root says how programs are linked: the `clang` command and the C files and Kod modules every program contains. Nothing in it is specific to one machine, so most machines never touch it. One that needs something else (a Homebrew LLVM `clang` first on `PATH` that does not find the SDK, an unusual SDK) puts the names it changes in `link.local.cfg` next to it (only names `link.cfg` sets), for example:

```
LINK := /usr/bin/clang -target arm64-apple-darwin -Wl,-dead_strip
```

`link.local.cfg` is not tracked by git, so each new `git worktree` needs its own copy (`cp ../link.local.cfg .`). See [Self-hosting](self-hosting.md) for the format.

See [CLI reference](cli.md) for the full command surface.
