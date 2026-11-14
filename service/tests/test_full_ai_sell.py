#!/usr/bin/env python3
"""test_full_ai_sell — the Sell executor (`automations/full_ai_sell.py`, spec
03b › Interfaces, ticket 10 r3), pure tables plus the loader on a seeded temp DB.

  case_in_folders_table        empty include = all incl. unfiled; exclude wins;
                               a dead ref matches nothing; a non-empty include
                               never falls back to all
  case_list_price_table        ticket 10 r3 rows: Jev lanes, free lane 0, review
                               (clip too) None, shelf 50/10/0, explicit ladder
  case_clamp_table             [$10, $200]
  case_expand_owned_table      one copy owned = its whole dupe set
  case_pool_table              owned incl. dupe copies, review, disputed price,
                               no price, solo rule (sex / blowjob exempt) dropped
  case_pool_has_no_offer_cap   no offer history read; an unbought item stays
  case_pool_folder_filter      folder choice before dupe collapse; a row without
                               refs raises, never reads as unfiled
  case_pool_refusal_by_cause   no_match / no_priced_items / all_owned
  case_shoots_on_photo_only_pool  >= 1 shoot, rows + prints passed, no DB
  case_seed_format             pick:<account>:<fan>:<trigger_key>
  case_pick_same_seed_same_pick  same seed -> same Pick; the seed drives it
  case_pick_lowest_lane_at_or_above_target  intensity 1-2 $10, 3 $50, 4 $100
  case_pick_subjects           each Ask subject retrieves its own row
  case_pick_clip_is_one        a clip sells alone, no preview
  case_pick_photo_set_from_one_shoot  <= 4 locked + <= 1 free_ok preview, one
                               shoot, price = highest locked list
  case_pick_photo_outside_any_shoot_sells_alone
  case_pick_free               price 0, lowest lane, sent media (caller-removed)
                               excluded; no match (sent or Owned) -> the
                               lowest-lane unseen item, subject "anything"
  case_same_piece_table        (ticket 46) the teased set at today's list price,
                               free_ok previews kept; a locked id gone, unpriced
                               or free lane -> None (the caller re-picks)
  case_pick_refusals           no_match, no_priced_items
  case_load_rows_refs_and_dupes  seeded vault: vf: / of: refs (int or string
                               ids), packs, groups
  case_load_rows_fails_closed  dupe lookup / bad refs / rows error ->
                               inventory_unknown
  case_folder_price_*          an agency's folder price lists the item (no
                               explicit bump), review stays out, unpriced
                               unchanged; highest of several; heat targets with
                               $25 / $70; haggle floor from a custom list
  case_load_rows_folder_cents  vf: + of: prices -> highest per row; deleted
                               folder / other account ignored; error -> refusal
  case_claim_ok_table          counts, kinds, plurals, subject words vs the
                               Pick (ticket 45); a price or a time is no count
  case_price_ok_table          any price named = the PPV price; None / 0 (a
                               tease, a Free item): no price may be named
  case_fallback_caption_table  counts + kinds per kind; only offer has the
                               price; each fallback passes its own audit
  case_clamp_quote_table       (ticket 47) worked quotes: floor = max($10,
                               67 % of list up to a dollar), no amount = floor,
                               above list = list, cents round up to a dollar
  case_clamp_quote_sweep       every list $10..$200 x asked in {None, 0, 1c,
                               floor-1c, floor, list, list+1c, 10^6}: >= ceil
                               (0.67 list), >= $10, <= list, whole dollars
  case_quoted_cents_table      (ticket 47) each dollar spelling; two amounts,
                               an amount next to "tip", no amount -> None

Run: ./venv/bin/python service/tests/test_full_ai_sell.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

import inspect  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from unittest.mock import patch  # noqa: E402

import vault_ai_brief  # noqa: E402
import vault_dupes  # noqa: E402
import vault_folder_prices  # noqa: E402
import vault_jev_rules  # noqa: E402
import vault_scripts  # noqa: E402
import vault_topic_folders  # noqa: E402
from automations import full_ai_sell as fs  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, VaultFolder, VaultFolderItem, VaultItem  # noqa: E402

_harness.bootstrap()


def case_in_folders_table():
    rows = [
        # (refs, include, exclude, expected, why)
        ({"vf:1"}, [], [], True, "empty include = all"),
        (set(), [], [], True, "unfiled item, empty include"),
        (set(), [], ["vf:1"], True, "unfiled, exclude names another folder"),
        ({"vf:1", "of:9"}, [], ["of:9"], False, "exclude wins over all"),
        ({"vf:1"}, ["vf:1"], ["vf:1"], False, "exclude wins over include"),
        ({"vf:1"}, ["vf:1"], [], True, "included folder"),
        ({"of:9"}, ["of:9"], [], True, "included OF list"),
        ({"vf:1"}, ["vf:404"], [], False, "dead ref matches nothing"),
        ({"vf:1"}, ["vf:2"], [], False, "non-empty include, no match: never all"),
        (set(), ["vf:2"], [], False, "unfiled, non-empty include"),
    ]
    for refs, inc, exc, want, why in rows:
        assert fs.in_folders(refs, inc, exc) is want, why


# ── Fixtures: describe fields + a current Jev blob ───────────────────

def _flags(vulva="not_in_frame", breasts="not_in_frame", anus="not_in_frame", *, underwear=True,
           over_vulva="", over_breasts=""):
    """A complete flags answer (`vault_ai_brief.flags_known`)."""
    out = {"underwear_visible": underwear, "vulva_vis": vulva, "breasts_vis": breasts, "anus_vis": anus}
    if over_vulva:
        out["over_vulva"] = over_vulva
    if over_breasts:
        out["over_breasts"] = over_breasts
    return out


def _jev(lane5, *, kind="photo", read_lane5=None, breasts="n", crotch="n", pen="n", review=False, **tags):
    """A current `_jev` blob (`vault_jev_rules.current`): this VERSION, status ok, `lane5`, `state`;
    a clip also `vv` jv1 and `frames`. `tags` are Noul answers (`vault_topic_folders._tag`)."""
    j = {"v": vault_jev_rules.VERSION, "status": "ok", "lane5": lane5, "state": {}, "kind": kind,
         "breasts_bare": breasts, "crotch_bare": crotch, "penetration": pen, "tags": dict(tags)}
    if kind == "video":
        j.update(vv=vault_jev_rules.VIDEO_VERSION, frames=[])
    if read_lane5 is not None:
        j["read_lane5"] = read_lane5
    if review:
        j["review"] = True
    return j


SOLO = {"people_count": 1, "partner_visible": False}
# Shelf fixtures (no Jev blob), the `shelf_price` tiers: a flagged nude still with her pussy on show
# is the $50 reveal; breasts out with her pussy covered and something on is the $10; a dressed sfw
# still is neither.
SHELF_50 = {"clothing_state": "fully_nude", "acts": ["posing"], "penetration": "none",
            "explicitness": "explicit", **_flags(vulva="bare", breasts="bare", underwear=False), **SOLO}
SHELF_10 = {"clothing_state": "partially_off", "acts": ["posing"], "penetration": "none",
            "explicitness": "explicit", "clothing_items": ["white panties"],
            **_flags(vulva="covered", breasts="bare", over_vulva="white panties"), **SOLO}
SHELF_0 = {"clothing_state": "dressed", "acts": ["posing"], "penetration": "none", "explicitness": "sfw",
           **_flags(vulva="covered", breasts="covered", over_vulva="jeans", over_breasts="t-shirt"), **SOLO}


def _with_jev(fields, jev):
    return {**fields, vault_jev_rules.JEV_KEY: jev}


def _price(fields, kind="photo"):
    return fs.list_price_cents(vault_topic_folders.jev_of(fields), fields, kind)


def case_list_price_table():
    explicit = {"acts": ["fingering"]}
    rows = [
        # (fields, kind, expected cents, why) — ticket 10 r3 › List price
        (_with_jev({}, _jev("$10")), "photo", 1000, "Jev lane $10"),
        (_with_jev({}, _jev("$50")), "photo", 5000, "Jev lane $50"),
        (_with_jev({}, _jev("$100")), "photo", 10000, "Jev lane $100"),
        (_with_jev({}, _jev("free")), "photo", 0, "free lane: preview / gift only, never sold"),
        (_with_jev({}, _jev("review")), "photo", None, "review lane: no price"),
        (_with_jev({}, _jev("review", kind="video", read_lane5="$50")), "video", None,
         "review clip: review checked before lane_of (its read_lane5 is ignored)"),
        (_with_jev({}, _jev("$50", kind="video")), "video", 5000, "clip lane $50"),
        (_with_jev({}, _jev("odd")), "photo", None, "unknown lane: no price"),
        (_with_jev(explicit, _jev("$10")), "photo", 5000, "explicit act: $10 -> $50"),
        (_with_jev(explicit, _jev("$50")), "photo", 10000, "explicit act: $50 -> $100"),
        (_with_jev(explicit, _jev("$100")), "photo", 15000, "explicit act: $100 -> $150"),
        (_with_jev(explicit, _jev("free")), "photo", None, "explicit act is never free"),
        (SHELF_50, "photo", 5000, "no blob: shelf 50"),
        (SHELF_10, "photo", 1000, "no blob: shelf 10"),
        (SHELF_0, "photo", None, "no blob: shelf 0 -> no price, never free"),
        (SHELF_50, "video", None, "no blob: a clip's shelf is 0"),
        ({**SHELF_50, "acts": ["fingering"]}, "photo", 10000, "no blob: shelf 50 + explicit act -> $100"),
        (_with_jev(SHELF_0, {**_jev("$50"), "v": "old"}), "photo", None, "stale blob = no blob: shelf 0"),
    ]
    for fields, kind, want, why in rows:
        got = _price(fields, kind)
        assert got == want, (why, got)


def case_clamp_table():
    for cents, want in ((0, 1000), (500, 1000), (999, 1000), (1000, 1000), (15000, 15000),
                        (20000, 20000), (20001, 20000), (25000, 20000)):
        assert fs.clamp_cents(cents) == want, (cents, fs.clamp_cents(cents))


# ── Pool ─────────────────────────────────────────────────────────────

T0 = datetime(2026, 7, 1)
DRESSED = SHELF_0   # sfw, every region covered by clothing, solo: priced by its Jev lane alone


def _row(mid, fields, kind="photo", *, refs=(), packs=(), minutes=0):
    """A row shaped as `full_ai_sell.load_rows` returns it: `vault_scripts._load_rows`' keys + the
    item's folder `refs` and Pack categories."""
    fields = vault_ai_brief.settled_reading(fields)
    return {"media_id": mid, "kind": kind, "created_at": T0 + timedelta(minutes=minutes),
            "duration_seconds": 12 if kind == "video" else None, "fields": fields,
            "describe_status": "described", "score": vault_scripts.escalation_score(fields),
            "refs": set(refs), "packs": set(packs)}


