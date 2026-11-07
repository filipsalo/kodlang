---
icon: lucide/layers
---

# Types

Kod is statically typed. Every parameter needs a type annotation; a `let`
without one takes the type of its value.

Naming a type that doesn't exist is an error wherever a type is written:
an annotation, a parameter or return type, a struct field, an enum payload,
an alias target or a type argument. The error carries a did-you-mean hint
when a known type name is close.

An unannotated `let` takes the type of its value. If the compiler can't
work out that type, the binding is an error
(``cannot infer the type of `x`; add a type annotation``), and so is any
other use of such a value, like a `match` subject or an argument. A value
whose type is unknown because of an earlier error, such as a call to an
unknown function or method, a misspelled field, an unknown variant or an
unknown type, doesn't produce further errors where it's used.

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

Mutability belongs to each binding. A `let x` in a block that hides an
outer `mut x` (see [Blocks and bindings](control-flow.md#blocks-and-bindings))
can't be reassigned inside that block, and after the block the outer `x`
can be again. Likewise a `mut x` in a block leaves an outer `let x`
immutable once the block ends. A `for` variable and the names a pattern
binds, in a `match` arm, `if … is` or a let-else, can be reassigned
without `mut`, whatever binding the name had in another block.

Assigning to a name that was never declared is an error too (declare it
with `mut` first), and so is assigning to anything other than a name, a
field (`p.x = 1`) or an element (`xs[0] = 1`).

The value of an annotated `let`, of an assignment to a name and of an
assignment to a field must have the declared type: `let x: int64 = "s"` is
an error (`` expected `int64`, got `str` ``), and so is storing an `int64` in
a `bool` or an `[int64]` in a `[str]`. A `T` is accepted where a `T?` is
declared and is checked as a `T`: with `type Words = [str]`,
`let w: Words? = []` is fine and `let w: Words? = [1]` reports the element
(`` expected `str`, got `int64` ``), while `let x: int64? = "s"` names the
declared type (`` expected `int64?`, got `str` ``). `none` is accepted
wherever an optional or `none` is declared, a struct or primitive other
than `bytes` where an interface is, and `[]` as any array type. A `T?`
isn't accepted where a `T` is declared; unwrap it first with `x?` or
`x? or default`. An optional is passed on as it is, so a `T?` where a `U?`
is declared needs `T` to be `U`: like an `[Sq]` isn't a `[Shape]`, an
`Sq?` or `int64?` isn't a `Shape?` even when `Sq` and `int64` implement
`Shape`; rewrap it instead, as in
`match sq { Some(v) -> v none -> none }`. A function value
must match a function type exactly, since a function is never adapted: a
function taking a struct isn't a `func(SomeInterface) -> ...`, and one
returning `int64` isn't a `func() -> int64?`. Without an annotation,
`let x = none` and `let xs = []` are errors, since their type can't be
inferred.

Function and method arguments, struct constructor fields and enum payloads
are checked the same way (see [Argument types](functions.md#argument-types)),
so `m.set(5, 1)` on a `Map[str, int64]` is an error. So are element stores
(`xs[i] = v`, `m[k] = v`, see [Indexing](arrays.md#indexing)) and `return`
values (see [Return values](functions.md#return-values)).

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


## Module-level constants

A `let` at the top level of a module names a constant. It needs a type, and `mut`
isn't allowed there:

```kod
let MAX_BLOCK: int64 = 65535
let SECONDS_PER_DAY: int64 = 24 * 60 * 60
let GREETING: str = "hello, " + "world"
let PRIMES: [int64] = [2, 3, 5, 7]
let DEFAULT_MODE: Mode = Mode.Fast
```

The value is built only from literals, operators, array literals, enum variants
without a payload, and other constants. A call, a constructor, an f-string, a `match` or
anything else is an error (``this can't be part of a module-level constant``), so a
constant never has a side effect, and a constant that refers to itself, directly or through
others, is an error (``constant `A` refers to itself``).

A constant is used by its name. Another module's is `import "limits" { MAX_BLOCK }` or
`limits.MAX_BLOCK`, like a function's. A local variable or parameter of the same name hides
it, as it does a function, and a constant and a function can't share a name in one
module. A constant can't be assigned.

The value is worked out at each use, like a [default](functions.md#default-values), so an
array constant is a new array every time, and nothing is shared between uses.

## Primitive types

| Type | Description | Example |
|------|-------------|---------|
| `int64` | 64-bit signed integer | `42`, `-7` |
| `float64` | 64-bit IEEE 754 float, see [Floating point](floats.md) | `1.5`, `2e9` |
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
let bad: int64 = 1 23 456       // error — `23 456` isn't a group of 3, so it's another literal
```

A literal must fit in `int64`, in any base: `9223372036854775808` or
`0x8000000000000000` is an error at the literal, not a value that wraps
around. The one exception is the smallest `int64`, written as a prefix `-`
and its digits, with or without a space between them:
`-9223372036854775808` or `- 9223372036854775808`. In
`x - 9223372036854775808` the `-` subtracts, and in
`-9223372036854775808.to_str()` it negates the call, so in both the literal
stands alone and is an error; the second suggests `(-9223372036854775808)`.

Arithmetic operators: `+`, `-`, `*`, `/`, `%`. Compound assignment
`+=` and `-=` update a variable, field, or array element in place
(`n -= 3` is `n = n - 3`). An assignment binds looser than every
operator, so `ok = a and b` assigns `a and b`. A prefix `-` negates the whole call, field
access, index or `?` after it, and binds tighter than any binary
operator: `-xs[0]` is `-(xs[0])`, `-p.get()` is `-(p.get())`, and
`-a * b` is `(-a) * b`. That includes an unwrap's default, so `-x? or 3`
is `-(x? or 3)` and gives `-3` for a `none`. It also makes `-n.to_str()`
the negation of a `str`, an error whose hint suggests `(-n).to_str()`.

## Boolean literals

```kod
let flag: bool = true
let other: bool = false
```

Logical operators: `and`, `or`, `not`. Comparison: `==`, `!=`, `<`, `<=`, `>`,
`>=`. Comparisons, `and`/`or`/`not` and `is` always produce a `bool`, so
`let ok = a < b` is a `bool` binding and `f"{a < b}"` prints `true` or `false`.

`not` binds looser than comparisons and `is`, and tighter than `and` and `or`:
`not a == b` is `not (a == b)`, `not x is .Red` is `not (x is .Red)`, and
`not a and b` is `(not a) and b`. Its operand must be a `bool`; test an optional
with `x is none`.

`bool` and `int64` don't mix, and nothing else stands in for a `bool`. Both
operands of `and` and `or` must be `bool`, and so must the condition of an
`if`, a `for` loop and an `assert`: test a number with `n != 0` and an
optional with `x is not none`. Arithmetic, bitwise and ordering operators
don't take `bool` operands, and `==`/`!=` compare a `bool` only with
another `bool`, so `b == 1`, `true + 1` and `if flags & 1` are errors.
Comparisons bind tighter than `&`, `|` and `^`, so a bit test is written
`(flags & 1) != 0`.

Chained comparisons are supported Python-style: `a < b < c` is `(a < b) and (b < c)` with `b` evaluated once. The operands are evaluated left to right, and a chain stops at the first comparison that is false, so in `a < b < f()` `f` isn't called when `a < b` is false. Any comparison chain works — `0 <= i < len(xs)` is the canonical bounds check.

## Operators

An operator never converts its operands; both must be of a type it takes,
and of the same type:

| Operator | Operands | Result |
|----------|----------|--------|
| `+` | two `int64`, two `float64`, two `str`, two `bytes` or two arrays of one type | the operands' type |
| `-` `*` `/` | two `int64` or two `float64` | the operands' type |
| `%` | two `int64` | `int64` |
| `&` `\|` `^` `<<` `>>` | two `int64` | `int64` |
| `<` `<=` `>` `>=` | two `int64`, two `float64`, two `str` or two `bytes` | `bool` |
| `==` `!=` | two `int64`, two `float64`, `bool`, `str` or `bytes`, two values of a payload-free enum, an enum value and a unit variant, or an optional and `none` | `bool` |
| `and` `or` | two `bool` | `bool` |

So `"n = " + 5` is an error (`` cannot add `str` and `int64` ``); write
`"n = " + str(5)` or `f"n = {5}"`. `s - t` on two strings, `xs * 2` on an
array, `-s` on a string, `s + b` with `b: bytes` and `red < blue` on an enum
are errors too. `+=` and `-=` follow the rules of `+` and `-`. An index,
as in `xs[i]`, `s[i]` and `xs[i] = v`, and the bounds of a slice must be
`int64`, so `xs["a"]` and `xs[true]` are errors, and so is an `int64?`
index; unwrap it first.

`==` and `!=` compare `str` and `bytes` by content and enums by variant (see
[Equality](enums.md#equality)). Nothing else has an `==`: comparing two
structs, arrays, interface values or function values is an error, so
compare a struct's fields, or an array's `len(...)` and elements, instead.
Comparing values of two different types, like an `int64` with a `str` or
values of two different enums, is an error too.

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

The `?` goes after the whole type, so `[str]?` is an optional array and
`Box[int64]?` an optional generic struct. `names? or []` is the array, or an
empty one when there is none.

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

`is` and `is not` bind like comparisons, tighter than `and` and `or`, so
`if ready and x is none` reads as `ready and (x is none)`. A pattern that
binds a name, like `Some(v)`, only works when the `is` is the whole `if`
condition: `if a and x is Some(v)` is an error, since `v` would be unset
when `a` is false. `Some(_)` or `Some(_v)` binds nothing and works anywhere.

Or peel off the `Some` with `let .Some(v) = y else { ... }`:

```kod
let .Some(v) = y else { return -1 }
// v is in scope and has type int64
```

An optional can hold another optional, as `MaybeInt?` does with
`type MaybeInt = int64?`. An `int64?` that goes where a `MaybeInt?` is
expected becomes its value, the way an `int64` becomes the value of an
`int64?`, so a `none` `MaybeInt?` means there is no `int64?` at all. A
`Map[str, int64?]`'s `get` returns such an optional: `none` for a missing
key, and `Some(v)` for a stored value, where `v` is `none` if `none` was
stored.

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
its type must match the unwrapped `T`, unless it's a call that never
returns, such as `kod_panic(...)` or a helper that ends in one
(see [Return values](functions.md#return-values)).
It's built as a `T`: with `T` an interface, a struct default becomes an
interface value, and with `T` an enum, `.Up` names `T`'s variant. `x?` on
a value that isn't optional is an error. A following `or` outside the
unwrap stays a boolean operator: `x? or 1` substitutes 1 for none, but
`(x?) or some_bool` is a boolean-or on the unwrapped value (and a type
error unless `T` is `bool`).

Operators don't look inside an optional. With `n: int64?`, `n == 3`,
`n < 4` and `n + 1` are errors, and so is comparing a `bool?` such as
`m.get(key)` with `true`; unwrap first, as in `n? == 3` or
`(n? or 0) + 1`. Only `== none` and `!= none` compare the optional itself.

### Optional chaining

On a struct `T?`, `x?.field` and `x?.method(...)` evaluate to an optional
of the field or return type, and to `none` without touching the field
when `x` is `none`. `x?.method(...)` takes arguments like an ordinary
method call: arguments it leaves out take the method's
[defaults](functions.md#default-values), and none of them is evaluated
when `x` is `none`. A `T?` doesn't stand in for a `T`: returning `t?.name`
from a function declared `-> str` or `-> str or Error` is an error, so
unwrap it first with `t?.name?` or `t?.name? or ""`, or declare the
function `-> str?`. `t?.name = v` isn't an assignment; unwrap first, as in
`if t is Some(u) { u.name = v }`.

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
is an error that says to write `Pair[A, B](...)`. A generic struct's method
signatures are always checked, but a method body is compiled only for each
instantiation, so the body of a struct that nothing instantiates isn't
checked. An error in a body is reported once, for the first instantiation
that hits it, and names that instantiation, like `Pair[str, int64]`.
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

Functions can be generic too, with their type arguments usually inferred from
the call: see [Generic functions](functions.md#generic-functions).

## Interfaces

Method-based contracts that types can opt into by declaring the right methods. Primitives implement them implicitly via boxing.

```kod
interface Printable {
    func to_str(self) -> str
}

func show(anon x: Printable) -> none {
    print(x.to_str())
}

show(42)        // works — int64 implements Printable via primitives/int64.kod
show(true)      // same for bool
```

A call on an interface value must name one of the interface's methods,
with arguments that match its signature; an unknown method is an error. A
trailing argument the call leaves out takes the default the interface
declares for it (`func greet(self, times: int64 = 2) -> str`), so give
each implementation the same default.

A struct, `int64`, `str` or `bool` becomes an interface value wherever one
is expected (a `bytes` value can't be one):
an annotated `let`, an argument, a field, an array element, a value stored
with `m[k] = v`, and a return value, including the value of a `-> Shape?`
or `-> Shape or Error` function.

The type must declare every method of the interface, with the same
parameter and return types (labels and defaults may differ). Otherwise
using it as the interface is an error at that spot, such as
``struct `P` doesn't implement interface `Shape`: missing method `area` ``
or ``method `area` is `func(int64) -> int64`, not `func() -> int64` ``.
`throw` counts too, since it makes its value an `Error`.

An interface value converts to another interface that declares only methods
the first one has, with the same parameter and return types, in any order. It
goes wherever a struct would (an argument, an annotated `let`, a field, a
return value), and a downcast still works on the result:

```kod
interface Reader {
    func read(self) -> int64
}
interface ReadCloser {
    func close(self) -> none
    func read(self) -> int64
}

func drain(anon r: Reader) -> int64 {
    return r.read()
}

let rc: ReadCloser = File(n: 7)
drain(rc)                      // 7
let r: Reader = rc
if r is File(f) {              // still the File
    print_int(f.n)
}
```

Converting builds the new interface's method table when it runs, so it costs a
small allocation. Arrays and optionals of interface values don't convert
element by element: a `[ReadCloser]` is not a `[Reader]`.

## Union types

`A | B` holds a value of any one of its member types. A `match` or `is` says
which one it holds:

```kod
type Id = int64 | str

func show(anon id: Id) -> str {
    match id {
        n: int64 -> return f"#{n}"
        s: str -> return s
    }
}

let id: Id = 42
if id is s: str {
    print(s)
}
```

A member can be any type: a primitive, a struct, an enum, an interface, an
array, a generic instance or a function type. See
[Pattern matching](pattern-matching.md#union-member) for the patterns.

A union is a set, so order, repeats and nesting don't matter. `int64 | str` and
`str | int64` are one type, in every module, and with `type Id = int64 | str`,
`Id | bool` is `int64 | str | bool`. A union with only one member left is that
member.

`none` in a union makes it optional: `T | none` is exactly `T?`, and
`A | B | none` is the optional of `A | B`. An optional member counts the same
way, so `A? | B` is that type too.

In a type, `|` binds tighter than `or`, so `int64 | str or Error` is a fallible
`int64 | str`. A function type's return type takes every member after the `->`,
so `func() -> int64 | str` returns a union. To put such a function in a union,
give its type an alias first.

A value goes into a union by being written where the union is declared, as a `T`
goes into a `T?`. It goes to the member of its own type. Without one, a struct or
primitive goes to an interface member it implements, and implementing two of them
is an error, since it could be either. An enum's `.Variant` goes to the one enum
member that declares that variant, and `[]` to the one array member. A value with
no member reports the mismatch (`` expected `int64 | str`, got `bool` ``).

A union is passed on as it is, so an `A | B` isn't accepted where an `A | B | C`
is declared, as an `[Sq]` isn't a `[Shape]`. Match it and put the member in the
other union instead. Nor is a union accepted where one of its members is declared.

A union has no fields, methods or operators of its own, so `==`, printing and
`f"{x}"` need a `match` first, and a union can't be a `Map` key. A union can't
mention a type parameter, except as `T | none`, since `T | str` would have only
one member when `T` is `str`. A union alias can't refer to itself, so a recursive
type such as a JSON value is still an [enum](enums.md).

## Type aliases

`type Name = T` gives an existing type a second name. An alias is
transparent: a value of the alias type is a value of `T`, with all of its
methods, fields and operators. The target can be any type, including one
declared further down the module or one from the module's own imports
(`type Num2 = dep.Num`, usable as `mid.Num2` from a module that imports
only `mid`, or `type Num = dep.Num` to pass the name on as `mid.Num`).
Each module's aliases are its own: two modules may declare aliases of one
name whether or not they stand for the same type, and a module's alias may
take the name of a struct, enum or interface another module declares (see
[Modules](modules.md#where-names-resolve)):

```kod
type Name = str
type Ids = [int64]
type MaybeNode = Node?
type Callback = func(int64) -> int64
type StrMap = Map[str, str]
type Outcome = int64 or Error
type Key = int64 | str

type Node = struct {
    label: str
}

let n: Name = "kod"
print_int(n.char_count())    // 3
```

An alias of `T or Error` works wherever `T or Error` does, including as the
return type of a function or of `main`, so `throw`, `try` and `must` behave
the same through it. That holds for an imported alias too, written
`dep.Outcome` or listed in `import "./dep" { Outcome }`.

An alias whose target names an unknown type is an error, and so is one that
refers back to itself through other aliases (`type A = B` with `type B = A`).
So is a target that gets a generic's type arguments wrong, such as
`type B = Map[str]`, `type P = Pair` or `type D = [Box[int64]]` for a `Box`
that isn't generic. Each of these is reported once, at the alias.

## Fallible types: `T or Error`

A function declared `-> T or Error` returns a `Result` cell — either an `Ok(T)` or an `Err(Error)`. Use `try` to propagate, `must` to panic, or pattern-match the result directly.

`try` and `must` take a `T or Error` value, and `try` only works inside a
function that returns `T or Error` itself; anything else is an error. Either
can appear anywhere a value can, as in `out += [try parse(s)]` or
`xs[try first(xs)..]`; on an `Err`, `try` returns from the function there. An
explicit `Result[T, E]` with an `E` other than `Error` doesn't count, since
its error isn't an `Error` to report or pass on; match it instead.

A call whose result is a `T or Error` can't be used as a statement on its own, because
that would drop an error without a word:

```kod
file.close()               // error: the `none or Error` result of this call is dropped
try file.close()           // propagate it
must file.close()          // panic on it
let _ = file.close()       // ignore it, on purpose
```

`let _ = expr` evaluates `expr`, whatever its type, and keeps nothing: it binds no
name, so it can be written any number of times in a block, and `_` can't be read
afterwards. It is for fallible calls whose failure doesn't matter, like closing a
connection that already failed. Any other value can be dropped by calling it as a
statement, as before.

A `none or Error` function that ends without a `return`, or with a bare
`return`, returns `Ok(none)`, as `return none` does.

Outside a fallible function's `return`, a plain value isn't a result:
`let r: int64 or Error = 3` is an error, and
`let r: int64 or Error = .Ok(value: 3)` is a successful result.

`Error` is the only type that can follow `or`: `-> int64 or IoError` is a
parse error. Throw a struct that implements `Error` instead, and recover it
with a downcast (see below). `throw` takes an `Error` value, so throwing an
enum, an array or an optional is an error, such as
``expected `Error`, got `Color` ``.

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
has the result's value type; `Err`'s is the `Error` interface (on an
explicit `Result[T, E]`, it's an `E`):

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
`x is T` and a `T(b)` pattern hold only for a value of exactly that
declaration, or that generic instance, whichever module boxed it, so an error
struct that an imported function throws matches its type in the caller. `T`
may be an alias of a struct or of a generic instance
(`type IntBox = Box[int64]`), written `dep.T` through another module. Naming
a generic type itself (`is Box`) is an error:
`` `Box` is generic; downcast to one of its instances through a type alias such as `type IntBox = Box[int64]` ``.
The pattern names such a struct through its module (`e is errs.NotFound(nf)`,
which needs `errs` to declare `NotFound`) or, when it is imported as an item,
by its own name (`e is NotFound(nf)`). Either way it binds one name, the
struct, whose fields are read from it. A local or parameter named like the
module hides it, so `errs.NotFound(nf)` after `let errs = 3` is an error.
