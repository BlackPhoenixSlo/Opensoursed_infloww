from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Literal, Sequence, Union

from isotime import parse_iso


@dataclass(frozen=True)
class Kept:
    id: int
    of_promo_id: int | None
    discount_percent: int
    reactivate_count: int
    last_reactivated_at: datetime | None
    ticked_at: datetime | None = None
    preempt: bool = False


@dataclass(frozen=True)
class Created:
    campaign_id: int | None
    settled_at: datetime
    listed_at: datetime | None
    claims_seen: int | None
    first_claims: int | None


@dataclass(frozen=True)
class Memo:
    kept_of_promo_id: int | None = None
    first_claims: int | None = None
    last_claims: int | None = None
    read_at: datetime | None = None
    finished_at: str | None = None


@dataclass(frozen=True)
class Inputs:
    campaigns: Sequence[Kept]
    promos: Sequence[dict] | None
    now: datetime
    max_reactivations: int = 0
    cooldown_min: int = 2
    memo: Memo = field(default_factory=Memo)
    owned_ids: frozenset[int] = frozenset()
    creates: Sequence[Created] = ()
    auto_times: Sequence[datetime] = ()
    not_before: datetime | None = None
    preempt_enabled: bool = False
    prior: Memo = field(default_factory=Memo)
    skew_s: int | None = None


@dataclass(frozen=True)
class Tally:
    due: int = 0
    skipped_cap: int = 0
    skipped_cooldown: int = 0
    skipped_no_discount: int = 0
    skipped_unverifiable: int = 0


WaitReason = Literal["of_unreachable", "promo_already_live", "inferred_cap_untrusted",
                     "breaker_hold", "backoff", "budget", "nothing_due"]
HOLD_REASONS: frozenset[str] = frozenset({"breaker_hold", "backoff", "budget"})
HoldReason = Literal["backoff", "budget"]
PreemptWait = Literal["second_live", "end_unconfirmed", "clock", "count_untrusted", "cooldown",
                      "no_recovery_slot", "breaker_hold", "backoff", "budget"]


@dataclass(frozen=True)
class Wait:
    reason: WaitReason
    live: dict | None = None
    kept: int | None = None
    tally: Tally | None = None
    cooldown_ends: datetime | None = None
    wait_reason: PreemptWait | None = None


@dataclass(frozen=True)
class AfterEnd:
    campaign_id: int
    due: tuple[int, ...]
    tally: Tally = field(default_factory=Tally)


@dataclass(frozen=True)
class TurnOff:
    reason: str
    campaign_id: int


@dataclass(frozen=True)
class Fill:
    campaign_id: int
    live: dict


@dataclass(frozen=True)
class Timed:
    campaign_id: int
    live: dict


Verdict = Union[Wait, AfterEnd, TurnOff, Fill, Timed]

BREAKER_N = 3
NOT_LISTED_S = 600  # a create's id not seen live this long after its settle is a zero row
BACKOFF_BASE_S = 120
BACKOFF_CAP_S = 6 * 3600  # caps the doubling only: OF's own Retry-After is honoured in full
BUDGET_HOUR = 3
BUDGET_DAY = 8
PREEMPT_MIN_CAP = 10  # a smaller cap (and 0 = unlimited) is never pre-empted
TIMED_LEAD_S = 120
SKEW_MAX_S = 30
_RATE_LIMITED = ("http_403", "http_429")
_OFF_AS_IS = ("captcha", "deactivated", "price_free")


def backoff_until(now: datetime, k: int, retry_after_s: float | None) -> datetime:
    doubling = min(BACKOFF_BASE_S * 2 ** (max(k, 1) - 1), BACKOFF_CAP_S)
    return now + timedelta(seconds=max(retry_after_s or 0.0, doubling))


def failure_turns_off(error_class: str | None, prev_class: str | None) -> str | None:
    if error_class in _OFF_AS_IS:
        return error_class
    if error_class in _RATE_LIMITED:
        # A first 403/429 may be the proxy provider's, so only a second in a row stops Keep running.
        return "rate_limited" if prev_class in _RATE_LIMITED else None
    if error_class and error_class.startswith("http_4"):
        return "create_refused"
    return None


def preempt_failure(error_class: str | None,
                    prev_class: str | None) -> tuple[str | None, bool, bool]:
    # Only the page's own state stops Keep running: a refusal of an early create says nothing about the After-end create that recovers it.
    if error_class in _OFF_AS_IS:
        return error_class, False, False
    return (None, failure_turns_off(error_class, prev_class) is not None,
            error_class != "session_dead")


