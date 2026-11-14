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
| 1 | Report recipe + Do-mode export | ultra/s1-report-export | #571 (+#572 strip patch, #573 watch check) | 98b6c5341 | AE 86550c8a1, public c78dfad84, demo; landing n/a |
| 2 | Owner tokens + Toolbox read tools + /admin/mcp | ultra/s2-tokens-toolbox-mcp | | | |

## Step 1 notes

- rwl full tier: round 1 (structure, correctness, codex, codex-da, deepseek) + 3 fix rounds; F1–F21 closed. codex-da IDEAS (shrink to named report variants) rejected: owner decision in 01 Answer.
- Deferred minor: a 1-char CJK request word ("李") vs single-token names ("李明"/"李华") still lets the model's pick through.
- Proof (measured): demo stack, fake LLM patched outside service/ to return a report_export draft; card → Download → 20-row CSV byte-identical to direct POST /admin/reports/run; xlsx = valid zip; cross-Agency creator id → 400, no file.
- Full suite at head: 10 vitest reds in PermissionEditor/RoleSettingsTab/VaultProPage also red on origin/main (measured); 3 py reds (tx_rollup, vault_flags_sweep, vault_jev) pass alone = load flakes (measured).

## Step 2 notes

- rwl full tier round 1 (S1–S9, `.scratch/ultra-s2-review/FINDINGS.md`); round 2: S1–S9 CLOSED (Sonnet verdicts), structure pass 8 minors, 6 fixed (one token-tool rule `td.token_tools()`, dead EXTRA entry, STRIPPED reuse, dead helpers, one eviction loop, generic card text).
- Deferred minor: `_download` takes `ReportFile | report_files.File` union (same 3 fields).
- Step 3 MUST: the token allowlist grants a whole route, not the tool's arg schema (e.g. bearer can POST /admin/reports/run with format=csv). Harmless for reads; every write tool route must be no broader than its tool schema, or gate it.
- Step 6 MUST: `mcp_api.Builtin.run` is sync with `td.NoArgs`; register_account/login need an args model + async run.

## Fable consults

- F1 (2026-11-13, before step 1 review): continue + 2 redirects. Spec 13 on paper before step 2 freezes `Tool` → **accept** (spec before step 2; build stays step 4). Resolve 12 before step 3 → **decline** (owner: 09–12 specced when step 3 lands; step 3 bio tools exclude background). Step 3 "four owner jobs" eval not achievable without sends/live OF → **accept**: rename to tool-surface usability transcript over MCP; 07 deferred. Split step 2 into 3 PRs → **decline** (owner: one PR per step). Real DeepSeek smoke per prompt step → owner's call; global rule forbids paid checks → flagged "guess" in PRs. Per-step risks recorded for briefs. Next check: two-Agency negative export in browser; bearer-through-Next + in-process ASGI spike before step 2.
- F2 (2026-11-13, ticket 13): chain runs at plan submit, not in `toolbox.call`/route flag/Caption writer; executor sends approved text byte-for-byte; `call()` refuses `effect=send` without a plan step. Freeze `Tool.model_text` + `Tool.text_kind` in step 2 (drift test). Stage list in 13 Answer. Step-2 risk: silent arg loss → write tools verify echo; exact unique name match. → **accept** (13 Answer written; flagged owner-vetoable).
- F3 (2026-11-14, step 2 rwl round 1 + 4-round check): token blocklist failed open (measured: bearer created an employee login that survived revoke). → **accept (b) allowlist**: a bearer may call only method+route-template pairs derived from Toolbox `TOOLS` + report files + `/admin/mcp`; everything else 403. DEVIATION (owner-vetoable) from 03 "ASSUMPTION: tokens = full owner rights": that was written against a read-only split; widen later is easy. `connect_account` → MCP builtin outside TOOLS; `_clip` sets truncated; report-file cap per owner; prove SHARE_TOKEN fix against AE config.
- Step 2 merge of main 713774458 (#574–576 Full AI): owner_tokens migration rechained 0117 → 0118 (after 0117_full_ai_decisions; test_full_ai_migration single-head check loosened to "one head, 0117 on its line"); prompt entries renumbered NEW-107/108 (main took NEW-106); `/admin/owner-tokens` chatter-blocked, `/admin/mcp` UNMAPPED; hook-layer test lists StripCookieIdentities. public-sync strip patch regenerated; the 22 private-word lines main's Full AI docs/code added are stripped by it since the step 2 deploy.
