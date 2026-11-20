#!/usr/bin/env python3
"""promo_create_guard — the Create reservation (docs/spec/phase-01-promo-preempt.md, ADR-0040):

  case_two_reservers_one_wins    the partial unique index: one open row per Creator.
  case_reserve_rereads_the_campaign  a campaign gone or changed since the decision → refused.
  case_newer_create_refused      an automatic create refuses when a create settled after its
                                 decision read.
  case_rv_c01_stale_read_does_not_overwrite_manual  a manual create sent before the read and
                                 settled during it, or a fresh manual id missing from the read.
  case_rv_c06_rule_gone_dry_run_tick_or_stale_read_refuses  read over 90 s, re-ticked, the
                                 claimed rule dry run / deleted / none: refused (reserve, CAS).
  case_sending_cas               pending → sending once; a recheck miss → failed not_sent, no POST.
  case_outcome_table             2xx + id → created; no id / bad body / 5xx / timeout → unknown;
                                 4xx → failed http_<status> (captcha / price_free by body, the
                                 asked wait kept); refused before send → not_sent; deactivated;
                                 a dead session; the raw route's 502 read through its cause;
                                 proxy refusal / DNS / connect failure / pool busy → not_sent.
  case_failed_backoff_and_turn_off  each failed automatic create sets not_before (doubling,
                                 Retry-After in full); a first 429 keeps Keep running on, a
                                 second in a row turns it off (rate_limited) with one notice.
  case_budget_windows_ignore_manual  budget_state counts automatic rows of the last 24 h only.
  case_rule_and_limit_rechecked  an automatic create refuses when the promo_reactivate rule is
                                 off or the Re-create limit is spent.
  case_manual_adoption_makes_mirror  a manual create adopted by a read gets its mirror row,
                                 unarmed; a raw (OF mirror) one gets none.
  case_clear_open_row            the operator's "create anyway" settles the open row cleared.
  case_rv_c02_clear_only_from_the_state_shown  a row that started sending since is not cleared.
  case_reconcile_adopt           a unique candidate settles created: campaign repointed, the
                                 old id kept under it, one notice per row.
  case_reconcile_several_candidates  two matches stay open (reconcile_reads counts the read).
  case_reconcile_pre_id_excluded  an id seen in the decision read is never adopted.
  case_rv_c03_foreign_promo_before_send_not_adopted  window from sent_at; no pre-send read →
                                 never adopted.
  case_rv_c02_reconcile_leaves_fresh_sender_alone  sending: the sender's until SETTLE_GRACE_S.
  case_rv_c02_pending_expiry_loses_to_sender  the pending expiry is a pending-only CAS.
  case_rv_c07_pending_released_by_time_without_read  a failed read still releases it.
  case_reconcile_null_cap_is_zero  OF's null cap matches a sent 0.
  case_reconcile_no_match_stays_open  no candidate: open, reconcile_reads + 1.
  case_reconcile_pending_past_grace_fails  a pending row past SETTLE_GRACE_S never reached OF.
  case_unknown_lost_at_unknown_off_s  no candidate UNKNOWN_OFF_S after the send → lost, Keep
                                 running off (create_unknown), one notice.
  case_rv_c13_turn_off_persists_keep_warning_at  the stop's time is on the campaign.
  case_rv_r02_pre_send_failure_backs_off_keeps_running  proxy CONNECT refusal → not_sent.
  case_rv_c05_takeover_moved_before_post_refused  expect_kept re-checked at the sending CAS.
  case_rv_c04_duplicate_notices_once  the migration's unticked duplicates: one notice each.
  case_settle_atomic             a crash before commit leaves the row open, the campaign as it was.
  case_rv_r08_late_created_after_cleared_keeps_id  refused late success: id kept on the row.
  case_listed_at_marks_seen_live  the first read showing a created id live stamps listed_at.
  case_fence_rechecked_and_stamped  an automatic reserve refuses (fence) off the stamped box;
                                 the row carries this box's id; a manual one is never fenced.
  case_fence_notices_at_boot     each fenced Kept campaign: one owner notice per env value
                                 (re-tick text for a row with no stamp), none for a stamped one.
  case_rvb_c2_reserve_rechecks_backoff_budget_and_failed_send  in the reservation's own
                                 transaction: a back-off ahead, a full budget window (this row
                                 not counted), no recovery slot for a Pre-emption, and a send
                                 failed after the decision read refuse it.
  case_rvb_r3_timed_window_rechecked  an auto_timed reservation outside its window (local
                                 deadline from OF's end + skew) refuses at reserve and at the
                                 sending CAS.
  case_rvb_r3_skew_sampled_at_answer  the clock skew is the answer's arrival minus OF's
                                 createdAt, not the sending stamp (the POST may wait after it).
  case_rvb_r2_failed_preempt_keeps_running  a 400 or a second 403/429 in a row on a Fill or
                                 Timed: Keep running stays on, its early tick goes off, one
                                 notice that names it; a captcha still turns Keep running off.
  case_rvb_c5_unknown_preempt_notifies_now  a Pre-emption with no clear answer files the
                                 owner notice at once; the row stays open for the reconcile.
  case_f2_untick_during_slot_wait_no_post  a real OFClient whose only signed slot is held: the
                                 Employee unticks Keep running (or Keep running moves, for a
                                 manual create) while the sender waits; the guard re-run right
                                 before the request leaves refuses it: zero POSTs, failed
                                 not_sent, no back-off. Nothing changed: one POST, created.

Run: ./venv/bin/python service/tests/test_promo_create_guard.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first
_harness.bootstrap()

import asyncio  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import requests  # noqa: E402
from curl_cffi.const import CurlECode  # noqa: E402
from curl_cffi.requests import exceptions as curl_exc  # noqa: E402
from sqlalchemy import select  # noqa: E402

import notifications_api  # noqa: E402
import promo_create_guard as g  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (Account, AgencyNotification, AutomationRule, LinkMeta, PromoCampaign,  # noqa: E402
                       PromoCreateReservation, User, UserAccount)
from fastapi import HTTPException  # noqa: E402

from of_client import OFAPIError, OFDeactivatedError, OFDeniedError, OFSignedPoolBusy  # noqa: E402
from of_promos import normalise_of_promo  # noqa: E402

BOX = "test-box"
os.environ[g.HOST_ENV] = BOX

TERMS = {"discount": 50, "subscribe_counts": 10, "subscribe_days": 30, "message": "Promo",
         "type": "all"}


async def _creator(aid: str, *, of_id=500, owner=True) -> int:
    async with get_session() as s:
        s.add(Account(id=aid, nickname=f"nick_{aid}"))
        if owner:
            s.add(User(id=f"u_{aid}", username=f"owner_{aid}", password="pw"))
            s.add(UserAccount(user_id=f"u_{aid}", account_id=aid))
        row = PromoCampaign(account_id=aid, of_promo_id=of_id, name="Summer", discount_percent=50,
                            price_cents=0, subscribe_counts=10, subscribe_days=30, message="Promo",
                            promo_type="all", status="active", subscriber_count=0,
                            auto_reactivate=True, reactivate_count=0, created_at=datetime.utcnow(),
                            keep_host_id=BOX)
        s.add(row)
        # The Keep running tick's rule: enabled, live (not dry run).
        s.add(AutomationRule(account_id=aid, name="keep", kind="promo_reactivate", is_enabled=True,
                             trigger_json="{}", steps_json='{"dry_run": false}'))
        await s.flush()
        return row.id


_TICK = object()   # _reserve: the campaign's current keep_ticked_at (the run's decision)


async def _reserve(aid, cid, *, terms=TERMS, pre=(500,), source="auto_ended", read_at=None,
                   rule_id=None, ticked=_TICK, timed_end=None):
    if ticked is _TICK:
        ticked = None if cid is None or (c := await _campaign(cid)) is None else c.keep_ticked_at
    return await g.reserve(aid, cid, source, terms, {"auto_reactivate": True, "of_promo_id": 500},
                           list(pre), read_at or datetime.utcnow(), rule_id=rule_id, ticked_at=ticked,
                           **({} if timed_end is None else {"timed_end": timed_end}))


async def _row(rid) -> PromoCreateReservation:
    async with get_session() as s:
        return await s.get(PromoCreateReservation, rid)


async def _campaign(cid) -> PromoCampaign:
    async with get_session() as s:
        return await s.get(PromoCampaign, cid)


async def _notices(aid) -> list[AgencyNotification]:
    async with get_session() as s:
        return list((await s.execute(select(AgencyNotification).where(
            AgencyNotification.account_id == aid,
            AgencyNotification.kind == "promo_keep_running"))).scalars())


async def _age(rid, seconds):
    """Backdate a row's clocks (created_at, sent_at) by `seconds`."""
    async with get_session() as s:
        r = await s.get(PromoCreateReservation, rid)
        r.created_at -= timedelta(seconds=seconds)
        if r.sent_at is not None:
            r.sent_at -= timedelta(seconds=seconds)


