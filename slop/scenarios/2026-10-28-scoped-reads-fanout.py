from __future__ import annotations

import asyncio
import time
from collections import Counter

from slop.lib.client import label
from slop.lib.scope_faults import C_WRITE_SCOPE
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
    n_clients = max(1, min(ctx.users, int(ctx.param("clients", CLIENTS))))
    per_client = len(aids) * len(READS)
    ctx.metric("burst", {"clients": n_clients, "creators": len(aids), "reads_per_client": per_client,
                         "of_ms": round(fake.latency_s * 1000)})

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

    def of_sends() -> int:
        with fake.lock:
            return sum(len(v) for v in fake.sends.values())

    fan = w.data["fans"][aids[1]][0]["id"]
    s0 = of_sends()
    r = await ctx.owner.post(f"/api/of/v2/chats/{fan}/messages", json={"text": "slop write scope"})
    sent = of_sends() - s0
    detail = (r.json().get("detail") if r.status_code == 400 else None) or {}
    ctx.check(C_WRITE_SCOPE, r.status_code == 400 and detail.get("error") == "account_required" and sent == 0,
              http_status=r.status_code, error=detail.get("error"), of_sends=sent, creators=len(aids))

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
