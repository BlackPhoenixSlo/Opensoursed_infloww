#!/usr/bin/env python3
from __future__ import annotations

import _harness
from _jev_fixtures import mapped  # noqa: E402

from _full_ai_sell_helpers import (  # noqa: E402
    A, OWNER_A, FakePriceJev, _body, _db, _guarded, _post, _price, _put_draft, _reply, _rows, _vault,
)
import contextlib  # noqa: E402
from dataclasses import replace  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from sqlalchemy import update  # noqa: E402

from _full_ai_fixtures import QUIET_SCENE, QUIET_TEST  # noqa: E402
import vault_ai_brief  # noqa: E402
import vault_jev_rules  # noqa: E402
from automations import _price_jev, full_ai_sell as fs, full_ai_writers as wr  # noqa: E402
from automations.full_ai_config import DEFAULTS  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import VaultItem  # noqa: E402


T0 = datetime(2026, 7, 1)
DRESSED = {"clothing_state": "dressed", "acts": ["posing"], "penetration": "none", "explicitness": "sfw",
           "underwear_visible": True, "vulva_vis": "covered", "breasts_vis": "covered",
           "anus_vis": "not_in_frame", "over_vulva": "jeans", "over_breasts": "t-shirt",
           "people_count": 1, "partner_visible": False}
TOY_J = {"toy": "toy_visible_not_in_use"}
ALL = {"include": [], "exclude": []}
TOY = fs.Ask("toy", "photo", 3)
SEED = "pick:a:f:t1"


def _jev(lane5, kind="photo", **tags):
    j = {"v": vault_jev_rules.VERSION, "status": "ok", "lane5": lane5, "state": {}, "kind": kind,
         "breasts_bare": "n", "crotch_bare": "n", "penetration": "n", "tags": dict(tags)}
    if kind == "video":
        j.update(vv=vault_jev_rules.VIDEO_VERSION, frames=[])
    return j


def _row(mid, lane="$50", kind="photo"):
    fields = vault_ai_brief.settled_reading(mapped({**DRESSED, vault_jev_rules.JEV_KEY: _jev(lane, kind, **TOY_J)}))
    return {"media_id": mid, "kind": kind, "created_at": T0 + timedelta(minutes=mid),
            "duration_seconds": 12 if kind == "video" else None, "fields": fields,
            "describe_status": "described", "score": 0, "refs": set(), "packs": set()}


def _shoot(*ids):
    return {"items": [{"media_id": i} for i in ids]}


def _clip(mid, lane="$10"):
    return _row(mid, lane, kind="video")


def _pick(rows, shoots=(), ask=TOY, *, groups=(), owned=(), seed=SEED, **kw):
    pool = fs.pool(rows, [list(g) for g in groups], set(owned), ALL, ask)
    assert isinstance(pool, list), pool
    return fs.pick(pool, list(shoots), ask, seed=seed, **kw)


def _cents(rows):
    pool = fs.pool(rows, [], set(), ALL, fs.Ask("anything", "any", 1))
    return {r["media_id"]: r["list_cents"] for r in pool}


