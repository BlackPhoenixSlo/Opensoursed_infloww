#!/usr/bin/env python3
"""
`vault_ingest.ingest_ids` — putting a finished import INTO the local mirror.
Plain-assert, no pytest (repo convention).

Why this suite exists: an upload that succeeded on OnlyFans was invisible in the
dashboard. The grid serves from the mirror the moment the mirror holds any row
for the account (`VaultManagePanel`'s `useLocal`), and nothing in the whole
import path — `vault_upload`, the batch route, the CLI — ever wrote a mirror
row. The media was genuinely in her vault and appeared in no vault view, until
somebody thought to run a full re-collect. The operator's reading of that is
"the upload failed", and the next move is to upload it again, onto OnlyFans'
byte dedupe, which returns the same id and changes nothing.

The two boundaries are what this pins:

  * an account with NO mirror is left alone. Seeding rows there would flip the
    grid from a complete live-OF listing to a view of just-imported items, and
    hiding the rest of a vault is a worse bug than the one being fixed.
  * a row that already exists keeps everything the describe pass wrote about it.
    A re-import of the same file is a dedupe hit on OF, and it must not cost the
    account its description, tags or review state.

Cases:
  case_import_lands_in_an_existing_mirror   — the new id is queryable after,
                                    with the kind and urls OF just reported.
  case_no_mirror_is_left_untouched — zero rows in, zero rows out, and OF is
                                    never even asked.
  case_a_fully_buried_mirror_is_left_untouched — rows exist but every one is
                                    soft-deleted, so the grid is reading OF; the
                                    guard must agree with the grid, not with the
                                    row count.
  case_describe_output_survives_a_reimport — description/tags/review_state are
                                    preserved on conflict; urls refresh.
  case_a_dead_id_does_not_sink_the_batch — one id 500s, the others still land.
  case_reimport_does_not_restamp_the_run_id — an import is not a sweep and must
                                    not claim to be the last one that saw a row.
  case_a_404_during_ingest_never_buries_an_existing_row — the ingest shares
                                    `resolve_fresh` but NOT its soft-delete; an
                                    import must never remove media from the grid.
  case_a_404_on_a_new_id_creates_nothing — and withholding that write must not
                                    invent a row either.

Run: cd service/tests && \
  PYTHONPATH=$(cd .. && pwd) ../../venv/bin/python test_vault_mirror_ingest.py
Exit 0 = all cases passed. Temp DB bound by _harness (never prod).
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime  # noqa: E402

from sqlalchemy import select  # noqa: E402

import vault_ingest  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, VaultItem  # noqa: E402

_AID = "acc_ingest"


# ── Fake OF ─────────────────────────────────────────────────────────

class _NotFound(Exception):
    """Shaped like the error `vault_stills._resolve_fresh_sync` reads a 404 out
    of — it looks at `e.response.status_code`, and a plain exception is a
    TRANSIENT failure to that code, not a deletion."""

    class response:  # noqa: N801 — mimicking the client's attribute, not a class
        status_code = 404


class _FakeOF:
    """Answers the by-id read the ingest is built on, and counts the asks."""

    def __init__(self):
        self.timeout_s = 5.0
        self.asked: list[int] = []
        self.fails: set[int] = set()
        self.missing: set[int] = set()
        self.kinds: dict[int, str] = {}

    def vault_media_by_id(self, media_id: int) -> dict:
        mid = int(media_id)
        self.asked.append(mid)
        if mid in self.missing:
            raise _NotFound("OF 404 for this media")
        if mid in self.fails:
            raise RuntimeError("OF 500 for this media")
        kind = self.kinds.get(mid, "photo")
        return {
            "id": mid,
            "type": kind,
            "createdAt": "2026-09-08T10:00:00Z",
            "files": {
                "thumb": {"url": f"https://cdn.of/{mid}/thumb.jpg?sig=fresh"},
                "full": {"url": f"https://cdn.of/{mid}/full.jpg?sig=fresh"},
            },
            "listStates": [],
        }

    def reset(self) -> None:
        self.asked.clear()
        self.fails.clear()
        self.missing.clear()
        self.kinds.clear()


_OF = _FakeOF()


# ── Seeders ─────────────────────────────────────────────────────────

async def _clear_items() -> None:
    async with get_session() as s:
        rows = (await s.execute(
            select(VaultItem).where(VaultItem.account_id == _AID)
        )).scalars().all()
        for row in rows:
            await s.delete(row)
        await s.commit()


async def _seed_item(media_id: int, **over) -> None:
    """One mirror row, as a collect sweep would have left it."""
    now = datetime.utcnow()
    vals = dict(
        account_id=_AID, media_id=media_id, kind="photo",
        thumb_url=f"https://cdn.of/{media_id}/thumb.jpg?sig=STALE",
        full_url=f"https://cdn.of/{media_id}/full.jpg?sig=STALE",
        raw_json=json.dumps({"id": media_id, "type": "photo"}),
        created_at=now, updated_at=now, last_seen_run_id=77,
        search_text="photo", tags="[]", of_folder_ids="[]",
    )
    vals.update(over)
    async with get_session() as s:
        s.add(VaultItem(**vals))
        await s.commit()


async def _get(media_id: int) -> VaultItem | None:
    async with get_session() as s:
        return await s.get(VaultItem, (_AID, media_id))


async def _count() -> int:
    async with get_session() as s:
        return len((await s.execute(
            select(VaultItem).where(VaultItem.account_id == _AID)
        )).scalars().all())


# ── Cases ───────────────────────────────────────────────────────────

async def case_import_lands_in_an_existing_mirror():
    await _clear_items()
    _OF.reset()
    await _seed_item(100)                      # the mirror exists
    _OF.kinds[201] = "photo"

    landed = await vault_ingest.ingest_ids(_AID, [201], _OF)

    assert landed == 1, f"expected 1 row landed, got {landed}"
    row = await _get(201)
    assert row is not None, "the imported media must be queryable in the mirror"
    assert row.kind == "photo", f"kind came from OF, got {row.kind!r}"
    assert row.thumb_url and "sig=fresh" in row.thumb_url, \
        f"the freshly signed url must be stored, got {row.thumb_url!r}"
    assert row.removed_at is None, "a media OF just handed us is not removed"


async def case_no_mirror_is_left_untouched():
    await _clear_items()
    _OF.reset()

    landed = await vault_ingest.ingest_ids(_AID, [301, 302], _OF)

    assert landed == 0, f"an uncollected account takes no rows, got {landed}"
    assert await _count() == 0, \
        "a partial mirror would hide the rest of the vault behind it"
    assert _OF.asked == [], \
        f"OF must not even be asked when there is no mirror, got {_OF.asked}"


async def case_a_fully_buried_mirror_is_left_untouched():
    """A mirror whose every row is soft-deleted is NOT a mirror the grid uses.

    `cache_summary` — the count the UI turns into `cachedCount`, and therefore
    into `useLocal = cachedCount > 0` — filters on `removed_at IS NULL`. A guard
    that counted every row instead would disagree with the grid in exactly the
    direction it exists to prevent: `vault_stills` stamps `removed_at` on any OF
    "not found", so an expired signature or a session pointed at the wrong OF
    user can bury a whole 2,500-item mirror while the grid falls back to live OF
    and looks fine. Landing three imported ids there would flip the grid onto a
    mirror holding three tiles, and the rest of her vault would be gone from
    every view.
    """
    await _clear_items()
    _OF.reset()
    buried = datetime.utcnow()
    for mid in (801, 802, 803, 804, 805):
        await _seed_item(mid, removed_at=buried)

    landed = await vault_ingest.ingest_ids(_AID, [901], _OF)

    assert landed == 0, (
        "every row is soft-deleted, so the grid is serving live OF and already "
        f"shows the import; landing here hides the vault behind it, got {landed}")
    assert await _get(901) is None, "the imported id must not be seeded"
    assert _OF.asked == [], \
        f"OF must not be asked when there is no live mirror, got {_OF.asked}"


async def case_one_live_row_is_still_a_mirror():
    """The buried-mirror check must not become "no soft-deletes anywhere".

    A real vault always carries some `removed_at` rows — every media the creator
    has ever hidden. If ONE row is still live the grid is on the mirror, and the
    import has to land there or it is invisible.
    """
    await _clear_items()
    _OF.reset()
    buried = datetime.utcnow()
    await _seed_item(811, removed_at=buried)
    await _seed_item(812)                      # one survivor — the grid uses it

    landed = await vault_ingest.ingest_ids(_AID, [913], _OF)

    assert landed == 1, f"a mirror with a live row still takes the import, got {landed}"
    assert await _get(913) is not None, "the imported media must be queryable"


async def case_describe_output_survives_a_reimport():
    await _clear_items()
    _OF.reset()
    await _seed_item(400, description="she is on the balcony at sunset",
                     tags=json.dumps(["balcony", "sunset"]),
                     review_state="approved", search_text="photo balcony sunset")

    landed = await vault_ingest.ingest_ids(_AID, [400], _OF)

    assert landed == 1, f"expected the existing row refreshed, got {landed}"
    row = await _get(400)
    assert row.description == "she is on the balcony at sunset", \
        f"describe output was clobbered: {row.description!r}"
    assert json.loads(row.tags) == ["balcony", "sunset"], f"tags lost: {row.tags!r}"
    assert row.review_state == "approved", f"review lost: {row.review_state!r}"
    assert "sig=fresh" in row.thumb_url, "the url SHOULD refresh — it is bookkeeping"


async def case_a_dead_id_does_not_sink_the_batch():
    await _clear_items()
    _OF.reset()
    await _seed_item(500)
    _OF.fails.add(601)

    landed = await vault_ingest.ingest_ids(_AID, [601, 602], _OF)

    assert landed == 1, f"the healthy id must still land, got {landed}"
    assert await _get(601) is None, "the failed id writes nothing"
    assert await _get(602) is not None, "the id after the failure must land"


async def case_reimport_does_not_restamp_the_run_id():
    await _clear_items()
    _OF.reset()
    await _seed_item(700, last_seen_run_id=77)

    await vault_ingest.ingest_ids(_AID, [700], _OF)

    row = await _get(700)
    assert row.last_seen_run_id == 77, (
        "an import is not a collect sweep; stamping run 0 over a real sweep's id "
        f"lies about what last paged this account, got {row.last_seen_run_id}")


async def case_a_404_during_ingest_never_buries_an_existing_row():
    """An IMPORT must not be able to delete media from the operator's grid.

    The ingest is built on `vault_stills.resolve_fresh` so that one place knows
    what a 404 from OnlyFans means — but that function's default is to stamp
    `removed_at` on it, which is right for the RENDER path and wrong here. The
    render path asks about a media the mirror already claims exists, so a 404
    really is a deletion. This caller asks about a media this process uploaded
    seconds ago, and a Google Drive memo hit re-imports an id that ALREADY has a
    mirror row. One blip from OF — or a session pointed at the wrong OF user,
    the mundane cause `has_live_mirror`'s own docstring cites — then soft-
    deleted a tile the operator could see a second earlier, and `bytes_for`'s
    negative cache answered `gone` on every render of it until a full
    re-collect. Hence `mark_gone=False` at the call site.
    """
    await _clear_items()
    _OF.reset()
    await _seed_item(20)                       # the mirror is live
    await _seed_item(22)                       # …and already holds the id
    _OF.missing.add(22)

    landed = await vault_ingest.ingest_ids(_AID, [22], _OF)

    assert _OF.asked == [22], f"the id must still be read from OF, got {_OF.asked}"
    assert landed == 0, f"no payload means no row written, got {landed}"
    row = await _get(22)
    assert row is not None, "the pre-existing row must survive a 404"
    assert row.removed_at is None, (
        "an import soft-deleted media that was already in the vault view — a "
        "404 on an id we just uploaded is a blip, not a deletion")
    assert "sig=STALE" in row.thumb_url, \
        f"nothing was refreshed either, got {row.thumb_url!r}"


async def case_a_404_on_a_new_id_creates_nothing():
    """The other half: withholding the soft-delete must not turn a 404 into a
    row. `resolve_fresh` cannot create one, and the upsert below it only runs on
    a payload — so an id OF genuinely does not have leaves the mirror exactly as
    it was."""
    await _clear_items()
    _OF.reset()
    await _seed_item(30)
    _OF.missing.add(99)

    landed = await vault_ingest.ingest_ids(_AID, [99], _OF)

    assert landed == 0, f"a 404 lands nothing, got {landed}"
    assert await _get(99) is None, "no row may be invented for a media OF denies"
    assert await _count() == 1, "and nothing else moved"


async def _seed_fixtures():
    async with get_session() as s:
        if await s.get(Account, _AID) is None:
            s.add(Account(id=_AID, nickname=_AID, color="#aaaaaa"))
            await s.commit()


_harness.run(
    _seed_fixtures,
    case_import_lands_in_an_existing_mirror,
    case_no_mirror_is_left_untouched,
    case_a_fully_buried_mirror_is_left_untouched,
    case_one_live_row_is_still_a_mirror,
    case_describe_output_survives_a_reimport,
    case_a_dead_id_does_not_sink_the_batch,
    case_reimport_does_not_restamp_the_run_id,
    case_a_404_during_ingest_never_buries_an_existing_row,
    case_a_404_on_a_new_id_creates_nothing,
)
