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
| `\{`, `\}` | a brace: in an f-string, one that doesn't start or end an interpolation, as in `f"\{\"n\": {n}\}"` |
| `\xHH` | the byte `HH`, two hex digits (`00` to `FF`) |
| `\u{H...}` | a Unicode character, 1 to 6 hex digits, written as UTF-8 |

`\x` gives a single byte, so `"\xC3\xA9"` and `"\u{e9}"` are both `é` (two bytes), while
`"\xE9"` is one byte that isn't valid UTF-8 by itself. A string may hold any bytes. A
`\u{...}` must be a Unicode scalar value: at most `10FFFF`, and not a surrogate
(`D800` to `DFFF`).

A malformed `\x` or `\u` is an error: a `\x` without two hex digits, a `\u` without
braces, an empty or unterminated `\u{}`, more than six digits, or a value that isn't a
scalar value. So is any other escape, such as `"\d"`: a backslash that stands for
itself is written `\\`, or the string is written raw (below). Non-ASCII UTF-8 can also
be written directly in the source. Character literals (`'a'`) take the simple escapes
only.

### Raw strings

`r"..."` is a string whose text is taken as it is written: a backslash is a
backslash, and nothing is an escape. It ends at the next `"`, so it can't hold one;
`r"""..."""` can, and is dedented as a `"""` string is. Raw strings suit text full of
backslashes, such as [regular expressions](regex.md) and Windows paths:

```kod
let digits = r"\d+(\.\d+)?"            // the same as "\\d+(\\.\\d+)?"
let path = r"C:\Users\kod"
let quoted = r"""
    say "\n" for a newline
    """                                  // say "\n" for a newline, and a newline
```

Byte literals (`b"..."`) and f-strings take the same escapes. In an f-string, the braces of
`\u{...}` are part of the escape, not an interpolation: `f"\u{e9}{n}"` is `é` followed by
the value of `n`.

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

<!-- kod:
let a = 1
let b = 2
let items = [1, 2, 3]
-->
```kod
print(f"{a} + {b} = {a + b}")
print(f"flag={true}")             // flag=true
print(f"items: {len(items)}")    // any type with to_str works
```

