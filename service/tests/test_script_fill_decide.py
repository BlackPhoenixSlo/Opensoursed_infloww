#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import script_fill_decide as d  # noqa: E402
import vault_ai_brief  # noqa: E402
import vault_ai_vision_decide  # noqa: E402
import vault_jev_flags  # noqa: E402
import vault_jev_rules  # noqa: E402
import vault_scripts  # noqa: E402

T0 = datetime(2026, 7, 1)
ACCT = "acct-a"



def _jev(lane, kind="photo", bare="n", **extra):
    j = {"v": vault_jev_rules.VERSION, "status": "ok", "lane5": lane, "state": {}, "kind": kind,
         "breasts_bare": bare, "crotch_bare": bare, "penetration": "n", "tags": {}, **extra}
    if kind == "video":
        j.update(vv=vault_jev_rules.VIDEO_VERSION, frames=[])
    return j


def _flags(vulva, breasts, *, underwear=True, ov="", ob=""):
    out = {"underwear_visible": underwear, "vulva_vis": vulva, "breasts_vis": breasts, "anus_vis": "not_in_frame"}
    if ov:
        out["over_vulva"] = ov
    if ob:
        out["over_breasts"] = ob
    return out


SOLO = {"people_count": 1, "partner_visible": False}
TIERS = {
    "sfw": {"clothing_state": "dressed", "acts": ["posing"], "penetration": "none", "explicitness": "sfw",
            **_flags("covered", "covered", ov="jeans", ob="t-shirt")},
    "suggestive": {"clothing_state": "lingerie_on", "acts": ["posing"], "penetration": "none",
                   "explicitness": "suggestive", **_flags("covered", "covered", ov="panties", ob="bra")},
    "explicit": {"clothing_state": "fully_nude", "acts": ["posing"], "penetration": "none",
                 "explicitness": "explicit", **_flags("bare", "bare", underwear=False)},
}


def _item(mid, tier, kind="photo", lane="$10", colour="white", **kw):
    fields = {**TIERS[tier], "clothing_items": [f"{colour} bra"], **SOLO,
              vault_jev_rules.JEV_KEY: _jev(lane, kind, "y" if tier == "explicit" else "n")}
    if lane in vault_jev_rules.PAID:
        m = vault_jev_flags.apply(fields, fields[vault_jev_rules.JEV_KEY])
        fields.update({k: m[k] for k in ("explicitness", "breasts_vis", "vulva_vis", "anus_vis")})
    fields = vault_ai_brief.settled_reading(fields)
    row = {"media_id": mid, "kind": kind, "created_at": T0 + timedelta(minutes=mid),
           "duration_seconds": 12 if kind == "video" else None, "fields": fields,
           "describe_status": "described", "score": vault_scripts.escalation_score(fields),
           "refs": set(), "folder_cents": None, "review_state": None, "operator_overrides_json": None,
           "account_id": ACCT}
    row.update(kw)
    return row


WHITE = ([_item(m, "sfw", lane="free") for m in (1, 2, 3)]
         + [_item(m, "suggestive") for m in (4, 5, 6, 7)] + [_item(8, "suggestive", "video", "$50")]
         + [_item(m, "explicit", lane="$50") for m in (9, 10, 11, 12)] + [_item(13, "explicit", "video", "$50")])
RED = ([_item(m, "sfw", lane="free", colour="red") for m in (31, 32)]
       + [_item(m, "suggestive", colour="red") for m in (33, 34)]
       + [_item(m, "explicit", lane="$50", colour="red") for m in (35, 36)]
       + [_item(37, "explicit", "video", "$50", colour="red")])
WHITE_IDS = {r["media_id"] for r in WHITE}
RED_IDS = {r["media_id"] for r in RED}


def _row(rid, step, notes="", text="", price=0, media=(), previews=(), script="Spicy intro"):
    return {"id": rid, "script_id": script, "script_step": step, "text": text, "notes": notes,
            "price_cents": price, "media_json": json.dumps([{"id": m, "type": "photo"} for m in media]),
            "previews_json": json.dumps(list(previews))}


def _seq(steps, script="Spicy intro"):
    rows = []
    for step in range(1, max([13, *steps]) + 1):
        notes, text, price, media = steps.get(step, (f"{step}/13, bridge", "how's your day going?", 0, ()))
        rows.append(_row(100 + step, step, notes, text, price, media, script=script))
    return rows


S1 = {1: ("1/3, freebie", "hey babe here's a little something", 0, ()),
      3: ("1/3, ppv", "wanna see more? 😈", 0, ()),
      5: ("2/3", "sending you 2 pics 🙈", 0, ()),
      7: ("3/3, ppv", "the full video, all of me", 0, ())}


def _cov(remaining=0, described=300):
    return {"target": 1000, "describable": 2000, "described": described, "terminal": 0,
            "goal": described + remaining, "remaining": remaining}


def _plan(rows, items, *, used=(), groups=(), remaining=0, blocked=None, prints=None, shoots=None, **kw):
    eff = [d.effective(r) for r in items]
    if shoots is None:
        kept = [m for r in rows for m in d._media(r)]
        shoots = d.build_shoots(d.fillable_rows(eff, account_id=ACCT), groups, kept, prints or {})
    return d.plan(rows, shoots, eff, used, groups, _cov(remaining), blocked, account_id=ACCT, **kw)


def _opts(p):
    return {o["step"] if o["option"] == 1 else (o["step"], o["option"]): o for o in p["options"]}



def case_roles_table():
    rows = [
        ("1/3, ppv", "wanna see more?", 0, "paid_media", "any", 1, [], "ppv note"),
        ("2/3", "", 1933, "paid_media", "any", 1, [], "saved price, no tag"),
        ("3/3, bridge", "so what are you up to", 0, "chat", None, 0, [], "bridge"),
        ("3/3, bridge", "", 3967, "paid_media", "any", 1, [], "price beats a bridge note"),
        ("1/3, freebie", "a little gift", 0, "free_media", "photo", 1, [], "freebie"),
        ("ppv no content, lock", "unlock to see", 3967, "chat", None, 0, ["lock_no_content"],
         "no content beats a saved price"),
        ("", "unlock it for $15 babe", 0, "paid_media", "any", 1, [], "text quotes an amount"),
        ("", "sending you 3 pics now", 0, "paid_media", "photo", 3, [], "photo count promise"),
        ("", "6 pics just for you", 0, "paid_media", "photo", 4, [], "photo count capped at 4"),
        ("", "i just filmed this for u", 0, "paid_media", "clip", 1, [], "clip word"),
        ("", "my 3 new videos", 0, "paid_media", "clip", 1, [], "clips are always one"),
        ("", "a video and 2 pics", 0, "paid_media", "any", 2, [], "clip and photo nouns -> any"),
        ("", "here's a free pic babe", 0, "free_media", "photo", 1, [], "promise saying free"),
        ("", "hey how are you", 0, "chat", None, 0, [], "nothing"),
        ("2/3", "", 0, "chat", None, 0, [], "a bare position note"),
    ]
    seq = [_row(i, i, n, t, p) for i, (n, t, p, *_rest) in enumerate(rows, 1)]
    got = d.roles(seq + [{**_row(99, 1), "script_step": None}])
    assert 99 not in got, "a row without a step is not in the run"
    for i, (_n, _t, _p, role, wants, count, flags, why) in enumerate(rows, 1):
        r = got[i]
        assert (r["role"], r["wants"], r["count"], r["flags"]) == (role, wants, count, flags), (why, r)


