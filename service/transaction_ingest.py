"""
Background ingest supervisor for OF's /api2/v2/payouts/transactions ledger.

Single async supervisor task per process. 5-min ticks (`_TICK_INTERVAL_S`).
Sequential per-account inside one refresh tick. 0.4s inter-page sleep.

Drops X-Priority entirely (the request-context priority does not propagate
to a background task — see library/db_data/12_transaction_ingest_synthesis.md §2
row 3). The rate-limit posture is cadence + sequential walk, not a header.

7-day rolling window steady-state; 90-day cold-start backfill.

3-step dedup writer (synthesis §5):
  Step 1: provider_id fast path (handles re-polls + loading->cleared flips).
  Step 2: fingerprint fallback for kind='tip' to find the WS-pump sibling row
          (account_id, fan_id, kind='tip', amount_cents +/- tolerance,
          occurred_at +/- 300s, source='ws', provider_transaction_id IS NULL).
          Patches in place; promotes to source='ledger'.
  Step 3: fresh insert as source='ledger'.
A page is planned by transaction_ingest_decide.plan_page and written in ONE
write transaction — none at all for a quiet re-poll (every field equal).

fans.lifetime_spend_cents rule (synthesis §5), in the row's own transaction:
  Bump by the amount on a Step 3 revenue insert. Never on a Step 1 re-poll.
  Step 2 only reconciles: the WS path already bumped by the WS amount
  (event_transcoder), so the promote applies (ledger - WS amount). On
  status->chargedback or refunded, apply -prev_amount_cents, clamped at 0.

paidMessage convergence: when a ledger row arrives with kind='ppv_message'
AND a plausible unpaid outbound message exists, in the SAME transaction
link transaction.message_id and set messages.is_paid=true,
messages.purchased_at=occurred_at. This is currently the ONLY reliable
PPV-unlock signal (WS pump has caught 0 unlock events).

Canonical background-task template: _perflog_evictor_loop at
service/server.py:1374-1394. Sync OF client wrap idiom: server.py:1887
and server.py:2388 (`await asyncio.to_thread(...)`).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, NamedTuple

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

import account_health
import accounts as account_registry
from cadence import boot_grace
import client_pool
from db import of_writer, write_telemetry
from db.engine import get_session
import fansly_backend
import fansly_revenue
from db.models import (
    Account,
    AutomationRule,
    Chatter,
    ChatterUser,
    Fan,
    Message,
    Transaction,
    TransactionScanHistory,
    User,
    UserAccount,
)
from curl_cffi.requests.exceptions import ProxyError
from of_client import OFClient
import ownership
import purchase_notifications
from tip_ledger import TIP_LEDGER_PREFIX

log = logging.getLogger("of-relay.ingest_tx")


def _env_float(name: str, default: float) -> float:
    """Read a float knob from the environment. A malformed value must not take
    the relay down at import time — it degrades to the default, loudly."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        log.warning("ingest_bad_env name=%s value=%r — using default %.0f",
                    name, raw, default)
        return default


# ── Knobs ────────────────────────────────────────────────────────────
_TICK_INTERVAL_S = 300                  # 5 minutes (was 600 — too slow vs the 30m green tier ceiling)
_PAGE_SLEEP_S = 0.4
_PAGE_LIMIT = 100                       # OF max per request
_BACKFILL_CONCURRENCY = 4               # synthesis review §4
# Minimum gap between cycles, ALWAYS honoured — the anti-spin floor.
# Both loops below sleep `interval - elapsed` so the inter-scan GAP stays
# constant regardless of cycle duration (that fix is why they sleep at end
# rather than at start). But `max(0.0, ...)` means a cycle that OVERRUNS its
# interval sleeps zero and re-enters immediately — a hot loop that pegs the
# CPU and never backs off. It is self-sustaining: the spin starves the event
# loop and the SQLite writer, which makes the next cycle slower still, so the
# sleep stays zero forever. Observed 2026-08-21: relay at ~102% CPU on a
# 2-vCPU box, load 7.48, and every request's `last_seen_at` bump timing out
# on the 30 s busy_timeout ("database is locked") because the writer never
# got a gap. Recovery required the backlog to drain by luck.
# So: overrunning yields the floor, never zero. Fast cycles are unaffected
# (interval - elapsed is far larger than the floor), so the anti-drift intent
# is preserved exactly.
_MIN_CYCLE_GAP_S = 5.0
# Boot grace — how long each loop below holds its FIRST cycle after process
# start. `_MIN_CYCLE_GAP_S` bounds a cycle that OVERRUNS; this bounds the one
# that starts too early, which the floor cannot see. At t=0 the relay is still
# spawning the WS pumps, the pump supervisor, the automation executor's
# immediate first drain and the fleet-wide scrape_chats seed, so a full-fleet
# ledger walk fired at t=0 competes with the startup it is part of — and a
# RESTART is precisely what produced the 2026-08-21 CPU cap (three inside
# ~64 min). Costs at most one cycle of ledger freshness on a boot and nothing
# at all in steady state. Zero disables, for a recovery boot where freshness
# beats politeness. See cadence.boot_grace.
_BOOT_GRACE_S = _env_float("INGEST_BOOT_GRACE_S", 90.0)
_FAST_BOOT_GRACE_S = _env_float("INGEST_FAST_BOOT_GRACE_S", 30.0)
_PPV_LINK_LOOKBACK_DAYS = 30
# Per-tick orphan-attribution sweep window (see attribution_backfill). Covers
# a refresh scan's 7-day window plus slack for late-clearing pending rows.
_ATTR_SWEEP_SINCE_DAYS = 14
# Wall-post ownership belt: keep re-reading the purchases feed this long after
# the account's last ppv_post sale (cost gate for _has_recent_post_txn;
# stamping is idempotent). Deliberately its own knob — tuning the attribution
# window above must not silently retune this safety gate.
_POST_OWNERSHIP_SINCE_DAYS = 14
_STALE_INFLIGHT_S = 900                 # 15 min — escape valve for crashed ticks (see _tick_locks comment)

# Re-entrant tick guard: if run_one_tick(aid) takes >600s the next supervisor
# cycle would fire concurrently and double-write. Per-account asyncio.Lock.
_tick_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

# Cycle gate: only scan accounts whose owner (User) or linked chatter has
# been active within the last _ONLINE_WINDOW_S seconds. last_seen_at is
# bumped per-request with a ~5-min throttle (auth.py / chatters.py), so a
# 10-min window covers the throttle slack without keeping a logged-out
# dashboard's broken sessions burning OF proxy quota every 5 minutes.
_ONLINE_WINDOW_S = 600

# A run_one_tick stamps current_status='refreshing'/'backfilling' at start
# (scan_started) and overwrites it at end via _mark_success / _record_failure.
# If the tick task is cancelled (uvicorn reload, deploy, SIGTERM) or the
# process dies between those points, the stamp persists in the DB and the
# /run endpoint's 409 guard locks the account out permanently. _STALE_INFLIGHT_S
# bounds how long a real in-flight stamp can be trusted before treating it
# as a tombstone from a crashed prior holder. 15min >> typical tick duration
# (under 60s steady-state, a few min during a fresh 90d backfill).

# The pure half (kind catalog, row parsing, the page plan, the scan state
# machine) lives in transaction_ingest_decide; every name stays importable
# from here.
from transaction_ingest_decide import (  # noqa: E402,F401
    KIND_CATALOG,
    PATCH_FIELDS,
    IN_FLIGHT,
    SCAN_FIELDS,
    _DEFAULT_BACKFILL_DAYS,
    _ENABLE_PPV_FINGERPRINT,
    _FAIL_BACKOFF_S,
    _FAILS_BEFORE_PAUSE,
    _HTML_TAG,
    _NON_REVENUE_STATUSES,
    _REFUND_STATUSES,
    _ROLLING_WINDOW_DAYS,
    _STATUS_MAP,
    Existing,
    RowOp,
    ScanState,
    WsTip,
    _classify_kind,
    _normalize_status,
    _parse_iso,
    _parse_row,
    _strip_html,
    _to_cents,
    decide_mode,
    is_paused,
    parse_page,
    plan_page,
    scan_after_failure,
    scan_after_success,
    scan_interrupted,
    scan_started,
    subscription_fans,
    tip_window,
    window_for,
)


# ── Writer pieces ───────────────────────────────────────────────────

# Pathological-case guard for the linker's candidate fetch. A fan's same-price
# outbound messages in a 30-day window are normally a handful; if we ever see
# this many, the case is ambiguous by definition and we refuse to guess.
_PPV_LINK_CANDIDATE_CAP = 50


