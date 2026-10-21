#!/usr/bin/env python3
"""purchase_followup (Smart Messages' "Purchased" Trigger) must send a fan ONE
configured message per purchase, after the configured delay, and nothing else:
off by default, silent on a dry run, never twice for the same purchase (a no-id
send included), capped per sweep, blind to skip-listed, paused, blacklisted,
muted-creator and out-of-audience fans, and deaf to purchases it cannot prove
were made inside its window. Mocked OnlyFans only (FakeOF); nothing reaches the
network."""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select, update  # noqa: E402

import audience_include  # noqa: E402
import auth  # noqa: E402
import chatters  # noqa: E402
import purchase_notifications as pn  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, AutomationRule, Blacklist, Fan, Message, PurchaseFollowupClaim,
    ScheduledJob, SkipList, Transaction,
)
import automation_executor as executor  # noqa: E402
import automations.purchase_followup as pf  # noqa: E402
import purchase_followup_config_api as api  # noqa: E402

TEXT = "thank you for unlocking that 💕"
KIND = "purchase_followup"
_REAL_MAKE_CLIENT = executor._make_client
_REAL_PACED = executor.of_write_paced
_REAL_AUDIENCE = audience_include.automation_audience
_REAL_ON_COOLDOWN = executor.fan_on_cooldown
_REAL_LIMIT = pf._LIMIT


class FakeOF:
    """Records every send; echoes an id so attribution has something to link.
    `fail` makes every send raise it; `subscribed` answers the no-id probe;
    `reject_media` refuses any send carrying media the way OF does (a 400
    naming `mediaFiles`)."""
    def __init__(self, *, with_id: bool = True, fail: Exception | None = None,
                 subscribed: bool = True, reject_media: bool = False):
        self.sent: list[tuple[int, str, dict]] = []
        self.reject_media = reject_media
        self.probed: list[int] = []
        self.with_id = with_id
        self.fail = fail
        self.subscribed = subscribed
        self._next_id = 9_000_000_000_000

    def send_message(self, chat_id, text, **kw):
        if self.fail is not None:
            raise self.fail
        if self.reject_media and kw.get("media_files"):
            raise _MediaRejected()
        self._next_id += 1
        self.sent.append((int(chat_id), text, kw))
        if not self.with_id:
            return {"success": True}       # OF's 200 with no message id
        return {"id": self._next_id, "text": f"<p>{text}</p>",
                "createdAt": "2026-06-01T12:30:00+00:00"}

    def get_user(self, fan_id):
        self.probed.append(int(fan_id))
        return {"id": int(fan_id), "subscribedOn": "2026-01-01" if self.subscribed else None}


class _MediaRejected(Exception):
    """OF's answer to a send whose vault media it will not attach."""
    class response:
        status_code = 400

        @staticmethod
        def json():
            return {"errors": {"mediaFiles": ["not found"]}}


PURPOSES: list[str | None] = []


async def _unpaced(account_id, fn, **kw):
    """The real paced seam (send_purpose audit, rate-limit retry) minus the 11s
    spacing, so a sweep of many fans runs in milliseconds."""
    PURPOSES.append(kw.get("send_purpose"))
    return await _REAL_PACED(account_id, fn, **{**kw, "min_gap_s": 0.0, "pause_s": 0.0})


def _use_fake(**kw) -> FakeOF:
    fake = FakeOF(**kw)
    executor._make_client = lambda account_id: fake   # the sender's client seam
    executor.of_write_paced = _unpaced
    PURPOSES.clear()
    return fake


def _sandboxed(go) -> None:
    """Run one case and put every seam it swapped back, pass or fail."""
    try:
        asyncio.run(go())
    finally:
        executor._make_client = _REAL_MAKE_CLIENT
        executor.of_write_paced = _REAL_PACED
        audience_include.automation_audience = _REAL_AUDIENCE
        executor.fan_on_cooldown = _REAL_ON_COOLDOWN
        pf._LIMIT = _REAL_LIMIT


async def _as(principal: str, aid: str, coro_fn):
    """Call a config route as a signed-in owner or chatter of `aid`."""
    ids = frozenset({aid})
    if principal == "owner":
        tok_u = auth._request_user.set(auth.AuthedUser("u-pf-owner", "pf_owner", ids))
        tok_c = chatters._request_chatter.set(None)
    else:
        tok_u = auth._request_user.set(None)
        tok_c = chatters._request_chatter.set(chatters.ChatterIdentity(
            "c-pf", "pf_chatter", None, None, frozenset({"u-pf-owner"}), ids))
    try:
        return await coro_fn()
    finally:
        auth._request_user.reset(tok_u)
        chatters._request_chatter.reset(tok_c)


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _save(aid: str, config: dict, *, principal: str = "owner") -> dict:
    """Save through the config route, as the Smart Messages editor does."""
    return await _as(principal, aid, lambda: api.put_purchase_followup_config(
        api._ConfigBody(account_id=aid, config=config)))


async def _rules(aid: str) -> list[AutomationRule]:
    async with get_session() as s:
        return list((await s.execute(select(AutomationRule).where(
            AutomationRule.account_id == aid, AutomationRule.kind == KIND)
            .order_by(AutomationRule.id))).scalars().all())


async def _steps(aid: str) -> dict:
    return json.loads((await _rules(aid))[0].steps_json)


async def _patch_steps(aid: str, **changes) -> None:
    """Edit the stored rule's steps directly (what a generic PATCH could do)."""
    async with get_session() as s:
        for rule in (await s.execute(select(AutomationRule).where(
                AutomationRule.account_id == aid, AutomationRule.kind == KIND))).scalars():
            steps = json.loads(rule.steps_json)
            for k, v in changes.items():
                if v is None:
                    steps.pop(k, None)
                else:
                    steps[k] = v
            rule.steps_json = json.dumps(steps)


async def _set_enabled(aid: str, on: bool) -> None:
    """Flip the rule's switch the way the generic automation-rules routes do,
    leaving its steps (and their enabled_at) untouched."""
    async with get_session() as s:
        await s.execute(update(AutomationRule).where(
            AutomationRule.account_id == aid, AutomationRule.kind == KIND)
            .values(is_enabled=on))


async def _enable(aid: str, **extra) -> None:
    """Turn it on through the config route, sending "immediately" unless told
    otherwise (Infloww's own start is a 1～3 minute delay). enabled_at is the
    real "now": only purchases seeded after this call count."""
    await _save(aid, {"enabled": True, "text": TEXT, "delay_range": None, **extra})


async def _backdate(aid: str, *, minutes: int) -> None:
    """Pretend the switch went on `minutes` ago."""
    now = datetime.utcnow()
    await _patch_steps(aid, enabled_at=(now - timedelta(minutes=minutes)).isoformat())


async def _seed_purchase(aid: str, fid: int, msg_id: int, *, minutes_ago: float = 0,
                         sent_minutes_ago: float | None = None, ledger_minutes_ago: float | None = None,
                         ledger_status: str = "cleared", **fan_kw) -> None:
    """A PPV this account sent the fan, unlocked `minutes_ago`: the
    `messages.is_paid` / `purchased_at` signal the purchase-notification poll and
    the ledger linker already write. Sent when bought unless `sent_minutes_ago`;
    `ledger_minutes_ago` adds the ledger's transaction row for it."""
    now = datetime.utcnow()
    bought_at = now - timedelta(minutes=minutes_ago)
    sent_at = now - timedelta(minutes=minutes_ago if sent_minutes_ago is None else sent_minutes_ago)
    async with get_session() as s:
        if await s.get(Fan, (aid, fid)) is None:
            s.add(Fan(account_id=aid, fan_id=fid, **fan_kw))
        s.add(Message(account_id=aid, fan_id=fid, message_id=msg_id,
                      direction="out", body="a locked set 🔒", price_cents=1000,
                      is_paid=True, purchased_at=bought_at, created_at=sent_at))
        if ledger_minutes_ago is not None:
            s.add(Transaction(account_id=aid, fan_id=fid, kind="ppv", message_id=msg_id,
                              amount_cents=1000, status=ledger_status,
                              occurred_at=now - timedelta(minutes=ledger_minutes_ago)))


async def _followups(aid: str) -> list[Message]:
    async with get_session() as s:
        return list((await s.execute(select(Message).where(
            Message.account_id == aid,
            Message.automation_kind == KIND))).scalars().all())


async def _fan(aid: str, fid: int) -> Fan:
    async with get_session() as s:
        return await s.get(Fan, (aid, fid))


async def _unpause(aid: str) -> None:
    async with get_session() as s:
        await s.execute(update(Fan).where(Fan.account_id == aid)
                        .values(automation_paused_until=None))


async def _refused(coro, status: int) -> None:
    try:
        await coro
    except HTTPException as e:
        assert e.status_code == status, e
    else:
        raise AssertionError(f"expected {status}")


async def _run(aid: str, n: int, **payload) -> dict:
    return await pf.run(aid, payload, run_id=n)


# ── cases ─────────────────────────────────────────────────────────────

