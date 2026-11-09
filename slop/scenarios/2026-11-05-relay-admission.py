"""Nothing a person taps waits behind background reads (owner, 2026-11-05: "make sure nothing blocks
user actions and it's still fast so the background action works"). Two ways a tap used to wait, both
in service/server.py's per-Creator lanes:
  A. a background read (`X-Priority: background`) took a worker thread first and then blocked there
     on its Creator's background lane (2 slots), so a flood of them filled the default executor and a
     tap's thread queued behind it; now it waits for the lane on the event loop (`_bg_admission`) and
     takes a thread only once admitted (`threads_waiting_background`, a new lane-stats gauge, stays 0);
  B. a user read joined a background read of the same key already in flight (relay_coalesce, and
     relay_cache's per-key lock) and inherited its lane wait; now the flight key carries the priority
     class (a background read may still join a user one).

The world: one Agency with 50 Creators (`one_agency`), each with a captured session
(seed/of_sessions.py), so the relay builds its REAL OFClient; OnlyFans is lib/of_wire.py on loopback
(`OF_WIRE`): after the probe a chat list answers in BG_OF_S (1.5 s on average, `route_s`; x uniform(0.5, 1.5),
`route_jitter`), the taps' reads and sends in its 50 ms.
`--users` chatters (real invites, `POST /chatter/register`, own `POST /chatter/login` cookies), each
assigned PER_USER (13) Creators, the Agency's 50 spread evenly.

Legs, one run:
  probe     quiet relay: on PROBES Creators at once, a background `GET /api/of/v2/chats?query=<unique>`
            whose OF call fake OF holds PROBE_HOLD_S (3 s, `hold`), then, once that call is on OF's
            wire, the same URL at user priority, timed.
  baseline  every chatter taps once per assigned Creator, think time THINK_MS between taps: open a
            fan (`GET /api/of/v2/chats/{fan}/messages`, the head page, always OF), send to it
            (`POST /api/of/v2/chats/{fan}/messages`), `GET /api/of/v2/users/me`.
  flood     every chatter keeps BG_PER_CREATOR (4) background chat-list reads in flight per assigned
            Creator (`refresh=1`, a unique `offset` each, so every one is its own OF call; refilled as
            each answers, until a stop Event; started at RAMP_PER_S, the host's somaxconn is 128),
            then, SETTLE_S later, the same taps as baseline; then the flood stops and drains (every
            read answered). `GET /admin/priority-lanes/stats` (owner) every SAMPLE_S throughout.

Checks (lib/relay_admission_faults.py has the targeted names): tap p95 under the flood <= 2 x the
baseline's + 100 ms per kind and overall (catches blocking, not host jitter: lib/relay_admission_faults.py); threads_waiting_background 0 in every sample (fleet and per
Creator; at least 5 samples); bg_in_flight_peak <= 2 per Creator and reached; every probe's user read
< 1 s while its background twin took >= 3 s; every chatter signed in; every tap 200 (users/me answers
the asked Creator); every background read 200, none dropped, the flood held >= 90 % of its reads in
flight while the taps ran; OnlyFans saw exactly one chat-list call per background read (its offset),
exactly one send per send tap (its text), per leg no more message reads than opens and at least one
per (Creator, fan) opened; lib/of_wire.py saw only signed calls it models; stock: no 5xx. Relay pool (C_POOL, lib/procmon.py's 1 s samples
ramp to drain): DB connections out never past the pool's bound (service/db/engine.py POOL_SIZE + MAX_SPILL, read off
/__slop/loop-cpu; an unbounded pool is red) and relay threads under THREADS_MAX; a sample past either stops the
flood there, before the gate's thread guard kills the run. Metrics:
p95 per leg and kind, lane-stats sample maxima, flood counts; p95 vs the last green run: the flood
leg's p95 per kind (standard volume: --scale=medium --users=120 --no-ui, 6,240 reads in flight).

Faults: `admission-in-thread` (default `--break`: A reverted; targets the tap p95 and thread-wait checks;
taps slow to ~10 s, past the 30 s client timeout only on a loaded host), `coalesce-ignores-priority` (B reverted; targets the probe check),
`pool-spills-unbounded` (the DB pool's spill cap off; targets C_POOL; run it as lib/relay_admission_faults.py says: 2 s spills need 200 users, where uncapped
hits the gate's thread guard first).

Bypasses, declared: lib/of_wire.py (OnlyFans on loopback, its own declared bypasses), its chat list
empty and slowed to BG_OF_S +- 50 % for every caller after the probe (a guess at OF behind a residential
proxy under load; the taps' routes keep 50 ms). The jitter is load-bearing: at a fixed 1.5 s every lane
stays in phase and ~100 answers land within 0.6 s each cycle; taps during those waves were the p95 tail
(slow taps saw ~154 background answers/s around them, fast ones ~27: evidence …-1ca3); the clients are httpx pools, not browsers: the app's relaySchedule.ts caps a
browser at 2 background reads per Creator, the flood keeps 4 per chatter (two tabs' worth) and runs
past the browser's own cap on purpose; background reads are chat lists only (the shell's other
background reads take the same lane and the same admission); the probe's background read is the
owner's, its user read too (one session, two classes, as one browser tab sends them).
"""
from __future__ import annotations

