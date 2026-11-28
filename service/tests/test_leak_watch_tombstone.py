#!/usr/bin/env python3
import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import uuid  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402

import httpx  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import account_page  # noqa: E402
import accounts as account_registry  # noqa: E402
import leak_tracker  # noqa: E402
import notifications_api  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import LeakTrackerTenant, LeakWatch, LeakWatchOptOut, LeakWatchTombstone, User, UserAccount, UserLlmKey  # noqa: E402

V1 = Path(__file__).resolve().parent / "fixtures" / "leak_tracker_v1"
TRACKER = "http://127.0.0.1:9"
ON = {"LEAK_TRACKER_URL": TRACKER, "LEAK_TRACKER_ENABLED": "1", "OI_CELL_MAP": None}

IDS = fx.seed_two_agencies()
AGENCY_A, AGENCY_B = IDS["agency_a_owner"], IDS["agency_b_owner"]
CREATOR, OTHER = IDS["creator_a"], IDS["creator_b"]
OWNER_A = fx.login_owner("agency_a_owner")
MASTER = fx.login_owner("agency_master")
PENDING = "Leak watch deletes are still pending at the removal service; try again later"
PENDING_OFF = ("Leak watch deletes are still pending at the removal service and the Leak tracker is switched off on "
               "this server; switch it back on so they can finish, then try again")


def _golden(name: str) -> dict:
    return json.loads((V1 / f"{name}.json").read_text())


DELETED = _golden("delete")
PUT_CREATED = _golden("put_created")
ERR_401 = _golden("err_401")
LIMITED = _golden("err_429")
TENANT = _golden("me")["response"]["tenant_id"]
KEY_1, KEY_2, KEY_3 = "ltk_" + "a" * 40, "ltk_" + "b" * 40, "ltk_" + "c" * 40
ASKED = datetime(2026, 11, 27, 11, 0)


class Tracker:
    def __init__(self):
        self.answer: dict | Exception = DELETED
        self.by_watch: dict[str, dict | Exception] = {}
        self.calls: list[httpx.Request] = []
        self.before_delete = None

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.before_delete:
            await self.before_delete()
        answer = self.by_watch.get(request.url.path.rsplit("/", 1)[-1], self.answer)
        if isinstance(answer, Exception):
            raise answer
        assert request.method == answer["method"], request.method
        response = answer["response"]
        if answer is PUT_CREATED:
            response = {**response, "watch_id": request.url.path.rsplit("/", 1)[-1]}
        return httpx.Response(answer["status"], json=response)

    def deletes(self) -> list[tuple[str, str]]:
        return [(r.url.path.removeprefix("/v1/watches/"), r.url.params["requested_at"]) for r in self.calls
                if r.method == "DELETE"]


@contextmanager
def _tracker(env: dict | None = None):
    fake = Tracker()
    real = httpx.AsyncClient
    want = {**ON, **(env or {})}
    saved = {k: os.environ.get(k) for k in want}
    leak_tracker.httpx.AsyncClient = lambda **kw: real(**{**kw, "transport": httpx.MockTransport(fake.handler)})
    for k, v in want.items():
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


@contextmanager
def _no_live():
    real = account_page.of_me

    async def none(_account_id: str):
        return None
    account_page.of_me = none
    try:
        yield
    finally:
        account_page.of_me = real


def _reset() -> None:
    async def _wipe():
        async with get_session() as s:
            await s.execute(delete(UserLlmKey).where(UserLlmKey.provider == "leak_tracker"))
            await s.execute(delete(LeakTrackerTenant))
            await s.execute(delete(LeakWatch))
            await s.execute(delete(LeakWatchTombstone))
            await s.execute(delete(LeakWatchOptOut))
        for agency, key in ((AGENCY_A, KEY_1), (AGENCY_B, KEY_2)):
            await leak_tracker.store_key(agency, key)
            await leak_tracker.bind_tenant(agency, TENANT)
    asyncio.run(_wipe())
    leak_tracker._wake.clear()
    for agency in (AGENCY_A, AGENCY_B):
        leak_tracker.forget_invalid(agency)
        fx.store_blob(agency, "flags", {"leak_tracker": True})
        fx.store_blob(agency, "roles", {"enforce": True, "roles": [], "assignments": {}})


