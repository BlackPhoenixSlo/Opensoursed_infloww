"""OnlyFans' API at its wire, on loopback: what the relay's REAL `OFClient`
(curl_cffi, signed headers, its own error handling) reaches when a scenario sets
`OF_WIRE = True` (lib/cli.py starts it and points the relay's `OF_API_ORIGIN`,
the ADR 0024 seam, here). Runs in the harness process, a thread per request
(stdlib `ThreadingHTTPServer`: curl's `Upgrade: h2c` is ignored and the body
read, which uvicorn's httptools drops, ADR 0024), so the relay's calls arrive
concurrently and are recorded in arrival order.

  GET  /hash/?u=<uid>                      the CDN's x-hash (text), any account
  GET  /static/prod/f/<rev>/2313.js        the signing chunk (lib/browserbase.py's
                                           synthetic one): a paste-curl bootstrap
                                           derives its rules from it
  GET  /api2/v2/users/me                   the Creator: {id, username, name, wsUrl,
                                           wsAuthToken}: the WS pump's ticket
  GET  /api2/v2/chats                      OF's chat list, empty (`{"list": []}`): what
                                           the Creators strip's badges read while a
                                           pump is live (bypass, declared: no chats)
  GET  /api2/v2/users/notifications/count  the bell's counts, all zero (`{"all": 0, ...}`):
                                           the shell's per-Creator badge read
  GET  /cdn-cgi/trace                      Cloudflare's trace, as `proxies.probe` reads it
                                           (ip / loc / colo lines; lib/relay.py points
                                           `proxies.TRACE_URL` here under OF_WIRE), so a
                                           proxy's confirm and recheck probes go through
                                           the fake proxy to loopback, never to 1.1.1.1
  POST /api2/v2/chats/{fan}/messages       OF's new message (id, text, createdAt,
                                           fromUser), recorded per Creator in order
  GET  /api2/v2/subscriptions/count/all    the fan counts (`subscribers.active/all/expired`,
                                           fixed per Creator): the Dashboard's Per-model cards
  GET  /api2/v2/subscriptions/subscribers/chart
                                           OF's Subscriptions chart, no new fans (`subscribers` 0)
  GET  /api2/v2/payouts/referrals/chart    Statements › Referrals, $0 (`total` 0): the
                                           Dashboard's Referrals tile
  GET  /api2/v2/users/notifications        the alerts feed, empty: the purchases poller
  any other path                           404, counted (`unmodelled`)

`extra_s[uid]` adds seconds to every /api2/ call of that Creator: a Creator whose proxy
fails and is retried (bypass, declared: no proxy hop exists here, so the retries are
modelled as their measured cost, not run).

OF's chat WebSocket (`wsUrl`, ws://127.0.0.1:<port>/ws3/<uid>; the relay's real
of_ws pump connects here): the client's `{"act":"connect","token":…}` is answered
`{"connected":true,"v":"5.4.0"}` as OF does; then the socket stays open, reading
what the client sends (pings) and pushing nothing. Each connect is recorded
(`ws_connects`: t, account, token as issued). `drop_ws(ids)` closes those
Creators' sockets, as OF does when it ends a session's socket: the pump
reconnects through /users/me.

A Creator in `otp` (set by the scenario at any time) is a login OnlyFans has
asked to confirm with a 2FA code: every /api2/ call it makes is answered 400
with OF's code-101 body (`OTP_BODY`; `payload.otpState` and `strong` as OF web's
bundle reads them on code 101, the message text a guess).

The Creator is the request's signed `User-ID` header (the hash CDN's `u=`).
Bypass, declared: the `Sign` / `Time` / `X-Hash` headers are only checked to be
present (`unsigned` counts calls without them), never verified; `LATENCY_S`
(50 ms per call) is a guess at OF's latency.
"""
from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

LATENCY_S = 0.05
OTP_BODY = {"error": {"code": 101, "message": "Confirm it is you", "payload": {
    "otpState": {"email": False, "phoneOtp": False, "appOtp": True, "faceOtp": False, "forceFaceOtp": False,
                 "phoneLast4": "", "phoneCode": {}, "faceCode": {}, "emailCode": {}},
    "strong": False}}}
_SEND = re.compile(r"/api2/v2/chats/(\d+)/messages")
_NUM = re.compile(r"/\d+(?=/|$)")
_CHUNK = re.compile(r"/static/prod/f/[^/]+/2313\.js")


