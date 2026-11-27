# No-id send contract: a 200 without `id` counts as SENT; advance durable state so the next tick never re-messages the fan.
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import NamedTuple

import dm_rate
from send_ops import RECONCILED, Reconciled, is_reconciled
from db.engine import get_session
from db.models import Fan, SkipList, VaultItem
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert


log = logging.getLogger("of-relay.automation.common")


_UNREACHABLE_MARKERS = ("Cannot send message to this user", "User not found")


def is_unreachable_fan_error(exc: BaseException) -> bool:
    s = str(exc)
    return any(m in s for m in _UNREACHABLE_MARKERS)


async def skip_unreachable_fan(account_id, fan_id, exc, *, log=log) -> bool:
    if not is_unreachable_fan_error(exc):
        return False
    await _skip_and_rest(account_id, fan_id, datetime.utcnow())
    log.info("skip_listed unreachable fan account=%s fan=%s (%s)",
             account_id, fan_id, str(exc).splitlines()[0][:80])
    return True


# A validation reject means OF created nothing, which is what makes a text-only retry safe instead of a double-message.
_MEDIA_REJECT_STATUSES = (400, 422)


# Fails closed: a false positive re-sends the same message twice.
def is_media_rejected_error(exc: BaseException) -> bool:
    resp = getattr(exc, "response", None)
    if getattr(resp, "status_code", None) not in _MEDIA_REJECT_STATUSES:
        return False
    try:
        body = resp.json()
    except Exception:
        return False
    errors = body.get("errors") if isinstance(body, dict) else None
    return isinstance(errors, dict) and "mediaFiles" in errors


_RECHECK_CAP = 10
_RECHECK_TTL_S = 3600.0
_RECHECKED: dict[tuple[str, int], float] = {}
# hold references: a bare task can be GC'd mid-run
_RECHECK_TASKS: set[asyncio.Task] = set()


def _recheck_ids(media_ids) -> list[int]:
    ids: list[int] = []
    for m in media_ids or ():
        try:
            mid = int(m)
        except (TypeError, ValueError):
            log.warning("media_reject_recheck bad id=%r", m)
            continue
        if mid not in ids:
            ids.append(mid)
    return ids


async def recheck_rejected_media(account_id, client, media_ids, *, log=log) -> list[int]:
    asked: list[int] = []
    gone: list[int] = []
    if account_id is None:
        return gone
    aid = str(account_id)
    try:
        import vault_cache
        import vault_stills
        ids = _recheck_ids(media_ids)
        if not ids:
            return gone
        async with get_session() as s:
            live = set((await s.execute(select(VaultItem.media_id).where(
                VaultItem.account_id == aid, VaultItem.media_id.in_(ids),
                VaultItem.removed_at.is_(None)))).scalars())
        # no await between the memo read and its write, so concurrent re-checks of one reject cannot both pass
        now = time.monotonic()
        if len(_RECHECKED) > 1000:
            for k in [k for k, t in _RECHECKED.items() if now - t >= _RECHECK_TTL_S]:
                del _RECHECKED[k]
        due = [m for m in ids if m in live
               and ((aid, m) not in _RECHECKED or now - _RECHECKED[(aid, m)] >= _RECHECK_TTL_S)]
        asked, rest = due[:_RECHECK_CAP], due[_RECHECK_CAP:]
        for mid in asked:
            _RECHECKED[(aid, mid)] = now
        if rest:
            log.warning("media_reject_recheck capped account=%s unchecked=%s", aid, rest)
        for mid in asked:
            try:
                fresh = await vault_stills.resolve_fresh(aid, mid, client)
            except Exception:  # noqa: BLE001
                log.warning("media_reject_recheck failed account=%s media=%s",
                            aid, mid, exc_info=True)
                continue
            if fresh.reason == "gone":
                gone.append(mid)
        if gone:
            await vault_cache.invalidate(aid)
    except Exception:  # noqa: BLE001
        log.warning("media_reject_recheck failed account=%s", aid, exc_info=True)
    log.info("media_reject_recheck account=%s asked=%s gone=%s", aid, asked, gone)
    return gone


def _recheck_done(task: asyncio.Task) -> None:
    _RECHECK_TASKS.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.warning("media_reject_recheck task failed", exc_info=exc)


def schedule_recheck_rejected_media(account_id, client, media_ids, *, log=log) -> asyncio.Task:
    task = asyncio.get_running_loop().create_task(
        recheck_rejected_media(account_id, client, list(media_ids or ()), log=log),
        name=f"media-reject-recheck:{account_id}")
    _RECHECK_TASKS.add(task)
    task.add_done_callback(_recheck_done)
    return task


class SendOutcome(NamedTuple):

    result: dict | Reconciled | None
    media_landed: bool


def revive_outcome(saved) -> SendOutcome:
    if is_reconciled(saved):
        return SendOutcome(RECONCILED, False)
    return SendOutcome(*(saved or (None, False)))


def _price_kw(media: list, price_cents: int) -> dict:
    return {"price": price_cents / 100} if media and price_cents > 0 else {}


