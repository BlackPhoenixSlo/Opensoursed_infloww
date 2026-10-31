#!/usr/bin/env python3
"""
A07 send_followup — automation tests (spec 07_send_followup.md).

Acceptance the prompt calls out: an eligible fan gets a follow-up and
followup_state advances. These cases run the automation through the real
`run_once` dispatcher (registry wiring + automation_runs exercised) against a
fake OFClient + a patched llm_client.chat — no network.

  case_eligible_fan_gets_followup:
      a $-spending fan silent >26h → step-1 nudge sent, outbound `messages` row,
      followup_state.messages_sent advances to {"1": ...}, run status=ok.
  case_with_image_attaches_bot_media:
      with_image=True + a 'bot' vault folder → the send carries a media id.
  case_ineligible_fan_skipped:
      a fan under $1 lifetime spend is not eligible — nothing sent.
  case_fan_reply_pauses_drip:
      a fan whose latest message is inbound → reply_cooldown, no send.
  case_dry_run_sends_nothing:
      dry_run generates but neither sends nor advances state.
  case_reply_mid_tick_is_not_nudged:
      the fan writes back AFTER the run's message-time snapshot (here: while his
      nudge is being generated) → no send, reply_cooldown, lease released.
  case_lease_blocks_followup:
      a live lease held by another automation skips that fan this cycle.
  case_contact_guard_holds_due_step:
      a fan nudged an hour ago (NudgeState only — no messages row) holds a due
      drip step (skipped_guard); exclude_replied_hours=0 releases it.
  case_restart_cooldown_expires_resets_cycle:
      a restart_cooldown entry past its cooldown → tracking, cycle++, sent reset.
  case_rejected_media_still_delivers_the_text:
      OF refuses the ATTACHMENT (bad vault id) → the nudge re-sends text-only,
      state advances, image_attached stays 0. Without this one dead media id
      strands every follow-up on the account forever.
  case_first_error_names_a_send_failure:
      a failing run reports first_error, not just a bare count.
  case_empty_draft_is_counted_and_named:
      an empty model draft is counted AND named (it used to bump silently).
  case_fan_side_400_is_never_retried:
      a 400 that merely MENTIONS mediaFiles but is not keyed as a mediaFiles
      field error is about the FAN — retrying it would double-message them.

Run: ./venv/bin/python service/tests/test_send_followup.py   (exit 0 = pass)
"""
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
from automation_executor import acquire_fan_lease, run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account,
    AutomationRun,
    Fan,
    FollowupState,
    Message,
    NudgeState,
)
from of_client import OFAPIError  # noqa: E402

OWN_ID = "999"


# ── Fakes (no network) ────────────────────────────────────────────────

class FakeOF:
    """Records sends; serves an optional 'bot' vault folder + photos."""

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
        # Default: an active fan. The undeliverable-quarantine probe reads
        # `subscribedOn`; a lapsed-sub test overrides this to return it falsy.
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
    """Minimal stand-in for the `requests` response OFAPIError carries. The
    media classifier reads status + JSON body off it rather than sniffing the
    exception string, so the fakes have to carry a real one."""

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
    """OF's verbatim answer to a vault id that has gone bad (captured from prod
    account 800000038): 400 with a field-keyed validation error naming
    `mediaFiles`."""
    return OFAPIError(
        "400 for https://onlyfans.com/api2/v2/chats/1/messages\n"
        + json.dumps(_OF_MEDIA_REJECT_BODY),
        response=_FakeResponse(400, _OF_MEDIA_REJECT_BODY),
    )


class MediaRejectingOF(FakeOF):
    """Refuses any send carrying an attachment. Nothing is wrong with the fan or
    the text: the identical send with no media succeeds, which is exactly what
    makes the text-only fallback correct."""

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
    """Every send raises a fault that is NOT a media rejection — a 500 with no
    parseable body, which is what an upstream/proxy blip looks like."""

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


class MediaWordedButFanFaultOF(FakeOF):
    """The false positive that would cost a DOUBLE MESSAGE: a rejection that is
    about the FAN, whose body merely mentions mediaFiles in passing. OF did not
    key it as a mediaFiles field error, so the send must NOT be retried."""

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


# ── 🔴 Acceptance: an eligible silent fan gets a follow-up + state advances ──

