#!/usr/bin/env python3
from __future__ import annotations

import _harness
from _jev_fixtures import mapped  # noqa: E402

from _full_ai_sell_helpers import (  # noqa: E402
    A, IDS, NANO, OWNER_A, TURN, _body, _db, _guarded, _picks, _put_draft, _reply, _rows, _system, _vault,
)
import contextlib  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from _full_ai_fixtures import QUIET, FakeInfoJev, FakeJev, FakeWriterHTTP, _fake_jev  # noqa: E402
import assistant_full_ai  # noqa: E402
import tenant_keys  # noqa: E402
import vault_ai_brief  # noqa: E402
import vault_jev_rules  # noqa: E402
from automations import _info_jev as ij  # noqa: E402
from automations import _price_jev  # noqa: E402
from automations import _router_jev as rj  # noqa: E402
from automations import full_ai_sell as fs  # noqa: E402
from automations import full_ai_test as ft  # noqa: E402
from automations import full_ai_writers as wr  # noqa: E402
from automations.full_ai_config import DEFAULTS, Invalid, merged, put_draft, validate  # noqa: E402
from automations.full_ai_decide import Decision, Facts, decide_turn  # noqa: E402
from automations.full_ai_sell import Pick  # noqa: E402
from automations.welcome_chatter_for_info import _EXTRACT_SYSTEM  # noqa: E402

SHADOW_VERSION = "14f5d4f6222f"
MAIN_INFO_VERSION = "66b043f3a87e"
# The test request (questions + state keys) at defaults on a1622d58b (before these flags), by
# `sext_scene`: `_questions("test", scene, spacing=True, likes=True)` + router state, scene,
# Spacing and He likes keys. True re-pinned 2026-11-14: `scene_offer` false-side lost "he just
# said no to buying or cannot pay" (a decline sells now, owner "we never stop selling").
# Re-pinned 2026-11-15: `asks_if_ai` reads `fan_new_messages` only in test + live (NEW-158).
# Re-pinned 2026-11-16: test + live ask `asks_offer_details` (NEW-165); without it the 11-15 pins hold.
# Re-pinned 2026-11-17: `asks_offer_details` took its probed wording (NEW-165); nothing else moved.
PRE_REQUEST_SHA = {False: "a10064d5a88e2fd636a03d86ea5702a6ddcef47795451588940595bcbc1f9088",
                   True: "c414bc89f0ea43453ec1a7c9d7994b6ef2bf511b47e962bd58b49feeaf331205"}
SETTLE = "/admin/full-ai/test/settle"
CHATTY = "ok:haha stop it, what are u watching tonight"
VAULT = {101: "$10", 102: "$10", 103: "$10", 104: "$10", 202: "$50"}



def case_flag_table():
    assert DEFAULTS["chat_tease"] is DEFAULTS["ask_implied"] is DEFAULTS["info_wide"] is True
    assert DEFAULTS["chat_tease_prices"] == [0, 300, 1000, 4000, 8000, 12000, 16000, 20000]
    assert "chat_tease_rungs" not in DEFAULTS
    assert validate(DEFAULTS) == []
    assert [fs.tease_photos(c) for c in (0, 300, 999, 1000, 4000, 20000)] == [1, 1, 1, 2, 8, 40]
    for k in ("chat_tease", "ask_implied", "info_wide"):
        for ok in (True, False):
            assert validate({**DEFAULTS, k: ok}) == [], (k, ok)
        for bad in (1, "yes", None):
            assert validate({**DEFAULTS, k: bad}) == [f"{k}: must be true or false"], (k, bad)
    for ok in ([0], [1000], [0, 300, 20000], list(range(300, 1500, 100)), [500, 1000], [20000, 0, 300]):
        assert validate({**DEFAULTS, "chat_tease_prices": ok}) == [], ok
    for bad in ([], list(range(300, 1600, 100)), [299], [20001], [10.0], [True], ["0"], 0, None, [0, -100],
                [0, 0], [1000, 300, 1000]):
        errs = validate({**DEFAULTS, "chat_tease_prices": bad})
        assert len(errs) == 1 and errs[0].startswith("chat_tease_prices: "), (bad, errs)
    for k, lab in (("chat_tease", "Chat tease"), ("chat_tease_prices", "Chat tease prices"),
                   ("ask_implied", "Implied asks"), ("info_wide", "Wider hobbies")):
        assert assistant_full_ai.label(k) == lab and k in assistant_full_ai.CONFIG_KEYS, k
    new = ("chat_tease", "chat_tease_prices", "ask_implied", "info_wide")
    pre = {k: v for k, v in DEFAULTS.items() if k not in new}
    got = merged({"checkpoint": pre, "previous": pre, "draft": pre, "rev": 3})
    assert all(got[s][k] == DEFAULTS[k] for s in ("checkpoint", "draft") for k in new), got
    old = {**pre, "chat_tease": False, "chat_tease_rungs": [0, 1000]}
    got = merged({"checkpoint": old, "previous": old, "draft": old, "rev": 4})
    for side in ("checkpoint", "previous", "draft"):
        assert "chat_tease_rungs" not in got[side] and got[side]["chat_tease"] is False, side
        assert got[side]["chat_tease_prices"] == DEFAULTS["chat_tease_prices"] and validate(got[side]) == [], side
    assert validate(old) == ["chat_tease_rungs: retired, renamed to chat_tease_prices: remove it"] == validate({**DEFAULTS, "chat_tease_rungs": "junk"})
    try:
        put_draft(None, old, 0)
        raise AssertionError("a retired key was stored")
    except Invalid as e:
        assert e.errors == ["chat_tease_rungs: retired, renamed to chat_tease_prices: remove it"], e.errors