def case_pick_fill_table():
    six = [_row(i) for i in range(1, 7)]
    got = _pick(six + [_row(40), _row(41)], [_shoot(*range(1, 7))], bundle="fill")
    assert len(got.media) == 5 and set(got.media) <= set(range(1, 7)), got.media
    two = [_row(10), _row(11), _row(20, "$10"), _row(21, "$100"), _row(22, "$10")]
    got = _pick(two, [_shoot(10, 11)], bundle="fill")
    assert got.media[:2] in ((10, 11), (11, 10)) and len(got.media) == 3, got.media
    assert got.media[2] in (20, 22) and 21 not in got.media, got.media
    assert got.list_cents == 5000 == got.price_cents, got
    rows = [_row(30), _row(31, "$10"), _row(32, "$10"), _row(33, "$50"), _row(34, "$100"), _row(35, "$10")]
    cents = _cents(rows)
    for seed in (f"s{i}" for i in range(12)):
        got = _pick(rows, [], groups=[(31, 32)], owned=[33], seed=seed, bundle="fill")
        assert len(got.media) == 3, (seed, got.media)
        assert 33 not in got.media and 34 not in got.media, (seed, got.media)
        assert not {31, 32} <= set(got.media), (seed, got.media)
        anchor = cents[got.media[0]]
        assert all(cents[m] <= anchor for m in got.media), (seed, got.media)
        assert got.price_cents == max(cents[m] for m in got.media), (seed, got)
    a = _pick(rows, [], groups=[(31, 32)], seed="same", bundle="fill")
    assert a == _pick(rows, [], groups=[(31, 32)], seed="same", bundle="fill"), a
    anyask = fs.Ask("anything", "photo", 3)
    got = _pick([_row(30), _row(31, "$10"), _row(35, "$10")], [], anyask, bundle="fill")
    assert got.media == (30,), got.media
    got = _pick([_row(30), _row(31, "$10"), _row(36), _row(37), _row(38)], [], anyask, bundle="fill")
    assert len(got.media) == 3 and set(got.media) <= {30, 36, 37, 38}, got.media
    assert got.list_cents == 5000 == got.price_cents, got
    clip = _row(50, kind="video")
    got = _pick([clip, _row(51, "$10"), _row(52, "$10")], [], fs.Ask("toy", "video", 3), bundle="fill")
    assert got.media == (50,) and got.format == "video", got
    got = _pick([_row(60), _row(61), _row(62), _row(63, "$10")], [_shoot(60, 61, 62)], bundle="fill")
    assert set(got.media) == {60, 61, 62}, got.media


def case_pick_shoot_is_today():
    cases = [([_row(i) for i in range(1, 7)], [_shoot(*range(1, 7))]),
             ([_row(10), _row(11), _row(20, "$10")], [_shoot(10, 11)]),
             ([_row(30), _row(31, "$10")], []),
             ([_row(50, kind="video"), _row(51)], [])]
    for rows, shoots in cases:
        for seed in ("a", "b", "c"):
            assert _pick(rows, shoots, seed=seed, bundle="shoot") == _pick(rows, shoots, seed=seed), (rows, seed)
    assert len(_pick(*cases[0], bundle="shoot").media) == 4


def case_bundle_counts():
    got = _pick([_row(30), _row(31, "$10"), _row(32, "$10")], [], bundle="fill")
    assert wr.got_words(got) == "3 photos", wr.got_words(got)
    assert fs.claim_ok("3 photos just for u", got) and fs.claim_ok("3 pics", got)
    assert not fs.claim_ok("4 pics", got) and not fs.claim_ok("a video", got)
    rows = [_row(i) for i in range(1, 7)] + [_row(7, "free")]
    big = _pick(rows, [_shoot(*range(1, 8))], bundle="fill")
    assert len(big.media) == 5 and big.previews == (7,), big
    assert fs.fallback_caption(big, "offer") == "6 pics, $50 to unlock", fs.fallback_caption(big, "offer")



def case_bundle_of_table():
    for mode, cfg, want in (("test", {}, "fill"), ("test", {"sell_bundle": "shoot"}, "shoot"),
                            ("test", {"sell_bundle": "fill"}, "fill"), ("shadow", {"sell_bundle": "fill"}, "shoot"),
                            ("shadow", {}, "shoot")):
        f = SimpleNamespace(mode=mode, config={**DEFAULTS, **cfg})
        assert wr.bundle_of(f) == want, (mode, cfg)



@contextlib.contextmanager
def _draft(**cfg):
    _put_draft({**DEFAULTS, "sell_on": True, **cfg})
    try:
        yield
    finally:
        _put_draft(dict(DEFAULTS))


def _toys(items):
    return _vault(items, tags=TOY_J)


def _settle(pair, row_id, outcome):
    with _guarded():
        r = OWNER_A.post("/admin/full-ai/test/settle", json={"account_id": A, "pair": pair, "side": "draft",
                                                              "row_id": row_id, "outcome": outcome})
    assert r.status_code == 200, r.text


def _remove(*mids):
    async def q():
        async with get_session() as s:
            await s.execute(update(VaultItem).where(VaultItem.account_id == A, VaultItem.media_id.in_(mids))
                            .values(removed_at=datetime.utcnow()))
            await s.commit()
    _db(q)


VAULT = {301: "$50", 302: "$10", 303: "$10", 304: "$10"}
ASK_TOY = {"asks_subject": "toy", "asks_format": "photo"}
WANTS = ({**QUIET_TEST, "wants_content": .9}, 3.0, ASK_TOY)


