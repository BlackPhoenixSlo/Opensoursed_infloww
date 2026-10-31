"""The follow-up drip (`automations.send_followup`) after its phase machine became one
pure `decide()` (service/automations/send_followup_decide.py): one tick on every Creator
at once over an inbox-sized world, checked fan by fan against the rule each fan's history
puts him under, while the owner's dashboard tabs watch the live stream.

World: `agency_inbox` (one Agency, its Creators, their fans, threads for a share of them),
plus seed/followup_drip.py: every eligible fan (>= $1 spend) without a thread gets one
drip case (due step 1, due step 2, inside the 18 h gap, past the 7-day cap, a reply
mid-drip, a reply after the drip, finished and silent, an expired reply / restart
cooldown, still cooling). The threaded eligible fans are the natural mix: no state row,
their last message decides (his -> reply, ours 26 h..7 days ago -> step 1, older ->
retired, newer -> nothing); a fan within an hour of the 26 h or 7-day line is left out of
the per-rule checks (`edge`), never out of the counts.

Load: the owner's dashboard tab (actors/manager.OwnerTab: the All-scope reads, its
`/events` stream, inbox re-reads) and `--users` more `/events` streams on the owner's
session (each one dashboard tab's live channel, where every nudge fans out), opened before
the tick over TAB_RAMP_S (20 s, `--set tab_ramp_s=`). Not `--users` full dashboard tabs: 200
of them re-reading the inbox every 10 s saturate the relay's dashboard reads (/admin/accounts
14 s, measured: evidence 20261029T231950Z-2026-10-30-followup-drip-ddb7, stopped), which is
2026-10-28-dashboard-load's flow, and drown the drip's own timing; the tick is
`POST /__slop/run-automation` (kind `send_followup`, the product's `run_once` under the
run-slot pool, lib/followup.py `tick`) for every Creator at once; then a second tick the same way.

Invariants: per rule (lib/followup_faults.py names them): the gap, the steps, the cap,
reply vs restart cooldowns, cooldown expiry before the sweep, the fans held; then the
counts (LLM calls = OF sends = new followup rows = recorded steps = the runs'
followups_sent, one nudge per fan at most, no errors), every nudge on every tab's stream,
and a second tick that nudges nobody, its just-nudged fans held by the drip's gap
(its contact-guard and send-rest holds equal tick 1's, Creator by Creator). Budget: each Creator's run time per nudge
(`automation_runs` started -> completed, so not the wait for one of the executor's run
slots), p95 over the Creators, vs TICK_PER_NUDGE_P95_MS and the last green run.

Faked or bypassed, declared: DeepSeek at its HTTP boundary (a loopback fake: one fixed
line for the nudge, 0.4 s); OF's send (lib/relay.py `_OfflineOF.send_message`); the
supervisor's cadence (the scenario ticks; payload `with_image: false`, so the vault is
never read, and `limit` = fans per Creator, so the 200-fan sweep ceiling never thins a
tick); the account DM rate raised to DM_PER_MIN (lib/followup.py) through the real Concurrency panel route.
SLOP_LIVE=1 is refused (it would spend on the real DeepSeek): every check SKIPs.

Break-it-once: followup-skips-18h-gap (`_MIN_GAP_H` = 0): only the two gap checks go red
(GAP, and AGAIN: without the gap the contact guard is what holds tick 2).

The run slot pool and the dispatch plan these ticks once also checked are their own flows:
2026-10-30-run-slot-pool and 2026-10-30-dispatch-plan (same world, lib/followup.py).

A bad tz_offset_minutes (lib/dispatch_tz_faults.py BAD_TZ), after the checks above: one
send_followup clock rule whose stored offset is "x" is written on the last Creator
(seed/followup_drip.py `seed_bad_tz_rule`; declared bypass: raw SQL, a hand-edited row the rules
API refuses; only this phase writes it, so the other follow-up flows never see it). The owner adds
two good follow-up rules through the real rules route (`POST /admin/automation-rules`): an
interval one on the first Creator and a daily_at one on the second, in UTC+5:30 with its slot
10 min ago (creator-local). One real supervisor pass (`POST /__slop/automation-tick`). BAD_TZ:
the bad rule makes no job, each good rule exactly one, inside the pass; the list route answers
for all three, a good rule's `next_due_at` (dispatch_plan.next_due) was due before the pass and
after it is the next fire (interval: its job + 1 h; clock: the slot tomorrow); the bad rule's is
null. Their runs nudge nobody (tick 2 showed every fan held). Expected traceback, declared: under
--fault=dispatch-bad-tz-aborts-pass the pass logs `automation_rule_materialize_failed` with the
pre-fix ValueError on "x" (EXPECTED_TRACEBACKS), so only BAD_TZ goes red (the list route reads
the quiet `dispatch_plan.trigger_of`, which the fault leaves alone).
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import Counter
from datetime import datetime, timedelta

from slop.actors import manager
from slop.lib import followup
from slop.lib.dispatch_tz_faults import BAD_TZ
from slop.lib.followup_faults import AGAIN, CAP, COUNTS, GAP, HOLD, LIVE, REPLIES, RESUME, STEPS
from slop.seed.followup_drip import BAD_TZ_RAW, seed_bad_tz_rule

PROFILE = "agency_inbox"
UI = False
FAULT = "followup-skips-18h-gap"
TICK_PER_NUDGE_P95_MS = 1500    # 0.4 s fake LLM + the send + the state writes, per nudge
P95_VS_LAST = (1.5, 300)
OF_SEND_ID_BASE = 9_700_000_000_000   # lib/relay.py: the fake OF's message ids (this run's sends)
EDGE_H = 1.0
TAB_RAMP_S = 20.0
BAD_TZ_EVERY_S = 3600
BAD_TZ_OFFSET_MIN = 330          # a half-hour zone (Kolkata)
EXPECTED_TRACEBACKS = (("automation_rule_materialize_failed",
                        f"invalid literal for int() with base 10: {BAD_TZ_RAW!r}"),)


def _dt(v) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


def _snapshot(con, aids: list[str]) -> dict:
    """Per eligible fan: his followup_state row, last in/out, and this run's nudges."""
    q = ",".join("?" * len(aids))
    fans = {(a, int(f)): {} for a, f in con.execute(
        f"SELECT account_id, fan_id FROM fans WHERE account_id IN ({q}) AND lifetime_spend_cents >= 100 "
        "AND (total_likes IS NULL OR total_likes >= 1)", aids)}
    for a, f, d, at in con.execute(
            f"SELECT account_id, fan_id, direction, MAX(created_at) FROM messages WHERE account_id IN ({q}) "
            "AND direction IN ('in','out') GROUP BY account_id, fan_id, direction", aids):
        if (a, int(f)) in fans:
            fans[a, int(f)][d] = _dt(at)
    for a, f, phase, cycle, until, sent in con.execute(
            f"SELECT account_id, fan_id, phase, cycle, cooldown_until, messages_sent FROM followup_state "
            f"WHERE account_id IN ({q})", aids):
        if (a, int(f)) in fans:
            fans[a, int(f)]["state"] = {"phase": phase, "cycle": cycle, "until": _dt(until),
                                        "sent": json.loads(sent or "{}")}
    for a, f, mid in con.execute(
            f"SELECT account_id, fan_id, message_id FROM messages WHERE account_id IN ({q}) AND direction='out' "
            "AND automation_kind='followup' AND message_id >= ?", (*aids, OF_SEND_ID_BASE)):
        if (a, int(f)) in fans:
            fans[a, int(f)].setdefault("nudges", []).append(int(mid))
    return fans


