# Phase 06 — Sign-off

**Objective.** On the final code commit of this effort, every Acceptance block of this plan's Phases 0–5 and of the parent plan's Phases 1–7 exits 0, the flag-on sweep and the flag-off default run and sweep are green and fresh, and `docs/messages-pro-parity.md` is regraded at that commit with the Compare page as evidence. Colour is now graded (ADR-0010), and every Region still `partial` names its remaining px difference.

## Problem Statement

Phases 0–5 each change one Region and run their own checks. Nobody has yet checked the result as a whole on the last commit. Someone who knows Infloww needs proof that four things hold together: the parent plan's guarantees (the extras audit, the Geometry token module with no colour in it, three panes with no sideways scroll, the Split Inbox) survived the restyle; the Legacy flag still adds nothing inline; the 1440 and 390 shots look like Infloww; and the parity doc tells the truth. Today the parity doc is graded at `3126cbdd` and says "Colours are never graded (ADR-0001)". ADR-0010 has since made the Infloww palette the Messages Pro default, so the doc grades the wrong thing at an old commit.

## Solution

One sign-off pass, done by a single ticket that runs in order:

1. One default harness run on the final code commit, and a Visual loop on its shots against the Clone and the Infloww captures. Regressions found here are fixed in the component that owns them and committed. A difference still left after round three becomes a `VISUAL GAP:` line and a `differs` Compare row.
2. With the code final at commit `<sha>`, the Compare page is re-pinned to it: `Measured at`, the ours values, the Status cells and the Colour inventory's `<basename>:<line>` cells. Phase 0's own block, re-run below, checks the page against that commit.
3. `docs/messages-pro-parity.md` is regraded at the same `<sha>`. Colour is graded, the Compare rows are cited, and every partial Region cites its `differs` rows by ID next to the reference value and ours.
4. The Acceptance block then runs once and must exit 0: every Acceptance block of this plan's Phases 0–5 and of the parent's Phases 1–7 (the parent's `main` baseline replaced by the commit this effort started from), the flag-on sweep, the flag-off default run (the committed desktop and phone shots and both phone flows), the flag-off sweep, and the structural regrade checks.

## User Stories

1. As the human, I want every Acceptance block of this plan's Phases 0–5 re-run on the final commit, so that a later Phase did not quietly break an earlier one.
2. As the human, I want the parent plan's Acceptance blocks for Phases 1–7 re-run on the final commit, so that the restyle kept every guarantee the parity run signed off.
3. As the human, I want the parent's `service/` line read against the commit this effort started from, so that the line checks this effort and not the unmerged parent Phases stacked on the branch.
4. As the human, I want a parent Acceptance line that a binding decision of this plan makes impossible to pass to be named in the result with that decision, never silently skipped or edited, so that I can veto it.
5. As the human, I want a line that fails for any other reason to be treated as a regression and fixed in this Phase, so that sign-off does not hand broken code forward.
6. As an Employee who turns the Legacy flag on, I want the flag-on sweep green at 1440, 1280, 768 and 390, in the app and in the Pop-out window, so that the automation extras never cause sideways scroll, a clipped control or missing panes.
7. As an Employee who turns the Legacy flag on, I want the Chat header's Infloww icon row (Priority to Find) at the same x as with the flag off, so that the 44px flag-on shift recorded by ticket 127 is shown to be gone.
8. As someone who knows Infloww, I want the committed 1440×900 desktop shot to read as Infloww's Messages Pro: the Creator tabs row as the first row, the Infloww palette, 96px Fan List rows, the two-line Chat header, the bubble action row, date dividers and the three-row Composer. I also want the Inflowwww extras marked clearly.
9. As an Employee on a phone, I want the committed 390×844 Fan List and Thread shots to show one pane at a time, the per-bubble action row always visible and nothing cut off at the right edge, so that the phone layout survived the restyle.
10. As an Employee on a phone, I want the Composer's "+" overflow and the Fan insights slide-over measured on-screen at 390 by Phase 5's gated `phone-composer-overflow` flow, so that the two phone gaps ticket 127 recorded are confirmed closed on the final commit.
11. As the human, I want the default report (the seven shots, the `phone-popout` flow and the `phone-composer-overflow` flow) and the flag-off sweep (eight runs) asserted fresh and passing from this run, so that no stale PNG passes for a current one.
12. As the human, I want the committed PNGs and reports to come from the flag-off runs only, so that the repo shows the default product.
13. As the human, I want the Visual loop compared against the Clone's shot and, for look and feel, against the Infloww captures (read only, never committed, never quoted), so that the ground-truth order of the plan is followed.
14. As the human, I want every Compare row's matched state checked against the final shots and corrected where it is wrong, so that the Compare page is the evidence the regrade cites.
15. As the human, I want the parity doc's grading rules to grade colour against the Infloww palette under ADR-0010 instead of "never graded", so that the doc grades what this plan changed.
16. As the human, I want a Region to be `done` only when every Compare row for it reads matched and the parent's existing done rule also holds, so that an unmatched Compare row cannot hide behind a done status.
17. As the human, I want every `partial` row to name each remaining Geometry or Colour difference as the Clone's value next to ours, citing the Compare row's ticket. A Region that is partial only for non-visual reasons (Not wired, a "—" field, test-only) should say "no px difference remains", so that the plan's "names the remaining px difference" can be checked.
18. As the human, I want the parity doc's "Graded at" commit to be the code commit the run checked, with no change under `app/`, `scripts/` or `service/` after it, so that the grade cannot drift from the code.
19. As the human, I want every extra in the `EXTRAS` catalogue listed under "Ours" after the regrade, with the extras that Phases 2–5 moved described at their new placement (kebab, "+" overflow, Composer row 1 or the fourth row), so that the doc and the code agree and nothing we built is lost.
20. As the human, I want the Notifications toggle and the in-pane Notifications panel graded in the Fan List row. That covers their default, on and off states and where they are tested, so that the new control appears in the parity doc.
21. As the human, I want the parent's "Needs the human" items that this effort closed (the 44px flag-on shift, the 390 "+" overflow, the 11px Fan insights overhang) shown as resolved in their Region rows, and the rest carried forward, so that I know what is still mine.
22. As the human, I want a check that nothing from `~/Downloads` (Infloww captures, Infloww stylesheet) was committed by this effort, so that floor 2 and the plan's untrusted-input rule held.
23. As the human, I want the result to carry the summaries of both reports, every `VISUAL GAP:` line and every superseded Acceptance line, so that the coordinator's RUN.md can quote them.

## Implementation Decisions

- **Owns.** Two files are owned for real. One is `docs/messages-pro-parity.md`: its "Graded at" line, its preamble, its "How Regions are graded" section, its "Ours" entries and its "Parity table". The other is the Compare page `docs/screenshots/messages-pro-compare.md`, but only its `Measured at` line, its Status and Ours cells, its new `differs` rows for a VISUAL GAP the Visual loop leaves, and the Colour inventory's `<basename>:<line>` cells; the existing rows, their IDs and tickets belong to Phase 0 and to the Phases that own them. A third, narrow write: a superseded parent Acceptance line (below) is corrected in its parent spec, and nothing else in the parent specs. The PNGs and the two report JSONs under `docs/screenshots/` are regenerated by the harness and never edited by hand. A component under `app/components/chat/` or `app/app/messages-pro/` is touched only to fix a regression this pass finds. The fix is the smallest one that makes the failing line or shot pass, and it is made in the module the owning Phase changed.
- **Interfaces.** None change. The pass uses `scripts/ui-shots.sh` as it is (its default run, `UI_SHOTS_SWEEP=1`, and `OPENINFLOWW_LEGACY_AUTOMATIONS=1`), the extras catalogue `EXTRAS` in `app/lib/openinflowwwwExtras.ts`, and the Acceptance blocks of the specs as written.
- **Schema.** None.
- **Contracts.**
  - **Parity doc.** The structure that the parent Phase 7 awk check enforces stays exactly as it is: the `Graded at` line, an "Ours" entry per extra in the form `- **<name>** — <host>; <flag or overflow>; <what>.`, a row per Region with four filled cells and a status of done, partial or ours-only, and the table last. The 15 Regions stay; no Colour Region is added, because colour is graded inside each Region's row.
  - **Compare page.** Phase 0's contract, read as written: the `## Compare rows` table has seven columns `ID | Region | Difference | Clone px | Ours | Ticket | Status`, Status is `differs`, `matched` or `ours`, and the `## Colour inventory` table is not read by the grading parse. A Region cell names one or more parity-table Regions (case-insensitive, comma-separated). A `differs` row puts its Region at `partial`; an `ours` row (FL11) constrains nothing.
  - **Re-pin.** Phase 0's block checks `Measured at` against `app scripts service` and against `scripts/ui-shots.sh`, and checks the inventory's literal lines against the code. Re-pinning the page to the graded commit is what lets that block pass on the final commit, and the Acceptance asserts the two pins are the same commit.
  ASSUMPTION: rung 3 (Phases 1–5 already update the page's Ours and Status cells, Phase 0 spec's Contracts bullet). Overturned if the human wants `Measured at` left at Phase 0's commit, in which case Phase 0's block cannot pass after Phase 2 and is recorded as a `SUPERSEDED:` line instead.
- **Order of runs.** The Visual loop and the regrade come first, on a prior default run, so the block can run once against a pinned commit. Inside the block the order is fixed because each harness run deletes and rewrites its own outputs:
  1. The Acceptance blocks, this plan's Phases 0–5 first and then the parent's 1–7. Between them they run `pnpm -C app typecheck`, `lint` and `test:run` (each appears in 7 of the 13 blocks).
  2. The flag-on sweep, which is a check only. Its `messages-pro-1280.png` is copied to a temp path for story 7.
  3. The default run.
  4. The flag-off sweep.

  Steps 3 and 4 write the committed outputs (`docs/ui-shots.md`, sweep section, "the committed outputs come from the flag-off run").
- **Part C runs only when the Compare page carries its rows.** Step 1 pipes every block through `bash -e`, so no line in it may rely on a human skipping it. Phase 4's Part C check is guarded inside Phase 4's own block: it runs only when the Compare page carries owned Part C rows (TH7–TH9, Difference "Part C:", Phase 0), and a vetoed Part C leaves them `unowned`, so the guard skips it. Step 1 never runs it unconditionally, and the regrade still sees vetoed Part C rows as `differs`, so the Message list Region reads `partial` with them named.
- **Per-Phase Compare gates.** The re-run blocks of Phases 2–5 pass a FL, CH, TH or CP row that is `matched` or `differs` with `remaining: <n>px — <reason>` (Phase 0's Named remainder), the per-Phase form of the Partial rule below; only Phase 1's CO1–CO7 and SH1–SH2 must read `matched`.
- **Parent Phase 0 is not re-run.** The plan names Phases 1–7. The fresh-and-passing assertion over the seven default shots and the flows, taken from parent Phase 0's block, is repeated in this Phase's Acceptance with Phase 5's `phone-composer-overflow` flow added to the expected set. The self-test is not re-run, because Phases 1–5 add checks and one flow but do not change the harness's gate logic.
- **Baseline substitution.** Inside the re-run blocks, `"$(git merge-base HEAD main)"` is replaced by the parent of the commit that added `docs/plans/messages-pro-look-and-feel.md`.
  ASSUMPTION: rung 3, the same substitution ticket 120 used (`.scratch/messages-pro-parity/RUN.md:40`, `:62`). Overturned if the human wants the `main` baseline, in which case the `service/` lines fail until the branch merges.
- **Superseded lines.** A parent Acceptance line is superseded only when a binding decision of this plan (its "Decisions already made" or a Phase bullet) makes it fail. The case in view is a check that an element sits inline when this plan moved it into the kebab or the "+" overflow. Such a line is recorded in the result as a `SUPERSEDED:` line with the plan line that overrides it. The sign-off ticket then corrects that one line in the parent spec, ticket 130's precedent (`RUN.md:56`), so that the block exits 0. Every other failure is a regression and is fixed here.
  ASSUMPTION: rung 3 (ticket 130 corrected a stale parent line), even though the parent specs are otherwise read-only context. Overturned if the human wants superseded lines left red, in which case Acceptance step 1 names them and fails.
- **Grading rule change.** The Reference bullet of "How Regions are graded" drops "Colours are never graded (ADR-0001)". In its place, colour is graded against the Infloww palette per ADR-0010, using the Compare page's colour rows CO1–CO7, all of which must read `matched` (plan Phase 1). Messages Pro under the light theme is graded as Phase 1's spec states it. Typography is not graded by the shots: the harness stubs Google Fonts (`docs/ui-shots.md`), so a font difference is a Visual loop read, never a matched row by default.
- **Done rule.** The `done` bullet gains one condition: "no Compare row for the Region reads differs". The parent's existing conditions stay, and the Acceptance also refuses a `done` row whose Ours cell still says Not wired or VISUAL GAP.
- **Partial rule.** The `partial` bullet gains one requirement: the Ours cell cites every `differs` Compare row of the Region by its ID (for example `FL3`) with the reference value next to ours (px for Geometry, the hex value for colour) and the owning ticket, or reads "no px difference remains" when the Region has no `differs` row and is partial only for non-visual reasons. The reference value is the Clone's, or the capture's where the Compare row marks it "(wins)" (Phase 0's Clone px contract).
  ASSUMPTION: rung 5, the plan's "names the remaining px difference" read as a checkable phrase. Overturned if the human wants non-visual partials to carry no such phrase.
- **Evidence column.** Each Clone evidence cell adds the Compare page and the Compare rows of its Region. The Clone's `messages.html` lines stay.
- **Phone layout and Extras overflow** stay `ours-only`. Infloww still has no phone app, and the extras are still ours.
- **Infloww captures** rank first for look and feel and are read in the Visual loop, but they are never committed or quoted, and the Compare page and the parity doc cite the Clone's px, or the capture's px where Phase 0 marked it "(wins)", as a value only. Infloww has no phone app, so the 390 shots are compared against Phase 4's and Phase 5's phone rules, not against a capture.
- **Flag-on desktop.** The 44px shift is checked on the flag-on sweep's 1280 shot against the flag-off one.
  ASSUMPTION: rung 5. The 1280 sweep shot is the only flag-on Thread shot the harness makes without a new state, because the plan says the harness gains none. Overturned if the human wants a flag-on 1440 shot, which would be a new harness state.

## Testing Decisions

- **Seam.** One seam: this Phase's Acceptance block, run from the repo root. It drives the specs' own Acceptance blocks, the existing `scripts/ui-shots.sh` gates (overflow, clipped controls, panes, console errors, off-host requests, per-shot checks), and a structural check of the parity doc and the Compare page. No new vitest file. The external behaviour under test is already covered by the Phases' tests: the extras audit `app/app/messages-pro/extras.test.tsx`, the colour guard in `app/lib/messagesPro.test.ts`, and each Region's component tests. This Phase only requires that they all pass together on one commit.
- **The visual side** (does it read as Infloww at 1440 and 390?) is the Visual loop, a `# manual:` step done by the implementer reading the PNGs, as the parent plan's Visual loop is. It is not asserted in code; it is made checkable by its outputs: every remaining difference must be a `differs` Compare row, and step 4 then forces its Region to `partial` and the row's ID into the Ours cell. The 390 "+" and slide-over boxes are asserted in code by Phase 5's flow; only the flag-on 44px read stays purely manual (Phase 3's DOM-order test guards it in code).
- **Prior art.** Parent ticket 120 (Phase 6 sign-off: full block with the flag off and on, baseline substitution) and ticket 127 (Phase 7 sign-off: flag-on sweep, then default run, then the parity doc graded at a commit), both in `.scratch/messages-pro-parity/RUN.md`. The parent Phase 7 awk check over `docs/messages-pro-parity.md` is reused through re-running that block.

## Acceptance

Before this block runs (the sign-off ticket's work, in this order): one default `scripts/ui-shots.sh` run on the final code commit; the Visual loop (manual steps below) with any regression fixed in its owning module and committed; then, at that final code commit `<sha>`, re-pin the Compare page (`Measured at \`<sha>\``, ours values, Status cells, the Colour inventory's `<basename>:<line>` cells) and regrade `docs/messages-pro-parity.md` (`Graded at \`<sha>\``). The block then runs once and must exit 0 with no further edit.

```sh
set -eu
cd "$(git rev-parse --show-toplevel)"
# Prerequisite: venv/bin/python; in a git worktree, link the main checkout's venv first (Worktrees in docs/ui-shots.md).
test -x venv/bin/python
tmp=$(mktemp -d)
# The commit this effort started from: the parent of the commit that added its plan file.
BASE=$(git rev-parse "$(git log --format=%H --diff-filter=A -1 -- docs/plans/messages-pro-look-and-feel.md)^")
# The graded code commit: the parity doc and the Compare page are pinned to the same one, and no code changed after it.
sha=$(sed -n 's/^Graded at `\([0-9a-f]\{7,40\}\)`.*/\1/p' docs/messages-pro-parity.md)
msha=$(sed -n 's/^Measured at `\([0-9a-f]\{40\}\)`.*/\1/p' docs/screenshots/messages-pro-compare.md | head -1)
test -n "$sha" && test -n "$msha"
test "$(git rev-parse "$sha")" = "$msha"
git merge-base --is-ancestor "$sha" HEAD
git diff --quiet "$sha" -- app scripts service

# 1. Every Acceptance block: this plan's Phases 0-5, then the parent's Phases 1-7, main baseline -> BASE.
#    (Phase 4's Part C check guards itself on the Compare page's owned Part C rows, so a vetoed Part C skips, never fails.)
#    (They carry pnpm -C app typecheck, lint and test:run, the extras audit and the parent Phase 7 parity-doc check.)
test "$(ls docs/spec/messages-pro-look-and-feel/phase-0[0-5]-*.md | wc -l)" -eq 6
for f in docs/spec/messages-pro-look-and-feel/phase-0[0-5]-*.md docs/spec/phase-0[1-7]-*.md; do
  awk '/^## Acceptance/{a=1;next} a&&/^```sh$/{p=1;next} p&&/^```$/{exit} p' "$f" \
    | sed 's/"\$(git merge-base HEAD main)"/'"$BASE"'/g' > "$tmp/block.sh"
  test -s "$tmp/block.sh"
  echo "== $f"
  bash -e "$tmp/block.sh" || { echo "FAIL: $f"; exit 1; }
done

# 2. Flag-on sweep (check only; its exit code is the check). Keep its 1280 shot for the 44px manual check.
OPENINFLOWW_LEGACY_AUTOMATIONS=1 UI_SHOTS_SWEEP=1 scripts/ui-shots.sh
cp docs/screenshots/messages-pro-1280.png "$tmp/flag-on-1280.png"

# 3. Committed outputs, flag off: the default run (desktop and phone shots, both phone flows), then the sweep.
scripts/ui-shots.sh
UI_SHOTS_SWEEP=1 scripts/ui-shots.sh
venv/bin/python -I - <<'PY'
import json, os
want = ["messages-pro-desktop", "messages-pro-popout", "messages-pro-insights", "messages-pro-phone-list",
        "messages-pro-phone-thread", "messages-pro-composer-ppv", "clone-messages-pro"]
r = json.load(open("docs/screenshots/messages-pro-report.json"))
shots = {x["name"]: x for x in r["shots"]}
assert r["ok"] is True and sorted(shots) == sorted(want), sorted(shots)
flows = {f["name"]: f for f in r["flows"]}
# phone-composer-overflow is Phase 5's flow: the "+" panel and the Fan insights slide-over inside x 0..390 (story 10).
assert sorted(flows) == ["desktop-edit-name", "phone-composer-overflow", "phone-popout"], sorted(flows)
assert flows["phone-composer-overflow"]["viewport"] == [390, 844]
for x in list(shots.values()) + list(flows.values()):
    if "file" in x:
        assert os.path.getsize(x["file"]) > 0 and os.path.getmtime(x["file"]) >= r["startedAt"], x["file"]
    assert x["gated"] and not x.get("overflowX") and not x["consoleErrors"] and not x["offHostRequests"], x["name"]
    assert x["checks"] and all(c["ok"] for c in x["checks"]), x["name"]
s = json.load(open("docs/screenshots/messages-pro-sweep.json"))
assert s["ok"] and len(s["runs"]) == 8 and all(x["ok"] and not x["failures"] for x in s["runs"]), s
print("report ok=True shots=7 flows=3; sweep ok=True runs=8")
PY

# 4. The regrade: colour graded, Compare rows agree with statuses, partials cite their rows, extras listed.
venv/bin/python -I - <<'PY'
import re
doc = open("docs/messages-pro-parity.md").read()
assert "Colours are never graded" not in doc and "ADR-0010" in doc and "messages-pro-compare.md" in doc
sec = lambda t, h: t.split(h, 1)[1].split("\n## ", 1)[0]
cells = lambda l: [c.strip() for c in l.strip().strip("|").split("|")]
sep = lambda l: re.match(r"^\|[-: |]+\|$", l.strip())
rows = [cells(l) for l in sec(doc, "## Parity table").splitlines()
        if l.startswith("|") and not sep(l) and not l.startswith("| Region")]
status = {r[0].lower(): r[3] for r in rows}
ourscell = {r[0].lower(): r[2] for r in rows}
# Phase 0's contract: ## Compare rows is one table, ID | Region | Difference | Clone px | Ours | Ticket | Status.
page = open("docs/screenshots/messages-pro-compare.md").read()
cmp = [cells(l) for l in sec(page, "## Compare rows").splitlines()
       if l.startswith("|") and not sep(l) and re.fullmatch(r"[A-Z]{2}\d+", cells(l)[0])]
assert cmp, "no Compare rows"
differs = {}
for c in cmp:
    assert len(c) == 7 and c[6] in ("differs", "matched", "ours"), c
    regions = [x.strip().lower() for x in re.split(r",|/", c[1]) if x.strip()]
    for region in regions:
        assert region in status, "Compare row %s names no parity Region: %s" % (c[0], c[1])
        if c[6] == "differs":
            differs.setdefault(region, []).append(c[0])
# Plan Phase 1: every colour row reads matched.
co = [c for c in cmp if c[0].startswith("CO")]
assert len(co) >= 7 and all(c[6] == "matched" for c in co), [c[0] for c in co if c[6] != "matched"]
for region, st in status.items():
    if region in differs:
        assert st == "partial", "%s is %s with differing rows %s" % (region, st, differs[region])
    if st == "done":
        assert not re.search(r"Not wired|VISUAL GAP", ourscell[region]), "done Region keeps a gap: " + region
    if st == "partial":
        ids = differs.get(region, [])
        if ids:
            gone = [i for i in ids if not re.search(r"\b%s\b" % i, ourscell[region])]
            assert not gone, "partial %s does not cite its differing rows %s" % (region, gone)
        else:
            assert "no px difference remains" in ourscell[region], "partial names nothing: " + region
assert re.search(r"Notifications", ourscell["fan list"]), "Fan List row does not grade the Notifications toggle"
src = open("app/lib/openinflowwwwExtras.ts").read()
names = re.findall(r'name: "([^"]+)"', src.split("export const EXTRAS", 1)[1].split("] as const", 1)[0])
assert len(names) >= 21, names
ours = sec(doc, "## Ours")
missing = [n for n in names if "- **%s** —" % n not in ours]
assert not missing, missing
print("regrade ok: %d Regions, %d Compare rows, %d differing, %d extras" % (len(rows), len(cmp), sum(map(len, differs.values())), len(names)))
PY

# 5. Nothing from ~/Downloads entered the repo during this effort: no path names them, and no file added or
#    changed since BASE is byte-identical to a capture or an Infloww stylesheet/chunk (hashes only; nothing is executed).
test -z "$(git diff --name-only "$BASE" -- . | grep -E 'infloww-shots|infloww-asar' || true)"
test -z "$(git ls-files | grep -E 'infloww-shots|infloww-asar' || true)"
git diff --name-only --diff-filter=AM "$BASE" HEAD > "$tmp/changed.txt"
venv/bin/python -I - "$tmp/changed.txt" <<'PY'
import hashlib, os, sys
h = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
roots = [os.path.expanduser("~/Downloads/infloww-shots-2026-10-12"),
         os.path.expanduser("~/Downloads/infloww-asar/dist/preload/pages/of")]
bad = set()
for root in roots:
    for d, _, fs in os.walk(root):
        for f in fs:
            bad.add(h(os.path.join(d, f)))
hit = [p.strip() for p in open(sys.argv[1]) if p.strip() and os.path.isfile(p.strip()) and h(p.strip()) in bad]
assert not hit, hit
print("no capture or stylesheet copied: %d ground-truth files hashed" % len(bad))
PY

# manual (before the block, step "Visual loop"): Read docs/screenshots/messages-pro-desktop.png beside docs/screenshots/clone-messages-pro.png, and beside the Infloww captures in ~/Downloads/infloww-shots-2026-10-12/ (read only; never copy, commit or quote a name or handle). Per Region (Window header, Creator tabs, Fan tabs, Fan List, Chat header, Message list, Composer, Fan insights) write the visual diff (position, size, colour, label, order, missing element); fix regressions in the owning module and re-run, up to three rounds; record what remains as VISUAL GAP: lines with the reference value (the Clone's, or the capture's where the Compare row marks it "(wins)"), ours and the owning ticket, and as a `differs` Compare row.
# manual: Read docs/screenshots/messages-pro-phone-list.png and messages-pro-phone-thread.png (390x844): one pane at a time, the per-bubble action row visible without hover, nothing cut off at the right edge.
# manual: Read $tmp/flag-on-1280.png beside docs/screenshots/messages-pro-1280.png: the Chat header's Infloww icon row (Priority to Find) starts at the same x in both and no extra renders inline in that header (the 44px shift of ticket 127 is gone). Record a VISUAL GAP: line with both x values if not.
# manual: put the report and sweep summaries printed above, every SUPERSEDED: line and every VISUAL GAP: line in the Phase result, each manual read with its outcome (pass, or the VISUAL GAP: line it produced).
```

## Depends on

- **Phase 0 — Measure and pin**: the Compare page `docs/screenshots/messages-pro-compare.md` with every visible difference as a Compare row, and the Colour inventory. Its Acceptance block is re-run here.
- **Phase 1 — Colour and shell**: the Infloww palette in Messages Pro's JSX, the hidden Top bar with the moved controls, the colour rows matched, and the light-theme decision the grading rule follows.
- **Phase 2 — Fan List rows and header**: the 96px rows, the moved header controls, and the Notifications toggle graded in the Fan List row.
- **Phase 3 — Chat header**: the two-line header and the extras moved into the kebab and "+" overflow, which story 7 checks with the flag on.
- **Phase 4 — Thread and bubbles**: the bubble action row, date dividers, avatars and the restyled "Jumping to latest…" chip.
- **Phase 5 — Composer**: the three-row Composer, the PPV fourth row, and the gated `phone-composer-overflow` flow that asserts the on-screen "+" at 390 and the 390 Fan insights fit (story 10, Acceptance step 3).

## Out of Scope

- New harness states (a flag-on 1440 shot, a light-theme shot, open menus, the Notifications toggle off). The plan's Phase 0 says the harness gains no new state, and parent Decision G holds.
- Re-running parent Phase 0's self-test. No Phase of this plan changes the harness's gate logic, and the plan names parent Phases 1–7.
- A pixel-diff tool for the flag-on and flag-off shots. That would be a new dependency, and one manual read answers the one question.
- New Regions in the parity table, such as a Colour Region. Colour is graded inside each Region's row, and the parent Phase 7 check fixes the Region list.
- Closing the parent's "Needs the human" items this plan does not name (the Buys & tips rail overlap, the time formats, the Vault picker never opened in a browser, and the others). They are carried forward in their Region rows.
- Merging, pushing or committing. Floor 2 and the header leave committing to the coordinator.
- Re-measuring the Clone or the Infloww stylesheet. That is Phase 0's measurement work; this Phase only re-checks ours against it.

## Further Notes

- ASSUMPTION: re-running this plan's own Phase 0–5 Acceptance blocks on the final commit is added on top of the plan's "Phases 1–7 of the parent plan". Rung 3, since parent tickets 120 and 127 re-ran their own Phase's full block at sign-off, and "evidence never shrinks the goal". Overturned if the human wants only the parent blocks.
- The Compare parse follows Phase 0's spec (`docs/spec/messages-pro-look-and-feel/phase-00-measure-and-pin.md`, Interfaces: seven columns, Status `differs`/`matched`/`ours`, Region a glossary Region name). ASSUMPTION: rung 5, a Region cell that covers several Regions (a colour row) lists them comma-separated with the parity table's names. Overturned by Phase 0's page using another separator, in which case step 4's split follows it.
- ASSUMPTION: a Compare row's colour value counts as the "px difference" a partial row must name when the remaining gap is colour, written as the hex value. Rung 5. Overturned if the human wants colour gaps graded separately from px.
- ASSUMPTION: "phone and desktop shots" means the existing default run's 1440×900 `messages-pro-desktop` and 390×844 `messages-pro-phone-list` / `messages-pro-phone-thread`, plus the sweep's 1280 and 768. Rung 3 (the parent sign-offs used them). Overturned if the human wants a new 390 shot, which would be a new harness state.

## Review

codex, 2026-10-15. Blind call (no spec) and draft call, `codex exec --sandbox read-only`, reasoning high, both exited 0.

Blind call:
- B1 "done has no threshold" (plan :82-85): **reject**. The spec states the threshold in the Done and Partial rules, and Acceptance step 4 now asserts it per Region.
- B2 flag-on sweep does not prove every extra appears (ADR-0003, `docs/ui-shots.md:259-263`): **reject**. The flag-on presence of every extra is the extras audit `app/app/messages-pro/extras.test.tsx:4-5` (flag off and on), re-run inside the parent Phase 7 and this plan's blocks; the sweep only checks layout.
- B3 Visual loop not carried into sign-off (parent plan :50-59): **reject**. It is the first Solution step and a manual step of the block; the draft-call version of this finding (D1) is answered there.
- B4 `TopBar.tsx` / `AppShell.tsx` missing: **reject**. `ls app/components/TopBar.tsx app/components/AppShell.tsx` fails in the repo too; the brief's path list is stale, and this Phase touches neither.
- B5 seam at the rendered screen plus component tests: **reject** (agreement, no change). That is the spec's seam already.
- B6 the Clone can be wrong where captures disagree (`docs/infloww-screens.md:15-20`): **accept**. Partial rule, the captures bullet and the Visual loop step now take the reference value as the capture's where Phase 0 marked it "(wins)".
- B7 fonts are stubbed so typography parity is unproven (`docs/ui-shots.md:131-136`): **accept**. The Grading rule now says typography is not graded by the shots.
- B8 `unmatchedRequests` are recorded but not gated (`docs/ui-shots.md:199-223`): **reject**. Every state the Phase relies on has a per-shot check that is gated (step 3 asserts every check ok), and changing the gate logic is out of scope (plan Phase 0: the harness gains no state).

Draft call:
- D1 the visual checks are comments, so the block passes with visual parity broken: **partial**. The look-and-feel read stays manual, as the parent plan's Visual loop is. But its outputs are now checkable: every remaining difference must be a `differs` row, and step 4 forces that Region to partial and its ID into the Ours cell. The 390 "+" and slide-over boxes are now asserted in code through Phase 5's `phone-composer-overflow` flow, which the draft missed. The 44px read stays manual, with Phase 3's DOM-order test as its code guard.
- D2 colour grading not checked; the Phase 1 rerun precedes the Compare correction: **accept**. Step 4 asserts CO1–CO7 exist and read `matched`, and the regrade now happens before the block, which runs once.
- D3 the partial assertion takes any "px": **accept**. A partial Region must now cite each of its `differs` rows by ID, or read "no px difference remains" when it has none.
- D4 the `done` check does not keep the parent done rule: **accept**. A `done` Region may have no `differs` row, and its Ours cell may not say Not wired or VISUAL GAP. The rest of the parent rule (Gap tables, "—" fields) stays enforced by the parent Phase 7 block.
- D5 a third file owned (parent spec lines) after saying two: **accept**. Owns now names that narrow write, along with the Compare re-pin it also needed.
- D6 the Downloads check matches filenames only: **accept**. Step 5 also hashes every file added or changed since BASE against the capture and stylesheet directories. It only reads them, and nothing is executed.
- D7 no typecheck/lint/test:run in the block: **reject**. `grep -l "pnpm -C app typecheck"` (and `lint`, `test:run`) over the 13 re-run specs matches 7 each, and step 1 runs them all with `bash -e`. The Order of runs bullet now says so.
- D8 Notifications story unchecked: **partial**. Step 4 asserts the Fan List row names Notifications. The on and off states are tested by Phase 2's block, which is re-run. A toggle-off harness state stays out of scope (plan Phase 0).

Found while reconciling (self, not codex): the old step 3 asserted `flows == ["phone-popout"]`, which fails once Phase 5 adds its flow. Phase 0's block pins `Measured at`, which fails on the final commit unless the page is re-pinned. Both are fixed above.

### Six hats

Six-hats report, 2026-10-15 (`.scratch/messages-pro-look-and-feel/SIX-HATS.md`).

- White, step 1 runs Phase 4's "skip if vetoed" Part C block unconditionally under `bash -e`: **accept**. New decision "Part C runs only when the Compare page carries its rows": the guard sits in Phase 4's block (owned TH7–TH9 rows, Phase 0), so step 1 never runs it unconditionally and a veto skips it; step 1's comment says so.
- Black, typography can't be graded but earlier gates demanded `matched` for text-width rows: **accept**. The per-Phase gates now take Phase 0's Named remainder, which is this spec's Partial rule applied per Phase; the new "Per-Phase Compare gates" bullet records it. CO1–CO7 stay strict here too (step 4).
- Black, the `ui-shots.sh` pin in Phase 0's block: **reject** as a defect here. The Re-pin bullet already re-pins `Measured at` to the final commit before step 1, so Phase 0's block passes on it.
- Blue, this Phase won't fit one context window: **accept** (recorded in plan-review.md as tracer bullets: Visual loop and regression fixes; re-pin and regrade; the final block).
