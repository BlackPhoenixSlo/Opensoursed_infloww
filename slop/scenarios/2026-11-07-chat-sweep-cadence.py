"""Full chat sweeps (`scrape_chats`, payload `{}`) run on a cadence, never one per relay restart
(service/sweep_cadence.py).

Prod AE (2026-11, measured): the boot seed enqueued one sweep per account on every restart with no
dedupe; 16 deploys in 48 h left up to 18 identical pending sweeps per account on a 2-slot bulk lane.

World: `flat_agency` with CREATORS Creators, each with a captured session (the relay's REAL
OFClient against lib/of_wire.py, `OF_WIRE`). Each Creator's OF chat list holds CHATS of its Fans.
A live Creator's last four are deep threads (DEEP messages, OF pages them desc by `id` and asc by
`offset`): SILENT Silent mass-only chats (all our queued mass rows, `isFromQueue`, Fans with no DB
row), one the same but for a Fan with a fan message in the DB, one with a fan reply on page 1.
The last two
Creators are deactivated (the real `POST /admin/accounts/{id}/active`) and session-dead (SQL: the
row `account_health.mark_session_dead` writes, probe stamped now so the recovery probe stays off).
Each live Creator carries, by SQL, BACKLOG identical pending `{}` sweeps (what BACKLOG restarts of
the old boot seed left) and one future-dated `fan_ids` scrape.

Phases: (1) one cadence pass; (2) RESTARTS times: SIGTERM + start the relay (`stack.stop_relay`,
as `docker stop`), two cadence passes; (3) supervisor passes (`/__slop/automation-tick`) until no
live Creator has an open sweep: the sweeps run against the fake OF; (4) restart + a cadence pass;
(3b) each live Creator's first Silent mass-only chat gets the steps in TRIGGERS: Click reads (a plain `GET
/api/of/v2/chats/{fan}/messages` head read, or `POST /api/of/v2/chats/{fan}/mark-as-read`) and warms (the app's
prefetch: `peek=1` at background priority), the second and later Click reads inside the dedup window;
TRIGGERS[2] is the warm-then-open leg: a warm, then the inbox open that rides it, which sends only its
mark-as-read; Creator 0's second gets REPLY_LEG (a fan reply frame through `/__slop/of-ws-frame`, which the WS
transcoder counts into `chats.unread_count`, then warms while it is unread); the other Creators' second
none; each fan-message deep chat one head read; supervisor passes run the jobs they bought; (5) Creator 0's sweep runs aged past SWEEP_EVERY_S by SQL + a cadence pass; (6) FakeOF answers Creator 0's
chat reads 429 after its first FF_GOOD chats and one supervisor pass runs the sweep phase 5 enqueued.

Checks (names in lib/sweep_cadence_faults.py): ONE_OPEN (every observation: at most one
pending/running `{}` sweep per Creator); COLLAPSE (each backlog's oldest job is the one left, the
rest cancelled 'duplicate full sweep', the `fan_ids` job still pending); ANCHOR (no sweep after
phase 4 while the last finished one is recent, exactly Creator 0's after phase 5, none ever for the
deactivated / session-dead Creator); FAILFAST (phase 6: the sweep stops at FAIL_FAST failed reads, FF_GOOD
good reads then FAIL_FAST 429s, and its run is not ok and carries no `full_sweep`); DEFER (phase 3: each
Silent mass-only chat costs one messages page and no asc page, keeps that page and is left deferred with a NULL
cursor; the two other deep chats get both ends and a cursor, no mark); BACKFILL_ON_DEMAND (phase 3b: a
deferred chat gets one `deferred_history` job, bought by its first Click read alone (no warm before it buys one),
ends with a cursor, no mark, and the rows and asc pages of the Creator's fan-message deep chat, today's first
scrape; the REPLY_LEG chat's reply leaves it unread and buys nothing, nor do its warms: no job, still deferred, no
asc page; every head read answered 200 after one OF read, every mark-as-read 200; no job for the untriggered or the not-deferred chat); DEFER_NET (history pages of the Silent mass-only chats since phase 3,
route head reads left out, below the same chats at the fan-message deep chat's sweep cost, which is what
SCRAPE_EAGER_HISTORY=1 pays for them; inferred reference: same depth, same paging, no trigger buys a job under
eager). Evidence `sweep-cadence.json`.

Bypasses (declared): OF at its wire (lib/of_wire.py: one message per chat; 50 ms a call, a
guess); the cadence's timer (`/__slop/sweep-cadence-tick`, lib/sweep_cadence_relay.py: one
`sweep_cadence.tick()` pass; prod's periodic task starts FIRST_AFTER_S after boot, TICK_S apart)
and the supervisor's (`/__slop/automation-tick`); the 429 burst (an `extra_routes` handler on FakeOF's chat
messages route, OF's `TOO_MANY_BODY`; its tracebacks are EXPECTED_TRACEBACKS); time (a finished run's `completed_at` moved by
SQL, the row the product wrote, its time only).
Break-it-once: `sweep-enqueued-every-pass` (the scenario's FAULT: each pass enqueues for every
live Creator, the old per-restart seed in the new loop): only ONE_OPEN and ANCHOR.
`failfast-only-before-first-scan` (the sweep's stop only before its first scraped chat, as before): only FAILFAST.
`history-eager` (SCRAPE_EAGER_HISTORY=1, today's both-ends backfill on every first scrape): only DEFER and DEFER_NET.
`no-deferred-trigger` (the Click read triggers enqueue nothing): only BACKFILL_ON_DEMAND.
The warm-then-open leg is TRIGGERS[2]: the unread warm's peeked head read buys nothing; the inbox open inside
UNREAD_WARM_REUSE_MS (20 s, app/hooks/useUnreadMessagesPrefetch.ts) rides it and sends only its mark-as-read, which
alone buys the job (`jobs_after` [0, 1, 1]); slow-connections' WARM_REUSED proves the open in the browser.
"""
from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import datetime, timedelta
from urllib.parse import parse_qs

