from __future__ import annotations

import contextlib
import json
import time
from datetime import datetime, timedelta
from unittest.mock import patch

import tenant_keys
from _full_ai_fixtures import QUIET, FakeInfoJev, FakeJev, QuietHeatJev
from automations import _heat_jev, _info_jev, _router_jev
from db.engine import get_session
from db.models import (
    Account, AccountAiConfig, AutomationRule, Fan, FanProfile, FunnelState, MassBroadcastCache, MassMessageFunnel,
    MassRun, Message, MessageMedia, NudgeState, Post, PriorityMassRun, S4SMedia, S4SProfile, S4SRequest, S4SSlot,
    PromoCampaign, SmartList, SubscriberSnapshot, User, UserAccount,
)
from of_client import OFClient

FAN = "900000000000000002"
LAPSED = 900000000000000007
OWN_MESSAGE = "900000000000000302"
CAST = 7101
AUDIENCE_LIST = 702
PLATFORM_MESSAGE = {"fansly": 900000000000000303, "onlyfans": 8_700_303}

HOST = "kind-verdicts"
LLM_REPLY = "hey you, tell me more"
LLM_JSON = {"nickname": "Tom/Gym", "short_bio": "likes the gym", "hobbies": "gym"}


class _Download:
    status_code = 200

    def iter_content(self, chunk_size):
        return iter([b"jpeg"])

    def close(self):
        pass


