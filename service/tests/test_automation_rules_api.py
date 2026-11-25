#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import ast  # noqa: E402
import inspect  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select  # noqa: E402

import automation_rules_api as api  # noqa: E402 — module under test
from automations import _customs  # noqa: E402 — the customs floor the catalog must mirror
from automation_rules_api import (  # noqa: E402
    KindSwitch, RuleCreate, RulePatch, _validate_payload_for_kind, create_rule,
    delete_rule, ensure_kind_rule, list_kinds, list_rules, run_now, switch_kind,
    update_rule,
)
from db.engine import get_session  # noqa: E402
from db.models import Account, AutomationRule, Message, ScheduledJob  # noqa: E402


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))



async def case_create_then_list():
    aid = "acc_ar_create"
    await _seed_account(aid)

    out = await create_rule(RuleCreate(
        account_id=aid, kind="welcome_chatter_for_info", name="Daytime chat",
        every_seconds=300, payload={"limit": 40, "dry_run": False},
    ))
    assert out["id"] and out["kind"] == "welcome_chatter_for_info", out
    assert out["is_enabled"] is True, out
    assert out["every_seconds"] == 300, out
    assert out["payload"] == {"limit": 40, "dry_run": False}, out
    assert out["last_run"] is None, "no run has happened yet"
    assert out["next_due_at"] is not None, out

    listed = await list_rules(account_id=aid)
    rules = listed["rules"]
    assert len(rules) == 1 and rules[0]["id"] == out["id"], listed
    assert rules[0]["name"] == "Daytime chat", rules[0]


async def case_list_counts_smart_message_sends():
    from datetime import datetime
    aid, other = "acc_ar_sent", "acc_ar_sent_other"
    for a in (aid, other):
        await _seed_account(a)
    async with get_session() as s:
        for kind in ("send_welcome", "purchase_followup", "birthday_message", "nudge_online"):
            s.add(AutomationRule(account_id=aid, name=kind, kind=kind,
                                 trigger_json='{"every_seconds": 300}', steps_json="{}",
                                 is_enabled=False))
        n = 0
        def out(acc, fan, ak):
            nonlocal n
            n += 1
            s.add(Message(account_id=acc, fan_id=fan, message_id=7_000 + n, direction="out",
                          body="x", automation_kind=ak, created_at=datetime.utcnow()))
        for fan in (1, 2):
            for _ in range(3):
                out(aid, fan, "welcome")
        out(aid, 1, "purchase_followup")
        out(aid, 2, "purchase_followup")
        out(aid, 3, "nudge_online")
        out(other, 1, "birthday_message")
    rules = {r["kind"]: r for r in (await list_rules(account_id=aid))["rules"]}
    assert rules["send_welcome"]["sent"] == 2, rules["send_welcome"]
    assert rules["purchase_followup"]["sent"] == 2, rules["purchase_followup"]
    assert rules["birthday_message"]["sent"] == 0, rules["birthday_message"]
    assert "sent" not in rules["nudge_online"], rules["nudge_online"]



async def case_toggle_and_edit():
    aid = "acc_ar_edit"
    await _seed_account(aid)
    created = await create_rule(RuleCreate(
        account_id=aid, kind="send_welcome", every_seconds=120,
    ))
    rid = created["id"]

    patched = await update_rule(rid, RulePatch(
        is_enabled=False, every_seconds=900,
        payload={"max_welcomes": 10}, name="Slow welcomes",
    ))
    assert patched["is_enabled"] is False, patched
    assert patched["every_seconds"] == 900, patched
    assert patched["payload"] == {"max_welcomes": 10}, patched
    assert patched["name"] == "Slow welcomes", patched
    assert patched["next_due_at"] is None, patched

    again = await update_rule(rid, RulePatch(is_enabled=True))
    assert again["is_enabled"] is True, again
    assert again["every_seconds"] == 900, "interval unchanged by partial patch"
    assert again["payload"] == {"max_welcomes": 10}, again



async def case_run_now_enqueues_job():
    aid = "acc_ar_run"
    await _seed_account(aid)
    created = await create_rule(RuleCreate(
        account_id=aid, kind="gen_info", every_seconds=600,
        payload={"limit": 50},
    ))
    rid = created["id"]

    from starlette.requests import Request
    from db.models import Employee
    async with get_session() as s:
        emp = Employee(display_name="op_run_now")
        s.add(emp)
        await s.flush()
        emp_id = emp.id
    req = Request({"type": "http", "headers": [(b"x-employee-id", str(emp_id).encode())]})
    res = await run_now(rid, req)
    assert res["enqueued_job_id"] and res["kind"] == "gen_info", res

    async with get_session() as s:
        jobs = (await s.execute(
            select(ScheduledJob).where(ScheduledJob.account_id == aid,
                                       ScheduledJob.kind == "gen_info")
        )).scalars().all()
        assert len(jobs) == 1, ("one job enqueued", jobs)
        job = jobs[0]
        assert job.status == "pending", job.status
        assert job.rule_id == rid, "job linked back to its rule"
        assert job.created_by_employee_id == emp_id, ("run-now is the operator's", job.created_by_employee_id)
        import json
        assert json.loads(job.payload_json) == {"limit": 50}, job.payload_json

    listed = await list_rules(account_id=aid)
    row = next(r for r in listed["rules"] if r["id"] == rid)
    assert row["has_pending_job"] is True, row


