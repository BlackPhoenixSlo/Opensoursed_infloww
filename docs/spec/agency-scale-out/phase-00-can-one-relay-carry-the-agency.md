# Phase 00 — Can one relay carry the agency? (go/no-go)

**Objective.** A measured Go/no-go gate says whether Cell mode gets built, and every no-cell-code input later Phases need (stall fix, agency-write list, send baseline, draft Cell scope, Feature table, stream and power-off proofs, and on Build the Cell budget C, D) exists on main with today's single Box unchanged.

Plan: `.scratch/agency-scale-out/phased-plan.md` Phase 0 + Fable amendments 3, 4, 6. Tickets 02, 03, 04, 05, 07, 08, 09, 12, 14. ADRs 0058–0064 (no new ADR).

Amended 2026-11-26: the gate no longer decides or blocks anything; Cell mode gets built (re-plan R1). See Further Notes.

## Problem Statement
The owner wants one agency of ~200 Creators and ~200 chatters on the product. Nobody knows if one Relay carries that: the only post-fix number is "held 15" from one contended run (m, ticket 02), and parallel All-inbox loads stall a Relay at ~380% CPU for 13–70 s (m). Building Cells first may spend weeks on something a fixed Box does not need. Later Phases also lean on unknowns: agency writes on the chat path, today's double sends after a crash, route ownership, 19 streams in one browser, a confirmable Hostinger stop. Today's alerting can also lose a page silently (m, ticket 03).

## Solution
Measure first. Fix the inbox stall, run a P-scaled ladder on an uncontended KVM 8 plus a 30 vs 2×15 Creator comparison; the verdict tool prints Defer, Build, Mixed or Fix-route, and on Build a sweep prints the Cell budget. In parallel, with no Cell code: list every agency write the suite makes, baseline the send kill matrix, draft Cell scope and the Feature table, prove 19 HTTP/2 streams in a real browser, drill power-off 10/10, fix the two alert bugs (outside the gate). Env unset everywhere; Compose unchanged. P0 is done only when its evidence folder holds the drill/spike results (the GATE line is optional, scale path, 2026-11-26).

