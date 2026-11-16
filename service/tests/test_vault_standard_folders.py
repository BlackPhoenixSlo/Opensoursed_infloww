"""Real temporary SQLite placement; no AI, OF requests, or fan messages."""
import _harness  # first: binds a throwaway DB before engine imports
_harness.bootstrap()

import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import select
from db.engine import get_session
from db.models import Account, VaultItem, VaultFolder, VaultFolderItem, VaultFolderPrice
from vault_standard_rules import classify, key, REVIEW, categories
import vault_standard_folders as folders


def item(**fields):
    return SimpleNamespace(kind="photo", describe_status="described", removed_at=None,
        ai_fields_json=json.dumps(fields), operator_overrides_json=None)


def case_no_guess_before_describing():
    row = item(tags=["bikini"], explicitness="sfw")
    row.describe_status = None
    assert classify(row) == set()
    assert classify(item()) == {REVIEW}
    assert classify(item(setting="bathroom")) == {REVIEW}
    assert classify(item(setting="outdoor")) == {"outdoors"}
    assert "cosplay" not in classify(item(primary_folder="outfit_cosplay", tags=["streetwear"]))
    assert "cosplay" in classify(item(description="She is wearing a costume."))
    reviewed = item()
    reviewed.operator_overrides_json = json.dumps({"_standard_folders": {key("photo", REVIEW): False}})
    assert classify(reviewed) == set(), "a manual move out of review must survive refresh"


def case_specific_and_overlapping():
    row = item(camera="mirror", tags=["bikini", "poolside"], setting="outdoor")
    assert classify(row) == {"mirror_selfie", "bikini", "pool", "outdoors"}
    assert "beach" not in classify(row)
    assert "selfie" not in classify(row)
    assert classify(item(description="She is in a bedroom. There is no shower or bath.")) == {REVIEW}
    assert classify(item(description="She is lying on the bed.")) == {"bed"}
    assert classify(item(description="She could be at a beach. It is not a pool.")) == {REVIEW}


def case_focus_acts_and_media_type():
    assert "feet" not in classify(item(_jev={"tags": {"bare_toes_visible": "y"}}))
    assert "feet" in classify(item(_jev={"tags": {"feet_focus": "y"}}))
    assert "solo_play" not in classify(item(people_count=1, acts=["posing"]))
    assert "toy_play" not in classify(item(_jev={"tags": {"toy": "toy_visible_not_in_use"}}))
    row = item(people_count=1, partner_visible=False, acts=["toy_insertion", "strip"])
    assert classify(row) == {"toy_play", "solo_play"}
    row.kind = "video"
    assert classify(row) == {"toy_play", "solo_play", "striptease"}
    assert "anal_play" not in classify(item(body_focus=["ass"]))


def case_override_and_uncertainty():
    row = item(setting="shower", tags=["pool"], confidence=95)
    row.operator_overrides_json = json.dumps({"setting": "other", "tags": ["beach"]})
    assert classify(row) == {"beach"}
    assert classify(item(tags=["beach"], confidence=40)) == {REVIEW}
    assert classify(item(clothing_state="dressed", explicitness="sfw", nsfw=False)) == {"casual"}
    assert "casual" not in classify(item(clothing_state="dressed", explicitness="sfw", nsfw=False,
        _jev={"breasts_bare": "y"}))


async def case_seed_and_concurrent_refresh():
    async with get_session() as s:
        s.add_all([Account(id="standard-a"), Account(id="standard-b")])
    import vault_settings
    for account in ("standard-a", "standard-b"):   # both per-Creator switches on: off is test_vault_settings.py
        await vault_settings.put(account, folder_price_final=True, standard_folders=True)
    async with get_session() as s:
        s.add_all([
            VaultItem(account_id="standard-a", media_id=1, kind="photo", created_at=datetime.utcnow(),
                describe_status="described", ai_fields_json=json.dumps({"tags": ["bikini", "beach"]})),
            VaultItem(account_id="standard-a", media_id=2, kind="video", created_at=datetime.utcnow(),
                describe_status="described", ai_fields_json=json.dumps({"tags": ["bikini"]})),
            VaultItem(account_id="standard-a", media_id=3, kind="photo", created_at=datetime.utcnow(),
                describe_status=None, ai_fields_json=json.dumps({"tags": ["bikini"]})),
            VaultItem(account_id="standard-b", media_id=1, kind="photo", created_at=datetime.utcnow(),
                describe_status="described", ai_fields_json=json.dumps({"tags": ["pool"]})),
        ])
    await asyncio.gather(folders.sync("standard-a"), folders.sync("standard-a"), folders.sync("standard-b"))
    result = await folders.listing("standard-a")
    assert len(result["list"]) == len(categories("photo")) + len(categories("video"))
    assert result["pending"] == 1
    assert next(f for f in result["list"] if f["kind"] == "photo" and f["slug"] == "bikini")["items"] == 1
    assert next(f for f in result["list"] if f["kind"] == "video" and f["slug"] == "bikini")["items"] == 1
    assert next(f for f in result["list"] if f["slug"] == "pool")["items"] == 0


