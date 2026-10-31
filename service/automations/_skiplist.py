"""Skip-list reasons + loaders (hard skip, muted/restricted, promo spam, self-heal)."""
from __future__ import annotations

from datetime import datetime

from db.engine import get_session
from db.models import Fan, Message, SkipList
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert


# ── Muted-creator + manual "restrict from automations" skip-listing ─────────
# Three DURABLE skip_list reasons that mean "no automation may ever message this
# fan" — a HARD block honoured by EVERY sender (unlike the welcome_chatter_for_info promo-spam
# guard, which is reversible and only covers the gather opener):
#   • 'muted_creator'   — auto: the fan is a creator we follow (subscribedBy) AND
#       we've muted their chat on OF (isMutedNotifications). Mutual-promo spam.
#       Written/cleared by the chat-scrape as the OF mute state flips.
#   • 'manual_restrict' — a human hit "Restrict this fan from automations" in the
#       chat ⋯ menu / Settings. Stays until they Unrestrict.
#   • 'of_restricted'   — a human restricted this user ON ONLYFANS from our UI
#       (chat ⋯ menu "Restrict on OnlyFans"). OF stops delivering their messages
#       to us, so automations must never message them either — and the durable
#       row is what lets the roster badge / inbox counts exclude them (the thin
#       skip_users=all /chats rows carry no isRestricted flag to key off).
# Senders that already gate on FULL skip_list membership (welcome_chatter_for_info,
# send_followup) honour all three
# for free. The priced/proactive senders and list-broadcasts load
# `load_hard_skip_ids` and exclude these explicitly — see the loader below.
MUTED_CREATOR_REASON = "muted_creator"
MANUAL_RESTRICT_REASON = "manual_restrict"
OF_RESTRICTED_REASON = "of_restricted"
# The offer engine's HARD stop reason. Since 07-23 the BOT no longer writes it:
# a hard decline (chargeback / report / unsubscribe language) now takes a 72h
# ladder offers-pause instead of permanent silence — the
# classifier misread a forwarded "unsubscribe and block anyone who…" game as a
# threat and ghosted a real fan forever. The reason stays in the hard set so a
# row an OPERATOR writes by hand (or a legacy row) is still honoured by every
# reader. (The boot-time catch-up that cleared the bot-era rows was removed in
# the 2026-10 cleanup.) A PERMANENT operator stop belongs in manual_restrict.
LADDER_STOP_REASON = "ladder_stop"
HARD_SKIP_REASONS = frozenset(
    {MUTED_CREATOR_REASON, MANUAL_RESTRICT_REASON, OF_RESTRICTED_REASON,
     LADDER_STOP_REASON}
)


# ── Self-healing fans.source classification ─────────────────────────────────
# `fans.source` is what tells the muted-creator auto-skip AND the welcome_chatter_for_info /
# gen_info promo-spam guards that a chat is a peer-creator
# (`creator_we_follow`) rather than a real fan. It is derived from OF's
# relationship flags (`subscribedOn` → us=their creator → 'fan';
# `subscribedBy` → we follow THEM → 'creator_we_follow'). The trap: those flags
# are ABSENT from the two highest-volume ingestion paths — the chat scrape
# (`list_chats` was forcing skip_users=all, which strips them) and plain WS DMs
# (payload is just `fromUser:{id}`) — and `source` was only ever written on the
# INSERT, never refreshed. So a creator first seen via either path was stuck as
# 'onlyfans'/'unknown' forever and stayed invisible to every creator guard.
#
# These helpers let ANY path that DOES carry the flags repair the row on
# conflict: UPGRADE a weak/unknown source to the class OF's flags imply, and
# NEVER downgrade an already-authoritative ('fan' / 'creator_we_follow') value
# nor touch the row when the payload carries no flag.
_WEAK_SOURCES = ("onlyfans", "unknown", "ledger")


def classify_source(subscribed_on, subscribed_by) -> str | None:
    """The authoritative source OF's relationship flags imply, or None when the
    payload carries neither (→ the caller must NOT touch `source`)."""
    if subscribed_on:
        return "fan"
    if subscribed_by:
        return "creator_we_follow"
    return None


