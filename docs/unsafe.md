---
icon: lucide/triangle-alert
---

# Calling C with unsafe

`stdlib/unsafe.kod` lets Kod code call C functions that take buffers, write
results through pointers, or deal in C strings. It reads and writes raw
memory, so nothing checks what it does: a wrong address or size corrupts
the program or crashes it, without an error that says why. Code that
uses it says so with `import "unsafe"`, and the rest of the program
doesn't need it.

```kod
import "unsafe"

extern func pipe(anon fds: int64) -> int64
extern func getenv(anon name: int64) -> int64

func make_pipe() -> [int64] {
    let fds = unsafe.alloc(8)               // room for two C ints
    if unsafe.c_int(pipe(fds)) < 0 {
        panic(f"pipe failed: errno {unsafe.errno()}")
    }
    let ends = [unsafe.load32(fds), unsafe.load32(fds + 4)]
    unsafe.free(fds)
    return ends
}

func home() -> str {
    let name = "HOME"
    let value = getenv(unsafe.c_str(name))  // a `char *`, or 0
    if value == 0 {
        return ""
    }
    return unsafe.str_at(value)             // a copy in a Kod `str`
}
```

## Addresses

An address is an `int64`, and arithmetic on it is ordinary arithmetic:
`fds + 4` is four bytes further on. Pass one to an `extern` parameter of
type `int64` where C takes a pointer, and take one back the same way. 0
is C's `NULL`.

| Function | Meaning |
|----------|---------|
| `alloc(size)` | `size` bytes of zeroed memory, from C's heap; a program that runs out of memory panics |
| `free(addr)` | give back what `alloc` returned; 0 does nothing |
| `load8(addr)` | the byte at `addr`, 0 to 255 |
| `load32(addr)` | the 4 bytes at `addr` as a signed C `int` |
| `load64(addr)` | the 8 bytes at `addr` |
| `store8(addr, v)`, `store32(addr, v)`, `store64(addr, v)` | write the low 1, 4 or 8 bytes of `v` at `addr` |
| `copy_out(addr, n)` | the `n` bytes at `addr` as a new `bytes` |
| `copy_in(addr, data)` | write the bytes of `data` at `addr` |

Memory from `alloc` isn't counted or freed for you: free it when C is done
with it. Loads and stores are single instructions; 4- and 8-byte ones should
be at an address that is a multiple of their size, as C would place them.

## Strings and bytes

| Function | Meaning |
|----------|---------|
| `c_str(s)` | the address of the bytes of the `str` `s`, followed by a 0 byte: a `char *` for C to read |
| `data(b)` | the address of the bytes of the `bytes` `b`, for C to read |
| `str_at(addr)` | a copy of the C string at `addr`, up to its 0 byte, as a `str` |

`c_str` and `data` don't copy: the address is good only while `s` or `b`
is, so keep the value in a variable for as long as C uses the address,
and don't let C change the bytes. A `str` with a 0 byte inside looks
shorter to C; check for one first where that matters. To give C a buffer it
writes into, `alloc` one and `copy_out` what it wrote.

## C's int and errno

| Function | Meaning |
|----------|---------|
| `c_int(x)` | the low 4 bytes of `x` as a signed C `int` |
| `errno()` | C's `errno` for this thread, as the last failed call left it |

A C function that returns `int` leaves the upper half of the 8-byte result
undefined, so wrap its result in `c_int` before comparing it: `-1` may
otherwise read as `4294967295`. A function returning `long`, `ssize_t`,
`size_t` or a pointer fills all 8 bytes. Read `errno()` straight after the
call that failed: anything else in between, a `print` too, may change it.

## What doesn't fit

- C functions that take a variable number of arguments, such as `open`,
  `fcntl` and `printf`, pass them in a way an `extern` doesn't. Call them
  through a small C function instead (see
  [Link inputs](modules.md#link-inputs)).
- A C function that takes or returns a `struct` by value, or a `float` or
  `double`. Pointers to structs are fine: `alloc` the bytes C's layout
  needs and `load`/`store` the fields at their offsets.
- A function pointer, for a callback: a Kod function value isn't one.
