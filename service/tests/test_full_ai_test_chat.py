#!/usr/bin/env python3
from __future__ import annotations

import _harness

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

from _full_ai_fixtures import QUIET, QUIET_TEST, FakeJev, FakeWriterHTTP, _fake_jev, _shape_drop
from automations import _info_jev, _router_jev, full_ai_chat, full_ai_offer_turn, full_ai_sell, full_ai_test, full_ai_turn
from automations import full_ai_writers
from automations._outbound import finalize_draft
from automations._style_flags import STYLE_AUTOMATIONS, nonnative_flag_key, spacing_flag_key, typo_flag_key
from automations.full_ai_config import DEFAULTS, turn_bound_s
from automations.full_ai_decide import arm_of
from db.engine import get_session
from db.models import AccountAiConfig, Fan, Message


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


def case_strip_emojis_config():
    pair, raw = "p-emoji", "omg hii 😏 what are u up to tonight"
    _store_config(A, {"draft": {**DEFAULTS, "strip_emojis": True}, "rev": 4})
    try:
        ck, *_ = _post(OWNER_A, _body(pair), f"ok:{raw}")
        dr, *_ = _post(OWNER_A, _body(pair, side="draft"), f"ok:{raw}")
    finally:
        _store_config(A, {})
    kept, gone = (" ".join(p["text"] for p in x.json()["parts"]) for x in (ck, dr))
    assert "😏" in kept and "hii" in kept, kept
    assert "😏" not in gone and "hii" in gone and "tonight" in gone, gone
    ck_row, dr_row = _rows(A, pair)
    assert "😏" not in json.dumps(_reply(dr_row)["parts"], ensure_ascii=False), _reply(dr_row)["parts"]


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
    assert c["parts"] != d["parts"], (c["parts"], d["parts"])
    ck_row, dr_row = _rows(A, pair)
    assert _reply(dr_row)["typo_state"] == {} and _reply(ck_row)["typo_state"] != {}, (
        _reply(ck_row)["typo_state"], _reply(dr_row)["typo_state"])


def case_echo_is_sent():
    pair, his = "p-echo", "happy halloween"
    r, fw, *_ = _post(OWNER_A, _body(pair, text=his), "ok:happy halloween to u too")
    got = r.json()
    assert r.status_code == 200, r.text
    assert got["status"] == "sent" and got["parts"] and "dropped_reason" not in got, got
    assert "halloween" in " ".join(p["text"] for p in got["parts"]), got["parts"]
    (row,) = _rows(A, pair)
    assert _reply(row)["dropped_reason"] is None, _reply(row)
    pair = "p-drop"
    with _shape_drop("banned"):
        r, fw, *_ = _post(OWNER_A, _body(pair), "ok:hii")
    got = r.json()
    assert (got["status"], got["parts"], got["writer"], got["wait_s"]) == ("failed", [], None, None), got
    assert got["dropped_reason"] == "banned" and len(fw.requests) == 1, (got, fw.requests)
    (row,) = _rows(A, pair)
    assert row.status == "failed" and row.writer_model is None, (row.status, row.writer_model)
    assert _reply(row)["dropped_reason"] == "banned", _reply(row)
    assert full_ai_test.session_row(row)["dropped_reason"] == "banned", full_ai_test.session_row(row)


def case_typo_state_is_the_sessions():
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
    pair = "p-twice-at-once"
    body = _body(pair)
    real, calls, out = full_ai_turn.run_turn, [], {}
    entered, release = threading.Event(), threading.Event()

    async def held(facts):
        calls.append(facts.anchor_key)
        if len(calls) == 1:
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
            threading.Timer(0.5, release.set).start()
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
    assert rows_at_409 == [first.json()["row_id"]], rows_at_409
    assert [x.id for x in _rows(A, pair)] == [first.json()["row_id"]]


