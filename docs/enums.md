---
icon: lucide/tag
---

# Enums

Enums in Kod are tagged unions — each value carries a discriminant identifying which variant it is, plus an optional payload with named fields.

## Declaration

```kod
type Direction = enum {
    North
    South
    East
    West
}

type Message = enum {
    // unit variant (no payload)
    Quit
    // payload variants
    Text(content: str)
    Move(x: int64, y: int64)
}
```

Comments are allowed inside the body. Variants without parentheses are *unit variants*; variants with parentheses carry named fields.

A payload field can name the enum itself, e.g. `Branch(kids: [Tree])` inside `type Tree = enum { ... }`.

## Construction

```kod
let d: Direction = Direction.North
let m: Message = Message.Text(content: "hello")
let q: Message = Message.Quit
```

The annotation is optional: a constructor has the enum's type, so
`let m = Message.Text(content: "hello")` (or `mod.Enum.Variant(...)` for
an imported enum) can be matched without an `else` arm.

Payload values go in declaration order, labelled or not:
`Message.Move(x: 1, y: 2)` and `Message.Move(1, 2)` are the same value. A
missing or extra payload value, a label that isn't the field in that
position, and a variant the enum doesn't declare (`Message.Txt`) are errors.
Each payload value must have its field's type, with the same implicit
conversions as a [function argument](functions.md#argument-types):
`Message.Text(content: 5)` is an error (`` expected `str`, got `int64` ``).

## Implicit variant syntax

Inside a `match` arm, the enum name can be omitted when the type is unambiguous:

```kod
match d {
    .North -> print("north")
    .South -> print("south")
    else -> {}
}
```

The variant must belong to the subject's enum: `.Up` in a `match` on a
`Direction` that has no `Up` is an error, even when another enum declares
`Up`, and so is naming that other enum, `Arrow.Up`. The same goes for an
`if d is ...` pattern.

Unit variants can also use the implicit `.Variant` form in expressions:

```kod
let d: Direction = .North
```

A payload variant can use it too. Wherever the enum type is known, the
variant belongs to that enum: an annotated `let`
(`let m: Message = .Text(content: "hi")`), an assignment to a variable,
field, element or key, an argument, a struct field, an array element, an
array literal in a `+` chain with an array of the enum (`ms += [.Quit]`,
`[.Quit] + ms` or `[.Quit] + [.Text(content: "a")] + load()`), a return
value (the `T` of a `T or Error` function too), the other side of `==` or
`!=` (`m == .Quit`), in a comparison chain too (`.Quit == m == n`), or an
arm of a `match` whose value goes to one of these
(`d == match n { 0 -> .North else .South }`). Elsewhere, as in an
unannotated `let`, a `match` subject, an unannotated array literal or a
method call on the variant, it belongs to the one enum that declares a
variant of that name among those the module sees: its own, those of the
modules it imports and the builtin ones. When several of them declare it,
that is an error:

```kod
type Figure = enum {
    Square(side: int64)
    Circle(r: int64)
}

type Shape = enum {
    Circle(r: int64)
    Rect(w: int64, h: int64)
}

let s = .Circle(r: 2)
// error: `.Circle` is ambiguous: `Figure` and `Shape` both declare it;
// write `Shape.Circle` or give the value a type
```

`let s: Shape = .Circle(r: 2)` and `Shape.Circle(r: 2)` both work. The
error writes an imported enum through its import alias, as in
`geo.Shape`. It suggests an enum whose variant takes the payload written
(a unit variant for a bare `.Circle`), preferring the module's own enum
when several do. Enums of modules a module doesn't import don't count, so
a generic method or a default written in an imported module means the
same variant whichever program uses it. Only when none of the enums the
module sees declares the variant does an enum of another loaded module
count. When several of those do, the module can't write any of them, so
the error only suggests giving the value a type, as by passing it straight
to a parameter of its enum.

In a `T or Error` function, a returned `.Ok(...)` or `.Err(...)` is the
result's own variant, unless `T` declares a variant of that name whose
payload fits what is written and the result's doesn't. With
`type Status = enum { Ok  Failed(code: int64) }`, `return .Ok` in a
`-> Status or Error` function returns `Status.Ok`, while
`return .Ok(.Failed(code: 1))` returns the result's `Ok`. When both
variants take the one argument written, its type decides: with
`Ok(n: int64)` in `Status`, `return .Ok(5)` returns `Status.Ok(n: 5)`, as
5 can't be a `Status`. An arm of a returned `match` works the same way,
and so does a return type that names the `T or Error` through an alias.

## Generic enums

Type parameters go in square brackets after the name, as for structs, and
each instantiation is monomorphised:

```kod
type Either[L, R] = enum {
    Left(value: L)
    Right(value: R)
}

let e: Either[int64, str] = .Left(value: 1)
```

A variant of a generic enum needs its type arguments from where it goes:
an annotated `let`, as above, or any other place listed above where the
enum type is known, such as an argument, an array element or the other side
of `==`. Without one,
`let e = Either.Left(value: 1)` (or `.Left(value: 1)`, `Result.Ok(5)`) is an
error, ``cannot infer the type of `e`; add a type annotation``. Type
arguments on the enum name, `Either[int64, str].Left(value: 1)`, are an
error, since type arguments must be followed by `(`. A pattern names the
enum without them, and its bindings take the matched value's payload
types: on an `Either[int64, str]`, `Either.Left(n)` binds an `int64`.

## Pattern matching

```kod
match m {
    Message.Quit -> print("quit")
    Message.Text(content) -> print(content)
    Message.Move(x, y) -> {
        print_int(x)
        print_int(y)
    }
    else -> {}
}
```

- Bindings in payload patterns (`content`, `x`, `y`) capture the field values
- `else` is the catch-all arm; matches whatever the other arms didn't
- Arm bodies can be a single expression (after `->`) or a block (`{ ... }`)

## Memory layout (compiler)

```
[ offset 0  ] discriminant : int64  (8 bytes)
[ offset 8  ] payload      : max(variant payload sizes) bytes
```

Variants are assigned discriminants in declaration order starting from 1.
Discriminant 0 is reserved as the `none` sentinel.

### Example: `Message`

```
Message.Quit  → discriminant 1, no payload
Message.Text  → discriminant 2, content at payload offset 0  (8 bytes)
Message.Move  → discriminant 3, x at offset 0, y at offset 8 (16 bytes)
```

Total size: 8 (discriminant) + 16 (max payload) = **24 bytes**.

## Equality

Two enum values are equal if and only if they are the same variant. Payload contents are not compared.

```kod
Direction.North == Direction.North  // true
Direction.North == Direction.South  // false
```

In the compiler this is a single integer comparison on the discriminant.

Since payloads aren't compared, an enum with payload variants only compares
with a variant that has none: with `m: Message`, `m == .Quit` and
`m != Message.Quit` are fine, but `m == .Text(content: "hi")` is an error
that suggests `m is .Text(content)` instead, and so is comparing two
`Message` values (`a == b`); test them with `is` or `match`. Comparing
values of two different enums is an error, and so is a `.Variant` that the
other side's enum doesn't declare.

## `match` as an expression

A match can produce a value when every arm body is an expression:

```kod
let label: str = match d {
    .North -> "north"
    .South -> "south"
    .East  -> "east"
    .West  -> "west"
}
```

Payload bindings are in scope in the arm's expression:

```kod
let dist: int64 = match m {
    .Move(x, y) -> x + y
    else 0
}
```

## Current limitations

- No nested patterns (e.g. `Shape.Rect(w, 0)` matching on a specific field value).
- No guard clauses on match arms.
