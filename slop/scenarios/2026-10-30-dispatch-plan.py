"""The automation dispatch plan (service/dispatch_plan.py, lib/dispatch_faults.py names the
checks): the scheduler's own path, follow-up rules firing through real supervisor passes.

World: `agency_inbox` + seed/followup_drip.py (lib/followup.py `setup`, as
2026-10-30-followup-drip), so each run has due fans to sweep. Load: the owner switches the
follow-up on for every Creator through the real rules route (`POST /admin/automation-rules`,
every PLAN_EVERY_S; two rules of the kind on every other Creator and on the last one) and
deactivates the last one (`POST /admin/accounts/{id}/active`). Then one real supervisor pass
(`POST /__slop/automation-tick`: rules -> jobs, due pairs -> runs), a second (a wake) the
moment the first one's jobs exist, while its runs are still queued for a slot, and
PLAN_CADENCE_PASSES more.

Invariants: ONE: the first pass makes one job per Creator, two rules or one; by the end of the
wake every active Creator's jobs are `done`, ran once each and were spawned once each (the
hooks' task lists: each pass lists the runs it spawned), the deactivated one's job is still
pending, never spawned, never run. CADENCE: over all the passes (inside the rules' interval)
each active Creator's rule made exactly one job (a second rule of the kind is held while the
first one's job is open, then fires once on its own anchor: deferred, not dropped, not
repeated), the deactivated Creator's at most one. Budget: a pass with nothing due, vs the last
green run.

Faked or bypassed, declared: as lib/followup.py (DeepSeek at its HTTP boundary, OF's send, the
DM rate via the real route); the supervisor's timer (the hook runs its pass). No `--users`
streams: this flow is the scheduler, not the fan-out (2026-10-30-followup-drip watches that).
SLOP_LIVE=1: every check SKIPs.

Break-it-once: dispatch-plan-two-jobs-per-kind (ONE, the scenario's FAULT) patches the
executor's busy read (`_pair_busy`), --fault=dispatch-plan-ignores-cadence (CADENCE)
dispatch_plan.interval_due, and --fault=dispatch-plan-spawns-in-flight-pairs (ONE, at
--scale=medium: the wake must find runs still queued) dispatch_plan.plan_dispatch.
A rule switched off mid-run (service/run_decide.py `park`, lib/jobs_faults.py names the check
RULE_OFF), after the passes above: on the first Creator the owner schedules a send due now (`POST
/api/of/v2/scheduled-sends`, the composer's deferral) and one supervisor pass fires it, so the
account's write gate spaces the next write 11 s out; the owner adds an auto_posts rule (the
Ready-made panel's `POST /admin/automation-rules`), a second pass fires it, and while its run
waits at the gate with its job `running` the owner switches the rule off (the panel's `PATCH
/admin/automation-rules/{id}`, which leaves a running job alone). OnlyFans then refuses the post
(`create_post`: the offline client's build error, no `of-vault.json`), so the job is parked.
RULE_OFF: the job ends `cancelled` with the rule-off reason after its one attempt; then OnlyFans
accepts posts (`of-vault.json` written) and a third pass runs: no second run, no post. Bypass,
declared: a job of the rule still pending then has its 60 s retry backoff collapsed by SQL
(`run_at` in the past), so a requeued retry is due on that pass (never touches a cancelled job).
--fault=job-park-ignores-rule-off (RULE_OFF) patches run_decide.park.
"""
from __future__ import annotations

import asyncio
import time
from collections import Counter
from datetime import datetime

from slop.lib import dispatch_faults as dispatch
from slop.lib import followup
from slop.lib import jobs_faults

PROFILE = "agency_inbox"
UI = False
FAULT = "dispatch-plan-two-jobs-per-kind"
P95_VS_LAST = (1.5, 300)
PLAN_EVERY_S = 3600          # the follow-up rule's interval (its catalog cadence_default_s)
PLAN_CADENCE_PASSES = 3      # supervisor passes right after the first, all inside the interval
# The rule-off phase's auto_posts run fails on purpose (OnlyFans refuses the post): its
# `automation_run_failed ... kind=auto_posts run_id=` warning logs the traceback.
EXPECTED_TRACEBACKS = (("kind=auto_posts run_id=", "slop: OF is offline"),)


async def _pass(ctx) -> dict:
    r = await ctx.owner.post("/__slop/automation-tick", timeout=900)
    return r.json() if r.status_code < 300 else {"error": f"{r.status_code} {r.text[:300]}", "tasks": []}


