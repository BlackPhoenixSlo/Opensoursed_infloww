#!/usr/bin/env python3
"""GET / POST /admin/vault-ai/folder-prices: an agency's price per vault folder (`vf:<id>` /
`of:<id>`), read by Full AI Chat's sell executor. Our DB only, no OF call.

Real HTTP with real owner / chatter logins (pattern: test_full_ai_internal_folders.py).

  case_set_list_update_clear     set vf + of, list sorted, re-set updates, null clears
  case_validation                account_id / ref / price errors as 400 with their codes; nothing written
  case_vf_must_be_live_and_ours  a deleted or another account's internal folder -> 404
  case_ownership                 another owner's account -> 403; a folder-limited chatter -> 403
  case_parse_tables              parse_ref / parse_cents edges

Run: ./venv/bin/python service/tests/test_vault_folder_prices.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB
_harness.bootstrap()

import uuid  # noqa: E402
from datetime import datetime  # noqa: E402

from sqlalchemy import select  # noqa: E402

import vault_folder_prices as vfp  # noqa: E402
from _pre_enforcement import seed_pre_enforcement_install  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, Chatter, ChatterFolderAccess, ChatterUser, User, UserAccount, VaultFolder, VaultFolderPrice,
)

AID, OTHER = "accFP", "accFPother"
URL = "/admin/vault-ai/folder-prices"
IDS: dict[str, int] = {}
C: dict[str, object] = {}


async def case_seed():
    uid, uid2, cid = uuid.uuid4().hex, uuid.uuid4().hex, uuid.uuid4().hex
    now = datetime.utcnow()
    async with get_session() as s:
        s.add_all([User(id=uid, username="ownerfp", password="secretpw"),
                   User(id=uid2, username="ownerfp2", password="secretpw")])
        s.add_all([Account(id=AID, nickname="FP"), Account(id=OTHER, nickname="O")])
    async with get_session() as s:
        s.add_all([UserAccount(user_id=uid, account_id=AID), UserAccount(user_id=uid2, account_id=OTHER)])
        s.add(Chatter(id=cid, username="cfp", password="secretpw", display_name="Cfp",
                      created_at=now, last_seen_at=now))
        live, gone, theirs = (VaultFolder(account_id=AID, name="beach"),
                              VaultFolder(account_id=AID, name="old", deleted_at=now),
                              VaultFolder(account_id=OTHER, name="theirs"))
        s.add_all([live, gone, theirs])
        await s.flush()
        IDS.update(live=live.id, gone=gone.id, theirs=theirs.id)
    async with get_session() as s:
        s.add(ChatterUser(chatter_id=cid, user_id=uid, created_at=now))
        s.add(ChatterFolderAccess(chatter_id=cid, account_id=AID, folder_id=12, folder_name="f12", created_at=now))
    await seed_pre_enforcement_install()
    C["owner"] = _login("/auth/login", "ownerfp")
    C["owner2"] = _login("/auth/login", "ownerfp2")
    C["chatter"] = _login("/chatter/login", "cfp")


def _login(path: str, user: str):
    c = _harness.make_client()
    r = c.post(path, json={"username": user, "password": "secretpw"})
    assert r.status_code == 200, (path, r.status_code, r.text)
    return c


def _set(ref, cents, who="owner", aid=AID):
    return C[who].post(URL, json={"account_id": aid, "ref": ref, "price_cents": cents})


def _list(who="owner", aid=AID):
    return C[who].get(f"{URL}?account_id={aid}")


async def _rows():
    async with get_session() as s:
        return {(a, r): c for a, r, c in (await s.execute(
            select(VaultFolderPrice.account_id, VaultFolderPrice.folder_ref, VaultFolderPrice.price_cents))).all()}


async def case_set_list_update_clear():
    vf = f"vf:{IDS['live']}"
    r = _set(vf, 2500)
    assert r.status_code == 200 and r.json() == {"account_id": AID, "ref": vf, "price_cents": 2500}, r.text
    assert _set("of:777", 7000).status_code == 200
    got = _list()
    assert got.status_code == 200 and got.json() == {"list": [{"ref": "of:777", "price_cents": 7000},
                                                              {"ref": vf, "price_cents": 2500}]}, got.text
    assert _set(vf, 4999).status_code == 200
    assert (await _rows())[(AID, vf)] == 4999, "re-set updates the one row"
    r = _set("of:777", None)
    assert r.status_code == 200 and r.json()["price_cents"] is None, r.text
    assert _list().json() == {"list": [{"ref": vf, "price_cents": 4999}]}
    assert _set("of:404", None).status_code == 200, "clearing an unpriced folder is a no-op"
    _set(vf, None)
    assert await _rows() == {}


async def case_validation():
    rows = [
        ({"ref": "of:1", "price_cents": 2500}, "account_id_required"),
        ({"account_id": AID, "ref": "x:1", "price_cents": 2500}, "bad_ref"),
        ({"account_id": AID, "ref": "vf:abc", "price_cents": 2500}, "bad_ref"),
        ({"account_id": AID, "price_cents": 2500}, "bad_ref"),
        ({"account_id": AID, "ref": "of:1", "price_cents": 999}, "bad_price"),
        ({"account_id": AID, "ref": "of:1", "price_cents": 20001}, "bad_price"),
        ({"account_id": AID, "ref": "of:1", "price_cents": 25.5}, "bad_price"),
        ({"account_id": AID, "ref": "of:1", "price_cents": "2500"}, "bad_price"),
        ({"account_id": AID, "ref": "of:1", "price_cents": True}, "bad_price"),
    ]
    for body, code in rows:
        r = C["owner"].post(URL, json=body)
        assert r.status_code == 400 and r.json()["detail"]["error"] == code, (body, r.status_code, r.text)
    r = C["owner"].post(URL, json={"account_id": AID, "ref": "of:1", "price_cents": 1})
    assert r.json()["detail"] == {"error": "bad_price", "min": 1000, "max": 20000}, r.text
    assert C["owner"].get(f"{URL}?account_id=").status_code == 400
    assert await _rows() == {}, "nothing written"
    assert _set("of:1", 1000).status_code == 200 and _set("of:1", 20000).status_code == 200, "bounds inclusive"
    _set("of:1", None)


async def case_vf_must_be_live_and_ours():
    assert _set(f"vf:{IDS['gone']}", 2500).status_code == 404, "deleted folder"
    assert _set(f"vf:{IDS['theirs']}", 2500).status_code == 404, "another account's folder"
    assert _set("vf:999999", 2500).status_code == 404, "no such folder"
    assert await _rows() == {}


async def case_ownership():
    assert _set("of:1", 2500, who="owner2").status_code == 403, "not this owner's account"
    assert _list(who="owner2").status_code == 403
    assert _set("of:1", 2500, who="chatter").status_code == 403, "folder-limited chatter"
    assert _list(who="chatter").status_code == 403
    assert _set("of:5", 3000, who="owner2", aid=OTHER).status_code == 200
    assert _list().json() == {"list": []}, "accounts never see each other's prices"
    assert await _rows() == {(OTHER, "of:5"): 3000}


def case_parse_tables():
    for raw, want in (("vf:12", "vf:12"), (" of:7 ", "of:7"), ("of:abc_1", "of:abc_1"), ("vf:", None),
                      ("of:", None), ("vf:1x", None), ("OF:1", None), (None, None), (12, None),
                      ("of:" + "9" * 41, None)):
        assert vfp.parse_ref(raw) == want, (raw, vfp.parse_ref(raw))
    for raw, want in ((1000, 1000), (20000, 20000), (2500.0, 2500), (999, None), (20001, None),
                      (25.5, None), ("2500", None), (None, None), (True, None), (False, None)):
        assert vfp.parse_cents(raw) == want, (raw, vfp.parse_cents(raw))


_harness.run()
