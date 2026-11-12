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
  case_candidates_match_and_carry_rung — confident Jev photos are candidates; a
      photo whose words say feet but Jev never classified is not; each carries
      the rung it is filed on now, read from FOLDER MEMBERSHIP (never
      ai_fields_json, a shared blob).
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
  case_category_lookup_table           — pure: name lookup is case/space-blind;
      None/""/unknown raise UnknownCategory.
  case_normalise_verdicts_table        — pure: rung normalising, REJECT_VALUES ->
      None, last-wins dupes; a non-int media_id raises InvalidMediaIds.
  case_normalise_verdicts_unknown_rung — pure: a rung not in the category's
      rungs (incl. another category's) raises UnknownRung.
  case_price_tier_table                — pure: from `_jev` alone ($100 / $50 /
      $10 / free only with every body answer "n"); no usable `_jev` -> None.
  case_jev_likelihood_table            — pure: feet_subject clamped (junk 0),
      soles / toes boost by noisy-OR, not-in-picture damp.
  case_candidates_ranked_and_prefilled — route: only confident Jev photos (seen,
      score >= .6: .59 out), likely-first, each with suggested + tier + score;
      no-Jev words, failed Jev, unseen, videos out; `limit` cuts the unfiled
      queue only; filed items (a video, a no-Jev photo) always come back after
      it; a capped scan is deterministic.
  case_jev_free_ok_table               — pure: a Jev row may ride free only at
      lane5 free with breasts / crotch / penetration all "n"; no usable _jev -> None.
  case_jev_pick_preselect_table        — pure: `jev_pick` (preselect + AI-feet
      membership): score >= FEET_PRESELECT_SCORE (.59 no, .6 yes), feet seen,
      known tier, rung from tier + feet_detail, never tease for an unsafe body.
  case_candidates_jev_selects_and_ranks — route: a Jev-only feet photo (no word
      says feet) is found; Jev-says-no, failed Jev, malformed JSON and .55 are
      not; an unsafe confident row comes back unpicked, never free.
  case_triage_refuses_unsafe_free      — route: 400 not_free_safe for a Jev row
      that is not free-safe on the free rung, nothing written; paid rung / safe
      Jev / non-Jev rows on it are filed.
  case_video_never_feet                — route: a feet clip (Jev and words say
      feet) is no candidate; filing it (or a gif) on any rung is 400
      feet_photos_only, nothing written; one filed before the rule comes back
      and its reject is allowed.
  case_publish_free_rung_skips_unsafe  — route: a not-free-safe Jev row already on
      the free rung (pre-guard) is flagged `unsafe_on_free`, left out of the free
      rung's OF push (`skipped_unsafe`); a clip / gif filed on any rung before
      photos-only is left out (`skipped_videos`); a free rung of only such rows
      400s folder_empty before any OF client.

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

    # 101 and 102 are confident Jev photos; 103's words say feet but Jev never
    # classified it: it waits for Jev, no word-search candidates (precision only).
    assert 101 in got and 102 in got, f"confident Jev photos must be candidates: {sorted(got)}"
    assert 103 not in got, "a photo Jev has not classified must not be a candidate"
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


# ── Pure cases (no DB, no client) ───────────────────────────────────

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

    # "elbows" is pinned at the HTTP level in case_unknown_rung_and_category_400.
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
        # Rung case/whitespace normalised.
        ([{"media_id": 1, "rung": "  NUDE "}], {1: "nude"}),
        ([{"media_id": 1, "rung": "Nude-Body"}], {1: "nude-body"}),
        # Every REJECT_VALUES member, plus None / missing / casing → None.
        *[([{"media_id": 1, "rung": v}], {1: None})
          for v in sorted(vault_pack_picker.REJECT_VALUES)],
        ([{"media_id": 1, "rung": None}], {1: None}),
        ([{"media_id": 1, "rung": " REJECT "}], {1: None}),
        ([{"media_id": 1, "rung": "None"}], {1: None}),
        ([{"media_id": 1}], {1: None}),  # missing rung -> "" -> reject
        # Duplicate media_id: last wins.
        ([{"media_id": 1, "rung": "tease"}, {"media_id": 1, "rung": "nude"}], {1: "nude"}),
        ([{"media_id": 1, "rung": "nude"}, {"media_id": 1, "rung": "reject"}], {1: None}),
        # Empty input.
        ([], {}),
        (None, {}),
    ]
    for given, want in rows:
        got = vault_pack_picker.normalise_verdicts(feet, given)
        assert got == want, f"normalise_verdicts(feet, {given!r}) -> {got!r}, want {want!r}"

    # A media_id that is not a plain int refuses the whole batch, naming the bad values: never coerced onto
    # another item (1.9 -> 1, True -> 1), never silently dropped (missing / None / junk / a non-object row).
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
    # A rung valid for ANOTHER category is refused here. ("soles" is pinned at
    # the HTTP level in case_unknown_rung_and_category_400.)
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
    """A `_jev` as `vault_jev_rules.blob` stores it (the keys the picker reads)."""
    return {"v": "v8+nn.10", "status": "ok", "lane5": lane5,
            **{"breasts_bare": "n", "crotch_bare": "n", "penetration": "n", **body},
            "feet_subject": feet_subject,
            "P": {"feet_focus": feet_subject, "soles_visible": soles, "bare_toes_visible": toes},
            "tags": {"feet_detail": detail, "feet_any": seen,
                     "feet_focus": "y" if isinstance(feet_subject, float) and feet_subject >= 0.4 else "n"}}


