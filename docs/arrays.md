---
icon: lucide/list
---

# Arrays

Arrays in Kod are resizable, homogeneous sequences. The type is `[T]` where `T` is the element type.

An array is a value, like an `int64` or a `str`: assigning it, passing it or
storing it in a field gives the other place the array as it is, and changing
one of them later leaves the others alone (see [Arrays are values](#arrays-are-values)).

## Literals

```kod
let nums: [int64] = [1, 2, 3, 4, 5]
let words: [str] = ["hello", "world"]
let empty: [int64] = []
```

A literal with no type to go to takes its first element's type, and every
other element must have that type: `let xs = [1, "a"]` is an error
(`` expected `int64`, got `str` ``), and so is `[Sq(s: 1), Circle(r: 1)]`
even when both implement `Shape`. Annotate the array to mix structs behind
an interface: `let shapes: [Shape] = [Sq(s: 1), Circle(r: 1)]`, which the
error suggests when the module has an interface both implement.

## Indexing

<!-- kod: let nums: [int64] = [1, 2, 3, 4, 5] -->
```kod
let first: int64 = nums[0]
let last: int64 = nums[-1]    // negative index counts from end
let third: int64 = nums[2]
```

Negative indices wrap around: `arr[-1]` is equivalent to `arr[len(arr) - 1]`.
An index out of range either way panics. An index must be an `int64`:
`nums["a"]`, `nums[true]` and an `int64?` index such as `nums[m.get(k)]` are
errors.

An array never shrinks, so in `for i in 0..len(xs)` (from any literal of 0 or
more) `xs[i]` is always in range, and the compiler leaves out the check when
`xs` is a `let` or a parameter, which nothing can point at another array.

Arrays nest: an element of a `[[int64]]` is an `[int64]`, so `grid[i][j]`
and `for row in grid { for x in row { ... } }` work, and an element of a
`[bool]` is a `bool`.

A literal takes its element type from where it goes, at any depth: a
`let`, an assignment, an argument, a field, an enum payload, a return value
(including a match arm's), the rest of an array `+` chain (see
[Concatenation](#concatenation)), or an element or `Map` value it's stored
as. In `let g: [[Shape]] = [[Sq(s: 3)]]`, `shapes += [Sq(s: 4)]`,
`[Sq(s: 1)] + shapes` or `return [none, 3]` from a `-> [int64?]` function,
each struct is boxed as the interface and each value wrapped as the
optional. In a `[Direction]`, `[.North, .South]` builds `Direction`
variants even when another enum declares variants of those names, and in a
`[Maybe[int64]]`, `[.Just(value: 1), .Nothing]` builds `Maybe[int64]` ones.

Arrays, `str` and `bytes` can be indexed, and so can a struct that declares
an `op_index` method (`Map` does). Element assignment needs an array or a
struct with `op_index_set`, slicing needs an array, `str` or `bytes`, and
`for … in` needs an array, `str`, `bytes`, `Map`, `Set` or `a..b` (see
[Control flow](control-flow.md#for-in-foreach)). Anything else is a compile
error.

An array can be changed, by assigning an element or appending, only through
a name that could be assigned: a `mut` binding or a `mut` parameter. On a
`let` array, a parameter not declared `mut`, a `for` variable or a pattern
binding, `xs[0] = 1` and `grid[i][j] = 1` are errors
(`` cannot change `xs`, an immutable binding; declare it with `mut` ``),
as `xs += [1]` is. An array kept in a field is changed through the field,
so `self.xs[i] = v` and `p.items += [x]` work however `self` or `p` is bound.

An assigned element must have the array's element type, with the same
conversions as a `let`: `names[0] = 5` on a `[str]` is an error, while
`xs[0] = 42` on an `[int64?]` and `pets[0] = Cat()` on a `[Pet]` wrap and
box the value. On a struct, the key of `m[k]` and the key and value of
`m[k] = v` must have the types of `op_index`'s and `op_index_set`'s
parameters (see [Indexing a struct](builtins.md#indexing-a-struct)), so
`m[5]` on a `Map[str, int64]` is an error.

An element or a slice is read once its index or bounds have been worked out, so
`xs[add(mut xs)]` reads the array that `add` leaves.

A store evaluates its parts left to right: in `rows()[i()] = v()` and
`m[k()] = v()` the receiver comes first, then the index or key, then the
value, and `f().x = v()` calls `f` before `v`. A compound
`rows()[i()] += v()` evaluates the receiver and the index once, reads the
element and then evaluates `v()`, so `rows` and `i` are each called once.
Indexing a struct calls its `op_index`, so it counts as a call too:
`xs[a[k]] += b[k]` calls `a`'s `op_index` once, before `b`'s.

## Length

<!-- kod: let nums: [int64] = [1, 2, 3, 4, 5] -->
```kod
let n: int64 = len(nums)
```

## Slicing

<!-- kod: let nums: [int64] = [1, 2, 3, 4, 5] -->
```kod
let sub: [int64] = nums[1..4]   // elements 1, 2, 3
let prefix: [int64] = nums[..3]  // first three
let suffix: [int64] = nums[3..]  // from index 3 onward
let all: [int64] = nums[..]      // all of it
```

A negative bound counts from the end, as an index does: `nums[..-1]` is all but the
last and `nums[-2..]` the last two. Then both endpoints clamp to `[0, len]`, so
`[1, 2, 3][1..10]` is `[2, 3]` and `[1, 2, 3][-9..1]` is `[1]`. An end before the
start yields an empty slice. Both bounds must be `int64`.

## Concatenation

Use `+=` to append elements or extend with another array:

```kod
mut a: [int64] = [1, 2]
a += [3, 4]          // a is now [1, 2, 3, 4]
```

Or `+` to produce a new array; neither operand is modified:

<!-- kod: let a: [int64] = [1, 2, 3, 4] -->
```kod
let b: [int64] = [5]
let c: [int64] = a + b   // [1, 2, 3, 4, 5]; a and b are unchanged
```

Every literal and `match` in a chain of `+` is built as the type the whole
chain goes to, or, without one, as its first operand that isn't a literal or
`match`. So `[Sq(s: 1)] + [Sq(s: 2)] + shapes` boxes both squares as `Shape`,
and `let ms: [Maybe[str]] = [.Just(value: "a")] + [.Nothing]` builds
`Maybe[str]` variants. The other operands must all have that one type:
`squares + shapes` (a `[Sq]` and a `[Shape]`) and `nums + names` are errors,
and so is `names + [1]`, whose literal's element isn't a `str`.

`+=` grows the array's buffer geometrically, so appending in a loop is
amortized O(1) per element. `+` always copies both operands, so
`xs = xs + [x]` costs O(len(xs)); prefer `xs += [x]` in loops. `xs += [x]`
with one element builds no array for the literal: `x` goes straight onto the
end of `xs`.

## Arrays are values

Each name, field and element holds an array of its own. After `let a = xs`,
`xs += [3]` leaves `a` as it was, and so does `xs[0] = 9`; the same goes for
an array stored in a field or in another array, or passed to a function:

```kod
mut xs = [1, 2]
let a = xs
xs += [3]              // xs is [1, 2, 3], a is still [1, 2]

mut grid = [[0, 0], [0, 0]]
let row = grid[0]
grid[0][1] = 5         // grid is [[0, 5], [0, 0]], row is still [0, 0]
```

None of this copies anything until it has to: assigning or passing an array
shares its elements, and they are copied the first time one holder changes
them while another still has them. An array nobody else holds is changed in
place, so appending in a loop stays amortized O(1). A function changes its
caller's array only through a [`mut` parameter](functions.md#mut-parameters).

A `for x in xs` loop goes over `xs` as it was when the loop started: what
the body appends or assigns to `xs` is in `xs` afterwards, but the loop
doesn't reach it.

## Repetition

`*` with an `int64` repeats an array, in a new array, which is the way to make
one of a given size:

<!-- kod: let n = 10 -->
```kod
mut seen = [false] * 1000      // 1000 times false
let zeros: [int64] = [0] * n
let ab = [1, 2] * 3            // [1, 2, 1, 2, 1, 2]
```

The count comes second, and zero or less gives an empty array. It is one
allocation and a copy, much faster than appending in a loop. Each element is
a value of its own, so the rows of `mut grid = [[0] * 3] * 3` can be changed
one at a time.

## Comprehensions

`[elem for x in xs]` makes an array of what `elem` is for each `x`:

```kod
let words = ["pear", "fig", "apple"]
let sizes = [len(w) for w in words]               // [4, 3, 5]
let long = [w.upper() for w in words if len(w) > 3]
let pairs = [(i, j) for i in 0..3 for j in i + 1..3]    // [(0, 1), (0, 2), (1, 2)]
```

The `for` goes over what a [`for` loop](control-flow.md#for-in-foreach) does, and binds
what that does: `for i, x in xs`, `for k, v in m`, `for (a, b) in pairs`. Any number of
`for`s and `if`s may follow each other, each inside the one before it. An `if` can bind
names and narrow them as an `if` statement's condition does:

<!-- kod:
let fields = ["1", "x", "3"]
let maybe: [int64?] = [1, none]
-->
```kod
let nums = [n for f in fields if f.parse_int() is Some(n)]     // [1, 3]
let next = [n + 1 for n in maybe if n is not none]             // [2]
let table = [
    (i, f)
    for i, f in fields
    if i > 0
]
```

The names are the comprehension's own. `elem` is worked out after the `for`s and `if`s, in
their order, as if it were appended in the loops' body, and what it is converts to the type
the array goes to: `let ids: [int64?] = [i for i in 0..3]`. Where the array goes nowhere that
says its type, it's an array of `elem`'s.

## Comparing

`==` and `!=` compare two arrays of the same type element by element: they are
equal when they have the same length and each element is `==` to the one at
the same place in the other.

```kod
[1, 2] == [1, 2]             // true
["a"] != ["a", "b"]          // true
[[1], [2, 3]] == [[1], [2, 3]]
```

The elements must have an `==` of their own, so an array of interface values,
functions or `shared struct`s without `op_eq` doesn't compare (see
[Operators](types.md)).

## As text

An f-string, `str(xs)` and `print(xs)` show an array as its elements in
brackets, separated by `, `, each as an f-string would show it:

```kod
print([1, 2, 3])             // [1, 2, 3]
print(f"{["a", "b"]}")       // [a, b]
print([[1], []])             // [[1], []]
```

A `str` element shows as its text, without quotes. The elements must have a
text of their own: an array of functions can't be shown.

## Iterating

**Index-based:**

<!-- kod: let nums: [int64] = [1, 2, 3, 4, 5] -->
```kod
mut i: int64 = 0
for i < len(nums) {
    print_int(nums[i])
    i = i + 1
}
```

**Foreach:**

<!-- kod: let nums: [int64] = [1, 2, 3, 4, 5] -->
```kod
for n in nums {
    print_int(n)
}
```

## Memory layout (compiler)

Arrays are represented as a header struct on the heap:

```
{ void* ptr, int64 len, int64 cap }
```

The `ptr` field points to a block of elements, each 8 bytes wide except in a
`[bool]`, whose elements are a byte each (a 1000-element `[bool]` takes 1000
bytes, not 8000). `len` is the number of live elements; `cap` is the
allocated capacity, in elements.

The header is counted like any other object, and the count says how many
places hold the array. Before changing an array, generated code checks that
the count is 1; if it isn't, `_kod_arr_unique` copies the header and the
elements, stores the copy where the array was, and lets go of the original.

`xs = xs[..n]`, which keeps the first elements of the array in `xs`, drops
the rest where the array is (a field written the same on both sides, as in
`s.items = s.items[..n]`, too), through `_kod_arr_truncate_at`, rather than making
a copy; `arrays.pop` uses it.

Appending (`+=`) goes through `_kod_arr_concat` in the runtime, which
writes into the existing buffer and reallocates it with doubled capacity
only when `cap` runs out. `+` goes through `_kod_arr_concat_new`, which
allocates a fresh header and buffer, and `*` through `_kod_arr_repeat`. Each
takes the element width from the compiler, which knows the type.

## Helpers

The `arrays` module has what's the same for an array of any type:

```kod
import "arrays"

arrays.contains(["a", "b"], "b")     // true
arrays.equal([1, 2], [1, 2])         // true
```

Elements compare with `==`, so `str`s by content, and a type that `==` doesn't
take is an error (see [Generic functions](functions.md#checking)).

| Function | Gives |
|----------|-------|
| `sum(xs)`, `sum_floats(xs)` | what `int64`s, or `float64`s, come to; 0 for none |
| `min(xs)`, `max(xs)` | the first of the smallest, or largest, elements by `<`; a `T?`, `none` when there are none |
| `any(xs)`, `all(xs)` | whether one of some `bool`s, or all of them, are true |
| `reversed(xs)` | the elements, last first, in a new array |
| `pop(mut xs)` | the last element, taken off `xs`; a `T?`, `none` when there are none |

With a comprehension, these are over anything:

<!-- kod:
import "arrays"
let words = ["pear", "fig"]
-->
```kod
let total = arrays.sum([len(w) for w in words])
let longest = arrays.max([len(w) for w in words])? or 0
assert arrays.all([w != "" for w in words])
```

## Sorting

The `sort` module's functions return a new array and leave the argument as it
is. They take O(n log n) comparisons and are stable: elements that compare equal
keep their order.

```kod
import "sort"

sort.sorted([3, 1, 2])       // [1, 2, 3]
sort.sorted(["b", "a"])      // ["a", "b"]
```

`sorted` orders by `<`, so it takes numbers, `str`s (by byte), and structs that
declare [`op_lt`](structs.md#operators). `sorted_by` takes the order as a
function that says whether its first argument goes before its second:

<!-- kod:
import "sort"
type Person = struct {
    name: str
    age: int64
}
let people = [Person(name: "ann", age: 41), Person(name: "bo", age: 29)]
-->
```kod
sort.sorted_by(people, less: func(a: Person, b: Person) -> bool {
    return a.age < b.age
})
```

`sorted_by_key` orders by what a function gives for each element, by `<`, and
calls it once per element:

<!-- kod:
import "sort"
type Person = struct {
    name: str
    age: int64
}
let people = [Person(name: "ann", age: 41), Person(name: "bo", age: 29)]
-->
```kod
sort.sorted_by_key(people, key: func(anon p: Person) -> int64 { return p.age })
```

## Heaps and deques

`Heap[T]` from the `heaps` module keeps its elements so that the smallest by `<`
comes out first, as a priority queue does. `push` and `pop` take O(log n), and
`peek` gives the smallest without taking it out. Both `pop` and `peek` give a
`T?`, `none` when the heap is empty. Elements that compare equal come out in
no particular order.

<!-- kod: import "heaps" { Heap } -->
```kod
mut todo = Heap[(int64, str)]()
todo.push((3, "c"))
todo.push((1, "a"))
todo.push((2, "b"))
assert (todo.pop()? or (0, "")) == (1, "a")
assert len(todo) == 2
```

A tuple compares its elements in order, so `(distance, node)` pairs come out
nearest first, as a shortest-path search wants them. For the largest first,
push the negated number or give the element type an `op_lt` that says so.

`Deque[T]` from the `deques` module is a queue open at both ends:
`push_back` and `push_front` add, `pop_front` and `pop_back` take an element
out and give it as a `T?`, and `front` and `back` look without taking. Each
takes O(1), counting the occasional doubling of its storage.

<!-- kod: import "deques" { Deque } -->
```kod
mut queue = Deque[int64]()
queue.push_back(1)
queue.push_back(2)
queue.push_front(0)
assert queue.pop_front() == 0
assert queue.pop_back() == 2
assert len(queue) == 1
```

Both are values, like arrays: a copy, `let saved = queue`, keeps what the queue
held when it was made. `len(h)` and `h.is_empty()` say how much is in either,
`h.values()` gives the elements as an array (a heap's in no particular order,
a deque's front to back), so `for x in d.values()` goes over a deque front to
back.
