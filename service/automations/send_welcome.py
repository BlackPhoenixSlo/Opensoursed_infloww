from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from random import Random
from types import MappingProxyType
from typing import Any, NamedTuple, get_args

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import automation_executor as ax
import dm_rate
import run_slot
import send_ops
import smart_message_extras as extras
from attribution import write_outbound_attribution
from audiences import contact_guard_excludes, resolve_window_hours
from automation_registry import register
from ._knobs import bool_knob, test_mode
from ._send_failure import revive_outcome, send_dropping_bad_media, skip_unreachable_fan
from ._skiplist import load_hard_skip_ids
from ._style_flags import load_strip_emojis, load_voice_blocks
from ._typing_hold import (hold_with_typing, load_typing_indicator, load_typing_wpm,
                           typing_delay_seconds)
from .lifecycle_messages import (MAX_VARIANTS, follow_ups_of, pick, run_follow_up,
                                 schedule_follow_ups)
from ._run_pool import run_paced
from .rhythm import INLINE_MAX_S
from .pacing import ROLE_GIF as _ROLE_GIF, ROLE_OPENER as _ROLE_OPENER, welcome_burst_pace
from .auto_follow import gated_follow, stamp_ping
from .welcome_compose import (_ADJS, _ADJS_HIM,
                              _bot_folder_media_id,
                              _clock_hours, _compose_bubbles,
                              _custom_message, _greet_token, _load_ai_config,
                              message_variants,
                              _local_greeting, _model_hour,
                              _resolve_welcome_name, _slot_image_id)
from . import welcome_turn
from . import send_welcome_decide
from .welcome_turn import WELCOME_REST_S as _WELCOME_REST_S, Landed as _Landed
from db.engine import get_session
from db.models import WelcomeSent


log = logging.getLogger("of-relay.automation.send_welcome")

_DEFAULT_NOTIF_LIMIT = 50
_DELAY_PAGES_MAX = 6
_DELAY_SLACK_MIN = 10
_DEFAULT_MAX_WELCOMES = 25
_GUARD_DEFAULT_H = 12.0

# A GIF is picked, not typed: flat pause and no typing frame.
_GIF_HOLD_S = 3.0

# A paced burst is ~85-99s of mostly sleeping, so wall time binds: 6 drains a 25-fan surge in about two runs.
_PACE_CONCURRENCY = 6
# Admission budget, checked before a fan starts, never mid-burst; deferred fans have no welcome_sent claim, so the next tick re-serves them.
_RUN_WALL_BUDGET_S = 300.0
# With no image all greetings fire inside this band, bypassing of_write_paced spacing and retry; if OF starts 429ing, widen it first, routing through of_write_paced is the real fix.
_PACE_START_JITTER_S = (0.5, 4.0)
# Upper bound on emit overhead only: it includes event-loop contention from the other concurrent bursts.
_HOLD_OVERRUN_WARN_S = 2.0




@dataclass(slots=True)
class _Tally:

    sent: int = 0
    errors: int = 0
    skipped_locked: int = 0
    skipped_cooldown: int = 0
    image_attached: int = 0
    pinned_used: int = 0
    gifs_sent: int = 0
    followed_back: int = 0
    follow_back: Counter = field(default_factory=Counter)
    follow_back_errors: int = 0
    deferred_budget: int = 0
    aborted_on_reply: int = 0
    turn: Counter = field(default_factory=Counter)
    reply_guard_off: int = 0
    hold_overrun_max_s: float = 0.0
    follow_ups_queued: int = 0
    after_of_welcome: int = 0


_FOLLOW_BACK_DEFAULT = True
# Default ON: OF's /subscribe charges when the target is a paid creator, and the read saved was never worth an unasked-for purchase.
_FOLLOW_BACK_GATE_DEFAULT = True



def _find_user(item: dict) -> dict | None:
    for key in ("user", "fromUser", "subscriber", "author"):
        u = item.get(key)
        if isinstance(u, dict) and u.get("id"):
            return u
    data = item.get("data")
    if isinstance(data, dict):
        for key in ("user", "relatedUser", "subscriber"):
            u = data.get(key)
            if isinstance(u, dict) and u.get("id"):
                return u
    return None


