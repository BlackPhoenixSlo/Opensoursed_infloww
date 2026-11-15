#!/usr/bin/env python3
"""test_full_ai_mode_api — the Full AI page's Mode control (ticket 74, spec 04a: the flip gate).

`GET / PUT /admin/full-ai/mode` through `_harness.make_client()` sessions on the temp DB (Agency A's
owner and chatter, Agency B's Creator); the live job body through `run_once` with OF faked at
`ax._make_client` (`_of_fixtures.FakeOF`), Jev and the Writers' wire faked
(`_full_ai_live_helpers.world`). No network, no paid call, no live OF send.

  case_put_live_creates_one_rule      no rule → one enabled rule {"every_seconds": 300, "mode": "live"};
                                      live_rule = its id; GET live
  case_legacy_shadow_rule_in_place    enabled rule without mode reads shadow; PUT live updates that row
                                      (still one); PUT off → disabled, mode gone, GET off
  case_off_drops_the_queued_job       his DM queues a job (run_at ahead); PUT off; at claim the job drops:
                                      no OF call, no ai_decisions row, job not pending
  case_off_switch_wins_over_mode      Live + FULL_AI_CHAT_OFF: his DM gets no OF call and no row (the same
                                      setup without the switch replies: the control, its live row listed
                                      in GET /admin/full-ai/today, tagged live)
  case_rollback_on_creator_with_no_rule  Off on a Creator with no rule: 200, nothing enabled; FULL_AI_CHAT_OFF
                                      set then cleared reads back both ways (flip.md rollback 1-2)
  case_off_then_live_drops_the_old_job  Off then Live inside the reply wait: the job queued before Off is
                                      cancelled, never runs
  case_two_rules_of_the_kind          Live leaves one enabled; Off parks both, trigger {"every_seconds": 300}
  case_live_keeps_its_fans_list       while Live, a checkpoint PUT / rollback to no Fans list: 409; Off: 200
  case_blocker_read_fails_closed      the blocker read raising: GET 200 with one blocker, PUT live 409, Off 200
  case_refusals                       shadow / anything else 422; Agency B's Creator 403; chatter 403
                                      (the opt-in guard); nothing written
  case_live_blockers                  no Fans list / a Writer without a key / no TypeSafe key → 409 naming it,
                                      no rule written, GET lists them; all set → []
  case_shared_routes_never_turn_live  the rule editor's trigger edit, switch-on and re-enable of a parked Live
                                      rule: 409; switch-off stays open (reads off); `_validate_trigger` drops
                                      `mode` (fail closed: Shadow)
  case_interval_job_every_300s        `dispatch_plan.parse_trigger` reads the live trigger as a 300 s interval

Run: ./venv/bin/python service/tests/test_full_ai_mode_api.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import delete, select, update  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import runtime_switches  # noqa: E402
import tenant_keys  # noqa: E402
import webhook_dispatch as wd  # noqa: E402
from _full_ai_fixtures import _msg  # noqa: E402
from _full_ai_live_helpers import world  # noqa: E402
from automation_executor import run_once  # noqa: E402
from automation_rules_api import _validate_trigger  # noqa: E402
from automations import full_ai_live  # noqa: E402
from automations.full_ai_config import DEFAULTS  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AccountAiConfig, AiDecision, AutomationRule, Message, ScheduledJob  # noqa: E402
from dispatch_plan import parse_trigger  # noqa: E402

IDS = fx.seed_two_agencies()
AID = IDS["creator_a"]
THEIRS = IDS["creator_b"]
OWNER = fx.login_owner("agency_a_owner")
CHATTER = fx.login_chatter("chatter_a")
KIND = "full_ai_chat"
ROUTE = "/admin/full-ai/mode"
LIVE = {"every_seconds": 300, "mode": "live"}
KEYS = {"nanogpt": "sk-test-a", "openrouter": "sk-test-a", "deepseek": "sk-test-a", "typesafe": "sk-test-a"}
FANS_SET = {"include": [], "exclude": [4242]}


def _run(coro):
    return asyncio.run(coro)


async def _reset(*, fans: dict | None = None, keys: dict | None = None) -> None:
    """Creator A with no Full AI rule, no jobs / rows / messages; its checkpoint = DEFAULTS + `fans`
    (default: an exclude list set); the owner's keys = `keys` (default: every Writer + TypeSafe)."""
    async with get_session() as s:
        for m in (AutomationRule, ScheduledJob, AiDecision, Message, AccountAiConfig):
            q = delete(m).where(m.account_id == AID)
            await s.execute(q.where(AutomationRule.kind == KIND) if m is AutomationRule else q)
        s.add(AccountAiConfig(account_id=AID, full_ai_config_json=json.dumps(
            {"checkpoint": {**DEFAULTS, "fans": FANS_SET if fans is None else fans}})))
    await tenant_keys.set_keys(IDS["agency_a_owner"], {**dict.fromkeys(KEYS), **(KEYS if keys is None else keys)})
    if runtime_switches.on("FULL_AI_CHAT_OFF"):
        await runtime_switches.set_override("FULL_AI_CHAT_OFF", None, by="test")


