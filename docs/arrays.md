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
an interface: `let shapes: [Shape] = [Sq(s: 1), Circle(r: 1)]`.

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
`xs = xs + [x]` costs O(len(xs)); prefer `xs += [x]` in loops.

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

The `ptr` field points to an arena-allocated block of elements, each 8 bytes wide. `len` is the number of live elements; `cap` is the allocated capacity.

Appending (`+=`) goes through `_kod_array_concat` in the runtime, which
writes into the existing buffer and reallocates it with doubled capacity
only when `cap` runs out. `+` goes through `_kod_array_concat_new`, which
allocates a fresh header and buffer.
