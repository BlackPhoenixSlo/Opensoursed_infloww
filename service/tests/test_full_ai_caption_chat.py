#!/usr/bin/env python3
"""test_full_ai_caption_chat — `caption_writer` "caption": the PPV's caption from its own call, the
chat bubbles before it from a Writer prompt with no item, price or `>>OFFER`, through the Relay API.

`POST /admin/full-ai/test/turn` over the shared sell helpers (two-Agency fixture, owner cookies,
the 03a invariants), fakes at the network edges only (Jev, the Writers' wire). One NanoGPT script
per Turn: the caption call first, then the chat Writer.

  case_default_chat_unchanged        caption_writer "chat": one Writer call, no `caption` key
  case_caption_writes_the_ppv_line   the caption call's line ships as the last bubble with the PPV;
                                     the chat prompt has no item line, price or OFFER
  case_caption_one_bubble_girl       style on: a caption with commas / a line break stays one bubble
  case_caption_asked_marker_stripped rwl3 A2: an ASKED line in the caption is stripped, never sent
  case_caption_price_fail_fallback   a wrong price twice: rewrite (same messages), then today's
                                     path (the chat Writer's sell prompt and caption)
                                     (`caption.rejected`: each refused text + its checks)
  case_caption_rewrite_ok            a wrong first caption, a true rewrite: the rewrite ships
  case_chat_bubble_fails_alone       a chat bubble claiming a vid on a photo: the caption ships alone
  case_free_item_caption             make_right Free item: FREE price block, apology frames + DRAFT line
  case_was_price_caption             haggle re-offer: the OLD-CORE-33 was-price block in the caption
  case_prompt_is_old_wording         the assembled system + user equal the old 1:1 wording (literals)
  case_no_description_and_shadow     no described media -> None; shadow / tease / priced make_right
                                     never take the caption path
  case_chat_block_test_live_only     test / live: the last CHAT_TAIL rows (FAN / YOU, his newest last)
                                     under CHAT_RULE; Shadow and an empty thread: the old prompt
  case_differs_rule                  a Pick not what he asked for: DIFFERS_RULE in the style's place
                                     (price only when priced), the note, set facts, price block;
                                     an exact Pick keeps its seeded style; its shape passes
                                     caption_fails at the right price only; NAME_PRICE under the
                                     price block when priced, never on a Free / exact Pick
  case_preview_count                 previews: the locked count rule, "never as free" only when priced

Run: ./venv/bin/python service/tests/test_full_ai_caption_chat.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

from _full_ai_sell_helpers import (  # noqa: E402
    A, NANO, OPENROUTER, OWNER_A, PICS, PRICED, TURN, _body, _guarded, _hot, _picks, _ppvs, _put_draft,
    _reply, _rows, _vault,
)
import contextlib  # noqa: E402
import json  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from _full_ai_fixtures import FakeJev, FakeWriterHTTP, _fake_jev  # noqa: E402
import vault_ai_brief  # noqa: E402
from automations import full_ai_caption as fc, full_ai_sell, full_ai_test, full_ai_turn, full_ai_writers as w  # noqa: E402
from automations.full_ai_config import DEFAULTS  # noqa: E402
from automations.full_ai_decide import Decision  # noqa: E402
from automations.full_ai_sell import Pick  # noqa: E402

SETTLE = "/admin/full-ai/test/settle"
EURYALE = DEFAULTS["writers"][0]
GOOD = "caught myself in jeans in the mirror, $10 to unlock"
LEAD = "mm ok babe"


def _cap(text: str) -> str:
    return "ok:" + json.dumps({"caption": text})


def _turn(body: dict, script: list[str] | str, verdict):
    """One test turn under the invariants: (response json, Writer fake)."""
    fw = FakeWriterHTTP({NANO: "ok:hii", OPENROUTER: "ok:hii"})
    fw.script[NANO] = list(script) if isinstance(script, list) else script
    with _guarded(), _picks(), fw.on(), _fake_jev(FakeJev(verdict)):
        r = OWNER_A.post(TURN, json=body)
    assert r.status_code == 200, r.text
    return r.json(), fw


def _settle(pair: str, row_id: int, outcome: str):
    with _guarded():
        return OWNER_A.post(SETTLE, json={"account_id": A, "pair": pair, "side": "draft",
                                          "row_id": row_id, "outcome": outcome})


@contextlib.contextmanager
def _draft(**cfg):
    _put_draft({**DEFAULTS, "sell_on": True, **cfg})
    try:
        yield
    finally:
        _put_draft(dict(DEFAULTS))


def _set(**cfg) -> None:
    _put_draft({**DEFAULTS, "sell_on": True, **cfg})


def _sys(fw, i: int) -> str:
    return fw.requests[i]["body"]["messages"][0]["content"]


def _usr(fw, i: int) -> str:
    return fw.requests[i]["body"]["messages"][1]["content"]


def _texts(parts: list[dict]) -> list[str]:
    return [p["text"] for p in parts if "text" in p]


def _sells(fw, i: int) -> bool:
    """Request `i`'s prompt carries an item, a price or the marker (today's sell prompt)."""
    s = _sys(fw, i)
    return any(x in s for x in ("CONTENT YOU CAN ACTUALLY SEND HIM", "THE PRICE", ">>OFFER", "$"))


def _outcomes(attempts: list[dict]) -> list[tuple]:
    return [(a["writer"], a["outcome"], a.get("rewrite", False)) for a in attempts]


ASK = (_hot(wants_content=0.9), 1.0)       # Heat 2: the $10 photo 101


# ── Turns ─────────────────────────────────────────────────────────────

def case_default_chat_unchanged():
    pair = "c-default"
    with _draft(), _vault(PRICED):
        got, fw = _turn(_body(pair), ["ok:mm here u go babe, $10 to unlock"], ASK)
    assert len(fw.requests) == 1 and _sells(fw, 0), fw.requests
    assert "caption" not in got and "caption" not in _reply(_rows(pair)[0]), got
    assert not _sys(fw, 0).startswith(fc.HEAD)


def case_caption_writes_the_ppv_line():
    pair = "c-ok"
    with _draft(caption_writer="caption", text_style="formal"), _vault(PRICED):
        got, fw = _turn(_body(pair), [_cap(GOOD), f"ok:{LEAD}"], ASK)
    assert got["status"] == "sent" and got["offer"]["ref"] == 101, got
    assert len(fw.requests) == 2, fw.requests
    # Request 0: the caption call, the old 1:1 prompt (exact equality in case_prompt_is_old_wording).
    assert _sys(fw, 0).startswith(fc.HEAD) and _sys(fw, 0).endswith(fc.JSON_CONTRACT), _sys(fw, 0)
    assert _usr(fw, 0).endswith("\n\n" + w.PRICE_BLOCK.format(px="$10")), _usr(fw, 0)
    assert fw.requests[0]["body"]["temperature"] == fc.TEMPERATURE
    # Request 1: the chat Writer, no item, no price, no OFFER.
    assert not _sells(fw, 1) and w.CAPTION_APART in _sys(fw, 1) and w.NO_SELL_OFFERS in _sys(fw, 1), _sys(fw, 1)
    assert _texts(got["parts"]) == [LEAD, GOOD], got["parts"]
    assert _ppvs(got["parts"]) == [1] and got["parts"][1]["ppv"]["price_cents"] == 1000, got["parts"]
    cap = got["caption"]
    assert (cap["writer"], cap["model"], cap["outcome"]) == ("caption", EURYALE, "ok"), cap
    assert _outcomes(cap["attempts"]) == [(EURYALE, "ok", False)] and cap["ms"] >= 0, cap
    reply = _reply(_rows(pair)[0])
    assert reply["caption"] == cap and reply["caption_fallback"] is False, reply
    assert _outcomes(got["attempts"]) == [(EURYALE, "ok", False)], got["attempts"]   # the chat Writer's
    session = OWNER_A.get("/admin/full-ai/test/session",
                          params={"account_id": A, "pair": pair, "side": "draft"}).json()
    assert session["rows"][0]["caption"] == cap, session


def case_caption_one_bubble_girl():
    pair = "c-girl"
    line = "ok so, i caught myself in jeans\nin the mirror, wanna see"
    with _draft(caption_writer="caption"), _vault(PRICED):
        got, fw = _turn(_body(pair), [_cap(line), f"ok:{LEAD}"], ASK)
    assert got["caption"]["writer"] == "caption", got["caption"]
    last = got["parts"][-1]
    assert "ppv" in last and "jeans" in last["text"] and "mirror" in last["text"] and "\n" not in last["text"], got
    assert _ppvs(got["parts"]) == [len(got["parts"]) - 1], got["parts"]


def case_caption_asked_marker_stripped():
    """rwl3 A2: an `ASKED:` line in the caption never reaches the fan; the rest ships."""
    pair = "c-asked"
    with _draft(caption_writer="caption", text_style="formal"), _vault(PRICED):
        got, fw = _turn(_body(pair), [_cap(GOOD + "\nASKED: home_city"), f"ok:{LEAD}"], ASK)
    assert got["status"] == "sent" and "asked" not in json.dumps(got["parts"]).lower(), got["parts"]
    assert _texts(got["parts"]) == [LEAD, GOOD], got["parts"]


def case_caption_price_fail_fallback():
    pair = "c-fallback"
    chat = "here u go babe, $10 to unlock"
    with _draft(caption_writer="caption", text_style="formal"), _vault(PRICED):
        got, fw = _turn(_body(pair), [_cap("its $40 babe"), _cap("only $40 for u"), f"ok:{chat}"], ASK)
    assert len(fw.requests) == 3, fw.requests
    assert fw.requests[1]["body"]["messages"] == fw.requests[0]["body"]["messages"]   # same messages
    assert _sells(fw, 2), _sys(fw, 2)                                                 # today's prompt
    cap = got["caption"]
    assert (cap["writer"], cap["outcome"]) == ("chat", "failed"), cap
    assert _outcomes(cap["attempts"]) == [(EURYALE, "ok", False), (EURYALE, "ok", True)], cap
    assert _texts(got["parts"]) == [chat] and _ppvs(got["parts"]) == [0], got["parts"]
    assert "$40" not in json.dumps(got["parts"]) and _reply(_rows(pair)[0])["caption_fallback"] is False
    assert cap["rejected"] == [{"checks": ["price"], "text": "its $40 babe"},
                               {"checks": ["price"], "text": "only $40 for u"}], cap


def case_caption_rewrite_ok():
    pair = "c-rewrite"
    with _draft(caption_writer="caption", text_style="formal"), _vault(PRICED):
        got, fw = _turn(_body(pair), [_cap("all my videos for $10"), _cap(GOOD), f"ok:{LEAD}"], ASK)
    assert len(fw.requests) == 3 and not _sells(fw, 2), fw.requests
    assert (got["caption"]["writer"], got["caption"]["outcome"]) == ("caption", "rewrite_ok"), got["caption"]
    assert _texts(got["parts"]) == [LEAD, GOOD], got["parts"]


def case_chat_bubble_fails_alone():
    pair = "c-alone"
    with _draft(caption_writer="caption", text_style="formal"), _vault(PRICED):
        got, fw = _turn(_body(pair), [_cap(GOOD), "ok:my new vid is coming"], ASK)
    assert len(fw.requests) == 2 and got["caption"]["outcome"] == "alone", got["caption"]
    assert _texts(got["parts"]) == [GOOD] and _ppvs(got["parts"]) == [0], got["parts"]


FREE_VAULT = {**PRICED, 303: "$10"}


def case_free_item_caption():
    pair = "c-free"
    gift = "this ones on me babe, just me in the mirror"
    with _draft(text_style="formal"), _vault(FREE_VAULT):
        sold, _ = _turn(_body(pair, PICS), ["ok:mm ok i have something for u"], ASK)
        assert _settle(pair, sold["row_id"], "bought").status_code == 200
        _set(text_style="formal", caption_writer="caption")
        got, fw = _turn(_body(pair, "this is a scam", n=2), [_cap(gift), "ok:omg im so sorry babe"],
                        (_hot(complains_now=0.9), 1.0))
    assert got["route"] == "make_right" and got["offer"]["kind"] == "free", got
    assert _usr(fw, 0).endswith("\n\n" + fc.FREE_PRICE_BLOCK), _usr(fw, 0)
    chat = _sys(fw, 1)
    assert w.MAKE_RIGHT_HEAD in chat and w.CAPTION_APART in chat, chat
    assert w.MAKE_RIGHT_TAIL not in chat and w.FREE_TERMS not in chat and "[id " not in chat, chat
    assert _texts(got["parts"])[-1] == gift and got["parts"][-1]["ppv"]["price_cents"] == 0, got["parts"]
    assert got["caption"]["writer"] == "caption", got["caption"]


def case_was_price_caption():
    pair = "c-was"
    with _draft(draft_questions=True, text_style="formal"), _vault(PRICED):
        first, _ = _turn(_body(pair, PICS), ["ok:mm i have something for u"], (_hot(wants_content=0.9), 2.0))
        assert first["offer"]["price_cents"] == 5000, first["offer"]
        _set(draft_questions=True, text_style="formal", caption_writer="caption")
        got, fw = _turn(_body(pair, "would you do $20?", n=2), [_cap("ok $34 just for u babe"), "ok:hmm ok"],
                        (_hot(counter_offer=0.9), 2.0))
    assert (got["route_row"], got["offer"]["price_cents"]) == ("haggle", 3400), got
    assert _usr(fw, 0).endswith("\n\n" + w.WAS_PRICE_BLOCK.format(was="$50", px="$34")), _usr(fw, 0)
    assert not _sells(fw, 1), _sys(fw, 1)
    assert _texts(got["parts"]) == ["hmm ok", "ok $34 just for u babe"], got["parts"]
    assert got["parts"][-1]["ppv"]["price_cents"] == 3400, got["parts"]


# ── Pure ──────────────────────────────────────────────────────────────

# fastt describe_media.caption_style_prompt(style, "her", audience="1to1"), rendered, as literals.
_OLD_HEAD = ("You write first-person sales copy for an OnlyFans creator's PPV send, from the recorded "
             "facts about one piece of vault media.\n  caption - ")
_OLD_RULE = {
    "detail": "ONE sultry line <= 100 chars. OPEN with the most specific visual detail from the facts "
              "(garment, place, position), then the tease.\nAt most ONE emoji, only if it earns its place.\n",
    "house": "ONE sultry line <= 110 chars.\nAt most ONE emoji.\n",
    "blunt": "ONE sultry line <= 70 chars, NO emoji, no hashtags/@. Say the thing plainly. Shorter always wins.\n",
    "question": "ONE sultry line <= 110 chars ending in a QUESTION he wants answered. Never state what "
                "the media shows outright.\n",
}
_OLD_TAIL = ("GROUND TRUTH: never name a colour, garment, place, body part or act that is\n"
             "not in the facts above. If the facts do not say it, you may not write it.\n"
             "You do not know WHEN this was filmed, whether it expires, or whether it is\n"
             "leaving. Never claim a time, a deadline or a limited window.\n"
             "Match the register of these (adapt to the facts, never copy them):\n"
             '  "couldnt keep the red set on for long"\n'
             '  "you caught me in the tub... come see"\n'
             'Respond with STRICT JSON only: {"caption": "..."}.')
# fastt _ppv_caption.body_suffix(him_lines(...), price_cents=1000) with his name and kink.
_OLD_SUFFIX = ("\n\nWHO IS READING IT\n  - his name: Mike\n  - into: feet\n\n"
               "Use this to choose WHICH TRUE DETAIL of the media to open on, and how to address him. "
               "It is NOT a list of things the media contains. Never name an act, a garment or a body "
               "part that the facts above do not list, however much he wants it — the HARD RULE above "
               "wins every time.\nWork in AT MOST ONE thing about him, and only if it lands naturally. "
               "A caption that just sells the media beats one that name-drops his job.\n\n"
               "THE PRICE\nIt unlocks at $10. You may name it or not, but if you name a price it must "
               "be exactly $10.")
_OLD_WAS = ("THE PRICE\nHe already saw this piece at $50 and did not buy. It is $34 now because you cut "
            "it for him. You may name $34; if you name a price it must be exactly $34. Never beg and "
            "never apologise for the first price.")

HERO = {"clothing_state": "dressed", "acts": ["posing"], "penetration": "none", "explicitness": "sfw",
        "people_count": 1, "partner_visible": False, "setting": "bedroom", "description": "a mirror selfie in jeans"}


def _pick(price: int, list_cents: int | None = None, fields: dict | None = HERO) -> Pick:
    hero = {"media_id": 7, "kind": "photo", "seconds": None, "fields": fields} if fields else None
    return Pick(ref=7, media=(7,), previews=(), price_cents=price, list_cents=list_cents or price,
                subject="dressed", format="photo", lane="$10",
                facts={"kinds": {"photo": 1}, "items": [], "description": "", "hero": hero})


def _facts(**fan) -> SimpleNamespace:
    return SimpleNamespace(account_id=A, fan_id=42, fan_info=fan)


def case_prompt_is_old_wording():
    for style in fc.STYLES:
        assert fc.system(style) == _OLD_HEAD + _OLD_RULE[style] + _OLD_TAIL, style
    msgs = fc.messages(_facts(real_name="Mike", fetishes="feet"), _pick(1000), None)
    style = fc.style_for(A, 42, 7)
    assert msgs[0] == {"role": "system", "content": _OLD_HEAD + _OLD_RULE[style] + _OLD_TAIL}, msgs[0]
    brief = vault_ai_brief.copy_brief(HERO, description="a mirror selfie in jeans", kind="photo")
    assert msgs[1]["content"] == brief + _OLD_SUFFIX, msgs[1]["content"]
    assert brief.startswith("WHAT IT IS: a mirror selfie in jeans\nACTS: posing\n") and \
        brief.endswith("\n\n" + vault_ai_brief.SELLING_BRIEF), brief
    assert fc.price_block(_pick(3400), 5000) == _OLD_WAS
    assert fc.price_block(_pick(3400), 3400) == w.PRICE_BLOCK.format(px="$34")
    assert fc.price_block(_pick(0), None) == "THE PRICE\nFREE — just send it when the moment fits"
    # No fan facts: no WHO IS READING IT block, the price block alone.
    bare = fc.messages(_facts(), _pick(1000), None)[1]["content"]
    assert bare.endswith(brief.split("WHAT IT IS")[0] + "\n\nTHE PRICE\nIt unlocks at $10. You may name it "
                         "or not, but if you name a price it must be exactly $10.") and "WHO IS" not in bare
    assert fc.parse('sure: {"caption": "hey u"} ') == "hey u" and fc.parse("hey u") == ""


def case_no_description_and_shadow():
    assert fc.messages(_facts(), _pick(1000, fields=None), None) is None
    p = _pick(1000)
    cfg = {**DEFAULTS, "caption_writer": "caption"}

    def on(route: str, mode: str = "test", pick=p, config=cfg) -> bool:
        d = Decision(route=route, heat=2, row="sell", fired=frozenset(), dropped=())
        return full_ai_turn._ppv_turn(d, SimpleNamespace(config=config, mode=mode, pick=pick))
    assert on("sell_now") and on("make_right", pick=_pick(0))
    assert not on("sell_now", mode="shadow") and not on("tease") and not on("make_right")
    assert not on("sell_now", config=DEFAULTS) and not on("sell_now", pick=None)
    assert full_ai_test.MODE == "test"


def _row(d: str, body: str) -> SimpleNamespace:
    return SimpleNamespace(direction=d, body=body, media_count=0, raw_json=None)


def _tfacts(mode: str, rows: list, **cfg) -> SimpleNamespace:
    return SimpleNamespace(account_id=A, fan_id=42, fan_info={}, mode=mode, cut_rows=rows,
                           config={**DEFAULTS, "caption_writer": "caption", **cfg})


def case_chat_block_test_live_only():
    rows = [_row("out" if i % 2 else "in", f"line {i}") for i in range(20)] + [_row("in", "show me ur feet")]
    pick = _pick(1000)
    old = fc.messages(_facts(), pick, None)
    for mode in ("test", "live"):
        user = fc.messages(_tfacts(mode, rows), pick, None)[1]["content"]
        shown = rows[-fc.CHAT_TAIL:]
        lines = "\n".join(f"{'FAN' if r.direction == 'in' else 'YOU'}: {r.body}" for r in shown)
        assert f"\n\n{fc.CHAT_HEAD}\n{lines}\n\n{fc.CHAT_RULE}\n\n{fc.set_facts(pick)}" in user, user
        assert lines.endswith("FAN: show me ur feet") and "line 5\n" not in user, lines
        assert user.index(fc.CHAT_HEAD) < user.index("THE SET HE GETS") < user.index("\n\nTHE PRICE\n"), user
        # No-differs: the old prompt plus the chat block and set facts only; the seeded style kept.
        assert user.replace(f"\n\n{fc.CHAT_HEAD}\n{lines}\n\n{fc.CHAT_RULE}", "").replace(
            f"\n\n{fc.set_facts(pick)}", "") == old[1]["content"], user
        assert fc.messages(_tfacts(mode, rows), pick, None)[0] == old[0]
        assert fc.CHAT_HEAD not in fc.messages(_tfacts(mode, []), pick, None)[1]["content"]
    assert fc.messages(_tfacts("shadow", rows), pick, None) == old            # Shadow: byte-identical


NEAR_FACTS = {"kinds": {"photo": 3}, "items": [], "description": "topless on the bed", "asked": {"subject": "feet", "format": "video"},
              "media": [{"id": i, "kind": "photo", "seconds": None} for i in (7, 8, 9, 10)]}


def case_differs_rule():
    rows = [_row("out", "hii"), _row("in", "send me a feet video")]
    base = _pick(4500)
    near = Pick(**{**base.__dict__, "media": (7, 8, 9), "previews": (10,), "facts": {**base.facts, **NEAR_FACTS}})
    msgs = fc.messages(_tfacts("live", rows), near, None)
    priced = fc.differs_rule(True)
    assert msgs[0]["content"] == fc.HEAD + priced + _OLD_TAIL, msgs[0]["content"]
    assert "<= 220 chars" in priced and "how many he unlocks in plain words (\"1 photo\", \"2 videos\") and the price from THE PRICE" in priced, priced
    assert not any(fc.STYLE_RULES[st].format(tone=fc.TONE) in msgs[0]["content"] for st in fc.STYLES)
    user = msgs[1]["content"]
    note = w.NEAREST_NOTE.format(asked="a feet video", got="3 photos")
    for part in (note, "THE SET HE GETS: 3 photos, locked, plus 1 photo he sees without unlocking.",
                 "FAN: send me a feet video", w.PRICE_BLOCK.format(px="$45") + fc.NAME_PRICE):
        assert part in user, (part, user)
    assert user.index("THE SET HE GETS") < user.index(note) < user.index("\n\nTHE PRICE\n"), user
    # The shape it asks for passes the Claim audit at the right price (locked or shown count), not a wrong one.
    good = "not what u asked for babe, no feet vid, but 3 pics of me topless on the bed, plus one u can see, $45"
    assert full_ai_sell.caption_fails(good, near, 4500) == []
    assert full_ai_sell.caption_fails(good.replace("$45", "$40"), near, 4500) == ["price"]
    free = Pick(**{**near.__dict__, "price_cents": 0})
    fs = fc.messages(_tfacts("live", rows), free, None)
    assert fs[0]["content"] == fc.HEAD + fc.differs_rule(False) + _OLD_TAIL, fs[0]["content"]
    assert "price" not in fc.differs_rule(False) and "how many he gets in plain words (\"1 photo\", \"2 videos\");" in fc.differs_rule(False)
    assert fs[1]["content"].endswith("\n\n" + fc.FREE_PRICE_BLOCK), fs[1]["content"]
    exact = fc.messages(_tfacts("live", rows), base, None)[1]["content"]
    assert exact.endswith("\n\n" + w.PRICE_BLOCK.format(px="$45")) and fc.NAME_PRICE not in exact, exact
    # "plain" and Shadow: no note, no differs rule.
    for f in (_tfacts("live", rows, sell_nearest="plain"), _tfacts("shadow", rows)):
        m = fc.messages(f, near, None)
        assert note not in m[1]["content"] and "<= 220" not in m[0]["content"], m
        assert fc.NAME_PRICE not in m[1]["content"], m


def case_preview_count():
    base = _pick(4500)
    with_prev = Pick(**{**base.__dict__, "media": (7, 8, 9), "previews": (10,),
                        "facts": {**base.facts, "kinds": {"photo": 3}, "media": NEAR_FACTS["media"]}})
    got = fc.set_facts(with_prev)
    assert got == ("THE SET HE GETS: 3 photos, locked, plus 1 photo he sees without unlocking. Name only these "
                   "kinds and counts." + fc.PREVIEW_COUNT.format(free=", never as free")), got
    assert "A count you give is the locked count" in got and "never add the ones he already sees" in got
    assert fc.set_facts(Pick(**{**with_prev.__dict__, "price_cents": 0})).endswith('you can already see").')
    none = Pick(**{**base.__dict__, "media": (7, 8), "facts": {**base.facts, "kinds": {"photo": 2},
                                                               "media": NEAR_FACTS["media"][:2]}})
    assert fc.set_facts(none) == "THE SET HE GETS: 2 photos, locked. Name only these kinds and counts."


if __name__ == "__main__":
    _harness.run()
