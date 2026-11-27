#!/usr/bin/env python3
from __future__ import annotations

import _harness  # noqa: F401 — MUST be first (binds temp DB)

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import json  # noqa: E402
import sqlite3  # noqa: E402
import tempfile  # noqa: E402
import types  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402

from fastapi import HTTPException  # noqa: E402

import _send_kill_cell as kc  # noqa: E402
import accounts  # noqa: E402
import audience_include  # noqa: E402
import automation_executor as ax  # noqa: E402
import automations.scheduled_send  # noqa: E402,F401
import chatters  # noqa: E402
import media_cotag  # noqa: E402
import platforms  # noqa: E402
import send_ops  # noqa: E402
import server  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, User, UserAccount  # noqa: E402
from fansly_shim import FanslyShimClient, FanslyUnsupported  # noqa: E402
from side_effect_gate import send_refusal  # noqa: E402

_TMP = tempfile.TemporaryDirectory(prefix="send_refusal_")
accounts.SESSIONS_DIR = Path(_TMP.name)
accounts.ACCOUNTS_DIR = Path(_TMP.name) / "accounts"

OAID, FAID, UAID = kc.AID, "fansly_refusal_1", "myspace_refusal_1"
PLATFORM_OF = {FAID: "fansly", UAID: "myspace"}
OWNER = "owner_refusal"
_chatters = iter(range(1, 10_000))
FAN = 72950
TAGS, LOCKED = "platform_lacks:tagged_users", "platform_lacks:locked_text"

accounts.get_account = lambda aid: {"id": aid, "nickname": aid}
accounts.get_platform = lambda aid: PLATFORM_OF.get(aid, "onlyfans")


async def _seed() -> None:
    async with get_session() as s:
        s.add(User(id=OWNER, username=OWNER, password="x"))
        for aid in (OAID, FAID, UAID):
            s.add(Account(id=aid, nickname=aid))
            s.add(UserAccount(user_id=OWNER, account_id=aid))


asyncio.run(_seed())
send_ops.install(kc.SYNC_URL)


def _row_counts() -> dict[str, int]:
    with contextlib.closing(sqlite3.connect(str(_harness.DB_PATH))) as c:
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}


def _delta(before: dict[str, int]) -> dict[str, int]:
    after = _row_counts()
    return {t: after[t] - before.get(t, 0) for t in after if after[t] != before.get(t, 0)}


class _Stop(Exception):
    pass


class _RecordingShim(FanslyShimClient):
    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []

    def _request(self, method, path, *_a, **_k):
        self.requests.append((method, path))
        raise _Stop(path)


@contextlib.contextmanager
def _cells():
    with kc.cells(accounts=f"onlyfans:{OAID},fansly:{FAID},myspace:{UAID}"):
        yield


@contextlib.contextmanager
def _route(aid: str, client):
    req = types.SimpleNamespace(method="POST", query_params={}, state=types.SimpleNamespace(),
                                headers={"x-account-id": aid, "x-op-id": f"op-{aid}"})
    cid = f"chatter_{next(_chatters)}"
    chatter = chatters.ChatterIdentity(cid, cid, "Chatter", None, frozenset({OWNER}),
                                       frozenset({OAID, FAID, UAID}))
    tok, ctok = server._request_ctx.set(req), chatters._request_chatter.set(chatter)
    try:
        with patch.object(server, "_load_client", return_value=client):
            yield req
    finally:
        chatters._request_chatter.reset(ctok)
        server._request_ctx.reset(tok)


def _schedule_body(**kw) -> dict:
    return {"text": "later", "scheduled_date": (datetime.utcnow() + timedelta(hours=2)).isoformat() + "Z", **kw}


def _near_body(**kw) -> dict:
    return {"fan_id": FAN, "text": "soon", "run_at": (datetime.utcnow() + timedelta(minutes=5)).isoformat() + "Z", **kw}