def case_all_chat_no_paid_steps():
    rows = _seq({1: ("1/3, freebie", "a gift", 0, ())})
    p = _plan(rows, WHITE)
    assert p["status"] == "no_paid_steps", p["status"]
    assert all(o["media"] == [] for o in p["options"]), "nothing proposed"



def case_fillable_reasons():
    base = _item(1, "suggestive")
    no_tier = {k: v for k, v in base["fields"].items() if k != "explicitness"}
    disputed = {**base["fields"], vault_ai_brief.SETTLED_KEY: ["nude_but_clothed"]}
    rows = [
        (base, {}, None, "fillable"),
        ({**base, "account_id": None}, {}, "not_mine", "no account_id on the item"),
        ({k: v for k, v in base.items() if k != "account_id"}, {}, "not_mine", "account_id key missing"),
        ({**base, "removed_at": T0}, {}, "not_live", "removed"),
        ({**base, "describe_status": "failed"}, {}, "not_described", "not described"),
        ({**base, "account_id": "acct-b"}, {"account_id": "acct-a"}, "not_mine", "other Creator"),
        ({**base, "account_id": "acct-a"}, {"account_id": "acct-a"}, None, "own Creator"),
        ({**base, "fields": {**base["fields"], "people_count": 2}}, {}, "not_solo", "partner in shot"),
        ({**base, "fields": {**base["fields"], "people_count": None}}, {}, "not_solo", "solo unknown"),
        ({**base, "fields": {**base["fields"], "acts": ["blowjob"]}}, {}, "not_solo", "partner act, count 1"),
        ({**base, "fields": {**base["fields"], "primary_folder": "sex_with_partner"}}, {}, "not_solo",
         "partner folder, count 1"),
        ({**base, "fields": {**base["fields"], "penetration": "penis"}}, {}, "not_solo", "penis, count 1"),
        ({**base, "fields": {**base["fields"], "_jev": {**base["fields"]["_jev"],
                                                     "tags": {"people_count": "two_or_more"}}}},
         {}, "not_solo", "Jev counts two"),
        ({**base, "fields": {**base["fields"], "people_count": 2}}, {"solo_sequences": True}, "not_solo",
         "partner in shot, solo switch on"),
        ({**base, "fields": {**base["fields"], "people_count": 2}}, {"solo_sequences": False}, None,
         "partner in shot, solo switch off"),
        ({**base, "fields": {**base["fields"], "acts": ["blowjob"]}}, {"solo_sequences": False}, None,
         "partner act, solo switch off"),
        ({**base, "fields": {**no_tier, "people_count": 2}}, {"solo_sequences": False}, "no_rung",
         "partner, solo switch off: the other gates still apply"),
        ({**base, "fields": no_tier}, {}, "no_rung", "no Rung"),
        ({**base, "fields": {**base["fields"], "_jev": _jev("review")}}, {}, "jev_review", "Jev review"),
        ({**base, "fields": {**base["fields"], "_jev": _jev("$100", "video", review="fetch_failed")}}, {},
         "held", "held clip"),
        ({**base, "review_state": "rejected"}, {}, "rejected", "rejected"),
        ({**base, "needs_review": True}, {}, "review_folder", "REVIEW folder, switch on"),
        ({**base, "needs_review": True}, {"standard_folders": False}, None, "REVIEW folder, switch off"),
        ({**base, "fields": disputed}, {}, "unpriced_dispute", "disputed free-tier"),
    ]
    for item, kw, want, why in rows:
        got = d.fillable(d.effective(item), **{"account_id": ACCT, **kw})
        assert got == want, (why, got)
    duo = d.effective({**base, "fields": {**base["fields"], "people_count": 2}})
    assert d.fillable_rows([duo], account_id=ACCT) == [], "solo_sequences defaults on"
    assert [r["media_id"] for r in d.fillable_rows([duo], account_id=ACCT, solo_sequences=False)] == [1]
    free = {k: v for k, v in _item(3, "suggestive", lane="free")["fields"].items() if k != "explicitness"}
    flipped = d.effective({**base, "fields": free,
                           "operator_overrides_json": json.dumps({"explicitness_tier": "suggestive"})})
    assert d.fillable(flipped, account_id=ACCT) is None, "override puts it on a Rung"
    assert vault_scripts._with_script_why(flipped)["why"]["rung"] == 1
    paid = d.effective({**base, "fields": no_tier,
                        "operator_overrides_json": json.dumps({"explicitness_tier": "suggestive"})})
    assert d.fillable(paid, account_id=ACCT) == "unpriced_dispute", "suggestive beside a $10 Jev lane (W30 D1)"
    down = d.effective({**_item(2, "explicit", lane="$50"),
                        "operator_overrides_json": {"explicitness_tier": "suggestive"}})
    assert vault_scripts._with_script_why(down)["why"]["rung"] == 1, "explicit -> suggestive by override"
    stored = base["fields"]["_jev"]
    picked = d.effective({**base, "operator_overrides_json": {"_jev": {"lane": "free"}, "description": "x"}})
    assert picked["fields"]["_jev"] == stored and picked["fields"]["description"] == "x"



def case_ae_sequence_worked():
    rows = _seq(S1)
    p = _plan(rows, WHITE)
    assert p["status"] == "ok", p
    o = _opts(p)
    assert (o[1]["media"], o[1]["previews"], o[1]["price_cents"]) == ([1], [], 0)
    assert (o[3]["media"], o[3]["previews"], o[3]["flags"]) == ([2, 4], [2], ["no_video"])
    assert (o[5]["media"], o[5]["previews"], o[5]["flags"]) == ([3, 11, 12, 8], [3], [])
    assert (o[7]["media"], o[7]["previews"]) == ([13], [])
    assert [o[s]["price_cents"] for s in (3, 5, 7)] == [1000, 5000, 7500]
    assert all(o[s]["role"] == "chat" and o[s]["media"] == [] for s in (2, 4, 6, 8, 13))
    assert p["conflict"] is None and p["flags"] == []


