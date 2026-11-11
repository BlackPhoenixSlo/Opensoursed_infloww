"""OnlyFans' rosters for the mass-audience-crawl flow (scenarios/2026-11-08-mass-audience-crawl.py), on
lib/of_wire.py's server: an `extra_routes` handler in the harness process (as lib/vault_wire.py), answering
through of_wire's own `_record` (its `headers=` carries Retry-After). For the Creators it is given:

  GET  /api2/v2/subscriptions/subscribers   the fans roster `fans[uid]` (sorted ids), `offset` / `limit`,
  GET  /api2/v2/subscriptions/subscribes    the following roster `following[uid]`; `{list: [{id}], hasMore}`
       * a Dead-session Creator (`dead`): every call 401 with OF's body (the session died after the send)
       * the 429 schedule: per Creator a seeded RNG (`seed`, Creator); a roster call outside an open
         window opens one with probability `p429`: it and every roster call of that Creator for the next
         `retry_after_s` are answered 429 with `Retry-After: <s left>` and OF's "Please allow N seconds"
         body. A caller that waits what OF asks gets the page; one that retries sooner gets 429 again.
       * churn (`churn` Creators): each 429 answered subscribes one new fan (an id past the roster's top)
         and expires one seeded member, so a crawl that backs off reads a roster that moved (`drift`).
       * tail repeat (`tail_repeat` Creators, fans only): hasMore is always true and a page at or past the
         end serves the roster's last `limit` rows again: a page repeated twice in a row, for the crawl's
         repeat rule (re-read once, then NULL `truncated`). Synthetic, not a measured AE shape (Creator
         41182778's one repeat, ~offset 2450, was mid-roster, #440).
       * short rosters (`short[uid] = x`): both rosters end (hasMore false) after their first ceil(n / x)
         rows; OF still sends to (and counts) the whole roster (AE 11-11: partial Creators read <= 0.88).
  GET  /api2/v2/users/me/stats/messages/group   the mass feed: the Creator's queued sends (of_wire's
       `queue`), newest first, `limit` of them, each `{id, date, text, sentCount, template}`, sentCount
       its `accepts` truth (matched by text); an `unlisted` Creator's feed leaves its sends out (as a send
       past OF's newest page). Dead: 401. Never 429'd. `feeds` journals each {t, account, status, items}.
  POST /api2/v2/messages/queue   journalled, then left to of_wire (which keeps and answers it): `accepts`
       gets {t, account, text, truth, excluded_lists}: OF's recipients at that moment, (the userLists' rosters
       | userIds) minus the members of every `excludedLists` list (of_wire's `list_users`: the Auto_Exclude
       sync's); `excluded_lists` those list ids.

`pages`: every roster call {t0, t, account, route, offset, limit, status}. Lists (`/lists/{id}/users`, the
Auto_Exclude list a send excludes) stay of_wire's own bare pages, never 429'd (a 429 there would fail the
send's own exclude sync, not the crawl).
Bypass, declared: OF's rate limit is a seeded schedule, not OF's policy (a guess); the Retry-After header and
the body's wording are guesses at OF's form (of_pacing reads the body's "allow N seconds"); OF's roster pages
are `{list, hasMore}` as of_wire's empty ones; the tail repeat is synthetic (where OF repeats is unmeasured); the
short roster's cut is a guess at where OF stops; the feed's sentCount is final the moment OF accepts (AE 11-11:
final-looking counts at 64 s and 369 s, n=3; an undercount mid-delivery is not modelled) and the feed is not
rate limited (a guess).
"""
from __future__ import annotations

import json
import math
import random
import threading
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs

ROSTERS = {"/api2/v2/subscriptions/subscribers": "fans", "/api2/v2/subscriptions/subscribes": "following"}
FEED = "/api2/v2/users/me/stats/messages/group"
DEAD_BODY = {"error": {"code": 401, "message": "Unauthorized"}}


def _too_many(s: int) -> dict:
    return {"error": {"code": 429, "message": f"Too many requests. Please allow {s} seconds"}}