async def _link_ppv_message(
    s,
    *,
    account_id: str,
    fan_id: int,
    amount_cents: int,
    occurred_at: datetime,
    tx: Transaction,
    stamp_paid: bool = True,
) -> bool:
    """Attach a `ppv_message` ledger row to the outbound PPV it paid for — the
    message whose `sent_by_employee_id` ("Sent by …") then credits the sale in
    the per-employee view.

    Candidates: same (account, fan), outbound, EXACT price match, sent within
    _PPV_LINK_LOOKBACK_DAYS before the unlock, and not already claimed by
    another transaction. The claim guard is kind-agnostic on purpose — it
    mirrors the `uq_tx_msg` unique index, where a second claim of any kind is
    a constraint violation.

    Deliberately does NOT require the message to still be unpaid: the WS pump
    flips `is_paid` within seconds of an unlock while this ledger tick runs
    every ~5 minutes, so the purchased message is usually ALREADY paid by the
    time the money shows up — the old unpaid filter orphaned exactly the
    fastest buyers (or worse, matched a stale same-price message). Instead the
    flip is a POSITIVE signal: it marks which message the fan actually opened.

    Links ONLY when unambiguous: exactly one candidate, or exactly one
    candidate carrying the is_paid flag. Anything murkier stays unlinked for
    the Sales-needing-attribution panel (ops' "clear cases only" rule).
    Sequential unlocks still auto-link — each prior unlock's message is
    already claimed and excluded by the guard when the next tick fires.

    `stamp_paid=False` (historical backfill) writes ONLY `tx.message_id` — no
    message mutation, so bulk relinks have zero downstream side effects
    (funnels / offer watcher / bought-media dedupe all read `is_paid`) and
    reversal is a single UPDATE nulling the journaled message_ids.

    Returns True iff a link was made.
    """
    msg, _reason = await _select_ppv_link_candidate(
        s,
        account_id=account_id,
        fan_id=fan_id,
        amount_cents=amount_cents,
        occurred_at=occurred_at,
    )
    if msg is None:
        return False
    if stamp_paid:
        msg.is_paid = True
        msg.purchased_at = occurred_at
    tx.message_id = msg.message_id
    return True


async def _select_ppv_link_candidate(
    s,
    *,
    account_id: str,
    fan_id: int,
    amount_cents: int,
    occurred_at: datetime,
) -> tuple[Message | None, str]:
    """Pure READ: pick the message a PPV payment belongs to, or refuse.
    Returns (message, 'ok') on an unambiguous pick, else (None, reason) with
    reason in {'no_candidate', 'ambiguous'}. Shared by the live linker and the
    relink sweep's dry-run so the reported plan is exactly what apply would do.
    """
    cutoff = occurred_at - timedelta(days=_PPV_LINK_LOOKBACK_DAYS)
    already_claimed = (
        select(Transaction.id)
        .where(
            Transaction.account_id == Message.account_id,
            Transaction.fan_id == Message.fan_id,
            Transaction.message_id == Message.message_id,
        )
        .exists()
    )
    res = await s.execute(
        select(Message).where(
            Message.account_id == account_id,
            Message.fan_id == fan_id,
            Message.direction == "out",
            Message.price_cents == amount_cents,
            Message.created_at >= cutoff,
            Message.created_at <= occurred_at,
            ~already_claimed,
        )
        .order_by(Message.created_at.desc())
        .limit(_PPV_LINK_CANDIDATE_CAP)
    )
    candidates = list(res.scalars().all())
    if not candidates or len(candidates) >= _PPV_LINK_CANDIDATE_CAP:
        return (None, "no_candidate" if not candidates else "ambiguous")
    if len(candidates) == 1:
        return (candidates[0], "ok")
    paid = [m for m in candidates if m.is_paid]
    if len(paid) != 1:
        return (None, "ambiguous")  # leave for the manual panel
    return (paid[0], "ok")


# Synthetic message_id band for LEDGER-ingested chat tips the WS pump never saw
# (so no real chat_message row exists). Sits ABOVE the mass-placeholder band
# (5e15, attribution._MASS_PLACEHOLDER_BASE) and BELOW JS's 2**53 safe-integer
# ceiling (9.007e15), so the id round-trips through the Number-typed frontend
# `message_id` without precision loss and can't collide with a real OF id
# (~9.9e12) or a mass placeholder. id = base + transactions.id (the globally
# unique autoincrement PK) → stable + unique per (account, fan). NOT a sort key:
# the per-chat thread orders by created_at, so the tip lands in its true
# chronological slot no matter where this id sorts.
_TIP_MSG_ID_BASE = 6_000_000_000_000_000

# The BODY a ledger-derived tip row carries — the one definition, exported
# because a second consumer has to recognise these rows and can only do it by
# matching this exact string.
#
# ⚠️ send_welcome's `stop_on_reply` predicate EXCLUDES them: the operator's rule
# is "dont stop on single tip only on text" (plans/welcome-pacing §C4), and a
# bare tip is applause, not a conversational turn. Nobody TYPED this string — it
# is our own bookkeeping wearing an inbound row. It used to live as a second
# hand-copied literal over there with no import between the two files, so a
# purely cosmetic edit here (a different emoji, "tipped" instead of "Sent a")
# would have made every bare tip read as "he used words" and aborted every
# welcome burst on one — the exact behaviour the operator vetoed — while every
# suite stayed green, because the test carried its own third copy.
# Defined in its own leaf module (`service/tip_ledger.py`) rather than here, and
# imported at the top of this file: `automations/_common.py` has to RECOGNISE the
# string, and `_common` is the base every automation imports — an edge from there
# into this orchestrator drags the whole OF/Fansly client stack under the bottom
# of the automation tree. The leaf explains itself.


def tip_ledger_body(amount_cents: int) -> str:
    """The inbound-row body for a chat tip that only exists in the ledger.

    Callers that need to RECOGNISE such a row match `TIP_LEDGER_PREFIX` against
    the start of the body; this is the only place that builds a whole one."""
    return f"{TIP_LEDGER_PREFIX}{(amount_cents or 0) / 100:.2f} tip"


async def _synthesize_tip_message(
    s,
    *,
    account_id: str,
    fan_id: int,
    amount_cents: int,
    occurred_at: datetime,
    tx: Transaction,
) -> None:
    """Write an INBOUND `messages` row for a chat tip that only exists in the
    ledger, so the tip shows INLINE in the chat thread instead of only in the
    revenue panel.

    Only called on a FRESH ledger insert of a chat `kind='tip'` with no WS
    sibling (the fingerprint step found none) — so there's no real chat_message
    row to duplicate. Idempotent via on_conflict_do_nothing on the composite PK.

    The tip $ goes in the BODY, not price_cents (which stays 0, mirroring the WS
    tip row): the frontend reads a bubble's price from price_cents and a non-zero
    value would paint the tip as a locked PPV. `is_tip=True` paints it blue.

    Deliberately does NOT touch `chats` (preview/unread): a cold 90-day backfill
    replays old tips and must not resurrect the inbox badge; the message row
    alone satisfies "show the tip inline". Never advances live SSE either — the
    5-min ledger poll isn't a live path (the WS pump owns that).
    """
    # Flush so the autoincrement tx.id is populated for the synthetic id.
    await s.flush()
    if tx.id is None:
        return
    synth_id = _TIP_MSG_ID_BASE + int(tx.id)
    body = tip_ledger_body(amount_cents or 0)
    stmt = sqlite_insert(Message).values(
        account_id=str(account_id),
        fan_id=int(fan_id),
        message_id=synth_id,
        direction="in",
        sender_name="",
        body=body,
        media_ids="[]",
        media_count=0,
        price_cents=0,
        is_paid=None,
        is_tip=True,
        raw_json=None,
        created_at=occurred_at,
        ingested_at=datetime.utcnow(),
    ).on_conflict_do_nothing(
        index_elements=["account_id", "fan_id", "message_id"],
    )
    await s.execute(stmt)
    log.info("ingest_tx_synth_tip_msg account=%s fan=%s tx=%s msg=%s cents=%d",
             account_id, fan_id, tx.id, synth_id, amount_cents or 0)


