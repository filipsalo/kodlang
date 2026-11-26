---
icon: lucide/git-branch
---

# Control flow

## `if` / `else`

<!-- kod: let x = 5 -->
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

### `if` as a value

Where a value goes, an `if` with an `else` gives one: that of the branch that runs.

<!-- kod:
let n = -4
let line = "L12"
-->
```kod
let step = if line.starts_with("L") { -1 } else { 1 }
let size = if n < 0 {
    "negative"
} else if n < 10 {
    "small"
} else {
    "large"
}
print(f"{size}, {if n % 2 == 0 { "even" } else { "odd" }}")
```

A branch is a block whose last statement is an expression (or another `if` with an
`else`), the branch's value, as in
[a match's arm](pattern-matching.md#arms-with-several-statements). One that ends in
`return`, `throw` or a call that never returns needs no value. The `else` can't be
left out, and the branches' types follow the rules of
[`match` as an expression](pattern-matching.md#match-as-expression): they are one type, or
convert to the one that the value goes to, and a `none` makes it optional.

The condition can bind names and narrow them as in an `if` statement:

<!-- kod:
let text = "12"
-->
```kod
let doubled = if text.parse_int() is int64(n) and n > 0 { 2 * n } else { 0 }
```

At the start of a statement, `if` is always the statement.

## `for` (while-style)

`for` with a condition loops until the condition is false:

```kod
mut i: int64 = 0
for i < 10 {
    print_int(i)
    i = i + 1
}
```

This is Kod's general looping construct. There is no `while` keyword.
As with `if`, the condition must be a `bool`.

The condition can bind names as an `if` condition does, alone or joined by
`and`. The loop ends when a pattern fails, and the names are new each time
round:

<!-- kod:
type LineReader = shared struct {
    lines: [str]
    pos: int64
    func next_line(self) -> str? {
        if self.pos >= len(self.lines) {
            return none
        }
        self.pos += 1
        return self.lines[self.pos - 1]
    }
}
let reader = LineReader(lines: ["a", "b", ""], pos: 0)
-->
```kod
for reader.next_line() is Some(line) and len(line) > 0 {
    print(line)
}
```

## `for` / `in` (foreach)

Iterate over an array with `for … in`:

```kod
let names: [str] = ["alice", "bob", "carol"]
for name in names {
    print(name)
}
```

The loop variable is declared implicitly — no `let` needed.

`for i, x in xs` also numbers the elements from 0:

<!-- kod: let names: [str] = ["alice", "bob", "carol"] -->
```kod
for i, name in names {
    print(f"{i}: {name}")
}
```

`for i in a..b` counts from `a` up to but not including `b`, like the slice
`xs[a..b]`. Both bounds must be `int64` and are evaluated once, before the
first iteration, so changing `n` in the body of `for i in 0..n` doesn't change
how many times it runs. `a..b` works only here: it isn't a value of its own.

```kod
for i in 0..3 {
    print_int(i)    // 0, 1, 2
}
```

`a..=b` includes `b`. `step k` after the range counts by `k` instead of 1, and a
negative `k` counts down, while the counter is above the end (or, with `..=`,
not below it):

```kod
for i in 1..=3 {
    print_int(i)    // 1, 2, 3
}
for i in 0..10 step 4 {
    print_int(i)    // 0, 4, 8
}
for i in 3..=0 step -1 {
    print_int(i)    // 3, 2, 1, 0
}
```

The step is evaluated once too, and must be an `int64`. A step of 0 is an error
when it is a literal and a panic (`a range's step is 0`) when it isn't. These
forms work in a comprehension's `for` as well. `arrays.reversed(xs)` gives an
array's elements last first.

Either form can take `_` for a name it doesn't use.

A `str` or `bytes` value is iterated byte by byte, each byte an `int64` from 0 to
255, as `s[i]` gives it; `for i, b in s` numbers them. For text, iterate over
`s.code_points()` instead.

```kod
mut spaces: int64 = 0
for b in "a b c" {
    if b == ' ' {
        spaces += 1
    }
}
```

A `Map` is iterated in the order its keys were first set: `for k in m` gives the
keys and `for k, v in m` each key with its value. The loop goes over the entries
the map had when it started, so the body may set and remove entries freely.

<!-- kod:
mut ages = Map[str, int64]()
ages.set("alice", 30)
-->
```kod
for name, age in ages {
    print(f"{name} is {age}")
}
```

A `Set` from the `sets` module is iterated the same way, `for x in s`, over its
elements in the order they were first added.

Arrays, `str`, `bytes`, `Map`, `Set` and `a..b` can be iterated, and so can a
struct with a `values(self) -> [T]` method, such as a `Deque` or a `Heap`: the
loop goes over the array `values()` gives. Any other kind of value is an error.

## `break` and `continue`

Both work inside every form of `for`, and nowhere else; a function literal in a loop's
body is outside of it:

```kod
mut i: int64 = 0
for i < 100 {
    if i == 5 {
        break
    }
    i = i + 1
}
```

<!-- kod:
func process(anon x: int64) -> none {
    print_int(x)
}
let items = [1, 2, 3]
let skip_value = 2
-->
```kod
for x in items {
    if x == skip_value {
        continue
    }
    process(x)
}
```

Both act on the innermost loop. To leave or go on with an outer one, give it a
label, a name and a colon before its `for`, and name it after `break` or
`continue`:

<!-- kod: let grid = [[1, 2], [3, -1], [5, 6]] -->
```kod
mut found = -1
rows: for i, row in grid {
    for x in row {
        if x < 0 {
            found = i
            break rows
        }
    }
}
// found is 1
```

`continue rows` goes on with the next pass of the labelled loop. A label names the
loop it's on and the loops inside it can use it, so `break name` for a loop that
isn't around it is an error (`` no loop labelled `rows` around this `break` ``), and
so is a label that a loop around it already has.

## `match`

Pattern matching on enums, integers, and strings. See [Pattern matching](pattern-matching.md).

<!-- kod:
type Direction = enum {
    North
    South
    East
}
let direction = Direction.North
-->
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

<!-- kod:
type A = struct {
    x: int64
    func show(self) -> str { return "A" }
}
type B = struct {
    x: int64
    func show(self) -> str { return "B" }
}
-->
```kod
func show(anon item: A, anon flag: bool) -> str {
    if flag {
        let item = B(x: 9)   // hides the parameter until the `}`
        return item.show()   // B's show
    }
    return item.show()       // A's show
}
```

<!-- kod:
let xs = [1, 2, 3]
-->
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

<!-- kod:
func parse_num(anon s: str) -> int64? {
    return s.parse_int()
}
let args = ["1", "x", "3"]
mut total = 0
-->
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
[Function values](functions.md#function-values)).
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

<!-- kod:
let n = 5
-->
```kod
mut label = "other"
if n > 0 {
    label = "positive"
}
print(label)
```

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
can't. Nor can a call that never returns: `panic(...)`, or a `-> none`
function or method without a `return` whose body can't finish by these
same rules, such as one that ends in another such call or in a `for true`
loop without a `break`. A method counts whatever it's called on, a local
included, as long as the receiver's type is known at the call. A call
through a function value and a method called through an interface value
are taken to return, since what they call is chosen at run time; end
such a path with a `panic(...)` or a `return` after the call (see
[Return values](functions.md#return-values)).
