from __future__ import annotations

import asyncio
import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from slop.actors import ui
from slop.actors.manager import SseListener
from slop.lib.browserbase import paste_curl
from slop.lib.client import Recorder
from slop.lib.egress_faults import RESET_AFTER_S, WS_GAP, WS_GAP_MAX_S
from slop.lib.pump_faults import (BACKOFF_SLACK_S, BACKOFF_WANT_S, BACKOFF_WINDOW_S, PROBE_RESTART,
                                  PUMP_BACKOFF, PUMP_STOP, WS_EXIT_SLACK_S, WS_ME_MAX, WS_PARKED,
                                  WS_RETRIES, WS_RETRY_GAPS_S, WS_RETRY_SLACK_S, WS_WINDOW_S)
from slop.seed import of_sessions

PROFILE = "multi_agency_big_models"
UI = True
OF_WIRE = True
FAULT = "otp-state-not-session-dead"
OTP_IDX = (3, 5, 9)
RELINK = "/creators?relink=browserbase"
READS = 12
RACE_IDX = 1
SIGNED_SLOTS = 8
RACE_HOLD_S = (0.4,) + (1.4,) * (SIGNED_SLOTS - 1)
RELAY_ENV = {"ACCOUNT_LANE_TOTAL": str(READS)}
WS_GAP_IDX = 2
GAP_DROPS = 3
UP_MARGIN_S = 5.0
EXPECTED_TRACEBACKS = (("automation_run_failed", "otpState"),
                       ("roster-counts: OF read failed", "otpState"))
