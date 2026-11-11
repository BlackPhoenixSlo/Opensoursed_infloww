#!/usr/bin/env python3
"""Chatter folder limits on the vault MIRROR paths (not just /api/of/v2/vault/*).

Real HTTP with real owner / chatter logins. Owner A owns accV; chatter `cf`
is linked to A and restricted to OF folder 12 on accV. Mirror rows:
  101 in folder 12, 102 in folder 123 (the LIKE trap: '%12%' matched it),
  103 in no folder; all three have a thumb on disk.

  /admin/vault-ai/items       All → soft deny; folder 12 → only 101 (exact match);
                              folder 123 → empty; owner unchanged
  /admin/vault-ai/of-folders  chatter sees folder 12 only
  /admin/vault-ai/cache/summary  chatter count = allowed folders only
  /admin/vault-ai/thumb|image|poster  chatter 404 outside its folders (even on a
                              disk hit) and for media with no mirror row
  /admin/vault-ai/pack-candidates|flags-review|flags-accuracy,
  /admin/vault/media-stats    the review routes + the picker's stats: chatter lists
                              and counts folder 12's items only; owner unchanged
  /admin/vault-ai/flags-review/grade|pack-triage
                              chatter 404 outside its folders / no mirror row;
                              owner unchanged (200, 400 not_in_mirror for 999)
  pack-candidates shelf       chatter's rung counts are of folder 12's media only
  /api/of/v2/vault/media/{id}, PATCH items/{id}, items/{id}/hide, reorder
                              chatter 404 outside its folders / no mirror row,
                              before any cache read or OF call
  collect/status, cache/summary last_run, harvest-keywords/status
                              chatter gets no whole-vault totals / hit count
  /admin/vault-ai/sync        chatter 403 outside its folders; on All only the cache
                              drop (200, seen/new null, no OF walk)

Run: ./venv/bin/python service/tests/test_vault_chatter_folders.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB
_harness.bootstrap()

import json  # noqa: E402
import tempfile  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import accounts as account_registry  # noqa: E402
import vault_ai_api  # noqa: E402
import vault_ai_vision  # noqa: E402
import vault_cache  # noqa: E402
import vault_ingest  # noqa: E402
import vault_stills  # noqa: E402
from _pre_enforcement import seed_pre_enforcement_install  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, Chatter, ChatterFolderAccess, ChatterUser, User, UserAccount, VaultCacheRun,
    VaultItem, VaultOfQueryLog, VaultSend,
)

client_factory = _harness.make_client
AID = "accV"
_orig_get_account = account_registry.get_account
account_registry.get_account = (
    lambda a: {"id": a, "nickname": a} if a == AID else _orig_get_account(a))
vault_stills.THUMB_DIR = Path(tempfile.mkdtemp(prefix="vcf_thumbs_"))
_JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64


def _review_fields(graded: bool) -> dict:
    """The review routes' seed: both passes answered (flags_known), contradicting
    each other (fully_nude + a garment: listed by flags-review as passes_disagree),
    tagged "feet" (a pack candidate), graded at the current prompt when asked
    (flags-accuracy counts it)."""
    fields = {"description": "lying on her back", "explicitness": "explicit",
              "clothing_state": "fully_nude", "underwear_visible": True,
              "vulva_vis": "covered", "breasts_vis": "bare", "anus_vis": "not_in_frame",
              "over_vulva": "black lace thong", "tags": ["feet"]}
    if graded:
        fields["_graded"] = {"v": vault_ai_vision._FLAGS_VERSION, "corrected": [],
                             "confirmed": {"vulva_vis": "covered", "breasts_vis": "bare",
                                           "anus_vis": "not_in_frame"}}
    return fields


def _item(mid: int, folders: list[int], *, graded: bool = False,
          created_at: datetime | None = None) -> VaultItem:
    raw = {"id": mid, "type": "photo",
           "listStates": [{"id": f, "type": "custom", "hasMedia": True, "name": f"f{f}"}
                          for f in folders]}
    return VaultItem(account_id=AID, media_id=mid, kind="photo", raw_json=json.dumps(raw),
                     of_folder_ids=json.dumps(folders),
                     created_at=created_at or datetime(2026, 1, mid - 100),
                     search_text="photo", tags="[]", of_terms='["bikini"]',
                     ai_fields_json=json.dumps(_review_fields(graded)))


async def case_seed():
    uid = uuid.uuid4().hex
    cid = uuid.uuid4().hex
    async with get_session() as s:
        s.add(User(id=uid, username="ownerv", password="secretpw"))
        s.add(Account(id=AID, nickname="V"))
    async with get_session() as s:
        s.add(UserAccount(user_id=uid, account_id=AID))
        s.add(Chatter(id=cid, username="cf", password="secretpw", display_name="Cf",
                      created_at=datetime.utcnow(), last_seen_at=datetime.utcnow()))
    async with get_session() as s:
        s.add(ChatterUser(chatter_id=cid, user_id=uid, created_at=datetime.utcnow()))
        s.add(ChatterFolderAccess(chatter_id=cid, account_id=AID, folder_id=12,
                                  folder_name="f12", created_at=datetime.utcnow()))
        for mid, folders in ((101, [12]), (102, [123]), (103, [])):
            s.add(_item(mid, folders, graded=mid != 103))
        # One 1:1 priced send per media, 999 = a media the mirror has no row for.
        for mid in (101, 102, 103, 999):
            s.add(VaultSend(account_id=AID, fan_id=7, media_id=mid, message_id=mid * 10,
                            price_cents=500, was_purchased=True, sent_at=datetime(2026, 2, 1)))
        # OF search already harvested (fresh log row): search-of answers from the mirror.
        s.add(VaultOfQueryLog(account_id=AID, query="bikini", match_count=3,
                              fetched_at=datetime.utcnow()))
    await seed_pre_enforcement_install()
    for mid in (101, 102, 103):
        vault_stills.write(vault_stills.thumb_path(AID, mid), _JPEG)


def _login(path: str, user: str):
    c = client_factory()
    r = c.post(path, json={"username": user, "password": "secretpw"})
    assert r.status_code == 200, (path, r.status_code, r.text)
    return c


def _ids(r) -> list[int]:
    assert r.status_code == 200, (r.status_code, r.text)
    return [m["id"] for m in r.json()["list"]]


def case_items_gate_and_exact_folder_match():
    owner, chatter = _login("/auth/login", "ownerv"), _login("/chatter/login", "cf")
    q = f"/admin/vault-ai/items?account_id={AID}"
    assert _ids(owner.get(q)) == [103, 102, 101]
    assert _ids(owner.get(q + "&of_folder_id=12")) == [101], "LIKE '%12%' matched folder 123"
    assert _ids(owner.get(q + "&of_folder_id=123")) == [102]
    r = chatter.get(q)
    assert r.json() == {"list": [], "hasMore": False, "source": "mirror"}, r.json()
    assert _ids(chatter.get(q + "&of_folder_id=12")) == [101]
    assert _ids(chatter.get(q + "&of_folder_id=123")) == []
    assert _ids(chatter.get(q + "&internal_folder_id=1")) == []


def case_of_folders_filtered():
    owner, chatter = _login("/auth/login", "ownerv"), _login("/chatter/login", "cf")
    q = f"/admin/vault-ai/of-folders?account_id={AID}"
    assert sorted(_ids(owner.get(q))) == [12, 123]
    assert _ids(chatter.get(q)) == [12]


def case_folder_actions_refuse_outside_chatter_scope():
    owner, chatter = _login("/auth/login", "ownerv"), _login("/chatter/login", "cf")
    assert chatter.get(f"/admin/vault-ai/folder-plan?account_id={AID}").status_code == 403
    assert chatter.post("/admin/vault-ai/folder-plan/apply",
                        json={"account_id": AID, "confirm": True}).status_code == 403
    assert chatter.post("/admin/vault-ai/of-folders",
                        json={"account_id": AID, "name": "x", "media_ids": [101]}).status_code == 403
    for path in ("add", "remove", "rename"):
        r = chatter.post(f"/admin/vault-ai/of-folders/123/{path}",
                         json={"account_id": AID, "media_ids": [101], "name": "x"})
        assert r.status_code == 403, (path, r.status_code, r.text)
    assert chatter.delete(f"/admin/vault-ai/of-folders/123?account_id={AID}").status_code == 403
    assert chatter.post("/admin/vault-ai/of-folders/sort", json={"account_id": AID}).status_code == 403
    assert chatter.post("/admin/vault-ai/of-folders/12/add",
                        json={"account_id": AID, "media_ids": [102]}).status_code == 404
    assert chatter.post("/admin/vault-ai/duplicates/hide",
                        json={"account_id": AID, "media_ids": [102]}).status_code == 404
    assert owner.get(f"/admin/vault-ai/folder-plan?account_id={AID}").status_code == 200


def case_duplicate_list_hides_foreign_folder_media():
    import vault_dupes
    from sqlalchemy import select, update
    owner, chatter = _login("/auth/login", "ownerv"), _login("/chatter/login", "cf")
    async def seed():
        async with get_session() as s:
            originals = {item.media_id: (item.content_hash, item.content_hash_kind)
                         for item in (await s.execute(select(VaultItem).where(
                             VaultItem.account_id == AID,
                             VaultItem.media_id.in_([101, 102])))).scalars()}
            s.add(_item(104, [12]))
            for mid in (101, 102, 104):
                await s.execute(update(VaultItem).where(VaultItem.account_id == AID,
                    VaultItem.media_id == mid).values(
                    content_hash=vault_dupes.pack_hash("same", 0, 0),
                    content_hash_kind=vault_dupes.HASH_KIND))
            return originals
    import asyncio
    originals = asyncio.run(seed())
    try:
        own = owner.get(f"/admin/vault-ai/duplicates?account_id={AID}")
        restricted = chatter.get(f"/admin/vault-ai/duplicates?account_id={AID}")
        assert own.status_code == 200 and own.json()["sets"] == 1, own.text
        assert own.json()["scanned"] == 3 and own.json()["unhashed"] == 1
        assert own.json()["removable"] == 2
        assert restricted.status_code == 200, restricted.text
        got = restricted.json()
        assert got["sets"] == got["removable"] == got["returned"] == 1, got
        assert got["scanned"] == 2 and got["unhashed"] == 0, got
        assert got["clusters"][0]["original"]["media_id"] == 101
        assert [d["media_id"] for d in got["clusters"][0]["dupes"]] == [104]
    finally:
        async def cleanup():
            from sqlalchemy import delete
            async with get_session() as s:
                await s.execute(delete(VaultItem).where(VaultItem.account_id == AID,
                    VaultItem.media_id == 104))
                for mid, (content_hash, content_hash_kind) in originals.items():
                    await s.execute(update(VaultItem).where(VaultItem.account_id == AID,
                        VaultItem.media_id == mid).values(
                        content_hash=content_hash, content_hash_kind=content_hash_kind))
        asyncio.run(cleanup())


def case_duplicate_hide_uses_chatter_folder_scope():
    """A~B~C is not transitive: hiding C must use the visible B/C pair."""
    import asyncio
    import automation_executor as ax
    import vault_dupes

    owner, chatter = _login("/auth/login", "ownerv"), _login("/chatter/login", "cf")
    original_make_client = ax._make_client
    async def seed():
        async with get_session() as s:
            for mid, day, folder, bits in ((201, 1, 123, 3 << 60),
                                            (202, 2, 12, (3 << 60) | 1),
                                            (203, 3, 12, (3 << 60) | 3)):
                item = _item(mid, [folder], created_at=datetime(2025, 1, day))
                item.content_hash = vault_dupes.pack_hash(f"chain-{mid}", bits, bits)
                item.content_hash_kind = vault_dupes.HASH_KIND
                s.add(item)
    asyncio.run(seed())
    try:
        def pair(response):
            assert response.status_code == 200, response.text
            return next(c for c in response.json()["clusters"]
                        if c["original"]["media_id"] in (201, 202))

        q = f"/admin/vault-ai/duplicates?account_id={AID}&threshold=1"
        own, restricted = pair(owner.get(q)), pair(chatter.get(q))
        assert own["original"]["media_id"] == 201
        assert [d["media_id"] for d in own["dupes"]] == [202], own
        assert restricted["original"]["media_id"] == 202
        assert [d["media_id"] for d in restricted["dupes"]] == [203], restricted

        class FakeOF:
            def __init__(self):
                self.hidden = []

            def hide_vault_media(self, media_ids):
                self.hidden.append(list(media_ids))
                return {"success": True}

        fake = FakeOF()
        ax._make_client = lambda *_a, **_k: fake
        body = {"account_id": AID, "threshold": 1}
        owner_c = owner.post("/admin/vault-ai/duplicates/hide",
                             json={**body, "media_ids": [203]})
        assert owner_c.status_code == 200, owner_c.text
        assert owner_c.json()["hidden"] == 0
        assert owner_c.json()["refused"] == {"not_a_duplicate": [203]}
        assert fake.hidden == []

        chatter_b = chatter.post("/admin/vault-ai/duplicates/hide",
                                 json={**body, "media_ids": [202]})
        assert chatter_b.status_code == 200, chatter_b.text
        assert chatter_b.json()["hidden"] == 0
        assert chatter_b.json()["refused"] == {"is_original": [202]}
        assert fake.hidden == []

        chatter_c = chatter.post("/admin/vault-ai/duplicates/hide",
                                 json={**body, "media_ids": [203]})
        assert chatter_c.status_code == 200, chatter_c.text
        assert chatter_c.json()["hidden_ids"] == [203], chatter_c.json()
        assert chatter_c.json()["refused"] == {}, chatter_c.json()
        assert fake.hidden == [[203]]

        owner_b = owner.post("/admin/vault-ai/duplicates/hide",
                             json={**body, "media_ids": [202]})
        assert owner_b.status_code == 200, owner_b.text
        assert owner_b.json()["hidden_ids"] == [202], owner_b.json()
        assert fake.hidden == [[203], [202]], fake.hidden
    finally:
        ax._make_client = original_make_client
        async def cleanup():
            from sqlalchemy import delete
            async with get_session() as s:
                await s.execute(delete(VaultItem).where(VaultItem.account_id == AID,
                    VaultItem.media_id.in_([201, 202, 203])))
        asyncio.run(cleanup())


def case_vision_routes_stay_in_chatter_folders():
    owner, chatter = _login("/auth/login", "ownerv"), _login("/chatter/login", "cf")
    for route, body in (("describe", {"media_id": 102}),
                        ("flags-all", {"media_ids": [102]})):
        r = chatter.post(f"/admin/vault-ai/{route}", json={"account_id": AID, **body})
        assert r.status_code == 404, (route, r.status_code, r.text)
    for route in ("describe-all/plan", "flags-all/status", "describe-all/status"):
        r = chatter.get(f"/admin/vault-ai/{route}?account_id={AID}")
        assert r.status_code == 403 and r.json()["detail"] == {"error": "folder_not_allowed"}, (route, r.status_code, r.text)
    for route, body in (("flags-all", {}), ("describe-all", {})):
        r = chatter.post(f"/admin/vault-ai/{route}", json={"account_id": AID, **body})
        assert r.status_code == 403 and r.json()["detail"] == {"error": "folder_not_allowed"}, (route, r.status_code, r.text)
    assert owner.get(f"/admin/vault-ai/describe-all/plan?account_id={AID}").status_code == 200
    for route in ("flags-all/status", "describe-all/status"):
        assert owner.get(f"/admin/vault-ai/{route}?account_id={AID}").status_code == 200


def case_summary_counts_allowed_only():
    owner, chatter = _login("/auth/login", "ownerv"), _login("/chatter/login", "cf")
    q = f"/admin/vault-ai/cache/summary?account_id={AID}"
    o, c = owner.get(q).json(), chatter.get(q).json()
    assert (o["count"], c["count"]) == (3, 1), (o, c)
    assert o["complete"] is False and c["complete"] is False


def case_stills_404_outside_folders():
    owner, chatter = _login("/auth/login", "ownerv"), _login("/chatter/login", "cf")
    for mid, want_chatter in ((101, 200), (102, 404), (103, 404), (999, 404)):
        r = chatter.get(f"/admin/vault-ai/thumb?account_id={AID}&media_id={mid}")
        assert r.status_code == want_chatter, (mid, r.status_code, r.text[:80])
    for mid in (101, 102, 103):
        r = owner.get(f"/admin/vault-ai/thumb?account_id={AID}&media_id={mid}")
        assert r.status_code == 200, ("owner", mid, r.status_code)
        assert r.headers.get("cache-control") == "private, max-age=604800", r.headers.get("cache-control")
    for route in ("image", "poster"):
        r = chatter.get(f"/admin/vault-ai/{route}?account_id={AID}&media_id=102")
        assert r.status_code == 404, (route, r.status_code)


def case_search_of_filtered_for_chatter():
    owner, chatter = _login("/auth/login", "ownerv"), _login("/chatter/login", "cf")
    body = {"account_id": AID, "query": "bikini"}
    o, c = owner.post("/admin/vault-ai/search-of", json=body), chatter.post("/admin/vault-ai/search-of", json=body)
    assert o.status_code == 200 and sorted(o.json()["ids"]) == [101, 102, 103], o.text
    assert c.status_code == 200 and c.json()["ids"] == [101] and c.json()["count"] == 1, c.text


def _mids(r, key: str) -> list[int]:
    assert r.status_code == 200, (r.status_code, r.text[:200])
    return sorted(int(x["media_id"]) for x in r.json()[key])


def case_review_lists_scoped_to_folders():
    """pack-candidates, flags-review, flags-accuracy, media-stats: the owner
    sees every item, the chatter only folder 12's (101), counts included. The
    retired disputes routes are gone for both."""
    owner, chatter = _login("/auth/login", "ownerv"), _login("/chatter/login", "cf")
    a = f"account_id={AID}"
    for path, key in ((f"/admin/vault-ai/pack-candidates?{a}&category=feet", "candidates"),
                      (f"/admin/vault-ai/flags-review?{a}", "items")):
        assert _mids(owner.get(path), key) == [101, 102, 103], path
        assert _mids(chatter.get(path), key) == [101], path
    for path, keys, want in (
        (f"/admin/vault-ai/flags-review?{a}", ("total", "graded", "iffy"), ((3, 2, 3), (1, 1, 1))),
        (f"/admin/vault-ai/flags-accuracy?{a}", ("graded_items", "answers"), ((2, 6), (1, 3))),
    ):
        o, c = owner.get(path).json(), chatter.get(path).json()
        assert (tuple(o[k] for k in keys), tuple(c[k] for k in keys)) == want, (path, o, c)
    for gone in (owner.get(f"/admin/vault-ai/disputes?{a}"),
                 owner.post("/admin/vault-ai/disputes/resolve",
                            json={"account_id": AID, "media_id": 101, "values": {}})):
        assert gone.status_code in (404, 405), (gone.status_code, gone.text[:120])
    o, c = owner.get(f"/admin/vault/media-stats?{a}").json(), chatter.get(f"/admin/vault/media-stats?{a}").json()
    assert sorted(o["by_media"]) == ["101", "102", "103", "999"], o
    assert sorted(c["by_media"]) == ["101"] and c["by_media"]["101"]["unlocks"] == 1, c


def case_review_writes_404_outside_folders():
    """flags-review/grade, pack-triage: the chatter may write
    only folder 12's media; outside (102), unfiled (103), unknown (999) and a
    verdict list naming one of them 404 as a still does. The owner is unchanged:
    200, and 400 not_in_mirror for 999 (triage never looks the media up)."""
    owner, chatter = _login("/auth/login", "ownerv"), _login("/chatter/login", "cf")

    def triage(*mids):
        return {"account_id": AID, "category": "feet",
                "verdicts": [{"media_id": m, "rung": "tease"} for m in mids]}

    posts = (
        ("/admin/vault-ai/flags-review/grade",
         lambda m: {"account_id": AID, "media_id": m, "corrections": {}}, 400),
        ("/admin/vault-ai/pack-triage", triage, 200),
    )
    for path, body, owner_999 in posts:
        for mid, want in ((102, 404), (103, 404), (999, 404), (101, 200)):
            r = chatter.post(path, json=body(mid))
            assert r.status_code == want, ("chatter", path, mid, r.status_code, r.text[:120])
        for mid, want in ((102, 200), (999, owner_999)):
            r = owner.post(path, json=body(mid))
            assert r.status_code == want, ("owner", path, mid, r.status_code, r.text[:120])
    r = chatter.post("/admin/vault-ai/pack-triage", json=triage(101, 102))
    assert r.status_code == 404, ("one outside verdict spoils the list", r.status_code, r.text[:120])


def case_pack_shelf_counts_scoped():
    """After the triage above filed 101 (chatter) and 102 + 999 (owner) on "tease":
    the owner's shelf counts all three, the chatter's only 101."""
    owner, chatter = _login("/auth/login", "ownerv"), _login("/chatter/login", "cf")
    q = f"/admin/vault-ai/pack-candidates?account_id={AID}&category=feet"

    def tease(r):
        assert r.status_code == 200, (r.status_code, r.text[:200])
        return next(x["count"] for x in r.json()["folders"] if x["rung"] == "tease")
    assert (tease(owner.get(q)), tease(chatter.get(q))) == (3, 1)


def case_by_id_edit_hide_reorder_gated():
    owner, chatter = _login("/auth/login", "ownerv"), _login("/chatter/login", "cf")
    h = {"X-Account-Id": AID}
    import asyncio
    for mid in (101, 102):   # cached, so a pass reads no OF
        asyncio.run(vault_cache.put(AID, f"media-by-id:{mid}", {"id": mid}, started_at=datetime.utcnow()))
    for mid, want in ((101, 200), (102, 404), (103, 404), (999, 404)):
        r = chatter.get(f"/api/of/v2/vault/media/{mid}", headers=h)
        assert r.status_code == want, ("by-id", mid, r.status_code, r.text[:120])
    assert owner.get("/api/of/v2/vault/media/102", headers=h).json() == {"id": 102}

    edit = {"account_id": AID, "fields": {"description": "x"}}
    assert chatter.patch("/admin/vault-ai/items/102", json=edit).status_code == 404
    assert chatter.patch("/admin/vault-ai/items/101", json=edit).status_code == 200
    r = chatter.post("/admin/vault-ai/items/102/hide", json={"account_id": AID})
    assert r.status_code == 404, ("hide", r.status_code, r.text[:120])

    def reorder(c, folder, *mids):
        return c.post("/admin/vault-ai/reorder", json={
            "account_id": AID, "folder_id": folder,
            "order": [{"media_id": m, "manual_order": 0} for m in mids]})
    for folder, mids, want in ((12, (101,), 200), (123, (101,), 404), (12, (101, 102), 404),
                               (None, (102,), 404), (None, (101,), 200)):
        r = reorder(chatter, folder, *mids)
        assert r.status_code == want, ("reorder", folder, mids, r.status_code, r.text[:120])
    assert reorder(owner, 123, 102).status_code == 200


async def case_run_totals_owner_only():
    async with get_session() as s:
        s.add(VaultCacheRun(account_id=AID, status="error", phase="media", pages_done=9,
                            total_seen=900, upserted=900, error="boom",
                            started_at=datetime.utcnow(), finished_at=datetime.utcnow()))
    owner, chatter = _login("/auth/login", "ownerv"), _login("/chatter/login", "cf")
    q = f"account_id={AID}"
    vault_ai_api._warm_progress[AID] = {"phase": "images", "warmed": 40, "warm_total": 900}
    try:
        o = owner.get(f"/admin/vault-ai/collect/status?{q}").json()["run"]
        c = chatter.get(f"/admin/vault-ai/collect/status?{q}").json()["run"]
    finally:
        vault_ai_api._warm_progress.pop(AID, None)
    assert (o["total_seen"], o["upserted"], o["pages_done"]) == (900, 900, 9), o
    assert (o["warmed"], o["warm_total"]) == (40, 900), o
    assert (c["total_seen"], c["upserted"], c["pages_done"]) == (None, None, None), c
    assert (c["warmed"], c["warm_total"]) == (None, None), c
    assert (o["error"], c["error"]) == ("boom", None), (o, c)   # a cap's error names the vault's size
    assert c["status"] == o["status"], (c, o)
    o = owner.get(f"/admin/vault-ai/cache/summary?{q}").json()
    c = chatter.get(f"/admin/vault-ai/cache/summary?{q}").json()
    assert (o["last_run"]["total_seen"], c["last_run"]["total_seen"]) == (900, None), (o, c)
    vault_ai_api._kw_progress[AID] = {"total": 30, "done": 4, "matches": 77}
    try:
        o = owner.get(f"/admin/vault-ai/harvest-keywords/status?{q}").json()["progress"]
        c = chatter.get(f"/admin/vault-ai/harvest-keywords/status?{q}").json()["progress"]
    finally:
        vault_ai_api._kw_progress.pop(AID, None)
    assert o == {"total": 30, "done": 4, "matches": 77}, o
    assert c == {"total": 30, "done": 4, "matches": None}, c


def case_sync_needs_an_allowed_folder():
    owner, chatter = _login("/auth/login", "ownerv"), _login("/chatter/login", "cf")
    saved = vault_ingest.has_live_mirror

    async def _no_mirror(_aid):
        return False
    vault_ingest.has_live_mirror = _no_mirror   # stop before any OF walk
    saved_inv, dropped = vault_cache.invalidate, []

    async def _inv(aid):
        dropped.append(aid)
    vault_cache.invalidate = _inv
    try:
        for folder, want in (("&of_folder_id=123", 403), ("&of_folder_id=12", 200)):
            r = chatter.post(f"/admin/vault-ai/sync?account_id={AID}{folder}")
            assert r.status_code == want, ("chatter", folder, r.status_code, r.text[:120])
            if want == 403:
                assert r.json()["detail"] == {"error": "folder_not_allowed"}, r.json()
        # All (where the UI opens): Refresh still drops the cache; no whole-vault walk or counts.
        vault_ingest.has_live_mirror = saved   # a walk would need it: must not get that far
        dropped.clear()
        r = chatter.post(f"/admin/vault-ai/sync?account_id={AID}")
        assert r.status_code == 200, ("chatter All", r.status_code, r.text[:120])
        assert (r.json()["seen"], r.json()["new"]) == (None, None), r.json()
        assert dropped == [AID], dropped
        vault_ingest.has_live_mirror = _no_mirror
        for folder in ("", "&of_folder_id=123"):
            r = owner.post(f"/admin/vault-ai/sync?account_id={AID}{folder}")
            assert r.status_code == 200, ("owner", folder, r.status_code, r.text[:120])
    finally:
        vault_ingest.has_live_mirror = saved
        vault_cache.invalidate = saved_inv
    assert vault_ai_api.vault_ingest is vault_ingest


_harness.run()
