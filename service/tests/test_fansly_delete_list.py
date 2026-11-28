#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
import uuid  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402

from sqlalchemy import delete, select  # noqa: E402

import accounts as account_registry  # noqa: E402

_TMP = tempfile.TemporaryDirectory(prefix="fansly_delete_list_")
account_registry.SESSIONS_DIR = Path(_TMP.name)
account_registry.ACCOUNTS_DIR = Path(_TMP.name) / "accounts"
account_registry.ACTIVE_FILE = Path(_TMP.name) / "active.json"
account_registry.MIGRATED_MARKER = Path(_TMP.name) / ".migrated"

import automation_executor as ax  # noqa: E402
import server  # noqa: E402
import side_effect_gate  # noqa: E402
import smart_lists_api  # noqa: E402
from automations import auto_follow, lifecycle_messages as lm, smart_list_sync as sls  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AutomationRun, Fan, SmartList, SubscriberSnapshot, User, UserAccount  # noqa: E402
import fansly_backend  # noqa: E402
from fansly_shim import FanslyShimClient, platform_unsupported  # noqa: E402

http = _harness.make_client()

FANSLY_AID = "8803601"
OF_AID = "8803602"
LIST = "900000000000000301"
PROOF = "900000000000000002"
REAL = "900000000000000777"
REASON = "platform_lacks:delete_list"
REMOVE = ("POST", "/lists/remove", {"listId": LIST})
READ = (("GET", "/lists/account", {"itemId": ""}),
        ("GET", "/lists/itemsnew", {"listId": LIST, "limit": "50", "sortMode": "3"}))


class _Shim(FanslyShimClient):
    def __init__(self, members=(), lists=(LIST,)) -> None:
        self.members, self.lists = list(members), lists
        self.calls: list[tuple] = []

    def _request(self, method, path, *, params=None, json_body=None, **_kw):
        self.calls.append((method, path, params if method == "GET" else json_body))
        if path == "/lists/account":
            return [{"id": lid, "label": "seg", "type": 1} for lid in self.lists]
        if path == "/lists/itemsnew":
            return [{"id": m, "sortId": "0", "listId": params["listId"], "type": 1, "metadata": ""}
                    for m in self.members]
        return None


class _FakeOF:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_list(self, list_id):
        self.deleted.append(str(list_id))
        return {"success": True}


async def _seed() -> None:
    async with get_session() as s:
        boss = User(id=uuid.uuid4().hex, username="delete_list_boss", password="pw")
        s.add_all([boss, Account(id=FANSLY_AID, nickname=FANSLY_AID), Account(id=OF_AID, nickname=OF_AID)])
        await s.flush()
        s.add_all([UserAccount(user_id=boss.id, account_id=FANSLY_AID),
                   UserAccount(user_id=boss.id, account_id=OF_AID)])

asyncio.run(_seed())
account_registry.save_meta(FANSLY_AID, {"id": FANSLY_AID, "nickname": FANSLY_AID, "platform": "fansly"})
account_registry.save_meta(OF_AID, {"id": OF_AID, "nickname": OF_AID, "platform": "onlyfans"})
assert http.post("/auth/login", json={"username": "delete_list_boss", "password": "pw"}).status_code == 200


@contextmanager
def _grant(value: str | None):
    saved = os.environ.pop(side_effect_gate.LIVE_CHECK_ENV, None)
    if value is not None:
        os.environ[side_effect_gate.LIVE_CHECK_ENV] = value
    try:
        yield
    finally:
        os.environ.pop(side_effect_gate.LIVE_CHECK_ENV, None)
        if saved is not None:
            os.environ[side_effect_gate.LIVE_CHECK_ENV] = saved


LIST_GRANT = f"{FANSLY_AID}:delete_list:list={LIST}"
PROOF_GRANT = f"{LIST_GRANT},{FANSLY_AID}:block_user:fan={PROOF}"


@contextmanager
def _clients(client):
    made: list[str] = []

    def make(aid):
        made.append(str(aid))
        return client

    with patch.object(ax, "_make_client", make), \
            patch.object(server, "_get_client", lambda: (made.append("route"), client)[1]), \
            patch.object(server, "_load_client", make):
        yield made


@contextmanager
def _refusals():
    real = side_effect_gate.raise_if_refused
    seen: list[str] = []

    def spy(reason, what):
        if reason is not None:
            seen.append(reason)
        real(reason, what)

    with patch.object(side_effect_gate, "raise_if_refused", spy), \
            patch.object(smart_lists_api, "raise_if_refused", spy):
        yield seen


