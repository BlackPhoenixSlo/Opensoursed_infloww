#!/usr/bin/env python3
"""Settings → System (service/system_admin_api.py): master-only automation
status + run log.

  * the Master reads both routes;
  * an owner (non-master) gets 403, a chatter 403, nobody signed in 401;
  * /admin/system/automations reports each kind's rule is_enabled and config
    `enabled` flag, flags a disagreement as a mismatch, and flags duplicate rules;
  * /admin/system/runs lists runs across accounts (with error_text) and the
    failed / pending scheduled_jobs, and honours its filters.

Run: ./venv/bin/python service/tests/test_system_admin_api.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB
_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, AutomationRule, AutomationRun, ScheduledJob  # noqa: E402

IDS = fx.seed_two_agencies()
A = IDS["creator_a"]
B = IDS["creator_b"]
C = "1000003"  # a third creator, only to hold the two mismatch examples


def _rule(aid: str, kind: str, enabled: bool) -> AutomationRule:
    return AutomationRule(account_id=aid, name=kind, kind=kind, trigger_json="{}",
                          steps_json="{}", is_enabled=enabled)


async def _seed() -> None:
    now = datetime.utcnow()
    async with get_session() as s:
        # A: autoreply rule ON + config ON (agree); nudge_online twice (duplicate),
        # config absent (default ON).
        s.add_all([_rule(A, "autoreply", True),
                   _rule(A, "nudge_online", True), _rule(A, "nudge_online", False),
                   _rule(A, "scrape_chats", False)])
        s.add(AccountAiConfig(
            account_id=A,
            autoreply_config_json=json.dumps({"enabled": True}),
        ))
        # C: autoreply rule ON + config OFF (mismatch); nudge_online ON in config
        # with no rule (a config-on/no-rule mismatch).
        s.add(Account(id=C))
        s.add(_rule(C, "autoreply", True))
        s.add(AccountAiConfig(
            account_id=C,
            autoreply_config_json=json.dumps({"enabled": False}),
            nudge_config_json=json.dumps({"enabled": True}),
        ))
        s.add_all([
            AutomationRun(account_id=A, kind="autoreply", status="ok",
                          started_at=now - timedelta(minutes=5), completed_at=now),
            AutomationRun(account_id=B, kind="send_followup", status="error",
                          started_at=now - timedelta(minutes=1), error_text="boom: upstream 500"),
            ScheduledJob(account_id=B, kind="send_followup", payload_json="{}", run_at=now,
                         status="error", attempts=3, last_error="boom: upstream 500"),
            ScheduledJob(account_id=A, kind="autoreply", payload_json="{}", run_at=now,
                         status="pending"),
            ScheduledJob(account_id=A, kind="autoreply", payload_json="{}", run_at=now,
                         status="done"),
        ])


asyncio.run(_seed())
MASTER = fx.login_owner("agency_master")
OWNER = fx.login_owner("agency_a_owner")
CHATTER = fx.login_chatter("chatter_a")
ANON = _harness.make_client()
ROUTES = ("/admin/system/automations", "/admin/system/runs")


def _row(body: dict, aid: str, kind: str) -> dict:
    acct = next(a for a in body["accounts"] if a["account_id"] == aid)
    return next(r for r in acct["automations"] if r["kind"] == kind)


def case_master_reads_both_routes():
    for path in ROUTES:
        r = MASTER.get(path)
        assert r.status_code == 200, f"{path}: {r.status_code} {r.text}"


def case_non_master_is_refused():
    for path in ROUTES:
        assert OWNER.get(path).status_code == 403, f"owner reached {path}"
        assert CHATTER.get(path).status_code == 403, f"chatter reached {path}"
        assert ANON.get(path).status_code == 401, f"anonymous reached {path}"
    # Even naming the owner's OWN account does not open it.
    assert OWNER.get(f"/admin/system/runs?account_id={A}").status_code == 403


def case_status_reflects_rule_and_config_flags():
    body = MASTER.get("/admin/system/automations").json()
    agree = _row(body, A, "autoreply")
    assert agree["rule_enabled"] is True and agree["config_enabled"] is True, agree
    assert agree["mismatch"] is False and agree["effective"] is True, agree

    bad = _row(body, C, "autoreply")
    assert bad["rule_enabled"] is True and bad["config_enabled"] is False, bad
    assert bad["mismatch"] is True and bad["effective"] is False, bad

    dup = _row(body, A, "nudge_online")
    assert dup["duplicate_rules"] is True and len(dup["rule_ids"]) == 2, dup
    assert dup["rules_enabled_count"] == 1, dup
    assert dup["config_stored"] is False and dup["config_enabled"] is True, "nudge_online defaults ON"

    norule = _row(body, C, "nudge_online")
    assert norule["rule_ids"] == [] and norule["config_enabled"] is True, norule
    assert norule["mismatch"] is True, "config on with no rule must flag"

    extra = _row(body, A, "scrape_chats")
    assert extra["source"] == "rule" and extra["rule_enabled"] is False, extra

    # B has no rules and no config: every config-gated kind defaulting OFF agrees.
    assert _row(body, B, "autoreply")["mismatch"] is False
    # ...and a house-default-ON kind nobody ever saved or ruled is not a mismatch.
    row = _row(body, B, "nudge_online")
    assert row["config_enabled"] is True and row["rule_ids"] == [], row
    assert row["mismatch"] is False, row
    assert body["mismatch_count"] >= 2, body["mismatch_count"]


def case_kill_switch_reported():
    os.environ["STYLE_FORCE_OFF"] = "1"
    try:
        body = MASTER.get("/admin/system/automations").json()
    finally:
        os.environ.pop("STYLE_FORCE_OFF", None)
    sw = next(k for k in body["kill_switches"] if k["env"] == "STYLE_FORCE_OFF")
    assert sw["active"] is True and sw["value"] == "1", sw


def case_runs_span_accounts_with_errors_and_jobs():
    body = MASTER.get("/admin/system/runs").json()
    assert {r["account_id"] for r in body["runs"]} >= {A, B}, body["runs"]
    assert body["runs"][0]["error_text"] == "boom: upstream 500", "newest first"
    statuses = sorted(j["status"] for j in body["jobs"])
    assert statuses == ["error", "pending"], f"done jobs must not list: {statuses}"
    err = next(j for j in body["jobs"] if j["status"] == "error")
    assert err["last_error"] == "boom: upstream 500" and err["attempts"] == 3, err


def case_runs_filters():
    body = MASTER.get("/admin/system/runs", params={"status": "error"}).json()
    assert [r["status"] for r in body["runs"]] == ["error"], body["runs"]
    assert [j["status"] for j in body["jobs"]] == ["error"], body["jobs"]
    body = MASTER.get("/admin/system/runs", params={"account_id": A, "kind": "autoreply"}).json()
    assert [r["kind"] for r in body["runs"]] == ["autoreply"], body["runs"]
    assert [j["status"] for j in body["jobs"]] == ["pending"], body["jobs"]


_harness.run()