# OF dropped the type= filter (it now 400s), so the feed is mixed: keep subscribe-ish items; untyped items pass through.
def _extract_new_subscribers(resp: object) -> list[dict]:
    if isinstance(resp, list):
        items = resp
    elif isinstance(resp, dict):
        items = resp.get("list") or resp.get("notifications") or resp.get("items") or []
    else:
        items = []
    out: list[dict] = []
    seen: set[int] = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        t = str(it.get("type") or "").lower()
        if t and "subscrib" not in t:
            continue
        user = _find_user(it)
        if not user:
            continue
        try:
            uid = int(user.get("id"))
        except (TypeError, ValueError):
            continue
        if uid in seen:
            continue
        seen.add(uid)
        out.append({"id": uid, "username": user.get("username"), "name": user.get("name"),
                    "at": extras.parse_iso(it.get("createdAt"))})
    return out




# Persisted dedup: survives restarts, so a sub yields exactly one welcome.
async def _load_welcomed(account_id: str) -> set[int]:
    async with get_session() as s:
        rows = (await s.execute(
            select(WelcomeSent.fan_id).where(WelcomeSent.account_id == str(account_id))
        )).all()
    return {int(r[0]) for r in rows}


async def _established_fan_ids(
    account_id: str, fan_ids: list[int], *, max_outbound: int, max_inbound: int
) -> set[int]:
    import audience_include
    return await audience_include.established_fan_ids(
        account_id, fan_ids, max_outbound=max_outbound, max_inbound=max_inbound)


async def _mark_welcomed(account_id: str, fan_id: int, username: str | None) -> None:
    async with get_session() as s:
        await s.execute(
            sqlite_insert(WelcomeSent)
            .values(
                account_id=str(account_id),
                fan_id=int(fan_id),
                fan_username=username,
                sent_at=datetime.utcnow(),
            )
            .on_conflict_do_nothing(index_elements=["account_id", "fan_id"])
        )




# Absent means ON in production (operator decision); under CHATTERLY_TEST_MODE absent means OFF.
def _on_unless_off(payload: dict, key: str) -> bool:
    return bool_knob(payload, key, not test_mode())



class _HoldSegment(NamedTuple):
    seconds: float
    indicator: bool
    quiet_s: float
    think_at_s: float
    think_for_s: float
    check_after: bool


def _hold_segments(*, pace, typing_s: float, is_gif: bool, typing_on: bool,
                   interruptible: bool) -> list[_HoldSegment]:
    indicator = typing_on and not is_gif
    if pace is None:
        total = _GIF_HOLD_S if is_gif else typing_s
        segments = [_HoldSegment(total, indicator, 0.0, 0.0, 0.0,
                                 is_gif and interruptible)]
    elif interruptible and not is_gif and pace.quiet_s > 0:
        segments = [
            _HoldSegment(pace.quiet_s, False, 0.0, 0.0, 0.0, True),
            _HoldSegment(pace.total_s - pace.quiet_s, indicator, 0.0,
                         pace.think_at_s, pace.think_for_s, False),
        ]
    else:
        segments = [_HoldSegment(pace.total_s, indicator, pace.quiet_s,
                                 pace.think_at_s, pace.think_for_s,
                                 is_gif and interruptible)]
    want = (pace.total_s if pace is not None
            else (_GIF_HOLD_S if is_gif else typing_s))
    assert abs(sum(seg.seconds for seg in segments) - want) < 1e-9, (segments, want)
    return segments



@dataclass(frozen=True, slots=True)
class _RunCtx:

    account_id: str
    voice: str
    cfg: Mapping[str, Any]
    hour: int
    client: Any
    bot_media_id: int | None
    tally: _Tally

    dry_run: bool
    time_only: bool
    skip_time_bubble: bool
    question: str
    gif_id: str
    message: tuple[str, ...]
    media_ids: tuple[int, ...]
    price_cents: int
    owners: frozenset[int]
    unsend_minutes: int
    follow_back: bool
    follow_back_gate: bool
    paced: bool
    stop_on_reply: bool
    early_mark: bool
    pace_open_quiet: Any
    pace_gap_quiet: Any
    follow_ups: tuple[dict, ...]

    typing_wpm: float
    typing_on: bool
    strip_emoji_on: bool


_Bubble = tuple[str, str | None, str]


class _Burst(NamedTuple):
    landed: int
    last_landed: _Landed | None
    aborted: tuple[datetime, int] | None
    marked: bool
    lost: "run_slot.SlotLost | None" = None


