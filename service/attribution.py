from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Iterable

import re

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import relay_cache
import relay_hooks
# Re-exported: other modules import _norm_body and _seconds_apart from here.
from attribution_pair import (  # noqa: F401
    _DEFAULT_MANUAL_YIELD_S,
    _norm_body,
    _seconds_apart,
    adopt_windows,
    hard_yield,
    manual_yield_s,
    pair_placeholders,
)
from db.engine import get_session
from db.models import Chat, Message, Transaction

log = logging.getLogger("of-relay.attribution")


def _preview_text(body: str | None) -> str:
    if not body:
        return ""
    return re.sub(r"<[^>]+>", "", body).strip()[:120]


async def _advance_chat_preview(
    *,
    account_id: str,
    fan_id: int,
    message_id: int,
    body: str,
    created_at: datetime,
    conn=None,
) -> None:
    # OF-WS pump skips outbound; forward-only WHERE so a backfilled write cannot clobber a newer preview.
    preview = _preview_text(body)
    stmt = (
        sqlite_insert(Chat)
        .values(
            account_id=str(account_id),
            fan_id=int(fan_id),
            last_message_id=int(message_id),
            last_message_at=created_at,
            last_message_preview=preview,
            unread_count=0,
        )
        .on_conflict_do_update(
            index_elements=["account_id", "fan_id"],
            set_={
                "last_message_id": int(message_id),
                "last_message_at": created_at,
                "last_message_preview": preview,
                # Reply clears unread; the forward-only WHERE keeps the unread of a fan message that landed after our send.
                "unread_count": 0,
            },
            where=(
                (Chat.last_message_at.is_(None))
                | (Chat.last_message_at <= created_at)
            ),
        )
    )
    try:
        if conn is not None:
            await conn.execute(stmt)
        else:
            async with get_session() as s:
                await s.execute(stmt)
    except Exception:
        log.debug(
            "chat preview advance skipped (account=%s fan=%s msg=%s)",
            account_id, fan_id, message_id, exc_info=True,
        )


async def _manual_yield_seconds(account_id: str) -> int:
    try:
        from db.models import AccountAiConfig
        async with get_session() as s:
            cfg = await s.get(AccountAiConfig, str(account_id))
    except Exception:
        log.debug("manual_yield_seconds read failed", exc_info=True)
        return _DEFAULT_MANUAL_YIELD_S
    return manual_yield_s(cfg.webhook_config_json if cfg else None)


# Above real OF message_ids (sorts newest) and below JS 2**53 so ids round-trip the frontend as distinct React keys.
_MASS_PLACEHOLDER_BASE = 5_000_000_000_000_000
# Exclusive: transaction_ingest._TIP_MSG_ID_BASE (6e15) holds PERMANENT tip history, and adopt_thread_placeholders DELETES by range.
_MASS_PLACEHOLDER_CEIL = 6_000_000_000_000_000
# Generous for a stalled ingest, but refuses a stub with no real row adopting a same-caption send weeks later.
_MAX_ADOPT_SECONDS = 6 * 3600.0

# Shared by the chat engines' pre-pass and messages.mark_queue_copies_unsent so both retire the same rows.
# 30 min not 30 s: OF stamps delivery itself and a 745-recipient queue is not instantaneous.
_BLAST_COPY_SLACK = timedelta(minutes=30)


def _slug_sender(display_name: str) -> str:
    return re.sub(r"\s+", "", (display_name or "").strip().lower())


async def mass_sender_tag(sent_by_employee_id: int | None) -> str:
    if sent_by_employee_id is None:
        return ""
    try:
        from employees import get_automation_employee_id
        auto_id = await get_automation_employee_id()
    except Exception:
        auto_id = None
    return await _mass_sender_tag(sent_by_employee_id, auto_id)


