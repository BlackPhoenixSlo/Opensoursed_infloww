#!/usr/bin/env python3
import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import asyncio  # noqa: E402

from sqlalchemy import func, select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts  # noqa: E402
import of_call_counter  # noqa: E402
import purchase_poll_decide as decide  # noqa: E402
import server  # noqa: E402,F401 — mounts the routes
import accounts_admin_api  # noqa: E402 — after server (relay_host)
import app_open_warm  # noqa: E402
import purchase_poll  # noqa: E402
import view_lease  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Action  # noqa: E402

IDS = fx.seed_two_agencies()
A, B = IDS["creator_a"], IDS["creator_b"]
PATH = "/admin/view-lease"
POLLS: list[tuple[str, str]] = []


def _fake_poll_now(aid):
    POLLS.append((aid, of_call_counter.caller_kind()))

    async def _noop():
        return None
    return _noop()


purchase_poll.poll_now = _fake_poll_now


def _spawn_inline(coro, name):
    with of_call_counter.caller(f"loop:{name}"):
        try:
            coro.send(None)
        except StopIteration:
            return
    raise AssertionError(f"{name}: the fake poll_now never suspends")


accounts_admin_api._spawn_bg = _spawn_inline
PACED: list[list[str]] = []
NOTED: list[str] = []
app_open_warm.pace = lambda ids, poll: PACED.append(list(ids))
app_open_warm.note_read = NOTED.append


def _reset():
    view_lease._holders.clear()
    view_lease._streams.clear()
    POLLS.clear()
    PACED.clear()
    NOTED.clear()


def _renew(client, ids, selected=None, tab="t1", opened=False):
    return client.post(PATH, json={"tab": tab, "account_ids": ids, "selected": selected, "opened": opened})


def case_owner_renews():
    _reset()
    owner = fx.login_owner("agency_a_owner")
    r = _renew(owner, [A], A)
    assert r.status_code == 200, r.text
    assert r.json() == {"leased": [A], "ttl_s": view_lease.TTL_S, "warm": "none"}, r.json()
    assert view_lease.leased_ids() == {A}
    assert POLLS == [(A, "select_refresh")], POLLS
    POLLS.clear()
    assert _renew(owner, [A], A).status_code == 200 and POLLS == [], "re-renewal: no refresh"
    assert _renew(owner, [A], None).status_code == 200 and POLLS == []
    assert _renew(owner, [A], A).status_code == 200 and POLLS == [(A, "select_refresh")], "selected changed"


def case_chatter_renews():
    _reset()
    ca = fx.login_chatter("chatter_a")
    r = _renew(ca, [A, B], None)
    assert r.status_code == 200 and r.json()["leased"] == [A], r.text
    cab = fx.login_chatter("chatter_ab")
    r = _renew(cab, [A, B], B)
    assert r.status_code == 200 and r.json()["leased"] == [A, B], r.text
    assert view_lease.leased_ids() == {A, B}
    holders = set(view_lease._holders)
    assert ("chatter", IDS["chatter_a"], "t1") in holders and ("chatter", IDS["chatter_ab"], "t1") in holders


def case_other_agency_dropped():
    _reset()
    saved = accounts.is_watcher
    accounts.is_watcher = lambda a: a == "4242"
    try:
        owner = fx.login_owner("agency_a_owner")
        r = _renew(owner, [B, A, "4242", "999999", A], B)
        assert r.status_code == 200 and r.json()["leased"] == [A], r.text
        assert view_lease.leased_ids() == {A}
        assert POLLS == [] and PACED == [[A]], f"selected B ignored: {POLLS} {PACED}"
    finally:
        accounts.is_watcher = saved


def case_empty_releases():
    _reset()
    owner = fx.login_owner("agency_b_owner")
    r = _renew(owner, [], B)
    assert r.status_code == 200 and r.json()["leased"] == [B], "selected alone is leased"
    assert view_lease.leased_ids() == {B}
    r = _renew(owner, [], None)
    assert r.status_code == 200 and r.json()["leased"] == [], r.text
    assert view_lease.leased_ids() == set()


