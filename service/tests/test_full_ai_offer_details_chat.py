#!/usr/bin/env python3
from __future__ import annotations

import _harness

from _full_ai_sell_helpers import (  # noqa: E402
    A, IDS, NANO, OPENROUTER, OWNER_A, PRICED, TURN, _db, _guarded, _hot, _no_offer, _picks, _ppvs, _reply,
    _rows, _sell_draft, _system, _vault,
)
import contextlib  # noqa: E402
import json  # noqa: E402
from dataclasses import replace  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from sqlalchemy import delete, select, update  # noqa: E402

import vault_folder_prices  # noqa: E402
from _full_ai_fixtures import FakeInfoJev, FakeJev, FakeWriterHTTP, _fake_jev  # noqa: E402
from automations import _voice, cat_stickers, full_ai_offer_turn, full_ai_test  # noqa: E402
from automations import full_ai_writers as wr  # noqa: E402
from automations.full_ai_config import DEFAULTS  # noqa: E402
from automations.full_ai_offer_details import OfferFacts  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AiDecision, SensitiveWord, VaultItem  # noqa: E402

Q = "asks_offer_details"


def _body(pair: str, text: str, n: int = 1, side: str = "draft", **kw) -> dict:
    return {"account_id": A, "pair": pair, "side": side, "n": n, "text": text, **kw}


def _turn(body: dict, writer: str | list[str], verdict, info: FakeInfoJev | None = None):
    fw = FakeWriterHTTP({NANO: writer, OPENROUTER: writer})
    fj = FakeJev(verdict)
    with _guarded(), _picks(), fw.on(), _fake_jev(fj, info):
        r = OWNER_A.post(TURN, json=body)
    assert r.status_code == 200, r.text
    return r.json(), fj, fw


def case_c_open_offer_questions_hold_state():
    pair = "od-open"
    with _sell_draft(sext_scene=True), _vault(PRICED):
        _turn(_body(pair, "hey"), "ok:hii where u from\nASKED: home_city", (_hot(), 1.0),
              FakeInfoJev(({}, "home_city")))
        sold, _, _ = _turn(_body(pair, "send me something hot", n=2), "ok:mm this one babe",
                           (_hot(wants_content=0.9, sexual_now=0.9), 3.0))
        assert sold["route"] == "sell_now" and sold["offer"]["ref"] == 101, sold
        offer = _rows(pair)[1]
        before = _reply(offer)
        assert before["asked"] and before["scene"], before
        for n, text in enumerate(("what is this of?", "photo or video?", "how many?", "how long is it?"), 3):
            got, _, _ = _turn(_body(pair, text, n=n), "ok:its me in jeans babe", (_hot(**{Q: 0.95}), 3.0),
                              FakeInfoJev(({}, "home_city")))
            rows = _rows(pair)
            row, prev = rows[-1], _reply(rows[-2])
            assert (got["route"], row.route_row) == ("chat", "offer_details"), (text, got["route"], row.route_row)
            _no_offer(row)
            assert full_ai_test.open_offer_of(rows).id == offer.id, text
            assert (_reply(row)["asked"], _reply(row)["scene"]) == (prev["asked"], prev["scene"]), (text, _reply(row))
            assert "held_tease" not in _reply(row), _reply(row)
    assert len(full_ai_test._offers(_rows(pair))) == 1


