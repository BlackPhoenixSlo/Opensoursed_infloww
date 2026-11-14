#!/usr/bin/env python3
"""Ultra plans, pure (service/ultra_decide.py; docs/plans/ultra-mode/issues/06-ultra-loop.md).

Cases:
  case_valid_plan        — a read → write (reference) → send (literal ids) plan validates; the summary is trimmed;
                           the write records its reference's location; "$5 off" in a send's text is text.
  case_refused_table     — table: not an object, empty summary, no steps, too many, unknown tool, bad args (the
                           tool's pydantic model), unknown key on a step, bad / duplicate id, a reference to an
                           unknown step, a forward reference, a self reference, a reference in account_id, another
                           Agency's Creator → PlanError naming step + field.
  case_send_literal_only — a reference in EVERY field of mass_send / post_create (and " $x.y" with a leading
                           space) → refused naming step + field; nothing recorded for a send.
  case_substitute        — recorded references filled from earlier results (dotted keys, list index); a missing
                           path → KeyError; an unrecorded "$x.y" string and " $x.y" untouched; a send step's args
                           come back unchanged even when they read like references.
  case_digest            — sha256 over canonical JSON: key order does not matter, any change does.
  case_outcome           — done / failed / uncertain per effect: a send with no answer, a 5xx or an echo-check
                           502 is uncertain, a write with no answer too (m6); a send 4xx, a write's 4xx/5xx and
                           a read's failure are failed.
  case_states            — expired after OK_TTL (awaiting_ok only), said as OK_TTL_TEXT; PlanStatus / StepState
                           are the Literal sets (FINAL inside PlanStatus); close: started → uncertain, pending → skipped,
                           ended states kept; recovered: running → interrupted with close's states; any other
                           status untouched.
  case_step_end          — a call result → the stored state: done keeps open_url and the id it made (short
                           scalars only), a mass that kept fewer fan ids than approved a plain note (kept_note);
                           a failure / an uncertain send
                           carries the error as error_text's sentence (no answer: NO_ANSWER), clipped to MAX_ERROR.
  case_oversize_send_done — a send's 2xx answer over the size cap: done with its id + truncated (a read: 413).
  case_error_text        — an error detail → one plain sentence: OF's {upstream_status, upstream_body} → "OnlyFans
                           answered 500: <OF's message>", a relay reason, invalid-args maps, FastAPI's list, a
                           string; never a raw dict; capped at MAX_ERROR.
  case_may_send          — a send passes only as the `started` step of a `running` plan with the step's tool and
                           exact args; any other status / state / step / tool / arg → refused.
  case_card_and_report   — a send's card (rows from toolbox_sends.card_rows) shows Creator name + id (two
                           Creators sharing a nickname differ), audience, price, media ids and the FULL text; two
                           sends to different fan ids have different cards (every id listed); a write
                           shows its args, a reference as "from step <id>" (a list of them "N from step <id>"),
                           no media reads "none"; titles: a send's own title, else the tool name in Title Case;
                           report_text counts from the step states.

Run: ./venv/bin/python service/tests/test_ultra_decide.py   (exit 0 = green)
"""
from __future__ import annotations

import _harness  # noqa: F401 — MUST be first (temp DB env) even for a pure module

from datetime import datetime, timedelta  # noqa: E402
from typing import get_args  # noqa: E402

import toolbox_sends  # noqa: E402
import ultra_card as uc  # noqa: E402
import ultra_decide as ud  # noqa: E402

CA = "1000001"
OWNED = frozenset({CA})
LONG = "hey you " + "x" * 3000


def _plan(*steps, summary="Halloween mass"):
    return {"summary": summary, "steps": list(steps)}


READ = {"id": "pick", "tool": "vault_search", "args": {"account_id": CA, "query": "halloween"}}
WRITE = {"id": "folder", "tool": "of_folder_create",
         "args": {"account_id": CA, "name": "Halloween", "media_ids": ["$pick.data_only.list.0.id"]}}