def _item(pid, *, at=None, counts=10, days=30, message="Promo", type_="all", finished=False):
    raw = {"id": pid, "subscribeCounts": counts, "subscribeDays": days, "message": message,
           "type": type_, "isFinished": finished, "claimsCount": 0,
           "createdAt": (at or datetime.utcnow()).isoformat() + "+00:00"}
    return normalise_of_promo(raw)


async def _sent(aid, cid, **kw) -> g.Reservation:
    res = await _reserve(aid, cid, **kw)
    assert isinstance(res, g.Reservation), res
    assert await g.mark_sending(res, {"auto_reactivate": True}) is None
    return res


async def _unknown(aid, cid, **kw) -> g.Reservation:
    """Sent with no answer: the reconcile owns it (no sender left)."""
    res = await _sent(aid, cid, **kw)
    await g.settle(res, g.Outcome("unknown"))
    return res


async def _manual_created(aid, of_id) -> g.Reservation:
    res = await g.reserve(aid, None, "manual_raw", TERMS, {}, None, None)
    assert await g.mark_sending(res, {}) is None
    await g.settle(res, g.outcome_of(res=[{"id": of_id}]))
    return res


async def case_two_reservers_one_wins():
    aid = "gd_two"
    cid = await _creator(aid)
    a, b = await asyncio.gather(_reserve(aid, cid), _reserve(aid, cid))
    got = sorted([type(a).__name__, type(b).__name__])
    assert got == ["Refused", "Reservation"], (a, b)
    refused = a if isinstance(a, g.Refused) else b
    assert refused.reason == "create_open", refused


async def case_reserve_rereads_the_campaign():
    aid = "gd_reread"
    cid = await _creator(aid)
    async with get_session() as s:
        (await s.get(PromoCampaign, cid)).auto_reactivate = False
    assert await _reserve(aid, cid) == g.Refused("campaign_changed")
    assert await _reserve(aid, 99_999) == g.Refused("campaign_gone")
    async with get_session() as s:
        n = len((await s.execute(select(PromoCreateReservation).where(
            PromoCreateReservation.account_id == aid))).scalars().all())
    assert n == 0, "a refused reserve leaves no row"


async def case_newer_create_refused():
    aid = "gd_newer"
    cid = await _creator(aid)
    read_at = datetime.utcnow() - timedelta(seconds=30)
    await _manual_created(aid, 777)
    assert await _reserve(aid, cid, read_at=read_at) == g.Refused("newer_create")
    assert isinstance(await _reserve(aid, cid, pre=(500, 777)), g.Reservation)


async def case_rv_c01_stale_read_does_not_overwrite_manual():
    """A manual create starts before the automatic GET, the GET misses it, then it settles:
    the automatic create refuses (settled after the read); with a fresh read that still
    misses the manual id (OF lists late), it refuses too (manual_unlisted)."""
    aid = "gd_c01"
    cid = await _creator(aid)
    manual = await g.reserve(aid, None, "manual_raw", TERMS, {}, None, None)
    assert await g.mark_sending(manual, {}) is None
    read_at = datetime.utcnow()                     # the automatic GET begins
    await g.settle(manual, g.outcome_of(res=[{"id": 777}]))
    assert not await g.has_open(aid)
    assert await _reserve(aid, cid, read_at=read_at) == g.Refused("newer_create")
    assert await _reserve(aid, cid) == g.Refused("manual_unlisted"), "fresh read, id missing"
    assert isinstance(await _reserve(aid, cid, pre=(500, 777)), g.Reservation)


