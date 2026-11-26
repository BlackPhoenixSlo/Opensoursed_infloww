# Send claims live in each Cell's own SQLite, with no fallback store

**Status: proposed** (2026-11-26, `.scratch/agency-scale-out/phased-plan.md` Phases 1–2; ticket 05; nothing built yet).

With Cells moving and restoring, a send can go out twice: once from a stale owner, or again after a restore forgets it happened. We decided that in Cell mode every send runs through `send_ops.dispatch()` in the order Not owner → capability gate (ADR-0056) → Send claim → upstream, where the Send claim is a row committed in the Cell's own SQLite before the call, keyed by an Op ID built from a Send anchor saved before the send. One claim allows one wire attempt; a second only after a full 4xx from the Platform or a proxy refusal before any tunnel. A claim that cannot be written refuses the send: there is one claim store and no degraded path. A Send tripwire in each client send method raises `unclaimed_send` without a claim, so any sender with no anchor is refused; Retry is off and an Unconfirmed send waits for a person. etcd (ADR-0059, release 3) never holds claims and never runs beside this store: cells keep claims in their own SQLite and only pause sends when their box loses its etcd lease. We chose this because a remote store would sit in every send path (priority mass would need one remote write per Fan), while a local table moves byte for byte with a Planned move and is replicated by Litestream. The cost: WAL with synchronous=NORMAL survives a kill but not power loss (i), so after a lossy restore each thread gets a live non-marking peek for 24 h (g) before its first automated send; 6 send kinds stay refused until they have stable anchors (Release-1 Feature table); Fansly automations stay held after a restore until a person releases them.

ASSUMPTION: a full 4xx from OnlyFans means not accepted; overturned by a 4xx that still delivered.
ASSUMPTION: one local SQLite write per send is fast enough; overturned by claim p99 > 100 ms under load.

## Considered Options

- **A bucket compare-and-set write per send.** Rejected: a remote store in the send path.
- **Today's in-memory guards as the claim** (`mass_queue_api.py:28-45`, `sends_inflight.py`). Rejected: lost on restart; kept for the screen only.
- **A local fallback when the main store is down.** Rejected: two claim stores can both say yes.
