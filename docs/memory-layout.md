---
icon: lucide/memory-stick
---

# Memory Layout

This document describes how Kod values are represented in memory at runtime.

## Primitive types

Primitive values are stored directly — on the stack in local variables, or
passed by value in registers.

| Type    | Width | Representation                                         |
| ------- | ----- | ------------------------------------------------------ |
| `int64` | 8     | Two's-complement 64-bit int                            |
| `float64` | 8   | IEEE 754 binary64 bit pattern, in an integer slot      |
| `str`   | 8     | Pointer to null-terminated C string in `.data` section |
| `bool`  | 1     | 0 (false) or 1 (true)                                  |
| `none`  | 8     | Always 0 (null sentinel)                               |

## Struct values

Struct variables are **reference types**: the variable holds an 8-byte pointer
to the struct's data, which lives on the [heap](#the-heap).

```
stack slot (8 bytes)          heap memory
┌──────────────┐              ┌──────────────┐
│   pointer ───┼─────────────▶│   field 0    │  offset 0
└──────────────┘              │   field 1    │  offset 8
                              │   ...        │
                              └──────────────┘
```

Fields are laid out sequentially in declaration order, each at its natural
alignment. The total allocation size (`data_width`) is the sum of all field
widths.

### Example: `Point`

```
type Point = struct {
    x: int64    // offset 0, width 8
    y: int64    // offset 8, width 8
}
```

- `data_width` = 16 (allocated on the heap)
- `width` = 8 (size of the pointer stored in a stack slot)

### Reference semantics

Assigning a struct variable copies the pointer, not the data:

```
let p = Point(x: 3, y: 4)
let q: Point = p        // q and p point to the same object
q.x = 10               // also modifies p.x
```

The same holds for any expression that yields a struct, such as a call, a
`match` expression, `x? or fallback` or `try f()`: the binding stores the
pointer the expression produced.

### Arrays of small structs

An array whose elements are a plain struct or a tuple of two to four fields,
each an `int64`, a `float64`, a `bool` or an enum whose variants carry
nothing, keeps each element's fields in its own buffer, one after another,
instead of a pointer to a cell per element. A `[(int64, int64)]` element is 16
bytes in the array and nothing else; a `Map` or `Set` keeps its keys in an array,
so finding a key reads the fields where they are instead of following a pointer.

```
[(1, 2), (3, 4)]     buffer:  1 | 2 | 3 | 4        (8 bytes each)
```

Reading a field (`xs[i].x`), comparing or hashing an element, storing one, and
appending one from another such array (`ys += [xs[i]]`) work on the fields in
place. Reading an element whole, to pass it to a function or keep it, makes a
cell holding a copy of it. Inside a loop each such read and each `for x in xs`
keeps one cell, used again on the next pass unless something kept the last
one, so a loop over the elements allocates nothing in the usual case. A struct
with a `mut self` method still has it: the method changes a copy, which goes
back into the array when it returns.

A struct with a field of another kind, a `shared struct`, or one with an
`op_index_set` method is kept as a pointer, as before.

## Enum values

Enums are **heap-allocated**, like structs. A stack slot holds an 8-byte
pointer; the cell at the pointer is:

```
[offset 0]  discriminant : int64  (variant index starting from 1)
[offset 8]  payload      : max(variant payload sizes) bytes
```

Because enum variables are pointers, they fit in a single register and pass
through the ARM64 calling convention without any multi-word ABI gymnastics.

A variant without a payload has one cell per module, in the module's data,
with its discriminant and zeroes for the payload: `.Up` or `TokenKind.EOF`
is the address of that cell, so making one allocates nothing. The cell is
outside the counted heap, so counting it does nothing either, and it is
never freed. An enum none of whose variants has a payload has no other values,
so the compiler doesn't count them at all.

See `docs/enums.md` for details.

## Union values

A union is an enum the compiler writes, with one variant per member, so its
value is a pointer to a cell of the same shape: the discriminant says which
member it holds, and the payload is that member's 8-byte value. Members are
numbered in a fixed order worked out from the types themselves, so a union is
laid out the same in every module however it's spelled. A struct, enum or other
reference held in a union is a pointer to its own cell, so it costs a second
allocation. A `T | none` is a `T?` with an optional's layout; the optional of a
larger union is an optional cell holding a pointer to a union cell.

## Reclaiming memory

Kod counts references. Every struct, enum value, optional cell, interface cell,
array and computed string has a count, and it is freed when the count reaches 0,
as are the references it held. A program does nothing to make this happen: there
is no `free`, no scope to declare and no collector that pauses it, and a server
that handles requests for days stays the size its live data needs.

**A cycle is never freed.** Two values that refer to each other keep each other
alive after the last outside reference is gone:

A value can't refer to itself, so only shared structs (see
[Structs](structs.md)) make one:

```kod
type Node = shared struct {
    name: str
    other: Node?
}

let a = Node(name: "a", other: none)
let b = Node(name: "b", other: a)
a.other = b  // a and b now live until the program exits
```

A closure makes a cycle easy to write without seeing it: a closure stored in a
struct it captures keeps that struct alive, as in
`req.on_done = func() { req.count += 1 }`. That costs nothing for something that
lives as long as the program, and leaks once per `req` for something made per
request.

