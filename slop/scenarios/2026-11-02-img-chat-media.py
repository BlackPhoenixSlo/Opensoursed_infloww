"""Chat media through the relay's `/img` OF-CDN proxy (service/img_api.py: disk cache, the IMG_FETCH lane, the
in-slot re-read that collapses a cold-pane herd, by-hash), at volume, with `--users` owner tabs opening the same
chats at once.

World: `agency_inbox` plus seed/chat_media.py, `--set img_assets=` CDN assets (120 small, 400 medium, 1200 huge): photo
messages in existing threads with their `message_media` rows, on synthetic signed `cdn2/cdn3.onlyfans.com` URLs,
some on `public.onlyfans.com` (the direct lane), a few full sources > 2 MiB (never disk-cached), and stale chats
whose signatures expired. The scenario arms lib/img_relay.py (the fake CDN at curl_cffi's wire) with every asset.

Each tab (`--users`, one owner session's pool) opens its chats like the app (`GET /admin/messages/{creator}/{fan}`,
X-Account-Id) and fetches every photo's thumb (MediaTile) and full source (the lightbox) as MediaTile does:
`/img?u=<url>&account_id=<creator>`, no header, TAB_CONC at a time. Fresh chats are split: the probe's (from the end
of the list, until PROBE_TILES cacheable assets, at most half) and the herd's. Tab i opens CHATS_PER_USER herd chats
spread over the list, so each is opened by ~users x CHATS_PER_USER / herd chats tabs at once (the cold-pane herd).
  cold        every tab at once, empty disk cache.
  warm        the same opens again.
  rotated     OF re-signed every fresh URL (seed/chat_media.rotate: the message_media rows a REST refresh rewrites),
              the same opens: same host + path, new Policy / Signature.
  stale       users // STALE_USERS_DIV tabs open the stale chats at once: every photo's signature expired.
  probe-miss  quiet (nothing else in flight): one tab opens the probe chats, one fetch at a time, cold cache.
  probe-hit   the same opens again (warm).
  by-hash     the owner fetches each > 2 MiB source with X-Account-Id (the header img_api needs to answer X-Img-Hash),
              then `/img/by-hash/<h>?account_id=`.
Every phase ends once the img_fetch lane is back to 0 busy (DRAIN_S).

Checks (names in lib/img_faults.py): BYTES, CDN_COLLAPSE, COLD_HERD, WARM_HIT, MAX_INFLIGHT, BIG, DIRECT, EXPIRED,
LANE_DRAINED, REJECTED, BY_HASH, NO_OFFHOST; TILE_HASH is KNOWN_RED (SKIP with this run's result). Budgets: the quiet
probe's cacheable tiles, cold (`MISS_P95_MS`, probe-miss) and warm (`HIT_P95_MS`, probe-hit), both also vs the last
green run (`P95_VS_LAST`); plus the stock no 5xx / no unexpected Traceback. The herd's tile p95s are metrics only
(`herd_p95_ms`): they are the harness's own queue (users x TAB_CONC in flight), not a tile's cost.
"Cacheable" = a fresh asset <= 2 MiB. Assets > 2 MiB (BIG) and stale ones (EXPIRED) are excluded from
CDN_COLLAPSE / WARM_HIT and asserted on their own lines. CDN_COLLAPSE is per asset <= the cap, not == 1: the
product has no per-URL single-flight (up to `cap` slots can fetch one asset before the first write lands).
COLD_HERD (cold and stale, the herds that miss the cache): no /img 5xx but the lane's own 503, and /admin/streams
(a sync route: it needs a threadpool token) polled every STREAMS_POLL_S from its own thread answers
< COLD_HERD_STREAMS_MS. The contention lives in the stale herd (every fetch misses and takes a slot); cold is
mostly HIT / COLLAPSED once the first misses land. Measured green at medium / 200
(20261103T184827Z-2026-11-02-img-chat-media-c239): max 299.0 ms cold (482 first-look misses of 5362), 21.1 ms stale.

The threadpool finding (#172, the mechanism in service/admission.py `Lane.enter_async`), closed. Pre-fix at
medium / 200 (20261103T153026Z-2026-11-02-img-chat-media-7911, host load ~26): 5239 of 5362 cold /img 5xx,
/admin/streams p50 ~10 s, 246 relay threads, the run died INFRA. Not reliably reproduced on a quieter host (the same
pre-fix code: 20261103T162502Z-...-a362 COLD_HERD red only, stale /admin/streams 2266 ms;
20261103T162707Z-...-fcde green; HEAD's img_api.py + admission.py copied onto this tree,
20261103T184642Z-2026-11-02-img-chat-media-4256: green, 167 relay threads at cold's peak, stale /admin/streams max
1431.9 ms). /img is now `async def` and waits in `Lane.enter_async` on the loop; measured (c239 above): 0 5xx, 84
relay threads at cold's peak, stale /admin/streams max 21.1 ms.

Bypasses (declared):
  - OnlyFans' CDN is lib/img_relay.py's loopback fake (module docstring), reached through the product's own
    curl_cffi sessions (rewritten at curl_cffi's request wire): CDN_LATENCY_S per request (0.1 s, a guess at OF's
    CDN through a proxy); bytes are seeded noise; only the Policy's expiry is checked; no Range, no CDN 5xx.
  - The Creators have no OF session: `_OfflineOF` (lib/relay.py) answers `client.http` with img_relay's per-Creator
    curl_cffi session (impersonate as of_client, synthetic auth_id / sess cookies and account headers), no proxy.
  - `img_api._IMG_CACHE_DIR` is re-pointed into the run's temp dir at arm (never the laptop's /tmp default).
  - Media rows and the rotation are SQL (seed/chat_media.py: the rows the transcoder and reconcile_rest_media
    write). Tabs are one owner session's connection pool, not browsers: TAB_CONC fetches at a time (Chromium's
    HTTP/1.1 per-host cap; a guess for an HTTP/2 deploy), no browser HTTP cache or service worker (sw-images.js
    is production-only).
  - The by-hash phase sends X-Account-Id on /img, which MediaTile never does (TILE_HASH).
  - The tabs' GET is resent once on a socket reset before any response (`_TabHttp`, Chromium's keep-alive retry),
    counted in the `resent_on_reset` metric (0-3 a run at medium / 200).
  - SLOP_LIVE=1 is refused (every check SKIPs).

Break-it-once: `img-cache-never-hits` (the scenario's FAULT, `--break`'s default small / 20: `img_api._img_cache_lookup`
always misses) turns WARM_HIT and CDN_COLLAPSE red (the probe-hit budget too: noise); `--fault=img-cache-key-keeps-signature` (the disk-cache key is the whole
signed URL, so the rotated reopen misses) WARM_HIT; `--fault=img-fetch-lane-unbounded` (IMG_FETCH admits
everything) MAX_INFLIGHT (CDN_COLLAPSE may go red too: noise, measured not reliable); `--scale=medium --users=200
--fault=img-fetch-on-pool-tokens` (the #172 cycle back: the lane's wait parks a threadpool thread and the
failed-fetch close needs a pool token while holding its slot) COLD_HERD
(20261103T185000Z-2026-11-02-img-chat-media-break-f83d: stale /admin/streams 10 s timeouts, 177 lane 503s; EXPIRED,
REJECTED and the stock 5xx go red too: noise, the wedge's own 503s).
"""
# No `from __future__ import annotations`: lib/cli.py loads a scenario outside sys.modules, and @dataclass resolves
# string annotations through it.
import asyncio
import hashlib
import json
import os
import threading
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlencode, urlsplit

