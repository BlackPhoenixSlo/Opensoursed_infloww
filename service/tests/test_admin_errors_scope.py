#!/usr/bin/env python3
"""/admin/errors (service/diag_api.py) is Agency-scoped, over HTTP with real session cookies
(the two-Agency bench, service/tests/_agency_fixtures.py).

A row belongs to the Employee that filed it (W30 F2), never to the Creator it names: an owner
reads its Agency's Employees' rows (its own + its chatters' Mirror rows), a chatter only its
own; a row naming no Employee is the Master's (`users.is_admin`, as `auth.require_master`).

  • case_reads_own_agency_only: each owner reads its own Employees' rows, never the other
    Agency's, a Creator-only or an unattributed one; a chatter its own; the Master all.
  • case_shared_creator_stays_with_the_reporter: two Agencies sharing a Creator read (and
    Clear) only their own reports on it, over the real POST too.
  • case_chatters_on_one_creator_see_only_their_own: two chatters of one Agency on one
    Creator never read each other's (or the owner's) reports; the owner reads all three.
  • case_clear_deletes_own_only: an owner's Clear deletes only its own rows.
  • case_chatter_cannot_clear: a chatter session's Clear is 403 and deletes nothing.
  • case_no_session_401: no session reads and clears nothing.
  • case_count_is_total: `count` is every matching row, not the page (`limit`).
  • case_post_attribution: a reported error keeps only the Creator/Employee the reporter owns
    (header or body); another Agency's is dropped, so it never lands in that Agency's list.
  • case_server_error_attribution: an unhandled 500's X-Account-Id is kept only when the
    principal owns it.
  • case_server_error_hides_sql_parameters: a failed statement's bound values (a 2FA seed)
    never reach the stored row (engine hide_parameters, W30 F9).

Run: ./venv/bin/python service/tests/test_admin_errors_scope.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from sqlalchemy import delete, select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import employees  # noqa: E402
import server  # noqa: E402 — mounts the routes
from db.engine import get_session  # noqa: E402
from datetime import datetime  # noqa: E402

import accounts as account_registry  # noqa: E402
from db.models import AppError, Account, Chatter, ChatterUser, UserAccount  # noqa: E402

IDS = fx.seed_two_agencies()
A, B = IDS["creator_a"], IDS["creator_b"]
SHARED = "1000099"     # a Creator both Agencies hold
PATH = "/admin/errors"


async def _seed_shared_and_second_chatter() -> str:
    """Creator SHARED linked to both owners; `chatter_a2`, a second chatter of Agency A."""
    (account_registry.ACCOUNTS_DIR / SHARED).mkdir()
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(Account(id=SHARED, nickname="shared", color="#aaaaaa"))
        s.add(Chatter(id="chatter-a2-id", username="chatter_a2", password=fx.PASSWORD,
                      display_name="chatter_a2", color="#bbbbbb", created_at=now, last_seen_at=now))
    async with get_session() as s:
        for owner in ("agency_a_owner", "agency_b_owner"):
            s.add(UserAccount(user_id=IDS[owner], account_id=SHARED))
        s.add(ChatterUser(chatter_id="chatter-a2-id", user_id=IDS["agency_a_owner"], created_at=now))
    return "chatter-a2-id"


IDS["chatter_a2"] = asyncio.run(_seed_shared_and_second_chatter())


def _mirror(chatter: str, owner: str) -> int:
    return asyncio.run(employees.get_or_create_mirror_employee(
        IDS[chatter], IDS[owner], display_name=chatter, color=None))


def _owner_emp(name: str) -> int:
    return asyncio.run(employees.get_owner_employee_id(SimpleNamespace(id=IDS[name], username=name)))


EMP_A = _owner_emp("agency_a_owner")
EMP_B = _owner_emp("agency_b_owner")
OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
MASTER = fx.login_owner("agency_master")
CHATTER_A = fx.login_chatter("chatter_a")
CHATTER_A2 = fx.login_chatter("chatter_a2")
CHATTER_B = fx.login_chatter("chatter_b")
CHATTER_AB = fx.login_chatter("chatter_ab")
MIRROR_A = _mirror("chatter_a", "agency_a_owner")
MIRROR_A2 = _mirror("chatter_a2", "agency_a_owner")
MIRROR_B = _mirror("chatter_b", "agency_b_owner")


def _seed(rows: list[tuple[str, str | None, int | None]]) -> None:
    """Fresh table holding `rows` of (message, account_id, employee_id)."""
    async def go():
        async with get_session() as s:
            await s.execute(delete(AppError))
            for msg, aid, emp in rows:
                s.add(AppError(source="browser", kind="error", message=msg, account_id=aid, employee_id=emp))
            await s.commit()
    asyncio.run(go())


def _stored() -> list[AppError]:
    async def go():
        async with get_session() as s:
            return list((await s.execute(select(AppError).order_by(AppError.id))).scalars())
    return asyncio.run(go())


BENCH = [("a-creator", A, None), ("b-creator", B, None), ("orphan", None, None),
         ("a-emp", None, EMP_A), ("b-emp", None, EMP_B), ("a-chatter", A, MIRROR_A)]


def _seen(client) -> set[str]:
    r = client.get(PATH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == len(body["list"])
    return {row["message"] for row in body["list"]}


def case_reads_own_agency_only():
    _seed(BENCH)
    assert _seen(OWNER_A) == {"a-emp", "a-chatter"}
    assert _seen(OWNER_B) == {"b-emp"}
    assert _seen(CHATTER_A) == {"a-chatter"}, "a chatter: its own rows only"
    assert _seen(MASTER) == {m for m, _a, _e in BENCH}, "the Master: every row, unattributed included"


def case_shared_creator_stays_with_the_reporter():
    _seed([("s-by-a-owner", SHARED, EMP_A), ("s-by-b-chatter", SHARED, MIRROR_B)])
    assert _seen(OWNER_A) == {"s-by-a-owner"}
    assert _seen(OWNER_B) == {"s-by-b-chatter"}
    assert _seen(CHATTER_B) == {"s-by-b-chatter"}
    r = OWNER_A.delete(PATH)
    assert r.status_code == 200 and r.json()["deleted"] == 1, r.text
    assert {e.message for e in _stored()} == {"s-by-b-chatter"}, "A's Clear left B's report"
    _seed([])
    r = CHATTER_B.post(PATH, json={"message": "real", "stack": "at B"}, headers={"X-Account-Id": SHARED})
    assert r.json()["ok"], r.text
    assert [(e.account_id, e.employee_id) for e in _stored()] == [(SHARED, MIRROR_B)]
    assert _seen(OWNER_A) == set() and _seen(OWNER_B) == {"real"}


def case_chatters_on_one_creator_see_only_their_own():
    _seed([("by-a1", A, MIRROR_A), ("by-a2", A, MIRROR_A2), ("by-owner", A, EMP_A)])
    assert _seen(CHATTER_A) == {"by-a1"}
    assert _seen(CHATTER_A2) == {"by-a2"}
    assert _seen(OWNER_A) == {"by-a1", "by-a2", "by-owner"}
    assert _seen(OWNER_B) == set()


def case_clear_deletes_own_only():
    _seed(BENCH)
    r = OWNER_A.delete(PATH + "?since_hours=24")
    assert r.status_code == 200 and r.json()["deleted"] == 2, r.text
    assert {e.message for e in _stored()} == {"a-creator", "b-creator", "orphan", "b-emp"}
    assert _seen(OWNER_B) == {"b-emp"}


def case_chatter_cannot_clear():
    _seed(BENCH)
    r = CHATTER_A.delete(PATH + "?since_hours=24")
    assert r.status_code == 403, r.text
    assert len(_stored()) == len(BENCH)


def case_no_session_401():
    _seed(BENCH)
    anon = _harness.make_client()
    assert anon.get(PATH).status_code == 401
    assert anon.delete(PATH).status_code == 401
    assert len(_stored()) == len(BENCH)


def case_count_is_total():
    _seed([(f"a{i}", A, EMP_A) for i in range(60)] + [("b", B, EMP_B)])
    body = OWNER_A.get(PATH + "?limit=50").json()
    assert body["count"] == 60 and len(body["list"]) == 50, (body["count"], len(body["list"]))


def case_post_attribution():
    _seed([])
    r = OWNER_A.post(PATH, json={"message": "spoof", "account_id": B, "employee_id": EMP_B})
    assert r.json()["ok"], r.text
    r = OWNER_A.post(PATH, json={"message": "hdr"}, headers={"X-Account-Id": A})
    assert r.json()["ok"], r.text
    r = CHATTER_A.post(PATH, json={"message": "chatter"}, headers={"X-Account-Id": A, "X-Employee-Id": str(EMP_B)})
    assert r.json()["ok"], r.text
    got = {e.message: (e.account_id, e.employee_id) for e in _stored()}
    assert got["spoof"] == (None, EMP_A), "another Agency's Creator/Employee dropped; the owner's own Employee"
    assert got["hdr"] == (A, EMP_A)
    assert got["chatter"] == (A, MIRROR_A), "a chatter may not name Agency B's Employee: its own instead"
    assert _seen(OWNER_B) == set()
    assert _seen(OWNER_A) == {"spoof", "hdr", "chatter"}
    # A chatter on a page with no Creator picked: its own Mirror Employee, so its owner still reads it.
    r = CHATTER_A.post(PATH, json={"message": "bare"})
    assert r.json()["ok"], r.text
    bare = {e.message: (e.account_id, e.employee_id) for e in _stored()}["bare"]
    assert bare == (None, MIRROR_A), bare
    assert "bare" in _seen(OWNER_A) and "bare" not in _seen(OWNER_B)
    # A chatter of two Agencies naming no Employee: the row cannot be placed, the Master's alone.
    r = CHATTER_AB.post(PATH, json={"message": "two"})
    assert r.json()["ok"], r.text
    assert {e.message: (e.account_id, e.employee_id) for e in _stored()}["two"] == (None, None)
    assert "two" not in _seen(OWNER_A) | _seen(OWNER_B) and "two" in _seen(MASTER)


async def _boom():
    raise RuntimeError("boom")

server.app.add_api_route("/admin/__errors_scope_boom", _boom, methods=["GET"])

SEED = "JBSWY3DPEHPK3PXPSEEDVALUE"


async def _boom_sql():
    from sqlalchemy import text
    async with get_session() as s:
        await s.execute(text("SELECT * FROM no_such_table WHERE seed = :seed"), {"seed": SEED})

server.app.add_api_route("/admin/__errors_scope_boom_sql", _boom_sql, methods=["GET"])


def case_perflog_recent_is_master_only():
    """Every Agency's perf rows: an owner or chatter who is not the Master is refused."""
    assert OWNER_A.get("/admin/perflog/recent").status_code == 403
    assert CHATTER_A.get("/admin/perflog/recent").status_code in (401, 403)


def case_server_error_attribution():
    _seed([])
    for hdr in (A, B):
        try:
            OWNER_A.get("/admin/__errors_scope_boom", headers={"X-Account-Id": hdr})
        except RuntimeError:
            pass  # TestClient re-raises; the middleware has already stored the row
    got = sorted((e.account_id or "") for e in _stored() if e.source == "server")
    assert got == ["", A], got
    assert _seen(OWNER_B) == set(), "a 500 naming Agency B's Creator never reaches B"


def case_server_error_hides_sql_parameters():
    _seed([])
    try:
        OWNER_A.get("/admin/__errors_scope_boom_sql")
    except Exception:
        pass  # TestClient re-raises; the middleware has already stored the row
    rows = [e for e in _stored() if e.source == "server"]
    assert len(rows) == 1 and "no_such_table" in rows[0].message, [(e.kind, e.message) for e in rows]
    assert SEED not in rows[0].message and SEED not in (rows[0].stack or ""), rows[0].message


_harness.run()