SEND = {"id": "mass", "tool": "mass_send",
        "args": {"account_id": CA, "text": LONG, "user_lists": ["fans"], "price": 10, "media_files": [9301]}}
POST = {"id": "post", "tool": "post_create", "args": {"account_id": CA, "text": "new set", "price": 5,
                                                      "media_files": [9301], "previews": [9301]}}


def _errs(raw, owned=OWNED) -> list[tuple[str, str]]:
    try:
        ud.validate_plan(raw, owned)
    except ud.PlanError as e:
        return [(x["step"], x["field"]) for x in e.errors]
    raise AssertionError(f"accepted: {raw}")


def case_valid_plan() -> None:
    plan = ud.validate_plan(_plan(READ, WRITE, SEND, summary="  Halloween mass  "), OWNED)
    assert plan.summary == "Halloween mass" and [s["id"] for s in plan.steps] == ["pick", "folder", "mass"], plan
    assert plan.steps[2]["args"]["text"] == LONG and "refs" not in plan.steps[2]
    assert plan.steps[1]["refs"] == [{"at": ["media_ids", 0], "step": "pick", "path": "data_only.list.0.id"}]
    cheap = {**SEND, "args": {**SEND["args"], "text": "$5 off tonight", "user_ids": [1]}}
    assert ud.validate_plan(_plan(cheap), OWNED).steps[0]["args"]["text"] == "$5 off tonight"


def case_refused_table() -> None:
    send = lambda **kw: {**SEND, "args": {**SEND["args"], **kw}}  # noqa: E731
    table = [
        ("not an object", ["x"], [("", "plan")]),
        ("empty summary", _plan(READ, summary=" "), [("", "summary")]),
        ("no steps", _plan(), [("", "steps")]),
        ("too many", _plan(*[{**READ, "id": f"s{i}"} for i in range(ud.MAX_STEPS + 1)]), [("", "steps")]),
        ("unknown tool", _plan({"id": "a", "tool": "fan_dm", "args": {}}), [("a", "tool")]),
        ("bad args", _plan({**READ, "args": {"account_id": CA, "limit": "lots"}}), [("pick", "limit")]),
        ("extra arg", _plan({**READ, "args": {**READ["args"], "zz": 1}}), [("pick", "zz")]),
        ("send no audience", _plan(send(user_lists=[])), [("mass", "args")]),
        ("step key", _plan({**READ, "why": "x"}), [("", "steps")]),
        ("bad id", _plan({**READ, "id": "Pick!"}), [("Pick!", "id")]),
        ("dup id", _plan(READ, READ), [("pick", "id")]),
        ("unknown ref", _plan(READ, {**WRITE, "args": {**WRITE["args"], "media_ids": ["$nope.id"]}}),
         [("folder", "media_ids.0")]),
        ("forward ref", _plan(WRITE, READ), [("folder", "media_ids.0")]),
        ("self ref", _plan({**WRITE, "args": {**WRITE["args"], "media_ids": ["$folder.id"]}}),
         [("folder", "media_ids.0")]),
        ("ref account", _plan(READ, {**WRITE, "args": {**WRITE["args"], "account_id": "$pick.id"}}),
         [("folder", "account_id")]),
        ("foreign creator", _plan({**READ, "args": {"account_id": "1000002"}}), [("pick", "account_id")]),
    ]
    for name, raw, want in table:
        got = _errs(raw)
        assert all(w in got for w in want), (name, got, want)
    assert _errs(_plan(READ), frozenset()) == [("pick", "account_id")]  # no Creators: every account_id refused