def _route(aid: str, list_id: str = LIST):
    return http.delete(f"/api/of/v2/lists/{list_id}", headers={"X-Account-Id": aid})


def case_route_without_a_grant_answers_501_before_any_client_or_request():
    shim = _Shim()
    for grant in (None, f"{FANSLY_AID}:delete_list:list=900000000000000999", f"{OF_AID}:delete_list:list={LIST}"):
        with _grant(grant), _clients(shim) as made, _refusals() as seen:
            r = _route(FANSLY_AID)
        assert r.status_code == 501 and r.json()["detail"] == "delete list: not on this platform", (grant, r.text)
        assert seen == [REASON], (grant, seen)
        assert made == [] and shim.calls == [], (grant, made, shim.calls)


def case_route_with_a_grant_reads_members_and_refuses_a_real_fan_or_an_unclear_read():
    for label, members, grant in (
            ("a non-granted fan", [REAL], PROOF_GRANT),
            ("the Proof fan beside a real fan", [PROOF, REAL], PROOF_GRANT),
            ("the Proof fan beside an unreadable id", [PROOF, "x1"], PROOF_GRANT),
            ("the Proof fan as an int id", [int(PROOF)], PROOF_GRANT),
            ("a full 50-row page of the Proof fan", [PROOF] * 50, PROOF_GRANT),
            ("the Proof fan without its fan= grant", [PROOF], LIST_GRANT)):
        shim = _Shim(members)
        with _grant(grant), _clients(shim), _refusals() as seen:
            r = _route(FANSLY_AID)
        assert r.status_code == 501, (label, r.text)
        assert seen == [REASON], (label, seen)
        assert shim.calls == list(READ), (label, shim.calls)


def case_route_with_a_grant_on_a_list_gone_from_fansly_refuses_after_the_account_read():
    shim = _Shim([PROOF], lists=())
    with _grant(PROOF_GRANT), _clients(shim), _refusals() as seen:
        r = _route(FANSLY_AID)
    assert r.status_code == 501 and seen == [REASON], (r.text, seen)
    assert shim.calls == [READ[0]], shim.calls


def case_route_with_a_grant_deletes_an_empty_or_proof_only_complete_list_once():
    for label, members in (("empty", []), ("Proof fan only", [PROOF])):
        shim = _Shim(members)
        with _grant(PROOF_GRANT), _clients(shim), _refusals() as seen:
            r = _route(FANSLY_AID)
        assert r.status_code == 200 and r.json() == {"success": True}, (label, r.text)
        assert seen == [], (label, seen)
        assert shim.calls == [*READ, REMOVE], (label, shim.calls)


def case_onlyfans_route_still_deletes_without_a_grant_on_one_client_load():
    fake = _FakeOF()
    with _grant(None), _clients(fake) as made, _refusals() as seen:
        r = _route(OF_AID, "77")
    assert r.status_code == 200 and seen == [] and fake.deleted == ["77"], (r.text, seen, fake.deleted)
    assert made == ["route"], made


class _UnsupportedShim(_Shim):
    @platform_unsupported("no list delete here")
    def delete_list(self, list_id, **_ignored):
        raise AssertionError("refused delete_list ran")


def case_route_on_a_platform_whose_delete_is_not_a_live_check_refuses_with_its_marker_reason():
    shim = _UnsupportedShim([PROOF])
    with patch.object(fansly_backend, "Shim", _UnsupportedShim), _grant(PROOF_GRANT), \
            _clients(shim) as made, _refusals() as seen:
        r = _route(FANSLY_AID)
    assert r.status_code == 501 and r.json()["detail"] == "delete list: not on this platform", r.text
    assert seen == ["no list delete here"] and made == ["route"] and shim.calls == [], (seen, made, shim.calls)


async def _smart_list(aid: str, *, state: str | None = None, of_list_id=int(LIST)) -> int:
    async with get_session() as s:
        await s.execute(delete(SmartList).where(SmartList.account_id == aid))
        row = SmartList(account_id=aid, name=f"seg {uuid.uuid4().hex[:6]}", rules_json='{"rules": []}',
                        of_list_id=of_list_id, is_active=state is None, sync_state=state)
        s.add(row)
        await s.flush()
        return row.id


