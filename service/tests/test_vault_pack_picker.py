#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import json  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

import accounts as account_registry  # noqa: E402
import automation_executor as ax  # noqa: E402 — patch the OF-client seam
import server  # noqa: E402
import vault_pack_picker  # noqa: E402 — pure helpers under test
import vault_scripts  # noqa: E402 — the reaper predicate under test
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, User, UserAccount, VaultFolder, VaultFolderItem, VaultItem,
)

_TEST_ACCOUNTS = {"acc_owner", "acc_foreign", "acc_rank", "acc_jev"}
_orig_get_account = account_registry.get_account
_orig_list_accounts = account_registry.list_accounts
account_registry.get_account = (
    lambda a: ({"id": a, "nickname": a} if a in _TEST_ACCOUNTS else _orig_get_account(a))
)
account_registry.list_accounts = (
    lambda: [{"id": a, "nickname": a} for a in sorted(_TEST_ACCOUNTS)]
)
account_registry.is_account = lambda aid: aid in _TEST_ACCOUNTS


class _FakeOF:

    def __init__(self):
        self.timeout_s = 5.0
        self.calls: list[tuple] = []
        self.next_list_id = 700
        self.create_fails = False
        self.members: dict[int, list[int]] = {}

    def create_vault_list(self, name: str) -> dict:
        self.calls.append(("create", name))
        if self.create_fails:
            raise RuntimeError(f"OF refused the list {name!r}")
        self.next_list_id += 1
        self.members.setdefault(self.next_list_id, [])
        return {"id": self.next_list_id}

    def add_media_to_vault_list(self, list_id: int, media_ids: list) -> dict:
        self.calls.append(("add", int(list_id), list(media_ids)))
        have = self.members.setdefault(int(list_id), [])
        have.extend(m for m in media_ids if m not in have)
        return {"ok": True}

    def vault_media(self, limit=100, offset=0, type="all", list_id=None, **_kw):  # noqa: A002
        rows = self.members.get(int(list_id), [])[offset:offset + limit]
        return {"list": [{"id": m} for m in rows]}

    def reset(self) -> None:
        self.calls.clear()
        self.create_fails = False
        self.members.clear()


_OF = _FakeOF()
_armed = False


def _client(*_a, **_k):  # noqa: ANN001
    if not _armed:
        raise AssertionError("triage must NEVER construct an OF client")
    return _OF


ax._make_client = _client  # type: ignore[assignment]

_AID = "acc_owner"
_FOREIGN = "acc_foreign"
_OWNER_USER = "pk_owner"
_STRANGER_USER = "pk_stranger"

_RUNGS = ("tease", "nude", "nude-body")
_NAMES = tuple(f"feet-{r}" for r in _RUNGS)



async def _seed_user(username: str) -> str:
    uid = uuid.uuid4().hex
    async with get_session() as s:
        s.add(User(id=uid, username=username, password="secretpw"))
    return uid


async def _seed_account(aid: str, owner_user_id: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid, nickname=aid, color="#aaaaaa"))
        s.add(UserAccount(user_id=owner_user_id, account_id=aid))


async def _seed_item(
    aid: str, media_id: int, *, search_text: str | None = None,
    fields: dict | None = None, kind: str = "photo",
) -> None:
    async with get_session() as s:
        s.add(VaultItem(
            account_id=aid, media_id=media_id, kind=kind,
            created_at=datetime.utcnow(),
            search_text=search_text,
            ai_fields_json=(json.dumps(fields) if fields is not None else None),
            describe_status=("described" if fields is not None else None),
        ))


async def _wipe_folders(aid: str) -> None:
    async with get_session() as s:
        for row in (await s.execute(
            select(VaultFolderItem).where(VaultFolderItem.account_id == aid)
        )).scalars().all():
            await s.delete(row)
        for row in (await s.execute(
            select(VaultFolder).where(VaultFolder.account_id == aid)
        )).scalars().all():
            await s.delete(row)


async def _membership(aid: str) -> dict[str, set[int]]:
    async with get_session() as s:
        folders = {
            f.id: f.name for f in (await s.execute(
                select(VaultFolder).where(
                    VaultFolder.account_id == aid, VaultFolder.deleted_at.is_(None))
            )).scalars().all()
        }
        out: dict[str, set[int]] = {name: set() for name in folders.values()}
        for media_id, folder_id in (await s.execute(
            select(VaultFolderItem.media_id, VaultFolderItem.folder_id)
            .where(VaultFolderItem.account_id == aid)
        )).all():
            name = folders.get(folder_id)
            if name:
                out[name].add(int(media_id))
    return out


async def _folder_id(name: str, aid: str = _AID) -> int:
    async with get_session() as s:
        return (await s.execute(
            select(VaultFolder).where(
                VaultFolder.account_id == aid, VaultFolder.name == name,
                VaultFolder.deleted_at.is_(None))
        )).scalar_one().id


def _login(username: str) -> TestClient:
    c = TestClient(server.app)
    r = c.post("/auth/login", json={"username": username, "password": "secretpw"})
    assert r.status_code == 200, f"login {username!r} failed: {r.status_code} {r.text}"
    return c


def _triage(c: TestClient, verdicts: list[dict], aid: str = _AID, category: str = "feet"):
    return c.post("/admin/vault-ai/pack-triage",
                  json={"account_id": aid, "category": category, "verdicts": verdicts})



