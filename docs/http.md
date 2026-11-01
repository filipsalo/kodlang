---
icon: lucide/globe
---

# HTTP client

`stdlib/net/client.kod` makes HTTP/1.1 requests over TCP or TLS, and
`stdlib/net/http.kod` is the part that doesn't touch the network: URLs,
headers, writing a request to a `Writer` and reading a response from a
`BufReader`. A program that only parses or builds HTTP imports `net/http`
and links no socket or TLS code; one that imports `net/client` links both
(see [TCP](io.md#tcp) and [TLS](io.md#tls)).

```kod
import "net/client" { get }

func main() -> int64 or Error {
    let r = try get("https://example.com/")
    print(f"{r.status} {r.reason}")
    print(r.text())
    return 0
}
```

One request uses one connection, which is closed afterwards
(`Connection: close`). There is no keep-alive, no pipelining, no cookies,
no proxy support and no automatic decompression (no `Accept-Encoding` is
sent).

## Requests

| Function | Meaning |
|----------|---------|
| `get(url)` | `GET` with the default options |
| `post(url, body, content_type)` | `POST` of a `bytes` body |
| `fetch(method, url, options = Options())` | any method; the body is `options.body`; `Response or Error` |

`Options`:

| Field | Default | Meaning |
|-------|---------|---------|
| `headers` | none | extra request headers (`Headers`) |
| `body` | empty | the request body (`bytes`) |
| `trust_file` | `""` | PEM roots for `https`, as for [`net/tls`](io.md#tls) |
| `timeout_ms` | 30000 | limit for the connect, the TLS handshake, and each single read or write; not for the request as a whole |
| `max_redirects` | 5 | redirects to follow; 0 returns the redirect response as it is |
| `limits` | see below | caps on what a response may send |

A `Host` header, `Connection: close` and a `Content-Length` (for any body,
and for an empty `POST`, `PUT` or `PATCH`) are always set by the library and
replace any you give. `User-Agent: kod` and `Accept: */*` are added when you
don't give them.

URLs are `http://` or `https://`, a host (a name, an IPv4 address, or an IPv6
address in brackets), an optional port, and an optional path and query. The
scheme is case-insensitive, the default ports are 80 and 443, and a missing
path is `/`. A fragment is dropped. Credentials in the URL (`user@host`),
other schemes, spaces and control characters are errors.

## Redirects

`301`, `302` and `303` are retried as `GET` without a body (`HEAD` stays
`HEAD`); `307` and `308` repeat the method and the body. A `Location` may be
an absolute URL, `//host/path`, `/path`, `?query` or a path relative to the
request's, with `.` and `..` segments resolved. A redirect from `https` to
`http` is an error, never followed. When the redirect goes to another host or
port, the `Authorization`, `Cookie` and `Proxy-Authorization` headers are not
sent on. More than `max_redirects` redirects is an error.

## Responses

```kod
type Response = struct {
    status: int64
    reason: str
    headers: Headers
    body: bytes

    func text(self) -> str
    func ok(self) -> bool          // 200..299
    func header(self, anon name: str) -> str?
}
```

`headers` keeps the order the server sent and any repeated names.
`Headers` has `get(name) -> str?` (the first value), `all(name) -> [str]`,
`has(name)`, `add(name, value)` and `set(name, value)` (replaces every value
of that name), and compares names without regard to case.

The body is framed as RFC 9112 says: none for `HEAD`, `1xx`, `204` and `304`;
chunked when `Transfer-Encoding` is `chunked` (extensions are ignored
and trailers are read and dropped); else `Content-Length`; else everything up
to the end of the connection. `100 Continue` and other `1xx` responses before
the real one are skipped.

Bad responses are errors, not guesses. All of these throw an `IoError` of kind
`Protocol`, with `op` `http` and a `detail` saying what was wrong: a status
line that isn't `HTTP/1.x` and a three-digit status, a header without a `:`,
whitespace before the `:`, a header continuation line, a `NUL` in a header,
a `Content-Length` that is not plain digits or that repeats with a different
value, a `Transfer-Encoding` other than plain `chunked` (the client doesn't undo `gzip` or any other coding), a bad chunk size or a
chunk without its closing line break. A connection that ends before the
announced length or the last chunk is `UnexpectedEof`.

## Limits

`Limits` bounds what one response may make the client read, so a hostile or
broken server can't use up memory:

| Field | Default | Exceeding it |
|-------|---------|--------------|
| `max_body` | 16777216 | `Protocol`, `body too large` |
| `max_header_bytes` | 65536 | `Protocol`, `headers too large` (the status line, all header lines and trailers together) |
| `max_headers` | 100 | `Protocol`, `too many headers` |

A `Content-Length` over `max_body` fails before any of the body is read.

## Building and reading by hand

`net/http` has what `client` is made of:

| Function | Meaning |
|----------|---------|
| `parse_url(s)` | `Url or Error` with `scheme`, `host`, `port`, `target` (path and query) |
| `resolve(base, location)` | the `Url` a `Location` points to |
| `write_request(w, req)` | write a `Request` (`method`, `url`, `headers`, `body`) to any `Writer`; header names and values with a line break or other control character, and a bad method, are `InvalidInput` errors |
| `read_response(br, method, limits = Limits())` | read one response from a `BufReader`; `method` decides whether there is a body |

`write_request` and `read_response` work on `MemWriter` and `MemReader`, which
is how they are tested without a network.
