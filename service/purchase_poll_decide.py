"""
The purchases poll's decisions, pure: no DB, no OF, no clock of its own (the
caller passes `now`, monotonic seconds).

`purchase_poll.start_fast_poll` ticks every `FAST_S` and, per Creator, asks
`tier` (Demand: a View lease or an enabled Seller -> "fast", else "slow") and
`due` (is the tier's interval up since its last poll). ADR-0031, phase-01 1a.

Knobs, read here only: `PURCHASES_POLL_FAST_S` (default 30 s, the loop's tick
and a Demand Creator's interval) and `PURCHASES_POLL_SLOW_S` (default 300 s, an
Idle Creator's). soak/timing/knobs.py reads the literal defaults.

The Backoff ladder (phase-01 stories 42-46, OnlyFans only): `after` folds a poll's `Outcome`
into the Creator's state. A 429 holds its next poll for the longer of OF's asked wait
(of_pacing.asked_wait: Retry-After, else "Please allow N seconds") and the rung,
`PURCHASES_BACKOFF_BASE_S` (30) doubling per failure in a row up to `PURCHASES_BACKOFF_MAX_S`
(900): OF's usual "allow 1 seconds" never stops the climb. A 401 the strict dead-session
classifier does not recognise (`unauthorized`) climbs the same ladder. The first ok resets it.
The hold runs from OF's answer to the failing poll. The one cap, `PURCHASES_BACKOFF_DEMAND_MAX_S`
(120), is `hold_s`'s: while the Creator has Demand its hold never passes it, a longer ask
included, so a Creator gaining Demand mid-hold is capped at once. `dead` holds nothing: a
Dead-session Creator leaves the live set (transaction_ingest.live_account_ids), so a cleared
flag resumes polling on the next cycle. `error` neither climbs nor holds.
`catch_up`: the poll after a gap longer than a fast interval and a tick pages back, up to
`PURCHASES_CATCHUP_MAX_PAGES` (3) pages (purchase_notifications.poll_purchases).
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass, replace
from typing import Literal

from env_knob import env_float

Tier = Literal["fast", "slow"]

_DEFAULT_FAST_S = 30.0
_DEFAULT_SLOW_S = 300.0
# The loop sleeps at least transaction_ingest._MIN_CYCLE_GAP_S (5 s) between cycles.
_MIN_FAST_S = 5.0


FAST_S = env_float("PURCHASES_POLL_FAST_S", _DEFAULT_FAST_S, _MIN_FAST_S)
SLOW_S = max(FAST_S, env_float("PURCHASES_POLL_SLOW_S", _DEFAULT_SLOW_S, _MIN_FAST_S))
BACKOFF_BASE_S = env_float("PURCHASES_BACKOFF_BASE_S", 30.0, 1.0)
BACKOFF_MAX_S = max(BACKOFF_BASE_S, env_float("PURCHASES_BACKOFF_MAX_S", 900.0, 1.0))
BACKOFF_DEMAND_MAX_S = env_float("PURCHASES_BACKOFF_DEMAND_MAX_S", 120.0, 1.0)
CATCHUP_MAX_PAGES = int(env_float("PURCHASES_CATCHUP_MAX_PAGES", 3.0, 1.0))
# A Select refresh reads no feed whose last ok poll started under this long ago (5 s at the 30 s tick, the loop's
# own floor between cycles): the data it would fetch is that fresh already, and alternating selections or new tab
# ids read a Creator at most once per this. Scales with FAST_S (slop runs FAST_S 5 s).
SELECT_MIN_AGE_S = FAST_S / 6

OutcomeKind = Literal["ok", "rate_limited", "unauthorized", "dead", "error"]


@dataclass(frozen=True)
class Outcome:
    """One purchases poll's answer (purchase_notifications.poll_purchases). `retry_after_s`: OF's
    asked wait on a 429 (of_pacing.asked_wait: the header, else its "allow N seconds" text), None
    when it named none.
    `reason`: account_health.is_session_dead_error's, on `dead`."""
    kind: OutcomeKind
    retry_after_s: float | None = None
    reason: str | None = None


@dataclass(frozen=True)
class PollState:
    """One Creator's poll bookkeeping, held in Relay memory: a restart polls every Demand Creator on its
    first cycle and spreads the Idle ones over SLOW_S (`first_idle_state`).
    `last_s`: the loop cycle (monotonic s) that last polled it (None: only a Select refresh has).
    `last_ok_s`: when its last ok poll actually started. `step`: failures in a row on the ladder.
    `held_at` / `hold_s`: when OF answered the failing poll (the loop's or a Select refresh's) and
    its hold, uncapped: the longer of OF's ask and the rung (the Demand cap is `hold_s()`'s)."""
    last_s: float | None = None
    last_ok_s: float | None = None
    step: int = 0
    held_at: float | None = None
    hold_s: float = 0.0


