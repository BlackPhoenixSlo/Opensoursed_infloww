from __future__ import annotations

import functools as _functools
import time
import json as _json
import os as _os
import sys
import threading
from collections import OrderedDict
from collections.abc import Set as AbstractSet
import logging
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
from typing import Any, TypedDict

import requests

from fansly_client import MEDIA_BASE, FanslyAPIError, FanslyClient
from fansly_vault import VaultMixin

log = logging.getLogger("of-relay.fansly.shim")


def _guard_outbound(text):
    # Same floor every OFClient send passes: an automation on a Fansly account can't dodge the sensitive-word guard
    try:
        from of_client import _guard_outbound as guard
        from of_rich_text import has_html, of_plain
    except ImportError:
        return text
    text = guard(text)
    return of_plain(text) if has_html(text) else text

# Peak memory = this x Fansly's server-chosen partSize (20 MiB) regardless of file size; separate from OnlyFans' env var (5 MiB parts)
_UPLOAD_PART_CONCURRENCY = int(_os.environ.get("FANSLY_UPLOAD_PART_CONCURRENCY") or 4)
_UPLOAD_HASH_CHUNK = 1024 * 1024


_UNSUPPORTED_LOGGED: set[str] = set()
_RAISE = object()


class FanslyUnsupported(FanslyAPIError):
    status_code = 501


class FanslyBlocked(FanslyAPIError):
    status_code = 501


_BROADCAST_UNCONFIRMED = "broadcast shape is bundle-derived; sends only with confirm_live_broadcast"


def fansly_unsupported(reason: str, returns: Any = _RAISE):
    def decorate(fn):
        @_functools.wraps(fn)
        def wrapper(*_args: Any, **_kwargs: Any) -> Any:
            if fn.__name__ not in _UNSUPPORTED_LOGGED:
                _UNSUPPORTED_LOGGED.add(fn.__name__)
                log.info("fansly: %s is a no-op — %s", fn.__name__, reason)
            if returns is _RAISE:
                raise FanslyUnsupported(f"{fn.__name__}: {reason}")
            return returns() if callable(returns) else returns
        wrapper.fansly_unsupported = reason
        return wrapper
    return decorate


def fansly_blocked(reason: str, returns: Any = _RAISE):
    def decorate(fn):
        @_functools.wraps(fn)
        def wrapper(*_args: Any, **_kwargs: Any) -> Any:
            if fn.__name__ not in _UNSUPPORTED_LOGGED:
                _UNSUPPORTED_LOGGED.add(fn.__name__)
                log.warning("fansly: %s is not wired yet — %s",
                            fn.__name__, reason)
            if returns is _RAISE:
                raise FanslyBlocked(f"{fn.__name__}: {reason}")
            return returns() if callable(returns) else returns
        wrapper.fansly_blocked = reason
        return wrapper
    return decorate


# 1 USD == 1000 units, anchored on /orders/products wallet names ("$5 Wallet Balance" -> 5000): guessing cents undercharges PPVs 10x
FANSLY_PRICE_UNIT = 1000
_MAX_PURCHASE_UNITS = 10_000_000 * FANSLY_PRICE_UNIT

_UNLOCK_NOTIF_TYPES = {2007, 2008, 32007}
_BANKING_SET = {2007: "accountMediaPrice"}
_UNBANKED_WATCHED = {7001, 15006, 15016, 45012} | (_UNLOCK_NOTIF_TYPES - _BANKING_SET.keys())
_PURCHASE_TTL_S = 60
_PRICE_METADATA_KEYS = ("accountMediaPrice", "price", "amount")


def _fansly_price(usd: Any) -> int:
    return int(round(float(usd or 0) * FANSLY_PRICE_UNIT))



def vault_ids_of(media_files: Any) -> list[str]:
    out: list[str] = []
    for m in list(media_files or []):
        if not m:
            continue
        if isinstance(m, dict):
            mid = m.get("mediaId") or m.get("vault_id") or m.get("id")
            if not mid:
                raise FanslyAPIError(
                    "Fansly attaches VAULT media. This looks like an OF "
                    "fresh-upload claim (processId/host), which Fansly cannot "
                    "consume — run the bytes through upload_media (POST "
                    "/api/of/v2/upload) and attach the vault id it returns."
                )
            out.append(str(mid))
        else:
            out.append(str(m))
    return out


def check_sendable(*, media_files: Any = None, price: Any = 0,
                   previews: Any = None, locked_text: Any = None) -> None:
    # Single source for these rules: the relay's schedule route asks it too, so a bad send fails at schedule time, not hours later
    vault_ids = vault_ids_of(media_files)
    price_usd = float(price or 0)
    if price_usd <= 0:
        return
    # Fansly prices the media, not the message: a text-only PPV would go out free
    if not vault_ids:
        raise FanslyAPIError(
            "A Fansly PPV price rides on the attached media, so a paid "
            "send needs at least one vault attachment."
        )
    # Every attachment free on a paid send: fan pays nothing, composer reports a sale (reachable via OF's preview counter)
    wanted = {str(v) for v in vault_ids}
    if len(({str(p) for p in (previews or [])} & wanted)) >= len(wanted):
        raise FanslyAPIError(
            "Every attachment is marked as a free preview, so a paid send "
            "would deliver all of it for nothing. Leave at least one "
            "attachment locked, or send it free."
        )
    # Message text is always visible on Fansly: OF's text lock has no wire field
    if locked_text:
        raise FanslyAPIError(
            "Fansly always shows the message text — only the media locks. "
            "Send without 'lock text', or move the tease into the media."
        )


# A Fansly GIF is a message whose content is the KLIPY page url (not renderable, 403s on scrape): page<->gif is remembered from /gif-provider and resolved in of_message
_KLIPY_CACHE_PATH = _os.path.join(_os.path.dirname(__file__), ".klipy_urls.json")
_KLIPY_CACHE_MAX = 8000
_KLIPY_API_TIMEOUT_S = 2.0
_KLIPY_PREWARM_CAP = 4
_KLIPY_PREWARM_BUDGET_S = 0.8
_klipy_item2gif: "OrderedDict[str, str]" = OrderedDict()
_klipy_gif2item: dict[str, str] = {}
_klipy_loaded = False
_klipy_lock = threading.Lock()


def _klipy_load() -> None:
    global _klipy_loaded
    if _klipy_loaded:
        return
    _klipy_loaded = True
    try:
        with open(_KLIPY_CACHE_PATH, encoding="utf-8") as fh:
            data = _json.load(fh)
        for item, gif in (data.get("item2gif") or {}).items():
            if item and gif:
                _klipy_item2gif[item] = gif
                _klipy_gif2item[gif] = item
    except (OSError, ValueError):
        pass


def _klipy_save() -> None:
    try:
        tmp = _KLIPY_CACHE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            _json.dump({"item2gif": dict(_klipy_item2gif)}, fh)
        _os.replace(tmp, _KLIPY_CACHE_PATH)
    except OSError:
        pass


def _klipy_remember(itemurl: str, gifurl: str) -> None:
    if not itemurl or not gifurl:
        return
    _klipy_load()
    with _klipy_lock:
        if _klipy_item2gif.get(itemurl) == gifurl:
            _klipy_item2gif.move_to_end(itemurl)
            return
        _klipy_item2gif[itemurl] = gifurl
        _klipy_item2gif.move_to_end(itemurl)
        _klipy_gif2item[gifurl] = itemurl
        while len(_klipy_item2gif) > _KLIPY_CACHE_MAX:
            old_item, old_gif = _klipy_item2gif.popitem(last=False)
            _klipy_gif2item.pop(old_gif, None)


def _klipy_render_url(token: str) -> str | None:
    if not token:
        return None
    if "static.klipy.com" in token:
        return token
    if "klipy.com/gifs/" in token:
        _klipy_load()
        return _klipy_item2gif.get(token)
    return None


def _klipy_wire_url(gid: str) -> str:
    if not gid:
        return gid
    if "klipy.com/gifs/" in gid:
        return gid
    if "static.klipy.com" in gid:
        _klipy_load()
        return _klipy_gif2item.get(gid, gid)
    if "/" not in gid and " " not in gid:
        return f"https://klipy.com/gifs/{gid}"
    return gid


_klipy_unresolvable: set[str] = set()


def _klipy_pick_gif(file_obj: Any) -> str | None:
    if isinstance(file_obj, dict):
        for size in ("md", "hd", "sm", "xs", "original"):
            node = file_obj.get(size)
            if isinstance(node, dict):
                for kind in ("gif", "webp"):
                    variant = node.get(kind)
                    url = variant.get("url") if isinstance(variant, dict) else None
                    if url:
                        return url
    found = {"gif": None, "webp": None, "mp4": None}

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            u = o.get("url")
            if isinstance(u, str):
                low = u.lower()
                for ext in found:
                    if low.endswith("." + ext) and not found[ext]:
                        found[ext] = u
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(file_obj)
    return found["gif"] or found["webp"] or found["mp4"]


def _klipy_resolve_via_api(page_url: str) -> str | None:
    if page_url in _klipy_item2gif:
        return _klipy_item2gif[page_url]
    if page_url in _klipy_unresolvable:
        return None
    slug = page_url.rstrip("/").rsplit("/", 1)[-1]
    if not slug:
        return None
    try:
        resp = requests.get(f"https://api.klipy.com/api/v1/gifs/{slug}",
                            timeout=_KLIPY_API_TIMEOUT_S)
        if resp.status_code == 404:
            _klipy_unresolvable.add(page_url)
            return None
        data = (resp.json() or {}).get("data") or {}
    except (requests.RequestException, ValueError):
        return None
    gif = _klipy_pick_gif(data.get("file") or {})
    if not gif:
        _klipy_unresolvable.add(page_url)
        return None
    _klipy_remember(page_url, gif)
    _klipy_save()
    return gif


def _klipy_prewarm(messages: list[dict]) -> None:
    # of_message must never touch the network on the render path: resolve here, bounded and parallel
    pending: list[str] = []
    seen: set[str] = set()
    for m in messages:
        content = m.get("content") or ""
        if "klipy.com/gifs/" not in content:
            continue
        for tok in content.split():
            if ("klipy.com/gifs/" in tok and tok not in seen
                    and tok not in _klipy_unresolvable
                    and _klipy_render_url(tok) is None):
                seen.add(tok)
                pending.append(tok)
    if not pending:
        return
    pending = pending[:_KLIPY_PREWARM_CAP]
    ex = ThreadPoolExecutor(max_workers=len(pending))
    try:
        futures = [ex.submit(_klipy_resolve_via_api, u) for u in pending]
        wait(futures, timeout=_KLIPY_PREWARM_BUDGET_S)
    finally:
        ex.shutdown(wait=False)


