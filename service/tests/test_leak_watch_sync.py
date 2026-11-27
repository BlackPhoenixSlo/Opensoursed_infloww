#!/usr/bin/env python3
import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import uuid  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

import httpx  # noqa: E402
from sqlalchemy import create_engine, delete, select, update  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import account_health  # noqa: E402
import account_page  # noqa: E402
import leak_tracker  # noqa: E402
from db.engine import get_session, sync_database_url  # noqa: E402
from db.models import Account, AccountHealth, LeakWatch, LeakWatchTombstone, UserAccount, UserLlmKey  # noqa: E402

V1 = Path(__file__).resolve().parent / "fixtures" / "leak_tracker_v1"
TRACKER = "http://127.0.0.1:9"
ON = {"LEAK_TRACKER_URL": TRACKER, "LEAK_TRACKER_ENABLED": "1", "OI_CELL_MAP": None}

IDS = fx.seed_two_agencies()
AGENCY_A, AGENCY_B = IDS["agency_a_owner"], IDS["agency_b_owner"]
CREATOR, SECOND, THIRD, OTHER = IDS["creator_a"], "1000011", "1000012", IDS["creator_b"]
OWNER_A = fx.login_owner("agency_a_owner")


def _golden(name: str) -> dict:
    return json.loads((V1 / f"{name}.json").read_text())


PUT_UPDATED = _golden("put_updated")
CREATOR_CAP = _golden("err_409_creator_cap")
LIMITED = _golden("err_429")
ERR_401 = _golden("err_401")
GONE = _golden("err_410")
DOWN = httpx.ConnectError("refused")
KEY_1, KEY_2 = "ltk_" + "a" * 40, "ltk_" + "b" * 40
TODAY = datetime(2026, 11, 27, 10, 0)
TOMORROW = datetime(2026, 11, 28, 0, 30)


async def _seed_accounts() -> None:
    async with get_session() as s:
        for aid in (SECOND, THIRD):
            s.add(Account(id=aid, nickname=f"creator_{aid}", color="#aaaaaa"))
    async with get_session() as s:
        for aid in (SECOND, THIRD):
            s.add(UserAccount(user_id=AGENCY_A, account_id=aid))

asyncio.run(_seed_accounts())


class Tracker:
    def __init__(self):
        self.answer: dict | Exception = PUT_UPDATED
        self.by_watch: dict[str, dict | Exception] = {}
        self.calls: list[httpx.Request] = []
        self.during = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.during:
            self.during(request)
        answer = self.by_watch.get(request.url.path.rsplit("/", 1)[-1], self.answer)
        if isinstance(answer, Exception):
            raise answer
        assert request.method == answer["method"], request.method
        return httpx.Response(answer["status"], json=answer["response"])

    def pushed(self) -> dict[str, dict]:
        return {r.url.path.removeprefix("/v1/watches/"): json.loads(r.content) for r in self.calls}


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


def _reset() -> None:
    async def _wipe():
        async with get_session() as s:
            await s.execute(delete(UserLlmKey).where(UserLlmKey.provider == "leak_tracker"))
            await s.execute(delete(LeakWatch))
            await s.execute(delete(AccountHealth))
        await account_health.load_write_gate()
        await leak_tracker.store_key(AGENCY_A, KEY_1)
    asyncio.run(_wipe())
    for agency in (AGENCY_A, AGENCY_B):
        leak_tracker.forget_invalid(agency)
        fx.store_blob(agency, "flags", {"leak_tracker": True})
        fx.store_blob(agency, "roles", {"enforce": True, "roles": [], "assignments": {}})


def _row(account: str, *, agency: str = AGENCY_A, on: bool = True, synced_at: datetime | None = TODAY,
         synced_paused: bool | None = False, username: str | None = None) -> str:
    req = PUT_UPDATED["request"]
    watch_id = f"w_{account}_{uuid.uuid4().hex[:6]}"

    async def _add():
        async with get_session() as s:
            s.add(LeakWatch(agency_user_id=agency, account_id=account, watch_id=watch_id, on=on,
                            platform=req["platform"], username=username or f"{req['username']}{account[-2:]}",
                            verified=req["verified"], display_name=req["display_name"],
                            aliases_json=json.dumps(req["aliases"]), instagram=req["instagram"], x=req["x"],
                            consent_at=TODAY, consent_by="user:fixture:agency_a_owner", synced_at=synced_at,
                            synced_paused=synced_paused))
    asyncio.run(_add())
    return watch_id


def _body(account: str, *, paused: bool) -> dict:
    req = PUT_UPDATED["request"]
    return {**req, "account_id": account, "username": f"{req['username']}{account[-2:]}", "paused": paused}