ALL = {"include": [], "exclude": []}
TITS = fs.Ask("tits", "any", 2)
SEX = fs.Ask("sex", "any", 2)


def _ids(rows):
    assert not isinstance(rows, fs.Refusal), rows
    return {r["media_id"] for r in rows}


def _pool_rows():
    return [
        _row(1, _with_jev(DRESSED, _jev("$10"))),                       # kept unless owned
        _row(2, _with_jev(DRESSED, _jev("$10")), minutes=1),            # dupe copy of 1
        _row(3, _with_jev(DRESSED, _jev("review"))),                    # review lane: no price
        _row(4, _with_jev(DRESSED, _jev("$10", review=True))),          # disputed (jev_review), sfw tier
        _row(5, SHELF_0),                                               # no blob, shelf 0: no price
        _row(6, _with_jev({**DRESSED, "people_count": 2}, _jev("$50"))),  # partner in shot
        _row(7, _with_jev({k: v for k, v in DRESSED.items() if k not in SOLO}, _jev("$50"))),  # solo unknown
        _row(8, _with_jev(DRESSED, _jev("$50"))),                       # kept
        _row(9, _with_jev(DRESSED, _jev("free"))),                      # free lane: preview / gift only
    ]


def case_expand_owned_table():
    groups = [[1, 2, 3], [10, 11]]
    rows = [
        (set(), set(), "nothing owned"),
        ({2}, {1, 2, 3}, "a copy expands to its whole set"),
        ({10, 99}, {10, 11, 99}, "an id in no set stays itself"),
        ({3, 11}, {1, 2, 3, 10, 11}, "two sets"),
    ]
    for owned, want, why in rows:
        assert fs.expand_owned(owned, groups) == want, why