async def _state(list_id: int) -> str | None | bool:
    async with get_session() as s:
        row = (await s.execute(select(SmartList).where(SmartList.id == list_id))).scalar_one_or_none()
        return False if row is None else row.sync_state


def _delete_smart(list_id: int):
    return http.delete(f"/admin/smart-lists/{list_id}", params={"delete_of_list": "true"})


def case_smart_list_delete_without_a_grant_answers_501_before_the_tombstone():
    lid = asyncio.run(_smart_list(FANSLY_AID))
    with _grant(None), _refusals() as seen:
        r = _delete_smart(lid)
    assert r.status_code == 501 and r.json()["detail"] == "delete list: not on this platform", r.text
    assert seen == [REASON], seen
    assert asyncio.run(_state(lid)) is None


def case_smart_list_delete_with_a_grant_queues_the_tombstone():
    lid = asyncio.run(_smart_list(FANSLY_AID))
    with _grant(LIST_GRANT), _refusals() as seen, patch.object(smart_lists_api, "_wake"):
        r = _delete_smart(lid)
    assert r.status_code == 200 and r.json()["of_list_delete_queued"] is True and seen == [], (r.text, seen)
    assert asyncio.run(_state(lid)) == smart_lists_api.DELETING


def case_onlyfans_smart_list_delete_still_queues_without_a_grant():
    lid = asyncio.run(_smart_list(OF_AID, of_list_id=77))
    with _grant(None), _refusals() as seen, patch.object(smart_lists_api, "_wake"):
        r = _delete_smart(lid)
    assert r.status_code == 200 and seen == [], (r.text, seen)
    assert asyncio.run(_state(lid)) == smart_lists_api.DELETING


async def _unpaced(_aid, fn, **_kw):
    return await asyncio.to_thread(fn)


def _tombstone_run(shim, grant):
    lid = asyncio.run(_smart_list(FANSLY_AID, state=smart_lists_api.DELETING))
    with _grant(grant), _clients(shim) as made, patch.object(ax, "of_write_paced", _unpaced):
        out = asyncio.run(sls.run(FANSLY_AID, {}, run_id=0))
    return lid, out, made


def case_tombstone_without_a_grant_is_held_with_no_client_or_request():
    shim = _Shim()
    lid, out, made = _tombstone_run(shim, None)
    assert out == {"status": "skipped", "reason": REASON}, out
    assert made == [] and shim.calls == [], (made, shim.calls)
    assert asyncio.run(_state(lid)) == smart_lists_api.DELETING


def case_tombstone_with_a_grant_keeps_a_list_holding_a_real_fan_or_an_unreadable_id():
    for label, members in (("a real fan", [REAL]), ("the Proof fan and an unreadable id", [PROOF, ""])):
        shim = _Shim(members)
        lid, out, _made = _tombstone_run(shim, PROOF_GRANT)
        assert (out["status"], out["reason"], out["deleted"], out["writes"], out["held_tombstones"]) == (
            "skipped", REASON, 0, 0, [lid]), (label, out)
        assert shim.calls == list(READ), (label, shim.calls)
        assert asyncio.run(_state(lid)) == smart_lists_api.DELETING, label


def case_tombstone_with_a_grant_deletes_an_empty_or_proof_only_list_once_and_drops_the_row():
    for label, members in (("empty", []), ("Proof fan only", [PROOF])):
        shim = _Shim(members)
        lid, out, _made = _tombstone_run(shim, PROOF_GRANT)
        assert out["status"] == "ok" and out["deleted"] == 1 and "reason" not in out, (label, out)
        assert shim.calls == [*READ, *READ, REMOVE], (label, shim.calls)
        assert asyncio.run(_state(lid)) is False, label


def case_missing_fansly_list_finishes_tombstone_without_writing():
    shim = _Shim(lists=())
    lid, out, _made = _tombstone_run(shim, PROOF_GRANT)
    assert out["deleted"] == 1 and out["writes"] == 0, out
    assert shim.calls == [READ[0]], shim.calls
    assert asyncio.run(_state(lid)) is False


def case_missing_fansly_list_is_cleared_for_recreation():
    shim = _Shim(lists=())
    lid = asyncio.run(_smart_list(FANSLY_AID))
    with _clients(shim):
        out = asyncio.run(sls.run(FANSLY_AID, {}, run_id=0))
    async def stored():
        async with get_session() as s:
            row = await s.get(SmartList, lid)
            return row.of_list_id, row.sync_error
    upstream_id, error = asyncio.run(stored())
    assert out["error"] == 1 and upstream_id is None and "next sync" in error, (out, upstream_id, error)


