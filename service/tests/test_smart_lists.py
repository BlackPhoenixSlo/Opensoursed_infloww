#!/usr/bin/env python3
"""Smart Lists tests — saved dynamic fan segments (Growth feature #1).

  case_resolve_empty_matches_all   blank rules → everyone matches.
  case_resolve_lifetime_spend      lifetime_spend threshold filters.
  case_resolve_recent_spend        recent_spend(days) reads the right window.
  case_resolve_last_active         last_active_days recency filter.
  case_resolve_never_active_fails  a never-active fan fails any recency rule.
  case_resolve_status_and_tag      status ==/!= and tag has/not_has.
  case_resolve_match_any_vs_all    OR vs AND across rules.
  case_preview_counts_real         POST /preview returns the true count+sample.
  case_crud_and_resolve            create → list → resolve saved list to ids.
  case_rename_collision_is_409...  renaming onto a taken name 409s, not 500s.
  case_resolve_v2_facts            ledger money (+between), date ops, enums.
  case_validate_v2                 scope/timeframe defaults, bad values 422.
  case_org_scope_and_timeframes    org sums the agency's creators; timeframe,
                                   highest, last amount, refunds excluded.
  case_snapshot_drives_status      roster snapshot: active/expired, renew, dates.
  case_activate_quota_and_queue    activate → rule + one coalesced job; quota 409.
  case_syncing_lock_409            PATCH / DELETE / deactivate refused while syncing.
  case_delete_queues_of_list_delete  delete_of_list=1 leaves a hidden tombstone
                                   + a plain sync job; the name is free again.
  case_tombstone_reads_as_missing...  a `deleting` row: routes 404, auto_follow
                                   resolves nothing.
  case_org_scope_stays_in_one_agency  a master's oversight link never joins
                                   another agency's creator to the org.
  case_stale_snapshot_falls_back...  an old roster crawl no longer decides status.

The DB-backed cases call the Relay as a signed-in owner (the shared two-Agency
fixture) and link each case's Creator to that owner's Agency, so they pass with
or without ALLOW_ANONYMOUS_ADMIN=1.

Run: ./venv/bin/python service/tests/test_smart_lists.py
"""
from __future__ import annotations

import _harness  # MUST be first
_harness.bootstrap()

import asyncio  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from db.engine import get_session  # noqa: E402
import _agency_fixtures as fx  # noqa: E402
import json  # noqa: E402

from sqlalchemy import select  # noqa: E402

from db.models import (  # noqa: E402
    Account, AutomationRule, Fan, ScheduledJob, SmartList, SubscriberSnapshot,
    Transaction, UserAccount,
)
import smart_lists_api  # noqa: E402
from smart_lists_api import _validate_rules, resolve  # noqa: E402

_IDS = fx.seed_two_agencies()
_OWNER = "agency_a_owner"
_client = fx.login_owner(_OWNER)


# ── pure resolve() — no DB needed ─────────────────────────────────────

def _fan(fid, spend=0, last=None, status=None, tags=None, recent=None):
    return {
        "fan_id": fid, "lifetime_spend": spend, "last_active_days": last,
        "status": status, "tags": tags or [], "recent_spend": recent or {},
    }


def case_resolve_empty_matches_all():
    fans = [_fan(1), _fan(2), _fan(3)]
    assert resolve({}, fans) == [1, 2, 3]
    assert resolve({"rules": []}, fans) == [1, 2, 3]


def case_resolve_lifetime_spend():
    fans = [_fan(1, spend=500), _fan(2, spend=10000), _fan(3, spend=25000)]
    rules = {"match": "all", "rules": [{"field": "lifetime_spend", "op": ">=", "value": 10000}]}
    assert resolve(rules, fans) == [2, 3], resolve(rules, fans)


def case_resolve_recent_spend():
    fans = [_fan(1, recent={30: 6000}), _fan(2, recent={30: 100}), _fan(3, recent={7: 9999})]
    rules = {"rules": [{"field": "recent_spend", "op": ">=", "value": 5000, "days": 30}]}
    # only fan 1 has ≥$50 in the 30-day window; fan 3's spend is in a 7d bucket.
    assert resolve(rules, fans) == [1], resolve(rules, fans)


