#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
import uuid  # noqa: E402
from contextlib import contextmanager  # noqa: E402
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
from automations import smart_list_sync as sls  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, SmartList, User, UserAccount  # noqa: E402
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
            "ok", f"partial:{REASON}", 0, 0, [lid]), (label, out)
        assert shim.calls == list(READ), (label, shim.calls)
        assert asyncio.run(_state(lid)) == smart_lists_api.DELETING, label


def case_tombstone_with_a_grant_deletes_an_empty_or_proof_only_list_once_and_drops_the_row():
    for label, members in (("empty", []), ("Proof fan only", [PROOF])):
        shim = _Shim(members)
        lid, out, _made = _tombstone_run(shim, PROOF_GRANT)
        assert out["status"] == "ok" and out["deleted"] == 1 and "reason" not in out, (label, out)
        assert shim.calls == [*READ, REMOVE], (label, shim.calls)
        assert asyncio.run(_state(lid)) is False, label


_harness.run()
