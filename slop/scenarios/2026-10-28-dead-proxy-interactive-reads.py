"""Reads a person waits on, for Creators whose proxy has died (the fail-fast interactive reads).
Prod 2026-10-28: a proxy answering CONNECT 403 made the Fan List (`/chats`), the bell
(`/users/notifications`) and a thread (`/chats/{fan}/messages`) run OFClient's full
proxy retry, 5 tries with 0.4-3.2 s pauses, so each read took ~7 s to its 502. Now
`server._proxy` marks a request that is not `X-Priority: background` interactive and
its GETs take 2 tries with one 0.2 s pause; background work and every write keep 5.

The world: one Agency with 50 Creators (`one_agency`), each with a captured session
(seed/of_sessions.py), so the relay builds its REAL OFClient; OnlyFans is lib/of_wire.py
on loopback (`OF_WIRE`). DEAD (5, `--set dead=`) Creators are put on one proxy,
lib/proxy_wire.py, through the product's own `POST /admin/proxies` and
`POST /admin/proxies/assign` (the owner, signed in); each reads `users/me` once through
it while it is alive (the client is built and its x-hash fetched, as on prod before
the proxy failed). Then the proxy dies, and at once: one background read per dead
Creator (`GET /api/of/v2/users/notifications/count`, `X-Priority: background`, as the
app's polls are tagged), and `--users` people, arriving at seeded times over ARRIVE_S
(5 s, `--set arrive_s=`; while the background reads are still retrying), each open one
Creator drawn from the seed among the DEAD and HEALTHY (10) others, firing that
Creator's three reads together:
dead: `/chats` (Fan List), `/users/notifications` (bell), `/chats/{fan}/messages`
(thread); healthy: `/chats`, `/users/me`, `/users/notifications/count` (what
lib/of_wire.py models).

Invariants: the binding went through and the warm-up tunneled; every read of a dead
Creator answered 502 `proxy_unreachable` (none dropped: users' reads + background reads);
interactive dead reads p95 <= INTERACTIVE_MS (budget); every background dead read still
took >= BG_MIN_MS (the 5-try pauses alone); per upstream call, the relay's own
`proxy_error_retry` / `proxy_error` lines show 2 tries for an interactive route and 5 for
the background one, and the dead proxy saw exactly that many refused CONNECTs (plus one
per `proxy_probe` line, should proxy_health probe it); a read someone waits on never
counts toward marking the proxy bad: EARLY_S after the death, with DOWN_AFTER or more
interactive reads already failed and no 5-try chain able to end yet, the proxy's
`health` (GET /admin/proxies) reads 0 errors; after the background reads it reads one
error each and still `suspect` (the confirm waits CONFIRM_GAP_S, 30 s, past a blip); every
healthy Creator's read answered 200 meanwhile; lib/of_wire.py saw only signed calls it
models. p95 of the healthy reads vs the last green run.

Bypasses, declared: the dead proxy is SOCKS5 on loopback that refuses each CONNECT after
0.33 s (lib/proxy_wire.py: measured per-try time on prod; curl 97 not 56, both
`ProxyError`); background work is the `X-Priority: background` route, not a no-request
job (ingest, automations: covered by service/tests/test_proxy_retry_interactive.py);
the dead reads' 502s go to their own recorder (the expected answer, checked here, not the
stock no-5xx check's); people are httpx pools, not browsers; all `--users` at the same
instant (`--set arrive_s=0`) measures the relay's own queue instead: healthy reads p95
~4 s with 600 at once (…-f18d, …-b46e), the cliff 2026-10-28-scoped-reads-fanout
documents; a seeded thread is not
needed for the dead thread read (it never reaches OnlyFans); the owner pauses THINK_S
(1 s) between adding the proxy and binding Creators: back to back, the product's
fire-and-forget SQL mirror syncs (`_kick_db_sync`) race and one logs `sync_from_disk
failed` (UNIQUE proxies.label), a product race outside this flow, not hidden by
EXPECTED_TRACEBACKS.

Break-it-once: interactive-reads-full-proxy-retry (the 5-try policy back for interactive
reads) turns only the budget and the tries check red; `--fault=interactive-failures-counted`
(an interactive read's failure counts toward bad again) turns only the counting check red; `--fault=relay-cache-failure-not-shared`
(callers queued behind a failed relay_cache fetch each go upstream again, one after
another: the bell's and Fan List's readers of one dead Creator wait N failures) turns
only the budget red, at `--scale=medium --users=200` (at small no reader queues behind
another, so it is NOT CAUGHT there: measured 2026-10-28).
"""
from __future__ import annotations

import asyncio
import re
import time
from collections import Counter, defaultdict

from slop.lib.client import Recorder
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
INTERACTIVE_MS = 1500   # a read someone waits on, dead proxy, request to 502
BG_MIN_MS = 6000        # 0.4 + 0.8 + 1.6 + 3.2 s: the full policy's pauses alone
FAN = 4242              # the thread a person opens on a dead Creator
LABEL = "slop-dead"
ARRIVE_S = 5.0          # people open their Creator over this window (seeded times)
THINK_S = 1.0           # the owner's pause between adding the proxy and binding Creators
EARLY_S = 5.0           # the health read after the death: before any 5-try chain can end (6 s + 5 tries)
DOWN_AFTER = 3          # service/proxy_health.py: counted failures that would start the confirm

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
BG_ROUTE = "/api2/v2/users/notifications/count"   # its OnlyFans route, in the relay's log lines

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


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    of_sessions.seed(w, w.data["creators"])
    main = w.data["agencies"][0]["user_id"]
    aids = [c["id"] for c in w.data["creators"] if c["owner"] == main]
    n_dead = int(ctx.param("dead", DEAD))
    dead, healthy = aids[:n_dead], aids[n_dead:n_dead + HEALTHY]
    proxy = ProxyWire(float(ctx.param("refuse_ms", REFUSE_S * 1000)) / 1000)
    with proxy:
        await _run(ctx, w, proxy, dead, healthy)