async def case_follow_up_step_is_not_queued():
    import json
    from datetime import datetime, timedelta
    aid = "acc_ar_fu_queued"
    await _seed_account(aid)
    out = await create_rule(RuleCreate(account_id=aid, kind="gen_info", every_seconds=3600))
    past = datetime.utcnow() - timedelta(minutes=1)
    async with get_session() as s:
        s.add(ScheduledJob(account_id=aid, kind="gen_info", run_at=past, status="pending",
                           rule_id=out["id"], payload_json=json.dumps(
                               {"follow_up": {"fan_id": 7, "steps": [], "step": 1}, "_followup": True})))

    async def badge() -> bool:
        return next(r for r in (await list_rules(account_id=aid))["rules"]
                    if r["id"] == out["id"])["has_pending_job"]

    assert await badge() is False, "a follow-up step is not the rule queued"
    async with get_session() as s:
        s.add(ScheduledJob(account_id=aid, kind="gen_info", run_at=past, status="pending",
                           rule_id=out["id"], payload_json="{}"))
    assert await badge() is True


async def case_next_due_clock_and_limits():
    from datetime import datetime, timedelta
    from db.models import AutomationRun
    aid = "acc_ar_next_clock"
    await _seed_account(aid)
    from dispatch_plan import Clock, next_due
    now = datetime.utcnow()
    slot = (now + timedelta(hours=2)).strftime("%H:%M")
    t0 = datetime.utcnow()
    clock = await create_rule(RuleCreate(account_id=aid, kind="auto_posts", payload={"dry_run": True},
                                         trigger={"daily_at": [slot], "tz_offset_minutes": 0}))
    t1 = datetime.utcnow()
    got = datetime.fromisoformat(clock["next_due_at"])
    want = {next_due(Clock((slot,), 0, None), None, t) for t in (t0, t1)}
    assert got in want, (got, want)
    assert clock["every_seconds"] is None, clock

    async with get_session() as s:
        bad = AutomationRule(account_id=aid, name="bad tz", kind="auto_posts", steps_json="{}",
                             trigger_json='{"daily_at": ["09:00"], "tz_offset_minutes": "x"}')
        s.add(bad)
        await s.flush()
        bad_id = bad.id
    capped = await create_rule(RuleCreate(account_id=aid, kind="nudge_online",
                                          trigger={"every_seconds": 600, "max_runs": 2}))
    rows = {r["id"]: r for r in (await list_rules(account_id=aid))["rules"]}
    assert rows[bad_id]["next_due_at"] is None, rows[bad_id]
    assert rows[capped["id"]]["next_due_at"] is not None, "no runs yet: due"
    async with get_session() as s:
        for _ in range(2):
            s.add(AutomationRun(account_id=aid, kind="nudge_online", status="ok", started_at=now))
    rows = {r["id"]: r for r in (await list_rules(account_id=aid))["rules"]}
    assert rows[capped["id"]]["next_due_at"] is None, rows[capped["id"]]



async def case_delete():
    aid = "acc_ar_del"
    await _seed_account(aid)
    created = await create_rule(RuleCreate(
        account_id=aid, kind="apply_profiles", every_seconds=1800,
    ))
    rid = created["id"]

    res = await delete_rule(rid)
    assert res["deleted"] == rid, res

    listed = await list_rules(account_id=aid)
    assert all(r["id"] != rid for r in listed["rules"]), "rule gone from list"

    try:
        await delete_rule(rid)
        assert False, "expected 404 on second delete"
    except HTTPException as e:
        assert e.status_code == 404, e



async def case_validation():
    aid = "acc_ar_valid"
    await _seed_account(aid)

    try:
        await create_rule(RuleCreate(account_id=aid, kind="not_a_real_kind",
                                     every_seconds=300))
        assert False, "expected 422 for unknown kind"
    except HTTPException as e:
        assert e.status_code == 422, e

    try:
        await create_rule(RuleCreate(account_id=aid, kind="gen_info",
                                     every_seconds=5))
        assert False, "expected 422 for tiny interval"
    except HTTPException as e:
        assert e.status_code == 422, e

    try:
        api._validate_payload([1, 2, 3])
        assert False, "expected 422 for list payload"
    except HTTPException as e:
        assert e.status_code == 422, e


