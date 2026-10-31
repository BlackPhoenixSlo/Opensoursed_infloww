"""The welcome burst (`automations.send_welcome`) after its filters became one pure
`partition` (service/automations/send_welcome_decide.py): a subscribe wave hits every
Creator at once, OnlyFans' toasts poke each Creator's welcome rule, one supervisor pass
runs them all, and every subscriber is checked against what his history says he gets,
while `--users` owner tabs watch the live stream.

World: `agency_inbox` plus seed/welcome_burst.py, per Creator: `new` brand-new subs, `welcomed`
renewals the welcome already greeted (claim + 2 outbound rows), `established` renewals with a
real conversation (4 out / 10 in, no claim), all in OF's subscribe feed at once; a share of the
Creators (`of_on_frac`) has OnlyFans' own welcome on. Sizes per scale (`--set new=`,
`welcomed=`, `established=`, `of_on_frac=`).

Flow, all through real routes: the owner raises the DM rate (Concurrency panel route) and adds
one `send_welcome` rule per Creator (`POST /admin/automation-rules`, every 300 s, `after_of_welcome`,
`stop_on_reply` on so the claim lands with bubble 0, `limit` / `max_welcomes` = the feed, so no
batch cap). Tick 0 (an empty feed) fires each new rule once, so a CONTROL pass after it has
nothing due. Then the feed is published, the `--users` /events streams open over TAB_RAMP_S, every
Creator's subscribe toasts arrive (`POST /__slop/of-ws-frame`, serial per Creator, the real
transcoder pokes the rule), tick 1 runs; one more toast per Creator and tick 2.

Invariants (lib/welcome_burst_faults.py names them): ONCE (one greeting + one follow-back per new
sub of an OF-off Creator, nothing for a claimed fan, nothing in tick 2), ESTABLISHED (no send, follow
or claim for a renewal with history; the runs' skipped_existing = the seed), OF_ON (OF-on Creators send
nothing, claim + follow each new sub once), COUNTS (OF sends = new welcome rows, distinct fans sent =
the runs' welcomes_sent, follows = followed_back, no errors), POKE (control pass runs nothing; each
toast pass runs every Creator's rule; a toast inside the 60 s poke floor after a run is spent), LIVE (every welcome bubble on every tab). Budget: a Creator's
tick-1 run time per welcome (automation_runs started -> completed), p95, vs PER_WELCOME_P95_MS and the
last green run.

Faked or bypassed, declared: OnlyFans' subscribe feed, settings, templates, profile read and follow
(lib/welcome_relay.py, at the offline client); OF's send (lib/relay.py `_OfflineOF.send_message`); the
supervisor's 30 s cadence (`POST /__slop/automation-tick`, one `_drain_due_jobs_once` pass);
`human_pace: false` (paced holds are minutes of real sleep; the relay's test mode already zeroes typing
holds) and `with_image: false` (no vault read); the DM rate raised to DM_PER_MIN; the wait between waves (the 60 s poke floor) replaced by moving
each rule's own scheduled_jobs rows AGE_S back (SQL, `_age_jobs`), a row the product writes, only older.

Break-it-once: welcome-burst-rewelcomes (partition ignores welcome_sent): only ONCE goes red.
`--fault=welcome-to-established` (partition ignores the NOT-NEW scan): only ESTABLISHED.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from slop.actors import manager
from slop.lib.welcome_burst_faults import COUNTS, ESTABLISHED, LIVE, OF_ON, ONCE, POKE
from slop.seed import ts, welcome_burst

PROFILE = "agency_inbox"
UI = False
FAULT = "welcome-burst-rewelcomes"
PER_WELCOME_P95_MS = 400      # measured p95 65.8 ms at medium (slop/evidence/20261030T215222Z-2026-10-30-welcome-burst-7482): 2 bubbles, claim, follow
P95_VS_LAST = (1.5, 300)
OF_SEND_ID_BASE = 9_700_000_000_000   # lib/relay.py: the fake OF's message ids (this run's sends)
DM_PER_MIN = 600
EVERY_S = 300
AGE_S = 120   # the rules' last job moved this far back: past the 60 s poke floor, inside EVERY_S
TAB_RAMP_S = 10.0
SIZES = {"small": (8, 4, 4), "medium": (20, 8, 8), "huge": (40, 12, 12)}   # new, welcomed, established
BURST = (False, True)   # the composed burst, per bubble "is the question": the seeded brain has no
                        # activity line and the rule no GIF, so one greeting, then the question


def _dt(v) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


def _publish(ctx, feed: dict, of_on: list) -> None:
    """of-welcome.json for lib/welcome_relay.py, atomically (the relay reads it on every call)."""
    f = ctx.stack.tmp / "of-welcome.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({"feed": feed, "of_welcome_on": of_on}))
    os.replace(tmp, f)


def _toast(item: dict) -> dict:
    return {"toasts": {"type": "subscribed", "data": {"relatedUser": dict(item["user"])}}}


async def _tick(ctx) -> dict:
    t = time.perf_counter()
    r = await ctx.owner.post("/__slop/automation-tick", timeout=900)
    body = r.json() if r.status_code == 200 else {"error": r.text[:300]}
    return {"status": r.status_code, "ms": (time.perf_counter() - t) * 1000,
            "welcome": sorted(a for a, k in body.get("tasks", []) if k == "send_welcome"), **body}


def _runs(con, after_id: int, upto: int) -> dict[str, list]:
    out: dict[str, list] = defaultdict(list)
    for rid, a, st, done, stats in con.execute(
            "SELECT id, account_id, started_at, completed_at, stats_json FROM automation_runs "
            "WHERE kind='send_welcome' AND id > ? AND id <= ? ORDER BY id", (after_id, upto)):
        out[str(a)].append({"id": rid, "start": _dt(st), "done": _dt(done), **json.loads(stats or "{}")})
    return out


def _age_jobs(con, rule_ids) -> None:
    """The time between two subscribe waves, without the wait: each rule's own jobs (the
    cadence anchor, job_queue.rule_last_fired_at) are moved AGE_S back."""
    q = ",".join("?" * len(rule_ids))
    with con:
        con.execute(f"UPDATE scheduled_jobs SET created_at = ? WHERE rule_id IN ({q})",
                    (ts(datetime.utcnow() - timedelta(seconds=AGE_S)), *rule_ids))


def _max_run(con) -> int:
    return con.execute("SELECT COALESCE(MAX(id), 0) FROM automation_runs").fetchone()[0]


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    new_n, wel_n, est_n = SIZES.get(ctx.scale, SIZES["small"])
    seed = welcome_burst.seed(w, w.data["fans"], w.data["threads"], new=ctx.param("new", new_n),
                              welcomed=ctx.param("welcomed", wel_n), established=ctx.param("established", est_n),
                              of_on_frac=ctx.param("of_on_frac", 0.3))
    aids = [c["id"] for c in w.data["creators"]]
    of_on = set(seed["of_welcome_on"])
    feed = seed["feed"]
    ctx.metric("world", {"creators": len(aids), "of_welcome_on": len(of_on),
                         **{k: sum(len(v) for v in seed[k].values()) for k in ("new", "welcomed", "established")}})

    r = await ctx.owner.post("/lanes-panel/config", json={"values": {"OF_DM_PER_MIN": DM_PER_MIN}})
    ctx.metric("dm_per_min", {"set": DM_PER_MIN, "status": r.status_code})
    _publish(ctx, {a: [] for a in aids}, sorted(of_on))
    rules = {}
    for a in aids:
        n = len(feed[a])
        r = await ctx.owner.post("/admin/automation-rules", json={
            "account_id": a, "kind": "send_welcome", "every_seconds": EVERY_S, "payload": {
                "with_image": False, "question": welcome_burst.QUESTION, "human_pace": False,
                "stop_on_reply": True, "after_of_welcome": True, "limit": n, "max_welcomes": n}})
        r.raise_for_status()
        rules[a] = int(r.json()["id"])

    con = w.sql()
    ws0 = {(str(a), int(f)): s for a, f, s in con.execute("SELECT account_id, fan_id, sent_at FROM welcome_sent")}

    ctx.rec.stage = "tick0"
    tick0 = await _tick(ctx)            # the new rules fire once on an empty feed
    ctx.rec.stage = "control"
    _age_jobs(con, list(rules.values()))
    control = await _tick(ctx)          # AGE_S < EVERY_S: nothing due, nothing poked
    ctx.rec.stage = None

    _publish(ctx, feed, sorted(of_on))
    sse_http = ctx.owner.share(limits=max(1, ctx.users) + 4)
    tabs = [manager.SseListener(sse_http, resume=True) for _ in range(max(1, ctx.users))]
    ramp = float(ctx.param("tab_ramp_s", TAB_RAMP_S))
    unopened: list[str] = []

    async def open_tab(i: int, lis) -> None:
        await asyncio.sleep(ramp * i / len(tabs))
        try:
            await lis.start()
        except Exception as e:  # noqa: BLE001 — a tab that never connected is a LIVE finding
            unopened.append(f"{i}: {type(e).__name__}")

    ctx.rec.stage = "tabs-open"
    await asyncio.gather(*(open_tab(i, x) for i, x in enumerate(tabs)))

    async def toasts(a: str, items: list) -> list[int]:
        bad = []
        for it in items:   # serial per Creator, like its WS pump
            r = await ctx.owner.post("/__slop/of-ws-frame", json={"account_id": a, "frame": _toast(it)})
            if r.status_code != 200:
                bad.append(r.status_code)
        return bad

    ctx.rec.stage = "toasts1"
    bad1 = await asyncio.gather(*(toasts(a, list(reversed(feed[a]))) for a in aids))
    q1 = await manager.quiesce(ctx.owner)
    run0 = _max_run(con)
    ctx.rec.stage = "tick1"
    tick1 = await _tick(ctx)
    ctx.rec.stage = None
    seen1 = (await ctx.owner.get("/__slop/welcome")).json()
    run1 = _max_run(con)
    ws1 = {(str(a), int(f)): s for a, f, s in con.execute("SELECT account_id, fan_id, sent_at FROM welcome_sent")}
    rows1 = [(str(a), int(f), int(m)) for a, f, m in con.execute(
        "SELECT account_id, fan_id, message_id FROM messages WHERE direction='out' AND automation_kind='welcome' "
        "AND message_id >= ?", (OF_SEND_ID_BASE,))]
    ids1 = {m for _, _, m in rows1}
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and any(ids1 - set(t.message_ids) for t in tabs):
        await asyncio.sleep(0.25)

    ctx.rec.stage = "toasts-floor"      # a toast right after tick 1: under the poke floor, spent
    bad2 = await asyncio.gather(*(toasts(a, feed[a][:1]) for a in aids))
    await manager.quiesce(ctx.owner)
    floor = await _tick(ctx)
    _age_jobs(con, list(rules.values()))
    ctx.rec.stage = "toasts2"
    bad2 += await asyncio.gather(*(toasts(a, feed[a][:1]) for a in aids))
    q2 = await manager.quiesce(ctx.owner)
    ctx.rec.stage = "tick2"
    tick2 = await _tick(ctx)
    ctx.rec.stage = None
    seen2 = (await ctx.owner.get("/__slop/welcome")).json()
    rows2 = con.execute("SELECT COUNT(*) FROM messages WHERE direction='out' AND automation_kind='welcome' "
                        "AND message_id >= ?", (OF_SEND_ID_BASE,)).fetchone()[0]
    ws2 = {(str(a), int(f)) for a, f in con.execute("SELECT account_id, fan_id FROM welcome_sent")}
    runs1, runs2 = _runs(con, run0, run1), _runs(con, run1, _max_run(con))
    con.close()
    for t in tabs:
        await t.stop()
    await sse_http.aclose()

    sends1 = {a: v for a, v in seen1["sends"].items() if a in feed}
    follows1 = {a: Counter(v) for a, v in seen1["follows"].items() if a in feed}
    sends2 = sum(len(v) for a, v in seen2["sends"].items() if a in feed) - sum(len(v) for v in sends1.values())
    follows2 = sum(len(v) for a, v in seen2["follows"].items() if a in feed) - \
        sum(sum(c.values()) for c in follows1.values())

    def to(a: str, f: int) -> list[dict]:
        return [s for s in sends1.get(a, ()) if int(s["fan"]) == f]

    def fol(a: str, f: int) -> int:
        return follows1.get(a, Counter()).get(f, 0)

    def claimed_now(a: str, f: int) -> bool:
        return (a, f) in ws1 and (a, f) not in ws0

    # ONCE: OF-off Creators' new subs get exactly one burst (BURST: one greeting, then the
    # question) + one follow; a claimed renewal gets nothing anywhere; tick 2 sends and follows nobody.
    once_bad: dict[str, object] = {}
    for a in aids:
        for f in seed["new"][a]:
            if a in of_on:
                continue
            got = to(a, f)
            shape = tuple(s["text"] == welcome_burst.QUESTION for s in got)
            if not (shape == BURST and fol(a, f) == 1 and claimed_now(a, f)):
                once_bad[f"{a}/{f}"] = {"sends": len(got), "questions": sum(shape), "follows": fol(a, f),
                                       "claimed": claimed_now(a, f)}
        for f in seed["welcomed"][a]:
            if to(a, f) or fol(a, f) or ws1.get((a, f)) != ws0.get((a, f)):
                once_bad[f"{a}/{f} (welcomed)"] = {"sends": len(to(a, f)), "follows": fol(a, f)}
    n_new_off = sum(len(seed["new"][a]) for a in aids if a not in of_on)
    ctx.check(ONCE, n_new_off > 0 and not once_bad and sends2 == 0 and follows2 == 0 and rows2 == len(rows1),
              new_subs=n_new_off, welcomed=sum(len(v) for v in seed["welcomed"].values()), wrong=len(once_bad),
              e_g=dict(list(once_bad.items())[:4]), tick2_sends=sends2, tick2_follows=follows2,
              tick2_new_rows=rows2 - len(rows1))

    est_bad = {f"{a}/{f}": {"sends": len(to(a, f)), "follows": fol(a, f), "claimed": (a, f) in ws2}
               for a in aids for f in seed["established"][a] if to(a, f) or fol(a, f) or (a, f) in ws2}
    est_counts = {a: [x.get("skipped_existing") for x in runs1.get(a, [])] for a in aids}
    est_wrong = {a: v for a, v in est_counts.items() if v != [len(seed["established"][a])]}
    ctx.check(ESTABLISHED, sum(len(v) for v in seed["established"].values()) > 0 and not est_bad and not est_wrong,
              established=sum(len(v) for v in seed["established"].values()), wrong=len(est_bad),
              e_g=dict(list(est_bad.items())[:4]), skipped_existing_vs_seed=est_wrong)

    on_bad: dict[str, object] = {}
    for a in sorted(of_on):
        if sends1.get(a):
            on_bad[a] = {"sends": len(sends1[a])}
        miss = [f for f in seed["new"][a] if not (claimed_now(a, f) and fol(a, f) == 1)]
        if miss:
            on_bad[f"{a} new"] = {"not claimed+followed once": miss[:5], "n": len(miss)}
        st = runs1.get(a, [{}])[0]
        if st.get("of_welcome_on") is not True or st.get("welcomes_sent"):
            on_bad[f"{a} run"] = {k: st.get(k) for k in ("of_welcome_on", "welcomes_sent", "after_of_welcome_fans")}
    ctx.check(OF_ON, bool(of_on) and not on_bad, creators=len(of_on), wrong=on_bad)

    flat = [x for v in runs1.values() for x in v] + [x for v in runs2.values() for x in v]
    welcomes = sum(int(x.get("welcomes_sent") or 0) for x in flat)
    fb = sum(int(x.get("followed_back") or 0) for x in flat)
    # Both ticks: OF's sends / follows (lib/welcome_relay.py) vs the rows and the two ticks' runs.
    all_sends = {a: v for a, v in seen2["sends"].items() if a in feed}
    n_sends = sum(len(v) for v in all_sends.values())
    n1 = {a: len(v) for a, v in sends1.items()}
    fans_sent = len({(a, int(s["fan"])) for a, v in sends1.items() for s in v}) + \
        len({(a, int(s["fan"])) for a, v in all_sends.items() for s in v[n1.get(a, 0):]})
    n_follows = sum(len(v) for a, v in seen2["follows"].items() if a in feed)
    errs = {f"{x['id']}": {k: x.get(k) for k in ("errors", "follow_back_errors", "skipped_locked",
                                                  "skipped_cooldown", "first_error")}
            for x in flat if x.get("errors") or x.get("follow_back_errors") or x.get("first_error")
            or x.get("done") is None}
    ctx.check(COUNTS, n_sends > 0 and n_sends == rows2 and len(rows1) == len(ids1) and fans_sent == welcomes
              and n_follows == fb and not errs,
              of_sends=n_sends, welcome_rows=rows2, fans_sent=fans_sent, welcomes_sent=welcomes,
              follows=n_follows, followed_back=fb, errors=errs)

    want = sorted(aids)
    toast_bad = [b for x in (*bad1, *bad2) for b in x]
    ctx.check(POKE, tick0["welcome"] == want and control["welcome"] == [] and tick1["welcome"] == want
              and floor["welcome"] == []
              and tick2["welcome"] == want and not toast_bad and not q1.get("timed_out") and not q2.get("timed_out"),
              tick0=len(tick0["welcome"]), control=control["welcome"], tick1=len(tick1["welcome"]),
              under_floor=floor["welcome"],
              tick2=len(tick2["welcome"]), creators=len(want), toast_errors=toast_bad[:5],
              statuses=[t["status"] for t in (tick0, control, tick1, floor, tick2)])

    missing = {i: len(ids1 - set(t.message_ids)) for i, t in enumerate(tabs) if ids1 - set(t.message_ids)}
    ctx.check(LIVE, bool(ids1) and not missing, bubbles=len(ids1), tabs=len(tabs), tabs_missing=len(missing),
              e_g=dict(list(missing.items())[:5]), unopened=unopened[:5],
              ended=[t.ended for t in tabs if t.ended][:3])

    per = sorted((x["done"] - x["start"]).total_seconds() * 1000 / int(x["welcomes_sent"])
                 for v in runs1.values() for x in v if x.get("done") and int(x.get("welcomes_sent") or 0))
    p95 = per[min(len(per) - 1, int(round(0.95 * (len(per) - 1))))] if per else float("inf")
    ctx.check(f"tick-1 run time per welcome p95 <= {PER_WELCOME_P95_MS} ms", p95 <= PER_WELCOME_P95_MS,
              budget=True, p95_ms=round(p95, 1), per_creator=[round(x, 1) for x in per])
    ctx.metric("p95_vs_last_green", {"run time per welcome": round(p95, 1)})
    ctx.metric("ticks", {k: {"ms": round(t["ms"], 1), "spawned": t.get("spawned"), "welcome_runs": len(t["welcome"])}
                         for k, t in (("tick0", tick0), ("control", control), ("tick1", tick1), ("floor", floor),
                                       ("tick2", tick2))})
    ctx.metric("runs1", {a: {k: v[0].get(k) for k in ("new_subscribers", "welcomes_sent", "followed_back",
                                                       "skipped_existing", "skipped_guard", "after_of_welcome_fans",
                                                       "of_welcome_on", "errors", "run_wall_s")}
                         for a, v in runs1.items() if v})
    ctx.note(f"tick 1: {fans_sent} welcomes / {n_sends} bubbles over {len(aids)} Creators "
             f"({len(of_on)} OF-welcome-on), {n_follows} follows, {len(tabs)} tabs; tick 2: {sends2} sends; "
             f"per-welcome p95 {p95:.0f} ms")
