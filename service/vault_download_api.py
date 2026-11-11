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
                                                          (`cdn_resign`: its listing window, else by id), no bytes. The direct
                                                          path's retry after a 403 / expired url.
  GET /admin/vault-ai/download?account_id=&media_id=[&u=] the full-quality file through the account's client (its
                                                          proxy), streamed (never read whole), Content-Disposition
                                                          attachment; a 403 re-signs by media id once.

Every route: the account is the caller's (`assert_account_owned`), and a folder-restricted chatter gets 404 for a
media outside its folders or one the mirror has no row for (`vault_ai_api.assert_media_visible`, the stills'
rule). The url streamed is the mirror row's when the row has one for the same file; `u` is used only when it names
a file of that media (the row's payload) or, for an unrestricted caller, an OF CDN host (what `/img` already
accepts); `/download/resign` follows the same rule (a foreign `u` would hand a restricted chatter a fresh url of
a hidden media). Downloads hold a `VAULT_DOWNLOAD` slot each for the whole stream: queued at most SLOT_WAIT_S, then
503 (the browser lists the item failed, Retry failed). However the response ends (`_SlotStream`), including a client
gone before the body ever started, the upstream response is closed and only then the slot freed; a consumer that
takes no chunk for SEND_IDLE_S, or a stream past MAX_STREAM_S, is cut (the browser's Content-Length check fails the
item).

Every OF read these routes make (the re-sign of a stale / expired url: one listing read per 100-item window, `cdn_resign`,
else one by-id read per file) runs as a paced background
walk on the Creator (`of_pacing.walk`, kind `vault_download`): >= PAGE_GAP_S apart, shared with the Creator's other
walks, OF's 429 waited out and retried once. Measured on AE 2026-11-10: a 118-file download whose urls had expired 3
days earlier re-signed 76 files in 19 s unpaced, OF answered 429 for the account, the last 26 files failed (`relay
403`) and the Creator's chat scrape and vault collect failed with them.

Logs `vault_download account=… media=… status=… bytes=… resigned=…` once per stream: the live script
(`scripts/vault-download-live.py`) counts these to tell direct items (none) from relayed ones.
"""
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
import automation_executor as ax  # _make_client seam (tests inject a fake client here)
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
# server._CutShortStreams puts a fresh dict here per request (inherited by the handler's and the body's tasks: the
# same dict); a chunked body cut mid-file sets "cut", so its final message is dropped too (no terminating chunk).
CUT_SHORT: ContextVar[dict | None] = ContextVar("vault_download_cut_short", default=None)
# A queued download waits this long for a slot, then 503 (retryable: the browser lists it failed). A slot is a whole
# file's stream, so this is "another tab's file finished", not a fixed latency. Under the 60 s read timeout common
# in front of the app (nginx's default proxy_read_timeout): the browser gets our clean 503, never the proxy's 504.
SLOT_WAIT_S = 45.0
# A browser that takes no chunk for this long (a stalled tab, a dead socket the OS has not noticed) gives its slot
# back. Upstream stalls are curl's: a streamed GET with a float timeout aborts below 1 B/s for `timeout_s`.
SEND_IDLE_S = 120.0
# The longest one file may stream (a 4 GB source video at ~5 Mbit/s); past it the stream is cut.
MAX_STREAM_S = 2 * 3600.0
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


def _u_ok(u: str, row: dict | None, unrestricted: bool) -> bool:
    """May `u` stand in for the media's own url? Only when it names a file of that media (the mirror row), or, for an
    unrestricted caller with no row, any OF CDN url (what `/img` accepts). Else a restricted chatter could pass a
    hidden media's url with a visible media's id."""
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
    media / file."""
    unrestricted = await _gate(account_id, media_id)
    client = await asyncio.to_thread(ax._make_client, account_id)
    if u and _cdn_host(u) and _u_ok(u, await _row_media(account_id, media_id), unrestricted):
        fresh = await _paced(account_id, lambda: cdn_resign.resign(account_id, media_id, u, client))
    else:
        got = await _paced(account_id, lambda: vault_stills.resolve_fresh(account_id, media_id, client))
        fresh = full_url(got.media)
    if not fresh:
        raise HTTPException(status_code=404, detail="no_fresh_url")
    return {"url": fresh}


def _paced(account_id: str, run):
    """`run()` with its OF reads paced on the Creator (module doc)."""
    return of_pacing.walk(account_id, "vault_download", run)


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
        """Upstream closed, then the slot back and one log line: once, from whichever end comes first (the handler's
        error path, the body's `finally`, `_SlotStream.__call__`'s `finally`). The close runs off the loop (closing a
        streamed curl response joins its transfer thread, img_api's note) and the slot is freed only when it has
        finished (the executor future's done callback, run on the loop), so a burst of disconnects never admits new
        streams while the old transfers are still open. No await, so it completes under cancellation too."""
        nonlocal released
        if released:
            return
        released = True
        try:
            closing = asyncio.get_running_loop().run_in_executor(None, _close, r)
        except RuntimeError:   # the executor is shut down (process exit): nothing to wait on
            _close(r)
            free()
            return
        closing.add_done_callback(free)

    try:
        try:
            async def get(x: str):
                return await run_in_threadpool(client.http.get, x, timeout=client.timeout_s, stream=True)

            r, fetched_url = await _paced(account_id, lambda: cdn_resign.fetch(account_id, media_id, url, client, get))
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
            # Stop short: server._CutShortStreams drops the final message, uvicorn closes the connection, the browser's
            # read fails the item (vaultDownload.ts `short body`). No Traceback. A known length does it by itself (sent
            # < Content-Length); chunked (no length) a clean end would read as the whole file, so the request is
            # marked in CUT_SHORT for the middleware (raising would not do: BaseHTTPMiddleware completes the body).
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
    """A StreamingResponse that gives the download's slot back however it ends. The body's own `finally` is not
    enough: a client gone before Starlette starts the generator (the disconnect wins the race in its task group)
    leaves the generator never started, so its `finally` never runs and the slot and the curl response leak; four of
    those and every relay download queued forever. Each send waits at most SEND_IDLE_S for the browser."""

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
            await self.body_iterator.aclose()   # a generator paused at `yield` runs its `finally` now, not at GC