from slop.actors import fan_dm
from slop.lib.client import Recorder
from slop.lib.of_wire import TOO_MANY_BODY, unread
from slop.lib.sweep_cadence_faults import (ANCHOR, BACKFILL_ON_DEMAND, COLLAPSE, DEFER, DEFER_NET, FAILFAST,
                                           ONE_OPEN)
from slop.seed import ts

PROFILE = "flat_agency"
UI = False
OF_WIRE = True
FAULT = "sweep-enqueued-every-pass"
CREATORS = 5          # 3 live, 1 deactivated, 1 session-dead
CHATS = 12            # each Creator's OF chat list
BACKLOG = 5           # identical pending {} sweeps per live Creator (the old seed, 5 restarts)
RESTARTS = 3
SWEEP_EVERY_S = 4 * 3600   # service/sweep_cadence.py SWEEP_EVERY_S (the scenario imports no service code)
DUP_REASON = "duplicate full sweep"
MSG_ROUTE = "GET /api2/v2/chats/{id}/messages"
FF_GOOD = 3           # phase 6: Creator 0's chats OF still answers before the 429 burst
FAIL_FAST = 5         # service/automations/scrape_chats.py SCRAPE_SWEEP_FAIL_FAST default
# Phase 6's tracebacks, the errors FakeOF's 429 burst makes: each failed chat read, and the broken-off run.
SILENT = 2            # Silent mass-only chats per live Creator (the tail of its chat list, after FAILFAST's reads)
DEEP = 150            # a deep thread's messages: page 1 (the sweep's limit 50) reports hasMore
DEEP_ID_BASE = 7_100_000_000_000   # deep threads' OF ids, below threads.HISTORY_ID_BASE and every relay band
HEAD_LIMIT = 10        # a chat open's head read (the app's page), != the sweep's 50
# service/of_reads.PEEK_CURSOR: a Background first page sends it as `id`; it is no cursor.
PEEK_ID = "9223372036854775807"
REPLY_ID_BASE = fan_dm.INJECT_ID_BASE + 880_000   # phase 3b's fan reply frames
# Phase 3b's triggers, per live Creator (by index) on its first Silent mass-only chat: each first Click read buys
# the job alone. "read" = a plain head read (a Click read); "mark" = a mark-as-read POST (a Click read); "warm" = the
# app's prefetch (peek=1, background priority); "reply" = a fan reply frame.
CLICKS = ("read", "mark")
TRIGGERS = (("read", "read"),
            ("warm", "read", "warm", "read"),
            ("warm", "mark", "read"))
