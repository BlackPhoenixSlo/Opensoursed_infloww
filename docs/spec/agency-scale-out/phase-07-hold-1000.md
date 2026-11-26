# Phase 07 — Hold 1,000 models and 1,000 chatters, proved by small tests

**Objective.** Every part of Cell mode that grows with the number of Cells has been run alone at 100-Cell size with stubs or on one machine, the scale changes are built, and one scale report states what 1,000 Creators and 1,000 chatters rests on, each number labelled m/i/g.

Inputs: `.scratch/agency-scale-out/replan-2026-11-26.md` R1, R5, R6 (binding); OWNER-DECISIONS.md 2026-11-26 ("Load test only small parts"). ADRs 0058–0064, no new ADR unless story 15 fires. Path: scale (after the AE demo) for every story here. Cross-box moves (ticket 56: WireGuard, move key) are scale too: the demo runs AE on one Box (R9). The one demo-path change, the All inbox asking only the Cells it needs, is already in Phase 01 (story 30 and its Fan-out decision, folded into ticket 35).

## Problem Statement
The owner wants one Agency of 1,000 Creators and 1,000 chatters. That is ~100 Cells (i) on 34–50 Boxes (i). One Cell at its budget is ticket 26's job, and each Cell shares nothing. Nobody has tested the parts every Cell shares, which get heavier as Cells are added:
- **Front door.** One Caddy carrying ~11,000 open streams (i: 1,000 chatters × 6 + 50 broad actors × 101).
- **Control cell.** It answers 100 copy pollers and 1,000 token renewals.
- **Placement.** One file listing 1,000 Creators, pushed to every Box.
- **Agency copy.** It resends a whole changed section to every Cell (m, ticket 07 item 4).
- **Deploys.** Today a deploy goes one Box at a time (m, `deploy/fleet/fleet.py:959-979`), and ticket 58 makes it one Cell at a time, which means hours at ~100 Cells (g).
- **All inbox.** Today it asks once per account (m, `app/hooks/useChatList.ts:326-333`).

The owner ruled out a full-size load test.

## Solution
Test each shared part alone, on the laptop at nice 10, against stubs:
- Front door: 100 stub Cells and 1,000 fake chatters.
- Control cell: 100 pollers, 1,000 renewals and one grant edit, with one real data cell under load.
- Placement: render and push for 1,000 Creators to 50 stand-in Boxes.

Build three changes:
- A grant edit sends only the changed person's rows.
- Deploys run on several Boxes at once and stop a Box at its first red.
- A small fallback, built only if the 125-stream browser test (ticket 22) fails.

One command collects every number into a scale report using R5's honest wording. No paid fleet. Slop runs only at `--scale=small`, after the owner's yes as a ticket's last step.

