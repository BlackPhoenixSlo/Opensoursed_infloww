#!/usr/bin/env python3
"""Profile-Promotion tests (Growth feature #6). OF is faked — no network.

Locks in the contract discovered by LIVE testing on 2026-07-22:
  • OF /promotions returns {items:[...]} (NOT {list:[...]}) — list must parse it.
  • create_promo returns a LIST [{id,...}] — of_promo_id must be captured from it
    (else delete can't reach OF and leaves a live promo).
  • performance = claimsCount; discount is a % (1..100), never echoed on list.
  • fetch failure → of_available False (None sentinel), not a 500.

  case_list_parses_items_and_of_available
  case_create_captures_of_id_from_list_response
  case_discount_validation
  case_of_unavailable_when_fetch_fails
  case_offer_expiration_and_audience_reach_of   Infloww's/OF's composer fields
  case_bad_audience_is_422
  case_of_only_row_keeps_its_created_date
  case_keep_running_toggle_owns_the_rule        tick ensures the hourly real rule; last untick parks it
  case_create_with_keep_running_moves_the_flag  the form's default tick arms the new one, unticks others
  case_create_unarmable_is_created_unarmed      no of_promo_id → made, not armed, response says why
  case_create_stores_finish_days_and_expires_at

Run: ./venv/bin/python service/tests/test_promotions.py
"""
from __future__ import annotations

import _harness  # MUST be first
_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AutomationRule, PromoCampaign, UserAccount  # noqa: E402

import _agency_fixtures as fx  # noqa: E402

# The admin routes need a session (no anonymous admin): an Agency owner signs in and owns every seeded account.
_OWNER = fx.seed_two_agencies()["agency_a_owner"]
_client = fx.login_owner("agency_a_owner")


class FakeOF:
    """Mimics the LIVE OF promo endpoints: {items:[...]} on GET, a LIST on create."""
    def __init__(self):
        self._id = 70_000_000
        self.created: list[int] = []
        self.deleted: list[int] = []
        self.store: dict[int, dict] = {}
        self.calls: list[dict] = []   # every create's kwargs, as OF would get them

    def promotions(self, *, offset=0, limit=100):
        # OF pages this endpoint and its hasMore is ALWAYS true, so the fake
        # mimics both: callers must stop on a short page, not on hasMore.
        page = list(self.store.values())[offset:offset + limit]
        return {"hasMore": True, "items": page}

    def create_promo(self, *, discount, subscribe_counts, subscribe_days=30, message="", type="all",
                     finish_days=None):
        self._id += 1
        self.calls.append({"discount": discount, "type": type, "finish_days": finish_days})
        item = {"id": self._id, "message": message, "price": 3, "type": type,
                "subscribeCounts": subscribe_counts, "subscribeDays": subscribe_days,
                "claimsCount": 0, "isFinished": False}
        self.store[self._id] = item
        self.created.append(int(discount))
        return [item]   # OF returns a LIST containing the created promo

    def delete_promo(self, pid):
        self.deleted.append(int(pid))
        if int(pid) in self.store:
            self.store[int(pid)]["isFinished"] = True   # OF flips to finished
        return {"success": True}


def _use_fake() -> FakeOF:
    f = FakeOF()
    ax._make_client = lambda account_id: f  # type: ignore[attr-defined]
    return f


async def _seed(aid):
    async with get_session() as s:
        s.add(Account(id=aid))
    async with get_session() as s:
        if not await s.get(UserAccount, (_OWNER, aid)):
            s.add(UserAccount(user_id=_OWNER, account_id=aid))


def case_list_parses_items_and_of_available():
    aid = "promo_list"
    asyncio.run(_seed(aid))
    f = _use_fake()
    f.store[123] = {"id": 123, "message": "old", "subscribeCounts": 5,
                    "subscribeDays": 30, "claimsCount": 9, "isFinished": True}
    r = _client.get(f"/admin/promotions?account_id={aid}").json()
    assert r["of_available"] is True, r
    # claimsCount maps to subscriber_count (performance readout)
    assert any(c["of_promo_id"] == 123 and c["subscriber_count"] == 9 for c in r["campaigns"]), r


