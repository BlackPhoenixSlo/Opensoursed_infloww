"""automations/full_ai_owner.py — who owns a Fan's DM in live Mode (spec 04b › Solution). Pure.

Two derived answers, no stored state (pattern `wcfi_decide.py`):

  in_fans(cfg, i, e)   the Fans list: empty include = every Fan, exclude wins, a failed read = not listed
  of_app_human(items, fan_id=, anchor_at=, known_ids=)
                       the send time of the first OF-app item a human sent after his anchor, or None
  fan_after(items, fan_id=, anchor_at=)
                       the newest OF chat item the Fan sent after his anchor, or None
  yield_left_s(sent_at, now, yield_s)
                       seconds of the Human yield still to run (0 = none)
  claims(off, listed)  Full AI is on for the Creator and the Fan is on its Fans list: the other reply
                       Lanes skip him, whatever Full AI then does (reply, no_send, Stop).
  who_owns(facts)      Full AI's own check at job start and before each bubble: `Stop(reason)` or None.
                       First match wins, in `REASONS` order:

  1. off_global / off_rule / off_mode   switch FULL_AI_CHAT_OFF; rule full_ai_chat off; Mode not live
  2. not_listed                         the Fans list says no, or its OF read failed
  3. hard_skip                          blacklist, a hard skip_list reason or unreachable, a muted creator
  4. audience                           the account fence says no
  5. human / human_of_app               a human's 1:1 answer since the anchor
  6. funnel_walk                        a pending, not held funnel_state whose walker rule is on
  7. top_spend                          lifetime spend >= top_spend_cents (0 = off)

The facts come from `full_ai_owner_io.load`. No DB, OF client, lease or dm_rate import (AST test);
`of_shapes` (pure OF frame readers) is the one app import.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from of_shapes import queue_id   # pure: OF's mass-copy marker

REASONS: tuple[str, ...] = ("off_global", "off_rule", "off_mode", "not_listed", "hard_skip", "audience",
                            "human", "human_of_app", "funnel_walk", "top_spend")
OFF_REASONS: tuple[str, ...] = REASONS[:3]
HUMAN_REASONS: tuple[str, ...] = ("human", "human_of_app")


@dataclass(frozen=True)
class OwnerFacts:
    off: str | None             # one of OFF_REASONS (the loader picks the first), None = Full AI on
    listed: bool                # on the Fans list (a failed read = False)
    hard_skip: bool
    audience_ok: bool
    human: str | None           # one of HUMAN_REASONS (rows win over the OF app), None = no human answer
    human_at: datetime | None   # the human send's time (for start_human_yield)
    walk_advancing: bool
    spend_cents: int
    top_spend_cents: int        # 0 = no limit
    fan_newest: dict | None = None   # the OF read's newest item HE sent after the anchor (None: none / not read)


@dataclass(frozen=True)
class Stop:
    reason: str


def claims(off: str | None, listed: bool) -> bool:
    """Full AI holds this Fan: every other reply Lane skips him."""
    return off is None and bool(listed)


def in_fans(fans_cfg: dict, in_include: bool | None, in_exclude: bool | None) -> bool:
    """The Fans list's verdict. Empty include = every Fan; exclude wins; a `None` membership (its OF
    read failed) on a list that is set = not listed, so the Fan stays with today's Lanes (never widen)."""
    cfg = fans_cfg or {}
    if cfg.get("include") and in_include is not True:
        return False
    if cfg.get("exclude") and in_exclude is not False:
        return False
    return True


def who_owns(f: OwnerFacts) -> Stop | None:
    """Full AI's Stop for this Fan now, or None (it may answer)."""
    if f.off is not None:
        return Stop(f.off)
    if not f.listed:
        return Stop("not_listed")
    if f.hard_skip:
        return Stop("hard_skip")
    if not f.audience_ok:
        return Stop("audience")
    if f.human is not None:
        return Stop(f.human)
    if f.walk_advancing:
        return Stop("funnel_walk")
    if f.top_spend_cents > 0 and f.spend_cents >= f.top_spend_cents:
        return Stop("top_spend")
    return None


def of_time(v) -> datetime | None:
    """OF's `createdAt` (ISO, maybe `Z` / an offset) as naive UTC, like our rows; None if unreadable."""
    if not isinstance(v, str) or not v:
        return None
    try:
        t = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t.astimezone(timezone.utc).replace(tzinfo=None) if t.tzinfo else t


def of_app_human(items: list[dict], *, fan_id: int, anchor_at: datetime, known_ids: set[int]) -> datetime | None:
    """The earliest send time of an OF chat item a human sent after his anchor: not from the Fan (an item
    with no readable sender counts as human), newer than `anchor_at`, an id not among this Fan's
    `messages` rows (`known_ids`: ours, already attributed) and no queue id (not a mass copy)."""
    hits = []
    for m in items or []:
        if not isinstance(m, dict):
            continue
        sender = m.get("fromUser")
        sender_id = sender.get("id") if isinstance(sender, dict) else None
        if sender_id is not None and str(sender_id) == str(fan_id):
            continue
        at = of_time(m.get("createdAt"))
        if at is None or at <= anchor_at:
            continue
        try:
            mid = int(m.get("id"))
        except (TypeError, ValueError):
            mid = None
        if mid is not None and mid in known_ids:
            continue
        if queue_id(m) is not None:
            continue
        hits.append(at)
    return min(hits) if hits else None


def fan_after(items: list[dict], *, fan_id: int, anchor_at: datetime) -> dict | None:
    """The newest OF chat item from the Fan (`fromUser.id`) sent after `anchor_at` with an id, or None."""
    best, best_key = None, None
    for m in items or []:
        if not isinstance(m, dict) or str((m.get("fromUser") or {}).get("id")) != str(fan_id):
            continue
        at = of_time(m.get("createdAt"))
        if at is None or at <= anchor_at or not str(m.get("id", "")).isdigit():
            continue
        key = (at, int(m["id"]))
        if best_key is None or key > best_key:
            best, best_key = m, key
    return best


def yield_left_s(sent_at: datetime, now: datetime, yield_s: int) -> int:
    """Seconds of the Human yield (`yield_s` from the human's send at `sent_at`) left at `now`; 0 when it
    has run out or is disabled (`yield_s` <= 0)."""
    if yield_s <= 0:
        return 0
    return max(0, int(yield_s - (now - sent_at).total_seconds()))
