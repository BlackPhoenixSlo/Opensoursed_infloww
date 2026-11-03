"""service/mass_queue_decide.py — the pure half of POST /api/of/v2/messages/queue.

No DB, no OF, no fastapi: each function maps request values to a value.
mass_queue_api owns the effects (resolve_mass_audience, broadcast_lock +
ensure_exclude_list, the mass_runs mint, the OF send, the close, the unsend
enqueue), in that order, and calls these through the module attribute:

    threshold_refusal      -> the 422 text for thresholds + online-only, before any read
    threshold_count_refusal-> the 422 text for a thresholded audience of 0 / too many
    strip_excluded         -> user_ids minus the excluded ids (mirrors of_client's subtraction)
    needs_exclude_list     -> whether the excluded ids must ride the Auto_Exclude list
    pending_placeholders   -> explicit recipients OF did not echo (optimistic rows)
"""
from __future__ import annotations


def threshold_refusal(scheduled: str | None, save_for_later: bool,
                      thresholds: bool, online_now: bool,
                      expired_over_days: float | None) -> str | None:
    """The 422 text a thresholded online-only send is refused with, or None."""
    if thresholds and online_now:
        # The thresholded online audience is OF's online list read NOW, so it
        # can't wait for a schedule; and that list is active subscribers only,
        # so nobody on it has expired.
        if scheduled or save_for_later:
            return ("Thresholds with 'Only fans online right now' resolve "
                    "the online list at send time: send now, or turn "
                    "off online-only to schedule.")
        if expired_over_days:
            return ("OnlyFans' online list holds active subscribers only, "
                    "so 'Expired over' can't combine with online-only.")
    return None


def threshold_count_refusal(n: int, cap: int) -> str | None:
    """The 422 text for a thresholded audience of `n` explicit ids, or None."""
    if not n:
        return ("No fan clears these thresholds right now "
                "— nothing was sent.")
    if n > cap:
        return (f"{n} fans clear these thresholds; "
                f"one send takes at most {cap}. Raise a "
                "threshold or pick a smaller list — nothing was sent.")
    return None


def strip_excluded(user_ids: list, excluded: list) -> list:
    """`user_ids` in order minus every id whose int is excluded; elements kept
    as given. Either side empty -> `user_ids` itself (same object)."""
    if not (excluded and user_ids):
        return user_ids
    excl = {int(x) for x in excluded}
    return [u for u in user_ids if int(u) not in excl]


def needs_exclude_list(excluded: list | None, user_lists: list | None,
                       online_only: bool, filters: dict | None) -> bool:
    """Excluded ids on a list/online/filters audience must ride the Auto_Exclude
    list (OF has no per-user exclude field); explicit ids are stripped instead."""
    return bool(excluded and (user_lists or online_only or filters))


def pending_placeholders(recipient_ids: list | None, echoed: set[int]) -> list[int]:
    """Explicit recipients (int-able, in order) OF did not echo back."""
    pending: list[int] = []
    for raw in (recipient_ids or []):
        try:
            fid = int(raw)
        except (TypeError, ValueError):
            continue
        if fid not in echoed:
            pending.append(fid)
    return pending