def _send_pos(items):
    order = sorted((vault_scripts._with_script_why(dict(r)) for r in items), key=vault_scripts._script_sort_key)
    return {r["media_id"]: i for i, r in enumerate(order)}


def _shoot_of(items):
    shoots = d.build_shoots([d.effective(r) for r in items], [], [], {})
    return {int(m): n for n, s in enumerate(shoots)
            for m in [*(r["media_id"] for r in s["items"]), *(s.get("overflow") or [])]}


def _locked(o):
    return o["media"][len(o["previews"]):]


def case_assignment_invariants():
    items = WHITE + RED
    by_id = {r["media_id"]: vault_scripts._with_script_why(dict(r)) for r in items}
    pos, shoot = _send_pos(items), _shoot_of(items)
    top = {kind: max((m for m, r in by_id.items() if r["kind"] == kind and d._list_cents(r)), key=pos.get)
           for kind in ("photo", "video")}
    seqs = [
        _seq(S1),
        _seq({1: ("1/4, freebie", "a gift", 0, ()), 3: ("1/4, ppv", "", 0, ()), 5: ("2/4, ppv", "2 pics", 0, ()),
              8: ("3/4, ppv", "6 pics", 0, ()), 11: ("4/4, ppv", "", 0, ())}),
        _seq({2: ("1/2, ppv", "pic for you", 0, ()), 9: ("2/2, ppv", "", 3967, ())}),
    ]
    for rows in seqs:
        p = _plan(rows, items)
        assert p["status"] == "ok", p["status"]
        paid = sorted((o for o in p["options"] if o["role"] == "paid_media"), key=lambda o: o["step"])
        every = [m for o in p["options"] for m in o["media"]]
        assert len(set(every)) == len(every), "no id twice in one Sequence"
        hi = {"photo": -1, "video": -1}
        for o in paid:
            locked = _locked(o)
            photos = [m for m in locked if by_id[m]["kind"] == "photo"]
            vids = [m for m in locked if by_id[m]["kind"] == "video"]
            assert locked == photos + vids and len(vids) <= 1, ("photos, then one video last", o)
            if o["wants"] == "clip":
                assert not photos and vids and not o["previews"], ("a clip ask: the clip alone", o)
            else:
                assert 1 <= len(photos) <= 4 and len({by_id[m]["why"]["rung"] for m in photos}) == 1, o
                assert len({shoot[m] for m in photos}) == 1, ("a Slice's photos: one Shoot (A2a)", o)
                assert ("no_video" in o["flags"]) == (not vids), o
            for kind, ids in (("photo", photos), ("video", vids)):
                if ids:
                    assert min(pos[m] for m in ids) > hi[kind], ("each kind ascends across Steps", o)
                    hi[kind] = max(pos[m] for m in ids)
            assert len(o["previews"]) <= 1, "one preview"
            for m in o["previews"]:
                assert by_id[m]["kind"] == "photo" and d._free_safe(by_id[m], d._list_cents(by_id[m]))
        last_photo = [o for o in paid if o["wants"] != "clip"][-1]
        assert top["photo"] in last_photo["media"], ("the last photo Step holds the top photo", last_photo)
        if any(by_id[m]["kind"] == "video" for m in _locked(paid[-1])):
            assert top["video"] in paid[-1]["media"], ("the last Step's clip is the top clip", paid[-1])
    o = _opts(_plan(seqs[1], items))
    assert [_locked(o[s]) for s in (3, 5, 8, 11)] == [[4], [33, 34, 8], [9, 10, 11, 12, 13], [36, 37]]
    assert o[3]["flags"] == ["no_video"]
    o = _opts(_plan(seqs[2], items))
    assert (_locked(o[2]), _locked(o[9]), o[9]["flags"], o[9]["price_cents"]) == ([4, 8], [36, 37], [], 3967), o


BLUE = ([_item(m, "sfw", lane="free", colour="blue") for m in (801, 802, 803)]
        + [_item(m, "suggestive", colour="blue") for m in range(804, 810)]
        + [_item(m, "explicit", lane="$50", colour="blue") for m in (810, 811, 812)]
        + [_item(813, "suggestive", "video", "$50", colour="blue"),
           _item(815, "suggestive", "video", "$50", colour="blue"),
           _item(814, "explicit", "video", "$50", colour="blue")])


def case_asks_table():
    rows = [
        ("watch me spread my BARE PUSSY for u", {"genitals"}, "spread / pussy, any case"),
        ("watch me take it all off for you", {"nude"}, "phrase"),
        ("nothing on but a smile", {"nude"}, "phrase"),
        ("sliding this bra off slowly", {"breasts"}, "bra off"),
        ("i'll drop this juicy ass on your face", {"ass"}, "ass"),
        ("riding my toy til i cum", {"act"}, "act words"),
        ("grab my tits and my booty", {"breasts", "ass"}, "two asks"),
        ("let me show you everything you've been craving, ready for it?", set(), "nothing named"),
        ("assume the position, class is in session", set(), "whole words only: ass in assume / class"),
        ("", set(), "empty"),
        (None, set(), "none"),
        ("i'm not showing my pussy yet", set(), "not ... pussy"),
        ("you won’t see me naked", set(), "curly won't ... naked"),
        ("don't make me spread", set(), "don't ... spread"),
        ("not yet babe, pussy comes later", set(), "yet ... pussy"),
        ("no tits for you, just my ass", {"ass"}, "no reaches tits, not ass 5 words on"),
        ("no good boy of mine would dare look away from this.. my ass and tits are all yours",
         {"ass", "breasts"}, "a far-off no keeps the asks (AE step shape)"),
        ("you'll see my pussy soon", {"genitals"}, "a deferral word after the ask does not drop it"),
    ]
    for text, want, why in rows:
        assert d.asks(text) == want, (why, d.asks(text))
    eff = {m: d.effective(r)["fields"] for m, r in ((r["media_id"], r) for r in BLUE)}
    assert d.answers(eff[801]) == frozenset() and d.answers(eff[804]) == {"breasts"}
    assert d.answers(eff[810]) == {"genitals", "nude", "breasts"}, d.answers(eff[810])
    assert d.answers({**eff[804], "body_focus": ["ass"]}) == {"ass", "breasts"}
    assert d.answers({**eff[804], "acts": ["fingering"]}) == {"act", "breasts"}


