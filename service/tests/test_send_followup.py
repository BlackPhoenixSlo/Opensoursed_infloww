#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402
import llm_client  # noqa: E402
from automations import send_followup  # noqa: E402  (preview_compose unit test)
from automations import rhythm  # noqa: E402
from automation_executor import acquire_fan_lease, run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account,
    AutomationRun,
    Fan,
    FanLease,
    FollowupState,
    Message,
    NudgeState,
)
from of_client import OFAPIError  # noqa: E402

OWN_ID = "999"



class FakeOF:

    def __init__(self, *, vault: bool = False, user_id: str = OWN_ID):
        self.user_id = user_id
        self.sent: list[tuple[int, str, list]] = []
        self._next_id = 8_000_000_000_000
        self._vault = vault

    def send_message(self, chat_id, text, *, media_files=None, **kw) -> dict:
        self._next_id += 1
        self.sent.append((int(chat_id), text, list(media_files or [])))
        return {
            "id": self._next_id,
            "text": f"<p>{text}</p>",
            "createdAt": "2026-06-04T12:00:00+00:00",
        }

    def get_user(self, user_id) -> dict:
        return {"id": int(user_id), "subscribedOn": True}

    def vault_lists(self, **kw) -> dict:
        if not self._vault:
            return {"list": []}
        return {"list": [{"id": 77, "name": "Bot"}, {"id": 9, "name": "other"}]}

    def vault_media(self, *, list_id=None, **kw) -> dict:
        if not self._vault or list_id != 77:
            return {"list": []}
        return {"list": [{"id": 501}, {"id": 502}, {"id": 503},
                         {"id": 504}, {"id": 505}, {"id": 506}]}


class _FakeResponse:

    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


_OF_MEDIA_REJECT_BODY = {
    "error": {"code": 0,
              "message": "Something wrong with attached media, please try to "
                         "upload it again"},
    "errors": {"mediaFiles": ["Something wrong with attached media, please try "
                              "to upload it again"]},
}


def _media_reject_error() -> OFAPIError:
    return OFAPIError(
        "400 for https://onlyfans.com/api2/v2/chats/1/messages\n"
        + json.dumps(_OF_MEDIA_REJECT_BODY),
        response=_FakeResponse(400, _OF_MEDIA_REJECT_BODY),
    )


# OF's answer to a dead vault id: 400 with a field-keyed error naming mediaFiles
class MediaRejectingOF(FakeOF):

    def __init__(self, **kw):
        super().__init__(**kw)
        self.rejected = 0
        self.attempts = 0

    def send_message(self, chat_id, text, *, media_files=None, **kw) -> dict:
        self.attempts += 1
        if media_files:
            self.rejected += 1
            raise _media_reject_error()
        return super().send_message(chat_id, text, media_files=media_files, **kw)


class SendFailingOF(FakeOF):

    def __init__(self, **kw):
        super().__init__(**kw)
        self.attempts = 0

    def send_message(self, chat_id, text, *, media_files=None, **kw) -> dict:
        self.attempts += 1
        raise OFAPIError(
            "500 for https://onlyfans.com/api2/v2/chats/1/messages\n"
            "upstream exploded",
            response=_FakeResponse(500, ValueError("not json")),
        )


# a 400 about the fan that merely mentions mediaFiles must NOT be retried (double message)
class MediaWordedButFanFaultOF(FakeOF):

    def __init__(self, **kw):
        super().__init__(**kw)
        self.attempts = 0

    def send_message(self, chat_id, text, *, media_files=None, **kw) -> dict:
        self.attempts += 1
        raise OFAPIError(
            "400 for https://onlyfans.com/api2/v2/chats/1/messages\n"
            '{"error":{"code":0,"message":"Cannot send mediaFiles to this user"}}',
            response=_FakeResponse(
                400, {"error": {"code": 0,
                                "message": "Cannot send mediaFiles to this user"}}),
        )


def _use_fake(*, vault: bool = False) -> FakeOF:
    fake = FakeOF(vault=vault)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


def _patch_llm(reply: str = "hey you, been thinking about you today 💕",
               captured: list | None = None) -> None:
    async def _fake_chat(**kw):
        if captured is not None:
            captured.append(kw)
        return SimpleNamespace(content=reply)
    llm_client.chat = _fake_chat  # type: ignore[attr-defined]


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _seed_fan(aid: str, fid: int, *, spend_cents: int = 500,
                    likes: int | None = None, name: str = "Bob") -> None:
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=fid, of_display_name=name,
                  lifetime_spend_cents=spend_cents, total_likes=likes))


