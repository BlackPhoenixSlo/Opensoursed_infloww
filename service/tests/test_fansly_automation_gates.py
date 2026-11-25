#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import json  # noqa: E402
import tempfile  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

from sqlalchemy import select  # noqa: E402

import accounts as account_registry  # noqa: E402
import automation_executor as ax  # noqa: E402
import audiences  # noqa: E402
import automations.lifecycle_messages as lm  # noqa: E402
import automations.mass_premade  # noqa: E402,F401
import automations.send_mass_message  # noqa: E402,F401
import automations.smart_list_sync as sls  # noqa: E402
import automations.unsend_messages  # noqa: E402,F401
from automation_executor import run_once  # noqa: E402
from automations import send_welcome  # noqa: E402
from automations.auto_follow import gated_follow  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, AutomationRule, Fan, LifecycleMessageClaim, MassBroadcastCache, MassRun, Message,
    ScheduledJob, SmartList, WelcomeSent,
)
from fansly_shim import FanslyShimClient  # noqa: E402

_TMP = tempfile.TemporaryDirectory(prefix="fansly_automation_gates_")
account_registry.SESSIONS_DIR = Path(_TMP.name)
account_registry.ACCOUNTS_DIR = Path(_TMP.name) / "accounts"
account_registry.ACTIVE_FILE = Path(_TMP.name) / "active.json"
account_registry.MIGRATED_MARKER = Path(_TMP.name) / ".migrated"

_REAL_MAKE_CLIENT = ax._make_client
_REAL_PACED = ax.of_write_paced
_REAL_MARK_WELCOMED = send_welcome._mark_welcomed
_REAL_EXCLUDE_LIST = audiences.ensure_exclude_list


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def _request(self, method, path, *_a, **_k):
        raise AssertionError(f"unrecorded Fansly request {method} {path}")

    def send_message(self, chat_id, text, **_kw):
        self.calls.append(("send", int(chat_id), text))
        return {"id": 8_800_000 + len(self.calls), "text": text,
                "createdAt": datetime.utcnow().isoformat() + "+00:00"}

    def unsend_message(self, message_id, with_user_id=None):
        self.calls.append(("unsend", int(message_id), int(with_user_id)))
        return {"success": True}

    def cancel_scheduled(self, queue_id):
        self.calls.append(("cancel", int(queue_id)))
        return {"success": True}

    def follow_user(self, user_id):
        self.calls.append(("follow", int(user_id)))
        return {"success": True}

    def get_user(self, user_id):
        return {"id": int(user_id), "subscribePrice": 0, "subscribedByExpireDate": "2026-01-01"}

    def notifications(self, *, limit=10, offset=0, **_kw):
        return {"list": [{"user": {"id": 46901, "name": "Ida", "username": "ida"}}], "hasMore": False}


class _Fansly(_Recorder, FanslyShimClient):
    pass


class _OF(_Recorder):
    def mass_message_history(self, **_kw):
        self.calls.append(("history",))
        return {"items": [], "hasMore": False}

    def set_subscription_discount(self, user_id, discount, period):
        self.calls.append(("discount", int(user_id)))
        return {"id": int(user_id)}

    def resubscribe_user(self, user_id):
        self.calls.append(("resubscribe", int(user_id)))
        return {"success": True}

    def list_users_in(self, list_id, *, limit=20, offset=0):
        return []

    def add_users_to_lists(self, body):
        self.calls.append(("list_add", json.dumps(body, sort_keys=True)))
        return {k: list(v) for k, v in body.items()}

    def create_list(self, name):
        self.calls.append(("create_list", name))
        return {"id": 701}

    def delete_list(self, list_id):
        self.calls.append(("delete_list", int(list_id)))
        return {}

    def my_settings(self):
        return {"replyOnSubscribe": False}

    def message_templates(self, **_kw):
        return []

    def vault_media(self, *, list_id=None, **_kw):
        self.calls.append(("vault", int(list_id)))
        return {"list": [{"id": 901, "files": {"full": {"url": "https://x/901.jpg"}}}]}

    def send_mass_message(self, text, **kw):
        self.calls.append(("mass", text, tuple(kw["excluded_user_lists"])))
        return {"id": 66101, "createdAt": datetime.utcnow().isoformat() + "+00:00"}


