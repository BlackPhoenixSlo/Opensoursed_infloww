#!/usr/bin/env python3
"""
`_reject_foreign_media` — the routes that hand media ids to OnlyFans refuse ids
that are not this model's. Plain-assert, no pytest (repo convention).

Why this suite exists: /vault is scoped to one model, and the vault manager used
to carry its SELECTION across a model switch. Thirty items picked while looking
at one creator stayed selected when the operator clicked the next creator's chip,
and "add to folder" then posted those ids into the new creator's OnlyFans folder,
over her session — the relay forwarded whatever the client sent, having checked
only that the caller owned the account. The same stale-client path reached
`hide_item`, and OnlyFans has no unhide.

The panel now remounts per model, so the client should never send a foreign id
again. This is the layer that does not depend on the client being right, because
that assumption has already been wrong once and these two calls cannot be undone.

The escape hatch is the interesting boundary: an account that has never been
COLLECTED has an empty mirror, its grid is served straight from OnlyFans, and the
guard genuinely cannot tell its media from anyone else's. Refusing there would
break foldering for every uncollected account, so it stands aside — and this
suite pins that, because it is the case a future tightening will break first.

Testing the FUNCTION is not enough, and that was this suite's own first gap:
every case here called `_reject_foreign_media` directly, so the guard line could
be deleted from all five routes and nothing would go red. The thing that can
regress is the CALL SITES. The route cases below drive the real route bodies with
an OF double that fails the test the moment it is constructed, so a missing
guard is a test failure rather than a silent write against a creator's account.

Cases:
  case_foreign_id_is_refused        — an id belonging to another model 404s
                                    `not_in_mirror`.
  case_own_ids_pass                 — the account's own ids go through untouched.
  case_partial_selection_is_refused_whole — one foreign id among nine of ours
                                    refuses the batch; a half-written folder is
                                    not a state anyone can reason about.
  case_uncollected_account_is_let_through — an empty mirror stands aside.
  case_empty_list_is_not_an_error   — nothing to check is not a refusal.
  case_a_hidden_media_is_still_ours — a soft-deleted row is this account's media
                                    and must not be refused.
  case_route_of_folder_create_refuses — POST /of-folders, no OF client built.
  case_route_of_folder_add_refuses  — POST /of-folders/{id}/add, same.
  case_route_hide_refuses           — POST /items/{id}/hide, same. No unhide
                                    exists, so this is the one that cannot be
                                    walked back.
  case_route_publish_refuses        — POST /folders/{id}/publish re-checks what
                                    it reads back out of the DB.
  case_route_of_folder_create_passes_own_ids — and the guards are not blanket
                                    refusals: our own ids still reach OF.
  case_route_of_folder_remove_refuses — POST /of-folders/{id}/remove, no OF
                                    client built.
  case_route_of_folder_remove_passes_own_ids — our own ids reach OF's
                                    DELETE /vault/lists/{id}/media.
  case_client_removes_from_folder   — that call's exact wire shape.

Run: cd service/tests && \
  PYTHONPATH=$(cd .. && pwd) ../../venv/bin/python test_vault_foreign_media_guard.py
Exit 0 = all cases passed. Temp DB bound by _harness (never prod).
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

# These cases test feature logic, not the account gate (that is
# test_account_isolation_gate's job). They reach `/admin` routes or
# `assert_account_owned` with no session, which fails closed (401) since
# 3b30b486. This is the documented escape hatch (read per call), scoped to this
# test process.
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

# `assert_account_owned` resolves the principal against the registry; register
# the test ids in-process so the routes below reach their own logic instead of a
# 403 about a missing meta dir. (ALLOW_ANONYMOUS_ADMIN=1 is what lets an
# unauthenticated case through the auth gate at all — see the run line above.)
_TEST_ACCOUNTS = {_MINE, _THEIRS, _FRESH}
account_registry.get_account = (
    lambda a: {"id": a, "nickname": a} if a in _TEST_ACCOUNTS else None
)
account_registry.list_accounts = (
    lambda: [{"id": a, "nickname": a} for a in sorted(_TEST_ACCOUNTS)]
)
account_registry.is_account = lambda aid: aid in _TEST_ACCOUNTS


# ── The OF double ───────────────────────────────────────────────────

class _FakeOF:
    """Every OnlyFans write these routes can make, recorded.

    The recording IS the assertion. A guard that refuses must refuse BEFORE any
    of this happens — a folder created on her account and then abandoned is
    litter the operator has to clear by hand, and `hide_vault_media` has no
    inverse at all — so every refusal case below asserts this stayed empty.
    """

    def __init__(self):
        self.timeout_s = 5.0
        self.built_for: list[str] = []
        self.calls: list[tuple] = []
        self.next_list_id = 5001

    def reset(self) -> None:
        self.built_for.clear()
        self.calls.clear()

    # the seam vault_ai_api goes through
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
        """Did anything at all reach OnlyFans?

        Constructing the client counts. It is the step every one of these routes
        takes first, so "a client was built for this account" is the earliest and
        broadest evidence that a refusal came too late.
        """
        return bool(self.built_for or self.calls)


_OF = _FakeOF()
ax._make_client = _OF.make_client  # type: ignore[assignment]


async def _route_refused(coro) -> dict | None:
    """Run a route body; return its 404 refusal detail, or None if it did not
    refuse. Any other status is a hard failure — a route that 500s on a foreign
    id is not a route that refused it."""
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
    """The refusal detail, or None if the guard let it through."""
    try:
        await api._reject_foreign_media(account_id, media_ids)
    except HTTPException as e:
        assert e.status_code == 404, f"expected 404, got {e.status_code}"
        return e.detail if isinstance(e.detail, dict) else {"error": str(e.detail)}
    return None


# ── Cases ───────────────────────────────────────────────────────────

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
    """A soft-deleted row is this account's media, and the guard says so.

    `removed_at` means OnlyFans is not showing it (an operator hid it, or a
    render 404 buried it) — not that it belongs to somebody else. The guard
    deliberately does NOT filter on it: refusing here would block re-adding a
    media the operator can see in her own OnlyFans vault, and it would do it with
    an error message about the wrong model, which is a diagnosis nobody could
    act on. Note this is the opposite answer from `vault_ingest`, which DOES
    filter — the two are asking different questions ("is this ours" vs "is the
    grid reading the mirror"), and this case exists so that difference stays
    deliberate.
    """
    await _seed_item(_MINE, 31)
    now = datetime.utcnow()
    async with get_session() as s:
        row = await s.get(VaultItem, (_MINE, 31))
        row.removed_at = now
        await s.commit()

    assert await _refused(_MINE, [31]) is None, \
        "a hidden media is still this model's media"


# ── The call sites ──────────────────────────────────────────────────
# Everything above proves the FUNCTION refuses. These prove it is CALLED. Delete
# any one of the five `await _reject_foreign_media(...)` lines and exactly one of
# these goes red — which is the property the suite was missing.

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


async def case_route_hide_refuses():
    """The one that cannot be walked back: OnlyFans exposes no unhide."""
    await _seed_item(_THEIRS, 943)
    _OF.reset()

    detail = await _route_refused(api.hide_item(943, {"account_id": _MINE}))

    assert detail is not None, "hiding another model's media must be refused"
    assert not _OF.touched(), (
        "a hide that reached OnlyFans cannot be undone by anything in this "
        f"codebase or its UI; OF saw {_OF.calls!r}")


async def case_route_publish_refuses():
    """Publish re-checks what it reads out of the DB, not just what it was sent.

    The rows it reads were written from the wire by /folders/{id}/add, and any
    folder poisoned while that route was unguarded is still on disk. This is the
    last point before those ids are posted to her OnlyFans list.
    """
    fid = await _seed_folder(_MINE, "poisoned")
    await _seed_item(_MINE, 45)
    await _seed_item(_THEIRS, 945)
    await _seed_member(_MINE, fid, 45)
    await _seed_member(_MINE, fid, 945)      # as the live bug would have left it
    _OF.reset()

    detail = await _route_refused(api.publish_folder_to_of(
        fid, {"account_id": _MINE}))

    assert detail is not None, "a poisoned folder must not publish"
    assert detail.get("media_ids") == [945], f"the offending id is named: {detail!r}"
    assert not _OF.touched(), f"nothing may reach OF, saw {_OF.calls!r}"


async def case_route_of_folder_create_passes_own_ids():
    """And these are guards, not walls.

    Without this case every guard above could be satisfied by refusing
    everything, and the suite would look green while foldering was dead.
    """
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