import httpx

from slop.lib.img_faults import (
    BIG, BY_HASH, BYTES, CDN_COLLAPSE, COLD_HERD, DIRECT, EXPIRED, LANE_DRAINED, MAX_INFLIGHT, NO_OFFHOST, REJECTED,
    TILE_HASH, WARM_HIT,
)
from slop.lib.client import Http
from slop.lib.img_relay import ACCOUNT_HEADERS, arm_run, creator_headers, signed
from slop.lib.procmon import pct
from slop.seed import chat_media

PROFILE = "agency_inbox"
UI = False
FAULT = "img-cache-never-hits"
CDN_LATENCY_S = 0.1     # per fake CDN request (a guess)
TAB_CONC = 6
CHATS_PER_USER = 3
STALE_USERS_DIV = 4
PROBE_TILES = 30        # cacheable assets the probe chats hold
DRAIN_S = 30
STREAMS_POLL_S = 0.5    # COLD_HERD: /admin/streams polled this often through the cold and stale phases
STREAMS_TIMEOUT_S = 10  # a poll that takes longer is recorded as this (a wedged relay)
COLD_HERD_STREAMS_MS = 2000  # COLD_HERD's budget: every /admin/streams poll through a cache-miss herd
# Budgets on the quiet probe (one tab, one fetch at a time, nothing else in flight), cacheable tiles. Measured
# (host load ~3): probe-miss p95 125.2 ms (n=32, medium/200, 20261103T184827Z-2026-11-02-img-chat-media-c239) and
# 125.5 ms (n=32, small/20, 20261103T185147Z-2026-11-02-img-chat-media-baseline-b668), of which 100 ms is the fake's
# CDN_LATENCY_S sleep; probe-hit p95 2.4 / 2.9 ms.
# What catches what (headroom is a guess):
#   MISS_P95_MS   absolute ceiling on a quiet miss (one CDN round-trip + the relay's ~27 ms): a miss stuck behind the
#                 lane or a stall, or >= 2 extra round-trips. One extra round-trip (~227 ms) still fits it:
#   P95_VS_LAST   catches that, relative to the last green run: miss limit max(1.5 x ~127, ~127 + 50) ~ 190 ms.
#   HIT_P95_MS    a warm tile that pays any CDN call (>= CDN_LATENCY_S) can never fit it (asserted below).
# The herd's p95s (medium/200: cold ~11.7 s, warm ~5.6 s) are the harness's queue, metrics only.
MISS_P95_MS = 250
HIT_P95_MS = 50
P95_VS_LAST = (1.5, 50)
P95_VS_LAST_MIN_N = 20
assert HIT_P95_MS < CDN_LATENCY_S * 1000
assert PROBE_TILES >= P95_VS_LAST_MIN_N  # the probe's tiles are what P95_VS_LAST compares
PROBE_MISS_P95 = f"p95 img cold tile, quiet probe (/img MISS) < {MISS_P95_MS}ms"
PROBE_HIT_P95 = f"p95 img warm tile, quiet probe (/img HIT) < {HIT_P95_MS}ms: no warm tile pays a CDN round-trip"
KNOWN_RED = {
    TILE_HASH: "open finding: img_api._stream_upstream sets X-Img-Hash only when the request carries X-Account-Id, "
               "and MediaTile fetches /img?u=&account_id= with no header (app/lib/mediaUrl.ts proxyImage, "
               "next.config rewrites, Traefik add none), so its by-hash pivot never fires",
}