async def case_rv_c06_rule_gone_dry_run_tick_or_stale_read_refuses():
    aid = "gd_c06"
    cid = await _creator(aid)
    async with get_session() as s:
        rule = (await s.execute(select(AutomationRule).where(AutomationRule.account_id == aid))).scalar_one()
        rid = rule.id
    assert await _reserve(aid, cid, read_at=datetime.utcnow() - timedelta(seconds=91)) == \
        g.Refused("decision_stale")
    assert await _reserve(aid, cid, ticked=datetime.utcnow() - timedelta(hours=1)) == \
        g.Refused("campaign_changed"), "re-ticked since the decision"
    # Live at reserve, switched to dry run before the POST: no POST.
    res = await _reserve(aid, cid, rule_id=rid)
    assert isinstance(res, g.Reservation), res
    async with get_session() as s:
        (await s.get(AutomationRule, rid)).steps_json = '{"dry_run": true}'
    assert await g.mark_sending(res, {"auto_reactivate": True}) == "rule_off"
    assert (await _row(res.id)).error_class == "not_sent"
    assert await _reserve(aid, cid, rule_id=rid) == g.Refused("rule_off")
    async with get_session() as s:                  # the claimed rule deleted, another live
        await s.delete(await s.get(AutomationRule, rid))
        s.add(AutomationRule(account_id=aid, name="keep2", kind="promo_reactivate", is_enabled=True,
                             trigger_json="{}", steps_json='{"dry_run": false}'))
    assert await _reserve(aid, cid, rule_id=rid) == g.Refused("rule_off")
    async with get_session() as s:                  # no rule at all
        for r in (await s.execute(select(AutomationRule).where(AutomationRule.account_id == aid))).scalars():
            await s.delete(r)
    assert await _reserve(aid, cid) == g.Refused("rule_off")


async def case_sending_cas():
    aid = "gd_cas"
    cid = await _creator(aid)
    res = await _reserve(aid, cid)
    assert await g.mark_sending(res, {"auto_reactivate": True}) is None
    assert await g.mark_sending(res, {"auto_reactivate": True}) == "not_pending", "sending only once"
    row = await _row(res.id)
    assert row.state == "sending" and row.sent_at is not None, row.state

    aid = "gd_cas_miss"
    cid = await _creator(aid)
    res = await _reserve(aid, cid)
    async with get_session() as s:
        (await s.get(PromoCampaign, cid)).auto_reactivate = False      # unticked after reserve
    assert await g.mark_sending(res, {"auto_reactivate": True}) == "campaign_changed"
    row = await _row(res.id)
    assert (row.state, row.error_class, row.sent_at) == ("failed", "not_sent", None), row.state


class _Resp:
    def __init__(self, status, text="", headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}


def _raw(err: BaseException, status: int) -> HTTPException:
    """server._proxy's translation of a transport / pool error: `raise ... from e`."""
    try:
        raise HTTPException(status, str(err)) from err
    except HTTPException as e:
        return e


def _raw_502(err: OFAPIError) -> HTTPException:
    """server._proxy's translation: the OF error rides along as the cause."""
    try:
        raise HTTPException(502, {"upstream_status": err.response.status_code}) from err
    except HTTPException as e:
        return e


async def case_outcome_table():
    item = {"id": 7, "subscribeCounts": 10, "isFinished": False}
    rows = [
        (dict(res=[item]), "created", None),
        (dict(res={"promoId": 7}), "created", None),
        (dict(res={"success": True}), "unknown", None),
        (dict(res=None), "unknown", None),
        (dict(res=[]), "unknown", None),
        (dict(error=ValueError("bad json")), "unknown", None),
        (dict(error=requests.Timeout()), "unknown", None),
        (dict(error=requests.ConnectionError()), "unknown", None),
        (dict(error=OFAPIError("502", response=_Resp(502))), "unknown", None),
        (dict(error=OFAPIError("400", response=_Resp(400))), "failed", "http_400"),
        (dict(error=OFAPIError("429", response=_Resp(429))), "failed", "http_429"),
        (dict(error=OFDeniedError("slot busy")), "failed", "not_sent"),
        (dict(error=OFDeactivatedError("deactivated")), "failed", "deactivated"),
        (dict(error=OFAPIError("403", response=_Resp(403, '{"error":{"message":"Access denied."}}'))),
         "failed", "price_free"),
        (dict(error=OFAPIError("400", response=_Resp(400, "please solve the Captcha"))), "failed", "captcha"),
        (dict(error=OFAPIError("400 Wrong user.", response=_Resp(400, '{"error":{"code":301,"message":"Wrong user."}}'))),
         "failed", "session_dead"),
        (dict(error=_raw_502(OFAPIError("429", response=_Resp(429)))), "failed", "http_429"),
        (dict(error=HTTPException(502, "no cause")), "unknown", None),
        # rv r2/c8: provably before the request left the box → not_sent, never unknown.
        (dict(error=curl_exc.ProxyError("CONNECT 403")), "failed", "not_sent"),
        (dict(error=_raw(curl_exc.ProxyError("CONNECT 403"), 502)), "failed", "not_sent"),
        (dict(error=curl_exc.DNSError("no such host")), "failed", "not_sent"),
        (dict(error=curl_exc.ConnectionError("refused", code=CurlECode.COULDNT_CONNECT)), "failed", "not_sent"),
        (dict(error=curl_exc.ConnectionError("reset", code=CurlECode.RECV_ERROR)), "unknown", None),
        (dict(error=curl_exc.Timeout("read")), "unknown", None),
        (dict(error=OFSignedPoolBusy()), "failed", "not_sent"),
        (dict(error=_raw(OFSignedPoolBusy(), 503)), "failed", "not_sent"),
    ]
    for kw, state, cls in rows:
        got = g.outcome_of(**kw)
        assert (got.state, got.error_class) == (state, cls), (kw, got)
        if state == "created":
            assert got.item["of_promo_id"] == 7, got
    got = g.outcome_of(error=OFAPIError("429", response=_Resp(429, "", {"Retry-After": "28800"})))
    assert got.retry_after_s == 28800.0, got
    got = g.outcome_of(error=OFAPIError("429", response=_Resp(429, "Please allow 90 seconds")))
    assert got.retry_after_s == 90.0, got
    assert g.outcome_of(error=OFAPIError("400", response=_Resp(400))).retry_after_s is None


async def case_failed_backoff_and_turn_off():
    aid = "gd_backoff"
    cid = await _creator(aid)
    async with get_session() as s:
        (await s.get(PromoCampaign, cid)).keep_ticked_at = datetime.utcnow() - timedelta(hours=1)
    t0 = datetime.utcnow()
    res = await _sent(aid, cid)
    await g.settle(res, g.outcome_of(error=OFAPIError("429", response=_Resp(429, "", {"Retry-After": "30"}))))
    row = await _row(res.id)
    assert (row.state, row.error_class, row.retry_after_s) == ("failed", "http_429", 30.0)
    assert abs((row.not_before - (t0 + timedelta(seconds=120))).total_seconds()) < 5, row.not_before
    assert (await _campaign(cid)).auto_reactivate and await _notices(aid) == []
    async with get_session() as s:      # the back-off over: a reserve inside it is refused
        (await s.get(PromoCreateReservation, res.id)).not_before = datetime.utcnow()
    res = await _sent(aid, cid)
    await g.settle(res, g.outcome_of(error=OFAPIError("429", response=_Resp(429))))
    row = await _row(res.id)
    assert abs((row.not_before - (t0 + timedelta(seconds=240))).total_seconds()) < 5, row.not_before
    c = await _campaign(cid)
    assert (c.auto_reactivate, c.keep_warning) == (False, "rate_limited"), (c.auto_reactivate, c.keep_warning)
    assert len(await _notices(aid)) == 1
    budget = await g.budget_state(aid, datetime.utcnow())
    assert len(budget.auto_times) == 2 and budget.not_before == row.not_before, budget