async def _run(ctx, w, proxy: ProxyWire, dead: list[str], healthy: list[str]) -> None:
    owner, fake = ctx.owner, ctx.of_wire

    # ── the owner puts DEAD Creators on the proxy (the product's routes), each reads once through it ──
    r = await owner.post("/admin/proxies", json={"label": LABEL, "scheme": "socks5", "host": "127.0.0.1",
                                                  "port": proxy.port, "notes": "slop: dies mid-run"})
    bound = [r.status_code]
    await asyncio.sleep(THINK_S)  # the owner picks Creators (docstring: the SQL mirror's race)
    for a in dead:
        bound.append((await owner.post("/admin/proxies/assign", json={"label": LABEL, "account_id": a})).status_code)
    warm = await asyncio.gather(*(_read(owner, "/api/of/v2/users/me", a, "warm") for a in dead))
    tunneled = sum(1 for c in proxy.connects if c["alive"])
    ctx.check(C_BIND, all(s == 200 for s in bound) and all(x["status"] == 200 for x in warm) and tunneled >= len(dead),
              routes=bound, warm={x["aid"]: x["status"] for x in warm}, tunneled=tunneled)

    # ── the proxy dies; background reads and people's reads land together ──
    rng = w.rng("dead_proxy_people")
    picks = [rng.choice(dead + healthy) for _ in range(ctx.users)]
    dead_rec = Recorder()  # the dead reads' expected 502s, checked below (declared)
    n_dead_reads = sum(len(DEAD_READS) for a in picks if a in dead)
    pool = 3 * len(picks) + len(dead)  # every read in flight at once
    dead_http, live_http = owner.share(rec=dead_rec, limits=pool), owner.share(limits=pool)
    n0 = len(fake.calls)
    c0 = len(proxy.connects)
    killed_at = proxy.kill()
    ctx.rec.stage = "dead"

    async def health() -> dict:
        r = await owner.get("/admin/proxies")
        rows = r.json().get("proxies", []) if r.status_code == 200 else []
        return next((p.get("health") or {} for p in rows if p.get("label") == LABEL), {})

    async def early() -> tuple[float, dict]:
        await asyncio.sleep(max(0.0, killed_at + EARLY_S - time.time()))
        t = time.time()
        return t, await health()
    early_task = asyncio.create_task(early())
    bg = [asyncio.create_task(_read(dead_http, BG_READ, a, "background", {"X-Priority": "background"}))
          for a in dead]
    await asyncio.sleep(0.05)  # the background calls are in their retry when people arrive

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
    early_at, early_health = await early_task
    after_health = await health()
    ctx.rec.stage = None
    for h in (dead_http, live_http):
        await h.aclose()
    await asyncio.sleep(0.5)  # the relay's last log lines reach relay.log
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
    ctx.check(C_BG, bool(bms) and min(bms) >= BG_MIN_MS, min_ms=round(min(bms), 1) if bms else None,
              max_ms=round(max(bms), 1) if bms else None, floor_ms=BG_MIN_MS, n=len(bms))

    # Per upstream call, the relay's own lines: N-1 `proxy_error_retry ... attempt=k/N <route>`
    # then one `proxy_error ... url=<route>`; the proxy refused exactly sum(N) CONNECTs.
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
    probes = len(_PROBE.findall(text))   # proxy_health's own probes through it (none expected in this window)
    ctx.check(C_TRIES, bool(calls) and BG_ROUTE in calls and len(calls) > 1 and not off
              and sum(tries.values()) == len(refused) - probes,
              upstream_calls=dict(calls), off=off, tries=sum(tries.values()), refused_connects=len(refused),
              probe_connects=probes)

    failed_early = sum(1 for x in inter if x["end"] <= early_at)
    bg_early = sum(1 for x in bgs if x["end"] <= early_at)
    if failed_early < DOWN_AFTER:   # nothing to tell apart yet (few people, or reads slower than the budget)
        ctx.skip(C_COUNT, f"only {failed_early} interactive reads had failed {EARLY_S} s after the death "
                          f"(need {DOWN_AFTER})")
    else:
        ctx.check(C_COUNT, bg_early == 0 and early_health.get("errors") == 0
                  and early_health.get("state") == "healthy"
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
    ctx.metric("http_dead", dead_rec.summary())
    ctx.metric("p95_vs_last_green", {"healthy reads": pct(lms, 0.95)} if lms else {})
    ctx.metric("p95_vs_last_green_n", {"healthy reads": len(lms)})
    ctx.note(f"dead proxy ({len(dead)} Creators, {proxy.refuse_s * 1000:.0f} ms per refused CONNECT): interactive "
             f"p50 {pct(ims, 0.5)} / p95 {p95} / max {round(max(ims), 1) if ims else None} ms (n {len(ims)}); "
             f"background min {round(min(bms), 1) if bms else None} / max {round(max(bms), 1) if bms else None} ms "
             f"(n {len(bms)}); healthy p95 {pct(lms, 0.95)} ms (n {len(lms)})",
             f"upstream calls by route: {dict(calls)}; refused CONNECTs {len(refused)}",
             "interactive p95 ms by read: " + ", ".join(f"{k} {v}" for k, v in by_read.items()))
