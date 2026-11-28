from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import weakref
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, NamedTuple
from urllib.parse import parse_qs, urlsplit

from fastapi import HTTPException
from fastapi.responses import FileResponse, Response

import automation_executor as ax
import of_pacing
import vault_mirror
from db.engine import get_session
from db.models import VaultItem
from jsonsafe import load_json

log = logging.getLogger("of-relay.vault_stills")

THUMB_DIR = Path(os.environ.get("VAULT_THUMB_DIR", "/tmp/of-relay-vault-thumbs"))
POSTER_DIR = Path(os.environ.get("VAULT_POSTER_DIR", "/tmp/of-relay-vault-posters"))
IMAGE_DIR = Path(os.environ.get("VAULT_IMAGE_DIR", "/tmp/of-relay-vault-images"))

# `private`: stills routes are per-user gated, so a shared cache must not hand one user's tile to another.
_HEADERS = {"Cache-Control": "private, max-age=604800"}

Pick = Callable[[dict], "str | None"]


def thumb_path(account_id: str, media_id: int) -> Path:
    return THUMB_DIR / account_id / f"{media_id}.jpg"


def poster_path(account_id: str, media_id: int, idx: int) -> Path:
    return POSTER_DIR / account_id / f"{media_id}_{idx}.jpg"


def image_path(account_id: str, media_id: int) -> Path:
    return IMAGE_DIR / account_id / f"{media_id}.jpg"


# Well above the largest real still, well below a video: it only catches a mis-picked url.
_MAX_STILL_BYTES = 8 * 1024 * 1024

# A 200 isn't proof of a picture: a still is written as .jpg and served as image/jpeg.
_IMAGE_MAGIC = (
    b"\xff\xd8\xff",
    b"\x89PNG\r\n\x1a\n",
    b"GIF87a", b"GIF89a",
)


# Bounds OF-bound stills process-wide: a cold 500-tile pane unbounded exhausted fds (EMFILE), failing sqlite, session scandir and sends. Queueing is the point.
import lane_config as _lane_config
# A cold pane's tail queued >10 s at 6; 12 curl handles are nothing next to the fd limit.
_MAX_INFLIGHT_FETCHES = _lane_config.resolve("VAULT_STILL_CONCURRENCY", 12)

# Per-loop: a Semaphore that parked a waiter belongs to its loop (tests run each case in its own asyncio.run); weak keys.
_SLOTS: "weakref.WeakKeyDictionary[Any, asyncio.Semaphore]" = weakref.WeakKeyDictionary()


def _fetch_slot() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    sem = _SLOTS.get(loop)
    if sem is None:
        sem = _SLOTS[loop] = asyncio.Semaphore(_MAX_INFLIGHT_FETCHES)
    return sem


def signed_url_expired(url: str, now: float) -> bool:
    q = parse_qs(urlsplit(url).query)
    try:
        if "Expires" in q:
            return float(q["Expires"][0]) < now
        if "Policy" in q:
            raw = q["Policy"][0].replace("-", "+").replace("_", "=").replace("~", "/")
            pol = json.loads(base64.b64decode(raw + "=" * (-len(raw) % 4)))
            return float(pol["Statement"][0]["Condition"]["DateLessThan"]["AWS:EpochTime"]) < now
    except Exception:  # noqa: BLE001
        return False
    return False


def _looks_like_an_image(data: bytes) -> bool:
    if data.startswith(_IMAGE_MAGIC):
        return True
    # WEBP is RIFF....WEBP: the size field sits between the two markers.
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def fetch_bytes_sync(client: Any, url: str) -> bytes | None:
    try:
        r = client.http.get(url, timeout=client.timeout_s)
        if r.status_code != 200:
            return None
        declared = r.headers.get("Content-Length") if hasattr(r, "headers") else None
        if declared and declared.isdigit() and int(declared) > _MAX_STILL_BYTES:
            log.warning("still too large to cache url=%.80s bytes=%s", url, declared)
            return None
        data = r.content
        if not data or len(data) > _MAX_STILL_BYTES:
            return None
        if not _looks_like_an_image(data):
            log.warning("refusing to cache a non-image body url=%.80s head=%r",
                        url, data[:8])
            return None
        return data
    except Exception:  # noqa: BLE001
        # Logged, not swallowed: to the caller this is indistinguishable from "OF said 403".
        log.warning("still fetch raised url=%.80s", url, exc_info=True)
    return None


