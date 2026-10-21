#!/usr/bin/env python3
"""The Agency owner's notification centre (service/notifications_api.py,
roadmap W6 6.7 and 6.10) and the audit log's names and date filter (6.16).

Over HTTP with real session cookies from the shared two-Agency fixture: the
audit middleware's hook files a row per real change (a role, a deactivation,
a chatter's unsend) and none for a save that changed nothing; each row is its
own Agency's; read / read-all and the unread count; a kind switched off in
the `preferences` blob files nothing; an assignment naming another Agency's
Employee files nothing; a dead session files once per episode; the clock-in
sweep files once per missed occurrence (not on a cancelled date, and past a
Shift it cannot read) and drops rows past retention; the unread count's SSE
push (once per batch) reaches the subscription the real /events route opens
for an owner and not a chatter's; a Master impersonating an owner reads that
owner's feed. No OnlyFans call: the unsend runs against a fake client.

Run: ./venv/bin/python service/tests/test_agency_notifications.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import delete, select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
from _clock_fixtures import (  # noqa: E402
    employee as _employee, event as _event, shift as _shift, time_tracking as _time_tracking, utc_now as _utc_now,
)
import account_health  # noqa: E402
import audit_labels  # noqa: E402
import events  # noqa: E402
import notifications_api  # noqa: E402
import server  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Action, AgencyNotification, Shift  # noqa: E402
from notifications_api import Notice  # noqa: E402

IDS = fx.seed_two_agencies()
A, B = IDS["agency_a_owner"], IDS["agency_b_owner"]
OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
CHATTER_A = fx.login_chatter("chatter_a")


def _rows(agency: str, kind: str | None = None) -> list[AgencyNotification]:
    async def _run():
        async with get_session() as s:
            q = select(AgencyNotification).where(AgencyNotification.agency_user_id == agency)
            if kind is not None:
                q = q.where(AgencyNotification.kind == kind)
            return list((await s.execute(q.order_by(AgencyNotification.id))).scalars().all())
    return asyncio.run(_run())


def _clear() -> None:
    async def _run():
        async with get_session() as s:
            await s.execute(delete(AgencyNotification))
    asyncio.run(_run())


def _put_roles(blob: dict) -> None:
    r = OWNER_A.put("/admin/settings/roles", json=blob)
    assert r.status_code == 200, r.text


# ── The audit hook ──────────────────────────────────────────────────────────

def case_a_roles_save_files_one_row_per_changed_assignment_and_none_when_nothing_changed():
    _clear()
    x = _employee("Xena")
    _put_roles({"assignments": {str(x): "chatter"}})
    rows = _rows(A, "role_changed")
    assert [r.text for r in rows] == ["Xena's role changed from no role to Chatter"], [r.text for r in rows]
    assert rows[0].employee_id == x
    _put_roles({"assignments": {str(x): "chatter"}})
    assert len(_rows(A, "role_changed")) == 1, "a save that changed nothing filed a row"
    _put_roles({"assignments": {str(x): "admin"}, "enforce": False})
    texts = [r.text for r in _rows(A, "role_changed")][1:]
    assert texts == ["Xena's role changed from Chatter to Admin", "Role settings changed: role permissions off"], texts
    assert _rows(B) == [], "another Agency got A's notification"


def case_an_assignment_naming_another_agencys_employee_files_nothing():
    _clear()
    fx.store_blob(A, "roles", {})
    mine, theirs = _employee("Mina"), _employee("Theo", owner="agency_b_owner")
    _put_roles({"assignments": {str(theirs): "chatter", "not-an-id": "chatter"}})
    _put_roles({"assignments": {str(theirs): "admin", str(mine): "chatter"}})
    texts = [r.text for r in _rows(A)]
    assert texts == ["Mina's role changed from no role to Chatter"], f"B's Employee leaked into A's feed: {texts}"
    assert _rows(B) == []


def case_an_employee_setup_files_a_row_only_when_its_role_changes():
    _clear()
    y = _employee("Yuri")
    for role in ("admin", "admin", "team-leader"):
        r = OWNER_A.put(f"/admin/employees/{y}/setup", json={"role_id": role})
        assert r.status_code == 200, r.text
    texts = [r.text for r in _rows(A, "role_changed")]
    assert texts == ["Yuri's role changed from no role to Admin", "Yuri's role changed from Admin to Team Leader"], \
        texts


def case_deactivating_files_once_by_patch_or_delete():
    _clear()
    p, d = _employee("Pat"), _employee("Dee")
    assert OWNER_A.patch(f"/admin/employees/{p}", json={"display_name": "Pat"}).status_code == 200
    assert _rows(A) == [], "a rename filed a deactivation"
    for _ in range(2):
        assert OWNER_A.patch(f"/admin/employees/{p}", json={"is_active": False}).status_code == 200
        assert OWNER_A.delete(f"/admin/employees/{d}").status_code == 200
    rows = _rows(A, "employee_deactivated")
    assert [(r.text, r.employee_id) for r in rows] == [("Pat was deactivated", p), ("Dee was deactivated", d)], \
        [(r.text, r.employee_id) for r in rows]
    # Another owner's DELETE is refused (404) and files nothing.
    q = _employee("Quin")
    assert OWNER_B.delete(f"/admin/employees/{q}").status_code == 404
    assert len(_rows(A)) == 2 and _rows(B) == []


def case_a_chatters_unsend_files_message_unsent_and_the_owners_own_does_not():
    _clear()
    fx.store_blob(A, "roles", {"enforce": False})
    original = server._get_client

    class _Fake:
        def unsend_message(self, *_a, **_k):
            return {"ok": True}
    server._get_client = lambda *_a, **_k: _Fake()
    try:
        head = {"X-Account-Id": IDS["creator_a"]}
        r = CHATTER_A.request("DELETE", "/api/of/v2/messages/555", headers=head, json={"withUserId": 42})
        assert r.status_code == 200, r.text
        r = OWNER_A.request("DELETE", "/api/of/v2/messages/556", headers=head, json={"withUserId": 42})
        assert r.status_code == 200, r.text
    finally:
        server._get_client = original
        fx.store_blob(A, "roles", {})
    rows = _rows(A, "message_unsent")
    assert [r.text for r in rows] == ["chatter_a unsent a message to fan 42 on creator_a"], [r.text for r in rows]
    assert rows[0].account_id == IDS["creator_a"]
    assert notifications_api._row(rows[0])["data"] == {"fan_id": 42, "message_id": 555}


def case_a_kind_switched_off_in_preferences_files_nothing():
    _clear()
    r = OWNER_A.put("/admin/settings/preferences", json={"notifications": {"employee_deactivated": False}})
    assert r.status_code == 200, r.text
    bad = OWNER_A.put("/admin/settings/preferences", json={"notifications": {"session_dead": "no"}})
    assert bad.status_code == 400, bad.text
    try:
        assert OWNER_A.delete(f"/admin/employees/{_employee('Off')}").status_code == 200
        assert _rows(A) == []
    finally:
        assert OWNER_A.put("/admin/settings/preferences", json={}).status_code == 200
    assert OWNER_A.delete(f"/admin/employees/{_employee('On')}").status_code == 200
    assert len(_rows(A, "employee_deactivated")) == 1


# ── Routes, tenancy, unread ────────────────────────────────────────────────

def case_the_list_read_and_read_all_are_the_owners_own_and_chatters_are_refused():
    _clear()
    for n in range(3):
        asyncio.run(notifications_api.notify(A, [Notice("role_changed", f"a{n}")]))
    asyncio.run(notifications_api.notify(B, [Notice("role_changed", "b0")]))
    body = OWNER_A.get("/admin/agency-notifications").json()
    assert [n["text"] for n in body["notifications"]] == ["a2", "a1", "a0"] and body["unread"] == 3, body
    assert [n["text"] for n in OWNER_B.get("/admin/agency-notifications").json()["notifications"]] == ["b0"]
    first = body["notifications"][0]["id"]
    assert OWNER_B.post(f"/admin/agency-notifications/{first}/read").status_code == 404
    assert OWNER_A.post(f"/admin/agency-notifications/{first}/read").json() == {"unread": 2}
    assert OWNER_A.get("/admin/agency-notifications").json()["unread"] == 2
    assert OWNER_A.post("/admin/agency-notifications/read-all").json() == {"unread": 0}
    assert OWNER_B.get("/admin/agency-notifications").json()["unread"] == 1
    assert CHATTER_A.get("/admin/agency-notifications").status_code == 403
    assert _harness.make_client().get("/admin/agency-notifications").status_code == 401
    # Reading files no audit row.
    async def _audited():
        async with get_session() as s:
            return (await s.execute(select(Action.id).where(Action.action.like("%agency-notifications%")))).first()
    assert asyncio.run(_audited()) is None


def _stream_agencies(client) -> frozenset:
    """The `agencies` the real GET /events opens its subscription with for
    `client`'s session (the stream itself is stubbed to end at once)."""
    seen: list[frozenset] = []
    original = server.sse_stream

    async def _capture(_request, _scope, *, agencies, **_kw):
        seen.append(agencies)
        yield ": captured\n\n"
    server.sse_stream = _capture
    try:
        r = client.get("/events")
    finally:
        server.sse_stream = original
    assert r.status_code == 200 and len(seen) == 1, (r.status_code, r.text, seen)
    return seen[0]


