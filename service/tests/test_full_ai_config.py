#!/usr/bin/env python3
"""test_full_ai_config — Full AI Chat's config: pure tables and the config API (phase 03a).

  case_turn_bound_s_table   20 + (1 + len(writers)) x writer_timeout_s: defaults -> 245,
                            one Writer at 5 s -> 30 (spec › Contracts › One Turn bound)
  case_turn_bound_cap_table (rwl-c F3) validate refuses a side whose turn_bound_s tops TURN_BOUND_MAX_S (900):
                            DEFAULTS (245) and the default chain at the 120 s max pass; a stored side over it
                            still loads (merged, turn_bound_s) and only its write is refused
  case_validate_table       (ticket 37) every refusal the spec names, one key changed each row;
                            DEFAULTS passes
  case_merged_fills_a_later_key  a stored side missing a later key takes it from DEFAULTS
  case_reference_covers_every_key  REFERENCE has exactly DEFAULTS' keys in its order, each with an allowed and
                            an about line; `reference()` defaults are DEFAULTS; both merged sides hold every key
  case_style_layers_table   `style`: five bools, exactly those keys; the legacy `text_style` on a write
                            sets all five and is never stored; a stored side with only `text_style`
                            reads girl = all on, formal = all off on every side; one layer stored alone
  case_folders_table        (ticket 43) `folders` refs validated by name, default all, a stored
                            v1 without `folders` reads all, unknown key still refused
  case_draft_questions_table (ticket 47) `draft_questions` a bool, default true (owner 2026-11-14);
                            a stored v1 without it reads true on every side
  case_sell_spacing_table   (03d ticket 59) `sell_spacing` a bool, default true, labelled "Spacing",
                            in CONFIG_KEYS; a stored v1 without it reads true
  case_sell_bundle_table    (03d ticket 61) `sell_bundle` shoot|fill, default fill, a stored v1
                            without it reads fill, labelled "Fill the set" on the page
  case_sell_count_strip_emojis_table  `sell_count` (default true) and `strip_emojis` (default false) bools,
                            page controls "Match his count" / "Strip emojis", in CONFIG_KEYS; a stored v1
                            without them reads the defaults
  case_typo_pct_table       `typo_pct` null (auto) or a whole 0-100, labelled "Typos %"; a stored
                            v1 without it reads null
  case_gif_pct_table        `gif_pct` null (auto) or a whole 0-100, labelled "GIFs %"; a stored
                            v1 without it reads null
  case_top_spend_cents_table (04b ticket 75) `top_spend_cents` a whole number >= 0, default 100000, labelled
                            "Top spend limit", in CONFIG_KEYS; a stored v1 without it reads 100000
  case_fans_table           (04b ticket 76) `fans` {include, exclude} lists of distinct OF list ids, default both
                            empty, each refusal names the key, labelled "Fans", in CONFIG_KEYS; a stored v1
                            without it reads the default
  case_catchup_minutes_table `catchup_minutes` {after_live: 1-6 ascending whole minutes 0-1440, then_every: 5-1440},
                            default 0/5/15 then 15, each refusal names the key, JSON-only, in CONFIG_KEYS; a stored
                            v1 without it reads the default
  case_transitions_and_stale_rev put_draft / save / rollback, StaleRev on a rev mismatch,
                            Invalid on a bad draft, nothing to save, nothing to roll back to
  case_ts_constants_match   the page's copies it keeps (fullAiConfig.ts STYLE_LAYERS, the legacy text_style pair,
                            the Sell switches' sell_nearest / sell_bundle values, the reply speed / Questions / PPV
                            caption labels, the plain switches' defaults) match these; `limits` lists the default first
  case_page_labels          the keys the page now edits (2026-11-15) carry their control label in REFERENCE
  case_manual_names_every_key  the help bot's manual names every DEFAULTS key but `version` as `key`
  case_audience_keys_carried_table  (owner 2026-11-15) `fans` / `top_spend_cents` one value on every side: the config
                            writes (JSON boxes too) keep them, `put_audience` sets them on all three sides
  case_config_api_audience  PUT config/audience: no rev, all sides, rev bumped (next draft PUT not stale), 422s
  case_config_api_round_trip GET defaults (+ `reference`, `limits`), PUT 422 (unknown key, catch-up too fast) / 409 / 200, save, roll back twice =
                            identity; the `full_ai_chat` rule row byte-identical throughout

Run: ./venv/bin/python service/tests/test_full_ai_config.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import copy  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
from pathlib import Path  # noqa: E402

from sqlalchemy import text  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
from automations.full_ai_config import (  # noqa: E402
    CAPTION_WRITERS, DEFAULTS, INFO_QUESTIONS, REFERENCE, REPLY_SPEEDS, SELL_BUNDLE, SELL_NEAREST, STYLE_LAYERS,
    TEXT_STYLES, TURN_BOUND_MAX_S, WRITER_PROVIDERS, Invalid, StaleRev, limits, merged, put_audience, put_checkpoint,
    put_draft, reference, rollback, save, style_layers, turn_bound_s, validate,
)
from db.engine import get_session  # noqa: E402
from db.models import AutomationRule  # noqa: E402
from llm_models import MODELS  # noqa: E402

# Every Writer-provider model (the page's Writer select), sorted.
WRITER_MODELS = sorted(m for m, v in MODELS.items() if v.provider in WRITER_PROVIDERS
                       or m == "euryale-v2.3-deepinfra")
WRITER_PROVIDERS_OF = {m: MODELS[m].provider for m in WRITER_MODELS}
# The LLM keys row's names, as Settings → AI keys names each provider.
PROVIDER_LABELS = {"nanogpt": "NanoGPT", "openrouter": "OpenRouter", "deepseek": "DeepSeek", "deepinfra": "DeepInfra",
                   "zai": "Z.ai (GLM)", "anthropic": "Anthropic (Claude)", "typesafe": "TypeSafe (Jev)"}


def case_turn_bound_s_table():
    table = [
        (DEFAULTS, 245),
        ({**DEFAULTS, "writers": ["deepseek-v4-flash"], "writer_timeout_s": 5}, 30),
        ({**DEFAULTS, "writers": ["euryale-v2.3", "hermes-4-405b"], "writer_timeout_s": 60}, 200),
        # 20 + extract 30 + v2.3's own 90 + Hermes 30; one retry doubles the Writers' part.
        ({**DEFAULTS, "writers": ["euryale-v2.3", "hermes-4-405b"], "writer_timeout_s": 30,
          "writer_timeouts": {"euryale-v2.3": 90}}, 170),
        ({**DEFAULTS, "writers": ["euryale-v2.3", "hermes-4-405b"], "writer_timeout_s": 30,
          "writer_timeouts": {"euryale-v2.3": 90}, "writer_retries": 1}, 290),
    ]
    for cfg, want in table:
        assert turn_bound_s(cfg) == want, (cfg["writers"], cfg["writer_timeout_s"], turn_bound_s(cfg))


def case_turn_bound_cap_table():
    """rwl-c F3: 6 Writers x 120 s x (1 + 3 retries) was a 3020 s Turn; validate now caps the bound."""
    six = ["euryale-v2.3", "euryale-v2.2", "euryale-v2.3-deepinfra", "hermes-4-405b", "glm-5.3-flash",
           "deepseek-v4-flash"]
    assert TURN_BOUND_MAX_S == 900
    assert turn_bound_s(DEFAULTS) * 3 < TURN_BOUND_MAX_S          # clear headroom on the shipped defaults
    passes = [
        {},                                                        # DEFAULTS: 245
        {"writer_timeout_s": 120},                                 # the default chain at the per-try max: 620
        {"writer_retries": 1},                                     # 425
        {"writers": six},                                          # 20 + 45 + 6 x 45 = 335
        {"writers": six, "writer_timeout_s": 120},                 # 860
    ]
    for change in passes:
        cfg = {**DEFAULTS, **change}
        assert turn_bound_s(cfg) <= TURN_BOUND_MAX_S and validate(cfg) == [], (change, turn_bound_s(cfg), validate(cfg))
    refused = [
        ({"writers": six, "writer_timeout_s": 120, "writer_retries": 3}, 3020),
        ({"writer_timeout_s": 120, "writer_retries": 1}, 1100),
        ({"writers": six, "writer_timeouts": {"hermes-4-405b": 120, "glm-5.3-flash": 120}, "writer_retries": 1}, 905),
    ]
    for change, bound in refused:
        cfg = {**DEFAULTS, **change}
        assert turn_bound_s(cfg) == bound, (change, turn_bound_s(cfg))
        assert validate(cfg) == [f"writers: one Turn could take {bound} s (Jev 20 + extract + every Writer try); "
                                 f"max {TURN_BOUND_MAX_S} s: fewer Writers or retries, or shorter timeouts"], validate(cfg)
        assert _raises(Invalid, put_draft, None, cfg, 0).errors == validate(cfg)
    # A bad writer key answers its own error only (no bound computed off it).
    assert validate({**DEFAULTS, "writer_retries": "3"}) == ["writer_retries: must be a whole number from 0 to 3"]
    assert validate({**DEFAULTS, "writers": "x", "writer_retries": 3}) == ["writers: must be a list of model ids"]
    # A side stored over the cap (before it existed) still loads; the Turn's deadline reads it as before.
    over = {**DEFAULTS, "writers": six, "writer_timeout_s": 120, "writer_retries": 3}
    got = merged({"checkpoint": over, "draft": over, "rev": 5})
    assert got["checkpoint"] == over and turn_bound_s(got["checkpoint"]) == 3020, got
    assert REFERENCE["writers"]["allowed"].endswith(f"one Turn at most {TURN_BOUND_MAX_S} s"), REFERENCE["writers"]
    for k in ("writer_timeout_s", "writer_timeouts", "writer_retries"):
        assert f"{TURN_BOUND_MAX_S} s" in REFERENCE[k]["about"], (k, REFERENCE[k])


# ── validate ──────────────────────────────────────────────────────────

def case_validate_table():
    assert validate(DEFAULTS) == [], validate(DEFAULTS)
    assert {MODELS[w].provider for w in DEFAULTS["writers"]} <= WRITER_PROVIDERS
    assert validate({}) == [], validate({})          # a missing key is its default
    refused = [  # (change, the field its one error names)
        ({"writers": ["gpt-9"]}, "writers"),                                  # unknown model
        ({"writers": ["qwen3-vl-30b"]}, "writers"),                           # provider mismatch
        ({"writers": ["euryale-v2.3", "claude-haiku-5-5"]}, "writers"),       # provider mismatch
        ({"writers": []}, "writers"),
        ({"writers": ["euryale-v2.3", "euryale-v2.2", "euryale-v2.3-deepinfra", "hermes-4-405b",
                      "glm-5.3-flash", "deepseek-v4-flash", "deepseek-v4-pro"]}, "writers"),  # seven
        ({"writers": ["euryale-v2.3", "euryale-v2.3"]}, "writers"),           # repeated
        ({"writers": "euryale-v2.3"}, "writers"),
        ({"writer_timeout_s": 4}, "writer_timeout_s"),
        ({"writer_timeout_s": 121}, "writer_timeout_s"),
        ({"writer_timeouts": []}, "writer_timeouts"),
        ({"writer_timeouts": {"gpt-9": 30}}, "writer_timeouts"),                # unknown model
        ({"writer_timeouts": {"qwen3-vl-30b": 30}}, "writer_timeouts"),         # not a Writer
        ({"writer_timeouts": {"euryale-v2.3": 121}}, "writer_timeouts"),
        ({"writer_timeouts": {"euryale-v2.3": "60"}}, "writer_timeouts"),
        ({"writer_retries": 4}, "writer_retries"),
        ({"writer_retries": -1}, "writer_retries"),
        ({"writer_retries": 1.5}, "writer_retries"),
        ({"writer_retries": True}, "writer_retries"),
        ({"writer_timeout_s": True}, "writer_timeout_s"),
        ({"writer_timeout_s": "25"}, "writer_timeout_s"),
        ({"sell_on": "yes"}, "sell_on"),                                     # 03b: settable, a bool
        ({"sell_on": 1}, "sell_on"),
        ({"fans_list": []}, "fans_list"),
        ({"reserved": {}}, "reserved"),
        ({"nanogpt_api_key": "sk-x"}, "nanogpt_api_key"),                     # a key never lands here
        ({"reply_by_webhook": "yes"}, "reply_by_webhook"),
        ({"typing_sign": 1}, "typing_sign"),
        ({"typing_notification": None}, "typing_notification"),
        ({"caption_writer": "llm"}, "caption_writer"),
        ({"gifs": 0}, "gifs"),
        ({"reply_speed": "fast"}, "reply_speed"),
        ({"text_style": "boy"}, "Human style"),                              # the label, never the wire value
        ({"version": 2}, "version"),
        ({"info_fields": ["shoe_size"]}, "info_fields"),
    ]
    for change, field in refused:
        errs = validate({**DEFAULTS, **change})
        assert len(errs) == 1 and errs[0].startswith(f"{field}: "), (change, errs)
    assert validate([]) and validate(None), "not an object"
    for ok in ({"writers": ["deepseek-v4-flash"]}, {"writer_timeout_s": 5}, {"writer_timeout_s": 60},
               {"writers": ["hermes-4-405b", "euryale-v2.3"]}, {"reply_speed": "0-15-60"},
               {"text_style": "formal"}, {"gifs": True}, {"info_fields": []}, {"sell_on": True}):
        assert validate({**DEFAULTS, **ok}) == [], (ok, validate({**DEFAULTS, **ok}))


ON, OFF = dict.fromkeys(STYLE_LAYERS, True), dict.fromkeys(STYLE_LAYERS, False)
FORMAL = {**DEFAULTS, "style": OFF}                  # the stored shape of the old `text_style: "formal"`
FORMAL_IN = {**DEFAULTS, "text_style": "formal"}     # a write in the old shape (Do mode's alias)


def case_merged_fills_a_later_key():
    # A stored side from before `style` and `typing_notification`: `text_style` only.
    old = {k: v for k, v in DEFAULTS.items() if k not in ("typing_notification", "style")}
    got = merged({"checkpoint": {**old, "text_style": "girl", "gifs": True}, "previous": {**old, "text_style": "girl"},
                  "draft": {**old, "text_style": "formal"}, "rev": 4})
    assert got["checkpoint"] == {**DEFAULTS, "gifs": True}, got["checkpoint"]
    assert got["previous"] == DEFAULTS, got["previous"]
    assert got["draft"] == FORMAL, got["draft"]
    assert got["rev"] == 4
    assert merged(None) == {"checkpoint": DEFAULTS, "previous": None, "draft": DEFAULTS, "rev": 0}
    # A stored v1 config from before 03b (no `sell_on`) reads selling off.
    pre = {k: v for k, v in DEFAULTS.items() if k != "sell_on"}
    assert merged({"checkpoint": pre, "draft": pre, "rev": 1})["draft"]["sell_on"] is False


def case_reference_covers_every_key():
    assert set(REFERENCE) == set(DEFAULTS), set(REFERENCE) ^ set(DEFAULTS)
    assert list(REFERENCE) == list(DEFAULTS), "REFERENCE out of DEFAULTS order"
    for k, r in REFERENCE.items():
        assert set(r) == {"allowed", "about", "page"}, (k, r)
        assert isinstance(r["allowed"], str) and r["allowed"].strip(), k
        assert isinstance(r["about"], str) and r["about"].strip(), k
        assert r["page"] is None or (isinstance(r["page"], str) and r["page"].strip()), k
    # One feature: Chat tease has the page switch; the old Ride-along photos (`offer_ride`) is retired.
    assert REFERENCE["chat_tease"]["page"] == "Chat tease" and "offer_ride" not in DEFAULTS
    assert "Ride-along photos" not in {r["page"] for r in REFERENCE.values()}
    ref = reference()
    assert [r["key"] for r in ref] == list(DEFAULTS)
    assert {r["key"]: r["default"] for r in ref} == DEFAULTS
    ref[0]["default"], ref[2]["default"]["typos"] = 9, False     # a copy: DEFAULTS untouched
    assert DEFAULTS["version"] == 1 and DEFAULTS["style"]["typos"] is True
    m = merged(None)
    for side in ("checkpoint", "draft"):
        assert set(m[side]) == set(DEFAULTS), (side, set(m[side]) ^ set(DEFAULTS))


APP = Path(__file__).resolve().parents[2] / "app"


def case_manual_names_every_key():
    """The help bot's manual (assistant_manual.md, its Full AI Chat section) names every config key as `key`, so a new
    key without a manual line fails here."""
    manual = (Path(__file__).resolve().parents[1] / "assistant_manual.md").read_text(encoding="utf-8")
    missing = [k for k in DEFAULTS if k != "version" and f"`{k}`" not in manual]
    assert not missing, f"assistant_manual.md does not name: {missing}"


def case_ts_constants_match():
    """The constants the page keeps a copy of (a TS type, or a value the controls write) match the server's; the rest
    it reads off GET config's `limits`."""
    ts = (APP / "components" / "automations" / "fullAiConfig.ts").read_text()
    layers = re.search(r"export const STYLE_LAYERS = \[([^\]]*)\] as const;", ts)
    assert layers and tuple(re.findall(r'"(\w+)"', layers[1])) == STYLE_LAYERS, layers
    casual = re.search(r'export const CASUAL_STYLE = "(\w+)";', (APP / "lib" / "fullAiStyle.ts").read_text())
    formal = re.search(r'ts === CASUAL_STYLE \|\| ts === "(\w+)"', ts)
    assert casual and formal and (casual[1], formal[1]) == TEXT_STYLES, (casual, formal)
    for key, values in (("sell_nearest", SELL_NEAREST), ("sell_bundle", SELL_BUNDLE)):
        sw = re.search(rf'key: "{key}", label: "[^"]+", on: "(\w+)", off: "(\w+)"', ts)
        assert sw and {sw[1], sw[2]} <= set(values) and sw[1] != sw[2], (key, sw)
        assert DEFAULTS[key] != sw[2], (key, "the default must read on")
    labels = re.search(r"const SPEED_LABEL: Record<string, string> = \{([^}]*)\}", ts)
    assert labels and set(re.findall(r'"([^"]+)":', labels[1])) <= set(REPLY_SPEEDS), labels
    for name, values in (("INFO_QUESTIONS_LABEL", INFO_QUESTIONS), ("CAPTION_LABEL", CAPTION_WRITERS)):
        m = re.search(rf"const {name}: Record<string, string> = \{{([^}}]*)\}}", ts)
        assert m and set(re.findall(r'(\w+):', m[1])) == set(values), (name, m)
    # The plain switches' defaults (what a side without the key reads) are the server's.
    sw = re.findall(r'(\w+): \{ label: "[^"]+", def: (true|false)', ts)
    assert {k for k, _ in sw} == {"sext_on", "lead_in", "describe_fan_photos", "strip_emojis"}, sw
    for k, d in sw:
        assert DEFAULTS[k] is (d == "true"), (k, d)
    # A side without the key reads the first option (`limits` lists the default first).
    lim = limits()
    assert lim["info_questions"][0] == DEFAULTS["info_questions"], lim
    assert lim["caption_writers"][0] == DEFAULTS["caption_writer"], lim