async def case_quiet_hours_default_off_set_clear():
    aid = "acc_ar_quiet"
    await _seed_account(aid)

    created = await create_rule(RuleCreate(
        account_id=aid, kind="welcome_chatter_for_info", every_seconds=300))
    assert created["quiet_hours"] is None, created
    rid = created["id"]

    patched = await update_rule(rid, RulePatch(quiet_hours=[22, 6]))
    assert patched["quiet_hours"] == [22, 6], patched

    again = await update_rule(rid, RulePatch(is_enabled=False))
    assert again["quiet_hours"] == [22, 6], again

    cleared = await update_rule(rid, RulePatch(quiet_hours=[0, 0]))
    assert cleared["quiet_hours"] is None, cleared

    for bad in ([25, 0], [5]):
        try:
            await create_rule(RuleCreate(account_id=aid, kind="welcome_chatter_for_info",
                                         every_seconds=300, quiet_hours=bad))
            assert False, f"expected 422 for quiet_hours={bad}"
        except HTTPException as e:
            assert e.status_code == 422, e



async def case_typed_payload_validation():
    aid = "acc_ar_typed"
    await _seed_account(aid)

    out = await create_rule(RuleCreate(
        account_id=aid, kind="welcome_chatter_for_info", every_seconds=300,
        payload={"limit": 40.0, "dry_run": False, "force_ids": [1, 2.0],
                 "future_knob": "keep-me"},
    ))
    p = out["payload"]
    assert p["limit"] == 40 and isinstance(p["limit"], int), p
    assert p["force_ids"] == [1, 2], p
    assert p["future_knob"] == "keep-me", p

    bad_payloads = [
        {"limit": 0},
        {"limit": "lots"},
        {"dry_run": "yes"},
        {"force_ids": 5},
        {"force_ids": [1, "x"]},
    ]
    for bad in bad_payloads:
        try:
            await create_rule(RuleCreate(account_id=aid, kind="welcome_chatter_for_info",
                                         every_seconds=300, payload=bad))
            assert False, f"expected 422 for payload={bad}"
        except HTTPException as e:
            assert e.status_code == 422, (bad, e)

    rid = out["id"]
    try:
        await update_rule(rid, RulePatch(payload={"limit": -3}))
        assert False, "expected 422 patching a sub-min int"
    except HTTPException as e:
        assert e.status_code == 422, e
    again = await update_rule(rid, RulePatch(payload={"limit": 5, "max_replies": 3}))
    assert again["payload"] == {"limit": 5, "max_replies": 3}, again



async def case_kinds_catalog():
    resp = await list_kinds()
    kinds = {k["kind"] for k in resp["kinds"]}
    for expected in ("welcome_chatter_for_info", "send_welcome", "gen_info",
                     "apply_profiles", "process_old_fans",
                     "scrape_chats", "send_followup", "send_mass_message",
                     "reply_mass_funnel", "unsend_messages"):
        assert expected in kinds, (expected, kinds)
    for k in resp["kinds"]:
        want = api._CREATE_PAYLOAD.get(k["kind"])
        if want is None:
            continue
        leaked = [key for key, val in k.items() if val == want]
        assert not leaked, (k["kind"], leaked)

    _SURFACES = {"rules", "brain", "ready_made", "settings", "internal"}
    for k in resp["kinds"]:
        assert "label" in k and "recurring" in k and "knobs" in k, k
        assert k.get("surface") in _SURFACES, k
        for kn in k["knobs"]:
            assert "widget" in kn and "key" in kn and "type" in kn, kn

    rules_surface = {k["kind"] for k in resp["kinds"] if k.get("surface") == "rules"}
    assert rules_surface == {
        "welcome_chatter_for_info", "autoreply", "send_followup", "gen_info",
        "apply_profiles", "scrape_chats", "process_old_fans",
        "reply_mass_funnel", "customs_watch",
    }, rules_surface

    cw = {k["kind"]: k for k in resp["kinds"]}["customs_watch"]
    floor = next((kn for kn in cw["knobs"] if kn["key"] == "min_cents"), None)
    assert floor is not None, cw
    assert floor["type"] == "int" and floor.get("default") == _customs.MIN_CENTS, floor
    assert "widget" in floor, floor

    by_kind = {k["kind"]: k for k in resp["kinds"]}
    ai = by_kind["welcome_chatter_for_info"]
    assert ai.get("cadence_default_s") == 60, ai
    ht = next((kn for kn in ai["knobs"] if kn["key"] == "history_tail"), None)
    assert ht is not None and ht["type"] == "int" and ht.get("default") == 40, ai["knobs"]
    for kind_, want in (("send_followup", 3600),
                        ("gen_info", 86400), ("scrape_chats", 86400),
                        ("apply_profiles", 3600),
                        ("reply_mass_funnel", 120)):
        assert by_kind[kind_].get("cadence_default_s") == want, by_kind[kind_]

    assert ai.get("example"), ai
    for kind_ in ("process_old_fans", "scrape_chats", "reply_mass_funnel"):
        assert by_kind[kind_].get("group") == "advanced", by_kind[kind_]
    assert by_kind["welcome_chatter_for_info"].get("group") != "advanced", by_kind["welcome_chatter_for_info"]