def case_off_by_default_nothing_is_scheduled_or_sent():
    async def go():
        fake = _use_fake()
        aid = "pf_default"
        await _seed_account(aid)
        await _seed_purchase(aid, 11, 1101)
        got = await _as("owner", aid, lambda: api.get_purchase_followup_config(account_id=aid))
        assert got["config"]["enabled"] is False, got
        assert got["defaults"]["enabled"] is False, got
        await executor._materialize_due_rules()
        async with get_session() as s:
            jobs = (await s.execute(select(ScheduledJob).where(
                ScheduledJob.account_id == aid))).scalars().all()
        assert jobs == [], f"an unconfigured account got a job: {jobs}"
        # A stray job for an account with no rule sends nothing either, whatever it carries.
        res = await pf.run(aid, {"enabled": True, "text": TEXT,
                                 "enabled_at": "2000-01-01T00:00:00"}, run_id=1)
        assert res == {"status": "skipped", "reason": "disabled", "sent": 0}, res
        assert fake.sent == [], fake.sent
    _sandboxed(go)


def case_one_message_per_purchase_through_the_gated_paced_seam_and_never_twice():
    async def go():
        fake = _use_fake()
        aid = "pf_happy"
        await _seed_account(aid)
        await _enable(aid)
        await _seed_purchase(aid, 21, 2101)
        res = await _run(aid, 1)
        assert res.get("sent") == 1, res
        assert [(f, t) for f, t, _ in fake.sent] == [(21, TEXT)], fake.sent
        assert fake.sent[0][2].get("media_files") == [], fake.sent
        assert PURPOSES == ["gated"], PURPOSES
        rows = await _followups(aid)
        assert [r.fan_id for r in rows] == [21], rows
        # A SHORT post-send rest (not the drips' 10 minutes): the cooldown is shared
        # by every sender, the AI seller's post-buy follow-up included.
        fan = await _fan(aid, 21)
        now = datetime.utcnow()
        assert fan.automation_paused_until and fan.automation_paused_until > now, fan
        assert fan.automation_paused_until <= now + timedelta(seconds=90), fan.automation_paused_until
        # Dedupe: the same purchase never gets a second message, cooldown or not.
        await _unpause(aid)
        res = await _run(aid, 2)
        assert res.get("sent") == 0 and len(fake.sent) == 1, (res, fake.sent)
        # A NEW purchase by the same fan within 2 hours is claimed, not thanked
        # again (Infloww's own floor on "every time", haveBeenSentMessage.hours=2),
        # however many he unlocks.
        await _seed_purchase(aid, 21, 2102)
        res = await _run(aid, 3)
        assert res.get("sent") == 0 and res.get("folded") == 1 and len(fake.sent) == 1, (res, fake.sent)
        assert (21, 2102) in await pf._claimed(aid, [2102])
        res = await _run(aid, 4)
        assert res.get("folded") == 0 and len(fake.sent) == 1, (res, fake.sent)
        # 3 hours after the thank-you, his next purchase gets one: the silent
        # claim made since is no thank-you.
        async with get_session() as s:
            await s.execute(update(PurchaseFollowupClaim).where(
                PurchaseFollowupClaim.account_id == aid,
                PurchaseFollowupClaim.purchased_message_id == 2101)
                .values(created_at=datetime.utcnow() - timedelta(hours=3)))
        await _seed_purchase(aid, 21, 2103)
        res = await _run(aid, 5)
        assert res.get("sent") == 1 and len(fake.sent) == 2, (res, fake.sent)
    _sandboxed(go)


def case_dry_run_sends_and_claims_nothing():
    async def go():
        fake = _use_fake()
        aid = "pf_dry"
        await _seed_account(aid)
        await _enable(aid)
        await _seed_purchase(aid, 31, 3101)
        res = await _run(aid, 1, dry_run=True)
        assert res.get("dry_run") is True and res.get("would_send") == 1, res
        assert fake.sent == [], fake.sent
        assert await _followups(aid) == []
        # Nothing was claimed: the real run still sends it, once.
        res = await _run(aid, 2)
        assert res.get("sent") == 1 and len(fake.sent) == 1, (res, fake.sent)
        # Once claimed, a dry run no longer counts it either.
        await _unpause(aid)
        res = await _run(aid, 3, dry_run=True)
        assert res.get("would_send") == 0 and res.get("would_fold") == 0, res
    _sandboxed(go)


def case_no_id_send_is_claimed_probed_and_not_retried():
    async def go():
        fake = _use_fake(with_id=False, subscribed=False)
        aid = "pf_noid"
        await _seed_account(aid)
        await _enable(aid)
        await _seed_purchase(aid, 41, 4101)
        res = await _run(aid, 1)
        assert res.get("no_id") == 1, res
        assert len(fake.sent) == 1, fake.sent
        # No id → no attribution row; the fan is probed and, his sub lapsed, quarantined.
        assert await _followups(aid) == []
        assert fake.probed == [41], fake.probed
        assert (await _fan(aid, 41)).subscription_status == "expired"
        # The purchase was claimed before the wire, so the next sweep leaves it.
        await _unpause(aid)
        res = await _run(aid, 2)
        assert len(fake.sent) == 1, f"a no-id purchase was messaged again: {fake.sent}"
    _sandboxed(go)


def case_a_rate_limited_send_is_released_for_a_later_sweep_other_failures_are_not():
    async def go():
        aid = "pf_fail"
        await _seed_account(aid)
        await _enable(aid)
        await _seed_purchase(aid, 45, 4501)
        await _seed_purchase(aid, 46, 4601)
        await _seed_purchase(aid, 47, 4701)
        # OF's throttle: nothing was created, so the claim is handed back.
        fake = _use_fake(fail=Exception('400 {"message":"Please allow 10 seconds"}'))
        res = await _run(aid, 1)
        assert res.get("errors") == 3 and fake.sent == [], res
        fake.fail = None
        res = await _run(aid, 2)
        assert sorted(f for f, _, _ in fake.sent) == [45, 46, 47], (res, fake.sent)
        # A permanent "can't message" skip-lists the fan and keeps the claim.
        await _seed_purchase(aid, 48, 4801)
        fake.fail = Exception("400 Cannot send message to this user")
        res = await _run(aid, 3)
        assert res.get("unreachable") == 1, res
        async with get_session() as s:
            skip = (await s.execute(select(SkipList).where(
                SkipList.account_id == aid, SkipList.fan_id == 48))).scalar_one_or_none()
        assert skip is not None, "an unreachable fan was not skip-listed"
        # Anything else might have reached OF: claimed, never retried.
        await _seed_purchase(aid, 49, 4901)
        fake.fail = Exception("read timeout")
        res = await _run(aid, 4)
        assert res.get("errors") == 1, res
        fake.fail = None
        res = await _run(aid, 5)
        assert res.get("sent") == 0 and len(fake.sent) == 3, (res, fake.sent)
    _sandboxed(go)


def case_cap_limits_each_sweep_the_rest_wait_and_the_cap_is_bounded():
    async def go():
        fake = _use_fake()
        aid = "pf_cap"
        await _seed_account(aid)
        await _enable(aid)
        pf._LIMIT = 1
        await _seed_purchase(aid, 51, 5101)
        await _seed_purchase(aid, 52, 5201)
        res = await _run(aid, 1)
        assert res.get("sent") == 1 and res.get("capped") == 1, (res, fake.sent)
        res = await _run(aid, 2)
        assert res.get("sent") == 1 and len(fake.sent) == 2, (res, fake.sent)
        assert sorted(f for f, _, _ in fake.sent) == [51, 52], fake.sent
        res = await _run(aid, 3)
        assert res.get("sent") == 0 and len(fake.sent) == 2, (res, fake.sent)
        # The cap is 25, whatever the rule's steps say.
        pf._LIMIT = _REAL_LIMIT
        assert pf._LIMIT == 25
        await _patch_steps(aid, limit=10 ** 6)
        for i in range(26):
            await _seed_purchase(aid, 5300 + i, 530_000 + i)
        res = await _run(aid, 4)
        assert res.get("sent") == 25 and res.get("capped") == 1, res
    _sandboxed(go)


def case_a_busy_fan_waits_without_using_a_cap_slot():
    async def go():
        fake = _use_fake()
        aid = "pf_busy"
        await _seed_account(aid)
        await _enable(aid)
        pf._LIMIT = 1
        await _seed_purchase(aid, 55, 5501)
        await _seed_purchase(aid, 56, 5601)
        # A chat engine holds fan 55's send lease mid-reply.
        assert await executor.acquire_fan_lease(aid, 55, "autoreply")
        res = await _run(aid, 1)
        assert res.get("busy") == 1 and [f for f, _, _ in fake.sent] == [56], (res, fake.sent)
        await executor.release_fan_lease(aid, 55)
        res = await _run(aid, 2)
        assert [f for f, _, _ in fake.sent] == [56, 55], (res, fake.sent)
    _sandboxed(go)


