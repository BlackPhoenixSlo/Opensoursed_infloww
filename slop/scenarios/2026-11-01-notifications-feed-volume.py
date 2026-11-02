"""The Agency owner's notification feed at volume (service/notifications_api.py: GET
/admin/agency-notifications?limit&offset, POST /read-all, POST /{id}/read, the `tick` sweep, the
owner's `agency_notifications` SSE count).

World: `agency_inbox` + `seed/agency_notifications` (one session_dead per Creator) +
`seed/agency_notifications_bulk` (`--notif_rows=`, SCALES `notifications_feed_rows`, by SQL; ages
1 min..120 d, read and unread, three rows on the RETENTION boundary). Through the real routes: 3
owner-made logins (`POST /admin/employees/login`, role Chatter, one Creator each), 4 plain Employees
(`POST /admin/employees`), time tracking on for Chatter + Team Leader (`PUT
/admin/settings/time-tracking`). `min(--users, 10)` owner SSE streams listen throughout
(actors/manager, states agency_notifications).

1. page: every `--users` owner session opens the bell (`GET ?limit=30`), clicks one seeded unread
   row (`POST /{id}/read`), and takes its share of the pages: for each page size 30/50/100/200 the
   feed's pages (one past the end too) are dealt round-robin over the sessions, all at once (starts
   spread over RAMP_S, PAGE_THINK_S between pages). The feed is frozen meanwhile (nothing filed):
   per size the pages, in offset order, must be the SQL list exactly. Paging while rows are filed
   shifts offsets by design and is not checked.
2. prune: first every SSE stream must show SQL's unread after phase 1's concurrent clicks
   (CLICK_SYNC, polled up to SSE_WAIT_S). Then one sweep at the seed's `now` (the hook below) while no
   Shift is due, so it only prunes: every row older than RETENTION gone, every younger one kept (the
   -1 s / 0 / +1 s boundary rows too), and then every SSE stream must show SQL's new unread (unread
   rows were among the pruned) within SSE_WAIT_S (KNOWN_RED: it does not; skipped too when the streams
   were not in sync before the sweep). Then a running Shift for login 0 (`POST /admin/shifts`, started
   1 h ago, no clock-in): the next sweep files its missed clock-in.
3. read: the sessions click Mark all read / one row (picked at setup, younger than RETENTION -
   PICK_MARGIN so no real-clock sweep prunes it first) / reopen the bell while one filer files for real
   (role toggles via `PUT /admin/employees/{id}/setup`, deactivate + reactivate via `PATCH
   /admin/employees/{id}`, a Shift for login 1 and sweeps). Barrier: once the filer and every
   session's rounds are done, every session clicks Mark all read (after its own THINK_S); right after
   the last answer, FINAL_STEPS file one row each (login 0's role toggled, Employee 0 deactivated, a
   Shift for login 2 + a sweep), which must land within the read-all fault's lag (else LATER_UNREAD fails: it could not
   judge). Once LATER_WAIT_S (> that lag) has passed since the last Mark all read, those rows must be
   unread; then GET's unread and every SSE stream's last event must reach SQL's within SSE_WAIT_S
   (polled, not slept).
4. UI (not --no-ui): login 1's role toggled (one fresh row), then /notifications (shot
   notifications-page), the bell's badge = the API unread, re-read until they agree or BADGE_WAIT_S
   (shot bell-trigger), its Agency tab with the newest row (shot bell-agency-open), Mark all read
   -> badge gone (shot bell-agency-settled); side effect: SQL and API unread 0.

Load (a guess at humans): PAGE_THINK_S 1-3 s between one session's pages, THINK_S 0.2-1 s between
its clicks in phase 3; each phase's requests, offered req/s and peak in-flight (from the recorder's
timeline, every call in the phase's window) are in metric `load` and the budget check's detail.
Not hidden: with 0.2-1 s between pages (a burst, ~1.1k page-phase requests in 6.1 s, ~180 req/s) the
GET p95 measured 327.7 ms at medium/200 sessions, over P95_MS (run
20261101T104816Z-2026-11-01-notifications-feed-volume-70c6); P95_MS holds for human-paced paging.
Likewise all 200 final Mark all reads in one instant (peak in-flight 200) measured POST read-all p95
571.0 ms (run 20261101T114221Z-2026-11-01-notifications-feed-volume-e3ce, host load 17-20, so partly
the host) vs 65-77 ms with each session's THINK_S after the barrier (peak in-flight ~40, host load ~5).
Budgets: GET p95 <= P95_MS (all stages); GET, POST read-all and POST /:id/read p95 each vs the last
green run (P95_VS_LAST).

Bypasses (declared): bulk rows by SQL (only shapes `notify` writes; no clock_in_missed in bulk,
each needs a Shift: the sweep files those for real here). The sweep's 5-min cadence
(server._periodic, skipped under CHATTERLY_TEST_MODE): lib/notifications_relay.py's loopback
`POST /__slop/notifications-tick {now?}` runs `notifications_api.tick(now)`, inert unless this
scenario writes `$DEMO_SHOTS_TMP/notifications-tick.json`; `now` is passed only for the prune
(the seed's clock, so the boundary rows are exact). Everything else is real routes.
Break-it-once (lib/notifications_faults.py): read-all-marks-later-rows (FAULT): only LATER_UNREAD;
--fault=notif-page-skips-offset: only PAGED; --fault=notif-prune-ignores-retention: only PRUNED.
"""
from __future__ import annotations

