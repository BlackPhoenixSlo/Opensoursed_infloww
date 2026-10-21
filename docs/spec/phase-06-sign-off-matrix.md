# Phase 06 — Visual and functional sign-off matrix

**Objective.** Every route in the app's route tree has been walked locally at 1440×900 and 390×844, light and dark. Every Parity matrix row carries a final Matrix status and its Inventory version. Every Effort suite, plus this plan's suite, is green on one recorded commit. A reviewer can tell each deliberate Inflowwww improvement from a mismatch.

## Problem Statement

After Phases 0–5 the Merged tree has new surfaces: Agency context, Shifts and time tracking, Share for Share, Applied Settings, Employees, Sales records, Notifications and others. Each of these was checked only on its own Phase's seams. A reviewer, or the owner deciding whether Inflowwww "is Infloww", can't answer three questions from one place:

- Which screens match the saved Infloww evidence?
- Which screens differ on purpose, and which differ by accident?
- Which screens are still placeholders?

The Phase 0 Parity matrix was seeded from the plan's Baseline table before any of that work landed. So its grades are a forecast, not an observation. The Infloww account is banned, so nobody can capture a fresh authenticated screen to compare against. That makes it easy to overclaim "1:1" parity that nobody actually verified.

## Solution

A reviewer opens `docs/infloww-parity-matrix.md` and finds the following:

- **A sign-off line.** It names the commit where every suite and walk ran, with each suite's last output line.
- **A graded row for every Inventory section and sub-screen.** Each row carries:
  - its Matrix status (matched, intentionally improved, intentionally different, not wired, unverified, missing, blocked);
  - its Inventory version (v5.7.14 capture, v5.7.20 bundle and help centre, or both);
  - the evidence it was graded against;
  - a Phone column;
  - its remaining differences, tagged by kind: layout, typography, responsive, labels, states, dialogs, keyboard, navigation.
- **A "Labelled improvements" section.** It lists every deliberate departure and where the UI labels it.

A throwaway local route walk produces the screenshots behind the grades. It lives under `/tmp` and is never committed, as Phase 0's walk pass did (plan: "with the existing harnesses"). It runs headless Chromium against `next dev` on 127.0.0.1, with the relay mocked and every off-host request aborted. It also fails when the matrix and the running app disagree:

- a route with no row;
- a placeholder page graded as built;
- a built page graded "missing";
- a phone layout not marked as an improvement.

No PNG from this walk is committed.

## User Stories

