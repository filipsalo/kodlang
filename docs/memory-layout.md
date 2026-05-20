# Memory Layout

This document describes how Kod values are represented in memory at runtime.

## Primitive types

Primitive values are stored directly — on the stack in local variables, or
passed by value in registers.

| Type    | Width | Representation              |
|---------|-------|-----------------------------|
| `int64` | 8     | Two's-complement 64-bit int |
| `str`   | 8     | Pointer to null-terminated C string in `.data` section |
| `bool`  | 1     | 0 (false) or 1 (true) |
| `none`  | 8     | Always 0 (null sentinel)    |


## Struct values

Struct variables are **reference types**: the variable holds an 8-byte pointer
to the struct's data, which lives in the global arena.

```
stack slot (8 bytes)          arena memory
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

- `data_width` = 16 (allocated in arena)
- `width` = 8 (size of the pointer stored in a stack slot)

### Reference semantics

Assigning a struct variable copies the pointer, not the data:

```
let p = Point(x: 3, y: 4)
let q: Point = p        // q and p point to the same object
q.x = 10               // also modifies p.x
```


## Enum values

Enums are **arena-allocated**, like structs. A stack slot holds an 8-byte
pointer; the cell at the pointer is:

```
[offset 0]  discriminant : int64  (variant index starting from 0)
[offset 8]  payload      : max(variant payload sizes) bytes
```

Because enum variables are pointers, they fit in a single register and pass
through the ARM64 calling convention without any multi-word ABI gymnastics.

See `docs/enums.md` for details.


## The global arena

All struct allocations go into a single implicit arena, backed by a
linked-list bump allocator in `stdlib/arena.c`. The user never interacts
with the arena directly — struct constructors allocate into it automatically.

### Allocator design

- Initial block: 4 MB (allocated via `malloc`)
- When a block is full, a new block of at least 4 MB is linked in
- Allocations are aligned to 8 bytes
- Memory is never freed during a program run (the OS reclaims it on exit)

This is appropriate for compiler workloads, where all data is allocated
upfront and the process exits when done.

### Entry point

```c
void *arena_alloc(int64_t size);
```

Called internally by the compiler whenever a struct is constructed. Not
exposed to Kod programs directly.


## Calling convention (ARM64, macOS)

- Arguments: passed in `x0`–`x7`
- Return value: in `x0`
- Caller-saved: `x0`–`x15`
- Callee-saved: `x19`–`x28`
- Frame pointer: `fp` (`x29`)
- Link register: `lr` (`x30`)

Since struct variables are 8-byte pointers, they fit in a single register
and can be passed to and returned from functions normally.
