#!/usr/bin/env python3
"""test_full_ai_ride — the off-path wording (test Mode: SEXT_HOT_TEST, SELL_STEP_TEST,
ESCALATION_TEST, the no-Spacing `scene_offer`) and the ride delivery of a Chat tease (config
`chat_tease`, test Mode): on row offer_moment, not hot, the unasked offer is a Chat tease, its
photos riding her ordinary reply, which never mentions them. The old `offer_ride` (Ride-along
photos) is retired into `chat_tease` (owner 2026-11-14 "combine the doubles").

  case_flag_table             `offer_ride` retired: not in DEFAULTS / labels; a stored side holding it
                              reads, validates and saves, the key dropped
  case_ride_switches          `tease_turn`: test Mode + `chat_tease` + sell_now chat_tease, or
                              offer_moment not hot; `ride_flag` / `ride_turn` gone
  case_pick_ride              pure `pick(ride=True)`: photos only, 1-2, never a video, never 3, no
                              preview, marked `facts["ride"]`; `ride=False` is today's Pick
  case_ride_prompt            pure `messages_for` with a ride Pick: the chat prompt + RIDE_NOTE; no item
                              line, price block, marker or ESCALATION*; a tease Turn's Refusal: no need-line
  case_twins                  test Mode composes the _TEST twins, Shadow the old three byte for byte
  case_no_example             SELL_STEP_TEST / SCENE_SELL prompts carry no `sell_caption_example`;
                              Shadow's SELL_STEP prompt still does
  case_scene_offer_wording    TEST_NOULS["scene_offer"] (no-Spacing) text; Shadow digest pinned
  case_wording_in_catalog     every new wording is in docs/prompts/new/current-repo.md
  case_api_ride               Test chat, chat_tease on, offer_moment: the tease price Jev's price, 2
                              photos, no caption call, row ride, the PPV on her last bubble, claim audit
                              passes, Spacing and `teases_sent` count it
  case_api_ride_bad_claim     a reply naming a video / a wrong price twice: her text alone, no PPV,
                              `offer_dropped` "claim", the fallback caption never sent
  case_api_ride_asks_nothing  NEW-168: a ride prompt prints no ask ids / ASKED_EXCEPTION; a
                              volunteered marker stripped, nothing counted or recorded
  case_api_flag_off           chat_tease off: ESCALATION_TEST pitched, a 3-photo fill, no tease Jev
  case_api_hot_moment         chat_tease on, hot offer_moment: pitched (SELL_STEP_TEST), no ride
  case_api_scene_offer_unchanged  flag on, sext scene: row scene_offer sells as before (no ride)
  case_api_offer_ride_stored  a draft PUT holding `offer_ride` is refused; the GET has no such key
  case_fallback_caption_chained  rwl-a F2: the fallback caption runs the shared chain; a banned
                              word in it drops it: no text, `offer_dropped` "shape" (no PPV),
                              `dropped_reason` the chain's ("banned", rwl-a N5)
  case_ride_audit_fail_no_media_claim  rwl-a F6: a ride whose text fails twice ships only the
                              bubbles claiming no media and no price; none left -> no text,
                              `dropped_reason` "claim" (rwl-a N5)
  case_api_caption_no_chat_writer  rwl-a F9: the caption passed, every chat Writer failed: the
                              caption ships alone with its PPV (outcome "alone"), status sent

Run: ./venv/bin/python service/tests/test_full_ai_ride.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

from _full_ai_sell_helpers import (  # noqa: E402
    A, CONFIG, NANO, OPENROUTER, OWNER_A, PRICED, TURN, FakePriceJev, _body, _guarded, _picks, _post, _ppvs, _price,
    _put_draft, _reply, _rows, _system, _vault,
)
import contextlib  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from _full_ai_fixtures import QUIET_SCENE, QUIET_TEST, FakeInfoJev, FakeJev, FakeWriterHTTP, _fake_jev  # noqa: E402
import assistant_full_ai  # noqa: E402
import vault_ai_brief  # noqa: E402
import vault_jev_rules  # noqa: E402
from automations import _router_jev as rj  # noqa: E402
from automations import full_ai_sell as fs  # noqa: E402
from automations import full_ai_test as ft  # noqa: E402
from automations import full_ai_writers as wr  # noqa: E402
from automations import _price_jev  # noqa: E402
from automations.full_ai_config import DEFAULTS, REFERENCE, Invalid, merged, put_draft, validate  # noqa: E402
from automations.full_ai_decide import Decision  # noqa: E402
from automations.full_ai_sell import Pick  # noqa: E402

SHADOW_VERSION = "14f5d4f6222f"
SCENE_OFFER_TRUE = (
    "He is turned on and adding to the scene himself (he says what he wants, what he would do to her, "
    "or asks for more), they have each sent several sexting messages, no locked message of hers is "
    "waiting unbought in `thread`, and he has written three or more lines since the last locked "
    "message she sent")
# 2026-11-14: "he just said no to buying or cannot pay" dropped (then a decline sold now; since
# 2026-11-15 "broke" routes nothing).
SCENE_OFFER_FALSE = (
    "The sexting only just started, a locked message of hers "
    "in `thread` is still not bought, she sent or offered him something in one of her last two "
    "messages, he has written fewer than three lines since her last locked message, his lines are "
    "getting shorter or cooler, or he just came")
RIDE_WORDING = ("- A photo of you, or a few, goes out attached to this message by itself, free or locked. "
                "Write only your normal reply to what he said and keep the chat going: no word about the "
                "photo, no price, no 'want to see'.\n")
SELL_STEP_TEST_WORDING = (
    "\n4. THIS MESSAGE SENDS HIM THE PIECE. {close} Write it as the NEXT LINE OF THIS SCENE, matched to HIS OWN "
    "WORDS — what you're doing in it, for him — never as a product, never 'check out my new video'. Call it what "
    "it is (a pic, pics or a video, as its line says) and claim nothing its description does not show.")
SCENE_SELL_WORDING = (
    "\nTHIS MESSAGE SENDS HIM A LOCKED PIECE. {close} Write it as the NEXT LINE OF THIS SCENE, matched to HIS OWN "
    "WORDS — what you're doing in it, for him — never as a product, never 'check out my new video'.")
CLOSE = wr.CLOSE_BY_ID
EXAMPLE = wr._voice.HER.sell_caption_example


# ── Pure ──────────────────────────────────────────────────────────────

def case_flag_table():
    assert "offer_ride" not in DEFAULTS and "offer_ride" not in REFERENCE
    assert "offer_ride" not in assistant_full_ai.CONFIG_KEYS and "offer_ride" not in assistant_full_ai.LABELS
    assert REFERENCE["chat_tease"]["page"] == "Chat tease", REFERENCE["chat_tease"]
    # A stored side still holding it (PR #663's key) reads and validates, the key dropped; a write
    # carrying it, any value, is refused, naming its successor.
    old = {**DEFAULTS, "offer_ride": False, "chat_tease": False}
    got = merged({"checkpoint": old, "previous": old, "draft": old, "rev": 3})
    for side in ("checkpoint", "previous", "draft"):
        assert "offer_ride" not in got[side] and got[side]["chat_tease"] is False and validate(got[side]) == [], side
    for v in (True, False, "junk", None):
        assert validate({**DEFAULTS, "offer_ride": v}) == ["offer_ride: retired, folded into chat_tease: remove it"], v
    try:
        put_draft(None, old, 0)
        raise AssertionError("a retired key was stored")
    except Invalid as e:
        assert e.errors == ["offer_ride: retired, folded into chat_tease: remove it"], e.errors


def _facts(mode="test", **cfg):
    return SimpleNamespace(mode=mode, config={**DEFAULTS, **cfg})


def case_ride_switches():
    D = lambda route, row, *fired: Decision(route, 2, row, frozenset(fired))   # noqa: E731
    on = _facts(chat_tease=True, sext_scene=False)
    assert not hasattr(wr, "ride_flag") and not hasattr(wr, "ride_turn")
    rows = [   # (decision, facts) -> tease_turn
        ((D("sell_now", "offer_moment", "offer_moment"), on), True),
        ((D("sell_now", "chat_tease", "chat_tease"), on), True),
        ((D("sell_now", "sell", "wants_content"), on), False),
        ((D("sell_now", "scene_offer", "scene_on", "scene_offer"), _facts(sext_scene=True)), False),
        ((D("sell_now", "offer_moment", "offer_moment", "sexual_now"), on), False),           # hot
        ((D("sell_now", "offer_moment", "offer_moment", "scene_on"), _facts(sext_scene=True)), False),  # hot
        ((D("sell_now", "offer_moment", "offer_moment", "sexual_now"),
          _facts(chat_tease=True, sext_scene=False, sext_on=False)), True),                   # not hot
        ((D("chat", "offer_moment"), on), False),
        ((D("sell_now", "offer_moment", "offer_moment"), _facts(chat_tease=False)), False),
        ((D("sell_now", "offer_moment", "offer_moment"), _facts("shadow", chat_tease=True)), False),
        ((D("sell_now", "offer_moment", "offer_moment"), _facts("live", chat_tease=True)), True),   # live = test (04a)
    ]
    for (d, f), want in rows:
        assert wr.tease_turn(d, f) is want, (d, f.mode)
    p = Pick(ref=1, media=(1,), previews=(), price_cents=1000, list_cents=1000, subject="anything",
             format="photo", lane="$10", facts={"ride": True})
    assert wr.is_ride(p) and not wr.is_ride(fs.Refusal("no_match")) and not wr.is_ride(None)
    assert not wr.is_ride(Pick(**{**p.__dict__, "facts": {}}))


T0 = datetime(2026, 7, 1)
DRESSED = {"clothing_state": "dressed", "acts": ["posing"], "penetration": "none", "explicitness": "sfw",
           "underwear_visible": True, "vulva_vis": "covered", "breasts_vis": "covered",
           "anus_vis": "not_in_frame", "over_vulva": "jeans", "over_breasts": "t-shirt",
           "people_count": 1, "partner_visible": False}
ALL = {"include": [], "exclude": []}
ANY = fs.Ask("anything", "any", 2)


def _row(mid, lane="$50", kind="photo"):
    j = {"v": vault_jev_rules.VERSION, "status": "ok", "lane5": lane, "state": {}, "kind": kind,
         "breasts_bare": "n", "crotch_bare": "n", "penetration": "n", "tags": {}}
    if kind == "video":
        j.update(vv=vault_jev_rules.VIDEO_VERSION, frames=[])
    fields = vault_ai_brief.settled_reading({**DRESSED, vault_jev_rules.JEV_KEY: j})
    return {"media_id": mid, "kind": kind, "created_at": T0 + timedelta(minutes=mid),
            "duration_seconds": 12 if kind == "video" else None, "fields": fields,
            "describe_status": "described", "score": 0, "refs": set(), "packs": set()}


def _pick(rows, shoots=(), ask=ANY, *, seed="ride:s", **kw):
    pool = fs.pool(rows, [], set(), ALL, ask)
    assert isinstance(pool, list), pool
    return fs.pick(pool, list(shoots), ask, seed=seed, **kw)


def case_pick_ride():
    shoot6 = [_row(i) for i in range(1, 7)]
    loose = [_row(20), _row(21), _row(22), _row(23)]
    clip = _row(50, kind="video")
    for rows, shoots in ((shoot6, [{"items": [{"media_id": i} for i in range(1, 7)]}]),
                         (loose, []), (loose + [clip], []), ([clip, _row(51)], []), ([_row(60)], [])):
        for bundle in ("shoot", "fill"):
            for seed in (f"s{i}" for i in range(8)):
                got = _pick(rows, shoots, seed=seed, bundle=bundle, ride=True)
                assert isinstance(got, Pick), (rows, got)
                assert 1 <= len(got.media) <= 2 and got.format == "photo", got
                assert 50 not in got.media and got.previews == () and got.facts.get("ride") is True, got
                assert _pick(rows, shoots, seed=seed, bundle=bundle, ride=True) == got   # seeded
    assert len(_pick(shoot6, [{"items": [{"media_id": i} for i in range(1, 7)]}], ride=True).media) == 2
    assert len(_pick(loose, [], bundle="fill", ride=True).media) == 2                     # fill target 2
    assert len(_pick([_row(60)], [], bundle="fill", ride=True).media) == 1
    # Only a video: no ride piece (photos only).
    assert isinstance(_pick([clip], [], ride=True), fs.Refusal)
    # ride=False is today's Pick.
    for rows in (shoot6, loose, loose + [clip]):
        a = _pick(rows, [], bundle="fill")
        assert a == _pick(rows, [], bundle="fill", ride=False) and "ride" not in a.facts, a


def _turn_facts(mode="test", **cfg):
    def r(d, t, mid):
        return SimpleNamespace(direction=d, body=t, created_at=None, message_id=mid, automation_kind=None,
                               media_count=0, raw_json=None, price_cents=None, is_paid=False, purchased_at=None)
    return SimpleNamespace(account_id="acct_snap", anchor_key="test:r:3", config={**DEFAULTS, **cfg},
                           fan_info={}, next_question=None, spent=[SimpleNamespace(amount_cents=1000)], offer_piece=None,
                           mode=mode, cut_rows=[r("out", "hii", 1), r("in", "u look so good today", 2)])


PICK = Pick(ref=11, media=(11, 12), previews=(), price_cents=5000, list_cents=5000, subject="anything",
            format="photo", lane="$50", facts={"description": "a mirror selfie in jeans", "items": [],
                                              "kinds": {"photo": 2}})
RIDE = Pick(**{**PICK.__dict__, "facts": {**PICK.facts, "ride": True}})


def case_ride_prompt():
    f = _turn_facts(sext_scene=False, lead_in=False)
    ride = wr.messages_for("sell_now", "offer_moment", 2, f, RIDE)
    chat = wr.messages_for("chat", "offer_moment", 2, f, None)
    sys_ = ride[0]["content"]
    assert RIDE_WORDING in sys_, sys_
    assert sys_.replace(f"\n{RIDE_WORDING}", "", 1) == chat[0]["content"], (sys_, chat[0]["content"])
    for bad in (wr.ESCALATION[:40], wr.ESCALATION_TEST[:40], wr.PRICE_BLOCK.format(px="$50"), ">>OFFER",
                wr.item_line(RIDE, None)):
        assert bad not in sys_, bad
    # No spend line beside a ride Pick (its amounts would fail the price check).
    assert ride[1] != chat[1], chat[1]
    unspent = _turn_facts(sext_scene=False, lead_in=False)
    unspent.spent = []
    assert ride[1] == wr.messages_for("chat", "offer_moment", 2, unspent, None)[1], ride[1]
    # An unmarked Pick (flag off / no ride Turn): today's pitched offer_moment prompt.
    off = wr.messages_for("sell_now", "offer_moment", 2, f, PICK)[0]["content"]
    assert RIDE_WORDING not in off and wr.ESCALATION_TEST.format(close=CLOSE) in off
    # plain (a separate caption) or a Refusal never rides.
    assert RIDE_WORDING not in wr.messages_for("sell_now", "offer_moment", 2, f, RIDE, plain=True)[0]["content"]
    assert RIDE_WORDING not in wr.messages_for("sell_now", "offer_moment", 2, f, fs.Refusal("no_match"))[0]["content"]
    assert RIDE_WORDING not in wr.messages_for("tease", "offer_moment", 2, f, RIDE)[0]["content"]
    # A Refusal on a Chat tease Turn (chat_tease on, offer_moment not hot): plain chat, no need-line;
    # hot, or chat_tease off, it keeps the need-line (the pitched unasked offer).
    no = fs.Refusal("no_match")
    assert wr.FILMING_MORE not in wr.messages_for("sell_now", "offer_moment", 2, f, no)[0]["content"]
    assert wr.FILMING_MORE not in wr.messages_for("sell_now", "chat_tease", 2, f, no)[0]["content"]
    assert wr.FILMING_MORE in wr.messages_for("sell_now", "offer_moment", 2, f, no, hot=True)[0]["content"]
    off_f = _turn_facts(sext_scene=False, lead_in=False, chat_tease=False)
    assert wr.FILMING_MORE in wr.messages_for("sell_now", "offer_moment", 2, off_f, no)[0]["content"]
    shadow = _turn_facts("shadow", sext_scene=False, lead_in=False)
    assert wr.FILMING_MORE in wr.messages_for("sell_now", "offer_moment", 2, shadow, no)[0]["content"]


def case_twins():
    hot_test = wr.SEXT_HOT_TEST + wr.SELL_STEP_TEST.format(close=CLOSE, example=EXAMPLE)
    hot_old = wr.SEXT_HOT + wr.SELL_STEP.format(close=CLOSE, example=EXAMPLE)
    assert wr.sell_beat("sell", True, test=True) == hot_test
    assert wr.sell_beat("sell", True) == hot_old
    assert wr.sell_beat("offer_moment", False, test=True) == wr.ESCALATION_TEST.format(close=CLOSE)
    assert wr.sell_beat("offer_moment", False) == wr.ESCALATION.format(close=CLOSE)
    assert wr.sell_beat("sell", False, test=True) == wr.sell_beat("sell", False) == wr.CONTENT_ASK.format(close=CLOSE)
    # The old three stay verbatim (OLD-AIC-08 / step 4 / OLD-AIC-05).
    assert wr.SEXT_HOT.startswith("THE THREAD IS HOT") and "what would you do to me if you were here" in wr.SEXT_HOT
    assert wr.SELL_STEP.startswith("\n4. THEN SELL HIM WHAT HE JUST DESCRIBED.")
    assert wr.ESCALATION == ("HE'S CLEARLY INTO IT RIGHT NOW — the moment to SELL, not tease. Match his heat "
                             "in one short line, then close it: {close}")
    for mode, want_hot, want_esc in (("test", wr.SEXT_HOT_TEST, wr.ESCALATION_TEST),
                                     ("shadow", wr.SEXT_HOT, wr.ESCALATION)):
        f = _turn_facts(mode, sext_scene=False, lead_in=False, chat_tease=False)
        sext = wr.messages_for("sext", "sexual_now", 3, f, None)[0]["content"]
        hot = wr.messages_for("sell_now", "sell", 3, f, PICK, hot=True)[0]["content"]
        apart = wr.messages_for("sell_now", "sell", 3, f, PICK, hot=True, plain=True)[0]["content"]
        moment = wr.messages_for("sell_now", "offer_moment", 3, f, PICK)[0]["content"]
        assert want_hot in sext and want_hot in hot and want_hot in apart, mode
        assert want_esc.format(close=CLOSE) in moment, mode
        other = wr.SEXT_HOT if mode == "test" else wr.SEXT_HOT_TEST
        assert other not in sext + hot + apart, mode
        assert RIDE_WORDING not in sext + hot + apart + moment, mode
    # Shadow: a ride Pick never reaches a Shadow Turn (`tease_turn`); the builder keeps the old wording.
    shadow = _turn_facts("shadow", sext_scene=False, lead_in=False)
    assert wr.ESCALATION.format(close=CLOSE) in wr.messages_for("sell_now", "offer_moment", 3, shadow, PICK)[0]["content"]


def case_no_example():
    """Owner 2026-11-14 "Yes, drop the example line": test Mode's hot sell and the scene sell carry
    no example caption (the Writer copied it word for word); Shadow's SELL_STEP keeps it."""
    assert wr.SELL_STEP_TEST == SELL_STEP_TEST_WORDING and wr.SCENE_SELL == SCENE_SELL_WORDING
    assert "{example}" in wr.SELL_STEP and "{example}" not in wr.SELL_STEP_TEST + wr.SCENE_SELL
    test = _turn_facts(sext_scene=False, lead_in=False)
    hot = wr.messages_for("sell_now", "sell", 3, test, PICK, hot=True)[0]["content"]
    scene = wr.messages_for("sell_now", "sell", 3, _turn_facts(sext_scene=True, lead_in=False), PICK, hot=True,
                            scene="building")[0]["content"]
    shadow = wr.messages_for("sell_now", "sell", 3, _turn_facts("shadow", sext_scene=False, lead_in=False), PICK,
                             hot=True)[0]["content"]
    assert SELL_STEP_TEST_WORDING.format(close=CLOSE) in hot and EXAMPLE not in hot, hot
    assert SCENE_SELL_WORDING.format(close=CLOSE) in scene and EXAMPLE not in scene, scene
    assert wr.SELL_STEP.format(close=CLOSE, example=EXAMPLE) in shadow and EXAMPLE in shadow, shadow