async def relink_orphan_ppvs(
    *,
    account_id: str | None = None,
    since: datetime | None = None,
    dry_run: bool = False,
    limit: int = 500,
    newest_first: bool = True,
    after: tuple[str, int] | None = None,
    stamp_paid: bool = True,
) -> dict[str, Any]:
    """Retry the payment→message link for orphaned chat PPVs
    (`kind='ppv_message'`, `message_id IS NULL`). Fill-only: enumerates only
    message-NULL rows and never touches `attributed_employee_id`, so manual
    assignments and existing links are untouchable by construction.

    Two callers, two shapes:
      • per-tick sweep (run_one_tick): account + recent `since` window,
        `newest_first=True` + bounded `limit` — fresh linkable rows are always
        reached even if the window holds permanently-ambiguous rows.
      • one-shot backfill: `newest_first=False` with `after` as a keyset
        cursor `(occurred_at_iso, id)` — chunked traversal of ALL history,
        oldest first, `stamp_paid=False` (attribution only, zero message-state
        side effects).

    CONCURRENCY: a read-only pass plans the batch; only the orphans of the
    fans it would link something for are revisited (a link can free or take
    a sibling orphan's candidate), in ONE write transaction (`_ledger_txn`,
    BEGIN IMMEDIATE, labelled `ledger-relink`) — a tick whose orphans are all
    ambiguous takes no write lock at all, and the lock is held for the
    linkable few, not the whole batch. Each revisit re-checks
    `message_id IS NULL` and re-picks its candidate, in a SAVEPOINT: an
    IntegrityError (uq_tx_msg race with a claim of the same message) rolls
    back that row only → `conflict_skipped`.

    DRY RUN is genuinely read-only: it runs the same candidate selector and
    reports what apply WOULD do, tracking would-be claims in memory so two
    orphans can't both "plan" the same message (such repeats count as
    `conflict_skipped`).

    Returns {examined, linked, ambiguous_skipped, no_candidate,
    conflict_skipped, journal: [{tx_id, message_id}], next_after} —
    `next_after` is the keyset cursor for the next chunk (None = exhausted).
    """
    from sqlalchemy import tuple_ as sa_tuple

    stats: dict[str, Any] = {
        "examined": 0, "linked": 0, "ambiguous_skipped": 0,
        "no_candidate": 0, "conflict_skipped": 0,
        "journal": [], "next_after": None, "dry_run": dry_run,
    }

    q = (
        select(
            Transaction.id, Transaction.account_id, Transaction.fan_id,
            Transaction.amount_cents, Transaction.occurred_at,
        )
        .where(
            Transaction.kind == "ppv_message",
            Transaction.message_id.is_(None),
            Transaction.fan_id.is_not(None),
            Transaction.status.in_(("cleared", "pending")),
        )
    )
    if account_id is not None:
        q = q.where(Transaction.account_id == account_id)
    if since is not None:
        q = q.where(Transaction.occurred_at >= since)
    if newest_first:
        q = q.order_by(Transaction.occurred_at.desc(), Transaction.id.desc())
    else:
        q = q.order_by(Transaction.occurred_at.asc(), Transaction.id.asc())
        if after is not None:
            q = q.where(
                sa_tuple(Transaction.occurred_at, Transaction.id)
                > (datetime.fromisoformat(after[0]), after[1])
            )
    q = q.limit(limit)

    async with get_session() as s:
        rows = (await s.execute(q)).all()
        dry = await _relink_pass(s, rows, dry_run=True, stamp_paid=stamp_paid)
    outcomes, journal = dry["outcomes"], dry["journal"]
    if not dry_run and journal:
        fans = {(str(r[1]), int(r[2])) for r in rows if outcomes[r[0]] == "linked"}
        async with _ledger_txn("ledger-relink") as s:
            real = await _relink_pass(s, [r for r in rows if (str(r[1]), int(r[2])) in fans],
                                      dry_run=False, stamp_paid=stamp_paid)
        outcomes, journal = {**outcomes, **real["outcomes"]}, real["journal"]
        # Paid → owned. Only on stamp_paid runs: the attribution-only
        # backfill promises zero downstream side effects. After the commit,
        # so no lock is held.
        for tx_id, aid, fid, msg_id, cents in real["stamps"]:
            await ownership.try_stamp_message(
                str(aid), int(fid), int(msg_id), price_cents=int(cents or 0),
                context=f"relink tx={tx_id}")
    counts = Counter(outcomes.values())
    stats.update({k: counts[k] for k in _RELINK_OUTCOMES}, examined=len(rows), journal=journal)

    if len(rows) == limit and not newest_first and rows:
        last = rows[-1]
        stats["next_after"] = (last.occurred_at.isoformat(), int(last.id))
    return stats


_RELINK_OUTCOMES = ("linked", "ambiguous_skipped", "no_candidate", "conflict_skipped")


async def _relink_pass(s, rows, *, dry_run: bool, stamp_paid: bool) -> dict[str, Any]:
    """relink_orphan_ppvs over `rows` in session `s`. dry_run: read-only,
    would-be claims tracked in memory. Else links in `s` (the caller's
    write transaction), one SAVEPOINT per row. Returns `outcomes` (tx id ->
    one of _RELINK_OUTCOMES), `journal`, and `stamps`: the links whose
    ownership stamp waits for the commit."""
    from sqlalchemy.exc import IntegrityError

    outcomes: dict[int, str] = {}
    out: dict[str, Any] = {"outcomes": outcomes, "journal": [], "stamps": []}
    dry_claimed: set[tuple[str, int, int]] = set()
    for tx_id, aid, fid, cents, occ in rows:
        tx = (await s.execute(
            select(Transaction).where(
                Transaction.id == tx_id,
                Transaction.message_id.is_(None),  # re-check: live tick may have won
            )
        )).scalar_one_or_none()
        if tx is None:
            outcomes[tx_id] = "conflict_skipped"
            continue
        msg, reason = await _select_ppv_link_candidate(
            s, account_id=aid, fan_id=int(fid),
            amount_cents=int(cents or 0), occurred_at=occ,
        )
        if msg is None:
            outcomes[tx_id] = "ambiguous_skipped" if reason == "ambiguous" else "no_candidate"
            continue
        if dry_run:
            claim_key = (str(aid), int(fid), int(msg.message_id))
            if claim_key in dry_claimed:
                outcomes[tx_id] = "conflict_skipped"
                continue
            dry_claimed.add(claim_key)
        else:
            try:
                async with s.begin_nested():
                    if stamp_paid:
                        msg.is_paid = True
                        msg.purchased_at = occ
                    tx.message_id = msg.message_id
                    await s.flush()
            except IntegrityError:
                outcomes[tx_id] = "conflict_skipped"
                continue
            log.info(
                "relink_ppv_linked tx=%d account=%s fan=%s msg=%d cents=%d stamp_paid=%s",
                tx_id, aid, fid, int(msg.message_id), int(cents or 0), stamp_paid,
            )
            if stamp_paid:
                out["stamps"].append((tx_id, aid, fid, int(msg.message_id), cents))
        outcomes[tx_id] = "linked"
        out["journal"].append({"tx_id": int(tx_id), "message_id": int(msg.message_id)})
    return out


async def _has_recent_post_txn(account_id: str, *, since: datetime) -> bool:
    """Any wall-post purchase on the ledger recently? Cheap gate for the
    per-tick post-ownership sweep — most accounts sell nothing off the wall
    and should not pay a notifications fetch every 5 minutes."""
    async with get_session() as s:
        row = (await s.execute(
            select(Transaction.id).where(
                Transaction.account_id == account_id,
                Transaction.kind == "ppv_post",
                Transaction.occurred_at >= since,
            ).limit(1)
        )).scalar_one_or_none()
    return row is not None


async def _bump_lifetime(s, account_id: str, fan_id: int, amount_cents: int) -> None:
    """Add `amount_cents` to this fan's lifetime spend, creating the row if
    needed.

    SHARED with the Fansly lane (fansly_revenue), which writes the same
    `transactions` rows from a different source and must keep this rollup in
    step. It lives here, next to the OF writer that has always called it,
    rather than being duplicated there — a second copy is how the two lanes
    would drift.
    """
    fan = await s.get(Fan, (account_id, fan_id))
    if fan is None:
        # PPV-only / non-replying fans never trigger the WS-pump's inbound
        # chat_message path that creates fans rows (event_transcoder.py
        # early-returns on direction=="out"). Without this stub, their
        # lifetime_spend silently stays 0 while the transactions ledger
        # holds the truth — and stats/sort-by-spend rank them as $0.
        # `source="ledger"` flags the row as ledger-originated so a
        # later inbound DM can upsert the OF profile fields cleanly.
        s.add(Fan(
            account_id=account_id,
            fan_id=fan_id,
            source="ledger",
            lifetime_spend_cents=amount_cents,
        ))
        return
    fan.lifetime_spend_cents = (fan.lifetime_spend_cents or 0) + amount_cents
    fan.updated_at = datetime.utcnow()


async def _apply_lifetime_delta(s, account_id: str, fan_id: int, delta_cents: int) -> None:
    """Signed change to an EXISTING fan's lifetime spend, clamped at 0 (a
    chargeback takes the sale off; a promote reconciles the WS amount to the
    ledger's). Runs inside the caller's `_ledger_txn`: BEGIN IMMEDIATE already
    holds the write lock, so the read-modify-write cannot hit
    SQLITE_BUSY_SNAPSHOT and commits with the row it belongs to — a failure
    between the two can no longer leave the counter stale."""
    if delta_cents == 0:
        return
    fan = await s.get(Fan, (account_id, fan_id))
    if fan is None:
        return
    fan.lifetime_spend_cents = max(0, (fan.lifetime_spend_cents or 0) + delta_cents)
    fan.updated_at = datetime.utcnow()


@contextlib.asynccontextmanager
async def _ledger_txn(label: str = "ledger"):
    """One ledger write transaction: `of_writer.immediate()` (BEGIN IMMEDIATE,
    the lock up front) with an ORM session on its connection, its writes
    labelled `label` in write_telemetry (`ledger`: the page writer;
    `ledger-relink`: the relink sweep). Flushed on success; the COMMIT /
    ROLLBACK is immediate()'s."""
    with write_telemetry.writer(label):
        async with of_writer.immediate() as conn:
            s = AsyncSession(bind=conn, expire_on_commit=False)
            try:
                yield s
                await s.flush()
            finally:
                await s.close()


class _PageRead(NamedTuple):
    """A page read and planned: the ORM rows the apply writes over, and the
    plan made from their snapshots."""
    held: dict[str, Transaction]   # provider id (text) -> its row
    ws: dict[int, Transaction]     # Transaction.id -> WS-pump tip row
    ops: list[RowOp]


