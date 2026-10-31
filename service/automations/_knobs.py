"""Env + rule-payload knob readers: test_mode, bool_knob, coerce_ids."""
from __future__ import annotations

import os


# ── Rule-payload knobs: the ONE boolean reader ───────────────────────────────
# Lives here, and not next to any one automation, because the knobs it guards
# are read from several modules (auto_follow, auto_stories, nudge_online,
# nudge_online_fire, promo_reactivate, send_welcome) and the
# defect it exists to prevent is exactly the one that appears when each module
# writes the read itself. Most of them already imported from `_common` (`load_hard_skip_ids`, `load_voice_blocks`,
# `build_facts_note`, …); `auto_stories` and `promo_reactivate` did NOT, and this
# gave them their first `_common` edge. An earlier version of this comment said
# it cost "no new edge" — it costs two, both to the module every automation
# already depends on transitively, which is a price worth naming rather than
# denying.
#
# ⚠️ SCOPE: automation RULE PAYLOADS, the store where a `null` USED to survive.
# The boundary now POPS a null for a catalogued knob instead of skipping it
# (`automation_rules_api._validate_payload_for_kind`, pinned by
# `test_automation_rules_api.case_a_null_for_a_catalogued_knob_is_dropped_at_the_boundary`),
# so nothing NEW can store one. The null clause below is therefore a defence
# against HISTORY — rules written before that line still carry stored nulls —
# and it stays pinned by
# `test_automation_rules_api.case_every_catalogued_bool_honours_its_default`.
#
# It is NOT closed for `account_ai_config.style_config_json`, which still holds
# four hand-rolled bool reads: `load_painful_texting_flag`,
# `load_cat_stickers_flag` and `load_factground_flag` in _style_flags.py, and
# `cat_stickers.load_cat_sticker_config` (cat_stickers.py, the `cat_stickers`
# key). They were left alone deliberately, not missed — but NOT because a `null`
# is impossible there. An earlier version of this comment said it "cannot reach
# storage for a style flag at all", and that is false. It cannot arrive through
# the style-config API — `style_config_api._persist` coerces with
# `{k: bool(v) …}` before writing — but a row written by an older build (the
# retired settings IMPORT path wrote `style_config_json` verbatim, no bool
# coercion) can still carry `"factground_…": null`, and `load_factground_flag`'s `bool(stored.get(KEY, True))` then
# reads it False while its docstring says True.
# The DECISION still stands: closing it means converting the whole style-flag
# family (`load_style_flags`, `load_typo_flags`, `load_nonnative_flags`,
# `load_spacing_flags`, `load_consistency_flags`, …) — a dozen sibling loaders no
# round of this review has read — so it is its own change with its own review,
# and it is a hand-edited-import hazard rather than an unreachable one.

def test_mode() -> bool:
    """Are we running under the test harness? THE one parse of
    `CHATTERLY_TEST_MODE` — every reader goes through here.

    ⚠️ PARSED, not just "is the variable set". `CHATTERLY_TEST_MODE=0` is a thing
    a person types when they mean "no", and a bare truthiness test on the string
    makes it mean "yes" — which zeroes typing time in one module while another
    decides it is production and defaults its knobs ON."""
    v = (os.environ.get("CHATTERLY_TEST_MODE") or "").strip().lower()
    return v not in ("", "0", "false", "no", "off")


def bool_knob(payload: dict | None, key: str, default: bool) -> bool:
    """A boolean payload knob whose read-default is shared by ABSENT and `null`.

    ⚠️ THIS IS THE ONLY CORRECT WAY TO READ A `type: "bool"` KNOB. The two
    spellings that look like it are both wrong for a value the API actually
    stores:

        bool(payload.get(k, True))   # `null` → False. `.get` FOUND the key, so
                                     # the default never applied.
        payload.get(k, True)         # `null` → None → falsy, same hole, and it
                                     # does not even return a bool.

    `_validate_payload_for_kind` (automation_rules_api) used to SKIP a None
    value instead of rejecting it, which made `null` the one non-boolean that
    reached storage for a catalogued bool. That boundary now POPS the key, so no
    NEW rule can store one — the null clause here defends rules written before
    that line, and stored nulls do not expire. Every surface that reads "absent
    or null ⇒ the declared default" — the catalog, BrainPanel, RuleEditor — must
    still agree with the automation about what such a rule does. On `money_gate`
    and `follow_back_gate` that disagreement SPENDS MONEY; on `dry_run` it turns
    a "plans only, nothing sent" toast into real sends.

    A key that is present-but-null says nothing, so it means what absent means.

    Pinned for every catalogued bool, in every kind, by
    `test_automation_rules_api.case_every_catalogued_bool_honours_its_default`.
    """
    v = (payload or {}).get(key)
    return default if v is None else bool(v)


def coerce_ids(raw: object) -> set[int]:
    """Payload id-list → set[int], dropping (not raising on) non-numeric entries.

    Payload values are JSON/operator-supplied; one bad `force_ids` entry must
    never abort the whole automation run.
    """
    out: set[int] = set()
    if not isinstance(raw, (list, tuple, set)):
        return out
    for x in raw:
        try:
            out.add(int(x))
        except (TypeError, ValueError):
            continue
    return out