def case_scene_offer_wording():
    q = rj.TEST_NOULS["scene_offer"]
    assert q["instructions"] == ("They are sexting. Is this a good moment for her to send him a locked photo "
                                 "or video as the next step of it?")
    assert q["criteria"] == {"true": SCENE_OFFER_TRUE, "false": SCENE_OFFER_FALSE}, q["criteria"]
    assert rj.question_version() == rj.QUESTION_VERSION == SHADOW_VERSION
    assert rj.THRESHOLDS["wants_content"] == 0.7
    assert "scene_offer" not in rj._questions()
    assert rj._questions("test", True)["scene_offer"].criteria["true"] == SCENE_OFFER_TRUE


def case_wording_in_catalog():
    from pathlib import Path
    doc = (Path(__file__).resolve().parents[2] / "docs" / "prompts" / "new" / "current-repo.md").read_text(encoding="utf-8")
    for nid in ("NEW-145", "NEW-146", "NEW-147", "NEW-148"):
        assert f"### {nid} " in doc, nid
    for text in (wr.SEXT_HOT_TEST, wr.SELL_STEP_TEST.strip("\n"), wr.ESCALATION_TEST, RIDE_WORDING.strip("\n")):
        assert text in doc, text[:40]
    assert json.dumps(SCENE_OFFER_TRUE) in doc and json.dumps(SCENE_OFFER_FALSE) in doc
    assert wr.RIDE_NOTE == RIDE_WORDING