def preempt_applies(enabled: bool, ticked: bool, cap: int | None) -> bool:
    return bool(enabled and ticked and threshold(int(cap or 0)) is not None)


def threshold(cap: int) -> int | None:
    return (9 * cap + 9) // 10 if cap >= PREEMPT_MIN_CAP else None


def _flags_live(p: dict) -> bool:
    return not p.get("is_finished") or bool(p.get("cap_inferred"))


def observe(memo: Memo, promos: Sequence[dict] | None, kept_ids: set[int], now: datetime) -> Memo:
    # A lower count for the memo's promo untrusts it for good: the history is no longer monotonic.
    for q in promos or ():
        if (q.get("of_promo_id") == memo.kept_of_promo_id and q.get("claims_present")
                and memo.last_claims is not None and int(q.get("subscriber_count") or 0) < memo.last_claims):
            return Memo(memo.kept_of_promo_id, None, int(q.get("subscriber_count") or 0), now,
                        q.get("finished_at"))
    p = next((p for p in promos or () if p.get("of_promo_id") in kept_ids and _flags_live(p)), None)
    if p is None:
        return memo
    claims = int(p.get("subscriber_count") or 0) if p.get("claims_present") else None
    fin = p.get("finished_at")
    if p["of_promo_id"] != memo.kept_of_promo_id:
        return Memo(p["of_promo_id"], claims, claims, now, fin)
    if claims is None:
        return replace(memo, finished_at=fin)
    went_down = memo.last_claims is not None and claims < memo.last_claims
    return Memo(memo.kept_of_promo_id, None if went_down else memo.first_claims, claims, now, fin)


def decide(i: Inputs) -> Verdict:
    # Fail closed: a failed read cannot tell "finished" from "unreachable".
    if i.promos is None:
        return Wait("of_unreachable")
    by_of = {c.of_promo_id: c.id for c in i.campaigns if c.of_promo_id is not None}
    # OF runs one promo at a time and a create ends the current one: any live promo means a discount is on offer, so stand down (two Kept campaigns would ping-pong).
    live_now = [p for p in i.promos if not p.get("is_finished")]
    if live_now:
        shown = next((p for p in live_now if p.get("of_promo_id") in by_of), live_now[0])
        kept = by_of.get(shown.get("of_promo_id"))
        why = None
        if kept is not None:
            v = _preempt(i, next(c for c in i.campaigns if c.id == kept), shown, len(live_now))
            if not isinstance(v, (str, type(None))):
                return v
            why = v
        return Wait("promo_already_live", live=shown, kept=kept, wait_reason=why)
    m = i.memo
    # An inferred cap is trusted only when we watched this Kept promo fill from 0: a create would otherwise end a promo OF still offers.
    for p in i.promos:
        pid = p.get("of_promo_id")
        trusted = pid in by_of and pid == m.kept_of_promo_id and m.first_claims == 0
        earlier = pid in i.owned_ids and pid not in by_of
        if p.get("cap_inferred") and not trusted and not earlier:
            return Wait("inferred_cap_untrusted", live=p, kept=by_of.get(pid))
    v = _after_end(i)
    if isinstance(v, AfterEnd):
        v = _breaker(i, v.campaign_id, v.tally) or v
    return _budget(i, v) if isinstance(v, AfterEnd) else v


def _preempt(i: Inputs, c: Kept, p: dict, n_live: int) -> Verdict | PreemptWait | None:
    cap = int(p.get("subscribe_counts") or 0)
    if not preempt_applies(i.preempt_enabled, c.preempt, cap):
        return None
    if n_live > 1:
        return "second_live"
    screen = _screen(i, c)
    if screen not in (None, "cooldown"):
        return None
    why: str | None = None
    v: Fill | Timed | None = None
    end = parse_iso(p.get("finished_at"))
    left = timed_left(end, i.now, i.skew_s)
    if in_timed_window(left):
        if i.prior.kept_of_promo_id != p.get("of_promo_id") or i.prior.finished_at != p.get("finished_at"):
            why = "end_unconfirmed"
        else:
            v = Timed(c.id, p)
    elif left is None and end is not None and in_timed_window((end - i.now).total_seconds()):
        why = "clock"
    if v is None:
        m = i.memo
        trusted = (m.kept_of_promo_id == p.get("of_promo_id") and m.first_claims == 0
                   and bool(p.get("claims_present")))
        claims = int(p.get("subscriber_count") or 0)
        if trusted and threshold(cap) <= claims < cap:
            v = Fill(c.id, p)
        elif not trusted:
            why = why or "count_untrusted"
    if v is None:
        return why
    if screen == "cooldown":
        return "cooldown"
    gate = _breaker(i, c.id, Tally())
    if isinstance(gate, TurnOff):
        return gate
    if gate is not None:
        return gate.reason
    hold = create_hold(i.auto_times, i.not_before, i.now)
    if hold:
        return hold[0]
    if not _recovery_slot(i):
        return "no_recovery_slot"
    return v


