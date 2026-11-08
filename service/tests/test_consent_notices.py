#!/usr/bin/env python3
"""OnlyFans' "Consent not accepted" as a pinned agency notification
(service/consent_notices.py + notifications_api.PINNED_KINDS).

The OF answers are fakes handed to `consent_notices.observe` as
`OFClient._http_call` hands them (status, url, body); the feed is read and
dismissed over HTTP with real owner session cookies from the shared
two-Agency fixture: a consent refusal files one row per owner, the read and
read-all refuse / skip it, the retention sweep keeps it, a /users/me
approval or an accepted media send clears it, a text-only send does not,
and an Agency that drops the Creator (unlinked or deleted) loses it.

Run: ./venv/bin/python service/tests/test_consent_notices.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import delete, select, update  # noqa: E402

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
        await cn.reload()
    asyncio.run(_run())


def _refuse_send() -> None:
    _observe(("POST", f"{OF}/messages/queue", {"text": "hi", "mediaFiles": [1]}, _R(400, CONSENT_400)))


def case_verdicts():
    assert cn.verdict_me({"needConsent": True, "needConsentState": "NC", "consentStatus": None}) is True
    assert cn.verdict_me({"needConsent": True, "consentStatus": "approved"}) is False
    assert cn.verdict_me({"needConsent": False}) is False
    assert cn.verdict_me({"id": 1}) is None and cn.verdict_me(None) is None
    post = lambda url, body, st, txt="{}": cn.verdict_call("POST", url, body, st, txt)  # noqa: E731
    assert post(f"{OF}/messages/queue", {"mediaFiles": [1]}, 400, CONSENT_400) is True
    assert post(f"{OF}/chats/5/messages", {}, 400, CONSENT_400) is True, "any write's refusal flags"
    assert post(f"{OF}/chats/5/messages", {"mediaFiles": [1]}, 200) is False
    assert post(f"{OF}/messages/queue", {"mediaFiles": [1]}, 200) is False
    assert post(f"{OF}/chats/5/messages", {"mediaFiles": []}, 200) is None, "a text send says nothing"
    assert post(f"{OF}/posts", {"mediaFiles": [1]}, 200) is None
    assert post(f"{OF}/messages/queue", {"mediaFiles": [1]}, 400, '{"error":{"message":"other"}}') is None
    assert cn.verdict_call("GET", f"{OF}/chats", None, 400, CONSENT_400) is None
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


def case_an_agency_that_unlinks_the_creator_loses_the_row():
    _reset()
    _refuse_send()

    async def _link(on: bool):
        async with get_session() as s:
            if on:
                s.add(UserAccount(user_id=A, account_id=ACC))
            else:
                await s.execute(delete(UserAccount).where(UserAccount.user_id == A, UserAccount.account_id == ACC))
    asyncio.run(_link(False))
    try:
        body = OWNER_A.get("/admin/agency-notifications").json()
        assert body["pinned"] == [] and body["unread"] == 0, body
        assert _rows() == [] and ACC not in cn._flagged
    finally:
        asyncio.run(_link(True))
    _refuse_send()
    assert len(_rows(A)) == 1, "re-linked, a new refusal must file again"


def case_a_creator_deleted_from_the_registry_loses_the_row():
    _reset()
    _refuse_send()
    d = account_registry.ACCOUNTS_DIR / ACC
    keep = d.with_name(ACC + ".kept")
    shutil.move(d, keep)
    try:
        assert OWNER_A.get("/admin/agency-notifications").json()["pinned"] == []
        assert _rows() == []
    finally:
        shutil.move(keep, d)


_harness.run()
