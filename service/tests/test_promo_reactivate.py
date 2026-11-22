#!/usr/bin/env python3
"""promo_reactivate automation tests — re-arm finished promos. OF is faked.

  case_dry_run_is_default        no dry_run key → plans only, zero OF calls.
  case_dry_run_null_is_still_a_dry_run
                                 a STORED `dry_run: null` too — the one
                                 non-boolean the API keeps, and this kind is
                                 uncatalogued so no seam test covers it.
  case_reactivates_finished      OF says finished → re-created, mirror repointed.
  case_rearm_preserves_a_zero_claim_cap  0 = unlimited, not "unset".
  case_skips_active              still live on OF → left alone.
  case_ignores_unmanaged         auto_reactivate off → never touched.
  case_fails_closed_when_of_down OF unreachable → stands down (no duplicate promo).
  case_respects_cycle_cap        max_reactivations reached → skipped.
  case_skips_without_discount    no saved discount → skipped (OF would reject).
  case_rearm_keeps_both_audiences  "all,expired" goes back to OF as its list.
  case_cap_reached_is_rearmed    claims >= cap is ended even with canClaim true, once
                                 the Kept promo was watched filling from 0.
  case_mn01_inferred_cap_without_history_waits  first seen already full (OF still says
                                 live) → Wait, no create; OF ending it re-creates (#850).
  case_mn01_missing_count_untrusted  a first read with no count never seeds a 0: a later
                                 full count waits.
  case_near_cap_queues_one_recheck  one claim short → ONE re-check in ~90 s,
                                 never two pending, never from a re-check run.
  case_expiring_soon_queues_an_expiry_recheck  expires_at before the next
                                 backstop → a re-check at expires_at + 30 s.
  case_expiry_past_but_of_live_retries_bounded  OF wins over our expires_at:
                                 no create, +60 s re-checks, at most 3.
  case_cooldown_queues_a_recheck_and_never_mints  held by the cooldown → no
                                 create, a re-check just past it (default 2 min).
  case_rearm_sends_finish_days_and_refreshes_expires_at  the bug: finish_days
                                 was dropped on re-create.
  case_dry_run_and_rule_off_queue_no_recheck  dry run never queues one; a rule
                                 switched off drops it.
  case_deleted_campaign_stops_rearming  no mirror row → nothing re-armed.
  case_mn13_racing_rechecks_queue_one  two runs past the same read both want a re-check:
                                 the per-Creator slot (compare-and-set) queues one.
  case_rv_c09_slot_owned_by_its_job  the slot names its owner job: a due one holds it, a
                                 cancelled one frees it at once, a non-owner never clears it.
  case_mn13_takeover_no_second   Keep running moving to another campaign keeps the slot.
  case_mn13_chain_bounded        each re-check run frees the slot and queues at most one;
                                 near_cap never from a re-check, expiry retries ≤ 3, then
                                 nothing pending.
  case_mn05_unparsed_id_unknown_then_adopted  a create answered with no id is unknown (the
                                 campaign keeps its old id, nothing read from the body); the
                                 next read adopts the new promo, no second POST.
  case_mn05_invisible_two_reads_no_second_create  the new promo missing from two reads: the
                                 open row blocks every create until a read adopts it.
  case_mn06_crash_after_post_adopts_no_duplicate  the process dies after the POST: runs wait
                                 out SETTLE_GRACE_S from sent_at, then adopt; no second POST.
  case_mn06_slow_send_past_grace_no_second_post  a run meeting a send still in flight past
                                 SETTLE_GRACE_S waits; one POST in all.
  case_mn02_unparsed_never_listed_turns_off  no id, never listed: lost UNKNOWN_OFF_S after the
                                 send, Keep running off (create_unknown) + one notice.
  case_f6_sold_out_before_any_read_never_trips_breaker  each new promo sells out before a
                                 read sees it live: its sighting with claims counts; 4
                                 cycles, Keep running stays on.
  case_mn02_listed_never_live_stops_after_three  listed but never live: held until
                                 NOT_LISTED_S after each settle, off (breaker) after 3 creates.
  case_owned_earlier_promo_full_never_blocks  the Kept promo ended while an earlier promo of
                                 the same campaign still reads full-but-live: After-end; a
                                 promo Inflowwww never owned in that state still waits.
  case_mn03_429_backs_off_then_turns_off  a 429 records failed + back-off (no POST until it
                                 ends); the second 429 in a row turns Keep running off.
  case_mn03_single_403_backs_off_keeps_on  one 403: back-off only, the next create goes out.
  case_mn03_retry_after_over_6h_honoured  Retry-After 8 h holds past the 6 h doubling cap.
  case_mn03_captcha_turns_off    a captcha body: off (captcha), one notice, no retry.
  case_mn03_dead_session_flags_account  "Wrong user.": the account is flagged, Keep running
                                 stays on, run_once skips the account.
  case_mn11_free_page_no_create  OF's "Access denied" (free page): off (price_free), notice,
                                 no retry.
  case_budget_holds_the_fourth   3 automatic creates in an hour: the 4th waits (budget).
  case_mn10_untick_mid_run_no_post  unticked during the read: the reserve re-read refuses.
  case_mn10_untick_after_reserve_no_post  unticked after the reserve: the sending CAS refuses.
  case_mn10_takeover_mid_run_no_post  Keep running moved to another campaign mid-read.
  case_mn10_manual_create_after_decision_read_no_post  a create reserved during the read
                                 beats this run's (newer_create).
  case_mn07_host_mismatch_or_unset_no_create  stamped by another box, env unset here, or
                                 ticked before the fence (no stamp): no OF read, no create; the
                                 env moving between the read and the reserve refuses (fence).
  case_mn09_free_trial_stops_at_limit  a Free trial with Re-create limit 2: two creates, then
                                 Keep running off (limit_reached) with a notice; no third.
  case_free_trial_no_limit_keeps_running  owner 11-21: a capped Free trial with no Re-create
                                 limit re-creates every time, never turned off.
  case_rv_r01_uncapped_trial_turned_off_before_read  a Kept Free trial with no Claim cap: off
                                 once (limit_needed) + notice, no OF read.
  case_rv_c11_dry_run_never_turns_off  a dry run leaves an aged unknown create and Keep
                                 running as they are.
  case_w30_f27_unauthorized_read_backs_off_toasts  an unclassified OF 401 on the read: not
                                 parked, toasts back off for GATE_STALE_S; a 500 leaves them.

Run: ./venv/bin/python service/tests/test_promo_reactivate.py
"""
from __future__ import annotations

import _harness  # MUST be first
_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import automation_executor as ax  # noqa: E402,F401 — registers plugins
from automation_executor import run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
import automations.promo_reactivate as pr  # noqa: E402
from db.models import (Account, AgencyNotification, AutomationRule, LinkMeta,  # noqa: E402
                       PromoCampaign, PromoCreateReservation, PromoKeepState, ScheduledJob,
                       User, UserAccount)
import account_health  # noqa: E402
import promo_create_guard  # noqa: E402
from of_client import OFAPIError  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

# This box's Host fence id; seeded campaigns carry it as their tick stamp.
BOX = "test-box"
os.environ[promo_create_guard.HOST_ENV] = BOX


