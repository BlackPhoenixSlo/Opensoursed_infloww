#!/usr/bin/env python3
"""GET /admin/vault-ai/internal-folders (ticket 49): the Creator's live INTERNAL vault folders
for Full AI Chat's Content folders picker (`vf:<id>` refs), with their item counts. No OF call.

Real HTTP with real owner / chatter logins (pattern: test_vault_chatter_folders.py).

  case_owner_lists_live_folders_with_counts   deleted folders and other accounts' folders left out; sorted by name
  case_restricted_chatter_gets_none           a chatter limited to OF folders sees no internal folder

Run: ./venv/bin/python service/tests/test_full_ai_internal_folders.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB
_harness.bootstrap()

import uuid  # noqa: E402
from datetime import datetime  # noqa: E402

from _pre_enforcement import seed_pre_enforcement_install  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, Chatter, ChatterFolderAccess, ChatterUser, User, UserAccount, VaultFolder, VaultFolderItem, VaultItem,
)

AID = "accIF"
Q = f"/admin/vault-ai/internal-folders?account_id={AID}"
IDS: dict[str, int] = {}


async def case_seed():
    uid, cid = uuid.uuid4().hex, uuid.uuid4().hex
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(User(id=uid, username="ownerif", password="secretpw"))
        s.add_all([Account(id=AID, nickname="IF"), Account(id="accOther", nickname="O")])
    async with get_session() as s:
        s.add(UserAccount(user_id=uid, account_id=AID))
        s.add(Chatter(id=cid, username="cif", password="secretpw", display_name="Cif",
                      created_at=now, last_seen_at=now))
        beach, ai = VaultFolder(account_id=AID, name="beach"), VaultFolder(account_id=AID, name="AI-lingerie")
        gone = VaultFolder(account_id=AID, name="old", deleted_at=now)
        s.add_all([beach, ai, gone, VaultFolder(account_id="accOther", name="theirs")])
        await s.flush()
        s.add_all([VaultFolderItem(account_id=AID, folder_id=ai.id, media_id=m) for m in (1, 2, 3)]
                  + [VaultFolderItem(account_id=AID, folder_id=gone.id, media_id=9)])
        # Media 3 was removed from the vault: the sell pool skips it, so the count does too.
        s.add_all([VaultItem(account_id=AID, media_id=m, kind="photo", created_at=now,
                             removed_at=now if m == 3 else None) for m in (1, 2, 3, 9)])
        IDS.update(ai=ai.id, beach=beach.id)
    async with get_session() as s:
        s.add(ChatterUser(chatter_id=cid, user_id=uid, created_at=now))
        s.add(ChatterFolderAccess(chatter_id=cid, account_id=AID, folder_id=12, folder_name="f12", created_at=now))
    await seed_pre_enforcement_install()


def _login(path: str, user: str):
    c = _harness.make_client()
    r = c.post(path, json={"username": user, "password": "secretpw"})
    assert r.status_code == 200, (path, r.status_code, r.text)
    return c


def case_owner_lists_live_folders_with_counts():
    r = _login("/auth/login", "ownerif").get(Q)
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.json() == {"list": [{"id": IDS["ai"], "name": "AI-lingerie", "items": 2},
                                 {"id": IDS["beach"], "name": "beach", "items": 0}]}, r.json()


def case_restricted_chatter_gets_none():
    r = _login("/chatter/login", "cif").get(Q)
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.json() == {"list": []}, r.json()


_harness.run()
