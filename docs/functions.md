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

Every argument is passed in a register, so a function can take at most 8
parameters. `self` takes one of them, so a method or interface method can
take at most 7 besides `self`. The same limit holds for externs, function
literals and function types such as `func(int64) -> int64`, in a type alias
too; going past it is an error where the function, literal or type is
written (`` `f` takes 9 parameters, but a function can take at most 8 ``),
not again at each call through it. When that is in another module, the
error is reported at each call through it instead. To pass more, group
them in a struct.

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

Labeled arguments go in parameter order: with `func move(x: int64, y: int64)`,
`move(y: 2, x: 1)` is an error
(`` parameter 0 of `move` expected label `x`, got `y` ``).

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
argument. A function's or method's default has its type checked where it
is declared, so `func f(x: int64 = "a")` is an error even if no call leaves
`x` out. Anything else wrong in it, such as an unknown name or variant, or
a wrong field in a constructor, is reported where a call leaves it out, and
an interface method's default is checked only at each call that leaves it
out.

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

## Return values

A returned value must have the function's return type, with the same
conversions as an argument: `func f() -> str { return 5 }` is an error
(`` expected `str`, got `int64` ``), and so is returning a `[Sq]` variable
from a `-> [Shape]` function. A `-> none` function returns no value; it
can end with a bare `return`, `return none`, or `return` of a call that
itself returns `none`. Any function can return a call that never returns
(see below), such as `return self.fail("bad")` or `return log.die("bad")`.

In a `-> T or Error` function, a returned `T` becomes a successful result.
A returned `T or Error` value must have the same `T`, so returning an
`int64 or Error` from a `-> str or Error` function is an error.

A function with a return type other than `none` must end every path with a
`return`, a `throw`, or a call that doesn't return, like `kod_panic(...)`.
One that can reach the end of its body is an error at its name, or at the
`func` of a function literal
(`` `pick` can reach its end without returning a value ``), and that
includes a `-> T?` function: write `return none` at the end. Only a
`-> none or Error` function may run off its end, which returns `Ok(none)`.
The error isn't reported for a body that already has other errors, or in
a file that doesn't parse, since those may hide the missing `return`.
Whether a path can reach the end is decided from the statements alone:

- `return`, `throw`, `break` and `continue` end a path, and so does a call
  of a function or method that never returns;
- an `if` ends every path only if it has an `else` and both branches do;
- a `match` does if each of its arms does;
- a `for true` loop does unless it can `break` out of itself; any other
  `for` loop, including `for … in`, may finish.

Code after a statement that ends every path is never run and isn't
considered, so a `break` placed after a `return` or `kod_panic(...)` doesn't
let a `for true` loop finish.

The builtin `kod_panic(...)` never returns, and neither does a function or
method that returns `none`, has no `return`, and can't reach the end of its
body by these rules. A function of the module or one it imports named
`kod_panic`, or a local function value of that name declared before the
call, hides the builtin (see [Built-ins](builtins.md)). So a helper that
ends in `kod_panic(...)` never returns, and nor does one that ends in a
call of another such helper (`self.fail(msg)`, `log.die(msg)`, or a
function declared further down), or in a `for true` loop it can't `break`
out of. A call that leads back to the function itself doesn't count:
`func spin() -> none { spin() }` is taken to return.

Blocks don't have their own scopes yet, so a local's type can change
between its bindings. Until they do, a call counts as never returning
only when what it calls doesn't depend on such a type: the builtin
`kod_panic`, a function of the module or one it imports (`die(msg)`), a
function of an imported module (`log.die(msg)`), or a method whose
receiver uses no local but `self` and parameters that no `let`, pattern,
`for` or let-else in the body binds again (`self.fail(msg)`,
`self.log.fail(msg)`, `r.fail(msg)` for such a parameter `r`,
`reporter().fail(msg)`). A method on any other local is taken to return,
whether a `let` (`let r = Reporter(); r.fail(msg)`), a match arm,
`if … is`, let-else or `for` binds it, and so is a plain call of a name
that such a local has at that point, even when it doesn't hold a function
(`kod_panic(msg)` after `let kod_panic = 5`). To end the path there, put
a `kod_panic(...)` or a `return` after the call.

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
function type declared before it, falling through to the direct `bl`
otherwise. Blocks don't have their own scopes yet, so a function value
declared in an `if` or loop body can still be called after the block
when no function is named like it.

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
