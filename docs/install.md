---
icon: lucide/download
---

# Install

## Requirements

- macOS on Apple Silicon (AArch64)
- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (recommended)
- Xcode Command Line Tools (`xcode-select --install`) — provides `as`, `ld`, and `clang`

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
make test        # run pytest
```

## Running

`kod` is installed as a `uv run` script:

```shell
uv run kod build hello.kod   # compile to a native binary
uv run kod run hello.kod     # build + execute
uv run kod test hello.kod    # run any `test "..." {}` blocks
uv run kod check hello.kod   # parse + codegen; report errors but emit nothing
```

For a global install:

```shell
uv tool install .   # puts `kod` on your PATH
```

See [CLI reference](cli.md) for the full command surface.
