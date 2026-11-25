#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import json  # noqa: E402
from datetime import datetime  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select  # noqa: E402

import accounts as account_registry  # noqa: E402
import automation_executor as ax  # noqa: E402 — the OF-client seam
import vault_ai_api as api  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, VaultFolder, VaultFolderItem, VaultItem  # noqa: E402

_MINE = "acc_mine"
_THEIRS = "acc_theirs"
_FRESH = "acc_never_collected"

_TEST_ACCOUNTS = {_MINE, _THEIRS, _FRESH}
account_registry.get_account = (
    lambda a: {"id": a, "nickname": a} if a in _TEST_ACCOUNTS else None
)
account_registry.list_accounts = (
    lambda: [{"id": a, "nickname": a} for a in sorted(_TEST_ACCOUNTS)]
)
account_registry.is_account = lambda aid: aid in _TEST_ACCOUNTS



class _FakeOF:

    def __init__(self):
        self.timeout_s = 5.0
        self.built_for: list[str] = []
        self.calls: list[tuple] = []
        self.next_list_id = 5001

    def reset(self) -> None:
        self.built_for.clear()
        self.calls.clear()

    def make_client(self, account_id, *_a, **_k):
        self.built_for.append(str(account_id))
        return self

    def create_vault_list(self, name):
        self.calls.append(("create_vault_list", name))
        self.next_list_id += 1
        return {"id": self.next_list_id, "name": name}

    def add_media_to_vault_list(self, list_id, media_ids):
        self.calls.append(("add_media_to_vault_list", int(list_id), list(media_ids)))
        return {"success": True}

    def remove_media_from_vault_list(self, list_id, media_ids):
        self.calls.append(("remove_media_from_vault_list", int(list_id), list(media_ids)))
        return {"id": int(list_id)}

    def hide_vault_media(self, media_ids):
        self.calls.append(("hide_vault_media", list(media_ids)))
        return {"success": True}

    def vault_list_media(self, *_a, **_k):
        return {"list": [], "hasMore": False}

    def touched(self) -> bool:
        return bool(self.built_for or self.calls)


_OF = _FakeOF()
ax._make_client = _OF.make_client  # type: ignore[assignment]


async def _route_refused(coro) -> dict | None:
    try:
        await coro
    except HTTPException as e:
        assert e.status_code == 404, \
            f"expected the guard's 404, got {e.status_code}: {e.detail!r}"
        return e.detail if isinstance(e.detail, dict) else {"error": str(e.detail)}
    return None


async def _seed_item(account_id: str, media_id: int) -> None:
    now = datetime.utcnow()
    async with get_session() as s:
        if await s.get(VaultItem, (account_id, media_id)) is not None:
            return
        s.add(VaultItem(
            account_id=account_id, media_id=media_id, kind="photo",
            raw_json=json.dumps({"id": media_id}), created_at=now, updated_at=now,
            last_seen_run_id=1, search_text="photo", tags="[]", of_folder_ids="[]",
        ))
        await s.commit()


async def _seed_folder(account_id: str, name: str) -> int:
    async with get_session() as s:
        f = VaultFolder(account_id=account_id, name=name, created_by="operator")
        s.add(f)
        await s.commit()
        return f.id


async def _seed_member(account_id: str, folder_id: int, media_id: int) -> None:
    async with get_session() as s:
        s.add(VaultFolderItem(account_id=account_id, folder_id=folder_id,
                              media_id=media_id))
        await s.commit()


async def _refused(account_id: str, media_ids: list[int]) -> dict | None:
    try:
        await api._reject_foreign_media(account_id, media_ids)
    except HTTPException as e:
        assert e.status_code == 404, f"expected 404, got {e.status_code}"
        return e.detail if isinstance(e.detail, dict) else {"error": str(e.detail)}
    return None



async def case_foreign_id_is_refused():
    await _seed_item(_MINE, 11)
    await _seed_item(_THEIRS, 99)

    detail = await _refused(_MINE, [99])

    assert detail is not None, "another model's media id must not reach OnlyFans"
    assert detail.get("error") == "not_in_mirror", f"got {detail!r}"
    assert detail.get("media_ids") == [99], f"the offending id is reported: {detail!r}"


async def case_own_ids_pass():
    await _seed_item(_MINE, 11)
    await _seed_item(_MINE, 12)

    assert await _refused(_MINE, [11, 12]) is None, \
        "the account's own media must go through"


async def case_partial_selection_is_refused_whole():
    for mid in range(20, 29):
        await _seed_item(_MINE, mid)
    await _seed_item(_THEIRS, 999)

    detail = await _refused(_MINE, [*range(20, 29), 999])

    assert detail is not None, "one foreign id poisons the batch"
    assert detail.get("media_ids") == [999], \
        f"only the foreign id is named, got {detail.get('media_ids')!r}"


async def case_uncollected_account_is_let_through():
    async with get_session() as s:
        rows = (await s.execute(
            select(VaultItem).where(VaultItem.account_id == _FRESH)
        )).scalars().all()
        assert rows == [], "this case needs an account with no mirror at all"

    assert await _refused(_FRESH, [11, 99, 12345]) is None, (
        "an account that has never been collected is served live from OnlyFans; "
        "the guard cannot judge its media and must not break foldering for it")


async def case_empty_list_is_not_an_error():
    assert await _refused(_MINE, []) is None, "nothing to check is not a refusal"


