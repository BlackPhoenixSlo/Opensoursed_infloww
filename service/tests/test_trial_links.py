#!/usr/bin/env python3
"""Free-trial-link tests (Growth feature #3). OF is faked — no network.

Locks in the contract captured by LIVE testing on 2026-07-22 (Ava):
  • GET /trials returns a BARE LIST (not {items:[...]} like /promotions).
  • An entry has NO `name` key — the operator's label is `trialLinkName`.
  • A spent/expired link KEEPS appearing in the list with isFinished=true, so
    status has to be surfaced or a dead link renders exactly like a live one.
  • clicksCounts is the click-through count (claimCounts is redemptions).
  • fetch failure → of_available False (None sentinel), not a 500; a reachable
    account with zero links is of_available True.

  case_list_parses_bare_list_and_status
  case_finished_link_is_marked_spent
  case_create_captures_of_id_and_round_trips
  case_of_unavailable_vs_reachable_but_empty
  case_mirror_status_unknown_when_of_silent
  case_offer_expiration_reaches_of   Infloww's/OF's "Offer expiration" (expireDays)

Run: ./venv/bin/python service/tests/test_trial_links.py
"""
from __future__ import annotations

import _harness  # MUST be first
_harness.bootstrap()

import asyncio  # noqa: E402

import automation_executor as ax  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, UserAccount  # noqa: E402

import _agency_fixtures as fx  # noqa: E402

# The admin routes need a session (no anonymous admin): an Agency owner signs in and owns every seeded account.
_OWNER = fx.seed_two_agencies()["agency_a_owner"]
_client = fx.login_owner("agency_a_owner")


class FakeOF:
    """Mimics the LIVE OF trial endpoints: a BARE LIST on GET, dict on create."""

    def __init__(self):
        self._id = 11_000_000
        self.deleted: list[int] = []
        self.store: dict[int, dict] = {}
        self.expire_days: list = []   # each create's expire_days, as OF would get it

    def _entry(self, tid, name, days, counts, *, claims=0, clicks=0,
               finished=False, expired=None):
        # Exactly the key set OF returned live — note `trialLinkName`, no `name`.
        return {"id": tid, "trialLinkName": name, "url": f"https://onlyfans.com/x/trial/{tid}",
                "subscribeDays": days, "subscribeCounts": counts,
                "claimCounts": claims, "clicksCounts": clicks,
                "isFinished": finished, "expiredAt": expired,
                "createdAt": None, "sharedWith": [], "user": {}}

    def seed(self, tid, *, name="seeded", days=7, counts=10, claims=0, clicks=0,
             finished=False, expired=None):
        self.store[tid] = self._entry(tid, name, days, counts, claims=claims,
                                      clicks=clicks, finished=finished, expired=expired)
        return tid

    def trial_links(self, *, offset=0, limit=100):
        # BARE LIST (not {"items": ...}), and PAGED — OF's default page is 3.
        return list(self.store.values())[offset:offset + limit]

    def create_trial_link(self, *, name, subscribe_days=7, subscribe_counts=1, expired_at=None,
                          expire_days=None):
        self.expire_days.append(expire_days)
        self._id += 1
        item = self._entry(self._id, name, subscribe_days, subscribe_counts)
        self.store[self._id] = item
        return item

    def delete_trial_link(self, tid):
        self.deleted.append(int(tid))
        self.store.pop(int(tid), None)
        return {"success": True}


def _use_fake() -> FakeOF:
    f = FakeOF()
    ax._make_client = lambda account_id: f  # type: ignore[attr-defined]
    return f


async def _seed(aid):
    async with get_session() as s:
        if not await s.get(Account, aid):
            s.add(Account(id=aid))
    async with get_session() as s:
        if not await s.get(UserAccount, (_OWNER, aid)):
            s.add(UserAccount(user_id=_OWNER, account_id=aid))


def _links(aid):
    r = _client.get(f"/admin/trial-links?account_id={aid}")
    assert r.status_code == 200, r.text
    return r.json()


def case_list_parses_bare_list_and_status():
    aid = "tl_list"
    asyncio.run(_seed(aid))
    f = _use_fake()
    f.seed(101, name="Bio link", days=3, counts=50, claims=2, clicks=9)

    d = _links(aid)
    assert d["of_available"] is True, d
    row = next(l for l in d["links"] if l["of_trial_id"] == 101)
    # trialLinkName is the label — reading `name` alone would yield "".
    assert row["name"] == "Bio link", row
    assert row["status"] == "active", row
    assert row["claim_counts"] == 2 and row["clicks_count"] == 9, row
    assert row["subscribe_days"] == 3 and row["subscribe_counts"] == 50, row


