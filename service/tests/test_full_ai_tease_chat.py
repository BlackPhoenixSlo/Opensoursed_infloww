#!/usr/bin/env python3
"""test_full_ai_tease_chat — the Pending tease and the Free item at the Test chat API (phase 03b,
ticket 46 phase B).

`POST /admin/full-ai/test/turn` and `POST /admin/full-ai/test/settle` over the shared selling
helpers (`_full_ai_sell_helpers`: two-Agency fixture, owner session cookies, a seeded vault) and
fakes at the network edges only (Jev at `_router_jev._client` / `_info_jev._client`, the Writers at
`llm_client.httpx.AsyncClient`). Every request runs inside `_guarded` (03a's invariants +
content_offers + `ownership.stamp_media_owned`).

Tease:
  case_tease_then_sell_same_piece      "how much?" / "I'm not buying" -> tease row (Pick, price NULL,
                                       no PPV, no `$`); his next reply -> row `sell`, the same piece
                                       (a fresh pick would differ); the Router saw the tease text
                                       as `pending_offer` (fetch, tease first)
  case_tease_gone_after_900s           the tease row 901 s old -> normal routing, `pending_offer` none
  case_complaint_after_tease           complaint inside the window -> make_right (rows 1-5 win)
  case_teased_piece_gone               teased photo removed -> re-pick of the same subject and
                                       format; then nothing of that format -> Refusal, never the clip
  case_tease_caption_fallback          the tease caption failing the audit twice -> priceless
                                       fallback caption, no `$`, still the tease row
  case_tease_buyer_no_spend_line       S3/S4: a prior buyer's tease prompt has no spend line, its
                                       text saying "free" passes the audit (no fallback caption)
  case_tease_sticker_only_tries_next   S2: GIFs on, a sticker-only tease -> floor:no_letters, the
                                       next Writer's text ships with the tease's Pick

Free item (make_right after a Buy, D52):
  case_free_item_after_buy             Buy -> complaint -> one unseen item at price 0 (row kind
                                       `free`, PPV 0), FREE item line, no spend line, "FREE" passes
                                       the audit (S3/S4); then Owned: never sold to him after
  case_free_item_needs_a_buy           a declined Offer is no Buy: apology alone, no sell step
  case_free_item_exhausted             everything already sent: Refusal all_owned, apology, no item
  case_free_item_sticker_only_tries_next  S2: a sticker-only Free-item reply -> floor:no_letters,
                                       the next Writer's text ships with the item
  case_settle_refuses_tease_and_free   settle on a tease / Free item row -> 422 not_a_priced_offer

Run: ./venv/bin/python service/tests/test_full_ai_tease_chat.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

from _full_ai_sell_helpers import (  # noqa: E402
    A, DRESSED, NANO, OPENROUTER, OWNER_A, PICS, PRICED, T0, TURN, _body, _db, _guarded, _hot, _jev,
    _picks, _ppvs, _put_draft, _reply, _rows, _sell_draft, _system, _vault,
)
import contextlib  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import update  # noqa: E402

from _full_ai_fixtures import QUIET, FakeJev, FakeWriterHTTP, _fake_jev  # noqa: E402
import vault_jev_rules  # noqa: E402
from automations import full_ai_sell, full_ai_writers as w  # noqa: E402
from automations.full_ai_config import DEFAULTS  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AiDecision, VaultItem  # noqa: E402

SETTLE = "/admin/full-ai/test/settle"
EURYALE, HERMES = DEFAULTS["writers"][:2]
_GIF_TAG = "laugh"
HOW_MUCH, NOT_BUYING = "how much?", "I'm not buying"
TEASE_TEXT = "mm its a cute one babe, u wanna see it"


def _turn(body: dict, script: dict | str, verdict):
    """One test turn under the invariants: (response json, Writer fake, Pick results, Router fake)."""
    script = {NANO: script} if isinstance(script, str) else script
    fw = FakeWriterHTTP({NANO: "ok:hii", OPENROUTER: "ok:hii", **script})
    fj = FakeJev(verdict)
    with _guarded(), _picks() as picks, fw.on(), _fake_jev(fj):
        r = OWNER_A.post(TURN, json=body)
    assert r.status_code == 200, r.text
    return r.json(), fw, picks, fj


def _settle(pair: str, row_id: int, outcome: str):
    with _guarded():
        return OWNER_A.post(SETTLE, json={"account_id": A, "pair": pair, "side": "draft",
                                          "row_id": row_id, "outcome": outcome})


def _texts(parts: list[dict]) -> list[str]:
    return [p["text"] for p in parts if "text" in p]


def _user(fw: FakeWriterHTTP, i: int = 0) -> str:
    return fw.requests[i]["body"]["messages"][1]["content"]


def _age(row_id: int, seconds: float) -> None:
    async def q():
        async with get_session() as s:
            row = await s.get(AiDecision, row_id)
            await s.execute(update(AiDecision).where(AiDecision.id == row_id).values(
                created_at=row.created_at - timedelta(seconds=seconds)))
            await s.commit()
    _db(q)


def _remove(mid: int) -> None:
    async def q():
        async with get_session() as s:
            await s.execute(update(VaultItem).where(VaultItem.account_id == A, VaultItem.media_id == mid)
                            .values(removed_at=datetime.utcnow()))
            await s.commit()
    _db(q)


def _add_clip(mid: int, lane: str) -> None:
    """A solo, priced 30 s clip in A's vault (`_vault` drops it with the rest)."""
    async def q():
        async with get_session() as s:
            s.add(VaultItem(account_id=A, media_id=mid, kind="video", duration_seconds=30,
                            created_at=T0 + timedelta(days=mid), tags="[]", describe_status="described",
                            of_folder_ids="[]", ai_fields_json=json.dumps(
                                {**DRESSED, "description": "a clip in jeans",
                                 vault_jev_rules.JEV_KEY: {**_jev(lane), "kind": "video", "frames": [],
                                                           "vv": vault_jev_rules.VIDEO_VERSION}})))
    _db(q)


