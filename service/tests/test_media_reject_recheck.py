#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402
from datetime import datetime  # noqa: E402

import vault_cache  # noqa: E402
import vault_scripts  # noqa: E402
from automations import _send_failure  # noqa: E402
from automations._send_failure import (  # noqa: E402
    SendOutcome, recheck_rejected_media, send_dropping_bad_media,
)
from db.engine import get_session  # noqa: E402
from db.models import Account, VaultItem  # noqa: E402

A = "77100001"


class _Resp:
    def __init__(self, status: int, body=None):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class _OFError(Exception):
    def __init__(self, status: int, body=None):
        super().__init__(f"{status} {json.dumps(body) if body else ''}")
        self.response = _Resp(status, body)


def _files(sig: str) -> dict:
    return {k: {"url": f"https://cdn3.onlyfans.com/files/x/{k}.jpg?Policy={sig}"}
            for k in ("thumb", "preview", "full")}


class FakeOF:

    account_id = A

    def __init__(self, alive=(), transient=(), payload=None):
        self.alive, self.transient = set(alive), set(transient)
        self.payload = payload
        self.byid: list[int] = []
        self.sent: list[list] = []

    def vault_media_by_id(self, media_id):
        self.byid.append(int(media_id))
        if int(media_id) in self.transient:
            raise _OFError(502)
        if int(media_id) in self.alive:
            return self.payload or {"id": int(media_id), "type": "photo", "files": _files("FRESH")}
        raise _OFError(404)

    def send_message(self, fan_id, text, media_files=None, **kw):
        self.sent.append(list(media_files or []))
        if media_files:
            raise _OFError(400, {"errors": {"mediaFiles": ["Something wrong with attached media"]}})
        return {"id": 5551, "text": text}


async def _seed(*ids: int) -> None:
    async with get_session() as s:
        if await s.get(Account, A) is None:
            s.add(Account(id=A, nickname="acct771"))
        for mid in ids:
            old = await s.get(VaultItem, (A, mid))
            if old is not None:
                await s.delete(old)
                await s.flush()
            raw = {"id": mid, "type": "photo", "files": _files("OLD")}
            s.add(VaultItem(account_id=A, media_id=mid, kind="photo", created_at=datetime.utcnow(),
                            thumb_url=raw["files"]["thumb"]["url"], raw_json=json.dumps(raw)))


async def _item(mid: int) -> VaultItem:
    async with get_session() as s:
        return await s.get(VaultItem, (A, mid))


async def case_gone_leaves_mirror_and_picker():
    await _seed(7101, 7102)
    vault_cache._invalidated_at.pop(A, None)
    gone = await recheck_rejected_media(A, FakeOF(alive={7102}), [7101])
    assert gone == [7101], gone
    assert (await _item(7101)).removed_at is not None, "a 404 must stamp removed_at"
    assert A in vault_cache._invalidated_at, "vault cache not invalidated"
    pool = {r["media_id"] for r in await vault_scripts._load_rows(A)}
    assert 7101 not in pool and 7102 in pool, pool


async def case_alive_stays_and_is_refreshed():
    await _seed(7111)
    vault_cache._invalidated_at.pop(A, None)
    of = FakeOF(alive={7111})
    assert await recheck_rejected_media(A, of, [7111]) == []
    row = await _item(7111)
    assert row.removed_at is None, "a live media must stay live"
    assert "Policy=FRESH" in row.thumb_url, row.thumb_url
    assert of.byid == [7111] and A not in vault_cache._invalidated_at


async def case_transient_stays_live():
    await _seed(7121)
    assert await recheck_rejected_media(A, FakeOF(transient={7121}), [7121]) == []
    assert (await _item(7121)).removed_at is None, "a 502 is not a deletion"


async def case_dedupe_and_cap():
    ids = list(range(7200, 7212))
    await _seed(*ids)
    of = FakeOF()
    gone = await recheck_rejected_media(A, of, [7200, 7200, "7201", *ids])
    assert of.byid == ids[:10], of.byid
    assert gone == ids[:10], gone
    assert (await _item(7211)).removed_at is None, "past the cap: unchecked, untouched"


