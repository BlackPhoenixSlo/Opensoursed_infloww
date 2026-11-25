#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402
import llm_client  # noqa: E402
from automations import _run_pool, send_welcome, welcome_compose, welcome_turn  # noqa: E402
from automation_executor import acquire_fan_lease, run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, AccountAiConfig, AutomationRule, AutomationRun, Fan, FanLease,
    FanProfile, FollowPingState, Message, NudgeState, ScheduledJob, SkipList,
    WelcomeSent,
)
from llm_client import LLMCapExceeded  # noqa: E402
from transaction_ingest import tip_ledger_body  # noqa: E402

OWN_ID = "999"



class FakeOF:

    def __init__(self, subs: list[dict], user_id: str = OWN_ID, *, vault: bool = False):
        self.user_id = user_id
        self._subs = subs
        self.sent: list[tuple[int, str, list]] = []
        self.prices: list[float | None] = []
        self.gifs: list[tuple[int, str, str]] = []
        self.gif_fails = False
        self.fail_texts: set[str] = set()
        self._next_id = 9_000_000_000_000
        self._vault = vault
        self.followed: list[int] = []
        self.resubscribed: list[int] = []
        self.profiles: dict[int, dict] = {}
        self.follow_fails: set[int] = set()
        self.paged = False
        self.offsets: list[int] = []

    def follow_user(self, user_id):
        if int(user_id) in self.follow_fails:
            raise RuntimeError(f"follow refused: {user_id}")
        self.followed.append(int(user_id))
        return {"ok": True}

    def resubscribe_user(self, user_id):
        self.resubscribed.append(int(user_id))
        return {"ok": True}

    def get_user(self, user_id) -> dict:
        return self.profiles.get(int(user_id), {"subscribePrice": 0})

    def notifications(self, *, limit: int = 10, offset: int = 0, type=None, **kw) -> dict:
        self.offsets.append(int(offset))
        subs = self._subs[offset:offset + limit] if self.paged else self._subs
        more = self.paged and offset + limit < len(self._subs)
        return {"list": [{"user": {k: v for k, v in s.items() if k != "createdAt"},
                          **({"createdAt": s["createdAt"]} if s.get("createdAt") else {})}
                         for s in subs], "hasMore": more}

    def send_message(self, chat_id, text, *, media_files=None, **kw) -> dict:
        gid = kw.get("giphy_id")
        if gid and self.gif_fails:
            raise RuntimeError("giphy id rejected")
        if text in self.fail_texts:
            raise RuntimeError(f"send refused: {text!r}")
        self._next_id += 1
        self.sent.append((int(chat_id), text, list(media_files or [])))
        self.prices.append(kw.get("price"))
        if gid:
            self.gifs.append((int(chat_id), text, str(gid)))
        return {
            "id": self._next_id,
            "text": f"<p>{text}</p>",
            # Every send gets this fixed stamp; handoff cases date injected rows just before it.
            "createdAt": "2026-06-04T12:00:00+00:00",
        }

    def mark_chat_read(self, chat_id) -> dict:
        return {"success": True}

    def set_fan_custom_name(self, user_id, name) -> dict:
        return {"success": True}

    def set_fan_note(self, user_id, note) -> dict:
        return {"success": True}

    def vault_lists(self, **kw) -> dict:
        if not self._vault:
            return {"list": []}
        return {"list": [{"id": 77, "name": "Bot"}, {"id": 9, "name": "other"}]}

    def vault_media(self, *, list_id=None, **kw) -> dict:
        if not self._vault or list_id != 77:
            return {"list": []}
        return {"list": [{"id": 501}, {"id": 502}, {"id": 503},
                         {"id": 504}, {"id": 505}, {"id": 506}]}


def _use_fake(subs: list[dict], *, vault: bool = False) -> FakeOF:
    fake = FakeOF(subs, vault=vault)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


def _patch_llm(reply: str = "heyy so happy you're here 💕") -> None:
    async def _fake_chat(**kw):
        return SimpleNamespace(content=reply)
    llm_client.chat = _fake_chat  # type: ignore[attr-defined]


def _patch_llm_cap() -> None:
    async def _raise(**kw):
        raise LLMCapExceeded("acc", 100, 200)
    llm_client.chat = _raise  # type: ignore[attr-defined]


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


def _sub(uid: int, name: str | None = None, username: str | None = None) -> dict:
    return {"id": uid, "name": name, "username": username or f"u{uid}"}



async def case_new_subs_get_one_welcome_each():
    aid = "acc_w1"
    await _seed_account(aid)
    _use_fake([_sub(1001, name="Bob"), _sub(1002, username="mystery_guy")])
    _patch_llm()

    res = await run_once(aid, "send_welcome", payload={})
    assert res["status"] == "ok", res
    assert res["new_subscribers"] == 2, res
    assert res["welcomes_sent"] == 2, res
    assert res["errors"] == 0 and res["skipped_locked"] == 0, res

    async with get_session() as s:
        ws = (await s.execute(
            select(WelcomeSent).where(WelcomeSent.account_id == aid)
        )).scalars().all()
        assert {w.fan_id for w in ws} == {1001, 1002}, [w.fan_id for w in ws]

        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid)
        )).scalars().all()
        assert len(msgs) == 2, f"two outbound rows, got {len(msgs)}"
        assert all(m.direction == "out" for m in msgs), [m.direction for m in msgs]
        assert all(m.body for m in msgs), "welcome body persisted"

        runs = (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == aid)
        )).scalars().all()
        assert len(runs) == 1 and runs[0].status == "ok", runs



async def case_no_dup_on_restart():
    aid = "acc_w2"
    await _seed_account(aid)
    _use_fake([_sub(2001, name="Cara")])
    _patch_llm()

    r1 = await run_once(aid, "send_welcome", payload={})
    assert r1["welcomes_sent"] == 1, r1

    r2 = await run_once(aid, "send_welcome", payload={})
    assert r2["status"] == "ok", r2
    assert r2["new_subscribers"] == 0, r2
    assert r2["welcomes_sent"] == 0, r2

    async with get_session() as s:
        ws = (await s.execute(
            select(WelcomeSent).where(WelcomeSent.account_id == aid)
        )).scalars().all()
        assert len(ws) == 1, f"still exactly one welcome_sent row, got {len(ws)}"
        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid)
        )).scalars().all()
        assert len(msgs) == 1, f"no duplicate message, got {len(msgs)}"



async def case_dedup_skips_preexisting():
    aid = "acc_w3"
    await _seed_account(aid)
    async with get_session() as s:
        s.add(WelcomeSent(account_id=aid, fan_id=3001, fan_username="old_fan"))
    _use_fake([_sub(3001, name="Old"), _sub(3002, name="New")])
    _patch_llm()

    res = await run_once(aid, "send_welcome", payload={})
    assert res["new_subscribers"] == 1, res
    assert res["welcomes_sent"] == 1, res

    async with get_session() as s:
        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid)
        )).scalars().all()
        assert {m.fan_id for m in msgs} == {3002}, [m.fan_id for m in msgs]



async def case_fan_lease_blocks_welcome():
    aid = "acc_w4"
    await _seed_account(aid)
    _use_fake([_sub(4001, name="Dee"), _sub(4002, name="Eve")])
    _patch_llm()

    assert await acquire_fan_lease(aid, 4001, "welcome_chatter_for_info", ttl_s=300) is True

    res = await run_once(aid, "send_welcome", payload={})
    assert res["skipped_locked"] == 1, res
    assert res["welcomes_sent"] == 1, res

    async with get_session() as s:
        ws = (await s.execute(
            select(WelcomeSent.fan_id).where(WelcomeSent.account_id == aid)
        )).all()
        assert {r[0] for r in ws} == {4002}, ws



async def case_cooldown_skips_welcome():
    aid = "acc_w4b"
    await _seed_account(aid)
    _use_fake([_sub(4101, name="Cool"), _sub(4102, name="Down")])
    _patch_llm()

    await ax.start_fan_cooldown(aid, 4101)

    res = await run_once(aid, "send_welcome", payload={})
    assert res["skipped_cooldown"] == 1, res
    assert res["welcomes_sent"] == 1, res
    async with get_session() as s:
        ws = (await s.execute(
            select(WelcomeSent.fan_id).where(WelcomeSent.account_id == aid)
        )).all()
        assert {r[0] for r in ws} == {4102}, ws



async def case_lease_released_on_send_so_the_rest_is_the_only_brake():
    aid = "acc_w4c"
    await _seed_account(aid)
    _use_fake([_sub(4201, name="Keep")])
    _patch_llm()

    res = await run_once(aid, "send_welcome", payload={})
    assert res["welcomes_sent"] == 1, res
    async with get_session() as s:
        assert await s.get(FanLease, (aid, 4201)) is None, \
            "lease HANDED BACK after a confirmed send — it must not outlast the rest"
        assert await ax.fan_on_cooldown(aid, 4201) is True, "the rest is in force"
        f = await s.get(Fan, (aid, 4201))
    left = (f.automation_paused_until - datetime.utcnow()).total_seconds()
    assert 0 < left <= welcome_turn.WELCOME_REST_S, f"{left}s left, cap {welcome_turn.WELCOME_REST_S}"
    assert welcome_turn.WELCOME_REST_S <= 180, "a new sub must not wait more than ~3 min"

    _use_fake([_sub(4202, name="Drop")])
    res2 = await run_once(aid, "send_welcome", payload={"dry_run": True})
    assert res2["welcomes_sent"] == 1, res2
    async with get_session() as s:
        assert await s.get(FanLease, (aid, 4202)) is None, "lease released on dry run"



async def case_dry_run_sends_nothing():
    aid = "acc_w5"
    await _seed_account(aid)
    fake = _use_fake([_sub(5001, name="Fay")])
    _patch_llm()

    res = await run_once(aid, "send_welcome", payload={"dry_run": True})
    assert res["welcomes_sent"] == 1, res
    assert fake.sent == [], "dry run must not call send_message"

    async with get_session() as s:
        ws = (await s.execute(
            select(WelcomeSent).where(WelcomeSent.account_id == aid)
        )).scalars().all()
        assert ws == [], "dry run must not mark welcome_sent"
        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid)
        )).scalars().all()
        assert msgs == [], "dry run writes no message row"



async def case_cap_never_costs_a_welcome():
    aid = "acc_w6"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(6001, username="gus_xo"), _sub(6002, username="hal_xo")])
    _patch_llm_cap()

    res = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert res["status"] == "ok", res
    assert res["welcomes_sent"] == 2, res
    assert fake.sent[0][1] == "Hey G-G-G-Gorgeous gus ! !!", fake.sent[0]
    assert fake.sent[1][1].startswith("doing "), fake.sent[1]

    async with get_session() as s:
        ws = (await s.execute(
            select(WelcomeSent).where(WelcomeSent.account_id == aid)
        )).scalars().all()
        assert len(ws) == 2, f"both fans welcomed despite the cap, got {len(ws)}"



async def case_with_image_attaches_bot_media():
    aid = "acc_w7"
    await _seed_account(aid)
    fake = _use_fake([_sub(7001, name="Ivy")], vault=True)
    _patch_llm()

    res = await run_once(aid, "send_welcome", payload={"with_image": True})
    assert res["welcomes_sent"] == 1, res
    assert res["image_attached"] == 1, res
    assert len(fake.sent) == 1, fake.sent
    _, _, media = fake.sent[0]
    assert len(media) == 1 and 501 <= media[0] <= 506, media



async def case_text_only_when_with_image_false():
    aid = "acc_w8"
    await _seed_account(aid)
    fake = _use_fake([_sub(8001, name="Jay")], vault=True)
    _patch_llm()

    res = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert res["welcomes_sent"] == 1, res
    assert res["image_attached"] == 0, res
    assert len(fake.sent) == 1, fake.sent
    _, _, media = fake.sent[0]
    assert media == [], media



async def case_with_image_no_bot_folder_sends_text():
    aid = "acc_w9"
    await _seed_account(aid)
    fake = _use_fake([_sub(9001, name="Kay")], vault=False)
    _patch_llm()

    res = await run_once(aid, "send_welcome", payload={"with_image": True})
    assert res["welcomes_sent"] == 1, res
    assert res["image_attached"] == 0, res
    _, _, media = fake.sent[0]
    assert media == [], media



def case_photo_index_deterministic_per_hour():
    expected = {
        0: 5, 3: 5, 4: 5,
        5: 0, 8: 0,
        9: 1, 11: 1,
        12: 2, 14: 2,
        15: 3, 17: 3,
        18: 4, 20: 4,
        21: 5, 23: 5,
    }
    for hour, idx in expected.items():
        got = welcome_compose._photo_index(hour)
        assert got == idx, f"hour {hour}: expected {idx}, got {got}"
    for hour in range(24):
        assert welcome_compose._photo_index(hour) == welcome_compose._photo_index(hour)


async def _seed_brain(aid: str) -> None:
    async with get_session() as s:
        s.add(AccountAiConfig(
            account_id=aid, utc_offset=0, location="Vancouver Island, Canada",
            time_activities_json=json.dumps(
                {k: f"doing {k} things" for k in
                 ("morning_1", "morning_2", "afternoon_1", "afternoon_2", "evening", "night")}),
        ))


async def case_real_name_no_nick_proposes_stutter():
    aid = "acc_w11"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(11001, name="Sofie")])
    async def _boom(**kw):
        raise AssertionError("LLM must not be called for the local template")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False})
    assert res["welcomes_sent"] == 1 and res["errors"] == 0, res
    assert len(fake.sent) == 2, fake.sent
    assert {fid for fid, _, _ in fake.sent} == {11001}, fake.sent
    b1, b2 = fake.sent[0][1], fake.sent[1][1]
    assert b1 == "Hey S-S-S-Sexy Sofie ! !!", b1
    assert b2.startswith("doing "), b2
    assert "in Vancouver Island, Canada" in b2, b2
    assert " in  in " not in b2 and b2.count("(") == b2.count(")"), b2
    assert "Will reply" not in b1 + b2, (b1, b2)


async def case_name_resolved_from_db_still_stutters():
    aid = "acc_w12"
    await _seed_account(aid)
    await _seed_brain(aid)
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=12001, real_name="Tom"))
    fake = _use_fake([_sub(12001, username="t_handle_88")])
    async def _boom(**kw):
        raise AssertionError("LLM must not be called when a name is known")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False})
    assert res["welcomes_sent"] == 1, res
    _, text, _ = fake.sent[0]
    assert text == "Hey T-T-T-Tasty Tom ! !!", text


