# Release 1 Placement is a static map on a Witness box; a human starts Failover; etcd comes last

**Status: proposed** (2026-11-26, `.scratch/agency-scale-out/phased-plan.md` Phases 1, 3, 6; ticket 03; nothing built yet).

Cell mode needs one answer to "which Cell owns this Creator" and someone to act when a Box dies. We decided that in Release 1 a person edits `fleet.toml`, fleet.py on the Witness box (another provider, SSH only) renders `placement.json` with a Placement generation and pushes it over the existing SSH path to every Box, which refuses a lower generation; the Front door reads only that local file and keeps the last good one with no expiry; Cells never read it and take their Owned Creators from `OI_ACCOUNTS` in their environment, the same reason as ADR-0041. A dead Box pages the human every 15 min with the exact `fleet.py failover` command. etcd (lease plus generation compare-and-set, a Conductor on the Witness box and 2 voter Boxes) comes only in Release 3, after a 10/10 power-off drill, 90 days of Witness logs on ≥5 Boxes, and ≥2 slow unplanned Box deaths; even then Cells never touch etcd when sending, and there is no peer-majority rule or local fallback. We chose this because safety comes from the Fence, the Owner epoch and session files on exactly one Cell, not from how fresh the map is, so a static map plus a human is enough to be safe and far less to run. The cost: Failover time is the owner's response time, and while the Witness box is down there are no moves, Failovers or new Creators (chatting and sending carry on).

ASSUMPTION: no signature on Placement in v1; root SSH from the Witness box is the only writer (overturned if a pull path via the bucket or etcd is added).
ASSUMPTION (g): 2 min down before paging, 90 days, 2 deaths; overturned by drills.

Amended 2026-11-26: at 1,000 models (15–40 Boxes, i) Box deaths are routine, so a human starting Failover is a stopgap for the 2-Cell demo only; Phase 6 (etcd automation) is required for scale (re-plan R6). The entry conditions above now gate turning Release 3 on, not building it.

Amended 2026-11-26 (R9): one box first, cross-box later. AE's Control and Cells all run on today's Box; cross-box moves, WireGuard and Box Failover are scale path.

## Considered Options

- **etcd or another consensus store from day one.** Rejected: quorum Boxes and an automatic takeover before the Fence is proven by drills.
- **Gateways fetching the map over the network.** Rejected: an unsigned fetch path; a local file is enough.
- **Cells reading Placement for ownership.** Rejected: a copied file or DB would carry ownership with it; the environment does not travel with a copy.
