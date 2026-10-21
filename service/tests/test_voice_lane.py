#!/usr/bin/env python3
"""test_voice_lane.py — the male voice lane, and the promise it rests on.

THE POINT OF THIS FILE is the first four cases: with no `voice` set, every string
the lane touches renders BYTE-IDENTICALLY to what shipped before `_voice` existed.
Seventeen live accounts run the female lane and earn money on these exact prompts;
"the new branch is opt-in" is a claim about code that has to be asserted, not read.
Everything after those four cases checks that the male branch actually differs.

The byte-identical cases come in two shapes, and BOTH are needed:

  • RENDER-TWICE — run the same builder with the lane absent, then explicitly at
    the default, and compare. Cheap, cannot rot, needs no maintenance. But it only
    proves NULL/""/'her' agree with EACH OTHER. It says nothing about agreeing
    with `main`, because it compares the branch with itself.
  • THE GOLDEN (`_golden()` / fixtures/female_lane_golden.json) — the three
    constants as literal-eval'd from the pre-branch source. This is the only
    EXTERNAL anchor in the file. Without it, editing `_PAINFUL_FRAME[VOICE_HER]`
    changes what 17 live accounts send and the suite stays fully green.

The first shape was written alone. Three separate reviewers independently
identified the resulting tautology (`_common.PAINFUL_TEXTING` IS
`_voice.HER.painful_texting`, so asserting they are equal cannot fail), which is
why the golden exists and why the degrade-to-her case is anchored to it too.

Run:  ./venv/bin/python service/tests/test_voice_lane.py
"""
import _harness  # noqa: F401 — MUST be first

_harness.bootstrap()

import json  # noqa: E402

from automations import _common, _voice, autoreply  # noqa: E402
from automations._outbound import finalize_draft  # noqa: E402
from automations._persona import compose_persona  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, Fan  # noqa: E402


class _Cfg:
    """A stand-in for the AccountAiConfig row compose_persona reads off."""

    def __init__(self, **kw):
        self.persona = kw.get("persona")
        self.location = kw.get("location")
        self.persona_facts_json = kw.get("persona_facts_json")
        self.voice = kw.get("voice")


# Every gendered slot populated, so the labels under test actually render.
_FACTS = json.dumps({
    "age": "31", "kinks": "loves eye contact", "limits": "no live calls",
    "job": "coach", "kids": "none",
})


def _fan(fan_id: int = 1, **kw) -> Fan:
    f = Fan(account_id="a", fan_id=fan_id, of_display_name="Bob")
    f.his_age = kw.get("his_age", "29")
    f.home_city = kw.get("home_city", "Leeds")
    f.occupation = kw.get("occupation", "welder")
    f.likes_boobs = kw.get("likes_boobs", True)
    f.likes_ass = kw.get("likes_ass", False)
    return f


def _autoreply_prompt(voice, **kw) -> str:
    """BOTH messages joined — the fan-facts block lives in the user turn, and a
    byte-identical claim that only covered the system turn would miss it."""
    msgs = autoreply._build_messages(
        "persona", _fan(**kw), [("in", "hey you about?")],
        "answer his last message directly, then a light tease.",
        style_on=True, painful_on=True, v=_voice.blocks(voice),
    )
    return "\n\n".join(m["content"] for m in msgs)


# ── The promise: no voice set ⇒ nothing moves ────────────────────────

def _golden() -> dict:
    """The three constants as they existed on `main`, extracted from the pre-branch
    source by literal-eval. The ONLY external anchor in this file — every other
    "unchanged" assertion here compares the branch with itself, which is fine for
    proving NULL/""/'her' agree but proves nothing about agreeing with `main`."""
    import pathlib
    return json.loads(
        (pathlib.Path(__file__).parent / "fixtures" / "female_lane_golden.json").read_text())


def case_persona_canon_unchanged_by_default():
    """compose_persona renders identically with the column absent, NULL, and 'her'."""
    absent = compose_persona(_Cfg(persona="p", persona_facts_json=_FACTS),
                             fallback="fb")
    null = compose_persona(_Cfg(persona="p", persona_facts_json=_FACTS, voice=None),
                           fallback="fb")
    her = compose_persona(_Cfg(persona="p", persona_facts_json=_FACTS, voice="her"),
                          fallback="fb")
    assert absent == null == her, "default persona canon moved"
    # And the female labels are still exactly what they were.
    assert "What she's into: loves eye contact" in her
    assert "What she won't do: no live calls" in her


def case_autoreply_prompt_unchanged_by_default():
    """The whole Auto Convo system prompt, rendered three ways, is one string."""
    assert _autoreply_prompt(None) == _autoreply_prompt("her") == _autoreply_prompt("")
    # The female-lane fan fact is still there — this is the line the male lane drops,
    # so if it ever vanishes by default the drop leaked into the wrong branch.
    assert "- likes: boobs" in _autoreply_prompt(None)


def case_chat_builder_prompts_unchanged_by_default():
    """The other chat builder, rendered three ways, is one string.

    `welcome_chatter_for_info` opens its style block with "a real 22yo girl",
    which the lane now supplies as `v.texter_noun`. Splitting a word out of an
    f-string is exactly the kind of edit that silently gains or loses a space,
    and this prompt is what live accounts send. Assert it rather than read it —
    the same discipline `case_autoreply_prompt_unchanged_by_default` applies to
    the other builder.

    The builder rolls dice on the GLOBAL rng — the ask/breather choice and the
    style variant — so each render is re-seeded first. Without that the three
    renders differ for a reason that has nothing to do with the lane, which is
    what this case caught on its first run."""
    import random
    from automations import welcome_chatter_for_info

    def _of(voice):
        random.seed(7)
        c = welcome_chatter_for_info._Candidate(1)
        c.last_body, c.messages = "hey", [("in", "hey")]
        return welcome_chatter_for_info._build_messages(
            "persona", _fan(), c, set(), v=_voice.blocks(voice))[0][0]["content"]

    for name, render in (("welcome_chatter_for_info", _of),):
        assert render(None) == render("her") == render(""), f"{name} default moved"
        # the exact pre-lane wording, spaces and comma included
        assert "yo girl, not an assistant)" in render(None), f"{name} style header drifted"
        assert "yo guy, not an assistant)" in render("him"), f"{name} male header wrong"


