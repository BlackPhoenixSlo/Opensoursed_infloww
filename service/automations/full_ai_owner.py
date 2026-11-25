from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from of_shapes import queue_id

REASONS: tuple[str, ...] = ("off_global", "off_rule", "off_mode", "not_listed", "hard_skip", "audience",
                            "human", "human_of_app", "funnel_walk", "top_spend")
OFF_REASONS: tuple[str, ...] = REASONS[:3]
HUMAN_REASONS: tuple[str, ...] = ("human", "human_of_app")


@dataclass(frozen=True)
class OwnerFacts:
    off: str | None
    listed: bool
    hard_skip: bool
    audience_ok: bool
    human: str | None
    human_at: datetime | None
    walk_advancing: bool
    spend_cents: int
    top_spend_cents: int
    fan_newest: dict | None = None


@dataclass(frozen=True)
class Stop:
    reason: str


def claims(off: str | None, listed: bool) -> bool:
    return off is None and bool(listed)


# A failed list read on a set list = not listed, so the Fan stays with today's Lanes (never widen).
def in_fans(fans_cfg: dict, in_include: bool | None, in_exclude: bool | None) -> bool:
    cfg = fans_cfg or {}
    if cfg.get("include") and in_include is not True:
        return False
    if cfg.get("exclude") and in_exclude is not False:
        return False
    return True


def who_owns(f: OwnerFacts) -> Stop | None:
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
    if not isinstance(v, str) or not v:
        return None
    try:
        t = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t.astimezone(timezone.utc).replace(tzinfo=None) if t.tzinfo else t


def of_app_human(items: list[dict], *, fan_id: int, anchor_at: datetime, known_ids: set[int]) -> datetime | None:
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
    if yield_s <= 0:
        return 0
    return max(0, int(yield_s - (now - sent_at).total_seconds()))
