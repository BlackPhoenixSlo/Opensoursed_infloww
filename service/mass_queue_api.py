"""service/mass_queue_api.py — server.py's mass-message queue block, moved wholesale:
the composer's broadcast (send now / schedule / save for later), a queued
message's read + in-place edit, and the cancel / mass unsend.

  POST   /api/of/v2/messages/queue
  POST   /api/of/v2/messages/queue/later
  GET    /api/of/v2/messages/queue/{queue_id:int}
  PUT    /api/of/v2/messages/queue/{queue_id:int}
  DELETE /api/of/v2/messages/queue/{queue_id}

plus `_open_mass_run` / `_close_mass_run` (the mass_runs mint + close). The pure
decisions live in mass_queue_decide.py, called through the module attribute.
`_proxy`, `_get_client`, `_load_client`, `_resolve_account_id`, `_spawn_bg` are
relay_host's call-time forwards, never `from server import`, so a test's
`server._get_client = fake` still reaches the moved code. Included mid-file in
server.py for route order (pinned by service/tests/test_route_order.py).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field

import mass_queue_decide
from automations.send_mass_decide import echoed_of
from relay_host import (
    get_client as _get_client,
    load_client as _load_client,
    proxy as _proxy,
    resolve_account_id as _resolve_account_id,
    spawn_bg as _spawn_bg,
)

log = logging.getLogger("of-relay")

router = APIRouter()


@contextlib.asynccontextmanager
async def _exclude_list_held(account_id: str, excluded_users: list[int]):
    """The composer's Auto_Exclude sync, yielding its OF list id with the
    account's `broadcast_lock` held until the caller's block ends: the block is
    the blast's OF POST. Looked up per call: slop's `auto-exclude-manual-lock-early`
    fault (slop/lib/auto_exclude_faults.py) wraps it to release the lock early."""
    from audiences import broadcast_lock, ensure_exclude_list
    async with broadcast_lock(account_id):
        yield await ensure_exclude_list(account_id, excluded_users, client=_get_client())


async def _open_mass_run(
    request: Request,
    *,
    user_lists: list,
    included_users: list[int],
    excluded_users: list[int],
    excluded_user_lists: list | None = None,
    funnel_id: int | None = None,
) -> tuple[str, int | None, int | None]:
    """Resolve account + X-Employee-Id and mint a `mass_runs` row so every
    per-fan outbound row downstream can reference it. Returns
    `(account_id, employee_id, mass_run_id)` — `mass_run_id` may be None if
    the mint failed (the broadcast still proceeds; attribution degrades to
    NULL, same fallback as the single-fan path)."""
    account_id = _resolve_account_id(request)
    # Resolves header (owner) OR chatter mirror Employee under the
    # account's owner. Chatters never carry X-Employee-Id and the header
    # is the only way the old path knew "who sent this"; without this
    # branch every chatter send showed up as Automation in the per-
    # employee stats table.
    from employees import resolve_outbound_employee_id
    employee_id = await resolve_outbound_employee_id(request, account_id)

    audience_filter = json.dumps({
        "user_lists": user_lists,
        "included_users": included_users,
        "excluded_users": excluded_users,
        # The audience actually SENT is wider than the three keys above: OF has
        # no per-user exclusion field for a list audience, so the excluded ids
        # ride in the Auto_Exclude list attached here. Forensics only — who
        # RECEIVED the blast is recorded on `recipients_json` at close.
        "excluded_user_lists": list(excluded_user_lists or []),
    })
    mass_run_id: int | None = None
    try:
        from db.engine import get_session
        from db.models import MassRun
        async with get_session() as s:
            run = MassRun(
                account_id=str(account_id),
                funnel_id=int(funnel_id) if funnel_id is not None else None,
                started_by_employee_id=employee_id,
                audience_filter=audience_filter,
                recipient_count=len(included_users),
                status="running",
            )
            s.add(run)
            await s.flush()
            mass_run_id = int(run.id)
    except Exception:
        log.exception("mass_runs mint failed (account=%s)", account_id)
    return account_id, employee_id, mass_run_id


async def _close_mass_run(
    *,
    account_id: str,
    employee_id: int | None,
    mass_run_id: int | None,
    text: str,
    price: float,
    result: Any,
    recipient_ids: list[int] | None = None,
    audience: dict | None = None,
    scheduled: bool = False,
) -> None:
    """After OF returns, persist a `messages` row per recipient of the
    broadcast. Two sources, handled in order:

      1. **Echoed ids.** OF's `/messages/queue` shape varies — some
         installations echo `{messages: [{userId, id, ...}]}`. For each
         echoed pair we write the REAL row (`write_outbound_attribution`) and
         drop any optimistic placeholder for that recipient.
      2. **Optimistic rows.** For the explicit recipients OF did NOT echo
         (`recipient_ids`, i.e. the `userIds` audience), we write an optimistic
         placeholder row at send time — direction='out', `mass_run_id` set,
         a synthetic `message_id` + `temp_id` — so the broadcast shows up in
         the chat cache immediately instead of never. The WS pump skips
         outbound events, so without this the row would otherwise never land.

    List-based audiences (`userLists`) aren't expanded here, so their members
    aren't in `recipient_ids` and NO per-fan row is written for them. What they
    get instead is step 4: the run itself records the body, OF's send stamp and —
    from `audience`, by paging OF's own rosters — the recipient set, so
    the chat engines' history read can materialize that row at READ time for
    the fans who reply (plans/blast-splice; this is the "future WS-pump reconciler" the
    previous version of this docstring was waiting for, arrived by another route:
    the pump never echoes outbound blasts at all).

    `audience` is the request body's own audience block (`user_lists`,
    `excluded_users`, `excluded_user_lists`, `filters`, `online_only`); omit it
    and the recipient set is simply not recorded. `scheduled=True` says OF has
    NOT sent this yet — the run gets no body and no stamp, because there is
    nothing on anyone's thread to splice."""
    if mass_run_id is None:
        return
    from attribution import (
        reconcile_mass_placeholder,
        write_mass_optimistic_rows,
        write_outbound_attribution,
    )
    from event_transcoder import _parse_iso, _to_cents

    created_at = (
        (_parse_iso(result.get("createdAt")) if isinstance(result, dict) else None)
        or datetime.utcnow()
    )
    price_cents = _to_cents(price)

    # ── 1) Real rows for any per-fan ids OF echoed in the response ──────
    per_fan_ids = echoed_of(result)

    echoed_fans: set[int] = set()
    for fan_id, msg_id in per_fan_ids:
        echoed_fans.add(fan_id)
        try:
            await write_outbound_attribution(
                account_id=account_id,
                fan_id=fan_id,
                message_id=msg_id,
                sent_by_employee_id=employee_id,
                body=text or "",
                price_cents=price_cents,
                created_at=created_at,
                mass_run_id=mass_run_id,
            )
            # If an optimistic placeholder for this recipient already landed
            # (e.g. a retry, or a future async reconciler), drop it so the
            # real row is the only one left.
            await reconcile_mass_placeholder(
                account_id=account_id, fan_id=fan_id, mass_run_id=mass_run_id,
            )
        except Exception:
            log.exception(
                "mass attribution write failed (account=%s run=%s fan=%s)",
                account_id, mass_run_id, fan_id,
            )

    # ── 2) Optimistic placeholders for the explicit recipients not echoed ─
    pending = mass_queue_decide.pending_placeholders(recipient_ids, echoed_fans)
    if pending:
        await write_mass_optimistic_rows(
            account_id=account_id,
            fan_ids=pending,
            mass_run_id=mass_run_id,
            sent_by_employee_id=employee_id,
            body=text or "",
            price_cents=price_cents,
            created_at=created_at,
        )

    # ── 3) Close the run. reply_mass_funnel only anchors on status='ok'
    #      runs, and the Mass Messages tab joins the broadcast cache on
    #      queue_id — mirror send_mass_message's close step.
    queue_id = result.get("id") if isinstance(result, dict) else None
    try:
        from db.engine import get_session
        from db.models import MassRun
        async with get_session() as s:
            mr = await s.get(MassRun, mass_run_id)
            if mr is not None:
                mr.status = "ok"
                mr.completed_at = datetime.utcnow()
                if queue_id is not None:
                    mr.queue_id = int(queue_id)
                if not scheduled:
                    # The splice record — mirror send_mass_message's close step.
                    # A SCHEDULED send leaves both NULL: it has not gone out, so
                    # there is no line on anyone's thread yet and a `sent_at` in
                    # the future would put one there.
                    mr.body = text or ""
                    mr.sent_at = created_at
    except Exception:
        log.exception("mass run close failed (account=%s run=%s)", account_id, mass_run_id)

    # ── 4) …and WHO OF sent it to, off OF's rosters (plans/blast-splice A.2).
    # BACKGROUNDED: the crawl is up to ~17 pages on the largest account and a
    # human is watching this response. It fails closed on its own (None →
    # `recipients_json` stays NULL → the run is never spliced), so there is
    # nothing for the request to wait on and nothing it could do about a failure.
    if audience is not None and not scheduled:
        async def _record_recipients() -> None:
            try:
                from attribution import stamp_mass_recipients
                from audiences import resolve_recipients_blocking
                # `_load_client(account_id)`, never `_get_client()`: this runs
                # detached from the request, so the middleware contextvar the
                # bare form reads is gone and it would fall back to the ACTIVE
                # account — another creator's roster, on the wrong run.
                recorded = await asyncio.to_thread(
                    resolve_recipients_blocking, _load_client(account_id),
                    user_lists=audience.get("user_lists") or [],
                    included_users=recipient_ids or [],
                    excluded_users=audience.get("excluded_users") or [],
                    excluded_user_lists=audience.get("excluded_user_lists") or [],
                    filters=audience.get("filters"),
                    online_only=bool(audience.get("online_only")),
                )
                await stamp_mass_recipients(mass_run_id, recorded)
            except Exception:
                log.warning("mass recipient record failed (account=%s run=%s) — "
                            "the blast is sent, it just will not be spliced",
                            account_id, mass_run_id, exc_info=True)
        _spawn_bg(_record_recipients(), f"mass-recipients-{mass_run_id}")