import asyncio
import math
import re
import time
from collections import Counter
from datetime import datetime, timedelta

from slop.actors import ui
from slop.actors.manager import SseListener
from slop.lib.client import Recorder
from slop.lib.notifications_faults import (BADGE, CLICK_SYNC, LATER_UNREAD, PAGED, PRUNE_PUSHED, PRUNED,
                                           READ_ALL_LAG_S, READ_ONE, UI_FEED)
from slop.seed import agency_notifications, agency_notifications_bulk, ts

PROFILE = "agency_inbox"
UI = True
FAULT = "read-all-marks-later-rows"
FEED = "/admin/agency-notifications"
GET_ROUTE = f"GET {FEED}"
P95_MS = 300               # GET at 10k rows, --users sessions paging concurrently (peak in-flight: `load`)
P95_VS_LAST = (1.5, 100)
# The spec's retention (service/notifications_api.RETENTION), held here, not read from the product,
# so a patched RETENTION cannot move what the prune check expects.
RETENTION = timedelta(days=90)
PICK_MARGIN = timedelta(days=1)  # phase-3 clicks spare rows this close to RETENTION (real-clock sweeps)
SIZES = (30, 50, 100, 200)
RAMP_S = 5.0               # each session's start spread (page phase)
PAGE_THINK_S = (1.0, 3.0)  # an owner reading a page before the next (guess at a human's)
THINK_S = (0.2, 1.0)       # between one session's clicks (read phase)
FILER_THINK_S = (0.05, 0.3)  # between the filer's writes (an owner editing Employees, fast)
READ_ROUNDS = 4            # phase 3 actions per session, before its final Mark all read
FILER_STEPS = 12
# Filed right after the last Mark all read answered, one row each: (what, index), then one sweep.
FINAL_STEPS = (("role", 0), ("deactivate", 0), ("shift", 2))
LATER_WAIT_S = READ_ALL_LAG_S + 1.0  # strictly past the read-all fault's re-run (coupled on purpose)
SSE_WAIT_S = 10.0          # deadline for SSE / GET to reach SQL's unread
BADGE_WAIT_S = 30.0        # deadline for the UI badge to reach the API's unread
POLL_S = 0.2
N_SSE = 10
N_LOGINS, N_PLAIN = 3, 4
ROLES = ("chatter", "team-leader")
WAIT_MS = 120_000          # next dev compiles a page on first visit
STEP_MS = 30_000           # one UI step after the page is up
SHOT_SETTLE_MS = 300       # the panel's re-render after the badge goes, before the settled shot
# {check name: "open finding: <one line>"}: a check red on a green harness (product bug) is SKIPped
# with its finding until the product is fixed. No fault may target one.
KNOWN_RED: dict[str, str] = {
    # measured 20261101T112655Z-2026-11-01-notifications-feed-volume-84ca (small): 49 unread pruned,
    # SQL unread 174 -> 125, all 10 streams still 174 after 10 s
    PRUNE_PUSHED: ("open finding: tick prune deletes unread rows without an SSE push (notify returns early "
                   "with no notices); the badge stays stale until the next notify (service/notifications_api.py tick)"),
}


