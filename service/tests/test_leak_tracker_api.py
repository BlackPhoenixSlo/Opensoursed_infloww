#!/usr/bin/env python3
import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import uuid  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import get_args  # noqa: E402
from unittest.mock import patch  # noqa: E402

import httpx  # noqa: E402
from sqlalchemy import delete, select, update  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import account_health  # noqa: E402
import accounts as account_registry  # noqa: E402
import employees  # noqa: E402
import account_page  # noqa: E402
import leak_tracker  # noqa: E402
import leak_tracker_api  # noqa: E402
import platforms  # noqa: E402
import relay_host  # noqa: E402
import tenant_keys  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, Action, Chatter, ChatterAccountAccess, ChatterUser, LeakTrackerTenant, LeakWatch, LeakWatchTombstone,
    UserAccount, UserLlmKey,
)

V1 = Path(__file__).resolve().parent / "fixtures" / "leak_tracker_v1"
relay_host.spawn_bg = lambda coro, name: coro.close()
TRACKER = "http://127.0.0.1:9"
ON = {"LEAK_TRACKER_URL": TRACKER, "LEAK_TRACKER_ENABLED": "1", "OI_CELL_MAP": None}

IDS = fx.seed_two_agencies()
OWNER_A = fx.login_owner("agency_a_owner")
CHATTER_A = fx.login_chatter("chatter_a")
CHATTER_AB = fx.login_chatter("chatter_ab")
EMP_A = asyncio.run(employees.get_or_create_mirror_employee(
    IDS["chatter_a"], IDS["agency_a_owner"], display_name="chatter_a", color="#bbbbbb"))


def _golden(name: str) -> dict:
    return json.loads((V1 / f"{name}.json").read_text())


ME = _golden("me")
ERR_401 = _golden("err_401")
ME_OTHER = {**ME, "response": {**ME["response"], "tenant_id": "tn_other0002"}}
ME_NO_BRAND = {**ME, "response": {**ME["response"], "brand": None, "contact_url": None}}


def _key(c: str) -> str:
    return "ltk_" + c * 40


KEY_1, KEY_2, KEY_3 = _key("a"), _key("b"), _key("c")


class Tracker:
    def __init__(self):
        self.answer: dict | Exception = ME
        self.routes: dict[str, dict | Exception] = {}
        self.calls: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        answer = self.routes.get(request.url.path, self.answer)
        if isinstance(answer, Exception):
            raise answer
        want = answer["path"]
        if want.startswith("/v1/watches/"):
            assert request.url.path.startswith("/v1/watches/"), request.url
        else:
            assert request.url.path == want, request.url
        assert request.method == answer["method"], request.method
        if "stream" in answer:
            return httpx.Response(answer["status"], stream=answer["stream"], headers=answer.get("headers"))
        if "raw" in answer:
            return httpx.Response(answer["status"], content=answer["raw"], headers=answer.get("headers"))
        response = answer["response"]
        if answer is PUT_CREATED or answer is PUT_UPDATED:
            response = {**response, "watch_id": request.url.path.rsplit("/", 1)[-1]}
        return httpx.Response(answer["status"], json=response, headers=answer.get("headers"))

    def bearers(self) -> list[str]:
        return [r.headers.get("authorization", "") for r in self.calls]


@contextmanager
def _tracker():
    fake = Tracker()
    real = httpx.AsyncClient
    saved = {k: os.environ.get(k) for k in ON}
    leak_tracker.httpx.AsyncClient = lambda **kw: real(**{**kw, "transport": httpx.MockTransport(fake.handler)})
    for k, v in ON.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield fake
    finally:
        leak_tracker.httpx.AsyncClient = real
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _reset(roles: dict | None = None) -> None:
    async def _wipe():
        async with get_session() as s:
            await s.execute(delete(UserLlmKey).where(UserLlmKey.provider == "leak_tracker"))
            await s.execute(delete(LeakTrackerTenant))
            await s.execute(delete(LeakWatch))
            await s.execute(delete(LeakWatchTombstone))
    asyncio.run(_wipe())
    leak_tracker.forget_invalid(IDS["agency_a_owner"])
    fx.store_blob(IDS["agency_a_owner"], "flags", {"leak_tracker": True})
    fx.store_blob(IDS["agency_a_owner"], "roles", roles or {"enforce": True, "roles": [], "assignments": {}})


def _stored() -> str:
    return asyncio.run(tenant_keys.get_key(IDS["agency_a_owner"], "leak_tracker"))


def _binding() -> str | None:
    async def _read():
        async with get_session() as s:
            return await s.scalar(select(LeakTrackerTenant.tenant_id).where(
                LeakTrackerTenant.agency_user_id == IDS["agency_a_owner"]))
    return asyncio.run(_read())


def _put(key: str, client=OWNER_A):
    return client.put("/admin/leaks/key", json={"key": key})


def _setup(client=OWNER_A) -> dict:
    r = client.get("/admin/leaks/setup")
    assert r.status_code == 200, r.text
    return r.json()


def _masked(key: str) -> str:
    return "••••" + key[-4:]


def case_a_key_is_checked_against_me_then_stored_and_binds_the_tenant():
    _reset()
    with _tracker() as t:
        r = _put(KEY_1)
        assert r.status_code == 200, r.text
        assert r.json() == {"key": "set", "masked": _masked(KEY_1), "brand": "Example Removal", "source": "own"}, r.json()
        assert t.bearers() == [f"Bearer {KEY_1}"], t.bearers()
        assert str(t.calls[0].url) == f"{TRACKER}/v1/me", t.calls[0].url
    assert _stored() == KEY_1
    assert _binding() == "tn_example0001"


def case_setup_shows_the_masked_key_to_the_owner_only_and_never_the_key():
    _reset({"enforce": True, "roles": [], "assignments": {str(EMP_A): "admin"}})
    with _tracker() as t:
        assert _put(KEY_1).status_code == 200
        owner = OWNER_A.get("/admin/leaks/setup")
        assert owner.json() == {"key": "set", "masked": _masked(KEY_1), "is_owner": True, "can_write": True,
                                "brand": "Example Removal", "source": "own", "previews": True}, owner.json()
        admin = CHATTER_A.get("/admin/leaks/setup")
        assert admin.json() == {"key": "set", "masked": None, "is_owner": False, "can_write": True,
                                "brand": "Example Removal", "source": "own", "previews": True}, admin.json()
        for r in (owner, admin):
            assert KEY_1 not in r.text and KEY_1[4:] not in r.text
        assert set(t.bearers()) == {f"Bearer {KEY_1}"}


def case_setup_reports_the_brand_from_me_or_null():
    _reset()
    with _tracker() as t:
        assert _put(KEY_1).status_code == 200
        assert _setup()["brand"] == "Example Removal"
        t.answer = ME_NO_BRAND
        assert _setup()["brand"] is None
        t.answer = httpx.ConnectError("refused")
        body = _setup()
        assert body["key"] == "set" and body["brand"] is None, body


def case_setup_with_no_key_makes_no_call():
    _reset()
    with _tracker() as t:
        assert _setup() == {"key": "missing", "masked": None, "is_owner": True, "can_write": True, "brand": None,
                            "source": None, "previews": True}
        assert t.calls == []