def case_tombstone_refuses_membership_change_while_waiting_for_write():
    shim = _Shim([PROOF])
    lid = asyncio.run(_smart_list(FANSLY_AID, state=smart_lists_api.DELETING))

    async def changed(_aid, fn, **_kw):
        shim.members.append(REAL)
        return await asyncio.to_thread(fn)

    with _grant(PROOF_GRANT), _clients(shim), patch.object(ax, "of_write_paced", changed):
        out = asyncio.run(sls.run(FANSLY_AID, {}, run_id=0))
    assert out["held_tombstones"] == [lid] and out["deleted"] == 0, out
    assert (out["status"], out["reason"]) == ("skipped", REASON), out
    assert shim.calls == [*READ, *READ], shim.calls
    assert asyncio.run(_state(lid)) == smart_lists_api.DELETING
    decision = ax.run_decide.outcome("ok", None, plugin_reason=out["reason"], plugin_status=out["status"])
    assert decision == ("skipped", "done", REASON), decision


async def case_held_tombstone_with_completed_deletion_reports_partial():
    held_id = await _smart_list(FANSLY_AID, state=smart_lists_api.DELETING)
    async with get_session() as s:
        row = SmartList(account_id=FANSLY_AID, name="local tombstone",
                        sync_state=smart_lists_api.DELETING, is_active=False)
        s.add(row)
        await s.flush()
        done_id = row.id
    with _grant(PROOF_GRANT), _clients(_Shim([REAL])), patch.object(ax, "of_write_paced", _unpaced):
        out = await sls.run(FANSLY_AID, {}, run_id=0)
    assert (out["status"], out["deleted"], out["held_tombstones"]) == ("partial", 1, [held_id]), out
    assert await _state(held_id) == smart_lists_api.DELETING
    assert await _state(done_id) is False


def case_tombstone_allows_a_granted_joiner_while_waiting_for_write():
    shim = _Shim()
    lid = asyncio.run(_smart_list(FANSLY_AID, state=smart_lists_api.DELETING))

    async def joined(_aid, fn, **_kw):
        shim.members.append(PROOF)
        return await asyncio.to_thread(fn)

    with _grant(PROOF_GRANT), _clients(shim), patch.object(ax, "of_write_paced", joined):
        out = asyncio.run(sls.run(FANSLY_AID, {}, run_id=0))
    assert out["deleted"] == 1 and shim.calls == [*READ, *READ, REMOVE], (out, shim.calls)
    assert asyncio.run(_state(lid)) is False


async def _seed_sync_rule(lid, rule, *, snapshot=False):
    from datetime import datetime, timedelta
    async with get_session() as s:
        row = await s.get(SmartList, lid)
        row.rules_json = json.dumps({"rules": [rule]})
        row.of_list_name = row.name
        if await s.get(Fan, (FANSLY_AID, int(PROOF))) is None:
            s.add(Fan(account_id=FANSLY_AID, fan_id=int(PROOF), tags='["proof"]', subscription_status="active"))
        if snapshot:
            s.add(SubscriberSnapshot(account_id=FANSLY_AID, fan_id=int(PROOF),
                                     seen_at=datetime.utcnow() - timedelta(hours=12)))


class _SyncShim(_Shim):
    def __init__(self, members=(), *, total=0, subscribers=()):
        super().__init__(members)
        self.total = total
        self.subscriber_rows = [
            {"subscriberId": fid, "status": 3, "createdAt": 1, "endsAt": 9999999999999}
            for fid in subscribers
        ]

    def _request(self, method, path, **kw):
        if path == "/lists/commands":
            self.calls.append((method, path, kw["json_body"]))
            return [cmd for cmd in kw["json_body"]["listCommands"] if cmd["type"] == 2]
        if path == "/subscribers":
            self.calls.append((method, path, kw.get("params")))
            return {"subscriptions": self.subscriber_rows, "stats": {"totalActive": self.total}}
        return super()._request(method, path, **kw)


async def case_unconfirmed_fansly_add_keeps_sync_pending():
    lid = await _smart_list(FANSLY_AID)
    await _seed_sync_rule(lid, {"field": "tag", "op": "has", "value": "proof"})
    shim = _SyncShim()
    with _clients(shim), patch.object(ax, "of_write_paced", _unpaced):
        out = await ax.run_once(FANSLY_AID, "smart_list_sync", payload={})
    assert out["pending"] == 1 and out["status"] == "partial", (out, shim.calls)
    assert await _state(lid) == "pending"
    async with get_session() as s:
        assert (await s.get(AutomationRun, out["run_id"])).status == "partial"


