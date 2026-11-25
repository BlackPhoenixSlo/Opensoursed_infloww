from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, NamedTuple

from sqlalchemy import select, update

from db.engine import get_session
from db.models import (
    CatalogItem,
    ContentOffer,
    MassBroadcastCache,
    MassRun,
    Message,
    VaultItem,
    VaultSend,
    WallMedia,
)

log = logging.getLogger("of-relay.ownership")

# Owned only when the money was real, never a free teaser: else every paid item reusing that media becomes unsellable.
OWNED_RESOLVED_BY = ("tip", "ppv_ledger", "ppv_txn", "ppv_fastpath", "manual")


def item_media(item: Any) -> list[int]:
    try:
        return [int(m) for m in json.loads(item.media_ids or "[]")]
    except Exception:
        return []


# Owned only, despite the name: a VaultSend's price_cents is the asked price, not proof of purchase; sent media stays resellable.
async def owned_or_seen_media(account_id: str, fan_id: int) -> set[int]:
    out: set[int] = set()
    async with get_session() as s:
        seen_ids = (await s.execute(
            select(VaultSend.media_id).where(
                VaultSend.account_id == str(account_id),
                VaultSend.fan_id == int(fan_id),
                VaultSend.was_purchased.is_(True))
        )).scalars().all()
        paid_rows = (await s.execute(
            select(Message.media_ids).where(
                Message.account_id == str(account_id),
                Message.fan_id == int(fan_id),
                Message.is_paid.is_(True))
        )).all()
        # A NON-FREE delivered content_offer survives a missed was_purchased flip and covers gate-off accounts.
        delivered_items = (await s.execute(
            select(ContentOffer.item_id).where(
                ContentOffer.account_id == str(account_id),
                ContentOffer.fan_id == int(fan_id),
                ContentOffer.status == "delivered",
                ContentOffer.resolved_by.in_(OWNED_RESOLVED_BY))
        )).scalars().all()
        owned_items = (await s.execute(
            select(CatalogItem).where(
                CatalogItem.id.in_([int(i) for i in delivered_items])))
        ).scalars().all() if delivered_items else []
        s.expunge_all()
    out |= {int(x) for x in seen_ids}
    for (mids_json,) in paid_rows:
        try:
            out |= {int(x) for x in json.loads(mids_json or "[]")}
        except Exception:
            continue
    for it in owned_items:
        out |= set(item_media(it))
    return out


# A priced send must be at least half NEW photos (operator ruling); an exact fraction with integer cross-multiplication keeps money off float rounding.
FRESH_PHOTO_MIN_NUM = 1
FRESH_PHOTO_MIN_DEN = 2

# Named constants: the HTTP layer switches on them to pick the operator's message.
RESALE_OWNED_VIDEO = "owned_video"
RESALE_MOSTLY_OWNED_PHOTOS = "mostly_owned_photos"


class ResaleVerdict(NamedTuple):

    reason: str
    owned_videos: list[int]
    owned_photos: list[int]
    photos_total: int

    @property
    def blocked(self) -> bool:
        return bool(self.reason)

    @property
    def owned_media(self) -> list[int]:
        return (self.owned_videos if self.reason == RESALE_OWNED_VIDEO
                else self.owned_photos)


async def resale_verdict(
    account_id: str,
    fan_id: int,
    media_ids: list[int],
    previews: list[int] | None = None,
) -> ResaleVerdict:
    target = {int(x) for x in media_ids if x}
    if not target or not fan_id:
        return ResaleVerdict("", [], [], 0)
    owned_all = await owned_or_seen_media(account_id, int(fan_id))

    async with get_session() as s:
        rows = (await s.execute(
            select(VaultItem.media_id, VaultItem.kind).where(
                VaultItem.account_id == str(account_id),
                VaultItem.media_id.in_(sorted(target)))
        )).all()
    kinds = {int(m): (k or "") for m, k in rows}
    unknown = sorted(target - set(kinds))
    if unknown:
        log.warning("resale_verdict: %d media unknown to the vault mirror "
                    "account=%s fan=%s ids=%s — counted toward no rule",
                    len(unknown), account_id, fan_id, unknown[:10])
    return resale_verdict_of(owned_all, media_ids, kinds, previews)


