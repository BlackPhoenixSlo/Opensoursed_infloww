#!/usr/bin/env python3
import _harness  # noqa: F401 — MUST be first

_harness.bootstrap()

import json  # noqa: E402

from automations import _common, _voice, autoreply  # noqa: E402
from automations._outbound import finalize_draft  # noqa: E402
from automations._persona import compose_persona  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, Fan  # noqa: E402


class _Cfg:

    def __init__(self, **kw):
        self.persona = kw.get("persona")
        self.location = kw.get("location")
        self.persona_facts_json = kw.get("persona_facts_json")
        self.voice = kw.get("voice")


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
    msgs = autoreply._build_messages(
        "persona", _fan(**kw), [("in", "hey you about?")],
        "answer his last message directly, then a light tease.",
        style_on=True, painful_on=True, v=_voice.blocks(voice),
    )
    return "\n\n".join(m["content"] for m in msgs)



def _golden() -> dict:
    import pathlib
    return json.loads(
        (pathlib.Path(__file__).parent / "fixtures" / "female_lane_golden.json").read_text())


def case_persona_canon_unchanged_by_default():
    absent = compose_persona(_Cfg(persona="p", persona_facts_json=_FACTS),
                             fallback="fb")
    null = compose_persona(_Cfg(persona="p", persona_facts_json=_FACTS, voice=None),
                           fallback="fb")
    her = compose_persona(_Cfg(persona="p", persona_facts_json=_FACTS, voice="her"),
                          fallback="fb")
    assert absent == null == her, "default persona canon moved"
    assert "What she's into: loves eye contact" in her
    assert "What she won't do: no live calls" in her


def case_autoreply_prompt_unchanged_by_default():
    assert _autoreply_prompt(None) == _autoreply_prompt("her") == _autoreply_prompt("")
    assert "- likes: boobs" in _autoreply_prompt(None)


def case_chat_builder_prompts_unchanged_by_default():
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
        assert "yo girl, not an assistant)" in render(None), f"{name} style header drifted"
        assert "yo guy, not an assistant)" in render("him"), f"{name} male header wrong"


def case_female_lane_matches_the_pre_branch_golden():
    golden = _golden()
    her = _voice.blocks(None)
    assert her.painful_texting == golden["PAINFUL_TEXTING"], "PAINFUL_TEXTING drifted from main"
    assert her.live_proof == golden["LIVE_PROOF_GUARDRAIL"], "LIVE_PROOF_GUARDRAIL drifted from main"
    assert list(her.off_deflections) == golden["_OFF_DEFLECTIONS"], "_OFF_DEFLECTIONS drifted from main"
    assert _common.PAINFUL_TEXTING == golden["PAINFUL_TEXTING"]
    assert _common.LIVE_PROOF_GUARDRAIL == golden["LIVE_PROOF_GUARDRAIL"]
    assert list(_common._OFF_DEFLECTIONS) == golden["_OFF_DEFLECTIONS"]


def case_shared_blocks_unchanged_by_default():
    golden = _golden()
    for v in (None, "her", "", "HER", "nonsense", 7, [], {"a": 1}):
        b = _voice.blocks(v)
        assert b.painful_texting == golden["PAINFUL_TEXTING"], v
        assert b.live_proof == golden["LIVE_PROOF_GUARDRAIL"], v
        assert list(b.off_deflections) == golden["_OFF_DEFLECTIONS"], v
        assert not b.is_male, v
        assert b.texter_noun == "girl", v


def case_garbage_voice_degrades_to_her():
    assert _voice.norm_voice("xyz") == _voice.VOICE_HER
    assert _voice.norm_voice(None) == _voice.VOICE_HER
    assert _voice.norm_voice(["him"]) == _voice.VOICE_HER
    assert _voice.norm_voice("  HIM  ") == _voice.VOICE_HIM



def case_persona_canon_male_labels():
    him = compose_persona(_Cfg(persona="p", persona_facts_json=_FACTS, voice="him"),
                          fallback="fb")
    assert "What he's into: loves eye contact" in him
    assert "What he won't do: no live calls" in him
    for dead in ("What she's into", "What she won't do"):
        assert dead not in him, f"female label survived: {dead}"
    assert "Work: coach" in him and "Kids: none" in him


