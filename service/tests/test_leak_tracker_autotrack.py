#!/usr/bin/env python3
import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import dataclasses  # noqa: E402
import inspect  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from datetime import timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

import httpx  # noqa: E402
from sqlalchemy import delete, select, update  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import account_page  # noqa: E402
import leak_tracker  # noqa: E402
import leak_tracker_api  # noqa: E402
import relay_host  # noqa: E402
import tenant_keys  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, LeakTrackerTenant, LeakWatch, LeakWatchAutoSkip, LeakWatchOptOut, LeakWatchTombstone, UserAccount,
    UserLlmKey,
)

V1 = Path(__file__).resolve().parent / "fixtures" / "leak_tracker_v1"
ME = json.loads((V1 / "me.json").read_text())["response"]
OWN_TENANT, INSTANCE_TENANT = ME["tenant_id"], "tn_instance0001"
OWN_KEY, INSTANCE_KEY = "ltk_" + "a" * 40, "ltk_" + "i" * 40
ON = {"LEAK_TRACKER_URL": "http://127.0.0.1:9", "LEAK_TRACKER_ENABLED": "1", "OI_CELL_MAP": None,
      "LEAK_TRACKER_KEY": INSTANCE_KEY}

OFF = {"leak_tracker": False}

IDS = fx.seed_two_agencies()
A, B = IDS["agency_a_owner"], IDS["agency_b_owner"]
CREATOR, SECOND, THIRD = IDS["creator_a"], "1000013", "1000014"
OWNER_A = fx.login_owner("agency_a_owner")
LIVE = {CREATOR: {"username": "MiaVale", "name": "Mia Vale"}, SECOND: {"username": "rowan_ash", "name": "Rowan"},
        THIRD: {"username": "juno.reed", "name": "Juno"}, IDS["creator_b"]: {"username": "ivy_lane", "name": "Ivy"}}


async def _seed() -> None:
    async with get_session() as s:
        for aid in (SECOND, THIRD):
            s.add(Account(id=aid, nickname=f"creator_{aid}", color="#aaaaaa"))
    async with get_session() as s:
        for aid in (SECOND, THIRD):
            s.add(UserAccount(user_id=A, account_id=aid))
        s.add(UserAccount(user_id=IDS["agency_master"], account_id=CREATOR))


asyncio.run(_seed())
SPAWNED: list = []
relay_host.spawn_bg = lambda coro, name: SPAWNED.append((name, coro))


class Tracker:
    def __init__(self):
        self.calls: list[httpx.Request] = []
        self.refuse: dict[str, dict] = {}
        self.lives: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path, bearer = request.url.path, request.headers.get("authorization", "")
        if path == "/v1/me":
            tenant = INSTANCE_TENANT if bearer == f"Bearer {INSTANCE_KEY}" else OWN_TENANT
            return httpx.Response(200, json={**ME, "tenant_id": tenant})
        if path.startswith("/v1/watches/") and request.method == "PUT":
            refused = self.refuse.get(json.loads(request.content)["username"])
            if refused is not None:
                return httpx.Response(refused["status"], json=refused["response"])
            return httpx.Response(200, json={"created": True, "seeded": False, "watch_id": path.rsplit("/", 1)[-1]})
        if path.startswith("/v1/watches/") and request.method == "DELETE":
            return httpx.Response(204)
        if path == "/v1/creators":
            return httpx.Response(200, json={"as_of": "2026-11-28T00:00:00Z", "creators": []})
        return httpx.Response(404, json={"error": "not_found"})

    def puts(self) -> list[tuple[str, dict, str]]:
        return [(r.url.path.rsplit("/", 1)[-1], json.loads(r.content), r.headers["authorization"])
                for r in self.calls if r.method == "PUT"]


