"""Shift schedule + Clock under a crowd (service/shifts_api.py, service/clock_api.py, service/shift_time.py,
service/shifts_timesheet.py): one Agency (`agency_inbox`: 3 Creators small, 10 medium), `employees` chatter
logins (50 small, 200 medium; `seed/chatters`: the real invite + register, each allowed one Creator,
round-robin), 30 days of Shift history and Clock events (`seed/shift_history`: weekly series, "This shift"
deletes, a DST night inside the anchored window [2026-10-02, 2026-11-01) UTC, a few chatters still clocked
in across its end). Time tracking on through the real `PUT /admin/settings/time-tracking` (roles chatter +
owner, auto clock-out 999 min so no live event is swept mid-run).

Phase A, at once: `race_rounds` rounds of `race_n` concurrent `POST /admin/shifts` on one Creator's free
slot (Sunday 20:00-24:00 local, a future week; a different Employee each), and the clock-in storm: every
actor chatter (`--users`, those not clocked in by the seed) signs in (`POST /chatter/login`, own cookie) and
fires `storm` concurrent `POST /admin/shifts/clock-in` (actors/clock.py).
Phase B, at once: the chatters' day (clock-status, heartbeats, clock-out, clock-in, heartbeats, clock-out;
human-paced), `readers` owner pools reading the Timesheet (group=employee and account, the 30-day window),
the week list (30 days and this week) and `GET /admin/stats/chatting-stats`, and the owner's writes: PATCH
scope=all on a Shift it creates on a slot no race touched (one per Creator), and on seeded series PATCH scope=this / following and
`/cancel` scope=this / following, each on a future occurrence the seed's own expansion names.

Checks: the race (exactly one 2xx per round, the rest 409, one Shift row on the slot); one open clock event
per storm chatter (one 2xx clock-in each); the Timesheet per Employee and per Creator over the window ==
the oracle (`seed/shift_history.occurrences`: the Occurrence rule written from the spec with zoneinfo,
wall-clock length kept across the Berlin fall-back, and the Agency-wide clock's per-Creator spans), the week
list over the window == the oracle's occurrences, the fall-back night's 5 h long; every owner write 2xx and the
week list shows it (each Creator's solo create in its first race-free week: `race_rounds` is capped at
SOLO_WEEKS per Creator so that week is inside the list's read); one
`actions` row (shift.create|edit|cancel, clock.in|out) per 2xx write and none for a refused one; budgets
p95 Timesheet <= 1 s and heartbeat <= 200 ms; p95 vs the last green run. With UI: /employees/shifts and
/analytics/employee-reports (trigger + settled screenshots), each settled page naming an Employee the API
lists for it.

Bypasses (declared): history (Shifts, assignments, Clock events and their `actions` rows) is SQL-seeded,
written as the routes would; the live writes all go through the real routes. The window is fixed in the
past, so the history's numbers never depend on the run's date. The seed's still-open events keep a
heartbeat of "when seeded" (auto clock-out 999 min keeps them open). Chatters reach the relay directly
(no Next proxy). The clock-in storm is k identical requests per chatter at once (a double-click / two
tabs). Owners' reads run in closed loops with 0.3-1 s think time.

Faults (lib/shifts_faults.py): `shift-overlap-check-skipped` (the scenario's) turns only the race red;
`timesheet-drops-open-shift` only the two Timesheet oracle checks; `clock-in-twice-opens-two` (the schema
without `uq_clock_events_open_employee`) only the one-open check.
"""
from __future__ import annotations

import asyncio
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

from slop.actors.clock import Clock
from slop.lib.shifts_faults import (AUDIT, LIST_ORACLE, ONE_OPEN, ORACLE_ACC, ORACLE_EMP, OWNER_WRITES, RACE,
                                    UI_REPORTS, UI_SHIFTS)
from slop.seed import chatters, shift_history
from slop.seed.shift_history import BLOCK_H, DST_NIGHT, RESERVED, WINDOW, occurrences, to_utc

PROFILE = "agency_inbox"
UI = True
FAULT = "shift-overlap-check-skipped"
TIMESHEET_P95_MS = 1000
HEARTBEAT_P95_MS = 200
P95_VS_LAST = (2.0, 50)
TS_BUDGET = f"p95 GET /admin/shifts/timesheet <= {TIMESHEET_P95_MS} ms"
HB_BUDGET = f"p95 POST /admin/shifts/clock-heartbeat <= {HEARTBEAT_P95_MS} ms"
WAIT_MS = 120_000
LIST_DAYS = 41      # the week list's read after the writes: [now, now + 41 d) (the route's 42-day cap)
SOLO_WEEKS = 3      # a Creator's solo create lies at most this many race weeks out, inside LIST_DAYS