async def case_reconcile_preserves_prices_metadata_and_custom_folders():
    before = await folders.listing("standard-a")
    bikini = next(f for f in before["list"] if f["kind"] == "photo" and f["slug"] == "bikini")
    async with get_session() as s:
        row = await s.get(VaultItem, ("standard-a", 1))
        raw = row.ai_fields_json
        row.operator_overrides_json = json.dumps({"tags": ["pool"]})
        s.add(VaultFolderPrice(account_id="standard-a", folder_ref=f"vf:{bikini['id']}", price_cents=2500))
        custom = VaultFolder(account_id="standard-a", name="Agency favourites", created_by="operator")
        s.add(custom)
        await s.flush()
        custom_id = custom.id
        s.add(VaultFolderItem(account_id="standard-a", folder_id=custom_id, media_id=1))
    await folders.sync("standard-a")
    after = await folders.listing("standard-a")
    assert [(f["id"], f["slug"]) for f in before["list"]] == [(f["id"], f["slug"]) for f in after["list"]]
    assert next(f for f in after["list"] if f["id"] == bikini["id"])["items"] == 0
    async with get_session() as s:
        assert (await s.get(VaultItem, ("standard-a", 1))).ai_fields_json == raw
        assert (await s.get(VaultFolderPrice, ("standard-a", f"vf:{bikini['id']}"))).price_cents == 2500
        assert await s.get(VaultFolderItem, ("standard-a", custom_id, 1)) is not None


async def case_manual_correction_survives_describe_and_review():
    async with get_session() as s:
        rows = list((await s.scalars(select(VaultFolder).where(VaultFolder.account_id == "standard-a"))).all())
        beach = next(f for f in rows if f.created_by == key("photo", "beach"))
        pool = next(f for f in rows if f.created_by == key("photo", "pool"))
        await folders.remember(s, "standard-a", beach, [1], True)
        await folders.remember(s, "standard-a", pool, [1], False)
    await folders.sync("standard-a", [1])
    async with get_session() as s:
        row = await s.get(VaultItem, ("standard-a", 1))
        row.ai_fields_json = json.dumps({"tags": ["pool"], "confidence": 20})
    await folders.sync("standard-a", [1])
    async with get_session() as s:
        assert await s.get(VaultFolderItem, ("standard-a", beach.id, 1)) is not None
        assert await s.get(VaultFolderItem, ("standard-a", pool.id, 1)) is None
        review = next(f for f in rows if f.created_by == key("photo", REVIEW))
        await folders.remember(s, "standard-a", review, [1], True)
    await folders.sync("standard-a", [1])
    async with get_session() as s:
        assert await s.get(VaultFolderItem, ("standard-a", beach.id, 1)) is None
        assert await s.get(VaultFolderItem, ("standard-a", review.id, 1)) is not None
        try:
            await folders.remember(s, "standard-a", beach, [2], True)
            raise AssertionError("video accepted into photo category")
        except Exception as e:
            assert getattr(e, "status_code", None) == 400


async def case_removed_media_and_account_isolation():
    async with get_session() as s:
        row = await s.get(VaultItem, ("standard-a", 1))
        row.removed_at = datetime.utcnow()
    await folders.sync("standard-a", [1])
    async with get_session() as s:
        remaining = list((await s.scalars(select(VaultFolderItem).join(VaultFolder, VaultFolderItem.folder_id == VaultFolder.id)
            .where(VaultFolderItem.account_id == "standard-a", VaultFolderItem.media_id == 1,
                   VaultFolder.created_by.startswith("vault_standard:")))).all())
        assert remaining == []
    other = await folders.listing("standard-b")
    assert next(f for f in other["list"] if f["slug"] == "pool")["items"] == 1


async def case_review_excluded_from_real_sales_inventory():
    from automations import full_ai_sell
    async with get_session() as session:
        session.add(VaultItem(account_id="standard-a", media_id=4, kind="photo", created_at=datetime.utcnow(),
            describe_status="described", ai_fields_json=json.dumps({"tags": [], "suggested_price_cents": 5000})))
    await folders.sync("standard-a", [4])
    loaded = await full_ai_sell.load_rows("standard-a")
    assert not isinstance(loaded, full_ai_sell.Refusal), loaded
    rows, _, _ = loaded
    assert 4 not in {r["media_id"] for r in rows}
    assert 2 in {r["media_id"] for r in rows}


async def case_real_description_completion_places_media():
    import vault_ai_vision
    await vault_ai_vision._write_item("standard-a", 3, describe_status="described",
        ai_fields_json=json.dumps({"tags": ["beach"], "confidence": 98}))
    result = await folders.listing("standard-a")
    assert result["pending"] == 0
    assert next(f for f in result["list"] if f["kind"] == "photo" and f["slug"] == "beach")["items"] == 1


async def case_saved_price_beats_ai_and_haggling():
    from automations import full_ai_sell as sell, full_ai_turn as turn
    from unittest.mock import AsyncMock, patch
    rows = [{"media_id": 55, "kind": "photo", "fields": {}, "folder_cents": 3500, "list_cents": 3500,
             "folder_final": True}]   # `load_rows` marks rows when `vault_settings.folder_price_final` is on
    chosen = sell._offer(rows, [], sell.Ask("anything", "photo", 1), free=False)
    assert sell.folder_price(chosen) == 3500
    assert sell.tease_price(chosen, 1000).price_cents == 3500
    free = sell._offer(rows, [], sell.Ask("anything", "photo", 1), free=True)
    assert sell.tease_price(free, 0).price_cents == 3500
    haggled = turn._haggled(chosen, None, True, ["how about $10?"])
    assert haggled.price_cents == 3500
    facts = SimpleNamespace(pick=chosen)
    reply = {}
    with patch.object(turn._price_jev, "ask", new=AsyncMock(side_effect=AssertionError("paid pricing should be skipped"))):
        await turn._price(facts, reply, 0, 1, True)
    assert facts.pick.price_cents == 3500 and reply["price"]["source"] == "folder"
    bundle = sell._offer([{**rows[0], "kind": "video"}, {**rows[0], "media_id": 56, "kind": "video"}],
        [], sell.Ask("anything", "video", 1), free=False, price="sum")
    assert sell.folder_price(bundle) == 7000
    assert sell.folder_price(sell._offer(rows, [], sell.Ask("anything", "photo", 1), free=True)) is None


_harness.run()