def tier(leased: bool, seller: bool) -> Tier:
    """Demand (a View lease, or an enabled Seller) is fast; an Idle Creator is slow."""
    return "fast" if leased or seller else "slow"


def interval_s(t: Tier) -> float:
    return FAST_S if t == "fast" else SLOW_S


def hold_s(state: PollState, t: Tier) -> float:
    """The hold in force: the state's, never above BACKOFF_DEMAND_MAX_S for a Demand ("fast")
    Creator (the one cap)."""
    return min(state.hold_s, BACKOFF_DEMAND_MAX_S) if t == "fast" else state.hold_s


def held(state: PollState | None, t: Tier, now: float, ahead: float) -> bool:
    """True while a 429 / unauthorized hold is on at `now`: now < held_at + hold_s. `ahead` looks one
    poll ahead for a Demand ("fast") Creator: held only while now + ahead is still inside the cap.
    `due` passes FAST_S (the loop's next tick); the one gate, purchase_poll._single_flight,
    passes 0 at each poll's real start (the loop's and a Select refresh's): no poll before OF's
    wait, nor before the cap when the cap wins."""
    if state is None or state.held_at is None:
        return False
    if now >= state.held_at + hold_s(state, t):
        return False
    return t != "fast" or now + ahead <= state.held_at + BACKOFF_DEMAND_MAX_S


def due(state: PollState | None, t: Tier, now: float) -> bool:
    """True when the tier's interval is up since the last poll (never polled: due) and no hold is
    on (`held`, a tick ahead). Half a tick of slack on the interval: the loop stamps each cycle's start and
    cycles ~FAST_S apart, so a cycle landing a hair early never skips a whole tick (a fast Creator
    every cycle, a slow one every SLOW_S / FAST_S cycles)."""
    if held(state, t, now, FAST_S):
        return False
    if state is None or state.last_s is None:
        return True
    return now - state.last_s >= interval_s(t) - FAST_S / 2


def ladder_s(step: int) -> float:
    """The hold after `step` failures in a row with no Retry-After: 30, 60, 120, 240, 480, 900, 900..."""
    return min(BACKOFF_BASE_S * 2 ** max(0, step - 1), BACKOFF_MAX_S)


def after(state: PollState | None, outcome: Outcome, started: float, answered: float) -> PollState:
    """`state` once a poll that actually started at `started` got `outcome` at `answered` (`last_s`
    is the loop's, kept). ok: the ladder reset, `last_ok_s` = started. rate_limited / unauthorized:
    one rung up and, from `answered`, a hold of the longer of OF's asked wait and `ladder_s`
    (uncapped: `hold_s` caps it). dead: no hold and no rung (the Creator leaves the live set
    instead). error: unchanged."""
    s = state or PollState()
    if outcome.kind == "ok":
        return replace(s, last_ok_s=started, step=0, held_at=None, hold_s=0.0)
    if outcome.kind in ("rate_limited", "unauthorized"):
        step = s.step + 1
        ra = outcome.retry_after_s if outcome.kind == "rate_limited" else None
        hold = max(ladder_s(step), 0.0 if ra is None else ra)
        return replace(s, step=step, held_at=answered, hold_s=hold)
    if outcome.kind == "dead":
        return replace(s, step=0, held_at=None, hold_s=0.0)
    return s


def catch_up(state: PollState | None, now: float) -> bool:
    """True when the last ok poll is older than FAST_S + one tick (or there is none: a restart),
    so this poll pages back for what the gap held; an Idle Creator's slow interval is such a gap."""
    return state is None or state.last_ok_s is None or now - state.last_ok_s > 2 * FAST_S


def polled(state: PollState | None, now: float) -> PollState:
    """`state` once the loop's cycle `now` polls the Creator (`last_s`)."""
    return replace(state or PollState(), last_s=now)


def first_idle_state(account_id: str, now: float, state: PollState | None) -> PollState:
    """`state` (its hold and last-ok kept) once the loop first sees an Idle Creator it has not polled:
    `last_s` set to a stable per-Creator phase (crc32 of its id) across the SLOW_S / FAST_S cycles.
    Without it every Idle Creator starts on the same stamp and comes due in the same cycle, in lockstep every SLOW_S: that cycle runs long (a
    Seller in it starts late) and bursts the shared proxies; spread, each cycle carries about
    n_idle * FAST_S / SLOW_S of them."""
    slots = max(1, round(SLOW_S / FAST_S))
    return replace(state or PollState(), last_s=now - SLOW_S + (zlib.crc32(account_id.encode()) % slots) * FAST_S)