async def case_ensure_kind_rule():
    aid = "acc_ar_ensure"
    await _seed_account(aid)

    async def _rows(kind="welcome_chatter_for_info"):
        async with get_session() as s:
            return (await s.execute(select(AutomationRule).where(
                AutomationRule.account_id == aid,
                AutomationRule.kind.in_((kind, "of_ai_chat"))
            ).order_by(AutomationRule.id))).scalars().all()

    async def _sync(**kw):
        async with get_session() as s:
            return await ensure_kind_rule(s, aid, kw.pop("kind", "welcome_chatter_for_info"), **kw)

    assert await _sync(enable=True) == "created"
    rows = await _rows()
    assert len(rows) == 1 and rows[0].is_enabled, rows
    assert '"every_seconds": 60' in rows[0].trigger_json, rows[0].trigger_json
    assert rows[0].name == api._CATALOG["welcome_chatter_for_info"]["label"], rows[0].name
    assert rows[0].steps_json == "{}", rows[0].steps_json

    assert await _sync(enable=True) == "unchanged"
    assert len(await _rows()) == 1

    await update_rule(rows[0].id, RulePatch(name="Nights only", every_seconds=900))

    assert await _sync(enable=False) == "parked"
    assert await _sync(enable=True) == "updated"
    rows = await _rows()
    assert len(rows) == 1, rows
    assert rows[0].is_enabled and rows[0].name == "Nights only", rows[0].name
    assert '"every_seconds": 900' in rows[0].trigger_json, rows[0].trigger_json

    assert await _sync(enable=True, every_seconds=1800, steps={"with_image": False},
                       name="Nudge online") == "updated"
    rows = await _rows()
    assert '"every_seconds": 1800' in rows[0].trigger_json, rows[0].trigger_json
    assert rows[0].name == "Nudge online" and "with_image" in rows[0].steps_json

    async with get_session() as s:
        s.add(AutomationRule(account_id=aid, name="second ticker", kind="welcome_chatter_for_info",
                             trigger_json='{"every_seconds": 60}', steps_json="{}",
                             is_enabled=True))
    assert len(await _rows()) == 2
    assert await _sync(enable=False) == "parked"
    assert not any(r.is_enabled for r in await _rows()), await _rows()
    assert await _sync(enable=False) == "unchanged"

    legacy_aid = "acc_ar_ensure_legacy"
    await _seed_account(legacy_aid)
    async with get_session() as s:
        s.add(AutomationRule(account_id=legacy_aid, name="pre-rename", kind="of_ai_chat",
                             trigger_json='{"every_seconds": 60}', steps_json="{}",
                             is_enabled=False))
    async with get_session() as s:
        action = await ensure_kind_rule(s, legacy_aid, "welcome_chatter_for_info", enable=True)
    assert action == "updated", action
    async with get_session() as s:
        legacy = (await s.execute(select(AutomationRule).where(
            AutomationRule.account_id == legacy_aid))).scalars().all()
    assert len(legacy) == 1 and legacy[0].is_enabled, legacy



async def case_switch_create_uses_catalog_defaults():
    import json

    aid = "acc_ar_switch_defaults"
    await _seed_account(aid)

    async def _rows(kind):
        async with get_session() as s:
            return (await s.execute(select(AutomationRule).where(
                AutomationRule.account_id == aid,
                AutomationRule.kind == kind))).scalars().all()

    out = await switch_kind(KindSwitch(account_id=aid, kind="apply_profiles", enable=True))
    assert out["action"] == "created", out
    rows = await _rows("apply_profiles")
    assert len(rows) == 1 and rows[0].is_enabled, rows
    assert json.loads(rows[0].steps_json) == {"push_to_of": True}, rows[0].steps_json
    assert '"every_seconds": 3600' in rows[0].trigger_json, rows[0].trigger_json
    assert rows[0].name == api._CATALOG["apply_profiles"]["label"], rows[0].name

    await update_rule(rows[0].id, RulePatch(payload={"push_to_of": False}))
    await switch_kind(KindSwitch(account_id=aid, kind="apply_profiles", enable=False))

    out = await switch_kind(KindSwitch(account_id=aid, kind="apply_profiles", enable=True))
    assert out["action"] == "updated", out
    rows = await _rows("apply_profiles")
    assert len(rows) == 1 and rows[0].is_enabled, rows
    assert json.loads(rows[0].steps_json) == {"push_to_of": False}, rows[0].steps_json

    out = await switch_kind(KindSwitch(account_id=aid, kind="gen_info", enable=True))
    assert out["action"] == "created", out
    gen = await _rows("gen_info")
    assert '"every_seconds": 86400' in gen[0].trigger_json, gen[0].trigger_json
    assert json.loads(gen[0].steps_json) == {}, gen[0].steps_json

    knobs = {k["key"]: k for k in api._CATALOG["apply_profiles"]["knobs"]}
    assert "default" not in knobs["push_to_of"], knobs["push_to_of"]

    aid2 = "acc_ar_switch_defaults_explicit"
    await _seed_account(aid2)
    async with get_session() as s:
        assert await ensure_kind_rule(s, aid2, "apply_profiles", enable=True,
                                      steps={"limit": 25}) == "created"
    async with get_session() as s:
        row = (await s.execute(select(AutomationRule).where(
            AutomationRule.account_id == aid2))).scalars().one()
    assert json.loads(row.steps_json) == {"limit": 25}, row.steps_json


