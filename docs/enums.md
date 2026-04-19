# Enums

Enums in Kod are tagged unions — each value carries a *discriminant* identifying which
variant it is, plus an optional *payload* holding the variant's fields.

## Syntax

### Declaration

```kod
type Direction = enum {
    North
    South
    East
    West
}

type Message = enum {
    Text(content: str)
    Number(value: int64)
}
```

Variants without parentheses are *unit variants* (no payload). Variants with
parentheses carry named fields.

### Construction

```kod
let d: Direction = Direction.North
let m: Message = Message.Text(content: "hello")
```

Unit variant: `EnumName.VariantName`
Payload variant: `EnumName.VariantName(field: value, ...)`

### Pattern matching

```kod
match m {
    Message.Text(content) -> print(content)
    Message.Number(value) -> print_int(value)
    _ -> print("unknown")
}
```

- Arrow `->` for single-statement arms
- Block `{ ... }` for multi-statement arms
- `_` is the wildcard pattern (matches anything)
- No exhaustiveness checking (yet)
- Match is a statement, not an expression (for now)

## Memory layout (compiler)

Enum values are stack-allocated with a fixed size determined at compile time:

```
[ offset 0  ] discriminant : int64  (8 bytes)
[ offset 8  ] payload      : max(variant payload sizes) bytes
```

Variants are assigned discriminants in declaration order, starting from 0.
Fields within a variant's payload are laid out sequentially, each at its
natural alignment.

### Example: `Message`

```
type Message = enum {
    Text(content: str)    // payload: str (8 bytes)  → discriminant 0
    Number(value: int64)  // payload: int64 (8 bytes) → discriminant 1
}
```

- `Text` discriminant = 0, `content` at payload offset 0
- `Number` discriminant = 1, `value` at payload offset 0
- max payload width = 8
- total enum width = 8 (discriminant) + 8 (payload) = **16 bytes**

### Example: `Direction` (unit variants only)

```
type Direction = enum { North South East West }
```

- All discriminants 0–3, no payload
- total enum width = 8 (discriminant) + 0 (payload) = **8 bytes**

## Equality

Two enum values are equal if and only if they are the same variant of the same
enum type. Payload contents are not compared.

```kod
Direction.North == Direction.North  // true
Direction.North == Direction.South  // false
```

In the compiler this is a single integer comparison on the discriminant.

## Implementation notes

### Type registry

Enum types are registered in `parser.type_registry` (keyed by name) when their
`TypeDeclaration` is parsed. This allows subsequent type annotations like
`: Direction` to resolve correctly at parse time.

### Match binding variables

Pattern bindings (e.g. `content` in `Message.Text(content)`) need stack space.
Their types are resolved from the enum's variant field definitions during
`FunctionDeclaration.parse`, and they are added to the function's `variables`
dict so the `StackFrame` allocates space for them before the function body is
compiled.

### Enum type attributes

`EnumType.make` sets class-level attributes for each variant:
- Unit variants → a singleton `EnumValue` instance
- Payload variants → an `EnumVariantConstructor` callable

This means `Direction.North` evaluates by looking up the `Direction` class in
scope and calling `getattr(Direction, 'North')`, which returns the singleton
directly.

## Current limitations

- **Explicit type annotations required in the compiler.** `let d: Direction = ...`
  works; `let d = ...` (inferred) requires the compiler to know the enum width
  before processing the assignment, which isn't yet supported.

- **Match expression must be a simple variable.** `match compute_direction() { ... }`
  is not yet supported in the compiler; the matched expression must name a
  local variable or parameter.

- **No passing enums as function arguments in the compiler.** Enums are
  multi-word values (16 bytes for a typical enum) and the current calling
  convention only handles single-register arguments. Passing enums to functions
  requires an extended ABI or by-reference passing, which is not yet
  implemented.

- **No exhaustiveness checking.** If no arm matches at runtime, the match falls
  through silently.

- **No nested patterns.** `Message.Text("literal")` as a pattern is not
  supported; bindings only bind by name.

- **Match is a statement, not an expression.** `let x = match m { ... }` is not
  yet supported.

## Roadmap

- Lift the explicit annotation requirement via type inference
- Support enums as function arguments (via ABI changes or arena-based references)
- Pattern matching as an expression
- Exhaustiveness checking
- Enum-based `Optional[T]` as the implementation of `T?` optional types
