"""Tests for the "non-native English" style layer (_common.apply_nonnative_style
+ load_nonnative_flags + the style_config_api whitelist).

Unlike the thumb-typo injector, this layer is DETERMINISTIC and applied ALWAYS when
on (a non-native speaker misspells the same word the same way every time). Verifies:
same input → same output, known words get their misspelling, protected tokens
(name / price / @handle / link / emoji) never mutate, the flag defaults OFF on
absent/NULL/garbage config, the nonnative+typos pipeline never double-mangles a word
or exceeds the bubble cap, and the API coercion keeps the nonnative_ key.

Run: ./venv/bin/python service/tests/test_nonnative_style.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB + TEST_MODE
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
    """Same input → same output (no rng), and every known word/phrase lands its
    non-native spelling at word boundaries, case-insensitively."""
    txt = "i think im gonna do it, of course, definitely"
    a = apply_nonnative_style(txt)
    b = apply_nonnative_style(txt)
    assert a == b, (a, b)
    assert "conna" in a and "ofcoas" in a and "deffinetly" in a, a
    assert "gonna" not in a and "definitely" not in a, a
    # case-insensitive match, casing carried onto the replacement
    assert apply_nonnative_style("Definitely") == "Deffinetly"
    assert apply_nonnative_style("GONNA") == "CONNA"
    # word boundary — a substring is NOT swapped ('gonna' inside a longer token)
    assert apply_nonnative_style("gonnabe") == "gonnabe"
    # entries harvested from the creator's own sent messages
    assert apply_nonnative_style("hiw long do you want") == "hiw long do you want"
    assert apply_nonnative_style("how long do you want") == "hiw long do you want"
    assert apply_nonnative_style("Hiw are u today") == "Hiw are u today"
    assert apply_nonnative_style("its so beautiful") == "its so beautifull"
    # 'how' must not fire inside a longer word ('however', 'showing')
    assert apply_nonnative_style("however showing") == "however showing"


def case_space_before_question_mark_is_occasional():
    """The creator's loudest habit ("Do you like it ?") — 187 of her 728 question
    messages carry it, 0 of 3,336 bot sends did. Rolls per '?' RUN so it reads as
    a habit, not a broken keyboard, and only when the caller passes an rng."""
    from automations._common import apply_nonnative_spacing

    # apply_nonnative_style stays DETERMINISTIC — spacing is a separate step the
    # senders apply after it, never an optional mode hidden inside it.
    assert apply_nonnative_style("Do you like it?") == "Do you like it?"

    # a run of '?' stays ONE unit — never "? ?"
    always = lambda: 0.0  # noqa: E731 — rng stub that always fires
    rng = type("R", (), {"random": staticmethod(always)})()
    assert apply_nonnative_spacing("u sure?? tell me", rng) == "u sure ?? tell me"
    assert apply_nonnative_spacing("ready?!", rng) == "ready ?!"

    # a link's query string is punctuation-critical and must survive intact
    assert apply_nonnative_spacing("onlyfans.com/x?y=1", rng) == "onlyfans.com/x?y=1"
    assert apply_nonnative_spacing("@her_xo?", rng) == "@her_xo?"
    # nothing to do
    assert apply_nonnative_spacing("no question here", rng) == "no question here"
    assert apply_nonnative_spacing("", rng) == ""

    # never fires when the roll always loses
    never = type("R", (), {"random": staticmethod(lambda: 1.0)})()
    assert apply_nonnative_spacing("Do you like it?", never) == "Do you like it?"

    # same seed → same output (the reply must not re-render differently)
    def _render(seed):
        r = random.Random(seed)
        return [apply_nonnative_spacing(apply_nonnative_style(p), r)
                for p in ("how are you?", "really?")]

    assert _render(11) == _render(11)
    # ...and it composes with the misspelling pass rather than fighting it
    assert "hiw" in _render(11)[0], _render(11)

    # ONE rng across a reply's bubbles → the '?'s decide INDEPENDENTLY. Re-seeding
    # per bubble replays the same roll and every bubble agrees, which is the
    # broken-keyboard artifact the rate exists to avoid.
    seen = {tuple(" ?" in p for p in _render(s)) for s in range(60)}
    assert len(seen) > 2, seen  # not just all-on / all-off

    # roughly a quarter of questions, not all of them
    hits = sum(apply_nonnative_spacing("it?", random.Random(i)).startswith("it ")
               for i in range(2000))
    assert 0.20 <= hits / 2000 <= 0.33, hits / 2000


def case_unknown_words_unchanged_byte_for_byte():
    """A reply with no known words is returned EXACTLY as-is (default = current
    behavior). Punctuation and spacing around a swapped word are preserved."""
    # No dictionary word here — note 'how' is deliberately NOT used, it IS one now
    # (harvested from Sophiepaid: 'how' → 'hiw').
    plain = "hey there babe what are you doing tonight"
    assert apply_nonnative_style(plain) == plain
    assert apply_nonnative_style("") == ""
    # surrounding punctuation kept; only the alpha core swaps
    assert apply_nonnative_style("gonna!") == "conna!"
    assert apply_nonnative_style("(gonna)") == "(conna)"
    assert apply_nonnative_style("...definitely?") == "...deffinetly?"


def case_protected_tokens_never_mutate():
    """A token carrying a digit / @handle / link / '$' / emoji — or a protected name
    — is NEVER touched, even if a known word is embedded in it."""
    # 'gonna' embedded in a handle / link / price-adjacent token stays put
    assert apply_nonnative_style("@gonna_xo") == "@gonna_xo"
    assert apply_nonnative_style("onlyfans.com/gonna") == "onlyfans.com/gonna"
    assert apply_nonnative_style("$25") == "$25"
    assert apply_nonnative_style("gonna2") == "gonna2"
    assert apply_nonnative_style("gonna😏") == "gonna😏"
    # a protected NAME that happens to be a dict word is never swapped
    assert apply_nonnative_style("gonna", protect=["Gonna"]) == "gonna"
    # …but a non-protected known word in the same string still swaps
    out = apply_nonnative_style("subscription is $25 babe", protect=["Jack"])
    assert out == "subscribtion is $25 babe", out


def case_pipeline_order_no_double_mangle():
    """nonnative FIRST, then humanize_typos with NONNATIVE_OUTPUTS in `protect` — the
    word the dict already mangled is never re-mangled, and the bubble cap holds."""
    parts = [apply_nonnative_style("im gonna send you the subscription link of course")]
    # the dict outputs are all present and intact before the typo pass
    for w in ("conna", "subscribtion", "ofcoas"):
        assert w in parts[0], (w, parts[0])
    for seed in range(30):
        out = humanize_typos(list(parts), random.Random(seed),
                             protect=list(NONNATIVE_OUTPUTS), max_bubbles=6)
        assert len(out) <= 6, (seed, out)
        joined = " ".join(out)
        # every non-native output survives the typo pass unchanged (protected)
        for w in ("conna", "subscribtion", "ofcoas"):
            assert w in joined, (seed, w, out)


async def case_load_flags_default_off():
    """TRI-STATE default on a missing row, NULL json, or garbage: an ABSENT key
    resolves to the per-automation default — ON for autoreply, OFF for the rest.
    Also reads a real per-automation true flag."""
    # the absent-key default — shared expectation
    default = {k: k == "autoreply" for k in STYLE_AUTOMATIONS}
    # no AccountAiConfig row at all
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
    assert on["autoreply"] is True, on   # absent → autoreply's default-ON


def case_api_roundtrip_keeps_nonnative_key():
    """style_config_api coerces to the known flags — the nonnative_ keys must survive
    (the gotcha: an un-whitelisted key is silently dropped on save). And the v2
    tri-state: absent keys are LEFT ABSENT on persist, so an unrelated save can't
    stamp an explicit false over a default."""
    from style_config_api import _defaults, _persist, _resolved_view
    defaults = _defaults()
    for a in STYLE_AUTOMATIONS:
        assert nonnative_flag_key(a) in defaults, (a, defaults)
    # info-gather's non-native layer defaults OFF; Auto-reply's defaults ON.
    assert defaults[nonnative_flag_key("welcome_chatter_for_info")] is False, defaults
    assert defaults[nonnative_flag_key("autoreply")] is True, defaults

    # a PUT carrying the nonnative key round-trips it (not stripped)...
    persisted = _persist({nonnative_flag_key("welcome_chatter_for_info"): True})
    assert persisted[nonnative_flag_key("welcome_chatter_for_info")] is True, persisted
    # ...but an ABSENT key is NOT materialized (the bug): it stays out of the stored
    # dict so it keeps resolving to the tri-state default at load time.
    assert nonnative_flag_key("autoreply") not in persisted, persisted
    assert "autoreply" not in persisted, persisted

    # The rendered view is default-aware: the saved flag reads back, the absent
    # ones resolve to their default.
    saved = _persist({nonnative_flag_key("welcome_chatter_for_info"): True})
    view = _resolved_view(saved)
    assert view[nonnative_flag_key("welcome_chatter_for_info")] is True, view
    assert view["autoreply"] is True and view[typo_flag_key("autoreply")] is True \
        and view[nonnative_flag_key("autoreply")] is True, view


def case_dict_entries_are_lowercase_keys():
    """Sanity: dict keys are lowercase (we match on core.lower()) and outputs cover
    both single words and phrases."""
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
