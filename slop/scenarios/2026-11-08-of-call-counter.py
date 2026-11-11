"""The OF call counter (service/of_call_counter.py): every signed OF request the relay sends lands in
`of_call_stats.json` beside the DB, keyed by (Caller kind, "METHOD folded-path", Creator, status class),
and the file equals what OnlyFans saw, across a restart with a send in flight.

World: `flat_agency` (small 3 / medium 10 Creators), each with a captured session: the relay's REAL OFClient
against lib/of_wire.py (`OF_WIRE`). RELAY_ENV: OF_CALL_STATS_FLUSH_S=1 (prod 30), the real automation supervisor
(SLOP_SUPERVISOR=1).

Phase 1, load (LOAD_S): `--users` owners read Relay routes that reach OF for a random Creator each turn (the
Dashboard's per-Creator subscriber counts and subscribers chart, the bell's counts with `refresh=1`, the chat
list and the notifications feed), 1-3 s think. Before it every Creator's WS pump comes up on FakeOF's socket
(`/__slop/pump-supervise`: the real `_reconcile_pumps`), each connect reading `/users/me`, and the owner sends two
mass messages to `fans` + `following` on the last Creator through the composer's real `POST /api/of/v2/messages/queue`:
each hands its Audience crawl to the Creator's crawler (service/audience_crawl.py), which pages both OF rosters
inside `of_pacing.walk("audience_crawl")`. Meanwhile WALKS ledger walks: one real
`transaction_ingest.supervisor_cycle()` (lib/sweep_pacing_relay.py), every Creator walked inside
`of_pacing.walk`, with FakeOF answering Creator 0's first ledger page 429 (`throttle`: the pacer's one retry
sends it again) and every ledger page of Creator 1 500 (`fail`). Then, once the wire is quiet, the file is
read against FakeOF's calls.
Phase 2, restart mid-send: the held-send leg (lib/of_call_counter_<leg>_leg.py, below) starts an automation's mass
send for Creator 0, FakeOF holds its `POST /api2/v2/messages/queue` HOLD_S (longer than uvicorn's 5 s graceful
wait), and the relay is stopped (SIGTERM, as `docker stop`) while OF holds it: the shutdown drain finishes the send,
after the handler's first counter flush. Without a leg the relay is stopped with no send held. The file is read
with the relay down, then the relay starts again on the same temp dir and the file is read once more, quiet.

Checks:
  counts_match_wire  after phase 1, per (method, folded path, Creator, status class) the file's counts equal
                     FakeOF's `/api2/` calls, nothing dropped or extra; the wire saw a 429, its retry and a 5xx.
  callers_labelled   every driven call in the end file is under its expected Caller kind: the users' reads
                     `route:GET <Relay path>`, the ledger walk `walk:transactions` (its disputes read
                     `walk:chargebacks`), the held send its leg's KIND, the WS pumps' `/users/me` `loop:ws-pump`
                     (no Creator id), the composer's sends `route:POST /api/of/v2/messages/queue` and both
                     Audience crawls' roster pages `walk:audience_crawl` (service/audience_crawl.py); each driven one
                     seen; zero `unlabelled`.
  survives_restart   the held send (if a leg) was answered after the SIGTERM and is in the file the stopped relay left;
                     the file's counts since phase 1 equal the wire's at the stop and again after the restart
                     (quiet); the restarted relay's `boots` is the stopped one's + 1 and kept every count.
  no_5xx             no Relay route the users read answered 5xx (the stock check counts every actor call).
  p95 vs last green  (P95_VS_LAST) the users' route p95s.
Folding is the spec's rule, written again here: numeric or 16+ hex/dash segments and the segment after
`/users/` (but me, list, notifications, performers, settings) -> {}, query dropped.

Bypasses (declared): OF at its wire (lib/of_wire.py: 50 ms a call, its own declared answers; the 429 and 500
armed by the scenario); seeding by SQL (the leg's); the ledger walk's cadence (`/__slop/sweep-pacing/run`);
the users and the composer sends are httpx clients on the routes (no browser).
Break-it-once: of-counter-drops-errors (the counter skips every non-2xx answer): only counts_match_wire.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import random
import re
import time
from collections import Counter
from pathlib import Path

from slop.lib.client import Recorder

PROFILE = "flat_agency"
UI = False
OF_WIRE = True
FAULT = "of-counter-drops-errors"
RELAY_ENV = {"OF_CALL_STATS_FLUSH_S": "1", "SLOP_SUPERVISOR": "1"}
P95_VS_LAST = (1.5, 100)
P95_VS_LAST_MIN_N = 30
LOAD_S = {"small": 20.0, "medium": 40.0, "huge": 40.0}
HOLD_S = 8.0                 # the held mass send: past uvicorn's 5 s graceful wait, inside RELAY_DRAIN_S (45)
STOP_GRACE_S = 75.0          # docker-compose.yml stop_grace_period
SEND_TIMEOUT_S = 120.0
LEDGER = "GET /api2/v2/payouts/transactions"
QUEUE = "POST /api2/v2/messages/queue"
ME = "GET /api2/v2/users/me"
SUBS, FOLLOWING = "GET /api2/v2/subscriptions/subscribers", "GET /api2/v2/subscriptions/subscribes"
AUDIENCE_CRAWL = "walk:audience_crawl"   # audience_crawl's pages, inside of_pacing.walk (innermost label wins)
MASS_SENDS = 2
MASS_TIMEOUT_S = 30.0
PUMP_UP_S = 30.0
# The walk logs the 500s armed on Creator 1's ledger, and FakeOF does not model the chargebacks read (404).
EXPECTED_TRACEBACKS = (("ingest_tx_scan_failed", "500 for http"),
                       ("ingest_cb_error", "slop fake: not modelled"))

COUNTS = "counts_match_wire"
LABELS = "callers_labelled"
RESTART = "survives_restart"
# Phase 2's held send, in a leg of its own (lib/of_call_counter_<leg>_leg.py; at most one): `KIND` (the Caller kind
# its queue POST and roster reads carry), `seed(w)` (SQL, before the users) and `async start_send(owner, w, aid)`
# (starts the send, returns the evidence RESTART reports). None: phase 2 stops the relay with no send held.
_LEGS = [importlib.import_module(f"slop.lib.{m.stem}")
         for m in sorted((Path(__file__).resolve().parents[1] / "lib").glob("of_call_counter_*_leg.py"))]
assert len(_LEGS) <= 1, f"of-call-counter: one held-send leg at most, found {[m.__name__ for m in _LEGS]}"
LEG = _LEGS[0] if _LEGS else None
SENDER = {LEG.KIND} if LEG else set()
NO_5XX = "no_5xx"

# The users' reads: Relay route -> the OF read it proxies (/api/of/v2/<x> -> /api2/v2/<x>).
USER_READS = ("/api/of/v2/subscriptions/count/all", "/api/of/v2/subscriptions/subscribers/chart?by=total",
              "/api/of/v2/users/notifications/count?refresh=1", "/api/of/v2/chats?limit=10&offset=0",
              "/api/of/v2/users/notifications?limit=10&offset=0")
# OF read -> the Caller kinds its driven calls may carry; every REQUIRED (read, Caller kind) must have been seen.
CALLERS = {**{"GET /api2/v2/" + p.split("?")[0].removeprefix("/api/of/v2/"): {"route:GET " + p.split("?")[0]}
              for p in USER_READS},
           LEDGER: {"walk:transactions"}, "GET /api2/v2/payouts/chargebacks": {"walk:chargebacks"},
           QUEUE: {"route:POST /api/of/v2/messages/queue", *SENDER},
           SUBS: {AUDIENCE_CRAWL, *SENDER}, FOLLOWING: {AUDIENCE_CRAWL, *SENDER},
           ME: {"loop:ws-pump"}}
REQUIRED = ({(k, c) for k, v in CALLERS.items() for c in v if c.startswith("route:GET ")}
            | {(LEDGER, "walk:transactions"), (ME, "loop:ws-pump"), *((QUEUE, k) for k in SENDER),
               (QUEUE, "route:POST /api/of/v2/messages/queue"), (SUBS, AUDIENCE_CRAWL), (FOLLOWING, AUDIENCE_CRAWL)})

_ID_SEG = re.compile(r"/(?:\d+|[0-9a-fA-F-]{16,})(?=/|$)")
_STATIC_USERS = {"me", "list", "notifications", "performers", "settings"}


def _fold(path: str) -> str:
    segs = _ID_SEG.sub("/{}", path).split("/")
    for i in range(len(segs) - 1):
        if segs[i] == "users" and segs[i + 1] not in _STATIC_USERS:
            segs[i + 1] = "{}"
    return "/".join(segs)


def _klass(status) -> str:
    if not isinstance(status, int):
        return "error"
    if status in (401, 403, 429):
        return str(status)
    return f"{status // 100}xx"


def _wire(fake) -> Counter:
    """FakeOF's signed API calls, keyed as the counter keys them (Caller kind aside)."""
    with fake.lock:
        calls = list(fake.calls)
    return Counter((c["route"].split(" ", 1)[0] + " " + _fold(c["path"]), c["account"] or "-", _klass(c["status"]))
                   for c in calls if c["path"].startswith("/api2/"))


