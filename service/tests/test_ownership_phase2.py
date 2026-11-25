#!/usr/bin/env python3
from __future__ import annotations

import _harness
_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import ownership  # noqa: E402
import server  # noqa: E402 — the HTTP re-sale guard; module level (importing it
import purchase_notifications as pn  # noqa: E402
import transaction_ingest as ti  # noqa: E402
from attribution import mass_placeholder_message_id  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, CatalogItem, ContentOffer, Fan, MassBroadcastCache, MassRun,
    Message, VaultItem, VaultSend, WallMedia,
)

_NOW = datetime(2026, 7, 23, 12, 0, 0)
_FAN = 80000408
_POST = 8000000445

_REAL_POST_NOTIF = {
    "id": 117490480688,
    "type": "paided_post",
    "createdAt": "2026-07-23T11:30:00+00:00",
    "isRead": True,
    "text": ("has purchased your <a href=https://onlyfans.com/8000000445/"
             "winefan>post</a> for $10.00!"),
    "replacePairs": {
        "{POST_URL}": "https://onlyfans.com/8000000445/winefan",
        "{PRICE}": "$10.00",
    },
    "subType": "your_post_purchased",
    "canGoToProfile": True,
    "user": {"id": _FAN, "name": "Dennis Hogan", "username": "fan671"},
}


class _NotifClient:
    def __init__(self, items, post_media=None, post_boom=False):
        self.items = items
        self.post_media = post_media or {}
        self.post_boom = post_boom
        self.post_calls = []

    def get_json(self, path):
        assert "type=purchases" in path, path
        return {"list": self.items}

    def get_post(self, post_id):
        self.post_calls.append(int(post_id))
        if self.post_boom:
            raise RuntimeError("OF 404")
        media = self.post_media.get(int(post_id))
        if media is None:
            return {}
        return {"id": int(post_id),
                "media": [{"id": int(m), "type": "video"} for m in media]}


async def _seed_account(aid):
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        if await s.get(Fan, (aid, _FAN)) is None:
            s.add(Fan(account_id=aid, fan_id=_FAN))
        await s.commit()


async def _vault_send_rows(aid, fan_id=_FAN):
    async with get_session() as s:
        return (await s.execute(
            select(VaultSend).where(VaultSend.account_id == aid,
                                    VaultSend.fan_id == fan_id)
        )).scalars().all()


def _item(aid, iid, media, previews=(), price=900):
    return CatalogItem(
        id=iid, account_id=aid, script_id=None, kind="video",
        media_ids=json.dumps(list(media)),
        preview_media_ids=json.dumps(list(previews)),
        price_cents=price, tip_unlock_cents=0, enabled=True,
    )



def case_parse_post_purchase_real_payload():
    p = pn.parse_post_purchase(_REAL_POST_NOTIF)
    assert p is not None, "the captured prod payload must parse"
    assert p["post_id"] == _POST, p
    assert p["fan_id"] == _FAN, p
    assert p["amount_cents"] == 1000, p
    assert pn.parse_purchase(_REAL_POST_NOTIF) is None, \
        "a post buy must not be mistaken for a chat buy"
    assert pn.parse_post_purchase(
        dict(_REAL_POST_NOTIF, type="paided_message")) is None
    assert pn.parse_post_purchase(
        dict(_REAL_POST_NOTIF, subType="your_stream_purchased")) is None
    assert pn.parse_post_purchase({"type": "paided_post", "text": "hi"}) is None
    assert pn.parse_post_purchase(None) is None
    assert pn.parse_post_purchase(
        dict(_REAL_POST_NOTIF, user={})) is None, "no fan id → no stamp target"



def case_post_buy_stamps_ownership():
    aid = "acc_own_post"
    async def go():
        await _seed_account(aid)
        async with get_session() as s:
            s.add(WallMedia(account_id=aid, media_id=4560395188, post_id=_POST,
                            price_cents=1000))
            s.add(WallMedia(account_id=aid, media_id=4560395189, post_id=_POST,
                            price_cents=1000))
            await s.commit()
        client = _NotifClient([_REAL_POST_NOTIF])
        out = await pn.poll_purchases(aid, client)
        assert out["posts"] == 1 and out["stamped"] == 2, out
        assert client.post_calls == [_POST], client.post_calls
        rows = await _vault_send_rows(aid)
        assert len(rows) == 2 and all(r.was_purchased for r in rows), rows

        owned = await ownership.owned_or_seen_media(aid, _FAN)
        assert {4560395188, 4560395189} <= owned, owned
        out2 = await pn.poll_purchases(aid, client)
        assert out2["stamped"] == 0, out2
        assert client.post_calls == [_POST], "re-sighting must not re-hit OF"
        assert len(await _vault_send_rows(aid)) == 2, "re-stamp must not dup rows"
    asyncio.run(go())


