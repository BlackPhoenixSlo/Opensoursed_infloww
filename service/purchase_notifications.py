from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any, NamedTuple

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import account_health
import of_pacing
import ownership
import relay_cache
from db.engine import get_session
from db.models import Message, PurchaseNotice
from of_coerce import cents_or_zero
from purchase_poll_decide import Outcome

log = logging.getLogger("of-relay.purchase_notif")

_PAID_TYPES = {"paided_message"}
_PAID_SUBTYPES = {"subscriber_pay_for_chat_message"}

_POST_TYPES = {"paided_post"}
_POST_SUBTYPES = {"your_post_purchased"}

_MSG_LINK_RE = re.compile(r"/chats/chat/(\d+)\?firstId=(\d+)")
_POST_LINK_RE = re.compile(r"onlyfans\.com/(\d+)(?:/|$|[\"'?])")
_AMOUNT_RE = re.compile(r"([0-9]+(?:\.[0-9]{1,2})?)")


def _parse_amount_cents(raw: Any) -> int:
    m = _AMOUNT_RE.search(str(raw or ""))
    return cents_or_zero(m.group(1)) if m else 0


def parse_purchase(n: Any) -> dict[str, Any] | None:
    if not isinstance(n, dict):
        return None
    if str(n.get("type") or "") not in _PAID_TYPES:
        return None
    sub = str(n.get("subType") or "")
    # A missing subType passes (older payloads) but a known non-chat one has no message to flip.
    if sub and sub not in _PAID_SUBTYPES:
        return None
    pairs = n.get("replacePairs")
    link = ""
    if isinstance(pairs, dict):
        link = str(pairs.get("{MESSAGE_LINK}") or "")
    if not link:
        link = str(n.get("text") or "")
    m = _MSG_LINK_RE.search(link)
    if not m:
        return None
    fan_id, message_id = int(m.group(1)), int(m.group(2))
    if not fan_id:
        fan_id = int(((n.get("user") or {}) if isinstance(n.get("user"), dict) else {}).get("id") or 0)
    if not fan_id or not message_id:
        return None
    amount = _parse_amount_cents(
        (pairs or {}).get("{AMOUNT}") if isinstance(pairs, dict) else None)
    return {
        "notif_id": n.get("id"),
        "fan_id": fan_id,
        "message_id": message_id,
        "amount_cents": amount,
        "created_at": n.get("createdAt"),
        "name": (pairs or {}).get("{NAME}") if isinstance(pairs, dict) else None,
    }


def parse_post_purchase(n: Any) -> dict[str, Any] | None:
    if not isinstance(n, dict):
        return None
    if str(n.get("type") or "") not in _POST_TYPES:
        return None
    sub = str(n.get("subType") or "")
    if sub and sub not in _POST_SUBTYPES:
        return None
    pairs = n.get("replacePairs")
    link = ""
    if isinstance(pairs, dict):
        link = str(pairs.get("{POST_URL}") or "")
    if not link:
        link = str(n.get("text") or "")
    m = _POST_LINK_RE.search(link)
    if not m:
        return None
    post_id = int(m.group(1))
    user = n.get("user") if isinstance(n.get("user"), dict) else {}
    fan_id = int(user.get("id") or 0)
    if not fan_id or not post_id:
        return None
    amount = _parse_amount_cents(
        pairs.get("{PRICE}") if isinstance(pairs, dict) else None)
    return {
        "notif_id": n.get("id"),
        "fan_id": fan_id,
        "post_id": post_id,
        "amount_cents": amount,
        "created_at": n.get("createdAt"),
    }


def _notified_time(created_at: Any) -> datetime | None:
    raw = str(created_at or "").strip()
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00")) if raw else None
    except ValueError:
        return None
    if ts is None:
        return None
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    return min(ts, datetime.utcnow())


def _purchase_time(created_at: Any) -> datetime:
    return _notified_time(created_at) or datetime.utcnow()


async def _flip_paid(account_id: str, fan_id: int, message_id: int,
                     created_at: Any = None) -> bool:
    notified = _notified_time(created_at)
    async with get_session() as s:
        if notified is not None:
            await s.execute(
                sqlite_insert(PurchaseNotice)
                .values(account_id=str(account_id), fan_id=int(fan_id),
                        message_id=int(message_id), notified_at=notified)
                .on_conflict_do_nothing(index_elements=["account_id", "fan_id", "message_id"]))
        res = await s.execute(
            update(Message)
            .where(Message.account_id == str(account_id),
                   Message.fan_id == int(fan_id),
                   Message.message_id == int(message_id),
                   Message.direction == "out",
                   Message.price_cents > 0,
                   or_(Message.is_paid.is_(False), Message.is_paid.is_(None)))
            .values(is_paid=True, purchased_at=_purchase_time(created_at))
        )
        await s.commit()
    return bool(res.rowcount)


