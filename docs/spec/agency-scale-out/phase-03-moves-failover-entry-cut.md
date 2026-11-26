# Phase 03 — Moves, failover, entry cut, recovery benchmark

**Objective.** Before Release 1, a Cell can be moved, a dead Box or Control cell can be brought back on the spare, today's single Box can be cut into N data cells plus a Control cell, and all of it is measured on throwaway Boxes with FakeOF. Plan Phase 3 + Fable amendments 1, 7; tickets 10, 05, 03, 08, 02, 11, 12, 13; ADRs 0059, 0060, 0062, 0063.

## Problem Statement
- A move today waits `sleep 5`, compares `count(messages)`, copies via the bucket plus a full deploy (m, `fleet.py:1095-1104,1205,1237`). Failover restores one Cell at a time (m, `:1202`); `oi-restore` only warns on a hash mismatch (m, `oi-restore:52-65`).
- After a lossy restore an automation can resend; gap attribution, cooldowns and payroll go silently wrong.
- Pages are unreliable, a Hot cell is invisible, deploys use the caller's checkout (m, `fleet.py:572-658`).
- Carve never creates a Control cell, so today's Box has no way in. No recovery number is measured.

## Solution
- `fleet.py move`: ticket 10's lossless Planned move, journaled on the Witness box. `fleet.py failover`: ticket 03 item 5, parallel restores from Restore manifest v2, then ticket 05's reconciliation.
- The Witness box pages with the exact command. `fleet.py entry-cut` clones today's stopped Box N+1 ways (one-way).
- WireGuard between Boxes, a pinned image SHA per Cell, Hot cell signals in `fleet.py status`.
- A benchmark on 8–11 throwaway Boxes (or a scaled run naming what it does not prove) gives the numbers.