async def _call(route: str, req, fields: dict):
    try:
        if route == "composer":
            return 200, await server.send_message(req, FAN, server.SendMessageBody(text="hi", **fields))
        if route == "schedule":
            return 200, await server.of_schedule_message(FAN, req, server._ScheduleMessageBody(**_schedule_body(**fields)))
        return 200, await server.create_scheduled_send(req, server._ScheduledSendBody(**_near_body(**fields)))
    except HTTPException as e:
        return e.status_code, e.detail


ROUTES = ("composer", "schedule", "near")


def case_send_refusal_table():
    rows = [
        ("explicit tags", {"text": "hi", "tagged_users": [5]}, False, TAGS),
        ("locked text", {"text": "hi", "locked_text": True, "price": 5, "media_files": [11]}, False, LOCKED),
        ("tags and locked text", {"tagged_users": [5], "locked_text": True}, False, TAGS),
        ("needs a co-tag", {"text": "hi", "media_files": [11]}, True, TAGS),
        ("legacy text-only job", {"fan_id": FAN, "text": "hi"}, False, None),
        ("empty tags and unlocked text", {"tagged_users": [], "locked_text": False}, False, None),
    ]
    for name, payload, would_cotag, want in rows:
        assert send_refusal(platforms.FANSLY, payload, would_cotag=would_cotag) == want, name
        assert send_refusal(platforms.ONLYFANS, payload, would_cotag=would_cotag) is None, name
        assert send_refusal(platforms.get("myspace"), payload, would_cotag=would_cotag) == "platform_unknown:myspace", name


async def case_fansly_routes_refuse_before_any_row_or_request():
    for route in ROUTES:
        for fields, want in (({"tagged_users": [5]}, TAGS), ({"locked_text": True}, LOCKED)):
            shim = _RecordingShim()
            with _cells(), _route(FAID, shim) as req:
                before = _row_counts()
                got = await _call(route, req, fields)
                delta = _delta(before)
            assert got == (501, want), (route, fields, got)
            assert delta == {} and shim.requests == [], (route, fields, delta, shim.requests)


async def case_unknown_account_routes_refuse_before_any_row():
    for route in ROUTES:
        with _cells(), _route(UAID, _RecordingShim()) as req:
            before = _row_counts()
            got = await _call(route, req, {})
            delta = _delta(before)
        assert got == (501, "platform_unknown:myspace") and delta == {}, (route, got, delta)


async def case_onlyfans_routes_still_send_tags_and_locked_text():
    fields = {"tagged_users": [5], "locked_text": True, "price": 3, "media_files": [11]}
    for route, wire, rows in (("composer", "/chats/", {"send_ops": 1, "messages": 1, "employees": 1}),
                              ("schedule", "/messages/queue", {"send_ops": 1, "employees": None}),
                              ("near", None, {"scheduled_jobs": 1, "employees": 1})):
        http = kc.FakeHttp()
        with _cells(), _route(OAID, kc.client(http)) as req:
            before = _row_counts()
            status, _ = await _call(route, req, fields)
            delta = _delta(before)
        assert status == 200, (route, status)
        assert {t: delta.get(t) for t in rows} == rows, (route, delta)
        if wire is None:
            assert http.calls == [], http.calls
            continue
        [(method, path, body)] = http.calls
        assert method == "POST" and wire in path, http.calls
        assert body["lockedText"] is True and body["userTags"] == [5], body
    with contextlib.closing(sqlite3.connect(str(_harness.DB_PATH))) as c:
        job = json.loads(c.execute("SELECT payload_json FROM scheduled_jobs WHERE account_id=? ORDER BY id DESC",
                                   (OAID,)).fetchone()[0])
    assert job["tagged_users"] == [5] and job["locked_text"] is True, job


def case_shim_send_with_tags_makes_no_group_request():
    for kwargs, want in (({"tagged_users": [5]}, TAGS), ({"locked_text": "tease"}, LOCKED)):
        shim = _RecordingShim()
        try:
            shim.send_message(FAN, "hi", **kwargs)
        except FanslyUnsupported as e:
            assert want in str(e), (kwargs, e)
        else:
            raise AssertionError(f"{kwargs} sent")
        assert shim.requests == [], (kwargs, shim.requests)
    shim = _RecordingShim()
    try:
        shim.send_message(FAN, "hi")
    except _Stop:
        pass
    assert shim.requests and "group" in shim.requests[0][1], shim.requests