def case_api_default_fills():
    with _draft(sext_scene=False), _toys(VAULT):
        r, _, (pick,) = _post(_body("b-fill", "show me ur toy"), "ok:3 pics just for u", jev=WANTS)
        row = _rows("b-fill")[0]
    assert row.route_row == "sell" and len(pick.media) == 3 and 301 not in pick.media, pick
    assert sorted(json.loads(row.offer_media_json)["locked"]) == sorted(pick.media), row.offer_media_json
    assert _reply(row)["caption_fallback"] is False, _reply(row)          # the claim audit passed "3 pics"
    with _draft(sext_scene=False, sell_bundle="shoot"), _toys(VAULT):
        _, _, (lone,) = _post(_body("b-shoot", "show me ur toy"), "ok:here", jev=WANTS)
    assert len(lone.media) == 1, lone


def case_api_free_item_one():
    pair = "b-free"
    with _draft(sext_scene=False), _toys({**VAULT, 305: "$10", 306: "$10"}):
        r, _, (sold,) = _post(_body(pair, "show me ur toy"), "ok:3 pics just for u", jev=WANTS)
        assert len(sold.media) == 3, sold
        _settle(pair, r.json()["row_id"], "bought")
        r2, _, (gift,) = _post(_body(pair, "this is a scam", n=2), "ok:omg so sorry, this one is FREE for u",
                               jev=({**QUIET_TEST, "complains_now": .9}, 1.0, ASK_TOY))
    assert r2.json()["route"] == "make_right" and gift.price_cents == 0, (r2.json(), gift)
    assert len(gift.media) == 1 and not set(gift.media) & set(sold.media), (gift, sold)


def case_api_tease_keeps_shoot():
    tease = ({**QUIET_TEST, "price": .9}, 1.0, ASK_TOY)
    for pair, gone in (("b-tease", False), ("b-tease-gone", True)):
        with _draft(sext_scene=False), _toys(VAULT):
            r, _, (teased,) = _post(_body(pair, "how much?"), "ok:mm its a cute one babe, u wanna see it", jev=tease)
            assert r.json()["route"] == "tease" and len(teased.media) == 1, (pair, r.json(), teased)
            if gone:
                _remove(*teased.media)
            r2, _, picks = _post(_body(pair, "ok", n=2), "ok:here u go babe", jev=({**QUIET_TEST}, 2.0, ASK_TOY))
        got = r2.json()
        assert got["route"] == "sell_now" and got["offer"]["kind"] == "offer", (pair, got)
        if gone:
            (again,) = picks
            assert len(again.media) == 1 and again.media != teased.media, (pair, again)
        else:
            assert picks == [] and got["offer"]["ref"] == teased.ref, (pair, got["offer"], picks)
            assert len(json.loads(_rows(pair)[1].offer_media_json)["locked"]) == 1, pair


def case_api_haggle_repick_keeps_shoot():
    pair = "b-haggle"
    with _draft(sext_scene=False, draft_questions=True):
        with _toys({301: "$50"}):
            r, _, (offer,) = _post(_body(pair, "show me ur toy"), "ok:mm i have something for u", jev=WANTS)
            assert offer.media == (301,) and offer.price_cents == 5000, offer
        with _toys({302: "$10", 303: "$10", 304: "$10"}):
            r2, _, (again,) = _post(_body(pair, "would you do $20?", n=2), "ok:hmm let me see babe",
                                    jev=({**QUIET_TEST, "counter_offer": .9}, 3.0, ASK_TOY))
    assert r2.json()["route_row"] == "haggle", r2.json()
    assert len(again.media) == 1 and again.subject == "toy", again


def case_api_price_jev_reads_count():
    with _draft(sext_scene=True), _toys(VAULT), _price(FakePriceJev(2.0)) as pf:
        _, _, (pick,) = _post(_body("b-pxb", "show me ur toy"), "ok:here",
                              jev=({**QUIET_SCENE, "wants_content": .9}, 3.0, ASK_TOY))
        row = _rows("b-pxb")[0]
    assert len(pick.media) == 3, pick
    (st,) = pf.calls
    assert st["offer"]["photos"] == 3 and st["he_asked"] == "yes", st["offer"]
    assert row.offer_price_cents == 3500, row.offer_price_cents