Make the back reference a [weak field](structs.md#weak-fields) and the cycle
doesn't form: a `weak` field doesn't keep its value alive, and reads as `none`
once the value is freed.

```kod
type Node = shared struct {
    name: str
    weak other: Node?
}
```

Otherwise break the cycle when you are done with it (`a.other = none`), or keep
the back reference as an index or a key instead of a struct. A closure's
captures can't be weak. Most data, including all of the compiler's, has no
cycles.

A weak field holds a small counted box with the value's address, made the first
time anything refers to that value weakly and shared by every weak field that
does; freeing the value empties the box. A value nothing refers to weakly costs
nothing extra.

Memory that has been freed is used again for new values but isn't returned to the
OS, so a program stays as big as it has ever been. There are no threads, so counts
aren't atomic.

### The heap

Counted objects live in one reserved address range of 64 GB (`stdlib/rc.c`), so
whether a pointer is counted is a check on its address, and string literals and
vtables need no count. A program that fills the range stops with
`rc: the counted heap is full`.

The 8 bytes before an object hold its header:

```
[offset -8]  count      : 32 bits
[offset -4]  size class :  8 bits
[offset -3]  slot mask  : 24 bits
[offset  0]  the object
```

Bits 0 to 20 of the mask say which 8-byte slots of the object hold references,
which is what freeing follows. Bit 21 marks an array whose elements are references,
bit 22 an array, and bit 23 an object with references past slot 20, whose block
ends in a pointer to a descriptor of them in the data section.

A block comes from the free list of its size class, or else from the end of the
used part of the range. Classes go up in steps of 16 bytes to 1 KB and in powers of
two after that.

### What generated code does

- A call returns a reference its caller owns. A value a statement computes and
  doesn't keep is released when the statement ends.
- A store into a variable, field or element retains the new value and releases the
  old one. When the value is fresh the store takes the reference over instead.
- A function borrows its parameters: a parameter costs nothing unless the body
  assigns to it. So that what it borrows can't go away, a caller holds a value it
  read from a field or element for the length of the statement.
- A pattern borrows what it binds from an enum's payload when the subject is a
  variable the function never assigns to: the subject keeps the payload alive for
  as long as the binding can be used. A binding that shares its slot with one the
  function owns (the same name bound another way, or assigned to) is owned too.
- `for x in xs` borrows each element: the loop holds the array, so `x` costs
  nothing unless the function assigns to it, or its slot is owned for the same
  reasons as a pattern's binding.
- A function releases its variables when it returns, except that a `let` or
  `mut` local holding an array or a struct that isn't shared (a map or set
  too) is released after the last statement of its block that uses it; a
  use inside a loop or a nested block counts for the whole statement. What
  it shared is then the other holder's alone, and changing it doesn't copy
  it. A local that a function literal captures, or that a `let-else` binding
  borrows from, lives as long as that does.

`retain` and `release` are calls with the object in `x17`, to `_rc_retain_stub` and
`_rc_release_stub`. They change only `x16`, `x17` and `lr`, and no flags, until an
object is freed, and freeing saves the rest, so they can sit anywhere in an
expression.

Every reference a function owns is in a slot of its frame, 0 while it holds
nothing, whenever the function calls anything that may panic. So when a
[catch](panics.md) takes a panic, each function between is let go of by
releasing its slots, which a row of the `__DATA,__kod_unwind` section lists
(`emit_unwind_row` in `codegen.kod`, `kod_unwind` in `runtime.c`). A `mut`
parameter's slot is put back into the caller's instead, and a map entry that
was being changed back into its map.

### Function values

A function value is a reference to a cell whose first word is the address of the
code. A named function or a literal that captures nothing has one such cell in the
data section, written only if the function is used as a value, and using it never
allocates. A literal that captures allocates a counted cell each time it's
evaluated, with the captured values after the code address:

```
closure cell:  [code, capture 0, capture 1, ...]
```

A call through a function value is `ldr x16, [f]; mov x17, f; blr x16`, so a
function reached that way finds its cell in `x17`. One that captures copies the
values into its frame on entry and borrows them, like parameters, since its caller
keeps the cell alive for the call. A [local function](functions.md#local-functions)
also keeps `x17` itself as the value of its own name, so a call to itself passes
the same cell on. Other functions ignore `x17`.

A `mut` that a literal captures is kept in a counted one-word struct from its
declaration on (`_MutCell[T]` in `builtins.kod`). The function's slot and each
closure that captures it hold a reference to the struct, and a read or an
assignment loads or stores its word. The parser makes the change, so codegen
sees an ordinary `let` of a struct and `n.value` for each use of `n`.

### Testing for mistakes

To test the rules themselves, build the runtime so that freed memory is overwritten
and never used again, by putting this in `link.local.cfg` and running the tests:

```
CFLAGS := -target arm64-apple-darwin -I stdlib -O2 -DRC_POISON
```

A use after free then shows as wrong output or a crash. `-DRC_STATS` adds counts of
allocations and frees, printed at exit when `KOD_RC_STATS` is set. A program can
declare `extern func rc_live_bytes() -> int64` to ask how much of the heap is in use.

## Calling convention (ARM64, macOS)

- Arguments: passed in `x0`–`x7`
- Return value: in `x0`
- Caller-saved: `x0`–`x15`
- Callee-saved: `x19`–`x28`
- Frame pointer: `fp` (`x29`)
- Link register: `lr` (`x30`)

Since struct variables are 8-byte pointers, they fit in a single register
and can be passed to and returned from functions normally.

### Stack frame

A function pushes `fp` and `lr`, points `fp` at them and keeps each local
in an 8-byte slot below `fp`, including the compiler's own temporaries.
Values that must survive a call in the middle of an expression are pushed
below those slots. The epilogue restores `sp` from `fp`, so a `try` that
returns from inside an expression, such as an array literal element or a
call argument, leaves the stack as the function found it.