def case_no_session_401():
    _reset()
    r = _renew(_harness.make_client(), [A], A)
    assert r.status_code == 401, (r.status_code, r.text)
    assert view_lease.leased_ids() == set() and POLLS == []


def case_over_200_refused():
    _reset()
    owner = fx.login_owner("agency_a_owner")
    r = _renew(owner, [A] + [str(5_000_000 + i) for i in range(200)], A)
    assert r.status_code == 422, (r.status_code, r.text[:200])
    assert _renew(owner, [A] * 200, A).status_code == 200
    assert _renew(owner, [A], A, tab="").status_code == 422
    assert _renew(owner, [A], A, tab="x" * 65).status_code == 422
    assert _renew(owner, [A], A, tab="x" * 64).status_code == 200


def case_not_audited():
    import audit_log
    assert PATH in audit_log._AUDIT_SKIP_PREFIXES
    owner = fx.login_owner("agency_a_owner")
    for _ in range(3):
        assert _renew(owner, [A], A).status_code == 200

    async def _n():
        async with get_session() as s:
            return (await s.execute(select(func.count()).select_from(Action)
                                    .where(Action.action.like("%view-lease%")))).scalar_one()
    assert asyncio.run(_n()) == 0


def case_gain_skips_current():
    _reset()
    saved_age, saved_at = purchase_poll.last_poll_age_s, dict(app_open_warm._warmed_at)
    age: dict[str, float] = {}
    purchase_poll.last_poll_age_s = lambda a: age.get(a)
    try:
        owner = fx.login_owner("agency_a_owner")
        age[A] = decide.SELECT_MIN_AGE_S + 1.0
        assert _renew(owner, [A], None).status_code == 200 and POLLS == [], f"polled a few s ago: {POLLS}"
        assert _renew(owner, [A], A).status_code == 200 and POLLS == [(A, "select_refresh")], "a selection refreshes"
        _reset()
        age[A] = 10_000.0
        app_open_warm._warmed_at[A] = app_open_warm._clock()
        assert _renew(owner, [A], None, tab="t2").status_code == 200 and POLLS == [], f"just warmed: {POLLS}"
        _reset()
        app_open_warm._warmed_at.pop(A)
        assert _renew(owner, [A], None, tab="t3").status_code == 200 and PACED == [[A]], PACED
    finally:
        purchase_poll.last_poll_age_s = saved_age
        app_open_warm._warmed_at.clear()
        app_open_warm._warmed_at.update(saved_at)


def case_selected_min_age():
    _reset()
    saved_age = purchase_poll.last_poll_age_s
    age: dict[str, float] = {A: decide.SELECT_MIN_AGE_S - 1.0}
    purchase_poll.last_poll_age_s = lambda a: age.get(a)
    try:
        owner = fx.login_owner("agency_a_owner")
        assert _renew(owner, [A], A).status_code == 200 and POLLS == [], f"polled under the floor: {POLLS}"
        assert _renew(owner, [A], None).status_code == 200 and POLLS == []
        age[A] = decide.SELECT_MIN_AGE_S + 0.1
        assert _renew(owner, [A], A).status_code == 200 and POLLS == [(A, "select_refresh")], POLLS
    finally:
        purchase_poll.last_poll_age_s = saved_age


def case_gains_paced():
    _reset()
    saved_at = dict(app_open_warm._warmed_at)
    app_open_warm._warmed_at.clear()
    try:
        cab = fx.login_chatter("chatter_ab")
        assert _renew(cab, [A, B], None).status_code == 200
        assert POLLS == [] and PACED == [[A, B]], (POLLS, PACED)
        _reset()
        assert _renew(cab, [A, B], B, tab="t2").status_code == 200
        assert POLLS == [(B, "select_refresh")] and PACED == [[A]] and NOTED == [B], (POLLS, PACED, NOTED)
        _reset()
        assert _renew(cab, [A, B], B, tab="t3", opened=True).status_code == 200
        assert PACED == [], f"an opening post's gains are the warm's: {PACED}"
    finally:
        app_open_warm._warmed_at.clear()
        app_open_warm._warmed_at.update(saved_at)


