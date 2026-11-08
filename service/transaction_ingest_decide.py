"""
The ledger ingest's decisions, pure: no DB, no OF, no clock of its own (the
caller passes `now`).

`transaction_ingest` parses a page once (`_parse_row`), reads what the page needs
(the rows already held by provider id, the WS-pump tips a ledger tip may be the
twin of — `tip_window` — and the fans that already subscribed — `subscription_fans`),
asks `plan_page` what to do with each OF row, and opens ONE write transaction
only if some op writes. The scan bookkeeping (`scan_started`, `scan_interrupted`,
`scan_after_failure`, `scan_after_success`, `scan_backfill_page`, `scan_seeded`, `window_for`,
`decide_mode`, `full_phase_s`, `full_bucket`, `recent_start_date`, `backfill_step`,
`marker_of`, `page_span`) is the same split: these compute the next state,
`transaction_ingest` reads and writes the row.

Everything here is re-exported by `transaction_ingest`, so its importers keep
reading `transaction_ingest._classify_kind` and friends.
"""
from __future__ import annotations

import calendar
import math
import zlib
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Iterable, Literal, NamedTuple

from attribution_backfill import SETTLED_REVERSALS
from of_coerce import cents_or_none as _to_cents, strip_tags as _strip_html

# ── Kind catalog (HTML-stripped description prefix -> kind) ─────────
# Order matters — match top-to-bottom. Public so the admin
# /unknown-kinds endpoint can render the prefix table.
KIND_CATALOG: tuple[tuple[str, str], ...] = (
    # OF's vocab: "Subscription from X" = first charge (new sub);
    # "Recurring subscription from X" = monthly renewal. Verified
    # against the data: of 57 fans with both labels, 56 had the plain
    # "Subscription from" row strictly earlier than "Recurring".
    # Mapping directly from the prefix beats the rebill-promote
    # heuristic — that heuristic depends on insertion order and quietly
    # fails when historical backfill writes newest-first.
    ("Recurring subscription from ", "rebill"),        # explicit renewal
    ("Subscription from ",           "subscription"),  # first charge; promoted by safety net
    ("Tip in chat from ",            "tip"),
    ("Tip from ",                    "tip"),
    ("Tip on post from ",            "tip_post"),
    ("Tip on stream from ",          "tip_stream"),
    ("Payment for message from ",    "ppv_message"),   # OF's actual prefix for PPV unlocks
    ("Message from ",                "ppv_message"),
    ("Post from ",                   "ppv_post"),
    ("Post purchase by ",            "ppv_post"),       # OF's actual ledger prefix for feed-post unlocks
    ("Stream from ",                 "ppv_stream"),
    ("Custom request from ",         "custom"),
    ("Custom from ",                 "custom"),
)

# OF's status vocab differs from the original capture. Map to Phase F vocab.
_STATUS_MAP = {
    "done":           "cleared",
    "loading":        "pending",
    "undo":           "chargedback",
    "pending_return": "refund_pending",
}

_REFUND_STATUSES = SETTLED_REVERSALS
_NON_REVENUE_STATUSES = (*SETTLED_REVERSALS, "failed")

# Gated dead code. Flip to True when Planner B's WS dispatcher PR starts
# writing kind='ppv_pending' rows on unlock events (synthesis §5 line 193).
_ENABLE_PPV_FINGERPRINT = False

# WS-pump sibling tolerance: amount +/- max(10c, 1%) for OF fee rounding
# ($5.00 -> $4.99 net); time +/- 300s for WS-vs-ledger clock drift.
_FINGERPRINT_WINDOW = timedelta(seconds=300)

# Scan state machine.
_ROLLING_WINDOW_DAYS = 7
# Ledger walk cadence (transaction_ingest resolves the env knobs, see there): every
# tick walks the trailing _DEFAULT_RECENT_WINDOW_H (`recent`); the full 7-day
# `refresh` runs on the first tick of each _DEFAULT_FULL_EVERY_S period, each
# account's periods shifted by its own phase (`full_bucket`). Plain literals
# (soak/timing/knobs.py reads them).
_DEFAULT_RECENT_WINDOW_H = 24.0
_DEFAULT_FULL_EVERY_S = 7200.0
_EPOCH = datetime(1970, 1, 1)
_DEFAULT_BACKFILL_DAYS = 90
_FAIL_BACKOFF_S = 1800                  # auto-pause 30 min after 3 real fails = two
                                        # 900 s ticks skipped (below a tick it only
                                        # relabelled); a proxy CONNECT refusal never counts