class FakeOF:
    """OF promo endpoints, live-accurate: {items:[...]} on read, LIST on create.

    Create modes: `create_shape` (what the POST answers, default OF's LIST), `raise_after_post`
    (raised once the promo exists), `slow_send` (an Event the POST waits on before landing),
    `lists_new` (False: a made promo never shows in a read), `lists_new_after` (reads it is
    missing from first), `new_live` (False: listed, but never live)."""
    create_shape = None
    raise_after_post: BaseException | None = None
    slow_send: threading.Event | None = None
    lists_new = True
    lists_new_after = 0
    new_live = True
    fail_with: Exception | None = None      # the POST raises this (OF refused), nothing made
    on_list = None                          # called on each read: the operator acts mid-read

    def __init__(self):
        self._id = 80_000_000
        self.store: dict[int, dict] = {}
        self.created: list[dict] = []
        self.types: list = []
        self.reads = 0
        self._shown_after: dict[int, int | None] = {}

    def _item(self, pid, *, counts, days, message, finished, claims=0, finished_at=None, created_at=None):
        return {"id": pid, "message": message, "price": 3, "type": "all",
                "subscribeCounts": counts, "subscribeDays": days, "createdAt": created_at,
                "claimsCount": claims, "isFinished": finished, "finishedAt": finished_at}

    def seed(self, pid, *, finished, counts=10, days=30, message="", claims=0):
        """claims=None: OF sent no count (claims_missing)."""
        self.store[pid] = self._item(pid, counts=counts, days=days,
                                     message=message, finished=finished, claims=claims)
        if claims is None:
            del self.store[pid]["claimsCount"]

    def promotions(self, *, offset=0, limit=100):
        # OF pages this endpoint and its hasMore is ALWAYS true, so the fake
        # mimics both: callers must stop on a short page, not on hasMore.
        if offset == 0:
            self.reads += 1
            if self.on_list is not None:
                self.on_list()
        shown = [p for pid, p in self.store.items()
                 if pid not in self._shown_after
                 or (self._shown_after[pid] is not None and self.reads > self._shown_after[pid])]
        return {"hasMore": True, "items": shown[offset:offset + limit]}

    finished_at = None   # what OF echoes as finishedAt on create (null for most)

    def create_promo(self, *, discount, subscribe_counts, subscribe_days=30, message="", type="all",
                     **kw):
        if self.slow_send is not None:
            assert self.slow_send.wait(10), "slow_send never released"
        if self.fail_with is not None:
            self.created.append({"failed": repr(self.fail_with)})
            raise self.fail_with
        self.types.append(type)
        self._id += 1
        item = self._item(self._id, counts=subscribe_counts, days=subscribe_days,
                          message=message, finished=not self.new_live, finished_at=self.finished_at,
                          created_at=datetime.utcnow().isoformat() + "+00:00")
        self.store[self._id] = item
        self._shown_after[self._id] = (self.reads + self.lists_new_after) if self.lists_new else None
        self.created.append({"discount": discount, "counts": subscribe_counts,
                             "days": subscribe_days, "message": message, **kw})
        if self.raise_after_post is not None:
            raise self.raise_after_post
        return [item] if self.create_shape is None else self.create_shape   # LIST response


def _use_fake() -> FakeOF:
    f = FakeOF()
    ax._make_client = lambda account_id: f  # type: ignore[attr-defined]
    return f


async def _seed_campaign(aid, *, of_id, auto=True, discount=50, count=0, message="Promo",
                         subscribe_counts=10, subscribe_days=30, promo_type="all",
                         finish_days=None, expires_at=None, last_reactivated_at=None,
                         host=BOX, recreates_left=None, preempt=True):
    async with get_session() as s:
        if not await s.get(Account, aid):
            s.add(Account(id=aid))
            # A live rule: an automatic create needs one enabled and not dry run (c6).
            s.add(AutomationRule(account_id=aid, name="keep-seed", kind="promo_reactivate",
                                 is_enabled=True, trigger_json=json.dumps({"every_seconds": 3600}),
                                 steps_json=json.dumps({"dry_run": False})))
        row = PromoCampaign(
            account_id=aid, of_promo_id=of_id, name="Summer", discount_percent=discount,
            price_cents=0, subscribe_counts=subscribe_counts,
            subscribe_days=subscribe_days, message=message,
            promo_type=promo_type, status="active", subscriber_count=0,
            auto_reactivate=auto, reactivate_count=count, created_at=datetime.utcnow(),
            finish_days=finish_days, expires_at=expires_at, last_reactivated_at=last_reactivated_at,
            keep_host_id=host, recreates_left=recreates_left, preempt=preempt,
        )
        s.add(row)
        await s.flush()
        return row.id


async def _campaign(cid):
    async with get_session() as s:
        return await s.get(PromoCampaign, cid)


async def _rechecks(aid) -> list[ScheduledJob]:
    async with get_session() as s:
        return list((await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == aid, ScheduledJob.kind == "promo_reactivate",
            ScheduledJob.status == "pending").order_by(ScheduledJob.id))).scalars())


def _near(a: datetime, b: datetime, slack_s: float = 5) -> bool:
    return abs((a - b).total_seconds()) <= slack_s


GO = {"dry_run": False}


async def _rule(aid, *, every=3600, enabled=True) -> int:
    async with get_session() as s:
        rule = AutomationRule(account_id=aid, name="keep", kind="promo_reactivate",
                              is_enabled=enabled, trigger_json=json.dumps({"every_seconds": every}),
                              steps_json=json.dumps(GO))
        s.add(rule)
        await s.flush()
        return rule.id


async def _run_rule_job(aid, rid) -> dict:
    """The rule's own job, claimed by run_once (so the run is bound to the rule)."""
    async with get_session() as s:
        s.add(ScheduledJob(account_id=aid, kind="promo_reactivate", payload_json=json.dumps(GO),
                           run_at=datetime.utcnow() - timedelta(seconds=1), status="pending",
                           rule_id=rid))
    return await run_once(aid, "promo_reactivate")


async def case_dry_run_is_default():
    aid = "pr_dry"
    await _seed_campaign(aid, of_id=111)
    f = _use_fake(); f.seed(111, finished=True)
    res = await run_once(aid, "promo_reactivate", payload={})
    assert res.get("dry_run") is True, res
    assert res["due"] == 1 and res["reactivated"] == 0, res
    assert f.created == [], "dry run must not create on OF"


async def case_dry_run_null_is_still_a_dry_run():
    """R3-9. `dry_run: null` is the ONE non-boolean the rules API stores — it
    skips a None value instead of rejecting it — and the old read
    `bool(payload.get("dry_run", True))` resolved it to FALSE, because `.get`
    found the key and the default never ran. That is a real re-arm on OF under a
    comment that said "# default SAFE".

    This kind has no `_CATALOG` entry, so
    `test_automation_rules_api.case_every_catalogued_bool_honours_its_default`
    will never walk it — the class check can only speak for knobs the catalog
    declares. This case is the whole coverage for this one, which is why it
    exists rather than being folded into the case above."""
    aid = "pr_dry_null"
    await _seed_campaign(aid, of_id=113)
    f = _use_fake(); f.seed(113, finished=True)
    res = await run_once(aid, "promo_reactivate", payload={"dry_run": None})
    assert res.get("dry_run") is True, res
    assert res["due"] == 1 and res["reactivated"] == 0, res
    assert f.created == [], "a null dry_run must not create on OF"


async def case_reactivates_finished():
    aid = "pr_go"
    cid = await _seed_campaign(aid, of_id=222, discount=40)
    f = _use_fake(); f.seed(222, finished=True)
    res = await run_once(aid, "promo_reactivate", payload={"dry_run": False})
    assert res["reactivated"] == 1, res
    assert len(f.created) == 1 and f.created[0]["discount"] == 40, f.created
    row = await _campaign(cid)
    assert row.of_promo_id not in (None, 222), "mirror must repoint at the NEW promo"
    assert row.reactivate_count == 1 and row.status == "active", (row.reactivate_count, row.status)
    assert row.last_reactivated_at is not None
    # The finished promo stays under the campaign, so its claimers' spend still
    # counts toward the campaign's Revenue (link_metrics).
    async with get_session() as s:
        meta = (await s.execute(select(LinkMeta).where(
            LinkMeta.account_id == aid, LinkMeta.kind == "promo", LinkMeta.of_id == 222))).scalar_one()
    assert meta.campaign_id == cid, meta.campaign_id


async def case_rearm_preserves_a_zero_claim_cap():
    """0 is a VALUE on both count knobs, not "unset".

    `subscribe_counts=0` means UNLIMITED claims — promotions_api documents it
    and deliberately dropped a max(1,...) floor so the UI could reach it.
    `subscribe_days=0` is what OF itself stores for a percent discount. An
    `or`-style default reads both as missing and silently re-arms the campaign
    as "1 claim / 30 days": the operator's always-on offer becomes a one-shot
    that finishes the moment somebody takes it.
    """
    aid = "pr_zero"
    await _seed_campaign(aid, of_id=333, discount=50,
                         subscribe_counts=0, subscribe_days=0)
    f = _use_fake(); f.seed(333, finished=True)
    res = await run_once(aid, "promo_reactivate", payload={"dry_run": False})
    assert res["reactivated"] == 1, res
    assert f.created[0]["counts"] == 0, (
        f"unlimited claim cap became {f.created[0]['counts']!r} — the re-armed "
        f"promo now finishes after that many claims")
    assert f.created[0]["days"] == 0, (
        f"subscribe_days 0 became {f.created[0]['days']!r}")


async def case_skips_active():
    """A live promo is never re-created. OF runs one promo at a time, so ANY
    live promo means a discount is already on offer — stand down."""
    aid = "pr_active"
    await _seed_campaign(aid, of_id=333)
    f = _use_fake(); f.seed(333, finished=False)   # still live
    res = await run_once(aid, "promo_reactivate", payload={"dry_run": False})
    assert res["reactivated"] == 0, res
    assert res["skipped"] == "promo_already_live", res
    assert res["live_of_promo_id"] == 333, res
    assert f.created == []


