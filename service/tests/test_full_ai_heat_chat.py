#!/usr/bin/env python3
from __future__ import annotations

import _harness

from _full_ai_sell_helpers import (  # noqa: E402
    A, NANO, OPENROUTER, OWNER_A, TURN, _body, _guarded, _put_draft, _reply, _rows, _vault,
)
import contextlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from _full_ai_fixtures import QUIET_SCENE, FakeJev, FakeWriterHTTP, _fake_jev  # noqa: E402
from automations import full_ai_test  # noqa: E402
from automations.full_ai_config import DEFAULTS  # noqa: E402

GOLDEN = Path(__file__).with_name("test_full_ai_heat_chat.requests.golden.json")


class FakeHeatJev:

    def __init__(self, *verdicts):
        self.verdicts, self.calls = list(verdicts), []

    async def system_one(self, state, questions, model=None):
        self.calls.append({"state": state, "questions": dict(questions), "model": model})
        if not self.verdicts:
            raise AssertionError("unscripted heat request")
        v = self.verdicts.pop(0)
        if isinstance(v, Exception):
            raise v
        return SimpleNamespace(scores={"reply_level": SimpleNamespace(
            score=v, probabilities={0: .1, 1: .1, 2: .2, 3: .4, 4: .2})})


@contextlib.contextmanager
def _heat(fake):
    try:
        from automations import _heat_jev
    except ImportError:
        yield fake
        return
    real = _heat_jev._client
    _heat_jev._client = lambda key: fake
    try:
        yield fake
    finally:
        _heat_jev._client = real


@contextlib.contextmanager
def _draft(**cfg):
    _put_draft({**DEFAULTS, **cfg})
    try:
        yield
    finally:
        _put_draft(dict(DEFAULTS))


def _turn(pair, n, text, answers, writer, *, intensity=2.0, choices=None, heat=None):
    script = writer if isinstance(writer, dict) else {NANO: writer}
    fw = FakeWriterHTTP({NANO: "ok:hii", OPENROUTER: "ok:hii", **script})
    jev = FakeJev(({**QUIET_SCENE, **answers}, intensity, choices or {}))
    with _guarded(), fw.on(), _fake_jev(jev), _heat(heat or FakeHeatJev()) as hf:
        r = OWNER_A.post(TURN, json=_body(pair, text, n=n))
    assert r.status_code == 200, r.text
    return r.json(), fw, jev, hf


def _requests(jev, fw) -> list:
    out = [{"jev": {"model": c["model"], "state": c["state"],
                    "questions": {q: v.model_dump(mode="json") for q, v in c["questions"].items()}}}
           for c in jev.calls]
    return out + [{"writer": {"host": r["host"], "model": r["model"], "body": r["body"]}} for r in fw.requests]


SEXUAL = {"sexual_now": .9}


def _byte_turns() -> dict:
    got = {}
    with _draft(sext_scene=False, floor_on=True, sell_on=True, chat_tease=False), _vault({101: "$10"}):
        for name, text, answers in (("chat", "how was ur day", {}), ("sell", "send me pics", {"wants_content": .9}),
                                    ("no_send", "im 16", {"says_under_18": .9})):
            _, fw, jev, hf = _turn(f"bi-{name}", 1, text, answers, "ok:mm hey u")
            assert hf.calls == [], (name, hf.calls)
            got[name] = _requests(jev, fw)
    with _draft(sext_scene=False, floor_on=False):
        _, fw, jev, hf = _turn("bi-sext-off", 1, "ur making me hard", SEXUAL, "ok:mm tell me more")
        got["sext_floor_off"] = _requests(jev, fw)
    with _draft(sext_scene=True, floor_on=False):
        _, fw, jev, hf = _turn("bi-scene-off", 1, "ur making me hard", SEXUAL, "ok:mm tell me more",
                               choices={"scene_stage": "opening"})
        got["scene_floor_off"] = _requests(jev, fw)
    return got


