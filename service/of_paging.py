"""service/of_paging.py — exhaustive, guarded paging of OF list endpoints.

Leaf module (stdlib only). Moved out of audiences.py, which still re-exports
the old private names (`_page_all_checked`, `_page_all`, `_ids_from_pages`,
`_LIST_PAGE`, `_ROSTER_PAGE`) as the SAME objects for existing importers.

`page_all` / `ids_from_pages` / `list_member_ids` / `find_list_id` look `page_all_checked` up as a module global at
call time, so patching `of_paging.page_all_checked` reaches every caller that
goes through this module's attributes.
"""
from __future__ import annotations

import logging

log = logging.getLogger("of-relay.of_paging")

LIST_PAGE = 100
ROSTER_PAGE = 50             # OF caps subscriber pages low; offset math is len-based
MAX_PAGES = 200              # backstop: 200 × 100 = 20k rows


def take_page(r, seen: set) -> tuple[list[dict], int, bool]:
    """One OF page step: (new rows, rows on the page, more pages?). `r` is the
    `{list, hasMore}` envelope or a bare list. Rows whose `id` is in `seen` are
    dropped and new ids added to it; id-less rows always count as new. `more` is
    False on an empty page or an envelope without hasMore."""
    items = (r.get("list") or []) if isinstance(r, dict) else (r or [])
    rows: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        iid = it.get("id")
        if iid is not None:
            if iid in seen:
                continue
            seen.add(iid)
        rows.append(it)
    more = bool(items) and not (isinstance(r, dict) and not r.get("hasMore"))
    return rows, len(items), more


def int_ids(rows) -> set[int]:
    """The int-able `id`s of `rows`; others skipped."""
    ids: set[int] = set()
    for u in rows:
        uid = u.get("id")
        if uid is None:
            continue
        try:
            ids.add(int(uid))
        except (TypeError, ValueError):
            continue
    return ids