def case_autoreply_male_prompt():
    him = _autoreply_prompt("him")
    assert "- likes: boobs" not in him and "- likes: ass" not in him
    assert "- age: 29" in him and "- city: Leeds" in him and "- job: welder" in him
    assert "his last message" in him, "fan-side pronouns must not flip"
    assert "like a real girl half-glued to her phone" not in him
    assert "you write the LEAST you can" in him, "brevity governor lost"
    assert "i don't do facetime babe" not in him
    assert "LIVE PROOF / FACETIME (hard rule)" in him, "live-proof rule lost"


def case_ass_fallback_also_dropped_for_male():
    her = _autoreply_prompt("her", likes_boobs=False, likes_ass=True)
    him = _autoreply_prompt("him", likes_boobs=False, likes_ass=True)
    assert "- likes: ass" in her
    assert "- likes: ass" not in him


def case_offplatform_deflection_is_male_voiced():
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
    for v in ("her", "him"):
        out, why = _common.guard_offplatform(
            "just chatting", random.Random(1), _voice.blocks(v))
        assert out == "just chatting" and why == []


async def case_finalize_draft_threads_voice():
    leaky = "add me on snapchat @bob"
    her, _ = await finalize_draft(
        leaky, account_id="a", fan_id=1, purpose="autoreply",
        v=_voice.blocks("her"))
    him, _ = await finalize_draft(
        leaky, account_id="a", fan_id=1, purpose="autoreply",
        v=_voice.blocks("him"))
    assert her in _voice.OFF_DEFLECTIONS["her"]
    assert him in _voice.OFF_DEFLECTIONS["him"]
    bare, _ = await finalize_draft(leaky, account_id="a", fan_id=1, purpose="autoreply")
    assert bare in _voice.OFF_DEFLECTIONS["her"]


def case_both_lanes_stay_structurally_parallel():
    her, him = _voice.blocks("her"), _voice.blocks("him")
    assert len(her.off_deflections) == len(him.off_deflections)
    for b in (her, him):
        assert b.live_proof.startswith("LIVE PROOF / FACETIME (hard rule):")
        assert "you write the LEAST you can" in b.painful_texting
        assert b.painful_texting.startswith("THE FEEL OF TEXTING")
    assert her.painful_texting != him.painful_texting
    assert her.live_proof != him.live_proof


def case_every_gendered_label_has_a_male_form():
    import re
    from automations._persona import PERSONA_FACT_FIELDS
    overrides = _voice.fact_labels("him")
    female = re.compile(r"\b(she|her|hers)\b", re.I)
    missing = [k for k, label in PERSONA_FACT_FIELDS
               if female.search(label) and k not in overrides]
    assert not missing, f"gendered labels with no male form: {missing}"
    still_female = [k for k, v in overrides.items() if female.search(v)]
    assert not still_female, f"male override is still female: {still_female}"


def case_every_canon_slot_has_a_male_placeholder():
    import re
    from automations._persona import PERSONA_FACT_FIELDS
    him, her = _voice.fact_placeholders("him"), _voice.fact_placeholders("her")
    declared = {k for k, _ in PERSONA_FACT_FIELDS}

    assert set(him) == declared and set(her) == declared
    try:
        _voice.assert_canon_parity(PERSONA_FACT_FIELDS + (("hobbies", "Her hobbies"),))
    except AssertionError:
        pass
    else:                       # pragma: no cover - the guard is the point
        raise AssertionError("a new canon slot with no male form did not fail parity")
    try:
        _voice.assert_canon_parity(PERSONA_FACT_FIELDS + (("age", "Her age"),))
    except AssertionError:
        pass
    else:                       # pragma: no cover
        raise AssertionError("a gendered label with no male override did not fail parity")

    blanked = [k for k in declared if her[k] and not him[k]]
    assert not blanked, f"male placeholder blank where hers is filled: {blanked}"

    female = re.compile(r"\b(she|her|hers|herself|girl|girls|woman|women)\b", re.I)
    still_female = [(k, v) for k, v in him.items() if female.search(v)]
    assert not still_female, f"male placeholder is still female: {still_female}"

    SHARED = {
        "relationship", "kids", "family",
        "kinks", "limits",
    }
    copied = [k for k in declared - SHARED if him[k] == her[k]]
    assert not copied, f"male placeholder is her copy verbatim: {copied}"
    assert SHARED <= declared, f"SHARED names an undeclared slot: {sorted(SHARED - declared)}"
    assert all(him[k] == her[k] for k in SHARED), \
        f"a SHARED slot diverged — decide which set it is in: " \
        f"{sorted(k for k in SHARED if him[k] != her[k])}"

    assert her["job"] == "content creator, waitressed before"
    assert her["tattoos"] == "script on her ribs, small rose on left wrist"
    assert her["kinks"] == "you fill this in — Enrich never guesses"
    assert _voice.fact_placeholders(None) == her
    assert _voice.fact_placeholders("hom") == her
    esc = _voice.fact_placeholders("him")
    esc["age"] = "999"
    assert _voice.fact_placeholders("him")["age"] != "999"