def case_session_reads_both_sides_in_order():
    pair = "p-both"
    a1, *_ = _post(OWNER_A, _body(pair, text="hey there"), "ok:heyy")
    b1, *_ = _post(OWNER_A, _body(pair, text="hello", side="draft"), "ok:hii")
    a2, _, fj, _ = _post(OWNER_A, _body(pair, 2, "how are you"), "ok:good wbu")
    assert [x.status_code for x in (a1, b1, a2)] == [200, 200, 200]
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



_TEST_MODULES = (full_ai_test, full_ai_writers, full_ai_turn, full_ai_offer_turn, _info_jev, full_ai_sell, _router_jev,
                 full_ai_chat)
_BANNED_MODULES = {"of_client", "automation_executor", "fan_lease", "dm_rate", "of_sends", "of_write"}
_BANNED_NAMES = {"_make_client", "send_message", "acquire_fan_lease", "start_fan_cooldown"}


def _send_paths(source: str) -> list[str]:
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
    import inspect
    import full_ai_api
    assert inspect.getmodule(full_ai_test.settle) in _TEST_MODULES
    src = inspect.getsource(full_ai_api.full_ai_test_settle)
    assert "full_ai_test.settle(" in src and _send_paths(src) == [], _send_paths(src)
    for m in sorted(_BANNED_MODULES):
        assert _send_paths(f"import {m}\n") == [m], m
    for name in sorted(_BANNED_NAMES):
        assert _send_paths(f"x.{name}()\n") == [name], name
        assert _send_paths(f"{name}()\n") == [name], name
    assert _send_paths("from fan_lease import acquire_fan_lease\n") == ["fan_lease", "acquire_fan_lease"]
    assert _send_paths("from automations._outbound import finalize_draft\n") == []



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
    assert _thread(fjc) == ([("fan", "hey there stranger")] + _her(c1.json())
                            + [("fan", "just got home from work")] + _her(c2.json())), _thread(fjc)
    assert fjc.calls[0]["state"]["fan_new_messages"] == ["yeah super tired"], fjc.calls[0]["state"]
    assert _thread(fjd) == [("fan", "hello gorgeous")] + _her(d1.json()), _thread(fjd)


def case_test_thread_equals_the_db_thread():
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



CHAIN = ("euryale-v2.3", "euryale-v2.2", "hermes-4-405b", "deepseek-v4-flash")



def _outcomes(attempts: list[dict]) -> list[tuple[str, str]]:
    return [(a["writer"], a["outcome"]) for a in attempts]


def case_chain_falls_on_each_failure():
    for how, outcome in (("503", "http_503"), ("429", "http_429"), ("timeout", "timeout"),
                         ("empty", "empty")):
        pair = f"p-fall-{how}"
        r, fw = _chain_post(_body(pair), {NANO: how})
        got = r.json()
        assert (got["status"], got["writer"]) == ("sent", "euryale-v2.2"), (how, got)
        assert _outcomes(got["attempts"]) == [("euryale-v2.3", outcome), ("euryale-v2.2", "ok")], got
        assert all(a["ms"] >= 0 for a in got["attempts"]), got["attempts"]
        assert got["parts"], got
        assert [x["host"] for x in fw.requests] == [NANO, OPENROUTER], (how, fw.requests)
        assert [x["timeout"] for x in fw.requests] == [45.0, 45.0], fw.requests
        (row,) = _rows(A, pair)
        assert (row.status, row.writer_model) == ("sent", "euryale-v2.2"), (row.status, row.writer_model)
        assert _reply(row)["attempts"] == got["attempts"], _reply(row)


def case_chain_floor_reject_falls():
    pair = "p-floor"
    r, fw = _chain_post(_body(pair), {NANO: "ok:framework: 1) tease him 2) ask his name"})
    got = r.json()
    assert (got["status"], got["writer"]) == ("sent", "euryale-v2.2"), got
    assert _outcomes(got["attempts"]) == [("euryale-v2.3", "floor:framework"), ("euryale-v2.2", "ok")]
    (row,) = _rows(A, pair)
    assert _reply(row)["floor_reason"] == "framework", _reply(row)
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
    assert _outcomes(got["attempts"]) == list(zip(CHAIN, ("http_503", "timeout", "timeout", "empty")))
    assert [x["host"] for x in fw.requests] == [NANO, OPENROUTER, OPENROUTER, DEEPSEEK], fw.requests
    (row,) = _rows(A, pair)
    assert (row.status, row.writer_model) == ("failed", None), (row.status, row.writer_model)
    assert _reply(row)["parts"] == [] and _reply(row)["attempts"] == got["attempts"], _reply(row)