def _facts(mode="test", **cfg):
    return SimpleNamespace(mode=mode, config={**DEFAULTS, **cfg})


def case_switches():
    for fn, key in ((wr.tease_flag, "chat_tease"), (wr.implied_flag, "ask_implied"), (wr.wide_flag, "info_wide")):
        for mode, flag, want in (("test", True, True), ("test", False, False), ("shadow", True, False),
                                 ("live", True, True)):
            assert fn(_facts(mode, **{key: flag})) is want, (key, mode, flag)
    D = lambda route, row, *fired: Decision(route, 2, row, frozenset(fired))   # noqa: E731
    on = _facts()
    for d, f, want in ((D("sell_now", "chat_tease", "chat_tease"), on, True),
                       (D("sell_now", "chat_tease", "chat_tease"), _facts(chat_tease=False), False),
                       (D("sell_now", "chat_tease", "chat_tease"), _facts("shadow"), False),
                       (D("chat", "otherwise", "chat_tease"), on, False),
                       (D("sell_now", "offer_moment", "offer_moment"), on, True),
                       (D("sell_now", "offer_moment", "offer_moment", "sexual_now"), on, False),
                       (D("sell_now", "offer_moment", "offer_moment"), _facts(chat_tease=False), False),
                       (D("sell_now", "offer_moment", "offer_moment"), _facts("shadow"), False),
                       (D("sell_now", "sell", "wants_content"), on, False)):
        assert wr.tease_turn(d, f) is want, (d, f.config["chat_tease"], f.mode)
    assert not hasattr(wr, "ride_turn") and not hasattr(wr, "ride_flag")


def _decide(fired, **kw):
    base = dict(intensity=1.0, pending_offer=False, pending_tease=False, jev_ok=True, chat_tease=True)
    return decide_turn(Facts(fired=frozenset(fired), **{**base, **kw}))


def case_route_row():
    d = _decide({"chat_tease"})
    assert (d.route, d.row, d.dropped) == ("sell_now", "chat_tease", ()), d
    for fired, kw, want in (({"wants_content"}, {}, "sell"), ({"price"}, {}, "tease_price"),
                            ({"counter_offer"}, {"open_offer": True, "draft_on": True}, "haggle"),
                            ({"offer_moment"}, {"draft_on": True}, "offer_moment"),
                            ({"scene_offer", "scene_on"}, {"scene": True}, "scene_offer"),
                            ({"sexual_now"}, {}, "sexual_now"), ({"scene_on"}, {"scene": True}, "scene_on"),
                            ({"stop"}, {}, "stop"), ({"complains_now"}, {}, "complains_now"),
                            ({"promo"}, {}, "promo")):
        got = _decide(fired | {"chat_tease"}, **kw)
        assert got.row == want, (fired, got)
        assert (got.route, got.dropped) == ((w := _decide(fired, **kw)).route, w.dropped), (fired, got, w)
    assert _decide({"chat_tease"}, chat_tease=False) == Decision("chat", 2, "otherwise", frozenset({"chat_tease"}))
    off = _decide({"chat_tease"}, sell_on=False)
    assert (off.route, off.row, off.dropped) == ("chat", "otherwise", ("chat_tease",)), off
    so = _decide({"sexual_now", "chat_tease"}, sext_on=False)
    assert (so.route, so.row, so.dropped) == ("sell_now", "chat_tease", ("sexual_now",)), so


T = datetime(2026, 7, 1, 12)


def _r(i, text, *, row="otherwise", price=None, outcome=None, minutes=None, parts=("ok",), media=None,
       tease=False):
    at = T + timedelta(minutes=i if minutes is None else minutes)
    offer = price is not None
    return SimpleNamespace(
        id=i, created_at=at, route_row=row, status="sent", mode="test", outcome=outcome,
        outcome_at=at if outcome else None, offer_price_cents=price, offer_list_cents=price,
        offer_item_ref=json.dumps({"ref": i, "subject": "anything", "format": "photo", "lane": "$10",
                                   "kind": "free" if price == 0 else "offer"}) if offer else None,
        offer_media_json=json.dumps({"locked": media or [i], "previews": []}) if offer else None,
        jev_json=json.dumps({"state": {"fan_new_messages": [text]}}),
        reply_json=json.dumps({"parts": [{"text": p} for p in parts],
                               **({"chat_tease": {"cents": price}} if tease else {})}))