def case_a_401_is_refused_and_nothing_is_stored():
    _reset()
    with _tracker() as t:
        t.answer = ERR_401
        r = _put(KEY_1)
        assert r.status_code == 422, r.text
        assert r.json()["detail"] == "Key not accepted", r.json()
        assert _stored() == "" and _binding() is None
        assert _setup()["key"] == "missing"
        t.answer = ME
        assert _put(KEY_1).status_code == 200
        t.answer = ERR_401
        assert _put(KEY_2).status_code == 422
        t.answer = ME
        assert _setup()["key"] == "set", "a refused new key never marks the stored one"
    assert _stored() == KEY_1


def case_an_unreachable_service_is_503_and_nothing_is_stored():
    for label, answer in [("connect", httpx.ConnectError("refused")),
                          ("timeout", httpx.ReadTimeout("slow")),
                          ("5xx", {**ME, "status": 502, "response": {"error": "bad_gateway"}})]:
        _reset()
        with _tracker() as t:
            t.answer = answer
            r = _put(KEY_1)
            assert r.status_code == 503, f"{label}: {r.status_code} {r.text}"
            assert KEY_1 not in r.text
        assert _stored() == "" and _binding() is None, label


def case_a_later_401_marks_the_key_no_longer_valid_until_a_new_key_is_saved():
    _reset()
    with _tracker() as t:
        assert _put(KEY_1).status_code == 200
        t.answer = ERR_401
        body = _setup()
        assert body["key"] == "invalid" and body["brand"] is None, body
        assert body["masked"] == _masked(KEY_1)
        t.answer = ME
        calls = len(t.calls)
        assert _setup()["key"] == "invalid"
        assert len(t.calls) == calls, "a key known to be revoked is not sent again"
        assert _put(KEY_2).status_code == 200
        assert _setup()["key"] == "set"
    assert _stored() == KEY_2 and _binding() == "tn_example0001"


def case_a_late_refusal_of_the_old_key_does_not_invalidate_the_replacement():
    _connect()
    real_client = httpx.AsyncClient
    agency = IDS["agency_a_owner"]

    async def rotate():
        started = asyncio.Event()
        release = asyncio.Event()

        async def refuse(_request):
            started.set()
            await release.wait()
            return httpx.Response(401)

        leak_tracker.httpx.AsyncClient = lambda **kw: real_client(**kw, transport=httpx.MockTransport(refuse))
        pending = asyncio.create_task(leak_tracker.call(agency, KEY_1, "GET", "/v1/me"))
        await asyncio.wait_for(started.wait(), 3)
        await leak_tracker.store_key(agency, KEY_2)
        release.set()
        try:
            await pending
        except leak_tracker.KeyRefused:
            pass
        else:
            raise AssertionError("old key was not refused")
        assert not leak_tracker.key_invalid(agency)

    with _tracker():
        asyncio.run(rotate())


def case_the_tracker_request_has_a_total_deadline():
    real_client = httpx.AsyncClient

    async def slow(_request):
        await asyncio.sleep(0.1)
        return httpx.Response(200)

    async def request():
        leak_tracker.httpx.AsyncClient = lambda **kw: real_client(**kw, transport=httpx.MockTransport(slow))
        try:
            await leak_tracker.call(None, "", "GET", "/v1/me", timeout=httpx.Timeout(0.02))
        except leak_tracker.Unreachable:
            return
        raise AssertionError("slow request escaped the total timeout")

    with _tracker():
        asyncio.run(request())


def case_a_key_of_another_tenant_is_refused_and_the_binding_never_moves():
    _reset()
    with _tracker() as t:
        assert _put(KEY_1).status_code == 200
        t.answer = ME_OTHER
        r = _put(KEY_2)
        assert r.status_code == 422, r.text
        assert r.json()["detail"] == "Key belongs to another tracker account"
        t.answer = ME
        assert _put(KEY_3).status_code == 200, "a key of the bound tenant still rotates"
    assert _stored() == KEY_3 and _binding() == "tn_example0001"


def case_an_empty_key_clears_it_and_keeps_the_binding():
    _reset()
    with _tracker() as t:
        assert _put(KEY_1).status_code == 200
        calls = len(t.calls)
        r = _put("   ")
        assert r.status_code == 200, r.text
        assert r.json() == {"key": "missing", "masked": None, "brand": None, "source": None}
        assert len(t.calls) == calls, "clearing calls nobody"
        assert _stored() == "" and _setup()["key"] == "missing"
        t.answer = ME_OTHER
        assert _put(KEY_2).status_code == 422, "the binding outlives a cleared key"
    assert _binding() == "tn_example0001"


def case_only_the_owner_session_sets_the_key():
    _reset({"enforce": True, "roles": [], "assignments": {str(EMP_A): "admin"}})
    with _tracker() as t:
        r = _put(KEY_1, CHATTER_A)
        assert r.status_code == 403, r.text
        assert _put("", CHATTER_A).status_code == 403
        assert t.calls == []
    assert _stored() == ""


def case_a_value_that_is_not_a_tracker_key_is_refused_without_a_call():
    _reset()
    with _tracker() as t:
        for bad in ["sk-" + "a" * 40, "ltk_" + "a" * 31, "ltk_" + "a" * 39 + "!", _masked(KEY_1), "ltk_" + "•" * 40]:
            r = _put(bad)
            assert r.status_code == 422, f"{bad!r}: {r.status_code}"
            assert r.json()["detail"] == "Key not accepted"
        assert t.calls == []
    assert _stored() == ""


def case_the_key_never_reaches_the_audit_log():
    _reset()
    with _tracker():
        assert _put(KEY_1).status_code == 200
        assert _put(KEY_1 + "x").status_code == 200

    async def _rows():
        async with get_session() as s:
            return (await s.execute(select(Action.action, Action.payload_json).where(
                Action.action == "PUT /admin/leaks/key"))).all()
    rows = asyncio.run(_rows())
    assert rows, "the key write is audited"
    blob = " ".join(p or "" for _, p in rows)
    assert KEY_1[4:] not in blob, blob
    assert {"key": "set"} in [json.loads(p) for _, p in rows if p]


PUT_CREATED = _golden("put_created")
PUT_UPDATED = _golden("put_updated")
ACCOUNT_TAKEN = _golden("err_409_account_taken")
CREATOR_CAP = _golden("err_409_creator_cap")
INVALID = _golden("err_422")
LIMITED = _golden("err_429")

CREATOR = IDS["creator_a"]
SECOND, FANSLY = "1000003", "1000004"
MIA = {"username": "miavale", "verified": True, "display_name": "Mia Vale", "aliases": ["mia.vale.x"],
       "instagram": "miavale", "x": "miavale"}
MIA_LIVE = {"username": "miavale", "name": "Mia Vale"}


async def _seed_scope() -> str:
    now = datetime.utcnow()
    scoped = uuid.uuid4().hex
    async with get_session() as s:
        s.add(Account(id=SECOND, nickname="creator_a2", color="#aaaaaa"))
        s.add(Account(id=FANSLY, nickname="creator_a3", color="#aaaaaa"))
        s.add(Chatter(id=scoped, username="lt_scoped", password=fx.PASSWORD, display_name="lt_scoped",
                      color="#bbbbbb", created_at=now, last_seen_at=now))
    async with get_session() as s:
        for aid in (SECOND, FANSLY):
            s.add(UserAccount(user_id=IDS["agency_a_owner"], account_id=aid))
        s.add(ChatterUser(chatter_id=scoped, user_id=IDS["agency_a_owner"], created_at=now))
        s.add(ChatterAccountAccess(chatter_id=scoped, user_id=IDS["agency_a_owner"], account_id=CREATOR))
    return scoped


