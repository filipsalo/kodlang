"""Drive the kod LSP server end-to-end: send a real LSP session over
stdin, read the framed responses, and check we get the expected shape
on each one. Builds the binary via `kod build` on first run."""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "build" / "apps" / "lsp" / "lsp"


@pytest.fixture(scope="module")
def lsp_binary():
    subprocess.run(
        [sys.executable, "-m", "kod", "build", "tools/lsp.kod"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
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
    assert "io.read_file" in value
    assert "str" in value


def test_definition_resolves_struct_type(lsp_binary):
    # Cursor on `Box` in `let b: Box = ...` should jump to the
    # `type Box = struct { ... }` decl.
    source = (
        "type Box = struct { x: int64 }\n"
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
        "type Box = struct {\n"
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
    assert any(
        "expected `)`" in d["message"] for d in diags
    ), f"no `expected )` in diags: {diags}"


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
    assert (
        diag_msgs[0]["params"]["diagnostics"] == []
    ), f"unexpected diagnostics: {diag_msgs[0]['params']['diagnostics']}"


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
