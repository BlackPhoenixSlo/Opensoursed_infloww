"""service/smart_message_extras.py — the per-message settings Smart Messages'
Triggers share: media and price, Frequency, Effective / Expiry dates, the random
"after delay" and Auto-unsend.

Infloww's Smart Message editor (index.9f50f370.js, read statically) gives every
automated message the same panels; these are the ones built here, on the one
message each of our Triggers holds (no collections, no sequences):

  media_ids       vault media ids sent with the message (at most `MEDIA_MAX`).
  price_cents     0 = free; else the message is a PPV locking its media at this
                  price, at least Infloww's "Minimum $3 USD" (@15304458) and at
                  most OnlyFans' $200 PPV ceiling.
                  A price needs media. Infloww keeps the price in cents too. A
                  fan who already owns any of the media (`owners`) is never sold
                  it again: he gets the text alone, free.
  frequency       "once" / "every": Infloww's "Send only once when the fan
                  matches the trigger" / "Send every time the fan matches the
                  trigger" (@14940448, @14940514). What "every" means is each
                  sender's own (its module docstring).
  starts_at       Effective: null = "Immediately", else the scheduled instant
                  (ISO, UTC). Nothing whose moment came before it is chased.
  ends_at         Expiry: null = "Never", else the instant it stops sending.
  unsend_minutes  Auto-unsend: 0 = off, else "Unsend messages" this many
                  minutes after the send, at most 23 hours (Infloww offers 0..24
                  hour(s), @14981830, but OnlyFans' per-chat delete window is
                  about 24h, so a 24h unsend would land on a message OF no
                  longer lets us delete). A PAID message is never unsent: the house
                  floors priced unsends at 24h because a PPV's late buyers are
                  real money (automations/unsend_messages), past OF's window.
                  The job is a follow-on of the rule's run, so switching the
                  rule off cancels the unsends still waiting.
  delay_range     Purchased and Delayed welcome only: null = "immediately", else
                  [a, b] minutes, "after delay … in random minute intervals
                  a～b minutes" (@14901308 .. @14901733), clamped as Infloww's
                  `handleRuleDelayValues` (@14775733) clamps it.

The config routes validate with `validate` + `check`; every sender reads the
stored steps back through the readers below, which never trust them.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from isotime import parse_iso  # extras.parse_iso: automations/send_welcome.py reads it here

log = logging.getLogger("of-relay.smart_message_extras")

MEDIA_MAX = 40                   # OF's vault dialog: "N / 40 Selected"
PRICE_MIN_CENTS = 300            # "Minimum $3 USD"
PRICE_MAX_CENTS = 20_000         # OF's PPV max ($200)
DELAY_MIN, DELAY_MAX = 1, 60     # handleRuleDelayValues' bounds
UNSEND_MAX_MINUTES = 23 * 60     # inside OF's ~24h per-chat delete window
FREQUENCIES = ("once", "every")

_ALL_KEYS = ("media_ids", "price_cents", "frequency", "starts_at", "ends_at", "unsend_minutes")


def _int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _iso(ts: datetime) -> str:
    return ts.replace(tzinfo=timezone.utc).isoformat()


def clamp_delay(a: int, b: int) -> list[int]:
    """Infloww's `handleRuleDelayValues`: each end inside 1..60, in order, and
    never equal (an equal pair widens by a minute; 60 becomes 59～60)."""
    lo, hi = (max(DELAY_MIN, min(int(x), DELAY_MAX)) for x in (a, b))
    if lo > hi:
        lo, hi = hi, lo
    if lo == hi:
        lo, hi = (59, 60) if lo == DELAY_MAX else (lo, lo + 1)
    return [lo, hi]


# ── The config routes ─────────────────────────────────────────────────

def validate(cfg: dict, *, delay: bool = False) -> dict[str, Any]:
    """The posted keys this module owns, checked with exact JSON types (as the
    routes check theirs) and normalised; absent keys keep their stored value."""
    out: dict[str, Any] = {}
    if "media_ids" in cfg:
        ids = cfg["media_ids"]
        if not isinstance(ids, list) or not all(_int(i) and i > 0 for i in ids):
            raise HTTPException(422, "media_ids must be a list of vault media ids")
        ids = list(dict.fromkeys(ids))
        if len(ids) > MEDIA_MAX:
            raise HTTPException(422, f"at most {MEDIA_MAX} media per message")
        out["media_ids"] = ids
    if "price_cents" in cfg:
        p = cfg["price_cents"]
        if not _int(p) or p < 0 or 0 < p < PRICE_MIN_CENTS:
            raise HTTPException(422, "Minimum $3 USD")
        if p > PRICE_MAX_CENTS:
            raise HTTPException(422, "Maximum $200 USD")
        out["price_cents"] = p
    if "frequency" in cfg:
        if cfg["frequency"] not in FREQUENCIES:
            raise HTTPException(422, "frequency must be once or every")
        out["frequency"] = cfg["frequency"]
    for key in ("starts_at", "ends_at"):
        if key in cfg:
            raw = cfg[key]
            ts = parse_iso(raw)
            if raw is not None and ts is None:
                raise HTTPException(422, f"{key} must be an ISO date and time or null")
            out[key] = _iso(ts) if ts else None
    if "unsend_minutes" in cfg:
        m = cfg["unsend_minutes"]
        if not _int(m) or not 0 <= m <= UNSEND_MAX_MINUTES:
            raise HTTPException(422, f"unsend_minutes must be a whole number from 0 to {UNSEND_MAX_MINUTES}")
        out["unsend_minutes"] = m
    if delay and "delay_range" in cfg:
        r = cfg["delay_range"]
        if r is not None and not (isinstance(r, list) and len(r) == 2 and all(_int(x) for x in r)):
            raise HTTPException(422, "delay_range must be null or [min, max] minutes")
        out["delay_range"] = None if r is None else clamp_delay(*r)
    return out


def check(merged: dict) -> None:
    """Rules across keys, on the config as it will be stored."""
    if merged.get("price_cents") and not merged.get("media_ids"):
        raise HTTPException(422, "a paid message needs media")
    start, end = parse_iso(merged.get("starts_at")), parse_iso(merged.get("ends_at"))
    if start and end and end <= start:
        raise HTTPException(422, "the expiry must come after the effective date")


def public(steps: dict, *, frequency: str, delay: list[int] | None | bool = False) -> dict[str, Any]:
    """The stored keys as the editor reads them. `frequency` is the value a
    stored rule without the key runs on; `delay` (Purchased / welcome only) the
    range one without `delay_range` runs on — False leaves the key out."""
    media, price = media_and_price(steps)
    out: dict[str, Any] = {
        "media_ids": media,
        "price_cents": price,
        "frequency": steps.get("frequency") if steps.get("frequency") in FREQUENCIES else frequency,
        "starts_at": _stamp(steps.get("starts_at")),
        "ends_at": _stamp(steps.get("ends_at")),
        "unsend_minutes": unsend_minutes(steps),
    }
    if delay is not False:
        out["delay_range"] = delay_range(steps) if "delay_range" in steps else delay
    return out


def defaults(*, frequency: str, delay: list[int] | None | bool = False) -> dict[str, Any]:
    """A Trigger's settings before anything is saved: no media, free, Infloww's
    frequency (and delay) for it, effective immediately, never expiring, no
    Auto-unsend."""
    out: dict[str, Any] = {"media_ids": [], "price_cents": 0, "frequency": frequency,
                           "starts_at": None, "ends_at": None, "unsend_minutes": 0}
    if delay is not False:
        out["delay_range"] = delay
    return out


def store(steps: dict, merged: dict) -> None:
    """Write this module's keys from `merged` into the rule's steps."""
    for key in (*_ALL_KEYS, "delay_range"):
        if key in merged:
            steps[key] = merged[key]


def _stamp(raw: Any) -> str | None:
    ts = parse_iso(raw)
    return _iso(ts) if ts else None


# ── The senders ───────────────────────────────────────────────────────

def media_and_price(steps: dict) -> tuple[list[int], int]:
    """(vault media ids, price in cents) to send; free when there is no media."""
    raw = steps.get("media_ids")
    media = [int(i) for i in raw if _int(i) and i > 0][:MEDIA_MAX] if isinstance(raw, list) else []
    media = list(dict.fromkeys(media))
    p = steps.get("price_cents")
    price = min(p, PRICE_MAX_CENTS) if _int(p) and p >= PRICE_MIN_CENTS and media else 0
    return media, price


async def owners(account_id: str, media: list[int], price_cents: int,
                 fan_ids) -> set[int]:
    """Fans among `fan_ids` who already own any of a PAID message's media
    (ownership.owners_of_media, the guard ppv_send runs before every PPV): they
    get the text alone, free. Nothing to ask for a free message."""
    fans = {int(f) for f in fan_ids}
    if not price_cents or not media or not fans:
        return set()
    import ownership
    return set(await ownership.owners_of_media(str(account_id), list(media))) & fans


def frequency(steps: dict, default: str = "every") -> str:
    f = steps.get("frequency")
    return f if f in FREQUENCIES else default


def window_skip(steps: dict, now: datetime) -> str | None:
    """Why a sweep sends nothing now: "scheduled" before its Effective date,
    "expired" from its Expiry on; None inside the window."""
    start, end = parse_iso(steps.get("starts_at")), parse_iso(steps.get("ends_at"))
    if start is not None and now < start:
        return "scheduled"
    if end is not None and now >= end:
        return "expired"
    return None


def window_start(steps: dict) -> datetime | None:
    """The Effective date, when one is set: nothing earlier is chased."""
    return parse_iso(steps.get("starts_at"))


def delay_range(steps: dict) -> list[int] | None:
    """[a, b] minutes, or None for "immediately" (also for an unreadable value)."""
    r = steps.get("delay_range")
    if isinstance(r, list) and len(r) == 2 and all(_int(x) for x in r):
        return clamp_delay(*r)
    return None


def delay_seconds(rng: list[int] | None, *seed: Any) -> int:
    """This one event's delay inside `rng`, in seconds, drawn from `seed` (the
    account, the fan and the event) so every sweep that sees the event draws the
    same one."""
    if not rng:
        return 0
    a, b = rng[0] * 60, rng[1] * 60
    h = int.from_bytes(hashlib.sha256(":".join(map(str, seed)).encode()).digest()[:8], "big")
    return a + h % (b - a + 1)


def unsend_minutes(steps: dict) -> int:
    m = steps.get("unsend_minutes")
    return max(0, min(m, UNSEND_MAX_MINUTES)) if _int(m) else 0


async def schedule_unsend(account_id: str, fan_id: int, message_id: int, *,
                          minutes: int, price_cents: int) -> int | None:
    """Queue Auto-unsend for one landed message (an `unsend_messages` job, the
    per-chat unsend), or nothing when it is off or the message is paid. A
    follow-on of the current rule's run (`enqueue_followup`): it carries the
    rule, so switching the rule off cancels it. Never raises: the message is
    already on the wire, and a failed queue must not cost the sender its claim
    or its rest — it is logged and the message simply stays."""
    if minutes <= 0 or price_cents > 0:
        return None
    try:
        import automation_executor as ax
        return await ax.enqueue_followup(
            str(account_id), "unsend_messages",
            payload={"targets": [{"message_id": int(message_id), "fan_id": int(fan_id)}]},
            run_at=datetime.utcnow() + timedelta(minutes=minutes))
    except Exception:  # noqa: BLE001
        log.warning("auto-unsend not queued account=%s fan=%s msg=%s",
                    account_id, fan_id, message_id, exc_info=True)
        return None