def _extract_klipy_gif(content: str) -> tuple[str | None, str]:
    if not content or "klipy.com" not in content:
        return None, content or ""
    render: str | None = None
    kept: list[str] = []
    for tok in content.split():
        url = _klipy_render_url(tok)
        if url is not None:
            if render is None:
                render = url
            continue
        kept.append(tok)
    return render, " ".join(kept)



def _iso(epoch_seconds: Any) -> str | None:
    if epoch_seconds in (None, 0, "0"):
        return None
    try:
        return datetime.fromtimestamp(float(epoch_seconds), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _avatar_url(account: dict) -> str | None:
    avatar = account.get("avatar")
    if isinstance(avatar, str):
        return avatar
    if isinstance(avatar, dict):
        locs = avatar.get("locations")
        if isinstance(locs, list) and locs and isinstance(locs[0], dict):
            return locs[0].get("location")
        for variant in avatar.get("variants") or []:
            vlocs = variant.get("locations") if isinstance(variant, dict) else None
            if isinstance(vlocs, list) and vlocs and isinstance(vlocs[0], dict):
                return vlocs[0].get("location")
    return None


def _media_full_url(media: dict) -> str | None:
    locs = media.get("locations")
    if isinstance(locs, list) and locs and isinstance(locs[0], dict):
        if locs[0].get("location"):
            return locs[0]["location"]
    # media["location"] is a bare storage path, never fetchable: only signed locations[]/variant urls count
    for v in media.get("variants") or []:
        vl = v.get("locations") if isinstance(v, dict) else None
        if isinstance(vl, list) and vl and isinstance(vl[0], dict) and vl[0].get("location"):
            return vl[0]["location"]
    return None


def _media_variant_url(media: dict, target_w: int) -> str | None:
    best: tuple[int, str] | None = None
    for v in media.get("variants") or []:
        if not isinstance(v, dict):
            continue
        w = v.get("width") or 0
        vl = v.get("locations")
        url = vl[0].get("location") if isinstance(vl, list) and vl and isinstance(vl[0], dict) else None
        if url and w <= target_w and (best is None or w > best[0]):
            best = (w, url)
    return best[1] if best else None


def of_media(account_media: dict) -> dict:
    media = account_media.get("media") or {}
    full = _media_full_url(media)
    preview = _media_variant_url(media, 640) or full
    thumb = _media_variant_url(media, 320) or preview
    of_type = "photo" if media.get("type") == 1 else "video"

    def _var(u: str | None) -> dict | None:
        return {"url": u} if u else None

    # Id stays a string: snowflakes exceed 2^53 and collapse in JS float64, colliding MediaTile keys
    mid = str(account_media.get("id") or "")
    return {
        "id": mid,
        "type": of_type,
        "url": full,
        "files": {
            "full": _var(full),
            "source": _var(full),
            "preview": _var(preview),
            "squarePreview": _var(preview),
            "thumb": _var(thumb),
        },
        "width": media.get("width"),
        "height": media.get("height"),
        # access=False is a locked PPV with no signed url; the frontend reads canView===false for the lock badge
        "canView": bool(account_media.get("access")),
    }


def _note_overlays(account: dict) -> dict:
    notes = account.get("notes")
    if not isinstance(notes, list):
        return {}
    nickname = ""
    note = ""
    for n in notes:
        if not isinstance(n, dict):
            continue
        if n.get("contentType") == 12002:
            nickname = n.get("note") or ""
        elif n.get("contentType") == 12000:
            note = n.get("note") or ""
    return {"displayName": nickname, "notice": note}


def of_user(account: dict) -> dict:
    return {
        "id": str(account.get("id") or ""),
        "name": account.get("displayName") or account.get("username") or "",
        "username": account.get("username") or "",
        "avatar": _avatar_url(account),
        "isVerified": bool(account.get("flags", 0) & 16) or None,
        "isOnline": account.get("statusId") == 1 or None,
        **_note_overlays(account),
    }


def of_message(msg: dict, *, account_id: str,
               media: list | None = None, price: float = 0.0,
               previews: list | None = None,
               purchased_ids: AbstractSet[str] | None = None) -> dict:
    sender = str(msg.get("senderId") or "")
    tip = msg.get("totalTipAmount") or 0
    attachments = msg.get("attachments") or []
    giphy_render, text = _extract_klipy_gif(msg.get("content") or "")
    out = {
        "id": str(msg.get("id") or ""),
        "text": text,
        "fromUser": {"id": sender},
        "createdAt": _iso(msg.get("createdAt")),
        "isTip": bool(tip),
        "price": price,
        "isFree": not price,
        # Priced = locked until a purchase is evidenced. Never read the grant's `purchased`: it is viewer-relative (true on every grant for us, the owner)
        # Real signal: an _UNLOCK_NOTIF_TYPES notification whose correlationId is the grant id and correlationGroupId the buyer (`purchased_ids`)
        "isOpened": (not price) or _is_purchased(msg, media, purchased_ids),
        "isNew": False,
        "media": media or [],
        "previews": previews or [],
        "mediaCount": len(media) if media else len(attachments),
        # The field is replyToMessageId (what OFMessage declares and the chat reads), a string: snowflakes exceed 2^53
        "replyToMessageId": str(msg["inReplyTo"]) if msg.get("inReplyTo") else None,
    }
    if giphy_render:
        out["giphyId"] = giphy_render
    return out


def of_chat_row(membership: dict, fan: dict | None, last_message: dict | None,
                *, account_id: str) -> dict:
    # Row id is the groupId (thread key get_messages pages on), withUser.id the fan's accountId: they differ from OF on purpose
    unread = int(membership.get("unreadCount") or 0)
    # OF zeroes unread when we reply, Fansly does not: lastMessageId != lastUnreadMessageId means a newer message (ours) exists, so clear; absent pointers keep the unread
    _last_id = str(membership.get("lastMessageId") or "")
    _last_unread_id = str(membership.get("lastUnreadMessageId") or "")
    if unread and _last_id and _last_unread_id and _last_id != _last_unread_id:
        unread = 0
    fan_obj = of_user(fan) if fan else {
        "id": str(membership.get("partnerAccountId") or ""),
        "name": membership.get("partnerUsername") or "",
        "username": membership.get("partnerUsername") or "",
        "avatar": None,
    }
    return {
        "id": str(membership.get("groupId") or ""),
        "withUser": fan_obj,
        "lastMessage": of_message(last_message, account_id=account_id) if last_message else None,
        "unreadMessagesCount": unread,
        "hasUnreadMessages": unread > 0,
        "canSendMessage": True,
        "canSendMedia": True,
        "isMutedNotifications": False,
        "isPinned": bool(membership.get("flags", 0) & 4),
    }


def of_chats_page(groups_response: dict, *, account_id: str, limit: int) -> dict:
    data = groups_response.get("data") or []
    agg = groups_response.get("aggregationData") or {}
    accounts_by_id = {str(a.get("id")): a for a in (agg.get("accounts") or [])}
    messages_by_id = {str(m.get("id")): m for m in (agg.get("messages") or [])}

    rows = []
    for membership in data:
        fan = accounts_by_id.get(str(membership.get("partnerAccountId")))
        last = messages_by_id.get(str(membership.get("lastMessageId")))
        rows.append(of_chat_row(membership, fan, last, account_id=account_id))

    return {"list": rows, "hasMore": len(data) >= limit}


def _media_indexes(payload: dict) -> tuple[dict, dict]:
    return (
        {str(m.get("id")): m for m in (payload.get("accountMedia") or [])},
        {str(b.get("id")): b for b in (payload.get("accountMediaBundles") or [])},
    )


def _bundle_media_ids(bundle: dict) -> list[str]:
    content = bundle.get("bundleContent")
    if content:
        return [str(x.get("accountMediaId"))
                for x in sorted(content, key=lambda x: x.get("pos") or 0)]
    return [str(x) for x in (bundle.get("accountMediaIds") or [])]


def _price_metadata(row: dict) -> dict:
    meta = row.get("metadata")
    if isinstance(meta, str):
        try:
            meta = _json.loads(meta)
        except (ValueError, TypeError):
            return {}
    return meta if isinstance(meta, dict) else {}


def _exact_int(raw: Any) -> int | None:
    if type(raw) is int:
        return raw
    if isinstance(raw, str) and raw.isascii() and raw.isdecimal():
        limit = sys.get_int_max_str_digits()
        if not limit or len(raw) <= limit:
            return int(raw)
    return None


def _meta_units(meta: dict, key: str) -> int | None:
    units = _exact_int(meta.get(key))
    return units if units is not None and units >= 0 else None


def _notif_price_usd(row: dict, code: int | None) -> float:
    meta = _price_metadata(row)
    banking_key = _BANKING_SET.get(code)
    keys = (banking_key,) if banking_key is not None else _PRICE_METADATA_KEYS
    # Presence, not truthiness: an explicit price 0 is a free unlock
    for key in keys:
        if key not in meta:
            continue
        units = _meta_units(meta, key)
        return 0.0 if units is None else units / FANSLY_PRICE_UNIT
    return 0.0


def _grant_price_usd(account_media: dict) -> float:
    # Fansly prices the media: /message reports 0, the real figure is the grant's permissions.permissionFlags[].price
    flags = ((account_media or {}).get("permissions") or {}).get("permissionFlags") or []
    amounts = [p.get("price") or 0 for p in flags if isinstance(p, dict)]
    top = max(amounts) if amounts else 0
    return (top / FANSLY_PRICE_UNIT) if top else 0.0


def _purchasable_ids(item: dict, media: list | None) -> set:
    # Index both grant ids and bundle contentIds: a bundle buy's 2007 row may name the bundle (unverified); every id belongs to this message, so no false unlock
    ids = {str(m.get("id")) for m in (media or []) if isinstance(m, dict) and m.get("id")}
    for a in item.get("attachments") or []:
        cid = str(a.get("contentId") or "")
        if cid:
            ids.add(cid)
    return ids


def _is_purchased(item: dict, media: list | None,
                  purchased_ids: AbstractSet[str] | None) -> bool:
    # OF locks per message, Fansly charges per grant: a match on any part opens the bubble
    if not purchased_ids:
        return False
    return bool(_purchasable_ids(item, media) & set(purchased_ids))


def _attachment_price_usd(item: dict, am_by_id: dict, bundle_by_id: dict) -> float:
    # max, not sum: teaser grants are free, so a $20 set with one free preview is $20
    prices = []
    for a in item.get("attachments") or []:
        cid = str(a.get("contentId") or "")
        if a.get("contentType") == 2 and cid in bundle_by_id:
            prices += [_grant_price_usd(am_by_id[m])
                       for m in _bundle_media_ids(bundle_by_id[cid]) if m in am_by_id]
        elif cid in am_by_id:
            prices.append(_grant_price_usd(am_by_id[cid]))
    return max(prices) if prices else 0.0


def _preview_grant_ids(item: dict, am_by_id: dict, bundle_by_id: dict) -> list:
    # Fansly has no previews field: on a priced message an unpriced grant IS the teaser
    ids, any_priced = [], False
    for a in item.get("attachments") or []:
        cid = str(a.get("contentId") or "")
        grants = []
        if a.get("contentType") == 2 and cid in bundle_by_id:
            grants = [am_by_id[m] for m in _bundle_media_ids(bundle_by_id[cid])
                      if m in am_by_id]
        elif cid in am_by_id:
            grants = [am_by_id[cid]]
        for g in grants:
            if _grant_price_usd(g) > 0:
                any_priced = True
            elif g.get("id"):
                ids.append(str(g["id"]))
    return ids if any_priced else []


def _resolve_attachments(item: dict, am_by_id: dict, bundle_by_id: dict) -> list:
    out = []
    for a in item.get("attachments") or []:
        cid = str(a.get("contentId") or "")
        if a.get("contentType") == 2 and cid in bundle_by_id:
            for amid in _bundle_media_ids(bundle_by_id[cid]):
                if amid in am_by_id:
                    out.append(of_media(am_by_id[amid]))
        elif cid in am_by_id:
            out.append(of_media(am_by_id[cid]))
    return out


def of_post(post: dict, *, media: list | None = None) -> dict:
    return {
        "id": str(post.get("id") or ""),
        "text": post.get("content") or "",
        "rawText": post.get("content") or "",
        "price": None,
        "postedAt": _iso(post.get("createdAt")),
        "postedAtPrecise": _iso(post.get("createdAt")),
        "likesCount": post.get("likeCount") or 0,
        "commentsCount": post.get("replyCount") or 0,
        "mediaCount": len(media if media is not None else (post.get("attachments") or [])),
        "media": media or [],
        "previews": [],
    }


def of_posts_page(timeline: dict, *, limit: int) -> dict:
    posts = timeline.get("posts") or []
    am_by_id, bundle_by_id = _media_indexes(timeline)
    rows = [of_post(p, media=_resolve_attachments(p, am_by_id, bundle_by_id))
            for p in posts]
    return {"list": rows, "hasMore": len(posts) >= limit}


def of_messages_page(message_response: dict, *, account_id: str, limit: int,
                     purchased_ids: AbstractSet[str] | None = None) -> dict:
    msgs = message_response.get("messages") or []
    _klipy_prewarm(msgs)
    am_by_id, bundle_by_id = _media_indexes(message_response)

    def _resolve(msg: dict) -> list:
        return _resolve_attachments(msg, am_by_id, bundle_by_id)

    return {
        "list": [of_message(m, account_id=account_id, media=_resolve(m),
                            price=_attachment_price_usd(m, am_by_id, bundle_by_id),
                            previews=_preview_grant_ids(m, am_by_id, bundle_by_id),
                            purchased_ids=purchased_ids)
                 for m in msgs],
        "hasMore": len(msgs) >= limit,
    }


def _klipy_to_giphy(items: Any, *, offset: int = 0) -> dict:
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        itemurl = it.get("itemurl") or ""
        slug = itemurl.rstrip("/").rsplit("/", 1)[-1] if itemurl else ""
        gif = it.get("gifUrl") or ""
        tiny = it.get("tinyGifUrl") or gif
        mp4 = it.get("mp4Url") or ""
        w = str(it.get("width") or "")
        h = str(it.get("height") or "")

        def _v(url: str, with_mp4: bool = False) -> dict:
            v = {"url": url or "", "width": w, "height": h}
            if with_mp4:
                v["mp4"] = mp4
            return v

        _klipy_remember(itemurl, gif)
        out.append({
            # id is the DIRECT gif: the page url is unrenderable; send_message recovers the wire url via the reverse map
            "type": "gif",
            "id": gif or itemurl or slug,
            "url": itemurl,
            "slug": slug,
            "title": it.get("title") or "",
            "images": {
                "original": _v(gif, with_mp4=True),
                "fixed_height": _v(tiny),
                "fixed_height_small": _v(tiny),
                "fixed_width": _v(tiny),
                "downsized": _v(tiny),
                "preview_gif": _v(tiny),
            },
        })
    if out:
        _klipy_save()
    return {
        "data": out,
        "pagination": {"total_count": len(out), "count": len(out), "offset": offset},
    }



class PurchaseFeed(TypedDict):
    sales: list[dict]
    unbanked_seen: dict[str, int]


class FanslyShimClient(VaultMixin, FanslyClient):


    @property
    def user_id(self) -> str:
        return str(self.session.account_id)

    @property
    def account_id(self) -> str:
        return str(self.session.account_id)

    proxy_label = None
    proxy_url = None
    x_of_rev = None

    @property
    def timeout_s(self):
        return self.timeout

    def egress_ip(self) -> None:
        return None


    def me(self) -> dict:  # type: ignore[override]
        account = self._request("GET", "/account/me")["account"]
        return of_user(account)

    def list_chats(self, *, limit: int = 10, offset: int = 0,
                   order: str = "recent", filter: str | None = None,
                   list_id: int | str | None = None,
                   query: str | None = None,
                   skip_users: str | None = "all") -> dict:
        params = {
            "sortOrder": "1",
            "flags": "2" if filter == "unread" else "0",
            "subscriptionTierId": "",
            "listIds": "",
            "search": query or "",
            "limit": str(limit),
            "offset": str(offset),
        }
        groups = self._request("GET", "/messaging/groups", params=params)
        page = of_chats_page(groups, account_id=self.session.account_id, limit=limit)
        self._known_group_ids.update(
            r["id"] for r in page["list"] if r.get("id")
        )
        # The frontend addresses a thread by fan id, not groupId: cache fan->group (find_group_with scans only 100 rows)
        for m in (groups.get("data") or []):
            fan, grp = m.get("partnerAccountId"), m.get("groupId")
            if fan and grp:
                self._fan_to_group[str(fan)] = str(grp)
                self._group_to_fan[str(grp)] = str(fan)
        self._backfill_last_messages(page["list"])
        return page

    def get_messages(self, chat_id: str | int, *, limit: int = 25,
                     order: str = "desc", before_id: str | int | None = None,
                     offset: int | None = None, peek: bool = False) -> dict:
        group_id = self._as_group_id(chat_id)
        params: dict[str, Any] = {"groupId": str(group_id), "limit": str(limit)}
        if before_id is not None:
            params["before"] = str(before_id)
        resp = self._request("GET", "/message", params=params)
        # Scoped to this thread's fan so one fan's purchase never unlocks another's bubble
        fan_id = self._fan_id_for_group(group_id)
        purchased = self._purchases_by_fan().get(str(fan_id or ""), frozenset())
        return of_messages_page(resp, account_id=self.session.account_id, limit=limit,
                                purchased_ids=purchased)

    def chat_folders(self, *, limit: int = 10, offset: int = 0,
                     filter: str = "can_pin_chat") -> dict:
        return {"list": [], "hasMore": False}

    def get_user(self, who: str | int) -> dict:
        accounts = self._request("GET", "/account", params={"ids": str(who)})
        return of_user(accounts[0]) if accounts else {}

    def list_users(self, ids: Any, *, view: str = "m") -> dict:
        id_list = [str(i) for i in (ids or [])]
        if not id_list:
            return {}
        accounts = self._request("GET", "/account",
                                 params={"ids": ",".join(id_list)}) or []
        out: dict[str, dict] = {}
        for a in accounts:
            u = of_user(a)
            if u.get("id"):
                out[str(u["id"])] = u
        return out

    # notes[]: contentType 12000 is a freeform note, 12002 the singleton Custom Username
    _NOTE_TYPE_FREEFORM = 12000
    _NOTE_TYPE_CUSTOM_NAME = 12002

    def _fan_notes(self, user_id: str | int) -> list:
        accounts = self._request("GET", "/account", params={"ids": str(user_id)}) or []
        notes = accounts[0].get("notes") if accounts else None
        return notes if isinstance(notes, list) else []

    def _upsert_note(self, user_id: str | int, content_type: int,
                     title: str, note: str) -> dict:
        existing = None
        for n in self._fan_notes(user_id):
            if isinstance(n, dict) and n.get("contentType") == content_type and n.get("id"):
                existing = n
        if existing:
            return self._request("POST", "/notes/edit", json_body={
                "id": str(existing["id"]),
                "contentType": content_type,
                "contentId": str(user_id),
                "title": title,
                "note": note,
            })
        return self._request("POST", "/notes", json_body={
            "contentType": content_type,
            "contentId": str(user_id),
            "title": title,
            "note": note,
        })

    def set_fan_custom_name(self, user_id: str | int, name: str) -> dict:
        return self._upsert_note(user_id, self._NOTE_TYPE_CUSTOM_NAME,
                                 "Custom Username", name or "")

    def set_fan_note(self, user_id: str | int, note: str) -> dict:
        text = note or ""
        title = (text.splitlines()[0] if text else "")[:90]
        return self._upsert_note(user_id, self._NOTE_TYPE_FREEFORM, title, text)

    def get_chat(self, chat_id: str | int) -> dict:
        group_id = self._as_group_id(chat_id)
        detail = self._request("GET", f"/group/{group_id}/")
        fan_id = next(
            (str(u.get("userId")) for u in detail.get("users", [])
             if str(u.get("userId")) != str(self.session.account_id)),
            "",
        )
        fan = None
        if fan_id:
            accounts = self._request("GET", "/account", params={"ids": fan_id})
            fan = accounts[0] if accounts else None
        membership = {
            "groupId": str(group_id),
            "partnerAccountId": fan_id,
            "unreadCount": 0,
            "flags": detail.get("groupFlags", 0),
        }
        return of_chat_row(membership, fan, detail.get("lastMessage"),
                           account_id=self.session.account_id)


    def _last_message_for_group(self, group_id: str | int) -> dict | None:
        # limit=1 answers an EMPTY messages array on Fansly (measured): ask a small page, take the newest
        try:
            resp = self._request(
                "GET", "/message",
                params={"groupId": str(group_id), "limit": "25"},
            )
        except Exception:
            return None
        msgs = (resp or {}).get("messages") or []
        if not msgs:
            return None
        return of_message(msgs[0], account_id=self.session.account_id)

    def _backfill_last_messages(self, rows: list[dict], *, cap: int = 30) -> None:
        for row in rows[:cap]:
            if row.get("lastMessage") is not None:
                continue
            gid = row.get("id")
            if gid:
                row["lastMessage"] = self._last_message_for_group(gid)


    # A vault mediaId is not sendable: mint an accountMedia grant (POST /account/media) and attach its id; the raw mediaId is accepted but delivers a dead attachment
    # Whitelist is [us, recipient]; a PPV's real price lives in permissions.permissionFlags, top-level price stays 0

    _MEDIA_CONTENT_TYPE = 1
    _MEDIA_PERMISSION_FLAGS = 8

    def _price_permissions(self, price_usd: Any) -> dict:
        # metadata is a JSON string holding another JSON string (Fansly's own); separators pinned to match the browser's bytes
        amount = _fansly_price(price_usd)
        if amount <= 0:
            return {"permissionFlags": []}
        inner = _json.dumps({"price": amount}, separators=(",", ":"))
        return {"permissionFlags": [{
            "type": 0,
            "flags": 3,
            "metadata": _json.dumps({"1": inner}, separators=(",", ":")),
            "price": amount,
        }]}

    def _attach_media(self, media_ids: list, *, fan_id: str,
                      price_usd: Any = 0, preview_ids: Any = None) -> list[str]:
        # One POST per media as captured; a media in preview_ids gets a FREE grant, siblings priced: mixed locks on one message
        us = str(self.session.account_id)
        priced = self._price_permissions(price_usd)
        free = {"permissionFlags": []}
        previews = {str(p) for p in (preview_ids or [])}
        content_ids: list[str] = []
        for mid in media_ids:
            body = [{
                "mediaId": str(mid),
                "previewId": None,
                "permissionFlags": self._MEDIA_PERMISSION_FLAGS,
                "price": 0,
                "whitelist": [{"accountId": us, "permissionFlags": 0},
                              {"accountId": str(fan_id), "permissionFlags": 0}],
                "permissions": free if str(mid) in previews else priced,
                "tags": [],
            }]
            resp = self._request("POST", "/account/media", json_body=body)
            row = (resp or [{}])[0] if isinstance(resp, list) and resp else {}
            cid = row.get("id")
            if not cid:
                raise FanslyAPIError(
                    f"/account/media accepted media {mid} but returned no "
                    f"accountMedia id, so there is nothing to attach."
                )
            content_ids.append(str(cid))
        return content_ids

    def send_message(self, chat_id: str | int, text: str | None = None, *,
                     locked_text: str | None = None, price: int = 0,
                     media_files: Any = None, previews: Any = None,
                     is_forward: bool = False,
                     reply_to_message_id: str | int | None = None,
                     tagged_users: Any = None, giphy_id: str | None = None,
                     auto_tag: bool = False, _broadcast: bool = False,
                     **_ignored: Any) -> dict:
        if not _broadcast:
            text = _guard_outbound(text)
        # A broadcast group id is freshly minted and in no DM listing: take it as-is
        group_id = str(chat_id) if _broadcast else self._group_for_send(chat_id)
        media_files = list(media_files or [])
        check_sendable(media_files=media_files, price=price,
                       previews=previews, locked_text=locked_text)
        vault_ids = vault_ids_of(media_files)
        price_usd = float(price or 0)
        content = text or ""
        if giphy_id:
            gif_url = _klipy_wire_url(str(giphy_id))
            content = f"{content} {gif_url}".strip() if content else gif_url
        attachments = []
        if vault_ids:
            fan_id = self._fan_id_for_group(group_id)
            if not fan_id:
                raise FanslyAPIError(
                    f"Can't attach media to group {group_id}: its recipient "
                    f"didn't resolve, and Fansly needs the accountId to "
                    f"whitelist who may view the attachment."
                )
            content_ids = self._attach_media(
                vault_ids, fan_id=fan_id, price_usd=price_usd,
                preview_ids=previews if price_usd > 0 else None,
            )
            attachments = [
                {"messageId": None, "pos": i, "contentId": cid,
                 "contentType": self._MEDIA_CONTENT_TYPE}
                for i, cid in enumerate(content_ids)
            ]
        created = super().send_message(
            str(group_id),
            content,
            in_reply_to=str(reply_to_message_id) if reply_to_message_id else None,
            # The web client omits scheduledFor on GIF sends
            scheduled_for=None if giphy_id else 0,
            attachments=attachments,
            broadcast=_broadcast,
        )
        # The send response must describe what we sent: Fansly echoes price 0 and no media, and the optimistic reconcile lets the response win (a sent PPV flips to free, tiles vanish)
        if not isinstance(created, dict):
            # /message/broadcast answers a bare scalar in `response`: keep it as the id (the send already fanned out)
            log.info("fansly: send response is a %s, not a message object: %r",
                     type(created).__name__, str(created)[:80])
            created = {"id": str(created) if created not in (None, "") else None,
                       "content": content, "groupId": str(group_id),
                       "senderId": str(self.session.account_id),
                       "createdAt": time.time()}
        return of_message(
            created,
            account_id=self.session.account_id,
            media=self._of_media_for_ids(vault_ids) if vault_ids else None,
            price=price_usd,
        )

    _UPLOAD_TYPE = 1
    _UPLOAD_STATUS_READY = 6
    # The five formInputs are replayed byte-for-byte; their meaning is not captured
    _UPLOAD_FORM_INPUTS = [
        {"type": 1001, "value": "false"}, {"type": 1002, "value": "false"},
        {"type": 1003, "value": ""}, {"type": 1004, "value": ""},
        {"type": 1005, "value": "\"\""},
    ]

    def _upload_session(self) -> "requests.Session":
        # self.http is not thread-safe and a presigned S3 PUT needs no auth: one bare session per part worker
        sess = requests.Session()
        if getattr(self.http, "proxies", None):
            sess.proxies.update(self.http.proxies)
        return sess

    def upload_media(self, file_path: Any, *,
                     content_type: str | None = None,
                     check_dedupe: bool = True,
                     watermark_text: str | None = None,
                     poll_timeout_s: float = 120.0,
                     poll_interval_s: float = 1.0) -> dict:
        # Vault uploads are PERMANENT (no delete endpoint): upload once and reuse the vault id
        import hashlib
        import mimetypes
        import time as _time
        from pathlib import Path as _Path
        path = _Path(str(file_path))
        if not path.exists():
            raise FileNotFoundError(str(path))
        ct = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        # Stream size and md5, never read_bytes: multi-GB videos in the relay that serves every account
        md5 = hashlib.md5()
        size = 0
        with path.open("rb") as fh:
            while chunk := fh.read(_UPLOAD_HASH_CHUNK):
                md5.update(chunk)
                size += len(chunk)
        md5_hex = md5.hexdigest()

        desc = self._request("POST", "/media/upload/create", base=MEDIA_BASE,
                             json_body={
                                 "fileSize": size,
                                 "mimeType": ct,
                                 "fileName": path.name,
                                 "uploadFormData": {
                                     "formInputs": list(self._UPLOAD_FORM_INPUTS)},
                             }) or {}
        upload_id = desc.get("id")
        parts = desc.get("parts") or []
        part_size = int(desc.get("partSize") or 0)
        if not upload_id or not parts or part_size <= 0:
            raise FanslyAPIError(
                f"/media/upload/create returned no upload id / parts for "
                f"{path.name}: {str(desc)[:200]}"
            )
        expected = max(1, -(-size // part_size))
        if len(parts) != expected:
            raise FanslyAPIError(
                f"upload/create returned {len(parts)} part(s) for a {size}-byte "
                f"file at partSize {part_size}, expected {expected}"
            )

        # Parts upload concurrently, each worker reading its own slice off disk; paired with OFClient.upload_media's part loop in service/of_client.py: retry/concurrency changes apply there too
        ordered = sorted(parts, key=lambda p: int(p.get("index", 0)))
        results: list[tuple[int, str] | None] = [None] * len(ordered)

        def _put_part(slot: int, part: dict) -> None:
            idx = int(part.get("index", 0))
            sess = self._upload_session()
            try:
                with path.open("rb") as fh:
                    fh.seek(idx * part_size)
                    chunk = fh.read(part_size)
                last: Exception | None = None
                for _attempt in range(3):
                    try:
                        put = sess.put(part["uploadUrl"], data=chunk,
                                       headers={"ngsw-bypass": "true"},
                                       timeout=max(float(self.timeout), 300.0))
                        if not put.ok:
                            raise FanslyAPIError(
                                f"S3 PUT part {idx} failed: {put.status_code} "
                                f"{put.text[:200]}", put)
                        etag = put.headers.get("ETag") or put.headers.get("etag")
                        if not etag:
                            raise FanslyAPIError(
                                f"S3 PUT part {idx} returned no ETag; "
                                f"complete needs it")
                        # S3 returns the ETag double-quoted and Fansly wants it echoed exactly that way
                        if not etag.startswith('"'):
                            etag = f'"{etag}"'
                        results[slot] = (idx, etag)
                        return
                    except FanslyAPIError:
                        raise
                    except Exception as e:
                        last = e
                        time.sleep(0.4)
                raise last or FanslyAPIError(f"S3 PUT part {idx} failed")
            finally:
                try:
                    sess.close()
                except Exception:   # noqa: BLE001 — a close must not mask the real error
                    pass

        workers = max(1, min(_UPLOAD_PART_CONCURRENCY, len(ordered)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_put_part, slot, part)
                       for slot, part in enumerate(ordered)]
            for fut in futures:
                fut.result()
        if any(r is None for r in results):
            raise FanslyAPIError(
                f"upload {upload_id} finished with missing parts")
        etags: list[tuple[int, str]] = [r for r in results if r is not None]

        self._request("POST", "/media/upload/complete", base=MEDIA_BASE,
                      json_body={
                          "id": str(upload_id),
                          "type": self._UPLOAD_TYPE,
                          "partSize": part_size,
                          "status": 0,
                          "parts": [{"index": i, "eTag": e} for i, e in etags],
                          "waitForComplete": 0,
                      })

        deadline = _time.monotonic() + poll_timeout_s
        state: dict = {}
        while True:
            state = self._request("GET", f"/media/upload/{upload_id}",
                                  base=MEDIA_BASE) or {}
            status = int(state.get("status") or 0)
            if status == self._UPLOAD_STATUS_READY and state.get("mediaId"):
                break
            if status > self._UPLOAD_STATUS_READY:
                raise FanslyAPIError(
                    f"upload {upload_id} ended in status {status} "
                    f"(no mediaId): {str(state)[:200]}")
            if _time.monotonic() >= deadline:
                raise FanslyAPIError(
                    f"upload {upload_id} still status {status} after "
                    f"{poll_timeout_s:.0f}s; not attaching an unfinished upload")
            _time.sleep(poll_interval_s)
        media_id = str(state["mediaId"])

        # /media?ids= returned nothing for a second or two after status 6: retry; an empty readback is reported, not fatal
        media: dict = {}
        for _ in range(4):
            try:
                media = self.vault_media_by_id(media_id) or {}
            except FanslyAPIError:
                media = {}
            if media:
                break
            _time.sleep(poll_interval_s)
        return {
            "ready": True,
            "vault_id": media_id,
            "deduped": False,
            "send_with": [media_id],
            "upload_id": str(upload_id),
            "upload_key": state.get("bucketKey"),
            "etag": etags[0][1].strip('"') if etags else None,
            "md5": md5_hex,
            "size": size,
            "filename": path.name,
            "stored_mime": state.get("mimeType"),
            "media": media,
            "existing": None,
            "note": f"uploaded — vault mediaId {media_id} (permanent; reuse it)",
        }


    def gif_trending(self, *, limit: int = 10, offset: int = 0) -> dict:
        resp = self._request("GET", "/gif-provider/featured")
        return _klipy_to_giphy(resp, offset=offset)

    def gif_search(self, query: str, *, limit: int = 10, offset: int = 0) -> dict:
        resp = self._request("GET", "/gif-provider/search", params={"search": query})
        return _klipy_to_giphy(resp, offset=offset)


    # Unmapped codes keep a fansly:<n> type (the frontend filters them out); metadata is passed through, never synthesized
    _NOTIF_TYPE_MAP = {
        7001: "tip",
        2007: "purchases", 2008: "purchases",
        32007: "purchases", 45012: "purchases",
        3002: "subscribed", 3003: "subscribed",
        15006: "subscribed", 15016: "subscribed",
        1002: "favorited", 2002: "favorited", 5003: "favorited",
        1004: "commented", 1005: "commented",
    }
    _NOTIF_LABELS = {
        7001: "sent a tip",
        2007: "purchased media", 2008: "purchased media",
        32007: "purchased locked text", 45012: "purchased a stream ticket",
        # A live unfollow DELETES the 3003 row: Fansly never renders an unfollow notification
        3003: "followed you", 3002: "follower update",
        15006: "subscribed", 15016: "subscribed", 15007: "subscription expired",
        15011: "promotion", 24001: "Fansly alert", 24002: "Fansly alert",
        1002: "liked your post", 2002: "liked your media",
        5003: "liked your message",
        1004: "replied to your post", 1005: "quoted your post",
    }

    # Which correlation id names the other account differs per code; None = no account id, skip hydration
    _NOTIF_ACTOR_FIELD = {
        3002: "correlationGroupId", 3003: "correlationGroupId",
        1002: "correlationId", 2002: "correlationId",
        5003: None, 1004: None, 1005: None,
    }

    @classmethod
    def _notif_actor_id(cls, row: dict, code: int | None) -> str:
        field = cls._NOTIF_ACTOR_FIELD.get(code, "correlationGroupId")
        return str(row.get(field) or "") if field else ""

    def _notification_rows(self) -> list:
        resp = self._request(
            "GET", "/notifications",
            params={"before": "0", "after": "0", "type": ""},
        )
        rows = resp.get("notifications") if isinstance(resp, dict) else None
        if not isinstance(rows, list):
            raise FanslyAPIError("GET /notifications: expected a notifications list")
        return rows

    def _of_notification(self, row: dict, users: dict) -> dict:
        code = _exact_int(row.get("type"))
        if code is None:
            code = -1
        who = self._notif_actor_id(row, code)
        user = users.get(who) if who else None
        label = self._NOTIF_LABELS.get(code, "notification")
        name = (user or {}).get("name") or (user or {}).get("username") or ""
        # Money rails read the amount out of the row text: a priced row must say its price
        price = _notif_price_usd(row, code) if code in _UNLOCK_NOTIF_TYPES else 0.0
        if price:
            label = f"{label} for ${price:.2f}"
        return {
            "id": str(row.get("id") or ""),
            # An unmapped code stays namespaced: a mislabeled money event is worse than a hidden one
            "type": self._NOTIF_TYPE_MAP.get(code, f"fansly:{code}"),
            "text": f"{name} {label}".strip() if name else label,
            "createdAt": _iso(row.get("createdAt")),
            "isRead": bool(row.get("acknowledgedAt")),
            "user": user or None,
            "metadata": row.get("metadata"),
            "fanslyType": code,
            "fanslyPriceUsd": price,
        }

    def purchases(self) -> PurchaseFeed:
        sales: list[dict] = []
        seen: dict[str, int] = {}
        for row in self._notification_rows():
            if not isinstance(row, dict):
                continue
            code = _exact_int(row.get("type"))
            if code is None:
                seen["invalid_type"] = seen.get("invalid_type", 0) + 1
                continue
            if code in _UNBANKED_WATCHED:
                seen[str(code)] = seen.get(str(code), 0) + 1
            key = _BANKING_SET.get(code)
            if key is None:
                continue
            meta = _price_metadata(row)
            units = _meta_units(meta, key)
            if units == 0:
                continue
            if units is None or units > _MAX_PURCHASE_UNITS:
                seen[f"{code}_unpriced"] = seen.get(f"{code}_unpriced", 0) + 1
                continue
            nid = row.get("id")
            if not nid or _exact_int(nid) is None:
                seen[f"{code}_malformed"] = seen.get(f"{code}_malformed", 0) + 1
                continue
            sales.append({
                "id": str(nid),
                "fan_id": str(row.get("correlationGroupId") or ""),
                "grant_id": str(row.get("correlationId") or ""),
                "price_usd": units / FANSLY_PRICE_UNIT,
                "created_at": row.get("createdAt"),
                "code": code,
            })
        return PurchaseFeed(sales=sales, unbanked_seen=seen)

    def notifications(self, *, limit: int = 10, offset: int = 0,
                      type: str | None = None, **_ignored: Any) -> dict:
        rows = self._notification_rows()
        who = {self._notif_actor_id(r, _exact_int(r.get("type")))
               for r in rows if isinstance(r, dict)}
        who.discard("")
        users: dict = {}
        if who:
            try:
                users = self.list_users(sorted(who)) or {}
            except FanslyAPIError:
                # A failing profile lookup must not empty the feed: the row is the notification
                log.warning("notifications: profile hydration failed", exc_info=True)
        items = [self._of_notification(r, users) for r in rows if isinstance(r, dict)]
        if type:
            want = str(type).lower()
            items = [i for i in items if i["type"] == want]
        page = items[offset:offset + limit] if limit else items
        return {"list": page, "hasMore": offset + len(page) < len(items)}

    def notifications_count(self, **_ignored: Any) -> dict:
        try:
            rows = self._notification_rows()
        except FanslyAPIError:
            log.warning("notifications_count: fetch failed", exc_info=True)
            rows = []
        buckets = {"subscribes": 0, "tips": 0, "comments": 0, "mentions": 0,
                   "hearts": 0, "gifts": 0, "all": 0}
        by_of_type = {"subscribed": "subscribes", "tip": "tips",
                      "commented": "comments", "favorited": "hearts"}
        for row in rows:
            if not isinstance(row, dict) or row.get("acknowledgedAt"):
                continue
            code = _exact_int(row.get("type"))
            if code is None:
                continue
            buckets["all"] += 1
            key = by_of_type.get(self._NOTIF_TYPE_MAP.get(code, ""))
            if key:
                buckets[key] += 1
        return buckets

    def notifications_read(self, **_ignored: Any) -> dict:
        # Body is bundle-derived, not live-captured: re-read the feed after the ack so an ignored ack leaves the badge up
        rows = [r for r in self._notification_rows() if isinstance(r, dict)]
        newest = str(rows[0].get("id") or "") if rows else ""
        if not (newest and any(not r.get("acknowledgedAt") for r in rows)):
            return {"counters": {"subscribes": 0, "tips": 0, "comments": 0, "mentions": 0,
                                 "hearts": 0, "gifts": 0, "all": 0}}
        self._request("POST", "/notifications/ack", json_body={"beforeAnd": newest, "type": ""})
        return {"counters": self.notifications_count()}


    def list_posts(self, *, limit: int = 10, offset: int = 0, **_ignored: Any) -> dict:
        return self.user_posts(self.session.account_id, limit=limit, offset=offset)

    def user_posts(self, user_id: str | int, *, limit: int = 10,
                   offset: int = 0, **_ignored: Any) -> dict:
        tl = self._request("GET", f"/timelinenew/{user_id}") or {}
        page = of_posts_page(tl, limit=limit)
        rows = page["list"][offset:offset + limit] if limit else page["list"]
        return {"list": rows, "hasMore": offset + len(rows) < len(page["list"])}

    def get_post(self, post_id: int | str) -> dict:
        resp = self._request("GET", "/post", params={"ids": str(post_id)}) or {}
        posts = resp.get("posts") if isinstance(resp, dict) else None
        if not posts:
            return {}
        am_by_id, bundle_by_id = _media_indexes(resp)
        return of_post(posts[0],
                       media=_resolve_attachments(posts[0], am_by_id, bundle_by_id))


    def payout_balances(self, **_ignored: Any) -> dict:
        wallets = self._request("GET", "/payments/wallets") or []
        total = 0.0
        for w in wallets if isinstance(wallets, list) else []:
            try:
                total += float(w.get("balance") or 0)
            except (TypeError, ValueError):
                pass
        return {"total": total, "wallets": wallets if isinstance(wallets, list) else []}

    def payout_requests(self, *, limit: int = 10, offset: int = 0,
                        **_ignored: Any) -> dict:
        return {"list": [], "hasMore": False}


    def _subscribers_payload(self, *, before: str | None = None) -> dict:
        params: dict[str, Any] = {}
        if before:
            params["before"] = str(before)
        return self._request("GET", "/subscribers", params=params) or {}

    _SUB_STATUS_ACTIVE = 3

    def _of_subscriber(self, row: dict, users: dict) -> dict:
        sid = str(row.get("subscriberId") or "")
        fan = dict(users.get(sid) or {"id": sid, "name": "", "username": ""})
        # Money is 1/1000-dollar units; times on this object are ms, unlike the seconds on notification rows
        renew = row.get("renewPrice") if row.get("renewPrice") is not None else row.get("price")
        ms = lambda v: _iso(float(v) / 1000.0) if v else None  # noqa: E731
        fan.update({
            "subscribedBy": row.get("status") == self._SUB_STATUS_ACTIVE,
            "subscribedByExpireDate": ms(row.get("endsAt")),
            "subscribedOnData": {"subscribeAt": ms(row.get("createdAt")),
                                 "expiredAt": ms(row.get("endsAt")),
                                 "renew": bool(row.get("autoRenew"))},
            "subscribePrice": (renew or 0) / 1000.0,
            "currentSubscribePrice": (row.get("price") or 0) / 1000.0,
            "fanslySubscription": {k: row.get(k) for k in (
                "id", "subscriptionTierId", "subscriptionTierName", "planId",
                "status", "giftCodeId", "autoRenew", "billingCycle", "duration")},
        })
        return fan

    def subscribers(self, *, type: str = "active", limit: int = 10,
                    offset: int = 0, online: bool = False,
                    **_ignored: Any) -> dict:
        payload = self._subscribers_payload()
        rows = [r for r in (payload.get("subscriptions") or []) if isinstance(r, dict)]
        want = str(type or "active").lower()
        if want == "active":
            rows = [r for r in rows if r.get("status") == self._SUB_STATUS_ACTIVE]
        elif want == "expired":
            rows = [r for r in rows if r.get("status") != self._SUB_STATUS_ACTIVE]
        ids = sorted({str(r.get("subscriberId") or "") for r in rows} - {""})
        users: dict = {}
        if ids:
            try:
                users = self.list_users(ids) or {}
            except FanslyAPIError:
                log.warning("subscribers: profile hydration failed", exc_info=True)
        fans = [self._of_subscriber(r, users) for r in rows]
        if online:
            fans = [f for f in fans if f.get("isOnline")]
        page = fans[offset:offset + limit] if limit else fans
        return {"list": page, "hasMore": offset + len(page) < len(fans)}

    def iter_online_subscribers(self, *, type: str = "active",
                                page_size: int = 20, max_fans: int = 1000,
                                **_ignored: Any) -> list[dict]:
        return self.subscribers(type=type, limit=max_fans, online=True)["list"]

    def subscription_counts(self, **_ignored: Any) -> dict:
        stats = (self._subscribers_payload().get("stats") or {})
        return {
            "active": stats.get("totalActive") or 0,
            "expired": stats.get("totalExpired") or 0,
            "all": stats.get("total") or 0,
        }

    def subscription_counts_all(self, **_ignored: Any) -> dict:
        return self.subscription_counts()


    # OF's get_pinned_messages returns the ROWS, not an envelope: a {"list": []} would hand callers the string "list"
    @fansly_unsupported("Fansly has no message pinning", returns=list)
    def get_pinned_messages(self, *_a: Any, **_k: Any) -> list: ...

    def schedules(self, **_ignored: Any) -> dict:
        resp = self._request("GET", "/post/scheduled") or {}
        rows = resp.get("scheduledPosts") if isinstance(resp, dict) else None
        out = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not row.get("postId") or row.get("status") == 3:
                continue
            try:
                when = _iso(float(row.get("scheduledFor")) / 1000.0)
            except (TypeError, ValueError):
                when = None
            template = row.get("postTemplate") if isinstance(row.get("postTemplate"), dict) else {}
            pid = str(row["postId"])
            out.append({"id": pid, "type": "post", "publishDateTime": when,
                        "entity": {"id": pid, "text": str(template.get("content") or "")}})
        out.sort(key=lambda i: i["publishDateTime"] or "")
        return {"list": out, "hasMore": False}

    # Scan runs to the thread's end: reaching a read message proves nothing about older ones. A partial scan acks nothing; unread older than the newest 200 messages is not seen
    _ACK_PAGE = 50
    _ACK_SCAN_PAGES = 4

    def _unread_message_ids(self, group_id: str) -> tuple[list[str], bool] | None:
        me = str(self.session.account_id)
        out: list[str] = []
        before = ""
        for _ in range(self._ACK_SCAN_PAGES):
            params = {"groupId": str(group_id), "limit": str(self._ACK_PAGE)}
            if before:
                params["before"] = before
            try:
                payload = self._request("GET", "/message", params=params) or {}
            except FanslyAPIError:
                log.warning("unread scan failed for group %s", group_id, exc_info=True)
                return None
            msgs = payload.get("messages") or []
            for msg in msgs:
                if not isinstance(msg, dict) or str(msg.get("senderId") or "") == me:
                    continue
                unread = any(
                    str(i.get("userId") or "") == me and not i.get("readAt")
                    for i in (msg.get("interactions") or [])
                    if isinstance(i, dict)
                )
                if unread and msg.get("id"):
                    out.append(str(msg["id"]))
            if len(msgs) < self._ACK_PAGE:
                return out, True
            before = str(msgs[-1].get("id") or "") if isinstance(msgs[-1], dict) else ""
            if not before:
                break
        return out, not out

    def mark_chat_read(self, chat_id: str | int) -> dict:
        # Ack EVERY unread message id: acking lastUnreadMessageId clears the pointer, not unreadCount (measured). No ack on send: a reply already reads as cleared in of_chat_row
        group_id = self._as_group_id(chat_id)
        scan = self._unread_message_ids(group_id)
        if scan is None:
            return {"success": False, "reason": "scan_failed"}
        message_ids, complete = scan
        if not complete:
            return {"success": False, "reason": "partial"}
        if not message_ids:
            return {"success": True}
        try:
            self._request(
                "POST", "/message/ack",
                json_body={"messageIds": message_ids, "type": 2},
            )
        except FanslyAPIError as e:
            # A stale unread pointer (400 code=99) stays blue in Fansly's own client too: report the miss, don't 502 a chat-open
            log.warning("fansly ack failed for group %s (msgs %s): %s",
                        group_id, message_ids, e)
            return {"success": False, "reason": "ack_rejected"}
        return {"success": True}

    # Fansly's Mark as Unread is client-side only (no server unread state): 501 instead of a success the next read takes back
    @fansly_unsupported("Fansly has no server-side unread state",
                        returns=lambda: {"success": True})
    def mark_chat_unread(self, *_a: Any, **_k: Any) -> dict: ...

    # Caps threads acked per mark-all so an upstream misread can mis-ack at most this many
    _MARK_ALL_CAP = 50

    def mark_all_chats_read(self, **_ignored: Any) -> dict:
        groups = self._request(
            "GET", "/messaging/groups",
            params={"sortOrder": "1", "flags": "0", "subscriptionTierId": "",
                    "listIds": "", "search": "", "limit": "100", "offset": "0"},
        )
        rows = groups.get("data") or []
        unread = [m for m in rows if isinstance(m, dict) and m.get("groupId")
                  and int(m.get("unreadCount") or 0)]
        partial = len(rows) >= 100 or len(unread) > self._MARK_ALL_CAP
        message_ids: list[str] = []
        acked_fans: list[str] = []
        for m in unread[: self._MARK_ALL_CAP]:
            scan = self._unread_message_ids(str(m["groupId"]))
            if scan is None:
                partial = True
                continue
            ids, complete = scan
            if not complete:
                partial = True
                continue
            message_ids.extend(ids)
            fan = str(m.get("partnerAccountId") or "")
            if fan.isdigit():
                acked_fans.append(fan)
        if message_ids:
            try:
                self._request(
                    "POST", "/message/ack",
                    json_body={"messageIds": message_ids, "type": 2},
                )
            except FanslyAPIError as e:
                log.warning("fansly mark-all ack failed (%d ids across %d threads): %s",
                            len(message_ids), len(unread), e)
                return {"success": False, "reason": "ack_rejected"}
        if partial:
            return {"success": True, "partial": True, "acked_fan_ids": acked_fans}
        return {"success": True}

    def transactions(self, *, limit: int = 20, offset: int = 0,
                     type: str | None = None, start: str | None = None,
                     end: str | None = None, **_ignored: Any) -> dict:
        return {"list": [], "hasMore": False}


    @property
    def _known_group_ids(self) -> set[str]:
        cache = self.__dict__.get("_group_id_cache")
        if cache is None:
            cache = set()
            self.__dict__["_group_id_cache"] = cache
        return cache

    @property
    def _fan_to_group(self) -> dict[str, str]:
        cache = self.__dict__.get("_fan_group_map")
        if cache is None:
            cache = {}
            self.__dict__["_fan_group_map"] = cache
        return cache

    @property
    def _group_to_fan(self) -> dict[str, str]:
        cache = self.__dict__.get("_group_fan_map")
        if cache is None:
            cache = {}
            self.__dict__["_group_fan_map"] = cache
        return cache

    def _purchases_by_fan(self) -> dict:
        # Keyed by BUYER: the feed is account-wide, so a flat grant set would unlock fan B when fan A bought the same item. Cached as one object, not per fan
        # /notifications is one page, so old purchases scroll off: the unlock survives via db.models.is_paid_ratchet (messages.is_paid); keep in step
        lock = self.__dict__.setdefault("_purchase_lock", threading.Lock())
        # Single-flight: a process-wide singleton on a 64-thread pool; hold the lock across the fetch so losers read the winner's result
        with lock:
            cached = getattr(self, "_purchase_cache", None)
            if cached and (time.time() - cached[0]) < _PURCHASE_TTL_S:
                return cached[1]
            try:
                rows = self._notification_rows()
            except (FanslyAPIError, requests.RequestException):
                # Narrow on purpose: a shape-change TypeError must not become "nothing purchased" (every PPV locked, no log)
                log.warning("purchase_feed_failed account=%s",
                            self.session.account_id, exc_info=True)
                return cached[1] if cached else {}
            by_fan: dict = {}
            for row in rows:
                if not isinstance(row, dict) or _exact_int(row.get("type")) not in _UNLOCK_NOTIF_TYPES:
                    continue
                buyer = str(row.get("correlationGroupId") or "")
                bought = str(row.get("correlationId") or "")
                if buyer and bought:
                    by_fan.setdefault(buyer, set()).add(bought)
            frozen = {k: frozenset(v) for k, v in by_fan.items()}
            self._purchase_cache = (time.time(), frozen)
            return frozen

    def _fan_id_for_group(self, group_id: str | int) -> str | None:
        gid = str(group_id)
        hit = self._group_to_fan.get(gid)
        if hit:
            return hit
        offset = 0
        while offset < 200:
            rows = (self.groups(limit=20, offset=offset) or {}).get("data") or []
            for row in rows:
                fan, grp = row.get("partnerAccountId"), row.get("groupId")
                if fan and grp:
                    self._group_to_fan[str(grp)] = str(fan)
                    self._fan_to_group[str(fan)] = str(grp)
            if gid in self._group_to_fan:
                return self._group_to_fan[gid]
            if len(rows) < 20:
                return None
            offset += 20
        return None


    def follow_user(self, user_id: str | int, **_ignored: Any) -> dict:
        # A 422 here is account policy (code 2 system account, code 5 no free follow): return a skip, a retry never succeeds
        try:
            self._request("POST", f"/account/{user_id}/followers")
        except FanslyAPIError as exc:
            if "422" in str(exc):
                log.info("fansly: %s does not accept a free follow (%s)",
                         user_id, exc)
                return {"success": False, "skipped": "not-followable"}
            raise
        return {"success": True}

    def unfollow_user(self, user_id: str | int, **_ignored: Any) -> dict:
        self._request("POST", f"/account/{user_id}/followers/remove")
        return {"success": True}

    # Heart is type 1 (captured) but not the picker index; the other six codes are unknown: do not guess
    _REACTION_HEART = 1

    def like_message(self, message_id: str | int, *_a: Any,
                     **_ignored: Any) -> dict:
        # Only the counterparty's message can be reacted to: skip rather than take down the automation
        try:
            self._request("POST", "/message/like", json_body={
                "messageId": str(message_id), "type": self._REACTION_HEART})
        except FanslyAPIError as exc:
            log.info("fansly: could not react to message %s (%s)",
                     message_id, exc)
            return {"success": False, "skipped": "not-likeable"}
        return {"success": True}

    def unsend_message(self, message_id: str | int, *_a: Any,
                       **_ignored: Any) -> dict:
        self._request("POST", "/message/delete",
                      json_body={"messageId": str(message_id)})
        return {"success": True}

    def _main_wall_id(self) -> str | None:
        if self.__dict__.get("_wall_id"):
            return self.__dict__["_wall_id"]
        account = self._request("GET", "/account/me").get("account") or {}
        walls = account.get("walls") or []
        wall = next((w for w in walls if w.get("mainWall")), None) \
            or next((w for w in walls if w.get("defaultWall")), None) \
            or (walls[0] if walls else None)
        wid = str(wall["id"]) if wall and wall.get("id") else None
        self.__dict__["_wall_id"] = wid
        return wid

    def create_post(self, text: str = "", *, media_files: Any = None,
                    scheduled_for: Any = None, **_ignored: Any) -> dict:
        # scheduledFor is MILLISECONDS here (seconds in the message lane): a seconds value reads as 1970 and posts immediately
        text = _guard_outbound(text)
        wall_id = self._main_wall_id()
        if not wall_id:
            raise FanslyAPIError(
                "Cannot create a Fansly post: the account exposes no wall to "
                "post to (POST /post requires wallIds).")
        media_files = list(media_files or [])
        if media_files:
            # Wall-post whitelist/pricing is uncaptured: guessing risks publishing paid media free to everyone
            raise FanslyAPIError(
                "Attaching media to a Fansly post is not wired yet — the "
                "post-side grant shape is uncaptured. Post text only.")
        body: dict[str, Any] = {
            "content": text or "",
            "fypFlags": 0,
            "inReplyTo": None,
            "quotedPostId": None,
            "attachments": [],
            "scheduledFor": int(float(scheduled_for) * 1000) if scheduled_for else 0,
            "expiresAt": 0,
            "postReplyPermissionFlags": [],
            "pinned": 0,
            "wallIds": [wall_id],
            "pinWallIds": [],
        }
        # _request already unwraps {success, response}: reading "response" again yields {} and the caller gets id=None, a live post nobody can delete
        post = self._request("POST", "/post", json_body=body) or {}
        post = post if isinstance(post, dict) else {}
        # A scheduled create omits the id (surfaces as postId in the queue): don't invent one
        pid = post.get("id")
        return {"success": True, "id": str(pid) if pid else None,
                "scheduled": bool(body["scheduledFor"])}

    def delete_post(self, post_id: str | int, **_ignored: Any) -> dict:
        # On a scheduled post this 422s (code 99): use cancel_scheduled
        self._request("POST", f"/post/{post_id}/delete")
        return {"success": True}

    def cancel_scheduled(self, post_id: str | int, **_ignored: Any) -> dict:
        # Alias: the relay's message-queue cancel reaches this with a post id; there is no scheduled-message queue
        self._request("POST", f"/post/scheduled/{post_id}/cancel")
        return {"success": True}

    def add_user_to_list(self, list_id: str | int, user_id: str | int,
                         **_ignored: Any) -> dict:
        self.add_users_to_lists({list_id: [user_id]})
        return {"success": True}

    def add_users_to_lists(self, users_by_list: dict[str, list[int]],
                           **_ignored: Any) -> dict[str, list[str]]:
        sent = {str(lid): [str(u) for u in users] for lid, users in users_by_list.items()}
        echoed = self._request("POST", "/lists/commands", json_body={"listCommands": [
            {"type": 1, "listItem": {"id": uid, "listId": lid}}
            for lid, uids in sent.items() for uid in uids]})
        if not isinstance(echoed, list):
            raise FanslyAPIError(f"POST /lists/commands echoed {type(echoed).__name__}, not the command array")
        out: dict[str, list[str]] = {lid: [] for lid in sent}
        for cmd in echoed:
            item = cmd.get("listItem") or {}
            if cmd.get("type") == 1 and str(item.get("listId")) in out:
                out[str(item["listId"])].append(str(item["id"]))
        return out

    def remove_user_from_list(self, list_id: str | int, user_id: str | int,
                              **_ignored: Any) -> dict:
        # Add and remove take DIFFERENT payloads: the add shape sent for a remove is accepted and silently does nothing
        self._request("POST", "/lists/commands", json_body={"listCommands": [
            {"type": 2, "listId": str(list_id),
             "itemIds": [str(user_id)]}]})
        return {"success": True}

    def create_list(self, name: str, description: str = "",
                    **_ignored: Any) -> dict:
        row = self._request("POST", "/lists", json_body={
            "label": name, "description": description or ""}) or {}
        row = row if isinstance(row, dict) else {}
        return {"id": str(row["id"]) if row.get("id") else None,
                "name": row.get("label") or name}

    def get_lists(self, **_ignored: Any) -> dict:
        rows = self._request("GET", "/lists/account",
                             params={"itemId": ""}) or []
        rows = rows if isinstance(rows, list) else []
        return {"list": [{"id": str(r.get("id")), "name": r.get("label") or ""}
                         for r in rows if isinstance(r, dict) and r.get("id")],
                "hasMore": False}


    @fansly_unsupported("Fansly has no message pinning",
                        returns=lambda: {"success": True})
    def pin_message(self, *_a: Any, **_k: Any) -> dict: ...

    @fansly_unsupported("Fansly has no message pinning",
                        returns=lambda: {"success": True})
    def unpin_message(self, *_a: Any, **_k: Any) -> dict: ...

    @fansly_unsupported("Fansly vault media cannot be deleted",
                        returns=lambda: {"success": False})
    def hide_vault_media(self, *_a: Any, **_k: Any) -> dict: ...

    @fansly_unsupported("Fansly has no vault hash lookup", returns=None)
    def vault_media_lookup_hash(self, *_a: Any, **_k: Any) -> None: ...

    @fansly_unsupported("Fansly stories cannot be created from the web API",
                        returns=lambda: {"success": False})
    def post_story_from_url(self, *_a: Any, **_k: Any) -> dict: ...

    @fansly_unsupported("Fansly stories are not creatable, so none exist",
                        returns=lambda: {"success": False})
    def delete_story(self, *_a: Any, **_k: Any) -> dict: ...


    @fansly_unsupported(
        "Fansly reports subscriber TOTALS only, with no per-day series; "
        "synthesising one would be invented analytics",
        returns=lambda: {"subscribers": 0, "subscribes": [], "earnings": [],
                         "total": 0, "delta": 0})
    def subscribers_chart(self, *_a: Any, **_k: Any) -> dict: ...


    # GATED: derived from the JS bundle, never run against a server. Include/exclude differ by a trailing +1 (30000/30001): inverting it blasts the audience meant to be suppressed; idempotency unknown; a mass send is unrecallable
    _BROADCAST_GROUP_TYPE = 3
    _BROADCAST_GROUP_FLAGS = 32
    _LISTS_SERVICE_ID = 30
    RECIPIENT_INCLUDE_LIST = _LISTS_SERVICE_ID * 1000
    RECIPIENT_EXCLUDE_LIST = _LISTS_SERVICE_ID * 1000 + 1

    def _broadcast_group(self, *, include_lists: list, exclude_lists: list,
                         tier_id: Any = None) -> str:
        recipients = [{"recipientId": str(i),
                       "type": self.RECIPIENT_INCLUDE_LIST}
                      for i in include_lists]
        recipients += [{"recipientId": str(i),
                        "type": self.RECIPIENT_EXCLUDE_LIST}
                       for i in exclude_lists]
        if not recipients:
            raise FanslyAPIError(
                "A broadcast needs at least one recipient list — a group with "
                "no audience is not a safe thing to guess the meaning of.")
        metadata = ""
        if tier_id:
            metadata = _json.dumps(
                {"4": _json.dumps({"subscriptionTierId": str(tier_id)},
                                  separators=(",", ":"))},
                separators=(",", ":"))
        body = {
            "type": self._BROADCAST_GROUP_TYPE,
            "groupFlags": self._BROADCAST_GROUP_FLAGS,
            "groupFlagsMetadata": metadata,
            "users": [{"userId": str(self.session.account_id),
                       "permissionFlags": 65535}],
            "recipients": recipients,
            "lastMessage": None,
            "userSettings": None,
        }
        group = self._request("POST", "/group", json_body=body) or {}
        gid = group.get("id") if isinstance(group, dict) else None
        if not gid:
            raise FanslyAPIError(
                "POST /group accepted the broadcast group but returned no id.")
        return str(gid)

    def send_mass_message(self, text: str = "", *, media_files: Any = None,
                          price: Any = 0, include_lists: Any = None,
                          exclude_lists: Any = None, tier_id: Any = None,
                          confirm_live_broadcast: bool = False,
                          **_ignored: Any) -> dict:
        include_lists = [i for i in (include_lists or []) if i]
        exclude_lists = [i for i in (exclude_lists or []) if i]
        if not confirm_live_broadcast:
            raise FanslyBlocked(f"send_mass_message: {_BROADCAST_UNCONFIRMED}")
        # Before the broadcast group is minted: a blocked text creates nothing
        text = _guard_outbound(text)
        check_sendable(media_files=media_files, price=price)
        group_id = self._broadcast_group(include_lists=include_lists,
                                         exclude_lists=exclude_lists,
                                         tier_id=tier_id)
        log.warning("fansly: BROADCASTING to group %s (include=%s exclude=%s)",
                    group_id, include_lists, exclude_lists)
        created = self.send_message(group_id, text, media_files=media_files,
                                    price=price, _broadcast=True)
        return {"success": True, "groupId": group_id,
                "id": str(created.get("id")) if created.get("id") else None}

    send_mass_message.fansly_blocked = _BROADCAST_UNCONFIRMED

    @fansly_blocked("needs an expired subscription to capture",
                    returns=lambda: {"list": [], "hasMore": False})
    def recent_expired_subscribers(self, *_a: Any, **_k: Any) -> dict: ...

    @fansly_blocked("resubscribe moves money — needs a payment method")
    def resubscribe_user(self, *_a: Any, **_k: Any) -> dict: ...

    def delete_promo(self, promo_id: str | int, **_ignored: Any) -> dict:
        # No delete verb: a gift code is disabled by re-POSTing the whole object with status 2
        codes = self._request("GET", "/subscriptions/giftcodes") or []
        cur = next((g for g in codes if isinstance(g, dict)
                    and str(g.get("id")) == str(promo_id)), None)
        if not cur:
            return {"success": False, "skipped": "not-found"}
        self._request("POST", "/subscriptions/giftcodes",
                      json_body={**cur, "status": 2})
        return {"success": True}

    def _first_plan(self) -> dict | None:
        tiers = self._request("GET", "/subscriptions/tiers") or []
        for t in tiers if isinstance(tiers, list) else []:
            for p in (t.get("plans") or []):
                if p.get("status") == 1 and p.get("id"):
                    return {**p, "tierId": t.get("id"), "tierName": t.get("name")}
        return None

    def create_promo(self, *, subscribe_counts: int = 1, subscribe_days: int = 30,
                     discount: int | None = None, message: str = "",
                     **_ignored: Any) -> dict:
        if discount is None:
            raise ValueError("create_promo requires discount (integer percent 1-100)")
        pct = max(1, min(int(discount), 100))
        plan = self._first_plan()
        if not plan:
            raise FanslyAPIError("Cannot create a Fansly promo: the account has "
                                 "no active subscription plan (create a tier first).")
        full = int(plan.get("price") or 0)
        promo_price = int(round(full * (100 - pct) / 100.0))
        created = self._request("POST", "/subscriptions/giftcodes", json_body={
            "id": "", "label": message or "", "planId": str(plan["id"]),
            "price": promo_price, "duration": int(subscribe_days),
            "maxUses": int(subscribe_counts), "newSubscribersOnly": 1,
            "startsAt": 0, "endsAt": 0,
        }) or {}
        return {
            "id": str(created.get("id") or ""),
            "price": (created.get("price") or 0) / 1000.0,
            "subscribeCounts": created.get("maxUses"),
            "subscribeDays": created.get("duration"),
            "message": created.get("label") or "",
            "isFinished": created.get("status") != 1,
            "canClaim": created.get("status") == 1,
            "claimsCount": created.get("uses") or 0,
            "fanslyGiftCode": {"code": created.get("code"), "planId": created.get("planId"),
                               "tierId": plan.get("tierId"),
                               "link": f"https://fansly.com/subscriptions/giftcode/{created.get('code')}"
                               if created.get("code") else None},
        }

    @fansly_blocked("post likes are out of go-live scope (YAGNI)",
                    returns=lambda: {"success": False, "skipped": "not-wired"})
    def like_post(self, *_a: Any, **_k: Any) -> dict: ...

    @fansly_unsupported("Fansly has no server-side message template store", returns=None)
    def message_templates(self, *_a: Any, **_k: Any) -> None: ...

    @fansly_unsupported("Fansly has no OnlyFans settings object; the follow-rule mirror waits for a paid-subscribe capture",
                        returns=None)
    def my_settings(self, *_a: Any, **_k: Any) -> None: ...

    def _group_for_send(self, chat_id: str | int) -> str:
        # A send to a fan with no DM thread mints a group (POST /group): a fan id as groupId 500s. Reads must not mint
        chat_id = str(chat_id)
        resolved = self._as_group_id(chat_id)
        if resolved != chat_id or chat_id in self._known_group_ids:
            return resolved
        # Re-scan the WHOLE listing before minting: find_group_with only covers the 100 newest, an older thread would get a duplicate
        existing = self.find_group_with(chat_id, scan_limit=10_000)
        if existing:
            self._known_group_ids.add(existing)
            self._fan_to_group[chat_id] = existing
            return existing
        created = self.create_group(chat_id)
        if not created:
            raise FanslyAPIError(
                f"Fansly accepted POST /group for fan {chat_id} but returned "
                f"no group id, so there is no thread to send into."
            )
        self._known_group_ids.add(created)
        self._fan_to_group[chat_id] = created
        log.info("fansly: minted DM group %s for fan %s (first message)",
                 created, chat_id)
        return created

    def _as_group_id(self, chat_id: str | int) -> str:
        chat_id = str(chat_id)
        if chat_id in self._known_group_ids:
            return chat_id
        mapped = self._fan_to_group.get(chat_id)
        if mapped:
            return mapped
        resolved = self.find_group_with(chat_id)
        if resolved:
            self._known_group_ids.add(resolved)
            return resolved
        return chat_id


_BLOCKED, _UNSUPPORTED = "blocked", "unsupported"
_STATS = (_BLOCKED, "Fansly stats read not captured")
_PROFILE = (_BLOCKED, "Fansly profile or account setting not captured")
_LABELS = (_BLOCKED, "Fansly post labels not captured")
_RELEASE = (_BLOCKED, "Fansly release forms not captured")
_POSTS = (_BLOCKED, "Fansly post action or read not captured")
_LINKS = (_BLOCKED, "Fansly tracking links, trials and promotions not captured")
_CHAT = (_BLOCKED, "Fansly chat action not captured")
_OF_SEND = (_UNSUPPORTED, "Fansly sends through send_message; OnlyFans's prepare/post/schedule split is not mapped")
_LISTS = (_BLOCKED, "Fansly list read or setting not captured")
_STORIES = (_BLOCKED, "Fansly story read or setting not captured")
_STREAMS = (_BLOCKED, "Fansly livestreams not captured")
_SUBS = (_BLOCKED, "Fansly subscription tiers and bundles not captured")
_PAYOUTS = (_BLOCKED, "Fansly payouts not captured")
_QUEUE = (_BLOCKED, "Fansly scheduled-message queue not captured")
_FANS = (_BLOCKED, "Fansly fan roster, media or search read not captured")
_NO_PIN = (_UNSUPPORTED, "Fansly has no message pinning")
_NO_STORY_WRITE = (_UNSUPPORTED, "Fansly stories cannot be created from the web API")
_OF_UPLOAD = (_UNSUPPORTED, "OnlyFans upload-claim pipeline; Fansly uploads through upload_media")

UNBUILT: dict[str, tuple[str, str]] = {
    "list_users_in": (_BLOCKED, "list members read not captured"),
    "rename_list": (_BLOCKED, "list rename not captured"),
    "delete_list": (_BLOCKED, "list delete not captured (its row menu needs a trusted event)"),
    "block_user": (_BLOCKED, "block not captured"),
    "unblock_user": (_BLOCKED, "unblock not captured"),
    "search_users": (_BLOCKED, "username search not captured"),
    "engagement_messages": (_BLOCKED, "mass-message stats feed not captured"),
    "mass_message_history": (_BLOCKED, "mass-message history not captured"),
    "schedule_mass_message": (_BLOCKED, "scheduled broadcast not captured"),
    "restrict_user": (_UNSUPPORTED, "Fansly has no restrict"),
    "unrestrict_user": (_UNSUPPORTED, "Fansly has no restrict"),
    "search_chat": (_UNSUPPORTED, "Fansly has no in-thread message search"),
    "set_subscription_discount": (_UNSUPPORTED, "Fansly has no per-fan subscription discount"),
    "delete_chat": (_UNSUPPORTED, "no capture or bundle note names a Fansly chat delete"),
    "chat_media": (_BLOCKED, "chat media gallery not captured"),
    **dict.fromkeys(("bookmarks_all", "campaign_claimers", "campaigns_chart", "campaigns_stats", "chargebacks",
                     "chargebacks_chart", "chargebacks_ratio", "earnings_chart", "fans_activity", "mass_message_buyers",
                     "messages_chart", "my_profile_stats", "my_start_date", "my_stats_overview", "my_stats_top_posts",
                     "notification_settings", "offer_claims", "payout_invoice", "payouts_chart", "promotions_chart",
                     "promotions_stats", "qr_views", "referral_payouts", "referrals", "referrals_balance",
                     "referrals_chart", "sessions", "social_buttons", "social_media_providers", "stats_top",
                     "stories_chart", "stories_top", "story_viewers", "streaks", "streaks_top", "stream_blocked_users",
                     "stream_viewers", "streams_chart", "streams_top", "subscribers_latest", "subscribers_top",
                     "today_activity", "trials_chart", "trials_stats"), _STATS),
    **dict.fromkeys(("add_social_button", "add_users_link", "close_all_sessions", "countries", "create_guest",
                     "delete_social_button", "delete_users_link", "patch_notification_settings",
                     "patch_security_settings", "put_security_settings", "set_reply_on_subscribe", "update_profile",
                     "users_links"), _PROFILE),
    **dict.fromkeys(("create_label", "labels", "sort_labels"), _LABELS),
    **dict.fromkeys(("release_form_mentions", "release_forms", "toggle_release_form"), _RELEASE),
    **dict.fromkeys(("archive_post", "comment_on_post", "edit_post", "pin_post", "post_comments", "post_stats",
                     "post_users", "posts_chart", "posts_top", "publish_schedule", "save_queued_post",
                     "schedules_later_chat", "schedules_later_post", "search_posts", "tagged_friend_users",
                     "unlike_post", "unpin_post"), _POSTS),
    **dict.fromkeys(("create_tracking_link", "create_trial_link", "delete_tracking_link", "delete_trial_link",
                     "finish_promo", "promotions", "share_campaign_stats", "share_trial_stats", "tracking_links",
                     "tracking_links_shared_with_me", "tracking_links_sorted", "trial_links", "trial_links_sorted",
                     "trials_shared_with_me", "unshare_campaign_stats", "add_link_claimers_to_list"), _LINKS),
    **dict.fromkeys(("bookmark_message", "hide_message", "mute_chat", "unmute_chat", "unlike_message", "hide_chat",
                     "unhide_chat"), _CHAT),
    **dict.fromkeys(("post_message", "prepare_message", "schedule_message"), _OF_SEND),
    **dict.fromkeys(("clear_list", "get_list", "list_posts_in", "set_list_pinned_to_chat"), _LISTS),
    **dict.fromkeys(("highlight", "my_stories_archive", "stories_feed", "user_highlights", "user_stories",
                     "settings_story", "patch_story_settings"), _STORIES),
    **dict.fromkeys(("block_stream_viewer", "reset_stream_key", "schedule_stream", "streams_feed",
                     "unblock_stream_viewer", "user_streams"), _STREAMS),
    **dict.fromkeys(("create_bundle", "delete_bundle", "edit_bundle", "subscription_bundles", "update_subscription"), _SUBS),
    **dict.fromkeys(("earning_stats", "payout_check_receive", "request_payout", "update_withdrawal_period"), _PAYOUTS),
    **dict.fromkeys(("edit_queued_message", "queued_message", "scheduled_messages"), _QUEUE),
    **dict.fromkeys(("performers_search", "user_photos", "user_videos", "following"), _FANS),
    **dict.fromkeys(("unpin_all_messages",), _NO_PIN),
    **dict.fromkeys(("create_story", "post_story"), _NO_STORY_WRITE),
    **dict.fromkeys(("upload_claim", "materialize_via_message", "materialize_to_vault"), _OF_UPLOAD),
}


def _marked(name: str, verdict: str, reason: str):
    def stub(self, *_a: Any, **_k: Any) -> Any: ...
    stub.__name__ = stub.__qualname__ = name
    return (fansly_blocked if verdict == _BLOCKED else fansly_unsupported)(reason)(stub)


for _name, (_verdict, _reason) in UNBUILT.items():
    if hasattr(FanslyShimClient, _name):
        raise RuntimeError(f"UNBUILT marks {_name}, which FanslyShimClient defines")
    setattr(FanslyShimClient, _name, _marked(_name, _verdict, _reason))