async def case_budget_windows_ignore_manual():
    aid = "gd_budget"
    cid = await _creator(aid)
    now = datetime.utcnow()
    async with get_session() as s:
        for source, state, ago in (("auto_ended", "created", 600), ("auto_ended", "failed", 3000),
                                   ("manual", "created", 60), ("manual_raw", "failed", 120),
                                   ("auto_ended", "created", 90_000)):
            s.add(PromoCreateReservation(account_id=aid, campaign_id=cid, source=source, state=state,
                                         terms_json="{}", created_at=now - timedelta(seconds=ago)))
    budget = await g.budget_state(aid, now)
    assert sorted(budget.auto_times) == [now - timedelta(seconds=3000), now - timedelta(seconds=600)], budget
    assert budget.not_before is None


async def case_rule_and_limit_rechecked():
    aid = "gd_rule"
    cid = await _creator(aid)
    async with get_session() as s:
        for r in (await s.execute(select(AutomationRule).where(AutomationRule.account_id == aid))).scalars():
            r.is_enabled = False
    assert await _reserve(aid, cid) == g.Refused("rule_off")
    async with get_session() as s:
        for r in (await s.execute(select(AutomationRule).where(AutomationRule.account_id == aid))).scalars():
            r.is_enabled = True
        (await s.get(PromoCampaign, cid)).recreates_left = 0
    assert await _reserve(aid, cid) == g.Refused("limit_reached")
    async with get_session() as s:
        (await s.get(PromoCampaign, cid)).recreates_left = 2
    res = await _reserve(aid, cid)
    assert isinstance(res, g.Reservation), res
    async with get_session() as s:
        (await s.get(PromoCampaign, cid)).recreates_left = 0          # spent after the reserve
    assert await g.mark_sending(res, {"auto_reactivate": True}) == "limit_reached"
    assert (await _row(res.id)).error_class == "not_sent"


MANUAL = {**TERMS, "mirror": {"name": "Spring", "promo_type": "all"}}


async def case_manual_adoption_makes_mirror():
    aid = "gd_manual"
    await _creator(aid)
    res = await g.reserve(aid, None, "manual", MANUAL, {}, [], None)
    assert await g.mark_sending(res, {}) is None
    await g.settle(res, g.Outcome("unknown"))
    await g.reconcile(aid, [_item(701, days=0)])
    row = await _row(res.id)
    assert (row.state, row.of_promo_id) == ("created", 701), row.state
    m = await _campaign(row.campaign_id)
    assert (m.name, m.of_promo_id, m.discount_percent, m.subscribe_days, m.auto_reactivate) == \
        ("Spring", 701, 50, 0, False), (m.name, m.of_promo_id, m.subscribe_days, m.auto_reactivate)

    aid = "gd_manual_raw"
    await _creator(aid)
    res = await g.reserve(aid, None, "manual_raw", TERMS, {}, [], None)
    assert await g.mark_sending(res, {}) is None
    await g.settle(res, g.outcome_of(res=[{"id": 702}]))
    row = await _row(res.id)
    assert (row.state, row.campaign_id) == ("created", None), (row.state, row.campaign_id)


async def case_clear_open_row():
    aid = "gd_clear"
    await _creator(aid)
    res = await g.reserve(aid, None, "manual", MANUAL, {}, [], None)
    assert await g.mark_sending(res, {}) is None
    await g.settle(res, g.Outcome("unknown"))
    row = await g.open_row(aid)
    assert row is not None and row.id == res.id
    assert await g.clear(row) is True
    assert (await _row(res.id)).state == "cleared" and await g.open_row(aid) is None
    assert await g.clear(row) is False


async def case_rv_c02_clear_only_from_the_state_shown():
    """The operator was shown a stale pending row; its sender flipped it to sending since:
    "create anyway" does not clear the active sender."""
    aid = "gd_c02_clear"
    await _creator(aid)
    res = await g.reserve(aid, None, "manual", MANUAL, {}, [], None)
    shown = await g.open_row(aid)
    assert await g.mark_sending(res, {}) is None
    assert await g.clear(shown) is False
    assert (await _row(res.id)).state == "sending"


async def case_reconcile_adopt():
    aid = "gd_adopt"
    cid = await _creator(aid)
    res = await _sent(aid, cid)
    await g.settle(res, g.outcome_of(res={"success": True}))
    assert (await _row(res.id)).state == "unknown"
    items = [_item(601), _item(500, finished=True)]
    assert await g.reconcile(aid, items) == 1
    row = await _row(res.id)
    assert (row.state, row.of_promo_id) == ("created", 601), (row.state, row.of_promo_id)
    c = await _campaign(cid)
    assert (c.of_promo_id, c.reactivate_count) == (601, 1), (c.of_promo_id, c.reactivate_count)
    async with get_session() as s:
        meta = (await s.execute(select(LinkMeta).where(
            LinkMeta.account_id == aid, LinkMeta.of_id == 500))).scalar_one()
    assert meta.campaign_id == cid
    notes = await _notices(aid)
    assert len(notes) == 1 and notes[0].dedupe_key == f"promo_create:{res.id}", notes
    assert "Summer" in notes[0].text and "601" in notes[0].text and "ended" in notes[0].text
    assert await g.reconcile(aid, items) == 0 and len(await _notices(aid)) == 1, "once per row"


async def case_reconcile_several_candidates():
    aid = "gd_several"
    cid = await _creator(aid)
    res = await _unknown(aid, cid)
    assert await g.reconcile(aid, [_item(601), _item(602)]) == 0
    row = await _row(res.id)
    assert (row.state, row.reconcile_reads) == ("unknown", 1), (row.state, row.reconcile_reads)


