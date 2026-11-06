"""OnlyFans' paged lists and its rate limit, on lib/of_wire.py's loopback server, for
scenarios/2026-11-05-sweep-pacing.py. A scenario arms it (`SweepWire(ctx.of_wire).install()`);
of_wire.py itself is not edited: `install` swaps the server's handler class for a subclass
that answers the four routes below and hands every other request to of_wire's own handler.

  GET /api2/v2/promotions                `{"hasMore": true, "items": [...]}` from `promos[uid]`,
                                         `offset` / `limit` (OF's hasMore is always true; the
                                         product stops on a short page)
  GET /api2/v2/subscriptions/subscribers `{"list": [...], "hasMore": bool}` from `subs[uid]`;
                                         a promotion's claimers read (`filter[promoId]=id`)
                                         pages `claims[(uid, id)]`, any other filter is empty
  GET /api2/v2/payouts/transactions      `txs[uid]` rows with createdAt in [start, end], newest
                                         first, `offset` / `limit`, `hasMore`
  GET /api2/v2/users/list                `{"<id>": {id, name, username}}` for every `m[]` / `x[]`
                                         id asked (the view is recorded)

OF's limit: a GUESS at OF's real policy (declared bypass; OF publishes none and it was never
measured): a token bucket per Creator across these four routes, BURST (10)
requests deep, refilled REFILL_PER_S (2) a second. A request finding no whole token is answered 429
with OF's body `{"error":{"code":429,"message":"Too many requests. Please allow 1 seconds"}}` and
takes none. So a page's own burst fits (a person's lookup + the Fan List's 8-batch name fill = 9),
a walk at the pacer's ~1 page/s never drains it, and back-to-back pages (50 ms each) drain it within
a second. Not measured against OF (prod: 148 /users/list 429s in 18 h over far more name fills, so
real OF is laxer than "1 a second"). `inject[(uid, route)] = {"offset": n, "text": msg}` answers the
first request for that page (and `view`, when given; an unfiltered one) 429 with `msg`, whatever
the limit says (OF's 429s are not only bursts); `"times": k` answers its first k requests so
(default 1). GET /campaigns and /trials stay of_wire's; their
arrivals are logged too (status None), not limited. Every request is kept in `log`, arrival order: {t, account, route, query (the
raw query string), offset, view, status}.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

BURST = 10
REFILL_PER_S = 2.0
TOO_MANY = "Too many requests. Please allow 1 seconds"
ROUTES = {"/api2/v2/promotions": "promotions", "/api2/v2/subscriptions/subscribers": "subscribers",
          "/api2/v2/payouts/transactions": "transactions", "/api2/v2/users/list": "users_list"}
LOGGED = {"/api2/v2/campaigns": "campaigns", "/api2/v2/trials": "trials"}  # of_wire answers; arrival logged


def body_429(text: str = TOO_MANY) -> dict:
    return {"error": {"code": 429, "message": text}}


def _naive(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


class SweepWire:
    def __init__(self, fake, *, burst: int = BURST, refill_per_s: float = REFILL_PER_S):
        self.fake, self.burst, self.refill_per_s = fake, burst, refill_per_s
        self.promos: dict[str, list[dict]] = {}
        self.subs: dict[str, list[dict]] = {}
        self.txs: dict[str, list[dict]] = {}   # newest first
        self.inject: dict[tuple[str, str], dict] = {}
        self.claims: dict[tuple[str, int], list[dict]] = {}
        self.log: list[dict] = []
        self._bucket: dict[str, tuple[float, float]] = {}   # Creator -> (tokens, at)
        self._lock = threading.Lock()

    def install(self) -> "SweepWire":
        base, sw = self.fake._srv.RequestHandlerClass, self

        class H(base):
            def _serve(self, method: str) -> None:
                path = urlsplit(self.path).path
                if method == "GET" and path in ROUTES:
                    return sw._serve(self)
                if method == "GET" and path in LOGGED:
                    sw._arrive(self.headers.get("User-ID") or "", LOGGED[path], urlsplit(self.path).query)
                return super()._serve(method)

        self.fake._srv.RequestHandlerClass = H
        return self

    def _serve(self, h) -> None:
        u = urlsplit(h.path)
        q = parse_qs(u.query)
        uid = h.headers.get("User-ID") or ""
        name = ROUTES[u.path]
        route = f"GET {u.path}"
        off, lim = int((q.get("offset") or ["0"])[0]), int((q.get("limit") or ["10"])[0])
        view = "m" if "m[]" in q else "x" if "x[]" in q else None
        now = time.time()
        with self._lock:
            if not all(h.headers.get(x) for x in ("Sign", "Time", "X-Hash")):
                with self.fake.lock:
                    self.fake.unsigned += 1
            tokens, at = self._bucket.get(uid, (float(self.burst), now))
            tokens = min(float(self.burst), tokens + (now - at) * self.refill_per_s)
            inj = self.inject.get((uid, name))
            text = None
            if (inj and not inj.get("done") and inj["offset"] == off and inj.get("view") in (None, view)
                    and not any(k.startswith("filter[") for k in q)):
                inj["fired"] = inj.get("fired", 0) + 1
                inj["done"], text = inj["fired"] >= inj.get("times", 1), inj["text"]
            elif tokens < 1.0:
                text = TOO_MANY
            else:
                tokens -= 1.0
            self._bucket[uid] = (tokens, now)
            entry = {"t": now, "account": uid, "route": name, "query": u.query, "offset": off, "view": view,
                     "status": 429 if text else 200, "asked": text, "tokens": round(tokens, 2)}
            self.log.append(entry)
        time.sleep(self.fake.latency_s)
        if text:
            return h._record(uid, route, 429, body_429(text))
        return h._record(uid, route, 200, self._page(uid, name, q, off, lim))

    def _arrive(self, uid: str, name: str, query: str) -> None:
        with self._lock:
            self.log.append({"t": time.time(), "account": uid, "route": name, "query": query, "offset": None,
                             "view": None, "status": None, "asked": None})

    def _page(self, uid: str, name: str, q: dict, off: int, lim: int):
        if name == "promotions":
            return {"hasMore": True, "items": self.promos.get(uid, [])[off:off + lim]}
        if name == "subscribers":
            if any(k.startswith("filter[") for k in q):
                pid = (q.get("filter[promoId]") or [None])[0]
                rows = self.claims.get((uid, int(pid)), []) if pid else []
                return {"list": rows[off:off + lim], "hasMore": off + lim < len(rows)}
            rows = self.subs.get(uid, [])
            return {"list": rows[off:off + lim], "hasMore": off + lim < len(rows)}
        if name == "transactions":
            lo, hi = _naive((q.get("start") or [None])[0]), _naive((q.get("end") or [None])[0])
            rows = [r for r in self.txs.get(uid, [])
                    if (a := _naive(r["createdAt"])) is not None and (lo is None or a >= lo) and (hi is None or a <= hi)]
            return {"list": rows[off:off + lim], "hasMore": off + lim < len(rows)}
        ids = q.get("m[]") or q.get("x[]") or []
        return {str(i): {"id": int(i), "name": f"Fan {i}", "username": f"u{i}"} for i in ids}

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [dict(e) for e in self.log]