# ── Through the Test chat API ─────────────────────────────────────────

class FakeTeaseJev:
    """`_price_jev._client`: the tease price Jev answers `verdict` (an option label) on every call,
    each call's questions recorded; an Offer price Score call raises (never asked on a tease)."""

    def __init__(self, verdict="$10"):
        self.verdict, self.calls = verdict, []

    async def system_one(self, state, questions, model=None):
        self.calls.append(list(questions))
        if _price_jev.TEASE_QID not in questions:
            raise RuntimeError("the Offer price Jev was asked")
        p = {k: (.8 if k == self.verdict else .01) for k in questions[_price_jev.TEASE_QID].criteria}
        return SimpleNamespace(choices={_price_jev.TEASE_QID: SimpleNamespace(choice=self.verdict, probabilities=p)})


@contextlib.contextmanager
def _draft(**cfg):
    _put_draft({**DEFAULTS, "sell_on": True, "draft_questions": True, "sext_scene": False, **cfg})
    try:
        yield
    finally:
        _put_draft(dict(DEFAULTS))


SAME = {301: "$50", 302: "$50", 303: "$50", 304: "$50"}
SOFT = {311: "$10", 312: "$10", 313: "$10", 314: "$10"}     # a ride draws only soft photos (rwl-a F4)
MOMENT = ({**QUIET_TEST, "offer_moment": .9}, 2.0)
CHATTY = "ok:haha stop ur making me blush, what are u up to tonight"


