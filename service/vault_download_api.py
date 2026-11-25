from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

import admission
import automation_executor as ax
import cdn_resign
import of_pacing
import proxies as proxy_registry
import vault_stills
from auth import assert_account_owned
from chatters import allowed_folder_ids_for_chatter
from db.engine import get_session
from db.models import VaultItem
from jsonsafe import load_json
from of_client import OF_CDN_SUFFIXES
from vault_ai_api import assert_media_visible

log = logging.getLogger("of-relay.vault_download")

router = APIRouter()

CHUNK = 256 * 1024
CUT_SHORT: ContextVar[dict | None] = ContextVar("vault_download_cut_short", default=None)
# Under the 60 s proxy_read_timeout common in front of the app, so the browser gets our clean 503, never the proxy's 504.
SLOT_WAIT_S = 45.0
SEND_IDLE_S = 120.0
# Longest one file may stream (4 GB source video at ~5 Mbit/s).
MAX_STREAM_S = 2 * 3600.0
_EXT = re.compile(r"\.([A-Za-z0-9]{2,5})$")
_KIND_EXT = {"photo": "jpg", "video": "mp4", "gif": "mp4", "audio": "mp3"}


def full_url(media: dict | None) -> str | None:
    files = (media or {}).get("files")
    full = files.get("full") if isinstance(files, dict) else None
    url = full.get("url") if isinstance(full, dict) else None
    return url if isinstance(url, str) and url.startswith(("https://", "http://")) else None


def file_name(media_id: int, url: str, kind: str | None) -> str:
    m = _EXT.search(urlsplit(url).path)
    return f"{media_id}.{(m.group(1).lower() if m else _KIND_EXT.get(kind or '', 'bin'))}"


def _cdn_host(u: str) -> bool:
    p = urlsplit(u)
    return p.scheme in ("http", "https") and any((p.hostname or "").lower().endswith(s) for s in OF_CDN_SUFFIXES)


async def _row_media(account_id: str, media_id: int) -> dict | None:
    async with get_session() as s:
        item = await s.get(VaultItem, (account_id, media_id))
    if item is None:
        return None
    return load_json(item.raw_json, None) or {"id": media_id, "type": item.kind, "files": {"full": {"url": item.full_url}}}


async def _gate(account_id: str, media_id: int) -> bool:
    assert_account_owned(account_id)
    await assert_media_visible(account_id, media_id)
    return await allowed_folder_ids_for_chatter(account_id) is None


def _u_ok(u: str, row: dict | None, unrestricted: bool) -> bool:
    return cdn_resign.same_file(u, row) or (unrestricted and row is None and _cdn_host(u))


@router.get("/admin/vault-ai/download/info")
async def download_info(account_id: str = Query(..., min_length=1)) -> dict[str, Any]:
    """Whether the browser may fetch this account's CDN urls itself: only when the account has no proxy."""
    assert_account_owned(account_id)
    eg = proxy_registry.egress(proxy_registry.registry(), account_id)
    return {"direct": isinstance(eg, proxy_registry.Direct)}


@router.get("/admin/vault-ai/download/resign")
async def download_resign(
    account_id: str = Query(..., min_length=1), media_id: int = Query(...),
    u: str | None = Query(None, description="The url that failed; the fresh one is for the same host+path"),
) -> dict[str, Any]:
    """A fresh signature for the same file (`cdn_resign`: its listing window, else by id). 404 when OF has no such
    media / file. No `u` (or one that may not stand in, `_u_ok`): the mirror row's own url is the failed one, so it
    goes through the same window / fail cache; a by-id read only without a row url."""
    unrestricted = await _gate(account_id, media_id)
    client = await asyncio.to_thread(ax._make_client, account_id)
    row = await _row_media(account_id, media_id)
    failed_u = u if u and _cdn_host(u) and _u_ok(u, row, unrestricted) else full_url(row)
    if failed_u:
        fresh = await cdn_resign.resign(account_id, media_id, failed_u, client, PACE_KIND)
    else:
        got = await _paced(account_id, lambda: vault_stills.resolve_fresh(account_id, media_id, client))
        fresh = full_url(got.media)
    if not fresh:
        raise HTTPException(status_code=404, detail="no_fresh_url")
    return {"url": fresh}


# Unpaced re-signs got OF 429 for the whole account (118-file download), failing the Creator's chat scrape too.
PACE_KIND = "vault_download"


def _paced(account_id: str, run):
    return of_pacing.walk(account_id, PACE_KIND, run)


