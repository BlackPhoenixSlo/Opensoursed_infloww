#!/usr/bin/env python3
"""OnlyFans' "Consent not accepted" as a pinned agency notification
(service/consent_notices.py + notifications_api.PINNED_KIND).

The OF answers are fakes handed to `consent_notices.observe` as
`OFClient._http_call` hands them (status, url, body); the feed is read and
dismissed over HTTP with real owner session cookies from the shared
two-Agency fixture: a consent refusal files one row per owner, the read and
read-all refuse / skip it, the retention sweep keeps it, a /users/me
approval or an accepted media send clears it, a text-only send does not,
and an Agency that unlinks the Creator no longer sees it nor counts it, in
any unread count (the read hides it, never deletes; the unlink / delete
routes do, the unlink before it commits, the delete and a clear for every
Agency). No state
in memory: a flag or clear lost to a race or a failed write is redone by the
next verdict, and an owner linked after the flag gets the row on the next.

Run: ./venv/bin/python service/tests/test_consent_notices.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import delete, select, update  # noqa: E402

import os  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
import consent_notices as cn  # noqa: E402
import notifications_api  # noqa: E402
import server  # noqa: E402,F401 — mounts the routes
from db.engine import get_session  # noqa: E402
from db.models import AgencyNotification, UserAccount  # noqa: E402
from notifications_api import Notice  # noqa: E402

IDS = fx.seed_two_agencies()
A, B = IDS["agency_a_owner"], IDS["agency_b_owner"]
ACC = IDS["creator_a"]
OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
MASTER = fx.login_owner("agency_master")
OF = "https://onlyfans.com/api2/v2"
CONSENT_400 = json.dumps({"error": {"code": 0, "message": "Consent not accepted"}})


class _R:
    def __init__(self, status: int, body) -> None:
        self.status_code = status
        self.text = body if isinstance(body, str) else json.dumps(body)


def _observe(*calls) -> None:
    """Each (method, url, body, response) through observe on a running loop, then its scheduled work."""
    async def _run():
        for method, url, body, r in calls:
            cn.observe(ACC, method, url, body, r)
            for _ in range(20):
                await asyncio.sleep(0.01)
    asyncio.run(_run())


def _rows(agency: str | None = None) -> list[AgencyNotification]:
    async def _run():
        async with get_session() as s:
            q = select(AgencyNotification).where(AgencyNotification.kind == cn.KIND)
            if agency:
                q = q.where(AgencyNotification.agency_user_id == agency)
            return list((await s.execute(q)).scalars().all())
    return asyncio.run(_run())


def _reset() -> None:
    async def _run():
        async with get_session() as s:
            await s.execute(delete(AgencyNotification))
    asyncio.run(_run())


def _refuse_send() -> None:
    _observe(("POST", f"{OF}/messages/queue", {"text": "hi", "mediaFiles": [1]}, _R(400, CONSENT_400)))


def case_verdicts():
    me = lambda body, st=200: cn.verdict("GET", f"{OF}/users/me", None, _R(st, body))  # noqa: E731
    assert me({"needConsent": True, "needConsentState": "NC", "consentStatus": None}) == (True, "NC")
    assert me({"needConsent": True, "consentStatus": "approved"}) == (False, None)
    assert me({"needConsent": False}) == (False, None)
    assert me({"id": 1}) == (None, None) and me(None) == (None, None)
    assert me({"needConsent": True}, 500) == (None, None)
    post = lambda url, body, st, txt="{}": cn.verdict("POST", url, body, _R(st, txt))[0]  # noqa: E731
    assert post(f"{OF}/messages/queue", {"mediaFiles": [1]}, 400, CONSENT_400) is True
    assert post(f"{OF}/chats/5/messages", {}, 400, CONSENT_400) is True, "any write's refusal flags"
    assert post(f"{OF}/chats/5/messages", {"mediaFiles": [1]}, 200) is False
    assert post(f"{OF}/messages/queue", {"mediaFiles": [1]}, 200) is False
    assert post(f"{OF}/chats/5/messages", {"mediaFiles": []}, 200) is None, "a text send says nothing"
    assert post(f"{OF}/posts", {"mediaFiles": [1]}, 200) is None
    assert post(f"{OF}/messages/queue", {"mediaFiles": [1]}, 400, '{"error":{"message":"other"}}') is None
    assert cn.verdict("GET", f"{OF}/chats", None, _R(400, CONSENT_400)) == (None, None)

    class _NoBody:  # a GET of anything but /users/me, or a 2xx write, never reads the body
        status_code = 200

        @property
        def text(self):
            raise AssertionError("body read")
    assert cn.verdict("GET", f"{OF}/chats", None, _NoBody()) == (None, None)
    assert cn.verdict("POST", f"{OF}/chats/5/messages", {"mediaFiles": [1]}, _NoBody()) == (False, None)
    assert "Ava: OnlyFans needs a signed consent form (NC law)" in cn.text_for("Ava", "NC")
    assert "(NC/AL law)" in cn.text_for("Ava", None) and "onlyfans.com/my/consent-form" in cn.text_for("Ava", None)


def case_a_refused_send_files_one_pinned_row_per_owner_and_only_once():
    _reset()
    _refuse_send()
    _refuse_send()
    rows = _rows()
    assert [(r.agency_user_id, r.account_id) for r in rows] == [(A, ACC)], [(r.agency_user_id, r.account_id) for r in rows]
    assert "OnlyFans needs a signed consent form (NC/AL law)" in rows[0].text, rows[0].text
    body = OWNER_A.get("/admin/agency-notifications").json()
    assert [n["kind"] for n in body["pinned"]] == [cn.KIND] and body["unread"] == 1, body
    assert all(n["kind"] != cn.KIND for n in body["notifications"]), "the pinned row is also paged"
    assert OWNER_B.get("/admin/agency-notifications").json()["pinned"] == [], "another Agency saw it"


def case_it_cannot_be_read_dismissed_or_pruned():
    _reset()
    _refuse_send()
    asyncio.run(notifications_api.notify(A, [Notice("role_changed", "news")]))
    pin = OWNER_A.get("/admin/agency-notifications").json()["pinned"][0]["id"]
    r = OWNER_A.post(f"/admin/agency-notifications/{pin}/read")
    assert r.status_code == 409, (r.status_code, r.text)
    assert OWNER_A.post("/admin/agency-notifications/read-all").json() == {"unread": 1}, "read-all read it"
    assert _rows(A)[0].read_at is None

    async def _age():
        async with get_session() as s:
            await s.execute(update(AgencyNotification).values(created_at=datetime.utcnow() - timedelta(days=400)))
    asyncio.run(_age())
    asyncio.run(notifications_api.tick())
    assert len(_rows(A)) == 1, "the retention sweep pruned a pinned row"


def case_users_me_flags_with_its_state_and_its_approval_clears():
    _reset()
    _observe(("GET", f"{OF}/users/me", None, _R(200, {"id": 1, "needConsent": True, "needConsentState": "AL"})))
    rows = _rows(A)
    assert len(rows) == 1 and "(AL law)" in rows[0].text and json.loads(rows[0].data_json)["state"] == "AL"
    _observe(("GET", f"{OF}/users/me", None, _R(200, {"needConsent": True, "consentStatus": "approved"})))
    assert _rows() == [] and OWNER_A.get("/admin/agency-notifications").json()["pinned"] == []
    _observe(("GET", f"{OF}/users/me", None, _R(200, {"id": 1})))
    assert _rows() == [], "a /users/me without the fields flagged"


def case_an_accepted_media_send_clears_and_a_text_send_does_not():
    _reset()
    _refuse_send()
    _observe(("POST", f"{OF}/chats/9/messages", {"text": "hi", "mediaFiles": []}, _R(200, {"id": 1})))
    assert len(_rows()) == 1, "a text-only send cleared it"
    _observe(("POST", f"{OF}/chats/9/messages", {"text": "hi", "mediaFiles": [7]}, _R(200, {"id": 2})))
    assert _rows() == [], "an accepted media send left it"


async def _link(user: str, on: bool):
    async with get_session() as s:
        if on:
            s.add(UserAccount(user_id=user, account_id=ACC))
        else:
            await s.execute(delete(UserAccount).where(UserAccount.user_id == user, UserAccount.account_id == ACC))


async def _linked(user: str) -> bool:
    async with get_session() as s:
        return (await s.execute(select(UserAccount.user_id).where(
            UserAccount.user_id == user, UserAccount.account_id == ACC))).first() is not None


def case_an_unlinked_creator_is_hidden_by_the_read_never_deleted():
    _reset()
    _refuse_send()
    asyncio.run(_link(A, False))
    try:
        for _ in range(2):
            body = OWNER_A.get("/admin/agency-notifications").json()
            assert body["pinned"] == [] and body["unread"] == 0, body
        assert OWNER_A.post("/admin/agency-notifications/read-all").json() == {"unread": 0}, "read-all counted it"
        pushed = []
        real = notifications_api._push
        notifications_api._push = lambda agency, unread: pushed.append((agency, unread))
        try:
            asyncio.run(notifications_api.push_unread([A]))
        finally:
            notifications_api._push = real
        assert pushed == [(A, 0)], f"the SSE push counted it: {pushed}"
        assert len(_rows(A)) == 1, "the GET deleted a row"
    finally:
        asyncio.run(_link(A, True))
    assert [n["account_id"] for n in OWNER_A.get("/admin/agency-notifications").json()["pinned"]] == [ACC]


def case_the_revoke_route_deletes_the_agencys_row():
    _reset()
    _refuse_send()
    pw = os.environ["ADMIN_PASSWORD"]
    r = MASTER.request("DELETE", f"/admin/users/{A}/accounts/{ACC}", json={"admin_password": pw})
    assert r.status_code == 200, r.text
    try:
        assert _rows() == [], "an unlinked Agency kept its consent row"
    finally:
        asyncio.run(_link(A, True))   # the grant route wants a registry meta.json the fixture lacks
    _refuse_send()
    assert len(_rows(A)) == 1, "re-linked, a new refusal must file again"


def case_a_failed_drop_leaves_the_revoke_undone_and_retryable():
    _reset()
    _refuse_send()
    pw = os.environ["ADMIN_PASSWORD"]
    real = notifications_api.drop_pinned

    async def broken(*a, **k):
        raise RuntimeError("database is locked")
    notifications_api.drop_pinned = broken
    try:
        try:
            r = MASTER.request("DELETE", f"/admin/users/{A}/accounts/{ACC}", json={"admin_password": pw})
            assert r.status_code >= 500, r.text
        except RuntimeError:
            pass
    finally:
        notifications_api.drop_pinned = real
    try:
        linked = asyncio.run(_linked(A))
        assert linked and len(_rows(A)) == 1, "a failed drop committed the unlink (the retry would 404, the row stranded)"
        r = MASTER.request("DELETE", f"/admin/users/{A}/accounts/{ACC}", json={"admin_password": pw})
        assert r.status_code == 200 and _rows() == [], r.text
    finally:
        if not asyncio.run(_linked(A)):
            asyncio.run(_link(A, True))


def case_the_account_delete_route_drops_every_agencys_row():
    _reset()
    asyncio.run(_link(B, True))
    _refuse_send()
    asyncio.run(_link(B, False))   # B's row outlives its link: hidden, then the delete takes it too
    d = account_registry.ACCOUNTS_DIR / ACC
    keep = d.with_name(ACC + ".kept")
    shutil.copytree(d, keep)
    try:
        account_registry.upsert_account(ACC, nickname="Ava")   # the route wants the meta.json the fixture lacks
        r = OWNER_A.delete(f"/admin/accounts/{ACC}")
        assert r.status_code == 200 and r.json() == {"ok": True}, r.text
        assert _rows() == [], [(n.agency_user_id, n.account_id) for n in _rows()]
        body = OWNER_A.get("/admin/agency-notifications").json()
        assert body["pinned"] == [] and body["unread"] == 0, body
    finally:
        if d.exists():
            shutil.rmtree(d)
        shutil.move(keep, d)


def case_a_flag_after_account_delete_files_nothing():
    _reset()
    d = account_registry.ACCOUNTS_DIR / ACC
    keep = d.with_name(ACC + ".kept")
    shutil.copytree(d, keep)
    try:
        account_registry.upsert_account(ACC, nickname="Ava")
        r = OWNER_A.delete(f"/admin/accounts/{ACC}")
        assert r.status_code == 200, r.text
        assert asyncio.run(_linked(A)), "the delete is expected to leave the link (else this case proves nothing)"
        filed = asyncio.run(cn.flag(ACC, "NC"))   # an in-flight OF call's 400 lands after the delete
        assert filed == 0 and _rows() == [], f"a flag after the delete filed {filed} row(s) nothing can remove"
    finally:
        if d.exists():
            shutil.rmtree(d)
        shutil.move(keep, d)


def case_a_clear_reaches_a_former_owners_row():
    _reset()
    asyncio.run(_link(B, True))
    _refuse_send()
    asyncio.run(_link(B, False))
    assert sorted(r.agency_user_id for r in _rows()) == sorted([A, B])
    _observe(("GET", f"{OF}/users/me", None, _R(200, {"needConsent": False})))
    assert _rows() == [], "a clear left a former owner's row (it would come back on a re-link)"


def case_an_owner_linked_after_the_flag_gets_the_row_on_the_next():
    _reset()
    _refuse_send()
    asyncio.run(_link(B, True))
    try:
        _refuse_send()
        assert sorted(r.agency_user_id for r in _rows()) == sorted([A, B])
        assert [n["account_id"] for n in OWNER_B.get("/admin/agency-notifications").json()["pinned"]] == [ACC]
        _observe(("POST", f"{OF}/chats/9/messages", {"mediaFiles": [7]}, _R(200, {"id": 2})))
        assert _rows() == [], "a clear left an owner's row"
    finally:
        asyncio.run(_link(B, False))


def case_a_clear_that_raced_the_flag_is_redone_by_the_next_verdict():
    _reset()
    real = notifications_api.notify

    async def clear_first(*a, **k):   # the clear runs between the flag's read and its insert
        assert await cn.clear(ACC) == 0
        return await real(*a, **k)
    notifications_api.notify = clear_first
    try:
        assert asyncio.run(cn.flag(ACC, "NC")) == 1
    finally:
        notifications_api.notify = real
    assert len(_rows(A)) == 1
    _observe(("POST", f"{OF}/chats/9/messages", {"mediaFiles": [7]}, _R(200, {"id": 2})))
    assert _rows() == [], "a later clear was skipped"


def case_a_failed_delete_is_redone_by_the_next_clear():
    _reset()
    _refuse_send()
    real = notifications_api.get_session

    def broken():
        raise RuntimeError("database is locked")
    notifications_api.get_session = broken
    try:
        assert asyncio.run(cn.clear(ACC)) == 0
    finally:
        notifications_api.get_session = real
    assert len(_rows(A)) == 1
    assert asyncio.run(cn.clear(ACC)) == 1 and _rows() == []


def case_a_flag_that_changes_nothing_writes_nothing():
    _reset()
    _refuse_send()
    real = notifications_api.notify
    calls = []

    async def counting(*a, **k):
        calls.append(a)
        return await real(*a, **k)
    notifications_api.notify = counting
    try:
        _refuse_send()
        _refuse_send()
    finally:
        notifications_api.notify = real
    assert calls == [] and len(_rows(A)) == 1, calls


_harness.run()
