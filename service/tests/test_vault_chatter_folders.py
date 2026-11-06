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
  /admin/vault-ai/pack-candidates|disputes|flags-review|flags-accuracy,
  /admin/vault/media-stats    the review routes + the picker's stats: chatter lists
                              and counts folder 12's items only; owner unchanged
  /admin/vault-ai/disputes/resolve|flags-review/grade|pack-triage
                              chatter 404 outside its folders / no mirror row;
                              owner unchanged (200, 400 not_in_mirror for 999)

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
import vault_ai_vision  # noqa: E402
import vault_stills  # noqa: E402
from _pre_enforcement import seed_pre_enforcement_install  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, Chatter, ChatterFolderAccess, ChatterUser, User, UserAccount, VaultItem,
    VaultOfQueryLog, VaultSend,
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
    each other (fully_nude + a garment: a dispute, listed by flags-review too),
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


def _item(mid: int, folders: list[int], *, graded: bool = False) -> VaultItem:
    raw = {"id": mid, "type": "photo",
           "listStates": [{"id": f, "type": "custom", "hasMedia": True, "name": f"f{f}"}
                          for f in folders]}
    return VaultItem(account_id=AID, media_id=mid, kind="photo", raw_json=json.dumps(raw),
                     of_folder_ids=json.dumps(folders), created_at=datetime(2026, 1, mid - 100),
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
    """pack-candidates, disputes, flags-review, flags-accuracy, media-stats: the
    owner sees every item, the chatter only folder 12's (101), counts included."""
    owner, chatter = _login("/auth/login", "ownerv"), _login("/chatter/login", "cf")
    a = f"account_id={AID}"
    for path, key in ((f"/admin/vault-ai/pack-candidates?{a}&category=feet", "candidates"),
                      (f"/admin/vault-ai/disputes?{a}", "disputes"),
                      (f"/admin/vault-ai/flags-review?{a}", "items")):
        assert _mids(owner.get(path), key) == [101, 102, 103], path
        assert _mids(chatter.get(path), key) == [101], path
    for path, keys, want in (
        (f"/admin/vault-ai/disputes?{a}", ("checked", "count"), ((3, 3), (1, 1))),
        (f"/admin/vault-ai/flags-review?{a}", ("total", "graded", "iffy"), ((3, 2, 3), (1, 1, 1))),
        (f"/admin/vault-ai/flags-accuracy?{a}", ("graded_items", "answers"), ((2, 6), (1, 3))),
    ):
        o, c = owner.get(path).json(), chatter.get(path).json()
        assert (tuple(o[k] for k in keys), tuple(c[k] for k in keys)) == want, (path, o, c)
    o, c = owner.get(f"/admin/vault/media-stats?{a}").json(), chatter.get(f"/admin/vault/media-stats?{a}").json()
    assert sorted(o["by_media"]) == ["101", "102", "103", "999"], o
    assert sorted(c["by_media"]) == ["101"] and c["by_media"]["101"]["unlocks"] == 1, c


def case_review_writes_404_outside_folders():
    """disputes/resolve, flags-review/grade, pack-triage: the chatter may write
    only folder 12's media; outside (102), unfiled (103), unknown (999) and a
    verdict list naming one of them 404 as a still does. The owner is unchanged:
    200, and 400 not_in_mirror for 999 (triage never looks the media up)."""
    owner, chatter = _login("/auth/login", "ownerv"), _login("/chatter/login", "cf")

    def triage(*mids):
        return {"account_id": AID, "category": "feet",
                "verdicts": [{"media_id": m, "rung": "tease"} for m in mids]}

    posts = (
        ("/admin/vault-ai/disputes/resolve",
         lambda m: {"account_id": AID, "media_id": m, "values": {"vulva_vis": "bare"}}, 400),
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


_harness.run()