SCOPED_ID = asyncio.run(_seed_scope())
account_registry.account_dir(SECOND).mkdir(exist_ok=True)
account_registry.save_meta(FANSLY, {"id": FANSLY, "nickname": "creator_a3", "platform": "fansly"})
SCOPED = fx.login_chatter("lt_scoped")
EMP_SCOPED = asyncio.run(employees.get_or_create_mirror_employee(
    SCOPED_ID, IDS["agency_a_owner"], display_name="lt_scoped", color="#bbbbbb"))
EMP_AB = asyncio.run(employees.get_or_create_mirror_employee(
    IDS["chatter_ab"], IDS["agency_a_owner"], display_name="chatter_ab", color="#bbbbbb"))


def _connect(roles: dict | None = None) -> None:
    _reset(roles)
    asyncio.run(leak_tracker.store_key(IDS["agency_a_owner"], KEY_1))
    asyncio.run(leak_tracker.bind_tenant(IDS["agency_a_owner"], ME["response"]["tenant_id"]))


@contextmanager
def _live(profiles: dict[str, dict | None]):
    real, asked = account_page.of_me, []

    async def fake(account_id: str):
        asked.append(account_id)
        return profiles.get(account_id)
    account_page.of_me = fake
    try:
        yield asked
    finally:
        account_page.of_me = real


def _enrol(body: dict | None = None, *, account: str = CREATOR, client=OWNER_A, consent=True):
    payload = {**(MIA if body is None else body)}
    if consent is not None:
        payload["consent"] = consent
    return client.put(f"/admin/leaks/watches/{account}", json=payload)


def _watches() -> list[LeakWatch]:
    async def _read():
        async with get_session() as s:
            return list((await s.execute(select(LeakWatch).order_by(LeakWatch.id))).scalars())
    return asyncio.run(_read())


def _pushed(t: Tracker) -> list[dict]:
    return [json.loads(r.content) for r in t.calls if r.method == "PUT"]


def case_enrol_rechecks_for_a_nonblank_key_after_profile_verification():
    _connect()

    async def verify(account_id: str):
        async with get_session() as s:
            await s.execute(update(UserLlmKey).where(
                UserLlmKey.user_id == IDS["agency_a_owner"], UserLlmKey.provider == leak_tracker.PROVIDER,
            ).values(api_key=" \t"))
        return MIA_LIVE

    with _tracker() as t, patch.object(account_page, "of_me", verify):
        t.answer = PUT_CREATED
        r = _enrol()
        assert r.status_code == 404, r.text
        assert not t.calls
    assert not _watches()


def case_enrol_rechecks_membership_after_profile_verification():
    _connect()
    master = fx.login_owner("agency_master")
    agency = IDS["agency_a_owner"]

    async def verify(account_id: str):
        r = await asyncio.to_thread(
            master.request, "DELETE", f"/admin/users/{agency}/accounts/{account_id}",
            json={"admin_password": os.environ["ADMIN_PASSWORD"]},
        )
        assert r.status_code == 200, r.text
        return MIA_LIVE

    try:
        with _tracker() as t, patch.object(account_page, "of_me", verify):
            t.answer = PUT_CREATED
            r = _enrol()
            assert r.status_code == 404, r.text
            assert not _watches()
            assert not t.calls
            assert _put("").status_code == 200
    finally:
        async def relink():
            async with get_session() as s:
                if await s.get(UserAccount, (agency, CREATOR)) is None:
                    s.add(UserAccount(user_id=agency, account_id=CREATOR))
        asyncio.run(relink())


def case_enrol_with_consent_mints_the_watch_id_stores_who_and_when_and_pushes_the_identity():
    _connect()
    with _tracker() as t, _live({CREATOR: MIA_LIVE}):
        t.answer = PUT_CREATED
        before = datetime.utcnow()
        r = _enrol()
        assert r.status_code == 200, r.text
        assert r.json() == {"synced": True}, r.json()
    (row,) = _watches()
    assert str(uuid.UUID(row.watch_id)) == row.watch_id
    assert t.calls[0].url.path == f"/v1/watches/{row.watch_id}", t.calls[0].url
    assert t.bearers() == [f"Bearer {KEY_1}"]
    assert _pushed(t) == [{**PUT_CREATED["request"], "account_id": CREATOR}], _pushed(t)
    assert row.consent_by == f"user:{IDS['agency_a_owner']}:agency_a_owner", row.consent_by
    assert before - timedelta(seconds=1) <= row.consent_at <= datetime.utcnow(), row.consent_at
    assert (row.agency_user_id, row.account_id, row.platform, row.username, row.verified) == \
        (IDS["agency_a_owner"], CREATOR, "onlyfans", "miavale", True)
    assert json.loads(row.aliases_json) == ["mia.vale.x"] and row.on is True
    assert row.synced_at is not None and row.synced_paused is False


def case_enrol_without_consent_saves_and_records_who_and_when():
    _connect()
    with _tracker() as t, _live({CREATOR: MIA_LIVE}):
        t.answer = PUT_CREATED
        r = _enrol(consent=None)
        assert r.status_code == 200, r.text
        assert len(t.calls) == 1
    (row,) = _watches()
    assert row.consent_by == f"user:{IDS['agency_a_owner']}:agency_a_owner", row.consent_by
    assert row.consent_at is not None


def case_an_admin_consents_under_the_employee_session():
    _connect({"enforce": True, "roles": [], "assignments": {str(EMP_A): "admin"}})
    with _tracker() as t, _live({}):
        t.answer = PUT_CREATED
        assert _enrol(client=CHATTER_A).status_code == 200
    (row,) = _watches()
    assert row.consent_by == f"chatter:{IDS['chatter_a']}:chatter_a", row.consent_by


def case_the_suggestion_is_the_live_identity_verified_or_empty_unverified():
    _connect()
    empty = {"username": "", "display_name": "", "verified": False}
    with _tracker() as t, _live({CREATOR: MIA_LIVE, FANSLY: MIA_LIVE}):
        body = OWNER_A.get(f"/admin/leaks/watches/{CREATOR}").json()
        assert body == {"tracked": False, "identity": None, "synced": False, "lanes": None, "this_week": None,
                        "next_refresh_at": None, "last_checked_at": None, "removal": None, "offer": None, "leaks": [], "next_cursor": None, "stale": False, "fetched_at": None,
                        "suggested": {"username": "miavale", "display_name": "Mia Vale", "verified": True}}, body
        body = OWNER_A.get(f"/admin/leaks/watches/{SECOND}").json()
        assert body["suggested"] == empty, "no live session: typed and unverified"
        body = OWNER_A.get(f"/admin/leaks/watches/{FANSLY}").json()
        assert body["suggested"] == empty, "Fansly: typed and unverified"
        assert t.calls == []


