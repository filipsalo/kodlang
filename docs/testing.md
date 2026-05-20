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
- `kod test <dir>` walks the directory for `*_test.kod`, builds them all in one binary via a temporary aggregator at the project root.
- `kod test .` walks the entire project.

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
- The codegen emits each test as a regular function (`<prefix>$__test_N`) and, per module, a `<prefix>$__run_tests` dispatcher.
- `kod test` builds a runtime `_main` that calls every test-bearing module's `__run_tests` in turn, then `_kod_test_summary` once at the end. Counters live in C runtime statics.
- `fail`/`assert` set a per-test "failed" flag the dispatcher reads after each test returns; that flag drives the `ok` / `FAIL` line and the aggregate count.