def case_api_ride():
    for cw in ("chat", "caption"):
        pair = f"r-ride-{cw}"
        with _draft(caption_writer=cw), _vault(SOFT), _price(FakeTeaseJev("$10")) as tj:
            r, fw, (pick,) = _post(_body(pair, "u look so good today"), CHATTY, jev=MOMENT)
            row = _rows(pair)[0]
        got = r.json()
        assert (got["route"], got["route_row"]) == ("sell_now", "offer_moment"), got
        assert tj.calls == [[_price_jev.TEASE_QID]], tj.calls          # the tease price Jev only
        # $10: up to tease_photos(1000) = 2 photos, locked at Jev's price, the vault list kept.
        assert len(pick.media) == 2 and set(pick.media) <= set(SOFT) and pick.format == "photo", pick
        assert pick.previews == (), pick
        assert len(fw.requests) == 1, [q["body"]["messages"][0]["content"][:80] for q in fw.requests]  # no caption
        system = _system(fw)
        assert RIDE_WORDING in system, system
        assert wr.ESCALATION_TEST[:40] not in system and wr.ESCALATION[:40] not in system
        assert ">>OFFER" not in system and "THE PRICE" not in system
        reply = _reply(row)
        assert reply["ride"] is True and "caption" not in reply and "price" not in reply, reply
        assert reply["chat_tease"]["cents"] == 1000 and reply["chat_tease"]["error"] is None, reply["chat_tease"]
        assert reply["caption_fallback"] is False and reply["claim_fail"] == [], reply
        assert "offer_dropped" not in reply, reply
        assert _ppvs(got["parts"]) == [len(got["parts"]) - 1], got["parts"]
        assert got["offer"]["price_cents"] == 1000 == row.offer_price_cents, got["offer"]
        assert sorted(json.loads(row.offer_media_json)["locked"]) == sorted(pick.media), row.offer_media_json
        # Spacing counts it as a Piece and an Unasked piece; Jev's `teases_sent` names it.
        rows = _rows(pair)
        sp = ft.spacing_of(rows, row.created_at + timedelta(minutes=1))
        assert sp["pieces_this_sitting"] == 1 and sp["unasked_pieces_this_sitting"] == 1, sp
        assert ft.is_tease(row) and ft.teases_sent_of(rows) == ["$10 photo set, he did not buy it"], ft.teases_sent_of(rows)


