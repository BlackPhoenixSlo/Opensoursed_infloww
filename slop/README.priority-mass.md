# slop/: Priority mass message at its 5,000-fan cap

Smart Messages' Priority mass message (`service/priority_mass_api.py`, `automations/priority_mass.py`): one direct
message per fan of a frozen audience, sent at most once even when the relay dies mid-send, stoppable, and refused
when its text holds a Sensitive word. The harness, its knobs and its rules are in `README.md`; this file is only
what this flow adds. The scenario's docstring is its spec (the oracle, bypasses, the UI run's expected traceback).

## Layout

| Path | Role |
|---|---|
| `lib/priority_mass_relay.py` | Inert unless the scenario writes its files under `$DEMO_SHOTS_TMP`. `of-rosters.json` (OF's custom lists per Creator) feeds `lib/automation_relay.py`'s offline walker lists, which the leg's freeze reads (at wire, so a restarted relay has them, and on `POST /__slop/priority-mass/rosters`). `of-pm.json` (`{write_gap_s, hang: {"<account>:<fan>": hang_s}}`, read on every call): OF's record of every send it took, `of-pm-sends.jsonl` (one O_APPEND write each, outlives a SIGKILL; `read_sends`); a hung send for the crash leg; the per-Creator 11 s write gap compressed to `write_gap_s` (the gate itself is the product's). Legs run through `POST /__slop/run-automation {kind: priority_mass, claim: true}`. |
| `lib/priority_mass_faults.py` | The check names and its faults (below), each patching the product function whose bug class it names (one the composer's served JS). |
| `seed/priority_mass_audience.py` | `seed(w, sizes, priced=)`: per Creator a pool (its seeded fans plus roster fans up to the size, 80% with a `fans` row), OF lists (2 include, 1 exclude, and OF's `MASSDMEXCLUDE`, drawn from the first include list; returned, the scenario writes them), local exclusions (MASSdmEXCLUDE members, blacklist rows, for a priced Creator fans who bought its media) and the contact guard's recent history. Deterministic (`w.rng("priority_mass_audience")` and its `:massdm_of` stream); returns per Creator `pool`, `no_row`, `lists`, `include`, `exclude`, `massdm_of`. |
| `scenarios/2026-11-01-priority-mass-5k.py` | The scenario; its `_frozen_oracle` (the audience a freeze must hold, from the seed). |

## Scenarios

- `2026-11-01-priority-mass-5k`: `agency_inbox` plus `seed/priority_mass_audience` for Creators A (roster big
  enough at medium that the 5,000 cap bites; priced $5 with media), B and C; the real supervisor runs
  (`SLOP_SUPERVISOR=1`, its boot heal is the crash path). Sensitive words added and imported (an .xlsx) through the
  real routes; four texts holding them posted on C (-> 4xx with the block message); runs A, B, C launched, A posted again at once (->
  409); one leg driver per run; `--users` owners poll `GET /admin/priority-mass/runs`. B is cancelled after OF
  took 15 of its fans; A's fan at 40% hangs at OF, the relay is SIGKILLed and restarted on the same DB, the boot
  heal awaited, `/resume` on A and B, every run driven to its end. Leg scan: while A's hung leg holds its run lock,
  a clean run S is posted on A, then `SCAN_WORD` is added through `POST /admin/sensitive-words/add`; S's first leg
  runs only after the restart. With UI: Priority mass messages shows A's sent
  count (`smart-messages-1-priority-tab`, `smart-messages-2-run-settled`) and Sensitive words' Add dialog adds a
  word (`sensitive-words-1-add-dialog`, `sensitive-words-2-saved`), then New Message > Priority mass message 'Post
  as' B: OF's MASSDMEXCLUDE pre-ticked in Exclude (`priority-mass-ui-1-massdm-preticked`), Send, the run driven to
  Done (`priority-mass-ui-2-run-settled`; the composer's `GET /api/of/v2/lists` answered at the browser's wire).
  Checks (`lib/priority_mass_faults.py`):
  `FROZEN`, `ONCE`, `ROWS`, `CRASH`, `SETTLED`, `CANCEL`, `REFUSE`, `REPEAT`, `RESUME`, `LEG_SCAN` (S stops at its
  first leg naming the word, none sent by OF), `UI_SEED` (UI run only: the POST, run row and frozen fans exclude
  OF's MASSDMEXCLUDE); the scenario's "legs: no
  5xx, a transport error only for the leg in flight at the SIGKILL", "UI: Priority mass messages lists A's run
  with its sent / total as the DB counts" and "UI: a word added in Sensitive words' Add dialog is listed and
  refuses a run"; budget `p95 GET /admin/priority-mass/runs`, plus it and A's leg time per fan sent vs the last
  green run, all in the scenario. Faults: `pm-claimed-row-resent-after-crash` (default; targets `ONCE`, `CRASH`),
  `pm-cancel-keeps-pending` (`CANCEL`), `pm-sensitive-word-ignored` (`REFUSE`), `pm-leg-exact-scan-only` (the
  leg's `sensitive_hits` finds nothing; `LEG_SCAN`), `pm-ui-no-massdm-seed` (client: the composer's MASSDMEXCLUDE
  seed reverted; `UI_SEED`, UI run only). Knobs: `--roster_a=` A's roster
  (SCALES `priority_mass_roster_a`), `--poll_s=` (5 s).