def case_resolve_last_active():
    fans = [_fan(1, last=2.0), _fan(2, last=30.0), _fan(3, last=6.9)]
    rules = {"rules": [{"field": "last_active_days", "op": "<=", "value": 7}]}
    assert resolve(rules, fans) == [1, 3], resolve(rules, fans)


def case_resolve_never_active_fails():
    fans = [_fan(1, last=None), _fan(2, last=3.0)]
    rules = {"rules": [{"field": "last_active_days", "op": "<=", "value": 7}]}
    assert resolve(rules, fans) == [2], "never-active fan must NOT match a recency rule"


def case_resolve_status_and_tag():
    fans = [_fan(1, status="active", tags=["whale"]),
            _fan(2, status="expired", tags=["vip"]),
            _fan(3, status="active", tags=[])]
    r_status = {"rules": [{"field": "status", "op": "==", "value": "active"}]}
    assert resolve(r_status, fans) == [1, 3]
    r_neq = {"rules": [{"field": "status", "op": "!=", "value": "active"}]}
    assert resolve(r_neq, fans) == [2]
    r_tag = {"rules": [{"field": "tag", "op": "has", "value": "whale"}]}
    assert resolve(r_tag, fans) == [1]
    r_nottag = {"rules": [{"field": "tag", "op": "not_has", "value": "whale"}]}
    assert resolve(r_nottag, fans) == [2, 3]


def case_resolve_match_any_vs_all():
    fans = [_fan(1, spend=20000, status="expired"),
            _fan(2, spend=100, status="active"),
            _fan(3, spend=100, status="expired")]
    rules = [
        {"field": "lifetime_spend", "op": ">=", "value": 10000},
        {"field": "status", "op": "==", "value": "active"},
    ]
    assert resolve({"match": "all", "rules": rules}, fans) == []          # neither fan is both
    assert resolve({"match": "any", "rules": rules}, fans) == [1, 2]      # spend OR active


# ── DB-backed: preview + CRUD via the API ─────────────────────────────

async def _seed(aid):
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(Account(id=aid))
    async with get_session() as s:
        # the signed-in owner's Agency holds this Creator
        s.add(UserAccount(user_id=_IDS[_OWNER], account_id=aid))
        # fan 1: whale, active, active recently
        s.add(Fan(account_id=aid, fan_id=1, of_display_name="Whale",
                  lifetime_spend_cents=25000, subscription_status="active",
                  last_message_received_at=now - timedelta(days=1)))
        # fan 2: small spender, active
        s.add(Fan(account_id=aid, fan_id=2, of_display_name="Small",
                  lifetime_spend_cents=500, subscription_status="active",
                  last_message_received_at=now - timedelta(days=20)))
        # fan 3: mid spender via a recent tx, expired
        s.add(Fan(account_id=aid, fan_id=3, of_display_name="Mid",
                  lifetime_spend_cents=12000, subscription_status="expired",
                  last_message_received_at=now - timedelta(days=2)))
        s.add(Transaction(account_id=aid, fan_id=3, kind="ppv", amount_cents=8000,
                          occurred_at=now - timedelta(days=3)))