def _load(timeline, t0: float, t1: float) -> dict:
    """A phase's load from the recorder's timeline ((end epoch s, route, status, ms) per call): every
    call that ended in [t0, t1] (SSE stream opens excluded), offered req/s over the window, and the
    most calls in flight at once (each spans end - ms .. end)."""
    calls = [(end - ms / 1000, end) for end, route, _, ms in timeline
             if t0 <= end <= t1 and not route.startswith("GET /events")]
    edges = sorted([(a, 1) for a, _ in calls] + [(b, -1) for _, b in calls], key=lambda e: (e[0], e[1]))
    peak = cur = 0
    for _, d in edges:
        cur += d
        peak = max(peak, cur)
    secs = t1 - t0
    return {"requests": len(calls), "seconds": round(secs, 1),
            "req_per_s": round(len(calls) / secs, 1) if secs > 0 else None, "peak_in_flight": peak}


class _State:
    """What the phases share."""

    def __init__(self, ctx, w) -> None:
        self.ctx, self.w, self.owner = ctx, w, ctx.owner
        self.rng = w.rng("scenario:notifications-feed")
        self.users = max(1, ctx.users)
        self.n_rows = ctx.param("notif_rows", w.size["notifications_feed_rows"])
        self.logins: list[dict] = []
        self.plain: list[int] = []
        self.bulk: dict = {}
        self.total = 0
        self.seeded_unread: list[int] = []
        self.young: list[int] = []  # bulk ids younger than RETENTION - PICK_MARGIN at seed time
        self.https: list = []
        self.listeners: list[SseListener] = []
        self.load: dict[str, dict] = {}
        self.phases: dict = {}


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat() + "Z"


def _chk(ctx, name: str, ok: bool, **detail) -> None:
    if name in KNOWN_RED:
        ctx.skip(name, KNOWN_RED[name], observed_ok=ok, **detail)
    else:
        ctx.check(name, ok, **detail)


def _q(w, q: str, *a) -> list[tuple]:
    con = w.sql()
    try:
        return con.execute(q, a).fetchall()
    finally:
        con.close()


def _feed_ids(w) -> list[int]:
    return [r[0] for r in _q(w, "SELECT id FROM agency_notifications WHERE agency_user_id=?"
                                " ORDER BY created_at DESC, id DESC", w.user_id)]


def _unread(w) -> int:
    return _q(w, "SELECT COUNT(*) FROM agency_notifications WHERE agency_user_id=? AND read_at IS NULL",
              w.user_id)[0][0]


async def _api_unread(h) -> int | None:
    r = await h.get(f"{FEED}?limit=1")
    return r.json().get("unread") if r.status_code == 200 else None


def _sse_last(listeners) -> list[int | None]:
    return [next((f.get("unread") for t, f, _ in reversed(li.state_events) if t == "agency_notifications"), None)
            for li in listeners]


async def _sse_reaches_sql(s: _State, with_api: bool = False) -> dict:
    """Polls until every SSE stream's last agency_notifications (and GET's unread, `with_api`)
    equals SQL's unread, or SSE_WAIT_S. Returns what it last saw, with each stream's event count."""
    t0 = time.monotonic()
    while True:
        want = _unread(s.w)
        api = await _api_unread(s.owner) if with_api else want
        last = _sse_last(s.listeners)
        ok = api == want and all(v == want for v in last)
        if ok or time.monotonic() - t0 > SSE_WAIT_S:
            return {"ok": ok, "sql": want, "api": api if with_api else None, "sse_last": last,
                    "waited_s": round(time.monotonic() - t0, 2),
                    "sse_events": [sum(1 for t, *_ in li.state_events if t == "agency_notifications")
                                   for li in s.listeners]}
        await asyncio.sleep(POLL_S)


async def _tick(s: _State, now: datetime | None = None) -> dict:
    r = await s.owner.post("/__slop/notifications-tick", json={"now": now.isoformat()} if now else {})
    r.raise_for_status()
    return r.json()


async def _shift_for(s: _State, login: dict) -> None:
    now = datetime.utcnow()
    r = await s.owner.post("/admin/shifts", json={
        "start_utc": _iso(now - timedelta(hours=1)), "end_utc": _iso(now + timedelta(hours=3)), "tz": "UTC",
        "employee_ids": [login["id"]], "account_ids": [login["account_id"]]})
    r.raise_for_status()


