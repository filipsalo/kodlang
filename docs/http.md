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

`get`, `post` and `fetch` open a connection for each request and close it
afterwards (`Connection: close`). To make several requests over the same
connection, use a [`Client`](#connection-reuse). There is no pipelining, no
cookies and no proxy support.

## Requests

A `Client` carries the settings that describe the service you talk to (its
headers, its certificate roots, its deadline) and makes the requests:

```kod
import "net/client" { Client }

let client = Client(deadline_ms: 15000)
client.headers.add("Accept", "application/json")
client.headers.add("Authorization", "Bearer " + token)

let user = try client.get("https://api.example.com/users/1")
let made = try client.post("https://api.example.com/users", payload, content_type: "application/json")
```

| Method of `Client` | Meaning |
|---|---|
| `get(url, options = Options())`, `delete(url, options = Options())` | `GET`, `DELETE` |
| `post(url, body, content_type, options = Options())`, `put(...)`, `patch(...)` | the method with a `bytes` body and a `Content-Type` |
| `fetch(method, url, options = Options())` | any method; the body is `options.body` |
| `close()` | close the idle connections (see [Connection reuse](#connection-reuse)) |

All return `Response or Error`. The functions `get`, `post`, `put`, `patch`,
`delete` and `fetch` of the module do the same with a new `Client` for each
call, which is closed again afterwards: one request, one connection.

A `Client` has these fields, each with the default shown:

| Field | Default | Meaning |
|-------|---------|---------|
| `headers` | none | headers sent with every request (`Headers`) |
| `trust_file` | `""` | PEM roots for `https`, as for [`net/tls`](io.md#tls) |
| `timeout_ms` | 30000 | limit for the connect, the TLS handshake, and each single read or write; a server that keeps sending slowly never trips it (see `deadline_ms`) |
| `deadline_ms` | 0 | limit for the whole request (connect, handshake, every redirect and reading the whole body); 0 means none, a negative value is an `InvalidInput` error |
| `max_redirects` | 5 | redirects to follow; 0 returns the redirect response as it is |
| `accept_gzip` | true | send `Accept-Encoding: gzip`, and decode a gzip response (see [Compression](#compression)) |
| `limits` | see below | caps on what a response may send |
| `max_idle_per_host`, `idle_ms` | 2, 30000 | connection reuse (see [Connection reuse](#connection-reuse)) |

`Options` is for one request. Its fields are the same, plus the body, and each
one that you leave out means the `Client`'s value:

| Field | Meaning |
|-------|---------|
| `headers` | added to the client's; where both have a header of the same name, the request's wins |
| `body` | the request body (`bytes`); empty by default |
| `trust_file`, `timeout_ms`, `deadline_ms`, `max_redirects`, `accept_gzip`, `limits` | replace the client's for this request, including with `0` or `false` |

```kod
let r = try client.get(url, options: Options(deadline_ms: 2000))   // this one is quicker
let q = try client.get(url, options: Options(deadline_ms: 0))      // and this one has none
```

A `Host` header, `Connection: close` and a `Content-Length` (for any body,
and for an empty `POST`, `PUT` or `PATCH`) are always set by the library and
replace any you give. `User-Agent: kod` and `Accept: */*` are added when you
don't give them.

URLs are `http://` or `https://`, a host (a name, an IPv4 address, or an IPv6
address in brackets), an optional port, and an optional path and query. The
scheme is case-insensitive, the default ports are 80 and 443, and a missing
path is `/`. A fragment is dropped. Credentials in the URL (`user@host`),
other schemes, spaces and control characters are errors.

## Connection reuse

A `Client` keeps the connections it has finished with and uses them again for
the next request to the same scheme, host and port, which saves the TCP connect
and the TLS handshake each time:

```kod
import "net/client" { Client }

func main() -> int64 or Error {
    let client = Client()
    let a = try client.get("https://api.example.com/users/1")
    let b = try client.get("https://api.example.com/users/2")   // same connection
    client.close()
    return 0
}
```

`max_idle_per_host` (2) is how many idle connections are kept for each scheme,
host and port; 0 turns reuse off, so every request opens and closes its own.
`idle_ms` (30000) is how old an idle connection may be before it is closed instead
of reused.

A connection goes back to the `Client` after a response only when nothing about
the exchange makes it unsafe: the response is `HTTP/1.1` (or `HTTP/1.0` with
`Connection: keep-alive`), has no `Connection: close`, has a length (a
`Content-Length`, chunked encoding, or no body at all, as for `HEAD`, `204` and
`304`), and left nothing unread. A response that ends where the connection ends is
never reused. After any error the connection is closed.

Before an idle connection is used, the `Client` checks that the server has not
closed it, and discards it if it has. A server can still close one in the instant
between that check and the request. When a request on a reused connection then
fails before any of the response arrives, and its method is `GET`, `HEAD`,
`OPTIONS`, `PUT`, `DELETE` or `TRACE` (the ones that are safe to repeat), the
`Client` makes it once more on a new connection. A `POST` or `PATCH` is not
repeated, and the error is returned as it is.

Redirects use the `Client` too, so a redirect within one host goes over the same
connection. The timeouts and the deadline apply to a reused connection exactly as to a new one. A `Client` is not meant to be shared by two requests at the same
time, and there is only one thread.

## Deadlines

`timeout_ms` bounds each wait, so a server that sends one byte every few
seconds can keep a request open for as long as it likes. `deadline_ms` bounds
the request as a whole: the time is counted from the start of `fetch` and shared
by every redirect, and every read and write is given only what is left of it.
When it runs out the call throws an `IoError` of kind `TimedOut` whose `detail`
is `deadline exceeded`, however the wait ended, and the connection is closed.

Two things can overrun it: resolving a host name is not interruptible, and a TLS
connection spends up to the time left on the TCP connect and then up to the
same on the handshake. Neither is by more than one `timeout_ms`.

## Compression

With `accept_gzip` on, requests carry `Accept-Encoding: gzip` (unless you set an
`Accept-Encoding` yourself), and a response whose `Content-Encoding` is `gzip` or
`x-gzip` is decoded before you see it: `Response.body` holds the decoded bytes,
the `Content-Encoding` header is removed, and `Content-Length` is the decoded
length. This happens whenever the response says it is gzip, even from a server that
was not asked to compress, and with `accept_gzip` off.

The decoded body is held to `limits.max_body` like any other, so a response that
inflates past it fails with a `Protocol` error `body too large` instead of filling
memory. A body that is not valid gzip is a `Protocol` error `bad gzip body` with
the reason, and `Content-Length` of the compressed data was already checked as
usual. Any other `Content-Encoding` (`br`, `deflate`, `zstd`, or a list of codings)
is left alone: the body comes back as received, with its header, for you to handle.
A response with no body, such as one to `HEAD`, is not decoded.

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

## Query strings and percent-encoding

Put user input into a URL through `Query`, never by concatenating it:

```kod
import "net/http" { Query, with_query }

let q = Query()
q.add("q", "kod language")
q.add("page", "2")
let url = with_query("https://api.example.com/search", q)
// https://api.example.com/search?q=kod%20language&page=2
```

| Function | Meaning |
|---|---|
| `percent_encode(s)` | every byte except `A-Z a-z 0-9 - . _ ~` becomes `%XX` (uppercase hex); UTF-8 text is encoded byte by byte |
| `percent_decode(s)` | the reverse; `%XX` is a byte, and `+` stays a `+`; a `%` not followed by two hex digits is an `InvalidInput` error; `str or Error` |
| `Query` | `add(name, value)` appends a pair, `to_str()` joins them as `name=value&name=value`, with names and values encoded; no pairs give `""` |
| `with_query(url, q)` | `url` plus `?` and the query, or `&` if `url` already has a `?`; an empty query returns `url` as it is; a `#fragment` stays at the end |

## Basic authentication

`basic_auth(user, password)` returns the value for an `Authorization` header,
`Basic ` and the base64 of `user:password` (RFC 7617). The text is taken as
bytes, so UTF-8 passes through unchanged. A `user` containing `:` is an
`InvalidInput` error, because the colon is what separates the two.

```kod
import "net/http" { basic_auth }

let options = Options()
options.headers.add("Authorization", try basic_auth("aladdin", "open sesame"))
```

## Building and reading by hand

`net/http` has what `client` is made of:

| Function | Meaning |
|----------|---------|
| `parse_url(s)` | `Url or Error` with `scheme`, `host`, `port`, `target` (path and query) |
| `resolve(base, location)` | the `Url` a `Location` points to |
| `write_request(w, req, keep_alive = false, accept_gzip = false)` | write a `Request` (`method`, `url`, `headers`, `body`) to any `Writer`, with `Connection: close` unless `keep_alive`, and `Accept-Encoding: gzip` when `accept_gzip` and there is no `Accept-Encoding` header already; header names and values with a line break or other control character, and a bad method, are `InvalidInput` errors |
| `read_response(br, method, limits = Limits())` | read one response from a `BufReader`; `method` decides whether there is a body; `Response.keep_alive` says whether the connection can carry another request |

`write_request` and `read_response` work on `MemWriter` and `MemReader`, which
is how they are tested without a network.