def source_self_heal_set(subscribed_on, subscribed_by) -> dict:
    """An on-conflict SET fragment (mergeable into an upsert's `set_`/`update_set`)
    that upgrades `source` to the class OF's flags imply. Returns {} when the
    payload has no authoritative flag, so callers can splat it unconditionally.

    The lattice is fan > creator_we_follow > weak, and 'fan' HEALS DOWNWARD over
    'creator_we_follow' — it is not merely upgrade-only. `subscribedBy` says
    nothing about who someone is: OF hands creator status to anyone, and on a
    free page the model follows fans back, so ordinary fans carry the flag. The
    original upgrade-only rule made that label permanent (`creator_we_follow` is
    not in _WEAK_SOURCES), and a fan who later subscribed could never wash it
    off. Live fallout: 71 of Ava's 73 so-labelled fans were real, and the
    promo-spam guards had been refusing to answer them since 2026-06-17 — one had
    86 inbound messages and was asking "why you ignore me?". `subscribedOn` is
    proof he is OUR fan, so it always wins. We still never downgrade 'fan'."""
    strong = classify_source(subscribed_on, subscribed_by)
    if strong is None:
        return {}
    if strong == "fan":
        return {"source": "fan"}
    from sqlalchemy import case
    return {
        "source": case(
            (Fan.source.is_(None), strong),
            (Fan.source.in_(_WEAK_SOURCES), strong),
            else_=Fan.source,
        )
    }


# ── peer-creator promo spam ─────────────────────────────────────────────────
# What a promo blast actually looks like on the wire. Peer creators compose in
# OF's rich-text mass-message editor, so their sends carry editor spans, bold/
# italic sales copy, or a link back to their page ("FLASH SALE!!", "UNLOCK THIS
# BUNDLE", onlyfans.com/…). A real fan types into the plain chat box and his
# message arrives as bare <p>text</p> — across 73 of Ava's flagged fans only 3
# ever emitted one of these, against 44 of founder's 63 known blasters.
_PROMO_MARKERS = ("m-editor-", "onlyfans.com", "<strong>", "<em>")


async def load_promo_spam_ids(account_id) -> set[int]:
    """fan_ids this account should treat as peer-creator promo blasters — the founder
    problem. Same id-set shape as load_hard_skip_ids, so a
    caller gates with a plain `fid in promo_spam`.

    ALL of: OF says we follow them, they never paid, we never got a real exchange
    out of them (turn_counter), and they have ACTUALLY blasted promo at us.

    `source == 'creator_we_follow'` alone was the whole test until 2026-07-24, and
    it was far too blunt — it only means OF told us we're subscribed to them, which
    is true of any fan the model followed back on a free page. It silenced 71 real
    fans on one account for five weeks (see source_self_heal_set).

    Deliberately CONSERVATIVE: a chatty creator-bot that types plain text is not
    caught and costs a few LLM cents, which is far cheaper than ignoring a real
    fan's "why are you ignoring me?" for a month. Muting the chat remains the
    operator's durable override (skip_list 'muted_creator')."""
    async with get_session() as s:
        rows = (await s.execute(
            select(Fan.fan_id)
            .where(Fan.account_id == str(account_id),
                   Fan.source == "creator_we_follow",
                   func.coalesce(Fan.lifetime_spend_cents, 0) == 0,
                   func.coalesce(Fan.turn_counter, 0) == 0,
                   select(Message.message_id).where(
                       Message.account_id == Fan.account_id,
                       Message.fan_id == Fan.fan_id,
                       Message.direction == "in",
                       or_(*[Message.body.contains(m) for m in _PROMO_MARKERS]),
                   ).exists())
        )).all()
    return {int(r[0]) for r in rows}


def should_skip_muted_creator(fan) -> bool:
    """True when this Fan row is a creator we follow whose chat we've muted — i.e.
    mutual-promo spam no automation should ever touch. Belt-and-suspenders to the
    durable skip_list row: it catches the fan at candidate time even in the window
    BEFORE the scrape has written the row (or if the row was cleared by hand)."""
    return bool(
        fan is not None
        and getattr(fan, "is_muted", False)
        and (getattr(fan, "source", "") or "") == "creator_we_follow"
    )


async def load_hard_skip_ids(account_id) -> set[int]:
    """fan_ids this account has on skip_list under ANY hard reason (muted_creator /
    manual_restrict / of_restricted / ladder_stop). Use for priced/proactive sends
    and list-broadcasts."""
    return await _load_skip_ids(account_id, HARD_SKIP_REASONS)


