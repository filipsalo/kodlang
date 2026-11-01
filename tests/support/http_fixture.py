"""A scripted HTTP server for stdlib/net/client_test.kod.

Usage: http_fixture.py PORT [CERT KEY]. It answers on 127.0.0.1:PORT, one raw
response per path (see Handler.route), over TLS 1.2 when a certificate and key
are given, and exits by itself after two minutes. A connection stays open for
the next request unless the request or the route says otherwise.
"""

import gzip
import os
import socketserver
import ssl
import sys
import threading
import time

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 0
TLS_FILES = sys.argv[2:4]
LOCK = threading.Lock()
STATE = {"connections": 0, "drops": 0, "flaky": 0}


def reply(
    status: str, body: bytes = b"", headers: str = "", length: bool = True
) -> bytes:
    head = f"HTTP/1.1 {status}\r\n{headers}"
    if length:
        head += f"Content-Length: {len(body)}\r\n"
    return head.encode() + b"\r\n" + body


def redirect(status: str, location: str) -> bytes:
    return reply(status, b"moved", f"Location: {location}\r\n")


def chunked() -> bytes:
    parts = [b"Wiki", b"pedia", b" in\r\n\r\nchunks."]
    body = b"".join(f"{len(p):x}\r\n".encode() + p + b"\r\n" for p in parts)
    head = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
    return head + body + b"0\r\nX-Trailer: yes\r\n\r\n"


def echo(
    method: str, target: str, headers: list[tuple[str, str]], body: bytes
) -> bytes:
    lines = [f"{method} {target}"] + [f"{k}: {v}" for k, v in headers]
    text = "\n".join(lines).encode() + b"\n\n" + body
    return reply("200 OK", text)


