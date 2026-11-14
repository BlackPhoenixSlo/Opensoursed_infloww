#!/usr/bin/env python3
"""Ultra automation-rule sends (step 5B): auto_mass / auto_story make a switched-on mass_premade / auto_stories
rule over POST /admin/automation-rules, only as a started step of a running plan.

Cases:
  case_body              — the flat args → create_rule's body (kind, every_seconds, nested payload, is_enabled
                           true; unset knobs left out, 0 kept); bad args refused per field (a price finer than
                           cents on any paid send: the card shows cents).
  case_card              — every pinned arg on the card (Creator, audience, price, folder, interval, unsend /
                           delete); the Auto mass text in full; an Auto story carries no text; hours_to_live
                           omitted / 0 / 24: stored args = card = request.
  case_plan_refusals     — a judge's picks as an Auto mass's media → refused (the tool has no media_files); the
                           send chain refuses an off-platform text (step + stage named); a clean text passes; a
                           step after a rule step refused (RULES_LAST, also in the planner prompt + MCP text).
  case_rule_made_from_plan — no plan step → 403, no rule; the started step of a running plan → one ON rule per
                           tool with the exact trigger + payload, result id = the rule id, open_url its page;
                           a check on an answer with no ON rule fails (pure).
  case_folder_ref_pure   — a rule's folder = "$<earlier of_folder_create>.id" (same Creator): refs, card row,
                           substitute, started `resolved`, may_send; a read / other tool / other account / other
                           path / later step / a ref in any other field refused.
  case_folder_then_rule_runs — create folder → auto_story through the executor: the made id lands in the rule.

Seeded straight into the temp DB; no network, no OnlyFans call (making a rule calls none).

Run: ./venv/bin/python service/tests/test_ultra_rule_sends.py   (exit 0 = green)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import json  # noqa: E402

from sqlalchemy import delete, select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import toolbox  # noqa: E402
import toolbox_decide as td  # noqa: E402
import toolbox_sends as ts  # noqa: E402
import ultra_card as uc  # noqa: E402
import ultra_decide as ud  # noqa: E402
import ultra_run  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AutomationRule, UltraPlan  # noqa: E402

IDS = fx.seed_two_agencies()
CA, OWNER_A = IDS["creator_a"], IDS["agency_a_owner"]
A = fx.login_owner("agency_a_owner")
COOKIE_A = {"Cookie": "; ".join(f"{k}={v}" for k, v in A.cookies.items())}
OWNED = frozenset({CA})
MASS = {"account_id": CA, "every_hours": 24, "text": "new set just dropped", "media_folder_id": 77,
        "media_count": 2, "price": 9.5, "user_lists": ["fans", "following"], "excluded_user_lists": ["123"],
        "online_only": True, "unsend_after_hours": 6}
PAID = {"account_id": CA, "text": "hi", "media_files": [5], "price": 9.99, "user_lists": ["fans"]}
STORY = {"account_id": CA, "every_hours": 12, "folder_id": 88, "per_run": 2, "hours_to_live": 0}


def _plan(*steps):
    return {"summary": "rules", "steps": list(steps)}


def case_body() -> None:
    req = td.build_request(ud.TOOLS["auto_mass"], td.validate_args(ud.TOOLS["auto_mass"], MASS))
    assert (req.method, req.path, req.query, req.headers) == (
        "POST", "/admin/automation-rules", {"account_id": CA}, {"X-Account-Id": CA}), req
    assert req.json == {"account_id": CA, "kind": "mass_premade", "every_seconds": 86400, "is_enabled": True,
                        "payload": {"messages": [{"text": "new set just dropped", "media_folder_id": 77,
                                                  "media_count": 2, "price": 9.5, "user_lists": ["fans", "following"],
                                                  "excluded_user_lists": ["123"], "online_only": True,
                                                  "unsend_after_hours": 6}]}}, req.json
    free = td.validate_args(ud.TOOLS["auto_mass"], {**MASS, "price": 0, "online_only": False,
                                                    "unsend_after_hours": None, "excluded_user_lists": []})
    assert td.build_request(ud.TOOLS["auto_mass"], free).json["payload"]["messages"][0] == {
        "text": "new set just dropped", "media_folder_id": 77, "media_count": 2, "user_lists": ["fans", "following"],
        "price": 0}  # 0 is sent; unset knobs (None / [] / False) left out
    story = td.build_request(ud.TOOLS["auto_story"], td.validate_args(ud.TOOLS["auto_story"], STORY)).json
    assert story == {"account_id": CA, "kind": "auto_stories", "every_seconds": 43200, "is_enabled": True,
                     "payload": {"folder_id": 88, "per_run": 2, "hours_to_live": 0}}, story  # 0 = keep: sent
    for tool, args, field in [("auto_mass", {**MASS, "user_lists": []}, "user_lists"),
                              ("auto_mass", {**MASS, "every_hours": 0}, "every_hours"),
                              ("auto_mass", {k: v for k, v in MASS.items() if k != "media_folder_id"}, "media_folder_id"),
                              ("auto_mass", {**MASS, "media_files": [1]}, "media_files"),
                              ("auto_mass", {**MASS, "text": ""}, "text"),
                              ("auto_mass", {**MASS, "price": 9.999}, "price"),  # m4: card shows cents
                              ("mass_send", {**PAID, "price": 9.995}, "price"),
                              ("mass_send", {**PAID, "price": float("inf")}, "price"),
                              ("post_create", {k: v for k, v in PAID.items() if k != "user_lists"} | {"price": 0.001},
                               "price"),
                              ("auto_story", {**STORY, "folder_id": 0}, "folder_id"),
                              ("auto_story", {**STORY, "text": "hi"}, "text")]:
        try:
            td.validate_args(ud.TOOLS[tool], args)
        except td.ArgsError as e:
            assert field in e.errors, (tool, field, e.errors)
        else:
            raise AssertionError((tool, field, "accepted"))
    for price in (9.99, 3.07, 199.1, 12):  # inside the $3-$200 band;  # whole cents pass (float noise ignored)
        assert td.validate_args(ud.TOOLS["mass_send"], {**PAID, "price": price})["price"] == price


def case_card() -> None:
    plan = ud.validate_plan(_plan({"id": "m", "tool": "auto_mass", "args": MASS},
                                  {"id": "s", "tool": "auto_story", "args": STORY}), OWNED)
    m, s = uc.card(plan, {CA: "Creator A"})
    assert (m["effect"], m["title"], m["text"]) == ("send", "Auto mass", "new set just dropped"), m
    assert m["rows"] == [["Creator", f"Creator A ({CA})"], ["Audience", "lists fans, following, minus lists 123, online now only"],
                         ["Price", "$9.50"], ["Media", "2 random photo(s) per run from vault folder 77"],
                         ["When", "within a minute of this step starting, then every 24 h until switched off"],
                         ["Unsend after", "6 h"]], m["rows"]
    assert "text" not in s and s["title"] == "Auto story", s
    assert s["rows"] == [["Creator", f"Creator A ({CA})"], ["Audience", "her stories (every subscriber)"],
                         ["Media", "2 random photo(s) per run from vault folder 88"],
                         ["When", "within a minute of this step starting, then every 12 h until switched off"],
                         ["Deleted after", "not deleted by the app (OnlyFans expires stories on its own)"]], s["rows"]
    # M3: omitted / 0 / 24 → the stored args, the card and the request carry the same hours_to_live
    for given, want, words in [(None, 24, "24 h"), (0, 0, "not deleted"), (24, 24, "24 h")]:
        args = {k: v for k, v in STORY.items() if k != "hours_to_live"} | (
            {} if given is None else {"hours_to_live": given})
        p = ud.validate_plan(_plan({"id": "s", "tool": "auto_story", "args": args}), OWNED)
        stored = p.steps[0]["args"]
        body = td.build_request(ud.TOOLS["auto_story"], td.validate_args(ud.TOOLS["auto_story"], stored)).json
        row = dict(uc.card(p, {})[0]["rows"])["Deleted after"]
        assert stored["hours_to_live"] == body["payload"]["hours_to_live"] == want and words in row, (given, body, row)
        assert p.raw()["steps"][0]["args"]["hours_to_live"] == want  # what the sha covers


async def case_plan_refusals() -> None:
    find = {"id": "find", "tool": "vault_search", "args": {"account_id": CA, "query": "red"}}
    judge = {"id": "pick", "question": "red ones", "candidates": "$find.data_only.list", "pick_n": 2, "confirm": False}
    for raw, (step, field, words) in [
            (_plan(find, judge, {"id": "m", "tool": "auto_mass", "args": {**MASS, "media_files": "$pick.ids"}}),
             ("m", "media_files", "literal")),
            (_plan({"id": "m", "tool": "auto_mass", "args": {**MASS, "text": "add me on telegram"}}),
             ("m", "text", "stage offplatform"))]:
        try:
            await ultra_run.checked(raw, OWNED)
        except ud.PlanError as e:
            assert any(x["step"] == step and x["field"] == field and words in x["error"] for x in e.errors), e.errors
        else:
            raise AssertionError((step, field, "accepted"))
    # M4: a rule goes live at once, so rule steps end the plan (only other rule steps may follow)
    later = {"id": "f", "tool": "of_folders_list", "args": {"account_id": CA}}
    try:
        ud.validate_plan(_plan({"id": "m", "tool": "auto_mass", "args": MASS},
                               {"id": "s", "tool": "auto_story", "args": STORY}, later), OWNED)
    except ud.PlanError as e:
        assert e.errors == [{"step": "m", "field": "tool", "error": f"{ud.RULES_LAST}: move f before it"}], e.errors
    else:
        raise AssertionError("a step after a rule accepted")
    import mcp_api
    import ultra_plan_decide as upd
    assert ud.RULES_LAST in upd.SYSTEM_PROMPT and ud.RULES_LAST in mcp_api.PROPOSE_DESCRIPTION
    ud.validate_plan(_plan(later, {"id": "m", "tool": "auto_mass", "args": MASS}), OWNED)
    ok = await ultra_run.checked(_plan({"id": "m", "tool": "auto_mass", "args": MASS},
                                       {"id": "s", "tool": "auto_story", "args": STORY}), OWNED)
    assert ok.steps[0]["args"]["text"] == MASS["text"] and ok.steps[1]["args"] == STORY, ok.steps
    assert ok.steps[0]["args"] == {**MASS}, ok.steps  # every knob already explicit: defaults add nothing


async def _rules() -> list[AutomationRule]:
    async with get_session() as s:
        return list((await s.execute(select(AutomationRule).where(AutomationRule.account_id == CA)
                                     .order_by(AutomationRule.id))).scalars())


async def case_rule_made_from_plan() -> None:
    creds = toolbox.Creds(cookie=COOKIE_A["Cookie"], forwarded_host="app.example.com", forwarded_proto="https")
    plan = _plan({"id": "m", "tool": "auto_mass", "args": MASS}, {"id": "s", "tool": "auto_story", "args": STORY})
    pid = "f" * 32
    r = await toolbox.call(ud.TOOLS["auto_mass"], MASS, creds)
    assert r["error"] == {"status": 403, "detail": toolbox.SEND_REFUSED}, r
    assert await _rules() == []
    try:
        for sid, name, args, page, kind, every, payload in [
                ("m", "auto_mass", MASS, "/growth/auto-mass", "mass_premade", 86400,
                 ts.rule_body("auto_mass", MASS)["payload"]),
                ("s", "auto_story", STORY, "/growth/auto-story", "auto_stories", 43200,
                 {"folder_id": 88, "per_run": 2, "hours_to_live": 0})]:
            async with get_session() as s:
                await s.execute(delete(UltraPlan).where(UltraPlan.id == pid))
                s.add(UltraPlan(id=pid, owner_user_id=OWNER_A, source="mcp", plan_json=json.dumps(plan),
                                plan_sha256=ud.digest(plan), status="running",
                                step_states=json.dumps([{"id": x, "state": "started" if x == sid else "done"}
                                                        for x in ("m", "s")])))
            r = await toolbox.call(ud.TOOLS[name], args, creds, plan_step=f"{pid}:{sid}")
            assert "error" not in r and r["open_url"] == f"https://app.example.com{page}", r
            rule = (await _rules())[-1]
            assert (rule.kind, rule.is_enabled, json.loads(rule.trigger_json), json.loads(rule.steps_json)) == (
                kind, True, {"every_seconds": every}, payload), (rule.kind, rule.trigger_json, rule.steps_json)
            assert ud.step_end(sid, "send", r)["result"] == {"id": rule.id}, r
        assert [x.kind for x in await _rules()] == ["mass_premade", "auto_stories"]
    finally:
        async with get_session() as s:
            await s.execute(delete(UltraPlan).where(UltraPlan.id == pid))
            await s.execute(delete(AutomationRule).where(AutomationRule.account_id == CA))
    assert ts.check_rule(MASS, {"id": 3, "is_enabled": True}) is None
    for body in ({"id": 3, "is_enabled": False}, {"is_enabled": True}, [], "ok"):
        assert ts.check_rule(MASS, body), body


MAKE = {"id": "mk", "tool": "of_folder_create", "args": {"account_id": CA, "name": "Spooky"}}
RULE_FOLDER = {"id": "s", "tool": "auto_story", "args": {**STORY, "folder_id": "$mk.id"}}


def case_folder_ref_pure() -> None:
    """M1: a rule's folder may be "$<earlier of_folder_create>.id" on the same Creator; nothing else is a ref."""
    plan = ud.validate_plan(_plan(MAKE, RULE_FOLDER), OWNED)
    s = plan.steps[1]
    assert s["refs"] == [{"at": ["folder_id"], "step": "mk", "path": "id"}], s
    assert dict(uc.card(plan, {CA: "Creator A"})[1]["rows"])["Media"] == (
        "2 random photo(s) per run from folder created in step mk (Spooky)")
    mass = ud.validate_plan(_plan(MAKE, {"id": "m", "tool": "auto_mass",
                                         "args": {**MASS, "media_folder_id": "$mk.id"}}), OWNED)
    assert mass.steps[1]["refs"] == [{"at": ["media_folder_id"], "step": "mk", "path": "id"}]
    args = ud.substitute(s, {"mk": {"id": 555}})
    assert args["folder_id"] == 555 and ud.started(s, args) == {"id": "s", "state": "started",
                                                                 "resolved": {"folder_id": 555}}
    pj, mk = plan.as_json(), {"id": "mk", "state": "done", "result": {"id": 555}}
    started = ud.started(s, args)
    assert ud.may_send(pj, "running", [mk, started], "s", "auto_story", args)
    assert not ud.may_send(pj, "running", [mk, started], "s", "auto_story", {**args, "folder_id": 556})
    assert not ud.may_send(pj, "running", [{**mk, "result": {"id": 556}}, started], "s", "auto_story", args)
    assert not ud.may_send(pj, "running", [{**mk, "state": "failed"}, started], "s", "auto_story", args)
    both = frozenset({CA, IDS["creator_b"]})
    for steps, field, words in [
            ([{"id": "fl", "tool": "of_folders_list", "args": {"account_id": CA}},
              {**RULE_FOLDER, "args": {**STORY, "folder_id": "$fl.id"}}], "folder_id", "of_folder_create"),
            ([{"id": "add", "tool": "of_folder_add", "args": {"account_id": CA, "list_id": 5, "media_ids": [1]}},
              {**RULE_FOLDER, "args": {**STORY, "folder_id": "$add.id"}}], "folder_id", "of_folder_create"),
            ([{**MAKE, "args": {**MAKE["args"], "account_id": IDS["creator_b"]}}, RULE_FOLDER],
             "folder_id", "this step's account_id"),
            ([MAKE, {**RULE_FOLDER, "args": {**STORY, "folder_id": "$mk.name"}}], "folder_id", "of_folder_create"),
            ([RULE_FOLDER, MAKE], "folder_id", "of_folder_create"),  # a later step is no earlier one
            ([MAKE, {**RULE_FOLDER, "args": {**STORY, "folder_id": 88, "per_run": "$mk.id"}}], "per_run", "literal"),
            ([MAKE, {"id": "m", "tool": "auto_mass", "args": {**MASS, "text": "$mk.id"}}], "text", "literal")]:
        try:
            ud.validate_plan(_plan(*steps), both)
        except ud.PlanError as e:
            assert any(x["field"] == field and words in x["error"] for x in e.errors), (steps, e.errors)
        else:
            raise AssertionError(f"accepted: {steps}")


