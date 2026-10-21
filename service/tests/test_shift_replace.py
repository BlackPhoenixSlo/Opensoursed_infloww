#!/usr/bin/env python3
"""Replace on overlap and the scheduling horizon (roadmap W6 6.12).

- `replace: true` on POST or PATCH /admin/shifts writes a Shift that clashes with other Shifts on a Creator
  instead of answering 409: a one-off it clashes with is cancelled, a weekly series loses the clashing
  occurrences' dates (`cancelled_dates`), each with its `shift.cancel` or `shift.edit` audit row. The Shift's
  own double-staffing is still 409, and `replace` that is not true or false is 422. A "this" edit that lands on
  another occurrence of its own series takes that date out too, and the series' audit rows chain (each row's
  `before` is the one before's `after`). A series in a zone with DST loses the clashing local date.
- A create or an edit may not put a Shift's start more than SCHEDULE_HORIZON (366 days) ahead (422), while an
  edit that keeps a far start where it is goes through.

The seam is the Relay over HTTP with Agency A's owner session (Multiple employees per shift off, so the overlap
rule is on); every case owns its Creator and Employees.

Run: ./venv/bin/python service/tests/test_shift_replace.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
from _clock_fixtures import IDS, create as _create, employee as _employee  # noqa: E402
from _clock_fixtures import shift as _seed_shift, utc_now, z  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Action, Shift, UserAccount  # noqa: E402

OWNER_A = fx.login_owner("agency_a_owner")
MONDAYS = ["2026-03-02", "2026-03-09", "2026-03-16", "2026-03-23", "2026-03-30"]
MARCH = {"from": "2026-03-01T00:00:00Z", "to": "2026-04-06T00:00:00Z"}
_next_creator = iter(range(1_000_401, 1_000_500))


def _creator() -> str:
    aid = str(next(_next_creator))

    async def _seed():
        async with get_session() as s:
            s.add(Account(id=aid, nickname=f"replace_{aid[-2:]}", color="#aaaaaa"))
        async with get_session() as s:
            s.add(UserAccount(user_id=IDS["agency_a_owner"], account_id=aid))
    (account_registry.ACCOUNTS_DIR / aid).mkdir()
    asyncio.run(_seed())
    return aid


def _body(emp, aid: str, day: str, start: str = "09:00", end: str = "17:00", weekly: bool = False, **extra) -> dict:
    emps = emp if isinstance(emp, list) else [emp]
    return {"start_utc": f"{day}T{start}:00Z", "end_utc": f"{day}T{end}:00Z", "tz": "UTC", "employee_ids": emps,
            "account_ids": [aid], **({"repeat_days": [1], "repeat_until": MONDAYS[-1]} if weekly else {}), **extra}


def _post(body: dict, status: int = 200):
    r = OWNER_A.post("/admin/shifts", json=body)
    assert r.status_code == status, f"create: {r.status_code} {r.text}"
    return r.json()


def _patch(shift_id: int, body: dict, status: int = 200):
    r = OWNER_A.patch(f"/admin/shifts/{shift_id}", json=body)
    assert r.status_code == status, f"edit: {r.status_code} {r.text}"
    return r.json()


def _week(aid: str) -> list[tuple[int, str]]:
    r = OWNER_A.get("/admin/shifts", params={**MARCH, "account_id": aid})
    assert r.status_code == 200, r.text
    return [(o["shift_id"], o["occurrence_start"]) for o in r.json()["occurrences"]]


def _row(shift_id: int) -> Shift:
    async def _get():
        async with get_session() as s:
            return await s.get(Shift, shift_id)
    return asyncio.run(_get())


def _audit(shift_id: int) -> list[str]:
    return [action for action, _ in _audit_rows(shift_id)]


def _audit_rows(shift_id: int) -> list[tuple[str, dict]]:
    async def _get():
        async with get_session() as s:
            rows = (await s.execute(select(Action.action, Action.payload_json).where(
                Action.target_type == "shift", Action.target_id == str(shift_id)).order_by(Action.id))).all()
            return [(action, json.loads(payload)) for action, payload in rows]
    return asyncio.run(_get())


# ── Replace on overlap ──────────────────────────────────────────────


def case_replace_cancels_a_clashing_one_off():
    aid, e1, e2 = _creator(), _employee("replace_one_1"), _employee("replace_one_2")
    old = _post(_body(e1, aid, MONDAYS[0]))["shift_id"]
    refused = _post(_body(e2, aid, MONDAYS[0], "12:00", "20:00"), status=409)
    assert [c["shift_id"] for c in refused["clashes"]] == [old], refused
    assert _row(old).status == "scheduled", "a refused write changes nothing"
    new = _post(_body(e2, aid, MONDAYS[0], "12:00", "20:00", replace=True))["shift_id"]
    assert _row(old).status == "cancelled" and _row(old).cancelled_at is not None
    assert _audit(old) == ["shift.create", "shift.cancel"], _audit(old)
    assert _week(aid) == [(new, f"{MONDAYS[0]}T12:00:00Z")], _week(aid)


def case_replace_takes_only_the_clashing_occurrences_out_of_a_series():
    aid, e1, e2 = _creator(), _employee("replace_series_1"), _employee("replace_series_2")
    series = _post(_body(e1, aid, MONDAYS[0], weekly=True))["shift_id"]
    new = _post(_body(e2, aid, MONDAYS[2], "16:00", "18:00", replace=True))["shift_id"]
    assert json.loads(_row(series).cancelled_dates) == [MONDAYS[2]], _row(series).cancelled_dates
    assert _row(series).status == "scheduled"
    assert _audit(series) == ["shift.create", "shift.edit"], _audit(series)
    assert _week(aid) == [(series, f"{d}T09:00:00Z") for d in MONDAYS[:2]] + [(new, f"{MONDAYS[2]}T16:00:00Z")] \
        + [(series, f"{d}T09:00:00Z") for d in MONDAYS[3:]], _week(aid)


def case_a_replacing_series_clears_every_clashing_week():
    aid, e1, e2 = _creator(), _employee("replace_two_series_1"), _employee("replace_two_series_2")
    old = _post(_body(e1, aid, MONDAYS[0], weekly=True))["shift_id"]
    new = _post(_body(e2, aid, MONDAYS[0], "08:00", "10:00", weekly=True, replace=True))["shift_id"]
    assert json.loads(_row(old).cancelled_dates) == MONDAYS, _row(old).cancelled_dates
    assert _week(aid) == [(new, f"{d}T08:00:00Z") for d in MONDAYS], _week(aid)


def case_an_edit_with_replace_moves_onto_another_shift():
    aid, e1, e2 = _creator(), _employee("replace_edit_1"), _employee("replace_edit_2")
    other = _post(_body(e1, aid, MONDAYS[1]))["shift_id"]
    mine = _post(_body(e2, aid, MONDAYS[0]))["shift_id"]
    _patch(mine, _body(e2, aid, MONDAYS[1], "10:00", "11:00"), status=409)
    _patch(mine, _body(e2, aid, MONDAYS[1], "10:00", "11:00", replace=True))
    assert _row(other).status == "cancelled"
    assert _week(aid) == [(mine, f"{MONDAYS[1]}T10:00:00Z")], _week(aid)


def case_a_this_edit_onto_its_own_series_takes_that_date_out_with_chained_audit_rows():
    aid, emp = _creator(), _employee("replace_this_emp")
    series = _post(_body(emp, aid, MONDAYS[0], weekly=True))["shift_id"]
    moved = {**_body(emp, aid, MONDAYS[2], "10:00", "11:00"), "scope": "this",
             "occurrence_start": f"{MONDAYS[1]}T09:00:00Z"}
    refused = _patch(series, moved, status=409)
    assert {c["shift_id"] for c in refused["clashes"]} == {series}, refused
    new = _patch(series, {**moved, "replace": True})["shift_id"]
    assert sorted(json.loads(_row(series).cancelled_dates)) == MONDAYS[1:3], _row(series).cancelled_dates
    assert _week(aid) == [(series, f"{MONDAYS[0]}T09:00:00Z"), (new, f"{MONDAYS[2]}T10:00:00Z")] \
        + [(series, f"{d}T09:00:00Z") for d in MONDAYS[3:]], _week(aid)
    rows = _audit_rows(series)
    assert [a for a, _ in rows] == ["shift.create", "shift.edit", "shift.edit"], rows
    for (_, prev), (_, row) in zip(rows, rows[1:]):
        assert row["before"] == prev["after"], (prev, row)


def case_replace_in_a_dst_zone_takes_out_the_local_date_that_clashes():
    # America/New_York: 09:00 local is 14:00Z before 2026-03-08 and 13:00Z after it.
    aid, e1, e2 = _creator(), _employee("replace_dst_1"), _employee("replace_dst_2")
    ny = {"tz": "America/New_York", "account_ids": [aid]}
    series = _post({**ny, "start_utc": f"{MONDAYS[0]}T14:00:00Z", "end_utc": f"{MONDAYS[0]}T22:00:00Z",
                    "employee_ids": [e1], "repeat_days": [1], "repeat_until": MONDAYS[-1]})["shift_id"]
    # 08:30-09:30 EDT on 03-16 clashes only with the DST-shifted 13:00Z start.
    one_off = {**ny, "start_utc": f"{MONDAYS[2]}T12:30:00Z", "end_utc": f"{MONDAYS[2]}T13:30:00Z",
               "employee_ids": [e2]}
    refused = _post(one_off, status=409)
    assert [c["occurrence_start"] for c in refused["clashes"]] == [f"{MONDAYS[2]}T13:00:00Z"], refused
    new = _post({**one_off, "replace": True})["shift_id"]
    assert json.loads(_row(series).cancelled_dates) == [MONDAYS[2]], _row(series).cancelled_dates
    assert _week(aid) == [(series, f"{MONDAYS[0]}T14:00:00Z"), (series, f"{MONDAYS[1]}T13:00:00Z"),
                          (new, f"{MONDAYS[2]}T12:30:00Z")] \
        + [(series, f"{d}T13:00:00Z") for d in MONDAYS[3:]], _week(aid)


def case_its_own_double_staffing_is_still_409_and_replace_must_be_a_switch():
    aid, e1, e2, e3 = _creator(), _employee("replace_self_1"), _employee("replace_self_2"), _employee("replace_self_3")
    old = _post(_body(e1, aid, MONDAYS[0]))["shift_id"]
    refused = _post(_body([e2, e3], aid, MONDAYS[0], replace=True), status=409)
    assert {c["shift_id"] for c in refused["clashes"]} == {None, old}, refused
    assert _row(old).status == "scheduled", "nothing is replaced when the write is refused"
    for bad in ("yes", 1, None):
        _post(_body(e2, aid, MONDAYS[0], replace=bad), status=422)
    _patch(old, _body(e1, aid, MONDAYS[0], replace="true"), status=422)
    assert _row(old).status == "scheduled"


# ── The scheduling horizon ──────────────────────────────────────────


def case_a_start_past_the_horizon_is_refused_and_a_far_start_kept_in_place_is_not():
    aid, emp = _creator(), _employee("horizon_emp")
    far, near = utc_now() + timedelta(days=367), utc_now() + timedelta(days=300)
    r = OWNER_A.post("/admin/shifts", json={"start_utc": z(far), "end_utc": z(far + timedelta(hours=2)), "tz": "UTC",
                                            "employee_ids": [emp], "account_ids": [aid]})
    assert r.status_code == 422 and "366 days" in r.text, f"{r.status_code} {r.text}"
    sid = _create(OWNER_A, start_utc=z(near), end_utc=z(near + timedelta(hours=2)), tz="UTC",
                  employee_ids=[emp], account_ids=[aid])["shift_id"]
    edit = {"start_utc": z(far), "end_utc": z(far + timedelta(hours=2)), "tz": "UTC", "employee_ids": [emp],
            "account_ids": [aid]}
    _patch(sid, edit, status=422)
    # A Shift already beyond the horizon (scheduled before it applied) keeps its start through an edit.
    seeded = _seed_shift(far, far + timedelta(hours=2), [(emp, aid)])
    _patch(seeded, {**edit, "end_utc": z(far + timedelta(hours=3))})
    _patch(seeded, {**edit, "start_utc": z(far + timedelta(hours=1)), "end_utc": z(far + timedelta(hours=3))},
           status=422)


_harness.run()
