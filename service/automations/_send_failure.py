"""OF send-failure handling: unreachable fans, media rejects, quarantine.

THE NO-ID SEND CONTRACT (read before writing a sender):
    of_client.send_message returns OF's created message, normally with an `id`.
    A 200 response WITHOUT an `id` is anomalous but reachable. Treat it as SENT
    for idempotency: advance/guard your durable state (welcome_sent, followup_
    state, funnel current_step, or — for "fan spoke last" eligibility — a short
    `fans.automation_paused_until`) so the NEXT tick does NOT re-send to the same
    fan. The message row is simply unrecorded until scrape_chats backfills it.
    NEVER leave state such that the fan is re-messaged (that spams a real fan).
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import NamedTuple

import dm_rate
from db.engine import get_session
from db.models import Fan, SkipList, VaultItem
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert


log = logging.getLogger("of-relay.automation.common")


# ── unreachable-fan skip-listing ────────────────────────────────────────────
# OnlyFans permanently rejects sends to some fans — an expired/restricted sub
# ("Cannot send message to this user") or a deleted account ("User not found").
# Retrying every cycle is pointless and floods the logs (these are the bulk of
# the relay's "errors"), so the first time a send hits one we skip-list the fan;
# any sender that checks `skip_list` then leaves them alone.
_UNREACHABLE_MARKERS = ("Cannot send message to this user", "User not found")


def is_unreachable_fan_error(exc: BaseException) -> bool:
    """True when an OF send failed PERMANENTLY for this fan (can't-message /
    deleted), vs a transient error (proxy blip, rate limit, network)."""
    s = str(exc)
    return any(m in s for m in _UNREACHABLE_MARKERS)


async def skip_unreachable_fan(account_id, fan_id, exc, *, log=log) -> bool:
    """If `exc` is a permanent 'can't message this fan' error, quarantine the fan
    on BOTH gates senders honour — skip_list (reason 'unreachable') for the
    skip_list-aware senders AND automation_paused_until for the pause-only ones —
    so NOBODY burns another LLM call generating a reply we can never deliver.
    Returns True if it quarantined; False for transient errors (caller keeps its
    normal handling)."""
    if not is_unreachable_fan_error(exc):
        return False
    await _skip_and_rest(account_id, fan_id, datetime.utcnow())
    log.info("skip_listed unreachable fan account=%s fan=%s (%s)",
             account_id, fan_id, str(exc).splitlines()[0][:80])
    return True


# ── rejected ATTACHMENT (the message is fine, the picture is not) ───────────
# A vault id can go bad permanently — re-encoded, removed, DRM'd — and OF then
# refuses the whole send with a field-keyed validation error naming `mediaFiles`.
# Only these statuses may be treated that way: a validation reject means OF
# created NOTHING, which is the precondition that makes a retry safe instead of
# a double-message.
_MEDIA_REJECT_STATUSES = (400, 422)


def is_media_rejected_error(exc: BaseException) -> bool:
    """True when OF refused the ATTACHED MEDIA rather than the message or the fan.

    Read off the RESPONSE rather than sniffed out of the exception text. Matching
    a substring like "mediafiles" against `str(exc)` would also fire on an error
    that merely mentions the field, and the cost of a false positive here is not
    a wasted call — it is sending a real fan the SAME MESSAGE TWICE, because the
    caller retries on a True. So this asks the two questions that actually license
    a retry: did OF reject the request as invalid (so nothing was created), and
    did it name `mediaFiles` as the offending field?

    Fails CLOSED — no response, non-JSON body, or any doubt returns False and the
    caller's normal error handling runs. Nothing about the recipient is wrong
    here, so skip-list and undeliverable-quarantine must NOT claim this one."""
    resp = getattr(exc, "response", None)
    if getattr(resp, "status_code", None) not in _MEDIA_REJECT_STATUSES:
        return False
    try:
        body = resp.json()
    except Exception:
        return False
    errors = body.get("errors") if isinstance(body, dict) else None
    return isinstance(errors, dict) and "mediaFiles" in errors


# A refused vault id is usually one the creator DELETED on OF. The mirror only
# learns of a deletion through a by-id 404 (the collect walk never removes rows),
# so without a re-check every picker keeps choosing the dead id and every send
# re-hits the same reject. Bounded: one send's ids, at most this many GETs.
_RECHECK_CAP = 10
# A per-fan sender hits the same reject once per fan: an id this process already
# re-read (alive or fetch failed) within the TTL is not re-read. A gone id needs
# no memo: its `removed_at` keeps it out of the live-row SELECT.
_RECHECK_TTL_S = 3600.0
_RECHECKED: dict[tuple[str, int], float] = {}
# Detached re-checks: referenced until done (a bare task can be GC'd mid-run).
_RECHECK_TASKS: set[asyncio.Task] = set()


def _recheck_ids(media_ids) -> list[int]:
    """Each id as an int, in order, duplicates dropped; a bad id is skipped alone."""
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
    """After OF refused a send's ATTACHMENT: re-read each of `media_ids` by id
    (`vault_stills.resolve_fresh`, the render path's read, `mark_gone=True`). A
    404 stamps the mirror row `removed_at`, which every picker already skips; a
    live id gets its row refreshed; any other failure leaves the row alone.
    Only ids with a live mirror row are read, and none this process re-read
    within `_RECHECK_TTL_S`. Returns the ids found gone.

    Never raises: the caller's send outcome is already decided and this is
    mirror upkeep, so every failure is logged and swallowed. Senders call
    `schedule_recheck_rejected_media`, which runs this off the send path."""
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
        # No await between the memo read and its write: concurrent re-checks of
        # the same reject (one per fan) cannot both pass.
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
    """`recheck_rejected_media` as a detached task: the caller's send outcome
    and its bookkeeping (claims, recipient rows) never wait on, or get
    cancelled with, mirror upkeep. Returns the task (tests await it)."""
    task = asyncio.get_running_loop().create_task(
        recheck_rejected_media(account_id, client, list(media_ids or ()), log=log),
        name=f"media-reject-recheck:{account_id}")
    _RECHECK_TASKS.add(task)
    task.add_done_callback(_recheck_done)
    return task


class SendOutcome(NamedTuple):
    """What `send_dropping_bad_media` actually managed to deliver."""

    result: dict | None
    # True only when an attachment was asked for AND OF accepted it, so callers
    # can drive their image counter off this directly instead of second-guessing
    # the media list they passed in.
    media_landed: bool


def _price_kw(media: list, price_cents: int) -> dict:
    """`send_message`'s price for a send: a priced message locks its media at
    `price_cents`; with no media there is nothing to lock, so it goes out free.
    Absent when free, so a free send's call is the one it always was."""
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
        # The account's DM rate (OF_DM_PER_MIN, dm_rate): a plain wait, the
        # slot kept; a caller that already took this DM's turn (where it
        # handles SlotLost) passes at once.
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
    # Deliberately outside the handler: a failure of the RETRY should surface on
    # its own, not chained under "during handling of the above exception".
    log.warning(
        "of_media_rejected fan=%s media=%s — resending text-only (%s)",
        fan_id, list(media_files), str(rejected).splitlines()[0][:120],
    )
    outcome = SendOutcome(await _post([]), media_landed=False)
    schedule_recheck_rejected_media(getattr(client, "account_id", None), client, media_files, log=log)
    return outcome


def send_dropping_bad_media_sync(client, fan_id, text: str, media_files: list, *,
                                 price_cents: int = 0, log=log) -> SendOutcome:
    """`send_dropping_bad_media`, blocking: for a sender whose send is the `fn`
    of `of_write_paced` (run in a worker thread), which is where the audience
    assert already ran. Same rule: a refused ATTACHMENT resends the text alone,
    free; any other failure is re-raised for the caller (and the paced seam's
    rate-limit retry). The caller calls `schedule_recheck_rejected_media` itself
    when media was asked and did not land: this runs in a worker thread."""
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


# How long to rest a fan whose subscription has lapsed before re-checking. They
# can't be DM'd while expired, but they may re-subscribe — so retry in a WEEK
# rather than skip-listing forever. (Deleted accounts ARE skip-listed.)
_UNDELIVERABLE_RETRY = timedelta(days=7)


async def quarantine_if_undeliverable(client, account_id, fan_id, *, log=log) -> str | None:
    """A send to `fan_id` returned 200 WITHOUT a message id — OF silently dropped
    it (see THE NO-ID SEND CONTRACT). A single no-id is usually transient, but a
    fan where EVERY send is no-id is undeliverable: the sub lapsed, or the account
    is gone. Retrying that fan every tick is what burns the LLM (it generates a
    reply it can never deliver). So when we hit a no-id, probe OF to LEARN WHY and
    quarantine the fan so we stop calling the model for them:

      * account deleted / 'User not found'  → skip_list ('unreachable') + a pause.
        welcome_chatter_for_info/send_followup honour skip_list; the pause covers the
        pause-only senders (autoreply).
      * sub lapsed (`subscribedOn` falsy)    → record subscription_status='expired'
        + pause 1 WEEK (re-checks then, in case they re-subscribe).
      * still subscribed (a real transient)  → return None; the caller keeps its
        normal short no-id pause and retries next tick.

    Best-effort: if the probe itself fails we return None (the caller keeps the
    short pause) — we NEVER exile a fan on a failed probe. Returns the reason
    string when it quarantined, else None. `subscribedOn` is the same field the
    executor trusts to classify a fan vs a creator (automation_executor)."""
    now = datetime.utcnow()
    try:
        info = await asyncio.to_thread(client.get_user, fan_id)
    except Exception as exc:
        if is_unreachable_fan_error(exc):           # 'User not found' → deleted
            await _skip_and_rest(account_id, fan_id, now)
            log.info("quarantine fan account=%s fan=%s — deleted/not-found", account_id, fan_id)
            return "deleted"
        log.debug("undeliverable probe failed account=%s fan=%s — keeping short pause",
                  account_id, fan_id, exc_info=True)
        return None
    if not (isinstance(info, dict) and info.get("subscribedOn")):
        # Sub lapsed — can't DM. Record it and rest a week (re-checks then).
        await _set_status_and_pause(account_id, fan_id, "expired",
                                    now + _UNDELIVERABLE_RETRY)
        log.info("quarantine fan account=%s fan=%s — sub lapsed, paused 7d", account_id, fan_id)
        return "expired"
    return None  # subscribedOn truthy → genuinely transient; caller keeps short pause


async def _skip_and_rest(account_id, fan_id, now) -> None:
    """Skip-list AND pause-a-week a fan that's gone for good. Both gates so every
    sender (skip_list-aware OR pause-only) leaves the fan alone. An existing row
    is UPGRADED to 'unreachable' — a fan can already carry 'info' or 'too_long'
    (graduation reasons, which a sender may deliberately let through); keeping
    that reason would mask the terminal one."""
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
    """UPSERT subscription_status + automation_paused_until (candidates can come
    from the messages table with no Fan row yet — UPDATE would no-op)."""
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