async def _mass_sender_tag(sent_by_employee_id: int | None, auto_id: int | None) -> str:
    if sent_by_employee_id is None:
        return ""
    try:
        if auto_id is not None and int(sent_by_employee_id) == int(auto_id):
            return ""
        from db.models import Employee
        async with get_session() as s:
            emp = await s.get(Employee, int(sent_by_employee_id))
        slug = _slug_sender(emp.display_name) if emp is not None else ""
        return f"mass-{slug}" if slug else ""
    except Exception:
        log.debug("mass_sender_tag resolve failed (emp=%s)",
                  sent_by_employee_id, exc_info=True)
        return ""


def mass_placeholder_message_id(mass_run_id: int) -> int:
    return _MASS_PLACEHOLDER_BASE + int(mass_run_id)


async def _backfill_attribution(
    *,
    account_id: str,
    fan_id: int,
    message_id: int,
    sent_by_employee_id: int | None,
    automation_kind: str | None,
    mass_run_id: int | None,
    funnel_step: str | None,
) -> None:
    # NULL automation_kind reads as a HUMAN send and resume_after_manual_hours then mutes the bot on that fan; the WS pump inserts first with NULL.
    # coalesce keeps the first writer's value; body/media/raw_json stay untouched (the pump has the real OF payload).
    ours = {"sent_by_employee_id": sent_by_employee_id,
            "automation_kind": automation_kind,
            "mass_run_id": mass_run_id,
            "funnel_step": funnel_step}
    have = {k: v for k, v in ours.items() if v is not None}
    if not have:
        return
    try:
        async with get_session() as s:
            await s.execute(
                update(Message)
                .where(Message.account_id == str(account_id),
                       Message.fan_id == int(fan_id),
                       Message.message_id == int(message_id))
                .values(**{k: func.coalesce(getattr(Message, k), v)
                           for k, v in have.items()})
            )
        log.info("attribution backfilled onto an existing row: account=%s fan=%s "
                 "msg=%s kind=%s", account_id, fan_id, message_id, automation_kind)
    except Exception:
        log.warning("attribution backfill failed account=%s fan=%s msg=%s",
                    account_id, fan_id, message_id, exc_info=True)