async def case_candidates_match_and_carry_rung():
    await _wipe_folders(_AID)
    c = _login(_OWNER_USER)

    r = c.get("/admin/vault-ai/pack-candidates", params={"account_id": _AID, "category": "feet"})
    assert r.status_code == 200, r.text
    body = r.json()
    got = {int(x["media_id"]) for x in body["candidates"]}

    assert 101 in got and 102 in got, f"confident Jev photos must be candidates: {sorted(got)}"
    assert 103 not in got, "a photo Jev has not classified must not be a candidate"
    assert body["rungs"] == list(_RUNGS), body["rungs"]
    assert all(x["rung"] is None for x in body["candidates"]), body["candidates"]

    shelf = body["folders"]
    assert [f["rung"] for f in shelf] == list(_RUNGS), shelf
    assert all(f["folder_id"] is None and f["count"] == 0 for f in shelf), shelf

    assert _triage(c, [{"media_id": 101, "rung": "nude"}]).status_code == 200
    again = c.get("/admin/vault-ai/pack-candidates",
                  params={"account_id": _AID, "category": "feet"}).json()
    by_id = {int(x["media_id"]): x["rung"] for x in again["candidates"]}
    assert by_id[101] == "nude", by_id
    assert by_id[102] is None, by_id
    assert again["filed"] == 1, again["filed"]

    filled = {f["rung"]: f for f in again["folders"]}
    assert filled["nude"]["count"] == 1, filled
    assert filled["nude"]["folder_id"] is not None, filled
    assert filled["nude"]["of_list_id"] is None, "triage must never write to OF"
    assert filled["tease"]["count"] == 0, filled


async def case_triage_creates_all_rungs():
    await _wipe_folders(_AID)
    c = _login(_OWNER_USER)

    res = _triage(c, [{"media_id": 101, "rung": "tease"}])
    assert res.status_code == 200, res.text
    names = {f["name"] for f in res.json()["folders"]}
    assert names == set(_NAMES), f"all three rungs must exist after the first save: {names}"

    async with get_session() as s:
        rows = (await s.execute(
            select(VaultFolder).where(VaultFolder.account_id == _AID)
        )).scalars().all()
    for f in rows:
        assert f.created_by == "operator", f"{f.name}: created_by={f.created_by!r}"
        assert f.of_list_id is None, f"{f.name}: triage must never write to OF"


async def case_verdict_is_exclusive():
    await _wipe_folders(_AID)
    c = _login(_OWNER_USER)

    assert _triage(c, [{"media_id": 101, "rung": "tease"}]).status_code == 200
    assert _triage(c, [{"media_id": 101, "rung": "nude"}]).status_code == 200

    m = await _membership(_AID)
    assert m["feet-nude"] == {101}, m
    assert m["feet-tease"] == set(), f"re-filing must MOVE, not copy: {m}"
    on = [name for name, ids in m.items() if 101 in ids]
    assert on == ["feet-nude"], f"an item may sit on exactly one rung: {on}"


async def case_reject_removes_everywhere():
    await _wipe_folders(_AID)
    c = _login(_OWNER_USER)

    assert _triage(c, [{"media_id": 101, "rung": "nude"}]).status_code == 200
    res = _triage(c, [{"media_id": 101, "rung": None}])
    assert res.status_code == 200, res.text
    assert res.json()["rejected"] == 1, res.json()

    m = await _membership(_AID)
    assert all(101 not in ids for ids in m.values()), f"a reject must clear every rung: {m}"

    body = c.get("/admin/vault-ai/pack-candidates",
                 params={"account_id": _AID, "category": "feet"}).json()
    by_id = {int(x["media_id"]): x["rung"] for x in body["candidates"]}
    assert by_id[101] is None, by_id

    assert _triage(c, [{"media_id": 101, "rung": "nude"}]).status_code == 200
    assert _triage(c, [{"media_id": 101, "rung": "reject"}]).json()["rejected"] == 1
    m2 = await _membership(_AID)
    assert all(101 not in ids for ids in m2.values()), m2


async def case_resave_is_idempotent():
    await _wipe_folders(_AID)
    c = _login(_OWNER_USER)

    verdicts = [{"media_id": 101, "rung": "nude"}, {"media_id": 102, "rung": "tease"}]
    first = _triage(c, verdicts)
    assert first.status_code == 200, first.text
    before = await _membership(_AID)

    second = _triage(c, verdicts)
    assert second.status_code == 200, second.text
    after = await _membership(_AID)
    assert before == after, f"re-saving must be a no-op: {before} != {after}"

    async with get_session() as s:
        rows = (await s.execute(
            select(VaultFolderItem).where(VaultFolderItem.account_id == _AID)
        )).scalars().all()
    assert len(rows) == 2, f"no duplicate membership rows: {len(rows)}"


async def case_unknown_rung_and_category_400():
    c = _login(_OWNER_USER)
    bad_rung = _triage(c, [{"media_id": 101, "rung": "soles"}])
    assert bad_rung.status_code == 400, bad_rung.status_code
    bad_cat = _triage(c, [{"media_id": 101, "rung": "nude"}], category="elbows")
    assert bad_cat.status_code == 400, bad_cat.status_code
    empty = _triage(c, [])
    assert empty.status_code == 400, empty.status_code
    before = await _membership(_AID)
    bad_ids = _triage(c, [{"media_id": 101, "rung": "nude"}, {"media_id": 1.9, "rung": "nude"},
                          {"media_id": True, "rung": "tease"}, {"rung": "nude"}])
    assert bad_ids.status_code == 400, bad_ids.text
    assert bad_ids.json()["detail"] == {"error": "invalid_media_ids", "media_ids": [1.9, True, None]}, bad_ids.text
    assert await _membership(_AID) == before, "a refused triage writes nothing"
    listing = c.get("/admin/vault-ai/pack-candidates",
                    params={"account_id": _AID, "category": "elbows"})
    assert listing.status_code == 400, listing.status_code


async def case_folder_name_survives_the_reaper():
    await _wipe_folders(_AID)
    c = _login(_OWNER_USER)
    assert _triage(c, [{"media_id": 101, "rung": "nude"}]).status_code == 200

    async with get_session() as s:
        rows = (await s.execute(
            select(VaultFolder).where(VaultFolder.account_id == _AID)
        )).scalars().all()
    assert rows, "expected the rung folders"
    for f in rows:
        reapable = (
            f.created_by == "vault_ai_script"
            and f.name.startswith(vault_scripts.AI_FOLDER_PREFIX)
        )
        assert not reapable, f"{f.name!r} (created_by={f.created_by!r}) is reapable"


