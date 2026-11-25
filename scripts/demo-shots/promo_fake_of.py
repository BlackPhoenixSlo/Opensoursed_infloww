from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

FMT = "%Y-%m-%dT%H:%M:%S+00:00"


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


@dataclass
class Promo:
    id: int
    cap: int
    claims: int
    created: datetime
    message: str = ""
    type: object = "all"
    days: int = 30
    finished_at: datetime | None = None
    finished: bool = False
    listed: bool = True

    def live(self) -> bool:
        return not self.finished and not (self.finished_at and self.finished_at <= utcnow())

    def item(self, claims: int | None = None) -> dict:
        d = {"id": self.id, "message": self.message, "price": 0, "type": self.type,
             "claimsCount": self.claims if claims is None else claims, "subscribeCounts": self.cap,
             "subscribeDays": self.days, "createdAt": self.created.strftime(FMT),
             "isFinished": not self.live(), "canClaim": self.live()}
        if self.finished_at is not None:
            d["finishedAt"] = self.finished_at.strftime(FMT)
        return d


@dataclass
class Acct:
    promos: list[Promo] = field(default_factory=list)
    next: list[dict] = field(default_factory=list)
    end_old: bool = True
    end_old_on_fail: bool = False
    finish_on_cap: bool = False
    new_starts_at: int = 0
    stale: dict[int, list[int]] = field(default_factory=dict)
    on_read: object = None
    posts: list[dict] = field(default_factory=list)
    events: list[tuple[float, int, str]] = field(default_factory=list)