@contextmanager
def _tracker(**over: str | None):
    fake = Tracker()
    real, real_me = httpx.AsyncClient, account_page.of_me
    env = {**ON, **over}
    saved = {k: os.environ.get(k) for k in env}

    async def live(account_id: str):
        fake.lives.append(account_id)
        return LIVE.get(account_id)
    leak_tracker.httpx.AsyncClient = lambda **kw: real(**{**kw, "transport": httpx.MockTransport(fake.handler)})
    account_page.of_me = live
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield fake
    finally:
        leak_tracker.httpx.AsyncClient = real
        account_page.of_me = real_me
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _reset(flags_b: dict | None = None) -> None:
    async def _wipe():
        async with get_session() as s:
            for model in (UserLlmKey, LeakTrackerTenant, LeakWatch, LeakWatchTombstone, LeakWatchOptOut,
                          LeakWatchAutoSkip):
                await s.execute(delete(model))
    asyncio.run(_wipe())
    for cache in (leak_tracker._tenants, leak_tracker._tenant_misses, leak_tracker._capped,
                  leak_tracker._ensure_asked):
        cache.clear()
    while SPAWNED:
        SPAWNED.pop()[1].close()
    for agency in (A, B):
        leak_tracker.forget_invalid(agency)
        fx.store_blob(agency, "roles", {"enforce": True, "roles": [], "assignments": {}})
    fx.store_blob(A, "flags", {})
    fx.store_blob(B, "flags", flags_b if flags_b is not None else {})


def _watches(agency: str = A) -> dict[str, LeakWatch]:
    async def _read():
        async with get_session() as s:
            return {w.account_id: w for w in (await s.scalars(
                select(LeakWatch).where(LeakWatch.agency_user_id == agency))).all()}
    return asyncio.run(_read())


def _binding(agency: str = A) -> str | None:
    return asyncio.run(leak_tracker.bound_tenant(agency))


def case_a_missing_flag_is_on_and_only_an_explicit_false_turns_it_off():
    assert leak_tracker.tracker_on({}) is True
    assert leak_tracker.tracker_on({"leak_tracker": True}) is True
    assert leak_tracker.tracker_on({"leak_tracker": False}) is False
    _reset()
    with _tracker():
        assert OWNER_A.get("/admin/settings/applied").json()["flags"]["leak_tracker"] is True
        assert OWNER_A.get("/admin/leaks/setup").status_code == 200
        fx.store_blob(A, "flags", {"leak_tracker": False})
        assert OWNER_A.get("/admin/settings/applied").json()["flags"]["leak_tracker"] is False
        assert OWNER_A.get("/admin/leaks/setup").status_code == 404


def case_the_instance_key_backs_an_agency_without_its_own_and_setup_never_shows_it():
    _reset()
    with _tracker(LEAK_TRACKER_KEY=None):
        assert OWNER_A.get("/admin/leaks/setup").json()["key"] == "missing"
    with _tracker(LEAK_TRACKER_KEY="not-a-key"):
        assert OWNER_A.get("/admin/leaks/setup").json()["key"] == "missing"
    with _tracker() as t:
        r = OWNER_A.get("/admin/leaks/setup")
        assert r.json() == {"key": "set", "masked": None, "is_owner": True, "can_write": True,
                            "brand": ME["brand"], "source": "instance", "previews": True}, r.json()
        assert INSTANCE_KEY not in r.text and INSTANCE_KEY[-4:] not in r.text
        assert OWNER_A.put("/admin/leaks/key", json={"key": OWN_KEY}).json()["source"] == "own"
        own = OWNER_A.get("/admin/leaks/setup").json()
        assert (own["source"], own["masked"]) == ("own", "••••" + OWN_KEY[-4:]), own
        assert t.calls[-1].headers["authorization"] == f"Bearer {OWN_KEY}"
        cleared = OWNER_A.put("/admin/leaks/key", json={"key": ""}).json()
        assert cleared == {"key": "missing", "masked": None, "brand": None, "source": None}, \
            "an Agency bound to its own tenant never falls back to another tenant's key"
        assert asyncio.run(leak_tracker.binding(A)) == (OWN_TENANT, False)