async def case_owner_auth_403():
    await _wipe_folders(_AID)
    c = _login(_STRANGER_USER)

    listing = c.get("/admin/vault-ai/pack-candidates",
                    params={"account_id": _AID, "category": "feet"})
    saving = _triage(c, [{"media_id": 101, "rung": "nude"}])
    assert listing.status_code == 403, listing.status_code
    assert saving.status_code == 403, saving.status_code

    m = await _membership(_AID)
    assert not any(m.values()), f"a 403 must write nothing: {m}"


async def case_publish_refuses_empty_folder():
    await _wipe_folders(_AID)
    c = _login(_OWNER_USER)
    assert _triage(c, [{"media_id": 101, "rung": "nude"}]).status_code == 200
    empty_id = await _folder_id("feet-tease")

    r = c.post(f"/admin/vault-ai/folders/{empty_id}/publish", json={"account_id": _AID})
    assert r.status_code == 400, f"expected folder_empty, got {r.status_code} {r.text}"
    assert r.json()["detail"]["error"] == "folder_empty", r.text

    missing = c.post("/admin/vault-ai/folders/999999/publish", json={"account_id": _AID})
    assert missing.status_code == 404, missing.status_code

    foreign = c.post(f"/admin/vault-ai/folders/{empty_id}/publish",
                     json={"account_id": _FOREIGN})
    assert foreign.status_code == 403, foreign.status_code


async def case_publish_binds_then_adds_and_reuses_the_list():
    global _armed
    await _wipe_folders(_AID)
    c = _login(_OWNER_USER)
    assert _triage(c, [
        {"media_id": 101, "rung": "nude"}, {"media_id": 102, "rung": "nude"},
    ]).status_code == 200
    fid = await _folder_id("feet-nude")

    _OF.reset()
    _armed = True
    try:
        r = c.post(f"/admin/vault-ai/folders/{fid}/publish", json={"account_id": _AID})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] is True, body
        assert body["pushed"] == 2, body
        assert body["stale_on_of"] == [], f"a fresh list must be an exact copy: {body}"
        list_id = body["of_list_id"]

        kinds = [call[0] for call in _OF.calls]
        assert kinds[:2] == ["create", "add"], f"create must precede add: {_OF.calls}"

        async with get_session() as s:
            assert (await s.get(VaultFolder, fid)).of_list_id == list_id

        _OF.calls.clear()
        again = c.post(f"/admin/vault-ai/folders/{fid}/publish", json={"account_id": _AID})
        assert again.status_code == 200, again.text
        assert again.json()["created"] is False, again.text
        assert again.json()["of_list_id"] == list_id, again.text
        assert not [call for call in _OF.calls if call[0] == "create"], \
            f"re-publish must never mint a second list: {_OF.calls}"
    finally:
        _armed = False


async def case_publish_reports_what_of_still_holds():
    global _armed
    await _wipe_folders(_AID)
    c = _login(_OWNER_USER)
    assert _triage(c, [
        {"media_id": 101, "rung": "nude"}, {"media_id": 102, "rung": "nude"},
    ]).status_code == 200
    fid = await _folder_id("feet-nude")

    _OF.reset()
    _armed = True
    try:
        first = c.post(f"/admin/vault-ai/folders/{fid}/publish", json={"account_id": _AID})
        assert first.status_code == 200, first.text
        assert first.json()["stale_on_of"] == [], first.text

        assert _triage(c, [{"media_id": 102, "rung": "reject"}]).status_code == 200

        again = c.post(f"/admin/vault-ai/folders/{fid}/publish", json={"account_id": _AID})
        assert again.status_code == 200, again.text
        body = again.json()
        assert body["pushed"] == 1, body
        assert body["stale_on_of"] == [102], \
            f"OF still holds 102 and the operator must be told: {body}"
    finally:
        _armed = False


async def case_publish_surfaces_an_of_failure():
    global _armed
    await _wipe_folders(_AID)
    c = _login(_OWNER_USER)
    assert _triage(c, [{"media_id": 101, "rung": "nude"}]).status_code == 200
    fid = await _folder_id("feet-nude")

    _OF.reset()
    _OF.create_fails = True
    _armed = True
    try:
        r = c.post(f"/admin/vault-ai/folders/{fid}/publish", json={"account_id": _AID})
        assert r.status_code == 502, f"expected of_publish_failed, got {r.status_code} {r.text}"
    finally:
        _armed = False
        _OF.create_fails = False

    m = await _membership(_AID)
    assert m["feet-nude"] == {101}, f"a failed publish must not touch the shelf: {m}"
    async with get_session() as s:
        assert (await s.get(VaultFolder, fid)).of_list_id is None



def case_category_lookup_table():
    feet = vault_pack_picker.CATEGORIES["feet"]
    known = [(name, vault_pack_picker.CATEGORIES[name])
             for name in vault_pack_picker.CATEGORIES]
    rows = known + [
        ("FEET", feet),
        ("FeEt", feet),
        ("  feet  ", feet),
        ("\tFeet\n", feet),
    ]
    for raw, want in rows:
        got = vault_pack_picker.category(raw)
        assert got is want, f"category({raw!r}) -> {got!r}, want {want!r}"

    for raw in (None, "", "   ", "foot", "feet-tease", "fe et", "hands"):
        try:
            got = vault_pack_picker.category(raw)
        except vault_pack_picker.UnknownCategory as e:
            assert e.args == (raw,), f"category({raw!r}) carried {e.args!r}"
        else:
            raise AssertionError(f"category({raw!r}) -> {got!r}, want UnknownCategory")