def case_a_verified_claim_needs_the_live_handle():
    _connect()
    with _tracker() as t, _live({SECOND: {"username": "someoneelse", "name": "X"}}):
        t.answer = PUT_CREATED
        assert _enrol().status_code == 200
        assert _enrol({**MIA, "username": "mia_two"}, account=SECOND).status_code == 200
        assert _enrol({**MIA, "username": "mia_three"}, account=FANSLY).status_code == 200
    assert [(w.account_id, w.platform, w.verified) for w in _watches()] == \
        [(CREATOR, "onlyfans", False), (SECOND, "onlyfans", False), (FANSLY, "fansly", False)]
    assert [b["verified"] for b in _pushed(t)] == [False, False, False]
    assert [b["platform"] for b in _pushed(t)] == ["onlyfans", "onlyfans", "fansly"]


def case_saving_a_kept_verified_handle_reads_no_live_identity():
    _connect()
    with _tracker() as t, _live({CREATOR: MIA_LIVE}) as asked:
        t.answer = PUT_CREATED
        assert _enrol().status_code == 200
        assert asked == [CREATOR]
        t.answer = PUT_UPDATED
        assert _enrol({**MIA, "display_name": "Mia V."}).status_code == 200
        assert asked == [CREATOR], "an already-verified handle is kept without asking OnlyFans again"
    (row,) = _watches()
    assert row.verified is True and _pushed(t)[-1]["verified"] is True


def case_identity_changes_refresh_consent():
    _connect({"enforce": True, "roles": [], "assignments": {str(EMP_A): "admin"}})
    with _tracker() as t, _live({}):
        t.answer = PUT_CREATED
        assert _enrol().status_code == 200
        (before,) = _watches()
        t.answer = PUT_UPDATED
        assert _enrol({**MIA, "display_name": "Other"}, client=CHATTER_A, consent=None).status_code == 200
        (after,) = _watches()
        assert after.watch_id == before.watch_id
        assert after.consent_at > before.consent_at
        assert after.consent_by == f"chatter:{IDS['chatter_a']}:chatter_a"


def case_a_second_creator_on_the_same_handle_is_409():
    _connect()
    with _tracker() as t, _live({}):
        t.answer = PUT_CREATED
        assert _enrol().status_code == 200
        calls = len(t.calls)
        for handle in ("miavale", "MiaVale"):
            r = _enrol({**MIA, "username": handle}, account=SECOND)
            assert r.status_code == 409, f"{handle}: {r.status_code} {r.text}"
            assert r.json()["detail"] == "Another Creator in this agency already uses that handle"
        assert len(t.calls) == calls
        assert _enrol({**MIA, "username": "miavale"}, account=FANSLY).status_code == 200, "other Platform"
    assert [w.account_id for w in _watches()] == [CREATOR, FANSLY]


def case_save_while_the_service_is_down_keeps_the_row_unsynced():
    for label, answer in [("connect", httpx.ConnectError("refused")),
                          ("timeout", httpx.ReadTimeout("slow")),
                          ("5xx", {**PUT_CREATED, "status": 502, "response": {"error": "bad_gateway"}}),
                          ("429", LIMITED),
                          ("401", {**PUT_CREATED, "status": 401, "response": ERR_401["response"]})]:
        _connect()
        with _tracker() as t, _live({}):
            t.answer = answer
            r = _enrol()
            assert r.status_code == 200, f"{label}: {r.status_code} {r.text}"
            assert r.json() == {"synced": False}, label
            assert len(t.calls) == 1, label
        (row,) = _watches()
        assert row.synced_at is None and row.consent_by == f"user:{IDS['agency_a_owner']}:agency_a_owner", label
    assert leak_tracker.key_invalid(IDS["agency_a_owner"])


def case_saving_with_a_known_invalid_key_refuses_without_writing():
    _connect()
    with _tracker() as t, _live({}):
        t.answer = ERR_401
        assert _setup()["key"] == "invalid"
        r = _enrol()
        assert r.status_code == 409 and r.json()["detail"]["error"] == "key_invalid"
        assert _watches() == [] and len(t.calls) == 1


def case_only_an_ack_for_this_watch_marks_it_synced():
    for answer in ({**PUT_CREATED, "raw": b"<html>"},
                   {**PUT_CREATED, "response": {"watch_id": "other-watch"}}):
        _connect()
        with _tracker() as t, _live({}):
            t.answer = answer
            assert _enrol().json() == {"synced": False}
            assert _watches()[0].synced_at is None
            asyncio.run(leak_tracker.sync_watches())
            assert len(t.calls) == 2
            assert _watches()[0].synced_at is None
            t.answer = PUT_UPDATED
            asyncio.run(leak_tracker.sync_watches())
            assert len(t.calls) == 3 and _watches()[0].synced_at is not None


def case_an_update_keeps_the_watch_id_and_refreshes_consent():
    _connect()
    with _tracker() as t, _live({}):
        t.answer = PUT_CREATED
        assert _enrol().status_code == 200
        (first,) = _watches()
        t.answer = PUT_UPDATED
        r = _enrol({**MIA, "display_name": "Mia V."})
        assert r.status_code == 200 and r.json() == {"synced": True}, r.text
        (row,) = _watches()
        assert (row.watch_id, row.consent_by) == (first.watch_id, first.consent_by)
        assert row.consent_at > first.consent_at
        assert row.display_name == "Mia V."
        assert {r.url.path for r in t.calls} == {f"/v1/watches/{row.watch_id}"}
        assert _pushed(t)[-1] == {**PUT_UPDATED["request"], "account_id": CREATOR, "verified": False}
        t.answer = httpx.ConnectError("refused")
        r = _enrol({**MIA, "display_name": "Mia"})
        assert r.json() == {"synced": False}, r.text
    (row,) = _watches()
    assert row.display_name == "Mia" and row.synced_at < row.updated_at and row.synced_paused is False


def case_concurrent_save_of_a_refused_watch_returns_conflict():
    from server import app

    _connect()
    real_client = httpx.AsyncClient

    async def race():
        first_started = asyncio.Event()
        release = asyncio.Event()
        upstream = {}

        async def upstream_put(request):
            identity = json.loads(request.content)
            watch_id = request.url.path.rsplit("/", 1)[-1]
            if identity["display_name"] == "Refused":
                first_started.set()
                await release.wait()
                return httpx.Response(422, json=INVALID["response"])
            upstream[watch_id] = identity["display_name"]
            return httpx.Response(200, json={"watch_id": watch_id})

        leak_tracker.httpx.AsyncClient = lambda **kw: real_client(
            **kw, transport=httpx.MockTransport(upstream_put))
        async with real_client(transport=httpx.ASGITransport(app=app), base_url="http://testserver",
                               cookies=dict(OWNER_A.cookies.items())) as client:
            path = f"/admin/leaks/watches/{CREATOR}"
            first = asyncio.create_task(client.put(path, json={**MIA, "display_name": "Refused", "consent": True}))
            await asyncio.wait_for(first_started.wait(), 3)
            second = asyncio.create_task(client.put(path, json={**MIA, "display_name": "Accepted", "consent": True}))
            await asyncio.wait({second}, timeout=0.4)
            release.set()
            rejected, accepted = await asyncio.gather(first, second)
        assert (rejected.status_code, accepted.status_code) == (422, 409)
        return upstream

    with _tracker(), _live({}):
        upstream = asyncio.run(race())
    assert not upstream and not _watches()