async def _seed_msg(aid: str, fid: int, mid: int, direction: str,
                    age_hours: float) -> None:
    async with get_session() as s:
        s.add(Message(
            account_id=aid, fan_id=fid, message_id=mid, direction=direction,
            body="hi", created_at=datetime.utcnow() - timedelta(hours=age_hours),
        ))



async def case_eligible_fan_gets_followup():
    aid = "acc_f1"
    await _seed_account(aid)
    await _seed_fan(aid, 1001)
    await _seed_msg(aid, 1001, 1, "out", age_hours=48)
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "send_followup", payload={"with_image": False})
    assert res["status"] == "ok", res
    assert res["eligible"] == 1, res
    assert res["followups_sent"] == 1, res
    assert res["state_advanced"] == 1, res
    assert res["errors"] == 0, res
    assert len(fake.sent) == 1 and fake.sent[0][0] == 1001, fake.sent

    async with get_session() as s:
        st = await s.get(FollowupState, (aid, 1001))
        assert st is not None, "followup_state row written"
        assert st.phase == "tracking", st.phase
        sent_map = json.loads(st.messages_sent)
        assert "1" in sent_map, sent_map

        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid,
                                  Message.direction == "out", Message.message_id > 1)
        )).scalars().all()
        assert len(msgs) == 1 and msgs[0].body, "outbound nudge persisted"

        runs = (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == aid)
        )).scalars().all()
        assert len(runs) == 1 and runs[0].status == "ok", runs



async def case_prompt_personalised_with_name_and_hours():
    aid = "acc_f1b"
    await _seed_account(aid)
    await _seed_fan(aid, 1101, name="Charlie")
    await _seed_msg(aid, 1101, 1, "out", age_hours=48)
    _use_fake()
    captured: list = []
    _patch_llm(captured=captured)

    res = await run_once(aid, "send_followup", payload={"with_image": False})
    assert res["followups_sent"] == 1, res
    assert len(captured) == 1, captured

    msgs = captured[0]["messages"]
    blob = "\n".join(m["content"] for m in msgs)
    assert "Charlie" in blob, blob
    assert "48h" in blob or "~48" in blob, blob
    assert any(d in blob for d in
               ("Monday", "Tuesday", "Wednesday", "Thursday",
                "Friday", "Saturday", "Sunday")), blob



async def case_with_image_attaches_bot_media():
    aid = "acc_f2"
    await _seed_account(aid)
    await _seed_fan(aid, 2001)
    await _seed_msg(aid, 2001, 1, "out", age_hours=48)
    fake = _use_fake(vault=True)
    _patch_llm()

    res = await run_once(aid, "send_followup", payload={"with_image": True})
    assert res["followups_sent"] == 1, res
    assert res["image_attached"] == 1, res
    assert len(fake.sent) == 1, fake.sent
    _, _, media = fake.sent[0]
    assert len(media) == 1 and 501 <= media[0] <= 506, media



async def case_ineligible_fan_skipped():
    aid = "acc_f3"
    await _seed_account(aid)
    await _seed_fan(aid, 3001, spend_cents=50)
    await _seed_msg(aid, 3001, 1, "out", age_hours=48)
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "send_followup", payload={"with_image": False})
    assert res["eligible"] == 0, res
    assert res["followups_sent"] == 0, res
    assert fake.sent == [], fake.sent



async def case_fan_reply_pauses_drip():
    aid = "acc_f4"
    await _seed_account(aid)
    await _seed_fan(aid, 4001)
    await _seed_msg(aid, 4001, 1, "out", age_hours=48)
    await _seed_msg(aid, 4001, 2, "in", age_hours=2)
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "send_followup", payload={"with_image": False})
    assert res["followups_sent"] == 0, res
    assert res["skipped_unread"] == 1, res
    assert fake.sent == [], fake.sent

    async with get_session() as s:
        st = await s.get(FollowupState, (aid, 4001))
        assert st is not None and st.phase == "reply_cooldown", st
        assert st.cooldown_until is not None, st



async def case_dry_run_sends_nothing():
    aid = "acc_f5"
    await _seed_account(aid)
    await _seed_fan(aid, 5001)
    await _seed_msg(aid, 5001, 1, "out", age_hours=48)
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "send_followup", payload={"dry_run": True})
    assert res["followups_sent"] == 1, res
    assert res["state_advanced"] == 0, res
    assert fake.sent == [], "dry run must not send"

    async with get_session() as s:
        st = await s.get(FollowupState, (aid, 5001))
        sent_map = json.loads(st.messages_sent) if st else {}
        assert sent_map == {}, sent_map