def case_page_labels():
    """The keys the page edits since 2026-11-15 name their control (REFERENCE `page`, the plan card's label too)."""
    import assistant_full_ai
    want = {"sext_on": "Sexting", "lead_in": "Lead-in questions", "info_questions": "Questions",
            "caption_writer": "PPV caption", "sell_count": "Match his count", "describe_fan_photos": "Read his photos",
            "strip_emojis": "Strip emojis", "top_spend_cents": "Top spend limit", "fans": "Fans"}
    for k, lab in want.items():
        assert REFERENCE[k]["page"] == lab and assistant_full_ai.label(k) == lab, (k, REFERENCE[k], assistant_full_ai.label(k))


def case_style_layers_table():
    """`style` is the stored truth of the five human-texting layers; `text_style` survives as the
    write alias / old stored shape (girl = all on, formal = all off)."""
    assert DEFAULTS["style"] == ON and "text_style" not in DEFAULTS, DEFAULTS
    for ok in ({**ON, "typos": False}, OFF, {**OFF, "spacing": True}):
        assert validate({**DEFAULTS, "style": ok}) == [], ok
    for bad in ({**ON, "typos": 1}, {k: v for k, v in ON.items() if k != "painful"}, {**ON, "emoji": True},
                [], None, "girl", {**ON, "typos": None}):
        errs = validate({**DEFAULTS, "style": bad})
        assert len(errs) == 1 and errs[0].startswith("style: want exactly texting, nonnative, spacing, typos, painful"), (bad, errs)
    assert validate({**DEFAULTS, "text_style": "girl"}) == validate(FORMAL_IN) == []
    # The read: an alias wins over `style`; neither = off (the old `text_style != "girl"`).
    rows = [({"style": {**ON, "typos": False}}, {**ON, "typos": False}),
            ({"text_style": "girl"}, ON), ({"text_style": "formal"}, OFF),
            ({"text_style": "formal", "style": ON}, OFF), ({"text_style": "girl", "style": OFF}, ON),
            ({}, OFF), ({"style": {"typos": True}}, {**OFF, "typos": True})]
    for cfg, want in rows:
        assert style_layers(cfg) == want, (cfg, style_layers(cfg))
    # A write: one layer off is stored as given; the alias becomes `style` and is never stored.
    s = put_draft(None, {**DEFAULTS, "style": {**ON, "typos": False}}, 0)
    assert s["draft"] == {**DEFAULTS, "style": {**ON, "typos": False}} and s["checkpoint"] == DEFAULTS, s
    s = put_draft(s, {**s["draft"], "text_style": "formal"}, 1)
    assert s["draft"] == FORMAL and "text_style" not in s["draft"], s["draft"]
    s = put_draft(s, {**s["draft"], "text_style": "girl"}, 2)
    assert s["draft"] == DEFAULTS, s["draft"]
    # Every side of an old stored blob (text_style only) reads as before; save / roll back keep the layers.
    old = {k: v for k, v in DEFAULTS.items() if k != "style"}
    got = merged({"checkpoint": {**old, "text_style": "formal"}, "previous": {**old, "text_style": "girl"},
                  "draft": {**old, "text_style": "formal", "gifs": True}, "rev": 9})
    assert (got["checkpoint"]["style"], got["previous"]["style"], got["draft"]["style"]) == (OFF, ON, OFF), got
    typo_off = put_draft(got, {**DEFAULTS, "style": {**ON, "typos": False}}, 9)
    saved = save(typo_off, 10)
    assert saved["checkpoint"]["style"] == {**ON, "typos": False} and saved["previous"]["style"] == OFF, saved
    assert rollback(saved, 11)["checkpoint"]["style"] == OFF