def page_all_checked(fetch, max_pages: int | None = None) -> tuple[list[dict], bool]:
    """`page_all` plus an explicit INCOMPLETE flag: (rows, incomplete).
    Incomplete = the crawl hit the backstop, OF answered a non-empty page
    that added nothing new (a repeated page: offset ignored), or an empty page
    that still says `hasMore: true`, so rows past it were never read. Callers that act on "everyone else" (the audience fence,
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
        rows, n, more = take_page(r, seen_ids)
        out.extend(rows)
        if not n:                                    # exhausted, unless OF says more
            if isinstance(r, dict) and r.get("hasMore"):
                log.warning("page_all_checked: page %d (offset %d) empty with hasMore (%d rows "
                            "read) — read marked incomplete", page, offset, len(out))
                return out, True
            return out, False
        if not rows:                                 # repeated page: no progress
            log.warning("page_all_checked: page %d (offset %d) added nothing new (%d rows "
                        "read) — repeated page, read marked incomplete", page, offset, len(out))
            return out, True
        if not more:
            return out, False
        offset += n
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
    return int_ids(rows), truncated


def users_count(meta) -> int | None:
    """`usersCount` of a `/lists/{id}` answer as an int, else None."""
    try:
        return int(meta.get("usersCount"))
    except (AttributeError, TypeError, ValueError):
        return None


def list_size(client, list_id) -> int | None:
    """OF's member count of a custom list: `usersCount` of `/lists/{id}` (one GET), or None
    (no `get_list` on the client, the GET failed, or no int count: logged). Blocking."""
    try:
        return users_count(client.get_list(list_id))
    except Exception as e:  # noqa: BLE001 — no count: the read stays as it was
        log.warning("list_size list=%s: no usersCount (%s)", list_id, e)
        return None


def list_member_ids(client, list_id, **paging) -> tuple[set[int], bool]:
    """(member ids, incomplete) of an OF custom list (`/lists/{id}/users`). Blocking.
    `paging`: `page_all_checked`'s keywords; Auto_Exclude's background refresh
    crawls past 20k with `max_pages` (audiences `_refresh_auto_exclude`).
    An incomplete read whose last page is the page before it again (a TAIL repeat) holding
    exactly OF's `usersCount` (list_size: one more GET, only then) is complete: OF answers an
    offset past a list's end with its last page again (measured on AE 2026-11-11: lists of 10
    and 16 members, every read), not an empty one. Any other incomplete read (the backstop, a
    repeat of an earlier page, an empty page with hasMore) stays incomplete whatever the count.
    A lagging count can only mis-flag a read that missed rows; removals stay `members - ids`,
    so nothing unread is removed on the strength of it."""
    pages: list = []                # the row ids of the last two pages OF answered

    def fetch(off):
        r = client.list_users_in(list_id, limit=LIST_PAGE, offset=off)
        items = (r.get("list") or []) if isinstance(r, dict) else (r or [])
        # Ids only: a re-served page's other fields (an envelope's offset, a
        # user's lastSeen) may differ between two answers.
        pages[:] = [*pages[-1:], [it.get("id") for it in items if isinstance(it, dict)]]
        return r
    ids, incomplete = ids_from_pages(fetch, **paging)
    tail_repeat = (len(pages) == 2 and any(i is not None for i in pages[1])
                   and pages[0] == pages[1])
    if incomplete and tail_repeat and list_size(client, list_id) == len(ids):
        log.info("list_member_ids list=%s: all %d members read (usersCount) — complete", list_id, len(ids))
        incomplete = False
    return ids, incomplete


# OF's answers to adding a fan it will not put on any list: a fan who left the
# audience (403) and a deleted account (404; measured on AE 2026-11-12).
UNLISTABLE = {403: "Unable to add user to user list", 404: "User not found"}


def unlistable(e: Exception) -> bool:
    """OF's 403 "Unable to add user to user list" or 404 "User not found" (an
    `OFAPIError` carries its response), and no other error: a 429, a 5xx or
    a timeout is not it. A list add that failed with it is a permanent
    refusal for that fan; any other failure may be transient."""
    code = getattr(getattr(e, "response", None), "status_code", None)
    want = UNLISTABLE.get(code)
    return want is not None and want in str(e)


class ListLookupIncomplete(RuntimeError):
    """`find_list_id`: OF's `/lists` read came back incomplete and the name is
    not among the rows read, so "absent" cannot be told from "not read"."""


def find_list_id(client, name: str) -> int | None:
    """The id of the account's OF list named exactly `name` (`/lists`, paged),
    or None when a COMPLETE read has no such list. Blocking. A name missing
    from an INCOMPLETE read raises `ListLookupIncomplete`: a find-or-create
    caller that took it as absent would create a duplicate list."""
    rows, incomplete = page_all_checked(
        lambda off: client.get_lists(limit=LIST_PAGE, offset=off))
    lid = next((it.get("id") for it in rows if (it.get("name") or "") == name), None)
    if lid is not None:
        return int(lid)
    if incomplete:
        raise ListLookupIncomplete(
            f"OF lists read incomplete ({len(rows)} read), no {name!r} among them")
    return None


# ── GET /schedules (the dated calendar) ───────────────────────────────────
# Measured live 2026-11-21 (capture queue--scheduled-post-endpoint + paging
# read): dated scheduled posts are ONLY here (/schedules/later/post is the
# undated "saved for later" list). OF honours the publishDate range, IGNORES
# `offset` and `limit`, and sends no hasMore/total/cursor: one read returns the
# whole range. So a window is walked in date chunks, never in offset pages.
# ASSUMPTION: a read of >= SCHEDULE_PAGE rows, or one that says hasMore, may be
# cut short by a server cap nobody has seen (none seen at 100) — such a 7-day
# chunk is re-read one day at a time, and only such a single day makes the
# listing incomplete.
SCHEDULE_PAGE = 100
# ASSUMPTION: 7-day chunks keep most chunks under SCHEDULE_PAGE in one read.
SCHEDULE_CHUNK_DAYS = 7
# ASSUMPTION: 1 day before and 2 after cover any time-zone skew between the
# UTC dates used here and OF's filter[timeZone], plus a post minted near midnight.
SCHEDULE_PAD_BEFORE_DAYS = 1
SCHEDULE_PAD_AFTER_DAYS = 2


def schedule_chunks(days: int, *, chunk_days: int = SCHEDULE_CHUNK_DAYS,
                    today=None) -> list[tuple]:
    """Date ranges (date objects) spanning today-pad .. today+days+pad (UTC).
    Neighbouring ranges share their boundary day, so the walk is gap-free
    whether OF treats publishDateEnd as inclusive or not; rows read twice are
    deduped by the caller."""
    from datetime import datetime, timedelta, timezone
    today = today or datetime.now(timezone.utc).date()
    lo = today - timedelta(days=SCHEDULE_PAD_BEFORE_DAYS)
    hi = today + timedelta(days=days + SCHEDULE_PAD_AFTER_DAYS)
    out, start = [], lo
    while True:
        end = min(start + timedelta(days=chunk_days), hi)
        out.append((start, end))
        if end >= hi:
            return out
        start = end


def schedule_row_key(row) -> str:
    """Identity of a /schedules row, for deduping overlapping ranges."""
    if not isinstance(row, dict):
        return repr(row)
    ent = row.get("entity")
    eid = ent.get("id") if isinstance(ent, dict) else None
    return f"{row.get('type')}:{row.get('id')}:{eid}"


def _has_text(row) -> bool:
    """Whether a /schedules row's post carries its text (rawText or text)."""
    ent = row.get("entity") if isinstance(row, dict) else None
    return isinstance(ent, dict) and any(
        isinstance(ent.get(f), str) for f in ("rawText", "text"))


