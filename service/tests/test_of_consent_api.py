#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import os  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
import consent_notices  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, Action, Chatter, ChatterUser, Employee, OfConsentAccept, User, UserAccount,
)

PW = "secretpw"
A1, A_REQ, B1 = "772001", "772002", "772011"
U: dict[str, str] = {}


async def _user(username: str, *, is_admin: bool = False) -> str:
    uid = uuid.uuid4().hex
    async with get_session() as s:
        s.add(User(id=uid, username=username, password=PW, is_admin=is_admin))
    return uid


fx._sandbox_sessions_tree()


async def _account(account_id: str, *owner_ids: str) -> None:
    (account_registry.ACCOUNTS_DIR / account_id).mkdir()
    async with get_session() as s:
        s.add(Account(id=account_id, nickname=f"acct{account_id}"))
        for uid in owner_ids:
            s.add(UserAccount(user_id=uid, account_id=account_id))


async def _seed() -> None:
    U["owner"] = await _user("consent_owner")
    U["other"] = await _user("consent_other")
    U["founder"] = await _user("consent_founder", is_admin=True)
    await _account(A1, U["owner"], U["founder"])
    await _account(A_REQ, U["owner"])
    await _account(B1, U["other"])
    cid = uuid.uuid4().hex
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(Chatter(id=cid, username="consent_chatter", password=PW, display_name="C",
                      created_at=now, last_seen_at=now))
    async with get_session() as s:
        s.add(ChatterUser(chatter_id=cid, user_id=U["owner"], created_at=now))
    assert await consent_notices.flag(A_REQ, "NC") == 1

asyncio.run(_seed())


def _login(username: str):
    c = _harness.make_client()
    r = c.post("/auth/login", json={"username": username, "password": PW})
    assert r.status_code == 200, f"login {username}: {r.status_code} {r.text}"
    return c


def _chatter():
    c = _harness.make_client()
    r = c.post("/chatter/login", json={"username": "consent_chatter", "password": PW})
    assert r.status_code == 200, f"chatter login: {r.status_code} {r.text}"
    return c


async def _rows(account_id: str) -> list[OfConsentAccept]:
    async with get_session() as s:
        return list((await s.execute(select(OfConsentAccept).where(
            OfConsentAccept.account_id == account_id).order_by(OfConsentAccept.id))).scalars())


def _n(account_id: str) -> int:
    return len(asyncio.run(_rows(account_id)))


def case_owner_turns_it_on_and_off_each_change_one_row_with_who_and_when():
    c = _login("consent_owner")
    g = c.get(f"/admin/of-consent/{A1}").json()
    assert (g["auto_accept"], g["changed"]) == (False, None), g
    t0 = datetime.utcnow() - timedelta(seconds=1)
    r = c.put(f"/admin/of-consent/{A1}", json={"auto_accept": True})
    assert r.status_code == 200, r.text
    body = r.json()
    rows = asyncio.run(_rows(A1))
    assert len(rows) == 1 and rows[0].enabled is True, rows
    row = rows[0]

    async def _emp():
        async with get_session() as s:
            return (await s.execute(select(Employee).where(Employee.id == row.employee_id))).scalar_one()
    emp = asyncio.run(_emp())
    assert (row.user_id, row.username, emp.user_id) == (U["owner"], "consent_owner", U["owner"]), row
    assert t0 <= row.at <= datetime.utcnow(), row.at
    assert body["auto_accept"] is True and "show" not in body, body
    assert body["changed"] == {"enabled": True, "user_id": U["owner"], "username": "consent_owner",
                               "employee_id": row.employee_id, "at": row.at.isoformat() + "Z"}, body
    assert c.get(f"/admin/of-consent/{A1}").json() == body

    async def _actions():
        async with get_session() as s:
            return list((await s.execute(select(Action).where(
                Action.action == f"PUT /admin/of-consent/{A1}"))).scalars())
    acts = asyncio.run(_actions())
    assert acts and acts[-1].employee_id == row.employee_id, [(a.employee_id, a.payload_json) for a in acts]

    assert c.put(f"/admin/of-consent/{A1}", json={"auto_accept": True}).status_code == 200
    assert _n(A1) == 1, "the same value again wrote a row"
    r = c.put(f"/admin/of-consent/{A1}", json={"auto_accept": False})
    assert r.status_code == 200 and r.json()["auto_accept"] is False, r.text
    rows = asyncio.run(_rows(A1))
    assert [x.enabled for x in rows] == [True, False], rows
    assert r.json()["changed"]["enabled"] is False and r.json()["auto_accept"] is False, r.json()


def case_required_follows_the_consent_notice():
    c = _login("consent_owner")
    g = c.get(f"/admin/of-consent/{A_REQ}").json()
    assert (g["required"], g["auto_accept"]) == (True, False), g
    g = c.get(f"/admin/of-consent/{A1}").json()
    assert g["required"] is False and "show" not in g, g
    assert asyncio.run(consent_notices.clear(A_REQ)) == 1
    g = c.get(f"/admin/of-consent/{A_REQ}").json()
    assert (g["required"], g["auto_accept"]) == (False, False), g
    assert asyncio.run(consent_notices.flag(A_REQ, "NC")) == 1


def case_who_may_save():
    impersonating = _login("consent_founder")
    r = impersonating.post("/admin/impersonate",
                           json={"user_id": U["owner"], "admin_password": os.environ["ADMIN_PASSWORD"]})
    assert r.status_code == 200, r.text
    before = _n(A_REQ)
    for who, c, aid, want in (("anonymous", _harness.make_client(), A_REQ, 401),
                              ("chatter", _chatter(), A_REQ, 403),
                              ("other owner", _login("consent_other"), A_REQ, 403),
                              ("impersonation", impersonating, A_REQ, 403)):
        r = c.put(f"/admin/of-consent/{aid}", json={"auto_accept": True})
        assert r.status_code == want, (who, r.status_code, r.text)
    assert _n(A_REQ) == before, "a refused save wrote a row"
    assert _login("consent_other").get(f"/admin/of-consent/{A_REQ}").status_code == 403


def case_a_bad_body_is_422():
    c = _login("consent_owner")
    for body in ({}, {"auto_accept": "yes"}, {"auto_accept": 1}):
        assert c.put(f"/admin/of-consent/{A_REQ}", json=body).status_code == 422, body


if __name__ == "__main__":
    _harness.run()