def _file(path) -> tuple[dict, Counter]:
    raw = json.loads(path.read_text())
    out: Counter = Counter()
    for _caller, key, aid, status, n in raw["rows"]:
        out[(key, aid, status)] += n
    return raw, out


def _diff(want: Counter, got: Counter) -> dict:
    keys = set(want) | set(got)
    return {" | ".join(k): {"wire": want[k], "file": got[k]} for k in sorted(keys) if want[k] != got[k]}


async def _quiet(fake, quiet_s: float = 2.5, max_s: float = 60.0) -> bool:
    """Until no OF call arrived for `quiet_s` (the counter flushes every 1 s)."""
    t0 = time.monotonic()
    n = -1
    while time.monotonic() - t0 < max_s:
        with fake.lock:
            m = len(fake.calls)
        if m == n:
            return True
        n = m
        await asyncio.sleep(quiet_s)
    return False


async def _settled(fake, path) -> tuple[dict, Counter, Counter]:
    """The file and the wire read with no call in between: (raw file, file counts, wire counts)."""
    for _ in range(20):
        await _quiet(fake)
        w1 = _wire(fake)
        await asyncio.sleep(2.5)     # > 2 flushes
        raw, got = _file(path)
        if _wire(fake) == w1:
            return raw, got, w1
    return raw, got, _wire(fake)