def case_folders_table():
    """(ticket 43) `folders: {include, exclude}`: refs `vf:<id>` / `of:<id>`; a malformed ref is
    refused by name; the default is empty = all folders; a stored v1 without `folders` reads all."""
    assert DEFAULTS["folders"] == {"include": [], "exclude": []}, DEFAULTS["folders"]
    for ok in ({"include": [], "exclude": []}, {"include": ["vf:12"], "exclude": []},
               {"include": ["vf:1", "of:987654321"], "exclude": ["vf:2"]},
               {"include": [], "exclude": ["of:5"]}):
        assert validate({**DEFAULTS, "folders": ok}) == [], (ok, validate({**DEFAULTS, "folders": ok}))
    refused = [  # (folders, a word the one error must carry: the bad ref or key by name)
        ({"include": ["vf:abc"], "exclude": []}, "'vf:abc'"),
        ({"include": ["vf:"], "exclude": []}, "'vf:'"),
        ({"include": ["12"], "exclude": []}, "'12'"),
        ({"include": ["xx:12"], "exclude": []}, "'xx:12'"),
        ({"include": [], "exclude": ["of:-3"]}, "'of:-3'"),
        ({"include": [], "exclude": ["vf:1 "]}, "'vf:1 '"),
        ({"include": [12], "exclude": []}, "12"),
        ({"include": "vf:1", "exclude": []}, "include"),
        ({"include": [], "exclude": None}, "exclude"),
        ({"include": [], "exclude": [], "only": ["vf:1"]}, "'only'"),
        ({"include": ["vf:3"]}, "['include']"),
        ({}, "got []"),
        (["vf:1"], "object"),
        (None, "object"),
    ]
    for folders, word in refused:
        errs = validate({**DEFAULTS, "folders": folders})
        assert len(errs) == 1 and errs[0].startswith("folders: ") and word in errs[0], (folders, errs)
    # Stored v1 from before 03b (no `folders`): both sides read all folders; unknown keys still refused.
    pre = {k: v for k, v in DEFAULTS.items() if k != "folders"}
    got = merged({"checkpoint": pre, "draft": {**pre, "sell_on": True}, "rev": 2})
    assert got["checkpoint"]["folders"] == got["draft"]["folders"] == {"include": [], "exclude": []}, got
    assert validate({**DEFAULTS, "fans_list": []}) == ["fans_list: unknown key"]
    # A draft PUT stores the side's folders as given, read per side.
    s = put_draft(None, {**DEFAULTS, "folders": {"include": ["vf:7"], "exclude": ["of:9"]}}, 0)
    assert s["draft"]["folders"] == {"include": ["vf:7"], "exclude": ["of:9"]}, s["draft"]
    assert s["checkpoint"]["folders"] == {"include": [], "exclude": []}, s["checkpoint"]
    assert _raises(Invalid, put_draft, None, {**DEFAULTS, "folders": {"include": ["vf:x"], "exclude": []}}, 0).errors == [
        "folders: bad ref 'vf:x' in include (want vf:<id> or of:<id>)"]


