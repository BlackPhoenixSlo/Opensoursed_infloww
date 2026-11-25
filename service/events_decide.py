from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, NamedTuple, Optional, Union

# Per account: sized for a laptop sleep or a dropped socket on a busy Creator.
RING_MAX = 256
BATCH_MAX = 200
RATE_TAU_S = 1.0
# Within a batch only the newest frame per (type, account, field) is kept: the newest of each of these says everything the older ones did.
COALESCE = {"chat_typing": "fan_id", "chat_queue_update": "id", "creator_refreshed": "account_id"}


@dataclass(frozen=True, slots=True)
class Rings:
    epoch: str
    seq: int = 0
    rings: Mapping[str, tuple[tuple[int, Any], ...]] = field(default_factory=dict)
    evicted: Mapping[str, int] = field(default_factory=dict)
    evicted_any: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Stream:
    rate: float = 0.0
    rate_at: float = 0.0


@dataclass(frozen=True, slots=True)
class Knobs:
    min_rate: float
    window_ms: float
    max_window_ms: float


@dataclass(frozen=True, slots=True)
class Published:
    frame: Any


@dataclass(frozen=True, slots=True)
class Deliver:
    now: float
    ends: bool
    open_n: int
    open_deadline: float
    knobs: Knobs


@dataclass(frozen=True, slots=True)
class Resync:
    pass


@dataclass(frozen=True, slots=True)
class Emit:
    frames: tuple


@dataclass(frozen=True, slots=True)
class Head:
    eid: str


@dataclass(frozen=True, slots=True)
class Send:
    pass


@dataclass(frozen=True, slots=True)
class Open:
    deadline: float


@dataclass(frozen=True, slots=True)
class Append:
    close: bool = False


RingEffect = Union[Resync, Emit, Head]
StreamEffect = Union[Send, Open, Append]


def first_key(event: Any) -> Optional[str]:
    if not isinstance(event, dict):
        return None
    for k in event:
        if not k.startswith("__"):
            return k
    return None


def frame_fan_id(event: Mapping) -> Any:
    kind = first_key(event)
    body = event.get(kind) if kind else None
    if not isinstance(body, Mapping):
        return None
    if kind == "api2_chat_message":
        sender = (body.get("fromUser") or {}).get("id") if isinstance(body.get("fromUser"), Mapping) else None
        if sender is not None and str(sender) != str(event.get("__account_id")):
            return sender
        if event.get("__fan_id") is not None:
            return event["__fan_id"]
        target = body.get("toUser")
        if isinstance(target, Mapping) and target.get("id") is not None:
            return target["id"]
        from event_transcode_decide import Echo, dm_key
        plan = dm_key(event.get("__account_id"), body)
        return plan.fan_id if isinstance(plan, Echo) else None
    return body.get("fan_id")


def toast_fan_id(toast: Any) -> Any:
    if not isinstance(toast, Mapping):
        return None
    data = toast.get("data") if isinstance(toast.get("data"), Mapping) else {}
    rel = data.get("relatedUser")
    if isinstance(rel, Mapping) and rel.get("id") is not None:
        return rel["id"]
    repl = data.get("replacements")
    if isinstance(repl, Mapping) and repl.get("{RELATED_USER_ID}"):
        return repl["{RELATED_USER_ID}"]
    sender = toast.get("fromUser")
    return sender.get("id") if isinstance(sender, Mapping) else None


def ring_key(frame: Mapping) -> str:
    return "" if frame.get("__agency") is not None else str(frame.get("__account_id") or "")


def head_id(st: Rings) -> str:
    return f"{st.epoch}.{st.seq}"


def rate_now(st: Stream, now: float) -> float:
    return st.rate * math.exp((st.rate_at - now) / RATE_TAU_S)


def batching_on(knobs: Knobs) -> bool:
    return knobs.window_ms > 0


def window_s(rate: float, knobs: Knobs) -> float:
    if not batching_on(knobs) or rate <= knobs.min_rate:
        return 0.0
    if rate > 10 * knobs.min_rate:
        return max(knobs.window_ms, knobs.max_window_ms) / 1000
    return knobs.window_ms / 1000


def _coalesce_key(frame: Mapping) -> Optional[tuple]:
    event_type = first_key(frame)
    fld = COALESCE.get(event_type)  # type: ignore[arg-type]
    body = frame.get(event_type) if fld else None
    if not isinstance(body, dict) or body.get(fld) is None:
        return None
    return event_type, frame.get("__account_id"), body[fld]