async def _read_plan(s, account_id: str, parsed: list[dict]) -> _PageRead:
    """Read what `plan_page` needs — the rows already held by provider id,
    the WS-pump tips a ledger tip may be the twin of, the fans that already
    have a subscription row — and plan the page against it."""
    pids = [p["provider_id"] for p in parsed if p["provider_id"]]   # keyed as text: the column's type
    held: dict[str, Transaction] = {}
    if pids:
        for tx in (await s.execute(select(Transaction).where(
            Transaction.account_id == account_id,
            Transaction.provider_transaction_id.in_(pids),
        ))).scalars():
            held.setdefault(str(tx.provider_transaction_id), tx)
    ws: dict[int, Transaction] = {}
    window = tip_window(parsed, held)
    if window is not None:
        fans, lo, hi = window
        for tx in (await s.execute(select(Transaction).where(
            Transaction.account_id == account_id,
            Transaction.fan_id.in_(fans),
            Transaction.kind == "tip",
            Transaction.source == "ws",
            Transaction.provider_transaction_id.is_(None),
            Transaction.occurred_at >= lo,
            Transaction.occurred_at <= hi,
        ))).scalars():
            ws[tx.id] = tx
    sub_fans = subscription_fans(parsed)
    subscribed: set[int] = set()
    if sub_fans:
        subscribed = {r[0] for r in (await s.execute(select(Transaction.fan_id).where(
            Transaction.account_id == account_id,
            Transaction.fan_id.in_(sub_fans),
            Transaction.kind.in_(("subscription", "rebill")),
        ).distinct())).all()}
    existing = {pid: Existing(*(getattr(tx, f) for f in PATCH_FIELDS)) for pid, tx in held.items()}
    fingerprints = [WsTip(tx.id, tx.fan_id, tx.amount_cents, tx.occurred_at) for tx in ws.values()]
    return _PageRead(held, ws, plan_page(parsed, existing, fingerprints, subscribed_fans=subscribed))


async def _apply_ops(s, account_id: str, ops: list[RowOp], held: dict, ws: dict) -> dict[int, tuple]:
    """Write `ops` in the open `_ledger_txn` session, rows and lifetime deltas
    alike. `held` (provider id -> row) is the page's one row-identity tracker:
    a patch writes the row it names, an insert / promote adds to it. Returns
    {op index: (fan_id, message_id, cents)} for each PPV that linked: its
    ownership stamp waits for the commit."""
    stamps: dict[int, tuple] = {}
    for i, op in enumerate(ops):
        if not op.writes:
            continue
        p = op.parsed
        if op.action == "patch":
            tx = held[str(p["provider_id"])]
            for f in PATCH_FIELDS:
                setattr(tx, f, p[f])
            if op.status_flip:
                log.info(
                    "ingest_tx_status_flip provider=%s old=%s new=%s",
                    p["provider_id"], *op.status_flip,
                )
            if op.lifetime_delta:
                log.info(
                    "ingest_tx_chargeback provider=%s amount=%d",
                    p["provider_id"], -op.lifetime_delta,
                )
        elif op.action == "promote":
            tx = ws[op.target_id]
            prev_ws_amount = tx.amount_cents
            tx.provider_transaction_id = p["provider_id"]
            tx.source = "ledger"
            for f in PATCH_FIELDS:
                setattr(tx, f, p[f])
            held[str(p["provider_id"])] = tx
            log.info(
                "ingest_tx_fingerprint_match account=%s fan=%s "
                "provider=%s amount=%d kind=%s prev_amount=%d",
                account_id, p["fan_id"], p["provider_id"],
                p["amount_cents"], op.kind, prev_ws_amount,
            )
        else:  # insert
            tx = Transaction(
                account_id=account_id,
                fan_id=p["fan_id"],
                kind=op.kind,
                message_id=None,
                amount_cents=p["amount_cents"],
                currency=p["currency"],
                occurred_at=p["occurred_at"],
                provider_transaction_id=p["provider_id"],
                status=p["status"],
                cleared_at=p["cleared_at"],
                payout_pending_days=p["payout_pending_days"],
                net_cents=p["net_cents"],
                fee_cents=p["fee_cents"],
                vat_cents=p["vat_cents"],
                description=p["description"],
                source="ledger",
            )
            s.add(tx)
            held[str(p["provider_id"])] = tx
            if op.link_ppv:
                await _link_ppv_message(
                    s,
                    account_id=account_id,
                    fan_id=p["fan_id"],
                    amount_cents=p["amount_cents"],
                    occurred_at=p["occurred_at"],
                    tx=tx,
                )
                # The linked message is PAID → its media is OWNED. Stamped
                # after the commit (ownership opens its own session; running
                # it here would write-deadlock against ours). Covers every
                # lane the linker reaches: catalog offers, priced teasers
                # (VaultSend rows keyed by message id) and mass placeholders
                # (media via the broadcast cache).
                if tx.message_id is not None:
                    stamps[i] = (int(p["fan_id"]), int(tx.message_id), int(p["amount_cents"] or 0))
            # A chat tip that only exists in the ledger (WS pump missed it)
            # has NO chat_message row → it never shows in the thread, only in
            # the revenue panel. Synthesize an inbound row so it appears
            # inline. Chat tips only (kind=='tip'); tips on posts/streams
            # (tip_post/tip_stream) don't ride a chat and are excluded.
            if op.synth_tip:
                await _synthesize_tip_message(
                    s, account_id=account_id, fan_id=p["fan_id"],
                    amount_cents=p["amount_cents"],
                    occurred_at=p["occurred_at"], tx=tx,
                )
        # The fan's lifetime spend, in this same transaction as the row: a
        # revenue insert adds (creating the fan row); a refund / promote
        # reconcile moves an existing fan's.
        if op.lifetime_create:
            await _bump_lifetime(s, account_id, p["fan_id"], op.lifetime_delta)
        elif op.lifetime_delta:
            await _apply_lifetime_delta(s, account_id, p["fan_id"], op.lifetime_delta)
    return stamps


def _log_plan(account_id: str, ops: list[RowOp]) -> None:
    for op in ops:
        if op.action == "skip":
            log.info("ingest_tx_skip no_provider_id account=%s", account_id)
        elif op.raw_kind == "unknown":
            log.info(
                "ingest_tx_unknown_kind account=%s provider=%s description=%r",
                account_id, op.parsed["provider_id"], op.parsed["description"][:120],
            )


class _Ingested(NamedTuple):
    ops: list[RowOp]
    stamps: dict[int, tuple]   # op index -> (fan_id, message_id, cents): a PPV that linked
    wrote: bool                # a write transaction was opened (and committed)


async def _ingest_rows(account_id: str, rows: list[dict]) -> _Ingested:
    """Plan `rows` and write them. A page whose plan writes nothing (a quiet
    re-poll: every row held, every field equal; or no provider id at all) is
    read in a plain session and takes no write lock; a page with news is
    re-read and re-planned inside ONE write transaction (so the plan sees
    exactly what it writes over) and written there."""
    parsed = parse_page(rows, datetime.utcnow())
    async with get_session() as s:
        ops = (await _read_plan(s, account_id, parsed)).ops
    _log_plan(account_id, ops)
    if not any(op.writes for op in ops):
        return _Ingested(ops, {}, False)
    async with _ledger_txn() as s:
        r = await _read_plan(s, account_id, parsed)
        stamps = await _apply_ops(s, account_id, r.ops, r.held, r.ws)
    return _Ingested(r.ops, stamps, True)


async def _after_commit(account_id: str, ops: list[RowOp], stamps: dict[int, tuple]) -> None:
    """Side effects that must see the committed rows, per op in page order.
    Each op's are isolated: one that raises is logged and the rest still run
    (the rows are committed; the tick is no failure)."""
    for i, op in enumerate(ops):
        try:
            await _after_commit_op(account_id, op, stamps.get(i))
        except Exception:
            log.warning("ingest_tx_after_commit_failed account=%s provider=%s",
                        account_id, op.parsed["provider_id"], exc_info=True)


async def _after_commit_op(account_id: str, op: RowOp, stamp: tuple | None) -> None:
    # Ownership stamp for the freshly-linked PPV buy (best-effort by
    # contract — see ownership.try_stamp_message; the purchases-
    # notification poll re-stamps the same message idempotently anyway).
    if stamp is not None:
        fan_id, msg_id, cents = stamp
        await ownership.try_stamp_message(
            account_id, fan_id, msg_id, price_cents=cents, context="ingest")
    # Announce news (insert / promote / status flip) to SSE subscribers
    # AFTER the commit, so the browser's refetch can't race the write. The
    # frontend (useInboxRealtime) drops the fan drawer's revenue caches on
    # this event — without it the chart/Sales panel sits on 5-30 min
    # staleTimes after a sale.
    #
    # The 48h recency cap applies to INSERTS only (`capped`, applied by
    # events.announce_transaction): a 90-day cold backfill inserts
    # hundreds of ancient rows nobody is looking at. Status flips (a held
    # PPV settling pending→cleared days after purchase) and ledger
    # promotes only happen on rows already inside the 7-day refresh
    # window — naturally bounded, AND exactly the update the drawer is
    # waiting on. Plain re-polls (no flip) stay silent — they happen every
    # 5-min tick.
    if op.broadcast is not None and op.parsed["fan_id"]:
        from events import announce_transaction
        await announce_transaction(
            account_id, op.parsed["fan_id"], occurred_at=op.parsed["occurred_at"],
            capped=op.broadcast == "insert", kind=op.kind,
            status=op.parsed["status"], reason=op.broadcast)