def write(p: Path, data: bytes) -> None:
    tmp = p.with_name(f".{p.name}.{os.getpid()}.part")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(data)
        os.replace(tmp, p)
    except Exception:  # noqa: BLE001
        try:
            tmp.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass


class _Resolved(NamedTuple):
    media: dict | None
    gone: bool


def _resolve_fresh_sync(client: Any, media_id: int) -> _Resolved:
    try:
        m = client.vault_media_by_id(media_id)
        return _Resolved(m if isinstance(m, dict) else None, False)
    except of_pacing.ReadPacingExpired:
        raise
    except Exception as e:  # noqa: BLE001
        resp = getattr(e, "response", None)
        return _Resolved(None, getattr(resp, "status_code", None) == 404)


async def _refresh_mirror(account_id: str, media_id: int, media: dict) -> None:
    async with get_session() as s:
        item = await s.get(VaultItem, (account_id, media_id))
        if item is None:
            return
        vals = vault_mirror.row_values(account_id, media)
        if vals is None:
            return
        for k in vault_mirror.MIRROR_REFRESH_FIELDS:
            setattr(item, k, vals[k])
        await s.commit()


async def _mark_gone(account_id: str, media_id: int) -> None:
    now = datetime.utcnow()
    async with get_session() as s:
        item = await s.get(VaultItem, (account_id, media_id))
        if item is not None and item.removed_at is None:
            item.removed_at = now
            item.updated_at = now
            await s.commit()


class Still(NamedTuple):

    data: bytes | None
    reason: str


class Fresh(NamedTuple):

    media: dict | None
    reason: str


async def resolve_fresh(account_id: str, media_id: int, client: Any,
                        *, mark_gone: bool = True) -> Fresh:
    fresh = await asyncio.to_thread(_resolve_fresh_sync, client, media_id)
    if fresh.gone:
        if mark_gone:
            await _mark_gone(account_id, media_id)
        return Fresh(None, "gone")
    if fresh.media is None:
        return Fresh(None, "fetch_failed")
    await _refresh_mirror(account_id, media_id, fresh.media)
    return Fresh(fresh.media, "ok")


async def bytes_for(account_id: str, media_id: int, path: Path, pick: Pick) -> Still:
    if path.is_file():
        return Still(path.read_bytes(), "ok")

    # Everything past here costs descriptors (DB connection, curl handle, thread), so it runs _MAX_INFLIGHT_FETCHES at a time.
    async with _fetch_slot():
        # Re-check under the slot: a re-render queues several requests for the SAME media and the first holder already wrote it.
        if path.is_file():
            return Still(path.read_bytes(), "ok")

        async with get_session() as s:
            item = await s.get(VaultItem, (account_id, media_id))
        # Negative cache: without it every render of a dead tile pays two OF calls.
        if item is not None and item.removed_at is not None:
            return Still(None, "gone")
        # no_variant must NOT soft-delete (unlike gone): a voice note is fine, just not a picture.
        if item is not None and not vault_mirror.has_still(item.kind):
            return Still(None, "no_variant")

        url: str | None = None
        if item is not None:
            url = pick(load_json(item.raw_json, {}) or {}) or item.thumb_url

        client = await asyncio.to_thread(ax._make_client, account_id)
        data = None
        if url:
            data = await asyncio.to_thread(fetch_bytes_sync, client, url)
        if data is None:
            fresh = await resolve_fresh(account_id, media_id, client)
            if fresh.media is None:
                return Still(None, fresh.reason)
            retry = pick(fresh.media)
            if not retry:
                return Still(None, "no_variant")
            if retry == url:
                return Still(None, "fetch_failed")
            data = await asyncio.to_thread(fetch_bytes_sync, client, retry)
            if data is None:
                return Still(None, "fetch_failed")

        write(path, data)
        return Still(data, "ok")


async def serve(account_id: str, media_id: int, path: Path, pick: Pick) -> Response:
    if path.is_file():
        return FileResponse(path, media_type="image/jpeg", headers=_HEADERS)
    still = await bytes_for(account_id, media_id, path, pick)
    if still.data is None:
        raise HTTPException(
            status_code=404,
            detail="media_gone" if still.reason == "gone" else still.reason)
    return Response(content=still.data, media_type="image/jpeg", headers=_HEADERS)
