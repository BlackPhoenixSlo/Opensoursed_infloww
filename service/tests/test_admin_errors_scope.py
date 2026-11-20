#!/usr/bin/env python3
"""/admin/errors (service/diag_api.py) is Agency-scoped, over HTTP with real session cookies
(the two-Agency bench, service/tests/_agency_fixtures.py).

A row belongs to the Creator it names (`account_id`), else to the Employee it names; a row
naming neither is the Master's (`users.is_admin`, the instance owner as `auth.require_master`).

  • case_reads_own_agency_only: each owner reads its own Creator's and Employees' rows, never
    the other Agency's or an unattributed one; a chatter reads its Creators'; the Master all.
  • case_clear_deletes_own_only: an owner's Clear deletes only its own rows.
  • case_chatter_cannot_clear: a chatter session's Clear is 403 and deletes nothing.
  • case_no_session_401: no session reads and clears nothing.
  • case_count_is_total: `count` is every matching row, not the page (`limit`).
  • case_post_attribution: a reported error keeps only the Creator/Employee the reporter owns
    (header or body); another Agency's is dropped, so it never lands in that Agency's list.
  • case_server_error_attribution: an unhandled 500's X-Account-Id is kept only when the
    principal owns it.

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
from db.models import AppError  # noqa: E402

IDS = fx.seed_two_agencies()
A, B = IDS["creator_a"], IDS["creator_b"]
PATH = "/admin/errors"


def _owner_emp(name: str) -> int:
    return asyncio.run(employees.get_owner_employee_id(SimpleNamespace(id=IDS[name], username=name)))


EMP_A = _owner_emp("agency_a_owner")
EMP_B = _owner_emp("agency_b_owner")
OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
MASTER = fx.login_owner("agency_master")
CHATTER_A = fx.login_chatter("chatter_a")


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
         ("a-emp", None, EMP_A), ("b-emp", None, EMP_B)]


def _seen(client) -> set[str]:
    r = client.get(PATH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == len(body["list"])
    return {row["message"] for row in body["list"]}


def case_reads_own_agency_only():
    _seed(BENCH)
    assert _seen(OWNER_A) == {"a-creator", "a-emp"}
    assert _seen(OWNER_B) == {"b-creator", "b-emp"}
    assert _seen(CHATTER_A) == {"a-creator"}, "a chatter: its Creators' rows only"
    assert _seen(MASTER) == {m for m, _a, _e in BENCH}, "the Master: every row, unattributed included"


def case_clear_deletes_own_only():
    _seed(BENCH)
    r = OWNER_A.delete(PATH + "?since_hours=24")
    assert r.status_code == 200 and r.json()["deleted"] == 2, r.text
    assert {e.message for e in _stored()} == {"b-creator", "orphan", "b-emp"}
    assert _seen(OWNER_B) == {"b-creator", "b-emp"}


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
    _seed([(f"a{i}", A, None) for i in range(60)] + [("b", B, None)])
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
    assert got["chatter"] == (A, None), "a chatter may not name Agency B's Employee"
    assert _seen(OWNER_B) == set()
    assert _seen(OWNER_A) == {"spoof", "hdr", "chatter"}
    # A chatter on a page with no Creator picked: its own Mirror Employee, so its owner still reads it.
    r = CHATTER_A.post(PATH, json={"message": "bare"})
    assert r.json()["ok"], r.text
    bare = {e.message: (e.account_id, e.employee_id) for e in _stored()}["bare"]
    assert bare[0] is None and bare[1] is not None, bare
    assert "bare" in _seen(OWNER_A) and "bare" not in _seen(OWNER_B)


async def _boom():
    raise RuntimeError("boom")

server.app.add_api_route("/admin/__errors_scope_boom", _boom, methods=["GET"])


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


_harness.run()