def _keepalive_reset(e: httpx.HTTPError) -> bool:
    """The keep-alive race's shapes: a reset socket (ReadError, measured: cause BrokenResourceError) or a close
    before any response. A truncated body ('peer closed connection without sending complete message body') is
    neither: never resent, it reaches BYTES as a transport error."""
    if isinstance(e, httpx.RemoteProtocolError):
        return "without sending a response" in str(e)
    return isinstance(e, httpx.ReadError)


class _TabHttp(Http):
    """The tabs' pool. A GET the relay's socket reset before any response (`_keepalive_reset`) is sent once more,
    as Chromium resends a request whose reused keep-alive socket fails (lib/client.py's KEEPALIVE_EXPIRY_S note).
    With /img off the threadpool the relay outruns the harness: it drains users x TAB_CONC bodies at once, and can
    finish reading one > 5 s - KEEPALIVE_EXPIRY_S after uvicorn started that connection's keep-alive timer
    (measured: those requests never reach the relay's access log, and with keep-alive off none fail,
    20261103T155317Z-2026-11-02-img-chat-media-9283). The resend sits under Http's recording (one record per GET,
    both tries timed); each is kept in `resent` with its error."""

    def __init__(self, owner: Http, limits: int) -> None:
        super().__init__(str(owner.c.base_url), owner.rec, limits=limits, host=owner.host, prefix=owner.prefix,
                         headers=owner.headers)
        self.c.cookies = owner.c.cookies   # as Http.share
        self.resent: list[str] = []
        send = self.c.request

        async def once_more(method: str, url, **kw) -> httpx.Response:
            try:
                return await send(method, url, **kw)
            except httpx.HTTPError as e:
                if method != "GET" or not _keepalive_reset(e):
                    raise
                self.resent.append(f"{str(url).split('?')[0]} {type(e).__name__}: {e} (cause "
                                   f"{e.__cause__ or e.__context__!r}; stage {self.rec.stage})")
                return await send(method, url, **kw)

        self.c.request = once_more


def _key(url: str) -> str:
    p = urlsplit(url)
    return f"{(p.hostname or '').lower()}{p.path}"


class Sink(NamedTuple):
    """What a phase's opens record: one rec per /img (and by-hash) fetch, and every open that failed."""
    recs: list
    bad: list


@dataclass
class Phase:
    """One phase's fetches and what the relay and the fake saw, once the img_fetch lane drained."""
    name: str
    want: Counter       # /img fetches by asset key its opens must make (the opened chats' media, per open)
    recs: list
    opens_bad: list
    calls: list         # the fake CDN's calls during the phase, in arrival order
    disk0: dict         # /admin/img-cache/disk before / after
    disk1: dict
    streams0: dict      # /admin/streams before / after
    streams1: dict
    drained: bool
    seconds: float
    streams_ms: list    # COLD_HERD: each /admin/streams poll's latency during the opens (cold and stale only)

    def disk_delta(self, k: str) -> int:
        return self.disk1[k] - self.disk0[k]

    def streams_delta(self, k: str) -> int:
        return self.streams1[k] - self.streams0[k]

    def img_recs(self) -> list:
        return [r for r in self.recs if not r["by_hash"]]


async def _img(http, sink: Sink, assets: dict, key: str, aid: str, url: str | None, path: str, *,
               by_hash: bool = False, headers: dict | None = None) -> dict:
    """One GET through the pool's Http (recorded under lib/client's label, a transport error with its cause in
    http.json), timed here for the probe budgets."""
    t = time.perf_counter()
    try:
        r = await http.get(path, headers=headers)
        status, body, h = r.status_code, r.content, r.headers
    except httpx.HTTPError as e:
        sink.bad.append(f"{path.split('?')[0]} {key}: {type(e).__name__}")
        status, body, h = 599, b"", {}
    a = assets.get(key)
    rec = {"key": key, "url": url, "aid": aid, "status": status, "cache": h.get("x-img-cache"),
           "detail": "" if status == 200 else body[:200].decode("utf-8", "replace"),
           "hash": h.get("x-img-hash"), "ms": (time.perf_counter() - t) * 1000, "by_hash": by_hash,
           "bytes_ok": a is not None and status == 200 and len(body) == a["size"]
           and hashlib.sha256(body).hexdigest() == a["sha256"]}
    sink.recs.append(rec)
    return rec


