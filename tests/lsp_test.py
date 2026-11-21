"""Drive the kod LSP server end-to-end: send a real LSP session over
stdin, read the framed responses, and check we get the expected shape
on each one. Builds the binary via `kod build` on first run."""

import json
import re
import subprocess
from pathlib import Path

import pytest
from stdio_test import removed_if_signalled, running, stderr_text

ROOT = Path(__file__).resolve().parent.parent
KOD = ROOT / "build" / "apps" / "kod" / "kod"
BIN = ROOT / "build" / "apps" / "lsp" / "lsp"


def build_lsp(kod: Path = KOD) -> None:
    """`kod build tools/lsp.kod`. If pytest is stopped by SIGTERM or SIGHUP, or
    the build runs past the bound of the other process tests, everything it
    started is stopped."""
    with removed_if_signalled(lambda: None):
        with running([kod, "build", "tools/lsp.kod"]) as proc:
            assert proc.stdout is not None
            built = proc.stdout.read().decode(errors="replace")
            proc.wait()
            assert proc.returncode == 0, built + stderr_text(proc)


@pytest.fixture(scope="module")
def lsp_binary(sh_kodc):
    build_lsp()
    assert BIN.exists()
    return BIN


def frame(body: dict) -> bytes:
    s = json.dumps(body)
    return f"Content-Length: {len(s)}\r\n\r\n{s}".encode()


def parse_frames(raw: bytes) -> list[dict]:
    """Split the server's framed stdout back into JSON messages."""
    out = []
    pos = 0
    while pos < len(raw):
        m = re.search(rb"Content-Length: (\d+)\r\n\r\n", raw[pos:])
        if not m:
            break
        length = int(m.group(1))
        body_start = pos + m.end()
        body = raw[body_start : body_start + length]
        out.append(json.loads(body))
        pos = body_start + length
    return out


def drive(binary: Path, messages: list[dict]) -> list[dict]:
    payload = b"".join(frame(m) for m in messages)
    result = subprocess.run(
        [str(binary)],
        input=payload,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode()
    return parse_frames(result.stdout)


def test_initialize_then_shutdown(lsp_binary):
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    assert len(responses) == 2
    init, shutdown = responses
    assert init["id"] == 1
    assert init["result"]["capabilities"]["textDocumentSync"] == 1
    assert init["result"]["serverInfo"]["name"] == "kod-lsp"
    assert shutdown["id"] == 2
    assert shutdown["result"] is None


def test_a_message_that_is_not_json_is_skipped(lsp_binary):
    """Bad JSON used to panic the server; now it is dropped and the session
    goes on."""
    good = frame({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    junk = b'Content-Length: 9\r\n\r\n{"a": 1,]'
    truncated = b"Content-Length: 5\r\n\r\n[1, 2"
    tail = frame({"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": None})
    exit_ = frame({"jsonrpc": "2.0", "method": "exit", "params": None})
    result = subprocess.run(
        [str(lsp_binary)],
        input=good + junk + truncated + tail + exit_,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode()
    responses = parse_frames(result.stdout)
    assert [r["id"] for r in responses] == [1, 2]


def test_did_open_with_error_emits_diagnostic(lsp_binary):
    bad_source = "func main() -> int64 {\n  does_not_exist()\n  return 0\n}\n"
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": "file:///tmp/sample.kod",
                        "languageId": "kod",
                        "version": 1,
                        "text": bad_source,
                    }
                },
            },
            {"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    diag_msgs = [
        r for r in responses if r.get("method") == "textDocument/publishDiagnostics"
    ]
    assert len(diag_msgs) == 1
    diags = diag_msgs[0]["params"]["diagnostics"]
    assert len(diags) >= 1
    d = diags[0]
    assert "does_not_exist" in d["message"]
    assert d["severity"] == 1
    assert d["source"] == "kod"
    # The error is on line 2 of the source, indented by two spaces.
    # LSP positions are 0-indexed, so that's line=1, character=2.
    assert d["range"]["start"]["line"] == 1
    assert d["range"]["start"]["character"] == 2


def test_unknown_identifier_diagnostic(lsp_binary):
    # Typo'd identifier — the most common "broken while typing" mistake.
    # Used to slip past the compiler silently (just emitted 0); the LSP
    # would then publish an empty diagnostics list and the editor would
    # show nothing.
    bad_source = "func main() -> int64 {\n  let x: int64 = 0\n  return xy\n}\n"
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": "file:///tmp/typo.kod",
                        "languageId": "kod",
                        "version": 1,
                        "text": bad_source,
                    }
                },
            },
            {"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    diag_msgs = [
        r for r in responses if r.get("method") == "textDocument/publishDiagnostics"
    ]
    assert len(diag_msgs) == 1
    diags = diag_msgs[0]["params"]["diagnostics"]
    diag = next(d for d in diags if "unknown name `xy`" in d["message"])
    # Range widens to the full identifier (was always one-character wide).
    start = diag["range"]["start"]
    end = diag["range"]["end"]
    assert start["line"] == 2 and start["character"] == 9
    assert end["line"] == 2 and end["character"] == 11


def test_hover_renders_signature(lsp_binary):
    # Cursor on `read_file` in `io.read_file(...)` should yield a Hover
    # with the function's signature in a Kod-fenced code block. Same
    # lookup as go-to-def; just renders SigInfo instead of a Location.
    source = (
        'import "io"\n'
        "func main() -> int64 {\n"
        '  let s: str = io.read_file("/dev/null")\n'
        "  return 0\n"
        "}\n"
    )
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": "file:///tmp/hover.kod",
                        "languageId": "kod",
                        "version": 1,
                        "text": source,
                    }
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/hover",
                "params": {
                    "textDocument": {"uri": "file:///tmp/hover.kod"},
                    "position": {"line": 2, "character": 20},
                },
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    init = next(r for r in responses if r.get("id") == 1)
    assert init["result"]["capabilities"]["hoverProvider"] is True
    hover = next(r for r in responses if r.get("id") == 2)
    assert hover["result"] is not None, "expected a Hover, got null"
    value = hover["result"]["contents"]["value"]
    # io.read_file: extern func read_file(anon path: str) -> str
    # The anon param's binding name (`path`) should be in the hover so
    # the user can tell what each positional argument represents.
    assert "io.read_file" in value
    assert "anon path: str" in value


