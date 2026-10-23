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

## Implicit variant syntax

Inside a `match` arm, the enum name can be omitted when the type is unambiguous:

```kod
match d {
    .North -> print("north")
    .South -> print("south")
    else -> {}
}
```

Unit variants can also use the implicit `.Variant` form in expressions:

```kod
let d: Direction = .North
```

A payload variant can use it too when it goes straight into an annotated
`let`, as in `let m: Message = .Text(content: "hi")`. Elsewhere, construct
payload variants with the explicit `Enum.Variant(...)` form.

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

Construct a variant with the implicit form into an annotated `let`, as
above. Type arguments on the enum name, `Either[int64, str].Left(value: 1)`,
are an error, since type arguments must be followed by `(`.

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
