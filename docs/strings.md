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
print(f"the answer is {int_to_str(n)}")
```

Anything inside `{ }` is a Kod expression. Multiple interpolations:

```kod
print(f"{a} + {b} = {int_to_str(a + b)}")
```

!!! note
    `int64` values must be converted to `str` explicitly (e.g. `int_to_str(n)`) before interpolation. There is no implicit conversion.

## Concatenation

Use `+` to concatenate strings:

```kod
let greeting: str = "hello" + ", " + name + "!"
```

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

```kod
let s: str = int_to_str(42)    // "42"
```

See [Built-ins](builtins.md) for the full list of string-related functions.
