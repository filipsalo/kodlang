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

## Compression

`stdlib/compress/deflate.kod` compresses into the three formats that
[`compress/inflate`](#decompression) reads, written in Kod like it.

```kod
import "compress/deflate"

let packed = deflate.gzip(kod_str_to_bytes(text))
let quick = deflate.gzip(data, level: 1)
```

| Function | Meaning |
|---|---|
| `gzip(data: bytes, level: int64 = 6) -> bytes` | a gzip file (RFC 1952) of one member, with no name and a zero time |
| `zlib(data: bytes, level: int64 = 6) -> bytes` | a zlib stream (RFC 1950) |
| `raw(data: bytes, level: int64 = 6) -> bytes` | a raw deflate stream (RFC 1951) |

`level` trades speed for size as zlib's does: `0` only frames the data (stored
blocks), `1` to `3` take the first good match, and `4` to `9` look further back and
put off a match when the next byte starts a longer one; `9` is the smallest and
slowest. A level outside `0..9` is taken as the nearest one. Each block is written
whichever way is smallest: stored, with the standard codes, or with Huffman codes
made for its own data, so data that doesn't compress grows by only about 5 bytes
every 16 KB.

## Decompression

`stdlib/compress/inflate.kod` decompresses gzip, zlib and raw deflate data. It is
written in Kod, like [compressing](#compression), so it links no C library.

```kod
import "compress/inflate"

let text = kod_bytes_to_str(must inflate.gunzip(data))
```

| Function | Meaning |
|---|---|
| `gunzip(data: bytes, max_output: int64 = 16777216) -> bytes or Error` | a gzip file (RFC 1952); several members one after the other give their output joined, like `gunzip` does |
| `inflate_zlib(data: bytes, max_output: int64 = 16777216) -> bytes or Error` | a zlib stream (RFC 1950) |
| `inflate_raw(data: bytes, max_output: int64 = 16777216) -> bytes or Error` | a raw deflate stream (RFC 1951) |

`max_output` is the most bytes the result may have. Decompression stops as soon as
it would be exceeded, so a few kilobytes of input cannot make the program allocate
gigabytes; the buffer grows only as output is produced. Errors are `IoError`s of
kind `InvalidInput`, with `op` the function's name and a `detail` that says what was
wrong: `output too large`, `truncated`, or the wording zlib uses for corrupt data
(`incorrect header check`, `invalid block type`, `incorrect data check` for a
checksum that does not match, `incorrect length check`, `invalid distance too far
back`). Bytes after the last gzip member
are an error, and so is a stream that ends before its final block.

## Percent-encoding

For URLs and query strings, see [HTTP client](http.md#query-strings-and-percent-encoding).