class _FolderOF:
    def create_vault_list(self, name):
        return {"id": 555, "name": name}


async def case_folder_then_rule_runs() -> None:
    """M1 through the executor: the folder step's id lands in the ON rule; `resolved` records it."""
    import automation_executor
    real, automation_executor._make_client = automation_executor._make_client, lambda *_a, **_k: _FolderOF()
    creds = toolbox.Creds(cookie=COOKIE_A["Cookie"], forwarded_host="app.example.com", forwarded_proto="https")
    try:
        out = await ultra_run.propose(_plan(MAKE, RULE_FOLDER), OWNER_A, OWNED, "mcp")
        pid = out["plan_id"]
        async with get_session() as s:
            sha = (await s.get(UltraPlan, pid)).plan_sha256
        await ultra_run.approve(pid, OWNER_A, sha, creds)
        await ultra_run._TASKS[pid]
        async with get_session() as s:
            row = await s.get(UltraPlan, pid)
        states = json.loads(row.step_states)
        assert row.status == "done", (row.status, states)
        assert states[0]["result"] == {"id": 555} and states[1]["resolved"] == {"folder_id": 555}, states
        rule = (await _rules())[-1]
        assert rule.kind == "auto_stories" and json.loads(rule.steps_json)["folder_id"] == 555, rule.steps_json
    finally:
        automation_executor._make_client = real
        async with get_session() as s:
            await s.execute(delete(AutomationRule).where(AutomationRule.account_id == CA))


if __name__ == "__main__":
    _harness.run()