def case_post_reusing_media_stamps_full_set():
    aid = "acc_own_reuse"
    async def go():
        await _seed_account(aid)
        async with get_session() as s:
            s.add(WallMedia(account_id=aid, media_id=871002, post_id=_POST,
                            price_cents=1000))
            s.add(WallMedia(account_id=aid, media_id=871001, post_id=111111,
                            price_cents=0))
            await s.commit()
        client = _NotifClient([_REAL_POST_NOTIF],
                              post_media={_POST: [871001, 871002]})
        out = await pn.poll_purchases(aid, client)
        assert out["stamped"] == 2, out
        owned = await ownership.owned_or_seen_media(aid, _FAN)
        assert {871001, 871002} <= owned, \
            "the re-used media must be owned too — live media list wins"
    asyncio.run(go())


def case_post_buy_get_post_fallback():
    aid = "acc_own_fallback"
    async def go():
        await _seed_account(aid)
        client = _NotifClient([_REAL_POST_NOTIF],
                              post_media={_POST: [881001, 881002, 881003]})
        out = await pn.poll_purchases(aid, client)
        assert client.post_calls == [_POST], "must fall back to the live GET"
        assert out["stamped"] == 3, out
        owned = await ownership.owned_or_seen_media(aid, _FAN)
        assert {881001, 881002, 881003} <= owned, owned
    asyncio.run(go())


def case_unresolvable_post_no_stamp_no_crash():
    aid = "acc_own_unresolved"
    async def go():
        await _seed_account(aid)
        client = _NotifClient([_REAL_POST_NOTIF], post_boom=True)
        out = await pn.poll_purchases(aid, client)
        assert out["posts"] == 1 and out["stamped"] == 0, out
        assert await _vault_send_rows(aid) == [], "no media known → nothing stamped"
    asyncio.run(go())


def case_resale_guard_video_is_absolute():
    aid = "acc_resale_video"
    async def go():
        await _seed_account(aid)
        paid_video, paid_photo = 3625114743, 4109699184
        paid_unknown, fresh_video = 9_999_001, 3591733757
        async with get_session() as s:
            s.add(VaultItem(account_id=aid, media_id=paid_video, kind="video",
                            created_at=_NOW))
            s.add(VaultItem(account_id=aid, media_id=paid_photo, kind="photo",
                            created_at=_NOW))
            s.add(VaultItem(account_id=aid, media_id=fresh_video, kind="video",
                            created_at=_NOW))
            await s.commit()
        await ownership.stamp_media_owned(
            aid, _FAN, [paid_video, paid_photo, paid_unknown], source="test")

        v = await ownership.resale_verdict(
            aid, _FAN, [paid_video, paid_unknown, fresh_video])
        assert v.reason == "owned_video", v
        assert v.owned_videos == [paid_video], v
        v2 = await ownership.resale_verdict(
            aid, _FAN, [paid_video, fresh_video], previews=[paid_video])
        assert v2.reason == "owned_video", v2
        v3 = await ownership.resale_verdict(aid, _FAN, [fresh_video, paid_unknown])
        assert not v3.blocked, v3
        assert v3.photos_total == 0, v3
        assert not (await ownership.resale_verdict(aid, _FAN, [])).blocked
        assert not (await ownership.resale_verdict(aid, 0, [paid_video])).blocked
        assert not (await ownership.resale_verdict(
            aid, 4_242_424, [paid_video])).blocked, "a different fan owns nothing"
    asyncio.run(go())


def case_resale_guard_photos_need_half_fresh():
    aid = "acc_resale_photos"
    async def go():
        await _seed_account(aid)
        old = [7_100_001, 7_100_002, 7_100_003]
        new = [7_200_001, 7_200_002, 7_200_003]
        async with get_session() as s:
            for m in old + new:
                s.add(VaultItem(account_id=aid, media_id=m, kind="photo",
                                created_at=_NOW))
            await s.commit()
        await ownership.stamp_media_owned(aid, _FAN, old, source="test")

        async def reason(media, previews=None):
            return (await ownership.resale_verdict(
                aid, _FAN, media, previews=previews)).reason

        assert await reason([old[0], new[0]]) == "", "exactly half must pass"
        assert await reason(old[:2] + new[:2]) == ""
        assert await reason(old[:2] + new[:1]) == "mostly_owned_photos"
        assert await reason(old[:1] + new[:2]) == ""
        assert await reason(old) == "mostly_owned_photos"
        assert await reason(new) == ""

        assert await reason(old[:2] + new[:1] + [old[2]],
                            previews=[old[2]]) == "mostly_owned_photos"
        assert await reason(old[:2] + new[:1], previews=old[:2]) == ""

        v = await ownership.resale_verdict(aid, _FAN, old[:2] + new[:1])
        assert v.photos_total == 3 and v.owned_photos == old[:2], v
        assert v.owned_videos == [], v
        assert v.owned_media == old[:2], v
    asyncio.run(go())


