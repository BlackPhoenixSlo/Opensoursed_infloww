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

Faked or bypassed, declared: OF's send (lib/automation_relay.py's offline walker client);
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

KILL, last (send once, service/automations/send_marker_decide.py: a step killed mid-send is
never auto-resent; listed "may not have sent", the user retries). KILL Creators = the first
min(KILL_CREATORS, Creators) (KILL_CREATORS = the 4 run slots: every hung run holds one), each
with seed/house_funnel.py `seed_kill`'s third funnel and broadcast: three walking fans on its
PPV step (bubble 0 the PPV) with their answer in, one `control` fan with none. OF's side is
lib/send_once_relay.py (`first_key: fan_text`): `partial` OF takes the PPV and refuses bubble 1
with a 400; `partial_noid` the same, the PPV answered without its id; `kill` OF takes the PPV and
never answers (`hang`), but on the last KILL Creator takes the PPV, answers it, and hangs on
bubble 1 (`hang_after_first`: the landed fan). One tick per KILL Creator scoped to its run (own
Recorder: they die with the relay) until each `kill` fan's text is taken and unanswered, the same
set for KILL_STABLE_S; SIGKILL (`crash_relay`); OF answers every fan normally from then on; restart
on the same DB. Then one DM through the pump per `kill`, `partial_noid` and `control` fan, one welcome
chatter run per KILL Creator scoped to them (`only_fan_ids`), two funnel ticks (each settles
first), the owner's `GET /admin/unconfirmed-sends`, one `POST /admin/unconfirmed-sends/retry`
per hung (not landed) fan, one more tick. Checks (lib/send_marker_faults.py): FUNNEL_ONCE,
FUNNEL_MARKED, FUNNEL_SETTLED, FUNNEL_RETRY, FUNNEL_PARTIAL, FUNNEL_PARTIAL_NOID,
FUNNEL_PARKED_QUIET, and the scenario's own KILLED. Faked, declared: the agency's (fake)
DeepSeek key through the real `PUT /admin/my-llm-keys` and lib/wcfi_relay.py's DeepSeek answer
(the KILL Creators carry its persona). Bypasses, declared: the KILL fans' `fan_lease` rows (the
dead holder's 900 s TTL) expired by SQL right after the restart, as if 15 min had passed; the
retried fans' send rest (`fans.automation_paused_until`) nulled by SQL before the last tick.
Expected tracebacks, declared (EXPECTED_TRACEBACKS): the walker's `reply_mass_funnel send
failed` on the slop 400s, and the welcome chatter's nick push / mark-read on the offline OF.
Faults (each must turn only its targets red): funnel-partial-requeued, funnel-noid-not-counted,
funnel-marker-sets-status, funnel-sending-marker-ignored, funnel-settle-skips-lookup.
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
from slop.lib.send_marker_faults import (FUNNEL_MARKED, FUNNEL_ONCE, FUNNEL_PARKED_QUIET, FUNNEL_PARTIAL,
                                         FUNNEL_PARTIAL_NOID, FUNNEL_RETRY, FUNNEL_SETTLED)
from slop.lib.send_marker_kill import Kill
from slop.lib.send_once_relay import SLOP_MARK
from slop.seed import house_funnel as hf

PROFILE = "agency_inbox"
UI = False
FAULT = "house-funnel-offer-taken-ignored"
TICK_PER_FAN_P95_MS = 250     # reads + a state write per due fan, plus the sends of the few who answered
P95_VS_LAST = (1.5, 100)
DM_PER_MIN = 600
OF_SEND_ID_BASE = 9_700_000_000_000   # lib/relay.py: the fake OF's message ids (this run's sends)
LIVE_WAIT_S = 60
EXPECTED_TRACEBACKS = (("reply_mass_funnel send failed", SLOP_MARK),
                       ("push_nick_failed", "slop: OF is offline"),
                       ("mark_chat_read failed", "slop: OF is offline"))
KILL_CREATORS = 4      # the run slots (run_slot): one hung run per Creator, every slot busy
KILL_HANG_S = 300.0    # the kill comes long before
KILL_TIMEOUT_S = 120
KILL_STABLE_S = 3.0
KILLED = "house funnel kill: SIGKILL landed with each KILL Creator's kill fan's step taken by OF and unanswered"


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
    await _kill_phase(ctx, w, fan_by)


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


async def _tick_on(http, aid: str, run: int) -> dict:
    """_tick on `http` (the KILL phase's own pools), scoped to the KILL run."""
    r = await http.post("/__slop/run-automation", timeout=900, json={
        "account_id": aid, "kind": "reply_mass_funnel", "payload": {"max_chats": 10, "mass_run_id": run}})
    body = r.json() if r.status_code < 300 else {"error": r.text[:300]}
    return {"aid": aid, "status": r.status_code,
            "res": body.get("result") if isinstance(body.get("result"), dict) else body}


async def _kill_phase(ctx, w, fan_by: dict) -> None:
    """KILL (module docstring): a step killed after OF took it is listed, never re-sent by
    a tick, sent once more only on the user's Retry; a step that surely landed advances."""
    kaids = sorted(w.data["fans"])[:min(KILL_CREATORS, len(w.data["fans"]))]
    seeded = hf.seed_kill(w, w.data["threads"], kaids)
    kruns, roles = seeded["runs"], seeded["fans"]
    kaids = sorted(kruns)
    if not kaids:
        ctx.check(KILLED, False, reason="no Creator with four threaded fans (pool too small)")
        return
    landed_aid = kaids[-1]
    mode = {"kill": "hang", "partial": "4xx_after_first", "partial_noid": "noid_4xx_after_first"}
    hang = {(a, r["kill"]) for a, r in roles.items()}
    keys = {(a, f) for a, r in roles.items() for f in r.values()}
    walking = {(a, r[x]) for a, r in roles.items() for x in hf.KILL_ROLES}
    fans_cfg = {f"{a}:{r[x]}": ("hang_after_first" if x == "kill" and a == landed_aid else mode[x])
                for a, r in roles.items() for x in hf.KILL_ROLES}
    ppv, b1 = hf.KILL_STEPS[hf.KILL_PPV_STEP]["messages"]
    funnel_texts = {m for st in hf.KILL_STEPS for m in st["messages"]}
    ppv_step = hf.KILL_STEPS[hf.KILL_PPV_STEP]["step"]
    r = await ctx.owner.put("/admin/my-llm-keys", json={"deepseek": "slop-fake-deepseek"})
    ctx.metric("kill_deepseek_key", {"status": r.status_code})

    ctx.rec.stage = "kill"
    kill = Kill(ctx, keys, {a: roles[a]["kill"] for a in kaids}, lambda http, a: _tick_on(http, a, kruns[a]),
             KILL_HANG_S)
    hit, hung_text, waited = await kill.crash(fans_cfg, KILL_TIMEOUT_S, KILL_STABLE_S)
    t_kill = kill.t_kill
    want_hung = {k: (b1 if k[0] == landed_aid else ppv) for k in hang}
    ctx.check(KILLED, hit and hung_text == want_hung, kill_creators=len(kaids), hung_at_kill=len(hung_text),
              waited_s=waited, hung={f"{a}/{f}": t[:24] for (a, f), t in sorted(hung_text.items())})
    con = w.sql()
    kill.expire_leases(con)

    owner = kill.owner
    quiet = [(a, roles[a][x]) for a in kaids for x in ("kill", "partial_noid", "control")]
    recs = await fan_dm.say(owner, [(fan_by[k], "you there? 😘") for k in quiet])
    _ids, dm_landed = await _await_landed(con, recs)
    wcfi = []
    for a in kaids:
        r = await owner.post("/__slop/run-automation", timeout=900, json={
            "account_id": a, "kind": "welcome_chatter_for_info",
            "payload": {"only_fan_ids": [f for (x, f) in quiet if x == a]}})
        wcfi.append({"aid": a, "status": r.status_code,
                     "res": {k: v for k, v in ((r.json().get("result") or {}) if r.status_code == 200 else {}).items()
                             if not isinstance(v, (list, dict))}})
    ticks = [await kill.tick_all()]
    settled = _snapshot(con, kruns)
    ticks.append(await kill.tick_all())
    listed, get_status = await kill.unconfirmed()
    retry_fans = sorted(k for k in hang if k[0] != landed_aid)
    retried = await kill.retry(con, {(a, f): {"kind": "funnel", "fan_id": f, "mass_run_id": kruns[a]}
                                  for a, f in retry_fans})
    t_retry = kill.t_retry
    ticks.append(await kill.tick_all())
    rid = {r_: a for a, r_ in kruns.items()}
    marker = {(rid[r_], int(f)): (sa, ua) for r_, f, sa, ua in con.execute(
        f"SELECT mass_run_id, fan_id, sending_at, unconfirmed_at FROM funnel_state "
        f"WHERE mass_run_id IN ({','.join('?' * len(rid))})", list(rid))}
    final = _snapshot(con, kruns)
    con.close()
    await kill.close()
    ctx.rec.stage = None

    rows = kill.journal()
    took, pre = kill.took(), kill.pre_retry()
    ops = Counter((x["account_id"], int(x["fan_id"]), x["op"], x.get("id") is None) for x in rows)

    def st(snap, k) -> dict:
        return snap.get(k, {}).get("state") or {}

    def eg(ks) -> dict:
        return {f"{a}/{f}": {"settled": str(st(settled, (a, f))), "final": str(st(final, (a, f))),
                             "marker": str(marker.get((a, f))), "listed": listed.get((a, f)),
                             "of": {t[:20]: n for (x, y, t), n in took.items() if (x, y) == (a, f)}}
                for a, f in ks[:2]}

    def once(k) -> bool:
        mine = {t: n for (a, f, t), n in took.items() if (a, f) == k and t in funnel_texts}
        if any(n > 1 for (a, f, t), n in pre.items() if (a, f) == k and t in funnel_texts):
            return False
        if k in retry_fans:
            return all(n == (2 if t == hung_text.get(k) else 1) for t, n in mine.items())
        return all(n <= 1 for n in mine.values())
    bad = [k for k in sorted(walking) if not once(k)]
    ctx.check(FUNNEL_ONCE, not bad, fans=len(walking), wrong=len(bad), e_g=eg(bad))

    def marked(k) -> bool:
        row = listed.get(k) or {}
        return (row.get("kind") == "funnel" and row.get("mass_run_id") == kruns[k[0]]
                and row.get("state") == "UNCONFIRMED" and row.get("step") == ppv_step)
    bad = [k for k in retry_fans if not marked(k)]
    ctx.check(FUNNEL_MARKED, bool(retry_fans) and not bad and all(x == 200 for x in get_status),
              fans=len(retry_fans), wrong=len(bad), get_status=get_status, e_g=eg(bad))

    lk = (landed_aid, roles[landed_aid]["kill"])
    s1 = st(settled, lk)
    settled_ok = (s1.get("status") == "done" and marker.get(lk) == (None, None) and lk not in listed
                  and s1.get("ppv_at") is not None and s1["ppv_at"] <= datetime.utcfromtimestamp(t_kill)
                  and took[(*lk, ppv)] == 1)
    ctx.check(FUNNEL_SETTLED, settled_ok, e_g=eg([lk]))

    def retry_ok(k) -> bool:
        after = Counter(x["text"] for x in rows if (x["account_id"], int(x["fan_id"])) == k
                        and x["op"] == "accepted" and x["t"] >= t_retry)
        return (retried.get(k) == (200, "retried") and after[ppv] == 1 and st(final, k).get("status") == "done"
                and marker.get(k) == (None, None))
    bad = [k for k in retry_fans if not retry_ok(k)]
    ctx.check(FUNNEL_RETRY, bool(retry_fans) and not bad, fans=len(retry_fans), wrong=len(bad),
              retry={f"{a}/{f}": v for (a, f), v in sorted(retried.items())}, e_g=eg(bad))

    parts = [(a, r["partial"]) for a, r in sorted(roles.items())]
    bad = [k for k in parts if not (ops[(*k, "rejected", True)] >= 1 and took[(*k, ppv)] == 1
                                    and st(final, k).get("status") == "done")]
    ctx.check(FUNNEL_PARTIAL, bool(parts) and not bad, fans=len(parts), wrong=len(bad), e_g=eg(bad))

    noids = [(a, r["partial_noid"]) for a, r in sorted(roles.items())]
    bad = [k for k in noids if not (ops[(*k, "returned", True)] >= 1 and ops[(*k, "rejected", True)] >= 1
                                    and took[(*k, ppv)] == 1 and (marker.get(k) or (None, None))[1] is not None
                                    and (listed.get(k) or {}).get("state") == "UNCONFIRMED")]
    ctx.check(FUNNEL_PARTIAL_NOID, bool(noids) and not bad, fans=len(noids), wrong=len(bad), e_g=eg(bad))

    chat = Counter((x["account_id"], int(x["fan_id"])) for x in rows
                   if x["op"] == "accepted" and x["t"] >= t_kill and x["text"] not in funnel_texts)
    parked = [k for k in quiet if roles[k[0]]["control"] != k[1]]
    controls = [(a, r["control"]) for a, r in sorted(roles.items())]
    bad = [k for k in parked if chat[k]] + [k for k in controls if not chat[k]]
    ctx.check(FUNNEL_PARKED_QUIET, bool(controls) and not bad and len(dm_landed) == len(quiet)
              and all(x["status"] == 200 for x in wcfi), parked=len(parked), controls=len(controls),
              dms_landed=len(dm_landed), wrong=[f"{a}/{f}" for a, f in bad[:5]],
              chat_lines={f"{a}/{f}": chat[(a, f)] for a, f in quiet}, wcfi=wcfi)
    ctx.metric("kill", {"creators": len(kaids), "t_kill": t_kill, "ticks": [
        [{k: (t["res"] or {}).get(k) for k in ("advanced", "completed", "skipped_locked",
                                                "skipped_cooldown", "errors")} | {"status": t["status"]}
         for t in tk] for tk in ticks], "kill_ticks_http": kill.rec.summary()})
