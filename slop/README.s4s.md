# slop/: Share for Share requests

Share for Share (`service/s4s_requests_api.py`, `s4s_schedule_api.py`, `s4s_api.py`'s Discovery and blocks) under
racing owners on both sides, in the slop harness. The harness, its knobs and its rules are in `README.md`; this file
is only what this flow adds. The scenario's docstring is its spec (load plan, bypasses, guesses).

## Layout

| Path | Role |
|---|---|
| `seed/s4s_profiles.py` | `seed(w, creators, opted_out_frac=, blocks=)`: by SQL, as the Settings save, the posts routes and `POST /admin/s4s/blocks` leave them: an S4S profile per Creator (opted in unless drawn out, Discovery visible, Daily limit 1-3, the display fields an OF `/users/me` read stores), 1-3 posts (the first Primary), `blocks` distinct (Agency, other Agency's opted-in Creator) blocks with the Creator's projection at block time. |
| `lib/s4s_faults.py` | Every check name (`ONE_WINNER`, `SLOTS_JOBS`, `DAILY_LIMIT`, `CAP_SEQ`, `CAP_RACE`, `BLOCKED`, `AUDIT`, `SLOT_CANCEL`, `BOXES`, `SCHEDULE`, `SENDS`, `UI_ACCEPT`, `UI_PAGES`, `DISCOVER`, `PROPOSAL`), `CAP` (50, `s4s_common.MAX_SENT_PER_DAY`) and two faults patching `s4s_requests_api`. |
| `scenarios/2026-11-01-s4s-requests-race.py` | The scenario; its `_Plan` (who sends to whom on which day, from the seed only). |

## Scenarios

- `2026-11-01-s4s-requests-race`: no profile fits, so it composes `seed/agency` (`--agencies=`), `seed/creators`
  (`--creators_per_agency=` each) and `seed/s4s_profiles` (10% opted out, `--blocks=`), recorded as metric `seed`
  profile `s4s_requests`. Stage `load`, every plan from the seed: sends (every group, at most `--users` at once);
  race (`--race_groups=` requests, each answered by `--racers=` simultaneous calls: accept / decline / skip, or
  accept / decline vs the sender's cancel); limit (`--limit_targets=` Creators each get limit + 2 requests for one
  day, all accepted at once); booking (`--bookings=` accepted, then the sender's owner cancels its slot twice at
  once while the receiver's owner tries it); blocks (send and proposal both ways, Discovery, `/blocks`); cap
  (Creator S1 to 50 a day then 51 and 52, Creator S2 a `--burst=` of concurrent sends across 50); meanwhile
  `--users` owner readers, `--read_rounds=` x Requests, proposal, Schedule, Discover. Then `settle` (5 s) and `calm`
  (each `--users` owner opens Requests once within 10 s). With UI, agency 0's owner accepts on Creator U
  (screenshots `requests-trigger`, `requests-settled`, then `schedule`, `discover-creators`, `settings`). Checks
  (`lib/s4s_faults.py`): `ONE_WINNER`, `SLOTS_JOBS` (2 slots + 2 pending `s4s_post` jobs per accept, else none),
  `DAILY_LIMIT`, `CAP_SEQ`, `CAP_RACE`, `BLOCKED`, `AUDIT` (one `actions` row per transition), `SLOT_CANCEL`,
  `BOXES`, `SCHEDULE`, `DISCOVER`, `PROPOSAL`, `SENDS`, `UI_ACCEPT`, `UI_PAGES`; budgets (GET /requests p95 under
  load and idle, a load-stage ceiling, p95 vs the last green run) are the scenario's. `KNOWN_RED`: `CAP_RACE` (all
  scales) and the load-stage GET /requests budget (medium, huge) SKIP with their finding while red and FAIL once
  green. Faults: `s4s-accept-unguarded-update` (default; `_transition` without its status guard; targets
  `ONE_WINNER`, `SLOTS_JOBS`), `s4s-daily-limit-skipped` (`_limit_full` always false; `DAILY_LIMIT`, `PROPOSAL`).
  Knobs: `--agencies=`, `--creators_per_agency=`, `--blocks=`, `--race_groups=`, `--racers=`, `--limit_targets=`,
  `--bookings=`, `--burst=`, `--read_rounds=`; each defaults to SCALES `s4s_requests_<knob>`.