## User Stories
1. As the owner, I want a Front door test, so that I know one front Box carries the whole Agency when its twin is down. Caddy is rendered by fleet.py from a 1,000-Creator, 100-Cell `fleet.toml`. Load: 100 stub Cells, 1,000 fake chatters on ~5 Cells each, and 50 broad actors on all 100. Everyone signs in within 60 s, then 15 min steady. It reports added latency p50/p95/max, error rate, Caddy CPU and open files. [parallel-safe now]
2. As the owner, I want that run to count requests and streams per fake chatter and fail if any chatter touches a Cell outside its grants, so that Phase 01's "only granted Cells" rule is proved at 100 Cells. [parallel-safe now]
3. As a chatter, I want one Placement push (a Caddy reload) during that run to cost each stream at most one reconnect, so that adding a Creator never drops the floor. [parallel-safe now]
4. As the owner, I want a Control cell test, so that sign-in and revokes hold at 100 Cells. Setup: one real Control cell seeded with 1,000 Employees and 1,000 Creator reservations. Load: 99 stub pollers plus 1 real data cell, 1,000 token renewals in 60 s, and one grant edit mid-burst. It reports renewal p95, time until all 100 Cells hold the edit, and control CPU. [parallel-safe now]
5. As a chatter on a busy Cell, I want the grant apply on the real data cell timed during a fan-write burst at ticket 26's D rate (20 DMs/min until D exists, g), so that a grant edit never stalls my sends. It reports apply time and the longest fan-write wait. Last step: ask the owner for one `--scale=small` inbox slop run beside it. No answer means skipped, and the report says so. [parallel-safe now]
6. As the owner, I want Placement rendered for 1,000 Creators, 100 Cells and 50 Boxes, with time and file size, so that the map stays safe when large. Every refusal (a Creator in two Cells, an unknown Box, one bare id under two platforms) must still fire at that size. [parallel-safe now]
7. As the owner, I want Placement pushed to 50 Boxes, 10 at a time, so that one dead Box never blocks a map change. It reports total time. An unreachable Box is named while the rest update, and the generation rule holds on every Box. [parallel-safe now]
8. As the owner, I want every Phase 07 test to target loopback only, run at nice 10, refuse any other address and take the one-run-per-machine lock, so that no load reaches prod, AE or a paid Box. [parallel-safe now]
9. As the owner, I want a grant edit for one person to send only that person's grant rows, a removed list and a root hash to each Cell (copy `format: 2`), not whole sections × 100 Cells. Each Cell applies each changed person-section whole, as in ticket 29. [parallel-safe now]
10. As the owner, I want a Cell whose root hash differs after an apply to fetch the full section list and repair itself, so that it never drifts silently. [parallel-safe now]
11. As the owner, I want the Control test to print every copy section's size at the 1,000-chatter seed and one grant edit's total bytes under format 1 and format 2, so that I know which section to split next. Any whole section over 256 KB (g) is flagged. [parallel-safe now]
12. As the owner, I want `fleet.py deploy --rolling` to run one canary Box alone, then up to `--parallel N` Boxes at once (default 8, g), so that 100 Cells deploy in minutes, not hours. Each Box restarts one Cell at a time (box tools → data cells → Caddy and app), and the Control cell goes last. [parallel-safe now]
13. As the owner, I want a red Cell to stop its own Box at once and stop every other Box from starting its next Cell, so that a bad image never spreads. Cells already restarting finish. The output names what runs the new SHA, what runs the old one, and what was not touched. [parallel-safe now]
14. As the owner, I want `fleet.py deploy --rolling --plan` to print the waves for the real `fleet.toml`, and the drill to time one step, so that 100-Cell wall time = waves × measured step (i). [parallel-safe now]
15. Only if ticket 22 fails at 125 streams: as a broad actor, I want live streams capped per tab at the largest count that passed, with the other Cells kept fresh by the existing head-page poll (`app/hooks/useChatList.ts:383-416`), so that the fallback stays as small as the failure. Only if that misses the 45 s staleness rule do we build ADR-0061's gateway fan-in, under a new ADR. [parallel-safe now]
16. As the owner, I want one command to gather every part into a scale report for my phone, so that the claim never outruns the proof. Parts: 15, 22 and 26 from Phase 00, plus stories 1–7, 11 and 14. It prints the evidence-qualified claim, labels every number m/i/g, writes "incomplete" for any missing part, and lists Phase 06 as needed for 1,000. [parallel-safe now]
17. As an installer, I want `OI_CELL_MAP` unset to stay byte-identical to main, and a `fleet.toml` with no `agency` to render as today, so that the single Box is untouched. [parallel-safe now]

## Implementation Decisions
- **Owns.**
  - New: scale harnesses beside the container drills (stub Cells, fake chatters, Front door, Control, Placement push runners) and a scale report tool.
  - Modified: fleet.py `deploy --rolling` (box-parallel, `--parallel`, `--plan`) and the Placement push (10 at a time); the Relay's Agency copy module (format 2); the app's stream cap (story 15 only).
- **Interfaces.** Harness scripts take `--cells --chatters --cells-each --broad --out --break` and write `<part>.json`. `--plan` changes nothing.
- **Contracts.**
  - Copy format 2 is Phase 01's shape plus `root_sha` and `removed`: `{format:2, epoch, version, grant_gen, root_sha, sections:{name:{sha256, rows}}, removed:[name]}`.
  - The 5 grant tables and people rows split into one section per person (`grants/<person id>`). Every other section stays whole.
  - `root_sha` = sha256 over the sorted `name:sha` list.
  - A Cell polls with `accept=2`, and control sends format 2 only once every Cell in Placement has asked for it, so old and new versions run side by side (ticket 58).
  - Grant rows stay unfiltered (ticket 07 item 2). `grant_gen` is unchanged.
  - Part JSON: `{part, numbers:[{name, value, unit, label, how}], budget, pass}`. The report refuses a number whose label is not m, i or g.
  - Part names (`<part>.json`, read by `deploy/fleet/scale_report.py --in <dir>`, repeatable): `stall` (15), `stream` (22), `cell_budget` (26), `front_door`, `control`, `loaded_cell`, `placement`, `deploy_plan` (14), `copy_sections` (11). Extra scalar keys (e.g. `slop`) print as notes.