def case_humanizer_is_laned_and_her_half_is_the_golden():
    golden = _golden()
    her, him = _voice.blocks("her"), _voice.blocks("him")
    assert her.humanizer == golden["STYLE_HUMANIZER"], "female humanizer drifted from main"
    assert _common.STYLE_HUMANIZER == golden["STYLE_HUMANIZER"], "the re-export drifted"

    assert "bratty" in her.humanizer
    assert "bratty" not in him.humanizer, "a dom is not bratty"
    assert "NEVER seeking his approval" in him.humanizer

    assert "😏" in him.humanizer and "😈" in him.humanizer
    for banned in ("🥺", "🥰", "😘", "💦", "🥵"):
        assert banned in him.humanizer, f"{banned} must be named as forbidden"
    assert "🥺" not in her.humanizer, "the female block names no emoji set"
    for b in (her, him):
        assert "0-1 emoji, never the same emoji twice" in b.humanizer


def case_send_followup_refusal_and_address_are_laned():
    from automations import send_followup
    common = dict(tod="evening", activity="", clock="", fan_name="", fan_bio="")

    her_sys = send_followup._compose_system({"persona": "p"}, **common)
    him_sys = send_followup._compose_system(
        {"persona": "p", "_voice": _voice.blocks("him")}, **common)

    assert _golden()["LIVE_PROOF_GUARDRAIL"] in her_sys
    assert "facetime babe" in her_sys
    assert "facetime babe" not in him_sys, "the male lane still refuses like a woman"
    assert "you get me right here or not at all" in him_sys

    assert "babe" in send_followup._compose_user(1, "", 5.0)
    assert "babe" not in send_followup._compose_user(1, "", 5.0, "man")


_BANNED_FOR_HIM = "🥺🥰😘💕💦🥵😍🙈✨💅💋😻🤭🤍🌟"


def case_engines_without_a_humanizer_still_get_the_emoji_rule():
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
        assert 'if style_on else ""' not in src, (
            f"{mod.__name__} still drops the vocabulary when human-style is off")


def case_prompt_builders_never_assert_a_female_creator():
    from automations import _voice, send_welcome
    from db.models import Fan

    f = Fan(account_id="a", fan_id=1, of_display_name="Mike")

    assert send_welcome._local_greeting("Cody") == "Hey C-C-C-Cute Cody ! !!"
    assert send_welcome._local_greeting("Cody", "him") == "Hey C-C-C-Cocky Cody ! !!"
    for letter in ("C", "J", "Y"):
        assert send_welcome._ADJS[letter] != send_welcome._ADJS_HIM[letter], letter
    assert set(send_welcome._ADJS) == set(send_welcome._ADJS_HIM), "a letter has no male form"
    assert send_welcome._greet_token({"name": "xx_99"}) == "cutie"
    assert send_welcome._greet_token({"name": "xx_99"}, "him") == "boy"


