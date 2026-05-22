---
icon: lucide/braces
---

# JSON

`stdlib/json.kod` parses and emits JSON.

## Quick example

```kod
import "json"

let v: json.Value = json.parse("[1, 2, 3]")
// v is Array([Number(1), Number(2), Number(3)])

let s: str = json.emit(v)
// s is "[1,2,3]"
```

## The `Value` type

```kod
type Value = enum {
    Null
    Bool(value: bool)
    Number(value: int64)        // int64 only — floats not supported
    Str(value: str)
    Array(items: [Value])
    Object(keys: [str], values: [Value])
}
```

Object entries are stored as parallel arrays (`keys[i]` ↔ `values[i]`)
rather than a separate `Entry` struct, so the type stays
single-recursive.

## Accessors

Free functions (Kod doesn't yet support methods on enums) that return
`T?` so callers can chain via `let .Some(v) = ... else`:

| Function | Returns |
|---|---|
| `get(v: Value, key: str) -> Value` | Object lookup. Returns `Null` if the key is missing or `v` isn't an Object. |
| `as_str(v: Value) -> str?` | Unwrap to a string, `none` if not `Str`. |
| `as_int(v: Value) -> int64?` | Unwrap to an integer, `none` if not `Number`. |
| `as_bool(v: Value) -> bool?` | Unwrap to a bool, `none` if not `Bool`. |

```kod
let .Some(method) = json.as_str(json.get(req, key: "method")) else { return }
let .Some(id) = json.as_int(json.get(req, key: "id")) else { return }
```

## Limitations

- Numbers are int64 only.
- String escapes: `\n \t \r \" \\ \/`. No `\uXXXX`.
- Strict JSON: no trailing commas, no comments.
- Parse failure currently panics rather than returning an error type.