async def case_welcome_name_resolution_matrix():
    aid = "acc_w_names"
    await _seed_account(aid)
    cases = [
        ("country label in both columns is not his name",
         dict(of_display_name="FanA577", generated_nickname="Canada/Office job/Spender",
              custom_nickname="Canada/Canada/office job", home_country="Canada"), None, None, ""),
        ("curated beats the raw OF display name",
         dict(of_display_name="Fan_e", custom_nickname="Tyren"), None, None, "Tyren"),
        ("HTML-escaped couple's account → the first name",
         dict(of_display_name="Chris&amp;Char", custom_nickname="Chris&amp;Char"),
         None, None, "Chris"),
        ("a handle is never minted into a name",
         dict(of_display_name="FanB10"), None, None, ""),
        ("curated 'First Last' greets by the FIRST name",
         dict(custom_nickname="Randy Lahey/Vancouver", of_display_name="RLdude"),
         None, None, "Randy"),
        ("a confirmed real_name still outranks everything",
         dict(real_name="Mike", custom_nickname="Garrett", of_display_name="zzz"),
         None, None, "Mike"),
        ("the gen_info profile nickname fills an empty row",
         dict(), "Sexy Sofie/Delta,Canada/30", None, "Sofie"),
        ("brand-new sub, no Fan row: the notification name is used",
         None, None, "Garrett Baydala", "Garrett"),
        ("...but not when that notif name is a handle",
         None, None, "u1000001", ""),
        ("his own city is not his name",
         dict(custom_nickname="Kelowna", home_city="Kelowna"), None, None, ""),
    ]
    for i, (label, cols, prof, notif, want) in enumerate(cases):
        fid = 14000 + i
        async with get_session() as s:
            if cols is not None:
                s.add(Fan(account_id=aid, fan_id=fid, **cols))
            if prof:
                s.add(FanProfile(account_id=aid, fan_id=fid, nickname=prof))
        got = await welcome_compose._resolve_welcome_name(
            aid, fid, {"name": notif} if notif else {})
        assert got == want, f"{label}: got {got!r}, want {want!r}"


async def case_random_handle_no_name_greets_deterministically():
    aid = "acc_w13"
    await _seed_account(aid)
    fake = _use_fake([_sub(13001, username="xx_gamer_99")])
    async def _boom(**kw):
        raise AssertionError("a nameless fan must NOT cost an LLM call")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert res["welcomes_sent"] == 1, res
    assert fake.sent[0][1] == "Hey G-G-G-Gorgeous gamer ! !!", fake.sent[0]

    assert welcome_compose._greet_token({"username": "u4471223"}) == "cutie"
    assert welcome_compose._greet_token({"username": "4471223"}) == "cutie"
    assert welcome_compose._greet_token({"username": "u4471223"}, "him") == "boy"
    assert "#" not in welcome_compose._local_greeting(
        welcome_compose._greet_token({"username": "u800000704"}))
    assert welcome_compose._greet_token({"username": "xx_rider_92"}) == "rider"
    assert welcome_compose._greet_token({"username": "bigdaddy69"}) == "bigdaddy"
    assert welcome_compose._greet_token({"name": "Zoe", "username": "zz"}) == "zoe"
    assert welcome_compose._greet_token({"username": "__99"}) == "cutie"
    assert welcome_compose._greet_token({}) == "cutie"


async def case_word_restriction_applied_to_sent_welcome():
    aid = "acc_w14"
    await _seed_account(aid)
    async with get_session() as s:
        s.add(AccountAiConfig(
            account_id=aid, utc_offset=0, location="Vancouver Island, Canada",
            time_activities_json=json.dumps(
                {k: "wanna meet up soon" for k in welcome_compose._SLOT_KEYS}),
        ))
    fake = _use_fake([_sub(14001, username="zz_handle_77")])

    res = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert res["welcomes_sent"] == 1, res
    sent_text = fake.sent[1][1]
    assert "meeet" in sent_text and "meet " not in sent_text, sent_text



async def case_slot_hour_roundtrip():
    for k in welcome_compose._SLOT_KEYS:
        h = welcome_compose._slot_hour(k)
        assert h is not None and welcome_compose._slot_key(h) == k, (k, h)
    assert welcome_compose._slot_hour("bogus") is None
    assert welcome_compose._slot_hour(None) is None



async def _seed_pin(aid: str, pins: dict) -> None:
    async with get_session() as s:
        cfg = await s.get(AccountAiConfig, aid)
        cfg.welcome_pinned_json = json.dumps(pins)


async def case_pinned_line_weekday_refresh():
    import re as _re
    today = welcome_compose._model_weekday(0)
    cfg = {"utc_offset": 0, "welcome_pins": {
        "afternoon_1": {"line": "just got back from the beach, Monday arvo lol",
                        "weekday": "Monday"},
        "night": {"line": "winding down, come say hi", "weekday": "Monday"},
    }}
    got = welcome_compose._pinned_line(cfg, 13)
    exp = ("just got back from the beach, Monday arvo lol" if today.lower() == "monday"
           else _re.sub(r"\bMonday\b", today, "just got back from the beach, Monday arvo lol"))
    assert got == exp, (got, exp)
    assert welcome_compose._pinned_line(cfg, 22) == "winding down, come say hi"
    assert welcome_compose._pinned_line(cfg, 7) is None

    stored = "Monday" if today != "Monday" else "Tuesday"
    lc = {"utc_offset": 0, "welcome_pins": {
        "afternoon_1": {"line": f"had a fun {stored.lower()} babe", "weekday": stored}}}
    assert welcome_compose._pinned_line(lc, 13) == f"had a fun {today.lower()} babe"
    uc = {"utc_offset": 0, "welcome_pins": {
        "afternoon_1": {"line": f"{stored.upper()} VIBES", "weekday": stored}}}
    assert welcome_compose._pinned_line(uc, 13) == f"{today.upper()} VIBES"


async def case_run_pin_ships_even_when_activity_blank():
    aid = "acc_w_pin_blank"
    await _seed_account(aid)
    async with get_session() as s:
        s.add(AccountAiConfig(account_id=aid, utc_offset=0, location="Argentina",
                              time_activities_json="{}"))
    line = "beach day vibes, come say hi"
    await _seed_pin(aid, {k: {"line": line, "weekday": "Monday"}
                          for k in welcome_compose._SLOT_KEYS})
    fake = _use_fake([_sub(42001, name="Sofie")])
    async def _boom(**kw):
        raise AssertionError("pinned slot must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert res["welcomes_sent"] == 1 and res["pinned_used"] == 1, res
    assert len(fake.sent) == 2, fake.sent
    assert fake.sent[0][1] == "Hey S-S-S-Sexy Sofie ! !!", fake.sent[0]
    assert fake.sent[1][1] == line, fake.sent[1]


async def case_run_uses_pinned_line_no_llm():
    aid = "acc_w_pin"
    await _seed_account(aid)
    await _seed_brain(aid)
    line = "beach day vibes, come say hi"
    await _seed_pin(aid, {k: {"line": line, "weekday": "Monday"}
                          for k in welcome_compose._SLOT_KEYS})
    fake = _use_fake([_sub(40001, name="Sofie")])
    async def _boom(**kw):
        raise AssertionError("pinned slot must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert res["welcomes_sent"] == 1 and res["pinned_used"] == 1, res
    assert len(fake.sent) == 2, fake.sent
    assert fake.sent[0][1] == "Hey S-S-S-Sexy Sofie ! !!", fake.sent[0]
    assert fake.sent[1][1] == line, fake.sent[1]


async def case_nameless_fan_gets_activity_bubble_and_pin():
    aid = "acc_w_pin_noname"
    await _seed_account(aid)
    await _seed_brain(aid)
    line = "beach day vibes, come say hi"
    await _seed_pin(aid, {k: {"line": line, "weekday": "Monday"}
                          for k in welcome_compose._SLOT_KEYS})
    fake = _use_fake([_sub(41001, username="xx_gamer_99")])
    async def _boom(**kw):
        raise AssertionError("pinned slot + nameless fan must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert res["welcomes_sent"] == 1 and res["pinned_used"] == 1, res
    assert len(fake.sent) == 2, fake.sent
    assert fake.sent[0][1] == "Hey G-G-G-Gorgeous gamer ! !!", fake.sent[0]
    assert fake.sent[1][1] == line, fake.sent[1]



async def case_time_only_bubble_is_clock_without_activity():
    today = welcome_compose._model_weekday(0)
    cfg = {"utc_offset": 0, "location": "Vancouver",
           "time_activities": {"afternoon_1": "just got back from the beach"}}

    long_ = welcome_compose._activity_bubble(cfg, 13)
    short = welcome_compose._activity_bubble(cfg, 13, time_only=True)
    assert long_ == [f"just got back from the beach... it's {today} afternoon in Vancouver"], long_
    assert short == [f"it's {today} afternoon in Vancouver"], short
    assert "beach" not in short[0], short

    assert welcome_compose._activity_bubble(cfg, 7) == []
    assert welcome_compose._activity_bubble(cfg, 7, time_only=True) == [
        f"it's {today} morning in Vancouver"]
    assert welcome_compose._activity_bubble(
        {"utc_offset": 0, "time_activities": {}}, 19, time_only=True) == [
        f"it's {today} evening"]


async def case_run_time_only_sends_short_second_bubble():
    aid = "acc_w_timeonly"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(43001, name="Sofie")])
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False,
                                  "time_only": True})
    assert res["welcomes_sent"] == 1, res
    assert len(fake.sent) == 2, fake.sent
    assert fake.sent[0][1] == "Hey S-S-S-Sexy Sofie ! !!", fake.sent[0]
    b2 = fake.sent[1][1]
    assert b2.startswith("it's "), b2
    assert "doing " not in b2, b2
    assert "Vancouver Island, Canada" in b2, b2


async def case_time_only_outranks_a_pinned_line():
    aid = "acc_w_timeonly_pin"
    await _seed_account(aid)
    await _seed_brain(aid)
    line = "beach day vibes, come say hi"
    await _seed_pin(aid, {k: {"line": line, "weekday": "Monday"}
                          for k in welcome_compose._SLOT_KEYS})
    fake = _use_fake([_sub(43101, name="Sofie"), _sub(43102, name="Mia")])
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False,
                                  "time_only": True, "test_fan": 43101,
                                  "test_name": "Sofie"})
    assert res["welcomes_sent"] == 1 and res["pinned_used"] == 0, res
    assert fake.sent[1][1].startswith("it's "), fake.sent[1]
    assert fake.sent[1][1] != line, fake.sent[1]

    fake.sent.clear()
    res2 = await run_once(aid, "send_welcome",
                          payload={"with_image": False,
                                   "test_fan": 43102, "test_name": "Mia"})
    assert res2["welcomes_sent"] == 1 and res2["pinned_used"] == 1, res2
    assert fake.sent[1][1] == line, fake.sent[1]


async def case_time_only_always_opens_with_its():
    aid = "acc_w_timeonly_its"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(43401, name="Nora"), _sub(43402, name="Owen")])
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False, "time_only": True})
    assert res["welcomes_sent"] == 2, res
    b2s = [t for i, (_, t, _) in enumerate(fake.sent) if i % 2]
    assert len(b2s) == 2 and all(t.startswith("it's ") for t in b2s), fake.sent



async def case_question_ships_verbatim_as_third_bubble():
    q = "so tell me, where are you from?"
    aid = "acc_w_question"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(44001, name="Sofie")])
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM — the question never does")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False,
                                  "question": q})
    assert res["welcomes_sent"] == 1, res
    assert len(fake.sent) == 3, fake.sent
    assert fake.sent[0][1] == "Hey S-S-S-Sexy Sofie ! !!", fake.sent[0]
    assert fake.sent[1][1].startswith("doing "), fake.sent[1]
    assert fake.sent[2][1] == q, fake.sent[2]
    assert fake.sent[2][2] == [], fake.sent[2]

    aid2 = "acc_w_question_pin"
    await _seed_account(aid2)
    await _seed_brain(aid2)
    line = "beach day vibes, come say hi"
    await _seed_pin(aid2, {k: {"line": line, "weekday": "Monday"}
                           for k in welcome_compose._SLOT_KEYS})
    fake2 = _use_fake([_sub(44002, name="Mia")])
    res2 = await run_once(aid2, "send_welcome",
                          payload={"with_image": False,
                                   "question": q})
    assert res2["welcomes_sent"] == 1 and res2["pinned_used"] == 1, res2
    assert [t for _, t, _ in fake2.sent[1:]] == [line, q], fake2.sent

    aid3 = "acc_w_question_blank"
    await _seed_account(aid3)
    await _seed_brain(aid3)
    fake3 = _use_fake([_sub(44003, name="Nora")])
    res3 = await run_once(aid3, "send_welcome",
                          payload={"with_image": False,
                                   "question": "   "})
    assert res3["welcomes_sent"] == 1, res3
    assert len(fake3.sent) == 2, fake3.sent


async def case_custom_message_replaces_the_burst():
    aid = "acc_w_message"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(45001, name="Sofie"), _sub(45002, username="x9_284")], vault=True)
    async def _boom(**kw):
        raise AssertionError("a custom welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome", payload={
        "with_image": True, "question": "what's yours?", "gif_id": "g123",
        "message": "  Hey {name}, so glad you're here!  "})
    assert res["welcomes_sent"] == 2, res
    assert res["image_attached"] == 0 and res["gifs_sent"] == 0, res
    assert sorted(fake.sent) == [
        (45001, "Hey Sofie, so glad you're here!", []),
        (45002, "Hey babe, so glad you're here!", []),
    ], fake.sent
    assert fake.gifs == [], fake.gifs

    aid2 = "acc_w_message_blank"
    await _seed_account(aid2)
    await _seed_brain(aid2)
    fake2 = _use_fake([_sub(45003, name="Nora")])
    res2 = await run_once(aid2, "send_welcome", payload={"with_image": False, "message": "   "})
    assert res2["welcomes_sent"] == 1, res2
    assert len(fake2.sent) == 2 and fake2.sent[0][1].startswith("Hey N-N-N-"), fake2.sent


def _stamp(minutes_ago: float) -> str:
    return (datetime.utcnow() - timedelta(minutes=minutes_ago)).isoformat() + "+00:00"


async def _unsend_jobs(aid: str) -> list[ScheduledJob]:
    async with get_session() as s:
        return list((await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == aid,
            ScheduledJob.kind == "unsend_messages"))).scalars().all())