def _roster_then_ensure() -> dict:
    r = OWNER_A.get("/admin/leaks/roster")
    assert r.status_code == 200, r.text
    while SPAWNED:
        asyncio.run(SPAWNED.pop(0)[1])
    return r.json()


def case_the_roster_auto_tracks_every_connected_creator_once():
    _reset(flags_b=OFF)
    with _tracker() as t:
        _roster_then_ensure()
        r = OWNER_A.get("/admin/leaks/roster")
        assert {row["account_id"] for row in r.json()["rows"]} == {CREATOR, SECOND, THIRD}, r.json()
        assert r.json()["untracked"] == []
        assert SPAWNED == [], "a roster load within the gap starts no second pass"
        rows = _watches()
        assert set(rows) == {CREATOR, SECOND, THIRD}
        mia = rows[CREATOR]
        assert (mia.username, mia.display_name, mia.verified, mia.on, mia.consent_by) == \
            ("miavale", "Mia Vale", True, True, leak_tracker.AUTO_CONSENT)
        assert mia.consent_at is not None and leak_tracker.watch_synced(mia)
        assert {bearer for _, _, bearer in t.puts()} == {f"Bearer {INSTANCE_KEY}"}
        assert _binding() == INSTANCE_TENANT
        before = len(t.puts())
        _roster_then_ensure()
        asyncio.run(leak_tracker.ensure_all())
        assert len(t.puts()) == before, "idempotent"


def case_auto_track_skips_deleted_turned_off_and_tombstoned_creators():
    _reset(flags_b=OFF)
    with _tracker() as t:
        _roster_then_ensure()
        assert OWNER_A.delete(f"/admin/leaks/watches/{CREATOR}").status_code == 200
        asyncio.run(leak_tracker.land_tombstones())
        assert not asyncio.run(leak_tracker.pending(A)), "the delete landed; only the opt-out remembers it"

        async def _mark():
            async with get_session() as s:
                await s.execute(update(LeakWatch).where(LeakWatch.account_id == SECOND).values(on=False))
                await s.execute(delete(LeakWatch).where(LeakWatch.account_id == THIRD))
                s.add(LeakWatchTombstone(watch_id="w_pending_0001", agency_user_id=A, account_id=THIRD,
                                         tenant_id=INSTANCE_TENANT, requested_at=leak_tracker.datetime.utcnow()))
        asyncio.run(_mark())
        before = len(t.puts())
        roster = _roster_then_ensure()
        asyncio.run(leak_tracker.ensure_all())
        assert len(t.puts()) == before
        assert set(_watches()) == {SECOND} and _watches()[SECOND].on is False
        assert {u["account_id"] for u in roster["untracked"]} == {CREATOR, THIRD}


def case_the_hourly_sync_tracks_new_connects_and_honours_an_explicit_false():
    _reset(flags_b={"leak_tracker": False})
    with _tracker() as t:
        asyncio.run(leak_tracker.sync_all())
        assert set(_watches()) == {CREATOR, SECOND, THIRD}
        assert _watches(B) == {}
        assert _watches(IDS["agency_master"]) == {}, "an overseeing master never takes an Agency's Creator"
        fx.store_blob(B, "flags", {})
        asyncio.run(leak_tracker.sync_all())
        assert set(_watches(B)) == {IDS["creator_b"]}
        assert len(t.puts()) == 4


def case_a_batch_bounds_each_pass():
    _reset(flags_b=OFF)
    saved = leak_tracker.ENSURE_BATCH
    leak_tracker.ENSURE_BATCH = 2
    try:
        with _tracker():
            asyncio.run(leak_tracker.ensure_all())
            assert len(_watches()) == 2
            asyncio.run(leak_tracker.ensure_all())
            assert len(_watches()) == 3
    finally:
        leak_tracker.ENSURE_BATCH = saved


