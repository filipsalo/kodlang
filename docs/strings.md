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

Interpolations are evaluated left to right, as are the operands of an
operator or a [comparison chain](types.md#boolean-literals), the parts of
`xs[i]` and `xs[lo..hi]`, and the receiver, index and value of a store
such as `xs[i] = v`, so in `f"{bump(:c)} then {c.n}"` the second part
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

## Searching and comparing

All of these work on bytes. For text that must be split at code points, use
`code_points()` or `char_slice`.

```kod
"GET /index".starts_with("GET")        // true
"a.kod".ends_with(".kod")              // true
"hello".contains("ell")                // true
"hello".find("l")                      // 2, an int64?
"hello".find("l", from: 3)             // 3
"hello".find("z")                      // none
"abc".strip_prefix("a")                // "bc", a str?
"abc".strip_suffix("x")                // none
```

`find` returns the byte offset of the first match at or after `from`
(default 0; a `from` outside the string is clamped into it). The empty string
is found at `from`. `strip_prefix` and `strip_suffix` return `none` when the
string doesn't start or end that way. `""` is a prefix and a suffix of every
string.

## Splitting, trimming and joining

```kod
"a,b,,c".split(",")                    // ["a", "b", "", "c"]
"".split(",")                          // [""]
"abc".split("")                        // ["abc"]
"  hi\r\n".trim()                     // "hi"
"  hi ".trim_start()                   // "hi "
"  hi ".trim_end()                     // "  hi"
", ".join(["a", "b", "c"])             // "a, b, c"
"ab".repeat(3)                         // "ababab"
"a-b-c".replace("-", to: "+")        // "a+b+c"
```

`split` always returns at least one element and keeps empty pieces, so
`sep.join(s.split(sep)) == s` for a non-empty `sep`. An empty separator
doesn't split. `trim` removes space, tab, `\n`, `\r` from the ends. `replace`
replaces every non-overlapping match from the left; an empty `old` replaces
nothing. `repeat` with a count of 0 or less gives `""`.

## Case and numbers

```kod
"Content-Length".lower()               // "content-length"
"abc".upper()                          // "ABC"
"-42".parse_int()                      // -42, an int64?
"4x".parse_int()                       // none
"".parse_int()                         // none
```

`lower` and `upper` change only ASCII letters and leave other bytes alone.
`parse_int` accepts an optional `-` or `+` followed by one or more decimal
digits and nothing else (no spaces); it returns `none` for anything else and
for a value outside the `int64` range.

## Building strings

`+=` copies the whole string every time, so a loop that appends thousands of
pieces does quadratic work and leaves every intermediate copy in memory (the
arena never frees). Use a `StrBuilder` for that:

```kod
import "strbuilder" { StrBuilder }

let out = StrBuilder()
out.append("HTTP/1.1 200 OK")
out.append("\r\n")
out.append_byte(10)
out.append_bytes(body)
print(out.to_str())
```

| Method | Meaning |
|--------|---------|
| `append(s: str)` | add a string |
| `append_bytes(b: bytes)` | add raw bytes |
| `append_byte(b: int64)` | add one byte; only the low 8 bits are used |
| `len() -> int64` | bytes so far |
| `clear()` | drop the content, keep the capacity |
| `to_str() -> str` | a copy of the content; the builder stays usable |
| `to_bytes() -> bytes` | the same as `bytes` |

The buffer doubles when it is full, so appending n bytes costs O(n) overall.
`to_str` makes a `StrBuilder` usable in an f-string. Embedded NUL bytes are
kept. A `StrBuilder` is a handle: copies of it (`let b = a`) share one buffer.

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