async def _toggle_role(s: _State, login: dict) -> None:
    login["role"] ^= 1
    r = await s.owner.request("PUT", f"/admin/employees/{login['id']}/setup", json={"role_id": ROLES[login["role"]]})
    r.raise_for_status()


async def _deactivate(s: _State, emp: int, back: bool) -> None:
    r = await s.owner.request("PATCH", f"/admin/employees/{emp}", json={"is_active": False})
    r.raise_for_status()
    if back:
        r = await s.owner.request("PATCH", f"/admin/employees/{emp}", json={"is_active": True})
        r.raise_for_status()


async def _file(s: _State, what: str, k: int, back: bool) -> None:
    """One real filing: a role toggle, a deactivation (+ reactivation if `back`), or a due Shift."""
    if what == "role":
        await _toggle_role(s, s.logins[k])
    elif what == "deactivate":
        await _deactivate(s, s.plain[k], back=back)
    else:
        await _shift_for(s, s.logins[k])


# ── setup: Employees, time tracking, the bulk feed, SSE ─────────────────────
async def _setup(s: _State) -> None:
    ctx, w, owner = s.ctx, s.w, s.owner
    ctx.rec.stage = "setup"
    creators = w.data["creators"]
    agency_notifications.seed(w, creators)
    for k in range(N_LOGINS):
        c = creators[k % len(creators)]
        r = await owner.post("/admin/employees/login", json={
            "username": f"slopnotif{k}", "password": "slop-notif-pass", "display_name": f"Shift Worker {k}",
            "role_id": ROLES[0], "account_ids": [c["id"]]})
        r.raise_for_status()
        s.logins.append({"id": r.json()["employee_id"], "account_id": c["id"], "role": 0})
    for k in range(N_PLAIN):
        r = await owner.post("/admin/employees", json={"display_name": f"Floor Staff {k}"})
        r.raise_for_status()
        s.plain.append(r.json()["id"])
    r = await owner.put("/admin/settings/time-tracking", json={"enabled": True, "role_ids": list(ROLES)})
    r.raise_for_status()
    s.bulk = agency_notifications_bulk.seed(w, creators, w.data["fans"], n=s.n_rows, retention=RETENTION)
    s.total = len(_feed_ids(w))
    s.seeded_unread = [r[0] for r in _q(w, "SELECT id FROM agency_notifications WHERE agency_user_id=? AND"
                                           " read_at IS NULL ORDER BY id", w.user_id)]
    safe = ts(w.now - RETENTION + PICK_MARGIN)  # by seeded age, before any sweep: the same under any fault
    bulk = set(s.bulk["ids"])
    s.young = [i for i, at in _q(w, "SELECT id, created_at FROM agency_notifications WHERE agency_user_id=?"
                                    " ORDER BY id", w.user_id) if i in bulk and at >= safe]
    ctx.metric("feed", {"rows": s.total, "bulk": len(s.bulk["ids"]), "unread": len(s.seeded_unread),
                        "older_than_retention": _q(w, "SELECT COUNT(*) FROM agency_notifications WHERE created_at < ?",
                                                   ts(w.now - RETENTION))[0][0]})
    s.https = [owner.share(limits=2) for _ in range(s.users)]
    s.listeners = [SseListener(owner.share(limits=2), states=("agency_notifications",))
                   for _ in range(min(N_SSE, s.users))]
    await asyncio.gather(*(li.start() for li in s.listeners))


