---
icon: lucide/arrow-left-right
---

# Streams and I/O errors

`stdlib/stream.kod` defines the error type and the two interfaces that byte
streams share, and `stdlib/fd.kod` implements them over file descriptors:
files, standard input and output and, later, sockets. Code that reads or
writes takes a `Reader` or a `Writer` and doesn't care what is behind it.

```kod
import "stream" { Reader, read_all }
import "fd" { open_read }

func count_bytes(anon r: Reader) -> int64 or Error {
    let data = try read_all(r)
    return len(data)
}

func main() -> int64 or Error {
    let f = try open_read("data.bin")
    print_int(try count_bytes(f))
    try f.close()
    return 0
}
```

## Errors

Every operation that can fail returns `T or Error` and throws an `IoError`:

```kod
type IoKind = enum {
    NotFound
    PermissionDenied
    AlreadyExists
    InvalidInput
    WouldBlock
    TimedOut
    ConnectionRefused
    ConnectionReset
    BrokenPipe
    UnexpectedEof
    Other
}

type IoError = struct {
    kind: IoKind
    op: str        // what was attempted: "open data.bin", "read", "write"
    errno: int64   // the OS error number, 0 if the error didn't come from the OS
    detail: str    // the OS's message, or a short explanation
}
```

`to_str` gives `open data.bin: No such file or directory`. Recover the kind
with a downcast:

```kod
match open_read(path) {
    Ok(f) -> use(f)
    Err(e) ->
        if e is IoError(io) and io.kind == .NotFound {
            print("no such file")
        } else {
            print(e.to_str())
        }
}
```

`kind_of_errno(errno)` maps an OS error number to an `IoKind`; anything it
doesn't know is `Other`. An interrupted system call is retried inside the
runtime, so `EINTR` never reaches a caller.

## Reader and Writer

```kod
interface Reader {
    func read(self, anon max: int64) -> bytes or Error
}

interface Writer {
    func write(self, anon data: bytes) -> int64 or Error
}
```

`read` returns between 1 and `max` bytes, waiting until there is something to
return, and returns an empty `bytes` at the end of the stream. With
`max <= 0` it returns an empty `bytes` without reading, so don't call it that
way to test for the end. `write` returns how many bytes it accepted, which
may be fewer than `len(data)`; an empty `data` writes nothing and returns 0.

| Function | Meaning |
|----------|---------|
| `read_all(r)` | read until the end of the stream; `bytes or Error` |
| `read_exact(r, n)` | exactly `n` bytes, or an `UnexpectedEof` error; `bytes or Error` |
| `write_all(w, data)` | write every byte, repeating `write` as needed; a `write` that accepts 0 bytes of a non-empty `data` is an `Other` error (`write returned 0`); `none or Error` |
| `write_str(w, s)` | `write_all` of a `str` |

## In-memory streams

`MemReader(data: bytes, pos: 0)` reads from a `bytes` value, which is how
tests and parsers get a stream without a file. `MemWriter(buf: StrBuilder())`
collects what is written, and `to_bytes()` / `to_str()` return a copy of it.
Neither can fail.

## BufReader

`BufReader` wraps any `Reader` with a buffer, for protocols that mix lines
and counted bodies such as HTTP:

```kod
let br = BufReader(inner: conn)
let status = try br.read_line()          // str?, none at the end of the stream
let body = try br.read_exact(length)     // takes what is buffered first
```

| Method | Meaning |
|--------|---------|
| `read(max)` | a `Reader`: the buffered bytes first, else one read of the inner stream |
| `read_exact(n)` | exactly `n` bytes, or `UnexpectedEof` |
| `read_until(delim)` | the bytes up to and excluding the byte `delim`, which is consumed; `bytes?`, none at the end of the stream; the last piece comes back even without a delimiter |
| `read_line()` | `read_until(10)` as a `str`, minus a trailing `\r` (`str?`) |

Fields: `inner`, `limit: int64 = 1048576` (a `read_until` or `read_line` longer
than this fails with an `InvalidInput` error `line too long` instead of
growing without bound), `chunk: int64 = 8192` (the size of each inner read).
A `BufReader` doesn't close its inner stream.

## Files and descriptors

`Fd` is a file descriptor and implements both `Reader` and `Writer`:

| Function | Meaning |
|----------|---------|
| `open_read(path)` | an existing file for reading |
| `create(path)` | a file for writing, created (mode `0644`) or truncated |
| `append(path)` | a file for writing, created if missing, written at its end |
| `stdin()`, `stdout()`, `stderr()` | descriptors 0, 1 and 2 |
| `Fd(fd: n)` | wrap a descriptor from elsewhere |
| `f.close()` | close it; `none or Error` |

`stdout()` writes straight to descriptor 1, bypassing the buffer that `print`
uses. Call `flush_stdout()` first when you mix the two.
Closing is explicit: an `Fd` that is dropped stays open until the program
exits.

The older `io.read_file` and `io.write_file` keep their behavior: an empty
string or `-1` on failure, with no reason.