async def case_custom_message_carries_its_media_price_and_auto_unsend():
    aid = "acc_w_msg_ppv"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(45101, name="Sofie")], vault=True)
    res = await run_once(aid, "send_welcome", payload={
        "message": "Hey {name}!", "media_ids": [601, 602], "price_cents": 800,
        "unsend_minutes": 30})
    assert res["welcomes_sent"] == 1, res
    assert fake.sent == [(45101, "Hey Sofie!", [601, 602])] and fake.prices == [8.0], (
        fake.sent, fake.prices)
    async with get_session() as s:
        rows = (await s.execute(select(Message).where(
            Message.account_id == aid, Message.automation_kind == "welcome"))).scalars().all()
    assert [r.price_cents for r in rows] == [800], rows
    assert await _unsend_jobs(aid) == []

    aid = "acc_w_msg_free"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(45102, name="Mia")])
    await run_once(aid, "send_welcome", payload={
        "message": "Hey {name}!", "media_ids": [603], "unsend_minutes": 30})
    assert fake.sent == [(45102, "Hey Mia!", [603])] and fake.prices == [None], fake.sent
    jobs = await _unsend_jobs(aid)
    assert len(jobs) == 1 and json.loads(jobs[0].payload_json)["targets"][0]["fan_id"] == 45102, jobs
    assert jobs[0].run_at > datetime.utcnow() + timedelta(minutes=29), jobs[0].run_at

    aid = "acc_w_burst_media"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(45103, name="Nora")])
    await run_once(aid, "send_welcome", payload={
        "with_image": False, "media_ids": [604], "price_cents": 800, "unsend_minutes": 30})
    assert fake.sent and all(m == [] for _, _, m in fake.sent), fake.sent
    assert set(fake.prices) == {None} and await _unsend_jobs(aid) == [], fake.prices


async def case_the_effective_and_expiry_dates_bound_the_welcome():
    aid = "acc_w_window"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([{**_sub(45201, name="A"), "createdAt": _stamp(30)},
                      {**_sub(45202, name="B"), "createdAt": _stamp(5)},
                      _sub(45203, name="C")])
    later = (datetime.utcnow() + timedelta(hours=1)).isoformat() + "+00:00"
    res = await run_once(aid, "send_welcome", payload={"message": "hi", "starts_at": later})
    assert res.get("reason") == "scheduled" and fake.sent == [], res
    res = await run_once(aid, "send_welcome", payload={"message": "hi", "ends_at": _stamp(1)})
    assert res.get("reason") == "expired" and fake.sent == [], res
    await run_once(aid, "send_welcome", payload={"message": "hi", "starts_at": later,
                                                 "test_fan": 45299})
    assert [f for f, _, _ in fake.sent] == [45299], fake.sent
    res = await run_once(aid, "send_welcome", payload={"message": "hi", "starts_at": _stamp(15)})
    assert sorted(f for f, _, _ in fake.sent) == [45202, 45203, 45299], fake.sent
    assert res["skipped_before_start"] == 1, res


async def case_the_random_delay_counts_from_the_subscribe():
    aid = "acc_w_delay"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([{**_sub(45301, name="A"), "createdAt": _stamp(1)},
                      {**_sub(45302, name="B"), "createdAt": _stamp(10)}])
    payload = {"message": "hi", "delay_range": [2, 5]}
    res = await run_once(aid, "send_welcome", payload=payload)
    assert [f for f, _, _ in fake.sent] == [45302] and res["delayed"] == 1, (res, fake.sent)
    async with get_session() as s:
        assert await s.get(WelcomeSent, (aid, 45301)) is None
    fake._subs[0]["createdAt"] = _stamp(10)
    res = await run_once(aid, "send_welcome", payload=payload)
    assert sorted(f for f, _, _ in fake.sent) == [45301, 45302] and res["delayed"] == 0, res


async def case_with_a_delay_the_feed_is_read_back_past_the_longest_delay():
    aid = "acc_w_delay_pages"
    await _seed_account(aid)
    await _seed_brain(aid)
    subs = [{**_sub(45501 + i, name=f"P{i}"), "createdAt": _stamp(m)}
            for i, m in enumerate((1, 2, 12, 13, 20, 30, 40))]
    fake = _use_fake(subs)
    fake.paged = True
    res = await run_once(aid, "send_welcome", payload={
        "message": "hi", "delay_range": [2, 5], "limit": 2, "max_welcomes": 10})
    assert fake.offsets == [0, 2, 4], fake.offsets
    welcomed = {f for f, _, _ in fake.sent}
    assert {45503, 45504, 45505, 45506} <= welcomed and 45501 not in welcomed, (res, fake.sent)
    assert 45507 not in welcomed, fake.sent
    aid = "acc_w_no_delay_pages"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake(subs)
    fake.paged = True
    await run_once(aid, "send_welcome", payload={"message": "hi", "limit": 2})
    assert fake.offsets == [0], fake.offsets


async def case_a_paid_welcome_never_re_sells_media_the_fan_owns():
    aid = "acc_w_owner"
    await _seed_account(aid)
    await _seed_brain(aid)
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=45601, message_id=45600, direction="out",
                      body="older set", price_cents=900, is_paid=True, media_ids="[702]",
                      created_at=datetime.utcnow() - timedelta(days=9)))
    fake = _use_fake([_sub(45601, name="Owns"), _sub(45602, name="New")])
    res = await run_once(aid, "send_welcome", payload={
        "message": "Hey {name}!", "media_ids": [701, 702], "price_cents": 800})
    assert res["welcomes_sent"] == 2, res
    by_fan = {f: (m, p) for (f, _, m), p in zip(fake.sent, fake.prices)}
    assert by_fan == {45601: ([], None), 45602: ([701, 702], 8.0)}, by_fan
    async with get_session() as s:
        rows = (await s.execute(select(Message).where(
            Message.account_id == aid, Message.automation_kind == "welcome"))).scalars().all()
    assert {r.fan_id: r.price_cents for r in rows} == {45601: 0, 45602: 800}, rows


async def case_a_failed_auto_unsend_queue_never_costs_the_welcome_claim():
    real = ax.enqueue_followup

    async def boom(*a, **kw):
        raise RuntimeError("db locked")
    ax.enqueue_followup = boom
    try:
        for early in (True, False):
            aid = f"acc_w_unsend_boom_{early}"
            await _seed_account(aid)
            await _seed_brain(aid)
            fake = _use_fake([_sub(45701, name="Boom")])
            payload = {"message": "hi", "unsend_minutes": 30, "human_pace": False,
                       "stop_on_reply": early}
            res = await run_once(aid, "send_welcome", payload=payload)
            assert res["welcomes_sent"] == 1, res
            async with get_session() as s:
                assert await s.get(WelcomeSent, (aid, 45701)) is not None
            await run_once(aid, "send_welcome", payload=payload)
            assert len(fake.sent) == 1, fake.sent
    finally:
        ax.enqueue_followup = real


def case_the_rule_routes_hold_the_delayed_welcome_settings_to_the_contract():
    import automation_rules_api as rules_api
    from fastapi import HTTPException
    ok = rules_api._validate_payload_for_kind("send_welcome", {
        "message": "hi", "delay_range": [5, 5], "media_ids": [1, 1, 2],
        "price_cents": 300, "starts_at": "2026-07-01T10:00:00Z", "unsend_minutes": 0})
    assert (ok["delay_range"], ok["media_ids"], ok["starts_at"]) == (
        [5, 6], [1, 2], "2026-07-01T10:00:00+00:00"), ok
    for bad in ({"price_cents": 299, "media_ids": [1]}, {"price_cents": 500},
                {"price_cents": 20_001, "media_ids": [1]},
                {"delay_range": [1]}, {"unsend_minutes": 23 * 60 + 1}, {"ends_at": "later"},
                {"starts_at": "2026-07-02T00:00:00Z", "ends_at": "2026-07-01T00:00:00Z"}):
        try:
            rules_api._validate_payload_for_kind("send_welcome", bad)
        except HTTPException as e:
            assert e.status_code == 422, e
        else:
            raise AssertionError(f"accepted {bad}")



_REAL_HOLD = send_welcome.hold_with_typing
_REAL_SLEEP = _run_pool._sleep


async def _no_jitter(seconds: float) -> None:
    await asyncio.sleep(0)


# Paced cases must patch hold_with_typing: test mode zeroes typing_wpm but not the sampler's quiet draws (real U(10,25)s sleeps).
def _record_holds(on_call=None) -> list[dict]:
    calls: list[dict] = []

    async def _rec(account_id, fan_id, seconds, *, typing_indicator=False,
                   quiet_s=0.0, think_at_s=0.0, think_for_s=0.0):
        calls.append({"fan_id": int(fan_id), "seconds": float(seconds),
                      "typing_indicator": bool(typing_indicator),
                      "quiet_s": float(quiet_s), "think_at_s": float(think_at_s),
                      "think_for_s": float(think_for_s)})
        await asyncio.sleep(0)
        if on_call is not None:
            await on_call(len(calls), calls[-1])

    async def _rec_jitter(seconds):
        calls.append({"fan_id": None, "seconds": float(seconds),
                      "typing_indicator": False, "quiet_s": 0.0,
                      "think_at_s": 0.0, "think_for_s": 0.0, "jitter": True})
        await asyncio.sleep(0)

    send_welcome.hold_with_typing = _rec  # type: ignore[assignment]
    _run_pool._sleep = _rec_jitter  # type: ignore[assignment]
    return calls


@asynccontextmanager
async def recording_holds(on_call=None):
    calls = _record_holds(on_call)
    try:
        yield calls
    finally:
        send_welcome.hold_with_typing = _REAL_HOLD  # type: ignore[assignment]
        _run_pool._sleep = _REAL_SLEEP  # type: ignore[assignment]


def case_hold_segments_are_the_four_shapes_and_they_sum():
    from automations.pacing import Pace
    seg = send_welcome._hold_segments

    out = seg(pace=None, typing_s=7.0, is_gif=False, typing_on=True,
              interruptible=True)
    assert len(out) == 1 and out[0].seconds == 7.0, out
    assert out[0].indicator is True and out[0].check_after is False, out

    out = seg(pace=None, typing_s=0.0, is_gif=True, typing_on=True,
              interruptible=True)
    assert len(out) == 1 and out[0].seconds == send_welcome._GIF_HOLD_S, out
    assert out[0].indicator is False and out[0].check_after is True, out
    assert seg(pace=None, typing_s=0.0, is_gif=True, typing_on=True,
               interruptible=False)[0].check_after is False

    pace = Pace(total_s=30.0, quiet_s=18.0, think_at_s=4.0, think_for_s=6.0)
    out = seg(pace=pace, typing_s=12.0, is_gif=False, typing_on=True,
              interruptible=True)
    assert len(out) == 2, out
    assert abs(sum(x.seconds for x in out) - 30.0) < 1e-9, out
    dark, typing = out
    assert dark.seconds == 18.0 and dark.indicator is False, dark
    assert dark.check_after is True, dark
    assert dark.quiet_s == 0.0, ("the dark half is a plain dark hold", dark)
    assert typing.seconds == 12.0 and typing.indicator is True, typing
    assert typing.check_after is False, ("she finishes what she is typing", typing)
    assert (typing.think_at_s, typing.think_for_s) == (4.0, 6.0), typing

    out = seg(pace=pace, typing_s=12.0, is_gif=False, typing_on=True,
              interruptible=False)
    assert len(out) == 1 and out[0].seconds == 30.0, out
    assert out[0].quiet_s == 18.0 and out[0].check_after is False, out
    flat = Pace(total_s=3.0, quiet_s=0.0)
    assert len(seg(pace=flat, typing_s=3.0, is_gif=False, typing_on=True,
                   interruptible=True)) == 1


async def case_flags_absent_every_hold_is_todays_flat_hold():
    aid = "acc_w_pace_off"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(47001, name="Sofie")], vault=True)
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]
    drew = {"n": 0}
    real_sampler = send_welcome.welcome_burst_pace
    def _tripwire(**kw):
        drew["n"] += 1
        return real_sampler(**kw)
    send_welcome.welcome_burst_pace = _tripwire  # type: ignore[assignment]

    async with recording_holds() as holds:
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": True,
                                      "question": "what's yours?",
                                      "gif_id": "l0MYt5jPR6QX5pnqM"})
        send_welcome.welcome_burst_pace = real_sampler  # type: ignore[assignment]

    assert res["welcomes_sent"] == 1 and len(fake.sent) == 4, (res, fake.sent)
    assert drew["n"] == 0, f"the sampler ran {drew['n']} times with the flag off"
    assert res["human_pace"] is False, res
    assert res["deferred_budget"] == 0 and res["hold_overrun_max_s"] == 0.0, res
    assert len(holds) == 4, holds
    assert all(h["fan_id"] == 47001 for h in holds), holds
    assert [h["seconds"] for h in holds] == [0.0, 0.0, 0.0, send_welcome._GIF_HOLD_S], holds
    assert all(h["quiet_s"] == 0.0 and h["think_at_s"] == 0.0
               and h["think_for_s"] == 0.0 for h in holds), holds


async def case_human_pace_hold_phases_match_the_table():
    from random import Random
    from automations.pacing import welcome_burst_pace

    aid = "acc_w_pace_on"
    fid = 47101
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    async with recording_holds() as holds:
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": True,
                                      "human_pace": True,
                                      "question": "what's yours?",
                                      "gif_id": "l0MYt5jPR6QX5pnqM"})

    assert res["welcomes_sent"] == 1 and res["human_pace"] is True, res
    assert len(fake.sent) == 4, fake.sent
    assert res["image_attached"] == 1, res
    assert len(holds) == 5, holds
    jitter, b0, b1, b2, gif = holds
    assert all(h["fan_id"] == fid for h in holds[1:]), holds

    assert jitter.get("jitter") is True, jitter
    assert 0.5 <= jitter["seconds"] <= 4.0, jitter

    def _expect(idx, role, has_image, text):
        return welcome_burst_pace(
            role=role, has_image=has_image, typing_s=0.0, text=text,
            rng=Random(f"welcome_pace:{aid}:{fid}:{idx}"))

    e0 = _expect(0, "opener", True, fake.sent[0][1])
    assert 6.0 <= b0["quiet_s"] <= 18.0, b0
    assert abs(b0["seconds"] - e0.total_s) < 1e-9, (b0, e0)
    assert abs(b0["quiet_s"] - e0.quiet_s) < 1e-9, (b0, e0)

    e1 = _expect(1, "gap", True, fake.sent[1][1])
    assert 10.0 <= b1["quiet_s"] <= 25.0, b1
    assert b1["seconds"] > b1["quiet_s"], b1
    assert abs(b1["seconds"] - e1.total_s) < 1e-9, (b1, e1)

    e2 = _expect(2, "tail", True, fake.sent[2][1])
    assert abs(b2["seconds"] - e2.total_s) < 1e-9, (b2, e2)
    assert b2["seconds"] < 25.0, b2

    egif = _expect(3, "gif", True, "")
    assert 2.0 <= gif["seconds"] <= 6.0, gif
    assert abs(gif["quiet_s"] - gif["seconds"]) < 1e-9, gif
    assert gif["typing_indicator"] is False, gif
    assert abs(gif["seconds"] - egif.total_s) < 1e-9, (gif, egif)

    from automations import rhythm as _rhythm
    assert all(h["seconds"] < _rhythm.INLINE_MAX_S for h in holds), holds