async def case_reply_mid_tick_is_not_nudged():
    aid = "acc_f5b"
    await _seed_account(aid)
    await _seed_fan(aid, 5101)
    await _seed_msg(aid, 5101, 1, "out", age_hours=48)
    fake = _use_fake()

    async def _chat_then_fan_replies(**kw):
        await _seed_msg(aid, 5101, 2, "in", age_hours=0)
        return SimpleNamespace(content="hey you 💕")
    llm_client.chat = _chat_then_fan_replies  # type: ignore[attr-defined]

    res = await run_once(aid, "send_followup", payload={"with_image": False})
    assert fake.sent == [], "nudged over a reply that arrived mid-tick"
    assert res["followups_sent"] == 0, res
    assert res["skipped_unread"] == 1, res

    async with get_session() as s:
        st = await s.get(FollowupState, (aid, 5101))
        assert st is not None and st.phase == "reply_cooldown", st
        assert json.loads(st.messages_sent or "{}") == {}, st.messages_sent
    assert await acquire_fan_lease(aid, 5101, "probe", ttl_s=1) is True



async def case_lease_blocks_followup():
    aid = "acc_f6"
    await _seed_account(aid)
    await _seed_fan(aid, 6001)
    await _seed_msg(aid, 6001, 1, "out", age_hours=48)
    fake = _use_fake()
    _patch_llm()

    assert await acquire_fan_lease(aid, 6001, "welcome_chatter_for_info", ttl_s=300) is True
    res = await run_once(aid, "send_followup", payload={"with_image": False})
    assert res["skipped_locked"] == 1, res
    assert res["followups_sent"] == 0, res
    assert fake.sent == [], fake.sent



async def case_cooldown_skips_followup():
    aid = "acc_f6b"
    await _seed_account(aid)
    await _seed_fan(aid, 6101)
    await _seed_msg(aid, 6101, 1, "out", age_hours=48)
    fake = _use_fake()
    _patch_llm()

    await ax.start_fan_cooldown(aid, 6101)
    res = await run_once(aid, "send_followup", payload={"with_image": False})
    assert res["skipped_cooldown"] == 1, res
    assert res["followups_sent"] == 0, res
    assert fake.sent == [], fake.sent



async def case_contact_guard_holds_due_step():
    aid = "acc_f6c"
    await _seed_account(aid)
    await _seed_fan(aid, 6201)
    await _seed_msg(aid, 6201, 1, "out", age_hours=48)
    fake = _use_fake()
    _patch_llm()

    async with get_session() as s:
        s.add(NudgeState(account_id=aid, fan_id=6201,
                         last_nudged_at=datetime.utcnow() - timedelta(hours=1),
                         nudge_count=1, updated_at=datetime.utcnow()))

    res = await run_once(aid, "send_followup", payload={"with_image": False})
    assert res["skipped_guard"] == 1, res
    assert res["followups_sent"] == 0, res
    assert fake.sent == [], fake.sent

    res2 = await run_once(aid, "send_followup",
                          payload={"with_image": False, "exclude_replied_hours": 0})
    assert res2["skipped_guard"] == 0, res2
    assert res2["followups_sent"] == 1, res2
    assert len(fake.sent) == 1 and fake.sent[0][0] == 6201, fake.sent



async def case_restart_cooldown_expires_resets_cycle():
    aid = "acc_f7"
    await _seed_account(aid)
    await _seed_fan(aid, 7001)
    await _seed_msg(aid, 7001, 1, "out", age_hours=1)
    async with get_session() as s:
        s.add(FollowupState(
            account_id=aid, fan_id=7001, phase="restart_cooldown", cycle=1,
            cooldown_until=datetime.utcnow() - timedelta(hours=1),
            messages_sent=json.dumps({"1": "x", "2": "y", "3": "z"}),
        ))
    _use_fake()
    _patch_llm()

    res = await run_once(aid, "send_followup", payload={"with_image": False})
    assert res["transitioned"] == 1, res

    async with get_session() as s:
        st = await s.get(FollowupState, (aid, 7001))
        assert st.phase == "tracking", st.phase
        assert st.cycle == 2, st.cycle
        assert json.loads(st.messages_sent) == {}, st.messages_sent