async def _write_one(account_id: str, raw: dict) -> tuple[int, int]:
    """Returns (inserted, patched). One row, its own transaction (none for a
    row with nothing to write) — the page path's row-by-row fallback. See the
    module docstring for the 3-step dedup contract."""
    r = await _ingest_rows(account_id, [raw])
    await _after_commit(account_id, r.ops, r.stamps)
    return r.ops[0].result


async def _write_page(account_id: str, rows: list[dict]) -> tuple[int, int]:
    """Returns (inserted, patched) for one ledger page, written in ONE write
    transaction, or with no write transaction for a quiet re-poll (a page used to cost a
    transaction per row, plus up to two more per lifetime delta). If that
    transaction fails for a row's sake, the page is retried row by row, each
    row in its own transaction, so one bad row never blocks the rest; a row
    that fails alone is logged and skipped (the OF ledger re-serves it next
    tick). A lock timeout is re-raised instead: it would only repeat per row
    (busy_timeout each), so the tick records the failure and the next tick
    re-reads the page."""
    try:
        r = await _ingest_rows(account_id, rows)
    except Exception as exc:
        if of_writer._locked(exc):
            raise
        log.warning("ingest_tx_page_failed account=%s rows=%d (%s); retrying row by row",
                    account_id, len(rows), exc)
        inserted = patched = 0
        for raw in rows:
            try:
                ins, pat = await _write_one(account_id, raw)
            except Exception:
                log.warning(
                    "ingest_tx_write_failed account=%s provider=%s",
                    account_id, raw.get("id"), exc_info=True,
                )
                continue
            inserted += ins
            patched += pat
        return inserted, patched
    if r.wrote:
        log.info("ingest_tx_page_written account=%s rows=%d", account_id, len(rows))
    await _after_commit(account_id, r.ops, r.stamps)
    return sum(op.result[0] for op in r.ops), sum(op.result[1] for op in r.ops)


# ── Supervisor / tick ───────────────────────────────────────────────

def _client_for(account_id: str) -> OFClient | None:
    """The pooled OFClient for `account_id`, or None if it cannot be built.

    Goes through `client_pool` rather than `OFClient.from_account` so the two
    ingest ticks (300s scan, 30s fast tick) reuse one long-lived client per
    account instead of building ~18k throwaway ones a day. Each throwaway
    started with an empty connection cache — a cold TLS handshake per call plus
    a pure-overhead x-hash GET, since of_client caches x-hash per instance. It
    was also the last fd-per-call site in production, the pattern that took the
    relay to EMFILE (see client_pool's module docstring).

    Do NOT close the returned client: pooled clients are shared and long-lived,
    and eviction is the pool's job (re-bootstrap / proxy edit already call it).
    """
    try:
        return client_pool.get(account_id)
    except Exception:
        return None


async def _scan_state(s, account_id: str) -> TransactionScanHistory:
    row = await s.get(TransactionScanHistory, account_id)
    if row is None:
        row = TransactionScanHistory(account_id=account_id)
        s.add(row)
        await s.flush()
    return row


def _scan_facts(row: TransactionScanHistory) -> ScanState:
    """The row's ScanState. A not-yet-flushed row's server-defaulted columns
    read None: they take ScanState's defaults."""
    default = ScanState()
    vals = {f: getattr(row, f) for f in SCAN_FIELDS}
    return ScanState(**{f: getattr(default, f) if v is None else v for f, v in vals.items()})


async def _is_paused(account_id: str) -> bool:
    async with get_session() as s:
        row = await s.get(TransactionScanHistory, account_id)
        return is_paused(_scan_facts(row) if row is not None else None, datetime.utcnow())


async def _decide_mode(account_id: str) -> str:
    async with get_session() as s:
        row = await s.get(TransactionScanHistory, account_id)
        return decide_mode(_scan_facts(row) if row is not None else None)


def _window_for(mode: str, state: TransactionScanHistory) -> tuple[datetime, datetime]:
    """See transaction_ingest_decide.window_for."""
    return window_for(mode, _scan_facts(state), datetime.utcnow())


def _store_scan(row: TransactionScanHistory, state: ScanState) -> None:
    for f in SCAN_FIELDS:
        setattr(row, f, getattr(state, f))
    row.updated_at = datetime.utcnow()


async def _mark_interrupted(account_id: str) -> None:
    """Cleanup path for run_one_tick when neither _mark_success nor
    _record_failure ran — typically CancelledError on shutdown.

    Sets status='idle' (not 'error') so we don't auto-pause after three
    process restarts; consecutive_failures is left untouched because this
    isn't an ingest failure, it's a process interruption. Only writes if
    the row is still parked at the start-of-tick stamp, so it's safe to
    call redundantly."""
    try:
        async with get_session() as s:
            row = await _scan_state(s, account_id)
            if row.current_status in IN_FLIGHT:
                prior_status = row.current_status
                _store_scan(row, scan_interrupted(_scan_facts(row), "interrupted_mid_tick"))
                log.warning(
                    "ingest_tx_interrupted_cleanup account=%s prior_status=%s",
                    account_id, prior_status,
                )
    except BaseException:
        # Best-effort. If THIS cleanup itself is cancelled, the boot-time
        # sweep in start_supervisor() picks up the stuck row next process.
        log.warning(
            "ingest_tx_interrupted_cleanup_failed account=%s",
            account_id, exc_info=True,
        )


async def _clear_stale_inflight() -> int:
    """Boot-time sweep. Any row parked at current_status IN
    ('refreshing','backfilling') with a last_scan_at older than 60s is by
    definition stale — the asyncio.Lock that protected it lived in the
    previous process. Reset to 'idle' so the next supervisor tick +
    manual /run can proceed.

    The 60s lower bound guards against a real-but-young scan that was
    spawned via admin /run in the few ms between process boot and the
    supervisor task getting CPU time. A real scan refreshes last_scan_at
    well within 60s; only crashed/restarted scans drift past it.

    Returns count of rows reset (for the startup log)."""
    cutoff = datetime.utcnow() - timedelta(seconds=60)
    async with get_session() as s:
        rows = (await s.execute(
            select(TransactionScanHistory).where(
                TransactionScanHistory.current_status.in_(IN_FLIGHT),
                # last_scan_at IS NULL would only happen on a row that
                # somehow got status stamped without a timestamp — treat
                # it as stale too (the OR catches NULL since SQL NULL
                # comparisons against `<` are FALSE).
                (TransactionScanHistory.last_scan_at < cutoff)
                | (TransactionScanHistory.last_scan_at.is_(None)),
            )
        )).scalars().all()
        for row in rows:
            log.warning(
                "ingest_tx_boot_clear_stale account=%s status=%s last_scan_at=%s",
                row.account_id, row.current_status,
                row.last_scan_at.isoformat() if row.last_scan_at else None,
            )
            _store_scan(row, scan_interrupted(_scan_facts(row), "interrupted_before_boot"))
        return len(rows)


def _is_proxy_refusal(exc: BaseException) -> bool:
    """The proxy refused the CONNECT tunnel (curl 56, e.g. IPRoyal DC's
    transient 403; OFClient._proxy_retry already retried it). The request
    never reached OF, so it says nothing about the account or its session."""
    seen: set[int] = set()
    e: BaseException | None = exc
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        if isinstance(e, ProxyError) and "CONNECT tunnel failed" in str(e):
            return True
        e = e.__cause__ or e.__context__
    return False


async def _record_failure(account_id: str, exc: Exception) -> None:
    refusal = _is_proxy_refusal(exc)
    async with get_session() as s:
        row = await _scan_state(s, account_id)
        state = scan_after_failure(_scan_facts(row), refusal, datetime.utcnow(),
                                   error=repr(exc)[:500])
        _store_scan(row, state)
    if refusal:
        # Not counted toward the pause: the next tick retries for free.
        log.info(
            "ingest_tx_proxy_refused account=%s consecutive_failures=%d "
            "(not counted) err=%s",
            account_id, state.consecutive_failures, str(exc)[:120],
        )
    elif state.current_status == "paused":
        log.info(
            "ingest_tx_account_paused account=%s consecutive_failures=%d "
            "last_error=%s",
            account_id, state.consecutive_failures, state.last_error,
        )


async def _mark_success(
    account_id: str,
    *,
    mode: str,
    inserted: int,
    patched: int,
    last_marker: int | None,
    page_rows_min_occurred_at: datetime | None,
    page_rows_max_occurred_at: datetime | None,
    floor_reached: bool,
) -> None:
    # 'ok' (not the start-of-tick 'refreshing') so the /run endpoint's
    # collision check (status IN ('refreshing','backfilling')) only fires
    # when a tick is genuinely in flight; a backfill short of its floor
    # keeps 'backfilling' so the banner reads "still working".
    async with get_session() as s:
        row = await _scan_state(s, account_id)
        _store_scan(row, scan_after_success(
            _scan_facts(row), mode=mode, inserted=inserted, patched=patched,
            last_marker=last_marker, rows_min=page_rows_min_occurred_at,
            rows_max=page_rows_max_occurred_at, floor_reached=floor_reached,
            now=datetime.utcnow()))


