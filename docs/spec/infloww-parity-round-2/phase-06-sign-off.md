# Phase 06 — Sign-off

**Objective.** One recorded commit passes every Effort suite, the mirror check, `ui-shots`, the Settings walk, the OF Manager click-through and the Route walk. Each of the eight round-2 Parity matrix rows is regraded. §3.5.1 covers the whole Smart Messages page, including the Mass Messages tab that Phase 2b placed there. Each row is graded from its walk shots compared with that page's Layout capture and a REA screenshot of the Dashboard bundle, not only with the Clone. `## Sign-off` records every line verbatim, including the `run-tests` line, which is recorded but is not a gate. `## Labelled improvements` lists every "Inflowwww extra" that Phases 1–5 and 2b kept. This Phase alone edits the matrix: it copies Phase 0's baseline record into `## Baseline run` and grades from the eight recheck records (`.scratch/infloww-parity-round-2/rechecks/<page>.md`). Its matrix work waits, needs-human, until the owner commits the uncommitted `## Sign-off` section now in the matrix.

## Problem Statement

The previous sign-off (run 8, `7f0b1c04`, partial) graded 37 of 79 rows `unverified` and named eight pages whose layout does not match Infloww. It never reran the OF Manager click-through or the Route walk on the merged tip. Phases 1–5 and 2b rebuild those eight pages from Layout captures, and 2b puts mass messages in the Smart Messages page's Mass Messages tab, where the bundle has them. Each Phase rechecks its own page into that page's recheck record and leaves the matrix alone, but a reviewer or the owner still can't answer four questions from one place:

- Does the whole tree pass together on one commit?
- Do the eight pages now read like the bundle?
- Which remaining differences are labelled extras, and which are mismatches?
- Is anything still unwalked?

Until now the grades were taken against the Clone. ADR-0013 says the Clone was wrong on exactly these pages, so a grade taken against it can claim parity that isn't there.

## Solution

A reviewer opens `docs/infloww-parity-matrix.md` and finds the following:

- **A round-2 paragraph at the top of `## Baseline run`**, copied from `.scratch/infloww-parity-round-2/baseline.md` (Phase 0), with its `== .scratch/infloww-parity-round-2/suite.sh` block taken from this Phase's own suite run, because Phases 1–5 add steps to that suite. The earlier entries stay below it.
- **A new `## Sign-off`.** It names one commit and gives one verbatim `<name>: exit <c> :: <last line>` line for each of the six Effort suites, `run-tests`, `of-mirror`, `ui-shots`, `settings-check`, `of-mirror-check` and `route-walk`. Every line exits 0 except `run-tests`, which is recorded under the owner's waiver.
- **The eight round-2 rows**, each regraded. §3.5.1 includes the Mass Messages tab, and the §3.7 container row follows its two children. Its Visual evidence cites three things:
  - the page's Layout capture (`docs/infloww-layouts/<page>.md`);
  - a REA screenshot of the bundle page (`/tmp/route-walk/bundle-<page>.png`, never committed, cited by sha256), or the reason the bundle did not render that page;
  - the fresh Route walk shots and the Clone shot.

  Its Remaining gap names every difference from the Layout capture, each with its kind tag.
- **`## Labelled improvements`.** It gains the Google Drive import, Ingest health, the Auto-unsend sweep and per-broadcast Auto-unsend, "Message online fans", Mass Nudge and every other extra those Phases kept, each with where the UI labels it. Every existing entry that cites a file on one of the eight pages is rechecked against the rebuilt file.

Nothing else is rebuilt here. A mismatch bigger than a label string or a test path becomes a ticket in the Phase that owns the page, and the row keeps its honest grade.

## User Stories