async def case_step_hours_override_honored():
    aid_hi = "acc_f8"
    await _seed_account(aid_hi)
    await _seed_fan(aid_hi, 8001)
    await _seed_msg(aid_hi, 8001, 1, "out", age_hours=30)
    fake_hi = _use_fake()
    _patch_llm()
    res_hi = await run_once(aid_hi, "send_followup",
                            payload={"with_image": False, "step_hours": [48, 64, 256]})
    assert res_hi["followups_sent"] == 0, res_hi
    assert fake_hi.sent == [], fake_hi.sent

    aid_lo = "acc_f8b"
    await _seed_account(aid_lo)
    await _seed_fan(aid_lo, 8101)
    await _seed_msg(aid_lo, 8101, 1, "out", age_hours=30)
    fake_lo = _use_fake()
    _patch_llm()
    res_lo = await run_once(aid_lo, "send_followup",
                            payload={"with_image": False, "step_hours": [10, 64, 256]})
    assert res_lo["followups_sent"] == 1, res_lo
    assert len(fake_lo.sent) == 1 and fake_lo.sent[0][0] == 8101, fake_lo.sent



async def case_preview_compose_returns_text_no_send():
    aid = "acc_f9"
    await _seed_account(aid)
    await _seed_fan(aid, 9001, name="Diana")
    fake = _use_fake()
    captured: list = []
    _patch_llm("hey there, hope your day is going great", captured=captured)

    res = await send_followup.preview_compose(aid, fan_id=9001)
    assert res["text"] == "hey there, hope your day is going great", res
    assert res["name"] == "Diana", res
    assert res["step"] == 1, res
    assert "image" in res and "slot" in res, res
    blob = "\n".join(m["content"] for m in captured[0]["messages"])
    assert "Diana" in blob, blob

    assert fake.sent == [], fake.sent
    async with get_session() as s:
        st = await s.get(FollowupState, (aid, 9001))
        assert st is None, st
        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid, Message.direction == "out")
        )).scalars().all()
        assert msgs == [], msgs


async def case_undeliverable_lapsed_sub_quarantined():
    aid = "acc_flapsed"
    await _seed_account(aid)
    await _seed_fan(aid, 9601, spend_cents=2900)
    await _seed_msg(aid, 9601, 1, "out", age_hours=48)
    fake = _use_fake()
    def _raise(chat_id, text, *, media_files=None, **kw):
        raise RuntimeError("500 Server Error")
    fake.send_message = _raise
    fake.get_user = lambda user_id: {"id": int(user_id), "subscribedOn": False}
    _patch_llm()

    res = await run_once(aid, "send_followup", payload={"with_image": False})
    assert res["status"] == "ok" and res["followups_sent"] == 0, res
    async with get_session() as s:
        f = await s.get(Fan, (aid, 9601))
    assert f is not None and f.automation_paused_until is not None, res
    assert f.automation_paused_until > datetime.utcnow() + timedelta(days=6), \
        "lapsed-sub payer must be rested ~a week, not retried every tick"
    assert f.subscription_status == "expired", "quarantine must record WHY"



async def case_completed_fan_rearms_on_inbound():
    aid = "acc_f10"
    await _seed_account(aid)
    await _seed_fan(aid, 10001)
    await _seed_msg(aid, 10001, 1, "out", age_hours=960)
    await _seed_msg(aid, 10001, 2, "in", age_hours=200)
    await _seed_msg(aid, 10001, 3, "out", age_hours=199)
    await _seed_msg(aid, 10001, 4, "out", age_hours=2)
    async with get_session() as s:
        s.add(FollowupState(
            account_id=aid, fan_id=10001, phase="completed", cycle=1,
            silence_started_at=datetime.utcnow() - timedelta(hours=960),
            messages_sent=json.dumps({"1": "x", "2": "y"}), completed=True,
        ))
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "send_followup", payload={"with_image": False})
    assert res["state_advanced"] == 1, res
    assert res["followups_sent"] == 0, res
    assert fake.sent == [], fake.sent

    async with get_session() as s:
        st = await s.get(FollowupState, (aid, 10001))
        assert st.phase == "restart_cooldown", st.phase
        assert st.completed is False, st.completed
        st.cooldown_until = datetime.utcnow() - timedelta(hours=1)

    res2 = await run_once(aid, "send_followup", payload={"with_image": False})
    assert res2["transitioned"] == 1, res2
    async with get_session() as s:
        st = await s.get(FollowupState, (aid, 10001))
        assert st.phase == "tracking", st.phase
        assert st.cycle == 2, st.cycle
        assert json.loads(st.messages_sent) == {}, st.messages_sent

    aid2 = "acc_f10b"
    await _seed_account(aid2)
    await _seed_fan(aid2, 10101)
    await _seed_msg(aid2, 10101, 1, "out", age_hours=960)
    async with get_session() as s:
        s.add(FollowupState(
            account_id=aid2, fan_id=10101, phase="completed", cycle=1,
            silence_started_at=datetime.utcnow() - timedelta(hours=960),
            messages_sent=json.dumps({"1": "x", "2": "y"}), completed=True,
        ))
    _use_fake()
    res2 = await run_once(aid2, "send_followup", payload={"with_image": False})
    assert res2["state_advanced"] == 0, res2
    async with get_session() as s:
        st2 = await s.get(FollowupState, (aid2, 10101))
        assert st2.phase == "completed", st2.phase



