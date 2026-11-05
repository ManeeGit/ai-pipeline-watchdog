from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .service import Watchdog

STATIC = Path(__file__).parent / "static"


def make_server(app: Watchdog, port: int = 8765) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        server_version = "PipelineWatchdog/0.1"
        def log_message(self, format, *args):
            pass

        def respond(self, code: int, body: bytes, kind: str):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            allowed_hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get("Host") not in allowed_hosts:
                self.respond(403, b"Host rejected", "text/plain; charset=utf-8")
                return
            path = urlsplit(self.path).path
            try:
                if path == "/api/summary":
                    self.respond(200, json.dumps(app.summary(), allow_nan=False).encode(), "application/json; charset=utf-8")
                elif path == "/healthz":
                    self.respond(200, b'{"status":"ok","scope":"http-process-only"}', "application/json")
                elif path == "/metrics":
                    self.respond(200, app.metrics().encode(), "text/plain; version=0.0.4; charset=utf-8")
                elif path in {"/", "/app.js", "/styles.css"}:
                    name = "index.html" if path == "/" else path[1:]
                    kind = {"index.html": "text/html", "app.js": "application/javascript", "styles.css": "text/css"}[name]
                    self.respond(200, (STATIC / name).read_bytes(), f"{kind}; charset=utf-8")
                else:
                    self.respond(404, b"Not found", "text/plain; charset=utf-8")
            except (OSError, ValueError):
                self.respond(500, b'{"error":"Unable to read local state"}', "application/json")

        def do_POST(self):
            self.respond(405, b"Read-only dashboard", "text/plain; charset=utf-8")
        do_PUT = do_POST
        do_DELETE = do_POST
        do_PATCH = do_POST

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