def case_normalise_verdicts_table():
    feet = vault_pack_picker.CATEGORIES["feet"]
    rows = [
        ([{"media_id": 1, "rung": "tease"}], {1: "tease"}),
        ([{"media_id": 1, "rung": "nude-body"}], {1: "nude-body"}),
        ([{"media_id": 1, "rung": "  NUDE "}], {1: "nude"}),
        ([{"media_id": 1, "rung": "Nude-Body"}], {1: "nude-body"}),
        *[([{"media_id": 1, "rung": v}], {1: None})
          for v in sorted(vault_pack_picker.REJECT_VALUES)],
        ([{"media_id": 1, "rung": None}], {1: None}),
        ([{"media_id": 1, "rung": " REJECT "}], {1: None}),
        ([{"media_id": 1, "rung": "None"}], {1: None}),
        ([{"media_id": 1}], {1: None}),
        ([{"media_id": 1, "rung": "tease"}, {"media_id": 1, "rung": "nude"}], {1: "nude"}),
        ([{"media_id": 1, "rung": "nude"}, {"media_id": 1, "rung": "reject"}], {1: None}),
        ([], {}),
        (None, {}),
    ]
    for given, want in rows:
        got = vault_pack_picker.normalise_verdicts(feet, given)
        assert got == want, f"normalise_verdicts(feet, {given!r}) -> {got!r}, want {want!r}"

    bad = [
        ([{"media_id": "12", "rung": "tease"}], ["12"]),
        ([{"media_id": 1.9, "rung": "nude"}], [1.9]),
        ([{"media_id": 1.0, "rung": "nude"}], [1.0]),
        ([{"media_id": True, "rung": "nude"}], [True]),
        ([{"rung": "nude"}], [None]),
        ([{"media_id": None, "rung": "nude"}], [None]),
        ([{"media_id": "abc", "rung": "nude"}], ["abc"]),
        ([{"media_id": [], "rung": "nude"}], [[]]),
        ([None, {"media_id": 2, "rung": "tease"}], [None]),
        ([{"media_id": 1, "rung": "nude"}, {"media_id": "1", "rung": "reject"}], ["1"]),
    ]
    for given, ids in bad:
        try:
            got = vault_pack_picker.normalise_verdicts(feet, given)
        except vault_pack_picker.InvalidMediaIds as e:
            assert e.media_ids == ids, f"normalise_verdicts(feet, {given!r}) named {e.media_ids!r}, want {ids!r}"
        else:
            raise AssertionError(f"normalise_verdicts(feet, {given!r}) -> {got!r}, want InvalidMediaIds")


def case_normalise_verdicts_unknown_rung():
    feet = vault_pack_picker.CATEGORIES["feet"]
    other = vault_pack_picker.Category(name="hands", rungs=("closeup",))
    bad = [
        (feet, [{"media_id": 1, "rung": "closeup"}], "closeup"),
        (other, [{"media_id": 1, "rung": "nude"}], "nude"),
        (other, [{"media_id": 1, "rung": " TEASE "}], "tease"),
        (feet, [{"media_id": 1, "rung": "tease"}, {"media_id": 2, "rung": "nude body"}],
         "nude body"),
    ]
    for cat, given, rung in bad:
        try:
            got = vault_pack_picker.normalise_verdicts(cat, given)
        except vault_pack_picker.UnknownRung as e:
            assert e.args == (rung,), f"{cat.name} {given!r}: UnknownRung{e.args!r}"
        else:
            raise AssertionError(f"{cat.name} {given!r} -> {got!r}, want UnknownRung")


_RANK = "acc_rank"
_JEV = "acc_jev"
_FLAGGED = {"underwear_visible": False, "breasts_vis": "not_in_frame",
            "vulva_vis": "not_in_frame", "anus_vis": "not_in_frame"}


def _flags(**regions) -> dict:
    return {**_FLAGGED, **regions}


def _jev_blob(lane5: str = "free", feet_subject: float = 0.9, detail: str = "socks", soles: float = 0.0,
              toes: float = 0.0, seen: str = "y", **body) -> dict:
    return {"v": "v8+nn.10", "status": "ok", "lane5": lane5,
            **{"breasts_bare": "n", "crotch_bare": "n", "penetration": "n", **body},
            "feet_subject": feet_subject,
            "P": {"feet_focus": feet_subject, "soles_visible": soles, "bare_toes_visible": toes},
            "tags": {"feet_detail": detail, "feet_any": seen,
                     "feet_focus": "y" if isinstance(feet_subject, float) and feet_subject >= 0.4 else "n"}}


def case_price_tier_table():
    tier = vault_pack_picker.price_tier
    rows = [
        ("no jev, nothing on show", _flags(), None),
        ("no jev, toy inserted", {"penetration": "toy", "vulva_vis": "bare"}, None),
        ("not a dict", None, None),
        ("jev $50 over covered flags", {**_flags(), "_jev": _jev_blob(lane5="$50")}, 50),
        ("jev $10, unflagged", {"_jev": _jev_blob(lane5="$10")}, 10),
        ("jev $100", {"_jev": _jev_blob(lane5="$100")}, 100),
        ("jev free over topless flags", {**_flags(breasts_vis="bare"), "_jev": _jev_blob()}, 0),
        ("jev free, unflagged: known", {"clothing_state": "fully_nude", "_jev": _jev_blob()}, 0),
        ("jev free, breasts unsure: unknown", {**_flags(), "_jev": _jev_blob(breasts_bare="unsure")}, None),
        ("jev free, crotch y: unknown", {**_flags(), "_jev": _jev_blob(crotch_bare="y")}, None),
        ("jev free, penetration unsure: unknown", {**_flags(), "_jev": _jev_blob(penetration="unsure")}, None),
        ("jev free, body answers missing: unknown", {**_flags(), "_jev": {"status": "ok", "lane5": "free"}},
         None),
        ("jev junk lane: unknown", {**_flags(breasts_vis="bare"), "_jev": _jev_blob(lane5="$7")}, None),
        ("jev review is unknown, even over free flags", {**_flags(), "_jev": _jev_blob(lane5="review")}, None),
        ("jev failed: unknown", {**_flags(breasts_vis="bare"), "_jev": {**_jev_blob(), "status": "error"}}, None),
        ("jev without status: unknown", {**_flags(), "_jev": {"lane5": "$50"}}, None),
        ("jev without lane5", {"_jev": {"status": "ok", "feet_subject": 0.9}}, None),
        ("video jev $100", {"_jev": {**_jev_blob(lane5="$100"), "kind": "video"}}, 100),
    ]
    for name, fields, want in rows:
        got = tier(fields)
        assert got == want, f"{name}: price_tier={got!r}, want {want!r}"