async def case_switch_kind_route():
    aid = "acc_ar_switch"
    await _seed_account(aid)

    out = await switch_kind(KindSwitch(account_id=aid, kind="autoreply", enable=True))
    assert out["action"] == "created" and out["kind"] == "autoreply", out

    async with get_session() as s:
        rows = (await s.execute(select(AutomationRule).where(
            AutomationRule.account_id == aid))).scalars().all()
    assert len(rows) == 1 and rows[0].is_enabled, rows

    out = await switch_kind(KindSwitch(account_id=aid, kind="autoreply", enable=False))
    assert out["action"] == "parked", out
    async with get_session() as s:
        rows = (await s.execute(select(AutomationRule).where(
            AutomationRule.account_id == aid))).scalars().all()
    assert len(rows) == 1 and not rows[0].is_enabled, rows

    out = await switch_kind(KindSwitch(account_id=aid, kind="of_ai_chat", enable=True))
    assert out["kind"] == "welcome_chatter_for_info", out

    try:
        await switch_kind(KindSwitch(account_id=aid, kind="not_a_kind", enable=True))
        raise AssertionError("unknown kind must 422")
    except HTTPException as e:
        assert e.status_code == 422, e



_UNCATALOGUED_ON_PURPOSE = {
    "send_welcome": {
        "test_fan",
        "test_name",
        "pace_open_quiet_s",
        "pace_gap_quiet_s",
        "guard_hours", "new_max_inbound", "new_max_outbound",
        "follow_up",
    },
    "auto_follow": set(),
}


async def case_every_knob_the_automation_reads_is_catalogued():
    import importlib
    import re

    for kind, exempt in _UNCATALOGUED_ON_PURPOSE.items():
        meta = api._CATALOG.get(kind)
        assert meta is not None, f"{kind} must have a catalog entry"
        mod = importlib.import_module(f"automations.{kind}")
        with open(mod.__file__) as fh:
            src = fh.read()
        reads = set(re.findall(
            r"""payload\.get\(\s*["']([A-Za-z_][A-Za-z0-9_]*)["']""", src))
        for helper in ("_int_knob", "_on_unless_off", "bool_knob"):
            reads |= set(re.findall(
                helper + r"""\(\s*payload\s*,\s*["']([A-Za-z_][A-Za-z0-9_]*)["']""",
                src))
        declared = {k["key"] for k in meta.get("knobs", [])}
        missing = sorted(reads - declared - exempt)
        assert not missing, (
            f"{kind} reads {missing} from its payload but declares them nowhere "
            f"in _CATALOG. Add a knob entry (hint + type + default matching the "
            f"code's read-default), or add the key to "
            f"_UNCATALOGUED_ON_PURPOSE['{kind}'] with a comment saying why.")

        assert not (declared - reads), (
            f"{kind} declares {sorted(declared - reads)} in _CATALOG but the "
            f"module never reads them")


_BOOL_DEFAULT_MISMATCH_ON_PURPOSE = {
    ("send_welcome", "time_only"): (
        "Catalog True (stamped at rule CREATION), sender False (an absent "
        "key must keep meaning what it meant before the knob existed, or sixteen "
        "legacy rules become clock-only retroactively). The TODO at the read site "
        "in send_welcome.run names the two one-way fixes. Do not close it here."),
}


