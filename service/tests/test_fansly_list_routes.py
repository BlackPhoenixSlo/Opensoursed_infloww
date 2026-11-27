#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import uuid  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402

import accounts as account_registry  # noqa: E402

_TMP = tempfile.TemporaryDirectory(prefix="fansly_list_routes_")
account_registry.SESSIONS_DIR = Path(_TMP.name)
account_registry.ACCOUNTS_DIR = Path(_TMP.name) / "accounts"
account_registry.ACTIVE_FILE = Path(_TMP.name) / "active.json"
account_registry.MIGRATED_MARKER = Path(_TMP.name) / ".migrated"

import server  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, User, UserAccount  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fansly"))
from stateful_fake import StatefulFansly  # noqa: E402

http = _harness.make_client()

_AID = "8803901"
server._resolve_account_id = lambda _req=None: _AID  # type: ignore[assignment]


async def _owner() -> None:
    async with get_session() as s:
        boss = User(id=uuid.uuid4().hex, username="list_routes_boss", password="pw")
        s.add_all([boss, Account(id=_AID, nickname=_AID)])
        await s.flush()
        s.add(UserAccount(user_id=boss.id, account_id=_AID))

asyncio.run(_owner())
assert http.post("/auth/login", json={"username": "list_routes_boss", "password": "pw"}).status_code == 200


def _on(platform: str) -> None:
    account_registry.save_meta(_AID, {"id": _AID, "nickname": _AID, "platform": platform})


def _call(method: str, path: str, client, **kw):
    with patch.object(server, "_get_client", return_value=client), \
            patch.object(server, "_invalidate_chat_folders"):
        return http.request(method, path, headers={"X-Account-Id": _AID}, **kw)


def _fansly_list(*members: str) -> tuple[StatefulFansly, object, str]:
    fake = StatefulFansly()
    shim = fake.client()
    lid = shim.create_list("Proof")["id"]
    if members:
        shim.add_users_to_lists({lid: list(members)})
    fake.calls.clear()
    return fake, shim, str(lid)


def _sent(fake: StatefulFansly) -> list[tuple[str, str]]:
    return [(m, p) for m, p, *_ in fake.calls]


def case_fansly_members_route_off_the_one_observed_page_answers_501_with_no_request():
    _on("fansly")
    fake, shim, lid = _fansly_list("900000000000000002")
    for label, params in (("default limit 20", {}), ("limit 10", {"limit": 10}),
                          ("offset", {"limit": 50, "offset": 50}), ("query", {"limit": 50, "query": "a"})):
        r = _call("GET", f"/api/of/v2/lists/{lid}/users", shim, params=params)
        assert r.status_code == 501 and r.json()["error"] == "fansly", (label, r.status_code, r.text)
        assert "only one 50-row first page" in r.json()["detail"], (label, r.text)
    r = _call("GET", "/api/of/v2/lists/fans/users", shim, params={"limit": 50})
    assert r.status_code == 501, r.text
    assert fake.calls == [], fake.calls


def case_fansly_members_route_reads_one_page_and_an_unknown_list_answers_501():
    _on("fansly")
    fake, shim, lid = _fansly_list("900000000000000002")
    r = _call("GET", f"/api/of/v2/lists/{lid}/users", shim, params={"limit": 50})
    assert r.status_code == 200 and r.json() == {"list": [{"id": "900000000000000002"}], "hasMore": False}, r.text
    assert _sent(fake) == [("GET", "/lists/account"), ("GET", "/lists/itemsnew")], fake.calls
    fake.calls.clear()
    r = _call("GET", "/api/of/v2/lists/900000000000000999/users", shim, params={"limit": 50})
    assert r.status_code == 501 and "is not on Fansly" in r.json()["detail"], r.text
    assert _sent(fake) == [("GET", "/lists/account")], fake.calls


def case_fansly_rename_route_renames_reads_back_and_undoes():
    _on("fansly")
    fake, shim, lid = _fansly_list("900000000000000002")
    for label in ("Renamed", "Proof"):
        r = _call("PATCH", f"/api/of/v2/lists/{lid}", shim, json={"name": label})
        assert r.status_code == 200 and r.json() == {"id": lid, "name": label}, (label, r.text)
        assert {"id": lid, "name": label} in shim.get_lists()["list"], (label, shim.get_lists())
    assert fake.members[lid] == ["900000000000000002"], fake.members
    assert [p for m, p, *_ in fake.calls if m == "POST"] == ["/lists/edit", "/lists/edit"], fake.calls
    fake.calls.clear()
    r = _call("PATCH", "/api/of/v2/lists/fans", shim, json={"name": "x"})
    assert r.status_code == 501 and r.json()["error"] == "fansly" and fake.calls == [], (r.text, fake.calls)


def case_fansly_rename_route_answers_502_on_an_echo_for_another_label():
    _on("fansly")
    fake, shim, lid = _fansly_list()
    real = shim._request

    def other_label(method, path, **kw):
        out = real(method, path, **kw)
        return {**out, "label": "Something else"} if path == "/lists/edit" else out

    with patch.object(shim, "_request", other_label):
        r = _call("PATCH", f"/api/of/v2/lists/{lid}", shim, json={"name": "Renamed"})
    assert r.status_code == 502 and r.json()["error"] == "fansly", (r.status_code, r.text)


class _OF:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def list_users_in(self, list_id, **kw):
        self.calls.append(("list_users_in", list_id, kw))
        return {"list": [], "hasMore": False}

    def rename_list(self, list_id, name):
        self.calls.append(("rename_list", list_id, name))
        return {"success": True}


def case_of_members_and_rename_routes_still_reach_the_client():
    _on("onlyfans")
    of = _OF()
    assert _call("GET", "/api/of/v2/lists/7/users", of).status_code == 200
    assert _call("PATCH", "/api/of/v2/lists/7", of, json={"name": "x"}).status_code == 200
    assert of.calls == [("list_users_in", "7", {"limit": 20, "offset": 0, "query": None}),
                        ("rename_list", "7", "x")], of.calls


_harness.run()