# 200 operators post at once and queue on the relay's 8-connection DB pool: measured p50 588 / p95 842 ms at medium/200
P95_MS = {"POST /api/of/v2/scheduled-sends": 1500, "GET /admin/accounts": 750,
          "GET /admin/agency-notifications": 500,
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
C_RACE = (f"the reads met an evicted client: a 2FA Creator's reads waited on its {SIGNED_SLOTS} signed slots "
          "and at least one was refused as retired (relay log type=OFSessionRetired)")
C_READER = ("a Creator with no automations is flagged by its owner's inbox read alone (via=proxy): "
            "otp_required, one notification")
C_WS = WS_PARKED
C_WS_RETRY = WS_RETRIES
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
    by_agency = defaultdict(list)
    for c in cs:
        if c["id"] != reader:
            by_agency[c["owner"]].append(c["id"])
    hit_agencies = {owner_of[a] for a in flagged_want}
    ctx.metric("world_otp", {"otp": otp, "reader": reader, "otp_owner": {a: owner_of[a] for a in flagged_want},
                             "creators_per_agency": {a: len(v) for a, v in by_agency.items()},
                             "fake_of": fake.origin})

    pools = {a["user_id"]: a["http"].share(limits=max(10, ctx.users)) for a in ags}
    read_rec = Recorder()
    readers_http = {a["user_id"]: a["http"].share(rec=read_rec, limits=READS * 4) for a in ags}
    rng = w.rng("session_health_otp")
    plan = []
    for u in range(ctx.users):
        plan.append((u, ags[u % len(ags)]["user_id"]))
    sched: list[dict] = []
    picks = {u: [] for u, _ in plan}
    per_phase = ctx.param("sends_per_user", 2)
    seat = Counter()
    for u, ag in plan:
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
    passes: list[dict] = []

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

    await supervise()
    up = await wait_for(lambda: {c["account"] for c in fake.ws_connects} >= set(ids), 30)
    with fake.lock:
        conns = list(fake.ws_connects)
    ctx.check(C_WS_UP, up and all(c["token_ok"] for c in conns) and set(fake.ws_live()) >= set(ids),
              connected=len({c["account"] for c in conns}), want=len(ids),
              bad_token=[c["account"] for c in conns if not c["token_ok"]][:5])

    readers = [asyncio.create_task(owner_reader(a["user_id"])) for a in ags]
    ws_gap = asyncio.create_task(_ws_gap(fake, healthy[WS_GAP_IDX]))

    ctx.rec.stage = "healthy"
    done_a = asyncio.Event()
    ops = asyncio.gather(*(operator(u, ag, picks[u][:per_phase]) for u, ag in plan))
    drainer = asyncio.create_task(drain(done_a, healthy, extra=0))
    await ops
    done_a.set()
    await drainer
    n_a = len(sched)
    a_snap = fake.snapshot()

    race = otp[RACE_IDX]
    race_key = (race, "GET /api2/v2/chats")
    with fake.lock:
        fake.hold[race_key] = list(RACE_HOLD_S)
    flip_t = fake.set_otp(flagged_want)
    flip_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    ctx.rec.stage = "otp"
    reads: list[dict] = []

    async def inbox_read(aid: str, k: int) -> None:
        burst = READS if aid == race else READS // 2
        await asyncio.sleep(0 if k < burst else 1.5 * (k - burst + 1) / (READS - burst))
        r = await readers_http[owner_of[aid]].get(f"/api/of/v2/chats?limit=10&offset={10 * k}&refresh=1",
                                                   headers={"X-Account-Id": aid})
        detail = r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json") else None
        reads.append({"account": aid, "status": r.status_code,
                      "upstream": detail.get("upstream_status") if isinstance(detail, dict) else None})

    dropped = asyncio.create_task(asyncio.to_thread(fake.drop_ws, otp))
    await asyncio.gather(*(inbox_read(a, k) for a in otp for k in range(READS)), inbox_read(reader, 0))
    with fake.lock:
        unheld = fake.hold.pop(race_key, [])
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
    while time.time() - flip_t < WS_WINDOW_S:
        await tick()
        await asyncio.sleep(1)
    end_b = time.time()
    ctx.rec.stage = None
    stop_readers.set()
    await asyncio.gather(*readers)
    await asyncio.sleep(0.5)

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

    flagged = {a: r for a, (d, r) in health.items() if d}
    ctx.check(C_ROW, flagged == {a: "otp_required" for a in flagged_want}, flagged=flagged, want=flagged_want)

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

    log_text = "\n".join(p.read_text(errors="replace") for p in sorted(ctx.out.glob("relay*.log")))
    retired = sum(1 for ln in log_text.splitlines() if f"http_error account={race} " in ln
                  and "url=/api2/v2/chats type=OFSessionRetired" in ln)
    reruns = log_text.count(f"client evicted mid-read account={race}:")
    bad_reads = [r for r in reads if r["status"] != 502 or r["upstream"] != 400]
    ctx.check(C_READS, len(reads) == READS * len(otp) + 1 and not bad_reads,
              reads=len(reads), statuses=dict(Counter(r["status"] for r in reads)), bad=bad_reads[:5],
              race_retired=retired, race_reruns=reruns)
    ctx.check(C_RACE, retired >= 1, creator=race, held_s=RACE_HOLD_S, unheld=unheld, retired=retired,
              reruns=reruns)
    via_proxy = f"account_session_dead account={reader} via=proxy" in log_text
    ctx.check(C_READER, flagged.get(reader) == "otp_required" and got[(owner_of[reader], reader)] == 1
              and via_proxy and reader_rows == {"scheduled_jobs": 0, "automation_runs": 0},
              reason=flagged.get(reader), notes=got[(owner_of[reader], reader)], via_proxy_logged=via_proxy,
              automation_rows=reader_rows)

    with fake.lock:
        calls = list(fake.calls)
        conns = list(fake.ws_connects)
    ws = {}
    for a in otp:
        me = [c for c in calls if c["account"] == a and c["route"] == "GET /api2/v2/users/me"
              and flip_t <= c["t"] <= end_b]
        picked = me[:1]
        for gap in WS_RETRY_GAPS_S:
            nxt = next((c for c in me if c["t"] - picked[-1]["t"] >= gap - WS_RETRY_SLACK_S), None) if picked else None
            if nxt is None:
                break
            picked.append(nxt)
        exit_t = (picked[-1]["t"] if picked else flip_t) + WS_EXIT_SLACK_S
        states = [p["pumps"].get(a) for p in passes if p["t"] >= exit_t]
        ws[a] = {"users_me": dict(Counter(c["status"] for c in me)),
                 "users_me_s_after_flip": [round(c["t"] - flip_t, 1) for c in me],
                 "reconnects": sum(1 for c in conns if c["account"] == a and c["t"] >= flip_t),
                 "pump_exit_due_s_after_flip": round(exit_t - flip_t, 1),
                 "pump_states_from_exit_due": dict(Counter(states))}
        ws[a]["ok"] = (len(me) <= WS_ME_MAX and all(c["status"] == 400 for c in me) and ws[a]["reconnects"] == 0
                       and len(states) >= 2 and set(states) == {"exited"})
        ws[a]["retries_ok"] = len(picked) == 1 + len(WS_RETRY_GAPS_S)
    ctx.check(C_WS, all(v["ok"] for v in ws.values()), window_s=round(end_b - flip_t, 1), per_creator=ws)
    ctx.check(C_WS_RETRY, all(v["retries_ok"] for v in ws.values()),
              per_creator={a: v["users_me_s_after_flip"] for a, v in ws.items()})

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

    ctx.rec.stage = "recovery"
    n_notes = len(notes)
    fake.set_otp([])
    rec_t = time.time()
    rev = "slop-of-rev-202610261200"
    boot = {}
    for a in flagged_want:
        r = await pools[owner_of[a]].post("/admin/session/bootstrap", timeout=60, json={
            "mode": "paste-curl", "curl": paste_curl(a, rev), "account_id": a, "make_active": False})
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

    probe_a = healthy[0]
    fake.set_otp([probe_a])
    await asyncio.to_thread(fake.drop_ws, [probe_a])

    async def pump_state() -> str | None:
        return (await ctx.owner.get("/__slop/pumps")).json()["pumps"].get(probe_a)

    t_end, state_d = time.time() + 20, None
    while time.time() < t_end and not (probe_a in flagged_now() and (state_d := await pump_state()) == "exited"):
        await asyncio.sleep(0.25)
    parked_d = probe_a in flagged_now() and state_d == "exited"
    fake.set_otp([])
    clear_t = time.time()
    await tick()
    cleared_d = probe_a not in flagged_now()
    after_d = passes[-1]["pumps"].get(probe_a)
    back_d = await wait_for(lambda: any(c["account"] == probe_a and c["t"] >= clear_t
                                        for c in fake.ws_connects), 10)
    ctx.check(PROBE_RESTART, parked_d and cleared_d and after_d == "running" and back_d,
              creator=probe_a, flagged_and_exited=parked_d, cleared_by_probe=cleared_d,
              pump_after_pass=after_d, socket_reconnected=back_d)
    await _phase_e_stop(ctx, w, fake, healthy[1], supervise, wait_for)
    await _phase_e_backoff(ctx, healthy[1], supervise)
    g = await ws_gap
    ctx.check(WS_GAP, len(g["early_gaps_s"]) == GAP_DROPS and None not in g["early_gaps_s"]
              and g["early_gaps_s"][-1] >= 3.0 and g["reconnects_while_up"] == 0
              and (g["up_s"] or 0) >= RESET_AFTER_S and g["gap_s"] is not None and g["gap_s"] <= WS_GAP_MAX_S,
              **g, reset_after_s=RESET_AFTER_S, max_gap_s=WS_GAP_MAX_S)
    ctx.check("lib/of_wire.py saw only signed calls it models", fake.unsigned == 0 and not fake.unmodelled,
              unsigned=fake.unsigned, unmodelled=dict(fake.unmodelled))

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


async def _ws_gap(fake, aid: str) -> dict:
    async def reconnect(after: float, timeout_s: float = 40.0) -> float | None:
        t_end = time.time() + timeout_s
        while time.time() < t_end:
            with fake.lock:
                t = next((c["t"] for c in fake.ws_connects if c["account"] == aid and c["t"] > after), None)
            if t is not None:
                return t
            await asyncio.sleep(0.05)
        return None

    out = {"creator": aid, "early_gaps_s": [], "up_s": None, "reconnects_while_up": None, "gap_s": None}
    up_at = None
    for _ in range(GAP_DROPS):
        t0 = time.time()
        await asyncio.to_thread(fake.drop_ws, [aid])
        up_at = await reconnect(t0)
        out["early_gaps_s"].append(round(up_at - t0, 2) if up_at else None)
        if up_at is None:
            return out
    await asyncio.sleep(max(0.0, up_at + RESET_AFTER_S + UP_MARGIN_S - time.time()))
    t0 = time.time()
    with fake.lock:
        out["reconnects_while_up"] = sum(1 for c in fake.ws_connects if c["account"] == aid and c["t"] > up_at)
    out["up_s"] = round(t0 - up_at, 1)
    await asyncio.to_thread(fake.drop_ws, [aid])
    t = await reconnect(t0)
    out["gap_s"] = round(t - t0, 2) if t else None
    return out


async def _phase_e_stop(ctx, w, fake, aid: str, supervise, wait_for) -> None:
    latest = w.sessions / "accounts" / aid / "latest.json"
    lost = latest.with_name("latest.json.slop-lost")
    before = (await ctx.owner.get("/__slop/pumps")).json()["pumps"].get(aid)
    live_before = aid in fake.ws_live()
    latest.rename(lost)
    try:
        after = (await supervise()).get(aid)
        closed = await wait_for(lambda: aid not in fake.ws_live(), 10)
    finally:
        lost.rename(latest)
    ctx.check(PUMP_STOP, before == "running" and live_before and after is None and closed,
              creator=aid, pump_before=before, socket_before=live_before, pump_after_pass=after,
              socket_closed=closed)


async def _phase_e_backoff(ctx, aid: str, supervise) -> None:
    await ctx.owner.post("/__slop/pump-crash", json={"account_ids": [aid]})
    try:
        t_end = time.time() + BACKOFF_WINDOW_S
        while time.time() < t_end:
            await supervise()
            await asyncio.sleep(1)
        starts = (await ctx.owner.get("/__slop/pump-crash")).json()["starts"].get(aid, [])
    finally:
        await ctx.owner.post("/__slop/pump-crash", json={"account_ids": []})
    gaps = [round(b - a, 2) for a, b in zip(starts, starts[1:])]
    off = [(k, g, d) for k, (g, d) in enumerate(zip(gaps, BACKOFF_WANT_S)) if not d - 0.5 <= g <= d + BACKOFF_SLACK_S]
    ctx.check(PUMP_BACKOFF, len(gaps) == len(BACKOFF_WANT_S) and not off, creator=aid, starts=len(starts),
              gaps_s=gaps[:30], want_s=BACKOFF_WANT_S, off=off[:10])


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
            await page.wait_for_timeout(300)
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
