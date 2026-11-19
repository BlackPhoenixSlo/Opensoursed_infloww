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
  case_create_without_id_is_unknown_unarmed     OF answered with no id: 200 "unknown", no mirror
                                 row until a read adopts it, not armed, response says why
  case_create_stores_finish_days_and_expires_at
  case_keep_warning_listed_until_retick  a campaign Inflowwww turned off keeps its reason
                                 (keep_warning) on the list; an open create shows
                                 keep_blocked "unknown"; a re-tick clears the warning and
                                 restarts the breaker's count (keep_ticked_at).
  case_manual_409_while_open     a create meeting an open one inside the grace: 409
                                 create_in_flight, nothing sent.
  case_create_unresolved_then_resolve_open  past the grace: 409 create_unresolved (id, terms);
                                 the resend with resolve_open clears it and creates.
  case_get_reconciles_open_row   the list read adopts a create sent with no answer: its mirror
                                 row appears.
  case_rv_c02_manual_age_runs_from_send  an old row just flipped to sending is in flight (409
                                 create_in_flight), not "create anyway".
  case_rv_c05_takeover_between_reserve_and_send_refused  Keep running moved after the reserve:
                                 the sending CAS refuses, 409 keep_running_moved, no POST.
  case_rv_r06_concurrent_ticks_one_kept  two racing ticks: one Kept campaign, the other 409.
  case_rv_r08_success_after_create_anyway_no_500  a late success on a cleared row: unresolved
                                 reply with OF's id, no 500; the row keeps the id.
  case_manual_after_budget_exhaustion  a full automatic budget never refuses a manual create,
                                 and the manual create is not counted.
  case_raw_route_reserved        the OF mirror's Start campaign reserves: a row per create, 409
                                 while one is open.
  case_raw_finish_unticks        stopping or deleting a Kept promo from the OF mirror unticks
                                 it first (and parks the rule).
  case_list_shows_backoff_and_budget  a Kept campaign held by the back-off or the budget says
                                 so (keep_blocked + until).
  case_mn07_tick_on_unfenced_copy_stamps_empty  a tick on a box with PROMO_CREATE_HOST_ID unset
                                 stamps "", lists keep_blocked "fence" and never creates; a tick
                                 on a set box stamps its id, with no OF read.
  case_mn09_unlimited_trial_refused  a Free trial keeps running only with a Claim cap and a
                                 Re-create limit 1-10, on create and on PATCH; other discounts
                                 store no limit.
  case_create_takeover_names_previous  a create that moves Keep running returns the campaign it
                                 took it from and notifies the owner.
  case_create_takeover_moved_409  the Kept campaign changed since the form showed it: 409
                                 keep_running_moved before OF hears; changed during the POST:
                                 created, not armed, says why.
  case_preempt_second_tick       the create stores `preempt` (default on) only when it arms;
                                 PATCH flips it alone, 422 with neither tick; GET lists
                                 `preempt`, `keep_wait`, and keep_blocked switch / clock.
  case_rvb_r4_c8_preempt_only_on_kept  PATCH stores `preempt` only on a Kept campaign (or one
                                 it ticks): alone on another → 422, beside an untick ignored;
                                 GET shows it off on an unkept row; `keep_wait` only while
                                 Kept, ticked early and the server switch on.