async def case_human_pace_the_question_keeps_its_own_beat_in_a_short_burst():
    from random import Random
    from automations.pacing import welcome_burst_pace

    q = "what's yours?"
    for shape, fid in (("skip_time_bubble", 47301), ("unfilled_slot", 47302)):
        aid = f"acc_w_role_{shape}"
        await _seed_account(aid)
        if shape == "skip_time_bubble":
            await _seed_brain(aid)
            payload = {"with_image": False, "human_pace": True,
                       "skip_time_bubble": True, "question": q}
        else:
            async with get_session() as _s:
                _s.add(AccountAiConfig(account_id=aid, utc_offset=0,
                                       location="Argentina",
                                       time_activities_json="{}"))
            payload = {"with_image": False, "human_pace": True,
                       "question": q}
        fake = _use_fake([_sub(fid, name="Sofie")])
        async def _boom(**kw):
            raise AssertionError("the welcome must NOT call the LLM")
        llm_client.chat = _boom  # type: ignore[attr-defined]

        async with recording_holds() as holds:
            res = await run_once(aid, "send_welcome", payload=payload)

        assert res["welcomes_sent"] == 1, (shape, res)
        assert len(fake.sent) == 2, (shape, fake.sent)
        assert fake.sent[1][1] == q, (shape, fake.sent)
        assert len(holds) == 3, (shape, holds)

        seed = Random(f"welcome_pace:{aid}:{fid}:1")
        as_tail = welcome_burst_pace(role="tail", has_image=False, typing_s=0.0,
                                     text=q, rng=seed)
        as_gap = welcome_burst_pace(role="gap", has_image=False, typing_s=0.0,
                                    text=q, rng=Random(f"welcome_pace:{aid}:{fid}:1"))
        got = holds[2]
        assert abs(got["seconds"] - as_tail.total_s) < 1e-9, (shape, got, as_tail)
        assert abs(got["quiet_s"] - as_tail.quiet_s) < 1e-9, (shape, got, as_tail)
        assert 10.0 <= as_gap.quiet_s <= 25.0, (shape, as_gap)
        assert abs(got["seconds"] - as_gap.total_s) > 1.0, (shape, got, as_gap)


async def case_human_pace_test_fan_is_exempt():
    aid = "acc_w_pace_test"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([], vault=True)
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    async with recording_holds() as holds:
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": False,
                                      "human_pace": True, "test_fan": 47201,
                                      "test_name": "Sofie"})

    assert res["welcomes_sent"] == 1 and res["human_pace"] is False, res
    assert len(fake.sent) == 2, fake.sent
    assert len(holds) == 2, holds
    assert all(h["seconds"] == 0.0 and h["quiet_s"] == 0.0 for h in holds), holds


async def case_human_pace_runs_fans_concurrently():
    aid = "acc_w_pace_conc"
    await _seed_account(aid)
    await _seed_brain(aid)
    fans = [47301, 47302, 47303, 47304]
    fake = _use_fake([_sub(f, name=n) for f, n in
                      zip(fans, ("Ada", "Ben", "Cal", "Dee"))])
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    real_cooldown = ax.fan_on_cooldown
    async def _explode(account_id, fan_id, **kw):
        if int(fan_id) == 47304:
            raise RuntimeError("boom on the cooldown read")
        return await real_cooldown(account_id, fan_id, **kw)
    ax.fan_on_cooldown = _explode  # type: ignore[assignment]

    async with recording_holds() as holds:
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": False,
                                      "human_pace": True})
        ax.fan_on_cooldown = real_cooldown  # type: ignore[assignment]

    assert res["welcomes_sent"] == 3, res
    assert res["errors"] == 1, f"the raising fan must be counted, not swallowed: {res}"
    assert res["run_wall_s"] >= 0.0, res
    first_three = [h.get("jitter") for h in holds[:3]]
    assert first_three == [True, True, True], f"the bursts ran serially: {holds[:3]}"
    async with get_session() as s:
        ws = {r[0] for r in (await s.execute(
            select(WelcomeSent.fan_id).where(WelcomeSent.account_id == aid))).all()}
        assert ws == {47301, 47302, 47303}, ws
        for f in fans:
            assert await s.get(FanLease, (aid, f)) is None, f"lease leaked for {f}"
    for f in (47301, 47302, 47303):
        assert await ax.fan_on_cooldown(aid, f) is True, f"{f} did not rest"


async def case_human_pace_wall_budget_defers_and_the_next_run_reserves():
    aid = "acc_w_pace_budget"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(47401, name="Ada"), _sub(47402, name="Ben")])
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    class _Clock:
        def __init__(self): self.t = 0.0
        def monotonic(self): return self.t
    clock = _Clock()

    calls: list[dict] = []
    async def _rec(account_id, fan_id, seconds, **kw):
        calls.append({"fan_id": int(fan_id), "seconds": float(seconds)})
        clock.t += 200.0
        await asyncio.sleep(0)

    real_time = send_welcome.time
    real_conc = send_welcome._PACE_CONCURRENCY
    real_warn = send_welcome._HOLD_OVERRUN_WARN_S
    send_welcome.time = clock            # type: ignore[assignment]
    send_welcome._PACE_CONCURRENCY = 1   # type: ignore[assignment]
    send_welcome._HOLD_OVERRUN_WARN_S = 1e9
    send_welcome.hold_with_typing = _rec  # type: ignore[assignment]
    _run_pool._sleep = _no_jitter  # type: ignore[assignment]
    try:
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": False,
                                      "human_pace": True})
    finally:
        send_welcome.hold_with_typing = _REAL_HOLD  # type: ignore[assignment]
        _run_pool._sleep = _REAL_SLEEP  # type: ignore[assignment]
        send_welcome.time = real_time               # type: ignore[assignment]
        send_welcome._PACE_CONCURRENCY = real_conc  # type: ignore[assignment]
        send_welcome._HOLD_OVERRUN_WARN_S = real_warn  # type: ignore[assignment]

    assert res["new_subscribers"] == 2, res
    assert res["welcomes_sent"] == 1, res
    assert res["deferred_budget"] == 1, res
    assert res["run_wall_s"] > send_welcome._RUN_WALL_BUDGET_S, res
    assert res["hold_overrun_max_s"] > 0.0, res
    assert {c["fan_id"] for c in calls} == {47401}, calls
    async with get_session() as s:
        ws = {r[0] for r in (await s.execute(
            select(WelcomeSent.fan_id).where(WelcomeSent.account_id == aid))).all()}
        assert ws == {47401}, ws
        assert await s.get(FanLease, (aid, 47402)) is None, "no lease for a deferred fan"

    async with recording_holds() as holds2:
        res2 = await run_once(aid, "send_welcome",
                              payload={"with_image": False,
                                       "human_pace": True})
    assert res2["new_subscribers"] == 1 and res2["welcomes_sent"] == 1, res2
    assert res2["deferred_budget"] == 0, res2
    assert {h["fan_id"] for h in holds2 if not h.get("jitter")} == {47402}, holds2
    async with get_session() as s:
        ws2 = {r[0] for r in (await s.execute(
            select(WelcomeSent.fan_id).where(WelcomeSent.account_id == aid))).all()}
        assert ws2 == {47401, 47402}, ws2


_OF_SEND_STAMP = datetime(2026, 6, 4, 12, 0, 0)


async def _inject_inbound(aid: str, fan_id: int, body: str, *, mid: int,
                          at: datetime, is_tip: bool = False) -> None:
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan_id, message_id=mid,
                      direction="in", body=body, is_tip=is_tip, created_at=at))


async def _welcome_rule(aid: str, kind: str, *, enabled: bool = True) -> None:
    async with get_session() as s:
        s.add(AutomationRule(account_id=aid, name=kind, kind=kind,
                             trigger_json=json.dumps({"every_seconds": 300}),
                             steps_json="{}", is_enabled=enabled))


async def _jobs(aid: str) -> list[ScheduledJob]:
    async with get_session() as s:
        return list((await s.execute(
            select(ScheduledJob).where(ScheduledJob.account_id == aid)
        )).scalars().all())


async def case_stop_on_reply_quiet_phase_drops_the_bubble():
    aid = "acc_w_sor_quiet"
    fid = 48001
    await _seed_account(aid)
    await _seed_brain(aid)
    await _welcome_rule(aid, "welcome_chatter_for_info")
    fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    seen = {"n": 0}
    async def _inject(n, entry):
        if len(fake.sent) != 1:
            return
        seen["n"] += 1
        if seen["n"] == 1:
            await _inject_inbound(aid, fid, "omg hey!! 😍", mid=770001,
                                  at=_OF_SEND_STAMP + timedelta(seconds=40))

    async with recording_holds(on_call=_inject) as holds:
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": True,
                                      "human_pace": True, "stop_on_reply": True,
                                      "question": "what's yours?",
                                      "gif_id": "l0MYt5jPR6QX5pnqM"})

    assert res["welcomes_sent"] == 1 and res["aborted_on_reply"] == 1, res
    assert res["stop_on_reply"] is True, res
    assert len(fake.sent) == 1, fake.sent
    assert fake.gifs == [], fake.gifs
    assert len(holds) == 3, holds
    quiet_first = holds[-1]
    assert quiet_first["fan_id"] == fid, quiet_first
    assert quiet_first["typing_indicator"] is False, quiet_first
    assert 10.0 <= quiet_first["seconds"] <= 25.0, quiet_first
    assert quiet_first["quiet_s"] == 0.0, \
        ("the quiet half is passed as a plain dark hold", quiet_first)
    async with get_session() as s:
        assert await s.get(WelcomeSent, (aid, fid)) is not None, "welcomed"
    assert res["handoff_enqueued"] == 0 and res["handoff_no_engine"] == 0, res
    assert await _jobs(aid) == [], "the turn is HIS — no job"


async def case_stop_on_reply_a_reply_during_the_dm_rate_wait_drops_the_bubble():
    import dm_rate
    import run_slot
    aid = "acc_w_sor_dmrate"
    fid = 48011
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
    saved_env, saved_w, saved_s = os.environ.get(dm_rate.KNOB), dm_rate.WINDOW_S, dm_rate.SLACK_S
    real_turn = dm_rate.turn
    waits: list[float] = []
    places: list[list] = []
    left: list = []
    real_send = fake.send_message

    def _send(*a, **kw):
        dm_rate.record(aid)
        return real_send(*a, **kw)
    fake.send_message = _send  # type: ignore[method-assign]

    async def _turn(account_id, **kw):
        if len(fake.sent) == 1 and not waits:
            await _inject_inbound(aid, fid, "omg hey!! 😍", mid=770011,
                                  at=_OF_SEND_STAMP + timedelta(seconds=40))
        w = await real_turn(account_id, **kw)
        if len(fake.sent) == 1:
            waits.append(w)
            places.append(dm_rate._TICKET.get().place)
        return w
    os.environ[dm_rate.KNOB] = "1"
    dm_rate.WINDOW_S, dm_rate.SLACK_S = 0.3, 0.0
    dm_rate._reset()
    dm_rate.turn = _turn  # type: ignore[assignment]
    try:
        async with recording_holds(), run_slot.hold(run_slot.SlotPool(1)):
            res = await run_once(aid, "send_welcome",
                                 payload={"with_image": False, "stop_on_reply": True,
                                          "question": "what's yours?"})
        left[:] = list(dm_rate._windows[aid].sent)
    finally:
        dm_rate.turn = real_turn  # type: ignore[assignment]
        dm_rate.WINDOW_S, dm_rate.SLACK_S = saved_w, saved_s
        dm_rate._reset()
        if saved_env is None:
            os.environ.pop(dm_rate.KNOB, None)
        else:
            os.environ[dm_rate.KNOB] = saved_env
    assert waits and waits[0] > 0, ("bubble 1's turn did not wait for a place", waits)
    assert res["welcomes_sent"] == 1 and res["aborted_on_reply"] == 1, res
    assert len(fake.sent) == 1, ("a bubble went out after his reply", fake.sent)
    assert await _jobs(aid) == [], "the turn is HIS: no job"
    assert places and not any(p is places[0] for p in left), (
        "the dropped bubble's DM place stayed in the window", left)


async def case_stop_on_reply_typing_phase_finishes_then_hands_the_turn_back():
    aid = "acc_w_sor_typing"
    fid = 48101
    await _seed_account(aid)
    await _seed_brain(aid)
    await _welcome_rule(aid, "welcome_chatter_for_info")
    fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    seen = {"n": 0}
    async def _inject(n, entry):
        if len(fake.sent) != 1:
            return
        seen["n"] += 1
        if seen["n"] == 2:
            await _inject_inbound(aid, fid, "hey gorgeous what u up to",
                                  mid=770101,
                                  at=_OF_SEND_STAMP - timedelta(seconds=10))

    async with recording_holds(on_call=_inject):
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": True,
                                      "human_pace": True, "stop_on_reply": True,
                                      "question": "what's yours?",
                                      "gif_id": "l0MYt5jPR6QX5pnqM"})

    assert res["welcomes_sent"] == 1 and res["aborted_on_reply"] == 1, res
    assert len(fake.sent) == 2, fake.sent
    assert fake.gifs == [], fake.gifs
    assert res["handoff_enqueued"] == 1 and res["handoff_no_engine"] == 0, res

    jobs = await _jobs(aid)
    assert len(jobs) == 1, [(j.kind, j.payload_json) for j in jobs]
    job = jobs[0]
    assert job.kind == "welcome_chatter_for_info", job.kind
    assert job.status == "pending", job.status
    assert json.loads(job.payload_json) == {
        "only_fan_ids": [fid], "force_ids": [fid], "turn_handoff_ids": [fid],
    }, job.payload_json
    due_in = (job.run_at - datetime.utcnow()).total_seconds()
    assert 150.0 < due_in <= 166.0, (due_in, job.run_at)


async def case_stop_on_reply_the_LAST_bubble_hands_the_turn_back_too():
    for paced, aid, fid in ((False, "acc_w_sor_tail", 48151),
                            (True, "acc_w_sor_tail_paced", 48151)):
        await _seed_account(aid)
        await _seed_brain(aid)
        await _welcome_rule(aid, "welcome_chatter_for_info")
        fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
        async def _boom(**kw):
            raise AssertionError("the welcome must NOT call the LLM")
        llm_client.chat = _boom  # type: ignore[attr-defined]

        async def _inject(n, entry, _aid=aid, _fid=fid, _fake=fake):
            if len(_fake.sent) == 2:
                await _inject_inbound(_aid, _fid, "wait are you real??",
                                      mid=770400 + _fid % 100,
                                      at=_OF_SEND_STAMP - timedelta(seconds=10))

        async with recording_holds(on_call=_inject) as holds:
            res = await run_once(aid, "send_welcome",
                                 payload={"with_image": True,
                                          "human_pace": paced,
                                          "stop_on_reply": True,
                                          "question": "what's yours?"})

        assert res["welcomes_sent"] == 1, (paced, res)
        assert len(fake.sent) == 3, (paced, fake.sent)
        assert res["aborted_on_reply"] == 0, (paced, res)
        assert len(holds) == (5 if paced else 3), (paced, holds)

        assert res["handoff_enqueued"] == 1, (paced, res)
        assert res["handoff_no_engine"] == 0, (paced, res)
        jobs = await _jobs(aid)
        assert len(jobs) == 1, (paced, [(j.kind, j.payload_json) for j in jobs])
        assert jobs[0].kind == "welcome_chatter_for_info", (paced, jobs[0].kind)
        assert json.loads(jobs[0].payload_json) == {
            "only_fan_ids": [fid], "force_ids": [fid], "turn_handoff_ids": [fid],
        }, (paced, jobs[0].payload_json)
        due_in = (jobs[0].run_at - datetime.utcnow()).total_seconds()
        assert 150.0 < due_in <= 166.0, (paced, due_in)