def case_create_captures_of_id_from_list_response():
    aid = "promo_create"
    asyncio.run(_seed(aid))
    f = _use_fake()
    r = _client.post("/admin/promotions", json={
        "account_id": aid, "name": "Test", "discount": 50,
        "subscribe_counts": 1, "subscribe_days": 1,
    }).json()
    assert r["of_promo_id"] is not None, f"of_promo_id must come from the LIST response: {r}"
    assert r["discount_percent"] == 50, r
    assert f.created == [50], f.created
    mid = r["id"]
    d = _client.delete(f"/admin/promotions/{mid}").json()
    assert d["of_deleted"] is True and d["deleted"] == mid, d
    assert f.deleted == [r["of_promo_id"]], f.deleted


def case_discount_validation():
    aid = "promo_val"
    asyncio.run(_seed(aid))
    _use_fake()
    assert _client.post("/admin/promotions", json={"account_id": aid, "name": "X", "discount": 0}).status_code == 422
    assert _client.post("/admin/promotions", json={"account_id": aid, "name": "X", "discount": 101}).status_code == 422


def case_of_unavailable_when_fetch_fails():
    aid = "promo_fail"
    asyncio.run(_seed(aid))

    class Boom:
        def promotions(self, *, offset=0, limit=100):
            raise RuntimeError("no session")
    ax._make_client = lambda account_id: Boom()  # type: ignore[attr-defined]
    r = _client.get(f"/admin/promotions?account_id={aid}").json()
    assert r["of_available"] is False, r   # None sentinel → False, not a 500


def case_only_one_campaign_can_keep_running():
    """OF runs one promo at a time, so arming a second campaign set up a
    ping-pong: each re-arm finished the other's live discount, minting a real
    promo on the creator's profile every tick."""
    aid = "pr_one_armed"
    asyncio.run(_seed(aid))
    _use_fake()
    a = _client.post("/admin/promotions", json={
        "account_id": aid, "name": "A", "discount": 10, "subscribe_counts": 1}).json()
    b = _client.post("/admin/promotions", json={
        "account_id": aid, "name": "B", "discount": 10, "subscribe_counts": 1}).json()

    first = _client.patch(f"/admin/promotions/{a['id']}", json={"auto_reactivate": True})
    assert first.status_code == 200, first.text

    second = _client.patch(f"/admin/promotions/{b['id']}", json={"auto_reactivate": True})
    assert second.status_code == 409, f"expected 409, got {second.status_code}: {second.text}"
    assert "already set to keep running" in second.text, second.text

    # Turning the first off frees the slot.
    assert _client.patch(f"/admin/promotions/{a['id']}",
                         json={"auto_reactivate": False}).status_code == 200
    assert _client.patch(f"/admin/promotions/{b['id']}",
                         json={"auto_reactivate": True}).status_code == 200


def case_subscribe_days_reflects_what_of_did():
    """OF DISCARDS subscribeDays for a percent discount (stores 0, no end date).
    The mirror used to keep the operator's typed number and `or` hid OF's 0, so
    the UI promised an expiry that does not exist."""
    aid = "pr_days"
    asyncio.run(_seed(aid))
    _use_fake()          # fake echoes subscribe_days back as OF stored it
    r = _client.post("/admin/promotions", json={
        "account_id": aid, "name": "Discount", "discount": 10,
        "subscribe_counts": 1, "subscribe_days": 0})
    assert r.status_code == 200, r.text
    assert r.json()["subscribe_days"] == 0, r.json()

    row = next(c for c in _client.get(f"/admin/promotions?account_id={aid}").json()["campaigns"]
               if c["id"] == r.json()["id"])
    assert row["subscribe_days"] == 0, f"OF's real 0 must survive the merge: {row}"


