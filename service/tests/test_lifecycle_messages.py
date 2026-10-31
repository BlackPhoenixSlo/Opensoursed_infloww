#!/usr/bin/env python3
"""lifecycle_messages (Smart Messages' Nearing expiry, Expired, Resubscribe and
Birthday Triggers) must send a fan ONE configured message per event and nothing
else: off by default, silent on a dry run, never twice for the same event (a
no-id send included), capped per sweep, blind to skip-listed, paused,
blacklisted and muted-creator fans, deaf to events from before the switch went
on, and unmoved by a short or empty roster read. Mocked OnlyFans only (FakeOF);
nothing reaches the network."""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

import os
import tempfile

os.environ["SETTINGS_BACKUP_DIR"] = tempfile.mkdtemp(prefix="lm_settings_backups_")
_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sqlalchemy import select, update  # noqa: E402

import auth  # noqa: E402
import chatters  # noqa: E402
import fans as fans_api  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, AutomationRule, Blacklist, Fan, LifecycleMessageClaim, Message,
    ScheduledJob, SkipList, SubscriberSnapshot, Transaction,
)
import automation_executor as executor  # noqa: E402
import automations.lifecycle_messages as lm  # noqa: E402
import lifecycle_message_config_api as api  # noqa: E402

TEXT = "hey {name}, don't go 🥺"
_REAL_MAKE_CLIENT = executor._make_client
_REAL_PACED = executor.of_write_paced
_REAL_LIMIT = lm._LIMIT
_REAL_TTL = lm._CRAWL_TTL_S
_REAL_PAGE_ALL = lm._page_all_checked


def _iso(dt: datetime) -> str:
    return dt.isoformat() + "Z"


def _sub(fid: int, *, sub: datetime, exp: datetime, renew: bool = True,
         renewed: bool = False) -> dict:
    """A row of OF's active-subscriber list."""
    return {"id": fid, "subscribedOnData": {
        "subscribeAt": _iso(sub), "expiredAt": _iso(exp),
        "status": "active" if renew else "Set to Expire",
        "renewedAt": _iso(sub) if renewed else None}}


class FakeOF:
    """Records every send; `roster` is what the active-subscriber list returns.
    `price` is the fans' own subscribePrice (None: absent, the gate's no_price),
    `refuse` the fans whose DMs OF refuses as can't-message."""
    def __init__(self, *, with_id: bool = True, subscribed: bool = True):
        self.sent: list[tuple[int, str]] = []
        self.kw: list[dict] = []          # each send's keyword arguments, in order
        self.probed: list[int] = []
        self.follows: list[int] = []
        self.discounts: list[tuple[int, int, int]] = []
        self.calls: list[str] = []
        self.crawls = 0
        self.roster: list[dict] = []
        self.with_id = with_id
        self.subscribed = subscribed
        self.price: float | None = None
        self.refuse: set[int] = set()
        self.discount_error: str | None = None
        self._next_id = 9_100_000_000_000

    def follow_user(self, fan_id):
        self.calls.append("follow")
        self.follows.append(int(fan_id))
        return {"success": True}

    def resubscribe_user(self, fan_id):
        return self.follow_user(fan_id)

    def set_subscription_discount(self, user_id, discount, period):
        self.calls.append("discount")
        if self.discount_error:
            raise RuntimeError(self.discount_error)
        self.discounts.append((int(user_id), int(discount), int(period)))
        return {"id": int(user_id)}

    def subscribers(self, *, type="active", limit=10, offset=0, **kw):
        if offset == 0:
            self.crawls += 1
        page = self.roster[offset:offset + limit]
        return {"list": page, "hasMore": offset + limit < len(self.roster)}

    def send_message(self, chat_id, text, **kw):
        self.calls.append("send")
        if int(chat_id) in self.refuse:
            raise RuntimeError("400 Cannot send message to this user")
        self._next_id += 1
        self.sent.append((int(chat_id), text))
        self.kw.append(kw)
        if not self.with_id:
            return {"success": True}
        return {"id": self._next_id, "text": f"<p>{text}</p>",
                "createdAt": "2026-06-01T12:30:00+00:00"}

    def get_user(self, fan_id):
        self.probed.append(int(fan_id))
        u = {"id": int(fan_id), "subscribedOn": "2026-01-01" if self.subscribed else None}
        if self.price is not None:
            u["subscribePrice"] = self.price
        return u


PURPOSES: list[str | None] = []


async def _unpaced(account_id, fn, **kw):
    PURPOSES.append(kw.get("send_purpose"))
    return await _REAL_PACED(account_id, fn, **{**kw, "min_gap_s": 0.0, "pause_s": 0.0})


def _use_fake(**kw) -> FakeOF:
    fake = FakeOF(**kw)
    executor._make_client = lambda account_id: fake
    executor.of_write_paced = _unpaced
    PURPOSES.clear()
    return fake


def _sandboxed(go) -> None:
    try:
        asyncio.run(go())
    finally:
        executor._make_client = _REAL_MAKE_CLIENT
        executor.of_write_paced = _REAL_PACED
        lm._LIMIT = _REAL_LIMIT
        lm._CRAWL_TTL_S = _REAL_TTL
        lm._page_all_checked = _REAL_PAGE_ALL


async def _as(principal: str, aid: str, coro_fn):
    ids = frozenset({aid})
    if principal == "owner":
        tok_u = auth._request_user.set(auth.AuthedUser("u-lm-owner", "lm_owner", ids))
        tok_c = chatters._request_chatter.set(None)
    else:
        tok_u = auth._request_user.set(None)
        tok_c = chatters._request_chatter.set(chatters.ChatterIdentity(
            "c-lm", "lm_chatter", None, None, frozenset({"u-lm-owner"}), ids))
    try:
        return await coro_fn()
    finally:
        auth._request_user.reset(tok_u)
        chatters._request_chatter.reset(tok_c)


async def _refused(coro, status: int) -> None:
    try:
        await coro
    except HTTPException as e:
        assert e.status_code == status, (e.status_code, e.detail)
    else:
        raise AssertionError(f"expected {status}")


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _seed_fan(aid: str, fid: int, **kw) -> None:
    async with get_session() as s:
        if await s.get(Fan, (aid, fid)) is None:
            s.add(Fan(account_id=aid, fan_id=fid, **kw))


async def _save(aid: str, kind: str, config: dict, *, principal: str = "owner") -> dict:
    return await _as(principal, aid, lambda: api.put_lifecycle_message_config(
        api._ConfigBody(account_id=aid, kind=kind, config=config)))


async def _rules(aid: str, kind: str) -> list[AutomationRule]:
    async with get_session() as s:
        return list((await s.execute(select(AutomationRule).where(
            AutomationRule.account_id == aid, AutomationRule.kind == kind)
            .order_by(AutomationRule.id))).scalars().all())


async def _steps(aid: str, kind: str) -> dict:
    return json.loads((await _rules(aid, kind))[0].steps_json)


async def _enable(aid: str, kind: str, *, hours_ago: float = 0, **extra) -> None:
    """On through the config route; `hours_ago` backdates the switch."""
    await _save(aid, kind, {"enabled": True, "text": TEXT, **extra})
    if hours_ago:
        at = (datetime.utcnow() - timedelta(hours=hours_ago)).isoformat()
        async with get_session() as s:
            for rule in (await s.execute(select(AutomationRule).where(
                    AutomationRule.account_id == aid, AutomationRule.kind == kind))).scalars():
                steps = json.loads(rule.steps_json)
                steps["enabled_at"] = at
                rule.steps_json = json.dumps(steps)


async def _age_crawl(aid: str, minutes: float = 30) -> None:
    """Make the last roster crawl `minutes` older so the next sweep crawls again."""
    async with get_session() as s:
        for r in (await s.execute(select(SubscriberSnapshot).where(
                SubscriberSnapshot.account_id == aid))).scalars():
            r.seen_at = r.seen_at - timedelta(minutes=minutes)


async def _unpause(aid: str) -> None:
    async with get_session() as s:
        await s.execute(update(Fan).where(Fan.account_id == aid)
                        .values(automation_paused_until=None))