def case_pool_table():
    groups = [[1, 2]]
    rows = _pool_rows()
    assert _ids(fs.pool(rows, groups, set(), ALL, TITS)) == {1, 8, 9}, \
        "review lane, disputed price, no price, partner and unknown solo dropped; dupe 2 collapsed"
    assert _ids(fs.pool(rows, groups, {2}, ALL, TITS)) == {8, 9}, "owned copy 2 drops its kept original 1"
    assert _ids(fs.pool(rows, groups, {1}, ALL, TITS)) == {8, 9}, "owned original"
    assert _ids(fs.pool(rows, groups, set(), ALL, SEX)) == {1, 6, 7, 8, 9}, "sex: no solo rule"
    assert _ids(fs.pool(rows, groups, set(), ALL, fs.Ask("blowjob", "any", 2))) == {1, 6, 7, 8, 9}, \
        "blowjob: no solo rule"
    got = fs.pool(rows, groups, set(), ALL, TITS)
    assert {r["media_id"]: r["list_cents"] for r in got} == {1: 1000, 8: 5000, 9: 0}, "list price carried"
    assert all("why" in r for r in got), "rows carry the script why"


def case_pool_has_no_offer_cap():
    # The same unbought item stays however often it was offered: the pool reads no offer history.
    assert list(inspect.signature(fs.pool).parameters) == ["rows", "dupe_groups", "owned", "folders", "ask"]


def case_pool_folder_filter():
    rows = [_row(1, _with_jev(DRESSED, _jev("$10")), refs={"vf:1"}),
            _row(2, _with_jev(DRESSED, _jev("$10")), refs={"of:7"}),
            _row(3, _with_jev(DRESSED, _jev("$10")))]
    assert _ids(fs.pool(rows, [], set(), ALL, TITS)) == {1, 2, 3}, "empty include = all, unfiled too"
    assert _ids(fs.pool(rows, [], set(), {"include": ["of:7"], "exclude": []}, TITS)) == {2}
    assert _ids(fs.pool(rows, [], set(), {"include": [], "exclude": ["vf:1"]}, TITS)) == {2, 3}
    # Filter before collapse: a set's original outside the choice never stands in for its copy inside.
    assert _ids(fs.pool(rows, [[1, 2]], set(), {"include": ["of:7"], "exclude": []}, TITS)) == {2}
    # A row missing `refs` must not read as unfiled (it would slip past every exclude).
    bare = {k: v for k, v in rows[0].items() if k != "refs"}
    try:
        fs.pool([bare], [], set(), {"include": [], "exclude": ["vf:1"]}, TITS)
    except KeyError:
        pass
    else:
        raise AssertionError("a row without refs passed the folder filter")


def case_pool_refusal_by_cause():
    priced = _row(1, _with_jev(DRESSED, _jev("$10")), refs={"vf:1"})
    partner = _row(2, _with_jev({**DRESSED, "people_count": 2}, _jev("$10")))
    rows = [
        ([], [], set(), ALL, TITS, "no_match", "empty vault"),
        ([priced], [], set(), {"include": ["vf:404"], "exclude": []}, TITS, "no_match", "dead include ref"),
        ([_row(3, SHELF_0), _row(4, _with_jev(DRESSED, _jev("review")))], [], set(), ALL, TITS,
         "no_priced_items", "nothing priced"),
        ([partner], [], set(), ALL, TITS, "no_match", "only partner content for a solo ask"),
        ([priced], [], {1}, ALL, TITS, "all_owned", "he owns the only priced item"),
        ([priced, _row(5, _with_jev(DRESSED, _jev("$10")))], [[1, 5]], {5}, ALL, TITS, "all_owned",
         "he owns a copy of the only priced item"),
    ]
    for rws, groups, owned, folders, ask, want, why in rows:
        got = fs.pool(rws, groups, owned, folders, ask)
        assert got == fs.Refusal(want), (why, got)


# ── Shoots ───────────────────────────────────────────────────────────

WHITE = {**DRESSED, "clothing_items": ["white bra"]}   # outfit_key "white …"
RED = {**DRESSED, "clothing_items": ["red dress"]}


async def case_shoots_on_photo_only_pool():
    rows = [_row(m, _with_jev(WHITE, _jev("$10")), minutes=m) for m in (1, 2, 3)]
    pooled = fs.pool(rows, [], set(), ALL, TITS)
    # An account with no DB rows at all: rows and prints passed, so nothing is read.
    shoots = await fs.shoots_for("no-such-account", pooled, {})
    assert len(shoots) >= 1, shoots
    assert {r["media_id"] for r in shoots[0]["items"]} == {1, 2, 3}


# ── Pick ─────────────────────────────────────────────────────────────

TOPLESS_J = {"breasts": "y", "topless": "y"}     # Jev reads the `tits` topic


def _tits(mid, lane, kind="photo", fields=DRESSED, minutes=0):
    return _row(mid, _with_jev(fields, _jev(lane, kind=kind, **TOPLESS_J)), kind, minutes=minutes)