def resale_verdict_of(
    owned: set[int],
    item_media: list[int],
    kinds: dict[int, str],
    previews: list[int] | None = None,
) -> ResaleVerdict:
    # A paid video in `previews` still blocks: deliberately stricter than "paying twice".
    # Unclassifiable media counts toward neither rule: blocking a live send on a guess is worse than the miss.
    target = {int(x) for x in item_media if x}
    prev = {int(x) for x in (previews or []) if x} & target
    payload = target - prev

    # Videos: the whole list, previews included (a video is never filler).
    owned_videos = sorted(m for m in target
                          if kinds.get(m) == "video" and m in owned)
    photos = {m for m in payload if kinds.get(m) == "photo"}
    owned_photos = sorted(photos & owned)
    fresh = len(photos) - len(owned_photos)

    # Photo test is cross-multiplied; exactly half is ALLOWED, so the comparison is strict.
    stale_photos = (bool(photos) and fresh * FRESH_PHOTO_MIN_DEN
                    < len(photos) * FRESH_PHOTO_MIN_NUM)
    reason = (RESALE_OWNED_VIDEO if owned_videos
              else RESALE_MOSTLY_OWNED_PHOTOS if stale_photos
              else "")
    return ResaleVerdict(reason, owned_videos, owned_photos, len(photos))


async def owners_of_media(account_id: str, media_ids: list[int]) -> set[int]:
    target = {int(x) for x in media_ids}
    if not target:
        return set()
    owners: set[int] = set()
    async with get_session() as s:
        rows = (await s.execute(
            select(Message.fan_id, Message.media_ids).where(
                Message.account_id == str(account_id),
                Message.is_paid.is_(True),
            )
        )).all()
        vs = (await s.execute(
            select(VaultSend.fan_id).where(
                VaultSend.account_id == str(account_id),
                VaultSend.was_purchased.is_(True),
                VaultSend.media_id.in_(list(target)),
            )
        )).scalars().all()
        owners |= {int(x) for x in vs if x is not None}
        co = (await s.execute(
            select(ContentOffer.fan_id, ContentOffer.item_id).where(
                ContentOffer.account_id == str(account_id),
                ContentOffer.status == "delivered",
                ContentOffer.resolved_by.in_(OWNED_RESOLVED_BY),
            )
        )).all()
        co_media: dict[int, set[int]] = {}
        if co:
            for ci in (await s.execute(
                select(CatalogItem).where(CatalogItem.id.in_(
                    [int(i) for _, i in co if i is not None])))
            ).scalars().all():
                co_media[int(ci.id)] = set(item_media(ci))
    for fid, mids_json in rows:
        if fid is None:
            continue
        try:
            mids = {int(x) for x in json.loads(mids_json or "[]")}
        except Exception:
            continue
        if mids & target:
            owners.add(int(fid))
    for fid, iid in co:
        if fid is not None and iid is not None and co_media.get(int(iid), set()) & target:
            owners.add(int(fid))
    return owners


