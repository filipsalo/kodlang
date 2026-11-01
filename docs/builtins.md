---
icon: lucide/wrench
---

# Built-ins

These names live in `stdlib/builtins.kod` and are available in every Kod program without an explicit import.

A call without a module name, `f(args)`, goes to the first of these that
exists:

1. a struct named `f` that the module sees (`Pt(x: 1)` constructs even
   where a local named `Pt` is in force);
2. the innermost binding of `f` in force, when it holds a function value;
3. a function the module declares or lists in an `import`;
4. the builtin of that name.

A binding that holds anything else doesn't hide a function, so
`let len = len(xs)` and a later `len(ys)` both call the builtin. It does
hide any outer binding of its name: after `let g = double`, a call
`g(1)` in a block that binds `let g = 5` goes to the module's or the
builtin `g`. With neither, it is an error:
`` `g` is a local of type `int64`, not a function ``.

A function value declared in a block hides an outer one only inside that
block; after the block, `f(args)` calls the outer one again. With no
binding of `f` in force and no function of that name, the call is an
error: `` `f` is called before its `let` `` or
`` `f` is declared in a block that has ended; declare it outside the block to call it here ``.

The same holds for `len`, `str`, `hash` and `kod_panic`: a module can
declare its own `func hash(anon p: Point) -> int64`, and
its `hash(...)` calls use it, while another module's `dep.hash(x)` names
that one. An f-string always converts its values with the builtin `str`.
Only the builtin `kod_panic` counts as a call that never returns; a
module's own or imported `kod_panic`, or a local function value of that
name, is an ordinary call. A local named `kod_panic` that holds anything
else doesn't hide the builtin, so `kod_panic(msg)` after
`let kod_panic = 5` never returns.

## Output

| Function | Signature | Description |
|----------|-----------|-------------|
| `print` | `(str) -> none` | Print a string followed by a newline. |
| `print_int` | `(int64) -> none` | Print an integer followed by a newline. Equivalent to `print(n.to_str())`. |
| `kod_puts` | `(str) -> int64` | Write a string and a newline to stdout. What `print` calls; embedded NULs are written as-is. |
| `putchar` | `(int64) -> int64` | C `putchar`: write a single byte to stdout. Also runs in the interpreter, which shares libc's stdout buffer with `kod_puts`. |

## Length

| Function | Signature | Description |
|----------|-----------|-------------|
| `len` | `(str) -> int64` | String length in bytes. |
| `len` | `([T]) -> int64` | Number of elements in an array. |
| `len` | `(SomeStruct) -> int64` | Dispatches to the struct's `func len(self) -> int64` method if one exists (e.g. `Map.len`); a `len` method of any other shape is an error. |

As a value, `len` is its string form: `let n: func(str) -> int64 = len`.

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

The `hash(x)` builtin takes a hashable value: an `int64`, `str`, `bytes` or
`bool`, or a value of an enum whose variants have no payloads, which hashes
by variant. Hashing anything else, such as a struct, an array, an optional
or an enum with payload variants, is an error
(`` cannot hash a value of type `[int64]` ``). It gives what the methods
above give, a `bytes` value hashes like the `str` with the same bytes, and
an enum value hashes to its variant's position, counting from 1.

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

A lookup finds the entry whose key is `==` to the one it's given, so key
equality depends on the key type: `str` and `bytes` keys match by
content, `int64` and `bool` keys by value, and enum keys by variant.