def case_delay_holds_the_message_until_due():
    async def go():
        fake = _use_fake()
        aid = "pf_delay"
        await _seed_account(aid)
        await _enable(aid, delay_range=[30, 31])
        await _backdate(aid, minutes=60)
        await _seed_purchase(aid, 61, 6101, minutes_ago=10)
        res = await _run(aid, 1)
        assert res.get("sent") == 0 and fake.sent == [], (res, fake.sent)
        await _seed_purchase(aid, 62, 6201, minutes_ago=45)
        res = await _run(aid, 2)
        assert [f for f, _, _ in fake.sent] == [62], fake.sent
    _sandboxed(go)


def case_the_random_delay_is_drawn_once_per_purchase_inside_the_range():
    """Infloww's "after delay … in random minute intervals a～b minutes": each
    purchase waits its own draw inside [a, b], and every sweep draws the same one
    (from the account, the fan and the message), so it is never re-rolled into
    an early send."""
    draws = {pf.extras.delay_seconds([2, 5], "acc", f, 100 + f) for f in range(200)}
    assert min(draws) >= 120 and max(draws) <= 300 and len(draws) > 50, (min(draws), max(draws))
    assert pf.extras.delay_seconds([2, 5], "acc", 7, 107) == pf.extras.delay_seconds([2, 5], "acc", 7, 107)
    assert pf.extras.delay_seconds(None, "acc", 7, 107) == 0

    async def go():
        fake = _use_fake()
        aid = "pf_rand"
        await _seed_account(aid)
        await _enable(aid, delay_range=[20, 40])
        await _backdate(aid, minutes=120)
        due = {}
        for i, ago in enumerate((5, 15, 25, 30, 35, 45, 55)):
            fid, mid = 640 + i, 64000 + i
            await _seed_purchase(aid, fid, mid, minutes_ago=ago)
            due[fid] = ago * 60 >= pf.extras.delay_seconds([20, 40], aid, fid, mid) + 5
        await _run(aid, 1, cap=25)
        sent = sorted(f for f, _, _ in fake.sent)
        # Past its draw → sent; not yet → held (5 s of slack for the sweep itself).
        assert all(due[f] for f in sent), (sent, due)
        assert {640, 641} - set(sent) == {640, 641}, sent        # 5, 15 min: under 20
        assert {645, 646} <= set(sent), sent                      # 45, 55 min: past 40
    _sandboxed(go)


def case_purchases_before_the_switch_went_on_are_not_chased():
    async def go():
        fake = _use_fake()
        aid = "pf_backlog"
        await _seed_account(aid)
        await _seed_purchase(aid, 71, 7101, minutes_ago=2)
        await _enable(aid)                      # enabled_at = now, two minutes after it
        res = await _run(aid, 1)
        assert res.get("sent") == 0 and fake.sent == [], (res, fake.sent)
    _sandboxed(go)


def case_purchases_older_than_a_day_are_not_chased():
    async def go():
        fake = _use_fake()
        aid = "pf_age"
        await _seed_account(aid)
        await _enable(aid)
        await _backdate(aid, minutes=26 * 60)
        await _seed_purchase(aid, 72, 7201, minutes_ago=24 * 60 + 4)
        await _seed_purchase(aid, 73, 7301, minutes_ago=23 * 60)
        res = await _run(aid, 1)
        assert [f for f, _, _ in fake.sent] == [73], (res, fake.sent)
    _sandboxed(go)


def case_an_old_purchase_flipped_late_is_not_chased():
    async def go():
        fake = _use_fake()
        aid = "pf_late"
        await _seed_account(aid)
        await _enable(aid)
        now = datetime.utcnow()
        # A PPV sent 100 days ago that the purchases feed only now reports as
        # bought 90 days ago (a backfill, a restart): the flip keeps OF's time.
        async with get_session() as s:
            s.add(Fan(account_id=aid, fan_id=74))
            s.add(Message(account_id=aid, fan_id=74, message_id=7401, direction="out",
                          body="old set", price_cents=1000, is_paid=False,
                          created_at=now - timedelta(days=100)))
        old = datetime.now(timezone(timedelta(hours=2))) - timedelta(days=90)
        link = "<a href='https://onlyfans.com/my/chats/chat/74?firstId=7401'>message</a>"
        notif = {"id": 74_000_001, "type": "paided_message",
                 "subType": "subscriber_pay_for_chat_message",
                 "createdAt": old.isoformat(), "text": f"has purchased your {link} for $6.00!",
                 "replacePairs": {"{MESSAGE_LINK}": link, "{AMOUNT}": "$6.00"}}
        out = await pn._handle_items(aid, None, [notif])
        assert out["flipped"] == 1, out
        async with get_session() as s:
            row = (await s.execute(select(Message).where(
                Message.account_id == aid, Message.message_id == 7401))).scalar_one()
        want = old.astimezone(timezone.utc).replace(tzinfo=None)
        assert row.is_paid and abs((row.purchased_at - want).total_seconds()) < 1, row.purchased_at
        res = await _run(aid, 1)
        assert res.get("sent") == 0 and fake.sent == [], (res, fake.sent)
        # Backstop: a purchase stamped "now" by a writer that only knows when it
        # NOTICED (no OF time), on a PPV sent long before the window, is not proof.
        await _seed_purchase(aid, 75, 7501, minutes_ago=0, sent_minutes_ago=100 * 24 * 60)
        res = await _run(aid, 2)
        assert res.get("sent") == 0 and fake.sent == [], (res, fake.sent)
        # The ledger's own transaction time inside the window IS proof.
        await _seed_purchase(aid, 76, 7601, minutes_ago=0, sent_minutes_ago=100 * 24 * 60,
                             ledger_minutes_ago=0)
        res = await _run(aid, 3)
        assert [f for f, _, _ in fake.sent] == [76], (res, fake.sent)
    _sandboxed(go)


def case_a_legacy_delay_minutes_is_kept_exact_up_to_a_day():
    """A rule saved before `delay_range` carries one `delay_minutes`: it keeps
    running as exactly that fixed delay (capped at its old day), never squeezed
    into the range's 1..60, until the owner saves a range."""
    assert pf.delay_of({"delay_minutes": 15}) == [15, 15]
    assert pf.delay_of({"delay_minutes": 90}) == [90, 90]
    assert pf.delay_of({"delay_minutes": 0}) is None
    assert pf.delay_of({"delay_minutes": 7 * 24 * 60}) == [24 * 60, 24 * 60]
    assert pf.delay_of({"delay_minutes": True}) is None
    assert pf.delay_of({"delay_range": None, "delay_minutes": 15}) is None
    assert pf.delay_of({"delay_range": [5, 2]}) == [2, 5]

    async def go():
        fake = _use_fake()
        aid = "pf_delaycap"
        await _seed_account(aid)
        await _enable(aid)
        await _backdate(aid, minutes=3 * 24 * 60)
        # Behind the route's back: the old key, no range.
        await _patch_steps(aid, delay_range=None, delay_minutes=7 * 24 * 60)
        await _seed_purchase(aid, 63, 6301, minutes_ago=24 * 60 + 30)
        await _seed_purchase(aid, 64, 6401, minutes_ago=30)
        res = await _run(aid, 1)
        assert [f for f, _, _ in fake.sent] == [63], (res, fake.sent)
        got = await _as("owner", aid, lambda: api.get_purchase_followup_config(account_id=aid))
        assert got["config"]["delay_range"] == [24 * 60, 24 * 60], got
        # A fixed 90 minutes: not due at 70 (a 59～60 clamp would have sent it), due at 95.
        aid = "pf_delay90"
        await _seed_account(aid)
        await _enable(aid)
        await _backdate(aid, minutes=3 * 60)
        await _patch_steps(aid, delay_range=None, delay_minutes=90)
        await _seed_purchase(aid, 61, 6101, minutes_ago=70)
        await _seed_purchase(aid, 62, 6201, minutes_ago=95)
        res = await _run(aid, 1)
        assert [f for f, _, _ in fake.sent] == [63, 62], (res, fake.sent)
    _sandboxed(go)


def case_a_rule_saved_before_frequency_keeps_its_24h_floor():
    """A stored rule with no `frequency` key keeps the one-per-fan-per-24h floor
    it was built with; only a save that writes the key moves it to 2h."""
    async def go():
        fake = _use_fake()
        aid = "pf_legacy_floor"
        await _seed_account(aid)
        await _enable(aid)
        await _patch_steps(aid, frequency=None)        # as stored before the key
        assert "frequency" not in await _steps(aid)
        await _seed_purchase(aid, 77, 7701)
        assert (await _run(aid, 1)).get("sent") == 1
        await _unpause(aid)

        async def age_thanks(hours: float) -> None:
            async with get_session() as s:
                await s.execute(update(PurchaseFollowupClaim).where(
                    PurchaseFollowupClaim.account_id == aid,
                    PurchaseFollowupClaim.silent.is_(False))
                    .values(created_at=datetime.utcnow() - timedelta(hours=hours)))
        # 3 hours on: past the new 2h floor, inside the old day — folded.
        await age_thanks(3)
        await _seed_purchase(aid, 77, 7702)
        res = await _run(aid, 2)
        assert res.get("sent") == 0 and res.get("folded") == 1, res
        # An unrelated save (switching it off and on, a new text) keeps it legacy.
        await _save(aid, {"enabled": False})
        await _save(aid, {"enabled": True, "text": TEXT})
        assert "frequency" not in await _steps(aid)
        await _seed_purchase(aid, 77, 7703)
        res = await _run(aid, 3)
        assert res.get("sent") == 0 and res.get("folded") == 1, res
        # A day after the thank-you, the next purchase is thanked.
        await age_thanks(25)
        await _seed_purchase(aid, 77, 7704)
        res = await _run(aid, 4)
        assert res.get("sent") == 1 and len(fake.sent) == 2, (res, fake.sent)
        # Saved by the editor (it posts `frequency`): the 2h floor from then on.
        await _unpause(aid)
        await _save(aid, {"frequency": "every"})
        await age_thanks(3)
        await _seed_purchase(aid, 77, 7705)
        res = await _run(aid, 5)
        assert res.get("sent") == 1 and len(fake.sent) == 3, (res, fake.sent)
    _sandboxed(go)