async def _rules() -> list[AutomationRule]:
    async with get_session() as s:
        return list((await s.execute(select(AutomationRule).where(
            AutomationRule.account_id == AID, AutomationRule.kind == KIND).order_by(AutomationRule.id))).scalars())


async def _add_rule(trigger: dict, enabled: bool) -> int:
    async with get_session() as s:
        r = AutomationRule(account_id=AID, name="Full AI Chat", kind=KIND, trigger_json=json.dumps(trigger),
                           steps_json="{}", is_enabled=enabled)
        s.add(r)
        await s.flush()
        return r.id


def _get(client=OWNER, aid=AID):
    return client.get(f"{ROUTE}?account_id={aid}")


def _put(mode, client=OWNER, aid=AID):
    return client.put(ROUTE, json={"account_id": aid, "mode": mode})


async def _dm_and_claim(fan: int, mid: int, *, before_claim=None):
    """His DM lands (the hook queues the job), `before_claim()` runs, the job is made due and one
    run_once claims it. Returns (FakeOF, run result, the job row after)."""
    await _msg(AID, fan, mid, "in", "hey you, how was your day", datetime.utcnow() - timedelta(seconds=5))
    with world() as (fake, _jevs, _info, _fw):
        await wd.on_inbound_message(AID, fan, mid)
        async with get_session() as s:
            jobs = list((await s.execute(select(ScheduledJob).where(
                ScheduledJob.account_id == AID, ScheduledJob.kind == KIND,
                ScheduledJob.status == "pending"))).scalars())
        assert len(jobs) == 1, [(j.id, j.payload_json) for j in jobs]
        assert jobs[0].run_at > datetime.utcnow() - timedelta(seconds=1), jobs[0].run_at
        if before_claim is not None:
            await before_claim()
        async with get_session() as s:
            await s.execute(update(ScheduledJob).where(ScheduledJob.id == jobs[0].id)
                            .values(run_at=datetime.utcnow() - timedelta(seconds=1)))
        res = await run_once(AID, KIND)
    async with get_session() as s:
        job = await s.get(ScheduledJob, jobs[0].id)
    return fake, res, job


async def _decisions() -> list[AiDecision]:
    async with get_session() as s:
        return list((await s.execute(select(AiDecision).where(AiDecision.account_id == AID))).scalars())


def case_put_live_creates_one_rule():
    _run(_reset())
    assert _get().json()["mode"] == "off"
    r = _put("live")
    assert r.status_code == 200 and r.json()["mode"] == "live", r.text
    rules = _run(_rules())
    assert len(rules) == 1 and rules[0].is_enabled and json.loads(rules[0].trigger_json) == LIVE, rules
    assert _run(full_ai_live.live_rule(AID)) == rules[0].id
    assert _get().json() == {"mode": "live", "off_switch": False, "blockers": []}, _get().text


def case_legacy_shadow_rule_in_place():
    _run(_reset())
    rid = _run(_add_rule({"every_seconds": 86400}, True))
    assert _get().json()["mode"] == "shadow"
    assert _put("live").json()["mode"] == "live"
    rules = _run(_rules())
    assert [(r.id, r.is_enabled, json.loads(r.trigger_json)) for r in rules] == [(rid, True, LIVE)], rules
    r = _put("off")
    assert r.status_code == 200 and r.json()["mode"] == "off", r.text
    rules = _run(_rules())
    assert [(r.id, r.is_enabled, json.loads(r.trigger_json)) for r in rules] == [(rid, False, {"every_seconds": 300})]
    assert _run(full_ai_live.live_rule(AID)) is None and _get().json()["mode"] == "off"


def case_off_drops_the_queued_job():
    _run(_reset())
    assert _put("live").status_code == 200

    async def off():
        assert _put("off").status_code == 200
    fake, res, job = _run(_dm_and_claim(5101, 81001, before_claim=off))
    assert fake.sent == [], fake.sent
    assert _run(_decisions()) == []
    assert (job.status, job.last_error) == ("cancelled", "rule switched off"), (job.status, job.last_error)
    print(f"  off: job {job.id} -> {job.status} ({job.last_error}); run_once -> {res}")


