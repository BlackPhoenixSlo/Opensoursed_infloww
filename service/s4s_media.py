"""service/s4s_media.py — S4S media: up to 5 vault items per S4S post, kept as
references to the Creator's own vault, never as files (ADR-0015).

  PUT /admin/s4s/profiles/{account_id}/posts/{post_id}/media
      {vault_media_ids: [<= 5 ids]} → the post's media, in this order.
      Owner-only, the Creator's own Agency. Each newly named id is read with
      the Creator's own OnlyFans session (`vault_media_by_id`, which proves it
      is this Creator's vault item and one we can share); only its id and kind
      are stored. An id no longer named is detached.
  GET /admin/s4s/media/{media_id}
      → a still of the item, read live from the Creator's vault with the
      Creator's own session. For the Creator's own Agency; for any Agency the
      Creator is listed to in Discovery while the item is on its Primary post
      (`listed_to`), so a partner sees the post before it sends a request;
      and for an Agency whose Creator is a party to a live request (pending,
      or accepted) that snapshotted it, so each side sees what will be posted
      before Accept. 404 to everyone else, a declined or expired request
      included, and once the item has left the vault.

At send, a request snapshots the media ids on each Primary post
(`snapshot`). At slot time `s4s_post` reads each of the partner's snapshot
items from the partner's vault with the partner's session (`fetch_to`, into
a temporary directory removed after the post) and uploads it to the poster's
own account. An item gone from the vault ends the slot `media_missing`.
`prune` deletes a row once it is detached and no live request or slot names it.

Limits: 5 per post (Infloww @13802032). Photos, GIFs and non-DRM videos only.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import delete, or_, select, update

from agency_scope import agency_account_ids
import automation_executor as ax
from db.engine import get_session
from db.models import S4SMedia, S4SPost, S4SProfile, S4SRequest, S4SSlot
from s4s_common import _json_object, _owner_context, listed_to

log = logging.getLogger("of-relay.s4s_media")

router = APIRouter(prefix="/admin/s4s", tags=["s4s"])

MAX_MEDIA = 5
# Request statuses whose snapshot a party may still preview ("skipped" is
# the sender's pending). Declined, cancelled and expired grant nothing.
LIVE = ("pending", "skipped", "accepted")
# The file keeps its URL's extension when it is one of these (upload_media
# names the upload after the file), else the kind's default.
_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov"}
_DEFAULT_EXT = {"photo": ".jpg", "gif": ".mp4", "video": ".mp4"}

_save_locks: dict[str, asyncio.Lock] = {}


class MediaMissing(Exception):
    """A slot's snapshot names an item that is gone (its row, or the vault item itself)."""


def _ids(raw: str | None) -> list[int]:
    """The media ids of a request's stored snapshot."""
    return [int(m["id"]) for m in json.loads(raw)] if raw else []


def slot_media_ids(r: S4SRequest, slot: S4SSlot) -> list[int]:
    """The snapshot ids this slot's poster posts: the partner's side of the request."""
    return _ids(r.from_media_json if slot.poster_account_id == r.to_account_id else r.to_media_json)


def _out(row: S4SMedia) -> dict[str, Any]:
    return {"id": row.id, "vault_media_id": row.vault_media_id, "media_type": row.media_type}


async def post_media(s, post_ids) -> dict[int, list[dict[str, Any]]]:
    """Each post's attached media, oldest first (the order they were added)."""
    rows = (await s.execute(
        select(S4SMedia).where(S4SMedia.post_id.in_(list(post_ids))).order_by(S4SMedia.id)
    )).scalars().all()
    out: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(r.post_id, []).append(_out(r))
    return out