async def _mass_ppv(aid: str, fid: int, msg_id: int, *, run: int, at: datetime,
                    paid: bool) -> None:
    """One recipient's row of a mass PPV: `msg_id` is the shared placeholder id
    when it is in the 5e15 band, else OF's real id for this fan."""
    async with get_session() as s:
        if await s.get(Fan, (aid, fid)) is None:
            s.add(Fan(account_id=aid, fan_id=fid))
        s.add(Message(account_id=aid, fan_id=fid, message_id=msg_id, direction="out",
                      body="mass set 🔒", price_cents=1000,
                      temp_id=f"mass:{run}:{fid}" if msg_id >= 5 * 10 ** 15 else None,
                      is_paid=paid, purchased_at=at if paid else None, created_at=at))


def case_a_mass_placeholder_is_never_thanked_and_its_adopted_row_is_thanked_once():
    async def go():
        import attribution
        fake = _use_fake()
        aid = "pf_mass_dup"
        await _seed_account(aid)
        await _enable(aid)
        ph = attribution.mass_placeholder_message_id(7)
        now = datetime.utcnow()
        # The ledger linked fan 91's purchase to the placeholder; OF's real row
        # for him has not been scraped yet.
        await _mass_ppv(aid, 91, ph, run=7, at=now, paid=True)
        res = await _run(aid, 1)
        assert res.get("candidates") == 0 and fake.sent == [], (res, fake.sent)
        # The real row lands (scraped unpaid) and adoption folds the stub into it,
        # carrying is_paid / purchased_at across.
        await _mass_ppv(aid, 91, 9101, run=7, at=now + timedelta(seconds=20), paid=False)
        async with get_session() as s:
            assert await attribution.adopt_thread_placeholders(s, account_id=aid, fan_id=91) == 1
        async with get_session() as s:
            real = await s.get(Message, (aid, 91, 9101))
        assert real.is_paid and real.purchased_at is not None, real
        res = await _run(aid, 2)
        assert [f for f, _, _ in fake.sent] == [91], (res, fake.sent)
        await _unpause(aid)
        res = await _run(aid, 3)
        assert len(fake.sent) == 1, f"one purchase, thanked twice: {fake.sent}"
        # Placeholder and real row BOTH paid (the feed flipped the real row, the
        # ledger the stub, adoption refused): still one message.
        await _mass_ppv(aid, 92, ph, run=7, at=now, paid=True)
        await _mass_ppv(aid, 92, 9201, run=7, at=now, paid=True)
        res = await _run(aid, 4)
        assert [f for f, _, _ in fake.sent] == [91, 92], (res, fake.sent)
    _sandboxed(go)


def case_two_fans_who_bought_the_same_message_id_are_each_thanked():
    async def go():
        fake = _use_fake()
        aid = "pf_mass_miss"
        await _seed_account(aid)
        await _enable(aid)
        # The claim is per FAN and message: one id held by two fans' rows (the
        # messages key is account+fan+message) is two purchases.
        await _seed_purchase(aid, 93, 9301)
        res = await _run(aid, 1)
        assert [f for f, _, _ in fake.sent] == [93], (res, fake.sent)
        # The second buyer comes AFTER the first one's claim: his is his own.
        await _seed_purchase(aid, 94, 9301)
        res = await _run(aid, 2)
        assert [f for f, _, _ in fake.sent] == [93, 94], (res, fake.sent)
        await _unpause(aid)
        res = await _run(aid, 3)
        assert len(fake.sent) == 2, fake.sent
        assert await pf._claim(aid, 93, [9301]) == [] and await pf._claim(aid, 94, [9301]) == []
    _sandboxed(go)


def _notif(fid: int, msg_id: int, n: int, created_at) -> dict:
    link = f"<a href='https://onlyfans.com/my/chats/chat/{fid}?firstId={msg_id}'>message</a>"
    out = {"id": n, "type": "paided_message", "subType": "subscriber_pay_for_chat_message",
           "text": f"has purchased your {link} for $6.00!",
           "replacePairs": {"{MESSAGE_LINK}": link, "{AMOUNT}": "$6.00"}}
    if created_at is not None:
        out["createdAt"] = created_at
    return out


def case_a_purchase_notification_time_inside_the_window_is_proof():
    async def go():
        fake = _use_fake()
        aid = "pf_notified"
        await _seed_account(aid)
        await _enable(aid)
        now = datetime.utcnow()
        async with get_session() as s:
            for fid, mid in ((95, 9501), (96, 9601)):
                s.add(Fan(account_id=aid, fan_id=fid))
                s.add(Message(account_id=aid, fan_id=fid, message_id=mid, direction="out",
                              body="old mass set", price_cents=1000, is_paid=False,
                              created_at=now - timedelta(days=5)))
        # A PPV sent five days ago, bought just now: the feed's own createdAt says so.
        bought = datetime.now(timezone.utc).isoformat()
        out = await pn._handle_items(aid, None, [_notif(95, 9501, 95_000_001, bought),
                                                 _notif(96, 9601, 96_000_001, None)])
        assert out["flipped"] == 2, out
        res = await _run(aid, 1)
        # Fan 96's notification carried no time: its "now" is not proof (the
        # ledger will be, when it lands).
        assert [f for f, _, _ in fake.sent] == [95], (res, fake.sent)
    _sandboxed(go)


def case_a_notification_for_a_row_already_flipped_paid_still_proves_the_time():
    async def go():
        fake = _use_fake()
        aid = "pf_notified_paid"
        await _seed_account(aid)
        await _enable(aid)
        now = datetime.utcnow()
        # another lane's isOpened fast path flipped it first, stamping "now".
        async with get_session() as s:
            s.add(Fan(account_id=aid, fan_id=103))
            s.add(Message(account_id=aid, fan_id=103, message_id=10301, direction="out",
                          body="old set", price_cents=1000, is_paid=True, purchased_at=now,
                          created_at=now - timedelta(days=5)))
        res = await _run(aid, 1)
        assert fake.sent == [], (res, fake.sent)     # "now" alone is not proof
        bought = datetime.now(timezone.utc).isoformat()
        out = await pn._handle_items(aid, None, [_notif(103, 10301, 103_000_001, bought)])
        assert out["flipped"] == 0, out              # already paid: no flip...
        res = await _run(aid, 2)
        assert [f for f, _, _ in fake.sent] == [103], (res, fake.sent)   # ...but the time is kept
    _sandboxed(go)


def case_a_ledger_row_or_notice_from_before_the_window_is_not_proof():
    """A sale restamped "now" by another writer is not proven by a ledger row or a
    purchases-feed notice from days ago: each proof is bounded below too."""
    async def go():
        fake = _use_fake()
        aid = "pf_stale_proof"
        await _seed_account(aid)
        await _enable(aid)
        three_days = 3 * 24 * 60
        await _seed_purchase(aid, 108, 10801, sent_minutes_ago=5 * 24 * 60,
                             ledger_minutes_ago=three_days)
        await _seed_purchase(aid, 109, 10901, sent_minutes_ago=5 * 24 * 60)
        old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        out = await pn._handle_items(aid, None, [_notif(109, 10901, 109_000_001, old)])
        assert out["flipped"] == 0, out
        res = await _run(aid, 1)
        assert fake.sent == [] and res.get("candidates") == 0, (res, fake.sent)
    _sandboxed(go)


def case_the_rest_after_a_thank_you_never_shortens_a_longer_pause():
    async def go():
        aid = "pf_rest"
        await _seed_account(aid)
        now = datetime.utcnow()
        async with get_session() as s:
            s.add(Fan(account_id=aid, fan_id=104,
                      automation_paused_until=now + timedelta(hours=72)))   # a decline pause
            s.add(Fan(account_id=aid, fan_id=105))
            s.add(Fan(account_id=aid, fan_id=106,
                      automation_paused_until=now + timedelta(seconds=5)))
        for fid in (104, 105, 106):
            await pf._rest(aid, fid)
        f104, f105, f106 = [await _fan(aid, f) for f in (104, 105, 106)]
        assert f104.automation_paused_until > now + timedelta(hours=71), f104.automation_paused_until
        for f in (f105, f106):
            assert now + timedelta(seconds=30) < f.automation_paused_until <= \
                datetime.utcnow() + timedelta(seconds=pf._COOLDOWN_S), f.automation_paused_until
    _sandboxed(go)