def case_resale_guard_http_layer_wiring():
    aid = "acc_resale_http"

    class _Body:
        def __init__(self, price, media_files, previews=()):
            self.price, self.media_files = price, list(media_files)
            self.previews = list(previews)

    async def go():
        await _seed_account(aid)
        vid, old_a, old_b, fresh = 8_100_001, 8_100_002, 8_100_003, 8_200_001
        async with get_session() as s:
            s.add(VaultItem(account_id=aid, media_id=vid, kind="video", created_at=_NOW))
            for m in (old_a, old_b, fresh):
                s.add(VaultItem(account_id=aid, media_id=m, kind="photo", created_at=_NOW))
            await s.commit()
        await ownership.stamp_media_owned(aid, _FAN, [vid, old_a, old_b], source="test")

        assert set(server._RESALE_MESSAGES) == {
            ownership.RESALE_OWNED_VIDEO, ownership.RESALE_MOSTLY_OWNED_PHOTOS}

        async def status(body):
            try:
                await server._reject_if_resale(aid, _FAN, body)
            except server.HTTPException as e:
                return e.status_code, e.detail
            return 200, None

        code, detail = await status(_Body(20.0, [vid, fresh]))
        assert code == 409 and detail["error"] == ownership.RESALE_OWNED_VIDEO, detail
        assert detail["owned_media"] == [vid], detail
        assert "video" in detail["message"], detail

        code, detail = await status(_Body(20.0, [old_a, old_b, fresh]))
        assert code == 409, detail
        assert detail["error"] == ownership.RESALE_MOSTLY_OWNED_PHOTOS, detail
        assert "2 of 3 photos" in detail["message"], detail
        assert detail["owned_media"] == [old_a, old_b], detail

        assert (await status(_Body(20.0, [old_a, fresh])))[0] == 200
        assert (await status(_Body(0, [vid, old_a, old_b])))[0] == 200, "free is never a re-sale"
        assert (await status(_Body(20.0, [{"processId": "x"}])))[0] == 200, "no vault ids"
        assert (await status(_Body(20.0, [-5])))[0] == 200, "fresh-claim placeholder"

        real = ownership.resale_verdict
        ownership.resale_verdict = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down"))
        try:
            assert (await status(_Body(20.0, [vid])))[0] == 200, "broken guard must allow"
        finally:
            ownership.resale_verdict = real
    asyncio.run(go())



def case_mass_buy_stamps_ownership():
    aid = "acc_own_massbuy"
    async def go():
        await _seed_account(aid)
        async with get_session() as s:
            run = MassRun(account_id=aid, queue_id=424242,
                          automation_kind="ppv_send", status="done")
            s.add(run)
            await s.flush()
            run_id = int(run.id)
            s.add(MassBroadcastCache(
                account_id=aid, queue_id=424242,
                media_json=json.dumps([{"id": 999001}, {"id": 999002}]),
                previews_json="[]", is_free=False,
            ))
            s.add(Message(
                account_id=aid, fan_id=_FAN,
                message_id=mass_placeholder_message_id(run_id),
                direction="out", price_cents=1500, is_paid=False,
                media_ids="[]", mass_run_id=run_id,
                created_at=_NOW - timedelta(hours=2),
            ))
            await s.commit()
        raw = {
            "id": "prov_mass_1", "amount": 15.0, "net": 12.0, "fee": 3.0,
            "vatAmount": 0, "createdAt": _NOW.isoformat() + "+00:00",
            "status": "done",
            "description": ("Payment for message from <a href='https://onlyfans"
                            ".com/fan671'>Dennis</a>"),
            "user": {"id": _FAN, "username": "fan671"},
        }
        ins, _pat = await ti._write_one(aid, raw)
        assert ins == 1, "the ledger row must insert"
        owners = await ownership.owners_of_media(aid, [999001])
        assert _FAN in owners, \
            "a mass-blast buy must make the fan an OWNER of the blast media"
        owned = await ownership.owned_or_seen_media(aid, _FAN)
        assert {999001, 999002} <= owned, owned
        await ti._write_one(aid, raw)
        rows = await _vault_send_rows(aid)
        assert len([r for r in rows if r.media_id in (999001, 999002)]) == 2, rows
    asyncio.run(go())