def _rows() -> dict[str, LeakWatch]:
    async def _read():
        async with get_session() as s:
            return {w.watch_id: w for w in (await s.execute(select(LeakWatch))).scalars()}
    return asyncio.run(_read())


def _sync(now: datetime = TODAY) -> None:
    asyncio.run(leak_tracker.sync_watches(now))


def case_only_dirty_rows_or_a_changed_paused_bit_are_pushed_then_the_daily_full_push():
    _reset()
    clean = _row(CREATOR)
    never = _row(SECOND, synced_at=None, synced_paused=None)
    switched = _row(THIRD, on=False)
    with _tracker() as t:
        _sync()
        assert t.pushed() == {never: _body(SECOND, paused=False), switched: _body(THIRD, paused=True)}, t.pushed()
        assert {r.method for r in t.calls} == {"PUT"}
        assert {r.headers["authorization"] for r in t.calls} == {f"Bearer {KEY_1}"}
        rows = _rows()
        assert (rows[never].synced_at, rows[never].synced_paused) == (TODAY, False)
        assert (rows[switched].synced_at, rows[switched].synced_paused) == (TODAY, True)
        assert rows[clean].synced_at == TODAY
        t.calls.clear()
        _sync(TODAY + timedelta(hours=13))
        assert t.calls == [], "nothing changed the same UTC day"
        _sync(TOMORROW)
        assert t.pushed() == {clean: _body(CREATOR, paused=False), never: _body(SECOND, paused=False),
                              switched: _body(THIRD, paused=True)}, t.pushed()
        assert {w.synced_at for w in _rows().values()} == {TOMORROW}
        t.calls.clear()
        _sync(TOMORROW + timedelta(hours=1))
        assert t.calls == [], "one full push per UTC day"


def case_paused_for_toggle_off_flag_off_and_deactivated():
    for label, setup in [
            ("toggle off", lambda: _row(CREATOR, on=False)),
            ("flag off", lambda: (_row(CREATOR), fx.store_blob(AGENCY_A, "flags", {"leak_tracker": False}))[0]),
            ("deactivated", lambda: (_row(CREATOR), asyncio.run(account_health.deactivate(CREATOR)))[0])]:
        _reset()
        watch_id = setup()
        with _tracker() as t:
            _sync()
            assert t.pushed() == {watch_id: _body(CREATOR, paused=True)}, (label, t.pushed())
        assert _rows()[watch_id].synced_paused is True, label
    _reset()
    watch_id = _row(CREATOR, synced_paused=True)
    with _tracker() as t:
        _sync()
        assert t.pushed() == {watch_id: _body(CREATOR, paused=False)}, "resumed"
    assert [leak_tracker.paused(on, flag, off) for on, flag, off in
            [(True, True, False), (False, True, False), (True, False, False), (True, True, True)]] == \
        [False, True, True, True]


def case_a_switch_that_reads_off_or_an_unset_url_makes_no_call_at_all():
    for label, env in [("switch env off", {"LEAK_TRACKER_ENABLED": "0"}), ("switch unset", {"LEAK_TRACKER_ENABLED": None}),
                       ("url unset", {"LEAK_TRACKER_URL": None}), ("url not https", {"LEAK_TRACKER_URL": "http://tracker.example.test"})]:
        _reset()
        _row(CREATOR, synced_at=None, synced_paused=None)
        with _tracker(env) as t:
            _sync()
            _sync(TOMORROW)
            assert t.calls == [], label
        assert all(w.synced_at is None for w in _rows().values()), label


def case_the_job_is_wanted_only_with_the_url_set_and_cell_mode_off():
    with _tracker():
        assert leak_tracker.jobs_on()
    with _tracker({"LEAK_TRACKER_URL": None}):
        assert not leak_tracker.jobs_on()
    with _tracker({"OI_CELL_MAP": "/nonexistent/placement.json"}):
        assert not leak_tracker.jobs_on()
    assert (leak_tracker.SYNC_EVERY_S, leak_tracker.SYNC_FIRST_AFTER_S) == (3600, 60)


def case_agencies_with_no_key_or_a_refused_key_are_skipped():
    _reset()
    a = _row(CREATOR, synced_at=None, synced_paused=None)
    _row(OTHER, agency=AGENCY_B, synced_at=None, synced_paused=None)
    with _tracker() as t:
        _sync()
        assert list(t.pushed()) == [a], t.pushed()
    _reset()
    _row(CREATOR, synced_at=None, synced_paused=None)
    leak_tracker._invalid.add(AGENCY_A)
    with _tracker() as t:
        _sync()
        assert t.calls == []


