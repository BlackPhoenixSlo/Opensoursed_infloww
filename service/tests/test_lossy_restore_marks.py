#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import sqlite3  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest.mock import patch  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
from _clock_fixtures import IDS, employee, event  # noqa: E402
from _send_kill_cell import AID, SYNC_URL, cells, restart  # noqa: E402

import auth  # noqa: E402
import automation_executor as ax  # noqa: E402
import cell_hold  # noqa: E402
import cell_mode  # noqa: E402
import restore_reconcile  # noqa: E402
import run_decide  # noqa: E402

FID = "fansly-77"
ACCOUNTS = f"onlyfans:{AID},fansly:{FID}"
NOW = datetime.utcnow().replace(microsecond=0)
SINCE, RESTORED = NOW - timedelta(hours=3), NOW - timedelta(hours=1)


def _ts(d: datetime) -> str:
    return d.strftime("%Y-%m-%d %H:%M:%S")


def _db(sql: str, args: tuple = ()):
    with contextlib.closing(sqlite3.connect(str(_harness.DB_PATH))) as c, c:
        return c.execute(sql, args).fetchall()


async def _seed() -> None:
    from db.engine import get_session
    from db.models import Account
    async with get_session() as s:
        for aid in (AID, FID):
            if await s.get(Account, aid) is None:
                s.add(Account(id=aid, nickname=aid))


def _boot(*, bump: bool, reconcile: bool) -> dict:
    queued: list = []

    async def go():
        await _seed()
        restart()
        cell_mode.install_meta(SYNC_URL)
        restore_reconcile.install(SYNC_URL)
        await cell_hold.boot(SYNC_URL)
        _db("UPDATE cell_holds SET released_by='t', released_at='t' WHERE released_at IS NULL")
        _db("UPDATE cell_meta SET reconcile_since=?, restored_at=?, peek_until=NULL",
            (_ts(SINCE), _ts(RESTORED)) if reconcile else (None, None))
        if bump:
            _db("UPDATE cell_meta SET data_gen=data_gen+1")
        cell_mode.install_meta(SYNC_URL)
        overdue = await ax.enqueue_job(AID, "scheduled_send", run_at=datetime.utcnow() - timedelta(seconds=5))
        async def check(owned):
            queued.append(owned)
        with patch.object(restore_reconcile, "boot_queue_check", check):
            held = await cell_hold.boot(SYNC_URL)
            if cell_hold._queue_check is not None:
                await cell_hold._queue_check
                cell_hold._queue_check = None
        job = _db("SELECT status, last_error FROM scheduled_jobs WHERE id=?", (overdue,))[0]
        return {"held": held, "job": job, "queued": queued,
                "peek_until": _db("SELECT peek_until FROM cell_meta")[0][0],
                "holds": _db("SELECT platform, account FROM cell_holds WHERE released_at IS NULL ORDER BY id")}

    with cells(accounts=ACCOUNTS):
        return asyncio.run(go())


def case_lossy_restore_arms_peek_parks_overdue_and_lists_queue_and_holds_only_non_of():
    got = _boot(bump=True, reconcile=True)
    until = datetime.strptime(got["peek_until"], "%Y-%m-%d %H:%M:%S")
    assert timedelta(hours=23, minutes=59) < until - NOW <= timedelta(hours=24, minutes=1), got
    assert got["holds"] == [("fansly", FID)] and got["held"] == [("fansly", FID)], got
    assert got["job"] == ("error", run_decide.RESTORE_REASON), got
    assert got["queued"] == [[("fansly", FID), ("onlyfans", AID)]], got


def case_lossy_restore_without_reconcile_point_keeps_phase_2_hold():
    got = _boot(bump=True, reconcile=False)
    assert got["peek_until"] is None and got["queued"] == [], got
    assert sorted(got["holds"]) == [("fansly", FID), ("onlyfans", AID)], got
    assert got["job"] == ("error", run_decide.RESTORE_REASON), got


def case_planned_move_fires_nothing():
    got = _boot(bump=False, reconcile=True)
    assert (got["peek_until"], got["holds"], got["held"], got["queued"]) == (None, [], [], []), got
    assert got["job"][0] == "pending", got


