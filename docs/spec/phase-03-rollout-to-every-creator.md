# Phase 03 — Rollout to every Creator on AE

**Objective.** A host-side Rollout driver can, unattended and resumably, bring every Eligible Creator on a relay to its
Describe target and Fill every eligible Sequence through the product routes (Apply gate, Fleet ceiling, Rollout
journal, undo, sanitised report), proven on the slop stack, with two new watch checks for coverage and Fill read-back.

**Sub-phases** (plan review, 2026-11-21). **3a — Describe side**: modes `measure | collect | describe | report`,
roster, Fleet ceiling, pauses, describe resume, describe report; needs only Phase 1a; ships in wave 1 with 1a so the
multi-day describe wave starts first. **3b — Fill side**: modes `plan | apply | undo`, Apply gate, backup check,
apply journal, read-back, lost-response reconcile, the report's Fill columns and contact sheet, both watch checks;
wave 3, needs Phase 1b, 3a, and a passed fit check. Every story, decision, seam and Acceptance block is labelled.

## Problem Statement
Phase 1 and Phase 2 give one owner one press per Sequence. AE has 18 Creators with a vault mirror, 330 candidate
Sequences and about 16,500 items to describe (issue 07). Pressing by hand is days of clicks, describe-all is one
manual press per Creator, the $1/day Describe cap stops sweeps short, and nothing records what a mass Fill wrote, so
it could neither be checked before chatters use it nor taken back.

## Solution
`scripts/script-fill-rollout/`, a stdlib-only Python driver run on the box host at nice 10, talking to the relay over
loopback with a founder session. Modes `measure | collect | describe | report` (3a) and `plan | apply | undo` (3b);
every mode is a dry run unless `--live`. It reads the roster once per run, sweeps up to 3 Eligible Creators at a time,
raises each Describe target in steps of 250 up to 1,000, defers capped Creators to the next UTC day, opens (and stops
retrying) a Creator whose sweeps make no progress, stops starting sweeps at the Fleet ceiling or when the relay looks
unwell, applies only Fill plans that pass its own Apply gate, journals intent before every write and reads every write
back, keeps before / after values and Undo lists on the host, and writes a sanitised per-Creator report with sweep
throughput. Two watch checks keep looking after the run.

## User Stories

**3a — Describe side.**

1. As the operator, I want one driver with modes `measure | collect | describe | report` (3b adds `plan | apply | undo`), so that each rollout stage is a separate, repeatable command.
2. As the operator, I want every mode to make no product-state write (vault, Collect runs, Scripts rows, spend ledger) unless I pass `--live`, so that a mistyped command is harmless.
3. As the operator, I want the driver to refuse any relay URL that is not loopback, so that it cannot be aimed at a public host by accident.
4. As the operator, I want to sign in once through a hidden prompt (or hand over a session through the environment), so that no password or cookie lands in a file, the journal or the shell history.
5. As the operator, I want the driver to refuse a session that is not a Master (`is_admin`), so that a partial roster never reads as the whole fleet.
6. As the operator, I want the roster to be every active OnlyFans Creator with a captured session and no Dead session mark, read once at the start of each run, so that only Eligible Creators are worked.
7. As the operator, I want disconnected, deactivated, non-OnlyFans and watcher accounts listed once with their reason and never retried, so that skips are visible but cost nothing.
8. As the operator, I want `measure` to record, read-only, per Creator: vault size, mirror completeness, described count, Describe target remaining, cap state and Sequence count, so that the canary and waves start from numbers.
9. As the operator, I want `collect` to run the existing Collect once per run for an Eligible Creator whose mirror is incomplete or empty, answer its "continue" pauses, wait for it and then re-read `complete`, so that "small vault" is only believed for a complete mirror and a page-capped vault is reported, not re-collected forever.
10. As the operator, I want `describe` to sweep up to 3 Creators at a time, each in sweeps bounded by a Describe target raised 250 at a time up to 1,000, so that the wave moves faster than one Creator at a time and killing the driver leaves at most 3 bounded sweeps running.
11. As the operator, I want the driver to recount described items through the plan route after every sweep instead of trusting the sweep's `done`, so that visits are never mistaken for descriptions.
12. As the operator, I want a Creator done when Phase 1's `target_remaining` is 0 at target 1,000 (or at a lower target equal to Phase 1's goal) on a complete mirror, so that Terminal failures never keep a Creator open forever.
13. As the operator, I want a cap refusal (429 at start, `capped` mid-sweep, items failing `jev_capped`) to defer that Creator until after 00:00 UTC and move on, so that caps stay as configured and the wave keeps going.
14. As the operator, I want a missing vision key, a Jev not ready (`jev.ready` false) or two sweeps in a row that describe nothing to put that Creator on the open list with the reason, so that a problem a person must fix is not retried.
15. As the operator, I want the driver to refuse a sweep that would take run spend past the Fleet ceiling ($2 × Eligible Creators unless restated), measured from each Creator's Describe cap ledger before and after every sweep, so that the run has a money stop whose overshoot is bounded.
16. As the operator, I want to restate the ceiling and per-item cost estimate after the canary by flag, so that the ceiling follows measured cost.
17. As the operator, I want the driver to stop starting sweeps, await the running ones and exit paused when `/livez` fails or is slow, requests keep erroring, two Creators in a row stop with the same error class, Jev is unavailable box-wide, or the ceiling is reached, so that it never grinds a sick relay.
18. As the operator, I want a re-run to resume from the journal (done Creators skipped, deferred ones skipped until their time, a sweep still running on the server awaited, not restarted; 3b adds: an apply whose response was lost reconciled by read-back), so that a crash or kill costs nothing.
19. Cut in plan review (SH-4): no single-process lock per journal; the operator runs one driver.
27. As the operator, I want `report` to write a host-only full report and a sanitised copy (Creator labels, counts, no ids or names) for the repo, with described items per minute of sweep time per Creator and for the run (3b adds the Fill columns), so that results can be shared safely and the describe wave's wall time can be forecast.
29. As the operator, I want `--creator` and `--sequence` filters on every mode, so that the canary is the same code on one Creator.
30. As the operator, I want exit codes that say done, refused, paused or deferred, so that a shell loop can re-run the driver after midnight UTC.