async def case_two_armed_campaigns_do_not_ping_pong():
    """The churn bug: OF only holds one live promo, so creating one FINISHES the
    other. With two armed campaigns each tick re-created whichever was finished,
    which finished the other — a real promo minted on the creator's public
    profile every tick, forever. uq_promo_keep_one (c4) makes a second Kept campaign
    per Creator impossible; the other campaign's live promo still stands this one down."""
    aid = "pr_pingpong"
    await _seed_campaign(aid, of_id=901, message="A")
    try:
        await _seed_campaign(aid, of_id=902, message="B")
        raise AssertionError("a second Kept campaign for one Creator must be refused")
    except IntegrityError:
        pass
    await _seed_campaign(aid, of_id=902, message="B", auto=False)
    f = _use_fake()
    f.seed(901, finished=True)          # A was superseded by B
    f.seed(902, finished=False)         # B is the live one

    res = await run_once(aid, "promo_reactivate", payload={"dry_run": False, "cooldown_minutes": 0})
    assert res["reactivated"] == 0, res
    assert res["skipped"] == "promo_already_live", res
    assert f.created == [], "must not re-create A while B's discount is live"


async def case_spent_promo_with_stale_isfinished_is_rearmed():
    """OF does not reliably flip isFinished on a spent promo — Ava has 9 with
    isFinished=False and canClaim=False, the oldest dead since 2025-12. Trusting
    isFinished alone would (a) show them as live in the UI and (b) make the
    automation stand down forever on an account with no offer running."""
    aid = "pr_stale"
    cid = await _seed_campaign(aid, of_id=808, discount=25)
    f = _use_fake()
    f.seed(808, finished=False)
    f.store[808]["canClaim"] = False          # spent, but OF never flipped isFinished

    res = await run_once(aid, "promo_reactivate", payload={"dry_run": False})
    assert res.get("skipped") != "promo_already_live", f"a spent promo is not an offer: {res}"
    assert res["reactivated"] == 1, res
    row = await _campaign(cid)
    assert row.of_promo_id not in (None, 808), "mirror must repoint at the new promo"


async def case_finds_promo_beyond_page_one():
    """/promotions is paged (10 by default) and its hasMore is always true. When
    we read only page 1, an older-but-LIVE promo looked absent, i.e. "expired",
    i.e. got re-created — minting a duplicate discount."""
    aid = "pr_paged"
    await _seed_campaign(aid, of_id=999)
    f = _use_fake()
    # 250 newer promos bury ours well past the first page.
    for pid in range(1000, 1250):
        f.seed(pid, finished=True)
    f.seed(999, finished=False)        # ours is LIVE, just old
    assert list(f.store).index(999) > 100, "fixture must bury it past page 1"

    res = await run_once(aid, "promo_reactivate", payload={"dry_run": False})
    assert res["reactivated"] == 0, res
    assert f.created == [], "a live promo on a later page must not be re-created"


async def case_ignores_unmanaged():
    aid = "pr_off"
    await _seed_campaign(aid, of_id=444, auto=False)
    f = _use_fake(); f.seed(444, finished=True)
    res = await run_once(aid, "promo_reactivate", payload={"dry_run": False})
    assert res["managed"] == 0 and res["reactivated"] == 0, res
    assert f.created == []


async def case_fails_closed_when_of_down():
    aid = "pr_down"
    await _seed_campaign(aid, of_id=555)

    class Boom:
        def promotions(self, *, offset=0, limit=100):
            raise RuntimeError("no session")
        def create_promo(self, **kw):
            raise AssertionError("must NOT create when OF is unreachable")
    ax._make_client = lambda account_id: Boom()  # type: ignore[attr-defined]
    res = await run_once(aid, "promo_reactivate", payload={"dry_run": False})
    assert res["skipped"] == "of_unreachable" and res["reactivated"] == 0, res


async def case_respects_cycle_cap():
    aid = "pr_cap"
    await _seed_campaign(aid, of_id=666, count=3)
    f = _use_fake(); f.seed(666, finished=True)
    res = await run_once(aid, "promo_reactivate",
                         payload={"dry_run": False, "max_reactivations": 3})
    assert res["reactivated"] == 0 and res["skipped_cap"] == 1, res
    assert f.created == []


async def case_skips_without_discount():
    aid = "pr_nodisc"
    await _seed_campaign(aid, of_id=777, discount=0)
    f = _use_fake(); f.seed(777, finished=True)
    res = await run_once(aid, "promo_reactivate", payload={"dry_run": False})
    assert res["reactivated"] == 0 and res["skipped_no_discount"] == 1, res
    assert f.created == []


async def case_fails_closed_without_of_id():
    """A campaign whose of_promo_id was never captured can't be looked up on OF,
    so its promo may well be LIVE. Re-creating it blind would mint a duplicate
    promo every cycle — and since the new id may not be captured either, it
    would never converge. Must skip, not re-create."""
    aid = "pr_noid"
    await _seed_campaign(aid, of_id=None)
    f = _use_fake()          # OF reachable, but this campaign isn't in it
    res = await run_once(aid, "promo_reactivate", payload={"dry_run": False})
    assert res["due"] == 0, res
    assert res["skipped_unverifiable"] == 1, res
    assert res["reactivated"] == 0, res
    assert f.created == [], "must not create a promo it cannot verify"


async def case_rearm_keeps_both_audiences():
    """A campaign for new AND expired subscribers is stored as "all,expired";
    the re-arm must send OF's list, not that joined string (OF would 400 it),
    and a single audience stays the bare string."""
    aid = "pr_both"
    await _seed_campaign(aid, of_id=777, promo_type="all,expired")
    f = _use_fake(); f.seed(777, finished=True)
    res = await run_once(aid, "promo_reactivate", payload={"dry_run": False})
    assert res["reactivated"] == 1, res
    assert f.types == [["all", "expired"]], f.types

    aid = "pr_expired_only"
    await _seed_campaign(aid, of_id=778, promo_type="expired")
    f = _use_fake(); f.seed(778, finished=True)
    res = await run_once(aid, "promo_reactivate", payload={"dry_run": False})
    assert res["reactivated"] == 1, res
    assert f.types == ["expired"], f.types


async def case_cap_reached_is_rearmed():
    """OF can lag flipping canClaim on a filled cap: claims >= cap is ended
    (of_promos.normalise_of_promo), so the next promo goes up now — given the Kept
    promo was first read at 0 and its Claims never went down (the memo survives runs)."""
    aid = "pr_capfull"
    await _seed_campaign(aid, of_id=1201, subscribe_counts=10)
    f = _use_fake(); f.seed(1201, finished=False, counts=10, claims=0)
    f.store[1201]["canClaim"] = True
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["skipped"] == "promo_already_live", res
    f.store[1201]["claimsCount"] = 10
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["reactivated"] == 1 and len(f.created) == 1, res
    # ... and an unlimited cap (0) is never "filled"
    aid = "pr_capzero"
    await _seed_campaign(aid, of_id=1202, subscribe_counts=0)
    f = _use_fake(); f.seed(1202, finished=False, counts=0, claims=500)
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["skipped"] == "promo_already_live" and f.created == [], res


async def case_mn01_inferred_cap_without_history_waits():
    aid = "pr_mn01_full"
    cid = await _seed_campaign(aid, of_id=1211, subscribe_counts=10)
    f = _use_fake(); f.seed(1211, finished=False, counts=10, claims=10)
    for _ in range(2):   # the backstop sees the same: still no history, still no create
        res = await run_once(aid, "promo_reactivate", payload=GO)
        assert res["skipped"] == "inferred_cap_untrusted" and f.created == [], res
        assert res["live_of_promo_id"] == 1211, res
    # Claims that went down untrust the id even if a later read is clean.
    aid = "pr_mn01_down"
    await _seed_campaign(aid, of_id=1213, subscribe_counts=10)
    g = _use_fake(); g.seed(1213, finished=False, counts=10, claims=0)
    await run_once(aid, "promo_reactivate", payload=GO)
    g.store[1213]["claimsCount"] = 6
    await run_once(aid, "promo_reactivate", payload=GO)
    g.store[1213]["claimsCount"] = 4
    await run_once(aid, "promo_reactivate", payload=GO)
    g.store[1213]["claimsCount"] = 10
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["skipped"] == "inferred_cap_untrusted" and g.created == [], res
    # OF itself ending it needs no history: re-created as #850.
    ax._make_client = lambda account_id: f  # type: ignore[attr-defined]
    f.store[1211]["isFinished"] = True
    res = await run_once("pr_mn01_full", "promo_reactivate", payload=GO)
    assert res["reactivated"] == 1 and len(f.created) == 1, res
    assert (await _campaign(cid)).of_promo_id not in (None, 1211)


