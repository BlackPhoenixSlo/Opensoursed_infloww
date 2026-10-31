"""The house funnel walker (`automations.reply_mass_funnel`) after its per-fan status
machine became one pure `decide()` (service/automations/funnel_decide.py): every
Creator's funnel broadcast walked in one tick, fan by fan against the rule his case
puts him under, after his answer came in through the real pump.

World: `agency_inbox` (one Agency, its Creators, their fans, threads for a share of
them), plus seed/house_funnel.py: one 3-step funnel (two lines, one line, a $24 PPV),
one broadcast per Creator 2 h ago to every fan without a seeded thread, and one case
per recipient (new, reply, ppv, buyer: they answer now; waiting, past_end, silent).

Load: `--users` fans answer at once (the repliers, spread over the Creators), each
line a WS frame through `POST /__slop/of-ws-frame` in the pump's shape
(`fan_dm.say`: one frame in flight per Creator); the run waits until each answer is a
`messages` row. Then one tick per Creator, all at once (`POST /__slop/run-automation`,
kind `reply_mass_funnel`, the product's `run_once` under the run-slot pool, payload
`max_chats` = the Creator's recipients so the 40-send cap never thins a tick), then a
second tick the same way.

Invariants (lib/funnel_faults.py names them): DISCOVER (a new replier is enrolled and
gets both lines of step 1 once, a silent recipient gets no walk), ADVANCE (an answer
earns exactly the next step; no answer reschedules, check_count 1, +4 min), PPV (the
PPV step sends one priced PPV, OF's `of_ppv` agrees, the walk ends), OFFER (a fan who
unlocked a PPV since the broadcast is halted offer_taken, sent nothing), END (a walk
past the script's end is closed), COUNTS (new funnel rows carry the fake OF's ids, one
per line the walks' step changes earned, the runs' `advanced` = the walks that moved,
nothing twice, no errors) and AGAIN (tick 2 sends nothing, moves nobody); then
(lib/funnel_jump_faults.py) JUMP_WAIT: a few held-out fans per Creator get a second,
branching broadcast (seed/house_funnel.py `seed_jump`), answer it with its keyword
through the pump, one tick per Creator scoped to that broadcast (`mass_run_id`) sends
step 1 and jumps them to step 5; past their first check, a second scoped tick finds them
quiet and must reschedule on step 1's (the SENT step's) intervals[1], not step 4's
(c - 1) nor step 5's. Budget: each
Creator's run time per due fan (`automation_runs` started -> completed, so not the wait
for a run slot), p95 over the Creators, vs TICK_PER_FAN_P95_MS and the last green run.

Faked or bypassed, declared: OF's send (the offline walker client);
the step's 4 s line gap to 0.2 s (lib/funnel_relay.py); the supervisor's cadence (the
scenario ticks); the buyer's unlock is seeded as the two rows purchase_notifications'
`_flip_paid` leaves (the PPV flipped paid, its `purchase_notices` row;
seed/house_funnel.py); the account DM rate raised to DM_PER_MIN through the real
Concurrency panel route. No LLM: the funnel's steps are static lines. JUMP_WAIT's
clock: between its two ticks the jump fans' `funnel_state.next_check_at` and the send's
60 s cooldown (`fans.automation_paused_until`) are moved to the past by SQL, as if the
first check's 2 minutes had passed (nothing else reads the clock there).

Break-it-once: house-funnel-offer-taken-ignored (decide() never sees a purchase): only
OFFER goes red (the buyer is walked on to step 2, consistently, so COUNTS holds).
house-funnel-jump-waits-prev-step (the pre-F1 c - 1 rule): only JUMP_WAIT goes red (a
linear walk's sent step is c - 1, so the main walk's checks cannot see it).
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import Counter
from datetime import datetime, timedelta

from slop.actors import fan_dm
from slop.lib.funnel_faults import ADVANCE, AGAIN, COUNTS, DISCOVER, END, OFFER, PPV
from slop.lib.funnel_jump_faults import JUMP_WAIT
from slop.seed import house_funnel as hf

PROFILE = "agency_inbox"
UI = False
FAULT = "house-funnel-offer-taken-ignored"
TICK_PER_FAN_P95_MS = 250     # reads + a state write per due fan, plus the sends of the few who answered
P95_VS_LAST = (1.5, 100)
DM_PER_MIN = 600
OF_SEND_ID_BASE = 9_700_000_000_000   # lib/relay.py: the fake OF's message ids (this run's sends)
LIVE_WAIT_S = 60


def _dt(v) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


def _snapshot(con, runs: dict[str, int]) -> dict:
    """Per recipient: his funnel_state, and this run's funnel sends (fake OF ids)."""
    rid = {r: a for a, r in runs.items()}
    q = ",".join("?" * len(rid))
    out: dict[tuple[str, int], dict] = {}
    for r, f, cs, nxt, cc, st, err, ppv_at, hops, last in con.execute(
            f"SELECT mass_run_id, fan_id, current_step, next_check_at, check_count, status, last_error, "
            f"last_ppv_sent_at, hops, last_sent_step FROM funnel_state WHERE mass_run_id IN ({q})", list(rid)):
        out.setdefault((rid[r], int(f)), {})["state"] = {
            "cs": cs, "next": _dt(nxt), "cc": cc, "status": st, "err": err, "ppv_at": _dt(ppv_at),
            "hops": hops, "last": last}
    for a, f, mid, step, price, body in con.execute(
            f"SELECT account_id, fan_id, message_id, funnel_step, price_cents, body FROM messages "
            f"WHERE mass_run_id IN ({q}) AND direction='out' AND message_id >= ?", (*rid, OF_SEND_ID_BASE)):
        out.setdefault((a, int(f)), {}).setdefault("sent", []).append(
            {"id": int(mid), "step": step, "price": int(price or 0), "body": body})
    return out


