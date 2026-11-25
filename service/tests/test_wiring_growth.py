#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import asyncio  # noqa: E402
import os  # noqa: E402

from sqlalchemy import delete, select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import automation_executor as ax  # noqa: E402
import automation_registry as reg  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AutomationRule, PromoCampaign, ScheduledJob  # noqa: E402

IDS = fx.seed_two_agencies()
AID = IDS["creator_a"]
UI = fx.login_owner("agency_a_owner")

os.environ["PROMO_CREATE_HOST_ID"] = "test-box"

reg.load_automation_plugins()
from automations import promo_reactivate  # noqa: E402
import automations.send_mass_message as send_mass_message  # noqa: E402



def _run(coro):
    return asyncio.run(coro)


async def _reset() -> None:
    async with get_session() as s:
        await s.execute(delete(ScheduledJob).where(ScheduledJob.account_id == AID))
        await s.execute(delete(AutomationRule).where(AutomationRule.account_id == AID))


async def _clear_jobs() -> None:
    async with get_session() as s:
        await s.execute(delete(ScheduledJob).where(ScheduledJob.account_id == AID))


async def _pending(kind: str, rule_id: int | None = None) -> list[ScheduledJob]:
    async with get_session() as s:
        q = select(ScheduledJob).where(ScheduledJob.account_id == AID,
                                       ScheduledJob.kind == kind,
                                       ScheduledJob.status == "pending")
        if rule_id is not None:
            q = q.where(ScheduledJob.rule_id == rule_id)
        return list((await s.execute(q)).scalars())


async def _supervisor_pass(kind: str) -> None:
    await ax._materialize_due_rules()
    for aid, k, _op, *_ in await ax._due_job_pairs():
        if aid == AID and k == kind:
            await ax.run_once(aid, k)


class _Recorder:
    def __init__(self, kind: str):
        self.kind, self.calls, self._orig = kind, [], None

    async def __call__(self, account_id, payload, *, run_id):
        self.calls.append(dict(payload or {}))
        return {"recorded": True}

    def __enter__(self):
        self._orig = reg._REGISTRY[self.kind]
        reg._REGISTRY[self.kind] = self
        return self

    def __exit__(self, *exc):
        reg._REGISTRY[self.kind] = self._orig


def _create(kind: str, body: dict) -> dict:
    r = UI.post("/admin/automation-rules", json={"account_id": AID, "kind": kind, **body})
    assert r.status_code == 200, f"create {kind}: {r.status_code} {r.text}"
    return r.json()


def _patch(rid: int, body: dict) -> dict:
    r = UI.patch(f"/admin/automation-rules/{rid}", json=body)
    assert r.status_code == 200, f"patch {rid}: {r.status_code} {r.text}"
    return r.json()


def _listed(rid: int) -> dict:
    r = UI.get(f"/admin/automation-rules?account_id={AID}")
    assert r.status_code == 200, r.text
    return next(x for x in r.json()["rules"] if x["id"] == rid)


def _check_switch(kind: str, create_body: dict, off_body, on_body) -> None:
    _run(_reset())
    rule = _create(kind, {**create_body, "is_enabled": True})
    rid = rule["id"]
    assert _listed(rid)["is_enabled"] is True
    _run(ax._materialize_due_rules())
    jobs = _run(_pending(kind, rid))
    assert len(jobs) == 1, f"{kind}: ON did not materialize a job ({len(jobs)})"

    _run(_clear_jobs())
    out = _patch(rid, off_body)
    assert out["is_enabled"] is False and _listed(rid)["is_enabled"] is False, out
    _run(ax._materialize_due_rules())
    assert _run(_pending(kind)) == [], f"{kind}: OFF still materialized a job"

    out = _patch(rid, on_body)
    assert out["is_enabled"] is True, out
    _run(ax._materialize_due_rules())
    assert len(_run(_pending(kind, rid))) == 1, f"{kind}: ON again did not schedule"



AF_PAYLOAD = {"action": "follow", "daily_cap": 5, "dry_run": True,
              "targets": {"source": "fan_ids", "fan_ids": [9001, 9002]}}
PR_PAYLOAD = {"max_reactivations": 0, "dry_run": True}
AS_TRIGGER = {"every_seconds": 6 * 3600}
AS_PAYLOAD = {"folder_id": 7, "per_run": 1, "hours_to_live": 6, "remove_vault_dupe": True}
AP_PAYLOAD = {"posts": [{"text": "hello"}]}
MP_PAYLOAD = {"messages": [{"text": "hi all", "unsend_after_hours": 8}]}
UN_PAYLOAD = {"policy": {"mass_text_hours": 4}}



def case_auto_follow_switch_schedules_and_parks():
    def body(on):
        return {"every_seconds": 600, "payload": AF_PAYLOAD, "is_enabled": on}
    _check_switch("auto_follow", {"name": "Auto-follow",
                                  "every_seconds": 600, "payload": AF_PAYLOAD},
                  body(False), body(True))


