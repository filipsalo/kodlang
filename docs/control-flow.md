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

A statement ends at the end of its line or at a `}`, so two statements
can share a line only after a block (`if c { a() } b()`). Anything else
after a statement on its line is an error: `let x = 5 print_int(x)`.

A `let` or let-else binding lasts from its statement to the end of the
block it's in. The bindings of a match arm's pattern, or of `if … is`,
last for that arm. A `for … in` variable lasts for the loop body, and
parameters (`self` included) for the whole function. Parameter and field
defaults follow the same rules.

Every block has its own scope. A binding may take the name of one still
in force, whatever kind of binding either is: a `let`, `mut` or
let-else, a name in a pattern, a `for` variable, a parameter or `self`.
Inside its block, arm or loop body the new binding hides the old one,
and reading or assigning the name there means the new one. When that
block, arm or loop ends, the old binding is back with its own value,
type and mutability:

```kod
func show(anon item: A, anon flag: bool) -> str {
    if flag {
        let item = B(x: 9)   // hides the parameter until the `}`
        return item.show()   // B's show
    }
    return item.show()       // A's show
}
```

```kod
mut total = 0
for x in xs {
    let total = x * 2        // this loop body's own `total`
    print(f"{total}")
}
total = total + 1            // the `mut total` again
```

A block may also bind a name again itself. The new binding then replaces
the old one for the rest of that block. These count as binding the name
again in the same block:

- a function's top block reusing a parameter's name;
- an arm reusing its pattern's name;
- a loop body reusing its `for` variable's name.

A binding's value, the array of a `for … in` and the value that
`if … is` tests all see the binding the name had before, even when the
type differs: `let x = x + 1`, `let x = f"#{x}"`, `for x in x`,
`if o is Some(o)`. A let-else's else block runs when the pattern doesn't
match, so there the name still has the binding it had before the
let-else:

```kod
for arg in args {
    let .Some(arg) = parse_num(arg) else {
        print(f"bad: {arg}")   // the str from `args`
        continue
    }
    total += arg               // the parsed int64
}
```

A name is a local only where a binding of it is in force. Elsewhere it
means a function of the module, an imported one or a builtin of that
name, as it does in a call (see
[Function-pointer types](functions.md#function-pointer-types)).
Elsewhere means before its `let`, or after the block, arm or loop that
bound it when no outer binding is in force. With none of those
functions, reading or assigning the name is an error:
`` `x` is read before its `let` `` or
`` `x` is declared in a block that has ended ``. When another module
declares a type of that name and this one doesn't see it, reading or
calling the name gives the error for that type (`` unknown type `Mode`;
lib/modes.kod declares `Mode`: write `modes.Mode` or list it in the
import (`{ Mode }`) ``), as with no local at all. Assigning the name
still gives the errors above. Declare a name before the block to use it
after the block:

```kod
mut label = "other"
if n > 0 {
    label = "positive"
}
print(label)
```

An enum's name before a `.`, and a type's name as a type argument, still
mean the type where a local of that name is in force: after
`let Color = 3`, `Color.Blue` is the enum's variant and `Box[Color]` an
instance of `Box`.

A function literal doesn't see the locals of the function it's written
in.

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
loop without a `break`. A method counts whatever it's called on, a local
included, as long as the receiver's type is known at the call. A call
through a function value and a method called through an interface value
are taken to return, since what they call is chosen at run time; end
such a path with a `kod_panic(...)` or a `return` after the call (see
[Return values](functions.md#return-values)).