def case_offer_expiration_and_audience_reach_of():
    """The Growth form now sends Infloww's/OF's "Offer expiration" (finish_days)
    and "User type". One audience stays the bare string the live-verified create
    used; both goes as OF's own list, and the mirror keeps it as "all,expired"
    so the re-arm can send the same list back. No finish_days → not sent."""
    aid = "promo_fields"
    asyncio.run(_seed(aid))
    f = _use_fake()
    r = _client.post("/admin/promotions", json={
        "account_id": aid, "name": "Both", "discount": 100, "subscribe_counts": 10,
        "subscribe_days": 7, "finish_days": 7, "promo_type": ["expired", "all"]})
    assert r.status_code == 200, r.text
    assert f.calls[-1] == {"discount": 100, "type": ["all", "expired"], "finish_days": 7}, f.calls
    assert r.json()["promo_type"] == "all,expired", r.json()

    r = _client.post("/admin/promotions", json={
        "account_id": aid, "name": "Expired", "discount": 20, "subscribe_counts": 0,
        "subscribe_days": 0, "finish_days": 0, "promo_type": ["expired"]})
    assert r.status_code == 200, r.text
    assert f.calls[-1] == {"discount": 20, "type": "expired", "finish_days": 0}, f.calls

    r = _client.post("/admin/promotions", json={
        "account_id": aid, "name": "Old caller", "discount": 20, "subscribe_counts": 1})
    assert r.status_code == 200, r.text
    assert f.calls[-1] == {"discount": 20, "type": "all", "finish_days": None}, f.calls


def case_bad_audience_is_422():
    aid = "promo_bad_type"
    asyncio.run(_seed(aid))
    f = _use_fake()
    for bad in (["fans"], [], "new"):
        r = _client.post("/admin/promotions", json={
            "account_id": aid, "name": "X", "discount": 10, "subscribe_counts": 1, "promo_type": bad})
        assert r.status_code == 422, (bad, r.status_code, r.text)
    assert f.calls == [], "a rejected audience must never reach OF"
    r = _client.post("/admin/promotions", json={
        "account_id": aid, "name": "X", "discount": 10, "subscribe_counts": 1, "finish_days": 31})
    assert r.status_code == 422, r.text   # OF's offer expiration tops out at 30 days


def case_of_only_row_keeps_its_created_date():
    """Infloww's Promo cell shows the creation date; an OnlyFans-only row (no
    mirror) carries it from OF's createdAt instead of None."""
    aid = "promo_created"
    asyncio.run(_seed(aid))
    f = _use_fake()
    f.store[555] = {"id": 555, "message": "live", "subscribeCounts": 5, "subscribeDays": 0,
                    "claimsCount": 1, "isFinished": False, "createdAt": "2026-10-01T10:00:00+00:00"}
    r = _client.get(f"/admin/promotions?account_id={aid}").json()
    row = next(c for c in r["campaigns"] if c["of_promo_id"] == 555)
    assert row["created_at"] == "2026-10-01T10:00:00+00:00", row


async def _rules(aid) -> list[AutomationRule]:
    async with get_session() as s:
        return list((await s.execute(select(AutomationRule).where(
            AutomationRule.account_id == aid,
            AutomationRule.kind == "promo_reactivate"))).scalars())


async def _row(mid) -> PromoCampaign:
    async with get_session() as s:
        return await s.get(PromoCampaign, mid)


def _create(aid, name, **kw):
    r = _client.post("/admin/promotions", json={
        "account_id": aid, "name": name, "discount": 10, "subscribe_counts": 1, **kw})
    assert r.status_code == 200, r.text
    return r.json()


KEEP = {"dry_run": False, "cooldown_minutes": 2, "max_reactivations": 0}