def case_a_shared_creator_watch_uses_the_named_roster_agency():
    _connect()
    owner_a, owner_b = IDS["agency_a_owner"], IDS["agency_b_owner"]
    other = IDS["creator_b"]
    async def share():
        async with get_session() as s:
            s.add(UserAccount(user_id=owner_b, account_id=CREATOR))
        return [await employees.get_or_create_mirror_employee(
            IDS["chatter_ab"], owner, display_name="chatter_ab", color="#bbbbbb") for owner in (owner_a, owner_b)]

    employees_ab = asyncio.run(share())
    try:
        for owner, employee in zip((owner_a, owner_b), employees_ab):
            fx.store_blob(owner, "roles", {"enforce": True, "roles": [], "assignments": {str(employee): "admin"}})
            fx.store_blob(owner, "flags", {"leak_tracker": True})
            asyncio.run(leak_tracker.store_key(owner, KEY_1))
            asyncio.run(leak_tracker.bind_tenant(owner, ME["response"]["tenant_id"]))
        with _tracker() as t, _live({}):
            t.answer = DOWN
            scope_b = {"X-Account-Id": other}
            path = f"/admin/leaks/watches/{CREATOR}"
            r = CHATTER_AB.put(path, json={**MIA, "display_name": "Agency B", "consent": True}, headers=scope_b)
            assert r.status_code == 200, r.text
            result = CHATTER_AB.get(path, headers=scope_b)
            assert result.json()["identity"]["display_name"] == "Agency B"
            (row,) = _watches()
            assert row.agency_user_id == owner_b
    finally:
        async def unshare():
            async with get_session() as s:
                await s.execute(delete(UserAccount).where(
                    UserAccount.user_id == owner_b, UserAccount.account_id == CREATOR))

        asyncio.run(unshare())


def case_service_refusals_drop_a_new_row_and_leave_an_old_one():
    for answer, status, detail in [
            (ACCOUNT_TAKEN, 409, "The removal service already tracks this Creator under another watch"),
            (CREATOR_CAP, 409, "The removal service's Creator limit is reached (2)"),
            (INVALID, 422, "The removal service refused the username")]:
        _connect()
        with _tracker() as t, _live({}):
            t.answer = answer
            r = _enrol()
            assert (r.status_code, r.json()["detail"]) == (status, detail), r.text
            assert _watches() == []
            t.answer = PUT_CREATED
            assert _enrol().status_code == 200
            (kept,) = _watches()
            t.answer = answer
            r = _enrol({**MIA, "display_name": "Changed"})
            assert r.status_code == status, r.text
        (row,) = _watches()
        assert (row.display_name, row.synced_at) == ("Mia Vale", kept.synced_at), detail


def case_a_creator_outside_the_agency_or_the_session_is_404():
    _connect({"enforce": True, "roles": [], "assignments": {str(EMP_SCOPED): "admin", str(EMP_AB): "admin"}})
    with _tracker() as t, _live({}):
        t.answer = PUT_CREATED
        both = {"X-Account-Id": CREATOR}
        for client, account, headers in [(OWNER_A, IDS["creator_b"], {}), (OWNER_A, "1000999", {}),
                                         (SCOPED, SECOND, {}), (CHATTER_AB, IDS["creator_b"], both)]:
            got = client.get(f"/admin/leaks/watches/{account}", headers=headers)
            assert (got.status_code, got.json()) == (404, {"detail": "Not Found"}), (account, got.text)
            put = client.put(f"/admin/leaks/watches/{account}", json={**MIA, "consent": True}, headers=headers)
            assert (put.status_code, put.json()) == (404, {"detail": "Not Found"}), (account, put.text)
        assert t.calls == []
        assert _enrol(client=SCOPED).status_code == 200
    assert [w.account_id for w in _watches()] == [CREATOR]


def case_team_leader_reads_but_never_writes():
    _connect({"enforce": True, "roles": [], "assignments": {str(EMP_A): "team-leader"}})
    with _tracker() as t, _live({}):
        t.answer = PUT_CREATED
        assert CHATTER_A.get(f"/admin/leaks/watches/{CREATOR}").status_code == 200
        r = _enrol(client=CHATTER_A)
        assert r.status_code == 403, r.text
        assert CHATTER_A.get("/admin/leaks/roster").status_code == 200
        assert t.calls == []
    assert _watches() == []


def _track(on, *, account: str = CREATOR, client=OWNER_A):
    return client.post(f"/admin/leaks/watches/{account}/tracking", json={"on": on})


def case_the_tracking_switch_pauses_and_resumes_keeping_the_row_and_calls_nothing():
    _connect()
    with _tracker() as t, _live({}):
        t.answer = PUT_CREATED
        assert _enrol().status_code == 200
        (before,) = _watches()
        t.calls.clear()
        r = _track(False)
        assert (r.status_code, r.json()) == (200, {"on": False}), r.text
        (row,) = _watches()
        assert row.on is False and row.updated_at > before.updated_at
        assert (row.watch_id, row.username, row.aliases_json, row.consent_at, row.synced_at, row.synced_paused) == \
            (before.watch_id, before.username, before.aliases_json, before.consent_at, before.synced_at, False)
        for path, name in [(f"/v1/creators/{row.watch_id}/leaks", "creator_leaks"), (f"/v1/creators/{row.watch_id}", "creator_one")]:
            t.routes[path] = {**_golden(name), "path": path}
        t.routes["/v1/me"] = ME
        assert OWNER_A.get(f"/admin/leaks/watches/{CREATOR}").json()["identity"]["on"] is False
        assert [c.method for c in t.calls] == ["GET", "GET", "GET"], "the hourly sync pushes the paused bit"
        t.calls.clear()
        assert (_track(True).status_code, _watches()[0].on) == (200, True)
        assert t.calls == []


def case_the_tracking_switch_is_owner_or_admin_only_inside_the_session_scope():
    _connect({"enforce": True, "roles": [], "assignments": {str(EMP_A): "team-leader", str(EMP_SCOPED): "admin"}})
    with _tracker() as t, _live({}):
        t.answer = PUT_CREATED
        assert _enrol().status_code == 200
        t.calls.clear()
        r = _track(False, client=CHATTER_A)
        assert (r.status_code, r.json()["detail"]) == (403, "Only the owner or an Admin can change Leak tracking"), r.text
        for account, client in [(SECOND, OWNER_A), (IDS["creator_b"], OWNER_A), ("1000999", OWNER_A), (SECOND, SCOPED)]:
            r = _track(False, account=account, client=client)
            assert (r.status_code, r.json()) == (404, {"detail": "Not Found"}), (account, r.text)
        for bad in ("false", 0, None):
            assert _track(bad).status_code == 422, bad
        assert OWNER_A.post(f"/admin/leaks/watches/{CREATOR}/tracking", content=b"{").status_code == 422
        assert _watches()[0].on is True
        assert (_track(False, client=SCOPED).status_code, _watches()[0].on) == (200, False)
        assert t.calls == []


def case_a_deactivated_creator_is_enrolled_paused():
    _connect()
    asyncio.run(account_health.deactivate(CREATOR))
    try:
        with _tracker() as t, _live({}):
            t.answer = PUT_CREATED
            assert _enrol().status_code == 200
            assert _pushed(t)[0]["paused"] is True, _pushed(t)
        (row,) = _watches()
        assert row.on is True and row.synced_paused is True
    finally:
        asyncio.run(account_health.activate(CREATOR))
        asyncio.run(account_health.load_write_gate())