**3b — Fill side.**

20. As the operator, I want `plan` to fetch a Fill plan for every Sequence of every Eligible Creator and run the Apply gate on each, journaling status, gate result and the rows' current values, so that the apply wave works from reviewed plans.
21. As the operator, I want the Apply gate to pass only plans with status `ok`, every media id live in that Creator's vault, valid Step order and previews, every paid price in $3–$200, and the Escalation rule held on every path, so that nothing unsendable is written even if the server errs.
22. As the operator, I want everything the gate or the server refuses listed with its one reason, and non-blocking plan flags (`gap`, `kept_existing`, `kept_unpriced`, `removed_media`, `free_unfilled`) listed per Sequence, so that every Sequence ends filled or explained.
23. As the operator, I want `apply` to refuse to run live without a fresh DB backup that passes an integrity check and holds every row about to be written with its current values, so that a full restore stays possible.
24. As the operator, I want `apply` to send the reviewed fingerprint, re-plan and re-gate once on `409 stale`, and skip as `stale` after a second one, so that an edited Sequence is never forced.
25. As the operator, I want each apply's intent journaled before the call, its Undo list and after values journaled after it, and the reviewed write set read back from the Scripts list and matched against the Undo list, so that a write that does not match, or an Undo list that misses a written row, is reported at once.
26. As the operator, I want `undo` to replay journaled Undo lists through `fill/undo`, scoped to a Creator or Sequence if I say, and to report rows left because someone edited them, so that a Fill is taken back without a DB restore.
28. As the owner, I want a contact sheet of the canary and a seeded sample of 10 filled Sequences, so that I alone judge taste while the wave runs.
31. As the owner, I want a watch check that flags Eligible Creators short of their Describe target and alerts when one has described nothing new in 26 h, so that a stalled describe wave is seen.
32. As the owner, I want a watch check that alerts on any filled Scripts row touched since the rollout whose media is gone from the vault or whose price is unsendable, so that broken fills are found before a chatter sends them.

## Implementation Decisions
- **Owns.** 3a: `scripts/script-fill-rollout/rollout.py` (CLI dispatch, describe side); `rollout_core.py` (Resp,
  Relay, Journal, Ctx, Refused, `say`, `sign_in`); `rollout_fill.py` (fill side); `rollout_decide.py` beside it (pure: roster filter, describe step, sweep outcome, ceiling arithmetic, pause rules, resume state,
  throughput, sanitiser); `test_script_fill_rollout.py` beside them; slop scenario `script-fill-rollout` with its 3a
  checks. 3b adds to the same files: Apply gate, read-back match, Undo reconstruction, apply-side resume and journal
  kinds; the scenario's 3b checks and `slop/lib/script_fill_rollout_faults.py`; in `scripts/proxy-health/watch.py`:
  checks `script_fill_coverage` and `script_fill_readback`, their `WATCH_SQL` keys, README Watch rows and runbook
  lines in `docs/proxy-health/README.md`, rows in `test_watch.py`. Nothing in `service/`.
- **Where watch.py lives** (3b). In this repo: `git ls-files scripts/proxy-health` lists `watch.py` and
  `test_watch.py`. `/Users/founder/oi-proxy-health` is a detached worktree of this same repository (same git common
  dir); its `docs/proxy-health/WATCH.md` is a symlink into `~/proxy-health-data/ae/WATCH.md`, tracked in neither tree.
  The 4h sweep runs watch.py from that worktree, and a WATCH.md line naming a check it does not know is
  `broken -> drop` (`scripts/proxy-health/watch.py:1408`). So the execute stage moves that worktree to a main holding
  both checks and confirms they plan as `run` before any WATCH.md line is added (see Further Notes, runbook).
- **Runtime** (3a). Host python3, standard library only (`urllib.request`, `http.cookiejar`, `json`, `sqlite3`,
  `getpass`, `hashlib`): the box host has no venv and the image carries only `service/` (issue 06 item 1). No
  `service/` import. Run as `nice -n 10 python3 -I scripts/script-fill-rollout/rollout.py <mode> --relay
  http://127.0.0.1:<port> ...`. One process, one thread: parallel sweeps run on the server; the driver polls them.
- **Interfaces.** CLI: `<mode> --relay URL [--live] [--journal PATH] [--creator ID] [--sequence NAME]
  [--ceiling-cents N] [--item-mc N] [--slots N] [--backup PATH] [--sample N --seed N] [--out PATH]`; `--slots` 1–3,
  default 3. Exit 0 done, 2 refused (usage, non-loopback, not Master; 3b: backup bad), 3 paused, 4 deferred work
  remains (re-run after 00:00 UTC). Open Creators (key, Jev not ready, no progress, mirror incomplete) do not change
  the exit code; they are listed. `rollout_decide` exposes pure functions over plain dicts. 3a:
  `eligible(account) -> (bool, reason)`, `next_target(described, goal) -> int`,
  `sweep_outcome(before, after, progress, cap) -> continue|done|defer|open:<reason>`,
  `sweep_spend(cap_before, cap_after) -> mc`, `run_spend(sweep_lines) -> mc`,
  `may_sweep(spent, running, ceiling, step, item_mc)`, `pause_reason(window) -> str|None`,
  `throughput(sweep_lines) -> {creator: items_per_min, run: items_per_min}`, `resume(journal_lines) -> State`,
  `sanitise(report) -> str`. 3b: `apply_gate(plan, live_ids) -> list[reason]`,
  `readback(plan, before_rows, undo, rows_now) -> list[mismatch]`,
  `reconstruct_undo(plan, before_rows, rows_now) -> (undo, uncertain)`; `resume` gains the apply kinds.
