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
P95_VS_LAST = (1.5, 100)
P95_VS_LAST_MIN_N = 200
BG_CAP = 2  # service/server.py _ACCOUNT_LANE_BACKGROUND (default)
# Owner accepted ~2k threads at medium/200 (scale = more boxes), so 3000. Still red there: the relay grew to 3477 threads, its DB pool spilling one aiosqlite thread per overflow connection (service/db/engine.py _SpillQueuePool).
MAX_THREADS_PROC = {"medium": 3000}
# The flood keeps ~10.4k reads in flight (16k-31k fds at medium/200) and ran the Mac's ephemeral ports dry; medium/120+ run exclusive and only they get this ceiling.
MAX_SOCKETS_RUN = {"medium": 26000}
THREADS_MAX = {"small": 400, "medium": 1000}  # measured max small 134, medium 417-512, uncapped 3477
SOCKETS_TRIP = {"small": 7600, "medium": 25500}  # medium: no-fault medium/200 ramp reached 24289
DB_TRIP_UNBOUNDED = 120
from slop.lib.latency_acceptance import latency_check

# Catches blocking (a fault puts tap p95 at 10-30 s), not host jitter: no-fault flood p95 spread 85-140 ms across runs on the shared machine, so 1.25x + 50 ms flipped on noise.
P95_RATIO, P95_SLACK_MS = 2.0, 100
PROBE_HOLD_S, PROBE_MAX_S = 3.0, 1.0
PER_USER = 13
BG_PER_CREATOR = 4
OF_IDLE_CLOSE_S = 5.0  # synthetic server idle lifetime; not a measured OF edge value
BG_OF_S = 1.5
BG_JITTER = 0.5  # load-bearing: at a fixed BG_OF_S every lane stays in phase and the answer waves become the p95 tail
THINK_MS = (500, 1500)
RAMP_PER_S = 300
SETTLE_S = 2.0
SAMPLE_S = 0.5
BG_TIMEOUT_S = 600
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

    owner_bg, owner_user = ctx.owner.share(limits=PROBES), ctx.owner.share(limits=PROBES)

    async def probe(i: int, aid: str) -> dict:
        path = f"/api/of/v2/chats?limit=10&offset=0&query=slopprobe{i}x{int(t0)}"
        with fake.lock:
            fake.hold[(aid, CHATS)] = [PROBE_HOLD_S]
        b0 = time.perf_counter()
        bg = asyncio.create_task(owner_bg.get(path, headers={"X-Account-Id": aid, "X-Priority": "background"}))
        on_wire = False
        for _ in range(250):
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

    fake.route_s[CHATS] = bg_of_s
    fake.route_jitter = float(ctx.param("bg_jitter", BG_JITTER))
    of0 = len(fake.calls)
    base_win = await leg("baseline")

    stop, sampling = asyncio.Event(), asyncio.Event()
    offsets = itertools.count(1)
    flood: list[tuple[str, int, int]] = []
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

    threads_max = int(ctx.param("threads_max", THREADS_MAX.get(ctx.scale, THREADS_MAX["medium"])))
    pool = {"samples": 0, "threads_max": 0, "db_peak": 0, "size": None, "max_overflow": None, "spills": [],
            "capped": [], "tripped": None}
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
            except Exception as exc:
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
                if db.get("holders"):
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
    else:
        flood_leg.cancel()
        await asyncio.gather(flood_leg, return_exceptions=True)
        flood_win = (f0, time.time())
    aborted.cancel()
    phase["now"] = "drain"
    stop.set()
    ctx.rec.stage = "drain"
    d0 = time.time()
    if abort.is_set():
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

    ctx.metric("of_keepalive", {"idle_close_s": fake._srv.idle_close_s, "idle_closed": fake._srv.idle_closed})

    bad_taps = Counter((t["leg"], t["kind"], t["status"]) for t in taps if not t["ok"])
    ctx.check(C_TAPS, len(taps) == 2 * n * per_user * len(KINDS) and not bad_taps, taps=len(taps),
              want=2 * n * per_user * len(KINDS), not_ok={" ".join(map(str, k)): v for k, v in bad_taps.items()})

    tap_samples = [s for s in samples if s["phase"] == "flood"]
    held = min((s["flood_in_flight"] for s in tap_samples), default=0)
    fbad = Counter(st for _, _, st in flood if st != 200)
    ctx.check(C_FLOOD, len(flood) == live["issued"] and not fbad and held >= 0.9 * n_flood,
              reads=len(flood), issued=live["issued"], not_200=dict(fbad), min_in_flight_during_taps=held,
              want_in_flight=n_flood)

    chat_calls = Counter((c["account"], (parse_qs(c.get("query") or "").get("offset") or [""])[0])
                         for c in of_calls if c["route"] == CHATS)
    flood_keys = {(a, str(o)) for a, o, _ in flood}
    flood_off = {o for _, o in flood_keys}
    off_wrong = [f"{a} {o}: {chat_calls.get((a, str(o)), 0)}" for a, o, st in flood
                 if st == 200 and chat_calls.get((a, str(o)), 0) != 1]
    strays = sum(v for k, v in chat_calls.items() if k[1] in flood_off and k not in flood_keys)
    send_wrong = []
    sent_texts = Counter((a, str(s["fan_id"]), re.sub(r"<[^>]+>", "", s.get("text") or ""))
                         for a, v in sends.items() for s in v)
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
    stretch = latency_check(ctx, C_TAP_P95,
        {k: v['flood'] for k, v in over.items()},
        {k: v['limit'] for k, v in over.items()})

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

    ctx.metric("run_sockets", socks)
    ctx.metric("socket_lifecycle", socket_samples)
    ctx.metric("of_idle_closed", fake._srv.idle_closed)
    ctx.metric("relay_pool", {**pool_detail, **{k: pool[k] for k in ("holders_last", "holders_at_peak") if k in pool}})
    ctx.metric("tap_p95_ms", p95)
    if not stretch:
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
    profile = 'stretch (advisory)' if stretch else 'acceptance' if ctx.users >= 120 else 'regression'
    if ctx.users >= 120:
        for value in over.values():
            value['limit'] = 500 if stretch else 700
    ctx.note(f"tap p95 ms baseline -> flood ({profile} limit): " + ", ".join(
        f"{k} {v['baseline']} -> {v['flood']} ({v['limit']})" for k, v in over.items()))
    ctx.note(f"flood: {n_flood} background reads in flight ({n} chatters x {per_user} Creators x {bg_per}), "
             f"{len(flood)} answered, drain {drain_s:.0f} s; lane samples {len(flood_samples)}, loop-waiting max "
             f"{max((s['loop_waiting'] for s in flood_samples), default=0)}, threads-waiting max "
             f"{max((s['threads_waiting'] for s in flood_samples), default=0)}")
    ctx.note("probe user read s (bg twin s): " + ", ".join(f"{p['user_s']} ({p['bg_s']})" for p in probes))
