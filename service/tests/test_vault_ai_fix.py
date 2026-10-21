#!/usr/bin/env python3
"""
Operator resolution of describe/flags disputes (`vault_ai_fix`). Durable
regression suite (plain-assert, no pytest — repo convention).

Two vision passes look at the same picture and sometimes contradict each other.
Which one is wrong differs item by item: on the graded vault all ten current disputes
are `clothing_state: fully_nude` on a still where the flags name a thong, and
the flags are right — but the reverse shape is equally possible, which is why
nothing here picks a side automatically.

Cases:
  case_dispute_offers_both_readings:
      a dispute is listed with BOTH resolutions, so the operator chooses rather
      than confirms. Picking automatically is the mistake the review exists to
      avoid.
  case_clean_and_unflagged_items_are_not_disputes:
      an item the two passes agree on, and one the flags never looked at, must
      not appear — the list measures disagreement, not coverage.
  case_fix_is_visible_to_every_reader:
      the correction is written into `ai_fields_json`, so the lanes, the price
      tiers and the copy brief see it with no change to any of them.
  case_fix_survives_a_forced_rerun:
      THE point. A correction a re-run silently reverts is worse than none —
      the operator would have no reason to look at the item again.
  case_fix_rejects_what_it_does_not_own:
      unknown fields are dropped and an invalid region state is refused, so a
      client posting a whole item back cannot rewrite fields this endpoint was
      never meant to own.
  case_resolving_the_dispute_removes_it:
      after the fix the item no longer contradicts itself — otherwise the
      operator works the same list forever.

Run: cd service/tests && \
  PYTHONPATH=$(cd .. && pwd) ../../venv/bin/python test_vault_ai_fix.py
Exit 0 = all cases passed. Temp DB bound by _harness (never prod). No OF, no
network, no LLM.
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import vault_ai_brief  # noqa: E402
import vault_ai_fix as F  # noqa: E402
import vault_scripts  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, VaultItem  # noqa: E402

_N = 0


def _next_account() -> str:
    global _N
    _N += 1
    return f"fix{_N}"


def _flags(vulva="not_in_frame", breasts="not_in_frame", anus="not_in_frame",
           *, underwear=True, over_vulva="", over_breasts="") -> dict:
    out = {"underwear_visible": underwear, "vulva_vis": vulva,
           "breasts_vis": breasts, "anus_vis": anus}
    if over_vulva:
        out["over_vulva"] = over_vulva
    if over_breasts:
        out["over_breasts"] = over_breasts
    return out


async def _seed(aid: str, rows: list[tuple[int, dict]]) -> None:
    base = datetime(2026, 7, 1, 12, 0, 0)
    async with get_session() as s:
        s.add(Account(id=aid))
        for i, (mid, fields) in enumerate(rows):
            s.add(VaultItem(account_id=aid, media_id=mid, kind="photo",
                            created_at=base + timedelta(seconds=i),
                            ai_fields_json=json.dumps(fields)))
        await s.commit()


async def _fields(aid: str, mid: int) -> dict:
    async with get_session() as s:
        item = await s.get(VaultItem, (aid, mid))
        return vault_ai_brief.load_fields(item.ai_fields_json)


# The a real graded shape: describe says fully_nude, the flags name a thong.
_THONG = {"description": "A woman lying on her back, fully nude.",
          "explicitness": "explicit", "clothing_state": "fully_nude",
          **_flags(vulva="covered", breasts="bare", over_vulva="black lace thong")}


def case_dispute_offers_both_readings() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [(700, _THONG)]))
    got = asyncio.run(F.list_disputes(aid))
    assert got["count"] == 1, got
    d = got["disputes"][0]
    assert d["codes"] == ["nude_but_clothed"], d["codes"]
    assert d["over"]["vulva_vis"] == "black lace thong"

    # BOTH sides are offered. Neither is applied.
    flags_side = d["propose"]["flags"]
    desc_side = d["propose"]["describe"]
    assert flags_side["clothing_state"] == "pulled_down", flags_side
    assert desc_side["over_vulva"] is None and desc_side["vulva_vis"] == "bare", desc_side
    stored = asyncio.run(_fields(aid, 700))
    assert stored["clothing_state"] == "fully_nude", "listing must not mutate"


def case_clean_and_unflagged_items_are_not_disputes() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [
        # The two passes agree.
        (710, {"explicitness": "suggestive", "clothing_state": "lingerie_on",
               **_flags(vulva="covered", breasts="covered",
                        over_vulva="black lace thong")}),
        # Never looked at by the flags pass — nothing to disagree WITH.
        (711, {"explicitness": "explicit", "clothing_state": "fully_nude"}),
    ]))
    got = asyncio.run(F.list_disputes(aid))
    assert got["count"] == 0, got["disputes"]
    assert got["checked"] == 1, "an unflagged item must not count as checked"


def case_fix_is_visible_to_every_reader() -> None:
    """Written into `ai_fields_json`, so the lanes and the price tiers pick it
    up without a single change to either."""
    aid = _next_account()
    asyncio.run(_seed(aid, [(720, _THONG)]))
    assert vault_scripts._is_nude(_THONG) is False, "fixture: thong means not nude"

    # Operator says describe was right — she really is nude, there is no thong.
    d = asyncio.run(F.list_disputes(aid))["disputes"][0]
    res = asyncio.run(F.apply_fix(aid, 720, d["propose"]["describe"]))
    assert res["ok"], res

    after = asyncio.run(_fields(aid, 720))
    assert "over_vulva" not in after, "a cleared garment must be gone, not blank"
    assert after["vulva_vis"] == "bare"
    assert vault_scripts._is_nude(after) is True, "the lane still reads her as clothed"


def case_fix_survives_a_forced_rerun() -> None:
    """A correction a re-run silently reverts is worse than no correction: the
    operator has no reason to ever look at the item again."""
    aid = _next_account()
    asyncio.run(_seed(aid, [(730, _THONG)]))
    asyncio.run(F.apply_fix(aid, 730, {"clothing_state": "pulled_down"}))

    async def rerun() -> None:
        # Exactly what `_flags_one` does on a forced pass: merge fresh model
        # output into the stored fields, skipping locked keys.
        async with get_session() as s:
            item = await s.get(VaultItem, (aid, 730))
            fields = vault_ai_brief.load_fields(item.ai_fields_json)
            locked = set(json.loads(item.locked_fields_json or "[]"))
            for k, v in {"clothing_state": "fully_nude",
                         "breasts_vis": "covered"}.items():
                if k not in locked:
                    fields[k] = v
            item.ai_fields_json = json.dumps(fields)
            await s.commit()

    asyncio.run(rerun())
    after = asyncio.run(_fields(aid, 730))
    assert after["clothing_state"] == "pulled_down", "the re-run reverted the operator"
    assert after["breasts_vis"] == "covered", "an UNfixed field must still refresh"


def case_fix_rejects_what_it_does_not_own() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [(740, _THONG)]))

    # A client posting the whole item back must not rewrite the prose.
    res = asyncio.run(F.apply_fix(aid, 740, {"description": "anything at all",
                                             "clothing_state": "pulled_down"}))
    assert res["ok"], res
    after = asyncio.run(_fields(aid, 740))
    assert after["description"].startswith("A woman"), "prose was rewritten"
    assert "description" not in res["applied"]

    # Nothing fixable at all is a refusal, not a silent no-op.
    assert asyncio.run(F.apply_fix(aid, 740, {"tags": ["x"]}))["ok"] is False
    # A region state outside the vocabulary is not an answer.
    bad = asyncio.run(F.apply_fix(aid, 740, {"vulva_vis": "sort of"}))
    assert bad["ok"] is False and bad["error"] == "bad_region_state", bad


def case_resolving_the_dispute_removes_it() -> None:
    """Otherwise the operator works the same list forever."""
    aid = _next_account()
    asyncio.run(_seed(aid, [(750, _THONG)]))
    d = asyncio.run(F.list_disputes(aid))["disputes"][0]
    res = asyncio.run(F.apply_fix(aid, 750, d["propose"]["flags"]))
    assert res["still_disagrees"] == [], res
    assert asyncio.run(F.list_disputes(aid))["count"] == 0, "dispute came back"


def case_confirming_is_evidence_not_a_no_op() -> None:
    """The half that is easy to skip and the half that makes measurement
    possible. Without a recorded confirmation, "the operator looked and agreed"
    and "nobody ever opened this" are the same record — and an accuracy
    computed over them reads 100% on a vault nobody has checked."""
    aid = _next_account()
    asyncio.run(_seed(aid, [(760, _THONG), (761, _THONG)]))

    # One confirmed as-is, one corrected.
    asyncio.run(F.record_grade(aid, 760, version=3))
    asyncio.run(F.record_grade(aid, 761, version=3,
                               corrections={"breasts_vis": "covered"}))

    acc = asyncio.run(F.flags_accuracy(aid, version=3))
    assert acc["graded_items"] == 2, acc
    # 3 regions x 2 items = 6 answers; exactly one was corrected.
    assert acc["answers"] == 6, acc
    assert acc["per_region"]["breasts_vis"] == {"ok": 1, "n": 2}, acc["per_region"]
    assert acc["accuracy"] == round(5 / 6, 4), acc

    # An UNGRADED item must not count as correct — that is the whole failure.
    asyncio.run(_seed(_next_account(), []))
    aid2 = _next_account()
    asyncio.run(_seed(aid2, [(770, _THONG)]))
    assert asyncio.run(F.flags_accuracy(aid2, version=3))["accuracy"] is None


def case_accuracy_refuses_to_mix_prompt_versions() -> None:
    """A score across two prompts measures neither. Three times in one session
    a number was taken from a half-finished re-run and read as a result,
    because v2 and v3 answers are indistinguishable once stored."""
    aid = _next_account()
    asyncio.run(_seed(aid, [(780, _THONG)]))
    asyncio.run(F.record_grade(aid, 780, version=2))

    now = asyncio.run(F.flags_accuracy(aid, version=3))
    assert now["graded_items"] == 0, "an old-version grade was counted"
    assert now["graded_other_versions"] == 1, now
    assert now["accuracy"] is None, "scored a vault with nothing graded at v3"


def case_queue_puts_ungraded_and_costly_items_first() -> None:
    """Two rounds of tuning were scored entirely on already-graded items, and a
    regression sat in the ungraded remainder through both without moving any
    total."""
    aid = _next_account()
    tame = {"explicitness": "suggestive", "clothing_state": "lingerie_on",
            **_flags(vulva="covered", breasts="covered",
                     over_vulva="black lace thong")}
    asyncio.run(_seed(aid, [(790, tame), (791, dict(tame)), (792, _THONG)]))
    asyncio.run(F.record_grade(aid, 790, version=3))

    q = asyncio.run(F.review_queue(aid, version=3))
    order = [i["media_id"] for i in q["items"]]
    assert order[-1] == 790, f"a graded item was not sent to the back: {order}"
    assert order[0] == 792, f"the disputed item should lead: {order}"
    assert q["graded"] == 1 and q["total"] == 3, q


def case_offscreen_penetration_can_actually_be_settled() -> None:
    """The bug the operator hit: the ONLY button on the flags side of this
    dispute answered `{"ok": false, "error": "no_fixable_fields"}`.

    `propose()` offered `penetration -> none`, `FIXABLE` did not list
    `penetration`, so `apply_fix` dropped it as an unknown key and had nothing
    left to write. And applying it would not have settled anything either: the
    detector also fires on the `acts` list, and read the literal string "none"
    as truthy, so an item explicitly cleared of penetration still disputed.
    """
    aid = _next_account()
    item = {"description": "Her hand is between her legs, off frame.",
            "explicitness": "explicit", "clothing_state": "fully_nude",
            "penetration": "fingers", "acts": ["rubbing_clit", "fingering"],
            **_flags(vulva="not_in_frame", breasts="covered",
                     over_breasts="white lace top", underwear=False)}
    asyncio.run(_seed(aid, [(800, item)]))

    d = asyncio.run(F.list_disputes(aid))["disputes"][0]
    assert d["codes"] == ["penetration_offscreen"], d["codes"]
    side = d["propose"]["flags"]
    assert side["penetration"] == "none", side
    # EVERY genital act goes in the same write, not just the penetrating one.
    # `rubbing_clit` and `fingering` both need the vulva in frame, which the
    # flags pass says it is not — so "Flags were right" clears both. Leaving
    # `rubbing_clit` behind was the both-wrong case: penetration gone, but the
    # item still claimed she was rubbing a clit that is not in the picture.
    assert side["acts"] == [], side

    res = asyncio.run(F.apply_fix(aid, 800, side))
    assert res["ok"], res
    assert res["still_disagrees"] == [], res
    assert asyncio.run(F.list_disputes(aid))["count"] == 0

    stored = asyncio.run(_fields(aid, 800))
    assert stored["penetration"] == "none" and stored["acts"] == []
    # "none" and "unclear" are ANSWERS, not findings.
    assert vault_ai_brief.penetration_claimed(stored) is False
    assert vault_ai_brief.genital_act_claimed(stored) is False
    # A clit-contact act with the vulva not_in_frame is now a contradiction too,
    # not only insertion — the describe pass inventing what it could not see.
    assert vault_ai_brief.genital_act_claimed({**stored, "acts": ["rubbing_clit"]}) is True
    assert vault_ai_brief.penetration_claimed({**stored, "acts": ["fingering"]}) is True


def case_hand_over_breast_thong_on_is_pulled_down() -> None:
    """The operator's screenshot: top exposed (a hand on one breast, the other
    bare), a black lace thong on the bottom, described `fully_nude`.

    Both passes erred — the flags called the breast `covered` because a hand is
    over it, describe called her `fully_nude` ignoring the thong — and the
    two-button resolver could express neither the truth: `is_bare` reads a
    hand-covered breast as not-bare, so "Flags were right" proposed
    `lingerie_on`. Keying the state on what is WORN (a hand is not worn) makes it
    `pulled_down`, and the hand-covered breast is corrected to `bare` so the
    tiers price it as the topless tease it is."""
    aid = _next_account()
    item = {"description": "A woman is fully nude, kneeling...",
            "explicitness": "explicit", "clothing_state": "fully_nude",
            "underwear_visible": True,
            **_flags(vulva="covered", breasts="covered", underwear=True,
                     over_vulva="black lace thong", over_breasts="her right hand")}
    asyncio.run(_seed(aid, [(830, item)]))

    d = asyncio.run(F.list_disputes(aid))["disputes"][0]
    assert d["codes"] == ["nude_but_clothed"], d["codes"]
    side = d["propose"]["flags"]
    assert side["clothing_state"] == "pulled_down", side
    assert side["breasts_vis"] == "bare", "a hand is not a garment — the top is exposed"
    assert "vulva_vis" not in side, "the thong is real clothing — the bottom stays covered"

    res = asyncio.run(F.apply_fix(aid, 830, side))
    assert res["ok"] and res["still_disagrees"] == [], res
    stored = asyncio.run(_fields(aid, 830))
    assert stored["clothing_state"] == "pulled_down"
    assert stored["breasts_vis"] == "bare" and stored["vulva_vis"] == "covered"
    assert stored["underwear_visible"] is True

    # A REAL garment over both regions is still lingerie_on — the hand is the
    # only thing that changes the reading.
    both = {**item, "over_breasts": "black lace bra"}
    assert F.propose(both, ["nude_but_clothed"])["flags"]["clothing_state"] == "lingerie_on"


def case_penetration_and_acts_are_validated() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [(810, dict(_THONG))]))
    bad_pen = asyncio.run(F.apply_fix(aid, 810, {"penetration": "banana"}))
    assert bad_pen == {"ok": False, "error": "bad_penetration_state",
                       "value": "banana"}, bad_pen
    bad_acts = asyncio.run(F.apply_fix(aid, 810, {"acts": "fingering"}))
    assert bad_acts["error"] == "bad_acts", bad_acts
    ok = asyncio.run(F.apply_fix(aid, 810, {"acts": [" Posing ", ""]}))
    assert ok["ok"] and asyncio.run(_fields(aid, 810))["acts"] == ["posing"], ok


def case_a_dressed_woman_is_never_offered_fully_nude() -> None:
    """`underwear_visible: False` is true of a tank top and jeans too.

    The rule read "nothing is bare" as "she is naked", so a woman photographed
    in a black top — flags: breasts covered by it, nothing else in frame — was
    offered `clothing_state -> fully_nude` as the correction to accept.
    """
    aid = _next_account()
    dressed = {"description": "A mirror selfie in a black top.",
               "explicitness": "suggestive", "clothing_state": "lingerie_on",
               **_flags(vulva="not_in_frame", breasts="covered",
                        over_breasts="black top", underwear=False)}
    asyncio.run(_seed(aid, [(820, dressed)]))
    d = asyncio.run(F.list_disputes(aid))["disputes"][0]
    assert d["codes"] == ["lingerie_but_nothing_on"], d["codes"]
    assert d["propose"]["flags"]["clothing_state"] == "dressed", d["propose"]
    assert asyncio.run(F.apply_fix(aid, 820, d["propose"]["flags"]))["still_disagrees"] == []

    # …but a real reveal still reads as one, from the same code path.
    topless = {**dressed, "over_breasts": "", "breasts_vis": "bare",
               "over_vulva": "denim skirt", "vulva_vis": "covered"}
    nude = {**dressed, "over_breasts": "", "breasts_vis": "bare",
            "vulva_vis": "bare"}
    assert F.propose(topless, ["lingerie_but_nothing_on"])["flags"][
        "clothing_state"] == "pulled_down"
    assert F.propose(nude, ["lingerie_but_nothing_on"])["flags"][
        "clothing_state"] == "fully_nude"


_harness.run(
    case_dispute_offers_both_readings,
    case_offscreen_penetration_can_actually_be_settled,
    case_hand_over_breast_thong_on_is_pulled_down,
    case_penetration_and_acts_are_validated,
    case_a_dressed_woman_is_never_offered_fully_nude,
    case_clean_and_unflagged_items_are_not_disputes,
    case_fix_is_visible_to_every_reader,
    case_fix_survives_a_forced_rerun,
    case_fix_rejects_what_it_does_not_own,
    case_resolving_the_dispute_removes_it,
    case_confirming_is_evidence_not_a_no_op,
    case_accuracy_refuses_to_mix_prompt_versions,
    case_queue_puts_ungraded_and_costly_items_first,
)