def case_the_unread_push_reaches_the_owners_stream_once_per_batch_and_not_its_chatters():
    owner_agencies, chatter_agencies = _stream_agencies(OWNER_A), _stream_agencies(CHATTER_A)
    assert A in chatter_agencies, "the chatter's stream lost its Agency's own events"

    async def _check():
        owner_q = await events.subscribe("all", accounts=frozenset(), agencies=owner_agencies)
        chatter_q = await events.subscribe("all", accounts=frozenset(), agencies=chatter_agencies)
        try:
            async with get_session() as s:
                unread = await notifications_api._unread(s, A)
            two = [Notice("role_changed", "one"), Notice("role_changed", "two")]
            assert await notifications_api.notify(A, two) == 2
            frame = owner_q.get_nowait()
            assert frame["agency_notifications"] == {"unread": unread + 2}, frame
            assert owner_q.empty(), "a batch pushed more than once"
            assert chatter_q.empty(), "a chatter session got the owner's unread count"
        finally:
            await events.unsubscribe("all", owner_q)
            await events.unsubscribe("all", chatter_q)
    asyncio.run(_check())


def case_a_master_impersonating_an_owner_reads_that_owners_feed_and_cannot_mark_it():
    _clear()
    asyncio.run(notifications_api.notify(A, [Notice("role_changed", "for A")]))
    master = fx.login_owner("agency_master")
    r = master.post("/admin/impersonate", json={"user_id": A, "admin_password": os.environ["ADMIN_PASSWORD"]})
    assert r.status_code == 200, r.text
    body = master.get("/admin/agency-notifications").json()
    assert [n["text"] for n in body["notifications"]] == ["for A"] and body["unread"] == 1, body
    assert master.post("/admin/agency-notifications/read-all").status_code == 403, "impersonation is read-only"
    assert OWNER_A.get("/admin/agency-notifications").json()["unread"] == 1


