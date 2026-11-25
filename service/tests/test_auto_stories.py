#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402 — shared _make_client seam
import automations.auto_stories as as_mod  # noqa: E402,F401 — registers
import automations.unsend_messages as un_mod  # noqa: E402,F401 — registers
from automation_executor import run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, ScheduledJob  # noqa: E402

KIND = "auto_stories"


def _photo(mid: int, *, drm: bool = False, url: str | None = "x") -> dict:
    full: dict = {"url": (f"https://cdn/{mid}.jpg" if url else None)}
    if drm:
        full["drm"] = {"signature": "..."}
    return {"id": mid, "type": "photo", "files": {"full": full}}


class FakeClient:

    def __init__(self, photos: list[dict], start_id: int = 700000,
                 *, lookup: dict | None = None):
        self.user_id = "999"
        self._photos = photos
        self._by_id = {int(p["id"]): p for p in photos}
        self.posted_urls: list[str] = []
        self.posted_mentions: list[str | None] = []
        self.deleted: list[int] = []
        self.hidden: list[int] = []
        self._lookup = lookup or {}
        self._next = start_id

    def vault_media(self, *, type="all", list_id=None, **kw):
        return {"list": self._photos}

    def vault_media_by_id(self, media_id):
        mid = int(media_id)
        return self._by_id.get(mid) or _photo(mid)

    def post_story_from_url(self, url, *, watermark_text=None,
                            return_upload=False, **kw):
        self._next += 1
        self.posted_urls.append(url)
        self.posted_mentions.append(kw.get("mention"))
        story = {"id": self._next, "isReady": False}
        if return_upload:
            return {"story": story,
                    "upload": {"md5": f"md5-{self._next}", "size": 1000 + self._next}}
        return story

    def delete_story(self, story_id):
        self.deleted.append(int(story_id))
        return {"deleted": story_id}

    def vault_media_lookup_hash(self, md5, size):
        return self._lookup.get((md5, int(size)))

    def hide_vault_media(self, media_ids):
        self.hidden.extend(int(m) for m in media_ids)
        return {"success": True, "hidden": len(media_ids)}


def _use_fake(photos: list[dict]) -> FakeClient:
    fake = FakeClient(photos)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _jobs(aid: str, kind: str) -> list[ScheduledJob]:
    async with get_session() as s:
        return (await s.execute(
            select(ScheduledJob).where(
                ScheduledJob.account_id == aid, ScheduledJob.kind == kind
            )
        )).scalars().all()



async def case_post_and_schedule_delete():
    aid = "acc_as_one"
    await _seed_account(aid)
    fake = _use_fake([_photo(1), _photo(2), _photo(3)])

    res = await run_once(aid, KIND, payload={
        "folder_id": 42, "per_run": 2, "hours_to_live": 6,
    })

    assert res["status"] == "ok" and res["posted"] == 2, res
    assert len(fake.posted_urls) == 2, fake.posted_urls
    assert len(set(fake.posted_urls)) == 2, "picks must be distinct"

    dels = await _jobs(aid, "unsend_messages")
    assert len(dels) == 2, dels
    for j in dels:
        tgt = json.loads(j.payload_json)["targets"][0]
        assert "story_id" in tgt, tgt
        delta_h = (j.run_at - datetime.utcnow()).total_seconds() / 3600
        assert 5.5 < delta_h < 6.5, delta_h



async def case_keep_no_delete():
    aid = "acc_as_keep"
    await _seed_account(aid)
    fake = _use_fake([_photo(1)])

    res = await run_once(aid, KIND, payload={
        "folder_id": 42, "per_run": 1, "remove_vault_dupe": False,
    })
    assert res["posted"] == 1, res
    assert await _jobs(aid, "unsend_messages") == []



async def case_dry_run_plans_nothing():
    aid = "acc_as_dry"
    await _seed_account(aid)
    fake = _use_fake([_photo(1), _photo(2)])

    res = await run_once(aid, KIND, payload={
        "folder_id": 42, "per_run": 2, "hours_to_live": 6, "dry_run": True,
    })
    assert res.get("dry_run") and res["posted"] == 0, res
    assert len(res["would_post"]) == 2, res
    assert fake.posted_urls == [], "dry_run posts nothing"
    assert await _jobs(aid, "unsend_messages") == []



async def case_no_usable_photos_skips():
    aid = "acc_as_empty"
    await _seed_account(aid)
    fake = _use_fake([_photo(1, drm=True), _photo(2, url=None)])

    res = await run_once(aid, KIND, payload={"folder_id": 42, "per_run": 1})
    assert res["status"] == "skipped" and res["reason"] == "no_usable_photos", res
    assert fake.posted_urls == []



async def case_media_files_pool():
    aid = "acc_as_pool"
    await _seed_account(aid)
    fake = _use_fake([])
    res = await run_once(aid, KIND, payload={
        "media_files": [501, 502, 503], "media_count": 2, "hours_to_live": 3,
    })
    assert res["status"] == "ok" and res["posted"] == 2, res
    assert len(fake.posted_urls) == 2 and len(set(fake.posted_urls)) == 2, fake.posted_urls
    assert all("cdn/" in u for u in fake.posted_urls), fake.posted_urls
    assert len(await _jobs(aid, "unsend_messages")) == 2



async def case_folder_plus_explicit_pool():
    aid = "acc_as_combo"
    await _seed_account(aid)
    fake = _use_fake([_photo(1), _photo(2)])
    res = await run_once(aid, KIND, payload={
        "folder_id": 42, "media_files": [3, 4], "media_count": 4,
    })
    assert res["status"] == "ok" and res["posted"] == 4, res
    assert len(set(fake.posted_urls)) == 4, "folder ∪ explicit, all distinct"



