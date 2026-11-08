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

`fail` is a builtin — no import needed. It works from any function a test calls, not only inside the `test` block. Outside `kod test` there is no test to fail, so `fail` panics with its message, as `assert` does outside a test.

## Discovery

- `kod test <file>` builds the file and every transitively imported module that contains `test` blocks, then runs them all in one binary.
- `kod test <dir>` walks the directory for `*_test.kod` and builds them all into one binary, with no temporary module. Each file keeps its own type names (see [Modules](modules.md#where-names-resolve)), so two test files may both declare a helper `type Pt`, and two test files may share a file name (`a/dup_test.kod` and `b/dup_test.kod`).
- `kod test .` walks the entire project.
- The walk skips a file with a path component below the directory that starts with `.` (worktrees under `.claude/`, editor files, scratch files such as `.kod_compile_test.kod`) and a `build` directory directly below it. (The test suite's own finder skips the dot-directories and a top-level `build/`, but not dot-files.) Only files count: a directory named `x_test.kod` is walked, not run. A match that is not a readable file (a link to nothing) stops the run with `kod test: cannot read <path>`, since a test skipped without a word reads as one that passed. `kod test <file>` takes the file named, whatever its path.

The aggregate exit code is 0 if every test passed, non-zero otherwise.

## Output

`kod test` replaces itself with the test binary, so the output appears as the tests run, and the exit code is the binary's. The reporter flushes stdout around every `ok`/`FAIL` line and the file header, and before a failure's detail goes to stderr, so the lines stay in order when stdout and stderr are the same pipe or log. What a test prints with `print` is flushed with them, so it comes out before that test's result line. A panic (an index out of bounds, a failed `must`) flushes stdout before its message too.

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

`make test` rebuilds the toolchain and runs pytest, which covers three kinds of check:

- **Example programs**: every `tests/**/*.kod`. Trailing `// expected output:`, `// expected errors:`, `// expected stderr:`, `// expected status:` and `// expected mode:` comments say what should happen. Each one is compiled and run; `mode: skip` opts out, for a module other fixtures import.
- **Test blocks**: every `*_test.kod` in the repo that contains `test` blocks runs through `kod test <file>`, one pytest case per file.
- **Self-hosting**: the fixed-point check described in [Self-hosting](self-hosting.md#verifying-self-hosting).

The tests run programs through the native tools, `build/apps/kod/kod` and `build/stage1/sh_kodc`; Python is only the test harness and the launcher.