def case_an_unreachable_service_leaves_new_rows_for_the_next_cycle():
    _reset(flags_b=OFF)
    with _tracker() as t:
        asyncio.run(leak_tracker.instance_tenant())
        t.handler = lambda request: httpx.Response(503)
        asyncio.run(leak_tracker.ensure_all())
        rows = _watches()
        assert len(rows) == 1 and not leak_tracker.watch_synced(next(iter(rows.values()))), \
            "the first failed push stops the pass"


def case_an_own_key_after_the_instance_key_moves_the_watches_to_the_own_tenant():
    _reset()
    with _tracker() as t:
        _roster_then_ensure()
        old = {aid: w.watch_id for aid, w in _watches().items()}
        r = OWNER_A.put("/admin/leaks/key", json={"key": OWN_KEY})
        assert r.status_code == 200, r.text
        assert _binding() == OWN_TENANT
        moved = _watches()
        assert all(moved[aid].watch_id != wid and moved[aid].synced_at is None for aid, wid in old.items())
        assert moved[CREATOR].consent_by == leak_tracker.AUTO_CONSENT

        async def _stones():
            async with get_session() as s:
                return {(x.watch_id, x.tenant_id) for x in (await s.scalars(select(LeakWatchTombstone))).all()}
        assert asyncio.run(_stones()) == {(wid, INSTANCE_TENANT) for wid in old.values()}
        t.calls.clear()
        asyncio.run(leak_tracker.land_tombstones())
        deletes = [(r.url.path.rsplit("/", 1)[-1], r.headers["authorization"]) for r in t.calls if r.method == "DELETE"]
        assert sorted(deletes) == sorted((wid, f"Bearer {INSTANCE_KEY}") for wid in old.values()), deletes
        assert asyncio.run(_stones()) == set()
        asyncio.run(leak_tracker.sync_watches())
        assert {bearer for _, _, bearer in t.puts()} == {f"Bearer {OWN_KEY}"}
        assert all(leak_tracker.watch_synced(w) for w in _watches().values())


def case_another_tenant_still_cannot_replace_an_own_key():
    _reset()
    with _tracker() as t:
        assert OWNER_A.put("/admin/leaks/key", json={"key": OWN_KEY}).status_code == 200
        real = t.handler

        def other(request):
            if request.url.path == "/v1/me" and request.headers["authorization"] == "Bearer ltk_" + "b" * 40:
                return httpx.Response(200, json={**ME, "tenant_id": "tn_other0002"})
            return real(request)
        t.handler = other
        r = OWNER_A.put("/admin/leaks/key", json={"key": "ltk_" + "b" * 40})
        assert (r.status_code, r.json()["detail"]) == (422, "Key belongs to another tracker account"), r.text


def _golden(name: str) -> dict:
    return json.loads((V1 / f"{name}.json").read_text())


def _skips(agency: str = A) -> dict[str, str]:
    async def _read():
        async with get_session() as s:
            return {x.account_id: x.reason for x in (await s.scalars(
                select(LeakWatchAutoSkip).where(LeakWatchAutoSkip.agency_user_id == agency))).all()}
    return asyncio.run(_read())


def _down(t: Tracker) -> None:
    def handler(request):
        t.calls.append(request)
        return httpx.Response(503)
    t.handler = handler


@contextmanager
def _batch(n: int):
    saved = leak_tracker.ENSURE_BATCH
    leak_tracker.ENSURE_BATCH = n
    try:
        yield
    finally:
        leak_tracker.ENSURE_BATCH = saved


@contextmanager
def _no_live(account_id: str):
    saved = LIVE.pop(account_id)
    try:
        yield
    finally:
        LIVE[account_id] = saved