def case_female_lane_matches_the_pre_branch_golden():
    """THE ONLY ASSERTION IN THIS FILE WITH REAL TEETH — and it was missing.

    Every other byte-identical case here compares the new code with ITSELF:
    `_common.PAINFUL_TEXTING` IS `_voice.HER.painful_texting` (_common.py:546), so
    asserting they are equal is a tautology that cannot fail. Two independent
    reviewers caught it. Edit `_PAINFUL_FRAME[VOICE_HER]` and all 17 live accounts
    get a new prompt with a fully green suite.

    `fixtures/female_lane_golden.json` holds the three constants as they existed on
    `main` before this lane, extracted by literal-eval from the pre-branch source.
    A golden was rejected during design as something that "rots on every legitimate
    copy edit" — true of a whole-prompt snapshot, wrong for these three. They are
    precisely the strings that must not move, so a legitimate edit SHOULD have to
    consciously regenerate this file rather than sail through unnoticed."""
    golden = _golden()
    her = _voice.blocks(None)
    assert her.painful_texting == golden["PAINFUL_TEXTING"], "PAINFUL_TEXTING drifted from main"
    assert her.live_proof == golden["LIVE_PROOF_GUARDRAIL"], "LIVE_PROOF_GUARDRAIL drifted from main"
    assert list(her.off_deflections) == golden["_OFF_DEFLECTIONS"], "_OFF_DEFLECTIONS drifted from main"
    # …and the re-exports the other six modules read are the same objects.
    assert _common.PAINFUL_TEXTING == golden["PAINFUL_TEXTING"]
    assert _common.LIVE_PROOF_GUARDRAIL == golden["LIVE_PROOF_GUARDRAIL"]
    assert list(_common._OFF_DEFLECTIONS) == golden["_OFF_DEFLECTIONS"]


def case_shared_blocks_unchanged_by_default():
    """Anything that is not literally 'him' resolves to the female blocks — and
    those blocks are the PRE-BRANCH ones.

    This compared against `_common.PAINFUL_TEXTING` until an external reviewer
    pointed out that `_common.PAINFUL_TEXTING` IS `_voice.HER.painful_texting`, so
    the loop asserted the new code against itself and could not fail. Anchored to
    the golden instead, it now says something: a corrupt `voice` column degrades to
    the exact text `main` shipped, not merely to whatever the female branch happens
    to hold today."""
    golden = _golden()
    for v in (None, "her", "", "HER", "nonsense", 7, [], {"a": 1}):
        b = _voice.blocks(v)
        assert b.painful_texting == golden["PAINFUL_TEXTING"], v
        assert b.live_proof == golden["LIVE_PROOF_GUARDRAIL"], v
        assert list(b.off_deflections) == golden["_OFF_DEFLECTIONS"], v
        assert not b.is_male, v
        assert b.texter_noun == "girl", v


def case_garbage_voice_degrades_to_her():
    """The failure direction is load-bearing: a corrupt column stays a girl."""
    assert _voice.norm_voice("xyz") == _voice.VOICE_HER
    assert _voice.norm_voice(None) == _voice.VOICE_HER
    assert _voice.norm_voice(["him"]) == _voice.VOICE_HER   # non-str, not truthy-cast
    assert _voice.norm_voice("  HIM  ") == _voice.VOICE_HIM  # trimmed + folded


# ── The male branch actually differs ─────────────────────────────────

def case_persona_canon_male_labels():
    him = compose_persona(_Cfg(persona="p", persona_facts_json=_FACTS, voice="him"),
                          fallback="fb")
    assert "What he's into: loves eye contact" in him
    assert "What he won't do: no live calls" in him
    for dead in ("What she's into", "What she won't do"):
        assert dead not in him, f"female label survived: {dead}"
    # Neutral labels are untouched — the lane re-labels two slots, not the slate.
    assert "Work: coach" in him and "Kids: none" in him


def case_autoreply_male_prompt():
    him = _autoreply_prompt("him")
    # The boobs/ass fact is the one that asserts a body the creator does not have.
    assert "- likes: boobs" not in him and "- likes: ass" not in him
    # …while every other fan fact survives: the fan is male in BOTH lanes.
    assert "- age: 29" in him and "- city: Leeds" in him and "- job: welder" in him
    assert "his last message" in him, "fan-side pronouns must not flip"
    # The two creator-voiced blocks re-voiced rather than switched off, so the male
    # lane keeps the brevity governor and the live-proof refusal.
    assert "like a real girl half-glued to her phone" not in him
    assert "you write the LEAST you can" in him, "brevity governor lost"
    assert "i don't do facetime babe" not in him
    assert "LIVE PROOF / FACETIME (hard rule)" in him, "live-proof rule lost"


def case_ass_fallback_also_dropped_for_male():
    """likes_ass is the other branch of the same tuple — both go, or neither."""
    her = _autoreply_prompt("her", likes_boobs=False, likes_ass=True)
    him = _autoreply_prompt("him", likes_boobs=False, likes_ass=True)
    assert "- likes: ass" in her
    assert "- likes: ass" not in him


def case_offplatform_deflection_is_male_voiced():
    """The one canned line that reaches a fan with the model cut out of the loop."""
    leaky = "heres my number 07700900123 text me"
    rng_seed = 4
    import random
    her, why_h = _common.guard_offplatform(
        leaky, random.Random(rng_seed), _voice.blocks("her"))
    him, why_m = _common.guard_offplatform(
        leaky, random.Random(rng_seed), _voice.blocks("him"))
    assert why_h and why_m, "the leak must still be caught in both lanes"
    assert her in _voice.OFF_DEFLECTIONS["her"]
    assert him in _voice.OFF_DEFLECTIONS["him"]
    assert "babe" not in him and "😏" not in him and "😉" not in him
    # Clean text passes through untouched in both lanes.
    for v in ("her", "him"):
        out, why = _common.guard_offplatform(
            "just chatting", random.Random(1), _voice.blocks(v))
        assert out == "just chatting" and why == []


async def case_finalize_draft_threads_voice():
    """The lane has to survive the shared send chokepoint, not just the builder."""
    leaky = "add me on snapchat @bob"
    her, _ = await finalize_draft(
        leaky, account_id="a", fan_id=1, purpose="autoreply",
        v=_voice.blocks("her"))
    him, _ = await finalize_draft(
        leaky, account_id="a", fan_id=1, purpose="autoreply",
        v=_voice.blocks("him"))
    assert her in _voice.OFF_DEFLECTIONS["her"]
    assert him in _voice.OFF_DEFLECTIONS["him"]
    # No voice argument at all = today's behaviour, which is what every other
    # engine still calls with.
    bare, _ = await finalize_draft(leaky, account_id="a", fan_id=1, purpose="autoreply")
    assert bare in _voice.OFF_DEFLECTIONS["her"]


