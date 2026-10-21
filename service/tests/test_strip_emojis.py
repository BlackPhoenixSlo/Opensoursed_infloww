"""Tests for the account-wide "Strip all emojis" toggle + the always-on
LIVE_PROOF_GUARDRAIL (FaceTime / "prove it" handling).

The model ignores a "no emojis" prompt and its emoji PLACEMENT is itself a dead
LLM tell, so when the account opts in we strip emojis IN CODE at the send
chokepoint. Verifies: the shared
strip_emojis() util removes emoji blocks but keeps em-dashes/apostrophes/text;
load_strip_emojis() defaults OFF on missing/NULL/garbage config and reads a real
true flag; the style_config_api whitelist round-trips the new key (the gotcha: an
un-whitelisted key is silently dropped on save); a real compose path
(send_followup.preview_compose) leaves emojis intact when OFF and strips them when
ON; and the live-proof guardrail is wired into every conversational sender.

Run: ./venv/bin/python service/tests/test_strip_emojis.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB + TEST_MODE
import inspect

from db.engine import get_session
from db.models import Account, AccountAiConfig, Fan
from automations._common import LIVE_PROOF_GUARDRAIL, load_strip_emojis, strip_emojis

_harness.bootstrap()


def case_strip_emojis_util():
    """Removes emoji / variation-selector / ZWJ / regional-indicator blocks, keeps
    plain text + em-dash + apostrophe, collapses the double space a removal leaves,
    and is empty/None-safe."""
    assert strip_emojis("hey 😏 babe 🙈") == "hey babe"          # mid + trailing
    assert strip_emojis("🥵😈 stop") == "stop"                    # leading run
    assert strip_emojis("yes 🇺🇸 sir") == "yes sir"               # regional-indicator pair
    # keep the punctuation an em-dash / apostrophe a real texter uses
    assert strip_emojis("i don't — really") == "i don't — really"
    assert strip_emojis("no emojis here") == "no emojis here"      # byte-for-byte
    assert strip_emojis("") == "" and strip_emojis(None) == ""     # safe on empty/None
    # an emoji-only string collapses to "" (the caller's `if p.strip()` drops it)
    assert strip_emojis("😏😏😏") == ""


async def case_load_strip_emojis_default_off():
    """load_strip_emojis is False on a missing row, NULL json, or garbage (existing
    accounts unaffected) and True only when the account-wide flag is set."""
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
    """style_config_api coerces to the known flags — strip_emojis must survive (an
    un-whitelisted key is silently dropped on save) and default OFF."""
    from style_config_api import _defaults, _persist, _resolved_view
    assert _defaults().get("strip_emojis") is False
    assert _persist({"strip_emojis": 1})["strip_emojis"] is True        # truthy → True
    assert _resolved_view({}).get("strip_emojis") is False              # absent → OFF
    # it doesn't disturb the existing per-automation flags (welcome_chatter_for_info defaults OFF)
    assert _resolved_view({"strip_emojis": True}).get("welcome_chatter_for_info") is False


async def case_compose_gating_followup():
    """A real compose path: with the flag OFF the emoji-laden model output is left
    intact; with it ON the returned text is emoji-free. Patches llm_client.chat so
    no network/cost-cap is touched."""
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
        assert "😏" in off["text"] and "🙈" in off["text"], off  # OFF → emojis kept

        on = await send_followup.preview_compose("se_compose_on", test_name="Jack")
        assert "😏" not in on["text"] and "🙈" not in on["text"], on  # ON → stripped
        assert "babe" in on["text"], on                              # text survives
    finally:
        llm_client.chat = orig


def case_live_proof_guardrail_content():
    """The guardrail names the live-proof asks and is unambiguously BLUNT (the whole
    point — no coy fumbling)."""
    g = LIVE_PROOF_GUARDRAIL.lower()
    assert "facetime" in g and "live call" in g, LIVE_PROOF_GUARDRAIL
    assert "blunt" in g and "direct" in g, LIVE_PROOF_GUARDRAIL
    assert "prove" in g, LIVE_PROOF_GUARDRAIL


def case_live_proof_guardrail_wired_into_senders():
    """Every conversational sender USES the guardrail in a prompt.

    The LANED engines (autoreply, welcome_chatter_for_info) are checked by RENDERING instead.
    They read the guardrail off `_voice.blocks(...)` because the block's worked
    examples vary by creator voice, so they neither import nor name the constant —
    and a grep for the symbol would report "not wired" for an engine that emits the
    text on every reply. Asserting the rendered prompt is what the count was ever a
    proxy for, and unlike the count it also proves the MALE lane carries the rule."""
    from automations import (welcome_chatter_for_info, _voice, autoreply, send_followup,
                             reply_mass_funnel)
    # NOTHING is source-counted any more. Every conversational sender now reads
    # `v.live_proof` off the bundle, because the block's worked examples vary by
    # creator voice — so none of them name the symbol, and a grep would report
    # "not wired" for engines that emit the text on every reply. The count is kept
    # only as a floor on the BUNDLE read, which is the thing that actually has
    # to be there.
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
    # …and the female lane is still the exact shared constant, not a near-copy.
    her_sys = autoreply._build_messages(
        "persona", fan, [("in", "hi")], "one short line")[0]["content"]
    assert LIVE_PROOF_GUARDRAIL in her_sys, "autoreply default lane drifted"
    assert LIVE_PROOF_GUARDRAIL in _welcome_chatter_for_info_sys(), "welcome_chatter_for_info default lane drifted"
    # …and the assembled followup system prompt actually carries it
    # send_followup: absent bundle → the female lane, byte-for-byte…
    sysmsg = send_followup._compose_system({}, "morning", "", "", "Jack", "")
    assert LIVE_PROOF_GUARDRAIL in sysmsg, sysmsg
    # …and an explicit male bundle swaps the refusal rather than dropping it
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
