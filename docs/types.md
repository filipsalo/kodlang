---
icon: lucide/layers
---

# Types

Kod is statically typed. Every variable and parameter requires a type annotation.

Naming a type that doesn't exist is an error wherever a type is written:
an annotation, a parameter or return type, a struct field, an enum payload,
an alias target or a type argument. The error carries a did-you-mean hint
when a known type name is close.

An unannotated `let` takes the type of its value. If the compiler can't
work out that type, the binding is an error (`cannot infer the type of
`x`; add a type annotation`). A value whose type is unknown because of an
earlier error, such as a call to an unknown function or method, a
misspelled field, an unknown variant or an unknown type, doesn't produce
further errors where it's used.

## Bindings and mutability

A `let` binding is immutable: once set, reassigning the name is a compile
error. Use `mut` for a binding you need to reassign. `+=` and `-=` count as
reassignment, so they require `mut` too.

```kod
let max: int64 = 100
mut total: int64 = 0
total += max          // ok — total is mutable

max = 50              // error: cannot reassign immutable binding `max`
```

Assigning to a name that was never declared is an error too (declare it
with `mut` first), and so is assigning to anything other than a name, a
field (`p.x = 1`) or an element (`xs[0] = 1`).

Parameters are immutable too — `mut` makes one reassignable inside the
body (`mut self` for a method receiver). This is **callee-local**: params
are passed by value, so reassigning one never affects the caller, and the
call site needs no annotation.

```kod
func bump(anon mut x: int64) -> int64 {
    x = x + 1     // ok — local to bump; the caller's value is unchanged
    return x
}
```

Struct fields stay mutable. And because structs and arrays are reference
values (see [Memory layout](memory-layout.md)), mutating a struct's *fields*
through a parameter or `self` (`p.field = v`) is still allowed regardless of
whether the binding is `mut` — `mut` governs only reassigning the name.

## Primitive types

| Type | Description | Example |
|------|-------------|---------|
| `int64` | 64-bit signed integer | `42`, `-7` |
| `str` | UTF-8 string | `"hello"` |
| `bool` | Boolean | `true`, `false` |
| `none` | No value (unit type) | — |

## Integer literals

```kod
let n: int64 = 42
let m: int64 = -1
```

Base prefixes for non-decimal forms:

```kod
let hex: int64 = 0xff           // 255
let oct: int64 = 0o755          // 493
let bin: int64 = 0b1010         // 10
```

Decimal literals may use a space as a thousands separator. The
grouping is strict — a head of 1-3 digits followed by space-prefixed
groups of exactly 3 digits each:

```kod
let pop: int64 = 1 000 000      // ok
let bad: int64 = 1 23 456       // lex error — middle group isn't 3 digits
```

Arithmetic operators: `+`, `-`, `*`, `/`, `%`. Compound assignment
`+=` and `-=` update a variable, field, or array element in place
(`n -= 3` is `n = n - 3`).

## Boolean literals

```kod
let flag: bool = true
let other: bool = false
```

Logical operators: `and`, `or`, `not` (prefix). Comparison: `==`, `!=`, `<`, `<=`, `>`, `>=`.
Comparisons, `and`/`or` and `is` always produce a `bool`, so `let ok = a < b`
is a `bool` binding and `f"{a < b}"` prints `true` or `false`.

`bool` and `int64` don't mix, and nothing else stands in for a `bool`. Both
operands of `and` and `or` must be `bool`, and so must the condition of an
`if`, a `for` loop and an `assert`: test a number with `n != 0` and an
optional with `x is not none`. Arithmetic, bitwise and ordering operators
don't take `bool` operands, and `==`/`!=` compare a `bool` only with
another `bool`, so `b == 1`, `true + 1` and `if flags & 1` are errors.
Comparisons bind tighter than `&`, `|` and `^`, so a bit test is written
`(flags & 1) != 0`.

Chained comparisons are supported Python-style: `a < b < c` evaluates `b` once and is equivalent to `(a < b) and (b < c)`. Any comparison chain works — `0 <= i < len(xs)` is the canonical bounds check.

## `none`

`none` is the unit value. Functions that return nothing are declared `-> none`:

```kod
func say_hi() -> none {
    print("hi")
}
```

## Optional types

Append `?` to any type to make it optional:

```kod
let x: int64? = none
let y: int64? = 42
```

Test with `is` and destructure with `Some(binding)`:

```kod
if x is none {
    print("nothing")
}
if y is not none {
    print("got something")
}
match y {
    Some(v) -> print_int(v)
    none -> print("nothing")
}
```

`is not Pat` reads as one operator — `is` negated by the trailing
`not` — and works anywhere `is Pat` does (expression context and
the `if … is …` form). It's the predicate spelling of "does this
not match"; for the `if` form, the body runs when the pattern *does
not* match.

Or peel off the `Some` with `let .Some(v) = y else { ... }`:

```kod
let .Some(v) = y else { return -1 }
// v is in scope and has type int64
```

### Postfix `?`

`expr?` on a `T?` value evaluates to `T`. Without a trailing clause it
panics on `none`; with `or default` it substitutes the default
instead:

```kod
let n: int64? = find("hello", 'l')
let idx: int64       = n?           // panics if none
let idx2: int64      = n? or -1     // -1 if none
```