def _three(text, items=BLUE):
    rows = _seq({3: ("1/3, ppv", text, 0, ()), 5: ("2/3, ppv", "", 0, ()), 7: ("3/3, ppv", "", 0, ())})
    p = _plan(rows, items)
    assert p["status"] == "ok", (text, p["status"])
    o = _opts(p)
    return {s: ([m for m in _locked(o[s]) if m < 813], o[s]["flags"]) for s in (3, 5, 7)}


def case_ask_preference():
    plain = _three("")
    assert plain == {3: ([804], []), 5: ([808], []), 7: ([812], [])}, ("control: even spread, top last", plain)
    rows = [
        ("let me show you my pussy", BLUE, [804], [], "genitals: no lift, the step's $50 clip 813 answers it"),
        ("get naked for me", BLUE, [804], ["ask_unmet"], "nude answered only above the window: no lift"),
        ("you won't see my pussy yet", BLUE, [804], [], "a negated ask does nothing"),
        ("look at my tits", BLUE, [804], [], "breasts: no lift, the $10 804 answers it"),
        ("bend over for you", [_with(r, body_focus=["ass"]) if r["media_id"] == 806 else r for r in BLUE],
         [806], [], "an ask answered inside the window wins over send order"),
    ]
    for text, items, photos, flags, why in rows:
        got = _three(text, items)
        assert got[3] == (photos, flags) and got[5][0] == [808] and got[7][0] == [812], (why, got)


def case_clip_only_and_previews():
    o = _opts(_plan(_seq({1: ("1/1, ppv", "a pic for you", 0, ())}), WHITE[:8]))
    assert (o[1]["media"], o[1]["previews"], o[1]["price_cents"]) == ([1, 7, 8], [1], 5000), \
        ("the top $10 photo + the $50 clip: priced by the clip", o[1])
    o = _opts(_plan(_seq({1: ("1/2, ppv", "2 pics", 0, ()), 3: ("2/2, ppv", "my new video 🎥", 0, ())}), WHITE))
    assert (o[1]["previews"], _locked(o[1])) == ([1], [11, 12, 8]), o[1]
    assert (o[3]["media"], o[3]["previews"]) == ([13], []), o[3]
    no_clip = [r for r in WHITE if r["kind"] == "photo"]
    p = _plan(_seq({1: ("1/2, ppv", "", 0, ()), 3: ("2/2, ppv", "", 0, ())}), no_clip)
    o = _opts(p)
    assert p["status"] == "ok" and all(o[s]["flags"] == ["no_video"] for s in (1, 3)), "no clip: never refused"


def case_coherence():
    w2 = [r for r in WHITE if r["media_id"] != 8] + [_item(58, "suggestive", "video", "$50"),
                                                      _item(38, "suggestive", "video", "$50", colour="red")]
    two = _seq({3: ("1/2, ppv", "2 pics", 0, ()), 7: ("2/2, ppv", "the full video", 0, ())})
    o = _opts(_plan(two, w2))
    assert _locked(o[3]) == [11, 12, 58], ("white photos take the white clip over red 38 sorting first", o[3])
    o = _opts(_plan(two, [r for r in w2 if r["media_id"] != 58]))
    assert _locked(o[3]) == [11, 12, 38], ("no white clip in reach: the pool's", o[3])
    inter = ([_item(m, "sfw", lane="free", colour=c) for m, c in ((700, "white"), (699, "red"))]
             + [_item(m, "suggestive", colour=c) for m, c in
                ((701, "white"), (702, "red"), (703, "red"), (704, "white"), (705, "red"), (706, "white"))]
             + [_item(707, "explicit", lane="$50", colour="white"), _item(708, "explicit", lane="$50", colour="red")])
    shoot = _shoot_of(inter)
    assert shoot[701] == shoot[704] == shoot[706] != shoot[702], "precondition: two Shoots"
    four = _seq({s: (f"{i}/4, ppv", "a pic", 0, ()) for i, s in enumerate((3, 5, 7, 9), 1)})
    o = _opts(_plan(four, inter))
    assert [_locked(o[s]) for s in (3, 5, 7, 9)] == [[701], [704], [706], [708]], \
        "step 5 skips red 703 for white 704 (step 3's Shoot); the last Step still takes the top"


def case_kept_reserved():
    rows = _seq({**S1, 3: ("1/3, ppv", "wanna see more?", 0, (5,))})
    p = _plan(rows, WHITE + RED)
    assert p["status"] == "ok", p
    o = _opts(p)
    new = [m for s in (1, 5, 7) for m in o[s]["media"]]
    assert new and 5 not in new, "the kept id is reserved"
    assert o[3]["keep"] and o[3]["media"] == [5] and o[3]["flags"] == ["kept_existing", "kept_unpriced"]
    gone = _opts(_plan(_seq({**S1, 3: ("1/3, ppv", "", 2000, (404,))}), WHITE))
    assert gone[3]["flags"] == ["kept_existing", "removed_media"], gone[3]["flags"]


def case_kept_dupe_set_reserved():
    rows = _seq({**S1, 3: ("1/3, ppv", "", 0, (99,))})
    items = WHITE + [_item(99, "suggestive")]
    p = _plan(rows, items, groups=[[4, 99]])
    assert p["status"] == "ok", p
    every = [m for o in p["options"] if not o["keep"] for m in o["media"]]
    assert 4 not in every and 99 not in every, "a kept id's dupe set is reserved"
    rows = _seq({**S1, 9: ("ppv", "", 0, (99,))})
    p = _plan(rows, WHITE, groups=[[4, 99]])
    o = _opts(p)
    assert p["status"] == "ok" and o[9]["flags"] == ["kept_existing", "kept_unpriced", "removed_media"], p
    assert _locked(o[3]) == [5], ("4 is reserved through its dupe set", o[3])
    assert _locked(_opts(_plan(rows, WHITE))[3]) == [4], "control: without the dupe set 4 is taken"


def _white_like(base, colour):
    return ([_item(base + m, "sfw", lane="free", colour=colour) for m in (1, 2, 3)]
            + [_item(base + m, "suggestive", colour=colour) for m in (4, 5, 6, 7)]
            + [_item(base + 8, "suggestive", "video", "$50", colour=colour)]
            + [_item(base + m, "explicit", lane="$50", colour=colour) for m in (9, 10, 11, 12)]
            + [_item(base + 13, "explicit", "video", "$50", colour=colour)])


def _with(item, **fields):
    return {**item, "fields": {**item["fields"], **fields}}


CLIP_ASK = _seq({1: ("1/2, freebie", "a gift", 0, ()), 3: ("1/2, ppv", "wanna see more?", 0, ()),
                 7: ("2/2, ppv", "the full video", 0, ())})