async def _sent_rows(aid: str, kind: str) -> list[Message]:
    async with get_session() as s:
        return list((await s.execute(select(Message).where(
            Message.account_id == aid, Message.automation_kind == kind))).scalars().all())


async def _run(kind: str, aid: str, **payload) -> dict:
    return await lm.sweep(kind, aid, payload)


def _today_mmdd() -> str:
    return datetime.utcnow().strftime("%m-%d")


# ── cases ─────────────────────────────────────────────────────────────

def case_off_by_default_nothing_is_read_or_sent():
    async def go():
        fake = _use_fake()
        aid = "lm_default"
        await _seed_account(aid)
        await _seed_fan(aid, 1, birthday=_today_mmdd())
        for kind in lm.KINDS:
            got = await _as("owner", aid, lambda: api.get_lifecycle_message_config(
                account_id=aid, kind=kind))
            assert got["config"]["enabled"] is False, got
            res = await _run(kind, aid)
            assert res == {"status": "skipped", "reason": "disabled", "sent": 0}, res
        assert fake.sent == [] and fake.crawls == 0, (fake.sent, fake.crawls)
        # The registered entry points are the same sweep.
        res = await lm.run_birthday(aid, {}, run_id=1)
        assert res.get("reason") == "disabled", res
    _sandboxed(go)


def case_nearing_expiry_messages_non_renewing_fans_inside_the_window_once():
    async def go():
        fake = _use_fake()
        aid = "lm_expiry"
        now = datetime.utcnow()
        await _seed_account(aid)
        for fid in (11, 12, 13, 14):
            await _seed_fan(aid, fid, real_name="Rob Smith", is_name_real=True)
        fake.roster = [
            _sub(11, sub=now - timedelta(days=20), exp=now + timedelta(hours=10), renew=False),
            _sub(12, sub=now - timedelta(days=20), exp=now + timedelta(hours=10), renew=True),
            _sub(13, sub=now - timedelta(days=20), exp=now + timedelta(hours=50), renew=False),
            _sub(14, sub=now - timedelta(days=20), exp=now + timedelta(hours=6), renew=False),
        ]
        await _enable(aid, lm.EXPIRY, hours_ago=20, hours=24)
        res = await _run(lm.EXPIRY, aid)
        # 11 and 14: not renewing, inside 24h. 12 renews; 13 is two days out.
        assert sorted(f for f, _ in fake.sent) == [11, 14], (res, fake.sent)
        assert fake.sent[0][1] == "hey Rob, don't go 🥺", fake.sent
        assert PURPOSES == ["gated", "gated"], PURPOSES
        assert res.get("roster") == "crawled" and res.get("listed") == 4, res
        assert sorted(r.fan_id for r in await _sent_rows(aid, lm.EXPIRY)) == [11, 14]
        # Never twice for the same expiry, and the cached crawl is reused.
        await _unpause(aid)
        res = await _run(lm.EXPIRY, aid)
        assert res.get("sent") == 0 and len(fake.sent) == 2, (res, fake.sent)
        assert res.get("roster") == "fresh" and fake.crawls == 1, (res, fake.crawls)
    _sandboxed(go)


def case_nearing_expiry_does_not_chase_a_window_entered_before_the_switch():
    async def go():
        fake = _use_fake()
        aid = "lm_expiry_late"
        now = datetime.utcnow()
        await _seed_account(aid)
        await _seed_fan(aid, 15)
        # Expires in 10h of a 24h window: the window opened 14h ago, before the switch.
        fake.roster = [_sub(15, sub=now - timedelta(days=20), exp=now + timedelta(hours=10),
                            renew=False)]
        await _enable(aid, lm.EXPIRY, hours=24)
        res = await _run(lm.EXPIRY, aid)
        assert res.get("sent") == 0 and fake.sent == [], (res, fake.sent)
    _sandboxed(go)


def case_nearing_expiry_reaches_a_fan_who_turns_renewal_off_late_in_a_long_window():
    async def go():
        fake = _use_fake()
        aid = "lm_expiry_renew_off"
        now = datetime.utcnow()
        await _seed_account(aid)
        await _seed_fan(aid, 16)
        # A 72h window, on for four days. He expires in 10h, so his window opened
        # 62h ago, and he only switched renewal off now: still worth the message.
        fake.roster = [_sub(16, sub=now - timedelta(days=20), exp=now + timedelta(hours=10),
                            renew=True)]
        await _enable(aid, lm.EXPIRY, hours_ago=96, hours=72)
        res = await _run(lm.EXPIRY, aid)
        assert res.get("sent") == 0, res
        await _age_crawl(aid)
        fake.roster = [_sub(16, sub=now - timedelta(days=20), exp=now + timedelta(hours=10),
                            renew=False)]
        res = await _run(lm.EXPIRY, aid)
        assert [f for f, _ in fake.sent] == [16], (res, fake.sent)
    _sandboxed(go)


def case_expired_messages_fans_gone_from_a_complete_crawl_n_hours_after_expiry():
    async def go():
        fake = _use_fake()
        aid = "lm_expired"
        now = datetime.utcnow()
        await _seed_account(aid)
        for fid in (21, 22, 23):
            await _seed_fan(aid, fid)
        fake.roster = [
            _sub(21, sub=now - timedelta(days=40), exp=now - timedelta(hours=30)),
            _sub(22, sub=now - timedelta(days=40), exp=now + timedelta(days=5)),
            _sub(23, sub=now - timedelta(days=40), exp=now - timedelta(hours=5)),
        ]
        await _enable(aid, lm.EXPIRED, hours_ago=20, hours=24)
        res = await _run(lm.EXPIRED, aid)
        assert res.get("sent") == 0, res          # everyone is still listed
        # Next crawl: 21 and 23 are gone. 21 expired 30h ago (> 24h); 23 only 5h ago.
        await _age_crawl(aid)
        fake.roster = [fake.roster[1]]
        res = await _run(lm.EXPIRED, aid)
        assert [f for f, _ in fake.sent] == [21], (res, fake.sent)
        assert fake.sent[0][1] == "hey babe, don't go 🥺", fake.sent   # no known name
        await _unpause(aid)
        res = await _run(lm.EXPIRED, aid)
        assert len(fake.sent) == 1, fake.sent
    _sandboxed(go)


def case_a_truncated_or_empty_crawl_changes_nothing():
    async def go():
        fake = _use_fake()
        aid = "lm_trunc"
        now = datetime.utcnow()
        await _seed_account(aid)
        await _seed_fan(aid, 31)
        await _seed_fan(aid, 32)
        fake.roster = [_sub(31, sub=now - timedelta(days=40), exp=now - timedelta(hours=30)),
                       _sub(32, sub=now - timedelta(days=40), exp=now + timedelta(days=5))]
        await _enable(aid, lm.EXPIRED, hours_ago=20)
        await _run(lm.EXPIRED, aid)
        # An empty read is not "everyone expired".
        await _age_crawl(aid)
        fake.roster = []
        res = await _run(lm.EXPIRED, aid)
        assert res.get("roster") == "empty" and fake.sent == [], (res, fake.sent)
        # Nor is a read that hit the page backstop.
        lm._page_all_checked = lambda fetch: ([_sub(32, sub=now - timedelta(days=40),
                                                    exp=now + timedelta(days=5))], True)
        res = await _run(lm.EXPIRED, aid)
        assert res.get("roster") == "truncated" and fake.sent == [], (res, fake.sent)
        async with get_session() as s:
            seen = {r.fan_id: r.seen_at for r in (await s.execute(select(SubscriberSnapshot).where(
                SubscriberSnapshot.account_id == aid))).scalars()}
        assert seen[31] == seen[32], seen         # neither unusable crawl was written
    _sandboxed(go)


