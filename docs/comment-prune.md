# Comment prune tracker

**Closed 2026-11-25: 190,452 → 15,212 (8.0%), target ≤19,045 met.** After the stricter counting rules from the gate-tooling review (#1086), the same tree counts 15,556 (8.2%), and the budget is set to that.

Owner GO 2026-11-24. Goal: comment + docstring lines ≤10% of the start recount, zero behaviour change. Each session: read this, continue from the first unfinished batch.

## Baseline

Recount 2026-11-24 at 672e58bca (`scripts/comment_budget.py --report`): **190,452** lines, 4,126 files. Target ≤ **19,045**. After tooling fixes the same tree counts 189,905 (`--rebaseline`); target unchanged.

| dir | lines | files |
|---|---:|---:|
| service | 100,831 | 1,299 |
| app | 49,478 | 1,790 |
| slop | 20,638 | 442 |
| scripts | 10,749 | 206 |
| fansly | 2,502 | 19 |
| soak | 1,954 | 60 |
| deploy | 1,431 | 36 |
| desktop | 893 | 42 |
| demo | 652 | 30 |
| loginExtensionMulti | 469 | 6 |
| .scratch | 439 | 178 |
| .claude | 363 | 14 |
| web | 53 | 2 |

## Final recount

`--report` at 156841d28:

| dir | start | final |
|---|---:|---:|
| service | 100,831 | 7,697 |
| app | 49,478 | 2,387 |
| slop | 20,638 | 4,422 |
| scripts | 10,749 | 207 |
| fansly | 2,502 | 124 |
| soak | 1,954 | 41 |
| deploy | 1,431 | 163 |
| desktop | 893 | 56 |
| demo | 652 | 56 |
| loginExtensionMulti | 469 | 36 |
| .scratch | 439 | 3 |
| .claude | 363 | 15 |
| web | 53 | 5 |
| **total** | **190,452** | **15,212** |

Budget (`scripts/comment-budget.json`) is lowered to these counts; CI `comment-budget.yml` runs `--check`.

## Tooling

- `scripts/comment_lang.py` — shared per-file comment/docstring spans (py tokenize+ast, sh shfmt, ts via `comment_tools.mjs`; extensionless bash/sh/python shebang scripts included) and the repo-wide runtime-docstring context.
- `scripts/comment_budget.py` — report by default; `--check` (run-tests.sh + CI `comment-budget.yml`) fails on growth, new commented files and unparsed files; `--check` compares changed files to the merge base of HEAD and `${COMMENT_BASE:-origin/main}` and requires a new `--allow` reason for growth; invalid manifests (non-integer limits, blank reasons) exit 1; `--lower [paths]` after each batch; `--allow FILE --reason`; `--rebaseline` initializes a missing manifest. An intentional replacement requires `--force`.
- `scripts/comment_equality.py <base> [<head>]` — merge gate (CI on `chore/comment-*` branches or `chore(comments)…` PR titles — W-batch rwl PRs that restore whys must use a `chore(comments)` title or equality never runs; gate on when the base has `scripts/comment-budget.json`): py AST + compile / TS AST + transpile emit / bash -n + shfmt AST; allowlisted comments identical, in order, at the same code position; runtime docstrings, line endings, BOM, regular modes unchanged; files reading their own source or `$LINENO` untouched; only modified tracked files.
- `scripts/comment_strip.py <paths>` — strips every prunable comment, self-gates (LEFT = untouched, exit 1), reports PARTIAL docstrings sharing a line with code, skips open-PR files of every GitHub remote (+ `--pr-repo`), `--skip-file` lists, budget `--allow` files and symlinks.

## Batch flow

1. `git switch -c chore/comment-prune-Bnn origin/main`; `grep -h '^+++ b/' .claude/skills/public-sync/*.d/*.patch | cut -c7- > /tmp/pinned.txt`; `python3 scripts/comment_strip.py <dirs> --skip-file /tmp/pinned.txt [--pr-repo OWNER/NAME for each sibling repo whose remote isn't a GitHub URL] > /tmp/Bnn-strip.txt 2>&1` (SKIP lines → skipped table; LEFT/PARTIAL → hand edit; strip exits 1 whenever anything is LEFT, which is expected, so read the summary rather than the exit code).
2. Sonnet workers (Agent `model: sonnet`, effort medium), ~50 files each: read `git diff` of their files, restore only non-obvious whys as one terse line (OF quirk, owner decision, invariant, workaround with reason). Comment-only edits.
3. Opus: `comment_equality.py origin/main`, sample 30 files of deletions, tests (vitest related / pytest per CLAUDE.md; full `run-tests.sh` every 4 batches), `comment_budget.py --lower <dirs>`, PR, merge when green.
4. Every 3 merged batches: deploy-all. Every 4 PRs: rwl (scope = tooling + sampled deletions).

## Batches

| # | scope | files | lines before | after | PR | sha |
|---|---|---:|---:|---:|---|---|
| T | tooling | — | — | — | #1047 | aef290087 |
| B01 | scripts/ (pilot) | 209 | 10,493 | 77 | #1048 | a6cf32141 |
| B02 | service/automations | 121 | 16,987 | 935 | #1052 | 55562fdb1 |
| B03 | service/db, bio_pages, seeds, scripts | 168 | 5,737 | 1,859 | #1054 | 7b4888d5a |
| B04 | service/[a-l]*.py | 115 | 10,548 | 683 | #1055 | 0c94cc48c |
| B05 | service/[m-z]*.py | 200 | 18,422 | 708 | #1056 | a572ff2a2 |
| B06 | service/tests/test_[a-c]* | 133 | 9,043 | 162 | #1057 | 00fdf0446 |
| B07 | service/tests/test_[d-h]* + helpers | 148 | 7,486 | 694 | #1059 | a4955f34d |
| B08 | service/tests/test_[i-r]* | 183 | 9,970 | 78 | #1060 | a9318e770 |
| B09 | service/tests/ rest | | | | | |
| B10 | app/components/chat | 211 | 7,009 | | | |
| B11 | app/components/growth, vault | 212 | 5,343 | | | |
| B12 | app/components/settings, setup, automations | 234 | 4,698 | | | |
| B13 | app/components/assistant, stats, messages, compose | 144 | 3,775 | | | |
| B14 | app/components/home, shell, ui, shifts, employees, auth | 121 | 2,550 | | | |
| B15 | app/components rest (other subdirs + root files) | 158 | 3,963 | | | |
| B16 | app/lib/[a-n]* | 110 | 3,797 | | | |
| B17 | app/lib rest | 268 | 9,206 | | | |
| B18 | app/hooks | 207 | 6,593 | | | |
| B19 | app/app, contexts, app root | 125 | 2,545 | | | |
| B20 | slop/lib | 228 | 5,997 | 132 | #1064 | 2228657db |
| B21 | slop scenarios, actors, seed, root | 164 | 10,328 | 187 | #1069 | 12c098418 |
| B22 | fansly, desktop, deploy, soak, demo | 171 | 5,827 | 234 | #1070 | 60e6d6e1b |
| B23 | rest dirs + previously skipped files | 200 | 6,909 | 876 | #1073 | 6c6e0313e |
| B24 | Twin/public-PR-skipped files (server.py, models.py, …) | 55 | 8,414 | 940 | #1076 | ab8ef02df |
| COMB | service/tests/test_[s-z]*, app/lib, app/hooks, app/components, app/app + contexts (B09–B19) | 1733 | 57,941 | 1,785 | #1063 | 63bb88ec3 |
| B25 | files deferred from earlier batches (nav, relayTypes, hooks, fansly shim, …) | 35 | 3,852 | 270 | #1078 | 2d8920348 |
| W | rwl window: restored-whys fixes | 23 | — | — | #1079 | 51bd7b30c |
| W | rwl window: blind-spots (test message) | — | — | — | #1080 | |
| F | Fansly fixture ids for public leak gate | — | — | — | #1077 | 41ff79d35 |
| D | deploy-all doc: Twin worktree path | — | — | — | #1051 | |

## Skipped (open PRs / pinned)

Pinned: files patched by public-sync's strip patches (`.claude/skills/public-sync/*.d/*.patch`; comment context lines must keep applying). Never pruned in batch PRs (the equality gate rejects `.patch` edits); they go in one separate hand-edited PR with `strip-regen.sh`, after the batches.

| file | reason | batch | swept |
|---|---|---|---|
| service/automations/_ppv_readback.py | twin-infloww_crm#7 | B02 | |
| service/automations/full_ai_ppv.py | twin-infloww_crm#7 | B02 | |
| service/automations/full_ai_settle.py | twin-infloww_crm#7 | B02 | |
| service/automations/reply_mass_funnel.py | pinned: test_full_ai_owner_io/test_full_ai_stand_down diff it vs origin/main | B02 | |
| service/automations/wcfi_decide.py | pinned: test_full_ai_stand_down diffs it vs origin/main | B02 | |
| service/db/models.py | twin-infloww_crm#45 | B03 | |
| service/db/migrations/versions/{20261103_1200_push_subscriptions,20261109_1200_tracking_link_bot_check,20261121_0100_keep_running_rules_heal,20261122_0310_tracking_clicks_unclassified}.py | pinned: strip patches | B03 | |
| service/bio_pages/public/script.js | pinned: test_bio_decide md5-pins the asset | B03 | never |
| service/tests/test_welcome_chatter_for_info.py | pinned: test_full_ai_handoff diffs it vs origin/main | B06–B09 | never |
| service/account_config_api.py | conflicts with Twin main | B04 | |
| service/assistant_api.py | conflicts with Twin main | B04 | |
| service/assistant_evidence_full_ai.py | conflicts with Twin main | B04 | |
| service/assistant_fan_pack.py | conflicts with Twin main | B04 | |
| service/assistant_full_ai.py | conflicts with Twin main | B04 | |
| service/audit_log.py | conflicts with Twin main | B04 | |
| service/auth.py | conflicts with Twin main | B04 | |
| service/full_ai_api.py | conflicts with Twin main | B04 | |
| service/full_ai_persona.py | conflicts with Twin main | B04 | |
| service/llm_client.py | conflicts with Twin main | B04 | |
| service/llm_models.py | conflicts with Twin main | B04 | |
| service/of_client.py | conflicts with Twin main | B05 | |
| service/permissions.py | conflicts with Twin main | B05 | |
| service/vault_ai_vision.py | conflicts with Twin main | B05 | |
| service/vault_ai_vision_decide.py | conflicts with Twin main | B05 | |
| service/vault_internal_folders.py | conflicts with Twin main | B05 | |
| service/vault_pack_picker.py | conflicts with Twin main | B05 | |
| service/vault_scripts.py | conflicts with Twin main | B05 | |
| service/vault_settings.py | conflicts with Twin main | B05 | |
| service/vault_tags.py | conflicts with Twin main | B05 | |
| app/lib/freeTrial.ts | conflicts with Twin main | COMB | |

## Decisions

- 2026-11-25 deploy-all before batch 1: run 20261124T2242Z-aef290087, AE 5cbabe72f, public 120df2c8c, Twin a31224323 (URL 000 = no DNS yet), demo/landing skip.
- 2026-11-25 B01 pilot: 4 Sonnet workers × ~52 files, 2–3 min each; 75 whys restored (~0.7%), Opus restored 1 more from a keyword sample. Pre-existing on main, not from prune: `scripts/script-fill-rollout/test_w30_sf_repros.py` 2 failed; `test_script_fill_lock_hold.py` and `ScriptsPage.test.tsx` 10k-render time out under full-suite load only.
- 2026-11-25 Workers write helper scripts under a per-worker name (`/tmp/Bnn-gN-*`); two B01 workers shared `/tmp/ins.py` and duplicated each other's inserts (cleaned, gate green).

- 2026-11-25 Fable on pilot: brief drops the ~1% expectation (service/ 3–5%), Keep list adds locks/never-twice/money/measured OF/read-marking/proxy-session; ~25 files per worker; second restore pass per batch for service/; full run-tests + deploy-all after each of B02–B05, B06+ unattended at owner cadence.
- 2026-11-25 B02: 2 passes (4 + 5 Sonnet workers), 353 whys restored (~2.1%). Full run: test_agency_notifications fails on main too; test_script_fill_lock_hold load-only. Source-pinning tests found by the full run: two diff files vs origin/main (files left unpruned), one asserts comment text (kept).

- 2026-11-25 B03: 1 pass, 126 whys (~3%); full run: test_bio_decide md5-pins bio script.js (reverted); test_vault_collect_walk / test_vault_flags_sweep / test_app_open_warm load-only (pass alone).
- 2026-11-25 deploy-all after B02 refused at public replay: #1049 shipped private-only text; fixed by strip patches in #1053.

- 2026-11-24 TS gate = custom AST walk (JSX whitespace per React rule, empty `{/* */}` dropped) + removeComments printer on non-JSX files; owner suggested printer only — printer alone false-fails JSX comment removal and misses nothing the walk catches.
- 2026-11-24 Shell gate = `shfmt --to-json` AST equality without positions and comments (heredoc `#` lines are content; `--minify` normalised code like `$(( $a*2 ))`).
- 2026-11-24 Runtime docstrings kept as code: files using `__doc__`/getdoc/typer/click (all docstrings), modules/classes/functions named in any `X.__doc__`/`getdoc(X)` repo-wide, FastAPI route handlers (`@x.get/post/...`, `add_api_route` endpoints), pydantic/TypedDict model classes incl. aliases and subclasses repo-wide (OpenAPI descriptions). Equality takes the union of base and head context.
- 2026-11-24 Directives keyed by code position (tokens before them, own-line vs trailing, cookie/shebang line); `{/* */}` between two JSX texts is kept (removal merges React text children).
- 2026-11-24 Strip-then-restore: `comment_strip.py` removes everything mechanically; Sonnet only restores whys. Proven on whole repo: 3,891 files stripped, gate 3,891 ok, floor 44 lines.
- 2026-11-24 Fable (pre-design): continue; add full tests per batch + public-sync dry-run in pilot; source-reading tests (~105) and public-sync strip patches invisible to AST equality. Opus: full `run-tests.sh` on every batch instead of one full-tree run; strip-patch targets pinned via `--skip-file`.
- 2026-11-24 `scripts/fu_hillclimb/hillclimb.py` `typo_sha` hashes `inspect.getsource` of typo functions → key changes once (research cache only); accepted.
- 2026-11-24 CI workflow gates itself on `.claude/REVIEW.md` existing, so it runs only in this repo (Twin/public client PRs would otherwise go red).
- 2026-11-25 B04: route handlers wired via add_api_route keep their docstring in OpenAPI (test_route_order wired goldens caught a wired handler; restored). Twin check added: batch files whose prune conflicts merging into Twin main are left for the sweep (twin main diverges in ~500 files; deploy-all after #1053 already hit ~25 conflicts in full_ai_* from B02).
- 2026-11-25 B05: test_of_rich_text perf case (761 ms) and ScriptsPage.test fail only under full-suite load (~50); pass alone.
- 2026-11-25 Twin gate is per hunk (Fable): prune hunks whose public replay would conflict merging into Twin main stay; B02's 24 already-conflicting service/automations files got those hunks back (budget --allow "Twin-adjacent"). _router_jev.py conflicts for a non-comment reason.
- 2026-11-25 B09–B19 tested together in one full run-tests (comment_equality proves code identical), shipped as one PR
- 2026-11-25 Fable endgame: target met; pinned/open-PR/NUL files recorded as exceptions; one rwl window, three themes (restored whys, gate tooling, blind spots).
- 2026-11-25 Fable (B23 check): prune files touched only by Twin/public-repo PRs now (they never git-merge into private); pinned public-sync targets with a strip-patch regen in the same PR; files of the owner-held nightly slop-fix PRs last.

## Exceptions kept

| file | comment | why |
|---|---|---|
| public-sync strip-patch targets (27 files, 816 lines) | all | patch context must keep applying; prune needs a hand PR with `strip-regen.sh` |
| files of open owner-held nightly slop-fix PRs #1020–#1045 (slop/scenarios, slop/lib, tabs) | all | prune after they merge (sweep) |
| app/hooks/useStillLadder.ts | all (44) | NUL byte; TS parser path skips it |
| service/tests/test_welcome_chatter_for_info.py, reply_mass_funnel.py, wcfi_decide.py | all | tests diff them vs origin/main |
| service/bio_pages/public/script.js | all | md5-pinned by test_bio_decide |
| hunks conflicting with Twin main (B02/B04/B05/B24 files) | those hunks | merge into Twin would conflict |
| service/automations/_router_jev.py | `asks_offer_details 0.6 measured 2026-11-17` | test_full_ai_offer_details_route asserts the text |

## Restored after review

| batch | file | line | why |
|---|---|---|---|
| B23 | several (Fable sample) | — | Fable check restored dropped whys |
| B24 | service/runtime_switches.py | `_lock` | lock/cache invariant |
| W | 23 files | 35 lines | rwl: wrong/misplaced restored whys fixed (#1079) |