async def run_one_tick(account_id: str, *, mode: str = "refresh") -> dict:
    """One supervisor tick for one account.

    refresh:  window = (utcnow - 7d, utcnow)
    backfill: window = (backfill_floor, oldest_seen_occurred_at or utcnow)

    Sleeps 0.4s between pages. Stops on empty page OR hasMore=false. Bounded
    by a per-account asyncio.Lock so a slow (>600s) tick can't stack with the
    next supervisor cycle. Returns
    {"rows_inserted": int, "rows_patched": int, "pages": int,
     "duration_ms": int, "error": str|None}."""
    # PLATFORM SEAM. Everything below this line is OF's payouts ledger: a
    # paginated walk over a dated window, with a fingerprint/promote writer and
    # a backfill state machine. Fansly has no such ledger — its only
    # creator-visible money signal is the purchases notification feed — so it
    # gets its own lane rather than a Fansly `if` in each of those steps. Both
    # lanes write the same `transactions` rows and return the same tick shape.
    if fansly_backend.is_fansly(account_id):
        t0 = time.monotonic()
        # Under the SAME per-account lock the OF path uses. The Fansly writer
        # dedups by SELECTing known provider ids and then inserting, which is
        # only atomic while one tick at a time runs for an account — and the
        # supervisor, the 30s fast poll and the admin /run endpoint can all
        # target the same account. Two overlapping ticks could otherwise both
        # miss the row and both insert it, double-counting a real sale. (The
        # partial unique index would reject the second, but as an
        # IntegrityError mid-tick, not as clean dedup.) This is the same
        # reasoning run_fast_tick documents for the OF lane.
        async with _tick_locks[account_id]:
            r = await fansly_revenue.run_one_tick(account_id)
        # The seam is where the translation to OF's tick dict belongs: `pages`
        # and `rows_patched` are OF-ledger concepts the Fansly lane has no
        # honest value for, and the clock is held here.
        return {"rows_inserted": r.rows_inserted, "rows_patched": 0, "pages": 0,
                "duration_ms": int((time.monotonic() - t0) * 1000),
                "error": r.error}
    lock = _tick_locks[account_id]
    async with lock:
        t0 = time.monotonic()
        # `finalized` tracks whether SOMETHING has overwritten the
        # start-of-tick stamp (success path → _mark_success, error path →
        # _record_failure, skip-on-stale → never stamped). If false at
        # finally entry we run _mark_interrupted as last-resort cleanup.
        # Wraps the start-stamp session too so a CancelledError landing
        # inside `async with get_session().__aexit__` (i.e., during the
        # commit await) still gets cleaned up.
        finalized = False
        try:
            async with get_session() as s:
                state = await _scan_state(s, account_id)
                # Race guard re-check inside the lock. The previous
                # `lock.locked()` peek before `async with` was racy: two
                # callers (admin /run + supervisor, or two clicks) could
                # both observe False and both queue into the lock, with the
                # second re-walking the full window after the first
                # finished. Serializing then re-reading current_status
                # catches the case where an in-flight peer (or crashed
                # prior holder) has already stamped the account.
                if state.current_status in IN_FLIGHT:
                    # Stale-timestamp escape valve. A real in-flight tick
                    # holds the lock too, so it can't get here. Anything
                    # parked at this status is from a *prior* process or
                    # crashed task. last_scan_at was stamped at tick START
                    # (see below), so its age == how long the stamp has been
                    # orphaned. Past _STALE_INFLIGHT_S it's a tombstone.
                    age_s = (
                        (datetime.utcnow() - state.last_scan_at).total_seconds()
                        if state.last_scan_at is not None
                        else _STALE_INFLIGHT_S + 1
                    )
                    if age_s < _STALE_INFLIGHT_S:
                        log.info(
                            "ingest_tx_scan_skip account=%s status=%s age_s=%.0f",
                            account_id, state.current_status, age_s,
                        )
                        # Skip path didn't touch the stamp, so we mark
                        # finalized=True to suppress the finally cleanup.
                        finalized = True
                        return {
                            "skipped": True, "rows_inserted": 0, "rows_patched": 0,
                            "pages": 0, "duration_ms": int((time.monotonic() - t0) * 1000),
                            "error": None,
                        }
                    log.warning(
                        "ingest_tx_scan_proceed_after_stale account=%s status=%s age_s=%.0f",
                        account_id, state.current_status, age_s,
                    )
                start_dt, end_dt = _window_for(mode, state)
                # Stamp last_scan_at AND current_status at tick START (see
                # scan_started; without it the schema default 'idle' makes an
                # account's first tick invisible to /run's 409 check).
                # _mark_success / _record_failure both overwrite at end,
                # AND the try/finally below catches CancelledError so the
                # stamp can't stick across process restarts.
                _store_scan(state, scan_started(_scan_facts(state), mode, start_dt, datetime.utcnow()))

            # Start stamp is committed. Every exit path below must
            # overwrite it.
            client = _client_for(account_id)
            if client is None:
                err = RuntimeError("no_session")
                log.warning("ingest_tx_no_session account=%s", account_id)
                await _record_failure(account_id, err)
                finalized = True
                return {
                    "rows_inserted": 0, "rows_patched": 0, "pages": 0,
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                    "error": "no_session",
                }

            pages = inserted = patched = 0
            offset = 0
            last_marker: int | None = None
            rows_min_ts: datetime | None = None
            rows_max_ts: datetime | None = None
            floor_reached = False
            # Repeated-page guard: some OF endpoints IGNORE `offset` and report
            # hasMore=true forever (verified live 2026-07-04 on the group-stats
            # endpoint) — without this, the loop is UNBOUNDED and wedges this
            # account's _tick_lock for good. A page whose ids we've all seen
            # means no cursor makes progress → stop WITHOUT floor_reached, so a
            # backfill never marks itself complete off a truncated scan.
            seen_tx_ids: set = set()
            _PAGE_CEILING = 500  # 500 × 100 rows — far past any real window

            try:
                log.info(
                    "ingest_tx_scan_start account=%s mode=%s start=%s end=%s",
                    account_id, mode, start_dt.isoformat(), end_dt.isoformat(),
                )
                while True:
                    if pages >= _PAGE_CEILING:
                        log.warning(
                            "ingest_tx_page_ceiling account=%s pages=%d — scan truncated",
                            account_id, pages,
                        )
                        break
                    # NO `type=` — capture proves it's a filter, not a partition
                    # (synthesis §2 row 5). One unfiltered request per page.
                    resp = await asyncio.to_thread(
                        client.transactions,
                        limit=_PAGE_LIMIT,
                        offset=offset,
                        start=start_dt.isoformat(),
                        end=end_dt.isoformat(),
                    )
                    rows = resp.get("list") or []
                    marker = resp.get("nextMarker")
                    if marker is not None:
                        last_marker = marker
                    log.info(
                        "ingest_tx_page_fetched account=%s page=%d count=%d marker=%s",
                        account_id, pages, len(rows), marker,
                    )
                    if not rows:
                        floor_reached = True
                        break
                    page_ids = {raw.get("id") for raw in rows if raw.get("id") is not None}
                    if page_ids and page_ids <= seen_tx_ids:
                        log.warning(
                            "ingest_tx_repeated_page account=%s page=%d offset=%d — "
                            "OF ignored the offset cursor; stopping scan",
                            account_id, pages, offset,
                        )
                        break
                    seen_tx_ids |= page_ids
                    for raw in rows:
                        occ = _parse_iso(raw.get("createdAt"))
                        if occ is not None:
                            if rows_min_ts is None or occ < rows_min_ts:
                                rows_min_ts = occ
                            if rows_max_ts is None or occ > rows_max_ts:
                                rows_max_ts = occ
                    # One write transaction for the page; row by row only
                    # if that fails (never raises for a row).
                    ins, pat = await _write_page(account_id, rows)
                    inserted += ins
                    patched += pat
                    pages += 1
                    if not resp.get("hasMore"):
                        floor_reached = True
                        break
                    offset += len(rows)
                    await asyncio.sleep(_PAGE_SLEEP_S)
            except Exception as e:
                if not _is_proxy_refusal(e):  # a refusal logs one line in _record_failure
                    log.warning("ingest_tx_scan_failed account=%s", account_id, exc_info=True)
                await _record_failure(account_id, e)
                finalized = True
                return {
                    "rows_inserted": inserted, "rows_patched": patched,
                    "pages": pages,
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                    "error": repr(e),
                }

            await _mark_success(
                account_id,
                mode=mode,
                inserted=inserted,
                patched=patched,
                last_marker=last_marker,
                page_rows_min_occurred_at=rows_min_ts,
                page_rows_max_occurred_at=rows_max_ts,
                floor_reached=floor_reached,
            )
            finalized = True

            # Relink: retry the payment→message link for recent orphaned chat
            # PPVs whose message row arrived AFTER the transaction did (scrape
            # lag, WS gap): a linked sale gets its sender (Message sender) and
            # its message's automation kind. newest-first + bounded limit so
            # permanently-ambiguous rows in the window can't starve fresh
            # linkable ones. Best-effort: a failure never fails the scan.
            try:
                rl = await relink_orphan_ppvs(
                    account_id=account_id,
                    since=datetime.utcnow() - timedelta(days=_ATTR_SWEEP_SINCE_DAYS),
                    limit=200,
                )
                if rl["linked"] or rl["ambiguous_skipped"]:
                    log.info(
                        "ingest_tx_relink_sweep account=%s linked=%d ambiguous=%d "
                        "no_candidate=%d conflicts=%d",
                        account_id, rl["linked"], rl["ambiguous_skipped"],
                        rl["no_candidate"], rl["conflict_skipped"],
                    )
            except Exception:
                log.warning(
                    "ingest_tx_relink_sweep_failed account=%s", account_id,
                    exc_info=True,
                )

            # Wall-POST ownership belt: the ledger's ppv_post row names WHO and
            # HOW MUCH but never WHICH post — only the purchases-notification
            # feed carries the post id. The 30s fast poll parses it live, but
            # that loop is GATED (selling automations ∪ online principals), so
            # an account selling only off its wall would never stamp. Whenever
            # this account has a recent ppv_post txn, re-read the feed here —
            # stamping is idempotent, and the announce channel this also feeds
            # is DEDUPED against the fast poll (not absent from this path).
            try:
                recent_post_buy = await _has_recent_post_txn(
                    account_id,
                    since=datetime.utcnow()
                    - timedelta(days=_POST_OWNERSHIP_SINCE_DAYS),
                )
                if recent_post_buy:
                    pn = await purchase_notifications.poll_purchases(
                        account_id, client, limit=50)
                    if pn.get("posts") or pn.get("stamped"):
                        log.info(
                            "ingest_tx_post_ownership_sweep account=%s %s",
                            account_id, pn,
                        )
            except Exception:
                log.warning(
                    "ingest_tx_post_ownership_sweep_failed account=%s",
                    account_id, exc_info=True,
                )

            dur_ms = int((time.monotonic() - t0) * 1000)
            log.info(
                "ingest_tx_scan_end account=%s mode=%s pages=%d inserted=%d "
                "patched=%d duration_ms=%d",
                account_id, mode, pages, inserted, patched, dur_ms,
            )
            return {
                "rows_inserted": inserted, "rows_patched": patched,
                "pages": pages, "duration_ms": dur_ms, "error": None,
            }
        finally:
            # Catches CancelledError (uvicorn reload, deploy, supervisor
            # cancel) and any BaseException so the start-of-tick stamp
            # doesn't strand the account at 'refreshing'/'backfilling'.
            # `finalized` is True iff _mark_success or _record_failure
            # already overwrote the stamp.
            if not finalized:
                await _mark_interrupted(account_id)