def case_the_sweep_reads_messages_through_an_index():
    """No walk of an account's outbound history every minute: each read of
    `messages` the sweep makes is an index SEARCH bounded by a time column or by
    the primary key, never a SCAN nor a search on (account, direction) alone."""
    async def go():
        from sqlalchemy import event
        from db.engine import engine
        fake = _use_fake()
        aid = "pf_plan"
        await _seed_account(aid)
        await _enable(aid)
        await _seed_purchase(aid, 107, 10701, sent_minutes_ago=5 * 24 * 60, ledger_minutes_ago=0)
        seen: list[tuple[str, object]] = []

        def _grab(conn, cursor, statement, params, context, executemany):
            if re.search(r"\b(FROM|JOIN) messages\b", statement) \
                    and statement.lstrip().upper().startswith("SELECT"):
                seen.append((statement, params))
        event.listen(engine.sync_engine, "before_cursor_execute", _grab)
        try:
            res = await _run(aid, 1)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", _grab)
        assert [f for f, _, _ in fake.sent] == [107], (res, fake.sent)
        assert len(seen) >= 3, seen     # one read per proof: sent, ledger, notice
        async with engine.connect() as conn:
            for stmt, params in seen:
                plan = [str(r[-1]) for r in
                        (await conn.exec_driver_sql("EXPLAIN QUERY PLAN " + stmt, params)).all()]
                on_messages = [d for d in plan if re.match(r"(SCAN|SEARCH) messages\b", d)]
                assert on_messages, (stmt, plan)
                for d in on_messages:
                    assert d.startswith("SEARCH messages") and (
                        "created_at>" in d or "message_id=?" in d), (stmt, plan)
    _sandboxed(go)


def case_the_notification_purchase_time_is_never_missing_or_future():
    now = datetime.utcnow()
    for raw in (None, "", "not a time"):
        assert pn._notified_time(raw) is None, raw
        assert abs((pn._purchase_time(raw) - now).total_seconds()) < 5, raw
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    got = pn._notified_time(future)
    assert got is not None and got <= datetime.utcnow(), got
    assert pn._purchase_time(future) <= datetime.utcnow()
    assert pn._notified_time("2026-01-02T03:04:05Z") == datetime(2026, 1, 2, 3, 4, 5)
    assert pn._notified_time("2026-01-02T05:04:05+02:00") == datetime(2026, 1, 2, 3, 4, 5)


def case_a_refunded_or_charged_back_transaction_is_not_proof():
    async def go():
        fake = _use_fake()
        aid = "pf_refund"
        await _seed_account(aid)
        await _enable(aid)
        old = 100 * 24 * 60
        await _seed_purchase(aid, 97, 9701, sent_minutes_ago=old, ledger_minutes_ago=0,
                             ledger_status="refunded")
        await _seed_purchase(aid, 98, 9801, sent_minutes_ago=old, ledger_minutes_ago=0,
                             ledger_status="chargedback")
        await _seed_purchase(aid, 99, 9901, sent_minutes_ago=old, ledger_minutes_ago=0,
                             ledger_status="pending")
        res = await _run(aid, 1)
        assert [f for f, _, _ in fake.sent] == [99], (res, fake.sent)
    _sandboxed(go)


def case_a_client_that_cannot_be_built_claims_nothing():
    async def go():
        aid = "pf_client"
        await _seed_account(aid)
        await _enable(aid)
        await _seed_purchase(aid, 100, 10001)

        def _broken(account_id):
            raise RuntimeError("no session on disk")
        executor._make_client = _broken
        try:
            await _run(aid, 1)
        except RuntimeError:
            pass
        else:
            raise AssertionError("a broken client was swallowed")
        assert await pf._claimed(aid, [10001]) == set(), "a run that never sent kept a claim"
        fake = _use_fake()
        res = await _run(aid, 2)
        assert [f for f, _, _ in fake.sent] == [100], (res, fake.sent)
    _sandboxed(go)


def case_a_fan_paused_after_the_snapshot_is_skipped_unclaimed():
    async def go():
        fake = _use_fake()
        aid = "pf_fresh_pause"
        await _seed_account(aid)
        await _enable(aid)
        await _seed_purchase(aid, 101, 10101)
        await _seed_purchase(aid, 102, 10201)

        async def _paused_now(account_id, fan_id):
            return int(fan_id) == 101       # another sender rested him mid-sweep
        executor.fan_on_cooldown = _paused_now
        res = await _run(aid, 1)
        assert [f for f, _, _ in fake.sent] == [102], (res, fake.sent)
        assert await pf._claimed(aid, [10101]) == set()
        executor.fan_on_cooldown = _REAL_ON_COOLDOWN
        await _unpause(aid)
        res = await _run(aid, 2)
        assert [f for f, _, _ in fake.sent] == [102, 101], (res, fake.sent)
    _sandboxed(go)


def case_the_claim_survives_another_writer_rewriting_custom_fields():
    async def go():
        fake = _use_fake()
        aid = "pf_race"
        await _seed_account(aid)
        await _enable(aid)
        await _seed_purchase(aid, 77, 7701)
        res = await _run(aid, 1)
        assert res.get("sent") == 1, res
        # Another engine read the fan's blob before our claim and writes it back.
        async with get_session() as s:
            await s.execute(update(Fan).where(Fan.account_id == aid, Fan.fan_id == 77)
                            .values(custom_fields=json.dumps({"other_engine": 1}),
                                    automation_paused_until=None))
        res = await _run(aid, 2)
        assert res.get("sent") == 0 and len(fake.sent) == 1, (res, fake.sent)
        # The claim itself: a second claim of the same purchase wins nothing.
        assert await pf._claim(aid, 77, [7701]) == []
    _sandboxed(go)


def case_a_job_queued_before_the_switch_went_off_sends_nothing():
    async def go():
        fake = _use_fake()
        aid = "pf_stale"
        await _seed_account(aid)
        await _enable(aid)
        await _seed_purchase(aid, 78, 7801)
        snapshot = await _steps(aid)            # what a job materialised while on carries
        assert snapshot["enabled"] is True, snapshot
        await _save(aid, {"enabled": False})    # switched off; the job is still queued
        res = await pf.run(aid, snapshot, run_id=1)
        assert res == {"status": "skipped", "reason": "disabled", "sent": 0}, res
        # Off through the generic switch (steps untouched) is off too.
        await _enable(aid)
        await _set_enabled(aid, False)
        res = await pf.run(aid, await _steps(aid), run_id=2)
        assert res == {"status": "skipped", "reason": "disabled", "sent": 0}, res
        assert fake.sent == [], fake.sent
    _sandboxed(go)


def case_off_then_on_through_the_config_route_does_not_chase_purchases_made_while_off():
    async def go():
        fake = _use_fake()
        aid = "pf_reenable"
        await _seed_account(aid)
        await _enable(aid)
        await _backdate(aid, minutes=120)
        await _save(aid, {"enabled": False})
        await _seed_purchase(aid, 79, 7901, minutes_ago=60)     # bought while off
        await _enable(aid)                                       # restamps enabled_at
        await _seed_purchase(aid, 80, 8001, minutes_ago=0)      # bought after
        res = await _run(aid, 1)
        assert [f for f, _, _ in fake.sent] == [80], (res, fake.sent)
    _sandboxed(go)


def case_the_generic_rule_routes_refuse_this_kind_except_switching_it_off():
    """Only the config route is owner-only and restamps enabled_at, so the generic
    automation-rules create / PATCH / switch refuse the kind, for anyone — except
    a plain switch-off (the Automations panel's toggle), which is always safe."""
    async def go():
        import automation_rules_api as rules_api
        aid = "pf_generic"
        await _seed_account(aid)
        await _enable(aid)
        rule = (await _rules(aid))[0]
        before = (rule.is_enabled, rule.steps_json, rule.trigger_json)
        for who in ("chatter", "owner"):
            calls = (
                lambda: rules_api.switch_kind(rules_api.KindSwitch(
                    account_id=aid, kind=KIND, enable=True)),
                lambda: rules_api.update_rule(rule.id, rules_api.RulePatch(is_enabled=True)),
                lambda: rules_api.update_rule(rule.id, rules_api.RulePatch(
                    is_enabled=False, name="renamed")),
                lambda: rules_api.update_rule(rule.id, rules_api.RulePatch(every_seconds=3600)),
                lambda: rules_api.update_rule(rule.id, rules_api.RulePatch(
                    payload={"enabled": True, "text": "x", "enabled_at": "2000-01-01T00:00:00"})),
                lambda: rules_api.create_rule(rules_api.RuleCreate(
                    account_id=aid, kind=KIND, is_enabled=True,
                    payload={"enabled": True, "text": "x"})),
            )
            for call in calls:
                try:
                    await _as(who, aid, call)
                except HTTPException as e:
                    assert e.status_code == 409, (who, e.status_code, e.detail)
                    assert "/admin/purchase-followup-config" in str(e.detail), e.detail
                else:
                    raise AssertionError(f"{who}: a generic route wrote a {KIND} rule")
        rules = await _rules(aid)
        assert len(rules) == 1, rules
        assert (rules[0].is_enabled, rules[0].steps_json, rules[0].trigger_json) == before
        # Switching it OFF is let through: the panel's toggle and the kind switch.
        out = await _as("chatter", aid, lambda: rules_api.update_rule(
            rule.id, rules_api.RulePatch(is_enabled=False)))
        assert out["is_enabled"] is False, out
        await _enable(aid)
        out = await _as("chatter", aid, lambda: rules_api.switch_kind(rules_api.KindSwitch(
            account_id=aid, kind=KIND, enable=False)))
        assert not any(r.is_enabled for r in await _rules(aid))
        # Its steps are untouched, so back on goes through the config route.
        assert json.loads((await _rules(aid))[0].steps_json)["text"] == TEXT
    _sandboxed(go)


