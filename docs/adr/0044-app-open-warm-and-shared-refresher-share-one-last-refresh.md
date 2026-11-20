# The App-open warm and the Shared refresher share one Last refresh per Creator

**Status: proposed** (2026-11-20, `.scratch/watched-creator-refresher/goal.md` netting rule and D4, owner decisions binding; amends ADR-0031's App-open warm reuse; nothing built yet).

ADR-0031's App-open warm reads every Creator an Employee can access on each open and reuses a Creator only within 30 s (`APP_OPEN_WARM_REUSE_S`); one warm of 10 Creators takes 38 s, longer than that window, so any open more than ~30 s after the last re-warms everything (measured). Beside a Shared refresher, two clocks would read one Creator twice: at a chatter's open and again at the refresher's slot. We decided each Creator has one Last refresh, written by whichever of the two read it: the warm answers `reused` with no reads for a Creator whose Last refresh is within its Cycle, and the refresher schedules a Creator's next read from its Last refresh, so a Creator just warmed waits for its next slot. Why: both read the same entries for the same tabs, and netting them lets the refresher replace the later-open cost (~230–370 OF calls per open at 50 Creators down to ~7, inferred) instead of stacking on it. The cost: "one refresh per open" now means "fresh within its Cycle", up to ~10 min old for a Creator without a View lease; going back to two clocks brings the double reads back.

## Considered Options

- **Two clocks (the warm's 30 s reuse beside the refresher's own schedule).** Rejected: each re-reads what the other just read.