_BOOL_READ_UNCLASSIFIABLE = {
    ("nudge_online", "with_image"): (
        "TWO-LEVEL default: `bool_knob(payload, 'with_image', "
        "bool_knob(cfg, 'with_image', True))`. The rule payload layers over the "
        "ACCOUNT config, so what a stored `null` resolves to depends on the "
        "account row, not on a constant: with `cfg.with_image = false` it "
        "resolves False while the catalog and every UI surface say True. The "
        "conversion itself is correct at both levels — the earlier version of "
        "this check regexed out the INNERMOST literal and certified 'null ⇒ "
        "True', which is only the answer when the account cfg is silent. Pinned "
        "instead, both levels and all four cells, by "
        "test_nudge_online.case_with_image_layers_the_payload_over_the_account_cfg."),
}


class _Unclassifiable(Exception):
    pass


def _resolve_object(mod, node):
    if isinstance(node, ast.Constant):
        return node.value
    try:
        if isinstance(node, ast.Name):
            return getattr(mod, node.id)
        if isinstance(node, ast.Attribute):
            return getattr(_resolve_object(mod, node.value), node.attr)
        if isinstance(node, ast.Subscript):
            return _resolve_object(mod, node.value)[_resolve_object(mod, node.slice)]
    except (AttributeError, KeyError, IndexError, TypeError) as e:
        raise _Unclassifiable(
            f"`{ast.unparse(node)}` is not resolvable at module level ({e})") from e
    raise _Unclassifiable(f"`{ast.unparse(node)}` is not a constant expression")


def _call_name(node: ast.Call) -> str | None:
    f = node.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return None


def _is_bool_knob(mod, node: ast.Call) -> bool:
    if _call_name(node) == "bool_knob":
        return True
    from automations import _common
    try:
        return _resolve_object(mod, node.func) is _common.bool_knob
    except _Unclassifiable:
        return False


_BOOL_KEY_PASSTHROUGH = {"_on_unless_off"}


def _const_str(node) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


class _Site:

    def __init__(self, lineno: int, form: str, *, resolves=None, problem=None):
        self.lineno, self.form, self.resolves, self.problem = lineno, form, resolves, problem


def _bool_read_sites(mod, tree: ast.AST, key: str) -> tuple[list[_Site], list[int]]:
    sites: list[_Site] = []
    dynamic_key_lines: list[int] = []
    passthrough = [(n.lineno, n.end_lineno) for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name in _BOOL_KEY_PASSTHROUGH]
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if _is_bool_knob(mod, node):
            if len(node.args) < 2:
                continue
            if _const_str(node.args[1]) is None:
                if not any(lo <= node.lineno <= (hi or lo) for lo, hi in passthrough):
                    dynamic_key_lines.append(node.lineno)
                continue
            if _const_str(node.args[1]) != key:
                continue
            form = ast.unparse(node)
            if len(node.args) < 3:
                sites.append(_Site(node.lineno, form,
                                   problem="read with no default at all"))
                continue
            default = node.args[2]
            if isinstance(default, ast.Call) and _call_name(default) == "bool_knob":
                sites.append(_Site(node.lineno, form, problem=(
                    "the default is another `bool_knob(...)`, so the "
                    "null-resolution depends on a second dict, not on a constant")))
                continue
            try:
                sites.append(_Site(node.lineno, form, resolves=bool(_resolve_object(mod, default))))
            except _Unclassifiable as e:
                sites.append(_Site(node.lineno, form, problem=str(e)))
        elif name == "_on_unless_off":
            if len(node.args) >= 2 and _const_str(node.args[1]) == key:
                sites.append(_Site(node.lineno, ast.unparse(node), resolves=True))
        elif name == "get" and isinstance(node.func, ast.Attribute):
            if not node.args or _const_str(node.args[0]) != key:
                continue
            form = ast.unparse(node)
            if len(node.args) >= 2:
                sites.append(_Site(node.lineno, form, problem=(
                    f"`.get({key!r}, <default>)` resolves a stored `null` to None, "
                    f"i.e. FALSE, no matter what the default says")))
            else:
                sites.append(_Site(node.lineno, form, resolves=False))
    return sites, dynamic_key_lines


