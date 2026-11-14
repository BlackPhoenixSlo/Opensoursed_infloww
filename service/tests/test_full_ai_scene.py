#!/usr/bin/env python3
"""test_full_ai_scene — the Full AI sext scene (config `sext_scene`, test Mode), pure, plain assert.

  case_scene_next_table          start, climb, never back, after -> new scene, off -> None, heat floor
  case_scene_words               Jev's `scene` state words
  case_switches                  scene_flag / is_hot / scene_turn / gif_offered over flag × Mode × Route
  case_flag_off_prompts_pinned   flag off: 14 Writer prompts byte-identical to origin/main's builder
  case_scene_prompts             scene Turns: SEXT_SCENE + stage (+ SEXT_HEAT on sext / SCENE_SELL on
                                 a hot sell / CAPTION_APART apart / need-line on a Refusal); no
                                 EXPLICIT_EARLY, NO_NARRATION_RULE, SELF_BAN, SEXT_HOT, sticker block
  case_scene_constants_in_catalog  every new constant is in docs/prompts/new/current-repo.md
  case_level_lane                `offer_level` target -> lane; None -> the heat path
  case_cents_of_table            the price ladder interpolated, nearest $5, clamped
  case_offer_state               the price Jev's `offer` from a Pick
  case_purchases_of              settled priced Offers in words, oldest first
  case_haggle_never_above_quote  `_haggled` after a Jev price ends at or under that quote

Run: ./venv/bin/python service/tests/test_full_ai_scene.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB before any db import

import hashlib  # noqa: E402
import json  # noqa: E402
from dataclasses import replace  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from automations import _price_jev as pj  # noqa: E402
from automations import full_ai_sell as fs  # noqa: E402
from automations import full_ai_test as ft  # noqa: E402
from automations import full_ai_writers as wr  # noqa: E402
from automations._prompt_rules import NO_NARRATION_RULE  # noqa: E402
from automations.full_ai_config import DEFAULTS  # noqa: E402
from automations.full_ai_decide import Decision  # noqa: E402
from automations.full_ai_scene import scene_next, scene_words  # noqa: E402
from automations.full_ai_sell import Pick, Refusal, Teased  # noqa: E402
from automations.full_ai_turn import _haggled  # noqa: E402

_DOCS = Path(__file__).resolve().parents[2] / "docs" / "prompts"


def case_scene_next_table():
    p = lambda n, stage, heat: {"n": n, "stage": stage, "heat": heat}   # noqa: E731
    rows = [   # (prev, on, Jev stage or None, heat) -> next
        ((None, False, "peak", 3), None),                                  # not a scene Turn
        ((p(4, "peak", 4), False, "peak", 4), None),                       # scene over
        ((None, True, None, 2), p(1, "opening", 2)),                       # start, Jev default
        ((None, True, "building", 3), p(1, "building", 3)),                # start mid-way
        ((None, True, "after", 3), p(1, "after", 3)),
        ((p(1, "opening", 2), True, "building", 3), p(2, "building", 3)),  # climb
        ((p(2, "building", 3), True, None, 3), p(3, "building", 3)),       # default keeps
        ((p(2, "building", 3), True, "opening", 2), p(3, "building", 3)),  # never back, heat floor
        ((p(3, "peak", 4), True, "building", 1), p(4, "peak", 4)),
        ((p(3, "peak", 4), True, "after", 4), p(4, "after", 4)),
        ((p(4, "after", 4), True, "after", 2), p(5, "after", 4)),
        ((p(4, "after", 4), True, None, 2), p(5, "after", 4)),             # default: keeps after
        ((p(4, "after", 4), True, "opening", 2), p(1, "opening", 2)),      # after -> a new scene
        ((p(5, "after", 4), True, "building", 3), p(1, "building", 3)),
        ((p(2, "weird", 1), True, None, 2), p(3, "opening", 2)),           # unknown saved stage
    ]
    for (prev, on, stage, heat), want in rows:
        got = scene_next(prev, on, stage, heat)
        assert got == want, (prev, on, stage, heat, got, want)


def case_scene_words():
    assert scene_words(None) == "none"
    assert scene_words({"n": 3, "stage": "building", "heat": 3}) == \
        "sexting for 3 of her messages so far, stage: building"


def _facts(mode="test", **cfg):
    return SimpleNamespace(mode=mode, config={**DEFAULTS, **cfg})


def case_switches():
    D = lambda route, *fired: Decision(route, 3, "x", frozenset(fired))   # noqa: E731
    on, off, shadow = _facts(sext_scene=True), _facts(sext_scene=False), _facts("shadow", sext_scene=True)
    assert wr.scene_flag(on) and not wr.scene_flag(off) and not wr.scene_flag(shadow)
    rows = [   # (decision, facts) -> (is_hot, scene_turn)
        ((D("sext", "sexual_now"), on), (True, True)),
        ((D("sext", "scene_on"), on), (True, True)),
        ((D("sell_now", "scene_on", "scene_offer"), on), (True, True)),
        ((D("sell_now", "wants_content"), on), (False, False)),
        ((D("chat", "scene_on"), on), (True, False)),
        ((D("sell_now", "scene_on"), off), (False, False)),           # flag off: scene_on is nothing
        ((D("sell_now", "sexual_now"), off), (True, False)),          # old hot, no scene
        ((D("sext", "sexual_now"), shadow), (True, False)),
        ((D("sell_now", "scene_on"), _facts(sext_scene=True, sext_on=False)), (False, False)),
    ]
    for (d, f), want in rows:
        assert (wr.is_hot(d.fired, f), wr.scene_turn(d, f)) == want, (d, f.mode, f.config["sext_scene"])
    gifs = [   # gif_offered: (decision, facts) -> bool
        ((D("chat"), _facts(gifs=True, sext_scene=False)), True),     # flag off: every Turn
        ((D("sext", "sexual_now"), _facts(gifs=True, sext_scene=False)), True),
        ((D("chat"), _facts(gifs=True, sext_scene=True)), False),     # needs gif_fits
        ((D("chat", "gif_fits"), _facts(gifs=True, sext_scene=True)), True),
        ((D("sext", "sexual_now", "gif_fits"), _facts(gifs=True, sext_scene=True)), False),  # scene
        ((D("chat", "gif_fits"), _facts(gifs=False, sext_scene=True)), False),
        ((D("chat"), _facts("shadow", gifs=True, sext_scene=True)), True),
    ]
    for (d, f), want in gifs:
        assert wr.gif_offered(d, f) is want, (d, f.mode, f.config)


def _row(d, t, mid):
    return SimpleNamespace(direction=d, body=t, created_at=None, message_id=mid, automation_kind=None,
                           media_count=0, raw_json=None, price_cents=None, is_paid=False, purchased_at=None)


def _turn(**cfg):
    return SimpleNamespace(account_id="acct_snap", anchor_key="test:s:3", config={**DEFAULTS, **cfg},
                           fan_info={}, next_question=None, spent=[], offer_piece=None, mode="test",
                           cut_rows=[_row("out", "hii", 1), _row("in", "im so hard for u", 2)])


PICK = Pick(ref=11, media=(11, 12), previews=(), price_cents=5000, list_cents=5000, subject="tits",
            format="photo", lane="$50", facts={"description": "topless on the bed", "items": [],
                                              "kinds": {"photo": 2}})
# sha256 of the 14 prompts below as origin/main (c847cb09f) built them, before the sext scene.
FLAG_OFF_PROMPTS_SHA = "00570ca587295d9a7222dad2e8fe1be44a375476e9317e7e90aea2792f08560f"


def case_flag_off_prompts_pinned():
    """Flag off: chat, sext, hot / cold / apart sell, a hot Refusal and offer_moment, GIFs off and
    on, byte-identical to the builder before the sext scene (`lead_in` off too)."""
    cases = []
    for gifs in (False, True):
        for route, row, pick, hot, plain in (
                ("chat", "otherwise", None, False, False), ("sext", "sexual_now", None, False, False),
                ("sell_now", "sell", PICK, True, False), ("sell_now", "sell", PICK, False, False),
                ("sell_now", "sell", PICK, True, True), ("sell_now", "sell", Refusal("no_match"), True, False),
                ("sell_now", "offer_moment", PICK, False, False)):
            cases.append(wr.messages_for(route, row, 3, _turn(gifs=gifs, sext_scene=False, lead_in=False), pick,
                                         hot=hot, plain=plain))
    # Selling off in test Mode puts SELL_OFF_LINE in NO_SELL_OFFERS' place (sell_nearest PR); put
    # back, every prompt is byte-identical to the pinned builder.
    cases = json.loads(json.dumps(cases).replace(json.dumps(wr.SELL_OFF_LINE)[1:-1],
                                                 json.dumps(wr.NO_SELL_OFFERS)[1:-1]))
    got = hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest()
    assert got == FLAG_OFF_PROMPTS_SHA, got


def _scene_system(route, pick=None, *, stage="building", heat=3, plain=False, gifs=True):
    f = _turn(gifs=gifs, sext_scene=True)
    return wr.messages_for(route, "scene_on", heat, f, pick, hot=True, plain=plain, scene=stage,
                           gif_ok=False)[0]["content"]


def case_scene_prompts():
    sticker = "STICKER:"
    for stage in wr.SCENE_STAGE:
        sext = _scene_system("sext", stage=stage, heat=4)
        assert f"{wr.SEXT_SCENE}\n{wr.SCENE_STAGE[stage]}\n{wr.SEXT_HEAT.format(heat=4)}" in sext
    sell = _scene_system("sell_now", PICK, stage="peak")
    assert (f"{wr.SEXT_SCENE}\n{wr.SCENE_STAGE['peak']}" + wr.SCENE_SELL.format(
        close=wr.CLOSE_BY_ID, example=wr._voice.HER.sell_caption_example)) in sell
    assert "HEAT " not in sell.split(wr.SEXT_SCENE)[1].split("\n\n")[0]      # no Heat line on a sell
    apart = _scene_system("sell_now", PICK, plain=True)
    assert f"{wr.SEXT_SCENE}\n{wr.SCENE_STAGE['building']}\n{wr.CAPTION_APART}" in apart
    refused = _scene_system("sell_now", Refusal("no_match"))
    assert f"{wr.SEXT_SCENE}\n{wr.SCENE_STAGE['building']}" in refused and wr.FILMING_MORE in refused
    for s in (_scene_system("sext"), sell, apart, refused):
        assert wr.SCENE_NARRATION in s and wr.SCENE_SELF in s
        for gone in (wr.EXPLICIT_EARLY, NO_NARRATION_RULE, wr.SELF_BAN, wr.SEXT_HOT, sticker):
            assert gone not in s, gone[:40]
    # gif_ok None keeps `config.gifs` (the old rule); False drops the block on any Route.
    f = _turn(gifs=True, sext_scene=True)
    assert sticker in wr.messages_for("chat", "otherwise", 2, f, None)[0]["content"]
    assert sticker not in wr.messages_for("chat", "otherwise", 2, f, None, gif_ok=False)[0]["content"]


def case_scene_constants_in_catalog():
    new = (_DOCS / "new" / "current-repo.md").read_text(encoding="utf-8")
    from automations import _router_jev as rj
    for c in (wr.SEXT_SCENE, *wr.SCENE_STAGE.values(), wr.SCENE_SELL, wr.SCENE_NARRATION.strip(),
              wr.SCENE_SELF, pj.PRICE["instructions"], *pj.PRICE["criteria"],
              *(rj.TEST_NOULS[q]["instructions"] for q in ("scene_on", "scene_offer")),
              *(rj.TEST_CHOICES[q]["instructions"] for q in ("scene_stage", "offer_level"))):
        flat = " ".join(c.split())
        assert flat in " ".join(new.split()), c[:60]


def _vault(media_id, lane, kind="photo", desc="x"):
    return {"media_id": media_id, "list_cents": lane, "kind": kind, "subject_tags": ["tits"],
            "fields": {"description": desc}, "outfit_key": None, "duration_seconds": None}


def case_level_lane():
    """`target` (LEVEL_CENTS) picks the lane; None keeps the heat path."""
    import automations.full_ai_sell as m
    pool = [_vault(1, 1000), _vault(2, 5000), _vault(3, 10000)]
    real = m._matches
    m._matches = lambda r, ask: True
    try:
        ask = fs.Ask("anything", "any", 1)                          # heat 1 -> $10 on the heat path
        assert fs.pick(pool, [], ask, seed="s").price_cents == 1000
        for level, want in (("soft", 1000), ("nude", 5000), ("explicit", 10000)):
            got = fs.pick(pool, [], ask, seed="s", target=fs.LEVEL_CENTS[level])
            assert got.price_cents == want, (level, got)
        assert fs.LEVEL_CENTS.get("any") is None
        assert fs.pick(pool, [], fs.Ask("anything", "any", 4), seed="s").price_cents == 10000
    finally:
        m._matches = real


def case_cents_of_table():
    rows = [(0, 1000), (1, 2000), (2, 3500), (3, 5000), (4, 7500), (5, 10000), (6, 15000),
            (0.5, 1500), (1.5, 3000), (2.3, 4000), (2.5, 4500), (3.5, 6500), (5.5, 12500),
            (4.2, 8000), (-1, 1000), (9, 15000)]
    for score, want in rows:
        assert pj.cents_of(score) == want, (score, pj.cents_of(score), want)
    assert len(pj.PRICE_LADDER_CENTS) == len(pj.PRICE["criteria"]) == 7
    assert all(fs.MIN_CENTS <= pj.cents_of(s / 10) <= fs.MAX_CENTS for s in range(-10, 80))


def case_offer_state():
    vid = Pick(ref=5, media=(5,), previews=(9,), price_cents=5000, list_cents=5000, subject="toy",
               format="video", lane="$50", facts={"kinds": {"video": 1}, "shown_kinds": {"video": 1, "photo": 1},
                                                  "items": [{"seconds": 95}], "descriptions": ["toy clip", ""]})
    assert pj.offer_state(vid) == {"photos": 0, "videos": 1, "video_seconds": [95], "free_previews": 1,
                                   "shows": ["toy clip"], "level": "$50", "list_price": "$50"}
    st = pj.state({"fan_new_messages": ["a"], "thread": ["b"], "x": 1}, 3, "none", ["bought 1"], PICK)
    assert list(st) == list(pj.STATE_KEYS) and st["heat"] == "3 of 4" and "x" not in st


def case_purchases_of():
    def r(rid, price, outcome, n, fmt, lane, desc=None):
        ref = {"ref": rid, "format": fmt, "lane": lane, "kind": "offer", **({"desc": desc} if desc else {})}
        return SimpleNamespace(id=rid, offer_item_ref=json.dumps(ref), offer_price_cents=price,
                               outcome=outcome, offer_media_json=json.dumps({"locked": list(range(n))}))
    rows = [r(1, 1000, "bought", 2, "photo", "$10", "topless on the bed"),
            r(2, 5000, "declined", 1, "video", "$50", "toy clip"),
            r(3, 0, "bought", 1, "photo", "free"),                      # a Free item: not priced
            r(4, 3500, None, 1, "photo", "$50"),                        # open: not settled
            r(5, 2000, "bought", 1, "photo", "$10")]
    assert ft.purchases_of(rows) == ["bought 2 photos for $10 (lane $10): topless on the bed",
                                     "said no to 1 video at $50: toy clip",
                                     "bought 1 photo for $20 (lane $10)"]
    assert ft.purchases_of([]) == []


def case_haggle_never_above_quote():
    """A Jev-priced Offer records Jev's price as its list (`_price`), so a haggle on it (same piece
    or a re-pick listed higher in the vault) never ends above the quote."""
    quoted = replace(PICK, price_cents=3500, list_cents=3500, facts={**PICK.facts, "vault_list_cents": 5000})
    piece = Teased("tits", "photo", tuple(sorted(quoted.media)), (), quoted.list_cents, 7)
    for his in (["ok 100"], ["30?"], ["how about 20"], ["deal"], ["50 and its a deal"]):
        same = _haggled(PICK, piece, True, his)                       # vault list $50, quote $35
        assert same.price_cents <= 3500 and same.list_cents <= 3500, (his, same)
        other = _haggled(replace(PICK, ref=99, media=(99,), list_cents=3000, price_cents=3000), piece, False, his)
        assert other.price_cents <= 3500, (his, other)


_harness.run()
