---
icon: lucide/search-code
---

# Pattern matching

Kod's `match` statement dispatches on a value and binds sub-parts.

## Syntax

```kod
match <expression> {
    <pattern> -> <arm-body>
    <pattern> -> {
        // multi-statement arm
    }
}
```

Arms are tested top-to-bottom. The first matching arm executes.

## Pattern kinds

### Catch-all (`else`)

`else` matches any value the other arms didn't cover. It must be the
last arm. The arrow is optional after `else`:

```kod
match x {
    1    -> print("one")
    2    -> print("two")
    else -> print("other")    // arrow form
}

match x {
    1 -> print("one")
    else { print("other") }   // block form
}
```

### Integer literal

```kod
match n {
    0    -> print("zero")
    1    -> print("one")
    else -> print("other")
}
```

### String literal

```kod
match s {
    "hello" -> print("greeting")
    "bye"   -> print("farewell")
    else    -> print("unknown")
}
```

### Bool

```kod
match b {
    true  -> print("yes")
    false -> print("no")
}
```

### Enum variant (explicit)

```kod
type Color = enum { Red, Green, Blue }

match c {
    Color.Red   -> print("red")
    Color.Green -> print("green")
    Color.Blue  -> print("blue")
}
```

### Enum variant (implicit shorthand)

When the type is clear from context, the enum name can be omitted:

```kod
match c {
    .Red   -> print("red")
    .Green -> print("green")
    .Blue  -> print("blue")
}
```

### Payload variant

Bind the payload fields:

```kod
type Shape = enum {
    Circle(radius: int64)
    Rect(w: int64, h: int64)
}

match shape {
    Shape.Circle(radius) -> print_int(radius)
    Shape.Rect(w, h)     -> print_int(w * h)
}
```

Bindings are by position — the names in the pattern don't have to match the field names.

### Optional

```kod
match maybe_n {
    Some(n) -> print_int(n)
    none    -> print("nothing")
}
```

### `is` test

A lightweight check without destructuring:

```kod
if x is none {
    print("empty")
}
if x is not none {
    print("has value")
}
```

## Match as expression

A `match` produces a value when every arm body is a single expression:

```kod
let label: str = match direction {
    .North -> "north"
    .South -> "south"
    .East  -> "east"
    .West  -> "west"
}
```

For multi-statement arm bodies, use a match statement and assign or
return from inside.

## `if X is .Variant(bindings) { ... }`

When you want a one-arm match with bindings in scope for the body, the
`if`/`is` sugar is shorter than a full `match`:

```kod
if module.decls[i] is .Func(decl_id) {
    // decl_id is in scope here
}
```

An optional `else { ... }` runs when the pattern doesn't match.
Pattern bindings stay scoped to the matching arm — they aren't
in scope in the `else` block.

```kod
if v is .Some(x) {
    print_int(x)
} else {
    print("missing")
}
```

## `let .Pattern(bindings) = expr else { ... }`

Destructure with an early-exit on the non-matching case. The `else`
block must exit the enclosing scope (return / throw / panic) so the
bindings are guaranteed-in-scope below:

```kod
let .Some(v) = m.get(key) else { return -1 }
// v is in scope here
```

## Exhaustiveness

A `match` on an enum (or on `T?` or `bool`) must cover every variant.
The compiler reports an error if any variant is missing and no
wildcard arm is present.

```kod
type Color = enum { Red, Green, Blue }

let c: Color = .Red
// error: match on Color doesn't cover variant Blue
match c {
    .Red -> print("red")
    .Green -> print("green")
}
```

Add the missing arm or an `else` catch-all:

```kod
match c {
    .Red -> print("red")
    .Green -> print("green")
    else -> print("other")
}
```

The single-arm sugar (`if X is .V(b) { ... }` and `let .V(b) = X else
{ ... }`) is not subject to exhaustiveness — they're explicitly
one-variant checks.

A `match` on `int64` or `str` must include an `else` arm — the
compiler reports an error otherwise. (`int64` and `str` have too many
possible values to enumerate; the `else` makes the fall-through
explicit.)

## Other limitations

- No nested patterns (e.g. `Shape.Rect(w, 0)` matching on a specific field value)
- No guard clauses (`if` conditions on arms)