def case_resubscribe_on_return_after_a_lapse_and_on_a_known_fans_fresh_start():
    async def go():
        fake = _use_fake()
        aid = "lm_resub"
        now = datetime.utcnow()
        await _seed_account(aid)
        await _seed_fan(aid, 41)
        await _seed_fan(aid, 42)
        await _seed_fan(aid, 43, created_at=now - timedelta(days=30))   # known before
        await _seed_fan(aid, 44, created_at=now - timedelta(hours=3))   # brand new fan
        await _seed_fan(aid, 45, created_at=now - timedelta(days=30))   # a renewal
        await _enable(aid, lm.RESUBSCRIBE, hours_ago=20)
        fake.roster = [_sub(41, sub=now - timedelta(days=60), exp=now + timedelta(days=1)),
                       _sub(42, sub=now - timedelta(days=60), exp=now + timedelta(days=9))]
        res = await _run(lm.RESUBSCRIBE, aid)
        assert res.get("sent") == 0, res
        await _age_crawl(aid)
        fake.roster = [fake.roster[1]]            # 41 lapsed
        await _run(lm.RESUBSCRIBE, aid)
        await _age_crawl(aid)
        fake.roster = [
            _sub(41, sub=now - timedelta(hours=1), exp=now + timedelta(days=30)),   # back
            fake.roster[0],
            _sub(43, sub=now - timedelta(hours=2), exp=now + timedelta(days=30)),
            _sub(44, sub=now - timedelta(hours=2), exp=now + timedelta(days=30)),
            _sub(45, sub=now - timedelta(hours=2), exp=now + timedelta(days=30), renewed=True),
        ]
        res = await _run(lm.RESUBSCRIBE, aid)
        assert sorted(f for f, _ in fake.sent) == [41, 43], (res, fake.sent)
        await _unpause(aid)
        await _age_crawl(aid)
        res = await _run(lm.RESUBSCRIBE, aid)
        assert len(fake.sent) == 2, (res, fake.sent)
    _sandboxed(go)


def case_birthday_greets_fans_whose_birthday_is_today_once_a_year():
    async def go():
        fake = _use_fake()
        aid = "lm_bday"
        await _seed_account(aid)
        await _seed_fan(aid, 51, birthday=_today_mmdd(), fan_chosen_nickname="Bobby")
        other = (datetime.utcnow() + timedelta(days=3)).strftime("%m-%d")
        await _seed_fan(aid, 52, birthday=other)
        await _seed_fan(aid, 53)
        await _enable(aid, lm.BIRTHDAY)
        res = await _run(lm.BIRTHDAY, aid)
        assert fake.sent == [(51, "hey Bobby, don't go 🥺")], (res, fake.sent)
        assert fake.crawls == 0, "the birthday sweep read the roster"
        async with get_session() as s:
            keys = (await s.execute(select(LifecycleMessageClaim.event_key).where(
                LifecycleMessageClaim.account_id == aid))).scalars().all()
        assert keys == [str(datetime.utcnow().year)], keys
        await _unpause(aid)
        res = await _run(lm.BIRTHDAY, aid)
        assert res.get("sent") == 0 and len(fake.sent) == 1, (res, fake.sent)
    _sandboxed(go)


async def _claim_last_year(aid: str, fid: int) -> None:
    async with get_session() as s:
        s.add(LifecycleMessageClaim(account_id=aid, kind=lm.BIRTHDAY, fan_id=fid,
                                    event_key=str(datetime.utcnow().year - 1)))


def case_frequency_once_greets_a_fan_once_ever_every_time_once_per_event():
    """"Send only once when the fan matches the trigger": a fan greeted on last
    year's birthday is not greeted again. "Every time": each birthday."""
    async def go():
        fake = _use_fake()
        aid = "lm_freq"
        await _seed_account(aid)
        for fid in (55, 56):
            await _seed_fan(aid, fid, birthday=_today_mmdd())
            await _claim_last_year(aid, fid)
        await _seed_fan(aid, 57, birthday=_today_mmdd())
        await _enable(aid, lm.BIRTHDAY)                  # Infloww's start: once
        res = await _run(lm.BIRTHDAY, aid)
        assert [f for f, _ in fake.sent] == [57], (res, fake.sent)
        await _save(aid, lm.BIRTHDAY, {"frequency": "every"})
        res = await _run(lm.BIRTHDAY, aid)
        assert sorted(f for f, _ in fake.sent) == [55, 56, 57], (res, fake.sent)
    _sandboxed(go)


def case_the_effective_and_expiry_dates_bound_what_is_sent():
    async def go():
        fake = _use_fake()
        aid = "lm_window"
        now = datetime.utcnow()
        await _seed_account(aid)
        await _seed_fan(aid, 58, birthday=_today_mmdd())
        await _enable(aid, lm.BIRTHDAY, starts_at=_iso(now + timedelta(hours=2)))
        res = await _run(lm.BIRTHDAY, aid)
        assert res == {"status": "skipped", "reason": "scheduled", "sent": 0}, res
        await _save(aid, lm.BIRTHDAY, {"starts_at": None, "ends_at": _iso(now - timedelta(minutes=5))})
        res = await _run(lm.BIRTHDAY, aid)
        assert res == {"status": "skipped", "reason": "expired", "sent": 0}, res
        assert fake.sent == [] and fake.crawls == 0, fake.sent
        # An Effective date later than the switch starts the window there: a
        # Nearing expiry window opened before it is not chased.
        aid = "lm_window_expiry"
        await _seed_account(aid)
        await _seed_fan(aid, 59)
        fake.roster = [_sub(59, sub=now - timedelta(days=20), exp=now + timedelta(hours=10),
                            renew=False)]
        await _enable(aid, lm.EXPIRY, hours_ago=48, hours=24,
                      starts_at=_iso(now - timedelta(hours=1)))
        res = await _run(lm.EXPIRY, aid)
        assert res.get("sent") == 0 and fake.sent == [], (res, fake.sent)
    _sandboxed(go)


async def _unsend_jobs(aid: str) -> list[ScheduledJob]:
    async with get_session() as s:
        return list((await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == aid,
            ScheduledJob.kind == "unsend_messages"))).scalars().all())


def case_media_a_price_and_auto_unsend_ride_on_the_message():
    async def go():
        fake = _use_fake()
        aid = "lm_media"
        await _seed_account(aid)
        await _seed_fan(aid, 61, birthday=_today_mmdd())
        await _enable(aid, lm.BIRTHDAY, media_ids=[801, 802], price_cents=1200,
                      unsend_minutes=60)
        await _run(lm.BIRTHDAY, aid)
        assert fake.kw == [{"media_files": [801, 802], "price": 12.0}], fake.kw
        assert [r.price_cents for r in await _sent_rows(aid, lm.BIRTHDAY)] == [1200]
        # A PPV is never auto-unsent.
        assert await _unsend_jobs(aid) == []
        aid = "lm_media_free"
        await _seed_account(aid)
        await _seed_fan(aid, 62, birthday=_today_mmdd())
        await _enable(aid, lm.BIRTHDAY, media_ids=[803], unsend_minutes=60)
        await _run(lm.BIRTHDAY, aid)
        assert fake.kw[-1] == {"media_files": [803]}, fake.kw
        jobs = await _unsend_jobs(aid)
        msg_id = (await _sent_rows(aid, lm.BIRTHDAY))[0].message_id
        assert len(jobs) == 1 and json.loads(jobs[0].payload_json) == {
            "targets": [{"message_id": msg_id, "fan_id": 62}]}, jobs
        assert jobs[0].run_at > datetime.utcnow() + timedelta(minutes=59), jobs[0].run_at
    _sandboxed(go)


def case_under_once_a_forced_test_is_never_held_back_and_never_counts():
    """A `force_ids` run is the operator's test, not the event: "once" does not
    skip a fan already greeted, and the test's claim does not use up his once."""
    async def go():
        fake = _use_fake()
        aid = "lm_once_forced"
        await _seed_account(aid)
        await _seed_fan(aid, 58, birthday=_today_mmdd())
        await _claim_last_year(aid, 58)
        await _seed_fan(aid, 59, birthday=_today_mmdd())
        await _enable(aid, lm.BIRTHDAY)                  # once
        res = await _run(lm.BIRTHDAY, aid, force_ids=[58, 59])
        assert sorted(f for f, _ in fake.sent) == [58, 59], (res, fake.sent)
        await _unpause(aid)
        # The real birthday sweep: 58 had his once last year; 59's was only a test.
        res = await _run(lm.BIRTHDAY, aid)
        assert sorted(f for f, _ in fake.sent) == [58, 59, 59], (res, fake.sent)
    _sandboxed(go)


