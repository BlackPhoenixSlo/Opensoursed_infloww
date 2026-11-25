from __future__ import annotations

import asyncio
import re
import threading
import time
from collections import Counter, defaultdict

from slop.lib.client import Recorder
from slop.lib.egress_faults import TORN_DIRECT
from slop.lib.procmon import pct
from slop.lib.proxy_wire import REFUSE_S, ProxyWire
from slop.seed import of_sessions

PROFILE = "one_agency"
UI = False
OF_WIRE = True
FAULT = "interactive-reads-full-proxy-retry"
P95_VS_LAST = (1.5, 100)
P95_VS_LAST_MIN_N = 30
DEAD = 5
HEALTHY = 10
INTERACTIVE_MS = 1500
# 0.4 + 0.8 + 1.6 + 3.2 s: the full policy's jittered pauses' ceiling (floor: half)
BG_PAUSE_CAP_MS = 6000
BG_SLACK_MS = 1500
FAN = 4242
LABEL = "slop-dead"
ARRIVE_S = 5.0
THINK_S = 1.0
EARLY_S = 5.0
DOWN_AFTER = 3
BG_TRIES = 5
BG_RECORD_SLACK_S = 0.5
TORN = 5
SETTLE_S = 3.0

DEAD_READS = {
    "chats": "/api/of/v2/chats?limit=25&offset=0&order=recent",
    "notifications": "/api/of/v2/users/notifications?limit=10&offset=0",
    "messages": f"/api/of/v2/chats/{FAN}/messages?limit=10",
}
HEALTHY_READS = {
    "chats": "/api/of/v2/chats?limit=25&offset=0&order=recent",
    "users/me": "/api/of/v2/users/me",
    "notifications/count": "/api/of/v2/users/notifications/count",
}
BG_READ = "/api/of/v2/users/notifications/count"
BG_ROUTE = "/api2/v2/users/notifications/count"

C_BIND = "dead proxy: bound through /admin/proxies, each Creator's first users/me tunneled through it"
C_ANS = "dead proxy: every read answered 502 proxy_unreachable, none dropped"
C_FAST = "dead proxy: interactive reads answer within budget"
C_BG = "dead proxy: background reads keep the full retry"
C_TRIES = ("dead proxy: each upstream call took the retries its priority gets (interactive 2, background 5), "
           "and the proxy saw exactly those")
C_COUNT = ("dead proxy: a read someone waits on never counts toward bad; the background reads' full-policy "
           "failures do, and no confirm runs inside the blip")
C_HEALTHY = "healthy Creators: every read answered 200 meanwhile, none dropped"
C_WIRE = "lib/of_wire.py saw only signed calls it models"

_RETRY = re.compile(rf"proxy_error_retry account=(\d+) proxy={LABEL}\(.*? attempt=(\d+)/(\d+) GET (\S+) ")
_FINAL = re.compile(rf"proxy_error account=(\d+) proxy={LABEL}\(.*? method=GET url=(\S+) ")
_PROBE = re.compile(rf"proxy_probe label={LABEL} ok=False")
_EGRESS = re.compile(r"client_egress account=(\d+) proxy=([^(\s]*)\([^)]*\)( registry=torn)?")
_EGRESS_REFUSED = re.compile(r"client_egress_refused account=(\d+)")


async def _read(http, path: str, aid: str, kind: str, headers: dict | None = None) -> dict:
    t0, start = time.perf_counter(), time.time()
    try:
        r = await http.get(path, headers={"X-Account-Id": aid, **(headers or {})})
        status = r.status_code
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
    except Exception:  # noqa: BLE001  transport error: recorded as 599 by the client too
        status, body = 599, None
    return {"kind": kind, "aid": aid, "path": path, "status": status, "start": start, "end": time.time(),
            "ms": (time.perf_counter() - t0) * 1000, "body": body}


def _unreachable(r: dict) -> bool:
    return r["status"] == 502 and ((r["body"] or {}).get("detail") or {}).get("upstream_status") == "proxy_unreachable"