The key type must be hashable, as for `hash(x)`: `int64`, `str`, `bytes`,
`bool` or an enum without payload variants. Any other key type, such as
`Map[[int64], int64]`, `Map[int64?, str]` or a struct, is an error at the
type argument that names it, in whichever module it's written
(`` `[int64]` can't be a `Map` key ``), reported once per key type. A key
that comes from another generic type's parameter is reported at the
argument of that type that is or holds the key: with
`type Index[V, K] = struct { m: Map[K, V] }`, a parameter of type
`Index[int64, Pt]` is an error at `Pt`
(`` `Pt` can't be a `Map` key in `Index[int64, Pt]` ``). A `Map[T, V]` in
a generic type's method names the instance whose `T` is the bad key
(`` `Pt` can't be a `Map` key in `Box[Pt]` ``); any other bad key in a
method, such as a `Map[Pt, int64]` written out in `Box[Pt]`, ends with the
instance it's compiled for, as other errors there do
(`` (in `Box[Pt]`) ``). The same holds for the element type of a
`Set[T]` from the `set` module.

## Indexing a struct

`m[k]` calls the struct's `op_index` and `m[k] = v` its `op_index_set`,
which is how `Map` supports both (`m[k]` is a `V?`, like `m.get(k)`).
`op_index` must take one key besides `self`, and `op_index_set` a key and
a value:

```kod
func op_index(self, anon key: K) -> V? { ... }
func op_index_set(self, anon key: K, anon value: V) -> none { ... }
```

The key and value must have those parameters' types, like a method's
arguments. `m[k] = v` evaluates `m`, then `k`, then `v` before the call,
and `m[k] += v` calls `op_index` and then `op_index_set` with the same `m`
and `k`, each evaluated once.

## Error handling

| Name | Description |
|------|-------------|
| `Error` (interface) | Marker for types that can be `throw`n. Requires `to_str(self) -> str`. |
| `ExitCode` (interface) | `exit_code(self) -> int64`, declared but not consulted yet: an `Err` that `main` returns exits with status 1 whatever it implements. |
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

// Read the whole file. Pipes and FIFOs (e.g. "/dev/stdin") are read
// until EOF. Returns "" if the file can't be opened or read.
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

`process.run(argv)` captures stdout and stderr. `process.exec(argv)` instead replaces the calling process with `argv[0]`, looked up on `PATH`: the new program has the same terminal, stdin and process id. Stdout is flushed first. If stdin is a pipe, input the program has already read into its buffer (as `io.read_stdin_line` does, beyond the line it asked for) is not handed on; a file or a terminal loses nothing. `exec` returns, with -1, only if `argv[0]` could not be run. Compiled programs only: the interpreter does not mirror its extern.

```kod
import "process"

func main() -> int64 {
    process.exec(["echo", "hello"])
    return 127  // not reached unless `echo` could not be run
}
```

## Environment variables

`stdlib/env.kod` reads and changes the process's environment. A program's
arguments come from `main(argv: [str])` (see [Functions](functions.md#main)).

```kod
import "env"

func main() -> int64 {
    let token = env.get("API_TOKEN")
    print(token? or "no token")
    env.set("MODE", "test")
    env.unset("API_TOKEN")
    return 0
}
```

| Function | Meaning |
|---|---|
| `get(name) -> str?` | the value, or `none` if the variable isn't set; a variable set to the empty string is `""`, not `none` |
| `set(name, value) -> none or Error` | set or replace it; the change is seen by programs started afterwards with `process.run` and `process.exec`; an empty `name`, one containing `=` or a NUL byte, and a `value` with a NUL byte are `InvalidInput` errors |
| `unset(name) -> none` | remove it; unsetting a variable that isn't set does nothing |

Compiled programs only: the interpreter does not mirror these externs.

## Extern (C runtime)

Available for re-declaration in any module if needed:

| Symbol | Description |
|--------|-------------|
| `_strlen` | C `strlen`. |
| `_arena_alloc` | Bump allocator for everything heap-shaped. |
| `_kod_str_concat`, `_kod_str_slice` | String operations the runtime exposes to codegen. |
| `_kod_sb_new`, `_kod_sb_append`, `_kod_sb_append_byte`, `_kod_sb_len`, `_kod_sb_clear`, `_kod_sb_to_str` | The growable buffer behind `StrBuilder` and the `str` methods `join`, `repeat`, `replace`, `lower` and `upper`; a handle is an `int64`. |
| `_kod_fd_open`, `_kod_fd_read`, `_kod_fd_write`, `_kod_fd_close`, `_kod_io_errno`, `_kod_errno_kind`, `_kod_errno_message` | Descriptor I/O and OS error numbers behind `stdlib/fd.kod` and `stdlib/stream.kod`; see [Streams](io.md). |
| `_kod_array_concat`, `_kod_array_concat_new` | Array append in place (`+=`) and concatenation into a new array (`+`). |
| `_kod_test_fail`, `_kod_test_summary` | Test runner internals. |
| `read_file`, `write_file` | File I/O. |

Direct use is rarely needed — the language-level operators cover most cases.
