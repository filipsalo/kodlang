---
icon: lucide/arrow-left-right
---

# Streams and I/O errors

`stdlib/stream.kod` defines the error type and the two interfaces that byte
streams share, and `stdlib/posix.kod` implements them over file descriptors:
files, standard input and output and, later, sockets. Code that reads or
writes takes a `Reader` or a `Writer` and doesn't care what is behind it.

```kod
import "stream" { Reader }
import "posix" { open_read }

func count_bytes(anon r: Reader) -> int64 or Error {
    let data = try r.read_all()
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
    Cancelled
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

<!-- kod:
import "stream"
import "stream" { Reader }
import "posix"
import "posix" { open_read }
type IoError = stream.IoError
func use(anon f: posix.Fd) -> none {}
let path = "data.bin"
-->
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
protocol being spoken, such as a malformed HTTP response (see [HTTP](http.md)).
`Cancelled` is for an operation in a [task](tasks.md#cancellation) that was
cancelled while it waited (`ECANCELED`). An interrupted system call is retried inside the
runtime, so `EINTR` never reaches a caller.

## Reader and Writer

```kod
interface Reader {
    func read(self, anon max: int64) -> bytes or Error

    func read_all(self) -> bytes or Error { ... }
    func read_exact(self, anon n: int64) -> bytes or Error { ... }
    func copy_to(self, anon to: Writer) -> int64 or Error { ... }
}

interface Writer {
    func write(self, anon data: bytes) -> int64 or Error

    func write_all(self, anon data: bytes) -> none or Error { ... }
    func write_str(self, anon text: str) -> none or Error { ... }
}
```

`read` returns between 1 and `max` bytes, waiting until there is something to
return, and returns an empty `bytes` at the end of the stream. With
`max <= 0` it returns an empty `bytes` without reading, so don't call it that
way to test for the end. `write` returns how many bytes it accepted, which
may be fewer than `len(data)`; an empty `data` writes nothing and returns 0.

A type only has to declare `read` or `write`; the rest are
[provided methods](types.md#provided-methods) built on them, so every
`Reader` and `Writer` has them, called on the value itself or through the
interface:

| Method | Meaning |
|--------|---------|
| `r.read_all()` | read until the end of the stream; `bytes or Error` |
| `r.read_exact(n)` | exactly `n` bytes, or an `UnexpectedEof` error; `bytes or Error` |
| `r.copy_to(w)` | write everything until the end of the stream to the `Writer` `w`, a piece at a time; how many bytes that was; `int64 or Error` |
| `w.write_all(data)` | write every byte, repeating `write` as needed; a `write` that accepts 0 bytes of a non-empty `data` is an `Other` error (`write returned 0`); `none or Error` |
| `w.write_str(s)` | `write_all` of a `str` |

## In-memory streams

`MemReader(data: bytes, pos: 0)` reads from a `bytes` value, which is how
tests and parsers get a stream without a file. `MemWriter(buf: StrBuilder())`
collects what is written, and `to_bytes()` / `to_str()` return a copy of it.
Neither can fail.

## BufReader

`BufReader` wraps any `Reader` with a buffer, for protocols that mix lines
and counted bodies such as HTTP:

<!-- kod:
import "stream" { BufReader, MemReader, Reader }
let conn = MemReader(data: kod_str_to_bytes("HTTP/1.0 200 OK\r\n\r\nhi"), pos: 0)
let length = 2
-->
```kod
let br = BufReader(inner: conn)
let status = try br.read_line()          // str?, none at the end of the stream
let body = try br.read_exact(length)     // takes what is buffered first
```

| Method | Meaning |
|--------|---------|
| `read(max)` | a `Reader`: the buffered bytes first, else one read of the inner stream |
| `read_exact(n)` | the `Reader`'s, so exactly `n` bytes, or `UnexpectedEof` |
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
| `f.close()` | close it and set `f.fd` to -1, so closing it again fails; `none or Error` |
| `f.seek(pos)` | goes on reading or writing `pos` bytes from the start of a file; `none or Error` |
| `f.is_terminal()` | whether it is a terminal, rather than a file or a pipe |
| `signal(pid, sig)` | send the signal numbered `sig` to the process `pid`, as C's `kill`; `none or Error` (for a child of this program, `process.Child.kill` is the easier way) |

### Waiting on several descriptors

`poll(read:, write:, timeout:)` waits until at least one of the descriptors
is ready, and says which, so a program can serve several pipes or
connections without blocking on any one of them:

<!-- kod:
import "posix"
import "time" { Duration }
let out = posix.stdin()
let err = posix.stdin()
let input = posix.stdout()
-->
```kod
let ready = try posix.poll(read: [out, err], write: [input], timeout: Duration(seconds: 5))
if ready.read[0] {
    let piece = try out.read(65536)         // doesn't wait
}
```

It returns a `posix.Ready` or an `Error`. `ready.read` and `ready.write` hold a
`bool` for each descriptor in `read` and `write`, in the same order.

- **Ready for reading** means a `read` won't wait: there is data, the stream
  has ended, or an error is pending.
- **Ready for writing** means a `write` of up to 512 bytes won't wait, or will
  fail at once because the reader has gone.
- **Ignored descriptors:** a descriptor of -1, such as a closed `Fd`, is never
  ready.
- **Timeout:** without `timeout:` it waits as long as it takes. When the
  timeout passes first, every entry is false. With a zero `Duration` it only
  looks.
- **Nothing to wait for:** if both lists are empty or hold only -1, it fails
  with an `InvalidInput` error instead of waiting forever.

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

`io.read_file` gives `str or Error`: an `IoError` that says why the file can't
be opened or read, such as `open data.txt: No such file or directory`. Where a
missing file means no text, `io.read_file(path)? or ""` gives the empty string.
The older `io.write_file` keeps its behavior: `-1` on failure, with no reason.

## TCP

`stdlib/net/tcp.kod` opens TCP connections. A connection is an `Fd`, so it is
a `Reader` and a `Writer`: it works with `BufReader` and has `read_all`,
`write_str` and the rest. It is Kod throughout, calling the C library's socket
functions through [`unsafe`](unsafe.md).

<!-- kod:
import "stream" { Reader }
-->
```kod
import "net/tcp" { connect, set_timeout }
import "time" { Duration }
import "stream" { BufReader }