_FAILS_BEFORE_PAUSE = 3
# The marker walk's bounds. Per tick: at OF's measured ~1.4 s a page + 0.4 s sleep + a write, ~2 s a
# page, 40 pages = 4,000 rows in ~80 s, under _STALE_INFLIGHT_S (720 s) even with 429 waits, and 2 at
# once add at most 2 x ~0.5 calls/s (5-10k rows: 2-3 ticks).
# No total ceiling: each page's marker strictly decreases, down to startDate (a row below it stops
# the walk); a page of nothing new, or a stuck marker, stops the tick. The cursor moves down within a
# walk; scan_backfill_restart, scan_started and trigger_backfill clear it: at most one re-walk an outage.
_BACKFILL_TICK_PAGES = 40
# A resumed tick's recent read: its offset paging ends at OF's offset cap (600 rows) anyway.
_BACKFILL_FRESH_PAGES = 6
BACKFILL_PARTIAL = "backfill_partial"   # between ticks: never IN_FLIGHT, or the next tick would skip
BACKFILL_STALLED = "backfill_stalled"   # stopped short of done, not the tick cap
_STALLED_PREFIX = "backfill_stopped: "


def _normalize_status(raw_status: str | None) -> str:
    if not raw_status:
        return "cleared"
    return _STATUS_MAP.get(raw_status, raw_status)


# ── Parsing helpers ─────────────────────────────────────────────────

def _classify_kind(description: str | None) -> str:
    text_ = _strip_html(description) if description and "<" in description else (description or "").strip()
    for prefix, kind in KIND_CATALOG:
        if text_.startswith(prefix):
            return kind
    return "unknown"


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _parse_row(raw: dict, now: datetime) -> dict:
    """Map an OF /payouts/transactions row to the local-column dict (`now`
    stands in for a missing createdAt). The row itself is not kept — see
    `Transaction.raw_json`."""
    user = raw.get("user") or {}
    return {
        "provider_id": raw.get("id"),
        "fan_id": user.get("id"),
        "amount_cents": _to_cents(raw.get("amount")) or 0,
        "currency": raw.get("currency") or "USD",
        "occurred_at": _parse_iso(raw.get("createdAt")) or now,
        "status": _normalize_status(raw.get("status")),
        "cleared_at": _parse_iso(raw.get("clearedAt")) if raw.get("clearedAt") else None,
        "payout_pending_days": raw.get("payoutPendingDays"),
        "net_cents": _to_cents(raw.get("net")),
        "fee_cents": _to_cents(raw.get("fee")),
        "vat_cents": _to_cents(raw.get("vatAmount")),
        "description": _strip_html(raw.get("description") or ""),
    }


# ── Page plan ───────────────────────────────────────────────────────

class Existing(NamedTuple):
    """A `transactions` row already held for a provider id (step 1): the
    columns a re-poll / promote overwrites from the ledger (parsed keys ==
    Transaction column names). A re-poll with every one equal writes nothing."""
    status: str
    cleared_at: datetime | None
    amount_cents: int
    net_cents: int | None
    fee_cents: int | None
    vat_cents: int | None
    description: str | None
    payout_pending_days: int | None

    @classmethod
    def of(cls, p: dict) -> Existing:
        """A parsed row's values (what the row holds once written)."""
        return cls(**{f: p[f] for f in cls._fields})


PATCH_FIELDS = Existing._fields


@dataclass(frozen=True)
class WsTip:
    """A WS-pump tip row with no provider id yet (step 2's candidates)."""
    id: int
    fan_id: int
    amount_cents: int
    occurred_at: datetime