def case_draft_questions_table():
    """(ticket 47) `draft_questions`: the DRAFT gate's config half, a bool, on by default (owner 2026-11-14;
    test Mode only, so Shadow / live never read it)."""
    assert DEFAULTS["draft_questions"] is True, DEFAULTS
    assert REFERENCE["draft_questions"]["page"] == "Unasked offers", REFERENCE["draft_questions"]
    for ok in (True, False):
        assert validate({**DEFAULTS, "draft_questions": ok}) == [], ok
    for bad in ("yes", 1, 0, None, "true"):
        assert validate({**DEFAULTS, "draft_questions": bad}) == ["draft_questions: must be true or false"], bad
    # Stored v1 without `draft_questions`: every side reads the default (on).
    pre = {k: v for k, v in DEFAULTS.items() if k != "draft_questions"}
    got = merged({"checkpoint": pre, "previous": pre, "draft": {**pre, "sell_on": True}, "rev": 2})
    assert got["checkpoint"]["draft_questions"] is got["previous"]["draft_questions"] is True, got
    assert got["draft"]["draft_questions"] is True and got["draft"]["sell_on"] is True, got["draft"]
    # A draft PUT stores it per side.
    s = put_draft(None, {**DEFAULTS, "draft_questions": False}, 0)
    assert (s["draft"]["draft_questions"], s["checkpoint"]["draft_questions"]) == (False, True), s