async def snapshot(s, account_id: str) -> list[dict[str, Any]]:
    """`{id, media_type}` of each media on the Creator's Primary post now:
    what a request stores at send."""
    return [{"id": i, "media_type": t} for i, t in (await s.execute(
        select(S4SMedia.id, S4SMedia.media_type)
        .join(S4SPost, S4SPost.id == S4SMedia.post_id)
        .where(S4SPost.account_id == account_id, S4SPost.is_primary.is_(True))
        .order_by(S4SMedia.id)
    )).all()]


async def slot_vault_ids(s, slot: S4SSlot) -> list[int]:
    """The partner's vault media ids for this slot, in snapshot order. Every
    row must be the slot's partner's own; a missing row raises MediaMissing."""
    ids = slot_media_ids(await s.get(S4SRequest, slot.request_id), slot)
    if not ids:
        return []
    rows = {m.id: m for m in (await s.execute(select(S4SMedia).where(S4SMedia.id.in_(ids)))).scalars().all()}
    out = []
    for i in ids:
        m = rows.get(i)
        if m is None or m.account_id != slot.partner_account_id:
            raise MediaMissing(i)
        out.append(m.vault_media_id)
    return out


# ── Cleanup ──────────────────────────────────────────────────────────


async def _pinned(s, now: datetime) -> set[int]:
    """Media ids a live request or slot still needs: an open request whose
    time is ahead (lazy expiry may not have written it yet), or an accepted
    one whose slots are not all done."""
    live_slots = select(S4SSlot.request_id).where(S4SSlot.status.in_(("scheduled", "posting")))
    rows = (await s.execute(
        select(S4SRequest.from_media_json, S4SRequest.to_media_json).where(
            or_(S4SRequest.from_media_json.is_not(None), S4SRequest.to_media_json.is_not(None)),
            or_((S4SRequest.status.in_(("pending", "skipped"))) & (S4SRequest.slot_at > now),
                S4SRequest.id.in_(live_slots)),
        )
    )).all()
    return {i for a, b in rows for i in _ids(a) + _ids(b)}


async def prune() -> int:
    """Delete detached rows no live request or slot names. Returns rows deleted.

    ASSUMPTION: prune runs after every media save, S4S post delete and
    `s4s_post` end, not on a timer. Rung 4 (each of those is when a row can
    stop being needed). Overturned by a Deployment that wants detached rows
    gone without S4S activity.
    """
    async with get_session() as s:
        pinned = await _pinned(s, datetime.utcnow())
        gone = [i for i in (await s.execute(select(S4SMedia.id).where(S4SMedia.post_id.is_(None)))).scalars().all()
                if i not in pinned]
        if gone:
            await s.execute(delete(S4SMedia).where(S4SMedia.id.in_(gone), S4SMedia.post_id.is_(None)))
    return len(gone)


# ── Vault reads ──────────────────────────────────────────────────────


def _of_url(url: str | None) -> str | None:
    """`url` when it is an https URL on OF's own media hosts, else None.
    No userinfo, port or backslash: urllib and libcurl must read the same host."""
    from of_client import OF_CDN_SUFFIXES

    if not url:
        return None
    u = urlparse(url)
    host = u.hostname or ""
    if (u.scheme != "https" or "\\" in url or u.netloc.lower() != host
            or not host.endswith(OF_CDN_SUFFIXES)):
        return None
    return url


def _source(item: dict) -> tuple[str, str]:
    """(url, media_type) of a vault item we can share, or a 400 why not."""
    kind = item.get("type")
    files = item.get("files") or {}
    full = files.get("full") or {}
    if kind in ("photo", "gif"):
        url = full.get("url") if not full.get("drm") else None
    elif kind == "video":
        drm = ((files.get("drm") or {}).get("manifest") or {})
        progressive = (item.get("videoSources") or {}).get("720") or full.get("url")
        url = None if (drm.get("hls") or drm.get("dash")) and not progressive else progressive
    else:
        raise HTTPException(status_code=400, detail=f"vault item {item.get('id')}: only photos and videos can be shared")
    if not url:
        raise HTTPException(status_code=400,
                            detail=f"vault item {item.get('id')} is DRM-protected and cannot be shared")
    if _of_url(url) is None:
        raise HTTPException(status_code=400, detail="vault media is not on an OnlyFans media host")
    return url, kind