def coalesce(frames) -> list:
    seen: set = set()
    kept = []
    for f in reversed(frames):
        key = _coalesce_key(f)
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        kept.append(f)
    kept.reverse()
    return kept


STATE_TYPES = frozenset({
    "session_dead",
    "account_active",
    "proxy_switched",
    "rule_run_finished",
    "scheduled_send_changed",
    "permissions_changed",
    "assignment_changed",
    "agency_notifications",
    "sessions_revoked",
})
# The stream ends after these so the browser reconnects and reads the session afresh.
ENDS_STREAM = frozenset({"permissions_changed", "assignment_changed", "sessions_revoked"})

# Allow-list of what a browser tab listens for; every other OF frame is persisted to event_inbox but not pushed.
SSE_TYPES = frozenset({
    "api2_chat_message",
    "toasts",
    "transaction_recorded",
    "purchase_notified",
    "vault_history_changed",
    "chat_typing",
    # Only the finish frame's `total` is trustworthy (event_transcoder).
    "chat_queue_update",
    "chat_queue_finish",
    "chat_responded",
    "creator_warmed",
    "creator_refreshed",
    "chat_read_changed",
    "chat_restrict_changed",
}) | STATE_TYPES

ANY_SCOPE_TYPES = frozenset({"creator_warmed", "creator_refreshed", "chat_read_changed", "chat_restrict_changed",
                             "chat_responded", "transaction_recorded", "purchase_notified", "toasts"})
MONEY_TOAST_TYPES = frozenset({"tip", "tips", "purchase", "purchases", "paided_message"})

# Another creator's home-feed frames were ~82% of WS traffic (measured, 8,451 of 10,308 rows) and nothing reads them; the account's OWN post_published is kept.
FEED_POST_TYPES = frozenset({
    "post_published", "post_expire", "post_updated", "post_fundraising_updated",
})


def is_feed_noise(event: Any, account_id: Any) -> bool:
    event_type = first_key(event)
    if event_type not in FEED_POST_TYPES:
        return False
    payload = event.get(event_type)
    if isinstance(payload, dict) and account_id is not None \
            and str(payload.get("user_id")) == str(account_id):
        return False
    return True


def typing_fan_id(payload: Any) -> Optional[int]:
    if not isinstance(payload, dict):
        return None
    for v in (payload.get("id"), payload.get("user_id"),
              (payload.get("fromUser") or {}).get("id") if isinstance(payload.get("fromUser"), dict) else None,
              (payload.get("user") or {}).get("id") if isinstance(payload.get("user"), dict) else None):
        try:
            if v is not None:
                return int(v)
        except (TypeError, ValueError):
            continue
    return None


def typing_due(last_at: Optional[float], now: float, throttle: float) -> bool:
    return last_at is None or now - last_at >= throttle


def sees(scope: str, accounts: Optional[frozenset], account_id: Any, any_scope: bool = False) -> bool:
    aid = str(account_id)
    if scope != "all" and scope != f"model:{aid}":
        if not (any_scope and scope.startswith("model:") and accounts is not None):
            return False
    return accounts is None or aid in accounts


def is_money_toast(event: Mapping) -> bool:
    items = event.get("toasts")
    return isinstance(items, list) and any(
        isinstance(t, dict) and str(t.get("type") or "").lower() in MONEY_TOAST_TYPES for t in items)


def any_scope(event: Mapping) -> bool:
    kind = first_key(event)
    return kind in ANY_SCOPE_TYPES and (kind != "toasts" or is_money_toast(event))


def wants(scope: str, accounts: Optional[frozenset], agencies: frozenset, event: Mapping) -> bool:
    agency = event.get("__agency")
    if agency is not None:
        return str(agency) in agencies
    account_id = event.get("__account_id")
    if account_id is None:
        return scope == "all" and accounts is None
    return sees(scope, accounts, account_id, any_scope(event))


def strips_message(readable: Optional[frozenset], event: Mapping) -> bool:
    body = event.get("chat_responded")
    return (readable is not None and isinstance(body, dict) and "message" in body
            and str(event.get("__account_id")) not in readable)


