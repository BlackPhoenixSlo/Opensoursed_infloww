"""The chat media flow's break-it-once faults (scenarios/2026-11-02-img-chat-media.py): lib/faults.py merges
`register(Fault)` into FAULTS. The check names live here and the scenario imports them, so a target can never name
a check that does not exist. Each patches a product module attribute inside the relay.
"""
from __future__ import annotations

import hashlib

BYTES = ("img: per phase /img fetches by asset == the opened chats' media (none dropped), every /img 200 body is "
         "the CDN's bytes (sha256 + length), every fresh asset answered 200, no unknown asset")
CDN_COLLAPSE = "img cold herd: per cacheable asset fake-CDN calls <= the img_fetch cap, img_cache_collapsed > 0"
COLD_HERD = ("img cache-miss herds (cold, stale): each missed the cache, no /img 5xx but the img_fetch lane's 503, "
             "/admin/streams answers within the scenario's budget through each")
WARM_HIT = ("img warm + rotated + probe reopen: every cacheable fetch X-Img-Cache HIT, no CDN call for one, "
            "/admin/img-cache/disk hits delta == those fetches")
MAX_INFLIGHT = "img: the fake CDN's peak in-flight (max over its calls) <= the img_fetch cap (/admin/streams)"
BIG = ("img >2 MiB: served whole, never cached (MISS every fetch, no > 2 MiB file in the armed cache dir), CDN "
       "calls == fetches, skipped_too_big delta == fetches, every phase")
DIRECT = ("img direct host: public.onlyfans.com fetches carry no Cookie, account UA or OF account headers; "
          "signed-host fetches carry all of their own Creator's")
EXPIRED = "img expired signature: every stale-chat fetch /img 403, one CDN call each (never cached)"
LANE_DRAINED = "img: img_fetch lane back to 0 busy after every phase (no leaked slot)"
REJECTED = "img: no /img rejected by the img_fetch lane (img_fetch_rejected delta == 0)"
BY_HASH = "img by-hash: /img miss with X-Account-Id answers X-Img-Hash, /img/by-hash/<h> 200 with the same bytes"
TILE_HASH = "img MediaTile shape (/img?u=&account_id=, no header): a miss answers X-Img-Hash (its by-hash pivot)"
NO_OFFHOST = "img: no off-host curl_cffi target (server-offhost.jsonl has no curl_cffi line)"


def _cache_never_hits() -> None:
    """The disk cache never answers: every lookup (first look and the in-slot re-read) misses."""
    import img_api

    img_api._img_cache_lookup = lambda u: None


def _key_keeps_signature() -> None:
    """The disk-cache key is the whole URL, query (Policy / Signature) included, not host + path: OF re-signing a
    URL busts its cached bytes (what `_img_cache_key`'s docstring guards against)."""
    import img_api

    img_api._img_cache_key = lambda u: hashlib.sha1(u.encode("utf-8")).hexdigest()


def _lane_unbounded() -> None:
    """IMG_FETCH admits every request at once (busy still counted): no ceiling on concurrent CDN fetches."""
    import admission

    lane = admission.IMG_FETCH

    def enter(label: str = "") -> bool:
        with lane._lock:
            lane.busy += 1
        return True

    async def enter_async(label: str = "") -> bool:
        return enter(label)

    def exit_() -> None:
        with lane._lock:
            lane.busy = max(0, lane.busy - 1)

    lane.enter, lane.enter_async, lane.exit = enter, enter_async, exit_


def _on_pool_tokens() -> None:
    """The #172 cycle back (see `admission.Lane.enter_async`), both halves on the anyio threadpool: IMG_FETCH's wait
    parks a pool thread (`enter_async` runs the blocking `enter` there), and the failed-fetch close that releases a
    slot (`img_api._close_then_exit`: every stale 403) needs a pool token while the slot is held (the executor thread
    hands it to the main loop's pool and waits, the hop of upload_faults._upload_on_loop). Slots, cap, wait_s and the
    503 are unchanged."""
    import asyncio

    import admission
    import img_api
    import server
    from starlette.concurrency import run_in_threadpool

    lane = admission.IMG_FETCH
    real_close = img_api._close_then_exit

    async def enter_async(label: str = "") -> bool:
        return await run_in_threadpool(lane.enter, label)

    def close_on_pool(r, held) -> None:
        asyncio.run_coroutine_threadsafe(run_in_threadpool(real_close, r, held), server._main_loop).result()

    lane.enter_async = enter_async
    img_api._close_then_exit = close_on_pool


def register(Fault) -> dict:
    return {
        # slop/run img-chat-media --break (the scenario's FAULT; --break runs small / 20 by default). Its probe-hit
        # p95 goes red too: noise (a p95 miss is not a catch).
        "img-cache-never-hits": Fault(_cache_never_hits, (WARM_HIT, CDN_COLLAPSE)),
        # slop/run img-chat-media --break --fault=img-cache-key-keeps-signature (any scale)
        # The rotated reopen misses and refetches (a cold herd's load, nothing more): only WARM_HIT.
        "img-cache-key-keeps-signature": Fault(_key_keeps_signature, (WARM_HIT,)),
        # slop/run img-chat-media --break --fault=img-fetch-lane-unbounded
        # Not CDN_COLLAPSE: with no ceiling the in-slot re-read collapses less, but not reliably to 0 (measured,
        # small / 20: collapsed 5 vs the baseline's 75, max calls per asset 3, never over the cap, CDN_COLLAPSE green,
        # 20261103T185251Z-2026-11-02-img-chat-media-break-be88): it may show as noise.
        "img-fetch-lane-unbounded": Fault(_lane_unbounded, (MAX_INFLIGHT,)),
        # slop/run img-chat-media --scale=medium --users=200 --no-ui --break --fault=img-fetch-on-pool-tokens
        # (at small / 20 the herd never outnumbers the threadpool: nothing to catch there). Expected noise: EXPIRED,
        # REJECTED and the stock 5xx (the wedge's own lane 503s).
        "img-fetch-on-pool-tokens": Fault(_on_pool_tokens, (COLD_HERD,)),
    }
