from datetime import datetime
from typing import Literal

from isotime import parse_iso


def is_unread(n: int | None, of_unread: bool | None = None) -> bool:
    if (n or 0) > 0:
        return True
    return of_unread if of_unread is not None else n is None


def history_plan(
    *, first_scrape: bool, unread_gate: bool, was_deferred: bool,
    local_unread: int | None, of_unread: bool | None, after_click: bool,
) -> Literal["both_ends", "defer", "page1"]:
    if not first_scrape or not unread_gate or after_click:
        return "both_ends"
    unread = is_unread(local_unread, of_unread)
    if was_deferred and (unread or of_unread is None):
        return "page1"
    return "defer" if unread else "both_ends"


def hold_ascending(
    *, unread_gate: bool, local_unread: int | None, initial_unread: int | None, of_unread: bool | None,
    after_click: bool, newer_inbound: bool,
) -> bool:
    if not unread_gate:
        return False
    if after_click:
        return newer_inbound or (local_unread or 0) > (initial_unread or 0)
    return is_unread(local_unread, of_unread)


def inbound_since(rows: list[dict], fan_id: int, at: datetime | None) -> bool:
    return at is not None and any(
        str((row.get("fromUser") or {}).get("id")) == str(fan_id)
        and (created := parse_iso(row.get("createdAt"))) is not None and created >= at
        for row in rows
    )


def new_unread_marker(
    *, deferred: bool, unread_gate: bool, local_unread: int | None, of_unread: bool | None,
) -> bool:
    return deferred and unread_gate and (of_unread is True or (local_unread or 0) > 0)