def _missed(st: Rings, last_id: Optional[str], sees: Callable[[str], bool],
            wants: Callable[[Any], bool], sees_any: Optional[Callable[[str], bool]],
            project: Callable[[Any], Any]) -> tuple[list, bool]:
    if not last_id:
        return [], False
    epoch, _, n = last_id.partition(".")
    try:
        since = int(n)
    except ValueError:
        return [], True
    if epoch != st.epoch or since > st.seq:
        return [], True
    gap = False
    missed: list[tuple[int, Any]] = []
    for key, ring in st.rings.items():
        if not key or sees(key):
            evicted = st.evicted
        elif sees_any is not None and sees_any(key):
            evicted = st.evicted_any
        else:
            continue
        if evicted.get(key, 0) > since:
            gap = True
        missed.extend((seq, out) for seq, f in ring if seq > since and wants(f)
                      and (out := project(f)) is not None)
    missed.sort(key=lambda t: t[0])
    return [f for _, f in missed], gap


def decide_ring(st: Rings, ev: Published) -> Rings:
    seq = st.seq + 1
    key = ring_key(ev.frame)
    ring = st.rings.get(key, ())
    evicted, evicted_any = st.evicted, st.evicted_any
    if len(ring) == RING_MAX:
        dropped, frame = ring[0]
        evicted = {**evicted, key: dropped}
        if isinstance(frame, Mapping) and any_scope(frame):
            evicted_any = {**evicted_any, key: dropped}
        ring = ring[1:]
    return Rings(st.epoch, seq, {**st.rings, key: ring + ((seq, ev.frame),)}, evicted, evicted_any)


def ended_since(st: Rings, since: int, wants: Callable[[Any], bool]) -> bool:
    # Fails closed: every ENDS_STREAM frame lands in this ring, so an eviction past `since` may hide one.
    if st.evicted.get("", 0) > since:
        return True
    for ring in st.rings.values():
        for seq, f in reversed(ring):
            if seq <= since:
                break
            if first_key(f) in ENDS_STREAM and wants(f):
                return True
    return False


def replay(st: Rings, last_id: Optional[str], sees: Callable[[str], bool], wants: Callable[[Any], bool],
           knobs: Knobs, sees_any: Optional[Callable[[str], bool]] = None,
           *, project: Callable[[Any], Any] = lambda frame: frame) -> tuple[RingEffect, ...]:
    missed, gap = _missed(st, last_id, sees, wants, sees_any, project)
    effects: list[RingEffect] = [Resync()] if gap else []
    step = BATCH_MAX if batching_on(knobs) else 1
    effects.extend(Emit(tuple(coalesce(missed[i:i + step]))) for i in range(0, len(missed), step))
    effects.append(Head(head_id(st)))
    return tuple(effects)


def decide_stream(st: Stream, ev: Deliver) -> tuple[Stream, StreamEffect]:
    rate = rate_now(st, ev.now) + 1 / RATE_TAU_S
    nxt = Stream(rate, ev.now)
    if ev.open_n and ev.open_n < BATCH_MAX and ev.now < ev.open_deadline:
        # Nothing may follow a stream-ending frame into this session's stream: it closes the batch.
        return nxt, Append(close=ev.ends)
    window = window_s(rate, ev.knobs)
    if window <= 0 or ev.ends:
        return nxt, Send()
    return nxt, Open(ev.now + window)


# `typing` repeats every ~2-3 s per typing fan and nothing reads it back.
UNPERSISTED_TYPES = frozenset({"typing"})


def inbox_row(account_id: Optional[str], event_type: Optional[str], payload: Any) -> dict:
    event_type = event_type or "unknown"
    # OF's top-level `id` is the dedup key so reconnect replays don't double-write.
    provider_id = None
    if isinstance(payload, dict):
        for k in ("id", "messageId", "eventId"):
            v = payload.get(k)
            if v is not None:
                provider_id = f"{event_type}:{v}"
                break
    return {"account_id": account_id, "source": "of_ws", "event_type": event_type,
            "payload": payload, "provider_event_id": provider_id}


def can_stub_chat_view(filter: str | None, list_id: str | None, query: str | None) -> bool:
    return (not filter or filter == "unread") and list_id is None and not query


def is_plain_chat_view(filter: str | None, list_id: str | None, query: str | None) -> bool:
    return not filter and can_stub_chat_view(filter, list_id, query)


class InboxRowUnpatched(Enum):
    VALUE = "unpatched"


PriorInboxRow = dict | None | InboxRowUnpatched


class PersistItem(NamedTuple):
    account_id: Optional[str]
    event_type: Optional[str]
    persistable: dict
    event: dict
    inbound_dm: bool = False
    prior: PriorInboxRow = InboxRowUnpatched.VALUE


def persist_plan(batch: list[PersistItem]) -> list[dict]:
    return [inbox_row(it.account_id, it.event_type, it.persistable)
            for it in batch if it.event_type not in UNPERSISTED_TYPES]