def case_both_lanes_stay_structurally_parallel():
    """The two lanes are built from the same template, so they cannot drift in
    SHAPE — only in the spans that carry a voice. Assert the invariants that a
    future third lane would be most likely to break."""
    her, him = _voice.blocks("her"), _voice.blocks("him")
    assert len(her.off_deflections) == len(him.off_deflections)
    # The rule survives in both; only the worked examples differ.
    for b in (her, him):
        assert b.live_proof.startswith("LIVE PROOF / FACETIME (hard rule):")
        assert "you write the LEAST you can" in b.painful_texting
        assert b.painful_texting.startswith("THE FEEL OF TEXTING")
    assert her.painful_texting != him.painful_texting
    assert her.live_proof != him.live_proof


def case_every_gendered_label_has_a_male_form():
    """A REGRESSION NET, not a spot check. The first cut of the male lane re-labelled
    three slots and missed `kinks`/`limits` — the two operator-only fields, last in
    the slate, which the Enrich pass never touches so nobody reads them. Rather than
    add two more hand-written asserts, scan the whole slate: any label containing
    she/her MUST have a male override. A sixth gendered slot added later fails here
    on the day it lands."""
    import re
    from automations._persona import PERSONA_FACT_FIELDS
    overrides = _voice.fact_labels("him")
    female = re.compile(r"\b(she|her|hers)\b", re.I)
    missing = [k for k, label in PERSONA_FACT_FIELDS
               if female.search(label) and k not in overrides]
    assert not missing, f"gendered labels with no male form: {missing}"
    # …and no override is itself still female.
    still_female = [k for k, v in overrides.items() if female.search(v)]
    assert not still_female, f"male override is still female: {still_female}"


def case_every_canon_slot_has_a_male_placeholder():
    """THE SAME NET, ONE COLUMN OVER — and the column that had no net is the one
    that went wrong.

    The placeholder is the example text under each canon box: the same "what does
    the operator write here" concept as the label beside it. The first cut laned the
    labels and left the placeholders, then patched that by REGEXing hers on the male
    lane and blanking whatever matched a she/her/girl/woman word list. Three holes,
    all of them live, and this case closes each:

      1. WHAT THE LIST DOESN'T KNOW. `job | "content creator, waitressed before"`
         has no banned word and sailed through — 21 of 26 male placeholders were
         her copy verbatim. So the assertion here is not "no female words survived",
         it is KEY PARITY with the declared contract: every canon slot must have a
         male value written for it, whether or not a word list can see anything
         wrong with hers.
      2. OVER-BLANKING. `tattoos` was a gendered example of a field BOTH lanes have.
         A filter's only move is deletion, so the male lane lost the hint entirely.
         An empty male placeholder under a filled female one fails here.
      3. THE FILTER COULD NEVER FAIL. Its word list carried no masculine terms, so a
         male table growing "his ex, they were together 3 years" would never have
         tripped anything. The scan below runs on the MALE values."""
    import re
    from automations._persona import PERSONA_FACT_FIELDS
    him, her = _voice.fact_placeholders("him"), _voice.fact_placeholders("her")
    declared = {k for k, _ in PERSONA_FACT_FIELDS}

    # 1. COVERAGE, both lanes — and it is not this test that enforces it.
    #    `assert_canon_parity` runs at `_persona` IMPORT, so a canon slot with no
    #    male value cannot boot the relay; a test only fails for whoever runs it.
    #    What this asserts is that the binding is real: call it with a slate the
    #    tables do not cover and it must raise.
    assert set(him) == declared and set(her) == declared
    try:
        _voice.assert_canon_parity(PERSONA_FACT_FIELDS + (("hobbies", "Her hobbies"),))
    except AssertionError:
        pass
    else:                       # pragma: no cover - the guard is the point
        raise AssertionError("a new canon slot with no male form did not fail parity")
    # …and the LABEL half of the same binding: a gendered new label with no male
    # form is the original bug, and the scan is adequate there because a label
    # NAMES a field in three words. (It is not adequate for a placeholder, which
    # is why that column is checked for coverage instead — "content creator,
    # waitressed before" carries no word any list would hold.)
    # `age` is re-declared rather than a new key, so the placeholder tables still
    # cover the slate exactly and it is the LABEL arm that has to catch this.
    try:
        _voice.assert_canon_parity(PERSONA_FACT_FIELDS + (("age", "Her age"),))
    except AssertionError:
        pass
    else:                       # pragma: no cover
        raise AssertionError("a gendered label with no male override did not fail parity")

    # 2. Blank is not an answer where hers has one. That was the regex filter's
    #    failure mode — it could only DELETE, so `tattoos` lost its hint entirely.
    blanked = [k for k in declared if her[k] and not him[k]]
    assert not blanked, f"male placeholder blank where hers is filled: {blanked}"

    # 3. …and no male value reads as a woman.
    female = re.compile(r"\b(she|her|hers|herself|girl|girls|woman|women)\b", re.I)
    still_female = [(k, v) for k, v in him.items() if female.search(v)]
    assert not still_female, f"male placeholder is still female: {still_female}"

    # 3b. COVERAGE IS NOT CONTENT, and the gap between them is where this lands.
    #     Parity plus a word scan is satisfied by copy-pasting HER table and
    #     editing only the five values that happen to carry a banned word —
    #     measured: 21 of 26 identical, every case green. That is the shipped bug
    #     with a table around it. So the ones that must DIFFER are enumerated by
    #     what they are, and the ones that legitimately coincide are named here.
    #     A new slot lands in neither set and fails until someone decides which.
    SHARED = {                  # no creator gender in the value, either lane
        "relationship", "kids", "family",
        "kinks", "limits",      # not examples — the same operator instruction
    }
    copied = [k for k in declared - SHARED if him[k] == her[k]]
    assert not copied, f"male placeholder is her copy verbatim: {copied}"
    assert SHARED <= declared, f"SHARED names an undeclared slot: {sorted(SHARED - declared)}"
    assert all(him[k] == her[k] for k in SHARED), \
        f"a SHARED slot diverged — decide which set it is in: " \
        f"{sorted(k for k in SHARED if him[k] != her[k])}"

    # 4. HER LANE IS BYTE-IDENTICAL to the table that shipped before the male lane
    #    existed (for the slots that survived the 2026-08-15 slate cut) — moving
    #    a column between modules must not edit it.
    assert her["job"] == "content creator, waitressed before"
    assert her["tattoos"] == "script on her ribs, small rose on left wrist"
    assert her["kinks"] == "you fill this in — Enrich never guesses"
    assert _voice.fact_placeholders(None) == her        # NULL column → shipped lane
    assert _voice.fact_placeholders("hom") == her       # a typo cannot flip a lane
    # A COPY, like fact_labels — the module's own dict must not escape.
    esc = _voice.fact_placeholders("him")
    esc["age"] = "999"
    assert _voice.fact_placeholders("him")["age"] != "999"