def test_definition_resolves_struct_type(lsp_binary):
    # Cursor on `Box` in `let b: Box = ...` should jump to the
    # `type Box = shared struct { ... }` decl.
    source = (
        "type Box = shared struct { x: int64 }\n"
        "func main() -> int64 {\n"
        "  let b: Box = Box(x: 5)\n"
        "  return b.x\n"
        "}\n"
    )
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": "file:///tmp/structdef.kod",
                        "languageId": "kod",
                        "version": 1,
                        "text": source,
                    }
                },
            },
            # Cursor on the `Box` in the type annotation on line 2.
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/definition",
                "params": {
                    "textDocument": {"uri": "file:///tmp/structdef.kod"},
                    "position": {"line": 2, "character": 10},
                },
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    defn = next(r for r in responses if r.get("id") == 2)
    loc = defn["result"]
    assert loc is not None
    # `type Box = ...` — name `Box` is at column 5 of line 0.
    assert loc["range"]["start"] == {"line": 0, "character": 5}


def test_hover_renders_struct_decl(lsp_binary):
    source = (
        "type Box = shared struct {\n"
        "  x: int64\n"
        "  name: str\n"
        "}\n"
        "func main() -> int64 {\n"
        '  let b: Box = Box(x: 5, name: "a")\n'
        "  return b.x\n"
        "}\n"
    )
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": "file:///tmp/structhover.kod",
                        "languageId": "kod",
                        "version": 1,
                        "text": source,
                    }
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/hover",
                "params": {
                    "textDocument": {"uri": "file:///tmp/structhover.kod"},
                    # `let b: Box` is now on line 5 (after the
                    # multi-line struct decl). Box starts at col 9.
                    "position": {"line": 5, "character": 10},
                },
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    hover = next(r for r in responses if r.get("id") == 2)
    assert hover["result"] is not None
    value = hover["result"]["contents"]["value"]
    assert "type Box = struct" in value
    assert "x: int64" in value
    assert "name: str" in value


def test_definition_resolves_enum_type(lsp_binary):
    source = (
        "type Color = enum { Red, Green, Blue }\n"
        "func main() -> int64 {\n"
        "  let c: Color = Color.Red\n"
        "  return 0\n"
        "}\n"
    )
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": "file:///tmp/enumdef.kod",
                        "languageId": "kod",
                        "version": 1,
                        "text": source,
                    }
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/definition",
                "params": {
                    "textDocument": {"uri": "file:///tmp/enumdef.kod"},
                    "position": {"line": 2, "character": 10},
                },
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    defn = next(r for r in responses if r.get("id") == 2)
    loc = defn["result"]
    assert loc is not None
    # `type Color = ...` — name at column 5 of line 0.
    assert loc["range"]["start"] == {"line": 0, "character": 5}


def test_definition_resolves_method(lsp_binary):
    # Cursor on `bump` in `c.bump()` should jump to the
    # `func bump(self) -> none` decl on the Counter struct.
    source = (
        "type Counter = shared struct {\n"
        "  value: int64\n"
        "  func bump(self) -> none {\n"
        "    self.value = self.value + 1\n"
        "  }\n"
        "}\n"
        "func main() -> int64 {\n"
        "  let c: Counter = Counter(value: 0)\n"
        "  c.bump()\n"
        "  return c.value\n"
        "}\n"
    )
    # Cursor on `bump` in `c.bump()` — line 8 (0-indexed), char 4.
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": "file:///tmp/method.kod",
                        "languageId": "kod",
                        "version": 1,
                        "text": source,
                    }
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/definition",
                "params": {
                    "textDocument": {"uri": "file:///tmp/method.kod"},
                    "position": {"line": 8, "character": 4},
                },
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    defn = next(r for r in responses if r.get("id") == 2)
    loc = defn["result"]
    assert loc is not None
    # `func bump(self)` is on line 2, name `bump` starts at column 7.
    assert loc["range"]["start"] == {"line": 2, "character": 7}


def test_hover_renders_method_signature(lsp_binary):
    source = (
        "type Counter = shared struct {\n"
        "  value: int64\n"
        "  func bump(self, anon by: int64) -> int64 {\n"
        "    self.value = self.value + by\n"
        "    return self.value\n"
        "  }\n"
        "}\n"
        "func main() -> int64 {\n"
        "  let c: Counter = Counter(value: 0)\n"
        "  return c.bump(3)\n"
        "}\n"
    )
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": "file:///tmp/methodhover.kod",
                        "languageId": "kod",
                        "version": 1,
                        "text": source,
                    }
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/hover",
                "params": {
                    "textDocument": {"uri": "file:///tmp/methodhover.kod"},
                    "position": {"line": 9, "character": 11},
                },
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    hover = next(r for r in responses if r.get("id") == 2)
    assert hover["result"] is not None
    value = hover["result"]["contents"]["value"]
    assert "Counter.bump" in value
    assert "int64" in value


def test_definition_resolves_same_module_function(lsp_binary):
    # A call site `helper()` should resolve to its `func helper(...)`
    # decl in the same buffer. Exercises the cg.func_idx path rather
    # than the cross-module import_fns one.
    source = (
        "func helper() -> int64 {\n"
        "  return 42\n"
        "}\n"
        "func main() -> int64 {\n"
        "  return helper()\n"
        "}\n"
    )
    # Line 4 (0-indexed), character 11 lands inside `helper()`.
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": "file:///tmp/same.kod",
                        "languageId": "kod",
                        "version": 1,
                        "text": source,
                    }
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/definition",
                "params": {
                    "textDocument": {"uri": "file:///tmp/same.kod"},
                    "position": {"line": 4, "character": 11},
                },
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    defn = next(r for r in responses if r.get("id") == 2)
    loc = defn["result"]
    assert loc is not None
    assert loc["uri"].endswith("/tmp/same.kod")
    # `func helper()` decl is on line 0, name identifier starts at col 5.
    assert loc["range"]["start"] == {"line": 0, "character": 5}


def test_definition_resolves_cross_module_function(lsp_binary):
    # `io.read_file(...)` should resolve to `func read_file(...)` in
    # stdlib/io.kod. The LSP compiles the buffer, looks up `read_file`
    # in cg.import_fns, and returns a Location pointing at the decl.
    source = (
        'import "io"\n'
        "func main() -> int64 {\n"
        '  let s: str = io.read_file("/dev/null")\n'
        "  return 0\n"
        "}\n"
    )
    # Cursor in the middle of `read_file` on line 2 (0-indexed),
    # character 20 lands inside the identifier.
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": "file:///tmp/gtd.kod",
                        "languageId": "kod",
                        "version": 1,
                        "text": source,
                    }
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/definition",
                "params": {
                    "textDocument": {"uri": "file:///tmp/gtd.kod"},
                    "position": {"line": 2, "character": 20},
                },
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    init = next(r for r in responses if r.get("id") == 1)
    assert init["result"]["capabilities"]["definitionProvider"] is True
    defn = next(r for r in responses if r.get("id") == 2)
    loc = defn["result"]
    assert loc is not None, "expected a Location, got null"
    assert loc["uri"].endswith("stdlib/io.kod"), loc["uri"]
    # io.kod's `func read_file(...)` is on a known line; the LSP returns
    # the span of the name identifier so we expect a non-zero column.
    assert loc["range"]["start"]["character"] > 0


