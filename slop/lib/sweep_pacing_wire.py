from __future__ import annotations

import calendar
import re
import threading
import time
from datetime import datetime
from functools import lru_cache
from urllib.parse import parse_qs, urlsplit

from slop.lib.proxy_wire import egress_of

# The token bucket is a GUESS at OF's policy (OF publishes none; prod 429s say real OF is laxer).
BURST = 10
# OF's ledger: `offset` >= 600 is empty, hasMore false (measured).
TX_CAP = 600
# whatever `limit` asks (measured).
TX_PAGE_MAX = 100
REFILL_PER_S = 2.0
TOO_MANY = "Too many requests. Please allow 1 seconds"
ROUTES = {"/api2/v2/promotions": "promotions", "/api2/v2/subscriptions/subscribers": "subscribers",
          "/api2/v2/payouts/transactions": "transactions", "/api2/v2/users/list": "users_list"}
LOGGED = {"/api2/v2/campaigns": "campaigns", "/api2/v2/trials": "trials"}
CHARGEBACKS = "/api2/v2/payouts/chargebacks"
LIST_ADD = re.compile(r"/api2/v2/lists/(\d+)/users/(?:(trial|promo)/(\d+)/claims|(campaign)/(\d+)/claimers)")


@lru_cache(maxsize=100_000)
def _epoch(created_at: str) -> int:
    return calendar.timegm(datetime.fromisoformat(created_at.replace("Z", "+00:00")).utctimetuple())


def _page(query: dict) -> tuple[int, int]:
    return int((query.get("offset") or ["0"])[0]), int((query.get("limit") or ["10"])[0])


def body_429(text: str = TOO_MANY) -> dict:
    return {"error": {"code": 429, "message": text}}


class SweepWire:
    def __init__(self, fake, *, burst: int = BURST, refill_per_s: float = REFILL_PER_S):
        self.fake, self.burst, self.refill_per_s = fake, burst, refill_per_s
        self.promos: dict[str, list[dict]] = {}
        self.subs: dict[str, list[dict]] = {}
        self.txs: dict[str, list[dict]] = {}
        self.disputes: dict[str, list[dict]] = {}
        self.inject: dict[tuple[str, str], dict] = {}
        self.claims: dict[tuple[str, int], list[dict]] = {}
        self.window = True
        self.startdate_iso = False
        self.honest: set[str] = set()
        self.share: dict[str, str] = {}
        self.depth: dict[str, int] = {}
        self.log: list[dict] = []
        self._bucket: dict[str, tuple[float, float]] = {}
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
                    q = parse_qs(urlsplit(self.path).query)
                    off, lim = _page(q)
                    return self._record(uid, f"GET {path}", 200, {"list": sw.disputes.get(uid, [])[off:off + lim],
                                                                  "marker": int(time.time())})
                lm = LIST_ADD.fullmatch(path) if method == "POST" else None
                if lm:
                    uid = self.headers.get("User-ID") or ""
                    kind, link = (lm.group(2), int(lm.group(3))) if lm.group(2) else (lm.group(4), int(lm.group(5)))
                    n = len(sw.claims.get((uid, link), ()))
                    with sw._lock:
                        sw.log.append({"t": time.time(), "account": uid, "route": "list_add", "query": "",
                                       "offset": None, "view": None, "status": 200, "asked": None,
                                       "list": lm.group(1), "kind": kind, "link": link, "count": n})
                    return self._record(uid, f"POST {path}", 200, {"count": n})
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
        off, lim = _page(q)
        view = "m" if "m[]" in q else "x" if "x[]" in q else None
        now = time.time()
        with self._lock:
            if not all(h.headers.get(x) for x in ("Sign", "Time", "X-Hash")):
                with self.fake.lock:
                    self.fake.unsigned += 1
            key = self.share.get(uid, uid)
            depth = float(self.depth.get(key, self.burst))
            tokens, at = self._bucket.get(key, (depth, now))
            tokens = min(depth, tokens + (now - at) * self.refill_per_s)
            inj = self.inject.get((uid, name))
            text, blank = None, False
            fire = (inj and not inj.get("done") and inj["offset"] == off and inj.get("view") in (None, view)
                    and not any(k.startswith("filter[") for k in q)
                    and (not inj.get("marker") or "marker" in q)
                    and (not inj.get("full") or "startDate" not in q))
            if fire and inj.get("skip"):
                inj["skip"] -= 1
                fire = False
            if fire and not inj.get("empty"):
                inj["fired"] = inj.get("fired", 0) + 1
                inj["done"], text = inj["fired"] >= inj.get("times", 1), inj["text"]
            elif tokens < 1.0:
                text = TOO_MANY
            else:
                tokens -= 1.0
                if fire:
                    inj["done"], blank = True, True
            self._bucket[key] = (tokens, now)
            entry = {"t": now, "account": uid, "route": name, "query": u.query, "offset": off, "view": view,
                     "status": 429 if text else 200, "asked": text, "tokens": round(tokens, 2),
                     "egress": egress_of(h.client_address[1])}
            self.log.append(entry)
        time.sleep(self.fake.latency_s)
        if text:
            return h._record(uid, route, 429, body_429(text))
        if blank:
            return h._record(uid, route, 200, {"list": [], "hasMore": False})
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
            sd = (q.get("startDate") or [None])[0] if self.window or uid in self.honest else None
            if sd and self.startdate_iso and len(sd) == 10 and uid not in self.honest:
                sd += "T00:00:00.000Z"
            # an ISO datetime startDate: OF answers an empty list (measured)
            if sd and len(sd) != 10:
                return {"list": [], "hasMore": False}
            mark = (q.get("marker") or [None])[0]
            if off >= TX_CAP:
                return {"list": [], "hasMore": False, "marker": mark}
            lim = min(lim, TX_PAGE_MAX)
            rows = [r for r in self.txs.get(uid, []) if (not sd or r["createdAt"][:10] >= sd)
                    and (mark is None or _epoch(r["createdAt"]) <= int(mark))]
            more = off + lim < len(rows)
            return {"list": rows[off:off + lim], "hasMore": more, "marker": mark,
                    "nextMarker": _epoch(rows[off + lim]["createdAt"]) if more else None}
        ids = q.get("m[]") or q.get("x[]") or []
        return {str(i): {"id": int(i), "name": f"Fan {i}", "username": f"u{i}"} for i in ids}

    def add_tx(self, uid: str, row: dict) -> None:
        with self._lock:
            self.txs[uid] = sorted([*self.txs.get(uid, []), row], key=lambda r: r["createdAt"], reverse=True)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [dict(e) for e in self.log]