async def case_a_hidden_media_is_still_ours():
    await _seed_item(_MINE, 31)
    now = datetime.utcnow()
    async with get_session() as s:
        row = await s.get(VaultItem, (_MINE, 31))
        row.removed_at = now
        await s.commit()

    assert await _refused(_MINE, [31]) is None, \
        "a hidden media is still this model's media"



async def case_route_of_folder_create_refuses():
    await _seed_item(_MINE, 41)
    await _seed_item(_THEIRS, 941)
    _OF.reset()

    detail = await _route_refused(api.create_of_folder(
        {"account_id": _MINE, "name": "beach", "media_ids": [41, 941]}))

    assert detail is not None, "create-with-media must refuse a foreign id"
    assert detail.get("error") == "not_in_mirror", f"got {detail!r}"
    assert not _OF.touched(), (
        "the refusal has to land BEFORE the folder is created — an empty folder "
        f"on her OnlyFans is litter the operator clears by hand; OF saw {_OF.calls!r}")


async def case_route_of_folder_add_refuses():
    await _seed_item(_MINE, 42)
    await _seed_item(_THEIRS, 942)
    _OF.reset()

    detail = await _route_refused(api.add_to_of_folder(
        7001, {"account_id": _MINE, "media_ids": [42, 942]}))

    assert detail is not None, "add-to-OF-folder must refuse a foreign id"
    assert not _OF.touched(), f"nothing may reach OF, saw {_OF.calls!r}"


# OF has no unhide: the one refusal that cannot be walked back
async def case_route_hide_refuses():
    await _seed_item(_THEIRS, 943)
    _OF.reset()

    detail = await _route_refused(api.hide_item(943, {"account_id": _MINE}))

    assert detail is not None, "hiding another model's media must be refused"
    assert not _OF.touched(), (
        "a hide that reached OnlyFans cannot be undone by anything in this "
        f"codebase or its UI; OF saw {_OF.calls!r}")


async def case_route_publish_refuses():
    fid = await _seed_folder(_MINE, "poisoned")
    await _seed_item(_MINE, 45)
    await _seed_item(_THEIRS, 945)
    await _seed_member(_MINE, fid, 45)
    await _seed_member(_MINE, fid, 945)
    _OF.reset()

    detail = await _route_refused(api.publish_folder_to_of(
        fid, {"account_id": _MINE}))

    assert detail is not None, "a poisoned folder must not publish"
    assert detail.get("media_ids") == [945], f"the offending id is named: {detail!r}"
    assert not _OF.touched(), f"nothing may reach OF, saw {_OF.calls!r}"


async def case_route_of_folder_create_passes_own_ids():
    await _seed_item(_MINE, 46)
    await _seed_item(_MINE, 47)
    _OF.reset()

    out = await api.create_of_folder(
        {"account_id": _MINE, "name": "sunset", "media_ids": [46, 47]})

    assert out.get("added") == 2, f"our own ids must reach OF, got {out!r}"
    assert ("add_media_to_vault_list", out["id"], [46, 47]) in _OF.calls, \
        f"the ids OF received are the ids we sent: {_OF.calls!r}"


async def case_route_of_folder_remove_refuses():
    await _seed_item(_MINE, 48)
    await _seed_item(_THEIRS, 948)
    _OF.reset()

    detail = await _route_refused(api.remove_from_of_folder(
        7002, {"account_id": _MINE, "media_ids": [48, 948]}))

    assert detail is not None, "remove-from-OF-folder must refuse a foreign id"
    assert not _OF.touched(), f"nothing may reach OF, saw {_OF.calls!r}"


async def case_route_of_folder_remove_passes_own_ids():
    await _seed_item(_MINE, 48)
    await _seed_item(_MINE, 49)
    _OF.reset()

    out = await api.remove_from_of_folder(
        7002, {"account_id": _MINE, "media_ids": [48, "49"]})

    assert out == {"account_id": _MINE, "list_id": 7002, "removed": 2}, out
    assert _OF.calls == [("remove_media_from_vault_list", 7002, [48, 49])], _OF.calls


async def case_client_removes_from_folder():
    import of_client
    c = of_client.OFClient.__new__(of_client.OFClient)
    sent = []
    c.request_json = lambda method, path, **kw: sent.append((method, path, kw)) or {"id": 7}
    assert c.remove_media_from_vault_list(7, ["48", 49]) == {"id": 7}
    assert sent == [("DELETE", f"{of_client.API_BASE}/vault/lists/7/media",
                     {"json_body": {"mediaIds": [48, 49]}})], sent


async def _seed_fixtures():
    async with get_session() as s:
        for aid in (_MINE, _THEIRS, _FRESH):
            if await s.get(Account, aid) is None:
                s.add(Account(id=aid, nickname=aid, color="#aaaaaa"))
        await s.commit()


_harness.run(
    _seed_fixtures,
    case_foreign_id_is_refused,
    case_own_ids_pass,
    case_partial_selection_is_refused_whole,
    case_uncollected_account_is_let_through,
    case_empty_list_is_not_an_error,
    case_a_hidden_media_is_still_ours,
    case_route_of_folder_create_refuses,
    case_route_of_folder_add_refuses,
    case_route_hide_refuses,
    case_route_publish_refuses,
    case_route_of_folder_create_passes_own_ids,
    case_route_of_folder_remove_refuses,
    case_route_of_folder_remove_passes_own_ids,
    case_client_removes_from_folder,
)