def case_sell_spacing_table():
    """(03d ticket 59) `sell_spacing`: Spacing's JSON-only switch, a bool, on by default."""
    import assistant_full_ai
    assert DEFAULTS["sell_spacing"] is True, DEFAULTS
    for ok in (True, False):
        assert validate({**DEFAULTS, "sell_spacing": ok}) == [], ok
    for bad in ("yes", 1, 0, None, "true"):
        assert validate({**DEFAULTS, "sell_spacing": bad}) == ["sell_spacing: must be true or false"], bad
    assert assistant_full_ai.label("sell_spacing") == "Spacing"
    assert "sell_spacing" in assistant_full_ai.CONFIG_KEYS
    # Stored v1 from before 03d (no `sell_spacing`): every side reads the default.
    pre = {k: v for k, v in DEFAULTS.items() if k != "sell_spacing"}
    got = merged({"checkpoint": pre, "previous": pre, "draft": {**pre, "sell_on": True}, "rev": 2})
    assert got["checkpoint"]["sell_spacing"] is got["previous"]["sell_spacing"] is True, got
    assert got["draft"]["sell_spacing"] is True and got["draft"]["sell_on"] is True, got["draft"]


def case_sell_bundle_table():
    """(03d ticket 61) `sell_bundle`: "shoot" (today's Pick) or "fill" (up to 5, filled to 3), default fill."""
    import assistant_full_ai
    assert DEFAULTS["sell_bundle"] == "fill", DEFAULTS
    for ok in ("shoot", "fill"):
        assert validate({**DEFAULTS, "sell_bundle": ok}) == [], ok
    for bad in ("always", "", None, True, "Fill"):
        assert validate({**DEFAULTS, "sell_bundle": bad}) == ["sell_bundle: must be one of shoot, fill"], bad
    assert "sell_bundle" in assistant_full_ai.CONFIG_KEYS
    assert assistant_full_ai.label("sell_bundle") == "Fill the set"
    pre = {k: v for k, v in DEFAULTS.items() if k != "sell_bundle"}
    got = merged({"checkpoint": pre, "previous": pre, "draft": pre, "rev": 2})
    assert got["checkpoint"]["sell_bundle"] == got["previous"]["sell_bundle"] == got["draft"]["sell_bundle"] == "fill", got


def case_sell_count_strip_emojis_table():
    """`sell_count` (a fresh offer aims at the count he names) and `strip_emojis` (every Mode): page-switch bools."""
    import assistant_full_ai
    assert DEFAULTS["sell_count"] is True and DEFAULTS["strip_emojis"] is False, DEFAULTS
    for k, lab in (("sell_count", "Match his count"), ("strip_emojis", "Strip emojis")):
        for ok in (True, False):
            assert validate({**DEFAULTS, k: ok}) == [], (k, ok)
        for bad in ("yes", 1, 0, None, "true"):
            assert validate({**DEFAULTS, k: bad}) == [f"{k}: must be true or false"], (k, bad)
        assert assistant_full_ai.label(k) == lab and k in assistant_full_ai.CONFIG_KEYS, k
        assert REFERENCE[k]["page"] == lab, k
    pre = {k: v for k, v in DEFAULTS.items() if k not in ("sell_count", "strip_emojis")}
    got = merged({"checkpoint": pre, "previous": pre, "draft": pre, "rev": 2})
    for side in ("checkpoint", "previous", "draft"):
        assert got[side]["sell_count"] is True and got[side]["strip_emojis"] is False, got[side]


def case_typo_pct_table():
    """`typo_pct`: the chance (%) a reply gets one typo; null = the per-sentence rule."""
    import assistant_full_ai
    from automations.full_ai_writers import typo_rate
    assert DEFAULTS["typo_pct"] is None, DEFAULTS
    for ok in (None, 0, 1, 35, 100):
        assert validate({**DEFAULTS, "typo_pct": ok}) == [], ok
    for bad in (-1, 101, 2.5, 50.0, "30", True, False, [30]):
        assert validate({**DEFAULTS, "typo_pct": bad}) == [
            "typo_pct: must be a whole percent from 0 to 100, or null"], bad
    assert [typo_rate({**DEFAULTS, "typo_pct": p}) for p in (None, 0, 35, 100)] == [None, 0.0, 0.35, 1.0]
    assert typo_rate({}) is None
    assert "typo_pct" in assistant_full_ai.CONFIG_KEYS
    assert assistant_full_ai.label("typo_pct") == "Typos %"
    pre = {k: v for k, v in DEFAULTS.items() if k != "typo_pct"}
    got = merged({"checkpoint": pre, "previous": pre, "draft": {**pre, "typo_pct": 40}, "rev": 2})
    assert got["checkpoint"]["typo_pct"] is got["previous"]["typo_pct"] is None, got
    assert got["draft"]["typo_pct"] == 40, got["draft"]


def case_gif_pct_table():
    """`gif_pct`: the chance (%) a Turn offers the sticker block while GIFs is on; null = every Turn."""
    import assistant_full_ai
    assert DEFAULTS["gif_pct"] is None, DEFAULTS
    for ok in (None, 0, 1, 50, 100):
        assert validate({**DEFAULTS, "gif_pct": ok}) == [], ok
    for bad in (-1, 101, 2.5, 50.0, "30", True, False, [30]):
        assert validate({**DEFAULTS, "gif_pct": bad}) == [
            "gif_pct: must be a whole percent from 0 to 100, or null"], bad
    assert "gif_pct" in assistant_full_ai.CONFIG_KEYS
    assert assistant_full_ai.label("gif_pct") == "GIFs %"
    pre = {k: v for k, v in DEFAULTS.items() if k != "gif_pct"}
    got = merged({"checkpoint": pre, "previous": pre, "draft": {**pre, "gif_pct": 25}, "rev": 2})
    assert got["checkpoint"]["gif_pct"] is got["previous"]["gif_pct"] is None, got
    assert got["draft"]["gif_pct"] == 25, got["draft"]


