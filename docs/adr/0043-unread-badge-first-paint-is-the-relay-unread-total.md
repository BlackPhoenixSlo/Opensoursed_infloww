# The Unread badge's first paint is the Relay's Unread total, not the rows the tab holds

**Status: proposed** (2026-11-20, `.scratch/watched-creator-refresher/goal.md` D6, Phase 2, owner decisions binding; source of the total waits on the plan's Q1; nothing built yet).

Under All Models a tab counts its Unread badge from the unread flags of the All-list rows it loaded, which age once a chat is read elsewhere: a fresh session showed 12 against 1 real unread row until the Unread chip was visited (owner, live), and the scenario's All list flags a chat `filter=unread` no longer returns (measured, `unread_parity.mismatches` 1). PR #881 makes the Unread chip's complete view win, but only once visited, and only for reads made in Inflowwww. We decided the Relay keeps one Unread total per Creator; a tab seeds its Unread badge from it at first paint, not from All-list flags, and the Relay pushes it on change over the Event stream, so a read on OF web clears every tab within one Cycle. Its source is the Live connection's counter frame if Q1 proves it reliable, else the Shared refresher's read (+1 OF call per Open-tab Creator per Cycle, inside ADR-0042's budget); the refresher reconciles it either way. Why: one Relay number is the same in every tab and costs no per-tab read, where a tab's rows are a partial, aging sample. The cost: the badge can disagree with the rows painted beside it until they reload, and the Roster count's rule that its window equals the Fan List's first page (`service/accounts_admin_api.py` ~305–320) no longer binds the Unread badge; the same notes record OF's `filter=unread` returning 0 for a Creator with an unread chat, so a polling source must not trust that list alone.
ASSUMPTION: the total is whole-inbox, not the Roster count's 25-chat window (rung 2 reading of the plan's "true unread total"); overturned if Q1 or the Phase 2 spec seeds from the Roster count.

## Considered Options

- **Keep All-list flags and patch them per event (#881's path).** Rejected: misses reads on OF web and a fresh session's first paint.
- **Seed from the Roster count.** Rejected: a 25-chat window that reads "N+" when full, not a total.
