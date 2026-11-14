"""lib/ultra_wild_relay.py's reply table and wire answer (no relay, no network)."""
from __future__ import annotations

import json

import pytest

from slop.lib import ultra_wild_relay as uw

WORLD = {"a_aid": "111", "b_aid": "990000001", "b_pid": "uwbpage00000001", "foreign_media": 999_999_001}
SYSTEM = {"role": "system", "content": "You plan work in Inflowwww for the Agency's owner."}


def _body(request: str, turns: int = 0, tool_answers: tuple[str, ...] = ()) -> dict:
    msgs = [SYSTEM, {"role": "user", "content": request}]
    for t in range(turns):
        msgs.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"call_{t}_0"}]})
        msgs += [{"role": "tool", "tool_call_id": f"call_{t}_0", "content": a} for a in tool_answers]
    return {"model": "deepseek-v4-flash", "messages": msgs}


@pytest.mark.parametrize("request_, turn, kind", [
    ("send a mass", 0, "calls"),                   # default: read-only plan
    ("send a mass", 1, "text"),                    # then idle text
    ("wild:unknown_tool go", 0, "calls"),
    ("wild:never_stops", 24, "calls"),
    ("wild:empty", 0, "text"),
    ("wild:http_500", 0, "status"),
    ("wild:http_500", 2, "status"),                # llm_client's retries re-ask turn 0..: every one 500
    ("wild:hang", 0, "hang"),
    ("wild:garbage_body", 0, "raw"),
    ("wild:no_such_case", 0, "calls"),             # unknown case: the default
    ("wild:send_bad", 99, "text"),                 # past a script: AFTER
])
def test_reply_kinds(request_, turn, kind):
    assert kind in uw.plan_reply(request_, turn, WORLD)


def test_default_is_one_read_only_step():
    (name, plan), = uw.plan_reply("anything", 0, WORLD)["calls"]
    assert name == uw.SUBMIT and [s["tool"] for s in plan["steps"]] == ["creators_list"]


def test_every_script_names_only_known_shapes():
    for case, turns in uw.scripts(WORLD).items():
        for r in turns:
            r = r.get("then", r)
            assert set(r) <= {"calls", "text", "status", "raw"}, case
            for name, args in r.get("calls", []):
                assert isinstance(name, str) and isinstance(args, (dict, str)), case


def test_world_ids_fill_in():
    s = uw.scripts(WORLD)
    assert s["cross_agency"][0]["calls"][0] == ["bio_page_get", {"pid": WORLD["b_pid"]}]
    assert s["send_bad"][4]["calls"][0][1]["steps"][0]["args"]["account_id"] == WORLD["b_aid"]
    assert s["send_bad"][5]["calls"][0][1]["steps"][0]["args"]["media_files"] == [WORLD["foreign_media"]]
    assert len(s["too_many_steps"][0]["calls"]) == 12
    assert len(s["too_many_steps"][1]["calls"][0][1]["steps"]) == 60
    assert uw.CONTROL in s["control_send"][0]["calls"][0][1]["steps"][0]["args"]["text"]


def test_answer_ignores_other_prompts(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_SHOTS_TMP", str(tmp_path))
    assert uw.answer({"messages": [{"role": "system", "content": "You turn a request into"}]}) is None
    assert not (tmp_path / uw.LOG).exists()


def test_answer_tool_calls_and_log(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_SHOTS_TMP", str(tmp_path))
    (tmp_path / uw.WORLD).write_text(json.dumps(WORLD))
    status, out = uw.answer(_body("wild:too_many_steps", turns=1, tool_answers=("a1", "a2")), sleep=lambda s: None)
    msg = out["choices"][0]["message"]
    assert status == 200 and out["choices"][0]["finish_reason"] == "tool_calls"
    assert msg["tool_calls"][0]["id"] == "call_1_0" and msg["tool_calls"][0]["function"]["name"] == uw.SUBMIT
    assert len(json.loads(msg["tool_calls"][0]["function"]["arguments"])["steps"]) == 60
    row = json.loads((tmp_path / uw.LOG).read_text().splitlines()[0])
    assert row["case"] == "too_many_steps" and row["turn"] == 1 and row["tool_answers"] == ["a1", "a2"]


def test_answer_raw_args_status_hang(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_SHOTS_TMP", str(tmp_path))
    slept: list[float] = []
    _s, out = uw.answer(_body("wild:bad_tool_json"), sleep=slept.append)
    assert out["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] == "{not json"
    assert uw.answer(_body("wild:http_500"), sleep=slept.append)[0] == 500
    assert uw.answer(_body("wild:garbage_body"), sleep=slept.append) == (200, "this is not a completion")
    _s, out = uw.answer(_body("wild:hang"), sleep=slept.append)
    assert uw.HANG_S in slept and out["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "creators_list"
    _s, out = uw.answer(_body("wild:empty"), sleep=slept.append)
    assert out["choices"][0]["message"] == {"role": "assistant", "content": ""}
