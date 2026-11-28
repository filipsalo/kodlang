---
icon: lucide/download
---

# Install

## Requirements

- macOS on Apple Silicon (AArch64)
- Xcode Command Line Tools (`xcode-select --install`) — provides `as` and `clang`, which compiles the C runtime and links every program

## From source

```shell
git clone https://codeberg.org/filipsalo/kod
cd kod
```

## Building the self-hosted compiler

The Makefile bootstraps everything from scratch:

```shell
make bootstrap   # clean rebuild of stage0 + stage1 (sh_kodc)
make stage1      # incremental rebuild
make test        # rebuild, then run the full test suite
```

## Running

`kod` is the native tool `build/apps/kod/kod`. Build it once with `make kod`, then start it through `./kod`, a link to it at the repository root (until it is built, `./kod` fails with the shell's `no such file or directory`):

```shell
make kod
./kod build hello.kod   # compile to a native binary
./kod run hello.kod     # build + execute
./kod test hello.kod    # run any `test "..." {}` blocks
./kod check hello.kod   # parse + codegen; report errors but emit nothing
```

Started through `./kod`, it runs `make stage1 kod` first when something is out of date, so edits to the compiler, the C runtime, the always-linked stdlib modules or the tool itself are picked up automatically (see [CLI reference](cli.md#kod-build-file)).

## Using kod in other projects

The checkout is the installation: put a link to its `kod` on your `PATH`.

```shell
ln -s ~/src/kod/kod ~/.local/bin/kod
```

Started through that link, or any other way but its own path
`build/apps/kod/kod`, `kod` brings the toolchain up to date first, as `./kod`
does: it finds the checkout by following the links to its own executable.
That costs a `make -q`, some 20 ms, and a rebuild only when something changed.
So a `git pull` in the checkout is all it takes to have the latest: the next
`kod` command anywhere builds it.

Outside the checkout, `kod build`, `run`, `test` and `check` work on the
project in the working directory:

- **Sources** are the project's: the file named, and the modules it imports
  with `import "./name"`, relative to the file that imports them. `import
  "net/http"` and the other standard modules come from the checkout's
  `stdlib/`.
- **What is built**: `kod build main.kod` writes the program to `./main`, as
  `go build` does, or wherever `-o PATH` says. Objects and the programs `kod
  run` and `kod test` make go to the project's hidden `.kod-build/`, so a
  `.gitignore` needs that and the programs. Compiled modules are cached in
  the checkout's `build/cache/`, shared by every project.
- **A program** that `kod run` or `kod test` starts runs in the project's
  directory, so the paths it opens are the project's.
- **Errors** name the project's files by their full paths.

## Linking

`link.cfg` at the repository root says how programs are linked: the `clang` command and the C files and Kod modules every program contains. Nothing in it is specific to one machine, so most machines never touch it. One that needs something else (a Homebrew LLVM `clang` first on `PATH` that does not find the SDK, an unusual SDK) puts the names it changes in `link.local.cfg` next to it (only names `link.cfg` sets), for example:

```
LINK := /usr/bin/clang -target arm64-apple-darwin -Wl,-dead_strip
```

`link.local.cfg` is not tracked by git, so each new `git worktree` needs its own copy (`cp ../link.local.cfg .`). See [Self-hosting](self-hosting.md) for the format.

See [CLI reference](cli.md) for the full command surface.