import asyncio
import itertools
import random
import re
import time
from collections import Counter
from urllib.parse import parse_qs

import httpx

from slop.lib.client import Http
from slop.lib.procmon import pct, socket_endpoints, socket_fds
from slop.lib.relay_admission_faults import (C_BG_CAP, C_NO_THREAD_WAIT, C_POOL, C_PROBE, C_TAP_P95, C_TAPS)
from slop.seed import chatters, of_sessions

PROFILE = "one_agency"
UI = False
OF_WIRE = True
FAULT = "admission-in-thread"
P95_VS_LAST = (1.5, 100)  # flood p95 spread across green-path runs on the shared machine: see P95_RATIO
P95_VS_LAST_MIN_N = 200
BG_CAP = 2  # service/server.py _ACCOUNT_LANE_BACKGROUND (default)
# The gate's per-process thread guard (README "The machine gate"). Killed at the 1500 default at
# medium/200 on main too (1518-2034 at the guard's first tick over it, 2026-11-06..09); owner 2026-11-09
# accepted ~2k (scale = more boxes), so 3000 here. Still red at 3000 (measured, 20261109T084847Z-...-b634):
# the relay grew 466 -> 3477 threads in 16 s of the flood, no plateau, its DB pool at 2856 overflow
# (spill) connections, one aiosqlite thread each (service/db/engine.py _SpillQueuePool). Above 3000 is
# the 5-7k class that panicked the Mac: bound the spills in the product, or the owner raises
# SLOP_MAX_THREADS_PROC_CEIL (3500) knowingly.
MAX_THREADS_PROC = {"medium": 3000}
# The gate's per-run socket guard (default 8192 fds, half the 16384 ephemeral ports). The flood keeps
# 200 x 13 x 4 = 10.4k reads in flight, both ends in this run's tree: 16k-31k fds at medium/200
# (measured 2026-11-09), which ran the Mac's ephemeral ports dry for every other run. Owner 2026-11-09:
# keep the flood, run it alone: medium/120 and larger are exclusive (lib/gate.py), and only an exclusive run gets
# this (capped at SLOP_MAX_SOCKETS_RUN_CEIL, 28000). Small green stays under the 8192 default. `--break`
# (admission-in-thread) was a socket runaway (8252 / 16101 / 26010 fds: -ce51, -6d14, -9217): every
# blocked worker thread keeps a curl handle per account, one socket each. Now the fake OF closes idle
# keep-alives (OF_IDLE_CLOSE_S) and SOCKETS_TRIP cuts the flood leg: no-fault small max 5481 sockets
# (52fa, was ~8.2k), the fault trips at 7621 and is CAUGHT (0df4).
MAX_SOCKETS_RUN = {"medium": 26000}
THREADS_MAX = {"small": 400, "medium": 1000}  # C_POOL: relay threads, ramp to drain; measured max small 134, medium 417-512 (caps 24-120), uncapped 3477
# relay + this process's socket fds (the gate's count): under the gate's 8192 at small, MAX_SOCKETS_RUN at medium
SOCKETS_TRIP = {"small": 7600, "medium": 25500}  # medium: no-fault medium/200 ramp reached 24289 (b705)
DB_TRIP_UNBOUNDED = 120  # an unbounded pool (max_overflow -1) stops the flood past pool_size + this many
# Catches blocking (a fault puts tap p95 at 10-30 s), not jitter: on the shared machine (gate: up to 6
# runs) the no-fault flood p95 spread over runs was 85-140 ms all, 120-189 ms send (measured: 7b84, 09ae,
# dd50, f09a), so 1.25x + 50 ms flipped on host noise.
P95_RATIO, P95_SLACK_MS = 2.0, 100
PROBE_HOLD_S, PROBE_MAX_S = 3.0, 1.0
PER_USER = 13          # Creators per chatter
BG_PER_CREATOR = 4     # background reads each chatter keeps in flight per assigned Creator
OF_IDLE_CLOSE_S = 5.0  # fake OF's keep-alive idle timeout (a guess at a real edge's)
BG_OF_S = 1.5          # OF's answer time for a chat list, on average
BG_JITTER = 0.5        # each one BG_OF_S x uniform(0.5, 1.5)
THINK_MS = (500, 1500)  # between one chatter's taps
RAMP_PER_S = 300       # flood reads started per second
SETTLE_S = 2.0
SAMPLE_S = 0.5
BG_TIMEOUT_S = 600     # a flood read waits its turn in the lane: up to reads / (2 x Creators / BG_OF_S)
PROBES = 3
CHATS = "GET /api2/v2/chats"
KINDS = ("open", "send", "me")