class _MassScheduleBody(BaseModel):
    text: str
    # Optional — omit for an immediate broadcast. /messages/queue is OF's
    # send-now path when no scheduledDate is in the body; with one it
    # becomes the scheduled-send path.
    scheduled_date: str | None = Field(
        None, description="ISO 8601 (e.g. 2026-06-01T18:00:00+00:00); omit to send now",
    )
    # OF's "Save for later": queued with no date (isPublishedWithPeriod: 1),
    # never sent now. Takes the scheduled branch below.
    save_for_later: bool = False
    user_ids: list[int] = Field(default_factory=list)
    user_lists: list[str] = Field(default_factory=list, description="List ids or built-in names like 'fans'")
    excluded_users: list[int] = Field(default_factory=list)
    excluded_user_lists: list[str] = Field(default_factory=list, description="List ids/names to exclude from the audience")
    price: float = Field(0, ge=0)
    locked_text: bool = False
    # int = existing vault id; dict = fresh-upload claim payload from
    # the /upload endpoint's `send_with`. Same shape send_message accepts.
    media_files: list[int | dict] = Field(default_factory=list)
    # Vault ids that ride along unlocked when price > 0. Must be a subset
    # of `media_files`'s numeric ids.
    previews: list[int] = Field(default_factory=list)
    # OF user ids of creators to @-tag in the broadcast (sent as `userTags`).
    # Same picker contract as direct chat sends — ids must come from
    # /api/of/v2/posts/tagged-friend-users or OF will 400.
    tagged_users: list[int] = Field(default_factory=list)
    # Giphy id — forwarded as top-level `giphyId` to OF. Multi-GIF mass
    # broadcasts fan out client-side as separate calls.
    giphy_id: str | None = Field(
        None,
        description="Giphy GIF id forwarded to OF as top-level `giphyId`.",
    )
    # Native audience filter — forwarded to OF as the top-level `filters` object.
    # `online_only=True` (or `filters={"online": 1}`) targets fans currently
    # online at send time. Combine with `user_lists=["fans"]` to blast every
    # online fan. Mirrors OF web's online broadcast.
    online_only: bool = False
    filters: dict | None = None
    # DB-sourced audience: inject the fan ids we exchanged a message with in the
    # last `recent_chat_hours` (newest first, capped to `recent_chat_limit`).
    # Resolved server-side from the local `messages` table and MERGED into
    # `user_ids` — no OF call needed. Bots + blacklisted fans are dropped.
    recent_chat_hours: float | None = Field(
        None, gt=0, description="Target fans chatted with in the last N hours (from local DB)",
    )
    recent_chat_limit: int | None = Field(
        None, gt=0, description="Cap the recent-chat audience to the N most-recent fans",
    )
    # DB-sourced EXCLUSIONS — drop fans from the audience based on recent
    # activity (resolved server-side, merged into `excluded_users`).
    #   exclude_replied_hours: fans we sent an OUTBOUND message to in the last
    #     N hours (i.e. "already replied") — don't re-blast them.
    #   exclude_inbound_hours: fans who messaged us INBOUND in the last N hours
    #     — the extra "2h inbound" filter.
    exclude_replied_hours: float | None = Field(
        None, gt=0, description="Exclude fans we replied to (outbound) in the last N hours",
    )
    exclude_inbound_hours: float | None = Field(
        None, gt=0, description="Exclude fans who messaged us (inbound) in the last N hours",
    )
    # Target fans with UNREAD messages (the OF "Unread" inbox tab), capped at
    # `unread_limit`. Resolved via OF `GET /chats?filter=unread` and MERGED into
    # `user_ids`. Great for "reply blast" to fans waiting on us.
    unread_limit: int | None = Field(
        None, gt=0, le=1000, description="Target up to N fans with unread messages",
    )
    # Auto-unsend: N hours after an immediate broadcast goes out, unsend it from
    # every recipient. OF has no native timer, so we enqueue a one-shot
    # `unsend_messages` job at send_time + N hours (the A12 automation calls
    # DELETE /messages/queue/{id} — the forever-window mass unsend). Ignored for
    # scheduled sends (unsending a future send is just a cancel).
    unsend_after_hours: float | None = Field(
        None, gt=0, le=8760, description="Auto-unsend the broadcast N hours after it sends",
    )
    # Funnel anchor — stamps the minted `mass_runs` row with this
    # `mass_message_funnels.id` so the reply_mass_funnel automation discovers
    # repliers and walks the funnel's reply/PPV steps. Send-now only (a
    # scheduled run is closed by OF later, so it never reaches 'ok' here).
    funnel_id: int | None = Field(
        None, gt=0, description="mass_message_funnels.id to walk repliers through",
    )
    # Online-fans thresholds (Infloww's Total spent / Tipped over / Subscribed
    # over / Expired over), resolved from our own records by
    # `audiences.threshold_fan_ids`. Any one set turns the audience into the
    # explicit ids of the picked lists' members and `user_ids` that clear them
    # all (online now, with `online_only`), at most THRESHOLD_IDS_MAX — the
    # lists and the OF online filter drop out. A list OF won't page → 422.
    min_total_spent: float | None = Field(None, gt=0, description="Only fans who spent at least $N")
    min_tipped: float | None = Field(None, gt=0, description="Only fans who tipped at least $N")
    subscribed_over_days: float | None = Field(None, gt=0, description="Only fans subscribed N+ days")
    expired_over_days: float | None = Field(None, gt=0, description="Only fans expired N+ days ago")

    def has_thresholds(self) -> bool:
        return bool(self.min_total_spent or self.min_tipped
                    or self.subscribed_over_days or self.expired_over_days)