def case_a_rule_without_a_readable_enable_stamp_sends_nothing():
    async def go():
        fake = _use_fake()
        aid = "pf_nostamp"
        await _seed_account(aid)
        await _enable(aid)
        await _seed_purchase(aid, 85, 8501)
        await _patch_steps(aid, enabled_at=None)
        res = await _run(aid, 1)
        assert res.get("status") == "skipped" and res.get("reason") == "no_enabled_at", res
        await _patch_steps(aid, enabled_at="yesterday-ish")
        res = await _run(aid, 2)
        assert res.get("status") == "skipped" and res.get("reason") == "no_enabled_at", res
        assert fake.sent == [], fake.sent
    _sandboxed(go)


def case_skip_listed_paused_blacklisted_and_muted_creator_fans_are_left_alone():
    async def go():
        fake = _use_fake()
        aid = "pf_skip"
        await _seed_account(aid)
        await _enable(aid)
        await _seed_purchase(aid, 81, 8101)
        await _seed_purchase(aid, 82, 8201, automation_paused_until=datetime.utcnow() + timedelta(hours=1))
        await _seed_purchase(aid, 83, 8301)
        await _seed_purchase(aid, 84, 8401)
        await _seed_purchase(aid, 86, 8601, is_muted=True, source="creator_we_follow")
        async with get_session() as s:
            s.add(SkipList(account_id=aid, fan_id=81, reason="manual_restrict"))
            s.add(Blacklist(fan_id=83, reason="test"))
        res = await _run(aid, 0, dry_run=True)       # the dry run's count leaves them out too
        assert res.get("would_send") == 1 and res.get("skipped") == 4, res
        res = await _run(aid, 1)
        assert [f for f, _, _ in fake.sent] == [84], (res, fake.sent)
        assert res.get("skipped") == 4, res
    _sandboxed(go)


def case_the_include_only_audience_is_honoured():
    async def go():
        fake = _use_fake()
        aid = "pf_audience"
        await _seed_account(aid)
        await _enable(aid)
        await _seed_purchase(aid, 87, 8701)
        await _seed_purchase(aid, 88, 8801)
        policy = audience_include._AUDIENCE_OFF._replace(
            mode="enforce", configured_mode="enforce", member_ids=frozenset({88}))

        async def _enforced(account_id):
            return policy
        audience_include.automation_audience = _enforced
        res = await _run(aid, 1)
        assert [f for f, _, _ in fake.sent] == [88], (res, fake.sent)
        assert res.get("audience_mode") == "enforce", res
    _sandboxed(go)


def case_the_text_goes_out_word_restricted():
    async def go():
        fake = _use_fake()
        aid = "pf_words"
        await _seed_account(aid)
        await _save(aid, {"enabled": True, "text": "let's meet soon", "delay_range": None})
        await _seed_purchase(aid, 89, 8901)
        await _run(aid, 1)
        sent = [t for _, t, _ in fake.sent]
        assert sent == [pf.apply_word_restriction("let's meet soon")], sent
        assert sent[0] != "let's meet soon", sent
    _sandboxed(go)


def case_name_is_filled_per_fan_never_sent_literally():
    """`{name}` is the fan's name — his real first name when known real, else his
    chosen nickname, else "babe" — filled per fan, as the lifecycle messages do."""
    async def go():
        fake = _use_fake()
        aid = "pf_name"
        await _seed_account(aid)
        await _save(aid, {"enabled": True, "delay_range": None,
                          "text": "Thanks for your purchase, {name}! You're in for a treat!"})
        await _seed_purchase(aid, 91, 9101, real_name="Mark Twain", is_name_real=True)
        await _seed_purchase(aid, 92, 9201, fan_chosen_nickname="Jojo")
        await _seed_purchase(aid, 93, 9301)
        await _run(aid, 1)
        sent = sorted((f, t) for f, t, _ in fake.sent)
        assert sent == [
            (91, "Thanks for your purchase, Mark! You're in for a treat!"),
            (92, "Thanks for your purchase, Jojo! You're in for a treat!"),
            (93, "Thanks for your purchase, babe! You're in for a treat!"),
        ], sent
    _sandboxed(go)


def case_end_to_end_a_switched_on_rule_is_materialised_and_run_by_the_executor():
    async def go():
        fake = _use_fake()
        aid = "pf_e2e"
        await _seed_account(aid)
        await _enable(aid)
        await _seed_purchase(aid, 90, 9001)
        await executor._materialize_due_rules()
        async with get_session() as s:
            jobs = (await s.execute(select(ScheduledJob).where(
                ScheduledJob.account_id == aid, ScheduledJob.kind == KIND,
                ScheduledJob.status == "pending"))).scalars().all()
        assert len(jobs) == 1, jobs
        res = await executor.run_once(aid, KIND)
        assert res.get("status") == "ok" and res.get("sent") == 1, res
        assert [f for f, _, _ in fake.sent] == [90], fake.sent
        async with get_session() as s:
            job = await s.get(ScheduledJob, jobs[0].id)
        assert job.status == "done", job.status
    _sandboxed(go)


def case_the_config_route_saves_the_rule_off_by_default_and_refuses_bad_input():
    async def go():
        aid = "pf_api"
        await _seed_account(aid)
        got = await _as("owner", aid, lambda: api.get_purchase_followup_config(account_id=aid))
        # Infloww's start for Purchased: a 1～3 minute delay, every time.
        assert got["config"] == got["defaults"] == {
            "enabled": False, "text": "", "media_ids": [], "price_cents": 0,
            "frequency": "every", "starts_at": None, "ends_at": None,
            "unsend_minutes": 0, "delay_range": [1, 3]}, got
        out = await _save(aid, {"enabled": True, "text": "  hi there  ", "delay_range": [15, 15]})
        assert out["config"] == {
            "enabled": True, "text": "hi there", "media_ids": [], "price_cents": 0,
            "frequency": "every", "starts_at": None, "ends_at": None,
            "unsend_minutes": 0, "delay_range": [15, 16]}, out
        rule = (await _rules(aid))[0]
        assert rule.is_enabled is True
        assert json.loads(rule.trigger_json) == {"every_seconds": 60}, rule.trigger_json
        steps = json.loads(rule.steps_json)
        assert steps["text"] == "hi there" and steps["delay_range"] == [15, 16], steps
        assert steps.get("enabled_at"), steps
        # Saving again while on keeps the first enable stamp.
        await _save(aid, {"enabled": True, "text": "hi again"})
        assert (await _steps(aid))["enabled_at"] == steps["enabled_at"]
        # Off: the rule is disabled, its text kept.
        out = await _save(aid, {"enabled": False})
        assert out["config"]["enabled"] is False and out["config"]["text"] == "hi again", out
        rules = await _rules(aid)
        assert len(rules) == 1 and rules[0].is_enabled is False, rules
        # Switching on needs the text IN the request, not a stored draft.
        await _refused(_save(aid, {"enabled": True}), 422)
        assert (await _rules(aid))[0].is_enabled is False
        # Refused: on with no text, and anything that is not the exact JSON type
        # (`"false"` would read as on, `true` as a one-minute delay).
        for bad in ({"enabled": True, "text": "   "}, {"delay_range": "soon"},
                    {"enabled": "false"}, {"enabled": 1}, {"delay_range": [True, 3]},
                    {"enabled": "false", "text": "hi"}, {"enabled": 1, "text": "hi"},
                    {"delay_range": [1.5, 3]}, {"delay_range": [1, 2, 3]}, {"text": 5},
                    {"media_ids": [0]}, {"media_ids": "5"}, {"media_ids": list(range(1, 42))},
                    {"price_cents": 299}, {"price_cents": -1}, {"price_cents": 5.0},
                    {"price_cents": 500},                         # a price with no media
                    {"frequency": "twice"}, {"starts_at": "soon"}, {"ends_at": 5},
                    {"starts_at": "2026-07-02T10:00:00Z", "ends_at": "2026-07-01T10:00:00Z"},
                    {"price_cents": 20_001, "media_ids": [1]},   # past OF's $200 PPV max
                    {"unsend_minutes": -1}, {"unsend_minutes": 23 * 60 + 1},
                    {"unsend_minutes": True}):
            await _refused(_save(aid, bad), 422)
        got = await _as("owner", aid, lambda: api.get_purchase_followup_config(account_id=aid))
        assert got["config"]["text"] == "hi again" and got["config"]["delay_range"] == [15, 16], got
        # The range is clamped as Infloww clamps it; null is "immediately".
        out = await _save(aid, {"delay_range": [90, 0]})
        assert out["config"]["delay_range"] == [1, 60], out
        out = await _save(aid, {"delay_range": None})
        assert out["config"]["delay_range"] is None, out
        # The extras round-trip, the stamps as UTC.
        out = await _save(aid, {"media_ids": [7, 8, 7], "price_cents": 500, "frequency": "once",
                                "starts_at": "2026-07-01T10:00:00+02:00", "ends_at": None,
                                "unsend_minutes": 90})
        cfg = out["config"]
        assert (cfg["media_ids"], cfg["price_cents"], cfg["frequency"], cfg["starts_at"],
                cfg["ends_at"], cfg["unsend_minutes"]) == (
            [7, 8], 500, "once", "2026-07-01T08:00:00+00:00", None, 90), cfg
        # Media can go while a price stays only if the price goes too.
        await _refused(_save(aid, {"media_ids": []}), 422)
        out = await _save(aid, {"media_ids": [], "price_cents": 0})
        assert out["config"]["media_ids"] == [] and out["config"]["price_cents"] == 0, out
        # The pre-range key survives a save that posts no range (it stays the
        # rule's exact delay), and goes when a range is posted.
        await _patch_steps(aid, delay_minutes=15, delay_range=None)
        await _save(aid, {"text": "hi"})
        steps = await _steps(aid)
        assert steps["delay_minutes"] == 15 and "delay_range" not in steps, steps
        await _save(aid, {"enabled": False})
        assert (await _steps(aid))["delay_minutes"] == 15
        out = await _save(aid, {"delay_range": [2, 5]})
        steps = await _steps(aid)
        assert "delay_minutes" not in steps and steps["delay_range"] == [2, 5], steps
    _sandboxed(go)