1. As an owner, I want one sign-off line naming the commit where every suite and walk ran, so that the grades describe one real tree.
2. As an owner, I want the only changes between the signed commit and the tip to be the matrix and this run's own records, so that no later code change can ride on the sign-off.
3. As an owner, I want each suite's and each walk's last output line copied verbatim into `## Sign-off`, so that the evidence of green lives in the doc and not only in a terminal.
4. As an owner, I want this effort's suite (`.scratch/infloww-parity-round-2/suite.sh`) run beside the five earlier Effort suites, so that the round-2 typecheck, lint, vitest and relay tests are part of the gate.
5. As an owner, I want the `run-tests` line recorded with its real exit code and marked as waived, so that the 29 legacy relay files that need `ALLOW_ANONYMOUS_ADMIN` are visible but don't block the sign-off (owner's waiver).
6. As an owner, I want the OF Manager click-through and the Route walk rerun on the signed commit, so that the two walks run 8 carried forward are no longer "not run".
7. As an owner, I want the previous partial sign-off replaced by a one-line pointer to `7f0b1c04`, so that the matrix holds exactly one `## Sign-off` (the next-steps suite's `matrix` contract) and the earlier record stays findable.
8. As a reviewer, I want each of the eight round-2 rows (§3.1 Dashboard, §3.5.1 Smart Messages, §3.5.5 Scripts, §3.5.4 Vault Pro, §3.5.8 Tracking links, §3.4 Creator reports, §3.7 Manage creators, §3.7 Custom proxy) graded against its Layout capture, so that the bundle, not the Clone, decides layout (ADR-0013).
9. As a reviewer, I want each of those rows to cite a REA screenshot of the same bundle page, by file name and sha256, so that I can see the comparison and confirm which image was used.
10. As a reviewer, I want a row whose bundle page did not render to say so in its Visual evidence, with the reason, and to be graded against the Layout capture's text alone, so that a missing screenshot is never silently skipped.
11. As a reviewer, I want the walk's 1440×900 shots in both themes read beside the bundle screenshot, and its 390×844 shots kept as the phone improvement, so that desktop layout is graded against Infloww and phone layout stays a labelled improvement.
12. As a reviewer, I want the Clone shot kept as secondary evidence on those rows, so that a Clone edit from Phase 0 is still visible, though it never outranks the capture.
13. As a reviewer, I want a row graded `matched` only when it has no difference from its Layout capture, and `intentionally improved` when every difference is a labelled extra, as the matrix header defines them, so that an unlabelled difference never reads as parity and a labelled one is named as ours.
14. As a reviewer, I want a row whose bundle controls are shown disabled with the "not wired" tooltip graded `not wired`, so that the grade says which controls aren't backed by the relay.
15. As a reviewer, I want every difference from the capture recorded in Remaining gap with its kind tag (`[layout]`, `[type]`, `[responsive]`, `[labels]`, `[states]`, `[dialogs]`, `[keyboard]`, `[nav]`), so that I can tell what kind of mismatch is left.
16. As a reviewer, I want the mass messages graded where Phase 2b put them, so that the moved mass messages are graded too. On the bundle's placement that is the Mass Messages tab inside the §3.5.1 row, and its Labelled improvements are the Auto-unsend sweep, per-broadcast Auto-unsend, "Message online fans" and Mass Nudge. If Phase 2b's fallback mounted them on a My Automations route instead, that route's row is graded like the eight.
17. As a reviewer, I want §3.5.1 graded on both of the bundle's parent tabs as `growth-smart-messages.md` records them, so that the grade follows ADR-0014 and the bundle placement it defers to. The Automated Messages tab holds only per-fan Triggers (the Nudge message, the Message on purchase and any other Trigger the capture shows), and no mass message may appear in it. The Mass Messages tab is graded against the capture's Mass Messages section.
18. As a reviewer, I want §3.5.4 to grade the Vault import card's file drop against the capture and the collapsed Drive section as a labelled extra, so that Phase 5's placement is checked.
19. As a reviewer, I want §3.7 Manage creators to keep the extension-first Add flow and the extension probe's `CONSOLE_ALLOW` line in the Route walk, so that the owner's "extension in front" holds and the probe doesn't fail the walk.
20. As a reviewer, I want `## Labelled improvements` to gain every "Inflowwww extra" Phases 1–5 and 2b kept (at least the Google Drive import below the file drop, Ingest health on Creator reports, the Auto-unsend sweep and per-broadcast Auto-unsend, "Message online fans" and Mass Nudge, plus the Dashboard shift cards when they are ours), each with where the UI marks it, so that every deliberate departure is listed in one place.
21. As a reviewer, I want every app file changed since `7f0b1c04` that renders the "Inflowwww extra" label named in `## Labelled improvements`, Messages Pro's catalogued extras aside, so that no new extra goes unlisted.
22. As a reviewer, I want no row and no sentence in the matrix to claim "verified 1:1" or "pixel perfect", so that the limits of the evidence stay honest.
23. As a developer, I want the Route walk rerun from `/tmp/route-walk-src/walk.py`, and recreated from the previous plan's ticket 41 if `/tmp` was cleared, so that every nav route, including any route Phases 1–5 and 2b added, is shot in four views and cross-checked against the matrix.
24. As a developer, I want the walk's mock table extended only where a rebuilt page needs a populated mock to render (for example, the Dashboard KPI reads), with synthetic data only, so that a route never fails just because its mock is empty.
25. As a developer, I want the bundle screenshots taken with REA from the bundle served on 127.0.0.1, in a Chromium whose resolver maps every host other than 127.0.0.1 to "not found", so that no request leaves the machine.
26. As a developer, I want the bundle screenshots written only under `/tmp/route-walk/`, so that nothing from the bundle enters the repo.
27. As a developer, I want label fixes and stale test paths found during the regrade fixed in this Phase, and any bigger mismatch filed as a ticket in the owning Phase with the walk's check line or the capture's offset as evidence, so that this Phase grades and doesn't rebuild.
28. As a developer, I want every relay test named in an Acceptance block of a Phase 1–5 or 2b spec present in this effort's suite, and any missing one added, so that the suite gates what the Phases proved.
29. As a developer, I want `ui-shots`' rewrite of `docs/screenshots/messages-pro-*` copied back from a `/tmp` backup, never from `git restore`, so that the matrix stays the only file that changes after the signed commit and the repo rules hold.
30. As an owner, I want no real creator, fan or account name in any shot, mock or matrix row, so that the sign-off artefacts can be shared.
31. As a reviewer, I want each of the eight rows graded from its page's recheck record (every Phase's section in it), and the Acceptance to fail if a page has none, so that a Phase's recheck is never skipped and lives in one place.
32. As a maintainer, I want Phase 0's baseline record copied into the matrix's `## Baseline run` with a round-2 suite block from this run, so that the next-steps suite's `matrix` step turns green.

## Implementation Decisions

- **Owns.**
  - **The Parity matrix's grading cells for the regraded rows:** Visual evidence, Remaining gap and Matrix status of the eight round-2 rows. The list widens to a My Automations mass-message row only if Phase 2b's fallback created one. It also owns:
    - the Matrix status and Remaining gap of the §3.7 container row, whose only children are the two regraded §3.7 rows. It reads the worst of their grades, by the header's container rule for §3.5 and §3.9;
    - `## Sign-off`;
    - the round-2 paragraph and block at the top of `## Baseline run`, copied from `.scratch/infloww-parity-round-2/baseline.md`, with its round-2 suite block replaced by this run's step-1 output of that suite (the earlier entries stay below);
    - `## Labelled improvements`, including a recheck of each existing entry that cites a file on the eight pages (for example "Earnings by channel (§3.1)", `components/home/CompetitorReports.tsx:447`). An entry whose file or line no longer renders the label is corrected or removed as a doc fix.

    Other cells and other rows change only when the walk contradicts them (a label fix).
  - **The Route walk** (`/tmp/route-walk-src/walk.py`, never committed). Only its mock table changes, and only for routes that need a populated mock to render. Its output contract is unchanged.
  - **The bundle screenshots** (`/tmp/route-walk/bundle-<page>.png`).
  - **This effort's suite** (`.scratch/infloww-parity-round-2/suite.sh`), and only to add relay tests a Phase's Acceptance names but the suite lacks.
  - **Label-only and test-path-only fixes** in any module.
  - The eight recheck records are inputs here, read and not rewritten. A grade that departs from a record's proposed row says why in Remaining gap.