def case_api_ride_bad_claim():
    """Her reply names a video / a wrong price, the rewrite too: her text goes out alone (no PPV,
    no fallback caption naming the photos and the price), `offer_dropped` "claim"."""
    pair = "r-ride-bad"
    bad = "ok:here's a hot video for u, $99"
    with _draft(), _vault(SOFT), _price(FakeTeaseJev("$10")):
        r, fw, (pick,) = _post(_body(pair, "u look so good today"), bad, jev=MOMENT)
        row = _rows(pair)[0]
    got = r.json()
    reply = _reply(row)
    assert reply["ride"] is True and reply["offer_dropped"] == "claim", reply
    assert reply["caption_fallback"] is False, reply
    assert {c["check"] for c in reply["claim_fail"]} >= {"price"}, reply["claim_fail"]    # typos may hit "video"
    assert len(fw.requests) == 2, len(fw.requests)                                           # one rewrite
    assert got["parts"] and _ppvs(got["parts"]) == [] and got["offer"] is None, got
    assert row.offer_item_ref is None and row.offer_price_cents is None, row.offer_item_ref
    shipped = " ".join(p.get("text") or "" for p in got["parts"])
    assert fs.fallback_caption(pick, "offer") not in shipped and "to unlock" not in shipped, shipped


def case_api_ride_asks_nothing():
    """NEW-168 on a ride: only a chat Turn asks (`_info_stage`'s Choice, `ask_list`), so a ride's
    prompt prints no `[id]` and no ASKED_EXCEPTION, a volunteered marker is stripped and counts
    nothing, and no `asked_marker` is recorded (asks only on route chat)."""
    pair, bad = "r-ask-ride", "ok:omg stop it\nhere's a hot video for u, $99\nASKED: home_city"
    fw = FakeWriterHTTP({NANO: [bad, bad], OPENROUTER: "ok:hii"})
    with _draft(), _vault(SOFT), _price(FakeTeaseJev("$10")), _guarded(), _picks(), fw.on(), \
            _fake_jev(FakeJev(MOMENT), FakeInfoJev(({}, "home_city"))):
        r = OWNER_A.post(TURN, json=_body(pair, "u look so good today"))
        row = _rows(pair)[0]
    got, reply = r.json(), _reply(row)
    assert r.status_code == 200 and reply["ride"] is True and len(fw.requests) == 2, (r.text, reply)
    for i in (0, 1):
        assert "[home_city]" not in _system(fw, i) and wr.ASKED_EXCEPTION not in _system(fw, i), i
    assert got["status"] == "sent" and got["parts"] and reply["asked"] == {}, (got, reply)
    assert "asked_marker" not in reply, reply
    assert "ASKED" not in json.dumps(got["parts"]), got["parts"]