async def case_stop_on_reply_a_finished_burst_he_never_answered_hands_off_nothing():
    aid = "acc_w_sor_tail_quiet"
    fid = 48161
    await _seed_account(aid)
    await _seed_brain(aid)
    await _welcome_rule(aid, "welcome_chatter_for_info")
    fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]
    await _inject_inbound(aid, fid, "hey just subbed", mid=770501,
                          at=_OF_SEND_STAMP - timedelta(minutes=5))

    async with recording_holds():
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": True,
                                      "stop_on_reply": True,
                                      "question": "what's yours?"})

    assert res["welcomes_sent"] == 1 and len(fake.sent) == 3, (res, fake.sent)
    assert res["aborted_on_reply"] == 0, res
    assert res["handoff_enqueued"] == 0 and res["handoff_no_engine"] == 0, res
    assert await _jobs(aid) == [], "he never replied — nothing to hand over"


async def case_stop_on_reply_an_unstamped_send_hands_the_turn_back():
    aid = "acc_w_sor_unstamped"
    fid = 48601
    await _seed_account(aid)
    await _seed_brain(aid)
    await _welcome_rule(aid, "welcome_chatter_for_info")
    fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    def _blind_send(chat_id, text, *, media_files=None, **kw):
        fake.sent.append((int(chat_id), text, list(media_files or [])))
        return {"success": True}
    fake.send_message = _blind_send  # type: ignore[assignment]

    async def _inject(n, entry):
        if len(fake.sent) == 1:
            await _inject_inbound(aid, fid, "omg hi!!", mid=770601,
                                  at=_OF_SEND_STAMP + timedelta(hours=1))

    async with recording_holds(on_call=_inject):
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": True,
                                      "stop_on_reply": True,
                                      "question": "what's yours?"})

    assert res["welcomes_sent"] == 1 and res["aborted_on_reply"] == 1, res
    assert res["handoff_enqueued"] == 1, ("an unreadable send may not be read as "
                                          "'his turn'", res)
    jobs = await _jobs(aid)
    assert len(jobs) == 1 and jobs[0].kind == "welcome_chatter_for_info", jobs


async def case_stop_on_reply_suppresses_the_gif_paced_and_unpaced():
    for paced in (True, False):
        aid = f"acc_w_sor_gif_{'on' if paced else 'off'}"
        fid = 48201 if paced else 48202
        await _seed_account(aid)
        await _seed_brain(aid)
        fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
        async def _boom(**kw):
            raise AssertionError("the welcome must NOT call the LLM")
        llm_client.chat = _boom  # type: ignore[attr-defined]

        async def _inject(n, entry, _aid=aid, _fid=fid, _fake=fake):
            if len(_fake.sent) == 3:
                await _inject_inbound(_aid, _fid, "haha hi", mid=770200 + _fid % 10,
                                      at=_OF_SEND_STAMP + timedelta(seconds=90))

        async with recording_holds(on_call=_inject):
            res = await run_once(aid, "send_welcome",
                                 payload={"with_image": True,
                                          "human_pace": paced,
                                          "stop_on_reply": True,
                                          "question": "what's yours?",
                                          "gif_id": "l0MYt5jPR6QX5pnqM"})

        assert res["welcomes_sent"] == 1, (paced, res)
        assert res["aborted_on_reply"] == 1, (paced, res)
        assert len(fake.sent) == 3, (paced, fake.sent)
        assert fake.gifs == [], (paced, fake.gifs)
        assert res["gifs_sent"] == 0, (paced, res)


async def case_stop_on_reply_anchor_is_a_snapshot_not_any_inbound_ever():
    aid = "acc_w_sor_anchor"
    fid = 48301
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]
    await _inject_inbound(aid, fid, "hi just subbed!", mid=770301,
                          at=_OF_SEND_STAMP - timedelta(minutes=5))

    async with recording_holds():
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": True,
                                      "stop_on_reply": True,
                                      "question": "what's yours?",
                                      "gif_id": "l0MYt5jPR6QX5pnqM"})

    assert res["welcomes_sent"] == 1 and res["aborted_on_reply"] == 0, res
    assert len(fake.sent) == 4, fake.sent
    assert len(fake.gifs) == 1, fake.gifs
    assert res["reply_guard_off"] == 0, ("the guard really ran for him", res)
    assert await _jobs(aid) == [], "no reply arrived DURING the burst"


async def case_stop_on_reply_words_decide_not_the_message_type():
    async def _burst(fid: int, body: str, *, is_tip: bool) -> tuple[dict, FakeOF]:
        aid = f"acc_w_sor_words_{fid}"
        await _seed_account(aid)
        await _seed_brain(aid)
        fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
        async def _boom(**kw):
            raise AssertionError("the welcome must NOT call the LLM")
        llm_client.chat = _boom  # type: ignore[attr-defined]

        async def _inject(n, entry):
            if len(fake.sent) == 1 and n == 2:
                await _inject_inbound(aid, fid, body, mid=770400 + fid % 100,
                                      at=_OF_SEND_STAMP + timedelta(seconds=30),
                                      is_tip=is_tip)

        async with recording_holds(on_call=_inject):
            res = await run_once(aid, "send_welcome",
                                 payload={"with_image": True,
                                          "stop_on_reply": True,
                                          "question": "what's yours?",
                                          "gif_id": "l0MYt5jPR6QX5pnqM"})
        return res, fake

    res, fake = await _burst(48401, "hey you 🙈", is_tip=False)
    assert res["aborted_on_reply"] == 1 and len(fake.sent) == 2, (res, fake.sent)

    res, fake = await _burst(48402, "buy something nice babe", is_tip=True)
    assert res["aborted_on_reply"] == 1 and len(fake.sent) == 2, (res, fake.sent)

    res, fake = await _burst(48403, tip_ledger_body(500), is_tip=True)
    assert res["aborted_on_reply"] == 0, ("a bare tip is applause, not a turn", res)
    assert len(fake.sent) == 4 and len(fake.gifs) == 1, fake.sent

    res, fake = await _burst(48404, "", is_tip=False)
    assert res["aborted_on_reply"] == 0, ("a wordless photo is not text", res)
    assert len(fake.sent) == 4 and len(fake.gifs) == 1, fake.sent


async def case_stop_on_reply_query_failure_finishes_the_burst():
    real = welcome_turn.newest_worded_inbound

    aid = "acc_w_sor_qfail_anchor"
    fid = 48501
    await _seed_account(aid)
    await _seed_brain(aid)
    await _inject_inbound(aid, fid, "hi from before the welcome", mid=770501,
                          at=_OF_SEND_STAMP - timedelta(minutes=9))
    fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]
    async def _always_raises(account_id, fan_id):
        raise RuntimeError("database is locked")
    welcome_turn.newest_worded_inbound = _always_raises  # type: ignore[assignment]
    async with recording_holds():
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": True,
                                      "stop_on_reply": True,
                                      "question": "what's yours?",
                                      "gif_id": "l0MYt5jPR6QX5pnqM"})
        welcome_turn.newest_worded_inbound = real  # type: ignore[assignment]
    assert res["welcomes_sent"] == 1 and res["aborted_on_reply"] == 0, res
    assert len(fake.sent) == 4 and len(fake.gifs) == 1, fake.sent
    assert res["stop_on_reply"] is True and res["reply_guard_off"] == 1, res

    aid = "acc_w_sor_qfail_check"
    fid = 48502
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
    llm_client.chat = _boom  # type: ignore[attr-defined]
    n = {"calls": 0}
    async def _raises_after_the_anchor(account_id, fan_id):
        n["calls"] += 1
        if n["calls"] == 1:
            return await real(account_id, fan_id)
        raise RuntimeError("database is locked")
    welcome_turn.newest_worded_inbound = _raises_after_the_anchor  # type: ignore[assignment]
    async with recording_holds():
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": True,
                                      "stop_on_reply": True,
                                      "question": "what's yours?",
                                      "gif_id": "l0MYt5jPR6QX5pnqM"})
        welcome_turn.newest_worded_inbound = real  # type: ignore[assignment]
    assert n["calls"] > 1, "the checkpoints must actually have run"
    assert res["welcomes_sent"] == 1 and res["aborted_on_reply"] == 0, res
    assert len(fake.sent) == 4 and len(fake.gifs) == 1, fake.sent


async def case_stop_on_reply_handoff_engine_precedence():
    async def _abort_and_read_stats(aid: str, fid: int) -> dict:
        fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
        async def _boom(**kw):
            raise AssertionError("the welcome must NOT call the LLM")
        llm_client.chat = _boom  # type: ignore[attr-defined]
        async def _inject(n, entry):
            if len(fake.sent) == 1 and n == 2:
                await _inject_inbound(aid, fid, "hey!!", mid=770600 + fid % 100,
                                      at=_OF_SEND_STAMP - timedelta(seconds=20))
        async with recording_holds(on_call=_inject):
            return await run_once(aid, "send_welcome",
                                  payload={"with_image": True,
                                           "stop_on_reply": True,
                                           "question": "what's yours?"})

    aid = "acc_w_sor_engine_none"
    await _seed_account(aid)
    await _seed_brain(aid)
    res = await _abort_and_read_stats(aid, 48601)
    assert res["aborted_on_reply"] == 1, res
    assert res["handoff_no_engine"] == 1 and res["handoff_enqueued"] == 0, res
    assert await _jobs(aid) == [], "nothing to enqueue TO"

    aid = "acc_w_sor_engine_wcfi"
    await _seed_account(aid)
    await _seed_brain(aid)
    await _welcome_rule(aid, "welcome_chatter_for_info")
    res = await _abort_and_read_stats(aid, 48602)
    assert res["handoff_enqueued"] == 1, res
    assert [j.kind for j in await _jobs(aid)] == ["welcome_chatter_for_info"], \
        await _jobs(aid)

    aid = "acc_w_sor_engine_aic"
    await _seed_account(aid)
    async with get_session() as s:
        s.add(AccountAiConfig(
            account_id=aid, utc_offset=0, location="Vancouver Island, Canada",
            time_activities_json=json.dumps(
                {k: f"doing {k} things" for k in
                 ("morning_1", "morning_2", "afternoon_1", "afternoon_2",
                  "evening", "night")})))
    await _welcome_rule(aid, "welcome_chatter_for_info", enabled=False)
    res = await _abort_and_read_stats(aid, 48603)
    assert res["handoff_no_engine"] == 1 and res["handoff_enqueued"] == 0, res
    assert await _jobs(aid) == [], await _jobs(aid)


async def case_stop_on_reply_handoff_job_actually_gets_him_answered():
    aid = "acc_w_sor_e2e"
    fid = 48901
    await _seed_account(aid)
    await _seed_brain(aid)
    await _welcome_rule(aid, "welcome_chatter_for_info")
    fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    async def _inject(n, entry):
        if len(fake.sent) == 1 and n == 2:
            await _inject_inbound(aid, fid, "hey! whats your name",
                                  mid=770901,
                                  at=_OF_SEND_STAMP - timedelta(seconds=15))

    async with recording_holds(on_call=_inject):
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": True,
                                      "stop_on_reply": True,
                                      "question": "what's yours?",
                                      "gif_id": "l0MYt5jPR6QX5pnqM"})

    assert res["aborted_on_reply"] == 1 and res["handoff_enqueued"] == 1, res
    welcome_sends = len(fake.sent)
    assert welcome_sends == 2 and fake.gifs == [], fake.sent

    jobs = await _jobs(aid)
    assert len(jobs) == 1, jobs
    job_payload = json.loads(jobs[0].payload_json)

    async with get_session() as s:
        fan = await s.get(Fan, (aid, fid))
        fan.automation_paused_until = None
    _patch_llm("aww hey! im Sofie 😊 whats yours")

    res2 = await run_once(aid, jobs[0].kind, payload=job_payload)
    assert res2["status"] == "ok", res2
    assert res2["turn_handoffs"] == 1, res2
    assert res2["replies_sent"] == 1, res2
    assert len(fake.sent) > welcome_sends, ("he was answered on the wire",
                                            fake.sent)

    async with get_session() as s:
        rows = (await s.execute(
            select(Message).where(Message.account_id == aid,
                                  Message.fan_id == fid,
                                  Message.direction == "out",
                                  Message.automation_kind == "welcome_chatter_for_info")
        )).scalars().all()
        assert rows and all(r.body for r in rows), ("a real reply row", rows)


async def case_stop_on_reply_handoff_belts_a_restricted_fan():
    aid = "acc_w_sor_belt"
    fid = 48801
    await _seed_account(aid)
    await _seed_brain(aid)
    await _welcome_rule(aid, "welcome_chatter_for_info")
    async with get_session() as s:
        s.add(SkipList(account_id=aid, fan_id=fid, reason="manual_restrict"))
    fake = _use_fake([], vault=True)
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    async def _inject(n, entry):
        if len(fake.sent) == 1 and n == 2:
            await _inject_inbound(aid, fid, "hey!!", mid=770801,
                                  at=_OF_SEND_STAMP - timedelta(seconds=20))

    async with recording_holds(on_call=_inject):
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": True,
                                      "stop_on_reply": True,
                                      "test_fan": fid, "test_name": "Sofie",
                                      "question": "what's yours?"})

    assert res["aborted_on_reply"] == 1, res
    assert res["handoff_skipped_restricted"] == 1, res
    assert res["handoff_enqueued"] == 0 and res["handoff_no_engine"] == 0, res
    assert await _jobs(aid) == [], "a restricted fan gets no forced turn"


async def case_stop_on_reply_claims_the_welcome_before_the_burst_can_die():
    async def _crash_after_the_greeting(aid: str, fid: int, payload: dict) -> dict:
        await _seed_account(aid)
        await _seed_brain(aid)
        _use_fake([_sub(fid, name="Sofie")], vault=True)
        async def _boom(**kw):
            raise AssertionError("the welcome must NOT call the LLM")
        llm_client.chat = _boom  # type: ignore[attr-defined]
        calls = {"n": 0}
        async def _die(account_id, fan_id, seconds, **kw):
            calls["n"] += 1
            if calls["n"] > 1 and len(_fake_sent()) >= 1:
                raise RuntimeError("worker died mid-burst")
        def _fake_sent():
            return ax._make_client(aid).sent
        send_welcome.hold_with_typing = _die  # type: ignore[assignment]
        try:
            return await run_once(aid, "send_welcome",
                                  payload={"with_image": True,
                                           "question": "what's yours?", **payload})
        finally:
            send_welcome.hold_with_typing = _REAL_HOLD  # type: ignore[assignment]

    aid = "acc_w_sor_earlymark_on"
    res = await _crash_after_the_greeting(aid, 48701, {"stop_on_reply": True})
    assert res["status"] == "error", res
    async with get_session() as s:
        assert await s.get(WelcomeSent, (aid, 48701)) is not None, \
            "the greeting landed — he must never be greeted twice"

    aid = "acc_w_sor_earlymark_off"
    res = await _crash_after_the_greeting(aid, 48702, {})
    assert res["status"] == "error", res
    async with get_session() as s:
        assert await s.get(WelcomeSent, (aid, 48702)) is None, \
            "flags off must keep today's post-loop claim"