async def _await_landed(con, recs: list[dict]) -> tuple[set, set]:
    """-> (accepted, landed): the answers the hook took, and those that are a
    `messages` row within LIVE_WAIT_S."""
    ids = {(x["account_id"], int(x["fan_id"]), int(x["message_id"])) for x in recs if x.get("status", 599) < 300}
    deadline = time.monotonic() + LIVE_WAIT_S
    landed: set = set()
    while time.monotonic() < deadline:
        landed = {(a, int(f), int(m)) for a, f, m in con.execute(
            "SELECT account_id, fan_id, message_id FROM messages WHERE direction='in' AND message_id >= ?",
            (fan_dm.SAY_ID_BASE,))} & ids
        if len(landed) == len(ids):
            break
        await asyncio.sleep(0.25)
    return ids, landed


async def _tick(ctx, aid: str, n: int, run: int | None = None) -> dict:
    t = time.perf_counter()
    payload = {"max_chats": max(1, n), **({"mass_run_id": run} if run is not None else {})}
    r = await ctx.owner.post("/__slop/run-automation", timeout=900, json={
        "account_id": aid, "kind": "reply_mass_funnel", "payload": payload})
    body = r.json() if r.status_code < 300 else {"error": r.text[:300]}
    return {"aid": aid, "status": r.status_code, "ms": (time.perf_counter() - t) * 1000,
            "res": body.get("result") if isinstance(body.get("result"), dict) else body}