def _natural(row: dict, now: datetime) -> str:
    """The rule a threaded fan (no state row) falls under, from his last messages."""
    li, lo = row.get("in"), row.get("out")
    if li and (lo is None or li > lo):
        return "n_reply"
    if lo is None:
        return "n_none"
    silence = (now - lo).total_seconds() / 3600
    if min(abs(silence - 26), abs(silence - 24 * 7)) < EDGE_H:
        return "edge"
    if silence > 24 * 7:
        return "n_cap"
    return "n_due" if silence >= 26 else "n_wait"


def _verdict(pred, fans, after=None) -> tuple[bool, dict]:
    bad = [(a, f) for (a, f) in fans if not pred(a, f)]
    eg = {f"{a}/{f}": str((after or {}).get((a, f), ""))[:300] for a, f in bad[:3]}
    return not bad, {"fans": len(fans), "wrong": len(bad), "e.g.": eg}


async def _bad_tz_phase(ctx, w, aids: list[str]) -> None:
    """One supervisor pass with a bad-tz rule among good ones (module docstring: BAD_TZ)."""
    ctx.rec.stage = "bad-tz"
    bad_rid = seed_bad_tz_rule(w, aids[-1])   # first: the lowest id of the three
    local = datetime.utcnow() + timedelta(minutes=BAD_TZ_OFFSET_MIN)
    slot_m = max(0, local.hour * 60 + local.minute - 10)
    slot = f"{slot_m // 60:02d}:{slot_m % 60:02d}"
    slot_utc = local.replace(hour=slot_m // 60, minute=slot_m % 60, second=0, microsecond=0) \
        - timedelta(minutes=BAD_TZ_OFFSET_MIN)
    good: dict[int, str] = {}
    for aid, body in ((aids[0], {"every_seconds": BAD_TZ_EVERY_S}),
                      (aids[1], {"trigger": {"daily_at": [slot], "tz_offset_minutes": BAD_TZ_OFFSET_MIN}})):
        r = await ctx.owner.post("/admin/automation-rules", json={
            "account_id": aid, "kind": "send_followup", "payload": followup.payload(ctx), **body})
        r.raise_for_status()
        good[int(r.json()["id"])] = "interval" if "every_seconds" in body else "clock"
    owners = {aids[0], aids[1], aids[-1]}

    async def listed() -> tuple[dict, list]:
        rows, bad_status = {}, []
        for a in sorted(owners):
            r = await ctx.owner.get("/admin/automation-rules", params={"account_id": a})
            if r.status_code != 200:
                bad_status.append(f"{a}: {r.status_code}")
                continue
            rows |= {int(x["id"]): x.get("next_due_at") for x in r.json()["rules"]}
        return rows, bad_status

    before, st_before = await listed()
    t0 = datetime.utcnow()
    r = await ctx.owner.post("/__slop/automation-tick", timeout=900)
    t1 = datetime.utcnow()
    after, st_after = await listed()
    ctx.rec.stage = None
    ids = [*good, bad_rid]
    con = w.sql()
    jobs: dict[int, list] = {i: [] for i in ids}
    for rid, created in con.execute(
            f"SELECT rule_id, created_at FROM scheduled_jobs WHERE rule_id IN ({','.join('?' * len(ids))}) "
            "AND payload_json NOT LIKE '%\"_followup\"%'", ids):
        jobs[int(rid)].append(_dt(created))
    con.close()
    bad: dict[str, object] = {}
    for rid, shape in good.items():
        made, nd0, nd1 = jobs[rid], _dt(before.get(rid)), _dt(after.get(rid))
        want = (made[0] + timedelta(seconds=BAD_TZ_EVERY_S) if shape == "interval" and len(made) == 1
                else slot_utc + timedelta(days=1))
        on_time = len(made) == 1 and t0 - timedelta(seconds=1) <= made[0] <= t1 + timedelta(seconds=1)
        shown = (nd0 is not None and nd0 <= t0 + timedelta(seconds=1)
                 and (shape == "interval" or nd0 == slot_utc)
                 and nd1 is not None and abs((nd1 - want).total_seconds()) < 1)
        if not (on_time and shown):
            bad[f"{shape} rule {rid}"] = {"jobs": [str(x) for x in made], "next_due_before": before.get(rid),
                                          "next_due_after": after.get(rid), "want_after": str(want)}
    skipped = not jobs[bad_rid] and bad_rid in before and before[bad_rid] is None and after.get(bad_rid) is None
    ctx.check(BAD_TZ, r.status_code == 200 and skipped and not bad and not st_before + st_after,
              tick=r.status_code, bad_rule=bad_rid, bad_rule_jobs=len(jobs[bad_rid]),
              bad_rule_next_due=[before.get(bad_rid), after.get(bad_rid)], good_rules=len(good),
              clock_slot=f"{slot} @ UTC+{BAD_TZ_OFFSET_MIN}m", wrong=bad, list_status=st_before + st_after,
              pass_ms=(r.json().get("ms") if r.status_code == 200 else r.text[:200]))


async def run(ctx) -> None:
    if followup.refuse_live(ctx, (GAP, STEPS, CAP, REPLIES, RESUME, HOLD, COUNTS, LIVE, AGAIN, BAD_TZ)):
        return
    cases = (await followup.setup(ctx, PROFILE))["cases"]
    w = ctx.world
    aids = [c["id"] for c in w.data["creators"]]

    con = w.sql()
    before = _snapshot(con, aids)
    t_seed = datetime.utcnow()
    cls = {k: cases.get(k) or _natural(v, t_seed) for k, v in before.items()}
    ctx.metric("classes", dict(Counter(cls.values())))

    # The owner's tab (its reads + stream) and `--users` more live streams on the same
    # session (each a dashboard tab's /events), opened over TAB_RAMP_S, not in one instant.
    owner_tab = manager.OwnerTab(ctx.owner.share(limits=8), w.rng("scenario:followup-drip:tab"))
    sse_http = ctx.owner.share(limits=max(1, ctx.users) + 4)
    streams = [manager.SseListener(sse_http, resume=True) for _ in range(max(1, ctx.users))]
    ramp = float(ctx.param("tab_ramp_s", TAB_RAMP_S))
    unopened: list[str] = []

    async def open_stream(i: int, lis) -> None:
        await asyncio.sleep(ramp * i / len(streams))
        try:
            await lis.start()
        except Exception as e:  # noqa: BLE001 — a stream that never connected is a finding (LIVE), not a crash
            unopened.append(f"{i}: {type(e).__name__}")

    ctx.rec.stage = "tabs-open"
    await owner_tab.start()
    await asyncio.gather(*(open_stream(i, x) for i, x in enumerate(streams)))
    ctx.rec.stage = None
    tabs = [owner_tab.lis, *streams]
    calls0 = (await ctx.owner.get("/__slop/fake/calls")).json()["calls"].get("deepseek:followup", 0)

    ctx.rec.stage = "tick1"
    t0 = datetime.utcnow()
    ticks = await asyncio.gather(*(followup.tick(ctx, a) for a in aids))
    ctx.rec.stage = None
    after = _snapshot(con, aids)
    calls1 = (await ctx.owner.get("/__slop/fake/calls")).json()["calls"].get("deepseek:followup", 0)
    nudge_ids = {mid for v in after.values() for mid in v.get("nudges", [])}
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and any(nudge_ids - set(t.message_ids) for t in tabs):
        await asyncio.sleep(0.25)

    ctx.rec.stage = "tick2"
    ticks2 = await asyncio.gather(*(followup.tick(ctx, a) for a in aids))
    ctx.rec.stage = None
    after2 = _snapshot(con, aids)
    runs: dict[str, tuple] = {}
    for a, st_, done, stats in con.execute(
            "SELECT account_id, started_at, completed_at, stats_json FROM automation_runs "
            "WHERE kind='send_followup' AND completed_at IS NOT NULL ORDER BY id"):
        runs.setdefault(str(a), (_dt(st_), _dt(done), json.loads(stats or "{}")))
    con.close()
    await owner_tab.close()
    await owner_tab.http.aclose()
    for x in streams:
        await x.stop()
    await sse_http.aclose()

    def st(k):
        return after[k].get("state") or {}

    def nudged(k) -> int:
        return len(after[k].get("nudges", []))

    def keys(k) -> set:
        return set(st(k).get("sent", {}))

    def near(dt, want, tol_min=15) -> bool:
        return dt is not None and abs((dt - want).total_seconds()) < tol_min * 60

    def by(*names_):
        return [k for k, c in cls.items() if c in names_]

    def same(k) -> bool:
        return (after[k].get("state") or {}) == (before[k].get("state") or {}) and not nudged(k)

    ok, d = _verdict(lambda a, f: same((a, f)), by("gap"), after)
    ctx.check(GAP, ok and d["fans"] > 0, **d)
    ok, d = _verdict(lambda a, f: nudged((a, f)) == 1 and st((a, f)).get("phase") == "tracking"
                     and keys((a, f)) == ({"1", "2"} if cls[a, f] == "due2" else {"1"}),
                     by("due1", "due2", "n_due"), after)
    ctx.check(STEPS, ok and d["fans"] > 0, **d)
    ok, d = _verdict(lambda a, f: not nudged((a, f)) and st((a, f)).get("phase") == "completed", by("cap", "n_cap"), after)
    ctx.check(CAP, ok and d["fans"] > 0, **d)
    ok, d = _verdict(lambda a, f: not nudged((a, f)) and (
        st((a, f)).get("phase") == "restart_cooldown" and near(st((a, f)).get("until"), t0 + timedelta(hours=72))
        if cls[a, f] == "restart" else
        st((a, f)).get("phase") == "reply_cooldown" and near(st((a, f)).get("until"), t0 + timedelta(hours=26))),
        by("reply", "n_reply", "restart"), after)
    ctx.check(REPLIES, ok and d["fans"] > 0, **d)
    ok, d = _verdict(lambda a, f: nudged((a, f)) == 1 and st((a, f)).get("phase") == "tracking"
                     and keys((a, f)) == {"1"} and st((a, f)).get("cycle") == (2 if cls[a, f] == "restart_expired" else 1),
                     by("reply_expired", "restart_expired"), after)
    ctx.check(RESUME, ok and d["fans"] > 0, **d)
    ok, d = _verdict(lambda a, f: same((a, f)) if cls[a, f] in ("cooling", "waiting") else
                     (not nudged((a, f)) and st((a, f)).get("phase") == "tracking"), by("cooling", "waiting", "n_none", "n_wait"), after)
    ctx.check(HOLD, ok and d["fans"] > 0, **d)

    res = [t["res"] for t in ticks]
    sent_sum = sum(int(x.get("followups_sent") or 0) for x in res)
    rows = sum(nudged(k) for k in after)
    recorded = sum(1 for k in after for v in st(k).get("sent", {}).values() if _dt(v) and _dt(v) >= t0)
    multi = [f"{a}/{f}" for (a, f) in after if nudged((a, f)) > 1]
    errs = {t["aid"]: {k: t["res"].get(k) for k in ("errors", "first_error", "cap_hit", "key_error", "no_llm_key")
                       if t["res"].get(k)} for t in ticks if t["status"] != 200 or any(
        t["res"].get(k) for k in ("errors", "cap_hit", "key_error", "no_llm_key", "error"))}
    ctx.check(COUNTS, rows > 0 and rows == sent_sum == recorded == calls1 - calls0 and not multi and not errs,
              nudge_rows=rows, followups_sent=sent_sum, recorded_steps=recorded, llm_calls=calls1 - calls0,
              multi=multi[:5], errors=errs)
    missing = {i: len(nudge_ids - set(t.message_ids)) for i, t in enumerate(tabs) if nudge_ids - set(t.message_ids)}
    ctx.check(LIVE, bool(nudge_ids) and not missing, nudges=len(nudge_ids), tabs=len(tabs),
              tabs_missing=len(missing), e_g=dict(list(missing.items())[:5]), unopened=unopened[:5],
              ended=[t.ended for t in tabs if t.ended][:3])
    sent2 = sum(int(t["res"].get("followups_sent") or 0) for t in ticks2)
    rows2 = sum(len(v.get("nudges", [])) for v in after2.values())
    def _held_outside(t) -> int:  # due steps the guard or the send rest held, not the drip
        return int(t["res"].get("skipped_guard") or 0) + int(t["res"].get("skipped_cooldown") or 0)
    held1 = {t["aid"]: _held_outside(t) for t in ticks}
    extra = {t["aid"]: _held_outside(t) - held1.get(t["aid"], 0) for t in ticks2
             if _held_outside(t) != held1.get(t["aid"], 0)}
    ctx.check(AGAIN, sent2 == 0 and rows2 == rows and not extra and all(t["status"] == 200 for t in ticks2),
              followups_sent=sent2, new_rows=rows2 - rows, held_by_guard_or_rest_vs_tick1=extra)

    # The product's own run time (automation_runs), not the wait for a run slot.
    per_nudge = sorted((done - st_).total_seconds() * 1000 / max(1, int(stats.get("followups_sent") or 0))
                       for st_, done, stats in runs.values())
    p95 = per_nudge[min(len(per_nudge) - 1, int(round(0.95 * (len(per_nudge) - 1))))]
    ctx.check(f"run time per nudge p95 <= {TICK_PER_NUDGE_P95_MS} ms", p95 <= TICK_PER_NUDGE_P95_MS,
              budget=True, p95_ms=round(p95, 1), per_creator=[round(x, 1) for x in per_nudge])
    ctx.metric("p95_vs_last_green", {"tick per nudge": round(p95, 1)})
    ctx.metric("ticks", [{"aid": t["aid"], "status": t["status"], "ms": round(t["ms"], 1),
                          **{k: t["res"].get(k) for k in ("eligible", "transitioned", "followups_sent",
                                                          "state_advanced", "skipped_unread", "skipped_guard",
                                                          "skipped_cooldown", "skipped_locked", "errors")}}
                         for t in ticks])
    ctx.metric("ticks2", [{"aid": t["aid"], **{k: t["res"].get(k) for k in (
        "followups_sent", "skipped_guard", "skipped_cooldown", "skipped_locked")}} for t in ticks2])
    ctx.metric("nudges_by_class", dict(Counter(cls[k] for k in after for _ in after[k].get("nudges", []))))
    ctx.note(f"tick 1: {rows} nudges over {len(aids)} Creators ({sent_sum} reported), "
             f"{len(tabs)} owner tabs; tick 2: {sent2}; per-nudge p95 {p95:.0f} ms")
    await _bad_tz_phase(ctx, w, aids)
