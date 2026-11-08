"""vault_download_api.py — Vault Pro's download (selection, a folder, the whole vault) on the relay side.

The browser saves each file itself (File System Access API, `app/components/vault/vaultDownload.ts`). It fetches
the signed CDN url DIRECT when the account has no proxy: OF signs every url for the egress that listed it
(`AWS:SourceIp`), and an unproxied account's egress is this machine's IP, the browser's too. With a proxy, a direct
fetch would 403 and show OF the operator's IP for a proxied Creator, so the browser never tries; it streams
through `GET /admin/vault-ai/download` instead.

  GET /admin/vault-ai/download/info?account_id=           {direct}: may the browser fetch this account's urls
                                                          itself (the account's egress is Direct, not a proxy).
  GET /admin/vault-ai/download/resign?account_id=&media_id=&u=
                                                          {url}: a freshly signed url for the same file as `u`
                                                          (one by-id OF read, `cdn_resign`), no bytes. The direct
                                                          path's retry after a 403 / expired url.
  GET /admin/vault-ai/download?account_id=&media_id=[&u=] the full-quality file through the account's client (its
                                                          proxy), streamed (never read whole), Content-Disposition
                                                          attachment; a 403 re-signs by media id once.

Every route: the account is the caller's (`assert_account_owned`), and a folder-restricted chatter gets 404 for a
media outside its folders or one the mirror has no row for (`vault_ai_api.assert_media_visible`, the stills'
rule). The url streamed is the mirror row's when the row has one for the same file; `u` is used only when it names
a file of that media (the row's payload) or, for an unrestricted caller, an OF CDN host (what `/img` already
accepts). Downloads hold a `VAULT_DOWNLOAD` slot each for the whole stream (queued, never rejected).

Logs `vault_download account=… media=… status=… bytes=… resigned=…` once per stream: the live script
(`scripts/vault-download-live.py`) counts these to tell direct items (none) from relayed ones.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

import admission
import automation_executor as ax  # _make_client seam (tests inject a fake client here)
import cdn_resign
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
_EXT = re.compile(r"\.([A-Za-z0-9]{2,5})$")
_KIND_EXT = {"photo": "jpg", "video": "mp4", "gif": "mp4", "audio": "mp3"}


def full_url(media: dict | None) -> str | None:
    """The full-quality file of an OF media dict: `files.full.url` (photo jpg, video / gif source mp4, audio mp3).
    None for a DRM-only video (OF ships `full` with no url, only license-gated manifests)."""
    files = (media or {}).get("files")
    full = files.get("full") if isinstance(files, dict) else None
    url = full.get("url") if isinstance(full, dict) else None
    return url if isinstance(url, str) and url.startswith(("https://", "http://")) else None


def file_name(media_id: int, url: str, kind: str | None) -> str:
    """`<mediaId>.<ext>`, the extension off the url's path (else by kind). Same rule as the app's `fileName`."""
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
    """Owner / unrestricted chatter: True. Restricted chatter: 404 unless the media is in its folders."""
    assert_account_owned(account_id)
    await assert_media_visible(account_id, media_id)
    return await allowed_folder_ids_for_chatter(account_id) is None


@router.get("/admin/vault-ai/download/info")
async def download_info(account_id: str = Query(...)) -> dict[str, Any]:
    """Whether the browser may fetch this account's CDN urls itself: only when the account has no proxy."""
    assert_account_owned(account_id)
    eg = proxy_registry.egress(proxy_registry.registry(), account_id)
    return {"direct": isinstance(eg, proxy_registry.Direct)}


