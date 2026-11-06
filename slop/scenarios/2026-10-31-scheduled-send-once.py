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
CONNECT the first time (OF never saw them: the composer's DM keeps the plain job retry, never
"proxy_retry", read from the owner's job list `GET /admin/system/runs`), PLAIN sends OF answers.
Phase B, per Creator: HANG sends OF takes and the call blocks; once
every run slot holds a send OF took and has not answered (steady), the relay is SIGKILLed,
OF answers normally from then on, and the relay starts again on the same DB; the scenario
waits for the boot heal's `reconciled_orphans` line before its first pass, so a pass never
claims a job the heal then sees as orphaned. Phase C, per Creator: one ECHO send OF takes
and answers with a 502 whose text echoes its rate-limit refusal ("Please allow 10 seconds"):
never retried (the rate-limit retry is for OF's 4xx), parked "may have sent". Phase C is not
in phase A: a 5th phase-A send per Creator lands >= 44 s after its first (the 11 s write
spacing) and would crowd the schedule -> OF-took budget. Phase D: two broadcasts
(`send_mass_message`, `POST /admin/automation/enqueue`, one fan each) whose proxy refuses the
CONNECT (lib/automation_relay.py `of-mass.json` `send_fail`, `of-mass.jsonl`): Creator 0's once
(then OF takes it), Creator 1's every time.

Checks (names in lib/send_once_faults.py): OF holds exactly 1 message per job; every job
ends done or error; every job in error carries "may have sent"; every REFUSE job ends done
and never read proxy_retry (REFUSED_DM_PLAIN); the once-refused broadcast read proxy_retry:1 due
PROXY_RETRY_MINUTES after the refusal, then OF took it once (REFUSED_DEFERRED); the always-refused
one read proxy_retry:1..3 and ended error proxy_refused after 4 refusals, OF never saw it
(REFUSED_TERMINAL); every mass run they minted reads refused or ok, none running (REFUSED_RUN_CLOSED);
the SIGKILL landed as planned; every ECHO send is one OF message, its job error "may have
sent", never resent (settled within its own wait); route p95s and schedule -> OF-took p95
(PLAIN, phase A) in budget, and vs the last green run.

Open (owner question, declared): the boot heal parks EVERY orphaned one-shot, also one whose
run never reached its OF write (still waiting in dm_rate.turn / the 11 s write gate /
send_mass_message's crawls): nothing durable records that a write started, and the owner's
spec says an orphaned one-shot parks. Phase B only kills once every running send is past
its write, so this scenario does not exercise that case.

Bypasses (declared): OF's DM endpoint is faked at the client boundary (lib/send_once_relay.py:
the 30 s client read timeout compressed to STALL_S, latency nil; ECHO's 502 is a fake
answer, OF's 5xx body unmeasured); the supervisor's cadence
(the scenario ticks between its own ticks). The per-Creator 11 s write spacing, the claim, the
retry backoff (60 s) and the boot heal are the product's. OF's mass endpoint and its user lists
are faked on the lane's client (automation_relay, proxy refusal at once: `proxy_s` 0). A
broadcast's 5-minute proxy wait is skipped once seen: its run_at moved to now by SQL (the row the product wrote, its time only). The
run's owner is made a site admin by SQL (`users.is_admin`, as runtime-switches) to read the job list.
Break-it-once: send-once-retries-after-accept (run_decide.ONE_SHOT_KINDS emptied: every
failed / orphaned job requeued, the pre-fix lane): only ONCE and ECHO_5XX go red;
--fault=rate-limit-text-sniff (of_write.is_rate_limited on the text alone, the pre-fix gate:
the ECHO send retried): only ECHO_5XX and ONCE; --fault=refused-job-not-deferred (run_once never
reads a refusal: the plain 60 s retry, the pre-fix park): only REFUSED_DEFERRED and REFUSED_TERMINAL;
--fault=composer-send-deferred (scheduled_send in run_decide.PROXY_DEFER_KINDS): only
REFUSED_DM_PLAIN; --fault=mass-refused-run-left-running (no close of a refused run's mass_runs
row): only REFUSED_RUN_CLOSED.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone

from slop.lib.client import Recorder
from slop.lib.send_once_faults import (ECHO_5XX, ONCE, PARKED, REFUSED, REFUSED_DEFERRED, REFUSED_DM_PLAIN,
                                       REFUSED_RUN_CLOSED, REFUSED_TERMINAL, SETTLED)
from slop.lib.send_once_relay import SLOP_MARK, read_journal

PROFILE = "agency_inbox"
UI = False
FAULT = "send-once-retries-after-accept"
RELAY_ENV = {"SLOP_SUPERVISOR": "1"}
# A parked send's run logs its error (automation_run_failed) with the fake's exception.
# Phase D's refused broadcasts log theirs with automation_relay's ProxyError.
EXPECTED_TRACEBACKS = (("automation_run_failed", SLOP_MARK),
                       ("automation_run_failed", "CONNECT tunnel failed, response 403"))
STALL_S = 3.0          # OFClient's 30 s read timeout, compressed (declared)
HANG_S = 300.0         # the kill comes long before
POLL_S = 2.0
PHASE_TIMEOUT_S = 300  # a phase settling (REFUSE's proxy wait skipped once seen, below)
PROXY_RETRY_MINUTES = 5   # run_decide.PROXY_RETRY_MINUTES: a refused broadcast's wait
PROXY_RETRIES = 3         # run_decide.PROXY_RETRIES: then the 4th refusal ends it proxy_refused
OF_MASS = {"send_s": 0.2, "accept_at": 0.5, "proxy_s": 0, "list_s": 0}   # phase D's fake OF (guess)
DEFER_SLACK_S = 30        # refusal -> park: the run's own end (the fake refuses at once)
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
    con = w.sql()
    with con:   # declared: the owner reads the site's job list (GET /admin/system/runs)
        con.execute("UPDATE users SET is_admin=1 WHERE id=?", (w.user_id,))
    con.close()

    # The plan: per Creator, distinct fans per behaviour; phases A, B, then C.
    plan: dict[str, list[dict]] = {"A": [], "B": [], "C": []}
    rng_c = w.rng("scenario:send-once:C")   # its own stream: phases A and B pick as before
    for ci, aid in enumerate(creators):
        every = [f["id"] for f in w.data["fans"][aid]]
        fans = rng.sample(every, sum(PER_CREATOR.values()))
        echo = rng_c.choice([f for f in every if f not in fans])
        for how, n in PER_CREATOR.items():
            for _ in range(n):
                fan = fans.pop()
                ph = "B" if how == "hang" else "A"
                k = len(plan[ph])
                plan[ph].append({"account_id": aid, "fan_id": fan, "how": how,
                                 "text": f"slop send-once {ph}{k} c{ci} {how} fan {fan}"})
        plan["C"].append({"account_id": aid, "fan_id": echo, "how": "echo_5xx",
                          "text": f"slop send-once C{ci} c{ci} echo_5xx fan {echo}"})

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

    watched: dict[int, str] = {}           # job id -> kind: the refused sends (phase A's REFUSE, phase D)
    deferred: dict[int, list[dict]] = {}   # job id -> each proxy wait the owner's job list showed

    async def skip_proxy_wait() -> None:
        """A watched job parked by a proxy refusal: read it as the owner's job list shows it
        (last_error, run_at), then move its run_at to now by SQL (declared)."""
        seen = []
        for kind in sorted(set(watched.values())):
            r = await tick_http.get(f"/admin/system/runs?kind={kind}&status=pending&limit=500")
            seen += [j for j in (r.json().get("jobs", []) if r.status_code == 200 else [])
                     if j["id"] in watched and str(j.get("last_error") or "").startswith("proxy_retry:")]
        for j in seen:
            row = {"last_error": j["last_error"][:120], "run_at": j["run_at"]}
            if not deferred.get(j["id"]) or deferred[j["id"]][-1] != row:
                deferred.setdefault(j["id"], []).append(row)
        if seen:
            con = w.sql()
            with con:
                con.executemany("UPDATE scheduled_jobs SET run_at = ? WHERE id = ? AND status = 'pending'",
                                [(datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f"), j["id"]) for j in seen])
            con.close()

    async def settle(ph: str) -> bool:
        t0 = time.monotonic()
        while time.monotonic() - t0 < PHASE_TIMEOUT_S:
            if all(r["status"] in ("done", "error", "cancelled") for r in jobs(ids(ph)).values()):
                return True
            await tick()
            await skip_proxy_wait()
            await asyncio.sleep(1.0)
        return False

    phases: dict[str, dict] = {}

    async def simple_phase(ph: str, hows: set[str]) -> bool:
        """Phase `ph` with OF answering `hows`: schedule its sends, chatters polling, settle."""
        ctx.rec.stage = ph
        write_cfg(hows)
        stop = asyncio.Event()
        pollers = asyncio.create_task(poll(stop))
        await schedule(ph)
        watched.update({j["job_id"]: "scheduled_send" for j in plan[ph]
                        if j["how"] == "refuse_once" and j.get("job_id")})
        t = time.monotonic()
        ok = await settle(ph)
        stop.set()
        await pollers
        phases[ph] = {"settled": ok, "s": round(time.monotonic() - t, 1)}
        return ok

    # ── phase A: OF takes it and never answers / the proxy refuses it once / plain ──
    ok_a = await simple_phase("A", {"stall", "refuse_once"})

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

    # ── phase C: OF takes it, then a 502 echoing its rate-limit text ──────────
    ok_c = await simple_phase("C", {"echo_5xx"})

    # ── phase D: broadcasts the proxy refuses, once (Creator 0) / every time (Creator 1) ──
    ctx.rec.stage = "D"
    once_aid, always_aid = creators[0], creators[1]
    mass_cfg = tmp / "of-mass.json"
    mass_cfg.write_text(json.dumps({**OF_MASS, "send_fail": {once_aid: "proxy", always_aid: "proxy"}}))
    con = w.sql()
    runs0 = con.execute("SELECT COALESCE(MAX(id), 0) FROM mass_runs").fetchone()[0]
    con.close()
    bcast = []
    for how, aid in (("once", once_aid), ("always", always_aid)):
        fan = w.data["fans"][aid][0]["id"]
        text = f"slop send-once D {how} {aid}"
        r = await tick_http.post("/admin/automation/enqueue", json={
            "account_id": aid, "kind": "send_mass_message", "payload": {"text": text, "included_users": [fan]}})
        jid = r.json().get("enqueued_job_id") if r.status_code == 200 else None
        bcast.append({"how": how, "account_id": aid, "text": text, "job_id": jid, "enqueue": r.status_code})
        if jid:
            watched[jid] = "send_mass_message"
    plan_d = [b["job_id"] for b in bcast if b["job_id"]]

    def mass_journal() -> list[dict]:
        f = tmp / "of-mass.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines() if x.strip()] if f.exists() else []

    t, ok_d = time.monotonic(), False
    while time.monotonic() - t < PHASE_TIMEOUT_S:
        if plan_d and all(r["status"] in ("done", "error", "cancelled") for r in jobs(plan_d).values()):
            ok_d = True
            break
        await tick()
        # Creator 0's proxy is back once it refused (before its wait is skipped: no 2nd refusal)
        if any(r["op"] == "send_refused" and r["account_id"] == once_aid for r in mass_journal()):
            mass_cfg.write_text(json.dumps({**OF_MASS, "send_fail": {always_aid: "proxy"}}))
        await skip_proxy_wait()
        await asyncio.sleep(1.0)
    phases["D"] = {"settled": ok_d, "s": round(time.monotonic() - t, 1)}
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

    ab = set(ids("A") + ids("B"))   # SETTLED is A+B by owner spec: phase C settles inside ECHO_5XX's own wait
    left = {i: r["status"] for i, r in rows.items() if i in ab and r["status"] not in ("done", "error")}
    ctx.check(SETTLED, not left and ok_a and ok_b, left=left, phases=phases)

    errored = {i: r["last_error"] for i, r in rows.items() if r["status"] == "error"}
    unmarked = {i: e[:120] for i, e in errored.items() if "may have sent" not in e}
    reasons = Counter(e.split(" (")[0][:60] for e in errored.values())
    ctx.check(PARKED, not unmarked, parked=len(errored), reasons=dict(reasons), unmarked=unmarked)

    refuse = [j for j in everyone if j["how"] == "refuse_once"]
    bad = {j["text"]: rows.get(j.get("job_id"), {}).get("status") for j in refuse
           if rows.get(j.get("job_id"), {}).get("status") != "done"}
    ctx.check(REFUSED, bool(refuse) and not bad, n=len(refuse), bad=bad)

    dm_deferred = {j["text"]: deferred[j["job_id"]] for j in refuse if j.get("job_id") in deferred}
    ctx.check(REFUSED_DM_PLAIN, bool(refuse) and not dm_deferred, n=len(refuse),
              deferred=dict(list(dm_deferred.items())[:10]))

    mj = mass_journal()
    d_rows = jobs(plan_d) if plan_d else {}
    wait_s = PROXY_RETRY_MINUTES * 60

    def ops(aid: str, op: str) -> list[float]:
        return [r["t"] for r in mj if r["account_id"] == aid and r["op"] == op]

    once, always = bcast
    seen_once = deferred.get(once["job_id"], [])
    due = (datetime.fromisoformat(seen_once[0]["run_at"]).replace(tzinfo=timezone.utc).timestamp()
           if seen_once and seen_once[0].get("run_at") else None)
    refused_t = ops(once_aid, "send_refused")
    waited = None if due is None or not refused_t else round(due - refused_t[0], 1)
    row = d_rows.get(once["job_id"], {})
    ctx.check(REFUSED_DEFERRED, bool(seen_once) and seen_once[0]["last_error"].startswith("proxy_retry:1 (")
              and waited is not None and wait_s - 1 <= waited <= wait_s + DEFER_SLACK_S
              and row.get("status") == "done" and len(refused_t) == 1 and len(ops(once_aid, "send_accepted")) == 1,
              job=row, sightings=seen_once[:4], due_after_refusal_s=waited, wait_s=wait_s,
              refused=len(refused_t), of_took=len(ops(once_aid, "send_accepted")))

    row = d_rows.get(always["job_id"], {})
    seen_always = [d["last_error"].split(" (")[0] for d in deferred.get(always["job_id"], [])]
    want_seen = [f"proxy_retry:{n}" for n in range(1, PROXY_RETRIES + 1)]
    ctx.check(REFUSED_TERMINAL, row.get("status") == "error" and row.get("last_error", "").startswith("proxy_refused (")
              and len(ops(always_aid, "send_refused")) == PROXY_RETRIES + 1 and not ops(always_aid, "send_begin")
              and seen_always == want_seen,
              job={**row, "last_error": row.get("last_error", "")[:120]}, sightings=seen_always,
              refused=len(ops(always_aid, "send_refused")), of_saw=len(ops(always_aid, "send_begin")))

    con = w.sql()
    runs = Counter(r[0] for r in con.execute(
        "SELECT status FROM mass_runs WHERE id > ? AND account_id IN (?, ?)", (runs0, once_aid, always_aid)))
    con.close()
    want_runs = Counter({"refused": len(ops(once_aid, "send_refused")) + len(ops(always_aid, "send_refused")),
                         "ok": len(ops(once_aid, "send_accepted"))})
    ctx.check(REFUSED_RUN_CLOSED, ok_d and runs == want_runs, runs=dict(runs), want=dict(want_runs), settled=ok_d)

    echo = [j for j in everyone if j["how"] == "echo_5xx"]
    off = {}
    for j in echo:
        r = rows.get(j.get("job_id"), {})
        if took[j["text"]] != 1 or r.get("status") != "error" or "may have sent" not in r.get("last_error", ""):
            off[j["text"]] = {"of_messages": took[j["text"]], "status": r.get("status"),
                              "last_error": r.get("last_error", "")[:120]}
    ctx.check(ECHO_5XX, bool(echo) and ok_c and not off, n=len(echo), settled=ok_c,
              off=dict(list(off.items())[:10]))

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
                             "broadcasts": bcast,
                             "status": dict(Counter(r["status"] for r in rows.values())),
                             "ticks": tick_rec.summary()})
    ctx.metric("p95_vs_last_green", p95s)
    for h in https:
        await h.aclose()
    await tick_http.aclose()