async def _reply_anchor(ctx: _RunCtx, fan_id: int
                        ) -> tuple[tuple[datetime, int] | None, bool]:
    if not ctx.stop_on_reply:
        return None, False
    try:
        return await welcome_turn.newest_worded_inbound(ctx.account_id, fan_id), True
    # A failed anchor read runs the burst unguarded; counted so stop_on_reply:true with zero aborts isn't read as nobody replied.
    except Exception:
        ctx.tally.reply_guard_off += 1
        log.warning("send_welcome reply anchor failed account=%s fan=%s — burst "
                    "runs unguarded", ctx.account_id, fan_id, exc_info=True)
        return None, False


async def _compose_plan(ctx: _RunCtx, sub: dict) -> list[_Bubble] | None:
    fan_id = sub["id"]
    try:
        name = await _resolve_welcome_name(ctx.account_id, fan_id, sub)
        greeting = _local_greeting(name or _greet_token(sub, ctx.voice), ctx.voice)
    except Exception:
        ctx.tally.errors += 1
        log.warning("send_welcome generate failed account=%s fan=%s",
                    ctx.account_id, fan_id, exc_info=True)
        return None
    if ctx.message:
        text = _custom_message(pick(ctx.message, "welcome", ctx.account_id, fan_id), name,
                               strip_emoji_on=ctx.strip_emoji_on)
        if not text.strip():
            ctx.tally.errors += 1
            return None
        return [(text, None, _ROLE_OPENER)]
    bubbles, roles, was_pinned = await _compose_bubbles(
        greeting=greeting, cfg=ctx.cfg, hour=ctx.hour,
        skip_time_bubble=ctx.skip_time_bubble, time_only=ctx.time_only,
        question=ctx.question, strip_emoji_on=ctx.strip_emoji_on)
    if was_pinned:
        ctx.tally.pinned_used += 1
    if not bubbles:
        ctx.tally.errors += 1
        return None
    plan: list[_Bubble] = [(b, None, r) for b, r in zip(bubbles, roles)]
    if ctx.gif_id:
        plan.append(("", ctx.gif_id, _ROLE_GIF))
    return plan


def _burst_media(ctx: _RunCtx, fan_id: int) -> tuple[list[int], int]:
    media_ids = ([ctx.bot_media_id] if ctx.bot_media_id is not None
                 else list(ctx.media_ids))
    # a paid message never re-sells media he already owns: text alone, free
    if fan_id in ctx.owners:
        return [], 0
    return media_ids, ctx.price_cents


async def _hold_bubble(ctx: _RunCtx, fan_id: int, idx: int, part: str,
                       gid: str | None, role: str, *, has_image: bool,
                       anchor: tuple[datetime, int] | None,
                       checking: bool) -> tuple[datetime, int] | None:
    typing_s = 0.0 if gid else typing_delay_seconds(part, ctx.typing_wpm)
    pace = welcome_burst_pace(
        role=role, has_image=has_image,
        typing_s=typing_s, text=part,
        rng=Random(f"welcome_pace:{ctx.account_id}:{fan_id}:{idx}"),
        open_quiet=ctx.pace_open_quiet,
        gap_quiet=ctx.pace_gap_quiet) if ctx.paced else None
    t0, w0 = time.monotonic(), run_slot.waited_s()
    for seg in _hold_segments(pace=pace, typing_s=typing_s,
                              is_gif=bool(gid), typing_on=ctx.typing_on,
                              interruptible=checking):
        await hold_with_typing(
            ctx.account_id, fan_id, seg.seconds,
            typing_indicator=seg.indicator, quiet_s=seg.quiet_s,
            think_at_s=seg.think_at_s, think_for_s=seg.think_for_s)
        if seg.check_after:
            aborted = await welcome_turn.fan_replied_since(
                ctx.account_id, fan_id, anchor)
            if aborted is not None:
                return aborted
    waited = await dm_rate.turn(ctx.account_id, release_budget_s=INLINE_MAX_S)
    if waited > 0 and checking:
        aborted = await welcome_turn.fan_replied_since(ctx.account_id, fan_id, anchor)
        if aborted is not None:
            dm_rate.release(ctx.account_id)
            return aborted
    if pace is not None:
        over = (time.monotonic() - t0) - (run_slot.waited_s() - w0) - pace.total_s
        if over > ctx.tally.hold_overrun_max_s:
            ctx.tally.hold_overrun_max_s = over
        if over > _HOLD_OVERRUN_WARN_S:
            log.warning("send_welcome hold overran by %.1fs account=%s "
                        "fan=%s bubble=%d (requested %.1fs)",
                        over, ctx.account_id, fan_id, idx, pace.total_s)
    return None


