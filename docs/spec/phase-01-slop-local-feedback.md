# Phase 01 — Local feedback without duplicate work

**Objective.** A developer's local slop loop reuses a Break baseline only at an equal Run identity, every run
records its four Run phases on the real path, unnecessary readiness sleep is cut only where measured, and exact
concurrent opt-in requests share one execution — with the Machine gate, coverage and timing thresholds unchanged.

## Problem Statement
Slop feedback is slow (Nov 9 nightly: 5h03m, 1129 s gate waits = 6.2 % of it, seven flaky results; plan). A developer
or agent cannot tell where a run's time goes: only a successful `ctx.build` is timed (`slop/lib/cli.py:117-133`), the
stack start is printed but not stored (`cli.py:555`), teardown is untimed, and nightly does not total any of it — and
its FAIL re-run merge keeps only the first attempt's gate wait (`slop/lib/nightly.py:115-121`). `--break
--baseline=<folder>` saves a baseline run but is unsafe: `_load_baseline` compares knobs only (`cli.py:655-669`,
`_same_knobs` with `git_sha`/`git_dirty` in `RUN_FACTS`, `cli.py:33-35`), so a green folder from older code, a dirty
tree that has since changed, or another environment (e.g. `PROXY_FLAP_BAD_PCT=0` exported in one shell — the stack
hands the caller's whole env to the relay, `slop/lib/stack.py:151`) is silently reused. Two sessions asking for the
same run at the same time each take a gate slot and a stack; from one checkout a second UI run is refused outright by
`app/.next/slop.lock` (`stack.py:55-71`, INFRA). `--changed` and the gate already exist but the fast loop is not
written down in one place.

## Solution
- One "Fast local feedback" section in `slop/README.md`: the existing `--changed --dry` → `--changed` → per-pick
  `--break --baseline=<its green folder>` loop and the gate's observed limits (T1); `--share` is added to it by T4,
  which ships the flag. No new selection.
- Every run records its Run identity (source incl. app dependency and app env-file inputs, environment) as run facts;
  `--baseline` is refused (INCONCLUSIVE, exit 3, saying which part differs, before any fault run starts) unless
  identity is equal and both the baseline's and the fault run's start and end source identities match. p95-vs-last-
  green keeps comparing across commits, as today.
- Every run records `run_phases` (startup, seeding, execution, teardown, plus the gate wait already recorded), on
  success and on failure; nightly totals them over every attempt, re-runs included.
- Readiness polling is tightened only if those numbers show the 1 s poll sleep is real waste; measured before/after
  into a checked artifact.
- `slop/run … --share` (opt-in): an exact concurrent request in the same checkout and directory with an equal Run
  identity waits, outside the gate, for the live run and gets its output, run folder and exit code. Without `--share`
  every run is a Fresh run; nightly never shares.

## User Stories
1. As a developer, I want one README section listing the fast loop (`slop/run --changed --dry`, `slop/run --changed`,
   `--break --baseline=<green folder>`), so that I use what exists instead of new selection machinery.
2. As a developer, I want that section to state that `slop/run all`/nightly stay the complete sweep and `--changed` is
   for development, so that coverage honesty is unchanged.
3. As a developer, I want the README to state the gate's limits as observed (6 slots, load < 12, threads < 12000,
   20 s stagger, medium/120+ exclusive, nightly 1129 s of gate waits) and that this Phase changes none of them, so
   that nobody "speeds up" by raising slots.
4. As a developer, I want every run folder's `metrics.json` `params` to carry `source_id` (the source at start),
   `source_id_end` (after teardown), `env_id` and `env_names`, so that a run's identity is checkable later.
5. As a developer, I want `source_id` to cover HEAD plus the tracked diff plus untracked non-ignored files, plus the
   ignored inputs a stack loads (`app/.env*` contents, `app/node_modules/.slop-lock-sha`, the venv's resolved
   python), with `app/tsconfig.json`/`app/next-env.d.ts` read as their originals, so that a dirty-tree baseline is
   reusable from the same dirty tree and refused once anything changed.
6. As a developer, I want `env_id` to hash every caller env var except shell noise, the gate's own bookkeeping and
   admission-only waits — caller guard policy (`SLOP_GATE`, `SLOP_MAX_THREADS_PROC*`, `SLOP_MAX_THREADS_TOTAL`,
   `SLOP_MAX_SOCKETS_RUN*`, `SLOP_GATE_EXCLUSIVE`) and runtime choice (`PATH`, `PLAYWRIGHT_NODEJS_PATH`, `SLOP_PW_NODE`)
   included — storing only the
   hash and the included names (never values), so that a setting exported in my shell blocks reuse without leaking
   secrets.
7. As a developer, I want `--break --baseline=<folder>` to be INCONCLUSIVE (exit 3), with no fault run started, and a
   one-line reason naming `source`, the added/removed env var names, or `env value changed (values are not stored)`,
   when identity differs, so that stale evidence is never reused silently.
8. As a developer, I want a baseline whose own `source_id != source_id_end`, or a fault run whose start or end source
   differs from the baseline's, made INCONCLUSIVE, so that a run that raced an edit cannot be a Break verdict.
9. As a developer, I want a baseline folder recorded before this Phase (no `source_id`) refused with "re-run without
   --baseline", so that legacy folders are not trusted by default.
10. As a developer, I want `--break` without `--baseline` to be INCONCLUSIVE when its in-process baseline and fault run
    have different start or end `source_id`, so that an edit between the two runs is caught.
11. As a developer, I want `p95 within … of the last green run` and `--changed` estimates to keep matching on knobs and
    world only (identity facts in `RUN_FACTS`), so that p95 regression checks still compare across commits.
12. As a developer, I want the README's `--baseline` commands to say "same Run identity — record and reuse from the
    same kind of shell (a conda-activated shell differs by `PATH`)", and that `raced` means re-run with nobody editing
    the checkout, so that documented commands match behaviour.
13. As a developer, I want `metrics.json` to carry `run_phases` = startup_s, seeding_s, execution_s, teardown_s and
    `seed_calls`/`seed_failed`, summing to the run's `seconds` metric, so that I see where a run's time goes.
14. As a developer, I want a stack that fails to start to record startup_s up to the failure and its partial-start
    cleanup as teardown_s (seeding/execution null), so that failure runs leave timing evidence charged to the right
    phase.
15. As a developer, I want a seed profile that raises to still add its seconds to seeding_s and count `seed_failed`,
    so that seeding cost includes failures.
16. As a developer, I want a timed-out or SIGTERMed run to record the phases it reached and teardown_s, so that
    cancellation is measured too.
17. As a developer, I want each readiness wait's seconds and poll count in `run_phases.waits`, so that the 1 s poll
    sleep's real cost can be judged.
18. As a developer, I want summary.txt to print one `run phases:` line, so that the split is visible without opening
    JSON.
19. As the owner, I want nightly's summary to total gate wait, startup, seeding, execution and teardown over every
    attempt (a FAIL's re-run added, not dropped) with seeding's share of measured phase seconds (untimed attempts and gate wait reported separately), so that the "seed cache
    only at >= 15 %" rule can be checked each night.
20. As a developer, I want readiness to poll faster with a bounded backoff only if measured waits show ≥ 1 sleep per
    wait is typical, and kept only if median startup_s over 5 runs drops (no-UI and UI scenario), recorded in a
    checked `t3-startup.json`, so that only demonstrably unnecessary waits go.
21. As a developer, I want the teardown grace (SIGTERM, 10 s, uvicorn 5 s graceful) and every scenario's deliberate
    observation window unchanged, so that failure detection is not traded for speed.
22. As an agent, I want `slop/run <args> --share` to wait outside the Machine gate when an identical request (same args,
    checkout, working directory, source and env identity) is live, so that followers take no slot and no stack.
23. As an agent following a Shared run, I want the leader's output (including `slop: folder …`) and its exit code
    verbatim (0, 1, 3, gate 75 or a signal exit), so that my report is exactly what I would have got.
24. As an agent, I want a Shared run never to be served from an earlier finished run, so that results are fresh: a
    follower joins only a generation that has not published a result.
25. As an agent, I want my own cancellation while following to stop only me (exit 3) and leave the leader running,
    so that one session cannot kill another's run.
26. As an agent following a leader that was cancelled, timed out or died without a result, I want INFRA exit 3 naming
    that, so that cancellation semantics carry over and nothing is guessed.
27. As an agent following a leader whose source changed mid-run (its result's `source_id_end` differs from the key's
    `source_id`), I want the leader's log and INFRA exit 3 naming that (no re-key, no re-election, no automatic
    re-run), so that I never get a verdict for code other than what the recorded identity says.
28. As a developer, I want any run without `--share` (explicit repeats, flake hunts) to execute itself, so that repeat
    runs stay Fresh runs.
29. As the owner, I want nightly's first runs and re-runs of a FAIL never to pass `--share`, and no env var to turn
    sharing on, so that nightly stays fresh.
30. As a developer, I want `--share` refused with `--map` and with `nightly`, so that map writes and the sweep keep
    their own semantics.
31. As a developer, I want follower waits bounded (then INFRA exit 3), so that a hung leader cannot stall a caller
    forever.
32. As a developer, I want `--share` documented in the README's fast-loop section by the ticket that ships it, so that
    the README never advertises a missing flag.

## Implementation Decisions
- **Owns.** `slop/lib/cli.py` (call sites only), `slop/lib/stack.py` (readiness wait timing, partial-start teardown
  timing; conditional poll change), `slop/lib/nightly.py` (row phases, `merge_rerun` sums, digest totals), new
  stdlib-only `slop/lib/identity.py` (Run identity + baseline identity check), new stdlib-only `slop/lib/phases.py`
  (Run phase bookkeeping), new stdlib-only `slop/lib/share.py` (Shared run), `slop/run` (route `--share` before the
  gate), `slop/README.md` (one section + `--baseline` wording; `--share` lines in T4), the "Run identity" line in
  `CONTEXT.md`, tests in `slop/lib/test_cli.py`, `slop/lib/test_nightly.py`, new `slop/lib/test_identity.py`,
  `slop/lib/test_phases.py`, `slop/lib/test_share.py`.
- **cli.py size.** 978 lines today (`wc -l`). Identity comparison lives in `identity.py`, phase bookkeeping in
  `phases.py`; cli.py only calls them. `wc -l slop/lib/cli.py` stays < 1000 (Acceptance). Each ticket's implementer
  checks `wc -l` before editing and, if its cli.py change would leave the file at ≥ 990 lines, first moves
  `_load_baseline`/`break_one` verbatim into `slop/lib/breakit.py` (re-exported from cli for existing tests) as its own
  commit — up front, not mid-ticket. The reviewer re-checks `wc -l`.
- **Interfaces.**
  - `identity.source_id(root) -> str`: sha256 of HEAD sha + `git diff HEAD --binary` + `(path, blob)` of
    `git ls-files -o --exclude-standard` + the ignored stack inputs: `app/.env*` contents (Next loads them;
    `app/.gitignore:15-16` ignores them; service `.env` is not an input — `relay_guarded.py:108-123` no-ops dotenv),
    `app/node_modules/.slop-lock-sha` (`nightly.py:45`) and `realpath(venv/bin/python)`. `app/tsconfig.json` and
    `app/next-env.d.ts` are hashed from `app/.next/slop.state.json` `originals` when a live app-lock holder has rewritten
    them (`recovery.py:180-186`), else from disk — so a developer edit counts and another run's mid-flight rewrite does
    not. Measured cost on this tree: 0.04 s (clean tree, design time).
  - `identity.env_id(env) -> (hash, names)`: computed once in `cli.main()` before cli mutates `os.environ`
    (`cli.py:826-832`) and reused by every `run_one` of that process. sha256 over sorted `name=sha256(value)` of every
    var not in `VOLATILE`: shell/session noise (`CLAUDE*`, `T3CODE*`, `AI_AGENT`, `XPC_*`, `__CF*`, `SHLVL`, `PWD`,
    `OLDPWD`, `_`, `SSH_AUTH_SOCK`, `TERM*`, `COLUMNS`, `LINES`, `GIT_EDITOR`, `MallocNanoZone`); the gate's own
    bookkeeping (`nightly.GATE_ENV` = `SLOP_GATED`, `SLOP_GATE_PID`, `SLOP_GATE_WAIT_S`, `SLOP_GATE_LOAD`, set by
    `~/.slop/gate.py:507`); admission-only waits that decide when, not how, a run executes (`SLOP_LOCK_WAIT_S`,
    `SLOP_WIRE_LOCK_WAIT_S`, `SLOP_LOAD_TIMEOUT`, `SLOP_START_STAGGER_S`, `SLOP_MAX_RUNS`, `SLOP_MAX_LOAD`,
    `SLOP_MAX_THREADS_MACHINE`, `SLOP_MAX_SOCKETS`, `SLOP_SHARE_WAIT_S`). Everything else — guard limits, `SLOP_GATE`,
    `PLAYWRIGHT_NODEJS_PATH`, `SLOP_PW_NODE`, `PATH`, `SLOP_GATE_EXCLUSIVE` — is identity. `PATH` picks the `node` the
    stack spawns (`stack.py:203,284,292`). `SLOP_GATE_EXCLUSIVE` is not admission-only: it makes the outer
    `gate.py run` exclusive (`~/.slop/gate.py:466`, `slop/run` passes no explicit flag unless medium/120+), and an
    exclusive run gets its declared socket guard limit instead of `SLOP_MAX_SOCKETS_RUN` (`gate.py:323-336`). Nothing
    joins `VOLATILE` without such a check showing it is bookkeeping or an admission-only wait.
  - Cross-shell reuse, measured 2026-11-10 (names only, values never printed): this agent's shell vs `zsh -lic` differs
    by `PATH` value and `CONDA_*`, `FPATH`, `INFOPATH`, `GSETTINGS_SCHEMA_DIR*` names; vs `zsh -lc` by `PATH`, `FPATH`,
    `INFOPATH`. So a baseline recorded from an agent shell is refused from a conda-activated human shell — by design,
    since `PATH` changes the runtime. Two shells of the same kind (slop-runner → slop-runner) differ only in `VOLATILE`
    names (`CLAUDE*`, `T3CODE*`). The README's `--baseline` wording says "record and reuse from the same kind of
    shell". The Acceptance records the cross-shell result as a measurement, not a pass condition on reuse.
  - `identity.baseline_problem(base_params, cur) -> str | None`: legacy (no `source_id`), raced
    (`source_id != source_id_end`), source differs, env names added/removed, env value changed.
  - `cli.RUN_FACTS` gains `source_id`, `source_id_end`, `env_id`, `env_names`. `_same_knobs` unchanged.
  - `cli._load_baseline` adds `identity.baseline_problem` after the knob comparison; `break_one` checks the fault run's
    start and end `source_id` against the baseline's (with or without `--baseline`).
  - `metrics.json` gains `run_phases` (below). `Stack` exposes `waits: list[{name, seconds, polls}]` and
    `teardown_s` (set by its own `__exit__`, including the partial-start one at `stack.py:213-215`).
  - `share.main(argv)`; `slop/run` execs it before the gate re-exec when `--share` is in the args.
- **Schema.** No database. Evidence formats only:
  ```
  params += {source_id, source_id_end, env_id, env_names: [str]}          # run facts, never knobs
  run_phases = {startup_s, seeding_s, execution_s, teardown_s: float|null,
                seed_calls: int, seed_failed: int, waits: [{name, seconds, polls}]}
                # polls = requests sent; a wait that needed no sleep has polls 1 (sleeps = polls - 1)
  slop/evidence/.share/<key>.lock                       flock only; never unlinked
  slop/evidence/.share/<key>.json                       {nonce, pid, argv, cwd, checkout, source_id, env_id, started}
  slop/evidence/.share/<key>.<nonce>.log                leader's tee'd output; immutable once result exists
  slop/evidence/.share/<key>.<nonce>.result.json        {nonce, exit, source_id_end, finished}; none if cancelled
  ```
  `key = sha256(argv without --share, checkout realpath, cwd realpath, source_id, env_id)`; argv is the exact original
  argument vector with `--share` removed, order kept (T4 review: reordered flags never share; no normalisation). All JSON written
  with the existing atomic replace (`report.py:17-27`). `slop/evidence/` is already gitignored (`slop/.gitignore:2`),
  which also makes sharing per checkout.
- **Contracts.** `slop/run` exit codes unchanged (0 / 1 / 3; gate 75). `slop: folder <path>` stays the line nightly and
  the slop-runner parse; a follower prints the leader's log verbatim, prefixed by one `slop: shared run of pid N
  (started T)` line, and exits with the leader child's exit code verbatim. A refused baseline is INCONCLUSIVE exit 3 as
  today's knob mismatch is, and starts no fault run.
- **Phase timing.** Measured in `run_one`/`_run_stack` from the post-gate `t0` (`cli.py:450`) so the four phases sum to
  the `seconds` metric (`cli.py:474`): startup = `t0` through Stack/FakeOF/fleet entry (relays, `next`, readiness);
  seeding = sum of every `Ctx.build` (try/finally, failures included); execution = `mod.run` minus seeding; teardown =
  from `mod.run` end through monitor stop and stack/wire `__exit__` (also on timeout/SIGTERM paths in `run_one`). A
  failed start charges its partial cleanup (`Stack.teardown_s`) to teardown, not startup. Gate wait stays
  `params.lock_wait_s`. The metric is named `run_phases` because nightly's summary already uses `phases` for
  all/volume/map. Nightly: `row_of` copies `run_phases` and `gate_wait_s`; `merge_rerun` sums both attempts' phase
  seconds and gate waits as it already sums `seconds`; the digest's seeding share = Σ seeding_s / Σ measured run
  seconds (the four phases) of the timed attempts. An untimed attempt (no `run_phases`, or all four null: died before
  a folder, gate exit 75, load error) keeps its wall seconds in the row's per-attempt `untimed` list (summed by
  `merge_rerun`), and the digest prints the untimed count and seconds and the gate wait apart from the share
  (review correction: row seconds include gate queueing and untimed attempts, which understated the share).
- **Readiness.** `Stack._wait` keeps its contract (HTTP < 500 = ready, same timeouts, same process-exit check). Only if
  ticket 2's evidence qualifies (US 20): first polls at 0.1 s, doubling to the current 1 s cap, and each request's
  timeout capped at the remaining budget (today `httpx.get(..., timeout=60)` can overrun it, `stack.py:334`). Teardown's
  10 s deadline and `UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN=5` stay (deliberate: Dockerfile parity). T3 also writes an
  inventory of fixed sleeps ≥ 2 s in `slop/scenarios`/`slop/actors`, each classed observation-window or readiness, to
  `.scratch/slop-local-feedback/sleeps.md`; it changes none of them without its own before/after.
- **Shared run protocol.**
  - Election: `share.main` computes the key, opens `<key>.lock` (never unlinked), tries `LOCK_EX|LOCK_NB`.
  - Leader: atomically writes `<key>.json` with a fresh nonce, then runs `slop/run <args without --share>` as a child
    (which takes the gate normally), tees its output to `<key>.<nonce>.log`; on SIGINT/SIGTERM/SIGHUP it stops the child
    the way nightly does (`Night.stop_child`: SIGINT, then `kill_tree` after 60 s, `nightly.py:349-385`, reused, not
    copied) and publishes no result — a cancellation anywhere from publication through spawn to the child's exit
    (a signal inside `Popen` is held until the child is assigned, so it is never left unsupervised); after the child
    exits and its pipe is drained it writes `<key>.<nonce>.result.json` (child's exit, fresh `source_id_end`; a
    signal then is held until the result is written), then unlocks. It deletes nothing: generation files are kept
    (T4 review: a caller's own `SLOP_SHARE_WAIT_S` cannot bound another follower's wait, so no age-based cleanup is
    safe; small logs, removed by hand only while no `--share` run is live).
  - Follower: trylock fails → read `<key>.json`; if its nonce already has a result (a new leader has not published
    yet) or the file is missing, re-read every 0.2 s for at most 10 s, retrying the trylock each time (free lock →
    lead). Having a nonce without a result, it polls every 0.2 s on a monotonic deadline of `SLOP_SHARE_WAIT_S` until
    its own `<key>.<nonce>.result.json` exists, the leader pid is gone, or a non-blocking `LOCK_SH` is granted
    (released at once), then reads that result — that nonce's files are never overwritten by a later leader. (T4
    review amendment, replacing "`LOCK_SH` blocking, bounded by alarm": flock grants no order, so a later generation B
    could take the lock first and a blocking follower of A would wait out B's whole run though A's result exists.) Result with `source_id_end == source_id` → print its log, exit with its exit code. No result → print the log
    and exit 3 with `slop: INFRA shared run … (leader cancelled/died)`. Source changed (`source_id_end != source_id`)
    → print the log and exit 3 with `slop: INFRA shared run … (source changed during the run; re-run)` — no re-key,
    no re-election, no automatic re-run (fail closed; the caller re-runs). The follower never signals the leader.
  - The publication-gap re-read stays a bounded loop (0.2 s steps, ≤ 10 s, trylock each step), not a single retry: a
    leader can hold the lock before its `<key>.json` is written for longer than one retry interval, and a single retry
    would turn that ordinary race into a spurious INFRA. Ending the loop without a readable live nonce → INFRA exit 3
    `(shared run did not publish)`, never a guess.
  - Nightly's child argv never contains `--share`; no env var enables it.
- **Slicing (≤ 4 tickets, in order).** T1 Run identity + baseline refusal + README section without `--share`
  (US 1–12). T2 Run phase timing + nightly totals + measured before-numbers: 5 small runs each of the no-UI and UI
  Acceptance scenarios, listed as `before` in `t3-startup.json` (US 13–19). T3 is a decision ticket on T2's numbers
  (US 20–21): it writes the sleep inventory, and if the before folders' median sleeps per wait (`polls - 1`) is < 1 it
  closes `no-change`/`few-sleeps` with no new runs; otherwise it makes the poll change and runs 5 `after` per scenario
  (`kept`/`dropped` or `no-change`/`no-drop`). Every verdict is recomputable from the listed folders. T4 `--share` in
  its smallest form (election, leader tee + result, follower replay, bounded publication-gap loop; source change →
  INFRA) + its README lines (US 22–32).

## Testing Decisions
- Seams, highest first: (1) the `slop/run` CLI on the real path (no-UI `2026-11-07-chat-sweep-cadence`, ~20 s, and UI
  `2026-11-07-ai-chatter-nav`, measured 12–14 s at small on 2026-11-09, both declare a `FAULT`); (2) `cli.main()` with a
  fake `Stack` class injected below `_run_stack` (so `run_one`'s phase instrumentation runs; today's SIGTERM tests
  replace `_run_stack` whole, `test_cli.py:31-55`, and would bypass it) and a controlled clock; (3)
  `identity.source_id`/`env_id`/`baseline_problem` on a temp git repo, including an `app/.next/slop.state.json` with
  originals; (4) `share.main` with an injected child command (a tiny script that blocks on a barrier file, counts its
  starts in a file and exits with a chosen code) for leader, follower, cancel, death, stale-result, publication-gap
  (lock held, no `<key>.json` yet for 1 s and for > 10 s / old nonce with result), rollover (A finishes, B leads
  before the follower reads), source-change (INFRA, no second child), exit 75 and signal-exit cases — each asserts the
  child-start count; (5) `nightly.digest`,
  `row_of` and `merge_rerun` on fixture folders/rows as `slop/lib/test_nightly.py` does (two-attempt phase and gate
  sums); (2b) `Stack.wait_ready` (public, pre-existing) against a local HTTP server for the readiness `waits` record
  (review correction: the only seam behind "no sleep = 1 poll").
- Tests assert external behaviour: exit codes, printed lines, files in the run folder, child-start counts — never
  private call order.
- Red/green: T1's refusal test is written first and fails on today's knob-only `_load_baseline`; T2's `merge_rerun`
  two-attempt gate-wait sum test is written first and fails on today's first-attempt-only merge (plan: red/green for
  bug fixes).
- Break it once (per ticket, by its reviewer): remove the identity comparison (T1), drop phase recording on the failure
  path (T2), make `share.main` always run fresh and separately make it accept a finished nonce (T4); the named tests and
  the matching Acceptance lines must go red. Accepted limit (T4 review): no Acceptance line can catch "accept a
  finished nonce" — a later request finds the lock free and leads before any result is read — so that mutation is
  proven by seam (4)'s rollover and publication-gap schedules only, not claimed for Acceptance.
- Real-path proof per ticket (via the slop-runner, `--scale=small`, nice 10, through the gate): the Acceptance block.
- Prior art: `slop/lib/test_cli.py` (`cli.main()` with faked stack, SIGTERM cases), `slop/lib/test_nightly.py`
  (digest on fixture folders), `slop/lib/test_stack_recovery.py` (Stack without a real relay), `~/.slop/test_gate.py`
  (flock-based gate semantics, outside this repo).

## Acceptance
```sh
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
S=2026-11-07-chat-sweep-cadence; U=2026-11-07-ai-chatter-nav
nfold() { ls -d slop/evidence/*-"$1"-* 2>/dev/null | wc -l; }
nice -n 10 venv/bin/python -m pytest -q slop/lib   # was 455 passed; new identity/phases/share/nightly tests included
test "$(wc -l < slop/lib/cli.py)" -lt 1000
slop/run --changed --dry                           # existing selection, unchanged
grep -q '^## Fast local feedback' slop/README.md

# green run records identity + phases that add up (real path, small, through the gate)
nice -n 10 slop/run "$S" --scale=small 2>&1 | tee /tmp/slf-green.log
G=$(sed -n 's/^slop: folder //p' /tmp/slf-green.log | head -1)
python3 - "$G" <<'EOF'
import json, sys
m = json.load(open(sys.argv[1] + "/metrics.json"))
ph, pa = m["run_phases"], m["params"]
assert all((ph[k] or 0) > 0 for k in ("startup_s", "seeding_s", "execution_s", "teardown_s")), ph
assert ph["seed_calls"] >= 1 and ph["seed_failed"] == 0 and ph["waits"], ph
tot = sum(ph[k] for k in ("startup_s", "seeding_s", "execution_s", "teardown_s"))
assert abs(tot - m["seconds"]) <= max(2.0, 0.1 * m["seconds"]), (tot, m["seconds"])
assert pa["source_id"] and pa["source_id"] == pa["source_id_end"] and pa["env_id"], pa
assert all("=" not in n for n in pa["env_names"]), "env values must never be stored"
EOF

# equal identity: the saved baseline is reused (no fresh baseline run), CAUGHT
n0=$(nfold "$S")
nice -n 10 slop/run "$S" --scale=small --break --baseline="$G" 2>&1 | tee /tmp/slf-reuse.log
grep -q "mutation CAUGHT" /tmp/slf-reuse.log; grep -qF "baseline: $(cd "$G" && pwd -P)" /tmp/slf-reuse.log
test "$(nfold "$S")" -eq $((n0 + 1))

# changed source: refused for source, exit 3, no fault run
n0=$(nfold "$S"); touch slop/.identity-probe
rc=0; nice -n 10 slop/run "$S" --scale=small --break --baseline="$G" > /tmp/slf-src.log 2>&1 || rc=$?
rm -f slop/.identity-probe; test "$rc" -eq 3
grep -q 'inconclusive: .*source' /tmp/slf-src.log; test "$(nfold "$S")" -eq "$n0"

# changed env: refused naming the var, exit 3, no fault run
rc=0; SLOP_IDENTITY_PROBE=1 nice -n 10 slop/run "$S" --scale=small --break --baseline="$G" > /tmp/slf-env.log 2>&1 || rc=$?
test "$rc" -eq 3; grep -q 'inconclusive: .*SLOP_IDENTITY_PROBE' /tmp/slf-env.log; test "$(nfold "$S")" -eq "$n0"

# probe gone: the same baseline is reusable again (the refusals were identity, not something else)
nice -n 10 slop/run "$S" --scale=small --break --baseline="$G" > /tmp/slf-restored.log 2>&1
grep -q "mutation CAUGHT" /tmp/slf-restored.log

# cross-shell: a measurement, recorded, not a reuse pass condition. The result must be either reuse (CAUGHT) or an
# env refusal (exit 3, no fault run) — never a source refusal or anything else. Differing names only, never values.
n0=$(nfold "$S")
rc=0; zsh -lic "cd '$PWD' && nice -n 10 slop/run '$S' --scale=small --break --baseline='$G'" > /tmp/slf-xsh.log 2>&1 || rc=$?
python3 - > /tmp/slf-xsh-names.txt <<'EOF2'
import os, subprocess
b = dict(l.split("=", 1) for l in subprocess.run(["zsh", "-lic", "env -0"], capture_output=True, text=True).stdout.split("\0") if "=" in l)
a = dict(os.environ)
print("only-here:", sorted(set(a) - set(b))); print("only-zsh:", sorted(set(b) - set(a)))
print("value-differs:", sorted(k for k in set(a) & set(b) if a[k] != b[k]))
EOF2
{ echo "exit=$rc"; grep -E 'mutation CAUGHT|inconclusive:' /tmp/slf-xsh.log | head -2; cat /tmp/slf-xsh-names.txt; } \
  > .scratch/slop-local-feedback/cross-shell.txt
if [ "$rc" -eq 0 ]; then grep -q "mutation CAUGHT" /tmp/slf-xsh.log
else test "$rc" -eq 3; grep -q 'inconclusive: .*env' /tmp/slf-xsh.log; ! grep -q 'inconclusive: .*source' /tmp/slf-xsh.log
     test "$(nfold "$S")" -eq "$n0"; fi

# two exact concurrent --share UI requests: one execution, both green, same folder. The gate may serialize
# separate runs; folder-count and follower-line assertions still reject that always-fresh behavior.
n0=$(nfold "$U")
nice -n 10 slop/run "$U" --scale=small --share > /tmp/slf-a.log 2>&1 & a=$!
nice -n 10 slop/run "$U" --scale=small --share > /tmp/slf-b.log 2>&1 & b=$!
ra=0; wait "$a" || ra=$?; rb=0; wait "$b" || rb=$?
test "$ra" -eq 0; test "$rb" -eq 0
fa=$(sed -n 's/^slop: folder //p' /tmp/slf-a.log); test -n "$fa"
test "$fa" = "$(sed -n 's/^slop: folder //p' /tmp/slf-b.log)"
test "$(nfold "$U")" -eq $((n0 + 1))
test "$(grep -l '^slop: shared run of pid' /tmp/slf-a.log /tmp/slf-b.log | wc -l)" -eq 1
head -1 "$fa/summary.txt" | grep -q ': PASS$'

# a later --share request is a Fresh run, not the finished one
nice -n 10 slop/run "$U" --scale=small --share > /tmp/slf-c.log 2>&1
test "$(nfold "$U")" -eq $((n0 + 2)); ! grep -q '^slop: shared run of pid' /tmp/slf-c.log

# T3 decision is a checked artifact, not a note: every verdict recomputes from its listed folders
python3 - <<'EOF'
import json, statistics
from pathlib import Path
t = json.load(open(".scratch/slop-local-feedback/t3-startup.json"))
ph = lambda f: json.load(open(Path("slop/evidence") / f / "metrics.json"))["run_phases"]
assert (t["verdict"], t["reason"]) in (("no-change", "few-sleeps"), ("no-change", "no-drop"), ("kept", "dropped")), t
assert set(t["before"]) == {"2026-11-07-chat-sweep-cadence", "2026-11-07-ai-chatter-nav"}, t["before"]
sleeps = [w["polls"] - 1 for fs in t["before"].values() for f in fs for w in ph(f)["waits"]]
assert sleeps and statistics.median(sleeps) == t["median_sleeps_per_wait"], t
assert (statistics.median(sleeps) < 1) == (t["reason"] == "few-sleeps"), t
for side in ("before",) if t["reason"] == "few-sleeps" else ("before", "after"):
    for scen, folders in t[side].items():
        assert len(folders) >= 5, (side, scen)
        assert statistics.median(ph(f)["startup_s"] for f in folders) == t["median"][side][scen], (side, scen)
if t["reason"] != "few-sleeps":
    dropped = all(t["median"]["after"][s] < t["median"]["before"][s] for s in t["before"])
    assert dropped == (t["verdict"] == "kept"), t["median"]
assert Path(".scratch/slop-local-feedback/sleeps.md").exists()
EOF
# observed after merge (not gating): next nightly's summary.md shows the run-phase totals line with seeding's share
```

## Depends on
None — single Phase. Within it, T2 needs T1 only for shared test fixtures; T3 needs T2's `run_phases.waits`; T4 needs
T1's `identity` module and adds its README lines to T1's section.

## Out of Scope
- Seed cache (#5): measured seeding share 1.22 % of run seconds over 631 November main-checkout runs (design-time
  scan of `metrics.json` `seed`); brief's stored figure 1.7 %; both far under the plan's 15 % trigger.
- Production-build cache: plan constraint (relay URL baked per run).
- Any gate change (slots, load/thread limits, stagger, exclusive rule, forced quiet scheduling, KVMs): plan item 3.
- Historical result caching (serving a finished run): plan item 6 prefers the opt-in in-flight seam; CONTEXT "Shared run".
- Cross-checkout sharing: see ASSUMPTION below.
- An immutable execution snapshot (copying the tree per run): would close the A→B→A gap below, at a copy per run;
  plan asks for the smallest safe seam.
- Changing timing thresholds, budgets, deliberate observation windows or teardown grace: plan constraint.
- Teaching the user-level `~/.claude/agents/slop-runner.md` to pass `--share`: outside this working tree, so not a
  ticket. Coordinator follow-up once T4 is merged and its Acceptance green (owner CLAUDE.md: shared agents are edited
  in `~/.claude/agents/`): one line — append `--share` to `slop/run --changed` and single-scenario commands unless the
  brief says repeat, flake or fresh; never to `nightly`, `--map` or `all`; report `shared` when the output has the
  `slop: shared run of pid` line. Until then T4 has no automated caller and its value stays zero (measured scope).
- An external scheduler or monitor integration: none found in the repo (`git grep 'slop/run'` outside evidence hits only
  docs/.scratch; callers are the slop-runner agent, humans and `slop/lib/nightly.py`); plan says not to invent one.
- New selection machinery: `--changed` already does it (plan item 1).
- Nightly treating exit 0 without a folder as OK (`nightly.verdict(0, None, None)`): pre-existing, nightly never shares.

## Further Notes
- Measured at design time: across 2546 unique November run folders in 33 checkouts on this machine, exactly one pair
  overlapped in time with equal sha, dirty flag and knobs (137 s, two different checkouts, dirty); 6 runs were INFRA on
  the per-checkout app lock. So T4's in-scope saving over that sample is zero (measured: the one overlap was
  cross-checkout, T4 is per-checkout); it is specced because the plan lists it and the owner wants it, built in its
  smallest form, kept last and opt-in so it can be dropped without touching T1–T3. Its value is honest only as
  disclosed here; the Phase does not widen it (no cross-checkout or historical sharing) to manufacture savings.
- The Phase adds safety and measurement more than speed. T1 does not make reuse faster (today `--baseline` already
  reuses, unsafely); it makes it correct. No end-to-end dev-loop benchmark is added: T2's `run_phases` and nightly
  totals are the measurement, and the final report quotes them instead of claiming a saving.
- Gate waits were 1129 s of the 5h03m nightly = 6.2 % (measured arithmetic on the plan's figures); no share of that is
  claimed as a saving.
- Readiness saving is a guess until T2 measures it: at most ~0.5 s mean per readiness wait (half the 1 s poll).
- Source identity is checked at run start and end only: an edit made and reverted within one run (A→B→A) is not
  detected. Disclosed in the README's `--baseline` wording.

ASSUMPTION: Shared runs are per checkout and per working directory (lock files under the checkout's own gitignored
`slop/evidence/.share/`, cwd in the key). Rung 4 (narrower is reversible) + 5. Overturned by measured cross-checkout
duplicate overlap worth a cross-checkout identity (the only measured overlap was cross-checkout, 137 s in November).

ASSUMPTION: `env_id` covers every caller env var minus noise, gate bookkeeping and admission-only waits, so an unknown
var blocks reuse/sharing rather than being ignored; guard limits and runtime paths count. Rung 4 (conservative).
Overturned by measured baseline refusals caused only by irrelevant vars — then extend `VOLATILE`, never switch to an
allowlist without evidence. Measured 2026-11-10: agent vs `zsh -lic` shells differ by `PATH` (runtime, stays) and
`CONDA_*`, `FPATH`, `INFOPATH`, `GSETTINGS_SCHEMA_DIR*` (not shown irrelevant: conda activation is what changes
`PATH`), so cross-kind reuse is refused by design; same-kind reuse is the supported loop.

ASSUMPTION: `source_id` is the whole working tree (not `covmap.DIFF_ROOTS`) plus the listed ignored stack inputs;
in-place `pip install` into the venv without changing its python path is not detected. Rung 4 + 5. Overturned if
identity takes > 1 s on a real dirty tree, or a venv package change is shown to have flipped a reused baseline.

ASSUMPTION: baseline folders without `source_id` are refused, no legacy fallback by `git_sha`. Rung 4. Overturned by
an owner request for a fallback.

ASSUMPTION: a leader that was cancelled, timed out or died, or whose source changed mid-run, leaves its followers
INFRA exit 3 (no automatic re-run, no re-key, no re-election). Rung 4 (fail closed, reversible) + 5; coordinator
decision on the six-hats Green bullet. Overturned by measured follower INFRA from source changes often enough to cost
more than the protocol re-key adds, or by the owner preferring auto re-run.

ASSUMPTION: the publication-gap re-read stays a bounded 0.2 s × ≤ 10 s loop, not one retry. Rung 4 (a spurious INFRA
costs a whole re-run; the loop costs ≤ 10 s of a follower that would wait anyway) + coordinator decision. Overturned by
seam (4) showing the 1 s gap schedule passes with one retry and the > 10 s one INFRAs either way — then it is
equivalent and the simpler form may be taken.

ASSUMPTION: `SLOP_SHARE_WAIT_S` default 7200 s (gate slot wait 3600 + scenario timeout 1800 + admission margin), then
INFRA exit 3. Rung 5. Overturned by a measured follower wait hitting it.

ASSUMPTION: T3 changes `Stack._wait` only if T2's before folders show median sleeps per wait (`polls - 1`) ≥ 1, and
keeps it only if median startup_s over 5 runs drops (no-UI and UI scenario); otherwise it closes `no-change` on those
folders with no new runs. Rung 5 + plan item 4. Overturned by the before/after medians, or by the 10 T2 before runs
being unrepresentative (e.g. all taken under high machine load) — then T3 re-measures.

ASSUMPTION: the README "Fast local feedback" section ships in T1 without `--share`; T4 adds its lines (items 1 and 3
are docs-only, no own ticket). Rung 5.

ASSUMPTION: `--set` of a reserved knob name (`seed`, `scale`, …) overriding the recorded knob (`cli.py:93-103`) is
left as is: no scenario reads such a param (`grep -l 'param("seed"' slop/scenarios` empty). Rung 5. Overturned by a
caller that passes one.

## Review
codex (read-only, `model_reasoning_effort=high`), 2026-11-10. Blind call on a git-free copy of the review workspace
(no `docs/spec`, `.scratch`, `.claude`, env or db); draft call with this spec minus `## Review`. Both exit 0, outputs
verbatim in `.scratch/slop-local-feedback/adversary-blind.md` and `adversary-draft.md`.

Draft call:
- D1 `VOLATILE` excludes execution settings (`SLOP_GATE`, guard limits, `PLAYWRIGHT_NODEJS_PATH`) — **accept**:
  `gate.py:68` (`SLOP_GATE=off` skips the nested gate), README:293-294 (guard kills), `cli.py:831`; VOLATILE narrowed
  to noise + `nightly.GATE_ENV` + admission-only waits; env_id computed before cli mutates env (US 6, Interfaces).
- D2 blanket tsconfig/next-env exclusion hides edits; ignored deps unchecked — **accept**: originals read from
  `slop.state.json` (`recovery.py:180-186`); `app/.env*`, `.slop-lock-sha`, venv python added (US 5). In-place pip
  change stays undetected — ASSUMPTION.
- D3 aggregate env hash cannot name a changed value — **accept**: US 7 now names added/removed vars or says "env value
  changed (values are not stored)"; per-var hashes rejected (low-entropy secrets brute-forceable).
- D4 A→B→A passes; fault-run end identity unchecked — **partial**: fault run start+end now compared to the baseline
  (US 8, 10); A→B→A disclosed (Further Notes), snapshot out of scope (copy per run, plan wants smallest seam).
- D5 follower registration races (publication gap, first leader, rollover overwrites) — **accept**: nonce-scoped
  immutable log/result, "finished nonce = not yet published, re-read ≤ 10 s", lock file never unlinked, schedules in
  seam (4) (Shared run protocol).
- D6 follower promotion has no identity transition — **accept**, then superseded by the six-hats reconcile (G1): a
  source change now ends the follower INFRA exit 3 with no re-key or re-election (US 27), which removes the transition
  instead of specifying it.
- D7 cancellation stops at the wrapper; exit 75/signal exits — **accept**: reuse `Night.stop_child`/`kill_tree`
  (rung 3, `nightly.py:349-385`), unlock after drain, exit code verbatim incl. 75 (US 23, protocol).
- D8 key omits cwd (relative `--baseline`) — **accept**: cwd realpath in key (US 22, Schema).
- D9 Acceptance false positives — **accept**: refusal asserts reason + no new folder + reuse after restore; reuse
  asserts `baseline: $G` + one folder; share asserts exit 0 both + PASS + exactly one follower line; a later request is
  fresh. Gate admission by followers is proven at seam (4) by child-start count, not by folder count — partial there.
- D10 failed-start cleanup charged to startup; startup omits FakeOF/fleet — **accept**: `Stack.teardown_s` on the
  partial path, startup from post-gate `t0`, phases sum to `seconds` (asserted).
- D11 `merge_rerun` drops re-run phase/gate time — **accept**: measured by codex (`10+20 → 30` seconds but gate `2+3 →
  2`); `merge_rerun` sums them, denominator Σ row seconds (US 19, seam 5).
- D12 seams underspecified; SIGTERM tests bypass instrumentation; no UI share; T3 manual — **accept**: fake Stack below
  `_run_stack`, race schedules listed, UI scenario for `--share` (fails without sharing via app lock), T3 checked
  `t3-startup.json`. Nightly totals line stays an after-merge observation; its logic is gated by seam (5) — partial.
- D13 T1 README advertises `--share` before T4; cli.py 978 → 1000 unprotected — **accept**: `--share` docs in T4
  (US 32); identity/phases in own modules, `wc -l < 1000` in Acceptance, `breakit.py` extraction fallback.

Blind call:
- B1 strengthen evidence validity before sharing — **accept**: already ordered T1 → T4.
- B2 alternatives: explicit attach to a known execution; immutable snapshot — **reject**: no caller distributes
  execution references (Out of Scope, external scheduler); `--share` is equally opt-in; snapshot as D4.
- B3 historical caching incompatible with Shared run — **accept**: already Out of Scope.
- B4 `_load_baseline` reuses an obsolete-SHA folder — **accept**: the premise of T1 (US 7–9).
- B5 empty-checks baseline returns `({}, None)` — **reject**: `break_one` then reports missing targets INCONCLUSIVE
  (`cli.py:698-713`), as codex itself notes.
- B6 `--set seed=…` overwrites the recorded knob — **reject**: no scenario reads reserved params (grep empty); ASSUMPTION.
- B7 `nightly.verdict(0, None, None)` is OK — **reject**: pre-existing, nightly never shares; Out of Scope line added.
- B8 untracked runtime files (plugin globs) must count — **accept**: already in `source_id`.
- B9 selection exclusions ≠ identity exclusions — **accept**: whole tree + ignored inputs (D2).
- B10 timeout/admission not in knobs — **partial**: share key has full argv (timeout included); a green baseline is
  green whatever its timeout, so not added to baseline identity.
- B11 env exclusions need proof; `SLOP_SERVER_WORKERS` etc. are inputs — **accept**: they are hashed (deny-list).
- B12 hashing everything is wrong (ports, gate vars) — **partial**: ports/paths are generated inside the stack, not
  caller env; gate bookkeeping excluded via `nightly.GATE_ENV` (D1).
- B13 outside-git settings (gate impl, `.env`) — **partial**: `app/.env*` hashed; service `.env` disabled by
  `relay_guarded.py:108-123`; `~/.slop/gate.py` affects admission/guards only, not the code under test — rejected.
- B14 tsconfig/next-env rewrites — **accept**: D2.
- B15 keep baseline, share and p95 comparisons separate — **accept**: `_same_knobs` unchanged (US 11).
- B16 followers must join before the gate — **accept**: already (`slop/run` routes `--share` before the re-exec).
- B17 atomic election, generation, never unlink the lock — **accept**: D5.
- B18 publish only the complete result — **accept**: result written after child exit + drain (D5/D7).
- B19 cancellation underspecified — **accept**: D7, US 25–26.
- B20 preserve the app lock — **accept**: followers never enter `Stack`; non-sharing runs unchanged.
- B21 retries must be forced fresh — **accept**: no env opt-in (US 29).
- B22 restrict sharing to single-scenario requests — **reject**: the follower waits for the leader process to exit, so
  `--break`/`--changed`/`all` outputs are complete; `--map`/`nightly` already refused (US 30).
- B23 acceptance traps (zero exits, same folder, refusal ≠ sharing) — **accept**: D9.
- B24 break the tests deliberately — **accept**: "Break it once" bullet in Testing Decisions.
- B25 timing proof automatable; reconcile with outer timer — **accept**: phases-sum-to-`seconds` and `t3-startup.json`
  checks in Acceptance.
- B26 per-request timeout 60 s can overrun the poll budget — **partial**: capped only if T3 touches `_wait`.
- B27 scenario fixed waits (fleet-200 8 s) as candidates — **partial**: T3 writes a classified inventory, changes none
  without its own before/after (plan item 4 keeps observation windows).
- B28 premise falsifiers; gate waits 6.21 % — **accept**: figure added; sharing value disclosed as near zero.

### Six hats
Report verbatim in `.scratch/slop-local-feedback/six-hats.md` (2026-11-10). Facts it states were re-checked; its
guesses stay guesses. Coordinator decisions (rung 2, invocation) applied where named.
- W1 plan items 1–4, 6 → 4 tickets; seed cache out at 1.22 %/1.7 %; gate unchanged — **accept**: fact, matches spec.
- W2 T4's in-scope saving is zero (measured) — **accept**: Further Notes now says "zero in scope, measured" instead of
  "inferred near zero"; T4 kept because the owner wants sharing, smallest form.
- W3 time saving unknown; no end-to-end before/after — **partial**: disclosed in Further Notes; no dev-loop benchmark
  added (YAGNI; T2's `run_phases` + nightly totals are the measurement, the plan asks to report measurements and limits).
- R1 T1 is the real win (correctness hole) — **accept**: gut, agrees with the ordering; no change.
- R2 T4 is a heavy protocol for a measured-zero benefit — **partial**: re-key/re-elect cut (G1); nonces, rollover and
  the bounded publication-gap loop stay — they are what makes "never an earlier finished run" and "no spurious INFRA"
  true.
- R3 Phase adds safety more than speed — **accept**: disclosed in Further Notes.
- K1 `env_id` may block real reuse; `SLOP_GATE_EXCLUSIVE` admission-only — **partial**. Measured: agent shell vs
  `zsh -lic` differs by `PATH` value and `CONDA_*`/`FPATH`/`INFOPATH`/`GSETTINGS_SCHEMA_DIR*` names (so the risk is
  real across shell kinds; same-kind shells differ only in `VOLATILE` names). `PATH` stays identity: it picks the
  `node` the stack spawns (`stack.py:203,284,292`). `SLOP_GATE_EXCLUSIVE` measured **not** admission-only: it makes the
  outer gate exclusive (`gate.py:466`), which changes the socket guard limit (`gate.py:323-336`) — stays identity.
  Added: a cross-shell Acceptance measurement recorded to `.scratch/slop-local-feedback/cross-shell.txt` (reuse or env
  refusal, never source refusal), README "same kind of shell" wording (US 12). No var added to `VOLATILE`.
- K2 `source_id` may report false "raced" when another session edits the worktree — **partial**: fail closed is the
  intended behaviour (an edit during a run does make the verdict suspect); house rule is one run owner per worktree
  (memory "No proof runs while implementer edits"). A run's own writes land in ignored paths — the green Acceptance
  asserts `source_id == source_id_end` (measured once T1 runs). README says `raced` = re-run with nobody editing (US 12).
- K3 cli.py budget tight; T3 needs ~20 runs — **accept**: implementer checks `wc -l` before editing and extracts
  `breakit.py` up front at ≥ 990 (Implementation Decisions); T3 reuses T2's 10 before runs and adds 10 only if it
  changes the poll (Slicing, Acceptance).
- Y1 T1 refusal design sound — **accept**: no change.
- Y2 T2 makes the 15 % rule checkable and fixes `merge_rerun` — **accept**: no change.
- Y3 ordering T1→T4, T4 droppable — **accept**: no change.
- G1 shrink T4: source change → INFRA, publication gap → one retry — **partial**: source change → INFRA exit 3, no
  re-key/re-elect (**accept**, coordinator decision; US 27, protocol, seam 4, ASSUMPTION). One retry **rejected**
  (coordinator decision): a leader may hold the lock longer than one retry before publishing, so one retry turns an
  ordinary race into spurious INFRA; bounded loop kept, seam 4 gains a 1 s and a > 10 s gap schedule. "Roughly halve"
  is the report's guess; not relied on.
- G2 evidence path for `env_id` before T1 merges; add PATH-class vars to `VOLATILE` if refused — **partial**: evidence
  path **accept** (measured now + Acceptance step); adding PATH-class vars **reject**: `PATH` is runtime selection
  (coordinator: never weaken identity without proof it is bookkeeping).
- G3 let T3 close early on T2's before runs — **accept** with evidence: `no-change`/`few-sleeps` only when the listed
  before folders recompute median sleeps per wait < 1; T2 produces those 10 runs (Slicing, Acceptance).
- B1 T1 → T2 now; `wc -l` check and early `breakit.py` — **accept**: as K3.
- B2 T3 a decision ticket; T4's shrunk form recorded as ASSUMPTION — **accept**: Slicing + ASSUMPTIONs.
- B3 slop-runner must learn `--share` after merge — **accept**: coordinator follow-up after T4 merges, exact one-line
  rule in Out of Scope; not a human blocker (owner CLAUDE.md puts shared-agent edits in scope).
- The report's Recommendation is about the set: reconciled in `docs/spec/plan-review.md` › Slop local feedback.
- Its ASSUMPTION "PATH differs between agent and human sessions" — now measured (K1); its ASSUMPTION "roughly halve" —
  guess, not used.

### T4 implementation review (round 2)
Reviewer REQUEST CHANGES on the first `share.py`; coordinator decisions (rung 2) applied:
- Leader cancelled outside its tee (during `p.wait()`, publication, or inside `Popen`) was killed by `kill_tree` or
  orphaned and printed "follower stopped" — **accept**: one `except Stopped` from publication through `p.wait()`,
  a signal inside `Popen` held until the child is assigned, `nightly.stop_child` reused; seam (4) schedules for
  publication, spawn and closed-stdout-while-alive.
- Blocking `LOCK_SH` lets generation B starve a follower of A — **accept**: bounded 0.2 s poll of A's own result,
  leader pid and a non-blocking `LOCK_SH`; SIGALRM removed (protocol amended; rollover-while-B-runs schedule).
- `cancelled` result field — **accept**: dropped; a cancelled leader publishes no result (schema verbatim), and
  writes its `leader cancelled` line to its log so followers see why.
- Finished-generation test could not fail — **accept**: renamed to a later request leading fresh; limit recorded in
  Testing Decisions.
- Age-based `_sweep` with differing `SLOP_SHARE_WAIT_S` — **accept**: removed; files kept (protocol, README).
- Argument order in the key — **accept** as narrow: exact argv minus `--share`, order kept (Schema, README).