- **Auth** (3a). `SFR_SESSION` env holds a `chatterly_session` cookie value; absent and on a TTY, a `getpass` prompt
  signs in via `POST /auth/login` (and `/auth/2fa/login` on a challenge), cookie kept in memory only. `GET /auth/me`
  must say `is_admin`, the Master's registry-wide set. No session is minted inside the container (issue 06 item 2).
  Sign-in and session use bump `last_seen_at` and login-attempt bookkeeping (`service/account_security.py:259`,
  `service/auth.py:675`); that is auth state, not product state, and is outside "dry run writes nothing".
- **Contracts read (existing).** 3a: `GET /livez`; `GET /admin/accounts` (`accounts[]` with `platform`,
  `has_session`, `session_dead_at`, `is_active`; `watchers[]`); `GET /admin/vault-ai/cache/summary` (`count`,
  `complete`, `running`, `last_run`); `POST /admin/vault-ai/collect`, `GET .../collect/status`, `POST
  .../collect/continue`; `GET .../describe-all/status` (`running`, `progress.{done, failed, capped, error, key_error,
  stop, aborted}`); `GET /admin/stats/grok-calls?by=purpose_model&status=all&from=<day>` (report only:
  `cost_millicents` per purpose / provider). 3b: `GET /admin/vault-ai/items` paged at 1,000 (live ids); `GET
  /admin/saved-replies` (rows, `removed_media_ids`); `GET /admin/vault-ai/thumb` for the contact sheet.
