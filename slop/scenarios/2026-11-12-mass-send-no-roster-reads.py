"""A list-audience mass send reads no OF roster (the Audience crawl is gone, docs/spec/phase-02-audience-crawl.md,
superseded 2026-11-12): who received it is assumed from the run's own `audience_filter`, never paged off OF's fans /
following after the send.

World: `flat_agency` (CREATORS: small 6 / medium 20), each with a captured session: the relay's REAL OFClient
against lib/of_wire.py (`OF_WIRE`). Each Creator's GUARD_N guard fans are drawn from its seeded fans.

Drive: `--users` mass sends (`user_lists ["fans", "following"]`, the Creator's guard in `excluded_users`, which the
send's Auto_Exclude sync puts on OF's list), round-robin over the Creators, every Creator's sends SPACING_S apart
(past of_write's 11 s per-Creator gap) from a seeded offset, kinds alternating: the real automation enqueue
(`POST /admin/automation/enqueue` send_mass_message, then `/__slop/run-automation {claim: true}`: the product's claim,
run slot and run_once) and the composer's real `POST /api/of/v2/messages/queue`. Then QUIET_S with no driven call (a
background read a send spawned would land here).

Checks:
  NO_ROSTER_READS  zero `GET /api2/v2/subscriptions/subscribers|subscribes` calls on the wire from the first send to
                   the end of the quiet window (nothing else in this stack reads a roster: no supervisor, no
                   thresholded or Priority send).
  SENDS_RECORDED   every planned send answered 200 with a mass run; every run `ok` with OF's queue id, that id one
                   OF accepted for that Creator with the send's text; its `audience_filter` keeps the guard in
                   `excluded_users`; one OF accept per send (nothing dropped, nothing doubled).
  no 5xx (stock, and named on the two send routes), P95_VS_LAST over the two send routes.

Bypasses (declared): OF at its wire (lib/of_wire.py: 50 ms a call, empty rosters); the supervisor's cadence (a driver
per Creator claims its send right after the enqueue); seeding by SQL (flat_agency); the users and the sends are httpx
clients on the routes (no browser).
Break-it-once: mass-send-reads-roster (every OF mass send followed by one fans and one following page, the crawl's
bug class): NO_ROSTER_READS only.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import Counter

import httpx

from slop.lib.client import Recorder

PROFILE = "flat_agency"
UI = False
OF_WIRE = True
FAULT = "mass-send-reads-roster"
CREATORS = {"small": 6, "medium": 20, "huge": 20}
GUARD_N = 5
SPACING_S = 12.0              # > of_write._OF_WRITE_GAP_S (11)
QUIET_S = 8.0                 # after the last send: a spawned background read lands inside it
P95_VS_LAST = (1.5, 300)
P95_VS_LAST_MIN_N = 8
TEXT = "slop no roster reads {}"
QUEUE = "/api/of/v2/messages/queue"
ENQUEUE = "/admin/automation/enqueue"
ROSTERS = ("/api2/v2/subscriptions/subscribers", "/api2/v2/subscriptions/subscribes")
WIRE_QUEUE = "POST /api2/v2/messages/queue"

NO_ROSTER_READS = "no_roster_reads"
SENDS_RECORDED = "sends_recorded"
NO_5XX = "no_5xx_sends"


def _q(w, sql: str, args=()) -> list[tuple]:
    con = w.sql()
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


async def run(ctx) -> None:
    w, fake = ctx.world, ctx.of_wire
    w.data["flat_creators"] = CREATORS.get(ctx.scale, CREATORS["small"])
    await ctx.build(PROFILE)
    creators = {str(c["id"]): c for c in w.data["creators"]}
    cs = list(creators)
    rng = w.rng("scenario:mass-send-no-roster-reads")
    fans = {a: [int(f["id"]) for f in w.data["fans"][a]] for a in cs}
    guard = {a: sorted(rng.sample(fans[a], GUARD_N)) for a in cs}

    # ── the plan: per Creator, its sends SPACING_S apart from a seeded offset, kinds alternating ──
    per: dict[str, list[dict]] = {a: [] for a in cs}
    for k in range(max(1, ctx.users)):
        per[cs[k % len(cs)]].append({})
    plan: list[dict] = []
    for ci, aid in enumerate(cs):
        off = rng.uniform(0, SPACING_S)
        for k, p in enumerate(per[aid]):
            p.update(aid=aid, kind="auto" if (k + ci) % 2 == 0 else "composer", at=off + k * SPACING_S,
                     text=TEXT.format(len(plan)))
            plan.append(p)
    ctx.metric("plan", {"sends": len(plan), "creators": len(cs), "load_s": round(max(p["at"] for p in plan), 1),
                        "kinds": dict(Counter(p["kind"] for p in plan))})

    send_http = ctx.owner.share(limits=min(200, len(cs) * 2 + 8))
    hook = ctx.owner.share(rec=Recorder(), limits=min(200, len(cs) + 4))

    async def auto_send(p: dict) -> None:
        r = await send_http.post(ENQUEUE, json={"account_id": p["aid"], "kind": "send_mass_message", "payload": {
            "text": p["text"], "user_lists": ["fans", "following"], "excluded_users": guard[p["aid"]],
            "exclude_replied_hours": 0, "exclude_inbound_hours": 0}})
        p["http"] = r.status_code
        if r.status_code != 200:
            return
        res: dict = {}
        for _ in range(600):
            r = await hook.post("/__slop/run-automation", timeout=900, json={
                "account_id": p["aid"], "kind": "send_mass_message", "claim": True})
            res = (r.json().get("result") or {}) if r.status_code == 200 else {}
            if res.get("reason") not in ("in_flight", "no_job"):
                break
            await asyncio.sleep(0.1)
        p["result"] = {k: res.get(k) for k in ("status", "reason", "mass_run_id")}
        if res.get("mass_run_id"):
            p["mass_run_id"] = int(res["mass_run_id"])

    async def composer_send(p: dict) -> None:
        r = await send_http.post(QUEUE, headers={"X-Account-Id": p["aid"]}, json={
            "text": p["text"], "user_lists": ["fans", "following"], "excluded_users": guard[p["aid"]]})
        p["http"] = r.status_code
        if r.status_code == 200 and r.json().get("_mass_run_id"):
            p["mass_run_id"] = int(r.json()["_mass_run_id"])

    async def creator(aid: str, t0: float) -> None:
        for p in per[aid]:
            await asyncio.sleep(max(0.0, t0 + p["at"] - time.monotonic()))
            try:
                await (auto_send(p) if p["kind"] == "auto" else composer_send(p))
            except httpx.HTTPError as e:      # recorded (599): the stock transport check
                p["error"] = repr(e)[:200]

    with fake.lock:
        n_calls0 = len(fake.calls)
    ctx.rec.stage = "load"
    t0 = time.monotonic()
    await asyncio.gather(*(creator(a, t0) for a in cs))
    ctx.rec.stage = None
    await asyncio.sleep(QUIET_S)
    await send_http.aclose()

    # ── NO_ROSTER_READS: the wire from the first send to the end of the quiet window ──
    with fake.lock:
        calls = list(fake.calls[n_calls0:])
        accepted = {a: [dict(e) for e in es] for a, es in fake.queue.items()}
    rosters = [c for c in calls if c["path"] in ROSTERS]
    ctx.check(NO_ROSTER_READS, not rosters, wire_calls=len(calls), roster_calls=len(rosters),
              by_creator=dict(Counter(c["account"] for c in rosters)),
              first=[{k: c[k] for k in ("account", "path", "query", "status")} for c in rosters[:5]])

    # ── SENDS_RECORDED: each send a run OF accepted, the guard kept in its audience_filter ──
    ids = [p["mass_run_id"] for p in plan if p.get("mass_run_id")]
    rows = {int(r[0]): r for r in (await asyncio.to_thread(
        _q, w, f"SELECT id, account_id, status, queue_id, audience_filter FROM mass_runs "
               f"WHERE id IN ({','.join('?' * len(ids))})", ids) if ids else [])}
    qtext = {(a, int(e["id"])): str(e.get("text") or "") for a, es in accepted.items() for e in es}
    excluded: dict[int, set[int]] = {}
    bad = []
    for p in plan:
        mid = p.get("mass_run_id")
        row = rows.get(mid) if mid else None
        why = None
        if p.get("http") != 200 or row is None:
            why = "no run"
        elif row[2] != "ok" or row[3] is None:
            why = f"status={row[2]} queue_id={row[3]}"
        elif p["text"] not in qtext.get((p["aid"], int(row[3])), ""):
            why = "queue id not accepted by OF with this text"
        else:
            try:
                excluded[mid] = {int(x) for x in (json.loads(row[4] or "{}").get("excluded_users") or [])}
            except (TypeError, ValueError):
                excluded[mid] = set()
            if not set(guard[p["aid"]]) <= excluded[mid]:
                why = "guard missing from audience_filter.excluded_users"
        if why:
            bad.append({"aid": p["aid"][-4:], "kind": p["kind"], "http": p.get("http"), "run": mid,
                        "result": p.get("result"), "error": p.get("error"), "why": why})
    ours = Counter(a for (a, _), t in qtext.items() if TEXT.format("") in t)   # this run's accepts per Creator
    doubled = {a[-4:]: (ours[a], len(per[a])) for a in cs if ours[a] != len(per[a])}
    ctx.check(SENDS_RECORDED, bool(plan) and not bad and not doubled, sends=len(plan), runs=len(rows),
              bad=bad[:10], accepts_vs_planned=doubled)

    # ── no 5xx on the two send routes; p95 vs last green ──
    summ = ctx.rec.summary("load")
    sends = {k: v for k, v in summ.items() if k in (f"POST {QUEUE}", f"POST {ENQUEUE}")}
    ctx.check(NO_5XX, bool(sends) and not any(v["5xx"] for v in sends.values()),
              routes={k: {"n": v["n"], "5xx": v["5xx"]} for k, v in sends.items()})
    ctx.metric("p95_vs_last_green", {k: v["p95_ms"] for k, v in sends.items()})
    ctx.metric("p95_vs_last_green_n", {k: v["n"] for k, v in sends.items()})

    await hook.aclose()
    ctx.metric("roster_calls_per_send", round(len(rosters) / max(1, len(plan)), 3))