async def stamp_media_owned(
    account_id: str,
    fan_id: int,
    media_ids: list[int],
    *,
    price_cents: int = 0,
    message_id: int | None = None,
    source: str = "",
) -> int:
    ids = sorted({int(m) for m in media_ids if m})
    if not ids or not fan_id:
        return 0
    stamped = 0
    async with get_session() as s:
        rows = (await s.execute(
            select(VaultSend.media_id, VaultSend.was_purchased).where(
                VaultSend.account_id == str(account_id),
                VaultSend.fan_id == int(fan_id),
                VaultSend.media_id.in_(ids),
            )
        )).all()
        existing = {int(m) for m, _ in rows}
        already_true = {int(m) for m, p in rows if p is True}
        to_flip = sorted((existing - already_true))
        if to_flip:
            await s.execute(
                update(VaultSend)
                .where(VaultSend.account_id == str(account_id),
                       VaultSend.fan_id == int(fan_id),
                       VaultSend.media_id.in_(to_flip))
                .values(was_purchased=True)
            )
        for m in ids:
            if m in existing:
                continue
            s.add(VaultSend(
                account_id=str(account_id),
                fan_id=int(fan_id),
                media_id=int(m),
                message_id=int(message_id) if message_id else None,
                price_cents=int(price_cents or 0),
                was_purchased=True,
            ))
        stamped = len(to_flip) + len([m for m in ids if m not in existing])
        await s.commit()
    if stamped:
        log.info(
            "ownership_stamp account=%s fan=%s media=%d newly_stamped=%d source=%s",
            account_id, fan_id, len(ids), stamped, source or "?")
    return stamped


# Negative entries rate-limit retries for posts OF won't serve (deleted/archived); process-local.
_POST_MEDIA_TTL_OK = timedelta(hours=24)
_POST_MEDIA_TTL_MISS = timedelta(hours=1)
_POST_MEDIA_CACHE_MAX = 512
_post_media_cache: dict[tuple[str, int], tuple[list[int] | None, datetime]] = {}


async def media_for_post(
    account_id: str, post_id: int, client: Any = None
) -> list[int]:
    # Live GET first: wall_media keeps the FIRST-seen post_id, so a post re-using media is incomplete there and stamping the subset leaves media re-sellable.
    key = (str(account_id), int(post_id))
    cached = _post_media_cache.get(key)
    if cached is not None:
        ids, at = cached
        ttl = _POST_MEDIA_TTL_OK if ids else _POST_MEDIA_TTL_MISS
        if datetime.utcnow() - at < ttl:
            return list(ids or [])
    live: list[int] = []
    if client is not None:
        try:
            detail = await asyncio.to_thread(client.get_post, int(post_id))
            media = detail.get("media") if isinstance(detail, dict) else None
            for m in media or []:
                try:
                    live.append(int(m["id"] if isinstance(m, dict) else m))
                except (KeyError, TypeError, ValueError):
                    continue
        except Exception:
            log.debug("ownership_post_fetch_failed account=%s post=%s",
                      account_id, post_id, exc_info=True)
    if live:
        _cache_post_media(key, live)
        return live
    async with get_session() as s:
        wall = (await s.execute(
            select(WallMedia.media_id).where(
                WallMedia.account_id == str(account_id),
                WallMedia.post_id == int(post_id),
            )
        )).scalars().all()
    if wall:
        log.info(
            "ownership_post_media_from_wall account=%s post=%s n=%d "
            "(live fetch unavailable — may be partial for media re-used "
            "across posts)", account_id, post_id, len(wall))
        out = [int(x) for x in wall]
        _cache_post_media(key, out)
        return out
    _cache_post_media(key, None)
    return []


def _cache_post_media(key: tuple[str, int], ids: list[int] | None) -> None:
    while len(_post_media_cache) >= _POST_MEDIA_CACHE_MAX:
        _post_media_cache.pop(next(iter(_post_media_cache)))
    _post_media_cache[key] = (ids, datetime.utcnow())


async def stamp_post_purchase(
    account_id: str,
    fan_id: int,
    post_id: int,
    *,
    price_cents: int = 0,
    client: Any = None,
) -> dict[str, Any]:
    media = await media_for_post(account_id, post_id, client)
    if not media:
        log.info(
            "ownership_post_unresolved account=%s fan=%s post=%s "
            "(no wall_media rows, no live media) — nothing stamped",
            account_id, fan_id, post_id)
        return {"resolved": False, "stamped": 0}
    stamped = await stamp_media_owned(
        account_id, fan_id, media,
        price_cents=price_cents, source=f"post:{post_id}")
    return {"resolved": True, "stamped": stamped}