def case_price_tier_table():
    tier = vault_pack_picker.price_tier
    rows = [
        # No usable `_jev`: unknown, whatever the describe's flags say (Jev prices, nothing else).
        ("no jev, nothing on show", _flags(), None),
        ("no jev, toy inserted", {"penetration": "toy", "vulva_vis": "bare"}, None),
        ("not a dict", None, None),
        # A Jev row prices from `_jev` alone; free needs all three body answers "n".
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
        # A video's `_jev` is its max frame's: the clip's price.
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
    # Soles / bare toes to the camera raise it (noisy-OR, weight _EV_JEV_BOOST); not in picture damps it.
    base = p(0.5)
    assert p(0.5, soles=1.0) > base and p(0.5, toes=0.8) > base, base
    assert abs(p(0.5, soles=1.0) - (1 - 0.5 * (1 - vault_pack_picker._EV_JEV_BOOST))) < 1e-9
    assert p(0.5, detail="not_in_picture") < base


def case_jev_pick_preselect_table():
    """`jev_pick`: the rung a Jev row arrives preselected on (pack picker + AI-feet folders), else None."""
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


def case_jev_free_ok_table():
    rows = [
        ("jev safe free", {"_jev": _jev_blob()}, True),
        ("jev $10", {"_jev": _jev_blob(lane5="$10")}, False),
        ("jev review", {"_jev": _jev_blob(lane5="review")}, False),
        ("jev free, breasts y", {"_jev": _jev_blob(breasts_bare="y")}, False),
        ("jev free, crotch unsure", {"_jev": _jev_blob(crotch_bare="unsure")}, False),
        ("jev free, penetration unsure", {"_jev": _jev_blob(penetration="unsure")}, False),
        ("jev failed", {"_jev": {**_jev_blob(), "status": "error"}}, None),
        ("no jev", _flags(), None),
        ("not a dict", None, None),
    ]
    for name, fields, want in rows:
        got = vault_pack_picker.free_ok(fields)
        assert got is want, f"{name}: free_ok={got!r}, want {want!r}"
    feet = vault_pack_picker.category("feet")
    assert feet.free_rung == "tease"


async def case_candidates_jev_selects_and_ranks():
    """A Jev row is selected and ranked from `_jev` alone: a feet photo whose describe never says feet is a
    candidate; a "feet" describe Jev says has no feet is not; qwen evidence does not make a candidate."""
    c = _login(_OWNER_USER)
    seeds = {
        # Jev only: no LIKE word anywhere, Jev sees soles to the camera.
        401: {"description": "legs up on the bed", "body_focus": ["legs"],
              "_jev": _jev_blob(feet_subject=0.8, detail="bare", soles=0.9)},
        # Every qwen signal says feet, Jev says they are a bystander: no candidate.
        402: {"description": "close up of her soles", "primary_folder": "feet", "body_focus": ["feet"],
              "_jev": _jev_blob(feet_subject=0.05, detail="other_shoes")},
        # The describe says feet, Jev says not in the picture and not the subject: dropped.
        403: {"description": "standing on her feet", "body_focus": ["feet", "face"],
              "_jev": _jev_blob(feet_subject=0.02, detail="not_in_picture", seen="n")},
        # Jev free but the breasts answer is unsure: ranked, never free.
        404: {"description": "feet on the pillow", **_flags(),
              "_jev": _jev_blob(feet_subject=0.95, detail="bare", breasts_bare="unsure")},
        # A failed Jev: no candidate (waits for Jev), whatever its words say.
        405: {"description": "her feet in pink socks", "primary_folder": "feet", "body_focus": ["feet"],
              "clothing_items": ["pink socks"], **_flags(),
              "_jev": {**_jev_blob(feet_subject=0.01), "status": "error"}},
        # Malformed JSON never breaks the read.
        406: None,
        # Jev free-safe feet at .55: below FEET_PRESELECT_SCORE -> no candidate.
        407: {"description": "legs on the sofa", "_jev": _jev_blob(feet_subject=0.55)},
    }
    for mid, fields in seeds.items():
        await _seed_item(_JEV, mid, fields=fields)
    async with get_session() as s:
        row = await s.get(VaultItem, (_JEV, 406))
        row.ai_fields_json = '{"_jev": {"tags": {"feet_any": "y"'   # truncated JSON
        row.search_text = "feet"
    r = c.get("/admin/vault-ai/pack-candidates", params={"account_id": _JEV, "category": "feet"})
    assert r.status_code == 200, r.text
    by = {x["media_id"]: x for x in r.json()["candidates"]}
    order = [x["media_id"] for x in r.json()["candidates"]]
    # Precision only: the confident Jev photos and nothing else (no low Jev score, no qwen, no failed Jev).
    assert order == [404, 401], order
    assert (by[401]["suggested"], by[401]["tier"], by[401]["free_ok"], by[401]["jev"]) == ("nude", 0, True, True)
    assert by[401]["preselect"] is True, by[401]
    # Confident but the body is unknown: comes back unpicked, never free.
    assert (by[404]["suggested"], by[404]["tier"], by[404]["free_ok"], by[404]["preselect"]) == \
        (None, None, False, False), by[404]


async def case_triage_refuses_unsafe_free():
    """🚨 A Jev row whose body is not known-safe is refused on the free rung (400, nothing written); the same
    row on a paid rung, a safe Jev row and a non-Jev row on the free rung are filed."""
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
    """A video's `_jev` as `vault_jev_rules.video_blob` stores it: the max frame's photo blob + kind video."""
    return {**_jev_blob(**kw), "kind": "video", "vv": 1, "frame": 7, "frames": [], "src": "720", "review": None}


async def case_video_never_feet():
    """No clips in feet (owner, 2026-11-12): a feet video is no candidate, whatever Jev's max frame or its words
    say; filing one (or a gif) on any rung is 400 feet_photos_only and writes nothing. One filed before the rule
    still comes back on its rung and can be rejected. Its tier / free-safety still read Jev's lane (publish skip)."""
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
        assert r.json()["detail"] == {"error": "feet_photos_only", "media_ids": [420, 421]}, r.text
        assert not any((await _membership(_JEV)).values()), "a refused triage writes nothing"

    # Filed before the rule: it comes back on its rung (so it can be unfiled), and a reject is allowed.
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


async def case_publish_free_rung_skips_unsafe():
    """🚨 A row the old prefill put on the free rung before the guard: flagged in candidates and never pushed to
    the free OF list; a non-free rung is pushed whole."""
    global _armed
    await _wipe_folders(_JEV)
    c = _login(_OWNER_USER)
    assert _triage(c, [{"media_id": 401, "rung": "tease"}, {"media_id": 405, "rung": "tease"},
                       {"media_id": 404, "rung": "nude-body"}], aid=_JEV).status_code == 200
    tease = await _folder_id("feet-tease", _JEV)
    paid_id = await _folder_id("feet-nude-body", _JEV)
    async with get_session() as s:   # pre-guard: 410 (Jev review) filed free, as the old prefill could
        s.add(VaultFolderItem(account_id=_JEV, folder_id=tease, media_id=410))
        # pre photos-only: a clip on the free rung and a gif on a paid one (seeded in case_video_never_feet)
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

    # Only unsafe rows left on the free rung: refused before any OF client (the seam is disarmed).
    assert _triage(c, [{"media_id": 401, "rung": "reject"}, {"media_id": 405, "rung": "reject"}],
                   aid=_JEV).status_code == 200
    r = c.post(f"/admin/vault-ai/folders/{tease}/publish", json={"account_id": _JEV})
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == {"error": "folder_empty", "skipped_unsafe": [410], "skipped_videos": [420]}, r.text
    # Unfiling them (the picker's toggle-off) is an ordinary reject.
    assert _triage(c, [{"media_id": m, "rung": "reject"} for m in (410, 420, 421)], aid=_JEV).status_code == 200
    m = await _membership(_JEV)
    assert not {410, 420} & m["feet-tease"] and 421 not in m["feet-nude-body"], m


async def case_candidates_ranked_and_prefilled():
    c = _login(_OWNER_USER)
    unseen = {**_jev_blob(feet_subject=0.9), "tags": {"feet_any": "n", "feet_focus": "n", "feet_detail": "socks"}}
    seeds = {
        # (fields, search_text, kind)
        301: ({"description": "her feet in pink socks", "_jev": _jev_blob(feet_subject=0.95)}, None, "photo"),
        302: ({"description": "topless, toes pointed", "_jev": _jev_blob(lane5="$10", feet_subject=0.7)},
              None, "photo"),
        # .5 + soles to the camera -> .65: in, on the bare rung.
        303: ({"description": "legs up", "_jev": _jev_blob(feet_subject=0.5, soles=1.0, detail="bare")},
              None, "photo"),
        # .59: out (precision only, no lower-scored suggestion).
        304: ({"description": "feet on the sofa", "_jev": _jev_blob(feet_subject=0.59)}, "feet", "photo"),
        # Every word says feet, no Jev yet: out, it waits for Jev.
        305: ({"description": "close up of her soles", "primary_folder": "feet", "body_focus": ["feet"],
               **_flags()}, "barefoot feet soles", "photo"),
        # A confident feet clip: out (no videos in feet).
        306: ({"description": "her feet", "_jev": _video_jev(feet_subject=0.95)}, "feet", "video"),
        # Jev scores feet high but does not see them (no seen tag): out.
        307: ({"description": "feet", "_jev": unseen}, "feet", "photo"),
        # Confident, body unsure: in, unpicked.
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
    assert order == [301, 308, 302, 303], order
    by = {x["media_id"]: x for x in body["candidates"]}
    assert (by[301]["suggested"], by[301]["tier"], by[301]["preselect"]) == ("tease", 0, True), by[301]
    assert (by[302]["suggested"], by[302]["tier"], by[302]["preselect"]) == ("nude-body", 10, True), by[302]
    assert (by[303]["suggested"], by[303]["score"]) == ("nude", 0.65), by[303]
    assert (by[308]["suggested"], by[308]["preselect"], by[308]["free_ok"]) == (None, False, False), by[308]
    assert all(x["jev"] and x["kind"] == "photo" for x in body["candidates"]), body["candidates"]
    scores = [x["score"] for x in body["candidates"]]
    assert scores == sorted(scores, reverse=True) and min(scores) >= vault_pack_picker.FEET_PRESELECT_SCORE, scores

    # A capped scan is deterministic: the newest (highest) ids, every call (304 is scanned, then gated out).
    real_cap = vault_pack_picker._SCAN_CAP
    vault_pack_picker._SCAN_CAP = 2
    try:
        capped = [sorted(x["media_id"] for x in get()["candidates"]) for _ in range(3)]
    finally:
        vault_pack_picker._SCAN_CAP = real_cap
    assert capped == [[308]] * 3, capped

    # File the top one: it leaves the queue's limit and comes back after it. Items filed before the
    # precision rule (a no-Jev photo, a below-gate photo, a clip) come back too, never in the queue.
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
    # 101, 102: confident Jev feet photos (seen, score >= FEET_PRESELECT_SCORE).
    await _seed_item(_AID, 101, search_text="barefoot feet soles on the bed",
                     fields={"description": "barefoot on the bed", "_jev": _jev_blob(feet_subject=0.9, detail="bare")})
    await _seed_item(_AID, 102, fields={"description": "legs crossed on the sofa", "_jev": _jev_blob(feet_subject=0.8)})
    # 103: every word says feet, Jev has not classified it — must never appear as a candidate.
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
    case_candidates_jev_selects_and_ranks,
    case_triage_refuses_unsafe_free,
    case_video_never_feet,
    case_publish_free_rung_skips_unsafe,
)