async def run(ctx) -> None:
    w, fake = ctx.world, ctx.of_wire
    await ctx.build(PROFILE)
    cs = [c["id"] for c in w.data["creators"]]
    stats = ctx.stack.db.parent / "of_call_stats.json"
    if LEG:
        LEG.seed(w)
    owner = ctx.owner.share()
    (await owner.put("/admin/my-llm-keys", json={"deepseek": "slop-fake-deepseek"})).raise_for_status()

    # ── every Creator's WS pump on FakeOF's socket (a `loop:` the stack runs) ──
    t_pumps = time.time()
    (await owner.post("/__slop/pump-supervise")).raise_for_status()
    while time.time() - t_pumps < PUMP_UP_S:
        with fake.lock:
            up = {c["account"] for c in fake.ws_connects if c["t"] >= t_pumps}
        if up >= set(cs):
            break
        await asyncio.sleep(0.25)

    # ── two composer mass sends: each hands its Audience crawl to the Creator's crawler ──
    mass_aid = cs[-1]
    mass_runs = []
    for i in range(MASS_SENDS):
        r = await owner.post("/api/of/v2/messages/queue", headers={"X-Account-Id": mass_aid},
                             json={"text": f"slop of-call-counter mass {i}", "user_lists": ["fans", "following"]})
        mass_runs.append({"status": r.status_code,
                          "run": r.json().get("_mass_run_id") if r.status_code == 200 else None})
    ids = [m["run"] for m in mass_runs if m["run"] is not None]
    t0 = time.monotonic()
    while ids and time.monotonic() - t0 < MASS_TIMEOUT_S:
        con = w.sql()
        try:
            left = con.execute(f"SELECT COUNT(*) FROM mass_runs WHERE id IN ({','.join('?' * len(ids))}) "
                               "AND recipients_json IS NULL", ids).fetchone()[0]
        finally:
            con.close()
        if not left:
            break
        await asyncio.sleep(0.25)
    ctx.metric("mass_recipients", {"sends": mass_runs, "recorded_s": round(time.monotonic() - t0, 2)})

    # ── phase 1: users + walks, a 429 and 500s at the wire ──
    with fake.lock:
        fake.throttle[(cs[0], LEDGER)] = 1
        fake.fail.add((cs[1 % len(cs)], LEDGER))
    stop = asyncio.Event()

    async def user(i: int, http) -> None:
        r = random.Random(f"{ctx.seed}:user:{i}")
        while not stop.is_set():
            aid = cs[r.randrange(len(cs))]
            hdr = {"X-Account-Id": aid}
            for p in USER_READS:
                if stop.is_set():
                    break
                try:
                    await http.get(p, headers=hdr)
                except Exception:  # noqa: BLE001 — recorded by the client (599)
                    pass
            try:
                await asyncio.wait_for(stop.wait(), r.uniform(1.0, 3.0))
            except asyncio.TimeoutError:
                pass

    ctx.rec.stage = "load"
    pool = ctx.owner.share(limits=min(200, ctx.users + 10))
    users = [asyncio.create_task(user(i, pool)) for i in range(ctx.users)]
    walks = []
    hook = ctx.owner.share(rec=Recorder(), limits=4)
    t_load = time.time()
    while time.time() - t_load < LOAD_S.get(ctx.scale, 20.0):
        if not walks or all(x.get("t1") for x in walks):
            r = await hook.post("/__slop/sweep-pacing/run", json={"job": "tx_cycles", "cycles": 1})
            r.raise_for_status()
            walks.append({"n": r.json()["started"][0], "t1": None})
        runs = {x["n"]: x for x in (await hook.get("/__slop/sweep-pacing/runs")).json()["runs"]}
        for x in walks:
            x.update(t1=runs[x["n"]]["t1"], error=runs[x["n"]]["error"])
        await asyncio.sleep(1.0)
    stop.set()
    await asyncio.gather(*users, return_exceptions=True)
    await pool.aclose()
    for _ in range(120):   # the last walk finishes
        runs = {x["n"]: x for x in (await hook.get("/__slop/sweep-pacing/runs")).json()["runs"]}
        for x in walks:
            x.update(t1=runs[x["n"]]["t1"], error=runs[x["n"]]["error"])
        if all(x["t1"] for x in walks):
            break
        await asyncio.sleep(1.0)
    ctx.rec.stage = None
    with fake.lock:
        fake.fail.discard((cs[1 % len(cs)], LEDGER))
        fake.throttle.clear()

    raw1, file1, wire1 = await _settled(fake, stats)
    led = {k: n for k, n in wire1.items() if k[0] == LEDGER}
    armed = {"429": led.get((LEDGER, cs[0], "429"), 0), "retry_2xx": led.get((LEDGER, cs[0], "2xx"), 0),
             "5xx": sum(n for k, n in wire1.items() if k[2] == "5xx")}
    bad = _diff(wire1, file1)
    ctx.check(COUNTS, not bad and armed["429"] >= 1 and armed["retry_2xx"] >= 1 and armed["5xx"] >= 1,
              keys=len(wire1), calls=sum(wire1.values()), armed=armed, mismatched=dict(list(bad.items())[:20]),
              walks=walks, boots=raw1.get("boots"), folded=raw1.get("folded"), write_error=raw1.get("write_error"))
    summ = ctx.rec.summary("load")
    reads = {k: v for k, v in summ.items() if k.startswith("GET /api/of/")}
    ctx.check(NO_5XX, bool(reads) and not any(v["5xx"] for v in reads.values()),
              routes={k: {"n": v["n"], "5xx": v["5xx"]} for k, v in reads.items()})
    p95 = {k: v["p95_ms"] for k, v in reads.items()}
    ctx.metric("p95_vs_last_green", p95)
    ctx.metric("p95_vs_last_green_n", {k: v["n"] for k, v in reads.items()})
    ctx.metric("of_call_counter_phase1", {"wire_calls": sum(wire1.values()), "keys": len(wire1), "armed": armed,
                                          "callers": sorted({r[0] for r in raw1["rows"]})[:40]})

    # ── phase 2: SIGTERM with a mass send held at OF ──
    aid = cs[0]
    sent, arrived = {"leg": None}, True
    if LEG:
        with fake.lock:
            fake.hold[(aid, QUEUE)] = [HOLD_S]
        sent = {"leg": LEG.__name__, **await LEG.start_send(owner, w, aid)}
        t0 = time.monotonic()
        while time.monotonic() - t0 < SEND_TIMEOUT_S:
            with fake.lock:
                arrived = not fake.hold.get((aid, QUEUE))
            if arrived:
                break
            await asyncio.sleep(0.05)
    await owner.aclose()
    await hook.aclose()
    t_term, took = await asyncio.to_thread(ctx.stack.stop_relay, 0, STOP_GRACE_S)
    raw2, file2 = _file(stats)
    wire2 = _wire(fake)
    with fake.lock:
        held = [c for c in fake.calls if c["account"] == aid and c["route"] == QUEUE]
    after_term = [round(c["t"] - t_term, 2) for c in held if c["t"] > t_term]
    d2 = _diff(wire2 - wire1, file2 - file1)
    await asyncio.to_thread(ctx.stack.start_relay)
    raw_up, file_up = _file(stats)
    lost = {" | ".join(k): {"stopped": n, "restarted": file_up[k]} for k, n in file2.items() if file_up[k] < n}
    raw3, file3, wire3 = await _settled(fake, stats)
    d3 = _diff(wire3 - wire2, file3 - file2)
    ctx.check(RESTART, arrived and (bool(after_term) or not LEG) and not d2 and not d3 and not lost
              and raw_up.get("boots") == raw2.get("boots", 0) + 1 and raw3.get("started_at") == raw1.get("started_at"),
              **sent, send_arrived=arrived,
              send_answered_s_after_term=after_term, exit_s=None if took is None else round(took, 2),
              at_stop=dict(list(d2.items())[:20]), after_restart=dict(list(d3.items())[:20]), lost=lost,
              boots={"stopped": raw2.get("boots"), "restarted": raw_up.get("boots")},
              file_calls={"phase1": sum(file1.values()), "stopped": sum(file2.values()),
                          "end": sum(file3.values())})
    by: Counter = Counter()
    for caller, key, _aid, _status, n in raw3["rows"]:
        by[(caller, key)] += n
    unlabelled = {k: n for (c, k), n in by.items() if c == "unlabelled"}
    wrong = {f"{c} | {k}": n for (c, k), n in by.items() if k in CALLERS and c not in CALLERS[k]}
    missing = sorted(f"{c} | {k}" for k, c in REQUIRED if not by[(c, k)])
    ctx.check(LABELS, not unlabelled and not wrong and not missing
              and len(ids) == MASS_SENDS and len(set(ids)) == MASS_SENDS, unlabelled=unlabelled, wrong=wrong,
              missing=missing, mass_runs=mass_runs, callers={f"{c} | {k}": n for (c, k), n in sorted(by.items())})
    (ctx.out / "of-call-counter.json").write_text(json.dumps(
        {"phase1": raw1, "stopped": raw2, "restarted": raw_up, "end": raw3}, default=str))