## User Stories
1. As the owner, I want `fleet.py move <cell> --to <box>` to grey a 15-model Cell ≤90 s p95, with automations paused by a Cell hold and claims drained first while chatters keep chatting, so that a move is barely noticed. [parallel-safe now]
2. As the owner, I want a move checked by sha256 of every listed file after `wal_checkpoint(TRUNCATE)` (busy=0, empty -wal), so that "copied" means byte-identical. [parallel-safe now]
3. As the owner, I want the copy to use a one-move key limited to the source IP and `rrsync -wo` into `<sid>.incoming`, removed before the final check, so that no lasting key can write a Cell. [parallel-safe now]
4. As the owner, I want `resume` to re-run the first undone step and `abort` before the rollback boundary to restart the source, so that a crashed move never strands a Cell. [parallel-safe now]
5. As a chatter, I want a lossless move to cause no 409s (Data generation unchanged, SSE resync only). [parallel-safe now]
6. As the owner, I want the source kept until the target's first good backup, and accounts failing Readiness held as "needs re-login" while the rest go live. [parallel-safe now]
7. As the owner, I want a dead Box paged after 2 min with the exact `fleet.py failover bN` command (repeated every 15 min), and pages for a Cell not ready (3/10 min), an older Placement generation >2 min, a missing `PLACEMENT-OK`, a fenced Cell, a Witness heartbeat >5 min old. [parallel-safe now]
8. As the owner, I want Failover to restore up to 3 Cells at once, ready ≤10 min after the Fence is confirmed. [parallel-safe now]
9. As the owner, I want `oi-restore` to stop on a hash mismatch or a Cell/Owner epoch differing from the DB restore point; an unreadable bucket keeps the Cell down; a too-old backup needs typed `accept-stale`; a missing `e{N}` falls back to `e{N-1}` with a Data generation bump. [parallel-safe now]
10. As the owner, I want Restore manifest v2 (sessions via `platforms.SESSION_FILES`), 5-min small-file backups, an hourly media tag, and age alerts (Litestream 10/60 s, small files 15/60 min, media 3 h, drill >8 days). [parallel-safe now]
11. As a chatter, I want manual chatting to work right after a lossy restore. [parallel-safe now]
12. As the owner, I want each thread's first automated send for 24 h after a lossy restore to wait on a non-marking peek (ADR 0050), an unmatched creator message newer than `reconcile_since` becoming an Unconfirmed send that holds that Fan. [parallel-safe now]
13. As the owner, I want Phase 2's restore hold (overdue jobs parked "may have sent (restore)") to fire on every lossy restore, and OF's native queue listed against the DB. [parallel-safe now]
14. As the owner, I want gap messages marked unattributed and gap-overlapping shifts held for my confirmation. [parallel-safe now]
15. As a chatter, I want chatting to continue when the Control cell dies, and it back on the spare ≤10 min. [parallel-safe now]
16. As the owner, I want fleet.py to refuse a Placement the spare could not take over (RAM; disk free ≥30% + 2× the largest DB). [parallel-safe now]
17. As the owner, I want move and Failover code platform-neutral (`SESSION_FILES`, string ids) so Fansly Cells need no rework, with automations held after a Fansly restore until a person releases them; admitting Fansly stays Phase 4's gate. [waits for MP mixed-platform restore drill]
18. As the owner, I want the same for Fanvue Cells; admission stays Phase 4's gate. [waits for MP Phase 2 merged]
19. As the owner, I want relay ports only on the WireGuard address, probes and watchdogs off loopback, and Caddy reaching other Boxes' Cells over WireGuard. [parallel-safe now]
20. As the owner, I want one hostname per Agency on 2 front Boxes, rendered apart from Cell ownership. [parallel-safe now]
21. As the owner, I want `fleet.py deploy` to run a pinned image SHA per Cell: box tools → data cells one at a time, stop at first red → Caddy + app → Control cell, refusing a Cell below `min_cell_proto`. [parallel-safe now]
22. As the owner, I want `fleet.py status` to flag a Hot cell, say "investigate", then print the whole-cell move. [parallel-safe now]
23. Moved to Phase 4 (`cell_plan.py` owns the grouping plan). This Phase reads a human-edited `fleet.toml`; drills use a fixture map.
24. As the owner, I want `fleet.py entry-cut` to turn today's stopped Box into N data cells plus a Control cell in one stopped window, warm-copied while live. [parallel-safe now]
25. As the owner, I want every non-owned Creator's whole session folder quarantined in each copy and the cut verified (folders == `OI_ACCOUNTS` == Placement per Cell; Cells disjoint; union == source set == Control cell reservations). [parallel-safe now]
26. As a master or owner, I want `cell_owned()` on reads, jobs and pumps, so that unpruned rows never double-count sales or show another Cell's Creators. [parallel-safe now]
27. As the owner, I want the Control cell backfilled and every Owner epoch written before first boot, so that the first chatter request after the cut works. [parallel-safe now]
28. As the owner, I want the old relay fenced right after the final copy (R9: `cell` kind on its container on box A — stopped and removed, restart none, two `docker inspect` reads), its stop confirmed before any Cell's egress opens, its data dir renamed aside whole so a restarted original cannot log in, and that dir kept frozen until every Cell passes a restore test. [parallel-safe now]
29. As the owner, I want the cut drilled on a prod DB copy offline (never prod): timed grey, Carve mutants red, agency totals equal. [parallel-safe now]
30. As the owner, I want the benchmark: 10 moves (p95 ≤90 s, hashes 10/10, 0 lost, 0 duplicates); the busiest Box killed and back ≤10 min after the Fence, then 15 min at inbox p95 ≤1 s, CPU ≤70%, RAM ≥25% free, steal p95 <10%; the Control cell killed; the Witness crashed after every step, including after an external write and before its journal line; one sibling Cell on the source Box stays live through each move; a front Box killed through the public hostname; disk free ≥30% + 2× largest DB through the 15 min; kill→page→operator start→Fence confirmed→ready→first good backup timed separately; data lost per class (Own data, sessions, media) recorded. [parallel-safe now]
31. As the owner, I want the N/N+1 smoke to pass with ticket 12's assertions after each step (only the restarting Cell 503, ≤20 s grey, 0 duplicates, N+1 restores N's manifest, N refuses to start under an N+1 `min_cell_proto`, N runs on the N+1 DB), with a Control-first upgrade failing. [parallel-safe now]

## Implementation Decisions
- **Owns.** fleet.py verbs `move`, `failover`, `restore`, `deploy`, `status`, `resume`, `abort`, `probe`, new `entry-cut`; the Witness journal; box tools `oi-backup`, `oi-restore`, new `oi-cell-stage`; WireGuard and front-route rendering; the Witness pager; relay `own_data` (new), `cell_owned()`, post-restore reconciliation in `send_ops`, lossy-restore marks; Hot cell metrics; container drills.
- **Interfaces.**
  - `fleet.py move <cell> --to <box>`, `failover <box> [--to <box>]`, `entry-cut --map fleet.toml [--offline <copy> --out <dir>]`, `resume <op>`, `abort <op>`. All run under the Witness lock (ticket 03 item 2).
  - `oi-cell-stage <dir> --owns platform:id,… [--role control|data]` quarantines and verifies one staged copy with ticket 11 item 2e's full checks (whole non-owned folders, no root `session_*.json`, `.migrated` present, `active.json` owned, no escaping symlink, non-owned proxy bindings dropped); on `data` it also blanks every agency-table field outside ticket 07 item 3's allowlist (passwords, TOTP secrets, recovery codes). Exit 0 only on a full verify. Phase 5's `carve` reuses it.
  - `cell-recovery-in-containers.sh --drill entry-cut --from <dir>` boots a staged `--out` tree instead of a synthetic one.
  - `cell_owned(account_id) -> bool | None`: None with `OI_ACCOUNTS` unset (no-op). Placed per ticket 11 item 4.
  - `own_data.checksum(db, account) -> sha256` over ticket 10 item 3's list, one read snapshot. Replaces `max(messages.rowid)` in the backup drill (m, `oi-backup:60-70`).