async def _unpaced(account_id, fn, **kw):
    return await _REAL_PACED(account_id, fn, **{**kw, "min_gap_s": 0.0, "pause_s": 0.0})


def _use(client):
    ax._make_client = lambda _aid: client  # type: ignore[assignment]
    ax.of_write_paced = _unpaced  # type: ignore[assignment]
    return client


def _restore() -> None:
    ax._make_client = _REAL_MAKE_CLIENT  # type: ignore[assignment]
    ax.of_write_paced = _REAL_PACED  # type: ignore[assignment]
    send_welcome._mark_welcomed = _REAL_MARK_WELCOMED  # type: ignore[assignment]
    audiences.ensure_exclude_list = _REAL_EXCLUDE_LIST  # type: ignore[assignment]


async def _account(aid: str, *fans: int) -> None:
    async with get_session() as s:
        s.add(Account(id=aid))
    async with get_session() as s:
        for f in fans:
            s.add(Fan(account_id=aid, fan_id=f, lifetime_spend_cents=20000))


_CAST, _OLD_CAST, _CHAT_FAN, _CHAT_MID, _COPY_MID = 7101, 7102, 5101, 51010001, 51010002


async def _seed_unsend(aid: str) -> None:
    await _account(aid)
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(MassBroadcastCache(
            account_id=aid, queue_id=_CAST, sent_at=now - timedelta(hours=10), body_text="hey babe",
            is_free=True, is_tip=False, media_count=0, is_canceled=False, can_unsend=True, fetched_at=now))
        s.add(MassRun(account_id=aid, queue_id=_OLD_CAST, automation_kind="mass_premade", audience_filter="{}",
                      recipient_count=1, status="ok", body="old blast", sent_at=now - timedelta(hours=30),
                      completed_at=now - timedelta(hours=30), unsent_at=now - timedelta(hours=1)))
        s.add(Message(account_id=aid, fan_id=_CHAT_FAN, message_id=_CHAT_MID, direction="out", body="hi there",
                      media_count=0, created_at=now - timedelta(hours=2)))
        s.add(Message(account_id=aid, fan_id=_CHAT_FAN, message_id=_COPY_MID, direction="out", body="old blast",
                      media_count=0, raw_json=json.dumps({"queueId": _OLD_CAST}),
                      created_at=now - timedelta(hours=30)))


async def _unsend_state(aid: str) -> tuple[bool, bool, bool]:
    async with get_session() as s:
        cast = await s.get(MassBroadcastCache, (aid, _CAST))
        chat = await s.get(Message, (aid, _CHAT_FAN, _CHAT_MID))
        copy = await s.get(Message, (aid, _CHAT_FAN, _COPY_MID))
        return bool(cast.is_canceled), bool(chat.is_unsent), bool(copy.is_unsent)


_UNSEND_POLICY = {"policy": {"text_hours": 1, "mass_text_hours": 8}}


async def case_fansly_unsend_drops_the_mass_lane_and_runs_per_chat():
    aid = "8803101"
    await _seed_unsend(aid)
    fake = _use(_Fansly())
    try:
        r = await run_once(aid, "unsend_messages", payload=_UNSEND_POLICY)
    finally:
        _restore()
    assert fake.calls == [("unsend", _CHAT_MID, _CHAT_FAN)], fake.calls
    assert r.get("mass_skipped") == "platform_lacks:mass_message_history", r
    assert not r.get("mass_refresh_failed"), r
    assert await _unsend_state(aid) == (False, True, False), await _unsend_state(aid)


