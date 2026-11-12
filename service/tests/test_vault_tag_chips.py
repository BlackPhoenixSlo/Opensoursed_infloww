#!/usr/bin/env python3
"""The Vault Pro grid's tag chips (service/vault_tags.py + vault_ai_api routes).

Real HTTP, real owner / chatter logins, temp DB. Mirror rows for accT:
  201 col tags ["feet","bed"]                       202 ai tags ["Feet","Lingerie"] (model case)
  203 ai primary_folder "Feet", ai tags ["shower"]  204 col ["feet_soles"] (not "feet": exact match)
  205 feet in all three sources (counted once)       206 col ["lingerie"], ai_fields_json malformed
  207 video, col ["feet","lingerie"]                 208 removed, col ["feet"]
  210 in OF folder 12, col ["feet"]                  901 other Creator, col ["feet"]

  items ?tags=          AND, the three sources, case-blind, exact element, removed / foreign out
  /tag-facets           counts per tag over the grid's filters (type, folder, picked tags), total
  /folders/from-tags    created_by=operator, members == the filter's result, default name, unique name,
                        400 tags_required / no_items, survives the vault_scripts reaper's predicate
  chatter (folder 12)   facets soft-deny outside its folder, scoped inside; save 403; nothing written

Run: ./venv/bin/python service/tests/test_vault_tag_chips.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB
_harness.bootstrap()

import json  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime  # noqa: E402

from sqlalchemy import select  # noqa: E402

import accounts as account_registry  # noqa: E402
import vault_scripts  # noqa: E402 — the reaper's predicate
import vault_tags  # noqa: E402
from _pre_enforcement import seed_pre_enforcement_install  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, Chatter, ChatterFolderAccess, ChatterUser, User, UserAccount, VaultFolder,
    VaultFolderItem, VaultItem,
)

AID, OTHER = "accT", "accO"
_orig_get_account = account_registry.get_account
account_registry.get_account = (
    lambda a: {"id": a, "nickname": a} if a in (AID, OTHER) else _orig_get_account(a))

_UNSET = object()


def _item(aid: str, mid: int, *, col=None, ai=_UNSET, kind: str = "photo", folders=(),
          removed: bool = False) -> VaultItem:
    ai_json = None if ai is _UNSET else (ai if isinstance(ai, str) else json.dumps(ai))
    return VaultItem(account_id=aid, media_id=mid, kind=kind,
                     raw_json=json.dumps({"id": mid, "type": kind}),
                     of_folder_ids=json.dumps(list(folders)), created_at=datetime(2026, 1, 1, 0, mid % 60),
                     tags=json.dumps(col) if col is not None else None, ai_fields_json=ai_json,
                     removed_at=datetime(2026, 2, 1) if removed else None)


async def case_seed():
    uid, cid = uuid.uuid4().hex, uuid.uuid4().hex
    async with get_session() as s:
        s.add(User(id=uid, username="ownert", password="secretpw"))
        s.add(Account(id=AID, nickname="T"))
        s.add(Account(id=OTHER, nickname="O"))
    async with get_session() as s:
        s.add(UserAccount(user_id=uid, account_id=AID))
        s.add(Chatter(id=cid, username="ct", password="secretpw", display_name="Ct",
                      created_at=datetime.utcnow(), last_seen_at=datetime.utcnow()))
    async with get_session() as s:
        s.add(ChatterUser(chatter_id=cid, user_id=uid, created_at=datetime.utcnow()))
        s.add(ChatterFolderAccess(chatter_id=cid, account_id=AID, folder_id=12,
                                  folder_name="f12", created_at=datetime.utcnow()))
        s.add_all([
            _item(AID, 201, col=["feet", "bed"]),
            _item(AID, 202, col=[], ai={"tags": ["Feet", " Lingerie "]}),
            _item(AID, 203, ai={"primary_folder": "Feet", "tags": ["shower"]}),
            _item(AID, 204, col=["feet_soles"]),
            _item(AID, 205, col=["feet"], ai={"tags": ["feet"], "primary_folder": "feet"}),
            _item(AID, 206, col=["lingerie"], ai="{not json"),
            _item(AID, 207, col=["feet", "lingerie"], kind="video"),
            _item(AID, 208, col=["feet"], removed=True),
            _item(AID, 210, col=["feet"], folders=[12]),
            _item(OTHER, 901, col=["feet"]),
        ])
    await seed_pre_enforcement_install()


def _login(path: str, user: str):
    c = _harness.make_client()
    r = c.post(path, json={"username": user, "password": "secretpw"})
    assert r.status_code == 200, (path, r.status_code, r.text)
    return c


def _ids(c, **params) -> set[int]:
    r = c.get("/admin/vault-ai/items", params={"account_id": AID, **params})
    assert r.status_code == 200, (r.status_code, r.text)
    return {m["id"] for m in r.json()["list"]}


def _facets(c, **params) -> dict:
    r = c.get("/admin/vault-ai/tag-facets", params={"account_id": AID, **params})
    assert r.status_code == 200, (r.status_code, r.text)
    return r.json()


async def _members(folder_id: int) -> set[int]:
    async with get_session() as s:
        return set((await s.execute(select(VaultFolderItem.media_id).where(
            VaultFolderItem.folder_id == folder_id))).scalars().all())


async def _folders() -> list[VaultFolder]:
    async with get_session() as s:
        return list((await s.execute(select(VaultFolder).where(
            VaultFolder.account_id == AID).order_by(VaultFolder.id))).scalars().all())


FEET = {201, 202, 203, 205, 207, 210}


def case_items_filter_three_sources_and_case():
    c = _login("/auth/login", "ownert")
    assert _ids(c, tags="feet") == FEET, _ids(c, tags="feet")
    assert _ids(c, tags="FEET ") == FEET, "the filter is case- and space-blind"
    assert _ids(c, tags="lingerie") == {202, 206, 207}, "malformed ai_fields_json is skipped, not a 500"
    assert _ids(c, tags=["feet", "lingerie"]) == {202, 207}, "two tags AND"
    assert _ids(c, tags=["feet", "lingerie"], type="video") == {207}
    assert _ids(c, tags="feet", of_folder_id=12) == {210}
    assert _ids(c, tags="feet_soles") == {204}
    assert _ids(c, tags="nope") == set()
    assert len(_ids(c)) == 8, "no tags = no tag filter"


def case_facets_counts():
    c = _login("/auth/login", "ownert")
    f = _facets(c)
    got = {t["tag"]: t["count"] for t in f["tags"]}
    assert got == {"feet": 6, "lingerie": 3, "bed": 1, "shower": 1, "feet_soles": 1}, got
    assert [t["tag"] for t in f["tags"]][:2] == ["feet", "lingerie"], "busiest first"
    assert f["total"] == 8 and f["selected"] == [], f
    v = _facets(c, type="video")
    assert {t["tag"]: t["count"] for t in v["tags"]} == {"feet": 1, "lingerie": 1}, v
    picked = _facets(c, tags="Feet")
    assert picked["total"] == 6 and picked["selected"] == ["feet"], picked
    assert {t["tag"]: t["count"] for t in picked["tags"]} == {"feet": 6, "lingerie": 2, "bed": 1, "shower": 1}
    assert {t["tag"]: t["count"] for t in _facets(c, of_folder_id=12)["tags"]} == {"feet": 1}


async def case_save_as_folder():
    c = _login("/auth/login", "ownert")
    r = c.post("/admin/vault-ai/folders/from-tags", json={"account_id": AID, "tags": ["feet", "Lingerie"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "feet + lingerie" and body["items"] == 2, body
    assert await _members(body["folder_id"]) == {202, 207}
    again = c.post("/admin/vault-ai/folders/from-tags", json={"account_id": AID, "tags": ["feet", "lingerie"]})
    assert again.status_code == 200 and again.json()["name"] == "feet + lingerie 2", again.text
    named = c.post("/admin/vault-ai/folders/from-tags",
                   json={"account_id": AID, "tags": ["feet"], "type": "photo", "name": "  Feet set  "})
    assert named.status_code == 200, named.text
    assert named.json()["name"] == "Feet set"
    assert await _members(named.json()["folder_id"]) == FEET - {207}
    for f in await _folders():
        assert f.created_by == "operator" and f.of_list_id is None and f.deleted_at is None, f.__dict__
        # vault_scripts.apply_ai_folders retires only created_by == AI_FOLDER_CREATOR AND AI- prefix.
        assert f.created_by != vault_scripts.AI_FOLDER_CREATOR

    assert c.post("/admin/vault-ai/folders/from-tags",
                  json={"account_id": AID, "tags": []}).json()["detail"]["error"] == "tags_required"
    r = c.post("/admin/vault-ai/folders/from-tags", json={"account_id": AID, "tags": ["nope"]})
    assert r.status_code == 400 and r.json()["detail"]["error"] == "no_items", r.text
    cap = vault_tags.FOLDER_MAX_ITEMS
    vault_tags.FOLDER_MAX_ITEMS = 3
    try:
        r = c.post("/admin/vault-ai/folders/from-tags", json={"account_id": AID, "tags": ["feet"]})
    finally:
        vault_tags.FOLDER_MAX_ITEMS = cap
    d = r.json()["detail"]
    assert r.status_code == 400 and d["error"] == "too_many_items" and d["count"] == len(FEET) and d["cap"] == 3, r.text
    assert len(await _folders()) == 3, "a refused save writes nothing"


async def case_chatter_scope():
    before = len(await _folders())
    ch = _login("/chatter/login", "ct")
    assert _facets(ch) == {"tags": [], "total": 0, "selected": []}, "All: soft deny"
    inside = _facets(ch, of_folder_id=12)
    assert {t["tag"]: t["count"] for t in inside["tags"]} == {"feet": 1} and inside["total"] == 1, inside
    r = ch.post("/admin/vault-ai/folders/from-tags", json={"account_id": AID, "tags": ["feet"], "of_folder_id": 12})
    assert r.status_code == 403, r.text
    assert len(await _folders()) == before


def case_pure_helpers():
    assert vault_tags.parse_tags([" Feet", "feet", "", "LACE", None]) == ["feet", "lace"]
    assert len(vault_tags.parse_tags([str(i) for i in range(20)])) == vault_tags.MAX_TAGS
    assert vault_tags.default_folder_name(["feet", "lace"]) == "feet + lace"
    assert vault_tags.unique_name("a", {"a", "a 2"}) == "a 3"
    assert vault_tags.unique_name("b", {"a"}) == "b"


_harness.run(
    case_seed,
    case_items_filter_three_sources_and_case,
    case_facets_counts,
    case_save_as_folder,
    case_chatter_scope,
    case_pure_helpers,
)
