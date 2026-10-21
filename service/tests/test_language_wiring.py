#!/usr/bin/env python3
"""test_language_wiring.py — R3 wiring: the OUTPUT-LANGUAGE directive actually reaches
the engines' system prompts, and load_account_language reads the column.

Run:  ./venv/bin/python service/tests/test_language_wiring.py
"""
import _harness  # noqa: F401 — MUST be first

_harness.bootstrap()

from automations import _language as L  # noqa: E402
from automations import welcome_chatter_for_info  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, Fan  # noqa: E402


def _mk_of_candidate(fan_id: int):
    c = welcome_chatter_for_info._Candidate(fan_id)
    c.fan_msg_n = 5
    c.last_dir = "in"
    c.last_body = "hola guapa"
    c.messages = [("in", "hola"), ("in", "que tal"), ("in", "hola guapa")]
    return c


def case_welcome_chatter_for_info_directive_es_vs_en():
    f = Fan(account_id="a", fan_id=1, of_display_name="Bob")
    c = _mk_of_candidate(1)
    msgs_es, _ = welcome_chatter_for_info._build_messages("persona", f, c, set(), lang="es")
    msgs_en, _ = welcome_chatter_for_info._build_messages("persona", f, c, set(), lang="en")
    sys_es = msgs_es[0]["content"]
    sys_en = msgs_en[0]["content"]
    assert "OUTPUT LANGUAGE" in sys_es and "Español" in sys_es, "es directive present"
    assert "'STICKER:' stay in English" in sys_es, "protocol token pinned"
    assert "OUTPUT LANGUAGE" not in sys_en, "en prompt unchanged"
    # the directive is at the END (prefix preserved for cache).
    assert sys_es.startswith(sys_en[:200]), "shared prefix preserved"


def case_autoreply_directive_es_vs_en():
    from automations import autoreply
    f = Fan(account_id="a", fan_id=3, of_display_name="Bob")
    hist = [("in", "hola"), ("in", "que tal")]
    es = autoreply._build_messages("persona", f, hist, "casual", lang="es")
    en = autoreply._build_messages("persona", f, hist, "casual", lang="en")
    assert "OUTPUT LANGUAGE" in es[0]["content"] and "Español" in es[0]["content"]
    assert "OUTPUT LANGUAGE" not in en[0]["content"]


def case_per_fan_routing_overrides_account():
    """Per-fan routing: every engine now sends lang=resolve_language(account_lang,
    fan.language). A fan pinned OR gen_info-detected 'es' on an 'en' account replies in
    Spanish; an unpinned fan on the same account stays English (no account change)."""
    from automations import welcome_chatter_for_info, autoreply
    ACC = "en"  # account default is English

    # precedence: a per-fan value wins; unset/blank falls back to the account default
    assert L.resolve_language(ACC, "es") == "es"
    assert L.resolve_language(ACC, None) == "en"
    assert L.resolve_language(ACC, "") == "en"

    es_fan = Fan(account_id="a", fan_id=11, of_display_name="Bob", language="es")
    en_fan = Fan(account_id="a", fan_id=12, of_display_name="Al", language=None)

    def eff(fan):  # exactly what the engines compute per fan
        return L.resolve_language(ACC, getattr(fan, "language", None))

    # welcome_chatter_for_info returns (msgs, presented); autoreply returns msgs
    of_es, _ = welcome_chatter_for_info._build_messages("persona", es_fan, _mk_of_candidate(11), set(), lang=eff(es_fan))
    of_en, _ = welcome_chatter_for_info._build_messages("persona", en_fan, _mk_of_candidate(12), set(), lang=eff(en_fan))
    assert "Español" in of_es[0]["content"], "es fan on en account → Spanish"
    assert "OUTPUT LANGUAGE" not in of_en[0]["content"], "unpinned fan on en account → English"

    ar_es = autoreply._build_messages("persona", es_fan, [("in", "hola")], "casual", lang=eff(es_fan))
    assert "Español" in ar_es[0]["content"]


async def case_load_account_language():
    async with get_session() as s:
        s.add(Account(id="acc_lang_load"))
        s.add(AccountAiConfig(account_id="acc_lang_load", language="es"))
        s.add(Account(id="acc_lang_none"))
        s.add(AccountAiConfig(account_id="acc_lang_none"))  # language NULL
    assert await L.load_account_language("acc_lang_load") == "es"
    assert await L.load_account_language("acc_lang_none") == "en"   # NULL → en
    assert await L.load_account_language("acc_absent") == "en"      # no row → en


if __name__ == "__main__":
    _harness.run(
        case_welcome_chatter_for_info_directive_es_vs_en,
        case_autoreply_directive_es_vs_en,
        case_per_fan_routing_overrides_account,
        case_load_account_language,
    )
