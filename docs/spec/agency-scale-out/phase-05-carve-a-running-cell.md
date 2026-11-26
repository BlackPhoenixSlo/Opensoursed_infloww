# Phase 05 — Release 2: carve a running cell

**Objective.** A human on the Witness box runs `fleet.py carve` and one busy data cell becomes two live Cells while the Agency keeps chatting, with 0 duplicate sends, 0 acts as a non-owned Creator, every half able to send, totals unchanged, and 11's drill passing 10/10 with its broken versions red. Plan: `.scratch/agency-scale-out/phased-plan.md` Phase 5; tickets 11 (decided detail), 09, 10, 06, 12, 13; ADRs 0062, 0063.

## Problem Statement
- In Release 1 a Hot cell's only fix is a Planned move of the whole Cell (02, 10). When one Cell holds too many busy Creators for any Box, moving it moves the problem.
- Today's only clone path, `fleet.py restore --as`, copies a whole shard with every session and no fence, then leaves pruning to a runbook (m `fleet.py:843-907`). A clone that keeps a non-owned Creator's `sessions/accounts/<id>/` folder rebuilds its login on boot (m `accounts.py:117-144`), so both copies could send as that Creator.
- Two equal epochs read "not stale" (m `oi-epoch:122-127`), so the untouched original could reopen.
- Unpruned copies hold each other's rows; without `cell_owned()` everywhere, sales and payroll double count (i, 11 §4).
- S4S books both legs in one transaction (m `s4s_requests_api.py:305-368`) and cross-cell S4S is closed (09): carving partners apart strands a deal. An `accepted` request never changes status again (m `s4s_common.py:15-21`: no verb leaves `accepted`), so openness must come from its slots.

## Solution
- One command, `fleet.py carve <cell> --out onlyfans:ID,… --to <box>`, run by a human on the Witness box. It reuses Phase 3's Planned move steps, Witness journal and Cell fence, and adds a persisted hold, Session-folder quarantine per half, a disjointness check, both Owner epochs bumped, an idempotent one-write reservation hand-off, a staged Placement generation then one generation flipping both halves live, and acks before writes reopen.
- Chatters see the source Cell's Creators grey for about 2 minutes (g), then back, each routed to its new Cell. Nobody re-logs in.
- Refused before anything changes: another fleet op open, open S4S legs across the cut, running remote logins, bare-id collisions, the Control cell, a bad `--out`, a Box whose tools cannot read carve records, missing bucket credentials for the new Cell.
- After the carve, restoring any pre-carve snapshot, including `restore --as`, is refused.
- Optional later: `fleet.py carve-prune <cell>` deletes the non-owned rows offline in a stopped window.