def case_plan_gates_unfillable():
    clip = _item(90, "explicit", "video", "$50")
    o = _opts(_plan(CLIP_ASK, WHITE + [clip]))
    assert o[7]["media"] == [90], ("control: a Fillable 90 wins the clip ask", o[7])
    bad = [
        (_with(clip, people_count=2), "not_solo", {}),
        (_with(clip, _jev=_jev("$50", "video", "y", review="fetch_failed")), "held", {}),
        ({**clip, "review_state": "rejected"}, "rejected", {}),
        ({**clip, "needs_review": True}, "review_folder", {}),
        ({**clip, "account_id": "acct-b"}, "not_mine", {}),
        ({**clip, "account_id": None}, "not_mine", {}),
        ({**clip, "needs_review": True}, None, {"standard_folders": False}),
    ]
    for item, reason, kw in bad:
        eff = [d.effective(r) for r in WHITE + [item]]
        assert d.fillable(eff[-1], account_id=ACCT, **kw) == reason, (reason, kw)
        shoots = d.build_shoots(eff, [], [], {})
        assert any(90 in {int(r["media_id"]) for r in s["items"]} for s in shoots), ("precondition", reason)
        p = _plan(CLIP_ASK, WHITE + [item], shoots=shoots, **kw)
        used = {m for x in p["options"] for m in (*x["media"], *x["previews"])}
        assert p["status"] == "ok" and (90 in used) == (reason is None), (reason, kw, p["status"], used)


def case_plan_gates_grown_fillable_rows():
    eff = [d.effective(r) for r in WHITE]
    other = d.fillable_rows([d.effective(_item(90, "explicit", "video", "$50", account_id="acct-b"))],
                            account_id="acct-b")
    assert [r["media_id"] for r in other] == [90], "precondition: Fillable for its own Creator"
    for how in ("append", "extend", "+="):
        fill = d.fillable_rows(eff, account_id=ACCT)
        if how == "append":
            fill.append(other[0])
        elif how == "extend":
            fill.extend(other)
        else:
            fill += other
        shoots = d.build_shoots(fill, [], [], {})
        assert any(90 in {int(r["media_id"]) for r in s["items"]} for s in shoots), ("precondition", how)
        p = d.plan(CLIP_ASK, shoots, fill, (), (), _cov(), None, account_id=ACCT,
                   live_ids=WHITE_IDS | {90})
        used = {m for x in p["options"] for m in (*x["media"], *x["previews"])}
        assert p["status"] == "ok" and 90 not in used, (how, p["status"], used)


def case_carried_why_never_trusted():
    clip = d.effective(_item(90, "explicit", "video", "$50"))
    forged_ok = {"solo": True, "rung": 2, "tier": "explicit", "closes": True, "payoff_acts": [],
                 "reveal": "", "clothing_state": "unclear", "beats": [], "acts": []}
    no_tier = {k: v for k, v in clip["fields"].items() if k != "explicitness"}
    disputed = {**clip["fields"], "explicitness": "suggestive", vault_ai_brief.SETTLED_KEY: ["nude_but_clothed"]}
    rows = [
        ({**_with(clip, people_count=2), "why": forged_ok}, "not_solo"),
        ({**clip, "fields": no_tier, "why": forged_ok}, "no_rung"),
        ({**clip, "fields": disputed, "why": forged_ok}, "unpriced_dispute"),
        ({**clip, "why": {**forged_ok, "solo": False, "rung": None}}, None),
    ]
    eff = [d.effective(r) for r in WHITE]
    for item, want in rows:
        assert d.fillable(item, account_id=ACCT) == want, (want, item.get("why"))
        p = d.plan(CLIP_ASK, d.build_shoots(eff + [item]), eff + [item], (), (), _cov(), None, account_id=ACCT)
        used = {m for x in p["options"] for m in (*x["media"], *x["previews"])}
        assert p["status"] == "ok" and (90 in used) == (want is None), (want, p["status"], used)


def case_plan_over_vault():
    rows = _seq({**S1, 3: ("1/3, ppv", "wanna see more? 😈", 0, (4,))})
    eff = [d.effective(r) for r in WHITE + RED + [_item(90, "explicit", "video", "$50", people_count=2)]]
    kept = [m for r in rows for m in d._media(r)]
    by_hand = d.plan(rows, d.build_shoots(d.fillable_rows(eff, account_id=ACCT), [[4, 33]], kept, {}), eff,
                     (), [[4, 33]], _cov(), None, account_id=ACCT, live_ids=[r["media_id"] for r in eff])
    got = d.plan_over_vault(rows, eff, (), [[4, 33]], {}, _cov(), None, account_id=ACCT)
    assert got == by_hand and got["status"] == "ok", (got["status"], by_hand["status"])
    assert "removed_media" not in _opts(got)[3]["flags"]
    gone = d.plan_over_vault(rows, [r for r in eff if r["media_id"] != 4], (), [[4, 33]], {}, _cov(), None,
                             account_id=ACCT)
    assert "removed_media" in _opts(gone)[3]["flags"], _opts(gone)[3]
    live = d.plan_over_vault(rows, [r for r in eff if r["media_id"] != 4], (), [[4, 33]], {}, _cov(), None,
                             account_id=ACCT, live_ids=WHITE_IDS)
    assert "removed_media" not in _opts(live)[3]["flags"], "explicit live_ids win"
    assert d.sequence_media_ids([{"media_json": json.dumps([{"id": 5}, 6, "x"]), "previews_json": "[7]"},
                                {"media": [{"id": 8}], "previews": None}]) == {5, 6, 7, 8}


def case_free_step_needs_free_safe():
    rows = _seq({1: ("1/2, freebie", "a gift", 0, ()), 7: ("2/2, ppv", "the full video", 0, ())})
    black = _white_like(600, "black")
    plain = _item(599, "sfw", lane="free", colour="black")
    p = _plan(rows, black + [plain])
    o = _opts(p)
    assert o[1]["media"] == [599], ("control: a free-safe 599 takes the free Step", o[1])
    bad = [
        (_with(plain, _jev=_jev("free", "photo", "n", breasts_bare="y")), "bare flag", "unpriced_dispute"),
        ({**plain, "folder_cents": 2000}, "folder price", None),
    ]
    for item, why, reason in bad:
        eff = d.effective(item)
        assert d.fillable(eff, account_id=ACCT) == reason, ("precondition", why, reason)
        p = _plan(rows, black + [item])
        o = _opts(p)
        assert p["status"] == "ok" and o[1]["media"] == [601], (why, o[1])
        assert all(599 not in x["previews"] for x in p["options"]), (why, "never a preview")