async def case_eligible_fan_gets_followup():
    aid = "acc_f1"
    await _seed_account(aid)
    await _seed_fan(aid, 1001)
    # Our last message was 48h ago; fan never replied → silence ~48h ≥ 26h.
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
        assert "1" in sent_map, sent_map  # step-1 recorded

        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid,
                                  Message.direction == "out", Message.message_id > 1)
        )).scalars().all()
        assert len(msgs) == 1 and msgs[0].body, "outbound nudge persisted"

        runs = (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == aid)
        )).scalars().all()
        assert len(runs) == 1 and runs[0].status == "ok", runs


# ── W2b: the nudge prompt is personalised (fan name + hours of silence) ──

async def case_prompt_personalised_with_name_and_hours():
    aid = "acc_f1b"
    await _seed_account(aid)
    await _seed_fan(aid, 1101, name="Charlie")
    await _seed_msg(aid, 1101, 1, "out", age_hours=48)  # silence ~48h
    _use_fake()
    captured: list = []
    _patch_llm(captured=captured)

    res = await run_once(aid, "send_followup", payload={"with_image": False})
    assert res["followups_sent"] == 1, res
    assert len(captured) == 1, captured

    msgs = captured[0]["messages"]
    blob = "\n".join(m["content"] for m in msgs)
    # Fan name must reach the LLM (system + user turn). This is also the only cover
    # for _load_eligible_fans handing resolve_fan_name a SQLAlchemy Row rather than a
    # dict — Row is not a dict, so it takes the getattr path.
    assert "Charlie" in blob, blob
    # Elapsed silence must be a concrete number, not a static template.
    assert "48h" in blob or "~48" in blob, blob
    # The full local clock line is injected too (weekday name present).
    assert any(d in blob for d in
               ("Monday", "Tuesday", "Wednesday", "Thursday",
                "Friday", "Saturday", "Sunday")), blob


# ── with_image attaches a bot-folder vault media id ───────────────────

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


# ── A fan under $1 lifetime spend is not eligible ─────────────────────

async def case_ineligible_fan_skipped():
    aid = "acc_f3"
    await _seed_account(aid)
    await _seed_fan(aid, 3001, spend_cents=50)  # $0.50 < $1
    await _seed_msg(aid, 3001, 1, "out", age_hours=48)
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "send_followup", payload={"with_image": False})
    assert res["eligible"] == 0, res
    assert res["followups_sent"] == 0, res
    assert fake.sent == [], fake.sent


# ── Fan's latest message is inbound → pause the drip ──────────────────

async def case_fan_reply_pauses_drip():
    aid = "acc_f4"
    await _seed_account(aid)
    await _seed_fan(aid, 4001)
    await _seed_msg(aid, 4001, 1, "out", age_hours=48)
    await _seed_msg(aid, 4001, 2, "in", age_hours=2)  # fan replied recently
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


# ── dry_run: generate but neither send nor advance ────────────────────

async def case_dry_run_sends_nothing():
    aid = "acc_f5"
    await _seed_account(aid)
    await _seed_fan(aid, 5001)
    await _seed_msg(aid, 5001, 1, "out", age_hours=48)
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "send_followup", payload={"dry_run": True})
    assert res["followups_sent"] == 1, res  # would-send counted
    assert res["state_advanced"] == 0, res  # nothing saved for a would-send
    assert fake.sent == [], "dry run must not send"

    async with get_session() as s:
        st = await s.get(FollowupState, (aid, 5001))
        # No nudge recorded (silence anchor may be set, but no step sent).
        sent_map = json.loads(st.messages_sent) if st else {}
        assert sent_map == {}, sent_map


# ── a reply that lands after the snapshot stops the nudge ─────────────

async def case_reply_mid_tick_is_not_nudged():
    aid = "acc_f5b"
    await _seed_account(aid)
    await _seed_fan(aid, 5101)
    await _seed_msg(aid, 5101, 1, "out", age_hours=48)
    fake = _use_fake()

    async def _chat_then_fan_replies(**kw):
        # run() took its msg_times snapshot before the loop; the reply lands now.
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
    # Nothing went out → the lease is released for a human / other automation.
    assert await acquire_fan_lease(aid, 5101, "probe", ttl_s=1) is True


# ── A live fan-lease blocks the followup this cycle ───────────────────

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


# ── W3: a fan on post-send cooldown is skipped (before the lease) ─────

