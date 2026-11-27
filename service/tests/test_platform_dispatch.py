#!/usr/bin/env python3
from __future__ import annotations

import _harness  # noqa: F401 — MUST be first (binds temp DB)

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import sqlite3  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import types  # noqa: E402
import uuid  # noqa: E402
from itertools import count  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402

import accounts  # noqa: E402
import automation_executor  # noqa: E402
import automation_registry  # noqa: E402
import client_pool  # noqa: E402
import fansly_backend  # noqa: E402
from fansly_revenue import TickResult  # noqa: E402
import of_ws  # noqa: E402
import platforms  # noqa: E402
import purchase_poll  # noqa: E402
import side_effect_gate  # noqa: E402
import transaction_ingest  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AutomationRun, ScheduledJob, User, UserAccount  # noqa: E402
from of_client import OFClient  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "proxy-health"))
import watch as wt  # noqa: E402

http = _harness.make_client()
import server  # noqa: E402

AID = "acc_dispatch"
OF_METAS = (None, {"platform": "onlyfans"}, {"platform": " OnlyFans "})
UNKNOWN = {"platform": "myspace"}
UNKNOWN_AID = "acc_unknown"

accounts.get_account = lambda aid: {"id": aid} if aid == AID else None


async def _owner() -> None:
    async with get_session() as s:
        boss = User(id=uuid.uuid4().hex, username="boss", password="pw")
        s.add_all([boss, Account(id=AID, nickname=AID), Account(id=UNKNOWN_AID, nickname=UNKNOWN_AID)])
        await s.flush()
        s.add(UserAccount(user_id=boss.id, account_id=AID))


asyncio.run(_owner())


@contextlib.contextmanager
def _patched(obj, **attrs):
    saved = {k: getattr(obj, k) for k in attrs}
    for k, v in attrs.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(obj, k, v)


def _meta(meta):
    return _patched(accounts, load_meta=lambda aid, m=meta: m)


def _fansly():
    return _patched(accounts, get_platform=lambda aid: "fansly")


def _no_backend_client(aid):
    raise AssertionError(f"Backend module asked for {aid}'s client on an OnlyFans path")


class _Pooled:
    pass


def case_onlyfans_client_loads_come_from_the_pool():
    pooled = _Pooled()
    with _patched(client_pool, get=lambda aid: pooled), \
            _patched(fansly_backend, get_client=_no_backend_client):
        for meta in OF_METAS:
            with _meta(meta):
                assert server._load_client(AID) is pooled, meta
                assert automation_executor._make_client(AID) is pooled, meta


def case_fansly_client_loads_come_from_the_backend_module():
    shim = object()
    asked: list[str] = []

    def get_client(aid):
        asked.append(aid)
        return shim

    def no_pool(aid):
        raise AssertionError("client_pool asked on a Fansly path")

    with _fansly(), _patched(client_pool, get=no_pool), \
            _patched(fansly_backend, get_client=get_client):
        assert server._load_client(AID) is shim
        assert automation_executor._make_client(AID) is shim
    assert asked == [AID, AID], asked


@contextlib.contextmanager
def _unknown_account():
    with _meta(UNKNOWN), _patched(fansly_backend, get_client=_no_backend_client), \
            patch.object(OFClient, "from_account", side_effect=AssertionError("OnlyFans client built")) as build:
        yield
    build.assert_not_called()


def case_unknown_platform_client_loads_refuse_and_build_nothing():
    with _unknown_account():
        for load in (client_pool.get, automation_executor._make_client):
            try:
                load(AID)
            except platforms.UnknownPlatformKey as e:
                assert e.reason == "platform_unknown:myspace", (load, e.reason)
            else:
                raise AssertionError(f"{load} built a client for an Unknown platform account")
    assert AID not in client_pool._POOL


