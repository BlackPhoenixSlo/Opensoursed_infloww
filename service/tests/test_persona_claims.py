#!/usr/bin/env python3
"""test_persona_claims.py — TIER B: the per-fan record of what SHE told HIM.

Canon (persona_facts_json) answers "who is she" once for all 8,050 fans. This is
the other half: what she actually SAID to ONE fan, stored ONLY where it deviates
from canon or covers something canon didn't.

Why it can't be canon-only: a claim already made cannot be retracted. Measured on
prod, one 966-turn thread went "no soy chilena, soy argentina de verdad" → "y sí,
estoy acá en Chile" → "en córdoba", and the fan closed with "ya no creo nada".
Correcting that fan back to Argentina mid-thread lands as the lie, not the fix.

  case_self_claim_prefilter:
      the COST GATE. Fires on her stating something about herself (EN + ES),
      stays quiet on ordinary chat and on the FAN's own claims.
  case_extract_gate_uses_the_prefilter:
      a saturated fan profile no longer kills the extract outright — but it only
      re-fires when she demonstrably made a claim, so the ~43%-of-lane saving the
      cost audit won is not handed back.
  case_merge_is_latest_wins_and_capped:
      LATEST-WINS per topic (unlike the fan-side fill-empty-only), capped, and
      the cap drops the STALEST topic.
  case_merge_is_idempotent:
      re-recording the same claim rewrites rather than grows — the executor
      re-runs its whole candidate loop on job retry, so capture must survive it.
  case_claims_block_renders_and_is_empty_by_default:
      "" for a fan with no deviations (most fans) ⇒ byte-identical prompt.
  case_claims_reach_the_engine:
      welcome_chatter_for_info injects it, in the USER message.
  case_parse_is_defensive:
      bad JSON never raises into a send path.

Run: ./venv/bin/python service/tests/test_persona_claims.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

# These cases test feature logic, not the account gate (that is
# test_account_isolation_gate's job). They reach `/admin` routes or
# `assert_account_owned` with no session, which fails closed (401) since
# 3b30b486. This is the documented escape hatch (read per call), scoped to this
# test process.
import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import json  # noqa: E402

from db.models import Fan  # noqa: E402
from automations import welcome_chatter_for_info  # noqa: E402
from automations._persona import (  # noqa: E402
    _column_for_topic, claims_to_scalars, mentions_self_claim, merge_persona_claims,
    parse_persona_claims, persona_claims_block,
)

_MARK = "YOU HAVE ALREADY TOLD HIM"


def _mk_of_candidate(fan_id, msgs):
    c = welcome_chatter_for_info._Candidate(fan_id)
    c.messages = list(msgs)
    c.last_body = msgs[-1][1] if msgs else ""
    return c


# ── the cost gate ─────────────────────────────────────────────────────

def case_self_claim_prefilter():
    """Deterministic, because it decides whether an LLM call is worth its money —
    it must not itself cost one."""
    # Real lines she sent, from the Ellafree transcripts.
    for claim in ("crecí acá en argentina, una infancia bastante normal",
                  "estoy en argentina",
                  "tengo 22 anos",
                  "vivo en cordoba sola",
                  "nope i'm 22 actually",
                  "yeah I am 49",
                  "i grew up on the island",
                  "my ex was a nightmare",
                  "i live alone babe",
                  "my dog Luna keeps me company",
                  "i was born in rosario",
                  "me llamo Sarah",
                  "mi tatuaje dice algo cursi jaja",
                  "i work as a bartender on weekends"):
        assert mentions_self_claim(claim), f"MISSED a claim: {claim!r}"

    # Ordinary chat must NOT fire — every false positive is a wasted extract.
    for chatter in ("jaja siempre tan cuidado con lo que decís",
                    "hey what are you up to tonight",
                    "you're sweet 😏",
                    "how was your day babe",
                    "lo que me contaste ayer me hizo reír",
                    "", None):
        assert not mentions_self_claim(chatter), f"FALSE POSITIVE: {chatter!r}"


def case_extract_gate_uses_the_prefilter():
    """A saturated FAN profile used to kill the extract outright — which is exactly
    the deep-thread moment her own claims start mattering. It now re-fires, but
    only on a turn where she actually said something."""
    saturated = Fan(account_id="a", fan_id=1, real_name="JH", his_age="27",
                    home_country="Mexico", home_city="Cancun", hobbies="beer",
                    occupation="builder", fetishes="ass",
                    recent_events='["went drinking"]')

    quiet = _mk_of_candidate(1, [("in", "hola"), ("out", "jaja hola vos")])
    assert welcome_chatter_for_info._extract_worthwhile(saturated, quiet) is False, \
        "saturated + no claim must stay skipped — that is the cost saving"

    spoke = _mk_of_candidate(1, [("in", "de donde sos?"),
                                 ("out", "crecí acá en argentina con mis primos")])
    assert welcome_chatter_for_info._extract_worthwhile(saturated, spoke) is True, \
        "saturated + she made a claim must extract"

    # Only HER side counts. The fan saying "i grew up in texas" is a FAN fact and
    # is already covered by the fan-side gate; it must not re-open the call.
    fan_only = _mk_of_candidate(1, [("in", "i grew up in texas and i live alone")])
    assert welcome_chatter_for_info._extract_worthwhile(saturated, fan_only) is False, \
        "the FAN's own claims must not trigger the creator-claims extract"

    # An UNsaturated profile still extracts regardless — unchanged behaviour.
    empty = Fan(account_id="a", fan_id=2)
    assert welcome_chatter_for_info._extract_worthwhile(empty, quiet) is True


# ── merge semantics ───────────────────────────────────────────────────

def case_merge_is_latest_wins_and_capped():
    """LATEST-WINS, unlike the fan-side fill-empty-only. First-wins would freeze a
    bad first extraction forever and stop a canon edit ever propagating."""
    prior = [{"topic": "hometown", "claim": "soy argentina", "at": "2026-07-25T00:12:24"}]
    newer = [{"topic": "hometown", "claim": "estoy acá en Chile"}]
    merged = merge_persona_claims(prior, newer, now_iso="2026-07-25T01:31:08")
    assert len(merged) == 1, merged
    assert merged[0]["claim"] == "estoy acá en Chile", merged

    # Cap drops the STALEST topic, not the newest.
    many = [{"topic": f"t{i}", "claim": f"c{i}", "at": f"2026-07-25T00:00:{i:02d}"}
            for i in range(30)]
    capped = merge_persona_claims([], many, now_iso="x")
    assert len(capped) == 20, len(capped)
    assert capped[-1]["topic"] == "t29", capped[-1]
    assert "t0" not in [c["topic"] for c in capped], "stalest must be dropped"


def case_merge_is_idempotent():
    """The executor flips a failed job back to pending and re-runs its whole
    candidate loop, so the same claim WILL be captured twice. Re-recording must
    rewrite the row, never grow the list."""
    claims = [{"topic": "hometown", "claim": "soy de rosario"}]
    once = merge_persona_claims(None, claims, now_iso="2026-07-25T10:00:00")
    twice = merge_persona_claims(once, claims, now_iso="2026-07-25T10:00:00")
    thrice = merge_persona_claims(twice, claims, now_iso="2026-07-25T10:00:00")
    assert once == twice == thrice, (once, twice, thrice)
    assert len(thrice) == 1


def case_parse_is_defensive():
    """Anything unparseable collapses to [] — this runs inside a send path."""
    for junk in (None, "", "not json", "{}", '"a string"', "[1,2,3]",
                 '[{"topic":"x"}]', '[{"claim":"y"}]', 42):
        assert parse_persona_claims(junk) == [], repr(junk)
    good = parse_persona_claims('[{"topic":"hometown","claim":"rosario","at":"t"}]')
    assert good == [{"topic": "hometown", "claim": "rosario", "at": "t"}], good


# ── rendering + wiring ────────────────────────────────────────────────

def case_claims_block_renders_and_is_empty_by_default():
    for blank in (None, "", "[]", "junk"):
        assert persona_claims_block(blank) == "", repr(blank)

    # A topic with no scalar of its own renders as itself.
    block = persona_claims_block(
        '[{"topic":"upbringing","claim":"crecí en argentina con mis primos"}]',
        age_claimed="22")
    assert _MARK in block, block
    assert "- your age: 22" in block, block
    assert "- upbringing: crecí en argentina con mis primos" in block, block
    # Imperative, not a passive inventory — the passive fan-facts list is the one
    # the model demonstrably ignores.
    assert "NEVER give him a different version" in block, block

    # A set scalar OVERRIDES its topic: exactly one line, under the scalar's label.
    # (Before the override rule this printed "where you are: en córdoba" directly
    # above "hometown: en córdoba" — caught live replaying the real Chile cascade.)
    dup = persona_claims_block(
        '[{"topic":"hometown","claim":"en c\u00f3rdoba, cora"}]',
        location_claimed="en c\u00f3rdoba, cora")
    assert dup.count("cora") == 1, dup
    assert "- hometown:" not in dup, dup

    # An operator hand-PATCHing a scalar the extractor never wrote still renders.
    solo = persona_claims_block('[{"topic":"her dog","claim":"Luna"}]',
                                location_claimed="buenos aires")
    assert "- where you are: buenos aires" in solo, solo
    assert "- her dog: Luna" in solo, solo


def case_claims_reach_the_engine():
    f = Fan(account_id="a", fan_id=3, of_display_name="JH",
            persona_claims_json='[{"topic":"hometown","claim":"crecí en argentina"}]',
            persona_age_claimed="22")
    msgs = [("in", "y donde creciste?")]

    of_m, _ = welcome_chatter_for_info._build_messages("p", f, _mk_of_candidate(3, msgs), set())
    for name, m in (("welcome_chatter_for_info", of_m),):
        user = m[1]["content"]
        assert _MARK in user, f"{name}: claims block missing"
        assert "crecí en argentina" in user, f"{name}: claim text missing"
        assert _MARK not in m[0]["content"], (
            f"{name}: claims belong in the USER message — the system prompt is "
            "prefix-cached and a per-fan block there fragments it")

    # A fan with NO deviations — most fans once canon is filled — is byte-clean.
    plain = Fan(account_id="a", fan_id=4, of_display_name="JH")
    of_n, _ = welcome_chatter_for_info._build_messages("p", plain, _mk_of_candidate(4, msgs), set())
    assert _MARK not in of_n[1]["content"], "no-deviation fan must be unchanged"


def case_extract_prompt_asks_for_deviations_only():
    """Handing the extractor canon is what keeps the ledger small. Without it every
    line she says looks novel and the ledger fills with noise canon already
    answers — which is what makes 'most fans stay empty' true."""
    sys_prompt = welcome_chatter_for_info._EXTRACT_SYSTEM
    assert "her_claims" in sys_prompt
    assert "DEVIATIONS-ONLY" in sys_prompt, "must be deviations-only, not a transcript"
    assert "empty list" in sys_prompt, "an empty list must be the expected answer"

    f = Fan(account_id="a", fan_id=5, of_display_name="JH")
    msgs = welcome_chatter_for_info._extract_messages(f, _mk_of_candidate(5, [("in", "hi")]),
                                        persona="Ella, 22, from Rosario.")
    assert "HER PROFILE" in msgs[1]["content"], "canon must reach the extractor"
    assert "Rosario" in msgs[1]["content"]


def case_scalars_are_an_operator_override_not_a_second_copy():
    """`fans.py` says "humans may correct what gen_info claimed" and PATCH accepts
    persona_*_claimed. That correction has to actually reach the prompt.

    It did not: the scalars were mirrors written FROM the list, and the renderer
    suppressed any scalar whose TEXT appeared in the list — so an extractor-written
    scalar was always suppressed by its own mirror, and the moment an operator
    PATCHed a different value BOTH would print. Matching by topic instead makes a
    set scalar win over every list row on that topic."""
    rows = [{"topic": "city", "claim": "en córdoba", "at": "1"},
            {"topic": "her ex", "claim": "un tipo de rosario", "at": "2"}]
    raw = json.dumps(rows)

    # No operator edit: the mirror renders ONCE, under the scalar's label, and the
    # list row it came from is not repeated underneath.
    mirrored = persona_claims_block(
        raw, location_claimed=claims_to_scalars(rows)["persona_location_claimed"])
    assert mirrored.count("en córdoba") == 1, mirrored
    assert "- where you are: en córdoba" in mirrored, mirrored
    assert "- city:" not in mirrored, mirrored
    # An unrelated topic is untouched by the override.
    assert "- her ex: un tipo de rosario" in mirrored, mirrored

    # Operator PATCHes a correction: it WINS, and the stale row is suppressed.
    corrected = persona_claims_block(raw, location_claimed="en rosario")
    assert "- where you are: en rosario" in corrected, corrected
    assert "en córdoba" not in corrected, "the corrected claim must not survive"
    assert "- her ex: un tipo de rosario" in corrected, corrected

    # No scalar set at all → the list renders as itself.
    plain = persona_claims_block(raw)
    assert "- city: en córdoba" in plain, plain
    assert "where you are" not in plain, plain


def case_topic_lookup_is_shared_by_writer_and_renderer():
    """One lookup, or a PATCHed correction lands on a topic that still prints its
    own row underneath."""
    assert _column_for_topic("hometown") == "persona_location_claimed"
    assert _column_for_topic("current location") == "persona_location_claimed"
    assert _column_for_topic("her age") == "persona_age_claimed"
    assert _column_for_topic("her job") == "persona_job_claimed"
    assert _column_for_topic("her dog") is None
    assert _column_for_topic("") is None
    # Every column the writer can produce must be one the renderer can override.
    written = set(claims_to_scalars(
        [{"topic": t, "claim": "x", "at": "1"}
         for t in ("hometown", "her age", "her job")]))
    assert written == {"persona_location_claimed", "persona_age_claimed",
                       "persona_job_claimed"}, written


def case_claims_to_scalars_is_newest_wins():
    """The mirror columns are a lookup, not control flow — extracted out of
    _extract_and_fill's persist path. `merged` is oldest→newest, so a later row on
    the same topic must win, matching the list's own latest-wins rule rather than
    depending on iteration order."""
    merged = [
        {"topic": "hometown", "claim": "soy de rosario", "at": "1"},
        {"topic": "her job", "claim": "trabajo en un bar", "at": "2"},
        {"topic": "current location", "claim": "estoy en chile", "at": "3"},
        {"topic": "her age", "claim": "tengo 22", "at": "4"},
    ]
    out = claims_to_scalars(merged)
    assert out["persona_location_claimed"] == "estoy en chile", out
    assert out["persona_job_claimed"] == "trabajo en un bar", out
    assert out["persona_age_claimed"] == "tengo 22", out

    # A topic matching nothing simply has no mirror — the claim still rides in
    # persona_claims_json and still reaches the prompt, so a miss costs nothing.
    assert claims_to_scalars([{"topic": "her dog", "claim": "Luna", "at": "1"}]) == {}
    assert claims_to_scalars([]) == {}


def case_ledger_and_scalars_reach_the_drawer():
    """The fan payload carries BOTH halves, and the three scalars are writable.

    Tier B ran with no operator surface at all: the engines recorded claims, the
    prompt used them and the pre-send check verified against them, but nothing
    was ever sent to the UI — so a wrong claim could not be seen, and the three
    columns the API had always accepted could not be reached from the client
    because `FanUpdate` never declared them. This pins the read side; the write
    side is the same PATCH `test_fan_language_patch` covers.

    The ledger is READ-ONLY on the wire on purpose — it is the audit trail of
    what she actually said, and a correction belongs on the scalar the prompt
    reads, not on the record of what happened."""
    import asyncio

    from db.engine import get_session
    from db.models import Account
    from fans import FanUpdateBody, _row_to_dict, get_fan, update_fan

    async def go():
        aid, fid = "acc_claims_ui", 9101
        ledger = [{"topic": "current location", "claim": "estoy acá en Chile", "at": "2026-07-25T19:00:00"},
                  {"topic": "city", "claim": "en córdoba", "at": "2026-07-25T20:44:39"}]
        async with get_session() as s:
            if await s.get(Account, aid) is None:
                s.add(Account(id=aid))
            if await s.get(Fan, (aid, fid)) is None:
                s.add(Fan(account_id=aid, fan_id=fid,
                          persona_claims_json=json.dumps(ledger),
                          persona_location_claimed="en córdoba"))
            await s.commit()

        got = await get_fan(aid, fid)
        assert got["persona_claims"] == ledger, got.get("persona_claims")

        # THE MERGED VIEW — and it must be the PROMPT'S, line for line. The drawer
        # renders this verbatim, so if it were built separately the operator would
        # be reading a second opinion about what the AI was told.
        block = persona_claims_block(json.dumps(ledger), location_claimed="en córdoba")
        printed = [ln[2:] for ln in block.splitlines() if ln.startswith("- ")]
        shown = [f"{r['label']}: {r['value']}" for r in got["persona_claims_resolved"]]
        assert shown == printed, (shown, printed)
        # The scalar override wins on its topic and the ledger row it replaces is
        # not printed twice; topics with NO mirror column still appear.
        assert "where you are: en córdoba" in shown, shown
        assert not any(s.startswith("current location:") for s in shown), shown
        cols = {r["label"]: r["column"] for r in got["persona_claims_resolved"]}
        assert cols["where you are"] == "persona_location_claimed", cols
        assert got["persona_location_claimed"] == "en córdoba", got
        # Absent columns come back as None, not missing — the drawer renders an
        # empty input rather than crashing on an undefined key.
        assert got["persona_age_claimed"] is None and got["persona_job_claimed"] is None, got

        # An operator correction lands on the scalar and does NOT rewrite history.
        await update_fan(aid, fid, FanUpdateBody(persona_location_claimed="en rosario"))
        after = await get_fan(aid, fid)
        assert after["persona_location_claimed"] == "en rosario", after
        assert after["persona_claims"] == ledger, "correcting a claim rewrote the ledger"

        # The PATCH RESPONSE must carry them too. The drawer writes it straight
        # into its query cache, so a response without the claims would blank the
        # panel the moment you corrected one.
        patched = await update_fan(aid, fid, FanUpdateBody(persona_job_claimed="barista"))
        assert "persona_claims_resolved" in patched and "persona_claims" in patched, \
            sorted(patched)
        assert any(r["value"] == "barista" for r in patched["persona_claims_resolved"]), \
            patched["persona_claims_resolved"]

        # …but the shared row serializer must NOT. Only the drawer reads these,
        # and building them per row put a JSON parse + merge on every list row.
        async with get_session() as s:
            one = _row_to_dict(await s.get(Fan, (aid, fid)))
        assert "persona_claims" not in one and "persona_claims_resolved" not in one, \
            "the row serializer is paying for two keys nothing but the drawer reads"
        assert one["persona_location_claimed"] == "en rosario", one

        # BOTH halves come from the same parser, so a long claim reads identically
        # in each. They used to differ — the ledger was unclipped and the merged
        # view clipped at 180 — and the drawer pairs them BY TEXT to find
        # superseded versions, so a long claim showed as current AND struck out.
        long_claim = "vivo sola en un depto chiquito " * 9      # 279 chars
        async with get_session() as s:
            row = await s.get(Fan, (aid, fid))
            row.persona_claims_json = json.dumps(
                [{"topic": "living situation", "claim": long_claim, "at": "2026-07-25T20:00:00"}])
            row.persona_location_claimed = None
            row.persona_job_claimed = None       # else its override row leads
            await s.commit()
        got = await get_fan(aid, fid)
        ledger_text = got["persona_claims"][0]["claim"]
        merged_text = next(r["value"] for r in got["persona_claims_resolved"]
                           if r["label"] == "living situation")
        assert ledger_text == merged_text, (len(ledger_text), len(merged_text))

        # Corrupt JSON degrades to [] rather than raising into the drawer.
        async with get_session() as s:
            row = await s.get(Fan, (aid, fid))
            row.persona_claims_json = "{not json"
            await s.commit()
        assert (await get_fan(aid, fid))["persona_claims"] == []

    asyncio.run(go())


CASES = [
    case_self_claim_prefilter,
    case_extract_gate_uses_the_prefilter,
    case_merge_is_latest_wins_and_capped,
    case_merge_is_idempotent,
    case_parse_is_defensive,
    case_claims_block_renders_and_is_empty_by_default,
    case_claims_reach_the_engine,
    case_extract_prompt_asks_for_deviations_only,
    case_claims_to_scalars_is_newest_wins,
    case_scalars_are_an_operator_override_not_a_second_copy,
    case_topic_lookup_is_shared_by_writer_and_renderer,
    case_ledger_and_scalars_reach_the_drawer,
]

if __name__ == "__main__":
    for c in CASES:
        c()
        print(f"  ok  {c.__name__}")
    print("all cases passed")