- **Schema.** Cell-mode installer only: `agency_copy_sections(name TEXT PRIMARY KEY, sha256 TEXT NOT NULL)` replaces `cell_meta.section_sha`.
- **Budgets (all g).**

  | Part | Budget |
  |---|---|
  | Front door | Added p95 ≤50 ms, max ≤500 ms, errors ≤0.1% (an intended 409 or 400 is not an error), open files ≤50% of the limit |
  | Control | Renew p95 ≤300 ms; edit on all 100 Cells ≤5 s |
  | Loaded Cell | Apply write lock ≤250 ms; longest fan-write wait ≤1 s |
  | Placement | Render ≤5 s; push to 50 Boxes ≤60 s |
  | Deploy | 100 Cells ≤45 min (i) |

- **Stub Cells**: one Python process (standard library only, like `deploy/fleet/tests/api_stubs.py`) on 100 loopback ports. It answers the inbox bundle with fixed-size JSON, sends one stream event per 2 s, and answers `409 not_owner` for a Creator it does not hold.
- **Fake chatters**: an asyncio driver over httpx (in venv, m), with a seeded, fixed grant spread.
- **Placement push test**: 50 ssh host aliases on one local sshd container, through `OI_FLEET_SSH` (m, `fleet.py:505-509`), as `failover-in-containers.sh:62-68` does. Each alias has its own Box root.
- **Deploy halt**: a red ends the run once the steps in flight finish. Rollback stays a higher Placement generation (ticket 58).
- **Ticket 26 sizing**: each Cell carries ~50 granted chatters plus 50 broad actors, so ~100 streams (i). Ticket 26's "chatter share" should be run at ≥100.

ASSUMPTION: ~5 Cells per chatter and ≤50 broad actors (g). Broad actors are the owner, managers, and chatters with no restriction rows, who see every Creator (m `service/chatters.py:143-164`). Overturned by ticket 66's grouping plan; rerun the tests with its numbers.
ASSUMPTION: fake chatters use HTTP/1.1 (no `h2` in venv, m). That means more Caddy connections than browsers make, so it is harder on Caddy (i). Overturned if a human installs `h2` and an h2 rerun costs Caddy more.
ASSUMPTION: per-person sections, not row deltas (rung 5: keeps whole-section apply, the sha check and delete-missing). Overturned by one person's section above 64 KB at the 1,000 seed.
ASSUMPTION: a red on one Box stops new starts everywhere (rung 4). Overturned by the owner wanting other Boxes to finish.
ASSUMPTION: laptop numbers stand in for a front Box (g). Overturned by an optional human rerun on one idle throwaway Box that comes out more than 1.5× worse.

## Testing Decisions
- **Seams.** Each part is tested from outside, through its real entry point:
  - Front door: the real rendered Caddyfile, driven over HTTP.
  - Control cell: the real Relay in cell mode on a temp dir, through `/auth` and `/fleet/agency-copy`.
  - Placement and deploy: real fleet.py over the SSH seam, and the Phase 03 container drill `upgrade` with `--parallel`.
  - Scale report: pytest over fixture part files (a label missing, a part missing, a budget missed).
- **Mutants.** Each goes red when its break is switched on:

  | Mutant | Breaks |
  |---|---|
  | `fanout-all` | The app asks every Cell |
  | `no-root-check` | A Cell skips the root hash |
  | `no-stop-on-red` | A red Box does not stop the deploy |
  | `serial-push` | The push goes one Box at a time and misses its budget |

- **Prior art.** `deploy/fleet/tests/failover-in-containers.sh`, `api_stubs.py`, `test_calibrate.py`, ticket 22's spike, Phase 01's `cells-acceptance.sh`.
- **Slop.** None by default (repo CLAUDE.md). Story 5's last step only, `--scale=small`, owner yes.