C_LOGIN = "every chatter signed in with its own login"
C_FLOOD = ("every background read answered 200 (none dropped); the flood held >= 90% of its reads in flight "
           "while the flood leg's taps ran")
C_OF = ("OnlyFans saw exactly one chat-list call per background read (its offset), exactly one send per send "
        "tap (its text), and per leg no more message reads than opens, at least one per (Creator, fan) opened")
C_WIRE = "lib/of_wire.py saw only signed calls it models"


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    of_sessions.seed(w, w.data["creators"])
    main = w.data["agencies"][0]["user_id"]
    aids = [c["id"] for c in w.data["creators"] if c["owner"] == main]
    fake = ctx.of_wire
    # OF closes idle keep-alives (as a real server does): bounds the relay's parked curl connections
    # (one per account x worker thread) by recent use, so the admission-in-thread fault run finishes
    # instead of parking ~12k connections into the socket guard (lib/bounded_server.py)
    fake._srv.idle_close_s = float(ctx.param("of_idle_close_s", OF_IDLE_CLOSE_S))
    bg_of_s = float(ctx.param("bg_of_s", BG_OF_S))
    n = max(1, ctx.users)
    per_user = min(PER_USER, len(aids))
    bg_per = int(ctx.param("bg_per_creator", BG_PER_CREATOR))
    think = (int(ctx.param("think_lo_ms", THINK_MS[0])), int(ctx.param("think_hi_ms", THINK_MS[1])))
    assign = [[aids[(k * per_user + j) % len(aids)] for j in range(per_user)] for k in range(n)]
    fans = {a: [f["id"] for f in w.data["fans"][a]] for a in aids}
    n_flood = n * per_user * bg_per
    ctx.metric("load", {"chatters": n, "creators": len(aids), "per_chatter": per_user, "bg_per_creator": bg_per,
                        "flood_reads_in_flight": n_flood, "bg_of_s": bg_of_s, "bg_jitter": float(ctx.param("bg_jitter", BG_JITTER)), "think_ms": list(think)})

    # ── chatters: real invites, own logins ──
    t0 = time.time()
    seeded = await chatters.seed(w, ctx.owner, main, [f"ra{k:03d}" for k in range(n)], account_ids=assign)
    base = str(ctx.owner.c.base_url)
    gate = asyncio.Semaphore(16)

    async def login(c: dict) -> Http | None:
        h = Http(base, ctx.rec, limits=16)
        async with gate:
            try:
                r = await h.post("/chatter/login", json={"username": c["username"], "password": c["password"]})
            except httpx.HTTPError:
                return None
        return h if r.status_code == 200 else None

    taps_http = await asyncio.gather(*(login(c) for c in seeded))
    ctx.metric("chatters_s", round(time.time() - t0, 1))
    ctx.check(C_LOGIN, all(taps_http), signed_in=sum(1 for h in taps_http if h), want=n)
    if not all(taps_http):
        return
    flood_http = []
    for h in taps_http:
        f = Http(base, ctx.rec, limits=per_user * bg_per + 4, prefix="bg ")
        f.c.cookies = h.c.cookies
        f.c.timeout = httpx.Timeout(BG_TIMEOUT_S)
        flood_http.append(f)

    # ── probe: a user read of a key a background read holds in flight ──
    owner_bg, owner_user = ctx.owner.share(limits=PROBES), ctx.owner.share(limits=PROBES)

    async def probe(i: int, aid: str) -> dict:
        path = f"/api/of/v2/chats?limit=10&offset=0&query=slopprobe{i}x{int(t0)}"
        with fake.lock:
            fake.hold[(aid, CHATS)] = [PROBE_HOLD_S]
        b0 = time.perf_counter()
        bg = asyncio.create_task(owner_bg.get(path, headers={"X-Account-Id": aid, "X-Priority": "background"}))
        on_wire = False
        for _ in range(250):  # until OF has the held call (the hold popped)
            with fake.lock:
                if not fake.hold.get((aid, CHATS)):
                    on_wire = True
                    break
            await asyncio.sleep(0.02)
        u0 = time.perf_counter()
        ru = await owner_user.get(path, headers={"X-Account-Id": aid})
        user_s = time.perf_counter() - u0
        rb = await bg
        return {"aid": aid, "on_wire": on_wire, "user_s": round(user_s, 3), "user_status": ru.status_code,
                "bg_s": round(time.perf_counter() - b0, 3), "bg_status": rb.status_code}

    ctx.rec.stage = "probe"
    probes = await asyncio.gather(*(probe(i, a) for i, a in enumerate(aids[:PROBES])))
    ctx.rec.stage = None
    for h in (owner_bg, owner_user):
        await h.aclose()
    ctx.check(C_PROBE, all(p["on_wire"] and p["user_status"] == 200 and p["bg_status"] == 200
                           and p["user_s"] < PROBE_MAX_S and p["bg_s"] >= PROBE_HOLD_S for p in probes),
              probes=probes, probe_max_s=PROBE_MAX_S, probe_hold_s=PROBE_HOLD_S)

    # ── taps ──
    taps: list[dict] = []

    async def tap(http: Http, leg: str, kind: str, aid: str, k: int) -> None:
        fan = fans[aid][k % len(fans[aid])]
        hdr = {"X-Account-Id": aid}
        text = f"slop-ra {leg} u{k} {aid}"
        t = time.perf_counter()
        try:
            if kind == "open":
                r = await http.get(f"/api/of/v2/chats/{fan}/messages?limit=10", headers=hdr)
            elif kind == "send":
                r = await http.post(f"/api/of/v2/chats/{fan}/messages", headers=hdr, json={"text": text})
            else:
                r = await http.get("/api/of/v2/users/me", headers=hdr)
            st = r.status_code
            body = r.json() if st == 200 else None
        except Exception:  # noqa: BLE001  transport error: recorded as 599 by the client too
            st, body = 599, None
        ms = (time.perf_counter() - t) * 1000
        ok = st == 200 and (kind != "me" or str((body or {}).get("id")) == aid)
        taps.append({"leg": leg, "kind": kind, "aid": aid, "fan": fan, "text": text, "status": st, "ok": ok,
                     "ms": ms})

    async def chatter_taps(k: int, leg: str) -> None:
        rng = random.Random(f"{ctx.seed}-{leg}-{k}")
        await asyncio.sleep(rng.uniform(0, think[1]) / 1000)
        for aid in assign[k]:
            for kind in KINDS:
                await tap(taps_http[k], leg, kind, aid, k)
                await asyncio.sleep(rng.uniform(*think) / 1000)

    async def leg(name: str) -> tuple[float, float]:
        ctx.rec.stage = name
        a = time.time()
        await asyncio.gather(*(chatter_taps(k, name) for k in range(n)))
        ctx.rec.stage = None
        return a, time.time()

    fake.route_s[CHATS] = bg_of_s  # from here on: the probe's user read is OF's usual 50 ms
    fake.route_jitter = float(ctx.param("bg_jitter", BG_JITTER))
    of0 = len(fake.calls)
    base_win = await leg("baseline")

    # ── flood + sampler ──
    stop, sampling = asyncio.Event(), asyncio.Event()
    offsets = itertools.count(1)
    flood: list[tuple[str, int, int]] = []  # (aid, offset, status)
    live = {"in_flight": 0, "issued": 0}
    phase = {"now": "ramp"}
    samples: list[dict] = []
    stats_http = ctx.owner.share(limits=2)

    async def slot(http: Http, aid: str, delay: float) -> None:
        await asyncio.sleep(delay)
        while not stop.is_set():
            o = next(offsets)
            live["in_flight"] += 1
            live["issued"] += 1
            try:
                r = await http.get(f"/api/of/v2/chats?limit=10&offset={o}&refresh=1",
                                   headers={"X-Account-Id": aid, "X-Priority": "background"})
                st = r.status_code
            except Exception:  # noqa: BLE001
                st = 599
            live["in_flight"] -= 1
            flood.append((aid, o, st))

    async def sampler() -> None:
        while not sampling.is_set():
            t = time.time()
            try:
                r = await stats_http.get("/admin/priority-lanes/stats")
                if r.status_code == 200:
                    d = r.json()
                    accts = d.get("accounts") or {}
                    samples.append({
                        "t": t, "phase": phase["now"], "flood_in_flight": live["in_flight"],
                        "threads_waiting": d["overall"]["threads_waiting_background"],
                        "threads_waiting_max_creator": max((a["threads_waiting_background"] for a in accts.values()),
                                                           default=0),
                        "loop_waiting": d["overall"]["loop_waiting_background"],
                        "bg_in_flight": d["overall"]["bg_in_flight"]})
            except httpx.HTTPError:
                pass
            try:
                await asyncio.wait_for(sampling.wait(), SAMPLE_S)
            except asyncio.TimeoutError:
                pass

    # The relay's threads and DB pool, from lib/procmon.py's 1 s samples (ps + /__slop/loop-cpu), ramp to
    # drain. A sample past the bound (DB connections over pool_size + max spill, threads over THREADS_MAX)
    # stops the flood at once, so an unbounded pool goes red here, not at the gate's thread guard.
    threads_max = int(ctx.param("threads_max", THREADS_MAX.get(ctx.scale, THREADS_MAX["medium"])))
    pool = {"samples": 0, "threads_max": 0, "db_peak": 0, "size": None, "max_overflow": None, "spills": [],
            "capped": [], "tripped": None}
    # Socket fds of the relay (lib/relay.py) + this process (the clients and the fake OF), as the gate's
    # socket guard counts them: past SOCKETS_TRIP the flood leg is cut short and the flood dropped, so a
    # fault that blocks every worker thread (one curl handle per account x thread) ends with its taps red
    # instead of in the guard (INFRA)
    sockets_trip = int(ctx.param("sockets_trip", SOCKETS_TRIP.get(ctx.scale, SOCKETS_TRIP["medium"])))
    socks = {"max": 0, "tripped": None}
    socket_samples: list[dict] = []
    abort = asyncio.Event()

    def endpoint_count(inventory: dict, *, local: int | None = None, peer: int | None = None) -> int:
        return sum(e["count"] for e in inventory["endpoints"]
                   if (local is None or e["local_port"] == local)
                   and (peer is None or e["peer_port"] == peer)
                   and e["peer_port"] is not None)

    def client_pool_state(handles: list[Http]) -> dict:
        active = idle = other = 0
        for h in handles:
            for conn in h.c._transport._pool.connections:
                if conn.is_idle():
                    idle += 1
                elif not conn.is_closed():
                    active += 1
                else:
                    other += 1
        return {"active": active, "idle": idle, "other": other}

    async def socket_sampler() -> None:
        relay_port = ctx.owner.c.base_url.port
        of_port = fake._srv.server_address[1]
        while not sampling.is_set():
            snapshot_started = time.perf_counter()
            try:
                local, response = await asyncio.gather(
                    asyncio.to_thread(socket_endpoints, {relay_port, of_port}),
                    ctx.mon.http.get(f"/__slop/socket-inventory?port={relay_port}&port={of_port}"))
                remote = response.json()
                fake_in = endpoint_count(local, local=of_port)
                fake_parked = max(0, len(fake._srv._sel.get_map()) - 1)
                socket_samples.append({
                    "phase": phase["now"], "elapsed_s": round(time.perf_counter() - snapshot_started, 3),
                    "in_flight": live["in_flight"],
                    "client_total": local["total"], "relay_total": remote["total"],
                    "client_to_relay": endpoint_count(local, peer=relay_port),
                    "relay_from_client": endpoint_count(remote, local=relay_port),
                    "relay_to_of": endpoint_count(remote, peer=of_port),
                    "fake_from_relay": fake_in, "fake_parked": fake_parked,
                    "fake_active_estimate": max(0, fake_in - fake_parked),
                    "fake_idle_closed": fake._srv.idle_closed,
                    "flood_client_pool": client_pool_state(flood_http),
                    "tap_client_pool": client_pool_state(taps_http),
                })
            except Exception as exc:  # diagnostic; the scenario's checks still decide the verdict
                socket_samples.append({"phase": phase["now"], "error": f"{type(exc).__name__}: {exc}"})
            try:
                await asyncio.wait_for(sampling.wait(), 5)
            except asyncio.TimeoutError:
                pass

    async def pool_watch() -> None:
        i = 0
        while not sampling.is_set():
            ss = ctx.mon.samples if getattr(ctx, "mon", None) else []
            for s in ss[i:]:
                db = s.get("db") or {}
                pool["samples"] += 1
                th, peak = s.get("threads") or 0, db.get("out_peak") or 0
                pool["threads_max"], pool["db_peak"] = max(pool["threads_max"], th), max(pool["db_peak"], peak)
                pool["size"], pool["max_overflow"] = db.get("size"), db.get("max_overflow")
                if db.get("holders"):  # SLOP_DB_HOLDERS=1 (lib/relay.py): diagnostic only
                    pool["holders_last"] = db["holders"]
                    if peak >= pool["db_peak"]:
                        pool["holders_at_peak"] = db["holders"]["out_now"]
                for k in ("spills", "capped"):
                    if db.get(k) is not None:
                        pool[k].append(db[k])
                mo = pool["max_overflow"]
                trip_db = (pool["size"] or 0) + (mo if mo is not None and mo >= 0 else DB_TRIP_UNBOUNDED)
                if pool["tripped"] is None and (th > threads_max or peak > trip_db):
                    pool["tripped"] = {"phase": phase["now"], "threads": th, "db_out_peak": peak, "trip_db": trip_db}
                    stop.set()
                    abort.set()
                if db.get("sockets") is not None:
                    both = db["sockets"] + (socket_fds() or 0)
                    socks["max"] = max(socks["max"], both)
                    if socks["tripped"] is None and both > sockets_trip:
                        socks["tripped"] = {"phase": phase["now"], "sockets": both, "relay": db["sockets"],
                                            "trip": sockets_trip}
                        stop.set()
                        abort.set()
            i = len(ss)
            try:
                await asyncio.wait_for(sampling.wait(), 0.25)
            except asyncio.TimeoutError:
                pass

    sam = asyncio.create_task(sampler())
    watch = asyncio.create_task(pool_watch())
    socket_watch = asyncio.create_task(socket_sampler())
    ctx.rec.stage = "ramp"
    slots = [(flood_http[k], aid) for k in range(n) for aid in assign[k] for _ in range(bg_per)]
    order = list(range(len(slots)))
    random.Random(ctx.seed).shuffle(order)
    tasks = [asyncio.create_task(slot(*slots[i], j / RAMP_PER_S)) for j, i in enumerate(order)]
    await asyncio.sleep(len(slots) / RAMP_PER_S + SETTLE_S)
    phase["now"] = "flood"
    f0 = time.time()
    flood_leg, aborted = asyncio.create_task(leg("flood")), asyncio.create_task(abort.wait())
    await asyncio.wait({flood_leg, aborted}, return_when=asyncio.FIRST_COMPLETED)
    if flood_leg.done():
        flood_win = flood_leg.result()
    else:  # cut short (fds or pool trip): the taps so far are the leg; the rest are never sent
        flood_leg.cancel()
        await asyncio.gather(flood_leg, return_exceptions=True)
        flood_win = (f0, time.time())
    aborted.cancel()
    phase["now"] = "drain"
    stop.set()
    ctx.rec.stage = "drain"
    d0 = time.time()
    if abort.is_set():  # the flood is dropped, not drained: its reads keep the relay's threads (and fds)
        for t in tasks:
            t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    ctx.rec.stage = None
    drain_s = time.time() - d0
    sampling.set()
    await sam
    await watch
    await socket_watch
    final = (await stats_http.get("/admin/priority-lanes/stats")).json()
    await stats_http.aclose()
    for h in (*taps_http, *flood_http):
        await h.aclose()
    with fake.lock:
        of_calls = list(fake.calls[of0:])
        sends = {a: list(v) for a, v in fake.sends.items()}

    # ── checks ──
    bad_taps = Counter((t["leg"], t["kind"], t["status"]) for t in taps if not t["ok"])
    ctx.check(C_TAPS, len(taps) == 2 * n * per_user * len(KINDS) and not bad_taps, taps=len(taps),
              want=2 * n * per_user * len(KINDS), not_ok={" ".join(map(str, k)): v for k, v in bad_taps.items()})

    tap_samples = [s for s in samples if s["phase"] == "flood"]
    held = min((s["flood_in_flight"] for s in tap_samples), default=0)
    fbad = Counter(st for _, _, st in flood if st != 200)
    ctx.check(C_FLOOD, len(flood) == live["issued"] and not fbad and held >= 0.9 * n_flood,
              reads=len(flood), issued=live["issued"], not_200=dict(fbad), min_in_flight_during_taps=held,
              want_in_flight=n_flood)

    # OF: one chat-list call per background read, by its (unique) offset
    chat_calls = Counter((c["account"], (parse_qs(c.get("query") or "").get("offset") or [""])[0])
                         for c in of_calls if c["route"] == CHATS)
    flood_keys = {(a, str(o)) for a, o, _ in flood}
    flood_off = {o for _, o in flood_keys}
    off_wrong = [f"{a} {o}: {chat_calls.get((a, str(o)), 0)}" for a, o, st in flood
                 if st == 200 and chat_calls.get((a, str(o)), 0) != 1]
    strays = sum(v for k, v in chat_calls.items() if k[1] in flood_off and k not in flood_keys)
    send_wrong = []
    sent_texts = Counter((a, str(s["fan_id"]), re.sub(r"<[^>]+>", "", s.get("text") or ""))
                         for a, v in sends.items() for s in v)  # OF web's <p>
    for t in taps:
        key = (t["aid"], str(t["fan"]), t["text"])
        if t["kind"] == "send" and t["status"] == 200 and sent_texts.get(key, 0) != 1:
            send_wrong.append(f"{key}: {sent_texts.get(key, 0)}")
    msg_route = "GET /api2/v2/chats/{id}/messages"
    open_wrong = {}
    for name, (a, b) in (("baseline", base_win), ("flood", flood_win)):
        opens = [t for t in taps if t["leg"] == name and t["kind"] == "open"]
        reads = [c for c in of_calls if c["route"] == msg_route and a <= c["t"] <= b + 5]
        requested = {(t["aid"], str(t["fan"])) for t in opens}
        fetched = {(c["account"], c["path"].split("/")[-2]) for c in reads}
        if len(reads) > len(opens) or requested != fetched:
            open_wrong[name] = {"opens": len(opens), "of_reads": len(reads),
                                "missing": sorted(requested - fetched), "unexpected": sorted(fetched - requested)}
    ctx.check(C_OF, not off_wrong and not strays and not send_wrong and not open_wrong,
              flood_reads=len(flood), off=off_wrong[:8], n_off=len(off_wrong), strays=strays,
              send_wrong=send_wrong[:8], n_send_wrong=len(send_wrong), opens=open_wrong)
    ctx.check(C_WIRE, fake.unsigned == 0 and not fake.unmodelled, unsigned=fake.unsigned,
              unmodelled=dict(fake.unmodelled))

    p95 = {}
    for name in ("baseline", "flood"):
        rows = [t["ms"] for t in taps if t["leg"] == name]
        p95[name] = {"all": pct(rows) or 0.0, **{k: pct([t["ms"] for t in taps if t["leg"] == name and t["kind"] == k]) or 0.0
                                          for k in KINDS}}
    over = {k: {"baseline": p95["baseline"][k], "flood": p95["flood"][k],
                "limit": round(P95_RATIO * p95["baseline"][k] + P95_SLACK_MS, 1)}
            for k in ("all", *KINDS)}
    ctx.check(C_TAP_P95, all(v["flood"] <= v["limit"] for v in over.values()), p95_ms=over)

    flood_samples = [s for s in samples if s["phase"] in ("ramp", "flood", "drain")]
    tw = [s for s in flood_samples if s["threads_waiting"] or s["threads_waiting_max_creator"]]
    ctx.check(C_NO_THREAD_WAIT, len(flood_samples) >= 5 and not tw, samples=len(flood_samples),
              nonzero=len(tw), max_threads_waiting=max((s["threads_waiting"] for s in flood_samples), default=0),
              first_nonzero=tw[:3])

    accts = {a: final["accounts"].get(a, {}) for a in aids}
    peaks = {a: st.get("bg_in_flight_peak", 0) for a, st in accts.items()}
    ctx.check(C_BG_CAP, max(peaks.values()) == BG_CAP and all(v <= BG_CAP for v in peaks.values()),
              over={a: v for a, v in peaks.items() if v > BG_CAP}, max_peak=max(peaks.values()),
              cap=final.get("cap_background"))

    mo, size = pool["max_overflow"], pool["size"]
    bound = size + mo if size is not None and mo is not None and mo >= 0 else None
    pool_detail = {"samples": pool["samples"], "threads_max": pool["threads_max"], "threads_limit": threads_max,
                   "db_out_peak": pool["db_peak"], "pool_size": size, "max_spill": mo, "db_bound": bound,
                   "spills": pool["spills"][-1] - pool["spills"][0] if pool["spills"] else None,
                   "capped": pool["capped"][-1] - pool["capped"][0] if pool["capped"] else None,
                   "tripped": pool["tripped"]}
    ctx.check(C_POOL, pool["samples"] >= 5 and bound is not None and pool["db_peak"] <= bound
              and pool["threads_max"] <= threads_max and pool["tripped"] is None, **pool_detail)

    # ── metrics ──
    ctx.metric("run_sockets", socks)
    ctx.metric("socket_lifecycle", socket_samples)
    ctx.metric("of_idle_closed", fake._srv.idle_closed)
    ctx.metric("relay_pool", {**pool_detail, **{k: pool[k] for k in ("holders_last", "holders_at_peak") if k in pool}})
    ctx.metric("tap_p95_ms", p95)
    ctx.metric("p95_vs_last_green", {f"flood {k}": p95["flood"][k] for k in ("all", *KINDS)})
    ctx.metric("p95_vs_last_green_n", {f"flood {k}": sum(1 for t in taps if t["leg"] == "flood"
                                                         and (k == "all" or t["kind"] == k)) for k in ("all", *KINDS)})
    ctx.metric("flood", {"reads": len(flood), "drain_s": round(drain_s, 1), "min_in_flight_during_taps": held,
                         "of_chat_calls": sum(chat_calls.values())})
    ctx.metric("lane_samples", {
        "n": len(flood_samples),
        "loop_waiting_max": max((s["loop_waiting"] for s in flood_samples), default=0),
        "threads_waiting_max": max((s["threads_waiting"] for s in flood_samples), default=0),
        "bg_in_flight_max": max((s["bg_in_flight"] for s in flood_samples), default=0)})
    o = final["overall"]
    ctx.metric("lanes_final", {k: o.get(k) for k in (
        "calls", "calls_user", "calls_background", "blocked_total", "blocked_background", "wait_s_avg_blocked",
        "wait_s_max", "loop_waiting_background_peak", "threads_waiting_background_peak")})
    ctx.metric("probes", probes)
    ctx.note("tap p95 ms baseline -> flood (limit): " + ", ".join(
        f"{k} {v['baseline']} -> {v['flood']} ({v['limit']})" for k, v in over.items()))
    ctx.note(f"flood: {n_flood} background reads in flight ({n} chatters x {per_user} Creators x {bg_per}), "
             f"{len(flood)} answered, drain {drain_s:.0f} s; lane samples {len(flood_samples)}, loop-waiting max "
             f"{max((s['loop_waiting'] for s in flood_samples), default=0)}, threads-waiting max "
             f"{max((s['threads_waiting'] for s in flood_samples), default=0)}")
    ctx.note("probe user read s (bg twin s): " + ", ".join(f"{p['user_s']} ({p['bg_s']})" for p in probes))