class _Sent(NamedTuple):
    result: Any
    media_landed: bool


async def _send_bubble(ctx: _RunCtx, sub: dict, idx: int, part: str,
                       gid: str | None, media_ids: list[int],
                       price_cents: int) -> _Sent | None:
    fan_id = sub["id"]
    anchor = f"welcome:{fan_id}"
    try:
        if gid:
            await dm_rate.turn(ctx.account_id)
            result = await asyncio.to_thread(lambda g=gid: send_ops.automated_sync(
                ctx.account_id, "send_welcome", fan_id, anchor,
                lambda: ctx.client.send_message(fan_id, "", giphy_id=g), part=idx))
            return _Sent(result, False)
        outcome = await send_ops.automated(
            ctx.account_id, "send_welcome", fan_id, anchor,
            lambda: send_dropping_bad_media(ctx.client, fan_id, part, media_ids, log=log,
                                            send_purpose="gated", price_cents=price_cents),
            part=idx, revive=revive_outcome)
        return _Sent(outcome.result, outcome.media_landed)
    except Exception as e:
        if send_ops.skip_fan(e):
            return None
        # Permanent unreachable (deleted/blocked): claim welcome_sent so the sweep never regenerates a welcome for a fan we can't reach.
        if idx == 0:
            ctx.tally.errors += 1
            if await skip_unreachable_fan(ctx.account_id, fan_id, e, log=log):
                await _mark_welcomed(ctx.account_id, fan_id, sub.get("username"))
            log.warning("send_welcome send failed account=%s fan=%s",
                        ctx.account_id, fan_id, exc_info=True)
        else:
            log.warning("send_welcome bubble %d failed account=%s fan=%s",
                        idx + 1, ctx.account_id, fan_id, exc_info=True)
        return None


async def _record_landed(ctx: _RunCtx, fan_id: int, part: str, gid: str | None,
                         sent: _Sent, price_cents: int) -> _Landed:
    result = sent.result
    if gid:
        ctx.tally.gifs_sent += 1
    elif sent.media_landed:
        ctx.tally.image_attached += 1
    msg_id = result.get("id") if isinstance(result, dict) else None
    of_created = (ax._parse_iso(result.get("createdAt"))
                  if isinstance(result, dict) else None)
    landed_at = of_created or datetime.utcnow()
    last_landed = _Landed(landed_at, int(msg_id or 0),
                          of_created is not None and msg_id is not None)
    if msg_id:
        await write_outbound_attribution(
            account_id=ctx.account_id,
            fan_id=int(fan_id),
            message_id=int(msg_id),
            sent_by_employee_id=None,
            automation_kind="welcome",
            body=str(result.get("text") or part),
            price_cents=price_cents,
            created_at=landed_at,
            emit_live=True,
        )
    return last_landed


async def _send_burst(ctx: _RunCtx, sub: dict, plan: list[_Bubble],
                      anchor: tuple[datetime, int] | None,
                      check_reply: bool) -> _Burst:
    fan_id = sub["id"]
    media_ids, sell_cents = _burst_media(ctx, fan_id)
    landed = 0
    marked = False
    last_landed: _Landed | None = None
    aborted: tuple[datetime, int] | None = None
    lost: run_slot.SlotLost | None = None
    for idx, (part, gid, role) in enumerate(plan):
        checking = check_reply and idx >= 1
        bubble_media, bubble_sell = (media_ids, sell_cents) if idx == 0 else ([], 0)
        if checking and not gid:
            aborted = await welcome_turn.fan_replied_since(ctx.account_id, fan_id, anchor)
            if aborted is not None:
                break
        try:
            aborted = await _hold_bubble(ctx, fan_id, idx, part, gid, role,
                                         has_image=bool(media_ids), anchor=anchor,
                                         checking=checking)
        except run_slot.SlotLost as e:
            if landed == 0:
                raise
            lost = e
            break
        if aborted is not None:
            break
        sent = await _send_bubble(ctx, sub, idx, part, gid, bubble_media, bubble_sell)
        if sent is None:
            break
        landed += 1
        price_cents = bubble_sell if sent.media_landed else 0
        last_landed = await _record_landed(ctx, fan_id, part, gid, sent, price_cents)
        if idx == 0:
            # claim welcome_sent as early as honestly possible: a second greeting next tick must never happen
            if ctx.early_mark:
                await _mark_welcomed(ctx.account_id, fan_id, sub.get("username"))
                marked = True
            msg_id = sent.result.get("id") if isinstance(sent.result, dict) else None
            if ctx.message and msg_id:
                await extras.schedule_unsend(
                    ctx.account_id, fan_id, int(msg_id),
                    minutes=ctx.unsend_minutes, price_cents=price_cents)
    return _Burst(landed, last_landed, aborted, marked, lost)