def case_c_writer_answers_from_facts():
    pair = "od-writer"
    with _sell_draft(lead_in=True, gifs=True), _vault(PRICED):
        _turn(_body(pair, "send me pics"), "ok:mm this one babe", (_hot(wants_content=0.9), 1.0))
        joke, _, _ = _turn(_body(pair, "are u a bot?", n=2), "ok:beep boop lol", (_hot(asks_if_ai=0.9), 1.0))
        assert joke["route"] == "ai_dare", joke
        assert full_ai_test.dare_due_of(_rows(pair))
        got, _, fw = _turn(_body(pair, "whats in it?", n=3), "ok:its a mirror selfie in jeans babe",
                           (_hot(**{Q: 0.95, "gif_fits": 0.9}), 1.0))
    assert got["route"] == "chat" and not any("gif" in p for p in got["parts"]), got
    system = _system(fw)
    user = fw.requests[0]["body"]["messages"][1]["content"]
    for want in (wr.OFFER_GOAL, "THE OFFER HE MEANS", "1 pic", "1 locked (paid)", "a mirror selfie in jeans",
                 "price it went out at: $10"):
        assert want in system, (want, system)
    assert "same pieces" not in system and "free preview" not in system, system
    for banned in (wr.NO_SELL_OFFERS, wr.ASK_HEAD, wr.LEAD_HEAD, *wr.LEAD_EXAMPLES.values(), wr.DARE_NEXT,
                   wr.STICKER_EXCEPTION, cat_stickers.prompt_block("allow", _voice.VOICE_HER)):
        assert banned not in system, (banned, system)
    assert "he's spent" not in user, user
    assert not full_ai_test.dared_of(_rows(pair))


def _again(pair: str, n: int) -> None:
    async def go():
        async with get_session() as s:
            src = (await s.execute(select(AiDecision).where(
                AiDecision.fan_id == full_ai_test.test_fan_id(pair)).order_by(AiDecision.id.desc()))).scalars().first()
            cols = {c.name: getattr(src, c.name) for c in AiDecision.__table__.columns if c.name != "id"}
            key = full_ai_test.trigger_key(full_ai_test.session_key(pair, "draft"), n)
            s.add(AiDecision(**{**cols, "trigger_key": key, "created_at": datetime.utcnow()}))
            await s.commit()
    _db(go)


def _details_system(pair: str, text: str, n: int) -> str:
    got, _, fw = _turn(_body(pair, text, n=n), "ok:hmm babe", (_hot(**{Q: 0.95}), 1.0))
    assert got["route"] == "chat" and _rows(pair)[-1].route_row == "offer_details", got
    return _system(fw)


def case_c_vault_read_failure_still_answers():
    pair = "od-vault-fail"

    async def boom(*_a, **_k):
        raise RuntimeError("database is locked")

    with _sell_draft(), _vault(PRICED):
        _turn(_body(pair, "send me pics"), "ok:mm this one babe", (_hot(wants_content=0.9), 1.0))
        real, full_ai_offer_turn.load_offer_vault = full_ai_offer_turn.load_offer_vault, boom
        try:
            system = _details_system(pair, "whats in it?", 2)
        finally:
            full_ai_offer_turn.load_offer_vault = real
    assert wr.OFFER_GOAL in system and "price it went out at: $10" in system, system


def case_c_same_as_first_offer():
    pair = "od-same"
    with _sell_draft(), _vault(PRICED):
        for n in (1, 2):
            sold, _, _ = _turn(_body(pair, "send me pics", n=n), "ok:mm this one babe", (_hot(wants_content=0.9), 1.0))
            assert sold["offer"]["ref"] == (101, 202)[n - 1], sold
        _again(pair, 3)
        assert [sorted(full_ai_test._media(r, "locked")) for r in full_ai_test._offers(_rows(pair))] == [
            [101], [202], [202]]
        system = _details_system(pair, "is it the same as the first one?", 4)
        first = _rows(pair)[0].created_at
        assert f"same pieces as the 1st offer, sent {first:%a %b} {first.day}: no" in system, system
        assert "price it went out at: $50" in system and "$10" not in system, system
        system = _details_system(pair, "wait was the $10 one a pic?", 5)
        assert "price it went out at: $10" in system and "same pieces" not in system, system