def _message(fan: int, mid: int, at: datetime, direction: str = "out") -> None:
    _db("INSERT INTO messages (account_id, fan_id, message_id, direction, created_at, sender_name, body, media_ids,"
        " media_count, price_cents, is_tip, is_unsent, is_promise) VALUES (?,?,?,?,?,'','','[]',0,0,0,0,0)",
        (AID, fan, mid, direction, _ts(at)))


@contextlib.contextmanager
def _gap():
    cell_mode.install_meta(SYNC_URL)
    restore_reconcile.install(SYNC_URL)
    _db("UPDATE cell_meta SET reconcile_since=?, restored_at=?, gap_confirmed_by=NULL, gap_confirmed_at=NULL",
        (_ts(SINCE), _ts(RESTORED)))
    try:
        yield
    finally:
        _db("UPDATE cell_meta SET reconcile_since=NULL, restored_at=NULL")
        restore_reconcile._path = None


def case_gap_messages_are_unattributed():
    with _gap():
        _message(81001, 7001, SINCE - timedelta(minutes=1))
        _message(81001, 7002, SINCE + timedelta(minutes=1))
        _message(81002, 7003, RESTORED - timedelta(minutes=1))
        _message(81002, 7004, SINCE + timedelta(minutes=2), direction="in")
        _message(81002, 7005, RESTORED + timedelta(minutes=1))
        user = SimpleNamespace(id="u1", username="owner", is_admin=True)
        with patch.object(auth, "assert_account_owned", lambda a: None), \
                patch.object(auth, "get_request_user", lambda: user):
            body = asyncio.run(restore_reconcile.restore_gap(account_id=AID))
    assert [(m["message_id"], m["attribution"]) for m in body["messages"]] == [
        (7002, "unattributed"), (7003, "unattributed")], body
    assert body["gap"]["reconcile_since"] == _ts(SINCE) and body["gap"]["restored_at"] == _ts(RESTORED), body


def _sheet(owner) -> dict[str, dict]:
    r = owner.get("/admin/shifts/timesheet", params={"from": (NOW - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z"),
                                                     "to": (NOW + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")})
    assert r.status_code == 200, r.text
    return {row["key"]: row for row in r.json()["rows"]}


def case_gap_overlapping_shift_held_until_owner_confirms():
    inside, outside = employee("gap_inside"), employee("gap_outside")
    event(inside, SINCE + timedelta(minutes=10), SINCE + timedelta(minutes=50))
    event(outside, RESTORED + timedelta(minutes=5), RESTORED + timedelta(minutes=20))
    owner = fx.login_owner("agency_a_owner")
    assert "restore_held" not in _sheet(owner)[str(inside)], "env unset: no field"
    with _gap():
        rows = _sheet(owner)
        held = (rows[str(inside)]["restore_held"], rows[str(outside)]["restore_held"])
        user = SimpleNamespace(id=IDS["agency_a_owner"], username="agency_a_owner", is_admin=True)
        with patch.object(auth, "get_request_user", lambda: user):
            first = asyncio.run(restore_reconcile.restore_gap_confirm())
            second = asyncio.run(restore_reconcile.restore_gap_confirm())
        after = _sheet(owner)[str(inside)]["restore_held"]
        by = _db("SELECT gap_confirmed_by FROM cell_meta")[0][0]
    assert held == (True, False), rows
    assert (first, second, after) == ({"confirmed": True}, {"confirmed": False}, False), (first, second, after)
    assert by == f"user:{IDS['agency_a_owner']}:agency_a_owner", by


def case_confirm_needs_a_signed_in_owner():
    from fastapi import HTTPException
    with _gap(), patch.object(auth, "get_request_user", lambda: None):
        try:
            asyncio.run(restore_reconcile.restore_gap_confirm())
        except HTTPException as e:
            assert e.status_code == 403, e
        else:
            raise AssertionError("anonymous confirm accepted")
        assert _db("SELECT gap_confirmed_at FROM cell_meta")[0][0] is None


if __name__ == "__main__":
    _harness.run()