CREATORS = _golden("creators")
MIA_W, ROWAN_W = (c["watch_id"] for c in CREATORS["response"]["creators"])
DOWN = httpx.ConnectError("refused")
UNKNOWN = {"seeded": False, "paused": False, "paused_since": None, "last_checked_at": None, "next_check_at": None,
           "next_refresh_at": None, "counts": None, "this_week": None}


def _rewatch(account: str, watch_id: str) -> None:
    async def _set():
        async with get_session() as s:
            row = await s.scalar(select(LeakWatch).where(LeakWatch.account_id == account))
            row.watch_id = watch_id
    asyncio.run(_set())


def _service(watch_id: str) -> dict:
    (c,) = [c for c in CREATORS["response"]["creators"] if c["watch_id"] == watch_id]
    return {k: c[k] for k in UNKNOWN}


def _local(account: str, name: str, username: str, *, on: bool = True) -> dict:
    return {"account_id": account, "name": name, "platform": platforms.for_account(account).key,
            "username": username, "display_name": "Mia Vale", "on": on, "synced": True}


def _enrol_three(t: Tracker) -> None:
    t.answer = PUT_CREATED
    assert _enrol().status_code == 200
    assert _enrol({**MIA, "username": "rowanash"}, account=SECOND).status_code == 200
    assert _enrol({**MIA, "username": "miavale"}, account=FANSLY).status_code == 200
    _rewatch(CREATOR, MIA_W)
    _rewatch(SECOND, ROWAN_W)


def _roster(client=OWNER_A) -> dict:
    r = client.get("/admin/leaks/roster")
    assert r.status_code == 200, r.text
    return r.json()


def case_the_roster_merges_local_rows_with_the_service_creators():
    _connect()
    with _tracker() as t, _live({}):
        _enrol_three(t)
        t.routes["/v1/creators"] = CREATORS
        before = datetime.now(timezone.utc).replace(microsecond=0)
        body = _roster()
        (call,) = [c for c in t.calls if c.method == "GET"]
        assert (str(call.url), call.headers["authorization"]) == (f"{TRACKER}/v1/creators", f"Bearer {KEY_1}")
    assert body["untracked"] == [] and body["stale"] is False, body
    assert before <= datetime.fromisoformat(body["fetched_at"]) <= datetime.now(timezone.utc), body["fetched_at"]
    assert body["rows"] == [
        {**_local(CREATOR, "creator_a", "miavale"), "reachable": True, **_service(MIA_W)},
        {**_local(SECOND, "creator_a2", "rowanash"), "reachable": True, **_service(ROWAN_W)},
        {**_local(FANSLY, "creator_a3", "miavale"), "reachable": True, **UNKNOWN},
    ], body["rows"]


def case_the_roster_lists_untracked_creators_and_makes_no_call_with_nothing_tracked():
    _connect()
    with _tracker() as t, _live({}):
        body = _roster()
        assert t.calls == []
    assert body == {"rows": [], "untracked": [{"account_id": CREATOR, "name": "creator_a"},
                                              {"account_id": SECOND, "name": "creator_a2"},
                                              {"account_id": FANSLY, "name": "creator_a3"}],
                    "stale": False, "fetched_at": None}, body


def case_a_team_leaders_roster_lists_only_the_session_creators():
    _connect({"enforce": True, "roles": [], "assignments": {str(EMP_SCOPED): "team-leader"}})
    with _tracker() as t, _live({}):
        t.answer = PUT_CREATED
        assert _enrol({**MIA, "username": "rowanash"}, account=SECOND).status_code == 200
        body = _roster(SCOPED)
        assert len(t.calls) == 1, "no Creator of the session is tracked: no call"
        assert _enrol().status_code == 200
        _rewatch(CREATOR, MIA_W)
        _rewatch(SECOND, ROWAN_W)
        t.routes["/v1/creators"] = CREATORS
        owner = _roster()
        scoped = _roster(SCOPED)
        t.routes["/v1/creators"] = DOWN
        stale = _roster(SCOPED)
    assert body["rows"] == [] and body["untracked"] == [{"account_id": CREATOR, "name": "creator_a"}], body
    assert [r["account_id"] for r in owner["rows"]] == [CREATOR, SECOND], owner
    for got in (scoped, stale):
        assert [r["account_id"] for r in got["rows"]] == [CREATOR] and got["untracked"] == [], got
        assert ROWAN_W not in json.dumps(got) and SECOND not in json.dumps(got), "the copy never widens the scope"
    assert stale["stale"] is True and stale["rows"][0]["counts"] == CREATORS["response"]["creators"][0]["counts"], stale


def case_an_unreachable_service_serves_the_last_good_copy_marked_stale():
    for label, down in [("connect", DOWN), ("timeout", httpx.ReadTimeout("slow")),
                        ("5xx", {**CREATORS, "status": 503, "response": {"error": "unavailable"}})]:
        _connect()
        with _tracker() as t, _live({}):
            _enrol_three(t)
            t.routes["/v1/creators"] = CREATORS
            fresh = _roster()
            t.routes["/v1/creators"] = down
            stale = _roster()
        assert stale["stale"] is True and stale["fetched_at"] == fresh["fetched_at"], (label, stale)
        assert stale["rows"] == fresh["rows"], label


def case_with_no_copy_the_local_rows_read_not_reachable():
    for label, down in [("connect", DOWN), ("5xx", {**CREATORS, "status": 502, "response": {"error": "bad_gateway"}})]:
        _connect()
        with _tracker() as t, _live({}):
            _enrol_three(t)
            t.routes["/v1/creators"] = down
            body = _roster()
        assert body["stale"] is False and body["fetched_at"] is None, (label, body)
        assert body["rows"] == [
            {**_local(CREATOR, "creator_a", "miavale"), "reachable": False, **UNKNOWN},
            {**_local(SECOND, "creator_a2", "rowanash"), "reachable": False, **UNKNOWN},
            {**_local(FANSLY, "creator_a3", "miavale"), "reachable": False, **UNKNOWN},
        ], (label, body["rows"])


def case_a_refused_key_drops_the_copy_and_the_roster_reads_key_invalid():
    _connect()
    with _tracker() as t, _live({}):
        _enrol_three(t)
        t.routes["/v1/creators"] = CREATORS
        assert _roster()["rows"][0]["reachable"] is True
        t.routes["/v1/creators"] = {**CREATORS, "status": 401, "response": ERR_401["response"]}
        r = OWNER_A.get("/admin/leaks/roster")
        assert r.status_code == 409 and r.json()["detail"] == {"error": "key_invalid", "message": "Key no longer valid"}, \
            r.text
        assert leak_tracker._copies == {}, "a refused key never serves the old copy"
        assert _setup()["key"] == "invalid"
        calls = len(t.calls)
        t.routes["/v1/creators"] = CREATORS
        assert OWNER_A.get("/admin/leaks/roster").status_code == 409
        assert len(t.calls) == calls, "an invalid key makes no more reads"


