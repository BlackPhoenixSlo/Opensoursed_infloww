"""Full chat sweeps (`scrape_chats`, payload `{}`) run on a cadence, never one per relay restart,
and never read a chat OnlyFans lists as unread (service/sweep_cadence.py,
service/automations/scrape_chats.py).

Prod (2026-11, measured): the boot seed enqueued one sweep per account on every restart with no
dedupe; 16 deploys in 48 h left up to 18 identical pending sweeps per account on a 2-slot bulk lane.
A sweep's `GET /chats/{fan}/messages` marks the chat read on OF, which an agency working in another
CRM sees flip before anyone answered.

World: `flat_agency` with CREATORS Creators, each with a captured session (the relay's REAL
OFClient against lib/of_wire.py, `OF_WIRE`). Each Creator's OF chat list holds CHATS of its Fans,
N_UNREAD of them with `unreadMessagesCount` > 0 (half of those also `hasUnread`). The last two
Creators are deactivated (the real `POST /admin/accounts/{id}/active`) and session-dead (SQL: the
row `account_health.mark_session_dead` writes, probe stamped now so the recovery probe stays off).
Each live Creator carries, by SQL, BACKLOG identical pending `{}` sweeps (what BACKLOG restarts of
the old boot seed left) and one future-dated `fan_ids` scrape of an unread Fan.

Phases: (1) one cadence pass; (2) RESTARTS times: SIGTERM + start the relay (`stack.stop_relay`,
as `docker stop`), two cadence passes; (3) supervisor passes (`/__slop/automation-tick`) until no
live Creator has an open sweep: the sweeps run against the fake OF; (4) restart + a cadence pass;
(5) Creator 0's sweep runs aged past SWEEP_EVERY_S by SQL + a cadence pass; (6) the `fan_ids` jobs
made due by SQL + a supervisor pass.

Checks (names in lib/sweep_cadence_faults.py): ONE_OPEN (every observation: at most one
pending/running `{}` sweep per Creator); COLLAPSE (each backlog's oldest job is the one left, the
rest cancelled 'duplicate full sweep', the `fan_ids` job still pending until phase 6); ANCHOR (no
sweep after phase 4 while the last finished one is recent, exactly Creator 0's after phase 5,
none ever for the deactivated / session-dead Creator); UNREAD (each live Creator's sweep read
exactly its read chats at OF, recorded chats_skipped_unread == N_UNREAD, and the phase-6 `fan_ids`
job read its unread Fan). Evidence `sweep-cadence.json`.

Bypasses (declared): OF at its wire (lib/of_wire.py: one message per chat; 50 ms a call, a
guess); the cadence's timer (`/__slop/sweep-cadence-tick`, lib/sweep_cadence_relay.py: one
`sweep_cadence.tick()` pass; prod's periodic task starts FIRST_AFTER_S after boot, TICK_S apart)
and the supervisor's (`/__slop/automation-tick`); time (a finished run's `completed_at` and the
`fan_ids` jobs' `run_at` moved by SQL, the rows the product wrote, their times only).
Break-it-once: `sweep-enqueued-every-pass` (the scenario's FAULT: each pass enqueues for every
live Creator, the old per-restart seed in the new loop): only ONE_OPEN and ANCHOR;
`--fault=sweep-reads-unread-chats` (the chat list's unread fields dropped in OFClient): only UNREAD.
"""
from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import datetime, timedelta

from slop.lib.client import Recorder
from slop.lib.sweep_cadence_faults import ANCHOR, COLLAPSE, ONE_OPEN, UNREAD
from slop.seed import ts

PROFILE = "flat_agency"
UI = False
OF_WIRE = True
FAULT = "sweep-enqueued-every-pass"
CREATORS = 5          # 3 live, 1 deactivated, 1 session-dead
CHATS = 12            # each Creator's OF chat list
N_UNREAD = 4          # of them unread on OF
BACKLOG = 5           # identical pending {} sweeps per live Creator (the old seed, 5 restarts)
RESTARTS = 3
SWEEP_EVERY_S = 4 * 3600   # service/sweep_cadence.py SWEEP_EVERY_S (the scenario imports no service code)
DUP_REASON = "duplicate full sweep"
MSG_ROUTE = "GET /api2/v2/chats/{id}/messages"