# ── Fast freshness poll (30s) ────────────────────────────────────────
# Layered ON TOP of the 5-min supervisor: one tiny request per online/selling
# account reading OF's purchases notification feed, so a PPV unlock flips
# `messages.is_paid` within ~30s and the automations see the payment the tick
# after the fan pays. The supervisor owns the ledger: the authoritative 7-day
# window, relink sweep, orphan attribution, and backfill.
#
# This tick used to ALSO re-read the newest ledger page every 30s. The ledger
# lands hours late (measured 209/560/628 min), so a 30s read of it bought no
# freshness over the 5-min supervisor and cost 120 OF calls an hour per selling
# account (about 40% of its OF traffic). A DM tip is recorded instantly off the
# WS pump (event_transcoder); a purchase is seen off the feed below.
_FAST_TICK_INTERVAL_S = 30
_FAST_PAGE_LIMIT = 10
# Accounts polled at once, and the gap between their starts. One account's
# tick is ~0.7 s of OF round-trip, so walking 20 one by one took ~14 s of the
# 30 s period and told the last account about a payment ~14 s late. Five at a
# time, starts STAGGER_S apart so a fleet never hits OF in the same second:
# 20 accounts finish in ~4.5 s. Each account still makes one call per tick,
# inside its own OF lane (purchase_notifications._of_lane), so this adds at
# most five threads to the shared executor.
_FAST_POLL_CONCURRENCY = 5
_FAST_POLL_STAGGER_S = 0.2


async def run_fast_tick(account_id: str) -> dict:
    """One freshness poll for one account: the newest _FAST_PAGE_LIMIT purchase
    notifications (single request). Writes NO money on OF — see above."""
    # PLATFORM SEAM, mirroring run_one_tick's. Without it a Fansly account
    # fell straight through to `_client_for` -> no OFClient -> "no_session"
    # every 30 seconds forever: a permanently dead path. That is not merely a
    # wasted call — this loop exists so a SELLING automation learns about a
    # payment in seconds rather than minutes (see _fast_poll_account_ids), and
    # on Fansly the purchases feed IS the payment signal. Skipping it left
    # Fansly sellers on the 5-minute supervisor cadence, still saying "waiting
    # on your tip" to a fan who had already paid. The read is cheap here: one
    # un-paginated page, already TTL-cached in the shim.
    if fansly_backend.is_fansly(account_id):
        async with _tick_locks[account_id]:
            r = await fansly_revenue.run_one_tick(account_id)
        return {"rows_inserted": r.rows_inserted, "rows_patched": 0,
                "error": r.error}
    client = _client_for(account_id)
    if client is None:
        return {"rows_inserted": 0, "rows_patched": 0, "error": "no_session"}
    # OF's purchases notification names the exact message id the moment it is
    # paid — flipping is_paid off it lets every reader of `messages.is_paid` see
    # the buy on its next tick. Writes NO money: the ledger (supervisor) stays the
    # sole revenue writer, so nothing here can double-count. Never raises.
    await purchase_notifications.poll_purchases(
        account_id, client, limit=_FAST_PAGE_LIMIT)
    return {"rows_inserted": 0, "rows_patched": 0, "error": None}


async def start_fast_poll() -> None:
    """30s freshness loop — see run_fast_tick. Same online-gate and pause
    respect as the main supervisor (idle dashboards ⇒ no proxy burn; an account
    the supervisor backed off after 3 fails stays skipped). Accounts run
    _FAST_POLL_CONCURRENCY at a time, starts _FAST_POLL_STAGGER_S apart —
    bounded OF load without the last account waiting out the whole fleet.
    Sleep AT END so the gap is _FAST_TICK_INTERVAL_S regardless of cycle
    duration."""
    log.info("ingest_tx_fast_poll_started tick=%ds limit=%d",
             _FAST_TICK_INTERVAL_S, _FAST_PAGE_LIMIT)
    # One tick interval of politeness, once, so the first fleet walk does not
    # land on top of the pumps still connecting. See _FAST_BOOT_GRACE_S.
    await boot_grace(_FAST_BOOT_GRACE_S, name="ingest-fast-poll")
    while True:
        try:
            cycle_started = time.monotonic()
            off = await account_health.deactivated_ids()
            account_ids = [
                m["id"] for m in account_registry.list_accounts()
                if m.get("has_session") and m["id"] not in off
            ]
            wanted = await _fast_poll_account_ids()
            account_ids = [aid for aid in account_ids
                           if aid in wanted and not await _is_paused(aid)]
            sem = asyncio.Semaphore(_FAST_POLL_CONCURRENCY)

            async def _fast(i: int, aid: str) -> None:
                await asyncio.sleep(i * _FAST_POLL_STAGGER_S)
                async with sem:
                    try:
                        await run_fast_tick(aid)
                    except Exception as e:
                        # RECORD it, don't just whisper. This was `log.debug` and
                        # nothing else, which was harmless while run_fast_tick
                        # swallowed its own fetch errors into an error dict — the
                        # only way here was a bug, not a dead session. The Fansly
                        # lane raises on a feed failure by design (its silence is
                        # unrecoverable lost sales), so an unrecorded catch here
                        # meant a dead Fansly session failed 120 times an hour,
                        # never incremented consecutive_failures, never paused,
                        # and never showed on the admin dashboard.
                        log.warning(
                            "ingest_tx_fast_cycle_account_failed account=%s",
                            aid, exc_info=True)
                        await _record_failure(aid, e)

            await asyncio.gather(*(_fast(i, a) for i, a in enumerate(account_ids)))
            elapsed = time.monotonic() - cycle_started
            await asyncio.sleep(max(_MIN_CYCLE_GAP_S, _FAST_TICK_INTERVAL_S - elapsed))
        except asyncio.CancelledError:
            return
        except Exception:
            log.warning("ingest_tx_fast_poll cycle failed", exc_info=True)
            await asyncio.sleep(_FAST_TICK_INTERVAL_S)


# Automations whose behaviour changes the moment a fan pays: they hold an open
# offer, or they gate on spend. For these, "did he buy?" is the purchases
# notification feed the fast tick reads (`messages.is_paid`) — the WS pump
# catches ~0 unlock events and the ledger lands hours late. They run around the
# clock, so their purchase detection cannot wait for someone to open the app.
_SELLING_KINDS = ("welcome_chatter_for_info", "ppv_send", "reengage_buyers")


async def _fast_poll_account_ids() -> set[str]:
    """Accounts the 30s loop should cover.

    Two independent reasons to poll fast, unioned:

      • a SELLING automation is enabled on the account — it may be sitting on an
        open offer right now, and the only fresh "he paid" signal is OF's
        purchases notification. At 5-minute granularity the AI keeps saying "waiting on your tip"
        and re-offering content the fan already bought, at 3am with nobody
        watching. This half does NOT depend on anyone being online.
      • somebody is actually looking at the account — dashboard freshness, the
        original reason this loop was gated at all.

    So an idle, non-selling account still costs nothing when no one is around,
    but a live seller never learns about a purchase late.
    """
    async with get_session() as s:
        selling = {r[0] for r in (await s.execute(
            select(AutomationRule.account_id)
            .where(AutomationRule.kind.in_(_SELLING_KINDS),
                   AutomationRule.is_enabled.is_(True))
        )).all()}
    return selling | await _online_account_ids()