def case_humanizer_is_laned_and_her_half_is_the_golden():
    """The humanizer is opt-in and mostly neutral — lowercase, no em-dash, dont
    echo him, vary the length. TWO spans are not:

      • "tease, be a lil BRATTY" is a submissive-playful register. It is the one
        line that tells the model what ATTITUDE to hold, so on a dom it inverts
        the exact axis the lane exists to establish.
      • the block names an emoji BUDGET (0-1) and no VOCABULARY, so the model
        reaches for what it associates with an OF creator — the female sexting
        set. Naming the set is the fix; the budget was never the problem."""
    golden = _golden()
    her, him = _voice.blocks("her"), _voice.blocks("him")
    assert her.humanizer == golden["STYLE_HUMANIZER"], "female humanizer drifted from main"
    assert _common.STYLE_HUMANIZER == golden["STYLE_HUMANIZER"], "the re-export drifted"

    assert "bratty" in her.humanizer          # hers is untouched
    assert "bratty" not in him.humanizer, "a dom is not bratty"
    assert "NEVER seeking his approval" in him.humanizer

    # the male emoji vocabulary exists, and bans the female set by name
    assert "😏" in him.humanizer and "😈" in him.humanizer
    for banned in ("🥺", "🥰", "😘", "💦", "🥵"):
        assert banned in him.humanizer, f"{banned} must be named as forbidden"
    assert "🥺" not in her.humanizer, "the female block names no emoji set"
    # the shared budget survives in BOTH
    for b in (her, him):
        assert "0-1 emoji, never the same emoji twice" in b.humanizer


def case_send_followup_refusal_and_address_are_laned():
    """send_followup was the only automation ENABLED on the live male account and
    the only engine still rendering the female refusal — "i don't do facetime
    babe" / "no live calls hun" — from a man. Its unresolved-name fallback called
    the FAN "babe" too, which is the same tell from the other direction."""
    from automations import send_followup
    common = dict(tod="evening", activity="", clock="", fan_name="", fan_bio="")

    her_sys = send_followup._compose_system({"persona": "p"}, **common)
    him_sys = send_followup._compose_system(
        {"persona": "p", "_voice": _voice.blocks("him")}, **common)

    # absent bundle → the female lane, byte-for-byte what this engine always sent
    assert _golden()["LIVE_PROOF_GUARDRAIL"] in her_sys
    assert "facetime babe" in her_sys
    assert "facetime babe" not in him_sys, "the male lane still refuses like a woman"
    assert "you get me right here or not at all" in him_sys

    # …and the fan-address fallback
    assert "babe" in send_followup._compose_user(1, "", 5.0)          # default = hers
    assert "babe" not in send_followup._compose_user(1, "", 5.0, "man")


# Every emoji hers uses freely that HIS OWN prompt rule forbids. Kept here rather
# than imported from `_voice._EMOJI_VOCAB` on purpose: parsing the ban out of the
# prompt string would make this test agree with the rule by construction, and the
# bug being guarded is precisely the two disagreeing.
_BANNED_FOR_HIM = "🥺🥰😘💕💦🥵😍🙈✨💅💋😻🤭🤍🌟"


def case_engines_without_a_humanizer_still_get_the_emoji_rule():
    """Found by trying to turn `strip_emojis` OFF on a live male account.

    The emoji vocabulary rides inside the HUMANIZER, which is an opt-in style block.
    `send_followup` does not carry the humanizer — its prompt asks for "real emojis"
    and then names none — so the model chose, and a model writing a flirty DM
    chooses 😘🥰🥺. On the male accounts the only thing suppressing that was
    `strip_emojis: true`, an account-wide switch that removes ALL emoji including
    the dry ones he SHOULD send. So "let his emoji through" would have released the
    female set, not his: the switch was load-bearing for the wrong reason.

    Hers is "" by construction, which is what makes this safe to bolt onto any
    engine — the female prompt cannot change."""
    from automations import _voice
    from automations import send_followup as SF

    def rendered(voice):
        return SF._compose_system(
            {"_voice": _voice.blocks(voice), "persona": "P"},
            "evening", "somewhere", "8:14pm", "Mike", "")

    her, him = rendered(_voice.VOICE_HER), rendered(_voice.VOICE_HIM)
    assert _voice.blocks(_voice.VOICE_HER).emoji_vocab == "", "hers must stay empty"
    assert "EMOJI (hard rule)" not in her, "the female prompt changed"
    assert "EMOJI (hard rule)" in him, "his prompt has no emoji guidance"
    for allowed in "😏😈🔥💪🖤🐺":
        assert allowed in him, allowed
    for banned in "🥺🥰😘💕😍🙈":
        assert banned in him, f"{banned} must be named to be banned"

    # The rule has to survive the join, not sit in an unused constant.
    assert him.endswith(_voice.blocks(_voice.VOICE_HIM).emoji_vocab)


def case_emoji_rule_does_not_depend_on_the_human_style_checkbox():
    """The second half of the same bug, on the engines that DO carry a humanizer.

    `autoreply` and `welcome_chatter_for_info` both wrote
    `v.humanizer if style_on else ""` — so the emoji vocabulary, which lives inside
    the humanizer, was gated on a per-automation "human style" checkbox that has
    nothing to do with who the creator is. Blake2 runs `autoreply` with
    `autoreply: false` in style_config, so the live male account had NO emoji
    guidance on the one engine actually cycling, and the prompt still asks for
    emoji. Turning `strip_emojis` off would have released the female set.

    The vocabulary is a LANE fact; the humanizer is a STYLE preference. This asserts
    every prompt builder carries the former regardless of the latter — with her at
    "" so the female prompt is untouched in both branches."""
    from automations import _voice
    him = _voice.blocks(_voice.VOICE_HIM)
    her = _voice.blocks(_voice.VOICE_HER)
    assert her.emoji_vocab == "", "her lane must stay a no-op"
    assert "😏" in him.emoji_vocab and "🥺" in him.emoji_vocab

    import inspect
    from automations import autoreply, welcome_chatter_for_info, send_followup
    for mod in (autoreply, welcome_chatter_for_info, send_followup):
        src = inspect.getsource(mod)
        assert "emoji_vocab" in src, (
            f"{mod.__name__} builds a prompt with no emoji vocabulary — a male "
            f"account there defaults to the female set")
        # ...and it must not be re-gated on style_on, which is the bug itself.
        assert 'if style_on else ""' not in src, (
            f"{mod.__name__} still drops the vocabulary when human-style is off")


