"""The welcome chatter (`automations.welcome_chatter_for_info`, the reply loop) after its
per-fan gates became one pure `decide()` (service/automations/wcfi_decide.py): fans DM
their Creators and each DM is answered in real time, by the product's own path.

World: `agency_inbox` (one Agency, its Creators, their fans, threads for a share of them),
plus seed/welcome_chatter.py: per Creator the persona, Reply Instant on (W7, no delay) and
an enabled welcome_chatter_for_info rule whose daily sweep last fired 30 min ago; then
`--users` fans without a seeded thread, spread over the Creators, one case each: open
(we spoke last), double (his line still unanswered), blacklisted, skip-listed, muted
creator we follow, promo blaster.

Load: `rounds` rounds (default 2, `--set rounds=`): every case fan sends one DM, each a WS
frame through `POST /__slop/of-ws-frame` in the pump's shape (`fan_dm.serial`: one frame
in flight per Creator, open loop at `rate` DMs/s per Creator, default RATE, `--set rate=`:
fans trickle in as in production, so each DM's W7 wake finds the Creator's previous run
done; a burst waits ~30 s per DM, see RATE); the real path does the rest: the transcoder's
`webhook_dispatch.on_inbound_message` queues a fan-scoped job and wakes the real automation
supervisor (RELAY_ENV SLOP_SUPERVISOR=1), whose `run_once` runs the lane under its run
slots, decides per fan, calls the LLM and sends each bubble to OF. A round ends when every
open fan's answer reached OF and no job of the lane is pending or running (a DM inside the
fan's 10 s reply cooldown is deferred to its end: the product's rule).

Invariants (lib/wcfi_faults.py names them): TURNS (one turn per DM of an open fan, nothing
dropped), SKIPLISTED (zero sends to a blacklisted / skip-listed / muted / promo fan),
DOUBLE (no bubble reached OF twice), COUNTS (OF's sends = the new outbound rows, none to a
fan who did not DM, no run errors), LANDED (every DM is its row). Budget: e2e p95, a DM's
frame handed to the relay -> his turn's first bubble at OF, vs E2E_P95_MS and the last green run.

Faked or bypassed, declared: DeepSeek at its HTTP boundary (lib/wcfi_relay.py through
lib/automation_relay.py's loopback fake: `{}` for the fact extract, two unique lines for a reply,
0.4 s each); OF's send (lib/relay.py `_OfflineOF.send_message`, journalled by
lib/wcfi_relay.py); the agency's (fake) DeepSeek key through the real `PUT /admin/my-llm-keys`;
the account DM rate raised to DM_PER_MIN through the real Concurrency panel route. Typing holds
are 0 under CHATTERLY_TEST_MODE (no pacing bypass of our own). SLOP_LIVE=1 is refused (it would
spend on the real DeepSeek): every check SKIPs.

Break-it-once: wcfi-skiplist-ignored (decide's `listed` skip re-decided as unlisted): only
SKIPLISTED goes red, through the BLACKLISTED fans alone (W7 wakes the lane for them; it skips
them as `listed`, the fault answers them). The skip-listed fans never reach run() (W7 wakes no
lane for them), so the fault does not touch them; nor the muted / promo fans (their own gates).
`--fault=wcfi-turn-sent-twice` (each text bubble sent and persisted twice): only DOUBLE.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import os
import time
from collections import Counter, defaultdict

from slop.actors import fan_dm
from slop.lib.wcfi_faults import COUNTS, DOUBLE, LANDED, SKIPLISTED, TURNS
from slop.seed import welcome_chatter as wc

PROFILE = "agency_inbox"
UI = False
FAULT = "wcfi-skiplist-ignored"
RELAY_ENV = {"SLOP_SUPERVISOR": "1"}
# frame -> first bubble at OF. Per Creator the lane runs one fan-scoped job at a time
# (one run per (account, kind)), ~1 s each (two 0.4 s fake LLM calls + reads + the send).
# RATE: a job queued while its Creator's run is in flight is not re-drained when that run
# ends (W7's wake was spent on the in-flight pair): it waits for the next wake or the 30 s
# tick, so a burst of N DMs to one Creator takes ~N x 30 s (measured: 20261030T212146Z-...-feb9). At one DM
# per 4 s per Creator the previous run is done by the next wake: p95 0.96 s small, 1.99 s
# medium/200 (measured: 20261030T213248Z-...-901c, 20261030T213354Z-...-06c0); a DM that
# misses its wake waits up to the 30 s tick.
# Budgets: E2E_P95_MS ~2.5x the medium p95 (headroom for a slower host, still far under the
# 30 s tick a missed wake costs, so p95 > 5 s means wakes are being missed); P95_VS_LAST's
# +1 s abs slack ~ one LLM round trip's jitter at medium (+50 %).
E2E_P95_MS = 5_000
RATE = 0.25
P95_VS_LAST = (1.5, 1000)
DM_PER_MIN = 600
ROUNDS = 2
SETTLE_S = 300
OF_SEND_ID_BASE = 9_700_000_000_000   # lib/relay.py: the fake OF's message ids (this run's sends)
KIND = wc.KIND
# wcfi's best-effort OF calls after a send (nickname push, mark read): the offline OF answers
# only me() and send_message, so each logs its warning + traceback; the turn is unaffected.
EXPECTED_TRACEBACKS = (("push_nick_failed", "slop: OF is offline"),
                       ("mark_chat_read failed", "slop: OF is offline"))


def _pending_jobs(con) -> int:
    return con.execute("SELECT COUNT(*) FROM scheduled_jobs WHERE kind=? AND status IN ('pending','running')",
                       (KIND,)).fetchone()[0]


def pct(xs, q=0.95):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))], 1) if xs else None


async def run(ctx) -> None:
    names = (TURNS, SKIPLISTED, DOUBLE, COUNTS, LANDED)
    if os.environ.get("SLOP_LIVE") == "1":
        for n in names:
            ctx.skip(n, "SLOP_LIVE=1 would call the paid DeepSeek API; this scenario runs on the fake only")
        return
    w = await ctx.build(PROFILE)
    seeded = wc.seed(w, w.data["fans"], w.data["threads"], live=max(1, ctx.users))
    cases = seeded["cases"]
    ctx.metric("classes", dict(Counter(cases.values())))
    r = await ctx.owner.put("/admin/my-llm-keys", json={"deepseek": "slop-fake-deepseek"})
    ctx.metric("agency_deepseek_key", {"status": r.status_code})
    r = await ctx.owner.post("/lanes-panel/config", json={"values": {"OF_DM_PER_MIN": DM_PER_MIN}})
    ctx.metric("dm_per_min", {"set": DM_PER_MIN, "status": r.status_code})

    fan_by = {(f["account_id"], f["id"]): f for fl in w.data["fans"].values() for f in fl}
    targets = [fan_by[k] for k in sorted(cases)]
    open_fans = {k for k, c in cases.items() if c in wc.ELIGIBLE}
    rounds = int(ctx.param("rounds", ROUNDS))
    rate = float(ctx.param("rate", RATE))
    ids = itertools.count(fan_dm.INJECT_ID_BASE)   # one id space over the rounds (no upsert of round 1)
    con = w.sql()
    flat = [x for k in sorted(cases) for x in k]
    pairs = " OR ".join(["(account_id=? AND fan_id=?)"] * len(cases))
    tc0 = {(a, int(f)): int(t or 0) for a, f, t in con.execute(
        f"SELECT account_id, fan_id, turn_counter FROM fans WHERE {pairs}", flat)}
    run0 = con.execute("SELECT COALESCE(MAX(id), 0) FROM automation_runs").fetchone()[0]
    stats0 = (await ctx.owner.get("/__slop/stats")).json()
    sends0 = len((await ctx.owner.get("/__slop/wcfi/of-sends")).json())

    dms: list[dict] = []
    settle: list[dict] = []
    for rnd in range(1, rounds + 1):
        ctx.rec.stage = f"round{rnd}"
        t_round = time.time()
        recs = await fan_dm.serial(ctx.owner, targets, 1, rate=rate, ids=ids, text=f"slop wcfi round {rnd}")
        for x in recs:
            x["round"] = rnd
        dms += recs
        t0 = {(x["account_id"], x["fan_id"]): x["t0"] / 1000 for x in recs}
        deadline = time.monotonic() + SETTLE_S
        waiting, jobs = set(open_fans), -1
        while time.monotonic() < deadline:
            sends = (await ctx.owner.get("/__slop/wcfi/of-sends")).json()[sends0:]
            answered = {(s["account_id"], s["fan_id"]) for s in sends
                        if (s["account_id"], s["fan_id"]) in t0 and s["t"] >= t0[(s["account_id"], s["fan_id"])]}
            waiting = open_fans - answered
            jobs = _pending_jobs(con)
            st = (await ctx.owner.get("/__slop/stats")).json()
            if not waiting and jobs == 0 and st["processed"] >= st["received"]:
                break
            await asyncio.sleep(0.5)
        await asyncio.sleep(1.0)   # a send already past its decision lands now, not after the checks
        ctx.rec.stage = None
        settle.append({"round": rnd, "s": round(time.time() - t_round, 1), "unanswered": len(waiting),
                       "jobs_left": jobs})
    ctx.metric("rounds", settle)

    sends = (await ctx.owner.get("/__slop/wcfi/of-sends")).json()[sends0:]
    stats1 = (await ctx.owner.get("/__slop/stats")).json()
    calls = (await ctx.owner.get("/__slop/fake/calls")).json()["calls"]
    rows: dict[tuple, list] = defaultdict(list)
    for a, f, mid, body, kind in con.execute(
            "SELECT account_id, fan_id, message_id, body, automation_kind FROM messages "
            "WHERE direction='out' AND message_id >= ?", (OF_SEND_ID_BASE,)):
        rows[(a, int(f))].append({"id": int(mid), "body": body, "kind": kind})
    tc1 = {(a, int(f)): int(t or 0) for a, f, t in con.execute(
        f"SELECT account_id, fan_id, turn_counter FROM fans WHERE {pairs}", flat)}
    landed = {(a, int(f), int(m)) for a, f, m in con.execute(
        "SELECT account_id, fan_id, message_id FROM messages WHERE direction='in' AND message_id >= ?",
        (fan_dm.INJECT_ID_BASE,))}
    runs = [json.loads(s or "{}") | {"_status": st} for s, st in con.execute(
        "SELECT stats_json, status FROM automation_runs WHERE kind=? AND id > ?", (KIND, run0))]
    con.close()

    by_fan: dict[tuple, list] = defaultdict(list)
    for s in sends:
        by_fan[(s["account_id"], s["fan_id"])].append(s)
    dm_by: dict[tuple, list] = defaultdict(list)
    for x in sorted(dms, key=lambda x: x["t0"]):
        dm_by[(x["account_id"], x["fan_id"])].append(x["t0"] / 1000)

    # LANDED: every DM accepted and in its thread.
    bad_dm = [x for x in dms if x.get("status", 599) >= 300
              or (x["account_id"], int(x["fan_id"]), int(x["message_id"])) not in landed]
    ctx.check(LANDED, bool(dms) and not bad_dm, dms=len(dms), missing=len(bad_dm),
              e_g=[f"{x['account_id']}/{x['fan_id']}/{x['message_id']}" for x in bad_dm[:3]])

    # TURNS: >= 1 bubble in every DM's window, turn_counter + rounds, runs' replies_sent = turns.
    e2e: list[float] = []
    wrong: dict[str, str] = {}
    for k in sorted(open_fans):
        ts_ = dm_by[k]
        got = sorted(s["t"] for s in by_fan.get(k, []))
        for i, t in enumerate(ts_):
            end = ts_[i + 1] if i + 1 < len(ts_) else float("inf")
            win = [x for x in got if t <= x < end]
            if not win:
                wrong[f"{k[0]}/{k[1]}"] = f"DM {i + 1}: no bubble before the next DM"
                break
            e2e.append((win[0] - t) * 1000)
        if tc1.get(k, 0) - tc0.get(k, 0) != len(ts_):
            wrong.setdefault(f"{k[0]}/{k[1]}", f"turn_counter {tc0.get(k)} -> {tc1.get(k)}, {len(ts_)} DMs")
    turns = sum(tc1.get(k, 0) - tc0.get(k, 0) for k in cases)
    replies = sum(int(x.get("replies_sent") or 0) for x in runs)
    ctx.check(TURNS, bool(open_fans) and not wrong and turns == replies,
              open_fans=len(open_fans), dms_each=rounds, wrong=len(wrong), e_g=dict(list(wrong.items())[:3]),
              turns_taken=turns, runs_replies_sent=replies)

    # SKIPLISTED: nothing to a fan the lane must never answer.
    skipped = {k: c for k, c in cases.items() if c in wc.SKIPPED}
    hit = {f"{k[0]}/{k[1]}": {"case": c, "of_sends": len(by_fan.get(k, [])), "rows": len(rows.get(k, []))}
           for k, c in skipped.items() if by_fan.get(k) or rows.get(k)}
    present = Counter(skipped.values())
    ctx.check(SKIPLISTED, all(present[c] for c in wc.SKIPPED) and not hit,
              fans=dict(present), sent_to=len(hit), e_g=dict(list(hit.items())[:3]))

    # DOUBLE: no (Creator, fan, text) twice at OF, no repeated body in a fan's rows.
    of_dup = [f"{a}/{f}: {t[:40]}" for (a, f, t), n in Counter(
        (s["account_id"], s["fan_id"], s["text"]) for s in sends).items() if n > 1]
    row_dup = [f"{k[0]}/{k[1]}" for k, rs in rows.items() if len({r["body"] for r in rs}) != len(rs)]
    ctx.check(DOUBLE, bool(sends) and not of_dup and not row_dup, of_sends=len(sends),
              twice_at_of=len(of_dup), fans_with_repeated_rows=len(row_dup), e_g=of_dup[:3] or row_dup[:3])

    # COUNTS: OF's sends = new rows (same ids, the lane's), none to a fan who did not DM, no errors.
    row_ids = {r["id"] for rs in rows.values() for r in rs}
    send_ids = {s["id"] for s in sends}
    foreign = [r for rs in rows.values() for r in rs if r["kind"] != KIND]
    stray = sorted(f"{a}/{f}" for (a, f) in by_fan if (a, f) not in cases)
    of_sends_n = stats1["of_sends"] - stats0["of_sends"]
    errs = [{k: x.get(k) for k in ("errors", "cap_hit", "key_error", "no_llm_key", "llm_capped", "_status")}
            for x in runs if x.get("errors") or x.get("cap_hit") or x.get("key_error") or x.get("no_llm_key")
            or x.get("llm_capped") or x["_status"] != "ok"]   # run_decide.outcome: a clean run is 'ok'
    ctx.check(COUNTS, bool(sends) and send_ids == row_ids and of_sends_n == len(sends) and not foreign
              and not stray and not errs,
              of_sends=len(sends), of_sends_stat=of_sends_n, new_rows=len(row_ids),
              only_at_of=len(send_ids - row_ids), only_in_db=len(row_ids - send_ids),
              other_kind_rows=len(foreign), stray_fans=stray[:5], runs=len(runs), run_errors=errs[:3])

    p95 = pct(e2e)
    ctx.check(f"e2e DM frame -> first bubble at OF p95 <= {E2E_P95_MS} ms",
              p95 is not None and p95 <= E2E_P95_MS, budget=True, p95_ms=p95, p50_ms=pct(e2e, 0.5),
              max_ms=pct(e2e, 1.0), samples=len(e2e))
    if p95 is not None:
        ctx.metric("p95_vs_last_green", {"e2e dm -> first bubble": p95})
    skips = Counter()
    for x in runs:
        for key in ("skipped_listed", "skipped_not_turn", "skipped_spam", "skipped_muted_creator",
                    "skipped_cooldown", "skipped_locked", "newly_skiplisted"):
            skips[key] += int(x.get(key) or 0)
    ctx.metric("runs", {"n": len(runs), "replies_sent": replies, **skips,
                        "status": dict(Counter(x["_status"] for x in runs))})
    ctx.metric("llm_calls", {k: v for k, v in calls.items() if k.startswith("deepseek:wcfi")})
    ctx.note(f"{len(dms)} DMs over {rounds} rounds from {len(cases)} fans ({len(open_fans)} open); "
             f"{len(sends)} bubbles at OF, {turns} turns, {len(runs)} runs; e2e p95 {p95} ms")
