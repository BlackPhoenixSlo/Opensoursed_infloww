#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

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


_THONG = {"description": "A woman lying on her back, fully nude.",
          "explicitness": "explicit", "clothing_state": "fully_nude",
          **_flags(vulva="covered", breasts="bare", over_vulva="black lace thong")}


def case_fix_is_visible_to_every_reader() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [(720, _THONG)]))
    assert vault_scripts._is_nude(_THONG) is False, "fixture: thong means not nude"

    res = asyncio.run(F.apply_fix(aid, 720, {"over_vulva": None, "vulva_vis": "bare",
                                             "underwear_visible": False}))
    assert res["ok"], res

    after = asyncio.run(_fields(aid, 720))
    assert "over_vulva" not in after, "a cleared garment must be gone, not blank"
    assert after["vulva_vis"] == "bare"
    assert vault_scripts._is_nude(after) is True, "the lane still reads her as clothed"


def case_fix_survives_a_forced_rerun() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [(730, _THONG)]))
    asyncio.run(F.apply_fix(aid, 730, {"clothing_state": "pulled_down"}))

    async def rerun() -> None:
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

    res = asyncio.run(F.apply_fix(aid, 740, {"description": "anything at all",
                                             "clothing_state": "pulled_down"}))
    assert res["ok"], res
    after = asyncio.run(_fields(aid, 740))
    assert after["description"].startswith("A woman"), "prose was rewritten"
    assert "description" not in res["applied"]

    assert asyncio.run(F.apply_fix(aid, 740, {"tags": ["x"]}))["ok"] is False
    bad = asyncio.run(F.apply_fix(aid, 740, {"vulva_vis": "sort of"}))
    assert bad["ok"] is False and bad["error"] == "bad_region_state", bad


def case_confirming_is_evidence_not_a_no_op() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [(760, _THONG), (761, _THONG)]))

    asyncio.run(F.record_grade(aid, 760, version=3))
    asyncio.run(F.record_grade(aid, 761, version=3,
                               corrections={"breasts_vis": "covered"}))

    acc = asyncio.run(F.flags_accuracy(aid, version=3))
    assert acc["graded_items"] == 2, acc
    assert acc["answers"] == 6, acc
    assert acc["per_region"]["breasts_vis"] == {"ok": 1, "n": 2}, acc["per_region"]
    assert acc["accuracy"] == round(5 / 6, 4), acc

    aid2 = _next_account()
    asyncio.run(_seed(aid2, [(770, _THONG)]))
    assert asyncio.run(F.flags_accuracy(aid2, version=3))["accuracy"] is None


def case_accuracy_refuses_to_mix_prompt_versions() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [(780, _THONG)]))
    asyncio.run(F.record_grade(aid, 780, version=2))

    now = asyncio.run(F.flags_accuracy(aid, version=3))
    assert now["graded_items"] == 0, "an old-version grade was counted"
    assert now["graded_other_versions"] == 1, now
    assert now["accuracy"] is None, "scored a vault with nothing graded at v3"


def case_queue_puts_ungraded_and_costly_items_first() -> None:
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


def case_queue_labels_auto_settled_and_sorts_by_price() -> None:
    aid = _next_account()
    ten = {"description": "Topless, thong on.", "explicitness": "explicit",
           "clothing_state": "fully_nude",
           **_flags(vulva="covered", breasts="bare", over_vulva="black lace thong")}
    fifty = {"description": "Lying back.", "explicitness": "explicit",
             "clothing_state": "lingerie_on",
             **_flags(vulva="bare", breasts="covered", over_breasts="her hands",
                      underwear=False)}
    zero = {"description": "In a bodysuit.", "explicitness": "explicit",
            "clothing_state": "fully_nude",
            **_flags(vulva="covered", breasts="covered",
                     over_vulva="black bodysuit", over_breasts="black bodysuit")}
    asyncio.run(_seed(aid, [(900, zero), (901, ten), (902, fifty)]))

    q = asyncio.run(F.review_queue(aid, version=3))
    by = {i["media_id"]: i for i in q["items"]}
    assert [i["media_id"] for i in q["items"]] == [902, 901, 900], q["items"]
    assert [by[m]["settled_price"] for m in (902, 901, 900)] == [50, 10, 0]
    assert by[901]["settled"][0] == ("clothing_state=fully_nude, yet a garment "
                                     "is visible → read as pulled_down"), by[901]
    assert by[901]["settled"][-1] == "never in a free lane"
    assert "passes_disagree" in by[901]["iffy"]
    assert "auto-settled" in F.IFFY_REASONS["passes_disagree"]
    assert asyncio.run(_fields(aid, 901))["clothing_state"] == "fully_nude"
    assert by[901]["locked"] == []