class OFStandIn:
    WRITES = frozenset({"send_message", "unsend_message", "cancel_scheduled", "send_mass_message",
                        "create_list", "add_users_to_lists", "post_story_from_url", "follow_user",
                        "create_post", "delete_post", "set_fan_custom_name", "set_fan_note",
                        "mark_chat_read", "create_promo", "upload_media"})

    def __init__(self, aid: str) -> None:
        self.account_id = self.user_id = aid
        self.http, self.timeout_s = self, 30
        self.calls: list[str] = []
        self.unmodelled: list[str] = []

    def __getattr__(self, name: str):
        if name.startswith("__"):
            raise AttributeError(name)
        self.unmodelled.append(name)
        raise AssertionError(f"unmodelled OnlyFans call {name}")

    def send_message(self, chat_id, text, **_kw):
        self.calls.append("send_message")
        return {"id": 8_800_000 + len(self.calls), "text": text,
                "createdAt": datetime.utcnow().isoformat() + "+00:00"}

    def unsend_message(self, message_id, with_user_id=None):
        self.calls.append("unsend_message")
        return {"success": True}

    def cancel_scheduled(self, queue_id):
        self.calls.append("cancel_scheduled")
        return {"success": True}

    def mass_message_history(self, **_kw):
        self.calls.append("mass_message_history")
        return {"items": [], "hasMore": False}

    def list_users_in(self, list_id, *, limit=20, offset=0):
        self.calls.append("list_users_in")
        return [{"id": int(FAN)}] if int(list_id) == AUDIENCE_LIST and not offset else []

    def add_users_to_lists(self, body):
        self.calls.append("add_users_to_lists")
        return {k: list(v) for k, v in body.items()}

    def get_lists(self, *, offset=0, **_kw):
        self.calls.append("get_lists")
        return {"list": [], "hasMore": False}

    def create_list(self, name):
        self.calls.append("create_list")
        return {"id": 701}

    def vault_media(self, *, list_id=None, **_kw):
        self.calls.append("vault_media")
        return {"list": [{"id": 901, "files": {"full": {"url": "https://x/901.jpg"}}}]}

    def vault_media_by_id(self, media_id):
        self.calls.append("vault_media_by_id")
        return {"id": int(media_id), "type": "photo",
                "files": {"full": {"url": f"https://cdn2.onlyfans.com/{media_id}.jpg"}}}

    def get(self, url, **_kw):
        self.calls.append("download")
        return _Download()

    def upload_media(self, path, **_kw):
        self.calls.append("upload_media")
        return {"vault_id": 902, "ready": True, "send_with": [902]}

    def post_story_from_url(self, url, **_kw):
        self.calls.append("post_story_from_url")
        return {"story": {"id": 3301}, "upload": {}}

    def list_chats(self, *, offset=0, **_kw):
        self.calls.append("list_chats")
        return {"list": [{"withUser": {"id": int(FAN)}}] if offset == 0 else [], "hasMore": False}

    def get_messages(self, chat_id, *, before_id=None, offset=0, **_kw):
        self.calls.append("get_messages")
        rows = [{"id": 8_700_001, "text": "hi there", "fromUser": {"id": int(chat_id)}, "isFree": True,
                 "createdAt": (datetime.utcnow() - timedelta(hours=3)).isoformat() + "+00:00"}]
        return {"list": rows if before_id is None and not offset else [], "hasMore": False}

    def subscribers(self, *, offset=0, **_kw):
        self.calls.append("subscribers")
        now = datetime.utcnow()
        row = {"id": int(FAN), "subscribedOnData": {
            "subscribeAt": (now - timedelta(hours=1)).isoformat() + "+00:00",
            "expiredAt": (now + timedelta(hours=12)).isoformat() + "+00:00", "status": "off"}}
        return {"list": [row] if offset == 0 else [], "hasMore": False}

    def promotions(self, *, offset=0, limit=10, **_kw):
        self.calls.append("promotions")
        row = {"id": 7701, "isFinished": True, "subscribeCounts": 10, "claimsCount": 10, "subscribeDays": 30,
               "price": 5, "type": "all", "createdAt": (datetime.utcnow() - timedelta(days=3)).isoformat() + "+00:00"}
        return {"list": [row] if not offset else [], "hasMore": False}

    def create_promo(self, **kw):
        self.calls.append("create_promo")
        return {"id": 7702, "isFinished": False, "subscribeCounts": kw.get("subscribe_counts"), "claimsCount": 0,
                "subscribeDays": kw.get("subscribe_days"), "type": "all",
                "createdAt": datetime.utcnow().isoformat() + "+00:00"}

    def mark_chat_read(self, chat_id):
        self.calls.append("mark_chat_read")
        return {"success": True}

    def set_fan_custom_name(self, fan_id, name):
        self.calls.append("set_fan_custom_name")
        return {"displayName": name}

    def set_fan_note(self, fan_id, note):
        self.calls.append("set_fan_note")
        return {"notice": note}

    def notifications(self, *, offset=0, type=None, **_kw):
        self.calls.append("notifications")
        row = {"id": "n1", "type": "subscribed", "createdAt": datetime.utcnow().isoformat() + "+00:00",
               "user": {"id": int(FAN), "name": "Synth Fan"}}
        return {"list": [row] if offset == 0 and type in (None, "subscribed") else [], "hasMore": False}

    def get_user(self, fan_id):
        self.calls.append("get_user")
        return {"id": int(fan_id), "subscribePrice": 0}

    def follow_user(self, fan_id):
        self.calls.append("follow_user")
        return {"success": True}

    def iter_online_subscribers(self, **_kw):
        self.calls.append("iter_online_subscribers")
        return [{"id": int(FAN), "name": "Synth Fan", "isOnline": True}]

    def create_post(self, text="", **_kw):
        self.calls.append("create_post")
        return {"id": 5501, "text": text}

    def get_post(self, post_id):
        self.calls.append("get_post")
        return {"id": int(post_id), "text": "edited by the poster"}

    def delete_post(self, post_id, **_kw):
        self.calls.append("delete_post")
        return {"success": True}

    def send_mass_message(self, text, **_kw):
        self.calls.append("send_mass_message")
        return {"id": 66101, "createdAt": datetime.utcnow().isoformat() + "+00:00"}