async def _torn_registry(ctx, owner, torn: list[str], bound: list[int]) -> None:
    path, log = ctx.stack.tmp / "proxies.json", ctx.out / "relay.log"
    await asyncio.sleep(SETTLE_S)
    whole = path.read_bytes()
    stop, cycles = threading.Event(), [0]

    def rewrite() -> None:
        half = len(whole) // 2
        while not stop.is_set():
            with open(path, "r+b") as f:
                f.truncate(0)
                f.write(whole[:half])
                f.flush()
                time.sleep(0.002)
                f.write(whole[half:])
                f.flush()
            cycles[0] += 1
            # whole only briefly so most builds meet a torn file (at 1 ms: 2 of 5 went direct under the fault)
            time.sleep(0.0002)

    off = log.stat().st_size
    writer = threading.Thread(target=rewrite, name="slop-torn-proxies", daemon=True)
    writer.start()
    try:
        await asyncio.sleep(0.05)
        reads = await asyncio.gather(*(_read(owner, "/api/of/v2/users/me", a, "torn") for a in torn))
    finally:
        stop.set()
        await asyncio.to_thread(writer.join)
        path.write_bytes(whole)
    await asyncio.sleep(0.5)
    with open(log, "rb") as f:
        f.seek(off)
        text = f.read().decode(errors="replace")
    egress, torn_builds = defaultdict(list), 0
    for m in _EGRESS.finditer(text):
        if m.group(1) in torn:
            egress[m.group(1)].append(m.group(2))
            torn_builds += bool(m.group(3))
    off_proxy = {a: ps for a, ps in egress.items() if any(p != LABEL for p in ps)}
    refused = sorted({m.group(1) for m in _EGRESS_REFUSED.finditer(text)} & set(torn))
    unbuilt = [a for a in torn if a not in egress]
    not_200 = Counter(x["status"] for x in reads if x["status"] != 200)
    ctx.check(TORN_DIRECT, all(s == 200 for s in bound) and not not_200 and not unbuilt and not off_proxy
              and not refused and torn_builds >= 1,
              creators=len(torn), binds_not_200=[s for s in bound if s != 200], reads_not_200=dict(not_200),
              builds=sum(len(v) for v in egress.values()), unbuilt=unbuilt[:5], off_proxy=off_proxy,
              refused=refused, builds_on_torn_registry=torn_builds, rewrite_cycles=cycles[0])


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    of_sessions.seed(w, w.data["creators"])
    main = w.data["agencies"][0]["user_id"]
    aids = [c["id"] for c in w.data["creators"] if c["owner"] == main]
    n_dead = int(ctx.param("dead", DEAD))
    dead, healthy = aids[:n_dead], aids[n_dead:n_dead + HEALTHY]
    torn = aids[n_dead + HEALTHY:n_dead + HEALTHY + TORN]
    proxy = ProxyWire(float(ctx.param("refuse_ms", REFUSE_S * 1000)) / 1000)
    with proxy:
        await _run(ctx, w, proxy, dead, healthy, torn)


