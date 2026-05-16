---
icon: lucide/wrench
---

# Built-ins

These functions are available in every Kod program without an explicit import (they live in `stdlib/builtins.kod`).

## Output

| Function | Signature | Description |
|----------|-----------|-------------|
| `print` | `(str) -> none` | Print a string followed by a newline |
| `print_int` | `(int64) -> none` | Print an integer followed by a newline |
| `putchar` | `(int64) -> int64` | Write a single byte (ASCII value) to stdout |

## String

| Function | Signature | Description |
|----------|-----------|-------------|
| `int_to_str` | `(int64) -> str` | Convert an integer to its decimal string representation |
| `len` | `(str) -> int64` | Length of a string in bytes |

## Array

| Function | Signature | Description |
|----------|-----------|-------------|
| `len` | `([T]) -> int64` | Number of elements in an array |

!!! note
    `len` is overloaded — it works on both strings and arrays.

## Math / integers

Standard arithmetic (`+`, `-`, `*`, `/`, `%`) and comparisons (`==`, `!=`, `<`, `<=`, `>`, `>=`) are built into the language, not functions.

## Extern (C runtime)

These are available via `extern` declarations in builtins and can be re-declared in any module:

| Symbol | Description |
|--------|-------------|
| `_strlen` | C `strlen` |
| `_arena_alloc` | Arena allocator used by the runtime |
| `_kod_str_concat` | String concatenation |
| `_kod_str_slice` | String slicing |
| `_kod_arr_concat` | Array concatenation |

Direct use of these is not recommended; use the language-level operators instead.

## I/O

File I/O is available via `extern` wrappers. The stdlib includes `read_file`:

```kod
import "io"
let contents: str = io.read_file("data.txt")
```
