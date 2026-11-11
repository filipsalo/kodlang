---
icon: lucide/arrow-left-right
---

# Streams and I/O errors

`stdlib/stream.kod` defines the error type and the two interfaces that byte
streams share, and `stdlib/posix.kod` implements them over file descriptors:
files, standard input and output and, later, sockets. Code that reads or
writes takes a `Reader` or a `Writer` and doesn't care what is behind it.

```kod
import "stream" { Reader, read_all }
import "posix" { open_read }

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
    WouldBlock      // reserved; nothing returns it yet
    TimedOut
    ConnectionRefused
    ConnectionReset
    BrokenPipe
    UnexpectedEof
    Other
    HostNotFound
    Tls
    Protocol
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
doesn't know is `Other`. `EAGAIN` is `TimedOut`, because a descriptor here is
only ever non-blocking through a timeout (see [TCP](#tcp)). `HostNotFound` is
for a name that doesn't resolve and has no OS error number (`errno` is 0).
`Tls` is for a TLS failure that isn't a plain I/O error, such as a certificate
that doesn't verify (see [TLS](#tls)). `Protocol` is for a peer that breaks the rules of the
protocol being spoken, such as a malformed HTTP response (see [HTTP](http.md)). An interrupted system call is retried inside the
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
`ended` is set when a `read_until` or `read_line` returned a last piece that the
stream's end cut short, with no delimiter after it; a protocol that needs
every line terminated can tell a truncation from a complete line by it.
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
| `f.is_terminal()` | whether it is a terminal, rather than a file or a pipe |

`stdout()` writes straight to descriptor 1, bypassing the buffer that `print`
uses. Call `flush_stdout()` first when you mix the two.
Closing is explicit: an `Fd` that is dropped stays open until the program
exits.

### Colour

`stdlib/term.kod` colours text for a terminal. `term.colour(fd)` says whether to:
`fd` is a terminal, `NO_COLOR` is unset or empty, and `TERM` isn't `dumb`. The
other functions wrap text in the escape codes of a style, whatever the output is,
so check first:

```kod
import "io"
import "posix"
import "term"

func main() -> int64 {
    mut label = "error:"
    if term.colour(posix.stderr()) {
        label = term.red(term.bold(label))
    }
    io.write_stderr(f"{label} no such file\n")
    return 1
}
```

The styles are `bold`, `dim`, `red`, `green` and `yellow`.

The older `io.read_file` and `io.write_file` keep their behavior: an empty
string or `-1` on failure, with no reason.

## TCP

`stdlib/net/tcp.kod` opens TCP connections. A connection is an `Fd`, so it is
a `Reader` and a `Writer` and works with `BufReader`, `read_all` and the rest.
A program that imports it compiles and links `stdlib/net/tcp.c`; no other
program does.

```kod
import "net/tcp" { connect, set_timeout }
import "time" { Duration }
import "stream" { BufReader, write_str }

func fetch_status_line(host: str) -> str or Error {
    let conn = try connect(host, port: 80)
    try set_timeout(conn, timeout: Duration(seconds: 5))
    try write_str(conn, "HEAD / HTTP/1.0\r\n\r\n")
    let br = BufReader(inner: conn)
    let line = try br.read_line()
    try conn.close()
    return line? or ""
}
```

| Function | Meaning |
|----------|---------|
| `connect(host, port, timeout = Duration(seconds: 10))` | resolve `host` (a name or an IP literal, IPv4 or IPv6) and connect to the first address that answers; `Fd or Error` |
| `set_timeout(f, timeout)` | make a read or a write on `f` fail with `TimedOut` after a [`Duration`](time.md) without progress; zero means wait forever; `none or Error` |
| `listen(host, port, backlog = 128)` | a `Listener` bound to `host:port`; an empty `host` means every IPv4 interface and port 0 picks a free port; `Listener or Error` |
| `l.accept()` | the next connection, waiting for one; `Fd or Error` |
| `is_idle(f)` | true if nothing is waiting to be read from `f`; false if it has data, an end of stream (the peer closed it) or an error pending |
| `l.port()` | the port it is bound to |
| `l.close()` | stop listening; `none or Error` |

`connect` gives up on each address after `timeout`, so a host
with several unreachable addresses can take longer in all. A refused
connection is `ConnectionRefused`, a timeout `TimedOut`, a name that doesn't
resolve `HostNotFound`, and a `port` outside 0..65535 or an empty `host`
`InvalidInput`. Writing to a peer that has closed is a `BrokenPipe` error and
doesn't kill the program with `SIGPIPE`. A connection has `TCP_NODELAY` set.

## TLS

`stdlib/net/tls.kod` runs TLS over a TCP connection, using the system's
SecureTransport (the Security framework), so it needs nothing installed and
checks certificates against the macOS keychain. A program that imports it
links `-framework Security -framework CoreFoundation`; no other program does.

```kod
import "net/tls" { connect }
import "stream" { BufReader, write_str }

func main() -> int64 or Error {
    let conn = try connect("example.com", port: 443)
    try write_str(conn, "GET / HTTP/1.0\r\nHost: example.com\r\n\r\n")
    let br = BufReader(inner: conn)
    print((try br.read_line())? or "")
    try conn.close()
    return 0
}
```

A `TlsStream` is a `Reader` and a `Writer`, so everything above works on it
as on a plain connection.

| Function | Meaning |
|----------|---------|
| `connect(host, port, trust_file = "", timeout = Duration(seconds: 10))` | open a TCP connection with [`net/tcp`](#tcp) and run the TLS handshake; `TlsStream or Error` |
| `s.read(max)`, `s.write(data)` | as for any stream |
| `s.set_timeout(timeout)` | as `net/tcp.set_timeout`: a read or write fails with `TimedOut` after a `Duration` without progress |
| `s.close()` | send a close notice, then close the connection; `none or Error` |

The server's certificate must be valid for `host`, chain to a trusted root and
be in date; otherwise `connect` throws an `IoError` of kind `Tls` whose
`detail` says why, and the connection is closed. `timeout` limits the TCP
connect and, separately, the handshake. A server that can't speak TLS 1.2 is a
`Tls` error: SecureTransport has no TLS 1.3, and the minimum version is 1.2.

`trust_file` is the path of a PEM file of certificates. When it isn't empty,
those certificates are the only trusted roots, in place of the keychain: use it
for a private CA or a self-signed server. The host name is still checked.

A server that closes the connection without a close notice reads as an
ordinary end of stream, since plain HTTP/1.0 servers do that; a response that
carries its own length (`Content-Length` or chunked) shows a truncation
anyway.
