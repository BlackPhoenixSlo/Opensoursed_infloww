"""The shell's per-Creator scoped reads fired all at once (the phone-load work). The app now
sends every Creator-scoped relay GET (`X-Account-Id`) with `cache: "no-store"`
(app/lib/relay.ts), so Chrome no longer holds its per-URL cache lock and runs one Agency's
per-Creator reads together instead of one after another: up to ~50 at once per client, the
relay's caches cold.

The world: one Agency with 50 Creators (`one_agency`, plus its neighbour), each with a
captured session (seed/of_sessions.py), so the relay builds its REAL OFClient; OnlyFans is
lib/of_wire.py on loopback (`OF_WIRE`), answering /users/me, /chats and
/users/notifications/count. `--users` clients, at most CLIENTS (5, `--set clients=`, see the
cap below; each its own connection pool on the owner's session: a browser tab) fire, at once
and with nothing cached in the relay, what the shell and Messages Pro read per Creator: `GET /api/of/v2/users/me` (the avatar),
`GET /api/of/v2/chats?limit=25&offset=0&order=recent` (the Fan List's first page) and
`GET /api/of/v2/users/notifications/count` (the bell), for every Creator. Then the relay is
restarted (cold again) and one client reads the same set the way Chrome did before: each
of the three URLs Creator after Creator, the three URLs side by side.

Invariants: every call answered 200 (no 5xx, nothing dropped: clients x Creators x 3);
each answer is that Creator's (users/me's id); OnlyFans saw exactly one call per Creator per
read in the cold burst (single-flight: the relay's per-key lock and coalescing, so N clients
cost OF what one does); lib/of_wire.py saw only signed calls it models. Metrics: p95 per
read (the recorder's `burst` / `serial` stages) and per-client wall time, concurrent vs serial. Budget: the burst's p95 per read vs the
last green run.

Bypasses, declared: lib/of_wire.py (OnlyFans' API on loopback, its own declared bypasses), its
latency raised to OF_MS (400 ms per call, `--set of_ms=`; a guess at OF behind a residential
proxy, where lib/of_wire.py's 50 ms default lets the relay's own queueing hide a stampede);
OF's chat list and bell are empty; the clients are httpx pools with
every request in flight at once (HTTP/2's shape; Chrome on HTTP/1.1 holds 6 per origin, so
this is the worst case), not browsers; the serial pass runs after a relay restart (SIGKILL,
same DB) so its caches are cold too.

The client cap hides a measured relay cliff. CLIENTS (5) keeps the run below a cliff between
10 and 20 cold clients: 10 clients (1500 reads at once) pass (evidence
20261028T072716Z-2026-10-28-scoped-reads-fanout-c663); 20 (3000) leave 1725-2045 reads past
the client's 30 s timeout (…-0f18 and …-d1a7 at host load 225-287, and …-6729 started on a quiet
host, load 4). That is the relay's per-request path (threads ~1900-2200, DB pool spills), not
OnlyFans': single-flight held in every one of them. `--set clients=20` reproduces it.
`--users` above 5 (`slop/run all`'s 20) still runs 5 clients. Even at 5 the DB pool is the
wait: every read checks out a connection (pool_wait_n ~ reads), p95 1 s of the ~2 s read p95
(…-1000). `--scale` changes only the seeded fans and threads, which these reads never touch
(OF's chat list is empty): small and medium run the same load (…-041f vs …-1000).

Break-it-once: relay-cache-no-single-flight (each miss its own lock: users/me, whose only
guard is relay_cache's lock, reaches OF once per client).
"""
from __future__ import annotations

import asyncio
import time
from collections import Counter

from slop.lib.client import label
from slop.seed import of_sessions

PROFILE = "one_agency"
UI = False
OF_WIRE = True
FAULT = "relay-cache-no-single-flight"
P95_VS_LAST = (1.25, 50)
P95_VS_LAST_MIN_N = 200
OF_MS = 400
CLIENTS = 5

READS = {
    "users/me": ("/api/of/v2/users/me", "GET /api2/v2/users/me"),
    "chats": ("/api/of/v2/chats?limit=25&offset=0&order=recent", "GET /api2/v2/chats"),
    "notifications/count": ("/api/of/v2/users/notifications/count", "GET /api2/v2/users/notifications/count"),
}
C_ALL = "cold concurrent burst: every call answered 200 (clients x Creators x 3, no 5xx, none dropped)"
C_OWN = "cold concurrent burst: each users/me answer is the asked Creator's"
C_ONE = "cold concurrent burst: OnlyFans saw exactly one call per Creator per read (single-flight)"
C_SER = "serial pass (Chrome before no-store): every call answered 200"
C_WIRE = "lib/of_wire.py saw only signed calls it models"