def _fetch(http, sink: Sink, assets: dict, aid: str, url: str, *, header: bool = False):
    """One /img like MediaTile (`header`: + X-Account-Id)."""
    return _img(http, sink, assets, _key(url), aid, url, f"/img?{urlencode({'u': url, 'account_id': aid})}",
                headers={"X-Account-Id": aid} if header else None)


async def _open(http, sink: Sink, assets: dict, chat: dict, conc: int) -> None:
    aid, fan = chat["account_id"], chat["fan_id"]
    try:
        r = await http.get(f"/admin/messages/{aid}/{fan}?limit=50", headers={"X-Account-Id": aid})
    except httpx.HTTPError as e:  # recorded as 599 by Http; BYTES fails on it
        sink.bad.append(f"messages {aid}/{fan}: {type(e).__name__}")
        return
    if r.status_code != 200:
        sink.bad.append(f"messages {aid}/{fan}: {r.status_code}")
        return
    urls = [u for m in r.json()["messages"] for md in (m.get("media") or [])
            for u in (md.get("thumb_url"), md.get("source_url")) if u]
    sem = asyncio.Semaphore(conc)

    async def one(u: str) -> None:
        async with sem:
            await _fetch(http, sink, assets, aid, u)

    await asyncio.gather(*(one(u) for u in urls))


def _tabs(http, plans: list[list[dict]], assets: dict, conc: int = TAB_CONC):
    """A phase body: every plan a tab, all at once; each opens its chats in turn."""
    async def body(sink: Sink) -> None:
        async def tab(chats):
            for c in chats:
                await _open(http, sink, assets, c, conc)
        await asyncio.gather(*(tab(p) for p in plans))
    return body


def _want(plans: list[list[dict]]) -> Counter:
    return Counter(k for p in plans for c in p for m in c["media"] for k in (m["thumb"], m["source"]))


async def _json(ctx, path: str) -> dict:
    r = await ctx.owner.get(path)
    if r.status_code != 200:
        raise RuntimeError(f"slop: {path} answered {r.status_code}: {r.text[:200]}")
    return r.json()


def _watch_streams(owner, out: list, stop: threading.Event) -> None:
    """COLD_HERD: GET /admin/streams every STREAMS_POLL_S until `stop`, each poll's ms (a timeout, transport error
    or non-200 is STREAMS_TIMEOUT_S x 1000). Its own thread, sync client and connection, so the harness's own loop
    (busy with users x TAB_CONC fetches) is not in the number."""
    with httpx.Client(base_url=str(owner.c.base_url), cookies=owner.c.cookies, headers=owner.headers,
                      timeout=STREAMS_TIMEOUT_S) as http:
        while not stop.is_set():
            t = time.perf_counter()
            try:
                r = http.get("/admin/streams")
                ms = (time.perf_counter() - t) * 1000 if r.status_code == 200 else STREAMS_TIMEOUT_S * 1000
            except httpx.HTTPError:
                ms = STREAMS_TIMEOUT_S * 1000
            out.append(round(ms, 1))
            stop.wait(STREAMS_POLL_S)


async def _phase(ctx, name: str, want: Counter, body, *, watch: bool = False) -> Phase:
    """`body(sink)` runs the phase's opens (`watch`: /admin/streams polled meanwhile); then wait for the lane to
    drain and take the fake's calls."""
    ctx.rec.stage = name
    disk0, streams0 = await _json(ctx, "/admin/img-cache/disk"), await _json(ctx, "/admin/streams")
    n0 = (await _json(ctx, "/__slop/img/stats"))["n"]
    sink = Sink([], [])
    t = time.time()
    streams_ms: list = []
    stop = threading.Event()
    watcher = asyncio.create_task(asyncio.to_thread(_watch_streams, ctx.owner, streams_ms, stop)) if watch else None
    try:
        await body(sink)
    finally:
        stop.set()
        if watcher:
            await watcher
    drained, t_end = False, time.monotonic() + DRAIN_S
    while time.monotonic() < t_end:
        try:  # a wedged relay (COLD_HERD red) may not answer at once: keep polling until DRAIN_S
            st = await _json(ctx, "/admin/streams")
        except httpx.HTTPError:
            continue
        if st["img_fetch_busy"] == 0 and st["active"] == 0:
            drained = True
            break
        await asyncio.sleep(0.2)
    seconds = round(time.time() - t, 1)
    disk1, streams1 = await _json(ctx, "/admin/img-cache/disk"), await _json(ctx, "/admin/streams")
    n1 = (await _json(ctx, "/__slop/img/stats"))["n"]
    calls = (await _json(ctx, f"/__slop/img/calls?since={n0}&until={n1}"))["calls"]
    return Phase(name, want, sink.recs, sink.bad, calls, disk0, disk1, streams0, streams1, drained, seconds,
                 streams_ms)