Action = Literal["insert", "patch", "promote", "noop", "skip"]
Reason = Literal["insert", "status_flip", "ledger_promote"]


@dataclass(frozen=True)
class RowOp:
    """What to do with one OF ledger row.

    action: insert (step 3) | patch (step 1: a field changed, e.g. a status
            flip) | noop (step 1: a re-poll with every field equal — writes
            nothing) | promote (step 2: adopt the WS twin `target_id`) |
            skip (no provider id).
    lifetime_delta: signed change to the fan's lifetime_spend_cents in the
        row's own transaction. `lifetime_create` (a fresh revenue insert) adds
        it and creates the fan row if missing; otherwise (a patch's refund, a
        promote's reconcile) it applies only to an existing fan, clamped at 0.
    link_ppv: try the payment -> message link (and stamp ownership after the
        commit if it linked). synth_tip: write the inline tip message.
    broadcast: why the row is news, for SSE (events caps an insert at 48 h)."""
    action: Action
    parsed: dict
    kind: str
    target_id: int | None = None
    status_flip: tuple[str, str] | None = None
    lifetime_delta: int = 0
    lifetime_create: bool = False
    link_ppv: bool = False
    synth_tip: bool = False
    broadcast: Reason | None = None

    @property
    def raw_kind(self) -> str:
        """The row's own kind (`kind` may promote a subscription to a rebill)."""
        return self.parsed["raw_kind"]

    @property
    def writes(self) -> bool:
        return self.action in ("insert", "patch", "promote")

    @property
    def result(self) -> tuple[int, int]:
        """(inserted, patched) for the tick's counters (a noop re-poll counts as patched)."""
        if self.action == "insert":
            return (1, 0)
        return (0, 0) if self.action == "skip" else (0, 1)


def _fingerprint_eligible(kind: str) -> bool:
    """Step 2 applies to chat tips (and gated PPVs) only."""
    return kind == "tip" or (_ENABLE_PPV_FINGERPRINT and kind.startswith("ppv"))


def tip_window(parsed: list[dict], held: Iterable[str]) -> tuple[set[int], datetime, datetime] | None:
    """The WS-tip read step 2 needs: (fans, from, to) over the page's rows
    that are fingerprint-eligible, have a fan and are not `held` by provider
    id; None if there are none."""
    held = set(held)
    tips = [p for p in parsed if p["provider_id"] and p["fan_id"] and str(p["provider_id"]) not in held
            and _fingerprint_eligible(p["raw_kind"])]
    if not tips:
        return None
    at = [p["occurred_at"] for p in tips]
    return ({p["fan_id"] for p in tips}, min(at) - _FINGERPRINT_WINDOW, max(at) + _FINGERPRINT_WINDOW)


def subscription_fans(parsed: list[dict]) -> set[int]:
    """Fans with a first-charge subscription row in the page (rebill candidates)."""
    return {p["fan_id"] for p in parsed if p["fan_id"] and p["raw_kind"] == "subscription"}


def parse_page(rows: list[dict], now: datetime) -> list[dict]:
    """A ledger page parsed once: each row's `_parse_row` dict plus its
    `raw_kind` (classified once). Everything below reads these."""
    out = []
    for raw in rows:
        p = _parse_row(raw, now)
        p["raw_kind"] = _classify_kind(p["description"])
        out.append(p)
    return out


