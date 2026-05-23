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
    diag_msgs = [
        r for r in responses if r.get("method") == "textDocument/publishDiagnostics"
    ]
    assert len(diag_msgs) == 2
    assert diag_msgs[0]["params"]["diagnostics"] == []
    second_diags = diag_msgs[1]["params"]["diagnostics"]
    assert any("oops" in d["message"] for d in second_diags)
