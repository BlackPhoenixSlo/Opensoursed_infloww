#!/usr/bin/env python3
"""
Permanent vault stills — `/admin/vault-ai/{thumb,image,poster}`.
Plain-assert, no pytest (repo convention).

Why this suite exists: OF CDN urls carry a time-signed Policy that stops
resolving after a couple of days. The mirror stores the url that was valid at
COLLECT time, so a tile whose bytes aren't already on disk had no way back —
the fetch 403'd and the tile stayed blank forever. These routes now re-ask OF
for the one media id, which returns a freshly signed url set, and retry once.

The retry has to be BOUNDED, or a media OF has actually deleted costs two doomed
OF calls on every render of the grid it sits in, for ever. That is what the
`gone` cases pin.

Cases:
  case_disk_hit_never_touches_of  — bytes on disk ⇒ served without an OF client.
  case_expired_url_resigns        — stored url 403s ⇒ re-signed via
                                    vault_media_by_id, bytes land on disk, and
                                    the mirror row is rewritten with the fresh
                                    url so the NEXT miss starts from a live one.
  case_resign_only_once           — the second read is a pure disk hit: no
                                    further OF traffic at all.
  case_gone_media_is_remembered   — OF 404s the id ⇒ the row is stamped
                                    `removed_at` and the response is `media_gone`.
  case_gone_media_costs_nothing   — …and EVERY later request short-circuits on
                                    that stamp: no client, no OF call at all.
  case_transient_failure_retries  — a non-404 failure must NOT be remembered —
                                    the row stays live and the next call retries.
  case_a_recollect_lifts_the_…    — seeing the media again CLEARS `removed_at`.
                                    The stamp is written from a GET, so without
                                    this a 404 for any reason other than deletion
                                    hid the media from every query that filters
                                    `removed_at IS NULL`, permanently.
  case_an_uncollected_media_…     — a media that was never collected resolves by
                                    id. The route used to take the url to fetch
                                    as a `u=` param, making it a fetch-any-url
                                    proxy behind a host-substring check.
  case_a_non_image_body_is_…      — a 200 carrying an mp4 or an HTML interstitial
                                    is never written to `{id}.jpg`; a disk hit
                                    short-circuits, so caching one is forever.
  case_audio_is_not_offered_a_thu… — the mirror projection stamps `_thumb` only
                                    for a kind that HAS a still, so a voice note
                                    reaches the browser with nothing to request
                                    and no tile has to know why.
  case_audio_never_asks_of_for_a_… — a voice note has NO frame: `full` is the
                                    audio, so the ladder used to download the
                                    MP3, fail the magic, re-sign and download it
                                    again before 404ing — twice per paint, for
                                    17.6% of a vault. It answers `no_variant`
                                    with no OF call, and does not soft-delete.
  case_poster_frame_resigns       — the video hover frames take the same path.
  case_refresh_keeps_derived_cols — a re-sign rewrites raw_json and the columns
                                    DERIVED from it together (of_folder_ids), so
                                    the blob and its projections can't drift —
                                    and does NOT touch describe/AI output.
  case_a_removed_still_refills    — a still gone from disk is re-fetched on
                                    the next read.
  case_owner_auth_403             — a non-owner is 403 on every route.
  case_cold_pane_is_capped        — 40 tiles asked for at once put at most
                                    _MAX_INFLIGHT_FETCHES in flight. An
                                    AI-folder lane runs to 569 items and every
                                    one is a miss on a cold store; uncapped that
                                    is an fd per tile and the PROCESS runs out
                                    (sqlite "unable to open database file",
                                    scandir EMFILE) — observed on prod
                                    2026-07-28.
  case_same_media_collapses       — …and N requests for the SAME media don't
                                    each pay a round-trip: whoever wins the slot
                                    writes the bytes, the rest re-check the disk
                                    under the slot and find them.

The DESCRIBE sweep reads these same stores through `vault_frames.collect`, and
until 2026-08-04 it did not: it fetched the url the collect had stored, with no
disk read and no re-sign, so a sweep 31 hours behind its collect recorded 979
photos as un-renderable while their bytes sat in IMAGE_DIR. The remaining cases
pin that ladder — the STATUS each outcome becomes lives in test_vault_ai_describe.

  case_describe_photo_reads_the_disk_store
                                  — THE incident: signature dead, bytes on disk
                                    ⇒ frames, and OF is never called.
  case_describe_photo_uses_the_full_frame_not_the_crop
                                  — a warm THUMB must not satisfy a describe: the
                                    300px centre-crop is what made the model
                                    over-report `fully_nude`.
  case_describe_photo_resigns_when_cold
                                  — cold store + dead url ⇒ one re-sign, and the
                                    bytes are kept so the next pass is free.
  case_describe_photo_transient_is_not_no_variant
                                  — OF unreachable ⇒ `fetch_failed`. Recording it
                                    as un-renderable is what cooled 1,777 items
                                    off for 7 days.
  case_collect_never_raises_at_its_callers
                                  — a fault it cannot classify, and a hang, both
                                    come back as `fetch_failed`. Raising ends the
                                    sweep that called it and stamps no row.
  case_describe_photo_no_renderable_variant
                                  — OF answered with nothing renderable ⇒
                                    `no_variant`, which DOES keep the cool-off.
  case_describe_photo_gone_is_gone — OF 404 ⇒ `gone` + soft-delete.
  case_unwarmed_video_warms_from_the_resigned_url
                                  — the clip half: the storyboard key comes from
                                    the url, so a re-signed mp4 must be warmed AND
                                    read back under the FRESH key.
  case_a_download_that_failed_is_retryable
                                  — `dl_fail`/`error` from the warmer are the
                                    source being there and missed ⇒ retryable.
  case_deleted_video_is_gone_not_fetch_failed
                                  — the CLIP half of `gone`. Its own case because
                                    the photo path reads the verdict straight off
                                    `bytes_for`, while a video reaches it through
                                    `resolve_fresh` — a second route to the same
                                    two outcomes, and the one that used to
                                    re-derive them with an extra DB read.

Run: cd service/tests && \
  PYTHONPATH=$(cd .. && pwd) ../../venv/bin/python test_vault_stills.py
Exit 0 = all cases passed. Temp DB bound by _harness (never prod).
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

import accounts as account_registry  # noqa: E402
import automation_executor as ax  # noqa: E402 — the OF-client seam
import server  # noqa: E402
import vault_frames  # noqa: E402 — its ladder reads these same stores
import vault_mirror  # noqa: E402 — the collect mapping the seeder reuses
import vault_stills as vs  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, User, UserAccount, VaultItem  # noqa: E402
from vault_frames import poster_frames as _video_poster_frames  # noqa: E402

_TEST_ACCOUNTS = {"acc_owner", "acc_foreign"}
_orig_get_account = account_registry.get_account
_orig_list_accounts = account_registry.list_accounts
account_registry.get_account = (
    lambda a: ({"id": a, "nickname": a} if a in _TEST_ACCOUNTS else _orig_get_account(a))
)
account_registry.list_accounts = (
    lambda: [{"id": a, "nickname": a} for a in sorted(_TEST_ACCOUNTS)]
)
# The isolation middleware asks per-candidate (one stat, no descriptor).
account_registry.is_account = lambda aid: aid in _TEST_ACCOUNTS

_AID = "acc_owner"
_FOREIGN = "acc_foreign"
_OWNER_USER = "stills_owner"
_STRANGER_USER = "stills_stranger"

_JPEG = b"\xff\xd8\xff\xe0fake-jpeg-bytes\xff\xd9"

# Redirect the three on-disk stores into a temp tree for the whole run. The path
# builders read these at call time, so assigning them is enough.
_TMP = Path(tempfile.mkdtemp(prefix="vault-stills-test-"))
vs.THUMB_DIR = _TMP / "thumbs"
vs.IMAGE_DIR = _TMP / "images"
vs.POSTER_DIR = _TMP / "posters"


# ── Fake OF ─────────────────────────────────────────────────────────
#
# `live` is the set of urls that currently resolve. An EXPIRED url is simply
# one that isn't in it — exactly what an aged-out Policy looks like from here:
# a non-200, never an exception.

class _FakeResp:
    def __init__(self, status: int, content: bytes = b""):
        self.status_code = status
        self.content = content


class _FakeHTTP:
    def __init__(self, of: "_FakeOF"):
        self._of = of

    def get(self, url: str, timeout: float | None = None, **_kw):  # noqa: ANN001
        self._of.gets.append(url)
        if url in self._of.live:
            # `bodies` overrides what a live url yields, so a case can model OF
            # answering 200 with something that is not a picture.
            return _FakeResp(200, self._of.bodies.get(url, _JPEG))
        return _FakeResp(403)


class _OFError(Exception):
    """Shaped like of_client.OFAPIError — the status on `.response` is the only
    thing that separates 'deleted for good' from 'try again later'."""
    def __init__(self, status: int):
        super().__init__(f"{status} for /vault/media")
        self.response = _FakeResp(status)


class _FakeOF:
    def __init__(self):
        self.timeout_s = 5.0
        self.http = _FakeHTTP(self)
        self.live: set[str] = set()
        self.bodies: dict[str, bytes] = {}
        self.gets: list[str] = []
        self.byid_calls: list[int] = []
        self.byid: dict[int, dict] = {}
        # Status raised for an id with no entry in `byid`: 404 = OF deleted it,
        # anything else = transient.
        self.byid_status = 404
        self.clients_made = 0

    def vault_media_by_id(self, media_id: int) -> dict:
        self.byid_calls.append(int(media_id))
        m = self.byid.get(int(media_id))
        if m is None:
            raise _OFError(self.byid_status)
        return m

    def reset(self) -> None:
        self.gets.clear()
        self.byid_calls.clear()
        self.bodies.clear()
        self.clients_made = 0


_OF = _FakeOF()


def _make_client(_aid: str, *_a, **_k):  # noqa: ANN001
    _OF.clients_made += 1
    return _OF


ax._make_client = _make_client  # type: ignore[assignment]


def _files(sig: str) -> dict:
    """A media `files` block signed with `sig` — bump the sig to model a re-sign."""
    base = f"https://cdn3.onlyfans.com/files/x/{{}}.jpg?Policy={sig}"
    return {
        "thumb": {"url": base.format("thumb")},
        "preview": {"url": base.format("preview")},
        "full": {"url": base.format("full")},
    }


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


async def _seed_media(aid: str, media_id: int, raw: dict, kind: str = "photo",
                      of_folder_ids: str = "[]") -> None:
    files = raw.get("files") or {}
    async with get_session() as s:
        existing = await s.get(VaultItem, (aid, media_id))
        if existing is not None:
            await s.delete(existing)
            await s.flush()
        s.add(VaultItem(
            account_id=aid, media_id=media_id, kind=kind,
            created_at=datetime.utcnow(),
            # Through the real collect mapping, not `files["thumb"]` — identical
            # for a photo, and the reason an AUDIO row carries the AUDIO url in
            # its thumb column, which is the shape the audio case has to model.
            thumb_url=vault_mirror.thumb_of(files),
            raw_json=json.dumps(raw),
            of_folder_ids=of_folder_ids,
        ))


async def _item(aid: str, media_id: int) -> VaultItem:
    async with get_session() as s:
        return await s.get(VaultItem, (aid, media_id))


def _login(username: str) -> TestClient:
    c = TestClient(server.app)
    r = c.post("/auth/login", json={"username": username, "password": "secretpw"})
    assert r.status_code == 200, f"login {username!r} failed: {r.status_code} {r.text}"
    return c


def _clear_disk() -> None:
    for d in (vs.THUMB_DIR, vs.IMAGE_DIR, vs.POSTER_DIR):
        shutil.rmtree(d, ignore_errors=True)


# ── Cases ───────────────────────────────────────────────────────────

async def case_disk_hit_never_touches_of():
    _clear_disk()
    _OF.reset()
    await _seed_media(_AID, 101, {"id": 101, "type": "photo", "files": _files("OLD")})
    p = vs.thumb_path(_AID, 101)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(_JPEG)

    c = _login(_OWNER_USER)
    r = c.get("/admin/vault-ai/thumb", params={"account_id": _AID, "media_id": 101})
    assert r.status_code == 200, r.text
    assert r.content == _JPEG, "disk bytes not served verbatim"
    assert _OF.clients_made == 0, "a disk hit must not construct an OF client"
    assert _OF.gets == [], _OF.gets


async def case_expired_url_resigns():
    _clear_disk()
    _OF.reset()
    old = _files("EXPIRED")
    new = _files("FRESH")
    await _seed_media(_AID, 202, {"id": 202, "type": "photo", "files": old})
    # Only the re-signed urls resolve — the stored ones are dead.
    _OF.live = {f["url"] for f in new.values()}
    _OF.byid = {202: {"id": 202, "type": "photo", "files": new}}

    c = _login(_OWNER_USER)
    r = c.get("/admin/vault-ai/thumb", params={"account_id": _AID, "media_id": 202})
    assert r.status_code == 200, f"expired url should self-heal, got {r.status_code} {r.text}"
    assert r.content == _JPEG, "re-signed bytes not returned"
    assert _OF.byid_calls == [202], f"expected exactly one by-id re-sign, got {_OF.byid_calls}"
    # Bytes are now permanent…
    assert vs.thumb_path(_AID, 202).read_bytes() == _JPEG, "re-signed bytes not persisted"
    # …and the mirror carries the live url, so the next miss starts from a good one.
    row = await _item(_AID, 202)
    assert row.thumb_url == new["thumb"]["url"], f"mirror url not refreshed: {row.thumb_url}"
    assert json.loads(row.raw_json)["files"]["thumb"]["url"] == new["thumb"]["url"]


async def case_resign_only_once():
    # Continues from the row healed above: the second read is pure disk.
    _OF.reset()
    c = _login(_OWNER_USER)
    r = c.get("/admin/vault-ai/thumb", params={"account_id": _AID, "media_id": 202})
    assert r.status_code == 200, r.text
    assert _OF.gets == [] and _OF.byid_calls == [], (
        f"second read must not touch OF: gets={_OF.gets} byid={_OF.byid_calls}"
    )


async def case_gone_media_is_remembered():
    _clear_disk()
    _OF.reset()
    await _seed_media(_AID, 303, {"id": 303, "type": "photo", "files": _files("EXPIRED")})
    _OF.live = set()
    _OF.byid = {}                # deleted at OF ⇒ by-id raises…
    _OF.byid_status = 404        # …with a 404: gone for good, not a hiccup.

    c = _login(_OWNER_USER)
    r = c.get("/admin/vault-ai/thumb", params={"account_id": _AID, "media_id": 303})
    assert r.status_code == 404, f"expected 404 for unrecoverable media, got {r.status_code}"
    assert r.json()["detail"] == "media_gone", r.json()
    assert not vs.thumb_path(_AID, 303).exists(), "nothing may be written on a failed fetch"
    row = await _item(_AID, 303)
    assert row.removed_at is not None, "a media OF 404s must be stamped removed_at"


async def case_gone_media_costs_nothing():
    # THE point of the stamp: the second render of a dead tile is free. Without
    # this the grid pays a doomed thumb fetch AND a doomed by-id, per tile, per
    # paint, for ever.
    _OF.reset()
    c = _login(_OWNER_USER)
    r = c.get("/admin/vault-ai/thumb", params={"account_id": _AID, "media_id": 303})
    assert r.status_code == 404, r.status_code
    assert r.json()["detail"] == "media_gone", r.json()
    assert _OF.clients_made == 0, "a known-gone media must not construct an OF client"
    assert _OF.gets == [] and _OF.byid_calls == [], (
        f"known-gone media still hit OF: gets={_OF.gets} byid={_OF.byid_calls}")


async def case_transient_failure_retries():
    # A 500 is NOT evidence the media is gone. Remembering it would blank a tile
    # permanently over one bad minute at OF.
    _clear_disk()
    _OF.reset()
    fresh = _files("FRESH")
    await _seed_media(_AID, 314, {"id": 314, "type": "photo", "files": _files("EXPIRED")})
    _OF.live = set()
    _OF.byid = {}
    _OF.byid_status = 502

    c = _login(_OWNER_USER)
    r = c.get("/admin/vault-ai/thumb", params={"account_id": _AID, "media_id": 314})
    assert r.status_code == 404, r.status_code
    assert r.json()["detail"] == "fetch_failed", r.json()
    row = await _item(_AID, 314)
    assert row.removed_at is None, "a transient failure must NOT be remembered as gone"

    # OF recovers → the very next call heals the tile.
    _OF.byid_status = 404
    _OF.live = {f["url"] for f in fresh.values()}
    _OF.byid = {314: {"id": 314, "type": "photo", "files": fresh}}
    r = c.get("/admin/vault-ai/thumb", params={"account_id": _AID, "media_id": 314})
    assert r.status_code == 200, f"retry after a transient failure should heal: {r.text}"
    assert vs.thumb_path(_AID, 314).exists(), "healed bytes not persisted"


async def case_refresh_keeps_derived_cols():
    # raw_json and the columns derived FROM it have to move together. They used to
    # be written by two different hand-rolled update sets, so a re-sign refreshed
    # the blob and left of_folder_ids pointing at the previous listStates.
    _clear_disk()
    _OF.reset()
    fresh = _files("FRESH")
    await _seed_media(
        _AID, 606, {"id": 606, "type": "photo", "files": _files("EXPIRED"),
                    "listStates": [{"id": 11, "type": "custom", "hasMedia": True}]},
        of_folder_ids="[11]")
    _OF.live = {f["url"] for f in fresh.values()}
    _OF.byid = {606: {"id": 606, "type": "photo", "files": fresh,
                      "listStates": [{"id": 22, "type": "custom", "hasMedia": True}]}}

    # The other half of the same contract: the refresh list names what a re-sign
    # OVERWRITES, so anything the AI or an operator concluded must be absent from
    # it. Seeing a media again says nothing about how it was graded, and a re-sign
    # that quietly reset a graded item is indistinguishable from never having
    # graded it — the grid would just show work that silently needs redoing.
    async with get_session() as s:
        row = await s.get(VaultItem, (_AID, 606))
        row.description = "she is on the balcony at golden hour"
        row.tags = '["balcony","solo"]'
        row.search_text = "balcony solo golden hour"
        await s.commit()

    c = _login(_OWNER_USER)
    assert c.get("/admin/vault-ai/thumb",
                 params={"account_id": _AID, "media_id": 606}).status_code == 200
    row = await _item(_AID, 606)
    assert json.loads(row.raw_json)["listStates"][0]["id"] == 22, "raw_json not refreshed"
    assert json.loads(row.of_folder_ids) == [22], (
        f"of_folder_ids drifted from the blob it is derived from: {row.of_folder_ids}")
    assert row.description == "she is on the balcony at golden hour", (
        "a re-sign overwrote the describe output — refreshing a url must not "
        "discard what the model concluded")
    assert json.loads(row.tags) == ["balcony", "solo"], f"tags reset by a re-sign: {row.tags}"
    assert row.search_text == "balcony solo golden hour", (
        f"search_text reset by a re-sign: {row.search_text!r}")


async def case_a_recollect_lifts_the_soft_delete():
    # `removed_at` had no writer of None anywhere in the repo, so the stamp was
    # one-way. That matters because `serve` writes it from a GET: one 404 on a
    # by-id read — an expired signature, or a session pointed at the wrong OF
    # user — buried the media in every query that filters `removed_at IS NULL`
    # (grid, picker, describe sweep, PPV lineup, catalog seed), and because
    # `serve` then short-circuits on the stamp, the render path could never
    # retry it either. Only a re-collect can heal it, so this pins that it does.
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert  # noqa: PLC0415

    import vault_mirror  # noqa: PLC0415

    await _seed_media(_AID, 707, {"id": 707, "type": "photo", "files": _files("EXPIRED")})
    async with get_session() as s:
        buried = await s.get(VaultItem, (_AID, 707))
        buried.removed_at = datetime.utcnow()
        await s.commit()
    assert (await _item(_AID, 707)).removed_at is not None, "seed did not bury the row"

    # Exactly what the collect sweep does when OF pages this media back to us.
    vals = vault_mirror.row_values(_AID, {"id": 707, "type": "photo", "files": _files("FRESH")}, 1)
    refresh = {k: vals[k] for k in vault_mirror.MIRROR_REFRESH_FIELDS + ("last_seen_run_id",)}
    async with get_session() as s:
        await s.execute(
            sqlite_insert(VaultItem).values(**vals).on_conflict_do_update(
                index_elements=["account_id", "media_id"], set_=refresh))
        await s.commit()

    assert (await _item(_AID, 707)).removed_at is None, (
        "OF handed this media back, so it is not removed — a re-collect must lift "
        "the stamp, or a bad 404 hides the media until someone writes SQL by hand")


async def case_an_uncollected_media_resolves_by_id():
    # The route used to take the url to fetch as a `u=` query param, so a hover
    # over a never-collected clip could still fill the store. That made every
    # render endpoint fetch whatever host the caller named, behind a check that
    # accepted any hostname containing both "cdn" and "onlyfans" — so
    # cdn.onlyfans.attacker.com passed, fetched with the account's own
    # authenticated client. It also earned nothing: a media with no stored url
    # lands in the SAME re-sign branch a stale url lands in.
    _clear_disk()
    _OF.reset()
    fresh = _files("FRESH")
    async with get_session() as s:                      # deliberately NOT seeded
        assert await s.get(VaultItem, (_AID, 808)) is None, "808 must be uncollected"
    _OF.live = {f["url"] for f in fresh.values()}
    _OF.byid = {808: {"id": 808, "type": "photo", "files": fresh}}

    c = _login(_OWNER_USER)
    r = c.get("/admin/vault-ai/thumb", params={"account_id": _AID, "media_id": 808})
    assert r.status_code == 200, f"uncollected media should resolve by id: {r.text}"
    assert r.content == _JPEG, "resolved bytes not returned"
    assert _OF.byid_calls == [808], f"expected exactly one by-id read: {_OF.byid_calls}"
    assert vs.thumb_path(_AID, 808).exists(), "resolved bytes not persisted"


async def case_a_non_image_body_is_never_cached():
    # A 200 is not proof of a picture. OF answers a wrong-variant url with a
    # perfectly good 200 carrying an MP4, and an edge in front of it can answer
    # with an HTML interstitial. Both used to be written to {media_id}.jpg and
    # served back as image/jpeg — permanently, because a disk hit short-circuits
    # before any re-sign logic runs.
    _clear_disk()
    _OF.reset()
    stale, fresh = _files("EXPIRED"), _files("FRESH")
    await _seed_media(_AID, 909, {"id": 909, "type": "photo", "files": stale})
    # The stored url resolves — but yields a video, not a still.
    _OF.live = {stale["thumb"]["url"]}
    _OF.bodies = {stale["thumb"]["url"]: b"\x00\x00\x00\x20ftypmp42" + b"\x00" * 64}
    _OF.byid = {}
    _OF.byid_status = 502          # re-sign unavailable ⇒ the call must FAIL…

    c = _login(_OWNER_USER)
    r = c.get("/admin/vault-ai/thumb", params={"account_id": _AID, "media_id": 909})
    assert r.status_code == 404, f"an mp4 body must not be served as an image: {r.text}"
    assert not vs.thumb_path(_AID, 909).exists(), (
        "a non-image body was cached as .jpg — every later render serves it from "
        "disk without ever re-checking")
    assert (await _item(_AID, 909)).removed_at is None, "a bad body is not a deletion"

    # …and the SAME url yielding real bytes still works, so the guard rejects the
    # body, not the url.
    _OF.reset()
    _OF.live = {f["url"] for f in fresh.values()}
    _OF.byid = {909: {"id": 909, "type": "photo", "files": fresh}}
    r = c.get("/admin/vault-ai/thumb", params={"account_id": _AID, "media_id": 909})
    assert r.status_code == 200, f"real bytes should still heal the tile: {r.text}"
    assert r.content == _JPEG


async def case_audio_never_asks_of_for_a_picture():
    # The backstop behind the case above. Nothing renders a `_thumb` for a voice
    # note any more, but five surfaces build a stills url from an id alone
    # (`mirrorThumbSrc`, `mirrorFullSrc`, the legacy panes) and cannot know the
    # kind. Unguarded, each one costs what the projection used to: `thumb_of`
    # hands the ladder the MP3, it downloads it, fails the image magic (the case
    # above), re-signs, downloads it AGAIN and 404s — two OF calls and one of six
    # in-flight slots, per tile, per paint, for ever.
    _clear_disk()
    _OF.reset()
    # One variant, and no extension on the path — OF's vault urls carry none, so
    # nothing downstream can tell what this is from the url alone.
    stale = "https://cdn3.onlyfans.com/files/x/0gwnzeh3cf8dgfj70262?Policy=OLD"
    fresh = "https://cdn3.onlyfans.com/files/x/0gwnzeh3cf8dgfj70262?Policy=NEW"
    raw = {"id": 4041, "type": "audio", "files": {"full": {"url": stale}}}
    await _seed_media(_AID, 4041, raw, kind="audio")
    # Everything OF could offer, offered: the stored url RESOLVES and the re-sign
    # WORKS and hands back a different, live url. Neither can help, because what
    # comes back either way is audio — which is what makes the ladder cost TWO
    # downloads plus a by-id and still end in a 404.
    _mp3 = b"ID3\x03\x00\x00\x00" + b"\x00" * 64
    _OF.live = {stale, fresh}
    _OF.bodies = {stale: _mp3, fresh: _mp3}
    _OF.byid = {4041: {"id": 4041, "type": "audio", "files": {"full": {"url": fresh}}}}

    c = _login(_OWNER_USER)
    r = c.get("/admin/vault-ai/thumb", params={"account_id": _AID, "media_id": 4041})
    assert r.status_code == 404, r.status_code
    assert r.json()["detail"] == "no_variant", r.json()
    assert _OF.clients_made == 0, "audio must not even construct an OF client"
    # RED, with `has_still` off: gets=2 byid=1 — the MP3 downloaded, the media
    # re-signed, the MP3 downloaded AGAIN, then 404. Every paint.
    assert _OF.gets == [] and _OF.byid_calls == [], (
        f"audio still went to OF: gets={_OF.gets} byid={_OF.byid_calls}")
    assert not vs.thumb_path(_AID, 4041).exists(), "nothing renderable to write"
    # The media is FINE — it just has no picture. Stamping it `removed_at` would
    # hide the voice note from every query that filters on it.
    assert (await _item(_AID, 4041)).removed_at is None, "audio is not deleted media"

    # The full-frame store takes the same verdict — the review UI asks for it.
    _OF.reset()
    r = c.get("/admin/vault-ai/image", params={"account_id": _AID, "media_id": 4041})
    assert r.status_code == 404, r.status_code
    assert r.json()["detail"] == "no_variant", r.json()
    assert _OF.gets == [] and _OF.byid_calls == [], (
        f"audio still went to OF: gets={_OF.gets} byid={_OF.byid_calls}")


async def case_audio_is_not_offered_a_thumb_url():
    # `_thumb` is the browser's WHOLE answer to "is there a picture": every tile
    # surface renders it and asks nothing else. It used to be stamped on every
    # mirror row with no kind branch, which is an instruction to fetch a picture
    # that cannot exist — 592 of them fleet-wide. The projection now asks
    # `vault_mirror.has_still` first, so a voice note simply arrives without one
    # and the tile renders its type instead. No client-side kind check needed.
    _clear_disk()
    _OF.reset()
    await _seed_media(_AID, 4101, {"id": 4101, "type": "photo", "files": _files("OK")})
    await _seed_media(_AID, 4102, {"id": 4102, "type": "audio",
                                   "files": {"full": {"url": "https://cdn3.onlyfans.com/files/x/voice"}}},
                      kind="audio")

    c = _login(_OWNER_USER)
    r = c.get("/admin/vault-ai/items", params={"account_id": _AID, "limit": 100})
    assert r.status_code == 200, r.text
    by_id = {int(it["id"]): it for it in r.json()["list"]}
    assert "_thumb" in by_id[4101], "a photo must still be offered its cached thumb"
    assert "_thumb" not in by_id[4102], (
        f"a voice note was offered a thumb url it can never satisfy: {by_id[4102].get('_thumb')}")
    assert _OF.gets == [] and _OF.byid_calls == [], "listing the mirror must not touch OF"


async def case_poster_frame_resigns():
    _clear_disk()
    _OF.reset()

    def _vid(sig: str) -> dict:
        files = _files(sig)
        # OF hangs the pre-extracted poster frames off `files.preview.options[]`.
        files["preview"] = {
            "url": files["preview"]["url"],
            "options": [
                {"url": f"https://cdn3.onlyfans.com/files/x/f{i}.jpg?Policy={sig}"}
                for i in range(3)
            ],
        }
        return {"id": 404, "type": "video", "files": files, "videoSources": {}}

    old, new = _vid("EXPIRED"), _vid("FRESH")
    frames_new = _video_poster_frames(new)
    assert len(frames_new) >= 3, f"fixture must expose poster frames, got {frames_new}"
    await _seed_media(_AID, 404, old, kind="video")
    _OF.live = set(frames_new)
    _OF.byid = {404: new}

    c = _login(_OWNER_USER)
    r = c.get("/admin/vault-ai/poster", params={"account_id": _AID, "media_id": 404, "i": 2})
    assert r.status_code == 200, f"poster frame should self-heal: {r.status_code} {r.text}"
    assert r.content == _JPEG, "re-signed poster bytes not returned"
    assert vs.poster_path(_AID, 404, 2).read_bytes() == _JPEG, "poster not persisted"


async def case_a_removed_still_refills():
    _clear_disk()
    _OF.reset()
    fresh = _files("FRESH")
    await _seed_media(_AID, 505, {"id": 505, "type": "photo", "files": fresh})
    _OF.live = {f["url"] for f in fresh.values()}
    _OF.byid = {505: {"id": 505, "type": "photo", "files": fresh}}

    c = _login(_OWNER_USER)
    assert c.get("/admin/vault-ai/thumb", params={"account_id": _AID, "media_id": 505}).status_code == 200
    assert vs.thumb_path(_AID, 505).read_bytes() == _JPEG, "thumb not written to disk"

    vs.thumb_path(_AID, 505).unlink()
    _OF.reset()
    r = c.get("/admin/vault-ai/thumb", params={"account_id": _AID, "media_id": 505})
    assert r.status_code == 200, r.text
    assert vs.thumb_path(_AID, 505).exists(), "re-fetch after removal did not repopulate"


async def case_owner_auth_403():
    c = _login(_STRANGER_USER)   # owns acc_foreign, NOT acc_owner
    for path, params in (
        ("/admin/vault-ai/thumb", {"account_id": _AID, "media_id": 101}),
        ("/admin/vault-ai/image", {"account_id": _AID, "media_id": 101}),
        ("/admin/vault-ai/poster", {"account_id": _AID, "media_id": 404, "i": 0}),
    ):
        r = c.get(path, params=params)
        assert r.status_code == 403, f"{path} → {r.status_code}, expected 403"


async def _seed_fixtures():
    owner_uid = await _seed_user(_OWNER_USER)
    stranger_uid = await _seed_user(_STRANGER_USER)
    await _seed_account(_AID, owner_uid)
    await _seed_account(_FOREIGN, stranger_uid)


def _pick_thumb_url(m: dict) -> str | None:
    return ((m.get("files") or {}).get("thumb") or {}).get("url")


class _ConcurrencyMeter:
    """Wraps the fake's `get` to record how many fetches overlap.

    The fetch runs under `asyncio.to_thread`, so the counter is guarded by a
    real lock — this measures actual thread overlap, not scheduling intent.
    """

    def __init__(self, inner):  # noqa: ANN001
        self._inner = inner
        self._lock = threading.Lock()
        self.live = 0
        self.peak = 0

    def get(self, url: str, timeout: float | None = None, **kw):  # noqa: ANN001
        with self._lock:
            self.live += 1
            self.peak = max(self.peak, self.live)
        try:
            # Long enough that anything allowed to overlap actually does — a
            # cap that "passes" because the work finished too fast to collide
            # proves nothing.
            time.sleep(0.03)
            return self._inner.get(url, timeout=timeout, **kw)
        finally:
            with self._lock:
                self.live -= 1


async def case_cold_pane_is_capped():
    _clear_disk()
    _OF.reset()
    files = _files("LIVE")
    _OF.live = {f["url"] for f in files.values()}
    ids = list(range(9000, 9040))
    for mid in ids:
        await _seed_media(_AID, mid, {"id": mid, "type": "photo", "files": files})

    meter = _ConcurrencyMeter(_OF.http)
    real_http, _OF.http = _OF.http, meter
    try:
        results = await asyncio.gather(*[
            vs.serve(_AID, mid, vs.thumb_path(_AID, mid), _pick_thumb_url)
            for mid in ids
        ])
    finally:
        _OF.http = real_http

    assert all(r.status_code == 200 for r in results), "a capped fetch must still serve"
    assert meter.peak <= vs._MAX_INFLIGHT_FETCHES, (
        f"{len(ids)} tiles put {meter.peak} fetches in flight; "
        f"cap is {vs._MAX_INFLIGHT_FETCHES} — the fd guard is not holding"
    )
    # The cap must throttle, not serialise: a 1-at-a-time path would make a
    # 569-tile lane unusable, which is how a "fix" gets reverted.
    assert meter.peak > 1, "the cap collapsed to a serial queue"
    for mid in ids:
        assert vs.thumb_path(_AID, mid).is_file(), f"{mid} not persisted"


async def case_same_media_collapses():
    _clear_disk()
    _OF.reset()
    files = _files("LIVE")
    _OF.live = {f["url"] for f in files.values()}
    await _seed_media(_AID, 9100, {"id": 9100, "type": "photo", "files": files})

    meter = _ConcurrencyMeter(_OF.http)
    real_http, _OF.http = _OF.http, meter
    try:
        results = await asyncio.gather(*[
            vs.serve(_AID, 9100, vs.thumb_path(_AID, 9100), _pick_thumb_url)
            for _ in range(25)
        ])
    finally:
        _OF.http = real_http

    assert all(r.status_code == 200 for r in results), "every caller must get the bytes"
    # The slot-holders that raced through the disk re-check together each fetch;
    # everyone behind them finds the file written. So the ceiling is the cap,
    # never the request count.
    assert len(_OF.gets) <= vs._MAX_INFLIGHT_FETCHES, (
        f"25 requests for ONE media made {len(_OF.gets)} OF calls — "
        f"the under-slot disk re-check isn't collapsing them"
    )


# ── The describe sweep reads the same stores ────────────────────────
#
# 2026-08-04: a describe sweep stamped 979 photos `blocked_drm` while 1,906 of
# their pictures sat in IMAGE_DIR. `_collect_images` fetched the url the collect
# had stored — signed ~24h, sweep ran 31h later — with no disk read and no
# re-sign, i.e. none of the ladder this module exists to be. These cases pin the
# fetch contract at `_collect_images` itself; the status it turns into is pinned
# in test_vault_ai_describe.

async def case_describe_photo_reads_the_disk_store():
    """THE incident. Stored url dead, bytes on disk ⇒ described, OF untouched."""
    _clear_disk()
    _OF.reset()
    _OF.live = set()          # every stored signature has aged out
    _OF.byid = {}
    await _seed_media(_AID, 8801, {"id": 8801, "type": "photo", "files": _files("EXPIRED")})
    p = vs.image_path(_AID, 8801)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(_JPEG)

    item = await _item(_AID, 8801)
    got = await vault_frames.collect(
        _AID, item, json.loads(item.raw_json), want=1)
    assert got.reason == "ok", got.reason
    assert len(got.images) == 1, got.images
    assert got.images[0].startswith("data:image/jpeg;base64,"), got.images[0][:40]
    assert _OF.gets == [], f"a cached photo must cost no OF fetch, got {_OF.gets}"
    assert _OF.byid_calls == [], f"…and no re-sign either, got {_OF.byid_calls}"


async def case_describe_photo_uses_the_full_frame_not_the_crop():
    """IMAGE_DIR, never THUMB_DIR. The thumb is a 300px centre-crop whose top and
    bottom are gone — reading a flag off it is what made the model over-report
    `fully_nude`, so a warm THUMB must not satisfy a describe."""
    _clear_disk()
    _OF.reset()
    fresh = _files("FRESH")
    _OF.live = {f["url"] for f in fresh.values()}
    _OF.byid = {8802: {"id": 8802, "type": "photo", "files": fresh}}
    await _seed_media(_AID, 8802, {"id": 8802, "type": "photo", "files": _files("EXPIRED")})
    # Only the crop is cached.
    tp = vs.thumb_path(_AID, 8802)
    tp.parent.mkdir(parents=True, exist_ok=True)
    tp.write_bytes(b"\xff\xd8\xffCROPPED-300px\xff\xd9")

    item = await _item(_AID, 8802)
    got = await vault_frames.collect(
        _AID, item, json.loads(item.raw_json), want=1)
    assert got.reason == "ok", got.reason
    assert _OF.byid_calls == [8802], "a warm THUMB must not stand in for the full frame"
    assert vs.image_path(_AID, 8802).is_file(), "the full frame was not kept"


async def case_describe_photo_resigns_when_cold():
    """No disk, stored url dead ⇒ re-sign once, describe, and KEEP the bytes so
    the next pass is free."""
    _clear_disk()
    _OF.reset()
    fresh = _files("FRESH")
    _OF.live = {f["url"] for f in fresh.values()}
    _OF.byid = {8803: {"id": 8803, "type": "photo", "files": fresh}}
    await _seed_media(_AID, 8803, {"id": 8803, "type": "photo", "files": _files("EXPIRED")})

    item = await _item(_AID, 8803)
    got = await vault_frames.collect(
        _AID, item, json.loads(item.raw_json), want=1)
    assert got.reason == "ok" and len(got.images) == 1, got
    assert _OF.byid_calls == [8803], f"expected one re-sign, got {_OF.byid_calls}"
    assert vs.image_path(_AID, 8803).read_bytes() == _JPEG, "re-signed bytes not persisted"


async def case_describe_photo_transient_is_not_no_variant():
    """OF unreachable ⇒ `fetch_failed`. This is the distinction the incident
    erased: stamping it `blocked_drm` inherits a 7-day cool-off and the next
    sweep skips an item that would have worked."""
    _clear_disk()
    _OF.reset()
    _OF.live = set()
    _OF.byid = {}
    _OF.byid_status = 500          # transient, NOT deleted
    try:
        await _seed_media(_AID, 8804, {"id": 8804, "type": "photo", "files": _files("EXPIRED")})
        item = await _item(_AID, 8804)
        got = await vault_frames.collect(
            _AID, item, json.loads(item.raw_json), want=1)
    finally:
        _OF.byid_status = 404
    assert got.images == [], got.images
    assert got.reason == "fetch_failed", f"a dead signature is not a DRM block: {got.reason}"


async def case_collect_never_raises_at_its_callers():
    """`collect` answers with a reason or it answers with frames — it does NOT
    raise. Every caller is a bulk sweep walking a vault, and both of them used to
    let an exception out of the per-item call and into a `gather` that ended the
    whole pass (see `test_vault_ai_describe.case_one_exploding_item_...`).

    A raise is also strictly LESS informative than a reason: the item stamps no
    row at all, so it reads as never-attempted forever. `fetch_failed` is the
    retry-at-once side of the vocabulary, which is the right default for a fault
    we cannot classify.
    """
    _clear_disk()
    _OF.reset()
    await _seed_media(_AID, 8830, {"id": 8830, "type": "photo", "files": _files("OK")})
    item = await _item(_AID, 8830)
    raw = json.loads(item.raw_json)

    orig = vault_frames._collect

    async def _boom(*_a, **_k):
        raise RuntimeError("the client blew up")

    vault_frames._collect = _boom
    try:
        got = await vault_frames.collect(_AID, item, raw, want=1)
    finally:
        vault_frames._collect = orig
    assert got.images == [], got.images
    assert got.reason == "fetch_failed", got.reason
    # `reason` is the retry policy; `detail` is the only place the difference
    # between "OF's signature expired" and "we shipped a bug" survives, and the
    # sweep hands it straight to the operator.
    assert "RuntimeError" in got.detail, got.detail

    # A collect that HANGS is the same failure with a worse shape: it holds a
    # sweep slot and a process-wide vision slot, and the 50-item chunk barrier
    # above it can never close. Bounded, with the same retryable verdict.
    async def _hang(*_a, **_k):
        await asyncio.sleep(60)

    vault_frames._collect = _hang
    prev = vault_frames.COLLECT_TIMEOUT_S
    vault_frames.COLLECT_TIMEOUT_S = 0.05
    try:
        got = await vault_frames.collect(_AID, item, raw, want=1)
    finally:
        vault_frames._collect = orig
        vault_frames.COLLECT_TIMEOUT_S = prev
    assert got.images == [], got.images
    assert got.reason == "fetch_failed", f"a hung collect must be retryable: {got.reason}"
    assert "gave up" in got.detail, got.detail


async def case_describe_photo_no_renderable_variant():
    """OF answered, and its answer carries nothing renderable ⇒ `no_variant`.
    Asking again changes nothing, so this one KEEPS the cool-off."""
    _clear_disk()
    _OF.reset()
    _OF.live = set()
    # A payload with only a video source — `still_url` skips video-looking urls.
    _OF.byid = {8805: {"id": 8805, "type": "photo",
                       "files": {"full": {"url": "https://cdn3.onlyfans.com/x/clip.mp4"}}}}
    await _seed_media(_AID, 8805, {"id": 8805, "type": "photo", "files": _files("EXPIRED")})

    item = await _item(_AID, 8805)
    got = await vault_frames.collect(
        _AID, item, json.loads(item.raw_json), want=1)
    assert got.images == [], got.images
    assert got.reason == "no_variant", got.reason


async def case_describe_photo_gone_is_gone():
    """OF 404s the id ⇒ `gone`, and the row is soft-deleted so no later sweep
    re-asks."""
    _clear_disk()
    _OF.reset()
    _OF.live = set()
    _OF.byid = {}                  # byid_status 404 = deleted for good
    await _seed_media(_AID, 8806, {"id": 8806, "type": "photo", "files": _files("EXPIRED")})

    item = await _item(_AID, 8806)
    got = await vault_frames.collect(
        _AID, item, json.loads(item.raw_json), want=1)
    assert got.reason == "gone", got.reason
    assert (await _item(_AID, 8806)).removed_at is not None, "deletion not remembered"


async def case_unwarmed_video_warms_from_the_resigned_url():
    """The other half of the incident: 1,046 clips whose storyboard was never
    warmed. The stored mp4 url is as dead as any jpeg url, so the miss re-signs
    and must then derive EVERYTHING — the mp4 and the frames it reads back —
    from that one fresh payload. The storyboard hash is taken from the url, so
    warming a fresh url and then reading the OLD hash finds nothing."""
    _clear_disk()
    _OF.reset()
    import server as srv

    old_mp4 = "https://cdn3.onlyfans.com/v/old.mp4?Policy=EXPIRED"
    new_mp4 = "https://cdn3.onlyfans.com/v/new.mp4?Policy=FRESH"
    await _seed_media(_AID, 8807,
                      {"id": 8807, "type": "video", "duration": 30,
                       "files": _files("EXPIRED"),
                       "videoSources": {"240": old_mp4, "720": None}},
                      kind="video")
    _OF.live = set()
    _OF.byid = {8807: {"id": 8807, "type": "video", "duration": 30,
                       "files": _files("FRESH"),
                       "videoSources": {"240": new_mp4, "720": None}}}

    warmed: list[str] = []

    def _fake_warm(_client, url, _dur):
        """Write the storyboard where the REAL warmer would — under the hash of
        the url it was handed."""
        warmed.append(url)
        h = srv._video_path_hash(url)
        for i in range(srv._STORYBOARD_FRAMES):
            fp = srv._storyboard_frame_path(h, i)
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_bytes(_JPEG)
        return "warmed"

    orig = vault_frames.warm_one_sync
    vault_frames.warm_one_sync = _fake_warm
    try:
        item = await _item(_AID, 8807)
        got = await vault_frames.collect(
            _AID, item, json.loads(item.raw_json), want=6)
    finally:
        vault_frames.warm_one_sync = orig
        for u in warmed:
            shutil.rmtree(srv._STORYBOARD_DIR / srv._video_path_hash(u), ignore_errors=True)

    assert warmed == [new_mp4], f"warmed the stale url: {warmed}"
    assert got.reason == "ok", got.reason
    assert len(got.images) == 6, f"frames not read back under the fresh hash: {len(got.images)}"


async def case_a_download_that_failed_is_retryable():
    """A clip whose mp4 we could not pull is `fetch_failed`, never `no_variant`.
    `warm_one_sync` reports `dl_fail` for a non-200 and `error` for an exception;
    both mean the source was there and we missed it, so both must be retried on
    the next sweep rather than inheriting the 7-day un-renderable cool-off."""
    _clear_disk()
    _OF.reset()
    mp4 = "https://cdn3.onlyfans.com/v/x.mp4?Policy=FRESH"
    await _seed_media(_AID, 8808,
                      {"id": 8808, "type": "video", "duration": 30, "files": {},
                       "videoSources": {"240": mp4}}, kind="video")
    # A fresh payload with a live mp4 but NO poster options — so the only route
    # to frames is the download, and that is what fails.
    _OF.byid = {8808: {"id": 8808, "type": "video", "duration": 30, "files": {},
                       "videoSources": {"240": mp4}}}

    orig = vault_frames.warm_one_sync
    for outcome in ("dl_fail", "error"):
        vault_frames.warm_one_sync = lambda *_a, _o=outcome, **_k: _o
        try:
            item = await _item(_AID, 8808)
            got = await vault_frames.collect(
                _AID, item, json.loads(item.raw_json), want=6)
        finally:
            vault_frames.warm_one_sync = orig
        assert got.images == [], got.images
        assert got.reason == "fetch_failed", f"warm={outcome!r} → {got.reason}"


async def case_deleted_video_is_gone_not_fetch_failed():
    """A CLIP OF has deleted ⇒ `gone` + soft-delete, never `fetch_failed`.

    The photo path reads that verdict straight out of `bytes_for`; a video reaches
    it through `resolve_fresh`, which is a second route to the same two outcomes.
    That route used to LOSE the answer (`resolve_fresh` returned a bare None) and
    re-derive it with an extra `VaultItem` read — so `gone` and `fetch_failed` were
    reconstructed rather than reported, and the two want opposite retry policies.
    The distinction now rides on the return; this pins that it survives the trip.
    """
    _clear_disk()
    _OF.reset()
    _OF.live = set()
    _OF.byid = {}                  # byid_status 404 = deleted for good
    await _seed_media(_AID, 8809,
                      {"id": 8809, "type": "video", "duration": 30, "files": {},
                       "videoSources": {"240": "https://cdn3.onlyfans.com/v/d.mp4?Policy=DEAD"}},
                      kind="video")

    item = await _item(_AID, 8809)
    got = await vault_frames.collect(
        _AID, item, json.loads(item.raw_json), want=6)
    assert got.images == [], got.images
    assert got.reason == "gone", f"a deleted clip is not a transient miss: {got.reason}"
    assert (await _item(_AID, 8809)).removed_at is not None, "deletion not remembered"


_harness.run(
    _seed_fixtures,
    case_disk_hit_never_touches_of,
    case_expired_url_resigns,
    case_resign_only_once,
    case_gone_media_is_remembered,
    case_gone_media_costs_nothing,
    case_transient_failure_retries,
    case_a_recollect_lifts_the_soft_delete,
    case_an_uncollected_media_resolves_by_id,
    case_a_non_image_body_is_never_cached,
    case_audio_is_not_offered_a_thumb_url,
    case_audio_never_asks_of_for_a_picture,
    case_poster_frame_resigns,
    case_refresh_keeps_derived_cols,
    case_a_removed_still_refills,
    case_owner_auth_403,
    case_cold_pane_is_capped,
    case_same_media_collapses,
    case_describe_photo_reads_the_disk_store,
    case_describe_photo_uses_the_full_frame_not_the_crop,
    case_describe_photo_resigns_when_cold,
    case_describe_photo_transient_is_not_no_variant,
    case_collect_never_raises_at_its_callers,
    case_describe_photo_no_renderable_variant,
    case_describe_photo_gone_is_gone,
    case_unwarmed_video_warms_from_the_resigned_url,
    case_a_download_that_failed_is_retryable,
    case_deleted_video_is_gone_not_fetch_failed,
)
