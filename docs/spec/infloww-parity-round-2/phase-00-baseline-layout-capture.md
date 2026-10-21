# Phase 00 — Baseline on the merged tree, layouts captured with REA

**Objective.** `.scratch/infloww-parity-round-2/baseline.md` holds a round-2 baseline that names the `main` tip it ran on and carries one verbatim line per member of the sign-off set (OF Manager click-through and Route walk included), ready for Phase 6 to copy into the Parity matrix's `## Baseline run`; the recheck record that Phases 1–5 write per page (`.scratch/infloww-parity-round-2/rechecks/<page>.md`) has a fixed format; `TODO.md` lives at `docs/messages-pro-feedback-2026-10-16.md`, `docs/messages-pro-parity.md` no longer describes the removed Composer "+" overflow, and each of the eight round-2 pages has a Layout capture in `docs/infloww-layouts/<page>.md`, checked by a new `layouts` step in the effort suite, with the eight Clone pages fixed where they disagree with it.

## Problem Statement

The owner fast-forwarded `main` to the worktree branch (`5fb64b78`), and `7f0b1c04` fixed the one red that the merge caused. Even so, nobody has proved the merged tree green end to end. The last Sign-off (`docs/infloww-parity-matrix.md` › `## Sign-off`, partial, at `7f0b1c04`) records `of-mirror-check: not run` and `route-walk: not run`. The matrix's Baseline run still names pre-merge commits (`9026f3a8`, `766922d7`). The merge also left `TODO.md` at the repo root, and three rows of the Messages Pro parity doc still say the `phone-composer-overflow` flow measures a "+" overflow that TODO A2 removed. The bigger gap: Phases 1–5 have to rebuild eight pages to "match the bundle" (ADR-0013), but no document says what the bundle shows on those pages. Without such a document, no implementer can transcribe a layout and no reviewer can reject a difference. The Clone is the only written reference for those pages, and it is the reference that was wrong.

## Solution

An owner opening `.scratch/infloww-parity-round-2/baseline.md` finds a round-2 baseline paragraph. It names the tip sha and gives one `<name>: exit <code> :: <last line>` line for each of the five earlier Effort suites, this effort's suite, `run-tests` (recorded only, waived), the mirror check, `ui-shots`, the Settings walk, the OF Manager click-through and the Route walk. All of them ran on that sha, and the three browser walks ran against the dev server on 127.0.0.1:3001. This Phase does not edit the Parity matrix: Phase 6 copies the paragraph to the top of the matrix's `## Baseline run`, where the earlier entries stay below as history. Until then the next-steps suite stays red on exactly one line, the missing round-2 block, and nothing else. The repo root no longer has `TODO.md`. The same file, under git history, is now `docs/messages-pro-feedback-2026-10-16.md`. A first line in it explains that code comments still cite its items as "TODO.md A1"–"B2".

Under `docs/infloww-layouts/` there is one Layout capture per page: `dashboard`, `growth-smart-messages`, `growth-scripts`, `growth-vault-pro`, `growth-tracking-links`, `analytics-creator-reports`, `creators-manage` and `creators-proxy`. Each one is a Markdown file with a fixed shape. A header records the bundle's entry chunk, the method (rendered with REA or static), and the commands that reproduce it. After the header come the component tree, then an Items table that gives every tab, label, column, filter, button, empty state, spacing value and colour, each with a stable ID and a `<file> @<offset>` source. Then comes a Clone fixes table, and a Notes section for disagreements with the Inventory and for version drift. In `growth-smart-messages.md`, two more sections record the per-fan Triggers the bundle shows and where the bundle places automated mass messages and any auto delete. Each Clone page in `ui-redesign/infloww-exact/` that disagreed with its capture is edited to match, and each edit is listed in the capture. Phases 1–5 then transcribe from these files and cite item IDs, and their reviewers reject any difference that lacks the "Inflowwww extra" label.

## User Stories