async def case_skip_time_bubble_drops_bubble_two_entirely():
    aid = "acc_w_skipbubble"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(46001, name="Sofie")])
    calls = {"n": 0}
    async def _counting(**kw):
        calls["n"] += 1
        return SimpleNamespace(content="a line nobody should see")
    llm_client.chat = _counting  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False, "skip_time_bubble": True,
                                  "question": "what's yours?",
                                  "gif_id": "l0MYt5jPR6QX5pnqM"})
    assert res["welcomes_sent"] == 1, res
    assert calls["n"] == 0, f"the skipped bubble still cost {calls['n']} LLM call(s)"
    assert len(fake.sent) == 3, fake.sent
    assert fake.sent[0][1] == "Hey S-S-S-Sexy Sofie ! !!", fake.sent[0]
    assert fake.sent[1][1] == "what's yours?", fake.sent[1]
    assert fake.sent[2][1] == "" and fake.gifs, fake.sent
    assert all("doing " not in t and not t.startswith("it's ")
               for _, t, _ in fake.sent), fake.sent


async def case_skip_time_bubble_outranks_time_only_and_a_pin():
    aid = "acc_w_skip_pin"
    await _seed_account(aid)
    await _seed_brain(aid)
    line = "beach day vibes, come say hi"
    await _seed_pin(aid, {k: {"line": line, "weekday": "Monday"}
                          for k in welcome_compose._SLOT_KEYS})
    fake = _use_fake([_sub(46101, name="Sofie")])
    async def _boom(**kw):
        raise AssertionError("a dropped bubble must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False, "time_only": True,
                                  "skip_time_bubble": True,
                                  "question": "what's yours?"})
    assert res["welcomes_sent"] == 1 and res["pinned_used"] == 0, res
    assert [t for _, t, _ in fake.sent] == ["Hey S-S-S-Sexy Sofie ! !!",
                                            "what's yours?"], fake.sent

    fake.sent.clear()
    res2 = await run_once(aid, "send_welcome",
                          payload={"with_image": False, "question": "what's yours?",
                                   "test_fan": 46102, "test_name": "Mia"})
    assert res2["welcomes_sent"] == 1 and res2["pinned_used"] == 1, res2
    assert [t for _, t, _ in fake.sent] == ["Hey M-M-M-Mighty Mia ! !!", line,
                                            "what's yours?"], fake.sent


async def case_skip_time_bubble_absent_composes_todays_bubbles():
    shapes: list[list[str]] = []
    for i, extra in enumerate(({}, {"skip_time_bubble": False})):
        aid = f"acc_w_skip_off{i}"
        await _seed_account(aid)
        await _seed_brain(aid)
        fake = _use_fake([_sub(46201 + i, name="Sofie")])
        async def _boom(**kw):
            raise AssertionError("the welcome must NOT call the LLM")
        llm_client.chat = _boom  # type: ignore[attr-defined]
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": False,
                                      "question": "what's yours?", **extra})
        assert res["welcomes_sent"] == 1, res
        shapes.append([t for _, t, _ in fake.sent])
    assert shapes[0] == shapes[1], shapes
    assert len(shapes[0]) == 3, shapes[0]
    assert shapes[0][0] == "Hey S-S-S-Sexy Sofie ! !!", shapes[0]
    assert shapes[0][1].startswith("doing "), shapes[0]
    assert shapes[0][2] == "what's yours?", shapes[0]


async def case_extract_filters_non_subscribe_notifications():
    feed = {"list": [
        {"type": "subscribed", "subType": "new_subscriber", "user": {"id": 111, "name": "Sub One"}},
        {"type": "tip",        "user": {"id": 222, "name": "Tipper"}},
        {"type": "comment",    "user": {"id": 333, "name": "Commenter"}},
        {"type": "subscribed", "subType": "returning_subscriber", "user": {"id": 444, "name": "Sub Two"}},
        {"user": {"id": 555, "name": "Untyped"}},
    ]}
    got = {s["id"] for s in send_welcome._extract_new_subscribers(feed)}
    assert got == {111, 444, 555}, got


async def case_gif_ships_as_fourth_bubble():
    aid = "acc_w_gif"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(45001, name="Sofie")])
    async def _boom(**kw):
        raise AssertionError("a picked GIF must never reach the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False,
                                  "question": "what's yours?",
                                  "gif_id": "l0MYt5jPR6QX5pnqM"})
    assert res["welcomes_sent"] == 1, res
    assert res["gifs_sent"] == 1, res
    assert len(fake.sent) == 4, fake.sent
    assert fake.sent[0][1] == "Hey S-S-S-Sexy Sofie ! !!", fake.sent[0]
    assert fake.sent[1][1].startswith("doing "), fake.sent[1]
    assert fake.sent[2][1] == "what's yours?", fake.sent[2]
    assert fake.sent[3][1] == "", fake.sent[3]
    assert fake.sent[3][2] == [], fake.sent[3]
    assert fake.gifs == [(45001, "", "l0MYt5jPR6QX5pnqM")], fake.gifs

    aid2 = "acc_w_gif_off"
    await _seed_account(aid2)
    await _seed_brain(aid2)
    fake2 = _use_fake([_sub(45002, name="Sofie")])
    res2 = await run_once(aid2, "send_welcome",
                          payload={"with_image": False,
                                   "question": "what's yours?", "gif_id": "  "})
    assert res2["gifs_sent"] == 0, res2
    assert len(fake2.sent) == 3, fake2.sent
    assert fake2.gifs == [], fake2.gifs


async def case_gif_failure_never_costs_the_welcome():
    aid = "acc_w_gif_fail"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(45101, name="Sofie")])
    fake.gif_fails = True
    async def _boom(**kw):
        raise AssertionError("the welcome must not call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False,
                                  "question": "what's yours?", "gif_id": "dead_id"})
    assert res["welcomes_sent"] == 1, res
    assert res["gifs_sent"] == 0, res
    assert res["errors"] == 0, res
    assert len(fake.sent) == 3, fake.sent
    async with get_session() as s:
        rows = (await s.execute(
            select(WelcomeSent.fan_id).where(WelcomeSent.account_id == aid)
        )).scalars().all()
    assert list(rows) == [45101], rows

    res2 = await run_once(aid, "send_welcome",
                          payload={"with_image": False,
                                   "question": "what's yours?", "gif_id": "dead_id"})
    assert res2["welcomes_sent"] == 0, res2
    assert len(fake.sent) == 3, fake.sent


async def case_burst_abort_takes_the_gif_with_it():
    aid = "acc_w_gif_abort"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(45301, name="Sofie")])
    fake.fail_texts = {"what's yours?"}
    async def _boom(**kw):
        raise AssertionError("the welcome must not call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False,
                                  "question": "what's yours?",
                                  "gif_id": "l0MYt5jPR6QX5pnqM"})
    assert res["welcomes_sent"] == 1, res
    assert len(fake.sent) == 2, fake.sent
    assert fake.gifs == [], fake.gifs
    assert res["gifs_sent"] == 0, res


async def case_unreachable_sub_claimed_not_retried():
    aid = "acc_w_unreach"
    await _seed_account(aid)
    fake = _use_fake([_sub(7501, name="Ghost")])
    def _raise(chat_id, text, **kw):
        raise Exception(
            f"404 for https://onlyfans.com/api2/v2/chats/{chat_id}/messages\n"
            '{"error":{"code":0,"message":"User not found"}}'
        )
    fake.send_message = _raise
    _patch_llm()

    r1 = await run_once(aid, "send_welcome", payload={})
    assert r1["welcomes_sent"] == 0 and r1["errors"] == 1, r1
    async with get_session() as s:
        ws = await s.get(WelcomeSent, (aid, 7501))
        assert ws is not None, "welcome_sent claimed → never retried"
        row = await s.get(SkipList, (aid, 7501))
        assert row is not None and row.reason == "unreachable", row

    r2 = await run_once(aid, "send_welcome", payload={})
    assert r2["new_subscribers"] == 0 and r2["errors"] == 0, r2
    assert r2["welcomes_sent"] == 0, r2



async def case_two_bubbles_image_on_first_only():
    aid = "acc_w_2bub"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(16001, name="Mia")], vault=True)
    _patch_llm()

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": True})
    assert res["welcomes_sent"] == 1 and res["image_attached"] == 1, res
    assert len(fake.sent) == 2, fake.sent
    _, b1, media1 = fake.sent[0]
    _, b2, media2 = fake.sent[1]
    assert b1 == "Hey M-M-M-Mighty Mia ! !!", b1
    assert len(media1) == 1 and 501 <= media1[0] <= 506, media1
    assert media2 == [], media2
    async with get_session() as s:
        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid))).scalars().all()
        assert len(msgs) == 2, f"both bubbles persisted, got {len(msgs)}"
        ws = (await s.execute(
            select(WelcomeSent).where(WelcomeSent.account_id == aid))).scalars().all()
        assert len(ws) == 1, ws


async def case_second_bubble_send_failure_still_marks_welcomed():
    aid = "acc_w_b2fail"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(20001, name="Sky")])
    _patch_llm()
    calls = {"n": 0}
    _orig_send = fake.send_message
    def _flaky(chat_id, text, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise Exception("network blip")
        return _orig_send(chat_id, text, **kw)
    fake.send_message = _flaky

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False})
    assert res["welcomes_sent"] == 1 and res["errors"] == 0, res
    assert len(fake.sent) == 1, fake.sent
    async with get_session() as s:
        assert await s.get(WelcomeSent, (aid, 20001)) is not None, "claimed"
        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid))).scalars().all()
        assert len(msgs) == 1, msgs

    r2 = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert r2["new_subscribers"] == 0 and r2["welcomes_sent"] == 0, r2



def _msgs(aid, fid, *, out=0, inn=0):
    rows = []
    mid = fid * 1000
    for _ in range(out):
        mid += 1
        rows.append(Message(account_id=aid, fan_id=fid, message_id=mid, direction="out",
                            body="x", created_at=datetime(2026, 6, 1)))
    for _ in range(inn):
        mid += 1
        rows.append(Message(account_id=aid, fan_id=fid, message_id=mid, direction="in",
                            body="x", created_at=datetime(2026, 6, 1)))
    return rows


async def case_skips_established_keeps_lightly_touched_new():
    aid = "acc_w_hist"
    await _seed_account(aid)
    async with get_session() as s:
        for r in (_msgs(aid, 6001, out=3) + _msgs(aid, 6003, out=2, inn=5)
                  + _msgs(aid, 6004, inn=9)):
            s.add(r)
    _use_fake([_sub(6001, name="Whale"), _sub(6002, name="Newbie"),
               _sub(6003, name="Masshit"), _sub(6004, name="Chatty")])
    _patch_llm()

    res = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert res["skipped_existing"] == 2, res
    assert res["welcomes_sent"] == 2, res
    async with get_session() as s:
        ws = (await s.execute(
            select(WelcomeSent.fan_id).where(WelcomeSent.account_id == aid))).all()
        assert {r[0] for r in ws} == {6002, 6003}, ws



async def case_contact_guard_skips_recent_nudge():
    aid = "acc_w_guard"
    await _seed_account(aid)
    async with get_session() as s:
        s.add(NudgeState(account_id=aid, fan_id=7001, last_nudged_at=datetime.utcnow()))
    _use_fake([_sub(7001, name="Touched"), _sub(7002, name="Fresh")])
    _patch_llm()

    res = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert res["skipped_guard"] == 1, res
    assert res["skipped_existing"] == 0, res
    assert res["welcomes_sent"] == 1, res
    async with get_session() as s:
        ws = (await s.execute(
            select(WelcomeSent.fan_id).where(WelcomeSent.account_id == aid))).all()
        assert {r[0] for r in ws} == {7002}, ws

    res2 = await run_once(aid, "send_welcome", payload={"with_image": False, "guard_hours": 0})
    assert res2["skipped_guard"] == 0 and res2["welcomes_sent"] == 1, res2



async def case_curated_nick_beats_raw_of_name():
    aid = "acc_w_name"
    await _seed_account(aid)
    await _seed_brain(aid)
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=8001,
                  custom_nickname="Garrett/Kelowna,Canada/Horny/CustomVideo"))
    fake = _use_fake([_sub(8001, name="Kyle")])
    async def _boom(**kw):
        raise AssertionError("LLM must not be called — a curated name resolves locally")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False})
    assert res["welcomes_sent"] == 1, res
    _, text, _ = fake.sent[0]
    assert text.startswith("Hey G-G-G-Gorgeous Garrett ! !!"), text
    assert all("Kyle" not in t for _, t, _ in fake.sent), fake.sent



async def case_test_fan_bypasses_new_gates():
    aid = "acc_w_force"
    await _seed_account(aid)
    async with get_session() as s:
        for r in _msgs(aid, 9001, out=5, inn=10):
            s.add(r)
        s.add(NudgeState(account_id=aid, fan_id=9001, last_nudged_at=datetime.utcnow()))
    _use_fake([])
    _patch_llm()

    res = await run_once(aid, "send_welcome",
                         payload={"test_fan": 9001, "test_name": "Sam", "with_image": False})
    assert res["welcomes_sent"] == 1, res
    assert res["skipped_existing"] == 0 and res["skipped_guard"] == 0, res



async def case_follow_back_all_new_subs_by_default():
    aid = "acc_w_fb1"
    await _seed_account(aid)
    fake = _use_fake([_sub(31001, name="Ann"), _sub(31002, name="Ben")])
    reads: list[int] = []
    fake.get_user = lambda uid: (reads.append(int(uid)), {"subscribePrice": 0})[1]
    _patch_llm()

    res = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert res["welcomes_sent"] == 2, res
    assert res["followed_back"] == 2, res
    assert res["follow_back_errors"] == 0, res
    assert sorted(fake.followed) == [31001, 31002], fake.followed
    assert sorted(reads) == [31001, 31002], \
        f"the gate is on by default and must read every profile, got {reads}"