def case_live_photo_outcome_is_not_a_photo_line():
    r = _r(1, "hey")
    r.reply_json = json.dumps({**json.loads(r.reply_json), "fan_photo": {"outcome": "none", "model": None, "ms": 3}})
    lines = ft.test_thread([r])
    assert [(m.direction, m.body, m.media_count) for m in lines] == [("in", "hey", 0), ("out", "ok", 0)], lines
    assert ft.chat_tease_of([r], T + timedelta(minutes=2))


def case_folds():
    now = T + timedelta(minutes=30)
    chat = [_r(i, f"line {i}") for i in range(1, 5)]
    free = _r(5, "line 5", row="chat_tease", price=0)
    after = [_r(6, "line 6"), _r(7, "line 7")]
    rows = chat + [free] + after
    assert ft.spacing_of(rows, now) == {"his_lines_since_last_piece": "no piece yet", "pieces_this_sitting": 0,
                                        "unasked_pieces_this_sitting": 0}
    assert ft.spacing_of(rows, now, free=True) == {"his_lines_since_last_piece": 3, "pieces_this_sitting": 0,
                                                   "unasked_pieces_this_sitting": 0}
    mr = [*chat, _r(5, "line 5", row="complains_now", price=0), *after]
    assert ft.spacing_of(mr, now, free=True)["his_lines_since_last_piece"] == "no piece yet"
    paid = _r(8, "line 8", row="chat_tease", price=1000)
    sp = ft.spacing_of([*rows, paid], now, free=True)
    assert sp == {"his_lines_since_last_piece": 1, "pieces_this_sitting": 1, "unasked_pieces_this_sitting": 1}, sp
    assert ft.spacing_of([*rows, paid], now)["unasked_pieces_this_sitting"] == 1
    assert ft.teases_sent_of(chat) == "none yet" == ft.NO_TEASES
    assert ft.teases_sent_of(rows) == ["free photo"]
    sent = [*rows, _r(8, "x", row="chat_tease", price=1000, outcome="bought", media=[8, 9]),
            _r(9, "x", row="offer_moment", price=1000, outcome="bought"),
            _r(10, "x", row="chat_tease", price=4000, media=[10, 11, 12]),
            _r(11, "x", row="chat_tease", price=4000, outcome="declined", media=[13, 14]),
            _r(12, "x", row="chat_tease", price=300, outcome="declined"),
            _r(13, "x", row="chat_tease", price=1250, outcome="bought"),
            _r(14, "x", row="chat_tease")]
    assert ft.teases_sent_of(sent) == ["free photo", "$10 photo set, he bought it", "$40 photo set, he did not buy it",
                                       "$40 photo set, he said no", "$3 photo, he said no",
                                       "$12.50 photo, he bought it"], ft.teases_sent_of(sent)
    om = [*chat, _r(5, "line 5", row="offer_moment", price=0, tease=True), *after]
    assert ft.teases_sent_of(om) == ["free photo"] and ft.is_tease(om[4]) and not ft.is_tease(om[0])
    assert ft.spacing_of(om, now, free=True)["his_lines_since_last_piece"] == 3
    om2 = [*om, _r(8, "x", row="offer_moment", price=1000, outcome="bought", tease=True)]
    assert ft.teases_sent_of(om2) == ["free photo", "$10 photo, he bought it"], ft.teases_sent_of(om2)
    assert ft.chat_tease_of(chat, now) == {"his_lines_this_sitting": 5, "teases_sent": "none yet"}
    assert ft.chat_tease_of(sent, now)["teases_sent"] == ft.teases_sent_of(sent)
    assert ft.chat_tease_of(sent, now)["his_lines_this_sitting"] == 15
    late = T + timedelta(hours=5)
    assert ft.chat_tease_of(rows, late) == {"his_lines_this_sitting": 1, "teases_sent": ["free photo"]}
    assert tuple(ft.chat_tease_of(chat, now)) == rj.TEASE_STATE_KEYS == ("his_lines_this_sitting", "teases_sent")
    assert not hasattr(ft, "tease_rung") and not hasattr(ft, "NONE_LEFT")


MAIN_PRICE_VERSION = "a8c6c0da0b86"


def case_tease_price_pure():
    opts = _price_jev.tease_options(DEFAULTS["chat_tease_prices"])
    assert opts == {"free": 0, "$3": 300, "$10": 1000, "$40": 4000, "$80": 8000, "$120": 12000, "$160": 16000,
                    "$200": 20000}, opts
    assert _price_jev.tease_options([1250, 0]) == {"$12.50": 1250, "free": 0}
    crit = _price_jev._tease_criteria(opts)
    assert crit["free"] == _price_jev.TEASE_PRICE["free"]
    assert crit["$10"] == "Up to 2 teasing photos of her, locked: he pays $10 to see them", crit
    assert crit["$200"].startswith("Up to 40 "), crit
    st = _price_jev.tease_state({"fan_new_messages": ["hey"], "thread": [], "teases_sent": ["free photo"],
                                 "his_lines_this_sitting": 6, "her_last_line": "x"}, 3, ["bought 2 photos for $10"],
                                [1000, 250])
    assert tuple(st) == _price_jev.TEASE_PRICE_STATE_KEYS, list(st)
    assert st == {"fan_new_messages": ["hey"], "thread": [], "heat": "3 of 4", "bought_before": "yes",
                  "purchases": ["bought 2 photos for $10"], "spent_so_far": "$12.50", "teases_sent": ["free photo"],
                  "his_lines_this_sitting": 6}, st
    none = _price_jev.tease_state({}, 1, [], [])
    assert (none["bought_before"], none["spent_so_far"]) == ("no", "nothing yet"), none
    assert _price_jev.PRICE_VERSION == _price_jev.price_version() == MAIN_PRICE_VERSION
    base = _price_jev.tease_price_version()
    assert _price_jev.TEASE_PRICE_VERSION == base and base != MAIN_PRICE_VERSION
    for name, other in (("TEASE_PRICE", {**_price_jev.TEASE_PRICE, "instructions": "x"}),
                        ("TEASE_PRICE_STATE_KEYS", ("x",))):
        real = getattr(_price_jev, name)
        setattr(_price_jev, name, other)
        try:
            assert _price_jev.tease_price_version() != base and _price_jev.price_version() == MAIN_PRICE_VERSION, name
        finally:
            setattr(_price_jev, name, real)