@dataclass
class Run:
    assets: dict
    cacheable: set      # asset keys: fresh, <= 2 MiB
    big: set            # asset keys: > 2 MiB
    expired: set        # asset keys: stale (expired signature)
    rotated_urls: dict  # asset key -> its re-signed URL (seed/chat_media.rotate)
    cache_dir: Path     # the arm hook's re-pointed img_api._IMG_CACHE_DIR
    cold: Phase
    warm: Phase
    rot: Phase
    stale: Phase
    pmiss: Phase
    phit: Phase
    byh: Phase

    @property
    def phases(self) -> tuple:
        return self.cold, self.warm, self.rot, self.stale, self.pmiss, self.phit, self.byh

    @property
    def cap(self) -> int:
        return self.cold.streams1["img_fetch_cap"]

    def tiles(self, p: Phase) -> list:
        """The phase's cacheable /img fetches."""
        return [r for r in p.img_recs() if r["key"] in self.cacheable]


def _known_red(ctx, name: str, ok: bool, **detail) -> None:
    ctx.skip(name, f"KNOWN_RED: {KNOWN_RED[name]} (this run: {'pass' if ok else 'fail'})", **detail)


def _check_bytes(ctx, r: Run) -> None:
    """Per phase the /img fetches by asset == the opened chats' media; every 200 is the CDN's bytes; every fresh
    asset 200; no fetch or CDN call for an asset the seed does not know."""
    bad, per_phase, ok = [], {}, True
    for p in r.phases:
        got = Counter(x["key"] for x in p.img_recs())
        missing, extra = p.want - got, got - p.want
        ok = ok and bool(p.want) and not missing and not extra
        per_phase[p.name] = {"fetches": sum(got.values()), "want": sum(p.want.values()),
                             "missing": dict(list(missing.items())[:3]), "extra": dict(list(extra.items())[:3])}
        bad += [dict(x, phase=p.name) for x in p.recs
                if x["key"] not in r.assets or (x["status"] == 200 and not x["bytes_ok"])
                or (x["key"] not in r.expired and x["status"] != 200)]
    unknown_calls = [c["key"] for p in r.phases for c in p.calls if c["key"] not in r.assets]
    opens_bad = [x for p in r.phases for x in p.opens_bad]
    ok = ok and not bad and not unknown_calls and not opens_bad
    ctx.check(BYTES, ok, per_phase=per_phase, bad=len(bad),
              sample=[{k: x[k] for k in ("phase", "key", "status", "cache", "bytes_ok")} for x in bad[:5]],
              unknown_cdn_calls=unknown_calls[:5], opens_bad=opens_bad[:5])


def _check_collapse(ctx, r: Run) -> None:
    """Cold herd: per cacheable asset <= cap CDN calls; the in-slot re-read collapsed some of the herd."""
    tiles = r.tiles(r.cold)
    per = Counter(c["key"] for c in r.cold.calls if c["key"] in r.cacheable)
    over = {k: n for k, n in per.items() if n > r.cap}
    collapsed = r.cold.streams_delta("img_cache_collapsed")
    ctx.check(CDN_COLLAPSE, r.cap > 0 and bool(tiles) and not over and collapsed > 0,
              cap=r.cap, cacheable_fetched=len({x["key"] for x in tiles}), cold_fetches=len(tiles),
              cdn_calls=sum(per.values()), max_per_asset=max(per.values(), default=0),
              per_asset_hist=dict(sorted(Counter(per.values()).items())), over_cap=dict(list(over.items())[:5]),
              img_cache_collapsed=collapsed, hits_first_look=r.cold.disk_delta("hits"),
              cache_labels=dict(Counter(x["cache"] for x in tiles)))


def _check_warm(ctx, r: Run) -> None:
    """Warm, rotated and probe-hit: every cacheable fetch HIT, no CDN call, hits delta == those fetches; the
    rotated phase fetched the re-signed URLs."""
    detail, ok = {}, True
    for p in (r.warm, r.rot, r.phit):
        f = r.tiles(p)
        calls = sum(1 for c in p.calls if c["key"] in r.cacheable)
        hits = p.disk_delta("hits")
        not_hit = [x for x in f if x["cache"] != "HIT"]
        detail[p.name] = {"fetches": len(f), "not_hit": len(not_hit), "cdn_calls": calls, "hits_delta": hits,
                          "labels": dict(Counter(x["cache"] for x in f)),
                          "sample": [(x["key"], x["status"], x["cache"]) for x in not_hit[:3]]}
        ok = ok and bool(f) and not not_hit and calls == 0 and hits == len(f)
    rot_signed = [x for x in r.tiles(r.rot) if signed(r.assets[x["key"]]["host"])]
    not_resigned = [x["key"] for x in rot_signed if x["url"] != r.rotated_urls.get(x["key"])]
    ctx.check(WARM_HIT, ok and bool(rot_signed) and not not_resigned, **detail,
              rotated_signed_fetches=len(rot_signed), rotated_not_resigned=not_resigned[:5])