async def canned_llm(url, headers, body, **_kw):
    content = json.dumps(LLM_JSON) if body.get("response_format") else LLM_REPLY
    return {"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}, 1


async def no_key(_aid):
    return ""


async def _key(_aid):
    return "kind-verdicts-key"


@contextlib.contextmanager
def _jev_answers():
    with patch.object(tenant_keys, "typesafe_key_for", _key), \
            patch.object(_router_jev, "_client", lambda _k: FakeJev(*[(QUIET, 1.0)] * 6)), \
            patch.object(_info_jev, "_client", lambda _k: FakeInfoJev()), \
            patch.object(_heat_jev, "_client", lambda _k: QuietHeatJev()):
        yield


def session_for(platform: str, fake):
    real = OFClient.from_account

    def from_account(aid, **kw):
        return fake if platform == "onlyfans" else real(aid, **kw)
    return from_account



async def _seed_active_list(aid: str, _platform: str) -> None:
    async with get_session() as s:
        s.add_all([Fan(account_id=aid, fan_id=f, lifetime_spend_cents=20000) for f in (1, 2)])
        s.add(SmartList(account_id=aid, name="Whales", is_active=True, rules_json=json.dumps(
            {"rules": [{"field": "lifetime_spend", "op": ">=", "value": 10000}]})))


async def _seed_broadcast_cache(aid: str, _platform: str) -> None:
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(MassBroadcastCache(
            account_id=aid, queue_id=CAST, sent_at=now - timedelta(hours=10), body_text="hey babe",
            is_free=True, is_tip=False, media_count=0, is_canceled=False, can_unsend=True, fetched_at=now))


async def _seed_own_message(aid: str, _platform: str) -> None:
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=int(FAN), message_id=int(OWN_MESSAGE), direction="out",
                      body="synthetic reply", media_count=0,
                      created_at=datetime.utcnow() - timedelta(hours=2)))


def _rows(*makers):
    async def seed(aid: str, platform: str) -> None:
        async with get_session() as s:
            for make in makers:
                s.add(make(aid, platform))
                await s.flush()
    return seed


def _fan(**kw):
    return lambda aid, _p: Fan(account_id=aid, fan_id=int(FAN), **kw)


def _rule(kind: str, **steps):
    return lambda aid, _p: AutomationRule(
        account_id=aid, name=kind, kind=kind, trigger_json="{}", is_enabled=True,
        steps_json=json.dumps({"enabled": True, "enabled_at": "2026-01-01T00:00:00",
                               "messages": [{"variants": ["hey you"]}], **steps}))


def _ai(**kw):
    return lambda aid, _p: AccountAiConfig(account_id=aid, **kw)


def _seen(fan_id: int, ago: timedelta):
    return lambda aid, _p: NudgeState(account_id=aid, fan_id=fan_id, last_seen_online_at=datetime.utcnow() - ago)


def _snap(fan_id: int, seen: timedelta, **kw):
    return lambda aid, _p: SubscriberSnapshot(account_id=aid, fan_id=fan_id, seen_at=datetime.utcnow() - seen, **kw)


def _payload_id(key: str, make):
    async def seed(aid: str, platform: str) -> dict:
        async with get_session() as s:
            row = make(aid, platform)
            s.add(row)
            await s.flush()
            return {key: row.id}
    return seed


def _s4s(posted: dict | None = None, media: bool = False):
    async def seed(aid: str, _platform: str) -> dict:
        partner, now = f"{aid}0", datetime.utcnow()
        async with get_session() as s:
            s.add_all([Account(id=partner, nickname=partner), User(id=f"u{aid}", username=f"u{aid}", password="x")])
            await s.flush()
            for who in (aid, partner):
                s.add_all([UserAccount(user_id=f"u{aid}", account_id=who),
                           S4SProfile(account_id=who, opted_in=True, display_name=who, username=who)])
            shared = S4SMedia(account_id=partner, vault_media_id=901, media_type="photo")
            if media:
                s.add(shared)
                await s.flush()
            req = S4SRequest(from_account_id=partner, to_account_id=aid, slot_at=now, from_caption="swap",
                             to_caption="swap", from_projection_json="{}", to_projection_json="{}", status="accepted",
                             from_media_json=json.dumps([{"id": shared.id}]) if media else None)
            s.add(req)
            await s.flush()
            slot = S4SSlot(request_id=req.id, poster_account_id=aid, partner_account_id=partner, text="go follow",
                           slot_at=now)
            if posted is not None:
                post = Post(account_id=aid, of_post_id=5501, status="posted", text="go follow", price_cents=0,
                            media_ids="[]", posted_at=now, raw_json=json.dumps(posted))
                s.add(post)
                await s.flush()
                slot.status, slot.post_id, slot.of_post_id, slot.posted_at = "posted", post.id, 5501, now
            s.add(slot)
            await s.flush()
            return {"slot_id": slot.id}
    return seed