## User Stories
1. As a chatter, I want the All inbox to load in ≤1 s p95 (max ≤2 s, Relay never at 100% CPU >5 s) when 100 colleagues open it at once, so that shift start never freezes the Relay (0a). [parallel-safe now]
2. As a chatter in a Split inbox group, I want `/admin/chats/recent` to return up to `limit` chats of my group, filtered in SQL before the limit, so that my list is never short or empty while older chats exist (0a). [parallel-safe now]
3. As the owner, I want the stall check to go red when the fix is reverted, so that the fix cannot silently regress (0a). [parallel-safe now]
4. As the owner, I want the verdict tool to accept a 200-Creator shape with a ladder to 1.25×P, P the larger of my number and a measured peak from a DB copy, so that the gate measures my agency, not a 50-Creator stand-in (0b). [parallel-safe now]
5. As the owner, I want every pin the gate mode changes listed, and campaign mode unchanged, so that old verdicts stay comparable (0b). [parallel-safe now]
6. As the owner, I want `--models/--big/--dpm/--grants` knobs in the one-agency seed and `calibrate.sh`, proven to change the seeded world, so that one harness drives every shape ticket 02 names (0b). [parallel-safe now]
7. As the owner, I want 3 valid runs on an uncontended KVM 8 (proved by throttling and steal, not network isolation) judged against 02's budgets with a 15-min soak, so that "one Box carries it" is measured (0c). [parallel-safe now]
8. As the owner, I want one 30-model Relay compared with two 15-model Relays on one Box at the same offered load, so that I know if splitting helps per Relay (0c). [parallel-safe now]
9. As the owner, I want ticket 02's shape sweep (8/15/50 Creators; 1/5/20 DMs/min; narrow vs broad grants) run only after a Build verdict and printing the Cell budget C and D, so that P4's planner gets measured inputs without spending Box time on a Defer (0c). [parallel-safe now] (superseded 2026-11-26, see Further Notes) Now: one real Cell at its budget, 15 models + its chatter share on one Box, small test, scale path.
10. As the owner, I want a plain-words gate line (Defer, Build, Mixed with a run count ≤5, or Fix-route), so that I can decide on my phone (gate). [parallel-safe now]
11. As the owner, I want every agency-table write the service suite makes listed by table, op and route/job label, so that P1 knows what moves to the Control cell (0d). [parallel-safe now]
12. As the owner, I want a canary that does one forbidden write, swallows the error, and is still recorded, and ticket 09's known writers required in the list, so that a swallowed IntegrityError or a crashed test cannot hide a write (0d). [parallel-safe now]
13. As the owner, I want a send-path agency write that cannot stay local flagged, so that ticket 07 is re-planned before P1 (0d gate). [parallel-safe now]
14. As the owner, I want every send kind × 3 kill points run on today's code with accept counts saved as a golden, each cell reached or marked n/a with a reason, so that P2 has a baseline (0e). [parallel-safe now]
15. As a developer, I want a static scan to write a draft `service/cell_scope.json` (routes, tables, file kinds, jobs) with hints and the probe's writers, so that P1's default-closed guard starts from a full list (0f). [parallel-safe now]
16. As a developer, I want a `--check` that reports missing or stale rows, so that the draft is current at P0's end without blocking other PRs (0f). [parallel-safe now]
17. As the owner, I want a Feature table of every feature as works / partial / off in Release 1, with its routes, jobs and send kinds, so that I sign what Release 1 switches off (0g). [parallel-safe now]
18. As the owner, I want the table to name public tracking slugs, share links, bio hosts, the ~29 cross-account reads, payroll's Control-to-Cell read, auto clock-out, cross-cell S4S and the 6 send kinds without a Send anchor, so that nothing switched off surprises me (0g). [parallel-safe now]
19. As the owner, I want a test that fails when any Cell scope route or job, or any send kind, is in no feature or in two, or when a feature claims a better state than its worst member, so that the table cannot drift from Cell scope (0g). [parallel-safe now]
20. As a chatter, I want 125 live streams plus 125 fetches on one host (was 19; resized 2026-11-26) to open over HTTP/2 in a real browser, with a dead stream greying only its own tiles within 3 s, so that ticket 08's per-Cell streams are proven before P1 (0h). [parallel-safe now]
21. As a chatter whose browser is forced to HTTP/1.1, I want a clear "unsupported connection" banner, not silent greying, so that I know why updates stopped (0h). [parallel-safe now]
22. As the owner, I want 10/10 Hostinger stops of a throwaway VM confirmed by ticket 04's rule, with account, VM id and IP checked before any stop, with timings, so that the Fence's 180 s window is measured (0i). [parallel-safe now]
23. As the owner, I want to know whether my proxy provider drops an already-open tunnel on revoke, so that ticket 04's one-time drill condition for the proxy fence is known (0i). [parallel-safe now]
24. As the owner, I want an alert marked raised only after a send succeeded, and an HTTP error counted as not delivered, so that a page is retried, never lost (0j, outside the gate). [parallel-safe now]
25. As the owner, I want every new P0 path off when its env is unset and Compose identical to main, so that today's Box is untouched. [parallel-safe now]

## Implementation Decisions
- **Owns.**
  - Relay: the `/admin/chats/recent` handler and a SQL form of the group rule in `split_inbox` (0a). New `agency_copy` module, probe mode only (0d).
  - Tests: new `test_chats_recent_stall`, `test_split_inbox_sql_parity`, `test_agency_write_probe`, `test_send_ops_kill` (+ golden), `test_cell_scope` in `service/tests`; `slop/lib/test_one_agency_knobs.py`.
  - Load: `slop/seed/profiles/one_agency`, `slop/scenarios/2026-10-24-chatter-crowd.py` (two-relay one-agency layout, soak stage, gate params), `calibrate.sh`, `calibrate_verdict` (0b). `scripts/dm_peak_rates.py --chatter-peak` (P from a DB copy).
  - Cell scope: new `service/cell_scope.json`, new `service/cell_features.json`, new scanner `scripts/cell_scope_scan.py`, rendered `docs/cell-mode/release-1-features.md` (0f, 0g).
  - Fleet: new `deploy/fleet/power_drill.py` and `deploy/fleet/proxy_revoke_check.py` (0i).
  - Alerts: `scripts/vps-watchdog.sh`, `scripts/notify.sh` (0j).
  - Spike: `.scratch/agency-scale-out/spikes/stream/` (throwaway, 0h; `git add -f`, `.scratch/` is in info/exclude but tracked by precedent (m `git ls-files .scratch`)).
  - Evidence: `.scratch/agency-scale-out/gate/` (GATE line, cal dir list, drill and spike JSON, `cell_budget.json` on Build).