def _verdict(pred, fans, after) -> tuple[bool, dict]:
    bad = [k for k in fans if not pred(k)]
    return not bad, {"fans": len(fans), "wrong": len(bad),
                     "e.g.": {f"{a}/{f}": str(after.get((a, f), ""))[:300] for a, f in bad[:3]}}


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    seeded = hf.seed(w, w.data["fans"], w.data["threads"], live=max(1, ctx.users))
    cases, runs = seeded["cases"], seeded["runs"]
    aids = sorted(runs)
    ctx.metric("classes", dict(Counter(cases.values())))
    r = await ctx.owner.post("/lanes-panel/config", json={"values": {"OF_DM_PER_MIN": DM_PER_MIN}})
    ctx.metric("dm_per_min", {"set": DM_PER_MIN, "status": r.status_code})

    con = w.sql()
    before = _snapshot(con, runs)
    fan_by = {(f["account_id"], f["id"]): f for fl in w.data["fans"].values() for f in fl}
    repliers = [k for k, c in cases.items() if c in hf.LIVE]

    # The answers, through the real pump, then wait until each one is a row.
    ctx.rec.stage = "answers"
    recs = await fan_dm.say(ctx.owner, [(fan_by[k], "yes 😍") for k in repliers])
    ids, landed = await _await_landed(con, recs)
    ctx.rec.stage = None
    ctx.metric("answers", {"sent": len(recs), "accepted": len(ids), "landed": len(landed)})

    per_aid = Counter(a for a, _f in cases)
    ctx.rec.stage = "tick1"
    t0 = datetime.utcnow()
    ticks = await asyncio.gather(*(_tick(ctx, a, per_aid[a]) for a in aids))
    t1 = datetime.utcnow()
    ctx.rec.stage = None
    after = _snapshot(con, runs)
    calls = (await ctx.owner.get("/__slop/fake/calls")).json()
    ctx.rec.stage = "tick2"
    ticks2 = await asyncio.gather(*(_tick(ctx, a, per_aid[a]) for a in aids))
    ctx.rec.stage = None
    after2 = _snapshot(con, runs)
    run_rows = {}
    for a, st_, done, stats in con.execute(
            "SELECT account_id, started_at, completed_at, stats_json FROM automation_runs "
            "WHERE kind='reply_mass_funnel' AND completed_at IS NOT NULL ORDER BY id"):
        run_rows.setdefault(str(a), (_dt(st_), _dt(done), json.loads(stats or "{}")))
    con.close()

    def st(k, snap=None):
        return (snap or after).get(k, {}).get("state")

    def sent(k, snap=None):
        return (snap or after).get(k, {}).get("sent", [])

    def by(*names):
        return [k for k, c in cases.items() if c in names]

    answered = {(a, f) for a, f, _m in landed}

    def landed_ok(k) -> bool:   # his answer is in, or the case is not a replier
        return cases[k] not in hf.LIVE or k in answered

    def lines(k, step):
        return [x for x in sent(k) if x["step"] == step]

    # DISCOVER: enrolled at step 1 with both lines; a silent recipient has no walk.
    def discover(k):
        if cases[k] == "silent":
            return st(k) is None and not sent(k)
        s = st(k) or {}
        return (landed_ok(k) and s.get("cs") == 1 and s.get("status") == "pending" and s.get("cc") == 0
                and len(sent(k)) == hf.LINES[1] == len(lines(k, 1))
                and all(x["price"] == 0 for x in sent(k)))
    ok, d = _verdict(discover, by("new", "silent"), after)
    ctx.check(DISCOVER, ok and any(cases[k] == "new" for k in cases), **d)

    # ADVANCE: an answer earns exactly the next step; no answer is a reschedule.
    def advance(k):
        s = st(k) or {}
        if cases[k] == "waiting":
            nxt = s.get("next")
            return (not sent(k) and s.get("cs") == 1 and s.get("cc") == 1 and s.get("status") == "pending"
                    and nxt is not None and t0 + timedelta(minutes=4) - timedelta(seconds=5)
                    <= nxt <= t1 + timedelta(minutes=4) + timedelta(seconds=5))
        return (landed_ok(k) and s.get("cs") == 2 and s.get("status") == "pending" and s.get("cc") == 0
                and len(sent(k)) == hf.LINES[2] == len(lines(k, 2)) and sent(k)[0]["price"] == 0)
    ok, d = _verdict(advance, by("reply", "waiting"), after)
    ctx.check(ADVANCE, ok and d["fans"] > 0, **d)

    # PPV: one priced PPV, OF has it at the step's price, the walk is done.
    of_ppv = calls.get("of_ppv") or {}

    def ppv(k):
        s = st(k) or {}
        return (landed_ok(k) and s.get("cs") == 3 and s.get("status") == "done" and s.get("ppv_at") is not None
                and len(sent(k)) == 1 and sent(k)[0]["step"] == 3 and sent(k)[0]["price"] == hf.PPV_PRICE * 100
                and of_ppv.get(f"{k[0]}:{k[1]}") == [hf.PPV_PRICE * 100])
    ok, d = _verdict(ppv, by("ppv"), after)
    ctx.check(PPV, ok and d["fans"] > 0, **d)

    # OFFER: a buyer who answered is halted offer_taken and sent nothing.
    def offer(k):
        s = st(k) or {}
        return landed_ok(k) and not sent(k) and s.get("status") == "done" and s.get("err") == "offer_taken" \
            and s.get("cs") == 1
    ok, d = _verdict(offer, by("buyer"), after)
    ctx.check(OFFER, ok and d["fans"] > 0, **d)

    # END: a walk past the script's end is closed, nothing sent.
    ok, d = _verdict(lambda k: not sent(k) and (st(k) or {}).get("status") == "done"
                     and (st(k) or {}).get("cs") == 3, by("past_end"), after)
    ctx.check(END, ok and d["fans"] > 0, **d)

    # COUNTS: the rows are the lines the step changes earned; the runs agree; nothing twice.
    def cs_of(k, snap):
        return (st(k, snap) or {}).get("cs") or 0
    moved = [k for k in cases if cs_of(k, after) > cs_of(k, before) and sent(k)]
    earned = sum(hf.LINES[s] for k in moved for s in range(cs_of(k, before) + 1, cs_of(k, after) + 1))
    rows = sum(len(sent(k)) for k in cases)
    priced = sum(1 for k in cases for x in sent(k) if x["price"])
    of_ppv_n = sum(len(v) for kk, v in of_ppv.items() if kk.split(":")[0] in runs)
    twice = [f"{a}/{f}" for (a, f) in cases
             if len({(x["step"], x["body"]) for x in sent((a, f))}) != len(sent((a, f)))]
    res = [t["res"] or {} for t in ticks]
    advanced = sum(int(x.get("advanced") or 0) for x in res)
    errs = {t["aid"]: {k: (t["res"] or {}).get(k) for k in ("errors", "cap_hit", "key_error", "error", "status")
                       if (t["res"] or {}).get(k)} for t in ticks
            if t["status"] != 200 or any((t["res"] or {}).get(k) for k in ("errors", "cap_hit", "key_error", "error"))}
    ctx.check(COUNTS, rows > 0 and rows == earned and advanced == len(moved) and priced == of_ppv_n
              and not twice and not errs,
              rows=rows, earned_lines=earned, walks_moved=len(moved), runs_advanced=advanced,
              priced_rows=priced, of_ppv=of_ppv_n, twice=twice[:5], errors=errs)

    # AGAIN: a second tick right away moves nobody and sends nothing.
    rows2 = sum(len(sent(k, after2)) for k in cases)
    changed = [f"{a}/{f}" for (a, f) in cases if st((a, f), after2) != st((a, f), after)]
    adv2 = sum(int((t["res"] or {}).get("advanced") or 0) for t in ticks2)
    ctx.check(AGAIN, rows2 == rows and adv2 == 0 and not changed and all(t["status"] == 200 for t in ticks2),
              new_rows=rows2 - rows, advanced=adv2, states_changed=len(changed), e_g=changed[:3])

    # The product's own run time per due fan (automation_runs), not the wait for a run slot.
    per_fan = []
    for a in aids:
        if a not in run_rows:
            continue
        s0, s1, stats = run_rows[a]
        due = sum(int(stats.get(k) or 0) for k in ("advanced", "waiting", "completed", "converted", "blocked"))
        per_fan.append((s1 - s0).total_seconds() * 1000 / max(1, due))
    per_fan.sort()
    p95 = per_fan[min(len(per_fan) - 1, int(round(0.95 * (len(per_fan) - 1))))] if per_fan else float("inf")
    ctx.check(f"run time per due fan p95 <= {TICK_PER_FAN_P95_MS} ms", p95 <= TICK_PER_FAN_P95_MS,
              budget=True, p95_ms=round(p95, 1), per_creator=[round(x, 1) for x in per_fan])
    ctx.metric("p95_vs_last_green", {"tick per due fan": round(p95, 1)})
    ctx.metric("ticks", [{"aid": t["aid"], "status": t["status"], "ms": round(t["ms"], 1),
                          **{k: (t["res"] or {}).get(k) for k in (
                              "discovered", "advanced", "waiting", "completed", "converted", "branched",
                              "blocked", "skipped_locked", "skipped_cooldown", "errors")}} for t in ticks])
    ctx.metric("ticks2", [{"aid": t["aid"], **{k: (t["res"] or {}).get(k) for k in (
        "discovered", "advanced", "waiting", "completed", "skipped_locked", "skipped_cooldown")}} for t in ticks2])
    ctx.note(f"{len(repliers)} answers ({len(landed)} landed); tick 1: {rows} lines to {len(moved)} walks over "
             f"{len(aids)} Creators; tick 2: {rows2 - rows}; per-due-fan p95 {p95:.0f} ms")

    await _jump_wait(ctx, w, seeded["jump_fans"], fan_by)


