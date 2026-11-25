from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

import rollout_core
from fake_relay import SESSION


@pytest.fixture
def serve():
    servers = []

    def _serve(fake):
        class H(BaseHTTPRequestHandler):
            def _do(self, method):
                u = urlsplit(self.path)
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                body = json.loads(raw) if raw else None
                ck = self.headers.get("Cookie") or ""
                cookie = ck.split("chatterly_session=", 1)[1].split(";")[0] if "chatterly_session=" in ck else None
                res = fake.handle(method, u.path, parse_qs(u.query), body, cookie)
                status, payload = res[0], res[1]
                extra = dict(res[2] if len(res) > 2 else {})
                data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", extra.pop("Content-Type", "application/json"))
                self.send_header("Content-Length", str(len(data)))
                for k, v in extra.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._do("GET")

            def do_POST(self):
                self._do("POST")

            def log_message(self, *a):
                pass

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return f"http://127.0.0.1:{srv.server_address[1]}"

    yield _serve
    for s in servers:
        s.shutdown()


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(rollout_core, "POLL_S", 0.005)
    monkeypatch.setenv("SFR_SESSION", SESSION)