async def case_of_unsend_still_sweeps_mass_and_per_chat():
    aid = "8803102"
    await _seed_unsend(aid)
    fake = _use(_OF())
    try:
        r = await run_once(aid, "unsend_messages", payload=_UNSEND_POLICY)
    finally:
        _restore()
    assert ("history",) in fake.calls and ("cancel", _CAST) in fake.calls, fake.calls
    assert ("unsend", _CHAT_MID, _CHAT_FAN) in fake.calls, fake.calls
    assert "mass_skipped" not in r, r
    assert await _unsend_state(aid) == (True, True, True), await _unsend_state(aid)


_EXPLICIT = {"targets": [{"queue_id": _OLD_CAST}, {"message_id": _CHAT_MID, "fan_id": _CHAT_FAN}]}


async def case_fansly_unsend_drops_explicit_mass_targets():
    aid = "8803103"
    await _seed_unsend(aid)
    account_registry.save_meta(aid, {"id": aid, "nickname": aid, "platform": "fansly"})
    fake = _use(_Fansly())
    try:
        r = await run_once(aid, "unsend_messages", payload=_EXPLICIT)
    finally:
        _restore()
    assert fake.calls == [("unsend", _CHAT_MID, _CHAT_FAN)], fake.calls
    assert r.get("mass_skipped") == "platform_lacks:mass_message_history", r
    assert await _unsend_state(aid) == (False, True, False), await _unsend_state(aid)


async def case_of_unsend_still_cancels_explicit_mass_targets():
    aid = "8803104"
    await _seed_unsend(aid)
    fake = _use(_OF())
    try:
        r = await run_once(aid, "unsend_messages", payload=_EXPLICIT)
    finally:
        _restore()
    assert fake.calls == [("cancel", _OLD_CAST), ("unsend", _CHAT_MID, _CHAT_FAN)], fake.calls
    assert "mass_skipped" not in r, r
    assert await _unsend_state(aid) == (False, True, True), await _unsend_state(aid)


_LM_MESSAGES = [{"variants": ["renew for 20% off"], "discount": {"percent": 20, "months": 2}},
                {"variants": ["see you soon"]}]


def _fan_per_message(aid: str) -> tuple[int, int]:
    key = f"{lm._FORCED}{datetime.utcnow().date().isoformat()}"
    by_idx: dict[int, int] = {}
    for fid in range(6101, 6200):
        by_idx.setdefault(lm.pick(range(2), lm.EXPIRY, aid, fid, key, "message"), fid)
        if len(by_idx) == 2:
            return by_idx[0], by_idx[1]
    raise AssertionError("no fan picks each message")


async def _seed_expiry(aid: str) -> tuple[int, int]:
    discounted, plain = _fan_per_message(aid)
    await _account(aid, discounted, plain)
    steps = {"enabled": True, "enabled_at": (datetime.utcnow() - timedelta(days=1)).isoformat(),
             "messages": _LM_MESSAGES}
    async with get_session() as s:
        s.add(AutomationRule(account_id=aid, name="expiry", kind=lm.EXPIRY, trigger_json="{}",
                             steps_json=json.dumps(steps), is_enabled=True))
    return discounted, plain


async def _claimed_fans(aid: str) -> set[int]:
    async with get_session() as s:
        return set((await s.execute(select(LifecycleMessageClaim.fan_id).where(
            LifecycleMessageClaim.account_id == aid))).scalars())


async def case_fansly_expiry_drops_only_the_discounted_plan():
    aid = "8803201"
    discounted, plain = await _seed_expiry(aid)
    fake = _use(_Fansly())
    try:
        r = await lm.sweep(lm.EXPIRY, aid, {"force_ids": [discounted, plain]})
    finally:
        _restore()
    assert fake.calls == [("send", plain, "see you soon")], fake.calls
    assert await _claimed_fans(aid) == {plain}, await _claimed_fans(aid)
    assert r["sent"] == 1 and r["errors"] == 0 and r["discounted"] == 0, r


