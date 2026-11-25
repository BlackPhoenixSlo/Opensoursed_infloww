from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB + TEST_MODE
import inspect

from db.engine import get_session
from db.models import Account, AccountAiConfig, Fan
from automations._common import LIVE_PROOF_GUARDRAIL, load_strip_emojis, strip_emojis

_harness.bootstrap()


def case_strip_emojis_util():
    assert strip_emojis("hey 😏 babe 🙈") == "hey babe"
    assert strip_emojis("🥵😈 stop") == "stop"
    assert strip_emojis("yes 🇺🇸 sir") == "yes sir"
    assert strip_emojis("i don't — really") == "i don't — really"
    assert strip_emojis("no emojis here") == "no emojis here"
    assert strip_emojis("") == "" and strip_emojis(None) == ""
    assert strip_emojis("😏😏😏") == ""
    assert strip_emojis("(⌒‿⌒) ⌘") == "(⌒‿⌒) ⌘"
    assert strip_emojis("⌚ ⏳") == ""
    assert strip_emojis("❤️ 👩‍❤️‍👩") == ""


async def case_load_strip_emojis_default_off():
    assert (await load_strip_emojis("se_missing")) is False

    async def _seed(aid: str, raw):
        async with get_session() as s:
            if await s.get(Account, aid) is None:
                s.add(Account(id=aid))
            s.add(AccountAiConfig(account_id=aid, style_config_json=raw))

    await _seed("se_null", None)
    await _seed("se_garbage", "{not valid json")
    await _seed("se_off", '{"strip_emojis": false}')
    await _seed("se_on", '{"strip_emojis": true}')
    assert (await load_strip_emojis("se_null")) is False
    assert (await load_strip_emojis("se_garbage")) is False
    assert (await load_strip_emojis("se_off")) is False
    assert (await load_strip_emojis("se_on")) is True


def case_api_roundtrip_keeps_strip_emojis_key():
    from style_config_api import _defaults, _persist, _resolved_view
    assert _defaults().get("strip_emojis") is False
    assert _persist({"strip_emojis": 1})["strip_emojis"] is True
    assert _resolved_view({}).get("strip_emojis") is False
    assert _resolved_view({"strip_emojis": True}).get("welcome_chatter_for_info") is False


async def case_compose_gating_followup():
    import llm_client
    from automations import send_followup

    class _Res:
        content = "hey babe 😏 been thinkin about u 🙈"

    async def _fake_chat(*a, **k):
        return _Res()

    orig = llm_client.chat
    llm_client.chat = _fake_chat
    try:
        async with get_session() as s:
            if await s.get(Account, "se_compose_off") is None:
                s.add(Account(id="se_compose_off"))
            if await s.get(Account, "se_compose_on") is None:
                s.add(Account(id="se_compose_on"))
            s.add(AccountAiConfig(account_id="se_compose_off", style_config_json="{}"))
            s.add(AccountAiConfig(account_id="se_compose_on",
                                  style_config_json='{"strip_emojis": true}'))

        off = await send_followup.preview_compose("se_compose_off", test_name="Jack")
        assert "😏" in off["text"] and "🙈" in off["text"], off

        on = await send_followup.preview_compose("se_compose_on", test_name="Jack")
        assert "😏" not in on["text"] and "🙈" not in on["text"], on
        assert "babe" in on["text"], on
    finally:
        llm_client.chat = orig


def case_live_proof_guardrail_content():
    g = LIVE_PROOF_GUARDRAIL.lower()
    assert "facetime" in g and "live call" in g, LIVE_PROOF_GUARDRAIL
    assert "blunt" in g and "direct" in g, LIVE_PROOF_GUARDRAIL
    assert "prove" in g, LIVE_PROOF_GUARDRAIL


def case_live_proof_guardrail_wired_into_senders():
    from automations import (welcome_chatter_for_info, _voice, autoreply, send_followup,
                             reply_mass_funnel)
    got = inspect.getsource(reply_mass_funnel).count("v.live_proof")
    assert got >= 1, f"reply_mass_funnel: {got} bundle reads, want >= 1"

    fan = Fan(account_id="a", fan_id=1, of_display_name="Bob")

    def _welcome_chatter_for_info_sys(**kw) -> str:
        c = welcome_chatter_for_info._Candidate(1)
        c.last_body = "hi"
        c.messages = [("in", "hi")]
        return welcome_chatter_for_info._build_messages("persona", fan, c, set(), **kw)[0][0]["content"]

    for voice in ("her", "him"):
        v = _voice.blocks(voice)
        for name, sysmsg in (("autoreply", autoreply._build_messages(
                                  "persona", fan, [("in", "hi")], "one short line",
                                  v=v)[0]["content"]),
                             ("welcome_chatter_for_info", _welcome_chatter_for_info_sys(v=v))):
            assert "LIVE PROOF / FACETIME (hard rule):" in sysmsg, f"{name}/{voice}"
    her_sys = autoreply._build_messages(
        "persona", fan, [("in", "hi")], "one short line")[0]["content"]
    assert LIVE_PROOF_GUARDRAIL in her_sys, "autoreply default lane drifted"
    assert LIVE_PROOF_GUARDRAIL in _welcome_chatter_for_info_sys(), "welcome_chatter_for_info default lane drifted"
    sysmsg = send_followup._compose_system({}, "morning", "", "", "Jack", "")
    assert LIVE_PROOF_GUARDRAIL in sysmsg, sysmsg
    him = send_followup._compose_system(
        {"_voice": _voice.blocks("him")}, "morning", "", "", "Jack", "")
    assert "LIVE PROOF / FACETIME (hard rule):" in him
    assert "facetime babe" not in him, "send_followup/him still refuses like a woman"


if __name__ == "__main__":
    _harness.run(
        case_strip_emojis_util,
        case_load_strip_emojis_default_off,
        case_api_roundtrip_keeps_strip_emojis_key,
        case_compose_gating_followup,
        case_live_proof_guardrail_content,
        case_live_proof_guardrail_wired_into_senders,
    )
