from __future__ import annotations

import contextlib
import json
from datetime import datetime, timedelta
from unittest.mock import patch

import llm_client
import tenant_keys
from _full_ai_fixtures import QUIET, FakeInfoJev, FakeJev, QuietHeatJev
from automations import _heat_jev, _info_jev, _router_jev
from db.engine import get_session
from db.models import (
    Account, AccountAiConfig, AutomationRule, Fan, FanProfile, FunnelState, MassBroadcastCache, MassMessageFunnel,
    MassRun, Message, MessageMedia, NudgeState, Post, S4SMedia, S4SProfile, S4SRequest, S4SSlot,
    SmartList, SubscriberSnapshot, User, UserAccount,
)
from of_client import OFAPIError, OFClient

FAN = "900000000000000002"
LAPSED = 900000000000000007
OWN_MESSAGE = "900000000000000302"
CAST = 7101
AUDIENCE_LIST = 702
PLATFORM_MESSAGE = {"fansly": 900000000000000303, "onlyfans": 8_700_303}

HOST = "kind-verdicts"
LLM_REPLY = "hey you, tell me more"
SPANISH_REPLY = "¿estás dormida? cuéntame más"
LLM_JSON = {"nickname": "Tom/Gym", "short_bio": "likes the gym", "hobbies": "gym"}


class _Download:
    status_code = 200

    def iter_content(self, chunk_size):
        return iter([b"jpeg"])

    def close(self):
        pass


class OFStandIn:
    WRITES = frozenset({"send_message", "unsend_message", "cancel_scheduled", "send_mass_message",
                        "create_list", "add_users_to_lists", "delete_list", "post_story_from_url", "follow_user",
                        "create_post", "delete_post", "set_fan_custom_name", "set_fan_note",
                        "mark_chat_read", "create_promo", "upload_media", "remove_user_from_list"})

    def __init__(self, aid: str) -> None:
        self.account_id = self.user_id = aid
        self.http, self.timeout_s = self, 30
        self.calls: list[str] = []
        self.send_recipients: list[str] = []
        self.unmodelled: list[str] = []

    def __getattr__(self, name: str):
        if name.startswith("__"):
            raise AttributeError(name)
        self.unmodelled.append(name)
        raise AssertionError(f"unmodelled OnlyFans call {name}")

    def send_message(self, chat_id, text, **_kw):
        self.calls.append("send_message")
        self.send_recipients.append(str(chat_id))
        return {"id": 8_800_000 + len(self.calls), "text": text,
                "createdAt": datetime.utcnow().isoformat() + "+00:00"}

    def unsend_message(self, message_id, with_user_id=None):
        self.calls.append("unsend_message")
        return {"success": True}

    def cancel_scheduled(self, queue_id):
        self.calls.append("cancel_scheduled")
        return {"success": True}

    def unsend_mass_message(self, queue_id):
        return self.cancel_scheduled(queue_id)

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

    def delete_list(self, list_id):
        self.calls.append("delete_list")
        return {"success": True}

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

    def following(self, *, offset=0, **_kw):
        self.calls.append("following")
        return {"list": [{"id": int(FAN)}] if offset == 0 else [], "hasMore": False}

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

    def my_settings(self):
        self.calls.append("my_settings")
        return {"replyOnSubscribe": True}

    def message_templates(self, **_kw):
        self.calls.append("message_templates")
        return [{"template": "reply_on_subscribe", "text": "<p>hi, welcome!</p>"}]

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

    def recent_expired_subscribers(self):
        self.calls.append("recent_expired_subscribers")
        return {"list": [{"id": LAPSED}], "hasMore": False}

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