async def case_reconcile_pre_id_excluded():
    aid = "gd_pre"
    cid = await _creator(aid)
    res = await _unknown(aid, cid, pre=(500, 601))
    assert await g.reconcile(aid, [_item(601)]) == 0
    assert (await _row(res.id)).state == "unknown"
    # and a candidate outside the window (made before the send) is not one either
    assert await g.reconcile(aid, [_item(602, at=datetime.utcnow() - timedelta(minutes=5))]) == 0
    # nor one whose terms differ
    for other in (_item(603, counts=9), _item(604, message="x"), _item(605, type_="expired")):
        assert await g.reconcile(aid, [other]) == 0, other
    assert (await _row(res.id)).state == "unknown"


async def case_rv_c03_foreign_promo_before_send_not_adopted():
    """A same-terms promo made after the reservation but before its POST, then the POST goes
    unanswered: not adopted (the window starts at sent_at). A manual row with no read before
    its send is never adopted."""
    aid = "gd_c03"
    cid = await _creator(aid)
    res = await _reserve(aid, cid)
    await _age(res.id, 60)                          # reserved a minute ago, still pending
    foreign = _item(601, at=datetime.utcnow() - timedelta(seconds=30))
    assert await g.mark_sending(res, {"auto_reactivate": True}) is None
    await g.settle(res, g.Outcome("unknown"))
    assert await g.reconcile(aid, [foreign]) == 0
    assert (await _row(res.id)).state == "unknown"
    await g.settle(res, g.Outcome("cleared"))

    aid = "gd_c03_manual"
    await _creator(aid)
    res = await g.reserve(aid, None, "manual", MANUAL, {}, None, None)
    assert await g.mark_sending(res, {}) is None
    await g.settle(res, g.Outcome("unknown"))
    assert await g.reconcile(aid, [_item(702)]) == 0
    assert (await _row(res.id)).state == "unknown", "no ids known before the send: never adopted"


async def case_rv_c02_reconcile_leaves_fresh_sender_alone():
    """A sending row's sender may still be in its POST: no adoption, no read counted, until
    SETTLE_GRACE_S past sent_at; then the reconcile has it."""
    aid = "gd_c02_sender"
    cid = await _creator(aid)
    res = await _sent(aid, cid)
    assert await g.reconcile(aid, [_item(601)]) == 0
    row = await _row(res.id)
    assert (row.state, row.reconcile_reads) == ("sending", 0), (row.state, row.reconcile_reads)
    await _age(res.id, g.SETTLE_GRACE_S + 1)
    assert await g.reconcile(aid, [_item(601)]) == 1
    assert (await _row(res.id)).of_promo_id == 601


async def case_rv_c02_pending_expiry_loses_to_sender():
    """Reconcile reads an expired pending row; its worker wins pending → sending before the
    cleanup writes: the pending-only CAS leaves the sender alone (no second POST freed)."""
    aid = "gd_c02_race"
    cid = await _creator(aid)
    res = await _reserve(aid, cid)
    await _age(res.id, g.SETTLE_GRACE_S + 1)
    real = g.settle

    async def worker_first(r, outcome, **kw):
        await g.mark_sending(res, {"auto_reactivate": True})      # the worker's CAS lands first
        return await real(r, outcome, **kw)
    g.settle = worker_first
    try:
        assert await g.reconcile(aid, []) == 0
    finally:
        g.settle = real
    row = await _row(res.id)
    assert row.state == "sending" and await g.has_open(aid), row.state


async def case_rv_c07_pending_released_by_time_without_read():
    """OF reads keep failing: elapsed time alone releases a never-sent row."""
    aid = "gd_c07"
    cid = await _creator(aid)
    res = await _reserve(aid, cid)
    await _age(res.id, g.SETTLE_GRACE_S + 1)
    assert await g.reconcile(aid, None) == 1
    row = await _row(res.id)
    assert (row.state, row.error_class) == ("failed", "not_sent") and not await g.has_open(aid)


async def case_reconcile_null_cap_is_zero():
    aid = "gd_null"
    cid = await _creator(aid)
    res = await _unknown(aid, cid, terms={**TERMS, "subscribe_counts": 0})
    assert await g.reconcile(aid, [_item(601, counts=None)]) == 1
    assert (await _row(res.id)).of_promo_id == 601


async def case_reconcile_no_match_stays_open():
    aid = "gd_none"
    cid = await _creator(aid)
    res = await _unknown(aid, cid)
    assert await g.reconcile(aid, [_item(500, finished=True)]) == 0
    assert await g.reconcile(aid, []) == 0
    row = await _row(res.id)
    assert (row.state, row.reconcile_reads) == ("unknown", 2), (row.state, row.reconcile_reads)
    assert await g.reconcile(aid, None) == 0 and (await _row(res.id)).reconcile_reads == 2, \
        "a failed read is no read"


async def case_reconcile_pending_past_grace_fails():
    aid = "gd_pending"
    cid = await _creator(aid)
    res = await _reserve(aid, cid)
    await g.reconcile(aid, [])
    assert (await _row(res.id)).state == "pending", "inside grace its sender may still send"
    await _age(res.id, g.SETTLE_GRACE_S + 1)
    await g.reconcile(aid, [_item(601)])
    row = await _row(res.id)
    assert (row.state, row.error_class) == ("failed", "not_sent"), row.state


async def case_unknown_lost_at_unknown_off_s():
    aid = "gd_lost"
    cid = await _creator(aid)
    res = await _sent(aid, cid)
    await g.settle(res, g.Outcome("unknown"))
    await _age(res.id, g.UNKNOWN_OFF_S - 30)
    await g.reconcile(aid, [])
    assert (await _row(res.id)).state == "unknown"
    await _age(res.id, 31)
    await g.reconcile(aid, [])
    assert (await _row(res.id)).state == "lost"
    c = await _campaign(cid)
    assert (c.auto_reactivate, c.keep_warning) == (False, "create_unknown"), (c.auto_reactivate,
                                                                               c.keep_warning)
    notes = await _notices(aid)
    assert len(notes) == 1 and notes[0].dedupe_key.startswith(f"promo_keep_off:{cid}:"), notes


async def case_rv_c13_turn_off_persists_keep_warning_at():
    """The committed stop carries its time (the 4 h sweep reads it, not the log line)."""
    aid = "gd_c13"
    cid = await _creator(aid)
    t0 = datetime.utcnow()
    async with get_session() as s:
        await g.turn_off(s, aid, cid, "breaker", t0)
    c = await _campaign(cid)
    assert (c.auto_reactivate, c.keep_warning, c.keep_warning_at) == (False, "breaker", t0), \
        (c.auto_reactivate, c.keep_warning, c.keep_warning_at)


