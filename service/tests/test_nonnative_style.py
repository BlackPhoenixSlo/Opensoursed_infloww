from __future__ import annotations

import _harness
import random

from db.engine import get_session
from db.models import Account, AccountAiConfig
from automations._common import (
    apply_nonnative_style, humanize_typos, load_nonnative_flags, nonnative_flag_key,
    typo_flag_key, NONNATIVE_MISSPELLINGS, NONNATIVE_OUTPUTS, NONNATIVE_PHRASES,
    STYLE_AUTOMATIONS,
)

_harness.bootstrap()


def case_deterministic_and_known_words_swapped():
    txt = "i think im gonna do it, of course, definitely"
    a = apply_nonnative_style(txt)
    b = apply_nonnative_style(txt)
    assert a == b, (a, b)
    assert "conna" in a and "ofcoas" in a and "deffinetly" in a, a
    assert "gonna" not in a and "definitely" not in a, a
    assert apply_nonnative_style("Definitely") == "Deffinetly"
    assert apply_nonnative_style("GONNA") == "CONNA"
    assert apply_nonnative_style("gonnabe") == "gonnabe"
    assert apply_nonnative_style("hiw long do you want") == "hiw long do you want"
    assert apply_nonnative_style("how long do you want") == "hiw long do you want"
    assert apply_nonnative_style("Hiw are u today") == "Hiw are u today"
    assert apply_nonnative_style("its so beautiful") == "its so beautifull"
    assert apply_nonnative_style("however showing") == "however showing"


def case_space_before_question_mark_is_occasional():
    from automations._common import apply_nonnative_spacing

    assert apply_nonnative_style("Do you like it?") == "Do you like it?"

    always = lambda: 0.0  # noqa: E731 — rng stub that always fires
    rng = type("R", (), {"random": staticmethod(always)})()
    assert apply_nonnative_spacing("u sure?? tell me", rng) == "u sure ?? tell me"
    assert apply_nonnative_spacing("ready?!", rng) == "ready ?!"

    assert apply_nonnative_spacing("onlyfans.com/x?y=1", rng) == "onlyfans.com/x?y=1"
    assert apply_nonnative_spacing("@her_xo?", rng) == "@her_xo?"
    assert apply_nonnative_spacing("no question here", rng) == "no question here"
    assert apply_nonnative_spacing("", rng) == ""

    never = type("R", (), {"random": staticmethod(lambda: 1.0)})()
    assert apply_nonnative_spacing("Do you like it?", never) == "Do you like it?"

    def _render(seed):
        r = random.Random(seed)
        return [apply_nonnative_spacing(apply_nonnative_style(p), r)
                for p in ("how are you?", "really?")]

    assert _render(11) == _render(11)
    assert "hiw" in _render(11)[0], _render(11)

    seen = {tuple(" ?" in p for p in _render(s)) for s in range(60)}
    assert len(seen) > 2, seen

    hits = sum(apply_nonnative_spacing("it?", random.Random(i)).startswith("it ")
               for i in range(2000))
    assert 0.20 <= hits / 2000 <= 0.33, hits / 2000


def case_unknown_words_unchanged_byte_for_byte():
    plain = "hey there babe what are you doing tonight"
    assert apply_nonnative_style(plain) == plain
    assert apply_nonnative_style("") == ""
    assert apply_nonnative_style("gonna!") == "conna!"
    assert apply_nonnative_style("(gonna)") == "(conna)"
    assert apply_nonnative_style("...definitely?") == "...deffinetly?"


def case_protected_tokens_never_mutate():
    assert apply_nonnative_style("@gonna_xo") == "@gonna_xo"
    assert apply_nonnative_style("onlyfans.com/gonna") == "onlyfans.com/gonna"
    assert apply_nonnative_style("$25") == "$25"
    assert apply_nonnative_style("gonna2") == "gonna2"
    assert apply_nonnative_style("gonna😏") == "gonna😏"
    assert apply_nonnative_style("gonna", protect=["Gonna"]) == "gonna"
    out = apply_nonnative_style("subscription is $25 babe", protect=["Jack"])
    assert out == "subscribtion is $25 babe", out


def case_pipeline_order_no_double_mangle():
    parts = [apply_nonnative_style("im gonna send you the subscription link of course")]
    for w in ("conna", "subscribtion", "ofcoas"):
        assert w in parts[0], (w, parts[0])
    for seed in range(30):
        out = humanize_typos(list(parts), random.Random(seed),
                             protect=list(NONNATIVE_OUTPUTS), max_bubbles=6)
        assert len(out) <= 6, (seed, out)
        joined = " ".join(out)
        for w in ("conna", "subscribtion", "ofcoas"):
            assert w in joined, (seed, w, out)


async def case_load_flags_default_off():
    default = {k: k == "autoreply" for k in STYLE_AUTOMATIONS}
    flags = await load_nonnative_flags("nn_missing")
    assert flags == default, flags

    async def _seed(aid: str, raw):
        async with get_session() as s:
            if await s.get(Account, aid) is None:
                s.add(Account(id=aid))
            s.add(AccountAiConfig(account_id=aid, style_config_json=raw))

    await _seed("nn_null", None)
    await _seed("nn_garbage", "{not valid json")
    await _seed("nn_on", '{"nonnative_welcome_chatter_for_info": true}')
    assert (await load_nonnative_flags("nn_null")) == default
    assert (await load_nonnative_flags("nn_garbage")) == default
    on = await load_nonnative_flags("nn_on")
    assert on["welcome_chatter_for_info"] is True, on
    assert on["autoreply"] is True, on


def case_api_roundtrip_keeps_nonnative_key():
    from style_config_api import _defaults, _persist, _resolved_view
    defaults = _defaults()
    for a in STYLE_AUTOMATIONS:
        assert nonnative_flag_key(a) in defaults, (a, defaults)
    assert defaults[nonnative_flag_key("welcome_chatter_for_info")] is False, defaults
    assert defaults[nonnative_flag_key("autoreply")] is True, defaults

    persisted = _persist({nonnative_flag_key("welcome_chatter_for_info"): True})
    assert persisted[nonnative_flag_key("welcome_chatter_for_info")] is True, persisted
    assert nonnative_flag_key("autoreply") not in persisted, persisted
    assert "autoreply" not in persisted, persisted

    saved = _persist({nonnative_flag_key("welcome_chatter_for_info"): True})
    view = _resolved_view(saved)
    assert view[nonnative_flag_key("welcome_chatter_for_info")] is True, view
    assert view["autoreply"] is True and view[typo_flag_key("autoreply")] is True \
        and view[nonnative_flag_key("autoreply")] is True, view


def case_dict_entries_are_lowercase_keys():
    for k in NONNATIVE_MISSPELLINGS:
        assert k == k.lower(), k
    for k in NONNATIVE_PHRASES:
        assert k == k.lower(), k
    assert set(NONNATIVE_OUTPUTS) >= set(NONNATIVE_MISSPELLINGS.values())
    assert set(NONNATIVE_OUTPUTS) >= set(NONNATIVE_PHRASES.values())


if __name__ == "__main__":
    _harness.run(
        case_deterministic_and_known_words_swapped,
        case_unknown_words_unchanged_byte_for_byte,
        case_space_before_question_mark_is_occasional,
        case_protected_tokens_never_mutate,
        case_pipeline_order_no_double_mangle,
        case_load_flags_default_off,
        case_api_roundtrip_keeps_nonnative_key,
        case_dict_entries_are_lowercase_keys,
    )