@router.post("/api/of/v2/messages/queue")
async def of_send_or_schedule_mass(
    request: Request,
    body: _MassScheduleBody = Body(...),
):
    """POST /messages/queue — broadcasts a mass message to many fans.
    With `scheduled_date` it's a scheduled send; without, it's immediate.
    `user_ids` for explicit fans OR `user_lists` for list-based audience.

    Attribution: mint a `mass_runs` row up front, then walk the
    OF response for per-fan ids and write attribution rows. This is the
    path the Next UI broadcast composer actually hits."""
    # DB-sourced audience: merge "chatted in the last N hours" fan ids into the
    # explicit user_ids before anything else, so mass-run attribution + the OF
    # send both see the full recipient set.
    # R1/R2: also resolve whenever a funnel_id is present (even with no other
    # audience knob) — else a plain funnel launch skips the resolver entirely and
    # never dedups answerers (the composer used to gate only on recent/exclude/
    # unread). exclude_funnel_responders drops fans who already answered THIS
    # funnel; for explicit ids they leave user_ids, for OF-native list/online
    # audiences they ride the Auto_Exclude list path below (excluded_users).
    # Run UNCONDITIONALLY (not just when an audience knob is set): the resolver
    # ALSO applies the always-on MASSdmEXCLUDE opt-out list + not-yet-fired
    # queued-send dedup, so a plain composer blast still skips an excluded /
    # already-queued fan. The client is only needed for the OF "Unread" lookup,
    # so build it only when unread_limit is set.
    _thresholds = body.has_thresholds()
    _online_now = bool(body.online_only or (body.filters or {}).get("online"))
    _refusal = mass_queue_decide.threshold_refusal(
        body.scheduled_date, body.save_for_later, _thresholds, _online_now,
        body.expired_over_days)
    if _refusal is not None:
        raise HTTPException(422, _refusal)
    from audiences import (MASSDMEXCLUDE_LIST, THRESHOLD_IDS_MAX,
                           AudienceUnknown, resolve_mass_audience)
    _aid = _resolve_account_id(request)
    try:
        resolved = await resolve_mass_audience(
            _aid,
            included_users=body.user_ids,
            excluded_users=body.excluded_users,
            recent_chat_hours=body.recent_chat_hours,
            recent_chat_limit=body.recent_chat_limit,
            exclude_replied_hours=body.exclude_replied_hours,
            exclude_inbound_hours=body.exclude_inbound_hours,
            exclude_funnel_responders=body.funnel_id,  # R1/R2 answered-once dedup
            unread_limit=body.unread_limit,
            # Every blast, priced or not, skips the MASSdmEXCLUDE opt-out list.
            exclude_list_name=MASSDMEXCLUDE_LIST,
            min_spent_cents=round(body.min_total_spent * 100) if body.min_total_spent else None,
            min_tips_cents=round(body.min_tipped * 100) if body.min_tipped else None,
            subscribed_over_days=body.subscribed_over_days,
            expired_over_days=body.expired_over_days,
            online_now=_thresholds and _online_now,
            # Read only by a thresholded send: the lists it narrows, and the
            # excluded lists it subtracts (OF's excludedLists is verified on
            # list audiences only, and this send becomes explicit userIds).
            user_lists=body.user_lists if _thresholds else None,
            excluded_user_lists=body.excluded_user_lists if _thresholds else None,
            client=_get_client() if (body.unread_limit or _thresholds) else None,
        )
    except AudienceUnknown as e:
        raise HTTPException(422, str(e))
    body.user_ids = resolved["included_users"]
    body.excluded_users = resolved["excluded_users"]
    if _thresholds:
        # The resolved ids ARE the audience: OF unions userLists with
        # userIds, so a list left in would re-add every fan below the bar.
        _refusal = mass_queue_decide.threshold_count_refusal(
            len(body.user_ids), THRESHOLD_IDS_MAX)
        if _refusal is not None:
            raise HTTPException(422, _refusal)
        body.user_lists = []
        body.online_only = False
        body.filters = None
    _skipped_answered = resolved.get("skipped_funnel_responders") or []
    _answered_total = int(resolved.get("funnel_responders_total") or 0)
    # Excluded ids must leave `user_ids` HERE too — of_client subtracts them
    # from the wire `userIds` (OF has no per-user exclude field), so if we left
    # them in `body.user_ids` the mass_runs recipient_count + the optimistic
    # `messages` rows _close_mass_run writes would be PHANTOM (rows for fans OF
    # never messaged), and those outbound rows would then poison the contact
    # guard. Mirror the of_client subtraction so our record matches the send.
    body.user_ids = mass_queue_decide.strip_excluded(body.user_ids, body.excluded_users)
    # OF cannot exclude individual ids from a list/online audience — the
    # `excludedUsers` body field doesn't exist (verified live 2026-06-12: it was
    # silently dropped and excluded fans got the blast). Mirror the ids into the
    # per-account Auto_Exclude OF list, which OF honors via `excludedLists`.
    # Explicit `user_ids` need no list — they're already stripped just above.
    # Done under the shared per-account broadcast lock, held from the sync
    # through the OF POST below (as automation sends hold it): a concurrent
    # automation send or Auto_Exclude refresh can't rewrite the list between
    # this blast's sync and OF reading its `excludedLists`. Errors bubble up
    # (500) — a broadcast without its guard is the bug itself.
    _later = bool(body.scheduled_date or body.save_for_later)
    _held = (_exclude_list_held(_aid, body.excluded_users) if mass_queue_decide.needs_exclude_list(
        body.excluded_users, body.user_lists, body.online_only, body.filters) else contextlib.nullcontext())
    async with _held as auto_lid:
        if auto_lid is not None and auto_lid not in (body.excluded_user_lists or []):
            body.excluded_user_lists = [*(body.excluded_user_lists or []), auto_lid]
        account_id, employee_id, mass_run_id = await _open_mass_run(
            request,
            user_lists=body.user_lists,
            included_users=body.user_ids,
            excluded_users=body.excluded_users,
            excluded_user_lists=body.excluded_user_lists,
            funnel_id=body.funnel_id,
        )
        client = _get_client()
        # OF throttles consecutive broadcast POSTs with a 400 "Please allow 10
        # seconds". Every automation absorbs that already (of_write_paced pre-spaces
        # >=11s, of_write_with_retry re-tries once after an async pause); this
        # handler — the one the Next composer hits, with a human watching — did not.
        # A blast landing within ~10s of an automation's blast failed AFTER the
        # audience resolve, the exclude sync and the mass_runs mint, and the manual
        # resubmit re-paid all of it.
        #
        # Retry only, no pacing: pacing would tax the common un-throttled case and
        # this is the interactive path. Safe to re-send because the retry fires only
        # on OF's rate-limit 400 — a POST OF refused, so nothing was created. Every
        # other error still surfaces unchanged. Both kinds are wrapped: scheduled
        # and immediate are the same throttled endpoint. The function-local import
        # mirrors this module's other automation_executor uses (that module must not
        # import server).
        from automation_executor import of_write_with_retry
        shared = dict(
            text=body.text,
            user_lists=body.user_lists,
            excluded_users=body.excluded_users,
            excluded_user_lists=body.excluded_user_lists,
            price=body.price,
            locked_text=body.locked_text,
            media_files=body.media_files,
            previews=body.previews,
            tagged_users=body.tagged_users,
            giphy_id=body.giphy_id,
            filters=body.filters,
            online_only=body.online_only,
        )
        if _later:
            post, extra = client.schedule_mass_message, dict(
                scheduled_date=body.scheduled_date,
                save_for_later=body.save_for_later and not body.scheduled_date,
                user_ids=body.user_ids)
        else:
            post, extra = client.send_mass_message, dict(included_users=body.user_ids)
        result = await of_write_with_retry(lambda: _proxy(lambda: post(**shared, **extra)))
    # A funnel-linked send only works if the reply-walker runs on this account —
    # without it the opener goes out and no reply-check ever fires. Best-effort:
    # never blocks the broadcast (nor holds its lock).
    if body.funnel_id and mass_run_id is not None:
        try:
            from funnels_api import ensure_funnel_walker
            await ensure_funnel_walker(account_id)
        except Exception:
            log.exception("funnel walker ensure failed (account=%s) — enable "
                          "Reply-walking in My Automations > Auto Funnel", account_id)
    # Scheduled sends don't produce per-fan rows now — OF fires the actual
    # messages later. The mass_run_id is stamped on `mass_runs` so the
    # WS-pump reconciler (TODO inside _close_mass_run) can match the
    # eventual arrivals.
    if not _later:
        await _close_mass_run(
            account_id=account_id,
            employee_id=employee_id,
            mass_run_id=mass_run_id,
            text=body.text,
            price=body.price,
            result=result,
            recipient_ids=body.user_ids,
            audience={"user_lists": body.user_lists,
                      "excluded_users": body.excluded_users,
                      "excluded_user_lists": body.excluded_user_lists,
                      "filters": body.filters,
                      "online_only": body.online_only},
            # Only immediate sends close here (a `_later` run never does — see
            # §8 of plans/blast-splice, that run stays 'running' forever and is
            # its own bug), so this is always False. Passed explicitly anyway:
            # the day a scheduled run learns to close itself, the flag is
            # already where it belongs.
            scheduled=False,
        )
        # Auto-unsend timer: schedule a one-shot `unsend_messages` job for the
        # forever-window mass unsend (DELETE /messages/queue/{id}) at send_time
        # + N hours. Picked up by the automation supervisor when due.
        queue_id = result.get("id") if isinstance(result, dict) else None
        if body.unsend_after_hours and queue_id:
            from automation_executor import enqueue_job
            run_at = datetime.utcnow() + timedelta(hours=body.unsend_after_hours)
            job_id = await enqueue_job(
                account_id, "unsend_messages",
                payload={"targets": [{"queue_id": int(queue_id),
                                      "mass_run_id": mass_run_id}]},
                run_at=run_at,
                created_by_employee_id=employee_id,
            )
            if isinstance(result, dict):
                result["_auto_unsend_at"] = run_at.isoformat() + "Z"
                result["_auto_unsend_job_id"] = job_id
    if mass_run_id is not None and isinstance(result, dict):
        result.setdefault("_mass_run_id", mass_run_id)
    if isinstance(result, dict) and (_answered_total or _skipped_answered):
        # R1/R2 surfacing: how many known answerers of this funnel were excluded
        # from the send (total), and the precise ids removed from an explicit-id
        # audience. The UI prints "N already answered — skipped".
        result["_skipped_already_answered"] = _answered_total or len(_skipped_answered)
        result["_skipped_already_answered_ids"] = _skipped_answered
    return result

