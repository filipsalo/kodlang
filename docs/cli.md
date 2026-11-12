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
2. Parse the entry and walk its transitive imports. A missing entry file (`path:1:1: error: no such file`) or a missing import (`importer:line:col: error: no such module ...`) is an error. Then read the comment lines at the top of each module for the C files, link arguments and required files it declares ([Link inputs](modules.md#link-inputs)); a mistake in them, or a required file that isn't there, stops the build before anything is compiled.
3. Compile each module that isn't prebuilt in `build/stage0/` to a `.o` with `sh_kodc _compile`, the entry first, stopping at the first that fails, and then each C file the modules name, once. A module compiled before is taken from `build/cache/` instead: its object there is named by a SHA-256 of `sh_kodc`, the module's path, and the path and text of each module it loads (what it imports, directly or not, and the `STAGE0_KOD` modules), which is all its object depends on. So an unchanged module isn't compiled again, whichever program it's in. Only modules named by a relative path, inside the project, are kept there. A failing module's errors follow those in the declarations of the modules it loads, such as an import that names no file, an unknown return type, a field declared twice or a parse error, since its own may be only their cascades.
4. Generate and assemble the `_main` runtime shim that calls the user's `main`.
5. Link everything against the prebuilt `build/stage0/` objects with the `LINK` command of `link.cfg` (`clang`, see [Self-hosting](self-hosting.md)), followed by the arguments the modules give with `kod:link`. The driver reads `link.cfg`, and `link.local.cfg` if there is one, from the working directory: run it from the repository root, or it says `link.cfg not found`.

The native driver (`build/apps/kod/kod`, built from `tools/kod.kod`) runs steps 2–5.

A syntax error is reported once: the parser skips the rest of the statement, struct
field, parameter or declaration it is in, and carries on with the next, so a later
mistake is still found. A missing `,` between parameters, or a missing `:` before a
field's type, is taken as written. Type errors inside a declaration (a function, a type,
a constant) that has a syntax error aren't reported, since they may come from what the
parser skipped; the other declarations are checked as usual.

On a terminal, errors are coloured: the location and message in bold, `error:` and
the caret under the column in red. Set `NO_COLOR` to any non-empty value, or
`TERM=dumb`, to turn colour off. When stderr is a file or a pipe there is none.

### `kod run <file>`

`kod build` + execute. Arguments after the file are passed to the program.

```shell
uv run kod run hello.kod
```

`kod` replaces itself with the program (`execvp`), so the program has your terminal. Its stdin, stdout and stderr are yours, its output appears as it is written, and its exit status, or the signal that killed it, is what your shell sees. (stdout is block-buffered when it is not a terminal; call `io.flush_stdout()` where the order of the two streams matters; a panic flushes it before its message.) If the program cannot be executed, `kod` says so and exits 127.

### `kod test <path>`

Run `test "..." { ... }` blocks. Path can be a file or a directory.

- File: builds the file + all transitively-imported modules that contain tests, runs everything in one binary, prints a rolled-up summary.
- Directory: walks for `*_test.kod` and builds them all into one program, with no temporary module, so two test files may share a file name. A file with a path component below the directory that starts with `.` (worktrees under `.claude/`, editor files) and a `build` directory directly below it are skipped; a `*_test.kod` that cannot be read (a link to nothing) stops the run. `kod test <file>` takes the file named, whatever its path.

```shell
uv run kod test stdlib/map_test.kod
uv run kod test stdlib            # everything under stdlib/
uv run kod test .                 # everything in the project
```

Both replace `kod` with the test binary, as `kod run` does with a program: its output appears as it is written and its exit status is `kod`'s. The test reporter flushes stdout around every result line and before a failure's detail goes to stderr, so the `ok`/`FAIL` lines and the `assertion failed` detail stay in order on a pipe or in a CI log too; output a test prints itself is flushed with them.

See [Testing](testing.md) for the syntax.

### `kod check <file>`

Run the full compile pipeline through codegen, report errors, but write no artifacts and skip the link step. Exits non-zero on any error. It also checks the link directives at the top of each module (see [Link inputs](modules.md#link-inputs)), but compiles no C file and does not look for a `kod:require` file. An error already shown for one module isn't shown again for another.

```shell
uv run kod check src/foo.kod
```

## Build outputs

| Path | Description |
|------|-------------|
| `build/stage0/` | The objects `sh_kodc`, `kod` and every app share: the C files and Kod modules `link.cfg` lists as `RUNTIME_C` and `STAGE0_KOD` (`arena.o`, `rc.o`, `runtime.o`, `_<name>.o`; see [Self-hosting](self-hosting.md#build-chain)) and the compiler library the two tools link. |
| `build/stage1/` | The self-hosted compiler `sh_kodc` and the objects it is linked from (`kodc.{s,o}`, `runtime_main.{s,o}`). |
| `build/apps/<stem>/` | The final executable, `<stem>` (or `<stem>_test` for `kod test`). `<stem>` is the entry's file name without `.kod`; for `kod test <dir>` it is the directory with every byte outside letters, digits, `_` and `-` replaced by `_` (its last 200 bytes, when it is longer), then `_tests`. A file whose name without `.kod` is empty, `.` or `..` has no program name and is refused. An entry named `kod` or `lsp` (other than `tools/kod.kod` and `tools/lsp.kod`, however they are spelled) is refused, because its executable would replace the tool. So is one whose directory the volume takes for the tool's, such as `KOD` on a case-insensitive volume. |
| `build/apps/<stem>/<stem>.obj/` | The program's objects, in a tree that mirrors the source tree: each module's `.o`, with its `.s` when it was compiled rather than taken from the cache (`lib/json.kod` is `<stem>.obj/lib/json.kod.o`), the object of each C file a module names (`<stem>.obj/lib/json.c.o`) and the `_main` shim (`<entry>.main.{s,o}`, or `<first entry>.testmain.{s,o}` for tests). So `json` and `./json`, or `a/util` and `b/util`, are different objects. |

| `build/cache/` | Module objects by key (step 3), `<sha256>.o`. Rebuilding `sh_kodc` empties it, since every key names the compiler. |

`make clean-apps` (which also empties `build/cache/`), `make clean-stage1`, `make clean` give scoped cleanup.

## Internal / debug commands

These exist for the build and for debugging. Their shape may change: `sh_kodc` has the internal subcommands `_compile`, `_emit-runtime-main` and `_emit-test-runtime-main`.
