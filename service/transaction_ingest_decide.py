from __future__ import annotations

import calendar
import math
import zlib
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Iterable, Literal, NamedTuple

from attribution_backfill import SETTLED_REVERSALS
from of_coerce import cents_or_none as _to_cents, strip_tags as _strip_html

# Match top-to-bottom. "Subscription from" is the first charge, "Recurring subscription from" a renewal (verified: 56 of 57 fans had the plain row earlier); prefix mapping beats the rebill-promote heuristic, which depends on insertion order and fails on newest-first backfill.
KIND_CATALOG: tuple[tuple[str, str], ...] = (
    ("Recurring subscription from ", "rebill"),
    ("Subscription from ",           "subscription"),
    ("Tip in chat from ",            "tip"),
    ("Tip from ",                    "tip"),
    ("Tip on post from ",            "tip_post"),
    ("Tip on stream from ",          "tip_stream"),
    ("Payment for message from ",    "ppv_message"),
    ("Message from ",                "ppv_message"),
    ("Post from ",                   "ppv_post"),
    ("Post purchase by ",            "ppv_post"),
    ("Stream from ",                 "ppv_stream"),
    ("Custom request from ",         "custom"),
    ("Custom from ",                 "custom"),
)

_STATUS_MAP = {
    "done":           "cleared",
    "loading":        "pending",
    "undo":           "chargedback",
    "pending_return": "refund_pending",
}

_REFUND_STATUSES = SETTLED_REVERSALS
_NON_REVENUE_STATUSES = (*SETTLED_REVERSALS, "failed")

_ENABLE_PPV_FINGERPRINT = False

# WS-pump sibling tolerance: amount +/- max(10c, 1%) for OF fee rounding, time +/- 300s for WS-vs-ledger clock drift.
_FINGERPRINT_WINDOW = timedelta(seconds=300)

_ROLLING_WINDOW_DAYS = 7
_DEFAULT_RECENT_WINDOW_H = 24.0
_DEFAULT_FULL_EVERY_S = 7200.0
_EPOCH = datetime(1970, 1, 1)
_DEFAULT_BACKFILL_DAYS = 90
# Auto-pause 30 min after 3 real fails (two 900 s ticks skipped); a proxy CONNECT refusal never counts.
_FAIL_BACKOFF_S = 1800
_FAILS_BEFORE_PAUSE = 3
# Marker walk per tick: ~2 s a page (OF ~1.4 s + 0.4 s sleep + write), 40 pages = 4,000 rows in ~80 s, under _STALE_INFLIGHT_S (720 s) even with 429 waits.
_BACKFILL_TICK_PAGES = 40
_BACKFILL_FRESH_PAGES = 6
BACKFILL_PARTIAL = "backfill_partial"
BACKFILL_STALLED = "backfill_stalled"
_STALLED_PREFIX = "backfill_stopped: "
_BACKFILL_MAX_STALLS = 3
BACKFILL_GIVEN_UP = "backfill_given_up"
_FULL_FAILED_PREFIX = "full_walk_failed: "


def _normalize_status(raw_status: str | None) -> str:
    if not raw_status:
        return "cleared"
    return _STATUS_MAP.get(raw_status, raw_status)



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



class Existing(NamedTuple):
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
        return cls(**{f: p[f] for f in cls._fields})


PATCH_FIELDS = Existing._fields


@dataclass(frozen=True)
class WsTip:
    id: int
    fan_id: int
    amount_cents: int
    occurred_at: datetime


Action = Literal["insert", "patch", "promote", "noop", "skip"]
Reason = Literal["insert", "status_flip", "ledger_promote"]


@dataclass(frozen=True)
class RowOp:
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
        return self.parsed["raw_kind"]

    @property
    def writes(self) -> bool:
        return self.action in ("insert", "patch", "promote")

    @property
    def result(self) -> tuple[int, int]:
        if self.action == "insert":
            return (1, 0)
        return (0, 0) if self.action == "skip" else (0, 1)


def _fingerprint_eligible(kind: str) -> bool:
    return kind == "tip" or (_ENABLE_PPV_FINGERPRINT and kind.startswith("ppv"))


def tip_window(parsed: list[dict], held: Iterable[str]) -> tuple[set[int], datetime, datetime] | None:
    held = set(held)
    tips = [p for p in parsed if p["provider_id"] and p["fan_id"] and str(p["provider_id"]) not in held
            and _fingerprint_eligible(p["raw_kind"])]
    if not tips:
        return None
    at = [p["occurred_at"] for p in tips]
    return ({p["fan_id"] for p in tips}, min(at) - _FINGERPRINT_WINDOW, max(at) + _FINGERPRINT_WINDOW)


def subscription_fans(parsed: list[dict]) -> set[int]:
    return {p["fan_id"] for p in parsed if p["fan_id"] and p["raw_kind"] == "subscription"}


def parse_page(rows: list[dict], now: datetime) -> list[dict]:
    out = []
    for raw in rows:
        p = _parse_row(raw, now)
        p["raw_kind"] = _classify_kind(p["description"])
        out.append(p)
    return out