async def is_hard_skipped(account_id, fan_id: int) -> bool:
    """Is THIS ONE fan on the account's hard-skip list? — `load_hard_skip_ids`'s
    question for a single fan, without materialising the answer for everyone else.

    A sender that already holds the whole set should keep using it. This is for
    the read that happens per-FAN and inside a paced burst — `send_welcome`'s turn
    handoff, which asks it on the abort path with up to six bursts in flight and
    was loading the account's entire hard-skip set to answer a boolean each time.
    The freshness argument for reading it there rather than reusing the run's own
    snapshot is right (a restriction can land mid-burst); what was wrong was
    building a set to test one membership."""
    from sqlalchemy import select
    async with get_session() as s:
        row = (await s.execute(
            select(SkipList.fan_id).where(
                SkipList.account_id == str(account_id),
                SkipList.fan_id == int(fan_id),
                SkipList.reason.in_(tuple(HARD_SKIP_REASONS)),
            ).limit(1)
        )).first()
    return row is not None


async def _load_skip_ids(account_id, reasons: frozenset) -> set[int]:
    from sqlalchemy import select
    async with get_session() as s:
        rows = (await s.execute(
            select(SkipList.fan_id).where(
                SkipList.account_id == str(account_id),
                SkipList.reason.in_(tuple(reasons)),
            )
        )).all()
    return {int(r[0]) for r in rows}


async def mark_muted_creator_skip(account_id, fan_id, *, now=None) -> None:
    """Durably skip-list a muted creator. Upserts reason='muted_creator' so the
    block is a HARD stop everywhere (it deliberately wins over a softer existing
    reason such as 'info', which a sender would otherwise let through) — but
    never over 'of_restricted': that one is strictly stronger (it also drives
    the unread-count exclusion) and the scrape must not demote it on the next
    mute reconcile."""
    now = now or datetime.utcnow()
    async with get_session() as s:
        await s.execute(
            sqlite_insert(SkipList)
            .values(account_id=str(account_id), fan_id=int(fan_id),
                    reason=MUTED_CREATOR_REASON, added_at=now)
            .on_conflict_do_update(
                index_elements=["account_id", "fan_id"],
                set_={"reason": MUTED_CREATOR_REASON, "added_at": now},
                where=(SkipList.reason.is_(None)
                       | (SkipList.reason != OF_RESTRICTED_REASON)),
            )
        )


async def set_of_restricted_skip(account_id, fan_id, restricted: bool, *, now=None) -> None:
    """Durable registry of users this account has restricted ON ONLYFANS via our
    UI. restricted=True upserts skip_list(reason='of_restricted') — it wins over
    any existing reason because it's the strongest block (OF itself stops
    delivering their messages). restricted=False removes ONLY that row; a muted
    creator gets its 'muted_creator' row back on the next scrape reconcile."""
    from sqlalchemy import delete as sa_delete
    now = now or datetime.utcnow()
    async with get_session() as s:
        if restricted:
            await s.execute(
                sqlite_insert(SkipList)
                .values(account_id=str(account_id), fan_id=int(fan_id),
                        reason=OF_RESTRICTED_REASON, added_at=now)
                .on_conflict_do_update(
                    index_elements=["account_id", "fan_id"],
                    set_={"reason": OF_RESTRICTED_REASON, "added_at": now},
                )
            )
        else:
            await s.execute(
                sa_delete(SkipList).where(
                    SkipList.account_id == str(account_id),
                    SkipList.fan_id == int(fan_id),
                    SkipList.reason == OF_RESTRICTED_REASON,
                )
            )


async def load_of_restricted_ids(account_id) -> set[int]:
    """fan_ids this account has restricted on OF via our UI — the exclusion set
    for the roster-badge fold and the /chats row annotation."""
    from sqlalchemy import select
    async with get_session() as s:
        rows = (await s.execute(
            select(SkipList.fan_id).where(
                SkipList.account_id == str(account_id),
                SkipList.reason == OF_RESTRICTED_REASON,
            )
        )).all()
    return {int(r[0]) for r in rows}


async def automation_restrict_status(account_id, fan_id) -> dict:
    """{restricted, reason} for one fan — restricted iff a HARD skip row exists
    (manual_restrict OR muted_creator). The UI flips its toggle off this."""
    from sqlalchemy import select
    async with get_session() as s:
        row = (await s.execute(
            select(SkipList.reason).where(
                SkipList.account_id == str(account_id),
                SkipList.fan_id == int(fan_id),
            )
        )).scalar_one_or_none()
    return {"restricted": row in HARD_SKIP_REASONS, "reason": row}