async def case_mn01_missing_count_untrusted():
    aid = "pr_mn01_missing"
    await _seed_campaign(aid, of_id=1212, subscribe_counts=10)
    f = _use_fake(); f.seed(1212, finished=False, counts=10, claims=None)
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["skipped"] == "promo_already_live", res
    f.store[1212]["claimsCount"] = 10
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["skipped"] == "inferred_cap_untrusted" and f.created == [], res


async def case_near_cap_queues_one_recheck():
    aid = "pr_nearcap"
    await _seed_campaign(aid, of_id=1301, subscribe_counts=10)
    f = _use_fake(); f.seed(1301, finished=False, counts=10, claims=9)
    t0 = datetime.utcnow()
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["skipped"] == "promo_already_live" and f.created == [], res
    assert res["recheck"]["reason"] == "near_cap", res
    jobs = await _rechecks(aid)
    assert len(jobs) == 1 and _near(jobs[0].run_at, t0 + timedelta(seconds=90)), jobs
    body = json.loads(jobs[0].payload_json)
    assert body["_recheck"] == "near_cap" and body["dry_run"] is False, body
    # never stacks: a second run while it is pending queues nothing
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert "recheck" not in res and len(await _rechecks(aid)) == 1, res
    # a re-check run never queues another near_cap
    async with get_session() as s:
        (await s.get(ScheduledJob, jobs[0].id)).status = "done"
    res = await run_once(aid, "promo_reactivate", payload={**GO, "_recheck": "near_cap"})
    assert "recheck" not in res and await _rechecks(aid) == [], res
    # two short is not near the cap
    aid = "pr_nearcap2"
    await _seed_campaign(aid, of_id=1302, subscribe_counts=10)
    f = _use_fake(); f.seed(1302, finished=False, counts=10, claims=8)
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert "recheck" not in res and await _rechecks(aid) == [], res


async def case_expiring_soon_queues_an_expiry_recheck():
    aid = "pr_expsoon"
    exp = datetime.utcnow() + timedelta(minutes=10)
    await _seed_campaign(aid, of_id=1401, expires_at=exp, preempt=False)   # After-end only (A)
    f = _use_fake(); f.seed(1401, finished=False)
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["recheck"]["reason"] == "expiry" and f.created == [], res
    jobs = await _rechecks(aid)
    assert len(jobs) == 1 and _near(jobs[0].run_at, exp + timedelta(seconds=30), 1), jobs
    # past the next backstop (hourly with no rule): nothing yet, the backstop has it
    aid = "pr_explater"
    await _seed_campaign(aid, of_id=1402, expires_at=datetime.utcnow() + timedelta(hours=2),
                         preempt=False)
    f = _use_fake(); f.seed(1402, finished=False)
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert "recheck" not in res and await _rechecks(aid) == [], res
    # the rule's own cadence is the horizon: a 3-hour rule reaches it
    rid = await _rule(aid, every=3 * 3600)
    res = await _run_rule_job(aid, rid)
    assert res["recheck"]["reason"] == "expiry", res
    jobs = await _rechecks(aid)
    assert len(jobs) == 1 and jobs[0].rule_id == rid, jobs
    assert json.loads(jobs[0].payload_json).get("_followup") is True, jobs[0].payload_json


async def case_expiry_past_but_of_live_retries_bounded():
    """Our expires_at is often a guess (created + finish_days). OF saying the
    promo is still on offer wins: no create, +60 s, at most 3 retries."""
    aid = "pr_expwrong"
    await _seed_campaign(aid, of_id=1501, expires_at=datetime.utcnow() - timedelta(seconds=40))
    f = _use_fake(); f.seed(1501, finished=False)
    retries = []
    for done in range(4):
        t0 = datetime.utcnow()
        res = await run_once(aid, "promo_reactivate",
                             payload={**GO, "_recheck": "expiry", "_expiry_retries": done})
        assert res["skipped"] == "promo_already_live", res
        jobs = await _rechecks(aid)
        if jobs:
            assert len(jobs) == 1 and _near(jobs[0].run_at, t0 + timedelta(seconds=60)), jobs
            retries.append(json.loads(jobs[0].payload_json)["_expiry_retries"])
            async with get_session() as s:
                (await s.get(ScheduledJob, jobs[0].id)).status = "done"
    assert retries == [1, 2, 3], retries
    assert f.created == [], "re-created while OF said the promo was on offer"
    # a backstop run past the guess starts no retry chain
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert "recheck" not in res and await _rechecks(aid) == [], res


async def case_cooldown_queues_a_recheck_and_never_mints():
    aid = "pr_cool"
    last = datetime.utcnow() - timedelta(seconds=60)
    await _seed_campaign(aid, of_id=1601, last_reactivated_at=last)
    f = _use_fake(); f.seed(1601, finished=True)
    res = await run_once(aid, "promo_reactivate", payload=GO)   # default cooldown: 2 min
    assert res["skipped_cooldown"] == 1 and res["reactivated"] == 0 and f.created == [], res
    jobs = await _rechecks(aid)
    want = last + timedelta(minutes=2, seconds=5)
    assert len(jobs) == 1 and _near(jobs[0].run_at, want, 1), (jobs, want)
    assert json.loads(jobs[0].payload_json)["_recheck"] == "cooldown"
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert "recheck" not in res and len(await _rechecks(aid)) == 1, res
    # past the cooldown it re-arms
    async with get_session() as s:
        (await s.get(ScheduledJob, jobs[0].id)).status = "done"
    res = await run_once(aid, "promo_reactivate",
                         payload={**GO, "_recheck": "cooldown", "cooldown_minutes": 1})
    assert res["reactivated"] == 1 and len(f.created) == 1, res


async def case_rearm_sends_finish_days_and_refreshes_expires_at():
    aid = "pr_finish"
    cid = await _seed_campaign(aid, of_id=1701, finish_days=7,
                               expires_at=datetime.utcnow() - timedelta(days=1))
    f = _use_fake(); f.seed(1701, finished=True)
    t0 = datetime.utcnow()
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["reactivated"] == 1, res
    assert f.created[0]["finish_days"] == 7, f.created
    row = await _campaign(cid)
    assert _near(row.expires_at, t0 + timedelta(days=7)), row.expires_at
    # OF's own future finishedAt wins over the guess
    aid = "pr_finish_of"
    cid = await _seed_campaign(aid, of_id=1702, finish_days=7)
    f = _use_fake(); f.seed(1702, finished=True)
    of_end = (datetime.utcnow() + timedelta(days=6, hours=23)).replace(microsecond=0)
    f.finished_at = of_end.isoformat() + "+00:00"
    await run_once(aid, "promo_reactivate", payload=GO)
    assert (await _campaign(cid)).expires_at == of_end
    # never sent → not sent back, and no expiry known
    aid = "pr_finish_none"
    cid = await _seed_campaign(aid, of_id=1703)
    f = _use_fake(); f.seed(1703, finished=True)
    await run_once(aid, "promo_reactivate", payload=GO)
    assert "finish_days" not in f.created[0] and (await _campaign(cid)).expires_at is None, f.created


async def case_dry_run_and_rule_off_queue_no_recheck():
    aid = "pr_nore_dry"
    await _seed_campaign(aid, of_id=1801, subscribe_counts=10)
    f = _use_fake(); f.seed(1801, finished=False, counts=10, claims=9)
    res = await run_once(aid, "promo_reactivate", payload={})
    assert "recheck" not in res and await _rechecks(aid) == [], res
    aid = "pr_nore_off"
    await _seed_campaign(aid, of_id=1802, subscribe_counts=10)
    f = _use_fake(); f.seed(1802, finished=False, counts=10, claims=9)
    rid = await _rule(aid)
    orig = pr.of_pacing.walk

    async def walk_then_switch_off(*a, **kw):   # the operator unticks mid-run
        async with get_session() as s:
            (await s.get(AutomationRule, rid)).is_enabled = False
        return await orig(*a, **kw)
    pr.of_pacing.walk = walk_then_switch_off
    try:
        res = await _run_rule_job(aid, rid)
    finally:
        pr.of_pacing.walk = orig
    assert res["skipped"] == "promo_already_live", res
    assert "recheck" not in res and await _rechecks(aid) == [], res


async def case_deleted_campaign_stops_rearming():
    aid = "pr_deleted"
    cid = await _seed_campaign(aid, of_id=1901)
    f = _use_fake(); f.seed(1901, finished=True)
    async with get_session() as s:
        await s.delete(await s.get(PromoCampaign, cid))
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["managed"] == 0 and f.created == [], res



async def _slot(aid):
    async with get_session() as s:
        st = await s.get(PromoKeepState, aid)
        return None if st is None else st.recheck_at


