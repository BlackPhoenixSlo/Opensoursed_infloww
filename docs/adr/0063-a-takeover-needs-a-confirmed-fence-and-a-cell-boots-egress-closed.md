# A takeover needs a confirmed Fence, and a Cell boots with egress closed

**Status: proposed** (2026-11-26, `.scratch/agency-scale-out/phased-plan.md` Phases 0, 2, 3; ticket 04; nothing built yet).

Two live owners of one Cell send twice, and today both are possible: fleet.py finds the VM to stop by IP (`fleet.py:1030-1031`, m) and two writes of the same epoch both pass (`oi-epoch:138`, m). We decided every promotion (Failover, Planned move, restore, clone activation) goes through one Fence: a power fence stops the VM id stored in Placement and counts only on a `success` action plus two `stopped` reads ≥5 s apart with a matching IP, read again after the Owner epoch write, which refuses a second Box at the same epoch; a proxy fence counts only when every proxy the Cell can use is revoked and a drill has shown the provider drops open tunnels, else it is unavailable. SSH silence or a bare Enter never fences; if both fences fail nothing is restored and the human is paged. In Cell mode a Cell boots behind an Egress gate that docker requires, lifted only when the bucket's Owner epoch matches; an unreadable bucket keeps a booting Cell closed but leaves a running one open. "No proxy" means refuse, so Release 1 admits only OnlyFans Creators with a proxy. We chose this because the owner wants fail closed: a duplicate send or two sessions on one account is worse than downtime. The cost: Failover waits on the provider API, a bucket outage blocks Cells from booting, and Fansly (always direct) waits for its own drill.

ASSUMPTION (evidence blocked): proxy providers offer per-Cell credentials or a revoke API; overturned by their docs.
ASSUMPTION (g): 180 s confirm window; overturned by measured Hostinger stop times.

## Accepted 2026-11-26: cell fence kind for planned moves with a reachable source

A power fence stops the whole VM, so a Planned move of one Cell would grey its 2–3 sibling Cells (position A, this ADR as written). Position B adds a third kind, `cell`: a reboot-persistent nft egress block on that Cell's bridge, read back over SSH, its containers stopped, then the epoch write that refuses a second Box, with the Egress gate keeping a restarted source closed. Only for a Planned move or Carve whose source answers SSH; an unreachable source is a Failover with the power fence. Amended 2026-11-26: D3 decided B (re-plan R2, `.scratch/agency-scale-out/replan-2026-11-26.md`): the demo's live move of Cell 2 must keep its sibling Cell live. Tickets 47, 53, 78, 92 unparked.
The Entry cut does not depend on this: today's Box has no siblings, so it is power-fenced right after the final copy, and no Cell opens egress until that stop is confirmed. (superseded by R9/R10 2026-11-26)

Amended 2026-11-26 (R9, `.scratch/agency-scale-out/replan-2026-11-26.md`): AE's Control and Cells run on today's Box beside the old relay, so the Entry cut fences the old relay with the existing `cell` kind, no new kind: its container stopped and removed with restart policy none, confirmed only by two `docker inspect` reads on the same daemon, then its data dir renamed aside whole (abort = rename back and start). No proxy revoke: each model keeps its own proxy. The Fence result and the Owner epoch are keyed by Cell instance (Cell, Box, data dir), not by Box, so a second instance of a Cell on the same Box is refused like a second Box. Power fence stays for an unreachable source and for cross-box moves (scale path).
ASSUMPTION: the owner wanted B (R2, inferred from "least blocking" + "show all work live"). Overturned by: the owner picking power-stop (A), then 47/53/78/92 park again; or a `move` drill showing a restarted source reaching FakeOF under B.

## Considered Options

- **SSH failure as proof the old Box is gone.** Rejected: a frozen or partitioned Box comes back.
- **Revoking one Creator's proxy.** Rejected: pool proxy failover moves Creators to another proxy (ADR-0030).
- **Today's fail-open boot gate.** Kept only with `OI_CELL_MAP` unset.
