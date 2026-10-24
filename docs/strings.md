---
icon: lucide/type
---

# Strings

Strings in Kod are UTF-8 byte sequences. The type is `str`.

## Literals

```kod
let s: str = "hello, world"
```

Supported escape sequences:

| Escape | Meaning |
|--------|---------|
| `\n` | newline |
| `\t` | tab |
| `\r` | carriage return |
| `\0` | NUL byte |
| `\\` | backslash |
| `\"` | double quote |
| `\'` | single quote |

There are no `\x..` or `\u{...}` escapes yet. For any other escape the
backslash and the character after it are both dropped, so `"\x41"` is
`"41"`. Non-ASCII UTF-8 can be written directly in the source.

## F-strings

Interpolate expressions into strings with `f"..."`:

```kod
let name: str = "world"
print(f"hello, {name}!")          // hello, world!

let n: int64 = 42
print(f"the answer is {n}")       // the answer is 42
```

Anything inside `{ }` is a Kod expression, string literals and nested
f-strings included (`f"[{f"<{n}>"}]"`, `f"{"}" + s}"`). Non-`str` values are auto-converted via their `to_str` method:

```kod
print(f"{a} + {b} = {a + b}")
print(f"flag={true}")             // flag=true
print(f"items: {items.len()}")    // any type with to_str works
```

Interpolations are evaluated left to right, like the operands of `+`, `==`
and the other operators, so in `f"{bump(:c)} then {c.n}"` the second part
sees what `bump` did.

What can be interpolated:

- `str`, and `bytes` as-is
- `int64` and `bool`
- a struct that declares `func to_str(self) -> str`
- a value of an interface that declares the same `to_str`, such as
  `Stringable` or `Error`; the call goes to the concrete type's `to_str`

Anything else is a compile error for now: an optional (`T?`), an enum, an
array, a function value, and a struct or interface without a
`func to_str(self) -> str`, including one whose `to_str` takes arguments
or returns something else.
Unwrap an optional first, e.g. `f"{n? or 0}"`.

## Concatenation

Use `+` to concatenate strings, or `+=` to append in place:

```kod
let greeting: str = "hello" + ", " + name + "!"

mut buf: str = "lines:\n"
buf += "  one\n"
buf += "  two\n"
```

`+=` works on struct fields too: `obj.message += " (cont.)"`.

Both operands of `+` must be `str`; nothing else is converted, so
`"n = " + 5` is an error. Convert with `str(...)` or use an f-string:
`"n = " + str(n)` or `f"n = {n}"`. `bytes` concatenate only with `bytes`.

## Multi-line strings

Triple-quoted strings span multiple lines:

```kod
let preamble: str = """
    .text
    .globl _main
    _main:
    """
```

The closing `"""` must sit on its own line. Its indent anchors the
dedent — every content line has at least that many leading spaces (or
tabs) stripped. The newline immediately after the opening `"""` is
not part of the value; the newline before the closing `"""` is. So
the example above produces:

```
.text
.globl _main
_main:
```

(four-space indent gone; trailing newline kept).

Combine with `f` for interpolation:

```kod
let asm: str = f"""
    bl ${mangled}$main
    ret
    """
```

Escape sequences work the same as in regular strings.
Each content line must be indented at least as far as the closing
`"""`; a content line with less indent is a lex error.

## Length

```kod
let n: int64 = len(s)
```

## Character access

Index into a string to get the ASCII value of a character (as `int64`):

```kod
let c: int64 = s[0]   // 'h' → 104
```

Negative indices count from the end:

```kod
let last: int64 = s[-1]
```

The index must be an `int64`, so `s["a"]` is an error.

Strings are immutable, so assigning to an element (`s[0] = 'H'`) is an
error. A `str` can't be iterated with `for … in` either; iterate over
`s.code_points()` instead.

## Slicing

```kod
let sub: str = s[2..5]   // bytes at positions 2, 3, 4
```

Either endpoint may be omitted: `s[..k]` is `s[0..k]` and `s[k..]` is `s[k..len(s)]`. `s[..]` returns a copy.

Both endpoints clamp to `[0, len(s)]`: a negative bound becomes 0 and a bound
past the end becomes `len(s)`, so `"hello"[3..40]` is `"lo"`. An end before
the start yields `""`. Unlike indexing, slice bounds never wrap. Both
bounds must be `int64`. `bytes` slices follow the same rules.

## Comparison

```kod
if s == "hello" {
    print("match")
}
if s != "bye" {
    print("not bye")
}
```

String equality compares contents, not identity. `<`, `<=`, `>` and `>=`
order two strings byte by byte, a prefix before the longer string:
`"apple" < "apples" < "zebra"`. The same holds for two `bytes` values.

## Conversion

Primitives have a `to_str` method:

```kod
let s: str = 42.to_str()           // "42"
let t: str = true.to_str()         // "true"
let u: str = "hi".to_str()         // identity
```

Structs can opt in by declaring `func to_str(self) -> str`. F-string interpolation calls `to_str` automatically.
`str(x)` converts the same values an f-string interpolates, and rejects the
same ones.

See [Built-ins](builtins.md) for the full list of string-related functions.