def case_jev_likelihood_table():
    feet = vault_pack_picker.category("feet")
    p = lambda v, **kw: vault_pack_picker.jev_likelihood(feet, _jev_blob(feet_subject=v, **kw))  # noqa: E731
    assert p(0.07) == 0.07 and p(1.7) == 1.0 and p(-1.0) == 0.0
    for junk in (True, "0.9", None, float("nan")):
        assert p(junk) == 0.0, junk
    base = p(0.5)
    assert p(0.5, soles=1.0) > base and p(0.5, toes=0.8) > base, base
    assert abs(p(0.5, soles=1.0) - (1 - 0.5 * (1 - vault_pack_picker._EV_JEV_BOOST))) < 1e-9
    assert p(0.5, detail="not_in_picture") < base


def case_jev_pick_preselect_table():
    feet = vault_pack_picker.category("feet")
    rows = [
        ("score .6, socks, free", _jev_blob(feet_subject=0.6), "tease"),
        ("score .59", _jev_blob(feet_subject=0.59), None),
        ("score .5 + soles boost -> .65", _jev_blob(feet_subject=0.5, soles=1.0, detail="bare"), "nude"),
        ("$100 body", _jev_blob(lane5="$100", feet_subject=0.9), "nude-body"),
        ("free, breasts unsure", _jev_blob(feet_subject=0.95, breasts_bare="unsure"), None),
        ("review", _jev_blob(lane5="review", feet_subject=0.95), None),
        ("feet not seen", {**_jev_blob(feet_subject=0.95), "tags": {"feet_any": "n", "feet_focus": "n",
                                                                    "feet_detail": "socks"}}, None),
        ("not in picture", _jev_blob(feet_subject=0.95, detail="not_in_picture"), None),
        ("failed", {**_jev_blob(feet_subject=0.95), "status": "error"}, None),
        ("no lane5", {k: v for k, v in _jev_blob(feet_subject=0.95).items() if k != "lane5"}, None),
        ("heels, free", _jev_blob(detail="heels"), "tease"),
        ("stockings, free", _jev_blob(detail="stockings_fishnets_nylons"), "tease"),
        ("bare, free", _jev_blob(detail="bare"), "nude"),
        ("$10 in heels", _jev_blob(lane5="$10", detail="heels"), "nude-body"),
        ("$50 at .55", _jev_blob(lane5="$50", feet_subject=0.55), None),
        ("free, crotch unsure, bare feet", _jev_blob(crotch_bare="unsure", detail="bare"), None),
        ("free, penetration y", _jev_blob(penetration="y"), None),
    ]
    assert vault_pack_picker.FEET_PRESELECT_SCORE == 0.6
    for name, j, want in rows:
        got = vault_pack_picker.jev_pick(feet, j)
        assert got == want, f"{name}: jev_pick={got!r}, want {want!r}"


def case_possible_table():
    feet = vault_pack_picker.category("feet")
    pv = lambda j: vault_pack_picker.possible(feet, {"_jev": j}) is not None  # noqa: E731
    assert vault_pack_picker.FEET_POSSIBLE_MIN == 0.3
    rows = [
        ("score .59", _jev_blob(feet_subject=0.59), True),
        ("score .3: at the floor", _jev_blob(feet_subject=0.3), True),
        ("score .29: below the floor", _jev_blob(feet_subject=0.29), False),
        ("score .05, seen", _jev_blob(feet_subject=0.05), False),
        ("score .2 + soles 1.0 boosted over the floor", _jev_blob(feet_subject=0.2, soles=1.0), True),
        ("score .6: confident, not possible", _jev_blob(feet_subject=0.6), False),
        ("unseen", _jev_blob(feet_subject=0.3, seen="n"), False),
        ("failed", {**_jev_blob(feet_subject=0.3), "status": "error"}, False),
        ("a clip", _video_jev(feet_subject=0.3), False),
    ]
    for name, j, want in rows:
        assert pv(j) is want, f"{name}: possible={pv(j)!r}, want {want!r}"
    assert vault_pack_picker.possible(feet, None) is None and vault_pack_picker.possible(feet, {}) is None
    rung = lambda j: vault_pack_picker.jev_rung(feet, j)  # noqa: E731
    rungs = [
        ("socks, free, .3", _jev_blob(feet_subject=0.3), "tease"),
        ("bare, free, .3", _jev_blob(feet_subject=0.3, detail="bare"), "nude"),
        ("$50 body, .3", _jev_blob(lane5="$50", feet_subject=0.3), "nude-body"),
        ("free, breasts unsure: unknown tier, never free", _jev_blob(feet_subject=0.3, breasts_bare="unsure"), None),
        ("review: unknown tier", _jev_blob(lane5="review", feet_subject=0.3), None),
        ("not in picture", _jev_blob(feet_subject=0.3, detail="not_in_picture"), None),
    ]
    for name, j, want in rungs:
        assert rung(j) == want, f"{name}: jev_rung={rung(j)!r}, want {want!r}"
        assert vault_pack_picker.jev_pick(feet, j) is None
        assert vault_pack_picker.jev_pick(feet, {**j, "feet_subject": 0.9,
                                                 "P": {**j["P"], "feet_focus": 0.9}}) == want, name


def case_jev_free_ok_table():
    rows = [
        ("jev safe free", {"_jev": _jev_blob()}, True),
        ("jev $10", {"_jev": _jev_blob(lane5="$10")}, False),
        ("jev review", {"_jev": _jev_blob(lane5="review")}, False),
        ("jev free, breasts y", {"_jev": _jev_blob(breasts_bare="y")}, False),
        ("jev free, crotch unsure", {"_jev": _jev_blob(crotch_bare="unsure")}, False),
        ("jev free, penetration unsure", {"_jev": _jev_blob(penetration="unsure")}, False),
        ("jev safe free, breasts_vis bare (locked)", {"_jev": _jev_blob(), **_flags(breasts_vis="bare")}, False),
        ("jev safe free, dressed but vulva bare", {"_jev": _jev_blob(), **_flags(vulva_vis="bare"),
                                                   "clothing_state": "dressed"}, False),
        ("jev safe free, flags covered", {"_jev": _jev_blob(), **_flags(breasts_vis="covered")}, True),
        ("jev failed", {"_jev": {**_jev_blob(), "status": "error"}}, None),
        ("no jev", _flags(), None),
        ("no jev, breasts_vis bare", _flags(breasts_vis="bare"), False),
        ("jev failed, vulva bare", {"_jev": {**_jev_blob(), "status": "error"}, **_flags(vulva_vis="bare")}, False),
        ("not a dict", None, None),
    ]
    for name, fields, want in rows:
        got = vault_pack_picker.free_ok(fields)
        assert got is want, f"{name}: free_ok={got!r}, want {want!r}"
    feet = vault_pack_picker.category("feet")
    assert feet.free_rung == "tease"


