#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import automation_executor as ax  # noqa: E402 — shared _make_client seam
import automations.send_mass_message as a10  # noqa: E402,F401 — registers the automation
from automation_executor import enqueue_job, run_once  # noqa: E402
from automations._wordfilter import (  # noqa: E402
    banned_hit_summary, filter_banned, load_banned_words,
    scan_outbound,
)
from db.engine import get_session  # noqa: E402
from db.models import Account, SensitiveWord, User, UserAccount  # noqa: E402



def case_mask_is_case_insensitive():
    for src in ("fuck you", "FUCK you", "FuCk you", "Fuck YOU"):
        r = scan_outbound(src, ["fuck"], "mask")
        assert r["clean_text"].lower().startswith("f***"), (src, r)
        assert [h.lower() for h in r["hits"]] == ["fuck"], (src, r)
    r = scan_outbound("fuck", ["FUCK"], "mask")
    assert r["clean_text"] == "f***" and r["hits"] == ["fuck"], r


def case_block_leaves_text_but_flags_hits():
    r = scan_outbound("send me your venmo now", ["venmo"], "block")
    assert r["clean_text"] == "send me your venmo now", r
    assert [h.lower() for h in r["hits"]] == ["venmo"], r


def case_word_boundary_no_substring_false_positive():
    for clean in ("what a great class", "you shall pass", "i will assess it",
                  "the embassy is closed", "molasses"):
        r = scan_outbound(clean, ["ass"], "mask")
        assert r["hits"] == [] and r["clean_text"] == clean, (clean, r)
    for hit in ("you ass", "ass!", "(ass)", "ass-hat", "an ass again"):
        r = scan_outbound(hit, ["ass"], "mask")
        assert r["hits"], (hit, r)
        assert "a**" in r["clean_text"], (hit, r)


def case_clean_text_passes_untouched():
    src = "hey babe, how was your day? 😘"
    r = scan_outbound(src, ["fuck", "venmo", "child"], "mask")
    assert r["clean_text"] == src and r["hits"] == [], r
    rb = scan_outbound(src, ["fuck", "venmo", "child"], "block")
    assert rb["clean_text"] == src and rb["hits"] == [], rb


def case_empty_list_is_a_noop():
    for words in ([], (), None, ["", "   ", "\t"]):
        r = scan_outbound("literally anything venmo fuck", words, "mask")
        assert r["hits"] == [], (words, r)
        assert r["clean_text"] == "literally anything venmo fuck", (words, r)


def case_never_raises_on_weird_input():
    for text in (None, "", 12345, 3.14, ["a", "list"], {"a": 1}, object()):
        r = scan_outbound(text, ["fuck"], "mask")
        assert isinstance(r["clean_text"], str) and isinstance(r["hits"], list), (text, r)
    for words in (None, "fuck", 5, [None, 1, "venmo"], object()):
        r = scan_outbound("send venmo", words, "block")
        assert isinstance(r["clean_text"], str) and isinstance(r["hits"], list), (words, r)
    r = scan_outbound("venmo", ["venmo"], "wobble")
    assert r["clean_text"] == "venmo" and r["hits"] == ["venmo"], r
    assert scan_outbound(None, ["fuck"], "block") == {"clean_text": "", "hits": []}


def case_mask_format_and_multiword_and_dedupe():
    assert scan_outbound("fuck", ["fuck"], "mask")["clean_text"] == "f***"
    assert scan_outbound("x marks", ["x"], "mask")["clean_text"] == "x* marks"
    r = scan_outbound("no child porn here", ["porn", "child porn"], "mask")
    assert "child porn" not in r["clean_text"], r
    assert any(h.lower() == "child porn" for h in r["hits"]), r
    r = scan_outbound("venmo VENMO", ["venmo", "Venmo", "VENMO"], "mask")
    assert r["clean_text"] == "v**** V****" and len(r["hits"]) == 2, r



def case_filter_banned_blocks_the_whole_turn():
# a hit in any bubble blocks all: sending bubble 1 alone would ship half a conversation
    parts, hits = filter_banned(["hey babe", "wanna venmo me?"], ["venmo"], "block")
    assert parts is None, f"a dirty bubble must block the turn, got {parts!r}"
    assert banned_hit_summary(hits) == ["venmo"], hits


def case_filter_banned_masks_every_bubble_and_keeps_order():
    parts, hits = filter_banned(["venmo me", "clean", "or VENMO"], ["venmo"], "mask")
    assert parts == ["v**** me", "clean", "or V****"], parts
    assert len(hits) == 2 and banned_hit_summary(hits) == ["venmo"], hits


def case_filter_banned_empty_list_is_identity():
    src = ["hey", "", "venmo"]
    parts, hits = filter_banned(src, [], "block")
    assert parts == src and hits == [], (parts, hits)
    parts, hits = filter_banned(src, None, "mask")
    assert parts == src and hits == [], (parts, hits)


