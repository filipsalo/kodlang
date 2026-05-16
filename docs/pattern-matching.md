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

### Wildcard

`_` matches any value:

```kod
match x {
    _ -> print("anything")
}
```

### Integer literal

```kod
match n {
    0 -> print("zero")
    1 -> print("one")
    _ -> print("other")
}
```

### String literal

```kod
match s {
    "hello" -> print("greeting")
    "bye"   -> print("farewell")
    _       -> print("unknown")
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

`match` can be used as an expression in some contexts:

```kod
let label: str = match direction {
    .North -> "north"
    .South -> "south"
    .East  -> "east"
    .West  -> "west"
}
```

!!! note
    Match expressions are supported in the interpreter. Compiler support is partial.

## Limitations

- No exhaustiveness checking — unmatched values fall through silently
- No nested patterns (e.g. `Shape.Rect(w, 0)` matching on a specific field value)
- No guard clauses (`if` conditions on arms)
