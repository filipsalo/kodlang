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
parameter, the label can be shortened to a leading `:`:

```kod
let name: str = "Alice"
greet(:name)          // shorthand for greet(name: name)
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

Each parameter binds a name of its own, `self` included, so two parameters
can't share one: `func f(anon a: int64, b a: str)` is an error
(`` parameter `a` is declared twice; give one of them another name ``). The
same holds for methods, interface methods, externs and function literals.

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
`kod_panic`, or a local function value of that name in force at the
call, hides the builtin (see [Built-ins](builtins.md)). So a helper that
ends in `kod_panic(...)` never returns, and nor does one that ends in a
call of another such helper (`self.fail(msg)`, `log.die(msg)`, or a
function declared further down), or in a `for true` loop it can't `break`
out of. A call that leads back to the function itself doesn't count:
`func spin() -> none { spin() }` is taken to return.

A local's type can change between its bindings, so a call never
returns only when what it calls doesn't depend on such a type: the builtin
`kod_panic`, a function of the module or one it imports (`die(msg)`), a
function of an imported module (`log.die(msg)`), or a method whose
receiver's type depends on no local but `self` and parameters that no
`let` or let-else in the body binds again (`self.fail(msg)`,
`self.log.fail(msg)`, `r.fail(msg)` for such a parameter `r` of a
struct type, `reporter().fail(msg)`, and `make(t).fail(msg)` or
`self.reps[i].fail(msg)` even for locals `t` and `i`, since the type of
the receiver doesn't depend on them). A method whose receiver's type
depends on any other local is taken to return, whether a `let`
(`let r = Reporter(); r.fail(msg)`), a match arm, `if … is`, let-else or
`for` binds it, and a parameter that the body binds again counts as such
a local. So is a plain call of a name that such a local has at that
point, even when it doesn't hold a function (`kod_panic(msg)` after
`let kod_panic = 5`). To end the path there, put a `kod_panic(...)` or a
`return` after the call.

A call in a value's place, as a returned value, a match arm's value or an
`x? or ...` default, is decided where it is written, from the type its
receiver has there, so `return r.fail(msg)` never returns after
`let r = Reporter()`. What it calls is still decided by the rules above:
`return die(msg)` is an error when `die` ends in `r.fail(msg)` on such a
local, and the error names that call and its line
(`` as `die` ends in `r.fail(msg)` (line 19) ``, or
`` (line 19 of lib/log.kod) `` when the call is in another module) and
says to put a `kod_panic(...)` after it. The `can reach its end` error names it too
when the body ends in such a call, or in a call through a local of its
own. A method called through an interface value is taken to return
wherever it is called, since the method that runs is chosen at run
time: call it as a statement and end the path with `kod_panic(...)`.

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

A function literal, `func(anon n: int64) -> int64 { return n + 1 }`, is
a value of its function type too. It doesn't see the locals of the
function it's written in, since there are no closures yet.

A bare identifier in value position resolves to the function's address
when no local of that name is in force there. A call `f(args)` goes to a
struct named `f` first, so `Pt(x: 1)` constructs even where a local
named `Pt` is in force. Otherwise it does an indirect `blr` when the
innermost binding of `f` in force holds a function value, and a direct
`bl` of the module's, an imported or the builtin function named `f` when
no binding of `f` is in force or it holds anything else. A function value
declared in a block, such as an `if` or loop body, is called that way
only from its `let` to the end of the block, and after the block `f(args)`
calls an outer function value of that name again. Elsewhere `f(args)`
calls the module's or an imported function, or the builtin, named `f`,
and `f` as a value is that function; with none of those it is an error:
`` `f` is declared in a block that has ended `` after the block, and
`` `f` is called before its `let` `` (or `` read ``) before the
declaration (see [Blocks and bindings](control-flow.md#blocks-and-bindings)
and [Built-ins](builtins.md)).

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
