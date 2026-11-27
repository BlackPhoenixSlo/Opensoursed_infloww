# Notices reach the Removal service by a daily laptop push of confirmed sends only

**Status: proposed** (2026-11-27, `.scratch/leak-tracker/goal.md` Phase 3; ticket 09 as amended; nothing built yet).

Notices are filed by several of the owner's tools on the owner's laptop, each with its own ledger, some of which overwrite themselves, and none reachable from the server (their UI is loopback-only). We decided a laptop exporter reads those ledgers read-only and pushes them daily (launchd, 13:00, nice 10, full replay each run) to the Removal service with the owner's Ingest key. Only confirmed sends count, per channel (a site form needs an ok row with a message id, a Google DMCA filing a report id and per-URL evidence; a form mark with no URLs is dropped). Each event's id is sha256 of tool, channel, URL, filing ref, kind and outcome, so a replay adds nothing and a later decision is a new event; self-overwriting ledgers are diffed and only changes appended. A Notice that arrives before its Leak waits by url key. Creators are mapped only through the owner's two CLI maps (source-tool client → Removal client → Agency + Creator), never by handle, and Service status is set there, never inferred from Notices. We chose this because a push needs no new listener on the laptop or the server's view into it, and full replay with content-addressed ids makes missed days self-healing. The cost: Notices lag up to a day (the page shows "Notices updated <time>" and a stale banner past 48 h), history the ledgers already overwrote is lost for good, and changing the id recipe later re-imports everything as new.

ASSUMPTION: history from before a client cancels stays visible read-only to that Agency; a transfer needs a new mapping.

## Considered Options

- **The service pulls from the laptop.** Rejected: the laptop's tools listen on loopback only.
- **Map Creators by handle.** Rejected: ambiguous rows would attach Notices to the wrong Agency; ambiguous rows are withheld and listed for the owner instead.
