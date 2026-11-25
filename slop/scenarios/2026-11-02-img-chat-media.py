# No `from __future__ import annotations`: lib/cli.py loads a scenario outside sys.modules, and @dataclass resolves string annotations through it.
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
CDN_LATENCY_S = 0.1
TAB_CONC = 6
CHATS_PER_USER = 3
STALE_USERS_DIV = 4
PROBE_TILES = 30
DRAIN_S = 30
STREAMS_POLL_S = 0.5
STREAMS_TIMEOUT_S = 10
COLD_HERD_STREAMS_MS = 2000
MISS_P95_MS = 250
HIT_P95_MS = 50
P95_VS_LAST = (1.5, 50)
P95_VS_LAST_MIN_N = 20
assert HIT_P95_MS < CDN_LATENCY_S * 1000
assert PROBE_TILES >= P95_VS_LAST_MIN_N
PROBE_MISS_P95 = f"p95 img cold tile, quiet probe (/img MISS) < {MISS_P95_MS}ms"
PROBE_HIT_P95 = f"p95 img warm tile, quiet probe (/img HIT) < {HIT_P95_MS}ms: no warm tile pays a CDN round-trip"
KNOWN_RED = {
    TILE_HASH: "open finding: img_api._stream_upstream sets X-Img-Hash only when the request carries X-Account-Id, "
               "and MediaTile fetches /img?u=&account_id= with no header (app/lib/mediaUrl.ts proxyImage, "
               "next.config rewrites, Traefik add none), so its by-hash pivot never fires",
}


def _keepalive_reset(e: httpx.HTTPError) -> bool:
    if isinstance(e, httpx.RemoteProtocolError):
        return "without sending a response" in str(e)
    return isinstance(e, httpx.ReadError)


class _TabHttp(Http):

    def __init__(self, owner: Http, limits: int) -> None:
        super().__init__(str(owner.c.base_url), owner.rec, limits=limits, host=owner.host, prefix=owner.prefix,
                         headers=owner.headers)
        self.c.cookies = owner.c.cookies
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
    recs: list
    bad: list


@dataclass
class Phase:
    name: str
    want: Counter
    recs: list
    opens_bad: list
    calls: list
    disk0: dict
    disk1: dict
    streams0: dict
    streams1: dict
    drained: bool
    seconds: float
    streams_ms: list

    def disk_delta(self, k: str) -> int:
        return self.disk1[k] - self.disk0[k]

    def streams_delta(self, k: str) -> int:
        return self.streams1[k] - self.streams0[k]

    def img_recs(self) -> list:
        return [r for r in self.recs if not r["by_hash"]]


async def _img(http, sink: Sink, assets: dict, key: str, aid: str, url: str | None, path: str, *,
               by_hash: bool = False, headers: dict | None = None) -> dict:
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
    return _img(http, sink, assets, _key(url), aid, url, f"/img?{urlencode({'u': url, 'account_id': aid})}",
                headers={"X-Account-Id": aid} if header else None)


async def _open(http, sink: Sink, assets: dict, chat: dict, conc: int) -> None:
    aid, fan = chat["account_id"], chat["fan_id"]
    try:
        r = await http.get(f"/admin/messages/{aid}/{fan}?limit=50", headers={"X-Account-Id": aid})
    except httpx.HTTPError as e:
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
        try:
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
    cacheable: set
    big: set
    expired: set
    rotated_urls: dict
    cache_dir: Path
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
        return [r for r in p.img_recs() if r["key"] in self.cacheable]


def _known_red(ctx, name: str, ok: bool, **detail) -> None:
    ctx.skip(name, f"KNOWN_RED: {KNOWN_RED[name]} (this run: {'pass' if ok else 'fail'})", **detail)


def _check_bytes(ctx, r: Run) -> None:
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
    by_phase = {p.name: max((c["inflight"] for c in p.calls), default=0) for p in r.phases}
    ctx.check(MAX_INFLIGHT, r.cap > 0 and bool(r.cold.calls) and max(by_phase.values()) <= r.cap,
              cap=r.cap, by_phase=by_phase)


def _check_big(ctx, r: Run) -> None:
    detail, ok, n = {}, True, 0
    for p in r.phases:
        f = [x for x in p.recs if x["key"] in r.big]
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
    sf = [x for x in r.stale.img_recs() if x["key"] in r.expired]
    calls = [c for c in r.stale.calls if c["key"] in r.expired]
    ctx.check(EXPIRED, bool(sf) and all(x["status"] == 403 for x in sf) and len(calls) == len(sf)
              and all(c["status"] == 403 for c in calls),
              fetches=len(sf), statuses=dict(Counter(x["status"] for x in sf)), cdn_calls=len(calls),
              cdn_statuses=dict(Counter(c["status"] for c in calls)))


def _check_cold_herd(ctx, r: Run) -> None:
    detail, ok = {}, True
    for p in (r.cold, r.stale):
        recs = p.img_recs()
        lane = [x for x in recs if x["status"] == 503 and "requests in flight" in x["detail"]]
        bad = [x for x in recs if x["status"] >= 500 and x not in lane]
        ms = p.streams_ms
        worst = max(ms, default=None)
        ok = ok and bool(recs) and p.disk_delta("misses") > 0 and bool(ms) and not bad \
            and worst < COLD_HERD_STREAMS_MS
        detail[p.name] = {"fetches": len(recs), "first_look_misses": p.disk_delta("misses"), "other_5xx": len(bad),
                          "other_5xx_statuses": dict(Counter(x["status"] for x in bad)), "lane_503": len(lane),
                          "sample": [(x["key"], x["status"], x["detail"][:80]) for x in bad[:3]],
                          "streams_polls": len(ms), "streams_max_ms": worst, "streams_p95_ms": pct(ms)}
    ctx.check(COLD_HERD, ok, budget_ms=COLD_HERD_STREAMS_MS, **detail)


def _check_lane(ctx, r: Run) -> None:
    ctx.check(LANE_DRAINED, all(p.drained and p.streams1["img_fetch_busy"] == 0 for p in r.phases),
              busy_after={p.name: p.streams1["img_fetch_busy"] for p in r.phases},
              active_after={p.name: p.streams1["active"] for p in r.phases})
    rejected = r.byh.streams1["img_fetch_rejected"] - r.cold.streams0["img_fetch_rejected"]
    ctx.check(REJECTED, rejected == 0, img_fetch_rejected=rejected,
              by_phase={p.name: p.streams_delta("img_fetch_rejected") for p in r.phases})


def _check_by_hash(ctx, r: Run) -> None:
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
    ms = _ms(recs)
    if not ms:
        ctx.skip(check, "no samples")
        return None
    p95 = round(pct(ms), 1)
    ctx.check(check, p95 < budget_ms, budget=True, p95=p95, n=len(ms), budget_ms=budget_ms)
    return p95, len(ms)


def _check_budgets(ctx, r: Run) -> None:
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
                if rec["hash"]:
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