def case_top_spend_cents_table():
    """`top_spend_cents` (04b ticket 75): a Fan at or over it is left to humans; 0 = off."""
    import assistant_full_ai
    assert DEFAULTS["top_spend_cents"] == 100000, DEFAULTS
    for ok in (0, 1, 100000, 10**9):
        assert validate({**DEFAULTS, "top_spend_cents": ok}) == [], ok
    for bad in (-1, 2.5, 100.0, "100", True, False, None, [1]):
        assert validate({**DEFAULTS, "top_spend_cents": bad}) == [
            "top_spend_cents: must be a whole number of cents, 0 or more (0 = off)"], bad
    assert "top_spend_cents" not in assistant_full_ai.CONFIG_KEYS     # its own write (`put_audience`)
    assert assistant_full_ai.label("top_spend_cents") == "Top spend limit"
    assert REFERENCE["top_spend_cents"]["page"] == "Top spend limit"      # the page's dollars box
    pre = {k: v for k, v in DEFAULTS.items() if k != "top_spend_cents"}
    got = merged({"checkpoint": pre, "previous": pre, "draft": {**pre, "top_spend_cents": 0}, "rev": 2})
    # Every side reads the checkpoint's (an audience key: one value everywhere).
    assert got["checkpoint"]["top_spend_cents"] == got["previous"]["top_spend_cents"] == 100000, got
    assert got["draft"]["top_spend_cents"] == 100000, got["draft"]
    assert merged(None)["checkpoint"]["top_spend_cents"] == 100000


def case_fans_table():
    """`fans` (04b ticket 76): the Fans list, shaped like `folders` but OF list ids."""
    import assistant_full_ai
    assert DEFAULTS["fans"] == {"include": [], "exclude": []}, DEFAULTS
    for ok in ({"include": [], "exclude": []}, {"include": [1, 2], "exclude": []}, {"include": [], "exclude": [9]},
               {"include": [5], "exclude": [5]}):
        assert validate({**DEFAULTS, "fans": ok}) == [], ok
    for bad in ("all", [], None, {"include": []}, {"include": [], "exclude": [], "x": []},
                {"include": "1", "exclude": []}, {"include": [], "exclude": None},
                {"include": ["1"], "exclude": []}, {"include": [1.0], "exclude": []}, {"include": [True], "exclude": []},
                {"include": [0], "exclude": []}, {"include": [], "exclude": [-3]}, {"include": [4, 4], "exclude": []}):
        errs = validate({**DEFAULTS, "fans": bad})
        assert len(errs) == 1 and errs[0].startswith("fans: "), (bad, errs)
    assert "fans" not in assistant_full_ai.CONFIG_KEYS     # its own write (`put_audience`)
    assert assistant_full_ai.label("fans") == "Fans"
    assert REFERENCE["fans"]["page"] == "Fans"      # the page's Fans dialog
    pre = {k: v for k, v in DEFAULTS.items() if k != "fans"}
    got = merged({"checkpoint": pre, "previous": pre, "draft": {**pre, "fans": {"include": [3], "exclude": []}},
                  "rev": 2})
    # Every side reads the checkpoint's list (an audience key: one value everywhere).
    assert got["checkpoint"]["fans"] == got["previous"]["fans"] == got["draft"]["fans"] == {
        "include": [], "exclude": []}, got


def case_audience_keys_carried_table():
    """(owner 2026-11-15) `fans` and `top_spend_cents` say who live answers, not how the AI behaves: put_draft /
    put_checkpoint (the JSON boxes included) / save / rollback keep the stored values whatever their body says;
    put_audience sets the given keys on all three sides at once (no rev), validates, refuses another key."""
    aud = {"fans": {"include": [7], "exclude": [8]}, "top_spend_cents": 5000}
    s0 = put_audience(put_draft(None, {"gifs": True}, 0), aud)
    assert s0["rev"] == 2 and s0["previous"] is None, s0
    assert all({k: s0[side][k] for k in aud} == aud for side in ("checkpoint", "draft")), s0
    assert s0["draft"]["gifs"] is True and s0["checkpoint"]["gifs"] is False, s0      # nothing else moved
    other = {"fans": {"include": [], "exclude": []}, "top_spend_cents": 0}
    d = put_draft(s0, {**DEFAULTS, "gifs": True, "reply_speed": "0-15-60", **other}, 2)   # a body naming other values
    assert {k: d["draft"][k] for k in aud} == aud, d["draft"]
    sv = save(d, 3)
    assert all({k: sv[side][k] for k in aud} == aud for side in ("checkpoint", "previous", "draft")), sv
    c = put_checkpoint(sv, {**DEFAULTS, "sell_on": True, **other}, 4)
    assert {k: c["checkpoint"][k] for k in aud} == aud and c["checkpoint"]["sell_on"] is True, c
    # A body only changing an audience key is unchanged, not a new checkpoint.
    assert _raises(Invalid, put_checkpoint, c, {**c["checkpoint"], **other}, 5).errors == [
        "Live settings: no change, nothing to save"]
    rb = rollback(c, 5)
    assert all({k: rb[side][k] for k in aud} == aud for side in ("checkpoint", "previous", "draft")), rb
    # Set later, then roll back: the new value holds on every side.
    a2 = put_audience(rb, {"top_spend_cents": 0})
    assert all(a2[side]["top_spend_cents"] == 0 and a2[side]["fans"] == aud["fans"]
               for side in ("checkpoint", "previous", "draft")) and a2["rev"] == 7, a2
    assert all(rollback(a2, 7)[side]["top_spend_cents"] == 0 for side in ("checkpoint", "previous", "draft"))
    # A JSON body's bad audience value is ignored like any other value of them; put_audience validates.
    assert put_draft(a2, {**DEFAULTS, "fans": "all", "top_spend_cents": -1}, 7)["draft"]["fans"] == aud["fans"]
    assert _raises(Invalid, put_audience, a2, {"fans": {"include": [0], "exclude": []}}).errors[0].startswith("fans: ")
    assert _raises(Invalid, put_audience, a2, {"top_spend_cents": -1}).errors == [
        "top_spend_cents: must be a whole number of cents, 0 or more (0 = off)"]
    assert _raises(Invalid, put_audience, a2, {"gifs": True}).errors == ["gifs: not an audience key"]
    assert _raises(Invalid, put_audience, a2, {}).errors
    before = copy.deepcopy(a2)
    put_audience(a2, aud)
    assert a2 == before                                                 # pure


