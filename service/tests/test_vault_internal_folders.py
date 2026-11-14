#!/usr/bin/env python3
"""The Inflowwww folders editor (`vault_internal_folders`): list + create / rename / add / remove /
reorder / delete of our own `vault_folders`. Our DB only, no OF call. Every write case asserts the rows
in `vault_folders` / `vault_folder_items` (and `vault_items` / `vault_folder_prices` where touched).

Real HTTP with real owner / second owner / folder-limited chatter logins
(pattern: test_vault_folder_prices.py, test_full_ai_internal_folders.py).

  case_list_fields_and_kinds      items/photos/videos/of_list_id/kind (ai / pack / own); deleted and other
                                  accounts' folders out; removed media not counted; nothing written
  case_create                     created_by="operator"; 400 name_required / name_too_long / reserved_name
                                  (any case); 409 name_taken; a deleted folder's name is free
  case_rename                     own: renamed, not adopted; AI folder adopted (created_by -> operator);
                                  409 / 400 reserved; 404 deleted / another account's folder
  case_add_copy_and_move          copy (added/already, idempotent); 404 not_in_mirror (foreign / unknown /
                                  removed) and 400 invalid_media_ids write nothing; move_from takes it out
                                  of the source; bad_move_from; AI target adopted, a no-op add is not
  case_pack_rungs                 feet_photos_only / not_free_safe write nothing; filing is exclusive in the
                                  category; rung<->plain moves (a refused one leaves the source); remove from
                                  a rung; rung rename / delete 400 pack_rung_fixed
  case_remove                     only members counted; media rows untouched; AI adopt only on a change
  case_reorder                    manual_order 0..n-1 == the listing's order (mixed 0,1,2 / NULL / -n / a
                                  removed member); before null = end; block keeps its order; bad_before;
                                  AI folder adopted only when the visible order changes
  case_delete                     deleted_at set, members + media stay, vf price cleared, of price kept,
                                  gone from the list, 404 after / for another account's folder
  case_rebuild_spares_edited_ai   an edited AI folder survives `apply_ai_folders`, a fresh AI-x is built
                                  beside it; an unedited one is rewritten in place
  case_scope                      second owner 403 everywhere; folder-limited chatter: list [], writes 403
                                  folder_not_allowed; nothing written
  case_pure_tables                folder_kind / reserved_name / place_before / listing_sort_key

Run: ./venv/bin/python service/tests/test_vault_internal_folders.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB
_harness.bootstrap()

import json  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import func, select  # noqa: E402

import vault_internal_folders as vif  # noqa: E402
import vault_scripts  # noqa: E402
from _pre_enforcement import seed_pre_enforcement_install  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, Chatter, ChatterFolderAccess, ChatterUser, User, UserAccount, VaultFolder, VaultFolderItem,
    VaultFolderPrice, VaultItem,
)

AID, LID, BID, OTHER = "accVIF", "accVIFlist", "accVIFbuild", "accVIFother"
BASE = "/admin/vault-ai/internal-folders"
SCRIPT = vault_scripts.AI_FOLDER_CREATOR
C: dict[str, object] = {}
T0 = datetime(2026, 11, 1, 12, 0, 0)

# Media per account: photos 1..20 (lower id = newer), videos 50/51, a removed photo 40, a Jev free-safe
# photo 30 and a Jev $50 (not free-safe) photo 31. OTHER owns 900.
PHOTOS = range(1, 21)


def _jev(lane5: str) -> str:
    return json.dumps({"_jev": {"v": "v8+nn.10", "status": "ok", "lane5": lane5, "breasts_bare": "n",
                                "crotch_bare": "n", "penetration": "n", "feet_subject": 0.9}})


def _media(aid: str) -> list[VaultItem]:
    rows = [VaultItem(account_id=aid, media_id=m, kind="photo", created_at=T0 - timedelta(minutes=m))
            for m in PHOTOS]
    rows += [VaultItem(account_id=aid, media_id=m, kind="video", created_at=T0 - timedelta(minutes=m))
             for m in (50, 51)]
    rows.append(VaultItem(account_id=aid, media_id=40, kind="photo", created_at=T0 - timedelta(minutes=40),
                          removed_at=T0))
    rows.append(VaultItem(account_id=aid, media_id=30, kind="photo", created_at=T0 - timedelta(minutes=30),
                          ai_fields_json=_jev("free")))
    rows.append(VaultItem(account_id=aid, media_id=31, kind="photo", created_at=T0 - timedelta(minutes=31),
                          ai_fields_json=_jev("$50")))
    return rows


async def case_seed():
    uid, uid2, cid = uuid.uuid4().hex, uuid.uuid4().hex, uuid.uuid4().hex
    now = datetime.utcnow()
    async with get_session() as s:
        s.add_all([User(id=uid, username="ownervif", password="secretpw"),
                   User(id=uid2, username="ownervif2", password="secretpw")])
        s.add_all([Account(id=a, nickname=a) for a in (AID, LID, BID, OTHER)])
    async with get_session() as s:
        s.add_all([UserAccount(user_id=uid, account_id=a) for a in (AID, LID, BID)]
                  + [UserAccount(user_id=uid2, account_id=OTHER)])
        s.add(Chatter(id=cid, username="cvif", password="secretpw", display_name="Cvif",
                      created_at=now, last_seen_at=now))
        for a in (AID, LID, BID):
            s.add_all(_media(a))
        s.add(VaultItem(account_id=OTHER, media_id=900, kind="photo", created_at=T0))
    async with get_session() as s:
        s.add(ChatterUser(chatter_id=cid, user_id=uid, created_at=now))
        s.add(ChatterFolderAccess(chatter_id=cid, account_id=AID, folder_id=12, folder_name="f12", created_at=now))
    await seed_pre_enforcement_install()
    C["owner"] = _login("/auth/login", "ownervif")
    C["owner2"] = _login("/auth/login", "ownervif2")
    C["chatter"] = _login("/chatter/login", "cvif")


def _login(path: str, user: str):
    c = _harness.make_client()
    r = c.post(path, json={"username": user, "password": "secretpw"})
    assert r.status_code == 200, (path, r.status_code, r.text)
    return c


# ── Helpers ──────────────────────────────────────────────────────────

async def _mk(name: str, *, by: str = "operator", items=(), aid: str = AID, deleted: bool = False,
              of_list_id: int | None = None) -> int:
    """A folder with `items`: media ids, or (media_id, manual_order) pairs."""
    async with get_session() as s:
        f = VaultFolder(account_id=aid, name=name, created_by=by, of_list_id=of_list_id,
                        deleted_at=T0 if deleted else None)
        s.add(f)
        await s.flush()
        for it in items:
            m, mo = it if isinstance(it, tuple) else (it, None)
            s.add(VaultFolderItem(account_id=aid, folder_id=f.id, media_id=m, manual_order=mo))
        await s.commit()
        return f.id


async def _members(fid: int, aid: str = AID) -> dict[int, int | None]:
    async with get_session() as s:
        return {int(m): mo for m, mo in (await s.execute(
            select(VaultFolderItem.media_id, VaultFolderItem.manual_order).where(
                VaultFolderItem.account_id == aid, VaultFolderItem.folder_id == fid))).all()}


async def _row(fid: int) -> VaultFolder:
    async with get_session() as s:
        return await s.get(VaultFolder, fid)


async def _folder_count(aid: str = AID) -> int:
    async with get_session() as s:
        return int((await s.execute(select(func.count()).select_from(VaultFolder)
                                    .where(VaultFolder.account_id == aid))).scalar_one())


async def _item_rows(aid: str = AID) -> int:
    async with get_session() as s:
        return int((await s.execute(select(func.count()).select_from(VaultFolderItem)
                                    .where(VaultFolderItem.account_id == aid))).scalar_one())


def _post(path: str, body: dict, who: str = "owner", aid: str = AID):
    return C[who].post(f"{BASE}{path}", json={"account_id": aid, **body})


def _delete(fid: int, who: str = "owner", aid: str = AID):
    return C[who].delete(f"{BASE}/{fid}?account_id={aid}")


def _list(who: str = "owner", aid: str = AID):
    return C[who].get(f"{BASE}?account_id={aid}")


def _err(r, status: int, code: str):
    assert r.status_code == status and r.json()["detail"]["error"] == code, (status, code, r.status_code, r.text)


def _listing(fid: int, aid: str = AID) -> list[int]:
    r = C["owner"].get(f"/admin/vault-ai/items?account_id={aid}&internal_folder_id={fid}")
    assert r.status_code == 200, r.text
    return [int(i["id"]) for i in r.json()["list"]]


def _by_order(members: dict[int, int | None]) -> list[int]:
    return [m for m, _ in sorted(members.items(), key=lambda kv: kv[1])]


# ── Cases ────────────────────────────────────────────────────────────

async def case_list_fields_and_kinds():
    ai = await _mk("AI-lingerie", by=SCRIPT, items=(1, 2, 50, 40), aid=LID)
    hand = await _mk("AI-handmade", items=(3,), aid=LID)
    rung = await _mk("feet-nude", items=(4, 5), aid=LID)
    beach = await _mk("beach", of_list_id=777, aid=LID)
    zed = await _mk("Zed", by=SCRIPT, items=(51,), aid=LID)
    await _mk("old", items=(6,), aid=LID, deleted=True)
    await _mk("theirs", items=(900,), aid=OTHER)
    before = await _folder_count(LID), await _item_rows(LID)
    r = _list(aid=LID)
    assert r.status_code == 200, r.text
    row = lambda i, n, c, p, v, of, k: {"id": i, "name": n, "items": c, "photos": p, "videos": v,  # noqa: E731
                                        "of_list_id": of, "kind": k}
    assert r.json() == {"list": [
        row(hand, "AI-handmade", 1, 1, 0, None, "own"),       # AI- name but the operator's
        row(ai, "AI-lingerie", 3, 2, 1, None, "ai"),          # removed 40 not counted
        row(beach, "beach", 0, 0, 0, 777, "own"),
        row(rung, "feet-nude", 2, 2, 0, None, "pack"),
        row(zed, "Zed", 1, 0, 1, None, "own"),                # generated but no AI- prefix
    ]}, r.json()
    assert (await _folder_count(LID), await _item_rows(LID)) == before, "a read writes nothing"
    assert (await _row(ai)).created_by == SCRIPT


async def case_create():
    r = _post("", {"name": "  trips  "})
    assert r.status_code == 200, r.text
    fid = r.json()["folder_id"]
    assert r.json() == {"account_id": AID, "folder_id": fid, "name": "trips"}, r.json()
    f = await _row(fid)
    assert (f.account_id, f.name, f.created_by, f.deleted_at, f.of_list_id) == (AID, "trips", "operator", None, None)
    assert await _members(fid) == {}
    n = await _folder_count()
    for body, status, code in (
            ({}, 400, "name_required"), ({"name": ""}, 400, "name_required"), ({"name": "   "}, 400, "name_required"),
            ({"name": "x" * 121}, 400, "name_too_long"),
            ({"name": "feet-tease"}, 400, "reserved_name"), ({"name": "Feet-Tease"}, 400, "reserved_name"),
            ({"name": " FEET-NUDE-BODY "}, 400, "reserved_name"),
            ({"name": "trips"}, 409, "name_taken")):
        _err(_post("", body), status, code)
    assert C["owner"].post(BASE, json={"name": "x"}).status_code == 400, "account_id required"
    assert await _folder_count() == n, "a refused create writes nothing"
    r = _post("", {"name": "y" * 120})
    assert r.status_code == 200, "120 chars is the max, inclusive"
    await _mk("gone-name", deleted=True)
    r = _post("", {"name": "gone-name"})
    assert r.status_code == 200, "a deleted folder's name is free again"
    assert (await _row(r.json()["folder_id"])).deleted_at is None


async def case_rename():
    own = await _mk("r1", items=(1,))
    r = _post(f"/{own}/rename", {"name": " r1b "})
    assert r.status_code == 200 and r.json() == {"account_id": AID, "folder_id": own, "name": "r1b",
                                                 "adopted": []}, r.text
    f = await _row(own)
    assert (f.name, f.created_by) == ("r1b", "operator")
    ai = await _mk("AI-r2", by=SCRIPT, items=((2, 0),))
    r = _post(f"/{ai}/rename", {"name": "r2 mine"})
    assert r.status_code == 200 and r.json()["adopted"] == [ai], r.text
    f = await _row(ai)
    assert (f.name, f.created_by) == ("r2 mine", "operator"), "a renamed AI folder becomes the operator's"
    assert await _members(ai) == {2: 0}, "membership untouched"
    assert _post(f"/{own}/rename", {"name": "r1b"}).status_code == 200, "its own name is not taken"
    _err(_post(f"/{own}/rename", {"name": "r2 mine"}), 409, "name_taken")
    _err(_post(f"/{own}/rename", {"name": "Feet-Nude"}), 400, "reserved_name")
    _err(_post(f"/{own}/rename", {"name": ""}), 400, "name_required")
    gone = await _mk("r3", deleted=True)
    theirs = await _mk("r4", aid=OTHER)
    _err(_post(f"/{gone}/rename", {"name": "r3b"}), 404, "folder_not_found")
    _err(_post(f"/{theirs}/rename", {"name": "r4b"}), 404, "folder_not_found")
    _err(_post("/999999/rename", {"name": "r5"}), 404, "folder_not_found")
    assert ((await _row(own)).name, (await _row(gone)).name, (await _row(theirs)).name) == ("r1b", "r3", "r4")


async def case_add_copy_and_move():
    a1 = await _mk("a1", items=(1,))
    r = _post(f"/{a1}/add", {"media_ids": [1, 2, 3, 2]})
    assert r.status_code == 200 and r.json() == {"account_id": AID, "folder_id": a1, "added": 2, "already": 1,
                                                 "moved": 0, "adopted": []}, r.text
    assert set(await _members(a1)) == {1, 2, 3}
    r = _post(f"/{a1}/add", {"media_ids": [1, 2, 3]})
    assert r.json()["added"] == 0 and r.json()["already"] == 3, r.text
    assert set(await _members(a1)) == {1, 2, 3} and await _item_rows() >= 3
    # Not this account's live media: the whole request is refused, nothing written.
    for ids, foreign in (([4, 900], [900]), ([99999], [99999]), ([4, 40], [40])):
        r = _post(f"/{a1}/add", {"media_ids": ids})
        _err(r, 404, "not_in_mirror")
        assert r.json()["detail"]["media_ids"] == foreign, r.text
    for bad in (["5"], [True], [1.0], [4, "5"]):
        _err(_post(f"/{a1}/add", {"media_ids": bad}), 400, "invalid_media_ids")
    for bad in ([], None, "4"):
        _err(_post(f"/{a1}/add", {"media_ids": bad}), 400, "media_ids_required")
    assert set(await _members(a1)) == {1, 2, 3}, "refused adds wrote nothing"
    # Move: out of the source in the same call.
    a2 = await _mk("a2", items=(5, 6))
    r = _post(f"/{a1}/add", {"media_ids": [5], "move_from": a2})
    assert r.status_code == 200 and (r.json()["added"], r.json()["moved"]) == (1, 1), r.text
    assert set(await _members(a1)) == {1, 2, 3, 5} and set(await _members(a2)) == {6}
    for mf in (a1, "x", True, 1.0):
        _err(_post(f"/{a1}/add", {"media_ids": [6], "move_from": mf}), 400, "bad_move_from")
    gone = await _mk("a-gone", items=(6,), deleted=True)
    _err(_post(f"/{a1}/add", {"media_ids": [6], "move_from": gone}), 404, "folder_not_found")
    _err(_post(f"/{gone}/add", {"media_ids": [6]}), 404, "folder_not_found")
    assert set(await _members(a1)) == {1, 2, 3, 5} and set(await _members(a2)) == {6}
    assert set(await _members(gone)) == {6}
    # Adding to an AI folder adopts it; a no-op add (all already members) does not.
    a3 = await _mk("AI-a3", by=SCRIPT, items=((8, 0),))
    r = _post(f"/{a3}/add", {"media_ids": [8]})
    assert r.json()["adopted"] == [] and (await _row(a3)).created_by == SCRIPT, r.text
    r = _post(f"/{a3}/add", {"media_ids": [7, 8]})
    assert r.json()["adopted"] == [a3] and (await _row(a3)).created_by == "operator", r.text
    assert set(await _members(a3)) == {7, 8}
    # Moving out of an AI folder adopts the source too.
    a4 = await _mk("AI-a4", by=SCRIPT, items=((9, 0),))
    r = _post(f"/{a1}/add", {"media_ids": [9], "move_from": a4})
    assert r.json()["adopted"] == [a4] and (await _row(a4)).created_by == "operator", r.text
    assert await _members(a4) == {} and 9 in await _members(a1)


async def case_pack_rungs():
    tease, nude, body = (await _mk("feet-tease"), await _mk("feet-nude"), await _mk("feet-nude-body"))
    snap = lambda: _gather(tease, nude, body)  # noqa: E731

    r = _post(f"/{nude}/add", {"media_ids": [50]})
    _err(r, 400, "feet_photos_only")
    assert r.json()["detail"]["media_ids"] == [50], r.text
    _err(_post(f"/{nude}/add", {"media_ids": [10, 51]}), 400, "feet_photos_only")
    r = _post(f"/{tease}/add", {"media_ids": [31, 10]})
    _err(r, 400, "not_free_safe")
    assert r.json()["detail"]["media_ids"] == [31], r.text
    assert await snap() == [set(), set(), set()], "refused rung adds wrote nothing"
    assert _post(f"/{nude}/add", {"media_ids": [31]}).status_code == 200, "a paid rung takes an unsafe body"

    r = _post(f"/{tease}/add", {"media_ids": [30, 10]})
    assert r.status_code == 200 and r.json()["added"] == 2, r.text
    assert await snap() == [{30, 10}, {31}, set()]
    r = _post(f"/{nude}/add", {"media_ids": [10]})
    assert r.status_code == 200, r.text
    assert await snap() == [{30}, {31, 10}, set()], "filing is exclusive within the category"
    r = _post(f"/{nude}/add", {"media_ids": [30], "move_from": tease})
    assert r.status_code == 200 and r.json()["moved"] == 1, r.text
    assert await snap() == [set(), {31, 10, 30}, set()], "a rung->rung move"
    # Rung -> plain folder, plain folder -> rung.
    p1 = await _mk("p1")
    r = _post(f"/{p1}/add", {"media_ids": [10], "move_from": nude})
    assert r.status_code == 200 and r.json()["moved"] == 1, r.text
    assert await snap() == [set(), {31, 30}, set()] and set(await _members(p1)) == {10}
    r = _post(f"/{body}/add", {"media_ids": [10], "move_from": p1})
    assert r.status_code == 200, r.text
    assert await snap() == [set(), {31, 30}, {10}] and await _members(p1) == {}
    # A refused move into a rung leaves the source as it was.
    p2 = await _mk("p2", items=(50,))
    _err(_post(f"/{nude}/add", {"media_ids": [50], "move_from": p2}), 400, "feet_photos_only")
    assert set(await _members(p2)) == {50} and await snap() == [set(), {31, 30}, {10}]
    # Remove from a rung (the picker's reject).
    r = _post(f"/{nude}/remove", {"media_ids": [30, 12]})
    assert r.status_code == 200 and r.json()["removed"] == 1, r.text
    assert await snap() == [set(), {31}, {10}]
    # Re-adding a member keeps its place in the rung (the picker would re-file it and drop the order).
    assert _post(f"/{nude}/reorder", {"media_ids": [31], "before": None}).status_code == 200
    placed = await _members(nude)
    r = _post(f"/{nude}/add", {"media_ids": [31]})
    assert r.status_code == 200 and (r.json()["added"], r.json()["already"]) == (0, 1), r.text
    assert await _members(nude) == placed == {31: 0}
    # A rung keeps its name and stays.
    _err(_post(f"/{nude}/rename", {"name": "toes"}), 400, "pack_rung_fixed")
    _err(_delete(nude), 400, "pack_rung_fixed")
    f = await _row(nude)
    assert (f.name, f.deleted_at) == ("feet-nude", None)
    assert await snap() == [set(), {31}, {10}]


async def _gather(*fids: int) -> list[set[int]]:
    return [set(await _members(f)) for f in fids]


async def case_remove():
    f = await _mk("rm1", items=(1, 2, 3))
    r = _post(f"/{f}/remove", {"media_ids": [2, 4, 900]})
    assert r.status_code == 200 and r.json() == {"account_id": AID, "folder_id": f, "removed": 1,
                                                 "adopted": []}, r.text
    assert set(await _members(f)) == {1, 3}
    async with get_session() as s:
        it = await s.get(VaultItem, (AID, 2))
        assert it is not None and it.removed_at is None, "the media stay in the vault"
    _err(_post(f"/{f}/remove", {"media_ids": ["2"]}), 400, "invalid_media_ids")
    gone = await _mk("rm-gone", items=(1,), deleted=True)
    _err(_post(f"/{gone}/remove", {"media_ids": [1]}), 404, "folder_not_found")
    assert set(await _members(gone)) == {1}
    ai = await _mk("AI-rm2", by=SCRIPT, items=((1, 0), (2, 1)))
    r = _post(f"/{ai}/remove", {"media_ids": [3]})
    assert r.json() == {"account_id": AID, "folder_id": ai, "removed": 0, "adopted": []}, r.text
    assert (await _row(ai)).created_by == SCRIPT, "a no-op remove does not adopt"
    r = _post(f"/{ai}/remove", {"media_ids": [2]})
    assert r.json()["adopted"] == [ai] and (await _row(ai)).created_by == "operator", r.text
    assert await _members(ai) == {1: 0}


async def case_reorder():
    # Listing order: 0,1,2 first, then NULL newest first (4 newer than 5; removed 40 is not listed), then -2, -1.
    f = await _mk("ro", items=((1, 0), (2, 1), (3, 2), (4, None), (5, None), (40, None), (7, -2), (6, -1)))
    assert _listing(f) == [1, 2, 3, 4, 5, 7, 6]

    async def check(want: list[int]):
        got = await _members(f)
        assert sorted(got.values()) == list(range(len(got))), got
        order = _by_order(got)
        assert [m for m in order if m != 40] == want, (order, want)
        assert _listing(f) == want, "the reorder agrees with the listing"

    r = _post(f"/{f}/reorder", {"media_ids": [6], "before": 2})
    assert r.status_code == 200 and r.json() == {"account_id": AID, "folder_id": f, "items": 8,
                                                 "adopted": []}, r.text
    await check([1, 6, 2, 3, 4, 5, 7])
    assert _post(f"/{f}/reorder", {"media_ids": [1], "before": None}).status_code == 200
    await check([6, 2, 3, 4, 5, 7, 1])
    assert _post(f"/{f}/reorder", {"media_ids": [1]}).status_code == 200, "no before: the end"
    await check([6, 2, 3, 4, 5, 7, 1])
    assert _post(f"/{f}/reorder", {"media_ids": [5, 3], "before": 6}).status_code == 200
    await check([5, 3, 6, 2, 4, 7, 1])
    assert _post(f"/{f}/reorder", {"media_ids": [999, 4], "before": 5}).status_code == 200, "non-members ignored"
    await check([4, 5, 3, 6, 2, 7, 1])
    snap = await _members(f)
    for body in ({"media_ids": [4], "before": 900}, {"media_ids": [4], "before": 4},
                 {"media_ids": [4, 5], "before": 5}, {"media_ids": [4], "before": "5"},
                 {"media_ids": [4], "before": True}):
        _err(_post(f"/{f}/reorder", body), 400, "bad_before")
    _err(_post(f"/{f}/reorder", {"media_ids": []}), 400, "media_ids_required")
    assert await _members(f) == snap, "a refused reorder writes nothing"
    # An AI folder: adopted only when the visible order changes (renumbering alone is no edit).
    ai = await _mk("AI-ro2", by=SCRIPT, items=((1, 0), (2, 1), (3, -1)))
    r = _post(f"/{ai}/reorder", {"media_ids": [3], "before": None})
    assert r.status_code == 200 and r.json()["adopted"] == [], r.text
    assert (await _row(ai)).created_by == SCRIPT, "a reorder that changes nothing does not adopt"
    assert _listing(ai) == [1, 2, 3]
    r = _post(f"/{ai}/reorder", {"media_ids": [2], "before": 1})
    assert r.json()["adopted"] == [ai] and (await _row(ai)).created_by == "operator", r.text
    assert _listing(ai) == [2, 1, 3] and await _members(ai) == {2: 0, 1: 1, 3: 2}


async def case_delete():
    d1 = await _mk("d1", items=(1, 2), of_list_id=555)
    async with get_session() as s:
        s.add_all([VaultFolderPrice(account_id=AID, folder_ref=f"vf:{d1}", price_cents=2500),
                   VaultFolderPrice(account_id=AID, folder_ref="of:555", price_cents=3000)])
        await s.commit()
    r = _delete(d1)
    assert r.status_code == 200 and r.json() == {"account_id": AID, "folder_id": d1, "deleted": True,
                                                 "of_list_id": 555}, r.text
    assert (await _row(d1)).deleted_at is not None
    assert set(await _members(d1)) == {1, 2}, "membership rows stay"
    async with get_session() as s:
        assert await s.get(VaultItem, (AID, 1)) is not None and await s.get(VaultItem, (AID, 2)) is not None
        prices = {ref: c for ref, c in (await s.execute(select(VaultFolderPrice.folder_ref, VaultFolderPrice.price_cents)
                                                       .where(VaultFolderPrice.account_id == AID))).all()}
    assert prices == {"of:555": 3000}, prices
    assert d1 not in {f["id"] for f in _list().json()["list"]}
    _err(_delete(d1), 404, "folder_not_found")
    theirs = await _mk("d-theirs", aid=OTHER)
    _err(_delete(theirs), 404, "folder_not_found")
    assert (await _row(theirs)).deleted_at is None


async def case_rebuild_spares_edited_ai():
    x = await _mk("AI-x", by=SCRIPT, items=((1, 0), (2, 1), (3, 2)), aid=BID)
    y = await _mk("AI-y", by=SCRIPT, items=((4, 0),), aid=BID)
    r = _post(f"/{x}/remove", {"media_ids": [3]}, aid=BID)
    assert r.status_code == 200 and r.json()["adopted"] == [x], r.text
    out = await vault_scripts.apply_ai_folders(BID, {"folders": [
        {"name": "x", "items": [{"media_id": 5, "manual_order": 0}], "source": "script"},
        {"name": "y", "items": [{"media_id": 6, "manual_order": 0}], "source": "script"}]})
    f = await _row(x)
    assert (f.deleted_at, f.created_by, f.name) == (None, "operator", "AI-x"), "the edited folder survives"
    assert await _members(x, BID) == {1: 0, 2: 1}, "its membership is the operator's"
    async with get_session() as s:
        fresh = (await s.execute(select(VaultFolder.id).where(
            VaultFolder.account_id == BID, VaultFolder.name == "AI-x", VaultFolder.created_by == SCRIPT,
            VaultFolder.deleted_at.is_(None)))).scalars().all()
    assert len(fresh) == 1 and fresh[0] != x, fresh
    assert await _members(fresh[0], BID) == {5: 0}
    # Control: the unedited generated folder IS rewritten in place.
    assert (await _row(y)).deleted_at is None and await _members(y, BID) == {6: 0}
    assert {c["name"]: c["reused"] for c in out["created"]} == {"AI-x": False, "AI-y": True}, out
    kinds = sorted((f["name"], f["kind"]) for f in _list(aid=BID).json()["list"])
    assert kinds == [("AI-x", "ai"), ("AI-x", "own"), ("AI-y", "ai")], kinds


async def case_scope():
    f = await _mk("sc", items=(1, 2), by=SCRIPT)
    rows_before, folders_before = await _item_rows(), await _folder_count()
    writes = (("post", "", {"name": "nope"}), ("post", f"/{f}/rename", {"name": "nope"}),
              ("post", f"/{f}/add", {"media_ids": [3]}), ("post", f"/{f}/remove", {"media_ids": [1]}),
              ("post", f"/{f}/reorder", {"media_ids": [2], "before": 1}), ("delete", f, None))
    assert _list(who="owner2").status_code == 403
    for who in ("owner2", "chatter"):
        for kind, path, body in writes:
            r = _delete(path, who=who) if kind == "delete" else _post(path, body, who=who)
            assert r.status_code == 403, (who, path, r.status_code, r.text)
            if who == "chatter":
                assert r.json()["detail"]["error"] == "folder_not_allowed", (path, r.text)
    r = _list(who="chatter")
    assert r.status_code == 200 and r.json() == {"list": []}, r.text
    assert (await _item_rows(), await _folder_count()) == (rows_before, folders_before)
    g = await _row(f)
    assert (g.name, g.created_by, g.deleted_at) == ("sc", SCRIPT, None)
    assert await _members(f) == {1: None, 2: None}


def case_pure_tables():
    for name, by, want in (("AI-beach", SCRIPT, "ai"), ("AI-beach", "operator", "own"), ("beach", SCRIPT, "own"),
                           ("feet-tease", "operator", "pack"), ("feet-nude-body", SCRIPT, "pack"),
                           ("Feet-Nude", "operator", "own"), ("ai-beach", SCRIPT, "own")):
        assert vif.folder_kind(name, by) == want, (name, by)
    for name, want in (("feet-tease", True), ("Feet-Tease", True), (" feet-nude ", True), ("FEET-NUDE-BODY", True),
                       ("feet", False), ("feet-tease2", False), ("beach", False), ("", False)):
        assert vif.reserved_name(name) == want, name
    pb = vif.place_before
    for order, moved, before, want in (
            ([1, 2, 3, 4], [4], 1, [4, 1, 2, 3]),
            ([1, 2, 3, 4], [1], None, [2, 3, 4, 1]),
            ([1, 2, 3, 4], [4, 2], 1, [4, 2, 1, 3]),
            ([1, 2, 3, 4], [2, 2, 9], 4, [1, 3, 2, 4]),        # dupes once, non-members ignored
            ([1, 2, 3], [9], None, [1, 2, 3]),
            ([1, 2, 3], [], 2, [1, 2, 3])):
        assert pb(order, moved, before) == want, (order, moved, before)
    for order, moved, before in (([1, 2], [1], 9), ([1, 2], [1], 1), ([1, 2, 3], [1, 2], 2)):
        try:
            pb(order, moved, before)
        except ValueError as e:
            assert str(e) == "bad_before"
        else:
            raise AssertionError(("bad_before expected", order, moved, before))
    key = vif.listing_sort_key
    new, old = T0, T0 - timedelta(hours=1)
    rows = [(7, -1, new), (8, -2, new), (5, None, old), (4, None, new), (9, None, None), (3, 2, old), (2, 0, old),
            (1, 1, new), (6, None, new)]
    got = [m for m, _, _ in sorted(rows, key=lambda r: key(*r))]
    # 0,1,2 / NULL newest first (tie at `new`: higher id first), no date last / -2, -1.
    assert got == [2, 1, 3, 6, 4, 5, 9, 8, 7], got


_harness.run()