async def send_dropping_bad_media(
    client, fan_id, text: str, media_files: list, *, log=log,
    send_purpose: str | None = None, price_cents: int = 0,
) -> SendOutcome:
    """`client.send_message`, except a refused ATTACHMENT degrades to text-only
    instead of losing the message entirely.

    `send_purpose` is the audience-coverage transport assert (gated / fenced /
    manual / not_fan_dm / exempt:<reason>): untagged raises under the test
    harness and logs loudly in prod — see audience_include.audit_send_purpose.

    Why this is not merely nice-to-have: a sender only advances its durable state
    on a RETURNED send, so a single permanently-bad vault id re-fires the same
    undeliverable message every tick, forever, burning an LLM call each time.
    Account 800000038 sat at 39-eligible / 0-sent for days on one bad night-slot
    image, and the run stats showed only "errors: 6" — nothing named the cause.
    The text is the point of these messages; the picture is a garnish, so ship
    the text.

    Re-raises unchanged when the failure is NOT about media — those belong to the
    caller's own skip/quarantine handling. `price_cents` > 0 sends the media
    locked at that price (a PPV); the text-only resend is free. After the
    resend the refused ids are re-checked off the send path
    (`schedule_recheck_rejected_media`)."""
    import audience_include as _audiences
    _audiences.audit_send_purpose(send_purpose, where="send_dropping_bad_media")

    async def _post(media: list):
        await dm_rate.turn(getattr(client, "account_id", None))
        return await asyncio.to_thread(
            lambda: client.send_message(fan_id, text, media_files=media,
                                        **_price_kw(media, price_cents))
        )

    try:
        result = await _post(media_files)
    except Exception as exc:
        if not (media_files and is_media_rejected_error(exc)):
            raise
        rejected = exc
    else:
        return SendOutcome(result, media_landed=bool(media_files))
    log.warning(
        "of_media_rejected fan=%s media=%s — resending text-only (%s)",
        fan_id, list(media_files), str(rejected).splitlines()[0][:120],
    )
    outcome = SendOutcome(await _post([]), media_landed=False)
    schedule_recheck_rejected_media(getattr(client, "account_id", None), client, media_files, log=log)
    return outcome


def send_dropping_bad_media_sync(client, fan_id, text: str, media_files: list, *,
                                 price_cents: int = 0, log=log) -> SendOutcome:
    try:
        result = client.send_message(fan_id, text, media_files=media_files,
                                     **_price_kw(media_files, price_cents))
    except Exception as exc:
        if not (media_files and is_media_rejected_error(exc)):
            raise
        log.warning("of_media_rejected fan=%s media=%s — resending text-only (%s)",
                    fan_id, list(media_files), (str(exc).splitlines() or [""])[0][:120])
        return SendOutcome(client.send_message(fan_id, text, media_files=[]),
                           media_landed=False)
    return SendOutcome(result, media_landed=bool(media_files))


# Lapsed subs may re-subscribe, so rest a week instead of skip-listing (deleted accounts are skip-listed).
_UNDELIVERABLE_RETRY = timedelta(days=7)


async def quarantine_if_undeliverable(client, account_id, fan_id, *, log=log) -> str | None:
    now = datetime.utcnow()
    try:
        info = await asyncio.to_thread(client.get_user, fan_id)
    except Exception as exc:
        if is_unreachable_fan_error(exc):
            await _skip_and_rest(account_id, fan_id, now)
            log.info("quarantine fan account=%s fan=%s — deleted/not-found", account_id, fan_id)
            return "deleted"
        log.debug("undeliverable probe failed account=%s fan=%s — keeping short pause",
                  account_id, fan_id, exc_info=True)
        return None
    if not (isinstance(info, dict) and info.get("subscribedOn")):
        await _set_status_and_pause(account_id, fan_id, "expired",
                                    now + _UNDELIVERABLE_RETRY)
        log.info("quarantine fan account=%s fan=%s — sub lapsed, paused 7d", account_id, fan_id)
        return "expired"
    return None


# An existing row is upgraded to unreachable: a prior "info"/"too_long" reason would mask the terminal one.
async def _skip_and_rest(account_id, fan_id, now) -> None:
    async with get_session() as s:
        await s.execute(
            sqlite_insert(SkipList)
            .values(account_id=str(account_id), fan_id=int(fan_id),
                    reason="unreachable", added_at=now)
            .on_conflict_do_update(
                index_elements=["account_id", "fan_id"],
                set_={"reason": "unreachable", "added_at": now},
            )
        )
        await s.execute(
            sqlite_insert(Fan)
            .values(account_id=str(account_id), fan_id=int(fan_id),
                    automation_paused_until=now + _UNDELIVERABLE_RETRY)
            .on_conflict_do_update(
                index_elements=["account_id", "fan_id"],
                set_={"automation_paused_until": now + _UNDELIVERABLE_RETRY,
                      "updated_at": now},
            )
        )


async def _set_status_and_pause(account_id, fan_id, status, until) -> None:
    async with get_session() as s:
        await s.execute(
            sqlite_insert(Fan)
            .values(account_id=str(account_id), fan_id=int(fan_id),
                    subscription_status=status, automation_paused_until=until)
            .on_conflict_do_update(
                index_elements=["account_id", "fan_id"],
                set_={"subscription_status": status, "automation_paused_until": until,
                      "updated_at": datetime.utcnow()},
            )
        )
