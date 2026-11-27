from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace
from datetime import datetime

from sqlalchemy import select

from attribution import (
    reconcile_mass_placeholder,
    write_mass_optimistic_rows,
    write_outbound_attribution,
)
import automation_executor as ax
from automation_registry import register
from automations import send_mass_decide as smd
from automations._pools import int_list
from of_client import proxy_refused
from of_write import _may_have_sent
import platforms
import send_ops
from job_queue import send_anchor
from send_tripwire import CellHeld
from side_effect_gate import PLATFORM_LACKS_PREFIX
from automations._wordfilter import (
    banned_hit_summary, filter_banned, load_banned_words,
)
from db.engine import get_session
from db.models import (MASS_RUN_FAILED, MASS_RUN_OK, MASS_RUN_REFUSED, MASS_RUN_RUNNING,
                       FunnelAccountMedia, ListMember, MassMessageFunnel, MassRun, ScheduledJob)
from event_transcoder import _parse_iso, _to_cents

_OP_KIND = {"mass_premade": "mass_premade"}


def _op_kind_anchor(attr_kind: str, attr_ref, payload: dict) -> tuple[str, str]:
    kind = _OP_KIND.get(attr_kind, "mass_job")
    return kind, send_anchor(payload)


log = logging.getLogger("of-relay.automation.send_mass_message")
RUN_REFUSED = "refused"   # a mass_runs status: the proxy refused its POST


async def _opener_media(funnel_id: int, account_id: str, s=None) -> tuple[list[int], list[int]]:
    if s is None:
        async with get_session() as s:
            return await _opener_media(funnel_id, account_id, s)
    row = await s.get(FunnelAccountMedia, (int(funnel_id), str(account_id)))
    return (smd.opener_media_of(row.opening_media_ids) if row is not None else []), []


async def _resolve_funnel(s, payload: dict) -> MassMessageFunnel | None:
    fid = payload.get("funnel_id")
    if fid is not None:
        try:
            return await s.get(MassMessageFunnel, int(fid))
        except (TypeError, ValueError):
            return None
    name = payload.get("funnel_name") or payload.get("funnel")
    if name:
        return (
            await s.execute(
                select(MassMessageFunnel).where(MassMessageFunnel.name == str(name))
            )
        ).scalar_one_or_none()
    return None


async def _members_of_lists(s, list_ids: list[int]) -> list[int]:
    if not list_ids:
        return []
    rows = (
        await s.execute(
            select(ListMember.fan_id).where(ListMember.list_id.in_(list_ids))
        )
    ).all()
    return [int(r[0]) for r in rows]


async def _pending_send_ids_but_dry(account_id: str) -> set[int]:
    from audiences import _PENDING_SEND_KINDS, _payload_recipient_ids
    async with get_session() as s:
        rows = (await s.execute(
            select(ScheduledJob.payload_json).where(
                ScheduledJob.account_id == str(account_id),
                ScheduledJob.status == "pending",
                ScheduledJob.kind.in_(_PENDING_SEND_KINDS),
            )
        )).scalars().all()
    out: set[int] = set()
    for raw in rows:
        try:
            queued = json.loads(raw or "{}")
        except (ValueError, TypeError):
            continue
        if isinstance(queued, dict) and not smd.is_dry_run(queued):
            out |= _payload_recipient_ids(queued)
    return out


async def _dry_fence(account_id: str, client, pol, stats: dict) -> None:
    import audience_include as _audiences
    if pol.mode != "enforce":
        await _audiences.audience_fence_for_broadcast(
            account_id, client=client, policy=pol, stats=stats)
        return
    stats["audience_mode"] = pol.mode
    if pol.paused:
        raise _audiences.AudienceHalt("kill_switch")
    if not pol.healthy:
        raise _audiences.AudienceHalt(pol.reason or "mirror_unhealthy")
    fence = await _audiences._audience_universe_ids(account_id) - pol.member_ids
    if len(fence) > _audiences.AUDIENCE_MAX_LIST_ROWS:
        raise _audiences.AudienceHalt("fence_scale")