def case_f1_a_creator_with_no_live_identity_is_skipped_for_a_day_and_never_holds_the_batch():
    _reset(flags_b=OFF)
    with _tracker() as t, _batch(1), _no_live(CREATOR):
        now = leak_tracker.datetime.utcnow()
        asyncio.run(leak_tracker.ensure_all(now))
        assert _watches() == {} and _skips() == {CREATOR: "no_identity"}
        asyncio.run(leak_tracker.ensure_all(now))
        asyncio.run(leak_tracker.ensure_all(now))
        assert set(_watches()) == {SECOND, THIRD}, "the skipped Creator no longer fills the batch"
        assert t.lives.count(CREATOR) == 1
        asyncio.run(leak_tracker.ensure_all(now + timedelta(hours=25)))
        assert t.lives.count(CREATOR) == 2, "retried after a day"


def case_f1_one_refused_creator_never_stops_the_rest():
    for golden, reason in (("err_422", "identity"), ("err_409_account_taken", "account_taken")):
        _reset(flags_b=OFF)
        with _tracker() as t:
            g = _golden(golden)
            t.refuse["miavale"] = {"status": g["status"], "response": g["response"]}
            asyncio.run(leak_tracker.ensure_all())
            assert set(_watches()) == {SECOND, THIRD}, reason
            assert _skips() == {CREATOR: reason}
            before = len(t.puts())
            asyncio.run(leak_tracker.ensure_all())
            assert len(t.puts()) == before, f"{reason}: not retried within the day"


def case_f1_the_creator_cap_stops_every_agency_on_that_key_until_the_next_day():
    _pause_case("err_409_creator_cap")


def case_f1_the_waitlist_stops_every_agency_on_that_key_until_the_next_day():
    _pause_case("err_409_waitlist")


def _pause_case(golden: str) -> None:
    _reset()
    with _tracker() as t:
        g = _golden(golden)
        for handle in ("miavale", "rowan_ash", "juno.reed", "ivy_lane"):
            t.refuse[handle] = {"status": g["status"], "response": g["response"]}
        now = leak_tracker.datetime.utcnow()
        asyncio.run(leak_tracker.ensure_all(now))
        assert len(t.puts()) == 1, [p[0] for p in t.puts()]
        assert _watches() == {} and _watches(B) == {} and _skips() == {}
        asyncio.run(leak_tracker.ensure_all(now + timedelta(hours=1)))
        assert len(t.puts()) == 1, "the cap holds for the rest of the day"
        t.refuse.clear()
        asyncio.run(leak_tracker.ensure_all(now + timedelta(hours=25)))
        assert set(_watches()) == {CREATOR, SECOND, THIRD} and set(_watches(B)) == {IDS["creator_b"]}


def case_f1_the_api_still_maps_a_cap_refusal_with_its_number():
    e = leak_tracker_api._http(leak_tracker.Refused("creator_cap", 2))
    assert (e.status_code, e.detail) == (409, "The removal service's Creator limit is reached (2)")
    assert leak_tracker_api._http(leak_tracker.Refused("unbound")).status_code == 503
    assert leak_tracker_api._http(leak_tracker.Refused("waitlist")).status_code == 409


def case_f2_one_failing_agency_never_skips_the_others_or_the_sync():
    _reset()
    real_owners, real_sync = leak_tracker.owners_of_many, leak_tracker.sync_watches
    synced = []

    async def boom(ids):
        if CREATOR in ids:
            raise RuntimeError("agency A blew up")
        return await real_owners(ids)

    async def sync(now=None):
        synced.append(True)
    leak_tracker.owners_of_many, leak_tracker.sync_watches = boom, sync
    try:
        with _tracker():
            asyncio.run(leak_tracker.sync_all())
            assert _watches() == {} and set(_watches(B)) == {IDS["creator_b"]}
            assert synced == [True]

            async def dead(now=None):
                raise RuntimeError("the whole pass blew up")
            real_all, leak_tracker.ensure_all = leak_tracker.ensure_all, dead
            try:
                asyncio.run(leak_tracker.sync_all())
            finally:
                leak_tracker.ensure_all = real_all
            assert synced == [True, True], "the sync runs even when auto-track fails"
    finally:
        leak_tracker.owners_of_many, leak_tracker.sync_watches = real_owners, real_sync