def case_unknown_platform_route_answers_501():
    _login()
    with _unknown_account():
        r = http.delete("/api/of/v2/messages/900544249226047488", headers={"X-Account-Id": AID})
    assert r.status_code == 501 and r.json()["detail"] == "platform_unknown:myspace", (r.status_code, r.text)


async def case_unknown_platform_job_is_skipped_without_running_the_kind():
    ran: list[str] = []

    @automation_registry.register("unknown_platform_probe")
    async def _probe(aid, payload, *, run_id):
        ran.append(aid)
        return {}

    with _unknown_account():
        job_id = await automation_executor.enqueue_job(UNKNOWN_AID, "unknown_platform_probe")
        result = await automation_executor.run_once(UNKNOWN_AID, "unknown_platform_probe")
    assert result == {"status": "skipped", "reason": "platform_unknown:myspace",
                      "run_id": result["run_id"], "job_id": job_id}, result
    assert ran == [], ran
    async with get_session() as s:
        run = await s.get(AutomationRun, result["run_id"])
        job = await s.get(ScheduledJob, job_id)
    assert (run.status, json.loads(run.stats_json)["reason"]) == ("skipped", "platform_unknown:myspace"), run.stats_json
    assert job.status == "done", job.status
    ro = sqlite3.connect(f"file:{_harness.DB_PATH}?mode=ro", uri=True)
    try:
        sql, params = wt.WATCH_SQL["platform_refusals"]
        rows = ro.execute(sql, {**params, "since": "-60 minutes"}).fetchall()
    finally:
        ro.close()
    assert (wt.PLATFORM_UNKNOWN, wt.PLATFORM_LACKS) == (side_effect_gate.PLATFORM_UNKNOWN_PREFIX,
                                                        side_effect_gate.PLATFORM_LACKS_PREFIX)
    assert rows == [("platform_unknown:myspace", UNKNOWN_AID, 1)], rows
    verdict = wt.WATCH_CHECKS["platform_refusals"].fn(types.SimpleNamespace(rows=lambda key: rows))
    assert verdict == ("alert", f"platform_unknown 1 (myspace): {UNKNOWN_AID}, 0 platform_lacks"), verdict


class _Stop(asyncio.CancelledError):
    pass


class _FakeSocket:
    def __init__(self, *args, **kwargs):
        self.args = args

    async def events(self):
        raise _Stop()
        yield  # pragma: no cover