def case_send_literal_only() -> None:
    ref = "$pick.data_only.list.0.id"
    mass_fields = {"account_id": ref, "text": ref, "price": ref, "media_files": [ref], "previews": [ref],
                   "user_lists": [ref], "user_ids": [ref], "excluded_user_lists": [ref], "scheduled_date": ref}
    post_fields = {"posted_at": ref, "expire_days": ref, "text": " $pick.id", "media_files": [" $pick.id"]}
    for base, fields in ((SEND, mass_fields), (POST, post_fields)):
        for field, value in fields.items():
            step = {**base, "args": {**base["args"], field: value}}
            got = _errs(_plan(READ, step))
            want = field + (".0" if isinstance(value, list) else "")
            assert (base["id"], want) in got, (field, got)
            try:
                ud.validate_plan(_plan(READ, step), OWNED)
            except ud.PlanError as e:
                assert any(x["error"] == ud.SEND_LITERAL for x in e.errors if x["field"] == want), e.errors


def case_substitute() -> None:
    results = {"pick": {"data_only": {"list": [{"id": 77}, {"id": 78}]}}, "folder": {"id": 9}}
    step = {"id": "add", "tool": "of_folder_add",
            "args": {"account_id": CA, "list_id": "$folder.id", "media_ids": ["$pick.data_only.list.1.id"]},
            "refs": [{"at": ["list_id"], "step": "folder", "path": "id"},
                     {"at": ["media_ids", 0], "step": "pick", "path": "data_only.list.1.id"}]}
    assert ud.substitute(step, results) == {"account_id": CA, "list_id": 9, "media_ids": [78]}
    assert step["args"]["list_id"] == "$folder.id"  # the stored plan is never mutated
    # Only recorded locations are filled: a string that reads like a reference elsewhere stays as written.
    loose = {"id": "f", "tool": "of_folder_create", "args": {"account_id": CA, "name": "$folder.id"}}
    assert ud.substitute(loose, results)["name"] == "$folder.id"
    spaced = ud.validate_plan(_plan(READ, {"id": "f", "tool": "of_folder_create",
                                           "args": {"account_id": CA, "name": " $pick.id"}}), OWNED).steps[1]
    assert "refs" not in spaced and ud.substitute(spaced, results)["name"] == " $pick.id"
    # A send fills its recorded refs only (validation records judge media / a rule's made folder, nothing else).
    send = {**SEND, "args": {**SEND["args"], "media_files": "$judge.ids"},
            "refs": [{"at": ["media_files"], "step": "judge", "path": "ids"}]}
    filled = ud.substitute(send, {**results, "judge": {"ids": [5, 6]}})
    assert filled["media_files"] == [5, 6] and filled["text"] == SEND["args"]["text"], filled
    for bad, path in (("$pick.data_only.list.5.id", "data_only.list.5.id"), ("$folder.name", "name"),
                      ("$later.id", "id")):
        sid = bad[1:].split(".")[0]
        try:
            ud.substitute({**loose, "refs": [{"at": ["name"], "step": sid, "path": path}]}, results)
        except KeyError as e:
            assert e.args[0] == bad, e
        else:
            raise AssertionError(bad)


def case_digest() -> None:
    a = {"summary": "s", "steps": [{"id": "a", "tool": "t", "args": {"x": 1, "y": "é"}}]}
    b = {"steps": [{"args": {"y": "é", "x": 1}, "tool": "t", "id": "a"}], "summary": "s"}
    assert ud.digest(a) == ud.digest(b) and len(ud.digest(a)) == 64
    assert ud.digest(a) != ud.digest({**a, "summary": "s2"})


def case_outcome() -> None:
    err = lambda st: {"error": {"status": st, "detail": "x"}}  # noqa: E731
    table = [("send", {"id": 1}, "done"), ("send", None, "uncertain"), ("send", err(502), "uncertain"),
             ("send", err(504), "uncertain"), ("send", err(500), "uncertain"), ("send", err(422), "failed"),
             ("send", err(409), "failed"), ("write", None, "uncertain"), ("write", err(502), "failed"),
             ("write", {"id": 1}, "done"), ("read", err(500), "failed"), ("read", None, "failed")]
    for effect, result, want in table:
        assert ud.outcome(effect, result) == want, (effect, result)