def _check_inflight(ctx, r: Run) -> None:
    """The fake never had more requests in flight than the lane's cap (`inflight` at each arrival)."""
    by_phase = {p.name: max((c["inflight"] for c in p.calls), default=0) for p in r.phases}
    ctx.check(MAX_INFLIGHT, r.cap > 0 and bool(r.cold.calls) and max(by_phase.values()) <= r.cap,
              cap=r.cap, by_phase=by_phase)


def _check_big(ctx, r: Run) -> None:
    """> 2 MiB: served whole, never cached, CDN calls == fetches == skipped_too_big delta, every phase; the relay's
    cache dir is the armed one and holds at least an entry per cacheable asset fetched (so 'no > 2 MiB file on disk'
    looks where the files are; by size, not by recomputing img_api's key)."""
    detail, ok, n = {}, True, 0
    for p in r.phases:
        f = [x for x in p.recs if x["key"] in r.big]  # by-hash re-fetches from the CDN too
        calls = sum(1 for c in p.calls if c["key"] in r.big)
        skipped = p.disk_delta("skipped_too_big")
        wrong = [x for x in f if not x["bytes_ok"] or x["cache"] != "MISS"]
        detail[p.name] = {"fetches": len(f), "cdn_calls": calls, "skipped_too_big": skipped, "wrong": len(wrong),
                          "labels": dict(Counter(x["cache"] for x in f))}
        ok = ok and not wrong and calls == len(f) == skipped
        n += len(f)
    dirs = sorted({d for p in r.phases for d in (p.disk0["dir"], p.disk1["dir"])})
    fetched = {x["key"] for p in r.phases for x in r.tiles(p)}
    sizes = [f.stat().st_size for f in r.cache_dir.glob("*/*.bin")]
    too_big = [s for s in sizes if s > chat_media.MAX_CACHE]
    ctx.check(BIG, ok and n > 0 and dirs == [str(r.cache_dir)] and bool(fetched) and len(sizes) >= len(fetched)
              and not too_big, **detail, relay_cache_dirs=dirs, armed_cache_dir=str(r.cache_dir),
              cacheable_fetched=len(fetched), bin_files=len(sizes), bin_files_over_2mib=too_big[:5])


def _check_direct(ctx, r: Run) -> None:
    """Direct-host calls carry nothing of an account (no cookie, no Creator UA, no OF headers); every signed-host
    call carries all of its own Creator's (so the check can see them)."""
    calls = [c for p in r.phases for c in p.calls if c["key"] in r.assets]
    direct = [c for c in calls if not signed(c["host"])]
    creator_uas = {creator_headers(a["account_id"])["User-Agent"] for a in r.assets.values()}
    leaky = [c for c in direct if c["cookie"] or c["of_headers"] or c["ua"] in creator_uas]
    own = set(ACCOUNT_HEADERS)
    wrong = [c for c in calls if signed(c["host"]) and (
        c["auth_id"] != r.assets[c["key"]]["account_id"] or not own <= set(c["of_headers"])
        or c["ua"] != creator_headers(r.assets[c["key"]]["account_id"])["User-Agent"])]
    signed_n = len(calls) - len(direct)
    ctx.check(DIRECT, bool(direct) and signed_n > 0 and not leaky and not wrong, direct_calls=len(direct),
              signed_calls=signed_n, leaky=[(c["path"], c["cookie"], c["of_headers"], c["ua"]) for c in leaky[:3]],
              signed_wrong=[(c["path"], c["auth_id"], c["of_headers"], c["ua"]) for c in wrong[:3]],
              direct_ua=sorted({c["ua"] for c in direct})[:2])


def _check_expired(ctx, r: Run) -> None:
    """Stale chats' fetches 403, one CDN call each (never cached)."""
    sf = [x for x in r.stale.img_recs() if x["key"] in r.expired]
    calls = [c for c in r.stale.calls if c["key"] in r.expired]
    ctx.check(EXPIRED, bool(sf) and all(x["status"] == 403 for x in sf) and len(calls) == len(sf)
              and all(c["status"] == 403 for c in calls),
              fetches=len(sf), statuses=dict(Counter(x["status"] for x in sf)), cdn_calls=len(calls),
              cdn_statuses=dict(Counter(c["status"] for c in calls)))


