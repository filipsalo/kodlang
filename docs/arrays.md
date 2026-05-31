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

Both endpoints clamp to `[0, len]`; out-of-range bounds yield an empty slice.

## Concatenation

Use `+=` to append elements or extend with another array:

```kod
let a: [int64] = [1, 2]
a += [3, 4]          // a is now [1, 2, 3, 4]
```

Or `+` to produce a new array:

```kod
let c: [int64] = a + b
```

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

Appending (`+=`) allocates a new backing buffer via `_kod_arr_concat` in the runtime.