## User Stories
1. As the owner, I want one command that carves a named set of Creators out of a running Cell onto a Box, so that a Hot cell splits without a rebuild. [parallel-safe now]
2. As the owner, I want the verb to be `carve`, not `split`, so that it never reads as Split Inbox. [parallel-safe now]
3. As the owner, I want carve refused on the Control cell, when `--out` is not a non-empty strict subset of the Cell's Placement accounts, when a bare Creator id sits under two Platforms, while a remote login runs, or while any move, restore, failover or carve journal is open, so that no half is empty, ambiguous, half-captured or raced. [parallel-safe now]
4. As the owner, I want carve refused on any open S4S leg between a kept and a carved Creator (request `pending` or `skipped`; any slot `scheduled` or `posting`, past due included; `posted` with a check job not finished), naming each request, and allowed when every leg is settled, so that I keep partners together or settle both legs first without a finished deal blocking forever. [parallel-safe now]
5. As the owner, I want the S4S and remote-login checks re-run on the frozen copy after writes close, so that nothing opened during the warm copy slips through. [parallel-safe now]
6. As the owner, I want a persisted hold that survives a relay restart and, in the source Cell, refuses every mutating route plus job claims, pump provider writes, vault sweeps and new remote logins, so that nothing acts while the Cell is being cut. [parallel-safe now]
7. As a chatter, I want the source Cell's Creators to show grey (moving) and come back on their own, so that I keep chatting on everything else and never re-log in. [parallel-safe now]
8. As the owner, I want the frozen original never edited except clearing its hold on abort, both halves staged as copies, so that abort before the boundary is "clear hold, start the original" and the original then sends. [parallel-safe now]
9. As the owner, I want each half to quarantine the whole `sessions/accounts/<id>/` folder of every Creator it does not own, so that the half cannot rebuild that Creator's login. [parallel-safe now]
10. As the owner, I want each staged half checked offline (no root `session_*.json`, `.migrated` present, `active.json` owned, no symlink or escaping pointer, non-owned proxy bindings dropped, `OI_ACCOUNTS` set) with the DB untouched, so that a half boots only if it is clean. [parallel-safe now]
11. As the owner, I want the carve to verify session dirs == `OI_ACCOUNTS` == Placement per half, halves disjoint, union == pre-carve set == Control cell reservations, so that no Creator is lost or doubled. [parallel-safe now]
12. As the owner, I want the exact successor map and reservation delta journaled before the rollback boundary, so that a resume after a crash finishes the same carve. [parallel-safe now]
13. As the owner, I want both Owner epochs bumped before first boot, the source's bound to its new membership, so that the untouched original restarted later stays closed. [parallel-safe now]
14. As the owner, I want the frozen original put behind Phase 3's Cell fence, confirmed by a read after both epoch writes, before either half opens egress, so that an original restarted mid-carve can never send. [parallel-safe now]
15. As the owner, I want the carved Creators' reservations moved to the new Cell in one all-or-nothing write that checks the expected holder and replays as success for the same op, so that no Creator is reserved twice, not at all, or stranded by a lost reply. [parallel-safe now]
16. As the owner, I want a staged Placement generation listing the new Cell (both halves still `moving`) installed before boot, so that both relays pass the Phase 1 startup check. [parallel-safe now]
17. As the owner, I want both halves booted egress-closed with the hold on, and readiness to be one identity probe per owned Creator through its proxy, so that a Creator whose probe fails is held as "needs re-login" while the others go live. [parallel-safe now]
18. As the owner, I want one Placement generation flipping both halves `live` and writes lifted only after every Box acks `PLACEMENT-OK`, so that no Front door routes a Creator to the old half. [parallel-safe now]
19. As the owner, I want the hold lifted once no Send claim is in flight, with any Unconfirmed send left as its own per-Fan hold (05), so that a send in flight at the stop is never sent twice and one unresolved Fan never keeps a whole Cell grey. [parallel-safe now]
20. As the owner, I want Keep-running promos re-stamped only for campaigns of each half's Owned Creators, so that no half auto-creates promos for a Creator it lost. [parallel-safe now]
21. As the owner, I want the source cleaned only after both halves have their own bucket backup and each passes a restore test, so that the frozen copy stays my recovery point until then. [parallel-safe now]
22. As the owner, I want any restore of a pre-carve snapshot, and any `restore --as` from one, refused after cutover, with the readers shipped one release before carve can run, so that no restore tool, old or new, resurrects the uncut Cell. [parallel-safe now]
23. As the owner, I want `resume` to re-run the first step not done and `abort` to work only before the boundary, so that a Witness crash at any step ends in one consistent state. [parallel-safe now]
24. As a chatter, I want a stale tab, a direct relay POST or a due job aimed at a carved-away Creator to get `409 not_owner` from the old half (the job: no claim, no egress), so that nothing acts from the wrong Cell. [parallel-safe now]
25. As the owner, I want agency sales, stats and payroll totals equal before and after the carve, so that unpruned copies never double count. [parallel-safe now]
26. As the owner, I want an optional `fleet.py carve-prune <cell>` in a stopped window that deletes only model and model_via rows of non-owned Creators per Cell scope plus their cache files, so that the copies shrink later. [parallel-safe now]
27. As the owner, I want carve-prune to keep `accounts` stubs, grants, shift_assignments and S4S pair rows, so that cascades never wipe grants or S4S history. [parallel-safe now]
28. As the owner, I want carve-prune to pass only with foreign_key_check empty, integrity ok, 0 non-owned rows in model tables, owned Own data equal, then VACUUM, with the frozen copy kept and no Data generation bump, so that a prune can never lose owned data. [parallel-safe now]
29. As a developer, I want 11's drill and its mutants runnable as a local container proof on the real relay image, so that a regression goes red before a box costs money. [parallel-safe now]
30. As the owner, I want 11's drill 10/10 on throwaway boxes at held load, so that Release 2 ships on measured proof. [parallel-safe now]
31. As the owner, I want unset `OI_CELL_MAP` to leave the relay untouched by the hold and the new route, so that today's single Box is unchanged. [parallel-safe now]
32. As the owner, I want Fansly Creators carved only once Phase 4 admits Fansly (MP mixed-platform restore drill plus Fansly proxy support), so that a Fansly session is never quarantined untested. [waits for MP mixed-platform restore drill merged]
33. As the owner, I want Fanvue Creators carved only once Phase 4 admits Fanvue (MP Phase 2 plus the same drill), so that Fanvue sessions have a known folder layout. [waits for MP Phase 2 merged]