def case_a_fan_who_owns_the_media_gets_the_text_alone_free():
    async def go():
        fake = _use_fake()
        aid = "lm_owner"
        await _seed_account(aid)
        await _seed_fan(aid, 63, birthday=_today_mmdd())
        async with get_session() as s:
            s.add(Message(account_id=aid, fan_id=63, message_id=6300, direction="out",
                          body="older set", price_cents=900, is_paid=True,
                          media_ids="[805]", created_at=datetime.utcnow() - timedelta(days=9)))
        await _seed_fan(aid, 64, birthday=_today_mmdd())
        await _enable(aid, lm.BIRTHDAY, media_ids=[804, 805], price_cents=1200)
        res = await _run(lm.BIRTHDAY, aid)
        assert res.get("sent") == 2 and res.get("owners_sent_free") == 1, res
        by_fan = dict(zip([f for f, _ in fake.sent], fake.kw))
        assert by_fan == {63: {"media_files": []},
                          64: {"media_files": [804, 805], "price": 12.0}}, by_fan
        rows = {r.fan_id: r.price_cents for r in await _sent_rows(aid, lm.BIRTHDAY)}
        assert rows == {63: 0, 64: 1200}, rows
    _sandboxed(go)


def case_dry_run_sends_and_claims_nothing():
    async def go():
        fake = _use_fake()
        aid = "lm_dry"
        await _seed_account(aid)
        await _seed_fan(aid, 61, birthday=_today_mmdd())
        await _enable(aid, lm.BIRTHDAY)
        res = await _run(lm.BIRTHDAY, aid, dry_run=True)
        assert res.get("dry_run") is True and res.get("would_send") == 1, res
        assert fake.sent == [] and await _sent_rows(aid, lm.BIRTHDAY) == []
        res = await _run(lm.BIRTHDAY, aid)
        assert res.get("sent") == 1, res
        await _unpause(aid)
        res = await _run(lm.BIRTHDAY, aid, dry_run=True)
        assert res.get("would_send") == 0, res
    _sandboxed(go)


def case_no_id_send_is_claimed_probed_and_not_retried():
    async def go():
        fake = _use_fake(with_id=False, subscribed=False)
        aid = "lm_noid"
        await _seed_account(aid)
        await _seed_fan(aid, 71, birthday=_today_mmdd())
        await _enable(aid, lm.BIRTHDAY)
        res = await _run(lm.BIRTHDAY, aid)
        assert res.get("no_id") == 1 and len(fake.sent) == 1, (res, fake.sent)
        assert await _sent_rows(aid, lm.BIRTHDAY) == []
        assert fake.probed == [71], fake.probed
        async with get_session() as s:
            assert (await s.get(Fan, (aid, 71))).subscription_status == "expired"
        await _unpause(aid)
        await _run(lm.BIRTHDAY, aid)
        assert len(fake.sent) == 1, f"a no-id event was messaged again: {fake.sent}"
    _sandboxed(go)


def case_cap_limits_each_sweep_and_the_rest_wait():
    async def go():
        fake = _use_fake()
        aid = "lm_cap"
        await _seed_account(aid)
        for fid in (81, 82):
            await _seed_fan(aid, fid, birthday=_today_mmdd())
        await _enable(aid, lm.BIRTHDAY)
        lm._LIMIT = 1
        res = await _run(lm.BIRTHDAY, aid)
        assert res.get("sent") == 1 and res.get("capped") == 1, res
        res = await _run(lm.BIRTHDAY, aid)
        assert sorted(f for f, _ in fake.sent) == [81, 82], (res, fake.sent)
        lm._LIMIT = _REAL_LIMIT
        assert lm._LIMIT == 25
        for i in range(26):
            await _seed_fan(aid, 8300 + i, birthday=_today_mmdd())
        res = await _run(lm.BIRTHDAY, aid)
        assert res.get("sent") == 25 and res.get("capped") == 1, res
    _sandboxed(go)


def case_force_ids_skips_the_roster_but_not_the_gates_or_the_claim():
    async def go():
        fake = _use_fake()
        aid = "lm_force"
        await _seed_account(aid)
        await _seed_fan(aid, 91)
        await _seed_fan(aid, 92)
        async with get_session() as s:
            s.add(SkipList(account_id=aid, fan_id=92, reason="manual_restrict"))
        await _enable(aid, lm.EXPIRY)
        res = await _run(lm.EXPIRY, aid, force_ids=[91, 92])
        assert [f for f, _ in fake.sent] == [91], (res, fake.sent)
        assert res.get("skipped") == 1 and fake.crawls == 0, (res, fake.crawls)
        await _unpause(aid)
        res = await _run(lm.EXPIRY, aid, force_ids=[91])
        assert len(fake.sent) == 1, "a forced fan was messaged twice the same day"
    _sandboxed(go)


def case_skip_listed_paused_blacklisted_and_muted_creator_fans_are_left_alone():
    async def go():
        fake = _use_fake()
        aid = "lm_skip"
        today = _today_mmdd()
        await _seed_account(aid)
        await _seed_fan(aid, 101, birthday=today)
        await _seed_fan(aid, 102, birthday=today,
                        automation_paused_until=datetime.utcnow() + timedelta(hours=1))
        await _seed_fan(aid, 103, birthday=today)
        await _seed_fan(aid, 104, birthday=today)
        await _seed_fan(aid, 105, birthday=today, is_muted=True, source="creator_we_follow")
        async with get_session() as s:
            s.add(SkipList(account_id=aid, fan_id=101, reason="manual_restrict"))
            s.add(Blacklist(fan_id=103, reason="test"))
        await _enable(aid, lm.BIRTHDAY)
        res = await _run(lm.BIRTHDAY, aid)
        assert [f for f, _ in fake.sent] == [104], (res, fake.sent)
        assert res.get("skipped") == 4, res
    _sandboxed(go)