async def case_mn13_racing_rechecks_queue_one():
    aid = "pr_mn13_race"
    await _seed_campaign(aid, of_id=2001, subscribe_counts=10)
    f = _use_fake(); f.seed(2001, finished=False, counts=10, claims=9)
    orig = pr.of_pacing.walk
    barrier = asyncio.Barrier(2)

    async def walk_together(*a, **kw):   # both runs decide on the same read
        out = await orig(*a, **kw)
        await barrier.wait()
        return out
    pr.of_pacing.walk = walk_together
    try:   # run_once's per-(account, kind) lock serialises one process; race the plugin
        res = await asyncio.gather(pr.run(aid, GO, run_id=0), pr.run(aid, GO, run_id=0))
    finally:
        pr.of_pacing.walk = orig
    assert all(r["skipped"] == "promo_already_live" for r in res), res
    assert sum("recheck" in r for r in res) == 1, res
    jobs = await _rechecks(aid)
    assert len(jobs) == 1 and await _slot(aid) == jobs[0].run_at, jobs


async def case_rv_c09_slot_owned_by_its_job():
    """c9: the slot names its owner job. A due owner not yet claimed still holds it; a
    cancelled owner frees it at once; an old re-check job that is not the owner never
    clears the replacement's slot."""
    aid = "pr_c09_owner"
    await _seed_campaign(aid, of_id=2002, subscribe_counts=10)
    f = _use_fake(); f.seed(2002, finished=False, counts=10, claims=9)
    await run_once(aid, "promo_reactivate", payload=GO)
    [job] = await _rechecks(aid)
    due = datetime.utcnow() - timedelta(seconds=30)   # due, the worker not there yet
    async with get_session() as s:
        (await s.get(ScheduledJob, job.id)).run_at = due
        (await s.get(PromoKeepState, aid)).recheck_at = due
        assert (await s.get(PromoKeepState, aid)).recheck_job_id == job.id
    res = await run_once(aid, "promo_reactivate", payload=GO)   # e.g. a toast poke
    assert "recheck" not in res and len(await _rechecks(aid)) == 1, res
    async with get_session() as s:                      # owner cancelled: free now, no wait
        (await s.get(ScheduledJob, job.id)).status = "cancelled"
    res = await run_once(aid, "promo_reactivate", payload=GO)
    [repl] = await _rechecks(aid)
    assert res["recheck"]["reason"] == "near_cap" and repl.id != job.id, res
    async with get_session() as s:                      # an older re-check job, not the owner
        s.add(ScheduledJob(account_id=aid, kind="promo_reactivate", status="pending",
                           payload_json=json.dumps({**GO, pr.RECHECK: "expiry"}),
                           run_at=datetime.utcnow() - timedelta(seconds=5)))
    await run_once(aid, "promo_reactivate")             # claims the old job: a Re-check run
    async with get_session() as s:
        st = await s.get(PromoKeepState, aid)
        assert (st.recheck_job_id, st.recheck_at) == (repl.id, repl.run_at), (st.recheck_job_id,
                                                                              st.recheck_at)


async def case_mn13_takeover_no_second():
    aid = "pr_mn13_take"
    old = await _seed_campaign(aid, of_id=2003, subscribe_counts=10)
    f = _use_fake(); f.seed(2003, finished=False, counts=10, claims=9)
    await run_once(aid, "promo_reactivate", payload=GO)
    [job] = await _rechecks(aid)
    slot = await _slot(aid)
    # Create promotion with Keep running takes it from the old campaign (a new live promo).
    f.store[2003]["isFinished"] = True
    f.seed(2004, finished=False, counts=10, claims=9)
    async with get_session() as s:
        (await s.get(PromoCampaign, old)).auto_reactivate = False
    await _seed_campaign(aid, of_id=2004, subscribe_counts=10)
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["live_of_promo_id"] == 2004 and "recheck" not in res, res
    assert [j.id for j in await _rechecks(aid)] == [job.id] and await _slot(aid) == slot


async def case_mn13_chain_bounded():
    aid = "pr_mn13_chain"
    cid = await _seed_campaign(aid, of_id=2005, subscribe_counts=10, preempt=False,   # A's chain
                               expires_at=datetime.utcnow() + timedelta(minutes=10))
    f = _use_fake(); f.seed(2005, finished=False, counts=10, claims=9)
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["recheck"]["reason"] == "near_cap", res   # the earliest of near_cap / expiry
    reasons = ["near_cap"]
    for step in range(10):
        pending = await _rechecks(aid)
        assert len(pending) <= 1, pending
        if not pending:
            break
        async with get_session() as s:
            (await s.get(ScheduledJob, pending[0].id)).run_at = datetime.utcnow() - timedelta(seconds=1)
            if step == 1:   # the expiry re-check fires past our expires_at; OF still says live
                (await s.get(PromoCampaign, cid)).expires_at = datetime.utcnow() - timedelta(seconds=40)
        res = await run_once(aid, "promo_reactivate")    # claims that job: a Re-check run
        assert res["skipped"] == "promo_already_live" and f.created == [], res
        if "recheck" in res:
            reasons.append((res["recheck"]["reason"], res["recheck"]["retries"]))
    assert reasons == ["near_cap", ("expiry", 0), ("expiry", 1), ("expiry", 2), ("expiry", 3)], reasons
    assert await _rechecks(aid) == [] and await _slot(aid) is None


class _Crash(BaseException):
    """The process dying mid-run: nothing below the POST runs (not an Exception, so no
    handler in the run catches it)."""


async def _owner(aid) -> None:
    async with get_session() as s:
        s.add(User(id=f"u_{aid}", username=f"owner_{aid}", password="pw"))
        s.add(UserAccount(user_id=f"u_{aid}", account_id=aid))


async def _reservations(aid) -> list[PromoCreateReservation]:
    async with get_session() as s:
        return list((await s.execute(select(PromoCreateReservation).where(
            PromoCreateReservation.account_id == aid).order_by(PromoCreateReservation.id))).scalars())


async def _keep_notices(aid) -> list[AgencyNotification]:
    async with get_session() as s:
        return list((await s.execute(select(AgencyNotification).where(
            AgencyNotification.account_id == aid,
            AgencyNotification.kind == "promo_keep_running"))).scalars())


async def _age_all(aid, seconds) -> None:
    """Move the Creator's create history `seconds` into the past (reservation clocks and the
    campaigns' last re-arm), as if that much time passed."""
    back = timedelta(seconds=seconds)
    async with get_session() as s:
        for r in await s.execute(select(PromoCreateReservation).where(
                PromoCreateReservation.account_id == aid)):
            r = r[0]
            for col in ("created_at", "sent_at", "settled_at", "listed_at", "not_before"):
                if getattr(r, col) is not None:
                    setattr(r, col, getattr(r, col) - back)
        for c in await s.execute(select(PromoCampaign).where(PromoCampaign.account_id == aid)):
            c = c[0]
            if c.last_reactivated_at is not None:
                c.last_reactivated_at -= back


async def case_mn05_unparsed_id_unknown_then_adopted():
    aid = "pr_mn05_unparsed"
    cid = await _seed_campaign(aid, of_id=3001)
    f = _use_fake(); f.seed(3001, finished=True)
    f.create_shape = {"success": True}               # 2xx, no id
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert (res["reactivated"], res["create"]) == (0, "unknown"), res
    assert (await _campaign(cid)).of_promo_id == 3001, "an unparsed id is never read as an id"
    assert [r.state for r in await _reservations(aid)] == ["unknown"]
    res = await run_once(aid, "promo_reactivate", payload=GO)
    new_id = max(f.store)
    assert res["skipped"] == "promo_already_live" and res["live_of_promo_id"] == new_id, res
    assert len(f.created) == 1, f.created
    row = await _campaign(cid)
    assert (row.of_promo_id, row.reactivate_count) == (new_id, 1), (row.of_promo_id, row.reactivate_count)
    assert [(r.state, r.of_promo_id) for r in await _reservations(aid)] == [("created", new_id)]


async def case_mn05_invisible_two_reads_no_second_create():
    aid = "pr_mn05_invisible"
    cid = await _seed_campaign(aid, of_id=3101)
    f = _use_fake(); f.seed(3101, finished=True)
    f.create_shape = {"success": True}
    f.lists_new_after = 2
    await run_once(aid, "promo_reactivate", payload=GO)
    for _ in range(2):
        res = await run_once(aid, "promo_reactivate", payload=GO)
        assert res["skipped"] == "create_open", res
    assert len(f.created) == 1, f.created
    (row,) = await _reservations(aid)
    assert (row.state, row.reconcile_reads) == ("unknown", 2), (row.state, row.reconcile_reads)
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["skipped"] == "promo_already_live", res
    assert len(f.created) == 1 and (await _campaign(cid)).of_promo_id == max(f.store)


