# Slop tests — read slop/README.md first
- Fresh worktree: `slop/run --list` once links `venv/` + `web/node_modules`, clones `app/node_modules`.
- Iterate `slop/run <scenario> --scale=small`. Before done: `slop/run --changed` green (own/flow picks always; 15 min budget for the rest; `--budget=0` when touching shared code on purpose). Quote the `slop/evidence/` folder, never `latest`.
- Own pick with `FAULT`: `slop/run <it> --break --baseline=<green folder>` must print CAUGHT. No per-task volume runs (medium/120+, 200 users): volume runs only once a day in `slop/run nightly` (owner 2026-11-12).
- `slop/run nightly` = daily sweep incl. volume + map refresh; never hold the gate around it. `slop/run all` only on demand / pre-deploy / when `--changed` picks most; `all --map` refreshes `slop/map.json`.
- Stacks: `scripts/demo-shots/relay_guarded.py` + `fetch-guard.cjs`, temp DB, loopback only; never `service/chatterly.db` or prod.
- Fan traffic via `POST /__slop/of-ws-frame` (`slop/lib/relay.py`), serial per Creator (`fan_dm.serial`, `--rate` open-loop). No test hooks in `service/`.
- Seeders `slop/seed/` (SQL, deterministic from `--seed`, only product-writable rows); actors `slop/actors/`; faults with `targets=[checks]` in `slop/lib/faults.py`; one scenario per user flow in `slop/scenarios/`. Latency budgets live in the scenario file.

# State logic — reducers, not setState chains
- ≥2 `useState`s that change together / gate each other / jointly decide validity or payload → pure `(state, action) => state` reducer with typed `Action` union in a `.ts` beside the component, plus pure `canSubmit`/`buildPayload`, vitest tables (template `app/components/chat/fanDrawerForm.ts` + test). Component only dispatches. Single booleans stay `useState`; no global store.

# Review
- Root `REVIEW.md` holds review rules (mirror `.claude/REVIEW.md`, keep identical); rwl skill reads it.
