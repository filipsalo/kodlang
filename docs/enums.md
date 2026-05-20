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

## Construction

```kod
let d: Direction = Direction.North
let m: Message = Message.Text(content: "hello")
let q: Message = Message.Quit
```

## Implicit variant syntax

Inside a `match` arm, the enum name can be omitted when the type is unambiguous:

```kod
match d {
    .North -> print("north")
    .South -> print("south")
    _ -> {}
}
```

Unit variants can also use the implicit `.Variant` form in expressions:

```kod
let d: Direction = .North
```

Payload variants always require the explicit form at construction time.

## Pattern matching

```kod
match m {
    Message.Quit -> print("quit")
    Message.Text(content) -> print(content)
    Message.Move(x, y) -> {
        print_int(x)
        print_int(y)
    }
    _ -> {}
}
```

- Bindings in payload patterns (`content`, `x`, `y`) capture the field values
- `_` is a wildcard that matches anything
- Arm bodies can be a single expression (after `->`) or a block (`{ ... }`)
- No exhaustiveness checking yet

## Memory layout (compiler)

```
[ offset 0  ] discriminant : int64  (8 bytes)
[ offset 8  ] payload      : max(variant payload sizes) bytes
```

Variants are assigned discriminants in declaration order starting from 0.

### Example: `Message`

```
Message.Quit  → discriminant 0, no payload
Message.Text  → discriminant 1, content at payload offset 0  (8 bytes)
Message.Move  → discriminant 2, x at offset 0, y at offset 8 (16 bytes)
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

## Current limitations

- No nested patterns (e.g. `Shape.Rect(w, 0)` matching on a specific field value).
- No guard clauses on match arms.
