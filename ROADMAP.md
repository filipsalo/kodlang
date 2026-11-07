# Roadmap

## Where things stand

Kod is self-hosted. `sh_kodc` (lexer, parser, codegen in `stdlib/kod/`, driver in
`kodc.kod`) compiles every Kod program, including itself, and the native `kod` tool
(`tools/kod.kod`) drives build / run / test / check. `kod/__main__.py` is a
launcher that hands off to the native tool once `make` has built it. The Python
interpreter is retired; the tag `python-bootstrap` keeps it (see
[Self-hosting](docs/self-hosting.md#recovering-from-a-bad-snapshot)).

The language has structs, enums with payloads, `match` (statement and expression, with
exhaustiveness checks), generic types and functions (monomorphised), interfaces, `T?`, `T or Error` with
`try` / `must`, function values and non-capturing lambdas, `str` / `bytes` / dynamic arrays,
and `test` blocks. The stdlib covers file and process I/O, `Map` / `Set`, sorting, time,
CRC-32, deflate / gzip, a minimal JSON, and LSP-style JSON-RPC framing.

## Last milestone (done): networking → HTTP → JSON

Grow the stdlib far enough to talk to HTTP services and handle real JSON. In order:

1. **Networking** (done) — TCP sockets (`getaddrinfo`, connect, read, write, close) as a small
   C shim and Kod wrapper in `stdlib/net/tcp.{kod,c}`, linked only into the programs that
   import them (see Link inputs in `docs/modules.md`). Errors come back as `T or Error`,
   not panics.
2. **TLS** — done: `stdlib/net/tls.{kod,c}` runs a client TLS session over a TCP
   connection with the system's SecureTransport (no extra install; TLS 1.2 at most), named
   in its leading `// kod:` lines so only programs that import it link the Security
   framework. A `TlsStream` is a `Reader` and a `Writer`, like a plain connection.
3. **HTTP/1.1 client** — done: `stdlib/net/http.kod` (URLs, headers, request writing and
   response parsing with `Content-Length`, chunked and read-to-close bodies and size limits,
   and `get`, `post`, `fetch` over TCP or TLS, with redirects). See `docs/http.md`.
4. **Robust JSON** — done: `json.parse` returns `Value or Error` with the position of a
   syntax error, follows RFC 8259 strictly (including `\uXXXX` and surrogate pairs), keeps
   numbers it can't hold as `Decimal` text, bounds nesting depth, and `emit_pretty` indents.
   See `docs/json.md`.

Done on the way: `str` has `starts_with`, `ends_with`, `find`, `split`, `trim`, `join`, `replace`,
`lower`, `upper`, `parse_int` and friends, and `StrBuilder` (`stdlib/strbuilder.kod`) appends in
amortised constant time (see `docs/strings.md`). `stdlib/stream.kod` and `stdlib/posix.kod` give
`Reader` / `Writer`, `IoError` with kinds, `BufReader` and file descriptors (see `docs/io.md`). `stdlib/net/tcp.kod` connects, listens and accepts, and a connection is an `Fd`.

`examples/github_repo.kod` ties it together as a worked API client (walked through in
`docs/api-client.md`), with `env` for tokens, `json.ObjectBuilder` for bodies and `Query` /
`percent_encode` for URLs, and `encoding/base64` with `basic_auth` for credentials. `net/http` has a `Client` that keeps
connections, a whole-request `deadline_ms`, and gzip responses (decoded in Kod by
`compress/inflate`).

Language work along the way, as these modules need it: calls over several lines, default
labels that can be skipped, `\x` / `\u` string escapes, module-level constants and a
statement that drops a `T or Error` being an error (all done); what remains is the open
codegen bugs that this kind of code is most likely to hit.

## Later

- Closures that capture enclosing locals.
- Dead-code elimination: skip compiling functions nothing reaches.