- **Interfaces.**
  - **The Route walk.** Inputs, outputs and exit codes are as in the previous plan's phase-06 spec: `PORT`, `ROUTE_WALK_OUT` default `/tmp/route-walk`, `report.json`, `<slug>-<1440|390>-<dark|light>.png`, `<slug>-error.png` and `clone-<name>.png`. Exit codes: 0 pass, 1 check failed, 2 usage, 3 prerequisite, 4 no dev server. It runs against the tree's dev server on 127.0.0.1:3001 (repo rules).
  - **A bundle screenshot** is one PNG per round-2 page, at 1440×900, named `bundle-<page>.png`. `<page>` is the Layout capture's slug (`dashboard`, `growth-smart-messages`, `growth-scripts`, `growth-vault-pro`, `growth-tracking-links`, `analytics-creator-reports`, `creators-manage`, `creators-proxy`). For `growth-smart-messages`, the shot shows the Automated Messages tab. A second shot, `bundle-growth-smart-messages-mass.png`, shows the Mass Messages tab when the bundle renders it. The shot is produced as follows:
    1. Serve the bundle with `python3 -I -m http.server --bind 127.0.0.1 <port> --directory ~/Downloads/infloww-remote-web`, started from a directory outside the bundle.
    2. Start the venv's cached Chromium headless with these flags:
       - `--remote-debugging-address=127.0.0.1` and `--remote-debugging-port=<port>`;
       - `--window-size=1440,900`;
       - `--host-resolver-rules="MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"`;
       - a throwaway profile under `/tmp`.
    3. Open the page at its route with the local API mock that its Layout capture records. REA's `capture_web_screenshot` never navigates, scrolls or runs page JavaScript (its tool description), so a separate driver does this. That driver is the venv's Playwright through `connect_over_cdp` on the same endpoint, the one the Route walk already uses, and it registers the mock as `page.route` handlers. The driver writes nothing to the repo.
    4. Pick the page's target with REA's `list_browser_targets`. Capture it with `capture_web_screenshot` (`cdp_endpoint` the loopback endpoint, `target_id` that target), with `allowed_origins` set to the loopback origin only. The shot is the 1440×900 viewport only. A part of the page below the fold is graded from the Layout capture's text, as the walk's viewport shots are (`page.screenshot` without `full_page`).
    5. Decode the artifact's base64 to the file and check that the file's sha256 equals the artifact's.
  - **The Sign-off section.** The first line is ``Signed off at `<short sha>` (<date>; infloww-parity-round-2 Phase 6).`` It is followed by a `text` fence with one `<name>: exit <c> :: <last line>` line per name, in this fixed order:
    1. the six suite directory names: `messages-pro-parity`, `of-manager-connectors`, `settings-tabs`, `messages-pro-look-and-feel`, `infloww-parity-next-steps`, `infloww-parity-round-2`;
    2. then `run-tests`, `of-mirror`, `ui-shots`, `settings-check`, `of-mirror-check` and `route-walk`.

    The `infloww-parity-next-steps` and `route-walk` lines come from the post-grade rerun (Run order, step 8), because both read the matrix. Every other line comes from steps 1–5.

    After the fence come the notes:
    - the `run-tests` waiver;
    - where the walks ran;
    - how the screenshots were restored;
    - one line `Rows not regraded here keep their grade from \`7f0b1c04\` or earlier (their Visual evidence names the walk).`;
    - one line `Previous sign-off: \`7f0b1c04\` (infloww-parity-next-steps run 8, partial).`

- **Schema.** None. No table, no migration.