def _close(r: Any) -> None:
    try:
        if r is not None:
            r.close()
    except Exception:  # noqa: BLE001
        pass


@router.get("/admin/vault-ai/download")
async def download(
    account_id: str = Query(..., min_length=1), media_id: int = Query(...),
    u: str | None = Query(None, description="The full url the browser holds (live listing); else the mirror's"),
):
    """The media's full-quality file through the account's client, streamed, as an attachment."""
    unrestricted = await _gate(account_id, media_id)
    row = await _row_media(account_id, media_id)
    client = await asyncio.to_thread(ax._make_client, account_id)
    url = full_url(row)
    if u and _u_ok(u, row, unrestricted):
        url = u
    if url is None:
        got = await _paced(account_id, lambda: vault_stills.resolve_fresh(account_id, media_id, client))
        url = full_url(got.media)
        kind = (got.media or {}).get("type")
        if url is None:
            raise HTTPException(status_code=404 if got.media is None else 422,
                                detail=got.reason if got.media is None else "no_full_file")
    else:
        kind = (row or {}).get("type")
    fetch_u = cdn_resign.current(account_id, url)

    lane = admission.VAULT_DOWNLOAD
    if not await lane.enter_within(SLOT_WAIT_S):
        log.info("vault_download account=%s media=%s status=busy bytes=0 resigned=False", account_id, media_id)
        raise HTTPException(status_code=503, detail="download_busy", headers={"Retry-After": "30"})
    r = None
    resigned = False
    out = {"sent": 0, "status": "aborted"}
    released = False

    def free(_done: Any = None) -> None:
        lane.leave()
        log.info("vault_download account=%s media=%s status=%s bytes=%s resigned=%s",
                 account_id, media_id, out["status"], out["sent"], resigned)

    async def release() -> None:
        nonlocal released
        if released:
            return
        released = True
        try:
            closing = asyncio.get_running_loop().run_in_executor(None, _close, r)
        except RuntimeError:
            _close(r)
            free()
            return
        closing.add_done_callback(free)

    try:
        try:
            async def get(x: str):
                return await run_in_threadpool(client.http.get, x, timeout=client.timeout_s, stream=True)

            r, fetched_url = await cdn_resign.fetch(account_id, media_id, url, client, get, PACE_KIND)
            resigned = fetched_url != fetch_u
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"upstream fetch failed: {e}") from e
        if r.status_code != 200:
            code = r.status_code
            raise HTTPException(status_code=code if code in (403, 404) else 502, detail=f"upstream {code}")
    except BaseException:
        out["status"] = "failed"
        await release()
        raise

    headers = {
        "Content-Disposition": f'attachment; filename="{file_name(media_id, url, kind)}"',
        "Cache-Control": "private, no-store",
    }
    if r.headers.get("Content-Length"):
        headers["Content-Length"] = r.headers["Content-Length"]
    resp_ct = r.headers.get("Content-Type", "application/octet-stream")
    deadline = time.monotonic() + MAX_STREAM_S

    async def body():
        try:
            async for chunk in iterate_in_threadpool(r.iter_content(chunk_size=CHUNK)):
                if time.monotonic() > deadline:
                    out["status"] = "too_long"
                    raise TimeoutError(f"vault download over {MAX_STREAM_S:.0f}s")
                if chunk:
                    out["sent"] += len(chunk)
                    yield chunk
            out["status"] = "ok"
        except Exception as e:  # noqa: BLE001 — the upstream died mid-body (curl 28 too slow, 18 cut short, a reset)
            if out["status"] != "too_long":
                out["status"] = "upstream_cut"
            log.warning("vault_download upstream cut account=%s media=%s after=%s: %s",
                        account_id, media_id, out["sent"], str(e)[:160])
            if "Content-Length" not in headers:
                mark = CUT_SHORT.get()
                if mark is not None:
                    mark["cut"] = True
        finally:
            await release()

    return _SlotStream(body(), release, media_type=resp_ct, headers=headers)


class _SlotStream(StreamingResponse):

    def __init__(self, content: Any, release: Callable[[], Awaitable[None]], **kw: Any) -> None:
        super().__init__(content, **kw)
        self._release = release

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        async def bounded_send(message: Any) -> None:
            async with asyncio.timeout(SEND_IDLE_S):
                await send(message)
        try:
            await super().__call__(scope, receive, bounded_send)
        finally:
            await self._release()
            await self.body_iterator.aclose()