def _pick(rows, ask, *, shoots=(), seed="pick:a:f:t1", **kw):
    return fs.pick(fs.pool(rows, [], set(), ALL, ask), list(shoots), ask, seed=seed, **kw)


def case_seed_format():
    assert fs.seed_for("acct", "fan9", "m77") == "pick:acct:fan9:m77"


def case_pick_same_seed_same_pick():
    rows = [_tits(m, "$10") for m in range(1, 9)]
    ask = fs.Ask("tits", "photo", 1)
    first = _pick(rows, ask, seed="pick:a:f:t1")
    assert isinstance(first, fs.Pick), first
    for _ in range(3):
        assert _pick(rows, ask, seed="pick:a:f:t1") == first
    refs = {_pick(rows, ask, seed=f"pick:a:f:t{i}").ref for i in range(30)}
    assert len(refs) > 1, "the seed drives the draw"


def case_pick_lowest_lane_at_or_above_target():
    every = [_tits(1, "$10"), _tits(2, "$50"), _tits(3, "$100")]
    upper = [_tits(2, "$50"), _tits(3, "$100")]
    cheap = [_tits(1, "$10")]
    rows = [
        # (rows, intensity, expected list cents, why) — 1-2 -> $10, 3 -> $50, 4 -> $100
        (every, 1, 1000, "intensity 1 -> $10"),
        (every, 2, 1000, "intensity 2 -> $10"),
        (every, 3, 5000, "intensity 3 -> $50"),
        (every, 4, 10000, "intensity 4 -> $100"),
        (upper, 1, 5000, "nothing at $10: lowest above"),
        (cheap, 4, 1000, "nothing at or above $100: the subject's lowest"),
    ]
    for rws, heat, want, why in rows:
        got = _pick(rws, fs.Ask("tits", "photo", heat))
        assert isinstance(got, fs.Pick), (why, got)
        assert (got.list_cents, got.price_cents) == (want, want), (why, got)
    anything = _pick([_row(1, _with_jev(DRESSED, _jev("$10"))), _row(2, _with_jev(DRESSED, _jev("$50")))],
                     fs.Ask("anything", "any", 3))
    assert anything.ref == 2 and anything.lane == "$50", anything


def case_pick_subjects():
    j = {
        "feet": {}, "butt": {"butt_focus": "y"}, "tits": TOPLESS_J, "pussy": {"crotch": "y"},
        "nude": {"outfit": "nude"}, "lingerie": {"outfit": "lingerie_or_bodysuit"},
        "bikini": {"outfit": "swimwear"}, "shower": {"setting": "bathroom"},
        "toy": {"toy": "toy_visible_not_in_use"}, "masturbation": {}, "blowjob": {},
        "sex": {"people_count": "two_or_more"},
    }
    extra = {"masturbation": {"acts": ["fingering"]}, "blowjob": {"acts": ["blowjob"]},
             "sex": {"people_count": 2}}
    rows = []
    for mid, (subject, tags) in enumerate(j.items(), start=1):
        rows.append(_row(mid, _with_jev({**DRESSED, **extra.get(subject, {})}, _jev("$10", **tags)),
                         packs={"feet"} if subject == "feet" else ()))
    for mid, subject in enumerate(j, start=1):
        got = _pick(rows, fs.Ask(subject, "photo", 1))
        assert isinstance(got, fs.Pick) and got.media == (mid,), (subject, got)
        assert got.subject == subject
    assert isinstance(_pick(rows, fs.Ask("anything", "photo", 1)), fs.Pick)


def case_pick_clip_is_one():
    rows = [_tits(m, "$50", "video", fields=WHITE, minutes=m) for m in (1, 2, 3)]
    for fmt in ("video", "any"):
        got = _pick(rows, fs.Ask("tits", fmt, 3))
        assert isinstance(got, fs.Pick) and len(got.media) == 1 and got.previews == (), (fmt, got)
        assert got.format == "video" and got.ref == got.media[0] and got.price_cents == 5000
        assert got.facts["kinds"] == {"video": 1}, got.facts


async def case_pick_photo_set_from_one_shoot():
    white = [_tits(1, "$10", fields=WHITE, minutes=1), _tits(2, "$50", fields=WHITE, minutes=2),
             _tits(3, "$10", fields=WHITE, minutes=3), _tits(4, "$50", fields=WHITE, minutes=4),
             _tits(5, "$10", fields=WHITE, minutes=5), _tits(6, "$50", fields=WHITE, minutes=6)]
    free_safe = _row(7, _with_jev(WHITE, _jev("free")), minutes=7)               # the preview
    free_bare = _row(8, _with_jev(WHITE, _jev("free", breasts="y")), minutes=8)  # fails free_ok
    red = [_tits(20, "$50", fields=RED, minutes=600), _tits(21, "$50", fields=RED, minutes=601)]
    ask = fs.Ask("tits", "photo", 3)
    pooled = fs.pool([*white, free_safe, free_bare, *red], [], set(), ALL, ask)
    shoots = await fs.shoots_for("no-such-account", pooled, {})
    shoot_of = {r["media_id"]: i for i, s in enumerate(shoots) for r in s["items"]}
    seen_white = False
    for i in range(20):
        got = fs.pick(pooled, shoots, ask, seed=f"pick:a:f:t{i}")
        assert isinstance(got, fs.Pick), got
        assert 1 <= len(got.media) <= 4 and len(got.previews) <= 1, got
        assert len({shoot_of[m] for m in (*got.media, *got.previews)}) == 1, ("one shoot", got)
        assert got.ref == got.media[0] and got.format == "photo"
        assert got.price_cents == got.list_cents == 5000, "price = highest locked list ($50 anchor)"
        assert 8 not in got.previews, "a preview passes free_ok"
        assert not set(got.media) & {7, 8}, "free-lane items are never locked"
        if got.ref in {2, 4, 6}:
            seen_white = True
            assert len(got.media) == 4 and got.previews == (7,), got
            assert {m for m in got.media if m in {1, 3, 5}}, "a $10 photo rides under the $50 price"
    assert seen_white