def case_a_row_saved_while_the_service_was_down_is_pushed_by_the_next_run_and_reads_synced():
    _reset()
    real = account_page.of_me

    async def none(_account_id: str):
        return None
    account_page.of_me = none
    try:
        with _tracker() as t:
            t.answer = DOWN
            r = OWNER_A.put(f"/admin/leaks/watches/{CREATOR}", json={
                "username": "miavale", "display_name": "Mia Vale", "aliases": ["mia.vale.x"], "consent": True})
            assert r.json() == {"synced": False}, r.text
            assert OWNER_A.get(f"/admin/leaks/watches/{CREATOR}").json()["synced"] is False
            t.answer = PUT_UPDATED
            t.calls.clear()
            asyncio.run(leak_tracker.sync_watches())
            ((watch_id, body),) = t.pushed().items()
            assert body["username"] == "miavale" and body["paused"] is False and body["account_id"] == CREATOR
            t.by_watch["leaks"], t.by_watch[watch_id] = _golden("creator_leaks"), _golden("creator_one")
            assert OWNER_A.get(f"/admin/leaks/watches/{CREATOR}").json()["synced"] is True
            t.calls.clear()
            asyncio.run(leak_tracker.sync_watches())
            assert t.calls == [], "synced rows wait for the daily push"
    finally:
        account_page.of_me = real
    assert _rows()[watch_id].synced_at is not None


def case_the_pass_never_reads_the_live_identity_or_lists_creators():
    _reset()
    _row(CREATOR)
    _row(SECOND)
    real, asked = account_page.of_me, []

    async def spy(account_id: str):
        asked.append(account_id)
        return {"username": "renamed", "name": "Renamed"}
    account_page.of_me = spy
    try:
        with _tracker() as t:
            _sync(TOMORROW)
            assert len(t.calls) == 2
            assert all(r.method == "PUT" and r.url.path.startswith("/v1/watches/") for r in t.calls)
            assert all(b["username"] != "renamed" for b in t.pushed().values())
    finally:
        account_page.of_me = real
    assert asked == []


def case_a_429_or_refused_key_stops_that_agency_and_a_down_service_stops_the_run():
    refused = {**PUT_UPDATED, "status": 401, "response": ERR_401["response"]}
    for label, answer, want_pushed, want_synced in [
            ("429", LIMITED, "a1 a2 b", "a1 b"),
            ("401", refused, "a1 a2 b", "a1 b"),
            ("connect error", DOWN, "a1 a2", "a1"),
            ("connect timeout", httpx.ConnectTimeout("slow"), "a1 a2", "a1"),
            ("502", {**LIMITED, "status": 502}, "a1 a2", "a1"),
            ("503", {**LIMITED, "status": 503}, "a1 a2", "a1"),
            ("504", {**LIMITED, "status": 504}, "a1 a2", "a1"),
            ("500", {**LIMITED, "status": 500}, "a1 a2 a3 b", "a1 a3 b"),
            ("read timeout", httpx.ReadTimeout("slow"), "a1 a2 a3 b", "a1 a3 b")]:
        _reset()
        asyncio.run(leak_tracker.store_key(AGENCY_B, KEY_2))
        ids = {"a1": _row(CREATOR, synced_at=None, synced_paused=None),
               "a2": _row(SECOND, synced_at=None, synced_paused=None),
               "a3": _row(THIRD, synced_at=None, synced_paused=None),
               "b": _row(OTHER, agency=AGENCY_B, synced_at=None, synced_paused=None)}
        with _tracker() as t:
            t.by_watch[ids["a2"]] = answer
            _sync()
            assert [r.url.path.rsplit("/", 1)[-1] for r in t.calls] == [ids[k] for k in want_pushed.split()], label
        rows = _rows()
        assert {k for k, w in ids.items() if rows[w].synced_at is not None} == set(want_synced.split()), label
    leak_tracker.forget_invalid(AGENCY_A)
    _reset()
    _row(CREATOR, synced_at=None, synced_paused=None)
    with _tracker() as t:
        t.answer = refused
        _sync()
    assert leak_tracker.key_invalid(AGENCY_A), "a 401 marks the key no longer valid"


def case_a_refused_row_stays_dirty_and_the_rest_are_pushed():
    _reset()
    capped = _row(CREATOR, synced_at=None, synced_paused=None)
    fine = _row(SECOND, synced_at=None, synced_paused=None)
    with _tracker() as t:
        t.by_watch[capped] = CREATOR_CAP
        _sync()
        assert set(t.pushed()) == {capped, fine}
        rows = _rows()
        assert rows[capped].synced_at is None and rows[fine].synced_at == TODAY
        t.calls.clear()
        _sync(TODAY + timedelta(hours=1))
        assert list(t.pushed()) == [capped], "retried next run"


