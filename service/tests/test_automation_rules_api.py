#!/usr/bin/env python3
"""
automation_rules_api — CRUD routes for the Automations control surface.

Drives the route coroutines directly (no HTTP) against the temp DB. Auth is a
no-op for unauthed test calls (assert_account_owned returns early), so we pass
account_id explicitly and exercise the real validation + persistence.

  case_create_then_list:
      create a rule → it persists with the right trigger/payload and shows up
      in the per-account list, enriched (every_seconds, payload, no run yet).
  case_toggle_and_edit:
      PATCH flips is_enabled, rewrites the interval + payload; reads back.
  case_run_now_enqueues_job:
      POST run-now inserts ONE pending scheduled_jobs row for (account, kind)
      carrying the rule's payload + rule_id — the executor's normal queue.
  case_follow_up_step_is_not_queued:
      only a fan's Smart Messages follow-up step pending (job_queue's
      `_FOLLOW_UP_JOB`) -> the badge is not "queued", as the materializer's busy
      gate does not see it; the rule's own due job still is.
  case_next_due_clock_and_limits:
      next_due_at is dispatch_plan.next_due: a daily_at rule shows its slot (it
      used to be null), a bad tz_offset_minutes row shows none and never raises,
      a rule at its max_runs shows none.
  case_delete:
      DELETE removes the row; a follow-up list no longer shows it.
  case_validation:
      unknown kind → 422; sub-tick interval → 422; non-object payload → 422.
  case_kinds_catalog:
      the kind catalog lists every registered automation (incl. scrape_chats).
  case_ensure_kind_rule:
      the switch a settings tab's "Enabled" box drives: create once at the
      CATALOG cadence, wake rather than duplicate, park EVERY row on off, never
      stamp on a cadence/name the caller did not send, and find a row still
      stored under a retired kind name.
  case_switch_create_uses_catalog_defaults:
      a switch-CREATED row is furnished from the catalog — payload as well as
      name and cadence — while a row that already exists is woken and never
      re-stamped with those defaults.
  case_switch_kind_route:
      the one-request switch the tabs POST: on/off in a single write, a retired
      kind name resolves to the live rule, an unknown kind is a 422.
  case_every_knob_the_automation_reads_is_catalogued:
      THE SEAM CHECK — every `payload.get` literal in send_welcome / auto_follow
      has a _CATALOG entry (and vice versa), so a knob can't ship with no typing
      and no UI surface. Exemptions are named in _UNCATALOGUED_ON_PURPOSE.
  case_money_and_follow_knob_defaults_match_the_code:
      the catalog's shown default matches the sender's read-default for the
      money-adjacent knobs, money_gate is TYPED (a string 422s), and a catalog
      default is display-only — never stamped onto a payload at save.
  case_every_catalogued_bool_honours_its_default:
      THE CLASS CHECK — every `type: "bool"` knob in EVERY kind resolves a
      stored `null` to the default the catalog shows. This is what stops the
      `bool(payload.get(k, True))` defect reappearing at a sixth site.

Run: ./venv/bin/python service/tests/test_automation_rules_api.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

# These cases test feature logic, not the account gate (that is
# test_account_isolation_gate's job). They reach `/admin` routes or
# `assert_account_owned` with no session, which fails closed (401) since
# 3b30b486. This is the documented escape hatch (read per call), scoped to this
# test process.
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


# ── create → list ─────────────────────────────────────────────────────

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
    # enabled + has cadence → a next-due estimate is projected.
    assert out["next_due_at"] is not None, out

    listed = await list_rules(account_id=aid)
    rules = listed["rules"]
    assert len(rules) == 1 and rules[0]["id"] == out["id"], listed
    assert rules[0]["name"] == "Daytime chat", rules[0]


async def case_list_counts_smart_message_sends():
    """Smart Messages' Sent column: the list carries `sent` on the welcome,
    purchase and lifecycle rules — their landed outbound rows, a welcome burst
    counted once per fan — and on no other kind."""
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
        for fan in (1, 2):                       # two welcomes, three bubbles each
            for _ in range(3):
                out(aid, fan, "welcome")
        out(aid, 1, "purchase_followup")
        out(aid, 2, "purchase_followup")
        out(aid, 3, "nudge_online")
        out(other, 1, "birthday_message")        # another Creator's send
    rules = {r["kind"]: r for r in (await list_rules(account_id=aid))["rules"]}
    assert rules["send_welcome"]["sent"] == 2, rules["send_welcome"]
    assert rules["purchase_followup"]["sent"] == 2, rules["purchase_followup"]
    assert rules["birthday_message"]["sent"] == 0, rules["birthday_message"]
    assert "sent" not in rules["nudge_online"], rules["nudge_online"]


# ── toggle + edit ─────────────────────────────────────────────────────

async def case_toggle_and_edit():
    aid = "acc_ar_edit"
    await _seed_account(aid)
    created = await create_rule(RuleCreate(
        account_id=aid, kind="send_welcome", every_seconds=120,
    ))
    rid = created["id"]

    # Disable + change cadence + replace payload + rename, all in one PATCH.
    patched = await update_rule(rid, RulePatch(
        is_enabled=False, every_seconds=900,
        payload={"max_welcomes": 10}, name="Slow welcomes",
    ))
    assert patched["is_enabled"] is False, patched
    assert patched["every_seconds"] == 900, patched
    assert patched["payload"] == {"max_welcomes": 10}, patched
    assert patched["name"] == "Slow welcomes", patched
    # Disabled → no next-due projection.
    assert patched["next_due_at"] is None, patched

    # A partial PATCH leaves untouched fields alone.
    again = await update_rule(rid, RulePatch(is_enabled=True))
    assert again["is_enabled"] is True, again
    assert again["every_seconds"] == 900, "interval unchanged by partial patch"
    assert again["payload"] == {"max_welcomes": 10}, again


# ── run-now enqueues exactly one job ──────────────────────────────────

async def case_run_now_enqueues_job():
    aid = "acc_ar_run"
    await _seed_account(aid)
    created = await create_rule(RuleCreate(
        account_id=aid, kind="gen_info", every_seconds=600,
        payload={"limit": 50},
    ))
    rid = created["id"]

    # An unauthed caller (script) naming an employee: the job is that
    # operator's, so the supervisor runs it in the operator tier (ADR 0025).
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

    # The list now reflects a pending job for that kind.
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
    # One fan's due follow-up step, as lifecycle_messages.schedule_follow_ups queues it (the
    # predicate reads the payload, not the kind).
    async with get_session() as s:
        s.add(ScheduledJob(account_id=aid, kind="gen_info", run_at=past, status="pending",
                           rule_id=out["id"], payload_json=json.dumps(
                               {"follow_up": {"fan_id": 7, "steps": [], "step": 1}, "_followup": True})))

    async def badge() -> bool:
        return next(r for r in (await list_rules(account_id=aid))["rules"]
                    if r["id"] == out["id"])["has_pending_job"]

    assert await badge() is False, "a follow-up step is not the rule queued"
    async with get_session() as s:   # the rule's own due job: queued
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
    # 2 h on: later today, or (from 22:00 UTC) a slot already owed today; either way the
    # route must show dispatch_plan.next_due at the moment it serialized (t0..t1).
    slot = (now + timedelta(hours=2)).strftime("%H:%M")
    t0 = datetime.utcnow()
    clock = await create_rule(RuleCreate(account_id=aid, kind="auto_posts", payload={"dry_run": True},
                                         trigger={"daily_at": [slot], "tz_offset_minutes": 0}))
    t1 = datetime.utcnow()
    got = datetime.fromisoformat(clock["next_due_at"])
    want = {next_due(Clock((slot,), 0, None), None, t) for t in (t0, t1)}
    assert got in want, (got, want)
    assert clock["every_seconds"] is None, clock

    async with get_session() as s:   # hand-edited / raw-SQL rows (the API 422s both)
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


# ── delete ────────────────────────────────────────────────────────────

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

    # Deleting again 404s.
    try:
        await delete_rule(rid)
        assert False, "expected 404 on second delete"
    except HTTPException as e:
        assert e.status_code == 404, e


# ── validation ────────────────────────────────────────────────────────

async def case_validation():
    aid = "acc_ar_valid"
    await _seed_account(aid)

    # Unknown kind.
    try:
        await create_rule(RuleCreate(account_id=aid, kind="not_a_real_kind",
                                     every_seconds=300))
        assert False, "expected 422 for unknown kind"
    except HTTPException as e:
        assert e.status_code == 422, e

    # Sub-tick interval.
    try:
        await create_rule(RuleCreate(account_id=aid, kind="gen_info",
                                     every_seconds=5))
        assert False, "expected 422 for tiny interval"
    except HTTPException as e:
        assert e.status_code == 422, e

    # Non-object payload — RuleCreate types payload as dict|None, so a non-dict
    # is rejected by the route's own _validate_payload via a direct check.
    try:
        api._validate_payload([1, 2, 3])
        assert False, "expected 422 for list payload"
    except HTTPException as e:
        assert e.status_code == 422, e


async def case_quiet_hours_default_off_set_clear():
    """Quiet hours are opt-in: absent → null (24/7). A [start,end] band round-trips;
    [0,0] (or start==end) clears it; out-of-range / wrong-shape → 422."""
    aid = "acc_ar_quiet"
    await _seed_account(aid)

    # default: no quiet_hours → serialized as null (fires 24/7)
    created = await create_rule(RuleCreate(
        account_id=aid, kind="welcome_chatter_for_info", every_seconds=300))
    assert created["quiet_hours"] is None, created
    rid = created["id"]

    # set a wrap-midnight band
    patched = await update_rule(rid, RulePatch(quiet_hours=[22, 6]))
    assert patched["quiet_hours"] == [22, 6], patched

    # a partial PATCH leaves it untouched
    again = await update_rule(rid, RulePatch(is_enabled=False))
    assert again["quiet_hours"] == [22, 6], again

    # [0,0] clears it back to off
    cleared = await update_rule(rid, RulePatch(quiet_hours=[0, 0]))
    assert cleared["quiet_hours"] is None, cleared

    # validation: out of range + wrong shape
    for bad in ([25, 0], [5]):
        try:
            await create_rule(RuleCreate(account_id=aid, kind="welcome_chatter_for_info",
                                         every_seconds=300, quiet_hours=bad))
            assert False, f"expected 422 for quiet_hours={bad}"
        except HTTPException as e:
            assert e.status_code == 422, e


# ── typed payload validation (per-kind knob schema) ───────────────────

async def case_typed_payload_validation():
    """The typed editor's contract is enforced server-side: ints honour
    min/max, bools/ids are type-checked, id-lists coerce to ints, unknown keys
    pass through (forward-compat), and a bad value 422s on create AND patch."""
    aid = "acc_ar_typed"
    await _seed_account(aid)

    # Good payload: ids + float-whole ints coerce, unknown key kept.
    out = await create_rule(RuleCreate(
        account_id=aid, kind="welcome_chatter_for_info", every_seconds=300,
        payload={"limit": 40.0, "dry_run": False, "force_ids": [1, 2.0],
                 "future_knob": "keep-me"},
    ))
    p = out["payload"]
    assert p["limit"] == 40 and isinstance(p["limit"], int), p
    assert p["force_ids"] == [1, 2], p          # coerced to whole ints
    assert p["future_knob"] == "keep-me", p     # unknown key forwarded untouched

    # Bad values → 422 (one per knob type).
    bad_payloads = [
        {"limit": 0},            # int below min=1
        {"limit": "lots"},       # int not a number
        {"dry_run": "yes"},      # bool not a bool
        {"force_ids": 5},        # ids not a list
        {"force_ids": [1, "x"]}, # ids member not a whole number
    ]
    for bad in bad_payloads:
        try:
            await create_rule(RuleCreate(account_id=aid, kind="welcome_chatter_for_info",
                                         every_seconds=300, payload=bad))
            assert False, f"expected 422 for payload={bad}"
        except HTTPException as e:
            assert e.status_code == 422, (bad, e)

    # PATCH runs the same kind-aware validation (kind comes from the row).
    rid = out["id"]
    try:
        await update_rule(rid, RulePatch(payload={"limit": -3}))
        assert False, "expected 422 patching a sub-min int"
    except HTTPException as e:
        assert e.status_code == 422, e
    # A good PATCH still lands.
    again = await update_rule(rid, RulePatch(payload={"limit": 5, "max_replies": 3}))
    assert again["payload"] == {"limit": 5, "max_replies": 3}, again


# ── catalog ───────────────────────────────────────────────────────────

async def case_kinds_catalog():
    resp = await list_kinds()
    kinds = {k["kind"] for k in resp["kinds"]}
    for expected in ("welcome_chatter_for_info", "send_welcome", "gen_info",
                     "apply_profiles", "process_old_fans",
                     "scrape_chats", "send_followup", "send_mass_message",
                     "reply_mass_funnel", "unsend_messages"):
        assert expected in kinds, (expected, kinds)
    # Create policy is server-side and must stay off this wire: a value on the
    # display path gets applied on display, including when the editor merely
    # OPENS an existing rule. Asserted as a PROPERTY rather than against key
    # names — a leak under a third name would walk straight past a name list.
    for k in resp["kinds"]:
        # Only kinds that HAVE a create payload can leak one. Without this the
        # comparison runs against None for every other kind and degenerates into
        # "no catalog field is None" — a different invariant wearing this name.
        want = api._CREATE_PAYLOAD.get(k["kind"])
        if want is None:
            continue
        leaked = [key for key, val in k.items() if val == want]
        assert not leaked, (k["kind"], leaked)

    # Every entry carries the editor-driving fields; each knob is decorated with
    # a `widget` so the editor can render a typed input instead of a JSON box.
    # Every kind also carries a `surface` so the editor can hide non-rules kinds.
    _SURFACES = {"rules", "brain", "ready_made", "settings", "internal"}
    for k in resp["kinds"]:
        assert "label" in k and "recurring" in k and "knobs" in k, k
        assert k.get("surface") in _SURFACES, k
        for kn in k["knobs"]:
            assert "widget" in kn and "key" in kn and "type" in kn, kn

    # The /automations rule dropdown shows EXACTLY these recurring brain senders.
    # reply_mass_funnel is here too: it's the per-account poller that advances
    # funnels past the opener, so it has to be creatable as a schedulable rule.
    #
    # An EXACT set on purpose: a kind reaches this dropdown by being catalogued,
    # and a registered-but-uncatalogued kind silently defaults to "internal". So
    # both directions are mistakes worth failing on — a new automation leaking
    # into the operator's dropdown before anyone decided it should, and one that
    # was meant to be schedulable quietly not being.
    #
    # customs_watch (2026-08-04) is a deliberate addition: it is the ONLY way to
    # switch custom-tracking on per account, and its `min_cents` knob is where
    # the per-account tip floor is set.
    rules_surface = {k["kind"] for k in resp["kinds"] if k.get("surface") == "rules"}
    assert rules_surface == {
        "welcome_chatter_for_info", "autoreply", "send_followup", "gen_info",
        "apply_profiles", "scrape_chats", "process_old_fans",
        "reply_mass_funnel", "customs_watch",
    }, rules_surface

    # The floor is the knob an operator actually has to get right, so it must
    # render as a typed input with a default rather than a raw-JSON box.
    cw = {k["kind"]: k for k in resp["kinds"]}["customs_watch"]
    floor = next((kn for kn in cw["knobs"] if kn["key"] == "min_cents"), None)
    assert floor is not None, cw
    # The default the operator sees must BE the engine's fallback floor — a
    # catalog literal that drifts from `_customs.MIN_CENTS` shows one figure
    # in the editor while the sweep runs on another.
    assert floor["type"] == "int" and floor.get("default") == _customs.MIN_CENTS, floor
    assert "widget" in floor, floor

    # W8-E: welcome_chatter_for_info seeds a 60s cadence and exposes the history_tail knob.
    by_kind = {k["kind"]: k for k in resp["kinds"]}
    ai = by_kind["welcome_chatter_for_info"]
    assert ai.get("cadence_default_s") == 60, ai
    ht = next((kn for kn in ai["knobs"] if kn["key"] == "history_tail"), None)
    assert ht is not None and ht["type"] == "int" and ht.get("default") == 40, ai["knobs"]
    # The recurring rules-surface kinds all carry a sane cadence preset.
    for kind_, want in (("send_followup", 3600),
                        ("gen_info", 86400), ("scrape_chats", 86400),
                        ("apply_profiles", 3600),
                        ("reply_mass_funnel", 120)):
        assert by_kind[kind_].get("cadence_default_s") == want, by_kind[kind_]

    # W9-A: every kind carries a one-line "example"; welcome_chatter_for_info in particular.
    assert ai.get("example"), ai
    # The utility kinds group under "Advanced"; core kinds have no group.
    for kind_ in ("process_old_fans", "scrape_chats", "reply_mass_funnel"):
        assert by_kind[kind_].get("group") == "advanced", by_kind[kind_]
    assert by_kind["welcome_chatter_for_info"].get("group") != "advanced", by_kind["welcome_chatter_for_info"]



# ── the rule behind a settings tab ────────────────────────────────────

async def case_ensure_kind_rule():
    """`enabled` on a settings tab owns the engine's rule row. The policy that
    five config endpoints used to hand-roll, pinned once."""
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

    # CREATE — cadence and name come from the catalog the editor offers. Not the
    # PAYLOAD, though: this kind declares no create payload, and the editor would
    # have written every bool knob it displays. The two paths share a source, not
    # a result.
    assert await _sync(enable=True) == "created"
    rows = await _rows()
    assert len(rows) == 1 and rows[0].is_enabled, rows
    assert '"every_seconds": 60' in rows[0].trigger_json, rows[0].trigger_json
    assert rows[0].name == api._CATALOG["welcome_chatter_for_info"]["label"], rows[0].name
    assert rows[0].steps_json == "{}", rows[0].steps_json

    # Saving again is a no-op, NOT a second ticker for the same kind.
    assert await _sync(enable=True) == "unchanged"
    assert len(await _rows()) == 1

    # The operator retunes the row in the rules editor…
    await update_rule(rows[0].id, RulePatch(name="Nights only", every_seconds=900))

    # …and a config save must not stamp on it. Nothing but the switch was sent.
    assert await _sync(enable=False) == "parked"
    assert await _sync(enable=True) == "updated"          # woken
    rows = await _rows()
    assert len(rows) == 1, rows
    assert rows[0].is_enabled and rows[0].name == "Nights only", rows[0].name
    assert '"every_seconds": 900' in rows[0].trigger_json, rows[0].trigger_json

    # A caller that DOES own the schedule (nudge) passes it and wins.
    assert await _sync(enable=True, every_seconds=1800, steps={"with_image": False},
                       name="Nudge online") == "updated"
    rows = await _rows()
    assert '"every_seconds": 1800' in rows[0].trigger_json, rows[0].trigger_json
    assert rows[0].name == "Nudge online" and "with_image" in rows[0].steps_json

    # OFF parks EVERY row of the kind. Parking only the first would leave the
    # engine sending under a box that reads off — the whole point of one switch.
    async with get_session() as s:
        s.add(AutomationRule(account_id=aid, name="second ticker", kind="welcome_chatter_for_info",
                             trigger_json='{"every_seconds": 60}', steps_json="{}",
                             is_enabled=True))
    assert len(await _rows()) == 2
    assert await _sync(enable=False) == "parked"
    assert not any(r.is_enabled for r in await _rows()), await _rows()
    assert await _sync(enable=False) == "unchanged"        # already off

    # A row still carrying a RETIRED kind name is the same row. Matching only the
    # canonical name would quietly create a duplicate beside it and double the tick.
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
    """A switch-created row is furnished from the catalog, payload included.

    Until the Brain grew a Fan-profiles button that was true of the name and the
    cadence only, and a new row arrived with an empty payload. The button needs a
    fresh `apply_profiles` to push the nickname and note to OnlyFans, which is
    what the catalog's own example advertises — and two live accounts
    deliberately run that engine DB-only, so the default must reach a CREATE and
    never a wake.

    It comes from `_CREATE_PAYLOAD`, NOT the knobs' `default` values, and that
    makes the two create paths deliberately differ: the editor applies knob
    defaults whenever it OPENS a rule, so a knob default here would re-stamp an
    existing row on its next save. The final assert is what holds that line.
    """
    import json

    aid = "acc_ar_switch_defaults"
    await _seed_account(aid)

    async def _rows(kind):
        async with get_session() as s:
            return (await s.execute(select(AutomationRule).where(
                AutomationRule.account_id == aid,
                AutomationRule.kind == kind))).scalars().all()

    # CREATE is furnished from the catalog: payload, cadence and name together.
    out = await switch_kind(KindSwitch(account_id=aid, kind="apply_profiles", enable=True))
    assert out["action"] == "created", out
    rows = await _rows("apply_profiles")
    assert len(rows) == 1 and rows[0].is_enabled, rows
    assert json.loads(rows[0].steps_json) == {"push_to_of": True}, rows[0].steps_json
    assert '"every_seconds": 3600' in rows[0].trigger_json, rows[0].trigger_json
    assert rows[0].name == api._CATALOG["apply_profiles"]["label"], rows[0].name

    # The operator turns the push OFF and parks the row…
    await update_rule(rows[0].id, RulePatch(payload={"push_to_of": False}))
    await switch_kind(KindSwitch(account_id=aid, kind="apply_profiles", enable=False))

    # …and waking it must NOT re-stamp the default. This assert is what stands
    # between an operator's choice and a button on another screen.
    out = await switch_kind(KindSwitch(account_id=aid, kind="apply_profiles", enable=True))
    assert out["action"] == "updated", out
    rows = await _rows("apply_profiles")
    assert len(rows) == 1 and rows[0].is_enabled, rows
    assert json.loads(rows[0].steps_json) == {"push_to_of": False}, rows[0].steps_json

    # A kind with no `_CREATE_PAYLOAD` entry still starts empty. gen_info also
    # proves the cadence — which DOES come from the catalog, unlike the payload:
    # the create ROUTE would have defaulted this one to 300s.
    out = await switch_kind(KindSwitch(account_id=aid, kind="gen_info", enable=True))
    assert out["action"] == "created", out
    gen = await _rows("gen_info")
    assert '"every_seconds": 86400' in gen[0].trigger_json, gen[0].trigger_json
    assert json.loads(gen[0].steps_json) == {}, gen[0].steps_json

    # The create default is its OWN catalog key, never a knob's `default`. Knob
    # defaults are what the editor pre-ticks whenever it OPENS a rule, so reading
    # them here would let a row created without a key acquire it on the next
    # unrelated save — an existing account's silence turned into a decision.
    # push_to_of must therefore carry no knob default.
    knobs = {k["key"]: k for k in api._CATALOG["apply_profiles"]["knobs"]}
    assert "default" not in knobs["push_to_of"], knobs["push_to_of"]

    # A caller that owns the payload still wins outright — the defaults fill a
    # silence, they do not merge into an answer.
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
    """The route the settings tabs call. One request per click — the client used
    to park N rows with N requests and could half-fail between them."""
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

    # A retired name resolves to the live kind — never a fresh legacy row.
    out = await switch_kind(KindSwitch(account_id=aid, kind="of_ai_chat", enable=True))
    assert out["kind"] == "welcome_chatter_for_info", out

    try:
        await switch_kind(KindSwitch(account_id=aid, kind="not_a_kind", enable=True))
        raise AssertionError("unknown kind must 422")
    except HTTPException as e:
        assert e.status_code == 422, e



# Knobs an automation reads that are deliberately NOT catalogued. Every entry is
# a real, named exemption — the point of the check below is that adding a knob
# without a UI surface must be a DECISION recorded here, not an oversight.
_UNCATALOGUED_ON_PURPOSE = {
    "send_welcome": {
        # Internal seams the UI drives, never an operator-typed rule knob:
        "test_fan",         # the panel's "send test" button targets one fan
        "test_name",        # ...under a name the operator typed in the box
        # Raw-JSON escape hatches, documented at their read site in the sender:
        "pace_open_quiet_s",   # per-rule override of the quiet band before b0
        "pace_gap_quiet_s",    # ...and between bubbles
        # New-sub definition, tuned per account by hand when a feed misbehaves:
        "guard_hours", "new_max_inbound", "new_max_outbound",
        # A queued follow-up job's own payload (lifecycle_messages), not a knob:
        "follow_up",
    },
    # Nothing exempt: every knob this kind reads has a catalog entry.
    "auto_follow": set(),
}


async def case_every_knob_the_automation_reads_is_catalogued():
    """THE SEAM CHECK. A knob read by an automation but absent from `_CATALOG`
    has no typed validation and no UI surface: `_validate_payload_for_kind`
    passes it through untouched, so `money_gate: "false"` (the string) saves
    fine and evaluates TRUTHY, and `follow_back` — a PAYING call — defaulted on
    with no way to switch it off short of hand-editing raw JSON.

    This seam has now been missed three times, each time by someone who added
    the knob and the read in the same change. So the guard is the check, not the
    three entries: walk `_CATALOG[kind]["knobs"]` against every `payload.get`
    literal in the matching module and fail on anything read but undeclared.

    Scoped to the two kinds this guard was written for. Widening it to every
    automation is worth doing, but not in the same change — several of the older
    kinds carry a dozen undeclared internal keys each, and an allowlist that long
    stops being a decision record and becomes a silent skip."""
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
        # Not every read goes through `.get` — three helpers take the key as an
        # argument. All are counted, or a catalogued knob would look unread.
        # (`bool_knob` joined them when `follow_back`/`follow_back_gate` moved
        # off `bool(payload.get(k, DEFAULT))`, which read a stored `null` as
        # False instead of as the default.)
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

        # A catalogued knob nobody reads is the same seam facing the other way:
        # the UI offers a switch that does nothing.
        assert not (declared - reads), (
            f"{kind} declares {sorted(declared - reads)} in _CATALOG but the "
            f"module never reads them")


# `type: "bool"` knobs whose module DELIBERATELY reads a different default than
# the catalog shows. Every entry is a decision with a migration behind it, and
# the check below prints this comment back at whoever tries to add a sixth.
_BOOL_DEFAULT_MISMATCH_ON_PURPOSE = {
    ("send_welcome", "time_only"): (
        "Catalog True (stamped at rule CREATION), sender False (an absent "
        "key must keep meaning what it meant before the knob existed, or sixteen "
        "legacy rules become clock-only retroactively). The TODO at the read site "
        "in send_welcome.run names the two one-way fixes. Do not close it here."),
}


# Reads this check REFUSES to certify, and why. An entry here is NOT a pass: it
# says "the null-resolution of this knob is not a single constant, so no source
# scan can vouch for it — here is what pins it instead". Removing the read's
# ambiguity means removing the entry.
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
    """A bool read whose null-resolution this check cannot reduce to one
    constant. Raised with a reason the failure message prints verbatim."""


def _resolve_object(mod, node):
    """The runtime VALUE of a default expression, read off the module.

    Handles the shapes a default is actually written in: a literal, a
    module-level constant (`_FOLLOW_BACK_DEFAULT`), an attribute path, and a
    subscript of either (`DEFAULTS["with_image"]` — S6's descriptor-table
    shape, which the previous regex classifier hard-failed on). Anything else
    raises rather than guessing."""
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
    """`bool_knob` for both `bool_knob(...)` and `_common.bool_knob(...)`."""
    f = node.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return None


def _is_bool_knob(mod, node: ast.Call) -> bool:
    """Is this call the shared reader — by IDENTITY, not by spelling?

    A name match alone missed an ALIAS (`from ._common import bool_knob as bk`),
    and an aliased helper was one of the shapes that could be added beside a
    correct read with this check staying green. Resolving the callee off the
    module object catches every spelling that actually binds to the function:
    the bare name, `_common.bool_knob`, and any alias of either. The name match
    stays first because it is free and answers for every read in the tree today.
    """
    if _call_name(node) == "bool_knob":
        return True
    from automations import _common
    try:
        return _resolve_object(mod, node.func) is _common.bool_knob
    except _Unclassifiable:
        return False


# Functions that read a bool knob through a key PARAMETER, and are therefore not
# a read of any one knob: the walk classifies them at their CALL sites instead,
# where the key IS a literal. Anything else reading through a non-literal key is
# a descriptor table this scan cannot follow per-key, and it is recorded as a
# problem for every knob in that module rather than ignored.
_BOOL_KEY_PASSTHROUGH = {"_on_unless_off"}


def _const_str(node) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


class _Site:
    """One place a bool knob is read, and what it resolves a stored `null` to.

    `resolves` is the answer, `problem` is set instead when the read is either
    illegal or unclassifiable. `form` is what gets printed back at whoever has
    to fix it."""

    def __init__(self, lineno: int, form: str, *, resolves=None, problem=None):
        self.lineno, self.form, self.resolves, self.problem = lineno, form, resolves, problem


def _bool_read_sites(mod, tree: ast.AST, key: str) -> tuple[list[_Site], list[int]]:
    """EVERY read of `key` in the module, plus the lines where a bool knob is
    read through a NON-LITERAL key.

    Every read, not the first one that classifies: a wrong read added BESIDE a
    right one used to pass, because the scan returned as soon as one
    `bool_knob(...)` answered. Two-read-site knobs are already the norm here —
    `send_welcome` reads `time_only` and `skip_time_bubble` at two sites each —
    so "the first read is correct" was never the claim worth making.

    The three forms, and the one that is a defect:

        bool_knob(p, k, D)      → null ⇒ D              ← the only correct one
        _on_unless_off(p, k)    → null ⇒ True in prod   ← bool_knob + a computed default
        <expr>.get(k)           → null ⇒ None ⇒ falsy   ← only legal for default False
        <expr>.get(k, D)        → null ⇒ None ⇒ FALSE, whatever D says  ← the defect

    The receiver of a `.get` is deliberately UNCONSTRAINED. It used to have to be
    a bare `ast.Name`, so `self.payload.get(k, True)` and `cfgs["x"].get(k, True)`
    — an Attribute and a Subscript receiver — were both discarded in silence
    beside a correct read. Nothing in the tree reads a catalogued key off a
    non-payload dict, so widening it costs no false positive and closes two of
    the four shapes that could be smuggled in.

    `dynamic_key_lines` are `bool_knob` calls whose KEY is not a literal. They
    cannot be attributed to any one knob, so the caller records them as a problem
    for EVERY knob in the module — reporting them only when no literal read was
    found (which is what this used to do) is exactly how an unrecognised second
    read got discarded once any literal read classified.
    """
    sites: list[_Site] = []
    dynamic_key_lines: list[int] = []
    # A key-parameter pass-through (`_on_unless_off`) is not a read of any knob;
    # its own call sites are classified above. Its BODY is the one non-literal
    # key in the tree today, and treating that as a descriptor table would fail
    # `send_welcome` on a helper this walk already understands.
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
            # A default that is itself a `bool_knob` is a SECOND payload, not a
            # constant — the answer depends on that other dict's contents and no
            # source scan can name it. Refuse; do not unwrap to the inner literal.
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
                # `bool_knob(payload, key, not _test_mode())` — ON outside the
                # harness, which is the production answer this walk is about.
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
    """THE CLASS CHECK. Every `type: "bool"` knob, in EVERY kind, must resolve a
    stored `null` to the default the catalog shows.

    Round 1 fixed this defect at the two sites a reviewer had named; round 2
    measured five more, two of which spend money (`auto_follow.money_gate` — the
    catalog prices the ungated pool at "≈$177 per 711 fans" — and
    `auto_follow.dry_run`, which ran LIVE while the toast said "plans only,
    nothing sent"). Fixing named sites is what produced the second round. So the
    deliverable is this case, not those sites: it makes a SIXTH site fail here
    before it can reach a rule.

    Why `null` and not merely "absent": `null` is the one non-boolean that
    reached storage for a bool knob, because `_validate_payload_for_kind` used to
    SKIP a None value rather than dropping it. `bool(payload.get(k, True))` reads
    it as False, because `.get` found the key and the default never ran; every UI
    surface reads it as the declared default. A key that says nothing must mean
    what an absent key means.

    ⚠️ The boundary now POPS a null for a catalogued knob
    (`case_a_null_for_a_catalogued_knob_is_dropped_at_the_boundary`), so no NEW
    rule can carry one. This case stays: rules written before that line still
    hold stored nulls, and `bool_knob`'s null clause is the defence that answers
    for them. It is now a defence against history rather than the contract.

    The read is not callable in isolation (each one sits inside a full `run()`),
    so this classifies the READ FORMS in the module's AST — see
    `_bool_read_sites` for the four it knows. What it must NOT do is fail on
    legitimate code, which the regex version did four ways at once (a paren
    inside a string default, `ruff format`'s trailing comma, a non-literal
    default, and a docstring quoting a wrong form on purpose); an `ast` walk
    gives all four away for free.

    ⚠️ WHAT THIS DOES AND DOES NOT PROMISE. It once said "never a silent skip",
    which is more than a source scan can hold. What it holds is: within the
    module a catalogued kind is named after, EVERY call that binds to
    `_common.bool_knob` (by identity, so an alias counts) and EVERY `.get` of
    the knob's literal key on ANY receiver is collected, they must all agree,
    and a read this walk cannot reduce to one constant — no default, an
    unresolvable default, a nested `bool_knob`, or a non-literal KEY anywhere in
    the module — is a hard failure demanding a `_BOOL_READ_UNCLASSIFIABLE`
    entry that names what pins it instead. Adding a wrong read beside a right
    one fails here, which was the whole point.

    What it cannot see, and what those exceptions exist for: a read in a module
    the catalog does not name (a fire-job or a helper), a key assembled at
    runtime (`getattr`, an f-string), and any resolution that depends on a
    second dict rather than a constant — `nudge_online.with_image` is that last
    one, and it is pinned by its own suite instead."""
    import importlib

    from automations import _common, send_welcome

    # The helper itself, first — everything below is a claim ABOUT this contract.
    for dflt in (True, False):
        assert _common.bool_knob({}, "k", dflt) is dflt
        assert _common.bool_knob({"k": None}, "k", dflt) is dflt
        assert _common.bool_knob(None, "k", dflt) is dflt
        assert _common.bool_knob({"k": True}, "k", dflt) is True
        assert _common.bool_knob({"k": False}, "k", dflt) is False
    # ...and `_on_unless_off` IS that helper with a computed default, not a
    # second implementation of it (they used to be two near-identical bodies and
    # only one had the `null` hole closed).
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

            # A `bool_knob` read through a NON-LITERAL key is a read this walk
            # cannot attribute to any knob, so it is a problem for EVERY knob in
            # the module — not a footnote to print only when no literal read was
            # found. That was the last silent skip: once any literal read
            # classified, an unrecognised second read was dropped on the floor.
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

            # EVERY site, not the first one that answers: a wrong read added
            # BESIDE a right one is the shape that passed before.
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
    # A walk that silently stopped finding knobs would pass this case forever.
    # (29 since the legacy selling engine's knob went with it, 2026-10-18; 28
    # since mass_nudge went, 2026-10-21; 27 since push_to_sheets' create_tab;
    # 25 since online_blast's two.)
    assert checked >= 25, f"only {checked} catalogued bools walked"


async def case_bool_knob_matches_the_typescript_half():
    """The relay's `bool_knob` and the app's `boolKnob` are ONE rule with two
    implementations, and nothing but a grep kept them in step — so they had
    already drifted: the TS half read `[]` and `{}` as ON where the relay reads
    them OFF, under a doc comment that described the relay's behaviour.

    They cannot share code across the wire, so they share a TABLE:
    `service/tests/fixtures/bool_knob_cases.json`, asserted here and by
    `app/lib/boolKnob.test.ts`. Add a row there and whichever half drifts goes
    red, instead of a reviewer noticing eight months later."""
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

    # The table must actually exercise the values the two languages disagree
    # about, or it ratifies the drift it exists to catch.
    stored = [c.get("value") for c in cases if not c.get("absent")]
    for v in (None, 0, "", [], {}):
        assert any(x == v and type(x) is type(v) for x in stored), (
            f"the shared table no longer covers a stored {v!r} — that is one of "
            f"the values python and JavaScript answer differently for")


async def case_a_null_for_a_catalogued_knob_is_dropped_at_the_boundary():
    """🔴 THE ROOT OF THE `null` CLASS, CLOSED WHERE IT ENTERS.

    `_validate_payload_for_kind` rejects `money_gate: "false"` and used to ACCEPT
    `money_gate: null` — so `null` became the one non-boolean that reached storage
    for a bool knob, and every reader downstream had to know it meant "absent".
    That knowledge landed at eight python read sites, at `app/lib/boolKnob.ts`,
    and at a source-regex guard that must now know every way a module might spell
    a payload read, forever.

    A key that says nothing IS an absent key, so the boundary pops it. That makes
    it true in the store rather than true by convention — and it covers `int`,
    `str` and `ids` at the same time, which had the identical hole with no
    defence built for any of them.

    Unknown/future keys still pass through untouched, null included: the catalog
    is not the schema, and the raw-JSON escape hatch is a feature."""
    aid = "acc_rules_null_boundary"
    await _seed_account(aid)

    # Every catalogued shape, all null, on a kind that has one of each.
    created = await create_rule(RuleCreate(
        account_id=aid, kind="auto_follow", every_seconds=3600, payload={
            "money_gate": None,          # bool
            "daily_cap": None,           # int
            "action": None,              # str/enum
            "dry_run": False,            # …and a real value survives beside them
            "some_future_key": None,     # NOT catalogued — passes through
        }))
    stored = created["payload"]
    for key in ("money_gate", "daily_cap", "action"):
        assert key not in stored, (key, stored)
    assert stored["dry_run"] is False, stored
    assert "some_future_key" in stored and stored["some_future_key"] is None, stored

    # And the sender then resolves the missing money gate to the catalog default,
    # which is the whole point: "price-check every fan", not "buy every priced
    # creator in the pool".
    from automations._common import bool_knob
    assert bool_knob(stored, "money_gate", True) is True, stored


async def case_money_and_follow_knob_defaults_match_the_code():
    """The catalog's `default` is what the UI SHOWS for an unset knob, so a
    default that disagrees with the sender's read-default renders a checkbox in
    a state the automation does not honour (the V5 mismatch). Pinned for the
    three money-adjacent knobs, whose read-defaults are load-bearing."""
    from automations import send_welcome

    knobs = {k["key"]: k for k in api._CATALOG["send_welcome"]["knobs"]}
    assert knobs["follow_back"]["default"] is send_welcome._FOLLOW_BACK_DEFAULT
    assert (knobs["follow_back_gate"]["default"]
            is send_welcome._FOLLOW_BACK_GATE_DEFAULT)
    # ...and the default has to survive a stored `null`. The boundary drops one
    # now, but rules written before it still carry them, and
    # `bool(payload.get(k, True))` is False for a null because `.get` found the
    # key and the default never applied. That made a stored `null` mean "lane
    # off, price-check off" to the sender while the catalog and the panel both
    # said True. A key that says nothing means what absent means.
    for key, dflt in (("follow_back", send_welcome._FOLLOW_BACK_DEFAULT),
                      ("follow_back_gate", send_welcome._FOLLOW_BACK_GATE_DEFAULT)):
        assert send_welcome.bool_knob({}, key, dflt) is dflt, key
        assert send_welcome.bool_knob({key: None}, key, dflt) is dflt, key
        assert send_welcome.bool_knob({key: False}, key, dflt) is False, key
    # `stop_on_reply` and `human_pace` are absent-means-ON, and the SENDER is the
    # authority on that. A bare `is True` here only re-states the catalog: flip
    # `_on_unless_off` back to absent-means-off and the panel would keep shipping
    # a ticked checkbox for a knob the sender ignores — with this case green. So
    # ask the sender, exactly as the follow_back pair above does.
    #
    # The env dance IS the carve-out, not a workaround: `_on_unless_off` answers
    # OFF under CHATTERLY_TEST_MODE (which _harness sets for every case in this
    # file), so asking it for the PRODUCTION default means asking it as
    # production would.
    _was_test_mode = os.environ.pop("CHATTERLY_TEST_MODE", None)
    try:
        for key in ("stop_on_reply", "human_pace"):
            assert knobs[key]["default"] is send_welcome._on_unless_off({}, key), key
        # ...and the carve-out itself, so deleting it also lands here in red
        # rather than as an 84-case suite that suddenly sleeps for minutes.
        os.environ["CHATTERLY_TEST_MODE"] = "1"
        for key in ("stop_on_reply", "human_pace"):
            assert send_welcome._on_unless_off({}, key) is False, key
            # ...and the variable is PARSED, not merely present. "0" is what a
            # person types when they mean no, and a bare truthiness test on the
            # string turned that into "yes, this is a test run" — silently
            # switching both knobs off on whatever ran with it.
            for off in ("0", "false", "no", "off", "", "  "):
                os.environ["CHATTERLY_TEST_MODE"] = off
                assert send_welcome._on_unless_off({}, key) is True, (key, off)
            os.environ["CHATTERLY_TEST_MODE"] = "1"
            # An EXPLICIT value still wins in both environments — the carve-out
            # only ever decides what an ABSENT key means.
            assert send_welcome._on_unless_off({key: True}, key) is True, key
            assert send_welcome._on_unless_off({key: False}, key) is False, key
    finally:
        if _was_test_mode is None:
            os.environ.pop("CHATTERLY_TEST_MODE", None)
        else:
            os.environ["CHATTERLY_TEST_MODE"] = _was_test_mode

    af = {k["key"]: k for k in api._CATALOG["auto_follow"]["knobs"]}
    # money_gate must be TYPED so `"false"` (the string) is a 422 rather than a
    # truthy value that silently leaves the gate on.
    assert af["money_gate"]["type"] == "bool" and af["money_gate"]["default"] is True
    try:
        _validate_payload_for_kind("auto_follow", {"money_gate": "false"})
        raise AssertionError("money_gate must reject a string")
    except HTTPException as e:
        assert e.status_code == 422, e
    # And the catalog default is DISPLAY-ONLY: validating an empty payload must
    # not stamp it, or every rule would be re-defaulted on save.
    assert _validate_payload_for_kind("auto_follow", {}) == {}


async def case_next_due_ignores_one_shot_runs_of_the_kind():
    """REGRESSION (wave6 B11): a scoped test enqueue (rule_id NULL) of the same
    kind must not push the rule's displayed next fire back; next_due_at anchors
    on the rule's own jobs, exactly like the materializer."""
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
        # The one-shot test run, minutes ago, outside the rule.
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