def _check_cold_herd(ctx, r: Run) -> None:
    """The herds that miss the cache (cold: every tab at once on an empty cache; stale: every fetch needs a slot,
    403s are never cached): each did miss, no /img 5xx but the lane's own 503, and /admin/streams kept answering
    < COLD_HERD_STREAMS_MS through each."""
    detail, ok = {}, True
    for p in (r.cold, r.stale):
        recs = p.img_recs()
        lane = [x for x in recs if x["status"] == 503 and "requests in flight" in x["detail"]]
        bad = [x for x in recs if x["status"] >= 500 and x not in lane]
        ms = p.streams_ms
        worst = max(ms, default=None)
        # A herd that found the cache warm proves nothing about contention.
        ok = ok and bool(recs) and p.disk_delta("misses") > 0 and bool(ms) and not bad \
            and worst < COLD_HERD_STREAMS_MS
        detail[p.name] = {"fetches": len(recs), "first_look_misses": p.disk_delta("misses"), "other_5xx": len(bad),
                          "other_5xx_statuses": dict(Counter(x["status"] for x in bad)), "lane_503": len(lane),
                          "sample": [(x["key"], x["status"], x["detail"][:80]) for x in bad[:3]],
                          "streams_polls": len(ms), "streams_max_ms": worst, "streams_p95_ms": pct(ms)}
    ctx.check(COLD_HERD, ok, budget_ms=COLD_HERD_STREAMS_MS, **detail)


def _check_lane(ctx, r: Run) -> None:
    """The lane back to 0 busy after every phase; nothing rejected over the run."""
    ctx.check(LANE_DRAINED, all(p.drained and p.streams1["img_fetch_busy"] == 0 for p in r.phases),
              busy_after={p.name: p.streams1["img_fetch_busy"] for p in r.phases},
              active_after={p.name: p.streams1["active"] for p in r.phases})
    rejected = r.byh.streams1["img_fetch_rejected"] - r.cold.streams0["img_fetch_rejected"]
    ctx.check(REJECTED, rejected == 0, img_fetch_rejected=rejected,
              by_phase={p.name: p.streams_delta("img_fetch_rejected") for p in r.phases})


def _check_by_hash(ctx, r: Run) -> None:
    """With X-Account-Id a miss answers X-Img-Hash, and by-hash serves the same bytes; MediaTile's shape (no
    header) is KNOWN_RED."""
    hb = [x for x in r.byh.recs if x["by_hash"]]
    hi = r.byh.img_recs()
    ctx.check(BY_HASH, bool(hi) and all(x["hash"] for x in hi) and len(hb) == len(hi)
              and all(x["status"] == 200 and x["bytes_ok"] for x in hb),
              img_with_header=len(hi), with_hash=sum(bool(x["hash"]) for x in hi), by_hash=len(hb),
              by_hash_statuses=dict(Counter(x["status"] for x in hb)), by_hash_bytes_ok=sum(x["bytes_ok"] for x in hb))
    tile_miss = [x for x in r.cold.recs if x["cache"] == "MISS"]
    _known_red(ctx, TILE_HASH, bool(tile_miss) and all(x["hash"] for x in tile_miss),
               misses=len(tile_miss), with_hash=sum(bool(x["hash"]) for x in tile_miss))


def _check_offhost(ctx) -> None:
    off = ctx.stack.tmp / "server-offhost.jsonl"
    lines = [json.loads(x) for x in off.read_text().splitlines() if x.strip()] if off.is_file() else []
    curl = [x for x in lines if x.get("via") == "curl_cffi"]
    ctx.check(NO_OFFHOST, not curl, curl_cffi_lines=len(curl), allowed=sum(not x.get("refused") for x in curl),
              targets=[x.get("target") for x in curl[:5]], offhost_lines=len(lines))


def _ms(recs: list) -> list:
    return [x["ms"] for x in recs if x["status"] == 200]


def _budget(ctx, check: str, recs: list, budget_ms: float) -> tuple | None:
    """p95 of the 200s in `recs` < budget_ms -> (p95, n), or None (SKIP) with no samples."""
    ms = _ms(recs)
    if not ms:
        ctx.skip(check, "no samples")
        return None
    p95 = round(pct(ms), 1)
    ctx.check(check, p95 < budget_ms, budget=True, p95=p95, n=len(ms), budget_ms=budget_ms)
    return p95, len(ms)


def _check_budgets(ctx, r: Run) -> None:
    """The quiet probe's cacheable tiles (budgeted, and vs the last green run); the herd's are metrics only."""
    got = {"img cold tile": _budget(ctx, PROBE_MISS_P95, r.tiles(r.pmiss), MISS_P95_MS),
           "img warm tile": _budget(ctx, PROBE_HIT_P95, r.tiles(r.phit), HIT_P95_MS)}
    ctx.metric("p95_vs_last_green", {k: v[0] for k, v in got.items() if v})
    ctx.metric("p95_vs_last_green_n", {k: v[1] for k, v in got.items() if v})
    herd = {"cold": _ms(r.tiles(r.cold)), "warm": _ms(r.tiles(r.warm) + r.tiles(r.rot))}
    ctx.metric("herd_p95_ms", {k: {"p95": round(pct(v), 1), "n": len(v)} for k, v in herd.items() if v})


