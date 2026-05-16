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

**Interpret** (fast, no compilation step):

```shell
$ python -m kod interpret hello.kod
Hello, world!
```

**Compile** to a native binary:

```shell
$ python -m kod build hello.kod
$ ./build/hello
Hello, world!
```

## A real program

```kod
func greet(name: str) -> none {
    print(f"Hello, {name}!")
}

func main() -> int64 {
    let names: [str] = ["Alice", "Bob", "Carol"]
    for i < len(names) {
        greet(names[i])
        i = i + 1
    }
    return 0
}
```

## Variables

Variables are declared with `let` and require a type annotation:

```kod
let x: int64 = 42
let s: str = "hello"
let flag: bool = true
```

Reassignment uses `=`:

```kod
x = x + 1
```

## Next steps

- [Types](types.md) — the full type system
- [Functions](functions.md) — declaration, parameters, return types
- [Control flow](control-flow.md) — `if`, `for`, `match`
