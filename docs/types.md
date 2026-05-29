---
icon: lucide/layers
---

# Types

Kod is statically typed. Every variable and parameter requires a type annotation.

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

Arithmetic operators: `+`, `-`, `*`, `/`, `%`. Compound assignment
`+=` and `-=` update a variable, field, or array element in place
(`n -= 3` is `n = n - 3`).

## Boolean literals

```kod
let flag: bool = true
let other: bool = false
```

Logical operators: `and`, `or`, `not` (prefix). Comparison: `==`, `!=`, `<`, `<=`, `>`, `>=`.

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
match y {
    Some(v) -> print_int(v)
    none -> print("nothing")
}
```

Or peel off the `Some` with `let .Some(v) = y else { ... }`:

```kod
let .Some(v) = y else { return -1 }
// v is in scope and has type int64
```

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

## Fallible types: `T or Error`

A function declared `-> T or Error` returns a `Result` cell — either an `Ok(T)` or an `Err(Error)`. Use `try` to propagate, `must` to panic, or pattern-match the result directly.

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