async def _dry_run(account_id: str, run_id: int, p: smd.Plan, client, pol,
                   stats: dict) -> dict:
    import audience_include as _audiences
    if p.is_list_audience:
        try:
            await _dry_fence(account_id, client, pol, stats)
        except _audiences.AudienceHalt as e:
            return {"status": "error", "reason": f"audience_halt:{e.reason}", **stats}
    out = smd.dry_run_result(p)
    log.info("send_mass_message DRY RUN account=%s run=%s would_send=%s",
             account_id, run_id, out["would_send_count"])
    return {**out, **stats}


async def close_run_if_unsent(mass_run_id: int | None, e: BaseException) -> None:
    # Only a surely-unsent failure closes the run; one OF may have taken stays running for the boot heal.
    if not mass_run_id or _may_have_sent(e):
        return
    async with get_session() as s:
        mr = await s.get(MassRun, mass_run_id)
        if mr is not None and mr.status == MASS_RUN_RUNNING:
            mr.status = MASS_RUN_REFUSED if proxy_refused(e) else MASS_RUN_FAILED
            mr.completed_at = datetime.utcnow()


@register("send_mass_message")
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    """Broadcast a funnel opener (or an explicit text) to the resolved audience,
    mint a `mass_runs` row, and persist one optimistic `messages` row per known
    recipient. Returns a stats dict (lands in `automation_runs.stats_json`).
    Every answer of a dry run, its skips and halts too, says `dry_run`, `sent: 0`."""
    out = await _run(account_id, payload or {}, run_id=run_id)
    if smd.is_dry_run(payload or {}):
        out = {**out, "dry_run": True, "sent": 0}
    return out