def case_pick_photo_outside_any_shoot_sells_alone():
    got = _pick([_tits(1, "$10")], fs.Ask("tits", "photo", 1), shoots=[])
    assert isinstance(got, fs.Pick) and got.media == (1,) and got.previews == ()


def case_pick_free():
    rows = [_tits(1, "$10"), _tits(2, "$50"), _row(3, _with_jev(DRESSED, _jev("free")))]
    ask = fs.Ask("tits", "photo", 4)
    pooled = fs.pool(rows, [], set(), ALL, ask)

    def unsent(sent):   # the sell step's half: pool minus every media already sent to him
        return [r for r in pooled if r["media_id"] not in sent]

    rows_ = [
        # (sent, expected media, expected subject, why)
        ((), (1,), "tits", "lowest matching lane first, heat ignored"),
        ({1}, (2,), "tits", "sent media excluded"),
        ({1, 2}, (3,), "anything", "no unseen match: the lowest-lane unseen item, subject not claimed"),
    ]
    for sent, want, subject, why in rows_:
        got = fs.pick(unsent(sent), [], ask, seed="pick:a:f:t1", free=True)
        assert isinstance(got, fs.Pick), (why, got)
        assert got.media == want and got.price_cents == 0 and got.previews == (), (why, got)
        assert got.subject == subject, (why, got)
    assert fs.pick(unsent({1, 2, 3}), [], ask, seed="s", free=True) == fs.Refusal("all_owned"), \
        "everything sent"
    assert "sent" not in inspect.signature(fs.pick).parameters, "the caller subtracts sent media"
    # make_right after a Buy: he owns every match of the asked subject. `pool` keeps the rest and
    # `pick`'s own fallback gives the lowest-lane unseen item, never claiming the subject.
    owned_all = [_tits(10, "$10"), _tits(11, "$50"),
                 _row(12, _with_jev(DRESSED, _jev("$50"))), _row(13, _with_jev(DRESSED, _jev("$10")))]
    left = fs.pool(owned_all, [], {10, 11}, ALL, ask)
    assert _ids(left) == {12, 13}, "pool never matches the subject"
    got = fs.pick(left, [], ask, seed="pick:a:f:t1", free=True)
    assert isinstance(got, fs.Pick), got
    assert got.media == (13,) and got.subject == "anything" and got.price_cents == 0, got


def case_same_piece_table():
    """Ticket 46: a Pending tease's piece re-validated against today's pool."""
    ask = fs.Ask("tits", "photo", 2)
    photos = [_tits(1, "$10", fields=WHITE, minutes=1), _tits(2, "$50", fields=WHITE, minutes=2)]
    preview = _row(7, _with_jev(WHITE, _jev("free")), minutes=7)                  # free-safe
    bare = _row(8, _with_jev(WHITE, _jev("free", breasts="y")), minutes=8)       # fails free_ok
    pooled = fs.pool([*photos, preview, bare], [], set(), ALL, ask)
    got = fs.same_piece(pooled, (1, 2), (7, 8), ask)
    assert isinstance(got, fs.Pick), got
    assert (got.media, got.previews, got.ref) == ((1, 2), (7,), 1), "same set; free_ok previews kept"
    assert got.price_cents == got.list_cents == 5000, "today's list: the highest locked"
    assert got.subject == "tits" and got.format == "photo", got
    repriced = fs.pool([_tits(1, "$50", fields=WHITE, minutes=1), _tits(2, "$50", fields=WHITE, minutes=2)],
                       [], set(), ALL, ask)
    assert fs.same_piece(repriced, (1,), (), ask).price_cents == 5000, "a teased $10 sells at today's $50"
    rows = [
        # (pool, locked, previews, why)
        (pooled, (), (), "nothing locked"),
        ([r for r in pooled if r["media_id"] != 2], (1, 2), (7,), "a companion gone: re-pick, never the rest"),
        (pooled, (1, 7), (), "a locked id now free lane"),
        (pooled, (99,), (), "not in the pool (removed / owned)"),
    ]
    for pool_, locked, previews, why in rows:
        assert fs.same_piece(pool_, locked, previews, ask) is None, why
    got = fs.same_piece([r for r in pooled if r["media_id"] != 7], (1, 2), (7,), ask)
    assert got.media == (1, 2) and got.previews == (), "a preview gone: the piece sells without it"


def case_pick_refusals():
    tits = [_tits(1, "$10")]
    assert _pick(tits, fs.Ask("feet", "photo", 1)) == fs.Refusal("no_match"), "no feet in the pool"
    assert _pick(tits, fs.Ask("tits", "video", 1)) == fs.Refusal("no_match"), "no clip in the pool"
    swim = [_row(1, _with_jev(DRESSED, _jev("free", outfit="swimwear")))]
    assert _pick(swim, fs.Ask("bikini", "photo", 1)) == fs.Refusal("no_priced_items"), \
        "only a free-lane match: nothing to sell"


# ── Loader (seeded temp DB) ──────────────────────────────────────────

async def _seed_vault(aid: str, items: list[tuple], folders: list[tuple]) -> dict[str, int]:
    """items = [(media_id, of_folder_ids raw, removed?)]; folders = [(name, deleted?, [media ids])].
    Returns {folder name: id}."""
    async with get_session() as s:
        s.add(Account(id=aid))
        await s.commit()
    ids: dict[str, int] = {}
    async with get_session() as s:
        for mid, raw, removed in items:
            s.add(VaultItem(account_id=aid, media_id=mid, kind="photo", created_at=T0 + timedelta(minutes=mid),
                            tags="[]", describe_status="described", of_folder_ids=raw,
                            removed_at=T0 if removed else None,
                            ai_fields_json=json.dumps(_with_jev(DRESSED, _jev("$10")))))
        for name, deleted, members in folders:
            f = VaultFolder(account_id=aid, name=name, deleted_at=T0 if deleted else None)
            s.add(f)
            await s.flush()
            ids[name] = f.id
            for mid in members:
                s.add(VaultFolderItem(account_id=aid, folder_id=f.id, media_id=mid))
        await s.commit()
    return ids


