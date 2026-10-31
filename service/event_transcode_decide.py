"""
event_transcode_decide — the pure decisions of service/event_transcoder.py.

The transcoder is the shell: it owns the DB writes (through `of_writer`), the
cache patches, the webhook hooks and the per-account state. Everything here is a
function of its arguments: no clock (callers pass `now`), no DB, no I/O, no
import of `event_transcoder` (no cycle). Tables: tests/test_event_transcode_decide.py.

  route(event)              which writer an OF WS frame goes to
  queue_fold / blasted      the "did this account just blast?" ring
  user_blob(payload)        the Fan touch a non-message frame carries
  dm_plan(aid, m, now)      Skip | Outbound | Inbound for a chat_message
  fan_upsert(plans)         the `fans` upsert of one chat's DM batch
  ppv_fields(payload, now)  the ledger row of a PPV-unlock frame
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Union

from events_decide import first_key
from of_shapes import giphy_dm_id   # stdlib-only OF payload-shape reader

# ── Field parsers ────────────────────────────────────────────────────

def parse_iso(s: str | None) -> datetime | None:
    """OF returns ISO 8601 with `+00:00` suffix. fromisoformat handles it
    on 3.11+; we strip a trailing `Z` for the older variant just in case."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def to_cents(price: Any) -> int:
    """OF prices come as floats like 9.99. Convert via int(round(... * 100))
    to avoid 9.99 → 998 floating-point traps."""
    try:
        if price is None or price == "":
            return 0
        return int(round(float(price) * 100))
    except Exception:
        return 0


def media_ids(media: list | None) -> list[int]:
    """Pluck media.id from each item; skip non-int."""
    if not isinstance(media, list):
        return []
    out: list[int] = []
    for m in media:
        if isinstance(m, dict):
            mid = m.get("id")
            if isinstance(mid, int):
                out.append(mid)
    return out


def strip_html(s: str) -> str:
    """Quick-and-dirty tag strip for the chat-list preview. OF returns
    minimal HTML (<p>, <span class>, <strong>); regex is enough.
    Full sanitization happens client-side when the body is rendered."""
    if not s:
        return ""
    return re.sub(r"<[^>]+>", "", s).strip()


# ── Routing ──────────────────────────────────────────────────────────

Lane = Literal["chat_message", "ppv", "toast", "queue", "other"]


def route(event: Any) -> tuple[Lane, str, Any] | None:
    """`(lane, event_type, payload)` for one frame, None for a non-dict or an
    envelope with no type. "other" is the touch + discovery-log fall-through; a
    known type whose payload is not a dict falls through to it, as it always has."""
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
    return "other", event_type, payload


# ── Broadcast queue ring ─────────────────────────────────────────────
# A ring is a tuple of `(queue_id, received_at)`, oldest first; the shell keeps
# one per account and stamps `received_at` with its own monotonic clock.

QUEUE_RING_MAX = 32
# A queue of fewer than five recipients is a small hand-send, not a blast. Only the
# FINISH frame's `total` is trustworthy: the first update carries -1.
QUEUE_MIN_RECIPIENTS = 5

Ring = tuple[tuple[int, float], ...]


def queue_fold(ring: Ring, event_type: str, payload: Any, now: float) -> Ring:
    """One `chat_queue_*` frame folded into a ring. The envelope, as `event_inbox`
    stores it::

        {"chat_queue_finish": {"id": 46605849959, "date": "...", "isReady": true,
         "isDone": true, "total": 23, "pending": 0, "canUnsend": true,
         "unsendSeconds": 1000000, "hasError": false, "isCanceled": false, ...}}

    Only the FINISH frame records — the first update carries `total: -1` and the
    ones between carry a falling `pending`, so `total` is only trustworthy at the
    end. A frame that says `isCanceled` records nothing and REMOVES any entry for
    the same queue: a blast the creator pulled back is not a blast anyone can be
    replying to. Replace-by-id: OF can re-send a finish frame, and two entries for
    one queue would push a real second blast out of a 32-deep ring for no gain."""
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


def blasted(ring: Ring, now: float, seconds: float) -> bool:
    """Did any queue in the ring finish within `seconds` of `now`?"""
    floor = now - float(seconds)
    return any(at >= floor for _q, at in ring)