async def case_final_step_fires_under_silence_cap():
    from automations import send_followup_decide as drip
    assert drip._STEP_THRESHOLDS_H[3] < drip._MAX_SILENCE_H, "step 3 above the cap is dead code"
    assert send_followup._resolve_step_thresholds({"step_hours": [26, 64, 256]}) == \
        send_followup._STEP_THRESHOLDS_H, "over-cap override must fall back"

    aid = "acc_f11"
    await _seed_account(aid)
    await _seed_fan(aid, 11001)
    await _seed_msg(aid, 11001, 1, "out", age_hours=130)
    await _seed_fan(aid, 11002)
    await _seed_msg(aid, 11002, 2, "out", age_hours=200)
    async with get_session() as s:
        s.add(FollowupState(
            account_id=aid, fan_id=11001, phase="tracking", cycle=1,
            silence_started_at=datetime.utcnow() - timedelta(hours=130),
            messages_sent=json.dumps({
                "1": (datetime.utcnow() - timedelta(hours=100)).isoformat(),
                "2": (datetime.utcnow() - timedelta(hours=60)).isoformat(),
            }),
        ))
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "send_followup", payload={"with_image": False})
    assert res["followups_sent"] == 1, res
    assert res["completed"] == 1, res
    assert len(fake.sent) == 1 and fake.sent[0][0] == 11001, fake.sent
    async with get_session() as s:
        st = await s.get(FollowupState, (aid, 11001))
        assert "3" in json.loads(st.messages_sent), st.messages_sent
        assert st.phase == "all_sent_waiting", st.phase


async def case_rejected_media_still_delivers_the_text() -> None:
    aid = "acc_fmedia"
    await _seed_account(aid)
    await _seed_fan(aid, 7001)
    await _seed_msg(aid, 7001, 1, "out", age_hours=48)
    fake = MediaRejectingOF(vault=True)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    _patch_llm()

    res = await run_once(aid, "send_followup", payload={"with_image": True})
    assert res["followups_sent"] == 1, res
    assert res["errors"] == 0, f"a recovered send is not an error: {res}"
    assert res["first_error"] is None, res
    assert res["image_attached"] == 0, f"the picture did NOT land: {res}"
    assert fake.rejected == 1, "the attachment must be attempted once"
    assert fake.attempts == 2, f"exactly one retry, no more: {fake.attempts}"
    assert len(fake.sent) == 1 and fake.sent[0][2] == [], \
        f"the retry must carry no media: {fake.sent}"

    assert res["state_advanced"] == 1, res
    async with get_session() as s:
        st = await s.get(FollowupState, (aid, 7001))
        assert st is not None and "1" in json.loads(st.messages_sent), st


async def case_first_error_names_a_send_failure() -> None:
    aid = "acc_ferr"
    await _seed_account(aid)
    await _seed_fan(aid, 7101)
    await _seed_msg(aid, 7101, 1, "out", age_hours=48)
    fake = SendFailingOF()
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    _patch_llm()

    res = await run_once(aid, "send_followup", payload={"with_image": False})
    assert res["followups_sent"] == 0, res
    assert res["errors"] == 1, res
    assert res["first_error"], "a failing run must name its first failure"
    assert "upstream exploded" in res["first_error"], res["first_error"]
    assert "\n" not in res["first_error"], "must be one line for a stats row"
    assert fake.attempts == 1, \
        f"a NON-media failure must never be retried: {fake.attempts}"


