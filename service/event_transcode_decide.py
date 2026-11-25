from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Union

from events_decide import first_key
from of_shapes import giphy_dm_id
from of_coerce import cents_or_zero as to_cents, strip_tags as strip_html  # noqa: F401 — td.strip_html (event_transcoder, tests)


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def media_ids(media: list | None) -> list[int]:
    if not isinstance(media, list):
        return []
    out: list[int] = []
    for m in media:
        if isinstance(m, dict):
            mid = m.get("id")
            if isinstance(mid, int):
                out.append(mid)
    return out



Lane = Literal["chat_message", "ppv", "toast", "queue", "other"]


def route(event: Any) -> tuple[Lane, str, Any] | None:
    event_type = first_key(event)
    if not event_type:
        return None
    payload = event[event_type]
    if event_type == "api2_chat_message" and isinstance(payload, dict):
        return "chat_message", event_type, payload
    if event_type in ("paidMessage", "messageUnlock", "purchase") and isinstance(payload, dict):
        return "ppv", event_type, payload
    if event_type == "toasts":
        return "toast", event_type, payload
    if event_type in ("chat_queue_finish", "chat_queue_update"):
        return "queue", event_type, payload
    if event_type == "chat_messages":
        # Counted at receipt: the persistence queue can lag or drop frames.
        return None
    return "other", event_type, payload


def counter_of(event: Any) -> int | None:
    v = event.get("chat_messages") if isinstance(event, dict) else None
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None



QUEUE_RING_MAX = 32
# Only the FINISH frame's total is trustworthy: the first update carries -1.
QUEUE_MIN_RECIPIENTS = 5

Ring = tuple[tuple[int, float], ...]


# Canceled removes its entry; replace-by-id since OF can re-send a finish frame.
def queue_fold(ring: Ring, event_type: str, payload: Any, now: float) -> Ring:
    if not isinstance(payload, dict):
        return ring
    try:
        queue_id = int(payload.get("id"))
    except (TypeError, ValueError):
        return ring
    if payload.get("isCanceled"):
        return tuple(e for e in ring if e[0] != queue_id)
    if event_type != "chat_queue_finish":
        return ring
    try:
        total = int(payload.get("total"))
    except (TypeError, ValueError):
        return ring
    if total < QUEUE_MIN_RECIPIENTS:
        return ring
    kept = tuple(e for e in ring if e[0] != queue_id)
    return (kept + ((queue_id, now),))[-QUEUE_RING_MAX:]


def queue_reread(before: Ring, after: Ring) -> bool:
    return bool({q for q, _at in after} - {q for q, _at in before})


def blasted(ring: Ring, now: float, seconds: float) -> bool:
    floor = now - float(seconds)
    return any(at >= floor for _q, at in ring)



# Avatar shape varies: messages give `avatar` (URL), toasts `avatarThumbs` (size->URL); prefer c144, then c50.
def user_blob(payload: Any) -> tuple[int, dict[str, Any]] | None:
    if not isinstance(payload, dict):
        return None
    user = None
    if isinstance(payload.get("fromUser"), dict):
        user = payload["fromUser"]
    elif isinstance(payload.get("user"), dict):
        user = payload["user"]
    elif isinstance(payload.get("data"), dict):
        d = payload["data"]
        if isinstance(d.get("relatedUser"), dict):
            user = d["relatedUser"]
        elif isinstance(d.get("user"), dict):
            user = d["user"]
    if not user:
        return None
    fan_id = user.get("id")
    if not isinstance(fan_id, int):
        return None
    avatar = user.get("avatar")
    if not avatar:
        thumbs = user.get("avatarThumbs")
        if isinstance(thumbs, dict):
            avatar = thumbs.get("c144") or thumbs.get("c50") or next(
                (v for v in thumbs.values() if isinstance(v, str)), None,
            )
    name = user.get("name")
    uname = user.get("username")
    if not (avatar or name or uname):
        return None
    fields: dict[str, Any] = {}
    if avatar:
        fields["avatar_url"] = avatar
    if name:
        fields["of_display_name"] = name
    if uname:
        fields["of_username"] = uname
    return fan_id, fields



@dataclass(frozen=True)
class Skip:
    message_id: Any
    fan_id: Any


@dataclass(frozen=True)
class Outbound:
    message_id: Any


@dataclass(frozen=True)
class Echo:
    message_id: Any
    fan_id: int


@dataclass(frozen=True)
class Inbound:
    msg: dict
    from_user: dict
    tip_cents: int
    image: bool
    has_media: bool


DmPlan = Union[Skip, Outbound, Echo, Inbound]


