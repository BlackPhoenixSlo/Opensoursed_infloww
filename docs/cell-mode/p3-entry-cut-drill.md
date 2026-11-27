# Phase 3 entry-cut drill (ticket 59)

This drill cuts a single-relay agency into Cells on loopback containers. It uses synthetic data only: no AE, no real VMs, no OnlyFans. Labels: **measured** means seen in a run, **inferred** means read from code or evidence, **guess** is unverified.

## What is drilled

`deploy/fleet/tests/drill_entry_cut.py` has two parts. Part A runs first.

- **Part A (box container + FakeOF).** It runs a live source relay on a box and cuts it in two waves. The Box runs the tools from `$OI/src/<sha>`, a `git archive` of a throwaway commit of the working tree plus any mutant patch.
  - Before wave 1:
    - root session refused;
    - a hand-edited Caddyfile refused until `replace_front = true`.
  - Wave 1 (s01 + s02):
    - fence;
    - folders moved out (`w1_folders_out`);
    - no source calls for K after the fence (`w1_k_source_silent`);
    - open blocked by the gate and marker;
    - a planted folder blocks open;
    - journal resume, each step ok once.
  - Wave 2 (s03):
    - an agency diff is refused;
    - container fence (relay gone);
    - checkout moved aside;
    - abort before the boundary restores the source;
    - abort after the boundary is refused, and resume finishes.
  - Finals:
    - verify_cells (own_data sums);
    - source silent;
    - Cells live;
    - Placement generation 5;
    - grey time;
    - `aside_untouched`: the wave-2 aside hashes to the digest journaled at `hash` (today's disk untouched);
    - `old_relay_back_silent`: after the wave-2 fence, the old compose comes back in the old checkout with its old env (a routine deploy). It must run and make 0 authenticated FakeOF calls for every moved account.
- **Part B (local, no docker).** It stages, backfills and boots s01 (Control), s02 and s03 (Data) from a synthetic source DB, or from `--from`. It uses `bin/oi-entry-cut` rows/delta and `bin/oi-entry-cut-backfill`. It checks:
  - quarantine and no secrets;
  - the reservation 409;
  - verify;
  - agency no-op apply;
  - the first request;
  - read scope and executor ownership;
  - no rebuild.
  - The real relay is also run on old checkouts:
    - `old_relay_w1` uses the tool's `out` move;
    - `old_relay_w2` uses the checkout layout Part A's real cut left on the Box, copied out of the box.

Every mutant run first asserts that the patched file is the one that ran (`setup_mutant_landed`, plus `setup_mutant_on_box` for `$OI/bin` tools). That covers the local fleet copy, `$OI/src/<sha>`, and `$OI/bin` after `step_tools`.

```sh
deploy/fleet/tests/cell-recovery-in-containers.sh --drill entry-cut            # Part A + B
deploy/fleet/tests/cell-recovery-in-containers.sh --drill entry-cut --break <m>
fleet.py entry-cut --offline <db> --out <dir> --accounts <ids>
deploy/fleet/tests/cell-recovery-in-containers.sh --drill entry-cut --from <dir>   # Part B on an offline cut
```

## Runs (measured, 2026-11-27, HEAD 3c19e3c97 + drill)

Verdict: green (read by `fleet.py preflight`: listed under `[preflight] proofs` in fleet.toml; a later red run must change this line)

| run | result | wall |
|---|---|---|
| full (A+B, env_unset) | 36/36 green | 342 s (A 164 s, B 174 s) |
| full, after the next main merge (readiness via main's Actor cookie) | 36/36 green; Part A mutants re-CAUGHT | 354 s |
| `--from` a fresh `--offline` cut of the synth DB | 12/12 green | 70 s |

The first full run on this code was 35/36. The only red was `env_unset`: its merge-base relay booted twice logged one 401 line in a different order, so the mask check stopped. That is not an entry-cut check (measured). The rerun was green.

## Mutants (measured, all CAUGHT, one loop on the final code)

| mutant | part | named red check | wall |
|---|---|---|---|
| session-files-only | B | stage_quarantine (+ b_verify) | 6 s |
| no-field-allowlist | B | no_secrets | 6 s |
| no-executor-filter | B | executor_owned | 72 s |
| no-read-intersect | B | read_scope | 71 s |
| no-reservations | B | reservation_409 (+ b_verify) | 4 s |
| no-root-session-check | A | root_session_refused | 19 s |
| open-before-fence | A | open_needs_fence | 68 s |
| no-source-fence | A | old_relay_back_silent: 22 auth calls each for both W accounts (+ container_fence, w2_aside) | 86 s |
| no-move-aside | A | old_relay_back_silent: 22 auth calls each for both W accounts (+ w2_aside) | 87 s |
| canary-folder-left | A | w1_folders_out + w1_k_source_silent: 6 source calls each for both K accounts after the fence | 44 s |

A mutant counts as CAUGHT only if every named check is red. For the source-call checks, the relay must also have reached FakeOF. The normal run shows the brought-back original running with 0 calls (measured).

## Grey time (measured, sequential)

The waves run one after another on one box. The window runs from `stop` to `live`, as recorded in the journal.

| wave | grey_s | fleet.py time inside window |
|---|---|---|
| 1 | 66.0 s | 46.4 s |
| 2 | 16.1 s | 16.1 s |

Both windows include the drill's deliberate kills and resumes. Wave 1 is also stopped at boot and retried with a planted folder. So these numbers are upper bounds for the drill, not production numbers (inferred).

## Bugs found by the drill

- **`TOOLS` lacked `oi-placement`.** On a fresh source box, wave 1 failed at `step_placement` (measured).
- **`front_want` rendered unplaced shards.** Wave 2's "installed" render included s03 routes, so the guard refused wave 1's front (measured). The fix drops the box's unplaced shards, keeping front and open.
- Test fixtures, after the main merge (measured):
  - `drill_move.move_sql` could not read main's f-string `_HELD_IDX`, so every drill using the move box stopped at setup.
  - The standin's `cell_meta` lacked `section_sha`, so the backfill's `agency_copy.install` failed. The standin now builds `service/cell_mode`'s shape.

## Residual risk (needs human)

After wave 1, the old relay keeps running for the wave-2 accounts. If someone re-logs a wave-1 canary on it, the relay rebuilds that account's folder, and the account then has a second owner. With env unset there is no proxy binding, so egress is Direct; dropping bindings is not a fence. **Rule: never re-login canaries on the old relay.**

Wave-2 preflight now refuses (`relogged:`) a source folder or root `session_<id>.json` whose account already lives in an open Cell. That case is pytest-proven only (`test_wave2_refuses_a_canary_relogged_on_the_source`, measured). It bounds the damage to the time between the re-login and wave 2; the relay still works the canary until then (inferred).

## Not proven

- A real DB copy: ticket 60, owner hands it over and runs `--from`.
- AE waves of 120 and 77 accounts (owner-run).
- Load or scale.
- Real TLS and Traefik.
- Real OF sessions.

The synthetic DB covers the schema plus seeded defaults. Real-data shapes are not covered (inferred).