## Implementation Decisions
- **Owns.**
  - `deploy/fleet/fleet.py`: subcommands `carve`, `carve-prune`, `resume`/`abort` for journal kind `carve`; `restore` (both forms) gains the pre-carve refusal.
  - `deploy/fleet/bin/oi-epoch`: `put` accepts and stores membership; reads ignore unknown fields.
  - `deploy/fleet/bin/oi-restore`: refuses a snapshot at or below a Cell's carve record.
  - `deploy/fleet/bin/oi-shard-stat`: new read-only `s4s-open <shard dir> <accounts>` (runs on the live DB read-only for preflight and on the frozen copy for the recheck, one rule for both).
  - Phase 3's Session-folder quarantine tool: carve calls it per half; any 11 step-e assert it lacks is added there, not in a second tool.
  - Relay: Phase 2's `cell_hold` module and `cell_holds` store gain `blocks=writes`, checked in Phase 1's route guard (all non-GET routes), executor claim, `send_ops.dispatch()`, vault sweeps and remote-login start; one `cell_local` route reporting hold and drain state; rows in `service/cell_scope.json`.
  - Control cell: the Creator reservation module (Phase 1) gains a batch hand-off.
  - `service/scripts/promo_keep_restamp.py`: `--owned-only` limits re-stamping to `OI_ACCOUNTS`.
  - `deploy/fleet/README.md`: carve and carve-prune runbook.
- **Interfaces.**
  - `fleet.py carve <cell> --out platform:id,… --to <box> [--yes]`; `fleet.py carve-prune <cell>`; `fleet.py resume <op>`; `fleet.py abort <op>`.
  - `cell_hold.active() -> Hold | None` (Phase 2); carve sets a Cell-scope hold (`why=carve`, `blocks=writes`) with Phase 2's `oi-cell-hold` over SSH, never an HTTP call. While held, mutating routes answer `409 cell_held`.
  - `GET /api/cell/hold` (fleet bearer, box-local): `{held, op, remote_login_jobs, claimed_sends_inflight, uncertain_sends}`.
  - Control: `POST /api/cell/reservations/handoff {op, from_cell, to_cell, accounts:[platform:id], expect_placement_gen}` → 200 all moved; 200 `already_applied` when this `op` already committed this exact batch; 409 naming the first mismatched account (or a different batch under the same `op`), nothing changed.