def case_finished_link_is_marked_spent():
    """The live bug: a spent link stays in /trials, and without isFinished the
    UI rendered it identically to a live one."""
    aid = "tl_fin"
    asyncio.run(_seed(aid))
    f = _use_fake()
    f.seed(201, name="live one")
    f.seed(202, name="spent one", claims=10, clicks=4, finished=True,
           expired="2026-05-27T17:11:39+00:00")

    by_id = {l["of_trial_id"]: l for l in _links(aid)["links"]}
    assert by_id[201]["status"] == "active", by_id[201]
    assert by_id[202]["status"] == "finished", by_id[202]
    assert by_id[202]["expired_at"] == "2026-05-27T17:11:39+00:00", by_id[202]


def case_create_captures_of_id_and_round_trips():
    aid = "tl_crud"
    asyncio.run(_seed(aid))
    f = _use_fake()

    r = _client.post("/admin/trial-links", json={
        "account_id": aid, "name": "zz round trip",
        "subscribe_days": 3, "subscribe_counts": 1,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    # Without of_trial_id, delete can't reach OF and the link is orphaned.
    assert body["of_trial_id"] is not None, body
    assert body["status"] == "active", body
    mirror_id, of_id = body["id"], body["of_trial_id"]

    rows = _links(aid)["links"]
    mine = [l for l in rows if l["of_trial_id"] == of_id]
    assert len(mine) == 1, f"created link should appear exactly once, got {mine}"
    assert mine[0]["source"] == "mirror" and mine[0]["name"] == "zz round trip", mine

    d = _client.delete(f"/admin/trial-links/{mirror_id}")
    assert d.status_code == 200 and d.json()["of_deleted"] is True, d.text
    assert f.deleted == [of_id], f.deleted
    assert of_id not in {l["of_trial_id"] for l in _links(aid)["links"]}


def case_of_unavailable_vs_reachable_but_empty():
    aid = "tl_down"
    asyncio.run(_seed(aid))

    _use_fake()                       # reachable, zero links
    assert _links(aid)["of_available"] is True

    class Boom:
        def trial_links(self, *, offset=0, limit=100):
            raise RuntimeError("no session")
    ax._make_client = lambda account_id: Boom()  # type: ignore[attr-defined]
    d = _links(aid)
    assert d["of_available"] is False, d      # None sentinel, not a 500


def case_mirror_status_unknown_when_of_silent():
    """A mirror row OF didn't return must not claim to be live — /trials
    ordering is unstable, so 'absent' is not proof of 'finished'."""
    aid = "tl_unknown"
    asyncio.run(_seed(aid))
    f = _use_fake()
    created = _client.post("/admin/trial-links", json={
        "account_id": aid, "name": "vanishes", "subscribe_days": 3, "subscribe_counts": 1,
    }).json()
    f.store.clear()                   # OF stops listing it

    row = next(l for l in _links(aid)["links"] if l["id"] == created["id"])
    assert row["status"] == "unknown", row


def case_pages_past_the_default_page():
    """/trials pages at THREE by default. The un-paged call showed 3 of Ava's
    18 real links — the operator saw a fraction of their own links with no hint
    that the rest existed."""
    aid = "tl_paged"
    asyncio.run(_seed(aid))
    f = _use_fake()
    for i in range(250):
        f.seed(30_000 + i, name=f"link {i}")

    got = _links(aid)
    assert got["of_available"] is True, got
    assert len(got["links"]) == 250, f"expected all 250, got {len(got['links'])}"
    ids = [l["of_trial_id"] for l in got["links"]]
    assert len(set(ids)) == 250, "paging must not duplicate rows"


def case_offer_expiration_reaches_of():
    """The Growth form now sends the link's Offer expiration (0 = none); an old
    caller that omits it sends nothing, and over 30 days is refused."""
    aid = "tl_expire"
    asyncio.run(_seed(aid))
    f = _use_fake()
    r = _client.post("/admin/trial-links", json={
        "account_id": aid, "name": "Week", "subscribe_days": 7, "subscribe_counts": 10, "expire_days": 0})
    assert r.status_code == 200, r.text
    r = _client.post("/admin/trial-links", json={
        "account_id": aid, "name": "Old", "subscribe_days": 7, "subscribe_counts": 1})
    assert r.status_code == 200, r.text
    assert f.expire_days == [0, None], f.expire_days
    r = _client.post("/admin/trial-links", json={
        "account_id": aid, "name": "Long", "subscribe_days": 7, "subscribe_counts": 1, "expire_days": 31})
    assert r.status_code == 422, r.text


_harness.run(
    case_offer_expiration_reaches_of,
    case_pages_past_the_default_page,
    case_list_parses_bare_list_and_status,
    case_finished_link_is_marked_spent,
    case_create_captures_of_id_and_round_trips,
    case_of_unavailable_vs_reachable_but_empty,
    case_mirror_status_unknown_when_of_silent,
)