async def case_candidates_jev_selects_and_ranks():
    c = _login(_OWNER_USER)
    seeds = {
        401: {"description": "legs up on the bed", "body_focus": ["legs"],
              "_jev": _jev_blob(feet_subject=0.8, detail="bare", soles=0.9)},
        402: {"description": "close up of her soles", "primary_folder": "feet", "body_focus": ["feet"],
              "_jev": _jev_blob(feet_subject=0.05, detail="other_shoes")},
        403: {"description": "standing on her feet", "body_focus": ["feet", "face"],
              "_jev": _jev_blob(feet_subject=0.02, detail="not_in_picture", seen="n")},
        404: {"description": "feet on the pillow", **_flags(),
              "_jev": _jev_blob(feet_subject=0.95, detail="bare", breasts_bare="unsure")},
        405: {"description": "her feet in pink socks", "primary_folder": "feet", "body_focus": ["feet"],
              "clothing_items": ["pink socks"], **_flags(),
              "_jev": {**_jev_blob(feet_subject=0.01), "status": "error"}},
        406: None,
        407: {"description": "legs on the sofa", "_jev": _jev_blob(feet_subject=0.55)},
        408: {"description": "on the rug", "_jev": _jev_blob(feet_subject=0.3)},
        409: {"description": "on the rug", "_jev": _jev_blob(feet_subject=0.29)},
        412: {"description": "socks on the bed", **_flags(breasts_vis="bare"),
              "_jev": _jev_blob(feet_subject=0.9)},
    }
    for mid, fields in seeds.items():
        await _seed_item(_JEV, mid, fields=fields)
    async with get_session() as s:
        row = await s.get(VaultItem, (_JEV, 406))
        row.ai_fields_json = '{"_jev": {"tags": {"feet_any": "y"'
        row.search_text = "feet"
    r = c.get("/admin/vault-ai/pack-candidates", params={"account_id": _JEV, "category": "feet"})
    assert r.status_code == 200, r.text
    by = {x["media_id"]: x for x in r.json()["candidates"]}
    order = [x["media_id"] for x in r.json()["candidates"]]
    assert order == [404, 412, 401, 407, 408], order
    assert (by[412]["suggested"], by[412]["free_ok"], by[412]["preselect"]) == (None, False, False), by[412]
    for m in (404, 401):
        assert by[m]["possible"] is False, by[m]
    assert (by[407]["possible"], by[407]["preselect"], by[407]["suggested"], by[407]["score"]) == \
        (True, False, "tease", 0.55), by[407]
    assert (by[408]["possible"], by[408]["preselect"], by[408]["suggested"], by[408]["score"]) == \
        (True, False, "tease", 0.3), by[408]
    assert _triage(c, [{"media_id": 409, "rung": "tease"}], aid=_JEV).status_code == 200
    back = c.get("/admin/vault-ai/pack-candidates", params={"account_id": _JEV, "category": "feet"}).json()
    assert {x["media_id"]: x["rung"] for x in back["candidates"]}.get(409) == "tease", back["candidates"]
    assert _triage(c, [{"media_id": 409, "rung": "reject"}], aid=_JEV).status_code == 200
    assert (by[401]["suggested"], by[401]["tier"], by[401]["free_ok"], by[401]["jev"]) == ("nude", 0, True, True)
    assert by[401]["preselect"] is True, by[401]
    assert (by[404]["suggested"], by[404]["tier"], by[404]["free_ok"], by[404]["preselect"]) == \
        (None, None, False, False), by[404]


async def case_triage_refuses_unsafe_free():
    await _wipe_folders(_JEV)
    c = _login(_OWNER_USER)
    await _seed_item(_JEV, 410, fields={"description": "feet", "_jev": _jev_blob(lane5="review")})
    await _seed_item(_JEV, 411, fields={"description": "feet", "_jev": _jev_blob(penetration="unsure")})
    r = _triage(c, [{"media_id": 404, "rung": "tease"}, {"media_id": 410, "rung": "tease"},
                    {"media_id": 411, "rung": "tease"}, {"media_id": 401, "rung": "tease"}], aid=_JEV)
    assert r.status_code == 400, r.text
    d = r.json()["detail"]
    assert d["error"] == "not_free_safe" and d["media_ids"] == [404, 410, 411] and d["rung"] == "tease", d
    assert not any((await _membership(_JEV)).values()), "a refused triage writes nothing"
    r = _triage(c, [{"media_id": 404, "rung": "nude-body"}, {"media_id": 401, "rung": "tease"},
                    {"media_id": 405, "rung": "tease"}], aid=_JEV)
    assert r.status_code == 200, r.text
    m = await _membership(_JEV)
    assert m["feet-tease"] == {401, 405} and m["feet-nude-body"] == {404}, m


def _video_jev(**kw) -> dict:
    return {**_jev_blob(**kw), "kind": "video", "vv": 1, "frame": 7, "frames": [], "src": "720", "review": None}