def case_api_flag_off():
    pair = "r-off"
    with _draft(chat_tease=False), _vault(SAME), _price(FakeTeaseJev()) as tj:
        r, fw, (pick,) = _post(_body(pair, "u look so good today"), "ok:mm 3 pics just for u", jev=MOMENT)
        row = _rows(pair)[0]
    assert r.json()["route_row"] == "offer_moment" and len(pick.media) == 3, pick
    assert tj.calls == [], tj.calls
    system = _system(fw)
    assert wr.ESCALATION_TEST.format(close=CLOSE) in system and RIDE_WORDING not in system, system
    reply = _reply(row)
    assert "ride" not in reply and "chat_tease" not in reply, reply
    assert row.offer_price_cents == 5000 and not ft.is_tease(row), row.offer_price_cents


def case_api_hot_moment():
    """chat_tease on, offer_moment while `sexual_now` fired (sext_on): the pitched hot sell
    (SEXT_HOT_TEST + SELL_STEP_TEST, no example), never a Chat tease."""
    pair = "r-hot"
    jev = ({**QUIET_TEST, "offer_moment": .9, "sexual_now": .9}, 3.0)
    with _draft(chat_tease=True), _vault(SAME), _price(FakeTeaseJev()) as tj:
        r, fw, (pick,) = _post(_body(pair, "fuck im so hard for u"), "ok:mm watch me babe", jev=jev)
        row = _rows(pair)[0]
    got = r.json()
    assert (got["route"], got["route_row"]) == ("sell_now", "offer_moment"), got
    assert tj.calls == [], tj.calls
    system = _system(fw)
    assert SELL_STEP_TEST_WORDING.format(close=CLOSE) in system and EXAMPLE not in system, system
    assert RIDE_WORDING not in system and "ride" not in _reply(row) and "chat_tease" not in _reply(row)
    assert got["offer"]["price_cents"] == 5000 and _ppvs(got["parts"]), got