def canned_llm(reply: str = LLM_REPLY):
    async def fire(url, headers, body, **_kw):
        content = json.dumps(LLM_JSON) if body.get("response_format") else reply
        return {"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}, 1
    return fire


def llm_says(reply: str):
    return lambda _aid: patch.object(llm_client, "_fire", canned_llm(reply))


async def no_key(_aid):
    return ""


async def _key(_aid):
    return "kind-verdicts-key"


@contextlib.contextmanager
def _jev_answers(_aid):
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



TAG_RULE = {"field": "tag", "op": "has", "value": "vip"}
CHAT_RULES = (TAG_RULE, {"field": "last_active_days", "op": "<=", "value": 7},
              {"field": "last_message_sent_at", "op": "within_last", "value": 7})
SPEND_RULE = {"field": "lifetime_spend", "op": ">=", "value": 10000}


def _lists(*lists: tuple[str, tuple[dict, ...], dict]):
    async def seed(aid: str, _platform: str) -> None:
        now = datetime.utcnow()
        async with get_session() as s:
            s.add(Fan(account_id=aid, fan_id=int(FAN), tags=json.dumps(["vip"]), lifetime_spend_cents=20000,
                      last_message_received_at=now - timedelta(days=1), last_message_sent_at=now - timedelta(days=1)))
            for name, rules, kw in lists:
                s.add(SmartList(account_id=aid, name=name, rules_json=json.dumps({"rules": list(rules)}),
                                **{"is_active": True, **kw}))
    return seed


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
    ("expiry_message", "run"): _rows(_fan(), _rule("expiry_message")),
    ("expired_message", "run"): _rows(
        _fan(), _rule("expired_message"), lambda aid, _p: Fan(account_id=aid, fan_id=LAPSED),
        _snap(LAPSED, timedelta(days=2), expired_at=datetime.utcnow() - timedelta(hours=30))),
    ("resubscribe_message", "run"): _rows(
        _fan(), _rule("resubscribe_message"), _snap(1, timedelta(days=2)),
        _snap(int(FAN), timedelta(days=3), subscribe_at=datetime.utcnow() - timedelta(days=30))),
    ("customs_watch", "owed"): _rows(_fan(customs_owed_at=datetime.utcnow() - timedelta(hours=2)),
                                     _out(timedelta(hours=1)), _audio),
    ("purchase_followup", "run"): _rows(_fan(), _rule("purchase_followup", text="thanks babe"), _out(
        timedelta(hours=2), price_cents=500, is_paid=True, purchased_at=datetime.utcnow() - timedelta(hours=1))),
    ("birthday_message", "run"): _rows(_fan(birthday=datetime.utcnow().strftime("%m-%d")),
                                       _rule("birthday_message")),
    ("reply_mass_funnel", "landed"): _seed_landed_funnel_send,
    ("full_ai_chat", "shadow"): _seed_turn,
    ("full_ai_chat", "live"): _seed_live_turn,
    ("welcome_chatter_for_info", "run"): _rows(_fan(), _out(timedelta(hours=2), automation_kind="send_welcome"),
                                               _in(timedelta(hours=1))),
    ("welcome_chatter_for_info", "spanish"): _rows(_fan(language="es"),
                                                   _out(timedelta(hours=2), automation_kind="send_welcome"),
                                                   _in(timedelta(hours=1))),
    ("unsend_messages", "mass"): _seed_broadcast_cache,
    ("unsend_messages", "chat"): _seed_own_message,
}


FAKE_STATE: dict = {}

WORLDS = {("full_ai_chat", "shadow"): _jev_answers, ("full_ai_chat", "live"): _jev_answers,
          ("welcome_chatter_for_info", "spanish"): llm_says(SPANISH_REPLY)}


def fan_groups(fake) -> list[str]:
    return [gid for gid, row in fake.groups.items() if row["partnerAccountId"] == FAN]


def threadless(fake) -> None:
    for gid in fan_groups(fake):
        del fake.groups[gid]


def fan_ids(start: int, n: int) -> list[int]:
    return list(range(start, start + n))


def tagged_lists(members: list[int], target: list[int], *rows: dict):
    async def seed(aid: str, _platform: str) -> None:
        async with get_session() as s:
            s.add_all([Fan(account_id=aid, fan_id=f, tags=json.dumps(["vip"])) for f in target])
            s.add_all([Fan(account_id=aid, fan_id=f) for f in sorted(set(members) - set(target))])
            s.add_all([SmartList(account_id=aid, rules_json=json.dumps({"rules": [TAG_RULE]}), is_active=True, **row)
                       for row in rows])
    return seed


def fansly_list(fake, members: list[int]) -> int:
    lid = fake.mint()
    fake.lists[lid] = {"accountId": fake.account_id, "type": 1, "label": "Chatty", "id": lid}
    fake.members[lid] = [str(m) for m in members]
    return int(lid)


class ListsOF(OFStandIn):
    def __init__(self, aid: str, lists: dict[int, list[int]]) -> None:
        super().__init__(aid)
        self.lists = {k: list(v) for k, v in lists.items()}
        self.bodies: list[tuple] = []

    def create_list(self, name):
        self.calls.append("create_list")
        lid = 701 + len(self.lists)
        self.lists[lid] = []
        return {"id": lid}

    def list_users_in(self, list_id, *, limit=20, offset=0):
        self.calls.append("list_users_in")
        if int(list_id) not in self.lists:
            raise OFAPIError("404 for lists", response=type("R", (), {"status_code": 404})())
        return [{"id": m} for m in self.lists[int(list_id)][offset:offset + limit]]

    def add_users_to_lists(self, body):
        self.bodies.append(("add", {k: list(v) for k, v in body.items()}))
        for lid, ids in body.items():
            self.lists[int(lid)] += ids
        return super().add_users_to_lists(body)

    def remove_user_from_list(self, list_id, user_id):
        self.calls.append("remove_user_from_list")
        self.bodies.append(("remove", int(list_id), int(user_id)))
        self.lists[int(list_id)].remove(int(user_id))
        return {}