def case_c_catalogue_price_changed_uses_quoted():
    pair = "od-catalogue"
    with _sell_draft(), _vault(PRICED):
        _turn(_body(pair, "send me pics"), "ok:mm this one babe", (_hot(wants_content=0.9), 1.0))

        async def reprice():
            async with get_session() as s:
                await s.execute(update(VaultItem).where(VaultItem.account_id == A, VaultItem.media_id == 101)
                                .values(of_folder_ids="[7]"))
                await s.commit()
            await vault_folder_prices.put(A, "of:7", 9000)
        _db(reprice)
        try:
            system = _details_system(pair, "how much was it again?", 2)
        finally:
            _db(lambda: vault_folder_prices.put(A, "of:7", None))
    assert "price it went out at: $10" in system and "$90" not in system, system


def case_c_no_offer_asks_which_one():
    pair = "od-none"
    with _sell_draft(), _vault(PRICED):
        system = _details_system(pair, "is that one a video?", 1)
    assert wr.OFFER_GOAL in system and wr.OFFER_NONE in system, system
    assert "price it went out at" not in system and "locked (paid)" not in system, system


def _unit_facts(of, mode="test", **cfg):
    def line(direction, text, mid):
        return SimpleNamespace(direction=direction, body=text, created_at=None, message_id=mid,
                               automation_kind=None, media_count=0, raw_json=None, price_cents=None,
                               is_paid=False, purchased_at=None)
    return SimpleNamespace(
        account_id="acct_od", anchor_key="test:od:1", mode=mode, config={**DEFAULTS, **cfg}, fan_info={},
        next_question=None, spent=[SimpleNamespace(kind="ppv_message", amount_cents=2500, occurred_at=None)],
        tips=[], offer_piece=None, offer_facts=of, dared=False, dare_due=True,
        cut_rows=[line("out", "hii", 1), line("in", "is it a video?", 2)])


CLIP = OfferFacts(locked_kinds={"video": 1}, locked=1, preview_kinds={"photo": 1}, previews=1, seconds=(83,),
                  descriptions=("her in the shower",), quoted_cents=2500, sent_at=datetime(2026, 11, 14, 10),
                  bought=False, same_as_first=(datetime(2026, 11, 13, 9), True), missing=frozenset())


def case_c_messages_for_branch_unit():
    facts = _unit_facts(CLIP, lead_in=True, gifs=True)
    system, user = (m["content"] for m in wr.messages_for("chat", "offer_details", 1, facts, None,
                                                          gif_ok=False, broke=True))
    assert wr.GOAL_HEAD + wr.OFFER_GOAL in system and wr.BROKE_JOKE in system, system
    assert ("THE OFFER HE MEANS (the only facts you may state about it):\n"
            "- what it is: 1 vid\n"
            "- 1 locked (paid)\n"
            "- 1 free preview (1 pic), not paid\n"
            "- length: 1:23\n"
            "- what it shows: her in the shower\n"
            "- price it went out at: $25\n"
            "- same pieces as the 1st offer, sent Fri Nov 13: yes") in system, system
    for banned in (wr.NO_SELL_OFFERS, wr.ASK_HEAD, wr.LEAD_HEAD, *wr.LEAD_EXAMPLES.values(), wr.DARE_NEXT,
                   wr.STICKER_EXCEPTION, wr.CONTRACT_OFFER):
        assert banned not in system, (banned, system)
    assert "he's spent" not in user, user
    for quoted, want in ((None, "price it went out at: no price named yet"), (0, "price it went out at: free")):
        of = replace(CLIP, quoted_cents=quoted, descriptions=(), same_as_first=None)
        system = wr.messages_for("chat", "offer_details", 1, _unit_facts(of), None, gif_ok=False)[0]["content"]
        assert want in system and "what it shows: not on record" in system and "same pieces" not in system, system
    system = wr.messages_for("chat", "offer_details", 1, _unit_facts(None), None, gif_ok=False)[0]["content"]
    assert ("THE OFFER HE MEANS (the only facts you may state about it):\n"
            "- none: nothing he said points to one offer, so you don't know which one he means.") in system, system
    plain = _unit_facts(CLIP, lead_in=True)
    system, user = (m["content"] for m in wr.messages_for("chat", "otherwise", 1, plain, None))
    assert wr.DARE_NEXT in system and wr.OFFER_GOAL not in system and "THE OFFER HE MEANS" not in system, system
    assert "he's spent" in user, user
    new = (Path(__file__).resolve().parents[2] / "docs" / "prompts" / "new" / "current-repo.md").read_text("utf-8")
    goal, block = (new[new.index(f"### {i}"):][:new[new.index(f"### {i}"):].index("\n#", 1)]
                   for i in ("NEW-166", "NEW-167"))
    assert wr.OFFER_GOAL.rstrip() in goal, goal
    for c in (wr.OFFER_HEAD, wr.OFFER_NONE, wr.OFFER_TYPE, wr.OFFER_LOCKED, wr.OFFER_PREVIEWS, wr.OFFER_LENGTHS,
              wr.OFFER_SHOWS, wr.OFFER_PRICE, wr.OFFER_UNPRICED, wr.OFFER_FREE, wr.OFFER_UNKNOWN, wr.OFFER_SAME):
        assert c in block, c


