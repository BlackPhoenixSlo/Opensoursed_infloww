#!/usr/bin/env python3
"""
copilot_api — POST /admin/copilot/{account_id}/{fan_id}/suggest, Messages Pro's
AI Copilot.

Drives the route coroutine directly against the temp DB with `llm_client.chat`
patched — this suite must NEVER buy a real completion. Covers: one call per
click returning three options, the prompt grounded in persona + fan facts + the
newest thread row + the picked mode, Tip request as the only mode allowed to
ask for money, Regenerate's `avoid` reaching the prompt, the unknown-mode
refusal, the provider failures (cap 429, provider 502, key error left to the
app-wide 424), the outbound floor (off-platform guard, banned words), the
account gate, and the route sitting under Messages Pro for Role enforcement.

Run: ./venv/bin/python service/tests/test_copilot_api.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import json  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"  # read per call; a case flips it back

from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402

import copilot_api  # noqa: E402
import llm_client  # noqa: E402
import permissions  # noqa: E402
from copilot_api import SuggestBody, suggest  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, AccountAiConfig, Fan, Message, SensitiveWord, User, UserAccount,
)
from llm_client import LLMCapExceeded, LLMHTTPError, LLMKeyError, LLMResult  # noqa: E402

AID = "acc_copilot_test"
FID = 7001
PERSONA = "You are Ava, 23, a playful gym girl from Miami."


class _Spy:
    """Stands in for llm_client.chat: records the kwargs, returns/raises."""

    def __init__(self, suggestions=("one", "two", "three"), raises=None):
        self.parsed = {"suggestions": list(suggestions)}
        self.raises = raises
        self.calls: list[dict] = []

    async def __call__(self, **kw):
        self.calls.append(kw)
        if self.raises is not None:
            raise self.raises
        return LLMResult(
            call_id=1, model=kw["model"], provider="deepseek",
            content=json.dumps(self.parsed), parsed=self.parsed,
            reasoning_content=None, tokens_in=100, tokens_out=30,
            cache_hit_tokens=0, cost_cents=0, latency_ms=5,
        )


def _patch(spy: _Spy) -> _Spy:
    llm_client.chat = spy  # copilot_api calls through the MODULE, so this lands
    return spy


def _system(spy) -> str:
    return spy.calls[-1]["messages"][0]["content"]


def _user(spy) -> str:
    return spy.calls[-1]["messages"][1]["content"]


async def _seed(aid: str = AID, fid: int = FID, banned: list[str] = ()) -> None:
    now = datetime.utcnow()
    async with get_session() as s:
        if await s.get(Account, aid) is not None:
            return
        s.add(Account(id=aid))
        s.add(AccountAiConfig(account_id=aid, persona=PERSONA))
        if banned:  # the owning Agency's Growth > Sensitive words
            agency = f"u_{aid}"
            s.add(User(id=agency, username=agency, password="x"))
            await s.flush()
            s.add(UserAccount(user_id=agency, account_id=aid))
            for w in banned:
                s.add(SensitiveWord(agency_user_id=agency, word=w, word_key=w.lower()))
        s.add(Fan(account_id=aid, fan_id=fid, occupation="firefighter"))
        hist = [("out", "hey 😏"), ("in", "haha hi"), ("out", "what u up to"),
                ("in", "just got off a night shift")]
        for i, (d, b) in enumerate(hist):
            s.add(Message(account_id=aid, fan_id=fid, message_id=fid * 100 + i,
                          direction=d, body=f"<p>{b}</p>",
                          created_at=now - timedelta(minutes=10 - i)))


async def _suggest(mode: str = "casual", avoid=(), aid: str = AID, fid: int = FID):
    return await suggest(aid, fid, SuggestBody(mode=mode, avoid=list(avoid)))


# ── Cases ─────────────────────────────────────────────────────────────

async def case_one_click_is_one_call_returning_three_suggestions():
    await _seed()
    spy = _patch(_Spy(("a", "b", "c")))
    out = await _suggest()
    assert out == {"mode": "casual", "suggestions": ["a", "b", "c"]}, out
    assert len(spy.calls) == 1, spy.calls
    kw = spy.calls[0]
    assert kw["purpose"] == "copilot" and kw["account_id"] == AID and kw["fan_id"] == FID, kw
    assert kw["response_format"] == {"type": "json_object"}, kw


async def case_the_prompt_is_grounded_in_persona_facts_thread_and_mode():
    await _seed()
    spy = _patch(_Spy())
    await _suggest("reengage")
    assert PERSONA in _system(spy)
    assert copilot_api.MODES["reengage"] in _system(spy)
    assert "job: firefighter" in _user(spy)
    assert "FAN: just got off a night shift" in _user(spy)
    assert "He spoke last" in _user(spy)


async def case_only_tip_request_may_ask_for_money():
    await _seed()
    spy = _patch(_Spy())
    for mode in copilot_api.MODES:
        await _suggest(mode)
        paid_rule = "NEVER offer or hint at PPV" in _system(spy)
        assert paid_rule == (mode != "tip_request"), (mode, _system(spy))
    assert list(copilot_api.MODES) == ["casual", "reengage", "tip_request", "sexting"]


async def case_regenerate_sends_the_set_on_screen_as_avoid():
    await _seed()
    spy = _patch(_Spy())
    await _suggest("sexting", avoid=["old option one", "old option two"])
    assert "old option one" in _user(spy) and "old option two" in _user(spy)
    await _suggest("sexting")
    assert "earlier options" not in _user(spy)


async def case_an_unknown_mode_is_refused():
    for bad in ("selling", "tip request", ""):
        try:
            SuggestBody(mode=bad)
        except ValidationError:
            continue
        raise AssertionError(f"mode {bad!r} was accepted")


async def case_the_daily_cap_is_a_429_and_the_provider_a_502():
    await _seed()
    for exc, status in ((LLMCapExceeded(AID, 100, 101), 429),
                        (LLMHTTPError("boom", status=500), 502)):
        _patch(_Spy(raises=exc))
        try:
            await _suggest()
        except HTTPException as e:
            assert e.status_code == status, (exc, e.status_code)
        else:
            raise AssertionError(f"{exc!r} did not raise")


async def case_a_key_error_reaches_the_app_wide_424_handler_untouched():
    """LLMKeyError subclasses LLMHTTPError: catching the parent first would
    turn the owner's "add your key" notice into a 502."""
    await _seed()
    _patch(_Spy(raises=LLMKeyError("missing", "deepseek", "copilot")))
    try:
        await _suggest()
    except LLMKeyError:
        pass
    else:
        raise AssertionError("the key error was swallowed")


