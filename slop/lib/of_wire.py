from __future__ import annotations

import asyncio
import json
import random
import re
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlsplit

from slop.lib.bounded_server import BoundedHTTPServer
from slop.lib.of_wire_upload import UploadWire

LATENCY_S = 0.05
OTP_BODY = {"error": {"code": 101, "message": "Confirm it is you", "payload": {
    "otpState": {"email": False, "phoneOtp": False, "appOtp": True, "faceOtp": False, "forceFaceOtp": False,
                 "phoneLast4": "", "phoneCode": {}, "faceCode": {}, "emailCode": {}},
    "strong": False}}}
FAIL_BODY = {"error": {"code": 0, "message": "slop fake: OF internal error"}}
TOO_MANY_BODY = {"error": {"code": 429, "message": "Too many requests. Please allow 1 seconds"}}
TOO_MANY_PLAIN_BODY = {"error": {"code": 429, "message": "Too many requests."}}
UNAUTH_BODY = {"error": {"code": 401, "message": "Unauthorized"}}
CONSENT_BODY = {"error": {"code": 0, "message": "Consent not accepted"}}
_SEND = re.compile(r"/api2/v2/chats/(\d+)/messages")
_VAULT_ONE = re.compile(r"/api2/v2/vault/media/(\d+)")
_QUEUE_ONE = re.compile(r"/api2/v2/messages/queue/(\d+)")
_MARK_ONE = re.compile(r"/api2/v2/chats/(\d+)/mark-as-read")
_LIST_USERS = re.compile(r"/api2/v2/lists/(\d+)/users(?:/(\d+))?")
_LIST = re.compile(r"/api2/v2/lists/(\d+)")
_NUM = re.compile(r"/\d+(?=/|$)")
_CHUNK = re.compile(r"/static/prod/f/[^/]+/2313\.js")


def unread(row: dict) -> bool:
    return bool(row.get("hasUnread")) or (row.get("unreadMessagesCount") or 0) > 0


def chat_mark_request(method: str, path: str) -> tuple[int | None, bool] | None:
    if method == "POST" and path == "/api2/v2/chats/mark-as-read":
        return None, True
    if method in ("POST", "DELETE") and (match := _MARK_ONE.fullmatch(path)):
        return int(match[1]), method == "POST"
    return None


def unread_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows if unread(row)]


def chat_page(query: dict, rows: list[dict], *, cap: int | None = None) -> dict:
    off, lim = int((query.get("offset") or ["0"])[0]), int((query.get("limit") or ["10"])[0])
    if cap is not None:
        lim = max(1, min(lim, cap))
    end = off + lim
    return {"list": rows[off:end], "hasMore": end < len(rows), "nextOffset": end}