class FakeOF:
    def __init__(self, latency_s: float = LATENCY_S):
        self.latency_s = latency_s
        self.otp: set[str] = set()
        self.extra_s: dict[str, float] = {}  # per Creator, seconds added to each /api2/ call
        self.lock = threading.Lock()
        self.calls: list[dict] = []          # every call, arrival order: {t, account, method, route, status}
        self.sends: dict[str, list[dict]] = {}  # per Creator, the messages OF accepted, in order (`t`: arrival)
        self.unmodelled: Counter = Counter()
        self.unsigned = 0
        self._ids = iter(range(9_000_000_000, 10**12))
        self._srv: ThreadingHTTPServer | None = None
        self.ws_connects: list[dict] = []  # arrival order: {t, account, token_ok}
        self._ws_open: dict[str, set] = {}  # account -> its open server-side sockets
        self._ws_loop: asyncio.AbstractEventLoop | None = None
        self._ws_port = 0
        self._chunk: str | None = None

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self._srv.server_address[1]}"

    def __enter__(self) -> "FakeOF":
        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._srv.daemon_threads = True
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        up = threading.Event()
        threading.Thread(target=self._ws_main, args=(up,), daemon=True).start()
        if not up.wait(10):
            raise SystemExit("slop: the fake OF WebSocket did not start")
        return self

    def __exit__(self, *_a) -> None:
        if self._srv is not None:
            self._srv.shutdown()
            self._srv.server_close()
        if self._ws_loop is not None:
            self._ws_loop.call_soon_threadsafe(self._ws_loop.stop)

    def _ws_main(self, up: threading.Event) -> None:
        import websockets

        fake = self

        async def session(ws) -> None:
            uid = ws.request.path.rstrip("/").rsplit("/", 1)[-1]
            try:
                hello = json.loads(await ws.recv())
            except Exception:  # noqa: BLE001 — a client that never says connect
                return
            with fake.lock:
                fake.ws_connects.append({"t": time.time(), "account": uid,
                                         "token_ok": hello.get("token") == f"slop-ws-{uid}"})
                fake._ws_open.setdefault(uid, set()).add(ws)
            try:
                await ws.send(json.dumps({"connected": True, "v": "5.4.0"}))
                async for _ in ws:  # the client's pings (get_onlines): nothing to answer
                    pass
            except websockets.ConnectionClosed:
                pass
            finally:
                with fake.lock:
                    fake._ws_open.get(uid, set()).discard(ws)

        async def start():
            return await websockets.serve(session, "127.0.0.1", 0)

        loop = asyncio.new_event_loop()
        self._ws_srv = loop.run_until_complete(start())  # held: the loop keeps only weak task refs
        self._ws_port = self._ws_srv.sockets[0].getsockname()[1]
        self._ws_loop = loop
        up.set()
        try:
            loop.run_forever()
        finally:
            loop.close()

    def drop_ws(self, account_ids) -> int:
        """Close these Creators' open sockets (OF ends them). Returns how many."""
        with self.lock:
            socks = [ws for a in account_ids for ws in self._ws_open.get(str(a), ())]
        for ws in socks:
            asyncio.run_coroutine_threadsafe(ws.close(), self._ws_loop).result(10)
        return len(socks)

    def ws_live(self) -> dict[str, int]:
        """Per Creator, its open sockets right now."""
        with self.lock:
            return {a: len(v) for a, v in self._ws_open.items() if v}

    def set_otp(self, account_ids) -> float:
        """From now on these Creators' logins want a 2FA code. Returns the epoch time."""
        with self.lock:
            self.otp = {str(a) for a in account_ids}
            return time.time()

    def chunk(self) -> str:
        if self._chunk is None:
            from slop.lib.browserbase import signing  # lazy: imports service/of_signer
            self._chunk = signing("0", "slop-rev", 0)["chunk"]
        return self._chunk

    def snapshot(self) -> dict:
        with self.lock:
            per = Counter((c["account"], c["route"], c["status"]) for c in self.calls)
            return {"calls": len(self.calls), "unsigned": self.unsigned, "unmodelled": dict(self.unmodelled),
                    "sends": {a: len(v) for a, v in self.sends.items()},
                    "ws_connects": len(self.ws_connects),
                    "by_route": {f"{a} {r} {s}": n for (a, r, s), n in sorted(per.items())}}

    def _handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_a):
                pass

            def _send(self, code: int, body, ctype: str = "application/json") -> None:
                data = body if isinstance(body, bytes) else (
                    body.encode() if isinstance(body, str) else json.dumps(body).encode())
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _serve(self, method: str) -> None:
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                u = urlsplit(self.path)
                route = f"{method} {_NUM.sub('/{id}', u.path)}"
                if u.path.rstrip("/") == "/hash":
                    uid = (parse_qs(u.query).get("u") or [""])[0]
                    return self._record(uid, route, 200, "%040x" % (hash(uid) & (2**160 - 1)), "text/plain")
                if method == "GET" and _CHUNK.fullmatch(u.path):
                    return self._record("", "GET /static/prod/f/{rev}/2313.js", 200, fake.chunk(),
                                        "application/javascript")
                if method == "GET" and u.path == "/cdn-cgi/trace":
                    return self._record("", route, 200, "fl=1\nh=127.0.0.1\nip=127.0.0.1\nts=0\n"
                                        "visit_scheme=http\nloc=SL\ncolo=SLOP\nhttp=http/1.1\n", "text/plain")
                uid = self.headers.get("User-ID") or ""
                if u.path.startswith("/api2/") and not all(self.headers.get(h) for h in ("Sign", "Time", "X-Hash")):
                    with fake.lock:
                        fake.unsigned += 1
                time.sleep(fake.latency_s + (fake.extra_s.get(uid, 0.0) if u.path.startswith("/api2/") else 0.0))
                with fake.lock:
                    otp = uid in fake.otp
                if u.path.startswith("/api2/") and otp:
                    return self._record(uid, route, 400, OTP_BODY)
                if method == "GET" and u.path == "/api2/v2/users/me":
                    return self._record(uid, route, 200, {"id": int(uid or 0), "username": f"u{uid}",
                                                          "name": f"Creator {uid}", "isPerformer": True,
                                                          "wsUrl": f"ws://127.0.0.1:{fake._ws_port}/ws3/{uid}",
                                                          "wsAuthToken": f"slop-ws-{uid}"})
                if method == "GET" and u.path == "/api2/v2/chats":
                    return self._record(uid, route, 200, {"list": [], "hasMore": False, "nextOffset": 0})
                if method == "GET" and u.path == "/api2/v2/users/notifications/count":
                    return self._record(uid, route, 200, {"all": 0, "subscribed": 0, "purchases": 0, "tip": 0})
                if method == "GET" and u.path == "/api2/v2/subscriptions/count/all":
                    n = int(uid or 0) % 900 + 100
                    return self._record(uid, route, 200, {"subscribers": {"active": n, "all": 2 * n, "expired": n},
                                                          "subscriptions": {"active": 0, "all": 0, "expired": 0}})
                if method == "GET" and u.path == "/api2/v2/subscriptions/subscribers/chart":
                    return self._record(uid, route, 200, {"subscribers": 0, "subscribes": [], "earnings": [],
                                                          "total": 0, "delta": 0})
                if method == "GET" and u.path == "/api2/v2/payouts/referrals/chart":
                    return self._record(uid, route, 200, {"total": 0, "delta": 0, "chartAmount": [], "chartCount": []})
                if method == "GET" and u.path == "/api2/v2/users/notifications":
                    return self._record(uid, route, 200, {"list": [], "hasMore": False})
                m = _SEND.fullmatch(u.path)
                if method == "POST" and m:
                    body = json.loads(raw or b"{}")
                    with fake.lock:
                        mid = next(fake._ids)
                        msg = {"id": mid, "text": body.get("text") or "", "price": body.get("price") or 0,
                               "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                               "fromUser": {"id": int(uid or 0)}, "mediaCount": 0, "media": [],
                               "isFree": True, "lockedText": False}
                        fake.sends.setdefault(uid, []).append({"fan_id": int(m.group(1)), "t": time.time(), **msg})
                    return self._record(uid, route, 200, msg)
                with fake.lock:
                    fake.unmodelled[route] += 1
                return self._record(uid, route, 404, {"error": {"code": 0, "message": "slop fake: not modelled"}})

            def _record(self, uid: str, route: str, status: int, body, ctype: str = "application/json") -> None:
                with fake.lock:
                    fake.calls.append({"t": time.time(), "account": uid, "route": route, "status": status})
                self._send(status, body, ctype)

            def do_GET(self):  # noqa: N802
                self._serve("GET")

            def do_POST(self):  # noqa: N802
                self._serve("POST")

            def do_PUT(self):  # noqa: N802
                self._serve("PUT")

            def do_DELETE(self):  # noqa: N802
                self._serve("DELETE")

        return H