def _metrics(ctx, r: Run) -> None:
    ctx.metric("phases", {p.name: {"s": p.seconds, "fetches": len(p.recs), "cdn_calls": len(p.calls),
                                   "labels": dict(Counter(x["cache"] for x in p.recs)),
                                   "statuses": dict(Counter(x["status"] for x in p.recs)),
                                   "disk_hits": p.disk_delta("hits"), "disk_misses": p.disk_delta("misses"),
                                   "disk_writes": p.disk_delta("writes"),
                                   "collapsed": p.streams_delta("img_cache_collapsed"),
                                   "rejected": p.streams_delta("img_fetch_rejected")} for p in r.phases})


async def run(ctx) -> None:
    every = (BYTES, CDN_COLLAPSE, COLD_HERD, WARM_HIT, MAX_INFLIGHT, BIG, DIRECT, EXPIRED, LANE_DRAINED, REJECTED,
             BY_HASH, TILE_HASH, NO_OFFHOST)
    if os.environ.get("SLOP_LIVE") == "1":
        for c in every:
            ctx.skip(c, "SLOP_LIVE=1: this scenario runs on the fake CDN only")
        return
    w = await ctx.build(PROFILE)
    t0 = time.time()
    data = chat_media.seed(w, ctx.param("img_assets", w.size["img_chat_assets"]))
    assets = data["assets"]
    armed = await arm_run(ctx.owner, ctx.stack.tmp, assets, CDN_LATENCY_S)
    cacheable = {k for k, a in assets.items() if not a["big"] and not a["stale"]}
    fresh = [c for c in data["chats"] if not c["stale"]]
    stale = [c for c in data["chats"] if c["stale"]]
    probe, tiles = [], 0
    while tiles < PROBE_TILES and len(probe) < len(fresh) // 2:
        c = fresh[-1 - len(probe)]
        probe.append(c)
        tiles += sum(k in cacheable for m in c["media"] for k in (m["thumb"], m["source"]))
    herd = fresh[:len(fresh) - len(probe)]
    per_tab = min(CHATS_PER_USER, len(herd))
    stride = max(1, len(herd) // per_tab)
    plans = [[herd[(i + j * stride) % len(herd)] for j in range(per_tab)] for i in range(ctx.users)]
    ctx.metric("chat_media_seed", {
        "seconds": round(time.time() - t0, 2), "chats": len(fresh), "herd_chats": len(herd),
        "probe_chats": len(probe), "probe_tiles": tiles, "stale_chats": len(stale), "assets": len(assets),
        "big": sum(a["big"] for a in assets.values()), "direct": sum(a["direct"] for a in assets.values()),
        "stale_assets": sum(a["stale"] for a in assets.values()), "cache_dir": armed["cache_dir"],
        "tabs_per_chat": round(ctx.users * per_tab / max(1, len(herd)), 1)})
    stale_plans = [[stale[i % len(stale)]] for i in range(max(1, ctx.users // STALE_USERS_DIV))]
    bigs = [k for k, a in assets.items() if a["big"]]
    http = _TabHttp(ctx.owner, limits=max(20, ctx.users * TAB_CONC))
    try:
        cold = await _phase(ctx, "cold", _want(plans), _tabs(http, plans, assets), watch=True)
        warm = await _phase(ctx, "warm", _want(plans), _tabs(http, plans, assets))
        rotated_urls = chat_media.rotate(w, data)
        rot = await _phase(ctx, "rotated", _want(plans), _tabs(http, plans, assets))
        stl = await _phase(ctx, "stale", _want(stale_plans), _tabs(http, stale_plans, assets), watch=True)
        pmiss = await _phase(ctx, "probe-miss", _want([probe]), _tabs(http, [probe], assets, conc=1))
        phit = await _phase(ctx, "probe-hit", _want([probe]), _tabs(http, [probe], assets, conc=1))

        async def by_hash(sink: Sink) -> None:
            for key in bigs:
                a = assets[key]
                rec = await _fetch(http, sink, assets, a["account_id"], rotated_urls.get(key, a["url"]), header=True)
                if rec["hash"]:  # MediaTile's rewriteToByHash URL
                    await _img(http, sink, assets, key, a["account_id"], None,
                               f"/img/by-hash/{rec['hash']}?{urlencode({'account_id': a['account_id']})}", by_hash=True)

        byh = await _phase(ctx, "by-hash", Counter(bigs), by_hash)
    finally:
        ctx.rec.stage = None
        await http.aclose()
    r = Run(assets, cacheable, set(bigs), {k for k, a in assets.items() if a["stale"]}, rotated_urls,
            Path(armed["cache_dir"]), cold, warm, rot, stl, pmiss, phit, byh)
    for p in r.phases:
        (ctx.out / f"img-calls-{p.name}.json").write_text(json.dumps(p.calls))

    for check in (_check_bytes, _check_collapse, _check_cold_herd, _check_warm, _check_inflight, _check_big, _check_direct,
                  _check_expired, _check_lane, _check_by_hash, _check_budgets):
        check(ctx, r)
    _check_offhost(ctx)
    _metrics(ctx, r)
    ctx.metric("resent_on_reset", {"n": len(http.resent), "sample": http.resent[:5]})