# Owner decision: no clips in feet.
async def case_video_never_feet():
    await _wipe_folders(_JEV)
    c = _login(_OWNER_USER)
    clip = {"description": "close up of her soles in white socks", "primary_folder": "feet", "body_focus": ["feet"],
            "_jev": _video_jev(feet_subject=0.95, detail="socks")}
    await _seed_item(_JEV, 420, fields=clip, kind="video", search_text="feet soles socks")
    await _seed_item(_JEV, 421, fields={"description": "feet", "_jev": _jev_blob(feet_subject=0.95)}, kind="gif")
    assert vault_pack_picker.jev_ok(clip) is None
    assert (vault_pack_picker.price_tier(clip), vault_pack_picker.free_ok(clip)) == (0, True)
    review = {**clip, "_jev": _video_jev(lane5="review")}
    assert (vault_pack_picker.price_tier(review), vault_pack_picker.free_ok(review)) == (None, False)

    def ids():
        r = c.get("/admin/vault-ai/pack-candidates", params={"account_id": _JEV, "category": "feet"})
        assert r.status_code == 200, r.text
        return {x["media_id"]: x for x in r.json()["candidates"]}
    by = ids()
    assert 420 not in by and 421 not in by and 401 in by, sorted(by)

    for rung in _RUNGS:
        r = _triage(c, [{"media_id": 401, "rung": "nude"}, {"media_id": 420, "rung": rung},
                        {"media_id": 421, "rung": rung}], aid=_JEV)
        assert r.status_code == 400, r.text
        assert {k: r.json()["detail"][k] for k in ("error", "media_ids")} == {"error": "feet_photos_only", "media_ids": [420, 421]}, r.text
        assert not any((await _membership(_JEV)).values()), "a refused triage writes nothing"

    assert _triage(c, [{"media_id": 401, "rung": "nude"}], aid=_JEV).status_code == 200
    async with get_session() as s:
        s.add(VaultFolderItem(account_id=_JEV, folder_id=await _folder_id("feet-nude", _JEV), media_id=420))
    v = ids()[420]
    assert (v["rung"], v["jev"], v["preselect"], v["suggested"]) == ("nude", False, False, None), v
    r = _triage(c, [{"media_id": 420, "rung": None}], aid=_JEV)
    assert r.status_code == 200 and r.json()["rejected"] == 1, r.text
    assert (await _membership(_JEV))["feet-nude"] == {401}
    assert 420 not in ids()
    await _wipe_folders(_JEV)


async def case_triage_refuses_ids_not_in_mirror():
    await _wipe_folders(_JEV)
    c = _login(_OWNER_USER)
    await _seed_item(_JEV, 430, fields={"description": "feet", "_jev": _jev_blob()})
    async with get_session() as s:
        (await s.get(VaultItem, (_JEV, 430))).removed_at = datetime.utcnow()
    r = _triage(c, [{"media_id": 401, "rung": "nude"}, {"media_id": 430, "rung": "nude"},
                    {"media_id": 101, "rung": "nude"}, {"media_id": 99999, "rung": "nude"}], aid=_JEV)
    assert r.status_code == 404, r.text
    assert {k: r.json()["detail"][k] for k in ("error", "media_ids")} == {"error": "not_in_mirror", "media_ids": [101, 430, 99999]}, r.text
    assert not any((await _membership(_JEV)).values()), "a refused triage writes nothing"
    r = _triage(c, [{"media_id": 401, "rung": "nude"}, {"media_id": 99999, "rung": None}], aid=_JEV)
    assert r.status_code == 200, r.text
    assert (await _membership(_JEV))["feet-nude"] == {401}
    await _wipe_folders(_JEV)


async def case_publish_free_rung_skips_unsafe():
    global _armed
    await _wipe_folders(_JEV)
    c = _login(_OWNER_USER)
    assert _triage(c, [{"media_id": 401, "rung": "tease"}, {"media_id": 405, "rung": "tease"},
                       {"media_id": 404, "rung": "nude-body"}], aid=_JEV).status_code == 200
    tease = await _folder_id("feet-tease", _JEV)
    paid_id = await _folder_id("feet-nude-body", _JEV)
    async with get_session() as s:
        s.add(VaultFolderItem(account_id=_JEV, folder_id=tease, media_id=410))
        s.add(VaultFolderItem(account_id=_JEV, folder_id=tease, media_id=420))
        s.add(VaultFolderItem(account_id=_JEV, folder_id=paid_id, media_id=421))
    r = c.get("/admin/vault-ai/pack-candidates", params={"account_id": _JEV, "category": "feet"})
    by = {x["media_id"]: x for x in r.json()["candidates"]}
    assert (by[410]["rung"], by[410]["unsafe_on_free"]) == ("tease", True), by[410]
    assert not by[401]["unsafe_on_free"] and not by[405]["unsafe_on_free"], (by[401], by[405])
    assert not by[404]["unsafe_on_free"], "unsafe on a paid rung is fine"

    _OF.reset()
    _armed = True
    try:
        pub = c.post(f"/admin/vault-ai/folders/{tease}/publish", json={"account_id": _JEV})
        assert pub.status_code == 200, pub.text
        body = pub.json()
        assert (body["skipped_unsafe"], body["skipped_videos"], body["pushed"]) == ([410], [420], 2), body
        added = [m for call in _OF.calls if call[0] == "add" for m in call[2]]
        assert sorted(added) == [401, 405], f"410 / clip 420 must never reach the free list: {_OF.calls}"
        _OF.reset()
        paid = c.post(f"/admin/vault-ai/folders/{paid_id}/publish", json={"account_id": _JEV})
        assert paid.status_code == 200, paid.text
        pb = paid.json()
        assert (pb["skipped_unsafe"], pb["skipped_videos"], pb["pushed"]) == ([], [421], 1), pb
        added = [m for call in _OF.calls if call[0] == "add" for m in call[2]]
        assert added == [404], f"gif 421 must never reach a paid list: {_OF.calls}"
    finally:
        _armed = False

    assert _triage(c, [{"media_id": 401, "rung": "reject"}, {"media_id": 405, "rung": "reject"}],
                   aid=_JEV).status_code == 200
    r = c.post(f"/admin/vault-ai/folders/{tease}/publish", json={"account_id": _JEV})
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == {"error": "folder_empty", "skipped_unsafe": [410], "skipped_videos": [420]}, r.text
    assert _triage(c, [{"media_id": m, "rung": "reject"} for m in (410, 420, 421)], aid=_JEV).status_code == 200
    m = await _membership(_JEV)
    assert not {410, 420} & m["feet-tease"] and 421 not in m["feet-nude-body"], m


