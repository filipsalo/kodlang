---
icon: lucide/list
---

# Arrays

Arrays in Kod are resizable, homogeneous sequences. The type is `[T]` where `T` is the element type.

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

```kod
let first: int64 = nums[0]
let last: int64 = nums[-1]    // negative index counts from end
let third: int64 = nums[2]
```

Negative indices wrap around: `arr[-1]` is equivalent to `arr[len(arr) - 1]`.
An index must be an `int64`: `nums["a"]`, `nums[true]` and an `int64?`
index such as `nums[m.get(k)]` are errors.

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
`for … in` needs an array. Anything else is a compile error.

An assigned element must have the array's element type, with the same
conversions as a `let`: `names[0] = 5` on a `[str]` is an error, while
`xs[0] = 42` on an `[int64?]` and `pets[0] = Cat()` on a `[Pet]` wrap and
box the value. On a struct, the key of `m[k]` and the key and value of
`m[k] = v` must have the types of `op_index`'s and `op_index_set`'s
parameters (see [Indexing a struct](builtins.md#indexing-a-struct)), so
`m[5]` on a `Map[str, int64]` is an error.

A store evaluates its parts left to right: in `rows()[i()] = v()` and
`m[k()] = v()` the receiver comes first, then the index or key, then the
value, and `f().x = v()` calls `f` before `v`. A compound
`rows()[i()] += v()` evaluates the receiver and the index once, reads the
element and then evaluates `v()`, so `rows` and `i` are each called once.
Indexing a struct calls its `op_index`, so it counts as a call too:
`xs[a[k]] += b[k]` calls `a`'s `op_index` once, before `b`'s.

## Length

```kod
let n: int64 = len(nums)
```

## Slicing

```kod
let sub: [int64] = nums[1..4]   // elements 1, 2, 3
let prefix: [int64] = nums[..3]  // first three
let suffix: [int64] = nums[3..]  // from index 3 onward
let copy: [int64] = nums[..]     // shallow copy
```

Both endpoints clamp to `[0, len]`: a negative bound becomes 0 and a bound past
the end becomes `len`, so `[1, 2, 3][1..10]` is `[2, 3]`. An end before the
start yields an empty slice. Unlike indexing, slice bounds never wrap.
Both bounds must be `int64`.

## Concatenation

Use `+=` to append elements or extend with another array:

```kod
mut a: [int64] = [1, 2]
a += [3, 4]          // a is now [1, 2, 3, 4]
```

Or `+` to produce a new array; neither operand is modified:

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

`+=` appends to the array itself, not to a copy, so everything that holds
the same array sees the new elements: after `let a = xs` and `xs += [3]`,
`a` ends in 3 too. That holds for an array kept in a field or in another
array (`rows[0] += [4]`) as well, and for an array passed to a function that
appends to its parameter. A `for x in xs` loop also reaches the elements
appended to `xs` while it runs.

The one exception is a `mut` binding that starts from an existing array, a
variable, a field or an element: it gets a copy of its own, so appending to
it leaves the original alone.

```kod
mut ys = xs            // a copy of xs
ys += [4]              // xs is unchanged
```

A `mut` binding that starts from a call, a literal or an expression such as
`xs + []` already holds an array nobody else has, so nothing is copied.
To keep the old contents in any other case, copy the array first with
`xs + []` or `xs[..]`. All of these copies are shallow: the inner arrays of a
`[[T]]` are still shared.

## Iterating

**Index-based:**

```kod
let i: int64 = 0
for i < len(nums) {
    print_int(nums[i])
    i = i + 1
}
```

**Foreach:**

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

The `ptr` field points to a block of elements, each 8 bytes wide. `len` is the number of live elements; `cap` is the allocated capacity.

Appending (`+=`) goes through `_kod_array_concat` in the runtime, which
writes into the existing buffer and reallocates it with doubled capacity
only when `cap` runs out. `+` goes through `_kod_array_concat_new`, which
allocates a fresh header and buffer.

## Helpers

The `arrays` module has what's the same for an array of any type:

```kod
import "arrays"

arrays.contains(["a", "b"], "b")     // true
arrays.equal([1, 2], [1, 2])         // true
```

Elements compare with `==`, so `str`s by content, and a type that `==` doesn't
take is an error (see [Generic functions](functions.md#checking)).

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

```kod
sort.sorted_by(people, less: func(a: Person, b: Person) -> bool {
    return a.age < b.age
})
```