async def _run(account_id: str, payload: dict, *, run_id: int) -> dict:
    if platforms.refusal_for_account(account_id, "send_mass_message"):
        return {"status": "skipped", "reason": f"{PLATFORM_LACKS_PREFIX}send_mass_message"}
    attr_kind = str(payload.get("automation_kind") or "send_mass_message")
    attr_ref = payload.get("automation_ref")

    list_ids, exclude_list_ids = smd.list_ids_of(payload)
    async with get_session() as s:
        funnel_row = await _resolve_funnel(s, payload)
        funnel = (smd.Funnel(id=int(funnel_row.id), opening_message=funnel_row.opening_message)
                  if funnel_row is not None else None)
        list_members = await _members_of_lists(s, list_ids)
        exclude_members = await _members_of_lists(s, exclude_list_ids)
        opener_media: list[int] = []
        if funnel is not None and not int_list(payload.get("media_files")):
            opener_media, _ = await _opener_media(funnel.id, account_id, s)
    included, excluded = smd.seed(payload, list_members, exclude_members)

    from audiences import (
        BROADCAST_DEFAULT_INBOUND_H,
        BROADCAST_DEFAULT_OUTBOUND_H,
        MASSDMEXCLUDE_LIST,
        resolve_mass_audience,
        resolve_window_hours,
    )
    # Contact-guard windows are default-on (absent: 6 h outbound / 2 h inbound, explicit 0 = off) so a blast that forgets them cannot re-touch a fan just messaged.
    out_h = resolve_window_hours(
        payload.get("exclude_replied_hours"), BROADCAST_DEFAULT_OUTBOUND_H)
    in_h = resolve_window_hours(
        payload.get("exclude_inbound_hours"), BROADCAST_DEFAULT_INBOUND_H)
    dry = smd.is_dry_run(payload)
    if dry:
        excluded = [*excluded, *sorted(await _pending_send_ids_but_dry(account_id))]
    resolved = await resolve_mass_audience(
        account_id,
        included_users=included,
        excluded_users=excluded,
        recent_chat_hours=payload.get("recent_chat_hours"),
        recent_chat_limit=payload.get("recent_chat_limit"),
        exclude_replied_hours=out_h or None,
        exclude_inbound_hours=in_h or None,
        exclude_last_chat_hours=payload.get("exclude_last_chat_hours"),
        exclude_funnel_responders=funnel.id if funnel else None,
        unread_limit=payload.get("unread_limit"),
        exclude_list_name=MASSDMEXCLUDE_LIST,
        exclude_pending_sends=not dry,
    )

    p = smd.plan(payload, funnel=funnel, resolved=resolved,
                 list_ids=list_ids, opener_media=opener_media)
    if isinstance(p, smd.Skip):
        log.warning("send_mass_message: %s (funnel=%s) — skipping", p.reason, funnel)
        return {"status": "skipped", "reason": p.reason}

    _banned, _banned_mode = await load_banned_words(account_id)
    _scanned, _hits = filter_banned([p.text], _banned, _banned_mode)
    # Block returns before the mint, so no dangling run row.
    if _scanned is None:
        _uniq = banned_hit_summary(_hits)
        log.warning("send_mass_message: BLOCKED broadcast — banned word(s) %r "
                    "account=%s", _uniq, account_id)
        return {"status": "skipped", "reason": "banned_words", "hits": _uniq}
    if _hits:
        log.info("send_mass_message: masked banned word(s) %r account=%s",
                 banned_hit_summary(_hits), account_id)
    text = _scanned[0]

    employee_id: int | None = None
    try:
        from employees import get_automation_employee_id
        employee_id = await get_automation_employee_id()
    except Exception:
        log.debug("automation employee lookup failed; mass run attribution NULL", exc_info=True)

    from audiences import broadcast_lock, ensure_exclude_list
    import audience_include as _audiences
    client = await asyncio.to_thread(ax._make_client, account_id)
    is_list_audience = p.is_list_audience

    audience_stats: dict = {}
    audience_pol = await _audiences.automation_audience(account_id)
    if audience_pol.mode != "off" and p.recipients:
        p = replace(p, recipients=await _audiences.filter_candidates(
            account_id, p.recipients, kind="send_mass_message",
            policy=audience_pol, stats=audience_stats))
        if not p.recipients and not is_list_audience:
            halted = audience_stats.get("audience_halted")
            log.warning("send_mass_message: audience fence left no explicit "
                        "recipients account=%s (%s)", account_id,
                        halted or "audience_empty")
            if halted:
                return {"status": "error", "reason": f"audience_halt:{halted}",
                        **audience_stats}
            return {"status": "skipped", "reason": "audience_empty",
                    **audience_stats}

    if dry:
        return await _dry_run(account_id, run_id, p, client, audience_pol, audience_stats)

    if not is_list_audience and p.excluded_user_lists and p.recipients:
        from audiences import AudienceUnknown, drop_exclude_list_members
        try:
            kept = await drop_exclude_list_members(client, p.recipients, p.excluded_user_lists)
        except AudienceUnknown:
            log.warning("send_mass_message: exclude list(s) %s unreadable — skipping "
                        "explicit send account=%s", p.excluded_user_lists, account_id)
            return {"status": "error", "reason": "excluded_lists_unreadable"}
        p = replace(p, recipients=kept)
        if not p.recipients:
            return {"status": "skipped", "reason": "audience_empty"}

    fence_attached = False
    auto_lid = None
    # OF has no excludedUsers field for list/online audiences (silently dropped); excludes ride in the Auto_Exclude list via excludedLists, so sync+mint+send hold one per-account lock.
    async with broadcast_lock(account_id):
        if send_ops.cells() and p.recipients:
            held = await asyncio.to_thread(send_ops.held_targets, account_id)
            p = replace(p, recipients=[fan for fan in p.recipients if str(fan) not in held])
            if not p.recipients and not p.user_lists:
                return {"status": "skipped", "reason": "fan_held"}
        if audience_pol.mode != "off" and is_list_audience:
            try:
                fence_ids = await _audiences.audience_fence_for_broadcast(
                    account_id, client=client, policy=audience_pol,
                    stats=audience_stats)
            # Halt loudly: an enforce-mode blast never sends unfenced.
            except _audiences.AudienceHalt as e:
                log.error("send_mass_message: AUTOFENCE unhealthy account=%s "
                          "(%s) — broadcast halted", account_id, e.reason)
                return {"status": "error", "reason": f"audience_halt:{e.reason}",
                        **audience_stats}
            for _lid in fence_ids:
                if _lid not in p.excluded_user_lists:
                    p = replace(p, excluded_user_lists=[*p.excluded_user_lists, _lid])
                    fence_attached = True
        if p.excl_set and is_list_audience:
            try:
                auto_lid = await ensure_exclude_list(
                    account_id, set(p.excl_set), client=client)
            except CellHeld:
                raise
            except Exception as e:
                # A proxy refusal is raised so the job waits it out; any other failure fails closed (no guard = the over-send bug), nothing minted yet.
                if proxy_refused(e):
                    raise
                log.warning("send_mass_message: Auto_Exclude sync failed — "
                            "skipping broadcast account=%s", account_id,
                            exc_info=True)
                return {"status": "error", "reason": "exclude_list_sync_failed"}
            if auto_lid is not None and auto_lid not in p.excluded_user_lists:
                p = replace(p, excluded_user_lists=[*p.excluded_user_lists, auto_lid])

        audience_filter = smd.audience_filter(p, ref=attr_ref, fence=fence_attached,
                                              auto_exclude=auto_lid)
        mass_run_id = 0
        op_kind, op_anchor = _op_kind_anchor(attr_kind, attr_ref, payload)

        # Minted right before the POST: a run row means handed to OF, never still waiting on the write gap.
        async def _mint() -> None:
            nonlocal mass_run_id
            async with get_session() as s:
                mr = MassRun(
                    account_id=str(account_id),
                    funnel_id=p.funnel_id,
                    started_by_employee_id=employee_id,
                    automation_kind=attr_kind,
                    audience_filter=audience_filter,
                    recipient_count=len(p.recipients),
                    status=MASS_RUN_RUNNING,
                )
                s.add(mr)
                await s.flush()
                mass_run_id = int(mr.id)

        # Spaced after the account's previous OF write so resends/drips never crowd OF's window.
        try:
            result = await ax.of_write_paced(
                account_id,
                lambda: send_ops.automated_sync(
                    account_id, op_kind, "mass", op_anchor, lambda: client.send_mass_message(
                        text=text,
                        user_lists=list(p.user_lists),
                        included_users=p.recipients,
                        excluded_users=sorted(p.excl_set),
                        excluded_user_lists=list(p.excluded_user_lists),
                        price=p.price,
                        media_files=p.media_files,
                        previews=p.previews,
                        filters=p.filters,
                        online_only=p.online_only,
                    ), body={"text": text, "price": p.price, "media_files": p.media_files}),
                send_purpose="fenced",
                before_write=_mint,
            )
        except Exception as e:
            await close_run_if_unsent(mass_run_id, e)
            raise
    queue_id = result.get("id") if isinstance(result, dict) else None

    created_at = (
        (_parse_iso(result.get("createdAt")) if isinstance(result, dict) else None)
        or datetime.utcnow()
    )
    price_cents = _to_cents(p.price)

    echoed_fans: set[int] = set()
    for fan_id, msg_id in smd.echoed_of(result):
        echoed_fans.add(fan_id)
        await write_outbound_attribution(
            account_id=account_id,
            fan_id=fan_id,
            message_id=msg_id,
            sent_by_employee_id=employee_id,
            body=text,
            price_cents=price_cents,
            created_at=created_at,
            mass_run_id=mass_run_id,
            automation_kind=attr_kind,
            emit_live=True,
        )
        await reconcile_mass_placeholder(
            account_id=account_id, fan_id=fan_id, mass_run_id=mass_run_id,
        )

    pending = [fid for fid in p.recipients if fid not in echoed_fans]
    optimistic = 0
    if pending:
        optimistic = await write_mass_optimistic_rows(
            account_id=account_id,
            fan_ids=pending,
            mass_run_id=mass_run_id,
            sent_by_employee_id=employee_id,
            body=text,
            price_cents=price_cents,
            created_at=created_at,
            automation_kind=attr_kind,
            emit_live=True,
        )

    async with get_session() as s:
        mr = await s.get(MassRun, mass_run_id)
        if mr is not None:
            mr.status = MASS_RUN_OK
            mr.completed_at = datetime.utcnow()
            if queue_id is not None:
                mr.queue_id = int(queue_id)
            mr.body = text
            mr.sent_at = created_at

    log.info(
        "send_mass_message account=%s run=%s mass_run=%s recipients=%d echoed=%d optimistic=%d",
        account_id, run_id, mass_run_id, len(p.recipients), len(echoed_fans), optimistic,
    )
    return {
        "mass_run_id": mass_run_id,
        "queue_id": int(queue_id) if queue_id is not None else None,
        "funnel_id": p.funnel_id,
        "recipients": len(p.recipients),
        "user_lists": len(p.user_lists),
        "echoed_rows": len(echoed_fans),
        "optimistic_rows": optimistic,
        "skipped_already_answered": len(p.skipped_answered),
        "skipped_already_answered_ids": p.skipped_answered,
        **audience_stats,
    }
