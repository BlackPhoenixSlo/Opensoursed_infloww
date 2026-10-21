#!/usr/bin/env python3
"""
The pack picker — `/admin/vault-ai/pack-candidates` and `/pack-triage`, plus
`/admin/vault-ai/folders/{id}/publish`. Plain-assert, no pytest (repo convention).

WHAT THIS PROTECTS. The picker is the only thing standing between the AI upseller
and a 22% hit rate: the vault's own taxonomy cannot find feet content (measured on
prod 2026-08-10 — `primary_folder='feet'` is set on ZERO items on either pilot and
on ZERO of the 68 items the operator hand-picked, while `body_focus` says "feet"
on 278 items because it lists feet whenever they are merely VISIBLE). So a human
files each candidate, and these are the invariants that make their verdict
trustworthy afterwards.

Cases:
  case_candidates_match_and_carry_rung — search_text OR ai_fields_json hits are
      candidates; a non-matching item is not; each carries the rung it is filed
      on now, read from FOLDER MEMBERSHIP (never ai_fields_json, a shared blob).
  case_triage_creates_all_rungs        — first save makes all three folders with
      created_by="operator" and of_list_id NULL, even the empty ones.
  case_verdict_is_exclusive            — re-filing an item moves it; it never
      ends up on two rungs of the same category.
  case_reject_removes_everywhere       — a null/"reject" verdict clears the item
      from every rung, and stores nothing about the rejection.
  case_resave_is_idempotent            — the same verdicts twice leave identical
      membership (no duplicate rows, no churn).
  case_unknown_rung_and_category_400   — a bad rung or category is refused rather
      than silently filed.
  case_folder_name_survives_the_reaper — the created folders are exactly what
      vault_scripts' reaper cannot touch (created_by != vault_ai_script AND no
      AI- prefix), asserted against the reaper's real predicate.
  case_owner_auth_403                  — a logged-in non-owner is refused on
      every route and nothing is written.
  case_publish_refuses_empty_folder    — empty folder 400s, unknown folder 404s,
      a non-owner 403s, and none of them construct an OF client.
  case_publish_binds_then_adds_...     — the happy path against a fake OF: create
      precedes add, of_list_id is persisted, and a re-publish reuses the list
      instead of minting a twin.
  case_publish_reports_what_of_still_holds — publish is ADDITIVE, so an item
      removed from the rung stays on OF; `stale_on_of` must surface it.
  case_publish_surfaces_an_of_failure  — an OF error is a 502 that leaves the
      internal folder and its membership untouched.

Run: cd service/tests && \
  PYTHONPATH=$(cd .. && pwd) ../../venv/bin/python test_vault_pack_picker.py
Exit 0 = all cases passed. Temp DB bound by _harness (never prod).
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import json  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

import accounts as account_registry  # noqa: E402
import automation_executor as ax  # noqa: E402 — patch the OF-client seam
import server  # noqa: E402
import vault_scripts  # noqa: E402 — the reaper predicate under test
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, User, UserAccount, VaultFolder, VaultFolderItem, VaultItem,
)

_TEST_ACCOUNTS = {"acc_owner", "acc_foreign"}
_orig_get_account = account_registry.get_account
_orig_list_accounts = account_registry.list_accounts
account_registry.get_account = (
    lambda a: ({"id": a, "nickname": a} if a in _TEST_ACCOUNTS else _orig_get_account(a))
)
account_registry.list_accounts = (
    lambda: [{"id": a, "nickname": a} for a in sorted(_TEST_ACCOUNTS)]
)
account_registry.is_account = lambda aid: aid in _TEST_ACCOUNTS

# ── The OF seam ─────────────────────────────────────────────────────
#
# Triage is a pure DB operation and must never reach OnlyFans; publish is the ONE
# route allowed to. `_armed` starts False so any accidental client construction
# in a triage case fails loudly, and the publish cases arm it deliberately.

class _FakeOF:
    """Records calls in order — publish's ordering (bind before add) is a
    documented invariant, so the order is part of what is asserted."""

    def __init__(self):
        self.timeout_s = 5.0
        self.calls: list[tuple] = []
        self.next_list_id = 700
        self.create_fails = False
        # list_id -> what OF reports in it, which is NOT always what we pushed.
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
        # OF's lists are additive — mirror that, because `stale_on_of` exists
        # precisely to surface what additivity leaves behind.
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


# ── Seeders ─────────────────────────────────────────────────────────

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
    """{folder_name -> {media_id}} for this account, from MEMBERSHIP rows."""
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


# ── Cases ───────────────────────────────────────────────────────────

async def case_candidates_match_and_carry_rung():
    await _wipe_folders(_AID)
    c = _login(_OWNER_USER)

    r = c.get("/admin/vault-ai/pack-candidates", params={"account_id": _AID, "category": "feet"})
    assert r.status_code == 200, r.text
    body = r.json()
    got = {int(x["media_id"]) for x in body["candidates"]}

    # 101 matches on search_text, 102 on ai_fields_json's body_focus, 103 on
    # neither — the union is the candidate generator the 08-01 triage used.
    assert 101 in got and 102 in got, f"both signals must generate candidates: {sorted(got)}"
    assert 103 not in got, "an item matching neither signal must not be a candidate"
    assert body["rungs"] == list(_RUNGS), body["rungs"]
    # Nothing filed yet.
    assert all(x["rung"] is None for x in body["candidates"]), body["candidates"]

    # The SHELF ships with the candidates, before any save has happened. This is
    # what makes the publish buttons reachable on open rather than only in the
    # moment after a Save — the ladder's shape must not depend on triage progress.
    shelf = body["folders"]
    assert [f["rung"] for f in shelf] == list(_RUNGS), shelf
    assert all(f["folder_id"] is None and f["count"] == 0 for f in shelf), shelf

    # File one, and it must come back carrying its rung.
    assert _triage(c, [{"media_id": 101, "rung": "nude"}]).status_code == 200
    again = c.get("/admin/vault-ai/pack-candidates",
                  params={"account_id": _AID, "category": "feet"}).json()
    by_id = {int(x["media_id"]): x["rung"] for x in again["candidates"]}
    assert by_id[101] == "nude", by_id
    assert by_id[102] is None, by_id
    assert again["filed"] == 1, again["filed"]

    # …and the shelf now carries real folder ids, so publish is live.
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

    # And it comes back as an ordinary unruled candidate — nothing is stored
    # about the rejection, so there is no reject list to maintain.
    body = c.get("/admin/vault-ai/pack-candidates",
                 params={"account_id": _AID, "category": "feet"}).json()
    by_id = {int(x["media_id"]): x["rung"] for x in body["candidates"]}
    assert by_id[101] is None, by_id

    # "reject" as a string must behave identically to null.
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
    listing = c.get("/admin/vault-ai/pack-candidates",
                    params={"account_id": _AID, "category": "elbows"})
    assert listing.status_code == 400, listing.status_code


async def case_folder_name_survives_the_reaper():
    """The folders must be outside vault_scripts' blast radius, by ITS predicate.

    vault_scripts retires a folder only when created_by == "vault_ai_script" AND
    the name starts with AI_FOLDER_PREFIX. Assert against the real constant, so
    renaming the prefix upstream breaks this test rather than the shelf.
    """
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
    """An empty OF list is noise in her vault, so publish refuses BEFORE the
    network — and refusing must not cost an OF client construction."""
    await _wipe_folders(_AID)
    c = _login(_OWNER_USER)
    assert _triage(c, [{"media_id": 101, "rung": "nude"}]).status_code == 200
    empty_id = await _folder_id("feet-tease")

    # The OF seam is DISARMED here: reaching it at all fails this case.
    r = c.post(f"/admin/vault-ai/folders/{empty_id}/publish", json={"account_id": _AID})
    assert r.status_code == 400, f"expected folder_empty, got {r.status_code} {r.text}"
    assert r.json()["detail"]["error"] == "folder_empty", r.text

    missing = c.post("/admin/vault-ai/folders/999999/publish", json={"account_id": _AID})
    assert missing.status_code == 404, missing.status_code

    foreign = c.post(f"/admin/vault-ai/folders/{empty_id}/publish",
                     json={"account_id": _FOREIGN})
    assert foreign.status_code == 403, foreign.status_code


async def case_publish_binds_then_adds_and_reuses_the_list():
    """The happy path of the one route that writes to her OnlyFans account.

    Asserts the ordering the primitive's docstring promises — create, bind
    of_list_id, THEN add — because a bind that lands after the add is what mints
    a second list with the same name on the next run.
    """
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

        # The id is persisted, so a re-publish tops up the SAME list.
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
    """Publish is additive: an item removed from the rung stays on OF. That has
    to be VISIBLE, because a silent divergence is a caption that can lie."""
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

        # The operator changes their mind: 102 is not a nude after all.
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
    """A failed OF write is a 502 that leaves the INTERNAL folder untouched — a
    folder that exists locally but not on OF is recoverable; losing it is not."""
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


async def _seed_fixtures():
    owner_uid = await _seed_user(_OWNER_USER)
    stranger_uid = await _seed_user(_STRANGER_USER)
    await _seed_account(_AID, owner_uid)
    await _seed_account(_FOREIGN, stranger_uid)
    # 101: matches on the denormalised search blob (tags + description).
    await _seed_item(_AID, 101, search_text="barefoot feet soles on the bed")
    # 102: matches only inside ai_fields_json — the body_focus signal, which is
    # exactly the over-inclusive one a human is here to filter.
    await _seed_item(_AID, 102, fields={
        "description": "lingerie pose, her feet happen to be in frame",
        "body_focus": ["face", "breasts", "legs", "feet"],
        "clothing_items": ["black thong"],
    })
    # 103: matches neither — must never appear as a candidate.
    await _seed_item(_AID, 103, search_text="shower selfie", fields={
        "description": "in the shower", "body_focus": ["face"], "clothing_items": [],
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
)
