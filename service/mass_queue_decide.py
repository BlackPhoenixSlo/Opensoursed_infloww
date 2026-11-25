from __future__ import annotations


def threshold_refusal(scheduled: str | None, save_for_later: bool,
                      thresholds: bool, online_now: bool,
                      expired_over_days: float | None) -> str | None:
    if thresholds and online_now:
        # Online list is read NOW (no scheduling) and holds active subs only, so none are expired.
        if scheduled or save_for_later:
            return ("Thresholds with 'Only fans online right now' resolve "
                    "the online list at send time: send now, or turn "
                    "off online-only to schedule.")
        if expired_over_days:
            return ("OnlyFans' online list holds active subscribers only, "
                    "so 'Expired over' can't combine with online-only.")
    return None


def threshold_count_refusal(n: int, cap: int) -> str | None:
    if not n:
        return ("No fan clears these thresholds right now "
                "— nothing was sent.")
    if n > cap:
        return (f"{n} fans clear these thresholds; "
                f"one send takes at most {cap}. Raise a "
                "threshold or pick a smaller list — nothing was sent.")
    return None


def nobody_left_refusal(asked: int, listed_out: int) -> str:
    if listed_out:
        return (f"nobody left to send to: the excluded lists hold all {listed_out} fan(s) "
                "left after the opt-out and already-queued checks; nothing was sent")
    if asked:
        return (f"nobody left to send to: {asked} of {asked} fan(s) skipped "
                "(opted out or already queued); nothing was sent")
    return "nobody left to send to: no fan, list or online audience picked; nothing was sent"


def strip_excluded(user_ids: list, excluded: list) -> list:
    if not (excluded and user_ids):
        return user_ids
    excl = {int(x) for x in excluded}
    return [u for u in user_ids if int(u) not in excl]


def needs_exclude_list(excluded: list | None, user_lists: list | None,
                       online_only: bool, filters: dict | None) -> bool:
    return bool(excluded and (user_lists or online_only or filters))


def pending_placeholders(recipient_ids: list | None, echoed: set[int]) -> list[int]:
    pending: list[int] = []
    for raw in (recipient_ids or []):
        try:
            fid = int(raw)
        except (TypeError, ValueError):
            continue
        if fid not in echoed:
            pending.append(fid)
    return pending