def test_parse_error_emits_diagnostic(lsp_binary):
    # The self-hosted parser used to advance silently past unexpected
    # tokens, so syntactically bad input fed a garbage AST to codegen
    # and the LSP either reported nothing or some confusing downstream
    # error. With the structured ParseError path, `expect()` records
    # `expected X, got Y` and the LSP publishes it as a diagnostic.
    bad_source = 'func main() -> int64 {\n  print("hi"\n  return 0\n}\n'
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": "file:///tmp/parse.kod",
                        "languageId": "kod",
                        "version": 1,
                        "text": bad_source,
                    }
                },
            },
            {"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    diag_msgs = [
        r for r in responses if r.get("method") == "textDocument/publishDiagnostics"
    ]
    assert len(diag_msgs) == 1
    diags = diag_msgs[0]["params"]["diagnostics"]
    assert any("expected `)`" in d["message"] for d in diags), (
        f"no `expected )` in diags: {diags}"
    )


def test_cross_module_import_resolves(lsp_binary):
    # Buffer that pulls in stdlib `io` and uses io.read_file should
    # compile cleanly. The previous LSP only loaded builtins +
    # primitives, so any `io.foo()` reference was reported as
    # `unknown name`. With the import walk, names from imported
    # modules resolve and we emit no diagnostics.
    source = (
        'import "io"\n'
        "func main() -> int64 {\n"
        '  let s: str = io.read_file("/dev/null")\n'
        "  return 0\n"
        "}\n"
    )
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": "file:///tmp/cross.kod",
                        "languageId": "kod",
                        "version": 1,
                        "text": source,
                    }
                },
            },
            {"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    diag_msgs = [
        r for r in responses if r.get("method") == "textDocument/publishDiagnostics"
    ]
    assert len(diag_msgs) == 1
    assert diag_msgs[0]["params"]["diagnostics"] == [], (
        f"unexpected diagnostics: {diag_msgs[0]['params']['diagnostics']}"
    )


def test_debounce_coalesces_typing_burst(lsp_binary):
    # 30 rapid didChange notifications followed by a 350ms idle period
    # (> the 250ms debounce window). The LSP should compile + publish
    # exactly once after the burst settles, not once per change.
    import subprocess as _sp
    import time

    process = _sp.Popen(
        [str(lsp_binary)],
        stdin=_sp.PIPE,
        stdout=_sp.PIPE,
        stderr=_sp.PIPE,
        cwd=ROOT,
    )
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": "file:///tmp/burst.kod",
                    "languageId": "kod",
                    "version": 1,
                    "text": "func main() -> int64 { return 0 }\n",
                }
            },
        },
    ]
    for i in range(30):
        msgs.append(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didChange",
                "params": {
                    "textDocument": {"uri": "file:///tmp/burst.kod", "version": i + 2},
                    "contentChanges": [
                        {"text": f"func main() -> int64 {{ return {i} }}\n"}
                    ],
                },
            }
        )
    process.stdin.write(b"".join(frame(m) for m in msgs))
    process.stdin.flush()
    time.sleep(0.35)  # > debounce_ms (250). Lets the LSP idle out.
    process.stdin.write(
        b"".join(
            frame(m)
            for m in [
                {"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": None},
                {"jsonrpc": "2.0", "method": "exit", "params": None},
            ]
        )
    )
    process.stdin.close()
    stdout, _ = process.communicate(timeout=10)
    assert process.returncode == 0
    responses = parse_frames(stdout)
    diag_msgs = [
        r for r in responses if r.get("method") == "textDocument/publishDiagnostics"
    ]
    # Debounce coalesces. We're tolerant of small fragmentation in
    # the pipe buffer between the test process and the LSP — what we
    # really want to assert is "many fewer compiles than didChanges."
    # 30 didChanges should produce a small handful of publishes at
    # most, never 30. Each one carries the final empty diagnostics.
    assert 1 <= len(diag_msgs) <= 5
    for d in diag_msgs:
        assert d["params"]["diagnostics"] == []


def test_did_change_republishes_diagnostics(lsp_binary):
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": "file:///tmp/edit.kod",
                        "languageId": "kod",
                        "version": 1,
                        "text": "func main() -> int64 { return 0 }\n",
                    }
                },
            },
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didChange",
                "params": {
                    "textDocument": {"uri": "file:///tmp/edit.kod", "version": 2},
                    "contentChanges": [
                        {"text": "func main() -> int64 {\n  oops()\n  return 0\n}\n"}
                    ],
                },
            },
            {"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    # Debounce coalesces the didOpen + didChange burst into a single
    # publish for the final buffer state. The test pipes both
    # notifications back-to-back, so the LSP never sees an idle gap;
    # the shutdown handler flushes the still-pending publish on the
    # way out, which is what we observe here.
    diag_msgs = [
        r for r in responses if r.get("method") == "textDocument/publishDiagnostics"
    ]
    assert len(diag_msgs) == 1
    diags = diag_msgs[0]["params"]["diagnostics"]
    assert any("oops" in d["message"] for d in diags)


def test_did_close_forgets_the_document(lsp_binary):
    uri = "file:///tmp/closing.kod"
    text = "func helper() -> int64 { return 1 }\nfunc main() -> int64 { return helper() }\n"
    hover = {"textDocument": {"uri": uri}, "position": {"line": 1, "character": 31}}
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "kod",
                        "version": 1,
                        "text": text,
                    }
                },
            },
            # The second hover reuses the first one's compile.
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/hover",
                "params": hover,
            },
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "textDocument/hover",
                "params": hover,
            },
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didClose",
                "params": {"textDocument": {"uri": uri}},
            },
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "textDocument/hover",
                "params": hover,
            },
            {"jsonrpc": "2.0", "id": 5, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    by_id = {r["id"]: r for r in responses if "id" in r}
    assert by_id[2]["result"] is not None
    assert "helper" in json.dumps(by_id[2]["result"])
    assert by_id[3]["result"] == by_id[2]["result"]
    # Closed, the document is gone: nothing to hover over.
    assert by_id[4]["result"] is None
    # The open's diagnostics (none), published with the first compile, then
    # the close's empty list.
    diag_msgs = [
        r["params"]
        for r in responses
        if r.get("method") == "textDocument/publishDiagnostics"
    ]
    assert diag_msgs == [
        {"uri": uri, "diagnostics": []},
        {"uri": uri, "diagnostics": []},
    ]


def _completion_labels(responses, response_id):
    """Extract the list of completion labels from a completion response."""
    resp = next(r for r in responses if r.get("id") == response_id)
    assert resp["result"] is not None, f"expected a CompletionList, got null: {resp}"
    return [item["label"] for item in resp["result"]["items"]]


def test_completion_offers_globals_at_bare_identifier(lsp_binary):
    # Cursor on the blank line inside main() — globals, imports, types
    # should all be present in the offered completions.
    source = (
        'import "io"\n'
        "func helper() -> int64 {\n"
        "  return 0\n"
        "}\n"
        "type Widget = shared struct {\n"
        "  size: int64\n"
        "}\n"
        "func main() -> int64 {\n"
        "  \n"
        "  return 0\n"
        "}\n"
    )
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": "file:///tmp/comp.kod",
                        "languageId": "kod",
                        "version": 1,
                        "text": source,
                    }
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/completion",
                "params": {
                    "textDocument": {"uri": "file:///tmp/comp.kod"},
                    # Line 7 is the blank line inside main(); col 2 is
                    # after the 2-space indent.
                    "position": {"line": 7, "character": 2},
                },
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    init = next(r for r in responses if r.get("id") == 1)
    cap = init["result"]["capabilities"]
    assert cap.get("completionProvider") is not None, (
        "completionProvider not advertised"
    )

    labels = _completion_labels(responses, 2)
    assert "helper" in labels  # free function
    assert "io" in labels  # import alias
    assert "Widget" in labels  # struct type name