def case_filter_banned_clean_turn_passes_through():
    parts, hits = filter_banned(["hey babe", "miss you"], ["venmo"], "block")
    assert parts == ["hey babe", "miss you"] and hits == [], (parts, hits)


def case_filter_banned_unknown_mode_fails_safe_to_block():
    for mode in ("", "MASKK", "nonsense", None):
        parts, hits = filter_banned(["venmo me"], ["venmo"], mode)
        assert parts is None, f"mode={mode!r} must fail safe to block, got {parts!r}"
        assert hits, mode
    parts, _ = filter_banned(["venmo me"], ["venmo"], "  MASK ")
    assert parts == ["v**** me"], parts


def case_filter_banned_never_raises():
    for parts in (None, [], [None], [123], ["ok"]):
        out, hits = filter_banned(parts, ["venmo"], "mask")
        assert isinstance(out, list) and isinstance(hits, list), (parts, out)



async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _sensitive(aid: str, agency: str, *words: str) -> None:
    async with get_session() as s:
        if await s.get(User, agency) is None:
            s.add(User(id=agency, username=agency, password="x"))
            await s.flush()
        if await s.get(UserAccount, (agency, aid)) is None:
            s.add(UserAccount(user_id=agency, account_id=aid))
        for w in words:
            s.add(SensitiveWord(agency_user_id=agency, word=w, word_key=w.lower()))


async def case_loader_absent_is_noop():
    aid = "acc_wf_absent"
    await _seed_account(aid)
    words, mode = await load_banned_words(aid)
    assert words == [] and mode == "block", (words, mode)
    words, mode = await load_banned_words("acc_wf_nope")
    assert words == [] and mode == "block", (words, mode)


async def case_loader_reads_every_agencys_sensitive_words():
    aid = "acc_wf_sensitive"
    await _seed_account(aid)
    await _sensitive(aid, "u_wf_agency_a", "Venmo", "child porn")
    await _sensitive(aid, "u_wf_agency_b", "venmo", "cashapp")
    words, mode = await load_banned_words(aid)
    assert mode == "block", mode
    assert sorted(w.lower() for w in words) == ["cashapp", "child porn", "venmo"], words



class FakeClient:

    def __init__(self, user_id: str = "999"):
        self.user_id = user_id
        self.sent: list[dict] = []

    def send_mass_message(self, text, **kw) -> dict:
        self.sent.append({"text": text, **kw})
        return {"id": 880001, "createdAt": "2026-06-04T10:00:00+00:00"}


def _use_fake(fake: FakeClient) -> None:
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]


async def case_mass_block_aborts_send():
    aid = "acc_wf_mass_block"
    await _seed_account(aid)
    await _sensitive(aid, "u_wf_mass_block", "venmo")
    fake = FakeClient()
    _use_fake(fake)

    await enqueue_job(aid, "send_mass_message", payload={
        "text": "pay me on venmo babe", "included_users": [3001], "price": 0})
# a hit aborts the whole broadcast before the OF call: nothing minted
    res = await run_once(aid, "send_mass_message")

    assert res["status"] == "skipped" and res["reason"] == "banned_words", res
    assert res["hits"] == ["venmo"], res
    assert fake.sent == [], f"OF must NOT be called on a blocked broadcast: {fake.sent}"


async def case_mass_clean_text_untouched():
    aid = "acc_wf_mass_clean"
    await _seed_account(aid)
    await _sensitive(aid, "u_wf_mass_clean", "venmo")
    fake = FakeClient()
    _use_fake(fake)

    await enqueue_job(aid, "send_mass_message", payload={
        "text": "hey babe how are you 😘", "included_users": [3003], "price": 0})
    res = await run_once(aid, "send_mass_message")

    assert res["status"] == "ok", res
    assert fake.sent and fake.sent[0]["text"] == "hey babe how are you 😘", fake.sent


if __name__ == "__main__":
    _harness.run(
        case_mask_is_case_insensitive,
        case_block_leaves_text_but_flags_hits,
        case_word_boundary_no_substring_false_positive,
        case_clean_text_passes_untouched,
        case_empty_list_is_a_noop,
        case_never_raises_on_weird_input,
        case_mask_format_and_multiword_and_dedupe,
        case_filter_banned_blocks_the_whole_turn,
        case_filter_banned_masks_every_bubble_and_keeps_order,
        case_filter_banned_empty_list_is_identity,
        case_filter_banned_clean_turn_passes_through,
        case_filter_banned_unknown_mode_fails_safe_to_block,
        case_filter_banned_never_raises,
        case_loader_absent_is_noop,
        case_loader_reads_every_agencys_sensitive_words,
        case_mass_block_aborts_send,
        case_mass_clean_text_untouched,
    )