# Creator 0's second Silent mass-only chat (the other Creators' stay untriggered): his reply leaves it unread, and
# neither it nor the warms after it buy anything.
REPLY_LEG = ("reply", "warm", "warm")
UNREAD_WAIT_S = 5      # the reply frame's unread bump lands off the inject request
EXPECTED_TRACEBACKS = (("scrape_chat_failed account=", "Too many requests"),
                       ("kind=scrape_chats", "full sweep stopped after"))


async def run(ctx) -> None:
    w, fake = ctx.world, ctx.of_wire
    w.data["flat_creators"] = int(ctx.param("creators", CREATORS))
    await ctx.build(PROFILE)
    creators = [c["id"] for c in w.data["creators"]]
    assert len(creators) >= len(TRIGGERS) + 2, "need a live Creator for each trigger leg"
    live, off, dead = creators[:-2], creators[-2], creators[-1]
    rng = w.rng("scenario:sweep-cadence")

    # OF's chat lists: CHATS Fans each; a live Creator's tail is its deep threads.
    con = w.sql()
    try:
        in_db = {(r[0], r[1]) for r in con.execute("SELECT DISTINCT account_id, fan_id FROM messages")}
        # a db_inbound pick must be read locally: an unread one is held back from its asc pass
        inbound = {(r[0], r[1]) for r in con.execute(
            "SELECT DISTINCT m.account_id, m.fan_id FROM messages m JOIN chats c"
            " ON c.account_id=m.account_id AND c.fan_id=m.fan_id"
            " WHERE m.direction='in' AND COALESCE(c.unread_count, 0)=0")}
    finally:
        con.close()
    listed: dict[str, list[int]] = {}
    deep: dict[tuple[str, int], list[dict]] = {}     # (Creator, Fan) -> OF's thread, newest first
    deep_kind: dict[str, dict[int, str]] = {}        # Creator -> Fan -> silent | db_inbound | reply
    for aid in creators:
        ids = [f["id"] for f in w.data["fans"][aid]]
        kinds: dict[int, str] = {}
        if aid in live:
            quiet = rng.sample(sorted(i for i in ids if (aid, i) not in in_db), SILENT + 1)
            kinds = {**{f: "silent" for f in quiet[:SILENT]}, quiet[SILENT]: "reply",
                     rng.choice(sorted(i for i in ids if (aid, i) in inbound)): "db_inbound"}
        deep_kind[aid] = kinds
        listed[aid] = rng.sample([i for i in ids if i not in kinds], CHATS - len(kinds)) + list(kinds)
        for fan, kind in kinds.items():
            base = DEEP_ID_BASE + (fan % 1_000_000) * 1_000
            rows = [{"id": base + i, "text": f"mass {i}", "fromUser": {"id": int(aid)}, "isFromQueue": True,
                     "isFree": True, "price": 0, "media": [], "mediaCount": 0,
                     "createdAt": (datetime(2026, 11, 1) + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%S+00:00")}
                    for i in range(DEEP, 0, -1)]
            if kind == "reply":
                rows[2] = {**rows[2], "text": "hey you", "fromUser": {"id": fan}, "isFromQueue": False}
            deep[(aid, fan)] = rows

    def deep_route(h, method, u, uid, route, _raw) -> bool:
        """A deep thread's messages page as OF pages it: desc older than `id`, asc from `offset`."""
        if method != "GET" or route != MSG_ROUTE:
            return False
        rows = deep.get((uid, int(u.path.rsplit("/", 2)[-2])))
        if rows is None:
            return False
        q = parse_qs(u.query)
        lim = int((q.get("limit") or ["10"])[0])
        if (q.get("order") or ["desc"])[0] == "asc":
            off = int((q.get("offset") or ["0"])[0])
            page, more = rows[::-1][off:off + lim], off + lim < len(rows)
        else:
            before = (q.get("id") or [None])[0]
            pool = [r for r in rows if before is None or r["id"] < int(before)]
            page, more = pool[:lim], len(pool) > lim
        h._record(uid, route, 200, {"list": page, "hasMore": more})
        return True

    with fake.lock:
        for aid in creators:
            fake.chats[aid] = [{"withUser": {"id": fan, "username": f"u{fan}", "name": f"Fan {fan}"},
                                "unreadMessagesCount": 0, "isMutedNotifications": False} for fan in listed[aid]]
        fake.extra_routes.append(deep_route)

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
                              (aid, json.dumps({"fan_ids": [listed[aid][0]]}),
                               ts(now + timedelta(days=1)), ts(now)))
            fan_job[aid] = int(cur.lastrowid)
    con.close()

    def jobs() -> list[dict]:
        con = w.sql()
        try:
            # scrape_fan: a one-fan scrape (enqueue_fan_scrape, its own kind since 90e5e97b4: the sender lane)
            rows = con.execute("SELECT id, account_id, payload_json, status, last_error, kind FROM scheduled_jobs"
                               " WHERE kind IN ('scrape_chats', 'scrape_fan') ORDER BY id").fetchall()
        finally:
            con.close()
        return [{"id": r[0], "account_id": r[1], "payload": r[2], "status": r[3], "last_error": r[4], "kind": r[5]}
                for r in rows]

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
        deep_db = {}
        for (aid, fan) in deep:
            h = con.execute("SELECT last_message_id, history_deferred_at FROM scrape_history"
                            " WHERE account_id=? AND fan_id=?", (aid, fan)).fetchone()
            n = con.execute("SELECT COUNT(*) FROM messages WHERE account_id=? AND fan_id=? AND message_id>=?"
                            " AND message_id<?", (aid, fan, DEEP_ID_BASE, DEEP_ID_BASE + 10**9)).fetchone()[0]
            deep_db[(aid, fan)] = {"cursor": h[0] if h else None, "deferred_at": h[1] if h else None, "rows": n}
    finally:
        con.close()
    deep_reads: dict[tuple[str, int], list[dict]] = {}
    for c in sweep_calls:
        if c["route"] == MSG_ROUTE and (key := (c["account"], int(c["path"].rsplit("/", 2)[-2]))) in deep:
            q = parse_qs(c["query"])
            deep_reads.setdefault(key, []).append({"order": (q.get("order") or ["desc"])[0],
                                                   "id": next((i for i in q.get("id", []) if i != PEEK_ID), None),
                                                   "offset": (q.get("offset") or [None])[0]})
    full_runs = Counter(r[0] for r in runs if json.loads(r[2] or "{}").get("full_sweep"))
    defer_bad = []
    for (aid, fan), reads in sorted(((k, deep_reads.get(k, [])) for k in deep), key=str):
        kind, db = deep_kind[aid][fan], deep_db[(aid, fan)]
        asc = sum(r["order"] == "asc" for r in reads)
        if kind == "silent":
            # one page-1 read per full sweep that ran (one sweep, unless a fault ran more)
            ok = (reads == [{"order": "desc", "id": None, "offset": None}] * max(1, full_runs[aid])
                  and db["cursor"] is None
                  and db["deferred_at"] is not None and db["rows"] == 50)
        else:
            ok = asc > 0 and db["cursor"] is not None and db["deferred_at"] is None
        if not ok:
            defer_bad.append({"creator": aid, "fan": fan, "kind": kind, "pages": len(reads), "asc": asc,
                              "full_sweeps": full_runs[aid], **db})

    # (3b) the deferred chats' triggers: Click reads, warms, the reply leg's fan reply frame;
    # a head read of a not-deferred deep chat too. Then supervisor passes run what they enqueued.
    def backfills() -> Counter:
        return Counter((j["account_id"], fid) for j in jobs() if j["kind"] == "scrape_fan"
                       for fid in json.loads(j["payload"]).get("fan_ids", [])
                       if json.loads(j["payload"]).get("source") == "deferred_history")

    def marker(aid: str, fan: int) -> int:
        con = w.sql()
        try:
            h = con.execute("SELECT unread_count FROM chats WHERE account_id=? AND fan_id=?", (aid, fan)).fetchone()
        finally:
            con.close()
        return int(h[0] or 0) if h else 0

    def deferred_now(aid: str, fan: int) -> bool:
        con = w.sql()
        try:
            h = con.execute("SELECT history_deferred_at FROM scrape_history WHERE account_id=? AND fan_id=?",
                            (aid, fan)).fetchone()
        finally:
            con.close()
        return bool(h and h[0])

    silent_of = {aid: [f for f, k in deep_kind[aid].items() if k == "silent"] for aid in live}
    plain_deep = {aid: next(f for f, k in deep_kind[aid].items() if k == "db_inbound") for aid in live}
    trig: dict[tuple[str, int], dict] = {}
    head_ms: list[float] = []
    # the opens go on the owner's own recorder: the run's http table carries the head read's p95
    opener = ctx.owner.share(limits=2)
    reply_ids = iter(range(REPLY_ID_BASE, REPLY_ID_BASE + 10**6))

    async def head_read(aid: str, fan: int, warm: bool = False) -> dict:
        hdr = {"X-Account-Id": aid, **({"X-Priority": "background"} if warm else {})}
        with fake.lock:
            at = len(fake.calls)
        t0 = asyncio.get_running_loop().time()
        r = await opener.get(f"/api/of/v2/chats/{fan}/messages?limit={HEAD_LIMIT}{'&peek=1' if warm else ''}",
                             headers=hdr, timeout=60)
        ms = round((asyncio.get_running_loop().time() - t0) * 1000, 1)
        with fake.lock:
            of = [c for c in fake.calls[at:] if c["route"] == MSG_ROUTE and c["account"] == aid
                  and int(c["path"].rsplit("/", 2)[-2]) == fan]
        head_ms.append(ms)
        ids = [parse_qs(c["query"], keep_blank_values=True).get("id", []) for c in of]
        return {"status": r.status_code, "of_reads": len(of), "ids": ids, "ms": ms, "warm": warm}

    def head_ok(read: dict) -> bool:
        return (read["status"] == 200 and read["ids"] == ([[PEEK_ID]] if read["warm"] else [[]])
                and (not read["warm"] or read["unread_before"] == read["unread_after"]))

    legs = [(aid, silent_of[aid][0], "read", TRIGGERS[i % len(TRIGGERS)]) for i, aid in enumerate(live)]
    legs.append((live[0], silent_of[live[0]][1], "reply", REPLY_LEG))
    for aid, fan, leg, steps in legs:
        t = trig[(aid, fan)] = {"leg": leg, "steps": list(steps), "deferred_before": deferred_now(aid, fan),
                                "reads": [], "marks": [], "replies": 0, "unread_before_reply": None,
                                "unread_after_reply": None, "jobs_after": []}
        if "mark" in steps:
            with fake.lock:
                fake.mark(aid, fan, read=False)
        for how in steps:
            if how == "mark":
                with fake.lock:
                    at = len(fake.calls)
                    was_unread = next(unread(row) for row in fake.chats[aid] if row["withUser"]["id"] == fan)
                r = await opener.post(f"/api/of/v2/chats/{fan}/mark-as-read", headers={"X-Account-Id": aid},
                                      timeout=60)
                with fake.lock:
                    reached_of = any(c["account"] == aid and c["route"].startswith("POST ") and c["status"] == 200
                                     and c["path"] == f"/api2/v2/chats/{fan}/mark-as-read" for c in fake.calls[at:])
                    is_unread = next(unread(row) for row in fake.chats[aid] if row["withUser"]["id"] == fan)
                t["marks"].append({"status": r.status_code, "reached_of": reached_of,
                                   "was_unread": was_unread, "is_unread": is_unread})
            elif how == "reply":
                fr = fan_dm.frame(next(reply_ids), {"id": fan, "username": f"u{fan}", "name": f"Fan {fan}"},
                                  "hey are you there")
                before = marker(aid, fan)
                t["unread_before_reply"] = before
                (await fan_dm.inject(hook, aid, fr)).raise_for_status()
                t["replies"] += 1
                for _ in range(UNREAD_WAIT_S * 10):
                    if marker(aid, fan) > before:
                        break
                    await asyncio.sleep(0.1)
                t["unread_after_reply"] = marker(aid, fan)
            else:
                if how == "warm":
                    before = marker(aid, fan)
                read = await head_read(aid, fan, warm=how == "warm")
                t["reads"].append(read)
            # the trigger's job lands off the request (the read's fired task): wait for it, or for a wrong one
            for _ in range(30):
                if not t["deferred_before"] or backfills()[(aid, fan)]:
                    break
                await asyncio.sleep(0.1)
            await asyncio.sleep(0.3)
            if how == "warm":
                read.update(unread_before=before, unread_after=marker(aid, fan))
            t["jobs_after"].append(backfills()[(aid, fan)])
    not_deferred_reads = {aid: await head_read(aid, plain_deep[aid]) for aid in live}
    await asyncio.sleep(0.5)
    for k in range(4):
        r = await hook.post("/__slop/automation-tick", timeout=600)
        r.raise_for_status()
        ticks.append({"at": f"backfills drain {k}", **r.json()})
        if not any(j["status"] in ("pending", "running") and "deferred_history" in j["payload"] for j in jobs()):
            break
    jobs_by_fan = backfills()
    with fake.lock:
        net_calls = list(fake.calls[calls_before:])
    con = w.sql()
    try:
        after_db = {}
        for (aid, fan) in deep:
            h = con.execute("SELECT last_message_id, history_deferred_at FROM scrape_history"
                            " WHERE account_id=? AND fan_id=?", (aid, fan)).fetchone()
            n = con.execute("SELECT COUNT(*) FROM messages WHERE account_id=? AND fan_id=? AND message_id>=?"
                            " AND message_id<?", (aid, fan, DEEP_ID_BASE, DEEP_ID_BASE + 10**9)).fetchone()[0]
            after_db[(aid, fan)] = {"cursor": h[0] if h else None, "deferred_at": h[1] if h else None, "rows": n}
    finally:
        con.close()
    # History pages since phase 3 per deep chat: every messages read but the route's head reads (limit HEAD_LIMIT).
    pages: dict[tuple[str, int], dict] = {k: {"desc": 0, "asc": 0} for k in deep}
    for c in net_calls:
        if c["route"] == MSG_ROUTE and (key := (c["account"], int(c["path"].rsplit("/", 2)[-2]))) in deep:
            q = parse_qs(c["query"])
            if (q.get("order") or ["desc"])[0] == "desc" and (q.get("limit") or [""])[0] == str(HEAD_LIMIT) \
                    and not [i for i in q.get("id", []) if i != PEEK_ID]:
                continue
            pages[key]["asc" if (q.get("order") or ["desc"])[0] == "asc" else "desc"] += 1
    backfill_bad = []
    for aid in live:
        ref = plain_deep[aid]           # today's first scrape of a same-depth deep chat (the sweep, phase 3)
        for fan in silent_of[aid]:
            t = trig.get((aid, fan))
            db, pg, n_jobs = after_db[(aid, fan)], pages[(aid, fan)], jobs_by_fan[(aid, fan)]
            if t is None:               # untriggered: no backfill bought
                ok = n_jobs == 0
            elif t["leg"] == "reply":   # unread from his reply on, warms only: nothing bought, history still deferred
                ok = (t["deferred_before"] and n_jobs == 0 and not any(t["jobs_after"])
                      and t["unread_after_reply"] > t["unread_before_reply"]
                      and db["cursor"] is None and db["deferred_at"] is not None and pg["asc"] == 0
                      and all(map(head_ok, t["reads"])))
            else:
                # each Creator's FIRST Click read buys the job alone; a warm before it buys none
                first = next(i for i, how in enumerate(t["steps"]) if how in CLICKS)
                ok = (t["deferred_before"] and n_jobs == 1
                      and t["jobs_after"] == [0] * first + [1] * (len(t["steps"]) - first)
                      and t["marks"] == [{"status": 200, "reached_of": True, "was_unread": True, "is_unread": False}]
                      * t["steps"].count("mark")
                      and db["cursor"] is not None and db["deferred_at"] is None
                      and db["rows"] == after_db[(aid, ref)]["rows"] and pg["asc"] == pages[(aid, ref)]["asc"]
                      and all(map(head_ok, t["reads"])))
            if not ok:
                backfill_bad.append({"creator": aid, "fan": fan, "triggers": t, "jobs": n_jobs, "pages": pg,
                                     "ref_pages": pages[(aid, ref)], "ref_rows": after_db[(aid, ref)]["rows"], **db})
        nd = not_deferred_reads[aid]
        if jobs_by_fan[(aid, ref)] or not head_ok(nd):
            backfill_bad.append({"creator": aid, "fan": ref, "kind": "not deferred", "jobs": jobs_by_fan[(aid, ref)],
                                 "read": nd})
    net_silent = sum(pages[(a, f)]["desc"] + pages[(a, f)]["asc"] for a in live for f in silent_of[a])
    net_eager = sum(len(silent_of[a]) * (pages[(a, plain_deep[a])]["desc"] + pages[(a, plain_deep[a])]["asc"])
                    for a in live)

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

    # (6) Creator 0's due sweep meets a 429 burst after its first FF_GOOD chats.
    ff_uid, ff_chats = live[0], []

    def burst(h, _method, u, uid, route, _raw) -> bool:
        if uid != ff_uid or route != MSG_ROUTE:
            return False
        chat = int(u.path.rsplit("/", 2)[-2])
        with fake.lock:
            if chat not in ff_chats:
                ff_chats.append(chat)
            good = ff_chats.index(chat) < FF_GOOD
        if good:
            return False
        h._record(uid, route, 429, TOO_MANY_BODY)
        return True

    con = w.sql()
    try:
        run_floor = con.execute("SELECT COALESCE(MAX(id), 0) FROM automation_runs").fetchone()[0]
    finally:
        con.close()
    with fake.lock:
        ff_before = len(fake.calls)
        fake.extra_routes.append(burst)
    try:
        r = await hook.post("/__slop/automation-tick", timeout=600)
        r.raise_for_status()
        ticks.append({"at": "failfast", **r.json()})
    finally:
        with fake.lock:
            fake.extra_routes.remove(burst)
            ff_calls = [c["status"] for c in fake.calls[ff_before:]
                        if c["account"] == ff_uid and c["route"] == MSG_ROUTE]
    con = w.sql()
    try:
        ff_runs = [{"status": r[0], "stats": json.loads(r[1] or "{}"), "error": (r[2] or "")[:200]}
                   for r in con.execute("SELECT status, stats_json, error_text FROM automation_runs WHERE"
                                        " kind='scrape_chats' AND account_id=? AND id>? ORDER BY id",
                                        (ff_uid, run_floor)).fetchall()]
    finally:
        con.close()

    (ctx.out / "sweep-cadence.json").write_text(json.dumps({
        "creators": {"live": live, "deactivated": off, "session_dead": dead},
        "listed": listed,
        "backlog": backlog, "fan_jobs": fan_job, "observations": observations, "ticks": ticks,
        "sweep_fetched": {a: sorted(v) for a, v in fetched.items()},
        "failfast": {"creator": ff_uid, "reads": ff_calls, "runs": ff_runs},
        "deep": [{"creator": a, "fan": f, "kind": deep_kind[a][f], "reads": deep_reads.get((a, f), []),
                  **deep_db[(a, f)]} for (a, f) in deep],
        "backfill": {"triggers": [{"creator": a, "fan": f, **t} for (a, f), t in trig.items()],
                     "not_deferred_reads": not_deferred_reads,
                     "jobs": [{"creator": a, "fan": f, "n": n} for (a, f), n in jobs_by_fan.items()],
                     "after": [{"creator": a, "fan": f, "kind": deep_kind[a][f], "pages": pages[(a, f)],
                                **after_db[(a, f)]} for (a, f) in deep],
                     "net": {"silent_pages": net_silent, "eager_pages": net_eager}},
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
    want_reads = [200] * FF_GOOD + [429] * FAIL_FAST
    ctx.check(FAILFAST, ff_calls == want_reads and len(ff_runs) == 1 and ff_runs[0]["status"] != "ok"
              and "full_sweep" not in ff_runs[0]["stats"],
              reads=ff_calls, want=want_reads, chats_listed=CHATS, runs=ff_runs)
    silent = [k for k in deep if deep_kind[k[0]][k[1]] == "silent"]
    ctx.check(DEFER, not defer_bad, silent=len(silent), deep=len(deep),
              silent_pages=sum(len(deep_reads.get(k, [])) for k in silent), bad=defer_bad[:10])
    ctx.check(BACKFILL_ON_DEMAND, not backfill_bad, triggered=len(trig),
              untriggered=sum(len(v) for v in silent_of.values()) - len(trig),
              jobs=sum(jobs_by_fan.values()), bad=backfill_bad[:10])
    ctx.check(DEFER_NET, net_silent < net_eager, silent_pages=net_silent, eager_pages=net_eager,
              silent_chats=sum(len(v) for v in silent_of.values()), triggered=len(trig))
    ctx.metric("sweep_cadence", {"observations": len(observations), "sweep_runs": len(runs),
                                 "of_message_reads": sum(len(v) for v in fetched.values()),
                                 "deep_history_pages": sum(len(v) for v in deep_reads.values()),
                                 "history_pages_with_backfills": net_silent, "eager_history_pages": net_eager,
                                 "head_read_ms_max": max(head_ms) if head_ms else None,
                                 "head_read_ms_p95": (sorted(head_ms)[min(len(head_ms) - 1, int(len(head_ms) * 0.95))]
                                                      if head_ms else None), "head_reads": len(head_ms)})