def case_preview_counts_real():
    aid = "sl_prev"
    asyncio.run(_seed(aid))
    # ≥ $100 lifetime → fans 1 and 3 (2 is $5)
    r = _client.post("/admin/smart-lists/preview", json={
        "account_id": aid,
        "rules": {"match": "all", "rules": [{"field": "lifetime_spend", "op": ">=", "value": 10000}]},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 2, body
    assert body["total_fans"] == 3, body
    assert {s["fan_id"] for s in body["sample"]} == {1, 3}, body
    # recent_spend in 7d ≥ $50 → only fan 3 (has an $80 tx 3 days ago)
    r2 = _client.post("/admin/smart-lists/preview", json={
        "account_id": aid,
        "rules": {"rules": [{"field": "recent_spend", "op": ">=", "value": 5000, "days": 7}]},
    })
    assert r2.json()["count"] == 1, r2.json()


def case_crud_and_resolve():
    aid = "sl_crud"
    asyncio.run(_seed(aid))
    # create
    r = _client.post("/admin/smart-lists", json={
        "account_id": aid, "name": "Whales",
        "rules": {"rules": [{"field": "lifetime_spend", "op": ">=", "value": 10000}]},
    })
    assert r.status_code == 200, r.text
    lid = r.json()["id"]
    # list
    lst = _client.get(f"/admin/smart-lists?account_id={aid}").json()["lists"]
    assert any(x["id"] == lid and x["name"] == "Whales" for x in lst), lst
    # duplicate name → 409
    dup = _client.post("/admin/smart-lists", json={"account_id": aid, "name": "Whales"})
    assert dup.status_code == 409, dup.text
    # resolve → fan ids 1 and 3
    res = _client.get(f"/admin/smart-lists/{lid}/resolve").json()
    assert res["fan_ids"] == [1, 3], res
    # bad rule rejected
    bad = _client.post("/admin/smart-lists", json={
        "account_id": aid, "name": "Bad",
        "rules": {"rules": [{"field": "nope", "op": ">=", "value": 1}]},
    })
    assert bad.status_code == 422, bad.text
    # delete
    d = _client.delete(f"/admin/smart-lists/{lid}")
    assert d.status_code == 200 and d.json()["deleted"] == lid


def case_rename_collision_is_409_not_500():
    """Renaming a segment onto an existing name must 409. UNIQUE(account_id,
    name) raises IntegrityError on flush; before the pre-check that escaped the
    handler as a raw 500."""
    aid = "sl_rename"
    asyncio.run(_seed(aid))
    a = _client.post("/admin/smart-lists", json={"account_id": aid, "name": "Alpha"})
    b = _client.post("/admin/smart-lists", json={"account_id": aid, "name": "Beta"})
    assert a.status_code == 200 and b.status_code == 200, (a.text, b.text)

    clash = _client.patch(f"/admin/smart-lists/{b.json()['id']}", json={"name": "Alpha"})
    assert clash.status_code == 409, f"expected 409, got {clash.status_code}: {clash.text}"

    # The failed rename must not have stuck.
    names = {x["name"] for x in _client.get(f"/admin/smart-lists?account_id={aid}").json()["lists"]}
    assert names == {"Alpha", "Beta"}, names
    # Renaming to its OWN name is a no-op, not a self-collision.
    same = _client.patch(f"/admin/smart-lists/{b.json()['id']}", json={"name": "Beta"})
    assert same.status_code == 200, same.text


# ── v2 conditions ─────────────────────────────────────────────────────

def _fan2(fid, *, status=None, renew=None, **facts):
    f = _fan(fid, status=status)
    f["renew"] = renew
    f["facts"] = {k.replace("__", ":"): v for k, v in facts.items()}
    return f


def case_resolve_v2_facts():
    fans = [
        _fan2(1, total_spend__creator__30d=6000, expires_at=-2.0, status="active", renew="off"),
        _fan2(2, total_spend__creator__30d=200, expires_at=-20.0, status="active", renew="on"),
        _fan2(3, total_spend__org__30d=9000, expires_at=5.0, status="expired"),
    ]
    spend = {"field": "total_spend", "op": ">=", "value": 5000, "scope": "creator", "timeframe": "30d"}
    assert resolve({"rules": [spend]}, fans) == [1]
    org = {**spend, "scope": "org"}
    assert resolve({"rules": [org]}, fans) == [3]
    between = {**spend, "op": "between", "value": [100, 6000]}
    assert resolve({"rules": [between]}, fans) == [1, 2]
    soon = {"field": "expires_at", "op": "within_next", "value": 3}
    assert resolve({"rules": [soon]}, fans) == [1]
    gone = {"field": "expires_at", "op": "within_last", "value": 7}
    assert resolve({"rules": [gone]}, fans) == [3]
    old = {"field": "expires_at", "op": "more_than", "value": 1}
    assert resolve({"rules": [old]}, fans) == [3]
    renew_off = {"field": "renew", "op": "==", "value": "off"}
    assert resolve({"rules": [renew_off]}, fans) == [1]
    # a missing date never matches; a missing spend is $0
    assert resolve({"rules": [{"field": "sub_start", "op": "more_than", "value": 0}]}, fans) == []
    assert resolve({"rules": [{**spend, "op": "<=", "value": 0}]}, fans) == [3]


def case_validate_v2():
    out = _validate_rules({"rules": [
        {"field": "tips_spend", "op": ">=", "value": "500"},
        {"field": "last_spend_amount", "op": ">", "value": 1, "timeframe": "7d"},
        {"field": "sub_start", "op": "between", "value": [30, 90]},
    ]})["rules"]
    assert out[0] == {"field": "tips_spend", "op": ">=", "value": 500.0,
                      "scope": "creator", "timeframe": "all"}, out[0]
    assert "timeframe" not in out[1], out[1]                # last amount has none
    assert out[2]["value"] == [30.0, 90.0], out[2]
    bad = [
        {"field": "total_spend", "op": ">=", "value": 1, "scope": "galaxy"},
        {"field": "total_spend", "op": ">=", "value": 1, "timeframe": "1y"},
        {"field": "sub_start", "op": "within_next", "value": 3},
        {"field": "sub_start", "op": "between", "value": [9, 1]},
        {"field": "renew", "op": "==", "value": "maybe"},
    ]
    for rule in bad:
        try:
            _validate_rules({"rules": [rule]})
        except Exception as e:  # HTTPException 422
            assert getattr(e, "status_code", None) == 422, (rule, e)
        else:
            raise AssertionError(f"accepted {rule}")


async def _link(aid):
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
    async with get_session() as s:
        s.add(UserAccount(user_id=_IDS[_OWNER], account_id=aid))


def _preview_ids(aid, rule) -> set[int]:
    r = _client.post("/admin/smart-lists/preview",
                     json={"account_id": aid, "rules": {"rules": [rule]}})
    assert r.status_code == 200, r.text
    return {x["fan_id"] for x in r.json()["sample"]}


def case_org_scope_and_timeframes():
    a, b = "sl_org_a", "sl_org_b"
    now = datetime.utcnow()

    async def seed():
        await _link(a)
        await _link(b)
        async with get_session() as s:
            s.add(Fan(account_id=a, fan_id=5))
            s.add(Fan(account_id=a, fan_id=6))
            s.add(Transaction(account_id=a, fan_id=5, kind="tip", amount_cents=1000,
                              occurred_at=now - timedelta(days=40)))
            s.add(Transaction(account_id=a, fan_id=5, kind="ppv_message", amount_cents=2500,
                              occurred_at=now - timedelta(days=2)))
            s.add(Transaction(account_id=b, fan_id=5, kind="tip", amount_cents=7000,
                              occurred_at=now - timedelta(days=1)))
            s.add(Transaction(account_id=a, fan_id=6, kind="tip", amount_cents=9900,
                              occurred_at=now - timedelta(days=1), status="refunded"))
    asyncio.run(seed())

    tot = {"field": "total_spend", "op": ">=", "value": 3000}
    assert _preview_ids(a, tot) == {5}                                       # 1000 + 2500
    assert _preview_ids(a, {**tot, "value": 5000}) == set()                  # creator scope only
    assert _preview_ids(a, {**tot, "value": 10000, "scope": "org"}) == {5}   # + 7000 on creator b
    assert _preview_ids(a, {**tot, "timeframe": "30d"}) == set()             # only 2500 in 30d
    assert _preview_ids(a, {"field": "tips_spend", "op": ">=", "value": 1000,
                            "scope": "org", "timeframe": "7d"}) == {5}
    assert _preview_ids(a, {"field": "highest_spend", "op": "==", "value": 7000,
                            "scope": "org"}) == {5}
    assert _preview_ids(a, {"field": "last_spend_amount", "op": "==", "value": 2500}) == {5}
    assert _preview_ids(a, {"field": "last_purchase_at", "op": "within_last", "value": 3}) == {5}
    # the refunded $99 tip never counts
    assert _preview_ids(a, {"field": "tips_spend", "op": ">", "value": 0}) == {5}


def case_snapshot_drives_status():
    aid = "sl_snap"
    now = datetime.utcnow()

    async def seed():
        await _link(aid)
        async with get_session() as s:
            for f in (7, 8, 9):
                s.add(Fan(account_id=aid, fan_id=f))
            s.add(SubscriberSnapshot(account_id=aid, fan_id=7, seen_at=now, renew_on=False,
                                     subscribe_at=now - timedelta(days=3),
                                     expired_at=now + timedelta(days=2)))
            s.add(SubscriberSnapshot(account_id=aid, fan_id=8, seen_at=now - timedelta(days=5),
                                     renew_on=True, subscribe_at=now - timedelta(days=60),
                                     expired_at=now - timedelta(days=4),
                                     resubscribed_at=now - timedelta(days=40)))
    asyncio.run(seed())

    def ids(rule):
        return _preview_ids(aid, rule)

    assert ids({"field": "status", "op": "==", "value": "active"}) == {7}
    assert ids({"field": "status", "op": "==", "value": "expired"}) == {8}
    assert ids({"field": "renew", "op": "==", "value": "off"}) == {7}
    assert ids({"field": "renew", "op": "==", "value": "on"}) == set()   # 8 is not active
    assert ids({"field": "sub_start", "op": "within_last", "value": 7}) == {7}
    assert ids({"field": "expires_at", "op": "within_next", "value": 3}) == {7}
    assert ids({"field": "resubscribed_at", "op": "more_than", "value": 30}) == {8}


async def _jobs(aid):
    async with get_session() as s:
        return [json.loads(j.payload_json) for j in (await s.execute(
            select(ScheduledJob).where(ScheduledJob.account_id == aid,
                                       ScheduledJob.kind == "smart_list_sync"))).scalars()]


def case_activate_quota_and_queue():
    aid = "sl_activate"
    asyncio.run(_link(aid))
    a = _client.post("/admin/smart-lists", json={"account_id": aid, "name": "A"}).json()
    b = _client.post("/admin/smart-lists", json={"account_id": aid, "name": "B"}).json()
    assert a["is_active"] is False and a["sync_state"] is None, a
    real = smart_lists_api.MAX_ACTIVE
    smart_lists_api.MAX_ACTIVE = 1
    try:
        r = _client.post(f"/admin/smart-lists/{a['id']}/activate")
        assert r.status_code == 200 and r.json()["is_active"] is True, r.text
        again = _client.post(f"/admin/smart-lists/{a['id']}/activate")
        assert again.status_code == 200, again.text                  # idempotent
        over = _client.post(f"/admin/smart-lists/{b['id']}/activate")
        assert over.status_code == 409 and "maximum of 1" in over.text, over.text
    finally:
        smart_lists_api.MAX_ACTIVE = real
    assert asyncio.run(_jobs(aid)) == [{}], "one coalesced sync job"

    async def rules():
        async with get_session() as s:
            return (await s.execute(select(AutomationRule).where(
                AutomationRule.account_id == aid,
                AutomationRule.kind == "smart_list_sync"))).scalars().all()
    rs = asyncio.run(rules())
    assert len(rs) == 1 and rs[0].is_enabled, rs
    lst = _client.get(f"/admin/smart-lists?account_id={aid}").json()
    assert lst["max_active"] == real, lst
    off = _client.post(f"/admin/smart-lists/{a['id']}/deactivate")
    assert off.status_code == 200 and off.json()["is_active"] is False, off.text


async def _set_state(list_id, state, of_list_id=None):
    async with get_session() as s:
        row = await s.get(SmartList, list_id)
        row.sync_state = state
        if of_list_id is not None:
            row.of_list_id = of_list_id


def case_syncing_lock_409():
    aid = "sl_lock"
    asyncio.run(_link(aid))
    lid = _client.post("/admin/smart-lists", json={"account_id": aid, "name": "L"}).json()["id"]
    _client.post(f"/admin/smart-lists/{lid}/activate")
    asyncio.run(_set_state(lid, "syncing"))
    assert _client.patch(f"/admin/smart-lists/{lid}", json={"name": "L2"}).status_code == 409
    assert _client.post(f"/admin/smart-lists/{lid}/deactivate").status_code == 409
    assert _client.delete(f"/admin/smart-lists/{lid}").status_code == 409
    asyncio.run(_set_state(lid, "ok"))
    r = _client.patch(f"/admin/smart-lists/{lid}", json={"name": "L2"})
    assert r.status_code == 200 and r.json()["name"] == "L2", r.text


def case_delete_queues_of_list_delete():
    aid = "sl_del"
    asyncio.run(_link(aid))
    lid = _client.post("/admin/smart-lists", json={"account_id": aid, "name": "D"}).json()["id"]
    asyncio.run(_set_state(lid, "ok", of_list_id=4242))
    r = _client.delete(f"/admin/smart-lists/{lid}?delete_of_list=true")
    assert r.status_code == 200 and r.json()["of_list_delete_queued"] is True, r.text
    # A tombstone the worker finishes — the job carries no OF list id at all.
    assert asyncio.run(_jobs(aid)) == [{}]
    row = asyncio.run(_get(lid))
    assert row.sync_state == "deleting" and row.of_list_id == 4242 and not row.is_active
    assert _client.get(f"/admin/smart-lists?account_id={aid}").json()["lists"] == []
    assert _client.get(f"/admin/smart-lists/{lid}/resolve").status_code == 404
    again = _client.post("/admin/smart-lists", json={"account_id": aid, "name": "D"})
    assert again.status_code == 200, again.text                    # the name is free


def case_tombstone_reads_as_missing_everywhere():
    from automations.auto_follow import _resolve_smart_list
    aid = "sl_tomb"

    async def seed():
        await _link(aid)
        async with get_session() as s:
            s.add(Fan(account_id=aid, fan_id=21, lifetime_spend_cents=50000))
            row = SmartList(account_id=aid, name="T", rules_json=json.dumps({"rules": []}),
                            of_list_id=77, sync_state="deleting")
            s.add(row)
            await s.flush()
            return row.id
    lid = asyncio.run(seed())
    assert asyncio.run(_resolve_smart_list(lid, aid)) == [], "auto_follow must not target it"
    assert _client.get(f"/admin/smart-lists/{lid}/resolve").status_code == 404
    assert _client.post(f"/admin/smart-lists/{lid}/activate").status_code == 404
    assert _client.patch(f"/admin/smart-lists/{lid}", json={"name": "U"}).status_code == 404
    asyncio.run(_set_state(lid, "ok"))
    assert asyncio.run(_resolve_smart_list(lid, aid)) == [21]       # a live row still resolves


async def _get(lid):
    async with get_session() as s:
        return await s.get(SmartList, lid)


def case_org_scope_stays_in_one_agency():
    master, b_owner = _IDS["agency_master"], _IDS["agency_b_owner"]
    x, y, z = "sl_org_x", "sl_org_y", "sl_org_z"

    async def go():
        async with get_session() as s:
            for aid in (x, y, z):
                s.add(Account(id=aid))
        async with get_session() as s:
            s.add(UserAccount(user_id=master, account_id=x))
            s.add(UserAccount(user_id=master, account_id=z))
            s.add(UserAccount(user_id=master, account_id=y))   # oversight link
            s.add(UserAccount(user_id=b_owner, account_id=y))  # y is agency B's
        async with get_session() as s:
            return await smart_lists_api.org_account_ids(s, x)
    assert asyncio.run(go()) == [x, z]


def case_stale_snapshot_falls_back_to_fan_row():
    aid = "sl_snap_stale"
    old = datetime.utcnow() - timedelta(days=2)

    async def seed():
        await _link(aid)
        async with get_session() as s:
            s.add(Fan(account_id=aid, fan_id=10, subscription_status="active"))
            s.add(Fan(account_id=aid, fan_id=11, subscription_status="active"))
            s.add(SubscriberSnapshot(account_id=aid, fan_id=10, seen_at=old))
            s.add(SubscriberSnapshot(account_id=aid, fan_id=11, seen_at=old - timedelta(days=9),
                                     resubscribed_at=old - timedelta(days=1)))
    asyncio.run(seed())
    # The stale crawl would call 11 expired; the fan row (newer) says active.
    assert _preview_ids(aid, {"field": "status", "op": "==", "value": "active"}) == {10, 11}
    # A recorded return is history — still usable off a stale snapshot.
    assert _preview_ids(aid, {"field": "resubscribed_at", "op": "within_last", "value": 30}) == {11}


def case_ghost_audience_idle_days():
    """Active fans with no purchase (rebills don't count), no inbound message
    and no (re)subscription in 30+ days. No date at all never matches."""
    aid = "sl_ghost"
    now = datetime.utcnow()
    old = now - timedelta(days=60)

    async def seed():
        await _link(aid)
        async with get_session() as s:
            s.add(Fan(account_id=aid, fan_id=23, last_message_received_at=now - timedelta(days=3)))
            s.add(Fan(account_id=aid, fan_id=26))  # never seen anywhere: no date
            for f in (20, 21, 22, 24, 25, 27):
                s.add(Fan(account_id=aid, fan_id=f))
            for f in (20, 21, 22, 23, 27):
                s.add(SubscriberSnapshot(account_id=aid, fan_id=f, seen_at=now, subscribe_at=old))
            s.add(SubscriberSnapshot(account_id=aid, fan_id=24, seen_at=now,
                                     subscribe_at=now - timedelta(days=10)))
            s.add(SubscriberSnapshot(account_id=aid, fan_id=25, seen_at=now - timedelta(days=5),
                                     subscribe_at=old))  # expired
            s.add(Transaction(account_id=aid, fan_id=21, kind="rebill", amount_cents=999,
                              occurred_at=now - timedelta(days=5)))
            s.add(Transaction(account_id=aid, fan_id=22, kind="tip", amount_cents=500,
                              occurred_at=now - timedelta(days=5), status="pending"))
            s.add(Transaction(account_id=aid, fan_id=27, kind="tip", amount_cents=500,
                              occurred_at=now - timedelta(days=2), status="refunded"))
    asyncio.run(seed())

    ghost = {"field": "idle_days", "op": "more_than", "value": 30}
    assert _preview_ids(aid, ghost) == {20, 21, 25, 27}
    r = _client.post("/admin/smart-lists/preview", json={"account_id": aid, "rules": {
        "match": "all", "rules": [{"field": "status", "op": "==", "value": "active"}, ghost]}})
    assert r.status_code == 200, r.text
    assert {x["fan_id"] for x in r.json()["sample"]} == {20, 21, 27}
    assert _preview_ids(aid, {"field": "idle_days", "op": "within_last", "value": 7}) == {22, 23}
    # it reads the roster's sub date, so the sync worker refreshes the roster
    assert smart_lists_api.uses_subscription_facts({"rules": [ghost]})
    _validate_rules({"rules": [ghost]})
    try:
        _validate_rules({"rules": [{**ghost, "op": "within_next"}]})
    except Exception:
        pass
    else:
        raise AssertionError("within_next accepted on idle_days")


_harness.run(
    case_resolve_empty_matches_all,
    case_resolve_lifetime_spend,
    case_resolve_recent_spend,
    case_resolve_last_active,
    case_resolve_never_active_fails,
    case_resolve_status_and_tag,
    case_resolve_match_any_vs_all,
    case_preview_counts_real,
    case_crud_and_resolve,
    case_rename_collision_is_409_not_500,
    case_resolve_v2_facts,
    case_validate_v2,
    case_org_scope_and_timeframes,
    case_snapshot_drives_status,
    case_activate_quota_and_queue,
    case_syncing_lock_409,
    case_delete_queues_of_list_delete,
    case_tombstone_reads_as_missing_everywhere,
    case_org_scope_stays_in_one_agency,
    case_stale_snapshot_falls_back_to_fan_row,
    case_ghost_audience_idle_days,
)
