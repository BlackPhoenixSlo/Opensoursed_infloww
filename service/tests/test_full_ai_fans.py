#!/usr/bin/env python3
"""test_full_ai_fans — the Fans list (spec 04b ticket 76): pure `in_fans` and the loader with a faked OF client.

  case_in_fans_table          both empty; include only (member / not); exclude only (member / not); both = out;
                              include read None; exclude read None; both None
  case_empty_lists_no_client  `fans` empty: the client is never built, 0 OF calls (load and claimed_ids)
  case_listed_by_lists        on an include list = listed; on none = not; on include and exclude = not
  case_read_failure           the list read raising (or the client not building): listed false for every
                              Fan, who_owns not_listed, claimed_ids empty
  case_claimed_ids_and_cache  3 Fans (in, out, excluded), live: only the first; a second call inside 5 min
                              makes no further OF call; while off: no OF call at all
  case_config_change_bites    a new `fans` in the stored config changes claimed_ids on the next call; an OF
                              membership change shows after the cache window, no restart
  case_cached_listed_never_reads_of  the help bot's peek: unknown / everyone / malformed / fresh / stale /
                              failed / exclude wins / list-id order; zero client builds, zero crawls
  case_folder_read_failure_is_stamped_then_cleared  a failed folder read stamps the failure (not listed);
                              a later good read clears it

Run: ./venv/bin/python service/tests/test_full_ai_fans.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import contextlib  # noqa: E402
import json  # noqa: E402
from datetime import datetime  # noqa: E402

import automation_executor as ax  # noqa: E402
from automations import autoreply  # noqa: E402
from automations import full_ai_owner_io as io  # noqa: E402
from automations.full_ai_owner import Stop, in_fans, who_owns  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, AutomationRule  # noqa: E402

ANCHOR = datetime(2026, 11, 15, 12, 0, 0)
_n = 0


class ListOF:
    """OF's `/lists/{id}/users` read only: {list_id: [fan ids]}; `fail` raises on every read."""

    def __init__(self, lists: dict[int, list[int]], *, fail: bool = False):
        self.lists, self.fail, self.reads = lists, fail, []

    def list_users_in(self, list_id, *, limit=20, offset=0):
        self.reads.append(int(list_id))
        if self.fail:
            raise RuntimeError("OF 500 on /lists/users")
        return [{"id": i} for i in self.lists.get(int(list_id), [])[offset:offset + limit]]


@contextlib.contextmanager
def _client(fake):
    """`ax._make_client` builds `fake` (None = raise); counts builds."""
    built = []
    real = ax._make_client

    def make(account_id):
        built.append(account_id)
        if fake is None:
            raise RuntimeError("no session")
        return fake
    ax._make_client = make
    try:
        yield built
    finally:
        ax._make_client = real


@contextlib.contextmanager
def _live():
    real = io._live

    async def on(account_id):
        return True
    io._live = on
    try:
        yield
    finally:
        io._live = real


async def _account(fans: dict | None) -> str:
    global _n
    _n += 1
    aid = f"acc-fans-{_n}"
    async with get_session() as s:
        s.add(Account(id=aid))
        s.add(AutomationRule(account_id=aid, name="Full AI Chat", kind="full_ai_chat", trigger_json="{}",
                             steps_json="{}", is_enabled=True))
        if fans is not None:
            s.add(AccountAiConfig(account_id=aid, full_ai_config_json=json.dumps(
                {"checkpoint": {"fans": fans}, "rev": 1})))
    return aid


async def _set_fans(aid: str, fans: dict) -> None:
    async with get_session() as s:
        (await s.get(AccountAiConfig, aid)).full_ai_config_json = json.dumps({"checkpoint": {"fans": fans}, "rev": 2})