async def _follow_back_one(ctx: _RunCtx, fan_id: int) -> None:
    try:
        # money_gate=False follows with no profile read: a new sub who is a paid creator charges this account their price
        fb_outcome = await gated_follow(
            ctx.client, fan_id, account_id=ctx.account_id, unfollow_first=False,
            money_gate=ctx.follow_back_gate)
        if fb_outcome in ("followed", "refollowed"):
            ctx.tally.followed_back += 1
            try:
                await stamp_ping(ctx.account_id, fan_id)
            except Exception:
                log.warning("send_welcome follow-back ledger write failed "
                            "account=%s fan=%s — the follow landed; auto_follow "
                            "may notify him again", ctx.account_id, fan_id,
                            exc_info=True)
        else:
            ctx.tally.follow_back[fb_outcome] += 1
    except Exception:
        ctx.tally.follow_back_errors += 1
        log.warning("send_welcome follow-back failed account=%s fan=%s — "
                    "welcome already landed", ctx.account_id, fan_id,
                    exc_info=True)


_UNREAD = object()


async def _queue_follow_ups(ctx: _RunCtx, fan_id: int, anchor) -> None:
    try:
        if anchor is _UNREAD:
            anchor = await welcome_turn.newest_worded_inbound(ctx.account_id, fan_id)
        await schedule_follow_ups(ctx.account_id, "send_welcome", fan_id,
                                  list(ctx.follow_ups), anchor,
                                  event=f"welcome:{datetime.utcnow().isoformat()}")
        ctx.tally.follow_ups_queued += 1
    except Exception:
        log.warning("send_welcome follow-ups not queued account=%s fan=%s",
                    ctx.account_id, fan_id, exc_info=True)


async def _of_welcome_on(client, account_id: str) -> bool | None:
    try:
        settings = await asyncio.to_thread(client.my_settings)
        if not (isinstance(settings, dict) and settings.get("replyOnSubscribe") is True):
            return False
        rows = await asyncio.to_thread(client.message_templates)
        rows = rows.get("list") if isinstance(rows, dict) else rows
        return any(
            isinstance(t, dict) and t.get("template") == "reply_on_subscribe"
            and bool(re.sub(r"<[^>]*>", "", str(t.get("text") or "")).strip()
                     or int(t.get("mediaCount") or 0) > 0)
            for t in rows or [])
    except Exception:
        log.warning("send_welcome OF welcome check failed account=%s — sending our own",
                    account_id, exc_info=True)
        return None


async def _after_of_welcome(ctx: _RunCtx, sub: dict) -> None:
    fan_id = sub["id"]
    ctx.tally.after_of_welcome += 1
    if ctx.dry_run:
        return
    await _mark_welcomed(ctx.account_id, fan_id, sub.get("username"))
    if ctx.follow_ups:
        await _queue_follow_ups(ctx, fan_id, _UNREAD)
    if ctx.follow_back:
        await _follow_back_one(ctx, fan_id)


async def _welcome_one(ctx: _RunCtx, w: send_welcome_decide.Welcome) -> None:
    sub = w.sub
    fan_id = sub["id"]
    if await ax.fan_on_cooldown(ctx.account_id, fan_id):
        ctx.tally.skipped_cooldown += 1
        return
    if not await ax.acquire_fan_lease(ctx.account_id, fan_id, "send_welcome"):
        ctx.tally.skipped_locked += 1
        return
    sent_ok = False
    try:
        if w.by_of:
            await _after_of_welcome(ctx, sub)
            return
        anchor, check_reply = await _reply_anchor(ctx, fan_id)
        plan = await _compose_plan(ctx, sub)
        if plan is None:
            return
        if ctx.dry_run:
            ctx.tally.sent += 1
            return
        burst = await _send_burst(ctx, sub, plan, anchor, check_reply)
        if burst.landed == 0:
            return
        if not burst.marked:
            await _mark_welcomed(ctx.account_id, fan_id, sub.get("username"))
        ctx.tally.sent += 1
        sent_ok = True
        if burst.lost is not None:
            raise burst.lost
        if ctx.follow_back:
            await _follow_back_one(ctx, fan_id)
        if ctx.follow_ups and burst.aborted is None:
            await _queue_follow_ups(ctx, fan_id, anchor if check_reply else _UNREAD)
        if burst.aborted is not None:
            ctx.tally.aborted_on_reply += 1
        verdict = await welcome_turn.hand_back_turn(
            ctx.account_id, fan_id, anchor=anchor, check_reply=check_reply,
            aborted=burst.aborted, last_landed=burst.last_landed,
            landed=burst.landed)
        ctx.tally.turn[verdict] += 1
    finally:
        # order is load-bearing: cooldown must be set before the lease drops; if the cooldown write fails keep the lease
        rested = False
        if sent_ok:
            try:
                await ax.start_fan_cooldown(ctx.account_id, fan_id,
                                            cooldown_s=_WELCOME_REST_S)
                rested = True
            except Exception:
                log.warning("send_welcome cooldown set failed account=%s fan=%s "
                            "— keeping the lease as the fallback brake",
                            ctx.account_id, fan_id, exc_info=True)
        if rested or not sent_ok:
            await ax.release_fan_lease(ctx.account_id, fan_id)


