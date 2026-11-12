"""Bio page visitors (service/bio_pages on BIO_PORT): anonymous fans, each visit the page, the Profile JSON, the ping
and maybe one Reveal, as v2's script.js does; abusers who hammer one Profile inside one guard minute. Lifted from
scenarios/2026-11-11-bio-pages-public.py so the public and the editor scenarios share one visitor.

`plan(rng, profiles, n, reveal_share)` picks the visits from the seed (seed/bio_pages.py's oracle profiles).
`Visitors(rec, base, users)` holds `users` httpx clients (no cookie, redirects not followed) and the bookkeeping:
`leaks` (answers holding a `slopdest-` token), `page_bad`/`json_bad`/`reveal_bad`, `visitor_refused` (429s to a
visitor), `views_ok`/`clicks_ok` ((profile, [link,] sent day, answered day) per ping 204 / Reveal 200), `status`
(every answer's code, 599 for a transport error), `abuse` (one record per abuser). `on_json(p, r)`, when set,
replaces the Profile JSON == oracle bytes compare (the editor scenario's Profiles change under the visitors).
"""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

from slop.lib.client import Http
from slop.seed import bio_pages

UAS = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Safari/604.1",
       "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Instagram 300.0.0.0",
       "Mozilla/5.0 (Linux; Android 14) musical_ly_2023", "Mozilla/5.0 (Linux; Android 14) Chrome/120")
SAME = {"Sec-Fetch-Site": "same-origin"}
STUB_MARK = "This page isn't available."
BOOT = '<script type="application/json" id="profile-bootstrap">'
L_PAGE, L_ASSET, L_JSON = "bio GET page", "bio GET asset", "bio GET /api/profiles/:u.json"
L_PING, L_REVEAL = "bio POST /v/:u", "bio GET /.netlify/functions/reveal"


BIO_HOST = "bio.slop.test"


def page_target(username: str, code: str | None, custom: str | None,
                base_host: str) -> tuple[str, str, str]:
    """Host, request path and bootstrap profilePath for a bio page or tracking URL."""
    if custom:
        return custom, f"/{code}" if code else "/", "/"
    return base_host, f"/{username}/{code}" if code else f"/{username}", f"/{username}"


def day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def want_url(link: dict, tid: str | None, country: str, region: str) -> str:
    """destination.js, for the rule shapes the seeder writes."""
    code = None
    if tid == "geo":
        geo = link["geo"] or {}
        rule = geo.get(country)
        if isinstance(rule, dict):
            code = rule.get(region) or rule.get("default")
        else:
            code = rule or geo.get("default")
    elif tid and tid.isascii() and tid.isdigit():
        code = tid
    dest = link["destination"]
    if not code:
        return dest
    return (dest[:-1] if dest.endswith("/") else dest) + "/c" + code


def tid_for(link: dict, path_code: str | None) -> str | None:
    """script.js revealUrl: a tracking Link sends the stored (path) code, else its default; others send none."""
    if not link["tracking"]:
        return None
    return path_code or link["default"] or None


def block(text: str):
    s = text.find(BOOT)
    if s < 0:
        return "missing"
    s += len(BOOT)
    try:
        return json.loads(text[s:text.index("</script>", s)])
    except ValueError:
        return "unreadable"


def count_bounds(past_rows, views_ok, clicks_ok, got):
    """Per (profile, link, day) key whose stored (views, clicks) fall outside seeded + answered (a call that crossed
    UTC midnight may count on either day): {key: {db, lo, hi}}."""
    sure: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    astride: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    for pid, s, a in views_ok:
        (sure[(pid, "", s)] if s == a else astride[(pid, "", s)])[0] += 1
        if s != a:
            astride[(pid, "", a)][0] += 1
    for pid, lid, s, a in clicks_ok:
        (sure[(pid, lid, s)] if s == a else astride[(pid, lid, s)])[1] += 1
        if s != a:
            astride[(pid, lid, a)][1] += 1
    off = {}
    for key in set(got) | set(past_rows) | set(sure) | set(astride):
        past = past_rows.get(key, (0, 0))
        lo = [past[i] + sure[key][i] for i in (0, 1)] if key in sure else list(past)
        hi = [lo[i] + (astride[key][i] if key in astride else 0) for i in (0, 1)]
        g = got.get(key, (0, 0))
        if not all(lo[i] <= g[i] <= hi[i] for i in (0, 1)):
            off["|".join(key)] = {"db": g, "lo": lo, "hi": hi}
    return off