def _vault_item(client, vid: int) -> dict:
    """The vault item, or MediaMissing once OF no longer has it."""
    from of_client import OFAPIError

    try:
        item = client.vault_media_by_id(vid)
    except OFAPIError as e:
        raise MediaMissing(vid) from e
    return item if isinstance(item, dict) else {}


def _check(account_id: str, vault_ids: list[int]) -> list[dict[str, Any]]:
    """Read each vault item with the Creator's own session: `{vault_media_id,
    media_type}` of each, or a 400 naming the first that cannot be shared."""
    client = ax._make_client(account_id)
    out = []
    for vid in vault_ids:
        try:
            item = _vault_item(client, vid)
        except MediaMissing:
            raise HTTPException(status_code=400, detail=f"vault item {vid} is not in this Creator's vault") from None
        out.append({"vault_media_id": vid, "media_type": _source(item)[1]})
    return out


def fetch_to(account_id: str, vault_id: int, folder: Path) -> Path:
    """Stream one of the Creator's vault items into `folder` with the
    Creator's own session, for an upload elsewhere. MediaMissing when the
    item is gone or can no longer be shared; any other failure raises."""
    client = ax._make_client(account_id)
    try:
        url, kind = _source(_vault_item(client, vault_id))
    except HTTPException as e:
        raise MediaMissing(vault_id) from e
    ext = Path(urlparse(url).path).suffix.lower()
    dest = folder / f"{vault_id}{ext if ext in _EXTS else _DEFAULT_EXT[kind]}"
    r = client.http.get(url, timeout=client.timeout_s, stream=True, allow_redirects=False)
    try:
        if r.status_code != 200:
            raise RuntimeError(f"OnlyFans media download answered {r.status_code}")
        with dest.open("wb") as f:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                f.write(chunk)
    finally:
        try:
            r.close()
        except Exception:  # noqa: BLE001 — closing a finished stream must not mask the result
            pass
    return dest


def _still(account_id: str, vault_id: int) -> tuple[bytes, str] | None:
    """(bytes, content type) of a still of the vault item, read now with the
    Creator's own session; None when the item or its still is gone."""
    client = ax._make_client(account_id)
    try:
        item = _vault_item(client, vault_id)
    except MediaMissing:
        return None
    files = item.get("files") or {}
    url = next((u for u in ((files.get(k) or {}).get("url") for k in ("thumb", "squarePreview", "preview"))
                if _of_url(u)), None)
    if url is None and item.get("type") == "photo":
        url = _of_url((files.get("full") or {}).get("url"))
    if url is None:
        return None
    r = client.http.get(url, timeout=client.timeout_s, allow_redirects=False)
    if r.status_code != 200:
        return None
    return r.content, (r.headers.get("content-type") or "image/jpeg")


# ── Save ─────────────────────────────────────────────────────────────


def _parse(body: dict[str, Any]) -> list[int]:
    ids = body.get("vault_media_ids")
    if (set(body) - {"vault_media_ids"} or not isinstance(ids, list)
            or not all(isinstance(i, int) and not isinstance(i, bool) and i > 0 for i in ids)):
        raise HTTPException(status_code=400, detail="vault_media_ids: a list of vault media ids is required")
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=400, detail="vault_media_ids: an id is listed twice")
    if len(ids) > MAX_MEDIA:
        raise HTTPException(status_code=400, detail=f"an S4S post carries at most {MAX_MEDIA} media")
    return ids


async def _own_post(s, account_id: str, raw_id: str) -> S4SPost:
    try:
        post = await s.get(S4SPost, int(raw_id))
    except ValueError:
        post = None
    if post is None or post.account_id != account_id:
        raise HTTPException(status_code=404, detail="post not found")
    return post