async def case_rv_r02_pre_send_failure_backs_off_keeps_running():
    """The proxy refuses CONNECT once `_proxy_retry` gave up: the POST never left, so the row is
    failed not_sent with a back-off, never unknown (which would turn Keep running off)."""
    aid = "gd_r02"
    cid = await _creator(aid)
    res = await _reserve(aid, cid)

    class Client:
        posts = 0

        def create_promo(self, **kw):
            Client.posts += 1
            raise curl_exc.ProxyError("CONNECT tunnel failed, response 403")
    sent = await g.send(res, {"auto_reactivate": True}, Client, TERMS)
    assert (sent.outcome.state, sent.outcome.error_class) == ("failed", "not_sent"), sent.outcome
    row = await _row(res.id)
    assert row.state == "failed" and row.not_before is not None and Client.posts == 1, row.state
    assert (await _campaign(cid)).auto_reactivate and not await g.has_open(aid)


async def case_rv_c05_takeover_moved_before_post_refused():
    """The form showed Keep running on campaign A; another tab moved it before the POST: the
    sending CAS refuses (keep_running_moved), no POST."""
    aid = "gd_c05"
    cid = await _creator(aid)
    res = await g.reserve(aid, None, "manual", MANUAL, {}, None, None, expect_kept=cid)
    assert isinstance(res, g.Reservation), res
    async with get_session() as s:
        (await s.get(PromoCampaign, cid)).auto_reactivate = False
    posts = []
    sent = await g.send(res, {}, lambda: type("C", (), {"create_promo": lambda self, **k: posts.append(k)})(),
                        MANUAL)
    assert sent.outcome is None and sent.refused == "keep_running_moved" and posts == [], sent
    assert (await _row(res.id)).error_class == "not_sent"
    assert await g.reserve(aid, None, "manual", MANUAL, {}, None, None, expect_kept=cid) == \
        g.Refused("keep_running_moved")


async def case_rv_c04_duplicate_notices_once():
    """The one-Kept migration's unticked duplicates: one owner notice each, once."""
    aid = "gd_dup"
    cid = await _creator(aid)
    async with get_session() as s:
        c = await s.get(PromoCampaign, cid)
        c.auto_reactivate, c.keep_warning, c.keep_warning_at = False, "kept_duplicate", datetime.utcnow()
    assert await g.duplicate_notices() >= 1
    await g.duplicate_notices()
    notes = await _notices(aid)
    assert len(notes) == 1 and g.OFF_TEXT["kept_duplicate"] in notes[0].text, [n.text for n in notes]


async def case_settle_atomic():
    aid = "gd_atomic"
    cid = await _creator(aid)
    res = await _sent(aid, cid)

    class Crash(Exception):
        pass

    real = notifications_api.file_for_creator_owners

    async def boom(*a, **k):
        raise Crash()
    notifications_api.file_for_creator_owners = boom
    try:
        try:
            await g.settle(res, g.outcome_of(res=[{"id": 601}]))
            raise AssertionError("the crash must surface")
        except Crash:
            pass
    finally:
        notifications_api.file_for_creator_owners = real
    row = await _row(res.id)
    assert (row.state, row.of_promo_id) == ("sending", None), (row.state, row.of_promo_id)
    c = await _campaign(cid)
    assert (c.of_promo_id, c.reactivate_count) == (500, 0), (c.of_promo_id, c.reactivate_count)
    assert await _notices(aid) == []


async def case_rv_r08_late_created_after_cleared_keeps_id():
    """A late success after "create anyway": the settle is refused, but OF's id lands on the
    row (held: no other reservation adopts it); no repoint, no notice."""
    aid = "gd_late"
    cid = await _creator(aid)
    res = await _sent(aid, cid)
    async with get_session() as s:
        (await s.get(PromoCreateReservation, res.id)).state = "cleared"
    assert await g.settle(res, g.outcome_of(res=[{"id": 601}])) is False
    row = await _row(res.id)
    assert (row.state, row.of_promo_id) == ("cleared", 601), (row.state, row.of_promo_id)
    assert (await _campaign(cid)).of_promo_id == 500 and await _notices(aid) == []
    later = await g.reserve(aid, None, "manual", MANUAL, {}, [500], None)
    assert await g.mark_sending(later, {}) is None
    await g.settle(later, g.Outcome("unknown"))
    assert await g.reconcile(aid, [_item(601)]) == 0, "the late id is held"


async def case_listed_at_marks_seen_live():
    aid = "gd_listed"
    cid = await _creator(aid)
    res = await _sent(aid, cid)
    await g.settle(res, g.outcome_of(res=[{"id": 601}]))
    await g.reconcile(aid, [_item(601, finished=True)])
    assert (await _row(res.id)).listed_at is None, "listed but ended is not live"
    await g.reconcile(aid, [_item(601)])
    first = (await _row(res.id)).listed_at
    assert first is not None
    await g.reconcile(aid, [_item(601)])
    assert (await _row(res.id)).listed_at == first, "the first sighting sticks"


async def case_fence_rechecked_and_stamped():
    aid = "gd_fence"
    cid = await _creator(aid)
    os.environ[g.HOST_ENV] = "box-b"
    try:
        assert await _reserve(aid, cid) == g.Refused("fence")
        manual = await g.reserve(aid, None, "manual", TERMS, {}, None, None)
        assert isinstance(manual, g.Reservation), manual
        assert (await _row(manual.id)).host_id == "box-b"
        await g.settle(manual, g.Outcome("cleared"))
    finally:
        os.environ[g.HOST_ENV] = BOX
    res = await _reserve(aid, cid)
    assert isinstance(res, g.Reservation) and (await _row(res.id)).host_id == BOX, res
    os.environ[g.HOST_ENV] = ""
    try:
        assert await g.mark_sending(res, {"auto_reactivate": True}) == "fence"   # env gone before the POST
    finally:
        os.environ[g.HOST_ENV] = BOX


async def case_fence_notices_at_boot():
    aid, old, ok = "gd_boot", "gd_boot_old", "gd_boot_ok"
    a = await _creator(aid, of_id=901)
    b = await _creator(old, of_id=902)
    await _creator(ok, of_id=903)
    async with get_session() as s:
        (await s.get(PromoCampaign, a)).keep_host_id = "box-a"
        (await s.get(PromoCampaign, b)).keep_host_id = None
    assert await g.fence_notices() >= 2
    assert await g.fence_notices() >= 2                     # a second boot files nothing new
    mine, theirs, none = await _notices(aid), await _notices(old), await _notices(ok)
    assert len(mine) == 1 and g.FENCE_TEXT in mine[0].text, [n.text for n in mine]
    assert mine[0].dedupe_key == f"promo_keep_fenced:{a}:{BOX}", mine[0].dedupe_key
    assert len(theirs) == 1 and g.RETICK_TEXT in theirs[0].text, [n.text for n in theirs]
    assert none == [], [n.text for n in none]
    os.environ[g.HOST_ENV] = "box-c"                        # a new env value: one more each
    try:
        await g.fence_notices()
    finally:
        os.environ[g.HOST_ENV] = BOX
    assert len(await _notices(aid)) == 2 and len(await _notices(ok)) == 1