async def _clusters(*_a, **_k):
    return {"clusters": [{"original": {"media_id": 101}, "dupes": [{"media_id": 102}]}]}


async def _boom(*_a, **_k):
    raise RuntimeError("dupe scan down")


async def case_load_rows_refs_and_dupes():
    aid = "sell-load-1"
    ids = await _seed_vault(aid, [(101, '["7", 8]', False), (102, None, False), (103, "[]", False),
                                  (104, None, False), (105, "[9]", True)],
                            [("AI-tits $10", False, [102]), ("old", True, [103]),
                             ("feet-nude", False, [104])])
    with patch.object(vault_dupes, "find_duplicates", _clusters):
        got = await fs.load_rows(aid)
    assert not isinstance(got, fs.Refusal), got
    rows, groups, prints = got
    by_id = {r["media_id"]: r for r in rows}
    assert set(by_id) == {101, 102, 103, 104}, "removed item 105 is not in the vault"
    assert by_id[101]["refs"] == {"of:7", "of:8"}, "a string id and an int id read alike"
    assert by_id[102]["refs"] == {f"vf:{ids['AI-tits $10']}"}
    assert by_id[103]["refs"] == set(), "a deleted folder gives no ref"
    assert by_id[104]["refs"] == {f"vf:{ids['feet-nude']}"} and by_id[104]["packs"] == {"feet"}
    assert by_id[101]["packs"] == set()
    assert groups == [[101, 102]]
    assert isinstance(prints, dict)
    assert vault_topic_folders.jev_of(by_id[101]["fields"]) is not None, "fields read as _load_rows reads them"


async def case_load_rows_fails_closed():
    aid = "sell-load-2"
    await _seed_vault(aid, [(201, "[1]", False)], [])
    with patch.object(vault_dupes, "find_duplicates", _boom):
        assert await fs.load_rows(aid) == fs.Refusal("inventory_unknown"), "dupe lookup down"
    aid = "sell-load-3"
    await _seed_vault(aid, [(301, "not json", False)], [])
    with patch.object(vault_dupes, "find_duplicates", _clusters):
        assert await fs.load_rows(aid) == fs.Refusal("inventory_unknown"), "bad of_folder_ids"
    with patch.object(vault_scripts, "_load_rows", _boom):
        assert await fs.load_rows(aid) == fs.Refusal("inventory_unknown"), "rows unreadable"


# ── Folder prices (an agency's price per folder, `vault_folder_prices`) ──

def _priced(row, cents):
    """`row` as `load_rows` gives it when its folders carry a price (`folder_cents`)."""
    return {**row, "folder_cents": cents}


def case_folder_price_list_table():
    explicit = {"acts": ["fingering"]}
    rows = [
        # (fields, kind, folder cents, expected, why)
        (_with_jev({}, _jev("$10")), "photo", 2500, 2500, "folder price replaces the $10 lane"),
        (_with_jev({}, _jev("$100")), "photo", 2500, 2500, "a folder price under the lane wins too"),
        (_with_jev(explicit, _jev("$10")), "photo", 2500, 2500, "no explicit bump on a folder price"),
        (_with_jev({}, _jev("free")), "photo", 3000, 3000, "a free-lane item in a priced folder is sold"),
        (_with_jev({}, _jev("review")), "photo", 9000, None, "review stays not for sale"),
        (_with_jev({}, _jev("review", kind="video", read_lane5="$50")), "video", 9000, None, "review clip too"),
        (SHELF_0, "photo", 4000, 4000, "no blob, shelf 0: the folder price"),
        (_with_jev({}, _jev("$50")), "photo", None, 5000, "no folder price: lane unchanged"),
        (_with_jev({}, _jev("$10")), "photo", 99999, 20000, "clamped to $200"),
    ]
    for fields, kind, folder, want, why in rows:
        got = fs.list_price_cents(vault_topic_folders.jev_of(fields), fields, kind, folder)
        assert got == want, (why, got)
    assert (fs.MIN_CENTS, fs.MAX_CENTS) == (vault_folder_prices.MIN_CENTS, vault_folder_prices.MAX_CENTS)


def case_folder_price_pool():
    rows = [_priced(_row(1, _with_jev(DRESSED, _jev("$10")), refs={"vf:1"}), 2500),
            _priced(_row(2, _with_jev(DRESSED, _jev("review")), refs={"vf:1"}), 2500),
            _priced(_row(3, _with_jev(DRESSED, _jev("$50"))), None),
            _row(4, _with_jev(DRESSED, _jev("$100")))]          # no folder_cents key at all
    got = fs.pool(rows, [], set(), ALL, TITS)
    assert {r["media_id"]: r["list_cents"] for r in got} == {1: 2500, 3: 5000, 4: 10000}, \
        "override; review out; unpriced and key-less rows unchanged"
    owned = fs.pool(rows, [[1, 4]], {4}, ALL, TITS)
    assert _ids(owned) == {3}, "owned / dupe rules unchanged on a priced item"
    only = fs.pool(rows, [], set(), {"include": [], "exclude": ["vf:1"]}, TITS)
    assert _ids(only) == {3, 4}, "folder filter unchanged"


def case_folder_price_highest_of_several():
    prices = {"vf:1": 2500, "of:7": 7000, "vf:9": 1500}
    for refs, want in (({"vf:1", "of:7"}, 7000), ({"vf:1", "vf:9"}, 2500), ({"vf:2"}, None), (set(), None)):
        assert vault_folder_prices.highest(refs, prices) == want, refs


