#!/usr/bin/env python3
"""test_full_ai_test_chat — Full AI Chat's Test chat, through the Relay API (phase 03a, ticket 32).

`POST /admin/full-ai/test/turn` and `GET /admin/full-ai/test/session` over `_harness.make_client()`
with real owner session cookies (the two-Agency fixture). Fakes sit only at the two network edges:
Jev at `_router_jev._client` (`FakeJev`), the Writers at `llm_client.httpx.AsyncClient`
(`FakeWriterHTTP`); no `llm_client.chat` patch (one exception: `case_chain_turn_deadline` also
fakes the Turn's clock, see Writer chain below). Every Turn runs inside `_guarded`: full-row
snapshots of messages, transactions, vault_sends, fan_lease and fans (each seeded with a row)
equal before and after, no `automation_runs` row, every send path patched to raise and never hit.

  case_chat_turn_via_api                 the response shape, a `sent` row from euryale-v2.3 matching it
  case_leak_is_deflected_and_stored      "let's meet in person tonight": the deflection, leak recorded
  case_parts_equal_the_shared_chain      girl / formal parts = a direct finalize_draft + shape_parts
                                         (+ typo throttle) with the matching context, and differ;
                                         the account-wide style switches (set against each side) unread
  case_typos_off_skips_only_the_typo_pass  `style.typos` off on the draft: its parts = the girl chain
                                         without the typo throttle, the checkpoint's keep it, no typo state
  case_echo_is_failed                    a reply shape_parts drops as echo: failed, dropped_reason echo
  case_typo_state_is_the_sessions        no Fan read or written; the state lands in reply_json
  case_wait_s_is_drawn_not_slept         in "0-2m", same per session:n, the handler under 1 s
  case_double_post_and_skipped_n_409     one row then 409; n = count + 2: 409, no row
  case_concurrent_duplicate_turn_one_run the same n again while the first runs: waits, then 409 once
                                         the row exists; one run_turn / Jev / Writer call, one row
  case_session_reads_both_sides_in_order both sides' rows by id; the next Turn reads the exchange
  case_cross_account                     A's pair reads empty under B; 403 for a non-owner, no row
  case_no_send_test_import_scan          the test modules name no send path (the settle and its route too)

Other tickets' Test chat cases: test_full_ai_routes_chat.py (34), test_full_ai_info_chat.py (35),
test_full_ai_config_chat.py (37); shared setup in _full_ai_chat_helpers.py.

Run: ./venv/bin/python service/tests/test_full_ai_test_chat.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

from _full_ai_chat_helpers import (
    A, B, DEEPSEEK, KEYS, NANO, OPENROUTER, OWNER_A, OWNER_B, REPLY_KEYS, TURN, ZAI, _agency_keys,
    _body, _chain_post, _Clock, _db, _direct, _guarded, _post, _reply, _rows, _SlowJev, _store_config,
)
import ast
import asyncio
import contextlib
import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import text

from _full_ai_fixtures import QUIET, QUIET_TEST, FakeJev, FakeWriterHTTP, _fake_jev
from automations import _info_jev, _router_jev, full_ai_chat, full_ai_sell, full_ai_test, full_ai_turn, full_ai_writers
from automations._outbound import finalize_draft
from automations._style_flags import STYLE_AUTOMATIONS, nonnative_flag_key, spacing_flag_key, typo_flag_key
from automations.full_ai_config import DEFAULTS, turn_bound_s
from automations.full_ai_decide import arm_of
from db.engine import get_session
from db.models import AccountAiConfig, Fan, Message

# ── The Turn ──────────────────────────────────────────────────────────

def case_chat_turn_via_api():
    pair = "p-chat"
    r, fw, fj, _ = _post(OWNER_A, _body(pair), "ok:omg hii my day was good, wbu")
    assert r.status_code == 200, r.text
    got = r.json()
    assert set(got) == KEYS, sorted(got)
    assert got["status"] == "sent" and got["writer"] == "euryale-v2.3", got
    assert got["route"] == "chat" and got["route_row"] == "otherwise" and got["dropped"] == [], got
    assert got["parts"] and all(p["text"] for p in got["parts"]), got["parts"]
    assert [a["writer"] for a in got["attempts"]] == ["euryale-v2.3"] and got["attempts"][0]["outcome"] == "ok"
    assert got["fan_info"] == {}, got["fan_info"]
    (row,) = _rows(A, pair)
    fid = full_ai_test.test_fan_id(pair)
    assert fid < 0, fid
    assert (row.id, row.mode, row.trigger_kind, row.trigger_key, row.fan_id) == (
        got["row_id"], "test", "test", f"test:{pair}-L:1", fid)
    assert (row.route, row.heat, row.route_row, row.status, row.writer_model) == (
        got["route"], got["heat"], got["route_row"], "sent", "euryale-v2.3")
    assert (row.arm, row.salt_ver) == (arm_of(A, fid), 1), (row.arm, row.salt_ver)
    reply = _reply(row)
    assert set(reply) == REPLY_KEYS, sorted(reply)
    assert reply["parts"] == got["parts"] and reply["attempts"] == got["attempts"], reply
    assert (reply["side"], reply["config_rev"], reply["wait_s"]) == ("checkpoint", 0, got["wait_s"]), reply
    assert reply["leak"] == [] and reply["dropped_reason"] is None and reply["turn_ms"] >= 0, reply
    jev = json.loads(row.jev_json)
    assert jev["state"]["fan_new_messages"] == ["hey you, how was your day"], jev["state"]
    assert jev["answers"] == QUIET_TEST and row.jev_error is None, jev
    # One Writer request, to NanoGPT with the spec's wire id, one attempt at the side's bound;
    # its prompt is the old chat skeleton.
    (req,) = fw.requests
    assert (req["host"], req["model"]) == (NANO, "Sao10K/L3.3-70B-Euryale-v2.3"), req
    assert req["timeout"] == DEFAULTS["writer_timeout_s"], req["timeout"]
    system, user = req["body"]["messages"]
    assert full_ai_writers.ROLE in system["content"] and full_ai_writers.CONTRACT in system["content"]
    assert user["content"].endswith(full_ai_writers.REPLY_NOW) and "FAN: hey you" in user["content"]
    assert len(fj.calls) == 1, fj.calls


def case_leak_is_deflected_and_stored():
    pair = "p-leak"
    raw = "let's meet in person tonight"
    r, *_ = _post(OWNER_A, _body(pair), f"ok:{raw}")
    got = r.json()
    assert r.status_code == 200 and got["status"] == "sent", r.text
    want, leak = _db(lambda: finalize_draft(raw, account_id=A, fan_id=full_ai_test.test_fan_id(pair),
                                            purpose="full_ai_writer"))
    assert leak and want != raw, (want, leak)
    joined = " ".join(p["text"] for p in got["parts"]).lower()
    assert "meet" not in joined, got["parts"]
    (row,) = _rows(A, pair)
    reply = _reply(row)
    assert reply["parts"] == got["parts"] and reply["leak"] == leak, reply


def _store_style(aid: str, on: bool | None) -> None:
    """Every per-automation style, typo, non-native and spacing switch and painful texting set to
    `on` (None clears the blob); strip-emoji stays off."""
    keys = [k for a in STYLE_AUTOMATIONS for k in (a, typo_flag_key(a), nonnative_flag_key(a),
                                                     spacing_flag_key(a))] + ["painful_texting"]

    async def go():
        async with get_session() as s:
            (await s.get(AccountAiConfig, aid)).style_config_json = (
                None if on is None else json.dumps(dict.fromkeys(keys, on)))
    _db(go)


def case_parts_equal_the_shared_chain():
    pair, his = "p-shape", "so what are you up to"
    raw = "omg hii. i was literally just thinking about u. what are u up to tonight? tell me everything"
    _store_config(A, {"draft": {**DEFAULTS, "text_style": "formal"}, "rev": 3})
    try:
        # The account-wide style switches set against each side: only strip-emoji is read.
        _store_style(A, False)
        girl, *_ = _post(OWNER_A, _body(pair, text=his), f"ok:{raw}")
        _store_style(A, True)
        formal, *_ = _post(OWNER_A, _body(pair, text=his, side="draft"), f"ok:{raw}")
    finally:
        _store_config(A, {})
        _store_style(A, None)
    fid = full_ai_test.test_fan_id(pair)
    g, f = girl.json(), formal.json()
    assert g["parts"] == _direct(raw, fid, his, girl=True), g["parts"]
    assert f["parts"] == _direct(raw, fid, his, girl=False), f["parts"]
    assert g["parts"] != f["parts"], (g["parts"], f["parts"])
    rows = _rows(A, pair)
    assert [(_reply(x)["side"], _reply(x)["config_rev"]) for x in rows] == [("checkpoint", 3), ("draft", 3)]


def case_typos_off_skips_only_the_typo_pass():
    pair, his = "p-typos-off", "so what are you up to"
    raw = "omg hii. i was literally just thinking about u. what are u up to tonight? tell me everything"
    _store_config(A, {"draft": {**DEFAULTS, "style": {**DEFAULTS["style"], "typos": False}}, "rev": 5})
    try:
        ck, *_ = _post(OWNER_A, _body(pair, text=his), f"ok:{raw}")
        dr, *_ = _post(OWNER_A, _body(pair, text=his, side="draft"), f"ok:{raw}")
    finally:
        _store_config(A, {})
    fid = full_ai_test.test_fan_id(pair)
    c, d = ck.json(), dr.json()
    assert c["parts"] == _direct(raw, fid, his, girl=True), c["parts"]
    assert d["parts"] == _direct(raw, fid, his, girl=True, typos=False), d["parts"]
    assert c["parts"] != d["parts"], (c["parts"], d["parts"])      # this raw draws a typo on the girl chain
    ck_row, dr_row = _rows(A, pair)
    assert _reply(dr_row)["typo_state"] == {} and _reply(ck_row)["typo_state"] != {}, (
        _reply(ck_row)["typo_state"], _reply(dr_row)["typo_state"])


def case_echo_is_failed():
    pair, his = "p-echo", "what are you doing right now babe"
    r, fw, *_ = _post(OWNER_A, _body(pair, text=his), f"ok:{his}")
    got = r.json()
    assert r.status_code == 200, r.text
    assert (got["status"], got["parts"], got["writer"], got["wait_s"]) == ("failed", [], None, None), got
    assert len(fw.requests) == 1, fw.requests
    (row,) = _rows(A, pair)
    assert row.status == "failed" and row.writer_model is None, (row.status, row.writer_model)
    assert _reply(row)["dropped_reason"] == "echo", _reply(row)


def case_typo_state_is_the_sessions():
    """A `fans` row planted at the test Fan's id, with a `*fix` state the throttle would carry on
    (since 41): the Turn's state starts from the session's own (empty), and `_guarded`'s `fans`
    snapshot shows nothing was written."""
    pair = "p-typo"
    fid = full_ai_test.test_fan_id(pair)
    planted = {"at": "2001-01-01T00:00:00", "since": 41}
    _db(lambda: _plant_fan(A, fid, {"_typo_fix": planted}))
    r, *_ = _post(OWNER_A, _body(pair), "ok:haha ok i see u. tell me more about ur weekend plans")
    assert r.status_code == 200 and r.json()["status"] == "sent", r.text
    (row,) = _rows(A, pair)
    state = _reply(row)["typo_state"]
    assert set(state) == {"at", "since"} and state["since"] in (0, 1), state
    assert state["at"] != planted["at"], state
    assert json.loads(_db(lambda: _fan(A, fid)).custom_fields) == {"_typo_fix": planted}


async def _plant_fan(aid: str, fid: int, custom: dict) -> None:
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=fid, custom_fields=json.dumps(custom)))


async def _fan(aid: str, fid: int):
    async with get_session() as s:
        return await s.get(Fan, (aid, fid))


def case_wait_s_is_drawn_not_slept():
    """In "0-2m", the same for the same `session:n` (the seed holds no account: the same pair
    under Creator B draws the same wait), and the handler returns at once."""
    pair = "p-wait"
    r, _, _, wall = _post(OWNER_A, _body(pair), "ok:mm hey")
    again, *_ = _post(OWNER_B, _body(pair, aid=B), "ok:mm hey")
    got = r.json()
    assert r.status_code == 200 and got["status"] == "sent", r.text
    assert again.status_code == 200 and again.json()["status"] == "sent", again.text
    assert 0 <= got["wait_s"] <= 120, got["wait_s"]
    assert again.json()["wait_s"] == got["wait_s"], (again.json()["wait_s"], got["wait_s"])
    assert wall < 1.0, wall


def case_double_post_and_skipped_n_409():
    pair = "p-twice"
    body = _body(pair)
    first, fw1, *_ = _post(OWNER_A, body, "ok:hey u")
    again, fw2, *_ = _post(OWNER_A, body, "ok:hey u")
    assert first.status_code == 200, first.text
    assert again.status_code == 409 and again.json() == {"row_id": None}, again.text
    skipped, fw3, *_ = _post(OWNER_A, _body(pair, n=3), "ok:hey u")
    assert skipped.status_code == 409 and skipped.json() == {"row_id": None}, skipped.text
    assert [len(f.requests) for f in (fw1, fw2, fw3)] == [1, 0, 0]
    assert [x.id for x in _rows(A, pair)] == [first.json()["row_id"]]


def case_concurrent_duplicate_turn_one_run():
    """Turn n posted again while the first is still running (double click, client retry): the
    second makes no paid call, waits for the first, then is 409 with the row stored (so the client's
    session reload recovers the reply); one `run_turn`, one Jev call, one Writer call."""
    pair = "p-twice-at-once"
    body = _body(pair)
    real, calls, out = full_ai_turn.run_turn, [], {}
    entered, release = threading.Event(), threading.Event()

    async def held(facts):
        calls.append(facts.anchor_key)
        if len(calls) == 1:                 # the first Turn waits until the duplicate is answered
            entered.set()
            for _ in range(500):
                if release.is_set():
                    break
                await asyncio.sleep(0.01)
        return await real(facts)

    fw, fj = FakeWriterHTTP({NANO: "ok:hey u"}), FakeJev((QUIET, 1.0), (QUIET, 1.0))
    full_ai_turn.run_turn = held
    try:
        with _guarded(), fw.on(), _fake_jev(fj):
            t = threading.Thread(target=lambda: out.setdefault("first", OWNER_A.post(TURN, json=body)))
            t.start()
            assert entered.wait(5), "the first Turn never reached run_turn"
            threading.Timer(0.5, release.set).start()   # the duplicate is in flight before release
            second = OWNER_A.post(TURN, json=body)
            rows_at_409 = [x.id for x in _rows(A, pair)]
            t.join(10)
    finally:
        release.set()
        full_ai_turn.run_turn = real
    first = out["first"]
    assert len(calls) == 1, ("the duplicate ran the Turn too", calls)
    assert (len(fj.calls), len(fw.requests)) == (1, 1), (len(fj.calls), len(fw.requests))
    assert first.status_code == 200 and first.json()["status"] == "sent", first.text
    assert second.status_code == 409 and second.json() == {"row_id": None}, second.text
    assert rows_at_409 == [first.json()["row_id"]], rows_at_409   # the 409 came after the row
    assert [x.id for x in _rows(A, pair)] == [first.json()["row_id"]]


def case_session_reads_both_sides_in_order():
    pair = "p-both"
    a1, *_ = _post(OWNER_A, _body(pair, text="hey there"), "ok:heyy")
    b1, *_ = _post(OWNER_A, _body(pair, text="hello", side="draft"), "ok:hii")
    a2, _, fj, _ = _post(OWNER_A, _body(pair, 2, "how are you"), "ok:good wbu")
    assert [x.status_code for x in (a1, b1, a2)] == [200, 200, 200]
    # The checkpoint's second Turn reads its own first exchange, not the draft side's.
    thread = fj.calls[0]["state"]["thread"]
    assert [(x["from"], x["text"]) for x in thread] == [("fan", "hey there"), ("her", "heyy")], thread
    got = OWNER_A.get(f"/admin/full-ai/test/session?account_id={A}&pair={pair}")
    assert got.status_code == 200, got.text
    rows = got.json()["rows"]
    assert [(x["row_id"], x["side"], x["n"], x["text"]) for x in rows] == [
        (a1.json()["row_id"], "checkpoint", 1, "hey there"), (b1.json()["row_id"], "draft", 1, "hello"),
        (a2.json()["row_id"], "checkpoint", 2, "how are you")], rows
    assert rows[2]["parts"] == a2.json()["parts"] and rows[2]["status"] == "sent", rows[2]


def case_cross_account():
    pair = "p-cross"
    r, *_ = _post(OWNER_A, _body(pair), "ok:hey")
    assert r.status_code == 200, r.text
    under_b = OWNER_B.get(f"/admin/full-ai/test/session?account_id={B}&pair={pair}")
    assert under_b.status_code == 200 and under_b.json() == {"rows": []}, under_b.text
    denied = OWNER_A.get(f"/admin/full-ai/test/session?account_id={B}&pair={pair}")
    assert denied.status_code == 403, denied.text
    fw = FakeWriterHTTP({NANO: "ok:hey"})
    with _guarded(), fw.on(), _fake_jev(FakeJev((QUIET, 1.0))):
        turn = OWNER_A.post(TURN, json=_body(pair, aid=B))
    assert turn.status_code == 403 and fw.requests == [], turn.text
    assert _rows(B, pair) == []


# ── No-send ───────────────────────────────────────────────────────────

_TEST_MODULES = (full_ai_test, full_ai_writers, full_ai_turn, _info_jev, full_ai_sell, _router_jev, full_ai_chat)
_BANNED_MODULES = {"of_client", "automation_executor", "fan_lease", "dm_rate", "of_sends", "of_write"}
_BANNED_NAMES = {"_make_client", "send_message", "acquire_fan_lease", "start_fan_cooldown"}


def _send_paths(source: str) -> list[str]:
    """Every import of a banned module and every banned name in `source` (the walker of
    test_full_ai_shadow.py `_send_paths`, with this set: `_outbound` is allowed, `run_turn`
    must call `finalize_draft`)."""
    found = []
    for n in ast.walk(ast.parse(source)):
        if isinstance(n, ast.Import):
            found += [a.name for a in n.names if a.name in _BANNED_MODULES]
        elif isinstance(n, ast.ImportFrom):
            mod = ".".join(p for p in ("automations" if n.level else "", n.module or "") if p)
            names = {f"{mod}.{a.name}" if mod else a.name for a in n.names}
            found += [m for m in {mod} | names if m in _BANNED_MODULES]
            found += [a.name for a in n.names if a.name in _BANNED_NAMES]
        elif isinstance(n, ast.Name) and n.id in _BANNED_NAMES:
            found.append(n.id)
        elif isinstance(n, ast.Attribute) and n.attr in _BANNED_NAMES:
            found.append(n.attr)
    return found


def case_no_send_test_import_scan():
    for mod in _TEST_MODULES:
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert _send_paths(src) == [], (mod.__name__, _send_paths(src))
    # The settle (03b): its code is in a scanned module, and its route handler names no send path.
    import inspect
    import full_ai_api
    assert inspect.getmodule(full_ai_test.settle) in _TEST_MODULES
    src = inspect.getsource(full_ai_api.full_ai_test_settle)
    assert "full_ai_test.settle(" in src and _send_paths(src) == [], _send_paths(src)
    # The scan sees every banned module and name.
    for m in sorted(_BANNED_MODULES):
        assert _send_paths(f"import {m}\n") == [m], m
    for name in sorted(_BANNED_NAMES):
        assert _send_paths(f"x.{name}()\n") == [name], name
        assert _send_paths(f"{name}()\n") == [name], name
    assert _send_paths("from fan_lease import acquire_fan_lease\n") == ["fan_lease", "acquire_fan_lease"]
    assert _send_paths("from automations._outbound import finalize_draft\n") == []


# ── Sessions across Turns (ticket 36) ─────────────────────────────────
#   case_three_turns_each_side_its_own_thread   the 3rd Turn's Jev state holds the first two
#                                               exchanges; the draft side reads only its own
#                                               (the session read's order: case_session_reads_both_sides_in_order)
#   case_test_thread_equals_the_db_thread       test_thread + build_state = the Shadow DB read
#                                               for the same exchange; real Router thread, no ppv
#   case_typo_fix_throttled_per_session         a seeded `*fix` on Turn 1 blocks Turn 2 on that
#                                               side only; no `fans` row read or written

from types import SimpleNamespace  # noqa: E402


def _thread(fj: FakeJev) -> list[tuple[str, str]]:
    return [(x["from"], x["text"]) for x in fj.calls[0]["state"]["thread"]]


def _her(got: dict) -> list[tuple[str, str]]:
    return [("her", p["text"]) for p in got["parts"]]


def case_three_turns_each_side_its_own_thread():
    pair = "p-three"
    c1, *_ = _post(OWNER_A, _body(pair, 1, "hey there stranger"), "ok:heyy u. whats up")
    d1, *_ = _post(OWNER_A, _body(pair, 1, "hello gorgeous", side="draft"), "ok:omg hi cutie")
    c2, *_ = _post(OWNER_A, _body(pair, 2, "just got home from work"), "ok:aw long day? tell me")
    d2, _, fjd, _ = _post(OWNER_A, _body(pair, 2, "missed you", side="draft"), "ok:missed u more")
    c3, _, fjc, _ = _post(OWNER_A, _body(pair, 3, "yeah super tired"), "ok:poor baby. come rest")
    assert [x.status_code for x in (c1, d1, c2, d2, c3)] == [200] * 5, [x.text for x in (c1, d1, c2, d2, c3)]
    assert all(x.json()["status"] == "sent" for x in (c1, d1, c2, d2, c3))
    # The checkpoint's third Turn: its two earlier exchanges, his new line apart, nothing of the draft's.
    assert _thread(fjc) == ([("fan", "hey there stranger")] + _her(c1.json())
                            + [("fan", "just got home from work")] + _her(c2.json())), _thread(fjc)
    assert fjc.calls[0]["state"]["fan_new_messages"] == ["yeah super tired"], fjc.calls[0]["state"]
    assert _thread(fjd) == [("fan", "hello gorgeous")] + _her(d1.json()), _thread(fjd)


def case_test_thread_equals_the_db_thread():
    """Two test rows (his line, her bubbles; a GIF part is a GIF-only line) and the same exchange as
    stored messages: the Turn after them reads the same Jev state on both paths, built by the
    real Router thread (`_router_jev.thread`, `_ppv`, `_bought`) with no `ppv` note."""
    from automations import _router_jev as router
    from automations import full_ai_chat
    t0 = datetime(2026, 11, 10, 18, 0)
    rows = [SimpleNamespace(created_at=at, jev_json=json.dumps({"state": {"fan_new_messages": his}}),
                            reply_json=json.dumps({"parts": parts}))
            for at, his, parts in (
                (t0 - timedelta(hours=3), ["hey you"], [{"text": "heyy"}, {"text": "how r u"}]),
                (t0 - timedelta(hours=1), ["earlier line", "good, you?"],
                 [{"gif": "g1", "tag": "wave"}, {"text": "same lol"}]))]
    lines = full_ai_test.test_thread(rows)
    assert [(m.direction, m.body) for m in lines] == [
        ("in", "hey you"), ("out", "heyy"), ("out", "how r u"), ("in", "good, you?"), ("out", ""),
        ("out", "same lol")]
    assert router.line_text(lines[4]) == router.GIF_ONLY, lines[4]
    fan = 7_360
    anchor_id = len(lines) + 1

    async def db_state():
        async with get_session() as s:
            for m in lines:
                s.add(Message(account_id=A, fan_id=fan, message_id=m.message_id, direction=m.direction,
                              body=m.body, created_at=m.created_at, raw_json=m.raw_json))
            s.add(Message(account_id=A, fan_id=fan, message_id=anchor_id, direction="in",
                          body="what are you up to", created_at=t0))
        try:
            return await full_ai_chat._read(A, fan, anchor_id)
        finally:
            async with get_session() as s:
                await s.execute(Message.__table__.delete().where(Message.fan_id == fan))
    ((anchor, db_st, db_offer, _photo),) = _db(db_state)
    turn = [full_ai_test._line("in", "what are you up to", t0, anchor_id)]
    st, has_offer = full_ai_chat.build_state(turn, lines, None, None)
    assert (st, has_offer) == (db_st, db_offer), (st, db_st)
    thread = router.thread(lines, t0)
    assert thread == st["thread"] and len(thread) == 6, thread
    assert thread[4]["text"] == router.GIF_ONLY, thread
    assert all("ppv" not in e for e in thread), thread


def case_typo_fix_throttled_per_session():
    """Writer lines whose real seed (`<fid>:<text>`) fires a `*fix` on an empty throttle state:
    X on the checkpoint's Turn 1, Y on its Turn 2 and on the draft side's Turn 1 (same Fan, same
    seed). Turn 1 carries the fix, Turn 2 cannot (one hour not passed), the draft side's Y still
    does. A `fans` row at the test Fan's id with a blocking state is never read (Turn 1 still
    fixes) nor written (`_guarded`)."""
    pair = "p-typo-turns"
    x, y = "literally sounds gorgeous", "actually wonderful tonight"
    fid = full_ai_test.test_fan_id(pair)
    _db(lambda: _plant_fan(A, fid, {"_typo_fix": {"at": datetime.utcnow().isoformat(), "since": 0}}))
    c1, *_ = _post(OWNER_A, _body(pair, 1, "hey there"), f"ok:{x}")
    c2, *_ = _post(OWNER_A, _body(pair, 2, "thanks babe"), f"ok:{y}")
    d1, *_ = _post(OWNER_A, _body(pair, 1, "hey there", side="draft"), f"ok:{y}")
    got = [r.json() for r in (c1, c2, d1)]
    assert all(g["status"] == "sent" for g in got), got

    def fixes(g):
        return [p["text"] for p in g["parts"] if p["text"].startswith("*")]
    assert [fixes(g) for g in got] == [["*literally lol"], [], ["*wonderful"]], got
    s1, s2, sd = (_reply(r)["typo_state"] for r in _rows(A, pair))
    assert s1["since"] == 0 and s1["at"], s1
    assert s2 == {"at": s1["at"], "since": 1}, (s1, s2)
    assert sd["since"] == 0 and sd["at"] and sd["at"] != s1["at"], sd


# ── Writer chain (ticket 33) ──────────────────────────────────────────
# case_chain_falls_on_each_failure   503 / 429 / timeout / empty on NanoGPT: Hermes answers, one
#                                    request per Writer
# case_chain_floor_reject_falls      `framework:` -> floor:framework, then Hermes; floor_on off -> sent
# case_chain_all_fail                four failures: failed, no parts, writer_model NULL, each outcome
# case_chain_key_missing_or_refused  no NanoGPT key -> no_key (no request); 401 / 402 -> http_<status>
# case_chain_provider_cap            NanoGPT capped -> cap, Hermes answers; all capped -> failed
# case_chain_turn_deadline           stages faked slow on a fake clock: Writer timeouts never exceed
#                                    the time left, the Turn ends within turn_bound_s
# The deadline case alone also fakes the Turn's clock (`full_ai_turn.time` / `full_ai_writers.time`,
# a module swap; asyncio's loop clock stays real): the bound is >= 30 s of wall time, which a test
# cannot spend, so the slow fakes advance that clock instead of sleeping.

CHAIN = ("euryale-v2.3", "hermes-4-405b", "glm-5.3-flash", "deepseek-v4-flash")



def _outcomes(attempts: list[dict]) -> list[tuple[str, str]]:
    return [(a["writer"], a["outcome"]) for a in attempts]


def case_chain_falls_on_each_failure():
    for how, outcome in (("503", "http_503"), ("429", "http_429"), ("timeout", "timeout"),
                         ("empty", "empty")):
        pair = f"p-fall-{how}"
        r, fw = _chain_post(_body(pair), {NANO: how})
        got = r.json()
        assert (got["status"], got["writer"]) == ("sent", "hermes-4-405b"), (how, got)
        assert _outcomes(got["attempts"]) == [("euryale-v2.3", outcome), ("hermes-4-405b", "ok")], got
        assert all(a["ms"] >= 0 for a in got["attempts"]), got["attempts"]
        assert got["parts"], got
        # Each Writer saw exactly one request (no internal retry), at the side's bound.
        assert [x["host"] for x in fw.requests] == [NANO, OPENROUTER], (how, fw.requests)
        assert [x["timeout"] for x in fw.requests] == [25.0, 25.0], fw.requests
        (row,) = _rows(A, pair)
        assert (row.status, row.writer_model) == ("sent", "hermes-4-405b"), (row.status, row.writer_model)
        assert _reply(row)["attempts"] == got["attempts"], _reply(row)


def case_chain_floor_reject_falls():
    pair = "p-floor"
    r, fw = _chain_post(_body(pair), {NANO: "ok:framework: 1) tease him 2) ask his name"})
    got = r.json()
    assert (got["status"], got["writer"]) == ("sent", "hermes-4-405b"), got
    assert _outcomes(got["attempts"]) == [("euryale-v2.3", "floor:framework"), ("hermes-4-405b", "ok")]
    (row,) = _rows(A, pair)
    assert _reply(row)["floor_reason"] == "framework", _reply(row)
    # The switch: floor_on off sends the first Writer's reply through the shared chain.
    _store_config(A, {"checkpoint": {**DEFAULTS, "floor_on": False}})
    try:
        r, fw = _chain_post(_body("p-floor-off"), {NANO: "ok:framework: tease him and ask his name"})
    finally:
        _store_config(A, {})
    got = r.json()
    assert (got["status"], got["writer"]) == ("sent", "euryale-v2.3"), got
    assert _outcomes(got["attempts"]) == [("euryale-v2.3", "ok")] and len(fw.requests) == 1, got


def case_chain_all_fail():
    pair = "p-allfail"
    r, fw = _chain_post(_body(pair), {NANO: "503", OPENROUTER: "timeout", ZAI: "429", DEEPSEEK: "empty"})
    got = r.json()
    assert (got["status"], got["parts"], got["writer"], got["wait_s"]) == ("failed", [], None, None), got
    assert _outcomes(got["attempts"]) == list(zip(CHAIN, ("http_503", "timeout", "http_429", "empty")))
    assert [x["host"] for x in fw.requests] == [NANO, OPENROUTER, ZAI, DEEPSEEK], fw.requests
    (row,) = _rows(A, pair)
    assert (row.status, row.writer_model) == ("failed", None), (row.status, row.writer_model)
    assert _reply(row)["parts"] == [] and _reply(row)["attempts"] == got["attempts"], _reply(row)


def case_chain_key_missing_or_refused():
    with _agency_keys({"nanogpt": ""}):
        r, fw = _chain_post(_body("p-nokey"), {})
    got = r.json()
    assert (got["status"], got["writer"]) == ("sent", "hermes-4-405b"), got
    assert _outcomes(got["attempts"]) == [("euryale-v2.3", "no_key"), ("hermes-4-405b", "ok")], got
    assert [x["host"] for x in fw.requests] == [OPENROUTER], fw.requests
    for status in ("401", "402"):                       # an invalid key, a key with no credit
        r, fw = _chain_post(_body(f"p-badkey-{status}"), {NANO: status})
        got = r.json()
        assert got["writer"] == "hermes-4-405b", (status, got)
        assert _outcomes(got["attempts"]) == [("euryale-v2.3", f"http_{status}"), ("hermes-4-405b", "ok")]
        assert [x["host"] for x in fw.requests] == [NANO, OPENROUTER], fw.requests


@contextlib.contextmanager
def _capped(providers: tuple[str, ...]):
    """Today's per-(account, provider) cost row at Creator A's daily cap, then removed."""
    from db.models import GrokDailyCost
    import llm_client
    day = datetime.utcnow().strftime("%Y-%m-%d")

    async def seed():
        async with get_session() as s:
            cap = (await s.get(AccountAiConfig, A)).daily_cost_cap_cents
            for p in providers:
                await s.merge(GrokDailyCost(day=day, account_id=A, provider=p, call_count=1,
                                            cost_cents=cap * llm_client._MILLICENTS_PER_CENT))

    async def clear():
        async with get_session() as s:
            await s.execute(text("DELETE FROM grok_daily_cost WHERE account_id = :a"), {"a": A})
    _db(seed)
    try:
        yield
    finally:
        _db(clear)


def case_chain_provider_cap():
    with _capped(("nanogpt",)):
        r, fw = _chain_post(_body("p-cap"), {})
    got = r.json()
    assert (got["status"], got["writer"]) == ("sent", "hermes-4-405b"), got
    assert _outcomes(got["attempts"]) == [("euryale-v2.3", "cap"), ("hermes-4-405b", "ok")], got
    assert [x["host"] for x in fw.requests] == [OPENROUTER], fw.requests
    with _capped(("nanogpt", "openrouter", "zai", "deepseek")):
        r, fw = _chain_post(_body("p-cap-all"), {})
    got = r.json()
    assert (got["status"], got["parts"], got["writer"]) == ("failed", [], None), got
    assert _outcomes(got["attempts"]) == [(w, "cap") for w in CHAIN] and fw.requests == [], got
    (row,) = _rows(A, "p-cap-all")
    assert row.writer_model is None, row.writer_model


class _SlowWriters(FakeWriterHTTP):
    """Every Writer request runs to its full timeout on the clock, then times out."""

    def __init__(self, clock: _Clock):
        super().__init__({NANO: "timeout", OPENROUTER: "timeout", ZAI: "timeout", DEEPSEEK: "timeout"})
        self.clock, self.start = clock, clock.t
        self.left: list[float] = []          # time left on the Turn when each request went out

    def __call__(self, *a, timeout=None, **k):
        self.left.append(self.start + turn_bound_s(DEFAULTS) - self.clock.t)
        self.clock.t += timeout
        return super().__call__(*a, timeout=timeout, **k)


def case_chain_turn_deadline():
    """Router Jev stalls 100 s of a 145 s Turn: NanoGPT gets its full 25 s, Hermes the 20 s
    left, GLM and DeepSeek are not called (`timeout`). A Router stall to the bound leaves no
    Writer called."""
    import types
    bound = turn_bound_s(DEFAULTS)
    assert bound == 145, bound
    for jev_s, want_timeouts in ((100.0, [25.0, 20.0]), (145.0, [])):
        clock = _Clock()
        fake_clock = types.SimpleNamespace(monotonic=clock.now, perf_counter=time.perf_counter)
        saved = (full_ai_turn.time, full_ai_writers.time)
        full_ai_turn.time = full_ai_writers.time = fake_clock
        fw = _SlowWriters(clock)
        try:
            t0 = time.perf_counter()
            r, _ = _chain_post(_body(f"p-deadline-{int(jev_s)}"), {}, fake_w=fw,
                               fake_j=_SlowJev(clock, jev_s, (QUIET, 1.0)))
            wall = time.perf_counter() - t0
        finally:
            full_ai_turn.time, full_ai_writers.time = saved
        got = r.json()
        assert [x["timeout"] for x in fw.requests] == want_timeouts, (jev_s, fw.requests)
        assert all(x["timeout"] <= left for x, left in zip(fw.requests, fw.left)), (fw.requests, fw.left)
        assert _outcomes(got["attempts"]) == [(w, "timeout") for w in CHAIN], got["attempts"]
        assert (got["status"], got["writer"]) == ("failed", None), got
        assert clock.t - fw.start <= bound, (clock.t - fw.start, bound)
        assert wall < 5.0, wall


if __name__ == "__main__":
    _harness.run()