def case_a_contract_error_is_an_error_and_never_replaces_the_last_good_copy():
    for label, bad in [("4xx", {**CREATORS, "status": 404, "response": {"error": "not_found"}}),
                       ("bad json", {**CREATORS, "raw": b"<html>oops"}),
                       ("null body", {**CREATORS, "response": None}),
                       ("no creators list", {**CREATORS, "response": {"creators": {"w_x": {}}}}),
                       ("not an object", {**CREATORS, "response": ["w_miavale_0001"]})]:
        _connect()
        with _tracker() as t, _live({}):
            _enrol_three(t)
            t.routes["/v1/creators"] = CREATORS
            good = _roster()
            t.routes["/v1/creators"] = bad
            r = OWNER_A.get("/admin/leaks/roster")
            t.routes["/v1/creators"] = DOWN
            stale = _roster()
        assert (r.status_code, r.json()["detail"]) == (502, "The removal service gave an answer the CRM cannot read"), \
            (label, r.text)
        assert stale["stale"] is True and stale["fetched_at"] == good["fetched_at"], (label, stale)
        assert stale["rows"] == good["rows"] and stale["rows"][0]["reachable"] is True, label


def case_a_malformed_creator_entry_is_unreadable():
    mia, rowan = CREATORS["response"]["creators"]
    for label, bad in [("counts a list", {"counts": [1, 2]}),
                       ("count a string", {"counts": {**mia["counts"], "live": "1"}}),
                       ("count a bool", {"counts": {**mia["counts"], "live": True}}),
                       ("count missing", {"counts": {k: v for k, v in mia["counts"].items() if k != "live"}}),
                       ("timestamp a number", {"last_checked_at": 1764216300}),
                       ("paused_since an object", {"paused_since": {"at": "2026-11-20"}}),
                       ("seeded missing", {"seeded": None})]:
        _connect()
        with _tracker() as t, _live({}):
            _enrol_three(t)
            creators = [{**mia, **bad}, rowan]
            t.routes["/v1/creators"] = {**CREATORS, "response": {**CREATORS["response"], "creators": creators}}
            r = OWNER_A.get("/admin/leaks/roster")
        assert r.status_code == 502, label


def case_the_roster_passes_this_week_through_and_a_bad_this_week_reads_null():
    mia, rowan = CREATORS["response"]["creators"]
    week = mia["this_week"]
    assert week["state"] == "complete" and rowan["this_week"]["state"] == "paused"
    assert mia["next_refresh_at"] == "2026-11-28T04:00:00Z" and rowan["next_refresh_at"] is None
    states = [(st, {**week, "state": st}, {**week, "state": st})
              for st in ("pending", "complete", "partial", "coverage_reduced", "paused")]
    for label, this_week, want in [
        *states,
        ("unknown keys dropped", {**week, "lanes": ["x"], "watch_id": "w_other"}, week),
        ("missing", None, None),
        ("not an object", "complete", None),
        ("unknown state", {**week, "state": "done"}, None),
        ("count a bool", {**week, "new": True}, None),
        ("count a string", {**week, "gone": "1"}, None),
        ("count missing", {k: v for k, v in week.items() if k != "came_back"}, None),
        ("since a number", {**week, "since": 20261121}, None),
        ("a pre-change today only", {**week, "day": "2026-11-27", "since": None}, None),
    ]:
        _connect()
        with _tracker() as t, _live({}):
            _enrol_three(t)
            entry = {k: v for k, v in mia.items() if k != "this_week"} if this_week is None \
                else {**mia, "this_week": this_week}
            t.routes["/v1/creators"] = {**CREATORS, "response": {**CREATORS["response"], "creators": [entry, rowan]}}
            body = _roster()
        assert body["rows"][0] == {**_local(CREATOR, "creator_a", "miavale"), "reachable": True,
                                   **_service(MIA_W), "this_week": want}, (label, body["rows"][0])
        assert body["rows"][1]["this_week"] == rowan["this_week"] and body["rows"][1]["next_refresh_at"] is None, label
        assert body["rows"][2]["this_week"] is None, label


def case_service_without_this_week_next_refresh_at_or_new_today_still_reads():
    mia, rowan = CREATORS["response"]["creators"]
    old = [{**{k: v for k, v in c.items() if k not in ("this_week", "next_refresh_at", "counts")},
            "counts": {k: v for k, v in c["counts"].items() if k != "new_today"},
            "today": {"day": "2026-11-27", "state": "complete", "new": 1, "first_scan": 0, "came_back": 0, "gone": 0}}
           for c in (mia, rowan)]
    _connect()
    with _tracker() as t, _live({}):
        _enrol_three(t)
        t.routes["/v1/creators"] = {**CREATORS, "response": {**CREATORS["response"], "creators": old}}
        body = _roster()
    assert [(r["this_week"], r["next_refresh_at"], r["reachable"]) for r in body["rows"]] == [(None, None, True)] * 3, body
    assert not any("today" in r for r in body["rows"]), body


def case_a_next_refresh_at_that_is_not_a_string_is_unreadable():
    mia, rowan = CREATORS["response"]["creators"]
    _connect()
    with _tracker() as t, _live({}):
        _enrol_three(t)
        t.routes["/v1/creators"] = {**CREATORS, "response": {**CREATORS["response"],
                                                             "creators": [{**mia, "next_refresh_at": 1764302400}, rowan]}}
        r = OWNER_A.get("/admin/leaks/roster")
    assert r.status_code == 502, r.text


def case_a_key_save_drops_the_agencys_cached_copy():
    _connect()
    with _tracker() as t, _live({}):
        _enrol_three(t)
        t.routes["/v1/creators"] = CREATORS
        assert _roster()["rows"][0]["reachable"] is True
        t.answer = ME
        assert _put(KEY_2).status_code == 200
        t.routes["/v1/creators"] = DOWN
        body = _roster()
    assert body["stale"] is False and [r["reachable"] for r in body["rows"]] == [False, False, False], body


def case_clearing_the_key_with_enrolled_creators_is_refused():
    _connect()
    with _tracker() as t, _live({}):
        _enrol_three(t)
        t.routes["/v1/creators"] = CREATORS
        assert _roster()["rows"][0]["reachable"] is True
        r = _put("")
        assert r.status_code == 409, r.text
        assert r.json()["detail"] == "Stop tracking every Creator before disconnecting"
        assert _stored() == KEY_1
        assert len(_watches()) == 3


def case_the_identity_is_checked_like_the_form():
    bad = [
        ("handle short", {"username": "m"}), ("handle long", {"username": "a" * 65}),
        ("handle space", {"username": "mia vale"}), ("handle missing", {"username": None}),
        ("too many aliases", {"aliases": ["alias1", "alias2", "alias3", "alias4", "alias5", "alias6"]}),
        ("alias short", {"aliases": ["abc"]}), ("alias long", {"aliases": ["a" * 65]}),
        ("alias short without _ . -", {"aliases": ["a.b-c"]}), ("alias short once decoded", {"aliases": ["a%2Eb_c"]}),
        ("alias short with a bad byte", {"aliases": ["ab%FF"]}),
        ("alias is the handle once normalised", {"aliases": ["mia.vale"]}),
        ("alias twice once normalised", {"aliases": ["mia.v", "miav"]}),
        ("alias banned", {"aliases": ["OnlyFans"]}), ("alias twice", {"aliases": ["mia.v", "MIA.V"]}),
        ("alias is the handle", {"aliases": ["MiaVale"]}), ("aliases not a list", {"aliases": "mia.v"}),
        ("instagram long", {"instagram": "a" * 31}), ("instagram dash", {"instagram": "mia-vale"}),
        ("x long", {"x": "a" * 16}), ("x dot", {"x": "mia.vale"}),
        ("display name long", {"display_name": "a" * 65}),
    ]
    _connect()
    with _tracker() as t, _live({}):
        t.answer = PUT_CREATED
        for label, over in bad:
            r = _enrol({**MIA, **over})
            assert r.status_code == 422, f"{label}: {r.status_code} {r.text}"
        assert t.calls == []
        r = _enrol({**MIA, "aliases": ["alias1", "alias2", "alias3", "a.b-c_d", "a" * 64], "instagram": None, "x": "",
                    "display_name": "a" * 64})
        assert r.status_code == 200, r.text
    assert _pushed(t)[0]["instagram"] is None and _pushed(t)[0]["x"] is None
    assert _watches() and _watches()[0].instagram is None