def case_c_tease_question_holds_tease():
    pair = "od-tease"
    with _sell_draft(), _vault(PRICED):
        tease, _, _ = _turn(_body(pair, "how much?"), "ok:mm its a cute one babe, u wanna see it",
                            (_hot(price=0.9), 1.0))
        assert tease["route"] == "tease" and tease["offer"]["ref"] == 101, tease
        got, fj, _ = _turn(_body(pair, "whats in it?", n=2), "ok:its a pic of me in jeans babe",
                           (_hot(**{Q: 0.95}), 2.0))
        assert Q in fj.calls[0]["questions"], sorted(fj.calls[0]["questions"])
        first, row = _rows(pair)
        assert (got["route"], row.route_row) == ("chat", "offer_details"), (got["route"], row.route_row)
        assert got["offer"] is None and got["parts"], got
        _no_offer(row)
        jev = json.loads(row.jev_json)
        assert jev["answers"][Q] == 0.95 and Q in jev["fired"], jev
        assert _reply(row)["held_tease"] == first.id, _reply(row)
        assert full_ai_test.pending_tease_of(_rows(pair), datetime.utcnow()).id == first.id
        ok, _, _ = _turn(_body(pair, "ok", n=3), "ok:here u go babe", (_hot(), 3.0))
    sold = _rows(pair)[2]
    assert (ok["route"], sold.route_row) == ("sell_now", "sell"), (ok["route"], sold.route_row)
    assert ok["offer"]["kind"] == "offer" and ok["offer"]["ref"] == 101, ok["offer"]
    pair = "od-nothing"
    with _sell_draft(), _vault(PRICED):
        got, _, _ = _turn(_body(pair, "is it a video?"), "ok:which one babe", (_hot(**{Q: 0.95}), 1.0))
    (row,) = _rows(pair)
    assert (got["route"], row.route_row) == ("chat", "offer_details"), (got["route"], row.route_row)
    assert got["offer"] is None and "held_tease" not in _reply(row), got


def case_b_reply_to_n_api():
    pair = "od-reply-mark"
    with _sell_draft(), _vault(PRICED):
        _turn(_body(pair, "how much?"), "ok:mm its a cute one babe, u wanna see it", (_hot(price=0.9), 1.0))
        fw = FakeWriterHTTP({NANO: "ok:x", OPENROUTER: "ok:x"})
        with _guarded(), _picks(), fw.on(), _fake_jev(FakeJev((_hot(), 2.0))):
            for bad in (2, 3, 0, -1):
                r = OWNER_A.post(TURN, json=_body(pair, "this one?", n=2, reply_to_n=bad))
                assert r.status_code == 422, (bad, r.status_code, r.text)
        assert len(_rows(pair)) == 1
        _turn(_body(pair, "this one?", n=2, reply_to_n=1), "ok:mm yes babe", (_hot(), 2.0))
        _turn(_body(pair, "ok", n=3), "ok:hehe", (_hot(), 3.0))
    first, marked, plain = _rows(pair)
    assert json.loads(marked.reply_json)["reply_to_n"] == 1, marked.reply_json
    assert "reply_to_n" not in json.loads(plain.reply_json) and "reply_to_n" not in json.loads(first.reply_json)
    with _guarded():
        rows = OWNER_A.get("/admin/full-ai/test/session", params={"account_id": A, "pair": pair}).json()["rows"]
    assert [x.get("reply_to_n") for x in rows] == [None, 1, None], rows