class Handler(socketserver.StreamRequestHandler):
    def setup(self) -> None:
        if TLS_FILES:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.maximum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(TLS_FILES[0], TLS_FILES[1])
            self.request = context.wrap_socket(self.request, server_side=True)
        super().setup()
        self.conn_id = 0
        self.requests = 0
        self.close_after = False
        self.keep_open = False

    def read_request(self) -> tuple[str, str, list[tuple[str, str]], bytes] | None:
        request_line = self.rfile.readline().decode("latin-1").rstrip("\r\n")
        if not request_line:
            return None
        method, target, _ = request_line.split(" ", 2)
        headers: list[tuple[str, str]] = []
        while True:
            line = self.rfile.readline().decode("latin-1").rstrip("\r\n")
            if not line:
                break
            name, _, value = line.partition(":")
            headers.append((name, value.strip()))
        length = 0
        for name, value in headers:
            if name.lower() == "content-length":
                length = int(value)
        body = self.rfile.read(length) if length else b""
        return method, target, headers, body

    def handle(self) -> None:
        while True:
            request = self.read_request()
            if request is None:
                return
            method, target, headers, body = request
            if self.requests == 0:
                with LOCK:
                    STATE["connections"] += 1
                    self.conn_id = STATE["connections"]
            self.requests += 1
            self.close_after = False
            self.keep_open = False
            path = target.split("?", 1)[0]
            response = self.route(method, target, path, headers, body)
            if response is None:
                return
            self.wfile.write(response)
            self.wfile.flush()
            asked_close = any(
                n.lower() == "connection" and "close" in v.lower() for n, v in headers
            )
            head = response.split(b"\r\n\r\n", 1)[0].lower()
            status = head.split(b" ", 2)[1] if head.count(b" ") >= 2 else b""
            bodyless = method == "HEAD" or status in (b"204", b"304")
            framed = (
                bodyless or b"content-length:" in head or b"transfer-encoding:" in head
            )
            if (
                asked_close
                or self.close_after
                or not framed
                or b"connection: close" in head
            ):
                return

    def github(self, target: str, path: str, headers: list[tuple[str, str]]) -> bytes:
        return github(target, path, headers)

    def dribble(self) -> bytes:
        """A 20-byte body sent a byte at a time, 50 ms apart: every read makes
        progress, the whole takes a second."""
        self.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Length: 20\r\n\r\n")
        self.wfile.flush()
        for _ in range(20):
            time.sleep(0.05)
            self.wfile.write(b"x")
            self.wfile.flush()
        return b""

    def encoded(self, method: str, path: str) -> bytes:
        """Responses with a Content-Encoding."""
        plain = b"hello gzip"
        coding = "gzip"
        if path == "/gzip-empty":
            plain = b""
        elif path == "/gzip-bomb":
            plain = b"x" * 20_000_000
        elif path == "/gzip-big":
            plain = b"0123456789abcdef" * 300_000
        elif path == "/gzip-utf8":
            plain = "Café ☕".encode()
        body = gzip.compress(plain, mtime=0)
        if path == "/gzip-bad":
            body = b"this is not gzip data"
        elif path == "/br":
            coding, body = "br", b"\x8b\x02\x80binary"
        elif path == "/gzip-list":
            coding = "gzip, br"
        elif path == "/x-gzip":
            coding = "x-gzip"
        headers = f"Content-Encoding: {coding}\r\n"
        if path == "/gzip-chunked":
            half = len(body) // 2
            parts = [body[:half], body[half:]]
            framed = b"".join(f"{len(p):x}\r\n".encode() + p + b"\r\n" for p in parts)
            head = f"HTTP/1.1 200 OK\r\n{headers}Transfer-Encoding: chunked\r\n\r\n"
            return head.encode() + framed + b"0\r\n\r\n"
        if method == "HEAD":
            head = f"HTTP/1.1 200 OK\r\n{headers}Content-Length: {len(body)}\r\n\r\n"
            return head.encode()
        return reply("200 OK", body, headers)

    def route(
        self,
        method: str,
        target: str,
        path: str,
        headers: list[tuple[str, str]],
        body: bytes,
    ) -> bytes | None:
        if path.startswith("/repos/"):
            return self.github(target, path, headers)
        if path == "/stats":
            return reply("200 OK", str(STATE["connections"]).encode())
        if path == "/conn-id":
            return reply("200 OK", f"conn {self.conn_id} req {self.requests}".encode())
        if path == "/redir-id":
            return redirect("302 Found", "/conn-id")
        if path.startswith("/gzip") or path in ("/x-gzip", "/br"):
            return self.encoded(method, path)
        if path == "/lies":
            # Says close but leaves the socket open: only the header can tell.
            self.keep_open = True
            return reply("200 OK", b"lies", "Connection: close\r\n")
        if path == "/lies10":
            self.keep_open = True
            return b"HTTP/1.0 200 OK\r\nContent-Length: 4\r\n\r\nlies"
        if path == "/close-after":
            return reply("200 OK", b"bye", "Connection: close\r\n")
        if path == "/http10":
            self.close_after = True
            return b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nok"
        if path == "/http10-keep":
            return b"HTTP/1.0 200 OK\r\nConnection: keep-alive\r\nContent-Length: 2\r\n\r\nok"
        if path == "/silent-close":
            self.close_after = True
            return reply("200 OK", b"closing")
        if path == "/drop":
            with LOCK:
                STATE["drops"] += 1
            return None
        if path == "/drops":
            return reply("200 OK", str(STATE["drops"]).encode())
        if path == "/flaky":
            with LOCK:
                STATE["flaky"] += 1
                first = STATE["flaky"] % 2 == 1
            return None if first else reply("200 OK", b"recovered")
        if path == "/flaky-count":
            return reply("200 OK", str(STATE["flaky"]).encode())
        if path == "/hello":
            return reply(
                "200 OK", b"hello", "Content-Type: text/plain\r\nX-A: 1\r\nX-A: 2\r\n"
            )
        if path == "/echo":
            return echo(method, target, headers, body)
        if path == "/head":
            return b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\n"
        if path == "/chunked":
            return chunked()
        if path == "/close":
            return reply("200 OK", b"until close", length=False)
        if path == "/nocontent":
            return b"HTTP/1.1 204 No Content\r\n\r\n"
        if path == "/interim":
            return b"HTTP/1.1 100 Continue\r\n\r\n" + reply("200 OK", b"after interim")
        if path == "/302":
            return redirect("302 Found", "/echo")
        if path == "/301":
            return redirect("301 Moved Permanently", "/echo")
        if path == "/303":
            return redirect("303 See Other", "/echo")
        if path == "/307":
            return redirect("307 Temporary Redirect", "/echo")
        if path == "/308":
            return redirect("308 Permanent Redirect", "/echo")
        if path == "/relative":
            return redirect("302 Found", "hello")
        if path == "/dir/relative":
            return redirect("302 Found", "../hello")
        if path == "/absolute":
            return redirect("302 Found", f"http://127.0.0.1:{PORT}/hello")
        if path == "/cross-host":
            return redirect("302 Found", f"http://localhost:{PORT}/echo")
        if path == "/chain":
            return redirect("302 Found", "/302")
        if path == "/loop":
            return redirect("302 Found", "/loop")
        if path == "/no-location":
            return reply("302 Found", b"nowhere")
        if path == "/to-ftp":
            return redirect("302 Found", "ftp://example.com/")
        if path == "/slow":
            time.sleep(1.5)
            return reply("200 OK", b"late")
        if path == "/dribble":
            return self.dribble()
        if path == "/hop1":
            time.sleep(0.4)
            return redirect("302 Found", "/hop2")
        if path == "/hop2":
            time.sleep(0.4)
            return redirect("302 Found", "/hello")
        if path == "/big":
            return reply("200 OK", b"x" * 3_000_000)
        if path == "/truncated":
            self.close_after = True
            return b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\nshort"
        if path == "/garbage":
            return b"NOT HTTP AT ALL\r\n\r\n"
        if path == "/bomb":
            lines = "".join(f"X-{i}: v\r\n" for i in range(500))
            return reply("200 OK", b"", lines)
        if path == "/created":
            return reply("201 Created", b"made")
        if path == "/missing":
            return reply("404 Not Found", b"nope")
        return reply("404 Not Found", b"no such route")