class _Candidates(NamedTuple):
    seen: int
    admitted: list[send_welcome_decide.Welcome]
    skipped: Counter[send_welcome_decide.Reason]


async def _source_subs(client, payload: dict, *, limit: int,
                       delay: list[int] | None) -> list[dict]:
    test_fan = payload.get("test_fan")
    if test_fan:
        nm = payload.get("test_name") or ""
        return [{"id": int(test_fan), "username": nm or None, "name": nm or None}]
    resp = await asyncio.to_thread(
        client.notifications, limit=limit, offset=0, type="subscribed",
    )
    subs = _extract_new_subscribers(resp)
    if delay:
        horizon = datetime.utcnow() - timedelta(minutes=delay[1] + _DELAY_SLACK_MIN)
        seen_ids = {s["id"] for s in subs}
        page = subs
        for n in range(1, _DELAY_PAGES_MAX):
            stamps = [s["at"] for s in page if s.get("at") is not None]
            if (not isinstance(resp, dict) or resp.get("hasMore") is False
                    or not stamps or min(stamps) < horizon):
                break
            resp = await asyncio.to_thread(
                client.notifications, limit=limit, offset=n * limit, type="subscribed",
            )
            page = [s for s in _extract_new_subscribers(resp) if s["id"] not in seen_ids]
            seen_ids.update(s["id"] for s in page)
            subs.extend(page)
    return subs


async def _candidates(account_id: str, client, payload: dict, *,
                      limit: int, of_welcome_on: bool | None) -> _Candidates:
    test_fan = bool(payload.get("test_fan"))
    delay = extras.delay_range(payload)
    subs = await _source_subs(client, payload, limit=limit, delay=delay)
    starts_at = extras.window_start(payload)
    now = datetime.utcnow()
    reads = send_welcome_decide.Reads(welcomed=await _load_welcomed(account_id),
                                      of_welcome_on=of_welcome_on)

    def decide(reads: send_welcome_decide.Reads) -> list[send_welcome_decide.Decision]:
        return send_welcome_decide.partition(
            subs, reads, account_id=account_id, now=now, test_fan=test_fan,
            starts_at=starts_at, delay=delay)

    def pending_ids(reads: send_welcome_decide.Reads) -> list[int]:
        return [w.sub["id"] for w in send_welcome_decide.welcomes(decide(reads))]

    pending = pending_ids(reads)
    max_out = int(payload.get("new_max_outbound", 2))
    max_in = int(payload.get("new_max_inbound", 8))
    if not test_fan and pending:
        # NOT-NEW gate: the feed includes renewals/re-subs and welcome_sent lacks fans pre-dating this automation, so established fans are skipped, not re-welcomed.
        known = await _established_fan_ids(
            account_id, pending, max_outbound=max_out, max_inbound=max_in)
        if known:
            reads = replace(reads, established=frozenset(known))
            pending = pending_ids(reads)
            log.info("send_welcome skipped %d established fan(s) account=%s",
                     len(known), account_id)
        guard_h = resolve_window_hours(payload.get("guard_hours"), _GUARD_DEFAULT_H)
        if pending and guard_h > 0:
            guard_ids = await contact_guard_excludes(account_id, outbound_hours=guard_h)
            if guard_ids:
                reads = replace(reads, guard=frozenset(guard_ids))
                pending = pending_ids(reads)
        if pending:
            hard_skip = await load_hard_skip_ids(account_id)
            if hard_skip:
                reads = replace(reads, restricted=frozenset(hard_skip))
                pending = pending_ids(reads)

    if pending:
        import audience_include as _audiences
        _pol = await _audiences.automation_audience(account_id)
        if _pol.mode != "off":
            reads = replace(reads, audience=frozenset(await _audiences.filter_candidates(
                account_id, pending, kind="send_welcome", policy=_pol)))

    decisions = decide(reads)
    return _Candidates(len(subs), send_welcome_decide.welcomes(decisions),
                       send_welcome_decide.skip_counts(decisions))