async def _auto_row(aid, cid, *, ago_s, source="auto_ended", state="created", not_before=None,
                    sent_ago_s=None, error_class=None):
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(PromoCreateReservation(
            account_id=aid, campaign_id=cid, source=source, state=state, terms_json="{}",
            created_at=now - timedelta(seconds=ago_s), not_before=not_before, error_class=error_class,
            sent_at=None if sent_ago_s is None else now - timedelta(seconds=sent_ago_s),
            settled_at=now - timedelta(seconds=ago_s)))


async def case_rvb_c2_reserve_rechecks_backoff_budget_and_failed_send():
    now = datetime.utcnow()
    aid = "gd_c2_backoff"
    cid = await _creator(aid)
    await _auto_row(aid, cid, ago_s=4000, state="failed", not_before=now + timedelta(minutes=5),
                    sent_ago_s=4000, error_class="http_500")
    assert await _reserve(aid, cid) == g.Refused("backoff")
    aid = "gd_c2_budget"
    cid = await _creator(aid)
    for ago in (600, 1200, 1800):
        await _auto_row(aid, cid, ago_s=ago)
    assert await _reserve(aid, cid) == g.Refused("budget")
    aid = "gd_c2_slot"
    cid = await _creator(aid)
    for ago in (600, 1200):
        await _auto_row(aid, cid, ago_s=ago)
    assert await _reserve(aid, cid, source="auto_fill") == g.Refused("no_recovery_slot")
    res = await _reserve(aid, cid)                  # the 3rd of 3: this row itself not counted
    assert isinstance(res, g.Reservation), res
    # a send that failed after this decision's read (its back-off already over): the read
    # predates whatever that send did on OF
    aid = "gd_c2_failed"
    cid = await _creator(aid)
    read_at = datetime.utcnow() - timedelta(seconds=30)
    await _auto_row(aid, cid, ago_s=20, state="failed", sent_ago_s=15, error_class="http_400",
                    not_before=now - timedelta(seconds=1))
    assert await _reserve(aid, cid, read_at=read_at) == g.Refused("newer_create")
    # never sent (refused before the POST): no effect on OF, the read still holds
    aid = "gd_c2_not_sent"
    cid = await _creator(aid)
    await _auto_row(aid, cid, ago_s=20, state="failed", error_class="not_sent")
    assert isinstance(await _reserve(aid, cid, read_at=read_at), g.Reservation)


async def case_rvb_r3_timed_window_rechecked():
    from dataclasses import replace
    aid = "gd_r3"
    cid = await _creator(aid)
    async with get_session() as s:
        (await s.get(PromoCampaign, cid)).preempt = True
    past = datetime.utcnow() - timedelta(seconds=1)
    assert await _reserve(aid, cid, source="auto_timed", timed_end=past) == g.Refused("timed_window")
    far = datetime.utcnow() + timedelta(seconds=g.TIMED_LEAD_S + 30)
    assert await _reserve(aid, cid, source="auto_timed", timed_end=far) == g.Refused("timed_window")
    res = await _reserve(aid, cid, source="auto_timed", timed_end=datetime.utcnow() + timedelta(seconds=100))
    assert isinstance(res, g.Reservation), res
    # the window closed while the POST waited for its slot: no POST
    assert await g.mark_sending(replace(res, timed_end=past), {"auto_reactivate": True}) == "timed_window"
    assert (await _row(res.id)).error_class == "not_sent"


async def case_rvb_r3_skew_sampled_at_answer():
    from db.models import PromoKeepState
    aid = "gd_r3_skew"
    cid = await _creator(aid)
    res = await _reserve(aid, cid)
    loop = asyncio.get_running_loop()

    class Client:
        def create_promo(self, **kw):
            # the POST waited 100 s for its slot after the sending stamp
            asyncio.run_coroutine_threadsafe(_age(res.id, 100), loop).result()
            return [{"id": 777, "createdAt": datetime.utcnow().isoformat() + "+00:00"}]
    sent = await g.send(res, {"auto_reactivate": True}, Client, TERMS)
    assert sent.outcome.state == "created", sent
    async with get_session() as s:
        skew = (await s.get(PromoKeepState, aid)).skew_s
    assert skew is not None and abs(skew) <= 2, skew


async def case_rvb_r2_failed_preempt_keeps_running():
    async def fill_failed(aid, err_status, *, prev_status=None):
        cid = await _creator(aid)
        async with get_session() as s:
            c = await s.get(PromoCampaign, cid)
            c.preempt, c.keep_ticked_at = True, datetime.utcnow() - timedelta(hours=1)
        if prev_status is not None:
            res = await _sent(aid, cid, source="auto_fill")
            await g.settle(res, g.outcome_of(error=OFAPIError(str(prev_status), response=_Resp(prev_status))))
            async with get_session() as s:               # its back-off over
                (await s.get(PromoCreateReservation, res.id)).not_before = datetime.utcnow()
            c = await _campaign(cid)
            assert (c.auto_reactivate, c.preempt) == (True, True), "a first 403/429 backs off only"
        res = await _sent(aid, cid, source="auto_fill")
        await g.settle(res, g.outcome_of(error=OFAPIError(str(err_status), response=_Resp(err_status))))
        return cid, res
    for aid, status, prev in (("gd_r2_400", 400, None), ("gd_r2_429", 429, 429), ("gd_r2_403", 403, 429)):
        cid, res = await fill_failed(aid, status, prev_status=prev)
        c = await _campaign(cid)
        assert (c.auto_reactivate, c.preempt, c.keep_warning) == (True, False, None), \
            (aid, c.auto_reactivate, c.preempt, c.keep_warning)
        assert (await _row(res.id)).not_before is not None
        texts = [n.text for n in await _notices(aid)]
        mine = [t for t in texts if "early re-create" in t]
        off = [t for t in mine if "Re-create at 90% filled is off" in t]
        assert len(mine) == (1 if prev is None else 2) and len(off) == 1 \
            and "short wait" not in off[0], (aid, texts)
    # captcha: Keep running off as before; the early-failure notice promises no re-create
    aid = "gd_r2_captcha"
    cid = await _creator(aid)
    async with get_session() as s:
        (await s.get(PromoCampaign, cid)).preempt = True
    res = await _sent(aid, cid, source="auto_fill")
    await g.settle(res, g.outcome_of(error=OFAPIError("400", response=_Resp(400, "captcha required"))))
    c = await _campaign(cid)
    assert (c.auto_reactivate, c.keep_warning) == (False, "captcha"), (c.auto_reactivate, c.keep_warning)
    texts = [n.text for n in await _notices(aid)]
    assert not any("short wait" in t for t in texts), texts
    # a first 429 (nothing turned off): the short-wait notice, the tick stays
    aid = "gd_r2_first"
    cid = await _creator(aid)
    async with get_session() as s:
        (await s.get(PromoCampaign, cid)).preempt = True
    res = await _sent(aid, cid, source="auto_fill")
    await g.settle(res, g.outcome_of(error=OFAPIError("429", response=_Resp(429))))
    c = await _campaign(cid)
    assert (c.auto_reactivate, c.preempt) == (True, True)
    texts = [n.text for n in await _notices(aid)]
    assert len(texts) == 1 and "short wait" in texts[0], texts