def _tease_row_checks(got: dict, row: AiDecision, ref: int) -> None:
    """A tease row (ticket 07 r3): its Pick in the item ref, price NULL, no PPV, no `$` shown."""
    assert got["route"] == "tease" and got["status"] == "sent", got
    assert got["offer"] is not None and got["offer"]["kind"] == "tease", got["offer"]
    assert (got["offer"]["ref"], got["offer"]["price_cents"]) == (ref, None), got["offer"]
    assert _ppvs(got["parts"]) == [] and not any("$" in t for t in _texts(got["parts"])), got["parts"]
    item = json.loads(row.offer_item_ref)
    assert (item["kind"], item["ref"], row.offer_price_cents) == ("tease", ref, None), (item, row.offer_price_cents)
    assert row.outcome is None and row.offer_message_id is None


# ── Tease ─────────────────────────────────────────────────────────────

def case_tease_then_sell_same_piece():
    """Heat 2 teases the $10 photo (101); his next reply comes at Heat 3, where a fresh pick takes
    the $50 one (202): the sell is the teased 101 at its list price."""
    for pair, line, answers, row_name in (("t-price", HOW_MUCH, _hot(price=0.9), "tease_price"),
                                          ("t-decline", NOT_BUYING, _hot(declines_buying=0.9), "tease_decline")):
        with _sell_draft(), _vault(PRICED):
            tease, fw, (pick,), _ = _turn(_body(pair, line), f"ok:{TEASE_TEXT}", (answers, 1.0))
            assert isinstance(pick, full_ai_sell.Pick) and pick.ref == 101, pick
            (row,) = _rows(pair)
            assert row.route_row == row_name, row.route_row
            _tease_row_checks(tease, row, 101)
            system = _system(fw)
            assert w.GOAL_HEAD + w.TEASE_GOAL + w.item_line(pick, None) in system, system
            assert "SELLING RULES" not in system and "to unlock" not in system, system
            assert _reply(row)["caption_fallback"] is False, _reply(row)
            sell, _, picks, fj = _turn(_body(pair, "ok", n=2), "ok:here u go babe", (QUIET, 2.0))
        # fetch's one source, tease first: her tease bubbles, space-joined.
        assert fj.calls[0]["state"]["pending_offer"] == " ".join(_texts(tease["parts"])), fj.calls[0]["state"]
        assert (sell["route"], _rows(pair)[1].route_row) == ("sell_now", "sell"), sell
        assert sell["offer"]["kind"] == "offer" and sell["offer"]["ref"] == 101, sell["offer"]
        assert sell["offer"]["price_cents"] == 1000 and picks == [], (sell["offer"], picks)
        assert _ppvs(sell["parts"]) == [len(sell["parts"]) - 1], sell["parts"]


