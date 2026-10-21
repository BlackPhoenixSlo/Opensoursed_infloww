"""
chats_page.py — one logical page of a model's OF chats, read from /chats.

Shared by the inbox list and the roster badge (server, which turns a cut-short
page into OF's own error).
"""

from __future__ import annotations

import logging
from typing import Any, NamedTuple

from of_client import OFAPIError, OFClient

log = logging.getLogger(__name__)


class ChatsPage(NamedTuple):
    rows: list[dict[str, Any]]
    # OF's hasMore as last read, or the rows overflowed `limit`.
    has_more: bool
    # Cut short: OF's 429 after some rows (`throttled`), or a dup-only read
    # (OF serving a window again). Either way not the end of history, and
    # paging on past it only ends in OF's 429.
    partial: bool
    # The 429 that cut the page short, for a caller that serves it as OF's error.
    throttled: OFAPIError | None


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
    """Blocking: assemble ONE logical page of `limit` conversations from OF.

    OF caps /chats at ~10 rows per response regardless of `limit` (same cap
    the roster scan and automation_executor's chat scrape work around), so a
    single upstream call for limit=25 silently returned ~10 rows — and the
    frontend, which advances its next offset by the 25 it ASKED for, then
    requested offset=25 and permanently skipped conversations ranked ~10-24:
    an unread fan in that band was visible to the roster badge (which pages
    by 10) but structurally unreachable by the chat list ("badge says 3, list
    shows 2"). Loop on hasMore, advancing by rows RECEIVED, until the logical
    page is full; dedupe fans that shift ranks between page reads.

    An OF 429 before any row raises; after some, the page stops there,
    `partial`. No sleep-and-retry — the caller holds a lane slot for the whole
    call."""
    rows: list[dict[str, Any]] = []
    seen: set[Any] = set()
    cur = int(offset)
    has_more = True
    partial = False
    throttled: OFAPIError | None = None
    # Hard cap on upstream reads: ~3 for a 25-row page at OF's 10-row cap, with
    # slack for rank churn. If OF ever serves repeating pages with hasMore=true,
    # this bounds the loop instead of wedging the per-account lane + per-key
    # cache lock (every future /chats and badge read for this key) forever.
    for _ in range((limit // 10) + 3):
        if len(rows) >= limit or not has_more:
            break
        try:
            r = client.list_chats(
                limit=max(1, limit - len(rows)), offset=cur, order=order,
                filter=filter, list_id=list_id, query=q,
            )
        except OFAPIError as e:
            status = e.response.status_code if e.response is not None else None
            if not (rows and status == 429):
                raise
            log.warning("assemble_chats_page: OF 429 at offset=%s — returning %d rows",
                        cur, len(rows))
            partial, throttled = True, e
            break
        page = r.get("list") or r.get("chats") or []
        # OF's hasMore is authoritative and must be read BEFORE the empty-page
        # break: an empty read past end-of-history (or a zero-match filter /
        # empty inbox) carries hasMore=false, and returning the loop's True
        # initializer instead gets cached for the full TTL and feeds the
        # frontend's owe-reply scan / infinite scroll a "more available" lie
        # it can never satisfy — an unbounded loadMore loop against live OF.
        has_more = bool(r.get("hasMore"))
        if not page:
            break
        cur += len(page)  # advance by RECEIVED, never by requested
        added = 0
        for ch in page:
            fid = (ch.get("withUser") or {}).get("id")
            if fid is not None:
                if fid in seen:
                    continue
                seen.add(fid)
            rows.append(ch)
            added += 1
        if added == 0:
            # Dup-only page: pagination isn't progressing (heavy rank churn or
            # an OF offset clamp). Stop rather than spin the lane.
            log.warning("assemble_chats_page: no progress at offset=%s (%d dup rows, limit=%s)",
                        cur - len(page), len(page), limit)
            partial = True
            break
    overflow = len(rows) > limit
    if overflow:
        rows = rows[:limit]
    return ChatsPage(rows=rows, has_more=has_more or overflow, partial=partial, throttled=throttled)