DRESSED = {"clothing_state": "dressed", "acts": ["posing"], "penetration": "none", "explicitness": "sfw",
           "underwear_visible": True, "vulva_vis": "covered", "breasts_vis": "covered",
           "anus_vis": "not_in_frame", "over_vulva": "jeans", "over_breasts": "t-shirt",
           "people_count": 1, "partner_visible": False}


def _row(mid, lane="$10"):
    j = {"v": vault_jev_rules.VERSION, "status": "ok", "lane5": lane, "state": {}, "kind": "photo",
         "breasts_bare": "n", "crotch_bare": "n", "penetration": "n", "tags": {}}
    fields = vault_ai_brief.settled_reading(mapped({**DRESSED, vault_jev_rules.JEV_KEY: j}))
    return {"media_id": mid, "kind": "photo", "created_at": T + timedelta(minutes=mid),
            "duration_seconds": None, "fields": fields, "describe_status": "described", "score": 0,
            "refs": set(), "packs": set()}


def _pick(rows, shoots, *, seed, **kw):
    ask = fs.Ask("anything", "any", 2)
    pool = fs.pool(rows, [], set(), {"include": [], "exclude": []}, ask)
    assert isinstance(pool, list), pool
    return fs.pick(pool, list(shoots), ask, seed=seed, **kw)


def case_pick_one_photo():
    shoot = [_row(i, lane="$10") for i in range(1, 6)]
    shoots = [{"items": [{"media_id": i} for i in range(1, 6)]}]
    for seed in (f"s{i}" for i in range(6)):
        for bundle in ("shoot", "fill"):
            one = _pick(shoot, shoots, seed=seed, bundle=bundle, ride=True, ride_max=1, target=1000)
            assert isinstance(one, Pick) and len(one.media) == 1 and one.facts["ride"], one
            two = _pick(shoot, shoots, seed=seed, bundle=bundle, ride=True, target=1000)
            assert two == _pick(shoot, shoots, seed=seed, bundle=bundle, ride=True, ride_max=2, target=1000)
            assert len(two.media) == 2 and two.media[0] == one.media[0], (one, two)
            five = _pick(shoot, shoots, seed=seed, bundle=bundle, ride=True, ride_max=5, target=1000)
            assert len(five.media) == 5 and five.media[0] == one.media[0], five


async def _ride(rows, cents):
    from automations import full_ai_turn
    from automations.full_ai_sell import Refusal

    async def load(_aid):
        return rows, [], {}

    async def shoots(_aid, _pool, _prints):
        return []

    async def price(*_a):
        return cents
    facts = SimpleNamespace(account_id="a", fan_id=1, anchor_key="k", mode="test", scene_now=None, tease=None,
                            offer_piece=None, owned=set(), sent=set(), state={"fan_new_messages": []},
                            config={**DEFAULTS, "folders": {"include": [], "exclude": []}, "sell_bundle": False,
                                    "sell_nearest": "off"}, pick=None)
    saved = fs.load_rows, fs.shoots_for, full_ai_turn._tease_price, full_ai_turn.tease_turn
    fs.load_rows, fs.shoots_for, full_ai_turn._tease_price = load, shoots, price
    full_ai_turn.tease_turn = lambda d, f: True
    try:
        await full_ai_turn._sell(facts, Decision("sell_now", 2, "chat_tease", frozenset()), {}, {}, None)
    finally:
        fs.load_rows, fs.shoots_for, full_ai_turn._tease_price, full_ai_turn.tease_turn = saved
    return facts.pick if isinstance(facts.pick, (Pick, Refusal)) else None


