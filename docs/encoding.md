---
icon: lucide/binary
---

# Encodings

## Base64

`stdlib/encoding/base64.kod` implements RFC 4648 base64, in both the standard
alphabet (`A-Z a-z 0-9 + /`) and the URL-safe one (`- _` in place of `+ /`).

```kod
import "encoding/base64"

let text = base64.encode_str("Aladdin:open sesame")
// QWxhZGRpbjpvcGVuIHNlc2FtZQ==

let raw = must base64.decode("QWxhZGRpbjpvcGVuIHNlc2FtZQ==")   // bytes
let back = base64.decode_str("QWxhZGRpbjpvcGVuIHNlc2FtZQ==")    // str or Error
```

| Function | Meaning |
|---|---|
| `encode(data: bytes, url: bool = false, pad: bool = true) -> str` | the base64 text of `data`; `url: true` uses the URL-safe alphabet; `pad: false` leaves out the trailing `=` |
| `encode_str(s: str, url: bool = false, pad: bool = true) -> str` | the same for the bytes of a `str` |
| `decode(text: str, url: bool = false) -> bytes or Error` | the bytes `text` stands for |
| `decode_str(text: str, url: bool = false) -> str or Error` | the same, as a `str` (the bytes are not checked to be UTF-8) |

Encoding is exact for any bytes, including NUL, and takes linear time.

Decoding is strict, so that two texts never stand for the same bytes by accident
and a mangled input is noticed:

- only the chosen alphabet is accepted: `+` and `/` are errors with `url: true`,
  and `-` and `_` are errors without it;
- no whitespace or line breaks are skipped (this is not MIME base64);
- padding is optional, but if it is there it must be exact: `Zg==` and `Zg` are
  both `f`, while `Zg=`, `Zg===`, `Z===`, `=Zg=` and `Zg==Zg==` are errors;
- a length that leaves a single character over (`Zm9vY`) is an error;
- the unused bits at the end must be zero, so `Zh==` (whose last character
  carries bits that `f` would not set) is an error.

Errors are `IoError`s of kind `InvalidInput`, with `op` `base64 decode` and a
`detail` that names the byte offset of the problem where there is one.

## Percent-encoding

For URLs and query strings, see [HTTP client](http.md#query-strings-and-percent-encoding).