def case_states() -> None:
    t0 = datetime(2026, 11, 14, 12, 0)
    assert not ud.expired("awaiting_ok", t0, t0 + ud.OK_TTL)
    assert ud.expired("awaiting_ok", t0, t0 + ud.OK_TTL + timedelta(seconds=1))
    assert not ud.expired("running", t0, t0 + timedelta(days=1))
    assert ud.OK_TTL_TEXT == "10 minutes"
    assert set(get_args(ud.PlanStatus)) == ud.FINAL | ud.LIVE | {"awaiting_ok"}
    assert not ud.FINAL & ud.LIVE and ud.RUN_LIVE < ud.LIVE and "awaiting_ok" not in ud.LIVE
    assert set(get_args(ud.StepState)) == {"pending", "started", "needs_you", "done", "failed", "uncertain", "skipped"}
    states = [{"id": "a", "state": "done"}, {"id": "b", "state": "started"}, {"id": "c", "state": "pending"}]
    ended = [{"id": "f", "state": "failed", "error": "x"}, {"id": "u", "state": "uncertain"},
             {"id": "s", "state": "skipped"}]
    assert [s["state"] for s in ud.close(states)] == ["done", "uncertain", "skipped"]
    assert ud.close(ended) == ended
    status, after = ud.recovered("running", states)
    assert status == "interrupted" and [s["state"] for s in after] == ["done", "uncertain", "skipped"], after
    assert ud.recovered("done", states) == ("done", states)


def case_step_end() -> None:
    err = lambda st, d="nope": {"error": {"status": st, "detail": d}, "open_url": "/x"}  # noqa: E731
    table = [
        ("send", {"id": 4242, "text": "hi", "open_url": "/growth/smart-messages"},
         {"id": "s", "state": "done", "open_url": "/growth/smart-messages", "result": {"id": 4242}}),
        ("read", {"data_only": {"list": [{"id": 1}]}, "open_url": "/v"}, {"id": "s", "state": "done", "open_url": "/v"}),
        ("write", {"id": {"nested": 1}, "open_url": None}, {"id": "s", "state": "done", "open_url": None}),
        ("write", {"id": True, "open_url": None}, {"id": "s", "state": "done", "open_url": None}),
        ("write", {"id": "x" * 65, "open_url": None}, {"id": "s", "state": "done", "open_url": None}),
        ("send", None, {"id": "s", "state": "uncertain", "open_url": None, "error": ud.NO_ANSWER}),
        ("send", err(502, "upstream"), {"id": "s", "state": "uncertain", "open_url": "/x", "error": "upstream"}),
        ("write", err(422), {"id": "s", "state": "failed", "open_url": "/x", "error": "nope"}),
        ("send", {"id": 7, "open_url": None, "_user_ids_kept": {"asked": 2, "kept": 1}},
         {"id": "s", "state": "done", "open_url": None, "result": {"id": 7},
          "note": "sent to 1 of 2 fans by id: 1 skipped (opted out or already queued)"}),
        ("send", {"id": 7, "open_url": None, "_user_ids_kept": {"asked": 2, "kept": 2}},
         {"id": "s", "state": "done", "open_url": None, "result": {"id": 7}}),
        ("send", {"id": 7, "open_url": None, "_user_ids_kept": "junk"},
         {"id": "s", "state": "done", "open_url": None, "result": {"id": 7}}),
        ("write", {"error": {"status": 422, "detail": "no value for $a.b"}},
         {"id": "s", "state": "failed", "open_url": None, "error": "no value for $a.b"}),
    ]
    for effect, result, want in table:
        assert ud.step_end("s", effect, result) == want, (effect, result, ud.step_end("s", effect, result))
    assert len(ud.step_end("s", "write", err(500, "y" * 900))["error"]) == ud.MAX_ERROR
    up = {"upstream_status": 500, "upstream_body": '{"error":"fake OF 500"}'}
    assert ud.step_end("s", "send", err(502, up))["error"] == "OnlyFans answered 500: fake OF 500"


