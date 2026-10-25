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

## Blocks and bindings

A `let` or let-else binding lasts from its statement to the end of the
block it's in. The bindings of a match arm's pattern, or of `if … is`,
last for that arm, a `for … in` variable for the loop body, and
parameters for the whole function.

Blocks don't have their own scopes yet: a function keeps one slot for
each name. So a block can't bind a name again while an enclosing block
or a parameter still has it bound:

```kod
func show(anon item: A, anon flag: bool) -> str {
    if flag {
        let item = B(x: 9)   // error: `item` is already a local here (line 1); ...
        return item.show()
    }
    return item.show()
}
```

The same goes for a pattern binding (`Some(x)` while a `let x` is still
bound) and a `for` variable; give the inner binding another name. A
block may bind a name again itself, and the new value still sees the old
binding, even when its type differs (`let x = 1`, then
`let x = f"#{x}"`). So may a block after one whose binding of the name
has ended. A let-else's else block runs when the pattern doesn't match,
so there the name still has its old binding:

```kod
for arg in args {
    let .Some(arg) = parse_num(arg) else {
        print(f"bad: {arg}")   // the str from `args`
        continue
    }
    total += arg               // the parsed int64
}
```

A name is a local only where its binding lasts. Before its `let`, or
after the block, arm or loop that bound it, the name means a function of
the module, an imported one or a builtin of that name, as it does in a
call (see [Function-pointer types](functions.md#function-pointer-types)),
and with none of those, reading or assigning it is an error:
`` `x` is read before its `let` `` or
`` `x` is declared in a block that has ended ``. Declare a name before
the block to use it after the block:

```kod
mut label = "other"
if n > 0 {
    label = "positive"
}
print(label)
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
can't. Nor can a call that never returns: `kod_panic(...)`, or a `-> none`
function or method without a `return` whose body can't finish by these
same rules, such as one that ends in another such call or in a `for true`
loop without a `break`. Until blocks get their own scopes, a method is
taken to return when its receiver's type depends on a local other than
`self` or a parameter, and a parameter that a `let` or let-else in the
body binds again counts as a local; end the path with a `kod_panic(...)`
or a `return` after the call (see
[Return values](functions.md#return-values)). A method called through an
interface value is taken to return too, so call it as a statement and
end the path with `kod_panic(...)`.