async def _read(http, name: str, aid: str) -> dict:
    try:
        r = await http.get(READS[name][0], headers={"X-Account-Id": aid})
        status, body = r.status_code, (r.json() if r.status_code == 200 else None)
    except Exception:  # noqa: BLE001  transport error: recorded as 599 by the client too
        status, body = 599, None
    return {"read": name, "aid": aid, "status": status, "t1": time.perf_counter(), "body": body}


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    of_sessions.seed(w, w.data["creators"])
    main = w.data["agencies"][0]["user_id"]
    aids = [c["id"] for c in w.data["creators"] if c["owner"] == main]
    fake = ctx.of_wire
    fake.latency_s = float(ctx.param("of_ms", OF_MS)) / 1000
    n_clients = max(1, min(ctx.users, int(ctx.param("clients", CLIENTS))))  # the cap: docstring
    per_client = len(aids) * len(READS)
    ctx.metric("burst", {"clients": n_clients, "creators": len(aids), "reads_per_client": per_client,
                         "of_ms": round(fake.latency_s * 1000)})

    # ── cold concurrent burst: every client, every Creator, every read, at once ──
    clients = [ctx.owner.share(limits=per_client) for _ in range(n_clients)]
    n0 = len(fake.calls)
    ctx.rec.stage = "burst"
    t0 = time.perf_counter()

    async def client(http) -> tuple[list[dict], float]:
        rs = await asyncio.gather(*(_read(http, name, a) for a in aids for name in READS))
        return rs, max(r["t1"] for r in rs) - t0

    done = await asyncio.gather(*(client(h) for h in clients))
    ctx.rec.stage = None
    for h in clients:
        await h.aclose()
    burst = [r for rs, _ in done for r in rs]
    walls = [wall * 1000 for _, wall in done]
    with fake.lock:
        of_calls = list(fake.calls[n0:])

    bad = Counter((r["read"], r["status"]) for r in burst if r["status"] != 200)
    ctx.check(C_ALL, len(burst) == n_clients * per_client and not bad,
              calls=len(burst), want=n_clients * per_client, not_200={f"{k[0]} {k[1]}": n for k, n in bad.items()})
    wrong = [r["aid"] for r in burst if r["read"] == "users/me" and r["status"] == 200
             and str((r["body"] or {}).get("id")) != r["aid"]]
    ctx.check(C_OWN, not wrong, wrong=wrong[:5], n_wrong=len(wrong))
    per = Counter((c["account"], c["route"]) for c in of_calls)
    off = {f"{a} {name}": per.get((a, route), 0) for a in aids for name, (_, route) in READS.items()
           if per.get((a, route), 0) != 1}
    ctx.check(C_ONE, not off, creators=len(aids), off=dict(list(off.items())[:8]), n_off=len(off),
              of_calls=len(of_calls))

    # ── serial pass on a cold relay: Chrome's per-URL lock, the three URLs side by side ──
    ctx.stack.crash_relay()
    await asyncio.to_thread(ctx.stack.start_relay)
    one = ctx.owner.share(limits=len(READS))
    ctx.rec.stage = "serial"
    s0 = time.perf_counter()

    async def lane(name: str) -> list[dict]:
        return [await _read(one, name, a) for a in aids]

    serial = [r for rs in await asyncio.gather(*(lane(n) for n in READS)) for r in rs]
    serial_wall = (max(r["t1"] for r in serial) - s0) * 1000
    ctx.rec.stage = None
    await one.aclose()
    sbad = Counter((r["read"], r["status"]) for r in serial if r["status"] != 200)
    ctx.check(C_SER, len(serial) == per_client and not sbad, calls=len(serial),
              not_200={f"{k[0]} {k[1]}": n for k, n in sbad.items()})
    ctx.check(C_WIRE, fake.unsigned == 0 and not fake.unmodelled, unsigned=fake.unsigned,
              unmodelled=dict(fake.unmodelled))

    http = {stage: ctx.rec.summary(stage) for stage in ("burst", "serial")}
    ctx.metric("http_by_stage", http)
    row = {(stage, n): http[stage][label("GET", READS[n][0])] for stage in http for n in READS}
    p95 = {f"burst {n}": row["burst", n]["p95_ms"] for n in READS}
    sp95 = {f"serial {n}": row["serial", n]["p95_ms"] for n in READS}
    burst_p50 = sorted(walls)[len(walls) // 2]
    ctx.metric("p95_ms", {**p95, **sp95})
    ctx.metric("client_wall_ms", {"burst_p50": round(burst_p50, 1), "burst_max": round(max(walls), 1),
                                  "serial": round(serial_wall, 1)})
    ctx.metric("p95_vs_last_green", p95)
    ctx.metric("p95_vs_last_green_n", {f"burst {n}": row["burst", n]["n"] for n in READS})
    ctx.note(f"per-client wall: burst p50 {burst_p50:.0f} ms / max {max(walls):.0f} ms "
             f"({n_clients} clients x {per_client} reads at once) vs serial {serial_wall:.0f} ms (one client)")
    ctx.note("p95 ms, burst / serial: " + ", ".join(f"{n} {p95[f'burst {n}']} / {sp95[f'serial {n}']}"
                                                     for n in READS))
