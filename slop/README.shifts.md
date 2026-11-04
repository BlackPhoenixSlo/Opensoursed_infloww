# slop/: Shift schedule and Clock

The Shift schedule and the Clock (`service/shifts_api.py`, `clock_api.py`, `shift_time.py`, `shifts_timesheet.py`)
under a crowd of chatters, in the slop harness. The harness, its knobs and its rules are in `README.md`; this file
is only what this flow adds. The scenario's docstring is its spec (phases, bypasses).

## Layout

| Path | Role |
|---|---|
| `seed/shift_history.py` | `seed(w, employees, creators, n=, open_n=)`: by SQL, each write with its `actions` row, `n` weekly Shift series (one Employee each, on the Creator it may work; Creator i in `TZS[i % 4]`; no two series of a Creator share a weekday x 4 h block; `RESERVED` Sunday 20:00-24:00 left free) and Clock events over the anchored window `WINDOW` [2026-10-02, 2026-11-01) UTC, which holds Berlin's fall-back (`series[0]`: a Sunday 00:00-04:00 series across it, 5 h that night); 70% of occurrences worked (80% on the Creator, 20% the agency-wide clock, 15% closed by Auto clock-out), some off-shift events, `open_n` Employees still clocked in. `occurrences(series, lo, hi)`: the Occurrence rule from its spec with zoneinfo alone, the scenario's oracle. |
| `actors/clock.py` | `Clock`: chatters on their own logins (`POST /chatter/login`, as `actors/chatter` `Crowd`); `storm(members, k)` fires `k` concurrent clock-ins per chatter, all at once; `work(m)` the top bar's day (clock-status, heartbeats with think time, clock-out, clock-in, heartbeats, clock-out); the plan from the seed, never an answer; `writes` records every clock write answered. |
| `lib/shifts_faults.py` | The check names and its faults (below). |
| `scenarios/2026-11-01-shifts-clock-crowd.py` | The scenario; its `oracle` (the Timesheet for a window from the seed's series and every clock event). |

## Scenarios

- `2026-11-01-shifts-clock-crowd`: `agency_inbox`, `--employees=` chatters (`seed/chatters`, one Creator each,
  round-robin), Time tracking on through `PUT /admin/settings/time-tracking` (auto clock-out 999 min), then
  `seed/shift_history` (`--series=`, `--open_n=`). Phase A at once: `--race_rounds=` rounds (capped at 3 per
  Creator) of `--race_n=` concurrent `POST /admin/shifts` on one Creator's free slot, and the clock-in storm
  (`actors/clock`: the `--users` chatters not clocked in by the seed each fire `--storm=` concurrent clock-ins).
  Phase B at once: the chatters' day (`Clock.work`), `--readers=` owner pools reading the Timesheet (by Employee
  and by Creator), the week list and chatting-stats, and the owner's writes (a create + PATCH scope=all per
  Creator, then `--edits=` PATCH this / following and cancel this / following on seeded series). Phase C, owners
  still reading: the cancel burst, on `--cancel_series=` other seeded series `/cancel` scope=this on every
  occurrence in [now + 1 d, now + `--cancel_days=` (84)), all at once. With UI,
  /employees/shifts and /analytics/employee-reports (`<page>-trigger` / `<page>-settled` screenshots). Checks
  (`lib/shifts_faults.py`): `RACE`, `ONE_OPEN`, `ORACLE_EMP`, `ORACLE_ACC`, `LIST_ORACLE` (incl. the 5 h fall-back
  night), `OWNER_WRITES`, `AUDIT`, `CANCEL_DATES` (every burst cancel 2xx, its date in the series'
  `cancelled_dates` and off the week list), `UI_SHIFTS`, `UI_REPORTS`; budgets (Timesheet and heartbeat p95, p95 vs the
  last green run) are the scenario's. Faults: `shift-overlap-check-skipped` (default; `_check_overlaps` says no
  clash; targets `RACE`), `timesheet-drops-open-shift` (`timesheet_rows` handed closed events only; `ORACLE_EMP`,
  `ORACLE_ACC`), `clock-in-twice-opens-two` (the schema without `uq_clock_events_open_employee`; `ONE_OPEN`),
  `shift-cancel-unlocked` (`cancel_shift` on the pre-fix unlocked session; `CANCEL_DATES`).
  Knobs: `--employees=`, `--series=`, `--open_n=`, `--race_rounds=`, `--race_n=`, `--storm=`, `--readers=`,
  `--edits=`, `--cancel_series=`; each defaults to SCALES `shifts_clock_<knob>`; `--cancel_days=` (84).
