"""A chatter's scheduled DM goes to OnlyFans once, never twice: a send OF may have taken is
never retried, whether its answer never came or the relay died after OF took it
(run_decide.outcome per write attempt, the boot heal's one_shot_family; the owner's default:
park it 'error', "may have sent", rather than risk a double DM).

World: `agency_inbox` (an Agency, its Creators and their fans). `--users` chatters schedule
near-term DMs through the real composer route (`POST /api/of/v2/scheduled-sends`, due at
once, X-Account-Id), spread round-robin over the Creators' fans, and every chatter keeps the
chat's ghost-bubble list open (`GET /api/of/v2/scheduled-sends?fan_id=`, every POLL_S) while
they go out. The real automation supervisor runs (SLOP_SUPERVISOR=1: its boot heal is the
orphan path); `/__slop/automation-tick` adds passes between its 30 s ticks. OnlyFans' side is
lib/send_once_relay.py (`of-send-once.jsonl`, survives a SIGKILL).

Phase A, per Creator: STALL sends OF takes and never answers (the call raises curl's
ReadTimeout after the compressed client timeout), REFUSE sends whose proxy refuses the
CONNECT the first time (OF never saw them: retried after the job backoff, then answered),
PLAIN sends OF answers. Phase B, per Creator: HANG sends OF takes and the call blocks; once
every run slot holds a send OF took and has not answered (steady), the relay is SIGKILLed,
OF answers normally from then on, and the relay starts again on the same DB; the scenario
waits for the boot heal's `reconciled_orphans` line before its first pass, so a pass never
claims a job the heal then sees as orphaned.

Checks (names in lib/send_once_faults.py): OF holds exactly 1 message per job; every job
ends done or error; every job in error carries "may have sent"; every REFUSE job ends done;
the SIGKILL landed as planned; route p95s and schedule -> OF-took p95 (PLAIN, phase A) in
budget, and vs the last green run.

Open (owner question, declared): the boot heal parks EVERY orphaned one-shot, also one whose
run never reached its OF write (still waiting in dm_rate.turn / the 11 s write gate /
send_mass_message's crawls): nothing durable records that a write started, and the owner's
spec says an orphaned one-shot parks. Phase B only kills once every running send is past
its write, so this scenario does not exercise that case.

Bypasses (declared): OF's DM endpoint is faked at the client boundary (lib/send_once_relay.py:
the 30 s client read timeout compressed to STALL_S, latency nil); the supervisor's cadence
(the scenario ticks between its own ticks). The per-Creator 11 s write spacing, the claim, the
retry backoff (60 s) and the boot heal are the product's.
Break-it-once: send-once-retries-after-accept (run_decide.ONE_SHOT_KINDS emptied: every
failed / orphaned job requeued, the pre-fix lane): only ONCE goes red.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections import Counter
from datetime import datetime

from slop.lib.client import Recorder
from slop.lib.send_once_faults import ONCE, PARKED, REFUSED, SETTLED
from slop.lib.send_once_relay import SLOP_MARK, read_journal

PROFILE = "agency_inbox"
UI = False
FAULT = "send-once-retries-after-accept"
RELAY_ENV = {"SLOP_SUPERVISOR": "1"}
# A parked send's run logs its error (automation_run_failed) with the fake's exception.
EXPECTED_TRACEBACKS = (("automation_run_failed", SLOP_MARK),)
STALL_S = 3.0          # OFClient's 30 s read timeout, compressed (declared)
HANG_S = 300.0         # the kill comes long before
POLL_S = 2.0
PHASE_TIMEOUT_S = 300  # a phase settling: REFUSE waits the 60 s job backoff
KILL_TIMEOUT_S = 120
KILL_STABLE_S = 3.0   # > one pass cadence: no claim pending
PER_CREATOR = {"stall": 2, "refuse_once": 1, "plain": 1, "hang": 2}
# Each Creator's DMs are spaced 11 s apart by of_write_paced (real), so the 4th send of a
# Creator's phase-A batch is >= 33 s after the first; plus the pass cadence.
E2E_P95_MS = 75_000
# A herd budget: phase A's 40 posts land in ~0.2 s while 200 chat lists poll; the relay
# finishes them one by one ~50-70 ms apart (relay.log), so the last waits ~2-3 s (measured
# p95 1780 / 3015 ms at medium/200, 20261030T182548Z-...-0121 / 20261030T183304Z-...-23b5).
# p95-vs-last-green guards drift.
P95_MS = {"POST /api/of/v2/scheduled-sends": 4000, "GET /api/of/v2/scheduled-sends": 1000}
P95_VS_LAST = (1.5, 2000)
# At least min(Creators, run slots) hung: one run per Creator (its run lock), every slot busy; more
# may run, a run waiting on a hold lends its slot (run_slot, ADR 0025).
KILLED = "SIGKILL landed with every running send taken by OF and unanswered (>= one per run slot)"
HEAL_TIMEOUT_S = 60
_SLOTS = re.compile(r"automation_run_slots_resized from=\d+ to=(\d+)|automation_supervisor_started .*max_concurrent=(\d+)")


def _run_slots(log: str) -> int | None:
    """The supervisor's run slots, as the relay last logged them."""
    found = [int(a or b) for a, b in _SLOTS.findall(log)]
    return found[-1] if found else None