def case_api_scene_offer_unchanged():
    pair = "r-scene"
    jev = ({**QUIET_SCENE, "scene_on": .9, "scene_offer": .9, "sexual_now": .9}, 3.0)
    for flag in (True, False):
        with _draft(sext_scene=True, chat_tease=flag), _vault(SAME), _price(FakePriceJev(2.0)):
            r, fw, (pick,) = _post(_body(f"{pair}-{flag}", "fuck im so hard for u"), "ok:mm watch me babe", jev=jev)
            row = _rows(f"{pair}-{flag}")[0]
        got = r.json()
        assert (got["route"], got["route_row"]) == ("sell_now", "scene_offer"), (got["route"], got["route_row"])
        system = _system(fw)
        assert RIDE_WORDING not in system and "ride" not in _reply(row), (flag, _reply(row))
        assert wr.SCENE_SELL.format(close=CLOSE, example=EXAMPLE) in system and EXAMPLE not in system, system[-600:]
        assert len(pick.media) == 3 and _ppvs(got["parts"]), (flag, pick, got["parts"])


def case_api_offer_ride_stored():
    """A draft PUT still holding the retired `offer_ride` is refused (422, naming `chat_tease`); nothing stored."""
    cur = OWNER_A.get(CONFIG, params={"account_id": A}).json()
    r = OWNER_A.put(f"{CONFIG}/draft", json={"account_id": A, "draft": {**DEFAULTS, "offer_ride": False}, "rev": cur["rev"]})
    assert r.status_code == 422 and "offer_ride: retired, folded into chat_tease: remove it" in r.text, r.text
    try:
        got = OWNER_A.get(CONFIG, params={"account_id": A}).json()
        assert got["rev"] == cur["rev"] and "offer_ride" not in got["draft"] and got["draft"]["chat_tease"] is True, got
        assert all(r["key"] != "offer_ride" for r in got.get("reference") or []), got.get("reference")
    finally:
        _put_draft(dict(DEFAULTS))


