"""service/of_paging.py — exhaustive, guarded paging of OF list endpoints.

Leaf module (stdlib only). Moved out of audiences.py, which still re-exports
the old private names (`_page_all_checked`, `_page_all`, `_ids_from_pages`,
`_LIST_PAGE`, `_ROSTER_PAGE`) as the SAME objects for existing importers.

`page_all` / `ids_from_pages` / `list_member_ids` look `page_all_checked` up as a module global at
call time, so patching `of_paging.page_all_checked` reaches every caller that
goes through this module's attributes.
"""
from __future__ import annotations

import logging

log = logging.getLogger("of-relay.of_paging")

LIST_PAGE = 100
ROSTER_PAGE = 50             # OF caps subscriber pages low; offset math is len-based
MAX_PAGES = 200              # backstop: 200 × 100 = 20k rows


def page_all_checked(fetch, max_pages: int | None = None) -> tuple[list[dict], bool]:
    """`page_all` plus an explicit INCOMPLETE flag: (rows, incomplete).
    Incomplete = the crawl hit the backstop, or OF answered a non-empty page
    that added nothing new (a repeated page: offset ignored), so rows past it
    were never read. Callers that act on "everyone else" (the audience fence,
    the include mirror, Auto_Exclude removals, "Dismiss the rest") must treat
    it as a FAILED / partial read, never as a complete snapshot — a silently
    short read would drop every unread member and un-fence / dismiss them.
    `max_pages` (opt-in) moves the backstop for one crawl; None = MAX_PAGES."""
    cap = MAX_PAGES if max_pages is None else max_pages
    out: list[dict] = []
    seen_ids: set = set()
    offset = 0
    for page in range(cap):
        r = fetch(offset)
        items = (r.get("list") or []) if isinstance(r, dict) else (r or [])
        if not items:                                 # exhausted
            return out, False
        added = 0
        for it in items:
            if not isinstance(it, dict):
                continue
            iid = it.get("id")
            if iid is not None:
                if iid in seen_ids:
                    continue
                seen_ids.add(iid)
            out.append(it)
            added += 1
        if added == 0:                                # repeated page: no progress
            log.warning("page_all_checked: page %d (offset %d) added nothing new (%d rows "
                        "read) — repeated page, read marked incomplete", page, offset, len(out))
            return out, True
        if isinstance(r, dict) and not r.get("hasMore"):
            return out, False
        offset += len(items)
    log.warning("page_all_checked hit the %d-page backstop (%d rows) — result may be "
                "truncated", cap, len(out))
    return out, True


def page_all(fetch):
    """Page an OF list endpoint to exhaustion, CAP-AGNOSTIC. `fetch(offset)`
    returns one page. Two shapes (both verified live 2026-06-12):
      • `/lists?format=infinite` → `{list, hasMore}` envelope — trust hasMore
        (OF honours limit=100 but may page; never guess from page length).
      • `/lists/{id}/users` → a BARE list with NO hasMore — page until an EMPTY
        page, so it's correct whatever page size OF actually honours (a short-
        page stop would under-read if OF ever caps below our requested limit).
    Without exhaustive paging, an exclude list with >1 page of members would
    only read page 1 and wrongly drop everyone past it as 'stale'.

    Guards (2026-07-04): some OF endpoints IGNORE `offset` and report
    hasMore=true forever (verified live on /users/me/stats/messages/group) —
    an unguarded exhaustion loop then spins forever inside a to_thread worker
    on the mass-broadcast hot path. Dedup by item id and stop on a page that
    adds nothing new, plus a hard page ceiling as the backstop. `page_all`
    drops the flag: use `page_all_checked` where a short read must not pass."""
    return page_all_checked(fetch)[0]


def ids_from_pages(fetch, **paging) -> tuple[set[int], bool]:
    """(user ids, incomplete) for any paged OF user list. Blocking.
    Rows without an int-able `id` are skipped. `paging`: `page_all_checked`'s
    keywords (`max_pages`), forwarded as given."""
    rows, truncated = page_all_checked(fetch, **paging)
    ids: set[int] = set()
    for u in rows:
        uid = u.get("id")
        if uid is None:
            continue
        try:
            ids.add(int(uid))
        except (TypeError, ValueError):
            continue
    return ids, truncated


def list_member_ids(client, list_id, **paging) -> tuple[set[int], bool]:
    """(member ids, incomplete) of an OF custom list (`/lists/{id}/users`). Blocking.
    `paging`: `page_all_checked`'s keywords; Auto_Exclude's background refresh
    crawls past 20k with `max_pages` (audiences `_refresh_auto_exclude`)."""
    return ids_from_pages(
        lambda off: client.list_users_in(list_id, limit=LIST_PAGE, offset=off), **paging)
