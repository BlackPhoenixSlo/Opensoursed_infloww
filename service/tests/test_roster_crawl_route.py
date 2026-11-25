#!/usr/bin/env python3
import _harness

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

    later = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=5)
    assert lm._CRAWL_TTL_S == 25 * 60
    got = asyncio.run(lm.refresh_roster(CREATOR_A, STUB, now=later))
    assert got == {"roster": "fresh"}, got
    assert STUB.calls == first_calls, "force=False crawled inside the TTL"

    r = _crawl(owner)
    assert r.status_code == 200 and r.json().get("roster") == "crawled", (r.status_code, r.text)
    assert STUB.calls > first_calls, "the route did not bypass the TTL"
    second = asyncio.run(_seen_at())
    assert len(second) == 1 and second != first, (first, second)


if __name__ == "__main__":
    _harness.run(case_signed_out_refused, case_other_agency_refused, case_unowned_account_refused,
                 case_owner_crawls_and_force_bypasses_ttl)