def case_off_switch_wins_over_mode():
    # Control: the same setup without the switch replies (fans list emptied in the stored checkpoint after
    # the PUT, so the run reads no OF list: every Fan listed).
    async def go(switch: bool, fan: int, mid: int):
        await _reset()
        assert _put("live").status_code == 200
        async with get_session() as s:
            await s.execute(update(AccountAiConfig).where(AccountAiConfig.account_id == AID).values(
                full_ai_config_json=json.dumps({"checkpoint": {**DEFAULTS}})))
        if switch:
            await runtime_switches.set_override("FULL_AI_CHAT_OFF", True, by="test")
        try:
            fake, _res, _job = await _dm_and_claim(fan, mid)
            return fake.sent, await _decisions()
        finally:
            await runtime_switches.set_override("FULL_AI_CHAT_OFF", None, by="test")
    sent, rows = _run(go(False, 5201, 82001))
    assert sent and len(rows) == 1, (sent, rows)
    today = OWNER.get(f"/admin/full-ai/today?account_id={AID}").json()["rows"]   # the owner reads live Turns there
    assert [(r["fan_id"], r["test"], r["live"]) for r in today] == [("5201", False, True)], today
    assert _get().json()["off_switch"] is False
    sent, rows = _run(go(True, 5202, 82002))
    assert sent == [] and rows == [], (sent, [(r.status, r.route) for r in rows])


def case_rollback_on_creator_with_no_rule():
    # flip.md's rollback, steps 1-2 (step 3, redeploy the previous image, is AE only):
    # Mode Off on a Creator with no rule, then FULL_AI_CHAT_OFF set and cleared; each reads back.
    _run(_reset())
    r = _put("off")
    assert r.status_code == 200 and r.json()["mode"] == "off", r.text
    assert _run(_rules()) == [], _run(_rules())
    assert _run(full_ai_live.live_rule(AID)) is None
    try:
        _run(runtime_switches.set_override("FULL_AI_CHAT_OFF", True, by="test"))
        assert _get().json() == {"mode": "off", "off_switch": True, "blockers": []}, _get().text
    finally:
        _run(runtime_switches.set_override("FULL_AI_CHAT_OFF", None, by="test"))
    assert _get().json()["off_switch"] is False, _get().text
    print(f"  rollback: off -> {r.json()}; rules {[(x.id, x.is_enabled) for x in _run(_rules())]}")


def case_off_then_live_drops_the_old_job():
    # Off then Live again inside the reply wait: the job queued before Off never runs.
    _run(_reset())
    assert _put("live").status_code == 200

    async def off_then_live():
        assert _put("off").status_code == 200 and _put("live").status_code == 200
    fake, _res, job = _run(_dm_and_claim(5102, 81002, before_claim=off_then_live))
    assert fake.sent == [] and _run(_decisions()) == [], (fake.sent, _run(_decisions()))
    assert (job.status, job.last_error) == ("cancelled", "rule switched off"), (job.status, job.last_error)


def case_two_rules_of_the_kind():
    _run(_reset())
    a = _run(_add_rule({"every_seconds": 86400}, True))
    b = _run(_add_rule(LIVE, False))
    assert _put("live").status_code == 200
    rules = [(r.id, r.is_enabled) for r in _run(_rules())]
    assert sum(on for _, on in rules) == 1 and len(rules) == 2, rules
    assert _run(full_ai_live.live_rule(AID)) in (a, b)
    assert _put("off").status_code == 200
    rules = [(r.id, r.is_enabled, json.loads(r.trigger_json)) for r in _run(_rules())]
    assert rules == [(a, False, {"every_seconds": 300}), (b, False, {"every_seconds": 300})], rules


def case_live_keeps_its_fans_list():
    # D61 holds while Live: no config write may leave the checkpoint with no Fans list.
    _run(_reset())

    def put_ck(fans):
        rev = OWNER.get(f"/admin/full-ai/config?account_id={AID}").json()["rev"]
        return OWNER.put("/admin/full-ai/config/checkpoint", json={
            "account_id": AID, "checkpoint": {**DEFAULTS, "fans": fans}, "rev": rev})

    def rollback():
        rev = OWNER.get(f"/admin/full-ai/config?account_id={AID}").json()["rev"]
        return OWNER.post("/admin/full-ai/config/rollback", json={"account_id": AID, "rev": rev})
    assert _put("live").status_code == 200
    r = put_ck({"include": [], "exclude": []})
    assert r.status_code == 409 and "Fans list" in r.json()["detail"], r.text
    assert put_ck({"include": [9], "exclude": []}).status_code == 200      # another list: fine
    assert _put("off").status_code == 200
    assert put_ck({"include": [], "exclude": []}).status_code == 200       # Off: any config
    assert _put("live").status_code == 409
    assert rollback().status_code == 200 and _put("live").status_code == 200
    r = rollback()                                                          # back to the empty list
    assert r.status_code == 409 and "Fans list" in r.json()["detail"], r.text
    assert _get().json()["mode"] == "live"


