#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

from datetime import datetime  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import automation_executor as ax  # noqa: E402
import llm_client  # noqa: E402
from automations import autoreply, welcome_chatter_for_info, rhythm  # noqa: E402
from automations._clock import clock_line as _clock_line  # noqa: E402
from automations._clock import load_clock_tz as _load_clock_tz  # noqa: E402
from automation_executor import run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, Fan  # noqa: E402

_VPS_NOW = datetime(2026, 7, 23, 7, 32)
_MARK = "RIGHT NOW for you it is"


class FakeOF:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []
        self._next_id = 9_000_000_000_000

    def send_message(self, chat_id, text, **kw) -> dict:
        self._next_id += 1
        self.sent.append((int(chat_id), text))
        return {"id": self._next_id, "text": f"<p>{text}</p>",
                "createdAt": "2026-07-23T07:32:00+00:00"}

    def set_fan_custom_name(self, user_id, name) -> dict:
        return {"success": True}

    def set_fan_note(self, user_id, note) -> dict:
        return {"success": True}

    def mark_chat_read(self, chat_id) -> dict:
        return {"success": True}

    def get_user(self, user_id) -> dict:
        return {"id": int(user_id), "subscribedOn": True}


def _use_fake() -> FakeOF:
    fake = FakeOF()
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


def _patch_llm_capture() -> list[list[dict]]:
    seen: list[list[dict]] = []

    async def _fake_chat(**kw):
        seen.append(kw.get("messages") or [])
        return SimpleNamespace(content="heyy 😏", call_id=1)

    llm_client.chat = _fake_chat  # type: ignore[attr-defined]
    return seen


def _mk_of_candidate(fan_id: int, msgs):
    c = welcome_chatter_for_info._Candidate(fan_id)
    c.fan_msg_n = sum(1 for d, _ in msgs if d == "in")
    c.last_dir = "in"
    c.last_body = msgs[-1][1]
    c.messages = list(msgs)
    return c



def case_clock_line_formats():
    assert _clock_line(None) == "", "None must yield no clock line"
    assert _clock_line(None, _VPS_NOW) == ""
    assert _clock_line(-420, _VPS_NOW) == "Thursday, July 23 — 12:32 AM (late night)", \
        _clock_line(-420, _VPS_NOW)
    assert _clock_line(-480, _VPS_NOW) == "Wednesday, July 22 — 11:32 PM (late night)", \
        _clock_line(-480, _VPS_NOW)
    assert "(morning)" in _clock_line(120, _VPS_NOW)
    assert "(afternoon)" in _clock_line(420, _VPS_NOW)
    assert "(evening)" in _clock_line(720, _VPS_NOW)
    assert "(late night)" in _clock_line(-300, _VPS_NOW)


def case_offset_wins_over_iana_zone():
    assert rhythm.tz_offset_for("America/Vancouver", -8, _VPS_NOW) == -480
    assert rhythm.tz_offset_for("America/Vancouver", None, _VPS_NOW) == -420
    assert rhythm.tz_offset_for("America/Vancouver", 0, _VPS_NOW) == -420
    assert rhythm.tz_offset_for(None, -8, _VPS_NOW) == -480
    assert rhythm.tz_offset_for(None, None, _VPS_NOW) is None
    assert rhythm.tz_offset_for(None, 0, _VPS_NOW) is None


async def case_load_clock_tz():
    async with get_session() as s:
        s.add(Account(id="acc_ck_off"))
        s.add(AccountAiConfig(account_id="acc_ck_off", utc_offset=-8))
        s.add(Account(id="acc_ck_iana"))
        s.add(AccountAiConfig(account_id="acc_ck_iana", utc_offset=0,
                              timezone="America/Vancouver"))
        s.add(Account(id="acc_ck_both"))
        s.add(AccountAiConfig(account_id="acc_ck_both", utc_offset=-8,
                              timezone="America/Vancouver"))
        s.add(Account(id="acc_ck_none"))
        s.add(AccountAiConfig(account_id="acc_ck_none", utc_offset=0))
    assert await _load_clock_tz("acc_ck_off") == -480
    assert await _load_clock_tz("acc_ck_iana") == -420
    assert await _load_clock_tz("acc_ck_both") == -480
    assert await _load_clock_tz("acc_ck_none") is None
    assert await _load_clock_tz("acc_ck_absent") is None