async def write_outbound_attribution(
    *,
    account_id: str,
    fan_id: int,
    message_id: int,
    sent_by_employee_id: int | None,
    body: str,
    price_cents: int,
    created_at: datetime,
    mass_run_id: int | None = None,
    funnel_step: int | None = None,
    automation_kind: str | None = None,
    emit_live: bool = False,
) -> None:
    hook_at = created_at
    try:
        try:
            relay_cache.invalidate("get_chat", str(account_id), match=lambda ex, c=int(fan_id): ex == (c,))
        except Exception:  # noqa: BLE001
            log.debug("get_chat invalidation skipped", exc_info=True)
        auto_id: int | None = None
        # Chatter session present but resolver failed: leave NULL, not Automation, or the sentinel is falsely credited for a chatter's send.
        if sent_by_employee_id is None:
            try:
                from chatters import get_request_chatter
                chatter = get_request_chatter()
            except Exception:
                chatter = None
            if chatter is not None:
                log.warning(
                    "outbound message %s left sent_by_employee_id=NULL — "
                    "chatter resolver returned None for chatter=%s account=%s. "
                    "Inspect logs for 'chatter→employee resolution failed'.",
                    message_id, chatter.id, account_id,
                )
            else:
                try:
                    from employees import get_automation_employee_id
                    sent_by_employee_id = auto_id = await get_automation_employee_id()
                except LookupError:
                    log.warning(
                        "Automation employee not found (migration 0011 not run?); "
                        "writing message %s with sent_by_employee_id=NULL",
                        message_id,
                    )
                except Exception:
                    log.warning(
                        "Automation employee lookup raised; writing message %s "
                        "with sent_by_employee_id=NULL",
                        message_id,
                        exc_info=True,
                    )

        # Reads only, BEFORE the write, so row, preview and cooldown are one short write txn; late imports avoid the attribution<->executor cycle.
        if sent_by_employee_id is not None and auto_id is None:
            try:
                from employees import get_automation_employee_id
                auto_id = await get_automation_employee_id()
            except Exception:
                if mass_run_id is None:
                    log.debug("w7 hard-yield cooldown skipped", exc_info=True)
        if mass_run_id is not None:
            mass_tag = await _mass_sender_tag(sent_by_employee_id, auto_id)
        else:
            mass_tag = ""
        yield_s = (await _manual_yield_seconds(str(account_id))
                   if hard_yield(mass_run_id=mass_run_id, sent_by=sent_by_employee_id,
                                 automation_id=auto_id) else 0)
        # Ours, not OF's: its own immediate transaction, not the OF-cache writer's batch.
        from db import of_writer
        async with of_writer.immediate() as conn:
            stmt = sqlite_insert(Message).values(
                account_id=str(account_id),
                fan_id=int(fan_id),
                message_id=int(message_id),
                direction="out",
                sender_name=mass_tag,
                body=body,
                media_ids="[]",
                media_count=0,
                price_cents=int(price_cents),
                is_paid=False if (price_cents or 0) > 0 else None,
                is_tip=False,
                sent_by_employee_id=sent_by_employee_id,
                mass_run_id=mass_run_id,
                funnel_step=funnel_step,
                automation_kind=automation_kind,
                raw_json=None,
                created_at=created_at,
                ingested_at=datetime.utcnow(),
            ).on_conflict_do_nothing(
                index_elements=["account_id", "fan_id", "message_id"],
            )
            res = await conn.execute(stmt)
            if (res.rowcount or 0) > 0:
                # Only on a real insert, so a duplicate re-run cannot re-bump the chat.
                await _advance_chat_preview(
                    account_id=str(account_id), fan_id=int(fan_id),
                    message_id=int(message_id), body=body, created_at=created_at,
                    conn=conn,
                )
            else:
                hook_at = (await conn.execute(select(Message.created_at).where(
                    Message.account_id == str(account_id), Message.fan_id == int(fan_id),
                    Message.message_id == int(message_id),
                ))).scalar_one_or_none() or created_at
            # Not gated on a new row: an echo or a scrape may have inserted it.
            if yield_s > 0:
                try:
                    from automation_executor import start_fan_cooldown
                    await start_fan_cooldown(str(account_id), int(fan_id),
                                             cooldown_s=yield_s, conn=conn)
                except Exception:
                    log.debug("w7 hard-yield cooldown skipped", exc_info=True)
        if (res.rowcount or 0) == 0:
            # Somebody inserted this row first: tag it anyway, losing the tag MUTES the engine on that fan.
            await _backfill_attribution(
                account_id=str(account_id), fan_id=int(fan_id),
                message_id=int(message_id),
                sent_by_employee_id=sent_by_employee_id,
                automation_kind=automation_kind,
                mass_run_id=mass_run_id, funnel_step=funnel_step,
            )
        log.info(
            "attribution: account=%s fan=%s msg=%s emp=%s mass_run=%s",
            account_id, fan_id, message_id, sent_by_employee_id, mass_run_id,
        )
        # Only on a real insert: re-broadcasting a duplicate would re-bump an already-shown chat.
        if emit_live and (res.rowcount or 0) > 0:
            from events import publish_db_message  # local import avoids a cycle
            await publish_db_message(
                account_id=str(account_id), fan_id=int(fan_id),
                message_id=int(message_id), body=body, created_at=created_at,
                price_cents=int(price_cents),
            )

    except Exception:
        log.exception(
            "attribution write failed (account=%s fan=%s msg=%s)",
            account_id, fan_id, message_id,
        )
    finally:
        import sends_inflight
        sends_inflight.end(account_id, fan_id, message_id)
        relay_hooks.fire_outbound_sent(account_id, fan_id, message_id, hook_at)