Run: ./venv/bin/python service/tests/test_promotions.py
"""
from __future__ import annotations

import _harness  # MUST be first
_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402
import promo_create_guard  # noqa: E402
import promotions_api  # noqa: E402
import server  # noqa: E402
from db.engine import get_session  # noqa: E402
from automation_executor import run_once  # noqa: E402
from db.models import (Account, AgencyNotification, AutomationRule, PromoCampaign,  # noqa: E402
                       PromoCreateReservation, PromoKeepState, UserAccount)

import _agency_fixtures as fx  # noqa: E402

# The admin routes need a session (no anonymous admin): an Agency owner signs in and owns every seeded account.
_OWNER = fx.seed_two_agencies()["agency_a_owner"]
_client = fx.login_owner("agency_a_owner")


BOX = "test-box"   # this box's Host fence id
os.environ[promo_create_guard.HOST_ENV] = BOX


class FakeOF:
    """Mimics the LIVE OF promo endpoints: {items:[...]} on GET, a LIST on create."""
    def __init__(self):
        self._id = 70_000_000
        self.created: list[int] = []
        self.deleted: list[int] = []
        self.store: dict[int, dict] = {}
        self.calls: list[dict] = []   # every create's kwargs, as OF would get them
        self.finished: list[int] = []
        self.reads = 0

    def promotions(self, *, offset=0, limit=100):
        self.reads += 1
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

    def finish_promo(self, pid):
        self.finished.append(int(pid))
        if int(pid) in self.store:
            self.store[int(pid)]["isFinished"] = True
        return {"success": True}

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


def case_create_without_id_is_unknown_unarmed():
    aid = "pr_create_noid"
    asyncio.run(_seed(aid))
    f = _use_fake()
    f.create_promo = lambda **kw: []          # OF answered without the created promo
    r = _create(aid, "NoId", auto_reactivate=True)
    assert (r["id"], r["of_promo_id"], r["create"], r["auto_reactivate"]) == (None, None, "unknown", False), r
    assert "shows here once OnlyFans lists it" in r["auto_reactivate_refused"], r
    assert asyncio.run(_reservations(aid)) == [("manual", "unknown")]
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


def case_keep_warning_listed_until_retick():
    aid = "pr_keep_warning"
    asyncio.run(_seed(aid))
    _use_fake()
    a = _create(aid, "A")

    def listed():
        return {c["id"]: c for c in _client.get(f"/admin/promotions?account_id={aid}").json()["campaigns"]
                if c["id"]}[a["id"]]
    assert (listed()["keep_warning"], listed()["keep_blocked"]) == (None, None)
    assert _client.patch(f"/admin/promotions/{a['id']}", json={"auto_reactivate": True}).status_code == 200
    ticked = asyncio.run(_row(a["id"])).keep_ticked_at
    assert ticked is not None

    async def open_create():
        async with get_session() as s:
            s.add(PromoCreateReservation(account_id=aid, campaign_id=a["id"], source="auto_ended",
                                         state="unknown", terms_json="{}"))
    asyncio.run(open_create())
    assert listed()["keep_blocked"] == "unknown"

    async def turned_off():
        async with get_session() as s:
            row = await s.get(PromoCampaign, a["id"])
            row.auto_reactivate, row.keep_warning = False, "breaker"
            for r in (await s.execute(select(PromoCreateReservation).where(
                    PromoCreateReservation.account_id == aid))).scalars():
                r.state = "lost"
    asyncio.run(turned_off())
    row = listed()
    assert (row["auto_reactivate"], row["keep_warning"], row["keep_blocked"]) == (False, "breaker", None), row
    assert _client.patch(f"/admin/promotions/{a['id']}", json={"auto_reactivate": True}).status_code == 200
    after = asyncio.run(_row(a["id"]))
    assert after.keep_warning is None and after.keep_ticked_at > ticked, (after.keep_warning, after.keep_ticked_at)
    assert listed()["keep_warning"] is None


async def _reservations(aid) -> list[tuple[str, str]]:
    async with get_session() as s:
        return [(r.source, r.state) for r in (await s.execute(select(PromoCreateReservation).where(
            PromoCreateReservation.account_id == aid).order_by(PromoCreateReservation.id))).scalars()]


async def _open_row(aid, *, ago_s=0, source="auto_ended", terms=None, pre_ids=None,
                    state="unknown", sent_ago_s=None) -> int:
    at = datetime.utcnow() - timedelta(seconds=ago_s)
    sent = at if sent_ago_s is None else datetime.utcnow() - timedelta(seconds=sent_ago_s)
    async with get_session() as s:
        r = PromoCreateReservation(account_id=aid, source=source, state=state, created_at=at,
                                   sent_at=sent, terms_json=json.dumps(terms or {}),
                                   pre_ids_json=None if pre_ids is None else json.dumps(pre_ids))
        s.add(r)
        await s.flush()
        return r.id


BODY = {"name": "New", "discount": 10, "subscribe_counts": 1}


def case_manual_409_while_open():
    aid = "pr_manual_open"
    asyncio.run(_seed(aid))
    f = _use_fake()
    asyncio.run(_open_row(aid, ago_s=60))
    r = _client.post("/admin/promotions", json={"account_id": aid, **BODY})
    assert r.status_code == 409 and r.json()["detail"]["reason"] == "create_in_flight", r.text
    assert f.calls == [], "nothing may reach OF while a create is open"


def case_create_unresolved_then_resolve_open():
    aid = "pr_manual_unresolved"
    asyncio.run(_seed(aid))
    f = _use_fake()
    rid = asyncio.run(_open_row(aid, ago_s=promo_create_guard.SETTLE_GRACE_S + 60,
                                terms={"discount": 30, "subscribe_counts": 5}))
    r = _client.post("/admin/promotions", json={"account_id": aid, **BODY})
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert (d["reason"], d["id"], d["terms"]["discount"]) == ("create_unresolved", rid, 30), d
    assert "create anyway" in d["message"], d
    assert f.calls == []
    r = _client.post("/admin/promotions", json={"account_id": aid, **BODY, "resolve_open": rid + 1})
    assert r.status_code == 409 and r.json()["detail"]["reason"] == "create_unresolved", r.text
    r = _client.post("/admin/promotions", json={"account_id": aid, **BODY, "resolve_open": rid})
    assert r.status_code == 200 and r.json()["of_promo_id"] is not None, r.text
    assert asyncio.run(_reservations(aid)) == [("auto_ended", "cleared"), ("manual", "created")]
    assert len(f.calls) == 1


def case_get_reconciles_open_row():
    aid = "pr_get_reconcile"
    asyncio.run(_seed(aid))
    f = _use_fake()
    terms = {"discount": 20, "subscribe_counts": 7, "subscribe_days": 30, "message": "Hi",
             "type": "all", "mirror": {"name": "Late one", "promo_type": "all"}}
    asyncio.run(_open_row(aid, ago_s=30, source="manual", terms=terms, pre_ids=[]))
    f.store[901] = {"id": 901, "message": "Hi", "type": "all", "subscribeCounts": 7, "subscribeDays": 0,
                    "claimsCount": 0, "isFinished": False,
                    "createdAt": datetime.utcnow().isoformat() + "+00:00"}
    rows = _client.get(f"/admin/promotions?account_id={aid}").json()["campaigns"]
    adopted = next(c for c in rows if c["of_promo_id"] == 901)
    assert (adopted["source"], adopted["name"], adopted["discount_percent"]) == ("mirror", "Late one", 20), adopted
    assert asyncio.run(_reservations(aid)) == [("manual", "created")]


def case_manual_after_budget_exhaustion():
    aid = "pr_manual_budget"
    asyncio.run(_seed(aid))
    f = _use_fake()

    async def full_budget():
        now = datetime.utcnow()
        async with get_session() as s:
            for m in range(8):
                at = now - timedelta(minutes=5 * m + 1)
                s.add(PromoCreateReservation(account_id=aid, source="auto_ended", state="failed",
                                             error_class="http_403", terms_json="{}", created_at=at,
                                             settled_at=at, not_before=now + timedelta(hours=1)))
    asyncio.run(full_budget())
    r = _client.post("/admin/promotions", json={"account_id": aid, **BODY})
    assert r.status_code == 200 and len(f.calls) == 1, r.text
    budget = asyncio.run(promo_create_guard.budget_state(aid, datetime.utcnow()))
    assert len(budget.auto_times) == 8, "a manual create is never counted"


def _raw(aid, method, path, **kw):
    return getattr(_client, method)(path, headers={"X-Account-Id": aid}, **kw)


def _raw_fake(aid) -> FakeOF:
    f = _use_fake()
    server._load_client = lambda account_id: f   # the raw /api/of/v2 routes' client
    known = server.account_registry.get_account
    server.account_registry.get_account = lambda a: {"id": a} if a == aid else known(a)
    return f


def case_raw_route_reserved():
    aid = "pr_raw_create"
    asyncio.run(_seed(aid))
    f = _raw_fake(aid)
    r = _raw(aid, "post", "/api/of/v2/promotions", json={"discount": 40, "subscribe_counts": 3})
    assert r.status_code == 200 and r.json()[0]["id"] == f._id, r.text
    assert asyncio.run(_reservations(aid)) == [("manual_raw", "created")]
    asyncio.run(_open_row(aid, ago_s=60))
    r = _raw(aid, "post", "/api/of/v2/promotions", json={"discount": 40, "subscribe_counts": 3})
    assert r.status_code == 409 and r.json()["detail"]["reason"] == "create_in_flight", r.text
    assert len(f.calls) == 1


def case_raw_finish_unticks():
    aid = "pr_raw_finish"
    asyncio.run(_seed(aid))
    f = _raw_fake(aid)
    a = _create(aid, "Kept", auto_reactivate=True)
    r = _raw(aid, "post", f"/api/of/v2/promotions/{a['of_promo_id']}/finish")
    assert r.status_code == 200 and f.finished == [a["of_promo_id"]], r.text
    assert not asyncio.run(_row(a["id"])).auto_reactivate
    assert not asyncio.run(_rules(aid))[0].is_enabled, "the last untick parks the rule"
    b = _create(aid, "Kept too", auto_reactivate=True)
    r = _raw(aid, "delete", f"/api/of/v2/promotions/{b['of_promo_id']}")
    assert r.status_code == 200 and f.deleted == [b["of_promo_id"]], r.text
    assert not asyncio.run(_row(b["id"])).auto_reactivate
    # another promo's stop leaves the Kept one alone
    c = _create(aid, "Kept three", auto_reactivate=True)
    assert _raw(aid, "post", f"/api/of/v2/promotions/{b['of_promo_id']}/finish").status_code == 200
    assert asyncio.run(_row(c["id"])).auto_reactivate


def case_list_shows_backoff_and_budget():
    aid = "pr_list_holds"
    asyncio.run(_seed(aid))
    _use_fake()
    a = _create(aid, "A", auto_reactivate=True)
    until = datetime.utcnow() + timedelta(minutes=4)

    async def failed(**kw):
        async with get_session() as s:
            s.add(PromoCreateReservation(account_id=aid, campaign_id=a["id"], source="auto_ended",
                                         state="failed", error_class="http_429", terms_json="{}",
                                         created_at=datetime.utcnow(), **kw))

    def listed():
        return next(c for c in _client.get(f"/admin/promotions?account_id={aid}").json()["campaigns"]
                    if c["id"] == a["id"])
    asyncio.run(failed(not_before=until))
    row = listed()
    assert (row["keep_blocked"], row["keep_blocked_until"]) == ("backoff", until.isoformat()), row
    asyncio.run(failed()); asyncio.run(failed())

    async def lift():
        async with get_session() as s:
            for r in (await s.execute(select(PromoCreateReservation).where(
                    PromoCreateReservation.account_id == aid))).scalars():
                r.not_before = None
    asyncio.run(lift())
    row = listed()
    assert row["keep_blocked"] == "budget" and row["keep_blocked_until"], row


def case_mn07_tick_on_unfenced_copy_stamps_empty():
    aid = "pr_mn07_copy"
    asyncio.run(_seed(aid))
    f = _use_fake()
    a = _create(aid, "Copy")
    os.environ[promo_create_guard.HOST_ENV] = ""
    try:
        reads = f.reads
        assert _client.patch(f"/admin/promotions/{a['id']}", json={"auto_reactivate": True}).status_code == 200
        assert f.reads == reads, "a tick reads nothing from OF"
        assert asyncio.run(_row(a["id"])).keep_host_id == ""
        f.store[a["of_promo_id"]]["isFinished"] = True
        reads = f.reads
        res = asyncio.run(run_once(aid, "promo_reactivate", payload={"dry_run": False}))
        assert res["skipped"] == "fence" and f.reads == reads and len(f.created) == 1, res
        row = next(c for c in _client.get(f"/admin/promotions?account_id={aid}").json()["campaigns"]
                   if c["id"] == a["id"])
        assert row["keep_blocked"] == "fence", row
    finally:
        os.environ[promo_create_guard.HOST_ENV] = BOX
    assert _client.patch(f"/admin/promotions/{a['id']}", json={"auto_reactivate": True}).status_code == 200
    assert asyncio.run(_row(a["id"])).keep_host_id == BOX


def case_mn09_unlimited_trial_refused():
    aid = "pr_mn09_trial"
    asyncio.run(_seed(aid))
    f = _use_fake()
    trial = {"discount": 100, "subscribe_days": 3, "auto_reactivate": True}
    r = _client.post("/admin/promotions", json={"account_id": aid, "name": "T", **trial, "subscribe_counts": 0})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "trial_unlimited", r.text
    r = _client.post("/admin/promotions", json={"account_id": aid, "name": "T", **trial, "subscribe_counts": 5})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "recreate_limit_required", r.text
    for bad in (0, 11):
        assert _client.post("/admin/promotions", json={"account_id": aid, "name": "T", **trial, "subscribe_counts": 5,
                                                       "recreate_limit": bad}).status_code == 422
    assert f.created == [], "a refused trial never reaches OF"
    t = _create(aid, "T", **trial, subscribe_counts=5, recreate_limit=3)
    assert t["auto_reactivate"] is True and asyncio.run(_row(t["id"])).recreates_left == 3, t
    assert _client.patch(f"/admin/promotions/{t['id']}", json={"auto_reactivate": False}).status_code == 200
    r = _client.patch(f"/admin/promotions/{t['id']}", json={"auto_reactivate": True})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "recreate_limit_required", r.text
    assert _client.patch(f"/admin/promotions/{t['id']}", json={"auto_reactivate": True,
                                                               "recreate_limit": 11}).status_code == 422
    r = _client.patch(f"/admin/promotions/{t['id']}", json={"auto_reactivate": True, "recreate_limit": 4})
    assert r.status_code == 200 and r.json()["recreates_left"] == 4, r.text
    assert _client.patch(f"/admin/promotions/{t['id']}", json={"auto_reactivate": False}).status_code == 200
    u = _create(aid, "Open trial", discount=100, subscribe_days=3, subscribe_counts=0)   # unticked: fine
    r = _client.patch(f"/admin/promotions/{u['id']}", json={"auto_reactivate": True, "recreate_limit": 3})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "trial_unlimited", r.text
    p = _create(aid, "Pct", auto_reactivate=True, recreate_limit=3)
    assert p["auto_reactivate"] is True and asyncio.run(_row(p["id"])).recreates_left is None, p


async def _moved_notices(aid) -> list[str]:
    async with get_session() as s:
        return [n.text for n in (await s.execute(select(AgencyNotification).where(
            AgencyNotification.account_id == aid,
            AgencyNotification.kind == "promo_keep_running"))).scalars() if "moved from" in n.text]


def case_create_takeover_names_previous():
    aid = "pr_takeover"
    asyncio.run(_seed(aid))
    _use_fake()
    a = _create(aid, "Alpha", auto_reactivate=True, expect_taken_from=None)
    assert a["auto_reactivate"] is True and a["keep_running_taken_from"] is None, a
    b = _create(aid, "Beta", auto_reactivate=True, expect_taken_from=a["id"])
    assert b["keep_running_taken_from"] == {"id": a["id"], "name": "Alpha"}, b
    assert not asyncio.run(_row(a["id"])).auto_reactivate and asyncio.run(_row(b["id"])).auto_reactivate
    texts = asyncio.run(_moved_notices(aid))
    assert len(texts) == 1 and "“Alpha” to “Beta”" in texts[0], texts


def case_create_takeover_moved_409():
    aid = "pr_takeover_moved"
    asyncio.run(_seed(aid))
    f = _use_fake()
    a = _create(aid, "Alpha", auto_reactivate=True)
    made = len(f.created)
    r = _client.post("/admin/promotions", json={"account_id": aid, **BODY, "auto_reactivate": True,
                                                "expect_taken_from": None})
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert d["reason"] == "keep_running_moved" and d["taken_from"] == {"id": a["id"], "name": "Alpha"}, d
    assert len(f.created) == made and asyncio.run(_reservations(aid)) == [("manual", "created")]
    assert asyncio.run(_row(a["id"])).auto_reactivate
    c = _create(aid, "Gamma")
    real = f.create_promo

    def arm_gamma_then_create(**kw):        # another tab moves Keep running mid-POST
        async def arm():
            async with get_session() as s:
                (await s.get(PromoCampaign, a["id"])).auto_reactivate = False
                (await s.get(PromoCampaign, c["id"])).auto_reactivate = True
        asyncio.run(arm())
        return real(**kw)
    f.create_promo = arm_gamma_then_create
    r = _create(aid, "Delta", auto_reactivate=True, expect_taken_from=a["id"])
    assert r["auto_reactivate"] is False and "now on “Gamma”" in r["auto_reactivate_refused"], r
    assert asyncio.run(_row(c["id"])).auto_reactivate


def case_rv_c02_manual_age_runs_from_send():
    """c2: a row reserved long ago that only just started sending is in flight (its sender
    may be mid-POST), never offered for "create anyway"."""
    aid = "pr_rv_c02_age"
    asyncio.run(_seed(aid))
    f = _use_fake()
    asyncio.run(_open_row(aid, ago_s=promo_create_guard.SETTLE_GRACE_S * 3, state="sending",
                          sent_ago_s=5))
    r = _client.post("/admin/promotions", json={"account_id": aid, **BODY})
    assert r.status_code == 409 and r.json()["detail"]["reason"] == "create_in_flight", r.text
    assert f.calls == []


def case_rv_c05_takeover_between_reserve_and_send_refused():
    """c5: Keep running moved after the reserve, before the POST: the sending CAS re-checks
    expect_taken_from, 409 keep_running_moved, OF never hears."""
    aid = "pr_rv_c05"
    asyncio.run(_seed(aid))
    f = _use_fake()
    a = _create(aid, "Alpha", auto_reactivate=True)
    c = _create(aid, "Gamma")
    made = len(f.calls)
    real = promo_create_guard.mark_sending

    async def move_then_send(res, recheck):
        async with get_session() as s:
            (await s.get(PromoCampaign, a["id"])).auto_reactivate = False
        async with get_session() as s:
            (await s.get(PromoCampaign, c["id"])).auto_reactivate = True
        return await real(res, recheck)
    promo_create_guard.mark_sending = move_then_send
    try:
        r = _client.post("/admin/promotions", json={"account_id": aid, **BODY, "auto_reactivate": True,
                                                    "expect_taken_from": a["id"]})
    finally:
        promo_create_guard.mark_sending = real
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert d["reason"] == "keep_running_moved" and d["taken_from"]["id"] == c["id"], d
    assert len(f.calls) == made, "OF must not hear a create the operator did not see"
    assert asyncio.run(_reservations(aid))[-1] == ("manual", "failed")


def case_rv_r06_concurrent_ticks_one_kept():
    """r6/c4: two ticks racing (PATCH path, refuse_others) leave exactly one Kept campaign;
    the loser gets 409, never a second Kept row."""
    aid = "pr_rv_r06"
    asyncio.run(_seed(aid))
    _use_fake()
    a, b = _create(aid, "A"), _create(aid, "B")

    async def race():
        return await asyncio.gather(
            promotions_api._arm(aid, a["id"], None, refuse_others=True),
            promotions_api._arm(aid, b["id"], None, refuse_others=True), return_exceptions=True)
    got = asyncio.run(race())
    errs = [g for g in got if isinstance(g, BaseException)]
    assert len(errs) == 1 and getattr(errs[0], "status_code", None) == 409, got
    kept = [x for x in (asyncio.run(_row(a["id"])), asyncio.run(_row(b["id"]))) if x.auto_reactivate]
    assert len(kept) == 1, kept


def case_rv_r08_success_after_create_anyway_no_500():
    """r8: the row was cleared ("create anyway" elsewhere) while this POST was out; OF then
    answers with an id: the reply says unresolved with that id (no 500), and the cleared row
    keeps the id so a read never counts it as a fresh promo."""
    aid = "pr_rv_r08"
    asyncio.run(_seed(aid))
    f = _use_fake()
    real = f.create_promo

    def cleared_meanwhile(**kw):
        async def clear():
            async with get_session() as s:
                for r in (await s.execute(select(PromoCreateReservation).where(
                        PromoCreateReservation.account_id == aid))).scalars():
                    r.state = "cleared"
        asyncio.run(clear())
        return real(**kw)
    f.create_promo = cleared_meanwhile
    r = _client.post("/admin/promotions", json={"account_id": aid, **BODY})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["create"], body["id"], body["of_promo_id"]) == ("unknown", None, f._id), body

    async def kept_id():
        async with get_session() as s:
            return [(x.state, x.of_promo_id) for x in (await s.execute(select(PromoCreateReservation)
                    .where(PromoCreateReservation.account_id == aid))).scalars()]
    assert asyncio.run(kept_id()) == [("cleared", f._id)]


def case_preempt_second_tick():
    aid = "pr_preempt"
    asyncio.run(_seed(aid))
    f = _use_fake()
    a = _create(aid, "A", subscribe_counts=10, auto_reactivate=True)
    assert (a["auto_reactivate"], a["preempt"]) == (True, True), a
    b = _create(aid, "B", subscribe_counts=10, auto_reactivate=True, preempt=False)
    assert b["preempt"] is False and asyncio.run(_row(b["id"])).preempt is False, b
    assert _client.patch(f"/admin/promotions/{b['id']}", json={}).status_code == 422
    r = _client.patch(f"/admin/promotions/{b['id']}", json={"preempt": True})
    assert r.status_code == 200 and r.json()["preempt"] is True and r.json()["auto_reactivate"], r.text
    r = _client.patch(f"/admin/promotions/{b['id']}", json={"preempt": False})
    assert r.status_code == 200 and r.json()["preempt"] is False, r.text
    r = _client.patch(f"/admin/promotions/{b['id']}", json={"auto_reactivate": False})
    assert (r.json()["auto_reactivate"], r.json()["preempt"]) == (False, False), r.text
    r = _client.patch(f"/admin/promotions/{b['id']}", json={"auto_reactivate": True})
    assert r.json()["preempt"] is False, r.text      # a re-tick keeps the second tick

    def listed():
        rows = _client.get(f"/admin/promotions?account_id={aid}").json()["campaigns"]
        return next(c for c in rows if c["id"] == b["id"])
    row = listed()
    assert (row["preempt"], row["keep_wait"], row["keep_blocked"]) == (False, None, None), row
    _client.patch(f"/admin/promotions/{b['id']}", json={"preempt": True})

    async def wait(reason):
        async with get_session() as s:
            await s.merge(PromoKeepState(account_id=aid, wait_reason=reason))
    asyncio.run(wait("count_untrusted"))
    assert listed()["keep_wait"] == "count_untrusted"
    os.environ["PROMO_PREEMPT_ENABLED"] = "0"
    try:
        row = listed()
        assert (row["keep_wait"], row["keep_blocked"]) == (None, "switch"), row
    finally:
        os.environ.pop("PROMO_PREEMPT_ENABLED")
    asyncio.run(wait("clock"))
    row = listed()
    assert (row["keep_wait"], row["keep_blocked"]) == ("clock", "clock"), row
    assert f.reads >= 1


def case_rvb_r4_c8_preempt_only_on_kept():
    aid = "pr_rvb_c8"
    asyncio.run(_seed(aid))
    _use_fake()
    a = _create(aid, "A", subscribe_counts=10, auto_reactivate=True)
    c = _create(aid, "C", subscribe_counts=10)                     # not Kept
    stored = asyncio.run(_row(c["id"])).preempt
    r = _client.patch(f"/admin/promotions/{c['id']}", json={"preempt": not stored})
    assert r.status_code == 422, r.text
    assert asyncio.run(_row(c["id"])).preempt == stored
    r = _client.patch(f"/admin/promotions/{c['id']}", json={"auto_reactivate": False, "preempt": not stored})
    assert r.status_code == 200 and r.json()["preempt"] is False, r.text
    assert asyncio.run(_row(c["id"])).preempt == stored, "an untick never stores the second tick"

    def listed(mid):
        rows = _client.get(f"/admin/promotions?account_id={aid}").json()["campaigns"]
        return next(x for x in rows if x["id"] == mid)
    assert asyncio.run(_row(c["id"])).preempt is True and listed(c["id"])["preempt"] is False

    async def wait(reason):
        async with get_session() as s:
            await s.merge(PromoKeepState(account_id=aid, wait_reason=reason))
    asyncio.run(wait("count_untrusted"))
    assert listed(a["id"])["keep_wait"] == "count_untrusted"
    _client.patch(f"/admin/promotions/{a['id']}", json={"preempt": False})
    assert listed(a["id"])["keep_wait"] is None, "the early tick is off: nothing waits on it"
    _client.patch(f"/admin/promotions/{a['id']}", json={"preempt": True})
    os.environ["PROMO_PREEMPT_ENABLED"] = "0"
    try:
        assert listed(a["id"])["keep_wait"] is None, "the switch is off: nothing waits on it"
    finally:
        os.environ.pop("PROMO_PREEMPT_ENABLED")


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
    case_create_without_id_is_unknown_unarmed,
    case_keep_warning_listed_until_retick,
    case_create_stores_finish_days_and_expires_at,
    case_manual_409_while_open,
    case_create_unresolved_then_resolve_open,
    case_get_reconciles_open_row,
    case_rv_c02_manual_age_runs_from_send,
    case_rv_c05_takeover_between_reserve_and_send_refused,
    case_rv_r06_concurrent_ticks_one_kept,
    case_rv_r08_success_after_create_anyway_no_500,
    case_manual_after_budget_exhaustion,
    case_raw_route_reserved,
    case_raw_finish_unticks,
    case_list_shows_backoff_and_budget,
    case_mn07_tick_on_unfenced_copy_stamps_empty,
    case_mn09_unlimited_trial_refused,
    case_create_takeover_names_previous,
    case_create_takeover_moved_409,
    case_preempt_second_tick,
    case_rvb_r4_c8_preempt_only_on_kept,
)
