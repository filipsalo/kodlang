# Roadmap

## Where things stand

Kod is self-hosted. `sh_kodc` (lexer, parser, codegen in `stdlib/kod/`, driver in
`kodc.kod`) compiles every Kod program, including itself, and the native `kod` tool
(`tools/kod.kod`) drives build / run / test / check. The Python package in `kod/` is
frozen: its interpreter runs `kodc.kod` when no `sh_kodc` exists and is a second
implementation of the language, and its launcher hands off to the native tool once
`make kod` has built it. Language features and build logic are added in Kod only.

The language has structs, enums with payloads, `match` (statement and expression, with
exhaustiveness checks), generics (monomorphised), interfaces, `T?`, `T or Error` with
`try` / `must`, function values and non-capturing lambdas, `str` / `bytes` / dynamic arrays,
and `test` blocks. The stdlib covers file and process I/O, `Map` / `Set`, sorting, time,
CRC-32, deflate / gzip, a minimal JSON, and LSP-style JSON-RPC framing.

## Next milestone: networking → HTTP → JSON

Grow the stdlib far enough to talk to HTTP services and handle real JSON. In order:

1. **Networking** (done) — TCP sockets (`getaddrinfo`, connect, read, write, close) as a small
   C shim and Kod wrapper in `stdlib/net/tcp.{kod,c}`, linked only into the programs that
   import them (see Link inputs in `docs/modules.md`). Errors come back as `T or Error`,
   not panics.
2. **TLS** — done: `stdlib/net/tls.{kod,c}` runs a client TLS session over a TCP
   connection with the system's SecureTransport (no extra install; TLS 1.2 at most), named
   in its leading `// kod:` lines so only programs that import it link the Security
   framework. A `TlsStream` is a `Reader` and a `Writer`, like a plain connection.
3. **HTTP/1.1 client** — request building, status line and header parsing,
   `Content-Length` and chunked bodies, over either stream type.
4. **Robust JSON** — parse errors returned as values instead of panics, `\uXXXX` escapes,
   non-integer numbers, and pretty-printing.

Done on the way: `str` has `starts_with`, `ends_with`, `find`, `split`, `trim`, `join`, `replace`,
`lower`, `upper`, `parse_int` and friends, and `StrBuilder` (`stdlib/strbuilder.kod`) appends in
amortised constant time (see `docs/strings.md`). `stdlib/stream.kod` and `stdlib/fd.kod` give
`Reader` / `Writer`, `IoError` with kinds, `BufReader` and file descriptors (see `docs/io.md`). `stdlib/net/tcp.kod` connects, listens and accepts, and a connection is an `Fd`.

Language work along the way, as these modules need it: `\x` / `\u` string escapes,
module-level constants (top-level `let` is currently an error), and the
open codegen bugs that this kind of code is most likely to hit.

## Later

- Pattern matching: nested patterns and guard clauses.
- Closures that capture enclosing locals.
- `pub` / private visibility for module members.
- Dead-code elimination: skip compiling functions nothing reaches.
- Retire the Python interpreter and bootstrap (see `TODO.md`).