def case_no_dupe_set_repeat_in_a_slice():
    items = [r for r in WHITE if r["media_id"] not in (10, 11, 12)] + [_item(90, "explicit", lane="$50")]
    rows = _seq({1: ("1/2, freebie", "a gift", 0, ()), 3: ("1/2, ppv", "wanna see more?", 0, ()),
                 7: ("2/2, ppv", "2 pics", 0, ())})
    o = _opts(_plan(rows, items))
    assert _locked(o[7]) == [9, 90, 13], ("control: no dupe set, the 2-pics ask takes both", o[7])
    eff = [d.effective(r) for r in items]
    unaware = d.build_shoots(eff, [], [], {})
    fp = {"kind": "photo", "md5": "same", "dhash": 0, "ahash": 0}
    for p, why in ((_plan(rows, items, groups=[[9, 90]]), "dupe set"),
                   (_plan(rows, items, groups=[[9, 90]], shoots=unaware), "dupe set, Shoots built without it"),
                   (_plan(rows, items, prints={9: fp, 90: fp}), "near-dupe")):
        every = [m for x in p["options"] for m in x["media"]]
        assert p["status"] == "ok" and not {9, 90} <= set(every), (why, p["status"], every)
        assert len(set(every)) == len(every), why


def case_used_items_last():
    def picks(**kw):
        p = _plan(_seq(S1), WHITE + RED, **kw)
        assert p["status"] == "ok", p["status"]
        return {m for o in p["options"] for m in o["media"]}
    base = picks()
    assert {35, 36} <= base, ("control: the top red pair", base)
    got = picks(used=[35])
    assert 35 not in got and {11, 12} <= got, ("35 used elsewhere: the next pair of one Shoot", got)
    fresh = picks(used=sorted(base))
    assert fresh & base == {1, 8, 13, 37}, \
        ("a whole plan used elsewhere: reused only where the rest runs out (all 3 clips, a 3rd free-safe photo)",
         fresh & base)
    every = WHITE_IDS | RED_IDS
    assert picks(used=sorted(every)) == base, "everything used elsewhere: reused, same plan"


def case_same_step_share():
    rows = _seq({1: ("1/3, freebie", "gift", 0, ()), 7: ("3/3, ppv", "", 0, ())})
    rows += [_row(201, 3, "1/3, ppv", "wanna see?"), _row(202, 3, "1/3, ppv", "or this?"),
             _row(203, 3, "1/3, freebie", "did not buy? have this")]
    o = {x["id"]: x for x in _plan(rows, WHITE)["options"]}
    assert o[201]["media"] and o[201]["media"] == o[202]["media"], "same Step, Role and wants share"
    assert (o[103]["option"], o[201]["option"], o[202]["option"], o[203]["option"]) == (1, 2, 3, 4), \
        "option = 1-based by id within its Step"
    assert not set(o[203]["media"]) & set(o[201]["media"]), "a free alternative never gets the paid Slice"
    rows = _seq({7: ("2/2, ppv", "", 0, ())}) + [_row(211, 3, "1/2, ppv", "a video"), _row(212, 3, "1/2, ppv", "a pic")]
    o = {x["id"]: x for x in _plan(rows, WHITE)["options"]}
    assert o[211]["media"] and o[212]["media"] and not set(o[211]["media"]) & set(o[212]["media"]), \
        "different wants differ"


GREEN = ([_item(m, "sfw", colour="green") for m in (41, 42)]
         + [_item(m, "suggestive", colour="green") for m in (43, 44)]
         + [_item(m, "explicit", lane="$50", colour="green") for m in range(45, 53)]
         + [_item(53, "explicit", "video", "$50", colour="green")])


def case_free_leniency():
    p = _plan(_seq(S1), GREEN)
    o = _opts(p)
    assert p["status"] == "ok" and o[1]["media"] == [] and o[1]["flags"] == ["free_unfilled"], p
    assert all(o[s]["media"] for s in (3, 5, 7)), "every paid Step filled"
    o = _opts(_plan(_seq(S1), GREEN + WHITE))
    assert o[1]["media"] == [1] and o[1]["flags"] == [], ("any free-safe photo of the pool fills it", o[1])
    no_clip = [r for r in WHITE if r["kind"] == "photo"]
    assert _plan(_seq(S1), no_clip, remaining=40)["status"] == "not_enough_content"
    assert _plan(_seq(S1), no_clip, remaining=0)["status"] == "no_fit"
    kept = {**S1, 3: ("1/3, ppv", "", 0, (43,)), 5: ("2/3", "2 pics", 0, (45, 46)), 7: ("3/3, ppv", "", 0, (53,))}
    rows = _seq(kept)
    p = _plan(rows, GREEN)
    assert p["status"] == "already_filled" and _opts(p)[1]["flags"] == ["free_unfilled"], p
    assert p["fingerprint"] == d.fingerprint(rows, []), "empty write set"



def _priced(steps, items=WHITE, **kw):
    p = _plan(_seq(steps), items, **kw)
    return p["status"], p["conflict"], {s: o["price_cents"] for s, o in _opts(p).items()
                                        if not isinstance(s, tuple) and o["role"] == "paid_media"}