async def _rule_off_phase(ctx, w, aid: str) -> None:
    """A rule switched off while its job runs, then OnlyFans refuses the write (module
    docstring: RULE_OFF): the retry is cancelled and nothing goes out after."""
    text = f"slop rule-off post {ctx.seed}"
    con = w.sql()
    fan = con.execute("SELECT fan_id FROM fans WHERE account_id = ? ORDER BY fan_id LIMIT 1", (aid,)).fetchone()[0]
    run0 = con.execute("SELECT COALESCE(MAX(id), 0) FROM automation_runs").fetchone()[0]
    con.close()

    def read(rid: int) -> tuple[list, list]:
        con = w.sql()
        try:
            return (con.execute("SELECT id, status, attempts, last_error FROM scheduled_jobs WHERE rule_id = ? "
                                "ORDER BY id", (rid,)).fetchall(),
                    con.execute("SELECT id, status FROM automation_runs WHERE kind = 'auto_posts' AND account_id = ? "
                                "AND id > ? ORDER BY id", (aid, run0)).fetchall())
        finally:
            con.close()

    ctx.rec.stage = "rule-off"
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    r = await ctx.owner.post("/api/of/v2/scheduled-sends", headers={"X-Account-Id": aid},
                             json={"fan_id": fan, "run_at": now, "text": "slop: the owner's deferred send"})
    r.raise_for_status()
    gate = await _pass(ctx)           # fires the send: the account's next write waits out the gap
    r = await ctx.owner.post("/admin/automation-rules", json={
        "account_id": aid, "kind": "auto_posts", "name": "rule-off probe", "every_seconds": PLAN_EVERY_S,
        "payload": {"posts": [{"text": text}]}, "is_enabled": True})
    r.raise_for_status()
    rid = int(r.json()["id"])
    fire = asyncio.create_task(_pass(ctx))
    t0 = time.monotonic()
    while not fire.done() and time.monotonic() - t0 < 10:
        jobs_, _ = read(rid)
        if jobs_ and jobs_[0][1] == "running":
            break
        await asyncio.sleep(0.05)
    off = await ctx.owner.request("PATCH", f"/admin/automation-rules/{rid}", json={"is_enabled": False})
    jobs_, runs_ = read(rid)
    mid_run = (off.status_code == 200 and not fire.done() and len(jobs_) == 1
               and jobs_[0][1] == "running" and not any(st != "running" for _, st in runs_))
    first = await fire
    parked, _ = read(rid)
    vault = ctx.stack.shard_svc[0] / "of-vault.json"
    vault.write_text("{}")   # OnlyFans accepts posts from here on
    try:
        con = w.sql()
        collapsed = con.execute("UPDATE scheduled_jobs SET run_at = '2000-01-01 00:00:00.000000' "
                                "WHERE rule_id = ? AND status = 'pending'", (rid,)).rowcount
        con.commit()
        con.close()
        again = await _pass(ctx)
    finally:
        vault.unlink()
    ctx.rec.stage = None
    jobs_, runs_ = read(rid)
    carriers = (await ctx.owner.get("/__slop/vault/fake")).json().get("carriers") or []
    posted = [c["post_id"] for c in carriers if c.get("text") == text]
    con = w.sql()
    rows = con.execute("SELECT COUNT(*) FROM posts WHERE account_id = ? AND text = ?", (aid, text)).fetchone()[0]
    con.close()
    job = jobs_[0] if len(jobs_) == 1 else None
    errs = [p["error"] for p in (gate, first, again) if "error" in p]
    cancelled_once = (job is not None and job[1] == "cancelled" and job[2] == 1
                      and (job[3] or "").startswith(jobs_faults.RULE_OFF_ERROR_PREFIX))
    nothing_after = len(runs_) == 1 and not posted and rows == 0
    ctx.check(jobs_faults.RULE_OFF, mid_run and cancelled_once and nothing_after and not errs,
              switched_off_mid_run=mid_run, patch=off.status_code, jobs=[list(j) for j in jobs_],
              after_park=[list(j) for j in parked], backoff_collapsed=collapsed,
              runs=[list(x) for x in runs_], posts_sent_after=len(posted), post_rows=rows,
              passes=[len(p.get("tasks") or []) for p in (gate, first, again)], errors=errs)


