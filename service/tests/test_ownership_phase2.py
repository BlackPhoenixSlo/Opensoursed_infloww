#!/usr/bin/env python3
"""Phase 2 of the no-duplicate-PPV plan: a fan who BUYS content in ANY lane
(wall post, mass blast, priced teaser) must end up OWNING its media ids, and
the re-sale guard must block on what he already paid for."""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)
_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import ownership  # noqa: E402
import server  # noqa: E402 — the HTTP re-sale guard; module level (importing it
               # inside a case, mid-event-loop, raced its own module init)
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

# Captured verbatim from prod 2026-07-23 (the Dennis incident's post buy).
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


class _FakeResp:
    def __init__(self, payload): self._p = payload
    def json(self): return self._p


class _NotifClient:
    """Purchase-notifications feed + optional single-post GET."""
    def __init__(self, items, post_media=None, post_boom=False):
        self.items = items
        self.post_media = post_media or {}
        self.post_boom = post_boom
        self.post_calls = []

    def get(self, path):
        assert "type=purchases" in path, path
        return _FakeResp({"list": self.items})

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


# ── §1: the post-purchase notification parser ────────────────────────

def case_parse_post_purchase_real_payload():
    p = pn.parse_post_purchase(_REAL_POST_NOTIF)
    assert p is not None, "the captured prod payload must parse"
    assert p["post_id"] == _POST, p
    assert p["fan_id"] == _FAN, p
    assert p["amount_cents"] == 1000, p
    # The two vocabularies never cross:
    assert pn.parse_purchase(_REAL_POST_NOTIF) is None, \
        "a post buy must not be mistaken for a chat buy"
    assert pn.parse_post_purchase(
        dict(_REAL_POST_NOTIF, type="paided_message")) is None
    # Known-foreign subType (a stream, say) is rejected; junk never crashes.
    assert pn.parse_post_purchase(
        dict(_REAL_POST_NOTIF, subType="your_stream_purchased")) is None
    assert pn.parse_post_purchase({"type": "paided_post", "text": "hi"}) is None
    assert pn.parse_post_purchase(None) is None
    assert pn.parse_post_purchase(
        dict(_REAL_POST_NOTIF, user={})) is None, "no fan id → no stamp target"


# ── §1: post buy → media OWNED (wall_media path) ─────────────────────

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
        # Live GET is consulted FIRST (wall_media keeps first-seen post_id, so
        # it can be partial); here it's empty → the wall rows are the source.
        assert client.post_calls == [_POST], client.post_calls
        rows = await _vault_send_rows(aid)
        assert len(rows) == 2 and all(r.was_purchased for r in rows), rows

        owned = await ownership.owned_or_seen_media(aid, _FAN)
        assert {4560395188, 4560395189} <= owned, owned
        # Re-poll: idempotent — same rows, nothing new stamped, and the
        # done-notification cache means OF is not re-fetched.
        out2 = await pn.poll_purchases(aid, client)
        assert out2["stamped"] == 0, out2
        assert client.post_calls == [_POST], "re-sighting must not re-hit OF"
        assert len(await _vault_send_rows(aid)) == 2, "re-stamp must not dup rows"
    asyncio.run(go())


def case_post_reusing_media_stamps_full_set():
    """wall_media keys rows by media id and keeps the FIRST-seen post_id, so a
    paid post re-using an older post's media has a partial row-set there. The
    live GET must win so the re-used media is stamped too (else it stays
    silently re-sellable — a Dennis-class miss)."""
    aid = "acc_own_reuse"
    async def go():
        await _seed_account(aid)
        async with get_session() as s:
            # Only the NEW media row points at this post; the re-used video's
            # row belongs to the earlier free post.
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
        await _seed_account(aid)  # no WallMedia rows at all
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
        out = await pn.poll_purchases(aid, client)  # must not raise
        assert out["posts"] == 1 and out["stamped"] == 0, out
        assert await _vault_send_rows(aid) == [], "no media known → nothing stamped"
    asyncio.run(go())