def case_f2_a_racing_insert_on_the_account_counts_as_already_tracked():
    _reset(flags_b=OFF)
    with _tracker() as t:
        asyncio.run(leak_tracker.ensure_all())
        real_watch, hidden = leak_tracker.watch, []

        async def miss_once(agency, account_id):
            if not hidden:
                hidden.append(account_id)
                return None
            return await real_watch(agency, account_id)
        leak_tracker.watch = miss_once
        try:
            ident = leak_tracker.auto_identity({"username": "MiaVale", "display_name": "Mia Vale"})
            try:
                asyncio.run(leak_tracker.save_watch(A, INSTANCE_KEY, CREATOR, ident, verified=True,
                                                    consent_by=leak_tracker.AUTO_CONSENT))
                raise AssertionError("expected a refusal")
            except leak_tracker.Refused as e:
                assert e.kind == "exists"
        finally:
            leak_tracker.watch = real_watch
        assert len(_watches()) == 3


def case_f3_the_roster_makes_no_service_or_of_call_and_queues_the_background_pass():
    _reset(flags_b=OFF)
    with _tracker() as t:
        asyncio.run(leak_tracker.instance_tenant())
        t.calls.clear()
        leak_tracker._wake.clear()
        r = OWNER_A.get("/admin/leaks/roster")
        assert r.status_code == 200, r.text
        assert r.json()["rows"] == [] and len(r.json()["untracked"]) == 3
        assert t.calls == [] and t.lives == [], "the page load stays DB-only"
        assert not leak_tracker._wake.is_set(), "a page load never wakes the tombstone pass"
        assert [name for name, _ in SPAWNED] == ["leak-auto-track"]
        _roster_then_ensure()
        assert set(_watches()) == {CREATOR, SECOND, THIRD}


def case_f3_roster_refetches_within_the_gap_start_one_pass():
    _reset(flags_b=OFF)
    with _tracker():
        for _ in range(3):
            assert OWNER_A.get("/admin/leaks/roster").status_code == 200
        assert len(SPAWNED) == 1
        leak_tracker._ensure_asked[A] -= leak_tracker.ENSURE_GAP_S
        assert OWNER_A.get("/admin/leaks/roster").status_code == 200
        assert len(SPAWNED) == 2


def case_f4_the_key_lookup_reads_only_the_db_even_with_the_service_down():
    _reset(flags_b=OFF)
    with _tracker() as t:
        asyncio.run(leak_tracker.ensure_all())
        assert asyncio.run(leak_tracker.binding(A)) == (INSTANCE_TENANT, True)
        leak_tracker._tenants.clear()
        t.calls.clear()
        _down(t)
        assert asyncio.run(leak_tracker.agency_key(A)) == (INSTANCE_KEY, True)
        assert t.calls == []
        assert OWNER_A.get("/admin/leaks/roster").status_code == 200
        assert [c.url.path for c in t.calls] == ["/v1/creators"], "no /v1/me on the way in"


def case_f4_instance_tenant_failures_back_off():
    _reset()
    with _tracker() as t:
        _down(t)
        assert asyncio.run(leak_tracker.instance_tenant()) is None
        assert asyncio.run(leak_tracker.instance_tenant()) is None
        assert len(t.calls) == 1, "the second ask waits out the backoff"
        retry_at, wait = leak_tracker._tenant_misses[INSTANCE_KEY]
        leak_tracker._tenant_misses[INSTANCE_KEY] = (0.0, wait)
        assert asyncio.run(leak_tracker.instance_tenant()) is None
        assert len(t.calls) == 2 and leak_tracker._tenant_misses[INSTANCE_KEY][1] == wait * 2