def case_asked_count_table():
    for text, want in (("I want bundle of 5 videos", 5), ("i want a bundle of 5 videos", 5), ("three pics", 3),
                       ("bundle of 5", 5), ("5 vids for me", 5), ("5 hot videos", 5), ("two pics pls", 2),
                       ("send me 5 sexy feet pics", 5), ("pack of five", 5), ("set of 3", 3),
                       ("10 videos", 5), ("twelve pics", 5), ("3 pics and 2 videos", 3), ("FOUR CLIPS", 4),
                       ("5 videos for $50", 5), ("can i get 2 more vids", 2),
                       ("$5 video", None), ("5$ video", None), ("5 dollars", None), ("5 dollar videos", None),
                       ("bundle of 5 dollars", None), ("5 min video", None), ("a 5 minute video", None),
                       ("bundle of 2 min clips", None), ("im 25 and want videos", None),
                       ("I am 25 years old, send videos", None), ("1 video", None), ("one pic", None),
                       ("a video", None), ("an hour long video", None), ("a few pics", None),
                       ("a couple of videos", None), ("give me 4", None), ("2.5 videos", None),
                       ("send me videos", None), ("", None)):
        assert fs.asked_count(text) == want, (text, fs.asked_count(text), want)
    assert fs.COUNT_MAX == 5


def case_pick_count_table():
    vid = fs.Ask("toy", "video", 3)
    clips = [_clip(50, "$50"), _clip(51, "$50"), _clip(52, "$10"), _clip(53, "$100"), _row(54)]
    for seed in ("s1", "s2", "s3", "s4"):
        got = _pick(clips, [], replace(vid, count=3), seed=seed)
        assert set(got.media) == {50, 51, 52} and got.media[0] in (50, 51), (seed, got.media)
        assert got.list_cents == got.price_cents == 11000 and got.format == "video", (seed, got)
        assert got.lane == "$50" and got.facts["asked_count"] == 3 and got.facts["kinds"] == {"video": 3}, got
    got = _pick(clips, [], replace(vid, count=5))
    assert len(got.media) == 3 and got.facts["asked_count"] == 5, got
    got = _pick(clips, [], replace(vid, count=2))
    assert len(got.media) == 2 and got.list_cents == sum(_cents(clips)[m] for m in got.media), got
    big = [_clip(i, "$100") for i in range(60, 66)]
    got = _pick(big, [], fs.Ask("toy", "video", 4, 5))
    assert len(got.media) == 5 and got.list_cents == got.price_cents == fs.MAX_CENTS == 20000, got
    assert _pick(clips, [], vid).media in ((50,), (51,)), _pick(clips, [], vid)
    assert _pick(clips, [], replace(vid, count=None)) == _pick(clips, [], vid)
    assert _pick(clips, [], replace(vid, count=3), seed="x") == _pick(clips, [], replace(vid, count=3), seed="x")
    assert _pick(clips, [], vid).ref == _pick(clips, [], replace(vid, count=3)).ref
    loose = [_row(i) for i in range(30, 37)]
    for count, want in ((2, 3), (3, 3), (4, 4), (5, 5)):
        got = _pick(loose, [], replace(TOY, count=count), bundle="fill")
        assert len(got.media) == want and got.facts["asked_count"] == count, (count, got.media)
        assert got.list_cents == 5000 == got.price_cents, got
    for seed in ("a", "b"):
        assert _pick(loose, [], replace(TOY, count=5), seed=seed, bundle="shoot") == _pick(loose, [], TOY, seed=seed)
    for kw in ({"free": True}, {"ride": True}):
        assert _pick(loose + clips, [], replace(TOY, count=5), **kw) == _pick(loose + clips, [], TOY, **kw), kw
    assert len(_pick(clips, [], replace(vid, count=5), free=True).media) == 1
    pool = fs.pool(clips, [], set(), ALL, vid)
    again = fs.same_piece(pool, (50, 51, 52), (), vid)
    assert again.list_cents == again.price_cents == 11000, again
    pool = fs.pool(loose[:3] + [_row(40, "$10")], [], set(), ALL, TOY)
    assert fs.same_piece(pool, (30, 40), (), TOY).list_cents == 5000
    got = _pick(clips, [], replace(vid, count=3))
    assert got.facts["media"] == [{"id": m, "kind": "video", "seconds": 12} for m in got.media], got.facts["media"]
    rows = [_row(i) for i in range(1, 4)] + [_row(7, "free")]
    p = _pick(rows, [_shoot(1, 2, 3, 7)])
    assert p.previews == (7,) and p.facts["media"] == [{"id": m, "kind": "photo", "seconds": None}
                                                      for m in (*p.media, 7)], p.facts["media"]