async def run(ctx) -> None:
    w, fake = ctx.world, ctx.of_wire
    w.data["flat_creators"] = int(ctx.param("creators", CREATORS))
    await ctx.build(PROFILE)
    creators = [c["id"] for c in w.data["creators"]]
    live, off, dead = creators[:-2], creators[-2], creators[-1]
    rng = w.rng("scenario:sweep-cadence")

    # OF's chat lists: CHATS Fans each, UNREAD of them unread.
    read_fans: dict[str, set[int]] = {}
    unread_fans: dict[str, list[int]] = {}
    with fake.lock:
        for aid in creators:
            fans = rng.sample([f["id"] for f in w.data["fans"][aid]], CHATS)
            unread = fans[:N_UNREAD]
            unread_fans[aid], read_fans[aid] = unread, set(fans[N_UNREAD:])
            fake.chats[aid] = [{"withUser": {"id": fan, "username": f"u{fan}", "name": f"Fan {fan}"},
                                "unreadMessagesCount": (1 + k % 3) if fan in unread else 0,
                                "hasUnread": fan in unread[::2], "isMutedNotifications": False}
                               for k, fan in enumerate(fans)]

    (await ctx.owner.post(f"/admin/accounts/{off}/active", json={"active": False})).raise_for_status()
    now = datetime.utcnow()
    backlog: dict[str, list[int]] = {}
    fan_job: dict[str, int] = {}
    con = w.sql()
    with con:
        con.execute("INSERT INTO account_health (account_id, session_dead_at, session_dead_reason, last_probe_at)"
                    " VALUES (?, ?, 'wrong_user', ?) ON CONFLICT(account_id) DO UPDATE SET"
                    " session_dead_at=excluded.session_dead_at, session_dead_reason=excluded.session_dead_reason,"
                    " last_probe_at=excluded.last_probe_at", (dead, ts(now), ts(now)))
        for aid in live:
            for k in range(BACKLOG):
                at = ts(now - timedelta(hours=10 - k))
                cur = con.execute("INSERT INTO scheduled_jobs (account_id, kind, payload_json, run_at, status, attempts,"
                                  " created_at) VALUES (?, 'scrape_chats', '{}', ?, 'pending', 0, ?)", (aid, at, at))
                backlog.setdefault(aid, []).append(int(cur.lastrowid))
            cur = con.execute("INSERT INTO scheduled_jobs (account_id, kind, payload_json, run_at, status, attempts,"
                              " created_at) VALUES (?, 'scrape_chats', ?, ?, 'pending', 0, ?)",
                              (aid, json.dumps({"fan_ids": [unread_fans[aid][0]]}),
                               ts(now + timedelta(days=1)), ts(now)))
            fan_job[aid] = int(cur.lastrowid)
    con.close()

    def jobs() -> list[dict]:
        con = w.sql()
        try:
            rows = con.execute("SELECT id, account_id, payload_json, status, last_error FROM scheduled_jobs"
                               " WHERE kind='scrape_chats' ORDER BY id").fetchall()
        finally:
            con.close()
        return [{"id": r[0], "account_id": r[1], "payload": r[2], "status": r[3], "last_error": r[4]} for r in rows]

    def open_sweeps(js: list[dict]) -> Counter:
        return Counter(j["account_id"] for j in js if j["payload"] == "{}" and j["status"] in ("pending", "running"))

    observations: list[dict] = []
    ticks: list[dict] = []
    hook = ctx.owner.share(rec=Recorder(), limits=2)

    def observe(label: str) -> list[dict]:
        js = jobs()
        observations.append({"at": label, "open": dict(open_sweeps(js)),
                             "sweeps_total": dict(Counter(j["account_id"] for j in js if j["payload"] == "{}"))})
        return js

    async def cadence(label: str) -> None:
        r = await hook.post("/__slop/sweep-cadence-tick", timeout=60)
        r.raise_for_status()
        ticks.append({"at": label, **r.json()})
        observe(label)

    async def drain(label: str, rounds: int = 6) -> None:
        for k in range(rounds):
            r = await hook.post("/__slop/automation-tick", timeout=600)
            r.raise_for_status()
            ticks.append({"at": f"{label} drain {k}", **r.json()})
            if not any(open_sweeps(jobs())[a] for a in live):
                break
        observe(label)

    async def restart(label: str) -> None:
        nonlocal hook
        await asyncio.to_thread(ctx.stack.stop_relay, 0, 20.0)
        await asyncio.to_thread(ctx.stack.start_relay)
        hook = ctx.owner.share(rec=Recorder(), limits=2)
        observe(label)

    # (1) + (2): collapse, then restarts.
    await cadence("first pass")
    for i in range(RESTARTS):
        await restart(f"restart {i + 1}")
        await cadence(f"restart {i + 1} pass a")
        await cadence(f"restart {i + 1} pass b")
    js = jobs()
    by_id = {j["id"]: j for j in js}
    collapse_bad = []
    for aid in live:
        ids = backlog[aid]
        if by_id[ids[0]]["status"] not in ("pending", "running"):
            collapse_bad.append((aid, "oldest not kept", by_id[ids[0]]["status"]))
        for jid in ids[1:]:
            if (by_id[jid]["status"], by_id[jid]["last_error"]) != ("cancelled", DUP_REASON):
                collapse_bad.append((aid, jid, by_id[jid]["status"], by_id[jid]["last_error"]))
        if by_id[fan_job[aid]]["status"] != "pending":
            collapse_bad.append((aid, "fan_ids job", by_id[fan_job[aid]]["status"]))

    # (3) the sweeps run.
    calls_before = len(fake.calls)
    await drain("sweeps run")
    with fake.lock:
        sweep_calls = list(fake.calls[calls_before:])
    fetched = {aid: {int(c["path"].rsplit("/", 2)[-2]) for c in sweep_calls
                     if c["account"] == aid and c["route"] == MSG_ROUTE} for aid in creators}
    con = w.sql()
    try:
        runs = con.execute("SELECT account_id, status, stats_json FROM automation_runs WHERE kind='scrape_chats'"
                           " ORDER BY id").fetchall()
    finally:
        con.close()
    skipped = {a: [json.loads(s or "{}").get("chats_skipped_unread") for a2, st, s in runs if a2 == a and st == "ok"]
               for a in live}

    # (4) a restart right after: nothing due.
    await restart("restart after sweeps")
    await cadence("after sweeps pass")
    recent_open = {a: n for a, n in open_sweeps(jobs()).items() if a in live and n}

    # (5) Creator 0's last sweep ages past SWEEP_EVERY_S.
    con = w.sql()
    with con:
        con.execute("UPDATE automation_runs SET completed_at=? WHERE kind='scrape_chats' AND account_id=?",
                    (ts(datetime.utcnow() - timedelta(seconds=SWEEP_EVERY_S + 60)), live[0]))
    con.close()
    await cadence("creator 0 aged")
    aged_open = {a: n for a, n in open_sweeps(jobs()).items() if n}
    ever_off = {a: max(o["sweeps_total"].get(a, 0) for o in observations) for a in (off, dead)}

    # (6) the fan_ids jobs come due: each reads the unread Fan it names.
    con = w.sql()
    with con:
        con.execute("UPDATE scheduled_jobs SET run_at=? WHERE id IN (%s)" % ",".join("?" * len(fan_job)),
                    (ts(datetime.utcnow() - timedelta(seconds=1)), *fan_job.values()))
        # Creator 0's new sweep stays out of this pass (it would read the same read chats again).
        con.execute("UPDATE scheduled_jobs SET run_at=? WHERE kind='scrape_chats' AND payload_json='{}'"
                    " AND status='pending' AND account_id=?", (ts(datetime.utcnow() + timedelta(days=1)), live[0]))
    con.close()
    calls_before = len(fake.calls)
    r = await hook.post("/__slop/automation-tick", timeout=600)
    r.raise_for_status()
    ticks.append({"at": "fan_ids due", **r.json()})
    with fake.lock:
        fan_calls = list(fake.calls[calls_before:])
    fan_fetched = {aid: {int(c["path"].rsplit("/", 2)[-2]) for c in fan_calls
                         if c["account"] == aid and c["route"] == MSG_ROUTE} for aid in live}
    fan_status = {j["id"]: j["status"] for j in jobs() if j["id"] in fan_job.values()}

    (ctx.out / "sweep-cadence.json").write_text(json.dumps({
        "creators": {"live": live, "deactivated": off, "session_dead": dead},
        "unread": unread_fans, "read": {a: sorted(v) for a, v in read_fans.items()},
        "backlog": backlog, "fan_jobs": fan_job, "observations": observations, "ticks": ticks,
        "sweep_fetched": {a: sorted(v) for a, v in fetched.items()},
        "fan_fetched": {a: sorted(v) for a, v in fan_fetched.items()}, "skipped_unread": skipped,
    }, indent=1, default=str))

    over = [(o["at"], a, n) for o in observations for a, n in o["open"].items() if n > 1]
    ctx.check(ONE_OPEN, not over, observations=len(observations), restarts=RESTARTS + 1, over=over[:10])
    ctx.check(COLLAPSE, not collapse_bad, backlog=BACKLOG, bad=collapse_bad[:10])
    anchor_bad = []
    if recent_open:
        anchor_bad.append(("open sweep while the last finished one is recent", recent_open))
    if {a: n for a, n in aged_open.items() if a in live} != {live[0]: 1}:
        anchor_bad.append(("after creator 0 aged, want only it", aged_open))
    if any(ever_off.values()):
        anchor_bad.append(("deactivated / session-dead got a sweep", ever_off))
    ctx.check(ANCHOR, not anchor_bad, bad=anchor_bad)
    unread_bad = []
    for aid in live:
        if fetched[aid] != read_fans[aid]:
            unread_bad.append((aid, "sweep read", sorted(fetched[aid] - read_fans[aid]),
                               "missed", sorted(read_fans[aid] - fetched[aid])))
        if not skipped[aid] or any(s != N_UNREAD for s in skipped[aid]):
            unread_bad.append((aid, "chats_skipped_unread", skipped[aid]))
        if fan_fetched[aid] != {unread_fans[aid][0]} or fan_status.get(fan_job[aid]) != "done":
            unread_bad.append((aid, "fan_ids job", sorted(fan_fetched[aid]), fan_status.get(fan_job[aid])))
    for aid in (off, dead):
        if fetched[aid]:
            unread_bad.append((aid, "deactivated / dead Creator read", sorted(fetched[aid])))
    ctx.check(UNREAD, not unread_bad, unread=N_UNREAD, chats=CHATS, bad=unread_bad[:10])
    ctx.metric("sweep_cadence", {"observations": len(observations), "sweep_runs": len(runs),
                                 "of_message_reads": sum(len(v) for v in fetched.values())})