def case_auto_follow_dry_run_switch_reaches_the_sender():
    follows: list[int] = []

    class _FakeClient:
        def get_user(self, fid):
            return {"subscribePrice": 0}

        def follow_user(self, fid):
            follows.append(int(fid))

    orig_client = ax._make_client
    ax._make_client = lambda _aid: _FakeClient()
    try:
        _run(_reset())
        rid = _create("auto_follow", {"every_seconds": 600, "payload": AF_PAYLOAD})["id"]
        _run(_supervisor_pass("auto_follow"))
        assert follows == [], f"dry_run=true still followed: {follows}"

        _run(_clear_jobs())
        _patch(rid, {"every_seconds": 600, "is_enabled": True,
                     "payload": {**AF_PAYLOAD, "dry_run": False}})
        _run(_supervisor_pass("auto_follow"))
        assert sorted(follows) == [9001, 9002], f"dry_run=false did not act: {follows}"

        follows.clear()
        _run(_clear_jobs())
        _patch(rid, {"payload": {k: v for k, v in AF_PAYLOAD.items() if k != "dry_run"}})
        _run(_supervisor_pass("auto_follow"))
        assert follows == [], f"absent dry_run ran live: {follows}"
    finally:
        ax._make_client = orig_client


def case_promo_reactivate_card_switch_schedules_and_parks():
    def body(on):
        return {"every_seconds": 3600, "payload": PR_PAYLOAD, "is_enabled": on}
    _check_switch("promo_reactivate", {"name": "Keep promos running",
                                       "every_seconds": 3600, "payload": PR_PAYLOAD},
                  body(False), body(True))


def case_promo_keep_running_switch_gates_the_runtime():
    async def _seed() -> int:
        async with get_session() as s:
            await s.execute(delete(PromoCampaign).where(PromoCampaign.account_id == AID))
            row = PromoCampaign(account_id=AID, of_promo_id=4242, name="Half off",
                                discount_percent=50, subscribe_counts=0, subscribe_days=0)
            s.add(row)
            await s.flush()
            return row.id

    pid = _run(_seed())
    orig = promo_reactivate.fetch_of_promos

    async def _nothing_live(_aid, need_ids=None, **_kw):
        return []

    promo_reactivate.fetch_of_promos = _nothing_live
    try:
        r = UI.patch(f"/admin/promotions/{pid}", json={"auto_reactivate": True})
        assert r.status_code == 200 and r.json()["auto_reactivate"] is True, r.text
        out = _run(ax.run_once(AID, "promo_reactivate", payload={"dry_run": True}))
        assert [w["id"] for w in out.get("would_reactivate", [])] == [pid], out

        r = UI.patch(f"/admin/promotions/{pid}", json={"auto_reactivate": False})
        assert r.status_code == 200 and r.json()["auto_reactivate"] is False, r.text
        out = _run(ax.run_once(AID, "promo_reactivate", payload={"dry_run": True}))
        assert out.get("managed") == 0 and not out.get("would_reactivate"), out
    finally:
        promo_reactivate.fetch_of_promos = orig


def case_auto_stories_switch_schedules_and_parks():
    def body(on):
        return {"trigger": AS_TRIGGER, "payload": AS_PAYLOAD, "is_enabled": on}
    _check_switch("auto_stories", {"name": "Auto stories", "trigger": AS_TRIGGER,
                                   "payload": AS_PAYLOAD},
                  body(False), body(True))


def case_auto_posts_row_switch_schedules_and_parks():
    _check_switch("auto_posts", {"name": "Auto posts", "every_seconds": 3600,
                                 "payload": AP_PAYLOAD},
                  {"is_enabled": False}, {"is_enabled": True})


def case_mass_premade_row_switch_schedules_and_parks():
    _check_switch("mass_premade", {"name": "Premade mass", "every_seconds": 3600,
                                   "payload": MP_PAYLOAD},
                  {"is_enabled": False}, {"is_enabled": True})


def case_unsend_auto_switch_schedules_and_parks():
    def body(on):
        return {"is_enabled": on, "every_seconds": 3600, "payload": UN_PAYLOAD}
    _check_switch("unsend_messages", {"name": "Auto-unsend mass", "every_seconds": 3600,
                                      "payload": UN_PAYLOAD},
                  body(False), body(True))



_RULE_KINDS = {
    "auto_follow": {"every_seconds": 600, "payload": AF_PAYLOAD},
    "promo_reactivate": {"every_seconds": 3600, "payload": PR_PAYLOAD},
    "auto_stories": {"trigger": AS_TRIGGER, "payload": AS_PAYLOAD},
    "auto_posts": {"every_seconds": 3600, "payload": AP_PAYLOAD},
    "mass_premade": {"every_seconds": 3600, "payload": MP_PAYLOAD},
    "unsend_messages": {"every_seconds": 3600, "payload": UN_PAYLOAD},
}