def case_a_put_answered_410_drops_the_row_with_no_tombstone_and_the_rest_are_pushed():
    _reset()
    gone = _row(CREATOR, synced_at=None, synced_paused=None)
    fine = _row(SECOND, synced_at=None, synced_paused=None)
    leak_tracker._copies[(AGENCY_A, "/v1/creators")] = ({gone: {}, fine: {}}, "2026-11-27T10:00:00+00:00")
    leak_tracker._copies[(AGENCY_A, f"/v1/creators/{gone}/leaks?limit=100")] = ({}, "2026-11-27T10:00:00+00:00")
    try:
        with _tracker() as t:
            t.by_watch[gone] = {**PUT_UPDATED, "status": GONE["status"], "response": GONE["response"]}
            _sync()
            assert set(t.pushed()) == {gone, fine}
            assert list(_rows()) == [fine] and _rows()[fine].synced_at == TODAY
            t.calls.clear()
            _sync(TOMORROW)
            assert list(t.pushed()) == [fine]

        async def _stones():
            async with get_session() as s:
                return list((await s.execute(select(LeakWatchTombstone))).scalars())
        assert asyncio.run(_stones()) == [], "the service already deleted it"
        assert [k for k in leak_tracker._copies if k[0] == AGENCY_A] == [(AGENCY_A, "/v1/creators")]
        assert set(leak_tracker._copies[(AGENCY_A, "/v1/creators")][0]) == {fine}
    finally:
        leak_tracker.drop_copies(AGENCY_A)
    assert not leak_tracker.gone(httpx.Response(410, json={"error": "other"}))
    assert not leak_tracker.gone(httpx.Response(410, content=b"<html>"))


def case_an_edit_during_the_push_is_not_marked_synced():
    _reset()
    watch_id = _row(CREATOR, synced_at=None, synced_paused=None)
    engine = create_engine(sync_database_url())

    def edit(_request):
        with engine.begin() as c:
            c.execute(update(LeakWatch).where(LeakWatch.watch_id == watch_id)
                      .values(display_name="Edited", updated_at=datetime.utcnow() + timedelta(seconds=5)))
    with _tracker() as t:
        t.during = edit
        _sync()
        assert len(t.calls) == 1
    engine.dispose()
    row = _rows()[watch_id]
    assert row.display_name == "Edited" and row.synced_at is None, "the edit is pushed by the next run"


def case_an_identity_saved_mid_run_is_pushed_again_by_the_next_run_whatever_the_stale_push_answered():
    real = account_page.of_me

    async def none(_account_id: str):
        return None
    account_page.of_me = none
    try:
        for label, answer in [("200", PUT_UPDATED), ("read timeout", httpx.ReadTimeout("slow")),
                              ("500", {**LIMITED, "status": 500}), ("503", {**LIMITED, "status": 503})]:
            _reset()
            first = _row(SECOND, synced_at=None, synced_paused=None)
            raced = _row(CREATOR, synced_at=None, synced_paused=None)
            saved: list[int] = []
            with _tracker() as t:
                def save(request, t=t, first=first, raced=raced, saved=saved, answer=answer):
                    if saved or not request.url.path.endswith(first):
                        return
                    saved.append(1)
                    r = OWNER_A.put(f"/admin/leaks/watches/{CREATOR}", json={"username": "mianew", "display_name": "Mia New"})
                    assert r.json() == {"synced": True}, r.text
                    t.by_watch[raced] = answer
                t.during = save
                _sync()
                sent = [(r.url.path.rsplit("/", 1)[-1], json.loads(r.content)["username"]) for r in t.calls]
                assert sent == [(first, _body(SECOND, paused=False)["username"]), (raced, "mianew"),
                                (raced, _body(CREATOR, paused=False)["username"])], (label, sent)
                rows = _rows()
                assert rows[first].synced_at == TODAY, label
                assert rows[raced].username == "mianew" and rows[raced].synced_at is None, (label, "the stale push re-dirties it")
                t.calls.clear()
                t.during = None
                t.by_watch.clear()
                _sync(TODAY + timedelta(hours=1))
                assert t.pushed() == {raced: {**_body(CREATOR, paused=False), "username": "mianew", "display_name": "Mia New",
                                              "aliases": [], "instagram": None, "x": None, "verified": False}}, (label, t.pushed())
                assert _rows()[raced].synced_at == TODAY + timedelta(hours=1), label
    finally:
        account_page.of_me = real


if __name__ == "__main__":
    _harness.run()
