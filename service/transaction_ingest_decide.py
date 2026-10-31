"""
The ledger ingest's decisions, pure: no DB, no OF, no clock of its own (the
caller passes `now`).

`transaction_ingest` parses a page once (`_parse_row`), reads what the page needs
(the rows already held by provider id, the WS-pump tips a ledger tip may be the
twin of — `tip_window` — and the fans that already subscribed — `subscription_fans`),
asks `plan_page` what to do with each OF row, and opens ONE write transaction
only if some op writes. The scan bookkeeping (`scan_started`, `scan_interrupted`,
`scan_after_failure`, `scan_after_success`, `window_for`, `decide_mode`) is the
same split: these compute the next state, `transaction_ingest` reads and writes
the row.

Everything here is re-exported by `transaction_ingest`, so its importers keep
reading `transaction_ingest._classify_kind` and friends.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Iterable, Literal, NamedTuple

from attribution_backfill import SETTLED_REVERSALS

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

_HTML_TAG = re.compile(r"<[^>]+>")
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
_DEFAULT_BACKFILL_DAYS = 90
_FAIL_BACKOFF_S = 600                   # auto-pause for 10 min after 3 real fails
                                        # (a proxy CONNECT refusal never counts)
_FAILS_BEFORE_PAUSE = 3


def _normalize_status(raw_status: str | None) -> str:
    if not raw_status:
        return "cleared"
    return _STATUS_MAP.get(raw_status, raw_status)


# ── Parsing helpers ─────────────────────────────────────────────────

def _strip_html(s: str | None) -> str:
    if not s:
        return ""
    return _HTML_TAG.sub("", s).strip()


def _classify_kind(description: str | None) -> str:
    text_ = _strip_html(description) if description and "<" in description else (description or "").strip()
    for prefix, kind in KIND_CATALOG:
        if text_.startswith(prefix):
            return kind
    return "unknown"


def _to_cents(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(round(float(v) * 100))
    except Exception:
        return None


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
    Lifetime: +amount on a revenue insert only; never on a re-poll; a
    promote reconciles the WS amount to the ledger's; a flip into a refund
    status takes the previous amount off."""
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
            refund = (p["status"] in _REFUND_STATUSES and prev.status not in _REFUND_STATUSES
                      and bool(fan))
            ops.append(RowOp("patch", p, kind, status_flip=flip,
                             lifetime_delta=-prev.amount_cents if refund else 0,
                             broadcast="status_flip" if flip else None))
            existing[key] = seen
            continue
        ws = _fingerprint_match(p, candidates, taken) if _fingerprint_eligible(raw_kind) else None
        if ws is not None:
            taken.add(ws.id)
            delta = (p["amount_cents"] - ws.amount_cents
                     if fan and p["status"] not in _NON_REVENUE_STATUSES else 0)
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


SCAN_FIELDS = tuple(ScanState.__dataclass_fields__)
IN_FLIGHT = ("refreshing", "backfilling")


def scan_started(state: ScanState, mode: str, start: datetime, now: datetime) -> ScanState:
    """Tick start: last_scan_at and the in-flight status are stamped (the /run
    endpoint's 409 guard reads the status; the dashboard tier reads
    "actively scanning"); a first backfill pins its floor at the window start."""
    floor = start if mode == "backfill" and state.backfill_floor is None else state.backfill_floor
    return replace(state, last_scan_at=now, backfill_floor=floor,
                   current_status="backfilling" if mode == "backfill" else "refreshing")


def scan_interrupted(state: ScanState, error: str) -> ScanState:
    """A tick that never finished (cancelled, or the process died): back to
    'idle', not 'error' — a restart is no ingest failure, so the streak stays."""
    return replace(state, current_status="idle", last_error=error)


def scan_after_failure(state: ScanState, proxy_refusal: bool, now: datetime, *,
                       error: str) -> ScanState:
    """A failed tick. A proxy CONNECT refusal never reached OF: the streak
    stays where it was (a real streak still pauses; a success still resets
    it). The third real failure in a row pauses the account _FAIL_BACKOFF_S."""
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
) -> ScanState:
    """A completed tick: the streak resets, the seen range widens, and the
    status says 'ok' — except a backfill that has not reached its floor,
    which stays 'backfilling' (the banner reads "still working")."""
    oldest, newest = state.oldest_seen_occurred_at, state.newest_seen_occurred_at
    if rows_min is not None and (oldest is None or rows_min < oldest):
        oldest = rows_min
    if rows_max is not None and (newest is None or rows_max > newest):
        newest = rows_max
    done = mode == "backfill" and floor_reached
    return replace(
        state,
        last_scan_at=now,
        consecutive_failures=0,
        last_error=None,
        last_marker=last_marker if last_marker is not None else state.last_marker,
        oldest_seen_occurred_at=oldest,
        newest_seen_occurred_at=newest,
        rows_inserted_total=state.rows_inserted_total + inserted,
        rows_patched_total=state.rows_patched_total + patched,
        fully_backfilled=True if done else state.fully_backfilled,
        current_status="backfilling" if mode == "backfill" and not floor_reached else "ok",
    )


def is_paused(state: ScanState | None, now: datetime) -> bool:
    return state is not None and state.paused_until is not None and state.paused_until > now


def decide_mode(state: ScanState | None) -> str:
    """No scan row yet, or never fully backfilled -> backfill; else refresh."""
    if state is None or not state.fully_backfilled:
        return "backfill"
    return "refresh"


def window_for(mode: str, state: ScanState, now: datetime) -> tuple[datetime, datetime]:
    """refresh: trailing 7d (5d pending + 2d safety).
    backfill: walk from oldest_seen_occurred_at (or now) BACK to backfill_floor."""
    if mode == "refresh":
        return (now - timedelta(days=_ROLLING_WINDOW_DAYS), now)
    floor = state.backfill_floor or (now - timedelta(days=_DEFAULT_BACKFILL_DAYS))
    end = state.oldest_seen_occurred_at or now
    return (floor, end)