class _EditQueuedMessageBody(BaseModel):
    """PUT /api/of/v2/messages/queue/{id}: a queued mass message saved in
    place. A schedule (`scheduled_date`) or `save_for_later` is required, so
    an edit can never send the message at once (that is Message now)."""
    text: str
    scheduled_date: str | None = None
    save_for_later: bool = False
    user_ids: list[int] = Field(default_factory=list)
    user_lists: list[str] = Field(default_factory=list)
    excluded_user_lists: list[str] = Field(default_factory=list)
    price: float = Field(0, ge=0)
    locked_text: bool = False
    media_files: list[int | dict] = Field(default_factory=list)
    previews: list[int] = Field(default_factory=list)
    tagged_users: list[int] = Field(default_factory=list)


@router.post("/api/of/v2/messages/queue/later")
async def of_save_mass_for_later(request: Request, body: _MassScheduleBody = Body(...)):
    """A mass message saved for later (OF's Save for later: queued with no
    date). POST /messages/queue with `save_for_later` does the same; this route
    is what OF Manager calls, so a relay that predates `save_for_later` answers
    405 instead of ignoring the field and sending the message at once."""
    body.save_for_later = True
    body.scheduled_date = None
    return await of_send_or_schedule_mass(request, body)


@router.get("/api/of/v2/messages/queue/{queue_id:int}")
def of_queued_message(queue_id: int):
    """One queued mass message (scheduled or saved for later), as OF's Edit
    message loads it: GET /messages/queue/{id}?format=scheduled."""
    return _proxy(lambda: _get_client().queued_message(queue_id))


