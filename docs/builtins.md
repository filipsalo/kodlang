---
icon: lucide/wrench
---

# Built-ins

These names live in `stdlib/builtins.kod` and are available in every Kod program without an explicit import.

## Output

| Function | Signature | Description |
|----------|-----------|-------------|
| `print` | `(str) -> none` | Print a string followed by a newline. |
| `print_int` | `(int64) -> none` | Print an integer followed by a newline. Equivalent to `print(n.to_str())`. |
| `puts` | `(str) -> int64` | C `puts`. |
| `putchar` | `(int64) -> int64` | Write a single byte to stdout. |

## Length

| Function | Signature | Description |
|----------|-----------|-------------|
| `len` | `(str) -> int64` | String length in bytes. |
| `len` | `([T]) -> int64` | Number of elements in an array. |
| `len` | `(SomeStruct) -> int64` | Dispatches to the struct's `len(self) -> int64` method if one exists (e.g. `Map.len`). |

## String conversion

There is no `int_to_str` builtin — primitives carry their own `to_str` methods:

```kod
let s: str = 42.to_str()      // "42"
let t: str = true.to_str()    // "true"
let u: str = "hi".to_str()    // identity
```

F-strings interpolate non-`str` values by calling `to_str` automatically:

```kod
print(f"n = {42}")            // n = 42
```

## Hashing

```kod
let h: int64 = "hello".hash()
let g: int64 = 99.hash()
```

`int64.hash` is the identity function; `str.hash` is djb2; `bool.hash` is 0/1.
Used internally by `Map[K, V]`.

## `Map[K, V]`

A built-in generic. Open-addressing hash map (PEP 468 dense + sparse).

```kod
let m: Map[str, int64] = Map[str, int64]()
m.set("a", 1)
m.set("b", 2)
match m.get("a") {
    Some(v) -> print(v.to_str())
    none -> print("miss")
}
print(len(m).to_str())   // 2
```

## Error handling

| Name | Description |
|------|-------------|
| `Error` (interface) | Marker for types that can be `throw`n. Requires `to_str(self) -> str`. |
| `ExitCode` (interface) | Optional refinement: a custom `exit_code(self) -> int64` controls the process exit when `main` returns an `Err`. |
| `kod_panic` (extern) | Print `panic: <msg>\n` to stderr and `exit(1)`. Used by `must` and by `assert` outside a test. |
| `kod_eprint` (extern) | Write to stderr without exiting. |

## Testing

| Name | Description |
|------|-------------|
| `fail(msg)` | Mark the current `test "..." {}` as failed; outside a test, no-op. |
| `assert <expr>` | Statement form. Inside a test, flag on `false`; outside, panic. Source text is captured at parse time. See [Testing](testing.md). |

## I/O

The `io` module wraps the filesystem primitives. Both calls require
`import "io"` — touching the filesystem is explicit at the import line.

```kod
import "io"

// Read whole file. Returns "" if the file can't be opened.
let contents: str = io.read_file("data.txt")

// Write a file, replacing it if it exists. Returns 0 on success,
// -1 on failure. The parent directory must already exist.
let rc: int64 = io.write_file("out.txt", "hello\n")
```

For subprocess support, see `stdlib/process.kod`:

```kod
import "process"

let r: process.ProcessResult = process.run(["echo", "hello"])
assert r.status == 0
assert r.stdout == "hello\n"
```

## Extern (C runtime)

Available for re-declaration in any module if needed:

| Symbol | Description |
|--------|-------------|
| `_strlen` | C `strlen`. |
| `_arena_alloc` | Bump allocator for everything heap-shaped. |
| `_kod_str_concat`, `_kod_str_slice` | String operations the runtime exposes to codegen. |
| `_kod_array_concat` | Array concatenation. |
| `_kod_test_fail`, `_kod_test_summary` | Test runner internals. |
| `read_file`, `write_file` | File I/O. |

Direct use is rarely needed — the language-level operators cover most cases.
