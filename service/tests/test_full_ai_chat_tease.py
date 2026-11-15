#!/usr/bin/env python3
"""test_full_ai_chat_tease — config `chat_tease` (Chat tease: an unasked teasing photo rides her
ordinary reply in a normal chat, priced by the tease price Jev from `chat_tease_prices`),
`ask_implied` (`wants_content`'s wider wording) and `info_wide` (what he is watching / playing now
is a hobby), all test Mode only.

  case_flag_table            defaults, validation (bools, prices), labels, merge of an old side, the
                             retired `chat_tease_rungs` read without an error, refused on a write
  case_switches              tease/implied/wide flags: test Mode only; `tease_turn` (row chat_tease,
                             or a not-hot offer_moment)
  case_route_row             row chat_tease: last flagged row, only replaces chat; sell flag drops it
                             naming nothing; ignored without the flag
  case_folds                 pure `spacing_of(free=)`, `teases_sent_of` (free, bought, unbought, said
                             no; a tease-priced offer_moment row counts), `chat_tease_of`
  case_tease_price_pure      `tease_options`, `tease_state`, the Choice's options, `TEASE_PRICE_VERSION`;
                             `PRICE_VERSION` unmoved
  case_pick_one_photo        `pick(ride=True, ride_max=n)`: n photos (1, 5); ride_max 2 unchanged
  case_ride_soft_only        rwl-a F4: `_sell`'s ride draws only soft-lane photos (<= $10); a free
                             tease only ones past the free guard; none left -> Refusal("no_match")
  case_router_request        flags off: the request is the one before them, byte for byte (pinned on
                             a1622d58b); `chat_tease` asked with the flag only; `ask_implied` swaps
                             `wants_content`'s wording in test Mode only; Shadow's digest unmoved
  case_info_request          `info_wide` swaps `stated_hobbies`; digest; extract system line
  case_wording_in_catalog    every new wording is in docs/prompts/new/current-repo.md
  case_api_tease             Test chat: Jev's "free" -> one free photo (price 0, kind free, RIDE_NOTE,
                             no caption) -> `teases_sent` names it -> Jev's "$3" -> one photo at $3
                             -> Decline -> "he said no" -> Jev's "$40" -> up to 8 photos at $40 -> Buy
                             -> "he bought it", `spent_so_far`; the Offer price Jev never asked
  case_api_tease_jev_fails   tease price Jev error / unoffered answer: a plain chat reply, no pick
  case_api_prices_from_config   the options are the side's `chat_tease_prices`, recorded on the row
  case_api_flag_off          `chat_tease` off: neither question is asked, a fired one is ignored
  case_api_info_wide         a fired hobbies extract carries HOBBIES_EXTRACT; off, wcfi's messages
  case_api_broke_ignored     owner 2026-11-15: an ask with `declines_buying` fired routes, picks and
                             prices (Offer price Jev asked) as without it; only BROKE_JOKE is added

Run: ./venv/bin/python service/tests/test_full_ai_chat_tease.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

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
PRE_REQUEST_SHA = {False: "60dc28c9ce4f9c0177bb47ebd98eefb418121d3d4f47b7f86ec1743399284890",
                   True: "a72e58d985022c50e490d46f535ebbdc6dc9f9da034eb747e61d4f72a66a9947"}
SETTLE = "/admin/full-ai/test/settle"
CHATTY = "ok:haha stop it, what are u watching tonight"
VAULT = {101: "$10", 102: "$10", 103: "$10", 104: "$10", 202: "$50"}


# ── Pure ──────────────────────────────────────────────────────────────

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
    # The retired `chat_tease_rungs` (PR #669's key): a stored side still holding it reads and
    # validates, the key dropped; a write carrying it is refused, naming its successor.
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
                                 ("live", True, True)):   # live = test (04a Mode gate)
            assert fn(_facts(mode, **{key: flag})) is want, (key, mode, flag)
    D = lambda route, row, *fired: Decision(route, 2, row, frozenset(fired))   # noqa: E731
    on = _facts()
    for d, f, want in ((D("sell_now", "chat_tease", "chat_tease"), on, True),
                       (D("sell_now", "chat_tease", "chat_tease"), _facts(chat_tease=False), False),
                       (D("sell_now", "chat_tease", "chat_tease"), _facts("shadow"), False),
                       (D("chat", "otherwise", "chat_tease"), on, False),
                       (D("sell_now", "offer_moment", "offer_moment"), on, True),             # not hot
                       (D("sell_now", "offer_moment", "offer_moment", "sexual_now"), on, False),   # hot
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
    # Every other matching row wins (an ask, tease, haggle, offer_moment, scene_offer, any sext).
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
    # Without the flag the id is ignored, not recorded; sell off drops it naming nothing.
    assert _decide({"chat_tease"}, chat_tease=False) == Decision("chat", 2, "otherwise", frozenset({"chat_tease"}))
    off = _decide({"chat_tease"}, sell_on=False)
    assert (off.route, off.row, off.dropped) == ("chat", "otherwise", ("chat_tease",)), off
    # Sexting off with sexual_now: the sext row drops (sext_off), the tease may still send.
    so = _decide({"sexual_now", "chat_tease"}, sext_on=False)
    assert (so.route, so.row, so.dropped) == ("sell_now", "chat_tease", ("sexual_now",)), so


T = datetime(2026, 7, 1, 12)


def _r(i, text, *, row="otherwise", price=None, outcome=None, minutes=None, parts=("ok",), media=None,
       tease=False):
    """A session row as `send` leaves it: his line in `jev_json`, her parts, the Offer columns
    (`media`: the locked ids, default [i]); `tease`: the tease price Jev priced it
    (`reply_json.chat_tease.cents`)."""
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
    """A live row keeps the photo read's outcome in `reply_json.fan_photo` (no `text`): the folds
    read his line from `jev_json`, never `photo["text"]` (public 2026-11-15: every live Turn after
    the first raised KeyError)."""
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
    # Flag off: a free photo is no Piece (today's outputs).
    assert ft.spacing_of(rows, now) == {"his_lines_since_last_piece": "no piece yet", "pieces_this_sitting": 0,
                                        "unasked_pieces_this_sitting": 0}
    # `free`: it ends the line count (2 rows after it + this Turn), the piece counts stay priced.
    assert ft.spacing_of(rows, now, free=True) == {"his_lines_since_last_piece": 3, "pieces_this_sitting": 0,
                                                   "unasked_pieces_this_sitting": 0}
    # A free make_right item is not a Chat tease photo.
    mr = [*chat, _r(5, "line 5", row="complains_now", price=0), *after]
    assert ft.spacing_of(mr, now, free=True)["his_lines_since_last_piece"] == "no piece yet"
    paid = _r(8, "line 8", row="chat_tease", price=1000)
    sp = ft.spacing_of([*rows, paid], now, free=True)
    assert sp == {"his_lines_since_last_piece": 1, "pieces_this_sitting": 1, "unasked_pieces_this_sitting": 1}, sp
    assert ft.spacing_of([*rows, paid], now)["unasked_pieces_this_sitting"] == 1      # UNASKED_ROWS
    # Teases sent: every chat_tease row with a photo, oldest first, in words with its outcome.
    assert ft.teases_sent_of(chat) == "none yet" == ft.NO_TEASES
    assert ft.teases_sent_of(rows) == ["free photo"]
    sent = [*rows, _r(8, "x", row="chat_tease", price=1000, outcome="bought", media=[8, 9]),
            _r(9, "x", row="offer_moment", price=1000, outcome="bought"),           # not a Chat tease
            _r(10, "x", row="chat_tease", price=4000, media=[10, 11, 12]),
            _r(11, "x", row="chat_tease", price=4000, outcome="declined", media=[13, 14]),
            _r(12, "x", row="chat_tease", price=300, outcome="declined"),
            _r(13, "x", row="chat_tease", price=1250, outcome="bought"),
            _r(14, "x", row="chat_tease")]                                          # no photo went out
    assert ft.teases_sent_of(sent) == ["free photo", "$10 photo set, he bought it", "$40 photo set, he did not buy it",
                                       "$40 photo set, he said no", "$3 photo, he said no",
                                       "$12.50 photo, he bought it"], ft.teases_sent_of(sent)
    # A Chat tease fired on row offer_moment (a not-hot unasked offer) counts as one, free or priced.
    om = [*chat, _r(5, "line 5", row="offer_moment", price=0, tease=True), *after]
    assert ft.teases_sent_of(om) == ["free photo"] and ft.is_tease(om[4]) and not ft.is_tease(om[0])
    assert ft.spacing_of(om, now, free=True)["his_lines_since_last_piece"] == 3
    om2 = [*om, _r(8, "x", row="offer_moment", price=1000, outcome="bought", tease=True)]
    assert ft.teases_sent_of(om2) == ["free photo", "$10 photo, he bought it"], ft.teases_sent_of(om2)
    assert ft.chat_tease_of(chat, now) == {"his_lines_this_sitting": 5, "teases_sent": "none yet"}
    assert ft.chat_tease_of(sent, now)["teases_sent"] == ft.teases_sent_of(sent)
    assert ft.chat_tease_of(sent, now)["his_lines_this_sitting"] == 15        # 14 rows + this Turn
    # A new Sitting (a gap over 2 h) restarts his line count; the teases sent stay the session's.
    late = T + timedelta(hours=5)
    assert ft.chat_tease_of(rows, late) == {"his_lines_this_sitting": 1, "teases_sent": ["free photo"]}
    assert tuple(ft.chat_tease_of(chat, now)) == rj.TEASE_STATE_KEYS == ("his_lines_this_sitting", "teases_sent")
    assert not hasattr(ft, "tease_rung") and not hasattr(ft, "NONE_LEFT")


# The Offer price Jev's digest before Chat tease's price (main 5a5d433d4): Chat tease must not
# move it. Re-pinned 2026-11-15: PRICE's $10 criterion back to before 11-14's "broke" clause
# (owner: ignore "broke").
MAIN_PRICE_VERSION = "a8c6c0da0b86"


def case_tease_price_pure():
    opts = _price_jev.tease_options(DEFAULTS["chat_tease_prices"])
    assert opts == {"free": 0, "$3": 300, "$10": 1000, "$40": 4000, "$80": 8000, "$120": 12000, "$160": 16000,
                    "$200": 20000}, opts
    assert _price_jev.tease_options([1250, 0]) == {"$12.50": 1250, "free": 0}       # config order kept
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
    """A vault row as test_full_ai_ride builds it (a dressed photo, settled)."""
    j = {"v": vault_jev_rules.VERSION, "status": "ok", "lane5": lane, "state": {}, "kind": "photo",
         "breasts_bare": "n", "crotch_bare": "n", "penetration": "n", "tags": {}}
    fields = vault_ai_brief.settled_reading({**DRESSED, vault_jev_rules.JEV_KEY: j})
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
    """`full_ai_turn._sell` on a fresh Chat tease Turn over `rows`, the tease price Jev said `cents`."""
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


async def case_ride_soft_only():
    from automations.full_ai_sell import Refusal
    big = [_row(i, lane="$50") for i in (1, 2)] + [_row(3, lane="$100")]
    for cents in (0, 300):          # no soft photo: no ride, free or $3
        assert await _ride(big, cents) == Refusal("no_match"), cents
    bare = _row(4, lane="$10")
    bare["fields"] = {**bare["fields"], "_jev": {**bare["fields"]["_jev"], "breasts_bare": "y"}}
    assert await _ride([*big, bare], 0) == Refusal("no_match")     # free guard fails: never free
    got = await _ride([*big, bare], 300)
    assert isinstance(got, Pick) and got.media == (4,) and got.price_cents == 300, got
    got = await _ride([*big, _row(5, lane="$10")], 0)
    assert isinstance(got, Pick) and got.media == (5,) and got.price_cents == 0, got


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
    # Shadow never takes either, whatever is passed.
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
    assert "next_chat_tease" not in text149 and "teases_sent" in text149      # the wording block is today's


# ── Through the Test chat API ─────────────────────────────────────────

class FakeTeaseJev:
    """`_price_jev._client`: each call pops a verdict (an option label, a label -> P map, or an
    exception) and records {state, questions}; with none left it raises (a failure, never an
    answer). Shared by the Offer price Jev's seam, so `questions` shows which one was asked."""

    def __init__(self, *verdicts):
        self.verdicts, self.calls = list(verdicts), []

    async def system_one(self, state, questions, model=None):
        self.calls.append({"state": state, "questions": questions, "model": model})
        v = self.verdicts.pop(0) if self.verdicts else RuntimeError("no verdict left")
        if isinstance(v, Exception):
            raise v
        if isinstance(v, float):        # the Offer price Jev's Score
            return SimpleNamespace(scores={"price": SimpleNamespace(score=v, probabilities={1: .5, 2: .5})})
        p = {v: .8, **{k: .2 / len(questions.get(_price_jev.TEASE_QID).criteria)
                       for k in questions[_price_jev.TEASE_QID].criteria if k != v}} if isinstance(v, str) else dict(v)
        return SimpleNamespace(choices={_price_jev.TEASE_QID: SimpleNamespace(choice=max(p, key=p.get),
                                                                              probabilities=p)})