def case_the_config_route_validates_and_only_an_owner_switches_it_on():
    async def go():
        _use_fake()
        aid = "lm_cfg"
        await _seed_account(aid)
        got = await _as("owner", aid, lambda: api.get_lifecycle_message_config(
            account_id=aid, kind=lm.EXPIRED))
        # Infloww's start: send only once, free, no dates, no Auto-unsend.
        assert got["defaults"] == got["config"] == {
            "enabled": False, "text": "", "hours": 24, "messages": [], "frequency": "once",
            "media_ids": [], "price_cents": 0, "starts_at": None, "ends_at": None,
            "unsend_minutes": 0}, got
        got = await _as("owner", aid, lambda: api.get_lifecycle_message_config(
            account_id=aid, kind=lm.BIRTHDAY))
        assert got["config"]["hours"] is None, got
        await _refused(_as("owner", aid, lambda: api.get_lifecycle_message_config(
            account_id=aid, kind="nope")), 422)
        # Infloww's bounds: Expired 12..120, Nearing expiry 1..120, whole hours.
        for kind, bad in ((lm.EXPIRED, 11), (lm.EXPIRED, 121), (lm.EXPIRY, 0),
                          (lm.EXPIRY, 2.5), (lm.EXPIRY, True)):
            await _refused(_save(aid, kind, {"hours": bad}), 422)
        for bad in ({"frequency": "every_time"}, {"media_ids": [-1]}, {"price_cents": 100},
                    {"price_cents": 500}, {"unsend_minutes": 2000}, {"starts_at": "tomorrow"},
                    {"starts_at": "2026-07-02T00:00:00Z", "ends_at": "2026-07-01T00:00:00Z"}):
            await _refused(_save(aid, lm.EXPIRY, bad), 422)
        out = await _save(aid, lm.EXPIRY, {"hours": 1})
        assert out["config"] == {
            "enabled": False, "text": "", "hours": 1, "messages": [], "frequency": "once",
            "media_ids": [], "price_cents": 0, "starts_at": None, "ends_at": None,
            "unsend_minutes": 0}, out
        out = await _save(aid, lm.EXPIRY, {"media_ids": [3], "price_cents": 900,
                                           "frequency": "every", "unsend_minutes": 15,
                                           "ends_at": "2026-12-31T23:00:00Z"})
        cfg = out["config"]
        assert (cfg["media_ids"], cfg["price_cents"], cfg["frequency"], cfg["unsend_minutes"],
                cfg["ends_at"], cfg["hours"]) == (
            [3], 900, "every", 15, "2026-12-31T23:00:00+00:00", 1), cfg
        # A rule saved before `frequency` existed reads (and runs) "every".
        async with get_session() as s:
            rule = (await s.execute(select(AutomationRule).where(
                AutomationRule.account_id == aid, AutomationRule.kind == lm.EXPIRY))).scalar_one()
            steps = json.loads(rule.steps_json)
            steps.pop("frequency")
            rule.steps_json = json.dumps(steps)
        got = await _as("owner", aid, lambda: api.get_lifecycle_message_config(
            account_id=aid, kind=lm.EXPIRY))
        assert got["config"]["frequency"] == "every", got
        await _save(aid, lm.EXPIRY, {"media_ids": [], "price_cents": 0, "unsend_minutes": 0,
                                     "ends_at": None})
        # On needs a text; a chatter may save it off but never switch it on.
        await _refused(_save(aid, lm.EXPIRY, {"enabled": True}), 422)
        await _refused(_save(aid, lm.EXPIRY, {"enabled": True, "text": TEXT},
                             principal="chatter"), 403)
        out = await _save(aid, lm.EXPIRY, {"enabled": True, "text": TEXT})
        assert out["config"]["enabled"] is True and out["config"]["hours"] == 1, out
        first = (await _steps(aid, lm.EXPIRY))["enabled_at"]
        rule = (await _rules(aid, lm.EXPIRY))[0]
        assert json.loads(rule.trigger_json) == {"every_seconds": 1800}, rule.trigger_json
        out = await _save(aid, lm.EXPIRY, {"enabled": False}, principal="chatter")
        assert out["config"]["enabled"] is False, out
        await asyncio.sleep(0.01)
        await _save(aid, lm.EXPIRY, {"enabled": True, "text": TEXT})
        assert (await _steps(aid, lm.EXPIRY))["enabled_at"] > first, "off→on did not restamp"
        assert len(await _rules(aid, lm.EXPIRY)) == 1
    _sandboxed(go)


def case_a_free_page_cannot_switch_on_the_paid_only_triggers():
    """Infloww's `isPaidAutoRules`: Nearing expiry, Expired and Resubscribe are
    refused on a free-subscription page; Birthday is not, saving off never is,
    and a page whose tier cannot be read is not refused."""
    async def go():
        import account_page
        fake = _use_fake()
        aid = "lm_free"
        await _seed_account(aid)
        fake.me = lambda: {"subscribePrice": 0}
        account_page.invalidate(aid)
        for kind in sorted(lm.PAID_ONLY):
            try:
                await _save(aid, kind, {"enabled": True, "text": TEXT})
            except HTTPException as e:
                assert e.status_code == 422, e
                assert e.detail == "This Creator is a free subscription profile and is unable to create this message", e.detail
            else:
                raise AssertionError(f"{kind} switched on for a free page")
            assert (await _save(aid, kind, {"enabled": False, "text": TEXT}))["config"]["enabled"] is False
        assert (await _save(aid, lm.BIRTHDAY, {"enabled": True, "text": TEXT}))["config"]["enabled"] is True

        fake.me = lambda: {"subscribePrice": 9.99}
        account_page.invalidate(aid)
        assert (await _save(aid, lm.EXPIRY, {"enabled": True, "text": TEXT}))["config"]["enabled"] is True
        account_page.invalidate(aid)
    _sandboxed(go)


def case_the_generic_switch_refuses_to_turn_these_kinds_on():
    async def go():
        import automation_rules_api as rules_api
        aid = "lm_generic"
        await _seed_account(aid)
        for kind in lm.KINDS:
            await _enable(aid, kind)
            await _save(aid, kind, {"enabled": False})
            try:
                await _as("owner", aid, lambda: rules_api.switch_kind(rules_api.KindSwitch(
                    account_id=aid, kind=kind, enable=True)))
            except HTTPException as e:
                assert e.status_code == 409, e
                assert "/admin/lifecycle-message-config" in str(e.detail), e.detail
            else:
                raise AssertionError(f"the generic switch turned {kind} on")
            assert not any(r.is_enabled for r in await _rules(aid, kind))
        # Switching OFF through it is always let through.
        await _enable(aid, lm.BIRTHDAY)
        await _as("chatter", aid, lambda: rules_api.switch_kind(rules_api.KindSwitch(
            account_id=aid, kind=lm.BIRTHDAY, enable=False)))
        assert not any(r.is_enabled for r in await _rules(aid, lm.BIRTHDAY))
    _sandboxed(go)


def case_the_fan_birthday_is_set_as_mm_dd_and_cleared_with_empty():
    async def go():
        aid = "lm_fanpatch"
        await _seed_account(aid)
        await _seed_fan(aid, 111)
        for bad in ("2-30", "13-01", "02-30", "1990-02-03", "feb 3"):
            try:
                fans_api.FanUpdateBody(birthday=bad)
            except ValidationError:
                pass
            else:
                raise AssertionError(f"accepted birthday {bad!r}")
        out = await _as("owner", aid, lambda: fans_api.update_fan(
            aid, 111, fans_api.FanUpdateBody(birthday="02-29")))
        assert out["birthday"] == "02-29", out
        out = await _as("owner", aid, lambda: fans_api.update_fan(
            aid, 111, fans_api.FanUpdateBody(birthday="")))
        assert out["birthday"] is None, out
    _sandboxed(go)


def case_end_to_end_a_switched_on_rule_is_materialised_and_run_by_the_executor():
    async def go():
        fake = _use_fake()
        aid = "lm_e2e"
        await _seed_account(aid)
        await _seed_fan(aid, 121, birthday=_today_mmdd())
        await _enable(aid, lm.BIRTHDAY)
        await executor._materialize_due_rules()
        async with get_session() as s:
            jobs = (await s.execute(select(ScheduledJob).where(
                ScheduledJob.account_id == aid, ScheduledJob.kind == lm.BIRTHDAY,
                ScheduledJob.status == "pending"))).scalars().all()
        assert len(jobs) == 1, jobs
        res = await executor.run_once(aid, lm.BIRTHDAY)
        assert res.get("status") == "ok" and res.get("sent") == 1, res
        assert [f for f, _ in fake.sent] == [121], fake.sent
    _sandboxed(go)


def _paid_page(fake: FakeOF, aid: str) -> None:
    """OnlyFans reports the page at $9.99 (a discount's cap reads it)."""
    import account_page
    fake.me = lambda: {"subscribePrice": 9.99}
    account_page.invalidate(aid)


async def _follow_up_jobs(aid: str, kind: str) -> list[ScheduledJob]:
    async with get_session() as s:
        return list((await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == aid, ScheduledJob.kind == kind,
            ScheduledJob.status == "pending",
            ScheduledJob.payload_json.contains('"follow_up"')).order_by(ScheduledJob.id))).scalars())


async def _take_follow_up(aid: str, kind: str) -> dict:
    """The pending follow-up job's payload, marked done, as the executor would."""
    job = (await _follow_up_jobs(aid, kind))[0]
    async with get_session() as s:
        (await s.get(ScheduledJob, job.id)).status = "done"
    return json.loads(job.payload_json)


