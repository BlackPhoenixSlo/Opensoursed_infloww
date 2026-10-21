# Phase 00 — Merge the finished runs, fix stale docs, publish the route matrix

**Objective.** `main` holds the four finished efforts through one local `merge:` commit, every Effort suite is green on one commit of the Merged tree, the inventory no longer says S4S was dropped, and `docs/infloww-parity-matrix.md` grades every Inventory section and sub-screen.

## Problem Statement

The owner reads `main` and sees a stale project. The Settings tabs show as stubs. The Messages Pro map shows 23 tickets done and 100 ready. The OF Manager connectors and Settings efforts don't exist at all. All of that work is finished, but it sits on the unmerged branch `t3code/recreate-infloww-ui-prompt`, at its finished tip `4c9c7160` (454 commits ahead of `main`'s merge base). The branch has since moved on by one commit, `ff715056`, which a live session added after the runs finished. The inventory says Share for Share was "dropped on purpose", and the roadmap now overturns that. Nobody can answer "how close is Inflowwww to Infloww, screen by screen?" without reading four plans, four maps and two parity docs. Every later Phase of this plan needs one honest baseline to cite, and today there isn't one.

## Solution

The finished branch is merged into `main` locally, with nothing pushed. Its only content conflicts are resolved by observation:
- The landing page keeps `main`'s real sign-in.
- The glossary keeps both sides' sections.

Every Effort suite then runs on that one commit, and the results are recorded. The inventory's stale S4S and section references are corrected. A new Parity matrix lists every Infloww surface with our route, visual evidence, data source, read/write behaviour, permission scope, remaining gap, Matrix status and Inventory version. A short screenshot walk of four key routes checks that the merged tree renders.

## User Stories

1. As the owner, I want the branch `t3code/recreate-infloww-ui-prompt` merged into `main` at its finished tip, so that `main` holds Messages Pro parity, the OF Manager connectors, the Settings tabs and the Messages Pro look-and-feel.
2. As the owner, I want the merge recorded as a `merge:` commit like 8581aead and 9fc6bdba, so that history reads the same as the earlier t3code merges.
3. As the owner, I want nothing pushed, so that I decide when `main` leaves the machine.
4. As the owner, I want the landing page at `/login` to behave exactly as it does on `main` today (Sign in / Register tabs, `?mode=` and `?username=` hand-off from the public site, the back-link to `SITE_URL`), so that the parody-site sign-in shipped in 8581aead is not regressed by the merge.
5. As a maintainer, I want `app/lib/repoUrl.ts` kept from the branch, so that the Settings About tab keeps its single source for the repo URL.
6. As a maintainer, I want `CONTEXT.md` to keep both the branch's glossary sections (OF Manager mirror, Settings layout, Settings storage and the rest) and `main`'s "Infloww parity: next steps" sections, so that no term is lost from either side.
7. As a maintainer, I want the live session's work after the finished tip (commit `ff715056` today, plus anything still uncommitted in the branch worktree) left out of the merge and untouched, so that someone else's in-progress work is neither shipped nor lost.
8. As a maintainer, I want the merge to stop if it produces any conflict other than `app/components/auth/Landing.tsx` and `CONTEXT.md`, so that an unforeseen conflict is not resolved by guessing.
9. As the owner, I want every Effort suite (`.scratch/messages-pro-parity`, `of-manager-connectors`, `settings-tabs` and `messages-pro-look-and-feel`) run on the same commit, with each step's last line recorded, so that the combined tree is shown to be green, not assumed green.
10. As the owner, I want `node scripts/of-mirror.mjs --check` run on that commit, so that the leak guard over the committed OF mirror still passes after the merge.
11. As a maintainer, I want the relay tests the branch touched run on that commit, so that the relay half of the Merged tree is shown green too. The four suites only run `test_settings_api.py`.
12. As the owner, I want every Effort map on `main` to show its true status after the merge (no `ready-for-agent`, no stale claims), so that the 23-done snapshot stops misleading anyone.
13. As a reader of `docs/infloww-screens.md`, I want every "we dropped S4S" statement replaced by a pointer to Phase 3 of `docs/plans/infloww-parity-next-steps.md`, so that the inventory matches the roadmap.
14. As a reader of `docs/infloww-screens.md`, I want the Leaderboard's dangling "see 3.12" pointed at §3.9, so that cross-references resolve.
15. As a reader of `docs/routes.md`, I want the Shift schedule and Share for Share rows to keep saying "stub", and the Settings row to no longer say "stub", so that the route map matches the code.
16. As a reader of `docs/routes.md`, I want one line pointing to the Parity matrix, so that I find the graded view from the route map.
17. As any later Phase, I want `docs/infloww-parity-matrix.md` to have one row for every numbered Inventory section except the containers (§1, §2, §3, §6), so that I can cite a row instead of re-auditing.
18. As any later Phase, I want sub-screen rows for every table row of §3.2 (13 OF Manager items), §3.4 (6 Analytics screens), §3.7 (2), §3.8 (5), §3.9 (3) and §3.10 (11 Settings tabs), and for §3.6's four S4S labels and §4.1's Auto Post and Auto Story, so that no Infloww screen is graded only as part of a bundle.
19. As a reviewer, I want each matrix row to carry the roadmap's columns plus a Matrix status and an Inventory version, so that I can tell matched screens from deliberate upgrades, gaps and unknowns.
20. As a reviewer, I want each row to name its Inventory version (the v5.7.14 capture or the v5.7.20 bundle and help centre), so that old screenshots are not mistaken for current truth.
21. As a reviewer, I want the matrix seeded from the plan's Baseline table, with every Baseline row's evidence carried over and its status mapped to a Matrix status, so that the matrix and the plan agree on day one.
22. As a reviewer, I want cross-cutting rows for "Role permissions enforced server-side" and "Employee identity source" (owner `X-Employee-Id` versus server-side chatter resolution), so that the gaps Phases 1 and 4 close are visible in the baseline.
23. As a reviewer, I want the Messages Pro row and the Settings tab rows to cite `docs/messages-pro-parity.md` and `docs/settings-parity.md` instead of re-grading them, so that signed-off work is not re-litigated.
24. As a reviewer, I want Inflowwww extras labelled per ADR-0003 and phone layouts graded "intentionally improved", so that deliberate improvements are not read as mismatches.
25. As the owner, I want the matrix to record the pre-merge `main` sha, the merge commit sha and each suite's per-step lines, so that the baseline can be reproduced and the merge undone.
26. As the owner, I want `/`, `/employees`, `/settings/time-tracking` and `/messages-pro` walked at 1440×900 and 390×844, in light and in dark, so that the merged tree is seen to render on the four routes later Phases touch first.
27. As the owner, I want those PNGs kept under `/tmp`, and the committed `docs/screenshots/` set left byte-identical, so that no screenshot churn is committed.
28. As the owner, I want a walk cell that no harness can produce recorded as "unverified" in the matrix, with the reason, so that a missing screenshot is never reported as a pass.
29. As the owner, I want the six parked connector tickets (06, 12, 19, 31, 38, 46) left parked and listed in the matrix's remaining-gap column, so that no live check or unknown body is guessed.
30. As a maintainer, I want this plan's own Effort suite to exist after Phase 0 (`.scratch/infloww-parity-next-steps/suite.sh`), checking the matrix's shape and running the relay tests, so that later Phases add steps to one script rather than inventing their own.