def case_byte_identity():
    got = json.dumps(_byte_turns(), ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if os.environ.get("HEAT_CAPTURE") == "1":
        GOLDEN.write_text(got, encoding="utf-8")
    want = GOLDEN.read_text(encoding="utf-8")
    assert got == want, "requests moved vs the main capture"



FIRST, SECOND = "mm i want u so bad", "mm come here baby"


def _sext(pair, writer, *verdicts, n=1, **cfg):
    with _draft(**{"sext_scene": False, "floor_on": True, **cfg}):
        return _turn(pair, n, "ur making me so hard", SEXUAL, writer, heat=FakeHeatJev(*verdicts))


def _texts(parts) -> str:
    return " ".join(p["text"] for p in parts if p.get("text")).lower()


def _hc(pair) -> dict:
    (row,) = _rows(pair)
    assert row.route == "sext" and row.heat == 3, (row.route, row.heat)
    return _reply(row)


def case_ok():
    from automations import _heat_jev
    g, fw, _, hf = _sext("hc-ok", f"ok:{FIRST}", 3.0)
    assert len(hf.calls) == 1 and len(fw.requests) == 1, (hf.calls, fw.requests)
    (call,) = hf.calls
    assert list(call["questions"]) == ["reply_level"] and call["model"] == "jev-1.14.0", call
    assert call["state"] == {"her_reply": "\n".join(p["text"] for p in g["parts"] if p.get("text"))}, call
    h = _hc("hc-ok")["heat_check"]
    assert h == {"cap": 3, "score": 3.0, "level": 3, "outcome": "ok", "ms": h["ms"],
                 "version": _heat_jev.HEAT_VERSION}, h
    assert isinstance(h["ms"], int) and g["heat_check"] == h and g["status"] == "sent", g
    assert "want u so bad" in _texts(g["parts"]), g["parts"]


def case_rewrite():
    g, fw, _, hf = _sext("hc-redo", {NANO: [f"ok:{FIRST}", f"ok:{SECOND}"]}, 4.0, 3.0)
    assert len(fw.requests) == 2 and len(hf.calls) == 2, (fw.requests, hf.calls)
    assert fw.requests[0]["body"]["messages"] == fw.requests[1]["body"]["messages"], "same messages"
    assert fw.requests[0]["model"] == fw.requests[1]["model"], "the Writer that answered"
    assert [bool(a.get("rewrite")) for a in g["attempts"]] == [False, True], g["attempts"]
    assert "baby" in _texts(g["parts"]) and "bad" not in _texts(g["parts"]), g["parts"]
    assert "baby" in hf.calls[1]["state"]["her_reply"].lower(), hf.calls
    rp = _hc("hc-redo")
    h = rp["heat_check"]
    assert (h["outcome"], h["score"], h["level"], h["redo_score"], h["first_level"]) == ("regen_ok", 3.0, 3, 3.0, 4), h
    assert rp["parts"] == g["parts"] and g["status"] == "sent", rp


def case_over_twice():
    g, fw, _, hf = _sext("hc-over", {NANO: [f"ok:{FIRST}", f"ok:{SECOND}"]}, 4.0, 4.0)
    assert len(fw.requests) == 2 and len(hf.calls) == 2, (fw.requests, hf.calls)
    assert "want u so bad" in _texts(g["parts"]), g["parts"]
    h = _hc("hc-over")["heat_check"]
    assert (h["outcome"], h["score"], h["level"], h["redo_score"]) == ("over_sent", 4.0, 4, 4.0), h
    assert g["status"] == "sent" == _rows("hc-over")[0].status, g


def case_fail_open():
    g, fw, _, hf = _sext("hc-fail", f"ok:{FIRST}", RuntimeError("jev down"))
    assert len(fw.requests) == 1 and len(hf.calls) == 1, (fw.requests, hf.calls)
    h = _hc("hc-fail")["heat_check"]
    assert h["outcome"] == "error" and "jev down" in h["error"] and h["score"] is None, h
    assert "redo_score" not in h and g["status"] == "sent", (h, g)
    assert "want u so bad" in _texts(g["parts"]), g["parts"]


@contextlib.contextmanager
def _drop_when(marker: str):
    from automations import _reply_shape
    real = _reply_shape.shape_parts

    def shaped(raw, ctx):
        if marker in raw:
            return _reply_shape.Shaped(parts=[], dropped_reason="banned", banned_hits=[])
        return real(raw, ctx)
    _reply_shape.shape_parts = shaped
    try:
        yield
    finally:
        _reply_shape.shape_parts = real


def case_rewrite_lost():
    cases = (
        ("empty", "empty", (4.0,), 2, 1),
        ("leak", "ok:lets meet in person tonight", (4.0,), 2, 1),
        ("dropped", "ok:zzdrop mm", (4.0,), 2, 1),
        ("ask_fails", f"ok:{SECOND}", (4.0, RuntimeError("second down")), 2, 2),
    )
    for name, redo, verdicts, n_w, n_h in cases:
        pair = f"hc-lost-{name}"
        with _drop_when("zzdrop"):
            g, fw, _, hf = _sext(pair, {NANO: [f"ok:{FIRST}", redo]}, *verdicts)
        assert (len(fw.requests), len(hf.calls)) == (n_w, n_h), (name, fw.requests, hf.calls)
        assert "want u so bad" in _texts(g["parts"]), (name, g["parts"])
        rp = _hc(pair)
        h = rp["heat_check"]
        assert (h["outcome"], h["level"], h["redo_score"]) == ("over_sent", 4, None), (name, h)
        assert rp["leak"] == [] and rp["dropped_reason"] is None, (name, rp)
        assert rp["typo_state"] == {"at": None, "since": 1}, (name, rp["typo_state"])
        assert g["status"] == "sent", (name, g)


def case_no_time():
    from automations import full_ai_turn
    real = full_ai_turn.turn_bound_s
    full_ai_turn.turn_bound_s = lambda cfg: 30.0
    try:
        g, fw, _, hf = _sext("hc-late", {NANO: [f"ok:{FIRST}", f"ok:{SECOND}"]}, 4.0)
    finally:
        full_ai_turn.turn_bound_s = real
    assert len(fw.requests) == 1 and len(hf.calls) == 1, (fw.requests, hf.calls)
    h = _hc("hc-late")["heat_check"]
    assert h["outcome"] == "over_sent" and "redo_score" not in h and "first_level" not in h, h
    assert "want u so bad" in _texts(g["parts"]) and g["status"] == "sent", g


def case_not_asked():
    turns = []
    with _draft(sext_scene=False, floor_on=True, chat_tease=False):
        turns.append(("chat",) + _turn("hn-chat", 1, "how was ur day", {}, "ok:good u?")[::3])
        turns.append(("no_send",) + _turn("hn-u18", 1, "im 16", {**SEXUAL, "says_under_18": .9}, "ok:x")[::3])
        turns.append(("no_writer",) + _turn("hn-nowriter", 1, "ur hot", SEXUAL, {NANO: "500", OPENROUTER: "500"})[::3])
    with _draft(sext_scene=False, floor_on=False):
        turns.append(("floor_off",) + _turn("hn-floor", 1, "ur hot", SEXUAL, "ok:mm")[::3])
    with _draft(sext_scene=True, floor_on=True, sell_on=True, chat_tease=False), _vault({101: "$10", 202: "$50"}):
        from automations import _price_jev
        real, _price_jev._client = _price_jev._client, lambda key: _PriceOne()
        try:
            turns.append(("scene_sell",) + _turn("hn-scene-sell", 1, "fuck yes", {"scene_on": .9, "scene_offer": .9},
                                                 "ok:i filmed this for u", intensity=3.0,
                                                 choices={"offer_level": "soft"})[::3])
        finally:
            _price_jev._client = real
    for name, g, hf in turns:
        (row,) = _rows({"chat": "hn-chat", "no_send": "hn-u18", "no_writer": "hn-nowriter",
                        "floor_off": "hn-floor", "scene_sell": "hn-scene-sell"}[name])
        assert hf.calls == [] and "heat_check" not in g and "heat_check" not in _reply(row), (name, hf.calls, g)
        want = {"chat": "chat", "no_send": "no_send", "no_writer": "sext", "floor_off": "sext",
                "scene_sell": "sell_now"}[name]
        assert row.route == want, (name, row.route)


class _PriceOne:
    async def system_one(self, state, questions, model=None):
        return SimpleNamespace(scores={"price": SimpleNamespace(score=1.0, probabilities={1: 1.0})})


def case_session_read():
    _sext("hc-read", {NANO: [f"ok:{FIRST}", f"ok:{SECOND}"]}, 4.0, 3.0)
    (row,) = _rows("hc-read")
    got = full_ai_test.session_row(row)
    assert got["heat_check"]["outcome"] == "regen_ok" and got["heat_check"] == _reply(row)["heat_check"], got
    with _guarded():
        r = OWNER_A.get("/admin/full-ai/test/session", params={"account_id": A, "pair": "hc-read"})
    assert r.status_code == 200, r.text
    (x,) = r.json()["rows"]
    assert x["heat_check"] == got["heat_check"], r.json()


_harness.run()