def case_a_trigger_picks_one_of_its_messages_and_one_variant_seeded_per_event():
    async def go():
        fake = _use_fake()
        aid = "lm_pick"
        await _seed_account(aid)
        for fid in range(200, 220):
            await _seed_fan(aid, fid, birthday=_today_mmdd())
        messages = [{"variants": ["a1", "a2"]}, {"variants": ["b1", "b2", "b3"]}]
        await _save(aid, lm.BIRTHDAY, {"enabled": True, "messages": messages})
        res = await _run(lm.BIRTHDAY, aid)
        assert res.get("sent") == 20, res
        texts = {t for _, t in fake.sent}
        assert texts <= {"a1", "a2", "b1", "b2", "b3"} and len(texts) >= 4, texts
        async with get_session() as s:
            claims = {c.fan_id: c for c in (await s.execute(select(LifecycleMessageClaim).where(
                LifecycleMessageClaim.account_id == aid))).scalars()}
        for fid, text in fake.sent:
            c = claims[fid]
            assert text in messages[c.message_idx]["variants"], (fid, text, c.message_idx)
            # Seeded on (fan, event): the same event picks the same text again.
            idx = lm.pick(range(2), lm.BIRTHDAY, aid, fid, c.event_key, "message")
            assert idx == c.message_idx
            assert lm.pick(messages[idx]["variants"], lm.BIRTHDAY, aid, fid, c.event_key) == text
        # The list view's text is the first message's first variant.
        assert (await _steps(aid, lm.BIRTHDAY))["text"] == "a1"
    _sandboxed(go)


def case_follow_ups_go_out_in_order_and_stop_for_good_on_a_reply():
    async def go():
        fake = _use_fake()
        aid = "lm_seq"
        await _seed_account(aid)
        await _seed_fan(aid, 301, birthday=_today_mmdd(), fan_chosen_nickname="Bo")
        await _seed_fan(aid, 302, birthday=_today_mmdd())
        await _save(aid, lm.BIRTHDAY, {"enabled": True, "messages": [{
            "variants": ["hb {name}"],
            "follow_ups": [{"text": "f1 {name}", "delay_minutes": 30},
                           {"text": "f2", "delay_minutes": 60}]}]})
        before = datetime.utcnow()
        await _run(lm.BIRTHDAY, aid)
        jobs = await _follow_up_jobs(aid, lm.BIRTHDAY)
        assert len(jobs) == 2, jobs
        assert all(timedelta(minutes=29) < j.run_at - before < timedelta(minutes=31) for j in jobs)
        # 301 gets both follow-ups; the second waits its own delay after the first.
        await _unpause(aid)
        jobs301 = [j for j in jobs if '"fan_id": 301' in j.payload_json]
        async with get_session() as s:
            (await s.get(ScheduledJob, [j for j in jobs if j not in jobs301][0].id)).status = "held"
        res = await _run(lm.BIRTHDAY, aid, **await _take_follow_up(aid, lm.BIRTHDAY))
        assert res.get("sent") == 1 and res.get("left") == 1, res
        assert fake.sent[-1] == (301, "f1 Bo"), fake.sent
        nxt = (await _follow_up_jobs(aid, lm.BIRTHDAY))[0]
        assert timedelta(minutes=59) < nxt.run_at - datetime.utcnow() < timedelta(minutes=61)
        await _unpause(aid)
        res = await _run(lm.BIRTHDAY, aid, **await _take_follow_up(aid, lm.BIRTHDAY))
        assert res.get("sent") == 1 and fake.sent[-1] == (301, "f2"), (res, fake.sent)
        assert await _follow_up_jobs(aid, lm.BIRTHDAY) == []
        assert [r.body for r in await _sent_rows(aid, lm.BIRTHDAY) if r.fan_id == 301] \
            == ["<p>hb Bo</p>", "<p>f1 Bo</p>", "<p>f2</p>"]
        # 302 says something after his birthday message: the sequence ends, unsent.
        async with get_session() as s:
            (await s.get(ScheduledJob, [j for j in jobs if j not in jobs301][0].id)).status = "pending"
            s.add(Message(account_id=aid, fan_id=302, message_id=9_200_000_000_001,
                          direction="in", body="thanks!", created_at=datetime.utcnow()))
        n = len(fake.sent)
        res = await _run(lm.BIRTHDAY, aid, **await _take_follow_up(aid, lm.BIRTHDAY))
        assert res == {"status": "skipped", "reason": "stopped_on_reply", "sent": 0}, res
        assert len(fake.sent) == n and await _follow_up_jobs(aid, lm.BIRTHDAY) == []
    _sandboxed(go)


def case_a_busy_fan_retries_and_a_rule_switched_off_drops_the_sequence():
    async def go():
        fake = _use_fake()
        aid = "lm_seq_off"
        await _seed_account(aid)
        await _seed_fan(aid, 311, birthday=_today_mmdd())
        await _save(aid, lm.BIRTHDAY, {"enabled": True, "messages": [{
            "variants": ["hb"], "follow_ups": [{"text": "f1", "delay_minutes": 1}]}]})
        await executor._materialize_due_rules()
        res = await executor.run_once(aid, lm.BIRTHDAY)
        assert res.get("sent") == 1, res
        job = (await _follow_up_jobs(aid, lm.BIRTHDAY))[0]
        assert job.rule_id is not None and '"_followup": true' in job.payload_json, job.payload_json
        # Still resting from the birthday message: tried again later, not lost.
        async with get_session() as s:
            (await s.get(ScheduledJob, job.id)).run_at = datetime.utcnow() - timedelta(seconds=1)
        res = await executor.run_once(aid, lm.BIRTHDAY)
        assert res.get("reason") == "busy", res
        retry = (await _follow_up_jobs(aid, lm.BIRTHDAY))[0]
        assert json.loads(retry.payload_json)["follow_up"]["tries"] == 1
        # Off: the queued follow-up is cancelled and never sends.
        await _save(aid, lm.BIRTHDAY, {"enabled": False})
        await _unpause(aid)
        async with get_session() as s:
            (await s.get(ScheduledJob, retry.id)).run_at = datetime.utcnow() - timedelta(seconds=1)
        await executor.run_once(aid, lm.BIRTHDAY)
        assert [t for _, t in fake.sent] == ["hb"], fake.sent
    _sandboxed(go)


def case_expired_follows_first_through_the_money_gate_and_a_refusal_is_not_quarantined():
    async def go():
        fake = _use_fake()
        aid = "lm_d12"
        await _seed_account(aid)
        for fid in (401, 402, 403):
            await _seed_fan(aid, fid)
        await _enable(aid, lm.EXPIRED)
        fake.price = 0
        fake.refuse = {402}
        res = await _run(lm.EXPIRED, aid, force_ids=[401, 402])
        # Followed before the message, through the paced write seam.
        assert fake.follows == [401, 402], fake.follows
        assert fake.calls[:2] == ["follow", "send"], fake.calls
        assert PURPOSES == ["gated"] * 4, PURPOSES
        assert [f for f, _ in fake.sent] == [401], fake.sent
        assert res.get("refused_expired") == 1 and res.get("unreachable") == 0, res
        assert res.get("follow_outcomes") == {"followed": 2}, res
        async with get_session() as s:
            assert (await s.execute(select(SkipList).where(
                SkipList.account_id == aid, SkipList.fan_id == 402))).first() is None
            assert (await s.get(Fan, (aid, 402))).automation_paused_until is None
        # A priced profile is never followed (it would PAY); the message still goes.
        fake.price = 9.99
        res = await _run(lm.EXPIRED, aid, force_ids=[403])
        assert fake.follows == [401, 402] and fake.sent[-1][0] == 403, (fake.follows, fake.sent)
        assert res.get("follow_outcomes") == {"paid_profile": 1}, res
        # Nearing expiry never follows.
        await _enable(aid, lm.EXPIRY)
        await _seed_fan(aid, 404)
        await _run(lm.EXPIRY, aid, force_ids=[404])
        assert fake.follows == [401, 402], fake.follows
    _sandboxed(go)


def case_nearing_expiry_gives_the_discount_before_the_message_and_none_without_it():
    async def go():
        fake = _use_fake()
        aid = "lm_discount"
        await _seed_account(aid)
        _paid_page(fake, aid)
        await _seed_fan(aid, 501)
        await _seed_fan(aid, 502)
        await _save(aid, lm.EXPIRY, {"enabled": True, "messages": [{
            "variants": ["renew for 20% off"], "discount": {"percent": 20, "months": 2}}]})
        res = await _run(lm.EXPIRY, aid, force_ids=[501])
        assert fake.discounts == [(501, 20, 2)] and fake.calls == ["discount", "send"], fake.calls
        assert res.get("discounted") == 1 and res.get("sent") == 1, res
        # A discount OF refused means no message promising it.
        fake.discount_error = "500 boom"
        res = await _run(lm.EXPIRY, aid, force_ids=[502])
        assert res.get("errors") == 1 and [f for f, _ in fake.sent] == [501], (res, fake.sent)
        # Expired offers none: OF's handling of a lapsed fan's discount is unverified.
        await _refused(_save(aid, lm.EXPIRED, {"messages": [{
            "variants": ["x"], "discount": {"percent": 20, "months": 2}}]}), 422)
    _sandboxed(go)