def case_canned_surfaces_are_laned():
    import dataclasses
    from automations import _voice
    her, him = _voice.blocks(_voice.VOICE_HER), _voice.blocks(_voice.VOICE_HIM)

    SAME = {
        "voice",
        "emoji_vocab",
        "is_male",
    }

    def _named_blocks(cls):
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
    assert her.emoji_vocab == "" and him.emoji_vocab != ""

    assert her.unlock_reactions[0] == "omg enjoy babe 😘"
    assert her.unlock_prompt == "unlock this babe 😏"
    assert her.aftercare == "mmm come here babe"
    assert her.nudge_lines[0] == "hey {name} u still there ? 🙈"
    assert "legs spread" in her.sell_caption_example

    assert all("{name}" in line for line in him.nudge_lines)
    assert not any(w in " ".join(him.nudge_lines).lower()
                   for w in ("i miss", "missing u", "dont leave me like this"))


def case_his_canned_text_obeys_his_own_emoji_rule():
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

    her_lines = " ".join(_voice.blocks(_voice.VOICE_HER).nudge_lines)
    assert any(c in her_lines for c in _BANNED_FOR_HIM), "her pool lost its emoji"


def case_sticker_pack_is_laned():
    import re
    from automations import cat_stickers
    her = cat_stickers.prompt_block("allow")
    him = cat_stickers.prompt_block("allow", "him")

    assert "the kind real girls spam in texts" in her
    assert "real girls spam" not in him, "a dom was told to text like a girl"
    assert "cat reaction gifs" in her
    assert " cat " not in him and "CAT STICKERS" not in him, "his pack isn't cats"
    assert "dog & wolf reaction gifs" in him

    her_tags = set(re.findall(r"^- ([a-z_]+):", her, re.M))
    him_tags = set(re.findall(r"^- ([a-z_]+):", him, re.M))
    assert her_tags == set(cat_stickers._CATALOG), her_tags
    assert him_tags < her_tags, "the male list must be a strict subset"
    submissive = cat_stickers._TAGS_NOT_FOR_HIM & her_tags
    assert submissive, "the female-only set is empty — the split stopped meaning anything"
    for tag in submissive:
        assert tag not in him_tags, f"male lane can still send {tag}"
    assert him_tags == her_tags - cat_stickers._TAGS_NOT_FOR_HIM, him_tags
    for v in (None, "", "her", "HER", "nonsense"):
        assert cat_stickers.prompt_block("allow", v) == her, v


def case_male_pack_has_its_own_gifs():
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
        assert cs.pick_gif(tag, rng, "acc_f", 1) in hers
    for banned in cs._TAGS_NOT_FOR_HIM:
        assert cs.pick_gif(banned, rng, "acc_m", 2, voice="him") is None, banned
    for banned in cs._TAGS_NOT_FOR_HIM & set(cs._CATALOG):
        assert cs.pick_gif(banned, rng, "acc_f", 2) is not None, banned


