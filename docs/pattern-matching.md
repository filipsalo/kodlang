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
    -1   -> print("minus one")
    else -> print("other")
}
```

A `-` directly before the digits makes the literal negative. As in an
expression, the smallest `int64` is written `-9223372036854775808`. Only a
literal can be a pattern, so `-n` is not one.

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

A literal pattern needs a value of its own type, so matching a `str`
against `3` is an error, and so is matching an optional: with
`n: int64?`, unwrap it first, as in `match n? { 3 -> ... }`.

### Enum variant (explicit)

```kod
type Color = enum {
    Red
    Green
    Blue
}

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
A pattern may bind fewer names than the variant has fields, but not more, and
it can't bind one name twice, though `_` and `_name` can repeat.
Naming an enum or variant that doesn't exist is an error, as is an
implicit `.Variant` that no enum declares.

Each binding takes the type of the field it binds, so different arms can
reuse a name for payloads of different types:

```kod
type Value = enum {
    I(value: int64)
    S(value: str)
}

match v {
    .I(value) -> print(f"int {value}")
    .S(value) -> print(f"str {value}")
}
```

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

### Nested patterns

A payload position can hold a pattern instead of a name. The arm matches only
when every nested pattern does, and a failed test moves on to the next arm:

```kod
type Shape = enum {
    Circle(radius: int64)
    Rect(w: int64, h: int64)
}

match shape {
    .Rect(w, 0)     -> print(f"flat {w}")   // h must be 0, w is bound
    .Rect(_, _)     -> print("rect")
    .Circle(radius) -> print_int(radius)
}

let best: Shape? = find_best()
match best {
    Some(.Circle(r))  -> print_int(r)
    Some(.Rect(w, h)) -> print_int(w * h)
    none              -> print("nothing")
}
```

Patterns nest to any depth, and each kind above can appear inside another:
literals, `none`, `Some(...)`, `Ok(...)`, `Err(...)`, enum variants, and a
struct downcast such as `.Wrap(Sq(s))`. In a payload position a bare name
always binds, so a downcast with no binding is not available there: write
`Sq(_)`. A nested literal needs a field of its own type.

Tests run left to right and from the outside in, and each nested pattern sees
the field's type, so `.Pair(Some(0), "x")` needs an optional `int64` and a `str`.

Nested patterns work wherever a pattern can bind: in a `match`, in an `if` or
`for` condition (`if best is Some(.Circle(r)) { ... }`), and in a let-else
(`let .Some(.Circle(r)) = best else { return }`). Elsewhere `is` is only a
test, and a nested pattern is an error: use a `match`, or an `if` of its own.

### Guards

An arm's pattern can be followed by `if` and a condition. The arm runs only
when the pattern matches and the condition is true; otherwise the next arm is
tried. The pattern's bindings are in scope in the guard:

```kod
match shape {
    .Circle(r) if r > 100 -> print("big circle")
    .Circle(r)            -> print_int(r)
    .Rect(w, h) if w == h -> print("square")
    .Rect(_, _)           -> print("rect")
}
```

The guard must be a `bool`. It runs at most once for each arm, after that arm's
pattern has matched, and can call functions. On an arm with alternatives it
applies to each of them: `.Plus | .Minus if ready -> ...`. Guards work in match
statements and match expressions, but not on `else`, which has no pattern to
guard. A guard can't bind names itself; put the pattern in the arm instead:
`Some(.Circle(r)) -> ...` rather than `Some(s) if s is .Circle(r) -> ...`.

### Alternatives (`|`)

Patterns joined with `|` share an arm, in a `match` statement or expression:

```kod
match token {
    .Plus | .Minus -> print("additive")
    .Star | .Slash -> print("multiplicative")
    else print("other")
}
match n {
    1 | 2 | 3 -> print("small")
    else print("big")
}
```

