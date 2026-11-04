# slop/: Follow-up drip, run slots and dispatch

The follow-up drip (`automations.send_followup`) and the scheduler it runs under (the run slot pool, the dispatch
rules), three scenarios on one world (`lib/followup.py`), in the slop harness. The harness, its knobs and its rules
are in `README.md`; this file is only what this flow adds. Each scenario's docstring is its spec (bypasses).

## Layout

| Path | Role |
|---|---|
| `lib/followup.py` | The follow-up world and tick the three follow-up scenarios share: `setup` (profile + `seed/followup_drip.py`, a fake DeepSeek key, the DM rate via the real Concurrency panel route), `payload` (the run's: no image, `limit` = fans per Creator), `tick` (one `POST /__slop/run-automation`, kind `send_followup`), `refuse_live` (SLOP_LIVE=1: every check SKIPs). |
| `seed/followup_drip.py` | Follow-up drip history by SQL: for the eligible fans (>= $1 lifetime spend) without a seeded thread, one drip case per fan, as the rows the drip and the chat would have left (`--set followup_frac=` takes a share); `seed_bad_tz_rule` (one rule whose stored `tz_offset_minutes` is "x"); `seed_kill` (the KILL phase's fresh `due1` fans). |
| `lib/followup_faults.py` | followup-drip's check names and its faults (below). |
| `lib/dispatch_tz_faults.py` | followup-drip's bad-tz check name and its fault (below). |
| `lib/run_slot_faults.py` | run-slot-pool's check names and its faults (below), each patching `run_slot_decide.decide` in the relay. |
| `lib/dispatch_faults.py` | dispatch-plan's check names and its faults (below), each patching a `dispatch_plan` helper or the shell's `_pair_busy` in the relay. |
| `lib/jobs_faults.py` | dispatch-plan's RULE_OFF check name and its fault (below), patching `run_decide.park`. |
| `scenarios/2026-10-30-followup-drip.py`, `2026-10-30-run-slot-pool.py`, `2026-10-30-dispatch-plan.py` | The scenarios. |

## Scenarios

- `2026-10-30-followup-drip`: the follow-up drip (`automations.send_followup`, its phase
  machine the pure `decide()` of `service/automations/send_followup_decide.py`) ticked on
  every Creator at once (`POST /__slop/run-automation` via `lib/followup.py`, `agency_inbox` +
  `seed/followup_drip.py`: one drip case per unthreaded eligible fan, the threaded ones a natural
  mix) while the owner's dashboard tab and `--users` more `/events` streams on its session watch
  (opened over `--set tab_ramp_s=` 20 s). Per rule: the 18 h gap, steps 1/2 at 26/64 h, the
  7-day cap, reply (26 h) vs restart (72 h) cooldowns, expiry before the sweep, the fans held;
  then LLM calls = sends = rows = recorded steps, every nudge on every tab, a second tick nudging
  nobody. `lib/automation_relay.py`'s DeepSeek fake answers the nudge prompt; SLOP_LIVE=1 SKIPs.
  Budget: the product's run time per nudge (`automation_runs`), p95 vs `TICK_PER_NUDGE_P95_MS`
  and the last green run. Fault `followup-skips-18h-gap` (`lib/followup_faults.py`: the gap and
  the second-tick checks). Then a bad `tz_offset_minutes` (one rule stored "x" by SQL, `seed/followup_drip.py`)
  beside two good rules made through the rules route, one real supervisor pass: the bad rule makes no job, each
  good one exactly one and its `next_due_at` is the next fire; fault `dispatch-bad-tz-aborts-pass`
  (`lib/dispatch_tz_faults.py`: the pre-fix raise aborts the pass) targets only that check.
  KILL, last (`README.send-once.md`): one fresh `due1` fan on each of the first 4 Creators (`seed/followup_drip.py`
  `seed_kill`); after the restart two ticks before the owner's list and Retry. Checks (`lib/send_marker_faults.py`):
  `DRIP_ONCE`, `DRIP_MARKED`, `DRIP_RETRY`, and the scenario's own KILLED. Fault `followup-sending-marker-ignored`
  (`Entry.marked` always False) turns only the three KILL checks red.
- `2026-10-30-run-slot-pool`: the run slot pool (`service/run_slot_decide.py`, Non-React #6) under
  the same world on `agency_pool` (at least 7 Creators, so more runs ask than the 4 slots at every
  scale) and two follow-up ticks on every Creator at once (`lib/followup.py`);
  `/__slop/run-automation` answers each run's `slot`, and two checks (`lib/run_slot_faults.py`)
  read them: never more runs holding a slot than `n` and the pool fills when more ask (CAP), queued
  runs granted in the order they asked (FIFO). Small (7 Creators) queues 3 per tick, medium (10) 6.
  Budget: the hook's round trip per run, p95 vs the
  last green run. `--users` changes nothing (no streams: the pool, not the fan-out). Faults
  `run-slot-fresh-runs-served-last-first` (FIFO, the scenario's) and
  `run-slot-automation-ignores-the-cap` (CAP) patch the pool's `decide()`.
- `2026-10-30-dispatch-plan`: the dispatch rules (`service/dispatch_plan.py`'s helpers and the
  executor's busy gate, Non-React #8) on the scheduler's real path, same world (`lib/followup.py`).
  The owner switches the follow-up on per Creator through `POST /admin/automation-rules` (two rules
  of the kind on every other Creator and the last), deactivates the last one (`POST
  /admin/accounts/{id}/active`), then real supervisor passes (`POST /__slop/automation-tick`,
  its `tasks`): one, a wake while its runs still queue for a slot, three more. ONE: one job per
  Creator, each active one's run spawned once and run once, the deactivated one's job pending and
  unspawned; CADENCE: each rule exactly one job over the passes (a second rule deferred, then
  once). Budget: a pass with nothing due, vs the last green run. `--users` changes nothing (no
  streams). Faults (`lib/dispatch_faults.py`): `dispatch-plan-two-jobs-per-kind` (ONE, the
  scenario's) and `dispatch-plan-ignores-cadence` (CADENCE) at any scale,
  `dispatch-plan-spawns-in-flight-pairs` (ONE) at `--scale=medium` (at small nobody waits for a
  slot, so each run claims its job at once and the wake finds no due pair to stack on: NOT
  CAUGHT there). Then RULE_OFF (`service/run_decide.py` `park`): an auto_posts rule switched off
  (`PATCH /admin/automation-rules/{id}`) while its job runs and OnlyFans refuses the post: the job
  ends `cancelled` after one attempt, nothing posted after. Fault `job-park-ignores-rule-off`
  (`lib/jobs_faults.py`).
