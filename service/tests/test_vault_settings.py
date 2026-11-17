#!/usr/bin/env python3
"""`vault_settings`: the two per-Creator vault switches, both OFF by default, and what off means.

  case_seed                       owner / other owner / folder-limited chatter logins
  case_default_off_and_routes     no row = both off; PUT sets one, keeps the other; bad bodies 400
  case_scope                      another owner's account and a folder-limited chatter -> 403
  case_standard_off_is_inert      off: sync creates no folder, listing is empty, a describe places nothing,
                                  a leftover Needs Review folder does not take media out of the sale pool,
                                  and is neither listed in the internal folders nor editable (404)
  case_price_final_off_is_before  off: rows carry no mark, a Pick has no locked price, the tease price and a
                                  haggle move it (the 11-15 rule: Jev decides the price)
  case_price_final_on_marks_rows  on: `load_rows` marks every row; off again: the mark is gone

Run: ./venv/bin/python service/tests/test_vault_settings.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB
_harness.bootstrap()

import json  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from sqlalchemy import func, select  # noqa: E402

import vault_settings  # noqa: E402
import vault_standard_folders as folders  # noqa: E402
from _pre_enforcement import seed_pre_enforcement_install  # noqa: E402
from automations import full_ai_sell as sell, full_ai_turn as turn  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, Chatter, ChatterFolderAccess, ChatterUser, User, UserAccount, VaultFolder, VaultFolderItem,
    VaultFolderPrice, VaultItem,
)
from vault_standard_rules import REVIEW, key  # noqa: E402

AID, OTHER = "accVS", "accVSother"
URL = "/admin/vault-ai/settings"
OFF = {"folder_price_final": False, "standard_folders": False}
C: dict[str, object] = {}


def _login(path: str, user: str):
    c = _harness.make_client()
    r = c.post(path, json={"username": user, "password": "secretpw"})
    assert r.status_code == 200, (path, r.status_code, r.text)
    return c


async def case_seed():
    uid, uid2, cid = uuid.uuid4().hex, uuid.uuid4().hex, uuid.uuid4().hex
    now = datetime.utcnow()
    async with get_session() as s:
        s.add_all([User(id=uid, username="ownervs", password="secretpw"),
                   User(id=uid2, username="ownervs2", password="secretpw")])
        s.add_all([Account(id=AID, nickname="VS"), Account(id=OTHER, nickname="O")])
    async with get_session() as s:
        s.add_all([UserAccount(user_id=uid, account_id=AID), UserAccount(user_id=uid2, account_id=OTHER)])
        s.add(Chatter(id=cid, username="cvs", password="secretpw", display_name="Cvs",
                      created_at=now, last_seen_at=now))
        s.add_all([VaultItem(account_id=AID, media_id=m, kind="photo", created_at=now, describe_status="described",
                             ai_fields_json=json.dumps({"tags": ["bikini"], "suggested_price_cents": 5000}))
                   for m in (1, 2)])
    async with get_session() as s:
        s.add(ChatterUser(chatter_id=cid, user_id=uid, created_at=now))
        s.add(ChatterFolderAccess(chatter_id=cid, account_id=AID, folder_id=12, folder_name="f12", created_at=now))
    await seed_pre_enforcement_install()
    C["owner"], C["owner2"] = _login("/auth/login", "ownervs"), _login("/auth/login", "ownervs2")
    C["chatter"] = _login("/chatter/login", "cvs")


async def case_default_off_and_routes():
    assert await vault_settings.load(AID) == OFF
    got = C["owner"].get(URL, params={"account_id": AID})
    assert got.status_code == 200 and got.json() == {"account_id": AID, **OFF}, got.text
    r = C["owner"].put(URL, json={"account_id": AID, "folder_price_final": True})
    assert r.status_code == 200 and r.json() == {"account_id": AID, "folder_price_final": True,
                                                 "standard_folders": False}, r.text
    r = C["owner"].put(URL, json={"account_id": AID, "standard_folders": True})
    assert r.json() == {"account_id": AID, "folder_price_final": True, "standard_folders": True}, r.text
    assert await vault_settings.load(OTHER) == OFF, "per Creator"
    for body in ({"account_id": AID}, {"account_id": AID, "standard_folders": 1},
                 {"account_id": AID, "folder_price_final": "yes"}, {"standard_folders": True}):
        assert C["owner"].put(URL, json=body).status_code == 400, body
    r = C["owner"].put(URL, json={"account_id": AID, **OFF})
    assert r.status_code == 200 and await vault_settings.load(AID) == OFF


async def case_scope():
    for who in ("owner2", "chatter"):
        assert C[who].get(URL, params={"account_id": AID}).status_code == 403, who
        assert C[who].put(URL, json={"account_id": AID, "standard_folders": True}).status_code == 403, who
    assert await vault_settings.load(AID) == OFF


async def _standard_count() -> int:
    async with get_session() as s:
        return int(await s.scalar(select(func.count()).select_from(VaultFolder).where(
            VaultFolder.account_id == AID, VaultFolder.created_by.startswith("vault_standard:"))) or 0)


async def case_standard_off_is_inert():
    import vault_ai_vision
    assert await folders.sync(AID) == 0 and await _standard_count() == 0
    assert await folders.listing(AID) == {"list": [], "pending": 0}
    r = C["owner"].post("/admin/vault-ai/standard-folders/sync", json={"account_id": AID})
    assert r.status_code == 200 and r.json() == {"list": [], "pending": 0}, r.text
    await vault_ai_vision._write_item(AID, 1, describe_status="described",
                                      ai_fields_json=json.dumps({"tags": ["beach"], "suggested_price_cents": 5000}))
    assert await _standard_count() == 0, "a finished describe places nothing while the switch is off"
    # A Needs Review folder left from an earlier "on": off, its media is for sale again.
    async with get_session() as s:
        review = VaultFolder(account_id=AID, name="Photos / Uncategorised / Needs Review", created_by=key("photo", REVIEW))
        s.add(review)
        await s.flush()
        s.add(VaultFolderItem(account_id=AID, folder_id=review.id, media_id=2))
        rid = review.id
    rows, _, _ = await sell.load_rows(AID)
    assert {r["media_id"] for r in rows} == {1, 2}
    await vault_settings.put(AID, standard_folders=True)
    rows, _, _ = await sell.load_rows(AID)
    assert {r["media_id"] for r in rows} == {1}, "on: Needs Review blocks the sale"
    await vault_settings.put(AID, standard_folders=False)
    # Off: the leftover category is neither listed (vault, Full AI picker) nor editable.
    base = "/admin/vault-ai/internal-folders"
    listed = C["owner"].get(base, params={"account_id": AID}).json()["list"]
    assert rid not in {f["id"] for f in listed}, listed
    assert C["owner"].post(f"{base}/{rid}/add", json={"account_id": AID, "media_ids": [1]}).status_code == 404
    assert C["owner"].delete(f"{base}/{rid}", params={"account_id": AID}).status_code == 404
    await vault_settings.put(AID, standard_folders=True)
    listed = C["owner"].get(base, params={"account_id": AID}).json()["list"]
    assert rid in {f["id"] for f in listed}, "on: listed again"
    async with get_session() as s:
        s.add(VaultItem(account_id=AID, media_id=9, kind="video", created_at=datetime.utcnow()))
    r = C["owner"].post(f"{base}/{rid}/add", json={"account_id": AID, "media_ids": [9]})
    assert r.status_code == 400 and r.json()["detail"] == {"error": "category_media_type", "kind": "photo"}, r.text
    async with get_session() as s:
        assert await s.get(VaultFolderItem, (AID, rid, 9)) is None, "refused: nothing filed"
        await s.delete(await s.get(VaultItem, (AID, 9)))
    await vault_settings.put(AID, standard_folders=False)
    async with get_session() as s:
        await s.delete(await s.get(VaultFolderItem, (AID, rid, 2)))
        await s.delete(await s.get(VaultFolder, rid))


async def case_price_final_off_is_before():
    rows = [{"media_id": 55, "kind": "photo", "fields": {}, "folder_cents": 3500, "list_cents": 3500}]
    ask = sell.Ask("anything", "photo", 1)
    p = sell._offer(rows, [], ask, free=False)
    assert p.facts["folder_cents"] == 3500 and "folder_price_cents" not in p.facts and "folder_final" not in p.facts
    assert sell.folder_price(p) is None
    t = sell.tease_price(p, 1000)                         # the tease price Jev's price replaces the list
    assert (t.price_cents, t.list_cents, t.facts["vault_list_cents"]) == (1000, 1000, 3500), t
    free = sell.tease_price(p, 0)
    assert (free.price_cents, free.list_cents) == (0, 3500), free
    piece = SimpleNamespace(list_cents=3500)
    h = turn._haggled(p, piece, True, ["how about $25?"])  # a haggle moves it, down to 67 % at most
    assert h.price_cents == 2500 and h.list_cents == 3500, h
    assert turn._haggled(p, piece, True, ["$5?"]).price_cents == sell.clamp_quote(3500, 500)


async def case_price_final_on_marks_rows():
    async with get_session() as s:
        f = VaultFolder(account_id=AID, name="beach")
        s.add(f)
        await s.flush()
        s.add(VaultFolderItem(account_id=AID, folder_id=f.id, media_id=1))
        s.add(VaultFolderPrice(account_id=AID, folder_ref=f"vf:{f.id}", price_cents=3500))
    rows, _, _ = await sell.load_rows(AID)
    assert all("folder_final" not in r for r in rows), "off: rows as before"
    assert {r["media_id"]: r["folder_cents"] for r in rows} == {1: 3500, 2: None}
    await vault_settings.put(AID, folder_price_final=True)
    rows, _, _ = await sell.load_rows(AID)
    assert all(r["folder_final"] is True for r in rows)
    priced = [{**r, "list_cents": 3500, "fields": {}} for r in rows if r["media_id"] == 1]
    p = sell._offer(priced, [], sell.Ask("anything", "photo", 1), free=False)
    hold = sell.hold_folder_price   # the one clamp `_sell` runs last (rwl3 A9)
    assert sell.folder_price(p) == 3500 and hold(sell.tease_price(p, 1000)).price_cents == 3500
    assert hold(turn._haggled(p, SimpleNamespace(list_cents=3500), True, ["how about $25?"])).price_cents == 3500
    unpriced = [{**r, "list_cents": 5000, "fields": {}} for r in rows if r["media_id"] == 2]
    u = sell._offer(unpriced, [], sell.Ask("anything", "photo", 1), free=False)
    assert sell.folder_price(u) is None and hold(sell.tease_price(u, 1000)).price_cents == 1000, \
        "no folder price: Jev still prices"
    await vault_settings.put(AID, folder_price_final=False)
    rows, _, _ = await sell.load_rows(AID)
    assert all("folder_final" not in r for r in rows)


_harness.run()
