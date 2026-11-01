---
icon: lucide/braces
---

# JSON

`stdlib/json.kod` parses and emits JSON, strictly as RFC 8259 defines it.

## Quick example

```kod
import "json"

func main() -> int64 or Error {
    let v = try json.parse("{\"name\": \"kod\", \"tags\": [1, 2.5, \"\\u00e9\"]}")
    let name = json.as_str(json.get(v, key: "name"))
    print(name? or "?")                       // kod
    print(json.emit(v))                       // {"name":"kod","tags":[1,2.5,"é"]}
    print(json.emit_pretty(v))
    return 0
}
```

## Parsing

```kod
func parse(anon src: str, max_depth: int64 = 512) -> Value or Error
```

Malformed input is an error you can handle, never a panic. The error is a
`JsonError`, which carries where it went wrong:

```kod
type JsonError = struct {
    message: str     // "unexpected character", "unterminated string", ...
    offset: int64    // byte offset in the input
    line: int64      // 1-based
    column: int64    // 1-based, in bytes
}
```

Its `to_str` reads `json: unexpected character at line 2, column 7`. Recover
it with a downcast (`e is JsonError(je)`, see
[Types](types.md#recovering-the-concrete-error-type)).

What the parser accepts is exactly JSON text: one value, with optional
whitespace (space, tab, newline, carriage return) around it. It rejects, with an
error saying what and where:

- an empty input, text after the value, and a missing or doubled comma,
  colon or bracket;
- trailing commas, comments, single quotes, unquoted keys, `NaN`,
  `Infinity` and a leading `+`;
- numbers like `01`, `-`, `1.`, `.5`, `1e` and `0x10`;
- a raw control character (below U+0020) inside a string;
- an escape other than `\" \\ \/ \b \f \n \r \t \uXXXX`;
- a `\u` escape that isn't four hex digits, and an unpaired surrogate
  (`\ud800` not followed by `\udc00`..`\udfff`, or a lone low surrogate);
- nesting deeper than `max_depth`, which stops `[[[[...` from exhausting the
  stack. Depth counts the arrays and objects around a value, so `max_depth: 1`
  allows `[1]` and not `[[1]]`.

A UTF-8 byte order mark at the start is skipped. Bytes of 0x80 and up inside
strings are taken as they are: the parser doesn't check that they are valid
UTF-8.

## The `Value` type

```kod
type Value = enum {
    Null
    Bool(value: bool)
    Number(value: int64)
    Str(value: str)
    Array(items: [Value])
    Object(keys: [str], values: [Value])
    Decimal(text: str)
}
```

An integer that fits in `int64` is a `Number` (`-0` is `Number(0)`). Any other
number is a `Decimal`: one with a fraction or an exponent (`2.5`, `1e3`,
`-0.0`), or an integer too large for `int64`. A `Decimal` keeps the number's
text exactly as it was written, so nothing is rounded and it is written back
unchanged; Kod has no floating-point type to hold it. `\uXXXX` escapes are
decoded into UTF-8, with a surrogate pair giving one four-byte character, and
`\u0000` gives a NUL byte inside the `str`.

Object entries are stored as parallel arrays (`keys[i]` is the key of
`values[i]`), in the order they were written. A repeated key is kept, and
`get` finds the first.

## Accessors

Free functions (Kod has no methods on enums). None of them can fail: they
return `Null` or `none` when the value isn't what you asked for, so
`get(get(v, key: "a"), key: "b")` is safe on any input.

| Function | Returns |
|---|---|
| `get(v, key)` | the first value of that key in an object; `Null` if the key is missing or `v` isn't an object |
| `at(v, index)` | the element of an array; `Null` if out of range or `v` isn't an array |
| `as_str(v)` | `str?`, for a `Str` |
| `as_int(v)` | `int64?`, for a `Number` (a `Decimal` is `none`, even `3.0`) |
| `as_bool(v)` | `bool?`, for a `Bool` |
| `as_array(v)` | `[Value]?`, for an `Array` |
| `as_number_text(v)` | `str?`, the text of a `Number` or a `Decimal` |
| `is_null(v)` | `bool` |

## Building values

Constructing a `Value` by hand means `.Object(keys: [...], values: [...])` with
two arrays that must stay in step. Two builders do the bookkeeping:

```kod
let body = json.ObjectBuilder()
body.put_str("title", "a bug")
body.put_int("priority", 2)
body.put_bool("urgent", false)
body.put("labels", json.array_of([.Str(value: "bug"), .Str(value: "ui")]))
let text = json.emit(body.build())
// {"title":"a bug","priority":2,"urgent":false,"labels":["bug","ui"]}
```

| Method | Meaning |
|---|---|
| `put(key, value)` | add an entry with any `Value`; entries keep the order they were added in, and a repeated key is added again |
| `put_str(key, s)`, `put_int(key, n)`, `put_bool(key, b)`, `put_null(key)` | the same for the common cases |
| `build() -> Value` | the `Object`; the builder can go on being used |

`array_of(items: Items) -> Value` makes an `Array` from a `[Value]`; `str_value(s)`,
`int_value(n)` and `bool_value(b)` make the scalar `Value`s, for building those
arrays.

## Emitting

```kod
func emit(anon v: Value) -> str
func emit_pretty(anon v: Value, indent: int64 = 2) -> str
```

`emit` writes compact JSON with no spaces. `emit_pretty` puts each array
element and object entry on its own line, indented by `indent` spaces per
level, with `": "` after a key; an empty array or object is `[]` or `{}`, and
there is no newline at the end. Both write strings with `\"`, `\\`, `\b`,
`\f`, `\n`, `\r`, `\t` and `\u00XX` for any other control character, and leave
everything else, UTF-8 included, as it is. The text of a `Decimal` is written
verbatim; a `Decimal` built by hand whose text isn't a JSON number is written
as `null`, so the output is always valid JSON.

`emit(parse(s))` and `s` mean the same JSON, with these exceptions: the
whitespace, the choice of escapes in strings, and `-0` written as `0`.