## Implementation Decisions

- **Owns.**
  - Git history of `main`: one merge of branch tip `4c9c7160f51aebbf8ac72d3706a1b04a1e3a96b9`.
  - Landing (the signed-out `/login` page component in `app/components/auth`): conflict resolution only.
  - The glossary `CONTEXT.md`: conflict resolution only.
  - The Inventory `docs/infloww-screens.md`: the S4S-dropped lines and the §3.4 cross-reference.
  - The route map `docs/routes.md`: one pointer line.
  - The new Parity matrix `docs/infloww-parity-matrix.md`.
  - The new Effort suite `.scratch/infloww-parity-next-steps/suite.sh`.
- **Interfaces.**
  - Landing's rendered output and behaviour are byte-for-byte `main`'s.
  - The `REPO_URL` export in the repo-URL module stays as the branch has it. Its one importer is the Settings About tab.
  - The new suite follows the house `step name cmd…` format. It prints `name: exit N :: <last line>` per step and exits non-zero if any step fails. It never calls another suite.
- **Schema.** None. The relay migrations `20261013_0100_user_settings` and `20261014_0100_split_inbox` arrive with the merge as they are. Phase 0 runs no migration against any database.
- **Contracts.** The Parity matrix's table is a contract that later Phases edit row by row:
  - **Columns, in this order:** `§` | Infloww surface | Inflowwww route | Visual evidence | Data source | Read/write | Permission scope | Remaining gap | Matrix status | Inventory version.
  - **`§`:** the Inventory number. Sub-screen rows put the number, a space, then the Inventory label (for example `3.2 Vault`). Cross-cutting rows use `X1`, `X2`.
  - **Matrix status:** exactly one of `matched`, `intentionally improved`, `intentionally different`, `not wired`, `unverified`, `missing`, `blocked`.
  - **Inventory version:** contains `v5.7.14` or `v5.7.20` (both when the row draws on both).
  - **No empty cell.** A cell with nothing to say reads `none`.
  - **Permission scope:** names the principal the relay checks for that surface: `user session`, `chatter session`, `user session + X-Employee-Id`, `public`, or `unverified`. Add `(account-scoped)` when the route also passes `X-Account-Id` through the account isolation gate.
  - **Unverified needs a reason.** A row whose Matrix status is `unverified` has a Remaining gap other than `none`.
  - **Walk lines.** The Baseline run holds exactly 16 lines of the form `walk <route> <1440|390> <light|dark>: <pass|unverified (<reason>)>`, one per walk cell.