async def case_follow_back_gate_defaults_ON_and_skips_a_priced_sub():
    aid = "acc_w_fb_default_gate"
    await _seed_account(aid)
    fake = _use_fake([_sub(31701, name="Free"), _sub(31702, name="Paid")])
    fake.profiles = {31701: {"subscribePrice": 0}, 31702: {"subscribePrice": 15}}
    _patch_llm()

    res = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert res["welcomes_sent"] == 2, res
    assert res["followed_back"] == 1, res
    assert res["follow_back_paid_skipped"] == 1, res
    assert fake.followed == [31701], \
        f"a priced sub was followed on the default payload: {fake.followed}"


async def case_follow_back_gate_off_follows_blind_with_no_read():
    aid = "acc_w_fb_ungated"
    await _seed_account(aid)
    fake = _use_fake([_sub(31801, name="Free"), _sub(31802, name="Paid")])
    reads: list[int] = []
    fake.get_user = lambda uid: (reads.append(int(uid)), {"subscribePrice": 15})[1]
    _patch_llm()

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False, "follow_back_gate": False})
    assert res["welcomes_sent"] == 2, res
    assert res["followed_back"] == 2, res
    assert sorted(fake.followed) == [31801, 31802], fake.followed
    assert reads == [], f"ungated follow-back reads no profiles, got {reads}"


# MONEY: a stored null follow_back_gate means the default (price-check on), not False.
async def case_follow_back_null_means_the_default_not_off():
    aid = "acc_w_fb_null"
    await _seed_account(aid)
    fake = _use_fake([_sub(31901, name="Free"), _sub(31902, name="Paid")])
    fake.profiles = {31901: {"subscribePrice": 0}, 31902: {"subscribePrice": 15}}
    _patch_llm()

    res = await run_once(aid, "send_welcome", payload={
        "with_image": False, "follow_back": None, "follow_back_gate": None})
    assert res["welcomes_sent"] == 2, res
    assert res["followed_back"] == 1, res
    assert res["follow_back_paid_skipped"] == 1, res
    assert fake.followed == [31901], \
        f"a null gate bought a priced sub a subscription: {fake.followed}"
    assert res["follow_back"] is True and res["follow_back_gate"] is True, res


async def case_run_stats_carry_the_follow_back_knobs():
    aid = "acc_w_fb_stats"
    await _seed_account(aid)
    fake = _use_fake([_sub(32001, name="Ann")])
    fake.profiles = {32001: {"subscribePrice": 0}}
    _patch_llm()

    on = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert on["follow_back"] is True and on["follow_back_gate"] is True, on
    assert on["followed_back"] == 1, on

    aid2 = "acc_w_fb_stats_off"
    await _seed_account(aid2)
    _use_fake([_sub(32002, name="Ben")])
    _patch_llm()
    off = await run_once(aid2, "send_welcome", payload={
        "with_image": False, "follow_back": False})
    assert off["follow_back"] is False, off
    assert off["followed_back"] == 0, off


async def case_follow_back_off_when_switched_off():
    aid = "acc_w_fb2"
    await _seed_account(aid)
    fake = _use_fake([_sub(31101, name="Cal")])
    _patch_llm()

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False, "follow_back": False})
    assert res["welcomes_sent"] == 1, res
    assert res["followed_back"] == 0, res
    assert fake.followed == [], fake.followed


async def case_follow_back_failure_never_costs_the_welcome():
    aid = "acc_w_fb3"
    await _seed_account(aid)
    fake = _use_fake([_sub(31201, name="Dee")])
    fake.follow_fails = {31201}
    _patch_llm()

    res = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert res["welcomes_sent"] == 1, res
    assert res["followed_back"] == 0 and res["follow_back_errors"] == 1, res
    assert res["errors"] == 0, f"a failed follow is not a welcome error: {res}"
    async with get_session() as s:
        assert await s.get(WelcomeSent, (aid, 31201)) is not None, "still claimed"

    r2 = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert r2["welcomes_sent"] == 0 and r2["followed_back"] == 0, r2


async def case_follow_back_dry_run_follows_nobody():
    aid = "acc_w_fb4"
    await _seed_account(aid)
    fake = _use_fake([_sub(31301, name="Eve")])
    _patch_llm()

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False, "dry_run": True})
    assert res["followed_back"] == 0, res
    assert fake.followed == [], fake.followed


async def case_follow_back_gate_skips_paid_and_unreadable_profiles():
    aid = "acc_w_fb5"
    await _seed_account(aid)
    fake = _use_fake([_sub(31401, name="Free"), _sub(31402, name="Paid"),
                      _sub(31403, name="Unknown")])
    fake.profiles = {
        31401: {"subscribePrice": 0},
        31402: {"subscribePrice": 9.99},
        31403: {},
    }
    _patch_llm()

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False, "follow_back_gate": True})
    assert res["welcomes_sent"] == 3, res
    assert res["followed_back"] == 1, res
    assert res["follow_back_paid_skipped"] == 1, res
    assert res["follow_back_no_price"] == 1, res
    assert fake.followed == [31401], fake.followed


async def case_follow_back_gate_resubscribes_a_lapsed_edge():
    aid = "acc_w_fb6"
    await _seed_account(aid)
    fake = _use_fake([_sub(31501, name="Lapsed"), _sub(31502, name="Current")])
    fake.profiles = {
        31501: {"subscribePrice": 0, "subscribedByExpireDate": "2026-01-01T00:00:00+00:00"},
        31502: {"subscribePrice": 0, "subscribedBy": True},
    }
    _patch_llm()

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False, "follow_back_gate": True})
    assert res["welcomes_sent"] == 2, res
    assert res["followed_back"] == 1, res
    assert res["follow_back_already"] == 1, res
    assert fake.resubscribed == [31501], fake.resubscribed
    assert fake.followed == [], fake.followed


async def case_follow_back_is_auto_follows_gate_not_a_copy_of_it():
    from automations import send_welcome as sw
    from automations import auto_follow as af

    assert not hasattr(sw, "_follow_back_outcome"), \
        "the copied classifier is back"
    assert not hasattr(sw, "_follow_back"), "the copied follow body is back"
    assert sw.gated_follow is af.gated_follow

    aid = "acc_w_fb_shared"
    await _seed_account(aid)
    fake = _use_fake([_sub(31601, name="Free")])
    fake.profiles = {31601: {"subscribePrice": 0}}
    _patch_llm()

    seen: list[tuple] = []
    real = af.gated_follow

    async def _spy(client, fan_id, *, account_id, unfollow_first=False, money_gate=True):
        seen.append((int(fan_id), unfollow_first, money_gate))
        return await real(client, fan_id, account_id=account_id,
                          unfollow_first=unfollow_first, money_gate=money_gate)

    sw.gated_follow = _spy          # type: ignore[assignment]
    try:
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": False,
                                      "follow_back_gate": True})
    finally:
        sw.gated_follow = real      # type: ignore[assignment]

    assert res["welcomes_sent"] == 1 and res["followed_back"] == 1, res
    assert seen == [(31601, False, True)], seen


async def case_an_unknown_follow_back_outcome_is_booked_under_its_own_name():
    from automations import send_welcome as sw
    from automations import auto_follow as af

    aid = "acc_w_fb_unknown"
    await _seed_account(aid)
    fake = _use_fake([_sub(31701, name="Free")])
    fake.profiles = {31701: {"subscribePrice": 0}}
    _patch_llm()

    real = af.gated_follow

    async def _stub(client, fan_id, *, account_id, unfollow_first=False, money_gate=True):
        return "shadow_banned"

    sw.gated_follow = _stub         # type: ignore[assignment]
    try:
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": False,
                                      "follow_back_gate": True})
    finally:
        sw.gated_follow = real      # type: ignore[assignment]

    assert res["welcomes_sent"] == 1, res
    assert res["follow_back_errors"] == 0 and res["errors"] == 0, res
    assert res["follow_back_no_price"] == 0, res
    assert res["follow_back_already"] == 0, res
    assert res["follow_back_paid_skipped"] == 0, res
    assert res["follow_back_outcomes"] == {"shadow_banned": 1}, res


async def case_follow_back_on_fansly_follows_without_a_price_to_read():
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2] / "fansly"))
    from fansly_shim import of_user
    aid = "acc_w_fb_fansly"
    await _seed_account(aid)
    fake = _use_fake([_sub(91001, name="Bob")])
    reads: list[int] = []
    fake.get_user = lambda uid: (reads.append(int(uid)), of_user(
        {"id": str(uid), "username": "bob", "displayName": "Bob",
         "subscriptionTiers": [{"id": "t1", "price": 5000}]}))[1]
    _patch_llm()
    real_platform = ax.account_registry.get_platform
    ax.account_registry.get_platform = lambda a: "fansly" if a == aid else "onlyfans"  # type: ignore[assignment]
    try:
        res = await run_once(aid, "send_welcome", payload={"with_image": False})
    finally:
        ax.account_registry.get_platform = real_platform  # type: ignore[assignment]
    assert res["welcomes_sent"] == 1, res
    assert fake.followed == [91001], (res, fake.followed)
    assert res["followed_back"] == 1 and res["follow_back_no_price"] == 0, res
    assert reads == [], ("no price to read on Fansly", reads)


async def case_pace_and_stop_default_ON_in_production_OFF_in_tests():
    saved = os.environ.get("CHATTERLY_TEST_MODE")
    try:
        os.environ.pop("CHATTERLY_TEST_MODE", None)
        for key in ("human_pace", "stop_on_reply"):
            assert send_welcome._on_unless_off({}, key) is True, key
            assert send_welcome._on_unless_off({key: False}, key) is False, key
            assert send_welcome._on_unless_off({key: True}, key) is True, key
            assert send_welcome._on_unless_off({key: None}, key) is True, key

        os.environ["CHATTERLY_TEST_MODE"] = "1"
        for key in ("human_pace", "stop_on_reply"):
            assert send_welcome._on_unless_off({}, key) is False, key
            assert send_welcome._on_unless_off({key: True}, key) is True, key
            assert send_welcome._on_unless_off({key: False}, key) is False, key

        from automations._common import _DEFAULT_TYPING_WPM, load_typing_wpm, test_mode
        for off in ("0", "false", "no", "off", ""):
            os.environ["CHATTERLY_TEST_MODE"] = off
            assert test_mode() is False, off
            for key in ("human_pace", "stop_on_reply"):
                assert send_welcome._on_unless_off({}, key) is True, (off, key)
            assert await load_typing_wpm("acc_w_no_such_account") == _DEFAULT_TYPING_WPM, off
        for on in ("1", "true", "yes"):
            os.environ["CHATTERLY_TEST_MODE"] = on
            assert test_mode() is True, on
            assert send_welcome._on_unless_off({}, "human_pace") is False, on
            assert await load_typing_wpm("acc_w_no_such_account") == 0.0, on
    finally:
        if saved is None:
            os.environ.pop("CHATTERLY_TEST_MODE", None)
        else:
            os.environ["CHATTERLY_TEST_MODE"] = saved


async def case_follow_back_under_human_pace():
    aid = "acc_w_fb_paced"
    await _seed_account(aid)
    await _seed_brain(aid)
    fans = (32001, 32002, 32003)
    fake = _use_fake([_sub(f, name=n) for f, n in zip(fans, ("Ada", "Ben", "Cal"))])
    reads: list[int] = []
    fake.get_user = lambda uid: (reads.append(int(uid)), {"subscribePrice": 0})[1]
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    holds = _record_holds()
    try:
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": False,
                                      "human_pace": True, "follow_back": True})
    finally:
        send_welcome.hold_with_typing = _REAL_HOLD  # type: ignore[assignment]
        _run_pool._sleep = _REAL_SLEEP  # type: ignore[assignment]

    assert res["human_pace"] is True, res
    assert res["welcomes_sent"] == 3, res
    assert res["followed_back"] == 3, res
    assert res["follow_back_errors"] == 0 and res["errors"] == 0, res
    assert set(fake.followed) == set(fans), fake.followed
    assert len(fake.followed) == 3, f"a fan was followed twice: {fake.followed}"
    assert sorted(reads) == sorted(fans), f"one gated read per fan, got {reads}"
    assert [h.get("jitter") for h in holds[:3]] == [True] * 3, holds[:3]
    async with get_session() as s:
        stamped = {int(r[0]) for r in (await s.execute(
            select(FollowPingState.fan_id)
            .where(FollowPingState.account_id == aid))).all()}
    assert stamped == set(fans), f"follow-back must stamp the ping ledger: {stamped}"


async def case_follow_back_ledger_write_failure_is_not_an_error():
    aid = "acc_w_fb_ledger"
    await _seed_account(aid)
    fake = _use_fake([_sub(34001, name="Ann")])
    _patch_llm()
    real_stamp = send_welcome.stamp_ping
    async def _boom(account_id, fan_id):
        raise RuntimeError("db went away mid-stamp")
    send_welcome.stamp_ping = _boom  # type: ignore[assignment]
    try:
        res = await run_once(aid, "send_welcome", payload={"with_image": False})
    finally:
        send_welcome.stamp_ping = real_stamp  # type: ignore[assignment]

    assert res["welcomes_sent"] == 1, res
    assert fake.followed == [34001], fake.followed
    assert res["followed_back"] == 1, res
    assert res["follow_back_errors"] == 0, (
        f"a lost ledger write is not a failed follow: {res}")
    assert res["errors"] == 0, res


async def case_paced_run_cancelled_raises_not_returns():
    aid = "acc_w_pace_cancel"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(f, name=n) for f, n in
                      zip((33001, 33002), ("Ada", "Ben"))])
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    async def _cancel_me(account_id, fan_id, seconds, **kw):
        raise asyncio.CancelledError()
    send_welcome.hold_with_typing = _cancel_me  # type: ignore[assignment]
    _run_pool._sleep = _no_jitter  # type: ignore[assignment]

    raised = None
    try:
        await send_welcome.run(aid, {"with_image": False,
                                     "human_pace": True}, run_id=0)
    except asyncio.CancelledError as e:
        raised = e
    except BaseException as e:                      # pragma: no cover - diagnosis
        raised = e
    finally:
        send_welcome.hold_with_typing = _REAL_HOLD  # type: ignore[assignment]
        _run_pool._sleep = _REAL_SLEEP  # type: ignore[assignment]

    assert isinstance(raised, asyncio.CancelledError), (
        f"a cancelled child must propagate, got {raised!r}")
    assert fake.sent == [], f"nothing should have shipped: {fake.sent}"