1. As a reviewer, I want one document that grades every Infloww surface against Inflowwww, so that I don't have to read six specs and four parity docs to know where the product stands.
2. As a reviewer, I want each row's grade to use the seven Matrix status values from the glossary and nothing else, so that "partly" and "done" can't hide a gap.
3. As a reviewer, I want each row to name its Inventory version (v5.7.14 or v5.7.20), so that I know how fresh the evidence behind the grade is.
4. As a reviewer, I want each row to cite the evidence it was graded against (a C[...] tag, a Clone file, a bundle selector or a help article id), so that I can re-check it myself.
5. As a reviewer, I want no row and no sentence in the matrix to claim "verified 1:1" parity, so that the account ban's limits on the evidence are honest.
6. As a reviewer, I want a row whose evidence is only a guess (G) graded "unverified" rather than "matched", so that a guess never reads as a confirmation.
7. As a reviewer, I want each row's remaining differences recorded under the roadmap's kinds (layout, typography, responsive behaviour, labels, empty/loading/error states, dialogs, keyboard use, navigation), so that I can tell what kind of mismatch is left.
8. As a reviewer, I want every phone layout marked "intentionally improved" in its own column, so that nobody mistakes a 390×844 screen for evidence-based 1:1 work.
9. As a reviewer, I want a "Labelled improvements" section listing the bounded S4S, shift tracking with audit history, the explicit Not wired and "Not applied yet" labels, phone layouts, and the Auto Post / Auto Story automations, so that the deliberate upgrades are visible in one place.
10. As a reviewer, I want each labelled improvement to say where the UI marks it (tooltip "Inflowwww extra", the Legacy flag, an Extras overflow, a "not wired" tooltip, a "Not applied yet" note), so that I can confirm the label exists on screen.
11. As a reviewer, I want Inflowwww-only workflows kept and graded "intentionally improved", never removed to imitate Infloww, so that the product keeps its stronger features.
12. As a reviewer, I want Leaderboard, Referrals, the platform selector, Idle mode, the update prompt and Help center content to keep explicit rows with their parked or intentionally different grade, so that what isn't built is listed rather than silently missing.
13. As an owner, I want one sign-off line naming the commit where every Effort suite, this plan's suite and every walk passed, so that I know the grades describe one real tree.
14. As an owner, I want the only change between that commit and the tip to be the matrix itself, so that a later code change can't ride on an old sign-off.
15. As an owner, I want each suite's last output line copied into the sign-off section, so that the evidence of green is in the doc and not only in a terminal.
16. As a developer, I want a route walk that reads its routes from the app's route tree (Sidebar, Sidebar footer, Settings tabs, `legacy` entries skipped), so that a route added by any Phase is walked without editing the walk.
17. As a developer, I want the walk to shoot each route at 1440×900 and 390×844, in the dark default and the light theme, into a directory under `/tmp`, so that the four views exist for grading and nothing lands in git.
18. As a developer, I want the walk to mock the relay with Playwright routes and synthetic data only, so that it needs no relay, no database and no account.
19. As a developer, I want any request to a host other than 127.0.0.1 or localhost to be aborted and to fail the walk, so that a screenshot run can never fetch from the network or log in anywhere real.
20. As a developer, I want the walk to fail on a 404 (HTTP status or Next's not-found fallback), an uncaught page error or a console error on any route, so that a broken route can't be graded.
21. As a developer, I want the walk to fail when a route scrolls sideways at 390×844, so that the phone layout claim holds.
22. As a developer, I want the walk to record every non-GET request and fail if a plain page load writes anything, so that walking a page can't mutate state.
23. As a developer, I want an error pass at 1440×900 in dark, with every mocked relay GET answering 500, that fails on an uncaught page error or Next's error overlay and saves a shot, so that each route's error state is captured and graded.
24. As a developer, I want the walk to fail when a walked route has no matrix row, and when a route a matrix row names is neither walked nor owned by a named harness, so that the matrix and the walk cover the same routes in both directions.
25. As a developer, I want the walk to fail when a route renders the "is not built yet." placeholder but a matrix row naming it is graded anything other than missing, blocked or intentionally different, so that a placeholder can't be signed off as built.
26. As a developer, I want the walk to fail when a route renders a real page but a row naming it is graded "missing", so that the matrix can't lag behind the code.
27. As a developer, I want the walk to fail on a row with a Matrix status or Inventory version outside the allowed values, or whose Phone column breaks the phone rule, so that the matrix's vocabulary stays closed.
27a. As a developer, I want the walk to shoot every route a matrix row names even when no Sidebar or Settings link reaches it (for example `/notifications`, reached from the top bar bell), so that a surface outside the nav can't keep a grade nobody shot.
28. As a developer, I want the walk to shoot each Clone page that a matrix row cites as visual evidence at 1440×900, with its off-host font requests aborted, so that the grader has the evidence beside our shot without fetching anything.
29. Cut by the six-hats review (YAGNI): a self-test switch for the walk. The walk is a throwaway `/tmp` script, so a self-test of it proves nothing a later run can rely on. Each gate still writes its own check line to `report.json`.
30. As a developer, I want the existing harnesses (`scripts/ui-shots.sh` for Messages Pro, `scripts/settings-check/walk.py` for Settings, `scripts/of-mirror-check/navigate.py` for OF Manager) re-run on the sign-off commit, so that the deep checks they already own count toward the sign-off.
31. As a developer, I want this plan's suite, `.scratch/infloww-parity-next-steps/suite.sh`, to run typecheck, lint, vitest and the relay tests that Phases 1–5 added, in the house one-line-per-step format, so that this effort has an Effort suite like the four before it.
32. As a developer, I want the whole relay test suite (`scripts/run-tests.sh`) and `node scripts/of-mirror.mjs --check` run on the sign-off commit, so that "backend tests" and the mirror's leak guard are part of the sign-off.
33. As a developer, I want any mismatch bigger than a label or a test path filed as a new ticket in the Phase that owns the area, so that this Phase grades and does not rebuild.
34. As a developer, I want label fixes and stale test paths found during the walk fixed in this Phase, so that small honest corrections don't wait for another run.
35. As a developer, I want a `docs/routes.md` row that the walk contradicts and that its owning Phase left stale (Phases 2 and 3 own their own rows) corrected as a label fix, so that the route map agrees with the matrix.
36. As an owner, I want no real creator, fan or account name in any shot, mock or matrix row, so that the sign-off artefacts can be shared.

## Implementation Decisions

- **Owns.**
  - **The Parity matrix** (`docs/infloww-parity-matrix.md`). Phase 0 creates it. This Phase adds the Phone column, the final grades and differences, the sign-off section and the "Labelled improvements" section.
  - **The Route walk.** A throwaway headless Playwright script at `/tmp/route-walk-src/walk.py`, never committed. It copies the Settings walk's mock routing, as Phase 0's `/tmp` pass does. What this spec fixes is its output contract (`report.json` and the shots), which Acceptance reads.
  - **This plan's suite** (`.scratch/infloww-parity-next-steps/suite.sh`).
  - **Label-only and test-path-only fixes** in any module.
  - **Stale rows in `docs/routes.md`** that the walk contradicts and the owning Phase left behind, as label fixes only.

- **Interfaces.**
  - **The Route walk.**
    - Inputs:
      - env `PORT`, the port of an already running `next dev`, default 3091 (Settings walk precedent);
      - env `ROUTE_WALK_OUT`, default `/tmp/route-walk`.
    - It takes no arguments.
    - Outputs:
      - `<out>/<slug>-<1440|390>-<dark|light>.png`;
      - `<out>/<slug>-error.png`;
      - `<out>/clone-<name>.png`;
      - `<out>/report.json`, `{"routes": [...], "checks": [...]}`: each route with its source (`nav` or `matrix`), its placeholder flag, its write list and its shot paths; each check as `{"check","want","got","ok"}`;
    - Exit codes:
      - 0: all checks pass;
      - 1: a check failed;
      - 2: usage;
      - 3: a prerequisite is missing (venv Playwright, cached Chromium; it installs nothing);
      - 4: no dev server on `PORT`.
  - **The Parity matrix.** Gains a `Phone` column. Its `Remaining gap` cell takes kind tags (`[layout] [type] [responsive] [labels] [states] [dialogs] [keyboard] [nav]`). It gains a `## Sign-off` section and a `## Labelled improvements` section. Phase 0's other columns are unchanged.
  - **This plan's suite.** House format, one line per step, `/tmp/suite-<name>.log`. It exits non-zero if any step fails.

- **Schema.** None. No table, no migration.

- **Contracts.**
  - **The matrix as the walk reads it.** The matrix is a Markdown table whose header names at least `Route`, `Visual evidence`, `Matrix status`, `Inventory version`, `Phone` and `Remaining gap`.
    - `Route` holds zero or more backticked app paths.
    - `Visual evidence` may cite Clone files as `ui-redesign/infloww-exact/<name>.html`.
    - `Matrix status` is one of the seven glossary values.
    - `Inventory version` is `v5.7.14`, `v5.7.20`, or both, comma-separated.
    - `Phone` is `intentionally improved` for a row that names at least one Route and whose status is neither missing nor blocked, since the walk shot that route at 390×844 without sideways scroll. It is `n/a` for a row with no Route (Leaderboard, Referrals and other surfaces with no app path) and for a missing or blocked row.
  - **The sign-off line** reads ``Signed off at `<short sha>` `` and is followed by one line per suite or walk: `<name>: exit <c> :: <last line>`, the suite format. The names are fixed: the five suite directory names (`messages-pro-parity`, `of-manager-connectors`, `settings-tabs`, `messages-pro-look-and-feel`, `infloww-parity-next-steps`), then `run-tests`, `of-mirror`, `ui-shots`, `settings-check`, `of-mirror-check` and `route-walk`.
  - **The walk's mocks** follow the Settings walk:
    - `GET /auth/me` is a synthetic owner;
    - `/chatter/me` is empty;
    - `/admin/employees` returns the three synthetic Employees "Alpha One", "Beta Two" and "Gamma Three";
    - any other `/auth/**`, `/chatter/**`, `/admin/**` or `/api/**` request gets `[]`;
    - pages, scripts and styles go to the dev server;
    - telemetry is switched off by `window.__perfLogNoIngest`;
    - the light theme is set by the app's own `chatterly:theme` key before load.

- **Grading rule.** A row is graded "matched" only when its route has no recorded difference against cited C-tagged or Clone evidence. With G-only evidence the row is "unverified". The same grade covers the Infloww evidence across both themes. Messages Pro's light theme keeps Infloww's dark palette by ADR-0010, and that is recorded, not a difference. Grading is done by the executing agent, who reads our shots beside the Clone shots and the existing per-effort parity docs (`docs/messages-pro-parity.md`, `docs/settings-parity.md`). It never re-grades a region those docs signed off unless the walk shows it changed. A region such a doc grades `partial` carries its named differences into `Remaining gap`, so it can't read "matched".
  - **Permission scope and read/write cells** are graded from the owning Phase's relay tests in this plan's suite (Phase 1 Agency context, Phase 4 Role enforcement), never from a shot. A hidden menu is UI hygiene, not the authorization gate (`app/lib/nav.ts:10`).

- **Routes walked.**
  - **Included:** every `href` in the Sidebar, the Sidebar footer and the Settings tabs of the app's route tree. `nb(...)` stubs and `notBuilt` links are included, so placeholders are caught.
  - **Excluded:** `legacy: true` entries (flag off, ADR-0003). They are listed under Labelled improvements from a code reading.
  - **Also included:** every backticked path in the matrix's `Route` cells that no nav link reaches (for example `/notifications`, which Phase 5 reaches from the bell with no sidebar entry). These are shot like nav routes.
  - **Covered by the existing harnesses:** the Pop-out window variant (`?window=1`) and OF Manager subpages under `/of-manager/`. These are not walked again. A matrix route outside the walked set and outside these two fails the walk.

- **Fix boundary.** The plan's Out of scope sets it. A mismatch that needs more than a label string or a test path becomes a ticket in the Phase that owns the area, with the walk's check line as evidence. The matrix row then keeps its honest grade.

## Testing Decisions

- **Seam 1 (new, the only one): the Route walk.**
  - It is the highest seam available: the real Next app, end to end, in a browser, with only the relay mocked.
  - It verifies external behaviour:
    - what each route renders;
    - whether it overflows;
    - whether it errors, writes or reaches off-host;
    - whether the matrix agrees with what rendered.
  - It never imports app code. It reads the route tree's source text, as the Settings walk already does for its tab list.
  - It has no self-test (cut by the six-hats review). Every gate writes its own `{"check","want","got","ok"}` line to `report.json`, and the manual spot-check reads them.
  - Prior art: `scripts/settings-check/walk.py` (mocks, off-host abort, nav parsing, check lines), `scripts/ui-shots.sh` (self-test switch, exit codes, refusing to install), and `scripts/of-mirror-check/render.py` (shots to `/tmp`).
- **Reused seams, unchanged:**
  - the four Effort suites;
  - `scripts/ui-shots.sh` (Messages Pro shots and flows);
  - `scripts/settings-check/walk.py` (Settings tabs and scenarios);
  - `scripts/of-mirror-check/navigate.py` (OF Manager click-through);
  - `node scripts/of-mirror.mjs --check`;
  - `scripts/run-tests.sh` (every relay plain-assert test plus vitest);
  - `app/lib/nav.test.ts` ("gives every link its own route").
- **No new vitest or relay test.** The Phase adds no behaviour to the app or the relay.

## Acceptance

```sh
cd "$(git rev-parse --show-toplevel)"
sh .scratch/messages-pro-parity/suite.sh
sh .scratch/of-manager-connectors/suite.sh
sh .scratch/settings-tabs/suite.sh
sh .scratch/messages-pro-look-and-feel/suite.sh
sh .scratch/infloww-parity-next-steps/suite.sh
scripts/run-tests.sh
node scripts/of-mirror.mjs --check
scripts/ui-shots.sh
# One local dev server for the three browser walks; 127.0.0.1 only, its log under /tmp.
NEXT_LOG_STAMP=$(mktemp); sleep 1
(cd app && exec npx next dev --webpack -H 127.0.0.1 -p 3091 >/tmp/route-walk-next.log 2>&1) &
NEXT_PID=$!
trap 'kill $NEXT_PID 2>/dev/null' EXIT
until curl -sf -o /dev/null http://127.0.0.1:3091/; do sleep 2; done
PORT=3091 ./venv/bin/python -I scripts/settings-check/walk.py
PORT=3091 ./venv/bin/python -I scripts/of-mirror-check/navigate.py
PORT=3091 ./venv/bin/python -I /tmp/route-walk-src/walk.py
# The report is fresh, all checks pass, four shots per walked route; the walk itself is not in the repo.
test /tmp/route-walk/report.json -nt "$NEXT_LOG_STAMP"
python3 -I -c 'import json,os,sys; r=json.load(open("/tmp/route-walk/report.json")); assert r["routes"] and all(c["ok"] for c in r["checks"]); assert all(len([p for p in x["shots"] if os.path.getsize(p)>0])>=4 for x in r["routes"])'
test -z "$(git ls-files 'scripts/route-walk*')"
# The matrix: sign-off commit recorded, nothing but the matrix changed since, improvements listed, no 1:1 claim.
SHA=$(sed -n 's/^Signed off at `\([0-9a-f]\{7,40\}\)`.*/\1/p' docs/infloww-parity-matrix.md | head -1)
test -n "$SHA"
git diff --quiet "$SHA" HEAD -- . ':(exclude)docs/infloww-parity-matrix.md'
# One "<name>: exit 0 :: <last line>" per suite and walk in the Sign-off section.
for n in messages-pro-parity of-manager-connectors settings-tabs messages-pro-look-and-feel infloww-parity-next-steps of-mirror ui-shots settings-check of-mirror-check route-walk; do
  sed -n '/^## Sign-off/,/^## /p' docs/infloww-parity-matrix.md | grep -q "^$n: exit 0 :: ." || exit 1
done
# run-tests is recorded, not gated: the owner waived its legacy failures on 2026-10-16 ("irrelevant").
sed -n '/^## Sign-off/,/^## /p' docs/infloww-parity-matrix.md | grep -q "^run-tests: exit [0-9]* :: ." 
grep -q '^## Labelled improvements' docs/infloww-parity-matrix.md
for w in 'S4S' 'Shift' 'Not wired' 'Not applied yet' 'Phone' 'Auto Post' 'Auto Story'; do
  sed -n '/^## Labelled improvements/,/^## /p' docs/infloww-parity-matrix.md | grep -q "$w" || exit 1
done
! grep -Eqi 'verified 1:1|pixel[- ]perfect' docs/infloww-parity-matrix.md
# No walk PNG committed or left untracked in the repo.
test -z "$(git status --porcelain -- '*.png' | grep -v ' docs/screenshots/')"
# manual: open /tmp/route-walk/ and spot-check that three graded rows (one matched, one intentionally improved, one unverified) look as their grade says beside their clone-*.png.
```

## Depends on

- **Phase 0:** the Merged tree, the four Effort suites on `main`, and `docs/infloww-parity-matrix.md` with its seeded rows and columns.
- **Phase 1:** Agency context and server-side employee identity. These are the matrix's permission-scope column and an improvement to list.
- **Phase 2:** Shifts, time tracking and the Dashboard shift cards. These give the walk new built routes, such as the Shift schedule and Time tracking applied, and the "shift tracking with audit history" improvement.
- **Phase 3:** Share for Share built routes and the bounded-S4S improvement (ADR-0011).
- **Phase 4:** Applied Settings and opt-in Role enforcement (ADR-0012), which regrade the Settings rows and the permission-scope column.
- **Phase 5:** Employees, Sales records, Org chart, Notifications and the Dashboard/Fan-report labels. These are new routes and labels to walk and grade.

## Out of Scope

- **Fresh authenticated Infloww captures.** The account is banned (plan). Saved Clone, BS, PAL, bundle and help evidence is used, with its uncertainty marked.
- **Committing new PNGs.** The plan allows only the docs' existing screenshot sets. `scripts/ui-shots.sh` refreshes its own set under `docs/screenshots/`, and everything else stays in `/tmp`.
- **Any fix bigger than a label or a test path.** These become a ticket in the owning Phase (plan).
- **Walking `legacy: true` routes.** The flag is off by default (ADR-0003). They are listed from code, not shot.
- **A Chatter-session walk.** Owner-only visibility is already pinned by `app/lib/nav.test.ts`, and Role enforcement is Phase 4's seams. A second session walk duplicates them (YAGNI).
- **Loading-state shots and keyboard walks in the Route walk.** Loading is timing-dependent and keyboard paths are owned by ui-shots flows and the Settings walk scenarios. The matrix records both from those harnesses and code (YAGNI).
- **A committed route-walk harness and its self-test.** The plan says "with the existing harnesses", so the walk stays a throwaway under `/tmp` (six-hats review, YAGNI).
- **A pixel-diff tool or any new dependency.** Grading is by eye against the Clone. Playwright and Chromium are already in the venv and cache.
- **Re-grading Messages Pro or Settings regions their parity docs signed off.** That happens only where the walk shows a change (plan, Phase 0 Out of scope).
- **The parked items** (connectors 06/12/19/31/38/46, Leaderboard, Referrals, the platform selector, Idle mode, the update prompt, Help center content). They keep rows with their grades, but nothing is built.
- **Pushing, or a remote tracker.** These are forbidden (floor 2).

## Further Notes

ASSUMPTION: the walk is a throwaway `/tmp` script that copies `scripts/settings-check/walk.py`'s mock routing, not a committed harness with a self-test. Rung 2: the plan's Phase 6 Work says "with the existing harnesses" (plan:305), and Phase 0 already covers the cells those harnesses miss with a throwaway `/tmp` pass. Rung 5: no new committed surface. The six-hats review cut the committed walk and its eight-fault self-test. Overturned if the owner wants a committed route-walk harness, which this Phase would then add under `scripts/route-walk/` with the self-test back.

ASSUMPTION: the walk mocks the relay with Playwright routes instead of starting a temp-DB relay like ui-shots. Rung 3 (the Settings walk and of-mirror-check do the same) and rung 5. The plan's "mocked network/relay tests for default acceptance" points the same way. Overturned if a route renders nothing gradable on empty mocks. In that case its populated state comes from the owning Phase's fixture, added to the walk's mock table.

ASSUMPTION: a plain page load that writes anything fails the walk. Rung 4 (the stricter gate is cheaper to relax than to add later). Overturned by a route whose load write is intended. It gets a named allowlist entry in the walk with its reason.

ASSUMPTION: the walk's matrix cross-check lives inside the walk, not in a vitest that parses a Markdown doc. Rung 5 (one seam). No vitest in the app reads `docs/` today (`grep` over `app/**/*.test.ts*` finds only component-relative imports). Overturned if the owner wants the matrix checked without a dev server.

ASSUMPTION: Ownership of this plan's suite is settled once, in the same words in Phase 0 and Phase 6 (six-hats review): Phase 0 creates `.scratch/infloww-parity-next-steps/suite.sh` with two steps, `matrix` and `relay`. Phases 1–5 do not edit it; each runs its own tests in its own Acceptance block, so Phases that run in the same wave (2 and 3) never collide on one file. Phase 6 alone extends it to its final form. This Phase's final form keeps Phase 0's `matrix` and `relay` steps and adds typecheck, lint, vitest with `--testTimeout=20000` (look-and-feel suite precedent), and each relay test named in Phases 1–5's Acceptance blocks to `relay`. Rung 3 (`.scratch/settings-tabs/suite.sh`) and rung 4. Overturned if the owner wants every Phase to append its own tests as it lands, in which case this Phase only adds typecheck, lint and vitest.

ASSUMPTION: the matrix grades use the glossary's seven Matrix status values ("intentionally different" kept for Leaderboard and Referrals), not only the four the plan's Phase 6 goal names. Rung 2 by way of `CONTEXT.md` › Matrix status (with its own flag). The four are read as the grades a supported route can end with. Overturned with the glossary's own ASSUMPTION.

ASSUMPTION: the sign-off is proven by `git diff --quiet <signed sha> HEAD` excluding the matrix, rather than by naming HEAD. The matrix commit itself moves HEAD. Rung 3 (look-and-feel's "sign-off at fe3011c8"). Overturned if the coordinator commits the matrix in the signed commit itself.

ASSUMPTION (overturned 2026-10-16): whole-relay `scripts/run-tests.sh` stood in for the roadmap's "backend tests" (rung 3) and a pre-plan failure there was to be recorded and ticketed, not waived. The owner ruled the harness ticket (44) "irrelevant" on 2026-10-16 (rung 2), so `run-tests` is recorded in `## Sign-off` with its real exit code and is not a gate; the five Effort suites are the backend gate.

## Review

codex, 2026-10-16. Blind call: `.scratch/infloww-parity-next-steps/review/phase-06-blind.md`. Draft call: `.scratch/infloww-parity-next-steps/review/phase-06-draft.md`.

Blind call:
- B1 (three alternatives; recommends area harnesses plus the matrix as index) — **reject**: that is already the chosen shape (Testing Decisions reuse ui-shots, the Settings walk and navigate.py; the Route walk covers the rest). No change.
- B2 (row universe undefined: nav links vs visible per principal vs nested OF Manager pages) — **accept**: Routes walked now names the universe (nav hrefs plus every matrix Route path; `/of-manager/` subpages and `?window=1` owned by named harnesses; owner session only, Chatter visibility pinned by `app/lib/nav.test.ts`) and the walk fails on a matrix route outside it.
- B3 (Phase 0's six statuses vs Phase 6's four) — **reject**: already settled by the seven-value ASSUMPTION in Further Notes, rung 2 via `CONTEXT.md` › Matrix status.
- B4 (access and write behaviour need the relay seam, not shots; `nav.ts:10`, `service/auth.py:289`) — **accept**: Grading rule now grades the permission-scope and read/write cells from the owning Phases' relay tests, never from a shot.
- B5 (evidence and confidence rule per row) — **reject**: the Grading rule already requires cited C/Clone evidence for "matched" and grades G-only rows "unverified".
- B6 (premise falsifier: `docs/messages-pro-parity.md` grades regions `partial`; a "matched" row over them would be false) — **accept**: a region its parity doc grades `partial` carries its named differences into `Remaining gap` and can't read "matched". Verified: `git show t3code/recreate-infloww-ui-prompt:docs/messages-pro-parity.md` grades Pop-out window, Window header, Fan List and others `partial`.
- B7 (the workspace has no `scripts/` or `ui-redesign/`, so the walk can't run) — **reject**: the review workspace is sparse by construction. `ls ui-redesign/infloww-exact` lists the Clone in the repo, and `git ls-tree -r --name-only t3code/recreate-infloww-ui-prompt` lists `scripts/settings-check/walk.py`, which Phase 0's merge brings to `main` (Depends on Phase 0).

Draft call:
- D1 (`/notifications` has no nav entry, Phase 5 spec line 155, so a nav-only walk never shoots it; coverage check was one-way) — **accept**: the walk now also walks every matrix Route path, fails on a matrix route neither walked nor harness-owned (stories 24, 27a), and the self-test injects that fault.
- D2 (Phone rule forces "intentionally improved" onto rows that may have no phone UI) — **partial**: every walked route is shot at 390×844 with a no-sideways-scroll gate, and the plan calls phone layouts improvements (plan, Phase 6 decisions), so a row with a Route keeps the label whatever its status. The real hole was rows with no Route (Leaderboard, Referrals); the contract now gives those `n/a`.
- D3 (Acceptance passes without per-suite sign-off lines, fresh report or shots) — **accept**: Acceptance now requires a `<name>: exit 0 :: <last line>` line per named suite and walk, a `report.json` newer than the run's stamp with every check ok, and four non-empty shots per walked route.
- D4 (self-test proves only that something failed, not that each gate fired) — **accept**: the self-test injects each of eight faults one at a time into an in-memory matrix copy and writes `selftest.json`; Acceptance asserts every fault fired its own check.
- D5 (`docs/routes.md` correction is scope the plan never asked for; Phase 0 owns stale docs) — **partial**: Phases 2 and 3 own their own `docs/routes.md` rows (`docs/spec/phase-02-shifts-time-tracking.md:74`, `docs/spec/phase-03-share-for-share.md:68`), so story 35 is narrowed to rows the walk contradicts and their owner left stale, as label fixes inside the plan's "label or test path" boundary. Kept because a route map that disagrees with the matrix is a label mismatch the plan allows this Phase to fix.
- D6 (no reverse coverage assertion for matrix rows) — **accept**: same change as D1.

ASSUMPTION: a matrix row with a Route keeps Phone "intentionally improved" even when its status is "unverified" or "intentionally different". Rung 2 via the plan's "Phone layouts are Inflowwww improvements" read as covering every shot phone layout. Overturned if the owner wants Phone graded per row against evidence.

ASSUMPTION: Phase 6 keeps the `docs/routes.md` correction for rows the owning Phase left stale. Rung 5 (one label fix beats a ticket round-trip). Overturned if the owner wants every stale doc row ticketed to its owning Phase.

### Six hats

Six-hats report, 2026-10-16 (`.scratch/infloww-parity-next-steps/review/six-hats.md`), reconciled as the Adversary brief does.

- Green (phase-06), use the existing harnesses plus a throwaway `/tmp` pass instead of a committed route walk with an eight-fault self-test: **accept**. Rung 2: plan:305 says "with the existing harnesses". Rung 5: no new committed surface. The walk is now `/tmp/route-walk-src/walk.py`, never committed, with the same `report.json` contract. Story 29 and the self-test are cut, Acceptance asserts that nothing under `scripts/route-walk*` is tracked, and the walk ASSUMPTION is rewritten. Codex D4's self-test is withdrawn with it. The coverage gates of D1 and D3 stay as `report.json` checks.
- Black (suite.sh ownership stated twice): **accept**. The suite ASSUMPTION is rewritten to the rule Phase 0 states in the same words: Phase 0 creates the suite, Phases 1–5 leave it alone, and this Phase alone extends it.
- White (Set gaps), keyboard and focus differences (roadmap:159, :166) have no Phase, and phase-06:220 drops keyboard walks: **partial**. Rung 5: no keyboard walk is added, because scripted focus paths per route are not cheap. The matrix's `[keyboard]` tag is still filled from ui-shots flows, the Settings walk scenarios and code. The roadmap's "accessible keyboard/focus states" improvement goes to the plan review's Not yet specified.
- Yellow (one matrix, closed status set, explicit "no 1:1 claim" check): **accept**, no change.
