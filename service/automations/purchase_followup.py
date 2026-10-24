"""service/automations/purchase_followup.py — message a fan after he buys a PPV.

Smart Messages' "Purchased" Trigger (Infloww's "Purchases" card, "Follow up with
fans who purchased a PPV"). Owner ruling N2, position B (2026-10-18): built on the
existing send path, not a new one.

Trigger (SWEEP): no new OnlyFans poller. The purchase signal is the one the relay
already keeps: `messages.is_paid` + `purchased_at` on an outbound priced message,
flipped within ~30s by `purchase_notifications` (OF's purchases feed, at the
notification's own time) and, later, by the ledger's `transaction_ingest` linker.
A `purchase_followup` automation rule with a 60s cadence runs this sweep; the
rule's steps are the config. Only
purchase_followup_config_api switches it ON or edits it (owner-only to switch
on, and it stamps `enabled_at` on every off→on). The generic automation-rules
routes refuse the kind except to switch it off or delete it, and a settings
import always lands it off.

  steps (written by purchase_followup_config_api):
    enabled        mirror of the switch; the sweep refuses to send without it
    text           the message sent after a purchase; `{name}` is the fan's name
                   (else "babe"), word-restricted on the way out
    delay_range    null = send immediately, else [a, b]: wait a random a～b
                   minutes (1..60) after each purchase, drawn per purchase so
                   every sweep waits the same (smart_message_extras). A rule
                   saved before the range existed keeps its `delay_minutes` d
                   EXACTLY (a fixed d minutes, up to a day; 0 = immediately)
                   until the owner picks a range.
    frequency      "every" (Infloww's default for the Trigger): one message per
                   purchase, but never a second within `_EVERY_FLOOR_H` (2h) of
                   the last — Infloww's own default for it excludes fans sent a
                   message in the last 2 hours. "once": one message per fan,
                   ever. Purchases inside the floor, or by a fan already thanked
                   once, are claimed SILENTLY. A rule saved before the key
                   existed keeps the floor it was built with: one per fan per
                   `_LEGACY_FLOOR_H` (24h), until the editor saves it.
    media_ids, price_cents, starts_at, ends_at, unsend_minutes
                   smart_message_extras: the media (a PPV at price_cents) sent
                   with the text (a fan who already owns any of it gets the
                   text alone, free), the Effective / Expiry window (nothing bought
                   before starts_at is chased; nothing is sent past ends_at) and
                   Auto-unsend (free messages only).
    enabled_at     purchases made before the switch last went on are never chased
  At most `_LIMIT` (25) fans are messaged per sweep; the rest wait for the next.
  job payload: only `dry_run` is read (resolve candidates, send nothing, claim
  nothing). Everything else comes from the rule as it is NOW, so a job queued
  before a switch-off — or replayed by a retry — sends nothing.

Safety:
  • Off by default: no rule → nothing materializes; no switched-on rule, no
    `enabled`, no text or no readable `enabled_at` → the sweep is skipped.
  • Only purchases it can PROVE are inside its window — bought after the later of
    `enabled_at` and 24h before the delay — by one of: the PPV was itself sent
    inside the window (a purchase follows its send); the purchases feed reported
    a purchase time inside it (`purchase_notices`); or the ledger holds a
    cleared or pending transaction for it inside it. A `purchased_at` that only
    says when somebody NOTICED a sale is not enough. Each proof is read through
    its own time index, so a sweep never walks the account's outbound history.
  • Never its own thank-you: a priced row this sender sent (automation_kind
    `purchase_followup`) is not a purchase to thank for, so a paid thank-you
    that is bought never sets off another.
  • Never a mass PPV's placeholder row (ids in attribution's 5e15 band, one id
    shared by every recipient): only OF's real per-fan row is a purchase. A
    purchase the ledger linked to a placeholder is followed up once adoption
    folds it into the real row, so it is claimed exactly once.
  • At most one message per purchase: each (fan, purchased message) is CLAIMED
    in `purchase_followup_claims` (INSERT … ON CONFLICT DO NOTHING) before the
    wire. The claim is handed back only when OnlyFans provably created nothing
    (its rate-limit refusal); any other failure, a crash or a 200 with no id
    keeps it.
  • The anti-spam floor, whatever the frequency: at most one message per fan per
    `floor_hours` (2h; 24h on a rule saved before `frequency`), however many PPVs he unlocks (a purchase by a fan thanked
    inside that span is claimed SILENTLY, no message), purchases claimed in one
    sweep share one message, and after a send the fan rests a SHORT `_COOLDOWN_S`: the
    rest is shared by every sender, and the drips' 10 minutes would silence the
    AI seller's post-buy follow-up. The rest only ever lengthens a pause, never
    shortens one (a 72h decline pause stays 72h).
  • Gated (audience_include): the include-only audience, the hard skip list, a
    muted creator, the global blacklist, a paused fan and the per-fan send lease
    all stand between a purchase and the wire. Sends go through `of_write_paced`
    (11s per-account spacing, send_purpose="gated").
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import automation_executor as ax        # _make_client / of_write_paced / lease seams
import smart_message_extras as extras
from attribution import _MASS_PLACEHOLDER_BASE, write_outbound_attribution
from automation_registry import register
from automations._common import (
    apply_word_restriction, load_hard_skip_ids, quarantine_if_undeliverable,
    send_dropping_bad_media_sync, should_skip_muted_creator, skip_unreachable_fan,
    substitute_placeholders, template_fan_name,
)
from db.engine import get_session
from db.models import (
    AutomationRule, Blacklist, Fan, Message, PurchaseFollowupClaim, PurchaseNotice,
    Transaction,
)

log = logging.getLogger("of-relay.automation.purchase_followup")

KIND = "purchase_followup"
_SEND_PURPOSE = "gated"
# Purchases older than this are not chased, even inside the enable window: the
# ledger linker can land a purchase hours late, but a day-old "thank you" reads
# as a bot catching up.
_MAX_AGE_HOURS = 24
_LIMIT = 25                      # fans messaged per sweep; the rest wait for the next
# At most one canned thank-you per fan per this many hours, however many PPVs he
# unlocks: Infloww's default for the Trigger (`resetTemplateDefaultData`,
# index.9f50f370.js @14445199, haveBeenSentMessage.hours=2).
_EVERY_FLOOR_H = 2
# The floor a rule saved before `frequency` existed was built with, and keeps.
_LEGACY_FLOOR_H = 24
# Infloww's defaults for the Trigger (@14445102): after a random 1～3 minutes, every time.
DEFAULT_DELAY = [1, 3]
DEFAULT_FREQUENCY = "every"
STORED_FREQUENCY = "every"       # a stored rule without the key: every purchase, 24h floor
_LEGACY_DELAY_MAX_MIN = 24 * 60  # the old `delay_minutes` cap
# Rest after a thank-you: long enough that no drip lands on top of it, short like
# the chat engines' own, so the AI seller's post-buy follow-up (one job, 90-240s
# after the unlock, dropped if the fan is resting) still goes out.
_COOLDOWN_S = 45
# Ledger rows that mean the money is (or will be) there; a refund or chargeback
# is not proof of a purchase. The same set transaction_ingest's linker trusts.
_PROOF_STATUSES = ("cleared", "pending")


def delay_of(steps: dict) -> list[int] | None:
    """The rule's random delay: its `delay_range`, else the single
    `delay_minutes` a rule saved before the range existed carries, kept exact
    ([d, d], up to its old one-day cap — not squeezed into the range's 1..60)."""
    if "delay_range" in steps:
        return extras.delay_range(steps)
    d = steps.get("delay_minutes")
    if isinstance(d, bool) or not isinstance(d, int) or d <= 0:
        return None
    d = min(d, _LEGACY_DELAY_MAX_MIN)
    return [d, d]


def floor_hours(steps: dict) -> int:
    """Hours between two thank-yous to one fan: Infloww's 2 for a rule saved
    with a `frequency`, the old 24 for one saved before the key existed."""
    return _EVERY_FLOOR_H if steps.get("frequency") in extras.FREQUENCIES else _LEGACY_FLOOR_H


def _parse_iso(raw) -> datetime | None:
    """An ISO stamp as naive UTC, or None when absent or unreadable."""
    try:
        ts = datetime.fromisoformat(str(raw)) if raw else None
    except ValueError:
        return None
    if ts is not None and ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts


async def _live_rule(account_id: str) -> dict | None:
    """Steps of the account's switched-on rule as it is NOW, or None when no rule
    of the kind is on. Several rows: the first on by id, as
    automation_rules_api.ensure_kind_rule wakes. The cadence is not read: the
    config route always writes 60s and nothing in a sweep depends on it."""
    async with get_session() as s:
        rule = (await s.execute(
            select(AutomationRule).where(
                AutomationRule.account_id == str(account_id),
                AutomationRule.kind == KIND,
                AutomationRule.is_enabled.is_(True),
            ).order_by(AutomationRule.id).limit(1)
        )).scalar_one_or_none()
    if rule is None:
        return None
    try:
        steps = json.loads(rule.steps_json or "{}")
    except (TypeError, ValueError):
        return {}
    return steps if isinstance(steps, dict) else {}


async def _purchases(account_id: str, *, now: datetime, start: datetime,
                     delay: list[int] | None) -> dict[int, list[int]]:
    """{fan_id: [purchased message ids]} for outbound priced messages bought
    after `start` whose own random delay (drawn from `delay`) has run out and
    which are at most a day past it, oldest purchase first — only those whose real
    purchase time is PROVEN inside the window: the PPV was itself sent inside it
    (a purchase cannot precede its send), the purchases feed reported a purchase
    time inside it, or the ledger holds a live transaction for it inside it. A
    `purchased_at` alone may be when a poll noticed the sale. Mass placeholder
    rows (one id shared by every recipient) are never a purchase.

    One read per proof, each bounded below by its own indexed time column
    (messages by ix_messages_dir_created, the ledger by ix_tx_account_time, the
    notices by ix_purchase_notices_time; messages joined by primary key), so the
    cost follows the window, not the account's history."""
    aid = str(account_id)
    lo_s, hi_s = (delay[0] * 60, delay[1] * 60) if delay else (0, 0)
    # The widest window any purchase's delay can put it in; each is cut to its own below.
    ready_before = now - timedelta(seconds=lo_s)
    fresh_after = max(start, now - timedelta(seconds=hi_s, hours=_MAX_AGE_HOURS))
    bought = (
        Message.account_id == aid,
        Message.direction == "out",
        Message.message_id < _MASS_PLACEHOLDER_BASE,
        Message.price_cents > 0,
        Message.is_paid.is_(True),
        # Never its own (paid) thank-you: that would thank him for the thank-you.
        or_(Message.automation_kind.is_(None), Message.automation_kind != KIND),
        Message.purchased_at.is_not(None),
        Message.purchased_at <= ready_before,
        Message.purchased_at >= fresh_after,
    )
    cols = (Message.fan_id, Message.message_id, Message.purchased_at)
    reads = [
        # Sent inside the window.
        select(*cols).where(*bought, Message.created_at >= fresh_after),
        # The ledger's own time.
        select(*cols).select_from(Transaction).join(Message, and_(
            Message.account_id == Transaction.account_id,
            Message.fan_id == Transaction.fan_id,
            Message.message_id == Transaction.message_id,
        )).where(
            Transaction.account_id == aid,
            Transaction.occurred_at >= fresh_after,
            Transaction.occurred_at <= ready_before,
            Transaction.status.in_(_PROOF_STATUSES),
            *bought,
        ),
        # The purchases feed's own time.
        select(*cols).select_from(PurchaseNotice).join(Message, and_(
            Message.account_id == PurchaseNotice.account_id,
            Message.fan_id == PurchaseNotice.fan_id,
            Message.message_id == PurchaseNotice.message_id,
        )).where(
            PurchaseNotice.account_id == aid,
            PurchaseNotice.notified_at >= fresh_after,
            PurchaseNotice.notified_at <= ready_before,
            *bought,
        ),
    ]
    found: dict[tuple[int, int], datetime] = {}
    async with get_session() as s:
        for q in reads:
            for fid, mid, at in (await s.execute(q)).all():
                if fid is not None and mid is not None:
                    found[(int(fid), int(mid))] = at
    out: dict[int, list[int]] = {}
    for (fid, mid), at in sorted(found.items(), key=lambda kv: (kv[1], kv[0])):
        due = at + timedelta(seconds=extras.delay_seconds(delay, aid, fid, mid))
        if due <= now and due >= now - timedelta(hours=_MAX_AGE_HOURS):
            out.setdefault(fid, []).append(mid)
    return out


async def _thanked_recently(account_id: str, fan_ids: list[int],
                            since: datetime | None) -> set[int]:
    """Fans among `fan_ids` sent a thank-you (a non-silent claim) since `since`
    (None: ever)."""
    if not fan_ids:
        return set()
    when = () if since is None else (PurchaseFollowupClaim.created_at >= since,)
    async with get_session() as s:
        return {int(f) for f in (await s.execute(
            select(PurchaseFollowupClaim.fan_id).where(
                PurchaseFollowupClaim.account_id == str(account_id),
                PurchaseFollowupClaim.fan_id.in_(fan_ids),
                PurchaseFollowupClaim.silent.is_(False),
                *when,
            ).distinct())).scalars().all()}


async def _claimed(account_id: str, msg_ids: list[int]) -> set[tuple[int, int]]:
    """{(fan_id, message_id)} already claimed among `msg_ids`."""
    if not msg_ids:
        return set()
    async with get_session() as s:
        return {(int(f), int(m)) for f, m in (await s.execute(
            select(PurchaseFollowupClaim.fan_id, PurchaseFollowupClaim.purchased_message_id)
            .where(PurchaseFollowupClaim.account_id == str(account_id),
                   PurchaseFollowupClaim.purchased_message_id.in_(msg_ids)))).all()}


async def _claim(account_id: str, fan_id: int, msg_ids: list[int], *,
                 silent: bool = False) -> list[int]:
    """Claim the fan's `msg_ids` in their own transaction, BEFORE the send
    (`silent`: claimed with no send at all). Returns the ids THIS call claimed: a
    row that already existed changes nothing (rowcount 0), so two sweeps racing
    one purchase can never both win it."""
    won: list[int] = []
    async with get_session() as s:
        for mid in msg_ids:
            res = await s.execute(
                sqlite_insert(PurchaseFollowupClaim)
                .values(account_id=str(account_id), fan_id=int(fan_id),
                        purchased_message_id=int(mid), silent=bool(silent),
                        created_at=datetime.utcnow())
                .on_conflict_do_nothing(
                    index_elements=["account_id", "fan_id", "purchased_message_id"]))
            if res.rowcount:
                won.append(int(mid))
        await s.commit()
    return won


async def _release(account_id: str, fan_id: int, msg_ids: list[int]) -> None:
    """Hand claims back — ONLY when OnlyFans provably created nothing."""
    async with get_session() as s:
        await s.execute(delete(PurchaseFollowupClaim).where(
            PurchaseFollowupClaim.account_id == str(account_id),
            PurchaseFollowupClaim.fan_id == int(fan_id),
            PurchaseFollowupClaim.purchased_message_id.in_(msg_ids)))
        await s.commit()


async def _rest(account_id: str, fan_id: int) -> None:
    """Rest the fan `_COOLDOWN_S` after a thank-you, as one conditional write that
    only ever LENGTHENS his pause: a longer one (a decline's 72h) is left as is.
    (The executor's start_fan_cooldown overwrites whatever pause is there.)"""
    now = datetime.utcnow()
    until = now + timedelta(seconds=_COOLDOWN_S)
    async with get_session() as s:
        await s.execute(update(Fan).where(
            Fan.account_id == str(account_id),
            Fan.fan_id == int(fan_id),
            or_(Fan.automation_paused_until.is_(None),
                Fan.automation_paused_until < until),
        ).values(automation_paused_until=until, updated_at=now))
        await s.commit()


def _skip(reason: str) -> dict:
    return {"status": "skipped", "reason": reason, "sent": 0}


@register(KIND)
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    cfg = await _live_rule(account_id)
    if cfg is None:
        return _skip("disabled")
    if cfg.get("enabled") is not True:
        return _skip("disabled")
    template = str(cfg.get("text") or "").strip()
    if not template:
        return _skip("no_text")
    enabled_at = _parse_iso(cfg.get("enabled_at"))
    if enabled_at is None:
        return _skip("no_enabled_at")
    dry_run = bool((payload or {}).get("dry_run"))
    now = datetime.utcnow()
    outside = extras.window_skip(cfg, now)
    if outside:
        return _skip(outside)
    media, price_cents = extras.media_and_price(cfg)
    unsend_after = extras.unsend_minutes(cfg)
    once = extras.frequency(cfg, STORED_FREQUENCY) == "once"

    # enabled_at is restamped on every off→on by the config route, the only route
    # that switches the kind on; the Effective date, when set, starts it later still.
    start = max(enabled_at, extras.window_start(cfg) or enabled_at)
    bought = await _purchases(account_id, now=now, start=start, delay=delay_of(cfg))

    # Include-only audience, at the candidate seam (classification: gated).
    import audience_include as _audiences
    audience_stats: dict = {}
    kept = set(await _audiences.filter_candidates(
        account_id, list(bought), kind=KIND, stats=audience_stats))

    hard_skip = await load_hard_skip_ids(account_id)
    fan_ids = list(bought) or [-1]
    async with get_session() as s:
        # Blacklist is GLOBAL (fan_id only); asked only about this sweep's buyers.
        blacklist = {int(x) for x in (await s.execute(
            select(Blacklist.fan_id).where(Blacklist.fan_id.in_(fan_ids)))).scalars().all()}
        fans = {int(f.fan_id): f for f in (await s.execute(
            select(Fan).where(Fan.account_id == str(account_id),
                              Fan.fan_id.in_(fan_ids)))).scalars().all()}
        s.expunge_all()
    done = await _claimed(account_id, [m for mids in bought.values() for m in mids])
    thanked = await _thanked_recently(
        account_id, list(bought), None if once else now - timedelta(hours=floor_hours(cfg)))

    plans: list[tuple[int, list[int]]] = []
    folds: list[tuple[int, list[int]]] = []
    skipped = 0
    for fid, mids in bought.items():
        pending = [m for m in mids if (fid, m) not in done]
        if not pending:
            continue
        if fid in thanked:
            folds.append((fid, pending))     # inside the floor, or thanked once: claim, never send
            continue
        fan = fans.get(fid)
        paused = fan is not None and fan.automation_paused_until is not None \
            and fan.automation_paused_until > now
        if (fan is None or fid not in kept or fid in hard_skip or fid in blacklist
                or paused or should_skip_muted_creator(fan)):
            skipped += 1
            continue
        plans.append((fid, pending))

    if dry_run:
        return {"status": "ok", "dry_run": True, "would_send": min(len(plans), _LIMIT),
                "would_fold": len(folds), "skipped": skipped,
                "capped": max(0, len(plans) - _LIMIT), "sent": 0, **audience_stats}

    # A paid thank-you never re-sells media the fan already owns (ppv_send's
    # ownership guard): an owner gets the text alone, free.
    owned = await extras.owners(account_id, media, price_cents, [f for f, _ in plans])
    folded = owners_sent = 0
    for fid, pending in folds:
        if await _claim(account_id, fid, pending, silent=True):
            folded += 1
    sent = no_id = errors = busy = unreachable = capped = attempted = 0
    # Before any claim: a client that cannot be built fails the run with nothing
    # claimed, so the executor's retry (or the next sweep) still has every purchase.
    client = await asyncio.to_thread(ax._make_client, account_id) if plans else None
    for i, (fid, pending) in enumerate(plans):
        if attempted >= _LIMIT:
            capped = len(plans) - i          # the rest wait for the next sweep
            break
        if await ax.fan_on_cooldown(account_id, fid):
            skipped += 1         # another sender rested him since the snapshot; next sweep
            continue
        if not await ax.acquire_fan_lease(account_id, fid, KIND):
            busy += 1            # a chat engine is mid-reply to him; next sweep, no slot used
            continue
        try:
            claimed = await _claim(account_id, fid, pending)
            if not claimed:
                continue
            attempted += 1
            text = apply_word_restriction(
                substitute_placeholders(template, fans[fid], name=template_fan_name(fans[fid])))
            fan_media, fan_price = ([], 0) if fid in owned else (media, price_cents)
            try:
                outcome = await ax.of_write_paced(
                    account_id,
                    lambda f=int(fid), t=text, m=fan_media, p=fan_price: send_dropping_bad_media_sync(
                        client, f, t, m, price_cents=p, log=log),
                    send_purpose=_SEND_PURPOSE, dm=True)
            except Exception as exc:  # noqa: BLE001
                if await skip_unreachable_fan(account_id, fid, exc, log=log):
                    unreachable += 1     # skip-listed; the claim stays
                    continue
                errors += 1
                if ax.is_rate_limited(exc):
                    # OF's throttle refused the write: nothing was created, so a
                    # later sweep may try again without risking a second message.
                    await _release(account_id, fid, claimed)
                log.warning("purchase_followup send failed account=%s fan=%s purchases=%s",
                            account_id, fid, claimed, exc_info=True)
                continue
            result = outcome.result
            msg_id = result.get("id") if isinstance(result, dict) else None
            if not msg_id:
                no_id += 1
                log.warning("purchase_followup no-id send account=%s fan=%s purchases=%s "
                            "— claimed, not retried", account_id, fid, claimed)
                await quarantine_if_undeliverable(client, account_id, fid, log=log)
                continue
            await write_outbound_attribution(
                account_id=account_id, fan_id=int(fid), message_id=int(msg_id),
                sent_by_employee_id=None, automation_kind=KIND,
                body=str(result.get("text") or text),
                price_cents=fan_price if outcome.media_landed else 0,
                created_at=ax._parse_iso(result.get("createdAt")) or datetime.utcnow(),
                emit_live=True,
            )
            await extras.schedule_unsend(
                account_id, fid, int(msg_id), minutes=unsend_after,
                price_cents=fan_price if outcome.media_landed else 0)
            await _rest(account_id, fid)
            sent += 1
            owners_sent += fid in owned
            log.info("purchase_followup sent account=%s fan=%s purchases=%s msg=%s",
                     account_id, fid, claimed, msg_id)
        finally:
            await ax.release_fan_lease(account_id, fid, holder=KIND)

    return {"status": "ok", "sent": sent, "no_id": no_id, "errors": errors,
            "unreachable": unreachable, "busy": busy, "skipped": skipped,
            "capped": capped, "folded": folded, "candidates": len(bought),
            "owners_sent_free": owners_sent, **audience_stats}