## Acceptance
```sh
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
P=venv/bin/python
OUT=.scratch/agency-scale-out/scale; mkdir -p "$OUT"
$P -m pytest -q deploy/fleet/tests/test_fleet.py deploy/fleet/tests/test_placement.py \
  deploy/fleet/tests/test_cell_deploy.py deploy/fleet/tests/test_scale_report.py
$P scripts/run_tests_parallel.py service/tests cell_agency_copy -j 8
(cd app && pnpm exec vitest run cell)
nice -n 10 deploy/fleet/tests/scale/front-door-load.sh --cells=100 --chatters=1000 --cells-each=5 --broad=50 --out "$OUT"
! nice -n 10 deploy/fleet/tests/scale/front-door-load.sh --cells=100 --chatters=1000 --break fanout-all --out "$OUT/mut"
nice -n 10 deploy/fleet/tests/scale/control-load.sh --pollers=100 --renewals=1000 --out "$OUT"
! nice -n 10 deploy/fleet/tests/scale/control-load.sh --pollers=100 --break no-root-check --out "$OUT/mut"
nice -n 10 deploy/fleet/tests/scale/placement-push.sh --accounts=1000 --cells=100 --boxes=50 --out "$OUT"
! nice -n 10 deploy/fleet/tests/scale/placement-push.sh --boxes=50 --break serial-push --out "$OUT/mut"
nice -n 10 deploy/fleet/tests/cell-recovery-in-containers.sh --drill upgrade --parallel
! nice -n 10 deploy/fleet/tests/cell-recovery-in-containers.sh --drill upgrade --parallel --break no-stop-on-red
$P deploy/fleet/scale_report.py --in "$OUT" --out "$OUT/scale-report.md" --check
nice -n 10 deploy/fleet/tests/cells-acceptance.sh --env-unset
scripts/run-tests.sh
# manual: brew install caddy (once, if ticket 22 has not already)
# manual: owner yes/no for one slop/run <inbox scenario> --scale=small beside control-load.sh (no answer = skipped, report says so)
# manual: owner reads scale-report.md on the phone
```

## Depends on
- **Phase 01.**
  - Front door Caddy cell block (28).
  - Agency copy (29).
  - Actor token and revoke (30, 31).
  - Only-granted-Cells All inbox and streams (35, 36).
  - Placement render and install (27).
- **Phase 03.**
  - One-Cell-at-a-time deploy (58).
  - Front Boxes (56).
  - Container drills.
- **Phase 00.**
  - 22, resized to 125 streams (R5): decides whether story 15 fires.
  - 26 (one Cell at budget) and 15 (stall check): their numbers feed the report.
- **Phase 06.** Not needed to build this Phase. It is needed for the 1,000 claim: at 34–50 Boxes, Box deaths are routine (ADR-0059). The report lists it.

## Out of Scope
- A full 1,000/1,000 run or a 1.25×P ladder: the owner said small parts only.
- Paid or throwaway fleets: only an optional human rerun on one idle Box.
- Row-level copy deltas, and splitting sections other than grants and people: wait for story 11's numbers.
- Building the gateway now: only if story 15's first fallback fails.
- etcd and automatic Failover: Phase 06.
- Fansly and Fanvue: no Platform-specific shared part here.

## Further Notes
R5 wording requires actual Cell evidence and 100-Cell measurements. The current standalone relay sweep runs with cell mode off, so the report identifies it as such. R5: "Each Cell is share-nothing, so one Cell at its budget is measured. The shared parts (Front door, browser, Control cell, Placement) were each measured alone at 100-Cell size with stubs. The whole at 1,000 was never run; cross-part effects are inferred."

ASSUMPTION: ~100 Cells and 34–50 Boxes (i: 1,000 ÷ 8–15 per Cell, 2–3 Cells per Box). Overturned by ticket 66's grouping plan.
ASSUMPTION: format 2 is scale path; if ticket 29 is still unbuilt, building format 2 straight into it saves one format bump (rung 5). Overturned if that would delay the demo.
ASSUMPTION: deploy width 8 and push width 10 (g). Overturned by the drill hitting Witness or bucket bandwidth limits.
ASSUMPTION: story 15 tries the stream cap plus head-page poll before the gateway (rung 5). Overturned by poll lag past the 45 s staleness rule.

## Review
Not yet adversary-reviewed (re-plan 2026-11-26).