@router.put("/api/of/v2/messages/queue/{queue_id:int}")
def of_edit_queued_message(queue_id: int, body: _EditQueuedMessageBody = Body(...)):
    """Save a queued mass message in place (OF Manager's Edit message, from the
    Queue): OF's PUT /messages/queue/{id}. A new `scheduled_date` reschedules."""
    if not body.scheduled_date and not body.save_for_later:
        raise HTTPException(422, "an edited queued message needs scheduled_date or save_for_later")
    return _proxy(lambda: _get_client().edit_queued_message(
        queue_id, text=body.text, scheduled_date=body.scheduled_date,
        save_for_later=body.save_for_later and not body.scheduled_date,
        user_ids=body.user_ids, user_lists=body.user_lists,
        excluded_user_lists=body.excluded_user_lists, price=body.price,
        locked_text=body.locked_text, media_files=body.media_files,
        previews=body.previews, tagged_users=body.tagged_users,
    ))


@router.delete("/api/of/v2/messages/queue/{queue_id}")
async def of_cancel_scheduled(request: Request, queue_id: int):
    """Cancel a previously scheduled message or unsend a mass broadcast.

    Both code paths share OF's wire endpoint:
      • scheduled (future) → cancel before it fires
      • mass broadcast (past) → unsend from EVERY recipient (no window)

    On success we flip `is_canceled=True` in the local mass-broadcast
    cache so the Settings → Mass messages list reflects the new state
    without waiting for the next refresh.

    On a Fansly Creator this is ALSO the scheduled-POST cancel: the Fansly
    shim's `cancel_scheduled` is Fansly's `POST /post/scheduled/{id}/cancel`,
    so `queue_id` is a post id from `GET /api/of/v2/schedules` (the Fansly
    Manager's Scheduled Posts page, roadmap 8.1). The bookkeeping below then
    finds nothing to mark. Locked by test_fansly_cancel_scheduled_route.py."""
    import mass_broadcast_cache as cache
    resp = await asyncio.to_thread(_proxy, lambda: _get_client().cancel_scheduled(queue_id))
    try:
        account_id = _resolve_account_id(request)
    except Exception as e:  # authed route — unreachable in practice
        log.warning("cancel bookkeeping skipped, account unresolved: %s", e)
        return resp

    # Three independent bits of local bookkeeping. OF has already canceled the
    # queue, so none of them may 500 the caller — and none may be skipped
    # because an earlier one failed, hence one guard each.
    try:
        await cache.mark_canceled(account_id, queue_id)
    except Exception as e:
        log.warning("mass_broadcast_cache mark_canceled failed: %s", e)
    try:
        # #R4: a manual mass unsend also closes funnel discovery for that run —
        # stop enrolling NEW repliers off the deleted mass (the walker keeps
        # advancing already-engaged fans until a purchase halts them).
        from audiences import close_funnel_discovery_for_queue
        await close_funnel_discovery_for_queue(account_id, queue_id=queue_id)
    except Exception as e:
        log.warning("close_funnel_discovery failed queue_id=%s: %s", queue_id, e)
    try:
        # Same mirror flip as the per-chat unsend above, one broadcast wide:
        # every recipient's mirror row would otherwise re-seed as an empty
        # bubble on their next chat open. Purchasers and funnel follow-ups
        # are spared inside mark_queue_unsent — they stay live on OF.
        from messages import mark_queue_unsent
        await mark_queue_unsent(account_id, queue_id)
    except Exception as e:
        log.warning("queue unsend mirror flip failed queue_id=%s: %s", queue_id, e)
    return resp