def case_off_cancels_an_already_queued_job():
    ran = []
    for kind, body in _RULE_KINDS.items():
        _run(_reset())
        rid = _create(kind, body)["id"]
        _run(ax._materialize_due_rules())
        assert len(_run(_pending(kind, rid))) == 1, f"{kind}: setup — no job queued"
        _patch(rid, {"is_enabled": False})
        with _Recorder(kind) as rec:
            _run(_supervisor_pass(kind))
        if rec.calls:
            ran.append(kind)
    assert not ran, f"ran after OFF: {ran}"


def case_off_stops_an_auto_posts_drip():
    _run(_reset())
    rid = _create("auto_posts", {"every_seconds": 3600, "payload": {
        "posts": [{"text": ""}, {"text": "second", "delay_minutes": 0}]}})["id"]
    _run(_supervisor_pass("auto_posts"))
    drip = _run(_pending("auto_posts"))
    assert len(drip) == 1, f"setup: expected one drip job, got {len(drip)}"
    _patch(rid, {"is_enabled": False})
    with _Recorder("auto_posts") as rec:
        _run(_supervisor_pass("auto_posts"))
    assert rec.calls == [], f"drip posted after OFF: {rec.calls}"


def case_off_stops_a_mass_premade_drip():
    orig = send_mass_message.run

    async def _skipped(_aid, _payload, *, run_id):
        return {"status": "skipped", "reason": "no_audience"}

    send_mass_message.run = _skipped
    try:
        _run(_reset())
        rid = _create("mass_premade", {"every_seconds": 3600, "payload": {
            "messages": [{"text": "first"}, {"text": "second", "delay_minutes": 0}]}})["id"]
        _run(_supervisor_pass("mass_premade"))
    finally:
        send_mass_message.run = orig
    drip = _run(_pending("mass_premade"))
    assert len(drip) == 1, f"setup: expected one drip job, got {len(drip)}"
    _patch(rid, {"is_enabled": False})
    with _Recorder("mass_premade") as rec:
        _run(_supervisor_pass("mass_premade"))
    assert rec.calls == [], f"drip broadcast after OFF: {rec.calls}"


async def _switch_off_directly(rid: int) -> None:
    async with get_session() as s:
        (await s.get(AutomationRule, rid)).is_enabled = False


def case_off_mid_run_leaves_no_follow_on():
    from automations import auto_posts
    import account_page

    _run(_reset())
    rid = _create("auto_posts", {"every_seconds": 3600, "payload": {"posts": [
        {"text": "first", "price": 5}, {"text": "second", "delay_minutes": 0}]}})["id"]
    orig_paid = account_page.is_paid_page

    async def _paid_and_off(_aid):
        await _switch_off_directly(rid)
        return True

    account_page.is_paid_page = _paid_and_off
    try:
        _run(_supervisor_pass("auto_posts"))
    finally:
        account_page.is_paid_page = orig_paid
    assert _run(_pending("auto_posts")) == [], "auto_posts drip enqueued after OFF"
    assert auto_posts

    _run(_reset())
    rid = _create("mass_premade", {"every_seconds": 3600, "payload": {
        "messages": [{"text": "first"}, {"text": "second", "delay_minutes": 0}]}})["id"]
    orig = send_mass_message.run

    async def _send_and_off(_aid, _payload, *, run_id):
        await _switch_off_directly(rid)
        return {"status": "skipped", "reason": "no_audience"}

    send_mass_message.run = _send_and_off
    try:
        _run(_supervisor_pass("mass_premade"))
    finally:
        send_mass_message.run = orig
    assert _run(_pending("mass_premade")) == [], "mass_premade drip enqueued after OFF"


def case_follow_on_jobs_do_not_move_the_rule_cadence():
    from datetime import datetime, timedelta
    _run(_reset())
    rid = _create("auto_posts", {"every_seconds": 3600, "payload": {
        "posts": [{"text": ""}, {"text": "second", "delay_minutes": 0}]}})["id"]
    _run(_supervisor_pass("auto_posts"))

    async def _age_the_fire():
        async with get_session() as s:
            jobs = list((await s.execute(select(ScheduledJob).where(
                ScheduledJob.rule_id == rid))).scalars())
            drips = [j for j in jobs if '"_followup"' in j.payload_json]
            fires = [j for j in jobs if j not in drips]
            assert len(drips) == 1 and len(fires) == 1, (len(drips), len(fires))
            fires[0].created_at = datetime.utcnow() - timedelta(seconds=3700)
            drips[0].status = "done"

    _run(_age_the_fire())
    _run(ax._materialize_due_rules())
    assert len(_run(_pending("auto_posts", rid))) == 1, \
        "the drip's created_at pushed the rule's next fire back"


_harness.run()
