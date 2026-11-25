#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime  # noqa: E402

from sqlalchemy import select  # noqa: E402

import vault_ingest  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, VaultItem  # noqa: E402

_AID = "acc_ingest"



class _NotFound(Exception):

    class response:  # noqa: N801 — mimicking the client's attribute, not a class
        status_code = 404


class _FakeOF:

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



async def _clear_items() -> None:
    async with get_session() as s:
        rows = (await s.execute(
            select(VaultItem).where(VaultItem.account_id == _AID)
        )).scalars().all()
        for row in rows:
            await s.delete(row)
        await s.commit()


async def _seed_item(media_id: int, **over) -> None:
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



async def case_import_lands_in_an_existing_mirror():
    await _clear_items()
    _OF.reset()
    await _seed_item(100)
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
    await _clear_items()
    _OF.reset()
    buried = datetime.utcnow()
    await _seed_item(811, removed_at=buried)
    await _seed_item(812)

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
    await _clear_items()
    _OF.reset()
    await _seed_item(20)
    await _seed_item(22)
# ingest must not soft-delete on a 404 (the render path's default): one OF blip would bury a tile the operator sees
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