async def _welcome_all(ctx: _RunCtx, admitted: list[send_welcome_decide.Welcome],
                       run_started: float) -> None:
    if not ctx.paced:
        for w in admitted:
            await _welcome_one(ctx, w)
    else:
        pool = await run_paced(
            admitted, lambda w: _welcome_one(ctx, w),
            concurrency=_PACE_CONCURRENCY, wall_budget_s=_RUN_WALL_BUDGET_S,
            started_at=run_started, clock=time.monotonic,
            jitter_for=lambda w: Random(
                f"wstart:{ctx.account_id}:{w.sub['id']}").uniform(*_PACE_START_JITTER_S))
        ctx.tally.deferred_budget = pool.deferred
        if pool.deferred:
            log.warning("send_welcome wall budget spent account=%s — deferring "
                        "%d fan(s) to the next tick", ctx.account_id, pool.deferred)
        # paced path counts a fan's crash instead of failing the run: one fan must not kill the other bursts
        for exc in pool.errors:
            ctx.tally.errors += 1
            log.warning("send_welcome paced fan failed account=%s",
                        ctx.account_id, exc_info=exc)


_SKIP_STATS: dict[send_welcome_decide.Reason, str] = {
    "established": "skipped_existing", "guard": "skipped_guard",
    "restricted": "skipped_restricted", "audience": "skipped_audience",
    "before_start": "skipped_before_start", "delayed": "delayed"}
assert set(_SKIP_STATS) == set(get_args(send_welcome_decide.Reason)) - {"welcomed"}, \
    "_SKIP_STATS out of sync with send_welcome_decide.Reason"


def _run_stats(ctx: _RunCtx, cands: _Candidates, *, after_of_welcome: bool,
               of_welcome: bool | None, batch_capped: bool,
               run_started: float) -> dict:
    t = ctx.tally
    return {
        "subscribers_seen": cands.seen,
        "new_subscribers": len(cands.admitted),
        "welcomes_sent": t.sent,
        "image_attached": t.image_attached,
        "pinned_used": t.pinned_used,
        "gifs_sent": t.gifs_sent,
        "follow_back": ctx.follow_back,
        "follow_back_gate": ctx.follow_back_gate,
        "followed_back": t.followed_back,
        "follow_back_already": (t.follow_back["already_following"]
                                + t.follow_back["pinged"]),
        "follow_back_paid_skipped": t.follow_back["paid_profile"],
        "follow_back_no_price": t.follow_back["no_price"],
        "follow_back_outcomes": dict(t.follow_back),
        "follow_back_errors": t.follow_back_errors,
        "skipped_locked": t.skipped_locked,
        "skipped_cooldown": t.skipped_cooldown,
        **{key: cands.skipped[reason] for reason, key in _SKIP_STATS.items()},
        "errors": t.errors,
        "message_variants": len(ctx.message),
        "after_of_welcome": after_of_welcome,
        "of_welcome_on": of_welcome,
        "after_of_welcome_fans": t.after_of_welcome,
        "follow_ups_queued": t.follow_ups_queued,
        "batch_capped": batch_capped,
        "dry_run": ctx.dry_run,
        "human_pace": ctx.paced,
        "run_wall_s": round(time.monotonic() - run_started, 1),
        "deferred_budget": t.deferred_budget,
        "hold_overrun_max_s": round(t.hold_overrun_max_s, 2),
        "stop_on_reply": ctx.stop_on_reply,
        "reply_guard_off": t.reply_guard_off,
        "aborted_on_reply": t.aborted_on_reply,
        "handoff_enqueued": t.turn["handoff"],
        "handoff_no_engine": t.turn["no_engine"],
        "handoff_skipped_restricted": t.turn["restricted"],
    }