def case_folder_price_pick_heat_targets():
    every = [_priced(_tits(1, "$10"), 2500), _priced(_tits(2, "$10"), 7000), _priced(_tits(3, "$100"), 12000)]
    low = [_priced(_tits(1, "$10"), 2500), _priced(_tits(2, "$10"), 7000)]
    above = [_priced(_tits(2, "$10"), 7000), _priced(_tits(3, "$10"), 12000)]
    rows = [
        # (rows, intensity, expected list cents, why) — targets $10 / $50 / $100, lowest at or above, else lowest
        (every, 1, 2500, "heat 1: $25 is the lowest at or above $10"),
        (every, 3, 7000, "heat 3: $70 is the lowest at or above $50"),
        (every, 4, 12000, "heat 4: $120 is the lowest at or above $100"),
        (low, 4, 2500, "nothing at or above $100: the lowest"),
        (above, 1, 7000, "heat 1: lowest above $10"),
    ]
    for rws, heat, want, why in rows:
        got = _pick(rws, fs.Ask("tits", "photo", heat))
        assert isinstance(got, fs.Pick), (why, got)
        assert (got.list_cents, got.price_cents) == (want, want), (why, got)
    odd = _pick([_priced(_tits(1, "$10"), 2499)], fs.Ask("tits", "photo", 1))
    assert odd.lane == "$24.99" and odd.price_cents == 2499, odd
    assert _pick(low, fs.Ask("tits", "photo", 1)).lane == "$25"


def case_folder_price_haggle_floor():
    for list_cents, asked, want in ((7000, None, 4700), (7000, 3000, 4700), (7000, 6000, 6000),
                                    (2500, None, 1700), (2499, None, 1700), (2500, 9000, 2500)):
        assert fs.clamp_quote(list_cents, asked) == want, (list_cents, asked, fs.clamp_quote(list_cents, asked))


async def case_load_rows_folder_cents():
    aid = "sell-load-prices"
    ids = await _seed_vault(aid, [(401, '["7"]', False), (402, None, False), (403, None, False), (404, None, False)],
                            [("cheap", False, [401, 402]), ("gone", True, [403])])
    await _seed_vault("sell-load-prices-other", [], [])
    await vault_folder_prices.put(aid, f"vf:{ids['cheap']}", 2500)
    await vault_folder_prices.put(aid, "of:7", 7000)
    await vault_folder_prices.put(aid, f"vf:{ids['gone']}", 9000)
    await vault_folder_prices.put("sell-load-prices-other", "of:7", 15000)
    with patch.object(vault_dupes, "find_duplicates", _clusters):
        rows, _groups, _prints = await fs.load_rows(aid)
    by_id = {r["media_id"]: r["folder_cents"] for r in rows}
    assert by_id == {401: 7000, 402: 2500, 403: None, 404: None}, \
        "highest of vf + of; a deleted folder's price and another account's ignored"
    pooled = fs.pool(rows, [], set(), ALL, TITS)
    assert {r["media_id"]: r["list_cents"] for r in pooled} == {401: 7000, 402: 2500, 403: 1000, 404: 1000}
    await vault_folder_prices.put(aid, "of:7", None)
    with patch.object(vault_dupes, "find_duplicates", _clusters):
        rows, _g, _p = await fs.load_rows(aid)
    assert {r["media_id"]: r["folder_cents"] for r in rows}[401] == 2500, "cleared OF price"
    with patch.object(vault_folder_prices, "load", _boom), patch.object(vault_dupes, "find_duplicates", _clusters):
        assert await fs.load_rows(aid) == fs.Refusal("inventory_unknown"), "prices unreadable: fail closed"


# ── Claim audit + fallback caption (ticket 45) ───────────────────────

CLIP, SET4, MIX = {"video": 1}, {"photo": 4}, {"photo": 2, "video": 1}


def _cpick(kinds, price=2500, subject="anything", description=""):
    n = sum(kinds.values())
    return fs.Pick(ref=1, media=tuple(range(1, n + 1)), previews=(), price_cents=price,
                   list_cents=price or 1000, subject=subject, format=next(iter(kinds)), lane="$10",
                   facts={"kinds": kinds, "items": [], "description": description})


def case_claim_ok_table():
    rows = [
        # (text, pick, expected, why)
        ("5 videos just for u", _cpick(CLIP), False, "count and plural over one clip"),
        ("my new video just for u 😏", _cpick(CLIP), True, "one clip, one video"),
        ("a hot vid babe", _cpick(CLIP), True, "a = 1"),
        ("videos of me", _cpick(CLIP), False, "plural on one clip"),
        ("my pics for u", _cpick(CLIP), False, "a kind the Pick lacks"),
        ("4 pics from my shoot", _cpick(SET4), True, "the count"),
        ("four pics", _cpick(SET4), True, "a number word"),
        ("3 pics", _cpick(SET4), False, "wrong count"),
        ("a pic just for u", _cpick(SET4), False, "a = 1 over four"),
        ("a vid", _cpick(SET4), False, "no clip in a photo set"),
        ("2 pics + 1 vid", _cpick(MIX), True, "each kind its own count"),
        ("a 5 minute video", _cpick(CLIP), True, "a time is no count"),
        ("$25 vid just for u", _cpick(CLIP), True, "a price is no count"),
        ("a few pics", _cpick(SET4), True, "a quantity word is no count"),
        ("all my content babe", _cpick(SET4), True, "a generic media word claims no kind"),
        ("hey babe wyd", _cpick(CLIP), True, "no claim"),
        ("", _cpick(CLIP), True, "empty text claims nothing"),
        ("my feet in this one", _cpick(CLIP, subject="feet"), True, "the Pick's subject"),
        ("my toes for u", _cpick(CLIP, subject="feet"), True, "a word of the subject"),
        ("my ass in this one", _cpick(CLIP, subject="feet"), False, "a subject the Pick lacks"),
        ("my ass in this one", _cpick(CLIP, description="bent over showing her butt"), True,
         "a subject its describe text names"),
        ("my tits babe", _cpick(SET4, subject="anything"), False, "anything names no subject"),
    ]
    for text, pick, want, why in rows:
        assert fs.claim_ok(text, pick) is want, (why, text)