def case_resale_guard_video_is_absolute():
    """`resale_verdict` — the re-sale guard for the human/extension send path,
    the one seller that had NO ownership check and re-charged 4 fans $456 for
    content they already held (one whale paid 4× for the same two clips at
    $40 → $80 → $100 → $120).

    VIDEO is the absolute rule: one already-paid video blocks, even when it
    was listed as a preview (a video is never mere filler). An owned id the vault mirror can't classify counts
    toward NO rule and passes: blocking a live send on a guess is worse than
    the miss, and it is logged instead."""
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
            # `paid_unknown` deliberately gets NO VaultItem row.
            await s.commit()
        await ownership.stamp_media_owned(
            aid, _FAN, [paid_video, paid_photo, paid_unknown], source="test")

        v = await ownership.resale_verdict(
            aid, _FAN, [paid_video, paid_unknown, fresh_video])
        assert v.reason == "owned_video", v
        assert v.owned_videos == [paid_video], v
        # Demoting the paid video into `previews` must NOT buy a way past it.
        v2 = await ownership.resale_verdict(
            aid, _FAN, [paid_video, fresh_video], previews=[paid_video])
        assert v2.reason == "owned_video", v2
        # Nothing owned but an unclassifiable id → allowed, counted nowhere.
        v3 = await ownership.resale_verdict(aid, _FAN, [fresh_video, paid_unknown])
        assert not v3.blocked, v3
        assert v3.photos_total == 0, v3
        # Cheap exits — never a false block.
        assert not (await ownership.resale_verdict(aid, _FAN, [])).blocked
        assert not (await ownership.resale_verdict(aid, 0, [paid_video])).blocked
        assert not (await ownership.resale_verdict(
            aid, 4_242_424, [paid_video])).blocked, "a different fan owns nothing"
    asyncio.run(go())


def case_resale_guard_photos_need_half_fresh():
    """PHOTOS are proportional, not absolute (operator ruling 2026-08-08): the
    non-preview photo set must be at LEAST half new. Re-using some stills to
    frame a fresh set is normal selling; charging again for a set that is
    mostly his already is the abuse.

    Exactly half PASSES — the bar is "at least 50% unbought" — and previews
    are excluded from both sides of the ratio, so padding a stale set with
    already-owned preview frames can neither rescue nor sink it."""
    aid = "acc_resale_photos"
    async def go():
        await _seed_account(aid)
        old = [7_100_001, 7_100_002, 7_100_003]      # he already paid for these
        new = [7_200_001, 7_200_002, 7_200_003]      # never sent
        async with get_session() as s:
            for m in old + new:
                s.add(VaultItem(account_id=aid, media_id=m, kind="photo",
                                created_at=_NOW))
            await s.commit()
        await ownership.stamp_media_owned(aid, _FAN, old, source="test")

        async def reason(media, previews=None):
            return (await ownership.resale_verdict(
                aid, _FAN, media, previews=previews)).reason

        # 1 of 2 fresh = exactly 50% → allowed (the boundary is inclusive).
        assert await reason([old[0], new[0]]) == "", "exactly half must pass"
        # 2 of 4 fresh = 50% → allowed.
        assert await reason(old[:2] + new[:2]) == ""
        # 1 of 3 fresh = 33% → blocked.
        assert await reason(old[:2] + new[:1]) == "mostly_owned_photos"
        # 2 of 3 fresh = 67% → allowed.
        assert await reason(old[:1] + new[:2]) == ""
        # every photo already his → blocked.
        assert await reason(old) == "mostly_owned_photos"
        # nothing of his → allowed.
        assert await reason(new) == ""

        # Previews sit outside the ratio on BOTH sides: a 1-fresh-of-3 payload
        # stays blocked no matter how many owned preview frames ride along...
        assert await reason(old[:2] + new[:1] + [old[2]],
                            previews=[old[2]]) == "mostly_owned_photos"
        # ...and marking the owned photos as previews leaves a clean payload.
        assert await reason(old[:2] + new[:1], previews=old[:2]) == ""

        v = await ownership.resale_verdict(aid, _FAN, old[:2] + new[:1])
        assert v.photos_total == 3 and v.owned_photos == old[:2], v
        assert v.owned_videos == [], v
        # `owned_media` is scoped to the reason — a photo block reports photos.
        assert v.owned_media == old[:2], v
    asyncio.run(go())


def case_resale_guard_http_layer_wiring():
    """The HTTP guard (`server._reject_if_resale`) must agree with the domain
    layer on BOTH grounds, and must stay silent on everything it is not for.

    Guards the seams a pure-`resale_verdict` test can't see: that every reason
    the domain can return has operator copy (a missing key would 500 on the
    money path instead of showing a message), that the free-send and
    no-vault-media exits come BEFORE any lookup, and that a broken guard read
    lets the send through rather than taking the chat offline."""
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

        # EVERY reason the domain can produce needs copy — no KeyError on a 409.
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
        # The counts must actually render — an unformatted brace would ship
        # "{owned} of {total}" straight to the operator.
        assert "2 of 3 photos" in detail["message"], detail
        assert detail["owned_media"] == [old_a, old_b], detail

        # Not a re-sale: half fresh, free send, no vault media, unknown fan.
        assert (await status(_Body(20.0, [old_a, fresh])))[0] == 200
        assert (await status(_Body(0, [vid, old_a, old_b])))[0] == 200, "free is never a re-sale"
        assert (await status(_Body(20.0, [{"processId": "x"}])))[0] == 200, "no vault ids"
        assert (await status(_Body(20.0, [-5])))[0] == 200, "fresh-claim placeholder"

        # A broken guard read must ALLOW, never 500 the chat.
        real = ownership.resale_verdict
        ownership.resale_verdict = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down"))
        try:
            assert (await status(_Body(20.0, [vid])))[0] == 200, "broken guard must allow"
        finally:
            ownership.resale_verdict = real
    asyncio.run(go())