async def _online_account_ids() -> set[str]:
    """Union of OF accounts visible to any principal active within the last
    _ONLINE_WINDOW_S seconds.

    Sources combined:
      • ADMINS (users.is_admin + last_seen_at) → EVERY account. An admin sees
        the whole roster in the UI, so scoping their tick to the accounts they
        happen to be listed against in `user_accounts` silently starves the
        rest. That is not hypothetical: Sophiepaid had NO user_accounts row at
        all and Ellapaid's owner was offline, so neither account's ledger was
        ever scanned — no `transactions` rows, an empty PPV chart on every one
        of their fans, and `fans.lifetime_spend_cents` frozen at 0 (which also
        starves the welcome_chatter_for_info "hand payers to humans" gate). Ownership is NOT
        the right lever for "should this run": a live, connected account must
        be ingested regardless of who is listed as its owner.
      • owners (users.last_seen_at) → user_accounts.account_id
      • chatters (chatters.last_seen_at + is_active=True) →
            chatter_users → user_accounts.account_id

    Non-admin principals stay scoped to their own accounts, so a multi-tenant
    box doesn't burn one agency's proxy because another agency is online.

    ⚠️ FAST-POLL ONLY. The 5-minute supervisor deliberately does NOT consult
    this: it is the sole writer of the `transactions` ledger that
    `fans.lifetime_spend_cents` — and therefore every automation's spend
    decision — is derived from, and automations run whether or not anyone is
    watching. Only the 30s freshness loop, which exists purely so an open
    dashboard updates quickly, may be skipped when nobody is looking.

    Empty set ⇒ nobody's online; the fast poll skips this tick. The
    /admin/ingest/transactions/{aid}/run admin endpoint stays unaffected —
    a manual re-sync is an explicit user gesture and bypasses this gate.
    """
    cutoff = datetime.utcnow() - timedelta(seconds=_ONLINE_WINDOW_S)
    async with get_session() as s:
        admin_online = (await s.execute(
            select(User.id).where(User.last_seen_at >= cutoff,
                                  User.is_admin.is_(True)).limit(1)
        )).first()
        if admin_online:
            # Every known account — the per-account `has_session` / paused
            # filters in the callers still decide what actually gets scanned.
            return {r[0] for r in (await s.execute(select(Account.id))).all()}
        owner_rows = (await s.execute(
            select(UserAccount.account_id)
            .join(User, User.id == UserAccount.user_id)
            .where(User.last_seen_at >= cutoff)
        )).all()
        chatter_rows = (await s.execute(
            select(UserAccount.account_id)
            .join(ChatterUser, ChatterUser.user_id == UserAccount.user_id)
            .join(Chatter, Chatter.id == ChatterUser.chatter_id)
            .where(Chatter.last_seen_at >= cutoff)
            .where(Chatter.is_active.is_(True))
        )).all()
    return {r[0] for r in owner_rows} | {r[0] for r in chatter_rows}


async def trigger_backfill(account_id: str, *, since: datetime | None = None) -> None:
    """Reset backfill bookkeeping so the next supervisor tick walks back from
    now to `since` (defaults to utcnow - 90d). Idempotent.

    Clears `oldest_seen_occurred_at` too: a backfill walks from there down to
    the floor, so on an account that was ever fully backfilled the window would
    sit wholly below `since` and skip the very gap asked for (a Creator
    reactivated after weeks off). Re-walking rows already held is harmless —
    the writer dedups on provider id."""
    floor = since or (datetime.utcnow() - timedelta(days=_DEFAULT_BACKFILL_DAYS))
    async with get_session() as s:
        row = await _scan_state(s, account_id)
        row.backfill_floor = floor
        row.oldest_seen_occurred_at = None
        row.fully_backfilled = False
        # Not "backfilling": run_one_tick reads that as a tick in flight and
        # skips the account for _STALE_INFLIGHT_S. The tick stamps it itself.
        row.current_status = "idle"
        row.paused_until = None
        row.consecutive_failures = 0
        row.updated_at = datetime.utcnow()


async def backfill_after_reactivation(account_id: str, deactivated_at: datetime) -> bool:
    """A Creator was just reactivated after being off since `deactivated_at`.
    A gap inside the rolling refresh window is re-read by the next refresh
    tick anyway; a longer one is backfilled from `deactivated_at` on. True
    when a backfill was queued."""
    if datetime.utcnow() - deactivated_at <= timedelta(days=_ROLLING_WINDOW_DAYS):
        return False
    await trigger_backfill(account_id, since=deactivated_at)
    return True


async def start_supervisor() -> None:
    """Async supervisor loop. Mirror of `_perflog_evictor_loop` shape
    (service/server.py:1374-1394): sleep inside try, return on
    CancelledError, log + continue on other exceptions.

    Refresh ticks strictly sequential (SQLite WAL serializes writes anyway,
    and we want bounded concurrent OF load). Backfill ticks may run up to
    _BACKFILL_CONCURRENCY in parallel — synthesis review §4: a 30-account
    cold-start drops from ~100min to ~25min."""
    log.info(
        "ingest_tx_supervisor_started tick=%ds window=%dd backfill=%dd",
        _TICK_INTERVAL_S, _ROLLING_WINDOW_DAYS, _DEFAULT_BACKFILL_DAYS,
    )
    # Boot-time sweep: clear any rows parked at 'refreshing'/'backfilling'
    # from the previous process. The asyncio.Lock that protected them is
    # gone; the stamp is by definition a tombstone. Without this sweep
    # both the /run endpoint's 409 guard and the lock-internal guard in
    # run_one_tick lock the account out until the stale-age escape (15min)
    # kicks in. Sweep makes the recovery instant.
    try:
        cleared = await _clear_stale_inflight()
        if cleared:
            log.warning("ingest_tx_supervisor_boot_cleared count=%d", cleared)
    except Exception:
        # A failed sweep doesn't block startup; the stale-age escape
        # valve is the second line of defense.
        log.warning("ingest_tx_supervisor_boot_sweep_failed", exc_info=True)
    # AFTER the sweep, never before it: the sweep is a single cheap UPDATE that
    # unlocks accounts the previous process left stamped in-flight, and holding
    # it for the grace would leave /run 409-ing for that whole window. The grace
    # covers the expensive part — the fleet walk below. See _BOOT_GRACE_S.
    await boot_grace(_BOOT_GRACE_S, name="ingest-supervisor")
    # Sleep AT END so the inter-scan gap is _TICK_INTERVAL_S regardless
    # of how long the cycle took. Original code slept first, so a slow
    # cycle pushed the last-account stamp to (_TICK_INTERVAL_S + duration)
    # past the prior cycle — for sequential 3-account walks that drifted
    # straight past the 30-min green-tier ceiling.
    while True:
        try:
            cycle_started = time.monotonic()
            off = await account_health.deactivated_ids()
            account_ids = [
                m["id"] for m in account_registry.list_accounts()
                if m.get("has_session") and m["id"] not in off
            ]
            # NO online gate here. This loop is not a dashboard convenience —
            # it is the only writer of the `transactions` ledger, and
            # `event_transcoder` bumps `fans.lifetime_spend_cents` off those
            # rows. The AUTOMATIONS run 24/7 with no online gate of their own
            # (automation_executor never consults one) and read that number to
            # decide real money questions: the whale gate
            # (max_lifetime_spend_cents), welcome_chatter_for_info's hand-to-human
            # gate. Gating the producer on "is a human watching" while the
            # consumers never stop meant that with every dashboard closed, a fan
            # who had already blown past the whale cap still read as $0 and the
            # AI kept selling to him. Freshness for a watching human is what the
            # 30s fast poll is for — THAT one keeps the online gate.
            if not account_ids:
                elapsed = time.monotonic() - cycle_started
                await asyncio.sleep(max(_MIN_CYCLE_GAP_S, _TICK_INTERVAL_S - elapsed))
                continue
            refresh_aids: list[str] = []
            backfill_aids: list[str] = []
            for aid in account_ids:
                if await _is_paused(aid):
                    continue
                if (await _decide_mode(aid)) == "backfill":
                    backfill_aids.append(aid)
                else:
                    refresh_aids.append(aid)

            for aid in refresh_aids:
                try:
                    await run_one_tick(aid, mode="refresh")
                except Exception as e:
                    log.warning("ingest_tx_scan failed account=%s", aid, exc_info=True)
                    await _record_failure(aid, e)

            if backfill_aids:
                sem = asyncio.Semaphore(_BACKFILL_CONCURRENCY)

                async def _bf(aid: str) -> None:
                    async with sem:
                        try:
                            await run_one_tick(aid, mode="backfill")
                        except Exception as e:
                            log.warning(
                                "ingest_tx_backfill failed account=%s",
                                aid, exc_info=True,
                            )
                            await _record_failure(aid, e)

                await asyncio.gather(*(_bf(a) for a in backfill_aids))

            elapsed = time.monotonic() - cycle_started
            await asyncio.sleep(max(_MIN_CYCLE_GAP_S, _TICK_INTERVAL_S - elapsed))
        except asyncio.CancelledError:
            return
        except Exception:
            log.warning("ingest supervisor cycle failed", exc_info=True)
            await asyncio.sleep(_TICK_INTERVAL_S)
