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

## Default values

Trailing parameters may declare a default with `= expr`, and a call can
leave them out:

```kod
func retry(anon n: int64, delay_ms: int64 = 100) -> int64 {
    return n * delay_ms
}

retry(3)                  // 300
retry(3, delay_ms: 500)   // 1500
```

The default is evaluated fresh at each call that omits it. It is
evaluated in the module that declares the function and can't see the
caller's local variables, so a name in it means the same thing at every
call site. Methods and [interface methods](types.md#interfaces) take
defaults the same way. A default must have its parameter's type, like an
argument. A function's or method's default is checked where it is
declared, so `func f(x: int64 = "a")` is an error even if no call leaves
`x` out; an interface method's default is checked at each call that leaves
it out.

## Argument types

Each argument must have its parameter's type: `print(5)` is an error
(`` expected `str`, got `int64` ``), and so is passing a `Gen[int64]` where
a `Gen[str]` is declared, or an `int64?` where an `int64` is. The only
implicit conversions are the ones an annotated `let` makes (see
[Bindings and mutability](types.md#bindings-and-mutability)):

- a `T` becomes a `T?`;
- a struct, `int64`, `str` or `bool` becomes an interface value;
- `.Variant` and `Enum.Variant(...)` are built for the parameter's enum;
- an array literal or `+` chain is built for an array of enums,
  interfaces, optionals or arrays.

An array value is never converted element by element. With
`func take(anon xs: [Shape])`, `take([Sq(s: 1)])` is fine, but passing a
`[Sq]` variable is an error. The same rules apply to extern functions, to
calls through a function value, and to the arguments of a method, an
interface method and `x?.method(...)`.

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

`main` can also return `int64 or Error`, directly or through an alias. A
returned value is the exit status, and an error that reaches the end of
`main` prints `panic: <message>` and exits with status 1.

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

An indirect call has the function type's return type wherever the
function value comes from: a local, an array element (`fs[i](x)`), a
struct field (`h.fn(x)`) or another call (`get_fn()(x)`). It must pass
exactly as many arguments as the function type has parameters, since a
function type carries no defaults.

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