def case_the_config_route_validates_messages_and_reads_a_text_only_rule():
    async def go():
        _paid_page(_use_fake(), "lm_cfg_msgs")
        aid = "lm_cfg_msgs"
        await _seed_account(aid)
        for bad in ([{"variants": []}], [{"variants": [" "]}], [{"variants": "hi"}],
                    [{"variants": ["x"]}] * 11, [{"variants": ["x"] * 11}],
                    [{"variants": ["x"], "follow_ups": [{"text": "y", "delay_minutes": 0}]}],
                    [{"variants": ["x"], "follow_ups": [{"text": "", "delay_minutes": 5}]}],
                    [{"variants": ["x"], "follow_ups": [{"text": "y", "delay_minutes": 5}] * 6}],
                    [{"variants": ["x"], "discount": {"percent": 22, "months": 1}}],
                    [{"variants": ["x"], "discount": {"percent": 20, "months": 13}}],
                    [{"variants": ["x"], "discount": {"percent": 20.0, "months": 1}}],
                    [{"variants": ["x"], "follow_ups": [{"text": "y", "delay_minutes": True}]}],
                    [{"variants": ["x", 7]}], "x", [{"variants": ["x"], "follow_ups": "y"}]):
            await _refused(_save(aid, lm.EXPIRY, {"messages": bad}), 422)
        out = await _save(aid, lm.EXPIRY, {"enabled": True, "messages": [
            {"variants": [" a ", "b"], "follow_ups": [{"text": "c", "delay_minutes": 5}],
             "discount": {"percent": 15, "months": 1}}, {"variants": ["d"]}]})
        assert out["config"]["messages"] == [
            {"variants": ["a", "b"], "follow_ups": [{"text": "c", "delay_minutes": 5}],
             "discount": {"percent": 15, "months": 1}},
            {"variants": ["d"], "follow_ups": [], "discount": None}], out
        assert out["config"]["text"] == "a", out
        # Turning on needs the messages in the same request; an empty list never.
        await _save(aid, lm.EXPIRY, {"enabled": False})
        await _refused(_save(aid, lm.EXPIRY, {"enabled": True}), 422)
        await _refused(_save(aid, lm.EXPIRY, {"enabled": True, "messages": []}), 422)
        # A rule saved before messages existed reads as its text, one message.
        async with get_session() as s:
            s.add(AutomationRule(account_id=aid, name="Birthday", kind=lm.BIRTHDAY,
                                 trigger_json="{}", is_enabled=False,
                                 steps_json=json.dumps({"enabled": False, "text": "old"})))
        got = await _as("owner", aid, lambda: api.get_lifecycle_message_config(
            account_id=aid, kind=lm.BIRTHDAY))
        assert got["config"]["messages"] == [
            {"variants": ["old"], "follow_ups": [], "discount": None}], got
    _sandboxed(go)


def case_buyers_are_the_messaged_fans_who_spent_within_the_window():
    async def go():
        fake = _use_fake()
        aid = "lm_buyers"
        await _seed_account(aid)
        for fid in (601, 602, 603):
            await _seed_fan(aid, fid, birthday=_today_mmdd(), of_username=f"u{fid}")
        await _save(aid, lm.BIRTHDAY, {"enabled": True, "messages": [{"variants": ["hb"]}]})
        fake.refuse = {603}
        await _run(lm.BIRTHDAY, aid)
        now = datetime.utcnow()
        async with get_session() as s:
            for fid, cents, at, status in (
                    (601, 500, now + timedelta(hours=1), "cleared"),
                    (601, 700, now + timedelta(days=2), "loading"),
                    (601, 900, now + timedelta(days=9), "cleared"),     # past the window
                    (601, 300, now + timedelta(hours=2), "refunded"),
                    (602, 400, now - timedelta(days=1), "cleared"),     # before the message
                    (603, 800, now + timedelta(hours=1), "cleared")):   # never got it
                s.add(Transaction(account_id=aid, fan_id=fid, kind="tip", amount_cents=cents,
                                  occurred_at=at, status=status))
        got = await _as("owner", aid, lambda: api.get_lifecycle_message_buyers(
            account_id=aid, kind=lm.BIRTHDAY))
        assert [(b["fan_id"], b["spent_cents"], b["purchases"], b["message"], b["username"])
                for b in got["buyers"]] == [(601, 1200, 2, 1, "u601")], got
        assert got["window_days"] == 7, got
    _sandboxed(go)




def case_a_follow_up_is_claimed_once_and_a_failure_after_the_send_never_resends_it():
    async def go():
        fake = _use_fake()
        aid = "lm_seq_claim"
        await _seed_account(aid)
        await _seed_fan(aid, 321, birthday=_today_mmdd())
        await _seed_fan(aid, 322, birthday=_today_mmdd())
        await _save(aid, lm.BIRTHDAY, {"enabled": True, "messages": [{
            "variants": ["hb"], "follow_ups": [{"text": "f1", "delay_minutes": 5}]}]})
        await _run(lm.BIRTHDAY, aid)
        jobs = {json.loads(j.payload_json)["follow_up"]["fan_id"]: json.loads(j.payload_json)
                for j in await _follow_up_jobs(aid, lm.BIRTHDAY)}
        await _unpause(aid)
        # The same job run twice (a requeue) sends the step once.
        assert (await _run(lm.BIRTHDAY, aid, **jobs[321])).get("sent") == 1
        await _unpause(aid)
        res = await _run(lm.BIRTHDAY, aid, **jobs[321])
        assert res == {"status": "skipped", "reason": "already_sent", "sent": 0}, res
        # OF took it, then the bookkeeping broke: done, not an error to retry.
        real = lm.write_outbound_attribution

        async def broken(**kw):
            raise RuntimeError("db down")
        lm.write_outbound_attribution = broken
        try:
            res = await _run(lm.BIRTHDAY, aid, **jobs[322])
        finally:
            lm.write_outbound_attribution = real
        assert res.get("status") == "ok" and res.get("sent") == 1, res
        await _unpause(aid)
        assert (await _run(lm.BIRTHDAY, aid, **jobs[322])).get("reason") == "already_sent"
        assert sorted(t for f, t in fake.sent if t == "f1") == ["f1", "f1"], fake.sent
        # The claim carries no message index: the Buyers list never reads it.
        async with get_session() as s:
            keys = {c.event_key: c.message_idx for c in (await s.execute(
                select(LifecycleMessageClaim).where(LifecycleMessageClaim.account_id == aid,
                                                    LifecycleMessageClaim.fan_id == 321))).scalars()}
        assert sorted(keys.values(), key=str) == [0, None], keys
    _sandboxed(go)


def case_a_discount_above_what_onlyfans_grants_for_the_price_is_refused():
    async def go():
        import account_page
        fake = _use_fake()
        aid = "lm_discount_cap"
        await _seed_account(aid)
        assert (lm.discount_cap(999), lm.discount_cap(599), lm.discount_cap(2000),
                lm.discount_cap(499)) == (50, 16, 60, 0)

        def msg(pct):
            return {"messages": [{"variants": ["x"], "discount": {"percent": pct, "months": 1}}]}
        fake.me = lambda: {"subscribePrice": 5.99}
        account_page.invalidate(aid)
        try:
            await _save(aid, lm.EXPIRY, msg(20))
        except HTTPException as e:
            assert e.status_code == 422 and "16%" in e.detail, e.detail
        else:
            raise AssertionError("a 20% discount saved on a $5.99 page")
        assert (await _save(aid, lm.EXPIRY, msg(15)))["config"]["messages"][0]["discount"] \
            == {"percent": 15, "months": 1}
        # A price that cannot be read cannot vouch for the discount.
        fake.me = lambda: (_ for _ in ()).throw(RuntimeError("session dead"))
        account_page.invalidate(aid)
        await _refused(_save(aid, lm.EXPIRY, msg(5)), 422)
        # No discount, no price read needed.
        assert (await _save(aid, lm.EXPIRY, {"messages": [{"variants": ["y"]}]}))["config"]["text"] == "y"
        account_page.invalidate(aid)
    _sandboxed(go)