def case_keep_running_toggle_owns_the_rule():
    aid = "pr_toggle_rule"
    asyncio.run(_seed(aid))
    _use_fake()
    a = _create(aid, "A")
    assert a["auto_reactivate"] is False and asyncio.run(_rules(aid)) == [], a  # API default: unarmed
    assert _client.patch(f"/admin/promotions/{a['id']}", json={"auto_reactivate": True}).status_code == 200
    rules = asyncio.run(_rules(aid))
    assert len(rules) == 1 and rules[0].is_enabled, rules
    assert json.loads(rules[0].trigger_json) == {"every_seconds": 3600}, rules[0].trigger_json
    assert json.loads(rules[0].steps_json) == KEEP, rules[0].steps_json
    assert _client.patch(f"/admin/promotions/{a['id']}", json={"auto_reactivate": False}).status_code == 200
    rules = asyncio.run(_rules(aid))
    assert len(rules) == 1 and not rules[0].is_enabled, "the last untick must park the rule"
    assert _client.patch(f"/admin/promotions/{a['id']}", json={"auto_reactivate": True}).status_code == 200
    rules = asyncio.run(_rules(aid))
    assert len(rules) == 1 and rules[0].is_enabled, "re-tick wakes the same row, never a second"
    # a refused tick (409) leaves the rule and flags alone
    b = _create(aid, "B")
    assert _client.patch(f"/admin/promotions/{b['id']}", json={"auto_reactivate": True}).status_code == 409
    assert asyncio.run(_row(a["id"])).auto_reactivate and not asyncio.run(_row(b["id"])).auto_reactivate
    # unticking a campaign that is not the armed one keeps the rule on
    assert _client.patch(f"/admin/promotions/{b['id']}", json={"auto_reactivate": False}).status_code == 200
    assert asyncio.run(_rules(aid))[0].is_enabled


def case_create_with_keep_running_moves_the_flag():
    aid = "pr_create_armed"
    asyncio.run(_seed(aid))
    _use_fake()
    a = _create(aid, "A", auto_reactivate=True)
    assert a["auto_reactivate"] is True and "auto_reactivate_refused" not in a, a
    b = _create(aid, "B", auto_reactivate=True)
    assert b["auto_reactivate"] is True, b
    assert not asyncio.run(_row(a["id"])).auto_reactivate, "the flag must MOVE to the new campaign"
    assert asyncio.run(_row(b["id"])).auto_reactivate
    rules = asyncio.run(_rules(aid))
    assert len(rules) == 1 and rules[0].is_enabled and json.loads(rules[0].steps_json) == KEEP, rules
    listed = {c["id"]: c["auto_reactivate"] for c in
              _client.get(f"/admin/promotions?account_id={aid}").json()["campaigns"] if c["id"]}
    assert listed == {a["id"]: False, b["id"]: True}, listed


def case_create_unarmable_is_created_unarmed():
    aid = "pr_create_noid"
    asyncio.run(_seed(aid))
    f = _use_fake()
    f.create_promo = lambda **kw: []          # OF answered without the created promo
    r = _create(aid, "NoId", auto_reactivate=True)
    assert r["id"] is not None and r["of_promo_id"] is None, r
    assert r["auto_reactivate"] is False, r
    assert "isn't linked to an OnlyFans promo" in r["auto_reactivate_refused"], r
    assert not asyncio.run(_row(r["id"])).auto_reactivate
    assert asyncio.run(_rules(aid)) == [], "an unarmable create must not switch the rule on"


def case_create_stores_finish_days_and_expires_at():
    aid = "pr_create_exp"
    asyncio.run(_seed(aid))
    _use_fake()
    t0 = datetime.utcnow()
    r = _create(aid, "Week", finish_days=7)
    row = asyncio.run(_row(r["id"]))
    assert row.finish_days == 7, row.finish_days
    assert abs((row.expires_at - (t0 + timedelta(days=7))).total_seconds()) < 5, row.expires_at
    for kw in ({}, {"finish_days": 0}):
        row = asyncio.run(_row(_create(aid, "Open", **kw)["id"]))
        assert row.expires_at is None and row.finish_days == kw.get("finish_days"), (kw, row.finish_days)


_harness.run(
    case_offer_expiration_and_audience_reach_of,
    case_bad_audience_is_422,
    case_of_only_row_keeps_its_created_date,
    case_only_one_campaign_can_keep_running,
    case_subscribe_days_reflects_what_of_did,
    case_list_parses_items_and_of_available,
    case_create_captures_of_id_from_list_response,
    case_discount_validation,
    case_of_unavailable_when_fetch_fails,
    case_keep_running_toggle_owns_the_rule,
    case_create_with_keep_running_moves_the_flag,
    case_create_unarmable_is_created_unarmed,
    case_create_stores_finish_days_and_expires_at,
)