@router.get("/admin/vault-ai/download/resign")
async def download_resign(
    account_id: str = Query(...), media_id: int = Query(...),
    u: str | None = Query(None, description="The url that failed; the fresh one is for the same host+path"),
) -> dict[str, Any]:
    """A fresh signature for the same file, by one by-id OF read. 404 when OF has no such media / file."""
    await _gate(account_id, media_id)
    client = await asyncio.to_thread(ax._make_client, account_id)
    if u and _cdn_host(u):
        fresh = await cdn_resign.resign(account_id, media_id, u, client)
    else:
        got = await vault_stills.resolve_fresh(account_id, media_id, client)
        fresh = full_url(got.media)
    if not fresh:
        raise HTTPException(status_code=404, detail="no_fresh_url")
    return {"url": fresh}


def _same_file(u: str, media: dict | None) -> bool:
    base = cdn_resign._base(u)
    return any(cdn_resign._base(x) == base for x in cdn_resign._urls(media or {}))


def _close(r: Any) -> None:
    try:
        if r is not None:
            r.close()
    except Exception:  # noqa: BLE001
        pass


@router.get("/admin/vault-ai/download")
async def download(
    account_id: str = Query(...), media_id: int = Query(...),
    u: str | None = Query(None, description="The full url the browser holds (live listing); else the mirror's"),
):
    """The media's full-quality file through the account's client, streamed, as an attachment."""
    unrestricted = await _gate(account_id, media_id)
    row = await _row_media(account_id, media_id)
    client = await asyncio.to_thread(ax._make_client, account_id)
    url = full_url(row)
    if u and (_same_file(u, row) or (unrestricted and row is None and _cdn_host(u))):
        url = u
    if url is None:
        got = await vault_stills.resolve_fresh(account_id, media_id, client)
        url = full_url(got.media)
        kind = (got.media or {}).get("type")
        if url is None:
            raise HTTPException(status_code=404 if got.media is None else 422,
                                detail=got.reason if got.media is None else "no_full_file")
    else:
        kind = (row or {}).get("type")
    fetch_u = cdn_resign.current(account_id, url)

    lane = admission.VAULT_DOWNLOAD
    await lane.__aenter__()
    r = None
    resigned = False
    try:
        try:
            r = await run_in_threadpool(client.http.get, fetch_u, timeout=client.timeout_s, stream=True)
            if r.status_code == 403:
                stale, r = r, None
                await run_in_threadpool(_close, stale)
                fetch_u = await cdn_resign.resign(account_id, media_id, fetch_u, client)
                if fetch_u is None:
                    raise HTTPException(status_code=403, detail="upstream_denied")
                resigned = True
                r = await run_in_threadpool(client.http.get, fetch_u, timeout=client.timeout_s, stream=True)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"upstream fetch failed: {e}") from e
        if r.status_code != 200:
            code = r.status_code
            raise HTTPException(status_code=code if code in (403, 404) else 502, detail=f"upstream {code}")
    except BaseException:
        asyncio.get_running_loop().run_in_executor(None, _close, r)
        await lane.__aexit__()
        log.info("vault_download account=%s media=%s status=failed bytes=0 resigned=%s",
                 account_id, media_id, resigned)
        raise

    headers = {
        "Content-Disposition": f'attachment; filename="{file_name(media_id, url, kind)}"',
        "Cache-Control": "private, no-store",
    }
    if r.headers.get("Content-Length"):
        headers["Content-Length"] = r.headers["Content-Length"]
    resp_ct = r.headers.get("Content-Type", "application/octet-stream")

    async def body():
        sent, status = 0, "aborted"
        try:
            async for chunk in iterate_in_threadpool(r.iter_content(chunk_size=CHUNK)):
                if chunk:
                    sent += len(chunk)
                    yield chunk
            status = "ok"
        finally:
            # Off the loop: closing a streamed curl response joins its transfer thread (img_api's note).
            asyncio.get_running_loop().run_in_executor(None, _close, r)
            await lane.__aexit__()
            log.info("vault_download account=%s media=%s status=%s bytes=%s resigned=%s",
                     account_id, media_id, status, sent, resigned)

    return StreamingResponse(body(), media_type=resp_ct, headers=headers)
