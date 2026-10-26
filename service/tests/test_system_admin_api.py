#!/usr/bin/env python3
"""Settings → System (service/system_admin_api.py): master-only automation
status + run log.

  * the Master reads both routes;
  * an owner (non-master) gets 403, a chatter 403, nobody signed in 401;
  * /admin/system/automations reports each kind's rule is_enabled and config
    `enabled` flag, flags a disagreement as a mismatch, and flags duplicate rules;
  * /admin/system/runs lists runs across accounts (with error_text) and the
    failed / pending scheduled_jobs, and honours its filters.
  * /admin/system/switches lists every runtime switch; PUT sets / clears an
    override (founder password required, audited with it redacted) that each
    consumer reads at once; bad values 422; a failed boot load is reported
    (`loaded: false`) and retried.

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
ROUTES = ("/admin/system/automations", "/admin/system/runs", "/admin/system/switches")


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


PW = os.environ["ADMIN_PASSWORD"]   # the harness sets the founder password


def _put(name: str, value, *, client=None, pw: str | None = PW):
    body = {"value": value} if pw is None else {"value": value, "admin_password": pw}
    return (client or MASTER).put(f"/admin/system/switches/{name}", json=body)


def _switch(name: str) -> dict:
    body = MASTER.get("/admin/system/switches").json()
    return next(k for k in body["switches"] if k["env"] == name)


def case_switches_list_every_registered_switch():
    import runtime_switches
    body = MASTER.get("/admin/system/switches").json()
    assert [k["env"] for k in body["switches"]] == [s.env for s in runtime_switches.SWITCHES], body
    assert isinstance(body["loaded"], bool), body   # the harness runs no startup: covered below
    sw = _switch("W7_WEBHOOK_DISPATCH_DISABLED")
    assert sw["source"] == "default" and sw["effective"] is False and sw["active"] is False, sw
    assert sw["kind"] == "bool" and sw["override"] is None and sw["fallback"] is False, sw


def case_env_kill_switch_reported():
    os.environ["STYLE_FORCE_OFF"] = "1"
    try:
        sw = _switch("STYLE_FORCE_OFF")
    finally:
        os.environ.pop("STYLE_FORCE_OFF", None)
    assert sw["active"] is True and sw["env_raw"] == "1" and sw["source"] == "env", sw
    assert sw["fallback"] is True and sw["overrides_env"] is False, sw


def case_override_beats_env_and_clears_back_to_it():
    import webhook_dispatch
    from automations import _common
    os.environ["W7_WEBHOOK_DISPATCH_DISABLED"] = "1"
    try:
        assert webhook_dispatch._global_kill_switch() is True, "env alone turns it on"
        r = _put("W7_WEBHOOK_DISPATCH_DISABLED", False)
        assert r.status_code == 200, r.text
        sw = r.json()["switch"]
        assert sw["source"] == "override" and sw["effective"] is False and sw["env_value"] is True, sw
        assert sw["override_by"] == "agency_master", sw
        assert sw["overrides_env"] is True, "an override against a set env var is flagged"
        assert webhook_dispatch._global_kill_switch() is False, "the override wins over env, no restart"
        r = _put("W7_WEBHOOK_DISPATCH_DISABLED", None)
        assert r.status_code == 200 and r.json()["switch"]["source"] == "env", r.text
        assert webhook_dispatch._global_kill_switch() is True, "cleared: env again"
    finally:
        os.environ.pop("W7_WEBHOOK_DISPATCH_DISABLED", None)
        _put("W7_WEBHOOK_DISPATCH_DISABLED", None)
    assert webhook_dispatch._global_kill_switch() is False
    # The style loaders read the same registry.
    assert _put("STYLE_FORCE_OFF", True).status_code == 200
    try:
        assert _common._style_force_off() is True
    finally:
        _put("STYLE_FORCE_OFF", None)
    assert _common._style_force_off() is False


def case_number_switch_override_reaches_its_consumer():
    import employees
    import smart_lists_api
    try:
        r = _put("SMART_LIST_MAX_ACTIVE", 3)
        assert r.status_code == 200 and r.json()["switch"]["effective"] == 3, r.text
        assert smart_lists_api._max_active() == 3
        r = _put("MAX_EMPLOYEES_PER_USER", 0)
        assert r.status_code == 200 and employees._max_employees() == 0, r.text
    finally:
        for name in ("SMART_LIST_MAX_ACTIVE", "MAX_EMPLOYEES_PER_USER"):
            assert _put(name, None).status_code == 200
    assert smart_lists_api._max_active() == 10 and employees._max_employees() == 20


def case_s4s_live_posting_override_reaches_its_consumer():
    import s4s_api
    assert s4s_api.live_posting() is True, "default on"
    try:
        assert _put("S4S_LIVE_POSTING", False).status_code == 200
        assert s4s_api.live_posting() is False, "the Settings override stops posting, no restart"
        os.environ["S4S_LIVE_POSTING"] = "off"
        assert _put("S4S_LIVE_POSTING", True).status_code == 200
        assert s4s_api.live_posting() is True, "the override beats an env off"
    finally:
        os.environ.pop("S4S_LIVE_POSTING", None)
        _put("S4S_LIVE_POSTING", None)
    assert s4s_api.live_posting() is True


def case_bad_writes_are_refused():
    assert _put("NOPE", True).status_code == 404
    for name, v in (("W7_WEBHOOK_DISPATCH_DISABLED", 1), ("W7_WEBHOOK_DISPATCH_DISABLED", "on"),
                    ("SMART_LIST_MAX_ACTIVE", 0), ("SMART_LIST_MAX_ACTIVE", True),
                    ("SMART_LIST_MAX_ACTIVE", 2.5), ("SMART_LIST_MAX_ACTIVE", 51),
                    ("SMART_LIST_MAX_ACTIVE", 10 ** 30), ("MAX_EMPLOYEES_PER_USER", 501)):
        r = _put(name, v)
        assert r.status_code == 422, (name, v, r.status_code, r.text)
    # Non-finite numbers: JSON has no literal, Python's json writes one, the relay must 422, not 500.
    for raw in (b'{"value": Infinity, "admin_password": "%s"}', b'{"value": NaN, "admin_password": "%s"}'):
        r = MASTER.put("/admin/system/switches/SMART_LIST_MAX_ACTIVE", content=raw % PW.encode(),
                       headers={"content-type": "application/json"})
        assert r.status_code in (400, 422), (raw, r.status_code, r.text)
    r = MASTER.put("/admin/system/switches/SMART_LIST_MAX_ACTIVE", json={"admin_password": PW})
    assert r.status_code == 422, r.text
    assert _switch("SMART_LIST_MAX_ACTIVE")["source"] == "default"


def case_a_write_needs_the_admin_password():
    assert _put("W7_WEBHOOK_DISPATCH_DISABLED", True, pw=None).status_code == 403
    assert _put("W7_WEBHOOK_DISPATCH_DISABLED", True, pw="wrong").status_code == 403
    assert _switch("W7_WEBHOOK_DISPATCH_DISABLED")["override"] is None


def case_non_master_cannot_write_a_switch():
    for client, code in ((OWNER, 403), (CHATTER, 403), (ANON, 401)):
        assert _put("W7_WEBHOOK_DISPATCH_DISABLED", True, client=client).status_code == code, client
    assert OWNER.get("/admin/system/switches").status_code == 403
    assert _switch("W7_WEBHOOK_DISPATCH_DISABLED")["override"] is None


def case_a_bad_env_value_falls_back_and_warns_once():
    import logging

    import runtime_switches
    seen: list[str] = []

    class _H(logging.Handler):
        def emit(self, rec):
            seen.append(rec.getMessage())
    h = _H()
    runtime_switches.log.addHandler(h)
    os.environ["SMART_LIST_MAX_ACTIVE"] = "lots"
    try:
        assert [runtime_switches.value("SMART_LIST_MAX_ACTIVE") for _ in range(5)] == [10] * 5
    finally:
        os.environ.pop("SMART_LIST_MAX_ACTIVE", None)
        runtime_switches.log.removeHandler(h)
    assert len([m for m in seen if "'lots' is not legal" in m]) == 1, seen


def case_a_failed_boot_load_is_reported_and_retried():
    import runtime_switches
    real = runtime_switches._read_rows

    async def broken():
        raise RuntimeError("db locked")
    runtime_switches._read_rows = broken
    runtime_switches._loaded = False
    try:
        try:
            asyncio.run(runtime_switches.load())
            raise AssertionError("load() must raise when the table cannot be read")
        except RuntimeError:
            pass
        assert MASTER.get("/admin/system/switches").json()["loaded"] is False
    finally:
        runtime_switches._read_rows = real
    asyncio.run(runtime_switches.load_until_loaded(interval_s=0))
    assert MASTER.get("/admin/system/switches").json()["loaded"] is True


def case_a_switch_write_is_audited_and_survives_a_reload():
    from sqlalchemy import select as _select

    import runtime_switches
    from db.models import Action, RuntimeSwitch
    path = "/admin/system/switches/OF_COTAG_ENABLED"
    assert _put("OF_COTAG_ENABLED", False).status_code == 200

    async def rows():
        async with get_session() as s:
            acts = (await s.execute(_select(Action).where(Action.action == f"PUT {path}"))).scalars().all()
            sw = await s.get(RuntimeSwitch, "OF_COTAG_ENABLED")
            return [a.payload_json or "" for a in acts], (sw.value_json, sw.updated_by) if sw else None
    payloads, row = asyncio.run(rows())
    assert len(payloads) == 1 and row == ("false", "agency_master"), (payloads, row)
    assert PW not in payloads[0] and '"***"' in payloads[0], "the audit row redacts the password"
    runtime_switches._overrides = {}            # a restart: the cache is empty until load()
    asyncio.run(runtime_switches.load())
    import media_cotag
    try:
        assert media_cotag.enabled() is False, "the stored override is back after a reload"
    finally:
        assert _put("OF_COTAG_ENABLED", None).status_code == 200
    assert media_cotag.enabled() is True


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