class _NotifKey(NamedTuple):
    kind: str
    account_id: str
    notif_id: Any


# The feed re-serves events every poll; a restart reprocesses each once (downstream is idempotent).
_DONE_NOTIFS: dict[_NotifKey, None] = {}


# Separate from _DONE_NOTIFS: only a ping that reached a live subscriber lands here, so an empty room re-offers the sale.
_ANNOUNCED_NOTIFS: dict[_NotifKey, None] = {}

_NOTIF_MEMO_MAX = 4096

_CATCHUP_UNFINISHED: set[str] = set()

# Bounds toast noise when a restart re-walks an already announced feed page.
_ANNOUNCE_MAX_AGE_S = 2 * 60 * 60


def _remember(memo: dict[_NotifKey, None], key: _NotifKey) -> None:
    while len(memo) >= _NOTIF_MEMO_MAX:
        memo.pop(next(iter(memo)))
    memo[key] = None


def _is_done(key: _NotifKey) -> bool:
    return key.notif_id is not None and key in _DONE_NOTIFS


def _is_fresh(created_at: Any) -> bool:
    raw = str(created_at or "").strip()
    if not raw:
        return True
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds() <= _ANNOUNCE_MAX_AGE_S


def _should_announce(key: _NotifKey, created_at: Any) -> bool:
    return (key.notif_id is not None
            and _is_fresh(created_at)
            and key not in _ANNOUNCED_NOTIFS)


async def _broadcast_purchase(account_id: str, p: dict[str, Any]) -> bool:
    # Unconditional, even with nobody watching: the WS carries no purchase frame, so this poll is the only money bust in prod.
    relay_cache.invalidate_money_feeds(str(account_id))
    try:
        from events import broadcast as _sse_broadcast
        reached = await _sse_broadcast({
            "purchase_notified": {
                "notif_id": str(p["notif_id"]),
                "fan_id": int(p["fan_id"]),
                "message_id": int(p["message_id"]),
                "amount_cents": int(p["amount_cents"] or 0),
                "created_at": p.get("created_at"),
                "name": (str(p["name"]) if p.get("name") else None),
            },
            "__account_id": str(account_id),
        })
    except Exception:  # noqa: BLE001
        log.debug("purchase_notified broadcast failed account=%s", account_id,
                  exc_info=True)
        return False
    return reached > 0


async def _announce_vault_history(account_id: str, fan_id: int) -> None:
    try:
        from events import broadcast as _sse_broadcast, js_safe_id
        await _sse_broadcast({
            "vault_history_changed": {"fan_id": js_safe_id(int(fan_id))},
            "__account_id": str(account_id),
        })
    except Exception:  # noqa: BLE001
        log.debug("vault_history_changed broadcast failed account=%s", account_id, exc_info=True)


async def _message_paid(account_id: str, fan_id: int, message_id: int) -> bool:
    async with get_session() as s:
        return bool((await s.execute(
            select(Message.is_paid).where(
                Message.account_id == str(account_id),
                Message.fan_id == int(fan_id),
                Message.message_id == int(message_id))
        )).scalar_one_or_none())


def classify(n: Any) -> str:
    if parse_purchase(n):
        return "chat_purchase"
    if parse_post_purchase(n):
        return "post_purchase"
    return "other"


async def _apply_chat(account_id: str, n: Any, out: dict[str, int],
                      *, announce: bool) -> bool:
    parsed = parse_purchase(n)
    assert parsed, "classify said chat_purchase"
    out["seen"] += 1
    key = _NotifKey("msg", str(account_id), parsed["notif_id"])
    # Announce sits above the _is_done gate: the ledger linker often flips first, which would retire the announcement unheard.
    if (announce and _should_announce(key, parsed["created_at"])
            and await _broadcast_purchase(account_id, parsed)):
        _remember(_ANNOUNCED_NOTIFS, key)
    if _is_done(key):
        out["known"] += 1
        return False
    flipped = await _flip_paid(
        account_id, parsed["fan_id"], parsed["message_id"], parsed["created_at"])
    if flipped:
        out["flipped"] += 1
        log.info(
            "purchase_notif_flip account=%s fan=%s msg=%s amount_cents=%s at=%s",
            account_id, parsed["fan_id"], parsed["message_id"],
            parsed["amount_cents"], parsed["created_at"])
    stamped = await ownership.try_stamp_message(
        account_id, parsed["fan_id"], parsed["message_id"],
        price_cents=parsed["amount_cents"], context="notif_chat")
    out["stamped"] += stamped
    if stamped:
        await _announce_vault_history(account_id, parsed["fan_id"])
    if key.notif_id is not None and (
        flipped or stamped
        or await _message_paid(account_id, parsed["fan_id"],
                               parsed["message_id"])
    ):
        _remember(_DONE_NOTIFS, key)
        return _is_fresh(parsed["created_at"])
    return False