async def _run(ctx, w, proxy: ProxyWire, dead: list[str], healthy: list[str], torn: list[str]) -> None:
    owner, fake = ctx.owner, ctx.of_wire

    r = await owner.post("/admin/proxies", json={"label": LABEL, "scheme": "socks5", "host": "127.0.0.1",
                                                  "port": proxy.port, "notes": "slop: dies mid-run"})
    bound = [r.status_code]
    # back to back, the product's fire-and-forget SQL mirror syncs race (`sync_from_disk failed`, UNIQUE proxies.label)
    await asyncio.sleep(THINK_S)
    for a in dead:
        bound.append((await owner.post("/admin/proxies/assign", json={"label": LABEL, "account_id": a})).status_code)
    torn_bound = []
    for a in torn:
        await asyncio.sleep(THINK_S)
        r = await owner.post("/admin/proxies/assign", json={"label": LABEL, "account_id": a})
        torn_bound.append(r.status_code)
    warm = await asyncio.gather(*(_read(owner, "/api/of/v2/users/me", a, "warm") for a in dead))
    tunneled = sum(1 for c in proxy.connects if c["alive"])
    ctx.check(C_BIND, all(s == 200 for s in bound) and all(x["status"] == 200 for x in warm) and tunneled >= len(dead),
              routes=bound, warm={x["aid"]: x["status"] for x in warm}, tunneled=tunneled)
    await _torn_registry(ctx, owner, torn, torn_bound)

    rng = w.rng("dead_proxy_people")
    picks = [rng.choice(dead + healthy) for _ in range(ctx.users)]
    dead_rec = Recorder()
    n_dead_reads = sum(len(DEAD_READS) for a in picks if a in dead)
    pool = 3 * len(picks) + len(dead)
    dead_http, live_http = owner.share(rec=dead_rec, limits=pool), owner.share(limits=pool)
    n0 = len(fake.calls)
    c0 = len(proxy.connects)
    killed_at = proxy.kill()
    ctx.rec.stage = "dead"

    async def health() -> dict:
        r = await owner.get("/admin/proxies")
        rows = r.json().get("proxies", []) if r.status_code == 200 else []
        return next((p.get("health") or {} for p in rows if p.get("label") == LABEL), {})

    async def early() -> tuple[float, dict, float]:
        await asyncio.sleep(max(0.0, killed_at + EARLY_S - time.time()))
        t = time.time()
        h = await health()
        return t, h, time.time()
    early_task = asyncio.create_task(early())
    bg = [asyncio.create_task(_read(dead_http, BG_READ, a, "background", {"X-Priority": "background"}))
          for a in dead]
    await asyncio.sleep(0.05)

    arrive_s = float(ctx.param("arrive_s", ARRIVE_S))
    when = w.rng("dead_proxy_arrivals")
    offsets = [when.uniform(0, arrive_s) for _ in picks]

    async def person(aid: str, at: float) -> list[dict]:
        await asyncio.sleep(at)
        if aid in dead:
            return await asyncio.gather(*(_read(dead_http, p, aid, "interactive") for p in DEAD_READS.values()))
        return await asyncio.gather(*(_read(live_http, p, aid, "healthy") for p in HEALTHY_READS.values()))

    people = [x for rs in await asyncio.gather(*(person(a, at) for a, at in zip(picks, offsets))) for x in rs]
    bgs = await asyncio.gather(*bg)
    early_at, early_health, early_read_at = await early_task
    after_health = await health()
    ctx.rec.stage = None
    for h in (dead_http, live_http):
        await h.aclose()
    await asyncio.sleep(0.5)
    with proxy.lock:
        refused = [c for c in proxy.connects[c0:] if not c["alive"]]

    inter = [x for x in people if x["kind"] == "interactive"]
    live = [x for x in people if x["kind"] == "healthy"]
    want_inter = n_dead_reads
    want_live = len(HEALTHY_READS) * sum(1 for a in picks if a in healthy)

    not_unreach = Counter(f"{x['kind']} {x['status']}" for x in inter + bgs if not _unreachable(x))
    ctx.check(C_ANS, len(inter) == want_inter and len(bgs) == len(dead) and not not_unreach,
              interactive=len(inter), want_interactive=want_inter, background=len(bgs), want_background=len(dead),
              not_proxy_unreachable=dict(not_unreach))

    ims = [x["ms"] for x in inter]
    p95 = pct(ims, 0.95)
    budget = float(ctx.param("interactive_ms", INTERACTIVE_MS))
    if ims:
        ctx.check(C_FAST, p95 <= budget, budget=True, p95_ms=p95, p50_ms=pct(ims, 0.5),
                  max_ms=round(max(ims), 1), budget_ms=budget, n=len(ims))
    else:
        ctx.skip(C_FAST, "no person opened a dead Creator (--users too low)")

    bms = [x["ms"] for x in bgs]
    refused_ms = BG_TRIES * proxy.refuse_s * 1000
    floor_ms = refused_ms + BG_PAUSE_CAP_MS / 2
    ceil_ms = refused_ms + BG_PAUSE_CAP_MS + BG_SLACK_MS
    ctx.check(C_BG, bool(bms) and floor_ms <= min(bms) and max(bms) <= ceil_ms,
              min_ms=round(min(bms), 1) if bms else None, max_ms=round(max(bms), 1) if bms else None,
              floor_ms=floor_ms, ceil_ms=ceil_ms, n=len(bms))

    text = (ctx.out / "relay.log").read_text(errors="replace")
    calls, retries, ns = Counter(), Counter(), defaultdict(set)
    for m in _FINAL.finditer(text):
        calls[m.group(2)] += 1
    for m in _RETRY.finditer(text):
        retries[m.group(4)] += 1
        ns[m.group(4)].add(int(m.group(3)))
    want_n = {route: (5 if route == BG_ROUTE else 2) for route in calls}
    tries = {route: calls[route] * want_n[route] for route in calls}
    off = {route: {"calls": calls[route], "retry_lines": retries[route], "tries_per_call": sorted(ns[route]),
                   "want": want_n[route]}
           for route in calls
           if ns[route] != {want_n[route]} or retries[route] != calls[route] * (want_n[route] - 1)}
    probes = len(_PROBE.findall(text))
    ctx.check(C_TRIES, bool(calls) and BG_ROUTE in calls and len(calls) > 1 and not off
              and sum(tries.values()) == len(refused) - probes,
              upstream_calls=dict(calls), off=off, tries=sum(tries.values()), refused_connects=len(refused),
              probe_connects=probes)

    failed_early = sum(1 for x in inter if x["end"] <= early_at)
    bg_early = sum(1 for x in bgs if x["end"] <= early_read_at + BG_RECORD_SLACK_S)
    if failed_early < DOWN_AFTER:
        ctx.skip(C_COUNT, f"only {failed_early} interactive reads had failed {EARLY_S} s after the death "
                          f"(need {DOWN_AFTER})")
    else:
        ctx.check(C_COUNT, (early_health.get("errors") or 0) <= bg_early
                  and early_health.get("state") in ("healthy", "suspect")
                  and (after_health.get("errors") or 0) >= len(dead) and after_health.get("state") == "suspect",
                  interactive_failed_before=failed_early, background_ended_before=bg_early,
                  at_s=round(early_at - killed_at, 2), early=early_health.get("state"),
                  early_errors=early_health.get("errors"), after=after_health.get("state"),
                  after_errors=after_health.get("errors"), want_after_errors_min=len(dead))

    bad_live = Counter(x["status"] for x in live if x["status"] != 200)
    ctx.check(C_HEALTHY, len(live) == want_live and not bad_live, calls=len(live), want=want_live,
              not_200=dict(bad_live))
    ctx.check(C_WIRE, fake.unsigned == 0 and not fake.unmodelled, unsigned=fake.unsigned,
              unmodelled=dict(fake.unmodelled), of_calls=len(fake.calls) - n0)

    lms = [x["ms"] for x in live]
    by_read = {k: pct([x["ms"] for x in inter if x["path"] == p], 0.95) for k, p in DEAD_READS.items()}
    ctx.metric("dead_proxy", {
        "dead": len(dead), "healthy": len(healthy), "people": len(picks), "refuse_s": proxy.refuse_s,
        "arrive_s": arrive_s,
        "interactive_ms": {"n": len(ims), "p50": pct(ims, 0.5), "p95": p95, "max": round(max(ims), 1) if ims else None,
                           "p95_by_read": by_read},
        "background_ms": {"n": len(bms), "min": round(min(bms), 1) if bms else None,
                          "max": round(max(bms), 1) if bms else None},
        "background_reads": [{"aid": x["aid"], "start": round(x["start"], 3), "end": round(x["end"], 3)}
                             for x in bgs],
        "killed_at": round(killed_at, 3), "people_done_at": round(max((x["end"] for x in people), default=0), 3),
        "healthy_ms": {"n": len(lms), "p50": pct(lms, 0.5), "p95": pct(lms, 0.95)},
        "upstream_calls": dict(calls), "refused_connects": len(refused)})
    end_health = await health()
    ctx.metric("dead_proxy_health", {k: end_health.get(k) for k in ("refusals", "inflight", "inflight_peak")})
    ctx.metric("http_dead", dead_rec.summary())
    ctx.metric("p95_vs_last_green", {"healthy reads": pct(lms, 0.95)} if lms else {})
    ctx.metric("p95_vs_last_green_n", {"healthy reads": len(lms)})
    ctx.note(f"dead proxy ({len(dead)} Creators, {proxy.refuse_s * 1000:.0f} ms per refused CONNECT): interactive "
             f"p50 {pct(ims, 0.5)} / p95 {p95} / max {round(max(ims), 1) if ims else None} ms (n {len(ims)}); "
             f"background min {round(min(bms), 1) if bms else None} / max {round(max(bms), 1) if bms else None} ms "
             f"(n {len(bms)}); healthy p95 {pct(lms, 0.95)} ms (n {len(lms)})",
             f"upstream calls by route: {dict(calls)}; refused CONNECTs {len(refused)}",
             "interactive p95 ms by read: " + ", ".join(f"{k} {v}" for k, v in by_read.items()))