# The ids are strings parsed in the handler: a typed path parameter would let
# FastAPI answer 422 before the 401/403 session checks run.
@router.put("/profiles/{account_id}/posts/{post_id}/media")
async def put_post_media(account_id: str, post_id: str, request: Request) -> list[dict[str, Any]]:
    """Set the post's media to these vault items, in this order.

    ASSUMPTION: a re-save keeps an already attached vault item's row and
    order position, reading only new ids, so re-ordering is remove and
    re-add. Rung 4 (no second vault read). Overturned by an owner wanting
    drag-to-reorder.
    """
    await _owner_context(account_id)
    ids = _parse(await _json_object(request))
    async with _save_locks.setdefault(account_id, asyncio.Lock()):
        async with get_session() as s:
            post = await _own_post(s, account_id, post_id)
            have = {m.vault_media_id for m in (await s.execute(
                select(S4SMedia).where(S4SMedia.post_id == post.id))).scalars().all()}
        new = await asyncio.to_thread(_check, account_id, [i for i in ids if i not in have])
        async with get_session() as s:
            post = await _own_post(s, account_id, post_id)  # deleted meanwhile → 404
            await s.execute(update(S4SMedia).where(S4SMedia.post_id == post.id,
                                                   S4SMedia.vault_media_id.not_in(ids)).values(post_id=None))
            s.add_all(S4SMedia(account_id=account_id, post_id=post.id, created_at=datetime.utcnow(), **n)
                      for n in new)
            await s.flush()
            media = (await post_media(s, [post.id])).get(post.id, [])
        await prune()
    return media


# ── Read ─────────────────────────────────────────────────────────────


@router.get("/media/{media_id}")
async def get_media(media_id: str) -> Response:
    """A still of the item, for its own Agency, an Agency its Creator is
    listed to while it is on the Primary post, or a party to a request that
    snapshotted it.

    ASSUMPTION: both parties of a request may see both snapshots, as both
    see both captions on the request. Rung 3 (`s4s_requests_api._out`
    returns `from` and `to` to either party). Overturned with that rule.
    ASSUMPTION: every kind previews as a still (OF's thumb), read on each
    request with no cache. Rung 4 (a 40 px tile needs no video; nothing kept
    on our disk). Overturned by an owner wanting to play a video before Accept.
    """
    ctx = await _owner_context()
    try:
        mid = int(media_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="media not found") from None
    async with get_session() as s:
        row = await s.get(S4SMedia, mid)
        own = await agency_account_ids(s, ctx.agency_user_id)
        allowed = row is not None and row.account_id in own
        if row is not None and not allowed and row.post_id is not None:
            allowed = (await s.execute(
                select(S4SPost.id).join(S4SProfile, S4SProfile.account_id == S4SPost.account_id)
                .where(S4SPost.id == row.post_id, S4SPost.account_id == row.account_id,
                       S4SPost.is_primary.is_(True), *listed_to(ctx.agency_user_id))
            )).first() is not None
        if row is not None and not allowed:
            for a, b in (await s.execute(
                select(S4SRequest.from_media_json, S4SRequest.to_media_json).where(
                    S4SRequest.status.in_(LIVE),
                    or_(S4SRequest.from_account_id.in_(own), S4SRequest.to_account_id.in_(own)))
            )).all():
                if mid in _ids(a) + _ids(b):
                    allowed = True
                    break
    if not allowed:
        raise HTTPException(status_code=404, detail="media not found")
    try:
        still = await asyncio.to_thread(_still, row.account_id, row.vault_media_id)
    except Exception:  # noqa: BLE001 — a preview that cannot be read is absent, not an error page
        log.warning("s4s_media: still of media %s could not be read", mid, exc_info=True)
        still = None
    if still is None:
        raise HTTPException(status_code=404, detail="media not found")
    return Response(content=still[0], media_type=still[1])