async def case_cooldown_skips_followup():
    aid = "acc_f6b"
    await _seed_account(aid)
    await _seed_fan(aid, 6101)
    await _seed_msg(aid, 6101, 1, "out", age_hours=48)
    fake = _use_fake()
    _patch_llm()

    # A new sub gets welcome FIRST: welcome's confirmed send rested the fan, so
    # followup must now skip it (priority realised via the shared cooldown).
    await ax.start_fan_cooldown(aid, 6101)
    res = await run_once(aid, "send_followup", payload={"with_image": False})
    assert res["skipped_cooldown"] == 1, res
    assert res["followups_sent"] == 0, res
    assert fake.sent == [], fake.sent


# ── contact guard: a recent nudge/blast holds a due drip step ─────────

async def case_contact_guard_holds_due_step():
    aid = "acc_f6c"
    await _seed_account(aid)
    await _seed_fan(aid, 6201)
    await _seed_msg(aid, 6201, 1, "out", age_hours=48)  # step-1 due (48h silence)
    fake = _use_fake()
    _patch_llm()

    # nudge_online touched the fan an hour ago — NudgeState only, NO messages
    # row, so followup's own msg_times can't see it. The shared guard must.
    async with get_session() as s:
        s.add(NudgeState(account_id=aid, fan_id=6201,
                         last_nudged_at=datetime.utcnow() - timedelta(hours=1),
                         nudge_count=1, updated_at=datetime.utcnow()))

    res = await run_once(aid, "send_followup", payload={"with_image": False})
    assert res["skipped_guard"] == 1, res
    assert res["followups_sent"] == 0, res
    assert fake.sent == [], fake.sent

    # Explicit 0 turns the guard off — the same due step now fires.
    res2 = await run_once(aid, "send_followup",
                          payload={"with_image": False, "exclude_replied_hours": 0})
    assert res2["skipped_guard"] == 0, res2
    assert res2["followups_sent"] == 1, res2
    assert len(fake.sent) == 1 and fake.sent[0][0] == 6201, fake.sent


# ── restart_cooldown past its window resets the cycle ─────────────────

async def case_restart_cooldown_expires_resets_cycle():
    aid = "acc_f7"
    await _seed_account(aid)
    await _seed_fan(aid, 7001)
    await _seed_msg(aid, 7001, 1, "out", age_hours=1)  # recent → no new send
    async with get_session() as s:
        s.add(FollowupState(
            account_id=aid, fan_id=7001, phase="restart_cooldown", cycle=1,
            cooldown_until=datetime.utcnow() - timedelta(hours=1),  # expired
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


# ── W8-C: payload step_hours overrides the silence thresholds ─────────

async def case_step_hours_override_honored():
    """A fan silent ~30h would fire the default step-1 nudge (26h threshold). A
    RAISED override (48h) suppresses it; a LOWERED override (10h) still fires —
    proving payload.step_hours drives the cadence in both directions."""
    # Raised → no send (30h < 48h).
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

    # Lowered → fires (30h ≥ 10h).
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


# ── W8-C: preview_compose returns text and sends/writes nothing ───────

async def case_preview_compose_returns_text_no_send():
    aid = "acc_f9"
    await _seed_account(aid)
    await _seed_fan(aid, 9001, name="Diana")
    fake = _use_fake()
    captured: list = []
    _patch_llm("hey there, hope your day is going great", captured=captured)

    res = await send_followup.preview_compose(aid, fan_id=9001)
    assert res["text"] == "hey there, hope your day is going great", res
    assert res["name"] == "Diana", res          # name resolved from the DB
    assert res["step"] == 1, res                # defaults to the first nudge
    assert "image" in res and "slot" in res, res
    # The fan name reached the LLM prompt (system + user turn).
    blob = "\n".join(m["content"] for m in captured[0]["messages"])
    assert "Diana" in blob, blob

    # Sent NOTHING and wrote no state.
    assert fake.sent == [], fake.sent
    async with get_session() as s:
        st = await s.get(FollowupState, (aid, 9001))
        assert st is None, st
        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid, Message.direction == "out")
        )).scalars().all()
        assert msgs == [], msgs


async def case_undeliverable_lapsed_sub_quarantined():
    """The paying-but-lapsed loop: a $-spending fan whose sub lapsed RAISES on every
    send (an error followup doesn't recognise as a permanent marker), so state
    never advances and followup re-fires the same nudge every tick forever. When
    the probe shows the sub is gone (`subscribedOn` falsy), followup must rest the
    fan ~a week and record WHY — not keep retrying."""
    aid = "acc_flapsed"
    await _seed_account(aid)
    await _seed_fan(aid, 9601, spend_cents=2900)            # a $29 payer
    await _seed_msg(aid, 9601, 1, "out", age_hours=48)       # silent 48h → due
    fake = _use_fake()
    # A non-marker send error (NOT "Cannot send message to this user"/"User not
    # found") + a lapsed sub on the probe.
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