The arm counts as one arm for each alternative when the compiler checks that
a `match` is exhaustive. Alternatives can't bind names, because each would
have to bind the same ones; `_` and nested literals are fine, as in
`.Circle(_) | .Dot` and `.Rect(0, _) | .Rect(_, 0)`. Give an arm that binds a
line of its own.

## Match as expression

A `match` produces a value when every arm has a value, in the simplest case a single expression:

```kod
let label: str = match direction {
    .North -> "north"
    .South -> "south"
    .East  -> "east"
    .West  -> "west"
}
```

Payload, `Some(x)`, and `Ok(v)` / `Err(e)` bindings are in scope in the
arm's expression, just as in the statement form. They may hide a local of
the same name, which is back after the arm (see
[Blocks and bindings](control-flow.md#blocks-and-bindings)):

```kod
let area: int64 = match shape {
    Shape.Circle(r)  -> 3 * r * r
    Shape.Rect(w, h) -> w * h
}
```

Without an annotation, the match takes the type of its first arm that
isn't `none`, and each arm's bindings have that arm's payload types:

```kod
let name = match w {
    .S(value) -> value          // value: str
    .I(value) -> f"#{value}"    // value: int64
}
print(name + "!")               // name: str
```

A `none` arm, or an arm of type `T?` next to arms of type `T`, makes the
match a `T?`, and the plain arms are wrapped:
`let found = match k { 1 -> "one" else -> none }` is a `str?`. Every other
arm must have the match's type, so `1 -> "a"` next to `else -> 2` is an
error. With an annotation each arm is converted to the annotated type,
which is how arms of different structs become one interface value:
`let s: Shape = match k { 1 -> Sq(s: 2) else -> Circle(r: 1) }`.

When the match's value is used, every arm needs a value: an arm that calls
a function returning `none` is an error, unless the call never returns,
like `kod_panic(...)` or a helper that ends in one, an imported module's
function (`log.die(...)`) included (see
[Return values](functions.md#return-values)). In a `-> none`
or `-> none or Error` function, `return match k { 1 -> a() else -> b() }`
doesn't use the value, so its arms may return `none`. Without an annotation, a match whose arms are
all `none` is an error too, as `let x = none` is, since its type can't be
inferred.

## Arms with several statements

An arm of a match expression may be a block. Its last statement must be an
expression, and that expression is the arm's value; the statements before it
run first, and what they bind is gone after the arm:

```kod
let size: int64 = match shape {
    Shape.Circle(r) -> {
        let d = 2 * r
        d * 3
    }
    Shape.Rect(w, h) -> w * h
}
```

The block is an ordinary block, so it may `return`, `throw` or `try` (they leave
the function, not just the arm), and an arm without braces is still one
expression. `else { ... }` takes a block too. A block that is empty, or whose
last statement is not an expression (`let`, `if`, an assignment), is an error:
the arm would have no value. A match *statement* needs none of this, since its
arms are blocks already.

## `if X is .Variant(bindings) { ... }`

When you want a one-arm match with bindings in scope for the body, the
`if`/`is` sugar is shorter than a full `match`:

```kod
if module.decls[i] is .Func(decl_id) {
    // decl_id is in scope here
}
```

An optional `else { ... }` runs when the pattern doesn't match, and
`else if` chains on as it does after any `if`; that `if` can bind names of
its own: `if r is Ok(v) { … } else if r is Err(e) and e.code > 0 { … }`.
Pattern bindings stay scoped to the matching arm — they aren't
in scope in the `else` block. There and after the `if`, a name the
pattern binds means what it meant before the `if`, such as an outer
local it hid in the arm: in `if o is Some(o) { … } else { … }` the
`else` block's `o` is the optional. As in a `match` arm, the pattern can name
the enum, `if s is Shape.Rect(w, h)`, or an imported one,
`if s is geo.Shape.Rect(w, h)`.

On a `T?` value, `.Some(v)` and `.None` are the same patterns as `Some(v)`
and `none`, here, in a `match` and with a bare `is`. On a `T or Error`
value, `.Ok(v)` and `.Err(e)` are the same as `Ok(v)` and `Err(e)`. Naming
the enum works too, as in `Option.Some(v)` and `Result.Ok(v)`. A generic
enum is named without type arguments, and the bindings take the value's
payload types: on a `Maybe[int64]`, `Maybe.Just(n)` binds an `int64`.

Any other variant pattern needs an enum value. On a `Color?`, `.Red` is an
error rather than a test that never matches: unwrap it first with `x?`, or
match `.Some(c)`. Likewise `.Some` and `.None` need an optional, and
`.Ok` and `.Err` a `T or Error`.

A bare `is` also tests an enum value's variant without binding its
payload: `if c is .Red and ready { ... }`, `s is .Circle(_)`.

A pattern with bindings can also be one of the operands an `if` condition
joins with `and`. Its names are in scope in the operands after it and in
the body, as if each `is` were its own `if` nested inside the one before:

```kod
if decl is .Import(_path, alias, _items) and not alias.starts_with("#") {
    aliases += [alias]
}
if a is .Some(x) and b is .Some(y) and x == y {
    print_int(x)
} else {
    print("no match")
}
```

The `else` block runs when any operand fails, and sees none of the
bindings. A `for` condition can bind the same way (see
[`for`](control-flow.md#for-while-style)). Elsewhere a pattern can't bind: not
under `or` or `not`, not with `is not` inside an `and` chain, not in a `let`
value. There the `is` is only a test, and `.Circle(r)` is an error.

```kod
if v is .Some(x) {
    print_int(x)
} else {
    print("missing")
}
```

## `let .Pattern(bindings) = expr else { ... }`

Destructure with an early-exit on the non-matching case. The `else`
block must exit the enclosing scope (return / throw / panic, or
break / continue in a loop) so the bindings are guaranteed-in-scope
below. A block that can reach its end is an error, decided by the same
rules as the end of a function (see
[Return values](functions.md#return-values)): it may end in an `if`/`else`
or a `match` whose every branch exits, in a `for true` loop it can't
`break` out of, or in a call that never returns, as for match arms above:

```kod
let .Some(v) = m.get(key) else { return -1 }
// v is in scope here
```

The bindings start after the else block, so inside it a name the
pattern binds still has the binding it had before the let-else, if any.

The pattern always starts with a `.`. On a `T?` value (like
`m.get(key)` above), `.Some(v)` binds the unwrapped payload and
`.None` matches `none`, the same spelling as for an `Option[T]`.
On a `T or Error` value, `.Ok(v)` binds the value and `.Err(e)` the
error. On an enum value, the variant is looked up in that value's
enum, even when another enum declares a variant of the same name:

```kod
let .Ok(text) = read_text(path) else { return 1 }
print(f"{text}!")    // text is a str
```

## Exhaustiveness

A `match` on an enum (or on `T?` or `bool`) must cover every variant.
The compiler reports an error if any variant is missing and no
wildcard arm is present. An arm naming a variant the enum doesn't declare
is reported instead, since it's usually a misspelling of the missing one,
and its bindings don't cause further errors in the arm.

```kod
type Color = enum {
    Red
    Green
    Blue
}

let c: Color = .Red
// error: match on Color doesn't cover variant Blue
match c {
    .Red -> print("red")
    .Green -> print("green")
}
```

An arm with a guard doesn't cover anything, since its condition can be false:
some other arm has to handle that variant too.

Nested patterns are checked all the way down. These arms cover every `Shape?`,
so no `else` is needed:

```kod
match best {
    Some(.Circle(_))  -> print("circle")
    Some(.Rect(_, _)) -> print("rect")
    none              -> print("nothing")
}
```

Drop the `.Rect` arm and the error names what is left:
`match on `Shape?` doesn't cover `Some(.Rect(_, _))``. A nested literal never
completes a field of type `int64` or `str`, so `.Rect(w, 0)` needs another arm
for the same variant.

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
