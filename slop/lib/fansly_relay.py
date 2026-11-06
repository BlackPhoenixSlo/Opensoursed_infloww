"""Fansly's API at its wire, for the formatted-script flow (scenarios/2026-11-05-rich-text-sends.py): lib/relay.py
loads this part (`wire` runs at the end of its `_wire`). The relay's REAL `FanslyShimClient` (seed/fansly_accounts.py
makes a Creator a Fansly account) sends through python-requests to apiv3.fansly.com; armed, that host goes to a
loopback fake in the relay process.

Inert until a scenario arms it: nothing here is patched before `POST /__slop/fansly/arm`, so every other scenario's
relay is untouched (a Fansly call there is refused by relay_guarded's socket guard, as before).

  arm(http)                  (harness side) POSTs the arm hook, answers {port}.
  POST /__slop/fansly/arm    (loopback; 409 under SLOP_LIVE=1)
       1. The fake: a loopback ThreadingHTTPServer (a thread per request) answering Fansly's `{success, response}`
          envelope for the send lane: GET /api/v1/messaging/groups (no DM groups yet: `{data: [], ...}`),
          POST /api/v1/group (a minted DM group `{id}`), POST /api/v1/message (the message as Fansly echoes it:
          `{id, groupId, senderId, content, createdAt, attachments: []}`). Anything else: 404, counted unmodelled.
       2. python-requests at its wire: `requests.Session.request` wrapped so a URL on apiv3.fansly.com goes to
          the fake (path + query kept); every other URL unchanged (the socket guard still refuses off-host).
  GET /__slop/fansly/calls   {calls, unmodelled}: every request the fake got, in arrival order:
       {i, t, method, path, token (the `authorization` header: seed/fansly_accounts.token), signed (the
       fansly-client-check header came), body (the JSON body), id (the minted group / message id, else None)}.

Bypasses (declared): Fansly's server is a loopback fake inside the relay process (shares its GIL); its answers'
shapes are fansly/test_automation_methods.py's (the captured recipes); the signature headers are never verified,
only their presence; no latency, no 4xx/5xx; `createdAt` is epoch seconds (a guess the shim does not read back).
"""


import itertools
import json
import os
import threading
import time
from urllib.parse import urlsplit

HOST = "apiv3.fansly.com"
_lock = threading.Lock()
_calls: list[dict] = []
_state: dict = {"port": None, "unmodelled": 0}
_ids = itertools.count(960_000_000_000_000_000)


async def arm(http) -> dict:
    r = await http.post("/__slop/fansly/arm")
    if r.status_code != 200:
        raise RuntimeError(f"slop: fansly arm hook answered {r.status_code}: {r.text[:200]}")
    return r.json()


def _answer(method: str, path: str, token: str, body) -> tuple[int, dict]:
    if method == "GET" and path == "/api/v1/messaging/groups":
        return 200, {"success": True, "response": {"data": [], "aggregationData": {}}}
    if method == "POST" and path == "/api/v1/group":
        return 200, {"success": True, "response": {"id": str(next(_ids))}}
    if method == "POST" and path == "/api/v1/message":
        sender = token.removeprefix("slop-fansly-")
        return 200, {"success": True, "response": {
            "id": str(next(_ids)), "groupId": str(body.get("groupId")), "senderId": sender,
            "content": body.get("content", ""), "createdAt": int(time.time()), "attachments": []}}
    with _lock:
        _state["unmodelled"] += 1
    return 404, {"success": False, "error": {"code": 404, "details": f"slop fake: unmodelled {method} {path}"}}


def _serve() -> int:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def _do(self):
            p = urlsplit(self.path)
            n = int(self.headers.get("content-length") or 0)
            raw = self.rfile.read(n) if n else b""
            try:
                body = json.loads(raw) if raw else None
            except ValueError:
                body = {"_raw": raw[:200].decode(errors="replace")}
            token = self.headers.get("authorization") or ""
            status, out = _answer(self.command, p.path, token, body if isinstance(body, dict) else {})
            with _lock:
                _calls.append({"i": len(_calls), "t": time.time(), "method": self.command, "path": p.path,
                               "token": token, "signed": "fansly-client-check" in self.headers, "body": body,
                               "id": (out.get("response") or {}).get("id") if status == 200 else None})
            data = json.dumps(out).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = _do

        def log_message(self, *_a):
            pass

    class Srv(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 256

    srv = Srv(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, name="slop-fake-fansly", daemon=True).start()
    return srv.server_address[1]


def _route_requests() -> None:
    """python-requests' Session.request: apiv3.fansly.com goes to the fake. Idempotent."""
    import requests
    inner = requests.Session.request
    if getattr(inner, "__slop_fansly__", False):
        return

    def request(self, method, url, *a, **k):
        p = urlsplit(str(url))
        if (p.hostname or "").lower() == HOST:
            url = f"http://127.0.0.1:{_state['port']}{p.path}" + (f"?{p.query}" if p.query else "")
        return inner(self, method, url, *a, **k)

    request.__slop_fansly__ = True
    requests.Session.request = request


def wire(app, loopback, relay) -> None:
    from fastapi import Request
    from fastapi.responses import JSONResponse

    async def arm_hook(request: Request):
        loopback(request)
        if os.environ.get("SLOP_LIVE") == "1":
            return JSONResponse({"error": "slop: SLOP_LIVE=1: the Fansly fake is not armed"}, status_code=409)
        if _state["port"] is None:
            _state["port"] = _serve()
        _route_requests()
        return {"port": _state["port"]}

    async def calls(request: Request) -> dict:
        loopback(request)
        with _lock:
            return {"calls": [dict(c) for c in _calls], "unmodelled": _state["unmodelled"]}

    app.add_api_route("/__slop/fansly/arm", arm_hook, methods=["POST"])
    app.add_api_route("/__slop/fansly/calls", calls, methods=["GET"])