**The merge.**
- **Who does what.** The implementer runs `git merge --no-ff --no-commit 4c9c7160f51aebbf8ac72d3706a1b04a1e3a96b9` in the main checkout, on `main`, with no tracked changes. It resolves the conflicts and stages them. The coordinator makes the commit with a message starting `merge: ` that names the four efforts. This keeps the house rule that only the coordinator commits.
- **Why the pinned sha.** The merge uses the pinned sha, not the branch name. The live session in the branch worktree may commit more, and only the finished tip is in scope.
- **Re-check before merging.** Run `git merge-tree --write-tree --name-only main 4c9c7160f51aebbf8ac72d3706a1b04a1e3a96b9` first. If it lists any conflicted path other than `app/components/auth/Landing.tsx` and `CONTEXT.md`, the ticket parks with that list and does not merge.

**The Landing conflict, decided by observing both sides.**
- **Branch side.** The branch's only change to the file since the merge base 957cd779 is a refactor. It imports `REPO_URL` and puts it in place of the hard-coded GitHub `href` in an "I host this for my friends" paragraph (`git diff 957cd779 4c9c7160 -- app/components/auth/Landing.tsx`).
- **Main side.** `main` rewrote the page for the parody-site sign-in (8581aead, 9fc6bdba). That paragraph is gone, the page links back to `SITE_URL` instead, and `Landing.test.tsx` pins the new behaviour.
- **Deviation from the plan, stated.** The plan's Work item 1 says to keep "the branch's `REPO_URL` import". This spec drops it, because the only use of the import is in a paragraph `main` deleted, so it would be a dead import. The rest of that item (keep `main`'s parody-site behaviour) is honoured in full. See the first ASSUMPTION in Further Notes.
- **Resolution.** The resolved file is `main`'s file exactly, with both hunks taken from `main`. The `REPO_URL` import is dropped, because nothing on `main`'s page uses it. The lint config makes an unused import a warning, not an error, but a dead import is still not kept. `app/lib/repoUrl.ts` and the Settings About tab arrive from the branch untouched.

**The CONTEXT.md conflict.** This conflict is not in the plan. It appeared because `main` gained 17c6922c (the glossary section for this plan) after the plan's merge-tree run, which is observation by today's `git merge-tree`. Both sides only append new sections after the same line.
- **Resolution.** Keep the branch's block (Colour through the Settings sections, under `## Language`) first, then `main`'s block ("Infloww parity: next steps" through "Parity evidence") at the end of the file, so the branch's sections stay under their own headings and the new section's "not repeated here" intro stays true.
  ASSUMPTION: branch first, main's section last (rung 3, each side appends at its end; reviewer round 1 showed main-first nests ~45 branch terms under the new heading). Overturned if the owner wants the new section interleaved. (was: `main`'s block first, then the branch's block (Colour, OF Manager mirror, Mirror controls, OnlyFans posting, Settings layout, Settings storage and the rest).
- **Check.** No bold term appears twice in the union (`uniq -d` over the `**Term**:` lines is empty).

**Stale docs.** These edits come only where the Merged tree is wrong.
- **Inventory: S4S.** Change five places:
  - §1.1 row 6's "**We dropped S4S**"
  - §2's "none (dropped)"
  - the §3.6 heading
  - §3.6's "**Dropped on purpose** [GAP]. No route." bullet
  - §4's "which we dropped"

  Each now says that S4S is planned in Phase 3 of `docs/plans/infloww-parity-next-steps.md`, bounded to this deployment's agencies (ADR-0011), and that `/share-for-share/[section]` is a stub until then.
- **Inventory: §3.4.** The Leaderboard's "see 3.12" becomes "see 3.9".
- **Route map.** `docs/routes.md` gains one sentence under its intro pointing to `docs/infloww-parity-matrix.md` for grades. Its rows already come out right after the merge, since the branch fixed the Settings row (merge-tree auto-merges it). So: no other edit.
- **Not edited.** `archive/` and `ui-redesign/infloww-exact/INFLOWW_GAP_TO_BUILD.md` also say S4S was dropped. They are the July gap analysis, which the roadmap calls "evidence to re-check, not current truth".