# ── Dead sessions ──────────────────────────────────────────────────────────

def case_a_dead_session_files_once_per_episode_for_its_owner_only():
    _clear()
    acc = IDS["creator_a"]
    assert asyncio.run(account_health.mark_session_dead(acc, "wrong_user"))
    assert not asyncio.run(account_health.mark_session_dead(acc, "wrong_user"))
    rows = _rows(A, "session_dead")
    assert [r.text for r in rows] == ["creator_a was logged out of OnlyFans: relink the creator to resume"], \
        [r.text for r in rows]
    assert _rows(B) == []
    assert asyncio.run(account_health.clear_session_dead(acc))
    assert asyncio.run(account_health.mark_session_dead(acc, "no_session"))
    assert len(_rows(A, "session_dead")) == 2, "a new dead episode filed nothing"
    asyncio.run(account_health.clear_session_dead(acc))
    # The same episode's key twice (two relays racing) files one row.
    at = datetime(2026, 1, 1)
    for _ in range(2):
        asyncio.run(notifications_api.notify_session_dead(acc, "wrong_user", at))
    assert len(_rows(A, "session_dead")) == 3


# ── The clock-in sweep ─────────────────────────────────────────────────────

def case_the_sweep_files_a_missed_clock_in_once_and_skips_who_clocked_or_may_not():
    _clear()
    now = _utc_now()
    late, clocked, early, unroled = (_employee(n) for n in ("Late", "Clocked", "Early", "Unroled"))
    fx.store_blob(A, "roles", {"assignments": {str(e): "chatter" for e in (late, clocked, early)}})
    _time_tracking(OWNER_A, {"enabled": True, "role_ids": ["chatter"], "auto_clock_out_minutes": 60})
    acc = IDS["creator_a"]
    running = _shift(now - timedelta(minutes=30), now + timedelta(hours=1),
                     [(late, acc), (clocked, acc), (unroled, acc)])
    _shift(now - timedelta(minutes=5), now + timedelta(hours=1), [(early, acc)])
    _shift(now - timedelta(hours=3), now - timedelta(hours=2), [(late, acc)])  # over: not missed now
    _event(clocked, now - timedelta(minutes=40))
    try:
        assert asyncio.run(notifications_api.tick(now)) == 1
        assert asyncio.run(notifications_api.tick(now + timedelta(minutes=5))) == 0, "the sweep filed twice"
        rows = _rows(A, "clock_in_missed")
        assert [(r.employee_id, notifications_api._row(r)["data"]["shift_id"]) for r in rows] == [(late, running)]
        assert rows[0].text.startswith("Late has not clocked in for the "), rows[0].text
        # A daily Shift that began yesterday runs again now, except on a
        # cancelled local date; one in an unknown zone is skipped, not fatal.
        daily, cancelled, broken = (_employee(n) for n in ("Daily", "Cancelled", "Broken"))
        everyone = (late, clocked, early, daily, cancelled, broken)
        fx.store_blob(A, "roles", {"assignments": {str(e): "chatter" for e in everyone}})
        yday = now - timedelta(days=1, minutes=30)
        every_day = "[1, 2, 3, 4, 5, 6, 7]"
        _edit_shift(_shift(yday, yday + timedelta(hours=2), [(daily, acc)]), repeat_days=every_day)
        _edit_shift(_shift(yday, yday + timedelta(hours=2), [(cancelled, acc)]), repeat_days=every_day,
                    cancelled_dates=f'["{now.date().isoformat()}"]')
        _edit_shift(_shift(now - timedelta(minutes=30), now + timedelta(hours=1), [(broken, acc)]), tz="Not/AZone")
        assert asyncio.run(notifications_api.tick(now)) == 1
        assert [r.employee_id for r in _rows(A, "clock_in_missed")] == [late, daily]
        # Time tracking off: nothing to miss.
        _time_tracking(OWNER_A, {"enabled": False})
        _clear()
        assert asyncio.run(notifications_api.tick(now)) == 0
    finally:
        fx.store_blob(A, "roles", {})
        _time_tracking(OWNER_A, {"enabled": False})