async def case_folder_final_one_clamp_in_sell():
    from automations import full_ai_turn
    final = {"folder_final": True}
    for cents in (300, 0):          # a tease quote (paid or free) never moves a final $10
        got = await _ride([{**_row(7), "folder_cents": 1000, **final}], cents)
        assert isinstance(got, Pick) and (got.price_cents, got.list_cents) == (1000, 1000), (cents, got)
    rows = [{**_row(8), "folder_cents": 3000, **final}]

    async def load(_aid):
        return rows, [], {}
    piece = SimpleNamespace(subject="anything", format="photo", locked=(8,), previews=(), list_cents=3000,
                            row_id=1)
    facts = SimpleNamespace(account_id="a", fan_id=1, anchor_key="k", mode="test", scene_now=None, tease=None,
                            offer_piece=piece, owned=set(), sent=set(),
                            state={"fan_new_messages": ["how about $20?"]},
                            config={**DEFAULTS, "folders": {"include": [], "exclude": []}, "sell_bundle": False,
                                    "sell_nearest": "off"}, pick=None)
    saved = fs.load_rows, full_ai_turn.tease_turn
    fs.load_rows, full_ai_turn.tease_turn = load, (lambda d, f: False)
    try:
        await full_ai_turn._sell(facts, Decision("sell_now", 2, "haggle", frozenset()), {}, {}, None)
    finally:
        fs.load_rows, full_ai_turn.tease_turn = saved
    assert isinstance(facts.pick, Pick) and (facts.pick.price_cents, facts.pick.list_cents) == (3000, 3000), \
        facts.pick
    rows[0] = {**rows[0], "folder_final": False}
    fs.load_rows, full_ai_turn.tease_turn = load, (lambda d, f: False)
    try:
        await full_ai_turn._sell(facts, Decision("sell_now", 2, "haggle", frozenset()), {}, {}, None)
    finally:
        fs.load_rows, full_ai_turn.tease_turn = saved
    assert facts.pick.price_cents == fs.clamp_quote(3000, 2000) < 3000, ("not final: the haggle moves it", facts.pick)


async def case_ride_soft_only():
    from automations.full_ai_sell import Refusal
    big = [_row(i, lane="$50") for i in (1, 2)] + [_row(3, lane="$100")]
    for cents in (0, 300):
        assert await _ride(big, cents) == Refusal("no_match"), cents
    bare = _row(4, lane="$10")
    bare["fields"] = {**bare["fields"], "_jev": {**bare["fields"]["_jev"], "breasts_bare": "y"}}
    assert await _ride([*big, bare], 0) == Refusal("no_match")
    got = await _ride([*big, bare], 300)
    assert isinstance(got, Pick) and got.media == (4,) and got.price_cents == 300, got
    got = await _ride([*big, _row(5, lane="$10")], 0)
    assert isinstance(got, Pick) and got.media == (5,) and got.price_cents == 0, got


async def case_free_ride_bounds():
    """W30 #1: a free tease quote rides only a free-safe photo listed at most $10 (the soft level)
    whose price is not a final folder price; every other priced photo stays priced or gives no ride.
    Spec phase-05 › Send: "price 0 (Free item, free Chat tease photo)" is a designed send."""
    from automations.full_ai_sell import Refusal
    over = {**_row(1), "folder_cents": 2500}                  # a non-final $25 folder: above soft
    assert await _ride([over], 0) == Refusal("no_match")
    final = {**_row(2), "folder_cents": 1000, "folder_final": True}
    got = await _ride([final, over], 0)
    assert isinstance(got, Pick) and got.media == (2,) and got.price_cents == 1000, got
    soft = {**_row(3), "folder_cents": 1000}                  # a non-final $10 folder: free ride OK
    got = await _ride([soft, over], 0)
    assert isinstance(got, Pick) and got.media == (3,) and got.price_cents == 0, got
    assert got.list_cents <= fs.LEVEL_CENTS["soft"], got