def _row(account: str, *, agency: str = AGENCY_A) -> str:
    req = PUT_CREATED["request"]
    watch_id = f"w_{account}_{uuid.uuid4().hex[:6]}"

    async def _add():
        async with get_session() as s:
            s.add(LeakWatch(agency_user_id=agency, account_id=account, watch_id=watch_id, platform=req["platform"],
                            username=f"{req['username']}_{account}", verified=req["verified"], display_name=req["display_name"],
                            aliases_json=json.dumps(req["aliases"]), consent_at=ASKED,
                            consent_by="user:fixture:agency_a_owner", synced_at=ASKED, synced_paused=False))
    asyncio.run(_add())
    return watch_id


def _stone(account: str, *, agency: str = AGENCY_A, tenant: str = TENANT, at: datetime = ASKED) -> str:
    watch_id = f"w_{account}_{uuid.uuid4().hex[:6]}"

    async def _add():
        async with get_session() as s:
            s.add(LeakWatchTombstone(watch_id=watch_id, agency_user_id=agency, account_id=account, tenant_id=tenant,
                                     requested_at=at))
    asyncio.run(_add())
    return watch_id


def _stones() -> dict[str, LeakWatchTombstone]:
    async def _read():
        async with get_session() as s:
            return {t.watch_id: t for t in (await s.execute(select(LeakWatchTombstone))).scalars()}
    return asyncio.run(_read())


def _rows() -> dict[str, LeakWatch]:
    async def _read():
        async with get_session() as s:
            return {w.watch_id: w for w in (await s.execute(select(LeakWatch))).scalars()}
    return asyncio.run(_read())


def _land() -> None:
    asyncio.run(leak_tracker.land_tombstones())


def case_delete_writes_the_tombstone_and_drops_the_row_together_and_wakes_the_job():
    _reset()
    watch_id = _row(CREATOR)
    leak_tracker._wake.clear()
    with _tracker() as t:
        before = datetime.utcnow().replace(microsecond=0)
        r = OWNER_A.delete(f"/admin/leaks/watches/{CREATOR}")
        assert (r.status_code, r.json()) == (200, {"tracked": False}), r.text
        assert t.calls == [], "the route only writes; the job sends the DELETE"
    (stone,) = _stones().values()
    assert (stone.watch_id, stone.agency_user_id, stone.account_id, stone.tenant_id, stone.attempts, stone.last_error) == \
        (watch_id, AGENCY_A, CREATOR, TENANT, 0, None)
    assert before <= stone.requested_at <= datetime.utcnow()
    assert _rows() == {}
    assert leak_tracker._wake.is_set(), "the delete wakes the tombstone job"


def case_the_job_retries_until_a_2xx_carrying_the_original_request_time():
    _reset()
    watch_id = _stone(CREATOR)
    golden_query = DELETED["path"].split("?", 1)[1]
    with _tracker() as t:
        for answer, error in [(httpx.ConnectError("refused"), "unreachable"),
                              ({**LIMITED, "method": "DELETE", "status": 500}, "service_error"),
                              ({**LIMITED, "method": "DELETE", "status": 503}, "unreachable"),
                              ({**LIMITED, "method": "DELETE"}, "http_429")]:
            t.answer = answer
            _land()
            stone = _stones()[watch_id]
            assert stone.last_error == error, (error, stone.last_error)
        assert _stones()[watch_id].attempts == 4
        t.answer = DELETED
        _land()
        assert _stones() == {}, "a 2xx deletes the tombstone"
        assert t.deletes() == [(watch_id, "2026-11-27T11:00:00Z")] * 5, t.deletes()
        assert golden_query == "requested_at=2026-11-27T11:00:00Z"
        assert {r.headers["authorization"] for r in t.calls} == {f"Bearer {KEY_1}"}
        t.calls.clear()
        _land()
        assert t.calls == []


def case_a_404_or_410_delete_counts_as_delivered():
    for status in (404, 410):
        _reset()
        watch_id = _stone(CREATOR)
        with _tracker() as t:
            t.answer = {**LIMITED, "method": "DELETE", "status": status}
            _land()
            assert t.deletes() == [(watch_id, "2026-11-27T11:00:00Z")], (status, t.deletes())
        assert _stones() == {}, status
        assert not asyncio.run(leak_tracker.pending(AGENCY_A)), status