async def case_no_media_source_skips():
    aid = "acc_as_nosrc"
    await _seed_account(aid)
    fake = _use_fake([_photo(1)])
    res = await run_once(aid, KIND, payload={"per_run": 1})
    assert res["status"] == "skipped" and res["reason"] == "no_media_source", res
    assert fake.posted_urls == []



async def case_story_unsend_leg():
    aid = "acc_as_del"
    await _seed_account(aid)
    fake = _use_fake([])

    res = await run_once(aid, "unsend_messages", payload={
        "targets": [{"story_id": 12345}],
    })
    assert res["unsent"] == 1 and res["failed"] == 0, res
    assert fake.deleted == [12345], fake.deleted



async def case_dupe_hide_with_ttl():
    aid = "acc_as_dupe_ttl"
    await _seed_account(aid)
    fake = _use_fake([_photo(11)])

    res = await run_once(aid, KIND, payload={
        "folder_id": 42, "per_run": 1, "hours_to_live": 6,
    })
    assert res["status"] == "ok" and res["posted"] == 1, res

    jobs = await _jobs(aid, "unsend_messages")
    assert len(jobs) == 1, jobs
    targets = json.loads(jobs[0].payload_json)["targets"]
    kinds = {k for t in targets for k in t}
    assert "story_id" in kinds and "hide_upload" in kinds, targets
    hide = next(t["hide_upload"] for t in targets if "hide_upload" in t)
    assert hide["md5"] and hide["size"], hide
    assert hide["exclude_ids"] == [11], hide



async def case_dupe_hide_no_ttl_keep():
    aid = "acc_as_dupe_keep"
    await _seed_account(aid)
    fake = _use_fake([_photo(22)])

    res = await run_once(aid, KIND, payload={"folder_id": 42, "per_run": 1})
    assert res["posted"] == 1, res

    jobs = await _jobs(aid, "unsend_messages")
    assert len(jobs) == 1, jobs
    targets = json.loads(jobs[0].payload_json)["targets"]
    assert len(targets) == 1 and "hide_upload" in targets[0], targets
    assert "story_id" not in targets[0], "kept story → no delete leg"
    delta_min = (jobs[0].run_at - datetime.utcnow()).total_seconds() / 60
    assert 10 < delta_min < 20, delta_min



async def case_remove_dupe_off_with_ttl():
    aid = "acc_as_dupe_off"
    await _seed_account(aid)
    fake = _use_fake([_photo(33)])

    res = await run_once(aid, KIND, payload={
        "folder_id": 42, "per_run": 1, "hours_to_live": 6,
        "remove_vault_dupe": False,
    })
    assert res["posted"] == 1, res
    jobs = await _jobs(aid, "unsend_messages")
    assert len(jobs) == 1, jobs
    targets = json.loads(jobs[0].payload_json)["targets"]
    assert len(targets) == 1 and "story_id" in targets[0], targets
    assert all("hide_upload" not in t for t in targets), targets



async def case_hide_upload_unsend_leg():
    aid = "acc_as_hide_leg"
    await _seed_account(aid)
    fake = FakeClient([], lookup={
        ("md5-new", 2000): {"id": 900},
        ("md5-src", 2001): {"id": 55},
    })
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]

    res = await run_once(aid, "unsend_messages", payload={"targets": [
        {"hide_upload": {"md5": "md5-new", "size": 2000, "exclude_ids": [55]}},
        {"hide_upload": {"md5": "md5-src", "size": 2001, "exclude_ids": [55]}},
        {"hide_upload": {"md5": "md5-miss", "size": 9999, "exclude_ids": []}},
    ]})
    assert res["failed"] == 0, res
    assert fake.hidden == [900], fake.hidden



async def case_story_mentions_cotag_on_unknown_media():
    aid = "acc_as_cotag"
    await _seed_account(aid)
    async with get_session() as s:
        s.add(AccountAiConfig(account_id=aid, utc_offset=0, daily_cost_cap_cents=100,
                              cotag_username="cohandle"))
    fake = _use_fake([_photo(1), _photo(2)])
    import media_cotag
    media_cotag.reset_caches()

    res = await run_once(aid, KIND, payload={"folder_id": 42, "per_run": 2})

    assert res["posted"] == 2, res
    assert fake.posted_mentions == ["@cohandle", "@cohandle"], fake.posted_mentions


async def case_story_skips_cotag_on_solo_media():
    aid = "acc_as_solo"
    await _seed_account(aid)
    fake = _use_fake([_photo(5150)])
    import json as _json

    import media_cotag
    from db.models import VaultItem
    media_cotag.reset_caches()
    async with get_session() as s:
        s.add(VaultItem(
            account_id=aid, media_id=5150, kind="photo", tags="[]",
            send_count=0, created_at=datetime.utcnow(),
            ai_fields_json=_json.dumps(
                {"people_count": 1, "partner_visible": False})))

    res = await run_once(aid, KIND, payload={"folder_id": 42, "per_run": 1})

    assert res["posted"] == 1, res
    assert fake.posted_mentions == [None], fake.posted_mentions
    media_cotag.reset_caches()


_harness.run(
    case_post_and_schedule_delete,
    case_keep_no_delete,
    case_dry_run_plans_nothing,
    case_no_usable_photos_skips,
    case_media_files_pool,
    case_folder_plus_explicit_pool,
    case_no_media_source_skips,
    case_story_unsend_leg,
    case_dupe_hide_with_ttl,
    case_dupe_hide_no_ttl_keep,
    case_remove_dupe_off_with_ttl,
    case_hide_upload_unsend_leg,
    case_story_mentions_cotag_on_unknown_media,
    case_story_skips_cotag_on_solo_media,
)