def case_verified_empty_fansly_roster_clears_active_members():
    lid = asyncio.run(_smart_list(FANSLY_AID))
    asyncio.run(_seed_sync_rule(lid, {"field": "status", "op": "==", "value": "active"},
                                snapshot=True))
    for total, expected in ((1, "error"), (0, "ok")):
        shim = _SyncShim([PROOF], total=total)
        with _clients(shim), patch.object(ax, "of_write_paced", _unpaced):
            out = asyncio.run(sls.run(FANSLY_AID, {}, run_id=0))
        assert out[expected] == 1 and out["writes"] == (total == 0), (out, shim.calls)
        assert asyncio.run(_state(lid)) == expected
    assert asyncio.run(_never_subscribed_status()) is None
    shim = _SyncShim()
    with _clients(shim), patch.object(ax, "of_write_paced", _unpaced):
        out = asyncio.run(sls.run(FANSLY_AID, {}, run_id=0))
    assert out["ok"] == 1 and out["writes"] == 0, out
    assert not any(path == "/subscribers" for _, path, _ in shim.calls), shim.calls


async def case_nonempty_roster_with_no_local_fans_holds_removals():
    from datetime import datetime
    lid = await _smart_list(FANSLY_AID)
    await _seed_sync_rule(lid, {"field": "status", "op": "==", "value": "active"})
    async with get_session() as s:
        await s.execute(delete(Fan).where(Fan.account_id == FANSLY_AID))
    shim = _SyncShim([PROOF], total=1, subscribers=[REAL])
    now = datetime.utcnow()
    assert (await lm.refresh_roster(FANSLY_AID, shim, now=now, force=True))["listed"] == 1
    assert await lm._last_crawl(FANSLY_AID) == now
    with _clients(shim), patch.object(ax, "of_write_paced", _unpaced):
        out = await sls.run(FANSLY_AID, {}, run_id=0)
    assert out["error"] == 1 and out["writes"] == 0, (out, shim.calls)
    assert await _state(lid) == "error"


async def _never_subscribed_status():
    async with get_session() as s:
        s.add(Fan(account_id=FANSLY_AID, fan_id=int(REAL)))
    rules = {"rules": [{"field": "status", "op": "==", "value": "expired"}]}
    fans = await smart_lists_api._load_normalised_fans(FANSLY_AID, rules)
    return next(fan["status"] for fan in fans if fan["fan_id"] == int(REAL))


async def case_empty_roster_holds_removals_for_active_or_tag():
    lid = await _smart_list(FANSLY_AID)
    active = {"field": "status", "op": "==", "value": "active"}
    tag = {"field": "tag", "op": "has", "value": "vip"}
    await _seed_sync_rule(lid, active)
    async with get_session() as s:
        await s.execute(delete(Fan).where(Fan.account_id == FANSLY_AID))
        row = await s.get(SmartList, lid)
        row.rules_json = json.dumps({"match": "any", "rules": [active, tag]})
    shim = _SyncShim([PROOF])
    await lm.refresh_roster(FANSLY_AID, shim, now=datetime.utcnow(), force=True)
    with _clients(shim), patch.object(ax, "of_write_paced", _unpaced):
        out = await sls.run(FANSLY_AID, {}, run_id=0)
    assert out["error"] == 1 and out["writes"] == 0, (out, shim.calls)


async def case_auto_follow_reloads_onlyfans_list_after_client_setup():
    lid = await _smart_list(OF_AID)
    async with get_session() as s:
        s.add(Fan(account_id=OF_AID, fan_id=int(PROOF)))
    loop = asyncio.get_running_loop()

    async def delete_list():
        async with get_session() as s:
            row = await s.get(SmartList, lid)
            row.sync_state = smart_lists_api.DELETING

    def make_client(_aid):
        asyncio.run_coroutine_threadsafe(delete_list(), loop).result(5)
        return _FakeOF()

    with patch.object(ax, "_make_client", make_client):
        out = await auto_follow._run_follow(
            OF_AID, {"money_gate": False}, cap=1, dry_run=True,
            targets={"source": "smart_list", "smart_list_id": lid}, hard_skip=set())
    assert out["candidates"] == 0 and out["would_follow"] == [], out


_harness.run()
