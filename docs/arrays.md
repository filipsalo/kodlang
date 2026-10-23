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

## Indexing

```kod
let first: int64 = nums[0]
let last: int64 = nums[-1]    // negative index counts from end
let third: int64 = nums[2]
```

Negative indices wrap around: `arr[-1]` is equivalent to `arr[len(arr) - 1]`.

Arrays nest: an element of a `[[int64]]` is an `[int64]`, so `grid[i][j]`
and `for row in grid { for x in row { ... } }` work, and an element of a
`[bool]` is a `bool`.

A literal takes its element type from where it goes, at any depth: a
`let`, an assignment, an argument, a field, an enum payload, a return value
(including a match arm's), or an element or `Map` value it's stored as. In
`let g: [[Shape]] = [[Sq(s: 3)]]`, `shapes += [Sq(s: 4)]` or
`return [none, 3]` from a `-> [int64?]` function, each struct is boxed as the
interface and each value wrapped as the optional. In a `[Direction]`,
`[.North, .South]` builds `Direction` variants even when another enum
declares variants of those names, and in a `[Maybe[int64]]`,
`[.Just(value: 1), .Nothing]` builds `Maybe[int64]` ones.

Arrays, `str` and `bytes` can be indexed, and so can a struct that declares
an `op_index` method (`Map` does). Element assignment needs an array or a
struct with `op_index_set`, slicing needs an array, `str` or `bytes`, and
`for … in` needs an array. Anything else is a compile error.

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