def case_price_ok_table():
    rows = [
        # (text, price_cents, expected, why)
        ("its $25 to unlock", 2500, True, "the price"),
        ("25$ babe", 2500, True, "symbol after"),
        ("$25.00", 2500, True, "cents spelled"),
        ("only 25 bucks", 2500, True, "bucks"),
        ("25 dollars", 2500, True, "dollars"),
        ("$20 to unlock", 2500, False, "another price"),
        ("$25 now, was $50", 2500, False, "every price named must be the price"),
        ("€25", 2500, True, "a euro amount is still a price named"),
        ("4 pics for u", 2500, True, "a count is no price"),
        ("unlock it babe", 2500, True, "naming no price is fine on an offer"),
        ("$10 to unlock", None, False, "no price allowed (tease)"),
        ("€10", None, False, "no price allowed, any currency"),
        ("4 pics for u", None, True, "no price named"),
        ("$0", 0, False, "free: no money talk"),
        ("just for u", 0, True, "free, nothing named"),
        ("this one's free for u babe", 5000, False, "free on a priced PPV (rwl fa3 S4)"),
        ("FREE for u today", 5000, False, "free, any case"),
        ("free? no babe, $50 to unlock", 5000, False, "any free claim on a priced PPV"),
        ("feel free to unlock it", 5000, False, "the word alone fails: no reading of intent"),
        ("freestyle vid for u, $50", 5000, True, "free only as a word"),
        ("this one's free for u babe", 0, True, "a Free item may say free"),
        ("free for u", None, True, "a tease names no price, free is fine"),
    ]
    for text, cents, want, why in rows:
        assert fs.price_ok(text, cents) is want, (why, text)


def case_fallback_caption_table():
    rows = [
        # (pick, kind, expected)
        (_cpick(CLIP, 2500), "offer", "1 vid, $25 to unlock"),
        (_cpick(SET4, 1050), "offer", "4 pics, $10.50 to unlock"),
        (_cpick(MIX, 5000), "offer", "2 pics + 1 vid, $50 to unlock"),
        (_cpick(SET4, 5000), "tease", "4 pics"),
        (_cpick(CLIP, 2500), "tease", "1 vid"),
        (_cpick(MIX, 0), "free", "2 pics + 1 vid"),
    ]
    for pick, kind, want in rows:
        got = fs.fallback_caption(pick, kind)
        assert got == want, (kind, got)
        assert fs.claim_ok(got, pick), ("the fallback passes the claim audit", got)
        assert fs.price_ok(got, pick.price_cents if kind == "offer" else None), ("and the price check", got)
        assert ("$" in got) is (kind == "offer"), ("only an offer names money", got)



# ── Haggle quote (ticket 47; spec › Interfaces `clamp_quote`, `quoted_cents`) ──

def case_clamp_quote_table():
    rows = [
        # (list, asked, expected, why) — worked by hand from the spec's formula
        (5000, 2000, 3400, "spec example: $50 list, $20 asked -> 67 % = $33.50 -> $34"),
        (5000, None, 3400, "no amount -> the floor"),
        (5000, 4000, 4000, "inside the range: his amount"),
        (5000, 3950, 4000, "cents round up to a whole dollar"),
        (5000, 6000, 5000, "above list -> list"),
        (5000, 3401, 3500, "a cent over the floor rounds up to the next dollar"),
        (10000, 5000, 6700, "67 % of $100 is exactly $67 (no float drift to $68)"),
        (10000, None, 6700, "floor of $100"),
        (20000, 1, 13400, "$200 list: floor $134"),
        (1000, None, 1000, "$10 list: 67 % = $6.70, the $10 minimum wins"),
        (1000, 500, 1000, "never under $10"),
        (1500, None, 1100, "$15 list: 67 % = $10.05 -> $11"),
        (1400, 0, 1000, "$14 list: 67 % = $9.38 -> $10"),
        (9900, None, 6700, "$99 list: 67 % = $66.33 -> $67"),
    ]
    for list_cents, asked, want, why in rows:
        got = fs.clamp_quote(list_cents, asked)
        assert got == want, (why, list_cents, asked, got)


def case_clamp_quote_sweep():
    """The property sweep: every list $10..$200 at $1 steps, eight asked amounts each."""
    n = 0
    for dollars in range(10, 201):
        lst = dollars * 100
        least = -(-67 * lst // 100)          # ceil(0.67 * list) in exact integers
        floor = max(1000, -(-least // 100) * 100)
        for asked in (None, 0, 1, floor - 1, floor, lst, lst + 1, 10 ** 6):
            got = fs.clamp_quote(lst, asked)
            assert isinstance(got, int), (lst, asked, got)
            assert got >= least and got >= 1000 and got <= lst and got % 100 == 0, (lst, asked, got)
            n += 1
    assert n == 191 * 8, n


def case_quoted_cents_table():
    rows = [
        # (his text, expected cents, why)
        ("would you do $20?", 2000, "$ before"),
        ("would you do 20$", 2000, "$ after"),
        ("$ 25 ok?", 2500, "$ then a space"),
        ("I'd pay 30 dollars", 3000, "dollars"),
        ("31 dollar max", 3100, "dollar"),
        ("40 bucks and it's mine", 4000, "bucks"),
        ("45 USD max", 4500, "usd, any case"),
        ("$19.99?", 1999, "cents kept (clamp_quote rounds)"),
        ("would you do $20 or $25?", None, "two amounts"),
        ("$20 now and $30 later", None, "two amounts"),
        ("I'll tip $20", None, "tip right before"),
        ("here's a $20 tip", None, "tip right after"),
        ("I'll tip you 20 bucks", None, "tip two words before"),
        ("tipping $15 if u send it", None, "tipping"),
        ("would you do 20?", None, "a bare number names no dollars"),
        ("can u do it cheaper", None, "no amount"),
        ("", None, "empty"),
    ]
    for text, want, why in rows:
        got = fs.quoted_cents(text)
        assert got == want, (why, text, got)


_harness.run()