async def stamp_message_ownership(
    account_id: str, fan_id: int, message_id: int, *, price_cents: int = 0
) -> int:
    stamped = 0
    async with get_session() as s:
        msg = (await s.execute(
            select(Message).where(
                Message.account_id == str(account_id),
                Message.fan_id == int(fan_id),
                Message.message_id == int(message_id),
            ).limit(1)
        )).scalar_one_or_none()
    row_media: list[int] = []
    mass_run_id = None
    if msg is not None:
        mass_run_id = msg.mass_run_id
        try:
            row_media = [int(x) for x in json.loads(msg.media_ids or "[]")]
        except Exception:
            row_media = []
        if not price_cents:
            price_cents = int(msg.price_cents or 0)
    if row_media:
        stamped += await stamp_media_owned(
            account_id, fan_id, row_media,
            price_cents=price_cents, message_id=message_id,
            source=f"msg:{message_id}")

    async with get_session() as s:
        res = await s.execute(
            update(VaultSend)
            .where(VaultSend.account_id == str(account_id),
                   VaultSend.fan_id == int(fan_id),
                   VaultSend.message_id == int(message_id),
                   VaultSend.was_purchased.is_not(True))
            .values(was_purchased=True)
        )
        await s.commit()
    if res.rowcount:
        stamped += int(res.rowcount)
        log.info(
            "ownership_stamp account=%s fan=%s via=vault_send msg=%s flipped=%d",
            account_id, fan_id, message_id, res.rowcount)

    if mass_run_id is not None:
        mass_media = await _mass_run_media(account_id, int(mass_run_id))
        if mass_media:
            stamped += await stamp_media_owned(
                account_id, fan_id, mass_media,
                price_cents=price_cents, message_id=message_id,
                source=f"mass_run:{mass_run_id}")
        else:
            log.info(
                "ownership_mass_unresolved account=%s fan=%s run=%s msg=%s "
                "(no queue_id / no broadcast-cache media) — mass media not stamped",
                account_id, fan_id, mass_run_id, message_id)
    return stamped


async def try_stamp_message(
    account_id: str, fan_id: int, message_id: int, *,
    price_cents: int = 0, context: str = "",
) -> int:
    try:
        return await stamp_message_ownership(
            account_id, fan_id, message_id, price_cents=price_cents)
    except Exception:  # noqa: BLE001
        log.warning("ownership_stamp_failed context=%s account=%s fan=%s id=%s",
                    context, account_id, fan_id, message_id, exc_info=True)
        return 0


async def try_stamp_post(
    account_id: str, fan_id: int, post_id: int, *,
    price_cents: int = 0, client: Any = None, context: str = "",
) -> dict[str, Any]:
    try:
        return await stamp_post_purchase(
            account_id, fan_id, post_id,
            price_cents=price_cents, client=client)
    except Exception:  # noqa: BLE001
        log.warning("ownership_stamp_failed context=%s account=%s fan=%s id=%s",
                    context, account_id, fan_id, post_id, exc_info=True)
        return {"resolved": False, "stamped": 0}


async def _mass_run_media(account_id: str, mass_run_id: int) -> list[int]:
    async with get_session() as s:
        queue_id = (await s.execute(
            select(MassRun.queue_id).where(MassRun.id == int(mass_run_id))
        )).scalar_one_or_none()
        if not queue_id:
            return []
        blob = (await s.execute(
            select(MassBroadcastCache.media_json).where(
                MassBroadcastCache.account_id == str(account_id),
                MassBroadcastCache.queue_id == int(queue_id),
            )
        )).scalar_one_or_none()
    out: list[int] = []
    try:
        for m in json.loads(blob or "[]"):
            out.append(int(m["id"] if isinstance(m, dict) else m))
    except (TypeError, ValueError, KeyError):
        return []
    return out