async def case_of_expiry_discounts_then_sends_both():
    aid = "8803202"
    discounted, plain = await _seed_expiry(aid)
    fake = _use(_OF())
    try:
        r = await lm.sweep(lm.EXPIRY, aid, {"force_ids": [discounted, plain]})
    finally:
        _restore()
    assert ("discount", discounted) in fake.calls, fake.calls
    assert {c[1] for c in fake.calls if c[0] == "send"} == {discounted, plain}, fake.calls
    assert await _claimed_fans(aid) == {discounted, plain}
    assert r["sent"] == 2 and r["discounted"] == 1, r


_WHALES = json.dumps({"rules": [{"field": "lifetime_spend", "op": ">=", "value": 10000}]})


async def _seed_lists(aid: str) -> tuple[int, int]:
    await _account(aid, 1, 2)
    async with get_session() as s:
        active = SmartList(account_id=aid, name="Whales", rules_json=_WHALES, is_active=True)
        tomb = SmartList(account_id=aid, name="Gone", rules_json="{}", is_active=False,
                         of_list_id=702, sync_state="deleting")
        s.add_all([active, tomb])
        await s.flush()
        return int(active.id), int(tomb.id)


async def _list_rows(aid: str) -> list[tuple]:
    async with get_session() as s:
        return [(r.id, r.of_list_id, r.sync_state, r.sync_error, r.synced_at) for r in (await s.execute(
            select(SmartList).where(SmartList.account_id == aid).order_by(SmartList.id))).scalars()]


async def case_fansly_smart_list_sync_skips_before_any_row_moves():
    aid = "8803301"
    await _seed_lists(aid)
    before = await _list_rows(aid)
    fake = _use(_Fansly())
    try:
        r = await sls.run(aid, {}, run_id=0)
    finally:
        _restore()
    assert r == {"status": "skipped", "reason": "platform_lacks:list_users_in"}, r
    assert fake.calls == [], fake.calls
    assert await _list_rows(aid) == before, (before, await _list_rows(aid))


async def case_of_smart_list_sync_deletes_and_syncs():
    aid = "8803302"
    active, _tomb = await _seed_lists(aid)
    fake = _use(_OF())
    try:
        r = await sls.run(aid, {}, run_id=0)
    finally:
        _restore()
    assert ("delete_list", 702) in fake.calls and ("create_list", "Whales") in fake.calls, fake.calls
    assert r["deleted"] == 1 and r["ok"] == 1, r
    rows = await _list_rows(aid)
    assert [(i, of, st) for i, of, st, *_ in rows] == [(active, 701, "ok")], rows


async def case_fansly_refollowed_falls_back_to_follow():
    fake = _Fansly()
    assert await gated_follow(fake, 4401, account_id="8803401") == "refollowed"
    assert fake.calls == [("follow", 4401)], fake.calls


async def case_of_refollowed_resubscribes():
    fake = _OF()
    assert await gated_follow(fake, 4402, account_id="8803402") == "refollowed"
    assert fake.calls == [("resubscribe", 4402)], fake.calls


async def _welcome(aid: str, fake) -> tuple[dict, list[tuple]]:
    await _account(aid)
    order: list[tuple] = []

    async def mark(account_id, fan_id, username):
        order.append(("mark", int(fan_id), list(fake.calls)))
        await _REAL_MARK_WELCOMED(account_id, fan_id, username)

    _use(fake)
    send_welcome._mark_welcomed = mark  # type: ignore[assignment]
    try:
        r = await run_once(aid, "send_welcome", payload={
            "with_image": False, "after_of_welcome": True, "message": "hey {name}", "follow_back": False})
    finally:
        _restore()
    return r, order


async def _check_own_greeting(aid: str, fake) -> None:
    r, order = await _welcome(aid, fake)
    assert fake.calls == [("send", 46901, "hey Ida")], fake.calls
    assert order == [("mark", 46901, [("send", 46901, "hey Ida")])], order
    assert (r["of_welcome_on"], r["welcomes_sent"]) == (False, 1), r
    async with get_session() as s:
        assert await s.get(WelcomeSent, (aid, 46901)) is not None