def case_video_bundle_counts():
    got = _pick([_clip(50), _clip(51), _clip(52)], [], fs.Ask("toy", "video", 1, 3))
    assert wr.got_words(got) == "3 videos", wr.got_words(got)
    line = wr.item_line(got, "x")
    assert " 0:36 " in line and "3 videos" in line, line
    one = _pick([_clip(50)], [], fs.Ask("toy", "video", 1))
    assert " 0:12 " in wr.item_line(one, "x") and "untitled" in wr.item_line(one, "x"), wr.item_line(one, "x")
    assert fs.claim_ok("3 vids just for u", got) and fs.claim_ok("these videos", got) and fs.claim_ok("a vid", got)
    assert not fs.claim_ok("2 videos", got) and not fs.claim_ok("3 pics", got) and not fs.claim_ok("5 vids", got)
    assert fs.fallback_caption(got, "offer") == "3 vids, $30 to unlock", fs.fallback_caption(got, "offer")
    st = _price_jev.offer_state(got)
    assert (st["videos"], st["photos"], st["video_seconds"], st["list_price"]) == (3, 0, [12, 12, 12], "$30"), st


def case_count_flag_table():
    for mode, cfg, want in (("test", {}, True), ("test", {"sell_count": False}, False), ("live", {}, True),
                            ("shadow", {"sell_count": True}, False), ("shadow", {}, False)):
        f = SimpleNamespace(mode=mode, config={**DEFAULTS, **cfg})
        assert wr.count_flag(f) is want, (mode, cfg)


CLIP_JEV = {"v": vault_jev_rules.VERSION, "status": "ok", "lane5": "$10", "state": {}, "kind": "video",
            "vv": vault_jev_rules.VIDEO_VERSION, "frames": [], "breasts_bare": "n", "crotch_bare": "n",
            "penetration": "n", "tags": TOY_J}


@contextlib.contextmanager
def _clips(mids):
    from sqlalchemy import delete
    from _full_ai_sell_helpers import DRESSED as DESCRIBED

    async def add():
        async with get_session() as s:
            for mid in mids:
                s.add(VaultItem(account_id=A, media_id=mid, kind="video", duration_seconds=30,
                                created_at=T0 + timedelta(days=mid), tags="[]", describe_status="described",
                                of_folder_ids="[]",
                                ai_fields_json=json.dumps(mapped({**DESCRIBED, vault_jev_rules.JEV_KEY: CLIP_JEV}))))

    async def drop():
        async with get_session() as s:
            await s.execute(delete(VaultItem).where(VaultItem.account_id == A))
    _db(add)
    try:
        yield
    finally:
        _db(drop)


ASK_VIDS = {"asks_subject": "toy", "asks_format": "video"}


def case_api_bundle_of_videos():
    jev = ({**QUIET_TEST, "wants_content": .9}, 3.0, ASK_VIDS)
    with _draft(sext_scene=False), _clips(range(401, 408)):
        r, _, (pick,) = _post(_body("b-vids", "i want a bundle of 5 videos"), "ok:5 vids just for u", jev=jev)
        row = _rows("b-vids")[0]
    got = r.json()
    assert row.route_row == "sell" and len(pick.media) == 5 and pick.format == "video", pick
    assert row.offer_list_cents == row.offer_price_cents == 5000 == got["offer"]["price_cents"], got["offer"]
    assert _reply(row)["asked_count"] == 5 and _reply(row)["caption_fallback"] is False, _reply(row)
    assert got["offer"]["media"] == list(pick.media), got["offer"]
    assert got["offer"]["items"] == [{"id": m, "kind": "video", "seconds": 30} for m in pick.media], got["offer"]
    assert json.loads(row.offer_media_json)["items"] == got["offer"]["items"], row.offer_media_json
    with _draft(sext_scene=False, sell_count=False), _clips(range(401, 408)):
        r, _, (lone,) = _post(_body("b-vids-off", "i want a bundle of 5 videos"), "ok:here", jev=jev)
        row = _rows("b-vids-off")[0]
    assert len(lone.media) == 1 and "asked_count" not in _reply(row), (lone, _reply(row))


_harness.run()
