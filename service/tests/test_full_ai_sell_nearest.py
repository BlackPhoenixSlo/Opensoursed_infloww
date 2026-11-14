#!/usr/bin/env python3
"""test_full_ai_sell_nearest — config `sell_nearest` (test Mode): an ask nothing in the vault matches
sells the nearest piece, the Writer says so ("note"), and selling off never promises a picture.

  case_pick_nearest_steps          (a) same subject any format, (b) any subject same format, (c)
                                   anything; subject kept only in (a); format = the anchor's kind;
                                   facts["asked"] / ["nearest"] recorded; exact match untouched
  case_pick_nearest_off_and_refusals  nearest=False still no_match; a relaxed set with nothing
                                   priced is no_priced_items; free ignores nearest
  case_sell_step_gates             `_sell`: a fresh sell_now relaxes ("plain" / "note"); "off",
                                   Shadow, a Pending tease's re-pick, a haggle and tease Route never
  case_turn_nearest_via_api        Test chat: his blowjob photo ask on a vault without one, scene on:
                                   a PPV goes out (Offer columns set), reply_json.nearest, the price
                                   Jev ran, NEAREST_NOTE in the Writer prompt; "plain" no note;
                                   "off" the Refusal row as before
  case_asked_words_table           NEAREST_NOTE's {asked}
  case_writer_note                 "note" -> NEAREST_NOTE right under the item line (chat mode) /
                                   in the caption call's prompt ("caption"), the bubbles before it
                                   nothing; "plain", an exact match, Shadow -> absent
  case_sell_off_lines              test Mode selling off: scene Turn SELL_OFF_SCENE, chat / sext
                                   SELL_OFF_LINE, never NO_SELL_OFFERS; selling on keeps it
  case_shadow_prompts_pinned       Shadow's Writer + caption prompts byte-identical to origin/main
  case_config                      default "note", a bad value refused, the assistant label

Run: ./venv/bin/python service/tests/test_full_ai_sell_nearest.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

from _full_ai_sell_helpers import (  # noqa: E402
    OFFER_COLS, PRICED, _body, _post, _put_draft, _reply, _rows, _system, _vault,
)
import asyncio  # noqa: E402
import contextlib  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from _full_ai_fixtures import QUIET, QUIET_SCENE  # noqa: E402
import assistant_full_ai  # noqa: E402
import vault_ai_brief  # noqa: E402
import vault_jev_rules  # noqa: E402
from automations import _price_jev, full_ai_caption, full_ai_config, full_ai_sell as fs  # noqa: E402
from automations import full_ai_turn, full_ai_writers as wr  # noqa: E402
from automations.full_ai_config import DEFAULTS  # noqa: E402
from automations.full_ai_decide import Decision  # noqa: E402
from automations.full_ai_sell import Pick, Refusal, Teased  # noqa: E402

# ── Pick fixtures (test_full_ai_sell.py's shapes) ─────────────────────

T0 = datetime(2026, 7, 1)
DRESSED = {"clothing_state": "dressed", "acts": ["posing"], "penetration": "none", "explicitness": "sfw",
           "underwear_visible": True, "vulva_vis": "covered", "breasts_vis": "covered",
           "anus_vis": "not_in_frame", "over_vulva": "jeans", "over_breasts": "t-shirt",
           "people_count": 1, "partner_visible": False}
TOY_J = {"toy": "toy_visible_not_in_use"}


def _jev(lane5, kind="photo", **tags):
    j = {"v": vault_jev_rules.VERSION, "status": "ok", "lane5": lane5, "state": {}, "kind": kind,
         "breasts_bare": "n", "crotch_bare": "n", "penetration": "n", "tags": dict(tags)}
    if kind == "video":
        j.update(vv=vault_jev_rules.VIDEO_VERSION, frames=[])
    return j


def _row(mid, lane="$10", kind="photo", *, packs=(), **tags):
    fields = vault_ai_brief.settled_reading({**DRESSED, vault_jev_rules.JEV_KEY: _jev(lane, kind, **tags)})
    return {"media_id": mid, "kind": kind, "created_at": T0 + timedelta(minutes=mid),
            "duration_seconds": 12 if kind == "video" else None, "fields": fields,
            "describe_status": "described", "score": 0, "refs": set(), "packs": set(packs)}


ALL = {"include": [], "exclude": []}


def _pick(rows, ask, **kw):
    pool = fs.pool(rows, [], set(), ALL, ask)
    assert not isinstance(pool, Refusal), pool
    return fs.pick(pool, [], ask, seed="pick:a:f:t1", **kw)


def case_pick_nearest_steps():
    toy_clip, toy_photo, plain_photo, plain_clip = (_row(1, kind="video", **TOY_J), _row(2, **TOY_J),
                                                    _row(3), _row(4, kind="video"))
    table = [
        # (rows, ask, media, subject, format, step, why)
        ([toy_clip, plain_photo], fs.Ask("toy", "photo", 1), (1,), "toy", "video", "format",
         "(a) same subject, any format: the toy clip"),
        ([plain_photo, plain_clip], fs.Ask("toy", "video", 1), (4,), "anything", "video", "subject",
         "(b) any subject, same format: a clip, subject not claimed"),
        ([plain_photo], fs.Ask("toy", "video", 1), (3,), "anything", "photo", "any",
         "(c) anything: the photo"),
        ([plain_photo], fs.Ask("feet", "any", 1), (3,), "anything", "photo", "subject",
         "format any: (a) is the ask itself, skipped; (b) any subject, any format"),
        ([toy_clip], fs.Ask("anything", "photo", 1), (1,), "anything", "video", "format",
         "subject anything: (a) any format; (b) is the ask itself"),
    ]
    for rows, ask, media, subject, fmt, step, why in table:
        got = _pick(rows, ask, nearest=True)
        assert isinstance(got, Pick), (why, got)
        assert (got.media, got.subject, got.format) == (media, subject, fmt), (why, got)
        assert got.facts["asked"] == {"subject": ask.subject, "format": ask.format}, (why, got.facts)
        assert got.facts["nearest"] == step, (why, got.facts)
    # An exact match is the same Pick, nearest or not, recording no miss.
    exact = fs.Ask("toy", "photo", 1)
    on, off = _pick([toy_photo, plain_photo], exact, nearest=True), _pick([toy_photo, plain_photo], exact)
    assert on == off and on.media == (2,) and "asked" not in on.facts and "nearest" not in on.facts, on
    # Relaxed rows run the normal lane logic (heat target).
    got = _pick([_row(5), _row(6, "$50")], fs.Ask("toy", "photo", 3), nearest=True)
    assert got.list_cents == 5000 and got.media == (6,), got


def case_pick_nearest_off_and_refusals():
    rows = [_row(3)]
    assert _pick(rows, fs.Ask("toy", "video", 1)) == Refusal("no_match"), "default: no relax"
    assert _pick(rows, fs.Ask("toy", "video", 1), nearest=False) == Refusal("no_match")
    # The relaxed set with nothing priced: a free-lane photo only.
    free = fs.pool([_row(7, "free")], [], set(), ALL, fs.Ask("toy", "video", 1))
    assert fs.pick(free, [], fs.Ask("toy", "video", 1), seed="s", nearest=True) == Refusal("no_priced_items")
    # free=True keeps its own fallback; nearest changes nothing there.
    pool = fs.pool(rows, [], set(), ALL, fs.Ask("toy", "video", 1))
    a = fs.pick(pool, [], fs.Ask("toy", "video", 1), seed="s", free=True)
    b = fs.pick(pool, [], fs.Ask("toy", "video", 1), seed="s", free=True, nearest=True)
    assert a == b and "asked" not in a.facts, (a, b)


# ── The sell step's gates (`full_ai_turn._sell`) ──────────────────────

@contextlib.contextmanager
def _sell_fakes(rows):
    """`load_rows` gives `rows`; `pick` spied (its `nearest` kwarg per call)."""
    real_load, real_pick, calls = fs.load_rows, fs.pick, []

    async def load(_aid):
        return rows, [], {}

    def spy(*a, **k):
        calls.append(k.get("nearest", False))
        return real_pick(*a, **k)
    fs.load_rows, fs.pick = load, spy
    try:
        yield calls
    finally:
        fs.load_rows, fs.pick = real_load, real_pick


def _facts(mode="test", *, tease=None, offer_piece=None, **cfg):
    return SimpleNamespace(account_id="acct_near", fan_id=7, anchor_key="test:s:1", mode=mode,
                           config={**DEFAULTS, "sell_on": True, "sext_scene": False, **cfg},
                           owned=set(), sent=set(), tease=tease, offer_piece=offer_piece, scene_now=None,
                           spent=[], state={"fan_new_messages": ["send it"]}, pick=None)


TOY_PHOTO = {"asks_subject": {"toy": 0.9}, "asks_format": {"photo": 0.9}}


def case_sell_step_gates():
    rows = [_row(3), _row(4, "$50")]       # no toy anywhere
    piece = Teased("toy", "photo", (99,), (), 5000, row_id=1)
    table = [
        # (decision, facts, nearest passed, a Pick, why)
        (Decision("sell_now", 2, "sell", frozenset()), _facts(), True, True, "fresh sell, note"),
        (Decision("sell_now", 2, "offer_moment", frozenset()), _facts(sell_nearest="plain"), True, True,
         "offer_moment, plain"),
        (Decision("sell_now", 2, "sell", frozenset()), _facts(sell_nearest="off"), False, False, "off"),
        (Decision("sell_now", 2, "sell", frozenset()), _facts("shadow"), False, False, "Shadow never"),
        (Decision("sell_now", 2, "sell", frozenset()), _facts(tease=piece), False, False,
         "a Pending tease's re-pick: never an unrelated piece"),
        (Decision("sell_now", 2, "haggle", frozenset()), _facts(offer_piece=piece), False, False,
         "the haggle's re-pick"),
        (Decision("tease", 2, "tease_price", frozenset()), _facts(), False, False, "tease Route"),
    ]
    for d, f, nearest, sold, why in table:
        reply: dict = {}
        with _sell_fakes(rows) as calls:
            asyncio.run(full_ai_turn._sell(f, d, TOY_PHOTO, reply))
        assert calls == [nearest], (why, calls)
        assert isinstance(f.pick, Pick) is sold, (why, f.pick)
        if sold:
            assert reply["nearest"] == {"asked_subject": "toy", "asked_format": "photo", "step": "subject"}, \
                (why, reply)
            assert f.pick.subject == "anything" and f.pick.facts["asked"] == {"subject": "toy", "format": "photo"}
        else:
            assert "nearest" not in reply and f.pick == Refusal("no_match"), (why, f.pick, reply)


# ── Through the Test chat API ─────────────────────────────────────────

class FakePriceJev:
    """`_price_jev._client` (test_full_ai_scene_chat.py's): one score per call."""

    def __init__(self, score):
        self.score, self.calls = score, []

    async def system_one(self, state, questions, model=None):
        self.calls.append(state)
        return SimpleNamespace(scores={"price": SimpleNamespace(score=self.score, probabilities={1: .5, 2: .5})})


@contextlib.contextmanager
def _price(fake):
    real = _price_jev._client
    _price_jev._client = lambda key: fake
    try:
        yield fake
    finally:
        _price_jev._client = real


@contextlib.contextmanager
def _draft(**cfg):
    _put_draft({**DEFAULTS, "sell_on": True, **cfg})
    try:
        yield
    finally:
        _put_draft(dict(DEFAULTS))


BJ_PHOTO = {"asks_subject": {"blowjob": 0.9}, "asks_format": {"photo": 0.9}}
ASK_TEXT = "show me a picure of you on your knees looking up so i can imagine u sucking it"


def case_turn_nearest_via_api():
    # Scene on, scene_offer: the price Jev prices the relaxed Pick as any Pick.
    with _draft(sext_scene=True), _vault(PRICED), _price(FakePriceJev(1.5)) as pj:
        r, fw, (pick,) = _post(_body("nr-note", ASK_TEXT), "ok:dont have that one yet.. but this one tho",
                               jev=({**QUIET_SCENE, "scene_on": .9, "scene_offer": .9}, 3.0,
                                    {**BJ_PHOTO, "scene_stage": "building", "offer_level": "any"}))
    got = r.json()
    (row,) = _rows("nr-note")
    assert (row.route, row.route_row, row.status) == ("sell_now", "scene_offer", "sent"), (row.route_row, got)
    assert isinstance(pick, Pick) and pick.ref in PRICED and pick.subject == "anything", pick
    assert any("ppv" in p for p in got["parts"]) and got["offer"]["kind"] == "offer", got
    assert all(getattr(row, c) is not None for c in OFFER_COLS[:4]), {c: getattr(row, c) for c in OFFER_COLS}
    rp = _reply(row)
    assert rp["nearest"] == {"asked_subject": "blowjob", "asked_format": "photo", "step": "subject"}, rp
    assert "refusal" not in rp and len(pj.calls) == 1 and rp["price"]["jev_cents"] == 3000, rp["price"]
    assert row.offer_price_cents == 3000, row.offer_price_cents
    assert wr.NEAREST_NOTE.format(asked="a blowjob photo", got=wr.got_words(pick)) in _system(fw), _system(fw)

    # "plain": the PPV and the record, no note.
    with _draft(sell_nearest="plain"), _vault(PRICED):
        r, fw, (pick,) = _post(_body("nr-plain"), "ok:mm i have something for u",
                               jev=({**QUIET, "wants_content": .9}, 1.0, BJ_PHOTO))
    (row,) = _rows("nr-plain")
    assert isinstance(pick, Pick) and row.status == "sent" and row.offer_price_cents, row.status
    assert _reply(row)["nearest"]["asked_subject"] == "blowjob", _reply(row)
    assert "You don't have that exact one" not in _system(fw), _system(fw)

    # "off": today's Refusal row.
    with _draft(sell_nearest="off"), _vault(PRICED):
        r, fw, picks = _post(_body("nr-off"), "ok:not right now babe",
                             jev=({**QUIET, "wants_content": .9}, 1.0, BJ_PHOTO))
    (row,) = _rows("nr-off")
    assert picks == [Refusal("no_match")] and r.json()["offer"] is None, picks
    rp = _reply(row)
    assert rp["refusal"] == "no_match" and "nearest" not in rp, rp
    assert all(getattr(row, c) is None for c in OFFER_COLS), {c: getattr(row, c) for c in OFFER_COLS}


# ── The Writer ────────────────────────────────────────────────────────

def case_asked_words_table():
    table = [
        ({"subject": "blowjob", "format": "photo"}, "a blowjob photo"),
        ({"subject": "feet", "format": "video"}, "a feet video"),
        ({"subject": "anything", "format": "photo"}, "a photo"),
        ({"subject": "toy", "format": "any"}, "a toy piece"),
    ]
    for asked, want in table:
        assert wr.asked_words(asked) == want, (asked, wr.asked_words(asked))


def _line(mid, t, d):
    return SimpleNamespace(direction=d, body=t, created_at=None, message_id=mid, automation_kind=None,
                           media_count=0, raw_json=None, price_cents=None, is_paid=False, purchased_at=None)


def _turn(mode="test", **cfg):
    return SimpleNamespace(account_id="acct_near", fan_id=7, anchor_key="test:s:3", config={**DEFAULTS, **cfg},
                           fan_info={}, next_question=None, spent=[], offer_piece=None, mode=mode,
                           cut_rows=[_line(1, "hii", "out"), _line(2, "show me u sucking it", "in")])


HERO = {"media_id": 11, "kind": "photo", "seconds": None, "fields": {"description": "topless on the bed"}}
EXACT = Pick(ref=11, media=(11,), previews=(), price_cents=5000, list_cents=5000, subject="tits",
             format="photo", lane="$50", facts={"description": "topless on the bed", "items": [],
                                               "kinds": {"photo": 1}, "hero": HERO})
NEAR = Pick(**{**EXACT.__dict__, "subject": "anything",
               "facts": {**EXACT.facts, "asked": {"subject": "blowjob", "format": "photo"}, "nearest": "subject"}})
NOTE = wr.NEAREST_NOTE.format(asked="a blowjob photo", got="a photo")
assert wr.got_words(Pick(**{**NEAR.__dict__, "media": (11, 12, 13)})) == "3 photos"


def case_writer_note():
    item = wr.item_line(NEAR, wr.TERMS.format(dollars=50))
    # chat mode: the note directly under the item line.
    sys_ = wr.messages_for("sell_now", "sell", 3, _turn(), NEAR)[0]["content"]
    assert f"{item}\n{NOTE}" in sys_, sys_
    # caption mode: the bubbles before the PPV get nothing new; the caption call's prompt has it.
    apart = wr.messages_for("sell_now", "sell", 3, _turn(caption_writer="caption"), NEAR, plain=True)
    assert NOTE not in json.dumps(apart) and "You don't have that exact one" not in apart[0]["content"]
    cap = full_ai_caption.messages(_turn(caption_writer="caption"), NEAR, None)
    assert NOTE in cap[1]["content"] and NOTE not in cap[0]["content"], cap
    assert cap[1]["content"].index(NOTE) < cap[1]["content"].index("THE PRICE"), cap[1]["content"]
    # absent: plain, an exact match, Shadow.
    for why, facts, pick in (("plain", _turn(sell_nearest="plain"), NEAR), ("exact", _turn(), EXACT),
                             ("shadow", _turn("shadow"), NEAR)):
        msgs = wr.messages_for("sell_now", "sell", 3, facts, pick)
        caps = full_ai_caption.messages(facts, pick, None)
        assert "You don't have that exact one" not in json.dumps(msgs + caps), why


def case_sell_off_lines():
    off = dict(sell_on=False, sext_scene=True)
    table = [
        # (route, row, facts, kwargs, wanted line, why)
        ("sext", "scene_on", _turn(**off), dict(hot=True, scene="building"), wr.SELL_OFF_SCENE, "scene Turn"),
        ("sext", "sexual_now", _turn(sell_on=False, sext_scene=False), dict(hot=True), wr.SELL_OFF_LINE,
         "sext, no scene"),
        ("chat", "otherwise", _turn(**off), {}, wr.SELL_OFF_LINE, "chat"),
        ("chat", "sell_off", _turn(**off), {}, wr.SELL_OFF_LINE, "sell_off row (as before)"),
        ("chat", "otherwise", _turn(sell_on=True), {}, wr.NO_SELL_OFFERS, "selling on: a piece can arrive"),
        ("sext", "scene_on", _turn(sell_on=True, sext_scene=True), dict(hot=True, scene="building"),
         wr.NO_SELL_OFFERS, "selling on, scene"),
        ("chat", "otherwise", _turn("shadow", **off), {}, wr.NO_SELL_OFFERS, "Shadow unchanged"),
    ]
    lines = {wr.SELL_OFF_SCENE, wr.SELL_OFF_LINE, wr.NO_SELL_OFFERS}
    for route, row, facts, kw, want, why in table:
        s = wr.messages_for(route, row, 3, facts, None, **kw)[0]["content"]
        assert want in s and not any(x in s for x in lines - {want}), (why, s)


def shadow_prompts(wr_mod, cap_mod, pick_cls, defaults) -> list:
    """Shadow's Writer + caption prompts over the routes this PR touches, every `sell_nearest` /
    `sell_on` value; built the same way against origin/main's modules for the pin."""
    def turn(**cfg):
        return SimpleNamespace(account_id="acct_near", fan_id=7, anchor_key="shadow:s:3",
                               config={**defaults, **cfg}, fan_info={}, next_question=None, spent=[],
                               offer_piece=None, mode="shadow",
                               cut_rows=[_line(1, "hii", "out"), _line(2, "show me u sucking it", "in")])
    near = pick_cls(**{**EXACT.__dict__, "facts": dict(NEAR.facts)})
    out = []
    for nearest in ("off", "plain", "note"):
        for sell_on in (False, True):
            for cw in ("chat", "caption"):
                f = turn(sell_nearest=nearest, sell_on=sell_on, sext_scene=True, caption_writer=cw)
                for route, row, pick, kw in (("chat", "otherwise", None, {}), ("sext", "sexual_now", None,
                                                                                dict(hot=True)),
                                             ("chat", "sell_off", None, {}),
                                             ("sell_now", "sell", near, {}),
                                             ("sell_now", "sell", near, dict(plain=True))):
                    out.append(wr_mod.messages_for(route, row, 3, f, pick, **kw))
                out.append(cap_mod.messages(f, near, None))
    return out


# sha256 of `shadow_prompts` built against origin/main 6c7062847 (before sell_nearest).
SHADOW_SHA = "e31837e488a0bc2958d893e2ccf4590a10f0644a68bf9f818e7895eed2532686"


def case_shadow_prompts_pinned():
    got = hashlib.sha256(json.dumps(shadow_prompts(wr, full_ai_caption, Pick, DEFAULTS),
                                    sort_keys=True).encode()).hexdigest()
    assert got == SHADOW_SHA, got


def case_config():
    assert DEFAULTS["sell_nearest"] == "note" and full_ai_config.SELL_NEAREST == ("off", "plain", "note")
    assert full_ai_config.validate({**DEFAULTS, "sell_nearest": "plain"}) == []
    errs = full_ai_config.validate({**DEFAULTS, "sell_nearest": "always"})
    assert errs == ["sell_nearest: must be one of off, plain, note"], errs
    assert assistant_full_ai.label("sell_nearest") == "Nearest piece"
    assert "sell_nearest" in assistant_full_ai.CONFIG_KEYS


if __name__ == "__main__":
    _harness.run()
