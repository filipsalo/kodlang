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

## `for` / `in` (foreach)

Iterate over an array with `for … in`:

```kod
let names: [str] = ["alice", "bob", "carol"]
for name in names {
    print(name)
}
```

The loop variable is declared implicitly — no `let` needed.

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