async def case_the_outbound_floor_guards_each_option():
    aid, fid = "acc_copilot_floor", 7002
    await _seed(aid, fid, banned=["venmo"])
    _patch(_Spy(("text me on snapchat at ava99", "send it to my venmo", "hiii u")))
    out = await _suggest(aid=aid, fid=fid)
    assert "snapchat" not in json.dumps(out).lower(), out   # off-platform guard
    assert not any("venmo" in s for s in out["suggestions"]), out  # banned → dropped
    assert "hiii u" in out["suggestions"], out


async def case_no_usable_option_is_a_502():
    await _seed()
    _patch(_Spy(()))
    try:
        await _suggest()
    except HTTPException as e:
        assert e.status_code == 502, e.status_code
    else:
        raise AssertionError("an empty answer came back as success")


async def case_an_unknown_fan_is_a_404_before_any_call():
    await _seed()
    spy = _patch(_Spy())
    try:
        await _suggest(fid=999999)
    except HTTPException as e:
        assert e.status_code == 404, e.status_code
    else:
        raise AssertionError("an unknown fan was served")
    assert spy.calls == []


async def case_the_account_gate_is_not_optional():
    await _seed()
    spy = _patch(_Spy())
    os.environ["ALLOW_ANONYMOUS_ADMIN"] = "0"
    try:
        try:
            await _suggest()
        except HTTPException as e:
            assert e.status_code == 401, e.status_code
        else:
            raise AssertionError("an anonymous suggest sailed through the gate")
    finally:
        os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"
    assert spy.calls == []


async def case_role_enforcement_reads_it_as_messages_pro():
    pages = permissions.route_pages(f"/admin/copilot/{AID}/{FID}/suggest", "POST") or ()
    assert "/messages-pro" in pages, pages


if __name__ == "__main__":
    _harness.run()