GONE = _golden("err_410")
DELETED = _golden("delete")


def _stones() -> list[LeakWatchTombstone]:
    async def _read():
        async with get_session() as s:
            return list((await s.execute(select(LeakWatchTombstone))).scalars())
    return asyncio.run(_read())


def _drop(account: str = CREATOR, client=OWNER_A):
    return client.delete(f"/admin/leaks/watches/{account}")


def case_delete_tombstones_the_watch_and_the_creator_reads_not_tracked_at_once():
    _connect()
    with _tracker() as t, _live({}):
        t.answer = PUT_CREATED
        assert _enrol().status_code == 200
        (row,) = _watches()
        t.calls.clear()
        r = _drop()
        assert (r.status_code, r.json()) == (200, {"tracked": False}), r.text
        assert t.calls == []
        body = OWNER_A.get(f"/admin/leaks/watches/{CREATOR}").json()
        assert body["tracked"] is False, body
        assert {"account_id": CREATOR, "name": "creator_a"} in _roster()["untracked"]
        assert (_drop().status_code, _drop().json()) == (200, {"tracked": False}), "a repeat changes nothing"
    assert _watches() == []
    (stone,) = _stones()
    assert (stone.watch_id, stone.agency_user_id, stone.account_id, stone.tenant_id) == \
        (row.watch_id, IDS["agency_a_owner"], CREATOR, ME["response"]["tenant_id"])


def case_delete_is_owner_or_admin_only_inside_the_session_scope():
    _connect({"enforce": True, "roles": [], "assignments": {str(EMP_A): "team-leader", str(EMP_SCOPED): "admin"}})
    with _tracker() as t, _live({}):
        t.answer = PUT_CREATED
        assert _enrol().status_code == 200
        assert _enrol({**MIA, "username": "rowanash"}, account=SECOND).status_code == 200
        r = _drop(client=CHATTER_A)
        assert (r.status_code, r.json()["detail"]) == (403, "Only the owner or an Admin can change Leak tracking"), r.text
        for account, client in [(IDS["creator_b"], OWNER_A), ("1000999", OWNER_A), (SECOND, SCOPED)]:
            r = _drop(account, client)
            assert (r.status_code, r.json()) == (404, {"detail": "Not Found"}), (account, r.text)
        assert len(_watches()) == 2 and _stones() == []
        assert _drop(client=SCOPED).status_code == 200
    assert [w.account_id for w in _watches()] == [SECOND] and [s.account_id for s in _stones()] == [CREATOR]


def case_delete_drops_that_watch_from_the_read_cache_only():
    _connect()
    with _tracker() as t, _live({}):
        _enrol_three(t)
        t.routes["/v1/creators"] = CREATORS
        for path, name in [(f"/v1/creators/{MIA_W}/leaks", "creator_leaks"), (f"/v1/creators/{MIA_W}", "creator_one")]:
            t.routes[path] = {**_golden(name), "path": path}
        t.routes["/v1/me"] = ME
        _roster()
        assert OWNER_A.get(f"/admin/leaks/watches/{CREATOR}").json()["tracked"] is True
        agency = IDS["agency_a_owner"]
        assert any(MIA_W in path for _, path in leak_tracker._copies)
        assert _drop().status_code == 200
        assert not any(MIA_W in path for _, path in leak_tracker._copies), leak_tracker._copies
        assert set(leak_tracker._copies[(agency, "/v1/creators")][0]) == {ROWAN_W}
        t.routes["/v1/creators"] = DOWN
        stale = _roster()
    assert stale["stale"] is True and [r["account_id"] for r in stale["rows"]] == [SECOND, FANSLY], stale
    assert stale["rows"][0]["counts"] == CREATORS["response"]["creators"][1]["counts"]


def case_clearing_the_key_is_refused_while_a_tombstone_is_pending():
    _connect()
    with _tracker() as t, _live({}):
        t.answer = PUT_CREATED
        assert _enrol().status_code == 200
        assert _drop().status_code == 200
        pending = (409, "A Leak watch delete is still pending at the removal service and needs a valid key to finish. "
                        "Replace the key instead of clearing it, or try again later")
        r = _put("")
        assert (r.status_code, r.json()["detail"]) == pending, r.text
        assert _stored() == KEY_1
        t.answer = {**ERR_401, "method": "DELETE", "path": DELETED["path"]}
        asyncio.run(leak_tracker.land_tombstones())
        assert leak_tracker.key_invalid(IDS["agency_a_owner"]) and len(_stones()) == 1
        r = _put("")
        assert (r.status_code, r.json()["detail"]) == pending, r.text
        t.answer = ME
        assert _put(KEY_2).status_code == 200, "replacing the key is allowed while a delete is pending"
        t.answer = DELETED
        asyncio.run(leak_tracker.land_tombstones())
        assert _stones() == []
        assert t.calls[-1].headers["authorization"] == f"Bearer {KEY_2}"
        assert _put("").status_code == 200
    assert _stored() == ""


def case_a_drill_in_read_answered_410_drops_the_row_with_no_tombstone():
    _connect()
    with _tracker() as t, _live({}):
        _enrol_three(t)
        t.routes[f"/v1/creators/{MIA_W}/leaks"] = {**GONE, "path": f"/v1/creators/{MIA_W}/leaks"}
        t.routes["/v1/creators"] = CREATORS
        _roster()
        body = OWNER_A.get(f"/admin/leaks/watches/{CREATOR}").json()
        assert (body["tracked"], body["identity"]) == (False, None), body
        assert not any(MIA_W in path or MIA_W in json.dumps(copy) for (_, path), (copy, _) in leak_tracker._copies.items())
        t.routes["/v1/creators"] = DOWN
        roster = _roster()
    assert [w.account_id for w in _watches()] == [SECOND, FANSLY]
    assert _stones() == [], "the service already deleted it"
    assert {"account_id": CREATOR, "name": "creator_a"} in roster["untracked"]
    assert [r["account_id"] for r in roster["rows"]] == [SECOND, FANSLY], roster


def case_a_save_answered_410_drops_the_row_and_says_so():
    _connect()
    with _tracker() as t, _live({}):
        t.answer = PUT_CREATED
        assert _enrol().status_code == 200
        t.answer = {**PUT_UPDATED, "status": 410, "response": GONE["response"]}
        r = _enrol(consent=None)
        assert (r.status_code, r.json()["detail"]) == (
            409, "The removal service already deleted this watch; save again to track this Creator anew"), r.text
        assert _watches() == [] and _stones() == []
        t.answer = PUT_CREATED
        assert _enrol().status_code == 200
    assert len(_watches()) == 1


def case_every_refusal_kind_has_an_http_mapping():
    assert set(leak_tracker_api.REFUSAL_HTTP) == set(get_args(leak_tracker.RefusalKind))


if __name__ == "__main__":
    _harness.run()