async def _jump_wait(ctx, w, held: dict, fan_by: dict) -> None:
    """JUMP_WAIT: answer the branching broadcast with its keyword, tick (step 1 sent,
    jumped to step 5), move the clock past the first check, tick again (quiet): the
    next check is the SENT step's intervals[1] away."""
    jump = hf.seed_jump(w, held)
    jfans, jruns = jump["fans"], jump["runs"]
    if not jfans:
        ctx.check(JUMP_WAIT, False, reason="no held-out fans to jump (pool too small)")
        return
    con = w.sql()
    ctx.rec.stage = "jump"
    recs = await fan_dm.say(ctx.owner, [(fan_by[k], f"ok {hf.JUMP_WORD} 😍") for k in jfans])
    _ids, landed = await _await_landed(con, recs)
    per = Counter(a for a, _f in jfans)
    t1 = await asyncio.gather(*(_tick(ctx, a, per[a], jruns[a]) for a in sorted(jruns)))
    jumped = _snapshot(con, jruns)
    # The clock past the first check (intervals[0]) and the send's cooldown: declared, SQL.
    past = hf.ts(datetime.utcnow() - timedelta(seconds=1))
    with con:
        con.execute(f"UPDATE funnel_state SET next_check_at=? WHERE mass_run_id IN ({','.join('?' * len(jruns))})",
                    (past, *jruns.values()))
        con.executemany("UPDATE fans SET automation_paused_until=NULL WHERE account_id=? AND fan_id=?", jfans)
    a0 = datetime.utcnow()
    t2 = await asyncio.gather(*(_tick(ctx, a, per[a], jruns[a]) for a in sorted(jruns)))
    a1 = datetime.utcnow()
    ctx.rec.stage = None
    quiet = _snapshot(con, jruns)
    con.close()

    want_min = hf.JUMP_STEPS[hf.JUMP_FROM]["check_intervals_min"][1]
    lo, hi = a0 + timedelta(minutes=want_min, seconds=-5), a1 + timedelta(minutes=want_min, seconds=5)

    def state(snap, k) -> dict:
        return snap.get(k, {}).get("state") or {}

    def n_sent(snap, k) -> int:
        return len(snap.get(k, {}).get("sent", []))

    def ok(k) -> bool:
        j, q = state(jumped, k), state(quiet, k)
        return (j.get("cs") == hf.JUMP_TO and j.get("cc") == 0 and j.get("last") == hf.JUMP_FROM
                and n_sent(jumped, k) == len(hf.JUMP_STEPS[hf.JUMP_FROM]["messages"])
                and q.get("cs") == hf.JUMP_TO and q.get("cc") == 1 and q.get("status") == "pending"
                and n_sent(quiet, k) == n_sent(jumped, k) and q.get("next") is not None and lo <= q["next"] <= hi)
    bad = [k for k in jfans if not ok(k)]
    errs = [t["aid"] for t in (*t1, *t2) if t["status"] != 200 or (t["res"] or {}).get("errors")]
    got = sorted({round(((state(quiet, k).get("next") or a0) - a0).total_seconds() / 60) for k in bad})
    ctx.check(JUMP_WAIT, not bad and not errs and len(landed) == len(jfans),
              fans=len(jfans), landed=len(landed), wrong=len(bad), want_next_check_min=want_min,
              got_min=got[:5], errors=errs,
              e_g={f"{a}/{f}": (str(jumped.get((a, f))), str(quiet.get((a, f)))) for a, f in bad[:2]})
    ctx.metric("jump", {"fans": len(jfans), "tick1": [{k: (t["res"] or {}).get(k) for k in (
        "discovered", "advanced", "errors")} for t in t1], "tick2": [{k: (t["res"] or {}).get(k) for k in (
            "advanced", "waiting", "skipped_cooldown", "errors")} for t in t2]})
