"""OnlyFans asks a Creator's login for a 2FA code (HTTP 400, code 101 with
`payload.otpState`, on every call): the account is flagged (account_health,
reason otp_required), its owner gets ONE session_dead notification that opens
Browserbase login (the sign-in that takes the code), the Creators table shows the
repair badge, the account's automations pause and its WS pump parks, while every
other Creator and Agency keeps sending; a re-capture resumes all of it.

The world: five Agencies, twenty Creators (multi_agency_big_models, mass fans by
SQL), each with a captured session in the bootstrap's shape (seed/of_sessions.py),
so the relay builds its REAL OFClient, and a healthy account_health row (an earlier
episode it recovered from). OnlyFans is lib/of_wire.py on loopback
(`OF_WIRE`: the relay's `OF_API_ORIGIN`), answering /users/me (with the WS
ticket), the hash CDN, the signing chunk and the DM send, serving OF's chat
WebSocket, and, for a Creator whose login wants 2FA, every /api2/ call with OF's
code-101 body. Every Creator's REAL of_ws pump runs against that socket (started
by `POST /__slop/pump-supervise`, one pump-supervisor pass, after every executor
tick). `--users` operators (each on its Agency owner's session) schedule
near-term DMs through the real `POST /api/of/v2/scheduled-sends`; the executor
fires them through `POST /__slop/automation-tick` (one real supervisor pass: due
pairs, run slots, the dead-session probe; the 30 s cadence bypassed); each owner
keeps `/events` open and polls `/admin/accounts` and the bell.

Phase A: every Creator healthy, every pump connected, every send delivered. Then
OnlyFans asks OTP_IDX's Creators (one of Agency 0, the UI owner's; two of Agency 1)
and READER (Agency 1, no automations: no operator schedules for it) for a code,
and ends OTP_IDX's sockets, so their pumps reconnect through /users/me while
READS concurrent inbox reads per Creator (the real `GET /api/of/v2/chats`: half in
one burst at the flip, which the old read-then-write flip lets each notify, half
spread over the pump's 1 s reconnect) meet the same 101: many callers of two kinds
at once. READER's socket stays up: only its one inbox read can flag it. Once all are
flagged, phase B schedules more for every Creator while the executor ticks and the
pump supervisor passes; the window from the flip is at least WS_WINDOW_S, which
the old reconnect loop (1, 2, 4, 8 s) fills with five /users/me. Phase C: OnlyFans
takes the logins again and each owner re-captures each flagged Creator through the
real `POST /admin/session/bootstrap` (paste-curl, a signed /users/me curl); the
executor drains the parked sends.

Invariants: account_health flags exactly the 2FA Creators (otp_required); one
session_dead notification per (owner, 2FA Creator) though many callers met the 101
at once, data.href the Browserbase relink, none for any other owner, and each
affected owner's /events carried it; every concurrent read answered 502 (upstream
400); READER's read flagged and notified it; per OTP_IDX Creator at most two
/users/me over the window (the pump's reconnect, the probe's) and its pump exited
and stayed parked through the supervisor passes; after detection a 2FA Creator
makes no run (no automation_runs row), no OF call but the probe's /users/me, its
sends stay pending; every healthy Creator's send reached OF once, in fire-time
order, with its outbound message row (nothing dropped, counts match), Agencies 2-4
untouched; /admin/accounts shows each owner its 2FA Creators paused (the UI's
side-effect check). Recovery: the flags clear, every parked send reaches OF exactly
once in fire-time order with its outbound row, no second notification, each pump
reconnects. UI: the bell's 2FA row (trigger) opens Creators with Browserbase login
(settled), the row reads, and the Creator's row shows the "automations paused"
badge naming Browserbase login. Budgets: route p95s and the tick's, vs the last
green run.
Bypasses, declared: lib/of_wire.py (OnlyFans' API and WebSocket on loopback, its
own declared bypasses), the executor's 30 s and the pump supervisor's 15 s cadence
(the hooks), the pump start re-pointed past _run_ui_safe's no-op (lib/relay.py);
the reads' 502s go to their own recorder (they are this scenario's expected
answer, checked below, not the stock no-5xx check's).
Break-it-once: otp-state-not-session-dead (the classifier's 101 branch reverted);
session-dead-claim-not-atomic (the read-then-write flip it replaced).
Screenshots: trigger-bell-2fa-row, settled-browserbase-login, settled-creators-badge.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from slop.actors import ui
from slop.actors.manager import SseListener
from slop.lib.browserbase import signing
from slop.lib.client import Recorder
from slop.seed import of_sessions

PROFILE = "multi_agency_big_models"
UI = True
OF_WIRE = True
FAULT = "otp-state-not-session-dead"
OTP_IDX = (3, 5, 9)  # Agency 0 (UI owner): Creator 3; Agency 1: Creators 5 and 9 (profile's owner layout)
RELINK = "/creators?relink=browserbase"
READS = 12  # concurrent inbox reads per OTP_IDX Creator at the flip, alongside its pump's reconnect
WS_WINDOW_S = 20  # flip -> end of phase B, at least: the old reconnect loop's 0, 1, 3, 7, 15 s
# The run that meets OF's 2FA demand logs its OFAPIError (automation_run_failed): expected (under the
# fault; a green run's pump and reads flag first); the scenario's own checks count the runs.
EXPECTED_TRACEBACKS = (("automation_run_failed", "otpState"),
                       # The Creators strip's badge read of a 2FA Creator (the UI's page) logs OF's 101.
                       ("roster-counts: OF read failed", "otpState"))
# Every operator posts its sends at the same instant (--users=200: a 400-request write herd);
# they queue on the relay's DB pool (8 connections): measured p50 588 / p95 842 ms at medium/200
# (20261025T231231Z-...-9276). A herd budget, not a single post's; p95-vs-last-green guards drift.
P95_MS = {"POST /api/of/v2/scheduled-sends": 1500, "GET /admin/accounts": 750,
          "GET /admin/agency-notifications": 500,
          # A pass waits for its runs, and a Creator's DMs are spaced by the executor's own
          # of_write_paced (_OF_WRITE_GAP_S, 11 s, kept real): a pass with a second send is >= 11 s.
          "POST /__slop/automation-tick": 15000}
P95_VS_LAST = (1.5, 150)
VIEWPORT = (1440, 1000)

C_ROW = "account_health flags exactly the 2FA Creators, reason otp_required"
C_NOTE = ("one session_dead notification per owner per 2FA Creator, opening Browserbase login; "
          "no other owner notified")
C_SSE = "each affected owner's /events carried the notification and the pause; no other owner's did"
C_PAUSE = ("after detection a 2FA Creator runs nothing: no run row, no OF call but the probe's /users/me "
           "(101: still paused), its sends stay pending")
C_API = "/admin/accounts shows each owner its 2FA Creators paused (session_dead_reason otp_required)"
C_WS_UP = "phase A: every Creator's WS pump connected through /users/me with the token OF issued"
C_READS = "every concurrent inbox read of a 2FA Creator answered 502 with OF's 400 (upstream_status)"
C_READER = ("a Creator with no automations is flagged by its owner's inbox read alone (via=proxy): "
            "otp_required, one notification")
C_WS = (f"the WS pump met the 2FA demand once and parked: per 2FA Creator at most 2 /users/me over "
        f">= {WS_WINDOW_S} s (the pump's reconnect, the probe's), no reconnect, the pump exited and "
        "supervisor passes left it parked")
C_REC_ROW = "recovery: a re-capture through POST /admin/session/bootstrap clears every flag"
C_REC_SENDS = ("recovery: every parked send of a 2FA Creator reached OF exactly once, in fire-time order, "
               "with its outbound row")
C_REC_NOTE = "recovery: no second session_dead notification"
C_REC_WS = "recovery: each re-captured Creator's pump reconnected (/users/me, then the socket) and is running"
UI_CHECKS = ("UI: the bell's Agency tab lists the 2FA notification as a link to Browserbase login",
             "UI: the row closes the bell and opens Creators with Browserbase login focused; the row is read (API)",
             "UI: the Creator's row shows the 'automations paused' badge naming Browserbase login",
             "no 5xx in the browser session")


def _iso_now(back_s: float = 1.0) -> str:
    t = datetime.now(timezone.utc) - timedelta(seconds=back_s)
    return t.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    cs = w.data["creators"]
    of_sessions.seed(w, cs)
    # Every Creator lost its session once before and recovered (the healthy row
    # phase C leaves): the flip then meets an existing row, which a read-then-write
    # claim lets every simultaneous caller take (a fresh row only collides on the key).
    con = w.sql()
    with con:
        con.executemany("INSERT INTO account_health (account_id) VALUES (?)", [(c["id"],) for c in cs])
    con.close()
    fake = ctx.of_wire
    ids = [c["id"] for c in cs]
    otp = [cs[i]["id"] for i in OTP_IDX]
    owner_of = {c["id"]: c["owner"] for c in cs}
    reader = next(c["id"] for c in cs if c["owner"] == owner_of[otp[1]] and c["id"] not in otp)
    flagged_want = [*otp, reader]
    healthy = [a for a in ids if a not in flagged_want]
    ags = w.data["agencies"]
    by_agency = defaultdict(list)  # the Creators operators schedule for: all but READER
    for c in cs:
        if c["id"] != reader:
            by_agency[c["owner"]].append(c["id"])
    hit_agencies = {owner_of[a] for a in flagged_want}
    ctx.metric("world_otp", {"otp": otp, "reader": reader, "otp_owner": {a: owner_of[a] for a in flagged_want},
                             "creators_per_agency": {a: len(v) for a, v in by_agency.items()},
                             "fake_of": fake.origin})

    pools = {a["user_id"]: a["http"].share(limits=max(10, ctx.users)) for a in ags}
    read_rec = Recorder()  # the 2FA reads' expected 502s (checked below), not the stock no-5xx check's
    readers_http = {a["user_id"]: a["http"].share(rec=read_rec, limits=READS * 4) for a in ags}
    rng = w.rng("session_health_otp")
    plan = []  # (user, agency user id): each operator works one Agency's Creators
    for u in range(ctx.users):
        plan.append((u, ags[u % len(ags)]["user_id"]))
    sched: list[dict] = []
    picks = {u: [] for u, _ in plan}
    per_phase = ctx.param("sends_per_user", 2)
    seat = Counter()
    for u, ag in plan:  # round-robin over the Agency's Creators, so each phase reaches every Creator
        j, mine = seat[ag], by_agency[ag]
        seat[ag] += 1
        for k in range(2 * per_phase):
            aid = mine[(j * per_phase + k % per_phase) % len(mine)]
            fan = rng.choice(w.data["fans"][aid])["id"]
            picks[u].append((aid, fan, f"slop-otp u{u} n{k}"))
    short = {ag: len(v) for ag, v in by_agency.items() if seat[ag] * per_phase < len(v)}
    if short:
        raise SystemExit(f"--users={ctx.users} x sends_per_user={per_phase} does not reach every Creator: {short}")

    async def operator(u: int, ag: str, todo: list) -> None:
        http = pools[ag]
        for aid, fan, text in todo:
            await asyncio.sleep(rng.uniform(0.0, 0.2))
            t0 = time.time()
            r = await http.post("/api/of/v2/scheduled-sends", headers={"X-Account-Id": aid},
                                json={"fan_id": fan, "text": text, "run_at": _iso_now()})
            sched.append({"account_id": aid, "fan_id": fan, "text": text, "status": r.status_code, "t": t0,
                          "t_done": time.time(),
                          "job_id": r.json().get("job_id") if r.status_code == 200 else None})

    lis = {a["user_id"]: SseListener(pools[a["user_id"]], states=("agency_notifications", "session_dead"))
           for a in ags}
    for li in lis.values():
        await li.start()

    stop_readers = asyncio.Event()

    async def owner_reader(ag: str) -> None:
        while not stop_readers.is_set():
            await pools[ag].get("/admin/accounts")
            await pools[ag].get("/admin/agency-notifications?limit=50")
            await asyncio.sleep(rng.uniform(0.5, 1.5))

    ticks: list[dict] = []
    passes: list[dict] = []  # pump-supervisor passes: (t, phase, pump states)

    async def supervise() -> dict:
        b = (await ctx.owner.post("/__slop/pump-supervise")).json()
        passes.append({"t": time.time(), "phase": ctx.rec.stage, "pumps": b["pumps"]})
        return b["pumps"]

    async def tick() -> dict:
        r = await ctx.owner.post("/__slop/automation-tick", timeout=600)
        b = r.json()
        ticks.append({"phase": ctx.rec.stage, **b})
        await supervise()
        return b

    def sql(q: str, args=()) -> list:
        con = w.sql()
        rows = con.execute(q, args).fetchall()
        con.close()
        return rows

    def pending(accounts) -> int:
        return sql("SELECT COUNT(*) FROM scheduled_jobs WHERE kind='scheduled_send' AND status IN "
                   f"('pending','running') AND account_id IN ({','.join('?' * len(accounts))})", accounts)[0][0]

    def flagged_now() -> set:
        return {a for (a,) in sql("SELECT account_id FROM account_health WHERE session_dead_at IS NOT NULL")}

    async def drain(users_done: asyncio.Event, accounts, extra: int = 2) -> None:
        while True:
            await tick()
            if users_done.is_set() and pending(accounts) == 0:
                break
        for _ in range(extra):
            await tick()

    async def wait_for(pred, timeout_s: float) -> bool:
        t_end = time.time() + timeout_s
        while not pred():
            if time.time() > t_end:
                return False
            await asyncio.sleep(0.25)
        return True

    # ── every Creator's pump on OF's socket ───────────────────────────────────
    await supervise()
    up = await wait_for(lambda: {c["account"] for c in fake.ws_connects} >= set(ids), 30)
    with fake.lock:
        conns = list(fake.ws_connects)
    ctx.check(C_WS_UP, up and all(c["token_ok"] for c in conns) and set(fake.ws_live()) >= set(ids),
              connected=len({c["account"] for c in conns}), want=len(ids),
              bad_token=[c["account"] for c in conns if not c["token_ok"]][:5])

    readers = [asyncio.create_task(owner_reader(a["user_id"])) for a in ags]

    # ── Phase A: every login healthy ──────────────────────────────────────────
    ctx.rec.stage = "healthy"
    done_a = asyncio.Event()
    ops = asyncio.gather(*(operator(u, ag, picks[u][:per_phase]) for u, ag in plan))
    drainer = asyncio.create_task(drain(done_a, healthy, extra=0))
    await ops
    done_a.set()
    await drainer
    n_a = len(sched)
    a_snap = fake.snapshot()

    # ── OnlyFans asks for 2FA: OTP_IDX's sockets end, inbox reads meet the 101 at once ──
    flip_t = fake.set_otp(flagged_want)
    flip_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    ctx.rec.stage = "otp"
    reads: list[dict] = []

    async def inbox_read(aid: str, k: int) -> None:
        # Half at the same instant (simultaneous claims), half spread over the pump's 1 s reconnect.
        burst = READS // 2
        await asyncio.sleep(0 if k < burst else 1.5 * (k - burst + 1) / (READS - burst))
        r = await readers_http[owner_of[aid]].get(f"/api/of/v2/chats?limit=10&offset={10 * k}&refresh=1",
                                                   headers={"X-Account-Id": aid})
        detail = r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json") else None
        reads.append({"account": aid, "status": r.status_code,
                      "upstream": detail.get("upstream_status") if isinstance(detail, dict) else None})

    dropped = asyncio.create_task(asyncio.to_thread(fake.drop_ws, otp))
    await asyncio.gather(*(inbox_read(a, k) for a in otp for k in range(READS)), inbox_read(reader, 0))
    dropped = await dropped
    detected = await wait_for(lambda: flagged_now() >= set(flagged_want), 20)
    detected_t = time.time()
    ctx.metric("detection", {"dropped_sockets": dropped, "all_flagged": detected,
                             "s_after_flip": round(detected_t - flip_t, 2)})

    done_b = asyncio.Event()
    ops = asyncio.gather(*(operator(u, ag, picks[u][per_phase:]) for u, ag in plan))
    drainer = asyncio.create_task(drain(done_b, healthy, extra=3))
    await ops
    done_b.set()
    await drainer
    while time.time() - flip_t < WS_WINDOW_S:  # the window the old reconnect loop would fill
        await tick()
        await asyncio.sleep(1)
    end_b = time.time()
    ctx.rec.stage = None
    stop_readers.set()
    await asyncio.gather(*readers)
    await asyncio.sleep(0.5)  # the last SSE frames

    con = w.sql()
    con.row_factory = None
    health = {a: (dead, reason) for a, dead, reason in con.execute(
        "SELECT account_id, session_dead_at, session_dead_reason FROM account_health")}
    notes = con.execute("SELECT agency_user_id, account_id, kind, text, data_json, read_at FROM agency_notifications "
                        "WHERE kind='session_dead' ORDER BY id").fetchall()
    jobs = con.execute("SELECT id, account_id, payload_json, run_at, status, attempts FROM scheduled_jobs "
                       "WHERE kind='scheduled_send' ORDER BY id").fetchall()
    runs = con.execute("SELECT account_id, started_at, status FROM automation_runs WHERE kind='scheduled_send' "
                       "ORDER BY id").fetchall()
    reader_rows = {t: con.execute(f"SELECT COUNT(*) FROM {t} WHERE account_id=?", (reader,)).fetchone()[0]
                   for t in ("scheduled_jobs", "automation_runs")}
    out_rows = {(a, int(m)) for a, m in con.execute(
        "SELECT account_id, message_id FROM messages WHERE direction='out'")}
    con.close()

    def dt(s: str | None) -> datetime | None:
        return datetime.fromisoformat(s) if s else None

    # ── account_health ────────────────────────────────────────────────────────
    flagged = {a: r for a, (d, r) in health.items() if d}
    ctx.check(C_ROW, flagged == {a: "otp_required" for a in flagged_want}, flagged=flagged, want=flagged_want)

    # ── notifications: DB rows, the API each owner reads, the SSE wire ────────
    got = Counter((ag, a) for ag, a, *_ in notes)
    want = Counter((owner_of[a], a) for a in flagged_want)
    bad_data = [{"account": a, "data": d, "text": t} for _ag, a, _k, t, d, _r in notes
                if json.loads(d or "{}") != {"reason": "otp_required", "href": RELINK}
                or "2FA code" not in t or "Browserbase login" not in t]
    api = {}
    for a in ags:
        body = (await pools[a["user_id"]].get("/admin/agency-notifications?limit=200")).json()
        api[a["user_id"]] = sorted(n["account_id"] for n in body["notifications"] if n["kind"] == "session_dead")
    api_ok = all(api[a["user_id"]] == sorted(x for x in flagged_want if owner_of[x] == a["user_id"]) for a in ags)
    ctx.check(C_NOTE, got == want and not bad_data and api_ok, rows=[list(k) + [n] for k, n in got.items()],
              want=[list(k) for k in want], bad=bad_data, api=api, callers_per_creator=READS + 1)
    sse = {ag: {"agency_notifications": [f for t, f, _ in li.state_events if t == "agency_notifications"],
                "session_dead": [(acc, f.get("reason")) for t, f, acc in li.state_events
                                 if t == "session_dead" and f.get("dead")]}
           for ag, li in lis.items()}
    sse_ok = all(
        (bool(sse[ag]["agency_notifications"]) and all(f.get("unread", 0) >= 1 for f in sse[ag]["agency_notifications"])
         and sorted(a for a, _ in sse[ag]["session_dead"]) == sorted(x for x in flagged_want if owner_of[x] == ag)
         and all(r == "otp_required" for _, r in sse[ag]["session_dead"]))
        if ag in hit_agencies else (not sse[ag]["agency_notifications"] and not sse[ag]["session_dead"])
        for ag in lis)
    ctx.check(C_SSE, sse_ok, per_owner={ag: {"agency_notifications": len(v["agency_notifications"]),
                                             "session_dead": v["session_dead"]} for ag, v in sse.items()},
              streams_ended={ag: li.ended for ag, li in lis.items() if li.ended})

    # ── the reads, READER ─────────────────────────────────────────────────────
    bad_reads = [r for r in reads if r["status"] != 502 or r["upstream"] != 400]
    ctx.check(C_READS, len(reads) == READS * len(otp) + 1 and not bad_reads,
              reads=len(reads), statuses=dict(Counter(r["status"] for r in reads)), bad=bad_reads[:5])
    log_text = "\n".join(p.read_text(errors="replace") for p in sorted(ctx.out.glob("relay*.log")))
    via_proxy = f"account_session_dead account={reader} via=proxy" in log_text
    ctx.check(C_READER, flagged.get(reader) == "otp_required" and got[(owner_of[reader], reader)] == 1
              and via_proxy and reader_rows == {"scheduled_jobs": 0, "automation_runs": 0},
              reason=flagged.get(reader), notes=got[(owner_of[reader], reader)], via_proxy_logged=via_proxy,
              automation_rows=reader_rows)

    # ── the WS pump: one reconnect, then parked ───────────────────────────────
    with fake.lock:
        calls = list(fake.calls)
        conns = list(fake.ws_connects)
    ws = {}
    for a in otp:
        me = [c for c in calls if c["account"] == a and c["route"] == "GET /api2/v2/users/me"
              and flip_t <= c["t"] <= end_b]
        # Passes from 5 s after the flip: the pump's own reconnect is due 1 s after its socket ended.
        states = [p["pumps"].get(a) for p in passes if p["t"] >= flip_t + 5]
        ws[a] = {"users_me": dict(Counter(c["status"] for c in me)),
                 "reconnects": sum(1 for c in conns if c["account"] == a and c["t"] >= flip_t),
                 "pump_states_from_flip_plus_5s": dict(Counter(states))}
        ws[a]["ok"] = (1 <= len(me) <= 2 and all(c["status"] == 400 for c in me) and ws[a]["reconnects"] == 0
                       and len(states) >= 2 and set(states) == {"exited"})
    ctx.check(C_WS, all(v["ok"] for v in ws.values()), window_s=round(end_b - flip_t, 1), per_creator=ws)

    # ── the pause ─────────────────────────────────────────────────────────────
    calls_after = defaultdict(Counter)
    for c in calls:
        if c["t"] >= detected_t and c["account"] in otp and c["route"].split(" ")[1].startswith("/api2/"):
            calls_after[c["account"]][f'{c["route"]} {c["status"]}'] += 1
    runs_after = defaultdict(list)
    for a, started, status in runs:
        if a in otp and dt(started) >= flip_utc:
            runs_after[a].append(status)
    pend = Counter(a for _id, a, _p, _r, st, _n in jobs if a in otp and st == "pending")
    made_otp = Counter(s["account_id"] for s in sched if s["account_id"] in otp and s["status"] == 200)
    pause = {}
    for a in otp:
        send_calls = sum(n for k, n in calls_after[a].items() if "/chats/" in k)
        me_400 = calls_after[a].get("GET /api2/v2/users/me 400", 0)
        pause[a] = {"runs_after_flip": runs_after[a], "of_calls_after_detection": dict(calls_after[a]),
                    "jobs_pending": pend[a], "jobs_made": made_otp[a]}
        pause[a]["ok"] = (detected and runs_after[a] == [] and send_calls == 0 and me_400 >= 1
                          and sum(calls_after[a].values()) == me_400
                          and pend[a] == sum(1 for s in sched if s["account_id"] == a and s["t"] >= flip_t
                                             and s["status"] == 200))
    ctx.check(C_PAUSE, all(p["ok"] for p in pause.values()), per_creator=pause)

    # ── healthy Creators: nothing dropped, counts match, order kept ───────────
    texts = {}
    for _id, a, p, run_at, st, _n in jobs:
        texts[(a, json.loads(p)["text"])] = (st, run_at)
    with fake.lock:
        sends = {a: list(v) for a, v in fake.sends.items()}

    done_at = {(s["account_id"], s["text"]): s["t_done"] for s in sched if s["status"] == 200}

    def delivered(accounts, since: float = 0.0) -> dict:
        lost, dup, wrong_order, no_row = [], [], {}, []
        for a in accounts:
            want_t = [s["text"] for s in sched if s["account_id"] == a and s["status"] == 200 and s["t"] >= since]
            got_t = [m["text"].removeprefix("<p>").removesuffix("</p>") for m in sends.get(a, [])]
            lost += [(a, t) for t in want_t if t not in got_t]
            dup += [(a, t) for t, n in Counter(got_t).items() if n > 1]
            # Fire-time order among what was scheduled: a Creator's sends run one at a time (the
            # executor's (account, kind) lock), so send i was claimed after send i-1 reached OF; a
            # send due earlier whose POST had returned by then must not go after it. Operators post
            # while ticks drain, and run_at is the client's clock, so a send committed after a
            # claim may carry an earlier run_at: that is no reordering.
            got = [(texts[(a, m_t)][1], m["t"], done_at.get((a, m_t), float("inf")))
                   for m, m_t in zip(sends.get(a, []), got_t) if (a, m_t) in texts]
            bad = [(got[i][0], got[j][0]) for i in range(1, len(got)) for j in range(i + 1, len(got))
                   if got[j][0] < got[i][0] and got[j][2] <= got[i - 1][1]]
            if bad:
                wrong_order[a] = bad[:6]
            no_row += [(a, m["id"]) for m in sends.get(a, []) if (a, int(m["id"])) not in out_rows]
        return {"lost": lost[:10], "dup": dup[:10], "wrong_order": wrong_order, "no_row": no_row[:10]}

    d = delivered(healthy)
    not_done = [(a, st) for (a, _t), (st, _r) in texts.items() if a in healthy and st != "done"]
    sched_bad = [s for s in sched if s["status"] != 200]
    ctx.check("every healthy Creator's send reached OF once, in fire-time order, with its outbound row "
              "(nothing dropped, counts match)",
              not (any(d.values()) or not_done or sched_bad),
              scheduled=len(sched), healthy_sent=sum(len(sends.get(a, [])) for a in healthy), **d,
              not_done=not_done[:10], schedule_refused=sched_bad[:5])
    untouched = [ag["user_id"] for ag in ags if ag["user_id"] not in hit_agencies]
    per_ag = {ag: {"made": sum(1 for s in sched if owner_of[s["account_id"]] == ag),
                   "sent": sum(len(sends.get(a, [])) for a in by_agency[ag])} for ag in untouched}
    ctx.check("Agencies without a 2FA Creator: every send delivered, no notification, nothing paused",
              all(v["made"] == v["sent"] for v in per_ag.values())
              and not any(ag in untouched for ag, *_ in notes)
              and not any(owner_of[a] in untouched for a in flagged), per_agency=per_ag)
    ctx.check("phase A (before OnlyFans asked for 2FA): every send of every Creator delivered",
              sum(a_snap["sends"].values()) == n_a, sent=sum(a_snap["sends"].values()), scheduled=n_a)

    # ── what the UI reads: /admin/accounts per owner ──────────────────────────
    seen = {}
    for a in ags:
        body = (await pools[a["user_id"]].get("/admin/accounts")).json()
        seen[a["user_id"]] = {x["id"]: x.get("session_dead_reason") for x in body["accounts"]
                              if x.get("session_dead_at")}
    ctx.check(C_API, all(seen[a["user_id"]] == {x: "otp_required" for x in flagged_want
                                                if owner_of[x] == a["user_id"]} for a in ags), per_owner=seen)
    (ctx.out / "api-after.json").write_text(json.dumps({"admin_accounts_dead": seen, "notifications": api,
                                                        "pause": pause, "ws": ws, "reads": reads},
                                                       indent=2, default=str))

    if ctx.app:
        await _ui(ctx, otp, owner_of, w.user_id, {c["id"]: c for c in cs})
    else:
        for n in UI_CHECKS:
            ctx.skip(n, "--no-ui")

    # ── Phase C: OnlyFans takes the logins again; each owner re-captures ──────
    ctx.rec.stage = "recovery"
    n_notes = len(notes)
    fake.set_otp([])
    rec_t = time.time()
    rev = "slop-of-rev-202610261200"
    boot = {}
    for a in flagged_want:
        r = await pools[owner_of[a]].post("/admin/session/bootstrap", timeout=60, json={
            "mode": "paste-curl", "curl": _curl(a, rev), "account_id": a, "make_active": False})
        boot[a] = r.status_code if r.status_code == 200 else f"{r.status_code} {r.text[:200]}"
    cleared = await wait_for(lambda: not (flagged_now() & set(flagged_want)), 20)
    resumed = await wait_for(lambda: {c["account"] for c in fake.ws_connects if c["t"] >= rec_t}
                             >= set(flagged_want), 30)
    done_c = asyncio.Event()
    done_c.set()
    await drain(done_c, otp, extra=1)
    for li in lis.values():
        await li.stop()
    ctx.rec.stage = None
    ctx.check(C_REC_ROW, all(v == 200 for v in boot.values()) and cleared,
              bootstrap=boot, still_flagged=sorted(flagged_now() & set(flagged_want)))
    con = w.sql()
    con.row_factory = None
    jobs = con.execute("SELECT id, account_id, payload_json, run_at, status, attempts FROM scheduled_jobs "
                       "WHERE kind='scheduled_send' ORDER BY id").fetchall()
    out_rows = {(a, int(m)) for a, m in con.execute(
        "SELECT account_id, message_id FROM messages WHERE direction='out'")}
    n_notes_after = con.execute("SELECT COUNT(*) FROM agency_notifications WHERE kind='session_dead'").fetchone()[0]
    con.close()
    texts = {(a, json.loads(p)["text"]): (st, run_at) for _id, a, p, run_at, st, _n in jobs}
    with fake.lock:
        sends = {a: list(v) for a, v in fake.sends.items()}
    d = delivered(otp)
    not_done = [(a, st) for (a, _t), (st, _r) in texts.items() if a in otp and st != "done"]
    ctx.check(C_REC_SENDS, not (any(d.values()) or not_done),
              parked=sum(made_otp.values()), sent={a: len(sends.get(a, [])) for a in otp}, **d,
              not_done=not_done[:10])
    ctx.check(C_REC_NOTE, n_notes_after == n_notes, before=n_notes, after=n_notes_after)
    pumps = (await ctx.owner.get("/__slop/pumps")).json()["pumps"]
    ctx.check(C_REC_WS, resumed and all(pumps.get(a) == "running" for a in flagged_want),
              reconnected=sorted({c["account"] for c in fake.ws_connects if c["t"] >= rec_t} & set(flagged_want)),
              pumps={a: pumps.get(a) for a in flagged_want})
    ctx.check("lib/of_wire.py saw only signed calls it models", fake.unsigned == 0 and not fake.unmodelled,
              unsigned=fake.unsigned, unmodelled=dict(fake.unmodelled))

    # ── budgets ───────────────────────────────────────────────────────────────
    p95s, ns = {}, {}
    for stage in ("healthy", "otp", "recovery"):
        routes = ctx.rec.summary(stage)
        for route, budget in P95_MS.items():
            name = f"p95 {route} < {budget}ms ({stage})"
            if route in routes:
                ctx.check(name, routes[route]["p95_ms"] < budget, budget=True, p95=routes[route]["p95_ms"],
                          n=routes[route]["n"])
                p95s[f"{stage} {route}"], ns[f"{stage} {route}"] = routes[route]["p95_ms"], routes[route]["n"]
            else:
                ctx.skip(name, "no samples")
    ctx.metric("p95_vs_last_green", p95s)
    ctx.metric("p95_vs_last_green_n", ns)
    ctx.metric("ticks", {"n": len(ticks), "phase_a": sum(t["phase"] == "healthy" for t in ticks),
                         "max_ms": max(t["ms"] for t in ticks), "spawned": sum(t["spawned"] for t in ticks)})
    ctx.metric("pump_passes", len(passes))
    ctx.metric("reads", {"n": len(reads), "summary": read_rec.summary()})
    ctx.metric("fake_of", fake.snapshot())
    (ctx.out / "of-wire-calls.json").write_text(json.dumps(fake.calls))
    (ctx.out / "of-ws-connects.json").write_text(json.dumps(fake.ws_connects))


def _curl(uid: str, rev: str) -> str:
    """The Creator's browser's signed /users/me, as DevTools copies it (the login
    extension's x-relay-static-param included), under lib/browserbase.py's
    synthetic signing material (the chunk lib/of_wire.py serves)."""
    s = signing(uid, rev, int(time.time() * 1000))
    h = {"user-id": uid, "x-bc": s["x_bc"], "x-of-rev": rev, "sign": s["sign"], "time": s["time"],
         "user-agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"),
         "accept": "application/json, text/plain, */*",
         "x-relay-static-param": s["rules"]["static_param"]}
    return (f"curl '{s['url']}' " + " ".join(f"-H '{k}: {v}'" for k, v in h.items())
            + f" -b 'auth_id={uid}; sess=slop{uid}recaptured'")


async def _ui(ctx, otp, owner_of, me, by_id) -> None:
    mine = next(a for a in otp if owner_of[a] == me)
    nick = by_id[mine]["nickname"]
    async with ui.owner_browser(ctx, viewport=VIEWPORT) as page:
        step = 0
        try:
            await page.goto(f"{ctx.app}/creators", wait_until="domcontentloaded")
            bell = page.get_by_role("button", name="Notifications")
            await page.get_by_test_id("bell-count").wait_for(timeout=120_000)
            await bell.click()
            tab = page.get_by_role("tab", name="Agency")
            if await tab.count():
                await tab.click()
            link = page.get_by_role("link", name=f"{nick} needs a 2FA code")
            await link.first.wait_for(timeout=60_000)
            href = await link.first.get_attribute("href")
            await page.wait_for_timeout(500)
            trigger = await ui.shot(ctx, page, "trigger-bell-2fa-row")
            ctx.check(UI_CHECKS[0], href == RELINK, href=href, shot=trigger)
            step = 1

            await link.first.click()
            dialog = page.get_by_role("dialog", name="Link creator account")
            await dialog.wait_for(timeout=60_000)
            region = dialog.get_by_role("region", name="Browserbase login")
            await region.wait_for(timeout=30_000)
            await page.wait_for_timeout(300)  # the modal moves focus to the section after it opens
            focused = await region.evaluate("r => r === document.activeElement || r.contains(document.activeElement)")
            bell_closed = await page.get_by_role("tab", name="Agency").count() == 0
            await page.wait_for_timeout(800)
            settled = await ui.shot(ctx, page, "settled-browserbase-login")
            body = (await ctx.owner.get("/admin/agency-notifications?limit=200")).json()
            row = next((n for n in body["notifications"] if n["kind"] == "session_dead" and n["account_id"] == mine),
                       {})
            ctx.check(UI_CHECKS[1], focused and bell_closed and row.get("read") is True and "relink=" not in page.url,
                      focused=focused, bell_closed=bell_closed, row_read=row.get("read"), url=page.url, shot=settled)
            step = 2

            await page.keyboard.press("Escape")
            await dialog.wait_for(state="hidden", timeout=30_000)
            badge = page.get_by_text("automations paused", exact=True)
            await badge.first.wait_for(timeout=60_000)
            title = await badge.first.get_attribute("title")
            n_badges = await badge.count()
            await badge.first.scroll_into_view_if_needed()
            await badge.first.hover()
            await page.wait_for_timeout(800)
            shot = await ui.shot(ctx, page, "settled-creators-badge")
            ctx.check(UI_CHECKS[2], n_badges == 1 and bool(title) and "2FA code" in title
                      and "Browserbase login" in title, badges=n_badges, title=title, shot=shot)
            step = 3
        except Exception as e:  # noqa: BLE001 — a missing row or badge is this step's FAIL, with its picture
            shot = await ui.shot(ctx, page, f"failed-ui-step-{step}")
            for n in UI_CHECKS[step:3]:
                ctx.check(n, False, error=f"{type(e).__name__}: {str(e)[:300]}", shot=shot)
        bad = [u for s, u in page.slop["statuses"] if s >= 500 and "/api/of/" not in u][:10]
        ctx.check(UI_CHECKS[3], not bad, five_xx=bad)
