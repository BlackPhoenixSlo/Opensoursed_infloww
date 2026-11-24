# Comment prune tracker

Owner GO 2026-11-24. Goal: comment + docstring lines ≤10% of the start recount, zero behaviour change. Each session: read this, continue from the first unfinished batch.

## Baseline

Recount 2026-11-24 at 672e58bca (`scripts/comment_budget.py --report`): **190,452** lines, 4,126 files. Target ≤ **19,045**.

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

## Tooling

- `scripts/comment_lang.py` — shared per-file comment/docstring spans (py tokenize+ast, sh shfmt, ts via `comment_tools.mjs`) and the repo-wide runtime-docstring context.
- `scripts/comment_budget.py` — report by default; `--check` (run-tests.sh + CI `comment-budget.yml`) fails on growth, new commented files and unparsed files; `--growth BASE` (CI) fails on a raised budget without a new `--allow` reason; `--lower [paths]` after each batch; `--allow FILE --reason`; `--rebaseline` after tool changes.
- `scripts/comment_equality.py <base> [<head>]` — merge gate (CI on `chore/comment-prune-*`): py AST / TS AST + printer / shfmt AST; allowlisted comments identical at the same code position; runtime docstrings, line endings, BOM, modes unchanged; only modified tracked files.
- `scripts/comment_strip.py <paths>` — strips every prunable comment, self-gates (LEFT = untouched), reports PARTIAL docstrings sharing a line with code, skips open-PR files of every GitHub remote (+ `--pr-repo`) and `--skip-file` lists.

## Batch flow

1. `git switch -c chore/comment-prune-Bnn origin/main`; `grep -h '^+++ b/' .claude/skills/public-sync/*.d/*.patch | cut -c7- > /tmp/pinned.txt`; `python3 scripts/comment_strip.py <dirs> --skip-file /tmp/pinned.txt [--pr-repo OWNER/NAME for each sibling repo whose remote isn't a GitHub URL] > /tmp/Bnn-strip.txt 2>&1` (SKIP lines → skipped table; LEFT/PARTIAL → hand edit).
2. Sonnet workers (Agent `model: sonnet`, effort medium), ~50 files each: read `git diff` of their files, restore only non-obvious whys as one terse line (OF quirk, owner decision, invariant, workaround with reason). Comment-only edits.
3. Opus: `comment_equality.py origin/main`, sample 30 files of deletions, tests (vitest related / pytest per CLAUDE.md; full `run-tests.sh` every 4 batches), `comment_budget.py --lower <dirs>`, PR, merge when green.
4. Every 3 merged batches: deploy-all. Every 4 PRs: rwl (scope = tooling + sampled deletions).

## Batches

| # | scope | files | lines before | after | PR | sha |
|---|---|---:|---:|---:|---|---|
| T | tooling | — | — | — | | |
| B01 | scripts/ (pilot) | 211 | 10,749 | | | |
| B02 | service/automations | 121 | 16,987 | | | |
| B03 | service/db, bio_pages, seeds, scripts | 168 | 5,737 | | | |
| B04 | service/[a-l]*.py | | | | | |
| B05 | service/[m-z]*.py | | | | | |
| B06 | service/tests/test_[a-c]* | | | | | |
| B07 | service/tests/test_[d-l]* | | | | | |
| B08 | service/tests/test_[m-r]* | | | | | |
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
| B20 | slop/lib | 246 | 7,050 | | | |
| B21 | slop/actors, evidence, seed | 93 | 2,083 | | | |
| B22 | slop/scenarios | 102 | 11,463 | | | |
| B23 | fansly, desktop, deploy, soak, demo | 187 | 7,432 | | | |
| B24 | .scratch, .claude, loginExtensionMulti, web, root | 200 | 1,324 | | | |
| B25 | skipped-file sweep | | | | | |

## Skipped (open PRs / pinned)

Pinned: files patched by public-sync's strip patches (`.claude/skills/public-sync/*.d/*.patch`; comment context lines must keep applying). Never pruned in batch PRs (the equality gate rejects `.patch` edits); they go in one separate hand-edited PR with `strip-regen.sh`, after the batches.

| file | reason | batch | swept |
|---|---|---|---|

## Decisions

- 2026-11-24 TS gate = custom AST walk (JSX whitespace per React rule, empty `{/* */}` dropped) + removeComments printer on non-JSX files; owner suggested printer only — printer alone false-fails JSX comment removal and misses nothing the walk catches.
- 2026-11-24 Shell gate = `shfmt --to-json` AST equality without positions and comments (heredoc `#` lines are content; `--minify` normalised code like `$(( $a*2 ))`).
- 2026-11-24 Runtime docstrings kept as code: files using `__doc__`/getdoc/typer/click (all docstrings), modules/classes/functions named in any `X.__doc__`/`getdoc(X)` repo-wide, FastAPI route handlers (`@x.get/post/...`, `add_api_route` endpoints), pydantic/TypedDict model classes incl. aliases and subclasses repo-wide (OpenAPI descriptions). Equality takes the union of base and head context.
- 2026-11-24 Directives keyed by code position (tokens before them, own-line vs trailing, cookie/shebang line); `{/* */}` between two JSX texts is kept (removal merges React text children).
- 2026-11-24 Strip-then-restore: `comment_strip.py` removes everything mechanically; Sonnet only restores whys. Proven on whole repo: 3,891 files stripped, gate 3,891 ok, floor 44 lines.
- 2026-11-24 Fable (pre-design): continue; add full tests per batch + public-sync dry-run in pilot; source-reading tests (~105) and public-sync strip patches invisible to AST equality. Opus: full-tree strip test run done before batch 1; strip-patch targets pinned via `--skip-file`.
- 2026-11-24 `scripts/fu_hillclimb/hillclimb.py` `typo_sha` hashes `inspect.getsource` of typo functions → key changes once (research cache only); accepted.
- 2026-11-24 CI workflow gates itself on `.claude/REVIEW.md` existing, so it runs only in this repo (Twin/public client PRs would otherwise go red).

## Exceptions kept

| file | comment | why |
|---|---|---|

## Restored after review

| batch | file | line | why |
|---|---|---|---|
