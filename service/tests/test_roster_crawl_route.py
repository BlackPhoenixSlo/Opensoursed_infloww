#!/usr/bin/env python3
"""POST /admin/roster/{account_id}/crawl, the on-demand roster crawl seam
(ADR 0024; the soak harness's only trigger for `subscriber_snapshot`).

Pins: the route is owner-only (401 signed out, 403 for another Agency's
owner or an account the caller does not own), answers 200 with refresh_roster's stats,
and `force=True` crawls past the 25-minute `_CRAWL_TTL_S` that the lifecycle
sweep's own call (force=False) still honours.

OF is a stub client on `automation_executor._make_client`: no network.

Run: ./venv/bin/python service/tests/test_roster_crawl_route.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

from sqlalchemy import select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import automation_executor as ax  # noqa: E402
from automations import lifecycle_messages as lm  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import SubscriberSnapshot  # noqa: E402

IDS = fx.seed_two_agencies()
CREATOR_A = "1000001"
FANS = (4100001, 4100002)


class _StubOF:
    """`subscribers` as OF pages it: a bare list, then an empty page."""

    def __init__(self):
        self.calls = 0

    def subscribers(self, *, type, limit, offset):
        self.calls += 1
        if offset:
            return []
        return [{"id": f, "subscribedOnData": {"status": "active",
                                               "subscribeAt": "2026-10-01T00:00:00+00:00",
                                               "expiredAt": "2026-11-01T00:00:00+00:00"}}
                for f in FANS]


STUB = _StubOF()
ax._make_client = lambda account_id: STUB


def _crawl(client, aid: str = CREATOR_A):
    return client.post(f"/admin/roster/{aid}/crawl", headers={"X-Account-Id": aid})


async def _seen_at() -> set:
    async with get_session() as s:
        return set((await s.execute(select(SubscriberSnapshot.seen_at).where(
            SubscriberSnapshot.account_id == CREATOR_A))).scalars())


def case_signed_out_refused():
    r = _crawl(_harness.make_client())
    assert r.status_code == 401, (r.status_code, r.text)
    assert STUB.calls == 0, "a refused call reached OF"


def case_other_agency_refused():
    r = _crawl(fx.login_owner("agency_b_owner"))
    assert r.status_code == 403, (r.status_code, r.text)
    assert STUB.calls == 0, "another owner's call reached OF"


def case_unowned_account_refused():
    r = _crawl(fx.login_owner("agency_a_owner"), "1000999")
    assert r.status_code == 403, (r.status_code, r.text)
    assert STUB.calls == 0


def case_owner_crawls_and_force_bypasses_ttl():
    owner = fx.login_owner("agency_a_owner")
    r = _crawl(owner)
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.json() == {"roster": "crawled", "listed": len(FANS), "returned": 0}, r.json()
    first_calls = STUB.calls
    assert first_calls >= 1
    first = asyncio.run(_seen_at())
    assert len(first) == 1, first

    # Seconds later, well inside the 25-minute TTL: the sweep's own call is
    # told "fresh" and reads nothing ...
    later = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=5)
    assert lm._CRAWL_TTL_S == 25 * 60
    got = asyncio.run(lm.refresh_roster(CREATOR_A, STUB, now=later))
    assert got == {"roster": "fresh"}, got
    assert STUB.calls == first_calls, "force=False crawled inside the TTL"

    # ... while the route (force=True) crawls again and restamps seen_at.
    r = _crawl(owner)
    assert r.status_code == 200 and r.json().get("roster") == "crawled", (r.status_code, r.text)
    assert STUB.calls > first_calls, "the route did not bypass the TTL"
    second = asyncio.run(_seen_at())
    assert len(second) == 1 and second != first, (first, second)


if __name__ == "__main__":
    _harness.run(case_signed_out_refused, case_other_agency_refused, case_unowned_account_refused,
                 case_owner_crawls_and_force_bypasses_ttl)