def case_f4_a_changed_instance_key_leaves_the_agency_able_to_paste_its_own():
    _reset(flags_b=OFF)
    with _tracker():
        asyncio.run(leak_tracker.ensure_all())
    other = "ltk_" + "j" * 40
    with _tracker(LEAK_TRACKER_KEY=other) as t:
        real = t.handler

        def moved(request):
            if request.url.path == "/v1/me" and request.headers["authorization"] == f"Bearer {other}":
                return httpx.Response(200, json={**ME, "tenant_id": "tn_instance0002"})
            return real(request)
        t.handler = moved
        assert asyncio.run(leak_tracker.agency_key(A)) == (other, True)
        r = OWNER_A.put("/admin/leaks/key", json={"key": OWN_KEY})
        assert r.status_code == 200, r.text
        assert asyncio.run(leak_tracker.binding(A)) == (OWN_TENANT, False)
        assert not asyncio.run(leak_tracker.pending(A)), "no delete is parked under a tenant no key reaches"
        assert _watches()
        r = OWNER_A.put("/admin/leaks/key", json={"key": ""})
        assert r.status_code == 409, r.text
        assert asyncio.run(leak_tracker.agency_key(A)) == (OWN_KEY, False)


def case_an_own_key_while_the_instance_tenant_backs_off_is_refused_503_and_moves_nothing():
    _reset(flags_b=OFF)
    with _tracker():
        asyncio.run(leak_tracker.ensure_all())
        before = {aid: w.watch_id for aid, w in _watches().items()}
        leak_tracker._tenants.clear()
        leak_tracker._tenant_misses[INSTANCE_KEY] = (time.monotonic() + 600, 30.0)
        r = OWNER_A.put("/admin/leaks/key", json={"key": OWN_KEY})
        assert r.status_code == 503, r.text
        assert asyncio.run(leak_tracker.binding(A)) == (INSTANCE_TENANT, True)
        assert {aid: w.watch_id for aid, w in _watches().items()} == before
        assert not asyncio.run(leak_tracker.pending(A))
        assert asyncio.run(leak_tracker.get_key(A, leak_tracker.PROVIDER)) == ""
        leak_tracker._tenant_misses.clear()
        assert OWNER_A.put("/admin/leaks/key", json={"key": OWN_KEY}).status_code == 200
        assert asyncio.run(leak_tracker.pending(A)), "once the instance tenant is known the old watches are tombstoned"


def case_f4_clearing_an_own_key_on_the_instance_tenant_answers_with_the_instance_brand():
    _reset(flags_b=OFF)
    with _tracker() as t:
        asyncio.run(leak_tracker.ensure_all())
        real = t.handler

        def same_tenant(request):
            if request.url.path == "/v1/me" and request.headers["authorization"] == f"Bearer {OWN_KEY}":
                return httpx.Response(200, json={**ME, "tenant_id": INSTANCE_TENANT})
            return real(request)
        t.handler = same_tenant
        assert OWNER_A.put("/admin/leaks/key", json={"key": OWN_KEY}).json()["source"] == "own"
        cleared = OWNER_A.put("/admin/leaks/key", json={"key": ""}).json()
        assert cleared == {"key": "set", "masked": None, "brand": ME["brand"], "source": "instance"}, cleared


def case_f5_save_needs_an_actor_and_gates_need_the_instance_bit():
    consent = inspect.signature(leak_tracker.save_watch).parameters["consent_by"]
    assert consent.default is inspect.Parameter.empty
    assert "instance" not in inspect.signature(leak_tracker.save_watch).parameters
    assert "instance" not in inspect.signature(leak_tracker.ensure_watches).parameters
    gates = {f.name: f for f in leak_tracker.Gates.__dataclass_fields__.values()}
    assert gates["instance"].default is dataclasses.MISSING