def case_media_and_a_price_go_out_with_the_message_and_its_price_is_recorded():
    async def go():
        fake = _use_fake()
        aid = "pf_ppv"
        await _seed_account(aid)
        await _enable(aid, media_ids=[501, 502], price_cents=700)
        await _seed_purchase(aid, 65, 6501)
        res = await _run(aid, 1)
        assert res.get("sent") == 1, res
        assert fake.sent[0][2] == {"media_files": [501, 502], "price": 7.0}, fake.sent
        rows = await _followups(aid)
        assert [(r.fan_id, r.price_cents) for r in rows] == [(65, 700)], rows
    _sandboxed(go)


def case_media_of_refuses_goes_out_as_the_free_text_alone():
    """OF refusing the vault media (deleted since) must not cost the fan his
    thank-you: the text goes out alone, free, and is recorded free."""
    async def go():
        fake = _use_fake(reject_media=True)
        aid = "pf_badmedia"
        await _seed_account(aid)
        await _enable(aid, media_ids=[503], price_cents=700, unsend_minutes=30)
        await _seed_purchase(aid, 66, 6601)
        res = await _run(aid, 1)
        assert res.get("sent") == 1, res
        assert [(f, t, kw) for f, t, kw in fake.sent] == [(66, TEXT, {"media_files": []})], fake.sent
        rows = await _followups(aid)
        assert [r.price_cents for r in rows] == [0], rows
        # It landed free, so its Auto-unsend is queued.
        assert len(await _unsend_jobs(aid)) == 1
    _sandboxed(go)


def case_a_fan_who_owns_the_media_gets_the_text_alone_free():
    """ppv_send's ownership guard: a paid thank-you never re-sells media the fan
    already unlocked. He gets the text alone, free (and its Auto-unsend); the
    others get the PPV."""
    async def go():
        fake = _use_fake()
        aid = "pf_owns_media"
        await _seed_account(aid)
        await _enable(aid, media_ids=[505, 506], price_cents=700, unsend_minutes=30)
        await _seed_purchase(aid, 78, 7801)
        await _seed_purchase(aid, 79, 7901)
        async with get_session() as s:      # 78 bought media 506 before
            s.add(Message(account_id=aid, fan_id=78, message_id=7800, direction="out",
                          body="older set", price_cents=900, is_paid=True,
                          media_ids="[506]", created_at=datetime.utcnow() - timedelta(days=9)))
        res = await _run(aid, 1)
        assert res.get("sent") == 2 and res.get("owners_sent_free") == 1, res
        sent = {f: kw for f, _, kw in fake.sent}
        assert sent[78] == {"media_files": []}, sent
        assert sent[79] == {"media_files": [505, 506], "price": 7.0}, sent
        rows = {r.fan_id: r.price_cents for r in await _followups(aid)}
        assert rows == {78: 0, 79: 700}, rows
        assert [json.loads(j.payload_json)["targets"][0]["fan_id"]
                for j in await _unsend_jobs(aid)] == [78]
    _sandboxed(go)


def case_the_price_ceiling_is_of_s_and_auto_unsend_stops_inside_of_s_window():
    import smart_message_extras as extras
    assert extras.PRICE_MAX_CENTS == 20_000
    assert extras.UNSEND_MAX_MINUTES == 23 * 60
    # A stored price past the ceiling (written behind the route) is sent at it.
    assert extras.media_and_price({"media_ids": [1], "price_cents": 50_000}) == ([1], 20_000)


def case_its_own_paid_thank_you_bought_is_never_a_purchase_to_thank_for():
    async def go():
        fake = _use_fake()
        aid = "pf_self"
        await _seed_account(aid)
        await _enable(aid, media_ids=[507], price_cents=500)
        async with get_session() as s:
            s.add(Fan(account_id=aid, fan_id=80))
            s.add(Message(account_id=aid, fan_id=80, message_id=8001, direction="out",
                          body="thanks 🔒", price_cents=500, is_paid=True,
                          purchased_at=datetime.utcnow(), created_at=datetime.utcnow(),
                          automation_kind=KIND))
        res = await _run(aid, 1)
        assert res.get("sent") == 0 and res.get("candidates") == 0 and fake.sent == [], res
    _sandboxed(go)


def case_a_failed_auto_unsend_queue_never_costs_the_claim_or_the_rest():
    async def go():
        fake = _use_fake()
        aid = "pf_unsend_boom"
        await _seed_account(aid)
        await _enable(aid, unsend_minutes=30)
        await _seed_purchase(aid, 81, 8101)
        real = executor.enqueue_followup

        async def boom(*a, **kw):
            raise RuntimeError("db locked")
        executor.enqueue_followup = boom
        try:
            res = await _run(aid, 1)
        finally:
            executor.enqueue_followup = real
        assert res.get("sent") == 1 and len(fake.sent) == 1, res
        assert (81, 8101) in await pf._claimed(aid, [8101])
        fan = await _fan(aid, 81)
        assert fan.automation_paused_until and fan.automation_paused_until > datetime.utcnow(), fan
        assert await _unsend_jobs(aid) == []
    _sandboxed(go)


def case_inside_a_rule_s_run_the_auto_unsend_job_carries_the_rule():
    """Queued as a follow-on of the rule's run: it carries the rule id (and the
    follow-on mark), so switching the rule off cancels the unsends still waiting."""
    async def go():
        _use_fake()
        aid = "pf_unsend_rule"
        await _seed_account(aid)
        await _enable(aid, unsend_minutes=30)
        await _seed_purchase(aid, 82, 8201)
        rid = (await _rules(aid))[0].id
        token = executor._current_rule_id.set(rid)
        try:
            await _run(aid, 1)
        finally:
            executor._current_rule_id.reset(token)
        jobs = await _unsend_jobs(aid)
        assert len(jobs) == 1 and jobs[0].rule_id == rid, jobs
        assert json.loads(jobs[0].payload_json).get(executor.FOLLOWUP_MARK) is True, jobs[0].payload_json
    _sandboxed(go)


async def _unsend_jobs(aid: str) -> list[ScheduledJob]:
    async with get_session() as s:
        return list((await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == aid,
            ScheduledJob.kind == "unsend_messages"))).scalars().all())