def case_tease_gone_after_900s():
    pair = "t-expired"
    with _sell_draft(), _vault(PRICED):
        tease, _, _, _ = _turn(_body(pair, HOW_MUCH), f"ok:{TEASE_TEXT}", (_hot(price=0.9), 1.0))
        _age(tease["row_id"], 901)
        got, _, picks, fj = _turn(_body(pair, "ok", n=2), "ok:hehe what u up to", (QUIET, 1.0))
    assert fj.calls[0]["state"]["pending_offer"] == "none", fj.calls[0]["state"]
    assert (got["route"], _rows(pair)[1].route_row) == ("chat", "otherwise"), got
    assert got["offer"] is None and picks == [], got


def case_complaint_after_tease():
    pair = "t-complaint"
    with _sell_draft(), _vault(PRICED):
        _turn(_body(pair, HOW_MUCH), f"ok:{TEASE_TEXT}", (_hot(price=0.9), 1.0))
        got, fw, picks, _ = _turn(_body(pair, "this is a scam", n=2), "ok:omg im so sorry babe",
                                  (_hot(complains_now=0.9), 1.0))
    assert (got["route"], _rows(pair)[1].route_row) == ("make_right", "complains_now"), got
    # No Buy in this session: the apology alone, no sell step.
    assert got["offer"] is None and picks == [] and w.MAKE_RIGHT_TAIL in _system(fw), got


def case_teased_piece_gone():
    """The teased photo leaves the vault inside the window: his next reply sells the other photo
    (same subject anything, same format photo), never the $10 clip a fresh any-format pick could
    take; with no photo left at all it is a Refusal, never the clip."""
    pair = "t-repick"
    photo = (_hot(price=0.9), 1.0, {"asks_format": "photo"})
    with _sell_draft(), _vault(PRICED):
        _add_clip(303, "$10")
        _, _, (pick,), _ = _turn(_body(pair, HOW_MUCH), f"ok:{TEASE_TEXT}", photo)
        assert (pick.ref, pick.format) == (101, "photo"), pick
        _remove(101)
        got, _, (again,), _ = _turn(_body(pair, "ok", n=2), "ok:here u go babe", (QUIET, 1.0))
        assert got["route"] == "sell_now" and got["offer"]["ref"] == 202, got
        assert (again.subject, again.format) == ("anything", "photo"), again
        # Tease again (the clip is still there); then the last photo goes too.
        _, _, (pick2,), _ = _turn(_body(pair, HOW_MUCH, n=3), f"ok:{TEASE_TEXT}", photo)
        assert pick2.ref == 202, pick2
        _remove(202)
        got2, _, (none,), _ = _turn(_body(pair, "ok", n=4), "ok:mm not right now", (QUIET, 1.0))
    assert none == full_ai_sell.Refusal("no_match"), none
    assert got2["route"] == "sell_now" and got2["offer"] is None and _ppvs(got2["parts"]) == [], got2
    assert _reply(_rows(pair)[3])["refusal"] == "no_match", _reply(_rows(pair)[3])


def case_tease_caption_fallback():
    """spec 03b line 195: the tease caption claims 5 videos for one photo, the rewrite too -> the
    priceless fallback caption, no `$`, the row still a tease with its Pick."""
    pair = "t-fallback"
    with _sell_draft(), _vault(PRICED):
        got, fw, (pick,), _ = _turn(_body(pair, HOW_MUCH),
                                    {NANO: ["ok:5 videos just for u babe", "ok:5 videos waiting for u"]},
                                    (_hot(price=0.9), 1.0))
    (row,) = _rows(pair)
    want = full_ai_sell.fallback_caption(pick, "tease")
    assert want == "1 pic" and _texts(got["parts"]) == [want], (want, got["parts"])
    assert _reply(row)["caption_fallback"] is True and len(fw.requests) == 2, _reply(row)
    _tease_row_checks(got, row, 101)