# ── Fan touch from a non-message frame ───────────────────────────────

def user_blob(payload: Any) -> tuple[int, dict[str, Any]] | None:
    """`(fan_id, fields)` a frame's creator-side user blob can refresh, else None.

    OF embeds the blob under a few different keys (toasts use `data.relatedUser`,
    online events use `user`, …). Avatar shape varies: messages give `avatar`
    (string URL), toasts give `avatarThumbs` (dict of size→URL). We prefer c144,
    fall back to c50, then any string. None without an int id or a field worth
    writing."""
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


# ── api2_chat_message ────────────────────────────────────────────────

@dataclass(frozen=True)
class Skip:
    """No primary key: a message id, a fan id or the account is missing."""
    message_id: Any
    fan_id: Any


@dataclass(frozen=True)
class Outbound:
    """Our own send echoed back: no row (the send handler owns it), cache bust only."""
    message_id: Any


@dataclass(frozen=True)
class Inbound:
    """One inbound DM. `msg`: its `messages` row, exact columns less `raw_json`
    (the shell's). `image`: the image hook owns it, else the words hook does;
    `has_media` is the image hook's flag (False for a gif). `tip_cents > 0` fires
    the tip hook and writes the ledger row."""
    msg: dict
    from_user: dict
    tip_cents: int
    image: bool
    has_media: bool


DmPlan = Union[Skip, Outbound, Inbound]


def dm_plan(account_id: Any, m: dict, now: datetime) -> DmPlan:
    """What one `api2_chat_message` payload becomes. `now` stamps a frame
    without `createdAt`.

    Direction: 'out' when `fromUser.id == account_id` (OF's echo of a send, which
    carries no recipient, so no (account, fan, message) key), else 'in'.

    A tip's $ value rides in top-level `tipAmount` (DOLLARS), NOT `price` — OF
    sends a tip as a chat_message with isTip=true and price=0. Fall back to price
    for an isTip frame lacking tipAmount; price_cents stays separate so the PPV
    logic is untouched. ONE predicate picks the words-vs-image lane: a non-tip
    media/gif DM is the image hook's, which owns its words too."""
    message_id = m.get("id")
    from_user = m.get("fromUser") or {}
    fan_id = from_user.get("id")
    if not message_id or not fan_id or not account_id:
        return Skip(message_id, fan_id)
    if str(fan_id) == str(account_id):
        return Outbound(message_id)

    price_cents = to_cents(m.get("price"))
    is_tip = bool(m.get("isTip"))
    tip_cents = to_cents(m.get("tipAmount")) if is_tip else 0
    if is_tip and tip_cents == 0:
        tip_cents = price_cents
    mids = media_ids(m.get("media"))
    is_paid = m.get("isOpened") if price_cents > 0 else None  # NULL for free messages
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


def fan_upsert(plans: list[Inbound]) -> tuple[dict, dict, tuple[Any, Any]]:
    """`(values, on_conflict, (subscribedOn, subscribedBy))` of the `fans` upsert
    for one chat's DM batch; the shell adds `updated_at` and the flags' source
    heal (automations._common.source_self_heal_set) to the conflict set.

    The newest non-blank value of each `fromUser` field across the frames wins.
    On conflict a blank NEVER clobbers a populated name/avatar: a plain OF message
    carries only `fromUser:{id}`, and writing `.get(...)` there used to null out
    names a toast/online frame had captured. `source` on insert reads OF's flags
    (`subscribedOn` = our fan, `subscribedBy` = a creator we follow) — the same
    rule as _common.classify_source, which this module cannot import (SQLAlchemy)."""
    first, last = plans[0].msg, plans[-1].msg
    user: dict = {}
    for p in plans:
        for k, v in p.from_user.items():
            if v is not None and v != "":
                user[k] = v
    created_at = last["created_at"]
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


# ── PPV unlock ───────────────────────────────────────────────────────

def ppv_fields(payload: dict, now: datetime) -> dict | None:
    """The ledger fields of a PPV-unlock frame (`fan_id`, `message_id`, `kind`,
    `amount_cents`, `occurred_at`), None when one is missing or the amount is 0.
    The exact OF shape is still unknown: read the most likely fields, message
    first."""
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