def end_on_our_clock(end: datetime | None, skew_s: int | None) -> datetime | None:
    if end is None or skew_s is None or abs(skew_s) > SKEW_MAX_S:
        return None
    return end + timedelta(seconds=skew_s)


def timed_left(end: datetime | None, now: datetime, skew_s: int | None) -> float | None:
    ours = end_on_our_clock(end, skew_s)
    return None if ours is None else (ours - now).total_seconds()


def in_timed_window(left: float | None) -> bool:
    return left is not None and 0 < left <= TIMED_LEAD_S


def _recovery_slot(i: Inputs) -> bool:
    return recovery_slot(i.auto_times, i.now)


def recovery_slot(auto_times: Sequence[datetime], now: datetime) -> bool:
    # A Pre-emption ends the live promo even when its create fails: one automatic create must stay in both budget windows for the After-end that recovers.
    for n, span in ((BUDGET_HOUR, timedelta(hours=1)), (BUDGET_DAY, timedelta(days=1))):
        if sum(1 for t in auto_times if now - t < span) + 1 > n - 1:
            return False
    return True


def create_hold(auto_times: Sequence[datetime], not_before: datetime | None,
                now: datetime) -> tuple[HoldReason, datetime] | None:
    if not_before is not None and now < not_before:
        return "backoff", not_before
    ends = []
    for n, span in ((BUDGET_HOUR, timedelta(hours=1)), (BUDGET_DAY, timedelta(days=1))):
        inside = sorted((t for t in auto_times if now - t < span), reverse=True)
        if len(inside) >= n:
            ends.append(inside[n - 1] + span)
    return ("budget", max(ends)) if ends else None


def _budget(i: Inputs, v: AfterEnd) -> Verdict:
    hold = create_hold(i.auto_times, i.not_before, i.now)
    return Wait(hold[0], tally=v.tally, cooldown_ends=hold[1]) if hold else v


def _breaker(i: Inputs, campaign_id: int, tally: Tally) -> Wait | TurnOff | None:
    if i.creates:
        top = i.creates[0]
        ends = top.settled_at + timedelta(seconds=NOT_LISTED_S)
        if top.listed_at is None and i.now < ends:
            return Wait("breaker_hold", tally=tally, cooldown_ends=ends)
    c = next(c for c in i.campaigns if c.id == campaign_id)
    mine = [r for r in i.creates if r.campaign_id == c.id
            and (c.ticked_at is None or r.settled_at >= c.ticked_at)][:BREAKER_N]

    def zero(r: Created) -> bool:
        gained = (r.claims_seen or 0) - (r.first_claims or 0)
        return gained <= 0 or r.listed_at is None
    if len(mine) == BREAKER_N and all(zero(r) for r in mine):
        return TurnOff("breaker", c.id)
    return None


def _screen(i: Inputs, c: Kept) -> str | None:
    if not 1 <= int(c.discount_percent or 0) <= 100:
        return "no_discount"  # OF rejects the create: a burnt call per run
    if i.max_reactivations and int(c.reactivate_count or 0) >= i.max_reactivations:
        return "cap"
    if c.last_reactivated_at and i.now - c.last_reactivated_at < timedelta(minutes=i.cooldown_min):
        return "cooldown"
    if c.of_promo_id is None:
        # Never captured: "finished" and "still live" look alike, a create would duplicate.
        return "unverifiable"
    return None


def _after_end(i: Inputs) -> Verdict:
    due: list[int] = []
    cap = cool = no_disc = unverifiable = 0
    held: list[datetime] = []
    for c in i.campaigns:
        why = _screen(i, c)
        if why == "no_discount":
            no_disc += 1
        elif why == "cap":
            cap += 1
        elif why == "cooldown":
            cool += 1
            held.append(c.last_reactivated_at)
        elif why == "unverifiable":
            unverifiable += 1
        else:
            due.append(c.id)
    tally = Tally(len(due), cap, cool, no_disc, unverifiable)
    if due:
        return AfterEnd(due[0], tuple(due), tally)
    ends = min(held) + timedelta(minutes=i.cooldown_min) if held else None
    return Wait("nothing_due", tally=tally, cooldown_ends=ends)