def case_a_tenant_mismatch_keeps_the_tombstone_and_the_rest_still_land():
    _reset()
    foreign = _stone(CREATOR, tenant="tn_other0002")
    mine = _stone(CREATOR)
    b = _stone(OTHER, agency=AGENCY_B)
    with _tracker() as t:
        _land()
        assert sorted(w for w, _ in t.deletes()) == sorted([mine, b]), t.deletes()
        assert {r.headers["authorization"] for r in t.calls} == {f"Bearer {KEY_1}", f"Bearer {KEY_2}"}
    left = _stones()
    assert list(left) == [foreign]
    assert (left[foreign].last_error, left[foreign].attempts) == ("tenant_mismatch", 0)


def case_the_switch_reading_off_still_lands_but_no_url_or_cell_mode_sends_nothing():
    for label, env, lands in [("switch env off", {"LEAK_TRACKER_ENABLED": "0"}, True),
                              ("switch unset", {"LEAK_TRACKER_ENABLED": None}, True),
                              ("url unset", {"LEAK_TRACKER_URL": None}, False),
                              ("cell mode", {"OI_CELL_MAP": "/nonexistent/placement.json"}, False)]:
        _reset()
        watch_id = _stone(CREATOR)
        with _tracker(env) as t:
            _land()
            assert [w for w, _ in t.deletes()] == ([watch_id] if lands else []), label
        assert (_stones() == {}) is lands, label


def case_no_key_or_a_refused_key_skips_the_agency_and_a_401_marks_it():
    _reset()
    a = _stone(CREATOR)
    b = _stone(OTHER, agency=AGENCY_B)
    asyncio.run(leak_tracker.store_key(AGENCY_B, ""))
    with _tracker() as t:
        t.answer = {**ERR_401, "method": "DELETE"}
        _land()
        assert [w for w, _ in t.deletes()] == [a]
        t.calls.clear()
        _land()
        assert t.calls == [], "a key known refused is not sent again"
    left = _stones()
    assert set(left) == {a, b}
    assert (left[a].last_error, left[a].attempts) == ("key_invalid", 1)
    assert left[b].attempts == 0
    assert leak_tracker.key_invalid(AGENCY_A)


def case_a_late_retry_after_a_re_enrol_names_only_the_old_watch_id():
    _reset()
    old = _row(CREATOR)
    with _tracker() as t, _no_live():
        t.answer = {**LIMITED, "method": "DELETE", "status": 503}
        assert OWNER_A.delete(f"/admin/leaks/watches/{CREATOR}").status_code == 200
        _land()
        assert [w for w, _ in t.deletes()] == [old]
        t.answer = PUT_CREATED
        r = OWNER_A.put(f"/admin/leaks/watches/{CREATOR}", json={
            "username": "miavale", "display_name": "Mia Vale", "aliases": [], "consent": True})
        assert r.json() == {"synced": True}, r.text
        (new,) = _rows()
        assert new != old
        t.calls.clear()
        t.answer = DELETED
        _land()
        assert [w for w, _ in t.deletes()] == [old], t.deletes()
        assert all(new not in str(r.url) for r in t.calls)
    assert _stones() == {} and list(_rows()) == [new]


def case_the_loop_runs_on_a_wake_and_every_ten_minutes():
    assert (leak_tracker.TOMBSTONES_EVERY_S, leak_tracker.TOMBSTONES_FIRST_AFTER_S) == (600, 60)
    runs: list[float] = []
    real_land, real_wake = leak_tracker.land_tombstones, leak_tracker._wake

    async def count():
        runs.append(asyncio.get_running_loop().time())
        if len(runs) == 1:
            raise RuntimeError("one bad pass never ends the loop")

    async def drive():
        leak_tracker._wake = asyncio.Event()
        task = asyncio.create_task(leak_tracker.tombstone_loop())
        await asyncio.sleep(0.05)
        assert runs == [], "the first pass waits"
        leak_tracker._wake.set()
        await asyncio.sleep(0.05)
        assert len(runs) == 1, runs
        leak_tracker._wake.set()
        await asyncio.sleep(0.05)
        assert len(runs) == 2, runs
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    leak_tracker.land_tombstones = count
    try:
        asyncio.run(drive())
    finally:
        leak_tracker.land_tombstones, leak_tracker._wake = real_land, real_wake


def case_the_request_time_survives_a_later_pass():
    _reset()
    at = datetime(2026, 11, 20, 9, 30, 15)
    watch_id = _stone(CREATOR, at=at)
    with _tracker() as t:
        t.answer = httpx.ReadTimeout("slow")
        _land()
        t.answer = DELETED
        _land()
        assert t.deletes() == [(watch_id, "2026-11-20T09:30:15Z")] * 2
    assert _stones() == {}