def _fingerprint_match(parsed: dict, candidates: Iterable[WsTip], taken: set[int]) -> WsTip | None:
    """The newest WS tip of this fan within the amount / time tolerance."""
    fan_id, amount = parsed["fan_id"], parsed["amount_cents"]
    if not fan_id:
        return None
    tol = max(10, amount // 100)
    at = parsed["occurred_at"]
    best = None
    for c in candidates:
        if (c.id in taken or c.fan_id != fan_id or abs(c.amount_cents - amount) > tol
                or abs(c.occurred_at - at) > _FINGERPRINT_WINDOW):
            continue
        if best is None or c.occurred_at > best.occurred_at:
            best = c
    return best


def plan_page(
    parsed: list[dict],
    existing_by_provider: dict[str, Existing],
    fingerprints: Iterable[WsTip],
    *,
    subscribed_fans: Iterable[int] = (),
) -> list[RowOp]:
    """One RowOp per `parse_page` row, in page order, as if each
    row were written and committed before the next (a provider id twice in a
    page: the second is a re-poll of the first; a fan's second subscription in
    a page is a rebill).

    3-step dedupe: provider id -> WS twin fingerprint (chat tips) -> insert.
    Lifetime follows "is the row in a settled reversal" (chargedback |
    refunded), so any oscillation nets to 0: +amount on a revenue insert only;
    never on a plain re-poll; a flip INTO a settled reversal takes the previous
    amount off, a flip OUT of one (to anything else, `failed` included) puts it
    back (a dispute OF lost, or the chargebacks poll's flip the ledger still
    calls `done`). The deduct clamps the counter at 0, so a reinstate can
    overshoot a fan whose counter was already below the amount. A promote
    reconciles the WS amount to the ledger's, or takes the WS amount off when
    the ledger row is already non-revenue (the WS pump bumped it)."""
    existing = {str(k): v for k, v in existing_by_provider.items()}
    candidates = list(fingerprints)
    taken: set[int] = set()
    subscribed = set(subscribed_fans)
    ops: list[RowOp] = []
    for p in parsed:
        raw_kind = p["raw_kind"]
        pid, fan = p["provider_id"], p["fan_id"]
        if not pid:
            ops.append(RowOp("skip", p, raw_kind))
            continue
        kind = "rebill" if raw_kind == "subscription" and fan and fan in subscribed else raw_kind
        key = str(pid)   # the column is text; OF may send the id as a number
        prev = existing.get(key)
        seen = Existing.of(p)
        if prev is not None:
            if prev == seen:
                ops.append(RowOp("noop", p, kind))
                continue
            flip = (prev.status, p["status"]) if prev.status != p["status"] else None
            delta = 0
            if fan and p["status"] in _REFUND_STATUSES and prev.status not in _REFUND_STATUSES:
                delta = -prev.amount_cents
            elif fan and prev.status in _REFUND_STATUSES and p["status"] not in _REFUND_STATUSES:
                delta = prev.amount_cents
            ops.append(RowOp("patch", p, kind, status_flip=flip, lifetime_delta=delta,
                             broadcast="status_flip" if flip else None))
            existing[key] = seen
            continue
        ws = _fingerprint_match(p, candidates, taken) if _fingerprint_eligible(raw_kind) else None
        if ws is not None:
            taken.add(ws.id)
            if not fan:
                delta = 0
            elif p["status"] in _NON_REVENUE_STATUSES:
                delta = -ws.amount_cents
            else:
                delta = p["amount_cents"] - ws.amount_cents
            ops.append(RowOp("promote", p, kind, target_id=ws.id, lifetime_delta=delta,
                             broadcast="ledger_promote"))
            existing[key] = seen
            continue
        revenue = bool(fan) and p["status"] not in _NON_REVENUE_STATUSES
        ops.append(RowOp("insert", p, kind,
                         lifetime_delta=p["amount_cents"] if revenue else 0, lifetime_create=revenue,
                         link_ppv=kind == "ppv_message" and bool(fan),
                         synth_tip=revenue and kind == "tip", broadcast="insert"))
        existing[key] = seen
        if fan and kind in ("subscription", "rebill"):
            subscribed.add(fan)
    return ops


# ── Scan state machine ──────────────────────────────────────────────

@dataclass(frozen=True)
class ScanState:
    """The `transaction_scan_history` columns the scan decides on."""
    consecutive_failures: int = 0
    paused_until: datetime | None = None
    current_status: str = "idle"
    last_error: str | None = None
    last_scan_at: datetime | None = None
    last_marker: int | None = None
    fully_backfilled: bool = False
    backfill_floor: datetime | None = None
    oldest_seen_occurred_at: datetime | None = None
    newest_seen_occurred_at: datetime | None = None
    rows_inserted_total: int = 0
    rows_patched_total: int = 0
    # The full walk's scheduling watermark (see decide_mode); NULL = not seeded yet.
    last_full_at: datetime | None = None


SCAN_FIELDS = tuple(ScanState.__dataclass_fields__)
IN_FLIGHT = ("refreshing", "backfilling")


def scan_started(state: ScanState, mode: str, start: datetime, now: datetime) -> ScanState:
    """Tick start: last_scan_at and the in-flight status are stamped (the /run
    endpoint's 409 guard reads the status; the dashboard tier reads
    "actively scanning"); a first backfill pins its floor at the window start.
    A backfill cursor below the window (the seen range of a walk before the
    marker walk) is no cursor: the walk starts over from the top, re-reads cost
    nothing, a marker below startDate would answer nothing."""
    floor = start if mode == "backfill" and state.backfill_floor is None else state.backfill_floor
    oldest = state.oldest_seen_occurred_at
    if (mode == "backfill" and oldest is not None
            and oldest < datetime.fromisoformat(recent_start_date(floor))):
        oldest = None
    return replace(state, last_scan_at=now, backfill_floor=floor, oldest_seen_occurred_at=oldest,
                   current_status="backfilling" if mode == "backfill" else "refreshing")


def scan_interrupted(state: ScanState, error: str) -> ScanState:
    """A tick that never finished (cancelled, or the process died): back to
    'idle', not 'error' — a restart is no ingest failure, so the streak stays."""
    return replace(state, current_status="idle", last_error=error)


def scan_after_failure(state: ScanState, proxy_refusal: bool, now: datetime, *,
                       error: str, full_at: datetime | None = None) -> ScanState:
    """A failed tick. A proxy CONNECT refusal never reached OF: the streak
    stays where it was (a real streak still pauses; a success still resets
    it). The third real failure in a row pauses the account _FAIL_BACKOFF_S.
    `full_at`: a failed full walk's window end, its period's slot spent."""
    if full_at is not None:
        state = replace(state, last_full_at=full_at)
    if proxy_refusal:
        return replace(state, last_error=error, current_status="idle")
    n = state.consecutive_failures + 1
    if n >= _FAILS_BEFORE_PAUSE:
        return replace(state, consecutive_failures=n, last_error=error, current_status="paused",
                       paused_until=now + timedelta(seconds=_FAIL_BACKOFF_S))
    return replace(state, consecutive_failures=n, last_error=error, current_status="error")


def scan_after_success(
    state: ScanState,
    *,
    mode: str,
    inserted: int,
    patched: int,
    last_marker: int | None,
    rows_min: datetime | None,
    rows_max: datetime | None,
    floor_reached: bool,
    now: datetime,
    stop_reason: str | None = None,
    full_at: datetime | None = None,
) -> ScanState:
    """A completed tick (`full_at`: a full walk's window end, cut short or not): the streak resets, the seen range widens, and the
    status says 'ok' — except a backfill not done: BACKFILL_PARTIAL (the walk is
    working, green), or BACKFILL_STALLED after a stop other than the tick's page
    cap (`stop_reason` kept in last_error, not green; a refresh in between leaves
    both). Until the backfill is done the seen range is its own: only a backfill
    moves it (a refresh's top above newest_seen would hide a gap from the next
    resumed read; a backfill's own pages go through scan_backfill_page)."""
    oldest, newest = state.oldest_seen_occurred_at, state.newest_seen_occurred_at
    moves_range = mode == "backfill" or state.fully_backfilled
    if moves_range and rows_min is not None and (oldest is None or rows_min < oldest):
        oldest = rows_min
    if moves_range and rows_max is not None and (newest is None or rows_max > newest):
        newest = rows_max
    done = mode == "backfill" and floor_reached
    unfinished = not done and (mode == "backfill" or not state.fully_backfilled)
    error = None
    if unfinished and mode == "backfill":
        error = None if stop_reason in (None, "tick_cap") else f"{_STALLED_PREFIX}{stop_reason}"
    elif unfinished and (state.last_error or "").startswith(_STALLED_PREFIX):
        error = state.last_error
    return replace(
        state,
        last_scan_at=now,
        consecutive_failures=0,
        last_error=error,
        last_marker=last_marker if last_marker is not None else state.last_marker,
        oldest_seen_occurred_at=oldest,
        newest_seen_occurred_at=newest,
        rows_inserted_total=state.rows_inserted_total + inserted,
        rows_patched_total=state.rows_patched_total + patched,
        fully_backfilled=True if done else state.fully_backfilled,
        current_status=(BACKFILL_STALLED if error else BACKFILL_PARTIAL) if unfinished else "ok",
        last_full_at=full_at if full_at is not None else state.last_full_at,
    )


def scan_backfill_page(state: ScanState, *, cursor: datetime | None, newest: datetime | None,
                       inserted: int, patched: int) -> ScanState:
    """One backfill tick's page, durably held: its counters and, for a marker-walk
    page, the cursor. A page never raises it (scan_backfill_restart, scan_started and
    trigger_backfill clear it)."""
    was_oldest, was_newest = state.oldest_seen_occurred_at, state.newest_seen_occurred_at
    return replace(
        state,
        oldest_seen_occurred_at=cursor if cursor is not None and (was_oldest is None or cursor < was_oldest)
        else was_oldest,
        newest_seen_occurred_at=newest if newest is not None and (was_newest is None or newest > was_newest)
        else was_newest,
        rows_inserted_total=state.rows_inserted_total + inserted,
        rows_patched_total=state.rows_patched_total + patched,
    )


def scan_backfill_restart(state: ScanState) -> ScanState:
    """The walk starts over from the top: its resumed read could not reach newest_seen
    (OF's offset cap), so rows between the two are unread. Markers have no such cap."""
    return replace(state, oldest_seen_occurred_at=None)


def is_paused(state: ScanState | None, now: datetime) -> bool:
    return state is not None and state.paused_until is not None and state.paused_until > now


def full_phase_s(account_id: str, full_every_s: float = _DEFAULT_FULL_EVERY_S) -> int:
    """The account's fixed offset into the full-walk period, in [0, full_every_s):
    crc32, so it survives restarts and spreads Creators across the period."""
    return zlib.crc32(str(account_id).encode()) % max(1, int(full_every_s))


def full_bucket(at: datetime, *, full_every_s: float, phase_s: float) -> int:
    """Which of the account's full-walk periods `at` (naive UTC) falls in."""
    return int(((at - _EPOCH).total_seconds() + phase_s) // full_every_s)


def scan_seeded(state: ScanState, now: datetime) -> ScanState:
    """A backfilled account with no full-walk watermark (rows from before it was
    persisted) is seeded to `now` once: its first full walk waits for its next phase
    boundary, so the deploy is no full-walk herd. Anything else unchanged."""
    if state.fully_backfilled and state.last_full_at is None:
        return replace(state, last_full_at=now)
    return state


def decide_mode(state: ScanState | None, *, now: datetime,
                full_every_s: float = _DEFAULT_FULL_EVERY_S, phase_s: float = 0.0) -> str:
    """No scan row yet, or a backfill not started (no cursor, no stop) -> backfill. Else the full
    7-day `refresh` when `now` is in another period than `state.last_full_at`
    (`full_bucket`; the last ATTEMPTED full walk's window end, persisted, so a restart
    keeps the schedule): one full walk per period, on its first tick, so walk to walk
    is full_every_s (+/- a tick). A watermark in a later period (clock stepped back)
    differs too: one refresh re-stamps it. Unseeded (None): an unfinished walk's
    refresh; a backfilled account `recent` (the caller seeds it, scan_seeded).
    Else `recent`, or the unfinished walk's `backfill`: a walk owes the full walks'
    status flips and disputes polls as much as a finished account, above all a
    walk that stopped and may never finish (the refresh leaves its cursor)."""
    started = (state is not None and (state.oldest_seen_occurred_at is not None
                                      or (state.last_error or "").startswith(_STALLED_PREFIX)))
    if state is None or (not state.fully_backfilled and not started):
        return "backfill"
    last_full_at = state.last_full_at
    if last_full_at is None:
        return "recent" if state.fully_backfilled else "refresh"
    b = lambda t: full_bucket(t, full_every_s=full_every_s, phase_s=phase_s)  # noqa: E731
    if b(now) != b(last_full_at):
        return "refresh"
    return "recent" if state.fully_backfilled else "backfill"


def recent_start_date(window_start: datetime) -> str:
    """The recent walk's `startDate`: the day before its window starts, date only
    (`YYYY-MM-DD`). OF filters createdAt >= that day's UTC midnight (measured
    2026-11-07, acct 15891843), hence the day of margin. Never an ISO datetime: what
    OF does with one is format-dependent (one form answered empty on acct 532022545;
    `2026-10-01T00:00:00Z`, limit=1, answered a row on 15891843, and one row cannot
    show the filter was honoured). The backfill's startDate too, from its floor."""
    return (window_start - timedelta(days=1)).date().isoformat()


def marker_of(at: datetime) -> int:
    """OF's `marker` (createdAt <= marker, unix seconds, measured) that re-reads the
    naive UTC `at`: rounded UP, so a row in `at`'s second is re-read, never skipped."""
    return calendar.timegm(at.timetuple()) + (1 if at.microsecond else 0)


def page_span(rows: list[dict], window_start: datetime) -> tuple[datetime | None, datetime | None, bool]:
    """(the page's oldest createdAt at or above window_start: the cursor it allows; its
    newest; whether a row sits below window_start, i.e. OF ignored startDate)."""
    at = [t for t in (_parse_iso(r.get("createdAt")) for r in rows) if t is not None]
    inside = [t for t in at if t >= window_start]
    return (min(inside, default=None), max(at, default=None), len(inside) < len(at))


class BackfillStep(NamedTuple):
    """What a marker-walk page means: `complete` the window is read to its start; `next`
    page at `marker`; `stop` not done, the next tick resumes from the cursor (`reason`)."""
    action: Literal["complete", "next", "stop"]
    reason: str
    marker: int | None = None


def backfill_step(*, rows: int, has_more: object, next_marker: object, sent_marker: int | None,
                  first_page: bool, held_since: bool, below_window: bool) -> BackfillStep:
    """Complete ONLY on a page with rows and hasMore false, or an empty first page with
    hasMore false and nothing held in the window (`_backfill_walk` then asks OF whether that
    answer was blank). OF's offset-cap answer (empty, hasMore false) looks like an end
    but is not: empty after a page, or with rows held, never completes."""
    if rows == 0:
        if first_page and not held_since and has_more is False:
            return BackfillStep("complete", "empty_window")
        return BackfillStep("stop", "empty_first_page_rows_held" if first_page and held_since else "empty_page")
    if has_more is False:
        return BackfillStep("complete", "last_page")
    if has_more is not True:
        return BackfillStep("stop", "no_has_more")
    if below_window:
        return BackfillStep("stop", "start_date_ignored")
    try:
        marker = math.ceil(float(next_marker))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return BackfillStep("stop", "no_next_marker")
    if sent_marker is not None and marker >= sent_marker:
        return BackfillStep("stop", "marker_not_decreasing")
    return BackfillStep("next", "more", marker)


def window_for(mode: str, state: ScanState, now: datetime, *,
               recent_h: float = _DEFAULT_RECENT_WINDOW_H) -> tuple[datetime, datetime]:
    """recent: trailing recent_h (rows land <= ~10.5 h late, measured).
    refresh: trailing 7d (5d pending + 2d safety).
    OF ignores start/end (measured 2026-11-07): the window bounds the bookkeeping;
    recent_start_date narrows what OF answers (recent walk, backfill).
    backfill: walk from oldest_seen_occurred_at (or now) BACK to backfill_floor."""
    if mode == "recent":
        return (now - timedelta(hours=recent_h), now)
    if mode == "refresh":
        return (now - timedelta(days=_ROLLING_WINDOW_DAYS), now)
    floor = state.backfill_floor or (now - timedelta(days=_DEFAULT_BACKFILL_DAYS))
    end = state.oldest_seen_occurred_at or now
    return (floor, end)