def test_completion_module_qualified_returns_imports_exports(lsp_binary):
    # After `io.`, completions should be io's exported functions.
    source = 'import "io"\nfunc main() -> int64 {\n  io.\n  return 0\n}\n'
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": "file:///tmp/compdot.kod",
                        "languageId": "kod",
                        "version": 1,
                        "text": source,
                    }
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/completion",
                "params": {
                    "textDocument": {"uri": "file:///tmp/compdot.kod"},
                    # Position immediately after the `.` on line 2.
                    "position": {"line": 2, "character": 5},
                },
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    labels = _completion_labels(responses, 2)
    # io.kod exports these (externs are still functions from the
    # caller's perspective).
    assert "read_file" in labels
    assert "write_file" in labels
    # `helper` is a global free function — not exported by `io`.
    assert "helper" not in labels


def test_completion_str_methods_on_typed_variable(lsp_binary):
    # After `s.`, where `s: str` was declared above, completions should
    # include the methods registered on str (to_str, hash, code_points,
    # char_at, contains, …).
    source = 'func main() -> int64 {\n  let s: str = "hello"\n  s.\n  return 0\n}\n'
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": "file:///tmp/recvstr.kod",
                        "languageId": "kod",
                        "version": 1,
                        "text": source,
                    }
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/completion",
                "params": {
                    "textDocument": {"uri": "file:///tmp/recvstr.kod"},
                    # Line 2 is `  s.`; column 4 is just past the dot.
                    "position": {"line": 2, "character": 4},
                },
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    labels = _completion_labels(responses, 2)
    assert "to_str" in labels
    assert "hash" in labels
    assert "contains" in labels
    assert "char_at" in labels


def test_completion_struct_methods_and_fields_on_typed_variable(lsp_binary):
    # After `p.` where `p: Point`, completions include the struct's
    # methods (distance) and fields (x, y).
    source = (
        "type Point = shared struct {\n"
        "  x: int64\n"
        "  y: int64\n"
        "  func distance(self) -> int64 { return 0 }\n"
        "}\n"
        "func main() -> int64 {\n"
        "  let p: Point = Point(x: 1, y: 2)\n"
        "  p.\n"
        "  return 0\n"
        "}\n"
    )
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": "file:///tmp/recvstruct.kod",
                        "languageId": "kod",
                        "version": 1,
                        "text": source,
                    }
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/completion",
                "params": {
                    "textDocument": {"uri": "file:///tmp/recvstruct.kod"},
                    # Line 7 is `  p.`; column 4 is just past the dot.
                    "position": {"line": 7, "character": 4},
                },
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    labels = _completion_labels(responses, 2)
    assert "distance" in labels
    assert "x" in labels
    assert "y" in labels


def test_completion_receiver_through_function_param(lsp_binary):
    # The receiver's type can also come from a function parameter
    # annotation, not just a `let`. After `s.`, get str methods.
    source = "func helper(s: str) -> int64 {\n  s.\n  return 0\n}\n"
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": "file:///tmp/recvparam.kod",
                        "languageId": "kod",
                        "version": 1,
                        "text": source,
                    }
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/completion",
                "params": {
                    "textDocument": {"uri": "file:///tmp/recvparam.kod"},
                    "position": {"line": 1, "character": 4},
                },
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    labels = _completion_labels(responses, 2)
    assert "to_str" in labels
    assert "char_at" in labels


def test_completion_hides_underscore_methods_by_default(lsp_binary):
    # After `s.`, internal helpers (names starting with `_`) should
    # NOT appear in the offered completions.
    source = 'func main() -> int64 {\n  let s: str = "hi"\n  s.\n  return 0\n}\n'
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": "file:///tmp/hideund.kod",
                        "languageId": "kod",
                        "version": 1,
                        "text": source,
                    }
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/completion",
                "params": {
                    "textDocument": {"uri": "file:///tmp/hideund.kod"},
                    "position": {"line": 2, "character": 4},
                },
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    labels = _completion_labels(responses, 2)
    # Public methods still present
    assert "to_str" in labels
    assert "char_at" in labels
    # Internal helpers omitted
    assert "_utf8_width_at" not in labels
    assert "_utf8_value_at" not in labels


