---
icon: lucide/cloud
---

# Writing an API client

`examples/github_repo.kod` reads a repository's details and its open issues from
the GitHub API. It is about a hundred lines and uses every piece of the
standard library that a client needs; this page walks through it.

```
kod run examples/github_repo.kod anthropics/anthropic-sdk-python
```

```
anthropics/anthropic-sdk-python
  (no description)
  language: Python
  stars: 4030, forks: 901
  license: Apache-2.0
open issues:
  #2050 fix(streaming): keep compaction metadata when a delta omits encrypted_content
  #2049 fix(decoders): close the response when JSONL decoding fails
  #2048 fix(tools): don't coerce a non-object tool input in the session runner
```

Set `GITHUB_TOKEN` to send a bearer token (private repositories need one), and
`GITHUB_API` to talk to something other than `https://api.github.com`. The tests
use that to run the example against a local stand-in server
(`tests/support/http_fixture.py`), so they need no network.

## The pieces

**Arguments and environment.** `main(argv: [str])` receives the command line,
with the program's name first. `env.get("GITHUB_TOKEN")` returns a `str?`, and
`x? or default` handles a missing variable ([Built-ins](builtins.md#environment-variables)).

**The client.** What every request to the service needs goes on a `Client` once: its
headers, its deadline. The example wraps it in a small `GitHub` type, so `main` reads
as `github.repo(name)` and `github.open_issues(name, limit: 3)`. One `Client` serves
both requests, which keeps the connection from the first and uses it for the second
([HTTP client](http.md)).

```kod
let client = Client(deadline: Duration(seconds: 15))
client.headers.add("Accept", "application/vnd.github+json")
client.headers.add("Authorization", "Bearer " + token)

let response = try client.get(url)
```

A single request can override any of that with `Options`, for instance
`client.get(url, options: Options(deadline: Duration(seconds: 2)))`. `Client.get` follows
redirects, enforces the size limits and the deadline, and picks TCP or TLS from the
URL.

**Query strings.** Build them with `Query`, which encodes names and values, rather
than by joining strings:

```kod
let query = Query()
query.add("state", "open")
query.add("per_page", "3")
let url = with_query("/repos/" + name + "/issues", query)
```

**Reading JSON.** `json.parse` returns `Value or Error`. The accessors never fail,
so a missing or null field is a fallback, not a crash:

```kod
func text_of(anon v: json.Value, key: str, fallback: str) -> str {
    return json.as_str(json.get(v, key: key))? or fallback
}
```

`json.get(license, key: "spdx_id")` on a `null` license is `Null`, and `as_str` of
that is `none`, which `? or "none"` turns into the text `none`.

**Errors.** A non-2xx response is not a Kod error; `fetch` hands it back so you can
read what the API said. The example turns it into its own `ApiError` and
throws it, so that callers see one failure path for "the request failed" and
"the API refused":

```kod
type ApiError = struct {
    status: int64
    reason: str
    detail: str

    func to_str(self) -> str { ... }
}
```

Network failures arrive as an `IoError` with a kind (`ConnectionRefused`,
`TimedOut`, `HostNotFound`, `Tls`, `Protocol`, ...); see [Streams](io.md#errors).
`main` here turns every failure into `error: ...` on standard error and an
exit status of 1, and a bad command line into 2.

## Sending JSON

Writing to an API is the same, with a body. `ObjectBuilder` keeps the keys and
values in step, and `post` sets the length and the content type:

```kod
import "json"
import "net/client" { post }

let body = json.ObjectBuilder()
body.put_str("title", "It crashes")
body.put_str("body", "Steps to reproduce: ...")
body.put("labels", json.array_of([json.str_value("bug")]))

let payload = kod_str_to_bytes(json.emit(body.build()))
let response = try post(
    "https://api.example.com/issues",
    payload,
    content_type: "application/json",
)
```

## What to know before relying on it

- `get`, `post` and `fetch` open a connection for each request and close it. A program
  that makes many requests to one host should create a `Client` and call its
  `get`, `post` and `fetch` instead, which keep connections for reuse
  ([Connection reuse](http.md#connection-reuse)).
- `timeout` applies to the connect, the TLS handshake and each read or write.
  Set `deadline` to bound a request as a whole ([Deadlines](http.md#deadlines)).
- TLS goes through the system's SecureTransport, which speaks TLS 1.2 at most. A
  server that insists on TLS 1.3 fails with a `Tls` error.
- Numbers with a fraction or an exponent come back as `Decimal` text, because
  Kod has no floating-point type: `json.as_int` is `none` for them, and
  `json.as_number_text` gives the digits.