async def case_every_catalogued_bool_honours_its_default():
    import importlib

    from automations import _common, send_welcome

    for dflt in (True, False):
        assert _common.bool_knob({}, "k", dflt) is dflt
        assert _common.bool_knob({"k": None}, "k", dflt) is dflt
        assert _common.bool_knob(None, "k", dflt) is dflt
        assert _common.bool_knob({"k": True}, "k", dflt) is True
        assert _common.bool_knob({"k": False}, "k", dflt) is False
    assert "bool_knob(payload, key, not test_mode())" in \
        inspect.getsource(send_welcome._on_unless_off)

    checked = 0
    for kind, meta in api._CATALOG.items():
        bools = [k for k in meta.get("knobs", []) if k.get("type") == "bool"]
        if not bools:
            continue
        mod = importlib.import_module(f"automations.{kind}")
        with open(mod.__file__) as fh:
            tree = ast.parse(fh.read(), filename=mod.__file__)
        for knob in bools:
            key = knob["key"]
            declared = bool(knob.get("default", False))
            sites, dynamic = _bool_read_sites(mod, tree, key)

            assert sites, (
                f"{kind}.{key} is catalogued as a bool but this check cannot "
                f"find the read. "
                + (f"The module reads bool knobs through a NON-LITERAL key at "
                   f"line(s) {dynamic} — a descriptor table this walk cannot "
                   f"follow per-key. Pin the table's own contract in that "
                   f"module's suite and record ({kind!r}, {key!r}) in "
                   f"_BOOL_READ_UNCLASSIFIABLE. "
                   if dynamic else
                   "If the read moved, teach `_bool_read_sites` the new form — "
                   "do not delete the knob from the walk."))

            sites = sites + [
                _Site(ln, "bool_knob(…, <non-literal key>, …)", problem=(
                    "a bool knob is read through a key this walk cannot resolve, "
                    "so it cannot tell whether that read also answers for this "
                    "knob (a descriptor table has this shape)"))
                for ln in dynamic]

            bad = [s for s in sites if s.problem]
            excuse = _BOOL_READ_UNCLASSIFIABLE.get((kind, key))
            if bad:
                assert excuse, (
                    f"{kind}.{key}: this check will not certify "
                    + "; ".join(f"line {s.lineno} `{s.form}` — {s.problem}" for s in bad)
                    + f". Read it as `_common.bool_knob(payload, {key!r}, "
                    f"{declared})` with a constant default, or record "
                    f"({kind!r}, {key!r}) in _BOOL_READ_UNCLASSIFIABLE saying "
                    f"what pins it instead.")
                checked += 1
                continue
            assert not excuse, (
                f"{kind}.{key} is now classifiable ({[s.form for s in sites]}) — "
                f"drop its _BOOL_READ_UNCLASSIFIABLE entry so the walk checks it.")

            answers = {s.resolves for s in sites}
            assert len(answers) == 1, (
                f"{kind}.{key} is read {len(sites)} ways that disagree about a "
                f"stored `null`: "
                + "; ".join(f"line {s.lineno} `{s.form}` ⇒ {s.resolves}" for s in sites)
                + ". One knob, one read.")
            resolved = answers.pop()

            excused = _BOOL_DEFAULT_MISMATCH_ON_PURPOSE.get((kind, key))
            if excused:
                assert resolved != declared, (
                    f"{kind}.{key} no longer mismatches — drop its "
                    f"_BOOL_DEFAULT_MISMATCH_ON_PURPOSE entry.")
                checked += 1
                continue
            assert resolved == declared, (
                f"{kind}.{key}: the catalog shows default={declared} and every UI "
                f"surface reads absent-or-null as that, but the automation "
                f"resolves a stored `null` to {resolved} at "
                + ", ".join(f"line {s.lineno} `{s.form}`" for s in sites)
                + f". Use `_common.bool_knob(payload, {key!r}, {declared})`, or "
                f"record a deliberate mismatch in "
                f"_BOOL_DEFAULT_MISMATCH_ON_PURPOSE.")
            checked += 1
    assert checked >= 25, f"only {checked} catalogued bools walked"


async def case_bool_knob_matches_the_typescript_half():
    import json
    import os as _os

    from automations import _common

    path = _os.path.join(_os.path.dirname(__file__), "fixtures", "bool_knob_cases.json")
    with open(path) as fh:
        fixture = json.load(fh)
    cases = fixture["cases"]
    assert len(cases) >= 14, f"the shared table shrank to {len(cases)} rows"

    for c in cases:
        payload = {} if c.get("absent") else {"k": c["value"]}
        got = _common.bool_knob(payload, "k", c["default"])
        assert got is c["expect"], (
            f"{c['name']}: bool_knob({payload}, 'k', {c['default']}) is {got}, "
            f"the shared table says {c['expect']}. If the RULE changed, change "
            f"the fixture and app/lib/boolKnob.ts with it — one of the two "
            f"halves moving alone is the defect this table exists to catch.")

    stored = [c.get("value") for c in cases if not c.get("absent")]
    for v in (None, 0, "", [], {}):
        assert any(x == v and type(x) is type(v) for x in stored), (
            f"the shared table no longer covers a stored {v!r} — that is one of "
            f"the values python and JavaScript answer differently for")


async def case_a_null_for_a_catalogued_knob_is_dropped_at_the_boundary():
    aid = "acc_rules_null_boundary"
    await _seed_account(aid)

    created = await create_rule(RuleCreate(
        account_id=aid, kind="auto_follow", every_seconds=3600, payload={
            "money_gate": None,
            "daily_cap": None,
            "action": None,
            "dry_run": False,
            "some_future_key": None,
        }))
    stored = created["payload"]
    for key in ("money_gate", "daily_cap", "action"):
        assert key not in stored, (key, stored)
    assert stored["dry_run"] is False, stored
    assert "some_future_key" in stored and stored["some_future_key"] is None, stored

    from automations._common import bool_knob
    assert bool_knob(stored, "money_gate", True) is True, stored


