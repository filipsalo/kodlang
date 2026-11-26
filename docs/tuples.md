---
icon: lucide/parentheses
---

# Tuples

A tuple is a few values together, of types of their own, that have no need of a name:

```kod
let p = (3, "three")            // a (int64, str)
print(p.0)                      // 3
print(p.1)                      // three

let (n, word) = p
print(f"{n} is {word}")         // 3 is three
```

Its type is the types of its elements in parentheses: `(int64, str)`, `[(int64, int64)]`,
`(str, (bool, float64))?`. A tuple has two to eight elements; for more, or where the
elements deserve names, declare a [struct](structs.md). `(x)` is just `x`.

## Taking one apart

`let` and `mut` take a tuple's elements as names of their own, with `_` for what isn't
needed. Tuples nest:

<!-- kod:
func bounds() -> (int64, int64) {
    return (1, 9)
}
-->
```kod
let (low, high) = bounds()
let (_, top) = bounds()
let ((a, b), c) = ((1, 2), "x")
mut (x, y) = (0, 1)
x += 1
```

So does a `for`:

```kod
let pairs = [(1, "one"), (2, "two")]
for (n, word) in pairs {
    print(f"{n} {word}")
}
for i, (n, word) in pairs {
    print(f"{i}: {n} {word}")
}

mut grid = Map[(int64, int64), str]()
grid[(0, 1)] = "a"
for (x, y), name in grid {
    print(f"{x},{y} {name}")
}
```

In an assignment the right side is worked out first, then its elements are stored from left
to right, so this swaps:

```kod
mut a = 1
mut b = 2
mut xs = [5, 6]
(a, b) = (b, a)
(xs[0], xs[1]) = (xs[1], xs[0])
```

## Elements

`p.0` is the first element, `p.1` the next. One of a `mut` tuple can be assigned:

```kod
mut p = (1, "a")
p.0 += 1
p.1 = "b"
assert p == (2, "b")
```

A tuple is a value, as a plain struct is: assigning or passing it gives the other place the
tuple as it is.

An array of tuples of two to four numbers, `bool`s or payload-free enums keeps the elements'
values in the array itself (see [Arrays of small structs](memory-layout.md#arrays-of-small-structs)),
so a `[(int64, int64)]` or a `Set[(int64, int64)]` costs no allocation per element.

## Where a tuple goes

Each element of a literal takes its type from where the tuple goes, as it would by itself:

```kod
let p: (int64?, [str]) = (none, [])
let found: [(str, int64 | str)] = [("a", 1), ("b", "x")]

func divide(anon a: int64, by b: int64) -> (int64, int64) {
    return (a / b, a % b)
}
let (q, r) = divide(17, by: 5)
assert q == 3 and r == 2
```

## Patterns

In a `match` and after `is`, `(p, q)` matches a tuple element by element. What stands for an
element is any pattern, or a name to bind:

```kod
func where_is(anon p: (int64, int64)) -> str {
    match p {
        (0, 0) -> return "origin"
        (x, 0) -> return f"on the x axis at {x}"
        (0, _) -> return "on the y axis"
        (x, y) if x == y -> return "on the diagonal"
        (_, _) -> return "elsewhere"
    }
}

let o: (int64, str)? = (1, "a")
if o is Some((n, _)) {
    print(n)
}
```

A pattern of names alone always matches, so it covers the type.

## Comparing, hashing and text

As plain structs do (see [Structs are values](structs.md#structs-are-values)), two tuples
of one type compare with `==` when their elements do, can be a `Map`'s key or a `Set`'s
element when their elements can be hashed, and print when their elements do:

```kod
assert (1, "a") == (1, "a") and (1, "a") != (1, "b")
print((1, ("a", [true])))       // (1, (a, [true]))
```

Tuples are also ordered by `<`, `<=`, `>` and `>=` when their elements are: by the first
element, and where those are equal by the next. So `min`, `max` and
[`sort.sorted`](arrays.md#sorting) take them:

```kod
import "sort"

assert (1, 9) < (2, 0) and (2, "a") < (2, "b")
assert sort.sorted([(2, "b"), (1, "z"), (2, "a")]) == [(1, "z"), (2, "a"), (2, "b")]
```