def case_catchup_minutes_table():
    """`catchup_minutes` (owner 2026-11-15): the catch-up's passes after Live, then every N minutes; JSON-only."""
    import assistant_full_ai
    assert DEFAULTS["catchup_minutes"] == {"after_live": [0, 5, 15], "then_every": 15}, DEFAULTS
    for ok in ({"after_live": [0], "then_every": 5}, {"after_live": [2, 7], "then_every": 1440},
               {"after_live": [0, 1, 2, 3, 4, 1440], "then_every": 60}):
        assert validate({**DEFAULTS, "catchup_minutes": ok}) == [], ok
    for bad in (None, [], "25", {"after_live": [0, 5]}, {"after_live": [0], "then_every": 25, "x": 1},
                {"after_live": [], "then_every": 25}, {"after_live": [0, 1, 2, 3, 4, 5, 6], "then_every": 25},
                {"after_live": [5, 0], "then_every": 25}, {"after_live": [0, 0], "then_every": 25},
                {"after_live": [-1], "then_every": 25}, {"after_live": [0, 1441], "then_every": 25},
                {"after_live": [0, 2.5], "then_every": 25}, {"after_live": [True], "then_every": 25},
                {"after_live": "0", "then_every": 25}, {"after_live": [0], "then_every": 4},
                {"after_live": [0], "then_every": 1441}, {"after_live": [0], "then_every": 25.0},
                {"after_live": [0], "then_every": None}):
        errs = validate({**DEFAULTS, "catchup_minutes": bad})
        assert len(errs) == 1 and errs[0].startswith("catchup_minutes: "), (bad, errs)
    assert "catchup_minutes" in assistant_full_ai.CONFIG_KEYS
    assert assistant_full_ai.label("catchup_minutes") == "Catch-up passes (min)"
    assert REFERENCE["catchup_minutes"]["page"] is None       # JSON only
    pre = {k: v for k, v in DEFAULTS.items() if k != "catchup_minutes"}
    got = merged({"checkpoint": pre, "previous": None, "draft": pre, "rev": 1})
    assert got["checkpoint"]["catchup_minutes"] == got["draft"]["catchup_minutes"] == DEFAULTS["catchup_minutes"]


# ── Transitions ───────────────────────────────────────────────────────

def _raises(exc, fn, *a):
    try:
        fn(*a)
    except exc as e:
        return e
    raise AssertionError(f"{fn.__name__}{a!r} did not raise {exc.__name__}")


def case_transitions_and_stale_rev():
    formal = FORMAL
    s1 = put_draft(None, FORMAL_IN, 0)
    assert s1 == {"checkpoint": DEFAULTS, "previous": None, "draft": formal, "rev": 1}, s1
    # A partial draft is stored filled from DEFAULTS.
    assert put_draft(None, {"gifs": True}, 0)["draft"] == {**DEFAULTS, "gifs": True}
    assert _raises(StaleRev, put_draft, s1, DEFAULTS, 0).rev == 1
    # A stale rev answers before field errors (rwl fa3 N2): 409, not 422.
    assert _raises(StaleRev, put_draft, s1, {**DEFAULTS, "sell_on": "yes"}, 0).rev == 1
    assert _raises(Invalid, put_draft, s1, {**DEFAULTS, "sell_on": "yes"}, 1).errors == [
        "sell_on: must be true or false"]
    # 03b: selling is settable on the draft alone; the checkpoint keeps its own (off) value.
    sold = put_draft(s1, {**formal, "sell_on": True}, 1)
    assert sold["draft"]["sell_on"] is True and sold["checkpoint"]["sell_on"] is False, sold
    s2 = save(s1, 1)
    assert s2 == {"checkpoint": formal, "previous": DEFAULTS, "draft": formal, "rev": 2}, s2
    assert _raises(StaleRev, save, s1, 0).rev == 1
    assert _raises(Invalid, save, s2, 2).errors == ["Draft is the same as the Live settings: nothing to make live"]
    s3 = rollback(s2, 2)
    assert s3 == {"checkpoint": DEFAULTS, "previous": formal, "draft": formal, "rev": 3}, s3
    s4 = rollback(s3, 3)
    assert {k: s4[k] for k in ("checkpoint", "previous", "draft")} == {
        k: s2[k] for k in ("checkpoint", "previous", "draft")} and s4["rev"] == 4, s4
    assert _raises(StaleRev, rollback, s3, 2).rev == 3
    assert _raises(Invalid, rollback, s1, 1).errors == ["previous: nothing to roll back to"]
    # The checkpoint JSON typed in: the old one becomes `previous` (Roll back undoes it), the draft stays.
    c1 = put_checkpoint(s1, {"gifs": True}, 1)
    assert c1 == {"checkpoint": {**DEFAULTS, "gifs": True}, "previous": DEFAULTS, "draft": formal, "rev": 2}, c1
    assert rollback(c1, 2)["checkpoint"] == DEFAULTS
    assert _raises(StaleRev, put_checkpoint, s1, DEFAULTS, 0).rev == 1
    assert _raises(Invalid, put_checkpoint, s1, {"writers": []}, 1).errors == ["writers: needs 1 to 6 Writers"]
    assert _raises(Invalid, put_checkpoint, s1, DEFAULTS, 1).errors == ["Live settings: no change, nothing to save"]
    # Pure: the inputs are untouched.
    before = copy.deepcopy(s2)
    save(put_draft(s2, DEFAULTS, 2), 3)
    assert s2 == before


# ── The config API ────────────────────────────────────────────────────

IDS = fx.seed_two_agencies()
A = IDS["creator_a"]
OWNER_A = fx.login_owner("agency_a_owner")
CONFIG = "/admin/full-ai/config"
REF = json.loads(json.dumps(reference()))     # as the wire carries it
LIMITS = {"max_writers": 6, "reply_speeds": ["0-2m", "0-15-60"], "default_reply_speed": "0-2m",
          "info_questions": ["pick", "list"], "caption_writers": ["chat", "caption"]}


def _db(fn):
    return asyncio.run(fn())


async def _seed_rule() -> None:
    async with get_session() as s:
        s.add(AutomationRule(account_id=A, name="Full AI Chat", kind="full_ai_chat",
                             trigger_json=json.dumps({"every_seconds": 86400}), steps_json="{}",
                             is_enabled=True))


_db(_seed_rule)


def _rule_row() -> list[tuple]:
    async def go():
        async with get_session() as s:
            return [tuple(r) for r in (await s.execute(text(
                "SELECT * FROM automation_rules WHERE account_id = :a AND kind = 'full_ai_chat'"),
                {"a": A})).all()]
    return _db(go)