async def case_money_and_follow_knob_defaults_match_the_code():
    from automations import send_welcome

    knobs = {k["key"]: k for k in api._CATALOG["send_welcome"]["knobs"]}
    assert knobs["follow_back"]["default"] is send_welcome._FOLLOW_BACK_DEFAULT
    assert (knobs["follow_back_gate"]["default"]
            is send_welcome._FOLLOW_BACK_GATE_DEFAULT)
    for key, dflt in (("follow_back", send_welcome._FOLLOW_BACK_DEFAULT),
                      ("follow_back_gate", send_welcome._FOLLOW_BACK_GATE_DEFAULT)):
        assert send_welcome.bool_knob({}, key, dflt) is dflt, key
        assert send_welcome.bool_knob({key: None}, key, dflt) is dflt, key
        assert send_welcome.bool_knob({key: False}, key, dflt) is False, key
    _was_test_mode = os.environ.pop("CHATTERLY_TEST_MODE", None)
    try:
        for key in ("stop_on_reply", "human_pace"):
            assert knobs[key]["default"] is send_welcome._on_unless_off({}, key), key
        os.environ["CHATTERLY_TEST_MODE"] = "1"
        for key in ("stop_on_reply", "human_pace"):
            assert send_welcome._on_unless_off({}, key) is False, key
            for off in ("0", "false", "no", "off", "", "  "):
                os.environ["CHATTERLY_TEST_MODE"] = off
                assert send_welcome._on_unless_off({}, key) is True, (key, off)
            os.environ["CHATTERLY_TEST_MODE"] = "1"
            assert send_welcome._on_unless_off({key: True}, key) is True, key
            assert send_welcome._on_unless_off({key: False}, key) is False, key
    finally:
        if _was_test_mode is None:
            os.environ.pop("CHATTERLY_TEST_MODE", None)
        else:
            os.environ["CHATTERLY_TEST_MODE"] = _was_test_mode

    af = {k["key"]: k for k in api._CATALOG["auto_follow"]["knobs"]}
    assert af["money_gate"]["type"] == "bool" and af["money_gate"]["default"] is True
    try:
        _validate_payload_for_kind("auto_follow", {"money_gate": "false"})
        raise AssertionError("money_gate must reject a string")
    except HTTPException as e:
        assert e.status_code == 422, e
    assert _validate_payload_for_kind("auto_follow", {}) == {}


async def case_next_due_ignores_one_shot_runs_of_the_kind():
    from datetime import datetime, timedelta
    from db.models import AutomationRun
    aid = "acc_ar_next_due"
    await _seed_account(aid)
    out = await create_rule(RuleCreate(
        account_id=aid, kind="auto_posts", every_seconds=86400,
        payload={"dry_run": True}))
    fired = datetime.utcnow() - timedelta(hours=20)
    async with get_session() as s:
        s.add(ScheduledJob(account_id=aid, kind="auto_posts", payload_json="{}",
                           run_at=fired, status="done", rule_id=out["id"],
                           created_at=fired))
        s.add(ScheduledJob(account_id=aid, kind="auto_posts", payload_json="{}",
                           run_at=datetime.utcnow(), status="done"))
        s.add(AutomationRun(account_id=aid, kind="auto_posts", status="ok",
                            started_at=datetime.utcnow()))
    rule = next(r for r in (await list_rules(account_id=aid))["rules"]
                if r["id"] == out["id"])
    want = fired + timedelta(seconds=86400)
    got = datetime.fromisoformat(rule["next_due_at"])
    assert abs((got - want).total_seconds()) < 1, (got, want)



_harness.run(
    case_create_then_list,
    case_list_counts_smart_message_sends,
    case_toggle_and_edit,
    case_run_now_enqueues_job,
    case_follow_up_step_is_not_queued,
    case_next_due_clock_and_limits,
    case_delete,
    case_validation,
    case_quiet_hours_default_off_set_clear,
    case_typed_payload_validation,
    case_kinds_catalog,
    case_every_knob_the_automation_reads_is_catalogued,
    case_every_catalogued_bool_honours_its_default,
    case_bool_knob_matches_the_typescript_half,
    case_a_null_for_a_catalogued_knob_is_dropped_at_the_boundary,
    case_money_and_follow_knob_defaults_match_the_code,
    case_ensure_kind_rule,
    case_switch_create_uses_catalog_defaults,
    case_switch_kind_route,
    case_next_due_ignores_one_shot_runs_of_the_kind,
)
