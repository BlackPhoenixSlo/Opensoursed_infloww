# Leak history is an append-only status-change log; routine probes stay outside it

**Status: proposed** (2026-11-27, `.scratch/leak-tracker/goal.md` Phase 1; tickets 02, 10 as amended; nothing built yet).

The owner's existing tools lose Leak history: one records a removal date once, another clears it, so "came back" and "gone after notice" cannot be told apart. We decided every Leak has an append-only Leak event log (`seen` with its Leak source, origin-status change, `google_seen`, `notice`, `notice_outcome`, `scan_partial`) and every derived field (`first_seen_at`, `gone_at`, `came_back_at`, `gone_count`) is computed from it, never stored and overwritten. Routine Origin probes are not events: each Leak has one rolling Probe state (last probe time, consecutive dead count, last status) that `last_up_at` and the 2-dead-probes rule read, and only a resulting Origin status change is logged. A Leak is unique per (Agency, Creator, url key); the service dedupes scan work across Agencies but never shares Leak rows. We chose this because the log makes every count re-derivable and honest, while daily probes on every Leak would grow it without bound and turn it into a browsing record nobody needs. The cost: probe flapping below the 2-probe threshold leaves no trace, so flap rate must be measured from Probe state counters during the AE tracer, and a log written from day one cannot later be backfilled with probes it never kept.

ASSUMPTION: 2 dead probes in a row means gone; overturned if the measured flap rate is under ~2 %, then 1 probe is enough.

Amended in the plan review (2026-11-27): `scan_partial` is watch-scoped (a capped watch may have no Leak), so it is not a Leak event. It is an append-only `lane_day` row per (watch, UTC day, Leak lane) with its outcome and reason, outside the per-Leak log. Probe state also holds `first_dead`, `flaps`, `last_live_at` and `dead_since`; only `dead_since` is copied onto the gone status-change event.

## Considered Options

- **Every probe as an event.** Rejected: unbounded rows per Leak for no user-facing view.
- **Mutable status columns, as the existing tools have.** Rejected: that is how history was lost.