- **Schema.** Additive only: a `may_have_sent_restore` parked job state; per-Cell `reconcile_since` and `peek_until` in a cell-mode settings row; backfilled `creator_reservations` rows (table from Phase 1).
- **Contracts.**
  - Journal line `{op, kind: move|failover|entry_cut, cells, from, to, map_gen_expected, step, status, ts, evidence}`, one fsynced file per op at `/var/lib/oi-witness/<agency>/ops/<op>.jsonl`, copied to the laptop bundle. The intended Placement bytes are journaled before they are published. Every step first checks whether its external result already exists (ticket 10 item 4), so a crash between an external write and its journal line resumes without a second write.
  - Restore manifest v2: `{cell, epoch, data_gen, code_sha, db{ltx_path, txid, commit_at}, files, sessions{"platform:id":{platform, file, sha, mtime}}, proxies_sha, secrets_sha, env_sha, media}`. Readers ignore unknown fields.
  - Per-minute Box summary to the Witness: `{box, cells:{sid:{state, epoch, data_gen, placement_gen, litestream_lag_s, smallfile_age_s, media_age_s, ready_accounts, cpu, spills, pool_wait_p95_ms, route_p95_ms}}}`.
- **Planned move** = ticket 10 items 1–2, 4–6. Steps 6–8 call Phase 2's Fence and Egress gate; the epoch write carries op id and target Box. Same image SHA on both ends (preflight). Placement generation +2; `data_gen` unchanged. Sibling Cells on the source Box stay live. The automation pause is a Cell hold (Phase 2; why `move`, blocks automations), set before the drain so a source restart keeps it, copied with the DB, cleared by fleet on the target after `live` and on the source by `abort`.
  Decided 2026-11-26 (D3 = B, ADR-0063 Accepted; was needs-human): a Planned move with the source reachable uses a `cell` Fence (reboot-persistent nft egress block on that Cell's bridge + SSH read-back + containers stopped + the second-owner-refusing epoch write, so the Egress gate keeps a restarted source closed); an unreachable source becomes a Box Failover with the power Fence.
- **Failover** = Fence (SSH silence never counts) → publish `down` → restore ≤3 in parallel → Readiness → publish `live` → clean. It reads the journal, never the rewritten map. No DNS repoint in Cell mode. A failed Fence writes no Placement (Phase 2 story 25); the dead relay already greys its Creators (Phase 1). Drill asserts generation, box and journal unchanged after a failed Fence.
- **Lossy restore** bumps `data_gen`, sets `reconcile_since = commit_at − 60 s`, runs ticket 05 item 6 and ticket 10 item 10. Stale tabs get 409 via `X-Cell-Gen`.
- **Control cell Failover** uses the same verb. Its restored agency-copy snapshot carries a newer epoch (ticket 07 item 4), and its Employee-id counter starts above the highest Employee id in any Cell's Agency copy (ticket 06 item 4).
- **WireGuard** keys are minted on the Witness and rendered per Box. Relay and app bind the WireGuard address only in Cell mode; unset env renders today's loopback bind.
- **Per-cell deploy** builds from `git archive <sha>` on the Witness, loads the image on the Box, records the SHA in the manifest. Order and stop rule: ticket 12 N/N+1 rule 3. Rollback = a higher Placement generation naming the old SHA.
- **Hot cell** thresholds: ticket 02 item 5. Spills from the pool counter (m, `db/engine.py:56`), CPU from `ae_observe`, new per-route p95 and pool wait. Advice only; a human applies it.
- **Entry cut (decides ticket 13; rung 2, amendment 1, unless flagged).**
  1. *Once, stopped.* One stop yields one frozen source; all N+1 copies come from it. This supersedes ticket 12's "cell by cell". The Control cell boots first, then the data cells in parallel, all egress-closed; no Cell runs `oi-cell-open` until the journal holds the source's confirmed Fence (step 3); each goes `live` after Readiness. On the demo (R10) the cut runs in two waves, each its own stop and a fresh `.backup`: wave 1 `--accounts` moves 2–3 canary accounts' session folders out of the old relay, which restarts without them; wave 2 cuts the rest.
  2. *Preflight.* Placement comes from a human-edited `fleet.toml` (Phase 4's `cell_plan.py` drafts it for go-live). Every source account must be placed in exactly one data cell. Refuse on: an account that is not OnlyFans-with-proxy (ADR 0063); a bare id under two platforms; running remote-login jobs; an open S4S leg across Cells (ticket 11 item 2a); a target Box missing the image.
  3. *Copy, then fence the source.* Warm rsync to every target while live. Then set a Cell hold (why `entry_cut`, blocks automations), drain claims, stop, checkpoint, hash, take `own_data.checksum` per account, send the final delta into `<sid>.incoming`, and check hashes are equal. Then fence the old relay through Phase 2's one Fence path with the `cell` kind (R9, ADR-0063 amended): its container stopped and removed, restart policy none, two `docker inspect` reads on the same daemon both say no such container; then its data dir is renamed aside whole to `data.entry-cut-aside/<op>/`. The confirmed FenceResult is journaled. Its Cells run on the same Box, so a power fence would grey them (superseded by R9/R10 2026-11-26: the power-fence form stays for an unreachable source and cross-box, scale). Before the boundary, abort = rename the dir back, clear the hold, start. Wave 1 only: the canary folders move out whole, the old relay restarts without them, and its account list read twice must not list them; that is the fence proof for those accounts.
  4. *Control cell.* A full clone through `oi-cell-stage --role control` with `OI_ACCOUNTS` empty: every session folder and root `session_*.json` quarantined, `.migrated` kept, `active.json` removed, every proxy binding dropped. Its compose is Phase 1's Control template (`${OI_ACCOUNTS?}`); the drill boots it. Control-only tables (ticket 07 item 1) are live only here.
  5. *Data cells.* A full clone through `oi-cell-stage --role data`, with write-block triggers installed and non-allowlisted login fields blanked at stage. Agency-copy section shas cover allowlisted fields only and come from the same frozen DB, so the first apply is a no-op. Non-owned rows stay, closed by `cell_owned()` and Cell scope; no prune in Release 1.
  6. *Backfills, offline, before any boot.* One `active` reservation per placed account; eager mirror Employees and roles (ticket 07 item 9); grant generation 1; agency-copy versions. Owner epoch e1 with its Cell instance (Box + data dir) goes to the bucket per Cell (ADR 0063, R9); `data_gen` 0.
  7. *Verify:* story 25, plus `own_data.checksum` per account equal between the step-3 source value and the owning Cell. Then the **rollback boundary**. After it, forward only.
  8. *Open.* Per Cell: epoch write, boot egress-closed, `oi-cell-open` only with the step-3 FenceResult confirmed, Readiness, `live`, clear the Cell hold. The old data dir stays frozen (renamed aside) until every Cell passes a restore test.
  9. *Grey* is timed from source stop to the last Cell `live` as the Front door sees it.
  10. *One-way.* No merge back (OWNER-DECISIONS, ADR 0062). After the boundary, recovery is per-Cell Failover.
- **Prod-copy drill** = `entry-cut --offline`. It takes the DB copy only, never real session files. Synthetic session folders (with `session_*.json`) are made per account, plus one root `session_*.json` with no `.migrated` marker. Boots run on an internal docker network with `OF_API_ORIGIN` → FakeOF. Mutants, each must go red:
  - quarantine only `SESSION_FILES`;
  - drop the executor `cell_owned()`;
  - drop the read intersect;
  - skip the source fence (a powered-on original must make 0 authenticated FakeOF calls);
  - skip the session move-aside (same check, original powered on with its old compose);
  - open before the fence (a target's `oi-cell-open` with no confirmed source FenceResult must refuse);
  - skip reservations (another Cell's bootstrap of a placed id must 409);
  - skip the root-session check (a booted Cell must not rebuild a non-owned folder);
  - skip the field allowlist (a data Cell DB must hold no password hash or TOTP secret).

## Testing Decisions
- **Primary seam:** fleet.py verbs driven against container Boxes, using the `failover-in-containers.sh` pattern. The Hostinger stub is `api_stubs`. FakeOF (`slop/lib/of_wire.py`, standalone) records every HTTP call, send and socket keyed by (source Cell, account); today it keys by account only (m, `of_wire.py:159`), so the drill gives each Cell its own egress address and asserts 0 authenticated traffic from a non-owner, including a restarted original. An HTTP+SSE client with an actor token stays open through Caddy across each fault.
- **Drill contents beyond the stories:**
  - `move`: a sibling Cell on the source Box stays live; a failed Fence leaves Placement unchanged.
  - `failover`: corrupt one file, mismatch snapshot/DB epoch, deny the bucket, need typed `accept-stale`, drop `e{N}` → each refused before promotion, or (last) restored from `e{N-1}` with `data_gen` +1; then a stale tab gets 409, a manual send gives 1 FakeOF accept, an automated tick is parked.
  - `control`: chatting through the outage; Control back ≤10 min; held past `OI_CELL_MAX_GRANT_AGE_S` → `503 grant_age_exceeded`, as designed.
  - `witness`: two Boxes and a recording notifier; one delivery fails and is retried; Witness cut off → the Box-side page fires; Caddy reaches the other Box's Cell only over the WireGuard interface.
  - `upgrade`: N = base commit; N+1 = a throwaway drill commit adding one manifest field and one forward migration (never merged, no hook in `service/`); story 31's assertions after each step. One new script, `cell-recovery-in-containers.sh --drill move|failover|control|witness|entry-cut|upgrade [--break <mutant>]`. `--break` exits 0 only when that mutant's own check goes red, the same as the house `--break`.
- **pytest** (`deploy/fleet/tests`) covers:
  - journal resume and abort per step, and generation checks;
  - the file list, and the manifest v2 round trip with unknown fields;
  - spare refusal and deploy order;
  - Hot cell and page rules;
  - `oi-cell-stage` on temp trees.
- **Relay** (`service/tests`, plain scripts):
  - `test_own_data` fails on any unclassified table or column.
  - `test_cell_owned`: env unset is a no-op; covers actor/master ids, clamp, executor claims, orphan recovery and pumps.
  - `test_send_ops_reconcile`: peek, native-queue listing and the Fansly hold (parking is Phase 2's).
  - `test_lossy_restore_marks`.
- Every drill reruns with `OI_CELL_MAP` unset: compose and routes must be identical to main.
- **Prior art:** `test_failover.py`, `failover-in-containers.sh --break`, `backup-restore-local.sh <bindir>` (no `--break` mode, m `backup-restore-local.sh:9`), `test_send_once.py` (`_Killed`), `test_audience_coverage.py`, `api_stubs.py`.

## Acceptance
```sh
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
uvx --python venv/bin/python pytest -q deploy/fleet/tests/test_fleet.py deploy/fleet/tests/test_failover.py \
  deploy/fleet/tests/test_move.py deploy/fleet/tests/test_entry_cut.py deploy/fleet/tests/test_witness.py \
  deploy/fleet/tests/test_cell_deploy.py
for t in test_own_data test_cell_owned test_send_ops_reconcile test_lossy_restore_marks test_send_once; do
  venv/bin/python scripts/run_tests_parallel.py service/tests "$t" -j 8
done
scripts/run-tests.sh
nice -n 10 deploy/fleet/tests/backup-restore-local.sh "${OI_BR_BIN:?dir with litestream and restic}"
for d in move failover control witness entry-cut upgrade; do
  nice -n 10 deploy/fleet/tests/cell-recovery-in-containers.sh --drill "$d"
done
for m in session-files-only no-executor-filter no-read-intersect no-source-fence no-move-aside open-before-fence no-reservations no-root-session-check no-field-allowlist; do
  nice -n 10 deploy/fleet/tests/cell-recovery-in-containers.sh --drill entry-cut --break "$m"
done
nice -n 10 deploy/fleet/tests/cell-recovery-in-containers.sh --drill upgrade --break control-first
for m in restore-hash-warn no-epoch-check down-before-fence; do
  nice -n 10 deploy/fleet/tests/cell-recovery-in-containers.sh --drill failover --break "$m"
done
# manual: owner hands over a prod DB copy (never prod); run `fleet.py entry-cut --map fleet.toml --offline <copy> --out <dir>` then `cell-recovery-in-containers.sh --drill entry-cut --from <dir>`; record grey and totals
# scale path (2026-11-26): owner provides throwaway Boxes + a Witness box; load is --scale=small, no 1.25×P ladder
# scale path: benchmark on those Boxes (story 30 + N/N+1 smoke), or a scaled run whose report names what it does not prove
# demo done (2026-11-26):
test -s docs/cell-mode/p3-entry-cut-drill.md
# scale path done:
# test -s docs/cell-mode/p3-benchmark.md
```

## Depends on
- **Phase 0:** 0c measured Cell budget (the benchmark load; scale path only, 2026-11-26); 0i power-off drill and proxy-provider check; 0j alert fixes (pages need `notify.sh` to fail loudly); 0e kill-matrix baseline.
- **Phase 1:**
  - `fleet.toml` accounts, `placement.json`, `PLACEMENT-OK`;
  - `OI_ACCOUNTS`, `not_owner`, `X-Cell-Gen`/`data_gen`;
  - Agency copy and triggers, `creator_reservations`;
  - Actor token, Caddy router, the finished Cell scope and route guard with its object → account → owned resolver (ticket 09);
  - `min_cell_proto` and the acceptance script;
  - the Control cell template (`${OI_ACCOUNTS?}`).
- **Phase 2:**
  - `send_ops.dispatch()`, Send claims, Unconfirmed sends with Retry off;
  - `vm_id`, the typed Fence result, and the epoch write that refuses a second owner;
  - the Egress gate, and one Fence path for every promotion;
  - the Cell hold store, and its restore hold that parks overdue jobs "may have sent (restore)" (Phase 2 story 16).

## Out of Scope
- Carve and `carve-prune`: Phase 5 (reuses `oi-cell-stage`).
- etcd and automatic Failover: Phase 6.
- Go-live and the Feature table check: Phase 4.
- Real power-off 10/10 and the revoke check: Phase 0 (0i).
- Merging Cells or returning to one Box: the owner chose clone, never merge.
- Pruning after the Entry cut: optional, not needed for safety.
- Bio in Cell mode; comparing rows changed after a snapshot; a second page contact; the Witness provider: ticket 03/10 fog, the owner's call.

## Further Notes
ASSUMPTION: Entry cut is once and stopped; data cells boot in parallel after the Control cell (rung 2, amendment 1 over ticket 12). Overturned by: prod-copy grey over a quiet hour; then open cells in waves from the same frozen source.
ASSUMPTION: Entry-cut grey ≤15 min for the real layout (g, rung 5). Overturned by: the prod-copy drill timing.
ASSUMPTION: preflight refuses a non-admitted account (Fansly, no proxy) rather than leaving it out (rung 4). Overturned by: the owner signing those Creators "off" in the Feature table; then `--leave <key>` quarantines them everywhere.
ASSUMPTION: today's VM is power-fenced at step 3, before the rollback boundary, and kept frozen, not reused at once (rung 4; power-off and the folder move are both undone by abort). Overturned by: an owner rule to reuse it, re-imaged only after every Cell's restore test. (superseded by R9/R10 2026-11-26: the old relay container is cell-fenced, its data dir kept aside and frozen; no re-image, see Further Notes)
ASSUMPTION: a powered-on original is kept closed by moving its session folders aside, not by giving it cell-mode env so its Egress gate applies (rung 5; today's Box runs with `OI_CELL_MAP` unset, whose boot gate fails open). Overturned by: a drill where the original reaches OnlyFans with its folders aside (some path rebuilds a session); then also render it cell-mode with no Owner epoch. (R9: wave 2 also removes the container with restart none and renames the whole data dir aside; the deploy refuse marker stops a routine deploy recreating it.)
ASSUMPTION: the prod-copy drill uses synthetic session folders, never real ones (rung 4).
ASSUMPTION: this Phase owns WireGuard/front-route rendering (Phase 1 spec hands it here). The grouping script is Phase 4's `cell_plan.py`.
ASSUMPTION: the N/N+1 smoke's N+1 is a throwaway drill commit adding one manifest field and one forward migration, so the smoke is never trivial (rung 5; no test hooks in `service/`). Overturned by: a real format change shipping in the same window; then use it.
ASSUMPTION (superseded 2026-11-26: D3 decided B, see Further Notes): a Planned move with a reachable source uses the `cell` Fence (position B) until the owner decides D3 (rung 4: B keeps siblings live and is undone by lifting the nft block; not rung 2, ticket 10 and ADR-0063 were written by this run). Overturned by: the owner picking A; then the stories under "Rests on D3" park and a move greys the whole source Box.
ASSUMPTION: Failover publishes `down` only after a confirmed Fence, over ticket 03 item 5's order, to keep Phase 2 story 25 and ticket 04 item 5 true (rung 4). Overturned by: the owner wanting a `down` page state before the Fence; then Phase 2 story 25 must allow a state-only write.
ASSUMPTION: the relay gains per-route p95 and pool-wait metrics (i; only the spill counter is confirmed, `db/engine.py:56`). Overturned by: an existing exporter.
ASSUMPTION (g): 60 s drain, 3 parallel restores, 24 h peek, age and page thresholds (tickets 03, 05, 10). Overturned by: the benchmark.

### Re-plan 2026-11-26
Binding: `.scratch/agency-scale-out/replan-2026-11-26.md` (R1–R5, R8). Plan top: `phased-plan.md` "Re-plan 2026-11-26".
- **Paths.**
  - demo: 49 (story 10), 50 (26), 51 (25), 52 (2–4, 6; same-Box slot move), 53 (1, 5, story 30's sibling part), 54 (8, 9, 15, 16; containers only), 58 (21, 31), 59 (24, 25, 27, 28), 60 (29), 64 trimmed.
  - scale: 55 (11–14), 56 (19, 20: WireGuard, two front Boxes, cross-box move; R9), 57 (7, 22), 63 + 65 (30, 31 on real Boxes).
  - later: 61 (17), 62 (18).
  - No ticket waits on 25 (GATE).
- **D3 decided B** (ADR-0063 Accepted). 53 is unparked and on the demo path.
  ASSUMPTION: the owner wanted B (R2). Overturned by: the owner picking power-stop; then 53 parks again and a move greys the whole source Box.
- **Entry cut for the demo (R9/R10, 2026-11-26; replaces R3's two-box layout).** One Box: AE box A holds the old relay, Control, Cell 1 and Cell 2.
  - Shadow first (Phase 4 ticket 119): Control + Cells egress-closed on `.backup` copies, read-only, own hostname.
  - Wave 1 canary (120): the 6 lowest-revenue models into a small Cell 2; old relay restarts without their folders. Wave 2 full cut (77): the rest into Cell 1 (or Cell 1 + Cell 3); old relay container cell-fenced, data dir aside.
  - After every Cell's restore test, Cell 2 relocates whole to a new slot on A (78) with the `cell` fence; Control + Cell 1 keep sending. Adding a Creator to an existing Cell is a merge (ADR-0062), so the whole Cell moves.
  - Front door: one hostname on A's Caddy. WireGuard, two front Boxes and cross-box moves are scale (56).
  ASSUMPTION: a kernel or disk fault on A takes all of AE down; AMBER for the demo (owner R9). Overturned by: the owner wanting a second Box; then cross-box moves (56) rejoin the demo.
  ASSUMPTION: the Witness role runs from the owner's laptop for the demo; no Witness box, no spare (rung 5). Overturned by: a demo step needing the Witness up while the laptop is off.
- **Container drills mirror it:** one container Box: canary into Cell 2, full cut into Cell 1, then Cell 2 relocated to a new slot; siblings keep sending. Failover is shown here only (R8), in containers; a dead-Box power-stop drill is scale.
- **Trimmed demo Acceptance (64).** Keep: the pytest lines, `test_own_data`, `test_cell_owned`, `test_send_once`, `run-tests.sh`, `backup-restore-local.sh`, drills `move failover control entry-cut upgrade`, all entry-cut, failover and `control-first` mutants, `witness` drill for journal resume only (52). Move to scale: `test_send_ops_reconcile`, `test_lossy_restore_marks` (55), Witness paging and Hot cell (57), the benchmark (63, 65). Demo done = `p3-entry-cut-drill.md`.
  ASSUMPTION: the `witness` drill splits into resume (demo) and paging (scale) (rung 5, R8). Overturned by: 64's ticket finding paging cannot be cut from the drill; then 57 joins the demo.
- **Benchmark (65):** `--scale=small`, no 1.25×P; still the owner's paid Boxes; scale path.
- **Scale change (R6):** `fleet.py deploy` runs Boxes in parallel at ~100 Cells (`phase-07-hold-1000.md`); the demo keeps one Cell at a time.
- **Human (R7, R9):** the offline prod DB copy for 60.

## Review
codex (gpt, high effort; partly blind: .scratch readable through git objects), 2026-11-26. Blind call B1–B10, draft call D1–D14.

- B1 seam CLI → relay → Caddy → browser; `/livez` passes with no sessions — **partial**: Readiness already means session login (ticket 10); drills now keep an actor-token HTTP+SSE client through Caddy across each fault; screenshots stay with the benchmark run.
- B2 alternatives (defer build, bucket move, pre-staged spare, defer entry cut) — **reject**: build gate is Phase 0; move method and one-stop cut are ticket 10 and amendment 1 (rung 2); spare staging is a benchmark question already flagged.
- B3 fence scope conflict — **needs-human**, see D3. (superseded 2026-11-26: D3 decided B, see Further Notes)
- B4 `down` before Fence vs no Placement on failed Fence — **accept**, see D4.
- B5 crash between external write and journal line — **accept**: Placement bytes journaled first, each step checks its result exists, Witness crash after every step (story 30, Contracts).
- B6 loss contract per data class — **partial**: per-class loss now recorded in the benchmark report; an allowance for claims/credentials/payroll is the owner's, not set here.
- B7 entry-cut gaps (root sessions, original reboot, due jobs) — **partial**: root sessions added (D5); original reboot and due jobs already covered by `no-source-fence` and `no-executor-filter`.
- B8 recovery bar (timing split, grant expiry, front Box kill, mixed-version per step) — **accept**: story 30 timing split + front Box kill; `control` drill past grant age; story 31.
- B9 equal totals hide misassigned rows; `oi-epoch` same-epoch twice (m codex probe) — **reject**: per-account `own_data.checksum` already required (cut step 7); epoch CAS is Phase 2's, listed in Depends on.
- B10 healthy sibling greys during a neighbour's move — **accept**: story 30, move drill.
- D1 entry cut copies passwords/TOTP to data Cells (ticket 07 item 3) — **accept**: `oi-cell-stage --role data` blanks non-allowlisted fields; shas over allowlist; mutant `no-field-allowlist`.
- D2 empty `OI_ACCOUNTS` fails Phase 1's `:?` (m codex `docker compose config` exit 1) — **accept**: Control renders `${OI_ACCOUNTS?}`; drill runs `compose config`; ASSUMPTION added.
- D3 move fence kind: ticket 10 item 4 step 6 wants a per-Cell egress fence; ADR 0063 and Phase 2 (`FenceResult{kind: power|proxy}`) allow only power or proxy; power-stopping the source VM greys its sibling Cells (ticket 02 item 4: 2–3 per Box) — **needs-human**. Position A (ADR 0063 as written): every move power-stops the source Box, so a 1-Cell move greys 2–3 Cells; safest, breaks story 1's "barely noticed". Position B (ticket 10): a `cell` Fence kind (persistent nft block + SSH read-back + stopped containers + second-owner-refusing epoch write + boot Egress gate) for planned moves with a reachable source only; needs ADR 0063 and Phase 2's FenceResult amended. Spec defaults to B pending the call. Settles it: owner's yes to B, or a `move` drill where the source is rebooted and its containers restarted after the epoch write showing 0 FakeOF traffic from the source with B alone. (decided 2026-11-26: B, re-plan R2; ADR-0063 Accepted.)
- D4 `down` published before a failed Fence contradicts ticket 04 item 5 / Phase 2 story 25 — **accept**: Fence first, `down` after; drill asserts nothing written on a failed Fence; mutant `down-before-fence`.
- D5 root `session_*.json` with no `.migrated` rebuilds a quarantined folder at boot (m `accounts.py:57-85`, ticket 11 item 2e) — **accept**: `oi-cell-stage` runs 2e's full checks; drill plants a root session; mutant `no-root-session-check`.
- D6 `backup-restore-local.sh --break` sets `BIN_DIR="--break"` (m `backup-restore-local.sh:9`) — **accept**: Acceptance passes `$OI_BR_BIN`; hash-mismatch mutant moved to `--drill failover --break restore-hash-warn`.
- D7 prod-copy drill and benchmark are only comments; `--map`/`--from` mismatch; Witness crash only after irreversible steps — **accept**: Acceptance ends with `test -s` on both reports; `--map` added, `--from` declared; every step.
- D8 restore refusals and post-restore sends untested end to end — **accept**: `failover` drill now corrupts, mismatches epochs, denies the bucket, needs `accept-stale`, falls back to `e{N-1}`, then stale tab 409 / manual send / parked tick; mutants `restore-hash-warn`, `no-epoch-check`.
- D9 N/N+1 smoke can pass trivially — **accept**: throwaway N+1 commit with a manifest field + forward migration; ticket 12's per-step assertions (story 31). "N refuses N+1 loudly" read as `min_cell_proto` start refusal, since readers ignore unknown fields (rule 1).
- D10 FakeOF counts by account, not Cell (m `of_wire.py:159`) — **accept**: per-Cell egress address, keyed (Cell, account), 0 non-owner traffic incl. sockets.
- D11 pages and WireGuard routing lack an end-to-end seam — **accept**: `witness` drill with recording notifier, failed delivery, Witness cut-off, cross-Box via WireGuard only.
- D12 grouping script owned by both Phase 3 and Phase 4 (`cell_plan.py`, phase-04:50) — **accept**: Phase 4 owns it; story 23 moved; cut reads `fleet.toml`, drills use a fixture map; my own ASSUMPTION's overturn condition held.
- D13 Fansly/Fanvue admission pulled into Phase 3 — **partial**: stories keep their MP labels (run rule) but now promise platform-neutral code and the Fansly restore hold only; admission stays Phase 4's gate.
- D14 Depends on names the Phase 0 Cell scope draft — **accept**: now Phase 1's finished Cell scope and object resolver; also added Phase 2's restore hold, which story 13 now reuses instead of re-specifying.

### Plan review (six hats), 2026-11-26
- Black (b) source fenced after the boundary while Cells open; original boots fail-open with `OI_CELL_MAP` unset; Phase 4 only sees it after — **accept**: step 3 power-fences today's Box right after the final copy, before the boundary; step 8 refuses `oi-cell-open` without that confirmed FenceResult; session folders moved aside; mutants `no-move-aside`, `open-before-fence`; story 28.
- Green (b) power fence for the entry cut, original unable to reopen — **accept**: same change; one Box, no siblings, so A costs nothing; not on D3.
- Black: `OI_ACCOUNTS` empty template lives here but Phase 1 owns the template — **accept**: moved to Phase 1; step 4 and Depends on point there.
- Red / Black (d) Phase 3 reads like several phases — **partial**: stays one spec; ticketed as several tickets (move, failover + restore, entry cut, deploy + Hot cell, benchmark), each Blocked-by Phase 0's `GATE build` (superseded 2026-11-26: no gate edge); no new spec files.
- Black (d) benchmark needs 8–11 paid Boxes — **reject**: already a manual needs-human line with a scaled run that names what it does not prove.
- Black (d) three holds drift — **partial**: the move and entry-cut pause is now a Cell hold (Phase 2's store); it blocks automations only, so it differs from carve's in what it blocks and from restore's in who releases it: one term and store, three reasons.
- Green (a) pick B by ticket 10 (rung 2) — **reject** the rung: ticket 10 and ADR-0063 were written by this run; D3 stays needs-human, default B, ADR-0063 notes the pending call. (superseded 2026-11-26: D3 decided B, see Further Notes)
- Rests on D3 (unparked 2026-11-26, D3 = B): stories 1 and 5 (move with siblings live, barely noticed), story 30's "one sibling Cell on the source Box stays live", the Planned move fence line, the `move` drill's sibling check. Entry cut and Failover do not.