LIE = "ok:its 3 vids total babe"


def _texts(got: dict) -> list[str]:
    return [p["text"] for p in got["parts"] if "text" in p]


def _sold(pair: str) -> AiDecision:
    sold, _, _ = _turn(_body(pair, "send me pics"), "ok:mm this one babe", (_hot(wants_content=0.9), 1.0))
    assert sold["offer"]["ref"] == 101, sold
    return _rows(pair)[0]


def _ask(pair: str, writer, n: int = 2, text: str = "how many pics is it?", **kw) -> tuple[dict, AiDecision]:
    got, _, _ = _turn(_body(pair, text, n=n, **kw), writer, (_hot(**{Q: 0.95}), 1.0))
    row = _rows(pair)[-1]
    assert (got["route"], row.route_row) == ("chat", "offer_details"), (got["route"], row.route_row)
    _no_offer(row)
    assert got["offer"] is None and _ppvs(got["parts"]) == [], got
    return got, row


def case_d_two_fails_send_fallback():
    pair = "od-d-fallback"
    with _sell_draft(), _vault(PRICED):
        offer = _sold(pair)
        got, row = _ask(pair, LIE)
    assert _texts(got) == ["1 pic, $10"], got
    rep = _reply(row)
    assert rep["offer_details"] == {
        "row": "offer_details", "offer_row_id": offer.id, "message_id": None,
        "media_ids": {"locked": [101], "previews": []}, "step": "media", "check": "fallback",
        "failed": ["media", "count"], "missing": []}, rep["offer_details"]
    assert [a.get("rewrite", False) for a in rep["attempts"]] == [False, True], rep["attempts"]
    words = set(" ".join(_texts(got)).lower().replace(",", " ").split())
    for k, v in rep["offer_details"].items():
        assert all(k not in p for p in got["parts"]) and k not in words, (k, got["parts"])
        for x in (v if isinstance(v, list) else [v] if isinstance(v, str) else []):
            assert x not in words, (x, got["parts"])


def case_d_fail_then_pass_is_rewrite():
    pair = "od-d-rewrite"
    with _sell_draft(), _vault(PRICED):
        _sold(pair)
        got, row = _ask(pair, [LIE, "ok:just 1 pic babe, $10"])
    assert _texts(got) == ["just 1 pic babe", "$10"], got      # the chain splits her bubbles
    assert (_reply(row)["offer_details"]["check"], _reply(row)["offer_details"]["failed"]) == (
        "rewrite", ["media", "count"]), _reply(row)["offer_details"]


def case_d_every_writer_fails_sends_fallback():
    pair = "od-d-nowriter"
    with _sell_draft(), _vault(PRICED):
        _sold(pair)
        got, row = _ask(pair, "500")
    assert _texts(got) == ["1 pic, $10"] and got["writer"] is None, got
    assert (_reply(row)["offer_details"]["check"], _reply(row)["offer_details"]["failed"]) == (
        "fallback", []), _reply(row)["offer_details"]


@contextlib.contextmanager
def _banned(word: str):
    async def add():
        async with get_session() as s:
            s.add(SensitiveWord(agency_user_id=IDS["agency_a_owner"], word=word, word_key=word))
            await s.commit()

    async def drop():
        async with get_session() as s:
            await s.execute(delete(SensitiveWord).where(SensitiveWord.agency_user_id == IDS["agency_a_owner"]))
            await s.commit()
    _db(add)
    try:
        yield
    finally:
        _db(drop)