def test_completion_shows_underscore_methods_when_partial_starts_with_underscore(
    lsp_binary,
):
    # If the user has typed `s._`, they are explicitly looking at
    # internal names — show them.
    source = 'func main() -> int64 {\n  let s: str = "hi"\n  s._\n  return 0\n}\n'
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": "file:///tmp/showund.kod",
                        "languageId": "kod",
                        "version": 1,
                        "text": source,
                    }
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/completion",
                "params": {
                    "textDocument": {"uri": "file:///tmp/showund.kod"},
                    # Position right after `s._`
                    "position": {"line": 2, "character": 5},
                },
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    labels = _completion_labels(responses, 2)
    # Public methods still appear too (the client filters)
    assert "to_str" in labels
    # Internal helpers now visible
    assert "_utf8_width_at" in labels
    assert "_utf8_value_at" in labels


def test_hover_includes_leading_doc_comment(lsp_binary):
    # `func helper` has a leading `//` comment block — the hover
    # response should render those lines as a markdown paragraph
    # above the fenced signature.
    source = (
        "// Helper that returns the answer.\n"
        "// Spans two lines on purpose.\n"
        "func helper() -> int64 { return 42 }\n"
        "func main() -> int64 {\n"
        "  return helper()\n"
        "}\n"
    )
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": "file:///tmp/dochover.kod",
                        "languageId": "kod",
                        "version": 1,
                        "text": source,
                    }
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/hover",
                "params": {
                    "textDocument": {"uri": "file:///tmp/dochover.kod"},
                    # `helper` on line 4: index 0 = `func`, …, 9 = `h`.
                    "position": {"line": 4, "character": 11},
                },
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    hover = next(r for r in responses if r.get("id") == 2)
    value = hover["result"]["contents"]["value"]
    assert "Helper that returns the answer." in value
    assert "Spans two lines on purpose." in value
    assert "```kod" in value
    assert "func helper()" in value


def _same_named_types(tmp_path):
    """Two modules that each declare a struct `Pt`, and the buffer's file name."""
    (tmp_path / "pa.kod").write_text(
        "type Pt = shared struct {\n  x: int64\n  func size(self) -> int64 { return 1 }\n}\n"
        "func make() -> Pt {\n  return Pt(x: 1)\n}\n"
    )
    (tmp_path / "pb.kod").write_text(
        "type Pt = shared struct {\n  y: int64\n  func area(self) -> int64 { return 2 }\n}\n"
        "func make() -> Pt {\n  return Pt(y: 2)\n}\n"
    )
    return f"file://{tmp_path}/main.kod"


def _buffer_session(lsp_binary, uri, source, request):
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "kod",
                        "version": 1,
                        "text": source,
                    }
                },
            },
            {"jsonrpc": "2.0", "id": 2, **request},
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    return next(r for r in responses if r.get("id") == 2)


def test_definition_and_hover_find_a_type_through_its_module(lsp_binary, tmp_path):
    # `pa.Pt` and `pb.Pt` are different types of one name: the cursor on
    # `Pt` goes to the declaration in the module written before the dot.
    uri = _same_named_types(tmp_path)
    source = (
        'import "./pa"\n'
        'import "./pb"\n'
        "func main() -> int64 {\n"
        "  let a: pa.Pt = pa.make()\n"
        "  let b: pb.Pt = pb.make()\n"
        "  return 0\n"
        "}\n"
    )
    for line, module, field in ((3, "pa", "x"), (4, "pb", "y")):
        position = {"line": line, "character": 13}
        defn = _buffer_session(
            lsp_binary,
            uri,
            source,
            {
                "method": "textDocument/definition",
                "params": {"textDocument": {"uri": uri}, "position": position},
            },
        )
        assert defn["result"]["uri"].endswith(f"/{module}.kod"), defn
        assert defn["result"]["range"]["start"] == {"line": 0, "character": 5}
        hover = _buffer_session(
            lsp_binary,
            uri,
            source,
            {
                "method": "textDocument/hover",
                "params": {"textDocument": {"uri": uri}, "position": position},
            },
        )
        value = hover["result"]["contents"]["value"]
        assert f"{field}: int64" in value, value
        assert ("y: int64" if field == "x" else "x: int64") not in value, value


def test_definition_finds_a_bare_type_in_the_buffer_over_an_imported_one(
    lsp_binary, tmp_path
):
    # The buffer declares its own `Pt` too; a bare `Pt` is that one.
    uri = _same_named_types(tmp_path)
    source = (
        'import "./pa"\n'
        "type Pt = shared struct {\n  z: int64\n}\n"
        "func main() -> int64 {\n"
        "  let c: Pt = Pt(z: 3)\n"
        "  let a: pa.Pt = pa.make()\n"
        "  return c.z\n"
        "}\n"
    )
    defn = _buffer_session(
        lsp_binary,
        uri,
        source,
        {
            "method": "textDocument/definition",
            "params": {
                "textDocument": {"uri": uri},
                "position": {"line": 5, "character": 9},
            },
        },
    )
    assert defn["result"]["uri"].endswith("/main.kod"), defn
    assert defn["result"]["range"]["start"] == {"line": 1, "character": 5}


def test_completion_offers_the_members_of_the_type_the_buffer_means(
    lsp_binary, tmp_path
):
    uri = _same_named_types(tmp_path)
    source = (
        'import "./pa"\n'
        'import "./pb"\n'
        "type Pt = shared struct {\n  z: int64\n}\n"
        "func main() -> int64 {\n"
        "  let b: pb.Pt = pb.make()\n"
        "  b.\n"
        "  return 0\n"
        "}\n"
    )
    resp = _buffer_session(
        lsp_binary,
        uri,
        source,
        {
            "method": "textDocument/completion",
            "params": {
                "textDocument": {"uri": uri},
                "position": {"line": 7, "character": 4},
            },
        },
    )
    labels = [item["label"] for item in resp["result"]["items"]]
    assert "y" in labels and "area" in labels, labels
    assert "x" not in labels and "size" not in labels and "z" not in labels, labels
    # A bare completion offers the one `Pt` the buffer can write.
    resp = _buffer_session(
        lsp_binary,
        uri,
        source.replace("  b.\n", "  \n"),
        {
            "method": "textDocument/completion",
            "params": {
                "textDocument": {"uri": uri},
                "position": {"line": 7, "character": 2},
            },
        },
    )
    labels = [item["label"] for item in resp["result"]["items"]]
    assert labels.count("Pt") == 1, labels