class FakeOF:
    def mark(self, uid: str, fan: int | None, read: bool) -> bool:
        if uid not in self.chats:
            return False
        rows = list(self.chats[uid])
        changed = False
        for i, row in enumerate(rows):
            if fan is not None and row["withUser"]["id"] != fan:
                continue
            changed = changed or unread(row) == read
            rows[i] = {**row, "unreadMessagesCount": 0 if read else max(1, row.get("unreadMessagesCount") or 0),
                       "hasUnread": not read}
        self.chats[uid] = rows
        return changed

    def __init__(self, latency_s: float = LATENCY_S):
        self.latency_s = latency_s
        self.otp: set[str] = set()
        self.fail: set[tuple[str, str]] = set()
        self.throttle: dict[tuple[str, str], int] = {}
        # OF per-account rate limit; AE measured 76 unpaced by-id reads in 19 s, then 429; real budget is a guess
        self.min_gap: dict[tuple[str, str], float] = {}
        self._gap_last: dict[tuple[str, str], float] = {}
        self.status: dict[tuple[str, str], tuple] = {}
        self.consent: dict[str, str] = {}
        self.consent_signed: set[str] = set()
        self.extra_s: dict[str, float] = {}
        self.route_s: dict[str, float] = {}
        self.route_jitter = 0.0
        self._rng = random.Random(0)
        self.hold: dict[tuple[str, str], list[float]] = {}
        self.chats: dict[str, list[dict]] = {}
        self.vault_lists: dict[str, list[dict]] = {}
        self.vault_order: dict[str, list[int]] = {}
        self.vault_sorts: dict[str, list[dict]] = {}
        self.messages: dict[str, dict[int, list[dict]]] = {}
        self.vault_media: dict[str, list[dict]] = {}
        self.fan_counts: dict[str, int] = {}
        self.purchases: dict[str, list[dict]] = {}
        self.notif_counts: dict[str, dict[str, int]] = {}
        self.notif_reads: dict[str, list[tuple[float, str | None]]] = {}
        self.profiles: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.calls: list[dict] = []
        self.sends: dict[str, list[dict]] = {}
        self.queue: dict[str, list[dict]] = {}
        self.posts: dict[str, list[dict]] = {}
        self.unsends: dict[str, list[dict]] = {}
        self.sent_counts: dict[int, int] = {}
        self.vault: dict[str, dict[int, dict]] = {}
        self.campaigns: dict[str, list[dict]] = {}
        self.lists: dict[str, list[dict]] = {}
        self.list_users: dict[int, list[int]] = {}
        self.repeat_pages: set[int] = set()
        self.upload = UploadWire(self)
        self.extra_routes: list = []
        self.unmodelled: Counter = Counter()
        self.unsigned = 0
        self._ids = iter(range(9_000_000_000, 10**12))
        self._srv: BoundedHTTPServer | None = None
        self.ws_connects: list[dict] = []
        self._ws_open: dict[str, set] = {}
        self._ws_loop: asyncio.AbstractEventLoop | None = None
        self._ws_port = 0
        self._chunk: str | None = None

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self._srv.server_address[1]}"

    def __enter__(self) -> "FakeOF":
        self._srv = BoundedHTTPServer(("127.0.0.1", 0), self._handler())
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
                async for _ in ws:
                    pass
            except websockets.ConnectionClosed:
                pass
            finally:
                with fake.lock:
                    fake._ws_open.get(uid, set()).discard(ws)

        async def start():
            return await websockets.serve(session, "127.0.0.1", 0)

        loop = asyncio.new_event_loop()
        # held: the loop keeps only weak task refs
        self._ws_srv = loop.run_until_complete(start())
        self._ws_port = self._ws_srv.sockets[0].getsockname()[1]
        self._ws_loop = loop
        up.set()
        try:
            loop.run_forever()
        finally:
            loop.close()

    def _reach(self, body: dict) -> int:
        def ids(xs):
            return [int(x) for x in xs or () if str(x).strip().isdigit()]
        got = set(ids(body.get("userIds"))).union(*(self.list_users.get(i, ()) for i in ids(body.get("userLists"))))
        return len(got.difference(*(self.list_users.get(i, ()) for i in ids(body.get("excludedLists")))))

    def head_chat(self, uid: str, fan: int, msg: dict) -> None:
        rows = self.chats.setdefault(uid, [])
        old = next((c for c in rows if c["withUser"]["id"] == fan), None)
        if old is not None:
            rows.remove(old)
        last = {k: msg.get(k) for k in ("id", "text", "fromUser", "isFree", "price", "createdAt")}
        base = old or {"withUser": {"id": fan, "_view": "s"}, "unreadMessagesCount": 0, "isMutedNotifications": False}
        rows.insert(0, {**base, "lastMessage": last})

    def drop_ws(self, account_ids) -> int:
        with self.lock:
            socks = [ws for a in account_ids for ws in self._ws_open.get(str(a), ())]
        for ws in socks:
            asyncio.run_coroutine_threadsafe(ws.close(), self._ws_loop).result(10)
        return len(socks)

    def push_ws(self, account_id, frame: dict) -> int:
        with self.lock:
            socks = list(self._ws_open.get(str(account_id), ()))
        for ws in socks:
            asyncio.run_coroutine_threadsafe(ws.send(json.dumps(frame)), self._ws_loop).result(10)
        return len(socks)

    def ws_live(self) -> dict[str, int]:
        with self.lock:
            return {a: len(v) for a, v in self._ws_open.items() if v}

    def set_otp(self, account_ids) -> float:
        with self.lock:
            self.otp = {str(a) for a in account_ids}
            return time.time()

    def chunk(self) -> str:
        if self._chunk is None:
            from slop.lib.browserbase import signing
            self._chunk = signing("0", "slop-rev", 0)["chunk"]
        return self._chunk

    def snapshot(self) -> dict:
        with self.lock:
            per = Counter((c["account"], c["route"], c["status"]) for c in self.calls)
            return {"calls": len(self.calls), "unsigned": self.unsigned, "unmodelled": dict(self.unmodelled),
                    "sends": {a: len(v) for a, v in self.sends.items()},
                    "queue": {a: len(v) for a, v in self.queue.items()},
                    "posts": {a: len(v) for a, v in self.posts.items()},
                    "unsends": {a: len(v) for a, v in self.unsends.items()},
                    "ws_connects": len(self.ws_connects),
                    "by_route": {f"{a} {r} {s}": n for (a, r, s), n in sorted(per.items())}}

    def _handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_a):
                pass

            def _send(self, code: int, body, ctype: str = "application/json", headers=()) -> None:
                data = body if isinstance(body, bytes) else (
                    body.encode() if isinstance(body, str) else json.dumps(body).encode())
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                for k, v in headers:
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def _serve(self, method: str) -> None:
                self._t0 = time.time()
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                u = urlsplit(self.path)
                route = f"{method} {_NUM.sub('/{id}', u.path)}"
                if u.path.rstrip("/") == "/hash":
                    uid = (parse_qs(u.query).get("u") or [""])[0]
                    return self._record(uid, route, 200, "%040x" % (hash(uid) & (2**160 - 1)), "text/plain")
                if method == "GET" and u.path == "/robots.txt":
                    return self._record("", route, 200, "User-agent: *\nDisallow: /\n", "text/plain")
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
                with fake.lock:
                    held = fake.hold.get((uid, route))
                    slow = fake.route_s.get(route, 0.0)
                    if slow and fake.route_jitter:
                        slow *= 1 + fake._rng.uniform(-fake.route_jitter, fake.route_jitter)
                    wait = fake.latency_s + slow + (held.pop(0) if held else 0.0)
                time.sleep(wait + (fake.extra_s.get(uid, 0.0) if u.path.startswith("/api2/") else 0.0))
                with fake.lock:
                    otp = uid in fake.otp
                if u.path.startswith("/api2/") and otp:
                    return self._record(uid, route, 400, OTP_BODY)
                with fake.lock:
                    failing = (uid, route) in fake.fail
                if failing:
                    return self._record(uid, route, 500, FAIL_BODY)
                with fake.lock:
                    limited = fake.throttle.get((uid, route), 0) > 0
                    if limited:
                        fake.throttle[(uid, route)] -= 1
                if limited:
                    return self._record(uid, route, 429, TOO_MANY_BODY)
                with fake.lock:
                    gap = fake.min_gap.get((uid, route))
                    now = time.monotonic()
                    last = fake._gap_last.get((uid, route))
                    too_soon = bool(gap) and last is not None and now - last < gap
                    if gap:
                        fake._gap_last[(uid, route)] = now
                if too_soon:
                    return self._record(uid, route, 429, TOO_MANY_BODY)
                with fake.lock:
                    mode = fake.status.get((uid, route))
                if mode is not None:
                    code, ra, body = (*mode, None)[:3]
                    if body is None:
                        body = UNAUTH_BODY if code == 401 else TOO_MANY_PLAIN_BODY
                    return self._record(uid, route, code, body,
                                        headers=() if ra is None else (("Retry-After", f"{ra:g}"),))
                with fake.lock:
                    law = fake.consent.get(uid)
                    signed = uid in fake.consent_signed
                if (law and not signed and method == "POST"
                        and (u.path == "/api2/v2/messages/queue" or _SEND.fullmatch(u.path))
                        and (json.loads(raw or b"{}").get("mediaFiles"))):
                    return self._record(uid, route, 400, CONSENT_BODY)
                for extra in fake.extra_routes:
                    if extra(self, method, u, uid, route, raw):
                        return
                if method == "GET" and u.path == "/api2/v2/users/me":
                    me = {"id": int(uid or 0), "username": f"u{uid}", "name": f"Creator {uid}", "isPerformer": True,
                          "wsUrl": f"ws://127.0.0.1:{fake._ws_port}/ws3/{uid}", "wsAuthToken": f"slop-ws-{uid}"}
                    with fake.lock:
                        me |= fake.profiles.get(uid, {})
                    if law:
                        me |= {"needConsent": True, "needConsentState": law,
                               "consentStatus": "approved" if signed else None}
                    return self._record(uid, route, 200, me)
                if method == "GET" and u.path == "/api2/v2/chats":
                    q = parse_qs(u.query)
                    with fake.lock:
                        chats = list(fake.chats.get(uid, ()))
                    if q.get("filter") == ["unread"]:
                        chats = unread_rows(chats)
                    return self._record(uid, route, 200, chat_page(q, chats))
                if method == "GET" and (m := _SEND.fullmatch(u.path)) and uid not in fake.messages:
                    fan = int(m.group(1))
                    return self._record(uid, route, 200, {"list": [{
                        "id": 8_000_000 + fan % 1_000_000, "text": "hey", "fromUser": {"id": fan}, "isFree": True,
                        "price": 0, "media": [], "createdAt": "2026-11-05T10:00:00+00:00"}], "hasMore": False})
                if method == "GET" and u.path == "/api2/v2/users/notifications/count":
                    with fake.lock:
                        counts = dict(fake.notif_counts.get(uid) or {"all": 0, "subscribed": 0, "purchases": 0, "tip": 0})
                    return self._record(uid, route, 200, counts)
                if method == "POST" and u.path == "/api2/v2/users/notifications/read":
                    with fake.lock:
                        counts = dict(fake.notif_counts.get(uid) or {"all": 0, "subscribed": 0, "purchases": 0, "tip": 0})
                        counts = {k: 0 for k in counts}
                        fake.notif_counts[uid] = counts
                        fake.notif_reads.setdefault(uid, []).append((time.time(), None))
                    return self._record(uid, route, 200, {"counters": counts})
                if mark := chat_mark_request(method, u.path):
                    with fake.lock:
                        fake.mark(uid, *mark)
                    return self._record(uid, route, 200, {"success": True})
                if method == "GET" and u.path == "/api2/v2/subscriptions/count/all":
                    n = fake.fan_counts.get(uid, int(uid or 0) % 900 + 100)
                    return self._record(uid, route, 200, {"subscribers": {"active": n, "all": 2 * n, "expired": n},
                                                          "subscriptions": {"active": 0, "all": 0, "expired": 0}})
                if method == "GET" and u.path == "/api2/v2/subscriptions/subscribers/chart":
                    return self._record(uid, route, 200, {"subscribers": 0, "subscribes": [], "earnings": [],
                                                          "total": 0, "delta": 0})
                if method == "GET" and u.path == "/api2/v2/payouts/referrals/chart":
                    return self._record(uid, route, 200, {"total": 0, "delta": 0, "chartAmount": [], "chartCount": []})
                if method == "GET" and u.path == "/api2/v2/users/notifications":
                    q = parse_qs(u.query)
                    if (q.get("type") or [""])[0] != "purchases":
                        return self._record(uid, route, 200, {"list": [], "hasMore": False})
                    off, lim = int((q.get("offset") or ["0"])[0]), int((q.get("limit") or ["10"])[0])
                    with fake.lock:
                        feed = list(fake.purchases.get(uid, ()))
                    return self._record(uid, route, 200, {"list": feed[off:off + lim], "hasMore": off + lim < len(feed)})
                if method == "GET" and u.path == "/api2/v2/payouts/transactions":
                    return self._record(uid, route, 200, {"list": [], "hasMore": False})
                if method == "GET" and u.path == "/api2/v2/campaigns":
                    q = parse_qs(u.query)
                    with fake.lock:
                        rows = list(fake.campaigns.get(uid, ()))
                    if "with_deleted" not in q:
                        rows = [r for r in rows if not r.get("isDeleted")]
                    off, lim = int(q.get("offset", ["0"])[0]), int(q.get("limit", ["10"])[0])
                    return self._record(uid, route, 200, {"list": rows[off:off + lim], "hasMore": off + lim < len(rows)})
                if method == "GET" and u.path == "/api2/v2/vault/lists":
                    q = parse_qs(u.query)
                    off, lim = int((q.get("offset") or ["0"])[0]), int((q.get("limit") or ["10"])[0])
                    with fake.lock:
                        lists = list(fake.vault_lists.get(uid, ()))
                        rank = {fid: k for k, fid in enumerate(fake.vault_order.get(uid, ()))}
                    lists.sort(key=lambda f: rank.get(f["id"], len(rank)))
                    return self._record(uid, route, 200, {"list": lists[off:off + lim], "hasMore": off + lim < len(lists)})
                if method == "POST" and u.path == "/api2/v2/vault/lists/sort":
                    body = json.loads(raw or b"{}")
                    with fake.lock:
                        fake.vault_sorts.setdefault(uid, []).append({"t": time.time(), "body": body})
                        if body.get("sort") == "custom" and isinstance(body.get("customOrder"), list):
                            fake.vault_order[uid] = [int(x) for x in body["customOrder"]]
                    return self._record(uid, route, 200, {"success": True})
                if method == "GET" and u.path == "/api2/v2/vault/media":
                    q = parse_qs(u.query)
                    off, lim = int((q.get("offset") or ["0"])[0]), int((q.get("limit") or ["24"])[0])
                    with fake.lock:
                        media = list(fake.vault_media.get(uid, ()))
                    page = {"list": media[off:off + lim], "hasMore": off + lim < len(media)}
                    return self._record(uid, route, 200, page)
                if method == "GET" and u.path == "/api2/v2/promotions":
                    return self._record(uid, route, 200, {"list": [], "hasMore": False})
                if method == "GET" and (u.path == "/api2/v2/posts" or re.fullmatch(r"/api2/v2/users/\d+/posts", u.path)):
                    return self._record(uid, route, 200, {"list": [], "hasMore": False})
                if method == "GET" and u.path in ("/api2/v2/subscriptions/subscribers",
                                                  "/api2/v2/subscriptions/subscribes"):
                    return self._record(uid, route, 200, {"list": [], "hasMore": False})
                vm = _VAULT_ONE.fullmatch(u.path)
                if method == "GET" and vm:
                    with fake.lock:
                        media = fake.vault.get(uid, {}).get(int(vm.group(1)))
                    if media is None:
                        return self._record(uid, route, 404, {"error": {"code": 0, "message": "Media Not Found"}})
                    return self._record(uid, route, 200, media)
                if method == "GET" and u.path == "/api2/v2/trials":
                    return self._record(uid, route, 200, [])
                if u.path == "/api2/v2/lists" and method in ("GET", "POST"):
                    q = parse_qs(u.query)
                    off, lim = int((q.get("offset") or ["0"])[0]), int((q.get("limit") or ["10"])[0])
                    with fake.lock:  # _record takes it too: answer after it is released
                        mine = fake.lists.setdefault(uid, [])
                        if method == "POST":
                            lst = {"id": next(fake._ids), "type": "custom",
                                   "name": json.loads(raw or b"{}").get("name") or "", "usersCount": 0}
                            mine.append(lst)
                            fake.list_users[lst["id"]] = []
                            ans = dict(lst)
                        else:
                            ans = {"list": [{**x, "usersCount": len(fake.list_users[x["id"]])}
                                            for x in mine[off:off + lim]], "hasMore": off + lim < len(mine)}
                    return self._record(uid, route, 200, ans)
                if method == "GET" and (lg := _LIST.fullmatch(u.path)):
                    lid = int(lg.group(1))
                    with fake.lock:  # _record takes it too: answer after it is released
                        meta = next(({**x, "usersCount": len(fake.list_users.get(lid, ()))}
                                     for x in fake.lists.get(uid, ()) if x["id"] == lid), None)
                    if meta is None:
                        return self._record(uid, route, 404, {"error": {"code": 0, "message": "List not found"}})
                    return self._record(uid, route, 200, meta)
                lm = _LIST_USERS.fullmatch(u.path)
                if lm:
                    lid = int(lm.group(1))
                    with fake.lock:
                        members = (fake.list_users.get(lid)
                                   if any(x["id"] == lid for x in fake.lists.get(uid, ())) else None)
                        if members is not None and method == "GET" and not lm.group(2):
                            q = parse_qs(u.query)
                            off, lim = int((q.get("offset") or ["0"])[0]), int((q.get("limit") or ["10"])[0])
                            off = 0 if lid in fake.repeat_pages else off
                            page = [{"id": i} for i in members[off:off + lim]]
                        elif members is not None and lm.group(2) and method in ("POST", "DELETE"):
                            fan = int(lm.group(2))
                            if method == "POST" and fan not in members:
                                members.append(fan)
                            elif method == "DELETE" and fan in members:
                                members.remove(fan)
                            page = {"success": True}
                        else:
                            page = None
                    if page is not None:
                        return self._record(uid, route, 200, page)
                    if members is None:
                        return self._record(uid, route, 404, {"error": {"code": 0, "message": "List not found"}})
                if method == "POST" and u.path in ("/api2/v2/messages/queue", "/api2/v2/posts"):
                    body = json.loads(raw or b"{}")
                    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
                    queue = u.path.endswith("/queue")
                    with fake.lock:
                        mid = next(fake._ids)
                        (fake.queue if queue else fake.posts).setdefault(uid, []).append(
                            {"t": time.time(), "id": mid, **body})
                        if queue:
                            fake.sent_counts[mid] = fake._reach(body)
                    return self._record(uid, route, 200, {"id": mid, "text": body.get("text") or "",
                                                          ("createdAt" if queue else "postedAt"): now})
                if method == "GET" and u.path == "/api2/v2/users/me/stats/messages/group":
                    lim = int((parse_qs(u.query).get("limit") or ["10"])[0])
                    with fake.lock:
                        items = [{"id": e["id"], "text": e.get("text") or "", "template": "group",
                                  "sentCount": fake.sent_counts.get(e["id"], 0),
                                  "date": datetime.fromtimestamp(e["t"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")}
                                 for e in reversed(fake.queue.get(uid, ()))]
                    return self._record(uid, route, 200, {"items": items[:lim], "hasMore": len(items) > lim})
                qm = _QUEUE_ONE.fullmatch(u.path)
                if method == "DELETE" and qm:
                    with fake.lock:
                        fake.unsends.setdefault(uid, []).append({"t": time.time(), "id": int(qm.group(1))})
                    return self._record(uid, route, 200, {"success": True})
                m = _SEND.fullmatch(u.path)
                if method == "GET" and m and uid in fake.messages:
                    q = parse_qs(u.query)
                    lim, before = int((q.get("limit") or ["10"])[0]), (q.get("id") or [None])[0]
                    with fake.lock:
                        rows = list(fake.messages.get(uid, {}).get(int(m.group(1)), ()))
                    if before is not None:
                        rows = [x for x in rows if int(x["id"]) < int(before)]
                    return self._record(uid, route, 200, {"list": rows[:lim], "hasMore": len(rows) > lim})
                if method == "POST" and m:
                    body = json.loads(raw or b"{}")
                    with fake.lock:
                        mid = next(fake._ids)
                        msg = {"id": mid, "text": body.get("text") or "", "price": body.get("price") or 0,
                               "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                               "fromUser": {"id": int(uid or 0)}, "mediaCount": 0, "media": [],
                               "isFree": True, "lockedText": False}
                        fake.sends.setdefault(uid, []).append({"fan_id": int(m.group(1)), "t": time.time(), **msg,
                                                               "body": body})
                        if uid in fake.messages:
                            fake.messages[uid].setdefault(int(m.group(1)), []).insert(0, msg)
                            fake.head_chat(uid, int(m.group(1)), msg)
                    return self._record(uid, route, 200, msg)
                if fake.upload.handle(self, method, u, uid, route, raw):
                    return
                with fake.lock:
                    fake.unmodelled[route] += 1
                return self._record(uid, route, 404, {"error": {"code": 0, "message": "slop fake: not modelled"}})

            def _record(self, uid: str, route: str, status: int, body, ctype: str = "application/json",
                        headers=()) -> None:
                with fake.lock:
                    fake.calls.append({"t0": getattr(self, "_t0", None), "t": time.time(), "account": uid,
                                       "route": route, "path": urlsplit(self.path).path,
                                       "query": urlsplit(self.path).query, "status": status,
                                       "cookie": bool(self.headers.get("Cookie"))})
                self._send(status, body, ctype, headers)

            def do_GET(self):  # noqa: N802
                self._serve("GET")

            def do_POST(self):  # noqa: N802
                self._serve("POST")

            def do_PUT(self):  # noqa: N802
                self._serve("PUT")

            def do_DELETE(self):  # noqa: N802
                self._serve("DELETE")

        return H
