# Ultra mode build — decision log

Run started 2026-11-13. Invocation: `/spec-auto` "Build Ultra mode + MCP … one PR per step, each shipped (rwl, merge green, deploy-all)".

## Decisions

- D1 (deviation, flagged): spec-auto floors say design-only without literal `--execute` and never push/deploy. The owner's own invocation asks to build, PR, merge and deploy-all each step (also global CLAUDE.md "ship every finished task"). Owner's explicit words win; treated as `--execute` + ship.
- D2 (code judo): spec-auto steps 0–4 (CONTEXT/ADRs/specs/adversary/tickets) skipped — `docs/plans/ultra-mode/` tickets already carry resolved, adversary-reviewed answers (codex 2-phase + Fable). Each build step's spec = its tickets' `## Answer` + owner amendments.
- D3: proofs never call paid LLMs. Real path = running relay + Next on local ports with a dev DB; the LLM provider row points at a local fake OpenAI-compatible server (network boundary only). ASSUMPTION: overturned if owner wants one real DeepSeek call per proof.
- D4: ticket 02 "re-run full eval on flash before ship" = paid → not run; flagged in PR.

## Steps

| # | Step | Branch | PR | Merged | Deployed |
|---|---|---|---|---|---|
| 1 | Report recipe + Do-mode export | ultra/s1-report-export | | | |

## Step 1 notes

- rwl full tier: round 1 (structure, correctness, codex, codex-da, deepseek) + 3 fix rounds; F1–F21 closed. codex-da IDEAS (shrink to named report variants) rejected: owner decision in 01 Answer.
- Deferred minor: a 1-char CJK request word ("李") vs single-token names ("李明"/"李华") still lets the model's pick through.
- Proof (measured): demo stack, fake LLM patched outside service/ to return a report_export draft; card → Download → 20-row CSV byte-identical to direct POST /admin/reports/run; xlsx = valid zip; cross-Agency creator id → 400, no file.
- Full suite at head: 10 vitest reds in PermissionEditor/RoleSettingsTab/VaultProPage also red on origin/main (measured); 3 py reds (tx_rollup, vault_flags_sweep, vault_jev) pass alone = load flakes (measured).

## Fable consults

- F1 (2026-11-13, before step 1 review): continue + 2 redirects. Spec 13 on paper before step 2 freezes `Tool` → **accept** (spec before step 2; build stays step 4). Resolve 12 before step 3 → **decline** (owner: 09–12 specced when step 3 lands; step 3 bio tools exclude background). Step 3 "four owner jobs" eval not achievable without sends/live OF → **accept**: rename to tool-surface usability transcript over MCP; 07 deferred. Split step 2 into 3 PRs → **decline** (owner: one PR per step). Real DeepSeek smoke per prompt step → owner's call; global rule forbids paid checks → flagged "guess" in PRs. Per-step risks recorded for briefs. Next check: two-Agency negative export in browser; bearer-through-Next + in-process ASGI spike before step 2.