def test_completion_after_a_block_that_hid_the_receiver(lsp_binary, tmp_path):
    # An inner `let v` hides the outer one until its block ends; the
    # members offered are those of the `v` in force at the cursor.
    uri = _same_named_types(tmp_path)
    source = (
        'import "./pa"\n'
        'import "./pb"\n'
        "func main(p: pb.Pt) -> int64 {\n"
        "  let v: pa.Pt = pa.make()\n"
        "  if true {\n"
        "    let v: pb.Pt = pb.make()\n"
        "    print_int(v.y)\n"
        "    p.\n"
        "  }\n"
        "  v.\n"
        "  return 0\n"
        "}\n"
    )

    def labels_at(line, character, text):
        resp = _buffer_session(
            lsp_binary,
            uri,
            text,
            {
                "method": "textDocument/completion",
                "params": {
                    "textDocument": {"uri": uri},
                    "position": {"line": line, "character": character},
                },
            },
        )
        return [item["label"] for item in resp["result"]["items"]]

    after = labels_at(9, 4, source)
    assert "x" in after and "size" in after, after
    assert "y" not in after and "area" not in after, after
    inside = labels_at(7, 6, source.replace("    p.\n", "    v.\n"))
    assert "y" in inside and "area" in inside, inside
    assert "x" not in inside and "size" not in inside, inside
    # A parameter hidden in an inner block is back after it.
    hidden = source.replace("  let v: pa.Pt = pa.make()\n", "").replace(
        "main(p: pb.Pt)", "main(v: pa.Pt)"
    )
    after_param = labels_at(8, 4, hidden)
    assert "x" in after_param and "y" not in after_param, after_param


def test_completion_ignores_braces_in_strings_chars_and_comments(lsp_binary, tmp_path):
    # Only braces the lexer reads as braces open or close a block: a `}`
    # in a string, a char literal or a comment between the `let` and the
    # cursor leaves the receiver's block open, and a `{` there leaves a
    # closed inner block closed.
    uri = _same_named_types(tmp_path)

    def labels_after(*lines):
        source = (
            'import "./pa"\nimport "./pb"\nfunc main() -> int64 {\n'
            + "  let v: pa.Pt = pa.make()\n"
            + "".join(f"  {line}\n" for line in lines)
            + "  v.\n  return 0\n}\n"
        )
        line = source.count("\n", 0, source.index("  v.\n"))
        resp = _buffer_session(
            lsp_binary,
            uri,
            source,
            {
                "method": "textDocument/completion",
                "params": {
                    "textDocument": {"uri": uri},
                    "position": {"line": line, "character": 4},
                },
            },
        )
        return [item["label"] for item in resp["result"]["items"]]

    for line in (
        'print("}")',
        "print('}')",
        "// close } here",
        'print(f"\\}")',
        'print("""}""")',
    ):
        labels = labels_after(line)
        assert "x" in labels and "size" in labels, (line, labels)
    # A `{` in a string does not keep an ended block open: the `v` of the
    # block is not the one in force after it.
    labels = labels_after(
        "if true {", "  let v: pb.Pt = pb.make()", "  print(v.y)", "}", 'print("{")'
    )
    assert "x" in labels and "y" not in labels, labels


def _hover_and_diagnostics(lsp_binary, source, line, character):
    """The hover contents (None when there is no hover) and the diagnostics
    published for `source`, with the cursor at `line`, `character`."""
    uri = "file:///tmp/directives.kod"
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "kod",
                        "version": 1,
                        "text": source,
                    }
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/hover",
                "params": {
                    "textDocument": {"uri": uri},
                    "position": {"line": line, "character": character},
                },
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    hover = next(r for r in responses if r.get("id") == 2)["result"]
    published = [
        r for r in responses if r.get("method") == "textDocument/publishDiagnostics"
    ]
    diagnostics = [d for r in published for d in r["params"]["diagnostics"]]
    return (hover["contents"]["value"] if hover else None), diagnostics


def test_the_link_directives_of_a_module_are_comments_to_the_language_server(
    lsp_binary,
):
    # tests/link/zlib_crc.kod: a block of `// kod:` lines, a blank line, then
    # the declarations. The block is no doc comment and no diagnostic.
    source = (ROOT / "tests" / "link" / "zlib_crc.kod").read_text()
    line = next(
        i for i, text in enumerate(source.splitlines()) if text.startswith("func crc32")
    )
    value, diagnostics = _hover_and_diagnostics(lsp_binary, source, line, 7)
    assert value is not None and "func crc32" in value
    assert "kod:" not in value
    assert diagnostics == []


def test_a_directive_block_with_no_blank_line_after_it_is_the_first_declarations_doc(
    lsp_binary,
):
    # What docs/modules.md warns of: the parser takes the comment block above a
    # declaration as its doc comment. Nothing breaks; the hover shows the lines.
    source = (
        "// kod:cc zlib_crc.c\n"
        "// kod:link -lz\n"
        "func crc(anon n: int64) -> int64 {\n"
        "  return n\n"
        "}\n"
        "func main() -> int64 {\n"
        "  return crc(1)\n"
        "}\n"
    )
    value, diagnostics = _hover_and_diagnostics(lsp_binary, source, 6, 10)
    assert value is not None and "func crc" in value
    assert "kod:link -lz" in value
    assert diagnostics == []


INTERFACE_SOURCE = (
    "interface Counter {\n"  # 0
    "    func next(self) -> int64\n"  # 1
    "\n"  # 2
    "    // Add up the next n values.\n"  # 3
    "    func sum(self, anon n: int64) -> int64 {\n"  # 4
    "        return self.next() * n\n"  # 5
    "    }\n"  # 6
    "}\n"  # 7
    "type Steps = shared struct {\n"  # 8
    "    func next(self) -> int64 {\n"  # 9
    "        return 1\n"  # 10
    "    }\n"  # 11
    "}\n"  # 12
    "type Dice = enum {\n"  # 13
    "    Six\n"  # 14
    "    func roll(self) -> int64 {\n"  # 15
    "        return 6\n"  # 16
    "    }\n"  # 17
    "}\n"  # 18
    "func main() -> int64 {\n"  # 19
    "    let c: Counter = Steps()\n"  # 20
    "    return c.sum(2) + Dice.Six.roll()\n"  # 21
    "}\n"  # 22
)


def test_hover_on_an_interface_name_lists_its_methods(lsp_binary):
    value, diagnostics = _hover_and_diagnostics(lsp_binary, INTERFACE_SOURCE, 20, 12)
    assert diagnostics == []
    assert value is not None
    assert "interface Counter {" in value
    assert "func next() -> int64" in value
    assert "func sum(anon n: int64) -> int64 { ... }" in value


def test_hover_on_an_interface_method_shows_it_and_its_doc(lsp_binary):
    value, _ = _hover_and_diagnostics(lsp_binary, INTERFACE_SOURCE, 21, 14)
    assert value is not None
    assert "func Counter.sum(" in value
    assert "Add up the next n values." in value


