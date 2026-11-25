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
    import img_api

    img_api._img_cache_lookup = lambda u: None


def _key_keeps_signature() -> None:
    import img_api

    img_api._img_cache_key = lambda u: hashlib.sha1(u.encode("utf-8")).hexdigest()


def _lane_unbounded() -> None:
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
        "img-cache-never-hits": Fault(_cache_never_hits, (WARM_HIT, CDN_COLLAPSE)),
        "img-cache-key-keeps-signature": Fault(_key_keeps_signature, (WARM_HIT,)),
        # not CDN_COLLAPSE: with no ceiling the in-slot re-read collapses less but not reliably to 0 (measured), so it may show as noise
        "img-fetch-lane-unbounded": Fault(_lane_unbounded, (MAX_INFLIGHT,)),
        "img-fetch-on-pool-tokens": Fault(_on_pool_tokens, (COLD_HERD,)),
    }