def case_offscreen_penetration_correction_settles_it() -> None:
    aid = _next_account()
    item = {"description": "Her hand is between her legs, off frame.",
            "explicitness": "explicit", "clothing_state": "fully_nude",
            "penetration": "fingers", "acts": ["rubbing_clit", "fingering"],
            **_flags(vulva="not_in_frame", breasts="covered",
                     over_breasts="white lace top", underwear=False)}
    asyncio.run(_seed(aid, [(800, item)]))
    assert vault_ai_brief.contradictions(item) == ["penetration_offscreen"]

    res = asyncio.run(F.apply_fix(aid, 800, {"penetration": "none", "acts": []}))
    assert res["ok"] and res["still_disagrees"] == [], res
    stored = asyncio.run(_fields(aid, 800))
    assert stored["penetration"] == "none" and stored["acts"] == []
    assert vault_ai_brief.penetration_claimed(stored) is False
    assert vault_ai_brief.genital_act_claimed(stored) is False
    assert vault_ai_brief.genital_act_claimed({**stored, "acts": ["rubbing_clit"]}) is True
    assert vault_ai_brief.penetration_claimed({**stored, "acts": ["fingering"]}) is True


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


_TAME = {"explicitness": "suggestive", "clothing_state": "lingerie_on",
         **_flags(vulva="covered", breasts="not_in_frame",
                  over_vulva="black lace thong")}


def case_iffy_reasons_table() -> None:
    thong = {"vulva_vis": "covered", "over_vulva": "black lace thong"}
    blind = {**_TAME, "explicitness": "explicit", "vulva_vis": "not_in_frame"}
    prose = {**_TAME, "vulva_vis": "not_in_frame",
             "description": "Stroking her exposed clitoris."}
    rows = (
        ("vulva covered, nothing named", {**_TAME, "over_vulva": ""}, None,
         ["unexplained_cover"]),
        ("unexplained but locked", {**_TAME, "over_vulva": ""}, {"vulva_vis"}, []),
        ("impossible garment is no name",
         {**_TAME, "breasts_vis": "covered", "over_breasts": "pink thong"}, None,
         ["unexplained_cover"]),
        ("two unexplained regions, one reason",
         {**_TAME, "over_vulva": "", "breasts_vis": "covered"}, None,
         ["unexplained_cover"]),
        ("fingering through a thong",
         {**_TAME, **thong, "explicitness": "explicit", "acts": ["fingering"]},
         None, ["act_vs_covered"]),
        ("toy penetration through a thong",
         {**_TAME, **thong, "explicitness": "explicit", "penetration": "toy"},
         None, ["act_vs_covered"]),
        ("penetration none", {**_TAME, **thong, "penetration": "none"}, None, []),
        ("penetration unclear", {**_TAME, **thong, "penetration": "unclear"},
         None, []),
        ("rubbing_clit over fabric",
         {**_TAME, **thong, "explicitness": "explicit", "acts": ["rubbing_clit"]},
         None, []),
        ("sex_doggy not in the act set",
         {**_TAME, **thong, "explicitness": "explicit", "acts": ["sex_doggy"]},
         None, []),
        ("passes disagree", _THONG, None, ["passes_disagree"]),
        ("explicit, nothing in frame", blind, None, ["blind"]),
        ("hardcore, nothing in frame", {**blind, "explicitness": "hardcore"},
         None, ["blind"]),
        ("suggestive, nothing in frame", {**blind, "explicitness": "suggestive"},
         None, []),
        ("sfw, nothing in frame", {**blind, "explicitness": "sfw"}, None, []),
        ("prose says exposed, flags not_in_frame", prose, None, ["prose_vs_flags"]),
        ("prose agrees with bare flags", {**prose, "vulva_vis": "bare"}, None, []),
        ("prose vs flags but locked", prose, {"vulva_vis"}, []),
        ("exposure word >40 chars away",
         {**prose, "description": "Exposed " + "and " * 12 + "her clitoris."},
         None, []),
        ("word boundary: clitoral is not clit",
         {**prose, "description": "Her exposed clitoral hood."}, None, []),
    )
    for name, fields, locked, want in rows:
        got = F.iffy_reasons(fields, locked or set())
        assert got == want, f"{name}: {got} != {want}"