class _Sender:
    def __init__(self) -> None:
        self.sends: list[dict] = []

    def send_message(self, chat_id, text, **kw):
        self.sends.append({"fan": int(chat_id), "text": text, **kw})
        return {"id": 8_810_000 + len(self.sends), "text": text,
                "createdAt": datetime.utcnow().isoformat() + "+00:00"}


async def _fire(aid: str, payload: dict, *, cotag_on: bool, needs: bool):
    sender, builds, fences, lookups = _Sender(), [], [], []

    def make(a):
        builds.append(a)
        return sender

    async def fence(account_id, fan_id, *, kind, payload=None):
        fences.append(fan_id)
        return True, "allowed"

    async def unpaced(account_id, fn, **kw):
        return await asyncio.to_thread(fn)

    await ax.enqueue_job(aid, "scheduled_send", payload={"fan_id": FAN, **payload},
                         run_at=datetime.utcnow() - timedelta(seconds=1))
    with _cells(), patch.object(ax, "_make_client", make), patch.object(ax, "of_write_paced", unpaced), \
            patch.object(audience_include, "check_at_fire", fence), \
            patch.object(media_cotag, "enabled", lambda: cotag_on), \
            patch.object(media_cotag, "needs_cotag", lambda a, m: lookups.append(a) or needs), \
            patch.object(ax, "start_fan_cooldown", lambda *a, **k: asyncio.sleep(0)):
        before = _row_counts()
        result = await ax.run_once(aid, "scheduled_send")
        delta = _delta(before)
    with contextlib.closing(sqlite3.connect(str(_harness.DB_PATH))) as c:
        status, stats = c.execute("SELECT status, stats_json FROM automation_runs WHERE id=?",
                                  (result["run_id"],)).fetchone()
        job = c.execute("SELECT status FROM scheduled_jobs WHERE id=?", (result["job_id"],)).fetchone()[0]
    return (status, json.loads(stats).get("reason"), job), delta, builds, fences, sender.sends, lookups


async def case_scheduled_send_refuses_at_fire_on_fansly():
    media = {"text": "pic", "media_files": [11]}
    rows = [
        ("explicit tags", {"text": "hi", "tagged_users": [5], "send_purpose": "manual"}, True, True, TAGS),
        ("locked text", {"text": "hi", "locked_text": True, "send_purpose": "manual"}, True, True, LOCKED),
        ("automated media needing a co-tag", media, True, True, TAGS),
        ("legacy text-only job", {"text": "hi"}, True, True, None),
        ("automated media, co-tag switch off", media, False, True, None),
        ("automated media needing no co-tag", media, True, False, None),
        ("manual media", {**media, "send_purpose": "manual"}, True, True, None),
    ]
    for name, payload, cotag_on, needs, want in rows:
        outcome, delta, builds, fences, sends, _lookups = await _fire(FAID, payload, cotag_on=cotag_on, needs=needs)
        if want:
            assert outcome == ("skipped", want, "done"), (name, outcome)
            assert delta == {"automation_runs": 1}, (name, delta)
            assert builds == fences == sends == [], (name, builds, fences, sends)
        else:
            assert outcome[0] == "ok" and outcome[2] == "done", (name, outcome)
            assert delta.get("send_ops") == 1 and builds == [FAID] and len(sends) == 1, (name, delta, builds, sends)


async def case_scheduled_send_on_onlyfans_still_sends_tags_and_locked_text():
    payload = {"text": "hi", "tagged_users": [5], "locked_text": True, "price": 3, "media_files": [11]}
    outcome, delta, builds, _fences, sends, lookups = await _fire(OAID, payload, cotag_on=True, needs=True)
    assert outcome[0] == "ok" and delta.get("send_ops") == 1 and builds == [OAID], (outcome, delta, builds)
    assert lookups == [], lookups
    [sent] = sends
    assert sent["tagged_users"] == [5] and sent["locked_text"] is True and sent["auto_tag"] is True, sent


if __name__ == "__main__":
    _harness.run()