Interpolations are evaluated left to right, as are the operands of an
operator or a [comparison chain](types.md#boolean-literals), the parts of
`xs[i]` and `xs[lo..hi]`, and the receiver, index and value of a store
such as `xs[i] = v`, so in `f"{bump(:c)} then {c.n}"` the second part
sees what `bump` did.

What can be interpolated:

- `str`, and `bytes` as-is
- `int64` and `bool`
- a struct, by its `func to_str(self) -> str` if it declares one; otherwise a plain
  `struct` as its name and fields, `Point(x: 1, y: 2)` (see
  [Structs are values](structs.md#structs-are-values))
- an array, as its elements in brackets (see [As text](arrays.md#as-text))
- a value of an interface that declares the same `to_str`, such as
  `Stringable` or `Error`; the call goes to the concrete type's `to_str`
- an enum, by its `func to_str(self) -> str` if it declares one, and
  otherwise as the name of its variant: `f"{c}"` is `Red`, and an `Op.Lit(n: 4)`
  is `Lit`, without its payload. A `T or Error` isn't one of these: test it first

`print(x)` takes the same values as `{x}` does.

Anything else is a compile error: an optional (`T?`), a function value, and a
`shared struct` or interface without a `func to_str(self) -> str`, including one whose
`to_str` takes arguments or returns something else.
Unwrap an optional first, e.g. `f"{n? or 0}"`.

The braces hold one expression, which may be followed by a format spec.

### Format specs

After a `:`, a format spec says how wide the text is and how a number is
written, as in Python:

```kod
let n = 42
let x = 3.14159
let name = "kod"
print(f"[{n:5}] [{n:<5}] [{n:^5}] [{n:05}] [{n:+}]")  // [   42] [42   ] [ 42  ] [00042] [+42]
print(f"{x:.2} {x:8.3} {x:e} {0.25:.1%}")            // 3.14    3.142 3.141590e+00 25.0%
print(f"{255:x} {255:#X} {5:08b} {1234567:,}")        // ff 0XFF 00000101 1,234,567
print(f"[{name:>6}] [{name:*^7}] [{"truncated":.5}]")  // [   kod] [**kod**] [trunc]
```

The parts, in this order, each optional:

| Part | Meaning |
|------|---------|
| fill and align | `<` left, `>` right, `^` centred, after an optional fill character (a space if none). Numbers align right and everything else left unless told otherwise. |
| sign | `+` writes a `+` before a positive number, and a space writes a space there; a negative number always has its `-`. |
| `#` | Puts `0x`, `0X`, `0o` or `0b` before a number written in that base. |
| `0` | Pads a number with zeros after its sign and base prefix, to the width. |
| width | The least number of characters (code points); a longer value isn't cut. |
| `,` or `_` | Groups the digits of a decimal number in threes, or with `_` those of a hex, octal or binary number in fours. |
| `.precision` | For a float, the digits after the point; for a string, the most characters to keep. |
| type | For an `int64`: `d` decimal (the default), `x` and `X` hex, `o` octal, `b` binary. For a `float64`: `f` fixed point (six digits after the point unless a precision says), `e` exponent form (`3.141590e+00`), `%` the value times 100 with a `%`. For a string: `s`. |

A float without a type or precision is written as `{x}` writes it, then
padded; with a precision and no type, it has that many digits after the point.
Digits are rounded correctly from the float's exact value, ties to even. A
`bool`, an enum or a struct is formatted as the text `{x}` gives it, so only
the fill, align, width and precision apply.

A spec that doesn't fit the value is a compile error: `{n:.2}` on an
`int64`, `{x:x}` on a `float64`, `{name:05}` on a `str`. The spec is written
out, so `{n:{w}}` with a width taken from a variable is an error too.

The same specs are also methods: `n.format("05")`, `x.format(".2")` and
`s.format(">10")` give what `f"{n:05}"` and the others do.

## Concatenation

Use `+` to concatenate strings, or `+=` to append in place:

<!-- kod: let name = "world" -->
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

<!-- kod: let mangled = "_kod" -->
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

<!-- kod: let s = "hello" -->
```kod
let n: int64 = len(s)
```

## Character access

Index into a string to get the ASCII value of a character (as `int64`):

<!-- kod: let s = "hello" -->
```kod
let c: int64 = s[0]   // 'h' → 104
```

Negative indices count from the end:

<!-- kod: let s = "hello" -->
```kod
let last: int64 = s[-1]
```

The index must be an `int64`, so `s["a"]` is an error.

Strings are immutable, so assigning to an element (`s[0] = 'H'`) is an
error. `for … in` over a `str` gives its bytes, as `s[i]` does; for text,
iterate over `s.code_points()` instead.

## Slicing

<!-- kod: let s = "hello" -->
```kod
let sub: str = s[2..5]   // bytes at positions 2, 3, 4
```

Either endpoint may be omitted: `s[..k]` is `s[0..k]` and `s[k..]` is `s[k..len(s)]`. `s[..]` returns a copy.

A negative bound counts from the end, as an index does: `"hello"[..-1]` is `"hell"`
and `"hello"[-3..]` is `"llo"`. Then both endpoints clamp to `[0, len(s)]`, so
`"hello"[3..40]` is `"lo"` and `"hello"[-9..2]` is `"he"`. An end before the start
yields `""`. Both bounds must be `int64`. `bytes` slices follow the same rules.

## Comparison

<!-- kod: let s = "hello" -->
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
"3-5".split_once("-")                  // ("3", "5"), as a (str, str)?
"".split(",")                          // [""]
"abc".split("")                        // ["abc"]
"a\r\nb\n".lines()                      // ["a", "b"]
" 1  2\t3\n".split_whitespace()          // ["1", "2", "3"]
"  hi\r\n".trim()                     // "hi"
"  hi ".trim_start()                   // "hi "
"  hi ".trim_end()                     // "  hi"
", ".join(["a", "b", "c"])             // "a, b, c"
"ab".repeat(3)                         // "ababab"
"a-b-c".replace("-", to: "+")        // "a+b+c"
```

`split` always returns at least one element and keeps empty pieces, so
`sep.join(s.split(sep)) == s` for a non-empty `sep`. An empty separator
doesn't split. `split_once` gives what is before the first `sep` and what is after
it, or `none` when `sep` isn't there, so `let (k, v) = must line.split_once(": ")`
takes a line apart. `lines` splits at each `\n` and drops a `\r` before it; a newline at
the end makes no empty line after it, so `"".lines()` is `[]`. `split_whitespace`
gives the pieces between runs of space, tab, `\n` and `\r`, with no empty ones.
`trim` removes space, tab, `\n`, `\r` from the ends. `replace`
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
pieces does quadratic work. Use a `StrBuilder` for that:

<!-- kod: let body = b"<html></html>" -->
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
| `append_int(n: int64)` | add `n` in decimal, as `n.to_str()` writes it, without making that string |
| `len() -> int64` | bytes so far |
| `clear()` | drop the content, keep the capacity |
| `to_str() -> str` | a copy of the content; the builder stays usable |
| `to_bytes() -> bytes` | the same as `bytes` |

The buffer doubles when it is full, so appending n bytes costs O(n) overall.
`to_str` makes a `StrBuilder` usable in an f-string. Embedded NUL bytes are
kept. A `StrBuilder` is a handle: copies of it (`let b = a`) share one buffer.

## Building bytes

A `ByteBuffer` is a growable buffer of bytes that, unlike a `StrBuilder`, can
read back what it holds and copy from itself. Decompressors are what it is
for: [`compress/inflate`](encoding.md#decompression) writes its output into
one, and the compiler builds its object files in them.

```kod
import "bytebuffer" { ByteBuffer }

let out = ByteBuffer()
out.push_bytes(b"ab")
out.push(0x63)
out.copy_back(distance: 3, length: 7)
assert out.to_bytes() == b"abcabcabca"
assert out.at(2) == 0x63
```

| Method | Meaning |
|--------|---------|
| `push(b: int64)` | add one byte; only the low 8 bits are used |
| `push_bytes(b: bytes)` | add bytes |
| `push_le(value: int64, size: int64)` | add the low `size` bytes of `value`, lowest first (little-endian); `size` from 0 to 8 |
| `push_buffer(other: ByteBuffer)` | add the bytes of `other` |
| `copy_back(distance: int64, length: int64)` | add `length` bytes, each a copy of the one `distance` before it, so a `distance` shorter than `length` repeats the last `distance` bytes |
| `drop_front(n: int64)` | drop the first `n` bytes |
| `slice(from: int64, to: int64) -> bytes` | a copy of the bytes from `from` up to `to` |
| `at(i: int64) -> int64` | the byte at `i`, 0 to 255 |
| `set(i: int64, b: int64)` | replace the byte at `i`; only the low 8 bits of `b` are used |
| `len() -> int64` | bytes so far |
| `to_bytes() -> bytes` | a copy of the content; the buffer stays usable |

`at` and `set` panic for an index outside `0..len()`, `push_le` for a `size`
outside `0..8`, and `copy_back` for a `distance` outside `1..len()` or a
negative `length`, the way indexing an array out of range does. The buffer
doubles when it is full. Like a `StrBuilder`, a `ByteBuffer` is a handle:
copies of it share one buffer.

## Conversion

Primitives have a `to_str` method:

```kod
let s: str = 42.to_str()           // "42"
let t: str = true.to_str()         // "true"
let u: str = "hi".to_str()         // identity
```

A struct can have its own by declaring `func to_str(self) -> str`. F-string interpolation calls `to_str` automatically.
`str(x)` converts the same values an f-string interpolates, and rejects the
same ones.

See [Built-ins](builtins.md) for the full list of string-related functions.