def case_oversize_send_done() -> None:
    """rwl cross-step M1: a send's 2xx too large to shape is still done with its id (never a synthetic 413)."""
    import toolbox_decide as td
    mass = ud.TOOLS["mass_send"]
    body = {"id": 777, "_user_ids_kept": {"asked": 3, "kept": 2},
            "media": [{"id": i, "src": "x" * 490, "thumb": "y" * 490} for i in range(50)]}
    out = td.shape_result(mass, 200, body)
    assert out == {"id": 777, "_user_ids_kept": {"asked": 3, "kept": 2}, "truncated": True}, out
    end = ud.step_end("s", "send", {**out, "open_url": "/growth/smart-messages"})
    assert end["state"] == "done" and end["result"] == {"id": 777} and "note" in end, end
    read = td.Tool("r", "r", "GET", "/x", td.NoArgs, "read")
    assert td.shape_result(read, 200, body)["error"]["status"] == 413  # a read still says narrow it


def case_error_text() -> None:
    table = [
        ({"upstream_status": 500, "upstream_body": '{"error":"fake OF 500"}'}, "OnlyFans answered 500: fake OF 500"),
        ({"upstream_status": 400, "upstream_body": '{"error":{"code":0,"message":"Please allow 10 seconds"}}'},
         "OnlyFans answered 400: Please allow 10 seconds"),
        ({"upstream_status": 503, "upstream_body": '{"message":"down"}'}, "OnlyFans answered 503: down"),
        ({"upstream_status": 502, "upstream_body": "<html>bad gateway</html>"},
         "OnlyFans answered 502: <html>bad gateway</html>"),
        ({"upstream_status": 500, "upstream_body": ""}, "OnlyFans answered 500"),
        ({"upstream_status": "proxy_unreachable", "upstream_body": "connect refused"},
         "The OnlyFans call failed (proxy unreachable): connect refused"),
        ({"detail": "invalid arguments", "errors": {"limit": "too big", "type": "bad"}},
         "invalid arguments: limit: too big; type: bad"),
        ({"detail": "OnlyFans answered with no post id"}, "OnlyFans answered with no post id"),
        ([{"loc": ["body", "price"], "msg": "must be >= 0"}], "price: must be >= 0"),
        ("plan refused\n  twice", "plan refused twice"),
        (None, ud.NO_ANSWER),
    ]
    for detail, want in table:
        assert ud.error_text(detail) == want, (detail, ud.error_text(detail))
    long = ud.error_text({"upstream_status": 500, "upstream_body": "z" * 5000})
    assert len(long) == ud.MAX_ERROR and long.startswith("OnlyFans answered 500: zzz"), long
    assert "{" not in ud.error_text({"upstream_status": 500, "upstream_body": '{"error":{"code":7}}'})


def case_may_send() -> None:
    plan = {"summary": "s", "steps": [{"id": "mass", "tool": "mass_send", "args": {"account_id": CA, "text": "hi"}}]}
    started = [{"id": "mass", "state": "started"}]
    args = {"account_id": CA, "text": "hi"}
    assert ud.may_send(plan, "running", started, "mass", "mass_send", args)
    table = [("awaiting_ok", started, "mass", "mass_send", args),
             ("done", started, "mass", "mass_send", args),
             ("running", [{"id": "mass", "state": "pending"}], "mass", "mass_send", args),
             ("running", [{"id": "mass", "state": "done"}], "mass", "mass_send", args),
             ("running", started, "other", "mass_send", args),
             ("running", started, "mass", "post_create", args),
             ("running", started, "mass", "mass_send", {**args, "text": "hi!"}),
             ("running", started, "mass", "mass_send", {**args, "user_ids": [1]})]
    for status, states, sid, tool, a in table:
        assert not ud.may_send(plan, status, states, sid, tool, a), (status, states, sid, tool, a)