@register("send_welcome")
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    payload = payload or {}
    if isinstance(payload.get("follow_up"), dict):
        return await run_follow_up(account_id, "send_welcome", payload["follow_up"],
                                   attribution_kind="welcome")
    _wv = (await load_voice_blocks(account_id)).voice
    dry_run = bool_knob(payload, "dry_run", False)
    with_image = bool_knob(payload, "with_image", True)
    limit = int(payload.get("limit") or _DEFAULT_NOTIF_LIMIT)
    max_welcomes = int(payload.get("max_welcomes") or _DEFAULT_MAX_WELCOMES)

    cfg = await _load_ai_config(account_id)
    strip_emoji_on = await load_strip_emojis(account_id)
    typing_wpm = await load_typing_wpm(account_id)
    typing_on = await load_typing_indicator(account_id)
    # Absent stays False on purpose (editor saves stamp the catalog's True): a True read default would turn every legacy rule clock-only.
    time_only = bool_knob(payload, "time_only", False)
    skip_time_bubble = bool_knob(payload, "skip_time_bubble", False)
    question = str(payload.get("question") or "").strip()
    gif_id = str(payload.get("gif_id") or "").strip()
    message = message_variants(payload.get("message"))[:MAX_VARIANTS]
    media_ids, price_cents = extras.media_and_price(payload) if message else ([], 0)
    unsend_minutes = extras.unsend_minutes(payload) if message else 0
    outside = None if payload.get("test_fan") else extras.window_skip(payload, datetime.utcnow())
    if outside:
        return {"status": "skipped", "reason": outside, "welcomes_sent": 0}
    follow_back = bool_knob(payload, "follow_back", _FOLLOW_BACK_DEFAULT)
    follow_back_gate = bool_knob(payload, "follow_back_gate", _FOLLOW_BACK_GATE_DEFAULT)
    human_pace = _on_unless_off(payload, "human_pace")
    paced = human_pace and not payload.get("test_fan")
    pace_open_quiet = payload.get("pace_open_quiet_s")
    pace_gap_quiet = payload.get("pace_gap_quiet_s")
    stop_on_reply = _on_unless_off(payload, "stop_on_reply")
    early_mark = human_pace or stop_on_reply
    follow_ups = tuple(follow_ups_of(payload.get("follow_ups")))
    after_of_welcome = bool_knob(payload, "after_of_welcome", False)
    run_started = time.monotonic()

    client = await asyncio.to_thread(ax._make_client, account_id)
    of_welcome = await _of_welcome_on(client, account_id) if after_of_welcome else None

    hour = _model_hour(_clock_hours(cfg))
    bot_media_id: int | None = None
    if with_image and not dry_run and not message and of_welcome is not True:
        bot_media_id = _slot_image_id(cfg, hour)
        if bot_media_id is None:
            bot_media_id = await asyncio.to_thread(_bot_folder_media_id, client, hour)

    cands = await _candidates(account_id, client, payload, limit=limit,
                              of_welcome_on=of_welcome)
    admitted = cands.admitted
    new_total = len(admitted)

    batch_capped = new_total > max_welcomes
    if batch_capped:
        log.warning(
            "send_welcome batch capped account=%s new=%d cap=%d (rest next tick)",
            account_id, new_total, max_welcomes,
        )
        admitted = admitted[:max_welcomes]

    t = _Tally()

    ctx = _RunCtx(
        account_id=account_id, voice=_wv, cfg=MappingProxyType(cfg), hour=hour,
        client=client, bot_media_id=bot_media_id, tally=t,
        dry_run=dry_run, time_only=time_only,
        skip_time_bubble=skip_time_bubble, question=question, gif_id=gif_id,
        message=message, media_ids=tuple(media_ids), price_cents=price_cents,
        owners=frozenset(await extras.owners(
            account_id, media_ids, price_cents, [w.sub["id"] for w in admitted])),
        unsend_minutes=unsend_minutes,
        follow_back=follow_back, follow_back_gate=follow_back_gate,
        paced=paced, stop_on_reply=stop_on_reply, early_mark=early_mark,
        pace_open_quiet=pace_open_quiet, pace_gap_quiet=pace_gap_quiet,
        typing_wpm=typing_wpm, typing_on=typing_on,
        strip_emoji_on=strip_emoji_on, follow_ups=follow_ups)

    await _welcome_all(ctx, admitted, run_started)

    return _run_stats(ctx, cands, after_of_welcome=after_of_welcome,
                      of_welcome=of_welcome, batch_capped=batch_capped,
                      run_started=run_started)