def _z(dt: datetime) -> str:
    return dt.isoformat() + "Z"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _merged(spans):
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _clip_s(a, b, lo, hi) -> float:
    return max(0.0, (min(b, hi) - max(a, lo)).total_seconds())


def oracle(series: list[dict], events: list[dict], lo: datetime, hi: datetime, now: datetime,
           by_employee: bool) -> dict[str, tuple]:
    """The Timesheet for [lo, hi) from the spec, over the seed's series and every clock event (an open one
    runs to `now`): {key: (scheduled_shifts, shifts_worked, scheduled_minutes, worked_minutes, open_now)}."""
    mine = defaultdict(list)  # employee -> its series
    for sr in series:
        mine[sr["employee_id"]].append(sr)
    spans = []  # (employee, account, lo, hi, open): each event's time per Creator
    for ev in events:
        stop = ev["out_utc"] or now
        if ev["account_id"] is not None:
            spans.append((ev["employee_id"], ev["account_id"], ev["in_utc"], stop, ev["out_utc"] is None))
            continue
        pieces = defaultdict(list)  # agency-wide: only inside the occurrences its Employee holds per Creator
        for sr in mine[ev["employee_id"]]:
            pieces[sr["account_id"]] += [(max(a, ev["in_utc"]), min(b, stop))
                                         for a, b in occurrences(sr, ev["in_utc"], stop)]
        spans += [(ev["employee_id"], acc, a, b, ev["out_utc"] is None)
                  for acc, ps in pieces.items() for a, b in _merged(ps) if a < b]
    rows: dict = {}

    def row(k):
        return rows.setdefault(k, {"n": 0, "worked_n": 0, "sched_s": 0.0, "worked_s": 0.0, "open": False})

    for sr in series:
        pair = (sr["employee_id"], sr["account_id"])
        for a, b in occurrences(sr, lo, hi):
            r = row(sr["employee_id"] if by_employee else sr["account_id"])
            r["n"] += 1
            r["sched_s"] += _clip_s(a, b, lo, hi)
            r["worked_n"] += any((e, acc) == pair and s_lo < b and s_hi > a for e, acc, s_lo, s_hi, _ in spans)
    worked = ([(ev["employee_id"], ev["in_utc"], ev["out_utc"] or now, ev["out_utc"] is None) for ev in events]
              if by_employee else [(acc, a, b, op) for _, acc, a, b, op in spans])
    for k, a, b, op in worked:
        s = _clip_s(a, b, lo, hi)
        if k is None or s <= 0:
            continue
        r = row(k)
        r["worked_s"] += s
        r["open"] = r["open"] or op
    return {str(k): (r["n"], r["worked_n"], int(r["sched_s"] // 60), math.ceil(round(r["worked_s"], 3) / 60),
                     r["open"]) for k, r in rows.items()}


def _product_rows(body: dict) -> dict[str, tuple]:
    out = {}
    for r in body.get("rows") or []:
        t = (r["scheduled_shifts"], r["shifts_worked"], r["scheduled_minutes"], r["worked_minutes"], r["open_now"])
        if any(t):
            out[r["key"]] = t
    return out


def _diff(got: dict, want: dict) -> list:
    return [{"key": k, "got": got.get(k), "want": want.get(k)} for k in sorted(got.keys() | want.keys())
            if got.get(k) != want.get(k)]


async def _settings(ctx) -> None:
    r = await ctx.owner.put("/admin/settings/time-tracking", json={
        "enabled": True, "clock_in_reminder": False, "auto_clock_out_minutes": 999, "role_ids": ["chatter", "owner"]})
    r.raise_for_status()


async def _roles(ctx, emp_ids: list[int]) -> None:
    """Every login holds a role: the Roles save gives any login without one Chatter (settings_api)."""
    r = await ctx.owner.get("/admin/settings/roles")
    r.raise_for_status()
    cfg = r.json().get("config") or {}
    have = cfg.get("assignments") or {}
    if any(str(e) not in have for e in emp_ids):
        rr = await ctx.owner.put("/admin/settings/roles", json=cfg)
        rr.raise_for_status()


def _slot(hist: dict, creator: dict, week: int, today: date) -> dict:
    """The reserved slot (Sunday 20:00-24:00 local) of `creator`, `week` weeks after the first Sunday at
    least a week ahead."""
    wd, block = RESERVED
    tz = hist["tz_by_creator"][creator["id"]]
    day = today + timedelta(days=7 + (wd - today.isoweekday()) % 7, weeks=week)
    wall = datetime.combine(day, datetime.min.time()) + timedelta(hours=block * BLOCK_H)
    return {"account_id": creator["id"], "tz": tz, "start": to_utc(wall, tz),
            "end": to_utc(wall + timedelta(hours=BLOCK_H), tz)}


async def _race(ctx, slot: dict, emps: list[int], n: int) -> dict:
    async def one(k: int):
        body = {"start_utc": _z(slot["start"]), "end_utc": _z(slot["end"]), "tz": slot["tz"],
                "employee_ids": [emps[k % len(emps)]], "account_ids": [slot["account_id"]]}
        try:
            r = await ctx.owner.post("/admin/shifts", json=body)
        except Exception:  # noqa: BLE001 — the stock check counts it
            return 599, None
        return r.status_code, (r.json().get("shift_id") if r.status_code < 300 else None)

    got = await asyncio.gather(*(one(k) for k in range(n)))
    return {**slot, "statuses": [s for s, _ in got],
            "actions": [("shift.create", str(i)) for _, i in got if i is not None]}


def _edit_plan(hist: dict, now: datetime, n: int) -> list[dict]:
    """Owner writes on seeded series, each on a future occurrence (>= now + 1 day) the seed's expansion
    names; kinds in turn: PATCH this, PATCH following, cancel this, cancel following. A "following" one
    needs an earlier occurrence left in its series, else the product takes it as "all"."""
    kinds = ("patch-this", "patch-following", "cancel-this", "cancel-following")
    out = []
    for sr in hist["series"]:
        if len(out) >= n:
            break
        occ = occurrences(sr, now + timedelta(days=1), now + timedelta(days=30))
        if not occ:
            continue
        kind = kinds[len(out) % len(kinds)]
        if kind.endswith("following") and not occurrences(sr, sr["start_utc"], occ[0][0]):
            continue
        out.append({"kind": kind, "series": sr, "occ": occ[0]})
    return out


async def _edit(http, e: dict) -> dict:
    """One planned write, answered, with what it must leave: `actions` (its audit rows), `shown` (week list
    occurrences: shift id, start, end) and `gone` (series id, occurrence start, following: no occurrence of
    the series starts there, or from there on)."""
    sr, (a, b) = e["series"], e["occ"]
    verb, scope = e["kind"].split("-")
    sid = sr["id"]
    if verb == "patch":
        body = {"start_utc": _z(a), "end_utc": _z(b - timedelta(hours=1)), "tz": sr["tz"],
                "employee_ids": [sr["employee_id"]], "account_ids": [sr["account_id"]],
                "scope": scope, "occurrence_start": _z(a)}
        if scope == "following":
            body["repeat_days"] = sr["repeat_days"]
            body["repeat_until"] = sr["repeat_until"].isoformat() if sr["repeat_until"] else None
        r = await http.request("PATCH", f"/admin/shifts/{sid}", json=body)
    else:
        r = await http.post(f"/admin/shifts/{sid}/cancel", json={"scope": scope, "occurrence_start": _z(a)})
    out = {"kind": e["kind"], "id": sid, "status": r.status_code, "gone": (sid, _z(a), scope == "following")}
    if verb == "cancel":
        return {**out, "actions": [("shift.cancel", str(sid))], "shown": []}
    new = r.json().get("shift_id") if r.status_code < 300 else None
    return {**out, "actions": [("shift.edit", str(sid)), ("shift.create", str(new))],
            "shown": [(new, _z(a), _z(b - timedelta(hours=1)))]}


async def _create_patch_all(http, slot: dict, emp: int) -> list[dict]:
    """One create on a free slot (no race), then PATCH scope=all on it: 30 min shorter."""
    body = {"start_utc": _z(slot["start"]), "end_utc": _z(slot["end"]), "tz": slot["tz"],
            "employee_ids": [emp], "account_ids": [slot["account_id"]]}
    r = await http.post("/admin/shifts", json=body)
    sid = r.json().get("shift_id") if r.status_code < 300 else None
    made = {"kind": "create", "id": sid, "status": r.status_code, "actions": [("shift.create", str(sid))],
            "shown": [], "gone": None}
    if sid is None:
        return [made]
    end = slot["end"] - timedelta(minutes=30)
    r = await http.request("PATCH", f"/admin/shifts/{sid}", json={**body, "end_utc": _z(end), "scope": "all"})
    return [made, {"kind": "patch-all", "id": sid, "status": r.status_code, "actions": [("shift.edit", str(sid))],
                   "shown": [(sid, _z(slot["start"]), _z(end))], "gone": None}]


async def _reader(http, rng, stop: asyncio.Event, week: tuple[str, str]) -> None:
    lo, hi = _z(WINDOW[0]), _z(WINDOW[1])
    reads = (f"/admin/shifts/timesheet?from={lo}&to={hi}&group=employee",
             f"/admin/shifts/timesheet?from={lo}&to={hi}&group=account",
             f"/admin/shifts?from={lo}&to={hi}", f"/admin/shifts?from={week[0]}&to={week[1]}",
             f"/admin/stats/chatting-stats?from={lo}&to={hi}")
    i = rng.randrange(len(reads))
    while not stop.is_set():
        try:
            await http.get(reads[i % len(reads)])
        except Exception:  # noqa: BLE001 — the stock check counts it
            pass
        i += 1
        try:
            await asyncio.wait_for(stop.wait(), rng.uniform(0.3, 1.0))
        except asyncio.TimeoutError:
            pass


def _p95(ctx, route: str) -> tuple[float | None, int]:
    s = ctx.rec.summary().get(route)
    return (s["p95_ms"], s["n"]) if s else (None, 0)


async def _listed(ctx, lo: datetime, hi: datetime) -> tuple[int, set]:
    r = await ctx.owner.get(f"/admin/shifts?from={_z(lo)}&to={_z(hi)}")
    return r.status_code, {(o["shift_id"], o["occurrence_start"], o["occurrence_end"])
                           for o in (r.json().get("occurrences", []) if r.status_code == 200 else [])}


def _check_race(ctx, w, race_out: list[dict], race_n: int) -> None:
    """Exactly one 2xx per round, the rest 409, and one Shift row on the slot."""
    con = w.sql()
    rounds = [{"account_id": x["account_id"], "start": _z(x["start"]),
               "2xx": sum(200 <= s < 300 for s in x["statuses"]), "409": sum(s == 409 for s in x["statuses"]),
               "other": [s for s in x["statuses"] if s != 409 and not 200 <= s < 300],
               "rows_on_slot": con.execute(
                   "SELECT COUNT(*) FROM shifts s JOIN shift_assignments a ON a.shift_id = s.id WHERE s.status = "
                   "'scheduled' AND a.account_id = ? AND s.start_utc = ?",
                   (x["account_id"], x["start"].strftime("%Y-%m-%d %H:%M:%S.%f"))).fetchone()[0]}
              for x in race_out]
    con.close()
    ctx.check(RACE, bool(rounds) and all(x["2xx"] == 1 and x["409"] == race_n - 1 and x["rows_on_slot"] == 1
                                         for x in rounds), rounds=rounds)


def _check_one_open(ctx, w, clock, members: list, emp_of_user: dict, storm: int) -> None:
    """After the storm, every storm chatter holds one open clock event, got one 2xx clock-in and a 409
    for each other one (clock_api.clock_in: a clock-in while one is open is 409)."""
    con = w.sql()
    open_by_emp = dict(con.execute("SELECT employee_id, COUNT(*) FROM clock_events WHERE out_utc IS NULL "
                                   "GROUP BY employee_id").fetchall())
    con.close()
    storm_ok = Counter(u for kind, u, st, _ in clock.writes if kind == "in" and 200 <= st < 300)
    storm_409 = Counter(u for kind, u, st, _ in clock.writes if kind == "in" and st == 409)
    got = [(m.username, emp_of_user[m.username]) for m in members]
    bad = [{"chatter": u, "employee_id": emp, "open": open_by_emp.get(emp, 0), "clock_in_2xx": storm_ok.get(u, 0),
            "clock_in_409": storm_409.get(u, 0)}
           for u, emp in got if open_by_emp.get(emp, 0) != 1 or storm_ok.get(u, 0) != 1
           or storm_409.get(u, 0) != storm - 1]
    ctx.check(ONE_OPEN, bool(members) and not bad, chatters=len(members), per=storm,
              statuses=dict(Counter(st for kind, _, st, _ in clock.writes if kind == "in")), bad=bad[:20],
              bad_n=len(bad))


async def _check_owner_writes(ctx, edits: list[dict]) -> None:
    """Every owner write 2xx, its `shown` occurrences listed and its `gone` ones not."""
    now = _utcnow()
    status, listed = await _listed(ctx, now, now + timedelta(days=LIST_DAYS))
    shown = []
    for e in edits:
        ok = 200 <= e["status"] < 300 and all(x in listed for x in e["shown"])
        if ok and e["gone"]:
            sid, a, following = e["gone"]
            ok = not any(i == sid and (s == a or following and s > a) for i, s, _ in listed)
        shown.append({"kind": e["kind"], "id": e["id"], "status": e["status"], "ok": ok})
    ctx.check(OWNER_WRITES, status == 200 and bool(edits) and all(x["ok"] for x in shown), writes=shown)


def _check_audit(ctx, w, base_action: int, race_out: list[dict], edits: list[dict], clock) -> None:
    """One `actions` row per 2xx write, none for a refused one."""
    want = Counter(a for x in race_out for a in x["actions"])
    want.update(a for e in edits if 200 <= e["status"] < 300 for a in e["actions"])
    want.update(("clock." + kind, str(eid)) for kind, _, st, eid in clock.writes if 200 <= st < 300)
    con = w.sql()
    got = Counter(con.execute("SELECT action, target_id FROM actions WHERE id > ? AND target_type IN "
                              "('shift', 'clock_event')", (base_action,)).fetchall())
    con.close()
    miss = {f"{k[0]} {k[1]}": want[k] - got.get(k, 0) for k in want if want[k] != got.get(k, 0)}
    extra = {f"{k[0]} {k[1]}": got[k] - want.get(k, 0) for k in got if k not in want}
    ctx.check(AUDIT, bool(want) and not miss and not extra, writes=sum(want.values()), rows=sum(got.values()),
              mismatched=dict(list(miss.items())[:20]), unexpected=dict(list(extra.items())[:20]))


async def _check_timesheet(ctx, w, hist: dict, base_event: int) -> None:
    """The Timesheet per Employee and per Creator over the DST window == the oracle, live events too."""
    con = w.sql()
    live = [{"id": i, "employee_id": e, "account_id": a, "in_utc": datetime.fromisoformat(t_in),
             "out_utc": datetime.fromisoformat(t_out) if t_out else None}
            for i, e, a, t_in, t_out in con.execute(
                "SELECT id, employee_id, account_id, in_utc, out_utc FROM clock_events WHERE id > ?",
                (base_event,)).fetchall()]
    con.close()
    lo, hi = WINDOW
    for group, name in (("employee", ORACLE_EMP), ("account", ORACLE_ACC)):
        tr = await ctx.owner.get(f"/admin/shifts/timesheet?from={_z(lo)}&to={_z(hi)}&group={group}")
        want_rows = oracle(hist["series"], hist["events"] + live, lo, hi, _utcnow(), group == "employee")
        got_rows = _product_rows(tr.json()) if tr.status_code == 200 else {}
        d = _diff(got_rows, want_rows)
        ctx.check(name, tr.status_code == 200 and bool(want_rows) and not d, http=tr.status_code,
                  rows=len(want_rows), mismatched=d[:20], mismatched_n=len(d))


async def _check_list(ctx, hist: dict) -> None:
    """The week list over the DST window == the oracle's occurrences, and the Berlin fall-back night's
    occurrence of the DST series (series[0]: Sunday 00:00-04:00 Berlin) is 5 h long."""
    lo, hi = WINDOW
    status, got = await _listed(ctx, lo, hi)
    want = {(sr["id"], _z(a), _z(b)) for sr in hist["series"] for a, b in occurrences(sr, lo, hi)}
    night = _z(to_utc(datetime.combine(DST_NIGHT, datetime.min.time()), hist["series"][0]["tz"]))
    dst = [(s, e) for i, s, e in got if i == hist["series"][0]["id"] and s == night]
    long5 = [datetime.fromisoformat(e[:-1]) - datetime.fromisoformat(s[:-1]) == timedelta(hours=5) for s, e in dst]
    ctx.check(LIST_ORACLE, status == 200 and got == want and long5 == [True], occurrences=len(want),
              missing=sorted(want - got)[:10], unexpected=sorted(got - want)[:10], dst_night=dst)


def _check_budgets(ctx) -> None:
    for nm, route, budget in ((TS_BUDGET, "GET /admin/shifts/timesheet", TIMESHEET_P95_MS),
                              (HB_BUDGET, "POST /admin/shifts/clock-heartbeat", HEARTBEAT_P95_MS)):
        p, n = _p95(ctx, route)
        if p is None:
            ctx.skip(nm, "no samples")
        else:
            ctx.check(nm, p <= budget, budget=True, p95_ms=p, n=n)
    keys = {"timesheet": "GET /admin/shifts/timesheet", "heartbeat": "POST /admin/shifts/clock-heartbeat",
            "clock_in": "POST /admin/shifts/clock-in", "clock_status": "GET /admin/shifts/clock-status",
            "shifts_list": "GET /admin/shifts", "shift_create": "POST /admin/shifts",
            "chatting_stats": "GET /admin/stats/chatting-stats"}
    ctx.metric("p95_vs_last_green", {k: p for k, r in keys.items() if (p := _p95(ctx, r)[0]) is not None})


async def _ui(ctx) -> None:
    from slop.actors import ui
    now = _utcnow()
    r = await ctx.owner.get(f"/admin/shifts?from={_z(now - timedelta(days=7))}&to={_z(now + timedelta(days=7))}")
    listed = {e["display_name"] for o in r.json().get("occurrences", []) for e in o["employees"]}
    # the report's default range (the last 30 days) and the card's own read; chatting-stats lists only
    # Employees with sends or sales, which this world does not seed
    rs = await ctx.owner.get(f"/admin/shifts/timesheet?from={_z(now - timedelta(days=30))}&to={_z(now)}"
                             "&group=employee")
    stat_names = {x.get("display_name") for x in (rs.json().get("rows") or [])} - {None}
    async with ui.owner_browser(ctx) as page:
        # (path, shot tag, names the API lists, check, its API status, scroll: the Clocked hours card sits
        # below the charts)
        for path, tag, names, check, api_status, scroll in (
                ("/employees/shifts", "shifts", listed, UI_SHIFTS, r.status_code, False),
                ("/analytics/employee-reports", "employee-reports", stat_names, UI_REPORTS, rs.status_code, True)):
            try:
                await page.goto(f"{ctx.app}{path}", wait_until="domcontentloaded", timeout=WAIT_MS)
                await ui.shot(ctx, page, f"{tag}-trigger")
                seen = None
                t_end = asyncio.get_event_loop().time() + WAIT_MS / 1000
                while seen is None and asyncio.get_event_loop().time() < t_end:
                    text = await page.inner_text("body")
                    seen = next((n for n in sorted(names) if n in text), None)
                    if seen is None:
                        await asyncio.sleep(0.5)
                if seen is not None and scroll:
                    await page.get_by_text(seen, exact=True).first.scroll_into_view_if_needed(timeout=WAIT_MS)
                await page.wait_for_timeout(500)
                await ui.shot(ctx, page, f"{tag}-settled")
                ctx.check(check, seen is not None, shown=seen, api_names=len(names), api_status=api_status)
            except Exception as e:  # noqa: BLE001 — a UI step that cannot complete is its check's FAIL
                try:
                    await ui.shot(ctx, page, f"failed-{tag}")
                except Exception:  # noqa: BLE001
                    pass
                ctx.check(check, False, error=f"{type(e).__name__}: {e}"[:400])


async def run(ctx) -> None:
    sizes = {k: ctx.param(k, ctx.world.size[f"shifts_clock_{k}"])
             for k in ("employees", "series", "open_n", "race_rounds", "race_n", "storm", "readers", "edits")}
    w = await ctx.build(PROFILE)
    creators = w.data["creators"]
    # Each Creator's solo create goes in its first week no race round takes, so it stays inside LIST_DAYS.
    sizes["race_rounds"] = min(sizes["race_rounds"], SOLO_WEEKS * len(creators))
    ctx.metric("sizes", sizes)
    await _settings(ctx)
    names = [f"{w.user_prefix}{w.seed}k{i}" for i in range(sizes["employees"])]
    recs = await chatters.seed(w, ctx.owner, w.user_id, names,
                               account_ids=[[creators[i % len(creators)]["id"]] for i in range(len(names))])
    r = await ctx.owner.get("/admin/employees")
    r.raise_for_status()
    by_user = {e.get("username"): e for e in r.json()["employees"]}
    for rec in recs:
        rec["employee_id"] = by_user[rec["username"]]["id"]
    await _roles(ctx, [rec["employee_id"] for rec in recs])
    hist = shift_history.seed(w, [{"employee_id": x["employee_id"], "account_id": x["account_ids"][0]} for x in recs],
                              creators, n=sizes["series"], open_n=sizes["open_n"])
    ctx.metric("history", {"series": len(hist["series"]), "events": len(hist["events"]),
                           "open": hist["open_employee_ids"], "tz_by_creator": hist["tz_by_creator"]})
    con = w.sql()
    base_action = con.execute("SELECT COALESCE(MAX(id), 0) FROM actions").fetchone()[0]
    base_event = con.execute("SELECT COALESCE(MAX(id), 0) FROM clock_events").fetchone()[0]
    con.close()

    # ── Phase A: the create race and the clock-in storm, at once ──
    rng = w.rng("shifts_clock_crowd")
    now0 = _utcnow()
    emps_of = defaultdict(list)
    for rec in recs:
        emps_of[rec["account_ids"][0]].append(rec["employee_id"])
    rounds, n_c = sizes["race_rounds"], len(creators)
    slots = [_slot(hist, creators[r % n_c], r // n_c, now0.date()) for r in range(rounds)]
    solo = [_slot(hist, c, len(range(i, rounds, n_c)), now0.date()) for i, c in enumerate(creators)]
    opens = set(hist["open_employee_ids"])
    actors = [rec for rec in recs if rec["employee_id"] not in opens][:max(1, ctx.users)]
    clock = Clock(ctx.rec, w.rng("clock"))
    members = [clock.member(rec, ctx.relay) for rec in actors]
    emp_of_user = {rec["username"]: rec["employee_id"] for rec in recs}
    logged = await asyncio.gather(*(clock.login(m) for m in members))
    members = [m for m, ok in zip(members, logged) if ok]
    ctx.metric("actors", {"asked": len(actors), "signed_in": len(members)})

    async def races():
        return [await _race(ctx, slot, emps_of[slot["account_id"]], sizes["race_n"]) for slot in slots]

    ctx.rec.stage = "A"
    race_out, _ = await asyncio.gather(races(), clock.storm(members, sizes["storm"]))
    _check_race(ctx, w, race_out, sizes["race_n"])
    _check_one_open(ctx, w, clock, members, emp_of_user, sizes["storm"])

    # ── Phase B: the chatters' day, owners reading, owner writes ──
    ctx.rec.stage = "B"
    stop = asyncio.Event()
    week = (_z(now0 - timedelta(days=3)), _z(now0 + timedelta(days=4)))
    readers = [ctx.owner.share(limits=4) for _ in range(sizes["readers"])]
    read_tasks = [asyncio.create_task(_reader(h, w.rng(f"reader{i}"), stop, week)) for i, h in enumerate(readers)]
    plan = _edit_plan(hist, now0, sizes["edits"])
    writer = ctx.owner.share(limits=4)
    edits: list[dict] = []

    async def owner_writes():
        for slot in solo:  # a create on a slot no race touched, then PATCH all on it
            edits.extend(await _create_patch_all(writer, slot, emps_of[slot["account_id"]][0]))
        for e in plan:
            edits.append(await _edit(writer, e))
            await asyncio.sleep(rng.uniform(0.2, 0.8))

    await asyncio.gather(owner_writes(), *(clock.work(m) for m in members))
    stop.set()
    await asyncio.gather(*read_tasks, return_exceptions=True)
    ctx.rec.stage = None

    await _check_owner_writes(ctx, edits)
    _check_audit(ctx, w, base_action, race_out, edits, clock)
    await _check_timesheet(ctx, w, hist, base_event)
    await _check_list(ctx, hist)
    _check_budgets(ctx)
    ctx.metric("clock_writes", dict(Counter(f"{k} {s}" for k, _, s, _ in clock.writes)))
    ctx.metric("routes", ctx.rec.summary())
    await clock.close(members)
    for h in (*readers, writer):
        await h.aclose()

    if ctx.app is None:
        ctx.skip(UI_SHIFTS, "--no-ui")
        ctx.skip(UI_REPORTS, "--no-ui")
        return
    await _ui(ctx)
