---
icon: lucide/git-branch
---

# Control flow

## `if` / `else`

```kod
if x > 0 {
    print("positive")
} else {
    print("non-positive")
}
```

The `else` branch is optional. Braces are always required.

The condition must be a `bool`. There's no truthiness, so `if n` on an
`int64` is an error (write `if n != 0`), and so is `if x` on an optional
(write `if x is not none`, or `if x is Some(v)` to bind the value).

## `for` (while-style)

`for` with a condition loops until the condition is false:

```kod
let i: int64 = 0
for i < 10 {
    print_int(i)
    i = i + 1
}
```

This is Kod's general looping construct. There is no `while` keyword.
As with `if`, the condition must be a `bool`.

## `for` / `in` (foreach)

Iterate over an array with `for … in`:

```kod
let names: [str] = ["alice", "bob", "carol"]
for name in names {
    print(name)
}
```

The loop variable is declared implicitly — no `let` needed.

Only arrays can be iterated. `for c in s` over a `str` and `for k in m`
over a `Map` are errors for now: iterate over `s.code_points()` or
`m.keys` instead. Iterating over any other kind of value is an error too.

## `break` and `continue`

Works inside both loop forms:

```kod
let i: int64 = 0
for i < 100 {
    if i == 5 {
        break
    }
    i = i + 1
}
```

```kod
for x in items {
    if x == skip_value {
        continue
    }
    process(x)
}
```

## `match`

Pattern matching on enums, integers, and strings. See [Pattern matching](pattern-matching.md).

```kod
match direction {
    Direction.North -> print("north")
    Direction.South -> print("south")
    else -> print("other")
}
```

## `return`

Return a value from a function:

```kod
func abs(n: int64) -> int64 {
    if n < 0 {
        return 0 - n
    }
    return n
}
```

A bare `return` (no value) is valid in `-> none` functions.

A function that returns a value must not be able to run off the end of its
body (see [Return values](functions.md#return-values)). An `if` without an
`else`, a `for` over a condition or an array, and a `for true` loop with a
`break` can all finish, so a `return` has to follow them; a `match` whose
arms all return, and a `for true` loop that only leaves through `return`,
can't.