async def case_fan_side_400_is_never_retried() -> None:
    aid = "acc_ffalsepos"
    await _seed_account(aid)
    await _seed_fan(aid, 7301)
    await _seed_msg(aid, 7301, 1, "out", age_hours=48)
    fake = MediaWordedButFanFaultOF(vault=True)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    _patch_llm()

    res = await run_once(aid, "send_followup", payload={"with_image": True})
    assert fake.attempts == 1, \
        f"a fan-side 400 must NOT trigger a text-only retry: {fake.attempts}"
    assert fake.sent == [], "nothing may have been delivered"
    assert res["followups_sent"] == 0, res
    assert res["errors"] == 1, res


async def case_empty_draft_is_counted_and_named() -> None:
    aid = "acc_fempty"
    await _seed_account(aid)
    await _seed_fan(aid, 7201)
    await _seed_msg(aid, 7201, 1, "out", age_hours=48)
    fake = _use_fake()
    _patch_llm(reply="")

    res = await run_once(aid, "send_followup", payload={"with_image": False})
    assert res["followups_sent"] == 0, res
    assert res["errors"] == 1, res
    assert "empty draft" in (res["first_error"] or ""), res
    assert fake.sent == [], "nothing may be sent for an empty draft"


async def case_model_wait_frees_the_slot() -> None:
    aid = "acc_ffreed"
    await _seed_account(aid)
    await _seed_fan(aid, 7301)
    await _seed_msg(aid, 7301, 1, "out", age_hours=48)
    fake = _use_fake()
    captured: list = []
    _patch_llm(captured=captured)
    chat = llm_client.chat = _harness.parking_chat(llm_client.chat, 1)
    res = await _harness.slot_parked(
        lambda: run_once(aid, "send_followup", payload={"with_image": False}), chat)
    assert res["followups_sent"] == 1 and [c for c, *_ in fake.sent] == [7301], (res, fake.sent)
    assert [(c["timeout_s"], c["max_attempts"]) for c in captured] == [(rhythm.MODEL_WAIT_S, rhythm.MODEL_TRIES)]


async def case_slot_lost_in_model_wait_sends_no_more() -> None:
    aid = "acc_ffreed_lost"
    await _seed_account(aid)
    for fid in (7311, 7312):
        await _seed_fan(aid, fid)
        await _seed_msg(aid, fid, fid, "out", age_hours=48)
    fake = _use_fake()
    _patch_llm()
    chat = llm_client.chat = _harness.parking_chat(llm_client.chat, 2)
    real, rhythm.INLINE_MAX_S = rhythm.INLINE_MAX_S, 0.2
    try:
        res = await _harness.slot_parked(
            lambda: run_once(aid, "send_followup", payload={"with_image": False}),
            chat, keep_s=0.5)
    finally:
        rhythm.INLINE_MAX_S = real
    assert res["status"] == "error", res
    assert len(fake.sent) == 1, fake.sent
    first = fake.sent[0][0]
    (other,) = {7311, 7312} - {first}
    async with get_session() as s:
        assert "1" in json.loads((await s.get(FollowupState, (aid, first))).messages_sent)
        st = await s.get(FollowupState, (aid, other))
        assert st is None or ("1" not in json.loads(st.messages_sent or "{}")
                              and st.sending_at is None), st.__dict__
        assert await s.get(FanLease, (aid, other)) is None
    _patch_llm()
    res = await run_once(aid, "send_followup", payload={"with_image": False})
    assert res["followups_sent"] == 1 and [c for c, *_ in fake.sent] == [first, other], (res, fake.sent)


_harness.run(
    case_model_wait_frees_the_slot,
    case_slot_lost_in_model_wait_sends_no_more,
    case_eligible_fan_gets_followup,
    case_completed_fan_rearms_on_inbound,
    case_final_step_fires_under_silence_cap,
    case_undeliverable_lapsed_sub_quarantined,
    case_prompt_personalised_with_name_and_hours,
    case_with_image_attaches_bot_media,
    case_ineligible_fan_skipped,
    case_fan_reply_pauses_drip,
    case_dry_run_sends_nothing,
    case_reply_mid_tick_is_not_nudged,
    case_lease_blocks_followup,
    case_cooldown_skips_followup,
    case_contact_guard_holds_due_step,
    case_restart_cooldown_expires_resets_cycle,
    case_step_hours_override_honored,
    case_preview_compose_returns_text_no_send,
    case_rejected_media_still_delivers_the_text,
    case_first_error_names_a_send_failure,
    case_empty_draft_is_counted_and_named,
    case_fan_side_400_is_never_retried,
)