def _out(ago: timedelta, **kw):
    return lambda aid, platform: Message(
        account_id=aid, fan_id=int(FAN), message_id=PLATFORM_MESSAGE[platform], direction="out", body="for you",
        media_count=1, created_at=datetime.utcnow() - ago, **kw)


def _in(ago: timedelta):
    return lambda aid, platform: Message(
        account_id=aid, fan_id=int(FAN), message_id=PLATFORM_MESSAGE[platform] + 2, direction="in",
        body="hey whats up", created_at=datetime.utcnow() - ago)



async def _seed_turn(aid: str, platform: str) -> dict:
    await _rows(_fan(), _out(timedelta(hours=2)), _in(timedelta(minutes=5)))(aid, platform)
    return {"only_fan_ids": [int(FAN)], "anchor": PLATFORM_MESSAGE[platform] + 2}


async def _seed_live_turn(aid: str, platform: str) -> dict:
    await _rows(lambda a, _p: AutomationRule(account_id=a, name="Full AI Chat", kind="full_ai_chat", is_enabled=True,
                                             steps_json="{}", trigger_json=json.dumps({"mode": "live"})))(aid, platform)
    return await _seed_turn(aid, platform)


def _profile(aid, _p):
    return FanProfile(account_id=aid, fan_id=int(FAN), nickname="Tom/Gym", short_bio="likes the gym")


def _audio(aid, platform):
    return MessageMedia(account_id=aid, fan_id=int(FAN), message_id=PLATFORM_MESSAGE[platform], media_id=6601,
                        type="audio")


async def _seed_landed_funnel_send(aid: str, platform: str) -> None:
    at = datetime.utcnow() - timedelta(hours=1)
    async with get_session() as s:
        funnel = MassMessageFunnel(name=f"funnel {aid}", opening_message="hey", steps_json=json.dumps(
            [{"step": 1, "messages": ["m1"]}, {"step": 2, "messages": ["m2"]}]))
        s.add(funnel)
        await s.flush()
        run = MassRun(account_id=aid, funnel_id=funnel.id, status="interrupted")
        s.add(run)
        await s.flush()
        s.add_all([
            Fan(account_id=aid, fan_id=int(FAN)),
            FunnelState(mass_run_id=run.id, fan_id=int(FAN), sending_at=at, unconfirmed_at=at, sending_ctx=json.dumps(
                {"replied": False, "bought": False, "substantive": False, "reply_text": None})),
            Message(account_id=aid, fan_id=int(FAN), message_id=PLATFORM_MESSAGE[platform], direction="out",
                    body="m1", media_count=0, created_at=at, automation_kind="reply_mass_funnel",
                    mass_run_id=run.id, funnel_step=1),
        ])



_NUDGE_CFG = _ai(nudge_config_json=json.dumps(
    {"quiet_hours": [], "require_welcomed": False, "nudge_line_image": False}))