def case_blocker_read_fails_closed():
    import full_ai_api
    _run(_reset())
    real = full_ai_api.full_ai_turn.stored_config

    async def boom(_aid):
        raise RuntimeError("db down")
    full_ai_api.full_ai_turn.stored_config = boom
    try:
        g = _get()
        assert g.status_code == 200 and g.json()["mode"] == "off", g.text
        assert len(g.json()["blockers"]) == 1 and g.json()["blockers"][0].startswith("Couldn't check"), g.text
        r = _put("live")
        assert r.status_code == 409 and "Couldn't check" in r.json()["detail"], r.text
        assert _run(_rules()) == []
        assert _put("off").status_code == 200
    finally:
        full_ai_api.full_ai_turn.stored_config = real


def case_refusals():
    _run(_reset())
    for bad in ("shadow", "on", "", None):
        r = _put(bad)
        assert r.status_code == 422, (bad, r.status_code, r.text)
    assert _put("live", aid=THEIRS).status_code == 403
    assert _get(aid=THEIRS).status_code == 403
    r = _put("live", client=CHATTER)
    assert r.status_code == 403 and r.json() == {"detail": "Your role does not allow Full AI Chat"}, r.text
    assert _run(_rules()) == []


def case_live_blockers():
    for kw, want in (
        ({"fans": {"include": [], "exclude": []}}, "No Fans list"),
        ({"keys": {**KEYS, "openrouter": None}}, "No key for openrouter"),
        ({"keys": {**KEYS, "deepseek": None, "nanogpt": None}}, "No key for deepseek, nanogpt"),
    ):
        _run(_reset(**kw))
        r = _put("live")
        assert r.status_code == 409 and want in r.json()["detail"], (kw, r.status_code, r.text)
        assert _run(_rules()) == [], kw
        blockers = _get().json()["blockers"]
        assert len(blockers) == 1 and blockers[0].startswith(want), blockers
    _run(_reset(fans={"include": [7], "exclude": []}))
    assert _get().json()["blockers"] == [] and _put("live").status_code == 200


def case_no_typesafe_key():
    import llm_providers
    real = llm_providers.typesafe_key
    llm_providers.typesafe_key = lambda: ""
    try:
        _run(_reset(keys={**KEYS, "typesafe": None}))
        r = _put("live")
        assert r.status_code == 409 and "No TypeSafe key" in r.json()["detail"], r.text
        assert _run(_rules()) == []
    finally:
        llm_providers.typesafe_key = real


def case_shared_routes_never_turn_live():
    _run(_reset())
    assert _put("live").status_code == 200
    rid = _run(_rules())[0].id
    r = OWNER.patch(f"/admin/automation-rules/{rid}", json={"trigger": {"every_seconds": 600}})
    assert r.status_code == 409 and "/admin/full-ai/mode" in r.text, r.text
    r = OWNER.post("/admin/automation-rules/switch", json={"account_id": AID, "kind": KIND, "enable": True})
    assert r.status_code == 409, r.text
    # Off through the shared routes stays open; the parked rule keeps its mode but reads off and
    # cannot be woken there.
    r = OWNER.patch(f"/admin/automation-rules/{rid}", json={"is_enabled": False})
    assert r.status_code == 200, r.text
    assert _get().json()["mode"] == "off" and _run(full_ai_live.live_rule(AID)) is None
    for call in (lambda: OWNER.patch(f"/admin/automation-rules/{rid}", json={"is_enabled": True}),
                 lambda: OWNER.post("/admin/automation-rules/switch",
                                    json={"account_id": AID, "kind": KIND, "enable": True}),
                 lambda: OWNER.post("/admin/automation-rules", json={
                     "account_id": AID, "kind": KIND, "every_seconds": 300, "is_enabled": True})):
        r = call()
        assert r.status_code == 409, r.text
    assert _get().json()["mode"] == "off"
    r = OWNER.post("/admin/automation-rules/switch", json={"account_id": AID, "kind": KIND, "enable": False})
    assert r.status_code == 200, r.text
    # The editor's trigger shape never carries `mode` (fail closed: an edit would read Shadow).
    assert _validate_trigger(LIVE) == {"every_seconds": 300}
    try:
        _validate_trigger("live")
        raise AssertionError("a non-dict trigger passed")
    except HTTPException as e:
        assert e.status_code == 422


def case_interval_job_every_300s():
    t = parse_trigger(LIVE)
    assert t is not None and getattr(t, "every", None) == 300, t


_harness.run()