def test_hover_on_an_enum_method(lsp_binary):
    value, _ = _hover_and_diagnostics(lsp_binary, INTERFACE_SOURCE, 21, 32)
    assert value is not None
    assert "func Dice.roll(" in value


def test_hover_shows_a_struct_methods_doc_but_not_a_trailing_comment(lsp_binary):
    source = (
        "type Box = shared struct {\n"  # 0
        "    x: int64 // not a doc\n"  # 1
        "    func plain(self) -> int64 {\n"  # 2
        "        return self.x\n"  # 3
        "    }\n"  # 4
        "\n"  # 5
        "    // Twice x.\n"  # 6
        "    // Never negative for a positive x.\n"  # 7
        "    func double(self) -> int64 {\n"  # 8
        "        return self.x * 2\n"  # 9
        "    }\n"  # 10
        "}\n"  # 11
        "func main() -> int64 {\n"  # 12
        "    let b = Box(x: 1)\n"  # 13
        "    return b.plain() + b.double()\n"  # 14
        "}\n"  # 15
    )
    plain, diagnostics = _hover_and_diagnostics(lsp_binary, source, 14, 14)
    assert diagnostics == []
    assert plain is not None and "func Box.plain(self) -> int64" in plain
    assert "not a doc" not in plain
    double, _ = _hover_and_diagnostics(lsp_binary, source, 14, 26)
    assert double is not None
    assert "Twice x.\nNever negative for a positive x." in double


FIELD_SOURCE = (
    "type Node = shared struct {\n"  # 0
    "    name: str\n"  # 1
    "    weak up: Node?\n"  # 2
    "}\n"  # 3
    "func label(anon n: Node) -> str {\n"  # 4
    "    match n {\n"  # 5
    "        Node(up: Node(:name)) -> return name\n"  # 6
    "        else -> return n.name\n"  # 7
    "    }\n"  # 8
    "}\n"  # 9
    "func main() -> int64 {\n"  # 10
    '    let root = Node(name: "root")\n'  # 11
    "    print(label(root))\n"  # 12
    "    return 0\n"  # 13
    "}\n"  # 14
)


def _definition_at(lsp_binary, source, line, character):
    uri = "file:///tmp/fields.kod"
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "kod",
                        "version": 1,
                        "text": source,
                    }
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/definition",
                "params": {
                    "textDocument": {"uri": uri},
                    "position": {"line": line, "character": character},
                },
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    return next(r for r in responses if r.get("id") == 2)["result"]


def test_hover_on_a_struct_shows_its_weak_fields(lsp_binary):
    value, diagnostics = _hover_and_diagnostics(lsp_binary, FIELD_SOURCE, 11, 16)
    assert diagnostics == []
    assert value is not None
    assert "type Node = struct { name: str, weak up: Node? }" in value


def test_hover_on_a_field_after_a_dot(lsp_binary):
    value, _ = _hover_and_diagnostics(lsp_binary, FIELD_SOURCE, 7, 26)
    assert value is not None
    assert "Node.name: str" in value


def test_hover_on_a_field_label_in_a_construction_and_a_pattern(lsp_binary):
    built, _ = _hover_and_diagnostics(lsp_binary, FIELD_SOURCE, 11, 21)
    assert built is not None and "Node.name: str" in built
    weak, _ = _hover_and_diagnostics(lsp_binary, FIELD_SOURCE, 6, 14)
    assert weak is not None and "weak Node.up: Node?" in weak
    short, _ = _hover_and_diagnostics(lsp_binary, FIELD_SOURCE, 6, 24)
    assert short is not None and "Node.name: str" in short


def test_definition_of_a_field_goes_to_its_declaration(lsp_binary):
    loc = _definition_at(lsp_binary, FIELD_SOURCE, 6, 14)
    assert loc is not None
    assert loc["range"]["start"] == {"line": 2, "character": 9}
    dotted = _definition_at(lsp_binary, FIELD_SOURCE, 7, 26)
    assert dotted is not None
    assert dotted["range"]["start"] == {"line": 1, "character": 4}


LOCALS_SOURCE = (
    "type Bag = shared struct {\n"  # 0
    '    func size(self) -> str { return "bag" }\n'  # 1
    "}\n"  # 2
    "type Box = shared struct {\n"  # 3
    "    n: int64\n"  # 4
    "    func size(self) -> int64 { return self.n }\n"  # 5
    "}\n"  # 6
    "func main() -> int64 {\n"  # 7
    "    let b = Box(n: 3)\n"  # 8
    "    let total = b.size() + 1\n"  # 9
    "    for item in [b] {\n"  # 10
    "        print_int(item.n + total)\n"  # 11
    "    }\n"  # 12
    "    return total\n"  # 13
    "}\n"  # 14
)


def _at(source, line, needle, nth=0):
    """The (line, character) of the `nth` `needle` on `line` of `source`."""
    text = source.split("\n")[line]
    col = -1
    for _ in range(nth + 1):
        col = text.index(needle, col + 1)
    return line, col


def test_hover_on_a_local_shows_its_compiled_type(lsp_binary):
    value, diagnostics = _hover_and_diagnostics(
        lsp_binary, LOCALS_SOURCE, *_at(LOCALS_SOURCE, 13, "total")
    )
    assert diagnostics == []
    assert value is not None and "total: int64" in value
    value, _ = _hover_and_diagnostics(
        lsp_binary, LOCALS_SOURCE, *_at(LOCALS_SOURCE, 9, "b.")
    )
    assert value is not None and "b: Box" in value


def test_hover_on_a_for_variable_and_its_field(lsp_binary):
    value, _ = _hover_and_diagnostics(
        lsp_binary, LOCALS_SOURCE, *_at(LOCALS_SOURCE, 11, "item")
    )
    assert value is not None and "item: Box" in value
    line, col = _at(LOCALS_SOURCE, 11, ".n")
    value, _ = _hover_and_diagnostics(lsp_binary, LOCALS_SOURCE, line, col + 1)
    assert value is not None and "Box.n: int64" in value


def test_hover_on_a_method_uses_the_receivers_type(lsp_binary):
    line, col = _at(LOCALS_SOURCE, 9, ".size")
    value, _ = _hover_and_diagnostics(lsp_binary, LOCALS_SOURCE, line, col + 1)
    assert value is not None and "Box.size" in value and "Bag" not in value