def case_pricing_table():
    mixed = [_item(61, "explicit", lane="$10", colour="blue"), _item(62, "explicit", lane="$50", colour="blue")]
    status, _, prices = _priced({3: ("1/1, ppv", "2 pics", 0, ())}, mixed)
    assert (status, prices) == ("ok", {3: 5000}), "photo Slice: its highest item"
    status, _, prices = _priced({3: ("1/1, ppv", "my video", 0, ())})
    assert prices == {3: 5000}, "clip Slice: the clip"
    rich = [_item(63, "explicit", lane="$50", colour="blue", folder_cents=30000)]
    assert _priced({3: ("1/1, ppv", "", 0, ())}, rich)[2] == {3: 20000}, "$200 cap"
    rows = [
        ({3: ("1/2, ppv", "only $15 babe", 0, ()), 7: ("2/2, ppv", "", 0, ())}, "ok", None, {3: 1500, 7: 5000},
         "quote kept unclamped"),
        ({3: ("1/1, ppv", "just $2", 0, ())}, "price_out_of_range",
         {"step": 3, "rule": "under_min", "price_cents": 200}, None, "$2 quote"),
        ({3: ("1/2, ppv", "", 5000, ()), 7: ("2/2, ppv", "for $20", 0, ())}, "price_conflict",
         {"step": 7, "rule": "quote_unholdable", "price_cents": 2000}, None, "quote under an earlier price"),
        ({3: ("1/2, ppv", "$80", 0, ()), 7: ("2/2, ppv", "", 5000, ())}, "price_conflict",
         {"step": 3, "rule": "quote_unholdable", "price_cents": 8000}, None, "quote over a later Fixed"),
        ({3: ("1/2, ppv", "", 3967, ()), 7: ("2/2, ppv", "pic", 0, ())}, "ok", None, {3: 3967, 7: 5000},
         "list above the earlier Fixed stays"),
        ({3: ("1/2, ppv", "", 1933, ()), 5: ("2/3", "a pic", 0, ()), 7: ("3/3, ppv", "", 3967, ())}, "ok", None,
         {3: 1933, 5: 3967, 7: 3967}, "clamped down to the next Fixed (list $50 > $39.67)"),
        ({3: ("1/2, ppv", "", 5000, ()), 5: ("2/2", "a pic", 0, ())}, "ok", None, {3: 5000, 5: 7500},
         "clamp up: $10 list after a $50 Fixed climbs the ladder to $75"),
        ({3: ("1/2, ppv", "", 5000, ()), 7: ("2/2, ppv", "", 3000, ())}, "price_conflict",
         {"step": 7, "rule": "below_earlier", "price_cents": 3000}, None, "descending Fixed"),
        ({3: ("1/1, ppv", "", 250, ())}, "price_out_of_range", {"step": 3, "rule": "under_min", "price_cents": 250},
         None, "Fixed in (0, $3)"),
        ({3: ("1/1, ppv", "", 25000, ())}, "price_out_of_range", {"step": 3, "rule": "over_max", "price_cents": 25000},
         None, "Fixed over $200"),
        ({3: ("1/2, ppv", "", 5000, ()), 12: ("2/2, ppv", "", 3000, ())}, "price_conflict",
         {"step": 12, "rule": "below_earlier", "price_cents": 3000}, None, "chat Steps between do not break it"),
    ]
    for steps, want_status, want_conflict, want_prices, why in rows:
        status, conflict, prices = _priced(steps)
        assert (status, conflict) == (want_status, want_conflict), (why, status, conflict)
        if want_prices is not None:
            assert {s: prices[s] for s in want_prices} == want_prices, (why, prices)
    rows = _seq({7: ("2/2, ppv", "", 4000, ())}) + [_row(301, 3, "1/2, ppv", "", 3000),
                                                   _row(302, 3, "1/2, ppv", "", 6000)]
    p = _plan(rows, WHITE)
    assert (p["status"], p["conflict"]) == ("price_conflict", {"step": 7, "rule": "below_earlier", "price_cents": 4000})
    gap = [_row(401, 1, "1/2, ppv", "", 5000), _row(402, 2, "bridge", "hey"), _row(405, 5, "2/2, ppv", "", 3000)]
    p = _plan(gap, WHITE)
    assert (p["status"], p["flags"]) == ("price_conflict", ["gap"]), p
    assert all(o["media"] == [] for o in p["options"])


FLAT = ([_item(m, "sfw", lane="free", colour="black") for m in (701, 702, 703)]
        + [_item(m, "suggestive", colour="black") for m in range(704, 712)])
FOUR = {1: ("1/5, freebie", "a gift", 0, ()), 3: ("2/5, ppv", "a pic", 0, ()), 5: ("3/5, ppv", "a pic", 0, ()),
        7: ("4/5, ppv", "a pic", 0, ()), 9: ("5/5, ppv", "a pic", 0, ())}


def case_ladder():
    status, _, prices = _priced(FOUR, FLAT)
    assert (status, prices) == ("ok", {3: 1000, 5: 1500, 7: 2300, 9: 3500}), \
        ("one List price climbs $10 -> $15 -> $23 -> $35", status, prices)
    rows = [
        ({3: ("1/2, ppv", "", 15000, ()), 5: ("2/2, ppv", "a pic", 0, ())}, {3: 15000, 5: 20000},
         "ladder $225 capped at $200"),
        ({3: ("1/3, ppv", "", 1000, ()), 5: ("2/3, ppv", "a pic", 0, ()), 7: ("3/3, ppv", "", 1200, ())},
         {3: 1000, 5: 1200, 7: 1200}, "ladder $15 capped by the next Fixed $12"),
        ({3: ("1/2, ppv", "", 20000, ()), 5: ("2/2, ppv", "a pic", 0, ())}, {3: 20000, 5: 20000},
         "at $200 already: flat at the cap, still nondecreasing"),
    ]
    for steps, want, why in rows:
        status, conflict, prices = _priced(steps, FLAT)
        assert (status, conflict, {s: prices[s] for s in want}) == ("ok", None, want), (why, status, prices)


def case_template_prices():
    tmpl = {3: 2500, 5: 4000, 7: 6000}
    p = _plan(_seq(S1), WHITE, template_prices=tmpl)
    o = _opts(p)
    assert p["status"] == "ok" and {s: o[s]["price_cents"] for s in (3, 5, 7)} == tmpl, "template prices used"
    assert all("template_price" in o[s]["flags"] and not o[s]["price_fixed"] for s in (3, 5, 7)), p["options"]
    rows = [
        (S1, {3: 200}, "ok", None, {3: 1000}, "under $3: ignored, List price"),
        (S1, {3: 25000}, "ok", None, {3: 1000}, "over $200: ignored, List price"),
        (S1, {3: 2500}, "ok", None, {3: 2500, 5: 5000, 7: 7500}, "template unclamped; List after it as before"),
        ({**S1, 3: ("1/3, ppv", "", 3000, ())}, {7: 4000}, "ok", None, {3: 3000, 5: 4000, 7: 4000},
         "Fixed then template: List clamped down to the template bound"),
        ({**S1, 3: ("1/3, ppv", "", 5000, ())}, {7: 3000}, "price_conflict",
         {"step": 7, "rule": "quote_unholdable", "price_cents": 3000}, None, "template under an earlier Fixed"),
        ({**S1, 7: ("3/3, ppv", "", 2000, ())}, {3: 2500}, "price_conflict",
         {"step": 3, "rule": "quote_unholdable", "price_cents": 2500}, None, "template over a later Fixed"),
        ({**S1, 3: ("1/3, ppv", "only $15 babe", 0, ())}, {3: 2500}, "ok", None, {3: 1500}, "a quote beats it"),
        ({**S1, 3: ("1/3, ppv", "", 3000, ())}, {3: 9000}, "ok", None, {3: 3000}, "a Fixed price beats it"),
    ]
    for steps, template, want_status, want_conflict, want_prices, why in rows:
        status, conflict, prices = _priced(steps, template_prices=template)
        assert (status, conflict) == (want_status, want_conflict), (why, status, conflict)
        if want_prices is not None:
            assert {s: prices[s] for s in want_prices} == want_prices, (why, prices)
    ignored = _opts(_plan(_seq(S1), WHITE, template_prices={3: 200}))[3]
    assert "template_price" not in ignored["flags"], ignored
    base = _plan(_seq(S1), WHITE)["fingerprint"]
    assert _plan(_seq(S1), WHITE, template_prices={3: 2500})["fingerprint"] != base
    assert _plan(_seq(S1), WHITE, template_prices={3: 200})["fingerprint"] == base
    via_vault = d.plan_from_vault(_seq(S1), [_raw(r) for r in WHITE], {}, account_id=ACCT, template_prices={3: 2500})
    assert _opts(via_vault)[3]["price_cents"] == 2500, "plan_from_vault passes template_prices through"