- **Contracts.**
  - **The matrix cells of a regraded row.**
    - **Visual evidence** cites the following, in this order:
      1. `docs/infloww-layouts/<page>.md`;
      2. either `/tmp/route-walk/bundle-<page>.png (sha256 <64 hex>)` or `bundle did not render: <reason>`;
      3. the Clone file `ui-redesign/infloww-exact/<name>.html` [CL];
      4. ours: the Route walk shots with this run's date.

      It no longer cites the 2026-10-16 walk.
    - **Remaining gap** follows the matrix header's kind-tag rule. Every labelled extra in it ends with `(Inflowwww extra; Labelled improvements)`.
  - **The grading rule for the regraded rows.** The matrix header's status definitions rule (coordinator ruling 3, 2026-10-17), with ADR-0013 and the previous Phase 6 grading ASSUMPTIONs. The inputs are the page's recheck record (its `### Differences` and proposed `### Matrix row` from every Phase section), the walk shots and the bundle screenshot.
    - Any difference from the Layout capture that carries no "Inflowwww extra" label, and that this Phase cannot fix as a label, gives `unverified`. The Remaining gap names the ticket filed in the owning Phase.
    - Otherwise, a bundle control shown disabled with the "not wired" tooltip gives `not wired`.
    - Otherwise, when every remaining difference is a labelled extra, the grade is `intentionally improved` (the header: "its extras are labelled per ADR-0003"), and the Remaining gap lists them.
    - Otherwise, with no difference left, the grade is `matched`.
    - The bundle screenshot and the Layout capture outrank the Clone, and the Clone shot is supporting evidence only.
    - Permission scope and read/write cells are still graded from the relay tests in the suites, never from a shot.
  - **The walk's mocks** are the Settings walk's synthetic owner and empty lists. A new entry may add only synthetic data, and never a real name.
  - **Start-of-Phase precondition.** The owner's uncommitted edit to `docs/infloww-parity-matrix.md` (the run-8 `## Sign-off`, +25 lines) must be committed before this Phase edits the matrix. The test: `git status --short docs/infloww-parity-matrix.md` must print nothing. If it prints anything, the matrix ticket is parked needs-human with that command. This is the only Phase that waits on it: Phases 0–5 and 2b make no matrix edit (coordinator ruling 2, 2026-10-17). Run order steps 0–6 may run before the owner commits; steps 7–8 may not.
  - **Run order.** One step at a time, from the repo root:
    0. Check that everything the run reads is committed: `git status --porcelain -- app service scripts ui-redesign docs/infloww-layouts docs/infloww-screens.md '.scratch/*/suite.sh'` must print nothing, and `HEAD` is the commit to be signed. Otherwise the Phase parks with the command and its output.
    1. the six suites;
    2. `run-tests`;
    3. `of-mirror --check`;
    4. `ui-shots`, with `docs/screenshots/` backed up to a `mktemp -d` directory and copied back after;
    5. then, on the 3001 dev server, the Settings walk, the OF Manager click-through and the Route walk;
    6. then the bundle screenshots;
    7. then the grading, from the recheck records, and the copy of `baseline.md` into `## Baseline run`;
    8. then, on the regraded matrix, rerun the `infloww-parity-next-steps` suite (its `matrix` step) and the Route walk (its matrix cross-check). The code is unchanged, because only the matrix differs from the signed commit. A failure is fixed in the matrix, and step 8 runs again.

    The grader cites only walk shots listed in this run's `/tmp/route-walk/report.json`. The walk does not empty its output directory (`os.makedirs(OUT, exist_ok=True)`, `walk.py:252`), so older PNGs may still sit there, and floor 2 forbids deleting them.

- **Fix boundary.** The plan's Out of scope sets it. A label string or a test path is fixed here. Anything else becomes a ticket in `.scratch/infloww-parity-round-2/issues/`, owned by the Phase whose page it is, and if that fix lands, the run starts again from step 1.

## Testing Decisions