- **Schema.**
  - No new SQLite tables (the hold is a Phase 2 `cell_holds` row). Control stores the hand-off `op` with the batch it applied (additive row or column in the Phase 1 reservations store).
  - Hold: one `cell_holds` row `{scope: cell, why: carve, blocks: writes, op, set_by, set_at}`; unreleased = held. It copies with the DB, so both halves boot held (story 17).
  - Bucket epoch object gains fields: `{epoch, box, by, op, accounts_sha}`. Source half: `e{N+1}` with its kept set; new half: `1` with its set.
  - Bucket carve record `<cell>/carved.json`: `{op, at_epoch, halves:[cell_a, cell_b]}`.
  - Witness journal line (10's form) with `kind:"carve"` plus `successors:{cell:[platform:id]}` and `reservation_delta`.
  - `fleet.toml`: a new `[[shard]]` for the new half; the source's `accounts` shrinks; new Cell's bucket secrets via `ensure_secrets` (m `fleet.py:451-490`, keyed by Cell id).
- **Contracts.**
  - Placement: generation G+1 (staged) adds the new Cell with both halves `moving`; G+2 flips both `live` in one write (Phase 3's move is also +2). Formats only gain fields (N/N+1 rules). The new half's Cell id is new; the source keeps its id.
  - Box ack: carve waits for `PLACEMENT-OK` (Phase 1) from every Box for G+1 before boot and for G+2 before removing the hold.
  - Not owner: the source half answers `409 not_owner` for carved Creators via `OI_ACCOUNTS` (Phase 1, Phase 3 `cell_owned()`); reservation 409 keys on the captured identity, rechecked at persistence (06).
  - Readers first (12 rule 2): the carve-record readers (`oi-restore`, `fleet.py restore`, `oi-epoch` membership) ship and reach every Box one release before `carve` is enabled; carve preflight refuses a Box whose `min_cell_proto` predates them.
- **Step order** (11 §2, plus fence and staged generation): a preflight (lock, refusals) → b warm rsync + hold + `moving` → c–d stop, checkpoint, sha256, per-account Own data checksum, final rsync, hashes equal, S4S + remote-login recheck on the frozen copy → e stage both halves offline → f verify → g journal successor map, **rollback boundary** → h bump both epochs, write carve record, Cell fence on the frozen original confirmed after the epoch writes, reservation hand-off → i publish G+1, acks, boot both egress-closed, open egress, readiness → j publish G+2, wait for acks, lift hold once no claim is in flight, owned-only promo re-stamp → k first bucket backup per half, cleanup after both pass a restore test.
- **Open S4S leg** = request `pending`/`skipped`, or any slot `scheduled`/`posting` (past due included), or `posted` with its check job not finished. An `accepted` request with every slot settled is not open.
- Before the boundary, abort clears the original's hold (`oi-cell-hold clear`, one-shot on the stopped Cell), republishes the original `live` at a fresh generation and starts it. After it, forward only. SSH lost before the boundary pages a human (10).
- The persisted hold also blocks new remote logins, so the step-d recheck is stable; preflight still refuses while one runs. ASSUMPTION below.
- Restores: `fleet.py restore` and `oi-restore` read the carve record; a snapshot whose epoch is ≤ `at_epoch` is refused, `--as` included. 10's `e{N-1}` fallback stays allowed only above `at_epoch`.
- carve-prune: own journal op, stopped window like a move, `PRAGMA foreign_keys=ON` before BEGIN, row selection from Cell scope `model`/`model_via` tables only (09), frozen copy kept, no `data_gen` bump (11 §5).

## Testing Decisions
- **Proof seam (one, highest):** `deploy/fleet/tests/carve-in-containers.sh [--break <mutant>] [--keep]`, built on `failover-in-containers.sh`'s two-box + MinIO harness for Box plumbing only, but running the real relay image built from the worktree (that harness loads a stand-in image, m `failover-in-containers.sh:82-84`), plus the Control cell, a Front door Caddy and FakeOF counting requests per account per Cell egress. It runs the real `fleet.py carve` end to end and writes `CHECK <name>: GREEN|RED` lines for 11's drill list plus the positive checks:
  - 0 duplicate sends; a send FakeOF accepted just before the stop ends with exactly 1 accept after the carve;
  - 0 authenticated requests, sends or sockets for a Creator from a non-owning Cell (due job for B in A's DB: no claim, no egress; direct relay POST and stale-tab request over HTTP: `409` body `not_owner`; capture with `bind_proxy` never called);
  - each half sends after the carve: one send per half = 1 FakeOF call + 1 `sent` row in the owning half;
  - one Creator with a failing identity probe stays "needs re-login" while the rest of its half is live;
  - Own data per kept Creator equal at stop = after carve = after prune; agency totals equal; session scan == `OI_ACCOUNTS`;
  - original restarted between stop and boot, and after cutover, stays closed;
  - abort before the boundary keeps the source hash and the original then sends;
  - cleanup refused while either half's restore test fails;
  - grey time printed.
  - `--break` mutants, each exiting 0 only when its own check goes red (house convention, m `failover-in-containers.sh:370`): `sessions-only` (remove only `SESSION_FILES`), `no-executor-filter`, `no-read-intersect`, `no-source-epoch-bump`, `no-source-fence`.
- **Fast seams under it:**
  - `deploy/fleet/tests/test_carve.py` (pytest, `api_stubs` SSH/bucket stubs): every preflight refusal (incl. open op, old box tools, missing bucket secrets); journal resume after a crash at each step; abort only before the boundary and clears the hold; both epochs, the carve record and the fence confirm before boot; G+1 before boot, G+2 with ack wait; pre-carve restore refused for both forms; carve-prune on a fixture SQLite keeps stubs, grants, shift_assignments and S4S pairs and passes foreign_key_check; `oi-shard-stat s4s-open` on each open-leg shape and on a settled `accepted` pair (allowed).
  - Control hand-off on a real Control SQLite (not a stub): 409 leaves reservations unchanged; commit → lost reply → same request replays `already_applied`.
  - `service/tests/test_cell_hold.py` (plain script): hold survives restart; refuses a mutating route (S4S accept, promo finish), executor claim, dispatch, vault sweep, remote-login start; route reports drain; env unset installs nothing and the route is absent.
  - `test_promo_keep_restamp.py` gains `--owned-only`; `test_cell_scope.py` covers the new route row.
- Prior art: `failover-in-containers.sh --break` (exit convention), `backup-restore-local.sh`, `test_failover.py` + `api_stubs.py`, `test_promo_keep_restamp.py`, `_s4s_fixtures.py`.

## Acceptance
```sh
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
uvx --python venv/bin/python pytest deploy/fleet/tests/test_fleet.py deploy/fleet/tests/test_failover.py deploy/fleet/tests/test_carve.py
venv/bin/python scripts/run_tests_parallel.py service/tests test_cell_hold
venv/bin/python scripts/run_tests_parallel.py service/tests test_cell_scope
venv/bin/python scripts/run_tests_parallel.py service/tests test_promo_keep_restamp
nice -n 10 deploy/fleet/tests/carve-in-containers.sh
for m in sessions-only no-executor-filter no-read-intersect no-source-epoch-bump no-source-fence; do
  nice -n 10 deploy/fleet/tests/carve-in-containers.sh --break "$m" || { echo "mutant $m not caught"; exit 1; }
done
scripts/run-tests.sh
# release gate (manual, owner yes per repo CLAUDE.md volume rule + paid throwaway boxes): 11's drill 10/10 at held load, grey p95 ≤120 s, witness crash after each step resumes, all five mutants red
```

## Depends on
- Phase 1: Placement install with generation checks and `PLACEMENT-OK` ack (meaning the Front door runs that generation, not only that the file landed), the startup check on `OI_CELL_ID`, `OI_ACCOUNTS`, `not_owner`, Control cell `creator_reservations`, the default-closed route guard and the finished Cell scope (incl. `model`/`model_via` rows used by carve-prune; drafted in Phase 0f).
- Phase 2: `send_ops.dispatch()`, Send claims, the Cell hold store and `oi-cell-hold`, the Fence path, the epoch write that refuses a second owner, the Egress gate.
- Phase 3: Planned move steps and Witness journal with its lock, Cell fence (ticket 10 item 6), move drain, one-move rsync key, manifest v2, Own data checksum, `cell_owned()`, Session-folder quarantine tool, restore-test tooling.
- Phase 4: Release 1 live, which this Phase carves, and its Platform admission gate (the demo cut is enough to start; the 7-day proof is not required, 2026-11-26).
- Ticket 05: per-Fan Unconfirmed send holds.
- A prior release carrying the carve-record readers on every Box (12 rule 2).

## Out of Scope
- Carving the Control cell: never (11 §2a).
- Merging Cells back: owner chose clone + delete (ADR-0062).
- Cross-cell S4S: closed in Release 1 (09); carve refuses instead.
- Turning Browserbase off during a carve: drain + captured-identity recheck suffices (11).
- Dropping the legacy `sessions.cookies_json` table: no runtime reader (m), agency-wide question, not carve's (11 fog).
- Auto-carve on Hot-cell signals: Release 2 is a human command; automation is Release 3's Conductor scope at most.
- etcd placement: Phase 6.
- A per-table checksum for the copy itself: file hashes prove the copy (10).
- Data generation bump on prune: rows removed were never served to the half (11 §5).
- Backup scope for vault media dirs: existing restic allowlist (m `oi-backup:43-48`); carve copies them by rsync, restore scope is Phase 3's.
- A first live carve in a quiet hour: the owner's call after the release gate, not this Phase's proof.

## Further Notes
ASSUMPTION: the persisted hold is Phase 2's `cell_holds` row, not a file in `data/` (rung 5; this line's earlier overturn held: Phase 2 ships a DB-row hold, Phase 3 reuses it). Overturned if a hold must be set on a Cell whose DB cannot be written while stopped; then a file beside the DB, read by the same `cell_hold` module.
ASSUMPTION: the hold blocks new remote logins as well (rung 5: smallest way to keep the step-d recheck true; remote-login jobs live only in relay memory, m `remote_login.py:221`). Overturned if a login started mid-carve must be allowed.
ASSUMPTION: the hold refuses every mutating route in the source Cell via Phase 1's route guard, not per-endpoint hooks (rung 5: its Creators are grey anyway; per-endpoint hooks missed promo finish/delete and S4S accept, m `server.py:4751-4760`, `s4s_requests_api.py:335`). Overturned if a write must stay open while grey.
ASSUMPTION: Browserbase stays on (11). Overturned if a login itself harms.
ASSUMPTION: grey p95 ≤120 s (11, g). Overturned by the drill's measured times.
ASSUMPTION: the source half keeps its Cell id and gets `e{N+1}`; the new half gets a new id at epoch 1 (rung 5: no re-key of the kept Creators' routes). Overturned if Placement needs both halves renamed.
ASSUMPTION: pre-carve restore refusal is a bucket carve record checked by epoch (rung 5: reuses the epoch object path). Overturned if manifest v2 already carries membership that restores can compare.
ASSUMPTION: S4S open-leg checks run read-only on the SQLite file via `oi-shard-stat`, live and frozen (rung 3: `oi-shard-stat` already opens the DB `mode=ro`). Overturned if read-only WAL reads on the live DB miss committed rows; the frozen-copy recheck is the binding one either way.
ASSUMPTION: the frozen original is fenced with Phase 3's Cell fence (egress block surviving reboot + SSH read-back, ticket 10 item 6), not a power fence (rung 5: the source Box keeps running the source half and siblings). Overturned if the owner picks A on Phase 3 D3 (needs-human); then the source half also lands on another Box. (2026-11-26: D3 decided B, so the Cell fence stands.)
ASSUMPTION: staged generation G+1 then live G+2 (rung 3: Phase 3's move uses +2). Overturned if Phase 1's startup check accepts a Cell absent from Placement.
ASSUMPTION: the local container drill is the laptop proof; 10/10 at held load on throwaway boxes needs the owner's yes and paid boxes (repo CLAUDE.md rung 2 for the yes; harness rung 3). Overturned if the owner waives the box run.

### Re-plan 2026-11-26
Binding: `.scratch/agency-scale-out/replan-2026-11-26.md` (R2, R4). Plan top: `phased-plan.md` "Re-plan 2026-11-26".
- **Path: later.** All of 82–95 (stories 1–33). Nothing on the demo or scale path waits on carve. Growing past a Cell's budget at 1,000 is done by moves (Phase 3) and new Cells, not carve (i).
- **D3 = B** (ADR-0063 Accepted). 92 is unparked but stays later.
- **No gate.** No ticket waits on 25.
- **Release 2 box run (95)** needs paid boxes and the owner's yes (R7).
ASSUMPTION: carve can wait until after 1,000 is held, because new Creators go to new Cells and moves rebalance (rung 5, R4). Overturned by: a Cell over budget that no move can fix, e.g. one Creator too big for its Cell's team split.

## Review
codex (gpt, reasoning high), 2026-11-26, partly blind (`.scratch/` readable via git objects; workspace lacked ticket 11 file).
Blind call:
- B1 alternative "stopped, fenced clone with warm pre-stage": **accept** — already the design; fence made explicit (story 14).
- B2 `carve` absent from fleet.py, ticket 11 missing in workspace (m): **reject** — expected, nothing built; ticket read from repo.
- B3 alternative "defer, whole-cell move only": **reject** — plan Phase 5 + ADR-0062 binding; move stays Release 1's answer.
- B4 alternative "online snapshot / selective export": **reject** — ADR-0062 clone + delete; selective export needs cross-Creator row closure the plan never asked for.
- B5 fence and blast radius on shared Boxes: **accept** — Cell fence on the frozen original, not power (story 14, ASSUMPTION).
- B6 serialize against other ops; crash points after epoch bump / hand-off / partial publish; stale tabs with equal `data_gen`: **partial** — lock added (story 3); hand-off replay (story 15); staged + live generations; stale tab already `not_owner` by `OI_ACCOUNTS`, independent of `data_gen`.
- B7 drain unknown sends; restorable post-carve backup; vault mounts not in backup: **partial** — per-half bucket backup before cleanup (story 21); drain via story 19; vault backup scope out of scope (Phase 3).
- B8 S4S under the write barrier; Master/restricted reads on unpruned clones: **partial** — recheck on frozen copy (story 5); totals + read-intersect mutant cover reads; Employee-role read matrix is Phase 3 `cell_owned()` proof.
- B9 drive real Caddy + app, HTTP/2 inbox, screenshots: **partial** — real relay image + Caddy + HTTP 409 checks added; app screenshots not added (no new UI; grey is Phase 1's).
- B10 one safety failure vetoes; witness kill per step; mutant per safety part: **partial** — already in drill; `no-source-fence` mutant added.
- B11 falsify the need for Release 2 by replaying peak load after move vs carve: **reject** — plan's proof is 11's drill; Hot cell metrics (Phase 3) inform the human's choice.
Draft call:
- D1 new half cannot boot before Placement lists it (Phase 1 story 3); ack must mean active Front door config: **accept** — staged G+1 then live G+2; Depends on states the ack meaning.
- D2 clone activation skips the confirmed Fence (ADR-0063): **accept** — step h Cell fence confirmed after epoch writes; drill restarts original mid-carve; mutant `no-source-fence`.
- D3 lost hand-off reply strands both halves: **accept** — same `op` + batch replays `already_applied`; tested on real Control SQLite.
- D4 hold misses promo finish/delete and S4S accept; abort leaves hold: **accept** — hold at route guard for all mutating routes; abort clears hold, drill proves a send after abort.
- D5 `accepted` S4S blocks the pair forever (m `s4s_common.py:15-21`): **accept** — openness from slots; settled-pair allow case tested.
- D6 readers-first rule and new Cell's bucket credentials: **accept** — readers one release ahead, preflight checks Box proto and secrets; per-half backup before cleanup.
- D7 mutant loop passes on a failed drill (m `42 0`): **accept** — harness exit code, `pipefail`.
- D8 proof passes with zero working sends; stories 7/15/17/19/22 lack checks; harness uses stand-in images (m `failover-in-containers.sh:82`): **accept** — positive send, failed-probe, in-flight-send, cleanup-refusal, HTTP 409 checks; real relay image.
- D9 wrong producers; per-Fan residual holds; Cell scope finished in Phase 1; "parallel-safe now" tags vs ticket 11 sequencing: **partial** — accept per-Fan holds (story 19), Phase 1 Cell scope, ticket 05 in Depends on; reject relabeling: owner rule limits story labels to MP status, phase order lives in Depends on.
- D10 quiet-hour live carve + 7-day watch is extra scope; Fansly/Fanvue need full Phase 4 admission: **accept** — live carve moved to Out of Scope; stories 32–33 inherit Phase 4 gates.

### Plan review (six hats), 2026-11-26
- Black (d) three holds drift (`cell_hold` file here vs Phase 2's DB row and Phase 3's move pause) — **partial**: this Phase reuses Phase 2's Cell hold store and refusal; the file is gone. Carve's hold stays a different kind (`blocks=writes`: every mutating route, pumps, sweeps, remote logins), so one term and store, not one behaviour.
- Green (a) pick B by ticket 10 (rung 2) — **reject** the rung: written by this run; D3 stays needs-human; this Phase keeps the `cell` Fence default. (superseded 2026-11-26: D3 decided B)
- Green doing-less: Phase 6 drop its Phase 5 dependency — **reject**, see Phase 6; nothing changes here.
- Red: every P5 ticket is Blocked-by Phase 0's `GATE build` (superseded 2026-11-26: no gate edge); the 10/10 box run stays the owner's yes.
- Rests on D3 (unparked 2026-11-26, D3 = B): story 14 and step h (Cell fence on the frozen original), the source half and siblings staying up on the source Box (Solution, story 7), the `no-source-fence` mutant's Cell-fence check, the fence ASSUMPTION. Under A the source Box powers off, so the source half must also land on another Box.