async def case_rvb_c5_unknown_preempt_notifies_now():
    aid = "gd_c5"
    cid = await _creator(aid)
    async with get_session() as s:
        (await s.get(PromoCampaign, cid)).preempt = True
    res = await _sent(aid, cid, source="auto_fill")
    assert await g.settle(res, g.Outcome("unknown"))
    assert (await _row(res.id)).state == "unknown"
    texts = [n.text for n in await _notices(aid)]
    assert len(texts) == 1 and "no promo may be live" in texts[0], texts
    assert (await _campaign(cid)).auto_reactivate
    # an After-end with no clear answer: still no notice (the reconcile has it)
    aid = "gd_c5_ended"
    cid = await _creator(aid)
    res = await _sent(aid, cid)
    await g.settle(res, g.Outcome("unknown"))
    assert await _notices(aid) == []


# ── rwl fixes ───────────────────────────────────────────────────────────────

class _WireResp:
    def __init__(self, body):
        import json as _json
        self.status_code, self.ok, self.headers, self.url = 200, True, {}, "https://onlyfans.com/x"
        self._body = body
        self.text = _json.dumps(body)

    def json(self):
        return self._body


def _slot_client(aid, sent, answer_id):
    """A real OFClient (no session) with ONE signed slot; its transport records each request
    that would leave the box and answers OF's created LIST: every gate in _http_call runs."""
    import threading
    from _of_wire import fake_wire
    from of_client import OFClient
    c = object.__new__(OFClient)
    c.account_id, c.proxy_label = aid, None
    fake_wire(c, object())
    c._signed_slots = threading.BoundedSemaphore(1)
    c._ensure_x_hash = lambda **_k: "h"
    c._persist_cf_cookies = lambda r: None
    c._note_signed_ok = lambda url, r: None

    def _transport(_fn, *, what="", **_k):
        sent.append(what)
        return _WireResp([{"id": answer_id, "subscribeCounts": 10, "subscribeDays": 30,
                           "message": "Promo", "type": "all", "claimsCount": 0, "isFinished": False}])
    c._proxy_retry = _transport
    return c


async def _send_while_held(res, recheck, c, change):
    """send() while the slot is held; once the row is sending (the sender waits on the slot),
    run `change`, then free the slot."""
    c._signed_slots.acquire()          # another call holds the account's only signed slot
    task = asyncio.create_task(g.send(res, recheck, lambda: c, TERMS))
    try:
        for _ in range(500):
            if (await _row(res.id)).state != "pending":
                break
            await asyncio.sleep(0.01)
        assert (await _row(res.id)).state == "sending"     # past the CAS, waiting on the slot
        await change()
    finally:
        c._signed_slots.release()
    return await asyncio.wait_for(task, 20)


async def case_f2_untick_during_slot_wait_no_post():
    aid = "gd_f2_slot"
    cid = await _creator(aid)
    sent: list[str] = []
    c = _slot_client(aid, sent, 7001)
    res = await _reserve(aid, cid)

    async def untick():
        async with get_session() as s:
            (await s.get(PromoCampaign, cid)).auto_reactivate = False
    out = await _send_while_held(res, {"auto_reactivate": True}, c, untick)
    assert sent == [] and out.outcome is None and out.refused == "campaign_changed", (sent, out)
    r = await _row(res.id)
    assert (r.state, r.error_class, r.sent_at, r.not_before) == ("failed", "not_sent", None, None), \
        (r.state, r.error_class, r.sent_at, r.not_before)
    # nothing changed while it waited: one POST, created
    async with get_session() as s:
        (await s.get(PromoCampaign, cid)).auto_reactivate = True
    res = await _reserve(aid, cid)

    async def nothing():
        return None
    out = await _send_while_held(res, {"auto_reactivate": True}, c, nothing)
    assert len(sent) == 1 and out.outcome.state == "created", (sent, out)
    # a manual create: Keep running moved while it waited
    aid = "gd_f2_manual"
    kept = await _creator(aid)
    sent = []
    c = _slot_client(aid, sent, 7002)
    res = await g.reserve(aid, None, "manual", TERMS, {}, None, None, expect_kept=kept)

    async def move():
        async with get_session() as s:
            (await s.get(PromoCampaign, kept)).auto_reactivate = False
    out = await _send_while_held(res, {}, c, move)
    assert sent == [] and out.refused == "keep_running_moved", (sent, out)


async def case_n1_failed_dispatch_check_is_not_sent():
    """The last guard itself raising (a locked DB) sent nothing: failed `not_sent`, the row
    closed, never `unknown` (which would block creates and end in create_unknown)."""
    aid = "gd_n1_check_raises"
    cid = await _creator(aid)
    sent: list[str] = []
    c = _slot_client(aid, sent, 7003)
    res = await _reserve(aid, cid)
    real = g._dispatch_check

    async def boom(*_a, **_k):
        raise RuntimeError("database is locked")
    g._dispatch_check = boom
    try:
        out = await g.send(res, {"auto_reactivate": True}, lambda: c, TERMS)
    finally:
        g._dispatch_check = real
    assert sent == [], sent
    assert out.outcome is not None and (out.outcome.state, out.outcome.error_class) == ("failed", "not_sent"), out
    r = await _row(res.id)
    assert (r.state, r.error_class) == ("failed", "not_sent"), (r.state, r.error_class)
    assert not await g.has_open(aid)        # closed: the next create is not blocked


_harness.run()