class AudienceWire:
    def __init__(self, fake, *, seed, fans: dict[str, list[int]], following: dict[str, list[int]],
                 p429: float, retry_after_s: int, dead=(), churn=(), tail_repeat=(), short=None, unlisted=()):
        self.fake = fake
        self.fans = {a: sorted(v) for a, v in fans.items()}
        self.following = {a: sorted(v) for a, v in following.items()}
        self.p429, self.retry_after_s = float(p429), int(retry_after_s)
        self.dead, self.churn, self.tail_repeat = set(dead), set(churn), set(tail_repeat)
        self.short, self.unlisted = dict(short or {}), set(unlisted)
        self._rng = {a: random.Random(f"{seed}:audience-wire:{a}") for a in self.fans}
        self._until: dict[str, float] = {}     # Creator -> its open 429 window's end (monotonic)
        self.lock = threading.Lock()
        self.pages: list[dict] = []
        self.accepts: list[dict] = []
        self.feeds: list[dict] = []
        self.churned: dict[str, int] = {}
        fake.extra_routes.insert(0, self.route)

    # ── the handler (of_wire's extra_routes: fn(h, method, u, uid, route, raw) -> True when answered) ──
    def route(self, h, method, u, uid, route, raw) -> bool:
        if method == "POST" and u.path == "/api2/v2/messages/queue" and uid in self.fans:
            self._accept(uid, json.loads(raw or b"{}"))
            return False                       # of_wire keeps and answers it
        if method == "GET" and u.path == FEED and uid in self.fans:
            return self._feed(h, uid, route, parse_qs(u.query))
        src = ROSTERS.get(u.path)
        if method != "GET" or src is None or uid not in self.fans:
            return False
        q = parse_qs(u.query)
        off, lim = int((q.get("offset") or ["0"])[0]), int((q.get("limit") or ["10"])[0])
        now = time.monotonic()
        headers = ()
        with self.lock:
            if uid in self.dead:
                status, body = 401, DEAD_BODY
            else:
                left = self._until.get(uid, 0.0) - now
                if left <= 0 and self._rng[uid].random() < self.p429:
                    self._until[uid] = now + self.retry_after_s
                    left = float(self.retry_after_s)
                if left > 0:
                    s = max(1, math.ceil(left))
                    status, body, headers = 429, _too_many(s), (("Retry-After", str(s)),)
                    if uid in self.churn:
                        self._churn(uid)
                else:
                    ids = (self.fans if src == "fans" else self.following)[uid]
                    if uid in self.short:
                        ids = ids[:math.ceil(len(ids) / self.short[uid])]
                    status = 200
                    if src == "fans" and uid in self.tail_repeat:
                        at = off if off < len(ids) else max(0, len(ids) - lim)
                        body = {"list": [{"id": i} for i in ids[at:at + lim]], "hasMore": True}
                    else:
                        body = {"list": [{"id": i} for i in ids[off:off + lim]], "hasMore": off + lim < len(ids)}
            self.pages.append({"t0": getattr(h, "_t0", None), "t": time.time(), "account": uid, "route": route,
                               "offset": off, "limit": lim, "status": status})
        h._record(uid, route, status, body, headers=headers)
        return True

    def _feed(self, h, uid: str, route: str, q: dict) -> bool:
        lim = int((q.get("limit") or ["10"])[0])
        if uid in self.dead:
            status, body = 401, DEAD_BODY
        else:
            with self.fake.lock:
                sent = list(self.fake.queue.get(uid, ()))
            with self.lock:
                truth = {a["text"]: len(a["truth"]) for a in self.accepts if a["account"] == uid}
            items = [] if uid in self.unlisted else [
                {"id": e["id"], "text": e.get("text") or "", "template": "group",
                 "sentCount": truth.get(e.get("text") or "", 0),
                 "date": datetime.fromtimestamp(e["t"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")}
                for e in reversed(sent)]
            status, body = 200, {"items": items[:lim], "hasMore": len(items) > lim}
        with self.lock:
            self.feeds.append({"t": time.time(), "account": uid, "status": status,
                               "items": [{"id": i["id"], "sentCount": i["sentCount"]} for i in body.get("items", ())]})
        h._record(uid, route, status, body)
        return True

    def _churn(self, uid: str) -> None:
        """One subscribe (a new id past the top) and one expire (a seeded member), under self.lock."""
        ids = self.fans[uid]
        rng = self._rng[uid]
        gone = ids.pop(rng.randrange(len(ids)))
        ids.append(max([gone, *ids]) + 1)
        self.churned[uid] = self.churned.get(uid, 0) + 1

    def _accept(self, uid: str, body: dict) -> None:
        with self.lock:
            base: set[int] = {int(x) for x in body.get("userIds") or ()}
            for name in body.get("userLists") or ():
                n = str(name).strip().lower()
                if n == "fans":
                    base |= set(self.fans[uid])
                elif n == "following":
                    base |= set(self.following[uid])
        with self.fake.lock:
            for lid in body.get("excludedLists") or ():
                base -= set(self.fake.list_users.get(int(lid), ()))
        with self.lock:
            self.accepts.append({"t": time.time(), "account": uid, "text": body.get("text") or "",
                                 "truth": sorted(base),
                                 "excluded_lists": [int(x) for x in body.get("excludedLists") or ()]})

    def snapshot(self) -> dict:
        with self.lock:
            return {"pages": list(self.pages), "accepts": list(self.accepts), "feeds": list(self.feeds),
                    "churned": dict(self.churned)}