- **Contracts read (Phase 1).** 1a, for 3a: `POST /admin/vault-ai/describe-all {account_id, target}`, `GET
  .../describe-all/plan?target=` (`cap.{spent_millicents, cap_millicents, capped, key_missing}`, `jev.{ready,
  reason}`, `target_remaining`, `coverage{target, describable, described, terminal, goal, remaining}`). 1b, for 3b:
  `POST /admin/saved-replies/fill/plan?account_id= {sequence}` (FillPlan with `options[].{id, media, previews,
  price_cents, price_fixed, flags}`, `flags`, `fingerprint`), `fill/apply {sequence, fingerprint}` (409 `stale` +
  fresh plan; returns `applied` and `undo`: `UndoEntry {id, media_ids, previews, price_cents, price_set}`, where
  `price_cents` is the row's price after apply and `price_set` says Fill wrote it), `fill/undo {sequence, undo}`
  (`undone`, `kept[{id, reason}]`).
- **Roster** (3a). `eligible`: in `accounts[]`, `platform == onlyfans`, `has_session`, no `session_dead_at`,
  `is_active`; reasons `watcher`, `not_onlyfans`, `no_session`, `dead_session`, `deactivated`. Never chased (memory:
  skip disconnected models). Read once per run and journaled (`roster`); a Creator that turns ineligible mid-run is
  caught by its next sweep failing (open, no-progress rule) or by the next run's roster. `/admin/accounts` silently
  drops the dead / deactivated marks when its health read fails (`service/accounts_admin_api.py:283`); the driver
  cannot see that, and the cost is bounded by the no-progress rule.
- **Measure** (3a). Read-only. Needs Phase 1a on the relay (wave 1 ships 1a with 3a); a plan route without
  `target_remaining` is a refusal, exit 2.
- **Collect** (3a). For a Creator with `complete` false: at most one Collect per run (journal `collect` line). Start
  it, poll status every 10 s, answer each pause with `continue` (pauses come every 2,000 new items and stop the walk if
  unanswered for 30 min, `service/vault_ai_api.py:269`), wait for the end, re-read `cache/summary`. Still `complete`
  false (a page-capped walk, `service/vault_runs.py:68`) → the Creator is worked on what the mirror holds, and is open
  with `mirror_incomplete` unless it reaches target 1,000.
- **Describe wave** (3a). Up to `--slots` (default 3) Creators sweep at once, picked in roster order; the claim is per
  account (`service/vault_ai_vision.py:1043`) while vision calls share one global gate of 8
  (`vault_ai_vision.py:233,243`), so 3 sweeps do not triple throughput; the report measures it. Per Creator: `goal` =
  Phase 1's `coverage.goal` at target 1,000; `t = next_target(described, goal)` = the next multiple of 250 above the
  described count, capped at `goal`; read `target_remaining` at `t`; 0 at `goal` → done; 0 below → raise `t`; else
  read the cap, check the ceiling, POST describe-all with `target: t`, journal `sweep_start {t, before, cap_before}`.
  Every 10 s the driver polls each running sweep; on `running: false` it reads the cap again, journals `sweep {t,
  before, after, progress, cap_before, cap_after, started, ended}`, recounts, and frees the slot for that Creator's
  next step or the next Creator. `sweep_outcome`: 429 `daily_cap_reached`, `progress.capped`, or `progress.error`
  naming `jev_capped` with fewer described after than the sweep's slice → `defer` until next 00:00 UTC; 424 /
  `key_error` → open `key`; `jev.ready` false before a sweep → open `jev_not_ready`; two sweeps in a row that add no
  described item → open `no_progress` (with `progress.error`/`stop`). A 409 on start means a sweep runs: await it in
  that slot.
- **Fleet ceiling** (3a). At the first live `describe` the journal records `run_start {ceiling_mc, eligible}`. Spend
  is measured per sweep from the Creator's Describe cap ledger (`cap.spent_millicents`, which pools DeepInfra describe
  and TypeSafe Jev, settles real cost including failed calls, `service/llm_client.py:1257`): `sweep_spend` = after −
  before on the same UTC day; across 00:00 UTC, after + max(0, cap − before) (an upper bound: the cap stopped the old
  day's spend there). Run spend = sum of journaled sweep spends, so it survives days and resumes. A sweep starts only
  if `spent + (running + 1) × 250 × item_mc <= ceiling`, each running sweep reserved at its estimate until its real
  spend is journaled; else no new sweep, and once the running ones end, pause `ceiling`. This is a soft stop: the
  accepted sweeps can overshoot by at most the running Creators' remaining Describe caps for the day (≤ 3 of them),
  because the server's cap stops each. Other describe spend on that Creator during a sweep is counted too
  (conservative). Default ceiling 200 cents × Eligible Creators.
- **Pauses** (3a). `/livez` non-200 or slower than 2 s; 3 consecutive 5xx / transport errors; the same
  `progress.error` class on two Creators in a row; `jev.ready` false on two Creators in a row (box-wide); ceiling.
  Pause = no new sweep or apply starts, running sweeps are awaited and journaled, then journal `pause {reason}`, exit 3;
  nothing is left half-written because the driver never writes outside one route call.
- **Report** (3a; 3b adds Fill columns). Per Creator: state or skip / open reason, mirror complete, describable,
  described before / after, Terminal failures (Phase 1's `coverage.terminal`), spend by provider, sweep wall minutes
  and described items per minute (`throughput`: described added ÷ (ended − started) per sweep, summed per Creator and
  run; parallel sweeps' overlapping minutes are counted once for the run figure). 3b adds Sequences eligible / filled
  / skipped by reason, non-blocking flags, and fill rate (filled ÷ eligible Sequences on Creators at their goal) at
  the top, so the premise stays visible. Deferred and open Creators listed as open, not done. Full report beside the
  journal. `sanitise` relabels Creators `C01..` (ordered by sha256 of the id) and drops ids, usernames, nicknames and
  Sequence names; written to `--out` (default `.scratch/script-fill-content/rollout-report.md`). 3b: `--sample N
  --seed N` writes a host-only `sample.html` contact sheet (thumbs inlined as data URIs) of N seeded filled Sequences;
  on a one-Creator run it is the canary sheet.
- **Journal.** JSON Lines, append-only, file mode 0600, default `~/script-fill-rollout/journal.jsonl` on the host. No
  lock: one operator runs one driver (SH-4). 3a kinds: `run_start`, `roster`, `skip`, `measure`, `collect`,
  `sweep_start`, `sweep`, `defer`, `open`, `pause`, `report`. 3b kinds: `plan`, `stale`, `backup`, `apply_intent`,
  `apply`, `readback`, `undo`. Every line: `t`, `mode`, `creator`, optional `sequence`. Holds ids; never copied into
  the repo.
- **Apply gate** (3b). `apply_gate` returns `[]` or reasons: `status:<status>`, `media_not_live`, `step_order` (an
  Option's `step` below the previous Option's in plan order), `preview_not_media` (a preview not among its Option's
  media, or on a free Option), `price_unsendable` (paid price outside 300–20,000 cents; free and chat Options may be
  0), `escalation` (on successive paid Steps, the highest price of one above the lowest of the next). Plan flags
  `gap`, `kept_existing`, `kept_unpriced`, `removed_media` and `free_unfilled` never block (Phase 1 stories 8, 12 and
  22: flagged, not blocking); they are listed per Sequence in the report. The gate runs again on every fresh plan
  (409). It never edits a plan.
- **Backup** (3b). Live apply requires `--backup PATH`: the file exists, is under 6 h old, opened `mode=ro` it passes
  `PRAGMA integrity_check` = `ok`, has `saved_replies` and `vault_items` tables, and holds every row id in the gated
  plans' write set with the media, previews and price the journal's before rows show (so a restore brings those rows
  back; an empty or wrong file fails, since `integrity_check` alone says `ok` on an empty DB). A copy taken
  in-container per the ae-deploy procedure; the driver never opens the live DB. Journal records path, size, sha256.
- **Apply** (3b). Per gated plan, one at a time: journal `apply_intent {sequence, fingerprint, before rows, write
  set}` (write set = the plan's Options with media whose before row has none; a `free_unfilled` Option is not in it);
  call apply with the fingerprint; journal `apply {undo, applied}`; re-read the Scripts list; `readback` →
  `readback ok|mismatch:<reasons>` where reasons are `undo_short` (a write-set id missing from the Undo list),
  `values` (media ids, previews or price differ from the plan, or an Undo entry's `price_cents` differs from the row's
  price now, or its `price_set` is not exactly "before price 0 and the Option paid") and `removed_media`
  (`removed_media_ids` not empty).
- **Lost response** (3b). On resume, an `apply_intent` with no `apply` line → re-read the Scripts list: write-set rows
  still empty → the apply never landed, re-plan; rows equal to the intent's plan → `reconstruct_undo` builds Phase 1
  `UndoEntry`s from the intent (media and previews now, `price_cents` = price now, `price_set` = before price 0 and the
  Option paid) and journals `apply {reconstructed: true}`; rows that differ from the plan → `uncertain`, listed, never
  undone automatically.
- **Undo** (3b). Newest apply first, skipping ones already journaled `undone`; Undo lists sent verbatim; journal
  per-row results, `kept` rows `left` with their reason.
- **Watch `script_fill_coverage`** (3b). SQL per account with live `vault_items` rows and no `account_health` dead or
  deactivated mark: describable (`kind IN ('photo','video')`, `removed_at IS NULL`), described (`describe_status =
  'described'`), terminal (not described and `describe_status IN ('refused','blocked_drm','gone')`, or
  `json_extract(ai_fields_json,'$._jev.status') = 'ok' AND json_extract(ai_fields_json,'$._jev.review') =
  'fetch_failed'`, the terminal held blob, `service/vault_jev_pass.py:109`, matching Phase 1's `is_terminal`), and the
  latest `describe_generated_at` among described rows only (a failed attempt also stamps it,
  `service/vault_ai_vision.py:775`). Goal = min(1000, describable − terminal). ok: none short; watch: short Creators
  all described something in 26 h; alert: one short with nothing new in 26 h. Detail `id8 described/goal`.
- **Watch `script_fill_readback`** (3b). SQL over `saved_replies` with media, `updated_at >= :cut` (merge time of the
  3b PR, the `free_gaps` precedent), `script_id` not reserved (`GLOB 'FM[0-9]*'` and not `'FM*[^0-9]*'`): media ids
  (`json_each`) without a live `vault_items` row of that account, or `price_cents` in 1–299 or above 20,000. Only those
  two (SH-4). It covers every media row touched since the cut, Fill-written or hand-edited, since either is
  unsendable. Any row → alert, detail `id8 script#step reason`.
- **Schema.** None. No migration, no table; the journal is a host file.

## Testing Decisions
- **Seam 1, `rollout_decide` tables** (`test_script_fill_rollout.py`, pytest, venv). 3a: roster reasons;
  `next_target` (0, 1, 249, 250, 344, 999, 1000+, goal below 1,000); `sweep_outcome` per branch (cap 429, `capped`,
  `jev_capped`, key, Jev not ready, one and two zero-progress sweeps); `sweep_spend` same day and across 00:00 UTC,
  `run_spend` over days; `may_sweep` edges with 0, 1, 2 running sweeps reserved; every pause rule fires and stays quiet
  below threshold; `throughput` with overlapping sweeps; `resume` from journals cut after each 3a kind (done, deferred
  before / after its time, sweep in flight in one of three slots); `sanitise` output has no id, username, nickname,
  Sequence name or run of 6+ digits. 3b: Apply gate per reason incl. branch Steps, chat Steps between paid ones, free
  Option at 0, `free_unfilled` not blocking, $3 / $200 edges, non-blocking flags; `readback` per reason incl. a Fixed
  price (entry `price_cents` = Fixed price, `price_set` false: ok), a Fill-set price (`price_set` true: ok), a wrong
  `price_set` (`values`) and a short Undo list (`undo_short`); `reconstruct_undo` (landed with Fill-set and Fixed
  prices, not landed, differs → uncertain); `resume` with `apply_intent` without `apply`, apply without readback.
- **Seam 2, slop `script-fill-rollout`** (guarded stack, `lib/vault_describe_relay.py` + `lib/vault_jev_relay.py`
  arms, `lib/vault_wire.py` fake vault). Master + two Agencies, four seeded Creator kinds (SH-4):
  **A** complete mirror partly described, one Sequence with a valid Fixed price on a paid Step, one Sequence name
  shared with B (Agency 1); **B** empty mirror (Collect with one pause), one Sequence with a Fixed-price conflict, the
  shared Sequence name (Agency 2); **C** page-capped mirror; **D** dead session. Watcher and other roster reasons stay
  in Seam 1. The driver runs as a subprocess over loopback HTTP with real sign-in. 3a checks: `ROLLOUT_DRY_RUN` (dry
  run of every 3a mode leaves `vault_items`, `vault_cache_runs`, `saved_replies`, `grok_calls` and `grok_daily_cost`
  unchanged); `ROLLOUT_ROSTER` (D skipped with its reason); `ROLLOUT_COLLECT` (B's pause answered, ends `complete`;
  C ends open `mirror_incomplete`); `ROLLOUT_DESCRIBE` (A, B, C sweep in parallel with `--slots 3`, each reaches its
  target in 250 steps, recount matches the DB, report shows items/minute); `ROLLOUT_STOPS` (Jev arm not ready → open
  `jev_not_ready`, no loop; low ceiling → exit 3 before a sweep; cap armed → defer, exit 4); `ROLLOUT_RESUME` (kill
  mid-wave, re-run awaits running sweeps and starts no second sweep for a done Creator); `ROLLOUT_REPORT` (sanitised
  report has no ids). 3b checks: `ROLLOUT_GATE` (plan + gate list every Sequence with a status; B's conflict
  refused); `ROLLOUT_BACKUP` (apply refuses without backup and with an empty backup); `ROLLOUT_READ_BACK` (apply
  writes match the journal, A's Fixed price kept); `ROLLOUT_LOST_RESPONSE` (journal cut after an `apply_intent`, its
  `apply` line removed, reconciled on re-run with a reconstructed Undo list); `ROLLOUT_ISOLATION` (the shared Sequence
  name filled on A and B each from its own vault only); `ROLLOUT_UNDO` (every filled row back to empty, A's Fixed price
  kept). FAULT `rollout-undo-list-short` (Phase 1's apply returns an Undo list missing its last Option) targets
  `ROLLOUT_READ_BACK` and `ROLLOUT_UNDO`; it lands with 3b.
- **Seam 3, `test_watch.py::test_watch_check_states`** (3b) rows for both checks (ok / watch / alert / unknown), kept
  honest by `test_watch_checks_declared_in_one_place`; plus `test_script_fill_coverage_sql_on_sqlite` and
  `test_script_fill_readback_sql_on_sqlite` that run each `WATCH_SQL` query on a temp SQLite under the read-only
  authorizer (the `test_view_lease_sql_on_sqlite` precedent, `scripts/proxy-health/test_watch.py:816`), including a
  terminal held clip, a failed attempt newer than the last describe, a dead price and a gone media id.
- Prior art: `scripts/proxy-health/test_watch.py`; `slop/scenarios/2026-11-01-vault-describe-sweep.py` (arms, poll
  loop); `slop/scenarios/2026-11-05-vault-collect.py` (fake vault); `scripts/prod-feet-folders.sh` (dry run default).

## Acceptance
3a (wave 1, ships with Phase 1a):

```sh
set -euo pipefail
# slop runs go through the slop-runner agent
venv/bin/python -m pytest scripts/script-fill-rollout -q
python3 -I scripts/script-fill-rollout/rollout.py --help >/dev/null
if grep -En '^\s*(import|from) +(httpx|requests|sqlalchemy|fastapi|db|service)\b' \
     scripts/script-fill-rollout/rollout.py scripts/script-fill-rollout/rollout_core.py \
     scripts/script-fill-rollout/rollout_fill.py scripts/script-fill-rollout/rollout_decide.py; then exit 1; fi
rc=0; python3 -I scripts/script-fill-rollout/rollout.py measure --relay https://example.com || rc=$?
test "$rc" -eq 2
slop/run script-fill-rollout --scale=small
RUN="$(ls -td slop/evidence/*-script-fill-rollout-* | grep -v -- -break- | head -1)"
# every check PASS, none SKIP (a SKIP leaves the run at exit 0, slop/lib/report.py:70-73)
python3 - "$RUN/invariants.json" <<'PY'
import json, sys
need = {"ROLLOUT_DRY_RUN", "ROLLOUT_ROSTER", "ROLLOUT_COLLECT", "ROLLOUT_DESCRIBE",
        "ROLLOUT_STOPS", "ROLLOUT_RESUME", "ROLLOUT_REPORT"}
checks = json.load(open(sys.argv[1]))
bad = [c["name"] for c in checks if c["status"] != "pass"]
missing = need - {c["name"] for c in checks}
if bad or missing:
    sys.exit(f"not pass {bad}, missing {sorted(missing)}")
PY
slop/run --changed
```

3b (wave 3; Phase 1b and 3a merged, fit check passed):

```sh
set -euo pipefail
venv/bin/python -m pytest scripts/script-fill-rollout -q
venv/bin/python -m pytest scripts/proxy-health -q
grep -q '"script_fill_coverage"' scripts/proxy-health/watch.py
grep -q '"script_fill_readback"' scripts/proxy-health/watch.py
slop/run script-fill-rollout --scale=small
GREEN="$(ls -td slop/evidence/*-script-fill-rollout-* | grep -v -- -break- | head -1)"
slop/run script-fill-rollout --break --baseline="$GREEN"     # must print CAUGHT
python3 - "$GREEN/invariants.json" <<'PY'
import json, sys
need = {"ROLLOUT_DRY_RUN", "ROLLOUT_ROSTER", "ROLLOUT_COLLECT", "ROLLOUT_DESCRIBE",
        "ROLLOUT_STOPS", "ROLLOUT_RESUME", "ROLLOUT_REPORT", "ROLLOUT_GATE", "ROLLOUT_BACKUP",
        "ROLLOUT_READ_BACK", "ROLLOUT_LOST_RESPONSE", "ROLLOUT_ISOLATION", "ROLLOUT_UNDO"}
checks = json.load(open(sys.argv[1]))
bad = [c["name"] for c in checks if c["status"] != "pass"]
missing = need - {c["name"] for c in checks}
if bad or missing:
    sys.exit(f"not pass {bad}, missing {sorted(missing)}")
PY
slop/run --changed
```

## Depends on
- 3a: Phase 1a — describe-all `target` and the plan route's `target_remaining` and `coverage` (incl. `goal`,
  `terminal`). Existing, unchanged: `progress.error` names a `jev_capped` item failure
  (`service/vault_ai_vision.py:764`), `jev.{ready, reason}` (`service/vault_jev_pass.py:281`), per-account describe
  claim (`vault_ai_vision.py:1043`).
- 3b: 3a; Phase 1b — `fill/plan`, `fill/apply` (fingerprint, `409 stale`, `UndoEntry {id, media_ids, previews,
  price_cents, price_set}`), `fill/undo`; the fit check passed (plan review › Workstreams). Phase 2 is not needed.

## Out of Scope
- The live AE run itself (deploy, canary, waves, owner taste review, the fit check): owner- or coordinator-ordered
  execute stage, outside these floors and outside this Phase's acceptance.
- An "all Creators" relay endpoint: rejected in issue 06; the driver uses product routes.
- Raising Describe caps or keys: caps stay as configured (issue 06 item 6).
- Taking the DB backup inside the driver: the ae-deploy in-container backup exists; the driver only verifies it.
- Running in the container, a scheduler or daemon: a shell loop re-runs the driver on exit 4 (YAGNI).
- A journal lock (flock), a pre-Phase-1 `measure` mode, a median-latency pause, re-reading the roster before every
  Creator: cut in plan review (SH-4).
- More than 3 parallel sweeps: the server's 8 vision slots are shared by every sweep, so more slots add contention,
  not throughput; the report's items/minute is the evidence to revisit.
- Owner approval gate before apply: issue 06 ASSUMPTION (auto-apply); the wave can be stopped after `plan`.
- A machine fill-rate threshold or fill quality judging: the owner alone judges (memory: owner judges reply quality);
  the report puts the fill rate first.
- Telling Fill-written rows from hand edits in the read-back watch, and checking previews there: it needs the host
  journal, which the sweep cannot read; gone media and unsendable prices are the two broken states (SH-4).

## Further Notes
Execute-stage runbook (owner-ordered, not acceptance; issue 06 item 3 order, re-cut by the plan review's waves):
wave 1 — `python3 -V` on the AE host (3.10+); ship 1a + 3a (deploy); `measure`; canary `--creator` describe;
restate `--ceiling-cents` / `--item-mc` from the canary's sweep spends; start the describe wave (shell loop on exit
4). Wave 2 — ship 1b; the coordinator's fit check on the Creator at ~1,000 described. Wave 3 — ship 3b + Phase 2;
canary `--creator` (plan, backup, apply, `--sample`); `plan` for everyone; backup; `apply`; `report`; move
`~/oi-proxy-health` to a main holding both checks and confirm they plan as `run`; then one WATCH.md line per check
(+ `vault_jev_errors`, `ai_spend_vs_cap`, `user_p95_vs_baseline`) with the PR URL.

Decided (rung 1): the plan route takes `target` as a query parameter — Phase 1 spec contract
`describe-all/plan GET ?target=`.
Decided (rung 1): concurrent sweeps on different Creators are allowed by the server — the describe claim is per
account (`service/vault_ai_vision.py:1043`) and vision calls share one global gate of 8 (`:233,243`).
ASSUMPTION: thresholds — `/livez` 2 s, 3 consecutive errors, 26 h stall, two zero-progress sweeps — are guesses
(rung 6); overturned by the canary's measured latencies and sweep outcomes.
ASSUMPTION: 3 parallel sweeps by default (coordinator ruling 4, cap 3); the run figure in the report may show 3 slots
no faster than 2 under the shared vision gate; overturned by the canary's items/minute, then `--slots` is lowered.
ASSUMPTION: `--item-mc` defaults to 20 millicents per item (rung 4, above the 7 mc photo estimate, clips cost more);
overturned by the canary's measured cost.
ASSUMPTION: backup must be under 6 h old (rung 4); overturned by the owner naming another window.
ASSUMPTION: the sanitised report goes to `.scratch/script-fill-content/rollout-report.md` (rung 3: effort facts live
there, `.scratch/` never deploys); overturned by the owner naming a docs path.
ASSUMPTION: `script_fill_coverage` cannot see `has_session` or watcher role (on-disk meta, not in the DB); it relies on
watchers having no vault rows and `account_health` marks (rung 5); overturned if a watcher shows vault rows.
ASSUMPTION: a Jev cap is read from `progress.error` naming `jev_capped` (rung 3: the sweep publishes its first item
error there; no structured field exists); overturned by a Phase 1 or later field carrying item-status counts.
ASSUMPTION: a page-capped mirror under 1,000 described is open `mirror_incomplete`, not done (rung 4: open is
reversible, done hides it); overturned by the owner accepting capped mirrors.
ASSUMPTION: with no journal lock, two drivers on one journal are prevented only by the operator (coordinator ruling 4);
a second shell could double the spend up to the ceiling check's view; overturned by a double-run incident, then the
lock returns.
ASSUMPTION (evidence blocked): the AE host's python3 version is unread (floor 2); stdlib-only and 3.10 syntax assumed;
overturned by `python3 -V` on the box.
Decided (rung 1): sign-in over loopback needs no share token — `/auth/` is in `_PUBLIC_PREFIXES` and the gate passes
any session cookie (`service/server.py` `_share_token_gate`); `/admin/*` refuses an anonymous caller
(`auth.assert_account_owned`), hence the Master session.

## Review
codex · 2026-11-21 · blind call (B) + draft call (D), both exit 0, outputs non-empty.

- B1 alternatives (manual, approve-then-apply, relay job; prod-feet runs in-container) — **reject**: issue 06 item 1 binds the host driver over product routes; prod-feet is cited only as the dry-run-default precedent; approve-first is issue 06's ASSUMPTION, kept in Out of Scope.
- B2 roster: Master check, health-read fallback, Fansly `has_session` — **partial**: Master already required, Fansly excluded by `platform`; added per-Creator roster re-read; the silent fallback (`accounts_admin_api.py:283`) is not visible to a client, cost bounded by the new no-progress rule (Roster).
- B3 Collect pauses / capped walk can end "done"; require `complete` — **accept**: one Collect per run, pauses answered, `complete` re-read, page-capped → open `mirror_incomplete` (Collect, story 9, Seam 2).
- B4 one terminal-aware count; Jev holds; zero-progress rule — **accept**: goal and Terminal failures come from Phase 1's `coverage`; watch SQL counts the terminal held blob; two zero-progress sweeps → open `no_progress` (Describe wave, Report, Watch coverage).
- B5 pre-sweep check lets a sweep overshoot; baseline across days; audit rows can be missing — **accept**: spend now from the Describe cap ledger before/after each sweep (pools both providers, settles failed calls), summed in the journal across days; stated as a soft stop whose overshoot is bounded by that Creator's remaining cap (Fleet ceiling, story 15).
- B6 commit then lost response leaves `already_filled` without Undo — **accept**: `apply_intent` journaled before the POST; resume reconciles by read-back, reconstructs the Undo list or marks `uncertain` (Apply, Lost response).
- B7 Undo would zero a kept $20 price — **partial**: false against Phase 1 (`UndoEntry.price_cents` null keeps the saved price, phase-01 spec Undo); added a successful Fixed-price fill + undo to Seam 2.
- B8 gate: $0 for free/chat, decide `gap`/`kept_unpriced`/`removed_media`, re-gate fresh plans — **partial**: price check was paid-only already, now explicit; flags declared non-blocking and listed (Phase 1 stories 12, 22); re-gate on every fresh plan stated. Composer step N+1 gap is Phase 1's `gap` flag, not a gate reason.
- B9 thresholds / missing data / `/livez` liveness only / feed run data to watch — **partial**: missing data is already `unknown` by watch precedent; pause also uses request latency and errors; the sweep cannot read the host journal, so watch stays DB-only (Out of Scope line added).
- B10 test the real CLI on loopback with shared Sequence name, kill-after-commit, Fixed-price undo — **accept**: all three added to Seam 2 (journal cut after `apply_intent` stands in for kill-after-commit deterministically).
- B11 fit premise unproven; all-skipped satisfies done — **partial**: fill rate added at the top of the report so the canary falsifies it; no machine threshold (owner judges, issue 06 item 11).
- B12 cost falsifier; issue 07 sizes parallel, issue 06 serial — **partial**: canary sweep spends restate the ceiling (already); serial walk defers capped Creators and moves on, so it is throughput-bound, not cap-bound (Out of Scope, parallel line).
- D1 committed Fill can lose its Undo record — **accept**: same rewrite as B6.
- D2 read-back passes with a short Undo list — **accept**: read-back compares the reviewed write set; a missing id is `undo_short` (Apply, `readback`), so the FAULT is caught by its own denominator.
- D3 Fixed-price read-back compares the null Undo price — **accept**: price compared to the plan's `price_cents`; Seam 1 row and Seam 2 Creator with a valid Fixed price.
- D4 Jev cap signal missing (`jev` = `{ready, reason}`, `jev_capped` is an item status) — **accept**: verified (`vault_jev_pass.py:178,281`); defer reads `progress.error` naming `jev_capped`, Jev not ready → open, box-wide pause on `jev.ready` false; Depends on lists both as existing; ASSUMPTION added.
- D5 `status=done` understates spend; estimate not a hard ceiling — **accept**: ceiling no longer reads `grok-calls`; report uses `status=all`; soft stop stated (same rewrite as B5).
- D6 dry run writes `last_seen_at` on sign-in / GET — **accept**: verified (`account_security.py:259`, `auth.py:675`); "writes nothing" redefined as no product-state write, the slop check names the product tables.
- D7 `integrity_check` is `ok` on an empty DB — **accept**: backup must also hold the tables and every write-set row with its before values; Seam 2 adds the empty-backup refusal.
- D8 Collect can pass without completeness — **accept**: same rewrite as B3; Seam 2 asserts the pause and `complete`.
- D9 coverage watch omits Jev holds; failed attempts refresh the timestamp — **accept**: verified (`vault_ai_vision.py:775`); terminal held blob counted, progress time from described rows only; roster limits stay an ASSUMPTION.
- D10 read-back watch also covers hand edits; its SQL is never executed by tests — **partial**: hand-edited broken rows are equally unsendable, scope stated (Watch readback, Out of Scope); SQL-on-SQLite tests added per `test_watch.py:816`.
- D11 WATCH.md lines before the sweep worktree has the checks get dropped — **accept**: verified (`watch.py:1408`); runbook moves `~/oi-proxy-health` first and checks `run`.
- D12 manual acceptance includes the live run and puts deploy before measure — **accept**: manual lines removed from Acceptance; runbook in Further Notes follows issue 06's order (measure → ship → canary); `measure` runs on a pre-Phase-1 relay.

### Six hats (plan review, 2026-11-21)

Reconciled from coordinator rulings on the six-hats report (`/tmp/sfc-sixhats.txt` was absent when this pass ran;
bullets named by ruling). Set-level lines: `docs/spec/plan-review-script-fill-content.md`.

- SH-1 Undo contract drifts (this spec read a null `price_cents` for a kept saved price) — **accept** (ruling 1):
  Contracts, Apply `readback`, Lost response `reconstruct_undo`, Seam 1 and Depends on now use Phase 1's
  `UndoEntry {id, media_ids, previews, price_cents (after apply), price_set}`; null-price semantics removed.
  Supersedes B7's and D3's null-price wording (their fixes stand: Fixed price kept, price compared to the plan).
- SH-2 re-cut and order — **accept** (ruling 2): 3a (measure, collect, describe, report; needs only 1a) ships in
  wave 1; 3b (plan, apply, undo, apply journal, Apply gate, read-back, watch checks) in wave 3 after 1b and the fit
  check. Stories grouped, decisions, seams, Acceptance and Depends on labelled; runbook re-cut by wave. The journal
  is split by kind: describe kinds in 3a (resume and Fleet ceiling need them), apply kinds in 3b — **partial** on
  "journal in 3b", reason: 3a's resume and ceiling are computed from journaled sweeps.
- SH-4a flock — **accept** (ruling 4): story 19 cut, lock and its exit-2 reason removed; ASSUMPTION records the cost.
- SH-4b `pre_phase1` measure mode — **accept** (ruling 4): 1a ships with 3a, so `measure` refuses a relay without
  `target_remaining`. Supersedes D12's "measure runs on a pre-Phase-1 relay".
- SH-4c median-latency pause — **accept** (ruling 4): removed from Pauses, story 17, Seam 1 and the thresholds
  ASSUMPTION.
- SH-4d roster re-read before every Creator — **accept** (ruling 4): roster read once per run. Supersedes B2's
  "per-Creator roster re-read"; the no-progress rule still bounds a Creator that turns ineligible.
- SH-4e slop scenario too big — **accept** (ruling 4): four seeded Creator kinds (A–D); watcher and other roster
  reasons stay in Seam 1; every Seam 2 behaviour kept by folding cases onto A and B.
- SH-4f `script_fill_readback` scope — **accept** (ruling 4): only gone media and unsendable price on filled rows;
  previews check dropped (the Apply gate still checks previews before writing).
- SH-4g describe throughput unknown — **accept** (ruling 4): report records sweep items/minute per Creator and run.
- SH-4h one Creator at a time is too slow — **accept** (ruling 4): up to 3 parallel sweeps (`--slots`, default 3),
  ceiling reserves running sweeps, pause awaits them; Out of Scope's serial line replaced. Supersedes B12's "serial
  walk".
- SH-4i Acceptance can pass broken — **accept** (ruling 4): both blocks `set -euo pipefail`, every named check PASS
  and none SKIP via `invariants.json`; the `test $? -eq 2` and `! grep` lines rewritten because under `set -e` the
  first aborts on the expected exit 2 and the second never fails (bash exempts `!` pipelines from `set -e`).
- SH-7 story count — **partial** (ruling 7): only story 19, which the flock cut removes, is cut; stories 6, 10, 17,
  18, 27 and 32 reworded by the cuts above.