The default is evaluated lazily (only when the value is `none`), and
its type must match the unwrapped `T`. A following `or` outside the
unwrap stays a boolean operator: `x? or 1` substitutes 1 for none, but
`(x?) or some_bool` is a boolean-or on the unwrapped value (and a type
error unless `T` is `bool`).

### Optional chaining

On a struct `T?`, `x?.field` and `x?.method(...)` evaluate to an optional
of the field or return type, and to `none` without touching the field
when `x` is `none`. A `T?` doesn't stand in for a `T`: returning `t?.name`
from a function declared `-> str` is an error, so unwrap it first with
`t?.name?` or `t?.name? or ""`, or declare the function `-> str?`.

## Arrays

`[T]` is a resizable array of element type `T`:

```kod
let nums: [int64] = [1, 2, 3]
let names: [str] = ["alice", "bob"]
```

See [Arrays](arrays.md) for indexing, slicing, and concatenation.

## Structs

Named product types:

```kod
type Point = struct {
    x: int64
    y: int64
}
```

See [Structs](structs.md).

## Enums

Tagged unions:

```kod
type Shape = enum {
    Circle(radius: int64)
    Rect(w: int64, h: int64)
}
```

See [Enums](enums.md).

## Generics

Type-parametric structs are monomorphised at compile time:

```kod
type Pair[A, B] = struct {
    first: A
    second: B
}

let p: Pair[str, int64] = Pair[str, int64](first: "hello", second: 42)
```

The type arguments of a constructor call pick the instantiation, so
`let p = Pair[str, int64](first: "hello", second: 42)` needs no annotation.
A generic struct always needs them: a bare `Pair(first: "hello", second: 42)`
is an error that says to write `Pair[A, B](...)`. Only instantiations are
compiled, so a method of a generic struct that nothing instantiates isn't
checked.
A type argument is a name (`str`, `ast.Expr`), an array (`[str]`), an
optional of either (`int64?`, `[str]?`) or another instantiation
(`Map[str, Pair[int64, str]]()`). Function types (`func(int64) -> str`) and
optional instantiations (`Pair[str, int64]?`) aren't accepted. Passing the
wrong number of type arguments, or type arguments to a struct that isn't
generic, is an error, and so is a `Type[A, B]` that isn't followed by `(`.
The same goes for a generic written as a type: `let m: Map = ...` is an
error that says to write `Map[K, V]`, and `Map[str]` is one for the missing
type argument.

`Map[K, V]` (in `builtins`) is the canonical example.

## Interfaces

Method-based contracts that types can opt into by declaring the right methods. Primitives implement them implicitly via boxing.

```kod
interface Stringable {
    func to_str(self) -> str
}

func show(anon x: Stringable) -> none {
    print(x.to_str())
}

show(42)        // works — int64 implements Stringable via primitives/int64.kod
show(true)      // same for bool
```

A call on an interface value must name one of the interface's methods,
with arguments that match its signature; an unknown method is an error.

## Type aliases

`type Name = T` gives an existing type a second name. An alias is
transparent: a value of the alias type is a value of `T`, with all of its
methods, fields and operators. The target can be any type, including one
declared further down the module:

```kod
type Name = str
type Ids = [int64]
type MaybeNode = Node?
type Callback = func(int64) -> int64
type StrMap = Map[str, str]
type Outcome = int64 or Error

type Node = struct {
    label: str
}

let n: Name = "kod"
print(n.char_count())    // 3
```

A struct, enum or interface that the importing module declares wins over
a same-named alias from an imported module. An alias whose target names an
unknown type is an error, and so is one that refers back to itself through
other aliases (`type A = B` with `type B = A`).

## Fallible types: `T or Error`

A function declared `-> T or Error` returns a `Result` cell — either an `Ok(T)` or an `Err(Error)`. Use `try` to propagate, `must` to panic, or pattern-match the result directly.

`Error` is the only type that can follow `or`: `-> int64 or IoError` is a
parse error. Throw a struct that implements `Error` instead, and recover it
with a downcast (see below).

```kod
type IoError = struct {
    message: str
    func to_str(self) -> str { return self.message }
}

func read_size(anon path: str) -> int64 or Error {
    throw IoError(message: f"file not found: {path}")
}

func main() -> int64 {
    let n: int64 = must read_size("missing.txt")  // panics on Err
    return n
}
```

To inspect a result instead of propagating or panicking, pattern-match it
with `Ok` / `Err` (the two-armed analog of `Some` / `none`). `Ok`'s binding
has the result's value type; `Err`'s is the `Error` interface:

```kod
match read_size("missing.txt") {
    Ok(n)  -> print_int(n)
    Err(e) -> print(e.to_str())
}
```

The same patterns work with `if … is` and the bare `is` operator, which is
handy in tests:

```kod
let r = read_size("missing.txt")
assert r is Err(_)              // it failed
if r is Err(e) { print(e.to_str()) }
```

### Recovering the concrete error type

`Err(e)` binds `e` as the `Error` interface. To get back the concrete error
struct, downcast with `is StructType` / `is StructType(binding)` — a general
interface downcast that tests the boxed type and, on a match, binds the
typed value:

```kod
match read_size(path) {
    Ok(n)  -> use(n)
    Err(e) ->
        if e is NotFound(nf) {
            print(f"missing: {nf.path}")
        } else {
            print(e.to_str())
        }
}
```

It works in `match`, `if … is`, and the bare `is` operator (a `match` on an
interface needs an `else`, since its set of implementors isn't enumerable).