async def case_mn06_crash_after_post_adopts_no_duplicate():
    aid = "pr_mn06_crash"
    cid = await _seed_campaign(aid, of_id=3201)
    f = _use_fake(); f.seed(3201, finished=True)
    f.raise_after_post = _Crash()
    try:
        await pr.run(aid, GO, run_id=0)
        raise AssertionError("the crash must surface")
    except _Crash:
        pass
    assert [r.state for r in await _reservations(aid)] == ["sending"]
    f.raise_after_post = None
    # Inside SETTLE_GRACE_S of sent_at the sender may still be alive: hands off (c2).
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["skipped"] == "create_open" and len(f.created) == 1, res
    await _age_all(aid, promo_create_guard.SETTLE_GRACE_S + 1)
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["skipped"] == "promo_already_live", res
    assert len(f.created) == 1, f.created
    assert (await _campaign(cid)).of_promo_id == max(f.store)


async def case_mn06_slow_send_past_grace_no_second_post():
    aid = "pr_mn06_slow"
    cid = await _seed_campaign(aid, of_id=3301)
    f = _use_fake(); f.seed(3301, finished=True)
    f.slow_send = threading.Event()
    first = asyncio.create_task(pr.run(aid, GO, run_id=0))
    for _ in range(200):
        rows = await _reservations(aid)
        if rows and rows[0].state == "sending":
            break
        await asyncio.sleep(0.02)
    else:
        raise AssertionError("the send never started")
    await _age_all(aid, promo_create_guard.SETTLE_GRACE_S + 1)
    res = await pr.run(aid, GO, run_id=0)                # another worker, past grace
    assert res["skipped"] == "create_open", res
    assert f.created == [] and [r.state for r in await _reservations(aid)] == ["sending"]
    f.slow_send.set()
    res = await first
    assert res["reactivated"] == 1, res
    assert len(f.created) == 1 and (await _campaign(cid)).of_promo_id == max(f.store)


async def case_mn02_unparsed_never_listed_turns_off():
    aid = "pr_mn02_lost"
    cid = await _seed_campaign(aid, of_id=3401)
    await _owner(aid)
    f = _use_fake(); f.seed(3401, finished=True)
    f.create_shape = {"success": True}
    f.lists_new = False
    await run_once(aid, "promo_reactivate", payload=GO)
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["skipped"] == "create_open", res
    await _age_all(aid, promo_create_guard.UNKNOWN_OFF_S + 1)
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["managed"] == 0 and len(f.created) == 1, (res, f.created)
    row = await _campaign(cid)
    assert (row.auto_reactivate, row.keep_warning, row.of_promo_id) == (False, "create_unknown", 3401)
    assert [r.state for r in await _reservations(aid)] == ["lost"]
    notes = await _keep_notices(aid)
    assert len(notes) == 1 and "Keep running is off" in notes[0].text, [n.text for n in notes]
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["managed"] == 0 and len(f.created) == 1


async def case_mn02_listed_never_live_stops_after_three():
    aid = "pr_mn02_breaker"
    cid = await _seed_campaign(aid, of_id=3501)
    await _owner(aid)
    f = _use_fake(); f.seed(3501, finished=True, claims=5)
    f.new_live = False
    for n in range(1, 4):
        res = await run_once(aid, "promo_reactivate", payload=GO)
        assert res["reactivated"] == 1 and len(f.created) == n, (n, res)
        await _age_all(aid, 150)                           # past the Cooldown, inside the hold
        res = await run_once(aid, "promo_reactivate", payload=GO)
        assert res["skipped"] == "breaker_hold" and len(f.created) == n, (n, res)
        await _age_all(aid, 500)                           # past NOT_LISTED_S
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["skipped"] == "breaker" and len(f.created) == 3, res
    row = await _campaign(cid)
    assert (row.auto_reactivate, row.keep_warning) == (False, "breaker"), (row.auto_reactivate,
                                                                            row.keep_warning)
    assert all(r.listed_at is None for r in await _reservations(aid))
    texts = [n.text for n in await _keep_notices(aid)]
    assert sum("re-created" in t for t in texts) == 3 and sum("3 promos in a row" in t for t in texts) == 1, texts


async def case_f6_sold_out_before_any_read_never_trips_breaker():
    """F6: each re-created promo sells out before a read sees it live (OF lists it finished
    with its claims at the cap). A sighting with claims went live: 4 cycles, Keep running
    stays on. (Listed but never live, 0 claims, still trips: case_mn02_listed_never_live.)"""
    aid = "pr_f6_soldout"
    cid = await _seed_campaign(aid, of_id=3511)
    await _owner(aid)
    f = _use_fake(); f.seed(3511, finished=True, claims=10)
    f.new_live = False
    for n in range(1, 5):
        res = await run_once(aid, "promo_reactivate", payload=GO)
        assert res.get("reactivated") == 1 and len(f.created) == n, (n, res)
        f.store[f._id]["claimsCount"] = 10                 # sold out before the next read
        await _age_all(aid, 1300)                          # past the hold and the Cooldown
    row = await _campaign(cid)
    assert (row.auto_reactivate, row.keep_warning) == (True, None), (row.auto_reactivate,
                                                                      row.keep_warning)
    rows = await _reservations(aid)                       # the 4th: no read since its create
    assert sum(r.listed_at is not None for r in rows) == 3, [(r.of_promo_id, r.listed_at) for r in rows]


async def case_owned_earlier_promo_full_never_blocks():
    aid = "pr_owned_earlier"
    cid = await _seed_campaign(aid, of_id=3602)
    f = _use_fake()
    f.seed(3601, finished=False, counts=10, claims=10)    # A: replaced by B, still reads full-but-live
    f.seed(3602, finished=True)                           # B: the Kept promo, ended
    async with get_session() as s:
        s.add(LinkMeta(account_id=aid, kind="promo", of_id=3601, campaign_id=cid))
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["reactivated"] == 1, res

    aid = "pr_foreign_full"
    await _seed_campaign(aid, of_id=3702)
    f = _use_fake()
    f.seed(3701, finished=False, counts=10, claims=10)    # never Inflowwww's
    f.seed(3702, finished=True)
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["skipped"] == "inferred_cap_untrusted" and f.created == [], res


class _Resp:
    def __init__(self, status, text="", headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}


def _refusal(status, text="", headers=None) -> OFAPIError:
    return OFAPIError(f"{status} for /promotions\n{text}", response=_Resp(status, text, headers))


def _posts(f: FakeOF) -> int:
    return len(f.created)


async def case_mn03_429_backs_off_then_turns_off():
    aid = "pr_mn03_429"
    cid = await _seed_campaign(aid, of_id=4001)
    await _owner(aid)
    f = _use_fake(); f.seed(4001, finished=True)
    f.fail_with = _refusal(429)
    t0 = datetime.utcnow()
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert (res["errors"], res["create"], res["error_class"]) == (1, "failed", "http_429"), res
    (row,) = await _reservations(aid)
    assert _near(row.not_before, t0 + timedelta(seconds=120)), row.not_before
    assert (await _campaign(cid)).auto_reactivate and await _keep_notices(aid) == []
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["skipped"] == "backoff" and _posts(f) == 1, res
    assert res["recheck"]["reason"] == "backoff", res
    await _age_all(aid, 121)
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["error_class"] == "http_429" and _posts(f) == 2, res
    row = await _campaign(cid)
    assert (row.auto_reactivate, row.keep_warning) == (False, "rate_limited"), (row.auto_reactivate,
                                                                                 row.keep_warning)
    notes = await _keep_notices(aid)
    assert len(notes) == 1 and "two promo creates in a row" in notes[0].text, [n.text for n in notes]
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["managed"] == 0 and _posts(f) == 2, res


async def case_mn03_single_403_backs_off_keeps_on():
    aid = "pr_mn03_403"
    cid = await _seed_campaign(aid, of_id=4101)
    f = _use_fake(); f.seed(4101, finished=True)
    f.fail_with = _refusal(403, "Forbidden")
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["error_class"] == "http_403", res
    assert (await _campaign(cid)).auto_reactivate
    f.fail_with = None
    await _age_all(aid, 121)
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["reactivated"] == 1, res
    row = await _campaign(cid)
    assert row.auto_reactivate and row.keep_warning is None and row.of_promo_id == max(f.store)
    assert [r.state for r in await _reservations(aid)] == ["failed", "created"]