1. As the owner, I want the round-2 baseline record to name the current `main` tip, so that every later Phase measures against the merged tree and not against pre-merge commits.
2. As the owner, I want the OF Manager click-through (`scripts/of-mirror-check/navigate.py`) rerun on the tip, so that the `not run` line left by the partial Sign-off at `7f0b1c04` has a real result beside it, which Phase 6 carries into the matrix.
3. As the owner, I want the Route walk (`/tmp/route-walk-src/walk.py`) rerun on the tip, so that every route's four shots and the matrix cross-check are known to hold after the merge.
4. As the owner, I want the three browser walks to run against the dev server for this tree on 127.0.0.1:3001, so that the walks exercise the same server I use and Next 16's one-dev-server-per-app-directory rule is not broken.
5. As the owner, I want the five earlier Effort suites, this effort's suite, the mirror check, `ui-shots` and the Settings walk rerun on the same sha, so that the baseline is one commit's complete sign-off set and not a mix of runs.
6. As the owner, I want the `run-tests` line recorded with its real exit code and marked as not a gate, so that my 2026-10-16 waiver stays visible while the evidence is still kept.
7. As the owner, I want each baseline line copied verbatim in the house form `<name>: exit <code> :: <last line>`, so that the baseline reads like the Sign-off section and nobody has to re-interpret it.
8. As the owner, I want the matrix's earlier Baseline run entries untouched by this Phase, and kept below the round-2 paragraph when Phase 6 adds it, so that the history of what ran before the merge is not lost.
9. As a maintainer, I want the baseline record shaped so that, pasted into the matrix, it satisfies the infloww-parity-next-steps matrix contract (no `walk ` line, and a `== .scratch/<effort>/suite.sh` block with one line per `step` for every `.scratch/*/suite.sh`, this effort's included), and I want the next-steps suite red on exactly that missing block and nothing else until Phase 6 pastes it, so that a new red there is still caught. It is red today because this effort's suite has no block.
10. As the owner, I want a red that the merge caused to be fixed in this Phase before the baseline is recorded, as `7f0b1c04` was, so that the baseline is green. I want any other red recorded verbatim and parked with its cause, so that this Phase does not grow into feature work.
11. As the owner, I want `docs/screenshots/messages-pro-*` and `app/next-env.d.ts` to be byte-identical to HEAD after `ui-shots` runs, so that running the baseline changes no tracked file.
12. As the owner, I want `TODO.md` moved with `git mv` to `docs/messages-pro-feedback-2026-10-16.md`, so that the repo root stays clean and the history of A1–B2 follows the file.
13. As a maintainer, I want the moved file to open with a line saying it was `TODO.md` and that code and script comments cite its items as "TODO.md A1"–"B2", so that the roughly 20 such comments still resolve without a code edit.
14. As the owner, I want the moved file to drop every real numeric id (the account id, the sandbox chat's id and the id in item B1; three 8-digit runs today) and every mention of the sandbox chat's name, so that a file under `docs/` follows the no-real-names rule. The rest of its content stays as written.
15. As a reviewer, I want `docs/messages-pro-parity.md`'s Composer, Fan insights and Phone layout rows (the plan's 62, 64, 66) to say what the `phone-composer-overflow` flow measures since `7f0b1c04` (the quick emojis in row 1 and the Send-at panel under ⏱), so that the parity doc matches the harness.
16. As a reviewer, I want the parity doc's other lines that still place an extra in the Composer's "+" rewritten (the Extras-overflow rule paragraph's "since ticket 147 the Composer's "+" is the last control of Composer row 1" sentence, Free previews, Quick emojis, At presets, and the Extras overflow row), so that no line describes a control that no longer exists. I also want the Fan List header's "+" left as it is, since it was not removed.
17. As a Phase 1–5 implementer, I want one Layout capture per page at a fixed path (`docs/infloww-layouts/<page>.md`, where `<page>` is the Clone file's base name), so that my Phase's spec and tickets can point at a file that exists before I start.
18. As a Phase 1–5 implementer, I want each capture's component tree written as an indented list in render order, so that I can place every panel, tab strip and table where the bundle places it.
19. As a Phase 1–5 implementer, I want every visible label recorded verbatim in English, so that I copy text and never paraphrase it.
20. As a Phase 1–5 implementer, I want tab order, table columns in order, filters, buttons, and each empty state's text recorded as separate items, so that each one can be graded separately.
21. As a Phase 1–5 implementer, I want spacing values (px) and colours (hex, plus the CSS variable when the bundle uses one) taken from the bundle's CSS, so that "matches" can be checked against a number.
22. As a reviewer, I want every item to cite its source as `<file> @<offset>` (a bundle chunk or CSS file and a decimal byte offset), so that I can reopen the exact bytes and check a disputed value.
23. As a Phase 1–5 implementer, I want every item to have a stable ID `<page>#<n>`, so that tickets, commits and matrix cells can cite the item an element came from.
24. As a Phase 2b implementer, I want `growth-smart-messages.md` to record where the bundle places automated mass messages, with sources, or "not found" with the exact `grep -F` commands that found nothing, so that my tab goes where the bundle puts it (ADR-0014's exception) or under My Automations.
25. As a Phase 2b implementer, I want the same capture to record whether any bundle chunk has an auto delete or unsend-after-time control, so that I know whether Auto delete is an Inflowwww extra (the ADR-0014 grep found none).
26. As a Phase 2 implementer, I want `growth-smart-messages.md` to list every per-fan Trigger the bundle shows, verbatim, in the bundle's order, with its source, so that I build only those Triggers and mark each one wired or Not wired.
27. As a Phase 2 implementer, I want the Smart Messages capture to record the bundle's send types and tab labels ("Automated Message", "Priority Mass Message", "OF Mass Message" at `index.9f50f370.js` @15735111 per ADR-0014), so that Phases 2 and 2b split the page from the same evidence.
28. As a Phase 5 implementer, I want `growth-vault-pro.md` to record the bundle's upload and import card (file drop and any link import), so that the Drive section is placed as the labelled extra below the bundle's file drop.
29. As a Phase 4 implementer, I want `creators-manage.md` to record the bundle's Add creator flow entry points, so that putting the extension first in that flow is a placement decision and not a guess.
30. As a reviewer, I want each capture's header to name the method used (`rendered`, meaning REA drove a real page served on 127.0.0.1, or `static`, meaning REA's chunk/module map plus `grep -F` on the chunks and CSS) and the reason, so that I know how far a value can be trusted.
31. As a later-Phase implementer, I want each capture's header to give the exact commands that reproduce it, so that "recheck against the bundle with REA before closing" means rerunning those commands and comparing Items.
32. As the owner, I want the bundle served only on 127.0.0.1, from a symlink tree under `/tmp` that maps the paths `index.html` asks for (`/35676908170/assets/<file>`) onto `~/Downloads/infloww-remote-web/`, with the server started from a directory outside the bundle, so that the bundle stays read-only and untouched.
33. As the owner, I want every request to a host other than 127.0.0.1 or localhost aborted during a rendered capture (fonts, Cookiebot, Infloww's APIs), so that no capture reads from a live system or leaves the machine. Where REA cannot abort such requests, I want the capture to use the static method.
34. As the owner, I want any mock for the SPA's API calls to live under `/tmp`, answer with synthetic data only and never be committed, so that a rendered capture needs no account.
35. As the owner, I want no key, token, credentialed URL, demo personal name or wholesale code copied into any capture, so that the untrusted bundle cannot leak through the docs.
36. As a maintainer, I want the effort suite to gain a `layouts` step that checks every capture against its format contract (header lines, sections, source cells, unique IDs, Smart Messages' extra sections, and a leak guard), so that a malformed or leaky capture fails the suite.
37. As a reviewer, I want each capture's Clone fixes table to list every disagreement between the Clone page and the bundle, giving what the Clone had, what the bundle has, and the item ID, so that I can see exactly where the Clone was wrong.
38. As a Phase 6 grader, I want the Clone pages in `ui-redesign/infloww-exact/` fixed to match their captures, so that the Route walk's `clone-<name>.png` shots, the relay's `/infloww` skin and any later reader of the Clone agree with the bundle.
39. As a Phase 1–5 implementer, I want each capture's Notes section to record where the bundle disagrees with the Inventory (`docs/infloww-screens.md`) or with a desktop Infloww capture, so that the control truth (Inventory) and the layout truth (bundle) never silently conflict (ADR-0013's version drift).
40. As a Phase 1–5 implementer, I want a mapping from each capture to its Phase and Parity matrix row, so that I know which capture is my input and which row my recheck record proposes.
41. As the owner, I want this Phase to leave the matrix untouched, so that grading happens once, in Phase 6, from the recheck records.
42. As the owner, I want nothing pushed, the worktree kept, the bundle never committed and `LIVE_TEST_HERE.md` untouched, so that the plan's out-of-scope lines hold.
43. As a Phase 1–5 implementer, I want one recheck record per page at a fixed path with a fixed shape, so that my REA recheck, its labelled differences and my proposed matrix row land where Phase 6 reads them, and nowhere else.

## Implementation Decisions

- **Owns.**
  - `.scratch/infloww-parity-round-2/baseline.md` (new): one paragraph and one text block. This Phase does not edit the Parity matrix (coordinator ruling, 2026-10-17).
  - The recheck record contract (Contracts, below). This Phase creates no recheck file.
  - `TODO.md`, which moves to `docs/messages-pro-feedback-2026-10-16.md`.
  - The Composer, Fan insights, Phone layout and Extras overflow rows of `docs/messages-pro-parity.md`, its Free previews, Quick emojis and At presets bullets, and the Composer "+" sentence of its Extras-overflow rule paragraph (line 23 today).
  - A new directory, `docs/infloww-layouts/`, holding eight Layout captures.
  - The eight Clone pages `ui-redesign/infloww-exact/{dashboard,growth-smart-messages,growth-scripts,growth-vault-pro,growth-tracking-links,analytics-creator-reports,creators-manage,creators-proxy}.html` (and their same-named `.js` only where a fix needs it).
  - The `layouts` step of `.scratch/infloww-parity-round-2/suite.sh`.
  - It modifies no `app/`, `service/` or `scripts/` file, with one exception: a merge-caused red fixed under User Story 10.

- **Interfaces.**
  - **Effort suite.** `.scratch/infloww-parity-round-2/suite.sh` keeps `typecheck`, `lint` and `vitest`. It gains `step layouts layouts_check`, a pure text check in the house style of the next-steps suite's `matrix` step: every problem prints one line, any output fails the step, and the last line on success is `layouts: <k> of 8 captured, contract holds`. The step does not read `~/Downloads`, so the suite runs on a machine without the bundle. It never calls another suite.
  - **Baseline record.** `baseline.md`'s paragraph begins exactly ``Round 2 baseline at `<sha>` `` (7–40 hex), states the date, the dev server (127.0.0.1:3001, reused or started by the run), and the order the members ran in. It is followed by a fenced ```` ```text ```` block with one line per member, in this order: `messages-pro-parity`, `of-manager-connectors`, `settings-tabs`, `messages-pro-look-and-feel`, `infloww-parity-next-steps`, `infloww-parity-round-2`, `run-tests`, `of-mirror`, `ui-shots`, `settings-check`, `of-mirror-check`, `route-walk`. Each line is `<name>: exit <code> :: <last output line>`, verbatim, and the same names as the Sign-off section's. No line in the block starts with `walk `.
    - After the member lines, the same block carries each of the six Effort suites' full output verbatim under its own `== .scratch/<effort>/suite.sh` line (one `<step>: exit <code> :: <last line>` per step), the house form of the existing Baseline run. These blocks are what Phase 6 pastes into the matrix: the next-steps `matrix` step loops over every `.scratch/*/suite.sh` and wants a block with a line for each of its `step`s (`.scratch/infloww-parity-next-steps/suite.sh`, the `for s in .scratch/*/suite.sh` loop). Running only that check on the tree today prints `baseline: no '== .scratch/infloww-parity-round-2/suite.sh' block`, so the next-steps suite stays red on that one problem until Phase 6 pastes a round-2 block (Phase 6 reruns the round-2 suite for it, because Phases 1–5 add steps). The round-2 block here must include the `layouts` line, which is why the `layouts` step exists before the baseline runs (Order, below).
  - **Walk scripts, unchanged and read-only.**
    - The Settings walk: `PORT=3001 ./venv/bin/python -I scripts/settings-check/walk.py`.
    - The OF Manager click-through: `PORT=3001 ./venv/bin/python -I scripts/of-mirror-check/navigate.py`. It addresses `localhost:<PORT>`, which reaches the same server.
    - The Route walk: `PORT=3001 ./venv/bin/python -I /tmp/route-walk-src/walk.py`. Output goes to `/tmp/route-walk`, with `report.json`.
    - `/tmp/route-walk-src/walk.py` exists today. If `/tmp` was cleared, it is recreated from previous-plan ticket 41 (`.scratch/infloww-parity-next-steps/issues/41-…md`) and never committed.
    - `scripts/ui-shots.sh` starts its own temp relay and `next dev` on free ports, so it runs before the three walks. Each walk is preceded by `curl -sf http://127.0.0.1:3001/`. A dropped server is restarted with `cd app && npx next dev --webpack -H 127.0.0.1 -p 3001` (log under `/tmp`), and that walk is rerun. The restart is recorded in the paragraph.
  - **Screenshot hygiene.** Before `ui-shots`, `docs/screenshots/messages-pro-*` are `cp -p`'d to a `/tmp` directory and copied back afterwards. `git restore` and `git checkout` are not used (repo rule). `app/next-env.d.ts` is restored by `ui-shots` itself.
  - **Moved feedback file.**
    - It is created with `git mv TODO.md docs/messages-pro-feedback-2026-10-16.md`.
    - Its new first line reads: `Formerly TODO.md at the repo root (moved 2026-10-17, infloww-parity-round-2 Phase 0). Code and script comments cite its items as "TODO.md A1"–"B2".`
    - The A1–B2 items keep their IDs and text. The only edits are that every run of 8 or more digits becomes a placeholder naming what it was (`<account id>`, `<chat id>`, `<id>`; three runs today, `grep -o -E '[0-9]{8,}' TODO.md | sort -u | wc -l` prints 3, on lines 18, 19 and 25), and every mention of the sandbox chat's name (3 today) becomes `the owner's sandbox chat`.
  - **Parity doc lines.** The `phone-composer-overflow` citations in the Composer (CP6), Fan insights (CP7) and Phone layout rows now say what the flow checks since `7f0b1c04`. That is the quick emojis after ⚙ in row 1 and the Send-at panel under ⏱, both on-screen at 390 (read the flow at `scripts/ui-shots.sh` around `"phone-composer-overflow"` and `docs/ui-shots.md`).
    - The Free previews, Quick emojis and At presets bullets name where TODO A2 put each one: Free previews inline in the PPV row whenever media is attached, Quick emojis in row 1 after ⚙, and the +5…+60 min presets under ⏱.
    - The Extras overflow row drops the Composer, which has had no overflow since A2. This matches `app/lib/openinflowwwwExtras.ts`'s own comment.
    - The rule paragraph's "since ticket 147 the Composer's "+" is the last control of Composer row 1, and since ticket 149 it opens on-screen at 390" sentence says instead that the Composer has had no Extras overflow since TODO A2, its extras sitting where the bullets above put them.
    - The Fan List header's "+" (the Broadcast bullet) is unchanged.

- **Schema.** None, because this Phase makes no data change. The Layout capture format below is a document contract, not a schema.

- **Contracts. The Layout capture format** (`docs/infloww-layouts/<page>.md`; `<page>` ∈ the eight Clone base names). The `layouts` step enforces it, and Phases 1–5 and 2b read it.

  ```text
  # Layout capture — <page>
  Bundle: ~/Downloads/infloww-remote-web/, entry `index.<8 hex>.js`
  Captured: <YYYY-MM-DD> at repo `<sha>`
  Method: rendered <w>x<h> | static — <one-clause reason>   (rendered names the viewport its px values came from)
  Reproduce: <the serve, REA and grep -F commands, one per line in a fenced sh block>
  Clone: ui-redesign/infloww-exact/<page>.html
  Phase: <label(s)> · Matrix row: <§ id>

  ## Component tree        indented "- " list in render order, each node ending in (<source>)
  ## Items                 | ID | Kind | Element | Value | Source |
  ## Clone fixes           | Item | Clone had | Bundle has | Clone edit |   ("None — <reason>" allowed)
  ## Notes                 Inventory or desktop-capture disagreements, version drift ("None — <reason>" allowed)
  ## Triggers              growth-smart-messages only: | ID | Trigger (verbatim) | Source |
  ## Mass messages placement   growth-smart-messages only: where automated mass messages and any
                            auto delete live, with sources, or "not found" plus the grep -F commands run
  ```

  - **ID.** `<page>#<n>`, where n counts up from 1 and is unique within the file. A recheck that changes an item keeps its ID. A new item takes the next free number.
  - **Kind.** One of `tab`, `label`, `column`, `filter`, `button`, `empty state`, `spacing`, `colour`, `layout`.
  - **Value.** The verbatim English label, a px value, or a hex value (with its CSS variable in backticks when the bundle uses one).
  - **Source.** `<file> @<offset>`, where file is a bundle file name (`index.<hex>.js|css`, `vendor.<hex>.js`, `utils.<hex>.js`, `index.html`, or another name in the bundle listing) and offset is a decimal byte offset. Several sources are separated by `; `. A rendered-only value (a computed px with no CSS rule found) cites `rendered <selector>` and is listed in Notes.
  - **Ordering.** Items appear in component-tree order, so the table reads top to bottom like the page.

- **Contracts. The recheck record format** (`.scratch/infloww-parity-round-2/rechecks/<page>.md`; `<page>` ∈ the eight capture names). It is the round's one place for REA recheck results and proposed matrix rows (coordinator ruling, 2026-10-17). The Layout captures stay pure bundle data and are never appended to, and no Phase 0–5 edits the Parity matrix. The file is created by the first Phase that rechecks the page, and each later Phase appends its own section:

  ```text
  # Rechecks — <page>
  ## Phase <label> — <YYYY-MM-DD> at `<sha>`
  ### REA                  the REA tools run (or the static citations), and the walk shots by /tmp path
  ### Differences          | Item | Capture | Ours | Disposition |   Disposition: fixed | not wired | Inflowwww extra at <where> | omission: <reason>
  ### Matrix row           the proposed cells (Visual evidence, Remaining gap, Matrix status) for Phase 6
  ### Labelled improvements   optional: one line per extra, in the matrix section's form
  ```

  - **Item** is the capture's `<page>#<n>` ID, or `—` for an element the capture lacks.
  - A difference with no Disposition is a review rejection. Phase 6 reads only this file for a row's regrade.

- **Capture method.**
  - **Serving.** A symlink tree is built under `/tmp/infloww-serve/`: `index.html` and `35676908170/assets/<each bundle file>` point into `~/Downloads/infloww-remote-web/`. This is needed because the bundle's `index.html` requests `/35676908170/assets/index.9f50f370.js` and similar paths, while the download is flat. The tree is served with `python3 -I -m http.server --bind 127.0.0.1 3401 --directory /tmp/infloww-serve`, started from `/tmp`.
  - **Rendered.** REA's `inspect_web_page`, `capture_web_screenshot` and `analyze_web_bundle` are pointed at `http://127.0.0.1:3401/`. Off-host requests are aborted as in User Story 33. The SPA's in-app routes come from the router table found in the chunk map.
  - **Static fallback.** This is the plan's fallback when the SPA blocks or REA cannot abort off-host requests. It uses REA's chunk/module map, then `grep -F` and byte-offset reads (`python3 -I`) on the chunks and CSS, starting from the page's route component and its i18n strings.
  - **Known limits (from the plan and the 2026-10-16 runs).** `analyze_web_bundle` needs a live page, and `recover_javascript_sources` needs Linux. Each capture states which method produced it.
  - **The Clone is never a source.** It is only compared against.

- **Capture → Phase map** (the input each later Phase transcribes from; all Phases also recheck their page against its capture before closing, into the page's recheck record):

  | Capture | Phase | Matrix row |
  |---|---|---|
  | `dashboard.md` | 1 | 3.1 |
  | `growth-smart-messages.md` | 2 (Smart Messages ticket); 2b reads `## Mass messages placement` | 3.5.1 |
  | `growth-scripts.md` | 2 | 3.5.5 |
  | `growth-vault-pro.md` | 2; 5 reads its import card items | 3.5.4 |
  | `growth-tracking-links.md` | 2 | 3.5.8 |
  | `analytics-creator-reports.md` | 3 | 3.4 Creator reports |
  | `creators-manage.md` | 4 | 3.7 Manage creators |
  | `creators-proxy.md` | 4 | 3.7 Custom proxy |

  Phase 6 compares each walk shot with the capture of the same page.

- **Clone fixes.** A Clone page is edited only where it disagrees with an item in its capture. The edit copies the item's value (label text, order, column, px, hex) and imports nothing from the bundle (no CSS block, no script). Each edit is one row in the capture's Clone fixes table. The relay serves the Clone at `/infloww` (`service/server.py`, `_INFLOWW_DIR`), and the Route walk shoots the eight pages as `clone-<name>.png`. Both pick up the edits with no code change.

- **Order inside the Phase.** The work runs in this order:
  1. Merge-caused fixes, if any.
  2. The `TODO.md` move and the parity lines (docs only).
  3. The `layouts` step. It has to exist before the baseline runs, because the next-steps `matrix` step wants a recorded line for every `step` of this effort's suite; added after the baseline, it would turn that suite red again.
  4. The eight captures with their Clone fixes. `growth-smart-messages` comes first because Phase 2b depends on its placement section.
  5. The baseline runs and its record, last, so that the recorded Route walk shoots the fixed Clone pages (`clone-<name>.png`) and the recorded `layouts` line reads 8 of 8. Steps 2–4 change no `app`, `service` or `scripts` file, so the baseline still measures the merged tree's code.

## Testing Decisions

- **Seam 1 (the one new seam): the effort suite's `layouts` step.** It checks external behaviour, meaning what a reader of `docs/infloww-layouts/` relies on, and does not check how a capture was made. For every present file it checks:
  - the file name is one of the eight;
  - the header lines `Bundle:`, `Captured:`, `Method: rendered|static`, `Clone:` and `Phase:` are present;
  - the sections `## Component tree`, `## Items`, `## Clone fixes` and `## Notes` are present, in that order;
  - the Items header is exact;
  - every Items row has 5 cells;
  - the ID matches `^<page>#[0-9]+$` and is unique;
  - the Kind is in the vocabulary;
  - the Source matches `<bundle file> @[0-9]+` (or `rendered <selector>`);
  - a `spacing` Value matches `[0-9.]+px` and a `colour` Value starts with `#` and 3, 4, 6 or 8 hex digits (User Story 21);
  - `growth-smart-messages.md` also has `## Triggers` and `## Mass messages placement`, the Triggers header is exactly `| ID | Trigger (verbatim) | Source |`, and every Triggers row has 3 cells, a unique `growth-smart-messages#<n>` ID shared with no Items row, and a well-formed Source;
  - `docs/infloww-layouts/` holds only `.md` files.

  The leak guard fails on any of these:
  - a URL with a query string, userinfo or `token|key|sig|auth` in it;
  - a `eyJ…` JWT-like run;
  - a base64-like run of 40 or more characters, meaning `[A-Za-z0-9+/]{40,}` (no `-`, `_` or `.` in the class, so hyphenated repo paths such as the `Clone:` line never trip it);
  - a backticked span longer than 200 characters (no wholesale code).

  Missing files are not a failure of the step. They show in its count, and the Acceptance requires all eight.
- **Seam 2 (existing, unchanged): the sign-off set itself.** That is the six Effort suites, `run-tests` (recorded only), `node scripts/of-mirror.mjs --check`, `scripts/ui-shots.sh`, the Settings walk, the OF Manager click-through and the Route walk. Phase 0 adds no test to them. Its evidence is their verbatim lines on one sha. The Route walk's matrix cross-check, and the next-steps suite's `matrix` step red on the missing round-2 block alone, together prove that the merged tree broke neither contract.
- No vitest or relay test is added, because this Phase changes no app or relay behaviour.
- **Prior art.**
  - The `matrix` step of `.scratch/infloww-parity-next-steps/suite.sh`: a pure text contract with a problems stream, and the shape copied here.
  - The previous Phase 6 Acceptance in `docs/spec/phase-06-sign-off-matrix.md`: the walk commands, the `report.json` freshness check and the `<name>: exit` greps.
  - Settings' bundle citations (`docs/spec/settings-tabs/phase-00-shell-tokens-blob.md`: `index.9fc9db54.css`, `SettingPage$2` in `index.9f50f370.js`).
  - ADR-0014's `index.9f50f370.js` offset citation.

## Acceptance

```sh
set -e   # `! cmd` lines carry `|| exit 1`: set -e ignores a negated pipeline
cd "$(git rev-parse --show-toplevel)"
BL=.scratch/infloww-parity-round-2/baseline.md
# 1. The sign-off set on the tip, strictly in sequence (run-tests is recorded, not gated: owner waiver 2026-10-16).
for e in messages-pro-parity of-manager-connectors settings-tabs messages-pro-look-and-feel infloww-parity-round-2; do
  sh ".scratch/$e/suite.sh"
done
# The next-steps suite is red only on its matrix step, and that step only on the round-2 block Phase 6 pastes.
NS=$(sh .scratch/infloww-parity-next-steps/suite.sh || true); echo "$NS"
! echo "$NS" | grep -v '^matrix: ' | grep -q ': exit [1-9]' || exit 1
P=$(grep -v '^matrix: ' /tmp/suite-matrix.log | grep -v '^$' || true)
test -z "$P" || test "$P" = "baseline: no '== .scratch/infloww-parity-round-2/suite.sh' block"
scripts/run-tests.sh || true
node scripts/of-mirror.mjs --check
SHOTS=$(mktemp -d); cp -p docs/screenshots/messages-pro-* "$SHOTS"/
c=0; scripts/ui-shots.sh || c=$?
cp -p "$SHOTS"/messages-pro-* docs/screenshots/
test "$c" -eq 0
test -z "$(git status --porcelain -- docs/screenshots app/next-env.d.ts)"
# 2. The three browser walks against the dev server for this tree on 127.0.0.1:3001 (reused if up, else started here).
up() { curl -sf -o /dev/null http://127.0.0.1:3001/; }
if ! up; then
  (cd app && exec npx next dev --webpack -H 127.0.0.1 -p 3001 >/tmp/r2-p0-next.log 2>&1) &
  NEXT_PID=$!; trap 'kill $NEXT_PID 2>/dev/null' EXIT
  i=0; until up; do i=$((i + 1)); test "$i" -lt 120; sleep 2; done
fi
STAMP=$(mktemp); sleep 1
up; PORT=3001 ./venv/bin/python -I scripts/settings-check/walk.py
up; PORT=3001 ./venv/bin/python -I scripts/of-mirror-check/navigate.py
up; test -f /tmp/route-walk-src/walk.py
PORT=3001 ./venv/bin/python -I /tmp/route-walk-src/walk.py
test /tmp/route-walk/report.json -nt "$STAMP"
python3 -I -c 'import json,os; r=json.load(open("/tmp/route-walk/report.json")); assert r["routes"] and all(c["ok"] for c in r["checks"]); assert all(len([p for p in x["shots"] if os.path.getsize(p)>0])>=4 for x in r["routes"])'
test -z "$(git ls-files 'scripts/route-walk*')"
# 3. The round-2 baseline record names a merged tip and carries one line per member; the matrix is untouched by this Phase.
R=$(sed -n '/^Round 2 baseline at `/,/^```$/p' "$BL")
SHA=$(echo "$R" | sed -n 's/^Round 2 baseline at `\([0-9a-f]\{7,40\}\)`.*/\1/p' | head -1)
test -n "$SHA"
git merge-base --is-ancestor 7f0b1c04 "$SHA"
git merge-base --is-ancestor "$SHA" HEAD
git diff --quiet "$SHA" HEAD -- app service scripts ui-redesign/infloww-exact docs/infloww-layouts .scratch/infloww-parity-round-2/suite.sh
echo "$R" | grep -q '^== .scratch/infloww-parity-round-2/suite.sh$'
echo "$R" | grep -q '^layouts: exit 0 :: layouts: 8 of 8 captured, contract holds'
for n in messages-pro-parity of-manager-connectors settings-tabs messages-pro-look-and-feel infloww-parity-round-2 of-mirror ui-shots settings-check of-mirror-check route-walk; do
  echo "$R" | grep -q "^$n: exit 0 :: ."
done
echo "$R" | grep -q '^infloww-parity-next-steps: exit [0-9]* :: .'
echo "$R" | grep -q '^run-tests: exit [0-9]* :: .'
! echo "$R" | grep -q '^walk ' || exit 1
! grep -qF 'Round 2 baseline at' docs/infloww-parity-matrix.md || exit 1
# 4. TODO.md moved, history kept, no real ids; the parity doc no longer describes the Composer "+" overflow.
test ! -e TODO.md
git ls-files --error-unmatch docs/messages-pro-feedback-2026-10-16.md >/dev/null
head -1 docs/messages-pro-feedback-2026-10-16.md | grep -q -F 'Formerly TODO.md'
for i in A1 A2 A3 A4 A5 B1 B2; do grep -q -F "**$i." docs/messages-pro-feedback-2026-10-16.md; done
! grep -q -E '[0-9]{8}' docs/messages-pro-feedback-2026-10-16.md || exit 1
! grep -q -F 'the "+" last in row 1' docs/messages-pro-parity.md || exit 1
! grep -q -F '"+" overflow' docs/messages-pro-parity.md || exit 1
! grep -q -F 'our "+" at the right' docs/messages-pro-parity.md || exit 1
! grep -q -F "Composer's \"+\"" docs/messages-pro-parity.md || exit 1
! grep -q -F 'Composer Extras overflow' docs/messages-pro-parity.md || exit 1
grep -q -F 'the "+" at the right end of the Fan List header' docs/messages-pro-parity.md
# 5. Eight Layout captures, each in contract, Smart Messages with its two extra sections; nothing of the bundle committed.
for p in dashboard growth-smart-messages growth-scripts growth-vault-pro growth-tracking-links analytics-creator-reports creators-manage creators-proxy; do
  test -s "docs/infloww-layouts/$p.md"
  grep -q "^Clone: ui-redesign/infloww-exact/$p.html" "docs/infloww-layouts/$p.md"
done
grep -q '^## Triggers' docs/infloww-layouts/growth-smart-messages.md
grep -q '^## Mass messages placement' docs/infloww-layouts/growth-smart-messages.md
sh .scratch/infloww-parity-round-2/suite.sh | grep -q '^layouts: exit 0 :: layouts: 8 of 8 captured, contract holds'
test -z "$(git ls-files | grep -E '(^|/)(index|vendor|utils)\.[0-9a-f]{8}\.(js|css)$')"
test -z "$(git ls-files | grep -F 'infloww-remote-web')"
# 6. Nothing pushed, the worktree kept.
test "$(git rev-list --count '@{u}..HEAD' 2>/dev/null || echo 1)" -ge 1
test -d <worktree>
# manual: open two captures beside their pages in the bundle (or the static sources) and spot-check five items each, including one colour and one spacing value, against the cited offsets.
# manual: skim every capture for any personal name or credential the leak guard cannot recognise.
```

## Depends on

No other Phase. The merge (`5fb64b78`) and the `ui-shots` fix (`7f0b1c04`) are already on `main` (`git merge-base --is-ancestor 5fb64b78 HEAD` succeeds).

No human action. This Phase writes no part of `docs/infloww-parity-matrix.md` (coordinator ruling, 2026-10-17), so the owner's uncommitted Sign-off section does not block it. The next-steps suite stays red today (`baseline: no '== .scratch/infloww-parity-round-2/suite.sh' block`) until Phase 6 pastes the round-2 block, and Acceptance §1 checks that this is its only red.

## Out of Scope

- Pushing, because floor 2 forbids it and the owner keeps everything local.
- Deleting the worktree `t3code-42e075ae`, which floor 2 does not allow. It is listed under "Needs the human" in the plan.
- Committing the bundle or any part of it, because it is untrusted input (ADR-0013). Captures quote values, not code.
- Live sandbox tests and `LIVE_TEST_HERE.md`, which belong to the owner and are left alone.
- Any edit to the Parity matrix, its Baseline run included. Phases 1–5 propose each row in their recheck records, and Phase 6 alone edits the matrix: it copies `baseline.md` into the Baseline run, regrades and signs (coordinator ruling, 2026-10-17).
- Changing any walk or harness script, including adding the eight pages' REA shots to the Route walk. The walks are evidence here and stay as they are (YAGNI). Phase 6 compares shots with captures by hand, as the plan says.
- Editing the "TODO.md A1"–"B2" comments in `app/` and `scripts/`. The moved file's first line resolves them, so editing about 20 code comments would buy nothing.
- Capturing pages other than the eight. Messages Pro keeps the Clone as its Geometry reference (ADR-0001), and Settings already measured the bundle (ADR-0009).
- Checking the bundle's version inside the suite, because the suite must run without `~/Downloads`. Each capture's `Bundle:` entry-chunk line is the version record.
- Fixing reds that the merge did not cause. They are recorded and parked (User Story 10).

## Further Notes

ASSUMPTION: the baseline lives in `.scratch/infloww-parity-round-2/baseline.md`, and this Phase makes no matrix edit at all; Phase 6 copies it into the matrix's `## Baseline run` (coordinator ruling 2, 2026-10-17, adopting six-hats 13; rung 4, since the matrix holds the owner's uncommitted `## Sign-off`, +25 lines, and Phase 6 regrades every row anyway). Overturned if the owner commits the Sign-off and wants the baseline in the matrix from Phase 0; then §3 reads the matrix's Baseline run and §1 puts the next-steps suite back under `set -e`.

ASSUMPTION: Phase 0 closes with the next-steps suite red on exactly one problem, the missing round-2 block, and the Acceptance pins that it is the only one (rung 1 for the cause, `for s in .scratch/*/suite.sh`, and observed 2026-10-17 on `cc8e1ef1` plus the working tree: `matrix: exit 1 :: matrix: 1 problem(s)` with that line alone in `/tmp/suite-matrix.log`, and `typecheck`, `lint`, `vitest` and `relay` exit 0; rung 4, a red that is pinned to one line still catches every new red). Overturned if the owner wants every suite green before Phase 1 starts; then the matrix paste moves from Phase 6 to Phase 0, after the owner commits the Sign-off.

ASSUMPTION: the recheck record format (`rechecks/<page>.md`, one `## Phase <label>` section per Phase, `### Differences` and `### Matrix row` inside) is coined here. Rung 3 for the path, which Phase 4's spec already used; rung 5 for the shape. Overturned if Phase 6's regrade needs a field the format lacks; then the format gains it before the first recheck is written.

ASSUMPTION: when Phase 6 pastes it, the round-2 baseline is a new paragraph at the top of `## Baseline run`, and the pre-merge entries stay below as history. It is not a rewrite. The next-steps suite's `matrix` step allows exactly 16 `walk ` lines and no new `## ` section (`.scratch/infloww-parity-next-steps/suite.sh:133-141, 20`), so additive is the only form that keeps it green (rung 1 for the constraint, rung 4 for the placement). Overturned if the owner wants the old entries removed.

ASSUMPTION: the baseline also records this effort's suite (`infloww-parity-round-2`) next to "the five effort suites" the plan names. It is green at `fda942e0` per the brief, and Phases 1–6 gate on it (rung 5, cheap and additive). Overturned if the owner wants exactly the previous Sign-off's set.

ASSUMPTION: "the OF Manager click-through" is `scripts/of-mirror-check/navigate.py` alone. Its README calls it the click-through, and the previous Phase 6 Acceptance ran only it under the `of-mirror-check` name (rung 3). Overturned if the owner wants `render.py`, `settings_values.py`, `writes.py` and the rest included, in which case each gets its own line.

ASSUMPTION: a red caused by the merge is fixed in this Phase before the baseline is recorded (house precedent `7f0b1c04`, rung 3). Any other red is recorded verbatim and parked for the human with its cause. The Acceptance's `exit 0` greps then fail visibly, and the Phase is not marked done. Overturned if the owner wants all reds fixed here.

ASSUMPTION: the Acceptance accepts any `SHA` with `7f0b1c04` as an ancestor and `app`, `service` and `scripts` equal to HEAD's. The commit that records the matrix necessarily differs from the sha that ran (house precedent: the Baseline run's "whose `app`, `service` and `scripts` equal…" wording, rung 3). Overturned if the owner wants the baseline on the exact recording commit.

ASSUMPTION: the bundle is served from a `/tmp/infloww-serve/` symlink tree, not with `--directory ~/Downloads/infloww-remote-web` as the plan writes it. The bundle's `index.html` requests `/35676908170/assets/<file>` while the download is flat (observed with `grep -o` on `index.html`; rung 1). The tree keeps the plan's intent: 127.0.0.1 only, started outside the bundle, bundle unmodified. Overturned if a check shows the SPA resolves its chunks some other way.

ASSUMPTION: port 3401 for the bundle server (rung 6). Any free port other than 3001 works. Overturned by a port clash.

ASSUMPTION: a rendered capture is allowed only if REA can abort every off-host request (fonts on `fe-static-assets`, Cookiebot, Infloww's APIs). Otherwise the capture uses the static method (rung 2, floor 2 "no network fetches", "no reads against live production"). Overturned if the owner allows the font requests, which carry no account data, in which case only the API calls must be blocked.

ASSUMPTION: the line numbers the plan names (62, 64, 66) are the Composer, Fan insights and Phone layout rows that cite the `phone-composer-overflow` flow. The lines at 31, 40, 41 and 67 also describe the removed Composer "+", so they are specced too because the evidence widens the work (rung 1, `grep -n -F '"+"' docs/messages-pro-parity.md`). The Fan List "+" at line 29 was not removed and stays. Overturned if the owner wants only the three rows touched.

ASSUMPTION: the moved feedback file replaces its real numeric ids (three 8-digit runs, observed with `grep -o -E '[0-9]{8,}' TODO.md | sort -u | wc -l`) and the sandbox chat's name with placeholders. The plan's product requirement (no real account names in docs) and its "keep its content" line are both rung 2, and the content kept is A1–B2's record, which the two identifiers do not change. Overturned if the owner wants the file byte-identical, in which case the Acceptance's `[0-9]{8}` line goes.

ASSUMPTION: code comments citing "TODO.md A1"–"B2" stay as they are, and the moved file's first line resolves them (rung 5). Overturned if a reviewer wants the comments repointed, which is a mechanical edit for a later ticket.

ASSUMPTION: the `layouts` step fails only on contract violations in files that exist and reports missing files in its count. The Acceptance requires 8 of 8. This keeps the suite green between capture tickets inside this Phase (rung 4). Overturned if the coordinator cuts the eight captures into one ticket, in which case the step can require all eight.

ASSUMPTION: the item ID form `<page>#<n>`, the Kind vocabulary and the capture's section names are coined here. Phases 1–5 are specced in parallel and cite captures only by path (rung 6). Overturned if a parallel spec names a different citation form, in which case the format changes before the first capture is written.

ASSUMPTION: the leak guard's thresholds (a base64-like run of 40 or more characters, a backticked span longer than 200 characters) come from no measurement. They are tight, and loosening them later is easy (rung 4). Overturned by a legitimate value that trips them.

ASSUMPTION: where the bundle's English label sits behind an i18n key, the capture records the English string and cites the string's offset, not the key's (rung 5). Overturned if a later Phase needs the keys.

ASSUMPTION: this Phase does not add the capture paths to the eight matrix rows' Visual evidence cells. That cell is regraded by Phase 6 from the recheck records, and the Capture → Phase map here is the index (rung 5). Overturned if the owner wants the citation in the matrix now.

## Review

Reviewer: blind call `codex` (exit 0, 2026-10-17); draft call `weaker (devils-advocate)`, 2026-10-17. The codex draft call failed postflight twice (exit 1, no output; `refresh_token_invalidated`, so codex needs a fresh `codex login`). The fallback persona ran inside this agent, confined to the workspace plus repo observations, because the header forbids spawning agents. Neither call could check bundle offsets: the bundle is not in the workspace.

Blind call (codex):
- B1 "The bundle is treated as truth before a drift rule exists" (ADR-0013:5-9). **reject**: ADR-0013 is binding and says a disagreement is recorded as version drift. The capture's `## Notes` section does exactly that.
- B2 "Workspace HEAD `cc8e1ef1` is not `5fb64b78`". **reject**: `git merge-base --is-ancestor 5fb64b78 HEAD` succeeds, and the Acceptance already accepts any descendant of `7f0b1c04`.
- B3 Alternative: a narrower baseline that marks missing gates "unavailable". **reject**: plan Work 1 names the full set and is binding. The suites exist in the repo (`ls .scratch/*/suite.sh` lists six); the workspace just lacks them.
- B4 Alternative: keep the runtime baseline and the visual capture separate. **partial**: the spec already orders them apart. The order is now reversed (baseline last), for D2/D3's reasons.
- B5 Alternative: use the Clone as a provisional reference. **reject**: ADR-0013 rejects the Clone for these eight pages.
- B6 Missing: the result format, and whether the new run appends to or replaces the old one. **reject**: Interfaces › Baseline record fixes the format, and the additive ASSUMPTION fixes the placement.
- B7 Missing: a bundle identity and a drift decision. **reject**: the `Bundle:` entry-chunk header line records the identity, `## Notes` records drift, and ADR-0013 decides drift.
- B8 Missing: loading, error and keyboard states (matrix header line 13). **reject**: the matrix already assigns those to walk flows and code. A capture claims static layout only.
- B9 Missing: a completeness check of every Inventory control against the capture. **reject**: plan line 8 keeps the Inventory as control truth and leaves grading to Phases 1–5 (User Story 41). `## Notes` records the disagreements.
- B10 Missing: viewport and theme coverage. **partial**: the `Method:` line now names the viewport of a rendered capture (`rendered <w>x<h>`). A theme matrix is not added: the px and hex values come from CSS rules, and the plan asks for one capture per page (YAGNI).
- B11 Seam: compare the rendered routes with the captures. **reject**: the plan gives that comparison to Phase 6, by hand (Out of Scope).
- B12 Seam: behaviour tested through mocked relay responses. **reject**: Phase 0 changes no app or relay behaviour.
- B13 Seam: check each value against its bundle offset. **partial**: the suite must run without `~/Downloads`, so this stays as the Reproduce commands plus the manual spot-check line. No rewrite.
- B14 Falsifier: a Route walk failure after the merge. **reject**: the Acceptance already gates on `report.json`'s checks and shots.

Draft call (weaker, devils-advocate):
- D1 The next-steps `matrix` step is red today, and the spec's one-line-per-member block does not fix it. Running only the `matrix_check` on the tree prints `baseline: no '== .scratch/infloww-parity-round-2/suite.sh' block`, because of the `for s in .scratch/*/suite.sh` loop in `.scratch/infloww-parity-next-steps/suite.sh`. That falsifies the old User Story 9 ("stays green"). **accept**: the Baseline record now also carries every suite's per-step output under `== .scratch/<effort>/suite.sh` lines. User Story 9 and the Acceptance (the `== …round-2` and `layouts:` greps) were rewritten to match.
- D2 Adding `step layouts` after the baseline would turn the next-steps suite red again, because the matrix step wants a line for every `step`. **accept**: Order now puts the `layouts` step before the baseline.
- D3 The Clone fixes ran after the baseline, so the recorded Route walk shot the unfixed `clone-<name>.png`, and the `git diff` check skipped `ui-redesign`. **accept**: the baseline now runs last, and the diff check covers `ui-redesign/infloww-exact`, `docs/infloww-layouts` and the round-2 `suite.sh`.
- D4 `TODO.md` holds three distinct 8-digit runs (`grep -o -E '[0-9]{8,}' TODO.md | sort -u | wc -l` → 3, on lines 18, 19 and 25) and the sandbox name three times. The spec allowed replacing one id only, while its `[0-9]{8}` guard would fail on the other two. **accept**: User Story 14, the Moved feedback file decision and its ASSUMPTION now cover every id and every mention of the name.
- D5 Parity doc line 23 still says "the Composer's "+" is the last control of Composer row 1". No decision owned that line, and no grep caught it. `Composer Extras overflow` (lines 31, 40, 41) would also survive the Acceptance. **accept**: line 23 added to Owns, User Story 16 and Parity doc lines, plus two negative greps.
- D6 The seam left User Stories 21 and 26 untested: spacing and colour Values, and the Triggers table shape. **accept**: Seam 1 now checks the `px` and hex Value forms and the exact Triggers header, cells, IDs and Sources.
- D7 The leak guard's "base64-like" class was undefined. A class that includes `-` would trip on `Clone: ui-redesign/infloww-exact/analytics-creator-reports.html`. **accept**: the class is pinned to `[A-Za-z0-9+/]{40,}`.
- D8 "Depends on: None" is false. The matrix holds the owner's uncommitted edits (` M`), the header forbids touching the file, and D1 shows the next-steps suite can only go green through a matrix edit. **accept**, and **needs-human**: Depends on now names the owner action. One position: the run waits and parks the baseline in `.scratch/infloww-parity-round-2/baseline.md`, which is reversible. The other: the run edits the matrix on top of the owner's Sign-off, which is faster. What settles it: the owner commits the Sign-off section or releases the file.
- D9 The "nothing pushed" check passes whenever there is no upstream (`|| echo 1`). **reject**: without an upstream there is no tracked remote to have pushed to, and floor 2 already forbids pushing. The check is weak but adequate.
- D10 The Acceptance never checks the Fan insights row (line 64) rewrite. **reject**: the new wording has no fixed literal to grep for. The row still cites `phone-composer-overflow`, which is the flow's real name (`scripts/ui-shots.sh:1574`), so a grep could not tell old wording from new. Reviewer reading covers it.

Six hats (2026-10-17, `.scratch/infloww-parity-round-2/review/six-hats.md`):
- SH1 **accept.** Phase 0 no longer waits on the owner's Sign-off. The baseline goes to `.scratch/infloww-parity-round-2/baseline.md`, §1 runs the next-steps suite outside `set -e` and pins its one known red, §3 reads `baseline.md`, and Depends on drops the human action (Objective, Solution, stories 1, 8, 9, 11, Owns, Interfaces, Acceptance, Depends on, Out of Scope, ASSUMPTIONs). D8's needs-human is superseded by coordinator ruling 2: nothing in Phase 0 touches the matrix, so there is nothing left for the owner to release here.
- SH9 **accept.** One recheck location for the round: Contracts now fix the recheck record format at `.scratch/infloww-parity-round-2/rechecks/<page>.md` (story 43), the captures stay pure bundle data, and Phase 6 verifies one record per page.
- SH10 **accept** (no change). The capture contract is kept as written; the recheck record reuses its `<page>#<n>` IDs.
- SH13 **accept.** No matrix edit in Phases 0–5 (coordinator ruling 2); Phase 6 copies the baseline, regrades and signs.