async def case_never_raises():
    await _seed(7131, 7132, 7133)
    of = FakeOF()
    assert await recheck_rejected_media(A, of, ["not-an-id", None, 7133]) == [7133]
    assert of.byid == [7133], of.byid
    of = FakeOF(alive={7131}, payload={"id": 7131, "listStates": 5})
    assert await recheck_rejected_media(A, of, [7131, 7132]) == [7132]
    assert (await _item(7131)).removed_at is None
    of = FakeOF()
    assert await recheck_rejected_media(None, of, [7131]) == [] and of.byid == []


async def case_dead_or_unknown_ids_cost_no_get():
    await _seed(7301, 7302)
    async with get_session() as s:
        (await s.get(VaultItem, (A, 7301))).removed_at = datetime.utcnow()
    of = FakeOF()
    assert await recheck_rejected_media(A, of, [7301, 7399, 7302]) == [7302]
    assert of.byid == [7302], of.byid
    of = FakeOF()
    assert await recheck_rejected_media(A, of, [7301, 7302, 7399]) == [] and of.byid == []


async def case_recent_ids_are_not_reread():
    await _seed(7311, 7312)
    of = FakeOF(alive={7311}, transient={7312})
    assert await recheck_rejected_media(A, of, [7311, 7312]) == []
    assert of.byid == [7311, 7312], of.byid
    assert await recheck_rejected_media(A, of, [7311, 7312]) == []
    assert of.byid == [7311, 7312], of.byid
    for k in [(A, 7311), (A, 7312)]:
        _send_failure._RECHECKED[k] -= _send_failure._RECHECK_TTL_S + 1
    assert await recheck_rejected_media(A, of, [7311, 7312]) == []
    assert of.byid == [7311, 7312, 7311, 7312], of.byid


async def _drain() -> None:
    await asyncio.gather(*list(_send_failure._RECHECK_TASKS), return_exceptions=True)


async def case_send_dropping_bad_media_rechecks():
    await _seed(7141, 7142)
    of = FakeOF()
    out = await send_dropping_bad_media(of, 42, "hi", [7141], send_purpose="gated")
    await _drain()
    assert out == SendOutcome({"id": 5551, "text": "hi"}, False), out
    assert of.sent == [[7141], []] and of.byid == [7141], (of.sent, of.byid)
    assert (await _item(7141)).removed_at is not None, "the rejected id was not re-checked"
    of = FakeOF(alive={7142}, payload={"id": 7142, "listStates": 5})
    out = await send_dropping_bad_media(of, 42, "hi", ["junk", 7142], send_purpose="gated")
    await _drain()
    assert out == SendOutcome({"id": 5551, "text": "hi"}, False), out
    assert of.byid == [7142], of.byid


class _GatedOF(FakeOF):

    def __init__(self):
        super().__init__()
        self.gate = threading.Event()

    def vault_media_by_id(self, media_id):
        self.gate.wait(5)
        return super().vault_media_by_id(media_id)


async def case_recheck_runs_off_the_send_path():
    await _seed(7151)
    of = _GatedOF()
    out = await send_dropping_bad_media(of, 42, "hi", [7151], send_purpose="gated")
    assert out == SendOutcome({"id": 5551, "text": "hi"}, False), out
    assert not of.gate.is_set() and of.byid == [], "the send waited on the re-check"
    pending = [t for t in _send_failure._RECHECK_TASKS if not t.done()]
    assert len(pending) == 1, pending
    of.gate.set()
    assert await pending[0] == [7151]
    assert (await _item(7151)).removed_at is not None
    assert not _send_failure._RECHECK_TASKS, "a finished task stays referenced"

    real = _send_failure.recheck_rejected_media

    async def boom(*a, **kw):
        raise RuntimeError("recheck exploded")

    _send_failure.recheck_rejected_media = boom
    try:
        out = await send_dropping_bad_media(FakeOF(), 42, "hi", [7152], send_purpose="gated")
        assert out == SendOutcome({"id": 5551, "text": "hi"}, False), out
        task = _send_failure.schedule_recheck_rejected_media(A, FakeOF(), [7152])
        try:
            await task
            raise AssertionError("expected the task to carry the error")
        except RuntimeError:
            pass
        await _drain()
    finally:
        _send_failure.recheck_rejected_media = real
    assert not _send_failure._RECHECK_TASKS


_harness.run()