async def write_mass_optimistic_rows(
    *,
    account_id: str,
    fan_ids: Iterable[int],
    mass_run_id: int,
    sent_by_employee_id: int | None,
    body: str,
    price_cents: int,
    created_at: datetime,
    automation_kind: str | None = None,
    emit_live: bool = False,
) -> int:
    # Explicit userIds only: expanding list audiences is ~250k synthetic rows a month; those rows arrive from OF via the scrape.
    placeholder_id = mass_placeholder_message_id(mass_run_id)
    is_paid = False if (price_cents or 0) > 0 else None
    sender_tag = await mass_sender_tag(sent_by_employee_id)

    seen: set[int] = set()
    rows: list[dict] = []
    for raw in fan_ids:
        try:
            fid = int(raw)
        except (TypeError, ValueError):
            continue
        if fid in seen:
            continue
        seen.add(fid)
        rows.append({
            "account_id": str(account_id),
            "fan_id": fid,
            "message_id": placeholder_id,
            "direction": "out",
            "sender_name": sender_tag,
            "body": body,
            "media_ids": "[]",
            "media_count": 0,
            "price_cents": int(price_cents),
            "is_paid": is_paid,
            "is_tip": False,
            "sent_by_employee_id": sent_by_employee_id,
            "temp_id": f"mass:{int(mass_run_id)}:{fid}",
            "mass_run_id": int(mass_run_id),
            "automation_kind": automation_kind,
            "raw_json": None,
            "created_at": created_at,
            "ingested_at": datetime.utcnow(),
        })

    if not rows:
        return 0

    try:
        async with get_session() as s:
            stmt = sqlite_insert(Message).values(rows).on_conflict_do_nothing(
                index_elements=["account_id", "fan_id", "message_id"],
            )
            await s.execute(stmt)
        for r in rows:
            await _advance_chat_preview(
                account_id=str(account_id), fan_id=int(r["fan_id"]),
                message_id=int(r["message_id"]), body=body, created_at=created_at,
            )
        log.info(
            "mass optimistic: account=%s run=%s rows=%d emp=%s",
            account_id, mass_run_id, len(rows), sent_by_employee_id,
        )
        if emit_live:
            from events import publish_db_message  # local import avoids a cycle
            for r in rows:
                await publish_db_message(
                    account_id=str(account_id), fan_id=int(r["fan_id"]),
                    message_id=int(r["message_id"]), body=body,
                    created_at=created_at, price_cents=int(price_cents),
                )
    except Exception:
        log.exception(
            "mass optimistic write failed (account=%s run=%s)",
            account_id, mass_run_id,
        )
    return len(rows)


async def adopt_thread_placeholders(s, *, account_id: str, fan_id: int) -> int:
    try:
        # Per thread, not per message: only ~9% of placeholders ever get a real twin, so one range-seek per thread beats a lookup per row.
        placeholders = (await s.execute(
            select(Message).where(
                Message.account_id == str(account_id),
                Message.fan_id == int(fan_id),
                Message.message_id >= _MASS_PLACEHOLDER_BASE,
                Message.message_id < _MASS_PLACEHOLDER_CEIL,
            )
        )).scalars().all()
        if not placeholders:
            return 0

        # Keyed only (media-only stubs never pair); normalize linearly, O(P + R) not O(P x R), on the inbox render path.
        keyed = [p for p in placeholders if _norm_body(p.body)]
        if not keyed:
            return 0

        # Per-stub ranges, not one min..max span; keyed only: this runs on every inbox poll.
        ranges = adopt_windows([p.created_at for p in keyed if p.created_at is not None],
                               timedelta(seconds=_MAX_ADOPT_SECONDS))
        if not ranges:
            return 0
        reals = (await s.execute(
            select(Message).where(
                Message.account_id == str(account_id),
                Message.fan_id == int(fan_id),
                Message.message_id < _MASS_PLACEHOLDER_BASE,
                Message.direction == "out",
                or_(*[and_(Message.created_at >= lo, Message.created_at <= hi)
                      for lo, hi in ranges]),
            )
        )).scalars().all()

        adopted = 0
        # Move the ledger reference BEFORE the delete or refuse the pair; a refusal leaves the harmless duplicate.
        for ph, real in pair_placeholders(keyed, reals, _MAX_ADOPT_SECONDS):
            if not await _repoint_transaction(
                s, account_id=account_id, fan_id=fan_id,
                old_id=int(ph.message_id), new_id=int(real.message_id),
            ):
                continue
            real.automation_kind = real.automation_kind or ph.automation_kind
            real.mass_run_id = real.mass_run_id or ph.mass_run_id
            real.sent_by_employee_id = (real.sent_by_employee_id
                                        or ph.sent_by_employee_id)
            # OF omits the price on some scraped PPV rows; that zero would erase the sale's value.
            if not (real.price_cents or 0) and (ph.price_cents or 0):
                real.price_cents = int(ph.price_cents)
            # One-way: OF's True is truth, a stub that saw the unlock may only promote.
            if ph.is_paid and not real.is_paid:
                real.is_paid = True
            if real.purchased_at is None and ph.purchased_at is not None:
                real.purchased_at = ph.purchased_at
            # One-way: an unsend that hit the stub before pairing must survive the delete.
            if ph.is_unsent and not real.is_unsent:
                real.is_unsent = True
                real.unsent_at = real.unsent_at or ph.unsent_at
                real.unsent_reason = real.unsent_reason or ph.unsent_reason
                real.unsent_by_employee_id = (real.unsent_by_employee_id
                                              or ph.unsent_by_employee_id)
            # chats.last_message_id points at the stub: real OF ids (~1e13) never exceed 5e15, so the chat would freeze forever.
            await s.execute(
                update(Chat)
                .where(
                    Chat.account_id == str(account_id),
                    Chat.fan_id == int(fan_id),
                    Chat.last_message_id == int(ph.message_id),
                )
                .values(
                    last_message_id=int(real.message_id),
                    last_message_at=real.created_at,
                    last_message_preview=_preview_text(real.body),
                )
            )
            await s.delete(ph)
            adopted += 1
        return adopted
    except Exception:
        log.exception("placeholder adopt failed (account=%s fan=%s)",
                      account_id, fan_id)
        return 0


