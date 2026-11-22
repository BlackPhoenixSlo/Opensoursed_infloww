"""service/promo_create_guard.py — the one gate every promo create on OnlyFans goes through
(docs/spec/phase-01-promo-preempt.md, ADR-0040).

A create is a Create reservation row (`promo_create_reservations`), committed BEFORE the
POST and settled after it, so a crash, an unparsed id or a racing create never mints a
duplicate:

  reserve       re-read the campaign and insert `pending`, one transaction; the partial
                unique index allows one open row per Creator (`create_open`).
  mark_sending  in the sending thread before the POST: pending → sending (CAS) plus the
                same re-read; a miss → failed `not_sent`, no POST.
  dispatch      the same re-read again inside the transport, right before the request leaves
                (after the signed-slot wait and warm-up, of_client.PRE_DISPATCH); a miss →
                failed `not_sent`, no POST.
  settle        one transaction: the state CAS (open states, or the caller's), the campaign
                repoint, the old id kept under the campaign (link_metrics), the owner notice.
  reconcile     a `pending` row past SETTLE_GRACE_S never reached OF: failed `not_sent` by a
                pending-only CAS, read or no read. On an OF list read a sent row (its sender
                gone: SETTLE_GRACE_S past sent_at) is adopted only on a UNIQUE candidate made
                after sent_at and absent from the ids known before the send; none after
                UNKNOWN_OFF_S → lost, Keep running off.
  send          the shared POST: the client, the sending CAS and create_promo in one thread.
  budget_state  the Create budget's and back-off's facts (automatic rows only).
  fenced        the Host fence (ADR-0041): an automatic create runs only on the box whose
                PROMO_CREATE_HOST_ID is stamped on the campaign; fence_notices at boot.

A failed or lost automatic create sets the Create back-off (`not_before`); some failures
turn Keep running off (promo_keep_decide.failure_turns_off). A manual create adopted late
gets its mirror row from `terms["mirror"]`.

An automatic create's decision holds only while nothing else touched OF since its read
(DECISION_MAX_AGE_S, no create sent or settled after it, no fresh manual id missing from
it), its rule and tick are unchanged and the back-off and Create budget still allow it
(`_recheck`, at reserve, at the sending CAS and right before the request leaves).

A negative read never settles a sent row `failed`: OF may list a create late. An error
that provably fired before the request left the box is failed `not_sent` (`_pre_send`).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping, Sequence

from curl_cffi.const import CurlECode
from curl_cffi.requests import exceptions as curl_exc
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

import account_health
import link_metrics
import notifications_api
import of_pacing
import runtime_switches
from automations._knobs import bool_knob
from db.engine import get_session
from db.models import AutomationRule, PromoCampaign, PromoCreateReservation, PromoKeepState
from isotime import parse_iso
from of_client import (PRE_DISPATCH, OFAPIError, OFDeactivatedError, OFDeniedError, OFDispatchRefused,
                       proxy_refused)
from of_promos import extract_created_promo, normalise_of_promo, promo_expires_at
from promo_keep_decide import (BREAKER_N, TIMED_LEAD_S, backoff_until, create_hold,  # noqa: F401
                               failure_turns_off, in_timed_window, preempt_failure, recovery_slot)

log = logging.getLogger("of-relay.promo_create_guard")

SETTLE_GRACE_S = 600       # a pending row this old lost its sender (> slot wait + retries)
UNKNOWN_OFF_S = 900        # a sent row with no candidate this long after the send is lost
CREATED_AT_SLACK_S = 5     # OF's createdAt may trail our sent_at stamp by this much
DECISION_MAX_AGE_S = 90    # an automatic create's OF read older than this no longer decides
OPEN = ("pending", "sending", "unknown")
REACHED = ("sending", "unknown", "created", "lost")    # states of a create that may be on OF
AUTO_SOURCES = ("auto_ended", "auto_fill", "auto_timed")
PREEMPT_SOURCES = ("auto_fill", "auto_timed")    # end a live promo: the switch must still be on
PREEMPT_SWITCH = "PROMO_PREEMPT_ENABLED"
MANUAL_SOURCES = ("manual", "manual_raw")
NOTICE_KIND = "promo_keep_running"
_SOURCE_WORD = {"auto_ended": "ended", "auto_fill": "filled", "auto_timed": "was ending"}
# Why Inflowwww turned Keep running off (campaign keep_warning), and who fixes it.
OFF_TEXT = {
    "create_unknown": "a promo create got no clear answer from OnlyFans and never showed up — "
                      "check the promos on OnlyFans, then tick Keep running again",
    "breaker": "3 promos in a row got no new claims or never went live — check the offer, "
               "then tick Keep running again",
    "price_free": "OnlyFans refused the promo because the page is free — set a subscription "
                  "price on OnlyFans, then tick Keep running again",
    "captcha": "OnlyFans asked for a captcha — open the account on OnlyFans, then tick Keep "
               "running again",
    "deactivated": "this Creator is deactivated — activate it, then tick Keep running again",
    "rate_limited": "OnlyFans refused two promo creates in a row (rate limit or block) — wait a "
                    "while, then tick Keep running again",
    "create_refused": "OnlyFans refused the promo create — check the offer, then tick Keep "
                      "running again",
    "limit_reached": "the free trial used up its Re-create limit — tick Keep running again "
                     "to set a new one",
    "limit_needed": "this free trial has no Offer limit, so it can't keep running — create a "
                    "new one with an Offer limit",
    "kept_duplicate": "another campaign of this Creator was also set to keep running, and only "
                      "one can be — tick Keep running again on the one you want",
}
HOST_ENV = "PROMO_CREATE_HOST_ID"
FENCE_TEXT = "This server is not set to create promos — ask the owner to set it up"
RETICK_TEXT = "Tick Keep running again"
KEEP_KIND = "promo_reactivate"


NO_EXPECT = object()       # Reservation.expect_kept: no Takeover expectation to check


@dataclass(frozen=True)
class Reservation:
    """An open create. The decision facts ride along for `_recheck`: the automatic create's
    read start, claimed rule and campaign tick; the manual create's expected Kept campaign
    (Takeover) and the OF ids known before its send (None: no read, never adopted)."""
    id: int
    account_id: str
    campaign_id: int | None
    source: str
    terms: dict = field(default_factory=dict)
    decision_read_at: datetime | None = None
    pre_ids: tuple[int, ...] | None = None
    rule_id: int | None = None
    ticked_at: datetime | None = None
    expect_kept: Any = NO_EXPECT
    timed_end: datetime | None = None    # auto_timed: OF's end on our clock (end + skew)


@dataclass(frozen=True)
class Refused:
    reason: str
    blocking: int | None = None    # create_open: the open row met; create_landed: the landed one


@dataclass(frozen=True)
class Outcome:
    """What a create came to: created (with OF's normalised `item`), failed, unknown, lost,
    cleared."""
    state: str
    item: dict | None = None
    error_class: str | None = None
    retry_after_s: float | None = None    # OF's asked wait on a refusal, uncapped


def _causes(error: BaseException) -> list[BaseException]:
    """`error` and its `raise ... from` causes (never `__context__`, see proxy_refused)."""
    out: list[BaseException] = []
    e: BaseException | None = error
    while e is not None and all(e is not x for x in out):
        out.append(e)
        e = e.__cause__
    return out


def _pre_send(e: BaseException) -> bool:
    """Fired before the request left the box: the proxy refused the tunnel, the name did
    not resolve, the TCP connect failed (curl 6/7). The signed-pool wait is an OFDeniedError."""
    return (proxy_refused(e) or isinstance(e, curl_exc.DNSError)
            or (isinstance(e, curl_exc.ConnectionError)
                and getattr(e, "code", None) == CurlECode.COULDNT_CONNECT))


def outcome_of(res: Any = None, error: BaseException | None = None) -> Outcome:
    """The send's result or exception → its Outcome. Anything that may have reached OF
    without an id to show for it is unknown, never failed (the reconcile decides)."""
    if error is not None:
        chain = _causes(error)
        if any(_pre_send(e) for e in chain):
            return Outcome("failed", error_class="not_sent")
        # server._proxy's HTTPException carries OF's error as its cause, header included.
        error = next((e for e in chain if isinstance(e, OFAPIError)), error)
        if isinstance(error, OFDeactivatedError):
            return Outcome("failed", error_class="deactivated")
        if isinstance(error, OFDeniedError):
            return Outcome("failed", error_class="not_sent")
        if account_health.is_session_dead_error(error):
            return Outcome("failed", error_class="session_dead")
        status, body, header = of_pacing.upstream(error) if isinstance(error, OFAPIError) else (None, "", None)
        if isinstance(status, int) and 400 <= status < 500:
            text = f"{body} {error}"
            # OF's free-page refusal (api_errors.raise_if_free_page_denied); captcha: a guess.
            cls = ("price_free" if "Access denied" in text
                   else "captcha" if "captcha" in text.lower() else f"http_{status}")
            return Outcome("failed", error_class=cls,
                           retry_after_s=of_pacing.asked_wait(header, of_pacing.allow_s(body)))
        return Outcome("unknown")     # 5xx, timeout, connection, bad body: may have landed
    item = normalise_of_promo(extract_created_promo(res))
    return Outcome("created", item=item) if item.get("of_promo_id") is not None else Outcome("unknown")


def host_id() -> str:
    """This box's Host fence id: env only, one value per box; "" = no automatic creates."""
    return os.environ.get(HOST_ENV, "").strip()


def fenced(stamp: str | None) -> str | None:
    """Why this box may not make a campaign's automatic creates, or None: "retick" for a
    campaign ticked before the fence existed (no stamp), "fence" when the env is unset or
    differs from the stamp (a DB copy, the other box of a failover pair)."""
    if stamp is None:
        return "retick"
    here = host_id()
    return None if here and here == stamp else "fence"


def unlimited_trial(discount: int | None, cap: int | None) -> bool:
    """A Free trial (discount 100) with no Claim cap: an automatic create could hand out free
    subs without end, each promo unbounded, so it may not keep running. The one rule the run
    and the API's 422 read. The Re-create limit is optional (owner 2026-11-21: Keep running
    is indefinite by default)."""
    return int(discount or 0) == 100 and not cap


def trial_unlimited(c: PromoCampaign) -> bool:
    """`unlimited_trial` of a campaign row."""
    return unlimited_trial(c.discount_percent, c.subscribe_counts)


def _live_rule(steps_json: str | None) -> bool:
    try:
        steps = json.loads(steps_json or "{}")
    except (TypeError, ValueError):
        steps = {}
    return not bool_knob(steps if isinstance(steps, dict) else {}, "dry_run", True)


async def _recheck(s, res: Reservation, want: Mapping[str, Any], now: datetime) -> str | None:
    """Why the decision no longer holds, or None: the campaign gone or changed (`want`:
    its columns that must still read so); a Takeover expectation broken. For an automatic
    create also the Host fence, the Re-create limit, the tick it decided on, its rule
    (gone, off or dry run now), the read's age, a create sent or settled after the read,
    a send that failed after it, the back-off and both budget windows (this row not
    counted), and a manual create too fresh to trust its absence from the read. A
    Pre-emption (Fill, Timed) also needs PROMO_PREEMPT_ENABLED still on (its kill switch)
    and a recovery create left in the budget; a Timed one its window still open."""
    R = PromoCreateReservation
    auto = res.source in AUTO_SOURCES
    if res.campaign_id is not None:
        c = await s.get(PromoCampaign, res.campaign_id)
        if c is None or c.account_id != res.account_id:
            return "campaign_gone"
        if any(getattr(c, k) != v for k, v in want.items()):
            return "campaign_changed"
        if auto and fenced(c.keep_host_id):
            return "fence"
        if auto and c.recreates_left == 0:
            return "limit_reached"
        if auto and trial_unlimited(c):
            return "trial_unlimited"
        if auto and c.keep_ticked_at != res.ticked_at:
            return "campaign_changed"     # re-ticked or unticked since the decision
    if res.source in PREEMPT_SOURCES and not runtime_switches.on(PREEMPT_SWITCH):
        return "switch_off"
    if res.expect_kept is not NO_EXPECT:
        kept = (await s.execute(select(PromoCampaign.id).where(
            PromoCampaign.account_id == res.account_id, PromoCampaign.auto_reactivate.is_(True))
            .order_by(PromoCampaign.id).limit(1))).scalar_one_or_none()
        if kept != res.expect_kept:
            return "keep_running_moved"
    if not auto:
        return None
    q = select(AutomationRule.steps_json).where(
        AutomationRule.account_id == res.account_id, AutomationRule.kind == KEEP_KIND,
        AutomationRule.is_enabled.is_(True))
    if res.rule_id is not None:
        q = q.where(AutomationRule.id == res.rule_id)
    if not any(_live_rule(j) for j in (await s.execute(q)).scalars().all()):
        return "rule_off"
    read = res.decision_read_at
    if read is None or now - read > timedelta(seconds=DECISION_MAX_AGE_S):
        return "decision_stale"
    # A failed send may have ended the live promo on OF all the same: the read predates it.
    failed_sent = and_(R.state == "failed", R.sent_at.is_not(None),
                       R.error_class.is_distinct_from("not_sent"))
    newer = (await s.execute(select(R.id).where(
        R.account_id == res.account_id, R.id != res.id, or_(R.state.in_(REACHED), failed_sent),
        or_(R.sent_at > read, R.settled_at > read)).limit(1))).scalar_one_or_none()
    if newer is not None:
        return "newer_create"
    if res.source == "auto_timed" and (
            res.timed_end is None or not in_timed_window((res.timed_end - now).total_seconds())):
        return "timed_window"
    # The run decided on its own budget read; a racing run may have spent it since.
    times, not_before = await _budget_facts(s, res.account_id, now, exclude_id=res.id)
    hold = create_hold(times, not_before, now)
    if hold:
        return hold[0]
    if res.source in PREEMPT_SOURCES and not recovery_slot(times, now):
        return "no_recovery_slot"
    fresh = (await s.execute(select(R.of_promo_id).where(
        R.account_id == res.account_id, R.source.in_(MANUAL_SOURCES), R.state == "created",
        R.of_promo_id.is_not(None),
        R.settled_at > now - timedelta(seconds=SETTLE_GRACE_S)))).scalars().all()
    if any(int(i) not in set(res.pre_ids or ()) for i in fresh):
        return "manual_unlisted"
    return None


async def reserve(account_id: str, campaign_id: int | None, source: str, terms: dict,
                  expect: Mapping[str, Any], pre_ids: Sequence[int] | None,
                  decision_read_at: datetime | None, *, replaced_of_promo_id: int | None = None,
                  claims_seen: int | None = None, first_claims: int | None = None,
                  rule_id: int | None = None, ticked_at: datetime | None = None,
                  expect_kept: Any = NO_EXPECT, timed_end: datetime | None = None,
                  unless_landed: int | None = None) -> Reservation | Refused:
    """Insert a `pending` row for this create, or refuse. `terms` are create_promo's kwargs
    (the reconcile matches on them); `pre_ids` the OF ids in the read before it (never
    adopted; None = no read, the row is never adopted). The keyword facts feed the
    Zero-claim breaker and `_recheck`. One transaction under SQLite's write lock: the
    Creator's open row refuses it `create_open` with that row's id (`blocking`), and
    reservation `unless_landed` (the earlier create a manual one replaces) settled created
    refuses it `create_landed`, so no read between them and the insert can let a replacement
    through after that create landed."""
    aid = str(account_id)
    ids = None if pre_ids is None else tuple(sorted({int(i) for i in pre_ids}))
    R = PromoCreateReservation
    try:
        async with get_session() as s:
            now = datetime.utcnow()
            # A write first: SQLite's write lock, so the reads below are the ones the insert acts on.
            await s.execute(update(R).where(R.account_id == aid, R.state.in_(OPEN)).values(state=R.state))
            if unless_landed is not None and (await s.execute(select(R.id).where(
                    R.id == unless_landed, R.account_id == aid, R.state == "created"))).scalar_one_or_none():
                return Refused("create_landed", unless_landed)
            if (blocking := (await s.execute(select(R.id).where(
                    R.account_id == aid, R.state.in_(OPEN)).limit(1))).scalar_one_or_none()) is not None:
                return Refused("create_open", blocking)
            row = PromoCreateReservation(
                account_id=aid, campaign_id=campaign_id, source=source, state="pending",
                terms_json=json.dumps(terms), pre_ids_json=None if ids is None else json.dumps(ids),
                replaced_of_promo_id=replaced_of_promo_id, claims_seen=claims_seen,
                first_claims=first_claims, host_id=host_id(), created_at=now)
            s.add(row)
            await s.flush()      # the unique index stays the backstop
            res = Reservation(row.id, aid, campaign_id, source, dict(terms), decision_read_at,
                              ids, rule_id, ticked_at, expect_kept, timed_end)
            why = await _recheck(s, res, expect, now)
            if why:
                await s.rollback()
                return Refused(why)
    except IntegrityError:
        # The open-row index, or the campaign's foreign key (deleted since the decision).
        async with get_session() as s:
            gone = campaign_id is not None and await s.get(PromoCampaign, campaign_id) is None
        return Refused("campaign_gone" if gone else "create_open")
    return res


async def _guard(res: Reservation, recheck: Mapping[str, Any], frm: str) -> str | None:
    """One guard for both moments: the row must still be `frm` (the write first: SQLite's lock,
    and the row still ours), it becomes sending with sent_at now, then the pre-POST re-read.
    A decision that no longer holds settles the row failed `not_sent` (never sent, so no
    back-off). Returns why there is no POST, or None to send."""
    now = datetime.utcnow()
    R = PromoCreateReservation
    async with get_session() as s:
        if (await s.execute(update(R).where(R.id == res.id, R.state == frm)
                            .values(state="sending", sent_at=now))).rowcount != 1:
            return f"not_{frm}"
        why = await _recheck(s, res, recheck, now)
        if why:
            await s.execute(update(R).where(R.id == res.id)
                            .values(state="failed", error_class="not_sent", sent_at=None, settled_at=now))
            log.info("promo_create not sent account=%s reservation=%s reason=%s at=%s",
                     res.account_id, res.id, why, "cas" if frm == "pending" else "dispatch")
    return why


async def mark_sending(res: Reservation, recheck: Mapping[str, Any]) -> str | None:
    """pending → sending right before the POST, plus the pre-POST re-read. Returns why there
    is no POST (already sending/settled: "not_pending"; the decision no longer holds: the
    row is failed `not_sent`), or None to send."""
    return await _guard(res, recheck, "pending")


async def _dispatch_check(res: Reservation, recheck: Mapping[str, Any]) -> str | None:
    """The last guard, right before the request leaves the box (of_client.PRE_DISPATCH): the
    sending CAS's re-read again, after the signed-slot wait (up to SIGNED_WAIT_S) and the
    warm-up, so an untick, a moved Keep running or a stale decision meanwhile sends nothing.
    sent_at moves to now (the request's real start). "not_sending": the row was cleared
    meanwhile."""
    return await _guard(res, recheck, "sending")


def _create_notice(res: Reservation, campaign: str, new_id: int | None):
    word = _SOURCE_WORD.get(res.source, "ended")
    return lambda nick: notifications_api.Notice(
        NOTICE_KIND, f"{nick}: Keep running re-created “{campaign}” after the last promo {word} — "
        f"new OnlyFans promo {new_id}.", account_id=res.account_id,
        data={"reservation_id": res.id, "of_promo_id": new_id}, dedupe=f"promo_create:{res.id}")


async def turn_off(s, account_id: str, campaign_id: int, reason: str, now: datetime) -> list[str]:
    """Inflowwww turns Keep running off (caller's transaction): the warning stays on the
    campaign for the card, one notice per stop. Returns the Agencies filed for (push their
    unread after commit). A campaign already unticked by the operator is left alone."""
    c = await s.get(PromoCampaign, campaign_id)
    if c is None or not c.auto_reactivate:
        return []
    c.auto_reactivate = False
    c.keep_warning = reason
    c.keep_warning_at = now     # the committed stop the 4 h sweep counts (not the log line)
    log.warning("promo_keep_off account=%s campaign=%s reason=%s", account_id, campaign_id, reason)
    return await notifications_api.file_for_creator_owners(s, account_id, lambda nick: notifications_api.Notice(
        NOTICE_KIND, f"{nick}: Keep running is off for “{c.name}” — {OFF_TEXT.get(reason, reason)}.",
        account_id=account_id, data={"campaign_id": campaign_id, "reason": reason},
        dedupe=f"promo_keep_off:{campaign_id}:{now.isoformat()}"))


async def _repoint(s, res: Reservation, item: dict, now: datetime) -> list[str]:
    """The Kept campaign follows its new OF promo (an automatic create)."""
    row = await s.get(PromoCampaign, res.campaign_id)
    if row is None:
        return []
    new_id = item.get("of_promo_id")
    if row.of_promo_id and new_id != row.of_promo_id:
        # The finished promo stays under the campaign: its claimers' spend still counts
        # toward the campaign's Revenue (link_metrics).
        (await link_metrics.meta_row(s, res.account_id, "promo", int(row.of_promo_id))).campaign_id = row.id
    row.of_promo_id = new_id
    row.status = "active"
    row.subscriber_count = 0
    row.reactivate_count = int(row.reactivate_count or 0) + 1
    row.last_reactivated_at = now
    row.expires_at = promo_expires_at(item.get("finished_at"), row.finish_days, now)
    filed = await notifications_api.file_for_creator_owners(
        s, res.account_id, _create_notice(res, row.name, new_id))
    if row.recreates_left is not None:
        row.recreates_left = max(0, row.recreates_left - 1)
        if row.recreates_left == 0:
            # The Free trial's last allowed Re-create is live: Keep running stops here.
            filed += await turn_off(s, res.account_id, row.id, "limit_reached", now)
    return filed


async def seed_memo(s, account_id: str, item: dict) -> None:
    """A Kept create's answer with Claims above 0: the claim memo (promo_keep_state) holds
    the new id untrusted (first_claims None), so no later read makes its count Trusted. An
    answer at 0 seeds nothing: OF may still show the old promo's count on the first read
    (claims lag), so the first_read Re-check's read decides. A memo already on the id stays."""
    pid = item.get("of_promo_id")
    if pid is None or not item.get("claims_present") or int(item.get("subscriber_count") or 0) <= 0:
        return
    vals = {"kept_of_promo_id": pid, "first_claims": None,
            "last_claims": int(item.get("subscriber_count") or 0), "read_at": datetime.utcnow(),
            "finished_at": item.get("finished_at")}
    await s.execute(sqlite_insert(PromoKeepState).values(account_id=str(account_id), **vals)
                    .on_conflict_do_update(index_elements=["account_id"], set_=vals,
                                           where=PromoKeepState.kept_of_promo_id.is_distinct_from(pid)))


async def _stamp_skew(s, res: Reservation, item: dict, answer_at: datetime) -> None:
    """Our clock against OF's, from our own create: when its answer arrived minus OF's
    createdAt (Timed needs it known and small). Not the sending stamp: the POST may wait
    for its slot after it. An answer with no createdAt makes it unknown."""
    at = parse_iso(item.get("created_at"))
    skew = round((answer_at - at).total_seconds()) if at is not None else None
    await s.execute(sqlite_insert(PromoKeepState).values(account_id=res.account_id, skew_s=skew)
                    .on_conflict_do_update(index_elements=["account_id"], set_={"skew_s": skew}))


async def _preempt_failed(s, res: Reservation, *, kept_off: bool, untick: bool,
                         recover: bool) -> list[str]:
    """A failed Pre-emption may still have ended the live promo on OF: say so. After-end
    recovers it once the back-off passes (the recovery slot keeps a create for it), so the
    short wait is promised only when a recovery is queued (`recover`, preempt_failure's); a
    dead session resumes once logged in again. `untick`: its early tick goes off (an OF
    refusal: early creates would keep failing), Keep running stays on."""
    c = await s.get(PromoCampaign, res.campaign_id)
    log.warning("promo_preempt_failed account=%s campaign=%s reservation=%s",
                res.account_id, res.campaign_id, res.id)
    if untick and c is not None and c.preempt:
        c.preempt = False
        log.warning("promo_preempt_off account=%s campaign=%s reservation=%s",
                    res.account_id, res.campaign_id, res.id)
    name = c.name if c is not None else f"#{res.campaign_id}"
    tail = ("" if kept_off else
            " Re-create at 90% filled is off for it now (tick it again to retry); Keep running still "
            "re-creates it after the promo ends." if untick else
            " It re-creates after a short wait." if recover else
            " It re-creates once the Creator is logged in again.")
    return await notifications_api.file_for_creator_owners(s, res.account_id, lambda nick: notifications_api.Notice(
        NOTICE_KIND, f"{nick}: Keep running's early re-create of “{name}” failed — OnlyFans may have "
        f"ended the old promo, so no promo may be live.{tail}",
        account_id=res.account_id, data={"campaign_id": res.campaign_id, "reservation_id": res.id},
        dedupe=f"promo_preempt_failed:{res.id}"))


async def _preempt_unknown(s, res: Reservation) -> list[str]:
    """A Pre-emption with no clear answer may have ended the live promo with nothing new up:
    tell the owners now, not UNKNOWN_OFF_S later (the reconcile still settles the row)."""
    c = await s.get(PromoCampaign, res.campaign_id)
    log.warning("promo_preempt_unknown account=%s campaign=%s reservation=%s",
                res.account_id, res.campaign_id, res.id)
    name = c.name if c is not None else f"#{res.campaign_id}"
    return await notifications_api.file_for_creator_owners(s, res.account_id, lambda nick: notifications_api.Notice(
        NOTICE_KIND, f"{nick}: Keep running's early re-create of “{name}” got no clear answer from "
        f"OnlyFans — no promo may be live. Check the promos on OnlyFans.",
        account_id=res.account_id, data={"campaign_id": res.campaign_id, "reservation_id": res.id},
        dedupe=f"promo_preempt_unknown:{res.id}"))


async def _adopt_manual(s, res: Reservation, item: dict, now: datetime) -> None:
    """A Growth create's mirror row, from the terms its reservation carries: what OF did
    where the item says (OF stores subscribeDays 0 for a percent discount). Not armed: a
    Keep running tick moved behind the operator's back would be a silent Takeover."""
    t, m = res.terms, res.terms.get("mirror") or {}
    days = item.get("subscribe_days")
    row = PromoCampaign(
        account_id=res.account_id, of_promo_id=item.get("of_promo_id"),
        name=m.get("name") or f"Promo #{item.get('of_promo_id')}",
        discount_percent=int(t.get("discount") or 0), price_cents=0,
        subscribe_counts=int(t.get("subscribe_counts") or 0),
        subscribe_days=int(t.get("subscribe_days") or 0) if days is None else days,
        message=t.get("message") or "", promo_type=m.get("promo_type") or "all", status="active",
        subscriber_count=item.get("subscriber_count") or 0, created_at=now,
        finish_days=t.get("finish_days"),
        expires_at=promo_expires_at(item.get("finished_at"), t.get("finish_days"), now))
    s.add(row)
    await s.flush()
    await s.execute(update(PromoCreateReservation).where(PromoCreateReservation.id == res.id)
                    .values(campaign_id=row.id))


async def _backoff(s, res: Reservation, outcome: Outcome, now: datetime) -> tuple[datetime, str | None]:
    """This failed automatic create's not_before, and the class of the send failure just
    before it (since the campaign's tick, back to the last created row): k counts them."""
    R = PromoCreateReservation
    c = await s.get(PromoCampaign, res.campaign_id) if res.campaign_id is not None else None
    q = select(R.state, R.error_class, R.not_before).where(
        R.account_id == res.account_id, R.source.in_(AUTO_SOURCES), R.id != res.id,
        R.state.in_(("created", "failed", "lost")))
    if c is not None and c.keep_ticked_at is not None:
        q = q.where(R.created_at >= c.keep_ticked_at)
    k, prev = 1, None
    for state, cls, not_before in (await s.execute(q.order_by(R.id.desc()).limit(64))).all():
        if state == "created":
            break
        if not_before is None:
            continue       # refused at the sending CAS: never reached OF
        if k == 1:
            prev = cls
        k += 1
    return backoff_until(now, k, outcome.retry_after_s), prev


async def settle(res: Reservation, outcome: Outcome, *, only: Sequence[str] = OPEN,
                 answer_at: datetime | None = None) -> bool:
    """Settle the row in one transaction; False when it was not in `only` (no-op). `unknown`
    keeps it open (sending → unknown) for the reconcile. A refused `created` still records
    OF's id on the row, so no other reservation adopts that promo. `answer_at`: when the
    sender got OF's answer (the clock skew's sample; a reconcile's adoption has none)."""
    now = datetime.utcnow()
    R = PromoCreateReservation
    filed: list[str] = []
    async with get_session() as s:
        if outcome.state == "unknown":
            moved = (await s.execute(update(R).where(R.id == res.id, R.state == "sending")
                                     .values(state="unknown"))).rowcount == 1
            if moved and res.source in PREEMPT_SOURCES and res.campaign_id is not None:
                filed = await _preempt_unknown(s, res)
        else:
            moved = None
    if moved is not None:
        await notifications_api.push_unread(filed)
        return moved
    async with get_session() as s:
        new_id = (outcome.item or {}).get("of_promo_id")
        cols: dict[str, Any] = {}
        auto = res.source in AUTO_SOURCES
        if auto and outcome.state in ("failed", "lost"):
            cols["not_before"], prev = await _backoff(s, res, outcome, now)
            cols["retry_after_s"] = outcome.retry_after_s
        moved = (await s.execute(update(R).where(R.id == res.id, R.state.in_(tuple(only))).values(
            state=outcome.state, of_promo_id=new_id, error_class=outcome.error_class,
            settled_at=now, **cols))).rowcount
        if moved != 1:
            if outcome.state == "created" and new_id is not None:
                # A late answer after "create anyway" or a lost call: the promo is on OF.
                await s.execute(update(R).where(R.id == res.id, R.of_promo_id.is_(None))
                                .values(of_promo_id=new_id))
                log.warning("promo_create late_created account=%s reservation=%s of_promo_id=%s",
                            res.account_id, res.id, new_id)
            return False
        if outcome.state == "created" and answer_at is not None:
            await _stamp_skew(s, res, outcome.item, answer_at)
        if outcome.state == "created" and auto and res.campaign_id is not None:
            filed = await _repoint(s, res, outcome.item, now)
            await seed_memo(s, res.account_id, outcome.item)
        elif outcome.state == "created" and res.source == "manual":
            await _adopt_manual(s, res, outcome.item, now)
        elif outcome.state == "lost" and res.campaign_id is not None:
            filed = await turn_off(s, res.account_id, res.campaign_id, "create_unknown", now)
        elif outcome.state == "failed" and auto and res.campaign_id is not None:
            pre = res.source in PREEMPT_SOURCES
            off, untick, recover = preempt_failure(outcome.error_class, prev) if pre else \
                (failure_turns_off(outcome.error_class, prev), False, False)
            if off:
                filed = await turn_off(s, res.account_id, res.campaign_id, off, now)
            if pre and outcome.error_class != "not_sent":
                filed += await _preempt_failed(s, res, kept_off=bool(off), untick=untick,
                                               recover=recover)
    log.info("promo_create settled account=%s reservation=%s state=%s of_promo_id=%s",
             res.account_id, res.id, outcome.state, new_id)
    await notifications_api.push_unread(filed)
    return True


def _audience(v: Any) -> frozenset[str]:
    parts = v.split(",") if isinstance(v, str) else list(v or ())
    return frozenset(str(p).strip() for p in parts if str(p).strip()) or frozenset({"all"})


def _candidate(r: PromoCreateReservation, p: dict, held: set[int], now: datetime) -> bool:
    """`p` (a normalised OF item) may be the promo row `r` created. OF echoes no discount,
    so: an id not known before the send (a row with no read before it is never adopted),
    made after the send, with the same cap (OF's null = 0), message and audience;
    subscribeDays only for discount 100 (OF stores 0 otherwise)."""
    if r.pre_ids_json is None or r.sent_at is None:
        return False
    terms = json.loads(r.terms_json or "{}")
    pid = p.get("of_promo_id")
    if pid is None or pid in held or pid in set(json.loads(r.pre_ids_json)):
        return False
    at = parse_iso(p.get("created_at"))
    if at is None or not r.sent_at - timedelta(seconds=CREATED_AT_SLACK_S) <= at <= now:
        return False
    if int(p.get("subscribe_counts") or 0) != int(terms.get("subscribe_counts") or 0):
        return False
    if (p.get("message") or "") != (terms.get("message") or ""):
        return False
    if _audience(p.get("promo_type")) != _audience(terms.get("type")):
        return False
    return int(terms.get("discount") or 0) != 100 or \
        int(p.get("subscribe_days") or 0) == int(terms.get("subscribe_days") or 0)


def reservation_of(r: PromoCreateReservation) -> Reservation:
    pre = None if r.pre_ids_json is None else tuple(json.loads(r.pre_ids_json))
    return Reservation(r.id, r.account_id, r.campaign_id, r.source, json.loads(r.terms_json or "{}"),
                       pre_ids=pre)


async def reconcile(account_id: str, items: Sequence[dict] | None) -> int:
    """Settle the Creator's open rows: a stale `pending` by time alone; sent rows against
    this OF read (normalised items; None = no read). Stamps listed_at on recent automatic
    creates seen live. Returns rows settled."""
    aid, now, R = str(account_id), datetime.utcnow(), PromoCreateReservation
    grace = timedelta(seconds=SETTLE_GRACE_S)
    async with get_session() as s:
        open_rows = (await s.execute(select(R).where(R.account_id == aid, R.state.in_(OPEN)))).scalars().all()
        held = set((await s.execute(select(R.of_promo_id).where(
            R.account_id == aid, R.of_promo_id.is_not(None)))).scalars().all())
    settled = 0
    for r in open_rows:
        res = reservation_of(r)
        if r.state == "pending":
            # Never flipped to sending: no POST. The pending-only CAS loses to a sender
            # that flips it meanwhile.
            if now - r.created_at > grace:
                settled += await settle(res, Outcome("failed", error_class="not_sent"), only=("pending",))
            continue
        if items is None or (r.state == "sending" and now - (r.sent_at or r.created_at) <= grace):
            continue       # no read, or its sender still owns it
        found = [p for p in items if _candidate(r, p, held, now)]
        if len(found) == 1:
            settled += await settle(res, Outcome("created", item=found[0]))
            continue
        async with get_session() as s:
            await s.execute(update(R).where(R.id == r.id, R.state.in_(OPEN))
                            .values(reconcile_reads=R.reconcile_reads + 1))
        if now - (r.sent_at or r.created_at) >= timedelta(seconds=UNKNOWN_OFF_S):
            settled += await settle(res, Outcome("lost"), only=(r.state,))
    if items is not None:
        await _stamp_listed(aid, items, now)
    return settled


async def _stamp_listed(aid: str, items: Sequence[dict], now: datetime) -> None:
    """listed_at = the first read showing the id live, on the breaker's last N automatic
    creates (older rows no longer count). A finished id with claims went live too (it sold
    out before a read saw it): only a sighting with neither leaves it unlisted."""
    def went_live(p: dict) -> bool:
        return not p.get("is_finished") or (bool(p.get("claims_present"))
                                            and int(p.get("subscriber_count") or 0) > 0)
    live = {p.get("of_promo_id") for p in items if went_live(p)}
    R = PromoCreateReservation
    async with get_session() as s:
        recent = (await s.execute(select(R.id, R.of_promo_id, R.listed_at).where(
            R.account_id == aid, R.state == "created", R.source.in_(AUTO_SOURCES))
            .order_by(R.settled_at.desc()).limit(BREAKER_N))).all()
    seen = [rid for rid, pid, listed in recent if listed is None and pid in live]
    if seen:
        async with get_session() as s:
            await s.execute(update(R).where(R.id.in_(seen), R.listed_at.is_(None)).values(listed_at=now))


async def has_open(account_id: str) -> bool:
    """A create of this Creator is open: no other may start until it settles."""
    R = PromoCreateReservation
    async with get_session() as s:
        return (await s.execute(select(R.id).where(
            R.account_id == str(account_id), R.state.in_(OPEN)).limit(1))).scalar_one_or_none() is not None


async def recent_creates(account_id: str) -> list[PromoCreateReservation]:
    """The Creator's automatic created rows, newest first (the breaker's facts)."""
    R = PromoCreateReservation
    async with get_session() as s:
        return list((await s.execute(select(R).where(
            R.account_id == str(account_id), R.state == "created", R.source.in_(AUTO_SOURCES))
            .order_by(R.settled_at.desc()).limit(BREAKER_N * 3))).scalars())   # room for a takeover


async def replaced_ids(account_id: str, campaign_ids: set[int]) -> set[int]:
    """OF promo ids these campaigns' reservations replaced or made."""
    R = PromoCreateReservation
    async with get_session() as s:
        rows = (await s.execute(select(R.replaced_of_promo_id, R.of_promo_id).where(
            R.account_id == str(account_id), R.campaign_id.in_(campaign_ids)))).all()
    return {int(i) for row in rows for i in row if i is not None}


async def open_row(account_id: str) -> PromoCreateReservation | None:
    """The Creator's open create, if any."""
    R = PromoCreateReservation
    async with get_session() as s:
        return (await s.execute(select(R).where(
            R.account_id == str(account_id), R.state.in_(OPEN)).limit(1))).scalar_one_or_none()


async def clear(row: PromoCreateReservation) -> bool:
    """The operator says this open create never went through ("create anyway"): settle it
    `cleared`, only from the state the operator was shown (a pending row that started
    sending since is not cleared). False when it moved meanwhile."""
    return await settle(reservation_of(row), Outcome("cleared"), only=(row.state,))


async def fence_notices() -> int:
    """At boot: each Kept campaign this box will not re-create (env unset or not its stamp)
    gets one owner notice per env value and a log line the 4 h sweep counts, so a deploy
    that silently stops re-creates is seen. Returns how many campaigns are fenced."""
    here = host_id()
    filed: list[str] = []
    async with get_session() as s:
        kept = (await s.execute(select(PromoCampaign).where(
            PromoCampaign.auto_reactivate.is_(True)))).scalars().all()
        blocked = [c for c in kept if fenced(c.keep_host_id)]
        for c in blocked:
            log.warning("promo_keep_blocked reason=fence account=%s campaign=%s", c.account_id, c.id)
            fix = RETICK_TEXT if fenced(c.keep_host_id) == "retick" else FENCE_TEXT
            filed += await notifications_api.file_for_creator_owners(
                s, c.account_id, lambda nick, c=c, fix=fix: notifications_api.Notice(
                    NOTICE_KIND, f"{nick}: Keep running can't re-create “{c.name}” on this server — {fix}.",
                    account_id=c.account_id, data={"campaign_id": c.id, "reason": "fence"},
                    dedupe=f"promo_keep_fenced:{c.id}:{here}"))
    await notifications_api.push_unread(filed)
    return len(blocked)


async def duplicate_notices() -> int:
    """At boot: one owner notice per Kept campaign the one-Kept migration unticked
    (keep_warning `kept_duplicate`); the dedupe key holds it to once. Returns how many."""
    filed: list[str] = []
    async with get_session() as s:
        rows = (await s.execute(select(PromoCampaign).where(
            PromoCampaign.keep_warning == "kept_duplicate", PromoCampaign.auto_reactivate.is_(False),
            PromoCampaign.keep_warning_at.is_not(None)))).scalars().all()
        for c in rows:
            filed += await notifications_api.file_for_creator_owners(
                s, c.account_id, lambda nick, c=c: notifications_api.Notice(
                    NOTICE_KIND, f"{nick}: Keep running is off for “{c.name}” — "
                    f"{OFF_TEXT['kept_duplicate']}.", account_id=c.account_id,
                    data={"campaign_id": c.id, "reason": "kept_duplicate"},
                    dedupe=f"promo_keep_off:{c.id}:{c.keep_warning_at.isoformat()}"))
    await notifications_api.push_unread(filed)
    return len(rows)


@dataclass(frozen=True)
class Budget:
    """The Create budget's and back-off's facts: automatic reservations' created_at in the
    last 24 h (any state) and the latest not_before."""
    auto_times: tuple[datetime, ...] = ()
    not_before: datetime | None = None


async def _budget_facts(s, account_id: str, now: datetime,
                        exclude_id: int | None = None) -> tuple[tuple[datetime, ...], datetime | None]:
    """Budget's facts in session `s`; `exclude_id`: a reservation left out (`_recheck`'s own)."""
    R = PromoCreateReservation
    mine = (R.account_id == str(account_id), R.source.in_(AUTO_SOURCES),
            *(() if exclude_id is None else (R.id != exclude_id,)))
    times = (await s.execute(select(R.created_at).where(
        *mine, R.created_at > now - timedelta(days=1)))).scalars().all()
    not_before = (await s.execute(select(func.max(R.not_before)).where(*mine))).scalar_one_or_none()
    return tuple(times), not_before


async def budget_state(account_id: str, now: datetime) -> Budget:
    async with get_session() as s:
        return Budget(*await _budget_facts(s, account_id, now))


@dataclass(frozen=True)
class Sent:
    """What `send` came to: the settled outcome (None: refused at the sending CAS, no POST,
    `refused` says why), OF's answer, and the exception, untouched, for the caller."""
    outcome: Outcome | None
    result: Any = None
    error: Exception | None = None
    refused: str | None = None


async def send(res: Reservation, recheck: Mapping[str, Any], client: Callable[[], Any],
               terms: Mapping[str, Any], *, wrap: Callable[[Callable[[], Any]], Any] | None = None) -> Sent:
    """Load the client, flip to sending and POST, in one thread, then settle. The POST may wait
    after the CAS (the signed slot, the warm-up), so the guard runs again inside the transport
    as each attempt's last step before the request leaves (`_dispatch_check` via
    of_client.PRE_DISPATCH; a proxy retry is another attempt: only a refused CONNECT is
    retried, so nothing reached OF yet); its
    refusal is like the CAS's: no POST, `refused` says why. `wrap`: server._proxy for the raw
    route, so its lane and error translation run around the POST. A BaseException (a crash)
    leaves the row open for the reconcile."""
    loop = asyncio.get_running_loop()
    kwargs = {k: v for k, v in terms.items() if k != "mirror"}
    reached, refused, answer_at = False, None, None

    def post():
        nonlocal reached, refused, answer_at
        c = client()
        refused = asyncio.run_coroutine_threadsafe(mark_sending(res, recheck), loop).result()
        if refused:
            return None
        reached = True

        def last_check() -> str | None:
            nonlocal refused, reached
            try:
                refused = asyncio.run_coroutine_threadsafe(_dispatch_check(res, recheck), loop).result()
            except Exception as e:
                # The guard itself failed (a locked DB): nothing left the box, so this is
                # `not_sent` like a failed CAS, never "may have reached OF".
                reached = False
                raise OFDispatchRefused("dispatch_check_failed") from e
            return refused
        token = PRE_DISPATCH.set(last_check)
        try:
            got = c.create_promo(**kwargs)
        finally:
            PRE_DISPATCH.reset(token)
        answer_at = datetime.utcnow()
        return got
    try:
        got = await asyncio.to_thread(wrap, post) if wrap else await asyncio.to_thread(post)
    except Exception as e:
        if refused:
            # The last guard refused it inside the transport and settled it: nothing was sent.
            return Sent(None, error=e, refused=refused)
        log.warning("promo_create failed account=%s reservation=%s", res.account_id, res.id,
                    exc_info=True)
        outcome = outcome_of(error=e) if reached else Outcome("failed", error_class="not_sent")
        await settle(res, outcome)
        return Sent(outcome, error=e)
    if refused:
        return Sent(None, refused=refused)
    outcome = outcome_of(res=got)
    await settle(res, outcome, answer_at=answer_at)
    return Sent(outcome, result=got)

