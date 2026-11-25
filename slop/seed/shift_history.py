from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import World, ts

# Anchored, never the wall clock: 30 days past every run, holding Europe/Berlin's fall-back.
WINDOW = (datetime(2026, 10, 2), datetime(2026, 11, 1))
DST_NIGHT = date(2026, 10, 25)
TZS = ("Europe/Berlin", "America/New_York", "Asia/Tokyo", "UTC")
BLOCK_H = 4
BLOCKS = 24 // BLOCK_H
RESERVED = (7, BLOCKS - 1)
AUTO_MIN = 10


def to_utc(wall: datetime, tz: str) -> datetime:
    return wall.replace(tzinfo=ZoneInfo(tz), fold=0).astimezone(timezone.utc).replace(tzinfo=None)


def to_wall(utc: datetime, tz: str) -> datetime:
    return utc.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz)).replace(tzinfo=None)


def occurrences(sr: dict, lo: datetime, hi: datetime) -> list[tuple[datetime, datetime]]:
    tz = sr["tz"]
    if not sr["repeat_days"]:
        return [(sr["start_utc"], sr["end_utc"])] if sr["start_utc"] < hi and sr["end_utc"] > lo else []
    ws, we = to_wall(sr["start_utc"], tz), to_wall(sr["end_utc"], tz)
    days = set(sr["repeat_days"]) | {ws.isoweekday()}
    skip = set(sr["cancelled_dates"])
    d, last = ws.date(), to_wall(hi, tz).date()
    if sr["repeat_until"] is not None:
        last = min(last, sr["repeat_until"])
    out = []
    while d <= last:
        if d not in skip and (d == ws.date() or d.isoweekday() in days):
            if d == ws.date():
                o = (sr["start_utc"], sr["end_utc"])
            else:
                wall = datetime.combine(d, ws.time())
                o = (to_utc(wall, tz), to_utc(wall + (we - ws), tz))
            if o[0] < hi and o[1] > lo:
                out.append(o)
        d += timedelta(days=1)
    return out


def _first_date(rng, wd: int, lo: date, hi: date) -> date:
    d = lo + timedelta(days=rng.randrange((hi - lo).days))
    return d + timedelta(days=(wd - d.isoweekday()) % 7)