async def _apply_post(account_id: str, client: Any, n: Any,
                      out: dict[str, int]) -> None:
    post = parse_post_purchase(n)
    assert post, "classify said post_purchase"
    out["posts"] += 1
    key = _NotifKey("post", str(account_id), post["notif_id"])
    if _is_done(key):
        out["known"] += 1
        return
    res = await ownership.try_stamp_post(
        account_id, post["fan_id"], post["post_id"],
        price_cents=post["amount_cents"], client=client,
        context="notif_post")
    out["stamped"] += res["stamped"]
    if res["stamped"]:
        await _announce_vault_history(account_id, post["fan_id"])
    if key.notif_id is not None and res["resolved"]:
        _remember(_DONE_NOTIFS, key)


async def _handle_items(account_id: str, client: Any, items: list,
                        *, announce: bool = False) -> dict[str, int]:
    out = {"seen": 0, "flipped": 0, "posts": 0, "stamped": 0, "known": 0}
    fresh_purchase = False
    for n in (items or []):
        kind = classify(n)
        if kind == "chat_purchase":
            if await _apply_chat(account_id, n, out, announce=announce):
                fresh_purchase = True
        elif kind == "post_purchase":
            await _apply_post(account_id, client, n, out)
    if fresh_purchase:
        # Lazy: the executor is heavy.
        from automation_executor import poke_rule
        poke_rule(account_id, "purchase_followup")
    return out


def _fetch_feed(client: Any, limit: int, offset: int) -> list:
    raw = client.get_json(
        f"/api2/v2/users/notifications?limit={int(limit)}"
        f"&offset={int(offset)}&type=purchases")
    items = raw.get("list") if isinstance(raw, dict) else raw
    return items if isinstance(items, list) else []


def feed_outcome(exc: BaseException) -> Outcome:
    reason = account_health.is_session_dead_error(exc)
    if reason:
        return Outcome("dead", reason=reason)
    status, body, header = of_pacing.upstream(exc)
    if status == 429:
        return Outcome("rate_limited", retry_after_s=of_pacing.asked_wait(header, of_pacing.allow_s(body)))
    if status == 401:
        return Outcome("unauthorized")
    return Outcome("error")


def _of_lane(account_id: str):
    for name in ("service.server", "server"):
        lane = getattr(sys.modules.get(name), "_priority_lane_background", None)
        if lane is not None:
            return lane(str(account_id))
    return contextlib.nullcontext()


def _fetch_feed_in_lane(account_id: str, client: Any, limit: int, offset: int) -> list:
    with _of_lane(account_id):
        return _fetch_feed(client, limit, offset)


async def poll_purchases(account_id: str, client: Any, *, limit: int = 10,
                         pages: int = 1) -> dict[str, Any]:
    totals = {"seen": 0, "flipped": 0, "posts": 0, "stamped": 0}
    catch_up = int(pages) > 1
    resume = catch_up and str(account_id) in _CATCHUP_UNFINISHED
    try:
        for page in range(max(1, int(pages))):
            items = await asyncio.to_thread(_fetch_feed_in_lane, account_id, client, limit, page * int(limit))
            got = await _handle_items(account_id, client, items, announce=True)
            known = got.pop("known")
            for k, v in got.items():
                totals[k] += v
            if (known and not resume) or len(items) < int(limit):
                break
        outcome = Outcome("ok")
        if catch_up:
            _CATCHUP_UNFINISHED.discard(str(account_id))
    except Exception as e:  # noqa: BLE001
        if catch_up:
            _CATCHUP_UNFINISHED.add(str(account_id))
        outcome = feed_outcome(e)
        log.debug("purchase_notif_poll_failed account=%s outcome=%s", account_id, outcome.kind, exc_info=True)
    return {**totals, "outcome": outcome}


async def backfill_purchases(
    account_id: str, client: Any, *, page_size: int = 50, max_pages: int = 20
) -> dict[str, int]:
    totals = {"seen": 0, "flipped": 0, "posts": 0, "stamped": 0, "pages": 0}
    seen_ids: set = set()
    for page in range(int(max_pages)):
        try:
            items = await asyncio.to_thread(
                _fetch_feed_in_lane, account_id, client, page_size, page * int(page_size))
        except Exception:  # noqa: BLE001
            log.warning("purchase_notif_backfill_fetch_failed account=%s page=%d",
                        account_id, page, exc_info=True)
            break
        fresh = [n for n in items
                 if isinstance(n, dict) and n.get("id") not in seen_ids]
        if not fresh:
            break
        seen_ids.update(n.get("id") for n in fresh)
        got = await _handle_items(account_id, client, fresh)
        got.pop("known")
        for k, v in got.items():
            totals[k] += v
        totals["pages"] += 1
        if len(items) < int(page_size):
            break
    log.info("purchase_notif_backfill account=%s %s", account_id, totals)
    return totals
