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
    let m: Map[str, int64] = Map[str, int64]()
    m.set("a", 1)
    match m.get("a") {
        Some(v) -> assert v == 1
        none -> fail("missing key after set")
    }
}
```

`fail` is a builtin — no import needed.

## Discovery

- `kod test <file>` builds the file and every transitively imported module that contains `test` blocks, then runs them all in one binary.
- `kod test <dir>` walks the directory for `*_test.kod` and builds them all into one binary, with no temporary module. Each file keeps its own type names (see [Modules](modules.md#where-names-resolve)), so two test files may both declare a helper `type Pt`, and two test files may share a file name (`a/dup_test.kod` and `b/dup_test.kod`).
- `kod test .` walks the entire project.
- The walk skips a file with a path component below the directory that starts with `.` (worktrees under `.claude/`, editor files, scratch files such as `.kod_compile_test.kod`) and a `build` directory directly below it. (The test suite's own finder skips the dot-directories and a top-level `build/`, but not dot-files.) Only files count: a directory named `x_test.kod` is walked, not run. A match that is not a readable file (a link to nothing) stops the run with `kod test: cannot read <path>`, since a test skipped without a word reads as one that passed. `kod test <file>` takes the file named, whatever its path.

The aggregate exit code is 0 if every test passed, non-zero otherwise.

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
- `kod test` builds a runtime `_main` that calls every test-bearing module's `__run_tests` in turn, then `_kod_test_summary` once at the end. Counters live in C runtime statics.
- `fail`/`assert` set a per-test "failed" flag the dispatcher reads after each test returns; that flag drives the `ok` / `FAIL` line and the aggregate count.

## Testing the compiler itself

`make test` rebuilds the toolchain and runs pytest, which covers three kinds of check:

- **Example programs**: every `tests/**/*.kod`. Trailing `// expected output:`, `// expected errors:`, `// expected stderr:`, `// expected status:` and `// expected mode:` comments say what should happen. By default each one runs both compiled and under the Python interpreter (`mode: run` / `mode: interpret` pick one, `mode: skip` opts out).
- **Test blocks**: every `*_test.kod` in the repo that contains `test` blocks runs through `kod test <file>`, one pytest case per file.
- **Self-hosting**: the fixed-point check and the interpreter parity check described in [Self-hosting](self-hosting.md#verifying-self-hosting).

The tests run programs through the native tools, `build/apps/kod/kod` and `build/stage1/sh_kodc`; Python only runs the interpreter. Python is frozen: language features and build logic are added in Kod, and a fixture for a feature the interpreter does not have says `// expected mode:` `run`. An `extern func` the interpreter does not mirror is compiled-only, so a fixture that calls one says `run` too.