async def case_candidates_ranked_and_prefilled():
    c = _login(_OWNER_USER)
    unseen = {**_jev_blob(feet_subject=0.9), "tags": {"feet_any": "n", "feet_focus": "n", "feet_detail": "socks"}}
    seeds = {
        301: ({"description": "her feet in pink socks", "_jev": _jev_blob(feet_subject=0.95)}, None, "photo"),
        302: ({"description": "topless, toes pointed", "_jev": _jev_blob(lane5="$10", feet_subject=0.7)},
              None, "photo"),
        303: ({"description": "legs up", "_jev": _jev_blob(feet_subject=0.5, soles=1.0, detail="bare")},
              None, "photo"),
        304: ({"description": "feet on the sofa", "_jev": _jev_blob(feet_subject=0.59)}, "feet", "photo"),
        305: ({"description": "close up of her soles", "primary_folder": "feet", "body_focus": ["feet"],
               **_flags()}, "barefoot feet soles", "photo"),
        306: ({"description": "her feet", "_jev": _video_jev(feet_subject=0.95)}, "feet", "video"),
        307: ({"description": "feet", "_jev": unseen}, "feet", "photo"),
        308: ({"description": "feet on the pillow", "_jev": _jev_blob(feet_subject=0.9, breasts_bare="unsure")},
              None, "photo"),
    }
    for mid, (fields, text, kind) in seeds.items():
        await _seed_item(_RANK, mid, fields=fields, search_text=text, kind=kind)

    def get(**params):
        r = c.get("/admin/vault-ai/pack-candidates",
                  params={"account_id": _RANK, "category": "feet", **params})
        assert r.status_code == 200, r.text
        return r.json()

    body = get()
    order = [x["media_id"] for x in body["candidates"]]
    assert order == [301, 308, 302, 303, 304], order
    by = {x["media_id"]: x for x in body["candidates"]}
    assert (by[301]["suggested"], by[301]["tier"], by[301]["preselect"]) == ("tease", 0, True), by[301]
    assert (by[302]["suggested"], by[302]["tier"], by[302]["preselect"]) == ("nude-body", 10, True), by[302]
    assert (by[303]["suggested"], by[303]["score"]) == ("nude", 0.65), by[303]
    assert (by[308]["suggested"], by[308]["preselect"], by[308]["free_ok"]) == (None, False, False), by[308]
    assert (by[304]["suggested"], by[304]["preselect"], by[304]["possible"], by[304]["score"]) == \
        ("tease", False, True, 0.59), by[304]
    assert all(x["jev"] and x["kind"] == "photo" for x in body["candidates"]), body["candidates"]
    sure = [x["score"] for x in body["candidates"] if not x["possible"]]
    maybe = [x["score"] for x in body["candidates"] if x["possible"]]
    assert sure == sorted(sure, reverse=True) and min(sure) >= vault_pack_picker.FEET_PRESELECT_SCORE, sure
    assert maybe == sorted(maybe, reverse=True) and max(maybe) < vault_pack_picker.FEET_PRESELECT_SCORE, maybe

    real_cap = vault_pack_picker._SCAN_CAP
    vault_pack_picker._SCAN_CAP = 2
    try:
        capped = [sorted(x["media_id"] for x in get()["candidates"]) for _ in range(3)]
    finally:
        vault_pack_picker._SCAN_CAP = real_cap
    assert capped == [[304, 308]] * 3, capped

    r = _triage(c, [{"media_id": 301, "rung": "tease"}, {"media_id": 305, "rung": "nude"},
                    {"media_id": 304, "rung": "nude"}], aid=_RANK)
    assert r.status_code == 200, r.text
    async with get_session() as s:
        s.add(VaultFolderItem(account_id=_RANK, folder_id=await _folder_id("feet-nude-body", _RANK), media_id=306))
    cut = get(limit=2)
    ids = [x["media_id"] for x in cut["candidates"]]
    assert ids == [308, 302, 301, 304, 305, 306], ids
    assert [x["rung"] for x in cut["candidates"]] == [None, None, "tease", "nude", "nude", "nude-body"], cut
    assert cut["filed"] == 4, cut


async def _seed_fixtures():
    owner_uid = await _seed_user(_OWNER_USER)
    stranger_uid = await _seed_user(_STRANGER_USER)
    await _seed_account(_AID, owner_uid)
    await _seed_account(_FOREIGN, stranger_uid)
    await _seed_account(_RANK, owner_uid)
    await _seed_account(_JEV, owner_uid)
    await _seed_item(_AID, 101, search_text="barefoot feet soles on the bed",
                     fields={"description": "barefoot on the bed", "_jev": _jev_blob(feet_subject=0.9, detail="bare")})
    await _seed_item(_AID, 102, fields={"description": "legs crossed on the sofa", "_jev": _jev_blob(feet_subject=0.8)})
    await _seed_item(_AID, 103, search_text="barefoot feet soles", fields={
        "description": "close up of her soles", "primary_folder": "feet", "body_focus": ["feet"],
    })


_harness.run(
    _seed_fixtures,
    case_candidates_match_and_carry_rung,
    case_triage_creates_all_rungs,
    case_verdict_is_exclusive,
    case_reject_removes_everywhere,
    case_resave_is_idempotent,
    case_unknown_rung_and_category_400,
    case_folder_name_survives_the_reaper,
    case_owner_auth_403,
    case_publish_refuses_empty_folder,
    case_publish_binds_then_adds_and_reuses_the_list,
    case_publish_reports_what_of_still_holds,
    case_publish_surfaces_an_of_failure,
    case_category_lookup_table,
    case_normalise_verdicts_table,
    case_normalise_verdicts_unknown_rung,
    case_price_tier_table,
    case_jev_likelihood_table,
    case_candidates_ranked_and_prefilled,
    case_jev_free_ok_table,
    case_jev_pick_preselect_table,
    case_possible_table,
    case_candidates_jev_selects_and_ranks,
    case_triage_refuses_unsafe_free,
    case_video_never_feet,
    case_triage_refuses_ids_not_in_mirror,
    case_publish_free_rung_skips_unsafe,
)