def case_in_fans_table():
    E, I, X, B = ({"include": [], "exclude": []}, {"include": [1], "exclude": []},
                  {"include": [], "exclude": [2]}, {"include": [1], "exclude": [2]})
    rows = [
        (E, None, None, True),                      # both empty: every Fan (reads ignored)
        (I, True, None, True), (I, False, None, False),
        (X, None, True, False), (X, None, False, True),
        (B, True, True, False),                     # member of both: exclude wins
        (B, True, False, True), (B, False, False, False),
        (I, None, None, False), (B, None, False, False),   # include read failed
        (X, None, None, False), (B, True, None, False),    # exclude read failed
        (B, None, None, False),                     # both failed
        ({}, None, None, True),
    ]
    for cfg, i, x, want in rows:
        assert in_fans(cfg, i, x) is want, (cfg, i, x)


async def case_empty_lists_no_client():
    for fans in (None, {"include": [], "exclude": []}):
        aid = await _account(fans)
        fake = ListOF({})
        with _client(fake) as built, _live():
            assert (await io.load(aid, 1, ANCHOR)).listed is True
            assert await io.claimed_ids(aid, [1, 2]) == {1, 2}
        assert built == [] and fake.reads == [], (built, fake.reads)


async def case_listed_by_lists():
    aid = await _account({"include": [501], "exclude": [502]})
    fake = ListOF({501: [1, 3], 502: [3]})
    with _client(fake):
        want = {1: True, 2: False, 3: False}
        for f, w in want.items():
            assert (await io.load(aid, f, ANCHOR)).listed is w, (f, w)
    # a client the caller hands in is used as is (no build)
    other = await _account({"include": [601], "exclude": []})
    mine = ListOF({601: [7]})
    with _client(None) as built:
        assert (await io.load(other, 7, ANCHOR, client=mine)).listed is True
    assert built == [] and set(mine.reads) == {601}, (built, mine.reads)   # page + empty terminal page


async def case_read_failure():
    aid = await _account({"include": [701], "exclude": []})
    with _client(ListOF({}, fail=True)), _live():
        f = await io.load(aid, 1, ANCHOR)
        assert f.listed is False and who_owns(f) == Stop("not_listed"), f
        assert await io.claimed_ids(aid, [1, 2, 3]) == set()
    ex = await _account({"include": [], "exclude": [702]})
    with _client(None), _live():                          # the client will not build
        assert (await io.load(ex, 1, ANCHOR)).listed is False
        assert await io.claimed_ids(ex, [1]) == set()


async def case_claimed_ids_and_cache():
    aid = await _account({"include": [801], "exclude": [802]})
    fake = ListOF({801: [1, 3], 802: [3]})
    with _client(fake) as built:
        assert await io.claimed_ids(aid, [1, 2, 3]) == set()        # off_mode: no OF call
        assert built == [] and fake.reads == [], (built, fake.reads)
        with _live():
            assert await io.claimed_ids(aid, [1, 2, 3]) == {1}
            n = len(fake.reads)
            assert n >= 2, fake.reads                                  # both lists read
            assert await io.claimed_ids(aid, [1, 2, 3]) == {1}
            assert len(fake.reads) == n, fake.reads                    # inside 5 min: cached


def _age_cache(aid: str) -> None:
    for key, (t, members) in list(autoreply._folder_cache.items()):
        if key[0] == aid:
            autoreply._folder_cache[key] = (t - autoreply._FOLDER_TTL_S - 1, members)


async def case_config_change_bites():
    aid = await _account({"include": [901], "exclude": []})
    fake = ListOF({901: [1], 902: [2]})
    with _client(fake), _live():
        assert await io.claimed_ids(aid, [1, 2]) == {1}
        await _set_fans(aid, {"include": [902], "exclude": []})
        assert await io.claimed_ids(aid, [1, 2]) == {2}              # next call, no restart
        await _set_fans(aid, {"include": [], "exclude": []})
        assert await io.claimed_ids(aid, [1, 2]) == {1, 2}
        await _set_fans(aid, {"include": [901], "exclude": []})
        fake.lists[901] = [1, 2]                                     # OF side changes
        assert await io.claimed_ids(aid, [1, 2]) == {1}              # cached (set earlier in this run)
        _age_cache(aid)
        assert await io.claimed_ids(aid, [1, 2]) == {1, 2}           # after the window


