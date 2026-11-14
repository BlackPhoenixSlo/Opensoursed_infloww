#!/usr/bin/env python3
"""test_full_ai_info_chat — Full AI Test chat: get-to-know info (phase 03a, ticket 35; split from
test_full_ai_test_chat.py).

Shared setup (seeded Agencies, owner clients, `_guarded`, `_post`, the Writer fakes) is
`_full_ai_chat_helpers.py`; every Turn runs inside `_guarded` as in test_full_ai_test_chat.py.

   case_info_stated_age_folds        Jev fires stated_his_age, the faked DeepSeek extract says 31:
                                     reply_json + response fan_info, the next row's fold carries it,
                                     a newer stated value replaces it (no `fans` row: `_guarded`)
   case_info_pick_in_writer_system   Jev's `next_question` pick is the chat Writer's ask line;
                                     `none` asks nothing; a sent ask counts in `asked`; a pick he
                                     answers in the same Turn is not asked or counted; nothing
                                     missing: no Choice, know enough; a sext Turn: Nouls only,
                                     no ask, nothing counted
   case_info_options_and_asked       the Choice offers every missing info field + none, a field
                                     asked twice included; the state carries the asked counts
   case_info_lead_in                 `lead_in`: lead head + line, SELF_GIVE, no fetishes ask, lead Jev wording
   case_info_stalled_extract         extract timeout / Jev failure: reply still written, fan_info
                                     unchanged, info_error set; extract capped by the Turn deadline,
                                     no time left skips the stage (`deadline`)

Run: ./venv/bin/python service/tests/test_full_ai_info_chat.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

from _full_ai_chat_helpers import (
    _CHAIN_KEYS, _GIF_TAG, A, DEEPSEEK, NANO, OK_LINE, OPENROUTER, OWNER_A, TURN, ZAI, _agency_keys,
    _body, _Clock, _guarded, _reply, _rows, _SlowJev, _store_config,
)
import json
import time

from _full_ai_fixtures import QUIET, FakeJev, FakeWriterHTTP, _fake_jev
from automations import _info_jev, full_ai_turn, full_ai_writers
from automations.full_ai_config import DEFAULTS, turn_bound_s


# ── Get-to-know (ticket 35) ───────────────────────────────────────────
#   case_info_stated_age_folds        Jev fires stated_his_age, the faked DeepSeek extract says 31:
#                                     reply_json + response fan_info, the next row's fold carries it,
#                                     a newer stated value replaces it (no `fans` row: `_guarded`)
#   case_info_pick_in_writer_system   Jev's `next_question` pick is the chat Writer's ask line;
#                                     `none` asks nothing; a sent ask counts in `asked`; a pick he
#                                     answers in the same Turn is not asked or counted; nothing
#                                     missing: no Choice, know enough; a sext Turn: Nouls only,
#                                     no ask, nothing counted
#   case_info_options_and_asked       the Choice offers every missing info field + none, a field
#                                     asked twice included; the state carries the asked counts
#   case_info_lead_in                 `lead_in`: lead head + line, SELF_GIVE, no fetishes ask, lead Jev wording
#   case_info_stalled_extract         extract timeout / Jev failure: reply still written, fan_info
#                                     unchanged, info_error set; extract capped by the Turn deadline,
#                                     no time left skips the stage (`deadline`)

from _full_ai_fixtures import FakeInfoJev  # noqa: E402
from automations.welcome_chatter_for_info import _EXTRACT_FIELDS, _EXTRACT_SYSTEM  # noqa: E402


def _extract_says(**vals) -> str:
    """The faked DeepSeek extract's reply: wcfi's JSON with `vals` filled."""
    return "ok:" + json.dumps({**dict.fromkeys(_EXTRACT_FIELDS, ""), "likes_boobs": False,
                               "likes_ass": False, "recent_events": [], "her_claims": [], **vals})


def _info_post(body: dict, info: FakeInfoJev, script: dict | None = None, *, fake_w=None,
               fake_j=None):
    """One test turn under the invariants with both Jevs and every Writer host faked (a host left
    out answers OK_LINE): (response json, Writer fake, wall seconds)."""
    full = {NANO: OK_LINE, OPENROUTER: OK_LINE, ZAI: OK_LINE, DEEPSEEK: OK_LINE, **(script or {})}
    fake_w = fake_w or FakeWriterHTTP(full)
    with _agency_keys(_CHAIN_KEYS), _guarded(), fake_w.on(), \
            _fake_jev(fake_j or FakeJev((QUIET, 1.0)), info):
        t0 = time.perf_counter()
        r = OWNER_A.post(TURN, json=body)
        wall = time.perf_counter() - t0
    assert r.status_code == 200, r.text
    return r.json(), fake_w, wall


def case_info_stated_age_folds():
    pair = "p-info-age"
    info = FakeInfoJev(({"his_age": 0.95}, "none"))
    got, fw, _ = _info_post(_body(pair, 1, "im 31 btw, u?"), info, {DEEPSEEK: _extract_says(his_age="31")})
    assert got["status"] == "sent" and got["fan_info"] == {"his_age": "31"}, got
    # The extract runs before the Writer, once, on DeepSeek with wcfi's verbatim prompt.
    assert [x["host"] for x in fw.requests] == [DEEPSEEK, NANO], fw.requests
    ex = fw.requests[0]
    assert ex["model"] == "deepseek-v4-flash" and ex["timeout"] == 25.0, ex
    assert ex["body"]["messages"][0] == {"role": "system", "content": _EXTRACT_SYSTEM}, ex["body"]
    assert "FAN: im 31 btw, u?" in ex["body"]["messages"][1]["content"], ex["body"]
    assert ex["body"]["response_format"] == {"type": "json_object"}, ex["body"]
    (row,) = _rows(A, pair)
    assert _reply(row)["fan_info"] == {"his_age": "31"} and _reply(row)["info_error"] is None, _reply(row)
    # `lead_in` on by default in test Mode: the lead wording's digest.
    assert json.loads(row.jev_json)["info_version"] == _info_jev.INFO_VERSION_LEAD, row.jev_json
    # Turn 2 states nothing: no extract, the fold carries the age.
    got, fw, _ = _info_post(_body(pair, 2, "what are u up to"), FakeInfoJev())
    assert got["fan_info"] == {"his_age": "31"} and DEEPSEEK not in [x["host"] for x in fw.requests], got
    assert _reply(_rows(A, pair)[1])["fan_info"] == {"his_age": "31"}
    # Turn 3: a newer stated value replaces the older one.
    got, _, _ = _info_post(_body(pair, 3, "ok im actually 32 lol"), FakeInfoJev(({"his_age": 0.9}, "none")),
                           {DEEPSEEK: _extract_says(his_age="32")})
    assert got["fan_info"] == {"his_age": "32"}, got


def _system(fw: FakeWriterHTTP) -> str:
    (w,) = [x for x in fw.requests if x["host"] == NANO]
    return w["body"]["messages"][0]["content"]


# `lead_in` off: the cases below pin today's ask (the lead form: `case_info_lead_in`).
_LEAD_OFF = {**DEFAULTS, "lead_in": False}


def case_info_pick_in_writer_system():
    _store_config(A, {"checkpoint": _LEAD_OFF})
    try:
        _pick_in_writer_system()
    finally:
        _store_config(A, {})


def _pick_in_writer_system():
    job = "- You DON'T know what he does for work. Ask what he does for a living."
    got, fw, _ = _info_post(_body("p-info-pick"), FakeInfoJev(({}, "occupation")))
    assert got["status"] == "sent", got
    assert full_ai_writers.ASK_HEAD + job in _system(fw), _system(fw)
    (row,) = _rows(A, "p-info-pick")
    assert _reply(row)["asked"] == {"occupation": 1}, _reply(row)
    # `none`: no ask line, nothing counted.
    got, fw, _ = _info_post(_body("p-info-none"), FakeInfoJev(({}, "none")))
    assert full_ai_writers.ASK_HEAD not in _system(fw) and job not in _system(fw), _system(fw)
    assert _reply(_rows(A, "p-info-none")[0])["asked"] == {}
    # Jev picks his age while he states it: the extract fills it, so no ask, nothing counted.
    got, fw, _ = _info_post(_body("p-info-answered", 1, "im 31"), FakeInfoJev(({"his_age": 0.95}, "his_age")),
                            {DEEPSEEK: _extract_says(his_age="31")})
    assert got["fan_info"] == {"his_age": "31"} and full_ai_writers.ASK_HEAD not in _system(fw), _system(fw)
    assert _reply(_rows(A, "p-info-answered")[0])["asked"] == {}
    # Every info field known: no Choice asked, the know-enough tier.
    _store_config(A, {"checkpoint": {**_LEAD_OFF, "info_fields": ["his_age"]}})
    try:
        info = FakeInfoJev()
        _, fw, _ = _info_post(_body("p-info-answered", 2, "so what now"), info)
    finally:
        _store_config(A, {"checkpoint": _LEAD_OFF})
    assert "next_question" not in info.calls[0]["questions"], info.calls[0]["questions"]
    assert full_ai_writers.KNOW_ENOUGH in _system(fw), _system(fw)
    # A sext Turn: Jev still gates what he stated, but no Choice, no ask line, nothing counted.
    info = FakeInfoJev(({}, "occupation"))
    got, fw, _ = _info_post(_body("p-info-sext"), info, fake_j=FakeJev(({**QUIET, "sexual_now": 0.95}, 3.0)))
    assert got["route"] == "sext" and got["status"] == "sent", got
    assert "next_question" not in info.calls[0]["questions"] and info.calls[0]["state"]["asked"] == {}
    assert full_ai_writers.ASK_HEAD not in _system(fw), _system(fw)
    assert _reply(_rows(A, "p-info-sext")[0])["asked"] == {}
    # A sticker-only reply: Jev picked a field but no text went out, so the ask is not counted.
    _store_config(A, {"checkpoint": {**_LEAD_OFF, "gifs": True}})
    try:
        lone = f"ok:STICKER: {_GIF_TAG}"
        got, _, _ = _info_post(_body("p-info-gif"), FakeInfoJev(({}, "occupation")),
                               {NANO: lone, OPENROUTER: lone, ZAI: lone, DEEPSEEK: lone})
    finally:
        _store_config(A, {"checkpoint": _LEAD_OFF})
    assert got["status"] == "sent" and [set(p) for p in got["parts"]] == [{"gif", "tag"}], got
    assert _reply(_rows(A, "p-info-gif")[0])["asked"] == {}, _reply(_rows(A, "p-info-gif")[0])


def case_info_options_and_asked():
    _store_config(A, {"checkpoint": _LEAD_OFF})
    try:
        _options_and_asked()
    finally:
        _store_config(A, {})


def _options_and_asked():
    pair = "p-info-asked"
    for n, (stated, script) in enumerate(((
            {"real_name": 0.95}, {DEEPSEEK: _extract_says(real_name="Sam")}), ({}, None)), start=1):
        got, _, _ = _info_post(_body(pair, n, f"line {n}"), FakeInfoJev((stated, "his_age")), script)
        assert got["status"] == "sent", got
    assert _reply(_rows(A, pair)[-1])["asked"] == {"his_age": 2}, _reply(_rows(A, pair)[-1])
    info = FakeInfoJev()
    _info_post(_body(pair, 3, "line 3"), info)
    (call,) = info.calls
    missing = [f for f in DEFAULTS["info_fields"] if f != "real_name"]
    q = call["questions"]
    assert list(q["next_question"].criteria) == missing + ["none"], q["next_question"].criteria
    assert "his_age" in q["next_question"].criteria                 # asked twice: still offered
    assert {k for k in q if k.startswith("stated_")} == {f"stated_{f}" for f in _EXTRACT_FIELDS}, q
    assert call["state"]["asked"] == {f: (2 if f == "his_age" else 0) for f in missing}, call["state"]
    assert call["state"]["fan_new_messages"] == ["line 3"], call["state"]
    assert call["model"] == _info_jev.MODEL, call


def case_info_lead_in():
    """`lead_in` (default on, test Mode): Jev's pick reaches the Writer as LEAD_HEAD + its
    LEAD_LINES line (counted in `asked`), SELF_GIVE for SELF_BAN, no "Ask what"; the Choice never
    offers fetishes and carries the lead wording (`her_last_line` in the state, the lead digest); a
    pick of fetishes fails the Choice (no ask, `asked` unchanged); every other fact known with
    fetishes empty is know enough with no Choice."""
    got, fw, _ = _info_post(_body("p-lead-pick"), FakeInfoJev(({}, "occupation")))
    sys_ = _system(fw)
    assert got["status"] == "sent", got
    assert full_ai_writers.LEAD_HEAD + full_ai_writers.LEAD_LINES["job"] in sys_, sys_
    assert full_ai_writers.ASK_HEAD not in sys_ and "Ask what" not in sys_, sys_
    assert full_ai_writers.SELF_GIVE in sys_ and full_ai_writers.SELF_BAN not in sys_, sys_
    (row,) = _rows(A, "p-lead-pick")
    assert _reply(row)["asked"] == {"occupation": 1}, _reply(row)
    assert json.loads(row.jev_json)["info_version"] == _info_jev.INFO_VERSION_LEAD != _info_jev.INFO_VERSION
    info = FakeInfoJev()
    _info_post(_body("p-lead-offer"), info)
    (call,) = info.calls
    nq = call["questions"]["next_question"]
    assert "fetishes" not in nq.criteria and "none" in nq.criteria, nq.criteria
    assert nq.instructions == _info_jev.NEXT_QUESTION_LEAD["instructions"], nq.instructions
    assert "her_last_line" in call["state"], call["state"]
    # Jev picks fetishes anyway: not offered, so the Choice fails; the reply is still written.
    got, fw, _ = _info_post(_body("p-lead-fet"), FakeInfoJev(({}, "fetishes")))
    assert got["status"] == "sent", got
    (row,) = _rows(A, "p-lead-fet")
    assert _reply(row)["asked"] == {} and _reply(row)["info_error"].startswith("jev_failed"), _reply(row)
    assert full_ai_writers.LEAD_HEAD not in _system(fw), _system(fw)
    # Every fact but fetishes known: know enough, no Choice.
    pair = "p-lead-enough"
    known = dict(real_name="Sam", his_age="31", home_country="Spain", home_city="Madrid",
                 hobbies="surfing", occupation="chef")
    _info_post(_body(pair, 1, "hi"), FakeInfoJev(({k: 0.95 for k in known}, "none")),
               {DEEPSEEK: _extract_says(**known)})
    info = FakeInfoJev()
    _, fw, _ = _info_post(_body(pair, 2, "so what now"), info)
    assert "next_question" not in info.calls[0]["questions"], info.calls[0]["questions"]
    assert full_ai_writers.KNOW_ENOUGH in _system(fw), _system(fw)


class _StallExtract(FakeWriterHTTP):
    """The DeepSeek extract runs to its full timeout on the Turn clock, then times out; every
    Writer answers at once."""

    def __init__(self, clock: _Clock):
        super().__init__({NANO: OK_LINE, OPENROUTER: OK_LINE, ZAI: OK_LINE, DEEPSEEK: "timeout"})
        self.clock = clock

    def __call__(self, *a, timeout=None, **k):
        conn = super().__call__(*a, timeout=timeout, **k)
        post = conn.post

        async def stalled(url, headers=None, json=None):
            if (json or {}).get("model") == "deepseek-v4-flash":
                self.clock.t += timeout
            return await post(url, headers=headers, json=json)
        conn.post = stalled
        return conn


def case_info_stalled_extract():
    import types
    pair = "p-info-stall"
    got, fw, wall = _info_post(_body(pair), FakeInfoJev(({"his_age": 0.95}, "none")), {DEEPSEEK: "timeout"})
    assert (got["status"], got["writer"], got["fan_info"]) == ("sent", "euryale-v2.3", {}), got
    (row,) = _rows(A, pair)
    assert _reply(row)["info_error"] == "extract:timeout" and _reply(row)["fan_info"] == {}, _reply(row)
    assert wall < 5.0, wall
    # A failed info Jev: the reply is still written, no extract.
    got, fw, _ = _info_post(_body("p-info-jevfail"), FakeInfoJev(RuntimeError("jev down")))
    assert got["status"] == "sent" and [x["host"] for x in fw.requests] == [NANO], (got, fw.requests)
    err = _reply(_rows(A, "p-info-jevfail")[0])["info_error"]
    assert err.startswith("jev_failed") and "jev down" in err, err
    # On the Turn clock: Router 100 s of 145 -> the extract gets its 25 s, stalls, NanoGPT the
    # 20 s left and sends; Router 130 s -> the extract is capped at the 15 s left, no Writer
    # time remains; Router 145 s -> the info stage is skipped (`deadline`).
    bound = turn_bound_s(DEFAULTS)
    for jev_s, extract_t, writer_t, status in ((100.0, [25.0], [20.0], "sent"),
                                               (130.0, [15.0], [], "failed"), (145.0, [], [], "failed")):
        clock = _Clock()
        start = clock.t
        fake_clock = types.SimpleNamespace(monotonic=clock.now, perf_counter=time.perf_counter)
        saved = (full_ai_turn.time, full_ai_writers.time)
        full_ai_turn.time = full_ai_writers.time = fake_clock
        info = FakeInfoJev(({"his_age": 0.95}, "none"))
        try:
            got, fw, _ = _info_post(_body(f"p-info-clock-{int(jev_s)}"), info, fake_w=_StallExtract(clock),
                                    fake_j=_SlowJev(clock, jev_s, (QUIET, 1.0)))
        finally:
            full_ai_turn.time, full_ai_writers.time = saved
        ts = [(x["model"], x["timeout"]) for x in fw.requests]
        assert [t for m, t in ts if m == "deepseek-v4-flash"] == extract_t, (jev_s, ts)
        assert [t for m, t in ts if m != "deepseek-v4-flash"] == writer_t, (jev_s, ts)
        assert got["status"] == status and got["fan_info"] == {}, (jev_s, got)
        assert clock.t - start <= bound, (jev_s, clock.t - start)
        (row,) = _rows(A, f"p-info-clock-{int(jev_s)}")
        want = "deadline" if jev_s >= bound else "extract:timeout"
        assert _reply(row)["info_error"] == want, (jev_s, _reply(row))
        assert (info.calls == []) == (jev_s >= bound), (jev_s, info.calls)


if __name__ == "__main__":
    _harness.run()