def case_prompt_builders_never_assert_a_female_creator():
    """A different failure class from the canned pools: prompts that INSTRUCT the
    model on register ("be a woman", "do girl things") beat any persona box that
    sits above them — a model handed prose context and a rule takes the rule.

    `send_welcome`'s `_ADJS` is the subtle one. It describes the FAN, who is male
    in both lanes, so it looks out of scope — but "Yummy Mike" is what SHE calls
    him, and it is the FIRST thing a new subscriber ever reads. Register, not
    pronouns.

    Every female render is asserted unchanged, since all of these ship today."""
    from automations import _voice, send_welcome
    from db.models import Fan

    f = Fan(account_id="a", fan_id=1, of_display_name="Mike")

    # ── send_welcome: the alliterative adjective + the nameless fallback
    assert send_welcome._local_greeting("Cody") == "Hey C-C-C-Cute Cody ! !!"
    assert send_welcome._local_greeting("Cody", "him") == "Hey C-C-C-Cocky Cody ! !!"
    for letter in ("C", "J", "Y"):          # Cute / Juicy / Yummy are hers alone
        assert send_welcome._ADJS[letter] != send_welcome._ADJS_HIM[letter], letter
    assert set(send_welcome._ADJS) == set(send_welcome._ADJS_HIM), "a letter has no male form"
    assert send_welcome._greet_token({"name": "xx_99"}) == "cutie"
    assert send_welcome._greet_token({"name": "xx_99"}, "him") == "boy"


def case_canned_surfaces_are_laned():
    """The model-free surfaces, where no prompt rule can reach the text.

    There are five now, and each was found the same way — by asking "what does this
    account SEND that no model wrote?". `OFF_DEFLECTIONS` was first; these four came
    after, and every one of them fires on a load-bearing beat:

      unlock_reactions  — the instant money lands, the highest-emotion beat there is
      nudge_lines       — an unsolicited re-engage, the only message he sends cold
      unlock_prompt     — the escalation ask itself, when the pack has no rung
      aftercare         — the beat right after a sale

    Disjointness is the assertion that matters. Equal LENGTH is asserted too: every
    caller picks with `random.choice`, so a shorter male pool would silently change
    the repeat rate rather than fail."""
    import dataclasses
    from automations import _voice
    her, him = _voice.blocks(_voice.VOICE_HER), _voice.blocks(_voice.VOICE_HIM)

    # THE FIELD LIST IS DERIVED. It was six of sixteen names typed out, which is
    # the defect `sellerCopyLane.test.tsx` spends its header on: a seventeenth
    # voice-varying block joins the bundle and joins no case. Every field is swept
    # by TYPE — tuple pools get length + disjointness, strings must simply differ —
    # so covering a new block is the default and NOT covering one is the thing you
    # have to go out of your way to do (`SAME` below, with a reason).
    SAME = {
        "voice",            # the lane id itself
        # "" for her by construction: the shipped humanizer names no emoji set, so
        # every prompt that appends this is byte-identical in the female lane.
        "emoji_vocab",
        "is_male",          # a bool derived from `voice`, not a prompt block
    }

    def _named_blocks(cls):
        """Every named value on the bundle — FIELDS **and** PROPERTIES.

        `dataclasses.fields()` alone stopped being the whole bundle the moment a
        block became derived; sweeping both is what keeps "covered by default"
        true regardless of how the next block is spelled."""
        names = [f.name for f in dataclasses.fields(cls)]
        names += [n for n, v in vars(cls).items() if isinstance(v, property)]
        return sorted(set(names))

    swept = _named_blocks(_voice.VoiceBlocks)
    assert "is_male" in swept, "the property sweep stopped seeing properties"
    for name in swept:
        a, b = getattr(her, name), getattr(him, name)
        if name in SAME:
            continue
        if isinstance(a, tuple):
            assert len(a) == len(b), f"{name}: pools must be equal length, {len(a)}/{len(b)}"
            assert not (set(a) & set(b)), f"{name}: a line is shared between lanes"
        else:
            assert a != b, f"{name}: identical in both lanes — lane it, or name it in SAME"
    assert SAME <= set(swept), "SAME names a value the bundle does not have"
    # …and the one deliberate "" is still ""; otherwise SAME hides a real miss.
    assert her.emoji_vocab == "" and him.emoji_vocab != ""

    # Hers is the shipped text, unchanged — the whole guarantee of this branch.
    assert her.unlock_reactions[0] == "omg enjoy babe 😘"
    assert her.unlock_prompt == "unlock this babe 😏"
    assert her.aftercare == "mmm come here babe"
    assert her.nudge_lines[0] == "hey {name} u still there ? 🙈"
    assert "legs spread" in her.sell_caption_example

    # His nudges keep the {name} token — they are templated, not literal.
    assert all("{name}" in line for line in him.nudge_lines)
    # ...and none of them MISS the fan. Hers pull by needing him; a dom does not.
    assert not any(w in " ".join(him.nudge_lines).lower()
                   for w in ("i miss", "missing u", "dont leave me like this"))


def case_his_canned_text_obeys_his_own_emoji_rule():
    """The sharpest form of the drift this module exists to stop.

    `_EMOJI_VOCAB` tells a male account, in the prompt, never to type 🥺 or 🙈. Then
    `_NUDGE_LINES` typed 🙈 or 🥺 for him — unprompted, into an unsolicited message —
    six times across fifteen lines, because canned text never passes a model and so
    never meets the rule. The prompt and the code disagreed, and the code wins on
    every surface listed here."""
    from automations import _voice
    him = _voice.blocks(_voice.VOICE_HIM)

    surfaces = {
        "nudge_lines": list(him.nudge_lines),
        "unlock_reactions": list(him.unlock_reactions),
        "fallbacks": [him.unlock_prompt, him.aftercare],
    }
    for name, lines in surfaces.items():
        for line in lines:
            hit = [c for c in _BANNED_FOR_HIM if c in line]
            assert not hit, f"{name}: {hit} is banned for him — {line[:60]!r}"
        assert "babe" not in " ".join(lines).lower(), f"{name}: still says babe"

    # And hers still DOES use them — otherwise this test passes by her pools being
    # emptied rather than his being written.
    her_lines = " ".join(_voice.blocks(_voice.VOICE_HER).nudge_lines)
    assert any(c in her_lines for c in _BANNED_FOR_HIM), "her pool lost its emoji"