def case_chain_key_missing_or_refused():
    with _agency_keys({"nanogpt": ""}):
        r, fw = _chain_post(_body("p-nokey"), {})
    got = r.json()
    assert (got["status"], got["writer"]) == ("sent", "euryale-v2.2"), got
    assert _outcomes(got["attempts"]) == [("euryale-v2.3", "no_key"), ("euryale-v2.2", "ok")], got
    assert [x["host"] for x in fw.requests] == [OPENROUTER], fw.requests
    for status in ("401", "402"):
        r, fw = _chain_post(_body(f"p-badkey-{status}"), {NANO: status})
        got = r.json()
        assert got["writer"] == "euryale-v2.2", (status, got)
        assert _outcomes(got["attempts"]) == [("euryale-v2.3", f"http_{status}"), ("euryale-v2.2", "ok")]
        assert [x["host"] for x in fw.requests] == [NANO, OPENROUTER], fw.requests


@contextlib.contextmanager
def _capped(providers: tuple[str, ...] = ("chat",)):
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
    with _capped(("nanogpt", "openrouter", "zai", "deepseek")):
        r, fw = _chain_post(_body("p-cap"), {})
    got = r.json()
    assert (got["status"], got["writer"]) == ("sent", CHAIN[0]), got
    with _capped():
        r, fw = _chain_post(_body("p-cap-all"), {})
    got = r.json()
    assert (got["status"], got["parts"], got["writer"]) == ("failed", [], None), got
    assert _outcomes(got["attempts"]) == [(w, "cap") for w in CHAIN] and fw.requests == [], got
    (row,) = _rows(A, "p-cap-all")
    assert row.writer_model is None, row.writer_model


class _SlowWriters(FakeWriterHTTP):

    def __init__(self, clock: _Clock):
        super().__init__({NANO: "timeout", OPENROUTER: "timeout", ZAI: "timeout", DEEPSEEK: "timeout"})
        self.clock, self.start = clock, clock.t
        self.left: list[float] = []

    def __call__(self, *a, timeout=None, **k):
        self.left.append(self.start + turn_bound_s(DEFAULTS) - self.clock.t)
        self.clock.t += timeout
        return super().__call__(*a, timeout=timeout, **k)


def case_chain_retries_and_timeouts():
    _store_config(A, {"checkpoint": {**DEFAULTS, "writer_retries": 1, "writer_timeouts": {"euryale-v2.3": 60}}})
    try:
        for how, outcome in (("429", "http_429"), ("timeout", "timeout"), ("503", "http_503")):
            r, fw = _chain_post(_body(f"p-retry-{how}"), {NANO: how})
            got = r.json()
            assert (got["status"], got["writer"]) == ("sent", "euryale-v2.2"), (how, got)
            assert _outcomes(got["attempts"]) == [("euryale-v2.3", outcome)] * 2 + [("euryale-v2.2", "ok")], got
            assert [(x["host"], x["timeout"]) for x in fw.requests] == [
                (NANO, 60.0), (NANO, 60.0), (OPENROUTER, 45.0)], fw.requests
        r, fw = _chain_post(_body("p-retry-401"), {NANO: "401"})
        got = r.json()
        assert _outcomes(got["attempts"]) == [("euryale-v2.3", "http_401"), ("euryale-v2.2", "ok")], got
    finally:
        _store_config(A, {})


def case_chain_turn_deadline():
    import types
    bound = turn_bound_s(DEFAULTS)
    assert bound == 245, bound
    for jev_s, want_timeouts in ((180.0, [45.0, 20.0]), (245.0, [])):
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
