#!/usr/bin/env python3
"""
Pushing the AI folders out as REAL OF vault lists — `_mirror_ai_folders_to_of`.
Plain-assert, no pytest (repo convention).

Why this suite exists: this is the only part of the vault-AI pipeline that
WRITES to her OnlyFans account, and it used to interleave those writes with a
purely cosmetic read-back. Per folder it created the list, added the media, then
re-paged that list out of OF and rewrote every VaultItem row for the account.
On a 12-folder plan the operator's request ran for minutes; the proxy in front
of the relay gave up first and the browser showed a bare "Internal Server
Error". The relay had logged nothing, because a client disconnect cancels the
handler with `CancelledError` — a BaseException, invisible to the
`except Exception` that records server errors. Folders the loop hadn't reached
were simply never made (observed 2026-07-28: two `AI-` folders left with a NULL
of_list_id), which is also why it "sometimes worked": a small plan finished
inside the timeout, a big one didn't.

So the ordering is the invariant, not an optimisation: every write lands before
any read-back, and the read-back is detached.

Cases:
  case_every_folder_is_made_before_any_readback — all creates+adds happen with
                                    ZERO membership pages issued, so a request
                                    that dies during the read-back has already
                                    made every folder real on OF.
  case_a_failed_folder_does_not_block_the_rest — one folder's OF create blows
                                    up; the others are still created and it is
                                    reported per folder, not raised.
  case_existing_list_is_reused     — a folder already carrying an of_list_id is
                                    added to, never re-created (that is how a
                                    re-run avoids a second list with the
                                    same name).
  case_readback_applies_every_list_in_one_pass — gains AND drops, across two
                                    lists, from a single pass over the vault.
  case_readback_survives_a_dead_list — one list 500s; the others still land.
                                    It runs detached, so an escaping exception
                                    would only ever surface as a GC warning.

Run: cd service/tests && \
  PYTHONPATH=$(cd .. && pwd) ../../venv/bin/python test_vault_ai_mirror.py
Exit 0 = all cases passed. Temp DB bound by _harness (never prod).
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime  # noqa: E402

import automation_executor as ax  # noqa: E402 — the OF-client seam
import vault_ai_api as api  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, VaultFolder, VaultItem  # noqa: E402

_AID = "acc_mirror"


# ── Fake OF ─────────────────────────────────────────────────────────

class _FakeOF:
    """Records every call in ORDER — the ordering invariant is the whole point."""

    def __init__(self):
        self.timeout_s = 5.0
        self.calls: list[tuple] = []
        self.next_list_id = 900
        # Names whose create must blow up.
        self.create_fails: set[str] = set()
        # list_id -> media ids OF reports in it; a list_id in `page_fails` raises.
        self.members: dict[int, list[int]] = {}
        self.page_fails: set[int] = set()

    def create_vault_list(self, name: str) -> dict:
        self.calls.append(("create", name))
        if name in self.create_fails:
            raise RuntimeError(f"OF refused the list {name!r}")
        self.next_list_id += 1
        return {"id": self.next_list_id}

    def add_media_to_vault_list(self, list_id: int, media_ids: list) -> dict:
        self.calls.append(("add", int(list_id), list(media_ids)))
        return {"ok": True}

    def vault_media(self, limit=100, offset=0, type="all", list_id=None, **_kw):  # noqa: A002
        self.calls.append(("page", int(list_id), int(offset)))
        if int(list_id) in self.page_fails:
            raise RuntimeError("OF 500 on this list")
        rows = self.members.get(int(list_id), [])[offset:offset + limit]
        return {"list": [{"id": m} for m in rows]}

    def reset(self) -> None:
        self.calls.clear()
        self.create_fails.clear()
        self.members.clear()
        self.page_fails.clear()

    def kinds(self, kind: str) -> list:
        return [c for c in self.calls if c[0] == kind]


_OF = _FakeOF()
ax._make_client = lambda _aid, *a, **k: _OF  # type: ignore[assignment]


# ── Seeders ─────────────────────────────────────────────────────────

async def _reset_db() -> None:
    async with get_session() as s:
        if await s.get(Account, _AID) is None:
            s.add(Account(id=_AID, nickname=_AID, color="#aaaaaa"))
    async with get_session() as s:
        for tbl in (VaultFolder, VaultItem):
            for row in (await s.execute(_select_all(tbl))).scalars().all():
                await s.delete(row)


def _select_all(tbl):
    from sqlalchemy import select
    return select(tbl).where(tbl.account_id == _AID)


async def _seed_folder(name: str, of_list_id: int | None = None) -> int:
    async with get_session() as s:
        f = VaultFolder(account_id=_AID, name=name, of_list_id=of_list_id,
                        created_by="vault_ai_script")
        s.add(f)
        await s.flush()
        return f.id


async def _seed_item(media_id: int, of_folder_ids: list[int] | None = None) -> None:
    async with get_session() as s:
        s.add(VaultItem(
            account_id=_AID, media_id=media_id, kind="photo",
            created_at=datetime.utcnow(), raw_json="{}",
            of_folder_ids=json.dumps(of_folder_ids or []),
        ))


async def _folder_ids(media_id: int) -> list[int]:
    async with get_session() as s:
        item = await s.get(VaultItem, (_AID, media_id))
        return sorted(json.loads(item.of_folder_ids or "[]"))


async def _of_list_id(folder_id: int) -> int | None:
    async with get_session() as s:
        f = await s.get(VaultFolder, folder_id)
        return f.of_list_id


def _plan(specs: list[tuple[str, list[int]]]) -> dict:
    return {"folders": [
        {"name": n, "items": [{"media_id": m} for m in ids]} for n, ids in specs
    ]}


def _created(pairs: list[tuple[int, str]]) -> list[dict]:
    return [{"folder_id": fid, "name": n, "items": 0, "reused": False}
            for fid, n in pairs]


# ── Cases ───────────────────────────────────────────────────────────

async def case_every_folder_is_made_before_any_readback():
    await _reset_db()
    _OF.reset()
    names = [f"AI-lane {i}" for i in range(6)]
    fids = [await _seed_folder(n) for n in names]
    plan = _plan([(n, [100 + i]) for i, n in enumerate(names)])

    out = await api._mirror_ai_folders_to_of(_AID, _created(list(zip(fids, names))), plan)

    assert len(_OF.kinds("create")) == 6, f"expected 6 creates, got {_OF.kinds('create')}"
    assert len(_OF.kinds("add")) == 6, f"expected 6 adds, got {_OF.kinds('add')}"
    # THE invariant: not one membership page may be issued while folders are
    # still unmade. This is what a timeout used to cut through.
    assert _OF.kinds("page") == [], (
        f"read-back ran inside the request — {len(_OF.kinds('page'))} pages issued "
        f"before every folder was made"
    )
    assert all(r.get("of_list_id") for r in out), f"a folder went unmirrored: {out}"
    for fid in fids:
        assert await _of_list_id(fid) is not None, f"folder {fid} has no of_list_id"


async def case_a_failed_folder_does_not_block_the_rest():
    await _reset_db()
    _OF.reset()
    names = ["AI-ok one", "AI-doomed", "AI-ok two"]
    fids = [await _seed_folder(n) for n in names]
    _OF.create_fails.add("AI-doomed")
    plan = _plan([(n, [200 + i]) for i, n in enumerate(names)])

    out = await api._mirror_ai_folders_to_of(_AID, _created(list(zip(fids, names))), plan)

    by_name = {r["name"]: r for r in out}
    assert by_name["AI-doomed"].get("of_error"), "the failure must be reported, not swallowed"
    assert by_name["AI-doomed"].get("of_list_id") is None
    # The folder AFTER the failure is the one that regressions kill.
    assert by_name["AI-ok two"].get("of_list_id"), (
        "a folder that failed on OF stopped the ones behind it"
    )
    assert await _of_list_id(fids[2]) is not None


async def case_existing_list_is_reused():
    await _reset_db()
    _OF.reset()
    fid = await _seed_folder("AI-already there", of_list_id=555)
    plan = _plan([("AI-already there", [301, 302])])

    out = await api._mirror_ai_folders_to_of(_AID, _created([(fid, "AI-already there")]), plan)

    assert _OF.kinds("create") == [], "a folder with an of_list_id must never be re-created"
    assert _OF.kinds("add") == [("add", 555, [301, 302])], _OF.kinds("add")
    assert out[0]["of_list_id"] == 555


async def case_readback_applies_every_list_in_one_pass():
    await _reset_db()
    _OF.reset()
    # 401 is already in list 700 but OF no longer has it there  -> dropped.
    # 402 is in neither          but OF reports it in 701       -> gained.
    # 403 is in 700 and OF agrees                               -> untouched.
    await _seed_item(401, [700])
    await _seed_item(402, [])
    await _seed_item(403, [700])
    _OF.members = {700: [403], 701: [402]}

    synced = await api._readback_membership(_OF, _AID, [700, 701])

    assert await _folder_ids(401) == [], "a dropped id must be removed"
    assert await _folder_ids(402) == [701], "a gained id must be added"
    assert await _folder_ids(403) == [700], "an unchanged item must not be rewritten"
    assert synced == 2, f"expected 2 touched rows, got {synced}"


async def case_readback_survives_a_dead_list():
    await _reset_db()
    _OF.reset()
    await _seed_item(501, [])
    await _seed_item(502, [])
    _OF.members = {800: [501], 801: [502]}
    _OF.page_fails.add(800)

    synced = await api._readback_membership(_OF, _AID, [800, 801])

    assert await _folder_ids(501) == [], "the dead list must contribute nothing"
    assert await _folder_ids(502) == [801], "a healthy list must still land"
    assert synced == 1, f"expected 1 touched row, got {synced}"


async def _seed_fixtures():
    async with get_session() as s:
        if await s.get(Account, _AID) is None:
            s.add(Account(id=_AID, nickname=_AID, color="#aaaaaa"))


_harness.run(
    _seed_fixtures,
    case_every_folder_is_made_before_any_readback,
    case_a_failed_folder_does_not_block_the_rest,
    case_existing_list_is_reused,
    case_readback_applies_every_list_in_one_pass,
    case_readback_survives_a_dead_list,
)
