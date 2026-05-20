---
icon: lucide/type
---

# Strings

Strings in Kod are UTF-8 byte sequences. The type is `str`.

## Literals

```kod
let s: str = "hello, world"
```

Standard escape sequences are supported: `\n`, `\t`, `\\`.

## F-strings

Interpolate expressions into strings with `f"..."`:

```kod
let name: str = "world"
print(f"hello, {name}!")          // hello, world!

let n: int64 = 42
print(f"the answer is {n}")       // the answer is 42
```

Anything inside `{ }` is a Kod expression. Non-`str` values are auto-converted via their `to_str` method:

```kod
print(f"{a} + {b} = {a + b}")
print(f"flag={true}")             // flag=true
print(f"items: {items.len()}")    // any type with to_str works
```

## Concatenation

Use `+` to concatenate strings, or `+=` to append in place:

```kod
let greeting: str = "hello" + ", " + name + "!"

let buf: str = "lines:\n"
buf += "  one\n"
buf += "  two\n"
```

`+=` works on struct fields too: `obj.message += " (cont.)"`.

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

Escape sequences (`\n`, `\t`, `\\`) work the same as regular strings.
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

## Slicing

```kod
let sub: str = s[2:5]   // bytes at positions 2, 3, 4
```

## Comparison

```kod
if s == "hello" {
    print("match")
}
if s != "bye" {
    print("not bye")
}
```

String equality compares contents, not identity.

## Conversion

Primitives have a `to_str` method:

```kod
let s: str = 42.to_str()           // "42"
let t: str = true.to_str()         // "true"
let u: str = "hi".to_str()         // identity
```

Structs can opt in by declaring `func to_str(self) -> str`. F-string interpolation calls `to_str` automatically.

See [Built-ins](builtins.md) for the full list of string-related functions.