def plan(rng, profiles: list[dict], n: int, reveal_share: float) -> list[dict]:
    with_live = [p for p in profiles if p["live"]]
    weights = [rng.uniform(0.2, 3.0) for _ in profiles]
    out = []
    for _ in range(n):
        p = rng.choices(profiles, weights)[0]
        kind = rng.choices(("path", "code", "custom", "spare", "bio_host"), (55, 20, 10, 10, 5))[0]
        code = str(rng.randint(1, 99_999)) if kind == "code" or (kind == "custom" and rng.random() < 0.3) else None
        if kind == "custom":
            p = rng.choice(with_live)
        link = rng.choice(p["links"]) if rng.random() < reveal_share else None
        out.append({"p": p, "kind": kind, "code": code, "link": link, "assets": rng.random() < 0.1,
                    "country": rng.choice(bio_pages.COUNTRIES), "region": rng.choice(bio_pages.REGIONS),
                    "ua": rng.choice(UAS)})
    return out


class Visitors:
    def __init__(self, rec, base: str, users: int):
        self.rec = rec
        self.leaks: list[str] = []
        self.page_bad: list = []
        self.json_bad: list = []
        self.reveal_bad: list = []
        self.visitor_refused: list[str] = []
        self.views_ok: list[tuple[str, str, str]] = []
        self.clicks_ok: list[tuple[str, str, str, str]] = []
        self.status: Counter = Counter()
        self.abuse: list[dict] = []
        self.on_json = None
        self.base = base
        self.clients = [self._client() for _ in range(max(1, users))]

    def _client(self) -> Http:
        return Http(self.base, self.rec, limits=4)

    async def reopen(self) -> None:
        """Fresh clients (a restarted bio process: no keep-alive connection to the old one is reused)."""
        old, self.clients = self.clients, [self._client() for _ in self.clients]
        for cl in old:
            await cl.aclose()

    async def aclose(self) -> None:
        for cl in self.clients:
            await cl.aclose()

    async def call(self, cl, lbl, method, path, **kw):
        try:
            r = await cl.request(method, path, route=lbl, **kw)
        except httpx.HTTPError:
            self.status[599] += 1
            return None
        self.status[r.status_code] += 1
        return r

    def scan(self, r, what: str) -> None:
        if r is not None and "slopdest-" in r.text and len(self.leaks) < 20:
            self.leaks.append(f"{what} {r.request.url.path} -> {r.status_code}")

    async def visit(self, k: int, v: dict) -> None:
        cl = self.clients[k % len(self.clients)]
        p, kind, code = v["p"], v["kind"], v["code"]
        custom = p["live"] if kind == "custom" else None
        ip = f"100.{64 + (k >> 16) % 60}.{(k >> 8) & 255}.{k & 255}"
        u = p["username"]
        base_host = {"spare": bio_pages.SPARE, "bio_host": BIO_HOST}.get(kind, urlsplit(self.base).netloc)
        host, path, profile_path = page_target(u, code, custom, base_host)
        hdr = {"X-Forwarded-For": ip, "CF-IPCountry": v["country"], "User-Agent": v["ua"],
               **({"CF-Region-Code": v["region"]} if v["region"] else {}), "Host": host}
        want = {"username": u, "trackingCode": code, "profilePath": profile_path}
        r = await self.call(cl, L_PAGE, "GET", path, headers=hdr)
        self.scan(r, "page")
        if r is None or r.status_code != 200 or not r.headers.get("content-type", "").startswith("text/html") \
                or block(r.text) != want:
            if len(self.page_bad) < 10:
                self.page_bad.append({"path": path, "host": host, "status": getattr(r, "status_code", None),
                                      "got": block(r.text) if r is not None else None, "want": want})
            return
        if v["assets"]:
            for a in ("/script.js", "/style.css"):
                self.scan(await self.call(cl, L_ASSET, "GET", a, headers=hdr), "asset")
        r = await self.call(cl, L_JSON, "GET", f"/api/profiles/{u}.json", headers=hdr)
        self.scan(r, "json")
        if self.on_json is not None:
            self.on_json(p, r)
        elif r is None or r.status_code != 200 or r.content != p["json"]:
            if len(self.json_bad) < 10:
                self.json_bad.append({"user": u, "status": getattr(r, "status_code", None),
                                      "body": r.content[:300].decode("utf-8", "replace") if r is not None else None})
        sent = day()
        r = await self.call(cl, L_PING, "POST", f"/v/{u}", headers=hdr)
        self.scan(r, "ping")
        if r is not None and r.status_code == 204:
            self.views_ok.append((p["id"], sent, day()))
        elif r is not None and r.status_code == 429:
            self.visitor_refused.append(f"ping {u} {ip}")
        link = v["link"]
        if link is None:
            return
        tid = tid_for(link, code)
        q = f"?id={link['link_id']}&user={u}" + (f"&trackingId={tid}" if tid else "")
        sent = day()
        r = await self.call(cl, L_REVEAL, "GET", "/.netlify/functions/reveal" + q, headers={**hdr, **SAME})
        if r is None:
            return
        if r.status_code == 429:
            self.visitor_refused.append(f"reveal {u} {ip}")
            return
        want = want_url(link, tid, v["country"], v["region"])
        if r.status_code == 200:
            self.clicks_ok.append((p["id"], link["id"], sent, day()))
        else:
            self.scan(r, "reveal")
        try:
            got = r.json()
        except ValueError:
            got = r.text[:200]
        if r.status_code != 200 or got != {"realUrl": want} or r.headers.get("cache-control") != "no-store":
            if len(self.reveal_bad) < 10:
                self.reveal_bad.append({"q": q, "country": v["country"], "region": v["region"],
                                        "status": r.status_code, "got": got, "want": want})

    async def abuser(self, i: int, profiles: list[dict], limit: int) -> None:
        """One wall-clock minute (the guard's window): 5 cross-origin Reveals, then 2 x limit Reveals and 2 x limit
        pings on one Profile."""
        cl = self.clients[i % len(self.clients)]
        p = profiles[i % len(profiles)]
        link = p["links"][0]
        hdr = {"X-Forwarded-For": f"100.127.0.{i + 1}"}
        q = f"/.netlify/functions/reveal?id={link['link_id']}&user={p['username']}"
        cross = [await self.call(cl, "bio abuser reveal", "GET", q, expect=(403,),
                                 headers={**hdr, "Sec-Fetch-Site": "cross-site"})
                 for _ in range(5)]
        sent = day()
        rv = [(int(time.time() // 60), await self.call(cl, "bio abuser reveal", "GET", q,
                                                       headers={**hdr, **SAME}, expect=(429,))) for _ in range(2 * limit)]
        pg = [(int(time.time() // 60), await self.call(cl, "bio abuser ping", "POST",
                                                       f"/v/{p['username'].upper()}", headers=hdr,
                                                       expect=(429,))) for _ in range(2 * limit)]
        end = day()
        for _, r in rv:
            if r is not None and r.status_code == 200:
                self.clicks_ok.append((p["id"], link["id"], sent, end))
        for _, r in pg:
            if r is not None and r.status_code == 204:
                self.views_ok.append((p["id"], sent, end))
        refused = [r for _, r in rv + pg if r is not None and r.status_code == 429]
        per_minute = Counter((kind, minute) for kind, rows, success in
                             (("reveal", rv, 200), ("ping", pg, 204)) for minute, r in rows
                             if r is not None and r.status_code == success)
        attempts = Counter((kind, minute) for kind, rows in (("reveal", rv), ("ping", pg))
                           for minute, _ in rows)
        self.abuse.append({"abuser": i, "cross_403": sum(r is not None and r.status_code == 403 for r in cross),
                           "per_minute": {f"{kind}:{minute}": n for (kind, minute), n in per_minute.items()},
                           "minute_ok": all(per_minute[key] == min(limit, n) for key, n in attempts.items()),
                           "refused": len(refused),
                           "other": sorted({getattr(r, "status_code", None) for _, r in rv + pg} - {200, 204, 429},
                                           key=str),
                           "refused_body_ok": all(r.content == b'{"error":"Too many requests"}' for r in refused)})