class _Logs(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


async def _pump_once(log_lines: list[str]):
    handler = _Logs()
    server.log.addHandler(handler)
    try:
        await asyncio.wait_for(server._ws_pump_for_account(AID), timeout=5)
    except _Stop:
        pass
    except asyncio.TimeoutError:
        raise AssertionError("pump kept running: it built a real Live connection") from None
    finally:
        server.log.removeHandler(handler)
    log_lines.extend(handler.lines)


async def case_onlyfans_pump_builds_the_onlyfans_live_connection():
    built: list[_FakeSocket] = []

    class _OFSocket(_FakeSocket):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            built.append(self)

    def no_ws(client):
        raise AssertionError("Backend module's Live connection built on an OnlyFans path")

    for meta in OF_METAS:
        built.clear()
        lines: list[str] = []
        with _meta(meta), _patched(of_ws, OFWebSocket=_OFSocket), \
                _patched(fansly_backend, ws=no_ws, get_client=_no_backend_client):
            await _pump_once(lines)
        assert len(built) == 1, (meta, built)
        assert f"ws-pump[{AID}]: connecting to OF" in lines, (meta, lines)


async def case_fansly_pump_builds_the_backend_live_connection():
    shim = object()
    made: list[object] = []

    def ws(client):
        made.append(client)
        return _FakeSocket()

    def no_of_socket(*a, **k):
        raise AssertionError("OFWebSocket built on a Fansly path")

    lines: list[str] = []
    with _fansly(), _patched(of_ws, OFWebSocket=no_of_socket), \
            _patched(fansly_backend, ws=ws, get_client=lambda aid: shim):
        await _pump_once(lines)
    assert made == [shim], made
    assert f"ws-pump[{AID}]: connecting to Fansly" in lines, lines


def _third_backend(drops: list):
    mod = types.ModuleType("third_backend")
    mod.drop = lambda aid=None: drops.append(("third", aid))
    return platforms.Platform("third", "Third", "third_session.json", mod, frozenset(), "remote_login_third")


class _Retirable:
    def close_signed_sessions(self):
        pass


def case_evict_drops_every_backend_client():
    drops: list[tuple] = []
    third = _third_backend(drops)
    with _patched(platforms, ALL=(*platforms.ALL, third)), \
            _patched(fansly_backend, drop=lambda aid=None: drops.append(("fansly", aid))):
        assert client_pool.evict(AID) is True
        assert client_pool.evict(None) is True
    assert drops == [("fansly", AID), ("third", AID), ("fansly", None), ("third", None)], drops


def case_evict_still_returns_early_when_only_loses():
    drops: list[tuple] = []
    third = _third_backend(drops)
    current = _Retirable()
    client_pool._POOL[AID] = current
    try:
        with _patched(platforms, ALL=(*platforms.ALL, third)), \
                _patched(fansly_backend, drop=lambda aid=None: drops.append(("fansly", aid))):
            assert client_pool.evict(AID, only=_Retirable()) is False
        assert client_pool._POOL.get(AID) is current
    finally:
        client_pool._POOL.pop(AID, None)
    assert drops == [], drops


async def _no_revenue_tick(aid):
    raise AssertionError(f"Backend module's revenue tick ran for {aid} on an OnlyFans path")


async def case_onlyfans_revenue_lanes_run_the_ledger_path():
    asked: list[str] = []

    def client_for(aid):
        asked.append(aid)
        return None

    with _patched(transaction_ingest, _client_for=client_for), \
            _patched(fansly_backend, revenue_tick=_no_revenue_tick):
        for meta in OF_METAS:
            asked.clear()
            with _meta(meta):
                tick = await transaction_ingest.run_one_tick(AID)
                fast = await purchase_poll.run_fast_tick(AID)
            assert tick["error"] == "no_session", (meta, tick)
            assert fast == {"rows_inserted": 0, "rows_patched": 0, "error": "no_session"}, (meta, fast)
            assert asked == [AID, AID], (meta, asked)


async def case_fansly_revenue_lanes_reach_the_backend_tick():
    ticks: list[str] = []

    async def revenue_tick(aid):
        ticks.append(aid)
        return TickResult(rows_inserted=3, error="feed_partial")

    def no_ledger_client(aid):
        raise AssertionError("ledger client asked on a Fansly path")

    with _fansly(), _patched(transaction_ingest, _client_for=no_ledger_client), \
            _patched(fansly_backend, revenue_tick=revenue_tick):
        tick = await transaction_ingest.run_one_tick(AID)
        fast = await purchase_poll.run_fast_tick(AID)
    assert ticks == [AID, AID], ticks
    assert isinstance(tick.pop("duration_ms"), int), tick
    assert tick == {"rows_inserted": 3, "rows_patched": 0, "pages": 0, "error": "feed_partial"}, tick
    assert fast == {"rows_inserted": 3, "rows_patched": 0, "error": "feed_partial"}, fast


async def case_concurrent_fansly_revenue_ticks_serialize_on_the_tick_lock():
    inside = peak = 0
    held: list[bool] = []

    async def revenue_tick(aid):
        nonlocal inside, peak
        inside += 1
        peak = max(peak, inside)
        held.append(transaction_ingest._tick_locks[aid].locked())
        await asyncio.sleep(0.05)
        inside -= 1
        return TickResult(rows_inserted=0)

    with _fansly(), _patched(fansly_backend, revenue_tick=revenue_tick):
        await asyncio.gather(transaction_ingest.run_one_tick(AID), purchase_poll.run_fast_tick(AID),
                             transaction_ingest.run_one_tick(AID))
    assert peak == 1, peak
    assert held == [True, True, True], held


def _raising_shim(exc: Exception):
    shim = fansly_backend.Shim.__new__(fansly_backend.Shim)

    def _request(*_a, **_k):
        raise exc

    shim._request = _request
    return shim


def _unsend(exc: Exception):
    login = http.post("/auth/login", json={"username": "boss", "password": "pw"})
    assert login.status_code == 200, (login.status_code, login.text)
    with _fansly(), _patched(fansly_backend, get_client=lambda aid: _raising_shim(exc)):
        return http.delete("/api/of/v2/messages/900544249226047488", headers={"X-Account-Id": AID})


def case_first_request_backend_api_error_answers_502_body():
    r = _unsend(fansly_backend.APIError("message delete refused"))
    assert r.status_code == 502, (r.status_code, r.text)
    assert r.json() == {"ok": False, "error": "fansly", "detail": "message delete refused"}, r.json()


def case_backend_api_error_with_status_code_answers_it():
    class _Unsupported(fansly_backend.APIError):
        status_code = 501

    r = _unsend(_Unsupported("Fansly has no unsend"))
    assert r.status_code == 501, (r.status_code, r.text)
    assert r.json() == {"ok": False, "error": "fansly", "detail": "Fansly has no unsend"}, r.json()


from sqlalchemy import func, select  # noqa: E402

import account_health  # noqa: E402
import events  # noqa: E402
import of_stats_api  # noqa: E402
import relay_cache  # noqa: E402
import shared_refresher  # noqa: E402
import unread_total  # noqa: E402
import view_lease  # noqa: E402
from automations import auto_follow, scrape_chats  # noqa: E402

Lack = platforms.Lack
RUN_AT = "2030-01-01T00:00:00Z"
_history_fan_ids = count(10000)


class _Reached(Exception):
    pass


class _ProbeClient:
    user_id = "123"

    def __init__(self):
        self.calls: list[str] = []

    def referrals_chart(self, *, start=None, end=None):
        self.calls.append("referrals_chart")
        return {"total": 0, "delta": 0, "chartCount": [], "chartAmount": []}

    def schedule_message(self, chat_id, **kw):
        self.calls.append("schedule_message")
        return {"ok": True}

    def user_posts(self, user_id, **kw):
        self.calls.append("user_posts")
        return {"list": []}

    def get_messages(self, chat_id, *, order, **kw):
        self.calls.append(order)
        if order == "desc":
            return {"list": [{"id": chat_id * 10, "fromUser": {"id": chat_id}}], "hasMore": True}
        return {"list": []}


def _async(value):
    async def f(*_a, **_k):
        return value
    return f


def _one_flag_platform(key: str, lacks, client: _ProbeClient, *, free_follow: bool = False):
    mod = types.ModuleType(f"{key}_backend")
    mod.APIError = type("APIError", (Exception,), {})
    mod.check_sendable = lambda **kw: None
    mod.Shim = type("Shim", (), {"send_refusal": staticmethod(lambda asked: None)})
    mod.get_client = lambda aid: client
    mod.drop = lambda aid=None: None
    return platforms.Platform(key, key.title(), f"{key}_session.json", mod, frozenset(lacks),
                              f"remote_login_{key}", free_follow=free_follow)


def _login():
    login = http.post("/auth/login", json={"username": "boss", "password": "pw"})
    assert login.status_code == 200, (login.status_code, login.text)


def _post(path: str, body: dict):
    _login()
    return http.post(path, json=body, headers={"X-Account-Id": AID})


def _enqueue_recorder(order: list[str]):
    async def enqueue(request, account_id, body, *, fan_id, run_at_iso, giphy_id):
        order.append("enqueue")
        return {"job_id": 1, "fan_id": fan_id, "run_at": run_at_iso}
    return enqueue


async def _referrals_on(client: _ProbeClient) -> bool:
    client.calls.clear()
    relay_cache.invalidate("payouts", AID)
    with _patched(of_stats_api, _stats_scope_ids=lambda a: ([AID], AID)), \
            _patched(accounts, list_accounts=lambda: [{"id": AID, "has_session": True}]), \
            _patched(account_health, deactivated_ids=_async(set())):
        await of_stats_api.admin_stats_referrals(account_id=AID, from_="2026-10-01", to="2026-10-02")
    return client.calls == ["referrals_chart"]


async def _wall_media_on(client: _ProbeClient) -> bool:
    client.calls.clear()
    _login()
    r = http.get("/admin/vault/wall-media", params={"account_id": AID, "force": "true"},
                 headers={"X-Account-Id": AID})
    if r.status_code == 500:
        assert client.calls == [], client.calls
        return False
    assert r.status_code == 200 and client.calls == ["user_posts"], (r.status_code, r.text, client.calls)
    return True


async def _unread_total_on(client: _ProbeClient) -> bool:
    moved: list[str] = []
    with _patched(unread_total, ENABLED=True, _moved=lambda aid: moved.append(aid) or True):
        shown = unread_total.snapshot(AID) is not None
        unread_total.on_tick(AID)
    assert shown == bool(moved), (shown, moved)
    return shown


async def _shared_refresh_on(client: _ProbeClient) -> bool:
    readable: list[frozenset] = []

    def plan(state, inputs, knobs):
        readable.append(inputs.readable)
        raise _Reached()

    with _patched(events, open_tab_accounts=lambda: frozenset({AID})), \
            _patched(transaction_ingest, live_account_ids=_async([AID])), \
            _patched(view_lease, leased_ids=lambda: set()), \
            _patched(account_health, dead_session_map=_async({})), \
            _patched(shared_refresher, _contributors={}), \
            _patched(shared_refresher.decide, plan=plan):
        with contextlib.suppress(_Reached):
            await shared_refresher.tick()
    return readable == [frozenset({AID})]


async def _near_schedule_media_on(client: _ProbeClient) -> bool:
    order: list[str] = []
    with _patched(server, _enqueue_scheduled=_enqueue_recorder(order)):
        r = _post("/api/of/v2/scheduled-sends", {"fan_id": 7, "run_at": RUN_AT, "media_files": [11], "price": 5})
    assert r.status_code in (200, 400), (r.status_code, r.text)
    return r.status_code == 200 and order == ["enqueue"]


async def _server_schedule_on(client: _ProbeClient) -> bool:
    client.calls.clear()
    order: list[str] = []
    with _patched(server, _enqueue_scheduled=_enqueue_recorder(order)):
        r = _post("/api/of/v2/chats/7/messages/scheduled", {"text": "hi", "scheduled_date": RUN_AT})
    assert r.status_code == 200, (r.status_code, r.text)
    assert (client.calls, order) in ((["schedule_message"], []), ([], ["enqueue"])), (client.calls, order)
    return client.calls == ["schedule_message"]


async def _history_unread_gate_on(client: _ProbeClient) -> bool:
    client.calls.clear()
    await scrape_chats._scrape_one_chat(
        AID, client.user_id, client, next(_history_fan_ids), None,
        page_size=1, max_pages=1, of_unread=True,
    )
    assert client.calls in (["desc"], ["desc", "asc"]), client.calls
    return client.calls == ["desc"]


PROBES = {
    Lack.REFERRALS: _referrals_on,
    Lack.WALL_MEDIA: _wall_media_on,
    Lack.HISTORY_UNREAD_GATE: _history_unread_gate_on,
    Lack.UNREAD_TOTAL: _unread_total_on,
    Lack.SHARED_REFRESH: _shared_refresh_on,
    Lack.NEAR_SCHEDULE_MEDIA: _near_schedule_media_on,
    Lack.SERVER_SCHEDULE: _server_schedule_on,
}
UNCONSUMED = frozenset({Lack.TIP_LEDGER, Lack.PURCHASE_LINKAGE, Lack.RENEWAL_STATE,
                        Lack.LAPSE_DETECTION, Lack.RETURN_DETECTION})


async def _probe_all(client: _ProbeClient) -> dict:
    return {flag: await probe(client) for flag, probe in PROBES.items()}


async def case_onlyfans_keeps_every_policy_and_fansly_lacks_every_one():
    assert set(PROBES) == set(Lack) - UNCONSUMED
    client = _ProbeClient()
    with _patched(client_pool, get=lambda aid: client), \
            _patched(fansly_backend, get_client=lambda aid: client):
        for meta in OF_METAS:
            with _meta(meta):
                got = await _probe_all(client)
            assert got == {f: True for f in PROBES}, (meta, got)
        with _fansly():
            got = await _probe_all(client)
        assert got == {f: False for f in PROBES}, got


async def case_each_lacks_flag_turns_off_only_its_policy():
    client = _ProbeClient()
    for flag in PROBES:
        plat = _one_flag_platform("third", {flag}, client)
        with _patched(platforms, for_account=lambda aid, p=plat: p):
            got = await _probe_all(client)
        assert got == {f: f is not flag for f in PROBES}, (flag, got)


def case_free_follow_skips_the_price_check_only_when_opted_in():
    client = _ProbeClient()
    for plat, want in [(platforms.ONLYFANS, False), (platforms.FANSLY, True),
                       (_one_flag_platform("third", Lack, client), False),
                       (_one_flag_platform("fourth", (), client, free_follow=True), True)]:
        with _patched(platforms, for_account=lambda aid, p=plat: p):
            assert auto_follow.follow_is_free(AID) is want, (plat.key, want)
    for meta in OF_METAS:
        with _meta(meta):
            assert auto_follow.follow_is_free(AID) is False, meta
    with _fansly():
        assert auto_follow.follow_is_free(AID) is True


def case_near_schedule_refuses_fansly_media_or_price():
    for extra in ({"media_files": [11]}, {"price": 5}):
        order: list[str] = []
        with _fansly(), _patched(server, _enqueue_scheduled=_enqueue_recorder(order)):
            r = _post("/api/of/v2/scheduled-sends", {"fan_id": 7, "run_at": RUN_AT, **extra})
        assert r.status_code == 400, (extra, r.status_code, r.text)
        assert r.json()["detail"] == ("Fansly scheduled sends support text and GIFs for now — PPV price and "
                                      "media attachments aren't wired on the Fansly path yet."), r.json()
        assert order == [], (extra, order)
        for meta in OF_METAS:
            order = []
            with _meta(meta), _patched(server, _enqueue_scheduled=_enqueue_recorder(order)):
                r = _post("/api/of/v2/scheduled-sends", {"fan_id": 7, "run_at": RUN_AT, **extra})
            assert r.status_code == 200 and order == ["enqueue"], (meta, extra, r.status_code, r.text)


async def _scheduled_rows() -> int:
    async with get_session() as s:
        return (await s.execute(select(func.count()).select_from(ScheduledJob)
                                .where(ScheduledJob.account_id == AID))).scalar_one()


async def case_long_schedule_checks_the_fansly_send_before_enqueue():
    order: list[str] = []
    checked: list[dict] = []

    def check_sendable(**kw):
        order.append("check")
        checked.append(kw)

    body = {"text": "hi", "scheduled_date": RUN_AT, "price": 5, "media_files": [11], "previews": [11]}
    with _fansly(), _patched(fansly_backend, check_sendable=check_sendable), \
            _patched(server, _enqueue_scheduled=_enqueue_recorder(order)):
        r = _post("/api/of/v2/chats/7/messages/scheduled", body)
    assert r.status_code == 200, (r.status_code, r.text)
    assert order == ["check", "enqueue"], order
    assert checked == [{"media_files": [11], "price": 5, "previews": [11]}], checked

    before = await _scheduled_rows()
    with _fansly():
        r = _post("/api/of/v2/chats/7/messages/scheduled", {"text": "hi", "scheduled_date": RUN_AT, "price": 5})
    assert r.status_code == 400, (r.status_code, r.text)
    assert "vault attachment" in r.json()["detail"], r.json()
    assert await _scheduled_rows() == before == 0, before

    def refuse(**kw):
        raise fansly_backend.APIError("refused by the Backend module")

    with _fansly(), _patched(fansly_backend, check_sendable=refuse):
        r = _post("/api/of/v2/chats/7/messages/scheduled", {"text": "hi", "scheduled_date": RUN_AT})
    assert r.status_code == 400 and r.json()["detail"] == "refused by the Backend module", (r.status_code, r.text)
    assert await _scheduled_rows() == 0


async def case_long_schedule_on_onlyfans_reaches_the_onlyfans_queue():
    client = _ProbeClient()

    def no_check(**kw):
        raise AssertionError("Backend module's send check ran on an OnlyFans path")

    for meta in OF_METAS:
        client.calls.clear()
        order: list[str] = []
        with _meta(meta), _patched(client_pool, get=lambda aid: client), \
                _patched(fansly_backend, check_sendable=no_check, get_client=_no_backend_client), \
                _patched(server, _enqueue_scheduled=_enqueue_recorder(order)):
            r = _post("/api/of/v2/chats/7/messages/scheduled",
                      {"text": "hi", "scheduled_date": RUN_AT, "price": 5})
        assert r.status_code == 200, (meta, r.status_code, r.text)
        assert client.calls == ["schedule_message"] and order == [], (meta, client.calls, order)


@contextlib.contextmanager
def _sessions_tree():
    with tempfile.TemporaryDirectory(prefix="platform_dispatch_sessions_") as d:
        root = Path(d)
        with _patched(accounts, SESSIONS_DIR=root, ACCOUNTS_DIR=root / "accounts",
                      ACTIVE_FILE=root / "active.json", MIGRATED_MARKER=root / ".migrated"):
            accounts.ACCOUNTS_DIR.mkdir(parents=True)
            yield accounts.ACCOUNTS_DIR


def _creator(adir, aid: str, platform: str, session_file: str | None, used: str):
    accounts.save_meta(aid, {"id": aid, "nickname": aid, "platform": platform, "last_used_at": used})
    if session_file:
        (adir / aid / session_file).write_text("{}")


def case_a_creator_holding_only_its_fansly_session_file_has_a_session():
    with _sessions_tree() as adir:
        _creator(adir, "of1", "onlyfans", "latest.json", "2026-01-01")
        _creator(adir, "fy1", "fansly", fansly_backend.SESSION_FILENAME, "2026-01-02")
        _creator(adir, "none1", "fansly", None, "2026-01-03")
        roster = {m["id"]: m["has_session"] for m in accounts.list_accounts()}
        assert roster == {"of1": True, "fy1": True, "none1": False}, roster
        assert accounts.get_active_account_id() == "fy1", "the fallback skips the newest Creator without a session"
        accounts.set_active_account_id("of1")
        assert accounts.get_active_account_id() == "of1"
        accounts.set_active_account_id("none1")
        assert accounts.get_active_account_id() == "fy1"


def case_session_probes_read_every_registered_session_file():
    with _sessions_tree() as adir:
        _creator(adir, "zz1", "zz", "zz_session.json", "2026-01-01")
        with _patched(platforms, SESSION_FILES=(*platforms.SESSION_FILES, "zz_session.json")):
            assert [m["has_session"] for m in accounts.list_accounts()] == [True]
            accounts.set_active_account_id("zz1")
            assert accounts.get_active_account_id() == "zz1"
        assert [m["has_session"] for m in accounts.list_accounts()] == [False]


_harness.run()