def case_f5_an_unbound_agency_binds_the_instance_or_saves_nothing():
    _reset(flags_b=OFF)
    with _tracker() as t:
        _down(t)
        ident = leak_tracker.auto_identity({"username": "MiaVale", "display_name": "Mia Vale"})
        try:
            asyncio.run(leak_tracker.save_watch(A, INSTANCE_KEY, CREATOR, ident, verified=True, consent_by="user:x:y"))
            raise AssertionError("expected unbound")
        except leak_tracker.Refused as e:
            assert e.kind == "unbound"
        assert _watches() == {} and _binding() is None


def case_f6_the_router_no_longer_owns_the_background_job():
    for name in ("ensure_watches", "ensure_all", "sync_all", "ENSURE_BATCH", "_save_watch", "_push"):
        assert not hasattr(leak_tracker_api, name), name
    assert (Path(__file__).resolve().parents[1] / "server.py").read_text().count("leak_tracker.sync_all") == 1


def case_f7_owners_of_many_matches_owners_of():
    many = asyncio.run(tenant_keys.owners_of_many([CREATOR, SECOND, "nobody"]))
    assert many == {CREATOR: [A], SECOND: [A]}, many
    assert asyncio.run(tenant_keys.owners_of(CREATOR)) == [A]
    assert asyncio.run(tenant_keys.owners_of_many([])) == {}


def case_f8_tombstone_key_choice():
    table = [
        ("tn_own", "tn_own", ("own_key", A)),
        ("tn_inst", "tn_own", ("inst_key", None)),
        ("tn_gone", "tn_own", ("", None)),
    ]
    for stone, bound, want in table:
        got = leak_tracker._stone_key(stone, bound, "own_key", A, "inst_key", "tn_inst")
        assert got == want, (stone, got)
    assert leak_tracker._stone_key("tn_inst", "tn_own", "own_key", A, "", None) == ("", None)


def case_f8_a_delete_during_the_pass_is_honoured_inside_the_lock():
    _reset(flags_b=OFF)
    with _tracker() as t:
        real = account_page.of_me

        async def delete_meanwhile(account_id):
            if account_id == CREATOR:
                await leak_tracker.opt_out(A, CREATOR)
            return await real(account_id)
        account_page.of_me = delete_meanwhile
        try:
            asyncio.run(leak_tracker.ensure_all())
        finally:
            account_page.of_me = real
        assert set(_watches()) == {SECOND, THIRD}


def case_f8_a_manual_track_clears_the_opt_out():
    _reset(flags_b=OFF)
    with _tracker():
        asyncio.run(leak_tracker.ensure_all())
        assert OWNER_A.delete(f"/admin/leaks/watches/{CREATOR}").status_code == 200
        asyncio.run(leak_tracker.land_tombstones())

        async def _opted():
            async with get_session() as s:
                return set((await s.scalars(select(LeakWatchOptOut.account_id))).all())
        assert asyncio.run(_opted()) == {CREATOR}
        r = OWNER_A.put(f"/admin/leaks/watches/{CREATOR}", json={"username": "miavale", "verified": True})
        assert r.status_code == 200, r.text
        assert asyncio.run(_opted()) == set()



def case_f8_a_delete_landing_during_a_manual_save_keeps_its_opt_out():
    _reset(flags_b=OFF)
    with _tracker():
        real = leak_tracker.push

        async def delete_meanwhile(agency, key, watch_id, body):
            pushed = await real(agency, key, watch_id, body)
            await leak_tracker.drop_watches(account_id=CREATOR, agency_user_id=A)
            await leak_tracker.opt_out(A, CREATOR)
            return pushed
        leak_tracker.push = delete_meanwhile
        try:
            r = OWNER_A.put(f"/admin/leaks/watches/{CREATOR}", json={"username": "miavale", "verified": True})
        finally:
            leak_tracker.push = real
        assert r.status_code == 200, r.text

        async def _opted():
            async with get_session() as s:
                return set((await s.scalars(select(LeakWatchOptOut.account_id))).all())
        assert asyncio.run(_opted()) == {CREATOR} and CREATOR not in _watches()

if __name__ == "__main__":
    _harness.run()