def _edit_shift(shift_id: int, **values) -> None:
    async def _run():
        async with get_session() as s:
            sh = await s.get(Shift, shift_id)
            for k, v in values.items():
                setattr(sh, k, v)
    asyncio.run(_run())


def case_the_sweep_drops_rows_past_retention():
    _clear()
    now = datetime(2026, 6, 1)

    async def _seed():
        async with get_session() as s:
            for days, text in ((91, "old"), (89, "recent")):
                s.add(AgencyNotification(agency_user_id=A, kind="role_changed", text=text,
                                         created_at=now - timedelta(days=days)))
    asyncio.run(_seed())
    asyncio.run(notifications_api.tick(now))
    assert [r.text for r in _rows(A)] == ["recent"]


# ── Audit log: names and dates (6.16) ──────────────────────────────────────

def case_action_label_names_known_actions_and_leaves_the_rest():
    label = audit_labels.action_label
    assert label("PUT /admin/settings/roles") == "Changed role settings"
    assert label("PUT /admin/settings/sales") == "Saved settings"
    assert label("DELETE /admin/employees/12") == "Deactivated an employee"
    assert label("POST /admin/employees/12/2fa/reset") == "Reset an employee's 2FA"
    assert label("DELETE /api/of/v2/messages/99") == "Unsent a message"
    assert label("DELETE /api/of/v2/messages/queue/99") == "Unsent a mass message"
    assert label("clock.auto_out") == "Clocked out for inactivity"
    assert label("POST /admin/something-new") is None
    assert label("DELETE /admin/employees/12/extra") is None


def case_the_audit_log_filters_by_from_and_to_and_labels_rows():
    emp = _employee("Auditee")

    async def _seed():
        async with get_session() as s:
            for day, action in ((1, "DELETE /admin/employees/1"), (2, "clock.in"), (3, "POST /admin/zzz")):
                s.add(Action(employee_id=emp, action=action, at=datetime(2026, 3, day, 12)))
    asyncio.run(_seed())

    def got(**params):
        r = OWNER_A.get("/admin/audit", params={"employee_id": emp, **params})
        assert r.status_code == 200, r.text
        return [(a["action"], a["label"]) for a in r.json()["actions"]]
    assert got() == [("POST /admin/zzz", None), ("clock.in", "Clocked in"),
                     ("DELETE /admin/employees/1", "Deactivated an employee")]
    assert [a for a, _ in got(**{"from": "2026-03-02"})] == ["POST /admin/zzz", "clock.in"]
    assert [a for a, _ in got(to="2026-03-02")] == ["clock.in", "DELETE /admin/employees/1"], "a date-only `to` includes its day"
    assert [a for a, _ in got(**{"from": "2026-03-02T00:00:00Z", "to": "2026-03-02T12:00:00Z"})] == []
    assert [a for a, _ in got(**{"from": "2026-03-02T13:00:00+02:00", "to": "2026-03-03T00:00:00Z"})] == ["clock.in"]
    # The UI sends Date.toISOString() bounds (milliseconds, Z).
    assert [a for a, _ in got(**{"from": "2026-03-02T11:00:00.000Z", "to": "2026-03-03T00:00:00.000Z"})] == ["clock.in"]
    assert OWNER_A.get("/admin/audit", params={"from": "yesterday"}).status_code == 422
    # The filter never widens the owner's scope: B sees none of A's rows.
    assert OWNER_B.get("/admin/audit", params={"employee_id": emp, "from": "2026-01-01"}).json()["actions"] == []


_harness.run()
