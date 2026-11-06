# Slop tests — mass data + mass user actions. Read slop/README.md first.
- Fresh worktree: `slop/run --list` once links the main checkout's `venv/`, `app/` and `web/node_modules` (then `venv/bin/python` runs service tests too).
- Iterate: `slop/run <scenario> --scale=small`. Before done: `slop/run --changed` green (diffs the branch + working tree vs merge-base with origin/main; own/flow picks always run, a 15 min budget for the rest; `--budget=0` when touching shared code on purpose). Quote the run folder under `slop/evidence/`, never `latest`.
- Every `own` pick that declares `FAULT`: `slop/run <it> --break --baseline=<its green folder>` (must print CAUGHT, exit 0). Only an own/flow pick tagged `volume` also gets `--scale=medium --users=200 --no-ui`.
- `slop/run nightly` = the daily full sweep incl. medium/200 volume runs and map refresh (README "Nightly"); never hold the gate around it (each child queues itself); per task still `--changed`.
- `slop/run all` only on demand, before deploy-all, or when `--changed` picks most scenarios; `slop/run all --map` refreshes `slop/map.json` (README "Which scenarios to run").
- Stacks reuse `scripts/demo-shots/relay_guarded.py` + `fetch-guard.cjs`: temp DB, loopback only; never `service/chatterly.db` or prod.
- Fan traffic enters via `POST /__slop/of-ws-frame` (`slop/lib/relay.py`), serial per Creator like the real pump (`fan_dm.serial`, `--rate` for open-loop). Never add test hooks inside `service/`.
- Seeders in `slop/seed/` (SQL bulk, deterministic from `--seed`, only rows the product could have written), actors in `slop/actors/`, faults with `targets=[check names]` in `slop/lib/faults.py`, one scenario per user flow in `slop/scenarios/`.
- Latency budgets live in the scenario file (end-to-end frame→SSE, plus real routes), never here.

# State logic — reducers, not setState chains
- When ≥2 `useState`s change together or gate each other, or validity/payload depends on several of them: a pure `(state, action) => state` reducer with a typed `Action` union in a plain `.ts` next to the component, plus pure `canSubmit`/`buildPayload` helpers, tested with vitest tables. The component only dispatches. Single booleans stay `useState`; no global store.