def _iso_now() -> str:
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    creators = [c["id"] for c in w.data["creators"]]
    rng = w.rng("scenario:send-once")
    tmp = ctx.stack.tmp
    cfg_file = tmp / "of-send-once.json"

    # The plan: per Creator, distinct fans per behaviour; phase A then phase B.
    plan: dict[str, list[dict]] = {"A": [], "B": []}
    for ci, aid in enumerate(creators):
        fans = rng.sample([f["id"] for f in w.data["fans"][aid]], sum(PER_CREATOR.values()))
        for how, n in PER_CREATOR.items():
            for _ in range(n):
                fan = fans.pop()
                ph = "B" if how == "hang" else "A"
                k = len(plan[ph])
                plan[ph].append({"account_id": aid, "fan_id": fan, "how": how,
                                 "text": f"slop send-once {ph}{k} c{ci} {how} fan {fan}"})

    def write_cfg(hows: set[str]) -> None:
        fans = {f"{j['account_id']}:{j['fan_id']}": j["how"] for ph in plan.values() for j in ph
                if j["how"] in hows}
        cfg_file.write_text(json.dumps({"fans": fans, "stall_s": STALL_S, "hang_s": HANG_S}))

    def journal() -> list[dict]:
        return read_journal(tmp)

    def jobs(ids: list[int]) -> dict[int, dict]:
        con = w.sql()
        try:
            q = ",".join("?" * len(ids))
            rows = con.execute(f"SELECT id, status, last_error, attempts FROM scheduled_jobs WHERE id IN ({q})",
                               ids).fetchall()
        finally:
            con.close()
        return {r[0]: {"status": r[1], "last_error": r[2] or "", "attempts": r[3]} for r in rows}

    tick_rec = Recorder()   # the passes: long by design, and one dies with the relay
    users = max(1, ctx.users)

    def shares() -> list:
        return [ctx.owner.share(limits=4) for _ in range(users)]

    https = shares()
    tick_http = ctx.owner.share(rec=tick_rec, limits=4)

    async def schedule(ph: str) -> None:
        async def one(u: int) -> None:
            for j in plan[ph][u::users]:
                await asyncio.sleep(rng.uniform(0, 0.2))
                j["t_sched"] = time.time()
                r = await https[u].post("/api/of/v2/scheduled-sends", headers={"X-Account-Id": j["account_id"]},
                                        json={"fan_id": j["fan_id"], "text": j["text"], "run_at": _iso_now()})
                j["status_code"] = r.status_code
                j["job_id"] = r.json().get("job_id") if r.status_code == 200 else None
        await asyncio.gather(*(one(u) for u in range(users)))

    async def poll(stop: asyncio.Event) -> None:
        """Every chatter's open chat: its ghost-bubble list, re-read every POLL_S."""
        everyone = [j for ph in plan.values() for j in ph]

        async def one(u: int) -> None:
            j = everyone[u % len(everyone)]
            await asyncio.sleep(rng.uniform(0, POLL_S))
            while not stop.is_set():
                await https[u].get(f"/api/of/v2/scheduled-sends?fan_id={j['fan_id']}",
                                   headers={"X-Account-Id": j["account_id"]})
                try:
                    await asyncio.wait_for(stop.wait(), POLL_S * rng.uniform(0.75, 1.25))
                except asyncio.TimeoutError:
                    pass
        await asyncio.gather(*(one(u) for u in range(users)))

    async def tick() -> None:
        await tick_http.post("/__slop/automation-tick", timeout=600)

    def ids(ph: str) -> list[int]:
        return [j["job_id"] for j in plan[ph] if j.get("job_id")]

    async def settle(ph: str) -> bool:
        t0 = time.monotonic()
        while time.monotonic() - t0 < PHASE_TIMEOUT_S:
            if all(r["status"] in ("done", "error", "cancelled") for r in jobs(ids(ph)).values()):
                return True
            await tick()
            await asyncio.sleep(1.0)
        return False

    phases: dict[str, dict] = {}

    # ── phase A: OF takes it and never answers / the proxy refuses it once / plain ──
    ctx.rec.stage = "A"
    write_cfg({"stall", "refuse_once"})
    stop = asyncio.Event()
    pollers = asyncio.create_task(poll(stop))
    await schedule("A")
    t = time.monotonic()
    ok_a = await settle("A")
    stop.set()
    await pollers
    phases["A"] = {"settled": ok_a, "s": round(time.monotonic() - t, 1)}

    # ── phase B: OF takes it, the call hangs, SIGKILL, restart ─────────────────
    ctx.rec.stage = "B"
    write_cfg({"hang"})
    stop = asyncio.Event()
    pollers = asyncio.create_task(poll(stop))
    await schedule("B")
    bids = ids("B")
    by_job = {j["job_id"]: j for j in plan["B"] if j.get("job_id")}
    passes = asyncio.create_task(tick())

    def hung() -> frozenset[str] | None:
        """The running B sends, if every one is a send OF took and has not answered."""
        rows = journal()
        returned = {r["text"] for r in rows if r["op"] == "returned"}
        open_ = {r["text"] for r in rows if r["op"] == "accepted" and r["text"] not in returned}
        running = frozenset(by_job[i]["text"] for i, r in jobs(bids).items() if r["status"] == "running")
        return running if running and running <= open_ else None

    # Kill once every run slot (AUTOMATION_MAX_CONCURRENT_RUNS, one per Creator at most) holds
    # a hung send: the same hung set for KILL_STABLE_S, i.e. no further claim is coming.
    t = time.monotonic()
    hit, seen, since = False, None, 0.0
    while time.monotonic() - t < KILL_TIMEOUT_S:
        now = hung()
        if now is None or now != seen:
            seen, since = now, time.monotonic()
        elif time.monotonic() - since >= KILL_STABLE_S:
            hit = True
            break
        if passes.done():
            passes = asyncio.create_task(tick())
        await asyncio.sleep(0.1)
    stop.set()
    await pollers
    at_kill = {i: r["status"] for i, r in jobs(bids).items()}
    relay_log = ctx.out / "relay.log"
    slots = _run_slots(relay_log.read_text(errors="replace"))
    heals_before = relay_log.read_text(errors="replace").count("reconciled_orphans")
    ctx.stack.crash_relay()
    passes.cancel()
    await asyncio.gather(passes, return_exceptions=True)
    write_cfg(set())   # OF answers normally from here on
    t_restart = time.monotonic()
    await asyncio.to_thread(ctx.stack.start_relay)
    restart_s = round(time.monotonic() - t_restart, 2)
    # The boot heal runs in the supervisor task, after /livez answers: wait for its line.
    t = time.monotonic()
    while relay_log.read_text(errors="replace").count("reconciled_orphans") <= heals_before:
        if time.monotonic() - t > HEAL_TIMEOUT_S:
            break
        await asyncio.sleep(0.1)
    healed_s = round(time.monotonic() - t, 2)
    for h in (*https, tick_http):   # their connections died with the relay
        await h.aclose()
    https = shares()
    tick_http = ctx.owner.share(rec=tick_rec, limits=4)
    want_hung = min(len(creators), slots) if slots else None
    ctx.check(KILLED, hit and want_hung is not None and len(seen or ()) >= want_hung,
              running_at_kill=Counter(at_kill.values()), creators=len(creators), run_slots=slots,
              hung_at_kill=len(seen or ()), want_hung=want_hung)
    stop = asyncio.Event()
    pollers = asyncio.create_task(poll(stop))
    t = time.monotonic()
    ok_b = await settle("B")
    stop.set()
    await pollers
    phases["B"] = {"settled": ok_b, "s": round(time.monotonic() - t, 1), "restart_s": restart_s,
                   "heal_waited_s": healed_s,
                   "at_kill": dict(Counter(at_kill.values()))}
    ctx.rec.stage = None

    # ── verdicts ──────────────────────────────────────────────────────────────
    everyone = [j for ph in plan.values() for j in ph]
    unscheduled = [j["text"] for j in everyone if not j.get("job_id")]
    rows = jobs([j["job_id"] for j in everyone if j.get("job_id")])
    journal_rows = journal()
    took = Counter(r["text"] for r in journal_rows if r["op"] == "accepted")
    first_took = {}
    for r in journal_rows:
        if r["op"] == "accepted":
            first_took.setdefault(r["text"], r["t"])

    not_once = {j["text"]: took[j["text"]] for j in everyone if took[j["text"]] != 1}
    ctx.check(ONCE, not unscheduled and not not_once, jobs=len(everyone), of_messages=sum(took.values()),
              not_once=dict(list(not_once.items())[:20]), unscheduled=unscheduled[:10])

    left = {i: r["status"] for i, r in rows.items() if r["status"] not in ("done", "error")}
    ctx.check(SETTLED, not left and ok_a and ok_b, left=left, phases=phases)

    errored = {i: r["last_error"] for i, r in rows.items() if r["status"] == "error"}
    unmarked = {i: e[:120] for i, e in errored.items() if "may have sent" not in e}
    reasons = Counter(e.split(" (")[0][:60] for e in errored.values())
    ctx.check(PARKED, not unmarked, parked=len(errored), reasons=dict(reasons), unmarked=unmarked)

    refuse = [j for j in everyone if j["how"] == "refuse_once"]
    bad = {j["text"]: rows.get(j.get("job_id"), {}).get("status") for j in refuse
           if rows.get(j.get("job_id"), {}).get("status") != "done"}
    ctx.check(REFUSED, bool(refuse) and not bad, n=len(refuse), bad=bad)

    # Budgets: the composer route, the ghost-bubble list, schedule -> OF took it (PLAIN, phase A).
    routes = ctx.rec.summary()
    p95s = {}
    for route, budget in P95_MS.items():
        if route in routes:
            p95s[route] = routes[route]["p95_ms"]
            ctx.check(f"p95 {route} < {budget}ms", routes[route]["p95_ms"] < budget, budget=True,
                      p95=routes[route]["p95_ms"], n=routes[route]["n"])
        else:
            ctx.skip(f"p95 {route} < {budget}ms", "no samples")
    e2e = Recorder()   # its summary's p95, the harness's one definition
    for j in plan["A"]:
        if j["how"] == "plain" and j["text"] in first_took and j.get("t_sched"):
            e2e.add("e2e", 200, (first_took[j["text"]] - j["t_sched"]) * 1000)
    name = f"schedule -> OF took it p95 (plain, phase A) < {E2E_P95_MS}ms"
    if e2e.calls:
        took_it = e2e.summary()["e2e"]
        p95 = round(took_it["p95_ms"])
        p95s["schedule -> OF took it"] = p95
        ctx.check(name, p95 < E2E_P95_MS, budget=True, p95=p95, n=took_it["n"],
                  max=round(max(ms for _, ms in e2e.calls["e2e"])))
    else:
        ctx.skip(name, "no samples")
    ctx.metric("phases", phases)
    ctx.metric("send_once", {"jobs": len(everyone), "by_how": dict(Counter(j["how"] for j in everyone)),
                             "of_messages": sum(took.values()),
                             "refused": sum(1 for r in journal_rows if r["op"] == "refused"),
                             "status": dict(Counter(r["status"] for r in rows.values())),
                             "ticks": tick_rec.summary()})
    ctx.metric("p95_vs_last_green", p95s)
    for h in https:
        await h.aclose()
    await tick_http.aclose()