def case_opened_starts_warm():
    _reset()
    calls: list[tuple] = []
    answer: list[dict] = [{}]

    async def _start(principal, account_ids, leased_first=(), *, refreshed=()):
        calls.append((principal, list(account_ids), set(leased_first), list(refreshed)))
        return answer[0]

    saved = app_open_warm.start
    app_open_warm.start = _start
    try:
        owner = fx.login_owner("agency_a_owner")
        r = _renew(owner, [A], A)
        assert r.status_code == 200 and r.json()["warm"] == "none" and calls == [], (r.json(), calls)
        _reset()
        answer[0] = {A: "started"}
        r = _renew(owner, [A], A, tab="t2", opened=True)
        assert r.status_code == 200 and r.json()["warm"] == "started", r.text
        assert len(calls) == 1, calls
        principal, ids, leased, refreshed = calls[0]
        assert principal == ("user", IDS["agency_a_owner"]), principal
        assert ids == [A] and leased == {A}, (ids, leased)
        assert refreshed == [A] and POLLS == [(A, "select_refresh")], (refreshed, POLLS)
        answer[0] = {A: "reused"}
        r = _renew(fx.login_chatter("chatter_ab"), [], None, tab="t3", opened=True)
        assert r.status_code == 200 and r.json()["warm"] == "reused", r.text
        assert calls[-1][0][0] == "chatter" and sorted(calls[-1][1]) == sorted([A, B]), calls[-1]
        answer[0] = {}
        assert _renew(owner, [], None, tab="t4", opened=True).json()["warm"] == "none"
    finally:
        app_open_warm.start = saved


def case_opened_gains_go_to_warm():
    _reset()
    calls: list[tuple] = []

    async def _start(principal, account_ids, leased_first=(), *, refreshed=()):
        calls.append((set(leased_first), list(refreshed)))
        return {}

    saved, saved_at = app_open_warm.start, dict(app_open_warm._warmed_at)
    app_open_warm.start = _start
    app_open_warm._warmed_at.clear()
    try:
        owner = fx.login_chatter("chatter_ab")
        assert _renew(owner, [A, B], A, opened=True).status_code == 200
        assert POLLS == [(A, "select_refresh")] and calls[0][1] == [A], (POLLS, calls)
        assert {A, B} <= calls[0][0], calls
        _reset()
        assert _renew(owner, [A, B], None, tab="t2", opened=True).status_code == 200
        assert POLLS == [] and calls[1][1] == [] and {A, B} <= calls[1][0], (POLLS, calls)
    finally:
        app_open_warm.start = saved
        app_open_warm._warmed_at.update(saved_at)




def _stream_leased(client, qs="", referer="https://app.example/messages-pro"):
    seen: list[set] = []
    original = server.sse_stream

    async def _two(_request, _scope, **_kw):
        yield b": a\n\n"
        seen.append(view_lease.leased_ids())
        yield b": b\n\n"
    server.sse_stream = _two
    try:
        r = client.get(f"/events{qs}", headers={"Referer": referer} if referer else {})
    finally:
        server.sse_stream = original
    return (seen[0] if seen else None), r.status_code


def case_legacy_stream_leases():
    _reset()
    owner = fx.login_owner("agency_a_owner")
    assert _stream_leased(owner) == ({A}, 200), "a pre-1a tab: its own Creators, not Agency B's"
    assert view_lease.leased_ids() == set() and view_lease._streams == {}, "ended: dropped"
    assert _stream_leased(owner, "?scope=all&lease=1") == (set(), 200), "the app since 1a"
    assert _stream_leased(owner, referer=None) == (set(), 200), "no Referer: not a browser page"
    assert _stream_leased(fx.login_chatter("chatter_a"), f"?scope=model:{A}") == ({A}, 200)
    assert _stream_leased(fx.login_chatter("chatter_ab")) == ({A, B}, 200)
    saved = accounts.is_watcher
    accounts.is_watcher = lambda a: a == B
    try:
        assert _stream_leased(fx.login_chatter("chatter_ab")) == ({A}, 200), "a watcher is never leased"
    finally:
        accounts.is_watcher = saved
    assert _stream_leased(_harness.make_client()) == (None, 401)
    assert view_lease.leased_ids() == set()


_harness.run()