SEEDS = {
    ("auto_follow", "run"): _rows(_fan()),
    ("expiry_message", "run"): _rows(_fan(), _rule("expiry_message")),
    ("expired_message", "run"): _rows(
        _fan(), _rule("expired_message"), lambda aid, _p: Fan(account_id=aid, fan_id=LAPSED),
        _snap(LAPSED, timedelta(days=2), expired_at=datetime.utcnow() - timedelta(hours=30))),
    ("resubscribe_message", "run"): _rows(
        _fan(), _rule("resubscribe_message"), _snap(1, timedelta(days=2)),
        _snap(int(FAN), timedelta(days=3), subscribe_at=datetime.utcnow() - timedelta(days=30))),
    ("nudge_online", "run"): _rows(_NUDGE_CFG, _seen(1, timedelta(days=1))),
    ("nudge_online_fire", "run"): _rows(_NUDGE_CFG, _rule("nudge_online"), _seen(int(FAN), timedelta(0))),
    ("customs_watch", "owed"): _rows(_fan(customs_owed_at=datetime.utcnow() - timedelta(hours=2)),
                                     _out(timedelta(hours=1)), _audio),
    ("purchase_followup", "run"): _rows(_fan(), _rule("purchase_followup", text="thanks babe"), _out(
        timedelta(hours=2), price_cents=500, is_paid=True, purchased_at=datetime.utcnow() - timedelta(hours=1))),
    ("birthday_message", "run"): _rows(_fan(birthday=datetime.utcnow().strftime("%m-%d")),
                                       _rule("birthday_message")),
    ("priority_mass", "list"): _payload_id("run_id", lambda aid, _p: PriorityMassRun(
        account_id=aid, text="priority hey", audience_json=json.dumps({"user_lists": [AUDIENCE_LIST]}))),
    ("reply_mass_funnel", "landed"): _seed_landed_funnel_send,
    ("full_ai_chat", "shadow"): _seed_turn,
    ("full_ai_chat", "live"): _seed_live_turn,
    ("promo_reactivate", "run"): _rows(_rule("promo_reactivate", dry_run=False), lambda aid, _p: PromoCampaign(
        account_id=aid, of_promo_id=7701, name="keep", discount_percent=50, subscribe_counts=10, subscribe_days=30,
        auto_reactivate=True, keep_host_id=HOST, keep_ticked_at=datetime.utcnow())),
    ("apply_profiles", "local"): _rows(_fan(hobbies="gym"), _profile),
    ("apply_profiles", "push"): _rows(_fan(hobbies="gym"), _profile),
    ("gen_info", "local"): _rows(_fan(notes="his own note"), _in(timedelta(hours=1))),
    ("gen_info", "push"): _rows(_fan(), _in(timedelta(hours=1))),
    ("process_old_fans", "local"): _rows(_fan()),
    ("process_old_fans", "push"): _rows(_fan(hobbies="gym"), _profile),
    ("autoreply", "run"): _rows(_ai(autoreply_config_json=json.dumps({"enabled": True})),
                                _fan(), _in(timedelta(hours=1))),
    ("send_followup", "run"): _rows(_fan(lifetime_spend_cents=500), _out(timedelta(hours=30))),
    ("welcome_chatter_for_info", "run"): _rows(_fan(), _out(timedelta(hours=2), automation_kind="send_welcome"),
                                               _in(timedelta(hours=1))),
    ("s4s_post", "run"): _s4s(),
    ("s4s_post", "media"): _s4s(media=True),
    ("s4s_check", "text_baseline"): _s4s({"id": 5501, "text": "go follow\n#advertisement"}),
    ("s4s_check", "empty_baseline"): _s4s({}),
    ("smart_list_sync", "sync"): _seed_active_list,
    ("unsend_messages", "mass"): _seed_broadcast_cache,
    ("unsend_messages", "chat"): _seed_own_message,
}


def _subscribed(fake) -> None:
    fake.notifications.insert(0, {
        "id": "900000000000000802", "accountId": fake.account_id, "type": 15016, "correlationId": "900000000000000502",
        "correlationGroupId": FAN, "acknowledgedAt": 0, "createdAt": int(datetime.utcnow().timestamp()),
        "metadata": json.dumps({"subscriptionStreak": 0})})


def _renewal_off(fake) -> None:
    fake.renewal_off(int((time.time() + 12 * 3600) * 1000))


FAKE_STATE = {("send_welcome", "run"): _subscribed, ("expiry_message", "run"): _renewal_off}

WORLDS = {("full_ai_chat", "shadow"): _jev_answers, ("full_ai_chat", "live"): _jev_answers}