def case_auto_unsend_queues_the_per_chat_unsend_for_a_free_message_only():
    async def go():
        fake = _use_fake()
        aid = "pf_unsend"
        await _seed_account(aid)
        await _enable(aid, unsend_minutes=90)
        await _seed_purchase(aid, 67, 6701)
        before = datetime.utcnow()
        await _run(aid, 1)
        jobs = await _unsend_jobs(aid)
        assert len(jobs) == 1, jobs
        msg_id = (await _followups(aid))[0].message_id
        assert json.loads(jobs[0].payload_json) == {
            "targets": [{"message_id": msg_id, "fan_id": 67}]}, jobs[0].payload_json
        assert before + timedelta(minutes=89) < jobs[0].run_at < datetime.utcnow() + timedelta(minutes=91)
        # A paid message is never unsent: its late buyers are real money.
        aid = "pf_unsend_ppv"
        await _seed_account(aid)
        await _enable(aid, unsend_minutes=90, media_ids=[504], price_cents=500)
        await _seed_purchase(aid, 68, 6801)
        await _run(aid, 1)
        assert len(fake.sent) == 2 and await _unsend_jobs(aid) == [], fake.sent
        # Off (0) queues nothing.
        aid = "pf_unsend_off"
        await _seed_account(aid)
        await _enable(aid)
        await _seed_purchase(aid, 69, 6901)
        await _run(aid, 1)
        assert len(fake.sent) == 3 and await _unsend_jobs(aid) == []
    _sandboxed(go)


def case_frequency_once_thanks_a_fan_once_ever_every_time_keeps_the_2h_floor():
    async def go():
        fake = _use_fake()
        aid = "pf_once"
        await _seed_account(aid)
        await _enable(aid, frequency="once")
        await _seed_purchase(aid, 70, 7001)
        assert (await _run(aid, 1)).get("sent") == 1
        await _unpause(aid)
        async with get_session() as s:
            await s.execute(update(PurchaseFollowupClaim).where(
                PurchaseFollowupClaim.account_id == aid)
                .values(created_at=datetime.utcnow() - timedelta(days=30)))
        await _seed_purchase(aid, 70, 7002)
        res = await _run(aid, 2)
        assert res.get("sent") == 0 and res.get("folded") == 1 and len(fake.sent) == 1, (res, fake.sent)
        # Back on "every time": a purchase past the 2-hour floor is thanked again.
        await _save(aid, {"frequency": "every"})
        await _seed_purchase(aid, 70, 7003)
        res = await _run(aid, 3)
        assert res.get("sent") == 1 and len(fake.sent) == 2, (res, fake.sent)
    _sandboxed(go)


def case_the_effective_and_expiry_dates_bound_what_is_sent():
    async def go():
        fake = _use_fake()
        aid = "pf_window"
        await _seed_account(aid)
        now = datetime.now(timezone.utc)
        await _enable(aid, starts_at=(now + timedelta(hours=1)).isoformat())
        await _seed_purchase(aid, 71, 7101)
        res = await _run(aid, 1)
        assert res == {"status": "skipped", "reason": "scheduled", "sent": 0}, res
        # Effective 20 minutes ago: a purchase from before it is not chased.
        await _backdate(aid, minutes=60)
        await _save(aid, {"starts_at": (now - timedelta(minutes=20)).isoformat()})
        await _seed_purchase(aid, 72, 7201, minutes_ago=30)
        await _seed_purchase(aid, 73, 7301, minutes_ago=10)
        res = await _run(aid, 2)
        # 71's purchase (made at the first sweep) is after it too.
        assert sorted(f for f, _, _ in fake.sent) == [71, 73], (res, fake.sent)
        # Past its Expiry nothing goes out.
        await _save(aid, {"starts_at": None, "ends_at": (now - timedelta(minutes=1)).isoformat()})
        await _seed_purchase(aid, 74, 7401)
        res = await _run(aid, 3)
        assert res == {"status": "skipped", "reason": "expired", "sent": 0}, res
        assert len(fake.sent) == 2
    _sandboxed(go)


def case_only_an_owner_can_switch_it_on_a_chatter_can_switch_it_off():
    async def go():
        aid = "pf_owner"
        await _seed_account(aid)
        # Refused: a chatter switching it on (nothing is written)...
        await _refused(_save(aid, {"enabled": True, "text": TEXT}, principal="chatter"), 403)
        assert await _rules(aid) == [], "a refused chatter save still wrote a rule"
        await _enable(aid)                      # the owner turns it on
        # ...or rewriting what a live rule sends.
        await _refused(_save(aid, {"text": "new words"}, principal="chatter"), 403)
        assert (await _steps(aid))["text"] == TEXT
        # A chatter may still turn it off.
        out = await _save(aid, {"enabled": False}, principal="chatter")
        assert out["config"]["enabled"] is False, out
        # And edit it while it is off.
        out = await _save(aid, {"text": "draft"}, principal="chatter")
        assert out["config"]["text"] == "draft", out
    _sandboxed(go)


def case_every_rule_of_the_kind_is_switched_and_written():
    async def go():
        aid = "pf_multi"
        await _seed_account(aid)
        await _enable(aid)
        # A second row of the kind (a generic create, or an old duplicate).
        async with get_session() as s:
            s.add(AutomationRule(account_id=aid, name="dup", kind=KIND,
                                 trigger_json='{"every_seconds": 60}',
                                 steps_json=json.dumps({"enabled": True, "text": "old"}),
                                 is_enabled=True))
        await _save(aid, {"enabled": False, "text": "parked"})
        rules = await _rules(aid)
        assert len(rules) == 2 and not any(r.is_enabled for r in rules), rules
        assert all(json.loads(r.steps_json)["text"] == "parked" for r in rules), rules
        got = await _as("owner", aid, lambda: api.get_purchase_followup_config(account_id=aid))
        assert got["config"]["enabled"] is False and got["config"]["text"] == "parked", got
        # On again: one row ticks, never a second ticker for the same kind.
        await _enable(aid)
        rules = await _rules(aid)
        assert [r.is_enabled for r in rules] == [True, False], rules
        assert all(json.loads(r.steps_json)["text"] == TEXT for r in rules), rules
    _sandboxed(go)


_harness.run(
    case_off_by_default_nothing_is_scheduled_or_sent,
    case_name_is_filled_per_fan_never_sent_literally,
    case_one_message_per_purchase_through_the_gated_paced_seam_and_never_twice,
    case_dry_run_sends_and_claims_nothing,
    case_no_id_send_is_claimed_probed_and_not_retried,
    case_a_rate_limited_send_is_released_for_a_later_sweep_other_failures_are_not,
    case_cap_limits_each_sweep_the_rest_wait_and_the_cap_is_bounded,
    case_a_busy_fan_waits_without_using_a_cap_slot,
    case_delay_holds_the_message_until_due,
    case_the_random_delay_is_drawn_once_per_purchase_inside_the_range,
    case_purchases_before_the_switch_went_on_are_not_chased,
    case_purchases_older_than_a_day_are_not_chased,
    case_an_old_purchase_flipped_late_is_not_chased,
    case_a_legacy_delay_minutes_is_kept_exact_up_to_a_day,
    case_a_mass_placeholder_is_never_thanked_and_its_adopted_row_is_thanked_once,
    case_two_fans_who_bought_the_same_message_id_are_each_thanked,
    case_a_purchase_notification_time_inside_the_window_is_proof,
    case_the_notification_purchase_time_is_never_missing_or_future,
    case_a_refunded_or_charged_back_transaction_is_not_proof,
    case_a_client_that_cannot_be_built_claims_nothing,
    case_a_fan_paused_after_the_snapshot_is_skipped_unclaimed,
    case_a_notification_for_a_row_already_flipped_paid_still_proves_the_time,
    case_a_ledger_row_or_notice_from_before_the_window_is_not_proof,
    case_the_rest_after_a_thank_you_never_shortens_a_longer_pause,
    case_the_sweep_reads_messages_through_an_index,
    case_the_claim_survives_another_writer_rewriting_custom_fields,
    case_a_job_queued_before_the_switch_went_off_sends_nothing,
    case_off_then_on_through_the_config_route_does_not_chase_purchases_made_while_off,
    case_the_generic_rule_routes_refuse_this_kind_except_switching_it_off,
    case_a_rule_without_a_readable_enable_stamp_sends_nothing,
    case_skip_listed_paused_blacklisted_and_muted_creator_fans_are_left_alone,
    case_the_include_only_audience_is_honoured,
    case_the_text_goes_out_word_restricted,
    case_end_to_end_a_switched_on_rule_is_materialised_and_run_by_the_executor,
    case_the_config_route_saves_the_rule_off_by_default_and_refuses_bad_input,
    case_media_and_a_price_go_out_with_the_message_and_its_price_is_recorded,
    case_media_of_refuses_goes_out_as_the_free_text_alone,
    case_auto_unsend_queues_the_per_chat_unsend_for_a_free_message_only,
    case_frequency_once_thanks_a_fan_once_ever_every_time_keeps_the_2h_floor,
    case_a_rule_saved_before_frequency_keeps_its_24h_floor,
    case_a_fan_who_owns_the_media_gets_the_text_alone_free,
    case_the_price_ceiling_is_of_s_and_auto_unsend_stops_inside_of_s_window,
    case_its_own_paid_thank_you_bought_is_never_a_purchase_to_thank_for,
    case_a_failed_auto_unsend_queue_never_costs_the_claim_or_the_rest,
    case_inside_a_rule_s_run_the_auto_unsend_job_carries_the_rule,
    case_the_effective_and_expiry_dates_bound_what_is_sent,
    case_only_an_owner_can_switch_it_on_a_chatter_can_switch_it_off,
    case_every_rule_of_the_kind_is_switched_and_written,
)