async def case_fansly_welcome_sends_its_own_greeting_then_marks():
    await _check_own_greeting("8803501", _Fansly())


async def case_of_welcome_off_sends_its_own_greeting_then_marks():
    await _check_own_greeting("8803502", _OF())


def _spy_exclude_list(fake) -> None:
    async def record(account_id, ids, *, client=None):
        fake.calls.append(("exclude_list", tuple(sorted(ids))))
        return 4343

    audiences.ensure_exclude_list = record  # type: ignore[assignment]


async def _mass_state(aid: str) -> tuple[int, list[str]]:
    async with get_session() as s:
        runs = len((await s.execute(select(MassRun.id).where(MassRun.account_id == aid))).all())
        jobs = list((await s.execute(select(ScheduledJob.kind).where(ScheduledJob.account_id == aid))).scalars())
    return runs, jobs


_BROADCAST = {"text": "hey all", "user_lists": ["fans"], "excluded_users": [5],
              "exclude_replied_hours": 0, "exclude_inbound_hours": 0}
_LACKS_MASS = {"status": "skipped", "reason": "platform_lacks:send_mass_message"}


async def _broadcast(aid: str, fake) -> dict:
    await _account(aid)
    _use(fake)
    _spy_exclude_list(fake)
    try:
        return await run_once(aid, "send_mass_message", payload=_BROADCAST)
    finally:
        _restore()


async def case_fansly_mass_message_skips_before_list_write_or_run():
    aid = "8803601"
    fake = _Fansly()
    r = await _broadcast(aid, fake)
    assert {k: r.get(k) for k in _LACKS_MASS} == _LACKS_MASS, r
    assert fake.calls == [], fake.calls
    assert await _mass_state(aid) == (0, []), await _mass_state(aid)


async def case_of_mass_message_syncs_the_list_mints_and_sends():
    aid = "8803602"
    fake = _OF()
    r = await _broadcast(aid, fake)
    assert r["status"] == "ok" and r["queue_id"] == 66101, r
    assert fake.calls == [("exclude_list", (5,)), ("mass", "hey all", (4343,))], fake.calls
    assert (await _mass_state(aid))[0] == 1


_PREMADE = {"messages": [{"text": "m1", "online_only": True, "media_folder_id": 5, "price": 10},
                         {"text": "m2", "online_only": True, "delay_minutes": 15}]}


async def _premade(aid: str, fake) -> dict:
    await _account(aid)
    _use(fake)
    ax._make_client = lambda _aid: fake.calls.append(("client",)) or fake  # type: ignore[assignment]
    try:
        return await run_once(aid, "mass_premade", payload=_PREMADE)
    finally:
        _restore()


async def case_fansly_premade_skips_before_client_vault_or_follow_up():
    aid = "8803701"
    account_registry.save_meta(aid, {"id": aid, "nickname": aid, "platform": "fansly"})
    fake = _Fansly()
    r = await _premade(aid, fake)
    assert {k: r.get(k) for k in _LACKS_MASS} == _LACKS_MASS and "remaining" not in r, r
    assert fake.calls == [], fake.calls
    assert await _mass_state(aid) == (0, []), await _mass_state(aid)


async def case_of_premade_reads_the_folder_sends_and_drips_the_rest():
    aid = "8803702"
    fake = _OF()
    r = await _premade(aid, fake)
    assert r["status"] == "ok" and r["remaining"] == 1, r
    assert fake.calls[:2] == [("client",), ("vault", 5)], fake.calls
    assert [c[:2] for c in fake.calls if c[0] == "mass"] == [("mass", "m1")], fake.calls
    assert await _mass_state(aid) == (1, ["mass_premade"]), await _mass_state(aid)

_harness.run()