async def case_mn03_retry_after_over_6h_honoured():
    aid = "pr_mn03_ra"
    await _seed_campaign(aid, of_id=4201)
    f = _use_fake(); f.seed(4201, finished=True)
    f.fail_with = _refusal(429, "", {"Retry-After": "28800"})
    t0 = datetime.utcnow()
    await run_once(aid, "promo_reactivate", payload=GO)
    (row,) = await _reservations(aid)
    assert row.retry_after_s == 28800 and _near(row.not_before, t0 + timedelta(hours=8)), row.not_before
    f.fail_with = None
    await _age_all(aid, 6 * 3600 + 60)                     # past the doubling's cap, not OF's ask
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["skipped"] == "backoff" and _posts(f) == 1, res
    assert "recheck" not in res, "a hold past the backstop is the backstop's"
    await _age_all(aid, 2 * 3600)
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["reactivated"] == 1, res


async def _off_once(aid, of_id, err, warning, text):
    cid = await _seed_campaign(aid, of_id=of_id)
    await _owner(aid)
    f = _use_fake(); f.seed(of_id, finished=True)
    f.fail_with = err
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["error_class"] == warning, res
    row = await _campaign(cid)
    assert (row.auto_reactivate, row.keep_warning) == (False, warning), (row.auto_reactivate, row.keep_warning)
    notes = await _keep_notices(aid)
    assert len(notes) == 1 and text in notes[0].text, [n.text for n in notes]
    await _age_all(aid, 86_400)
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["managed"] == 0 and _posts(f) == 1, (res, f.created)


async def case_mn03_captcha_turns_off():
    await _off_once("pr_mn03_captcha", 4301, _refusal(400, '{"error":"Please complete the captcha"}'),
                    "captcha", "captcha")


async def case_mn11_free_page_no_create():
    await _off_once("pr_mn11_free", 4401, _refusal(403, '{"error":{"code":0,"message":"Access denied."}}'),
                    "price_free", "page is free")


async def case_mn03_dead_session_flags_account():
    aid = "pr_mn03_dead"
    cid = await _seed_campaign(aid, of_id=4501)
    f = _use_fake(); f.seed(4501, finished=True)
    f.fail_with = _refusal(400, '{"error":{"code":301,"message":"Wrong user."}}')
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["error_class"] == "session_dead", res
    assert await account_health.is_session_dead(aid)
    assert (await _campaign(cid)).auto_reactivate, "a dead session never turns Keep running off"
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res == {"status": "skipped", "reason": "session_unlinked"}, res
    assert _posts(f) == 1


async def case_budget_holds_the_fourth():
    aid = "pr_budget"
    await _seed_campaign(aid, of_id=4601)
    f = _use_fake(); f.seed(4601, finished=True)
    async with get_session() as s:
        now = datetime.utcnow()
        for m in (10, 20, 30):                             # failures count too
            at = now - timedelta(minutes=m)
            s.add(PromoCreateReservation(account_id=aid, source="auto_ended", state="failed",
                                         error_class="http_403", terms_json="{}", created_at=at,
                                         settled_at=at, not_before=at + timedelta(seconds=120)))
        s.add(PromoCreateReservation(account_id=aid, source="manual", state="created",
                                     terms_json="{}", created_at=now))
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["skipped"] == "budget" and _posts(f) == 0, res
    assert _near(datetime.fromisoformat(res["recheck"]["at"]),
                 now - timedelta(minutes=30) + timedelta(hours=1, seconds=pr.COOLDOWN_GRACE_S)), res


def _in_loop(loop, coro_fn):
    """A FakeOF hook (it runs in the read's thread) doing DB work on the run's loop."""
    return lambda: asyncio.run_coroutine_threadsafe(coro_fn(), loop).result()


async def _untick(cid):
    async with get_session() as s:
        (await s.get(PromoCampaign, cid)).auto_reactivate = False


async def case_mn10_untick_mid_run_no_post():
    aid = "pr_mn10_mid"
    cid = await _seed_campaign(aid, of_id=4701)
    f = _use_fake(); f.seed(4701, finished=True)
    f.on_list = _in_loop(asyncio.get_running_loop(), lambda: _untick(cid))
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["skipped"] == "campaign_changed" and _posts(f) == 0, res
    assert await _reservations(aid) == []


async def case_mn10_untick_after_reserve_no_post():
    aid = "pr_mn10_after"
    cid = await _seed_campaign(aid, of_id=4801)
    f = _use_fake(); f.seed(4801, finished=True)
    real = promo_create_guard.mark_sending

    async def before_send(res, recheck):
        await _untick(cid)
        return await real(res, recheck)
    promo_create_guard.mark_sending = before_send
    try:
        res = await run_once(aid, "promo_reactivate", payload=GO)
    finally:
        promo_create_guard.mark_sending = real
    assert res["skipped"] == "not_sent" and _posts(f) == 0, res
    assert [(r.state, r.error_class) for r in await _reservations(aid)] == [("failed", "not_sent")]


async def case_mn10_takeover_mid_run_no_post():
    aid = "pr_mn10_takeover"
    a = await _seed_campaign(aid, of_id=4901)
    b = await _seed_campaign(aid, of_id=4902, auto=False)
    f = _use_fake(); f.seed(4901, finished=True); f.seed(4902, finished=False)

    async def takeover():
        async with get_session() as s:
            (await s.get(PromoCampaign, a)).auto_reactivate = False
            (await s.get(PromoCampaign, b)).auto_reactivate = True
    f.store[4902]["isFinished"] = True                     # the read shows nothing live
    f.on_list = _in_loop(asyncio.get_running_loop(), takeover)
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["skipped"] == "campaign_changed" and _posts(f) == 0, res


async def case_mn10_manual_create_after_decision_read_no_post():
    aid = "pr_mn10_manual"
    await _seed_campaign(aid, of_id=5001)
    f = _use_fake(); f.seed(5001, finished=True)

    async def manual():
        async with get_session() as s:
            s.add(PromoCreateReservation(account_id=aid, source="manual", state="created",
                                         terms_json="{}", of_promo_id=5002,
                                         created_at=datetime.utcnow(), settled_at=datetime.utcnow()))
    f.on_list = _in_loop(asyncio.get_running_loop(), manual)
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["skipped"] == "newer_create" and _posts(f) == 0, res


@contextlib.contextmanager
def _host(env: str):
    os.environ[promo_create_guard.HOST_ENV] = env
    try:
        yield
    finally:
        os.environ[promo_create_guard.HOST_ENV] = BOX


async def case_mn07_host_mismatch_or_unset_no_create():
    for i, (stamp, env) in enumerate((("box-a", BOX), ("box-a", ""), (None, BOX), ("", ""), ("", BOX))):
        aid = f"pr_mn07_{i}"
        await _seed_campaign(aid, of_id=5100 + i, host=stamp)
        f = _use_fake(); f.seed(5100 + i, finished=True)
        with _host(env):
            for payload in (GO, {}):                       # a dry run reads nothing either
                res = await run_once(aid, "promo_reactivate", payload=payload)
                assert res["skipped"] == "fence", (stamp, env, res)
        assert f.reads == 0 and _posts(f) == 0 and await _reservations(aid) == [], (stamp, env, f.reads)
    aid = "pr_mn07_moved"
    await _seed_campaign(aid, of_id=5110)
    f = _use_fake(); f.seed(5110, finished=True)
    f.on_list = lambda: os.environ.__setitem__(promo_create_guard.HOST_ENV, "box-b")
    with _host(BOX):
        res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["skipped"] == "fence" and _posts(f) == 0, res


async def case_mn09_free_trial_stops_at_limit():
    aid = "pr_mn09_limit"
    cid = await _seed_campaign(aid, of_id=5201, discount=100, subscribe_days=3, recreates_left=2)
    await _owner(aid)
    f = _use_fake(); f.seed(5201, finished=True, claims=4)
    for n, left in ((1, 1), (2, 0)):
        res = await run_once(aid, "promo_reactivate", payload=GO)
        assert res["reactivated"] == 1 and _posts(f) == n, (n, res)
        assert (await _campaign(cid)).recreates_left == left
        new = (await _campaign(cid)).of_promo_id
        res = await run_once(aid, "promo_reactivate", payload=GO)   # seen live
        assert res.get("skipped") == "promo_already_live" or (n == 2 and res["managed"] == 0), res
        f.store[new].update(isFinished=True, claimsCount=4)
        await _age_all(aid, 600)
    row = await _campaign(cid)
    assert (row.auto_reactivate, row.keep_warning) == (False, "limit_reached"), (row.auto_reactivate, row.keep_warning)
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["managed"] == 0 and _posts(f) == 2, res
    texts = [n.text for n in await _keep_notices(aid)]
    assert sum("Re-create limit" in t for t in texts) == 1, texts