def _request_sha(questions, state_keys) -> str:
    d = {"questions": {q: v.model_dump(mode="json") for q, v in questions.items()}, "state_keys": list(state_keys)}
    return hashlib.sha256(json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _keys(scene: bool, tease: bool = False) -> list[str]:
    return [*rj.state([], [], "", "", "").keys(), *(rj.SCENE_STATE_KEYS if scene else ()),
            *rj.SPACING_STATE_KEYS, *(rj.TEASE_STATE_KEYS if tease else ()), *rj.LIKES_STATE_KEYS]


def case_router_request():
    for scene, sha in PRE_REQUEST_SHA.items():
        q = rj._questions("test", scene, True, True, tease=False, implied=False)
        assert _request_sha(q, _keys(scene)) == sha, scene
        on = rj._questions("test", scene, True, True, tease=True, implied=True)
        assert "chat_tease" in on and "chat_tease" not in q, scene
        assert list(on)[:len(rj.QUESTIONS)] == list(rj.QUESTIONS), "same place"
        assert on["chat_tease"].criteria["true"] == rj.TEST_NOULS["chat_tease"]["criteria"]["true"]
        assert on["wants_content"].instructions == rj.TEST_IMPLIED["wants_content"]["instructions"]
        assert q["wants_content"].instructions == rj.QUESTIONS["wants_content"]["instructions"]
    sh = rj._questions("shadow", False, False, False, tease=True, implied=True)
    assert "chat_tease" not in sh and sh["wants_content"].instructions == rj.QUESTIONS["wants_content"]["instructions"]
    assert rj.question_version() == rj.QUESTION_VERSION == SHADOW_VERSION
    assert rj.TEST_THRESHOLDS["chat_tease"] == .7 and "chat_tease" not in rj.DRAFT
    base = rj.question_version("test")
    for name, other in (("TEST_IMPLIED", {"wants_content": {**rj.TEST_IMPLIED["wants_content"], "instructions": "x"}}),
                        ("TEASE_STATE_KEYS", ("x",))):
        real = getattr(rj, name)
        setattr(rj, name, other)
        try:
            assert rj.question_version("test") != base and rj.question_version() == SHADOW_VERSION, name
        finally:
            setattr(rj, name, real)


def case_info_request():
    off, on = ij._questions(["hobbies"]), ij._questions(["hobbies"], wide=True)
    assert list(off) == list(on), "same place"
    for qid in ij.STATED:
        same = qid != "stated_hobbies"
        assert (off[qid].instructions == on[qid].instructions) is same, qid
    assert on["stated_hobbies"].instructions == ij.STATED_WIDE["stated_hobbies"]["instructions"]
    assert ij.INFO_VERSION == ij.info_version() == ij.info_version(False, False, False) == MAIN_INFO_VERSION
    vs = {ij.info_version(lead, likes, wide) for lead in (0, 1) for likes in (0, 1) for wide in (0, 1)}
    assert len(vs) == 8, vs


def case_wording_in_catalog():
    doc = (Path(__file__).resolve().parents[2] / "docs" / "prompts" / "new" / "current-repo.md").read_text(encoding="utf-8")
    for nid in ("NEW-149", "NEW-150", "NEW-151", "NEW-152", "NEW-153"):
        assert f"### {nid} " in doc, nid
    for d in (rj.TEST_NOULS["chat_tease"], rj.TEST_IMPLIED["wants_content"], ij.STATED_WIDE["stated_hobbies"]):
        assert json.dumps(d["instructions"]) in doc, d["instructions"][:40]
        for v in d["criteria"].values():
            assert json.dumps(v) in doc, v[:40]
    assert ij.HOBBIES_EXTRACT in doc
    for v in _price_jev.TEASE_PRICE.values():
        assert json.dumps(v) in doc, v[:40]
    text149 = doc.split("### NEW-149 ", 1)[1].split("### NEW-150 ", 1)[0].split("```text", 1)[1]
    assert "next_chat_tease" not in text149



class FakeTeaseJev:

    def __init__(self, *verdicts):
        self.verdicts, self.calls = list(verdicts), []

    async def system_one(self, state, questions, model=None):
        self.calls.append({"state": state, "questions": questions, "model": model})
        v = self.verdicts.pop(0) if self.verdicts else RuntimeError("no verdict left")
        if isinstance(v, Exception):
            raise v
        if isinstance(v, float):
            return SimpleNamespace(scores={"price": SimpleNamespace(score=v, probabilities={1: .5, 2: .5})})
        p = {v: .8, **{k: .2 / len(questions.get(_price_jev.TEASE_QID).criteria)
                       for k in questions[_price_jev.TEASE_QID].criteria if k != v}} if isinstance(v, str) else dict(v)
        return SimpleNamespace(choices={_price_jev.TEASE_QID: SimpleNamespace(choice=max(p, key=p.get),
                                                                              probabilities=p)})


TJ = FakeTeaseJev()


@contextlib.contextmanager
def _deepseek_key():
    owner = IDS["agency_a_owner"]
    before = _db(lambda: tenant_keys.get_key(owner, "deepseek"))
    _db(lambda: tenant_keys.set_keys(owner, {"deepseek": "test-deepseek-agency-key"}))
    try:
        yield
    finally:
        _db(lambda: tenant_keys.set_keys(owner, {"deepseek": before}))


@contextlib.contextmanager
def _draft(**cfg):
    _put_draft({**DEFAULTS, "sell_on": True, **cfg})
    real = _price_jev._client
    TJ.verdicts, TJ.calls = [], []
    _price_jev._client = lambda key: TJ
    try:
        yield TJ
    finally:
        _price_jev._client = real
        _put_draft(dict(DEFAULTS))


def _turn(pair, n, text, answers=None, *, script=CHATTY, info=None):
    fj = FakeJev(({**QUIET, **(answers or {})}, 1.0))
    fw = FakeWriterHTTP({NANO: script})
    with _guarded(), _picks() as picks, fw.on(), _fake_jev(fj, info):
        r = OWNER_A.post(TURN, json=_body(pair, text, n=n))
    assert r.status_code == 200, r.text
    (call,) = fj.calls
    return r.json(), call, _rows(pair)[n - 1], fw, picks


def _settle(pair, row_id, outcome):
    with _guarded():
        r = OWNER_A.post(SETTLE, json={"account_id": A, "pair": pair, "side": "draft", "row_id": row_id,
                                       "outcome": outcome})
    return r


TEASE = {"chat_tease": .9}
MANY = {101: "$10", 102: "$10", 103: "$10", 104: "$10", 105: "$10", 106: "$10", 202: "$50"}


def _tease_call(tj, n=1):
    assert len(tj.calls) == n and all(list(c["questions"]) == [_price_jev.TEASE_QID] for c in tj.calls), tj.calls
    return tj.calls[-1]


def case_api_tease():
    pair, n = "ct-tease", 0

    def turn(text, answers=None, **kw):
        nonlocal n
        n += 1
        return _turn(pair, n, text, answers, **kw)

    with _draft(sext_scene=True) as tj, _vault(MANY):
        for i in range(4):
            g, call, row, _, _ = turn(f"just chilling {i}")
            assert g["route_row"] == "otherwise", g
        st = call["state"]
        assert (st["his_lines_this_sitting"], st["teases_sent"]) == (4, "none yet"), st
        assert "chat_tease" in call["questions"] and not tj.calls
        tj.verdicts = ["free"]
        g, call, row, fw, (pick,) = turn("mm what about u", TEASE)
        assert (g["route"], g["route_row"]) == ("sell_now", "chat_tease"), g
        tc = _tease_call(tj)
        assert list(tc["questions"][_price_jev.TEASE_QID].criteria) == list(_price_jev.tease_options(
            DEFAULTS["chat_tease_prices"])), tc["questions"]
        assert tc["questions"][_price_jev.TEASE_QID].instructions == _price_jev.TEASE_PRICE["instructions"]
        ts = tc["state"]
        assert tuple(ts) == _price_jev.TEASE_PRICE_STATE_KEYS, ts
        assert (ts["teases_sent"], ts["bought_before"], ts["spent_so_far"], ts["his_lines_this_sitting"],
                ts["fan_new_messages"]) == ("none yet", "no", "nothing yet", 5, ["mm what about u"]), ts
        assert len(pick.media) == 1 and pick.facts["ride"], pick
        assert g["offer"]["kind"] == "free" and g["offer"]["price_cents"] == 0, g["offer"]
        assert row.offer_price_cents == 0 and len(fw.requests) == 1, fw.requests          # no caption call
        system = _system(fw)
        assert wr.RIDE_NOTE in system and ">>OFFER" not in system and wr.FILMING_MORE not in system, system
        rep = _reply(row)
        ct = rep["chat_tease"]
        assert (ct["cents"], ct["error"], ct["version"], ct["options"]) == (
            0, None, _price_jev.TEASE_PRICE_VERSION, DEFAULTS["chat_tease_prices"]), ct
        assert ct["p"]["free"] == .8 and isinstance(ct["ms"], int), ct
        assert rep["ride"] is True and "price" not in rep and rep["claim_fail"] == [], rep
        assert rep["level"] == "soft", rep          # rwl-a F11: the lane the ride used
        assert "ppv" in g["parts"][-1], g["parts"]
        assert _settle(pair, row.id, "bought").status_code == 422
        g, call, row, _, _ = turn("haha nice")
        st = call["state"]
        assert (st["his_lines_since_last_piece"], st["pieces_this_sitting"], st["teases_sent"]) == (
            1, 0, ["free photo"]), st
        for t in ("so what now", "tell me more"):
            turn(t)
        tj.verdicts = ["$3"]
        g, call, row, fw, (pick,) = turn("u are fun", TEASE)
        assert _tease_call(tj, 2)["state"]["teases_sent"] == ["free photo"]
        assert (g["route_row"], g["offer"]["price_cents"], g["offer"]["kind"]) == ("chat_tease", 300, "offer"), g
        assert len(pick.media) == 1 and row.offer_price_cents == 300, (pick, row.offer_price_cents)
        assert _reply(row)["chat_tease"]["cents"] == 300 and wr.RIDE_NOTE in _system(fw)
        assert _settle(pair, row.id, "declined").status_code == 200
        g, call, row, _, _ = turn("ok")
        assert call["state"]["teases_sent"] == ["free photo", "$3 photo, he said no"], call["state"]
        for t in ("lol", "what are u doing later"):
            turn(t)
        tj.verdicts = ["$40"]
        g, call, row, fw, (pick,) = turn("u are cute", TEASE)
        assert _tease_call(tj, 3)["state"]["teases_sent"] == ["free photo", "$3 photo, he said no"]
        assert 2 < len(pick.media) <= fs.tease_photos(4000), pick.media
        assert (g["offer"]["price_cents"], row.offer_price_cents, row.offer_list_cents) == (4000, 4000, 4000), g
        assert _settle(pair, row.id, "bought").status_code == 200
        g, call, row, _, _ = turn("wow")
        assert call["state"]["teases_sent"][-1] == "$40 photo set, he bought it", call["state"]
        for t in ("hehe", "so"):
            turn(t)
        tj.verdicts = ["$80"]
        turn("ur amazing", TEASE)
        ts = _tease_call(tj, 4)["state"]
        assert (ts["bought_before"], ts["spent_so_far"]) == ("yes", "$40"), ts
        assert ts["purchases"] and "$40" in ts["purchases"][-1], ts


def case_api_tease_jev_fails():
    for i, verdict in enumerate((RuntimeError("typesafe down"), {"$999": .9, "free": .1}, {"free": .5, "$3": .5})):
        pair = f"ct-fail-{i}"
        with _draft(sext_scene=True) as tj, _vault(VAULT):
            tj.verdicts = [verdict]
            g, call, row, fw, picks = _turn(pair, 1, "hey u", TEASE)
        _tease_call(tj)
        # No tease this Turn: a plain chat reply, no pick, no need-line, no ride.
        assert (g["route"], g["route_row"], g["offer"], picks) == ("sell_now", "chat_tease", None, []), g
        rep = _reply(row)
        assert rep["refusal"] == "no_match" and rep["chat_tease"]["cents"] is None and rep["chat_tease"]["error"], rep
        system = _system(fw)
        assert wr.FILMING_MORE not in system and wr.RIDE_NOTE not in system, system
        assert g["parts"] and "ppv" not in g["parts"][-1], g["parts"]


def case_api_prices_from_config():
    pair = "ct-cfg"
    with _draft(chat_tease_prices=[500, 0]) as tj, _vault(VAULT):
        tj.verdicts = ["$5"]
        g, call, row, _, (pick,) = _turn(pair, 1, "hey u", TEASE)
    tc = _tease_call(tj)
    assert list(tc["questions"][_price_jev.TEASE_QID].criteria) == ["$5", "free"], tc["questions"]
    assert _reply(row)["chat_tease"]["options"] == [500, 0] and g["offer"]["price_cents"] == 500, g
    assert len(pick.media) == 1, pick
    # A draft still carrying the retired key is refused with where it went; the stored draft stays.
    cur = OWNER_A.get("/admin/full-ai/config", params={"account_id": A}).json()
    r = OWNER_A.put("/admin/full-ai/config/draft", json={
        "account_id": A, "draft": {**DEFAULTS, "chat_tease_rungs": [0, 1000]}, "rev": cur["rev"]})
    assert r.status_code == 422 and "chat_tease_rungs: retired, renamed to chat_tease_prices: remove it" in r.text, r.text
    got = OWNER_A.get("/admin/full-ai/config", params={"account_id": A}).json()
    assert got["rev"] == cur["rev"] and got["draft"] == cur["draft"], got
    _put_draft(dict(DEFAULTS))


def case_api_flag_off():
    pair = "ct-off"
    with _draft(chat_tease=False, sext_scene=False) as tj, _vault(VAULT):
        g, call, row, fw, picks = _turn(pair, 1, "hey u", TEASE)
    assert "chat_tease" not in call["questions"] and tj.calls == [], list(call["questions"])
    assert not set(rj.TEASE_STATE_KEYS) & set(call["state"]), call["state"]
    assert (g["route"], g["route_row"], g["offer"], picks) == ("chat", "otherwise", None, []), g
    assert "chat_tease" not in _reply(row) and "chat_tease" not in json.loads(row.jev_json)["fired"]


def case_api_info_wide():
    stated = ({"hobbies": .9}, "none")
    for wide in (True, False):
        pair = f"ct-wide-{wide}"
        script = {NANO: CHATTY, "api.deepseek.com": 'ok:{"hobbies": "watching Netflix"}'}
        fj = FakeJev(({**QUIET}, 1.0))
        fi = FakeInfoJev(stated)
        fw = FakeWriterHTTP(script)
        with _draft(info_wide=wide), _vault(VAULT), _deepseek_key(), _guarded(), fw.on(), _fake_jev(fj, fi):
            r = OWNER_A.post(TURN, json=_body(pair, "im chilling watching netflix", n=1))
        assert r.status_code == 200, r.text
        (ic,) = fi.calls
        want = ij.STATED_WIDE if wide else ij.STATED
        assert ic["questions"]["stated_hobbies"].instructions == want["stated_hobbies"]["instructions"], wide
        ex = next(q for q in fw.requests if q["host"] == "api.deepseek.com")
        msgs = ex["body"]["messages"]
        assert msgs[0]["content"] == _EXTRACT_SYSTEM, msgs
        assert (msgs[1]["content"] == ij.HOBBIES_EXTRACT) is wide, msgs
        assert r.json()["fan_info"] == {"hobbies": "watching Netflix"}, r.json()
        row = _rows(pair)[0]
        assert json.loads(row.jev_json)["info_version"] == ij.info_version(True, True, wide), wide


def case_api_broke_ignored():
    ask, got = {"wants_content": .99}, {}
    for broke in (False, True):
        with _draft(sext_scene=True) as tj, _vault(MANY):
            tj.verdicts = [2.0]
            g, call, row, fw, picks = _turn(f"ct-broke-{broke}", 1, "send me one, im broke tho",
                                            {**ask, **({"declines_buying": .99} if broke else {})})
        assert len(tj.calls) == 1 and "price" in json.loads(row.reply_json), (broke, tj.calls)
        assert ("declines_buying" in json.loads(row.jev_json)["fired"]) is broke, row.jev_json
        assert _system(fw).count(wr.BROKE_JOKE) == (1 if broke else 0), _system(fw)
        got[broke] = (g["route"], g["route_row"], g["offer"]["price_cents"], g["offer"]["list_cents"],
                      [sorted(MANY[m] for m in p.media) for p in picks])
    assert got[True] == got[False] and got[False][:2] == ("sell_now", "sell"), got


_harness.run()