def case_status_order():
    reserved = _seq({3: ("1/1, freebie", "", 0, ())}, script="FM12")
    assert _plan(reserved, WHITE)["status"] == "reserved", "reserved beats no_paid_steps"
    assert _plan(_seq({}, script="FM12x"), WHITE)["status"] == "no_paid_steps", "FM12x is not reserved"
    filled_bad = _seq({3: ("1/1, ppv", "", 200, (4,))})
    assert _plan(filled_bad, WHITE)["status"] == "already_filled", "already_filled beats a bad Fixed price"
    both = _seq({3: ("1/2, ppv", "", 5000, ()), 5: ("2/2, ppv", "", 250, ())})
    assert _plan(both, WHITE)["status"] == "price_out_of_range", "out of range beats a conflict"
    assert _plan(_seq({3: ("1/1, ppv", "", 5000, ())}), [])["status"] == "no_fit", "assignment after prices"


def case_gap_flag():
    rows = [_row(1, 1, "1/2, ppv"), _row(2, 2, "bridge"), _row(3, 4, "2/2, ppv")]
    assert _plan(rows, WHITE)["flags"] == ["gap"]
    assert _plan(_seq(S1), WHITE)["flags"] == []


def case_describe_block():
    p = _plan(_seq(S1), [], remaining=40)
    assert p["describe"] == {"described": 300, "target": 340, "remaining": 40, "can_describe": True,
                             "blocked_reason": None}, p["describe"]
    p = _plan(_seq(S1), [], remaining=40, blocked="no Vault Pro access")
    assert p["describe"]["can_describe"] is False and p["describe"]["blocked_reason"] == "no Vault Pro access"
    assert _plan(_seq(S1), [], remaining=0)["describe"]["can_describe"] is False



def case_fingerprint():
    rows = _seq(S1)
    writes = [{"id": 103, "media": [4], "previews": [], "price_cents": 1000}]
    fp = d.fingerprint(rows, writes)
    assert fp == d.fingerprint([dict(r) for r in reversed(rows)], list(writes)), "stable, row order free"
    for key, value in (("text", "changed"), ("notes", "2/3, ppv"), ("price_cents", 999), ("script_step", 40),
                       ("media_json", json.dumps([{"id": 7}])), ("previews_json", json.dumps([7]))):
        changed = [dict(r) for r in rows]
        changed[2][key] = value
        assert d.fingerprint(changed, writes) != fp, key
    for w in ({**writes[0], "media": [5]}, {**writes[0], "previews": [4]}, {**writes[0], "price_cents": None}):
        assert d.fingerprint(rows, [w]) != fp, w
    assert d.fingerprint(rows, []) != fp
    a, b = _plan(rows, WHITE + RED), _plan(rows, WHITE + RED, used=[35])
    assert a["fingerprint"] != b["fingerprint"]


def case_undo_check_table():
    entry = {"id": 5, "media_ids": [2, 4], "previews": [2], "price_cents": 1000, "price_set": True}
    row = {"id": 5, "script_id": "Spicy intro", "media_json": json.dumps([{"id": 2}, {"id": 4}]),
           "previews_json": "[2]", "price_cents": 1000}
    rows = [
        (row, "ok", "unchanged"),
        (None, "missing", "gone or another account's"),
        ({**row, "script_id": "Other"}, "moved", "relabelled"),
        ({**row, "media_json": json.dumps([{"id": 4}])}, "edited", "media changed"),
        ({**row, "previews_json": "[]"}, "edited", "previews changed"),
        ({**row, "price_cents": 1500}, "edited", "price edited after the Fill"),
    ]
    for r, want, why in rows:
        assert d.undo_check(r, entry, "Spicy intro") == want, why
    fixed = {**entry, "price_cents": 3967, "price_set": False}
    assert d.undo_check({**row, "price_cents": 3967}, fixed, "Spicy intro") == "ok"
    assert d.undo_check({**row, "price_cents": 4000}, fixed, "Spicy intro") == "edited", "Fixed edited after"


def case_determinism():
    rows = _seq(S1)
    a = _plan(rows, WHITE + RED + GREEN)
    b = _plan([dict(r) for r in rows], WHITE + RED + GREEN)
    assert a == b, "same input twice -> identical plan"
    c = _plan(list(reversed(rows)), WHITE + RED + GREEN)
    assert c == a, "Sequence row order does not matter"



def _raw(r, **kw):
    out = {"media_id": r["media_id"], "kind": r["kind"], "created_at": r["created_at"].isoformat(),
           "duration_seconds": r["duration_seconds"], "ai_fields_json": json.dumps(r["fields"]),
           "describe_status": "described", "review_state": None, "removed_at": None,
           "operator_overrides_json": None, "refs": [], "account_id": ACCT}
    out.update(kw)
    return out


def case_plan_from_vault():
    raw = [_raw(r) for r in WHITE]
    raw[12]["refs"] = ["vf:7"]
    raw.append(_raw(_item(70, "explicit", "video", "$50"), removed_at="2026-07-02"))
    p = d.plan_from_vault(_seq(S1), raw, {"vf:7": 9900}, account_id=ACCT)
    o = _opts(p)
    assert p["status"] == "ok" and o[7]["media"] == [13] and o[7]["price_cents"] == 9900, p
    assert p["describe"]["described"] == 13 and p["describe"]["remaining"] == 0
    photos = [r for r in raw if r["kind"] == "photo"]
    undescribed = [_raw(_item(m, "suggestive"), describe_status=None) for m in (80, 81)]
    assert d.plan_from_vault(_seq(S1), photos + undescribed, {}, account_id=ACCT)["status"] == "not_enough_content"
    assert d.plan_from_vault(_seq(S1), photos, {}, account_id=ACCT)["status"] == "no_fit"


def case_describe_target_reexport():
    assert d.DESCRIBE_TARGET == vault_ai_vision_decide.DESCRIBE_TARGET == 1000


_harness.run()