def _fingerprint_match(parsed: dict, candidates: Iterable[WsTip], taken: set[int]) -> WsTip | None:
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
    # Lifetime follows "row is in a settled reversal" (chargedback | refunded): +amount on a revenue insert only, never on a plain re-poll; a flip INTO a reversal takes the amount off, a flip OUT puts it back, so any oscillation nets to 0. The deduct clamps at 0.
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
        key = str(pid)  # the column is text; OF may send the id as a number
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



@dataclass(frozen=True)
class ScanState:
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
    last_full_at: datetime | None = None
    full_walk_failures: int = 0
    backfill_stalls: int = 0


SCAN_FIELDS = tuple(ScanState.__dataclass_fields__)
IN_FLIGHT = ("refreshing", "backfilling")


def scan_started(state: ScanState, mode: str, start: datetime, now: datetime) -> ScanState:
    floor = start if mode == "backfill" and state.backfill_floor is None else state.backfill_floor
    oldest = state.oldest_seen_occurred_at
    if (mode == "backfill" and oldest is not None
            and oldest < datetime.fromisoformat(recent_start_date(floor))):
        oldest = None
    return replace(state, last_scan_at=now, backfill_floor=floor, oldest_seen_occurred_at=oldest,
                   current_status="backfilling" if mode == "backfill" else "refreshing")


def scan_interrupted(state: ScanState, error: str) -> ScanState:
    # A cancelled/died tick goes back to 'idle', not 'error': a restart is no ingest failure, so the streak stays.
    return replace(state, current_status="idle", last_error=error)


def scan_after_failure(state: ScanState, proxy_refusal: bool, now: datetime, *,
                       error: str, full_at: datetime | None = None, progressed: bool = False,
                       reached: bool = False) -> ScanState:
    if full_at is not None and (reached or not proxy_refusal):
        state = replace(state, last_full_at=full_at, full_walk_failures=state.full_walk_failures + 1)
        error = f"{_FULL_FAILED_PREFIX}{error}"
    if progressed:
        return replace(state, last_error=error, current_status=BACKFILL_STALLED)
    if proxy_refusal:
        return replace(state, last_error=error, current_status="idle")
    n = state.consecutive_failures + 1
    if n >= _FAILS_BEFORE_PAUSE:
        return replace(state, consecutive_failures=n, last_error=error, current_status="paused",
                       paused_until=now + timedelta(seconds=_FAIL_BACKOFF_S))
    return replace(state, consecutive_failures=n, last_error=error, current_status="error")


class Success(NamedTuple):
    state: ScanState
    outcome: Literal["gap_queued", "given_up"] | None


def stall_count(stalls: int, *, stalled: bool, advanced: bool) -> int:
    if not stalled:
        return 0
    return 1 if advanced else stalls + 1


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
    advanced: bool = False,
) -> Success:
    # A finished account's walk moves newest_seen only if it read back to it: an outage longer than OF's 600-row offset cap left rows between unread.
    oldest, newest = state.oldest_seen_occurred_at, state.newest_seen_occurred_at
    backfill = mode == "backfill"
    unreached = (state.fully_backfilled and not backfill and rows_min is not None
                 and newest is not None and rows_min > newest)
    moves_range = backfill or (state.fully_backfilled and not unreached)
    if moves_range and rows_min is not None and (oldest is None or rows_min < oldest):
        oldest = rows_min
    if moves_range and rows_max is not None and (newest is None or rows_max > newest):
        newest = rows_max
    done = backfill and floor_reached
    stalled = backfill and not done and stop_reason not in (None, "tick_cap")
    stalls = stall_count(state.backfill_stalls, stalled=stalled, advanced=advanced) if backfill \
        else state.backfill_stalls
    given_up = stalls >= _BACKFILL_MAX_STALLS
    fails = state.full_walk_failures
    if full_at is not None:
        fails = 0 if floor_reached else fails + 1
    unfinished = not done and not given_up and (backfill or not state.fully_backfilled)
    error = None
    if stalled:
        error = f"{_STALLED_PREFIX}{stop_reason}"
    elif given_up:
        error = state.last_error if (state.last_error or "").startswith(_STALLED_PREFIX) \
            else f"{_STALLED_PREFIX}given_up"
    elif unfinished and stalls:
        error = state.last_error
    elif fails and full_at is not None:
        error = f"{_FULL_FAILED_PREFIX}cut_short: {stop_reason or 'incomplete'}"
    elif fails:
        error = state.last_error if (state.last_error or "").startswith(_FULL_FAILED_PREFIX) \
            else f"{_FULL_FAILED_PREFIX}owed"
    status = "ok"
    if given_up:
        status = BACKFILL_GIVEN_UP
    elif unfinished:
        status = BACKFILL_STALLED if stalled or stalls else BACKFILL_PARTIAL
    out = replace(
        state,
        last_scan_at=now,
        consecutive_failures=0,
        last_error=error,
        last_marker=last_marker if last_marker is not None else state.last_marker,
        oldest_seen_occurred_at=oldest,
        newest_seen_occurred_at=newest,
        rows_inserted_total=state.rows_inserted_total + (0 if backfill else inserted),
        rows_patched_total=state.rows_patched_total + (0 if backfill else patched),
        fully_backfilled=True if done or given_up else state.fully_backfilled,
        current_status=status,
        last_full_at=full_at if full_at is not None else state.last_full_at,
        full_walk_failures=fails,
        backfill_stalls=stalls,
    )
    if unreached and mode == "refresh":
        return Success(scan_backfill_queued(out, state.newest_seen_occurred_at), "gap_queued")
    return Success(out, "given_up" if given_up and backfill else None)