async def case_paced_cancel_while_parked_takes_the_spawned_bursts_down():
    aid = "acc_w_pace_cancel_parked"
    await _seed_account(aid)
    await _seed_brain(aid)
    n = send_welcome._PACE_CONCURRENCY + 4
    fans = [48401 + i for i in range(n)]
    fake = _use_fake([_sub(f, name=f"F{f}") for f in fans])
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    gate = asyncio.Event()
    admitted: list[int] = []
    async def _park(account_id, fan_id, seconds, **kw):
        admitted.append(int(fan_id))
        await gate.wait()
    send_welcome.hold_with_typing = _park  # type: ignore[assignment]
    _run_pool._sleep = _no_jitter  # type: ignore[assignment]

    task = asyncio.create_task(send_welcome.run(
        aid, {"with_image": False, "human_pace": True},
        run_id=0))
    try:
        for _ in range(400):
            if len(admitted) >= send_welcome._PACE_CONCURRENCY:
                break
            await asyncio.sleep(0.01)
        assert len(admitted) >= send_welcome._PACE_CONCURRENCY, (
            f"the admit loop never filled the semaphore: {admitted}")
        assert len(admitted) == send_welcome._PACE_CONCURRENCY, (
            f"more tasks than slots — the parent is not parked: {admitted}")

        sends_at_cancel = len(fake.sent)
        follows_at_cancel = len(fake.followed)
        task.cancel()

        raised = None
        try:
            await task
        except asyncio.CancelledError as e:
            raised = e
        except BaseException as e:                  # pragma: no cover - diagnosis
            raised = e
        assert isinstance(raised, asyncio.CancelledError), (
            f"a cancel while parked must propagate, got {raised!r}")

        async with get_session() as s:
            held = (await s.execute(select(FanLease.fan_id)
                                    .where(FanLease.account_id == aid))).all()
            assert held == [], f"a cancelled run left leases behind: {held}"

        gate.set()
        for _ in range(50):
            await asyncio.sleep(0.01)

        assert len(fake.sent) == sends_at_cancel, (
            f"{len(fake.sent) - sends_at_cancel} DM(s) shipped AFTER the run was "
            f"cancelled: {fake.sent[sends_at_cancel:]}")
        assert len(fake.followed) == follows_at_cancel, (
            f"{len(fake.followed) - follows_at_cancel} follow(s) fired AFTER the "
            f"run was cancelled: {fake.followed[follows_at_cancel:]}")
        async with get_session() as s:
            ws = (await s.execute(select(WelcomeSent.fan_id)
                                  .where(WelcomeSent.account_id == aid))).all()
            assert ws == [], f"a cancelled run claimed welcomes: {ws}"
    finally:
        gate.set()
        send_welcome.hold_with_typing = _REAL_HOLD  # type: ignore[assignment]
        _run_pool._sleep = _REAL_SLEEP  # type: ignore[assignment]



async def _welcome_follow_ups(aid: str) -> list[ScheduledJob]:
    async with get_session() as s:
        return list((await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == aid, ScheduledJob.kind == "send_welcome",
            ScheduledJob.status == "pending",
            ScheduledJob.payload_json.contains('"follow_up"')).order_by(ScheduledJob.id))).scalars())


async def _take_welcome_follow_up(aid: str, fan_id: int) -> dict:
    job = (await _welcome_follow_ups(aid))[0]
    async with get_session() as s:
        (await s.get(ScheduledJob, job.id)).status = "done"
        fan = (await s.execute(select(Fan).where(
            Fan.account_id == aid, Fan.fan_id == fan_id))).scalar_one_or_none()
        if fan is not None:
            fan.automation_paused_until = None
    return json.loads(job.payload_json)


async def case_a_message_list_is_its_variants_one_picked_per_fan():
    aid = "acc_w_variant"
    await _seed_account(aid)
    await _seed_brain(aid)
    names = ["Ann", "Bea", "Cat", "Dee", "Eve", "Fay", "Gia", "Hal", "Ivy", "Joy", "Kim", "Liv"]
    fake = _use_fake([_sub(46001 + i, name=n) for i, n in enumerate(names)])
    async def _boom(**kw):
        raise AssertionError("a written welcome must not call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]
    variants = ["hi {name}, so glad you're here", "welcome {name}!!", " "]

    res = await run_once(aid, "send_welcome", payload={
        "with_image": False, "question": "what's yours?", "message": variants})
    assert res["welcomes_sent"] == 12 and res["message_variants"] == 2, res
    got = {fid: t for fid, t, _ in fake.sent}
    assert len(fake.sent) == 12, fake.sent
    for i in range(12):
        picked = send_welcome.pick(variants[:2], "welcome", aid, 46001 + i)
        assert got[46001 + i] == picked.replace("{name}", names[i]), got
    assert len(set(got.values())) > 2 and {t.split()[0] for t in got.values()} == {"hi", "welcome"}


async def case_welcome_follow_ups_go_out_after_the_burst_and_stop_on_a_reply():
    aid = "acc_w_followups"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(46101, name="Mia")])
    _patch_llm()
    steps = [{"text": "still there?", "delay_minutes": 30},
             {"text": "miss u", "delay_minutes": 60}]

    res = await run_once(aid, "send_welcome", payload={
        "with_image": False, "follow_ups": steps})
    assert res["welcomes_sent"] == 1 and res["follow_ups_queued"] == 1, res
    jobs = await _welcome_follow_ups(aid)
    assert len(jobs) == 1, jobs
    wait = jobs[0].run_at - datetime.utcnow()
    assert timedelta(minutes=29) < wait <= timedelta(minutes=30), wait

    burst = len(fake.sent)
    r1 = await run_once(aid, "send_welcome", payload=await _take_welcome_follow_up(aid, 46101))
    assert r1["sent"] == 1, r1
    assert fake.sent[burst:] == [(46101, "still there?", [])], fake.sent
    assert len(await _welcome_follow_ups(aid)) == 1

    await _inject_inbound(aid, 46101, "hey you", mid=46101_001, at=datetime.utcnow())
    r2 = await run_once(aid, "send_welcome", payload=await _take_welcome_follow_up(aid, 46101))
    assert r2["status"] == "skipped" and r2["reason"] == "stopped_on_reply", r2
    assert len(fake.sent) == burst + 1, fake.sent
    assert await _welcome_follow_ups(aid) == []


def _of_welcome(fake: FakeOF, *, on, text: str = "<p>hi, welcome!</p>", media=0) -> None:
    def settings():
        if on is None:
            raise RuntimeError("session dead")
        return {"replyOnSubscribe": on}
    fake.my_settings = settings  # type: ignore[attr-defined]
    fake.message_templates = lambda **kw: [  # type: ignore[attr-defined]
        {"id": 1, "template": None, "text": "saved reply"},
        {"id": 2, "template": "reply_on_subscribe", "text": text, "mediaCount": media}]


async def case_after_of_welcome_sends_nothing_while_ofs_welcome_is_on():
    aid = "acc_w_after_of"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(46201, name="Nora")])
    _of_welcome(fake, on=True)
    _patch_llm()
    await _inject_inbound(aid, 46201, "hi there", mid=46201_001,
                          at=datetime.utcnow() - timedelta(minutes=5))
    payload = {"with_image": False, "after_of_welcome": True,
               "follow_ups": [{"text": "did you see my welcome?", "delay_minutes": 20}]}

    res = await run_once(aid, "send_welcome", payload=payload)
    assert (res["of_welcome_on"], res["after_of_welcome_fans"], res["welcomes_sent"],
            res["follow_ups_queued"]) == (True, 1, 0, 1), res
    assert fake.sent == [], fake.sent
    async with get_session() as s:
        assert await s.get(WelcomeSent, (aid, 46201)) is not None
    job = json.loads((await _welcome_follow_ups(aid))[0].payload_json)
    assert job["follow_up"]["anchor"][1] == 46201_001, job

    again = await run_once(aid, "send_welcome", payload=payload)
    assert again["new_subscribers"] == 0, again
    r = await run_once(aid, "send_welcome", payload=await _take_welcome_follow_up(aid, 46201))
    assert r["sent"] == 1 and fake.sent == [(46201, "did you see my welcome?", [])], (r, fake.sent)


async def case_after_of_welcome_sends_our_own_when_ofs_is_off_empty_or_unreadable():
    for i, (on, text, media) in enumerate(((False, "hi", 0), (True, "<p> </p>", 0), (None, "hi", 0),
                                           (True, "", "lots"))):
        aid = f"acc_w_after_of_off{i}"
        fid = 46301 + i
        await _seed_account(aid)
        await _seed_brain(aid)
        fake = _use_fake([_sub(fid, name="Ida")])
        _of_welcome(fake, on=on, text=text, media=media)
        _patch_llm()
        res = await run_once(aid, "send_welcome", payload={
            "with_image": False, "after_of_welcome": True, "message": "hey {name}"})
        unread = on is None or media == "lots"
        assert (res["of_welcome_on"], res["after_of_welcome_fans"], res["welcomes_sent"]) \
            == (None if unread else False, 0, 1), (on, text, res)
        assert fake.sent == [(fid, "hey Ida", [])], fake.sent


async def case_slot_lost_mid_burst_still_claims_the_fan():
    aid = "acc_w_slot_lost"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(47401, name="Sofie")], vault=True)
    payload = {"with_image": False, "human_pace": False, "stop_on_reply": False}
    with _harness.slot_lost_at_hold(send_welcome, 2) as calls:
        res = await run_once(aid, "send_welcome", payload=payload)
    assert calls[0] == 2, calls
    assert res["status"] == "error", res
    assert len(fake.sent) == 1, fake.sent
    async with get_session() as s:
        ws = (await s.execute(select(WelcomeSent).where(WelcomeSent.account_id == aid))).scalars().all()
        assert [w.fan_id for w in ws] == [47401], "the greeted fan was not claimed"
        assert (await s.get(Fan, (aid, 47401))).automation_paused_until is not None
    res = await run_once(aid, "send_welcome", payload=payload)
    assert len(fake.sent) == 1, fake.sent


_harness.run(
    case_slot_lost_mid_burst_still_claims_the_fan,
    case_follow_back_all_new_subs_by_default,
    case_follow_back_gate_defaults_ON_and_skips_a_priced_sub,
    case_follow_back_gate_off_follows_blind_with_no_read,
    case_follow_back_under_human_pace,
    case_follow_back_ledger_write_failure_is_not_an_error,
    case_paced_run_cancelled_raises_not_returns,
    case_paced_cancel_while_parked_takes_the_spawned_bursts_down,
    case_follow_back_null_means_the_default_not_off,
    case_run_stats_carry_the_follow_back_knobs,
    case_follow_back_off_when_switched_off,
    case_follow_back_failure_never_costs_the_welcome,
    case_follow_back_dry_run_follows_nobody,
    case_follow_back_gate_skips_paid_and_unreadable_profiles,
    case_follow_back_gate_resubscribes_a_lapsed_edge,
    case_follow_back_is_auto_follows_gate_not_a_copy_of_it,
    case_an_unknown_follow_back_outcome_is_booked_under_its_own_name,
    case_extract_filters_non_subscribe_notifications,
    case_skips_established_keeps_lightly_touched_new,
    case_contact_guard_skips_recent_nudge,
    case_curated_nick_beats_raw_of_name,
    case_test_fan_bypasses_new_gates,
    case_new_subs_get_one_welcome_each,
    case_no_dup_on_restart,
    case_dedup_skips_preexisting,
    case_fan_lease_blocks_welcome,
    case_cooldown_skips_welcome,
    case_lease_released_on_send_so_the_rest_is_the_only_brake,
    case_dry_run_sends_nothing,
    case_cap_never_costs_a_welcome,
    case_with_image_attaches_bot_media,
    case_text_only_when_with_image_false,
    case_with_image_no_bot_folder_sends_text,
    case_photo_index_deterministic_per_hour,
    case_two_bubbles_image_on_first_only,
    case_second_bubble_send_failure_still_marks_welcomed,
    case_real_name_no_nick_proposes_stutter,
    case_name_resolved_from_db_still_stutters,
    case_welcome_name_resolution_matrix,
    case_random_handle_no_name_greets_deterministically,
    case_word_restriction_applied_to_sent_welcome,
    case_slot_hour_roundtrip,
    case_pinned_line_weekday_refresh,
    case_run_uses_pinned_line_no_llm,
    case_run_pin_ships_even_when_activity_blank,
    case_nameless_fan_gets_activity_bubble_and_pin,
    case_time_only_bubble_is_clock_without_activity,
    case_run_time_only_sends_short_second_bubble,
    case_time_only_outranks_a_pinned_line,
    case_time_only_always_opens_with_its,
    case_follow_back_on_fansly_follows_without_a_price_to_read,
    case_pace_and_stop_default_ON_in_production_OFF_in_tests,
    case_hold_segments_are_the_four_shapes_and_they_sum,
    case_flags_absent_every_hold_is_todays_flat_hold,
    case_human_pace_hold_phases_match_the_table,
    case_human_pace_the_question_keeps_its_own_beat_in_a_short_burst,
    case_human_pace_test_fan_is_exempt,
    case_human_pace_runs_fans_concurrently,
    case_human_pace_wall_budget_defers_and_the_next_run_reserves,
    case_stop_on_reply_quiet_phase_drops_the_bubble,
    case_stop_on_reply_a_reply_during_the_dm_rate_wait_drops_the_bubble,
    case_stop_on_reply_typing_phase_finishes_then_hands_the_turn_back,
    case_stop_on_reply_the_LAST_bubble_hands_the_turn_back_too,
    case_stop_on_reply_a_finished_burst_he_never_answered_hands_off_nothing,
    case_stop_on_reply_an_unstamped_send_hands_the_turn_back,
    case_stop_on_reply_suppresses_the_gif_paced_and_unpaced,
    case_stop_on_reply_anchor_is_a_snapshot_not_any_inbound_ever,
    case_stop_on_reply_words_decide_not_the_message_type,
    case_stop_on_reply_query_failure_finishes_the_burst,
    case_stop_on_reply_handoff_engine_precedence,
    case_stop_on_reply_handoff_job_actually_gets_him_answered,
    case_stop_on_reply_handoff_belts_a_restricted_fan,
    case_stop_on_reply_claims_the_welcome_before_the_burst_can_die,
    case_skip_time_bubble_drops_bubble_two_entirely,
    case_skip_time_bubble_outranks_time_only_and_a_pin,
    case_skip_time_bubble_absent_composes_todays_bubbles,
    case_question_ships_verbatim_as_third_bubble,
    case_custom_message_replaces_the_burst,
    case_custom_message_carries_its_media_price_and_auto_unsend,
    case_the_effective_and_expiry_dates_bound_the_welcome,
    case_the_random_delay_counts_from_the_subscribe,
    case_with_a_delay_the_feed_is_read_back_past_the_longest_delay,
    case_a_paid_welcome_never_re_sells_media_the_fan_owns,
    case_a_failed_auto_unsend_queue_never_costs_the_welcome_claim,
    case_the_rule_routes_hold_the_delayed_welcome_settings_to_the_contract,
    case_gif_ships_as_fourth_bubble,
    case_gif_failure_never_costs_the_welcome,
    case_burst_abort_takes_the_gif_with_it,
    case_unreachable_sub_claimed_not_retried,
    case_a_message_list_is_its_variants_one_picked_per_fan,
    case_welcome_follow_ups_go_out_after_the_burst_and_stop_on_a_reply,
    case_after_of_welcome_sends_nothing_while_ofs_welcome_is_on,
    case_after_of_welcome_sends_our_own_when_ofs_is_off_empty_or_unreadable,
)
