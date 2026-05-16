---
icon: lucide/function-square
---

# Functions

## Declaration

```kod
func add(a: int64, b: int64) -> int64 {
    return a + b
}
```

Parameters are `name: Type`. The return type follows `->`. Functions that return nothing use `-> none`.

## Calling

```kod
let result: int64 = add(1, 2)
```

Arguments are passed positionally.

## Anonymous parameters

Mark a parameter `anon` to allow callers to pass it without a label:

```kod
func double(anon n: int64) -> int64 {
    return n * 2
}

let x: int64 = double(5)   // no label needed
```

Without `anon`, the parameter name becomes a required label at the call site. This only applies when calling functions — the parameter still has a name inside the function body.

!!! note
    Currently all parameters behave as positional (no labeled call syntax at call sites yet). `anon` is a declaration hint used by the type system.

## `main`

Every executable must define `main`. It can take no arguments or receive the command-line argument list:

```kod
// no args
func main() -> int64 {
    return 0
}

// with argv
func main(argv: [str]) -> int64 {
    print_int(len(argv))
    return 0
}
```

## Methods

Functions inside a `struct` type declaration are methods. The first parameter must be `self`:

```kod
type Counter = struct {
    value: int64

    func increment(self) -> none {
        self.value = self.value + 1
    }

    func get(self) -> int64 {
        return self.value
    }
}
```

Call with dot notation:

```kod
let c: Counter = Counter(value: 0)
c.increment()
print_int(c.get())
```

## Extern functions

Declare external C functions with `extern`:

```kod
extern func strlen(anon s: str) -> int64
extern func putchar(anon c: int64) -> int64
```

These link against the C runtime and any object files passed at link time.

## Recursion

Recursion works in the interpreter. In the compiler, mutual recursion between functions is supported as long as all functions are declared in the same module.

```kod
func fib(n: int64) -> int64 {
    if n <= 1 {
        return n
    }
    return fib(n - 1) + fib(n - 2)
}
```