TJ = FakeTeaseJev()


@contextlib.contextmanager
def _deepseek_key():
    """Creator A's Agency DeepSeek key for the block (a fake value: the wire is faked), then restored."""
    owner = IDS["agency_a_owner"]
    before = _db(lambda: tenant_keys.get_key(owner, "deepseek"))
    _db(lambda: tenant_keys.set_keys(owner, {"deepseek": "test-deepseek-agency-key"}))
    try:
        yield
    finally:
        _db(lambda: tenant_keys.set_keys(owner, {"deepseek": before}))


@contextlib.contextmanager
def _draft(**cfg):
    """A's draft sells, `cfg` over it; the price Jev seam is `TJ` (reset), so no call reaches TypeSafe."""
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
# Six $10 photos: room for a $40 tease's up to 8.
MANY = {101: "$10", 102: "$10", 103: "$10", 104: "$10", 105: "$10", 106: "$10", 202: "$50"}


def _tease_call(tj, n=1):
    """The tease price Jev's last call, after checking it was asked `n` times in all, each time the
    Choice alone (never the Offer price Score)."""
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
        # Jev's "free": one free photo, unlocked, riding her plain reply.
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
        assert _settle(pair, row.id, "bought").status_code == 422          # a free photo is no priced Offer
        # The free photo is her last piece: the line count restarts; Jev reads it in `teases_sent`.
        g, call, row, _, _ = turn("haha nice")
        st = call["state"]
        assert (st["his_lines_since_last_piece"], st["pieces_this_sitting"], st["teases_sent"]) == (
            1, 0, ["free photo"]), st
        for t in ("so what now", "tell me more"):
            turn(t)
        # Jev's "$3": one photo locked at $3 (price / $5, at least 1), the Offer price Jev not asked.
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
        # Jev's "$40": more than the old 2-photo cap (up to 8; the vault's six $10 photos).
        tj.verdicts = ["$40"]
        g, call, row, fw, (pick,) = turn("u are cute", TEASE)
        assert _tease_call(tj, 3)["state"]["teases_sent"] == ["free photo", "$3 photo, he said no"]
        assert 2 < len(pick.media) <= fs.tease_photos(4000), pick.media
        assert (g["offer"]["price_cents"], row.offer_price_cents, row.offer_list_cents) == (4000, 4000, 4000), g
        assert _settle(pair, row.id, "bought").status_code == 200
        g, call, row, _, _ = turn("wow")
        assert call["state"]["teases_sent"][-1] == "$40 photo set, he bought it", call["state"]
        # A later tease's state: he bought, and what he spent.
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
    """Owner 2026-11-15 ("just be ignorant of this broke stuff"): same Route, Pick and price."""
    ask, got = {"wants_content": .99}, {}
    for broke in (False, True):
        with _draft(sext_scene=True) as tj, _vault(MANY):
            tj.verdicts = [2.0]                     # the Offer price Jev says $35
            g, call, row, fw, picks = _turn(f"ct-broke-{broke}", 1, "send me one, im broke tho",
                                            {**ask, **({"declines_buying": .99} if broke else {})})
        assert len(tj.calls) == 1 and "price" in json.loads(row.reply_json), (broke, tj.calls)
        assert ("declines_buying" in json.loads(row.jev_json)["fired"]) is broke, row.jev_json
        assert _system(fw).count(wr.BROKE_JOKE) == (1 if broke else 0), _system(fw)
        got[broke] = (g["route"], g["route_row"], g["offer"]["price_cents"], g["offer"]["list_cents"],
                      [sorted(MANY[m] for m in p.media) for p in picks])     # media ids: seeded by pair
    assert got[True] == got[False] and got[False][:2] == ("sell_now", "sell"), got


_harness.run()
