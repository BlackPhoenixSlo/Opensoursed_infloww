"""service/promo_keep_decide.py — Keep running's decision, pure (docs/spec/phase-01-promo-preempt.md).

One run of `automations/promo_reactivate` reads the Kept campaigns and OnlyFans's promo list,
then asks `decide` what to do: `Wait(reason)`, `AfterEnd(campaign)`, `TurnOff(reason)`, or, while
the Kept promo is still live, `Fill` (a Trusted count at the threshold) or `Timed` (OF's own end
time is near): the Pre-emption, behind PROMO_PREEMPT_ENABLED and the campaign's `preempt`. No I/O here, so the
table test (`test_promo_keep_decide.py`) drives every branch, like `dispatch_plan`.
The shell owns the reads, the create and the Re-checks. `Inputs` is a plain dataclass so
later guards (budget, back-off, fence, Pre-emption) add fields without touching callers.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Sequence, Union

from isotime import parse_iso


@dataclass(frozen=True)
class Kept:
    """One Kept campaign (`promo_campaigns` with `auto_reactivate`), the fields decide reads."""
    id: int
    of_promo_id: int | None
    discount_percent: int
    reactivate_count: int
    last_reactivated_at: datetime | None
    ticked_at: datetime | None = None   # keep_ticked_at: the breaker counts only creates since
    preempt: bool = False               # the campaign's second tick: Fill/Timed allowed


@dataclass(frozen=True)
class Created:
    """One automatic `created` Create reservation (the Zero-claim breaker's facts)."""
    campaign_id: int | None
    settled_at: datetime
    listed_at: datetime | None          # first read that showed its id live
    claims_seen: int | None             # the replaced promo's Claims at the create
    first_claims: int | None            # ... and on its first read while Kept


@dataclass(frozen=True)
class Memo:
    """The claim memo (`promo_keep_state`): the Kept promo last seen live and its Claims.
    `first_claims` is None once that history cannot be trusted (the first read had no
    count, or Claims went down since)."""
    kept_of_promo_id: int | None = None
    first_claims: int | None = None
    last_claims: int | None = None
    read_at: datetime | None = None
    finished_at: str | None = None      # OF's finishedAt on the last read of the Kept promo


@dataclass(frozen=True)
class Inputs:
    campaigns: Sequence[Kept]
    promos: Sequence[dict] | None      # OF's list, normalise_of_promo'd; None = OF unreachable
    now: datetime
    max_reactivations: int = 0         # lifetime cycle cap per campaign, 0 = none
    cooldown_min: int = 2
    memo: Memo = field(default_factory=Memo)   # already observe()d with this read
    # Earlier promos of the Kept campaigns (link_metrics past ids, ids their reservations
    # replaced): full by count only, they are ended, never a reason to wait.
    owned_ids: frozenset[int] = frozenset()
    creates: Sequence[Created] = ()    # automatic created reservations, newest first
    # Create budget and back-off (promo_create_guard.budget_state): the Creator's automatic
    # reservations of the last 24 h (any state; manual ones never count) and the latest
    # not_before a failed one set.
    auto_times: Sequence[datetime] = ()
    not_before: datetime | None = None
    # Pre-emption: the server switch; the memo before this read (Timed needs OF's end time
    # read twice unchanged); our clock against OF's (promo_keep_state.skew_s, None = unknown).
    preempt_enabled: bool = False
    prior: Memo = field(default_factory=Memo)
    skew_s: int | None = None


@dataclass(frozen=True)
class Tally:
    """The per-campaign screen of an After-end pass (the run's summary counts)."""
    due: int = 0
    skipped_cap: int = 0
    skipped_cooldown: int = 0
    skipped_no_discount: int = 0
    skipped_unverifiable: int = 0


@dataclass(frozen=True)
class Wait:
    """No create this run. `live`/`kept`: the Live promo shown and the Kept campaign it
    belongs to (None = another promo); `tally`: why nothing was due; `cooldown_ends`: when
    the hold ends (Cooldown, breaker_hold, backoff, budget); `wait_reason`: why a live Kept
    promo is not pre-empted though Pre-emption applies (the card's waiting line)."""
    reason: str
    live: dict | None = None
    kept: int | None = None
    tally: Tally | None = None
    cooldown_ends: datetime | None = None
    wait_reason: str | None = None


@dataclass(frozen=True)
class AfterEnd:
    """Re-create `campaign_id` (the first of `due`: OF holds one live promo, so one per run)."""
    campaign_id: int
    due: tuple[int, ...]
    tally: Tally = field(default_factory=Tally)


@dataclass(frozen=True)
class TurnOff:
    """Inflowwww turns Keep running off for `campaign_id`; `reason` is its keep_warning."""
    reason: str
    campaign_id: int


@dataclass(frozen=True)
class Fill:
    """Re-create `campaign_id` while its promo `live` is still on offer, at a Trusted count."""
    campaign_id: int
    live: dict


@dataclass(frozen=True)
class Timed:
    """Re-create `campaign_id` shortly before OF's own end time of its live promo."""
    campaign_id: int
    live: dict


Verdict = Union[Wait, AfterEnd, TurnOff, Fill, Timed]

BREAKER_N = 3
NOT_LISTED_S = 600      # a create's id not seen live this long after its settle is a zero row
BACKOFF_BASE_S = 120
BACKOFF_CAP_S = 6 * 3600   # caps the doubling only: OF's own Retry-After is honoured in full
BUDGET_HOUR = 3
BUDGET_DAY = 8
PREEMPT_MIN_CAP = 10    # a smaller cap (and 0 = unlimited) is never pre-empted
TIMED_LEAD_S = 120
SKEW_MAX_S = 30
_RATE_LIMITED = ("http_403", "http_429")
_OFF_AS_IS = ("captcha", "deactivated", "price_free")


def backoff_until(now: datetime, k: int, retry_after_s: float | None) -> datetime:
    """The k-th failed automatic create in a row: no next one before this."""
    doubling = min(BACKOFF_BASE_S * 2 ** (max(k, 1) - 1), BACKOFF_CAP_S)
    return now + timedelta(seconds=max(retry_after_s or 0.0, doubling))


def failure_turns_off(error_class: str | None, prev_class: str | None) -> str | None:
    """The keep_warning a failed create turns Keep running off with, or None (back-off only).
    A first 403/429 may be the proxy provider's (DC 403s), so only a second in a row stops."""
    if error_class in _OFF_AS_IS:
        return error_class
    if error_class in _RATE_LIMITED:
        return "rate_limited" if prev_class in _RATE_LIMITED else None
    if error_class and error_class.startswith("http_4"):
        return "create_refused"
    return None


def preempt_failure(error_class: str | None, prev_class: str | None) -> tuple[str | None, bool]:
    """A failed Fill or Timed: (the keep_warning Keep running turns off with, or None; whether
    its early tick goes off). Only the page's own state stops Keep running: a refusal of an
    early create says nothing about the After-end create that recovers it."""
    if error_class in _OFF_AS_IS:
        return error_class, False
    return None, failure_turns_off(error_class, prev_class) is not None


def threshold(cap: int) -> int | None:
    """The Trusted count a Fill needs, ceil(0.9 × cap) in integers; None: never pre-empted."""
    return (9 * cap + 9) // 10 if cap >= PREEMPT_MIN_CAP else None


def _flags_live(p: dict) -> bool:
    """OF's own flags say live (an inferred cap is still live to OF)."""
    return not p.get("is_finished") or bool(p.get("cap_inferred"))


def observe(memo: Memo, promos: Sequence[dict] | None, kept_ids: set[int], now: datetime) -> Memo:
    """Fold one OF read into the claim memo. Only a Kept promo OF calls live counts; a
    read with no count is no news, never a 0. A lower count for the memo's promo, whatever
    OF's flags say, untrusts it for good: the history is no longer monotonic."""
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
    # OF runs one promo at a time and a create ends the current one, so any Live promo
    # means a discount is on offer: stand down (two Kept campaigns would ping-pong). A promo
    # a create of ours replaced, still listed live, may still be on offer too: no exemption.
    by_of = {c.of_promo_id: c.id for c in i.campaigns if c.of_promo_id is not None}
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
    # Ended only by our Claims >= cap reading, OF's flags still live: a create would end a
    # promo OF still offers unless we watched this Kept promo fill from 0 (ADR-0039).
    m = i.memo
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


def _preempt(i: Inputs, c: Kept, p: dict, n_live: int) -> Verdict | str | None:
    """Fill or Timed for the Kept campaign `c` whose promo `p` is live, or why not (the
    waiting line). None: Pre-emption does not apply (switch, tick, cap < 10) or nothing is
    owed yet (a Trusted count under the threshold, the end not near)."""
    cap = int(p.get("subscribe_counts") or 0)
    if not (i.preempt_enabled and c.preempt and threshold(cap) is not None):
        return None
    if n_live > 1:
        return "second_live"      # not ours to end; the shell logs it for the 4 h sweep
    screen = _screen(i, c)
    if screen not in (None, "cooldown"):
        return None               # Keep running would not re-create it after the end either
    why: str | None = None
    v: Fill | Timed | None = None
    end = parse_iso(p.get("finished_at"))
    left = timed_left(end, i.now, i.skew_s)
    if left is not None and 0 < left <= TIMED_LEAD_S:
        if i.prior.kept_of_promo_id != p.get("of_promo_id") or i.prior.finished_at != p.get("finished_at"):
            why = "end_unconfirmed"
        else:
            v = Timed(c.id, p)
    elif left is None and end is not None and 0 < (end - i.now).total_seconds() <= TIMED_LEAD_S:
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


def timed_left(end: datetime | None, now: datetime, skew_s: int | None) -> float | None:
    """Seconds left to OF's `end` on OF's clock (skew = ours minus OF's, so OF's now is ours
    minus skew); None without an end or a known clock within SKEW_MAX_S."""
    if end is None or skew_s is None or abs(skew_s) > SKEW_MAX_S:
        return None
    return (end - now).total_seconds() + skew_s


def _recovery_slot(i: Inputs) -> bool:
    return recovery_slot(i.auto_times, i.now)


def recovery_slot(auto_times: Sequence[datetime], now: datetime) -> bool:
    """A Pre-emption ends the live promo even when its create fails: one automatic create
    must stay in both budget windows after it, for the After-end that recovers."""
    for n, span in ((BUDGET_HOUR, timedelta(hours=1)), (BUDGET_DAY, timedelta(days=1))):
        if sum(1 for t in auto_times if now - t < span) + 1 > n - 1:
            return False
    return True


def create_hold(auto_times: Sequence[datetime], not_before: datetime | None,
                now: datetime) -> tuple[str, datetime] | None:
    """Create back-off, then the Create budget (BUDGET_HOUR per rolling hour, BUDGET_DAY per
    rolling day of automatic creates): (reason, until) while an automatic create is held."""
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
    """The Zero-claim breaker, gating only a create (None: go). Hold: the newest automatic
    create's id not yet seen live, until NOT_LISTED_S after its settle. Trip: this campaign's
    last BREAKER_N creates since its tick all zero (replaced promo gained no Claims, or its
    own id never seen live). A late first sighting still proves it went live."""
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
    """Why Keep running may not re-create `c` now (After-end and Pre-emption alike), or None."""
    if not 1 <= int(c.discount_percent or 0) <= 100:
        return "no_discount"                  # OF rejects the create: a burnt call per run
    if i.max_reactivations and int(c.reactivate_count or 0) >= i.max_reactivations:
        return "cap"
    if c.last_reactivated_at and i.now - c.last_reactivated_at < timedelta(minutes=i.cooldown_min):
        return "cooldown"
    if c.of_promo_id is None:
        # Never captured: "finished" and "still live" look alike, a create would duplicate.
        return "unverifiable"
    return None


def _after_end(i: Inputs) -> Verdict:
    """Nothing is on offer: every Kept campaign's promo is ended or gone from history."""
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