def case_no_production_sender_forgets_the_lane():
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    files = [p for p in sorted(root.rglob("*.py"))
             if "tests" not in p.parts and not p.name.startswith(("_drive_", "_verify_"))]
    assert len(files) > 20, f"glob found only {len(files)} modules — path wrong?"
    trees = {}
    for path in files:
        try:
            trees[path] = ast.parse(path.read_text())
        except SyntaxError:
            continue

    laned: dict[tuple[str, str], int | None] = {}
    reexports = {(path.stem, a.name): ((n.module or "").split(".")[-1], a.name)
                 for path, tree in trees.items() for n in tree.body
                 if isinstance(n, ast.ImportFrom) and n.level for a in n.names}
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
    assert len(laned) >= 14, f"only {len(laned)} laned defs found: {sorted(names)}"

    misses = []
    for path, tree in trees.items():
        local_defs = {n.name for n in ast.walk(tree)
                      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        owners: dict[str, tuple[str, str]] = {}
        for stem, name in laned:
            if stem == path.stem:
                owners[name] = (stem, name)
        modules: dict[str, str] = {}
        imported_mods: set[str] = set()
        stems = {stem for stem, _ in laned}
        stems |= {s for (s, _), tgt in reexports.items() if tgt in laned}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                src = (node.module or "").split(".")[-1]
                for alias in node.names:
                    hit = (src, alias.name)
                    hit = hit if hit in laned else reexports.get(hit, hit)
                    if hit in laned:
                        owners[alias.asname or alias.name] = hit
                    if alias.name in stems:
                        modules[alias.asname or alias.name] = alias.name
                    if not node.module or node.module.startswith("."):
                        imported_mods.add(alias.asname or alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    stem = alias.name.split(".")[-1]
                    binding = (alias.asname or alias.name).split(".")[-1]
                    imported_mods.add(binding)
                    if stem in stems:
                        modules[binding] = stem

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if isinstance(fn, ast.Attribute):
                holder = fn.value.id if isinstance(fn.value, ast.Name) else None
                stem = modules.get(holder or "")
                key = (stem, fn.attr) if stem else None
                key = key if key in laned else reexports.get(key, key)
                name = fn.attr
            elif isinstance(fn, ast.Name):
                owned = owners.get(fn.id)
                key = owned if owned else None
                name = fn.id
            else:
                continue
            if key is None:
                if isinstance(fn, ast.Attribute) and (
                        fn.value.id if isinstance(fn.value, ast.Name) else ""
                ) in imported_mods:
                    continue
                if name not in local_defs and name in {n for _, n in laned}:
                    misses.append(f"{path.relative_to(root)}:{node.lineno} {name}() "
                                  f"(callee unresolved — import it by name or module)")
                continue
            if key not in laned:
                continue
            if any(k.arg in ("v", "voice")
                   and not (isinstance(k.value, ast.Constant) and k.value.value is None)
                   for k in node.keywords):
                continue
            idx = laned[key]
            if idx is not None and len(node.args) > idx:
                continue
            if any(k.arg is None for k in node.keywords):
                continue
            if any(isinstance(a, ast.Starred) for a in node.args):
                continue
            misses.append(f"{path.relative_to(root)}:{node.lineno} {name}()")
    assert not misses, ("these production call sites take the SHIPPED lane by "
                        "default:\n  " + "\n  ".join(sorted(misses)))


def case_the_starter_brain_is_laned():
    import re
    import brain_defaults as bd
    from brain_defaults import BRAIN_DEFAULTS_HER, brain_defaults

    assert brain_defaults("her") == BRAIN_DEFAULTS_HER
    assert not hasattr(bd, "BRAIN_DEFAULTS"), "the ambiguous alias came back"
    for stored in (None, "", "  ", "her", " HER ", "hom", 7, ["him"]):
        assert brain_defaults(stored) == BRAIN_DEFAULTS_HER, stored
    assert brain_defaults() == BRAIN_DEFAULTS_HER, "the bare call changed lane"

    him = brain_defaults("him")
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
    for k in ("model", "daily_cost_cap_cents", "utc_offset", "timezone",
              "model_by_purpose", "persona_facts", "time_images"):
        assert him[k] == BRAIN_DEFAULTS_HER[k], k

    brain_defaults("him")["persona"] = "mutated"
    assert brain_defaults("him")["persona"] != "mutated"
    brain_defaults("him")["time_activities"]["night"] = "mutated"
    assert brain_defaults("him")["time_activities"]["night"] != "mutated"
    brain_defaults("her")["persona_facts"]["leak"] = 1
    assert "leak" not in brain_defaults("her")["persona_facts"]


def case_the_refusal_block_can_never_carry_the_offer():
    assert not hasattr(_voice.VoiceBlocks, "customs_offer"), (
        "the customs offer block is back on the voice bundle")
    assert not hasattr(_voice, "_CUSTOMS_CARVE_OUT")


async def case_load_voice_blocks():
    async with get_session() as s:
        s.add(Account(id="acc_voice_him"))
        s.add(AccountAiConfig(account_id="acc_voice_him", voice="him"))
        s.add(Account(id="acc_voice_null"))
        s.add(AccountAiConfig(account_id="acc_voice_null"))
        s.add(Account(id="acc_voice_junk"))
        s.add(AccountAiConfig(account_id="acc_voice_junk", voice="banana"))

    him = await _common.load_voice_blocks("acc_voice_him")
    assert him.voice == "him"
    assert him.is_male and him.texter_noun == "guy"

    for aid in ("acc_voice_null", "acc_voice_junk", "acc_absent"):
        b = await _common.load_voice_blocks(aid)
        assert b.voice == "her", aid
        assert b.painful_texting == _golden()["PAINFUL_TEXTING"], aid
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