_LOGGED_TX_COLLISIONS: set[tuple[str, int, int]] = set()
_LOGGED_TX_COLLISIONS_MAX = 512


async def _repoint_transaction(
    s, *, account_id: str, fan_id: int, old_id: int, new_id: int,
) -> bool:
    # A purchase can link straight to a synthetic id (the PPV candidate query does not exclude the band); deleting it would orphan those dollars.
    # uq_tx_msg collision means the purchase was recorded twice: refuse, keeping the duplicate message is the cheaper wrong.
    rows = (await s.execute(
        select(Transaction).where(
            Transaction.account_id == str(account_id),
            Transaction.fan_id == int(fan_id),
            Transaction.message_id == int(old_id),
        )
    )).scalars().all()
    if not rows:
        return True
    taken = (await s.execute(
        select(Transaction.id).where(
            Transaction.account_id == str(account_id),
            Transaction.fan_id == int(fan_id),
            Transaction.message_id == int(new_id),
        ).limit(1)
    )).scalar_one_or_none()
    if taken is not None or len(rows) > 1:
        # Once per pair per process: a refused pair is retried on every ingest and never resolves itself.
        seen = (str(account_id), int(old_id), int(new_id))
        if seen not in _LOGGED_TX_COLLISIONS:
            if len(_LOGGED_TX_COLLISIONS) >= _LOGGED_TX_COLLISIONS_MAX:
                _LOGGED_TX_COLLISIONS.clear()
            _LOGGED_TX_COLLISIONS.add(seen)
            log.warning(
                "placeholder adopt refused — ledger collision (account=%s fan=%s "
                "stub=%s real=%s stub_rows=%d real_taken=%s)",
                account_id, fan_id, old_id, new_id, len(rows), taken,
            )
        return False
    rows[0].message_id = int(new_id)
    return True


async def reconcile_mass_placeholder(
    *,
    account_id: str,
    fan_id: int,
    mass_run_id: int,
) -> None:
    try:
        async with get_session() as s:
            await s.execute(
                delete(Message).where(
                    Message.account_id == str(account_id),
                    Message.fan_id == int(fan_id),
                    Message.message_id == mass_placeholder_message_id(mass_run_id),
                )
            )
    except Exception:
        log.exception(
            "mass placeholder reconcile failed (account=%s fan=%s run=%s)",
            account_id, fan_id, mass_run_id,
        )
