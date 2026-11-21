---
icon: lucide/test-tube
---

# Testing

Kod has built-in syntax for unit tests: `test "description" { ... }` blocks and an `assert <expr>` statement. `kod test` runs them.

## A first test

```kod
// arithmetic_test.kod
test "addition works" {
    assert 2 + 2 == 4
}

test "negative arithmetic" {
    assert -1 + 1 == 0
    assert -5 - 5 == -10
}
```

```shell
$ uv run kod test arithmetic_test.kod
ok   addition works
ok   negative arithmetic

2/2 passed
```

## `assert <expr>`

If the expression evaluates to `false`, the current test is marked failed and the source text of the expression is captured in the failure message — no need to type `f"got {x}, want {y}"`:

```kod
test "this one will fail" {
    let n: int64 = 7
    assert n == 4
}
```

```
    foo_test.kod:3:5: assertion failed: n == 4
FAIL this one will fail
```

Multiple asserts per test continue running — they accumulate failure messages but don't short-circuit, so a single test surfaces every failing condition at once.

Outside a `test` block, `assert` panics with the same message (exit 1). Same syntax, intent matches the surrounding context — like Rust's always-on `assert!`.

## `fail(msg)`

For failures that aren't a boolean check, call the builtin `fail`:

```kod
test "map lookup hits" {
    mut m: Map[str, int64] = Map[str, int64]()
    m.set("a", 1)
    match m.get("a") {
        Some(v) -> assert v == 1
        none -> fail("missing key after set")
    }
}
```

`fail` is a builtin — no import needed. It works from any function a test calls, not only inside the `test` block. Outside `kod test` there is no test to fail, so `fail` panics with its message, as `assert` does outside a test.

## Discovery