def case_d_fallback_banned_is_dropped():
    pair = "od-d-banned"
    with _sell_draft(), _vault(PRICED):
        _sold(pair)
        with _banned("pic"):
            got, row = _ask(pair, LIE, text="how many is it?")
    assert got["parts"] == [] and got["status"] == "failed", got
    assert _reply(row)["offer_details"]["check"] == "dropped", _reply(row)["offer_details"]
    assert _reply(row)["dropped_reason"] == "banned", _reply(row)


def case_d_check_raise_sends_fallback():
    pair = "od-d-raise"

    def boom(text, of):
        raise ValueError("check bug")
    with _sell_draft(), _vault(PRICED):
        _sold(pair)
        real, full_ai_offer_turn.offer_answer_ok = full_ai_offer_turn.offer_answer_ok, boom
        try:
            got, row = _ask(pair, "ok:just 1 pic babe, $10")
        finally:
            full_ai_offer_turn.offer_answer_ok = real
    assert _texts(got) == ["1 pic, $10"], got
    rep = _reply(row)
    assert (rep["offer_details"]["check"], rep["offer_details"]["failed"]) == ("fallback", ["error"]), rep
    assert [a.get("rewrite", False) for a in rep["attempts"]] == [False], rep["attempts"]
    assert rep["dropped_reason"] is None, rep


def case_d_missing_description():
    pair = "od-d-nodesc"
    with _sell_draft(), _vault(PRICED):
        _sold(pair)

        async def undescribe():
            async with get_session() as s:
                item = (await s.execute(select(VaultItem).where(
                    VaultItem.account_id == A, VaultItem.media_id == 101))).scalar_one()
                fields = json.loads(item.ai_fields_json)
                fields.pop("description")
                item.ai_fields_json = json.dumps(fields)
                await s.commit()
        _db(undescribe)
        got, row = _ask(pair, "ok:its 1 pic babe, cant say more than that", text="whats in it?")
    assert _texts(got) == ["its 1 pic babe", "cant say more than that"], got
    od = _reply(row)["offer_details"]
    assert (od["check"], od["missing"]) == ("ok", ["description"]), od


def case_d_missing_media_fallback_no_counts():
    pair = "od-d-nomedia"
    with _sell_draft(), _vault(PRICED):
        offer = _sold(pair)

        async def strip():
            async with get_session() as s:
                await s.execute(update(AiDecision).where(AiDecision.id == offer.id).values(
                    offer_media_json=json.dumps({"locked": [999], "previews": [], "items": []})))
                await s.commit()
        _db(strip)
        got, row = _ask(pair, "ok:its 1 pic babe", text="whats in it?")
    assert _texts(got) == ["$10"], got
    od = _reply(row)["offer_details"]
    assert (od["check"], od["failed"], od["missing"], od["media_ids"]) == (
        "fallback", ["none"], ["description", "media"], {"locked": [999], "previews": []}), od


def case_d_quote_reply_end_to_end():
    pair = "od-d-quote"
    with _sell_draft(), _vault(PRICED):
        first = _sold(pair)
        sold, _, _ = _turn(_body(pair, "send me more pics", n=2), "ok:mm this one babe",
                           (_hot(wants_content=0.9), 2.0))
        assert sold["offer"]["ref"] == 202, sold
        newer = _rows(pair)[1]
        assert full_ai_test.open_offer_of(_rows(pair)).id == newer.id
        got, row = _ask(pair, "ok:yes that one babe", n=3, text="this one?", reply_to_n=1)
        plain, _, _ = _turn(_body(pair, "lol", n=4), LIE, (_hot(), 1.0))
    od = _reply(row)["offer_details"]
    assert (od["offer_row_id"], od["step"], od["check"]) == (first.id, "quote_reply", "ok"), od
    assert _rows(pair)[-1].route_row != "offer_details" and "offer_details" not in _reply(_rows(pair)[-1])
    assert _texts(plain) == ["its 3 vids total babe"], plain
    assert all("offer_details" not in _reply(r) for r in _rows(pair)[:2])


if __name__ == "__main__":
    _harness.run()
