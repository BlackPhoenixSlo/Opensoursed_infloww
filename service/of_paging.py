from __future__ import annotations

import logging

from side_effect_gate import ListAudience

log = logging.getLogger("of-relay.of_paging")

LIST_PAGE = 100
ROSTER_PAGE = 50  # OF caps subscriber pages low; offset math is len-based
MAX_PAGES = 200


def _items(r) -> list:
    return (r.get("list") or []) if isinstance(r, dict) else (r or [])


def take_page(r, seen: set) -> tuple[list[dict], int, bool]:
    items = _items(r)
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
    # Callers acting on "everyone else" must treat incomplete as a FAILED read: a silently short read would drop every unread member.
    cap = MAX_PAGES if max_pages is None else max_pages
    out: list[dict] = []
    seen_ids: set = set()
    offset = 0
    # Some OF endpoints ignore offset and report hasMore forever (measured on /users/me/stats/messages/group): dedup by id, stop on a page adding nothing, hard page ceiling.
    for page in range(cap):
        r = fetch(offset)
        rows, n, more = take_page(r, seen_ids)
        out.extend(rows)
        # /lists/{id}/users is a bare list with no hasMore: page until an empty page; /lists?format=infinite carries hasMore, trust it.
        if not n:
            if isinstance(r, dict) and r.get("hasMore"):
                log.warning("page_all_checked: page %d (offset %d) empty with hasMore (%d rows "
                            "read) — read marked incomplete", page, offset, len(out))
                return out, True
            return out, False
        if not rows:
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
    return page_all_checked(fetch)[0]


def ids_from_pages(fetch, **paging) -> tuple[set[int], bool]:
    rows, truncated = page_all_checked(fetch, **paging)
    return int_ids(rows), truncated


def users_count(meta) -> int | None:
    try:
        return int(meta.get("usersCount"))
    except (AttributeError, TypeError, ValueError):
        return None


def list_size(client, list_id) -> int | None:
    try:
        return users_count(client.get_list(list_id))
    except Exception as e:  # noqa: BLE001 — no count: the read stays as it was
        log.warning("list_size list=%s: no usersCount (%s)", list_id, e)
        return None


def _valid_id(row) -> int | None:
    uid = row.get("id") if isinstance(row, dict) else None
    if isinstance(uid, int) and not isinstance(uid, bool):
        return uid
    if isinstance(uid, str) and uid.isascii() and uid.isdigit():
        return int(uid)
    return None


def _one_page_member_ids(client, list_id, page: int) -> tuple[set[int], bool]:
    r = client.list_users_in(list_id, limit=page, offset=0)
    items = _items(r)
    got = [_valid_id(it) for it in items]
    ids = {i for i in got if i is not None}
    complete = isinstance(r, dict) and r.get("hasMore") is False and None not in got
    return ids, not complete


def list_audience(client, list_id) -> ListAudience:
    try:
        ids, cut = list_member_ids(client, list_id)
    except Exception as e:  # noqa: BLE001 — an unreadable list is an incomplete audience
        log.info("list_audience list=%s: members unreadable (%s)", list_id, e)
        return ListAudience(str(list_id), frozenset(), False)
    return ListAudience(str(list_id), frozenset(str(i) for i in ids), not cut)


def list_member_ids(client, list_id, **paging) -> tuple[set[int], bool]:
    if page := getattr(client, "platform_list_page", None):
        return _one_page_member_ids(client, list_id, page)
    pages: list = []

    def fetch(off):
        r = client.list_users_in(list_id, limit=LIST_PAGE, offset=off)
        items = _items(r)
        pages[:] = [*pages[-1:], [it.get("id") for it in items if isinstance(it, dict)]]
        return r
    ids, incomplete = ids_from_pages(fetch, **paging)
    # OF answers an offset past a list's end with its last page again, not an empty one (measured).
    tail_repeat = (len(pages) == 2 and any(i is not None for i in pages[1])
                   and pages[0] == pages[1])
    if incomplete and tail_repeat and list_size(client, list_id) == len(ids):
        log.info("list_member_ids list=%s: all %d members read (usersCount) — complete", list_id, len(ids))
        incomplete = False
    return ids, incomplete


# OF's answers to adding a fan it will not put on any list: left the audience (403), deleted account (404).
UNLISTABLE = {403: "Unable to add user to user list", 404: "User not found"}


def unlistable(e: Exception) -> bool:
    code = getattr(getattr(e, "response", None), "status_code", None)
    want = UNLISTABLE.get(code)
    return want is not None and want in str(e)


class ListLookupIncomplete(RuntimeError):
    pass


def find_list_id(client, name: str) -> int | None:
    # A name missing from an INCOMPLETE read raises: a find-or-create caller that took it as absent would create a duplicate list.
    rows, incomplete = page_all_checked(
        lambda off: client.get_lists(limit=LIST_PAGE, offset=off))
    lid = next((it.get("id") for it in rows if (it.get("name") or "") == name), None)
    if lid is not None:
        return int(lid)
    if incomplete:
        raise ListLookupIncomplete(
            f"OF lists read incomplete ({len(rows)} read), no {name!r} among them")
    return None


# /schedules honours the publishDate range but ignores offset/limit and sends no hasMore/total: walk date chunks, never offset pages.
SCHEDULE_PAGE = 100
SCHEDULE_CHUNK_DAYS = 7
# Assumed: 1 day before and 2 after cover time-zone skew between UTC dates here and OF's filter[timeZone].
SCHEDULE_PAD_BEFORE_DAYS = 1
SCHEDULE_PAD_AFTER_DAYS = 2


def schedule_chunks(days: int, *, chunk_days: int = SCHEDULE_CHUNK_DAYS,
                    today=None) -> list[tuple]:
    from datetime import datetime, timedelta, timezone
    today = today or datetime.now(timezone.utc).date()
    lo = today - timedelta(days=SCHEDULE_PAD_BEFORE_DAYS)
    hi = today + timedelta(days=days + SCHEDULE_PAD_AFTER_DAYS)
    # Neighbouring ranges share their boundary day so the walk is gap-free whether OF treats publishDateEnd as inclusive or not.
    out, start = [], lo
    while True:
        end = min(start + timedelta(days=chunk_days), hi)
        out.append((start, end))
        if end >= hi:
            return out
        start = end


def schedule_row_key(row) -> str:
    if not isinstance(row, dict):
        return repr(row)
    ent = row.get("entity")
    eid = ent.get("id") if isinstance(ent, dict) else None
    return f"{row.get('type')}:{row.get('id')}:{eid}"


def _has_text(row) -> bool:
    ent = row.get("entity") if isinstance(row, dict) else None
    return isinstance(ent, dict) and any(
        isinstance(ent.get(f), str) for f in ("rawText", "text"))


def _schedule_read(client, lo, hi, page: int) -> tuple[list, str | None, str | None]:
    # A reply that is not {list: [...]} or says OF is still syncing is NOT a complete range: reading it as one is how an orphan goes unlisted.
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
    # Every chunk is read even after one fails: a carrier sits days out in the LAST chunk, so stopping at the first bad chunk never reaches it.
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