**The Parity matrix.** `docs/infloww-parity-matrix.md` holds four sections in this order:
1. **Header.** What the file is, the column and Matrix status definitions (the glossary's), and the rule that later Phases edit rows in place.
2. **Baseline run.**
   - The pre-merge `main` sha and the merge commit sha.
   - Each Effort suite's per-step `name: exit N :: …` lines and the `of-mirror.mjs --check` result, all from the merge commit.
   - The walk's results.
3. **Matrix.** The table.
4. **Labelled improvements.** Inflowwww-only features graded "intentionally improved", each with its ADR-0003 label.

The rows follow these rules:
- **Coverage.** There is one row per numbered heading of the Inventory except §1, §2, §3 and §6 (containers or not an Infloww surface), plus the sub-screen rows in user story 18, plus X1 (role permissions enforced server-side) and X2 (Employee identity source).
- **Seeding.** Rows are seeded from the plan's Baseline table. The evidence carries over, and the Baseline status maps to a Matrix status:
  - done → `matched`, except where the row is an Inflowwww extra, which gets `intentionally improved`
  - partly → `not wired` or `unverified`, whichever the evidence supports
  - missing → `missing`
  - intentionally different → `intentionally different`, or `intentionally improved` for phone layouts
  - blocked → `blocked`
- **Signed-off areas.** The Messages Pro row grades `matched` from `docs/messages-pro-parity.md`. Each Settings tab row copies its grade from `docs/settings-parity.md`. Neither is re-graded.
- **Remaining gap.**
  - The OF Manager rows' gap column names the parked connector tickets they carry (06, 12, 19, 31, 38, 46).
  - The X2 row's gap names the owner-session `X-Employee-Id` path (`service/employees.py` `resolve_outbound_employee_id`) that Phase 1 leaves as it is.
- **Privacy.** No real creator, fan or account name appears anywhere in the file.

**The walk.** Plan item 5 is covered by three runs:
- **`scripts/ui-shots.sh`.** It covers `/messages-pro` at 1440 and 390 in its own throwaway stack, including its light-theme colour check.
  - It writes into the committed `docs/screenshots/`. So the set is copied to `/tmp/infloww-parity-p0/before/` first, the harness outputs are copied to `/tmp/infloww-parity-p0/ui-shots/` after, and the backup is copied back. `git status --porcelain -- docs/screenshots` must then be empty.
  - Exit 3 (a missing prerequisite or the legacy secret store) parks the cell with the exact command for the human. The implementer never moves secret files.
- **`scripts/settings-check/walk.py`.** Run with the venv's Python against `next dev --webpack -p 3091`. It covers `/settings/time-tracking` at both sizes in dark, and the light pass on `/settings/account`.
  - `next dev` can rewrite `app/tsconfig.json` and `app/next-env.d.ts`, so both are backed up first and restored after, as ui-shots does.
- **A throwaway Playwright pass.** It is written under `/tmp`, never committed, and copies walk.py's synthetic mock routing and off-host abort. It covers what neither harness does: `/` and `/employees` at both sizes in both themes (`chatterly:theme`), and `/settings/time-tracking` in light.
  - Its PNGs go to `/tmp/infloww-parity-p0/walk/`.
  - Each cell passes when it shows no 404, no "is not built yet." on these four routes, no console error, and no horizontal overflow at 390.
  - A cell it cannot produce becomes `unverified` in the matrix's Visual evidence column, with the reason.

**When a suite or harness fails.** A missing suite, a failing suite step or a failing `--check` on the merge commit parks the Phase with the verbatim `name: exit N :: …` lines. Phase 0 adds no behaviour, so it fixes no code. The merge stays staged or committed as it is, and the human decides. A harness exit 3 is not a failure: those cells read `unverified` with the exact command for the human.

**Reversibility.** The merge is local. The way back is the human's `git reset --hard <pre-merge sha>`, using the sha recorded in the matrix's Baseline run. No subagent runs a reset.

## Testing Decisions

- **One seam per concern, the highest available.**
  - The merged code is tested only through the existing Effort suites (typecheck, lint and vitest over `app/`, with the settings-api relay test) and `node scripts/of-mirror.mjs --check`. No new code test is written: Phase 0 adds no behaviour.
  - Landing's behaviour is pinned by `main`'s existing `app/components/auth/Landing.test.tsx` (mode from the URL, the `?username=` hand-off, the `SITE_URL` back-link). It runs inside the vitest step.
  - The relay half is seen through the five relay tests the branch touched or added: `test_account_config_api.py`, `test_account_isolation_gate.py`, `test_settings_api.py`, `test_settings_transfer.py` and `test_split_inbox_api.py`. They are plain-assert scripts run with `./venv/bin/python`, inside the new suite. `main` changed no `service/` file since the merge base, so the relay equals the branch's relay.
  - The Parity matrix's shape is checked by the new suite's `matrix` step. It is a pure text check of the contract above:
    - every required `§` id is present
    - every row has ten cells, none empty
    - every Matrix status is in the set
    - every Inventory version names `v5.7.14` or `v5.7.20`
    - every `unverified` row has a Remaining gap other than `none`
    - the Messages Pro row cites `docs/messages-pro-parity.md`, and every §3.10 tab row cites `docs/settings-parity.md`
    - the Baseline run holds the 16 walk lines and one recorded line per Effort suite step
  - Rendering is checked by the existing harnesses (`scripts/ui-shots.sh`, `scripts/settings-check/walk.py`) and the throwaway pass. None of them is changed.
- **Prior art.** `.scratch/settings-tabs/suite.sh` (the suite format, including a relay test step), `scripts/settings-check/walk.py` (mocked headless walk), `scripts/ui-shots.sh` (throwaway stack), and `app/components/auth/Landing.test.tsx`.

## Acceptance

```sh
set -e
cd "$(git rev-parse --show-toplevel)"
TIP=4c9c7160f51aebbf8ac72d3706a1b04a1e3a96b9

# 1. The merge: one merge: commit whose second parent is the pinned tip; nothing tracked left dirty; nothing pushed.
M=$(git rev-list --merges --parents HEAD | awk -v t="$TIP" '$3 == t {print $1; exit}')
test -n "$M"
git log -1 --format=%s "$M" | grep -q '^merge: '
test "$(git rev-parse "$M^2")" = "$TIP"
test "$(git rev-parse --abbrev-ref HEAD)" = main
git merge-base --is-ancestor "$M" main
grep -q "$(git rev-parse "$M^1")" docs/infloww-parity-matrix.md   # pre-merge main sha recorded
# only the two foreseen paths conflicted
test "$(git merge-tree --write-tree --name-only "$M^1" "$TIP" | sed -n '2,/^$/p' | grep -v '^$' | LC_ALL=C sort | tr '\n' ' ')" = "CONTEXT.md app/components/auth/Landing.tsx "
test -z "$(git status --porcelain --untracked-files=no)"
# manual: the owner decides when to push; `git status -sb` shows main ahead of origin/main.

# 2. Conflicts resolved by observation: Landing is main's side byte-for-byte; repoUrl kept; glossary is the union.
git diff --quiet "$M^1" "$M" -- app/components/auth/Landing.tsx
! grep -q 'REPO_URL' app/components/auth/Landing.tsx || exit 1
grep -q 'export const REPO_URL' app/lib/repoUrl.ts
grep -q 'REPO_URL' app/components/settings/AboutTab.tsx
! grep -nE '^(<<<<<<<|=======|>>>>>>>)( |$)' CONTEXT.md app/components/auth/Landing.tsx || exit 1
grep -q '^### Parity evidence' CONTEXT.md
grep -q '^### Settings storage' CONTEXT.md
test -z "$(grep -oE '^\*\*[^*]+\*\*:' CONTEXT.md | sort | uniq -d)"

# 3. The live session's uncommitted files did not ride along.
! git cat-file -e "HEAD:app/components/chat/MessageList.media.test.tsx" 2>/dev/null || exit 1

# 4. Effort maps tell the truth after the merge.
for e in messages-pro-parity of-manager-connectors settings-tabs messages-pro-look-and-feel; do
  test -f ".scratch/$e/map.md"
  ! grep -E '^\| [0-9]+ \|' ".scratch/$e/map.md" | grep -qE 'ready-for-agent|claimed' || exit 1
done

# 5. Stale docs fixed.
! grep -nE 'We dropped S4S|none \(dropped\)|we dropped it|Dropped on purpose|which we dropped|see 3\.12' docs/infloww-screens.md || exit 1
grep -q 'infloww-parity-next-steps' docs/infloww-screens.md
grep -q 'infloww-parity-matrix.md' docs/routes.md
grep -E '^\| Employees > Shift schedule' docs/routes.md | grep -q 'stub'
grep -E '^\| Share for Share' docs/routes.md | grep -q 'stub'
! grep -E '^\| Settings \|' docs/routes.md | grep -qi 'stub' || exit 1

# 6. Every Effort suite that exists on the Merged tree, on this one commit (includes this plan's suite: matrix shape + relay tests).
# Commits after M touch only docs and .scratch, so code results at HEAD are M's results.
test -z "$(git diff --name-only "$M" HEAD -- app service scripts)"
ls .scratch/*/suite.sh
for s in .scratch/*/suite.sh; do echo "== $s"; sh "$s"; done
for e in messages-pro-parity of-manager-connectors settings-tabs messages-pro-look-and-feel; do grep -q "$e" docs/infloww-parity-matrix.md; done
node scripts/of-mirror.mjs --check
grep -q "$M" docs/infloww-parity-matrix.md   # the Baseline run records the merge commit

# 7. The walk: harnesses pass, committed screenshots and dev-server-rewritten files untouched.
P=/tmp/infloww-parity-p0; rm -rf "$P"; mkdir -p "$P/before" "$P/ui-shots"
cp -Rp docs/screenshots/. "$P/before/"
rc=0; scripts/ui-shots.sh || rc=$?
cp -p docs/screenshots/messages-pro-*.png docs/screenshots/clone-messages-pro.png "$P/ui-shots/" 2>/dev/null || true
cp -Rp "$P/before/." docs/screenshots/
test "$rc" -eq 0 || { test "$rc" -eq 3 && grep -q '^walk /messages-pro .*unverified' docs/infloww-parity-matrix.md; }
test -z "$(git status --porcelain -- docs/screenshots)"
cp -p app/tsconfig.json app/next-env.d.ts "$P/"
(cd app && exec pnpm exec next dev --webpack -p 3091) > "$P/next-dev.log" 2>&1 &
DEV=$!
for i in $(seq 1 90); do curl -sf -o /dev/null http://127.0.0.1:3091/ && break; sleep 2; done
wr=0; PORT=3091 ./venv/bin/python -I scripts/settings-check/walk.py > "$P/settings-walk.jsonl" || wr=$?
kill "$DEV" 2>/dev/null || true; wait "$DEV" 2>/dev/null || true
cp -p "$P/tsconfig.json" "$P/next-env.d.ts" app/
test "$wr" -eq 0
test -z "$(git status --porcelain --untracked-files=no)"
# manual: the throwaway /tmp Playwright pass over / and /employees (both sizes, both themes) and /settings/time-tracking (light) is run by the implementer; its outcome is in the matrix's 16 walk lines, whose count and format the suite's matrix step checks.
```

## Depends on

None. Phase 0 is the first Phase. It needs only the read-only branch `t3code/recreate-infloww-ui-prompt` at `4c9c7160` and `main`.

## Out of Scope

- **Pushing `main` or the branch.** Floor 2 forbids it, and the owner decides when.
- **The six parked connector tickets (06, 12, 19, 31, 38, 46).** They need live checks or unknown request bodies (floor 2, and the roadmap's "do not guess a request body"). The matrix lists them.
- **Re-grading Messages Pro or Settings visuals.** Both are signed off. Their matrix rows cite the parity docs.
- **The live session's work after the finished tip.** It is now committed on the branch as `ff715056` (Composer, VaultPicker, MessageList, format, relay, `useComposerUploads` and the rest; `git diff --stat 4c9c7160 ff715056` lists 21 files). Merging the pinned sha leaves it out, and acceptance step 3 checks one of its files is absent.
- **Commits made on the branch after `4c9c7160`.** They are not part of the finished runs. If any exist, a later merge is the owner's call.
- **Scrubbing the absolute home paths that `scripts/check-public-export.sh` flags.** The settings-tabs RUN.md leaves this to the human.
- **Editing `archive/` or `ui-redesign/infloww-exact/` notes that say S4S was dropped.** They are July evidence, not current docs.
- **A committed route-walk harness or new screenshot sets.** YAGNI. Phase 0 walks four routes. A throwaway `/tmp` pass covers the cells the existing harnesses don't, and PNGs never enter the repo.
- **Running any Alembic migration.** The merge brings the migration files only. Nothing here touches a database.
- **Grading rows beyond what current evidence supports.** A row without fresh evidence is `unverified`, and Phase 6 re-walks every route.

## Further Notes

ASSUMPTION: the resolved `Landing.tsx` is `main`'s file exactly, with no `REPO_URL` import, although the plan says to keep "the branch's `REPO_URL` import". Rung 1: the branch's only change to the file swaps a hard-coded `href` for `REPO_URL` in a paragraph that `main` deleted (`git diff 957cd779 4c9c7160 -- app/components/auth/Landing.tsx`; `main`'s Landing has no GitHub link), so the import would be dead. `app/lib/repoUrl.ts` itself is kept. Overturned if the owner wants the "I host this for my friends" repo link back on the landing page. That would be a new change, not a merge resolution.

ASSUMPTION: `CONTEXT.md` is a second conflict the plan did not list, and it is resolved as the union, with `main`'s block first. Rung 1: `git merge-tree --write-tree --name-only main t3code/recreate-infloww-ui-prompt` today lists `CONTEXT.md` and `app/components/auth/Landing.tsx`. Both sides only append sections, and no term repeats. Rung 3 orders `main` first, as in every earlier merge where `main` is the first parent. Overturned if a term turns out to be defined differently on the two sides.

ASSUMPTION: the merge takes the pinned sha `4c9c7160` instead of the moving branch name. Rung 4: the worktree has an active session that may commit, and the plan's reconcile counted the runs at that tip. Overturned if the owner wants later branch commits included.

ASSUMPTION: the implementer stages the merge (`--no-commit`) and the coordinator commits it. Rung 2: the repo rule for subagents ("Never … `git commit` … Only the coordinator commits") together with the Phase note that the implementer performs the merge.

ASSUMPTION: Phase 0 creates `.scratch/infloww-parity-next-steps/suite.sh` with two steps, `matrix` (shape check) and `relay` (the five relay tests), and it never calls another suite. Rung 3: every finished effort has `.scratch/<effort>/suite.sh`, and `settings-tabs`' suite already runs a relay test. Ownership of this plan's suite is settled once, in the same words in Phase 0 and Phase 6 (six-hats review): Phase 0 creates `.scratch/infloww-parity-next-steps/suite.sh` with two steps, `matrix` and `relay`. Phases 1–5 do not edit it; each runs its own tests in its own Acceptance block, so Phases that run in the same wave (2 and 3) never collide on one file. Phase 6 alone extends it to its final form. Rung 4 for the split: one later writer is cheaper to undo than five. Overturned if the owner wants every Phase to append its own tests as it lands, in which case each Acceptance block of Phases 1–5 gains one `relay` line.

ASSUMPTION: the relay tests run here are the five the branch touched or added, not all 228. Rung 5: `main` changed no `service/` file since the merge base (`git diff --stat 957cd779 main -- service` is empty), so the Merged tree's relay is the branch's relay. Overturned by any relay failure that shows up during the walk's relay-backed ui-shots stack.

ASSUMPTION: the matrix uses seven Matrix status values, the plan's six plus `intentionally different` for Leaderboard and Referrals, and it treats §1, §2, §3 and §6 as containers or non-surfaces without rows of their own. Rung 3 for the seventh value: the glossary's Matrix status entry already defines it. Rung 5 for the containers: their content is fully covered by their numbered children, our route map or the unknowns list. Overturned if the owner grades those surfaces `blocked`, or wants container rows.

ASSUMPTION: the Messages Pro row and the 11 Settings tab rows copy their grades from `docs/messages-pro-parity.md` and `docs/settings-parity.md` without a re-walk. Rung 2: the plan's Phase 0 Out of scope says "Re-grading Messages Pro or Settings visuals (both are signed off)". Overturned by a walk cell in this Phase that fails on those routes. That cell's row then reads `unverified`, with the failure.

ASSUMPTION: the four-route walk uses the two existing harnesses where they reach, plus a throwaway `/tmp` Playwright pass that copies walk.py's mock routing for the cells they don't reach (`/` and `/employees` entirely, `/settings/time-tracking` in light). Rung 5: neither harness covers those cells, and a committed new harness is more than the plan asks for. Overturned if the owner wants a committed route-walk harness, which Phase 6 would then own.

## Review

codex, 2026-10-16. Raw outputs: `.scratch/infloww-parity-next-steps/review/phase-00-blind.md` and `phase-00-draft.md`.

**Blind call**
- B1 Alternatives (keep the branch as base, selective integration): **reject**. The plan's Work item 1 decides the merge, which makes it a binding constraint. The plan's own fallback (the branch as base if the owner declines) stays the owner's call.
- B2 No row-granularity or completeness rule against the route tree: **partial**. The spec already fixes coverage (stories 17–18, Coverage rule) and the matrix step checks every required `§` id. A check against every `page.tsx` is not asked by the plan, which keys rows to the Inventory. Phase 6 walks every `nav.ts` route.
- B3 Permission scope has no vocabulary and could hide which principal is authorised: **accept**. Contracts now fix the cell's values (`user session`, `chatter session`, `user session + X-Employee-Id`, `public`, `unverified`, plus `(account-scoped)`).
- B4 No rule for a missing or failing suite: **accept**. New "When a suite or harness fails" decision: park with the verbatim lines, fix no code in Phase 0. Harness exit 3 means `unverified`.
- B5 Privacy of screenshots and matrix not checked: **partial**. PNGs stay under `/tmp` and use the harnesses' synthetic fixtures, and the matrix's Privacy rule stands. An automated name check is rejected, because it would need real names in the repo to grep for.
- B6 Test each row at the route→relay→service seam with own/foreign/unauthenticated cases: **reject**. Phase 0 seeds the matrix from the Baseline and adds no behaviour. Server-side permission tests belong to Phases 1 and 4, and X1/X2 show the gap.
- B7 The reconcile snapshot is stale (branch now `ff715056`, `17 455`): **accept**. Observed: `git log 4c9c7160..t3code/recreate-infloww-ui-prompt` is one commit, `ff715056`, holding the live session's 21 files. The pinned sha already excludes it. The Problem Statement, story 7 and Out of Scope now say so.
- B8 "No eligible ticket remains" has no reproducible check: **reject**. Acceptance step 4 already greps every Effort map for `ready-for-agent` or `claimed`.
- B9 The Dashboard row is not graded yet: **reject**. The Seeding rule and Out of Scope already grade a row with no fresh evidence as `unverified`.
- B10 The checkout has user changes: **partial**. The merge runs only with no tracked changes (The merge, "Who does what"). The untracked effort files do not collide: `git ls-tree -r --name-only 4c9c7160 -- .scratch/infloww-parity-next-steps` is empty.

**Draft call**
- D1 Dropping `REPO_URL` from Landing contradicts plan Work item 1: **partial**. The decision stands on rung 1: the import's only use is in a paragraph `main` deleted, and `main`'s Landing imports only `SITE_URL` (`git show main:app/components/auth/Landing.tsx`). The deviation is now stated in Implementation Decisions, not only in Further Notes. Keeping a dead import would also pass lint, since `eslint` is run without `--max-warnings` (`app/package.json`), so the owner can reverse this at no cost.
- D2 This plan's suite and the five relay tests are unrequested scope: **reject**. Plan Phase 6 (plan line 305) runs "every effort suite plus this plan's suite", so the suite has to exist from some Phase. Phase 0 is where its first contract (the matrix) lands. Recording per-step lines is a superset of "the last line", and the house suites print one line per step anyway.
- D3 The matrix check is shape-only, so wrong grades pass: **partial**. The matrix step now also checks that `unverified` rows carry a reason, that Messages Pro and §3.10 rows cite their parity docs, and that the 16 walk lines and the per-suite lines are present. A full Baseline→status mapping check is not added, because "partly → `not wired` or `unverified`" is a judgment call that text matching cannot settle.
- D4 The walk acceptance does not check coverage, and `test "$rc" -eq 0` contradicts the exit-3 rule: **accept**. Exit 3 now passes only if the matrix records `/messages-pro` cells as `unverified`. The throwaway pass's cells are checked through the 16 walk lines the matrix step counts.
- D5 Merge checks do not prove the merge is on `main`, the first parent is recorded, or the conflicts were only the two: **accept**. Acceptance step 1 now checks the branch, ancestry, the recorded `M^1`, and the exact conflict set via `git merge-tree` (verified today: `CONTEXT.md app/components/auth/Landing.tsx`).
- D6 Suites run at HEAD, not M, and the per-suite records are not checked: **accept**. Step 6 now asserts that no `app`, `service` or `scripts` path changed between M and HEAD, which makes HEAD's code results M's results. It also greps the matrix for each Effort suite's name.

### Six hats

Six-hats report, 2026-10-16 (`.scratch/infloww-parity-next-steps/review/six-hats.md`), reconciled as the Adversary brief does.

- White (Set / phase-00), the merge is only assumed and `ff715056` sits on the branch past the pinned tip, so `main` stays behind after Phase 0: **accept**, no spec change. The spec already pins `4c9c7160` and leaves `ff715056` out (Out of Scope, acceptance step 3). The second merge it needs is now on the plan's Needs the human list.
- Red (phase-00), Phase 0 is the real payoff and everything after rests on a parked human decision: **reject on constraint**. The plan proceeds on the merge ASSUMPTION and lists the merge under Needs the human, and the invocation (`--execute --tickets 999`) binds the plan's order.
- Black (suite.sh ownership stated twice, phase-00:261 vs phase-06:236): **accept**. One rule, written in the same words here and in Phase 6: Phase 0 creates the suite with `matrix` and `relay`, Phases 1–5 leave it alone, and Phase 6 alone extends it. Rung 4: one later writer, and no collision between Phases 2 and 3, which share a wave.
- Yellow (one matrix, closed status set, Inventory version on every row): **accept**, no change.
- Blue (ticket and run Phase 0 alone, re-check the merge-tree conflict set then, gate Phase 1 on a green matrix): **partial**. The re-check is already acceptance step 1, which runs `git merge-tree` at merge time. The gate already holds: Phase 1 depends on Phase 0, and Phase 0's acceptance runs the matrix step. Running Phase 0 alone and holding the rest is rejected on constraint (invocation order).