def case_all_builders_carry_clock():
    clock = _clock_line(-420, _VPS_NOW)
    msgs = [("in", "hey"), ("in", "what time is it where you are?")]
    f = Fan(account_id="a", fan_id=1, of_display_name="Witcher")

    with_c, _ = welcome_chatter_for_info._build_messages("persona", f, _mk_of_candidate(1, msgs),
                                           set(), clock=clock)
    without, _ = welcome_chatter_for_info._build_messages("persona", f, _mk_of_candidate(1, msgs),
                                            set())
    assert f"{_MARK} {clock}" in with_c[0]["content"], "welcome_chatter_for_info clock line"
    assert _MARK not in without[0]["content"], "welcome_chatter_for_info no-tz prompt unchanged"

    ar_c = autoreply._build_messages("persona", f, msgs, "casual", clock=clock)
    ar_n = autoreply._build_messages("persona", f, msgs, "casual")
    assert f"{_MARK} {clock}" in ar_c[0]["content"], "autoreply clock line"
    assert _MARK not in ar_n[0]["content"], "autoreply no-tz prompt unchanged"



def case_vps_convo_replay():
    convo = [
        ("out", "oh i like that answer witcher"),
        ("in", "What are you doing rn?"),
        ("out", "makin my coffee n watchin my pups chase each other round the yard"),
        ("out", "what about u"),
        ("in", "Ya I'm having a drink and cuddling with the doggo. I'm guessing "
               "you're not on the island anymore if you're making coffee"),
        ("out", "bakc on the mainland now"),
        ("in", "The mainland? What time is it where you are?"),
    ]
    f = Fan(account_id="a", fan_id=7, of_display_name="Witcher")
    clock = _clock_line(rhythm.tz_offset_for("America/Vancouver", None, _VPS_NOW),
                        _VPS_NOW)
    msgs, _ = welcome_chatter_for_info._build_messages("persona", f,
                                                       _mk_of_candidate(7, convo), set(),
                                                       clock=clock)
    system, user = msgs[0]["content"], msgs[1]["content"]
    assert f"{_MARK} Thursday, July 23 — 12:32 AM (late night)" in system, system[:400]
    assert "never claim a different time of day" in system
    assert "What time is it where you are?" in user, "his question reaches the model"



async def case_welcome_chatter_for_info_run_wires_clock():
    aid = "acc_ck_run"
    async with get_session() as s:
        s.add(Account(id=aid))
        s.add(AccountAiConfig(account_id=aid, utc_offset=-8))
        s.add(Fan(account_id=aid, fan_id=901, of_display_name="Bob"))
    async with get_session() as s:
        from db.models import Message
        s.add(Message(account_id=aid, fan_id=901, message_id=901001,
                      direction="out", body="hey babe",
                      created_at=datetime(2026, 7, 23, 7, 0)))
        s.add(Message(account_id=aid, fan_id=901, message_id=901002,
                      direction="in", body="what time is it there?",
                      created_at=datetime(2026, 7, 23, 7, 1)))
    _use_fake()
    seen = _patch_llm_capture()
    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["status"] == "ok", res
    systems = [m[0]["content"] for m in seen if m]
    assert any(_MARK in sysmsg for sysmsg in systems), \
        ("clock line must reach the LLM", [s[:120] for s in systems])

    aid2 = "acc_ck_run_notz"
    async with get_session() as s:
        s.add(Account(id=aid2))
        s.add(Fan(account_id=aid2, fan_id=902, of_display_name="Al"))
    async with get_session() as s:
        from db.models import Message
        s.add(Message(account_id=aid2, fan_id=902, message_id=902001,
                      direction="out", body="hey babe",
                      created_at=datetime(2026, 7, 23, 7, 0)))
        s.add(Message(account_id=aid2, fan_id=902, message_id=902002,
                      direction="in", body="what time is it there?",
                      created_at=datetime(2026, 7, 23, 7, 1)))
    _use_fake()
    seen2 = _patch_llm_capture()
    res2 = await run_once(aid2, "welcome_chatter_for_info", payload={})
    assert res2["status"] == "ok", res2
    assert seen2, "the no-tz account still replies"
    assert all(_MARK not in (m[0]["content"] if m else "") for m in seen2), \
        "a no-tz account must NOT be given a clock"


if __name__ == "__main__":
    _harness.run(
        case_clock_line_formats,
        case_offset_wins_over_iana_zone,
        case_load_clock_tz,
        case_all_builders_carry_clock,
        case_vps_convo_replay,
        case_welcome_chatter_for_info_run_wires_clock,
    )