func fetch_status_line(host: str) -> str or Error {
    let conn = try connect(host, port: 80)
    try set_timeout(conn, timeout: Duration(seconds: 5))
    try conn.write_str("HEAD / HTTP/1.0\r\n\r\n")
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
| `l.accept(nonblocking = false)` | the next connection, waiting for one; `Fd or Error`. A `nonblocking` one is written to without waiting first, which is faster when there are other tasks; `set_timeout` doesn't apply to it |
| `l.wait()` | waits until there is a connection for `accept` to take; `none or Error` |
| `peer(f)` | the address at the other end, as `127.0.0.1:50123` or `[::1]:50123`; `""` when there is none |
| `shutdown(f, read = false, write = false)` | ends one direction of the connection, or both: a read of it gives the end of the stream, also one a task waits in, and a write fails |
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

`stdlib/net/tls.kod` runs TLS 1.3 over a TCP connection, both sides, with
Kod's own implementation (`stdlib/net/tls13.kod`, on the modules of
[Cryptography](crypto.md)). No system library is involved: a client checks the
server's certificates against the system's roots (on macOS, those of its root
keychain) itself.
A peer that can't speak TLS 1.3 (one that has only TLS 1.2, say) is refused.

```kod
import "net/tls" { connect }
import "stream" { BufReader }

func main() -> int64 or Error {
    let conn = try connect("example.com", port: 443)
    try conn.write_str("GET / HTTP/1.0\r\nHost: example.com\r\n\r\n")
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
`detail` says why, and the connection is closed. A server that can't do TLS 1.3
as the client does is a `Tls` error too, such as `the server doesn't speak TLS
1.3`. `timeout` limits the TCP connect and, separately, the handshake. What is
checked is in [Certificates](crypto.md#certificates-cryptox509).

`trust_file` is the path of a PEM file of certificates. When it isn't empty,
those certificates are the only trusted roots, in place of the system's: use it
for a private CA or a self-signed server. The host name is still checked.

The client offers the x25519 key exchange and the TLS 1.3 cipher suites with
AES-128-GCM, AES-256-GCM and ChaCha20-Poly1305, and takes ECDSA (P-256 and P-384)
and RSA-PSS signatures from the server. It doesn't resume sessions or send early
data; a server that asks for a client certificate gets none. `s.session` is
the `tls13.Session`, whose `client` holds what the handshake found, such as
the server's `certificates` and the cipher `suite`. A handshake costs
about 0.5 to 7 ms of CPU: 0.3 ms for X25519 and the rest checking signatures,
0.1 to 0.25 ms each for RSA, 0.6 ms on P-256 and 3 ms on P-384. The first in
a program also reads the system's roots, another 75 ms.

The server's side is `accept`, on a connection that [`net/tcp`](#tcp) accepted:

```kod
import "net/tcp"
import "net/tls"

func main() -> none or Error {
    let identity = try tls.load_identity("cert.pem", "key.pem")
    let l = try tcp.listen("127.0.0.1", port: 8443)
    let conn = try tls.accept(try l.accept(), identity)
    try conn.write_str("hello\n")
    try conn.close()
}
```

| Function | Meaning |
|----------|---------|
| `load_identity(cert_file, key_file)` | a certificate and its private key, from PEM files; `Identity or Error`. `cert_file` holds the server's certificate first and then those it was signed by, up to the root (which can be left out); `key_file` an RSA key, or an EC key on P-256 or P-384, that isn't encrypted (`PRIVATE KEY`, `RSA PRIVATE KEY` or `EC PRIVATE KEY`) |
| `identity.close()` | `accept` takes it no more; connections made with it go on |
| `accept(fd, identity)` | run the handshake as the server; `TlsStream or Error`. The connection is the stream's from then on, which closes it; on an error it is closed at once. How long the handshake may take is `fd`'s `tcp.set_timeout`, which a `nonblocking` one has not |

A key that isn't the certificate's is a `Tls` error, and so is a key on another
curve, or an EC key whose curve the certificate gives by its parameters rather
than by name.

The server speaks x25519 (asking a client that sent another key share for an
x25519 one), the three TLS 1.3 cipher suites, and the key's signature, ECDSA or
RSA-PSS. A client that offers no TLS 1.3, or can't take that key or key
exchange, is sent an alert (`protocol_version` or `handshake_failure`) and
`accept` fails with a `Tls` error. Clients have spoken TLS 1.3 since about
2018. `s.session.server` holds what a handshake found, such as the
`server_name` the client asked for. The client isn't asked for a certificate.

A server handshake costs about 0.6 ms of CPU with a P-256 key (0.25 ms for the
signature, 0.3 ms for X25519) and about 4 ms with an RSA key of 2048 bits. With
an EC key the first handshake in a program also makes a table of multiples of
the curve's generator, about 2 ms, which the signatures after it use.

Several tasks can use streams at the same time, and one may read a stream while another
writes to it; two writing to one stream at the same time isn't supported.

A server that closes the connection without a close notice reads as an
ordinary end of stream, since plain HTTP/1.0 servers do that; a response that
carries its own length (`Content-Length` or chunked) shows a truncation
anyway.
