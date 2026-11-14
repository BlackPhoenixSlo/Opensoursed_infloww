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
| 2 | Owner tokens + Toolbox read tools + /admin/mcp | ultra/s2-tokens-toolbox-mcp | #578 | 9789b4cef | AE 3f5fe8b84, public c64a4da3d, demo (2026-11-14) |
| 3 | Toolbox write tools (OF folders, bio pages) + bearer write gate | ultra/step3-write-tools | | | |

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

## Step 3 notes

- Tools (effect=write): `of_folder_create`, `of_folder_add`, `bio_page_create`, `bio_avatar_from_vault`, `bio_link_add`, `bio_link_bg_from_vault`, over existing routes; no new route (link create's answer gains an additive `link`: the created link). Plus read tool `bio_page_get` (GET `/admin/bio-pages/{pid}`). Token allowlist = TOOLS routes + EXTRA only, no special case. `call()` still refuses effect=send.
- Echo: a write tool has a `check(args, answer)` only where its route can 2xx without doing all that was asked: folder create (OF add failure swallowed → added 0; OF's own name), bio page create (display name / Creator; a Creator asked + no OnlyFans link back, her profile unreadable → error naming the page), link add (the answer's `link` vs the asked fields; the result keeps `link` outside the 50-row cut). A mismatch → 502 error result, never success. Folder add, avatar and background need none (they echo the args or fail loudly; `_set_file` always writes a new file name). Args validated by the pydantic model before any request.
- Resource binding: bio tools on a page id take no account_id and send no Creator. Their routes (link create, vault avatar/background) set `request.state.audit_account_id` = the page's stored Creator (`bio_pages.admin._audit_as`), which `audit_log` prefers over X-Account-Id/`?account_id=` (cookie callers too). Isolation needs none: the pid is no account id and every bio route is owner-scoped (foreign page 404).
- Step 3 MUST closed: `token_auth.write_refusal` (in `auth._token_request`, bearer only) holds a raw request to a write tool's route to exactly what the tool sends: body + path params validate against its args model, `build_request` rebuilds the request, and raw path / query / X-Account-Id / body must equal it (canonical JSON: unsent defaults, `0` for false, unstripped text, a path key in the body, a missing or mismatched Creator → 403; any Creator on a bio page route → 403). No repeated params, JSON object body. Cookie callers unchanged.
- DEVIATION: `of_folder_add` takes `account_id` + `list_id` (04 says resource-id tools take no account_id). No table stores an OF folder's Creator (the mirror only knows folders holding media; a new empty folder is invisible), so there is nothing to bind. The write runs on that Creator's own OF session, so OF scopes the list id to her; isolation checks `?account_id=`; audit records the Creator whose session wrote.
- DEVIATION: folder open_url = `/growth/vault-pro` (no folder deep-link page; app/ untouched). Bio tools open `/growth/bio-pages/{profile_id}` (create: from the answer; no id back → no open_url).
- Fix found on the way: `args_schema` stripped every key named `title`, so a property NAMED title vanished from the schema (bio_link_add). Properties are now kept.
- Deferred: `describe_all_start` (paid LLM spend); `bio_page_background` (no route); headless register/login (step 6).
- rwl full tier: round 1 (structure + correctness Opus) S1–S4, M1–M5; round 2 (Sonnet verdicts, Opus structure lens, codex review + codex-da) R1–R7; round 3 Sonnet verdicts + codex final: NONE. All closed (`.scratch/ultra-s3-review/FINDINGS.md`). codex-da IDEAS "return the created link instead of a pre-read" → adopted (R1).
- Proof (measured, offline demo stack, fake OF patched from a launcher outside service/): token minted in Settings → AI keys; over `POST /admin/mcp` all six write tools ok (bio page + link + vault avatar + vault link background; OF folder create + add); one audit row per write naming the Creator, `token s3-proof`, none for `/admin/mcp`; raw bearer with an extra key or a Creator header → 403; missing page → error result; revoked token → 401.
- Eval = tool-surface usability transcript (F1), not the four owner jobs (need sends / live OF; 07 stays deferred). Notes for step 4+: `of_folders_list` reads the mirror, so a just-created empty folder is not listed (description says never repeat); folder `open_url` names no Creator; an error result on a missing page still carries that page's `open_url`; called straight on the relay (no app host) `open_url` is a bare path and `public_url` names the relay host.

## Fable consults

- F1 (2026-11-13, before step 1 review): continue + 2 redirects. Spec 13 on paper before step 2 freezes `Tool` → **accept** (spec before step 2; build stays step 4). Resolve 12 before step 3 → **decline** (owner: 09–12 specced when step 3 lands; step 3 bio tools exclude background). Step 3 "four owner jobs" eval not achievable without sends/live OF → **accept**: rename to tool-surface usability transcript over MCP; 07 deferred. Split step 2 into 3 PRs → **decline** (owner: one PR per step). Real DeepSeek smoke per prompt step → owner's call; global rule forbids paid checks → flagged "guess" in PRs. Per-step risks recorded for briefs. Next check: two-Agency negative export in browser; bearer-through-Next + in-process ASGI spike before step 2.
- F2 (2026-11-13, ticket 13): chain runs at plan submit, not in `toolbox.call`/route flag/Caption writer; executor sends approved text byte-for-byte; `call()` refuses `effect=send` without a plan step. Freeze `Tool.model_text` + `Tool.text_kind` in step 2 (drift test). Stage list in 13 Answer. Step-2 risk: silent arg loss → write tools verify echo; exact unique name match. → **accept** (13 Answer written; flagged owner-vetoable).
- F3 (2026-11-14, step 2 rwl round 1 + 4-round check): token blocklist failed open (measured: bearer created an employee login that survived revoke). → **accept (b) allowlist**: a bearer may call only method+route-template pairs derived from Toolbox `TOOLS` + report files + `/admin/mcp`; everything else 403. DEVIATION (owner-vetoable) from 03 "ASSUMPTION: tokens = full owner rights": that was written against a read-only split; widen later is easy. `connect_account` → MCP builtin outside TOOLS; `_clip` sets truncated; report-file cap per owner; prove SHARE_TOKEN fix against AE config.
- Step 2 merge of main 713774458 (#574–576 Full AI): owner_tokens migration rechained 0117 → 0118 (after 0117_full_ai_decisions; test_full_ai_migration single-head check loosened to "one head, 0117 on its line"); prompt entries renumbered NEW-107/108 (main took NEW-106); `/admin/owner-tokens` chatter-blocked, `/admin/mcp` UNMAPPED; hook-layer test lists StripCookieIdentities. public-sync strip patch regenerated; the 22 private-word lines main's Full AI docs/code added are stripped by it since the step 2 deploy.