- `kod test <file>` builds the file and every transitively imported module that contains `test` blocks, then runs them all in one binary.
- `kod test <dir>` walks the directory for `*_test.kod` and builds them all into one binary, with no temporary module. Each file keeps its own type names (see [Modules](modules.md#where-names-resolve)), so two test files may both declare a helper `type Pt`, and two test files may share a file name (`a/dup_test.kod` and `b/dup_test.kod`).
- `kod test .` walks the entire project.
- The walk skips a file with a path component below the directory that starts with `.` (worktrees under `.claude/`, editor files, scratch files such as `.kod_compile_test.kod`) and a `build` directory directly below it. (The test suite's own finder skips the dot-directories and a top-level `build/`, but not dot-files.) Only files count: a directory named `x_test.kod` is walked, not run. A match that is not a readable file (a link to nothing) stops the run with `kod test: cannot read <path>`, since a test skipped without a word reads as one that passed. `kod test <file>` takes the file named, whatever its path.

The aggregate exit code is 0 if every test passed, non-zero otherwise.

## Each test in a process of its own

Each test runs in a child process of the test binary, made with `fork` just
before it, so a test that panics or crashes fails alone: its panic message (and
backtrace) or the signal that killed it is printed under it, it reports `FAIL`,
and the tests after it run as usual. A test starts from the state the program
had before the first test, not where the test before it left it: what one test
stores in a module-level variable, the next one doesn't see.

```
stdlib/foo_test.kod
  ok   one (1.20 ms)
panic: index 5 out of bounds for array of length 1
backtrace:
  #0  test "boom" (stdlib/foo_test.kod:7)
  FAIL boom (1.35 ms)
      killed by SIGSEGV
  FAIL bad pointer (985 μs)
  ok   three (1.30 ms)
```

A backtrace names a test's frame `test "<its name>"` and ends there. Starting
the process costs about a millisecond, which the time shown includes.

## Running code in a process of its own

`testing.run(body)` runs the function `body` in a child process and gives back
what that process did, so a test can check what a program prints, reads or
exits with, and that something panics:

```kod
import "io"
import "testing"

test "indexing past the end panics" {
    let r = testing.run(func() {
        let xs = [1]
        print_int(xs[5])
    })
    assert r.status == 1
    assert r.stderr.contains("panic: index 5 out of bounds for array of length 1")
}

test "print ends the line" {
    let r = testing.run(func() { print("hi") })
    assert r.stdout == "hi\n"
}

test "read_stdin_line reads one line" {
    let r = testing.run(func() { print(io.read_stdin_line()) }, stdin: "a\nb\n")
    assert r.stdout == "a\n"
}
```

The result is a `testing.Ran`:

| Field | Meaning |
|-------|---------|
| `status` | the exit status: 0 when `body` returned, 1 when it panicked, 2 when it called `fail`; -1 when a signal ended it. `body` is a function, not a `test` block, so an `assert` in it panics when it fails |
| `signal` | the number of the signal that ended it (`SIGSEGV` is 11), else 0 |
| `stdout`, `stderr` | everything it wrote to them, through `print` or C's `putchar` alike |

`stdin:` is what the child reads from standard input (nothing by default). The
child starts from the state of the test at the call, and what it changes
(variables it captured, module variables) stays in the child. Its output goes
to files rather than pipes, so it can write any amount.

## Output

`kod test` replaces itself with the test binary, so the output appears as the tests run, and the exit code is the binary's. The reporter flushes stdout around every `ok`/`FAIL` line and the file header, and before a failure's detail goes to stderr, so the lines stay in order when stdout and stderr are the same pipe or log. What a test prints with `print` is flushed with them, so it comes out before that test's result line. A panic (an index out of bounds, a failed `must`) flushes stdout before its message too.

When stdout is a terminal, `ok` is green, `FAIL` red, and the time each test took
dim; the summary line is green when all passed and red when any failed. The same
`NO_COLOR` and `TERM=dumb` turn this off as for [errors](cli.md#kod-build-file).

## Hermetic tests

A test needs nothing the repository does not have, and no network: a test of code that talks to a server starts a server of its own on the loopback interface. A test that needs the internet does not belong among the `*_test.kod` files that `kod test <dir>` and the test suite run. A module under test may declare C files and libraries (see [Link inputs](modules.md#link-inputs)); `kod test` compiles and links them like `kod build` does, and a `kod:require` file that is missing stops the build, naming the line that asks for it.

## Layout convention

Test files live next to the code they test, Go-style:

```
stdlib/
  builtins.kod
  map_test.kod
  primitives/
    int64.kod
    int64_test.kod
    str.kod
    str_test.kod
```

The naming convention `*_test.kod` makes them auto-discoverable by `kod test <dir>` without showing up as importable modules.

## How it works (briefly)

- The parser turns `test "..." { ... }` into a `Decl.Test` carrying a synthesized `FuncDecl`.
- The codegen emits each test as a regular function (`<prefix>$__test_N`) and, per module, a `<prefix>$__run_tests` dispatcher. `<prefix>` is described in [Modules](modules.md#symbol-and-object-names).
- The runner is a Kod module, `stdlib/testing.kod`, which `kod test` links into every test program (and `kod build` into any program with a `test` block, since the block's code is linked even though nothing runs it). Its counters are [module-level variables](types.md#module-level-variables).
- `kod test` builds a runtime `_main` that calls every test-bearing module's `__run_tests` in turn, then the runner's `summary` once at the end.
- `fail`/`assert` set a per-test "failed" flag the dispatcher reads after each test returns; that flag drives the `ok` / `FAIL` line and the aggregate count.

## Testing the compiler itself

`make test` rebuilds the toolchain, then builds and runs the test runner, `tools/run_tests.kod`, which runs every `*_test.kod` in the repository that contains `test` blocks through `kod test <file>` (skipping dot-directories and the top-level `build/`); the files of `tests/unit` run together, as one `kod test tests/unit`. A file passes when `kod test` exits 0, its summary line says all passed, and it ran at least as many tests as the file has `test` blocks. Among them:

- **Example programs** (`tests/examples_test.kod`): every other `tests/**/*.kod`. Trailing `// expected output:`, `// expected errors:`, `// expected stderr:`, `// expected status:` and `// expected mode:` comments say what should happen. Each one is compiled and run; `mode: skip` opts out, for a module other fixtures import.
- **Self-hosting** (`tests/selfhost_test.kod`): the fixed-point check described in [Self-hosting](self-hosting.md#verifying-self-hosting).

The tests run programs through the native tools, `build/apps/kod/kod` and `build/stage1/sh_kodc`.

The runner runs as many files at once as the machine has cores (`-j N` for another number), the slow ones first. Files that build the same program, into the same `build/apps/<name>`, share a group, and two of a group never run at the same time; the lists of groups, slow files and serial files are at the top of `tools/run_tests.kod`. The serial files (those that rebuild or replace the `kod` driver, write into the project root, or run `make` on the real tree) run afterwards, one at a time. Each file has 120 seconds: one still running then is killed with everything it started, and fails. The runner prints a line per file as it ends, then the whole output of each file that failed and a summary, and exits 1 if any failed. Given files or directories, it runs only those:

```shell
$ make -s stage1 kod && build/apps/kod/kod build tools/run_tests.kod
$ build/apps/run_tests/run_tests -j 4 stdlib/ tests/lsp_test.kod
```

`make gates` is what to run before a commit: `make test`, then `make test` again with the runtime built with `-DRC_POISON`, which overwrites freed memory so a use after free shows up. It refuses to run when there is a `link.local.cfg`, since it writes its own for the poisoned pass, and removes it again however the pass ends.
