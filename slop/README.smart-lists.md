# slop/: Smart Lists

Growth > Smart lists (`service/smart_lists_api.py`, its rules `smart_list_rules`) at 50k fans per big Creator, in
the slop harness. The harness, its knobs and its rules are in `README.md`; this file is only what this flow adds.
The scenario's docstring is its spec (flow, load, bypasses).

## Layout

| Path | Role |
|---|---|
| `seed/smart_list_facts.py` | `seed(w, creators, n=)`: the per-fan facts the rules read that no other seeder writes, by SQL: each fan's last message in / out from its thread (as the transcoder keeps them); per Creator 4 bound fans with one cleared ledger tip of exactly `LO`, `HI`, `LO - 1`, `HI + 1` cents; `n` fans tagged `whale` and `n` expired (status `expired`, expiry 1..60 days ago); `SHARED` (4) fans per Creator pair: one OF user with a fans row on two Creators, a tip and the tag on one only, its own lifetime on the other. SystemExit (INFRA) when no Creator got bound fans or no shared fan was seeded. |
| `lib/smart_lists_faults.py` | The check names `ORACLE` and `CAP` and three faults (below), each patching the relay's smart-list code. |
| `scenarios/2026-11-01-smart-lists-50k.py` | The scenario; its `ROWS` (one rule row per operator plus `between`, v1 lifetime, dates, tags, status, AND, OR, empty) and the harness SQL oracle (`_oracle`, Creator-scoped). |

## Scenarios

- `2026-11-01-smart-lists-50k`: `multi_agency_big_models` (Agency 0, the owner, holds the 3 big Creators and 2
  normal ones), `seed/earnings` (`--history_days=`, 30) and `seed/smart_list_facts`. All as the owner, real routes:
  oracle phase, `min(--users, 90)` owner tasks (5 Creators x 18 `ROWS`; ramped over `--ramp_s=` 30 s, seeded
  think `--think_s=` 5 s mean) each save a list (blank `POST`, `PATCH` to the row), preview, resolve and list it,
  against the SQL oracle (retried up to 3 times while a day threshold moves under it); solo phase, one owner on a
  quiet relay, `--solo_n=` (20) previews of the big Creators, each with a list GET; activation storm on Creator 3,
  cap (`SMART_LIST_MAX_ACTIVE`, read by Agency 4 made master by SQL) + `--storm_extra=` lists activated at once,
  then one deactivated and one 409'd one activated; create race on Creator 4, `max(2, --users)` creates of one
  name. With UI, /growth/smart-lists: Presets > "Mid spenders", Preview count (screenshot `preview-trigger`),
  Create smart list, the row searched for (`created-settled`). Checks: `ORACLE` (preview count == resolve ==
  oracle, same fan set, every row matching some fan except `empty`, and a shared fan answered differently on its
  two Creators), the readback check (every list reads back with its PATCHed name and rules), `CAP` (exactly cap
  2xx, the rest 409, the DB's active count polled every 5 ms never above the cap, `max_active` == cap, the freed
  slot reused), the race check (one 2xx, the rest 409, one row) and the UI check (the preset's count == the
  oracle, its `smart_lists` row holds the preset's rules). Budgets (preview and list p95, solo and under the
  oracle phase's owners) are the scenario's; the oracle-phase two are `KNOWN_RED` (skipped, numbers in
  `p95_owners`) at medium from 90 owners and huge from 5. Faults: `smart-list-between-exclusive-bound` (default;
  targets `ORACLE`), `smart-list-cap-read-then-write` (`CAP`; INFRA if the activate handler no longer matches its
  fork), `smart-list-ledger-org-leak` (`ORACLE`). Knobs: `--whale_fans=`, `--storm_extra=` (SCALES
  `smart_lists_<knob>`); fans per big Creator are SCALES `big_fans_per_creator`.