def case_sticker_pack_is_laned():
    """The TAGS carry a register: shy / pout / beg / miss_you are submissive-
    appealing and kiss / love / dance / celebrate / excited are eager-affectionate,
    which is exactly what the male lane exists to invert. And the block's own
    framing said the pack is "the kind real girls spam in texts", i.e. it told a dom
    to text like a girl in the same prompt that had just told him not to."""
    import re
    from automations import cat_stickers
    her = cat_stickers.prompt_block("allow")
    him = cat_stickers.prompt_block("allow", "him")

    assert "the kind real girls spam in texts" in her      # hers is untouched
    assert "real girls spam" not in him, "a dom was told to text like a girl"
    # The pack's own NOUN is a fact about the pictures, not a style knob: his gifs
    # are dogs and wolves, and a prompt that calls them cats is one the model can
    # narrate wrong in the one leak class no regex catches.
    assert "cat reaction gifs" in her
    assert " cat " not in him and "CAT STICKERS" not in him, "his pack isn't cats"
    assert "dog & wolf reaction gifs" in him

    her_tags = set(re.findall(r"^- ([a-z_]+):", her, re.M))
    him_tags = set(re.findall(r"^- ([a-z_]+):", him, re.M))
    assert her_tags == set(cat_stickers._CATALOG), her_tags
    assert him_tags < her_tags, "the male list must be a strict subset"
    # ⚠️ DERIVED FROM THE CATALOG, not from a hand-typed list. The 2026-08-15 trim
    # removed `pout`, `beg`, `grumpy` and `thumbs_up` outright, and a literal list
    # then fails for the one reason that is not a bug — the tag is simply gone. The
    # guarantee is about the SPLIT: every submissive tag that still exists is hers
    # alone, and his half is exactly the remainder.
    submissive = cat_stickers._TAGS_NOT_FOR_HIM & her_tags
    assert submissive, "the female-only set is empty — the split stopped meaning anything"
    for tag in submissive:
        assert tag not in him_tags, f"male lane can still send {tag}"
    assert him_tags == her_tags - cat_stickers._TAGS_NOT_FOR_HIM, him_tags
    # anything not "him" resolves to the full female pack
    for v in (None, "", "her", "HER", "nonsense"):
        assert cat_stickers.prompt_block("allow", v) == her, v


def case_male_pack_has_its_own_gifs():
    """Restricting the tag list was the cheap half. The gifs themselves are cats,
    and a kitten sent from a 38-year-old combat-sports coach is the same failure as
    the "real girls spam" framing — just in a picture instead of a sentence.

    The invariants that matter after a re-curation:

      * every tag the male prompt OFFERS has gifs behind it, or the model emits a
        marker and `pick_gif` silently returns None — a dropped reaction, not a
        text reply, because the sticker was meant to BE the reply;
      * no banned tag sneaks back in via the catalog rather than the frozenset;
      * the two packs share no gif id — an overlap means a cat leaked into his
        pack (or a dog into hers), which is the whole point of separating them;
      * `pick_gif` does NOT fall back to her pool for a tag he lacks. A tag he was
        never offered can still arrive (the model invents one, or an old marker
        survives a config flip) and None is the correct answer there."""
    import random
    from automations import cat_stickers as cs

    him_tags = set(cs._CATALOG_HIM)
    assert him_tags == set(cs._CATALOG) - cs._TAGS_NOT_FOR_HIM, him_tags
    assert not (him_tags & cs._TAGS_NOT_FOR_HIM), "a banned tag came back"

    hers = {g for _, gifs in cs._CATALOG.values() for g in gifs}
    his = {g for gifs in cs._CATALOG_HIM.values() for g in gifs}
    assert not (hers & his), f"packs share gifs: {hers & his}"
    assert len(his) == sum(len(g) for g in cs._CATALOG_HIM.values()), "dupe gif id"
    for tag, gifs in cs._CATALOG_HIM.items():
        assert len(gifs) >= 2, f"{tag} has {len(gifs)} — 2 is the floor"

    rng = random.Random(3)
    for tag in him_tags:
        assert cs.pick_gif(tag, rng, "acc_m", 1, voice="him") in his
        assert cs.pick_gif(tag, rng, "acc_f", 1) in hers          # her default
    # ∩ the catalog: `_TAGS_NOT_FOR_HIM` deliberately outlives the tags it names
    # (the 2026-08-15 trim dropped `beg`, `pout`, `dance`, `excited`), and a tag
    # that no longer exists has no gif to return on EITHER lane.
    for banned in cs._TAGS_NOT_FOR_HIM:
        assert cs.pick_gif(banned, rng, "acc_m", 2, voice="him") is None, banned
    for banned in cs._TAGS_NOT_FOR_HIM & set(cs._CATALOG):
        assert cs.pick_gif(banned, rng, "acc_f", 2) is not None, banned


