"""A scripted HTTP server for stdlib/net/client_test.kod.

Usage: http_fixture.py PORT. It answers on 127.0.0.1:PORT, one raw response per
path (see ROUTES), and exits by itself after two minutes.
"""

import os
import socketserver
import sys
import threading
import time

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 0


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
    def handle(self) -> None:
        request_line = self.rfile.readline().decode("latin-1").rstrip("\r\n")
        if not request_line:
            return
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
        path = target.split("?", 1)[0]
        self.wfile.write(self.route(method, target, path, headers, body))
        self.wfile.flush()

    def route(
        self,
        method: str,
        target: str,
        path: str,
        headers: list[tuple[str, str]],
        body: bytes,
    ) -> bytes:
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
        if path == "/big":
            return reply("200 OK", b"x" * 3_000_000)
        if path == "/truncated":
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


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    threading.Timer(120, lambda: os._exit(0)).start()
    with Server(("127.0.0.1", PORT), Handler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