def _schedule_read(client, lo, hi, page: int) -> tuple[list, str | None, str | None]:
    """One /schedules read for lo..hi: (rows, why it cannot be trusted | None,
    why it may be cut short | None). A reply that is not `{list: [...]}`, or
    says OF is still syncing, is NOT a complete range — reading it as one is
    how an orphan goes unlisted. One that says hasMore (OF pages /schedules by
    date only, there is no next page to ask for) or holds `page` rows may be
    cut short: a narrower range is read instead. The rows of a readable list
    are still returned: they exist on OF even when the range may hold more."""
    resp = client.schedules(publish_date=lo.isoformat(),
                            publish_date_end=hi.isoformat(), limit=page)
    if not isinstance(resp, dict):
        return [], f"reply is {type(resp).__name__}, not an object", None
    batch = resp.get("list")
    if not isinstance(batch, list):
        return [], "reply has no list" if "list" not in resp else "list is not a list", None
    if resp.get("syncInProcess"):
        return batch, "OF says syncInProcess", None
    if resp.get("hasMore"):
        return batch, None, "OF says hasMore"
    return batch, None, f"{len(batch)} rows (maybe truncated)" if len(batch) >= page else None


def schedules_in_window(client, days: int, *, page: int = SCHEDULE_PAGE,
                        chunk_days: int = SCHEDULE_CHUNK_DAYS,
                        today=None) -> tuple[list, str | None]:
    """Every /schedules row (posts AND chats) from today-pad to
    today+days+pad: (deduped rows, why the listing is INCOMPLETE | None).
    Every chunk is read even after one fails — a carrier sits ~days out, in
    the LAST chunk, so stopping at the first bad chunk never reaches it — and
    the rows are everything that could be read. A read that raises (an HTTP
    502, a timeout) is a gap like a bad reply: the walk goes on. Blocking; at
    most one read per chunk plus one per day of a cut chunk. A row read twice
    keeps the copy whose post carries text: a cut chunk may list a post bare
    while its day re-read lists it whole. When the second value is set, absence
    from the rows proves nothing: callers may act on what was listed, never on
    what was not."""
    from datetime import timedelta
    rows: dict[str, object] = {}
    gaps: list[str] = []

    def add(batch):
        for r in batch:
            k = schedule_row_key(r)
            if k not in rows or (_has_text(r) and not _has_text(rows[k])):
                rows[k] = r

    def read(lo, hi):
        try:
            return _schedule_read(client, lo, hi, page)
        except Exception as e:  # noqa: BLE001 — one failed range is a gap, not the end
            return [], f"read failed: {e}", None

    for lo, hi in schedule_chunks(days, chunk_days=chunk_days, today=today):
        batch, why, cut = read(lo, hi)
        add(batch)
        if why:
            gaps.append(f"{lo}..{hi}: {why}")
            continue
        if not cut:
            continue
        # Maybe truncated: re-read the chunk a day at a time. Each day range
        # (d, d+1) overlaps the next, so it is gap-free either way publishDateEnd
        # is read, exactly like the chunks.
        log.warning("schedules_in_window: %s..%s %s — re-reading it day by day",
                    lo, hi, cut)
        d = lo
        while d < hi:
            day, why, cut = read(d, d + timedelta(days=1))
            add(day)
            if why or cut:
                gaps.append(f"{d}: {why or cut} in one day")
            d += timedelta(days=1)
    return list(rows.values()), "; ".join(gaps) or None