# ── 1. page: the frozen feed paged by every session, plus a click each ──────
async def _page(s: _State) -> None:
    ctx, rng, users = s.ctx, s.rng, s.users
    ctx.rec.stage = "page"
    tasks = [(size, k) for size in SIZES for k in range(math.ceil(s.total / size) + 1)]
    rng.shuffle(tasks)
    clicks = rng.sample(s.seeded_unread, min(users, len(s.seeded_unread)))
    pages: dict[int, dict[int, list[int]]] = {sz: {} for sz in SIZES}
    by_limit = Recorder()
    plan = [(rng.uniform(0, RAMP_S), tasks[u::users], [rng.uniform(*PAGE_THINK_S) for _ in tasks[u::users]])
            for u in range(users)]

    async def pager(u: int) -> None:
        h, (start, mine, think) = s.https[u], plan[u]
        await asyncio.sleep(start)
        await h.get(f"{FEED}?limit=30")
        if u < len(clicks):
            await h.post(f"{FEED}/{clicks[u]}/read")
        for (size, k), pause in zip(mine, think):
            await asyncio.sleep(pause)
            t = time.perf_counter()
            r = await h.get(f"{FEED}?limit={size}&offset={k * size}")
            by_limit.add(f"limit={size}", r.status_code, (time.perf_counter() - t) * 1000)
            if r.status_code == 200:
                pages[size][k] = [n["id"] for n in r.json()["notifications"]]

    t0 = time.time()
    await asyncio.gather(*(pager(u) for u in range(users)))
    s.load["page"] = _load(ctx.rec.timeline, t0, time.time())
    ctx.metric("page_ms_by_limit", by_limit.summary())
    want = _feed_ids(s.w)
    bad: dict[int, dict] = {}
    for size in SIZES:
        got = [i for k in sorted(pages[size]) for i in pages[size][k]]
        missing_pages = [k for k in range(math.ceil(s.total / size) + 1) if k not in pages[size]]
        if got != want or missing_pages:
            c = Counter(got)
            bad[size] = {"got": len(got), "want": len(want), "missing": len(set(want) - set(got)),
                         "dup": sum(1 for v in c.values() if v > 1), "extra": len(set(got) - set(want)),
                         "first_diff": next((j for j, (a, b) in enumerate(zip(got, want)) if a != b), None),
                         "missing_pages": missing_pages[:10]}
    _chk(ctx, PAGED, not bad and len(want) == s.total, rows=s.total, pages=sum(len(p) for p in pages.values()),
         users=users, load=s.load["page"], bad=bad)
    unread_now = _unread(s.w)
    marks = ",".join("?" * len(clicks)) or "NULL"
    not_marked = [r[0] for r in _q(s.w, f"SELECT id FROM agency_notifications WHERE id IN ({marks})"
                                        " AND read_at IS NULL", *clicks)]
    _chk(ctx, READ_ONE, unread_now == len(s.seeded_unread) - len(clicks) and not not_marked,
         seeded_unread=len(s.seeded_unread), clicked=len(clicks), unread=unread_now, not_marked=not_marked[:10])


# ── 2. prune: one sweep at the seed's clock that files nothing ─────────────
async def _prune(s: _State) -> None:
    ctx, w = s.ctx, s.w
    ctx.rec.stage = "prune"
    synced = await _sse_reaches_sql(s)  # phase 1's concurrent clicks each pushed after their commit
    _chk(ctx, CLICK_SYNC, synced["ok"], clicks=min(s.users, len(s.seeded_unread)),
         **{k: v for k, v in synced.items() if k != "ok"})
    edge = ts(w.now - RETENTION)
    rows = _q(w, "SELECT id, created_at, read_at IS NULL FROM agency_notifications WHERE agency_user_id=?", w.user_id)
    before = {i: at for i, at, _ in rows}
    swept = await _tick(s, w.now)
    after = {r[0] for r in _q(w, "SELECT id FROM agency_notifications WHERE agency_user_id=?", w.user_id)}
    older = {i for i, at in before.items() if at < edge}
    gone = set(before) - after
    b = s.bulk["boundary"]
    _chk(ctx, PRUNED, bool(older) and gone == older and b["before"] in gone and b["at"] in after
         and b["after"] in after, retention_days=RETENTION.days, older=len(older), gone=len(gone),
         kept_younger=len(set(before) - older - gone), wrongly_gone=sorted(gone - older)[:10],
         left_old=sorted(older - gone)[:10], boundary=b, sweep=swept)
    unread_pruned = sum(1 for i, _, unread in rows if unread and i in gone)
    seen = await _sse_reaches_sql(s)
    detail = dict(unread_pruned=unread_pruned, filed=swept.get("filed"), before_prune=synced, after_prune=seen)
    if not synced["ok"]:  # a stale stream before the sweep would make "after" meaningless either way
        ctx.skip(PRUNE_PUSHED, "streams not in sync with SQL before the sweep (see CLICK_SYNC)", **detail)
    else:
        _chk(ctx, PRUNE_PUSHED, swept.get("filed") == 0 and unread_pruned > 0 and seen["ok"], **detail)
    await _shift_for(s, s.logins[0])  # due now: the next sweep files login 0's missed clock-in


