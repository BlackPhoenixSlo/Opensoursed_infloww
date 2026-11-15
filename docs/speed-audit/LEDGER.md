# Speed audit ledger

Daily audit: pick max(wall × runs/week) among rows not audited in 14 days (tie: oldest audit). Never re-propose a rejected idea. Numbers: measured / inferred / guess.

| process | entrypoint | runs/week | last measured wall + source | last audited | tried / rejected ideas |
|---|---|---|---|---|---|
| slop nightly | `slop/run` target `nightly` (T3 scheduler 02:00, `~/oi-slop-nightly`) | 7 | ~21.2k s (measured, 11-15 summary.md: volume 741 · all 11373 · map 9136). Map Mon–Sat after the 11-15 fix ~150 s (inferred: the 4 stale/unmapped rows' measured 11-15 seconds) | 2026-11-15 | DONE 11-15: map re-maps only stale entries (>200 behind / divergent) + unmapped; Sunday full refresh kept (3 entries that INFRA in `--map` had forced a full 91-scenario refresh every night). Rejected: merge `all` into a coverage run (map runs ignore budgets → different verdicts). Open, not speed: the 4 scenarios that INFRA |
| deploy-all | `.claude/skills/deploy-all` (`dry-run.sh`, `live.py`) | ~20 (inferred: 5 scratch runs on 11-15) | see PR #692 (`.scratch/deploy-all/*/`) | 2026-11-15 (PR #692) | DONE #692: no tick wait, parallel live targets, cached selftest, auto golden, stale-checkout guard |
| proxy-health collect | `scripts/proxy-health/collect.sh` (oi-proxy-health; 4 h AE + 11 h public) | ~57 | ~3 s script (measured: `coverage.ssh_s`=2 in runs/20261115T0559Z.json; 3 local plan calls 0.05 s each); sweep wall = the LLM agent | 2026-11-15 | no win: already one ssh round-trip; time is the agent prompt, not the script |
| run-tests.sh | `scripts/run-tests.sh` | rare (guess: tests usually run per file) | not measured | — | candidate: 555 serial `service/tests/test_*.py` → parallel; check real usage first |
| CI | `.github/workflows/` (`site`, `desktop-build`) | ~10 (measured: 33 `site` runs in last 200) | `site` avg 32 s (measured, `gh run list`) | 2026-11-15 | no win: 32 s |