def _int_id(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def dm_key(account_id: Any, m: dict) -> Union[Skip, Outbound, Echo, None]:
    message_id = m.get("id")
    from_user = m.get("fromUser")
    if not isinstance(from_user, dict) and message_id and account_id:
        fan = _int_id(m.get("chatUserId"))
        if fan:
            return Echo(message_id, fan)
    fan_id = from_user.get("id") if isinstance(from_user, dict) else None
    if not message_id or not fan_id or not account_id:
        return Skip(message_id, fan_id)
    if str(fan_id) == str(account_id):
        return Outbound(message_id)
    return None


# tipAmount is DOLLARS, not `price`: OF sends a tip as chat_message with isTip=true and price=0.
def dm_plan(account_id: Any, m: dict, now: datetime) -> DmPlan:
    key = dm_key(account_id, m)
    if key is not None:
        return key
    message_id, from_user = m["id"], m["fromUser"]
    fan_id = from_user["id"]

    price_cents = to_cents(m.get("price"))
    is_tip = bool(m.get("isTip"))
    tip_cents = to_cents(m.get("tipAmount")) if is_tip else 0
    if is_tip and tip_cents == 0:
        tip_cents = price_cents
    mids = media_ids(m.get("media"))
    is_paid = m.get("isOpened") if price_cents > 0 else None
    msg = dict(
        account_id=str(account_id), fan_id=int(fan_id), message_id=int(message_id),
        direction="in",
        sender_name=(from_user.get("name") or from_user.get("username") or "")[:255],
        body=m.get("text") or "",
        media_ids=json.dumps(mids), media_count=int(m.get("mediaCount") or 0),
        price_cents=price_cents, is_paid=is_paid, is_tip=is_tip,
        purchased_at=parse_iso(m.get("openedAt")) if is_paid else None,
        is_unsent=False, created_at=parse_iso(m.get("createdAt")) or now,
    )
    return Inbound(msg, from_user, max(tip_cents, 0),
                   image=bool(mids or giphy_dm_id(m)) and not is_tip, has_media=bool(mids))


# isFromQueue copies are skipped: a mass's per-Fan rows belong to its placeholders (write_mass_optimistic_rows).
def echo_row(account_id: Any, m: dict, echo: Echo, now: datetime) -> dict | None:
    if m.get("isFromQueue"):
        return None
    price_cents = to_cents(m.get("price"))
    mids = media_ids(m.get("media"))
    return dict(
        account_id=str(account_id), fan_id=int(echo.fan_id), message_id=int(echo.message_id),
        direction="out", sender_name="", body=m.get("text") or "",
        media_ids=json.dumps(mids), media_count=int(m.get("mediaCount") or 0),
        price_cents=price_cents, is_paid=False if price_cents > 0 else None, is_tip=False,
        is_unsent=False, created_at=parse_iso(m.get("createdAt")) or now,
    )


def is_inbound_dm(event: Any) -> bool:
    r = route(event)
    return r is not None and r[0] == "chat_message" and dm_key(event.get("__account_id"), r[2]) is None


# Misreading a money frame costs a sale its bust, a plain DM only one re-read: unclear fields clear the cache.
def money_bust(m: dict) -> bool:
    price = m.get("price")
    if m.get("isTip") is not False or isinstance(price, bool) or not isinstance(price, (int, float)):
        return True
    return price != 0


# A blank never clobbers a populated name/avatar: a plain OF message carries only fromUser:{id}.
def fan_upsert(plans: list[Inbound]) -> tuple[dict, dict, tuple[Any, Any]]:
    first = plans[0].msg
    user: dict = {}
    for p in plans:
        for k, v in p.from_user.items():
            if v is not None and v != "":
                user[k] = v
    # The latest DM of the batch, not the last frame: a late older one never wins.
    created_at = max(p.msg["created_at"] for p in plans)
    values = dict(
        account_id=first["account_id"],
        fan_id=first["fan_id"],
        of_username=user.get("username"),
        of_display_name=user.get("name"),
        avatar_url=user.get("avatar"),
        last_message_received_at=created_at,
        source=(
            "fan" if user.get("subscribedOn") else
            "creator_we_follow" if user.get("subscribedBy") else
            "unknown"
        ),
    )
    on_conflict: dict[str, Any] = {"last_message_received_at": created_at}
    if user.get("username"):
        on_conflict["of_username"] = user["username"]
    if user.get("name"):
        on_conflict["of_display_name"] = user["name"]
    if user.get("avatar"):
        on_conflict["avatar_url"] = user["avatar"]
    return values, on_conflict, (user.get("subscribedOn"), user.get("subscribedBy"))



# The exact OF shape of a PPV-unlock frame is still unknown: most likely fields, message first.
def ppv_fields(payload: dict, now: datetime) -> dict | None:
    msg = payload.get("message") if isinstance(payload.get("message"), dict) else payload
    message_id = msg.get("id") or payload.get("messageId") or payload.get("message_id")
    fan = (msg.get("fromUser") or payload.get("user") or payload.get("fan") or {})
    fan_id = fan.get("id") if isinstance(fan, dict) else None
    amount_cents = to_cents(msg.get("price") or payload.get("price") or payload.get("amount"))
    occurred = parse_iso(
        payload.get("openedAt") or payload.get("createdAt") or msg.get("openedAt")
    ) or now
    if not (message_id and fan_id and amount_cents > 0):
        return None
    return dict(fan_id=int(fan_id), message_id=int(message_id), kind="ppv",
                amount_cents=amount_cents, occurred_at=occurred)