def seed(w: World, employees: list[dict], creators: list[dict], *, n: int, open_n: int) -> dict:
    rng = w.rng("shift_history")
    lo, hi = WINDOW
    tz_by = {c["id"]: TZS[i % len(TZS)] for i, c in enumerate(creators)}
    by_creator: dict[str, list[int]] = {}
    for e in employees:
        by_creator.setdefault(e["account_id"], []).append(e["employee_id"])
    free = {c["id"]: [(wd, b) for wd in range(1, 8) for b in range(BLOCKS) if (wd, b) != RESERVED]
            for c in creators if c["id"] in by_creator}
    for slots in free.values():
        rng.shuffle(slots)
    con = w.sql()
    sid0 = (con.execute("SELECT COALESCE(MAX(id), 0) FROM shifts").fetchone()[0]) + 1
    eid0 = (con.execute("SELECT COALESCE(MAX(id), 0) FROM clock_events").fetchone()[0]) + 1
    actor = f"owner:{w.user_id}"

    def add(aid: str, wd: int, b: int, first: date, until: date | None) -> None:
        tz = tz_by[aid]
        days = [wd]
        mate = [s for s in free[aid] if s[1] == b]
        if mate and rng.random() < 0.5:
            free[aid].remove(mate[0])
            days.append(mate[0][0])
        wall = datetime.combine(first, datetime.min.time()) + timedelta(hours=b * BLOCK_H)
        sr = {"id": sid0 + len(series), "account_id": aid, "employee_id": rng.choice(by_creator[aid]),
              "start_utc": to_utc(wall, tz), "end_utc": to_utc(wall + timedelta(hours=BLOCK_H), tz), "tz": tz,
              "repeat_days": sorted(days), "repeat_until": until, "cancelled_dates": []}
        if rng.random() < 0.3:
            dates = [d for o in occurrences(sr, lo - timedelta(days=14), hi)
                     if (d := to_wall(o[0], tz).date()) != DST_NIGHT]
            sr["cancelled_dates"] = sorted(rng.sample(dates, min(len(dates), rng.randint(1, 2))))
        series.append(sr)

    series: list[dict] = []
    order = [c["id"] for c in creators if c["id"] in free]
    dst_aid = next((a for a in order if tz_by[a] == "Europe/Berlin"), None)
    if n and dst_aid:
        free[dst_aid].remove((7, 0))
        add(dst_aid, 7, 0, date(2026, 9, 20), None)
    k = 1
    while len(series) < n and any(free.values()):
        aid = order[k % len(order)]
        k += 1
        if not free[aid]:
            continue
        wd, b = free[aid].pop()
        first = _first_date(rng, wd, lo.date() - timedelta(days=14), lo.date() + timedelta(days=20))
        r = rng.random()
        until = None if r < 0.4 else (
            first + timedelta(days=rng.randrange(7, 40)) if r < 0.7 else hi.date() + timedelta(days=rng.randrange(1, 30)))
        add(aid, wd, b, first, until)

    raw: dict[int, list[tuple]] = {}
    for sr in series:
        for o_start, o_end in occurrences(sr, lo - timedelta(days=1), hi):
            if o_end > hi or rng.random() >= 0.7:
                continue
            t_in = o_start + timedelta(seconds=rng.randint(-600, 1200))
            t_out = o_end + timedelta(seconds=rng.randint(-1200, 900))
            acc = sr["account_id"] if rng.random() < 0.8 else None
            raw.setdefault(sr["employee_id"], []).append(
                (t_in, t_out, acc, sr["id"] if o_start <= t_in < o_end else None))
    for e in employees:
        for _ in range(rng.randint(0, 2)):
            t_in = lo + timedelta(seconds=rng.randrange(int((hi - lo).total_seconds()) - 7200))
            raw.setdefault(e["employee_id"], []).append(
                (t_in, t_in + timedelta(seconds=rng.randint(900, 5400)),
                 e["account_id"] if rng.random() < 0.5 else None, None))
    acc_of = {e["employee_id"]: e["account_id"] for e in employees}
    opens = sorted(rng.sample(sorted(acc_of), min(open_n, len(acc_of))))
    open_in = {emp: hi - timedelta(seconds=rng.randint(3600, 4 * 3600)) for emp in opens}

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    events: list[dict] = []
    ev_rows, act_rows = [], []
    for emp in sorted(raw.keys() | set(opens)):
        prev_out = None
        spans = sorted(raw.get(emp, []))
        if emp in open_in:
            spans = [x for x in spans if x[1] < open_in[emp]] + [(open_in[emp], None, acc_of[emp], None)]
        for t_in, t_out, acc, sid in spans:
            if prev_out is not None and t_in < prev_out:
                continue
            ev = {"id": eid0 + len(events), "employee_id": emp, "account_id": acc, "shift_id": sid,
                  "in_utc": t_in, "out_utc": t_out}
            auto = t_out is not None and rng.random() < 0.15
            seen = (t_out - timedelta(minutes=AUTO_MIN)) if auto else (now if t_out is None else None)
            events.append(ev)
            ev_rows.append((ev["id"], w.user_id, emp, acc, sid, ts(t_in), ts(t_out) if t_out else None,
                            None if t_out is None else ("auto" if auto else "manual"), ts(seen) if seen else None))
            wire = {"clock_event_id": ev["id"], "employee_id": emp, "account_id": acc, "shift_id": sid,
                    "in_utc": t_in.isoformat() + "Z", "out_utc": None, "close_reason": None}
            act_rows.append((emp, acc, "clock.in", "clock_event", str(ev["id"]),
                             json.dumps({"actor": f"employee:{emp}", "before": None, "after": wire}), ts(t_in)))
            if t_out is not None:
                done = {**wire, "out_utc": t_out.isoformat() + "Z", "close_reason": "auto" if auto else "manual"}
                act_rows.append((None if auto else emp, acc, "clock.auto_out" if auto else "clock.out",
                                 "clock_event", str(ev["id"]),
                                 json.dumps({"actor": "system" if auto else f"employee:{emp}", "before": wire,
                                             "after": done}), ts(t_out)))
            prev_out = t_out if t_out is not None else datetime.max

    sh_rows, as_rows = [], []
    for sr in series:
        made = sr["start_utc"] - timedelta(days=rng.randint(1, 10))
        after = {"shift_id": sr["id"], "start_utc": sr["start_utc"].isoformat() + "Z",
                 "end_utc": sr["end_utc"].isoformat() + "Z", "tz": sr["tz"], "repeat_days": sr["repeat_days"],
                 "repeat_until": sr["repeat_until"].isoformat() if sr["repeat_until"] else None}
        sh_rows.append((sr["id"], w.user_id, ts(sr["start_utc"]), ts(sr["end_utc"]), sr["tz"],
                        json.dumps(sr["repeat_days"]),
                        sr["repeat_until"].isoformat() if sr["repeat_until"] else None,
                        json.dumps([d.isoformat() for d in sr["cancelled_dates"]]) if sr["cancelled_dates"] else None,
                        "scheduled", actor, ts(made), ts(made)))
        as_rows.append((sr["id"], sr["employee_id"], sr["account_id"]))
        act_rows.append((None, sr["account_id"], "shift.create", "shift", str(sr["id"]),
                         json.dumps({"actor": actor, "before": None, "after": after}), ts(made)))
        if sr["cancelled_dates"]:
            act_rows.append((None, sr["account_id"], "shift.cancel", "shift", str(sr["id"]),
                             json.dumps({"actor": actor, "before": after, "after": {
                                 **after, "cancelled_dates": [d.isoformat() for d in sr["cancelled_dates"]]}}),
                             ts(made + timedelta(hours=1))))
    with con:
        con.executemany("INSERT INTO shifts (id, agency_user_id, start_utc, end_utc, tz, repeat_days, repeat_until,"
                        " cancelled_dates, status, created_by, created_at, updated_at)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", sh_rows)
        con.executemany("INSERT INTO shift_assignments (shift_id, employee_id, account_id) VALUES (?,?,?)", as_rows)
        con.executemany("INSERT INTO clock_events (id, agency_user_id, employee_id, account_id, shift_id, in_utc,"
                        " out_utc, close_reason, last_seen_utc) VALUES (?,?,?,?,?,?,?,?,?)", ev_rows)
        con.executemany("INSERT INTO actions (employee_id, account_id, action, target_type, target_id, payload_json,"
                        " at) VALUES (?,?,?,?,?,?,?)", act_rows)
    con.close()
    out = {"tz_by_creator": tz_by, "series": series, "events": events, "open_employee_ids": opens}
    w.data["shift_history"] = out
    return out