@contextmanager
def _kept_dir(account: str):
    d = account_registry.ACCOUNTS_DIR / account
    keep = d.with_name(account + ".kept")
    shutil.copytree(d, keep)
    try:
        account_registry.upsert_account(account, nickname="Mia Vale")
        yield
    finally:
        if d.exists():
            shutil.rmtree(d)
        shutil.move(keep, d)


def case_remove_fans_out_to_every_agencys_watch_of_that_creator():
    _reset()
    a, b, kept = _row(CREATOR), _row(CREATOR, agency=AGENCY_B), _row(OTHER)
    leak_tracker._wake.clear()
    with _tracker() as t, _kept_dir(CREATOR):
        r = OWNER_A.delete(f"/admin/accounts/{CREATOR}")
        assert (r.status_code, r.json()) == (200, {"ok": True}), r.text
        assert t.calls == []
        stones = _stones()
        assert {w: (s.agency_user_id, s.account_id, s.tenant_id) for w, s in stones.items()} == \
            {a: (AGENCY_A, CREATOR, TENANT), b: (AGENCY_B, CREATOR, TENANT)}
        assert list(_rows()) == [kept], "another Creator's watch stays"
        assert leak_tracker._wake.is_set()
        _land()
        assert sorted(w for w, _ in t.deletes()) == sorted([a, b])
        assert {r.headers["authorization"] for r in t.calls} == {f"Bearer {KEY_1}", f"Bearer {KEY_2}"}
    assert _stones() == {}


def case_a_watch_with_no_binding_refuses_remove_and_keeps_every_row():
    _reset()
    a, b = _row(CREATOR), _row(CREATOR, agency=AGENCY_B)

    async def _unbind():
        async with get_session() as s:
            await s.execute(delete(LeakTrackerTenant).where(LeakTrackerTenant.agency_user_id == AGENCY_B))
    asyncio.run(_unbind())
    with _tracker() as t, _kept_dir(CREATOR):
        r = OWNER_A.delete(f"/admin/accounts/{CREATOR}")
        assert (r.status_code, r.json()["detail"]) == (409, "Connect the removal service again before deleting"), r.text
        assert (account_registry.ACCOUNTS_DIR / CREATOR).is_dir(), "a refused Remove removes nothing"
        assert t.calls == []
    assert sorted(_rows()) == sorted([a, b]) and _stones() == {}


def case_unlink_tombstones_only_that_agencys_watch():
    _reset()
    a, b, kept = _row(CREATOR), _row(CREATOR, agency=AGENCY_B), _row(OTHER)
    leak_tracker._wake.clear()

    async def _relink():
        async with get_session() as s:
            if await s.get(UserAccount, (AGENCY_A, CREATOR)) is None:
                s.add(UserAccount(user_id=AGENCY_A, account_id=CREATOR))
    try:
        with _tracker() as t:
            r = MASTER.request("DELETE", f"/admin/users/{AGENCY_A}/accounts/{CREATOR}",
                               json={"admin_password": os.environ["ADMIN_PASSWORD"]})
            assert r.status_code == 200, r.text
            assert t.calls == []
        (stone,) = _stones().values()
        assert (stone.watch_id, stone.agency_user_id, stone.account_id) == (a, AGENCY_A, CREATOR)
        assert sorted(_rows()) == sorted([b, kept])
        assert leak_tracker._wake.is_set()
    finally:
        asyncio.run(_relink())


def case_remove_and_unlink_block_enrollment_before_removing_an_untracked_account():
    async def live(_account):
        return {"username": "miavale", "name": "Mia Vale"}

    for unlink in (True, False):
        _reset()
        attempts = []
        async def enroll_during_removal(_account, *_owners):
            attempts.append(await leak_tracker.ensure_watches(AGENCY_A, KEY_1, [CREATOR]))

        try:
            with (_tracker() as t, _kept_dir(CREATOR),
                  patch.object(notifications_api, "drop_pinned", enroll_during_removal),
                  patch.object(account_page, "of_me", live)):
                t.answer = PUT_CREATED
                if unlink:
                    r = MASTER.request("DELETE", f"/admin/users/{AGENCY_A}/accounts/{CREATOR}",
                                       json={"admin_password": os.environ["ADMIN_PASSWORD"]})
                else:
                    r = OWNER_A.delete(f"/admin/accounts/{CREATOR}")
                assert r.status_code == 200, r.text
                assert attempts == [0] and not t.calls and not _rows()
        finally:
            async def relink():
                async with get_session() as s:
                    if await s.get(UserAccount, (AGENCY_A, CREATOR)) is None:
                        s.add(UserAccount(user_id=AGENCY_A, account_id=CREATOR))
            asyncio.run(relink())


