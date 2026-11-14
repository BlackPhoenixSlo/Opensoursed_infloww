#!/usr/bin/env python3
"""test_full_ai_routes_chat — Full AI Test chat: every Route (phase 03a, ticket 34; split from
test_full_ai_test_chat.py).

Shared setup (seeded Agencies, owner clients, `_guarded`, `_post`, the Writer fakes) is
`_full_ai_chat_helpers.py`; every Turn runs inside `_guarded` as in test_full_ai_test_chat.py.

  case_every_route_via_api               (ticket 34) chat, sext, ai_dare, make_right, no_send/promo,
                                         no_send/under_18: route, row, parts, writer, status; each
                                         Route's beat reached the Writer; no_send calls none and
                                         adds no skip/blacklist row
  case_r10_via_api                       sell off: wants_content + sexual_now sext; wants_content chat
                                         sell_off with the sell-off line; price chat tease_off
  case_jev_failure_still_replies         chat, Heat 1, jev_failed, a reply written
  case_gifs_on_carry_a_gif_part          GIFs on (stored column) + STICKER line: a {gif, tag} part
                                         (a dropped draft's sticker stays failed);
                                         a sticker-only reply is the gif alone; GIFs off: no
                                         sticker block, the marker stripped, no gif part

Run: ./venv/bin/python service/tests/test_full_ai_routes_chat.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

from _full_ai_fixtures import _shape_drop  # noqa: E402
from _full_ai_chat_helpers import A, OWNER_A, _GIF_TAG, _body, _db, _post, _reply, _rows, _store_config
from sqlalchemy import func, select

from _full_ai_fixtures import QUIET
from automations import full_ai_writers
from automations.full_ai_config import DEFAULTS
from db.engine import get_session
from db.models import AccountAiConfig


# ── Every Route (ticket 34) ───────────────────────────────────────────
from automations import cat_stickers  # noqa: E402
from db.models import Blacklist, SkipList  # noqa: E402


def _hot(**qs) -> dict[str, float]:
    return {**QUIET, **qs}


def _system_of(fw) -> str:
    (req,) = fw.requests
    return req["body"]["messages"][0]["content"]


def _exclude_counts() -> tuple[int, int]:
    async def q():
        async with get_session() as s:
            return ((await s.execute(select(func.count()).select_from(SkipList))).scalar_one(),
                    (await s.execute(select(func.count()).select_from(Blacklist))).scalar_one())
    return _db(q)


def _set_model_notes(aid: str, notes: str | None) -> None:
    async def go():
        async with get_session() as s:
            (await s.get(AccountAiConfig, aid)).model_notes = notes
    _db(go)


def case_every_route_via_api():
    w = full_ai_writers
    notes = "Likes: telling him exactly what I'd do to him"
    _set_model_notes(A, notes)
    try:
        cases = [
            ("chat", _hot(), "chat", "otherwise", w.SELL_OFF_LINE),   # selling off: never a promise
            ("sext", _hot(sexual_now=0.9), "sext", "sexual_now", w.SEXT_HOT),
            ("dare", _hot(asks_if_ai=0.9), "ai_dare", "asks_if_ai", w.DARE),
            ("mr", _hot(complains_now=0.9), "make_right", "complains_now", w.MAKE_RIGHT_HEAD),
        ]
        for tag, answers, route, row, beat in cases:
            pair = f"p-route-{tag}"
            r, fw, _, _ = _post(OWNER_A, _body(pair), "ok:mmm ok babe", jev=(answers, 2.0))
            got = r.json()
            assert r.status_code == 200, r.text
            assert (got["route"], got["route_row"], got["status"], got["writer"]) == (
                route, row, "sent", "euryale-v2.3"), (tag, got)
            assert got["parts"] and all(p.get("text") for p in got["parts"]), (tag, got["parts"])
            (stored,) = _rows(A, pair)
            assert (stored.route, stored.route_row, stored.writer_model, stored.status) == (
                route, row, "euryale-v2.3", "sent"), tag
            system = _system_of(fw)
            assert beat in system, tag
            assert notes in system, tag                      # her Model info, every Route
            if route == "chat":
                assert not any(x in system for x in (w.SEXT_HOT, w.BRUSH_OFF, w.MAKE_RIGHT_HEAD))
            if route == "sext":
                assert got["heat"] == 3 and w.SEXT_HEAT.format(heat=3) in system, got
            if route == "ai_dare":                           # two beats, one reply
                assert system.index(w.BRUSH_OFF) < system.index(w.DARE), system
            if route == "make_right":                        # the apology, no item
                assert w.MAKE_RIGHT_TAIL in system and w.APOLOGY_FRAMES[0].replace("{name}", "babe") in system
                assert all(set(p) == {"text"} for p in got["parts"]), got["parts"]
    finally:
        _set_model_notes(A, None)
    for tag, q in (("promo", "promo"), ("u18", "says_under_18")):
        pair = f"p-route-{tag}"
        before = _exclude_counts()
        r, fw, _, _ = _post(OWNER_A, _body(pair), "ok:never sent", jev=(_hot(**{q: 0.95}), 1.0))
        got = r.json()
        assert r.status_code == 200, r.text
        assert (got["route"], got["route_row"], got["status"], got["writer"], got["parts"]) == (
            "no_send", q, "no_send", None, []), got
        assert fw.requests == [], fw.requests                # no Writer call
        (stored,) = _rows(A, pair)
        assert (stored.route, stored.route_row, stored.writer_model, stored.status) == (
            "no_send", q, None, "no_send")
        assert _reply(stored)["parts"] == [] and _reply(stored)["attempts"] == []
        assert _exclude_counts() == before                   # no exclude list touched


def case_r10_via_api():
    """DEFAULTS lock selling off (`sell_on` false)."""
    assert DEFAULTS["sell_on"] is False and DEFAULTS["sext_on"] is True
    w = full_ai_writers
    cases = [
        ("both", _hot(wants_content=0.9, sexual_now=0.9), "sext", "sexual_now", ["sell"]),
        ("ask", _hot(wants_content=0.9), "chat", "sell_off", ["sell"]),
        ("price", _hot(price=0.9), "chat", "tease_off", ["tease_price"]),
    ]
    for tag, answers, route, row, dropped in cases:
        pair = f"p-r10-{tag}"
        r, fw, _, _ = _post(OWNER_A, _body(pair), "ok:its all on my page babe", jev=(answers, 1.0))
        got = r.json()
        assert r.status_code == 200 and got["status"] == "sent", r.text
        assert (got["route"], got["route_row"], got["dropped"]) == (route, row, dropped), (tag, got)
        system = _system_of(fw)
        # Selling off in test Mode: no Turn promises a piece (NO_SELL_OFFERS never); a scene Turn
        # gets SELL_OFF_SCENE, every other SELL_OFF_LINE.
        scene = w.SEXT_SCENE in system
        assert w.NO_SELL_OFFERS not in system, tag
        assert (w.SELL_OFF_SCENE in system, w.SELL_OFF_LINE in system) == (scene, not scene), (tag, scene)
        (stored,) = _rows(A, pair)
        assert (stored.route, stored.route_row) == (route, row), tag


def case_jev_failure_still_replies():
    pair = "p-jev-fail"
    r, fw, fj, _ = _post(OWNER_A, _body(pair), "ok:haha sorry what", jev=RuntimeError("jev down"))
    got = r.json()
    assert r.status_code == 200, r.text
    assert (got["route"], got["heat"], got["route_row"], got["status"], got["writer"]) == (
        "chat", 1, "jev_failed", "sent", "euryale-v2.3"), got
    assert got["parts"] and got["dropped"] == [], got
    assert len(fw.requests) == 1 and len(fj.calls) == 1
    (stored,) = _rows(A, pair)
    assert stored.jev_error and "jev down" in stored.jev_error, stored.jev_error
    assert (stored.route_row, stored.heat, stored.status) == ("jev_failed", 1, "sent")



def case_gifs_on_carry_a_gif_part():
    gifs = cat_stickers._CATALOG[_GIF_TAG][1]
    _store_config(A, {"checkpoint": {**DEFAULTS, "gifs": True}})
    try:
        pair = "p-gif-on"
        r, fw, _, _ = _post(OWNER_A, _body(pair), f"ok:omg ur funny\nSTICKER: {_GIF_TAG}")
        got = r.json()
        assert r.status_code == 200 and got["status"] == "sent", r.text
        assert cat_stickers.prompt_block("allow") in _system_of(fw)
        *texts, gif = got["parts"]
        assert texts and all(set(p) == {"text"} and "STICKER" not in p["text"] for p in texts), texts
        assert set(gif) == {"gif", "tag"} and gif["tag"] == _GIF_TAG and gif["gif"] in gifs, gif
        (stored,) = _rows(A, pair)
        assert _reply(stored)["parts"] == got["parts"]
        # The session read returns it; the next Turn's thread reads her text only.
        s = OWNER_A.get("/admin/full-ai/test/session", params={"account_id": A, "pair": pair}).json()
        assert s["rows"][0]["parts"] == got["parts"], s
        # A sticker-only reply is the gif alone.
        pair = "p-gif-solo"
        r, *_ = _post(OWNER_A, _body(pair), f"ok:STICKER: {_GIF_TAG}")
        got = r.json()
        assert got["status"] == "sent" and got["writer"] == "euryale-v2.3", got
        assert [set(p) for p in got["parts"]] == [{"gif", "tag"}], got["parts"]
        # A draft the chain drops stays failed: its sticker does not carry the Turn.
        pair = "p-gif-drop"
        with _shape_drop("banned"):
            r, *_ = _post(OWNER_A, _body(pair), f"ok:hii\nSTICKER: {_GIF_TAG}")
        got = r.json()
        assert (got["status"], got["parts"], got["writer"]) == ("failed", [], None), got
        (row,) = _rows(A, pair)
        assert _reply(row)["dropped_reason"] == "banned" and _reply(row)["parts"] == [], _reply(row)
    finally:
        _store_config(A, {})
    # GIFs off (DEFAULTS): no sticker block, the marker still stripped, no gif part.
    pair = "p-gif-off"
    r, fw, _, _ = _post(OWNER_A, _body(pair), f"ok:omg ur funny\nSTICKER: {_GIF_TAG}")
    got = r.json()
    assert got["status"] == "sent", got
    assert "STICKER" not in _system_of(fw)
    assert got["parts"] and all(set(p) == {"text"} and "STICKER" not in p["text"]
                                for p in got["parts"]), got["parts"]


if __name__ == "__main__":
    _harness.run()