def case_config_api_round_trip():
    rule = _rule_row()
    assert len(rule) == 1, rule
    got = OWNER_A.get(CONFIG, params={"account_id": A})
    assert got.status_code == 200, got.text
    assert got.json().pop("owner_keys") == {p: {"set": False} for p in {*WRITER_PROVIDERS_OF.values(), "deepinfra"}}
    got_body = {k: v for k, v in got.json().items() if k != "owner_keys"}
    assert got_body == {"checkpoint": DEFAULTS, "previous": None, "draft": DEFAULTS, "rev": 0,
                          "errors": [], "writer_models": WRITER_MODELS, "writer_providers": WRITER_PROVIDERS_OF, "provider_labels": PROVIDER_LABELS, "reference": REF,
                          "limits": LIMITS}, got_body
    formal = FORMAL_IN
    bad = OWNER_A.put(f"{CONFIG}/draft", json={"account_id": A, "draft": {**formal, "fans_list": []},
                                               "rev": 0})
    assert bad.status_code == 422 and bad.json() == {"errors": ["fans_list: unknown key"]}, bad.text
    fast = OWNER_A.put(f"{CONFIG}/draft", json={"account_id": A, "draft": {
        **formal, "catchup_minutes": {"after_live": [0, 5], "then_every": 1}}, "rev": 0})
    assert fast.status_code == 422 and fast.json() == {"errors": [
        "catchup_minutes: then_every must be whole minutes from 5 to 1440"]}, fast.text
    stale = OWNER_A.put(f"{CONFIG}/draft", json={"account_id": A, "draft": formal, "rev": 7})
    assert stale.status_code == 409 and stale.json()["rev"] == 0, stale.text
    ok = OWNER_A.put(f"{CONFIG}/draft", json={"account_id": A, "draft": formal, "rev": 0})
    assert ok.status_code == 200, ok.text
    formal = FORMAL                                 # stored as the layers
    assert ok.json() == {"checkpoint": DEFAULTS, "previous": None, "draft": formal, "rev": 1,
                         "errors": [], "writer_models": WRITER_MODELS, "writer_providers": WRITER_PROVIDERS_OF, "provider_labels": PROVIDER_LABELS, "reference": REF,
                         "limits": LIMITS}, ok.json()
    # The same request again is stale: someone (this tab) stored meanwhile.
    again = OWNER_A.put(f"{CONFIG}/draft", json={"account_id": A, "draft": formal, "rev": 0})
    assert again.status_code == 409 and again.json()["rev"] == 1, again.text
    saved = OWNER_A.post(f"{CONFIG}/save", json={"account_id": A, "rev": 1})
    assert saved.status_code == 200, saved.text
    after_save = saved.json()
    assert after_save == {"checkpoint": formal, "previous": DEFAULTS, "draft": formal, "rev": 2,
                          "errors": [], "writer_models": WRITER_MODELS, "writer_providers": WRITER_PROVIDERS_OF, "provider_labels": PROVIDER_LABELS, "reference": REF,
                          "limits": LIMITS}, after_save
    assert _rule_row() == rule
    assert OWNER_A.post(f"{CONFIG}/save", json={"account_id": A, "rev": 1}).status_code == 409
    nothing = OWNER_A.post(f"{CONFIG}/save", json={"account_id": A, "rev": 2})
    assert nothing.status_code == 422 and nothing.json() == {
        "errors": ["Draft is the same as the Live settings: nothing to make live"]}, nothing.text
    back = OWNER_A.post(f"{CONFIG}/rollback", json={"account_id": A, "rev": 2})
    assert back.status_code == 200, back.text
    assert (back.json()["checkpoint"], back.json()["previous"], back.json()["rev"]) == (
        DEFAULTS, formal, 3), back.json()
    assert _rule_row() == rule
    forth = OWNER_A.post(f"{CONFIG}/rollback", json={"account_id": A, "rev": 3})
    assert forth.status_code == 200, forth.text
    assert {**forth.json(), "rev": 2} == after_save and forth.json()["rev"] == 4, forth.json()
    assert _rule_row() == rule
    final = OWNER_A.get(CONFIG, params={"account_id": A}).json()
    assert "owner_keys" not in forth.json() and {k: v for k, v in final.items() if k != "owner_keys"} == forth.json()



def case_config_get_owner_keys():
    """rwl2 L5: the GET's `owner_keys` reads the Creator's billing owner's keys (the Live blocker's policy), booleans
    only; the write answers carry none."""
    import tenant_keys
    owner = IDS["agency_a_owner"]

    async def keys(v):
        await tenant_keys.set_keys(owner, {"nanogpt": v, "deepinfra": v})
    _db(lambda: keys("sk-test-l5-secret"))
    try:
        got = OWNER_A.get(CONFIG, params={"account_id": A})
        assert got.status_code == 200, got.text
        ok = got.json()["owner_keys"]
        assert ok["nanogpt"] == ok["deepinfra"] == {"set": True} and ok["openrouter"] == {"set": False}, ok
        assert "sk-test-l5-secret" not in got.text and "l5-s" not in got.text
    finally:
        _db(lambda: keys(None))
    assert OWNER_A.get(CONFIG, params={"account_id": A}).json()["owner_keys"]["nanogpt"] == {"set": False}


def case_config_api_audience():
    """PUT config/audience: no rev, sets the given keys on all three sides, bumps rev (the next draft PUT on it is not
    stale); 422 on a bad value or another key; a draft PUT naming other audience values keeps the stored ones."""
    cur = OWNER_A.get(CONFIG, params={"account_id": A}).json()
    r = OWNER_A.put(f"{CONFIG}/audience", json={"account_id": A, "fans": {"include": [5], "exclude": []}})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["rev"] == cur["rev"] + 1, got
    sides = [got["checkpoint"], got["draft"]] + ([got["previous"]] if got["previous"] else [])
    assert all(x["fans"] == {"include": [5], "exclude": []} for x in sides), got
    assert all(x["top_spend_cents"] == cur["checkpoint"]["top_spend_cents"] for x in sides), got
    t = OWNER_A.put(f"{CONFIG}/audience", json={"account_id": A, "top_spend_cents": 2500})
    assert t.status_code == 200 and t.json()["draft"]["top_spend_cents"] == 2500, t.text
    assert t.json()["draft"]["fans"] == {"include": [5], "exclude": []}, t.json()
    d = OWNER_A.put(f"{CONFIG}/draft", json={"account_id": A, "rev": t.json()["rev"], "draft": {
        **t.json()["draft"], "gifs": True, "fans": {"include": [], "exclude": []}, "top_spend_cents": 0}})
    assert d.status_code == 200, d.text
    assert (d.json()["draft"]["gifs"], d.json()["draft"]["fans"], d.json()["draft"]["top_spend_cents"]) == (
        True, {"include": [5], "exclude": []}, 2500), d.json()["draft"]
    for bad in ({"top_spend_cents": "5"}, {"fans": {"include": [0], "exclude": []}}, {}):
        b = OWNER_A.put(f"{CONFIG}/audience", json={"account_id": A, **bad})
        assert b.status_code == 422 and b.json()["errors"], (bad, b.text)
    assert OWNER_A.put(f"{CONFIG}/audience", json={"account_id": A, "gifs": True}).status_code == 422


if __name__ == "__main__":
    _harness.run()