def case_teaser_buy_flips_vault_send_rows():
    aid = "acc_own_teaser"
    msg_id = 10516999000001
    async def go():
        await _seed_account(aid)
        async with get_session() as s:
            for m in (661, 662):
                s.add(VaultSend(account_id=aid, fan_id=_FAN, media_id=m,
                                message_id=msg_id, price_cents=1200))
            s.add(Message(account_id=aid, fan_id=_FAN, message_id=msg_id,
                          direction="out", price_cents=1200, is_paid=False,
                          media_ids="[]", created_at=_NOW - timedelta(hours=1)))
            await s.commit()
        notif = {
            "id": 1, "type": "paided_message",
            "subType": "subscriber_pay_for_chat_message",
            "createdAt": _NOW.isoformat() + "+00:00",
            "replacePairs": {
                "{MESSAGE_LINK}": (f"<a href='https://onlyfans.com/my/chats/"
                                   f"chat/{_FAN}?firstId={msg_id}'>message</a>"),
                "{AMOUNT}": "$12.00",
            },
        }
        out = await pn.poll_purchases(aid, _NotifClient([notif]))
        assert out["flipped"] == 1 and out["stamped"] == 2, out
        rows = await _vault_send_rows(aid)
        assert all(r.was_purchased for r in rows if r.message_id == msg_id), rows
        assert _FAN in await ownership.owners_of_media(aid, [661]), \
            "a bought priced teaser must become ownership"
    asyncio.run(go())



def case_stamp_flips_existing_rows_not_dups():
    aid = "acc_own_idem"
    async def go():
        await _seed_account(aid)
        async with get_session() as s:
            s.add(VaultSend(account_id=aid, fan_id=_FAN, media_id=331,
                            message_id=None, price_cents=900,
                            was_purchased=False))
            await s.commit()
        n1 = await ownership.stamp_media_owned(aid, _FAN, [331, 332], source="t")
        assert n1 == 2, n1
        n2 = await ownership.stamp_media_owned(aid, _FAN, [331, 332], source="t")
        assert n2 == 0, "second stamp must be a no-op"
        rows = await _vault_send_rows(aid)
        assert len(rows) == 2 and all(r.was_purchased for r in rows), \
            "flip the existing row, insert only the never-sent one, never dup"
    asyncio.run(go())



def case_the_two_ownership_predicates_agree():
    aid = "acc_own_equiv"
    async def go():
        await _seed_account(aid)

        async def agree(media_id: int, why: str):
            by_media = _FAN in await ownership.owners_of_media(aid, [media_id])
            by_fan = media_id in await ownership.owned_or_seen_media(aid, _FAN)
            assert by_media == by_fan, (
                f"{why}: owners_of_media says {by_media} but "
                f"owned_or_seen_media says {by_fan} for media {media_id}")
            return by_media

        assert await agree(910001, "untouched media") is False

        await ownership.stamp_media_owned(aid, _FAN, [910002], source="test")
        assert await agree(910002, "signal 1 (VaultSend.was_purchased)") is True

        async with get_session() as s:
            s.add(_item(aid, 9101, [910003]))
            await s.commit()
            s.add(ContentOffer(account_id=aid, fan_id=_FAN, item_id=9101,
                               mode="ppv", price_cents=900, status="delivered",
                               resolved_by="ppv_ledger", offered_at=_NOW,
                               resolved_at=_NOW, updated_at=_NOW))
            await s.commit()
        assert await agree(910003, "signal 2 (delivered non-free offer)") is True

        async with get_session() as s:
            s.add(_item(aid, 9102, [910004]))
            await s.commit()
            s.add(ContentOffer(account_id=aid, fan_id=_FAN, item_id=9102,
                               mode="ppv", price_cents=0, status="delivered",
                               resolved_by="free", offered_at=_NOW,
                               resolved_at=_NOW, updated_at=_NOW))
            await s.commit()
        assert await agree(910004, "signal 2 negative (free teaser)") is False

        async with get_session() as s:
            s.add(Message(account_id=aid, fan_id=_FAN, message_id=910500,
                          direction="out", body="", is_paid=True,
                          media_ids=json.dumps([910005]), created_at=_NOW))
            await s.commit()
        assert await agree(910005, "signal 3 (paid Message.media_ids)") is True
    asyncio.run(go())


_harness.run(
    case_parse_post_purchase_real_payload,
    case_post_buy_stamps_ownership,
    case_post_reusing_media_stamps_full_set,
    case_post_buy_get_post_fallback,
    case_unresolvable_post_no_stamp_no_crash,
    case_resale_guard_video_is_absolute,
    case_resale_guard_photos_need_half_fresh,
    case_resale_guard_http_layer_wiring,
    case_mass_buy_stamps_ownership,
    case_teaser_buy_flips_vault_send_rows,
    case_stamp_flips_existing_rows_not_dups,
    case_the_two_ownership_predicates_agree,
)