def test_completion_on_a_receiver_whose_type_is_inferred(lsp_binary):
    # `p` has no written type, so only the compiled type says it's a Point.
    source = (
        "type Point = shared struct {\n"
        "  x: int64\n"
        "  func distance(self) -> int64 { return 0 }\n"
        "}\n"
        "func main() -> int64 {\n"
        "  for p in [Point(x: 1)] {\n"
        "    print_int(p.di)\n"
        "  }\n"
        "  return 0\n"
        "}\n"
    )
    uri = "file:///tmp/recvinferred.kod"
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "kod",
                        "version": 1,
                        "text": source,
                    }
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/completion",
                # Line 6 is `    print_int(p.di)`; column 18 is just past `di`.
                "params": {
                    "textDocument": {"uri": uri},
                    "position": {"line": 6, "character": 18},
                },
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    labels = _completion_labels(responses, 2)
    assert "distance" in labels
    assert "x" in labels


CHAIN_SOURCE = (
    "type Other = shared struct {\n"  # 0
    "    v: str\n"  # 1
    "    func twice(self) -> str { return self.v }\n"  # 2
    "}\n"  # 3
    "type Inner = shared struct {\n"  # 4
    "    v: int64\n"  # 5
    "    func twice(self) -> int64 { return self.v * 2 }\n"  # 6
    "    func half(self) -> int64 { return self.v / 2 }\n"  # 7
    "}\n"  # 8
    "type Outer = shared struct {\n"  # 9
    "    inner: Inner\n"  # 10
    "    items: [Inner]\n"  # 11
    "    func get(self) -> Inner { return self.inner }\n"  # 12
    "}\n"  # 13
    "func make() -> Outer {\n"  # 14
    "    return Outer(inner: Inner(v: 1), items: [Inner(v: 2)])\n"  # 15
    "}\n"  # 16
    "// A guess from the text would take `inner` for an Other, and `twice` for Other's.\n"  # 17
    "func misleading(inner: Other) -> str { return inner.twice() }\n"  # 18
    "func main() -> int64 {\n"  # 19
    "    let o = make()\n"  # 20
    "    print_int(o.inner.v)\n"  # 21
    "    print_int(make().inner.v)\n"  # 22
    "    print_int(o.items[0].v)\n"  # 23
    "    print_int(o.get().twice())\n"  # 24
    "    return 0\n"  # 25
    "}\n"  # 26
)


def _hover_after(source, line, needle):
    """The position just past the `.` of `needle` (which starts with one) on `line`."""
    line, col = _at(source, line, needle)
    return line, col + 1


def test_hover_on_a_field_of_a_field(lsp_binary):
    value, diagnostics = _hover_and_diagnostics(
        lsp_binary, CHAIN_SOURCE, *_hover_after(CHAIN_SOURCE, 21, ".v")
    )
    assert diagnostics == []
    assert value is not None and "Inner.v: int64" in value


def test_hover_on_a_field_of_a_call_and_of_an_element(lsp_binary):
    value, _ = _hover_and_diagnostics(
        lsp_binary, CHAIN_SOURCE, *_hover_after(CHAIN_SOURCE, 22, ".v")
    )
    assert value is not None and "Inner.v: int64" in value
    value, _ = _hover_and_diagnostics(
        lsp_binary, CHAIN_SOURCE, *_hover_after(CHAIN_SOURCE, 23, ".v")
    )
    assert value is not None and "Inner.v: int64" in value


def test_hover_on_a_method_of_a_method_result(lsp_binary):
    value, _ = _hover_and_diagnostics(
        lsp_binary, CHAIN_SOURCE, *_hover_after(CHAIN_SOURCE, 24, ".twice")
    )
    assert value is not None and "Inner.twice" in value and "Other" not in value


def test_completion_after_a_field_of_a_field(lsp_binary):
    source = CHAIN_SOURCE.replace("print_int(o.inner.v)", "print_int(o.inner.tw)")
    uri = "file:///tmp/chains.kod"
    line, col = _at(source, 21, ".tw")
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "kod",
                        "version": 1,
                        "text": source,
                    }
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/completion",
                "params": {
                    "textDocument": {"uri": uri},
                    "position": {"line": line, "character": col + 3},
                },
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    labels = _completion_labels(responses, 2)
    assert "twice" in labels
    assert "half" in labels


OPTIONAL_SOURCE = (
    "type Decoy = shared struct {\n"  # 0
    "    name: int64\n"  # 1
    "    func label(self) -> int64 { return self.name }\n"  # 2
    "}\n"  # 3
    "type Node = shared struct {\n"  # 4
    "    name: str\n"  # 5
    "    next: Node? = none\n"  # 6
    "    func label(self) -> str { return self.name }\n"  # 7
    "    func parent(self) -> Node? { return self.next }\n"  # 8
    "}\n"  # 9
    "func misleading(n: Decoy) -> int64 { return n.label() }\n"  # 10
    "func main() -> int64 {\n"  # 11
    '    let n = Node(name: "a", next: Node(name: "b"))\n'  # 12
    '    let first = n.next?.name? or ""\n'  # 13
    '    let second = n.next?.next?.label()? or ""\n'  # 14
    '    let third = n.parent()?.name? or ""\n'  # 15
    "    print(first + second + third)\n"  # 16
    "    return 0\n"  # 17
    "}\n"  # 18
)


def test_hover_through_optional_chains(lsp_binary):
    value, diagnostics = _hover_and_diagnostics(
        lsp_binary, OPTIONAL_SOURCE, *_hover_after(OPTIONAL_SOURCE, 13, ".name")
    )
    assert diagnostics == []
    assert value is not None and "Node.name: str" in value
    value, _ = _hover_and_diagnostics(
        lsp_binary, OPTIONAL_SOURCE, *_hover_after(OPTIONAL_SOURCE, 14, ".label")
    )
    assert value is not None and "Node.label" in value and "Decoy" not in value
    value, _ = _hover_and_diagnostics(
        lsp_binary, OPTIONAL_SOURCE, *_hover_after(OPTIONAL_SOURCE, 15, ".name")
    )
    assert value is not None and "Node.name: str" in value


def test_completion_after_an_optional_chain(lsp_binary):
    source = OPTIONAL_SOURCE.replace("n.next?.next?.label()", "n.next?.next?.par")
    uri = "file:///tmp/optchain.kod"
    line, col = _at(source, 14, "?.par")
    responses = drive(
        lsp_binary,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "kod",
                        "version": 1,
                        "text": source,
                    }
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/completion",
                "params": {
                    "textDocument": {"uri": uri},
                    "position": {"line": line, "character": col + 5},
                },
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit", "params": None},
        ],
    )
    labels = _completion_labels(responses, 2)
    assert "parent" in labels
    assert "next" in labels