async def case_free_trial_no_limit_keeps_running():
    """Owner 2026-11-21: Keep running is indefinite by default. A Free trial with a Claim cap
    and no Re-create limit re-creates on every finish: never limit_needed / limit_reached."""
    aid = "pr_trial_no_limit"
    cid = await _seed_campaign(aid, of_id=5251, discount=100, subscribe_days=3, recreates_left=None)
    await _owner(aid)
    f = _use_fake(); f.seed(5251, finished=True, claims=4)
    for n in (1, 2, 3):
        res = await run_once(aid, "promo_reactivate", payload=GO)
        assert res["reactivated"] == 1 and _posts(f) == n, (n, res)
        row = await _campaign(cid)
        assert (row.auto_reactivate, row.recreates_left, row.keep_warning) == (True, None, None), n
        f.store[row.of_promo_id].update(isFinished=True, claimsCount=4)
        await _age_all(aid, 600)
    texts = [n.text for n in await _keep_notices(aid)]
    assert len(texts) == 3 and not any("Keep running is off" in x for x in texts), texts


async def case_rv_r01_uncapped_trial_turned_off_before_read():
    """r1: a Kept Free trial with no Claim cap (unlimited claims; a set Re-create limit does
    not help) is turned off once, limit_needed + one notice, before any OF read; a dry run
    leaves it be."""
    for i, (aid, kw) in enumerate((("pr_r01_uncapped_nolimit", {"recreates_left": None, "subscribe_counts": 0}),
                                   ("pr_r01_uncapped", {"recreates_left": 3, "subscribe_counts": 0}))):
        cid = await _seed_campaign(aid, of_id=5301 + i, discount=100, subscribe_days=3, **kw)
        await _owner(aid)
        f = _use_fake(); f.seed(5301 + i, finished=True, counts=kw.get("subscribe_counts", 10))
        res = await run_once(aid, "promo_reactivate", payload={})
        assert (await _campaign(cid)).auto_reactivate and await _keep_notices(aid) == [], (aid, res)
        res = await run_once(aid, "promo_reactivate", payload=GO)
        assert res["skipped"] == "limit_needed" and f.reads == 0 and _posts(f) == 0, (aid, res)
        row = await _campaign(cid)
        assert (row.auto_reactivate, row.keep_warning) == (False, "limit_needed"), (aid, row.keep_warning)
        res = await run_once(aid, "promo_reactivate", payload=GO)
        assert res["managed"] == 0 and f.reads == 0, (aid, res)
        assert len(await _keep_notices(aid)) == 1 and await _reservations(aid) == [], aid


async def case_rv_c11_dry_run_never_turns_off():
    """c11: a dry run never mutates: an aged unknown create and an empty list leave the row
    unknown and Keep running on."""
    aid = "pr_c11_dry"
    cid = await _seed_campaign(aid, of_id=5401)
    f = _use_fake(); f.seed(5401, finished=True)
    f.create_shape = {"success": True}
    f.lists_new = False
    await run_once(aid, "promo_reactivate", payload=GO)
    await _age_all(aid, promo_create_guard.UNKNOWN_OFF_S + 1)
    res = await run_once(aid, "promo_reactivate", payload={})
    assert res["dry_run"] is True, res
    assert [r.state for r in await _reservations(aid)] == ["unknown"]
    row = await _campaign(cid)
    assert (row.auto_reactivate, row.keep_warning) == (True, None), (row.auto_reactivate, row.keep_warning)


async def case_w30_f4_dead_session_on_read_parks_account():
    """W30 F4: the Keep running read meets a dead session (OF's "Wrong user.", or no captured
    session at all): the run errors so run_once marks the account session-dead; the next run
    is skipped before any OF read. Keep running stays ticked. A plain OF failure still stands
    down as of_unreachable (case_fails_closed_when_of_down)."""
    aid = "pr_w30_f4_dead_read"
    cid = await _seed_campaign(aid, of_id=4511)
    f = _use_fake(); f.seed(4511, finished=True)
    reads = []

    def dead(**_k):
        reads.append(1)
        raise _refusal(400, '{"error":{"code":301,"message":"Wrong user."}}')
    f.promotions = dead
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["status"] == "error", res
    assert await account_health.is_session_dead(aid)
    assert (await _campaign(cid)).auto_reactivate, "a dead session never turns Keep running off"
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res == {"status": "skipped", "reason": "session_unlinked"}, res
    assert len(reads) == 1 and _posts(f) == 0, (reads, _posts(f))
    # no captured session: the client load itself fails
    aid = "pr_w30_f4_no_session"
    await _seed_campaign(aid, of_id=4512)

    def missing(account_id):
        raise FileNotFoundError(f"account {account_id} has no captured session")
    ax._make_client = missing  # type: ignore[attr-defined]
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["status"] == "error", res
    assert await account_health.is_session_dead(aid)


async def case_w30_f27_unauthorized_read_backs_off_toasts():
    """W30 F27: the read meets an OF 401 the strict classifier does not name: the run stands
    down (of_unreachable), the account is not parked (as the purchase poll treats a 401),
    and toasts poke nothing until GATE_STALE_S; any other failed read leaves them poking."""
    aid = "pr_w30_f27_401"
    await _seed_campaign(aid, of_id=4521)
    f = _use_fake(); f.seed(4521, finished=True)

    def unauthorized(**_k):
        raise _refusal(401, '{"error":{"code":401,"message":"Unauthorized"}}')
    f.promotions = unauthorized
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res.get("skipped") == "of_unreachable", res
    assert not await account_health.is_session_dead(aid)
    assert pr.should_poke(aid, 1) is False, "a 401 read: toasts back off"
    aid = "pr_w30_f27_500"
    await _seed_campaign(aid, of_id=4522)
    f = _use_fake(); f.seed(4522, finished=True)

    def down(**_k):
        raise _refusal(500, "oops")
    f.promotions = down
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res.get("skipped") == "of_unreachable", res
    assert pr.should_poke(aid, 1) is True, "any other failure: toasts still poke"


_harness.run(
    case_rearm_keeps_both_audiences,
    case_dry_run_is_default,
    case_dry_run_null_is_still_a_dry_run,
    case_reactivates_finished,
    case_rearm_preserves_a_zero_claim_cap,
    case_skips_active,
    case_ignores_unmanaged,
    case_fails_closed_when_of_down,
    case_respects_cycle_cap,
    case_skips_without_discount,
    case_fails_closed_without_of_id,
    case_two_armed_campaigns_do_not_ping_pong,
    case_spent_promo_with_stale_isfinished_is_rearmed,
    case_finds_promo_beyond_page_one,
    case_cap_reached_is_rearmed,
    case_mn01_inferred_cap_without_history_waits,
    case_mn01_missing_count_untrusted,
    case_near_cap_queues_one_recheck,
    case_expiring_soon_queues_an_expiry_recheck,
    case_expiry_past_but_of_live_retries_bounded,
    case_cooldown_queues_a_recheck_and_never_mints,
    case_rearm_sends_finish_days_and_refreshes_expires_at,
    case_dry_run_and_rule_off_queue_no_recheck,
    case_deleted_campaign_stops_rearming,
    case_mn13_racing_rechecks_queue_one,
    case_rv_c09_slot_owned_by_its_job,
    case_mn13_takeover_no_second,
    case_mn13_chain_bounded,
    case_mn05_unparsed_id_unknown_then_adopted,
    case_mn05_invisible_two_reads_no_second_create,
    case_mn06_crash_after_post_adopts_no_duplicate,
    case_mn06_slow_send_past_grace_no_second_post,
    case_mn02_unparsed_never_listed_turns_off,
    case_mn02_listed_never_live_stops_after_three,
    case_f6_sold_out_before_any_read_never_trips_breaker,
    case_owned_earlier_promo_full_never_blocks,
    case_mn03_429_backs_off_then_turns_off,
    case_mn03_single_403_backs_off_keeps_on,
    case_mn03_retry_after_over_6h_honoured,
    case_mn03_captcha_turns_off,
    case_mn11_free_page_no_create,
    case_mn03_dead_session_flags_account,
    case_budget_holds_the_fourth,
    case_mn10_untick_mid_run_no_post,
    case_mn10_untick_after_reserve_no_post,
    case_mn10_takeover_mid_run_no_post,
    case_mn10_manual_create_after_decision_read_no_post,
    case_mn07_host_mismatch_or_unset_no_create,
    case_mn09_free_trial_stops_at_limit,
    case_free_trial_no_limit_keeps_running,
    case_rv_r01_uncapped_trial_turned_off_before_read,
    case_rv_c11_dry_run_never_turns_off,
    case_w30_f4_dead_session_on_read_parks_account,
    case_w30_f27_unauthorized_read_backs_off_toasts,
)