class FakeOF:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.accts: dict[str, Acct] = {}
        self.log: list[dict] = []
        self._ids = iter(range(7_000_001, 8_000_000))
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.srv.daemon_threads = True
        self.origin = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()

    def acct(self, aid: str) -> Acct:
        with self.lock:
            return self.accts.setdefault(str(aid), Acct())

    def add(self, aid: str, *, cap: int, claims: int = 0, message: str = "", days: int = 30,
            finished_at: datetime | None = None, age_s: int = 3600) -> int:
        with self.lock:
            p = Promo(next(self._ids), cap, claims, utcnow() - timedelta(seconds=age_s), message,
                      "all", days, finished_at)
            a = self.acct(aid)
            a.promos.insert(0, p)
            a.events.append((time.time(), p.id, "start"))
            return p.id

    def get(self, aid: str, pid: int) -> Promo:
        return next(p for p in self.acct(aid).promos if p.id == pid)

    def newest(self, aid: str) -> Promo | None:
        a = self.acct(aid)
        return a.promos[0] if a.promos else None

    def finish(self, aid: str, pid: int) -> None:
        with self.lock:
            p = self.get(aid, pid)
            if p.live():
                self.acct(aid).events.append((time.time(), pid, "end"))
            p.finished = True

    def set_claims(self, aid: str, pid: int, n: int) -> None:
        with self.lock:
            p = self.get(aid, pid)
            p.claims = n
            if self.acct(aid).finish_on_cap and p.cap and n >= p.cap:
                self.finish(aid, pid)

    def claim(self, aid: str) -> int | None:
        with self.lock:
            p = next((p for p in self.acct(aid).promos
                      if p.live() and p.listed and not (p.cap and p.claims >= p.cap)), None)
            if p is None:
                return None
            self.set_claims(aid, p.id, p.claims + 1)
            return p.id

    def shift(self, aid: str, secs: float) -> None:
        d = timedelta(seconds=secs)
        with self.lock:
            for p in self.acct(aid).promos:
                p.created -= d
                if p.finished_at is not None:
                    p.finished_at -= d

    def count(self, aid: str, method: str, path: str) -> int:
        with self.lock:
            return sum(1 for r in self.log if r["account"] == str(aid) and r["method"] == method
                       and r["path"] == path)

    def gap_s(self, aid: str) -> float:
        with self.lock:
            ev = sorted(self.acct(aid).events)
        starts = [t for t, _, k in ev if k == "start"]
        if len(starts) < 2:
            return 0.0
        live, gap, last = set(), 0.0, None
        for t, pid, k in ev:
            if t > starts[-1]:
                break
            if not live and last is not None:
                gap += t - last
            live.add(pid) if k == "start" else live.discard(pid)
            last = t if not live else None
        return round(gap, 3)

    def _list(self, aid: str, q: dict) -> tuple[int, dict]:
        off, lim = int(q.get("offset", ["0"])[0]), int(q.get("limit", ["10"])[0])
        with self.lock:
            a = self.acct(aid)
            rows = []
            for p in a.promos:
                if not p.listed:
                    continue
                st = a.stale.get(p.id)
                rows.append(p.item(st.pop(0) if st else None))
            page = rows[off:off + lim]
            return 200, {"hasMore": off + lim < len(rows), "items": page}

    def _create(self, aid: str, body: dict) -> tuple[int, object, dict, float, object]:
        with self.lock:
            a = self.acct(aid)
            mode = a.next.pop(0) if a.next else {}
            old = a.promos[0] if a.promos else None
            status = int(mode.get("status", 200))
            a.posts.append({"t": time.time(), "status": status, "mode": sorted(mode),
                            "claims_old": old.claims if old else None, "cap_old": old.cap if old else None})
            made = None
            if status < 400 or mode.get("create"):
                fd = body.get("finishDays")
                made = Promo(next(self._ids), int(body.get("subscribeCounts") or 0),
                             int(mode.get("start_claims", a.new_starts_at)), utcnow(),
                             body.get("message") or "", body.get("type") or "all",
                             int(body.get("subscribeDays") or 0),
                             utcnow() + timedelta(days=int(fd)) if fd else None,
                             listed=not mode.get("never_listed"))
                now = time.time()
                if a.end_old:
                    for p in a.promos:
                        if p.live():
                            p.finished = True
                            a.events.append((now, p.id, "end"))
                a.promos.insert(0, made)
                if made.listed:
                    a.events.append((now, made.id, "start"))
            elif a.end_old_on_fail:
                for p in a.promos:
                    if p.live():
                        p.finished = True
                        a.events.append((time.time(), p.id, "end"))
        hdr = {"Retry-After": str(mode["retry_after"])} if "retry_after" in mode else {}
        if "body" in mode:
            out = mode["body"]
        elif status >= 400:
            out = {"error": {"code": status, "message": mode.get("message", "Bad request")}}
        elif mode.get("no_id"):
            out = {"success": True}
        else:
            out = [made.item()]
        return status, out, hdr, float(mode.get("sleep", 0)), mode.get("hold")

    def _handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # noqa: D401 — quiet
                pass

            def _send(self, status: int, body, hdr: dict | None = None) -> None:
                raw = body.encode() if isinstance(body, str) else json.dumps(body).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "text/plain" if isinstance(body, str) else "application/json")
                    for k, v in (hdr or {}).items():
                        self.send_header(k, v)
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except OSError:
                    pass

            def _do(self, method: str) -> None:
                u = urlsplit(self.path)
                q = parse_qs(u.query)
                aid = self.headers.get("User-ID") or (q.get("u") or [""])[0]
                path = u.path.rstrip("/") or "/"
                with fake.lock:
                    fake.log.append({"t": time.time(), "account": aid, "method": method, "path": path})
                if path == "/hash":
                    return self._send(200, "%040x" % (abs(hash(aid)) % (2 ** 160)))
                if path == "/api2/v2/users/me":
                    return self._send(200, {"id": int(aid or 0), "username": f"u{aid}", "name": "Fake"})
                if path == "/api2/v2/promotions" and method == "GET":
                    status, body = fake._list(aid, q)
                    cb, fake.acct(aid).on_read = fake.acct(aid).on_read, None
                    if cb:
                        cb()
                    return self._send(status, body)
                if path == "/api2/v2/promotions" and method == "POST":
                    n = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(n) or b"{}")
                    status, out, hdr, sleep, hold = fake._create(aid, body)
                    if hold is not None:
                        hold.wait(120)
                    if sleep:
                        time.sleep(sleep)
                    return self._send(status, out, hdr)
                return self._send(404, {"error": {"code": 404, "message": "fake: not served"}})

            def do_GET(self):  # noqa: N802
                self._do("GET")

            def do_POST(self):  # noqa: N802
                self._do("POST")

        return H