# ── a completed fan who writes back re-arms the cycle ─────────────────

async def case_completed_fan_rearms_on_inbound():
    """`completed` was terminal: a fan retired by the 1-week silence cap never
    got another drip step, even after he wrote back. The re-arm keys off the
    silence ANCHOR, not the last outbound — a PPV blast a minute after his reply
    used to bury it (prod: Ava/252453925, silent since 06-06, replied 06-15).

    NB the re-armed cycle re-anchors on the last outbound, so a fan whose thread
    has ALSO been cold past the cap just retires again on the same tick — correct,
    and self-limiting, since the new anchor is then newer than his reply."""
    aid = "acc_f10"
    await _seed_account(aid)
    await _seed_fan(aid, 10001)
    await _seed_msg(aid, 10001, 1, "out", age_hours=960)   # the drip's last send
    await _seed_msg(aid, 10001, 2, "in", age_hours=200)    # he wrote back...
    await _seed_msg(aid, 10001, 3, "out", age_hours=199)   # ...a blast buried it
    await _seed_msg(aid, 10001, 4, "out", age_hours=2)     # PPVs still flowing
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
    assert res["followups_sent"] == 0, res      # he just wrote — rest, don't nudge
    assert fake.sent == [], fake.sent

    # Re-armed through the SAME path a finished drip takes: restart_cooldown.
    async with get_session() as s:
        st = await s.get(FollowupState, (aid, 10001))
        assert st.phase == "restart_cooldown", st.phase
        assert st.completed is False, st.completed
        st.cooldown_until = datetime.utcnow() - timedelta(hours=1)   # expire it

    # ...and that expiry hands him back a fresh cycle (see
    # case_restart_cooldown_expires_resets_cycle for the transition itself).
    res2 = await run_once(aid, "send_followup", payload={"with_image": False})
    assert res2["transitioned"] == 1, res2
    async with get_session() as s:
        st = await s.get(FollowupState, (aid, 10001))
        assert st.phase == "tracking", st.phase
        assert st.cycle == 2, st.cycle
        assert json.loads(st.messages_sent) == {}, st.messages_sent

    # A retired fan who stayed silent stays retired.
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


# ── step 3 must be reachable under the hard silence cap ───────────────

async def case_final_step_fires_under_silence_cap():
    """Step 3's threshold was 256h while the cap retires a fan at 168h, so the
    final nudge could never fire. It must now land inside the cap."""
    from automations import send_followup_decide as drip
    assert drip._STEP_THRESHOLDS_H[3] < drip._MAX_SILENCE_H, "step 3 above the cap is dead code"
    # ...and the Brain panel can't re-break it: an over-cap override is invalid.
    assert send_followup._resolve_step_thresholds({"step_hours": [26, 64, 256]}) == \
        send_followup._STEP_THRESHOLDS_H, "over-cap override must fall back"

    aid = "acc_f11"
    await _seed_account(aid)
    await _seed_fan(aid, 11001)
    await _seed_msg(aid, 11001, 1, "out", age_hours=130)   # past step 3, under cap
    await _seed_fan(aid, 11002)
    await _seed_msg(aid, 11002, 2, "out", age_hours=200)   # over the cap: retired
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
    """One dead vault id must not strand the automation.

    State advances only on a RETURNED send, so before the fallback a refused
    attachment left the fan eligible forever: prod account 800000038 sat at
    39-eligible / 0-sent for days, regenerating the same nudges every hour."""
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

    # The point of the fix: state moved, so this fan leaves the eligible set
    # instead of being regenerated on every future tick.
    assert res["state_advanced"] == 1, res
    async with get_session() as s:
        st = await s.get(FollowupState, (aid, 7001))
        assert st is not None and "1" in json.loads(st.messages_sent), st


async def case_first_error_names_a_send_failure() -> None:
    """"errors: 6" with no cause is what hid this bug for days."""
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
    """The false positive that would cost a double message.

    A rejection that merely MENTIONS mediaFiles, but is not keyed as a mediaFiles
    field error, is about the fan. Retrying it would send the same nudge twice —
    which is why the classifier reads the response's `errors` map instead of
    sniffing the exception text for a substring."""
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
    """The `if not text` bump was silent — indistinguishable from a send error."""
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


_harness.run(
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