async def run(ctx) -> None:
    if followup.refuse_live(ctx, (dispatch.ONE, dispatch.CADENCE, jobs_faults.RULE_OFF)):
        return
    await followup.setup(ctx, PROFILE)
    w = ctx.world
    aids = [c["id"] for c in w.data["creators"]]
    off = aids[-1]
    rule_ids: dict[str, list[int]] = {}
    for i, a in enumerate(aids):
        for _ in range(2 if i % 2 == 0 or a == off else 1):
            r = await ctx.owner.post("/admin/automation-rules", json={
                "account_id": a, "kind": "send_followup", "every_seconds": PLAN_EVERY_S,
                "payload": followup.payload(ctx)})
            r.raise_for_status()
            rule_ids.setdefault(a, []).append(int(r.json()["id"]))
    (await ctx.owner.post(f"/admin/accounts/{off}/active", json={"active": False})).raise_for_status()
    ids = [x for v in rule_ids.values() for x in v]

    def jobs() -> dict[int, tuple]:
        con = w.sql()
        try:
            return {j: (str(a), st, rid) for j, a, st, rid in con.execute(
                "SELECT id, account_id, status, rule_id FROM scheduled_jobs "
                f"WHERE rule_id IN ({','.join('?' * len(ids))})", ids)}
        finally:
            con.close()

    con = w.sql()
    run0 = con.execute("SELECT COALESCE(MAX(id), 0) FROM automation_runs").fetchone()[0]
    con.close()
    ctx.rec.stage = "plan-pass"
    first_t = asyncio.create_task(_pass(ctx))
    t0 = time.monotonic()
    while not first_t.done() and len(jobs()) < len(aids) and time.monotonic() - t0 < 60:
        await asyncio.sleep(0.02)
    snap = jobs()                     # the first pass's jobs, before the wake
    woke_at = round(time.monotonic() - t0, 3)
    wake = await _pass(ctx)           # a wake landing while the first pass's runs are in flight
    first = await first_t
    made = jobs()
    con = w.sql()
    runs = Counter(str(a) for (a,) in con.execute(
        "SELECT account_id FROM automation_runs WHERE kind = 'send_followup' AND id > ?", (run0,)))
    con.close()
    ctx.rec.stage = "plan-cadence"
    cadence = [await _pass(ctx) for _ in range(PLAN_CADENCE_PASSES)]
    ctx.rec.stage = None
    after = jobs()

    spawned = [(str(a), k) for a, k in (first.get("tasks") or []) + (wake.get("tasks") or [])]
    per_spawn = Counter(a for a, k in spawned if k == "send_followup")
    other = sorted({f"{a}/{k}" for a, k in spawned if k != "send_followup"})
    first_jobs = Counter(a for a, _, _ in snap.values())
    per_made = Counter(a for a, _, _ in made.values())
    per_done = Counter(a for a, st, _ in made.values() if st == "done")
    rows, bad = {}, {}
    for a in aids:
        row = {"rules": len(rule_ids[a]), "first_pass_jobs": first_jobs[a], "jobs": per_made[a],
               "done": per_done[a], "runs": runs[a], "spawned": per_spawn[a]}
        if a == off:
            ok = (first_jobs[a] == per_made[a] == 1 and runs[a] == 0 and per_spawn[a] == 0
                  and all(st == "pending" for x, st, _ in made.values() if x == a))
        else:
            ok = first_jobs[a] == 1 and per_made[a] == per_done[a] == runs[a] == per_spawn[a]
        rows[a] = row
        if not ok:
            bad[a] = row
    errs = [p["error"] for p in (first, wake) if "error" in p]
    ctx.check(dispatch.ONE, not bad and not errs, creators=len(aids), deactivated=off,
              two_rules=sum(1 for v in rule_ids.values() if len(v) == 2), wake_after_s=woke_at,
              first_pass_spawned=len(first.get("tasks") or []), wake_spawned=len(wake.get("tasks") or []),
              bad=dict(list(bad.items())[:4]), other_pairs_spawned=other[:5], errors=errs)
    per_rule = Counter(rid for _, _, rid in after.values())
    cbad = {f"{a}/rule {rid}": per_rule[rid] for a, v in rule_ids.items() for rid in v
            if per_rule[rid] > 1 or (a != off and per_rule[rid] != 1)}
    cerrs = [p["error"] for p in cadence if "error" in p]
    ctx.check(dispatch.CADENCE, not cbad and not cerrs, passes=len(cadence), rules=len(ids),
              jobs=len(after), deferred_then_fired=len(set(after) - set(made)), bad=dict(list(cbad.items())[:6]),
              spawned=[len(p.get("tasks") or []) for p in cadence], errors=cerrs)
    idle_ms = max((p.get("ms") or 0) for p in cadence) if cadence else 0
    ctx.metric("dispatch_plan", {"rules": len(ids), "per_creator": rows, "first_pass_ms": first.get("ms"),
                                 "wake_ms": wake.get("ms"), "wake_after_s": woke_at,
                                 "cadence_ms": [p.get("ms") for p in cadence]})
    ctx.metric("p95_vs_last_green", {"supervisor pass, nothing due (max of the cadence passes)": idle_ms})
    await _rule_off_phase(ctx, w, aids[0])