def case_reconnecting_resumes_auto_enrollment_except_after_user_delete():
    async def live(_account):
        return {"username": "miavale", "name": "Mia Vale"}

    async def relink():
        async with get_session() as s:
            if await s.get(UserAccount, (AGENCY_A, CREATOR)) is None:
                s.add(UserAccount(user_id=AGENCY_A, account_id=CREATOR))

    for unlink, user_deleted in ((True, False), (True, True), (False, False), (False, True)):
        _reset()
        with _tracker() as t, _kept_dir(CREATOR), patch.object(account_page, "of_me", live):
            try:
                _row(CREATOR)
                t.answer = DELETED
                if user_deleted:
                    assert OWNER_A.delete(f"/admin/leaks/watches/{CREATOR}").status_code == 200
                    asyncio.run(leak_tracker.land_tombstones())
                    assert not _stones()
                if unlink:
                    r = MASTER.request("DELETE", f"/admin/users/{AGENCY_A}/accounts/{CREATOR}",
                                       json={"admin_password": os.environ["ADMIN_PASSWORD"]})
                else:
                    r = OWNER_A.delete(f"/admin/accounts/{CREATOR}")
                assert r.status_code == 200, r.text
                asyncio.run(leak_tracker.land_tombstones())
                assert not _stones()
                assert asyncio.run(leak_tracker.ensure_watches(AGENCY_A, KEY_1, [CREATOR])) == 0
                if not unlink:
                    assert account_registry.get_account(CREATOR) is None
                    account_registry.upsert_account(CREATOR)
                linked = MASTER.post(f"/admin/users/{AGENCY_A}/accounts", json={
                    "account_id": CREATOR, "admin_password": os.environ["ADMIN_PASSWORD"],
                })
                assert linked.status_code == 200, linked.text
                t.answer = PUT_CREATED
                assert asyncio.run(leak_tracker.ensure_watches(AGENCY_A, KEY_1, [CREATOR])) == int(not user_deleted)
            finally:
                asyncio.run(relink())


def _agency_user(key: str = KEY_3) -> str:
    uid = uuid.uuid4().hex

    async def _add():
        async with get_session() as s:
            s.add(User(id=uid, username=f"leak_{uid[:8]}", password=fx.PASSWORD))
        await leak_tracker.store_key(uid, key)
        await leak_tracker.bind_tenant(uid, TENANT)
    asyncio.run(_add())
    return uid


def _left(uid: str) -> tuple[bool, str | None, str | None]:
    async def _read():
        async with get_session() as s:
            user = await s.get(User, uid) is not None
            key = await s.scalar(select(UserLlmKey.api_key).where(UserLlmKey.user_id == uid,
                                                                  UserLlmKey.provider == "leak_tracker"))
            tenant = await s.scalar(select(LeakTrackerTenant.tenant_id).where(LeakTrackerTenant.agency_user_id == uid))
            return user, key, tenant
    return asyncio.run(_read())


def _delete_user(uid: str) -> httpx.Response:
    return MASTER.request("DELETE", f"/admin/users/{uid}",
                          json={"confirm": "delete", "admin_password": os.environ["ADMIN_PASSWORD"]})


def case_user_delete_lands_every_delete_inline_then_deletes_the_user():
    _reset()
    uid = _agency_user()
    one, two, earlier = _row(CREATOR, agency=uid), _row(OTHER, agency=uid), _stone(CREATOR, agency=uid)
    other_agency = _stone(CREATOR)
    leak_tracker._wake.clear()
    with _tracker() as t:
        r = _delete_user(uid)
        assert (r.status_code, r.json()) == (200, {"ok": True, "deleted_user_id": uid}), r.text
        assert sorted(w for w, _ in t.deletes()) == sorted([one, two, earlier]), t.deletes()
        assert {r.headers["authorization"] for r in t.calls} == {f"Bearer {KEY_3}"}
        assert {r.extensions["timeout"]["read"] for r in t.calls} == {15.0}
    assert _left(uid) == (False, None, None), "the cascade drops the key and the binding"
    assert list(_stones()) == [other_agency], "another Agency's tombstone waits for the job"
    assert _rows() == {}


