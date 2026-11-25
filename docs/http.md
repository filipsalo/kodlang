---
icon: lucide/globe
---

# HTTP

`stdlib/net/http.kod` makes HTTP/1.1 requests over TCP or TLS (see
[TCP](io.md#tcp) and [TLS](io.md#tls)), and [answers them](#serving). Its parts that don't touch the
network, URLs, headers, writing a request to a `Writer` and reading a
response from a `BufReader`, work on their own too.

```kod
import "net/http" { get }

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

<!-- kod:
let token = "secret"
let payload = kod_str_to_bytes("{}")
-->
```kod
import "net/http" { Client }
import "time" { Duration }

let client = Client(deadline: Duration(seconds: 15))
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
| `open(method, url, options = Options())` | as `fetch`, without reading the body: see [Bodies that don't fit in memory](#bodies-that-dont-fit-in-memory) |
| `close()` | close the idle connections (see [Connection reuse](#connection-reuse)) |

All return `Response or Error`. The functions `get`, `post`, `put`, `patch`,
`delete`, `fetch` and `open` of the module do the same with a new `Client` for each
call, which is closed again afterwards: one request, one connection.

A `Client` has these fields, each with the default shown:

| Field | Default | Meaning |
|-------|---------|---------|
| `headers` | none | headers sent with every request (`Headers`) |
| `trust_file` | `""` | PEM roots for `https`, as for [`net/tls`](io.md#tls) |
| `timeout` | `Duration(seconds: 30)` | limit for the connect, the TLS handshake, and each single read or write; a server that keeps sending slowly never trips it (see `deadline`) |
| `deadline` | `Duration()` | limit for the whole request (connect, handshake, every redirect and reading the whole body); zero means none, a negative one is an `InvalidInput` error |
| `max_redirects` | 5 | redirects to follow; 0 returns the redirect response as it is |
| `accept_gzip` | true | send `Accept-Encoding: gzip`, and decode a gzip response (see [Compression](#compression)) |
| `limits` | see below | caps on what a response may send |
| `max_idle_per_host`, `idle` | 2, `Duration(seconds: 30)` | connection reuse (see [Connection reuse](#connection-reuse)) |

`Options` is for one request. Its fields are the same, plus the body, and each
one that you leave out means the `Client`'s value:

| Field | Meaning |
|-------|---------|
| `headers` | added to the client's; where both have a header of the same name, the request's wins |
| `body` | the request body (`bytes`); empty by default |
| `body_from`, `body_length` | instead of `body`, a `Reader` to [send it from](#bodies-that-dont-fit-in-memory), and its length when that is known |
| `trust_file`, `timeout`, `deadline`, `max_redirects`, `accept_gzip`, `limits` | replace the client's for this request, including with `0` or `false` |

<!-- kod:
import "net/http" { Client, Options }
let client = Client()
let url = "https://api.example.com/users/1"
-->
```kod
let r = try client.get(url, options: Options(deadline: Duration(seconds: 2)))   // this one is quicker
let q = try client.get(url, options: Options(deadline: Duration()))              // and this one has none
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
import "net/http" { Client }

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
`idle` (30 seconds) is how old an idle connection may be before it is closed instead
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

`timeout` bounds each wait, so a server that sends one byte every few
seconds can keep a request open for as long as it likes. `deadline` bounds
the request as a whole: the time is counted from the start of `fetch` and shared
by every redirect, and every read and write is given only what is left of it.
When it runs out the call throws an `IoError` of kind `TimedOut` whose `detail`
is `deadline exceeded`, however the wait ended, and the connection is closed.

Two things can overrun it: resolving a host name is not interruptible, and a TLS
connection spends up to the time left on the TCP connect and then up to the
same on the handshake. Neither is by more than one `timeout`.

## Compression

With `accept_gzip` on, requests carry `Accept-Encoding: gzip` (unless you set an
`Accept-Encoding` yourself), and a response whose `Content-Encoding` is `gzip`,
`x-gzip` or `deflate` is decoded before you see it: `Response.body` holds the decoded
bytes, the `Content-Encoding` header is removed, and `Content-Length` is the decoded
length. This happens whenever the response says it is compressed, even from a server
that was not asked to compress, and with `accept_gzip` off. A `deflate` body is
meant to be zlib data, but some servers send raw deflate instead; both are read.

The decoded body is held to `limits.max_body` like any other, so a response that
inflates past it fails with a `Protocol` error `body too large` instead of filling
memory. A body that is not valid gzip is a `Protocol` error `bad gzip body` with
the reason (`bad deflate body` for `deflate`), and `Content-Length` of the compressed
data was already checked as usual. Any other `Content-Encoding` (`br`, `zstd`, or a
list of codings) is left alone: the body comes back as received, with its header,
for you to handle.
A response with no body, such as one to `HEAD`, is not decoded.

An [opened](#bodies-that-dont-fit-in-memory) response's body is decoded as it is
read, to any length. Its `Content-Encoding` and `Content-Length` headers are removed,
as the decoded length isn't known. That the body is not valid is an error of a read.

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

## Bodies that don't fit in memory

`open` gives the response once its headers have come. `resp.reader()` is a
[`Reader`](io.md#reader-and-writer) of the body, which is read as it is asked for, so
it takes no more memory than one piece:

<!-- kod:
import "net/http"
import "net/http" { Request, Response, get }
import "posix"
-->
```kod
func download(anon url: str, to: str) -> int64 or Error {
    let resp = try http.open("GET", url)
    if not resp.ok() {
        resp.close()
        throw http.HttpError(status: resp.status, message: resp.reason)
    }
    let out = try posix.create(to)
    let copied = resp.reader().copy_to(out)
    resp.close()
    try out.close()
    return try copied
}
```

The connection goes back to the `Client`, or is closed, once the body has been
read to its end or a read has failed. `resp.close()` ends it before that, and does
nothing after; a response that is neither read to its end nor closed keeps its
connection open. `resp.body` is empty, and `limits.max_body` doesn't hold. `timeout`
is for each read, and `deadline` goes on until the last. A compressed body
is [decoded](#compression) as it is read. When the connection ends
before the body does, a read fails with `UnexpectedEof`. Redirects are followed as
by `fetch`. For a response that has been read already, `reader()` reads its
`body`.

`Options(body_from: r)` sends what the `Reader` `r` gives until its end, in chunks,
or with `body_length` as its `Content-Length`; a body of another length than that is
an `InvalidInput` error. It works with `fetch` and `open`, always on a new connection:

<!-- kod:
import "net/http"
import "net/http" { Request, Response, get }
import "io"
import "posix"
-->
```kod
func upload(anon path: str, anon url: str) -> http.Response or Error {
    let f = try posix.open_read(path)
    let sent = http.fetch("PUT", url, options: http.Options(body_from: f, body_length: io.file_size(path)))
    try f.close()
    return try sent
}
```

A `Reader` can't be read twice, so a `307` or `308` redirect of such a request is
an error. An error of the `Reader` ends the request and is given back. When the
server answers and stops reading before all has been sent, the answer is given back
if it can still be read.

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
import "net/http" { basic_auth, Options }

let options = Options()
options.headers.add("Authorization", try basic_auth("aladdin", "open sesame"))
```

## Requests at the same time

Inside [tasks](tasks.md), a request waits for the network while the other
tasks run, so requests spawned together are made together, over TLS too:

<!-- kod:
import "net/http" { get }
import "tasks"
-->
```kod
func status_of(anon url: str) -> int64 or Error {
    return (try get(url)).status
}

func check_all(anon urls: [str]) -> none {
    mut checks: [tasks.Task[int64 or Error]] = []
    for url in urls {
        checks += [spawn status_of(url)]
    }
    for i, check in checks {
        match check.wait() {
            Ok(status) -> print(f"{urls[i]}: {status}")
            Err(e) -> print(f"{urls[i]}: {e.to_str()}")
        }
    }
}
```

Timeouts and deadlines hold for each task as they do without tasks. A
`Client` can be shared between tasks; each request takes a connection of its
own, from the idle ones or a new one. Looking up the host's address still
holds up every task (see [Tasks](tasks.md#waiting-for-io)).

## Serving

A `Router` says which handler answers which requests, and a `Server` answers
them: each connection is handled by a task of its own, and each request on it
by a handler, which takes the `Request` and gives back a `Response`.

```kod
import "net/http"
import "net/http" { Request, Response }

type User = struct {
    name: str
}

func find_user(anon id: int64) -> User or Error {
    if id != 7 {
        throw http.HttpError(status: 404, message: f"no user {id}")
    }
    return User(name: "Ada")
}

func show_user(anon req: Request) -> Response or Error {
    let Some(id) = req.param("id").parse_int() else {
        throw http.HttpError(status: 400, message: "an id is a number")
    }
    let user = try find_user(id)
    return http.json(f"\{\"name\": \"{user.name}\"}")
}

func main() -> none or Error {
    let routes = http.Router()
    routes.get("/", func(anon req: Request) -> Response or Error {
        return http.text(f"hello, {req.query("name")? or "you"}\n")
    })
    routes.get("/users/{id}", show_user)
    try http.Server(port: 8080, :routes).run()
}
```

A handler that waits, for a request of its own or a sleep, lets the other
connections go on meanwhile. One that fails fails only its own request:

- an `HttpError` is a response with its `status`, and its `message` as the body;
- any other error, and a [panic](panics.md), is a `500`, and the error, or the
  panic's message and backtrace, is logged. (A task the handler spawned
  `detached` is nobody's, so a panic in one still ends the program.)

### Routes

`routes.get(pattern, handler)`, and likewise `post`, `put`, `patch` and
`delete`, or `routes.add(method, pattern, handler)` for any other method, say
who answers the requests of that method whose path fits `pattern`:

| In a pattern | Fits |
|---|---|
| `/users/all` | just that |
| `/users/{id}` | any one part that isn't empty: `req.param("id")` is the part, percent-decoded |
| `/files/{path...}` | all the rest, with at least one part: `req.param("path")` is `a/b.txt` for `/files/a/b.txt` (and may have `..` in it: check it before it names a file) |

A written part goes before a `{name}` at the same place, and that before a
`{name...}`: with the first two above, `/users/all` is the first's. Adding a
pattern that fits the same paths as one added before for that method, or isn't
one at all, panics.

A path no pattern fits is a `404`. One that only patterns of other methods fit
is a `405`, with the methods it has in `Allow`. `HEAD` is answered by `GET`'s
handler, without the body, where there is no handler for `HEAD` itself.

### `Request`

| | |
|---|---|
| `method`, `target` | as sent; `target` is the path and the query |
| `headers`, `body` | `Headers`, and the body's `bytes` |
| `remote` | the client's address, such as `127.0.0.1:50123` |
| `path()` | `target` up to `?`; of a whole URL, as a proxy may send, its path |
| `param(name)` | the part of the path `{name}` in the pattern stands for; panics when the pattern has no such name |
| `query(name)` | the first value of `name` in the query, decoded (`+` is a space); `str?` |
| `queries(name)` | all its values, `[str]` |
| `header(name)` | a header's value; `str?` |
| `text()` | the body as text |
| `reader()` | a `Reader` of the body: see [Streaming](#streaming) |

### `Response`

| | |
|---|---|
| `http.text(body, status = 200)` | plain text |
| `http.html(body, status = 200)` | HTML |
| `http.json(body, status = 200)` | JSON, given as text: see [`json`](json.md) for making it |
| `http.redirect(to, status = 302)` | a redirect to `to` |
| `http.status(code)` | only a status, with its reason as the body where it can have one |
| `respond(status, body, content_type = "text/plain; charset=utf-8")` | any of them |
| `http.stream(write, status = 200, content_type = "application/octet-stream", length = none)` | a body that `write` [writes piece by piece](#streaming) |
| `http.file(path, req = none, content_type = none)` | a [file](#files)'s content, streamed; `Response or Error`, a 404 `HttpError` when there is no such file (or it is a directory). Its type is the one its name's ending says, when left out |
| `resp.with_header(name, value)` | `resp`, with a header added |

### Files

`routes.files(prefix, dir)` serves the files below the directory `dir`, for paths
below `prefix`:

<!-- kod:
import "net/http"
import "net/http" { Request, Response, get }
import "time" { Duration }
let routes = http.Router()
-->
```kod
routes.files("/static", "public", max_age: Duration(hours: 1))   // /static/css/a.css is public/css/a.css
routes.files("/", "site")                                        // and everything no other route fits
```

- A directory is its `index` (`index.html` when left out), and a `404` when it has
  none; its path without the slash at the end is redirected to the one with it.
- A part of the path that starts with a dot, such as `..` or `.git`, is a `404`, and
  so is an empty one or one with a `\` or a NUL in it. (`/.well-known` needs a
  `routes.files` of its own.) Symbolic links are followed, out of `dir` too.
- `max_age` is sent as `Cache-Control: max-age`.

Files have `Last-Modified`, and a request with `If-Modified-Since` that is as new
gets a `304`. A `GET` with a `Range` of bytes (one range, in any of its three forms) gets
those as a `206`, or a `416` when the file is shorter; `If-Range` with a date makes
that depend on the file being unchanged. Anything else in a `Range` is ignored, and the
whole file sent. There is no `ETag`. `http.file(path, req: req)` does the same in a
handler; without `req` it always sends the whole file.

When the response would be [compressed](#compressing) for the client, a `Range` is ignored: it
would be of the bytes compressed, which aren't kept.

### Streaming

A response's body needn't be in memory as a whole. `http.stream` takes a function
that writes it, which is called once the handler has given the response back:

<!-- kod:
import "net/http"
import "net/http" { Request, Response, get }
-->
```kod
func rows(anon _req: Request) -> Response or Error {
    return http.stream(func(anon w: http.BodyWriter) -> none or Error {
        for i in 0..1000000 {
            try w.write_str(f"{i},{i * i}\n")
        }
    }, content_type: "text/csv")
}
```

A `BodyWriter` is a [`Writer`](io.md#reader-and-writer). What is written goes out
once there are 64 KB of it, or at `w.flush()`, as for a stream of events. A
write waits while the client is slow to read, so the body takes no more memory
than that. `length` is the body's length when it is known, sent as
`Content-Length`; writing more or less than that is an error. Without it, the
body is sent in chunks (to a client that speaks HTTP/1.0, until the connection
closes), or with its length if it all fits in one piece.

Until the first piece goes out nothing has been sent, so an error or a panic in
the function is answered as a handler's is, by a `500` or an `HttpError`'s
status. After that it is logged and ends the connection, so that the client can
tell the body isn't whole (a client that speaks HTTP/1.0 can't, without
`length`). When the client goes away, the next write fails, which isn't logged.
A `HEAD`, and a status without a body, don't call the function.

A request's body can be read as it comes too, by a route added with
`stream_body: true`, or, without routes, when the `Server` has
`stream_bodies: true`:

<!-- kod:
import "net/http"
import "net/http" { Request, Response, get }
import "posix"
let routes = http.Router()
-->
```kod
func save(anon req: Request) -> Response or Error {
    let out = try posix.create("upload.tmp")
    let copied = req.reader().copy_to(out)
    try out.close()                          // whether or not the client went away
    return http.text(f"{try copied} bytes\n", status: 201)
}

routes.put("/upload", save, stream_body: true)
```

`req.reader()` is a [`Reader`](io.md#reader-and-writer) of the body; without
`stream_body`, of the bytes already read. `limits.max_body` doesn't hold for a
streamed body, nor does `body_timeout` limit the whole of it: the handler decides
how much, and how long, is too much. `req.body` is empty.

When the client sends something wrong, stops sending for `body_timeout`, or
goes away, a read fails; a handler that passes the error on answers with the
`400` or `408` it would have been. A client that asks first
(`Expect: 100-continue`) is told to go on at the first read. What the handler
leaves unread is read and dropped when it is short (64 KB); otherwise the
connection ends after the response.

### Compressing

With `Server(compress: true)`, responses are compressed with gzip for clients that
take it (`Accept-Encoding`), where that is worth it: a `Content-Type` of text, JSON,
JavaScript, XML, SVG or WebAssembly, and a body of 1 KB or more. They then have
`Content-Encoding: gzip`. Such a response has `Vary: Accept-Encoding` for other
clients too, for caches to tell them apart. A
[streamed](#streaming) body is compressed as it is written, and sent in chunks; `flush` sends
what there is, so events still come at once. `compress_level` is
[`deflate`](encoding.md#compression)'s.

A response is left as it is when it has a `Content-Encoding`, an `ETag` (which
names the bytes sent) or a `Cache-Control` of `no-transform`, when its status is
`206`, and when it is streamed to a client that speaks HTTP/1.0.

It is off unless asked for: it takes 10 to 20 µs for each KB, as long as a request
or two without it. Don't compress a page that has both a secret
(such as a CSRF token) and text the client chose: the length then tells about the
secret (the BREACH attack). A `Cache-Control` of `no-transform` leaves it out.

### Connections

A connection carries requests one after another, until the client sends
`Connection: close` (or speaks HTTP/1.0 without `keep-alive`), a request
can't be read, or the client goes away. A request's body is read by its
`Content-Length` or chunked; a client that sends `Expect: 100-continue` is
told to go on. Anything wrong with a request ends the connection, with a
`400`, or a `413` for a body past the limits, a `431` for headers past them, or
a `501` for a `Transfer-Encoding` other than `chunked`.

### `Server`

`Server(...)` has the settings, each with a default. `run()` listens on `host`
and `port` and answers requests until `stop`, or until Ctrl-C or a `kill`
(`SIGINT` or `SIGTERM`), which stops it as `stop` does; a second one ends the
program at once. `serve(l)` answers those that come to a
[`tcp.Listener`](io.md#tcp) there is already, and leaves signals alone. Both give
`none or Error`.

<!-- kod:
import "net/http" { Request, Response, Server, text }
import "time" { Duration }
func hello(anon req: Request) -> Response or Error {
    return text("hello\n")
}
-->
```kod
func main() -> none or Error {
    let server = Server(handler: hello, max_connections: 500, idle_timeout: Duration(seconds: 15))
    try server.run()
}
```

| Field | Default | Meaning |
|-------|---------|---------|
| `routes` | none | the `Router` that answers requests |
| `handler` | | answers them all instead, when there are no `routes` |
| `host`, `port` | `127.0.0.1`, 8080 | where `run` listens; an empty `host` means every IPv4 interface |
| `header_timeout` | 10 s | how long a client may take to send a request's headers, from when it connects or, on a kept-alive connection, from their first byte |
| `body_timeout` | 60 s | how long it may take to send the body after them; of a [streamed](#streaming) body, how long until the next of it comes |
| `write_timeout` | 60 s | how long it may take to read the response; of a streamed one, each 64 KB or less of it |
| `idle_timeout` | 60 s | how long a kept-alive connection may wait for its next request |
| `stop_timeout` | 10 s | how long requests may go on after `stop` |
| `max_connections` | 10000 | how many connections are open at once |
| `stop_on_signals` | true | whether `run` stops on `SIGINT` and `SIGTERM`; when false it leaves [signals](tasks.md#signals) alone too |
| `compress`, `compress_level` | false, 4 | whether [responses are compressed](#compressing), and how much |
| `stream_bodies` | false | whether `handler` reads the [bodies](#streaming) of requests itself |
| `limits` | `Limits()` | caps each request's headers and body, as for a response |
| `log` | stderr | a `func(str) -> none` that gets a line or more for each handler that fails |
| `access_log` | false | whether `log` gets a line for each request too: `127.0.0.1:50123 GET /users/7 200 14 B 0.31 ms`, with the length of the body sent and the time until it was |

`serve(l, handler, limits = Limits())` is `Server(:handler, :limits).serve(l)`.

The timeouts cap the whole of what they name, not each read, so a client that
sends a byte at a time is dropped too: with a `408` when it has begun a
request (which it may miss if it is still sending), else just closed. A handler has no timeout; use
[`tasks.within`](tasks.md#cancellation) for what it waits for.

At `max_connections`, a kept-alive connection that waits for its next request
is closed to make room, the one that would time out first; when there is
none, new connections wait to be accepted until one ends. Running out of file
descriptors doesn't end the server: it waits a little and tries again.

`server.stop(within: d)` ends `serve`: no more connections are accepted, those
waiting for a request are closed, and the requests being read or answered get
`d` (`stop_timeout` when left out) to finish, their responses saying
`Connection: close`. `serve` then returns, and a later one returns at once; when some hadn't finished, they are
cancelled and it returns a `TimedOut` error. It returns an error when accepting
fails or its task is cancelled (`task.cancel()`) too; then the connections'
tasks are cancelled and waited for.

## Building and reading by hand

`net/http` has what `client` is made of:

| Function | Meaning |
|----------|---------|
| `parse_url(s)` | `Url or Error` with `scheme`, `host`, `port`, `target` (path and query) |
| `resolve(base, location)` | the `Url` a `Location` points to |
| `write_request(w, req, keep_alive = false, accept_gzip = false)` | write an `Outgoing` (`method`, `url`, `headers`, `body`) to any `Writer`, with `Connection: close` unless `keep_alive`, and `Accept-Encoding: gzip` when `accept_gzip` and there is no `Accept-Encoding` header already; header names and values with a line break or other control character, and a bad method, are `InvalidInput` errors |
| `read_request(br, limits = Limits())` | the next `Request` from a `BufReader`, or `none` when the connection ends before one begins |
| `write_response(w, resp, keep_alive = false, head = false)` | writes `resp` with a `Content-Length` and, unless `keep_alive`, `Connection: close`; an empty `reason` is the status's usual one; `head` leaves out the body, for the answer to a `HEAD` |
| `read_response(br, method, limits = Limits())` | read one response from a `BufReader`; `method` decides whether there is a body; `Response.keep_alive` says whether the connection can carry another request |

`write_request` and `read_response` work on `MemWriter` and `MemReader`, which
is how they are tested without a network.