def case_a_backlog_of_due_follow_ups_never_holds_back_the_rules_own_run():
    async def go():
        _use_fake()
        aid = "lm_fu_backlog"
        await _seed_account(aid)
        await _enable(aid, lm.BIRTHDAY)
        past = datetime.utcnow() - timedelta(minutes=5)
        for fid in (1, 2, 3):
            await executor.enqueue_job(aid, lm.BIRTHDAY, run_at=past, payload={"follow_up": {
                "fan_id": fid, "steps": [{"text": "f", "delay_minutes": 5}], "anchor": None,
                "event": "e", "step": 1, "tries": 0}})
        await executor._materialize_due_rules()
        async with get_session() as s:
            jobs = (await s.execute(select(ScheduledJob).where(
                ScheduledJob.account_id == aid, ScheduledJob.status == "pending"))).scalars().all()
        assert len(jobs) == 4, jobs
        # The rule's run is claimed first, then the follow-ups in their order.
        order = [json.loads((await executor._claim_due_job(aid, lm.BIRTHDAY)).payload_json)
                 for _ in range(4)]
        assert "follow_up" not in order[0], order[0]
        assert [o["follow_up"]["fan_id"] for o in order[1:]] == [1, 2, 3], order
    _sandboxed(go)


def case_every_text_is_cut_to_the_cap_on_save():
    async def go():
        _use_fake()
        aid = "lm_text_cap"
        await _seed_account(aid)
        long = "x" * (lm.TEXT_MAX + 50)
        out = await _save(aid, lm.BIRTHDAY, {"messages": [{
            "variants": [long, "short"], "follow_ups": [{"text": long, "delay_minutes": 5}]}]})
        m = out["config"]["messages"][0]
        assert [len(v) for v in m["variants"]] == [lm.TEXT_MAX, 5], m
        assert len(m["follow_ups"][0]["text"]) == lm.TEXT_MAX, m
        assert len((await _save(aid, lm.BIRTHDAY, {"text": long}))["config"]["text"]) == lm.TEXT_MAX
    _sandboxed(go)


def case_pick_targets_table_claimed_and_gated_fans_drop_out_per_kind():
    """The sweep's pure selection: per kind, an already-claimed fan drops out
    silently; no row / outside the audience / hard-skipped / blacklisted /
    paused / muted-creator counts as skipped; the rest are planned in event order,
    each with a variant of its picked message, deterministically."""
    from types import SimpleNamespace as NS
    now = datetime(2026, 6, 1, 12, 0, 0)
    msgs = [{"variants": ["a", "b"]}, {"variants": ["c"]}]
    fan = lambda **kw: NS(**{"automation_paused_until": None, "is_muted": False, "source": "", **kw})  # noqa: E731
    fans = {1: fan(), 2: fan(), 3: fan(), 4: fan(), 5: fan(),
            6: fan(automation_paused_until=now + timedelta(minutes=1)),
            7: fan(is_muted=True, source="creator_we_follow"),
            8: fan(automation_paused_until=now - timedelta(minutes=1))}
    events = {i: f"ev{i}" for i in range(1, 10)}          # 9 has no Fan row
    rows = [  # (name, done, kept, hard_skip, blacklist, want planned, want skipped)
        ("all clear", set(), set(events), set(), set(), [1, 2, 3, 4, 5, 8], 3),
        ("already claimed dropped, not skipped", {1, 2}, set(events), set(), set(),
         [3, 4, 5, 8], 3),
        ("outside audience", set(), set(events) - {3}, set(), set(), [1, 2, 4, 5, 8], 4),
        ("hard skip + blacklist", set(), set(events), {4}, {5}, [1, 2, 3, 8], 5),
        ("claimed beats gated", {6, 7, 9}, set(events), set(), set(), [1, 2, 3, 4, 5, 8], 0),
    ]
    for kind in (lm.EXPIRY, lm.EXPIRED, lm.RESUBSCRIBE, lm.BIRTHDAY):
        for name, done, kept, hard, black, want, want_skipped in rows:
            args = (kind, "acc", events, msgs)
            kw = dict(done=done, fans=fans, kept=kept, hard_skip=hard, blacklist=black, now=now)
            plans, skipped = lm.pick_targets(*args, **kw)
            assert [p[0] for p in plans] == want and skipped == want_skipped, (kind, name, plans, skipped)
            assert lm.pick_targets(*args, **kw) == (plans, skipped), "not deterministic"
            for fid, key, idx, text in plans:
                assert key == events[fid] and text in msgs[idx]["variants"], (fid, key, idx, text)
    assert lm.pick_targets(lm.EXPIRY, "acc", {}, msgs, done=set(), fans={}, kept=set(),
                           hard_skip=set(), blacklist=set(), now=now) == ([], 0)


_harness.run(
    case_off_by_default_nothing_is_read_or_sent,
    case_a_free_page_cannot_switch_on_the_paid_only_triggers,
    case_nearing_expiry_messages_non_renewing_fans_inside_the_window_once,
    case_nearing_expiry_does_not_chase_a_window_entered_before_the_switch,
    case_nearing_expiry_reaches_a_fan_who_turns_renewal_off_late_in_a_long_window,
    case_expired_messages_fans_gone_from_a_complete_crawl_n_hours_after_expiry,
    case_a_truncated_or_empty_crawl_changes_nothing,
    case_resubscribe_on_return_after_a_lapse_and_on_a_known_fans_fresh_start,
    case_birthday_greets_fans_whose_birthday_is_today_once_a_year,
    case_frequency_once_greets_a_fan_once_ever_every_time_once_per_event,
    case_the_effective_and_expiry_dates_bound_what_is_sent,
    case_media_a_price_and_auto_unsend_ride_on_the_message,
    case_under_once_a_forced_test_is_never_held_back_and_never_counts,
    case_a_fan_who_owns_the_media_gets_the_text_alone_free,
    case_dry_run_sends_and_claims_nothing,
    case_no_id_send_is_claimed_probed_and_not_retried,
    case_cap_limits_each_sweep_and_the_rest_wait,
    case_force_ids_skips_the_roster_but_not_the_gates_or_the_claim,
    case_skip_listed_paused_blacklisted_and_muted_creator_fans_are_left_alone,
    case_the_config_route_validates_and_only_an_owner_switches_it_on,
    case_the_generic_switch_refuses_to_turn_these_kinds_on,
    case_the_fan_birthday_is_set_as_mm_dd_and_cleared_with_empty,
    case_end_to_end_a_switched_on_rule_is_materialised_and_run_by_the_executor,
    case_a_trigger_picks_one_of_its_messages_and_one_variant_seeded_per_event,
    case_follow_ups_go_out_in_order_and_stop_for_good_on_a_reply,
    case_a_busy_fan_retries_and_a_rule_switched_off_drops_the_sequence,
    case_expired_follows_first_through_the_money_gate_and_a_refusal_is_not_quarantined,
    case_nearing_expiry_gives_the_discount_before_the_message_and_none_without_it,
    case_the_config_route_validates_messages_and_reads_a_text_only_rule,
    case_buyers_are_the_messaged_fans_who_spent_within_the_window,
    case_a_follow_up_is_claimed_once_and_a_failure_after_the_send_never_resends_it,
    case_a_discount_above_what_onlyfans_grants_for_the_price_is_refused,
    case_a_backlog_of_due_follow_ups_never_holds_back_the_rules_own_run,
    case_every_text_is_cut_to_the_cap_on_save,
    case_pick_targets_table_claimed_and_gated_fans_drop_out_per_kind,
)