# ── §2: mass buy → ledger link → media OWNED via the broadcast cache ─

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
            # The optimistic placeholder row the blast wrote for this fan.
            s.add(Message(
                account_id=aid, fan_id=_FAN,
                message_id=mass_placeholder_message_id(run_id),
                direction="out", price_cents=1500, is_paid=False,
                media_ids="[]", mass_run_id=run_id,
                created_at=_NOW - timedelta(hours=2),
            ))
            await s.commit()
        # The ledger sees the buy (exact price, no other candidate).
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
        # Idempotent: the 5-min supervisor re-sees the same provider row.
        await ti._write_one(aid, raw)
        rows = await _vault_send_rows(aid)
        assert len([r for r in rows if r.media_id in (999001, 999002)]) == 2, rows
    asyncio.run(go())


# ── §2: priced-teaser buy → VaultSend rows flip via the message stamp ─

def case_teaser_buy_flips_vault_send_rows():
    aid = "acc_own_teaser"
    msg_id = 10516999000001
    async def go():
        await _seed_account(aid)
        async with get_session() as s:
            # What record_hot_teaser wrote at send time: rows keyed by message,
            # was_purchased NULL (never flipped by anything before Phase 2).
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


# ── stamp helper: SELECT-first idempotency, flip-don't-dup ───────────

def case_stamp_flips_existing_rows_not_dups():
    aid = "acc_own_idem"
    async def go():
        await _seed_account(aid)
        async with get_session() as s:  # an old offer-send row, unbought
            s.add(VaultSend(account_id=aid, fan_id=_FAN, media_id=331,
                            message_id=None, price_cents=900,
                            was_purchased=False))
            await s.commit()
        n1 = await ownership.stamp_media_owned(aid, _FAN, [331, 332], source="t")
        assert n1 == 2, n1  # one flip + one fresh insert
        n2 = await ownership.stamp_media_owned(aid, _FAN, [331, 332], source="t")
        assert n2 == 0, "second stamp must be a no-op"
        rows = await _vault_send_rows(aid)
        assert len(rows) == 2 and all(r.was_purchased for r in rows), \
            "flip the existing row, insert only the never-sent one, never dup"
    asyncio.run(go())


# ── §3: filler shortfall never blocks — tease slots may repeat ───────

def case_the_two_ownership_predicates_agree():
    """`owners_of_media` (media → fans) and `owned_or_seen_media` (fan → media)
    are direction-inverses of ONE predicate, and callers swap between them.

    Nothing pinned that. The discount-resend and aftercare guards asked
    the media→fans form; the gaps-lane merge moved both to the fan→media form on
    the strength of the two docstrings listing the same three signals. If the
    signal sets ever drift apart, that swap silently changes who gets re-pitched
    and who gets aftercare — with no test failing. So: assert they agree, on each
    signal on its own and on a media id that carries none.

    (The NAME is the trap this guards. `owned_or_seen_media` does NOT include
    merely-seen media — its own docstring has to open by saying so. Renaming it
    touches ten call sites in shipped engines; pinning the invariant is what
    actually buys the safety.)"""
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

        # Nothing at all → neither form claims ownership.
        assert await agree(910001, "untouched media") is False

        # Signal 1 — a purchased VaultSend row.
        await ownership.stamp_media_owned(aid, _FAN, [910002], source="test")
        assert await agree(910002, "signal 1 (VaultSend.was_purchased)") is True

        # Signal 2 — a delivered, NON-FREE content_offer over a catalog item.
        async with get_session() as s:
            s.add(_item(aid, 9101, [910003]))
            await s.commit()
            s.add(ContentOffer(account_id=aid, fan_id=_FAN, item_id=9101,
                               mode="ppv", price_cents=900, status="delivered",
                               resolved_by="ppv_ledger", offered_at=_NOW,
                               resolved_at=_NOW, updated_at=_NOW))
            await s.commit()
        assert await agree(910003, "signal 2 (delivered non-free offer)") is True

        # Signal 2, negative — a FREE teaser is resendable, never owned.
        async with get_session() as s:
            s.add(_item(aid, 9102, [910004]))
            await s.commit()
            s.add(ContentOffer(account_id=aid, fan_id=_FAN, item_id=9102,
                               mode="ppv", price_cents=0, status="delivered",
                               resolved_by="free", offered_at=_NOW,
                               resolved_at=_NOW, updated_at=_NOW))
            await s.commit()
        assert await agree(910004, "signal 2 negative (free teaser)") is False

        # Signal 3 — a paid Message whose media JSON overlaps.
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
