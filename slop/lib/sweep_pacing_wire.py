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
  GET /api2/v2/payouts/transactions      `txs[uid]` rows, newest first, `offset` / `limit`,
                                         `hasMore`, as OF answered on 2026-11-07 (measured, acct
                                         532022545): `start` / `end` ignored; `startDate`
                                         YYYY-MM-DD -> createdAt's date >= it (UTC here; OF's
                                         day-boundary TZ is unknown); an ISO `startDate` -> an
                                         empty list, hasMore false; `offset` pages it. At most
                                         `tx_cap` (TX_CAP, 600) rows, the latest, hasMore false
                                         there: INFERRED from prod offset-paged walks (6 pages
                                         then hasMore false), not probed. `add_tx` appends a row
                                         mid-run. `window = False` (fault
                                         tx-recent-window-ignored): OF ignores `startDate` too;
                                         `startdate_iso = True` (fault tx-recent-startdate-iso):
                                         a date-only startDate is read as the ISO datetime of
                                         that midnight, as if the product sent one (-> empty)
  GET /api2/v2/users/list                `{"<id>": {id, name, username}}` for every `m[]` / `x[]`
                                         id asked (the view is recorded)
  GET /api2/v2/payouts/chargebacks       `{"list": [], "marker": <epoch s>}`: no disputes (what a
                                         completed refresh walk polls, service/transaction_chargebacks);
                                         outside the bucket (a GUESS), logged as route `chargebacks`

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
from urllib.parse import parse_qs, urlsplit

BURST = 10
TX_CAP = 600   # OF's ledger answers the latest 600 rows, whatever the window (INFERRED: prod walks, 11-07)
REFILL_PER_S = 2.0
TOO_MANY = "Too many requests. Please allow 1 seconds"
ROUTES = {"/api2/v2/promotions": "promotions", "/api2/v2/subscriptions/subscribers": "subscribers",
          "/api2/v2/payouts/transactions": "transactions", "/api2/v2/users/list": "users_list"}
LOGGED = {"/api2/v2/campaigns": "campaigns", "/api2/v2/trials": "trials"}  # of_wire answers; arrival logged
CHARGEBACKS = "/api2/v2/payouts/chargebacks"


def body_429(text: str = TOO_MANY) -> dict:
    return {"error": {"code": 429, "message": text}}


class SweepWire:
    def __init__(self, fake, *, burst: int = BURST, refill_per_s: float = REFILL_PER_S):
        self.fake, self.burst, self.refill_per_s = fake, burst, refill_per_s
        self.promos: dict[str, list[dict]] = {}
        self.subs: dict[str, list[dict]] = {}
        self.txs: dict[str, list[dict]] = {}   # newest first
        self.inject: dict[tuple[str, str], dict] = {}
        self.claims: dict[tuple[str, int], list[dict]] = {}
        self.window = True                     # honour transactions' startDate
        self.tx_cap = TX_CAP
        self.startdate_iso = False             # read a date-only startDate as ISO (OF: empty)
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
                if method == "GET" and path == CHARGEBACKS:
                    uid = self.headers.get("User-ID") or ""
                    sw._arrive(uid, "chargebacks", urlsplit(self.path).query, status=200)
                    return self._record(uid, f"GET {path}", 200, {"list": [], "marker": int(time.time())})
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

    def _arrive(self, uid: str, name: str, query: str, status: int | None = None) -> None:
        with self._lock:
            self.log.append({"t": time.time(), "account": uid, "route": name, "query": query, "offset": None,
                             "view": None, "status": status, "asked": None})

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
            sd = (q.get("startDate") or [None])[0] if self.window else None
            if sd and self.startdate_iso and len(sd) == 10:
                sd += "T00:00:00.000Z"
            if sd and len(sd) != 10:   # an ISO datetime: OF answers nothing
                return {"list": [], "hasMore": False}
            rows = [r for r in self.txs.get(uid, []) if not sd or r["createdAt"][:10] >= sd][:self.tx_cap]
            return {"list": rows[off:off + lim], "hasMore": off + lim < len(rows)}
        ids = q.get("m[]") or q.get("x[]") or []
        return {str(i): {"id": int(i), "name": f"Fan {i}", "username": f"u{i}"} for i in ids}

    def add_tx(self, uid: str, row: dict) -> None:
        """A ledger row lands on OF mid-run (kept newest first)."""
        with self._lock:   # a new list: a page being served keeps the one it read
            self.txs[uid] = sorted([*self.txs.get(uid, []), row], key=lambda r: r["createdAt"], reverse=True)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [dict(e) for e in self.log]