def scan_backfill_page(state: ScanState, *, cursor: datetime | None, newest: datetime | None,
                       inserted: int, patched: int) -> ScanState:
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


def scan_backfill_queued(state: ScanState, floor: datetime) -> ScanState:
    if not state.fully_backfilled and state.backfill_floor is not None:
        floor = min(floor, state.backfill_floor)
    return replace(state, backfill_floor=floor, oldest_seen_occurred_at=None, fully_backfilled=False,
                   current_status="idle", paused_until=None, consecutive_failures=0, backfill_stalls=0)


def scan_backfill_restart(state: ScanState) -> ScanState:
    return replace(state, oldest_seen_occurred_at=None)


def is_paused(state: ScanState | None, now: datetime) -> bool:
    return state is not None and state.paused_until is not None and state.paused_until > now


def full_phase_s(account_id: str, full_every_s: float = _DEFAULT_FULL_EVERY_S) -> int:
    return zlib.crc32(str(account_id).encode()) % max(1, int(full_every_s))


def full_bucket(at: datetime, *, full_every_s: float, phase_s: float) -> int:
    return int(((at - _EPOCH).total_seconds() + phase_s) // full_every_s)


def walk_started(state: ScanState) -> bool:
    return state.oldest_seen_occurred_at is not None or state.backfill_stalls > 0


class Mode(NamedTuple):
    mode: str
    state: ScanState | None


def decide_mode(state: ScanState | None, *, now: datetime,
                full_every_s: float = _DEFAULT_FULL_EVERY_S, phase_s: float = 0.0) -> Mode:
    # Watermark seeding makes neither a deploy nor the boot after an outage a full-walk herd (at most one period late).
    if state is None or (not state.fully_backfilled and not walk_started(state)):
        return Mode("backfill", state)
    b = lambda t: full_bucket(t, full_every_s=full_every_s, phase_s=phase_s)  # noqa: E731
    last = state.last_full_at
    if (last is None and state.fully_backfilled) or (last is not None and b(now) - b(last) > 1):
        state = replace(state, last_full_at=now)
    last = state.last_full_at
    if last is None or b(now) != b(last):
        return Mode("refresh", state)
    return Mode("recent" if state.fully_backfilled else "backfill", state)


# OF filters createdAt >= that day's UTC midnight (measured), hence the day of margin; date only, never an ISO datetime: its handling is format-dependent.
def recent_start_date(window_start: datetime) -> str:
    return (window_start - timedelta(days=1)).date().isoformat()


# Rounded up so a row in at's second is re-read, never skipped.
def marker_of(at: datetime) -> int:
    return calendar.timegm(at.timetuple()) + (1 if at.microsecond else 0)


def page_span(rows: list[dict], window_start: datetime) -> tuple[datetime | None, datetime | None, bool]:
    at = [t for t in (_parse_iso(r.get("createdAt")) for r in rows) if t is not None]
    inside = [t for t in at if t >= window_start]
    return (min(inside, default=None), max(at, default=None), len(inside) < len(at))


class BackfillStep(NamedTuple):
    action: Literal["complete", "next", "stop"]
    reason: str
    marker: int | None = None


def backfill_step(*, rows: int, has_more: object, next_marker: object, sent_marker: int | None,
                  first_page: bool, held_since: bool, below_window: bool) -> BackfillStep:
    if rows == 0:
        if first_page and not held_since and has_more is False:
            return BackfillStep("complete", "empty_window")
        return BackfillStep("stop", "empty_first_page_rows_held" if first_page and held_since else "empty_page")
    # OF's offset-cap answer (empty, hasMore false) looks like an end but is not: empty after a page, or with rows held, never completes.
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
    # recent: rows land <= ~10.5 h late (measured); refresh: 7d = 5d pending + 2d safety. OF ignores start/end (measured): the window bounds the bookkeeping, recent_start_date narrows what OF answers.
    if mode == "recent":
        return (now - timedelta(hours=recent_h), now)
    if mode == "refresh":
        return (now - timedelta(days=_ROLLING_WINDOW_DAYS), now)
    floor = state.backfill_floor or (now - timedelta(days=_DEFAULT_BACKFILL_DAYS))
    end = state.oldest_seen_occurred_at or now
    return (floor, end)