def github(target: str, path: str, headers: list[tuple[str, str]]) -> bytes:
    """Enough of GitHub's repo API for examples/github_repo.kod."""
    sent = {name.lower(): value for name, value in headers}
    json_type = "Content-Type: application/json\r\n"
    if "user-agent" not in sent:
        body = b'{"message": "Request forbidden: send a User-Agent header"}'
        return reply("403 Forbidden", body, json_type)
    if sent.get("accept") != "application/vnd.github+json":
        return reply(
            "415 Unsupported Media Type", b'{"message": "bad Accept"}', json_type
        )
    parts = path.split("/")
    if parts[2:] == ["octo", "hello"]:
        body = (
            b'{"full_name": "octo/hello", "description": "Caf\\u00e9 \\u2615 tools",'
            b' "language": "Kod", "stargazers_count": 1234, "forks_count": 56,'
            b' "license": {"spdx_id": "MIT"}, "score": 9.5}'
        )
        return reply("200 OK", body, json_type)
    if parts[2:] == ["octo", "secret"]:
        if sent.get("authorization") != "Bearer s3cret":
            return reply("404 Not Found", b'{"message": "Not Found"}', json_type)
        body = b'{"full_name": "octo/secret", "description": null, "license": null}'
        return reply("200 OK", body, json_type)
    if parts[2:] == ["octo", "hello", "issues"]:
        if target.split("?", 1)[-1] != "state=open&per_page=3":
            return reply("400 Bad Request", b'{"message": "bad query"}', json_type)
        body = b'[{"number": 7, "title": "It crashes"}, {"number": 3, "title": "Add \\"docs\\""}]'
        return reply("200 OK", body, json_type)
    if parts[2:] == ["octo", "secret", "issues"]:
        return reply("200 OK", b"[]", json_type)
    if parts[2:] == ["octo", "quiet", "issues"]:
        return reply("200 OK", b"[]", json_type)
    if parts[2:] == ["octo", "quiet"]:
        return reply("200 OK", b'{"full_name": "octo/quiet"}', json_type)
    if parts[2:] == ["octo", "html"]:
        return reply("502 Bad Gateway", b"<html>upstream down</html>")
    return reply("404 Not Found", b'{"message": "Not Found"}', json_type)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    threading.Timer(120, lambda: os._exit(0)).start()
    with Server(("127.0.0.1", PORT), Handler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