def case_user_delete_keeps_a_watch_enrolled_during_the_inline_drain():
    _reset()
    uid = _agency_user()
    old = _row(CREATOR, agency=uid)
    late = []
    from concurrent.futures import ThreadPoolExecutor

    with _tracker() as t, ThreadPoolExecutor(1) as pool:
        async def enrol():
            late.append(await asyncio.get_running_loop().run_in_executor(pool, lambda: _row(OTHER, agency=uid)))

        t.before_delete = enrol
        r = _delete_user(uid)
        assert r.status_code == 409, r.text
        assert list(_rows()) == late
        assert [w for w, _ in t.deletes()] == [old]
        t.before_delete = None
        assert _delete_user(uid).status_code == 200
        assert [w for w, _ in t.deletes()] == [old, *late]


def case_user_delete_caps_the_whole_inline_drain():
    _reset()
    uid = _agency_user()
    first, second, third = (_stone(account, agency=uid) for account in (CREATOR, OTHER, "extra"))
    with _tracker() as t:
        async def delayed():
            await asyncio.sleep(0.12)
        t.before_delete = delayed
        old_budget = leak_tracker.INLINE_BUDGET_S
        leak_tracker.INLINE_BUDGET_S = 0.2
        try:
            r = _delete_user(uid)
        finally:
            leak_tracker.INLINE_BUDGET_S = old_budget
        assert r.status_code == 409, r.text
        assert [w for w, _ in t.deletes()] == [first, second]
        assert set(_stones()) == {second, third}
        assert _left(uid)[0]


def case_tombstone_batch_stops_on_rate_limit_or_service_down():
    for answer, error, stops in [
        ({**LIMITED, "method": "DELETE", "status": 500}, "service_error", False),
        (httpx.ReadTimeout("slow"), "service_error", False),
        ({**LIMITED, "method": "DELETE"}, "http_429", True),
        (httpx.ConnectError("refused"), "unreachable", True),
    ]:
        _reset()
        uid = _agency_user()
        first, second = (_stone(account, agency=uid) for account in ("first", "second"))
        with _tracker() as t:
            t.by_watch[first] = answer
            r = _delete_user(uid)
            assert (r.status_code, r.json()["detail"]) == (409, PENDING), r.text
            assert [w for w, _ in t.deletes()] == ([first] if stops else [first, second]), error
        assert _left(uid) == (True, KEY_3, TENANT)
        left = _stones()
        assert set(left) == ({first, second} if stops else {first}) and left[first].last_error == error
        with _tracker():
            assert _delete_user(uid).status_code == 200
        assert _left(uid) == (False, None, None) and _stones() == {}


def case_user_delete_with_no_key_or_the_service_down_answers_409():
    for label, down in [("no key", False), ("service down", True)]:
        _reset()
        uid = _agency_user()
        watch_id = _row(CREATOR, agency=uid)
        if not down:
            asyncio.run(leak_tracker.store_key(uid, ""))
        with _tracker() as t:
            t.answer = httpx.ConnectError("refused")
            r = _delete_user(uid)
            assert (r.status_code, r.json()["detail"]) == (409, PENDING), (label, r.text)
            assert [w for w, _ in t.deletes()] == ([watch_id] if down else []), label
        assert _left(uid)[0] and _left(uid)[2] == TENANT, label
        assert list(_stones()) == [watch_id], label


def case_user_delete_with_the_tracker_off_on_this_server_says_how_to_finish():
    for label, env in [("url unset", {"LEAK_TRACKER_URL": None}),
                       ("cell mode", {"OI_CELL_MAP": "/nonexistent/placement.json"})]:
        _reset()
        uid = _agency_user()
        watch_id = _row(CREATOR, agency=uid)
        with _tracker(env) as t:
            r = _delete_user(uid)
            assert (r.status_code, r.json()["detail"]) == (409, PENDING_OFF), (label, r.text)
            assert t.calls == [], label
        assert _left(uid) == (True, KEY_3, TENANT), label
        assert list(_stones()) == [watch_id], label


if __name__ == "__main__":
    _harness.run()