def case_tease_buyer_no_spend_line():
    """S3 + S4: after a Buy the tease prompt carries no spend line (its amounts would fail the
    price check); a tease text saying "free" names no price, so it passes (no fallback caption)."""
    pair = "t-buyer"
    free_text = "feel free to imagine it babe, its so cute"
    with _sell_draft(), _vault(PRICED):
        sold, _, _, _ = _turn(_body(pair, PICS), "ok:mm ok i have something for u", (_hot(wants_content=0.9), 1.0))
        assert sold["offer"]["ref"] == 101, sold
        assert _settle(pair, sold["row_id"], "bought").status_code == 200
        got, fw, (pick,), _ = _turn(_body(pair, HOW_MUCH, n=2), f"ok:{free_text}", (_hot(price=0.9), 1.0))
    assert pick.ref == 202 and got["offer"]["kind"] == "tease", (pick, got["offer"])
    assert "he's spent" not in _user(fw) and "$10" not in _user(fw), _user(fw)
    assert _texts(got["parts"]) and _reply(_rows(pair)[1])["caption_fallback"] is False, got["parts"]
    assert "free" in " ".join(_texts(got["parts"])), got["parts"]


def case_tease_sticker_only_tries_next():
    """S2: GIFs on, the first Writer answers a tease with only a sticker: a tease carries its Pick,
    so the lone gif can't be the reply -> floor:no_letters, the second Writer's text ships."""
    pair = "t-sticker"
    with _draft(sell_on=True, gifs=True), _vault(PRICED):
        got, fw, (pick,), _ = _turn(_body(pair, HOW_MUCH), {NANO: f"ok:STICKER: {_GIF_TAG}",
                                                            OPENROUTER: f"ok:{TEASE_TEXT}"},
                                    (_hot(price=0.9), 1.0))
    assert [(a["writer"], a["outcome"]) for a in got["attempts"]] == [
        (EURYALE, "floor:no_letters"), (HERMES, "ok")], got["attempts"]
    assert len(fw.requests) == 2 and got["writer"] == HERMES, got
    (row,) = _rows(pair)
    _tease_row_checks(got, row, pick.ref)


# ── Free item (make_right after a Buy) ────────────────────────────────

FREE_VAULT = {**PRICED, 303: "$10"}
SORRY = "omg im so sorry babe, this one is FREE for u"


def _buy(pair: str, n: int = 1) -> dict:
    """Turn `n` sells (Heat 2: the $10 photo 101 first) and he buys it."""
    sold, _, _, _ = _turn(_body(pair, PICS, n=n), "ok:mm ok i have something for u", (_hot(wants_content=0.9), 1.0))
    assert sold["route"] == "sell_now" and sold["offer"]["kind"] == "offer", sold
    assert _settle(pair, sold["row_id"], "bought").status_code == 200
    return sold


def case_free_item_after_buy():
    """D52: a complaint after a Buy -> make_right with one unseen item at price 0 (row kind `free`,
    a PPV of 0 on the last bubble), the FREE item line, no spend line; S4: her "FREE" passes.
    Then it is Owned: his next content ask sells the other photo, never the Free item."""
    pair = "f-buy"
    with _sell_draft(sell_bundle="shoot"), _vault(FREE_VAULT):     # one-photo Buy: 303 stays unseen
        sold = _buy(pair)
        got, fw, (gift,), _ = _turn(_body(pair, "this is a scam", n=2), f"ok:{SORRY}",
                                    (_hot(complains_now=0.9), 1.0))
        assert (got["route"], _rows(pair)[1].route_row) == ("make_right", "complains_now"), got
        assert gift.ref == 303 and gift.price_cents == 0 and sold["offer"]["ref"] == 101, (gift, sold)
        assert (got["offer"]["kind"], got["offer"]["ref"], got["offer"]["price_cents"]) == ("free", 303, 0), got
        ppvs = _ppvs(got["parts"])
        assert ppvs == [len(got["parts"]) - 1] and got["parts"][-1]["ppv"]["price_cents"] == 0, got["parts"]
        row = _rows(pair)[1]
        assert json.loads(row.offer_item_ref)["kind"] == "free" and row.offer_price_cents == 0, row.offer_item_ref
        system = _system(fw)
        assert w.item_line(gift, w.FREE_TERMS) in system and w.MAKE_RIGHT_TAIL not in system, system
        assert "SELLING RULES" not in system and "he's spent" not in _user(fw), _user(fw)
        assert _reply(row)["caption_fallback"] is False and "FREE" in " ".join(_texts(got["parts"])), got
        later, _, (pick,), _ = _turn(_body(pair, PICS, n=3), "ok:here u go babe", (_hot(wants_content=0.9), 1.0))
    assert pick.ref == 202 and later["offer"]["ref"] == 202, (pick, later["offer"])


