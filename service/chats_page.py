from __future__ import annotations

import logging
import time
from typing import Any, NamedTuple

import of_pacing
from of_client import OFAPIError, OFClient

log = logging.getLogger(__name__)

# OF 429 mid-page says "Please allow 1 seconds": wait that (when short) and re-read once; a failed page was re-asked by the UI and re-tripped OF.
IN_PAGE_RETRY_MAX_S = 2.0
_sleep = time.sleep

HOLD_MIN_S = 1.0
HOLD_MAX_S = 5.0


# A page that ended in 429 is not cached, so every re-ask hit OF again: hold the 429 per page key for OF's asked wait.
class ThrottleHold:

    def __init__(self, clock: Any = time.monotonic):
        self._clock = clock
        self._held: dict[Any, tuple[float, BaseException]] = {}

    def hold(self, key: Any, exc: BaseException, wait: float) -> float:
        now = self._clock()
        for k in [k for k, (until, _) in self._held.items() if until <= now]:
            del self._held[k]
        secs = min(max(wait, HOLD_MIN_S), HOLD_MAX_S)
        self._held[key] = (now + secs, exc)
        return secs

    def check(self, key: Any) -> BaseException | None:
        got = self._held.get(key)
        if got is None:
            return None
        if got[0] <= self._clock():
            del self._held[key]
            return None
        return got[1]


class ChatsPage(NamedTuple):
    rows: list[dict[str, Any]]
    has_more: bool
    partial: bool
    throttled: OFAPIError | None


def _read_429_once(
    read: Any, *, rows_so_far: int, offset: int, may_retry: bool,
) -> tuple[dict[str, Any] | None, OFAPIError | None]:
    try:
        return read(), None
    except OFAPIError as e:
        status = e.response.status_code if e.response is not None else None
        if not (rows_so_far and status == 429):
            raise
        err = e
    wait = of_pacing.retry_after(err)
    if not may_retry or wait is None or wait > IN_PAGE_RETRY_MAX_S:
        return None, err
    log.info("assemble_chats_page: OF 429 at offset=%s — retry once in %.1fs", offset, wait)
    _sleep(wait)
    try:
        return read(), err
    except OFAPIError as e:
        if e.response is None or e.response.status_code != 429:
            raise
        return None, e


# OF caps /chats at ~10 rows per response regardless of `limit`: loop on hasMore and advance by rows RECEIVED, or ranks ~10-24 are skipped.
def assemble_chats_page(
    client: OFClient,
    *,
    limit: int,
    offset: int,
    order: str,
    filter: str | None = None,
    list_id: str | None = None,
    q: str | None = None,
) -> ChatsPage:
    rows: list[dict[str, Any]] = []
    seen: set[Any] = set()
    cur = int(offset)
    has_more = True
    partial = False
    throttled: OFAPIError | None = None
    retried = False
    # Hard cap on reads: repeating pages with hasMore=true must not wedge the lane and cache lock.
    for _ in range((limit // 10) + 3):
        if len(rows) >= limit or not has_more:
            break
        r, err = _read_429_once(
            lambda: client.list_chats(
                limit=max(1, limit - len(rows)), offset=cur, order=order,
                filter=filter, list_id=list_id, query=q,
            ),
            rows_so_far=len(rows), offset=cur, may_retry=not retried,
        )
        if err is not None:
            retried = True
            if r is None:
                log.warning("assemble_chats_page: OF 429 at offset=%s — returning %d rows",
                            cur, len(rows))
                partial, throttled = True, err
                break
        page = r.get("list") or r.get("chats") or []
        # Read hasMore BEFORE the empty-page break: an empty read past the end carries false, and the True initializer would be cached and loop loadMore against OF.
        has_more = bool(r.get("hasMore"))
        if not page:
            break
        cur += len(page)
        added = 0
        for ch in page:
            fid = (ch.get("withUser") or {}).get("id")
            if fid is not None:
                if fid in seen:
                    continue
                seen.add(fid)
            rows.append(ch)
            added += 1
        # Dup-only page: OF offset clamp or rank churn; stop rather than spin the lane.
        if added == 0:
            log.warning("assemble_chats_page: no progress at offset=%s (%d dup rows, limit=%s)",
                        cur - len(page), len(page), limit)
            partial = True
            break
    overflow = len(rows) > limit
    if overflow:
        rows = rows[:limit]
    return ChatsPage(rows=rows, has_more=has_more or overflow, partial=partial, throttled=throttled)
