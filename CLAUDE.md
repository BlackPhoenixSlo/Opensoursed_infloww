# Slop tests — opt-in only (owner 2026-11-12)
- Never run slop by default. Change touches volume/concurrency (mass sends, sweeps, queues, many users)? Ask the owner if a slop run is needed; no answer = no slop. If yes: follow `slop/README.md` (`--scale=small`, no per-task volume; nightly sweep unchanged). Never `service/chatterly.db` or prod; no test hooks in `service/`.

# State logic — reducers, not setState chains
- ≥2 `useState`s that change together / gate each other / jointly decide validity or payload → pure `(state, action) => state` reducer with typed `Action` union in a `.ts` beside the component, plus pure `canSubmit`/`buildPayload`, vitest tables (template `app/components/chat/fanDrawerForm.ts` + test). Component only dispatches. Single booleans stay `useState`; no global store.

# Test loop
- Iterating on app code: `cd app && pnpm exec vitest related --run <changed files>` (only tests importing them: 12–26 s vs ~70 s full, measured 11-17). Before PR: full `scripts/run-tests.sh` (or `pnpm test:run` for app-only) — related never replaces it.

# Review
- Root `REVIEW.md` holds review rules (mirror `.claude/REVIEW.md`, keep identical); rwl skill reads it.