# ── _claim_audit, pure-ish (stubs: banned words; no Writer: too late for a rewrite) ──

def _audit_facts():
    return SimpleNamespace(account_id="acct_audit", fan_id=7, mode="test", anchor_key="test:a:1",
                           config={**DEFAULTS, "style": {**DEFAULTS["style"], "typos": False}},
                           typo_state={}, fan_info={}, cut_rows=[], pick=None)


async def _audit(pick, parts, banned=()):
    import time
    from automations import full_ai_turn as turn
    real = turn.load_banned_words

    async def words(_aid):
        return list(banned), "block"
    turn.load_banned_words = words
    try:
        f = _audit_facts()
        f.pick = pick
        reply = {"attempts": [], "leak": [], "dropped_reason": None, "typo_state": {}}
        got = await turn._claim_audit(Decision("sell_now", 2, "sell", frozenset()), f, reply, "w",
                                      parts, pick, time.monotonic())    # no time left: no rewrite
    finally:
        turn.load_banned_words = real
    return got, reply


async def case_fallback_caption_chained():
    bad = ["here's a hot video for u, $99"]
    got, reply = await _audit(PICK, bad)
    assert reply["caption_fallback"] is True and len(got) == 1 and "$50" in got[0], (got, reply)
    assert "offer_dropped" not in reply, reply
    got, reply = await _audit(PICK, bad, banned=("unlock",))
    assert got == [] and reply["offer_dropped"] == "shape" and reply["dropped_reason"] == "banned", (got, reply)


async def case_ride_audit_fail_no_media_claim():
    got, reply = await _audit(RIDE, ["omg stop it", "here's a hot video for u, $99"])
    assert reply["offer_dropped"] == "claim" and got == ["omg stop it"] and reply["dropped_reason"] is None, reply
    got, reply = await _audit(RIDE, ["here's a hot video for u, $99"])
    assert reply["offer_dropped"] == "claim" and got == [] and reply["dropped_reason"] == "claim", (got, reply)


def case_api_caption_no_chat_writer():
    pair, cap = "r-cap-alone", "caught myself in jeans in the mirror, $10 to unlock"
    script = {NANO: ["ok:" + json.dumps({"caption": cap}), *["400"] * 6], OPENROUTER: "400"}
    with _draft(caption_writer="caption", chat_tease=False, text_style="formal"), _vault(PRICED):
        r, fw, _ = _post(_body(pair), script)
    got = r.json()
    assert got["status"] == "sent" and got["caption"]["outcome"] == "alone", got
    assert [p.get("text") for p in got["parts"]] == [cap] and _ppvs(got["parts"]) == [0], got["parts"]
    assert got["offer"]["price_cents"] == 1000 and _rows(pair)[0].offer_price_cents == 1000, got["offer"]


_harness.run()