def _cached(aid: str, fan_id: int, fans: dict) -> io.FansRead:
    """`cached_listed` with every OF client build and folder crawl failing the test."""
    real = ax._make_client, autoreply._folder_members

    def no_client(*_a, **_k):
        raise AssertionError("cached_listed built an OF client")

    async def no_crawl(*_a, **_k):
        raise AssertionError("cached_listed crawled an OF list")
    ax._make_client, autoreply._folder_members = no_client, no_crawl
    try:
        return io.cached_listed(aid, fan_id, {"fans": fans})
    finally:
        ax._make_client, autoreply._folder_members = real


def case_cached_listed_never_reads_of():
    import time
    aid, ttl = "acc-fans-cached", autoreply._FOLDER_TTL_S
    inc, exc, both = ({"include": [11, 10], "exclude": []}, {"include": [], "exclude": [12]},
                      {"include": [10, 11], "exclude": [12]})
    key = autoreply._folder_key
    autoreply._folder_cache.pop(key(aid, [10, 11]), None)
    r = _cached(aid, 1, inc)
    assert r == io.FansRead(None, None, None, False), r                    # nothing cached: unknown
    assert _cached(aid, 1, {"include": [], "exclude": []}).listed is True  # no list: everyone
    assert _cached(aid, 1, {"include": "x"}).listed is False              # malformed: nobody
    now = time.monotonic()
    autoreply._folder_cache[key(aid, (11, 10))] = (now - 60, frozenset({1, 3}))   # order-free key
    autoreply._folder_cache[key(aid, [12])] = (now - 30, frozenset({3}))
    r = _cached(aid, 1, inc)
    assert r.listed is True and r.fresh and r.failed_age_s is None and 60 <= r.age_s < 70, r
    assert _cached(aid, 2, inc).listed is False
    assert _cached(aid, 3, exc).listed is False and _cached(aid, 1, exc).listed is True
    r = _cached(aid, 3, both)                                              # exclude wins
    assert r.listed is False and r.fresh and r.age_s >= 60, r              # the OLDEST read's age
    autoreply._folder_cache[key(aid, [12])] = (now - ttl - 5, frozenset({3}))
    r = _cached(aid, 1, both)
    assert r.listed is True and not r.fresh and r.age_s >= ttl, r          # one stale key = stale
    autoreply._folder_failed[key(aid, [12])] = now - 20
    r = _cached(aid, 1, both)                    # failed newest read = not listed then; never fresh
    assert r.listed is False and not r.fresh and 20 <= r.failed_age_s < 30, r
    autoreply._folder_cache[key(aid, [12])] = (now - 30, frozenset({3}))
    r = _cached(aid, 1, both)                    # a hit `_folder_members` still serves: the failure is moot
    assert r.listed is True and r.fresh and r.failed_age_s is None, r
    autoreply._folder_cache[key(aid, [12])] = (now - ttl - 5, frozenset({3}))
    autoreply._folder_failed[key(aid, [12])] = now - ttl - 9
    r = _cached(aid, 1, both)                    # a failure the good read overtook is none
    assert r.listed is True and not r.fresh and r.failed_age_s is None, r
    autoreply._folder_failed.pop(key(aid, [12]), None)


async def case_folder_read_failure_is_stamped_then_cleared():
    aid = await _account({"include": [951, 950], "exclude": []})
    k = autoreply._folder_key(aid, [950, 951])
    fake = ListOF({950: [1], 951: [2]}, fail=True)
    with _client(fake), _live():
        assert await io.claimed_ids(aid, [1, 2]) == set()
        assert k in autoreply._folder_failed and k not in autoreply._folder_cache
        r = _cached(aid, 1, {"include": [951, 950], "exclude": []})
        assert r.listed is False and r.failed_age_s is not None and not r.fresh, r
        fake.fail = False
        assert await io.claimed_ids(aid, [1, 2]) == {1, 2}                # no cache: re-read
        assert k not in autoreply._folder_failed and k in autoreply._folder_cache
        r = _cached(aid, 2, {"include": [950, 951], "exclude": []})
        assert r.listed is True and r.failed_age_s is None and r.fresh, r


if __name__ == "__main__":
    _harness.run()
