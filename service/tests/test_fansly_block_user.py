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

import accounts as account_registry  # noqa: E402

_TMP = tempfile.TemporaryDirectory(prefix="fansly_block_user_")
account_registry.SESSIONS_DIR = Path(_TMP.name)
account_registry.ACCOUNTS_DIR = Path(_TMP.name) / "accounts"
account_registry.ACTIVE_FILE = Path(_TMP.name) / "active.json"
account_registry.MIGRATED_MARKER = Path(_TMP.name) / ".migrated"

import server  # noqa: E402
import side_effect_gate  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, User, UserAccount  # noqa: E402
from fansly_shim import FanslyShimClient  # noqa: E402

http = _harness.make_client()

FANSLY_AID = "8803701"
OF_AID = "8803702"
PROOF = "900000000000000002"
OTHER = "900000000000000777"
REASON = "platform_lacks:block_user"
EMPTY = {"ignoring": [], "accounts": []}
READ = ("GET", "/ignore", {"noAggregation": "true"}, None)
BLOCK = ("POST", "/account/ignore", None, {"ignoredId": PROOF, "ignoreFlags": 2})


class _Shim(FanslyShimClient):
    def __init__(self, ignore=None) -> None:
        self.ignore = EMPTY if ignore is None else ignore
        self.calls: list[tuple] = []

    def _request(self, method, path, *, params=None, json_body=None, **_kw):
        self.calls.append((method, path, params, json_body))
        if path == "/ignore":
            return self.ignore
        return {"accountId": FANSLY_AID, **json_body}


class _FakeOF:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def block_user(self, user_id):
        self.calls.append(("block_user", str(user_id)))
        return {"success": True}

    def unblock_user(self, user_id):
        self.calls.append(("unblock_user", str(user_id)))
        return {"success": True}


async def _seed() -> None:
    async with get_session() as s:
        boss = User(id=uuid.uuid4().hex, username="block_user_boss", password="pw")
        s.add_all([boss, Account(id=FANSLY_AID, nickname=FANSLY_AID), Account(id=OF_AID, nickname=OF_AID)])
        await s.flush()
        s.add_all([UserAccount(user_id=boss.id, account_id=FANSLY_AID),
                   UserAccount(user_id=boss.id, account_id=OF_AID)])

asyncio.run(_seed())
account_registry.save_meta(FANSLY_AID, {"id": FANSLY_AID, "nickname": FANSLY_AID, "platform": "fansly"})
account_registry.save_meta(OF_AID, {"id": OF_AID, "nickname": OF_AID, "platform": "onlyfans"})
assert http.post("/auth/login", json={"username": "block_user_boss", "password": "pw"}).status_code == 200


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


GRANT = f"{FANSLY_AID}:block_user:fan={PROOF}"


@contextmanager
def _client(client):
    made: list[str] = []
    with patch.object(server, "_get_client", lambda: (made.append("route"), client)[1]):
        yield made


@contextmanager
def _refusals():
    real = side_effect_gate.raise_if_refused
    seen: list[str] = []

    def spy(reason, what):
        if reason is not None:
            seen.append(reason)
        real(reason, what)

    with patch.object(side_effect_gate, "raise_if_refused", spy):
        yield seen


def _block(aid: str, fan: str = PROOF):
    return http.post(f"/api/of/v2/users/{fan}/block", headers={"X-Account-Id": aid})


def _unblock(aid: str, fan: str = PROOF):
    return http.delete(f"/api/of/v2/users/{fan}/block", headers={"X-Account-Id": aid})


def case_block_without_a_grant_for_that_fan_answers_501_before_any_client_or_request():
    for grant in (None, f"{FANSLY_AID}:block_user:fan={OTHER}", f"{OF_AID}:block_user:fan={PROOF}",
                  f"{FANSLY_AID}:priority_mass:fan={PROOF}", f"{FANSLY_AID}:block_user"):
        shim = _Shim()
        with _grant(grant), _client(shim) as made, _refusals() as seen:
            r = _block(FANSLY_AID)
        assert r.status_code == 501 and r.json()["detail"] == "block user: not on this platform", (grant, r.text)
        assert seen == [REASON], (grant, seen)
        assert made == [] and shim.calls == [], (grant, made, shim.calls)


def case_block_with_the_grant_reads_empty_ignore_then_posts_flags_2_once():
    shim = _Shim()
    with _grant(GRANT), _client(shim), _refusals() as seen:
        r = _block(FANSLY_AID)
    assert r.status_code == 200 and r.json() == {"success": True}, r.text
    assert seen == [], seen
    assert shim.calls == [READ, BLOCK], shim.calls


def case_block_with_the_grant_on_an_unknown_block_state_raises_with_no_post():
    for label, ignore in (("populated", {"ignoring": [{"ignoredId": OTHER, "ignoreFlags": 2}], "accounts": []}),
                          ("an extra key", {**EMPTY, "x": 1}), ("a list", [])):
        shim = _Shim(ignore)
        with _grant(GRANT), _client(shim):
            r = _block(FANSLY_AID)
        assert r.status_code == 501, (label, r.status_code, r.text)
        assert shim.calls == [READ], (label, shim.calls)


def case_unblock_on_fansly_stays_blocked_with_no_request_even_under_a_grant():
    for grant in (None, GRANT, f"{FANSLY_AID}:unblock_user:fan={PROOF}"):
        shim = _Shim()
        with _grant(grant), _client(shim), _refusals() as seen:
            r = _unblock(FANSLY_AID)
        assert r.status_code == 501 and r.json()["detail"] == "unblock user: not on this platform", (grant, r.text)
        assert seen == [side_effect_gate.refusal(FanslyShimClient, "unblock_user")] and seen[0], (grant, seen)
        assert shim.calls == [], (grant, shim.calls)


def case_onlyfans_block_and_unblock_still_act_without_a_grant():
    fake = _FakeOF()
    with _grant(None), _client(fake), _refusals() as seen:
        assert _block(OF_AID, "77").status_code == 200
        assert _unblock(OF_AID, "77").status_code == 200
    assert seen == [] and fake.calls == [("block_user", "77"), ("unblock_user", "77")], (seen, fake.calls)


_harness.run()
