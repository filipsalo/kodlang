---
icon: lucide/zap
---

# Quickstart

## Hello, world

Create `hello.kod`:

```kod
func main() -> int64 {
    print("Hello, world!")
    return 0
}
```

**Build** and run:

```shell
$ uv run kod build hello.kod
$ ./build/apps/hello/hello
Hello, world!
```

`uv run kod run hello.kod` does both in one step.

## A real program

```kod
func greet(anon name: str) -> none {
    print(f"Hello, {name}!")
}

func main() -> int64 {
    let names: [str] = ["Alice", "Bob", "Carol"]
    for name in names {
        greet(name)
    }
    return 0
}
```

## Variables

Bindings are declared with `let` and are **immutable** — the name can't be
reassigned. A type annotation is usually required:

```kod
let x: int64 = 42
let s: str = "hello"
let flag: bool = true
```

For a binding you intend to reassign, use `mut`:

```kod
mut count: int64 = 0
count = count + 1   // ok

let limit: int64 = 10
limit = 20          // error: cannot reassign immutable binding `limit`
```

## A test file

```kod
// arithmetic_test.kod
test "addition" {
    assert 2 + 2 == 4
}

test "subtraction" {
    assert 10 - 3 == 7
}
```

```shell
$ uv run kod test arithmetic_test.kod
ok   addition
ok   subtraction

2/2 passed
```

## Next steps

- [Types](types.md) — the full type system
- [Functions](functions.md) — declaration, parameters, return types
- [Control flow](control-flow.md) — `if`, `for`, `match`
- [Testing](testing.md) — the `test` and `assert` syntax
