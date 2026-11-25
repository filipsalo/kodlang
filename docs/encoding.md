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

<!-- kod:
let text = "to be or not to be, that is the question"
let data = kod_str_to_bytes(text)
-->
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

### Compressing piece by piece

Data that is made a piece at a time, or is too long to hold, is compressed into a
[`Writer`](io.md#reader-and-writer) as it is written:

<!-- kod:
import "posix"
func rows() -> [str] {
    return ["a", "b"]
}
-->
```kod
let out = try posix.create("rows.gz")
let packed = deflate.gzip_writer(out)
for row in rows() {
    try packed.write_str(row)
}
try packed.finish()
try out.close()
```

`gzip_writer(to: Writer, level: int64 = 6)`, `zlib_writer` and `raw_writer` give a
`DeflateWriter`, itself a `Writer`. What is written goes to `to` as it is
compressed, 64 KB at a time, and takes a megabyte of memory or less however long it
is.

| Method | Meaning |
|---|---|
| `flush() -> none or Error` | sends all that has been written, so that it can be decompressed, though the stream goes on; each costs a few bytes and some of the compression |
| `finish() -> none or Error` | ends the stream, with its checksum; `to` isn't closed. Without it the data isn't whole. After it, writing is an `InvalidInput` error, and another does nothing |

## Decompression

`stdlib/compress/inflate.kod` decompresses gzip, zlib and raw deflate data. It is
written in Kod, like [compressing](#compression), so it links no C library.

<!-- kod: let data = deflate.gzip(kod_str_to_bytes("hello, hello")) -->
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

### Piece by piece

Data that comes from a `Reader`, or is too long to hold, is decompressed as it is
read:

<!-- kod:
import "stream" { MemReader }
let from = MemReader(data: deflate.gzip(kod_str_to_bytes("hello, hello")), pos: 0)
-->
```kod
let plain = inflate.gunzip_reader(from)
for true {
    let piece = try plain.read(65536)
    if len(piece) == 0 {
        break
    }
    print(len(piece))
}
```

| Function | Meaning |
|---|---|
| `gunzip_reader(from: Reader) -> InflateReader` | a gzip file, as `gunzip` |
| `zlib_reader(from: Reader) -> InflateReader` | a zlib stream |
| `raw_reader(from: Reader) -> InflateReader` | a raw deflate stream |
| `deflate_reader(from: Reader) -> InflateReader` | a zlib stream, or a raw one when it doesn't begin as a zlib stream does (as HTTP's `deflate` may be) |

An `InflateReader` is a [`Reader`](io.md#reader-and-writer) of the decompressed
data, which takes a few hundred KB of memory however long that is. It gives what it has
before it waits for more compressed data, so what a sender has flushed isn't held
up. There is no `max_output`: stop reading when there is too much.

A read fails as the functions above do, with the same details and `op` `inflate`,
once what was good before it has been read, and goes on failing. The checksum comes
last, so the data isn't known to be whole until the end has been read. An error of `from` is
given as it is. A gzip file is read to the end of `from`; after the others, `from`
may have been read past their end, by as much as it gave.

## Percent-encoding

For URLs and query strings, see [HTTP client](http.md#query-strings-and-percent-encoding).
