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
(`` parameter 0 of `move` expected label `x`, got `y` ``). A label may jump over
parameters that have [defaults](#default-values), which are then left out of the call.

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

## Long calls and parameter lists

A call may be split across lines wherever the arguments are separated, and so may a
parameter list. Put each argument on its own line, with or without a trailing comma,
and comments between them:

```kod
let conn = connect(
    "example.com",
    port: 8443,        // not the default
    timeout_ms: 200,
    tls: true,
)

func request(
    anon method: str,
    anon url: str,
    timeout_ms: int64 = 5000,
) -> none { ... }
```

This holds for every call: functions, methods, `x?.method(...)`, struct and enum
constructors (`Point(x: 1, y: 2)`), and the argument lists of enum variants in a type
declaration. A line break after the callee and before the `(` still ends the statement,
so `f` and `(1)` on two lines are two expressions, not a call. A call that never closes
is reported at the first token that cannot continue it, for instance
`` expected `)`, got `let` `` on the line of the next statement.

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

A label can jump over parameters that have defaults, so that a later one can be
set without writing out the ones in between:

```kod
func connect(anon host: str, port: int64 = 80, timeout_ms: int64 = 5000, tls: bool = false) -> none { ... }

connect("example.com")                          // all defaults
connect("example.com", timeout_ms: 200)         // port and tls by default
connect("example.com", port: 8443, tls: true)   // timeout_ms by default
```

The labels still go in parameter order, and a parameter that is jumped over must
have a default; `connect(port: 1)` is an error because `host` has none
(`` parameter 0 of `connect` is anon; remove label `port` ``). An `anon`
parameter with a default can be jumped over the same way, by labeling a later
argument. Unlabeled arguments fill the parameters strictly in order, so only a
label can skip.

Each default is evaluated afresh at the call, in the order of the parameters,
along with the arguments you did give: in `f(a: x(), c: z())` for `func f(a: int64, b: int64 = y(), c: int64 = 0)`,
the calls run `x`, then the default `y`, then `z`. It works the same for
methods, [interface methods](types.md#interfaces) and functions of other modules.

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
call, hides the builtin (see [Built-ins](builtins.md)). A local named
`kod_panic` that holds anything else doesn't, so `kod_panic(msg)` after
`let kod_panic = 5` never returns. So a helper that ends in
`kod_panic(...)` never returns, and nor does one that ends in a call of
another such helper (`self.fail(msg)`, `log.die(msg)`, or a function
declared further down), or in a `for true` loop it can't `break` out of.
A call that leads back to the function itself doesn't count:
`func spin() -> none { spin() }` is taken to return.

This holds for a call of:

- a function of the module or one it imports (`die(msg)`), or a function
  of an imported module (`log.die(msg)`);
- a method of a struct, whatever it's called on: `self`, a parameter,
  any local, a field or a call's result (`self.fail(msg)`,
  `self.log.fail(msg)`, `r.fail(msg)`, `self.reps[i].fail(msg)`,
  `reporter().fail(msg)`), as long as that expression's type is known at
  the call. A local has the type of its binding in force there, whether a
  `let`, let-else, match arm, `if … is` or `for` binds it, so
  `r.fail(msg)` never returns after `let r = Reporter()`, even where `r`
  is also a parameter of another type.

Two kinds of call are always taken to return, because what they call is
chosen at run time:

- a call through a function value (a local, parameter or field of a
  function type);
- a method called through an interface value.

End such a path with a `kod_panic(...)` or a `return` after the call.

A call in a value's place, as a returned value, a match arm's value or an
`x? or ...` default, is decided where it is written by the same rules, so
`return r.fail(msg)` never returns after `let r = Reporter()`, and nor
does `return die(msg)` when `die` ends in that call. When what it calls
ends in a call taken to return, the error names that call and its line:
`return die(msg)` is an error when `die` ends in `r.fail(msg)` after
`let r: Failer = Reporter()`, for an interface `Failer`
(`` as `die` ends in `r.fail(msg)` (line 19) ``, or
`` (line 19 of lib/log.kod) `` when the call is in another module), and
it says to put a `kod_panic(...)` after it. The `can reach its end` error
names that call too when the body ends in a call of such a function, and
says so when the body itself ends in a call through a function value or
a method called through an interface value. Such a call is taken to
return wherever it is written: call it as a statement and end the path
with `kod_panic(...)`.

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

A function of an imported module is a value written through its module,
`let f = vec.dot`. A name the module doesn't declare is an error with a
did-you-mean hint (`` module `vec` has no function or constant `dott` ``).

An indirect call has the function type's return type wherever the
function value comes from: a local, an array element (`fs[i](x)`), a
struct field (`h.fn(x)`) or another call (`get_fn()(x)`). It must pass
exactly as many arguments as the function type has parameters, since a
function type carries no defaults.

## Generic functions

Type parameters in brackets after the name make a function generic. They can
be used in its parameters, its return type and its body:

```kod
func first[T](anon xs: [T]) -> T? {
    if len(xs) == 0 {
        return none
    }
    return xs[0]
}

func map_all[T, U](anon xs: [T], f: func(T) -> U) -> [U] {
    mut out: [U] = []
    for x in xs {
        out += [f(x)]
    }
    return out
}

let a = first([1, 2])                                      // a: int64?
let b = map_all([1, 2], f: func(anon n: int64) -> str {    // b: [str]
    return f"#{n}"
})
```

Like a [generic struct](types.md#generics), a generic function is
monomorphised: it's compiled once for each list of type arguments a module
calls it with.

### Inference

A call usually leaves the type arguments out, and the compiler works them out
from the arguments:

- Arguments are read in parameter order. Each one is matched against its
  parameter's declared type: `T` takes the argument's whole type, `[T]` an
  array's element type, `Box[T]` an instance's type argument, and
  `func(T) -> U` a function's parameter and return types. `T?` takes the
  inner type of an optional or else the argument's own type, so `int64?` and
  `int64` both make `T` an `int64`.
- The first argument to settle a type parameter decides it. Later arguments
  are then converted to the parameter's type as in any call, and one that
  can't be is an error at that argument. With `func pick[T](a: T, b: T)`,
  `pick(a: 1, b: "x")` reports `` expected `int64`, got `str` ``, and arguments
  of two structs that share an interface need
  [the type written out](#explicit-type-arguments), as in
  `pick[Shape](a: sq, b: circle)`.
- An argument with no type of its own (`none`, `[]`, `.Red`) settles nothing,
  but takes its type from the parameter once the others have settled it:
  with `func add[T](xs: [T], x: T)`, `add(xs: [], x: 1)` makes `T` an `int64`.
- A parameter left to its default settles nothing either.
- Only arguments count. Neither the return type nor where the result goes
  matters, so a type parameter that no argument settles is an error, even in
  `let xs: [int64] = empty()`:
  `` cannot infer `T` in the call to `empty`; write the type arguments: `empty[T](...)` ``.

### Explicit type arguments

Type arguments can be written after the function's name, all of them or none:

```kod
let xs = empty[int64]()
let c = util.first[str](names)
```

They are spelled as for a generic struct's constructor (`str`, `[str]`,
`int64?`, `Box[int64]`). The wrong number is an error, and so is giving them to
a function that isn't generic.

### Checking

There are no bounds on a type parameter: the body may do anything the type
arguments allow, and is compiled for each instance. A signature is always
checked. A body is checked only for the instances that are called, so the body
of a generic function nothing calls isn't checked. An error in a body is
reported once, for the first instance that hits it, and names that instance:

```kod
func largest[T](a: T, b: T) -> T {
    if a < b {               // with Color: `<` doesn't take `Color` operands (in `largest[Color]`)
        return b
    }
    return a
}
```

A generic function may call itself and other generic functions. The chain of
instances has to end: one that keeps making a bigger type, like `f[[T]]` inside
`f[T]`, is an error once it is 64 instances deep.

Parameter defaults and the body resolve names in the module that wrote them,
as for a [generic struct's methods](modules.md), and `T` means the instance's
type in both.

### Limits

- A generic function isn't a value until it has its type arguments, and can't
  be a value yet with them. `let f = first` and `let f = first[int64]` are
  errors. A function literal does the job:
  `func(anon xs: [int64]) -> int64? { return first(xs) }`.
- Only top-level functions can be generic. A method can use its struct's type
  parameters but can't declare its own, and neither can an interface method, a
  function literal, an extern or `main`. A module-level constant can't either.
- A function literal in a generic body can't name `T`, as in a generic struct's
  methods, because it's compiled once and not per instance.
- A type parameter's name can't repeat in one list, and hides a type of the
  same name for the length of the function.

## Extern functions

Declare external C functions with `extern`:

```kod
extern func labs(anon n: int64) -> int64     // compiled programs only
extern func putchar(anon c: int64) -> int64
```

An `extern func` is a C symbol, resolved at link time against the C runtime and whatever the modules of the program declare (see [Link inputs](modules.md#link-inputs)): `labs` is in libc, and a module can name a C file of its own or a library to link. A `str` argument reaches C as a `KodStr *`, not as a `char *`, so a libc function that takes a C string does not fit.

## Recursion

Mutual recursion between functions is supported as long as all functions are declared in the same module.

```kod
func fib(n: int64) -> int64 {
    if n <= 1 {
        return n
    }
    return fib(n - 1) + fib(n - 2)
}
```