def case_no_production_sender_forgets_the_lane():
    """A lane parameter WITH A DEFAULT lets a call site forget it and silently render
    the shipped (female) lane. That default is not wrong on its own — ~50 tests rely
    on it to pin the female golden — but a PRODUCTION call relying on it is exactly
    how the since-deleted `scripts_api.simulate` previewed a male account as a woman and how
    a since-retired engine ran the whole-draft guards in the wrong lane.

    Python cannot make it required without breaking every one of those tests, so the
    invariant is asserted where it holds: every call in the shipping modules passes it.

    WHAT COUNTS IS DERIVED FROM THE SIGNATURE, NOT FROM A SPELLING. The first version
    matched a default spelled `_voice.HER`/`VOICE_HER` and so covered 16 of the 27
    functions that have one — the eleven defaulting to the bare string `"her"`
    (`send_welcome._greet_token`, `cat_stickers.pick_gif`,
    …) were invisible, and they are canned-text paths.
    A parameter named `v`/`voice` with ANY default is in scope: whatever the default
    is, a caller that omits it did not choose a lane."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    # Only SHIPPING code. Tests pass the default on purpose, and `_drive_*`/`_verify_*`
    # fire live OF calls on import — they are never imported, only read as text.
    files = [p for p in sorted(root.rglob("*.py"))
             if "tests" not in p.parts and not p.name.startswith(("_drive_", "_verify_"))]
    assert len(files) > 20, f"glob found only {len(files)} modules — path wrong?"
    trees = {}
    for path in files:
        try:
            trees[path] = ast.parse(path.read_text())
        except SyntaxError:
            continue

    # (module stem, function name) -> `v`'s POSITIONAL index, or None if keyword-only.
    # Keyed by MODULE too: `_build_messages` is defined four times with the lane at
    # four different indices, so a bare-name map would check one engine's call against
    # another engine's signature.
    laned: dict[tuple[str, str], int | None] = {}
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            a = node.args
            for arg, default in zip(a.kwonlyargs, a.kw_defaults):
                if arg.arg in ("v", "voice") and default is not None:
                    laned[(path.stem, node.name)] = None
            pos = a.posonlyargs + a.args
            for i, (arg, default) in enumerate(
                    zip(pos[len(pos) - len(a.defaults):], a.defaults),
                    start=len(pos) - len(a.defaults)):
                if arg.arg in ("v", "voice") and default is not None:
                    laned[(path.stem, node.name)] = i
    names = {n for _, n in laned}
    # Fixture drift: if the signature style changes and this finds nothing, the case
    # silently passes. It found 27 definitions under 25 names when written, 20
    # once the legacy selling engine and its packs were deleted, 19 once its
    # dead helpers were swept, 18 once the nudge info line (`_try_qa`) went, and
    # 16 once the PPV sender and the Vault AI describe automation were deleted,
    # 15 once the `_pins` judge went, and 14 once reengage_buyers went.
    assert len(laned) >= 14, f"only {len(laned)} laned defs found: {sorted(names)}"

    misses = []
    for path, tree in trees.items():
        # WHICH laned names this file can be calling. Matching a bare name across the
        # whole tree made `render` — the commonest verb here — hit eight `_probe_*`
        # report helpers. A call counts only if this file DEFINES the function or
        # IMPORTS it (by name, or as the module it is reached through).
        # `from X import name` must bind to the module X NAMES, not to any module
        # that happens to define something with that name. The first version scanned
        # every `laned` entry for a matching bare name and took its stem, so
        # `from .welcome_chatter_for_info import _build_messages` could be checked against
        # another engine's `_build_messages` signature — several definitions,
        # different positional indices for the lane.
        # Every function this file defines, laned or not. Without it, a module with
        # its own local `render()` (eight `_probe_*` report scripts have one) looks
        # "unresolved" and gets reported — the name is laned SOMEWHERE, but not here.
        local_defs = {n.name for n in ast.walk(tree)
                      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        owners: dict[str, tuple[str, str]] = {}   # local binding -> (stem, defname)
        for stem, name in laned:
            if stem == path.stem:
                owners[name] = (stem, name)
        modules: dict[str, str] = {}         # alias -> module stem (laned modules)
        # EVERY module alias this file binds, laned or not. `mod.fn()` where `mod`
        # is a real import and `mod` defines nothing laned is a DIFFERENT function
        # that happens to share a name — `_quotes.render` vs the laned `render`s.
        # Without this it reported as "unresolved" and the case failed on a call
        # that could not take a lane if it wanted to.
        imported_mods: set[str] = set()
        stems = {stem for stem, _ in laned}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                src = (node.module or "").split(".")[-1]
                for alias in node.names:
                    if (src, alias.name) in laned:
                        owners[alias.asname or alias.name] = (src, alias.name)
                    if alias.name in stems:          # `from . import rhythm`
                        modules[alias.asname or alias.name] = alias.name
                    if not node.module or node.module.startswith("."):
                        imported_mods.add(alias.asname or alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    stem = alias.name.split(".")[-1]
                    binding = (alias.asname or alias.name).split(".")[-1]
                    # A plain `import X` / `import X as y` binds a REAL module, so
                    # `y.fn()` resolves even when X defines nothing laned — the same
                    # escape the relative-import branch above already gets, and the
                    # one this branch forgot. `import assistant_evidence as ev` +
                    # `ev.render()` was reported as a hole against a `render` laned
                    # in a different module entirely. It cannot weaken the guard:
                    # `imported_mods` is only consulted when the call resolved to
                    # NO laned definition, and a laned module still lands in
                    # `modules` below and stays checked.
                    imported_mods.add(binding)
                    if stem in stems:
                        modules[binding] = stem

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            # The key is built from the RESOLVED owner. `owners` maps the local
            # BINDING to the module that defines it, so rebuilding `(stem, spelling)`
            # from the call site re-introduced the bare-name lookup the map exists to
            # replace — an aliased import (`from .x import render as r`) resolved to
            # a stem and then missed, because `(x, "r")` is not a key.
            if isinstance(fn, ast.Attribute):
                holder = fn.value.id if isinstance(fn.value, ast.Name) else None
                stem = modules.get(holder or "")
                key = (stem, fn.attr) if stem else None
                name = fn.attr
            elif isinstance(fn, ast.Name):
                owned = owners.get(fn.id)
                key = owned if owned else None
                name = fn.id
            else:
                continue
            # "could not resolve" and "resolved, not laned" are different answers and
            # were collapsed into one `continue`. Only the second is safe to skip: an
            # unresolved call to a name that IS laned somewhere is a hole, so it is
            # reported rather than assumed innocent.
            if key is None:
                if isinstance(fn, ast.Attribute) and (
                        fn.value.id if isinstance(fn.value, ast.Name) else ""
                ) in imported_mods:
                    continue          # a real module, and it defines nothing laned
                if name not in local_defs and name in {n for _, n in laned}:
                    misses.append(f"{path.relative_to(root)}:{node.lineno} {name}() "
                                  f"(callee unresolved — import it by name or module)")
                continue
            if key not in laned:
                continue
            # PRESENCE is not enough — `v=None` / `voice=None` names the parameter
            # and still hands the callee nothing to lane with. A literal None is the
            # one value that is never a lane.
            if any(k.arg in ("v", "voice")
                   and not (isinstance(k.value, ast.Constant) and k.value.value is None)
                   for k in node.keywords):
                continue
            idx = laned[key]
            if idx is not None and len(node.args) > idx:
                continue                      # supplied positionally
            # `*args` / `**kwargs` forwarding may carry it; that is the wrapper's
            # problem, and a splatted call cannot be read statically.
            if any(k.arg is None for k in node.keywords):
                continue
            if any(isinstance(a, ast.Starred) for a in node.args):
                continue
            misses.append(f"{path.relative_to(root)}:{node.lineno} {name}()")
    assert not misses, ("these production call sites take the SHIPPED lane by "
                        "default:\n  " + "\n  ".join(sorted(misses)))


def case_the_starter_brain_is_laned():
    """"Reset to defaults" is the sharp end of this one. BrainPanel preserves the
    `voice` key across a refill but copies `persona` and the six `time_activities`
    wholesale, so a female default on a male account is one click from a 22-year-old
    woman's identity with the right value still sitting in the voice dropdown — and
    the time lines are read out as the creator's own day by the prompt clock in every
    engine. A male account was seeded exactly this way and ran the
    yoga/beach/cat lines."""
    import re
    import brain_defaults as bd
    from brain_defaults import BRAIN_DEFAULTS_HER, brain_defaults

    # The shipped lane is byte-identical, under both names.
    assert brain_defaults("her") == BRAIN_DEFAULTS_HER
    # No bare alias: one name per value, so nothing can read "the default brain"
    # and silently mean "the female one".
    assert not hasattr(bd, "BRAIN_DEFAULTS"), "the ambiguous alias came back"
    for stored in (None, "", "  ", "her", " HER ", "hom", 7, ["him"]):
        assert brain_defaults(stored) == BRAIN_DEFAULTS_HER, stored
    assert brain_defaults() == BRAIN_DEFAULTS_HER, "the bare call changed lane"

    him = brain_defaults("him")
    # Same CONTRACT — _serialize's shape, and the same six clock slots. A missing
    # slot here is a time of day where the male account has no activity line.
    assert set(him) == set(BRAIN_DEFAULTS_HER), set(him) ^ set(BRAIN_DEFAULTS_HER)
    assert set(him["time_activities"]) == set(BRAIN_DEFAULTS_HER["time_activities"])
    # …but the creator's half really differs (a copy-paste default would pass every
    # assertion above and still be Ava).
    assert him["persona"] != BRAIN_DEFAULTS_HER["persona"]
    assert him["time_activities"] != BRAIN_DEFAULTS_HER["time_activities"]
    female = re.compile(r"\b(she|her|hers|girl|woman)\b", re.I)
    assert not female.search(him["persona"]), him["persona"]
    for slot, line in him["time_activities"].items():
        assert not female.search(line), f"{slot}: {line}"
        assert line.strip(), slot
    # Non-identity fields must NOT drift between lanes — they are not voice-varying,
    # and a second copy is a second thing to keep in sync.
    for k in ("model", "daily_cost_cap_cents", "utc_offset", "timezone",
              "model_by_purpose", "persona_facts", "time_images"):
        assert him[k] == BRAIN_DEFAULTS_HER[k], k

    # A DEEP copy. Reset writes over what it is handed, so a shared literal would let
    # one account's edit change every other account's starter. `time_activities` is
    # the one that matters: it is a NESTED dict and it is NOT empty, so a shallow
    # copy would have passed the top-level check below and still aliased six lines.
    brain_defaults("him")["persona"] = "mutated"
    assert brain_defaults("him")["persona"] != "mutated"
    brain_defaults("him")["time_activities"]["night"] = "mutated"
    assert brain_defaults("him")["time_activities"]["night"] != "mutated"
    brain_defaults("her")["persona_facts"]["leak"] = 1
    assert "leak" not in brain_defaults("her")["persona_facts"]


def case_the_refusal_block_can_never_carry_the_offer():
    """THE CUSTOMS OFFER MUST NOT RIDE INSIDE `live_proof`, EVER AGAIN.

    It used to. `live_proof` is the REFUSAL guardrail, which every conversational
    engine wants — so hiding a selling permission with a price inside it meant an
    engine could not take the refusal without also taking the pitch, and could not
    tell from its own code that it was selling. THREE engines inherited a
    $100-$200 custom offer they were never built to make: `send_followup` and
    `reply_mass_funnel` carried it into 1,869 of the 2,073 customs prompts on
    prod (90%), `send_followup` DELIVERED three (one drew a $30 tip against a
    $100 floor), and a since-retired engine rendered it to fans with ZERO lifetime
    spend in a prompt that simultaneously says "Don't offer pics or videos".
    The offer and the per-account flag that gated it are both gone."""
    # ── NO OFFER BLOCK ON THE BUNDLE AT ALL ──────────────────────────────
    # "No selling": Auto-reply and the info-gather lane only chat, so the
    # separate offer block they used to render (`customs_offer`, built from
    # `_CUSTOMS_CARVE_OUT`) was deleted. A resurrected one would be a renderable
    # pitch with no engine-level owner — the exact shape of the original bug.
    assert not hasattr(_voice.VoiceBlocks, "customs_offer"), (
        "the customs offer block is back on the voice bundle")
    assert not hasattr(_voice, "_CUSTOMS_CARVE_OUT")


async def case_load_voice_blocks():
    """ONE row read resolves the whole voice bundle; NULL / junk / no row → her."""
    async with get_session() as s:
        s.add(Account(id="acc_voice_him"))
        s.add(AccountAiConfig(account_id="acc_voice_him", voice="him"))
        s.add(Account(id="acc_voice_null"))
        s.add(AccountAiConfig(account_id="acc_voice_null"))       # voice NULL, no style
        s.add(Account(id="acc_voice_junk"))
        s.add(AccountAiConfig(account_id="acc_voice_junk", voice="banana"))

    him = await _common.load_voice_blocks("acc_voice_him")
    assert him.voice == "him"
    assert him.is_male and him.texter_noun == "guy"

    for aid in ("acc_voice_null", "acc_voice_junk", "acc_absent"):
        b = await _common.load_voice_blocks(aid)          # NULL / junk / no row → her
        assert b.voice == "her", aid
        assert b.painful_texting == _golden()["PAINFUL_TEXTING"], aid   # vs main
        assert b.texter_noun == "girl", aid


if __name__ == "__main__":
    _harness.run(
        case_persona_canon_unchanged_by_default,
        case_autoreply_prompt_unchanged_by_default,
        case_chat_builder_prompts_unchanged_by_default,
        case_female_lane_matches_the_pre_branch_golden,
        case_shared_blocks_unchanged_by_default,
        case_garbage_voice_degrades_to_her,
        case_persona_canon_male_labels,
        case_autoreply_male_prompt,
        case_ass_fallback_also_dropped_for_male,
        case_offplatform_deflection_is_male_voiced,
        case_finalize_draft_threads_voice,
        case_both_lanes_stay_structurally_parallel,
        case_every_gendered_label_has_a_male_form,
        case_every_canon_slot_has_a_male_placeholder,
        case_humanizer_is_laned_and_her_half_is_the_golden,
        case_send_followup_refusal_and_address_are_laned,
        case_sticker_pack_is_laned,
        case_male_pack_has_its_own_gifs,
        case_no_production_sender_forgets_the_lane,
        case_the_starter_brain_is_laned,
        case_the_refusal_block_can_never_carry_the_offer,
        case_load_voice_blocks,
        case_engines_without_a_humanizer_still_get_the_emoji_rule,
        case_emoji_rule_does_not_depend_on_the_human_style_checkbox,
        case_prompt_builders_never_assert_a_female_creator,
        case_canned_surfaces_are_laned,
        case_his_canned_text_obeys_his_own_emoji_rule,
    )