- **0a stall fix.** First profile the stall with the existing perf log and record the cause in the PR (cause unknown today (i)). Fix it, and move the split-inbox filter into the SQL before `.limit(limit)` (plan wording, rung 2; today the limit runs first and the Python filter after, m `service/server.py:2312-2357`). `split_inbox` gains one function that builds the predicate from the same cfg `group_of` reads (moved fans from `assignments`, else digit id `% group_count + 1`, else group 1; m `split_inbox.py:62-69`); `filter_for` stays as a post-check. `test_split_inbox_sql_parity` asserts SQL == `group_of` over a table of ids: moved in/out, non-digit, 2^53+1, int64 max. Response shape unchanged. Ids stay strings via `js_safe_id`.
  ASSUMPTION: OF fan ids fit SQLite's int64 (i). Overturned by: a stored fan id above 2^63; then that id's group is decided by the Python post-check only.
- **0b gate mode.** (superseded 2026-11-26, see Further Notes) Optional after the demo, small scale only, no 1.25×P ladder. `calibrate_verdict --gate --peak P`. P = max(owner's number, `dm_peak_rates.py --chatter-peak` on an owner-supplied DB copy: most distinct `sent_by_employee_id` in any 15-min window over 4 weeks); default 200 until either exists. N = ceil(1.25×P) (250 at P=200). `calibrate.sh --chatters=N` already ladders N/4…N. Pins changed in gate mode only: `LADDER` → N/4, N/2, 3N/4, N; `TOP`/`users` → N; `GATE_UP_TO` 100 → N; `models` 50 → `--models` (200); `fleet_shards` 1 → 1 or 2 (`--layout one-agency-split`); `RUN_KEYS` gains the 4 knobs plus `soak_s`. Kept: medium scale, seed 1, no fault, `--no-ui`, `owner_watching` (one owner tab per Relay), driver-lag, nodata, ISOLATION and off-host checks, invalid-run rules. Dropped in gate mode only: AE liveness and contention (campaign-only: they prove a contended box). Campaign mode keeps every pin byte-identical. Holds 120 s per step, then a 15-min soak stage at N in the scenario (new stage, gate param only).
  ASSUMPTION: N/4 steps, not 8/15/22/30 extended (rung 3: calibrate's own ladder). Overturned by: a bend between steps the owner wants located.
  ASSUMPTION: distinct senders per 15 min stand in for "online at once" (rung 5); it undercounts readers, the owner's number covers that by max. Overturned by: a session/presence log with history.
- **0c runs.** (superseded 2026-11-26, see Further Notes) Optional after the demo. Uncontended KVM 8: `--obs` required; every hold and the soak at ≤1% throttled periods and host steal p95 <10% (ticket 02 item 4 gate shape, `calibrate_verdict.py:99-119`). ISOLATION.json proves network isolation only. Owner's yes + written waiver of slop's small/15-min cap. "Two 15-model cells" = scenario layout `one-agency-split`: two one-agency Relays of 15 Creators on one Box, same seed, same DMs/min per Creator, same image SHA, chatters shared by Creator. Knobs from `dm_peak_rates.py` on the DB copy when supplied (skew, big Creators), else defaults. Each run (gate, split, sweep) is one cal dir. `frame→chatter` = the scenario's `frame_to_sse_p95_ms` (house metric); it excludes the OF socket read and browser paint (`--no-ui`).
  ASSUMPTION: shards stand in for Cells (rung 5). Overturned by: Front door/Agency copy overhead, measured in P3.
- **Gate (verdict output; bars (g), tickets 02/12).** (superseded 2026-11-26, see Further Notes) Blocks nothing; optional measurement. Only valid runs count; an invalid run (crash, nodata, driver lag, throttled, steal) prints `INVALID <why>`, is neither hold nor miss, and counts toward the 5-run cap. Budgets: route p95 ≤500 ms over ≥20 calls, inbox/send/login p95 ≤750 ms, CPU ≤80%, 0 pool spills, pool wait p95 ≤100 ms, frame→chatter ≤1 s, 0 lost/duplicated/leaked, soak passed.
  - Defer: 3/3 valid gate runs hold N → park P1–P6, re-gate at 1.5×P.
  - Build: 3/3 valid gate runs miss **and** in the comparison each 15-model Relay holds at least one ladder step more chatters than the 30-model Relay.
  - Fix-route: 3/3 miss and the split does not clear that bar.
  - Mixed: anything else → rerun, ≤5 runs total, then the human.
  - Plus: 0d send-path agency write → `REPLAN 07`; 0h fail → `REPLAN 08`. The verdict reads `probe/send_path.json` and the spike JSON from the evidence folder; either missing → `GATE incomplete`.
  ASSUMPTION: Build needs 3/3 misses, symmetric with Defer (rung 4: fewer weeks spent on a fluke). Overturned by: the owner accepting a 2/3 miss.
  ASSUMPTION: "more per Relay" = ≥1 ladder step margin (g). Overturned by: run-to-run noise larger than a step.
- **0c sweep (Build only).** (superseded 2026-11-26, see Further Notes) Replaced by 26 = one real Cell at its budget. Ticket 02 item 6 shapes, 3 valid repeats each. Writes `gate/cell_budget.json {C, D, shape, cal_dirs}`: C = held chatters, D = held inbound DMs/min at the 15-model shape, both raw (P4 plans at 70%).
- **0d probe.** `CELL_PROBE=block|record` makes the test harness install, after fixtures, BEFORE INSERT/UPDATE/DELETE triggers on every agency table of ticket 07 item 1 (copied and control-only). Each calls a registered SQLite function that records (table, op, label) in Python memory, outside the transaction; `block` then aborts (ticket 09 item 2, rung 2), `record` lets the write land. The run of record is `block`; one extra `record` pass catches writers hidden behind an earlier abort; the inventory is the union, with the diff listed. Labels come from `write_telemetry` (`http:METHOD /path`, `task:…`); route/job labels are passed into thread-pool work explicitly. Pumps are skipped in test mode, so each registered job's tick is called once directly. Each test process writes `$CELL_PROBE_OUT/<script>.jsonl` at exit, empty when it saw nothing; a script with no file is reported crashed and fails the fold. Hits labelled `thread` are listed separately with their stack, never dropped. Required hits (test fails if absent): `auth._touch_last_seen`, the chatter last_seen update, lazy employee creation, an audit row, a session-dead notification (ticket 09 item 2). Hits from send routes/jobs go to `probe/send_path.json`. Env unset: no triggers; the installer drops leftovers.
- **0e baseline.** `test_send_ops_kill` uses the `_Killed` pattern from `test_send_once` over every send kind in ticket 05 item 1 × kill after the local pre-send write, after upstream accepted but before the row/marker update, and after the update; then restart, tick, retry endpoint, and resend of the same request. A kind with no local pre-send write (the composer today, i) marks that cut `n/a: <why>`. A recording OF stub counts accepts per intended send. The golden `test_send_ops_kill.golden.json` holds, per (kind, cut), `reached` or `n/a`, and the accept count; the test fails if any cell is neither. P2 replaces the golden with ≤1 per op (P2's op id comes from `X-Op-Id`, so a new user action is a new op, not a duplicate).
- **0f Cell scope.** Format is ticket 09 item 1 (4 maps, exact keys, `why` on every row, route `scope`/`key`/`auth`/`partial`, table `scope` incl. model_via/pair/mixed, file rows, job `iterates`). The scanner imports `server` under the service test harness (temp DB), scans every feature-flag profile, reads `Base.metadata` + the real SQLite schema, writes rows with `hint` fields, and folds 0d's writers into table rows. `--check` exits non-zero on drift. Not wired into `run-tests.sh` or CI in P0.
  ASSUMPTION: no enforcement in P0 (rung 4: a Defer would leave every route PR paying for an unused file). Overturned by: the gate saying Build; P1 wires both halves (ticket 09 item 4).
- **0g Feature table (ticket 14's open shape, decided here).** A separate `service/cell_features.json`, not a column on 900 Cell scope rows (rung 5: the owner reads ~50 features, not ~900 rows). Shape:
  ```json
  {"schema":1,"scope_sha256":"…","signed":null,
   "features":{"<name>":{"state":"works|partial|off","why":"…","routes":["GET /x"],"jobs":[],"send_kinds":[]}}}
  ```
  Every Cell scope route and job, and every send kind, sits in exactly one feature (ticket 14: every route, job and send kind). Member state defaults from Cell scope: `closed` → off; `fanin` → partial; send kind without a Send anchor → off; model/agency/public → works. A feature's state is never better than its worst member. Draft states: tracking slugs, share links, bio hosts → off (need agency-unique ids + a Front door lookup, ticket 09); the ~29 cross-account reads → off except the roster and All inbox (partial: their routes are fanin and a feature is never better than its worst member; amended 2026-11-26, ticket 21); payroll finalisation → partial (blocked until every account is fresh); auto clock-out → off; cross-cell S4S → off; the 6 anchorless kinds (autoreply, welcome_chatter, generic followup, vault items, nudge, purchase_followup) → off; feed posts/stories → partial (no op id, ticket 05 fog). `signed` = `{by, at, sha256}` filled from the owner's written yes; P4 preflight refuses unsigned or a hash mismatch. The scanner renders `docs/cell-mode/release-1-features.md`.
  ASSUMPTION: the draft states above (rung 4: off is cheaper to turn on later). Overturned by: the owner marking any of them needed at launch.
- **0h spike.** 125 stub SSE endpoints (stdlib Python, was 19; resized 2026-11-26, ~125 Cells at 1,000 models, i) sending numbered events, behind a local Caddy with `tls internal`, HTTP/2, one static page opening 125 EventSources plus 125 fetches at once, driven by Playwright chromium at nice 10. Checks: `nextHopProtocol == "h2"`; all 125 deliver an event ≤1 s; the 125 fetches answer p95 ≤1 s while streams run (g); one blackholed endpoint greys only its tiles ≤3 s while the other 124 keep counting; `--disable-http2` shows the banner. Writes `gate/stream.json` plus trigger and settled screenshots. Not product code.
- **0i drills.** `power_drill.py --vm-id --ip --times 10`: before each stop, read the VM by id from the provider account and require id, account and IPv4 to match the given ones, else `unconfirmed`, no stop sent; stop by that id (never by IP), poll the action to `success`, two reads ≥5 s apart both `stopped` with matching IPv4, all ≤180 s, then start and wait running; prints per-try timings to `gate/power.json`. `proxy_revoke_check.py` holds a CONNECT tunnel through given credentials to an echo port on the throwaway box, waits for the operator to type `revoked`, then reports whether the open tunnel died and a new connect is refused (`gate/proxy.json`). That is only ticket 04 item 3's one-time drill; the proxy fence stays unavailable until per-Cell credentials and all-exit checks exist (P2). Neither touches OnlyFans.
- **0j alerts.** `transition` writes `bad` only after `notify.sh` exits 0, so a failed send retries next run; `notify.sh` uses `curl -f` on every channel. No pin edit: `prod-install-watchdog.sh` hashes the local scripts at run time (m `scripts/prod-install-watchdog.sh:28-29`). Prod install is `scripts/prod-install-watchdog.sh apply`, run by the human.
- **Schema.** None: no migration. 0d triggers exist only under `CELL_PROBE` in test DBs.
- **Contracts.** `cell_scope.json` and `cell_features.json` (above). Verdict line: `GATE defer|build|mixed|fix-route|incomplete peak=P n=N held=… runs=k/5` plus `REPLAN 07|08` and `INVALID` lines. Probe JSONL: `{"table","op","label","test","mode"}`. `cell_budget.json` (above).

## Testing Decisions
Five existing seams, one per tool family; no new runner.
- **Service suite** (`run_tests_parallel.py service/tests`, plain scripts): `test_chats_recent_stall` (filter-before-limit rows: newer out-of-group rows filling `limit` plus older in-group rows, explicit moves, inherited default, unbound chatter, owner; then the relay booted as a subprocess on a 200-Creator seeded temp DB, house precedent `test_link_share`/`test_bio_server`, 100 concurrent All loads, best of two herds ≤1.5 relay CPU seconds (fixed ≤0.6 s, mutant ≥2.3 s) measured with `ps -o time=`, with p95 and max wall time reported for diagnosis; `STALL_MUTANT=1` swaps in the pre-fix shape and must fail the same CPU gate with `STALL_MUTANT_RED`), `test_split_inbox_sql_parity`, `test_agency_write_probe` (canary recorded; required writers present; env unset installs nothing), `test_send_ops_kill` (golden match, every cell reached or n/a), `test_cell_scope` (scanner `--check` green; exactly-one-feature coverage; feature ≤ worst member). Prior art: `test_send_once`, `test_audience_coverage`, `test_route_order` golden, `test_split_inbox_api`.
- **slop/lib pytest** (`run_tests_parallel.py --pytest slop/lib`): `test_one_agency_knobs` seeds the profile with each knob (no slop run) and asserts the world's Creators, big count, DMs/min and grants; and that `one-agency-split` builds 2 Relays with one owner tab each.
- **Fleet pytest** (`deploy/fleet/tests`): gate mode, its pins, invalid-run counting, 3/3 symmetric verdict table, and campaign-mode invariance in `test_calibrate`; `test_power_drill` against `api_stubs` (timeout, error, stuck `stopping`, wrong VM id, account or IP mismatch each unconfirmed; a pre-check mismatch sends 0 stop calls); `test_proxy_revoke_check` against a stdlib stub proxy.
- **Scripts pytest** (`scripts/tests/test_alerting.py`, added to `run-tests.sh`): a curl stub on PATH that mimics curl: HTTP 500 body with exit 0 without `-f`, exit 22 with `-f` → `notify.sh` exits non-zero and watchdog state stays `ok`; then 200 → `bad` written. Removing `-f` turns it red.
- **Spike harness** (0h): its own run script; the real browser is the test.
Real-path proof: the drills; the stall test on one Cell (20 chatters at once). KVM 8 runs optional, scale path (2026-11-26).

## Acceptance
```sh
set -e
cd "$(git rev-parse --show-toplevel)"
P=venv/bin/python
$P scripts/run_tests_parallel.py service/tests test_chats_recent_stall test_split_inbox_sql_parity -j 8
STALL_MUTANT=1 $P scripts/run_tests_parallel.py service/tests test_chats_recent_stall -j 8 2>&1 | grep -q STALL_MUTANT_RED
$P scripts/run_tests_parallel.py service/tests test_agency_write_probe -j 8
$P scripts/run_tests_parallel.py service/tests test_send_ops_kill -j 8
OUT=.scratch/agency-scale-out/probe; rm -rf "$OUT"; mkdir -p "$OUT"
for M in block record; do CELL_PROBE=$M CELL_PROBE_OUT="$OUT/$M" nice -n 10 $P scripts/run_tests_parallel.py service/tests -j 8 || true; done
$P scripts/cell_scope_scan.py --fold-probe "$OUT/block" "$OUT/record" --check
$P scripts/cell_scope_scan.py --features --check
CELL_SCOPE_CHECK=1 $P scripts/run_tests_parallel.py service/tests test_cell_scope -j 8
$P scripts/run_tests_parallel.py --pytest slop/lib -j 8
$P -m pytest -q deploy/fleet/tests/test_calibrate.py deploy/fleet/tests/test_power_drill.py deploy/fleet/tests/test_proxy_revoke_check.py
$P -m pytest -q scripts/tests/test_alerting.py
git diff --exit-code main -- docker-compose.yml
scripts/run-tests.sh
# manual: brew install caddy (new local dependency, once)
nice -n 10 bash .scratch/agency-scale-out/spikes/stream/run.sh
# optional, scale path (2026-11-26): owner gives P and/or a DB copy: $P scripts/dm_peak_rates.py <copy> --chatter-peak; N=ceil(1.25*P)
# optional, scale path: owner gives a written yes + slop-cap waiver and an uncontended KVM 8
# optional, scale path: 3..5x  ssh root@<kvm8> bash -s -- <sha> --chatters=$N --one-agency --models=200 --soak=900 < deploy/fleet/calibrate.sh
# optional, scale path: 1x --models=30 --one-agency and 1x --models=15 --one-agency-split, same box, same N
# manual: stall check on one Cell-sized Relay (15 models): 20 chatters load All at once (R5)
# optional, scale path: $P deploy/fleet/calibrate_verdict.py --gate --peak $P_PEAK --obs <obs> --evidence .scratch/agency-scale-out/gate <cal dirs> > .scratch/agency-scale-out/gate/GATE.txt
# scale path: ticket 26 = one real Cell at its budget (phase-07)
# manual: $P deploy/fleet/power_drill.py --vm-id <throwaway VM, scale path (R9)> --ip <ip> --times 10   -> 10/10 confirmed
# manual: owner checks Webshare/IPRoyal sub-users; $P deploy/fleet/proxy_revoke_check.py on the throwaway box
# manual: owner runs scripts/prod-install-watchdog.sh apply after 0j merges
# done gate (after the manual steps):
# optional, scale path: grep -Eq '^GATE (defer|build|mixed|fix-route) ' .scratch/agency-scale-out/gate/GATE.txt
test -s .scratch/agency-scale-out/gate/stream.json && test -s .scratch/agency-scale-out/gate/power.json && test -s .scratch/agency-scale-out/gate/proxy.json
# optional, scale path: ! grep -q '^GATE build' .scratch/agency-scale-out/gate/GATE.txt || test -s .scratch/agency-scale-out/gate/cell_budget.json
```

## Depends on
- Code: MP 1a–1d merged (m) is the only prerequisite; 0a lands after MP 1d (merged).
- Inside P0: 0c needs 0a and 0b merged; 0f's table writers need 0d; 0g needs 0f; the GATE line needs 0c, 0d's `send_path.json` and 0h's `stream.json` (GATE line optional, 2026-11-26).
- Human (2026-11-26, R7, R9): signing the Feature table; the power drill on a throwaway VM and the proxy provider check move to the scale path (one Box, no power fence or proxy revoke on the demo). P, the slop-cap waiver and the KVM 8 only for the optional scale-path runs.

## Out of Scope
- Cell-mode write-block triggers with the gate row and the Agency copy apply — P1 (ticket 07).
- Enforcing Cell scope (route guard, CI job, `run-tests.sh` wiring) — P1 (ticket 09).
- `send_ops.dispatch`, Send claims, the real-path SIGKILL drill (05 item 7b) — P2.
- Typed Fence result in fleet.py, epoch refusal, egress gate, per-Cell proxy credentials — P2 (ticket 04).
- SSE replay after a dropped stream — already proven by `test_sse_replay`; per-Cell replay is P1.
- Witness probe, heartbeat and repeating pages — P3 (ticket 03); only the two alert bugs ship now.
- The P4 preflight that checks the signed table — P4.
- 3-Cells-per-Box run with the Front door — needs Cells (P3).
- Measuring P from a live Box — never prod; owner supplies a copy or a number.
- Ticket 02's offline sizing/grouping script — only useful after a Build verdict, when Cells are placed (superseded 2026-11-26: Phase 4 ticket 66 builds it, demo path).
  ASSUMPTION: it lands with P1's `fleet.toml` accounts (rung 5). Overturned by: the owner wanting the grouping plan before the gate.

## Further Notes
- ASSUMPTION: P = 200 until the owner gives one or a DB copy (ticket 12). Overturned by: a measured P; reruns 0c at the new N. (superseded 2026-11-26: target is 1,000 models / 1,000 chatters; no P needed)
- ASSUMPTION: the subprocess 100-load test (rung 3) separates fixed from reverted code on a laptop. Overturned by: the mutant passing; then only the Box run of the same test guards it.
- ASSUMPTION: the spike lives in `.scratch` (rung 5: throwaway, P1 builds the real test). Overturned by: P1 wanting to reuse it as is.
- ASSUMPTION: drill scripts live beside fleet.py, not in it (rung 4). Overturned by: P2 lifting the confirm rule in.

### Re-plan 2026-11-26
Binding: `.scratch/agency-scale-out/replan-2026-11-26.md` (R1, R4, R5, R7). Plan top: `phased-plan.md` "Re-plan 2026-11-26".
- **GATE blocks nothing.** Ticket 25 leaves every Blocked by. 16, 17, 25 are optional measurement after the demo. The ladder (0b, 0c) is optional, small scale only, no 1.25×P.
- **Paths.**
  - demo: 15 (stories 1–3), 18 (11–13), 19 (14), 20 (15–16), 21 (17–19), 22 (20–21, resized), 23 (22–23), 24 (24); story 25 everywhere.
  - scale: 16, 17 (4–6, 10), 25 (7, 8, 10), 26 (9, resized).
  - ASSUMPTION: 19 is demo (not named in R4, but demo ticket 38 waits on it). Overturned by: 38 dropping that edge.
- **22 resized:** 125 stub streams + 125 fetches in one real browser through local Caddy (0h above). Its pass keeps ADR-0061's no-gateway; a fail brings in gateway fan-in (Phase 7).
- **26 resized:** one real Cell at its budget, 15 models + its chatter share on one Box. Small test, not a blocker. Spec: `phase-07-hold-1000.md`.
- **Stall (15):** a one-Cell check, 20 chatters loading All at once on a 15-model Relay, replaces the KVM 8 stall run.
  ASSUMPTION: the laptop 100-load subprocess test and its mutant stay as the guard; R5's 20-chatter run is the real-path check (rung 4, keeps the stronger test). Overturned by: the 100-load test being too slow for CI.
- **23 power drill:** the tools stay demo (37 and 44 need them); the live 10/10 run on a throwaway VM is scale (R9: the demo has no power fence).
  ASSUMPTION: the demo needs no live power drill since AE stays on one Box (owner R9). Overturned by: a demo step that power-stops a VM.
- **Acceptance:** the done gate is `stream.json`, `power.json`, `proxy.json`; the GATE and `cell_budget.json` lines are optional (marked above).
- **Human (R7, R9):** signing the Feature table (power drill and proxy check are scale); `prod-install-watchdog.sh apply` is 24's last step. Nothing else waits on the human.
- Report wording for any size claim: R5's honest line (phased-plan top).

## Review
codex (gpt, reasoning high), 2026-11-26, partly blind (workspace sparse; `.scratch` reachable via git objects). Blind call B, draft call D.
- B1 alternatives (keep one relay + targeted fix; same-box 2-relay compare; decisions independent) — **reject**: already the plan's shape (Defer/Fix-route, 2×15 same box, REPLAN lines independent); no change.
- B2 workload definition missing (how P is measured; skew, grants from data) — **accept**: P = max(owner, `dm_peak_rates.py --chatter-peak` on a copy); knobs from the copy when given (0b, 0c).
- B3 pass conditions and fair comparison undefined — **accept**: "more per Relay" defined (≥1 step, same seed/DMs/SHA); repeat and invalid-run rule fixed before running (Gate).
- B4 old verdict carries more pins (GATE_UP_TO=100, 120 s holds, validity, AE liveness) — **accept**: GATE_UP_TO → N listed; validity kept; AE liveness/contention dropped in gate mode only (0b).
- B5 0d–0g need executable coverage (known writers, send kinds × boundaries, feature coverage) — **accept**: required writers (0d), n/a cells (0e), exactly-one-feature test (0g).
- B6 test seam: real relay + fake platform at the wire, browser paint — **partial**: keep the scenario's frame→SSE metric (house, ticket 02 reuses it) and name what it excludes (0c); browser paint under load is not in the plan.
- B7 0a seam: authenticated route, moves/inherit/unbound/owner, mutant once — **accept** (Testing, service suite).
- B8 0h numbered events + replay + screenshots; 0i egress evidence — **partial**: numbered events and screenshots added; replay is `test_sse_replay`/P1; egress gate is P2.
- B9 falsifiers (hot Creator over C/D, placement over box budget) — **reject**: that is P4's `cell_plan` "no fit", not P0.
- D1 Acceptance green without a measured verdict, no evidence, no C/D for P4 — **accept**: evidence folder + done-gate lines; Build sweep writes `cell_budget.json` (Objective, story 9, Acceptance).
- D2 one miss + two passes could say Build; invalid runs undefined — **accept**: 3/3 symmetric; INVALID counts to the cap, not as hold/miss.
- D3 P hard-coded, pool wait missing, ISOLATION ≠ uncontended, no soak in the scenario — **accept**: N from P, pool wait p95 ≤100 ms added, `--obs` throttling + steal required, scenario gains a soak stage (m `chatter-crowd.py:668-685` stops after holds).
- D4 two-Relay comparison unrunnable (layout fixed at 1 relay), knobs untested on the seeded world — **accept**: `one-agency-split` layout (m `chatter-crowd.py:20-24,596-601`; `calibrate.sh:71-75`), scenario in Owns, `test_one_agency_knobs`.
- D5 scan cap can return short; plan says filter before the SQL limit; `scanned` unused; CPU condition missing; mutant accepts any exit — **accept**: SQL predicate + parity test, no `scanned`, 1 Hz CPU check in the subprocess test, mutant must print `STALL_MUTANT_RED`.
- D6 `|| true` hides crashes, abort hides later writers, `thread` dropped, canary-only, copied-tables-only — **accept**: per-script JSONL or crashed; block + record passes unioned; `thread` listed; required writers; triggers on copied and control-only tables.
- D7 cuts assume a pre-send write; golden doesn't assert each cell reached; same-content resend is a new op in P2 — **accept**: `reached`/`n/a` per cell; resend of the same request, op = `X-Op-Id`.
- D8 Feature table checks less than "every route, job, send kind"; feed posts contradict 05 — **partial**: exactly-one-feature + worst-member rule accepted; feed posts stay partial: 05 puts them outside op-ID, which is why they are partial, not a contradiction.
- D9 power drill must check account/VM id/IP before stopping; proxy test missing from Acceptance; one tunnel ≠ fence available — **accept**: pre-check with 0 stop calls on mismatch; `test_proxy_revoke_check` in Acceptance; story 23 reworded to 04's one-time drill.
- D10 curl stub can hide a missing `-f`; md5 pins have no target; `apply` missing — **accept** (0j, Testing, Acceptance).
- D11 "None" false; `.scratch` spike excluded from staging — **accept** for Depends on (internal order + human inputs); **partial** for the spike: tracked by `git add -f` precedent, noted in Owns.

### Plan review (six hats), 2026-11-26
- Red / Green doing-less / Blue (2): ticket only Phase 0 now — **partial**: every Phase gets tickets (the run tickets the whole plan), but every P1–P6 ticket is Blocked-by this Phase's `GATE build` verdict, so nothing past 0a–0j can be taken before the gate; a Defer leaves them parked, not wasted. (superseded 2026-11-26, see Further Notes)
- White: P and the gate verdict unknown — **accept** as stated: P is a human input (Depends on) and the verdict is this Phase's output; nothing changes.
- Rests on D3: none.
