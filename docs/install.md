---
icon: lucide/download
---

# Install

## Requirements

- macOS on Apple Silicon (AArch64)
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Xcode Command Line Tools (`xcode-select --install`) — provides `as`, `ld`, and `clang`

## From source

```shell
git clone https://codeberg.org/filipsalo/kod
cd kod
uv sync
```

## Running

Use `uv run` to invoke the `kod` module:

```shell
uv run python -m kod interpret hello.kod   # interpret
uv run python -m kod build hello.kod       # compile to native binary
```

Or add a shell alias:

```shell
alias kod='uv run python -m kod'
```