def case_free_item_needs_a_buy():
    """D52: an Offer he declined is no Buy: the complaint gets the apology alone, no sell step."""
    pair = "f-declined"
    with _sell_draft(), _vault(FREE_VAULT):
        sold, _, _, _ = _turn(_body(pair, PICS), "ok:mm ok i have something for u", (_hot(wants_content=0.9), 1.0))
        assert _settle(pair, sold["row_id"], "declined").status_code == 200
        got, fw, picks, _ = _turn(_body(pair, "this is a scam", n=2), "ok:omg im so sorry babe",
                                  (_hot(complains_now=0.9), 1.0))
    assert got["route"] == "make_right" and got["offer"] is None and picks == [], (got, picks)
    assert _ppvs(got["parts"]) == [] and w.MAKE_RIGHT_TAIL in _system(fw), got["parts"]
    assert "refusal" not in _reply(_rows(pair)[1]), _reply(_rows(pair)[1])


def case_free_item_exhausted():
    """Every item already sent to him (101 bought, 202 offered and not bought: seen, not Owned): a
    Refusal (all_owned) keeps make_right's apology, no item, never chat."""
    pair = "f-exhausted"
    with _sell_draft(), _vault(PRICED):
        _buy(pair)
        offered, _, _, _ = _turn(_body(pair, PICS, n=2), "ok:here u go babe", (_hot(wants_content=0.9), 1.0))
        assert offered["offer"]["ref"] == 202, offered
        got, fw, picks, _ = _turn(_body(pair, "this is a scam", n=3), "ok:omg im so sorry babe",
                                  (_hot(complains_now=0.9), 1.0))
    assert picks == [], picks                   # the pool refuses before any draw
    assert got["route"] == "make_right" and got["offer"] is None and _ppvs(got["parts"]) == [], got
    assert w.MAKE_RIGHT_TAIL in _system(fw) and "SELLING RULES" not in _system(fw), _system(fw)
    assert _reply(_rows(pair)[2])["refusal"] == "all_owned", _reply(_rows(pair)[2])


def case_free_item_sticker_only_tries_next():
    """S2: a Free item carries an offer, so a sticker-only make_right reply is floor:no_letters and
    the next Writer's text ships with the item."""
    pair = "f-sticker"
    with _draft(sell_on=True, gifs=True), _vault(FREE_VAULT):
        _buy(pair)
        got, fw, (gift,), _ = _turn(_body(pair, "this is a scam", n=2),
                                    {NANO: f"ok:STICKER: {_GIF_TAG}", OPENROUTER: f"ok:{SORRY}"},
                                    (_hot(complains_now=0.9), 1.0))
    assert [(a["writer"], a["outcome"]) for a in got["attempts"]] == [
        (EURYALE, "floor:no_letters"), (HERMES, "ok")], got["attempts"]
    assert got["offer"]["kind"] == "free" and got["offer"]["ref"] == gift.ref, got
    assert _ppvs(got["parts"]) == [len(_texts(got["parts"])) - 1], got["parts"]


def case_settle_refuses_tease_and_free():
    """spec 03b story 59: settle on a tease row or a Free item row -> 422 `not_a_priced_offer`,
    nothing written."""
    pair = "f-settle"
    with _sell_draft(sell_bundle="shoot"), _vault(FREE_VAULT):     # one-photo Buy: 303 stays unseen
        _buy(pair)
        free, _, _, _ = _turn(_body(pair, "this is a scam", n=2), f"ok:{SORRY}", (_hot(complains_now=0.9), 1.0))
        tease, _, _, _ = _turn(_body(pair, HOW_MUCH, n=3), f"ok:{TEASE_TEXT}", (_hot(price=0.9), 1.0))
    assert (free["offer"]["kind"], tease["offer"]["kind"]) == ("free", "tease"), (free, tease)
    for got in (free, tease):
        for outcome in ("bought", "declined"):
            r = _settle(pair, got["row_id"], outcome)
            assert r.status_code == 422 and "not_a_priced_offer" in r.text, (got["offer"], r.status_code, r.text)
    rows = _rows(pair)
    assert [(x.outcome, x.outcome_at, x.join_src) for x in rows[1:]] == [(None, None, None)] * 2, rows


@contextlib.contextmanager
def _draft(**cfg):
    """A's draft side with `cfg` over DEFAULTS (through the config API), DEFAULTS again after."""
    _put_draft({**DEFAULTS, **cfg})
    try:
        yield
    finally:
        _put_draft(dict(DEFAULTS))


if __name__ == "__main__":
    _harness.run()