- **Seam 1 (reused, the highest): the Route walk.** It runs the real Next app end to end in a browser with only the relay mocked. It verifies every route renders without a 404, a page error or a console error, that the phone views don't scroll sideways, that a page load writes nothing and reaches nothing off-host, and that the matrix and the app agree in both directions. Any route a Phase added is covered automatically, because the walk reads the nav. Phase 2b adds none on the bundle's placement; its Mass Messages tab sits on `/growth/smart-messages`. Prior art: `/tmp/route-walk-src/walk.py` (previous plan's ticket 41) and `scripts/settings-check/walk.py`.
- **Evidence beside the seam: the bundle screenshots.** They are not a test, just the image a grader compares the walk's shots with. Their sha256 in the matrix ties each grade to one image.
- **Reused seams, unchanged:**
  - the six Effort suites;
  - `scripts/ui-shots.sh`;
  - `scripts/settings-check/walk.py`;
  - `scripts/of-mirror-check/navigate.py`;
  - `node scripts/of-mirror.mjs --check`;
  - `scripts/run-tests.sh` (recorded only);
  - the next-steps suite's `matrix` step, which checks the matrix contract after the regrade;
  - `app/lib/nav.test.ts`.
- **No new vitest, relay test or committed harness.** This Phase adds no behaviour. Each page's structure tests belong to Phases 1–5 and 2b.

## Acceptance

```sh
cd "$(git rev-parse --show-toplevel)" || exit 1
set -e
M=docs/infloww-parity-matrix.md
# What the walks run is committed; the bundle never is.
test -z "$(git status --porcelain -- app service scripts ui-redesign docs/infloww-layouts docs/infloww-screens.md '.scratch/*/suite.sh')"
test -z "$(git ls-files | grep -F infloww-remote-web)"
# This effort's suite gates every relay test the Phase 1-5 and 2b specs' Acceptance blocks name.
for t in $(for f in docs/spec/infloww-parity-round-2/phase-0[1-5]*.md; do sed -n '/^## Acceptance/,/^## /p' "$f"; done | grep -oE 'test_[a-z0-9_]+\.py' | sort -u); do
  grep -qF "${t%.py}" .scratch/infloww-parity-round-2/suite.sh || { echo "suite lacks $t"; exit 1; }
done
for s in messages-pro-parity of-manager-connectors settings-tabs messages-pro-look-and-feel infloww-parity-next-steps infloww-parity-round-2; do
  sh ".scratch/$s/suite.sh"
done
# run-tests is recorded, not gated (owner's waiver, 2026-10-16).
scripts/run-tests.sh || true
node scripts/of-mirror.mjs --check
# ui-shots rewrites docs/screenshots/messages-pro-*: back up, run, copy back (never git restore).
BAK=$(mktemp -d); cp -Rp docs/screenshots/. "$BAK"/
rc=0; scripts/ui-shots.sh || rc=$?
cp -Rp "$BAK"/. docs/screenshots/
test "$rc" -eq 0
git diff --quiet -- docs/screenshots
# The three browser walks on the tree's dev server, 127.0.0.1:3001.
STAMP=$(mktemp); sleep 1
if ! curl -sf -o /dev/null http://127.0.0.1:3001/; then
  (cd app && exec npx next dev --webpack -H 127.0.0.1 -p 3001 >/tmp/route-walk-next.log 2>&1) &
  NEXT_PID=$!; trap 'kill $NEXT_PID 2>/dev/null' EXIT
  until curl -sf -o /dev/null http://127.0.0.1:3001/; do sleep 2; done
fi
PORT=3001 ./venv/bin/python -I scripts/settings-check/walk.py
PORT=3001 ./venv/bin/python -I scripts/of-mirror-check/navigate.py
# manual: if /tmp was cleared, recreate /tmp/route-walk-src/walk.py from .scratch/infloww-parity-next-steps/issues/41-*.md first.
grep -q 'CONSOLE_ALLOW' /tmp/route-walk-src/walk.py
PORT=3001 ./venv/bin/python -I /tmp/route-walk-src/walk.py
test /tmp/route-walk/report.json -nt "$STAMP"
python3 -I -c 'import json,os; r=json.load(open("/tmp/route-walk/report.json")); assert r["routes"] and all(c["ok"] for c in r["checks"]); assert all(len([p for p in x["shots"] if os.path.getsize(p)>0])>=4 for x in r["routes"])'
test -z "$(git ls-files 'scripts/route-walk*')"
# manual: take the bundle screenshots with REA (Interfaces, "A bundle screenshot") into /tmp/route-walk/bundle-<page>.png, then grade.
# Each round-2 row cites its Layout capture, a bundle screenshot whose sha256 matches (or why none rendered), and a fresh walk.
row() { sed -n '/^## Matrix/,/^## /p' "$M" | awk -F'|' -v id="$1" '{g=$2; gsub(/^ +| +$/,"",g)} g==id'; }
SODATE=$(sed -n 's/^Signed off at `[0-9a-f]*` (\([0-9-]*\);.*/\1/p' "$M" | head -1); test -n "$SODATE"
for p in "3.1:dashboard" "3.5.1:growth-smart-messages" "3.5.5:growth-scripts" "3.5.4:growth-vault-pro" "3.5.8:growth-tracking-links" "3.4 Creator reports:analytics-creator-reports" "3.7 Manage creators:creators-manage" "3.7 Custom proxy:creators-proxy"; do
  id=${p%%:*}; pg=${p##*:}; r=$(row "$id")
  test -s "docs/infloww-layouts/$pg.md"
  grep -q '^### Matrix row' ".scratch/infloww-parity-round-2/rechecks/$pg.md" || { echo "no recheck record for $pg"; exit 1; }
  test -n "$r"
  echo "$r" | grep -qF "docs/infloww-layouts/$pg.md"
  ! echo "$r" | grep -qF 'the Route walk, 2026-10-16'
  echo "$r" | grep -qF "the Route walk, $SODATE"
  st=$(echo "$r" | awk -F'|' '{s=$10; gsub(/^ +| +$/,"",s); print s}')
  case "$st" in matched|"intentionally improved"|"not wired") ;; unverified) echo "$r" | grep -qF '.scratch/infloww-parity-round-2/issues/' ;; *) echo "row $id: grade $st"; exit 1 ;; esac
  sha=$(echo "$r" | sed -n "s/.*bundle-$pg\.png (sha256 \([0-9a-f]\{64\}\)).*/\1/p")
  if [ -n "$sha" ]; then test "$(shasum -a 256 "/tmp/route-walk/bundle-$pg.png" | cut -d' ' -f1)" = "$sha"
  else echo "$r" | grep -qF 'bundle did not render: '; fi
done
# Phase 2b's section is in the Smart Messages record; Phase 0's baseline record is at the top of the matrix's Baseline run.
grep -q '^## Phase 2b ' .scratch/infloww-parity-round-2/rechecks/growth-smart-messages.md
BS=$(sed -n 's/^Round 2 baseline at `\([0-9a-f]\{7,40\}\)`.*/\1/p' .scratch/infloww-parity-round-2/baseline.md | head -1); test -n "$BS"
sed -n '/^## Baseline run/,/^## Matrix/p' "$M" | grep -qF "Round 2 baseline at \`$BS\`"
# Sign-off: a new commit after run 8, nothing but the matrix and run records changed since, every line present.
SHA=$(sed -n 's/^Signed off at `\([0-9a-f]\{7,40\}\)`.*/\1/p' "$M" | head -1)
test -n "$SHA"; test "$SHA" != 7f0b1c04
git merge-base --is-ancestor 7f0b1c04 "$SHA"
git diff --quiet "$SHA" HEAD -- . ':(exclude)docs/infloww-parity-matrix.md' ':(exclude).scratch/infloww-parity-round-2'
git diff --quiet "$SHA" HEAD -- .scratch/infloww-parity-round-2/suite.sh
test "$(grep -c '^## Sign-off' "$M")" -eq 1
SO=$(sed -n '/^## Sign-off/,/^## /p' "$M")
for n in messages-pro-parity of-manager-connectors settings-tabs messages-pro-look-and-feel infloww-parity-next-steps infloww-parity-round-2 of-mirror ui-shots settings-check of-mirror-check route-walk; do
  echo "$SO" | grep -q "^$n: exit 0 :: ." || { echo "sign-off lacks $n"; exit 1; }
done
echo "$SO" | grep -qE '^run-tests: exit [0-9]+ :: .'
echo "$SO" | grep -qF 'Previous sign-off: `7f0b1c04`'
# Labelled improvements: the earlier entries, the round-2 extras, and every new file that renders the label.
LI=$(sed -n '/^## Labelled improvements/,/^## /p' "$M")
for w in 'S4S' 'Not wired' 'Not applied yet' 'Phone' 'Auto Post' 'Auto Story' 'Google Drive import' 'Ingest health' 'Auto-unsend' 'Message online fans' 'Mass Nudge'; do
  echo "$LI" | grep -qF "$w" || { echo "Labelled improvements lacks $w"; exit 1; }
done
# The Dashboard shift cards are listed when the 3.1 row calls them an extra.
if row 3.1 | grep -qE 'My shifts[^|]*Inflowwww extra'; then echo "$LI" | grep -qF 'My shifts'; fi
# Phase 2b's fallback only: a My Automations mass-message route needs its own row.
for h in $(grep -oE '"/growth/[a-z-]*mass[a-z-]*"' app/lib/nav.ts | tr -d '"'); do
  sed -n '/^## Matrix/,/^## /p' "$M" | grep -qF "\`$h\`" || { echo "no row for $h"; exit 1; }
done
for f in $(git diff --name-only 7f0b1c04 "$SHA" -- app/components app/lib app/app | grep -v '\.test\.' | grep -v '^app/components/chat/' | grep -vE 'app/lib/(openinflowwwwExtras|messagesProOurs)\.ts'); do
  [ -f "$f" ] && grep -qE 'EXTRA_LABEL|Inflowwww extra' "$f" || continue
  echo "$LI" | grep -qF "$(basename "$f")" || { echo "unlisted extra: $f"; exit 1; }
done
! grep -Eqi 'verified 1:1|pixel[- ]perfect' "$M"
# No walk or bundle PNG committed or left in the repo.
test -z "$(git status --porcelain -- '*.png' | grep -v ' docs/screenshots/')"
test -z "$(git ls-files | grep -E 'bundle-[a-z-]+\.png')"
# manual: open /tmp/route-walk/ and, for three regraded rows (one matched, one not wired, one unverified), check <slug>-1440-dark.png beside bundle-<page>.png and docs/infloww-layouts/<page>.md reads as the grade says.
```

## Depends on

- **The owner (needs-human):** commits the uncommitted `## Sign-off` section in `docs/infloww-parity-matrix.md`. Only the matrix ticket (Run order steps 7–8) waits on it.
- **Phase 0:** the baseline record on the merged tip (`.scratch/infloww-parity-round-2/baseline.md`), the recheck record contract, the eight Layout captures in `docs/infloww-layouts/`, how each page was reached and mocked in the bundle, and the Clone pages fixed to match.
- **Phase 1:** the Dashboard KPI header and the placement of the shift cards, which become a labelled extra if they're ours.
- **Phase 2:** Smart Messages as triggers only, plus Scripts, Vault Pro and Tracking links rebuilt from their captures, with their Not wired markers.
- **Phase 2b:** mass messages in the bundle's Mass Messages tab on `/growth/smart-messages`, with no new route and no new row. That tab includes the per-broadcast Auto-unsend and the Auto-unsend sweep. Phase 2b also supplies its section of `rechecks/growth-smart-messages.md`, saying where they were placed, with the proposed row 3.5.1 text and Labelled improvements lines for the Auto-unsend sweep, "Message online fans" and Mass Nudge. Under Phase 2b's fallback only, it supplies a My Automations route, nav entry, page-map entry and row instead.
- **Phase 3:** Creator reports' Overview and Creator performance tabs, and Ingest health as a labelled extra.
- **Phase 4:** Manage creators and Custom proxy rebuilt, with the extension kept in front and the probe unchanged.
- **Phase 5:** the Drive import collapsed below the file drop, a labelled extra.
- **Each of Phases 1–5 and 2b:** its relay tests added to this effort's suite, and its own recheck against the bundle with REA, recorded with a proposed row in `.scratch/infloww-parity-round-2/rechecks/<page>.md`.

## Out of Scope

- **Rebuilding any page.** Each fix beyond a label or a test path is a ticket in the owning Phase (plan, as the previous Phase 6).
- **Regrading rows outside the eight round-2 pages** (and, under Phase 2b's fallback only, its My Automations row), unless the walk contradicts them. The plan names those rows, and the other grades came from run 8 (YAGNI).
- **A pixel-diff gate** (for example REA's `compare_web_screenshots` as a threshold). Grading is by eye against the capture. The Inflowwww colours (ADR-0001, ADR-0010) and synthetic data make a pixel ratio meaningless as a gate (YAGNI).
- **Committing bundle screenshots, walk shots or any part of the bundle.** Floor 2, ADR-0013 and the repo rules.
- **A committed Route walk harness or its self-test.** The previous plan cut them, and the plan reuses the throwaway walk.
- **Fixing the 29 legacy `run-tests` files.** Owner's waiver: the line is recorded, not gated.
- **The translator LLM tier and the pluggable translate provider.** Ticket 28 stays closed, and the provider is a later plan.
- **Deleting the worktree, pushing, live sandbox tests.** These need the human (floor 2; `LIVE_TEST_HERE.md` is the owner's).

## Further Notes

ASSUMPTION: "the five effort suites" in the plan's Phase 6 goal is read as the five earlier suites plus this effort's own `.scratch/infloww-parity-round-2/suite.sh`, so the sign-off has six suite lines. Rung 3: the previous Phase 6 added its own suite to the four before it. The coordinator's fill also names this suite. Overturned if the owner wants exactly the five earlier suites, in which case the `infloww-parity-round-2` line moves under the notes.

ASSUMPTION: "a REA capture of the same page" is read as the page's Layout capture (Phase 0's Markdown, the layout truth by ADR-0013) plus a REA `capture_web_screenshot` PNG of the bundle page, cited by sha256 and kept in `/tmp`. Where the bundle did not render that page (Phase 0's known limit), the Layout capture's text is the comparison. Rung 2 (the plan's wording and ADR-0013) and rung 4 (nothing committed). Overturned if the owner wants the bundle screenshots committed or wants a row that has no bundle screenshot kept `unverified`.

ASSUMPTION: a row whose only differences from its Layout capture are labelled "Inflowwww extra" items reads `intentionally improved`, with those extras listed in Remaining gap, and `matched` means no difference at all. Rung 3: the matrix header defines `intentionally improved` as "its extras are labelled per ADR-0003" (coordinator ruling 3, 2026-10-17); the plan's owner decision that "the Parity matrix's grading rules decide `matched`" points at that header, and Phases 1 and 3 already aim for it. Overturned if the owner wants such rows graded `matched`.

ASSUMPTION: the run-8 `## Sign-off` is replaced, not kept beside the new one, and a one-line pointer to `7f0b1c04` keeps it findable. The next-steps suite's `matrix` step accepts one `## Sign-off` section (rung 1: `.scratch/infloww-parity-next-steps/suite.sh:20`), and git history keeps the old text (rung 4). Overturned if the owner wants a history of sign-offs, in which case the earlier ones move into a subsection and the suite's section check is widened.

ASSUMPTION: the sign-off's "nothing changed since" check excludes the matrix and `.scratch/infloww-parity-round-2/`, because the coordinator's run records may be committed after the signed commit and hold no code. The exception is `suite.sh`, which is the gate itself and is diffed on its own. Rung 5. Overturned if the coordinator commits those records in the signed commit, in which case only the matrix is excluded.

ASSUMPTION: the walks use the dev server on 127.0.0.1:3001, not the previous spec's 3091. Rung 2: the repo rules name 3001. Rung 1: run 8 recorded that Next 16 refuses a second dev server per app directory and that 3091 is held elsewhere (`docs/infloww-parity-matrix.md` › `## Sign-off`). Overturned when 3091 is free and the owner wants it back.

ASSUMPTION: the Labelled improvements file check covers files under `app/components`, `app/lib` and `app/app` changed since `7f0b1c04` (the round-2 base), and it skips `app/components/chat/`, `app/lib/openinflowwwwExtras.ts` and `app/lib/messagesProOurs.ts`. Messages Pro's extras are catalogued there and in `docs/messages-pro-parity.md`, not by file name (rung 3: the existing Labelled improvements entries). A file that renders the label only through a shared wrapper component, with no `EXTRA_LABEL` or literal of its own, is not caught. Such a file is found in the regrade, by eye, against the Layout capture (rung 5). Overturned if the owner wants every file that renders the label named.

ASSUMPTION: this Phase edits the matrix only after the owner's uncommitted run-8 edit to it is committed. The repo rules forbid touching that file while it is uncommitted owner state (rung 2). Otherwise the matrix ticket parks needs-human with `git status --short docs/infloww-parity-matrix.md` (parking is rung 4). Overturned if the owner commits it or releases the file, in which case the precondition passes trivially.

ASSUMPTION: Phase 6 is the only Phase that edits the matrix, and it reads every regrade from `.scratch/infloww-parity-round-2/rechecks/<page>.md` (coordinator ruling 2, adopting six-hats 13; rung 4/5: one regrade instead of a parked one per Phase). Overturned if the owner commits the matrix early and wants each Phase to regrade its own row; then this Phase checks those rows instead of writing them.

ASSUMPTION: mass messages are graded inside row 3.5.1, as the Mass Messages tab, and not in a separate "Auto mass messages" row. Rung 1 for the bundle (`index.9f50f370.js` @14654355, @15747892) and Phase 2b's spec, which puts them in that tab on `/growth/smart-messages` and adds no route or row (`docs/spec/infloww-parity-round-2/phase-02b-auto-mass-messages.md`, Objective and Out of Scope). Rung 2 for the plan's follow-the-bundle exception, which ADR-0014 (amended 2026-10-17) records (`docs/adr/0014-smart-messages-are-per-fan-triggers-mass-messages-move-to-my-automations.md`, decision and first ASSUMPTION). Overturned if Phase 2b's fallback runs. In that case the My Automations route gets its own row, which is graded like the eight and caught by the Acceptance's nav check.

ASSUMPTION: the §3.7 container row reads the worst grade of its two children, by analogy with the header's container rule for §3.5 and §3.9 (rung 3). Overturned if the owner wants container rows left at `unverified` with a pointer to their children.

ASSUMPTION: the `infloww-parity-next-steps` and `route-walk` Sign-off lines come from a rerun after the grading (Run order, step 8). Both read the matrix, and the grading changes the matrix after the signed commit (rung 5). Overturned if the owner wants every line taken from one pass, in which case the grading happens before step 1 and is itself committed into the signed commit.

## Review

Reviewer: weaker (devils-advocate), 2026-10-17. The `codex exec` preflight failed: both calls exited 1 within seconds with `ERROR: Your access token could not be refreshed because your refresh token was revoked` (`refresh_token_invalidated`). The run header's HARD RULE forbids spawning a subagent, so the reviewer agent ran the devils-advocate persona's two passes itself, citing only the workspace `/var/folders/wg/5ljlln2917j_gqp5gt85j8pr0000gn/T/tmp.Lw29cEx5jO/review`. That workspace holds no bundle, so no claim about a bundle offset could be checked. The "blind" pass was not structurally blind, because the same agent had already read the spec. Reconciliation also used rung-1 observations outside the workspace, cited below: the sibling specs, `/tmp/route-walk-src/walk.py` and REA's tool schema.

Blind pass (alternatives, missing requirements, seam, falsifiers):
- **reject.** Grade against the Layout capture's text alone and drop the bundle screenshots. The plan asks for the walk shot to be compared "with a REA capture of the same page" (plan:142). The screenshot is the only image-to-image comparison, and Phase 0 already serves the bundle. The text-only route stays as the "bundle did not render" fallback.
- **accept.** The other ~70 rows keep grades from `7f0b1c04` or earlier, so "the grades describe one real tree" (story 1) overclaims. Out of scope keeps them as they are, so Sign-off now carries a note line saying their grades predate this commit (Interfaces, the Sign-off section).
- **accept.** The §3.7 container row has exactly the two regraded children (matrix:204, "each screen is graded in its own 3.7 row"), and its grade would go stale. This Phase now owns its status (Owns; ASSUMPTION, rung 3).
- **accept.** REA's `capture_web_screenshot` requires `cdp_endpoint` and `target_id` and "never scrolls, navigates, or evaluates page JavaScript" (tool schema). So the spec's step 3, "open the page … with the local API mock", had no driver, and nothing set 1440×900. The steps now name `--window-size`, a Playwright `connect_over_cdp` driver with `page.route` mocks, `list_browser_targets`, and the viewport-only limit.
- **accept.** The recorded `infloww-parity-next-steps` and `route-walk` lines ran on the pre-grade matrix (Run order, steps 1–5 before step 7), so the regraded matrix was never checked by the recorded gate. Step 8 now reruns both after the grading, and their Sign-off lines come from that rerun (ASSUMPTION, rung 5).

Draft pass (where the spec is wrong):
- **accept.** This was the most severe finding: the spec assumed a separate "Auto mass messages" row and a new My Automations route. ADR-0014:7-9 predicts, and Phase 2b's spec decides (`phase-02b-auto-mass-messages.md:3`, `:138`), that mass messages stay in the bundle's Mass Messages tab on `/growth/smart-messages`, with no new route or row. The following were rewritten: the Objective, the Solution, stories 16, 17, 20 and 23, Owns, the Seam 1 sentence and Depends on (Phase 2b). §3.5.1 now grades both parent tabs, and the fallback is covered by the Acceptance's nav check.
- **accept.** Story 16 had no Acceptance check. It is now covered by the 3.5.1 entry in the row loop, plus the nav check for a `/growth/*mass*` route under the fallback.
- **accept.** Seven of the ten Labelled improvements words ('S4S', 'Shift', 'Not wired', 'Not applied yet', 'Phone', 'Auto Post', 'Auto Story') are already in HEAD's list (matrix:238-263), and 'Shift' matches the §3.8 entry, not the Dashboard shift cards. 'Auto delete' is not Phase 2b's wording ("Auto-unsend"), and Phase 5 checks "Google Drive import" (`phase-05-drive-import.md:102`). The words are now 'Google Drive import', 'Auto-unsend', 'Message online fans' and 'Mass Nudge', plus a conditional 'My shifts' check.
- **accept.** The "nothing changed since" diff excluded all of `.scratch/infloww-parity-round-2/`, so an edit to the gate itself (`suite.sh`) after sign-off would pass. `suite.sh` is now diffed on its own.
- **accept.** The suites run on the working tree, but the clean check skipped the inputs the run reads: `.scratch/*/suite.sh`, `docs/infloww-layouts/` and `docs/infloww-screens.md`. Run order step 0 and the Acceptance now check them.
- **partial.** Story 21's scan skipped `app/app/**` and any file that renders the label only through a wrapper. `app/app` is added. The wrapper case is left to the eye-regrade (ASSUMPTION, rung 5), because a grep for wrappers would be guesswork.
- **accept.** Existing Labelled improvements entries on rebuilt pages could go stale. For example, "Earnings by channel (§3.1)" cites `components/home/CompetitorReports.tsx:447`, and Phase 1 rebuilds `/`. This Phase now owns rechecking those entries (Owns).
- **partial.** The walk never empties `ROUTE_WALK_OUT` (`os.makedirs(OUT, exist_ok=True)`, `/tmp/route-walk-src/walk.py:252`), so a 2026-10-16 PNG can be cited by mistake. The grader now cites only shots in this run's `report.json`. No deletion is added, because floor 2 forbids it.
- **partial.** Both images are viewport-only (the REA schema; `page.screenshot` without `full_page`, walk.py:293, :314), so content below the fold is graded from the capture's text. A note is added under the screenshot steps. No full-page capture is added (YAGNI).
- **accept.** The precondition "and the diff isn't this effort's" can't be decided. It is now the same `git status --short docs/infloww-parity-matrix.md` test that Phase 0 (`phase-00-baseline-layout-capture.md:268`) and Phase 2b use.
- **reject.** Stories 19 and 30 (extension-first Add flow, no real names) have no check here. The Add flow is Phase 4's vitest. The mock table lives in `/tmp` and is never committed, so there is nothing committed to grep. The repo rule and the final manual step cover it.
- **accept.** The row loop checked only that the 2026-10-16 walk was absent. A row citing no fresh walk, or carrying any grade, passed. The loop now requires `the Route walk, <sign-off date>`, a grade of `matched`, `not wired` or `unverified`, and an issues-path reference on an `unverified` row.
- **reject.** The plan says "five effort suites" (plan:140), and the spec uses six. This is already flagged as an ASSUMPTION, and it matches Phase 0 (`phase-00-baseline-layout-capture.md:272`).
- **partial.** The previous plan's Phase 6 regraded every row (matrix header: "Phase 6 re-walks every route"), but this one regrades only nine. The re-walk still covers every route. Regrading is limited to the plan's eight pages and anything the walk contradicts, and the new Sign-off note makes the limit visible.

Six hats (2026-10-17, `.scratch/infloww-parity-round-2/review/six-hats.md`):
- SH1 **accept.** Only this Phase waits on the owner's commit, and only for its matrix steps (precondition, Depends on, ASSUMPTION); Phases 0–5 and 2b no longer do.
- SH7 **accept.** The grading rule now follows the matrix header: labelled extras only gives `intentionally improved`, and `matched` means no difference (Contracts, story 13, ASSUMPTION); the Acceptance's grade case accepts `intentionally improved`.
- SH9 **accept.** The Acceptance now verifies the recheck records: one per page with a proposed row, and 2b's section in the Smart Messages record (story 31).
- SH13 **accept.** This Phase alone edits the matrix: it copies `baseline.md` into `## Baseline run` (story 32, Owns) and regrades from the recheck records.
- SH18 **accept.** Grading fixed (SH7); the 2b offsets are corrected in Phase 2; ADR-0014 is amended in place by this run, and CONTEXT.md's glossary changes stay parked for its owner.

needs-human: the matrix ticket waits for the owner to commit the uncommitted `## Sign-off` (precondition). Rerun this review with `codex` after `codex login`. This review was in-process and not structurally blind. No material objection is left open.