def case_card_and_report() -> None:
    plan = ud.validate_plan(_plan(READ, WRITE, SEND), OWNED)
    cards = uc.card(plan, {CA: "Ava"})
    mass = cards[2]
    rows = dict(map(tuple, mass["rows"]))
    assert mass["effect"] == "send" and mass["text"] == LONG, mass
    assert rows == {"Creator": f"Ava ({CA})", "Audience": "lists fans", "Price": "$10.00", "Media": "1: 9301",
                    "When": "now"}, rows
    other = "1000002"  # m2: two Creators sharing a nickname get different cards
    twin = lambda aid: uc.card(ud.validate_plan(_plan({**SEND, "args": {**SEND["args"], "account_id": aid}}),  # noqa: E731
                                                OWNED | {other}), {CA: "Ava", other: "Ava"})[0]["rows"]
    assert twin(CA) != twin(other) and dict(map(tuple, twin(other)))["Creator"] == f"Ava ({other})"
    write = dict(map(tuple, cards[1]["rows"]))
    assert write["name"] == "Halloween" and cards[1]["effect"] == "write", write
    assert write["media_ids"] == "from step pick", write  # a one-item list of references: no JSON brackets
    assert [c["title"] for c in cards] == ["Vault Search", "OF Folder Create", "Mass message"], cards
    two = {**WRITE, "args": {**WRITE["args"], "media_ids": ["$pick.data_only.list.0.id", "$pick.data_only.list.1.id"]}}
    rows2 = dict(map(tuple, uc.card(ud.validate_plan(_plan(READ, two), OWNED), {})[1]["rows"]))
    assert rows2["media_ids"] == "2 from step pick", rows2
    mixed = {**WRITE, "args": {**WRITE["args"], "media_ids": [9301, "$pick.data_only.list.0.id"]}}
    rows3 = dict(map(tuple, uc.card(ud.validate_plan(_plan(READ, mixed), OWNED), {})[1]["rows"]))
    assert rows3["media_ids"] == '[9301, "from step pick"]', rows3  # a literal beside a reference: listed as is
    assert dict(map(tuple, cards[0]["rows"]))["query"] == "halloween"  # arg labels stay the arg names
    bare = toolbox_sends.card_rows("post", {"account_id": CA, "text": "hi"})
    assert dict(map(tuple, bare))["Media"] == "none", bare
    to = lambda ids: uc.card(ud.validate_plan(_plan({**SEND, "args": {**SEND["args"], "user_ids": ids}}),  # noqa: E731
                                              OWNED), {})[0]["rows"]
    assert to([111, 222]) != to([333, 444])
    assert dict(map(tuple, to([111, 222])))["Audience"] == "lists fans + 2 fan(s) by id: 111, 222"
    many = dict(map(tuple, to(list(range(1, 13)))))["Audience"]
    assert many.endswith("12 fan(s) by id: " + ", ".join(map(str, range(1, 13)))), many  # every id (M4)
    assert to(list(range(1, 13))) != to([*range(1, 11), 99, 12])  # the 11th id changed → a different card
    post = toolbox_sends.card_rows("post", {**POST["args"], "previews": [9301], "expire_days": 3,
                                            "posted_at": "2026-11-15T18:00:00+00:00"})
    assert post == [["Audience", "her feed (every subscriber)"], ["Price", "$5.00"], ["Media", "1: 9301"],
                    ["When", "2026-11-15T18:00:00+00:00"], ["Free previews", "1: 9301"],
                    ["Expires after", "3 day(s)"]], post
    states = [{"id": "pick", "state": "done", "open_url": "/growth/vault-pro"},
              {"id": "folder", "state": "done", "open_url": "/growth/vault-pro"},
              {"id": "mass", "state": "uncertain", "error": "no answer"}]
    line = uc.report_text(plan.summary, "failed", states)
    assert line == "Ultra plan failed: Halloween mass (2 of 3 steps done; mass uncertain)", line


if __name__ == "__main__":
    _harness.run()