def case_priority_table() -> None:
    def key(fields, lanes=(), reasons=()):
        return F._priority(fields, list(lanes), 3, list(reasons))

    def graded(v):
        return {**_TAME, F.GRADE_KEY: {"v": v}}

    bare = {**_TAME, "explicitness": "explicit", "clothing_state": "pulled_down",
            "breasts_vis": "bare"}
    assert vault_ai_brief.contradictions(bare) == [], "fixture: bare must be clean"
    before = (
        ("ungraded before graded v3", key(_TAME), key(graded(3))),
        ("ungraded before graded v4", key(_TAME), key(graded(4))),
        ("more reasons earlier", key(_TAME, reasons=["a", "b"]),
         key(_TAME, reasons=["a"])),
        ("contradiction before none", key(_THONG), key(_TAME)),
        ("tease 10 before unpaid", key(_TAME, ["tease 10"]), key(_TAME, ["mass"])),
        ("tease 50 before unpaid", key(_TAME, ["tease 50"]), key(_TAME, ["mass"])),
        ("safe explicit before unpaid", key(_TAME, ["safe explicit"]),
         key(_TAME, ["stories"])),
        ("any bare breaks the tie", key(bare), key(_TAME)),
    )
    before += (
        ("disputed: more price riding first",
         F._priority(_THONG, [], 3, [], 50), F._priority(_THONG, [], 3, [], 10)),
    )
    for name, first, second in before:
        assert first < second, f"{name}: {first} !< {second}"
    assert key(graded(2)) == key(_TAME), "a v2 grade is not graded at v3"
    assert F._priority(_TAME, [], 3, [], 50) == F._priority(_TAME, [], 3, [], 0), \
        "price only orders disputed items"


def case_grade_of_table() -> None:
    for name, fields, want in (
        ("None", None, {}),
        ("not a dict", ["x"], {}),
        ("no grade", {}, {}),
        ("grade not a dict", {F.GRADE_KEY: "yes"}, {}),
        ("grade dict", {F.GRADE_KEY: {"v": 3}}, {"v": 3}),
    ):
        got = F.grade_of(fields)
        assert got == want, f"{name}: {got} != {want}"


_harness.run(
    case_offscreen_penetration_correction_settles_it,
    case_penetration_and_acts_are_validated,
    case_fix_is_visible_to_every_reader,
    case_fix_survives_a_forced_rerun,
    case_fix_rejects_what_it_does_not_own,
    case_confirming_is_evidence_not_a_no_op,
    case_accuracy_refuses_to_mix_prompt_versions,
    case_queue_puts_ungraded_and_costly_items_first,
    case_queue_labels_auto_settled_and_sorts_by_price,
    case_iffy_reasons_table,
    case_priority_table,
    case_grade_of_table,
)