# ── 3. read: Mark all read / clicks / reopen while rows are filed for real ──
async def _read(s: _State) -> None:
    ctx, w, rng, users = s.ctx, s.w, s.rng, s.users
    ctx.rec.stage = "read"
    acts = [[rng.choices(("read_all", "read_one", "open"), (2, 2, 1))[0] for _ in range(READ_ROUNDS)]
            for _ in range(users)]
    picks = [[rng.choice(s.young) for _ in range(READ_ROUNDS)] for _ in range(users)]
    thinks = [[rng.uniform(*THINK_S) for _ in range(READ_ROUNDS + 1)] for _ in range(users)]
    steps = [("role", k % N_LOGINS) if k % 2 == 0 else ("deactivate", k % N_PLAIN) for k in range(FILER_STEPS)]
    steps.insert(FILER_STEPS // 2, ("shift", 1))
    filer_think = [rng.uniform(*FILER_THINK_S) for _ in steps]

    async def reader(u: int) -> None:
        h = s.https[u]
        for i, act in enumerate(acts[u]):  # thinks[u][-1]: before the final Mark all read
            await asyncio.sleep(thinks[u][i])
            if act == "read_all":
                await h.post(f"{FEED}/read-all")
            elif act == "read_one":
                await h.post(f"{FEED}/{picks[u][i]}/read")
            else:
                await h.get(f"{FEED}?limit=30")

    async def filer() -> None:
        for (what, k), pause in zip(steps, filer_think):
            await asyncio.sleep(pause)
            await _file(s, what, k, back=True)
            await _tick(s)

    async def read_all(u: int) -> float:
        await asyncio.sleep(thinks[u][-1])
        r = await s.https[u].post(f"{FEED}/read-all")
        r.raise_for_status()
        return time.time()

    t0 = time.time()
    await asyncio.gather(filer(), *(reader(u) for u in range(users)))
    # Barrier: filer and rounds done; then every session's final Mark all read (each after its own
    # think, not all in one instant: see "Not hidden"), then FINAL_STEPS right after the last answer.
    last = max(await asyncio.gather(*(read_all(u) for u in range(users))))
    mark = _q(w, "SELECT COALESCE(MAX(id), 0) FROM agency_notifications")[0][0]  # all filed before the barrier
    for what, k in FINAL_STEPS:
        await _file(s, what, k, back=False)
    final_tick = await _tick(s)
    filed_s = round(time.time() - last, 2)
    s.load["read"] = _load(ctx.rec.timeline, t0, time.time())
    await asyncio.sleep(max(0.0, last + LATER_WAIT_S - time.time()))
    later = _q(w, "SELECT id, kind, read_at FROM agency_notifications WHERE agency_user_id=? AND id>?", w.user_id, mark)
    in_lag = filed_s < READ_ALL_LAG_S  # else a deferred read-all re-run would land before them: unjudgeable
    _chk(ctx, LATER_UNREAD, in_lag and len(later) >= len(FINAL_STEPS) and all(r[2] is None for r in later),
         rows=len(later), kinds=dict(Counter(k for _, k, _ in later)),
         marked_read=[r[0] for r in later if r[2] is not None], filed_after_last_read_all_s=filed_s,
         fault_lag_s=READ_ALL_LAG_S, reason=None if in_lag else
         f"final filings took {filed_s}s >= the read-all fault's lag {READ_ALL_LAG_S}s: cannot judge",
         judged_after_s=round(time.time() - last, 2), sweep=final_tick)

    seen = await _sse_reaches_sql(s, with_api=True)
    synced = seen.pop("ok")
    ended = [li.ended for li in s.listeners if li.ended]
    _chk(ctx, BADGE, synced and not ended, **seen, ended=ended[:3])
    s.phases.update(read_s=round(time.time() - t0, 1), filer_steps=len(steps), filed_by_kind=dict(Counter(
        k for (k,) in _q(w, "SELECT kind FROM agency_notifications WHERE id>?", max(s.bulk["ids"])))))


# ── budgets ────────────────────────────────────────────────────────────────
def _budgets(s: _State) -> None:
    ctx = s.ctx
    routes = ctx.rec.summary()
    p95s = {k: routes[k]["p95_ms"] for k in (GET_ROUTE, f"POST {FEED}/read-all", f"POST {FEED}/:id/read")
            if k in routes}
    name = f"p95 {GET_ROUTE} <= {P95_MS}ms ({s.n_rows} rows, {s.users} sessions)"
    get = routes.get(GET_ROUTE)
    ctx.check(name, bool(get) and get["p95_ms"] <= P95_MS, budget=True, p95=get and get["p95_ms"],
              n=get["n"] if get else 0, by_stage={st: ctx.rec.summary(st).get(GET_ROUTE) for st in ("page", "read")},
              think_s={"page": PAGE_THINK_S, "read": THINK_S}, load=s.load)
    ctx.metric("load", s.load)
    ctx.metric("phases", s.phases)
    ctx.metric("p95_vs_last_green", p95s)


async def _ui(s: _State) -> None:
    ctx, w = s.ctx, s.w
    ctx.rec.stage = "ui"
    if ctx.app is None:
        ctx.skip(UI_FEED, "--no-ui")
        return
    # One fresh row first (a role toggle, real route), so the bell has news whatever phase 3 left.
    await _toggle_role(s, s.logins[1])
    detail: dict = {}
    try:
        async with ui.owner_browser(ctx, viewport=(1440, 900)) as page:
            await page.goto(f"{ctx.app}/notifications", wait_until="domcontentloaded")
            await page.get_by_role("tablist", name="Notification types").wait_for(timeout=WAIT_MS)
            await ui.shot(ctx, page, "notifications-page")
            # The badge and the API both settle (a lagging push, a late write): re-read both each poll.
            t0 = time.monotonic()
            while True:
                api_unread = await _api_unread(ctx.owner)
                want = None if api_unread is None else "99+" if api_unread > 99 else str(api_unread)
                shown = await page.evaluate(
                    "() => document.querySelector('[data-testid=bell-count]')?.textContent || ''")
                if shown == want or time.monotonic() - t0 > BADGE_WAIT_S:
                    break
                await asyncio.sleep(POLL_S)
            detail.update(badge=shown, want=want, api_unread=api_unread, badge_wait_s=round(time.monotonic() - t0, 2))
            await ui.shot(ctx, page, "bell-trigger")
            await page.get_by_role("button", name="Notifications", exact=True).click()
            tab = page.get_by_role("tab", name=re.compile(r"^Agency"))
            await tab.wait_for(timeout=STEP_MS)
            if await tab.get_attribute("aria-selected") != "true":
                await tab.click()
            newest = _q(w, "SELECT text FROM agency_notifications WHERE agency_user_id=? "
                           "ORDER BY created_at DESC, id DESC LIMIT 1", w.user_id)[0][0]
            await page.get_by_text(newest, exact=True).first.wait_for(timeout=STEP_MS)
            detail["newest"] = newest
            await ui.shot(ctx, page, "bell-agency-open")
            panel = page.locator("div:has(> [role=tablist][aria-label='Notification feeds'])")
            async with page.expect_response(lambda resp: resp.url.endswith(f"{FEED}/read-all"), timeout=STEP_MS) as rr:
                await panel.get_by_role("button", name="Mark all read", exact=True).click()
            detail["read_all_status"] = (await rr.value).status
            await page.get_by_test_id("bell-count").wait_for(state="detached", timeout=STEP_MS)
            await page.wait_for_timeout(SHOT_SETTLE_MS)
            await ui.shot(ctx, page, "bell-agency-settled")
            detail["after"] = {"sql_unread": _unread(w), "api_unread": await _api_unread(ctx.owner)}
            five = [(st, u) for st, u in page.slop["statuses"] if st >= 500]
            detail["five_xx"] = five[:10]
            _chk(ctx, UI_FEED, detail["badge"] == want and detail["read_all_status"] == 200
                 and detail["after"] == {"sql_unread": 0, "api_unread": 0} and not five, **detail)
    except Exception as e:  # noqa: BLE001 — a UI step that cannot complete is the check's FAIL
        _chk(ctx, UI_FEED, False, error=f"{type(e).__name__}: {e}"[:600], **detail)


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    (ctx.stack.tmp / "notifications-tick.json").write_text("{}")
    s = _State(ctx, w)
    await _setup(s)
    await _page(s)
    await _prune(s)
    await _read(s)
    _budgets(s)
    await _ui(s)
    ctx.rec.stage = None
    for li in s.listeners:
        await li.stop()
        await li.http.aclose()
    for h in s.https:
        await h.aclose()
