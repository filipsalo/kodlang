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

## Call labels

Calls use labeled arguments by default; the parameter name *is* the label:

```kod
func greet(name: str) -> none {
    print(f"Hello, {name}!")
}

greet(name: "Alice")
```

`anon` removes the label requirement for that parameter:

```kod
func double(anon n: int64) -> int64 {
    return n * 2
}

double(5)
```

Convention: when calling, label every parameter except 1–2 of a single shared
type (e.g. `slice(arr, from: 0, to: 3)` is fine; passing a label for `arr`
is just noise).

If a passed argument is a bare identifier with the same name as the
parameter, the label can be elided:

```kod
let name: str = "Alice"
greet(name)           // shorthand for greet(name: name)
```

## Label / binding split

A parameter can have two names — an external *label* used at call sites and
an internal *binding* used inside the function body:

```kod
func greet(who person: str) -> none {
    print(f"Hello, {person}!")
}

greet(who: "Alice")
```

Useful for prepositions that make call sites read naturally without forcing
short variable names inside the function.

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

## Function-pointer types

Functions are values. Use `func(T1, T2) -> R` as a type to store,
pass, or return them — the runtime representation is an 8-byte
pointer to the function's code, same as a C function pointer.

```kod
func double(x: int64) -> int64 { return x * 2 }
func triple(x: int64) -> int64 { return x * 3 }

func apply(anon f: func(int64) -> int64, anon x: int64) -> int64 {
    return f(x)
}

let g: func(int64) -> int64 = double
print_int(g(21))             // 42 — indirect call through g
print_int(apply(triple, 14)) // 42 — function passed as callback
```

Plain named functions only — no anonymous functions (lambdas) or
closures yet. A bare identifier in value position resolves to the
function's address when it isn't shadowed by a local variable; a
call site `f(args)` does an indirect `blr` when `f` is a local of
function type, falling through to the direct `bl` otherwise.

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
